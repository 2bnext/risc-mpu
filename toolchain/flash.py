#!/usr/bin/env python3
"""Upload a binary to the MPU via UART bootloader.

The bootloader has zero margin on back-to-back bytes at 115200 baud, so we
send in small chunks with a per-chunk delay. This is a kludge, not a real
flow-control protocol — large binaries and busy USB buses can still drop
bytes. If an upload fails, try smaller --chunk or larger --delay.
"""
import serial, struct, sys, time, os

args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = [a for a in sys.argv[1:] if a.startswith('--')]
skip_prompt = '--now' in flags
monitor = '--monitor' in flags

# Chunk tuning. 8 bytes / 1 ms = ~8 KB/s — reliable for ~14 KB binaries.
# Override with --chunk=N --delay=MS (larger = faster but less reliable).
chunk_size = 8
delay_ms = 1
for f in flags:
    if f.startswith('--chunk='):
        chunk_size = int(f.split('=')[1])
    elif f.startswith('--delay='):
        delay_ms = int(f.split('=')[1])

if len(args) < 1:
    print(f"Usage: {sys.argv[0]} [--now] [--monitor] [--chunk=N] [--delay=MS] <program.mpu> [serial_port]")
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

# Send length + program in small chunks with an inter-chunk delay.
payload = struct.pack("<I", len(prog)) + prog
delay_s = delay_ms / 1000.0
for i in range(0, len(payload), chunk_size):
    ser.write(payload[i:i + chunk_size])
    ser.flush()
    time.sleep(delay_s)
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
