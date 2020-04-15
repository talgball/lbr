#!/usr/bin/env python3
"""
robiot.py - Robot application to interact with the iot shadow.
    Telemetry state is reported to the shadow.  Desired states are used to drive motors.

    Shadow interaction is based on the examples from Amazon.  Their command line is:
    python shadow.py --endpoint a15t3x0cscxlt9-ats.iot.us-west-2.amazonaws.com \
        --root-ca '../../../.cred/iot/AmazonRootCA1.pem' \
        --cert '../../../.cred/iot/25e29ecfa9-certificate.pem.crt' \
        --key '../../../.cred/iot/25e29ecfa9-private.pem.key' \
        --thing-name lbr2a
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
from threading import Thread
import logging
import multiprocessing
import queue

from lbrsys import feedback
from lbrsys.settings import iotLogFile

from robcom import robhttp2
from robapps.iot import shadow

if multiprocessing.current_process().name == "Robot IoT Services":
    logging.basicConfig(
        level=logging.INFO,
        # level=logging.DEBUG,
        filename=iotLogFile,
        format='[%(levelname)s] (%(processName)-10s) %(message)s'
    )


class Args(object):
    """Class object to hold the args for shadow.main to make this module align with shadow.py"""
    thing_name = None
    robot_url = None
    endpoint = None
    root_ca = None
    cert = None
    key = None
    robot_ca = None
    verbosity = None
    use_websocket = False
    client_id = None
    shadow_property = None
    proxy_host = None
    signing_region = None
    robot_client = None


class RobIoTService(object):
    def __init__(self, commandQ=None, broadcastQ=None):
        print(("Process Name is %s" % multiprocessing.current_process().name))
        self.commandQ = commandQ
        self.broadcastQ = broadcastQ
        self.shadow_thread = None
        self.shadow_ops = None
        self.sq = None

        self.args = Args()
        self.setup_env()
        self.start_shadow()

        self.command_thread = Thread(target=self.start,
                                     name="RobIoTService Command Thread")
        # self.command_thread.daemon = True
        self.command_thread.start()


    def setup_env(self):
        try:
            self.args.thing_name = os.environ['ROBOT']
            self.args.robot_url = os.environ['ROBOT_URL']
            self.args.endpoint = os.environ['ROBOT_AWS_ENDPOINT']
            self.args.root_ca = os.environ['ROBOT_AWS_ROOT_CA']
            self.args.cert = os.environ['ROBOT_AWS_CERT']
            self.args.key = os.environ['ROBOT_AWS_KEY']
            self.args.robot_ca = os.environ['ROBOT_CA']
            self.args.verbosity = None  # placeholder, will be set in shadow.py
            # self.args.verbosity = 'Debug'
            self.args.use_websocket = False
            # self.args.client_id = 'samples-client-id'
            self.args.client_id = self.args.thing_name + '-client-id'
            self.args.shadow_property = 'telemetry'
            self.args.proxy_host = None
            self.args.proxy_port = 8080
            self.args.signing_region = 'us-west-2'
            user = os.environ['ROBOT_USER']
            token = os.environ['ROBOT_APITOKEN']
            self.args.robot_client = robhttp2.Client(self.args.thing_name, self.args.robot_url, user, token)

            """
            print("\t{}\n\t{}\n\t{}\n\t{}\n\t{}\n\t{}\n\t{}".format(
                self.args.thing_name,
                self.args.robot_url,
                self.args.endpoint,
                self.args.root_ca,
                self.args.cert,
                self.args.key,
                self.args.robot_ca))
            """

        except Exception as e:
            print(("Error setting up environment:\n%s" % str(e)))


    def start_shadow(self):
        print(("Starting shadow update process for %s" % self.args.robot_url))

        self.sq = queue.Queue()
        self.shadow_thread = Thread(target=shadow.ShadowOps,
                                    name='Robot Telemetry Shadow Update Process',
                                    args=(self.args, self.sq))

        # self.shadow_thread.daemon = True
        self.shadow_thread.start()
        return


    def start(self):
        while True:
            task = self.commandQ.get()
            if task == 'Shutdown':
                print("Shutting down RobIoT Service")
                self.sq.put("Shutdown")
                self.shadow_thread.join()
                self.commandQ.task_done()
                break
            else:
                print(("RobIotService Unknown Task %s" % str(task)))
        print("RobIoTService exited")
        return


if __name__ == '__main__':
    sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
    sys.path.insert(2, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
    sys.path.insert(3, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

    multiprocessing.set_start_method('spawn')
    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()
    p = multiprocessing.Process(target=RobIoTService, name="RobIoTService", args=(cq, bq))
    p.start()
    # iot_service = RobIoTService(cq, bq)
    i = input("Press any key to quit> ")
    cq.put("Shutdown")
    cq.join()
    bq.join()




