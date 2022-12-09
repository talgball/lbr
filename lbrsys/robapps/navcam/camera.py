#!/usr/bin/env python3
"""
camera.py - UVC camera module, with partial emulation of PiCamera api
    Borrows heavily from video.py by @fernandoemor and @artizirk from github
    Adds class structure and PiCamera-like interface
    Adds focus on mjpeg, which I'm currently using for robot navigation
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2022 Tal G. Ball"
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


from v4l2 import *
import fcntl
import mmap
import select
import time
import threading


class UVCCamera(object):
    def __init__(self, device='/dev/video0', video_format='mjpeg',
                 resolution='1920x1080', framerate=30):
        self.device = device
        self.video_format = video_format
        self.width, self.height = [int(r) for r in resolution.split('x')]
        self.framerate = framerate
        self.vd = None
        self.cp = None
        self.fmt = None
        self.req = None
        self.requested_buffer_count = 1 #  Saw somewhere that ~3 is normal.  Seems less laggy at 1.
        self.buffers = []
        self.output = None
        self.streaming_thread = None
        self.do_stream = False

    def __enter__(self):
        return self.config_camera()

    def __exit__(self, exc_type=None, exc_value=None, exc_tb=None):
        self.vd.close()
        if self.output is not None:
            self.output.flush()
            self.output.close()

    def prepare_buffers(self):
        self.req = v4l2_requestbuffers()
        self.req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        self.req.memory = V4L2_MEMORY_MMAP
        self.req.count = self.requested_buffer_count
        fcntl.ioctl(self.vd, VIDIOC_REQBUFS, self.req)  # request buffers

        for i in range(self.req.count):
            # setup a buffer
            buf = v4l2_buffer()
            buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = V4L2_MEMORY_MMAP
            buf.index = i
            fcntl.ioctl(self.vd, VIDIOC_QUERYBUF, buf)

            mm = mmap.mmap(self.vd.fileno(), buf.length, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                           offset=buf.m.offset)
            self.buffers.append(mm)

            # queue the buffer for capture
            fcntl.ioctl(self.vd, VIDIOC_QBUF, buf)

    def start_recording(self, output, format='mjpeg'):
        """'recording' naming convention to comply with PiCamera api.
        'format' not really yet supported
        """
        self.output = output
        self.video_format = format
        self.streaming_thread = threading.Thread(target=self.stream, name="StreamingThread")
        self.do_stream = True
        self.streaming_thread.start()
        print(f"Started Streaming Thread: {str(self.streaming_thread)}")

    def stream(self):
        print("\tStreaming..")
        buf_type = v4l2_buf_type(V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(self.vd, VIDIOC_STREAMON, buf_type)

        # note that select registers the device and therefore does not need to be in the main loop.
        # todo further investigating / understanding select in combination with ioctl
        print("\tCapturing initial image.")
        t0 = time.time()
        max_t = 1
        ready_to_read, ready_to_write, in_error = ([], [], [])
        print("\tEstablishing select to wait for image availability.")
        while len(ready_to_read) == 0 and time.time() - t0 < max_t:
            ready_to_read, ready_to_write, in_error = select.select([self.vd], [], [], max_t)

        buf = v4l2_buffer()
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        buf.memory = V4L2_MEMORY_MMAP

        while self.do_stream:
            fcntl.ioctl(self.vd, VIDIOC_DQBUF, buf)  # get image from the driver queue
            # print("buf.index", buf.index)
            mm = self.buffers[buf.index]
            self.output.write(mm.read())
            mm.seek(0)
            fcntl.ioctl(self.vd, VIDIOC_QBUF, buf)  # requeue the buffer

        buf_type = v4l2_buf_type(V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(self.vd, VIDIOC_STREAMOFF, buf_type)

    def stop_recording(self):
        print("Stopping streaming..")
        self.do_stream = False
        self.streaming_thread.join()  #todo add timeout and check is_alive


    def config_camera(self):
        try:
            self.vd = open(self.device, 'rb+', buffering=0)
            print("Getting device capabilities")
            self.cp = v4l2_capability()
            fcntl.ioctl(self.vd, VIDIOC_QUERYCAP, self.cp)

            print(f"Driver:  {self.cp.driver.decode()}")
            print(f"Name: {self.cp.card.decode()}")
            print("Is a video capture device?", bool(self.cp.capabilities & V4L2_CAP_VIDEO_CAPTURE))
            print("Supports read() call?", bool(self.cp.capabilities &  V4L2_CAP_READWRITE))
            print("Supports streaming?", bool(self.cp.capabilities & V4L2_CAP_STREAMING))

            print("Setting up device.")
            self.fmt = v4l2_format()
            self.fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            self.fmt.fmt.pix.width = self.width
            self.fmt.fmt.pix.height = self.height
            self.fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG # todo only does mjpeg for now
            fcntl.ioctl(self.vd, VIDIOC_S_FMT, self.fmt)
            print("Verifying settings..")  #todo change to assert statements
            fcntl.ioctl(self.vd, VIDIOC_G_FMT, self.fmt)  # get current settings
            print("width:", self.fmt.fmt.pix.width, "height:", self.fmt.fmt.pix.height)
            print("pxfmt:", self.fmt.fmt.pix.pixelformat)
            print("bytesperline:", self.fmt.fmt.pix.bytesperline)
            print("sizeimage:", self.fmt.fmt.pix.sizeimage)

            print("Getting streaming parameters.")  # todo somewhere in here you can set the camera framerate
            parm = v4l2_streamparm()
            parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            parm.parm.capture.capability = V4L2_CAP_TIMEPERFRAME
            fcntl.ioctl(self.vd, VIDIOC_G_PARM, parm)
            numerator = parm.parm.output.timeperframe.numerator
            denominator = parm.parm.output.timeperframe.denominator
            print(f"\ttime per frame: {numerator}/{denominator}")
            # fcntl.ioctl(self.vd, VIDIOC_S_PARM, parm)  # just got with the defaults

            self.prepare_buffers()

        except Exception as e:
            print(f"Exception configuring camera: {e}")

        return self

if __name__ == '__main__':
    print("Running local test to capture a few seconds of video")
    vidfile = '/home/robot/tmp/video.mjpg'
    vid = open(vidfile, 'wb')
    t0 = time.time()
    tmax = 5.0

    with UVCCamera() as camera:
        print("Starting recording..")
        camera.start_recording(vid)
        while time.time() - t0 <= tmax:
            time.sleep(0.1)
        print("Stopping recording..")
        camera.stop_recording()
    print("Done.")