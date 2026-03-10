"""
Robot AI service - bridges between lbrsys and the OpenAI platform.

This service sits above the rest of the system architecturally, wired to the
executive via JoinableQueues.  It receives telemetry and AI requests on its
commandQ and sends robot commands back through its broadcastQ, which the
executive's monitor thread dispatches through normal type-based routing.

The service uses OpenAI function calling (tools) so the model can issue
structured robot commands (move, stop, speak, turn, etc.) that are translated
to the same command strings used by the console and HTTP service.
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2009-2026 Tal G. Ball"
__license__ = "Apache License, Version 2.0"
__version__ = "1.0"

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
import time
import json
import logging
import multiprocessing
import threading
import queue

from lbrsys import ai_request, feedback, exec_report
from lbrsys.settings import aiLogFile

proc = multiprocessing.current_process()

if proc.name == "Robot AI Service":
    logging.basicConfig(
        level=logging.INFO,
        filename=aiLogFile,
        format='[%(levelname)s] (%(processName)-10s) %(message)s',
    )


SYSTEM_PROMPT = """You are the AI reasoning layer for a mobile robot called {robot_name}.
You sit above the robot's executive system and can observe sensor telemetry
and issue commands to all subsystems (motors, speech, camera, etc.).

Your current sensor state is provided below.  When asked to act, use the
available tools to issue robot commands.  You can call multiple tools in
sequence if needed.

When you have a text response for the operator, use the speak tool to say it
through the robot's speech system, or the report tool to send it as a text
report to the console.

Current robot state:
{state}
"""

ROBOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": "Move the robot with specified power level and angle. "
                           "Level is 0.0 to 1.0 (fraction of max power). "
                           "Angle is degrees: 0=forward, 90=right, 180=backward, 270=left.",
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
                "required": ["level", "angle"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop",
            "description": "Stop all movement immediately.",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    {
        "type": "function",
        "function": {
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
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
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
                "required": ["angle"]
            }
        }
    },
    {
        "type": "function",
        "function": {
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
                "required": ["heading"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Move the robot with specified power, angle, range, sensor, "
                           "and/or duration. Use this instead of 'move' when you want "
                           "the robot to move for a specific duration or distance. "
                           "The robot will stop automatically when the range or duration "
                           "limit is reached.",
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
                    "range": {
                        "type": "integer",
                        "description": "Distance limit in cm (0 = no limit)",
                        "default": 0
                    },
                    "sensor": {
                        "type": "string",
                        "description": "Range sensor direction to monitor: "
                                       "Forward, Back, Left, or Right",
                        "enum": ["Forward", "Back", "Left", "Right"],
                        "default": "Forward"
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Time limit in seconds (0 = no limit)",
                        "default": 0
                    },
                },
                "required": ["level", "angle"]
            }
        }
    },
    {
        "type": "function",
        "function": {
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
                "required": ["message"]
            }
        }
    },
]


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
        command = "/r/%.2f/%d/%d/%s/%d" % (level, angle, range_limit, sensor, duration)

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


class RobAIService:
    def __init__(self, commandQ=None, broadcastQ=None):
        print("Process Name is %s" % multiprocessing.current_process().name)
        self.commandQ = commandQ
        self.broadcastQ = broadcastQ
        self.client = None
        self.model = None
        self.state = {}
        self.conversation = []
        self.request_thread = None
        self.request_queue = queue.Queue()

        self.setup_client()
        self.start()

    def setup_client(self):
        """Initialize OpenAI client from environment variables."""
        try:
            from openai import OpenAI
            api_key = os.environ.get('ROBOT_OPENAI_API_KEY') or os.environ.get('OPENAI_API_KEY')
            if not api_key:
                logging.error("Neither ROBOT_OPENAI_API_KEY or OPENAI_API_KEY are set")
                print("Warning: ROBOT_OPENAI_API_KEY not set - AI service will not "
                      "be able to process requests")
                return

            self.client = OpenAI(api_key=api_key)
            self.model = os.environ.get('ROBOT_OPENAI_MODEL', 'gpt-5.2')
            logging.info("AI service initialized with model: %s" % self.model)
            print("AI service initialized with model: %s" % self.model)

        except ImportError:
            logging.error("openai package not installed")
            print("Warning: openai package not installed - AI service unavailable")
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

    def _call_openai(self, request):
        """Worker thread: call OpenAI API and process the response."""
        try:
            from lbrsys.settings import robot_name
        except ImportError:
            robot_name = 'lbr'

        system_message = SYSTEM_PROMPT.format(
            robot_name=robot_name,
            state=json.dumps(self.state, indent=2, default=str)
        )

        messages = [
            {"role": "system", "content": system_message},
        ]

        # Include recent conversation history for context
        messages.extend(self.conversation[-10:])

        # Add the new user message
        user_message = {"role": "user", "content": request.prompt}
        messages.append(user_message)
        self.conversation.append(user_message)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=ROBOT_TOOLS,
            )

            message = response.choices[0].message

            # Process tool calls if any
            if message.tool_calls:
                # Track the assistant message with tool calls
                self.conversation.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in message.tool_calls
                    ]
                })

                for tool_call in message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)
                    logging.info("AI tool call: %s(%s)" % (fn_name, str(fn_args)))

                    result = execute_tool_call(fn_name, fn_args, self.broadcastQ)

                    self.conversation.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })

            # If the model also produced text content, report it
            if message.content:
                logging.info("AI response: %s" % message.content)
                self.broadcastQ.put(exec_report('ai', message.content))

                if not message.tool_calls:
                    self.conversation.append({
                        "role": "assistant",
                        "content": message.content,
                    })

        except Exception as e:
            error_msg = "AI request error: %s" % str(e)
            logging.error(error_msg)
            print(error_msg)
            self.broadcastQ.put(exec_report('ai_error', str(e)))

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
    sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
    sys.path.insert(2, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

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

    print("AI Service test harness. Type a prompt or 'quit' to exit.")
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
