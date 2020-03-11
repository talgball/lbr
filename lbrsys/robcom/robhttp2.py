#!/usr/bin/env python
"""
robhttp2.py - module to handle http communications for robot client apps
    Version 2 externalizes environment dependencies and prepares the module
    to support robiot and refactors.  Also supports python3 and python2.
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
import requests
import json
import sys
import time
import threading
import queue

from robcom import publisher


class Client(object):
    def __init__(self, robot=None, robot_url=None, user=None, token=None):
        self.robot = robot
        self.robot_url = robot_url
        self.user = user
        self.token = token
        self.headers = {"content-type": "application/json"}
        self.t0 = time.time()
        self.posts = 0
        self.totalPostTime = 0.

        try:
            self.robot_ca = os.environ['ROBOT_CA']
        except:
            self.robot_ca = False

        if user and token:
            self.setAuthToken(user, token)

        self.publisher = publisher.Publisher("Robot http Client Publisher")

        self.postQ = queue.Queue()
        self.postThread = threading.Thread(target=self.postService,
                                           name="Post Service Thread")
        self.postThread.setDaemon(True)
        self.postThread.start()

    def setAuthToken(self, user=None, token=None):
        self.headers['User'] = user
        self.headers['Authorization'] = 'TOK:%s' % token

    def subscriber(self, payload=None):
        if payload == 'Shutdown':
            if self.posts != 0:
                print("Posts %d, Avg Post %.3f" %\
                      (self.posts, self.totalPostTime/self.posts), file=sys.stderr)
            print("Shutting down robhttp client.", file=sys.stderr)
            self.postQ.put('Shutdown')
            #todo: actual cleanup http env
            return

        payloadJ = json.dumps(payload._asdict())
        #print "payload: %s, payloadJ: %s" % (payload,payloadJ)
        self.postQ.put(payloadJ)        
        return

    def post(self, payload=None):
        """ Establish synonym for subscribe.  Considering refactor"""
        self.subscriber(payload)

    def get(self):
        response = ''
        responseJ = ''

        try:
            response = requests.get(self.robot_url + '/telemetry', data='\r\n',
                                    headers=self.headers, verify=self.robot_ca)

        except Exception as e:
            print("Get Exception: %s" %(e,), file=sys.stderr)

        if response != '':
            if response.status_code == 200:

                try:
                    responseJ = [response.json()]
                except ValueError as e:
                    responseJ = [{}]

            else:
                print("Response code: %d, Reason: %s\n" % \
                                     (response.status_code, response.reason), file=sys.stderr)

        return responseJ

    def postService(self):
        while True:
            payload = self.postQ.get()
            self.postQ.task_done()
            if payload == 'Shutdown':
                break
            
            tp0 = time.time()
            self.response = ''

            try:
                self.response = requests.post(self.robot_url, data=payload + '\r\n',
                                              headers=self.headers, verify=self.robot_ca)

            except Exception as e:
                print("Post Exception: %s" %(e,), file=sys.stderr)
            
            tp1 = time.time()
            self.postTurnAroundTime = tp1 - tp0
            self.totalPostTime += self.postTurnAroundTime
            self.posts += 1

            if self.response != '':           
                if self.response.status_code == 200 or self.response.status_code == 204:
                    
                    try:
                        responseJ  = [self.response.json()]
                    except ValueError as e:
                        responseJ = [{}]
                        
                    if type(responseJ[0]) is dict:
                        responseJ[0]['TurnAroundTime'] = self.postTurnAroundTime
                        responseJ[0]['Command'] = payload
                        responseJ[0]['Status'] = self.response.status_code
                    
                    self.publisher.publish(responseJ)

                else:
                    print("Response code: %d, Reason: %s\n\tPayload: %s" % \
                            (self.response.status_code, self.response.reason, str(payload)), file=sys.stderr)
            else:
                self.publisher.publish('No response')
                
        
def genericSubscriber(payload):
    print(str(payload))


if __name__ == '__main__':
    #from roblocals import *
    from collections import namedtuple
    power = namedtuple('power', 'level angle')

    robot = os.environ['ROBOT']
    robot_url = os.environ['ROBOT_URL']
    user = os.environ['ROBOT_USER']
    token = os.environ['ROBOT_APITOKEN']

    c = Client(robot, robot_url, user, token)
    c.publisher.addSubscriber(genericSubscriber)

    for n in range(5):
        c.post(power(0., 0))
        print("n: %d" % n)

    i = input("Press Enter to Shutdown: ")
    c.post('Shutdown')
