#!/usr/bin/env python3
"""Upload a binary to the MPU via UART bootloader."""
import serial, struct, sys, time

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <program.mpu> [serial_port]")
    sys.exit(1)

bin_file = sys.argv[1]
port = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyACM1"

prog = open(bin_file, "rb").read()
print(f"Uploading {len(prog)} bytes from {bin_file} to {port}...")

ser = serial.Serial(port, 115200)
time.sleep(0.2)

# Send length
ser.write(struct.pack("<I", len(prog)))
ser.flush()
time.sleep(0.1)

# Send in small chunks with pauses
CHUNK = 4
for i in range(0, len(prog), CHUNK):
    ser.write(prog[i:i+CHUNK])
    ser.flush()
    time.sleep(0.01)

time.sleep(0.1)
ser.close()
print("Upload complete.")
