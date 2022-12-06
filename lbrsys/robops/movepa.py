"""
movepa.py - Command movements based on power and an angle - open loop
    For a 2 motor robot design with tank like steering, this module
    translates a power level and a steering angle into values communicated
    to the motor controller for operating the motors.
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
from math import *

class Movepa:
    def __init__(self, controller):
        #assume the controller is good (for now)
        self.controller = controller
        # normally get maxPower from controller
        self.maxPower = 1000 # for sdc2130, channel values range from -1000 to +1000
        
    def movepa(self, curPower):
        p = curPower.level
        a = curPower.angle

        if a==0 and p==0 :
            # print(f"{curPower}")
            pass

        if p > 1.0:
            p = 1.0
            print("Power clammped at 100%:", curPower.level)

        scale = p * self.maxPower

        # standard angle = (90-robot angle) because
        # robot 0 is always facing forward where
        # standard 0 is always facing right
        throttle = int(sin((90-a)*pi/180.) * scale)
        steering = int(cos((90-a)*pi/180.) * scale)
        # print(f'power: {p}, angle: {a}, throttle: {throttle}, steering: {steering}')

        if self.controller:
            result = self.controller.mixMotorCommand(throttle, steering)
        else:
            result = (throttle, steering)

        return result


# module unit testing
if __name__ == '__main__':
    import time
    
    m = Movepa(None) # no real controller should be used for this test
    from collections import namedtuple
    power = namedtuple('power', 'level angle')
    #todo: centralize named tuple definitions
    '''
    for p in [power(1,0), power(.5,45), power(.5,90), power(.5,135),
              power(.5,180), power(.5,225), power(.5,270), power(.5,315),
              power(1,180), power(10,400)]:
        r = m.movepa(p)
        print p, r
    '''
    for level in range(0, 101, 10):
        for angle in range(0, 360, 30):
            r = m.movepa(power(level/100., angle))
            print(level, angle, r)

