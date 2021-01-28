"""
lbrsys toplevel package settings to configure the system for use with
specific ports and configuration options
"""

import os
import socket


robot_name = 'lbr2a'

# set the port for use in the http service and find the ip address
# for the robot
robhttpPort = 9145
# usual approach not working on the rpi: robhttpAddress = (socket.gethostbyname_ex('')[2][0],robhttpPort)
# hack to reliably get ip address on Linux, pending better solution
_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_s.connect(("8.8.8.8", 80))
robhttpAddress = (_s.getsockname()[0], robhttpPort)
_s.close()



# set USE_SSL = True to enable https for the http service
#   Using this feature requires environment variables ROBOT_CERT and ROBOT_KEY
#   to point to the certificate and private key files
USE_SSL = True


# set the port for connecting to a Roboteq SDC2130 motor controller
SDC2130_Port = '/dev/ttyACM0'

# set the port for getting range and potentially other sensor data
#   In the default case, a Parallax Propeller P8X32 microcontroller is
#   producing range data using an array of Maxbotix MB1220 ultrasonic
#   range sensors
P8X32_1_Port = '/dev/ttyUSB0'

# i2c address for mpu9150 motion processing device
MPU9150_ADDRESS = 0x68

# directional and rotational conventions
#   Motion processing device driver observes these conventions
#   on directions for each axis
X_Convention = -1 # X - clockwise and forward are negative
Y_Convention = 1  # Y - clockwise and right are positive
Z_Convention = -1 # Z - clockwise and up are negative (e.g., gravity is down)


# URL for experimental use of the Jitsi system for teleconferencing (not currently in use)
jitsiURL = "https://meet.jit.si/bfrobotics"

# uncomment the following line to automatically start the navigation camera
LAUNCH_NAVCAM = True

# Set SPEECH_SERVICE = 'native' for a pyttsx3 based implementation or 'aws_polly' for cloud based speech
SPEECH_SERVICE = 'aws_polly'

# URL for the robot registration service for use in configuring peer to peer
#   communications via WebRTC.  Full URL needed.
#   This setting and feature is not used in version 1.0.
robRegisterURL = "https://robots.bfrobotics.net/robregister"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# sqlite3 database containing robot configuration
dbfile = os.path.join(BASE_DIR, 'lbrsys/robot.sqlite3')

# authorization token file for robot api
# tokenFile = os.path.join(BASE_DIR, '')
tokenFile = os.path.join(os.path.join(os.environ['ROBOT_CRED'], 'robauth.tokens'))

# log directory and file configuration
LOG_DIR = os.path.join(BASE_DIR, 'logs')

if not os.path.isdir(LOG_DIR):
    os.mkdir(LOG_DIR)

robLogFile     = os.path.join(LOG_DIR, 'robot.log')
opsLogFile     = os.path.join(LOG_DIR, 'ops.log')
mpLogFile      = os.path.join(LOG_DIR, 'mpu.log')
rangeLogFile   = os.path.join(LOG_DIR, 'range.log')
gyroLogFile    = os.path.join(LOG_DIR, 'gyro.log')
robhttpLogFile = os.path.join(LOG_DIR, 'robhttp.log')
speechLogFile  = os.path.join(LOG_DIR, 'speech.log')
iotLogFile     = os.path.join(LOG_DIR, 'iot.log')
rangeobserverLogFile = os.path.join(LOG_DIR, 'rangeobserver.log')
headingobserverLogFile = os.path.join(LOG_DIR, 'headingobserver.log')
magCalibrationLogFile = os.path.join(LOG_DIR, 'magCalibration.csv')
