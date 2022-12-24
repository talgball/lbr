/*
  mb1220.ino - Arduino-based version of the driver to operate an array of 
  Maxbotix MB1220 ultrasonic range sensors.

  Source provided here for reference only.  See p8x32lbr.py for details on how
  lbrsys processes the range information and provides it to the system.
  
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
*/

#define NUMBER_OF_SENSORS 5
#define SENSOR_TRIGGER_PW 25 // mb1220 is 20us min
// #define SENSOR_TIMEOUT 50000 // mb1220 pw up to 58*765us
#define SENSOR_TIMEOUT 100000 // mb1220 pw up to 58*765us
#define SPEED_OF_SOUND 58    // mb1220 returns round trip time (2*29us/cm)

typedef struct Sensor {
  const char *name;
  int ctrlPin;
  int pingPin;
  unsigned long distance;
}Sensor;

Sensor sensors[NUMBER_OF_SENSORS] = {
  {.name="Forward", .ctrlPin=12, .pingPin=13, .distance=50},
  {.name="Left",    .ctrlPin=0,  .pingPin=8, .distance=40},
  {.name="Right",   .ctrlPin=0,  .pingPin=4, .distance=30},
  {.name="Back",    .ctrlPin=0,  .pingPin=4, .distance=20},
  {.name="Bottom",  .ctrlPin=0,  .pingPin=0, .distance=10},
};

long deltat = 0;

void setup() {
  // put your setup code here, to run once:
  int i;
  
  Serial.begin(115200);

  for(i=0; i<NUMBER_OF_SENSORS; i++) {
    
    if(sensors[i].ctrlPin == 0){
      sensors[i].distance = 0;
      continue;
    }
    
    pinMode(sensors[i].ctrlPin, OUTPUT);
    pinMode(sensors[i].pingPin, INPUT);
    digitalWrite(sensors[i].ctrlPin, LOW);
  }

  delay(500); // mb1220 has 175ms startup cycle and might be in a 100ms ranging cycle.
  // prelim testing indicates 100ms ranging cycle is min instead of typical. 
}

void loop() {
  int i;
  long tnow = 0;

  tnow = millis();
  
  for(i=0; i<NUMBER_OF_SENSORS; i++) {
    
    if(sensors[i].ctrlPin == 0){
      continue;
    }
    
    sensors[i].distance = get_distance(&sensors[i]);
    delay(200); // not needed after we install the rest of the sensors
  }

  report_sensors(sensors, deltat);

  delay(50);
  deltat = millis() - tnow;
}

unsigned long get_distance(Sensor *s) {
  
  // Trigger a ping
  digitalWrite(s->ctrlPin, HIGH);
  delayMicroseconds(SENSOR_TRIGGER_PW);
  digitalWrite(s->ctrlPin, LOW); 

  // Read the ping
  s->distance = pulseIn(s->pingPin, HIGH, SENSOR_TIMEOUT) / SPEED_OF_SOUND;


  // delayMicroseconds(SENSOR_TRIGGER_PW);  // remove this line when "real" process above is enabled
 
  return(s->distance);
}

void report_sensors(Sensor *ss, long delta) {
  int i;

  Serial.print("{ \"Ranges\": { ");
  for(i=0; i<NUMBER_OF_SENSORS; i++) {
    Serial.print("\"");
    Serial.print(ss[i].name);
    Serial.print("\": ");
    Serial.print(ss[i].distance);
    Serial.print(", ");
  }
  Serial.print("\"Deltat\": ");
  Serial.print(delta);
  Serial.print("}}\r\n");
}
