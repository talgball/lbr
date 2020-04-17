"""
rangeobserver - facilities to watch for a range to be achieved

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


import logging
import queue

from time import time as robtimer # legacy naming issue
import time

from lbrsys import power, nav


class RangeObserver(object):
    def __init__(self, navdata, qOut, curtime=None, testMode=False):
        if not curtime:
            self.curtime = robtimer()
        else:
            self.curtime = curtime

        self.maxRange = 768
        self.minRange = 17
        self.achievedTolerance = 1.0 # centimeters
        self.withinTolerance = False
        self.navdata        = navdata
        self.target         = navdata.range
        self.sensor         = navdata.sensor
        self.qOut           = qOut
        self.lastrange      = -900
        self.startTime      = self.curtime
        self.lastTime       = self.curtime
        self.totalUpdates   = 0
        self.totalTime      = 0
        self.observed       = False
        self.missed         = False
        self.dLF            = open('./rangeReadings.log', 'w')
        self.dLF.write("N\ttarget\trange\tdeltat\ttotalt\n")
        self.testMode       = testMode

        trange = self.target

        urange = trange
        if trange > self.maxRange:
            trange = self.maxRange
        elif trange < self.minRange:
            trange = self.minRange
        if trange != urange:
            self.target = trange
            msg = "Range Observer target clamped to %d, was %d" % (trange, urange)
            print(msg)
            logging.info(msg)

        logging.debug("Initialized Range Observer for range %s, sensor %s" %
                      (self.target, self.sensor))
        print("Initialized Observer for range %s, sensor %s at %s" % \
              (self.target, self.sensor, time.asctime()))


    def rangeAchieved(self, current, target):
        withinTolerance = False
        missed = False

        delta = current - target

        if abs(delta) <= self.achievedTolerance:
            withinTolerance = True
        elif current < (target - self.achievedTolerance) \
                or current > self.maxRange:
            missed = True

        return withinTolerance, missed


    def update(self, reading):
        currange = reading['Ranges'][self.sensor]
        self.curtime = reading['Timestamp']
        self.totalUpdates += 1

        # print("Range updated to %d" % currange)

        deltat = self.curtime - self.lastTime
        self.totalTime += deltat

        self.lastTime = self.curtime

        self.withinTolerance, self.missed = self.rangeAchieved(currange, self.target)

        if self.withinTolerance:
            self.observed = True
            self.qOut.put(('Observed', currange, self.totalTime))

            reportStr = "range observed: %.1f, elapsed: %f, updates: %d"
            logging.debug(reportStr % \
                          (currange, self.totalTime, self.totalUpdates, ))
            print(reportStr % \
                          (currange, self.totalTime,
                           self.totalUpdates, ))
            print("Completed at", time.asctime())

        elif self.missed:
            self.observed = False
            self.qOut.put(('Missed', currange, self.totalTime))

            reportStr = "range missed: %f, elapsed: %f, updates: %d"
            logging.debug(reportStr % \
                          (currange, self.totalTime,
                           self.totalUpdates, ))
            print(reportStr % \
                          (currange, self.totalTime,
                           self.totalUpdates, ))
            print("Completed at", time.asctime())


        self.dLF.write('%d\t%2.2f\t%2.2f\t%.4f\t%.4f\t%.4f\n' %\
                    (self.totalUpdates, self.target, currange,
                     self.curtime, deltat,self.totalTime))

        if self.lastrange != currange:
            # print("Range: %d" % currange)
            self.lastrange = currange

        if self.missed or self.withinTolerance:
            self.dLF.close()

        return


if __name__ == '__main__':
    import sys
    sys.path.append('../robdrivers')
    import p8x32lbr
    mpu = p8x32lbr.P8X32()
    mpu.flush()
    good, readings = mpu.read()

    q_out = queue.Queue()
    navdata = nav(power(0, 0), 20, 'Back', 0)
    o = RangeObserver(qOut=q_out, navdata=navdata, testMode=False)

    mpu.rangePub.addSubscriber(o.update)

    timeout = 30.
    t1 = time.time()

    while True:
        reading = mpu.read()
        if not q_out.empty():
            m = q_out.get()
            print(str(m))
            break
        if time.time()-t1 > timeout:
            print("timed out")
            break
        time.sleep(0.1)

    print('Elapsed time:',time.time()-t1)

