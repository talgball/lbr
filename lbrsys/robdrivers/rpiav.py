
"""
 rpiav.py - handle audio visual services for raspberry pi
   updated to add functions on 2018-11-24
   (module not currently fully integrated with lbrsys)
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
sys.path.append('..')
import os
import subprocess
import time
import logging

from robcom import publisher
from lbrsys.settings import jitsiURL


class VC:
    """Raspberry Pi Video Core Interface"""
    def __init__(self):
        un = os.uname()
        if un[0] != 'Linux': # assume RPi
            logging.debug("No Video Core Interface / Non - Raspberry Pi")

    def screenPowerStatus(self):
        screenProc = subprocess.check_output(["vcgencmd", "display_power"])
        status = int(screenProc.rsplit('=')[1].strip())
        return status

    def screenOff(self):
        logging.debug("Turning Display Power Off")
        screenProc = subprocess.check_output(["vcgencmd", "display_power", "0"])
        return screenProc

    def screenOn(self):
        logging.debug("Turning Display Power On")
        screenProc = subprocess.check_output(["vcgencmd", "display_power", "1"])
        return screenProc

    def coreTemp(self):
        coreTempProc = str(subprocess.check_output(["vcgencmd", "measure_temp"]))
        coreTemp = coreTempProc.rsplit('=')[1].strip()
        return coreTemp


class Jitsi:
    """jitsi video conference interface"""
    def __init__(self,url=jitsiURL):
        self.room = url


if __name__ == "__main__":
    v = VC()
    print(("Processor Core Temp = %s" % v.coreTemp()))
    while True:
        print("Toggle Screen. Press 'x' to exit.")
        r = input("Screen> ")
        if r == "0":
            sp = v.screenOff()
            print(sp)
        elif r == "1":
            sp = v.screenOn()
            print(sp)
        elif r == "?":
            sp = v.screenPowerStatus()
            if sp == 1:
                print("Display is on\n")
            elif sp == 0:
                print("Display is off\n")
            else:
                print("Display power status unknown\n")
        elif r == "x":
            break
