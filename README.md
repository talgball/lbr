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

A configuration module uses a sqllite database to store primary configuration information as metadata for significant 
capabilities of the robot.  The configuration process reads the database and arranges for indicated processes to be 
launched and connected together with various communications methods, typically python joinable queues, as specified in
the metadata.  Using this approach, the robot itself is "softly modeled" and can be significantly modified and extended
often without changing the existing code. 

After launching with the robot command, the system provides a command console in a terminal window.  Three types of 
commands are supported at the console: builtin, external and python.  Builtin commands are as follows:
* __/r/power/angle__ - Run the motors at a power level between 0 and 1 at a steering angle between 0 and 360 degrees 
from the robot's perspective, i.e. 0 degrees always mean straight ahead, and 180 is straight back.
* __/r/power/angle/range/sensor/interval__ - Run the motors at the given power level and angle subject to constraints:
  * *range* - Distance measured by the indicated sensor must be greater than the value specified, between 0 and 769 cm.
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
* __telemetry__ - Prototype module for generalizing telemetry processing.  Not currently in use.  A more advanced telemetry 
processing capability is implemented in the state machine package.
* __zoom manager__ - zoom is currently used for the video conferencing function in telepresence and has been typically 
managed manually.  This module will wrap the management of zoom communications and integrate and automate the management
process with the robot system.  This module is under development and not currently released.


### Operations
### Drivers
### Applications

### Environment and setup

## Hardware Overview


## Support and Collaboration

## Next Steps





 


