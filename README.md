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

statement at the bottom of the module.  The main entrypoint module, robot.py, is an exception to this rule.  The others
are not executed as mains at runtime.


### Executive
The executive package provides for configuring the robot at run time and commands the rest of the system.  A 
configuration module uses a sqllite database to store primary configuration information as metadata for significant 
capabilities of the robot.  The configuration process reads the database and arranges for indicated processes to be 
launched and connected together with various communications methods, typically python joinable queues.  Using this 
approach, the robot itself is 


### Communications
### Operations
### Drivers
### Applications


## Demonstration Videos


## Support and Collaboration

## Next Steps





 


