"""
calibration.py - Execute calibration processes for sensors with complex
    requirements such as magnetometers.
    THIS MODULE IS WIP and not yet integrated into the overall system.
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


import sqlite3
from dataclasses import dataclass, field
from typing import List

from lbrsys.settings import robot_name, dbfile


def load_calibrations():
    print("running load")
    calibrations = []
    try:
        with sqlite3.connect(dbfile) as con:
            con.row_factory = sqlite3.Row
            cursor = con.cursor()
            calibration_records = cursor.execute(
                "SELECT * FROM calibration \
                JOIN robot ON calibration.robot_id=robot.robot_id \
                WHERE robot.name=?", (robot_name,))

            calibrations = [CalibrationSetting(c['id'], c['robot_id'], c['name'], c['value'])
                            for c in calibration_records]

    except Exception as e:
        print(f"Error loading calibrations: {e}")

    return calibrations


@dataclass
class CalibrationSetting:
    id: int
    robot_id: str
    name: str
    value: float


@dataclass
class Calibration:
    settings: List[CalibrationSetting] = field(default_factory=load_calibrations)


if __name__ == '__main__':
    cal = Calibration()
    print(cal)
