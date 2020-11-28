# lbr - The "little brother robot" Project
Distributed Robot Operating System Architecture and Design Experiments

![System and Architecture](https://github.com/talgball/lbr/blob/master/docs/images/2020lbrsystem.png)

## Introduction
Telepresence is a young and promising space that has the potential for bringing people together in engaging and more 
flexible ways.  2020 has been a year of isolation for many people, and the long hours of video conferencing 
have made it possible to maintain more of life and work than would have been possible otherwise.  If instead of just
appearing passively on a screen, the remote people could engage more actively in the meeting space and with the other 
participants, the quality of communicating and connecting with each other would be radically enhanced and begin to 
feel more natural and rewarding.  In addition, being more deeply and continuously connected with family and community 
might also help people maintain their independence during periods of their lives that would have traditionally required 
specialized facilities.  Imagine a robot that is not only a telepresence device but is also equipped with sophisticated 
sensors and other devices to help people monitor their health issues and enable proactive support services.  Since a 
telepresence robot could have many remote users, doctors could make virutal house calls and provide a level of service 
beyond even the telehealth capabilities that have advanced over the past year.  The decision to open source the project
now is in the hope that it might be of some use or inspiration to others who seek to bring people closer together in the
years ahead.

This project houses an experimental code base for exploring robotics software architectures.  The concept of 
"robot" in the architecture is a distributed set of services and capabilities focused on satisfying one or more use
cases and typically delivered by one or more robotic hardware devices.  Telepresence, especially for residential use
cases, has been an initial target in mind to help guide and focus the research.

The project started in 2009 and has been progressing as a non-commercial, private research endeavor on a part time 
basis a few hours at a time over the past 11 years.  During that period, the capabilities of cloud platforms, further 
development and adoption
robotic operating systems like ROS, the rise of digital assistants like Alexa and Siri, and other advances in the state 
of the art have demonstrated that distributed and extensible sets of services can be integrated to produce a wide range 
of useful capabilities.  Adding physical robots as part of delivering those capabilities is a logical next step.  The
primary project goals of learning and developing concepts have been progressing alongside developments in the broader 
industry, and it's fun to participate and to play along.

To support development and testing of the software and architecture, a single robotics development hardware platform was
constructed.  While the code base here is configured for the specifics of that particular robot, the architecture and 
capabilities of the software would support a wide range of alternative hardware.  The software could be used as a whole
system, or its packages and modules could be used individually as needed to help with other projects.  As the code is
currently in an experimental state, it has not yet been packaged into a standard distribution package.  Instead, users
can clone or download this repository or any of its components, subject to the included Apache 2 license agreement and
notices.

## Demonstration Videos


## Software Overview
The embedded portion of the lbr software architecture is organized into 4 packages and an extensible collection of 
additional packages called, "applications".  There is also an external web client application and, at this writing, 
a small amount of supporting cloud services.  Only the embedded portion is being released at this time.  

Almost all of the code is written in python and currently requires python 3.5 or above.  The code style has evolved a
bit over the years, and your kind patience is requested.  When the project was started, my most recent commercial 
project that included personal coding was written in jython.  As we were using many Java libraries, we adopted 
CamelCase.  Of course, the python community prefers snake_case, and I have come ultimately come back home to that, 
although the previous packages have not been updated.  Also, users might notice that some packages and modules could 
do with significant refactoring, which often happens with long lived code bases.  They are on "the list."  Finally, 
some concepts have several different implementations across the code base.  That usually meant that each of them 
were interesting topics to explore and compare with each other over the course of the project.  Obviously, those 
would normally be optimized out in a commercial project.   

Unit testing for each module is behind the
 
    if __name__ == __main__:

statement near the bottom of the module.  The main entry point module, robot.py, is an exception to this rule.  
The others are not executed as mains at runtime except during unit testing.


### Executive
The executive package provides for configuring the robot at run time and commands the rest of the system.  It also 
provides for startup and shutdown operations.

A configuration module uses a sqllite database to store primary configuration information as metadata to specify 
capabilities of the robot.  The configuration process reads the database and arranges for indicated processes to be 
launched and connected together with various communications methods, typically python joinable queues, as specified in
the metadata.  The usual pattern is to create two joinable queues between connected processes.  One of them is used 
to send command messages, and the other one is used to convey response information such as telemetry back to the 
commanding process.  Using this approach, the robot itself is "softly modeled" and can be significantly modified and 
extended, often without changing the existing code, and could even "evolve" it's capabilities at runtime. 

After launching with the robot command, the system provides a command console in a terminal window.  Three types of 
commands are supported at the console: builtin, external and python.  Builtin commands are as follows:
* __/r/power/angle__ - Run the motors at a power level between 0 and 1 at a steering angle between 0 and 360 degrees 
from the robot's perspective, i.e. 0 degrees always mean straight ahead, and 180 is straight back.
* __/r/power/angle/range/sensor/interval__ - Run the motors at the given power level and angle subject to constraints:
  * *range* - Distance measured by the indicated sensor must remain greater than the value specified, between 0 and 769cm,
  or the motors are stopped.
  * *sensor* - Indicate which of forward, back, left or right range sensors to measure against the constraint.
  * *interval* - Stop the motors after the interval in seconds has expired, regardless of the range constraint.
* __S or s__ - Shortcut to immediately stop the motors.  Equivalent to /r/0/0.
* __/a/angle__ - Report when the robot has turned by the indicated number of degrees.
* __/t/angle__ - Turn the robot by the indicated number of degrees, 0 to +/- 360.  Positive angles turn clockwise.
* __/h/heading__ - Turn the robot to the indicated compass heading.
* __/s/text__ - Convert indicated text to speech and play it over default audio output. 
* __/d/song__ - Dance to the indicated song.  (Command no longer supported in current version.)
* __Shutdown__ - Shutdown the lbr software system

Note that when operating the robot from a client, such as the web application, these commands derived from indications 
expressed in the user interface and supplied automatically to the executive module for processing.  The command console
provides a manual means of controlling the robot without a client and is also useful during development and testing. 

External commands are added to the executive based on configurations in the metadata.  Typically, a command string 
and optional arguments are mapped to an entry point which is launched in a separate process on invocation.  Currently,
The following external commands are supported:
*  __navcam__ - Launch the navigation camera application, which is further described below in the __Applications__ section.
*  __docksignal__ - Launch the listener for infrared signals from the robot's charging dock to aid in docking navigation.
*  __autodock__ - Launch the automatic docking application to guide the robot into it's charging dock.

Hooks for command acceptance and further processing are stubbed out in the executive.  The idea behind this construct
is to provide a place in the architecture to connect to higher level rules or evaluation systems to determine whether 
some commands are acceptable or not prior to execution.

Finally, any console command line that starts with __!__ is passed to the python interpreter literally for attempted
execution.  The interpreter will have access to the namespace of the executive process. 


### Communications
The communications package contains modules that implement the supported communications processes and protocols. 

* __publish/subscribe__ - A lightweight facility for publishing and subscribing to messages, both within processes and 
between them.  Typical objects communicated are python named tuples, but messages are not type limited.  Subscribers
often inspect an incoming message's type to determine how to process it.
* authorization - A module to manage authorization tokens and authenticate users against them.  For example, tokens 
are used in communications with the web client to authenticate and authorize users. 
* __registration__ - A prototype module to register a robot with a centralized robotics service to facilitate further
communications and updates.  Not fully implemented currently. 
* __http service__ - A lightweight, embedded http server that also notionally implements a REST api to provide command 
processing and information flows between the robot and clients.  The service also supplies telemetry information on 
request to any interested process.  Messages to and from the service are in __application/json__ format.
This implementation is for development purposes and would be replaced by a production http server and applications 
prior to production deployment.  Although https and authentication are supported, the service is not sufficiently secure
for production.
* __http client__ - A lightweight client for communicating with the http service.  Clients such as Applications can embed
this module to flexibly connect with the http service and thereby the rest of the system.
* __speech__ - A wrapper around __pyttsx3__ and an adaptor to connect speech as a service to the system. 
* __dock signal__ - An interface to __lirc__ to capture and process infrared signals from the charging dock as aids to 
navigation during docking.
* __telemetry__ - Prototype module for generalizing telemetry processing.  Not currently in use.  A more advanced 
telemetry processing capability is implemented and utilized in the state machine package.
* __zoom manager__ - zoom is currently used for the video conferencing function in telepresence and has been typically 
managed manually.  This module will wrap the management of zoom communications and integrate and automate the management
process with the robot system.  This module is under development and not currently released.


### Operations
The operations package handles interactions between the robot systems and physical devices, including sensors and 
motors, and it provides the main operations loop for the system.  Communications with this package are implemented
as specified during configuration utilizing joinable queues.   
* __ops manager__ - The operations manager processes all commands that move the robot, and it gathers and communicates
telemetry data. It operates the main system loop.  The minimum loop time is configurable and is currently set at 10ms.  
If the system finishes all tasks executable in the current loop, the ops manager will wait until the remainder of the 
minimum loop time expires before starting the next loop iteration.  Typically, loop tasks are completed within a few
miliseconds.  This approach reduces cpu utilization and realistically aligns with the operating paradigm of the current
robot, i.e. a wheeled machine operating in a residential environment.  A much shorter loop time would be needed for a 
flying robot, for example.  The ops manager keeps and logs statistics on operation timings to enable further tuning of 
the system.  Excessively long loops, for example, typically indicate an error condition or bug has been encountered.
* __movement__ - The movement modules, notably __movepa.py__, translates the power and angle movement directives into 
precise parameters to communicate to the motor controller.  The translation algorithm can be adjusted based on the 
configuration of the robot motors and steering mechanisms.  The current robot employs tank like steering, as it has 
left and right motors that operate independently.
* __motion processing__ - Telemetry information is gathered from the 9 axis motion processing system and combined 
with other information for use in adjusting operations and to communicate across the system.
* __range__ - Operates the array of 4 ultrasonic range sensors and reports the distances forward, back, left and right
to the nearest object in each of those directions.
* __observers__ - Observers look for a particular condition to occur based on sensor data and report their findings 
back to the operations manager.  For example, a command to turn the robot by 45 degrees would launch a gyroscope 
observer to watch the rate of spin over a series of short time intervals to calculate the amount of turning that the
robot has experienced since the command was issued.  When the observer concludes that 45 degrees of turn has occurred,
it signals the ops manager to stop the motors.
* __ops rules__ - The rules system is consulted when the ops manager is processing a movement command to determine if
the movement is safe or should be adjusted for local conditions.  For example, when the robot is approaching an object,
the rules reduce the speed of the robot, regardless of the currently commanded speed, and when a minimum distance is 
reached, the robot automatically stops.  Note that currently only a forward range rule is implemented.


### Drivers
The drivers package contains a collection of modules for interfacing physical devices to the lbr system.  Note that they
are python modules operating in user space, as opposed to typical low level kernel mode drivers.  In practice these
drivers sit on top of their underlying operating system counterparts.  For example, if a device is connected to the 
system via USB port, the operating system's serial driver implements the underlying interface, and the lbr python driver
uses the serial interface to communicate semantically appropriate information between the device and the ops manager or
other interested processes.  These modules might be useful on a standalone basis for people who happen to have these
particular or similar devices and are in need of python drivers.

* __motors__ - A driver for the Roboteq SDC2130 2X20Amp motor controller is provided.  This driver communicates over USB 
using Roboteq's proprietary protocol to manage motor operations and report on electrical conditions, including battery 
voltage and the amount of current flowing through the motors.  The driver also implements a master feature toggle to
enable or disable motor operations.  When disabled, the driver does all of it's normal operations except for actually 
running the motors.  This toggle is useful during development and debugging, especially when there are potential safety
concerns when a paricular operation is being developed.
* __ultrasonic rangers__ - A driver to communicate over USB with a Parallax P8X32 microcontroller that has been 
programmed to operate an array of 4 MaxBotix MB1220 ultrasonic range sensors.  A package of readings is gathered on 
request and provided to the range operator running at the request of the operations manager.  The sensors gather a set of 
readings 10 times per second, and the range operator is set to request the data at the same rate.  Provisions were 
made in the software to support a 5th sensor to check for bottom distance, in case for example, the robot is approaching
a staircase, but that sensor is not installed in the current robot.  
* __9 axis mpu__ A driver to communicate over the i2c bus with an InvenSense MPU9150 9 axis motion processing unit. The
unit contains a 3 axis gyroscope, accelerometer and magnetometer.  Readings are gathered at the request of motion 
processing operations at the request of the operations manager.  The mpu9150 is a complex device, and careful study of 
its datasheet and other documents is required to operate it.  This driver configures and 
operates the device according to the manufacturer's specifications and provides the data in a single, timestamped json 
structure.  In addition to the 9 raw data streams plus the temperature reading, the driver calculates the compass heading 
in degrees from the magnetometer readings.  Note that the driver does not tilt compensate the magnetometer readings 
because this robot typically operates in a level, 2 dimensional plane.  The tilt compensation calculation is on the todo 
list.  In order to retrieve accurate magnetometer readings, hard and soft iron compensation might be needed.  A test 
procedure is referenced in the code. The current particular robot required only hard iron adjustments, which were 
calculated last in 2019.  Note that InvenSense does provide sdk's for driver development
for more typical projects, but a python version was needed in this case.  The device contains additional proprietary 
features for further onboard processing of the data streams to offload system cpu resources, and those were not acquired.
* __battery__ - A simple driver to map voltage readings from a 12 Volt, 35 Amp-Hour Absorbed Glass Mat (AGM) battery 
into a state of charge table and report the ongoing status to interested processes, via the ops manager in this case.
* __av__ - A wrapper package to access audio visual capabilities of a Raspberry Pi 3 GPU.  This module is incomplete and
not in significant use currently.
* __mcu__ - For reference, the firmware source for the Parallax P8X32 MCU that is used to drive the range sensors is 
provided.  It's written in their proprietary spinn language.  Subsequently, C libraries were provided, but this driver
has not been re-written to leverage them yet.


### Applications
Applications are packages that utilize and/or extend the lbr system. 

* __navcam__ - A lightweight module to stream mjpeg video from the Raspberry Pi Camera module to navigation clients over 
http based on the work by Dave Jones.
* __state machine__ - A general purpose, finite state machine application to operate lbr.  Complex behaviors that can 
be modeled as finite state machines can be implemented using this application by providing a state transition table as 
a csv file with the prescribed set of columns.  The state machine follows the table sequentially outputting the 
specified commands to lbr and collecting the telemetry package back as inputs to evaluate for the next step. The state
table specifies the conditions required to go on to any number of next states.  The format of the conditions supports
user specified tolerances for each condition.  For example, if a desired range is 40cm, a user might specify that ranges
from 39 to 41cm are acceptable.  Tolerance management capabilities are key elements for operating complex systems. 
Further, the state machine does not require specific knowledge of a particular telemetry package.  It searches the package 
presented for the information required to match its target conditions regardless of the hierarchical structure.  As a 
robot implements additional sensors and data streams, the state machine can immediately utilize them based on new
state tables.  The initial example usage of the application is the automatic docking procedure.  When the robot is
in the room with the docking station, the autodock state table is executed to autonomously pilot the robot to the dock
and verify that it is successfully being charged.  With this abstracted, csv driven approach, the state machine could 
serve as a type of "muscle memory" for behaviours that are complex but not necessarily intelligent on their own.  In 
the future, coupling this capability with an AI that could design new behaviors and present them to the 
state machine would mean that the robot could immediately "learn" new the behaviors dynamically without code changes.
* __IoT__ - An adaptation and implementation of an Amazon AWS sample program to facilitate communications with an 
AWS IoT Core Thing Device Shadow.  Telemetry data is reported to the shadow, and desired states are retrieved from 
the shadow.  Commanding the motors from the desired state information has not yet been tested.  This application was
developed in mid 2020 and is an exciting new avenue for the project.  The project predated Amazon's IoT services, and
integrating with them would simplify any eventual production deployment and generally accelerate access to cloud based
capabilities.  In many ways, IoT exemplifies the distributed  architecture concepts that the project was founded upon.



### Environment and setup

## Hardware Overview


## Support and Collaboration

## Next Steps





 


