"""
Driver for InvenSense mpu9150 9 axis motion processor
    https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-9150-Datasheet.pdf
    For now, this driver is specific for raspberry pi because of i2c details

    Note that magnetometer compensation factors are included to correct for hard iron
    distortions for a particular robot, lbr2a.  These factors can be calculated according
    to the procedure described in, for example:
        https://www.vectornav.com/support/library/magnetometer

    As of this writing, the lbr2a did not exhibit soft iron distortions.  Correcting
    for soft iron distoritions requires an expression to be developed, as opposed to
    constants.  The function MPU9150_A.adjustIron would need an update to implement
    soft iron compensation.
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


import os
if os.uname()[0] == 'Linux':
    import smbus
else:
    print(("Unsupported OS: %s" % str(os.uname())))
    raise Exception()

import sys
sys.path.append('..') # for testing

import time
from time import time as robtimer # legacy naming issue

from math import *
from robcom import publisher

from lbrsys import robot_id, gyro, accel, mag, mpuData
from lbrsys.settings import LOG_DIR
from lbrsys.settings import MPU9150_ADDRESS # typically 0x68
from lbrsys.settings import X_Convention, Y_Convention, Z_Convention
from lbrsys.settings import magCalibrationLogFile
from robdrivers.calibration import Calibration, CalibrationSetting
from robdrivers.magcal import calc_mag_correction


POWER_MGMT_1        = 0x6b
GYRO_CONFIG         = 0x1b
ACCEL_CONFIG        = 0x1c
SAMPLE_RATE_DIVIDER = 0x19
READINGS_START_REG  = 0x3b
READINGS_LEN        = 22
INT_PIN_CFG         = 0x37  # bit 1 is i2c_BYPASS_EN (set for host access)
USER_CTRL           = 0x6a  # bit 5 is i2c_MST_EN
MAG                 = 0x25
MAG_REGISTER        = 0x26
MAG_CTRL            = 0x27  # bit 7 is enable, bits 0-4 length
WRITE_TO_MAG        = 0x63

# slave registers
MAG_WAI             = 0x00  # device id fixed at 0x48
MAG_ADDRESS         = 0x0c  # address of AK8975C magnetometer in pass through mode
MAG_READ_ADDRESS    = 0x80 | MAG_ADDRESS  # set read flag
MAG_STATUS1         = 0x02  # 1 when data is ready
MAG_STATUS2         = 0x09  # 0 normal; 1 data read error
MAG_DATA            = 0x03  # length 6
MAG_SENS_ADJ        = 0x10  # length 3, sensitivity adjustment
MAG_CNTL            = 0x0A  # set to 1 for a single measurement


class MPU9150_A:
    bus = smbus.SMBus(1)

    #timeout        = 0 #non-blocking mode
    zeroGyroResult  = gyro(0.0,0.0,0.0,0.0)
    zeroAccelResult = accel(0.0,0.0,0.0)
    zeroMagResult   = mag(0.0,0.0,0.0)

    # todo - validate these settings, see page 30 of register map
    gyroRanges = { 250: 0x0,
                   500: 0x08,
                   1000:0x10,
                   2000:0x18 }


    # def __init__(self, port=MPU9150_ADDRESS, hix=-17.9244, hiy=-15.01645):
    def __init__(self, port=MPU9150_ADDRESS):

        self.port = port
        # hard iron offsets in uT measured on 2019-01-28 for lbr2a
        # for an untested device, set the default values to
        # hix = 0, hiy = 0
        # self.hix        = hix
        # self.hiy        = hiy
        self.hix = 0
        self.hiy = 0
        self.alpha_setting = None
        self.beta_setting = None
        self.mpu_enabled = False
        self.read_errors = 0
        self.error_limit = 3
        self.mpuPub     = publisher.Publisher("MPU Message Publisher")
        self.gyroPub    = publisher.Publisher("Gyro Publisher")
        self.doPublish  = False # doPublish means publish even if the result 0
        self.onRecord   = False

        self.gyroRange          = 250   # dps
        self.gyroFullScaleRange = 2000  # dps
        self.gyroSquelch        = 0.09
        self.gyroCalibration    = self.zeroGyroResult

        self.accelRange = 0  # selects range of +/- 2g

        #self.magDecl       = 13+55./60. # todo dynamically look up declination
        self.magDecl        = 0.
        self.magResolution  = 0.3 # AK8975C for MPU9150, +4095 to -4096 : +-1229uT
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

        self.setup()

    def setup(self):
        
        try:
            # initialize the device here
            self.mpu = self.port # legacy from when it was a serial device
            self.mag = MAG_ADDRESS
            
            # power up the device by selecting the gyro oscilator
            self.bus.write_byte_data(self.mpu, POWER_MGMT_1, 0x01)

            # respect the 30ms startup time for the gyroscope
            time.sleep(0.030)

            # enable slave i2c mode
            #self.bus.write_byte_data(self.mpu, USER_CTRL, 0x20)

            # enable direct access mode
            self.bus.write_byte_data(self.mpu, USER_CTRL, 0x00)
            
            # setup the magnetometer

            # for slave mode: set mode to single read and do reading
            #self.bus.write_byte_data(self.mpu, WRITE_TO_MAG, 0x01)
            #self.sampleMagnetometer()

            # set mode to bypass for direct access to magnetometer from the host
            self.bus.write_byte_data(self.mpu, INT_PIN_CFG, 0x02)

            # get magnetometer sensitivity adjustments
            self.bus.write_byte_data(self.mag, MAG_CNTL, 0x0f)
            time.sleep(0.010)
            self.asa = self.bus.read_i2c_block_data(self.mag, MAG_SENS_ADJ, 3)

            # get hard iron calibration adjustments
            self.get_mag_calibration()
            # print(f"mag calibrations: hix={self.hix}, hiy={self.hiy}")

            # queue up the first sensor run
            self.bus.write_byte_data(self.mag, MAG_CNTL, 0x01)

        except:
            print("Unexpected error initializing MPU:", sys.exc_info()[0])
            raise  

        self.mpu_enabled = True

        if not self.setGyroRange(250):
            print("Failed to set gyro range")
        
        #todo set accel range


    def reset(self):
        self.close()
        self.read_errors = 0
        time.sleep(2) # todo - determine a good amount of time for the reset
        self.setup()


    def sampleMagnetometer(self):
        """sample magnetometer in slave mode. Data is placed in EXT registers"""
        self.bus.write_byte_data(self.mpu, MAG, MAG_ADDRESS)
        self.bus.write_byte_data(self.mpu, MAG_REGISTER, MAG_CNTL)
        self.bus.write_byte_data(self.mpu, MAG_CTRL, 0x81)

        self.bus.write_byte_data(self.mpu, MAG, MAG_READ_ADDRESS)
        self.bus.write_byte_data(self.mpu, MAG_REGISTER, MAG_STATUS1)
        self.bus.write_byte_data(self.mpu, MAG_CTRL, 0x88)
        return

    def get_mag_calibration(self):
        cal = Calibration()
        self.hix, self.alpha_setting = cal.find_setting('MAG_ALPHA')
        self.hiy, self.beta_setting = cal.find_setting('MAG_BETA')
        return


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
        """
        hadj = [h[0]-self.hix, h[1]-self.hiy, h[2]]
        return hadj
        
    def readMagnetometer(self):
        """
        returns new sensitivity adjusted mag reading in uT if it's ready
            or most recent previous reading
        Note that mag sensor normally operates at 8-10Hz (read cycle is 9ms),
            while accel and gyro can run at 200Hz
        """
        
        drdy = self.bus.read_byte_data(self.mag, MAG_STATUS1)
        if drdy == 1:
            lsbraw = self.bus.read_i2c_block_data(self.mag, MAG_DATA, 7)
            status = lsbraw[6]
            
            if status == 0: # normal
                lsbrawi = [lsbraw[i+1]<<8|lsbraw[i] for i in range(0, 6, 2)]
                lsbraw2 = list(map(self.twos_comp, lsbrawi))
                lsbadj  = self.adjustSensitivity(lsbraw2)
                msu = [m*self.magResolution for m in lsbadj]
                msuadji = self.adjustIron(msu)
                self.lastm = mag(round(msuadji[0], 4),
                                 round(msuadji[1], 4),
                                 round(msuadji[2], 4))
            else:
                if status & 0x04:
                    print("Magnetic data read error")
                if status & 0x08:
                    print("Magnetic sensor overflow occured")
                    # when |X|+|Y|+|Z| > 2400uT

        # order some for next time
        if self.bus.read_byte_data(self.mag, MAG_CNTL) == 0:
            self.bus.write_byte_data(self.mag, MAG_CNTL, 0x01)
                    
        return self.lastm

        
    def setGyroRange(self, gyroRange=250, calibrate=True):
        """
        The gyro full scale range is controlled by bits 3 and 4 of register 1B.
        It is ok to write to the whole register, as the other bits are
        normally 0 unless a test is enabled.
        """
        if gyroRange in self.gyroRanges:
            rangeCode = self.gyroRanges[gyroRange]
        else:
            return False #todo: raise an exception
            
        try:
            self.bus.write_byte_data(self.mpu, GYRO_CONFIG, rangeCode)
            self.gyroRange = gyroRange

            if calibrate:
                self.gyroCalibration = self.calibrateGyro()

        except:
            print("Unexpected error:", sys.exc_info()[0])
            raise

        return True


    def read(self):
        """
         Ask for accelerometer, temperature, gyro, as a burst.
                
         While the accel, temp and gyro registers are in big endian order,
           the mag data is in little endian.

        Magnetometer reading has been delegated to separate function since
            the data isn't ready as often as the others. (The MPU EXT registers
            are still read as they would have been in slave mode, but the data
            will not be valid.  Instead, the mag data is collected directly
            from the magnetometer.  Leaving this in makes changing back to
            slave mode easier, should the need arise.)
        """

        if not self.mpu_enabled:
            return self.mpusu_zero

        if self.read_errors > self.error_limit:
            print("Resetting MPU due to excessive read errors")
            self.reset()
            return self.mpusu_zero

        try:
            # self.sampleMagnetometer() # only in slave mode
            regs = self.bus.read_i2c_block_data(self.mpu, READINGS_START_REG,
                                                READINGS_LEN)
        except IOError:
            self.read_errors += 1
            print("Unexpected MPU read error:", sys.exc_info()[0])
            print("\treturning 0 result")
            return self.mpusu_zero
            # raise

        t = robtimer()
        lsb = tuple()

        # accelerometer
        for i in range(0, 6, 2):
            lsb += (self.twos_comp(regs[i]<<8|regs[i+1]),)

        # temperature
        lsb += (self.twos_comp(regs[6] << 8 | regs[7]),)

        # gyro
        for i in range(8, 14, 2):
            lsb += (self.twos_comp(regs[i]<<8|regs[i+1]),)
    
        lsb += (t,)

        mpusu = self.lsb2su(lsb)
        self.mpuPub.publish(mpusu)
        self.gyroPub.publish(mpusu.gyro) # publish separately for legacy reasons..
        self.lastsu = mpusu

        self.numReads += 1

        return mpusu

    def twos_comp(self, val, bits=16):
        """compute the 2's complement of int value val"""
        if (val & (1 << (bits - 1))) != 0:  # if sign bit is set e.g., 8bit: 128-255
            val = val - (1 << bits)  # compute negative value
        return val

    def lsb2su(self, lsb):
        """
        local sensor bus (LSB) to standard units (SI)
        lsb format: (accelx,accely,accelz,temp,gyrox,gyroy,gyroz,compx,compy,compz)
         conversion formulas from InvenSense UI Data Logger App Note,
         MPU9150 Register Map and Product Spec, and
           for magnetometer: https://www.loveelectronics.co.uk/Tutorials/13/tilt-compensated-compass-arduino-tutorial
        """

        #print lsb
        t0 = robtimer()
        t = lsb[-1]
        
        # accelerometer in g
        aR = self.accelRange
        aR = 1.0
        # print("accel lsb: x=%d, y=%d, z=%d" % (lsb[0], lsb[1], lsb[2]))
        a = accel(round(float(lsb[0]/16384.) * aR, 4),
                  round(float(lsb[1]/16384.) * aR, 4),
                  round(float(lsb[2]/16384.) * aR, 4))
        
        # temperature in C
        temperature = round((lsb[3]/340. + 35), 1)

        # gyro in deg/sec
        gR   = self.gyroRange
        gR = 1
        calx = self.gyroCalibration.x
        caly = self.gyroCalibration.y
        calz = self.gyroCalibration.z
        
        gL = [(float(lsb[4]/131.) * gR - calx) * X_Convention,
              (float(lsb[5]/131.) * gR - caly) * Y_Convention,
              (float(lsb[6]/131.) * gR - calz) * Z_Convention]

        # further squelch noise
        for i in range(len(gL)):
            if abs(gL[i]) < self.gyroSquelch:
                gL[i] = 0.0
        g = gyro(round(gL[0],3),
                 round(gL[1],3),
                 round(gL[2],3),
                 round(t,4))

        # merge in the magentometer results
        # magnetometer function already returns mag uT
        m = self.zeroMagResult
        try:
            m = self.readMagnetometer()
        except Exception:
            self.read_errors += 1
            print("Magnetometer exception", sys.exc_info()[0])
           
        '''
        # this has to be re-worked since readMagnetometer()                
        #todo: better error handling for a.y, a.x domains
        if a.y <= 1.0:
            rollRadians = asin(a.y)
        else:
            rollRadians = asin(1.0)
        if a.x <= 1.0:
            pitchRadians = asin(a.x)
        else:
            pitchRadians = asin(1.0)
            
        # algorithm good for tilt <= 40 degrees, ignore tilt otherwise for now

        if abs(rollRadians) > 0.78 or abs(pitchRadians) > 0.78:
            m.x = self.magResolution * lsb[8]  # appears x-y swapped 
            m.y = self.magResolution * lsb[7]
        else:
            cosRoll = cos(rollRadians)
            sinRoll = sin(rollRadians)
            cosPitch = cos(pitchRadians)
            sinPitch = sin(pitchRadians)
            magx = self.magResolution * lsb[7] # may need to swap x-y, investigate
            magy = self.magResolution * lsb[8]
            magz = self.magResolution * lsb[9] * -1 # to align with accelerometer

            cx = magx * cosPitch + magz * sinPitch
            cy = magx * sinRoll * sinPitch + magy * cosRoll - \
                 magz * sinRoll * cosPitch

        if cy > 0:
            heading = 90. - atan(cy/cx) * 180./pi
        elif cy < 0:
            heading = 270. - atan(cy/cx) * 180./pi
        elif cy == 0:
            if cx < 0:
                heading = 180.
            else:
                heading = 0.
        else:
            heading = -1
        '''
        # This version of the algorithm does not tilt compensate

        heading = -1
        if m.y == 0:
            if m.x <= 0:
                heading = 0.
            elif m.x > 0:
                heading = 180.
        else:
            rawAngle = atan(m.x/m.y) * 180./ pi
            #print rawAngle
            if m.y <= 0:
                heading = round((270. + rawAngle), 0)
            else:
                heading = round((90. + rawAngle), 0)

        #print 'heading: %.0f' % heading
        su = mpuData(g, a, m, round(heading,2), temperature, round(t,4))

        deltat = robtimer()-t0
        self.unitConTime += deltat
        
        return su


    def calibrateGyro(self):
        """
        Simple software calibration method previously used with ITG3200
        eval board.  A more official approach is probably available
        at this point.  The main purpose of this approach is to cancel
        noise to avoid reporting small angular movement when the device
        is stationary.
        """

        calx = 0.0
        caly = 0.0
        calz = 0.0

        recordCount = 0
        for i in range(100):
            su = self.read()
            if su is not None:
                calx += su.gyro.x
                caly += su.gyro.y
                calz += su.gyro.z
                recordCount += 1

            # Read at ~50Hz instead of 200Hz full speed.
            # Just being conservative for calibration.
            time.sleep(0.020)

        # print("Gyro Calibration: z total %f/ %d readings = %f degrees/sec" % (
        #     calz, recordCount, calz/recordCount/Z_Convention))

        if recordCount != 0:
            result = gyro(  float(calx)/recordCount/X_Convention,
                            float(caly)/recordCount/Y_Convention,
                            float(calz)/recordCount/Z_Convention,
                            0.0) # timestamp 0.0 for calibration by convention

        else:
            result = self.zeroGyroResult
            # todo: Likely should raise an exception here..

        # print "gyro calibration %.2f,%.2f,%.2f" % (result.x,result.y,result.z)
        return result


    def calibrateMag(self, samples=500, source=None):
        """
        Execute calibration procedure to calculate the hard (and eventually soft)
        iron adjustments.  Note that the robot must be in a safe location for spinning
        around it's Z axis in order to collect the data.
        :param: samples - the number of magnetometer readings to collect
        :param: source - Collect new samples if None, otherwise read samples from path given by source.
        :return:
        todo - simplify using numpy arrays
        """
        if samples > 1000:
            print(f"Samples limited to 1000 instead of {samples}")
            samples = 1000

        cal_data = []
        x = None
        y = None

        if source is None:
            print("Collecting magnetometer calibration data.  Robot should be spinning about its z axis.")
            for r in range(samples):
                cal_data.append(self.read())
                time.sleep(0.150)
            print("Calibration data collected.")
            print(f"Example: {str(cal_data[-1])}")

            x = [r.mag.x for r in cal_data]
            y = [r.mag.y for r in cal_data]

            try:
                self.save_cal_data(cal_data)
            except Exception as e:
                print(f"Error saving magnetometer samples:\n{str(e)}")
                return

        try:
            if source is not None:
                source_path = os.path.join(LOG_DIR, source)
            else:
                source_path = source

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


    def close(self):
        self.mpu_enabled = False
        try:
            # self.mpu.close()
            # for the i2c version of the driver, interpret close as reset mpu
            self.bus.write_byte_data(self.mpu, POWER_MGMT_1, 0x80)
            self.mpuPub.publish(time.asctime() + " InvenSense MPU Closed")
        except:
            msg = time.asctime() + " Error Closing Controller"
            self.mpuPub.publish(msg)
            print(msg)


if __name__ == '__main__':
    mpu = MPU9150_A() # note: can optionally pass a port name to the constructor
    # k = input("Press return to continue")
    rl = []
    t0 = robtimer()
    for n in range(100): # normally 100 for this test
        rl.append(mpu.read())
        time.sleep(0.01)

    t1 = robtimer()
    dt = t1-t0
    print("Elapsed time for 100 cycles: %.4f, avg/cycle: %.4f, freq: %.4f" % \
          (dt,dt/100.,100./dt))
    print("Reads: %d, Avg Unit Conv Time: %fus" % \
          (mpu.numReads, mpu.unitConTime/mpu.numReads*1000000))

    #for r in rl:
    #    print r
    print(rl[-1])
    r = rl[-1]
    print("magnetic field magnitude: %.2fuT" % (sqrt(r.mag.x**2 +
                                               r.mag.y**2 +
                                               r.mag.z**2)))

    """
     Intent is to use the driver from the command line from this
     point for testing.
     call mpu.close() when finished
    """
