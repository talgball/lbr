"""
calibration.py - Execute calibration processes for sensors with complex
    requirements such as magnetometers.
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2021 Tal G. Ball"
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
from typing import List, Any

from lbrsys.settings import robot_name, dbfile


def load_calibrations():
    calibrations = []
    try:
        with sqlite3.connect(dbfile) as con:
            con.row_factory = sqlite3.Row
            cursor = con.cursor()
            calibration_records = cursor.execute(
                "SELECT * FROM calibration \
                JOIN robot ON calibration.robot_id=robot.robot_id \
                WHERE robot.name=?", (robot_name,))

            calibrations = [CalibrationSetting(c['robot_id'], c['name'], c['value'], c['id'])
                            for c in calibration_records]

    except Exception as e:
        print(f"Error loading calibrations: {e}")

    return calibrations


@dataclass
class CalibrationSetting: # todo consider eliminating id and making compound pk with robot_id and name
    robot_id: int
    name: str
    value: float
    id: int = 0
    # con: Any = None
    # cursor: Any = None

    '''
    def __post_init__(self):
        try:
            self.con = sqlite3.connect(dbfile)
            self.con.row_factory = sqlite3.Row
            self.cursor = self.con.cursor()
        except Exception as e:
            print(f"Error connecting to calibrary database: {e}")
    '''

    def save(self):
        if self.id != 0:
            try:
                with sqlite3.connect(dbfile) as con:
                    con.row_factory = sqlite3.Row
                    cursor = con.cursor()
                    cursor.execute(
                        "UPDATE calibration \
                        SET value = ? \
                        WHERE id = ?",
                        (self.value, self.id))
                    con.commit()

            except Exception as e:
                print(f"Error saving calibration {self.name}={self.value}: {e}")
        else:
            try:
                with sqlite3.connect(dbfile) as con:
                    con.row_factory = sqlite3.Row
                    cursor = con.cursor()

                    cursor.execute(
                        "INSERT INTO calibration \
                            (robot_id, name, value) \
                        VALUES (?, ?, ?)", (self.robot_id, self.name, self.value))
                    con.commit()
                r = cursor.execute(
                    "SELECT * from calibration \
                    WHERE robot_id = ? AND name = ? AND value = ?",
                    (self.robot_id, self.name, self.value))
                c = r.fetchone()
                self.id = c['id']

            except Exception as e:
                print(f"Error saving calibration {self.name}={self.value}: {e}")


@dataclass
class Calibration:
    settings: List[CalibrationSetting] = field(default_factory=load_calibrations)

    def find_setting(self, name, default=0.):
        value = default
        found = None
        for s in self.settings:
            if s.name == name:
                value = s.value
                found = s
                break
        return value, found


if __name__ == '__main__':
    cal = Calibration()
    print(cal)

    print("Saving new calibration setting")
    new_cal = CalibrationSetting(1, 'NEWCAL', 123.456)
    new_cal.save()
    input("Press enter to continue: ")
    print("Updating new calibration setting")
    new_cal.value = 789.012
    new_cal.save()
