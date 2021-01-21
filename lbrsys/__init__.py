"""
lbrsys - top level package initialization shared across the system
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

# Named tuple definitions are used across lbrsys to build objects for
# communicating commands, state and feedback or telemetry between modules
# and processes
from collections import namedtuple
power       = namedtuple('power',    'level angle')
nav         = namedtuple('nav', 'power range sensor interval')
voltages    = namedtuple('voltages', 'mainBattery internal vout time')
amperages   = namedtuple('amperages','channel1 channel2 time')
batlevel    = namedtuple('batlevel','voltage level source')
gyro        = namedtuple('gyro',     'x y z t')
accel       = namedtuple('accel',   'x y z')
mag         = namedtuple('mag',   'x y z')
mpuData     = namedtuple('mpuData', 'gyro accel mag heading temp time')

observeTurn = namedtuple('observeTurn', 'angle')
executeTurn = namedtuple('executeTurn', 'angle')
observeHeading = namedtuple('observeHeading', 'heading')
executeHeading = namedtuple('executeHeading', 'heading')
observeRange = namedtuple('observeRange', 'nav')
calibrateMagnetometer = namedtuple('calibrateMagnetometer', 'samples')

distance    = namedtuple('distance', 'n s e w t')

motorCommandResult = namedtuple('motorCommandResult',
                                'status command reply time')

dance       = namedtuple('dance', 'song')
speech      = namedtuple('speech','msg')
feedback    = namedtuple('feedback','info')
screen      = namedtuple('screen', 'power')
iot         = namedtuple('iot', 'msg')

# map between namedtuple (i.e. message types) and channel types
# This map is used in message routings
channelMap = {
    'Operations': {
        power, voltages, amperages, gyro,
        observeTurn, executeTurn,
        observeHeading, executeHeading,
        distance, nav, observeRange,
        motorCommandResult,
        calibrateMagnetometer,
    },
    'Speech': {speech},
    'Application': {feedback, dict},
    'Dance': {dance},
    'IoT': {iot},
}
