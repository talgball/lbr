#!/usr/bin/env python3
""""
 docksignal2.py - Arrange to obtain docking signals from the active dock
    and post them to httpservice.  This version is designed to be called from
    a service such as triggerhappy and is independent of lirc.  It uses the
    linux kernel built in gpio-ir capabilities.  Note that this module is
    executed once per relevant IR signal event and therefore needs to load and
    run in less time than the interval between signals.
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
import time
import requests
import json

def post_signal(robot_url, sig, user, apitoken, robot_ca):
    headers = {"content-type": "application/json",
               "User": user,
               "Authorization": "TOK:%s" % apitoken,
               }

    
    payload = {'dockSignal': {'time': time.time(),}}
               
    if sig == "left_signal":
        payload['dockSignal']['left'] = 1
    elif sig == "right_signal":
        payload['dockSignal']['right'] = 1
    
    try:
        response = requests.post(robot_url, data=json.dumps(payload) + '\r\n',
                                      headers=headers, verify=robot_ca)
        if response != '':           
            if response.status_code == 200 or response.status_code == 204:
                pass
            else:
                print("Docksignal post response: %d" % response.status_code,
                      file=sys.stderr)

    except Exception as e:
        print("Post Exception: %s" %(e,), file=sys.stderr)


def main():
    try:
        robot = os.environ['ROBOT_DOCK']
        user = os.environ['ROBOT_USER']
        apitoken = os.environ['ROBOT_APITOKEN']
        robot_url = os.environ['ROBOT_URL'] + '/docksignal'
        robot_ca = os.environ['ROBOT_CA']
    except Exception as e:
        print(("Error setting up environment:\n%s" %
              str(e)), file=sys.stderr)

    if len(sys.argv) > 1:
        post_signal(robot_url, sys.argv[1], user, apitoken, robot_ca)
    else:
        print("Usage: docksignal2.py <left_signal|right_signal>", file=sys.stderr)
        

if __name__ == '__main__':
    main()

        