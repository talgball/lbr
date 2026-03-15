"""
Robot AI service - bridges between lbrsys and the OpenAI platform.

This service sits above the rest of the system architecturally, wired to the
executive via JoinableQueues.  It receives telemetry and AI requests on its
commandQ and sends robot commands back through its broadcastQ, which the
executive's monitor thread dispatches through normal type-based routing.

The service uses the OpenAI Responses API with function calling (tools) so the
model can issue structured robot commands (move, stop, speak, turn, etc.) that
are translated to the same command strings used by the console and HTTP service.

Multi-turn conversation state is managed server-side via previous_response_id.
For multi-step tasks (navigation), the service runs a sense-act loop: execute
tool calls, wait for movement to complete (zero motor current), inject updated
telemetry, and send the next turn to the model.
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2009-2026 Tal G. Ball"
__license__ = "Apache License, Version 2.0"
__version__ = "2.0"

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.


import os
import sys
import io
import time
import json
import math
import logging
import multiprocessing
import threading
import queue
import base64
import urllib.request
import ssl

from lbrsys import (ai_request, feedback, exec_report, mic_audio,
                     set_process_title, robot_move_config, robot_ai_notes)
from lbrsys.settings import aiLogFile

proc = multiprocessing.current_process()

if proc.name == "Robot AI Service":
    logging.basicConfig(
        level=logging.INFO,
        filename=aiLogFile,
        format='[%(levelname)s] (%(processName)-10s) %(message)s',
    )
    set_process_title()


# Maximum iterations in the sense-act loop to prevent runaway API calls
MAX_SENSE_ACT_ITERATIONS = 20

# How long to wait for movement to complete before timing out (seconds)
MOVEMENT_COMPLETE_TIMEOUT = 60.0

# How often to check for movement completion (seconds)
MOVEMENT_POLL_INTERVAL = 0.25


SYSTEM_PROMPT = """You are the AI reasoning layer for a mobile robot called {robot_name}.
You sit above the robot's executive system and can observe sensor telemetry
and issue commands to all subsystems (motors, speech, camera, etc.).

Your current sensor state is provided below.  When asked to act, use the
available tools to issue robot commands.  You can call multiple tools in
sequence if needed.

When you have a text response for the operator, use the speak tool to say it
through the robot's speech system, or the report tool to send it as a text
report to the console.

If camera images are attached, they show the current view from the robot's
active camera. Use them to understand the robot's surroundings when relevant.

SAFETY CONSTRAINTS:
- Always use bounded movements. Every navigate() call MUST include a range
  and/or duration limit. Never issue open-ended movement commands.
- Default power level is 0.25 (25%) unless the operator specifies otherwise
  or you determine a lower level is warranted (e.g., tight spaces, nearby
  obstacles, low visibility).
- After issuing a movement command, you will receive updated telemetry when
  the movement completes. Use this to verify progress before issuing the
  next command.

PHYSICAL CONFIGURATION:
- Wheel diameter: {wheel_diameter} cm
- Encoder counts per revolution: {counts_per_rev}
- Distance per encoder count: {cm_per_count:.4f} cm
- To calculate distance from encoder counts:
  distance_cm = counts * {cm_per_count:.4f}

{robot_notes}

