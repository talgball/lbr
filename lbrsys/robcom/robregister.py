#!/usr/bin/env python
"""
robregister.py - module to register the robot with server to facilitate communications
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
import sys

sys.path.append('..')

from lbrsys.settings import robRegisterURL


def registerRobot(robname=None, robuser=None, token=None):
    url = robRegisterURL + "/%s/" % robname
    headers = {'content-type': "application/json",
               'Robot': robname,   # robname and robuser not strictly needed for TokenAuthentication
               'User': robuser,
               'Authorization': "Token %s" % token,
               }

    response = requests.post(url,
                            data='\r\n',
                            headers=headers,)
                            # verify='.cred/robot.pem')

    if response.status_code == 200 or response.status_code == 204:
        print((response.content))
        return True, response.status_code
    else:
        return False, response.status_code


if __name__ == '__main__':
    robot = None
    user = None
    apitoken = None

    try:
        robot = os.environ['ROBOT']
        user = os.environ['ROBOT_DJ_USER']
        apitoken = os.environ['ROBOT_DJ_APITOKEN']
    except Exception as e:
        print(("Error setting up environment:\n%s" %
              str(e)))

    if not robot and len(sys.argv) != 2:
        print('Usage: python robregister.py <robotname>')
        sys.exit()
    elif not robot:
        robot = sys.argv[1]

    result = registerRobot(robot, user, apitoken)
    if result[0]:
        print(("Registered robot %s" % (robot,)))
    else:
        print(("Error registering robot %s\n\tStatus: %d" % (robot, result[1])))

