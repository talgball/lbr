#!/usr/bin/python
"""
robauth.py - Module to manage api authorization tokens for robots.
# todo replace with service such as auth0 or use django or jwt
"""

__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2009-2020 Tal G. Ball"
__license__ = "Apache License, Version 2.0"
__version__ = "1.0"

import logging
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
from collections import OrderedDict
import hmac
from base64 import b64encode
from urllib.parse import quote

try:
    from secrets import token_urlsafe
except ImportError:
    def token_urlsafe(nbytes=None):
        random_bytes = os.urandom(nbytes)
        token = quote(b64encode(random_bytes).decode('utf-8'))
        return token


# setting the path here so that robauth.py can be
#    executed interactively from here
if __name__ == '__main__':
    sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    sys.path.insert(2, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from lbrsys.settings import tokenFile


DEFAULT_TOKEN_FILE = tokenFile
api_tokens = OrderedDict()


def load_api_tokens(token_file=DEFAULT_TOKEN_FILE):
    with open(token_file, "r") as tokenfp:
        for record in tokenfp.readlines():
            if record[0] == '#':
                continue

            record_split = record.split(':')
            if len(record_split) == 2:
                user = record_split[0].strip()
                token = record_split[1].strip()
                api_tokens[user] = token
            else:
                if record_split[0] != '':
                    print(("Invalid token record: %s" % record))
    return


def save_api_tokens(token_file=DEFAULT_TOKEN_FILE):
    with open(token_file, "w") as tokenfp:
        tokenfp.write("#\n")
        tokenfp.write("# Automatically generated api token file\n")
        tokenfp.write("#     manual edits will be lost\n")
        for t in api_tokens:
            tokenfp.write("%s: %s\n" % (t, api_tokens[t]))
    return


def save_single_token(user=None, token=None, token_file=DEFAULT_TOKEN_FILE):
    assert user is not None, "User required"
    assert token is not None, "Token required"
    with open(token_file, "a") as tokenfp:
        tokenfp.write("%s: %s\n" % (user, token))
    return


def make_user_token(user=None):
    token = token_urlsafe(32)
    api_tokens[user] = token
    save_single_token(user, token)
    return


def is_authorized(user=None, token=None):
    if len(api_tokens) == 0:
        load_api_tokens()

    if user and token and user in api_tokens:
        return hmac.compare_digest(token, api_tokens[user])
    else:
        return False

# todo delete user, delete manually for now
def delete_user(user=None):
    pass


if __name__ == "__main__":
    load_api_tokens()
    if len(sys.argv) >= 2:
        print(("Authorizing: %s" % sys.argv[1]))
        make_user_token(sys.argv[1])
    else:
        ut = input("UserToken: ")
        u, t = ut.split(':')
        print(f"Authorization: {is_authorized(u, t)}")
