"""
Robot Microphone Service — captures audio from the C920's integrated mic.

Wired to the executive via JoinableQueues (process_id=10, channels 20/21).
Uses ALSAMicrophone driver with voice activity detection to automatically
capture speech segments and emit mic_audio messages.

States: IDLE, LISTENING (ring buffer active, monitoring for voice),
        CAPTURING (recording after voice activity trigger).
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
import struct
import logging
import multiprocessing
import threading

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(2, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.insert(3, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from lbrsys import mic_command, mic_audio, feedback
from lbrsys.settings import micLogFile

proc = multiprocessing.current_process()

if proc.name == "Robot Microphone Service":
    logging.basicConfig(
        level=logging.INFO,
        filename=micLogFile,
        format='[%(levelname)s] (%(processName)-10s) %(message)s',
    )


# States
IDLE = 'IDLE'
LISTENING = 'LISTENING'
CAPTURING = 'CAPTURING'


class RobMicrophoneService:
    def __init__(self, commandQ=None, broadcastQ=None):
        print("Process Name is %s" % multiprocessing.current_process().name)
        self.commandQ = commandQ
        self.broadcastQ = broadcastQ

        self.state = IDLE
        self.mic = None
        self.output = None
        self.monitor_thread = None
        self.do_monitor = False
        self.capture_start_time = None

        self.setup_audio()
        self.start()

    def setup_audio(self):
        """Initialize microphone and streaming output (does NOT start recording)."""
        try:
            from lbrsys.robdrivers.audio import ALSAMicrophone, AudioStreamingOutput
            from lbrsys.settings import (MIC_DEVICE, MIC_SAMPLE_RATE, MIC_CHANNELS,
                                         MIC_RING_BUFFER_SECONDS)
        except ImportError as e:
            logging.error("Failed to import audio driver: %s" % str(e))
            print("Warning: Audio driver import failed: %s" % str(e))
            return

        # Determine device
        device = MIC_DEVICE
        if device is None:
            device = ALSAMicrophone.find_device('C920')
        if device is None:
            device = 'default'
            logging.warning("No C920 found, using default ALSA device")

        self.output = AudioStreamingOutput(
            ring_buffer_seconds=MIC_RING_BUFFER_SECONDS,
            sample_rate=MIC_SAMPLE_RATE,
            sample_width=2,
            channels=MIC_CHANNELS,
        )

        self.mic = ALSAMicrophone(
            device=device,
            sample_rate=MIC_SAMPLE_RATE,
            channels=MIC_CHANNELS,
            period_size=1024,
            name='mic',
        )
        self.mic.config_device()

        logging.info("Microphone service audio setup complete")
        print("Microphone service audio setup complete")

    def start(self):
        """Main loop — blocks on commandQ, dispatches by message type."""
        ta = time.asctime()
        logging.info("%s: Starting Microphone Service" % ta)

        while True:
            task = self.commandQ.get()

            if task == 'Shutdown':
                logging.info("Shutting down Microphone Service")
                print("Shutting down Microphone Service")
                self._cleanup()
                self.commandQ.task_done()
                break

            self.process_task(task)
            self.commandQ.task_done()

        self.end()

    def process_task(self, task):
        """Route incoming messages by type."""
        if type(task) is mic_command:
            self.handle_command(task)
        elif type(task) is str:
            logging.debug("Microphone service received string: %s" % task)
        else:
            logging.debug("Microphone service received unknown type: %s %s" %
                          (type(task).__name__, str(task)))

    def handle_command(self, cmd):
        """Dispatch mic_command by action."""
        action = cmd.action
        logging.info("Microphone command: %s" % action)

        if action == 'start_listening':
            self.handle_start_listening()
        elif action == 'stop_listening':
            self.handle_stop_listening()
        elif action == 'start_capture':
            self.handle_start_capture()
        elif action == 'stop_capture':
            self.handle_stop_capture()
        else:
            logging.warning("Unknown mic command action: %s" % action)
            print("Unknown mic command: %s" % action)

    def handle_start_listening(self):
        """Start mic recording and voice activity monitoring."""
        if not self.mic:
            print("Microphone not available")
            return

        if self.state != IDLE:
            print("Microphone already in state: %s" % self.state)
            return

        self.mic.start_recording(self.output)
        self.do_monitor = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_audio,
            name="MicMonitor",
            daemon=True,
        )
        self.monitor_thread.start()

        self.state = LISTENING
        status = {'microphone': {'state': LISTENING}}
        self.broadcastQ.put(status)
        logging.info("Microphone: now LISTENING")
        print("Microphone: now LISTENING")

    def handle_stop_listening(self):
        """Stop recording and monitoring."""
        if self.state == IDLE:
            print("Microphone already idle")
            return

        # If capturing, finalize first
        if self.state == CAPTURING:
            self._finalize_capture()

        self.do_monitor = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)

        if self.mic:
            self.mic.stop_recording()

        self.state = IDLE
        status = {'microphone': {'state': IDLE}}
        self.broadcastQ.put(status)
        logging.info("Microphone: now IDLE")
        print("Microphone: now IDLE")

    def handle_start_capture(self):
        """Manual capture trigger (no wake word needed)."""
        if not self.mic:
            print("Microphone not available")
            return

        if self.state == IDLE:
            # Start recording first if not already
            self.mic.start_recording(self.output)

        if self.state == CAPTURING:
            print("Already capturing")
            return

        self.output.start_capture()
        self.capture_start_time = time.time()
        self.state = CAPTURING
        logging.info("Microphone: manual capture started")
        print("Microphone: CAPTURING (manual)")

    def handle_stop_capture(self):
        """Manual capture stop."""
        if self.state != CAPTURING:
            print("Not currently capturing")
            return

        self._finalize_capture()

    def _monitor_audio(self):
        """Background thread: monitor ring buffer for voice activity."""
        from lbrsys.settings import (MIC_SILENCE_THRESHOLD, MIC_SILENCE_DURATION,
                                     MIC_MAX_CAPTURE_DURATION, MIC_SAMPLE_RATE)

        check_interval = 0.1  # Check every 100ms
        silence_start = None

        while self.do_monitor:
            time.sleep(check_interval)

            if not self.output:
                continue

            # Get recent audio for RMS analysis
            recent = self.output.ring_buffer.get_recent(0.1)
            if not recent or len(recent) < 4:
                continue

            rms = self._calculate_rms(recent)

            if self.state == LISTENING:
                if rms > MIC_SILENCE_THRESHOLD:
                    logging.info("Voice activity detected (RMS=%d)" % rms)
                    print("Voice activity detected (RMS=%d)" % rms)
                    self.output.start_capture()
                    self.capture_start_time = time.time()
                    self.state = CAPTURING
                    silence_start = None

            elif self.state == CAPTURING:
                elapsed = time.time() - self.capture_start_time

                # Check max duration
                if elapsed >= MIC_MAX_CAPTURE_DURATION:
                    logging.info("Max capture duration reached (%.1fs)" % elapsed)
                    print("Max capture duration reached")
                    self._finalize_capture()
                    silence_start = None
                    continue

                # Track silence for auto-stop
                if rms <= MIC_SILENCE_THRESHOLD:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= MIC_SILENCE_DURATION:
                        logging.info("Silence timeout, finalizing capture (%.1fs)" % elapsed)
                        print("Silence detected, finalizing capture")
                        self._finalize_capture()
                        silence_start = None
                else:
                    silence_start = None

    def _finalize_capture(self):
        """Get captured audio, wrap in WAV, emit mic_audio message."""
        from lbrsys.robdrivers.audio import AudioStreamingOutput
        from lbrsys.settings import MIC_SAMPLE_RATE, MIC_CHANNELS

        raw_audio = self.output.stop_capture()
        if not raw_audio:
            logging.warning("No audio captured")
            self.state = LISTENING if self.do_monitor else IDLE
            return

        duration = len(raw_audio) / (MIC_SAMPLE_RATE * 2 * MIC_CHANNELS)
        wav_data = AudioStreamingOutput.get_wav_bytes(
            raw_audio,
            sample_rate=MIC_SAMPLE_RATE,
            sample_width=2,
            channels=MIC_CHANNELS,
        )

        source = 'voice_activity' if self.do_monitor else 'manual'
        audio_msg = mic_audio(
            audio_data=wav_data,
            format='wav',
            duration=round(duration, 2),
            source=source,
        )

        self.broadcastQ.put(audio_msg)
        logging.info("Captured %.1fs of audio (%d bytes WAV), source=%s" %
                      (duration, len(wav_data), source))
        print("Captured %.1fs of audio (%d bytes)" % (duration, len(wav_data)))

        # Return to LISTENING if monitor is running, else IDLE
        self.state = LISTENING if self.do_monitor else IDLE

    @staticmethod
    def _calculate_rms(data):
        """Compute RMS energy from S16_LE PCM data."""
        count = len(data) // 2
        if count == 0:
            return 0
        samples = struct.unpack('<%dh' % count, data[:count * 2])
        sum_sq = sum(s * s for s in samples)
        return int((sum_sq / count) ** 0.5)

    def _cleanup(self):
        """Clean up resources on shutdown."""
        if self.state == CAPTURING:
            self.output.stop_capture()

        self.do_monitor = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)

        if self.mic:
            self.mic.close()

    def end(self):
        ta = time.asctime()
        logging.info("%s: Microphone Service Ended." % ta)
        print("Microphone Service ended.")


def start_service(commandq, broadcastq):
    RobMicrophoneService(commandQ=commandq, broadcastQ=broadcastq)


if __name__ == '__main__':
    sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
    sys.path.insert(2, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

    multiprocessing.set_start_method('spawn')
    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()

    # Monitor thread to print what the mic service sends back
    def monitor(q):
        while True:
            msg = q.get()
            if msg == 'Shutdown':
                q.task_done()
                break
            if type(msg) is mic_audio:
                print("  Mic -> Robot: mic_audio(format=%s, duration=%.2fs, "
                      "source=%s, %d bytes)" %
                      (msg.format, msg.duration, msg.source, len(msg.audio_data)))
            else:
                print("  Mic -> Robot: %s" % str(msg))
            q.task_done()

    mt = threading.Thread(target=monitor, args=(bq,), name="Monitor")
    mt.daemon = True
    mt.start()

    p = multiprocessing.Process(
        target=start_service, name="Robot Microphone Service", args=(cq, bq)
    )
    p.start()

    print("\nMicrophone Service test harness.")
    print("Commands: start_listening, stop_listening, start_capture, "
          "stop_capture, quit")
    while True:
        try:
            cmd = input("Mic> ")
            cmd = cmd.strip()
            if cmd.lower() in ('quit', 'exit', 'q'):
                break
            if cmd in ('start_listening', 'stop_listening',
                       'start_capture', 'stop_capture'):
                cq.put(mic_command(cmd))
            elif cmd:
                print("Unknown command: %s" % cmd)
        except (EOFError, KeyboardInterrupt):
            break

    cq.put("Shutdown")
    cq.join()
    bq.put("Shutdown")
    bq.join()
    p.join(timeout=5)
    print("Done.")
