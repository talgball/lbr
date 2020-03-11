"""
range operations service communicate range information to the system
    and manage range sensors
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
import pprint
import logging
import os
import multiprocessing
import threading
import queue

from lbrsys.settings import rangeLogFile
from lbrsys import observeRange

import robdrivers.p8x32lbr
from robops import rangeobserver

proc = multiprocessing.current_process()

if proc.name  == 'Range Services': # or proc.name == 'MainProcess':
    logging.basicConfig(
        level=logging.DEBUG,
        filename=rangeLogFile,
        format='[%(levelname)s] (%(processName)-10s) %(message)s')


class Rangeservice(object):
    def __init__(self, commandQ=None, broadcastQ=None): # extQ=None):
        self.commandQ   = commandQ
        self.broadcastQ = broadcastQ
        # self.extQ       = extQ
        self.rangemcu   = robdrivers.p8x32lbr.P8X32()
        self.lastLogTime= 0
        self.logInterval= 2.0
        self.lastExtSend= 0
        self.rangeReportInterval = 0.5
        self.lastRangeReportTime = 0.
        self.extInterval= 1
        self.waitTime   = 0.100 # the mb1220 range sensors have a 10Hz read rate
        self.observers  = []
        self.rangemcu.rangePub.addSubscriber(self.genericSubscriber)
        self.rangemcu.rangePub.addSubscriber(self.updateObservers)
        self.curtime = robtimer()
        #self.minLoopTime = 0.010
        ta = time.asctime()
        startmsg = "\n\n%s: Starting Range Operations" % (ta,)
        #print startmsg
        logging.debug(startmsg)
        self.start()

    def start(self):
        self.curtime = robtimer()
        
        opsStats = {'totalLoopTime':0, 'numLoops':0,
                    'successfulReadings':0, 'badReadings':0}

        lastWaitStart = 0
        
        while True:
            loopStartTime = robtimer()
            opsStats['numLoops'] += 1

            good, ranges = self.rangemcu.read()

            if good:
                # print("Range: %d" % ranges['Ranges']['Forward'])
                opsStats['successfulReadings'] += 1
                if robtimer() - self.lastRangeReportTime > self.rangeReportInterval:
                    self.broadcastQ.put(ranges)
                    self.lastRangeReportTime = robtimer()
            else:
                opsStats['badReadings'] +=1
            
            if not self.commandQ.empty():
                task = self.commandQ.get_nowait()
                logging.debug("%s: rangeops task is: %s" % (time.asctime(),str(task)))
                self.execTask(task)
                self.commandQ.task_done()
                if task == 'Shutdown':
                    self.processStats(opsStats)
                    break

            elapsedTime = robtimer() - loopStartTime
            time.sleep(self.waitTime)
                
            opsStats['totalLoopTime'] += robtimer() - loopStartTime
            
        self.end()

        
    def genericSubscriber(self,msg):
        
        if robtimer() - self.lastLogTime >= self.logInterval:
            logging.debug("%s: F: %.2f, BTM: %.2f, L: %.2f, R: %.2f, B: %.2f, DT: %.2fms, T: %.2fms" \
                          % (time.asctime(),      
                            msg['Ranges']['Forward'], 
                            msg['Ranges']['Bottom'],
                            msg['Ranges']['Left'],
                            msg['Ranges']['Right'],
                            msg['Ranges']['Back'],
                            msg['Ranges']['Deltat']  / 80000000.0 * 1000.0,
                            msg['Timestamp'] * 1000.0))
            
            self.lastLogTime = robtimer()

    def rangeSender(self,msg):
        if self.extQ:
            if robtimer() - self.lastExtSend >= self.extInterval:
                print("sending range: %s" % (str(msg),))
                self.extQ.put(msg)
                self.lastExtSend = robtimer()
        
    def execTask(self, task):
        if type(task) is observeRange:
            self.addObserver(task.nav, self.broadcastQ)


    def addObserver(self, navdata, qOut):
        rangeObserver = rangeobserver.RangeObserver(navdata, qOut)
        self.observers.append(rangeObserver)
        return rangeObserver


    def removeObserver(self, observer):
        if observer in self.observers:
            self.observers.remove(observer)


    def updateObservers(self, reading):
        for observer in self.observers:
            if not observer.observed and not observer.missed:
                observer.update(reading)
            else:
                self.removeObserver(observer)


    def processStats(self,opsStats):
        opsStats['AverageLoopTime'] = opsStats['totalLoopTime']/opsStats['numLoops']
        logging.debug("Ranger Service Operational Stats\n%s\n" % (pprint.pformat(opsStats)))


    def end(self):
        self.rangemcu.close()

if __name__ == '__main__':
    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()
    # eq = multiprocessing.JoinableQueue()

    r = threading.Thread(target=Rangeservice, name="Range Services",
                         args=(cq, bq))
    r.start()
    
    time.sleep(3) # time to start ranging
    t0 = time.time()

    cq.put(observeRange(20))
    while (time.time() - t0) < 15:
        if not bq.empty():
            m = bq.get()
            bq.task_done()
            if type(m) is tuple:
                pprint.pprint("Bq: " + str(m))
                break
        time.sleep(0.1)
    
    cq.put('Shutdown')
    cq.join()

