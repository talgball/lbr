#
# NOT CURRENTLY IN USE
# robtelemetry.py
#
#   Facilities to implement gathering and broadcasting of telemetry data,
#   directly or indirectly to external processes and services
#
#   inputList - dictionary containing 
#       name, type, incoming queue, frequency to publish - for each input
#
#   outputList -
#       name, type, publisher - for each output
#       publishers need to decide how to deal with each payload
#           and provide thier own transport mechanisms
#
#   type is the key linking element from inputs to outputs, i.e.
#       every input of a type is published to every output of the same type
#
#   It is assumed that the input and output lists are relatively short such
#   that the n2 behavior from multiplying the lengths of the lists still
#   implies a small number of operations

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


import time
from time import time as robtimer
import json
import threading
import multiprocessing


class RobTelemetry:
    def __init__(self,comQ,inputList=[],outputList=[]):
        self.comQ   = comQ
        self.iL     = inputList
        self.oL     = outputList

        self.minLoopTime = 0.500

        self.goThread = threading.Thread(target=self.go,
                                         name='Telemetry Thread',
                                         args=())

        self.goThread.setDaemon(True)

        

    def addInput(self,newInput):
        self.iL.append(newInput)

    def delInput(self,targetInput):
        if targetInput in self.iL:
            self.iL.remove(targetInput)

    def addOutput(self,newOutput):
        self.oL.append(newOutput)

    def delOutput(self,targetOutput):
        if targetOutput in self.oL:
            self.oL.remove(targetOutput)

    
    def go(self):
        while True:
            loopStartTime = robtimer()

            if not self.comQ.empty():
                command = self.comQ.get_nowait()

                if command == "Shutdown":
                    break

                if len(command) == 2:
                    try:
                        c = eval("self.%s" % command[0])
                        p = command[1]
                        c(p)
                    except:
                        raise
                
            for i in self.iL:
                payload = None
                if not i['queue'].empty():
                    payload = i['queue'].get_nowait()
                if payload:
                    for o in self.oL:
                        if i['type'] == o['type']:
                            if True: # replace with timing logic
                                o['publisher'](payload,o['queue'])
                            
            elapsedTime = robtimer() - loopStartTime
            if self.minLoopTime > elapsedTime:
                time.sleep(self.minLoopTime - elapsedTime)

            self.end()

    def end(self):
        pass

def testPublisher(payload,oq):
    oq.put(payload)
            
if __name__ == '__main__':
    cq = multiprocessing.JoinableQueue()
    iq = multiprocessing.JoinableQueue()
    oq = multiprocessing.JoinableQueue()
    
    t = RobTelemetry(cq)
        
    im = {'name':"i1",'type':1,'queue':iq,'pfreq':5}
    t.addInput(im)

    om = {'name':"o1",'type':1,'publisher':testPublisher, 'queue':oq}
    om2 = {'name':'o2','type':1,'publisher':testPublisher,'queue':oq}
    t.addOutput(om)
    t.addOutput(om2)
    
    t.goThread.start()
    
    #cq.put(("addOutput",om2)) - creates JoinableQueue inhertiance issue

    iq.put("test message")
    iq.put("test message 2")
    iq.put("end")

    while True:
        m = oq.get()
        print("message is %s" % m)
        if m == "end":
            break
        
    cq.put("Shutdown")
    

    
