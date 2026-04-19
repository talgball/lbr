"""
robtts.py - robot text to speech module
    Abstracts for higher level modules to isolate from tts approaches / technology
    Will implement the event api for the engine when needed.
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2009-2020 Tal G. Ball"
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
import subprocess
import tempfile
import threading

import pyttsx3

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
        self.engine = pyttsx3.init()
        self.language = language
        self.engine.setProperty('rate', rate)
        self.speechPub = publisher.Publisher("Speech Publisher")
        self.output_format = 'mp3'
        self.supported_formats = ['mp3', 'wav', 'mp4', 'amr', 'amr-wb', 'ogg', 'webm', 'flac']
        self.voice_id = voice_id
        # Playback subprocess handle for interruptible speech.
        # pyttsx3's engine.stop() does not work on the espeak backend, so
        # we synthesize to a file and play via an external subprocess we
        # can terminate.
        self._play_proc = None
        self._play_lock = threading.Lock()


    #small abstraction in case we need a db / more sophisticated approach
    # at some point.
    #More importantly, it gives apps the chance to build text from
    #
    def getText(self, msgKey, language):
        try:
            text = messageDict[msgKey][language]['text']
        except:
            print("Error finding standard message from key:", msgKey)
            text = ""
        return text


    def sayNow(self, text):
        self._synth_and_play(text)
        self.speechPub.publish(str(text))


    def say(self, text):
        # Legacy API — retained for compatibility; behaves like sayNow now
        # since the blocking vs non-blocking distinction came from pyttsx3's
        # own event loop which we no longer use.
        self._synth_and_play(text)
        self.speechPub.publish(str(text))


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


    def sayStd(self, msgKey, language='English'):
        if not language:
            language = self.language
        text = self.getText(msgKey, language)
        if text:
            self.say(text)

    def _synth_and_play(self, text):
        """Synthesize text to a WAV via pyttsx3.save_to_file, then play via
        ffplay subprocess so the utterance can be interrupted."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            tmp_path = f.name
        try:
            self.engine.save_to_file(text, tmp_path)
            self.engine.runAndWait()
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
        go through the echo-cancel module as the reference signal. paplay
        plays WAV natively (pyttsx3's synth output is already WAV)."""
        sink = _aec_sink()
        if sink:
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
