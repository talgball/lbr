
"""
driver module for Roboteq sdc2130 high performance motor controller
    https://www.roboteq.com/index.php/docman/motor-controllers-documents-and-files/documentation/datasheets/sdc21xx-datasheet/63-sdc21xx-datasheet/file

    The motor controller is connected via USB. Communication
    is via its proprietary protocol, as implemented in
    this driver.

    Note that mix motor control Mode 1 is assumed.
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


import sys
import io
import time

from serial import Serial, SerialException
from serial import EIGHTBITS, PARITY_NONE, STOPBITS_ONE

sys.path.insert(0, '..')

from lbrsys.settings import SDC2130_Port
from lbrsys import voltages, amperages, motorCommandResult
from robcom import publisher


# Master Control - False prevents motor activation (for testing)
executionEnabled = True

class SDC2130:
    baudrate = 115200
    bytesize = EIGHTBITS
    parity = PARITY_NONE
    stopbits = STOPBITS_ONE
    timeout = 0.250
    #timeout = 1 #second
    #timeout = 0 #non-blocking mode
    STOP_MOTOR_COMMAND = '!M 0 0\r'
    

    def __init__(self, port=SDC2130_Port):
        self.port = port
        try:
            self.rawController = Serial(self.port, self.baudrate, self.bytesize,
                                     self.parity, self.stopbits, self.timeout)

            self.controller = io.TextIOWrapper(io.BufferedRWPair(
                    self.rawController, self.rawController, 1),
                    newline='\r', line_buffering = True)
            # re-examine this access approach and see the comments re not passing same obj as reader / writer
            # for BufferedRWPair
            # https://docs.python.org/3/library/io.html#io.BufferedRandom
            #   but BufferedRandom is not seekable, so the following fails
            # self.controller = io.TextIOWrapper(io.BufferedRandom(self.rawController, buffer_size=1),
            #                                    newline='\r', line_buffering=True)
        except:
            print("Unexpected error:", sys.exc_info()[0])
            raise
        
        self.motorCommand = self.STOP_MOTOR_COMMAND
        self.messagePub = publisher.Publisher("SDC2130 Message Publisher")
        self.voltagePub = publisher.Publisher("SDC2130 Voltage Publisher")
        self.ampsPub    = publisher.Publisher("SDC2130 Amperage Publisher")
        self.motorControlPub = publisher.Publisher("SDC2130 Motor Control Publisher")

        self.lastVoltages = voltages(12.0,12.0,5.11,time.asctime())
        # self.lastVoltages = voltages(0.,0.,0.,time.asctime())

    
    def closeController(self):
        try:
            self.rawController.close()
            self.messagePub.publish(time.asctime() + " Controller Closed")
        except:
            msg = time.asctime() + " Error Closing Controller"
            self.messagePub.publish(msg)
            print(msg)

    def parseQueryResults(self,buffer,commandChar):
        values = []
        try:
            #print "in parse with: %s" % (buffer,)
            results = buffer[2:].split(':')
            #print results

            if results:    
                for r in results:
                    values.append(float(r))
            else:
                values.append(0.0)
        except:
            msg = time.asctime() + ": Error parsing query results: '%s'  Expected type %s\n" % (buffer, commandChar)
            self.messagePub.publish(msg)
            print(msg)
            values = [-999.,-999.]
            
        return tuple(values)
                

    def getVoltages(self):
        #
        # sdc2130 reports main bat voltage, internal voltage at driver stage,
        #   5V output voltage
        #   first 2 are 10x, third one is in millivolts

        try:
            # self.controller.flush()
            self.controller.write('?V\r')   # query for the voltages'
            self.controller.flush()

            # read the good echo, then the result
            readBuffer = self.controller.readline()
            if readBuffer == '?V\r':
                readBuffer = self.controller.readline()
            else:
                readBuffer = ""

        except:
            msg = time.asctime() + ' Error getting voltages'
            self.messagePub.publish(msg)
            print(msg)

        #logging.debug("getVoltages parsing buffer: "+readBuffer)
        #July, 2015 - unable to determine why having two ports open causes
        #   read errors
        readings = ()
        if len(readBuffer) > 3:
            readings = self.parseQueryResults(readBuffer,'V')
        else:
            #print "Skipped bad readBuffer in getVoltages"
            pass
        
        if len(readings) == 3:
            mainBatVolts = readings[1] / 10.0
            internalVolts = readings[0] / 10.0 #order different for sdc2130
            outputVolts = readings[2] / 1000.0
            v = voltages(mainBatVolts, internalVolts,outputVolts,
                         time.asctime())
            self.lastVoltages = v
        else:
            # v = voltages(0.,0.,0.,time.asctime())
            v = self.lastVoltages

        self.voltagePub.publish(v)
        
        return v


    def getAmps(self):
        # docs indicate that return value must be divided by 10
        # in amps to get the actual value
        try:
            # self.controller.flush()
            self.controller.write('?A\r')   # query for the amp readings
            self.controller.flush()

            # read the good echo, then read the result
            readBuffer = self.controller.readline()
            if readBuffer == '?A\r':
                readBuffer = self.controller.readline()
            else:
                readBuffer = ""

        except:
            msg = time.asctime() + ' Error getting amperages'
            self.messagePub.publish(msg)
            print(msg)

        #logging.debug("getAmps parsing buffer: "+readBuffer)
        #print "getAmps parsing buffer: %s" % (readBuffer,)
        #see comment in getVoltages re serial issue
        readings = ()
        if len(readBuffer) > 3:
            readings = self.parseQueryResults(readBuffer,'A')
        if len(readings) == 2:
            ampsChannel1 = readings[0] / 10.0
            ampsChannel2 = readings[1] / 10.0
        else:
            ampsChannel1 = 0.
            ampsChannel2 = 0.

        amps = amperages(ampsChannel1, ampsChannel2, time.asctime())
        self.ampsPub.publish(amps)

        return amps


    # resetController - similar to power off and power on
    # warning - also resets the serial connection
    def resetController(self):

        try:
            self.stopMotors()
            self.controller.write('%RESET 321654987\r')
            self.controller.flush()
            resetResult = self.controller.readline()
        except:
            print('error reseting controller')
            resetResult = "Error"

        self.messagePub.publish(time.asctime() + " " + resetResult)

        return resetResult

    
    # mixMotorCommand
    #   set the speed and direction of the motors
    #   As of July, 2017 independent motor operation is assumed
    #   speed sets the speed of both motors
    #   direction adds steering in a tank like manner
    #   range is -1000 to +1000 for each motor called in decimal
    #   if motorCommand is passed to the function, it is sent without modification
    #       ..or verification todo: security
    #
    def mixMotorCommand(self, speed=0, direction=0, motorCommand=None):
        m1 = speed + direction
        if m1 > 1000:
            m1 = 1000
        elif m1 < -1000:
            m1 = -1000

        m2 = speed - direction
        if m2 > 1000:
            m2 = 1000
        elif m2 < -1000:
            m2 = -1000

        return self.generalMotorCommand(m1, m2, motorCommand)

    # generalMotorCommand
    #   Used to send commands to each motor using channel 1 and channel 2.
    #   Controller interprets command based on mode. 
    #   Range is -1000 to +1000
    #
    def generalMotorCommand(self,chan1=0,chan2=0,motorCommand=None):
        
        if not motorCommand:

            if chan1 < -1000 or chan1 > 1000:
                chan1 = 0

            if chan2 < -1000 or chan2 > 1000:
                chan2 = 0

            self.motorCommand = '!M %d %d\r' % (chan1,chan2)
        else:
            self.motorCommand = motorCommand
        
        t = time.asctime()
        if executionEnabled:
            try:
                self.controller.write(self.motorCommand)
                reply = self.controller.readline() # first get echo
                #print reply 
                reply = self.controller.readline()
                #logging.debug("motor reply:"+reply)
                if reply == '':
                    commandReply = ''
                else:
                    commandReply = reply[0]
            except SerialException as e:
                print('\t***error writing motor command: %s to %s' % (motorCommand,self.port))
                print('\tSerial Exception: {0}: {1}'.format(e.errno, e.strerror))
                commandReply = ''

            if commandReply == '+':
                result = motorCommandResult('Success',
                                            motorCommand, commandReply, t)
            elif commandReply == '-':
                result = motorCommandResult('Failure',
                          motorCommand, commandReply, t)
            else:
                result = motorCommandResult('Unacknowledged',
                          motorCommand, commandReply, t)
        else:
            result = motorCommandResult('Disabled',
                                        motorCommand, '', t)

        self.motorControlPub.publish(result)   
        return result 
                
    #
    # stopMotors
    #
    #  toDo: implement a Stop Publisher and Subscribe to it
    #
    def stopMotors(self):
        result = self.mixMotorCommand(0,0)
        return(result)            

    #
    # gathers the readings (todo: figure out publishing)
    #    also keep watchdog alive (this gen requires a ! command for that)
    #
    def checkController(self):
        v = self.getVoltages()
        a = self.getAmps()

        # for now, just re-issue the current motor command
        # could flash an led or take any other runtime action
        # to keep watchdog alive
        if self.motorCommand != self.STOP_MOTOR_COMMAND:
            self.mixMotorCommand(0,0,motorCommand=self.motorCommand)

        return v,a
        # todo - add power, etc.


if __name__ == "__main__":
    c = SDC2130()

    speed = 0
    steering = 300
    cmd = c.mixMotorCommand(speed, steering)
    for r in range(3):
        time.sleep(.9)
        v,a = c.checkController()
        # if a.channel1 == 0:
        #     print "Channel 1 motor stopped"
        print(v,a)
    c.stopMotors()


    
     
