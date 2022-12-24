#!/usr/bin/env python3

"""
 dance.py - Simple app to make the robot dance based on beat location time offset data
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


import os
import sys
import json
import time
import subprocess
import wave
import alsaaudio
from threading import Thread

# temporary approach to make the rest of lbrsys available to this app
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.append(os.path.dirname(BASE_DIR))
sys.path.append(os.path.dirname(os.path.dirname(BASE_DIR)))

from lbrsys import power, dance
from lbrsys.robcom import robhttp2


class DanceApp(robhttp2.Client):
    def __init__(self, robot=None, robot_url=None,
                 user=None, token=None, cur_dance=None):
        super(DanceApp, self).__init__(robot, robot_url)
        self.setAuthToken(user, token)

        self.dance = cur_dance
        self.musicDir = os.getenv('ROBOT_MUSIC')

        self.songWavFile = self.musicDir + '/' + cur_dance.song + '.wav'
        self.songDataFile = self.musicDir + '/' + cur_dance.song + '.json'
        self.songData = self.get_song_data()
        self.t0 = 0.0
        self.song_started = False

        if self.songData:
            self.moves = self.config_moves()
            self.beats = self.songData['BEATS']
            print("Starting dance!")
            self.start()
        else:
            print("No song data.")

    def get_song_data(self, song_data_file=None):
        if song_data_file is not None:
            _song_data_file = song_data_file
        else:
            _song_data_file = self.songDataFile

        with open(_song_data_file, "r") as sdf:
            return json.load(sdf)

    def config_moves(self):
        move_right = power(0.5, 90)
        move_left = power(0.5, 270)
        move_up = power(0.5, 0)
        move_back = power(0.5, 180)
        # move_spin = todo configure this when mpu enabled

        # todo externalize choreography
        default_choreography = [move_right, move_left, move_up, move_back]
        core_1 = [move_up, move_back,
                  move_up, move_back,
                  move_left, move_right,
                  move_right, move_left,
                  ]

        core_2 = [move_up, move_up,
                  move_back, move_back,
                  move_left, move_right,
                  move_right, move_right,
                  move_left, move_left,
                  ]

        return core_1

    def move(self, cur_move):
        self.post(cur_move)

    def play_aplay(self, song=None):
        if song is not None:
            _song = song
        else:
            _song = self.songWavFile

        try:
            subprocess.run(['aplay', _song])
        except Exception as e:
            print(f"Error playing {song}")
            raise e

    def play(self, song=None):
        """play from playwav.py from pyalsaaudio package, modified for this app"""
        if song is not None:
            _song = song
        else:
            _song = self.songWavFile

        device = 'default' # todo externalize

        with wave.open(_song, 'rb') as f:
            format = None

            # 8bit is unsigned in wav files
            if f.getsampwidth() == 1:
                format = alsaaudio.PCM_FORMAT_U8
            # Otherwise we assume signed data, little endian
            elif f.getsampwidth() == 2:
                format = alsaaudio.PCM_FORMAT_S16_LE
            elif f.getsampwidth() == 3:
                format = alsaaudio.PCM_FORMAT_S24_3LE
            elif f.getsampwidth() == 4:
                format = alsaaudio.PCM_FORMAT_S32_LE
            else:
                raise ValueError('Unsupported format')

            periodsize = f.getframerate() // 8

            print('%d channels, %d sampling rate, format %d, periodsize %d\n' % (f.getnchannels(),
                                                                                 f.getframerate(),
                                                                                 format,
                                                                                 periodsize))
            #
            device = alsaaudio.PCM(channels=f.getnchannels(), rate=f.getframerate(),
                                   format=format, periodsize=periodsize, device=device)

            data = f.readframes(periodsize)
            while data:
                # Read data from stdin
                device.write(data)
                self.song_started = True
                data = f.readframes(periodsize)

    def start(self):
        song_thread = Thread(target=self.play, name="SongThread")
        song_thread.start()

        printed = False
        while True:
            if not self.song_started:
                continue
            else:
                if not printed:
                    print("Song started flag set.")
                    printed = True

            try:
                cur_move_num = 0
                cur_move = self.moves[cur_move_num % len(self.moves)]
                t0 = time.time()

                self.move(cur_move)

                for beat in self.beats:
                    t_now = time.time()

                    if t_now < t0 + beat:
                        time.sleep(t0 + beat - t_now)

                    cur_move_num += 1
                    cur_move = self.moves[cur_move_num % len(self.moves)]
                    self.move(cur_move)

            except KeyboardInterrupt:
                print(f"Stopping song on keyboard interrupt.")
                self.move(power(0, 0))
            finally:
                self.move(power(0, 0))
                break

        song_thread.join()


if __name__ == '__main__':
    try:
        robot = os.environ['ROBOT']
        robot_url = os.environ['ROBOT_URL']
        user = os.environ['ROBOT_USER']
        token = os.environ['ROBOT_APITOKEN']
    except Exception as e:
        print(("Error setting up environment:\n%s" %
              str(e)))
        raise e

    if len(sys.argv) > 2:
        print(f"Usage:  dance <song file from music dir>")
        exit()
    elif len(sys.argv) == 2:
        da  = DanceApp(robot, robot_url, user, token, dance(sys.argv[1]))
    else:
        da = DanceApp(robot, robot_url, user, token, dance('beg'))

    # da = DanceApp(robot, robot_url, user, token, dance('aobtd'))
