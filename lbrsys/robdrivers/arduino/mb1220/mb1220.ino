/*
  mb1220.ino - Arduino-based version of the driver to operate an array of 
  Maxbotix MB1220 ultrasonic range sensors.

  Source provided here for reference only.  See p8x32lbr.py for details on how
  lbrsys processes the range information and provides it to the system.
  
__author__ = "Tal G. Ball"
__copyright__ = "Copyright (C) 2022, 2026 Tal G. Ball"
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
#define SENSOR_TRIGGER_PW 25    // mb1220 is 20us min
#define SENSOR_TIMEOUT 50000    // mb1220 pw up to 58*765us
#define SPEED_OF_SOUND 58       // mb1220 returns round trip time (2*29us/cm)

// Each sensor requires 99ms/range.  Min pulse width is 25cm * 58us/cm = 1,450us = 1.45ms.
// Inter sensor delay must be set such that each sensor in rotation is only triggered
// every 100ms at most, to cover the 99ms range and allow for any further echo dissipation.
// In a 4 sensor configuration, if each sensor times out, 4 * 50,000us = 200ms would occur between ranges of an
// individual sensor in the rotation, which is adequate.  However, if each sensor sees a minimum pulse of 
// 25cm * 58us/cm, and we go on to the next one, the first sensor could see a new reqest in 5.8ms (4*25*58us)
// We need a delay between sensors of at least 25-5.8 = 19.2ms so that each sensor sees at most one trigger
// every 100ms.  To give some margin, we'll assume 100ms / enabled sensor count = 25ms
// 
#define INTER_SENSOR_DELAY 25

typedef struct Sensor {
  const char *name;
  int ctrlPin;
  int pingPin;
  unsigned long distance;
  int enabled;
}Sensor;

Sensor sensors[NUMBER_OF_SENSORS] = {
  {.name="Forward", .ctrlPin=6,  .pingPin=7,  .distance=50, .enabled=1},  
  {.name="Left",    .ctrlPin=12, .pingPin=13, .distance=40, .enabled=1},
  {.name="Right",   .ctrlPin=4,  .pingPin=5,  .distance=30, .enabled=1},
  {.name="Back",    .ctrlPin=10, .pingPin=11, .distance=20, .enabled=1},
  {.name="Bottom",  .ctrlPin=0,  .pingPin=0,  .distance=10, .enabled=0},
};


long deltat = 0;
int control = 0;
int received = 0;


void setup() {
  // put your setup code here, to run once:
  int i;
  
  Serial.begin(115200);

  for(i=0; i<NUMBER_OF_SENSORS; i++) {
    
    if(sensors[i].ctrlPin == 0 || sensors[i].enabled == 0){
      //sensors[i].distance = 0;
      continue;
    }
    
    pinMode(sensors[i].ctrlPin, OUTPUT);
    pinMode(sensors[i].pingPin, INPUT);
    digitalWrite(sensors[i].ctrlPin, LOW);
  }

  delay(500); // mb1220 has 175ms startup cycle and might be in a 100ms ranging cycle.
}

void loop() {
  int i;
  long tnow = 0;

  if (Serial.available() > 0) {
    received = Serial.read();
    Serial.print("received: ");
    Serial.print((char)received);
    Serial.print("\n");

    if ((char)received == 'g') {
      control = 1;
      received = 0;
    }

    if ((char)received == 's') {
      control = 0;
      received = 0; 
    }
    
  }

  if (control == 1) {

    // Drain pending serial output before the timing-sensitive sensor scan
    // to minimize USB interrupt activity during pulseIn() measurements.
    Serial.flush();

    tnow = millis();

    for (i=0; i<NUMBER_OF_SENSORS; i++) {
      
      if (sensors[i].ctrlPin == 0 || sensors[i].enabled == 0) {
        continue;
      }
      
      sensors[i].distance = get_distance(&sensors[i]);
      delay(INTER_SENSOR_DELAY);
    }
  
    report_sensors(sensors, deltat);
  
    delay(50);
    deltat = millis() - tnow;
  }
}


unsigned long get_distance(Sensor *s) {
  unsigned long pulse;

  // Trigger a ping
  digitalWrite(s->ctrlPin, HIGH);
  delayMicroseconds(SENSOR_TRIGGER_PW);
  digitalWrite(s->ctrlPin, LOW);

  // Use pulseInLong() instead of pulseIn().  The ATmega32U4 handles USB
  // via software interrupts on the same chip.  pulseIn() counts tight
  // assembly loop iterations that are disrupted by USB interrupts,
  // causing missed pulses.  pulseInLong() uses micros() (hardware timer)
  // and tolerates interrupts.
  pulse = pulseInLong(s->pingPin, HIGH, SENSOR_TIMEOUT);
  if (pulse > 0) {
    s->distance = pulse / SPEED_OF_SOUND;
  }

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
