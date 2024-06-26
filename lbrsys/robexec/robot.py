#!/usr/bin/env python3
"""
robot.py - main module for the robot
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
import sys
import socket
import logging
import multiprocessing
import subprocess
import threading
import time
import pprint

# setting the path here so that robot.py can be 
#    executed interactively from here Shutdown

if __name__ == '__main__':
    sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    sys.path.insert(2, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from lbrsys.settings import robot_name, dbfile, robLogFile, BASE_DIR
try:
    from lbrsys.settings import LAUNCH_NAVCAM
except:
    LAUNCH_NAVCAM = False

from lbrsys import power, nav
from lbrsys import observeTurn, executeTurn, executeHeading, calibrateMagnetometer
from lbrsys import speech, dance, feedback, exec_report
from lbrsys import channelMap, command_map

# These imports support dynamically launching robot processes during setup
from lbrsys import robcom
import robcom.robhttpservice
import robcom.speechsrvcs
import robcom.robcamservice
import robops
import robops.opsmgr
import robops.mpops
import robops.rangeops
import robapps
import robapps.iot
import robapps.iot.robiot

from lbrsys.robexec import robconfig

# Convention for interpreting queue setup configuration data
QueueNotShared = -1


class Robot(object):
    def __init__(self, name=robot_name):
        logging.info('Configuring robot {0} at {1} .'.format(robot_name, time.asctime()))

        self.r = robconfig.Robconfig(dbfile, name)
        self.r.saveMessageDict(os.path.join(BASE_DIR, 'lbrsys', 'robcom', 'robmsgdict.py'))

        '''
        The following section is a bit dense.  Here's how it works:

        1. Create empty dictionaries to hold channels, JoinableQueues when local
              and python, and processes, which are Processes when local and python. 
              Create an empty thread list.
        2. Take note of firstPass to indicate that the channels have not
              yet been created.
        3. Iterate over the process list - which is actually process meta data
            3.1 Prepare to track the channels for the current process (channelListForProcess)
            3.2 Iterate over the channel list - i.e. channel meta data
            3.2.1 create the Queue if needed
            3.2.2 if the channel is for the current process, add it to the list
            3.2.3 if the channel is for receiving, create a monitor thread
            3.3 create a tuple of the channels (Queues) suitable for passing
                  to Process SEE BUG NOTE BELOW
            3.4 create the Process and add it to the dictionary of Processes

        todo: check more of the meta data options and add behavior.
        todo:     switch to kwargs Process.
                      Order of channels can't be guaranteed
        '''

        self.channels = {}
        self.processes = {}
        self.extProcesses = {}
        self.monitorThreads = []
        firstPass = True

        for p in self.r.processList:
            channelListForProcess = []
            channelDescriptionsForProcess = []
            for c in self.r.channelList:
                if firstPass:
                    if c['share_queue'] == QueueNotShared:
                        self.channels[c['id']] = multiprocessing.JoinableQueue()
                    else:
                        if c['share_queue'] in self.channels:
                            self.channels[c['id']] = self.channels[c['share_queue']]
                            #print "share_queue: %s" % (self.channels[c['share_queue']])

                    if c['direction'] == 'Receive' and \
                       c['target_process_id'] == 0: #target 0 means robot
                        mt = threading.Thread(
                            target=self.monitor,
                            args=(self.channels[c['id']],),
                            name='MonitorThread-{0}: {1}'.format(
                                c['id'],
                                c['description']
                            )
                        )
                        mt.daemon = True
                        self.monitorThreads.append(mt)
                        
                if c['source_process_id'] == p['process_id'] or \
                   c['target_process_id'] == p['process_id']:
                    channelListForProcess.append(self.channels[c['id']])
                    channelDescriptionsForProcess.append(c['description'])

            p['channels'] = tuple(channelListForProcess)
            # p['channel_descriptions'] = "\n\t".join(d for d in channelDescriptionsForProcess)
            p['channel_descriptions'] = "\n\t".join(channelDescriptionsForProcess)
            firstPass = False

            if p['protocol'] == 'pylocal':
                self.processes[p['process_id']] = multiprocessing.Process(
                    target=eval(p['target']),
                    name=p['name'],
                    args=p['channels']
                )
                print("\nCreated Process: {0} with channels \n\t{1} targeting {2}".format(
                    p['name'],
                    p['channel_descriptions'],
                    p['target'])
                )
                # temporary - remove this
                if p['name'] == 'Robot Operations':
                    p['channels'][0].put("Hello from robot!")

        # todo: merge this into one of the previous loops through the channels
        self.sendChannels = {}
        for c in self.r.channelList:
            if c['direction'] == 'Send' and c['source_process_id'] == 0:
                self.sendChannels[c['id']] = [self.channels[c['id']], c]
                #pprint.pprint(c)
        pass # useful breakpoint to examine robot configuration data in debugger

    def start(self):
        self.r.noteStarted()

        print()
        for p in self.processes:
            print("Starting", self.processes[p].name)
            self.processes[p].start()
            time.sleep(0.5)

        print()
        for mt in self.monitorThreads:
            print("Starting", mt.name)
            mt.start()

        time.sleep(1)

        # pre-launch navcam
        if LAUNCH_NAVCAM and 'navcam' in self.r.extcmds:
            self.execExt('navcam')

        self.mainEmbodied()

    def mainEmbodied(self):
        while True:
            print("")
            command = input('Robot> ')

            #skip blank lines
            if len(command) == 0:
                continue

            if command == 'Shutdown':
                self.execSend(command)
                break

            # commands starting with ! are sent directly to python interpreter
            if command and command[0] == '!':
                try:
                    print("command: %s" % (command[1:]))
                    exec(command[1:])
                except Exception as e:
                    print("Error executing '%s',%s, %s" %
                    (command[1:], sys.exc_info()[0], e))
                continue

            # check to see if the command is external
            if command and command[0] != '/' and command not in 'Ss' \
                and 'stop' not in command.lower():
                if command in self.r.extcmds:
                    try:
                        self.execExt(command)
                    except Exception as e:
                        print("Error executing external command: '%s',%s, %s" %
                              (command, sys.exc_info()[0], e))
                else:
                    print("Unknown command: {}".format(command))
                continue

            preparedCommand = self.prepare(command)
            if preparedCommand and self.acceptedCommand(preparedCommand):
                self.execSend(preparedCommand)
                        
        self.end()

    def execExt(self, command):
        logging.info("Robot Exec: Processing external command - {}".format(str(command)))
        cmd = self.r.extcmds[command]
        if cmd['blocking']:
            run = subprocess.run
        else:
            run = subprocess.Popen

        target = cmd['target']
        if target[0] != '/':
            target = os.path.join(BASE_DIR, 'lbrsys', target)

        cmd_args = [target]
        if cmd['args'] is not None:
            ca = cmd['args'].split(' ')
            cmd_args = cmd_args + ca

        result = run(cmd_args, stdin=cmd['stdin'], stdout=cmd['stdout'], stderr=cmd['stderr'])
        logging.debug("\tResults: {}".format(str(result)))

        if run is subprocess.Popen:
            self.extProcesses[command] = result

        return result

    def execSend(self, preparedCommand):
        logging.debug("Robot Exec: Processing - {}".format(str(preparedCommand)))
        #
        # if type(preparedCommand) is power:
        #     print(f"Robot Exec Processing {str(preparedCommand)}")

        for c in list(self.sendChannels.values()):
            if preparedCommand != 'Shutdown':
                chanType = c[1]['type']
                if type(preparedCommand) in channelMap[chanType]:
                    # logging.debug("Robot Exec: Sending - {}".format(str(c)))
                    c[0].put(preparedCommand)
                    # print(f"put {preparedCommand} in {str(c[0])}, {c[1]['description']}")

    def monitor(self,monitorQ):
        while True:
            msg = monitorQ.get()
            # print "msg: %s" % (str(msg),)
            if msg:
                # Executive Report here is a response to a request for information,
                #   as opposed to a command to be further dispatched by default.
                if type(msg) is exec_report:
                    pprint.pp(f"Executive Report on {msg.name}: {str(msg.info)}", indent=4)
                    monitorQ.task_done()
                    continue

                #preparedCommand = self.prepare(str(msg))
                preparedCommand = self.prepare(msg)
                logging.debug("Robot-{0}:\n\t{1}".format(
                    threading.current_thread().name,
                    str(msg))
                )
                if preparedCommand and self.acceptedCommand(preparedCommand):
                    self.execSend(preparedCommand)   
            
            monitorQ.task_done()
            
            
    def acceptedCommand(self, command):
        return True


    def prepare(self, cmd):
        preparedCommand = cmd

        if cmd == 'S' or cmd == 's':
            preparedCommand = power(0,0)
            return preparedCommand
        
        if cmd == 'Shutdown':
            return preparedCommand
        
        logging.debug("type of cmd '%s' is: %s" % (str(cmd),type(cmd)))

        if type(cmd) is str and cmd[0] != '/':
            cmdWords = cmd.split(' ')
            if len(cmdWords) == 1 and cmdWords[0].lower() == 'stop':
                preparedCommand = power(0, 0)
                return preparedCommand

            if len(cmdWords) == 2 and cmdWords[0].lower() == 'stop':
                cw1 = cmdWords[1]
                if cw1 in self.extProcesses.keys():
                    p = self.extProcesses[cw1]
                    p.terminate()
                    termResult = p.wait(2)
                    self.extProcesses.pop(cw1)
                    print("\tStopped {}, result {}".format(cw1, termResult))
                    logging.debug("Stopped {}, result {}".format(cw1, termResult))
                else:
                    print("\tUnknown stop {}".format(cw1))
                    logging.debug("Unknown stop {}".format(cw1))
                return None

        if type(cmd) is str and len(cmd) > 3:
            preparedCommand = None
            try:
                rawfields = cmd.split('/')
                fields = [f for f in rawfields if f != '']
                command = fields[0]
                if command in command_map:
                    params = []
                    mapentry = command_map[command]
                    cmdentry = mapentry[len(fields)]
                    cmdtype = list(cmdentry.keys())[0]
                    i = 1

                    # handle nav as a special case for now since it nests power
                    #   suggest generalizing to avoid adding further special cases
                    if cmdtype is nav:
                        params.append(power(float(fields[i]), float(fields[i+1])))
                        i += 2

                    for t in cmdentry[cmdtype]:
                        if t is power:
                            continue
                        params.append(t(fields[i]))
                        i += 1

                    preparedCommand = cmdtype(*params)
                else:
                    print(f"Unknown command: {command}")

                # print(f"Test Prepared command: {str(preparedCommand)}")

            except ValueError as e:
                print(f"Value error preparing command: {str(cmd)}\n{str(e)}")

            except KeyError as e:
                print(f"Key error preparing command: {str(cmd)}\n{str(e)} - invalid parameter count")

            except TypeError as e:
                print(f"Type error preparing command: {str(cmd)}\n{str(e)}")

            except Exception as e:
                print(f"Unexpected error preparing command: {str(cmd)}\n{str(e)}")

        else:
            preparedCommand = feedback(cmd)

        return preparedCommand
            

    def end(self):
        #logging.debug('Shutting down..')
        print('Shutting down..')
        sys.stderr.flush()
        
        for c in self.r.channelList:
            if c['protocol'] == 'JoinableQueue' and c['direction'] == 'Send':
                self.channels[c['id']].put('Shutdown')
                print("Shutdown to channel:",str(c['description']),str(c['id']))
                
        # give the shutdown messages time to execute
        time.sleep(1)

        print("Terminating external processes")
        for p in self.extProcesses.values():
            p.terminate()
            p.wait(0.4)

        '''
        # todo: debug why the queues (especially #2) hangs
        # hint - check on the order in which the Shutdowns are sent relative
        #  to the channel map
        joinedQueues = []
        for c,cv in self.channels.iteritems():
            if not cv in joinedQueues:
                #logging.debug("Joining Channel %s, CommandQ %s" % (c,cv))
                print("Joining Channel %s, CommandQ %s" % (c,cv))
                while not cv.empty():
                    t = cv.get_nowait()
                    print "\tremoved item: ",t
                    cv.task_done()
                cv.join()
                joinedQueues.append(cv)
        #logging.debug('Joined Queues')
        print 'Joined Queues'
        '''
        
        '''        
        print "Starting Process Joins.."
        for p,pv in self.processes.iteritems():
            pv.join()
        #logging.debug('Joined Processes')
        print 'Joined Processes'
        '''

        # For now, terminate the processes.
        # Until hanging on join is resolved.
        print("Terminating robot processes")
        for p, pv in self.processes.items():
            pv.terminate()
            time.sleep(0.2)

        print('Terminated processes')

        self.r.noteShutdown()
        self.r.con.close()
        
        logging.info('Done at %s.', time.asctime())
        print('Done.')


if __name__ == '__main__':
    # arrange for Process spawning instead of forking
    multiprocessing.set_start_method('spawn')

    print("Configuring log file: %s" % robLogFile)
    logging.basicConfig(
        # level=logging.DEBUG,
        level=logging.INFO,
        filename=robLogFile,
        format='[%(levelname)s] (%(threadName)-10s) %(message)s'
    )

    # todo - temporary fix:
    # Since lbr2a is a raspberry pi 3 based design,
    # this command ensures that the hdmi audio pipe remains open.  Otherwise,
    # the initial portions of sound are cut off. Needs to at least be refactored to
    # rpiav.py or eliminated.
    # Note also that the hdmi display status must be 1 in order to get sound.
    if socket.gethostname() == 'lbr2a':
        forceAudio = subprocess.check_output(["vcgencmd", "force_audio", "hdmi", "1"])

    r = Robot()
    r.start()
