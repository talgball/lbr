#!/usr/bin/python3
"""
 robfsm.py - Provide a configurable state machine for executing
    robot behaviours, initailly focused on navigation tasks.

    robfsm operates as an "application" in the robot architecture
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2009-2020 Tal G. Ball"
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
import json
import time
import pprint
from threading import Thread

sys.path.append('../..')
from robcom import robhttp

import csv

from .fsm import StateMachine
from . import telemetry


class RobStateMachine(StateMachine):
    def __init__(self, stateFileName='./autodock.states', getTelemetry=None,
                 doOutputs=None, clock=0.5):
        super(RobStateMachine, self).__init__()
        assert (getTelemetry is not None), "getTelemetry function required"
        assert (doOutputs is not None), "doOutputs function required"
        self.getTelemetry = getTelemetry
        self.doOutputs = doOutputs
        self.clock = clock
        self.stateFileName = stateFileName
        self.stateTransMap = {}
        self.transitionsCompleted = 0
        self.maxTransitions = 60

        # exclusions are columns that are not inputs or outputs
        self.exclusions = ['Type', "Current State", "Next State"]

        self.stateLineCount = self.load()


    def load(self):
        line_count = 0
        with open(self.stateFileName, mode='r') as stateFile:

            csv_reader = csv.DictReader(stateFile, delimiter=',', dialect='excel')
            line_count = 0

            for row in csv_reader:
                stateName = row['Current State']

                if row['Type'] == "#":
                    continue

                if row['Type'] == "end":
                    end_state = 1
                else:
                    end_state = 0

                self.add_state(row['Current State'], self.transition, end_state)

                if row['Type'] == "start":
                    if self.startState is None:
                        self.set_start(stateName)
                    else:
                        raise Exception("Error setting start state to %s. %s is already start state" %
                                        (stateName, self.startState))

                if not stateName in self.stateTransMap:
                    self.stateTransMap[stateName] = []

                self.stateTransMap[stateName].append({
                    'Current State': stateName,
                    'Next State': row['Next State'],
                    'Inputs': self.getInputs(row),
                    'Outputs': self.getOutputs(row),
                })

                line_count += 1

        return line_count


    def savej(self, fileName='default'):
        if fileName == 'default':
            fileName = self.stateFileName.rpartition('.')[0] + '.json'
        with open(fileName, mode='w') as jf:
            json.dump(self.stateTransMap, jf)
        return


    def getInputs(self, d):
        inputs = {}
        for i in d:
            ikey = i.split(':')
            if len(ikey) == 1 and ikey[0] not in self.exclusions:
                if d[i].strip() != '':
                    inputs[ikey[0]] = d[i]
        return inputs


    def getOutputs(self, d):
        outputs = {}
        for i in d:
            ikey = i.split(':')
            if len(ikey) == 2 and ikey[0] == 'O':
                if d[i].strip() != '':
                    try:
                        outputs[ikey[1]] = float(d[i])
                    except ValueError:
                        outputs[ikey[1]] = d[i]
        return outputs


    def transition(self, telemetrySample):
        newState = self.currentState
        match = False

        self.transitionsCompleted += 1
        if self.transitionsCompleted <= self.maxTransitions:

            for row in self.stateTransMap[self.currentState]:
                match, report = telemetry.compare(row['Inputs'],
                                                  telemetrySample)
                if match:
                    self.doOutputs(row['Outputs'])
                    time.sleep(2*self.clock)

                    while True:
                        t = self.getTelemetry()
                        leftAmps = t['Amps Left']
                        rightAmps = t['Amps Right']

                        if leftAmps == 0 and rightAmps == 0:
                            break
                        else:
                            time.sleep(self.clock)

                    newState = row['Next State']

                    print(("Telemetry comparison - matched in state [%s]:" %
                          self.currentState))
                    print(("\tReport: %s" % str(report)))
                    print(("\tRequired: %s" % str(row['Inputs'])))
                    print(("\tSample: %s" % str(telemetrySample)))
                    print(("New State is [%s]: " % newState))
                    break
                else:
                    print(("Telemetry comparison - no match in state [%s]:" %
                          self.currentState))
                    print(("\tReport: %s" % str(report)))
                    print(("\tRequired: %s" % str(row['Inputs'])))
                    print(("\tSample: %s" % str(telemetrySample)))
                    time.sleep(self.clock)
                    # telemetrySample = self.getTelemetry()
                    # keeping same sample for each row
                    # then try again with new sample

            if not match:
                print(("Failed to match inputs for state %s" % self.currentState))
                newState = self.currentState
        else:
            print("Max State Transitions Exceeded.")
            newState = self.endStates[1] # assumes second end state is failure

        return newState, self.getTelemetry()


class FSMExec(robhttp.Client):
    """
    FSMExec class to provide an http interface for interacting
        between the state machine and the robot.
    """
    def __init__(self, robot=None, stateFileName='autodock.states'):
        super(FSMExec, self).__init__(robot)
        self.stateFileName = stateFileName
        self.stop = False
        # self.sampleInterval = 0.5
        self.sampleInterval = 1.5
        self.machine = RobStateMachine(getTelemetry=self.getTelemetry,
                                       stateFileName=self.stateFileName,
                                       doOutputs=self.doOutputs)
        self.machine.savej()

        print(("state machine lines: %d" % self.machine.stateLineCount))


    def subscriber(self, payload=None):
        if payload == 'Shutdown':
            if self.posts != 0:
                print("Posts %d, Avg Post %.3f" %\
                      (self.posts, self.totalPostTime/self.posts), file=sys.stderr)
            print("Shutting down.", file=sys.stderr)
            self.postQ.put('Shutdown')
            self.postQ.join()
            return

        payloadJ = json.dumps(payload)
        # print "payload: %s, payloadJ: %s" % (payload,payloadJ)
        self.postQ.put(payloadJ)
        return


    def getTelemetry(self):
        d = {}
        t = self.get()[0]
        d['heading'] = t['MPU']['heading']
        d['Forward'] = t['Ranges']['Forward']
        d['Rear'] = t['Ranges']['Back']
        d['Left'] = t['Ranges']['Left']
        d['Right'] = t['Ranges']['Right']
        d['Amps Left'] = t['amperages']['leftMotor']
        d['Amps Right'] = t['amperages']['rightMotor']
        d['Volts'] = t['Bat']['voltage']

        if 'dockSignal' in t and 'left' in t['dockSignal']:
            d['Dock Left'] = t['dockSignal']['left']

        if 'dockSignal' in t and 'right' in t['dockSignal']:
            d['Dock Right'] = t['dockSignal']['right']

        return d


    def doOutputs(self, outputs):
        if 'duration' in outputs and outputs['duration'] < 0:
            print(("Pausing for %.3f seconds before submitting %s" %
                  (abs(outputs['duration']), str(outputs))))
            time.sleep(abs(outputs['duration']))

        # submit the outputs if there are any
        for o in outputs:
            if outputs[o] != '':
                print(("\nPosting outputs: %s" % str(outputs)))
                self.subscriber(outputs)
                break

        if 'duration' in outputs and outputs['duration'] > 0:
            print(("Pausing for %.3f seconds after submitting %s" %
                  (outputs['duration'], str(outputs))))
            time.sleep(outputs['duration'])

        return

    def start(self):
        telemetry = self.getTelemetry()
        self.machine.run(telemetry)
        return


def genericSubscriber(payload):
    print(str(payload))


def main(robot=None, user=None, token=None, stateFileName='autodock.states'):
    """
    main is provided to streamline using this module from
        multiprocessing.Process
        # todo generalize search directory for state files
    """
    print(("Initializing State Machine Execution for robot %s with %s" %
          (robot, stateFileName)))

    fsm_client = FSMExec(robot, stateFileName)
    fsm_client.setAuthToken(user, token)
    # fsm_client.publisher.addSubscriber(genericSubscriber)
    fsm_client.start()
    fsm_client.subscriber('Shutdown')
    fsm_client.stop = True


if __name__ == '__main__':
    robot = None
    user = None
    apitoken = None

    try:
        robot = os.environ['ROBOT']
        user = os.environ['ROBOT_USER']
        apitoken = os.environ['ROBOT_APITOKEN']
    except Exception as e:
        print(("Error setting up environment:\n%s" %
              str(e)))

    stateFileName = 'autodock.states'

    if len(sys.argv) == 3:
        robot = sys.argv[1]
        stateFileName = sys.argv[2]
    elif not robot:
        print('Usage: robfsm.py <robotname> <statefile>')
        sys.exit()

    main(robot, user, apitoken, stateFileName)
