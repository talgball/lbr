"""
robttspolly.py - robot text to speech module
    Abstracts for higher level modules to isolate from tts approaches / technology
    This version integrates aws Polly as the tts service.
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2009-2021 Tal G. Ball"
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


import boto3
import os
import time
import io
import subprocess
import tempfile
import threading

from pydub import AudioSegment

from robcom.robmsgdict import messageDict
from robcom import publisher

from lbrsys.settings import AUDIO_DIR


def _aec_sink():
    """Return the configured PulseAudio AEC sink name, or None if AEC is
    disabled. Used to select paplay's --device explicitly rather than
    relying on PULSE_SINK, which SDL-based players (ffplay) only honor
    when SDL happens to pick the pulse audio backend."""
    try:
        from lbrsys.settings import MIC_USE_AEC, MIC_AEC_SINK
    except ImportError:
        return None
    if not MIC_USE_AEC:
        return None
    return MIC_AEC_SINK


class Robtts:
    def __init__(self,language='English',rate=150, voice_id='Kevin'):
        self.engine = boto3.Session(aws_access_key_id=os.environ['ROBOT_AWS_AK'],
                                   aws_secret_access_key=os.environ['ROBOT_AWS_SK'],
                                   region_name='us-west-2').client('polly')

        self.output_format = 'mp3'
        self.supported_formats = ['mp3', 'wav', 'mp4', 'amr', 'amr-wb', 'ogg', 'webm', 'flac']
        self.voice_id = voice_id
        self.language = language
        # self.engine.setProperty('rate', rate) # rate not currently used for this version
        self.speechPub = publisher.Publisher("Speech Publisher")
        # Playback subprocess handle for interruptible speech
        self._play_proc = None
        self._play_lock = threading.Lock()


    # small abstraction in case we need a db / more sophisticated approach
    # at some point.
    #
    def getText(self, msgKey, language):
        try:
            text = messageDict[msgKey][language]['text']
        except:
            print("Error finding standard message from key:", msgKey)
            text = ""
        return text


    def sayNow(self, text):
        return self.say(text)


    def say(self, text):
        pollyResponse = self.engine.synthesize_speech(Engine='neural',
                                                     Text=text,
                                                     OutputFormat=self.output_format,
                                                     VoiceId=self.voice_id)

        audio_bytes = pollyResponse['AudioStream'].read()
        self._play_audio_bytes(audio_bytes, self.output_format)
        self.speechPub.publish(str(text))
        return


    def sayStdNow(self, msgKey, language='English'):
        if msgKey[0] == '<':
            speech_files = os.listdir(AUDIO_DIR)
            for sf in speech_files:
                fname = sf.split('.')
                if len(fname) >= 2:
                    if fname[-1] in self.supported_formats:
                        fmt = fname[-1]
                        if fname[0] == msgKey[1:].lower():
                            sf_path = os.path.join(AUDIO_DIR, sf)
                            self._play_file(sf_path)
                            return

        # by default, say as normal
        self.say(msgKey)
        return

    def _play_audio_bytes(self, audio_bytes, fmt):
        """Decode the synth output to WAV and play it. paplay (used when
        AEC is enabled) only accepts WAV/raw, so we always normalize to
        WAV. Blocks until playback completes or is interrupted via stop()."""
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            tmp_path = f.name
        try:
            seg.export(tmp_path, format='wav')
            self._play_file(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _play_file(self, path):
        """Play an audio file, retaining the Popen handle so stop() can
        terminate playback mid-utterance. When AEC is enabled, we route
        via paplay --device=<sink> so the speaker stream is guaranteed to
        go through the echo-cancel module as the reference signal.
        paplay plays WAV natively; MP3 has already been decoded upstream."""
        sink = _aec_sink()
        if sink and path.lower().endswith('.wav'):
            cmd = ['paplay', '--device=' + sink, path]
        else:
            cmd = ['ffplay', '-nodisp', '-autoexit', '-hide_banner',
                   '-loglevel', 'error', path]
        with self._play_lock:
            self._play_proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
            )
            proc = self._play_proc
        proc.wait()
        with self._play_lock:
            if self._play_proc is proc:
                self._play_proc = None

    def stop(self):
        """Abort any in-flight speech playback immediately."""
        with self._play_lock:
            proc = self._play_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()


    def sayStd(self, msgKey, language='English'):
        return self.sayStdNow()


    def save(self, text, fileName):
        pollyResponse = self.engine.synthesize_speech(Engine='neural',
                                                     Text=text,
                                                     OutputFormat=self.output_format,
                                                     VoiceId=self.voice_id)

        with open(fileName, 'wb') as f:
            f.write(pollyResponse['AudioStream'].read())
            f.close()


def main(testSentences, tts=None):
    if not tts:
        tts = Robtts()

    for s in testSentences:
        # tts.sayNow(s)
        print(s)

    for mk in messageDict.keys():
        tts.sayStdNow(mk, 'English')


#externalize later
testSentences  = ["Hello, world!",
                  "This is a test of my text to speech system.",
                  "This is only a test.",
                  "Now is the time for all good people to come to the aid of their country."]

if __name__ == '__main__':
    tts = Robtts()
    main(testSentences, tts)
