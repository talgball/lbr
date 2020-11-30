# lbr - The "little brother robot" Project
Distributed Robot Operating System Architecture and Design Experiments

![System and Architecture](https://github.com/talgball/lbr/blob/master/docs/images/2020lbrsystem.png)

## Introduction
Telepresence robotics is a young and promising space that has potential for bringing people together in more engaging and
flexible ways than current video conferencing approaches.  If instead of just appearing passively on a screen, 
remote people could engage more actively in the space with local participants, the quality of communicating and 
connecting with each other would be radically enhanced and begin to feel more natural and rewarding.  

According to Verified Market Research, the global telepresence robot market was $181.6M USD in 2019 and is projected to 
reach $789.1M by 2027, representing a 20.2% compound annual growth rate.  The telepresence products currently in the 
market are primarily aimed at work environments, with healthcare being a 
leading market driver.  As the technology continues to develop, better and more cost-effective robots will become
increasingly available for in home use.  Some of the initial in-home use cases might well be extensions of the current 
office use cases.  For example, being more deeply and continuously connected with family and community 
might help people maintain their independence during periods of their lives that would have traditionally required 
specialized facilities.  Imagine a robot that not only enables telepresence but is also equipped with sophisticated 
sensors and other devices to help people monitor their health issues and connect proactively to support services. Since 
a telepresence robot could have many remote users, doctors could make virtual house calls and provide a level of 
service well beyond the telehealth capabilities that have advanced over the past year.  Then the same device could be 
used by friends and family to stay connected after the doctor's visit.
 
This project started in 2009 and has been progressing as a private research endeavor on a part time 
basis by one developer working a few hours at a time over the past 11 years and counting.  The goals of the project are
as follows:
* Learning and developing concepts in robotics and telepresence.
* Exploring the possibilities of integrating existing technologies and services to produce and enhance robotic use cases.
* Discovering and developing opportunities for in home telepresence robots.  

During the life of the project, the capabilities of cloud platforms, advances in robotics like the further development 
and adoption robotic operating systems like ROS, the rise of digital assistants like Alexa and Siri, and other advances 
have demonstrated that distributed and extensible sets of services can be integrated to produce useful capabilities
that might not have been envisioned when any one of the technologies was created.  Adding physical robots as part of 
delivering those capabilities is a logical next step, and it's rewarding to work along side these broad and rapidly
accelerating developments.

While 2020 has been a year of challenge and isolation, people have found expanded ways to connect with each other, 
ranging from long hours of video conferencing to signing from their balconies around the world.  The growing need for
connecting, working, collaborating, understanding and just being with each other will continue long after this pandemic
has ended.  The decision to open source the project now is in the hope that it might be of some use or inspiration to others 
who seek to bring people closer together in the years ahead using the amazing technologies of our time and perhaps to 
encourage groups of us to work together in that endeavor.

This repository houses a relatively small experimental code base for exploring robotics software architectures.  
The concept of "robot" in the architecture is a distributed set of services and capabilities focused on satisfying one 
or more use cases and typically delivered by one or more robotic hardware devices.  Telepresence, especially for 
residential use cases, has been an initial target in mind to help guide and focus the research.  Many of the concepts 
explored in the code are not new, and the combinations of them has been the primary area of focus.

To support development and testing of the software and architecture, a single robotics development hardware platform was
constructed.  While the code base here is configured for the specifics of that particular robot, the architecture and 
capabilities of the software would support a wide range of alternative hardware.  The software could be used as a whole
system, or its packages and modules could be used individually as needed to help with other projects.  As the code is
currently in an experimental state, it has not yet been packaged into a standard distribution.  Instead, users
can clone or download this repository or any of its components, subject to the included Apache 2 license agreement and
notices.

## Demonstration Videos
Here are couple of brief and definitely unpolished demos:

* [__Navigation__](https://youtu.be/vbRg4YTh7xg)
* [__Automatic Docking__](https://youtu.be/1rOheZw6kcA) 


## Software Overview
The embedded portion of the lbr software architecture is organized into 4 packages and an extensible collection of 
additional packages called, "applications".  There is also an external web client application and, at this writing, 
a small amount of supporting cloud based services.  Only the embedded portion is being released at this time.  

### Executive
The executive package provides for configuring the robot at run time and commands the rest of the system.  It also 
provides for startup and shutdown operations.

A configuration module uses a sqllite database to store primary configuration information as metadata to specify 
capabilities of the robot.  The configuration process reads the database and arranges for indicated processes to be 
launched and connected with various communications methods, typically python joinable queues, as specified in
the metadata.  The usual pattern is to create two joinable queues between connected processes.  One of them is used 
to send command messages, and the other one is used to broadcast response information such as telemetry back to the 
commanding process.  Using this approach, the robot itself is "softly modeled" and can be significantly modified and 
extended, often without changing the existing code, and could even "evolve" its capabilities at runtime. 

After launching with the __robot__ command, the system provides a command console in a terminal window.  Three types of 
commands are supported at the console: built-in, external and python.  Built-in commands are as follows:
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
* __/d/song__ - Play the indicated song and dance to it.  (Command no longer supported in current version.)
* __Shutdown__ - Shutdown the lbr software system

Note that when operating the robot from a client, such as the web application, these commands are automatically derived 
from actions in the user interface and supplied to the executive module for processing.  The command console
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
* __authorization__ - A module to manage authorization tokens and authenticate users against them.  For example, tokens 
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
milliseconds.  This approach reduces cpu utilization and realistically aligns with the operating paradigm of the current
robot, i.e. a wheeled machine operating in a residential environment.  A much shorter loop time would be needed for a 
flying robot, for example.  The ops manager keeps and logs statistics on operation timings to enable further tuning of 
the system.  Excessively long loops, for example, typically indicate an error condition or bug has been encountered.
    It is noted that the ops manager could be redesigned based on the asyncio package to further increase its efficiency.
    The entire current system except for video conferencing utilizes about 15% of the CPU resources of a Raspberry Pi 3,
    and while further improvements are desirable, this redesign hasn't reached a high enough priority yet.

* __movement__ - The movement modules, notably __movepa.py__, translates the power and angle movement directives into 
precise parameters to communicate to the motor controller.  The translation algorithm can be adjusted based on the 
configuration of the robot motors and steering mechanisms.  The current robot employs tank like steering, as it has 
left and right motors that operate independently.
* __motion processing__ - Telemetry information is gathered from the 9 axis motion processing system and combined 
with other information for use in adjusting operations and to communicate across the system.
* __range__ - Operates an array of 4 ultrasonic range sensors and reports the distances forward, back, left and right
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
uses the serial interface to communicate semantically appropriate information between the device and the operations manager
or other interested processes.  These modules might be useful on a standalone basis for people who happen to have these
particular or similar devices and are in need of python drivers.

* __motors__ - A driver for the __Roboteq SDC2130__ 2X20Amp motor controller is provided.  This driver communicates over USB 
using Roboteq's proprietary protocol to manage motor operations and report on electrical conditions, including battery 
voltage and the amount of current flowing through the motors.  The driver also implements a master feature toggle to
enable or disable motor operations.  When disabled, the driver does all of it's normal operations except for actually 
running the motors.  This toggle is useful during development and debugging, especially when there are potential safety
concerns when a particular operation is being developed.
* __ultrasonic rangers__ - A driver to communicate over USB with a __Parallax Propeller P8X32 MCU__ that has been 
programmed to operate an array of 4 __MaxBotix MB1220 Ultrasonic Range Sensors__.  A package of readings is gathered on 
request and provided to the range operator running at the request of the operations manager.  The sensors produce a set of 
readings 10 times per second, and the range operator is set to request the data at the same rate.  Provisions were 
made in the software to support a 5th sensor to check for bottom distance, in case for example, the robot is approaching
a staircase, but that sensor is not installed in the current robot.  
* __9 axis mpu__ A driver to communicate over the i2c bus with an __InvenSense MPU9150 9 Axis Motion Processing Unit__. 
The unit contains a 3 axis gyroscope, accelerometer and magnetometer.  Readings are gathered at the request of motion 
processing operations in collaboration with the operations manager.  This driver configures and 
operates the device according to the manufacturer's specifications and provides the data in a single, timestamped json 
structure.  In addition to the 9 raw data streams plus the temperature reading, the driver calculates the compass heading 
in degrees from the magnetometer readings.  Note that the driver does not tilt compensate the magnetometer readings 
because this initial robot typically operates in a level, 2 dimensional plane.  The tilt compensation calculation is on the todo 
list.  In order to retrieve accurate magnetometer readings, hard and soft iron compensation might be needed.  A test 
procedure is referenced in the code. The current robot required only hard iron adjustments, which were 
calculated last in 2019.  Note that InvenSense does provide sdk's for driver development
for more typical projects, but a lightweight python version was desired in this case.  The device contains additional proprietary 
features for further onboard processing of the data streams to offload system cpu resources.  Utilizing those capabilities 
requires a commercial relationship with InvenSense, and those were not implemented in this version.
* __battery__ - A simple driver to map voltage readings from a 12 Volt, 35 Amp-Hour Absorbed Glass Mat (AGM) battery 
into a state of charge table and report the ongoing status to interested processes.
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
a csv or json file with the prescribed set of columns.  The state machine follows the table sequentially outputting the 
specified commands to lbr and collecting the telemetry package back as inputs to evaluate for the next step. The state
table specifies the conditions required to go on to any number of next states.  The state machine application 
communicates via the REST api interface with the robot.  While the current configuration runs the state machine as an
embedded component, it could operate from any connected location.

    The state table format supports
user specified tolerances for each condition.  For example, if a desired range is 40cm, a user might specify that ranges
from 39 to 41cm are acceptable.  Tolerance management capabilities are key elements for operating complex systems. 
Further, the state machine does not require specific knowledge of a particular telemetry package.  It searches the package 
presented for the information required to match its target conditions regardless of the hierarchical structure.  As a 
robot implements additional sensors and data streams, the state machine can immediately utilize them based on new
state tables.  

    The initial example usage of the application is the automatic docking procedure.  When the robot is
in the room with the docking station, the autodock state table is executed to autonomously pilot the robot to the dock
and verify that it is successfully being charged.  With this abstracted approach, the state machine could 
serve as a type of "muscle memory" for behaviours that are complex but not necessarily intelligent on their own.  In 
the future, coupling this capability with an AI that could design new behaviors and present them to the 
state machine would mean that the robot could immediately "learn" the new behaviors dynamically without code changes.

* __IoT__ - An adaptation and implementation of an Amazon AWS IoT sample program to facilitate communications with an 
AWS IoT Core Thing Device Shadow.  Telemetry data is reported to the shadow, and desired states are retrieved from 
the shadow.  Commanding the motors from the desired state information has not yet been tested, and note that the 
current configuration is reporting shadow updates every 5 seconds.  Operating the motors would require shorter cycles.

    This application was developed in 2020 and is an exciting new avenue for the project.  The project predated 
Amazon's IoT services, and integrating with them would simplify any eventual production deployment and generally 
accelerate access to cloud based capabilities.  For example, creating Alexa skills to operate the robot would be a 
small incremental step from here.  In many ways, IoT exemplifies the distributed  architectural concepts that the 
project was founded upon.


### Environment and Setup
The system is configured using a combination of environment variables passed from the operation system and information
in the *settings.py* module.  Environment variables are used to pass private information such as credentials into the 
system without storing the information in any of the code modules.

Supported environment variables are as follows:
* ROBOT_URL - URL of the robot's http service
* ROBOT_CRED - Path to a directory containing credentials files
* ROBOT_CERT - Path to the robot's https certificate
* ROBOT_KEY  - Path to the robot's private key for the https certificate
* ROBOT_CA - Path to the robot's signing authority certificate 
* ROBOT_USER - String containing the username associated with the APITOKEN to be authenticated
* ROBOT_APITOKEN - String containing the token for authenticating the current robot user to enable API access
* ROBOT_AWS_CERT - Path to the certificate for accessing AWS IoT as a Thing
* ROBOT_AWS_KEY - Path to the private key for use in communicating with AWS IoT
* ROBOT_AWS_ENDPOINT - String containing the URL of the AWS IoT Thing 
* ROBOT_AWS_ROOT_CA - Path to the AWS root certificate
* ROBOT_DJ_USER - String containing the robot user name for registering with the bfrobotics web services
* ROBOT_DJ_APITOKEN - String containing API access token issued by the bfrobotics web services
* ROBOT_DOCK - String indicating which lirc contains the infrared docking messages

A planned but not yet released feature for *settings.py* is to enable "fake devices" so that the system could be 
exercised without requiring the robot hardware to be present.  This document will be updated when the feature is 
available.

### Code Style Notes
Almost all of the code is written in python and currently requires python 3.5 or above.  The code style has evolved a
bit over the years, and your kind patience is requested.  When the project was started, my most recent commercial 
project that included personal coding was written in jython.  As we were using many Java libraries, we adopted 
CamelCase.  Of course, the python community prefers snake_case, and I have come ultimately come back home to that, 
although the previous packages have not been updated.  Also, users might notice that some packages and modules could 
do with significant refactoring, which often happens with long lived code bases.  They are on "the list."  Finally, 
some concepts have several different implementations across the code base.  That usually meant that each of them 
were interesting topics to explore and compare with each other over the course of the project.  Obviously, those 
would normally be optimized during commercialization.   

Unit testing for each module is behind the
 
    if __name__ == __main__:

statement near the bottom of the module.  The main entry point module, robot.py, is an exception to this rule.  
The others are not executed as mains at runtime except during unit testing.


## Hardware Overview
The lbr development platform hardware was designed for flexibility and to support an ongoing set of experiments, including
hardware upgrades over the life of the robot.  It was not designed for productization directly.  However, the telepresence
use case requires the robot to have a sufficient physical height to make video conferencing with remote users comfortable.
The approximate overall dimensions of the robot are 56" X 17" X 12", and the system weighs about 35 pounds, with the battery
being the heaviest component.

* __Chassis__ - The frame is constructed from T6 aircraft aluminum, 1/8" thick and using a combination of 1" angle iron
pieces and 1/8" sheets.  Internally, movable 1/4" acrylic shelves hold the electronics.  A removable riser is
attached to the chassis to hold the monitor and video conferencing camera.  

* __Motors and Drive Train__ - Designing the drive train for this development platform was approached as an exercise in
practicality using readily available, off the shelf parts.  Two school bus windshield wiper gear motors from 
American Electric Motors are utilized.  These motors have electromechanical specifications similar to electric wheelchair 
motors but are significantly less expensive.  They have continued to perform well over the life of the platform.  The 
motors are mounted to the chassis with custom aluminum mounts.  6" solid rubber garden cart wheels are attached to the 
motors.  Their nylon hubs are augmented and reinforced with steel hub assemblies backed with aluminum plates.  The wheel 
bearing surfaces are interfaced to the drive shafts using stainless steel piping to form a precise and durable fit.  
In early drive train testing, the chassis comfortably transported a 90 pound kit around the pool deck.  (Don't try this at home.)

    My most significant regret in the original design is not including rotary encoders.  That additional data would 
    have made a lot of tasks with the software much more approachable, including autonomous mapping. 
  
* __Electrical__ -  Automotive components are used in the electrical power section due to their easy availability and 
overall reliability and since the system employs a 12V electrical system.  The battery is a U1, 12V, 35 Amp-Hour AGM, which 
provides a duty cycle of about 8 hours in the current configuration.  Circuits are branched and fused using an automotive 
fuse block.  A 100AMP safety switch disconnects the battery from the system.  Note that a bypass wire protected 
by a power diode should be added around the fuses and disconnect switch such that the motors always have a guaranteed 
return path to the battery.  Otherwise, transients could damage the motor controller during a failure event.  
The battery is charged by an external charging system mounted in the docking station.

* __Computer__ - The original implementation was a windows based machine on a Mini ATX motherboard.  That 
configuration in 2009 was a bit power hungry, but it worked well, and Skype was used for video conferencing (especially
pre-acquisition).  Through a series of further experiments, the current main computer is a Raspberry Pi 3 4GB, which
comfortably runs the lbr system except for the video conferencing.  Currently, zoom conferencing runs on an additional
windows stick.  It is likely that a future revision will settle on an Intel based Linux system that supports zoom, unless
a custom video system is implemented.  The debate is underway.

* __Monitor__ - The monitor is an Eyoyo 12 Inch HD unit with built-in speakers, typically used in surveillance systems.  
The key characteristics of the monitor are that it operates on 12V and is HD, 1920x1080, and that it automatically turns on
when its power is toggled.

* __Cameras__ - The navigation camera is a Raspberry Pi V2 camera module with an 8MP Sony image sensor.  
The video conferencing camera is Logitech C920 USB webcam.  Various camera configurations have been explored over time, 
and it seems that the needs for navigation and video conferencing are sufficiently different that it is easier to have 
two cameras in the design.  

* __Other Electronics__ - Most of the remaining electronic devices were described in the __Drivers__ section.  The infrared 
receiver and transmitter are custom circuits that interface to the Raspberry PI's GPIOs and are driven by the kernel
module supplied with Raspberry PI OS.  In addition, two custom switched 12V outlets are controlled by GPIOs. One is
used for powering the monitor, and the other one is used for the windows stick.  The Parallax P8X32 MCU has 
6 additional cores available, as 2 of the 8 are currently in use in driving the ultrasonic array.  The MCU has at least
20 unused GPIOs for future use, in addition to the unused Raspberry PI GPIOs, noting that the i2c bus is driven from the
Raspberry Pi instead of the MCU.  The MCU is interfaced to the Raspberry PI over USB.

* __Docking Station__ - The docking station transmits infrared signals that are used by the robot during docking, and it 
also receives signals.  The transceiver circuits are custom, and they are driven by a Parallax P8X32 MCU.  The communications
protocol is an implementation of the Sony IR remote standard.  The C source 
for the docking firmware is not included in this repository but is available on request. The docking
station embeds a NOCO Genius AGM charging system.

Having read this far, you might be curious about why the project is called, "little brother robot."  When the project 
started, my then 11 year old son came into the workshop and asked if I was building him a little brother.  I thought that
was a cool way to think about it, and the name stuck.   


## Support and Collaboration
As this or other robotics projects continue to unfold, opportunities to collaborate are welcome.  While this software is 
provided on an as-is basis, I'd be happy to answer questions or help resolve issues, subject to my availability.

My email address is __tal@ballfamily.org__





 


