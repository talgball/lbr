"""
Driver for audio devices integrated with the robot.  Provides fine access to parameters and
    the audio read-write processes.
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2022 Tal G. Ball"
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

import sys
import io
import time
import wave
import threading
import alsaaudio


class ALSAMicrophone:
    """Low-level ALSA microphone driver. Context manager, background streaming thread,
    pluggable output object — mirrors UVCCamera pattern."""

    def __init__(self, device='default', sample_rate=16000, channels=1,
                 format=alsaaudio.PCM_FORMAT_S16_LE, period_size=1024, name=None):
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.period_size = period_size
        self.name = name or device

        self.pcm = None
        self.output = None
        self.do_stream = False
        self.streaming_thread = None
        self.chunks_read = 0
        self.start_time = None

    def config_device(self):
        """Open and configure the ALSA PCM capture device."""
        self.pcm = alsaaudio.PCM(
            type=alsaaudio.PCM_CAPTURE,
            mode=alsaaudio.PCM_NORMAL,
            device=self.device,
            channels=self.channels,
            rate=self.sample_rate,
            format=self.format,
            periodsize=self.period_size,
        )

        print(f"ALSAMicrophone configured: device={self.device}, "
              f"rate={self.sample_rate}, channels={self.channels}, "
              f"period_size={self.period_size}")
        return self

    def start_recording(self, output):
        """Start streaming audio to the given output object in a background thread."""
        self.output = output
        self.do_stream = True
        self.chunks_read = 0
        self.start_time = time.time()

        self.streaming_thread = threading.Thread(
            target=self.stream,
            name=f"MicStream-{self.name}",
            daemon=True,
        )
        self.streaming_thread.start()

    def stream(self):
        """Background loop: read chunks from ALSA and write to output."""
        while self.do_stream:
            self.read_chunk()

    def read_chunk(self):
        """Read one period from the PCM device and write to output."""
        try:
            length, data = self.pcm.read()
        except alsaaudio.ALSAAudioError as e:
            print(f"ALSAMicrophone read error: {e}")
            return

        if length == -32:  # EPIPE — buffer overrun
            print("ALSAMicrophone: buffer overrun (EPIPE)")
            return

        if length > 0 and self.output:
            self.output.write(data)
            self.chunks_read += 1

    def stop_recording(self):
        """Stop the streaming thread and print stats."""
        self.do_stream = False
        if self.streaming_thread and self.streaming_thread.is_alive():
            self.streaming_thread.join(timeout=2.0)

        elapsed = time.time() - self.start_time if self.start_time else 0
        print(f"ALSAMicrophone stopped: {self.chunks_read} chunks in {elapsed:.1f}s")

    def close(self):
        """Close the PCM device."""
        if self.do_stream:
            self.stop_recording()
        if self.pcm:
            self.pcm.close()
            self.pcm = None

    def __enter__(self):
        return self.config_device()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    @staticmethod
    def find_device(name_substring='C920'):
        """Find a capture device whose name contains the given substring.

        Prefers plughw: devices over hw: devices because plughw provides
        ALSA software conversion (channel mixing, resampling) which is
        needed when the hardware doesn't support the requested format
        natively (e.g., the C920 only captures in stereo).
        """
        try:
            devices = alsaaudio.pcms(alsaaudio.PCM_CAPTURE)
        except Exception:
            devices = []

        matches = [d for d in devices if name_substring.lower() in d.lower()]

        if not matches:
            print(f"ALSAMicrophone: no device matching '{name_substring}', "
                  f"available: {devices}")
            return None

        # Prefer plughw: for software format conversion
        for d in matches:
            if d.startswith('plughw:'):
                print(f"ALSAMicrophone: found device '{d}' matching '{name_substring}'")
                return d

        # Fall back to first match
        print(f"ALSAMicrophone: found device '{matches[0]}' matching '{name_substring}'")
        return matches[0]


class AudioRingBuffer:
    """Thread-safe circular buffer holding a fixed-duration window of audio."""

    def __init__(self, duration_seconds=3.0, sample_rate=16000,
                 sample_width=2, channels=1):
        self.duration = duration_seconds
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.channels = channels

        self.buf_size = int(duration_seconds * sample_rate * sample_width * channels)
        self.buffer = bytearray(self.buf_size)
        self.pos = 0
        self.filled = False  # True once buffer has wrapped at least once
        self.lock = threading.Lock()

    def write(self, data):
        """Append data to ring buffer, wrapping at boundary."""
        with self.lock:
            data_len = len(data)
            if data_len >= self.buf_size:
                # Data larger than buffer — keep only the tail
                self.buffer[:] = data[-self.buf_size:]
                self.pos = 0
                self.filled = True
                return

            end = self.pos + data_len
            if end <= self.buf_size:
                self.buffer[self.pos:end] = data
                self.pos = end
            else:
                first = self.buf_size - self.pos
                self.buffer[self.pos:] = data[:first]
                remainder = data_len - first
                self.buffer[:remainder] = data[first:]
                self.pos = remainder
                self.filled = True

            if self.pos >= self.buf_size:
                self.pos = 0
                self.filled = True

    def get_audio(self):
        """Return full buffer contents in chronological order."""
        with self.lock:
            if not self.filled:
                return bytes(self.buffer[:self.pos])
            return bytes(self.buffer[self.pos:] + self.buffer[:self.pos])

    def get_recent(self, seconds):
        """Return the last N seconds of audio."""
        byte_count = int(seconds * self.sample_rate * self.sample_width * self.channels)
        byte_count = min(byte_count, self.buf_size)
        full = self.get_audio()
        return full[-byte_count:] if len(full) >= byte_count else full

    def clear(self):
        """Zero buffer and reset position."""
        with self.lock:
            self.buffer[:] = b'\x00' * self.buf_size
            self.pos = 0
            self.filled = False


class AudioStreamingOutput:
    """File-like interface that feeds both a ring buffer (always) and a capture
    buffer (when actively recording). Analogous to camera's StreamingOutput."""

    def __init__(self, ring_buffer_seconds=3.0, sample_rate=16000,
                 sample_width=2, channels=1):
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.channels = channels

        self.ring_buffer = AudioRingBuffer(
            duration_seconds=ring_buffer_seconds,
            sample_rate=sample_rate,
            sample_width=sample_width,
            channels=channels,
        )
        self.capture_buffer = io.BytesIO()
        self.capturing = False
        self.condition = threading.Condition()

    def write(self, data):
        """Write audio data to ring buffer (always) and capture buffer (if capturing)."""
        self.ring_buffer.write(data)
        with self.condition:
            if self.capturing:
                self.capture_buffer.write(data)
            self.condition.notify_all()

    def start_capture(self):
        """Begin capturing. Prepend ring buffer contents for pre-trigger context."""
        with self.condition:
            self.capture_buffer = io.BytesIO()
            # Prepend existing ring buffer audio as pre-trigger context
            pre_audio = self.ring_buffer.get_audio()
            if pre_audio:
                self.capture_buffer.write(pre_audio)
            self.capturing = True

    def stop_capture(self):
        """Stop capturing and return the raw audio bytes."""
        with self.condition:
            self.capturing = False
            raw_audio = self.capture_buffer.getvalue()
            self.capture_buffer = io.BytesIO()
        return raw_audio

    @staticmethod
    def get_wav_bytes(raw_audio, sample_rate=16000, sample_width=2, channels=1):
        """Wrap raw PCM data in a WAV header."""
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(raw_audio)
        return buf.getvalue()


if __name__ == '__main__':
    import os

    output_dir = '/home/robot/tmp'
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'test_audio.wav')

    duration = 5
    sample_rate = 16000
    channels = 1
    sample_width = 2

    # Try to auto-detect C920, fall back to default
    device = ALSAMicrophone.find_device('C920') or 'default'

    output = AudioStreamingOutput(
        ring_buffer_seconds=3.0,
        sample_rate=sample_rate,
        sample_width=sample_width,
        channels=channels,
    )

    print(f"Recording {duration} seconds from '{device}'...")
    with ALSAMicrophone(device=device, sample_rate=sample_rate,
                         channels=channels, period_size=1024) as mic:
        output.start_capture()
        mic.start_recording(output)
        time.sleep(duration)
        mic.stop_recording()
        raw_audio = output.stop_capture()

    wav_data = AudioStreamingOutput.get_wav_bytes(
        raw_audio, sample_rate=sample_rate,
        sample_width=sample_width, channels=channels
    )

    with open(output_file, 'wb') as f:
        f.write(wav_data)

    print(f"Saved {len(wav_data)} bytes to {output_file}")
    print(f"Play with: aplay {output_file}")
