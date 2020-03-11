#
# robmsgdict.py - standard dictionary of messages
#   provided to stub out rudimentary localization support for canned content
#
#  Tuples are (message text, purpose, channel type)
#

stdDict = {'English':{
    'Hello':('Hello','Robot Greeting', 'Monitor'),
    'AheadSlow':('Moving ahead slowly.','Set power to 20% at 0 degrees', 'Operations'),
    'StopMotors':('Stopping motors.','Set power to 0 in both motor channels', 'Operations'),
    'RightTurn':('Turning right.','Set power to 20% forward in left motor and 20% reverse in right motor', 'Operations'),
    'LeftTurn':('Turning left.','Set power to 20% forward in right motor and 20% reverse in left motor.', 'Operations'),
    'Reverse':('Backing up.','Set power in both motors to 20% reverse', 'Operations'),
    'AheadHalf':('Moving ahead at half speed.','set power in both motors to 50% at 0 degrees','Operations'),
    'AheadFull':('Moving ahead at full speed.','set power in both motors to 75% at 0 degrees','Operations'),
    'FlankIn3':('Engaging flank speed in 3 seconds.','set power to 100% at 0 degrees in both motors','Operations'),
    'MainBatt':('Main battery voltage is ','words','Monitor'),
    'InternalVoltage':('Microcontroller internal voltage is ','words','Monitor'),
    'Volts':('Volts','words', 'Monitor'),
    'Volt':('Volt','words', 'Monitor'),
    'Motor1Current':('Current in motor 1 is ','words', 'Monitor'),
    'Motor2Current':('Current in motor 2 is ','words', 'Monitor'),
    'Amps':('Amps','word Amps','words','Monitor'),
    'Amp':('Amps','word Amp','words','Monitor'),
    '/r/':('Command','','Drive local operations','Operations')},

    'Spanish':{
    'Hello':'Ola'}}
           
    
