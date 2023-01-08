"""
    Device driver for the Roboteq RIOX-1216AHRS.

        For this driver, importing PyRoboteq package, which is still under development
        as noted on its pypi.org page.  todo investigate why partial resulsts from RIOX
        are sometimes returned, resulting in driver read errors.  Ignored for now.
"""


__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2022 Tal G. Ball"
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

import os
import sys
import time
from math import *
import numpy as np
import PyRoboteq

from pyquaternion import Quaternion

from lbrsys import robot_id, gyro, accel, mag, mpuData, euler, mag_corrections
from lbrsys.robcom import publisher
from lbrsys.settings import LOG_DIR
from lbrsys.settings import X_Convention, Y_Convention, Z_Convention
from lbrsys.settings import magCalibrationLogFile
from lbrsys.settings import RIOX_1216AHRS_Port

from lbrsys.robdrivers.calibration import Calibration, CalibrationSetting
from lbrsys.robdrivers.magcal import calc_mag_correction, make_plot, get_mag_corrections

# Commands for RIOX not covered by PyRoboteq, as it was designed for a motor controller
READ_ALL_MEMS = '?ML'
READ_AHRS_DEGREES = '?EO'
READ_AHRS_QUATERNION = '?QO'


class RIOX(PyRoboteq.RoboteqHandler):
    zeroGyroResult = gyro(0.0,0.0,0.0,0.0)
    zeroAccelResult = accel(0.0,0.0,0.0)
    zeroMagResult = mag(0.0,0.0,0.0)

    def __init__(self, port=RIOX_1216AHRS_Port):
        super(RIOX, self).__init__(debug_mode=False, exit_on_interrupt=False)
        self.port = port

        self.mag_corrections = None
        self.hix = -34.35
        self.hiy = -8.85
        self.corrections = np.array([[0.70402391, -0.09952104], [-0.09952104, 0.96653636]])  # todo replace with lookup
        self.alpha_setting = None
        self.beta_setting = None
        self.mpu_enabled = True
        self.mems_enabled = True
        self.ahrs_enabled = False
        self.read_errors = 0
        self.error_limit = 3
        self.mpuPub     = publisher.Publisher("MPU Message Publisher")
        self.gyroPub    = publisher.Publisher("Gyro Publisher")
        self.doPublish  = False # doPublish means publish even if the result 0
        self.onRecord   = False

        # range setting seems unsupported for the RIOX
        # (gyroRange 4 is 1000 deg/sec) guessing for RIOX, 250, 500, 1000 or 2000 deg/sec
        self.gyroRange          = 4
        self.gyroFullScaleRange = 2000  # dps
        self.gyroSquelch        = 0.09
        self.gyroCalibration    = self.zeroGyroResult

        self.accelRange = 0  # selects range of +/- 2g

        #self.magDecl       = 13+55./60. # todo dynamically look up declination
        self.magDecl        = 0.
        self.magResolution  = 0.3 # AK8975C for MPU9150, +4095 to -4096 : +-1229uT, 0.3uT/LSB
        # self.magResolution  = 1.0 # Assume already adjusted for RIOX case
        self.asa            = [0.,0.,0.]  # sensitivy adjustments

        self.rawAngleL  = []
        self.lastg      = self.zeroGyroResult
        self.lasta      = self.zeroAccelResult
        self.lastm      = self.zeroMagResult
        self.lastsu     = mpuData(self.zeroGyroResult,
                                  self.zeroAccelResult,
                                  self.zeroMagResult,
                                  0.,0.,0.)
        self.mpusu_zero = mpuData(self.zeroGyroResult,
                                  self.zeroAccelResult,
                                  self.zeroMagResult,
                                  0., 0., 0.)

        self.lastRawAngle = -1
        self.unitConTime = 0
        self.numReads    = 0

        try:
            self.connected = self.connect(self.port)
        except Exception as e:
            print(f"Error connecting to RIOX on {port}")
            raise e

        self.mag_corrections = self.fetch_mag_corrections


    def read(self):
        if self.mems_enabled:
            return self.read_mems()

        if self.ahrs_enabled:
            return self.read_ahrs()

        return self.mpusu_zero

    def read_mems(self):
        if not self.mpu_enabled:
            return self.mpusu_zero

        mems = self.read_value(READ_ALL_MEMS)
        t = time.time()
        # print(mems)

        if mems.startswith(READ_ALL_MEMS[1:]):
            lsb = mems[len(READ_ALL_MEMS):].split(':')
            if len(lsb) != 10:
                self.read_errors += 1
                # print(f"Malformed mpu read: {mems}", file=sys.stderr)
                return self.lastsu

            try:
                lsb = list(map(lambda x: int(x), lsb))
            except ValueError as e:
                self.read_errors += 1
                print(f"ValueError: {e}", file=sys.stderr)
                return self.lastsu

            lsb += (t,)
            # print(f"lsb = {lsb}", file=sys.stderr)

            mpusu = self.lsb2su(lsb)
            # print(f"mpusu = {mpusu}", file=sys.stderr)

            self.mpuPub.publish(mpusu)
            self.gyroPub.publish(mpusu.gyro) # publish separately for legacy reasons..
            self.lastsu = mpusu

            self.numReads += 1
        else:
            self.read_errors += 1
            if self.read_errors > self.error_limit:
                pass
                # print("Resetting MPU due to excessive read errors")
                # self.reset()
                # print(f"MPU errors:{self.read_errors}, limit: {self.error_limit}", file=sys.stderr)
                # print(f"\t{mems}", file=sys.stderr)

            mpusu = self.lastsu

        return mpusu

    def lsb2su(self, lsb):
        """
        local sensor bus (LSB) to standard units (SI)
        lsb format: (accelx, accely, accelz, temp, gyrox, gyroy, gyroz, compx, compy, compz)
         conversion formulas from InvenSense UI Data Logger App Note,
         MPU9150 Register Map and Product Spec, and
           for magnetometer: https://www.loveelectronics.co.uk/Tutorials/13/tilt-compensated-compass-arduino-tutorial
        """

        # print lsb
        t0 = time.time()
        t = lsb[-1]

        # accelerometer in g
        # aR = self.accelRange
        aR = 1.0
        # print("accel lsb: x=%d, y=%d, z=%d" % (lsb[0], lsb[1], lsb[2]))
        a = accel(round(float(lsb[0] / 16384.) * aR, 4),
                  round(float(lsb[1] / 16384.) * aR, 4),
                  round(float(lsb[2] / 16384.) * aR, 4))

        # temperature in C
        temperature = round((lsb[3] / 340. + 35), 1)

        # gyro in deg/sec
        gR = self.gyroRange
        calx = self.gyroCalibration.x
        caly = self.gyroCalibration.y
        calz = self.gyroCalibration.z

        gL = [(float(lsb[4] / 131.) * gR - calx) * X_Convention,
              (float(lsb[5] / 131.) * gR - caly) * Y_Convention,
              (float(lsb[6] / 131.) * gR - calz) * Z_Convention]

        # further squelch noise
        for i in range(len(gL)):
            if abs(gL[i]) < self.gyroSquelch:
                gL[i] = 0.0
        g = gyro(round(gL[0], 3),
                 round(gL[1], 3),
                 round(gL[2], 3),
                 round(t, 4))

        lsbadj = lsb[7:10]
        # lsbadj = self.adjustSensitivity(lsb[7:10]) # No asa data for RIOX case

        msu = [m * self.magResolution for m in lsbadj]
        msuadji = self.adjustIron(msu)
        self.lastm = mag(round(msuadji[0], 4),
                         round(msuadji[1], 4),
                         round(msuadji[2], 4))

        m = self.lastm

        # This version of the algorithm does not tilt compensate
        heading = -1
        # x = m.x
        # y = -m.y
        # Align with the robot conventions and the sensor mounting direction
        x = -m.y
        y = m.x

        if x == 0:
            if y < 0.:
                heading = 180.
            elif y >= 0:
                heading = 0.
        else:
            rawAngle = atan(y / x) * 180. / pi

            if y >= 0 and x >= 0: # Quad 1
                heading = round(rawAngle, 0)
            elif y >= 0 and x < 0: # Quad 2
                heading = round((180. - abs(rawAngle)), 0)
            elif y < 0 and x < 0: # Quad 3
                heading = round((180. + abs(rawAngle)), 0)
            else: # Quad 4
                heading = round((360. - abs(rawAngle)), 0)

        su = mpuData(g, a, m, round(heading, 2), temperature, round(t, 4))

        deltat = time.time() - t0
        self.unitConTime += deltat

        return su

    def adjustSensitivity(self, h):
        """
        Adjustment for factory measured magnetometer sensitivity
        see https://www.akm.com/akm/en/file/datasheet/AK8975.pdf, sec 8.3.11
        """
        hadj = list(map(lambda x,a: x * (((a-128.)*0.5)/128.+1.), h, self.asa))
        return hadj

    def adjustIron(self, h):
        """
        Make hard and soft iron adjustments here.  As of 2019-01-28,
        lbr2a required hard iron adjustments but not soft iron.

        lbr6 needed both hard and soft iron adjustments as of 2022-12-30

        Two methods of soft iron correction are provided:
        If radius is available, move the given point onto a circle with the given
        radius, preserving the angle of a ray passing through the origin and the point.

        If radius is not available, use the rotation matrix corrections.

        Otherwise, adjust hard iron only.

        """

        # Get the hard iron adjustment out of the way
        hadj = [h[0]-self.hix, h[1]-self.hiy, h[2]]

        if self.corrections is not None:
            hadj_soft = self.corrections @ np.array([[hadj[0]], [hadj[1]]])
            hadj = list([hadj_soft[0][0], hadj_soft[1][0], h[2]])

        return hadj

    def calibrateMag(self, samples=500, source=None):
        """
        Execute calibration procedure to calculate the hard and soft
        iron adjustments.  Note that the robot must be in a safe location for spinning
        around it's Z axis in order to collect the data.
        :param: samples - the number of magnetometer readings to collect
        :param: source - Collect new samples if None or '-', otherwise read samples from path given by source.
            If '-c' then collect and view samples via existing corrections.
        :return:
        """
        # todo cleanup and integrate saving functions now that soft iron is implemented

        if samples > 1000:
            print(f"Samples limited to 1000 instead of {samples}")
            samples = 1000

        cal_data = []
        x = None
        y = None

        # todo externalize logic to control these flags
        do_save = True
        do_show = False

        if source is None or source.startswith('-') :
            if source == '-c':
                # do_save = False
                do_save = False
                do_show = True
            else:
                self.hix = 0.
                self.hiy = 0.
                self.corrections = None

            print("Collecting magnetometer calibration data.  Robot should be spinning about its z axis.")
            for r in range(samples):
                cal_data.append(self.read())
                time.sleep(0.150)
            print("Calibration data collected.")
            print(f"Example: {str(cal_data[-1])}")

            x = [r.mag.x for r in cal_data]
            y = [r.mag.y for r in cal_data]

            if do_save:
                try:
                    self.save_cal_data(cal_data)
                except Exception as e:
                    print(f"Error saving magnetometer samples:\n{str(e)}")
                    return

            if do_show:
                make_plot(x, y, "Corrected Data")
                return

        try:
            if source is not None and not source.startswith('-'):
                source_path = os.path.join(LOG_DIR, source)
            else:
                source_path = None

            alpha, beta, x_corrected, y_corrected = calc_mag_correction(x, y, source_path)
            self.hix = alpha
            self.hiy = beta

            if self.alpha_setting is None:
                self.alpha_setting = CalibrationSetting(robot_id, 'MAG_ALPHA', alpha)
            else:
                self.alpha_setting.value = alpha
            self.alpha_setting.save()

            if self.beta_setting is None:
                self.beta_setting = CalibrationSetting(robot_id, 'MAG_BETA', beta)
            else:
                self.beta_setting.value = beta
            self.beta_setting.save()

            self.save_corrected(x_corrected, y_corrected)
            print(f"Completed hard iron calibration with alpha {alpha}, beta {beta}")

        except Exception as calexception:
            print(f"Error calibrating magnetometer:\n{str(calexception)}")

        return

    def save_cal_data(self, cal_data):
        with open(magCalibrationLogFile, 'w') as f:
            print("X,Y,Z,Heading", file=f)
            for r in cal_data:
                print(f"{r.mag.x},{r.mag.y},{r.mag.z},{r.heading}", file=f)

    def save_corrected(self, x, y):
        with open(magCalibrationLogFile+'-corrected', 'w') as f:
            print("X-Corrected,Y-Corrected", file=f)
            for i in range(len(x)):
                print(f"{x[i]},{y[i]}", file=f)


    def reset(self):
        return

    def read_ahrs(self, units='Quaternion'):

        if not self.mpu_enabled:
            return self.mpusu_zero

        if units not in ['Quaternion', 'Euler']:
            print(f"Invalid units for read_ahrs: {units}")
            return Quaternion()

        cmd = READ_AHRS_QUATERNION if units == 'Quaternion' else READ_AHRS_DEGREES
        ahrs = self.read_value(cmd)
        ahrs = list(map(int, ahrs.split('=')[1].split(':')))

        if units == 'Quaternion':
            if len(ahrs) == 4:
                ahrs_out = Quaternion(*list(map(lambda x: round(x/16834., 6), ahrs)))
            else:
                print(f"Invalid AHRS for Quaternion: {ahrs}")
                ahrs_out = Quaternion()
        else:
            if len(ahrs) == 3:
                ahrs_out = euler(*list(map(lambda x: round(x/16834., 4), ahrs)))
            else:
                print(f"Invalid AHRS for Euler Angles: {ahrs}")
                ahrs_out = euler(0., 0., 0.)

        # todo add defaults to mpuData so that this function can return mpuData to
        #  integrate with the system and/or merge ahrs into mems mpuData
        return ahrs_out

    def close(self):
        return self.ser.close()


def test(n=10, units='Quaternion'):
    controller = RIOX()

    if controller.connected:
        results = []
        loop = n
        while loop > 0:
            r = controller.read_ahrs(units)
            # print(r)
            results.append(r)
            # time.sleep(0.1)
            loop -= 1

        controller.close()
        print(f"got {len(results)} results")
        return results


if __name__ == '__main__':
    """
    results = test(10, 'Quaternion')
    if len(results) <= 100:
        print(results)
    """
    controller = RIOX()
    for i in range(10):
        print(controller.read_mems())

    controller.close()