""" Robot http server and interface handler
Approach to operations:
    This http server module is conceptualized as a gateway between a robot,
    with private, internal operations, and the web.  Incoming requests for
    actions to be executed by the robot and requests for information such as
    telemetry data arrive via http post and get.

    Requests posted for execution are forwarded to the robot process using
    the robot's internal communications framework.  (In general, a move toward
    all json messaging is being considered.)

    When the robot makes available information for consumption by web users, it
    sends the information to this server.   User retrieve the information in replies
    to their posts or in replies to their get requests.
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


from http.server import HTTPServer
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import os
import ssl
import time
from time import time as robtimer
import json
import logging
import multiprocessing
import threading
import socket

from lbrsys.settings import robhttpLogFile, robhttpAddress, USE_SSL
from lbrsys import feedback

from robcom import robauth

proc = multiprocessing.current_process()

if proc.name == "Robot Http Service" :
    logging.basicConfig (level=logging.DEBUG,filename = robhttpLogFile,
                        format='[%(levelname)s] (%(processName)-10s) %(message)s',)


class RobHTTPService(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, receiveQ, sendQ):
        HTTPServer.__init__(self, address, handler)
        self.receiveQ = receiveQ
        self.sendQ = sendQ
        self.currentTelemetry = {'Ranges':{'Left':1,'Right':2,'Forward':3, 'Back':4, 'Bottom':5}}
        self.newTelemetry = True
        self.t0 = robtimer()
        self.motors_powered = 0
        self.telemetry_sent = 0
        self.heartbeat_thread = None
        self.heartbeat = False

        self.set_security_mode()


    def set_security_mode(self):
        try:
            if USE_SSL:
                self.socket = ssl.wrap_socket(
                    self.socket,
                    server_side=True,
                    certfile=os.environ['ROBOT_CERT'],
                    keyfile=os.environ['ROBOT_KEY']
                )
        except Exception as e:
            logging.error("Exception securing http server: {}".format(str(e)))


    def set_heartbeat(self):
        if self.motors_powered > 0 and not self.heartbeat:
            self.heartbeat_thread = threading.Thread(target=self.check_heartbeat)
            self.heartbeat_thread.start()
            self.heartbeat = True


    def check_heartbeat(self, pulse=2.0):
        time.sleep(pulse)
        self.heartbeat = False
        if self.motors_powered > 0 and time.time() - self.telemetry_sent > pulse:
            self.sendQ.put('/r/0/0')
            self.motors_powered = 0
            logging.debug("heartbeat timeout - cutting motor power")
        else:
            # print('\ttelemetry age: %.3f' % (time.time() - self.telemetry_sent))
            self.set_heartbeat()
    #
    # run this updater in a separate thread
    #
    def updateTelemetry(self):
        while True:
            msg = self.receiveQ.get()
            # print("Updating telemetry: {}".format(str(msg)))
            self.receiveQ.task_done()
            if msg == "Shutdown":
                break

            if type(msg) is feedback:  # todo - reexamine and look at voltages
                if type(msg.info) is dict:
                    self.currentTelemetry[list(msg.info.keys())[0]] = list(msg.info.values())[0]
                else:
                    print("Please send telemetry feedback as dict: %s" % (msg.info))

                self.newTelemetry = True
        return


class RobHandler(BaseHTTPRequestHandler):
    buffering = 1 # line buffering mode
    http_log_file = open(robhttpLogFile, 'w', buffering)

    def log_message(self, format, *args):
        self.http_log_file.write("%s - - [%s] %s\n" %
                            (self.client_address[0],
                             self.log_date_time_string(),
                             format % args))

    def handle_power(self, msgD):

        command = None
        # todo msgD type checking
        if 'heading' in msgD and msgD['heading'] != '':
            command = "/h/%.1f" % float(msgD['heading'])

        elif 'turn' in msgD and msgD['turn'] != '':
            command = "/t/%.1f" % float(msgD['turn'])

        elif 'level' in msgD and msgD['level'] != '':
            command = "/r/%.2f/%d" % (float(msgD['level']), int(msgD['angle']))

            # todo debug the default sensor case
            if 'range' in msgD and msgD['range'] != '':
                command += "/%d" % (int(msgD['range']))
                if 'sensor' in msgD and msgD['sensor'] != '':
                    command += "/%s" % msgD['sensor']
                else:
                    command += "Forward"

                if 'duration' in msgD and msgD['duration'] is not None:
                    command += "/%.1f" % (float(msgD['duration']))
                else:
                    command += "/0"

            if msgD['level'] > 0:
                self.server.motors_powered = time.time()
            elif msgD['level'] == 0:
                self.server.motors_powered = 0

        if command is not None:
            self.server.sendQ.put(command)
            self.send_response(200)
        else:
            self.send_response(400)

        if self.server.newTelemetry:
            self.server.newTelemetry = False

        # for now, always send telemetry
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        buffer = json.dumps(self.server.currentTelemetry).encode()
        # json.dump(buffer, self.wfile)
        self.wfile.write(buffer)

        if self.server.motors_powered > 0:
            self.server.telemetry_sent = time.time()
            self.server.set_heartbeat()

        if self.server.currentTelemetry == "Shutdown":
            logging.info("Shutting down robot http gateway service.")
            shutdownThread = threading.Thread(target=self.server.shutdown,
                                              name="Shutdown Thread")
            shutdownThread.start()
            shutdownThread.join()

        return


    def handle_docksignal(self, msgD):
        # print("handling docksignal: %s" % json.dumps(msgD))

        self.server.receiveQ.put(feedback(msgD))

        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        return

    def is_user_authorized(self):
        try:
            user = self.headers['User']
            token_type, token = self.headers['Authorization'].split(':')
            if token_type == 'TOK' and robauth.is_authorized(user, token):
                return True
            else:
                raise Exception
        except Exception as e:
            logging.info("Failed authorization.  Headers:\n%s\n%s" %
                         (str(self.headers), str(e)))
            return False


    def do_OPTIONS(self):
        """" Setup to support ajax queries from client"""
        # print("Headers: %s" % str(self.headers))
        self.send_response(200, 'ok')
        self.send_header('Access-Control-Allow-Credentials', 'true')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-Requested-With, Content-type, User, Authorization')
        self.end_headers()
        return


    def do_GET(self):
        """ return current telemetry"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        buffer = json.dumps(self.server.currentTelemetry).encode()
        # json.dump(buffer, self.wfile)
        self.wfile.write(buffer)

        self.server.telemetry_sent = time.time()
        # print("GET path: %s" % self.path)

        return


    def do_POST(self):
        """
        post power, turn or heading json for operating the motors
        post to /docksignal path to communicate receipt of docking signals

         post replies:
           200 - post reply contains telemetry data
           204 - post reply is status only, i.e. no new data.
           400 - bad post request, i.e. no power level provided (for now)
           401 - authentication failure
        """
        # print("Headers: %s" % str(self.headers))

        tpstart = time.time()

        if not self.is_user_authorized():
            self.send_response(401)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            return

        #assume json for now, one obj per line.
        msgS = self.rfile.readline()

        if type(msgS) is bytes:
            msgS = msgS.decode()

        msgD = json.loads(msgS)

        if self.path == '/':
            self.handle_power(msgD)

        elif self.path == '/docksignal':
            self.handle_docksignal(msgD)

        return


def startService(receiveQ, sendQ, addr=robhttpAddress):
    server = RobHTTPService(addr, RobHandler, receiveQ, sendQ)
    # server = RobHTTPService(('', 9145), RobHandler, receiveQ, sendQ)

    telUpdateThread = threading.Thread(target=server.updateTelemetry,
                                       name = "TelemetryUpdateThread")
    logging.debug("Starting Telemetry Updater.")
    telUpdateThread.start()
    
    logging.debug("Starting robot http gateway service.")
    server.serve_forever()
    telUpdateThread.join()

    # todo refactor this close
    RobHandler.http_log_file.close()


if __name__ == '__main__':

    sendQ = multiprocessing.JoinableQueue()
    receiveQ = multiprocessing.JoinableQueue()
    #address = robhttpAddress
    
    p = multiprocessing.Process(target=startService,
                                args=(receiveQ, sendQ,
                                      # ('',9145)),
                                      ('lbr2a.ballfamily.org',9145)),
                                      #('127.0.0.1',9145)),
                                name='Robot Http Service')                                 

    p.start()

    print("Service started..")

    cn = 0
    while True:
        comm = sendQ.get()
        sendQ.task_done()
        print("%d - %s: %s" % (cn,time.asctime(), comm))
        cn += 1
        if cn >= 20:
            receiveQ.put("Shutdown")
            break
        else:
            receiveQ.put("[{'Return':(%d,%d,%d)}]" % (cn,cn,cn))

    print("Joining Queues..")
    sendQ.join()
    receiveQ.join()
    print("Done.")
    print("Stopping service process..")
    #p.join()
    p.terminate()
    print("Done.")
