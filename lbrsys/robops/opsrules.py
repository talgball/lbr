"""
opsrules checks for constraints or rules against the operating environment
    and returns adjusted power levels.  For example, if we're going too
    fast near a wall, slow down.  Stop before hitting something.
    (Currently only checking against forward range.)
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


from lbrsys import power

class RangeRules:

    # put code here or nearby to read the rules from a data source
    # hard coded for now
    minForwardRange     = 25.0
    freeForwardRange    = 100.0
    minPowerLevel       = 0.15

    
    def __init__(self):
        lastForwardRange    = -1.0


    def adjustPower(self,reqPower,powerIn,fRange):
        powerOutLevel = 0.0
        
        if powerIn.level > 0:
            a = powerIn.angle
            if (a >= 0 and a <= 45) or (a >= 315 and a <= 360):
                if fRange <= self.minForwardRange:
                    powerOutLevel = 0.0
                else:
                    if  fRange >= self.freeForwardRange :
                        powerOutLevel = reqPower.level
                    else:
                        maxLevel = (1.0 - self.minForwardRange/fRange)
                        if powerIn.level <= maxLevel:
                            powerOutLevel = powerIn.level
                        else:
                            powerOutLevel = maxLevel

                        if powerOutLevel < self.minPowerLevel:
                            powerOutLevel = self.minPowerLevel
            else:
                powerOutLevel = powerIn.level

        self.lastForwardRange = fRange
        
        return power(powerOutLevel,powerIn.angle)
        
        
if __name__ == '__main__':
    rule = RangeRules()
    r = 50.0
        
    print("for Power .75, ranges and adjusted power:")
    p = power(0.75,0)
    for r in range(150, 1, -2):
        newPower = rule.adjustPower(p,r)
        print(r, newPower.level)

    
