"""
telemetry - module to provide utilities for processing telemetry data in applications
    Tal G. Ball April 20, 2019
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

import sys
if sys.version_info.major == 3:
    from functools import reduce

import pprint


class FindTelemetryKey(object):
    def __init__(self, dictionary, key):
        self.dictionary = dictionary
        self.key = key
        self.dpath = []
        self.k, self.value = self.findk(dictionary, key)
        self.dpath.reverse()

    def findk(self, d, k):
        """
        find key, k, in dictionary, d, if it exists at any level in a nested
            dictionary structure
        :param d: top level dictionary to search
        :param k: key to search
        :return: k and either the value of k if it exists or else None
        """
        # print("Searching for %s in %s" % (k, d))
        if k in d:
            self.dpath.append(k)
            return k, d[k]
        else:
            for key in d:
                if type(d[key]) == dict:
                    k, v = self.findk(d[key], k)
                    if v is not None:
                        self.dpath.append(key)
                        return k, v
        return k, None

    def lookup_key_in_sample(self, sample):
        seq = [sample] + self.dpath
        return reduce(lookup, seq)


def lookup(d, p):
    return(d[p[0]])


def compare(required, sample):
    """
    Compare two telemetry dictionaries to determine if sample meets requirements
    :param required: Dictionary containing rules to evaluate sample
    :param sample: Dictionary containing data to be evaluated
    :return: True if requirements met, otherwise False
    """

    results = {}
    matched = True
    for r in required:
        if r not in sample:
            matched = False
            results[r] = 'missing'
        else:
            results[r] = compare_field(required[r], sample[r])
            if not results[r]:
                matched = False

    return matched, results


def compare_field(rule, s):
    """
    Compare a rule-encoded value to a telemetry sample value
    :param rule: simple value, or string representing inequality or range
                    Whitespace required between comparison operator and value,
                    Whitespace optional for range operator ':'.
    :param s: sample to be tested
    :return: True if rule is met, otherwise False
    """

    try:
        s = float(s)
    except ValueError:
        pass

    try:
        rule = float(rule)
    except ValueError:
        pass

    if type(rule) == type(s):
        return s == rule

    elif type(rule) is str:
        rule_parsed = rule.split()

    else:
        rule_parsed = [rule]

    try:
        if len(rule_parsed) == 1:
            try:
                return s == float(rule_parsed[0])
            except ValueError:
                rp2 = rule_parsed[0].split(':')
                minvalue = float(rp2[0])
                maxvalue = float(rp2[1])
                return s >= minvalue and s <= maxvalue
        else:
            if rule_parsed[1] == ':':
                minvalue = float(rule_parsed[0])
                maxvalue = float(rule_parsed[2])
                return s >= minvalue and s <= maxvalue

            elif rule_parsed[0] == '<=':
                return s <= float(rule_parsed[1])

            elif rule_parsed[0] == '<':
                return s < float(rule_parsed[1])

            elif rule_parsed[0] == '>':
                return s > float(rule_parsed[1])

            elif rule_parsed[0] == '>=':
                return s >= float(rule_parsed[1])

            else:
                return False

    except Exception as e:
        return False


def findk(d, k):
    # print("Searching for %s in %s" % (k, d))
    if k in d:
        return k, d[k]
    else:
        for key in d:
            if type(d[key]) == dict:
                k, v = findk(d[key], k)
                if v is not None:
                    return k, v
    return k, None


if __name__ == "__main__":
    required = {'A':23, 'B':' < 42', 'C':'21.0', 'D':'10:20', 'E':'>= 12.7'}
    sample = {'B':25, 'C':21, 'D':15, 'E':12.8, 'F':'Something Extra'}

    m, r = compare(required, sample)
    assert m is False
    assert (r == {'A': 'missing', 'B': True, 'C': True, 'D': True, 'E': True}), str(r)
    print(m)
    pprint.pprint(r)

    sample['A'] = 23
    sample['C'] = 21
    m, r = compare(required, sample)
    assert m is True
    assert r == {'A': True, 'B': True, 'C': True, 'D': True, 'E': True}
    print(m)
    pprint.pprint(r)

    required['D'] = '10 : 20'
    m, r = compare(required, sample)
    assert m is True
    assert r == {'A': True, 'B': True, 'C': True, 'D': True, 'E': True}
    print(m)
    pprint.pprint(r)

    sample['D'] = 9
    m, r = compare(required, sample)
    assert m is False
    assert r == {'A': True, 'B': True, 'C': True, 'D': False, 'E': True}
    print(m)
    pprint.pprint(r)

    d = {'A': 1, 'B': {'C': {'X': 42}}}
    t = FindTelemetryKey(d, 'X')
    assert t.value == 42
    print(("Found: %s: %d" % ('X', t.value)))
    print(("dpath: %s" % t.dpath))
    print(("looking up %s in in %s\n\t" % (str(t.dpath), str(d))))

    z = t.lookup_key_in_sample(d)
    print(("The Answer is %d" % z))

    x = t.lookup_key_in_sample({'A': 1, 'B': {'C': {'X': 29}}})
    print(("Next sample is %d" % x))


    deepd = {'A': 1, 'B': {'C': {'D': {'E': {'F': {'G': {'H': {'I': {'X': 42}}}}}}}}}

    import timeit
    findk_total = timeit.timeit("t.lookup_key_in_sample(deepd)",
                                setup="from __main__ import FindTelemetryKey, lookup, deepd; \
                                t=FindTelemetryKey(deepd, 'X')",
                                number=100000)
    print(("Class approach: 100K tries: %.6f sec, %.1fus / try" % (findk_total, findk_total*10)))

    fkt = timeit.timeit("findk(deepd, 'X')",
                        setup="from __main__ import findk, deepd",
                        number=100000)
    print(("Function approach: 100K tries: %.6f sec, %.1fus / try" % (fkt, fkt*10)))
