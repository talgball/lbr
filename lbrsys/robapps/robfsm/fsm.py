"""
fsm - finite state machine from
    https://www.python-course.eu/finite_state_machine.php
    Used with permission of the author and
    modified by Tal G. Ball
"""

__author__ = "Bernd Klein"
__copyright__ = "Copyright 2011 - 2020, Bernd Klein, Bodenseo; " + \
                "Design by Denise Mitchinson adapted for python-course.eu by Bernd Klein"
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


class InitializationError(Exception):
    pass


class StateMachine(object):
    def __init__(self):
        self.handlers = {}
        self.startState = None
        self.currentState = None
        self.prevState = None
        self.endStates = []

    def add_state(self, name, handler, end_state=0):
        self.handlers[name] = handler
        if end_state:
            self.endStates.append(name)

    def set_start(self, name):
        self.startState = name

    def run(self, cargo):
        try:
            handler = self.handlers[self.startState]
            self.currentState = self.startState
        except:
            raise InitializationError("must call .set_start() before .run()")
        if not self.endStates:
            raise InitializationError("at least one state must be an end_state")

        while True:
            (newState, cargo) = handler(cargo)
            if newState in self.endStates:
                print(("reached ", newState))
                break
            else:
                self.prevState = self.currentState
                self.currentState = newState
                handler = self.handlers[newState]