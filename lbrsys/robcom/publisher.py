"""
publisher.py - Simple, general-purpose publish module
    It's up to the publisher and subscriber to agree as to the nature of the
    publications and payloads
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


class Publisher:
    def __init__(self, keyMessage):
        self.keyMessage = keyMessage
        self.subscribers = []


    def addSubscriber(self, subscriber):
        self.subscribers.append(subscriber)


    def removeSubscriber(self, subscriber):
        self.subscribers.remove(subscriber)


    def publish(self, payload):
        for subscriber in self.subscribers:
            if callable(subscriber):
                subscriber(payload)

