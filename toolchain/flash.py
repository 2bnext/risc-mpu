#!/usr/bin/env python3
"""Upload a binary to the MPU via UART bootloader."""
import serial, struct, sys, time, os

args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = [a for a in sys.argv[1:] if a.startswith('--')]
skip_prompt = '--now' in flags
monitor = '--monitor' in flags

if len(args) < 1:
    print(f"Usage: {sys.argv[0]} [--now] [--monitor] <program.mpu> [serial_port]")
    sys.exit(1)

bin_file = args[0]
if '.' not in os.path.basename(bin_file):
    bin_file += '.mpu'
port = args[1] if len(args) > 1 else "/dev/ttyACM1"

try:
    prog = open(bin_file, "rb").read()
except FileNotFoundError:
    print(f"error: input file not found: {bin_file}", file=sys.stderr)
    sys.exit(1)

if not skip_prompt:
    input("Press S2 on the iCESugar to reset, then hit Return to upload... ")

print(f"Uploading {len(prog)} bytes from {bin_file} to {port}...")

ser = serial.Serial(port, 115200)
time.sleep(0.2)

# Send length followed by program in one go — bootloader consumes bytes
# at 1 cycle each (12 MHz) while UART delivers one every ~1040 cycles.
ser.write(struct.pack("<I", len(prog)) + prog)
ser.flush()
print("Upload complete.")

if monitor:
    print(f"Monitoring {port} (Ctrl-C to exit)...")
    try:
        while True:
            data = ser.read(ser.in_waiting or 1)
            if data:
                sys.stdout.write(data.decode('utf-8', errors='replace'))
                sys.stdout.flush()
    except KeyboardInterrupt:
        print()
    finally:
        ser.close()
else:
    ser.close()
