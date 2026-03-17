#!/usr/bin/env python3
"""Direct serial test for range sensors - bypasses lbrsys driver.
Sends 'g' to start ranging, collects data for DURATION seconds, sends 's' to stop.
Reports any zero readings (excluding Bottom sensor).
"""

import serial
import time
import json
import sys

PORT = '/dev/ttyACM0'
BAUD = 115200
DURATION = 300

ser = serial.Serial(PORT, BAUD, bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                    timeout=1)
time.sleep(0.5)  # let port settle

# Flush any stale data
ser.reset_input_buffer()

# Start ranging
ser.write(b'g')
print(f"Ranging started. Collecting for {DURATION} seconds...")

start = time.time()
total_reports = 0
zero_counts = {}  # sensor_name -> count
all_sensors = set()

try:
    while time.time() - start < DURATION:
        line = ser.readline()
        if not line:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"  [non-JSON] {line[:120]}")
            continue

        total_reports += 1
        if total_reports == 1:
            print(f"  First report: {data}")
        # Structure: {"Ranges":{"Forward":-1,"Bottom":-1,"Left":-1,"Right":-1,"Back":-1,"Deltat":0}}
        ranges = data.get('Ranges', {})
        for sensor, value in ranges.items():
            if sensor == 'Deltat':
                continue
            all_sensors.add(sensor)
            if sensor == 'Bottom':
                continue
            if value == 0:
                zero_counts[sensor] = zero_counts.get(sensor, 0) + 1
                elapsed = time.time() - start
                print(f"  [{elapsed:5.1f}s] ZERO: {sensor} in {ranges}")

        if total_reports % 100 == 0:
            elapsed = time.time() - start
            print(f"  [{elapsed:5.1f}s] {total_reports} reports collected...")

finally:
    # Stop ranging
    ser.write(b's')
    time.sleep(0.2)
    ser.close()

print(f"\n{'='*60}")
print(f"Results after {DURATION}s ({total_reports} reports):")
print(f"Sensors seen: {sorted(all_sensors)}")
if zero_counts:
    print("ZERO readings detected (excluding Bottom):")
    for sensor in sorted(zero_counts):
        pct = 100.0 * zero_counts[sensor] / total_reports
        print(f"  {sensor}: {zero_counts[sensor]}/{total_reports} ({pct:.1f}%)")
else:
    print("No zero readings detected (excluding Bottom).")
print(f"{'='*60}")
