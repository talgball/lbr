"""
motion processing service - Provide the mpu data from the
   motion sensors to the overall system
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2020 Tal G. Ball"
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
import sys
import os
import multiprocessing
import threading
import queue

if __name__ == '__main__':
    sys.path.append('..')

from lbrsys import power, gyro, observeHeading, observeTurn
from lbrsys import calibrateMagnetometer
from lbrsys.settings import mpLogFile

# import robdrivers.mpu9150rpi
from lbrsys.robops import observer
from lbrsys.robops import headingobserver

from lbrsys.settings import RIOX_1216AHRS_Port

# todo find a more elegant abstraction for the MPU
if RIOX_1216AHRS_Port is not None:
    import lbrsys.robdrivers.riox_1216ahrs as mpu_driver
    MPU_CLASS = mpu_driver.RIOX
else:
    import lbrsys.robdrivers.mpu9150rpi as mpu_driver
    MPU_CLASS = mpu_driver.MPU9150_A

proc = multiprocessing.current_process()

if proc.name  == 'Motion Processing Services':# or proc.name == 'MainProcess':
    logging.basicConfig( level=logging.DEBUG,
                     filename=mpLogFile,
                     format='[%(levelname)s] (%(processName)-10s) %(message)s', )

class MPservice(object):
    def __init__(self,commandQ=None, broadcastQ=None):
        self.commandQ   = commandQ
        self.broadcastQ = broadcastQ
        # self.mpu       = robdrivers.mpu9150rpi.MPU9150_A()
        self.mpu = MPU_CLASS()
        self.lastLogTime= 0
        self.observers  = []
        self.mpu.gyroPub.addSubscriber(self.genericSubscriber)
        self.mpu.gyroPub.addSubscriber(self.updateObservers)
        self.mpu.mpuPub.addSubscriber(self.genericSubscriber)
        self.mpu.mpuPub.addSubscriber(self.updateObservers)
        self.curtime = robtimer()
        # self.minLoopTime = 0.010
        self.minLoopTime = 0.100
        self.mpuLogInterval = 15.
        self.mpuReportInterval = 2.
        self.lastMpuReportTime = 0.

        ta = time.asctime()
        startmsg = "%s: Starting Motion Processing Operations" % (ta,)
        # print startmsg
        logging.debug(startmsg)
        logging.debug("commandQ = %s\nbroadcastQ = %s" %
                      (str(commandQ),str(broadcastQ)))
        self.start()

    def start(self):
        self.curtime = robtimer()
        
        opsStats = {'totalLoopTime':0, 'numLoops':0,
                    'totalWaitTime':0, 'numWaits':0,
                    'successfulReadings':0, 'badReadings':0}

        lastWaitStart = 0
        gyroReading = gyro(0,0,0,self.curtime)
            
        while True:
            loopStartTime = robtimer()
            opsStats['numLoops'] += 1

            mpuReading = self.mpu.read()
            gyroReading = mpuReading.gyro
            #logging.debug("%s",(str(mpuReading),))
            
            if gyroReading.z != None :
                opsStats['successfulReadings'] += 1
                if robtimer() - self.lastMpuReportTime > self.mpuReportInterval:
                    self.broadcastQ.put(mpuReading)
                    self.lastMpuReportTime = robtimer()
            else:
                opsStats['badReadings'] +=1
            
            if not self.commandQ.empty():
                task = self.commandQ.get_nowait()
                logging.debug("%s: mpops task is: %s" % (time.asctime(), str(task)))
                self.commandQ.task_done()
                self.execTask(task)
                
                if task == 'Shutdown':
                    self.processStats(opsStats)
                    break

            elapsedTime = robtimer() - loopStartTime
            waitTime = self.minLoopTime - elapsedTime
        
            if waitTime > 0:
                opsStats['totalWaitTime'] += waitTime
                opsStats['numWaits'] += 1
            else:
                waitTime = 0

            time.sleep(waitTime)
                
            opsStats['totalLoopTime'] += robtimer() - loopStartTime
            
        self.end()

        
    def genericSubscriber(self,msg):
        if self.lastLogTime == 0:
            logging.debug('\n\n%s: Initiating motion processing logging.' %\
                          (time.asctime(),))
            logging.debug(str(msg))
            self.lastLogTime = time.time()
        if robtimer() - self.lastLogTime >= self.mpuLogInterval:
            logging.debug(str(msg))
            self.lastLogTime = time.time()

 
    def execTask(self, task):
        logging.debug("executing mpops task: " + str(task))

        if isinstance(task, observeTurn):
            if task.angle == -1:  # this shutdown method is obsolete
                self.commandQ.put('Shutdown')
            else:
                turnObserver = self.addObserver(task.angle, self.broadcastQ)

        if isinstance(task, observeHeading):
            headingObserver = self.addHeadingObserver(task.heading, self.broadcastQ)

        if type(task) is calibrateMagnetometer:
            try:
                self.mpu.calibrateMag(task.samples, task.source)
                # self.broadcastQ.put(power(0., 0))  # redundant with finally.
            except Exception as e:
                print(f"Error calibrating magnetometer\n{str(e)}")
            finally:
                self.broadcastQ.put(power(0., 0))


    def addObserver(self,angle,qOut):
        logging.debug("Initiating turn observation for angle %d" % angle)
        turnObserver = observer.Observer(angle,qOut)
        self.observers.append(turnObserver)
        return turnObserver

    def addHeadingObserver(self, heading, qOut):
        logging.debug("Initiating turn observation for heading %d" % heading)
        turnObserver = headingobserver.HeadingObserver(heading, qOut)
        self.observers.append(turnObserver)
        return turnObserver


    def removeObserver(self,turnObserver):
        if turnObserver in self.observers:
            self.observers.remove(turnObserver)

    def updateObservers(self, reading):
        for turnObserver in self.observers:
            if not turnObserver.observed and not turnObserver.missed:
                turnObserver.update(reading)
            else:
                self.removeObserver(turnObserver)
        
    def processStats(self,opsStats):
        opsStats['AverageLoopTime'] = opsStats['totalLoopTime']/opsStats['numLoops']
        if opsStats['numWaits'] != 0:
            opsStats['AverageWaitTime:'] = opsStats['totalWaitTime']/opsStats['numWaits']
        logging.debug("Motion Processing Services Operational Statistics")
        logging.debug("%s\n" % (pprint.pformat(opsStats)))

    def end(self):
        self.mpu.close()



def genericSubscriber(msg):
    print((str(msg)))

if __name__ == '__main__':
    import robdrivers
    #import robdrivers.ax500
    import robdrivers.sdc2130
    from robops import movepa
    #motorController = robdrivers.ax500.AX500()
    motorController = robdrivers.sdc2130.SDC2130()
    mover = movepa.Movepa(motorController)
    motorController.messagePub.addSubscriber(genericSubscriber)
    motorController.voltagePub.addSubscriber(genericSubscriber)
    motorController.voltagePub.addSubscriber(genericSubscriber)
    motorController.ampsPub.addSubscriber(genericSubscriber)
    #motorController.motorControlPub.addSubscriber(genericSubscriber)

    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()
    g = threading.Thread(target=MPservice,args=(cq,bq))
    g.start()
    print("Give mpu time for gyro calibration")
    time.sleep(2)
    
    print("sending turn observer request")
    cq.put(observeTurn(90))
    while True:
        if not bq.empty():
            m = bq.get()
            print(str(m))
            break
        else:
             mover.movepa(power(0.2,90))
        time.sleep(0.100)
             
    mover.movepa(power(0.,0.))
    
    cq.put('Shutdown')
    motorController.closeController()
    
    
