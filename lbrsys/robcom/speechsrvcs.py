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
import re
import multiprocessing
import threading
import queue
from datetime import datetime

from lbrsys.settings import SPEECH_SERVICE, SPEECH_GREETINGS, AUDIO_DIR, speechLogFile
from lbrsys import speech, speech_control, set_process_title


_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')

if SPEECH_SERVICE == 'aws_polly':
    from robcom import robttspolly as robtts
else:
    from robcom import robtts

proc = multiprocessing.current_process()

if proc.name  == 'Speech Services':
    logging.basicConfig( level=logging.DEBUG,
                         filename=speechLogFile,
                         format='[%(levelname)s] (%(processName)-10s) %(message)s', )
    set_process_title()


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

        # Sentence-level work queue drained by a dedicated worker thread.
        # Main thread stays responsive to speech_control('stop') while the
        # worker is blocked inside ffplay.
        self._work_q = queue.Queue()
        # Set by _handle_stop to tell the worker to drop remaining sentences
        # of the current utterance. Cleared at the start of the next one.
        self._abort_utterance = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop,
                                        name="SpeechWorker", daemon=True)
        self._worker.start()

        self.start()


    def _publish_control(self, action):
        """Emit speech_control on broadcastQ. Routed to Microphone channel
        via channelMap so the mic can self-mute during TTS."""
        if self.broadcastQ is None:
            return
        try:
            self.broadcastQ.put(speech_control(action))
        except Exception as e:
            logging.debug("speech_control publish failed: %s" % e)


    def _worker_loop(self):
        """Drain the internal work queue, synthesizing and playing one
        sentence at a time so the main loop can interrupt between (or
        during) sentences."""
        speaking = False
        while True:
            item = self._work_q.get()
            try:
                if item is None:
                    # Shutdown sentinel
                    if speaking:
                        self._publish_control('speaking_end')
                        speaking = False
                    return

                kind, payload = item

                if kind == 'begin':
                    self._abort_utterance.clear()
                    if not speaking:
                        self._publish_control('speaking_start')
                        speaking = True
                elif kind == 'sentence':
                    if not self._abort_utterance.is_set():
                        try:
                            self.tts.sayNow(payload)
                        except Exception as e:
                            logging.debug("tts.sayNow error: %s" % e)
                elif kind == 'std':
                    if not self._abort_utterance.is_set():
                        try:
                            self.tts.sayStdNow(payload)
                        except Exception as e:
                            logging.debug("tts.sayStdNow error: %s" % e)
                elif kind == 'save':
                    msg, full_name = payload
                    try:
                        self.tts.save(msg, full_name)
                    except Exception as e:
                        logging.debug("tts.save error: %s" % e)
                elif kind == 'end':
                    if speaking:
                        self._publish_control('speaking_end')
                        speaking = False
            finally:
                self._work_q.task_done()


    def _enqueue_speech(self, task):
        """Break a speech task into sentence-sized work items for the
        worker, bracketed by begin/end markers."""
        if task.save != '':
            if SPEECH_SERVICE == 'native':
                print("Speech save not supported for service native.")
                return
            file_name = f"{task.save}.mp3"
            full_name = os.path.join(AUDIO_DIR, file_name)
            print(f"Saving audio file to {full_name}")
            self._work_q.put(('save', (task.msg, full_name)))
            return

        msg = task.msg
        if not msg:
            return

        if msg[0] == '<':
            # Standard message key — single unit, no sentence splitting.
            self._work_q.put(('begin', None))
            self._work_q.put(('std', msg))
            self._work_q.put(('end', None))
            return

        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(msg) if s.strip()]
        if not sentences:
            return
        self._work_q.put(('begin', None))
        for s in sentences:
            self._work_q.put(('sentence', s))
        self._work_q.put(('end', None))


    def _handle_stop(self):
        """Abort any in-flight utterance and discard queued sentences of
        the current utterance. Sentences belonging to utterances queued
        *after* the current one are preserved."""
        self._abort_utterance.set()
        try:
            self.tts.stop()
        except Exception as e:
            logging.debug("tts.stop error: %s" % e)

        # Drain sentence/std items up to the next 'end' so the worker emits
        # a clean speaking_end and the mic un-mutes. Preserve anything after
        # that 'end' — those belong to a subsequent utterance.
        preserved = []
        saw_end = False
        try:
            while True:
                item = self._work_q.get_nowait()
                try:
                    if not saw_end:
                        kind = item[0]
                        if kind in ('sentence', 'std'):
                            continue
                        if kind == 'end':
                            saw_end = True
                            preserved.append(item)
                            continue
                        # begin/save from a subsequent utterance — keep
                        preserved.append(item)
                        saw_end = True
                    else:
                        preserved.append(item)
                finally:
                    self._work_q.task_done()
        except queue.Empty:
            pass

        for item in preserved:
            self._work_q.put(item)


    def start(self):
        if SPEECH_GREETINGS:
            self._enqueue_speech(speech(msg="<Hello", save=''))

        while True:
            task = self.commandQ.get()

            if task == 'Shutdown':
                if SPEECH_GREETINGS:
                    self._enqueue_speech(speech(msg="<Goodbye", save=''))
                self._work_q.put(None)
                self._worker.join(timeout=5.0)
                break

            if type(task) is speech_control:
                if task.action == 'stop':
                    self._handle_stop()
            elif type(task) is speech:
                self._enqueue_speech(task)
            else:
                # Fallback — plain string or legacy payload.
                self._enqueue_speech(speech(msg=str(task), save=''))

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
    
