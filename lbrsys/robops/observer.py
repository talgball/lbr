#
# observer - facilities to watch for, in this case, a turning angle to be achieved
#

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


import multiprocessing
import threading
import time
from time import time as robtimer
import os
import logging
import queue

from lbrsys import gyro


class Observer(object):
    def __init__(self,angle,qOut,curtime=None,testMode=False):
        if not curtime:
            self.curtime = robtimer()
        else:
            self.curtime = curtime
            
        self.targetAngle    = angle
        self.qOut           = qOut
        self.observed       = False
        self.missed         = False
        self.cumulativeAngle= 0
        self.lastAngleSpeed = 0
        self.startTime      = self.curtime
        self.lastTime       = self.curtime
        self.totalUpdates   = 0
        self.totalTime      = 0
        self.speedSum       = 0
        self.observed       = False
        self.dLF            = open('./gyrReadings.log','w')
        self.dLF.write("N\tz\tt\tdeltat\ttotalt\ttotala\n")

        self.testMode       = testMode
        self.sampleFileName = './gyrosample.log'
        self.sampleFile     = None
        logging.debug("Initialized Observer for angle %s" % (self.targetAngle,))
        print("Initialized Observer for angle %s at %.4f" % \
              (self.targetAngle,time.clock()))

    def update(self,reading):

        if not isinstance(reading, gyro):
            return
        else:
            gyroReading = reading

        self.totalUpdates += 1

        self.curtime = gyroReading.t

        if gyroReading.z:
            angleSpeed = abs(gyroReading.z)
        else:
            angleSpeed = self.lastAngleSpeed
            
        self.speedSum += angleSpeed
        deltat = self.curtime - self.lastTime
        self.totalTime += deltat
        
        if angleSpeed != 0 and self.lastAngleSpeed == 0:
            print('Turn started after %f' % (self.totalTime))
                         
        self.cumulativeAngle += (angleSpeed + self.lastAngleSpeed)/2.0 * deltat

        self.dLF.write('%d\t%2.2f\t%.4f\t%.4f\t%.4f\t%.4f\n' %\
                    (self.totalUpdates,angleSpeed,gyroReading.t,
                     deltat,self.totalTime,self.cumulativeAngle))

        self.lastAngleSpeed = angleSpeed
        self.lastTime = self.curtime

        if self.cumulativeAngle >= abs(self.targetAngle):
            self.qOut.put(('Observed',self.cumulativeAngle,self.totalTime))
            self.observed = True
            reportStr = "Angle observed: %.2f, elapsed: %.4f, updates: %d, avg speed %.2f deg/sec"
            logging.debug(reportStr % \
                          (self.cumulativeAngle,self.totalTime,
                           self.totalUpdates, self.speedSum/self.totalUpdates))
            print(reportStr % \
                          (self.cumulativeAngle,self.totalTime,
                           self.totalUpdates, self.speedSum/self.totalUpdates))
            print("Completed at", time.asctime())
            
            self.dLF.close()

            
    def getTestData(self):
        if not self.sampleFile:
            try:
                self.sampleFile = open(self.sampleFileName,'r')
            except:
                print('error opening test data file',self.sampleFileName)
                raise
            self.sampleData = self.sampleFile.readlines() # assumes 'small' test data
            self.sampleFile.close()
            self.numSamples = len(self.sampleData)
            self.curSample = 0
        if self.curSample < self.numSamples:
            line = self.sampleData[self.curSample]
            readings = line[29:].split(',') #unforgiving - based on current log format
            sample = float(readings[2])
            self.curSample += 1
        else:
            sample = 30.0
        logging.debug("test sample: z=%f" % (sample,))
        return gyro(0,0,sample)


        
if __name__ == '__main__':
    q_out = queue.Queue()
    
    o = Observer(qOut=q_out,angle=90,testMode=True)
    
    t1 = time.time()
    while True:
        reading = o.getTestData()
        o.update(reading)
        if not q_out.empty():
            m = q_out.get()
            print(str(m))
            break

    print('Elapsed time:',time.time()-t1)


    
