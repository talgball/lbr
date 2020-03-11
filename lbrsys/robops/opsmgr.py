"""
opsmgr.py - operations manager - handle intractions between the robot
    and physical devices including sensors and motors.  Manage the
    main operations loop for the system
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
import multiprocessing
import threading

from lbrsys.settings import opsLogFile
from lbrsys import power, nav, voltages, amperages
from lbrsys import gyro, accel, mag, mpuData
from lbrsys import observeTurn, executeTurn, observeHeading, executeHeading
from lbrsys import observeRange, feedback

import robdrivers
import robdrivers.sdc2130
import robdrivers.agmbat
from robops import movepa
from robops import opsrules

printTests = False

if multiprocessing.current_process().name == "Robot Operations":
    # temporary debug hack for linux:
    # sys.stdout = open(opsLogFile,"a")
    logging.basicConfig(
        level=logging.INFO,
        # level=logging.DEBUG,
        filename=opsLogFile,
        format='[%(levelname)s] (%(processName)-10s) %(message)s'
    )


class Opsmgr(object):
    def __init__(self,
                 commandQ=None, broadcastQ=None,  # todo avoid calling with positional args
                 rangecq=None, rangebq=None,
                 mpucq=None, mpubq=None):
        self.commandQ   = commandQ
        self.broadcastQ = broadcastQ
        self.mpucq     = mpucq
        self.mpubq     = mpubq
        #self.mpucq     = None
        #self.mpubq     = None

        self.rangecq    = rangecq
        self.rangebq    = rangebq
        
        self.initializeDevices()

        self.bat                = robdrivers.agmbat.Agmbat()
        self.mover              = movepa.Movepa(self.devices['motorController'])
        self.startTime          = robtimer()
        self.lastLogTime        = 0
        self.lastForwardRange   = -1
        self.forwardRange       = -1
        self.voltageMonitorThreshold = 10.6
        self.alarmInterval      = 60
        self.rangeInterval      = 0.5
        self.lastRangeTime      = 0
        self.lastPowerTime      = 0.
        self.stopPower          = power(0,0)
        self.lastPower          = self.stopPower
        self.rangeNoise         = 1
        self.lastVoltageAlarm   = robtimer() - self.alarmInterval
        self.lastVoltage        = voltages(0.,0.,0.,0.)
        #self.voltageInterval    = 180
        self.voltageInterval    = 15
        #self.voltageInterval     = 2
        self.voltageNoise       = 0.1
        #self.voltageNoise       = 0
        self.lastVoltageTime    = robtimer() - self.voltageInterval
        self.lastAmpsTime       = 0
        self.ampsInterval       = 1
        self.lastAmps           = amperages(0, 0, "")
        self.rangeRules         = opsrules.RangeRules()
        self.adjustedTask       = power(0.,0.)
        self.lastPower          = power(0.,0.)
        self.autoAdjust         = True # False means don't adjust for range

        self.lastRanges         = {'Ranges':{'Forward':0,'Left':0,'Right':0,
                                             'Bottom':0,'Back':0,'Deltat':0},
                                   'Timestamp':0.0}

        self.lastMpu            = mpuData(gyro(0,0,0,0), accel(0,0,0), mag(0,0,0),
                                          0, 0, 0) # todo convert to json
        self.curHeading         = 0

        self.lastMpuTime        = 0
        self.mpuInterval        = 2


        logging.info("Instantiated Robot Operations")
        if self.commandQ:
            self.start()


    def initializeDevices(self):
        self.motorController = robdrivers.sdc2130.SDC2130()
        self.devices = {'motorController' : self.motorController}
        self.motorController.messagePub.addSubscriber(self.genericSubscriber)
        self.motorController.voltagePub.addSubscriber(self.genericSubscriber)
        self.motorController.voltagePub.addSubscriber(self.voltageMonitor)
        self.motorController.voltagePub.addSubscriber(self.reportBat)
        self.motorController.ampsPub.addSubscriber(self.genericSubscriber)
        self.motorController.ampsPub.addSubscriber(self.reportAmps)
        self.motorController.motorControlPub.addSubscriber(self.genericSubscriber)

        
    def checkController(self):
        v,a = self.motorController.checkController()
        # v,a = self.motorController.cFront.checkController()
        #results published by the controller. return values mainly for unit testing

    def execTask(self,task):
        logging.debug("executing ops task: " + str(task))
        if printTests:
            print("executing task: " + str(task))

        if type(task) is power:
            self.lastPower = task
            self.requestedPower = task
            result = "no move result"
            if self.autoAdjust:
                self.adjustedTask = self.rangeRules.adjustPower(
                    self.requestedPower,self.lastPower,self.forwardRange)
                if printTests:
                    print(("adjusted task: %s" % str(self.adjustedTask)))
                result = self.mover.movepa(self.adjustedTask)
            else:
                result = self.mover.movepa(task)
            logging.debug(str(result))
            #print str(result)

        if type(task) is nav:
            # nav: power, range, interval
            # navexample = nav(power(0.2,0), 10, 'Forward', 20)
            self.commandQ.put(task.power)
            self.rangecq.put(observeRange(task))

        if type(task) is mpuData:
            self.mpuData = task
            self.curHeading = task.heading
            self.reportMpu(task)

        if type(task) is observeTurn:
            self.mpucq.put(task)

        if type(task) is executeTurn:
            mpuTask = observeTurn(task.angle)
            self.mpucq.put(mpuTask)
            if task.angle >= 0:
                # result = self.mover.movepa(power(0.25,90.0))
                self.commandQ.put(power(0.20, 90.0))
            else:
                # result = self.mover.movepa(power(0.25,270.0))
                self.commandQ.put(power(0.20, 270.0))

        if type(task) is executeHeading:
            if task.heading >= 0. and task.heading <= 360.:
                mpuTask = observeHeading(task.heading)
                self.mpucq.put(mpuTask)
                pa = calcDirection(self.curHeading, task.heading)[0]
                self.commandQ.put(power(0.20, pa))
                logging.debug("Heading Exectuion Ordered: %s, Power Angle %d" %\
                              (str(task), pa))
            else:
                logging.debug('Invalid heading: ' + str(task))

        # dancing not supported in this version
        # for the moment, make dancing an operation.  It should be an application.
        # if type(task) is dance:
        #     logging.debug("calling dance")
        #     result = robapps.danceapp.DanceApp(dance, self.mover)
        #     logging.debug(str(result))

        if type(task) is tuple and len(task) == 3:  # todo need to make an observation type
            if task[0] == 'Observed':
                self.commandQ.put(power(0, 0))
                logging.debug("Stopped motors on completed observation")

            if task[0] == 'Missed':
                self.commandQ.put(power(0, 0))
                logging.debug("Stopped motors on missed observation")


    def adjustTask(self):
        result = "no move result"
        if self.lastPower.level > 0:
            
            self.adjustedTask = self.rangeRules.adjustPower(
                self.requestedPower,self.lastPower,self.forwardRange)
            self.lastPower = self.adjustedTask
            self.lastForwardRange = self.forwardRange

            result = self.mover.movepa(self.adjustedTask)
            logging.debug("adjusted, result: %s" % (str(result),))

            if printTests:
                print("adjust - level: %.2f, range: %d" % \
                (self.adjustedTask.level,self.forwardRange))

        
    def processStats(self,opsStats):
        opsStats['AverageLoopTime'] = opsStats['totalLoopTime']/opsStats['numLoops']
        if opsStats['numWaits'] > 0:
            opsStats['AverageWaitTime:'] = opsStats['totalWaitTime']/opsStats['numWaits']
        else:
            opsStats['AverageWaitTime:'] = 0.
        #self.broadcastQ.put(opsStats)
        logging.info("Operations Stats\n%s\n" % (pprint.pformat(opsStats)))
        #pprint.pformat(opsStats)

    def genericSubscriber(self, msg):
        if self.lastLogTime == 0:
            logging.info('\n\nInitiating controller logging.')
            self.lastLogTime = robtimer()
            self.logsAllowed = 0
        if robtimer() - self.lastLogTime >= 10:
            logging.debug(str(msg))
            self.logsAllowed += 1
        if self.logsAllowed > 4: # yep, hard coded kludge for the moment. need non-generic subscribers.
            self.lastLogTime = robtimer()
            self.logsAllowed = 0            

    def voltageMonitor(self, v):  #todo - refactor / create monitors..
        if v.mainBattery < self.voltageMonitorThreshold:
            if robtimer() - self.lastVoltageAlarm >= self.alarmInterval:
                vdictj = {'voltages': v._asdict()}
                self.broadcastQ.put(vdictj)
                self.lastVoltageAlarm = robtimer()

    def reportBat(self, v):
        if robtimer() - self.lastVoltageTime >= self.voltageInterval:
            if abs(v.mainBattery-self.lastVoltage.mainBattery) > self.voltageNoise:
                bl = self.bat.getLevel(v.mainBattery)
                blD = {'Bat': {'voltage':bl.voltage,
                                'level':bl.level,
                                'source':bl.source}}
                self.broadcastQ.put(blD)
                self.lastVoltageTime = robtimer()
                self.lastVoltage = v
                logging.debug("Reported Battery Level: %s" % \
                              (str(self.bat.getLevel(v.mainBattery)),))
                logging.debug("v: %s\n" % (str(v),))

    def reportAmps(self, a):
        if robtimer() - self.lastAmpsTime >= self.ampsInterval:
            ampsD = {'amperages':   {'leftMotor':  a.channel1,
                                     'rightMotor': a.channel2,
                                     'time':       a.time}}
            self.broadcastQ.put(ampsD)
            self.lastAmpsTime = robtimer()
            self.lastAmps = a
            logging.debug('Amperages: %s\n' % (str(a)))


    def reportRange(self,info):
        '''
        example
        {u'Ranges': {u'Right': 55, u'Deltat': 12313264, u'Bottom': -1, u'Back': 18, u'Forward': 67, u'Left': 18},
         u'Timestamp': 0.07504105567932129}
        '''
        if robtimer() - self.lastRangeTime >= self.rangeInterval:
            #type checking is redundant here, info is known to be Range
            if type(info) == dict:
                if 'Ranges' in info:
                    '''
                    For now, let's always report 
                    f = info['Ranges']['Forward']
                    l = info['Ranges']['Left']
                    r = info['Ranges']['Right']
                    b = info['Ranges']['Back']
                    btm = info['Ranges']['Bottom']
                    lastf = self.lastRanges['Ranges']['Forward']
                    lastl = self.lastRanges['Ranges']['Left']
                    lastr = self.lastRanges['Ranges']['Right']
                    lastb = self.lastRanges['Ranges']['Back']
                    lastbtm = self.lastRanges['Ranges']['Bottom']
                    if abs(f-lastf) > self.rangeNoise or \
                       abs(l-lastl) > self.rangeNoise or \
                       abs(r-lastr) > self.rangeNoise or \
                       abs(b-lastb) > self.rangeNoise or \
                       abs(btm-lastbtm) > self.rangeNoise:
                    '''
                    self.broadcastQ.put(info)
                    self.lastRangeTime = robtimer()
                    self.lastRanges = info
        
    def reportMpu(self, m):
        '''
        example
        {u'temp': 28.4, u'gyro': [0.0, 0.106, 0.0, 1549408911.4707],
        u'accel': [-0.0046, -0.0247, 1.106], u'mag': [-10.7895, -10.6512, -31.6055],
        u'time': 1549408911.4707, u'heading': 315.0}
        '''
        if robtimer() - self.lastMpuTime >= self.mpuInterval:
            try:
                mpuDict = {'MPU':m._asdict()}
                self.broadcastQ.put(mpuDict)
                self.lastMpuTime = robtimer()
                self.lastMpu = m
            except KeyError as e:
                logging.debug("Error reporting mpu data: %s" % (str(e)))


    def start(self):
        printRange = True
        # minLoopTime = 0.050 # todo look at variablizing minLoopTime to be able to speed up or slow down as needed
        minLoopTime = 0.010
        opsStats = {'totalLoopTime':0, 'numLoops':0,
                    'totalWaitTime':0, 'numWaits':0,
                    'excessiveTimes':0}
        while True:
            loopStartTime = robtimer()
            if not self.commandQ.empty():
                task = self.commandQ.get_nowait()
                #print "task is:",task
                self.commandQ.task_done() # ensures queue doesn't hang

                if task == 'Shutdown':
                    self.mover.movepa(power(0.,0))
                    print("Executing Shutdown..")
                    self.processStats(opsStats)
                    break

                # since Ranges come in json dictionaries instead of named tuples,
                #   handle separately for now.
                if isinstance(task, dict):
                    if 'Ranges' in task:
                        self.forwardRange = task['Ranges']['Forward']
                        self.reportRange(task)
                        #logging.debug("range = %d" % (self.forwardRange,))
                        if printRange:
                            print(("Initial Forward Range = %dcm" % (self.forwardRange,)))
                            printRange = False

                self.execTask(task)

            self.checkController()
            dt = robtimer() - loopStartTime
            if dt > 1.0:
                print("it's taken %f after checking controller" % (dt,))

            if self.autoAdjust:
                self.adjustTask()

            elapsedTime = robtimer() - loopStartTime
            waitTime = minLoopTime - elapsedTime

            opsStats['totalLoopTime'] += elapsedTime
            opsStats['numLoops'] += 1
            if waitTime > 0:
                opsStats['totalWaitTime'] += waitTime
                opsStats['numWaits'] += 1
            
            if elapsedTime < minLoopTime and self.commandQ.empty():
                time.sleep(waitTime)

            if elapsedTime > 1.0:
                logging.debug("Excessive operations loop time: %f" % (elapsedTime))
                opsStats['excessiveTimes'] += 1

        self.end()


    def end(self):
        self.devices['motorController'].closeController()
        self.devices['motorController'].closeController()

        # self.devices['motorController'].cFront.closeController()
        # self.devices['motorController'].cRear.closeController()
        logging.debug("%s: motor controllers shutdown"\
                      % (time.asctime(),))


def calcDirection(heading, target):
    """
    Which way around the circle is closer
        90 is clockwise
        270 is counterclockwise
        0 is don't know - something went wrong
    """
    direction = 0
    if heading <= target:
        dcw = target - heading
        dccw = heading + 360 - target
        if dcw <= dccw:
            direction = 90
        else:
            direction = 270
    else:
        dcw = 360 - heading + target
        dccw = heading - target
        if dcw <= dccw:
            direction = 90
        else:
            direction = 270
    return direction, dcw, dccw



if __name__ == '__main__':
    import rangeops
    import mpops
    #printTests = True
    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()
    mpucq = multiprocessing.JoinableQueue()
    mpubq = multiprocessing.JoinableQueue()
    rangecq = multiprocessing.JoinableQueue()
    rangebq = multiprocessing.JoinableQueue()

    rangeP = multiprocessing.Process(
        target=rangeops.Rangeservice,
        name='Range Services',
        args=(rangecq,cq)
    )

    mpuP = multiprocessing.Process(
        target=mpops.MPservice,name='MPU',
        args=(mpucq,cq)
    )

    mgrThread = threading.Thread(
        target=Opsmgr,name='Manager',
        args=(cq, bq,
              #mpucq,cq,
              # rangecq,cq)
        )
    )

    mgrThread.start()
    time.sleep(0.5)
    rangeP.start()
    time.sleep(0.5)
    mpuP.start()
    time.sleep(1)

    p = power(.25,90)
    cq.put(p)
    # cq.put(executeTurn(90))

    time.sleep(5)
    cq.put('Shutdown')
    

    #p = power(.50,0)
    #cq.put(p)
    #time.sleep(8) # time to run unless range-oriented stop
    #cq.put(power(0,0))

    #time.sleep(3)
    
    #rangecq.put("Shutdown")
    #mpucq.put("Shutdown")
    #time.sleep(0.250)
    #cq.put("Shutdown")

    stop = power(0., 0)
    std = power(0.3, 0)
    def go(p=std):
        cq.put(p)
