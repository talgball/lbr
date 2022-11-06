"""
speech service
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


import time
from time import time as robtimer
import logging
import os
import multiprocessing
import threading
import queue
from datetime import datetime

from lbrsys.settings import SPEECH_SERVICE, AUDIO_DIR, speechLogFile
from lbrsys import speech

if SPEECH_SERVICE == 'aws_polly':
    from robcom import robttspolly as robtts
else:
    from robcom import robtts

proc = multiprocessing.current_process()

if proc.name  == 'Speech Services':
    logging.basicConfig( level=logging.DEBUG,
                         filename=speechLogFile,
                         format='[%(levelname)s] (%(processName)-10s) %(message)s', )


class SpeechService:
    def __init__(self, commandQ=None, broadcastQ=None):
        self.commandQ   = commandQ
        self.broadcastQ = broadcastQ
        self.tts = robtts.Robtts()
        self.tts.speechPub.addSubscriber(self.genericSubscriber)

        self.curtime = robtimer()
        #self.minLoopTime = 0.010
        ta = time.asctime()
        startmsg = "\n\n%s: Starting Speech Operations" % (ta,)
        #print startmsg
        logging.debug(startmsg)
        self.start()


    def start(self):
        self.tts.sayStdNow("<Hello")

        while True:
            # don't need the more sophisticated loop since this is essentially
            #   an output service
            task = self.commandQ.get()

            if task == 'Shutdown':
                self.tts.sayStdNow("<Goodbye")
                break
            else:
                #to do: add support for std dictionary
                if type(task) is speech:
                    if task.save == '':
                        if task.msg[0] == '<':
                            self.tts.sayStdNow(task.msg)
                        else:
                            self.tts.sayNow(task.msg)
                    else:
                        if SPEECH_SERVICE == 'native':
                            print("Speech save not supported for service native.")
                        else:
                            # file_name = f"{datetime.now()}.mp3"
                            file_name = f"{task.save}.mp3"
                            full_name = os.path.join(AUDIO_DIR, file_name)
                            print(f"Saving audio file to {full_name}")
                            self.tts.save(task.msg, full_name)
                else:
                    self.tts.sayNow(str(task))
            
        self.end()
        

    def genericSubscriber(self,msg):

        logging.debug('%s: Said: "%s"' % (time.asctime(),str(msg)))
        #to do: consider adding a broadcastQ message..

    def end(self):
        ta = time.asctime()
        endmsg = "%s: Speech Operations Ended.\n____________" % (ta,)
        #print endmsg
        logging.debug(endmsg)


if __name__ == '__main__':
    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()
    s = threading.Thread(target=SpeechService, name="Speech Services",
                         args=(cq,bq))
    s.start()

    cq.put("Testing speech service.")
    cq.put("Now is the time for all good robots to learn to speak.")

    print("Press Enter to End.")
    input("")
    cq.put("Shutdown")
    s.join()
    
