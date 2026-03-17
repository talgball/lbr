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
from lbrsys import observeRange, cancelRange, observeResult, set_process_title

import robdrivers.p8x32lbr

proc = multiprocessing.current_process()

if proc.name  == 'Range Services': # or proc.name == 'MainProcess':
    logging.basicConfig(
        level=logging.DEBUG,
        filename=rangeLogFile,
        format='[%(levelname)s] (%(processName)-10s) %(message)s')
    set_process_title()


class RangeCondition:
    """Lightweight condition representing a range target to watch for.
    Replaces the heavier RangeObserver class for inline checking."""

    MAX_RANGE = 768
    MIN_RANGE = 17
    TOLERANCE = 1.0  # centimeters

    BASELINE_SAMPLES = 3     # readings to establish initial range
    CONFIRM_READINGS = 2     # consecutive readings required to confirm target reached

    def __init__(self, nav_data, nav_id):
        self.distance = nav_data.range    # distance to travel in cm
        self.sensor = nav_data.sensor
        self.nav_id = nav_id
        self.start_time = robtimer()
        self.initial_range = None         # median of first N readings
        self.baseline_buf = []            # buffer for establishing baseline
        self.last_range = None
        self.confirm_count = 0            # consecutive readings meeting target
        self.total_updates = 0

        if self.distance <= 0:
            msg = "Range condition: invalid distance %s" % self.distance
            print(msg)
            logging.warning(msg)

        logging.debug("Range condition: distance=%s, sensor=%s, nav_id=%s" %
                      (self.distance, self.sensor, self.nav_id))
        print("Range condition: distance=%scm, sensor=%s at %s" %
              (self.distance, self.sensor, time.asctime()))

    def check(self, reading):
        """Check a range reading against this condition.
        The range parameter means distance to travel, measured as the change
        in the specified sensor's reading from the initial value.
        Returns ('observed', value, elapsed) or ('missed', value, elapsed) or None."""
        current = reading['Ranges'][self.sensor]
        self.total_updates += 1
        elapsed = robtimer() - self.start_time

        # establish baseline from median of first N readings
        if self.initial_range is None:
            self.baseline_buf.append(current)
            if len(self.baseline_buf) < self.BASELINE_SAMPLES:
                return None
            self.baseline_buf.sort()
            self.initial_range = self.baseline_buf[len(self.baseline_buf) // 2]
            self.last_range = self.initial_range
            msg = "Range baseline established: %.1f (samples: %s)" % (
                self.initial_range, self.baseline_buf)
            logging.debug(msg)
            print(msg)
            return None

        distance_traveled = abs(current - self.initial_range)

        # require consecutive confirming readings to filter noise spikes
        if distance_traveled >= self.distance - self.TOLERANCE:
            self.confirm_count += 1
            if self.confirm_count >= self.CONFIRM_READINGS:
                return 'observed', current, elapsed
        else:
            self.confirm_count = 0

        self.last_range = current
        return None


class Rangeservice(object):
    def __init__(self, commandQ=None, broadcastQ=None):
        self.commandQ   = commandQ
        self.broadcastQ = broadcastQ
        self.rangemcu   = robdrivers.p8x32lbr.P8X32()
        self.lastLogTime= 0
        self.logInterval= 2.0
        self.lastExtSend= 0
        self.rangeReportInterval = 0.5
        self.lastRangeReportTime = 0.
        self.extInterval= 1
        # No sleep between reads — readline() blocks until data arrives,
        # naturally pacing at the Arduino's send rate.  An additional sleep
        # causes the serial buffer to fill, triggering USB CDC/ACM flow
        # control which blocks Arduino Serial.print() and disrupts sensor
        # timing, leading to pulseIn() timeouts and spurious zero readings.
        self.conditions = []
        self.rangemcu.rangePub.addSubscriber(self.genericSubscriber)
        self.rangemcu.rangePub.addSubscriber(self.checkConditions)
        self.curtime = robtimer()
        ta = time.asctime()
        startmsg = "\n\n%s: Starting Range Operations" % (ta,)
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
                            # msg['Ranges']['Deltat']  / 80000000.0 * 1000.0,
                            msg['Ranges']['Deltat'],  # already milliseconds for lbr6
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
            cond = RangeCondition(task.nav, task.nav_id)
            self.conditions.append(cond)

        if type(task) is cancelRange:
            self.conditions = [c for c in self.conditions
                               if c.nav_id != task.nav_id]
            logging.debug("Canceled range condition nav_id=%s" % task.nav_id)

    def checkConditions(self, reading):
        """Check all active range conditions against the latest reading.
        Replaces the old observer/subscriber pattern with a simple inline check."""
        remaining = []
        for cond in self.conditions:
            result = cond.check(reading)
            if result is None:
                remaining.append(cond)
            else:
                status, value, elapsed = result
                self.broadcastQ.put(
                    observeResult(status, cond.sensor, value, elapsed, cond.nav_id)
                )
                traveled = abs(value - cond.initial_range) if cond.initial_range else 0
                report = ("Range %s: sensor=%s, reading=%.1f, traveled=%.1f/%.1fcm, "
                          "elapsed=%.3fs, updates=%d, nav_id=%s")
                logging.debug(report % (status, cond.sensor, value, traveled,
                                        cond.distance, elapsed,
                                        cond.total_updates, cond.nav_id))
                print(report % (status, cond.sensor, value, traveled,
                                cond.distance, elapsed,
                                cond.total_updates, cond.nav_id))
        self.conditions = remaining


    def processStats(self,opsStats):
        opsStats['AverageLoopTime'] = opsStats['totalLoopTime']/opsStats['numLoops']
        logging.debug("Ranger Service Operational Stats\n%s\n" % (pprint.pformat(opsStats)))


    def end(self):
        self.rangemcu.close()

if __name__ == '__main__':
    from lbrsys import nav, power

    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()

    r = threading.Thread(target=Rangeservice, name="Range Services",
                         args=(cq, bq))
    r.start()

    time.sleep(3) # time to start ranging
    t0 = time.time()

    cq.put(observeRange(nav(power(0, 0), 20, 'Forward', 0), nav_id='test1'))
    while (time.time() - t0) < 15:
        if not bq.empty():
            m = bq.get()
            bq.task_done()
            if type(m) is observeResult:
                pprint.pprint("Bq: " + str(m))
                break
        time.sleep(0.1)

    cq.put('Shutdown')
    cq.join()
