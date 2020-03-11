"""
Driver for Prallax Propeller, P8X32A, as programmed as a range sensor
    for lbr1 project.
        https://www.parallax.com/sites/default/files/downloads/P8X32A-Propeller-Datasheet-v1.4.0_0.pdf

    The microcontroller is driving an array of Maxbotix MB1220
    ultrasonic range sensors.
        https://www.maxbotix.com/documents/XL-MaxSonar-EZ_Datasheet.pdf

    The microcontroller packages and sends time fused collections
    of range readings in centimeters via serial communications.
    For convenient processing, the readings are provided in json.
    The firmware for the microcontroller is included for reference
    in the parallax subdirectory.

    This driver bridges the microcontroller to any interested system over USB.
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
import time
import json
from collections import deque
import serial

from lbrsys.settings import P8X32_1_Port
from robcom import publisher

testMovement = False

class P8X32:
    port = P8X32_1_Port
    baudrate = 115200
    bytesize = serial.EIGHTBITS
    parity = serial.PARITY_NONE
    stopbits = serial.STOPBITS_ONE
    timeout = 1 #second
    #timeout = 0 #non-blocking mode

    buffer = '' #keeping a copy for various debug purposes
    defaultRangeLine = b'{"Ranges":{"Forward":-1,"Bottom":-1,"Left":-1,"Right":-1,"Back":-1,"Deltat":0}}'
    rangeInit = json.loads(defaultRangeLine.decode())

    def __init__(self):
        try:
            self.controller = serial.Serial(self.port, self.baudrate, self.bytesize,
                                            self.parity, self.stopbits, self.timeout)

        except:
            print("Unexpected error:", sys.exc_info()[0])
            raise
        
        self.messagePub = publisher.Publisher("P8X32 Message Publisher")
        self.rangePub   = publisher.Publisher("P8X32-MB1220 Range Publisher")
        self.ranges     = self.rangeInit
        self.qDepth     = 500  # number of range readings to keep
        self.rangeList  = deque(maxlen=self.qDepth)
        self.t0         = time.time()

    def flush(self):
        self.controller.flushInput()

    def read(self):
        rangeLine = self.defaultRangeLine
        self.ranges = self.rangeInit
        goodRead = False
        try:
            rangeLine = self.controller.readline()
            t = time.time()

            # in case we don't get a line or are in debug mode
            if not rangeLine:
                rangeLine = self.defaultRangeLine
                
            self.ranges = json.loads(rangeLine.decode())
            self.ranges["Timestamp"] = t

            goodRead = True
            self.rangePub.publish(self.ranges)
            self.rangeList.append(self.ranges)
        except:
            if not rangeLine:
                rangeLine = self.defaultRangeLine
            errorStr = "error reading ranges:\n\t" + str(rangeLine)
            # print(errorStr)
            # print(sys.exc_info()[:2])
            #self.messagePub.publish(errorStr)
            goodRead = False

        return goodRead, self.ranges

    def close(self):
        self.controller.close()
    

def genericSubscriber(msg):
    print((str(msg)))

def genericRangeSubscriber(ranges):
    #c = 2.54 # set to 1.0 to keep in cm instead of inches
    c = 1.0
    printRanges(ranges,c)

def printRanges(ranges,c=1.0):
    print(("F: %.2f, BTM: %.2f, L: %.2f, R: %.2f, B: %.2f, DT: %.2fms, T: %.2fms" % \
          (ranges['Ranges']['Forward'] / c,
           ranges['Ranges']['Bottom']  / c,
           ranges['Ranges']['Left']    / c,
           ranges['Ranges']['Right']   / c,
           ranges['Ranges']['Back']    / c,
           ranges['Ranges']['Deltat']  / 80000000.0 * 1000.0,
           ranges['Timestamp'] * 1000.0)))

#
# Unit testing
#
if __name__ == '__main__':
    rangeList = []
    mpu = P8X32()
    mpu.flush()
    good,ranges = mpu.read() # eliminate partial result
    
    mpu.messagePub.addSubscriber(genericSubscriber)
    mpu.rangePub.addSubscriber(genericRangeSubscriber)
    
    for r in range(3):
        good,ranges = mpu.read()
        if good:
            rangeList.append(ranges)
            print(ranges)

    mpu.close()


