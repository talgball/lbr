"""
Robot Microphone Service — captures audio from the C920's integrated mic.

Wired to the executive via JoinableQueues (process_id=10, channels 20/21).
Uses ALSAMicrophone driver with voice activity detection to automatically
capture speech segments and emit mic_audio messages.

States: IDLE, LISTENING (ring buffer active, monitoring for voice),
        CAPTURING (recording after voice activity trigger),
        WAKE_LISTENING (openWakeWord monitoring for wake word),
        WAKE_CAPTURING (wake word detected, recording command).
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
import math
import logging
import multiprocessing
import threading

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(2, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.insert(3, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from lbrsys import mic_command, mic_audio, feedback, set_process_title
from lbrsys.settings import micLogFile

proc = multiprocessing.current_process()

if proc.name == "Robot Microphone Service":
    logging.basicConfig(
        level=logging.INFO,
        filename=micLogFile,
        format='[%(levelname)s] (%(processName)-10s) %(message)s',
    )
    set_process_title()


# States
IDLE = 'IDLE'
LISTENING = 'LISTENING'
CAPTURING = 'CAPTURING'
WAKE_LISTENING = 'WAKE_LISTENING'    # Listening for wake word via local ASR
WAKE_CAPTURING = 'WAKE_CAPTURING'    # Wake word detected, capturing command


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

        # Wake word detection
        self.oww_model = None
        self.wake_word_name = None
        self.do_wake_listen = False
        self.wake_thread = None

        self.setup_audio()
        self._auto_start_wake_word()
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

    def _auto_start_wake_word(self):
        """Optionally start wake word listening on service startup."""
        try:
            from lbrsys.settings import MIC_AUTO_WAKE_WORD
        except ImportError:
            return

        if MIC_AUTO_WAKE_WORD and self.mic:
            logging.info("Auto-starting wake word listening")
            self.handle_start_wake_word()

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
        elif action == 'start_wake_word':
            self.handle_start_wake_word()
        elif action == 'stop_wake_word':
            self.handle_stop_wake_word()
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

    def _setup_wake_word(self):
        """Initialize openWakeWord model for wake word detection."""
        if self.oww_model is not None:
            return True

        try:
            from openwakeword.model import Model as OWWModel
            from lbrsys.settings import MIC_WAKE_WORD_MODEL

            model_arg = MIC_WAKE_WORD_MODEL
            if model_arg and (model_arg.endswith('.tflite')
                              or model_arg.endswith('.onnx')):
                # Custom model file path
                self.oww_model = OWWModel(
                    wakeword_models=[model_arg],
                    inference_framework='onnx',
                )
            else:
                # Built-in model name (e.g., 'hey_jarvis')
                self.oww_model = OWWModel(
                    wakeword_models=[model_arg],
                    inference_framework='onnx',
                )

            # The model's prediction keys are the model names
            model_names = list(self.oww_model.models.keys())
            self.wake_word_name = model_names[0] if model_names else model_arg
            logging.info("openWakeWord initialized, model: '%s'" % self.wake_word_name)
            print("openWakeWord initialized, model: '%s'" % self.wake_word_name)

            # Pre-compute wake word feedback tone
            self._wake_tone_pcm = None
            self._wake_tone_device = 'pulse'
            try:
                from lbrsys.settings import (MIC_WAKE_WORD_FEEDBACK,
                                             MIC_WAKE_WORD_TONE_FREQ,
                                             MIC_WAKE_WORD_TONE_DURATION,
                                             MIC_WAKE_WORD_TONE_DEVICE)
                self._wake_feedback_enabled = MIC_WAKE_WORD_FEEDBACK
                self._wake_tone_device = MIC_WAKE_WORD_TONE_DEVICE
                if MIC_WAKE_WORD_FEEDBACK:
                    self._wake_tone_pcm = self._generate_tone(
                        MIC_WAKE_WORD_TONE_FREQ, MIC_WAKE_WORD_TONE_DURATION
                    )
                    logging.info("Wake word feedback tone ready "
                                 "(freq=%dHz, dur=%.2fs, device=%s)" %
                                 (MIC_WAKE_WORD_TONE_FREQ,
                                  MIC_WAKE_WORD_TONE_DURATION,
                                  self._wake_tone_device))
            except ImportError:
                self._wake_feedback_enabled = False

            return True

        except ImportError:
            logging.error("openwakeword package not installed")
            print("Warning: openwakeword not installed - wake word unavailable")
            return False
        except Exception as e:
            logging.error("Error initializing openWakeWord: %s" % str(e))
            print("Warning: openWakeWord init failed: %s" % str(e))
            return False

    def handle_start_wake_word(self):
        """Start listening for wake word using openWakeWord."""
        if not self.mic:
            print("Microphone not available")
            return

        if self.state != IDLE:
            print("Microphone already in state: %s" % self.state)
            return

        if not self._setup_wake_word():
            return

        self.mic.start_recording(self.output)
        self.do_wake_listen = True
        self.wake_thread = threading.Thread(
            target=self._wake_word_monitor,
            name="WakeWordMonitor",
            daemon=True,
        )
        self.wake_thread.start()

        self.state = WAKE_LISTENING
        status = {'microphone': {'state': WAKE_LISTENING,
                                 'wake_word': self.wake_word_name}}
        self.broadcastQ.put(status)
        logging.info("Microphone: now WAKE_LISTENING for '%s'" % self.wake_word_name)
        print("Microphone: now WAKE_LISTENING for '%s'" % self.wake_word_name)

    def handle_stop_wake_word(self):
        """Stop wake word listening."""
        if self.state not in (WAKE_LISTENING, WAKE_CAPTURING):
            print("Not in wake word mode (state: %s)" % self.state)
            return

        if self.state == WAKE_CAPTURING:
            self._finalize_capture()

        self.do_wake_listen = False
        if self.wake_thread and self.wake_thread.is_alive():
            self.wake_thread.join(timeout=2.0)

        if self.mic:
            self.mic.stop_recording()

        self.state = IDLE
        status = {'microphone': {'state': IDLE}}
        self.broadcastQ.put(status)
        logging.info("Microphone: wake word stopped, now IDLE")
        print("Microphone: wake word stopped, now IDLE")

    def _wake_word_monitor(self):
        """Background thread: feed audio to openWakeWord, watch for wake word.

        In WAKE_LISTENING state, feeds 16-bit PCM chunks to the openWakeWord
        model. When confidence exceeds threshold, starts capturing the command.
        In WAKE_CAPTURING state, monitors for silence to end capture.
        """
        import numpy as np
        from lbrsys.settings import (MIC_SILENCE_THRESHOLD, MIC_SILENCE_DURATION,
                                     MIC_MAX_CAPTURE_DURATION, MIC_SAMPLE_RATE)
        try:
            from lbrsys.settings import MIC_WAKE_WORD_THRESHOLD
        except ImportError:
            MIC_WAKE_WORD_THRESHOLD = 0.5
        try:
            from lbrsys.settings import MIC_WAKE_WORD_DEBUG
        except ImportError:
            MIC_WAKE_WORD_DEBUG = False

        # openWakeWord expects 1280-sample (80ms) chunks at 16kHz
        oww_chunk_samples = 1280
        oww_chunk_bytes = oww_chunk_samples * 2  # 16-bit = 2 bytes/sample
        check_interval = 0.08  # 80ms to match openWakeWord's native chunk size
        silence_start = None
        ambient_rms = 0.0  # Running estimate of ambient noise floor

        while self.do_wake_listen:
            time.sleep(check_interval)

            if not self.output:
                continue

            recent = self.output.ring_buffer.get_recent(check_interval)
            if not recent or len(recent) < oww_chunk_bytes:
                continue

            if self.state == WAKE_LISTENING:
                # Update running ambient noise estimate
                rms = self._calculate_rms(recent)
                if ambient_rms == 0.0:
                    ambient_rms = float(rms)
                else:
                    ambient_rms = 0.95 * ambient_rms + 0.05 * rms

                # Convert raw PCM bytes to int16 numpy array for openWakeWord
                audio_chunk = np.frombuffer(
                    recent[:oww_chunk_bytes], dtype=np.int16
                )

                # Get predictions from openWakeWord
                predictions = self.oww_model.predict(audio_chunk)
                score = predictions.get(self.wake_word_name, 0.0)

                if MIC_WAKE_WORD_DEBUG:
                    if score > 0.01:
                        print("WakeWord [rms=%d ambient=%d]: %s=%.3f" %
                              (rms, int(ambient_rms), self.wake_word_name,
                               score))

                if score >= MIC_WAKE_WORD_THRESHOLD:
                    logging.info("Wake word detected: %s (score=%.3f)" %
                                 (self.wake_word_name, score))
                    print("Wake word '%s' detected! (score=%.3f)" %
                          (self.wake_word_name, score))
                    self.oww_model.reset()

                    # Play feedback tone on daemon thread
                    if (self._wake_feedback_enabled
                            and self._wake_tone_pcm is not None):
                        threading.Thread(
                            target=self._play_wake_tone,
                            name="WakeTone",
                            daemon=True,
                        ).start()

                    self.output.start_capture()
                    self.capture_start_time = time.time()
                    self.state = WAKE_CAPTURING
                    status = {'microphone': {
                        'state': WAKE_CAPTURING,
                        'wake_word_detected': self.wake_word_name,
                    }}
                    self.broadcastQ.put(status)
                    silence_start = None
                # elif score >= MIC_WAKE_WORD_THRESHOLD * 0.8:
                #     logging.info("Wake word nearly detected: %s (score=%.3f)" %
                #                  (self.wake_word_name, score))
                #     print("Wake word '%s' nearly detected! (score=%.3f)" %
                #           (self.wake_word_name, score))

            elif self.state == WAKE_CAPTURING:
                elapsed = time.time() - self.capture_start_time
                rms = self._calculate_rms(recent)

                # Adaptive silence threshold: ambient noise floor + 50% margin,
                # but never below the configured minimum
                silence_threshold = max(MIC_SILENCE_THRESHOLD,
                                        ambient_rms * 1.5)

                if elapsed >= MIC_MAX_CAPTURE_DURATION:
                    logging.info("Max capture duration reached (%.1fs)" % elapsed)
                    print("Max capture duration reached")
                    self._finalize_capture()
                    self.state = WAKE_LISTENING
                    silence_start = None
                    continue

                if rms <= silence_threshold:
                    if silence_start is None:
                        silence_start = time.time()
                        logging.debug(
                            "Silence candidate started "
                            "(rms=%d, threshold=%d, ambient=%d)" %
                            (rms, int(silence_threshold), int(ambient_rms)))
                    elif time.time() - silence_start >= MIC_SILENCE_DURATION:
                        logging.info(
                            "Silence timeout after wake word, "
                            "finalizing capture (%.1fs, ambient_rms=%d)" %
                            (elapsed, int(ambient_rms)))
                        print("Silence detected, finalizing capture")
                        self._finalize_capture()
                        self.state = WAKE_LISTENING
                        silence_start = None
                else:
                    silence_start = None

    def _monitor_audio(self):
        """Background thread: monitor ring buffer for voice activity."""
        from lbrsys.settings import (MIC_SILENCE_THRESHOLD, MIC_SILENCE_DURATION,
                                     MIC_MAX_CAPTURE_DURATION, MIC_SAMPLE_RATE)

        check_interval = 0.1  # Check every 100ms
        silence_start = None
        ambient_rms = 0.0  # Running estimate of ambient noise floor

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
                # Update running ambient noise estimate
                if ambient_rms == 0.0:
                    ambient_rms = float(rms)
                else:
                    ambient_rms = 0.95 * ambient_rms + 0.05 * rms

                if rms > max(MIC_SILENCE_THRESHOLD, ambient_rms * 2.0):
                    logging.info("Voice activity detected (RMS=%d, ambient=%d)"
                                 % (rms, int(ambient_rms)))
                    print("Voice activity detected (RMS=%d)" % rms)
                    self.output.start_capture()
                    self.capture_start_time = time.time()
                    self.state = CAPTURING
                    silence_start = None

            elif self.state == CAPTURING:
                elapsed = time.time() - self.capture_start_time

                # Adaptive silence threshold
                silence_threshold = max(MIC_SILENCE_THRESHOLD,
                                        ambient_rms * 1.5)

                # Check max duration
                if elapsed >= MIC_MAX_CAPTURE_DURATION:
                    logging.info("Max capture duration reached (%.1fs)" % elapsed)
                    print("Max capture duration reached")
                    self._finalize_capture()
                    silence_start = None
                    continue

                # Track silence for auto-stop
                if rms <= silence_threshold:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= MIC_SILENCE_DURATION:
                        logging.info("Silence timeout, finalizing capture "
                                     "(%.1fs, ambient_rms=%d)" %
                                     (elapsed, int(ambient_rms)))
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

        if self.do_wake_listen:
            source = 'wake_word'
        elif self.do_monitor:
            source = 'voice_activity'
        else:
            source = 'manual'
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

        # Return to appropriate listening state or IDLE
        if self.do_wake_listen:
            self.state = WAKE_LISTENING
        elif self.do_monitor:
            self.state = LISTENING
        else:
            self.state = IDLE

    @staticmethod
    def _generate_tone(freq, duration, sample_rate=16000, amplitude=0.5,
                       pad_seconds=0.15):
        """Render a sine wave as S16_LE PCM bytes with silence padding.

        Bluetooth speakers buffer ~100-200ms before output begins,
        so leading silence ensures the tone is audible.
        """
        pad_samples = int(sample_rate * pad_seconds)
        tone_samples = int(sample_rate * duration)
        total_samples = pad_samples + tone_samples + pad_samples
        max_val = 32767 * amplitude
        pcm = bytearray(total_samples * 2)
        for i in range(tone_samples):
            value = int(max_val * math.sin(2.0 * math.pi * freq * i / sample_rate))
            struct.pack_into('<h', pcm, (pad_samples + i) * 2, value)
        return bytes(pcm)

    def _play_wake_tone(self):
        """Play pre-computed wake word tone via ALSA playback. Runs on daemon thread."""
        try:
            import alsaaudio
            device = alsaaudio.PCM(
                channels=1, rate=16000,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=1024, device=self._wake_tone_device,
            )
            chunk_bytes = 1024 * 2  # 1024 samples * 2 bytes
            offset = 0
            while offset < len(self._wake_tone_pcm):
                chunk = self._wake_tone_pcm[offset:offset + chunk_bytes]
                device.write(chunk)
                offset += chunk_bytes
            device.close()
            logging.info("Wake tone played successfully")
            print("Wake tone played")
        except Exception as e:
            logging.warning("Wake tone playback failed: %s" % str(e))
            print("Wake tone FAILED: %s" % str(e))

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
        if self.state in (CAPTURING, WAKE_CAPTURING):
            self.output.stop_capture()

        self.do_monitor = False
        self.do_wake_listen = False

        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        if self.wake_thread and self.wake_thread.is_alive():
            self.wake_thread.join(timeout=2.0)

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
          "stop_capture, start_wake_word, stop_wake_word, quit")
    while True:
        try:
            cmd = input("Mic> ")
            cmd = cmd.strip()
            if cmd.lower() in ('quit', 'exit', 'q'):
                break
            if cmd in ('start_listening', 'stop_listening',
                       'start_capture', 'stop_capture',
                       'start_wake_word', 'stop_wake_word'):
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
