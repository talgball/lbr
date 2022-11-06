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

from pydub import AudioSegment
from pydub.playback import play

from robcom.robmsgdict import messageDict
from robcom import publisher

from lbrsys.settings import AUDIO_DIR


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

        with io.BytesIO() as f: # use a memory stream
            f.write(pollyResponse['AudioStream'].read())
            f.seek(0)
            sound = AudioSegment.from_file(f, format=self.output_format)
            play(sound)

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
                            # print(f"Matched saved audio file: {sf_path}")
                            sound = AudioSegment.from_file(sf_path, format=fmt)
                            play(sound)
                            return

        # by default, say as normal
        self.say(msgKey)
        return


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
