#!/usr/bin/env python3
"""
camera.py - UVC camera module, with partial emulation of PiCamera api
    Borrows from video.py by @fernandoemor and @artizirk from github
    Adds class structure
    Adds iotcl management approach from capture.c in the linux documentation
    Adds PiCamera-like interface
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
import errno
import mmap
import select
import time
import threading
import array

from codetiming import Timer, TimerError


class UVCCamera(object):
    """USB Video Class Camera Management"""
    def __init__(self, device='/dev/video0', video_format='mjpeg',
                 # resolution='1280x720', framerate=30, memory='USERPTR',
                 # resolution='1920x1080', framerate=30, memory='USERPTR',
                 resolution='640x360', framerate=24, memory='USERPTR', name=None):
        self.device = device
        self.video_format = video_format
        self.width, self.height = [int(r) for r in resolution.split('x')]
        self.framerate = framerate
        self.name = name
        self.memory = memory  # 'USERPTR' or 'MMAP'
        self.vd = None
        self.cp = None
        self.fmt = None
        self.req = None
        self.requested_buffer_count = 2  #  2 is min, 1 for filling and 1 for reading simultaneously
        self.buffers = []
        self.output = None
        self.streaming_thread = None
        self.do_stream = False
        self.buf = v4l2_buffer()
        self.buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        # self.buf.memory = V4L2_MEMORY_MMAP
        self.buf.memory = V4L2_MEMORY_USERPTR
        self.buf_type = v4l2_buf_type(V4L2_BUF_TYPE_VIDEO_CAPTURE)
        self.frames_read = 0
        # self.frame_timer = Timer(name="Frame", logger=None)
        # self.frame_acq_timer = Timer(name="FrameAcquisition", logger=None)
        # self.frame_write_timer = Timer(name="FrameWrite", logger=None)
        # self.select_timer = Timer(name="Select", logger=None)
        # self.mm_read_timer = Timer(name="MMRead", logger=None)

    def __enter__(self):
        return self.config_camera()

    def close(self):
        self.vd.close()

    def __exit__(self, exc_type=None, exc_value=None, exc_tb=None):
        self.close()

    def stream_on(self):
        return self.xioctl(VIDIOC_STREAMON, self.buf_type)

    def stream_off(self):
        return self.xioctl(VIDIOC_STREAMOFF, self.buf_type)

    def config_camera(self):
        try:
            self.vd = open(self.device, 'rb+', buffering=0)
            print("Getting device capabilities")
            self.cp = v4l2_capability()
            self.xioctl(VIDIOC_QUERYCAP, self.cp)

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
            # self.fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV
            self.xioctl(VIDIOC_S_FMT, self.fmt)

            print("Verifying settings..")  #todo change to assert statements
            self.xioctl(VIDIOC_G_FMT, self.fmt)  # get current settings
            print("width:", self.fmt.fmt.pix.width, "height:", self.fmt.fmt.pix.height)
            print("pxfmt:", self.fmt.fmt.pix.pixelformat)
            print("bytesperline:", self.fmt.fmt.pix.bytesperline)
            print("sizeimage:", self.fmt.fmt.pix.sizeimage)

            print("Getting streaming parameters.")  # todo somewhere in here you can set the camera framerate
            parm = v4l2_streamparm()
            parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            parm.parm.capture.capability = V4L2_CAP_TIMEPERFRAME
            self.xioctl(VIDIOC_G_PARM, parm)
            numerator = parm.parm.output.timeperframe.numerator
            denominator = parm.parm.output.timeperframe.denominator
            print(f"\ttime per frame: {numerator}/{denominator}")
            if denominator != self.framerate and numerator == 1:
                print(f"\tChanging to {self.framerate}fps...")
                parm.parm.output.timeperframe.denominator = self.framerate
                self.xioctl(VIDIOC_S_PARM, parm)
                self.xioctl(VIDIOC_G_PARM, parm)
                denominator = parm.parm.output.timeperframe.denominator
                if self.framerate == denominator:
                    print("\t\tConfirmed.")
                else:
                    print(f"\t\tFailed to change frame rate to {self.framerate}fps.  Rate is {denominator}fps.")

            self.prepare_buffers()

        except Exception as e:
            print(f"Exception configuring camera: {e}")
            raise e

        return self

    def prepare_buffers(self, memory=None):
        if memory is None:
            memory = self.memory

        if memory == 'USERPTR':
            memory_type = V4L2_MEMORY_USERPTR
        else:
            # default to memory map if not using user allocated buffers
            memory_type = V4L2_MEMORY_MMAP

        self.req = v4l2_requestbuffers()
        self.req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        self.req.count = self.requested_buffer_count
        self.req.memory = memory_type
        self.xioctl(VIDIOC_REQBUFS, self.req)  # request buffers

        for i in range(self.req.count):
            buf = v4l2_buffer()
            buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.index = i
            buf.memory = memory_type
            self.xioctl(VIDIOC_QUERYBUF, buf)

            if memory_type == V4L2_MEMORY_USERPTR:
                new_buf = array.array('B', b'\x00' * buf.length)
                buf.m.userptr = new_buf.buffer_info()[0]
            else:
                new_buf = mmap.mmap(self.vd.fileno(), buf.length, mmap.MAP_SHARED,
                               mmap.PROT_READ | mmap.PROT_WRITE, offset=buf.m.offset)

            self.buffers.append(new_buf)

            # queue the buffer for capture
            self.xioctl(VIDIOC_QBUF, buf)

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
        self.stream_on()

        print("\tEntering streaming interface loop.")
        while self.do_stream:
            self.read_frame()

        self.stream_off()

    def read_frame(self):
        # self.frame_timer.start()
        # self.frame_acq_timer.start()

        # self.select_timer.start()
        max_t = 1
        ready_to_read, ready_to_write, in_error = select.select([self.vd], [], [], max_t)

        if len(ready_to_read) == 0:
            raise Exception("Select timeout.")
        # self.select_timer.stop()

        # self.mm_read_timer.start()
        self.xioctl(VIDIOC_DQBUF, self.buf)  # get image from the driver queue
        # print("self.buf.index", self.buf.index)
        f = b''
        if self.buf.memory == V4L2_MEMORY_USERPTR:
            f = self.buffers[self.buf.index]
        else:
            # default to memory map
            mm = self.buffers[self.buf.index]
            f = mm.read()
        # self.mm_read_timer.stop()

        # self.frame_acq_timer.stop()

        # self.frame_write_timer.start()
        self.output.write(f)
        # self.output.write(f.tobytes())  # another option for array.array.  converting here is slower

        # self.frame_write_timer.stop()
        # self.output.write(mm.read())
        if self.buf.memory == V4L2_MEMORY_MMAP:
            mm.seek(0)

        self.xioctl(VIDIOC_QBUF, self.buf)  # requeue the buffer
        self.frames_read += 1
        # self.frame_timer.stop()

        return

    def stop_recording(self):
        print("Stopping streaming..")
        self.do_stream = False
        time_msg = f"\tProcessed {self.frames_read} frames"
        # time_msg += f"{(Timer.timers['Frame']/self.frames_read)*1000:0.2f}ms/frame"
        print(time_msg)
        # timers disabled for now
        # print(f"\tAcquiring Frame: {(Timer.timers['FrameAcquisition']/self.frames_read*1000):0.2f}ms/frame")
        # print(f"\t\tWaiting for Device: {(Timer.timers['Select']/self.frames_read*1000):0.2f}ms/frame")
        # print(f"\t\tReading Frame from Buffer: {(Timer.timers['MMRead']/self.frames_read*1000):0.2f}ms/frame")
        # print(f"\tWriting Frame: {(Timer.timers['FrameWrite']/self.frames_read*1000):0.2f}ms/frame")

        # try:
        #     print(f"Latency Estimate: {(Timer.timers['LatencyTimer']/self.frames_read*1000):0.2f}ms/frame")
        # except KeyError:
        #     pass

        self.streaming_thread.join()  #todo add timeout and check is_alive

    def xioctl(self, request, arg):
        """Python version of wrapper to handle errors.
        See https://www.kernel.org/doc/html/v4.15/media/uapi/v4l/capture.c.html"""
        while True:
            r = -1
            try:
                r = fcntl.ioctl(self.vd, request, arg, True)
                if r == 0:
                    return r
            except IOError as e:
                if r == -1 and e.errno == errno.EINTR:
                    continue
                else:
                    raise e


if __name__ == '__main__':
    print("Running local test to capture a few seconds of video")
    vidfile = '/home/robot/tmp/video.mjpg'  # todo pass as arg
    vid = open(vidfile, 'wb')
    t0 = time.time()
    duration = 5.0

    do_test = True

    while do_test:
        with UVCCamera(device='/dev/video0') as camera:
            print("Starting recording..")
            camera.start_recording(vid)
            time.sleep(duration)
            print("Stopping recording..")
            camera.stop_recording()

        cont = input("Re-test: ")
        if cont.lower() != 'y' and cont.lower() != 'yes':
            do_test = False

    vid.close()
    print("Done.")