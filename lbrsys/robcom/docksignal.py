#!/usr/bin/python3
""""
 docksignal.py - arrange to obtain docking signals from the active dock
    and post them to httpservice
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


"""
For Reference:
A few notes from the lirc documentation:
        $ python
        >>> import lirc
        >>> sockid = lirc.init("myprogram")
        >>> lirc.nextcode()  # press 1 on remote after this
        ['one', 'horse']
        >>> lirc.deinit()

    Load custom configurations with:

        >>> sockid = lirc.init("myprogram", "mylircrc")
        >>> lirc.load_config_file("another-config-file") # subsequent configs

    Set whether `nextcode` blocks or not with:

        >>> sockid = lirc.init("myprogram", blocking=False)
        >>> lirc.set_blocking(True, sockid)  # or this
"""

import os
import sys
import json
import time
import lirc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from robcom import robhttp2


class DockSignal(robhttp2.Client):
    def __init__(self, robot=None, robot_url=None, user=None, token=None):
        super(DockSignal, self).__init__(robot, robot_url, user, token)
        self.sockid = lirc.init(robot, blocking=False)
        self.sampleInterval = 0.1
        self.timeToLive = 1.5
        self.stop = False
        self.current = {"dockSignal": {"left": 0, "right": 0, "time": 0}}
        self.setAuthToken(user, apitoken)
        print("\tdocksignal URL: {}".format(robot_url))


    def subscriber(self,payload=None):
        if payload == 'Shutdown':
            if self.posts != 0:
                print("Posts %d, Avg Post %.3f" %\
                      (self.posts, self.totalPostTime/self.posts), file=sys.stderr)
            print("Shutting down.", file=sys.stderr)
            self.postQ.put('Shutdown')
            #todo: actual cleanup http env
            return

        payloadJ = json.dumps(payload)
        #print "payload: %s, payloadJ: %s" % (payload,payloadJ)
        self.postQ.put(payloadJ)
        return



    def start(self):
        while True:
            c = lirc.nextcode()

            if len(c) != 0:
                self.current['dockSignal']['time'] = time.time()

                if c[0] == "power":
                    # consider sending Shutdown here
                    break
                if c[0] == "left_signal":
                    self.current['dockSignal']['left'] = 1
                elif c[0] == "right_signal":
                    self.current['dockSignal']['right'] = 1
                self.subscriber(self.current)
            else:
                t = time.time()
                if t - self.current['dockSignal']['time'] > self.timeToLive:
                    if self.current['dockSignal']['left'] == 1 or \
                            self.current['dockSignal']['right'] == 1:
                        self.current['dockSignal']['time'] = time.time()
                        self.current['dockSignal']['left'] = 0
                        self.current['dockSignal']['right'] = 0
                        self.subscriber(self.current)

            time.sleep(self.sampleInterval)

        lirc.deinit()
        return


def genericSubscriber(payload):
    print(str(payload))


if __name__ == '__main__':
    robot = None
    user = None
    apitoken = None

    try:
        robot = os.environ['ROBOT_DOCK']
        user = os.environ['ROBOT_USER']
        apitoken = os.environ['ROBOT_APITOKEN']
        robot_url = os.environ['ROBOT_URL'] + '/docksignal'
    except Exception as e:
        print(("Error setting up environment:\n%s" %
              str(e)))

    if not robot and len(sys.argv) != 2:
        print('Usage: python docksignal.py <robotname>')
        sys.exit()
    elif not robot:
        robot = sys.argv[1]

    print("Initializing Dock Signal Manager")

    dockClient = DockSignal(robot, robot_url, user, apitoken)
    # dockClient.publisher.addSubscriber(genericSubscriber)
    dockClient.start()
    time.sleep(3)
    dockClient.subscriber('Shutdown')
    dockClient.stop = True