Current robot state:
{state}
"""


ROBOT_TOOLS = [
    {
        "type": "function",
        "name": "move",
        "description": "Move the robot with specified power level and angle. "
                       "Level is 0.0 to 1.0 (fraction of max power). "
                       "Angle is degrees: 0=forward, 90=right, 180=backward, 270=left. "
                       "WARNING: This does not stop automatically. Prefer navigate() "
                       "with range/duration limits for safety.",
        "parameters": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "number",
                    "description": "Power level from 0.0 to 1.0"
                },
                "angle": {
                    "type": "integer",
                    "description": "Direction in degrees (0=forward)"
                },
            },
            "required": ["level", "angle"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "stop",
        "description": "Stop all movement immediately.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "speak",
        "description": "Say something through the robot's speech system.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The text to speak"
                }
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "turn",
        "description": "Execute a turn by specified degrees. "
                       "Positive = clockwise, negative = counter-clockwise.",
        "parameters": {
            "type": "object",
            "properties": {
                "angle": {
                    "type": "number",
                    "description": "Degrees to turn"
                }
            },
            "required": ["angle"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "navigate_to_heading",
        "description": "Turn to face an absolute compass heading (0-360 degrees).",
        "parameters": {
            "type": "object",
            "properties": {
                "heading": {
                    "type": "number",
                    "description": "Target compass heading in degrees"
                }
            },
            "required": ["heading"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "navigate",
        "description": "Move the robot with specified power, angle, range, sensor, "
                       "and/or duration. This is the preferred movement command. "
                       "The robot will stop automatically when the range or duration "
                       "limit is reached. Always specify at least a range or duration.",
        "parameters": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "number",
                    "description": "Power level from 0.0 to 1.0 (default 0.25)"
                },
                "angle": {
                    "type": "integer",
                    "description": "Direction in degrees (0=forward)"
                },
                "range": {
                    "type": "integer",
                    "description": "Distance limit in cm (0 = no limit)"
                },
                "sensor": {
                    "type": "string",
                    "description": "Range sensor direction to monitor: "
                                   "Forward, Back, Left, or Right",
                    "enum": ["Forward", "Back", "Left", "Right"],
                },
                "duration": {
                    "type": "integer",
                    "description": "Time limit in seconds (0 = no limit)"
                },
            },
            "required": ["level", "angle", "range", "sensor", "duration"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "report",
        "description": "Send a text report to the robot's console/operator. "
                       "Use this for information that should be displayed, not spoken.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The report text"
                }
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

# Tools that trigger robot movement and require waiting for completion
MOVEMENT_TOOLS = {'move', 'navigate', 'turn', 'navigate_to_heading'}


def execute_tool_call(tool_name, arguments, broadcastQ):
    """Translate an OpenAI tool call into a robot command string and enqueue it."""
    command = None

    if tool_name == "move":
        level = float(arguments["level"])
        angle = int(arguments["angle"])
        command = "/r/%.2f/%d" % (level, angle)

    elif tool_name == "stop":
        command = "/r/0/0"

    elif tool_name == "speak":
        message = arguments["message"]
        command = "/s/%s" % message

    elif tool_name == "turn":
        angle = float(arguments["angle"])
        command = "/t/%.1f" % angle

    elif tool_name == "navigate":
        level = float(arguments["level"])
        angle = int(arguments["angle"])
        range_limit = int(arguments.get("range", 0))
        sensor = arguments.get("sensor", "Forward")
        duration = int(arguments.get("duration", 0))
        command = "/r/%.2f/%d/%d/%s/%d" % (level, angle, range_limit,
                                            sensor, duration)

    elif tool_name == "navigate_to_heading":
        heading = float(arguments["heading"])
        command = "/h/%.1f" % heading

    elif tool_name == "report":
        message = arguments["message"]
        broadcastQ.put(exec_report('ai_report', message))
        logging.info("AI report: %s" % message)
        return "Report sent to console."

    if command:
        logging.info("AI executing command: %s" % command)
        broadcastQ.put(command)
        return "Command sent: %s" % command
    else:
        logging.warning("Unknown tool call: %s" % tool_name)
        return "Unknown tool: %s" % tool_name


def _format_robot_notes(notes):
    """Format robot AI notes for inclusion in the system prompt."""
    if not notes:
        return ""
    lines = ["ROBOT-SPECIFIC NOTES:"]
    for category, note in notes:
        lines.append("- [%s] %s" % (category, note))
    return "\n".join(lines)


class RobAIService:
    def __init__(self, commandQ=None, broadcastQ=None):
        print("Process Name is %s" % multiprocessing.current_process().name)
        self.commandQ = commandQ
        self.broadcastQ = broadcastQ
        self.client = None
        self.model = None
        self.state = {}
        self.last_response_id = None

        self.setup_client()
        self.start()

    def setup_client(self):
        """Initialize OpenAI client from environment variables."""
        try:
            from openai import OpenAI
            api_key = (os.environ.get('ROBOT_OPENAI_API_KEY')
                       or os.environ.get('OPENAI_API_KEY'))
            if not api_key:
                logging.error("Neither ROBOT_OPENAI_API_KEY or "
                              "OPENAI_API_KEY are set")
                print("Warning: ROBOT_OPENAI_API_KEY not set - AI service "
                      "will not be able to process requests")
                return

            self.client = OpenAI(api_key=api_key)
            self.model = os.environ.get('ROBOT_OPENAI_MODEL', 'gpt-5.2')
            logging.info("AI service initialized with model: %s (Responses API)"
                         % self.model)
            print("AI service initialized with model: %s (Responses API)"
                  % self.model)

        except ImportError:
            logging.error("openai package not installed")
            print("Warning: openai package not installed - "
                  "AI service unavailable")
        except Exception as e:
            logging.error("Error initializing AI client: %s" % str(e))
            print("Warning: Error initializing AI client: %s" % str(e))

    def start(self):
        """Main loop - blocks on commandQ, dispatches by message type."""
        ta = time.asctime()
        logging.info("%s: Starting AI Service" % ta)

        while True:
            task = self.commandQ.get()

            if task == 'Shutdown':
                logging.info("Shutting down AI Service")
                print("Shutting down AI Service")
                self.commandQ.task_done()
                break

            self.process_task(task)
            self.commandQ.task_done()

        self.end()

    def process_task(self, task):
        """Route incoming messages by type."""
        if type(task) is ai_request:
            self.handle_request(task)
        elif type(task) is feedback:
            self.update_state_from_feedback(task)
        elif type(task) is mic_audio:
            self.handle_audio(task)
        elif type(task) is exec_report:
            self.update_state_from_report(task)
        elif type(task) is dict:
            self.update_state_from_dict(task)
        elif type(task) is str:
            logging.debug("AI service received string: %s" % task)
        else:
            logging.debug("AI service received unknown type: %s %s" %
                          (type(task).__name__, str(task)))

    def handle_request(self, request):
        """Send prompt to OpenAI with robot state context and tool definitions.

        Runs the API call in a worker thread so the main loop can continue
        processing telemetry updates while waiting for the response.
        """
        if not self.client:
            msg = "AI client not available - cannot process request"
            logging.warning(msg)
            self.broadcastQ.put(exec_report('ai', msg))
            return

        # Handle reset command
        if request.prompt.strip().lower() == 'reset':
            self.last_response_id = None
            msg = "AI conversation reset"
            logging.info(msg)
            print(msg)
            self.broadcastQ.put(exec_report('ai', msg))
            return

        logging.info("AI request: %s" % request.prompt)
        print("AI processing: %s" % request.prompt)

        # Run the API call in a thread to avoid blocking telemetry processing
        t = threading.Thread(
            target=self._call_openai,
            args=(request,),
            name="AI-Request-Thread"
        )
        t.daemon = True
        t.start()

    def handle_audio(self, audio_msg):
        """Handle incoming mic_audio messages.

        Transcribes audio via OpenAI Whisper, then passes the transcript
        through the normal AI request pipeline for reasoning and action.
        """
        logging.info("Received audio: %.1fs, source=%s, %d bytes" %
                     (audio_msg.duration, audio_msg.source,
                      len(audio_msg.audio_data)))
        print("AI service received audio: %.1fs from %s" %
              (audio_msg.duration, audio_msg.source))
        self.state['last_audio'] = {
            'duration': audio_msg.duration,
            'source': audio_msg.source,
            'size': len(audio_msg.audio_data),
            'time': time.asctime(),
        }

        if not self.client:
            logging.warning("AI client not available - cannot transcribe audio")
            return

        # Run transcription in a thread to avoid blocking the main loop
        t = threading.Thread(
            target=self._transcribe_and_process,
            args=(audio_msg,),
            name="AI-Transcribe-Thread",
        )
        t.daemon = True
        t.start()

    def _transcribe_and_process(self, audio_msg):
        """Worker thread: transcribe audio via Whisper, then process as
        AI request."""
        try:
            audio_file = io.BytesIO(audio_msg.audio_data)
            audio_file.name = "audio.wav"

            transcript = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )

            text = transcript.text.strip()
            if not text:
                logging.info("Whisper returned empty transcript")
                print("AI: empty transcript, ignoring")
                return

            logging.info("Whisper transcript: %s" % text)
            print("AI heard: \"%s\"" % text)

            self.state['last_audio']['transcript'] = text

            # Feed transcript through the normal AI request pipeline
            prompt = "[Voice command from %s]: %s" % (audio_msg.source, text)
            self.handle_request(ai_request(prompt))

        except Exception as e:
            error_msg = "Whisper transcription error: %s" % str(e)
            logging.error(error_msg)
            print(error_msg)
            self.broadcastQ.put(exec_report('ai_error', error_msg))

    def _fetch_snapshot(self):
        """Fetch JPEG snapshot from camera service.
        Returns base64 string or None."""
        cameras = self.state.get('cameras', {})
        active = [n for n, info in cameras.items()
                  if n != 'off' and isinstance(info, dict)
                  and info.get('status') == 'on']

        if not active:
            return None

        try:
            from lbrsys.settings import CAMERA_SNAPSHOT_URL, USE_SSL
            ctx = None
            if USE_SSL:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(CAMERA_SNAPSHOT_URL)
            with urllib.request.urlopen(req, timeout=2, context=ctx) as resp:
                frame_bytes = resp.read()

            return base64.b64encode(frame_bytes).decode('ascii')
        except Exception as e:
            logging.warning("Failed to fetch snapshot: %s" % str(e))
            return None

    def _build_instructions(self):
        """Build the system prompt with current state and robot config."""
        try:
            from lbrsys.settings import robot_name
        except ImportError:
            robot_name = 'lbr'

        wheel_diameter = robot_move_config.wheel_diameter
        counts_per_rev = robot_move_config.counts_per_rev
        if counts_per_rev > 0:
            cm_per_count = (math.pi * wheel_diameter) / counts_per_rev
        else:
            cm_per_count = 0.0

        return SYSTEM_PROMPT.format(
            robot_name=robot_name,
            wheel_diameter=wheel_diameter,
            counts_per_rev=counts_per_rev,
            cm_per_count=cm_per_count,
            robot_notes=_format_robot_notes(robot_ai_notes),
            state=json.dumps(self.state, indent=2, default=str),
        )

    def _build_user_input(self, prompt):
        """Build user input items, with camera snapshot if available."""
        snapshot_b64 = self._fetch_snapshot()

        if snapshot_b64:
            return [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64,%s" % snapshot_b64,
                },
            ]
        else:
            return prompt

    def _is_movement_complete(self):
        """Check if the robot has stopped moving by examining motor current.

        Zero current on both motor channels is the definitive indicator
        that the robot has stopped moving.
        """
        amps = self.state.get('Amps')
        if amps is None:
            return True

        if isinstance(amps, dict):
            ch1 = abs(amps.get('channel1', 0))
            ch2 = abs(amps.get('channel2', 0))
        else:
            return True

        return ch1 == 0 and ch2 == 0

    def _wait_for_movement_complete(self):
        """Wait for the robot to finish moving.

        Polls motor current telemetry until both channels read zero,
        or timeout is reached. Returns True if movement completed,
        False on timeout.
        """
        start_time = time.time()
        # Brief initial delay to let the command reach the motors
        time.sleep(0.5)

        while time.time() - start_time < MOVEMENT_COMPLETE_TIMEOUT:
            if self._is_movement_complete():
                logging.info("Movement complete (%.1fs)" %
                             (time.time() - start_time))
                return True
            time.sleep(MOVEMENT_POLL_INTERVAL)

        logging.warning("Movement completion timeout (%.1fs)" %
                        MOVEMENT_COMPLETE_TIMEOUT)
        return False

    def _call_openai(self, request):
        """Worker thread: call OpenAI Responses API and process the response.

        Implements a sense-act loop for multi-step tasks: after executing
        tool calls that involve movement, waits for movement to complete,
        then feeds updated telemetry back to the model for the next decision.
        """
        instructions = self._build_instructions()
        user_input = self._build_user_input(request.prompt)

        input_items = [{"role": "user", "content": user_input}]

        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=input_items,
                tools=ROBOT_TOOLS,
                previous_response_id=self.last_response_id,
                store=True,
            )

            self.last_response_id = response.id
            self._process_response(response)

        except Exception as e:
            error_msg = "AI request error: %s" % str(e)
            logging.error(error_msg)
            print(error_msg)
            self.broadcastQ.put(exec_report('ai_error', str(e)))

    def _process_response(self, response):
        """Process a Responses API response, running the sense-act loop
        if tool calls are present.

        For single-step responses (text only, or non-movement tool calls),
        executes immediately and returns.

        For movement tool calls, executes the command, waits for completion,
        injects updated telemetry, and sends a follow-up request to the model.
        Repeats until the model produces a final text response with no
        further tool calls or the iteration limit is reached.
        """
        iteration = 0

        while iteration < MAX_SENSE_ACT_ITERATIONS:
            iteration += 1

            # Separate tool calls from text output
            function_calls = [item for item in response.output
                              if item.type == "function_call"]
            text_items = [item for item in response.output
                          if item.type == "message"]

            # Report any text content to the operator
            for item in text_items:
                for content in item.content:
                    if content.type == "output_text" and content.text:
                        logging.info("AI response: %s" % content.text)
                        self.broadcastQ.put(exec_report('ai', content.text))

            if not function_calls:
                # No tool calls — task complete
                break

            # Execute all tool calls and collect results
            tool_results = []
            has_movement = False

            for fc in function_calls:
                fn_name = fc.name
                fn_args = json.loads(fc.arguments)
                logging.info("AI tool call [iter %d]: %s(%s)" %
                             (iteration, fn_name, str(fn_args)))

                result = execute_tool_call(fn_name, fn_args, self.broadcastQ)

                tool_results.append({
                    "type": "function_call_output",
                    "call_id": fc.call_id,
                    "output": result,
                })

                if fn_name in MOVEMENT_TOOLS:
                    has_movement = True

            # If movement was commanded, wait for it to complete
            if has_movement:
                logging.info("Waiting for movement to complete...")
                completed = self._wait_for_movement_complete()
                if not completed:
                    logging.warning("Movement timed out, continuing anyway")

            # Build follow-up input: tool results + telemetry update.
            # The model's output items are already known server-side via
            # previous_response_id, so we only send the new items.
            follow_up_input = tool_results

            # Inject updated telemetry as a user message
            telemetry_text = ("[Telemetry update after command execution]\n"
                              + json.dumps(self.state, indent=2, default=str))
            follow_up_input.append({
                "role": "user",
                "content": telemetry_text,
            })

            # Refresh instructions with latest state
            instructions = self._build_instructions()

            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=instructions,
                    input=follow_up_input,
                    tools=ROBOT_TOOLS,
                    previous_response_id=self.last_response_id,
                    store=True,
                )

                self.last_response_id = response.id

            except Exception as e:
                error_msg = ("AI sense-act loop error (iter %d): %s" %
                             (iteration, str(e)))
                logging.error(error_msg)
                print(error_msg)
                self.broadcastQ.put(exec_report('ai_error', str(e)))
                break
        else:
            msg = ("AI sense-act loop reached max iterations (%d)" %
                   MAX_SENSE_ACT_ITERATIONS)
            logging.warning(msg)
            print(msg)
            self.broadcastQ.put(exec_report('ai', msg))

    def update_state_from_feedback(self, task):
        """Accumulate telemetry from feedback messages into state snapshot.

        Telemetry arrives as feedback(info) where info is typically a dict
        from opsmgr (e.g. {'Ranges': {...}}, {'Bat': {...}}, {'MPU': {...}}).
        Namedtuple fields are converted via _asdict() before being sent.
        """
        try:
            info = task.info
            if type(info) is dict:
                self.update_state_from_dict(info)
            else:
                # Handle namedtuples or other types by converting to dict
                if hasattr(info, '_asdict'):
                    self.update_state_from_dict(
                        {type(info).__name__: info._asdict()}
                    )
                else:
                    self.state['last_feedback'] = str(info)
                    logging.debug("State updated from non-dict feedback: %s"
                                  % type(info).__name__)
        except Exception as e:
            logging.debug("Error updating state from feedback: %s" % str(e))

    def update_state_from_dict(self, d):
        """Merge a telemetry dict into the state snapshot."""
        for k, v in d.items():
            self.state[k] = v
        logging.debug("State updated: %s" % str(list(d.keys())))

    def update_state_from_report(self, task):
        """Update state from exec_report messages."""
        try:
            self.state[task.name] = task.info
            logging.debug("State updated from report: %s" % task.name)
        except Exception as e:
            logging.debug("Error updating state from report: %s" % str(e))

    def end(self):
        ta = time.asctime()
        logging.info("%s: AI Service Ended." % ta)
        print("AI Service ended.")


if __name__ == '__main__':
    sys.path.insert(1, os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../')))
    sys.path.insert(2, os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../../')))

    multiprocessing.set_start_method('spawn')
    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()

    # Monitor thread to print what the AI service sends back
    def monitor(q):
        while True:
            msg = q.get()
            if msg == 'Shutdown':
                q.task_done()
                break
            print("  AI -> Robot: %s" % str(msg))
            q.task_done()

    mt = threading.Thread(target=monitor, args=(bq,), name="Monitor")
    mt.daemon = True
    mt.start()

    p = multiprocessing.Process(
        target=RobAIService, name="Robot AI Service", args=(cq, bq)
    )
    p.start()

    print("AI Service test harness (Responses API).")
    print("Type a prompt, 'reset' to clear conversation, or 'quit' to exit.")
    while True:
        try:
            prompt = input("AI> ")
            if prompt.lower() in ('quit', 'exit', 'q'):
                break
            if prompt.strip():
                cq.put(ai_request(prompt))
                time.sleep(3)  # Give time for the response
        except (EOFError, KeyboardInterrupt):
            break

    cq.put("Shutdown")
    cq.join()
    bq.put("Shutdown")
    bq.join()
    p.join(timeout=5)
    print("Done.")
