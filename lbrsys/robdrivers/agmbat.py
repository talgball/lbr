"""
agmbat.py - info / 'driver' for 35AH AGM battery.
    maps a voltage reading to the state of charge and returns a batlevel
    object
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


from lbrsys import batlevel


class Agmbat:
    def __init__(self):
        self.stateOfCharge = [(10.5, 0.), (11.3, 0.1), (11.5, 0.2), (11.7, 0.3),
                              (11.9, 0.4), (12.0, 0.5), (12.2, 0.6), (12.4, 0.7),
                              (12.5, 0.8), (12.6, 0.9), (12.7, 1.0)]

    def getLevel(self,v):
        level = 0.

        source = self.getSource(v)
        if source == 'AC':
            level = 1.0
        else:
            level = self.stateOfCharge[0][1]
            for vh in self.stateOfCharge:
                if vh[0] <= v:
                    level = vh[1]
                else:
                    break

        return batlevel(v, level, source)


    # kludge to determine power source for now
    def getSource(self, v):
        if v > 12.7:
            source = 'AC'
        else:
            source = "BAT"
        return source

if __name__ == '__main__':
    b = Agmbat()

    for v in range(104, 135, 5):
        volt = v/10.
        print("Level for %.2f: %.2f" % (volt,b.getLevel(volt).level))

