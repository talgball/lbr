"""
headingobserver - facilities to watch for a compass heading to be achieved
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


import logging
import queue
from time import time as robtimer # legacy naming issue
import time

from lbrsys import mpuData
from lbrsys.settings import headingobserverLogFile
from .opsmgr import calcDirection

class HeadingObserver(object):

    def __init__(self, heading, qOut, curtime=None, testMode=False):
        if not curtime:
            self.curtime = robtimer()
        else:
            self.curtime = curtime
            
        self.achievedTolerance      = 3.0 # degrees
        self.missedTolerance        = 20.0
        self.target         = heading
        self.qOut           = qOut
        self.lastHeading    = -900
        self.prevd          = -900.
        self.direction      = 0
        self.startTime      = self.curtime
        self.lastTime       = self.curtime
        self.totalUpdates   = 0
        self.totalTime      = 0
        self.observed       = False
        self.missed         = False
        self.dLF            = open(headingobserverLogFile,'w')
        self.dLF.write("N\ttarget\theading\tlastd\tdir\tt\tdeltat\ttotalt\n")
        self.testMode       = testMode

        logging.debug("Initialized Heading Observer for heading %s" % (self.target,))
        print("Initialized Observer for heading %s at %s" % \
              (self.target, time.asctime()))


    def headingAchieved(self, current, target):
        withinTolerance = False
        missed = False

        direction, dcw, dccw = calcDirection(current, target)


        if direction == 90: # clockwise
            d = dcw
            if abs(dcw) <= self.achievedTolerance:
                withinTolerance = True
            else:
                if abs(dcw) > abs(self.prevd) + self.missedTolerance:
                    missed = True
        else:
            d = dccw
            if abs(dccw) <= self.achievedTolerance:
                withinTolerance = True
            else:
                if abs(dccw) > abs(self.prevd) + self.missedTolerance:
                    missed = True

        self.prevd = d
        self.direction = direction
        return withinTolerance, missed


    def update(self,reading):

        if not isinstance(reading, mpuData):
            return
        else:
            mpuReading = reading

        self.totalUpdates += 1
        self.curtime = mpuReading.time
        curHeading = mpuReading.heading

        deltat = self.curtime - self.lastTime
        self.totalTime += deltat

        self.lastTime = self.curtime

        self.withinTolerance, self.missed = self.headingAchieved(curHeading, self.target)

        if self.withinTolerance:
            self.observed = True
            self.qOut.put(('Observed', curHeading, self.totalTime))

            reportStr = "Heading observed: %.1f, elapsed: %.3f, updates: %d"
            logging.debug(reportStr % \
                          (curHeading, self.totalTime, self.totalUpdates, ))
            print(reportStr % \
                          (curHeading, self.totalTime,
                           self.totalUpdates, ))
            print("Completed at", time.asctime())

        elif self.missed:
            self.observed = False
            self.qOut.put(('Missed', curHeading, self.totalTime))

            reportStr = "Heading missed: %.1f, elapsed: %.3f, updates: %d"
            logging.debug(reportStr % \
                          (curHeading, self.totalTime,
                           self.totalUpdates, ))
            print(reportStr % \
                          (curHeading, self.totalTime,
                           self.totalUpdates, ))
            print("Completed at", time.asctime())


        self.dLF.write('%d\t%2.2f\t%2.2f\t%2.2f\t%d\t%.4f\t%.4f\t%.4f\n' %\
                    (self.totalUpdates, self.target, curHeading, self.prevd,
                     self.direction, self.curtime, deltat,self.totalTime))

        self.lastHeading = curHeading

        if self.missed or self.withinTolerance:
            self.dLF.close()

        return


if __name__ == '__main__':
    import sys
    sys.path.append('../robdrivers')
    import mpu9150rpi
    mpu = mpu9150rpi.MPU9150_A()
    q_out = queue.Queue()
    o = HeadingObserver(qOut=q_out, heading=90, testMode=False)

    timeout = 30.
    t1 = time.time()

    while True:
        reading = mpu.read()
        o.update(reading)
        if not q_out.empty():
            m = q_out.get()
            print(str(m))
            break
        if time.time()-t1 > timeout:
            print("timed out")
            break

    print('Elapsed time:',time.time()-t1)

