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

import sqlite3
from collections import namedtuple

from lbrsys.settings import dbfile, robot_name

# Named tuple definitions are used across lbrsys to build objects for
# communicating commands, state and feedback or telemetry between modules
# and processes
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
calibrateMagnetometer = namedtuple('calibrateMagnetometer', 'samples source')

distance    = namedtuple('distance', 'n s e w t')

motorCommandResult = namedtuple('motorCommandResult',
                                'status command reply time')

dance       = namedtuple('dance', 'song')
speech      = namedtuple('speech','msg save', defaults=(False,))
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

# command_map generalizes and streamlines console command processing
#   in the prepare function.  Schema is as follows:
#       {command_label: {num_fields_present: {command: [param_type,]}},}
#
#   prepare handles nav as a special case currently since it is the only nested command
#
command_map = {
    'r': {3: {power: [float, float]}, 6: {nav: [power, float, str, float]}},
    'a': {2: {observeTurn: [float]}},
    't': {2: {executeTurn: [float]}},
    'h': {2: {executeHeading: [float]}},
    's': {2: {speech: [str]}, 3:{speech: [str, bool]}},
    'd': {2: {dance: [str]}},
    'm': {3: {calibrateMagnetometer: [int, str]}},
}


def get_robot_id(name):
    r_id = None
    try:
        with sqlite3.connect(dbfile) as con:
            con.row_factory = sqlite3.Row
            cursor = con.cursor()
            robot_record = cursor.execute(
                "SELECT robot_id FROM robot \
                WHERE robot.name=?", (name,))
            r_id = robot_record.fetchone()['robot_id']

    except Exception as e:
        print(f"Error getting robot id: {e}")

    return r_id


robot_id = get_robot_id(robot_name)