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

from pyquaternion import Quaternion

from lbrsys.settings import dbfile, robot_name
from lbrsys.robdrivers.calibration import Calibration, CalibrationSetting

# Named tuple definitions are used across lbrsys to build objects for
# communicating commands, state and feedback or telemetry between modules
# and processes
power       = namedtuple('power',    'level angle')
nav         = namedtuple('nav', 'power range sensor interval')
voltages    = namedtuple('voltages', 'mainBattery internal vout time')
amperages   = namedtuple('amperages','channel1 channel2 time')
batlevel    = namedtuple('batlevel','voltage level source')
count       = namedtuple('count', 'left right time', defaults=(0, 0, 0.))
gyro        = namedtuple('gyro',     'x y z t')
accel       = namedtuple('accel',   'x y z')
mag         = namedtuple('mag',   'x y z')
# quat        = namedtuple('quat', 'w x y z')  # json serializable representation of Quaternion
mpuData     = namedtuple('mpuData', 'gyro accel mag heading temp time quat qangle',
                         defaults=((0., 0., 0., 0.),
                                   (0., 0., 0.),
                                   (0., 0., 0.),
                                   0., 0., 0.,
                                   # (1., 0., 0., 0.),  # use this if sending quaternions as tuple
                                   Quaternion(),
                                   0.))

euler       = namedtuple('euler', 'roll pitch yaw')

observeTurn = namedtuple('observeTurn', 'angle')
executeTurn = namedtuple('executeTurn', 'angle')
observeHeading = namedtuple('observeHeading', 'heading')
executeHeading = namedtuple('executeHeading', 'heading')
observeRange = namedtuple('observeRange', 'nav')
calibrateMagnetometer = namedtuple('calibrateMagnetometer', 'samples source')
mag_corrections = namedtuple('mag_corrections', 'alpha beta xform0, xform1, xform2, xform3')
move_config = namedtuple('move_config', [
                           'wheel_diameter',
                           'counts_per_rev',
                           'm1_direction',
                           'm2_direction',
                           'm3_direction',
                           'm4_direction'],
                           defaults=(17.78, 130, -1, 1, 0, 0)
                           )

distance    = namedtuple('distance', 'n s e w t')

motorCommandResult = namedtuple('motorCommandResult',
                                'status command reply time')

dance       = namedtuple('dance', 'song')
speech      = namedtuple('speech','msg save', defaults=('',))
feedback    = namedtuple('feedback','info')
exec_report = namedtuple('exec_report', 'name info', defaults=('telemetry', {}))
screen      = namedtuple('screen', 'power')
iot         = namedtuple('iot', 'msg')
select_camera = namedtuple('select_camera', 'name')

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
    'Application': {feedback, exec_report, dict},
    'Dance': {dance},
    'IoT': {iot},
    'Camera': {select_camera}
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
    's': {2: {speech: [str]}, 3:{speech: [str, str]}},
    'd': {2: {dance: [str]}},
    'm': {3: {calibrateMagnetometer: [int, str]}},
    'report': {2: {exec_report: [str]}},
    'camera': {2: {select_camera: [str]}},
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


def get_move_config(robot_id):
    robot_move_config = move_config()
    try:
        with sqlite3.connect(dbfile) as con:
            con.row_factory = sqlite3.Row
            cursor = con.cursor()
            config_rec = cursor.execute(
                "SELECT * FROM move_config \
                WHERE move_config.robot_id=?", (robot_id,))
            config_record = config_rec.fetchone()
        robot_move_config = move_config(float(config_record['wheel_diameter']),
                                        int(config_record['counts_per_rev']),
                                        int(config_record['m1_direction']),
                                        int(config_record['m2_direction']), 0, 0)
    except Exception as e:
        print(f"Error getting move configuration for robot {robot_name}: {e}")

    return robot_move_config


robot_move_config = get_move_config(robot_id)
# print(f"Move Configuration: {str(robot_move_config)}")

robot_calibrations = Calibration()
