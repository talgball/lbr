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
import pyttsx3

from pydub import AudioSegment
from pydub.playback import play

from robcom.robmsgdict import messageDict
from robcom import publisher
from lbrsys.settings import AUDIO_DIR


class Robtts:
    def __init__(self,language='English',rate=150, voice_id='Kevin'):
        self.engine = pyttsx3.init()
        self.language = language
        self.engine.setProperty('rate', rate)
        self.speechPub = publisher.Publisher("Speech Publisher")
        self.output_format = 'mp3'
        self.supported_formats = ['mp3', 'wav', 'mp4', 'amr', 'amr-wb', 'ogg', 'webm', 'flac']
        self.voice_id = voice_id


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
        self.engine.say(text)
        self.engine.runAndWait()
        self.speechPub.publish(str(text))


    def say(self, text):
        self.engine.say(text)
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
                            # print(f"Matched saved audio file: {sf_path}")
                            sound = AudioSegment.from_file(sf_path, format=fmt)
                            play(sound)
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
