#!/usr/bin/env python3
"""
robcamservice - Experimental module to stream pycamera for use in robot navigation
    Code drawn from example in official picamera package
    http://picamera.readthedocs.io/en/latest/recipes2.html#web-streaming
    Modified by Tal G. Ball starting on December 12, 2018

    Further modifications by Tal G. Ball, starting on December 6, 2022 to create a v4l2 compatible version
    This version drops support for picamera for now, with the intention of merging the two
    approaches into one module as a later step.

    Tal G. Ball - February 26, 2023 - Initiated elevation of navcam to robcamservice, a more generalized
    camera management service.
"""


__author__ = "Dave Jones and Tal G. Ball"
__copyright__ = "Copyright 2013 - 2017, Dave Jones and 2018 - 2023, Tal G. Ball"
__license__ = "BSD 3"
__version__ = "1.0"

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


import sys
import os
import io
# import picamera
import logging
import socketserver
import ssl
from threading import Condition
from http import server
import multiprocessing
import threading
import time

from codetiming import Timer

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(2, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.insert(3, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from lbrsys import select_camera
from lbrsys.settings import robcamLogFile, USE_SSL, CAMERAS
# USE_SSL = False
from lbrsys.robdrivers import camera


proc = multiprocessing.current_process()

if proc.name == "Robot Camera Service" :
    logging.basicConfig (level=logging.DEBUG,filename = robcamLogFile,
                        format='[%(levelname)s] (%(processName)-10s) %(message)s',)


PAGE="""\
<html>
<head>
<title>lbr Navigation</title>
</head>
<body>
<center><h1>lbr Navigation</h1></center>
<center><img src="stream.mjpg" width="1920" height="1080"></center>
</body>
</html>
"""

class StreamingOutput(object):
    def __init__(self):
        self.frame = None
        self.buffer = io.BytesIO()
        self.condition = Condition()

    def write(self, buf):
        # if buf.startswith(b'\xff\xd8'):
        if bytes(buf[:2]) == b'\xff\xd8':  # For working with array.array
            # New frame, copy the existing buffer's content and notify all
            # clients it's available
            self.buffer.truncate()
            with self.condition:
                self.frame = self.buffer.getvalue()
                self.condition.notify_all()
            self.buffer.seek(0)
        w = self.buffer.write(buf)
        return w

    def flush(self):
        pass

    def close(self):
        pass

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler):
        server.HTTPServer.__init__(self, address, handler)
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

    def serve_forever(self, **kwargs):
        try:
            return super().serve_forever(**kwargs)
        except KeyboardInterrupt:
            print(f"Exiting camera service on keyboard interrupt.")


output = StreamingOutput()

def config_camera(camera_name):
    cam = None
    try:
        cam = camera.UVCCamera(device=CAMERAS[camera_name]['device'],
                               resolution='640x360',
                               framerate=15).config_camera()
    except Exception as e:
        msg = f"Exception configuring camera: {str(camera_name)} - {e}"
        logging.debug(msg)
        print(msg)

    return cam


def start_service(commandq, broadcastq):

    # setup default camera
    default_camera_started = False

    c = None
    current_camera = None

    try:
        for c in CAMERAS:
            current_camera = config_camera(c)

            if not default_camera_started:
                # current_camera = CAMERAS[c]['camera']
                current_camera.start_recording(output, format='mjpeg')
                default_camera_started = True
                break # for now, only setup one camera at a time until ready for reusue.
                # todo make camera safe for reuse instead of having to rebuild

    except Exception as e:
        msg = f"Exception starting camera: {str(c)} - {e}"
        logging.debug(msg)
        print(msg)

    try:
        address = ('', 9146)
        server = StreamingServer(address, StreamingHandler)

        streaming_thread = threading.Thread(target=server.serve_forever, name="CameraStreamingThread")
        logging.debug("Starting Camera Streaming.")
        streaming_thread.start()
    except Exception as e:
        msg = f"Exception Starting Camera Streaming thread: {str(current_camera)} - {e}"
        current_camera.stop_recording()
        logging.debug(msg)
        print(msg)

    while True:
        task = commandq.get()

        if task == "Shutdown":
            current_camera.stop_recording()
            current_camera.close()
            commandq.task_done()
            break

        if type(task) is select_camera and task.name in CAMERAS:
            current_camera.stop_recording()
            current_camera.close()

            current_camera = config_camera(task.name)
            current_camera.start_recording(output, format='mjpeg')
            commandq.task_done()

    # streaming_thread.join()  # no current termination except KeyboardInterrupt


if __name__ == '__main__':
    cq = multiprocessing.JoinableQueue()
    bq = multiprocessing.JoinableQueue()

    service = multiprocessing.Process(target=start_service, args=(cq, bq))
    service.start()

    while True:
        cmd = input("> ")
        if cmd == "Shutdown":
            cq.put(cmd)
            break
        else:
            cq.put(select_camera(cmd))

    # todo add joining instead of terminate
    service.terminate()
    print("Done.")



