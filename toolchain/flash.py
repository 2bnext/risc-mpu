#!/usr/bin/env python3
"""Upload a .mpu program to the iCESugar MPU.

Default: upload over UART into SPRAM (volatile — lost on power-off).
Use --persist to write to the on-board SPI flash instead, so the program
runs straight from power-on.

UART upload:
    flash.py program.mpu
    flash.py program.mpu --now --monitor --chunk=16 --delay=1

Persistent flash:
    flash.py --persist program.mpu       (write program to SPI flash @ 0x100000)
    flash.py --erase                     (clear the persist magic → UART only)

Flash format at offset 0x100000:
    4 bytes  magic 'MPU1'
    4 bytes  length (little-endian uint32, <= 64 KiB)
    N bytes  program
"""
import serial, struct, sys, time, os, subprocess

MAGIC = b'MPU1'
FLASH_OFFSET = 0x100000


def flag(flags, name):
    return name in flags


def flag_value(flags, prefix, default=None, cast=int):
    for f in flags:
        if f.startswith(prefix):
            return cast(f.split('=', 1)[1])
    return default


def run_icesprog(path):
    cmd = ['icesprog', '-o', f'0x{FLASH_OFFSET:x}', path]
    print('running:', ' '.join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(r.returncode)


def do_persist(mpu_file):
    with open(mpu_file, 'rb') as f:
        prog = f.read()
    if len(prog) > 0x10000:
        print(f"error: program too large ({len(prog)} bytes, max 64 KiB)",
              file=sys.stderr)
        sys.exit(1)
    image = MAGIC + struct.pack('<I', len(prog)) + prog
    # Write the image next to the .mpu file so it can be inspected.
    img_path = mpu_file.rsplit('.', 1)[0] + '.img'
    with open(img_path, 'wb') as f:
        f.write(image)
    print(f"persisting {mpu_file} ({len(prog)} bytes program, "
          f"{len(image)} bytes image -> {img_path}) at flash offset 0x{FLASH_OFFSET:x}")
    run_icesprog(img_path)
    print("done. Power-cycle or press S2 to run.")


def do_erase():
    # Any non-magic bytes disable the flash path.
    erase_path = '/tmp/mpu_erase.bin'
    with open(erase_path, 'wb') as f:
        f.write(b'\x00\x00\x00\x00')
    run_icesprog(erase_path)
    print(f"erased magic at 0x{FLASH_OFFSET:x} — bootloader will fall back to UART")


def do_uart_upload(mpu_file, port, chunk_size, delay_ms, skip_prompt, monitor):
    try:
        prog = open(mpu_file, "rb").read()
    except FileNotFoundError:
        print(f"error: input file not found: {mpu_file}", file=sys.stderr)
        sys.exit(1)

    if not skip_prompt:
        input("Press S2 on the iCESugar to reset, then hit Return to upload... ")

    print(f"Uploading {len(prog)} bytes from {mpu_file} to {port}...")

    ser = serial.Serial(port, 115200)
    time.sleep(0.2)

    # Send length + program in small chunks with an inter-chunk delay.
    # The bootloader has zero margin back-to-back at 115200 baud, so we
    # pace the upload in chunks. Tune with --chunk / --delay.
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


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if flag(flags, '--erase'):
        do_erase()
        return

    if len(args) < 1:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    mpu_file = args[0]
    if '.' not in os.path.basename(mpu_file):
        mpu_file += '.mpu'

    if flag(flags, '--persist'):
        if not os.path.exists(mpu_file):
            print(f"error: input file not found: {mpu_file}", file=sys.stderr)
            sys.exit(1)
        do_persist(mpu_file)
        return

    port = args[1] if len(args) > 1 else "/dev/ttyACM1"
    chunk_size = flag_value(flags, '--chunk=', default=8)
    delay_ms = flag_value(flags, '--delay=', default=1)
    skip_prompt = flag(flags, '--now')
    monitor = flag(flags, '--monitor')
    do_uart_upload(mpu_file, port, chunk_size, delay_ms, skip_prompt, monitor)


if __name__ == '__main__':
    main()
