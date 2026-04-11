# risc-mpu

A 32-bit RISC processor with a custom instruction set, built from scratch in Verilog and running on an iCESugar 1.5 FPGA board (Lattice iCE40UP5K). The entire system — processor, memory, UART, bootloader, assembler, C compiler, and simulator — fits in about 1000 lines of Verilog and 1000 lines of Python.

The ISA has a truly 68K feel, especially with the pseudo opcodes.

**The ISA and initial verilog files are 100% designed and created by me, without a.i.** Claude has at later stage been used for debugging, documentation and the toolchain so I could get my ideas implemented very rapidly.

There are microcontroller style peripherals: gpio, i2c, adc and a uart for monitoring.

## Architecture

- **32-bit fixed-width instructions** with a uniform encoding: 5-bit opcode, 3-bit register, 2-bit size, and a 20-bit payload
- **8 registers** — `r0` is hardwired to zero (the classic RISC trick), `r7` is aliased as `sp` (the stack pointer). The other six are general-purpose. Having `r0 = 0` available everywhere gives you a free zero immediate, an unconditional branch (`jmp target`), a register clear (`clr rD`), and a "no base / no index" placeholder inside every AGU operand — without burning an opcode bit on any of them.
- **22 instructions**: LD, LDH, ST, ADD, SUB, AND, OR, XOR, SHL, SHR, ASR, 6 branches, CALL, RET, JMPR, CALLR, NOP
- **Address Generation Unit (AGU)** shared by 9 instructions, providing register-direct, immediate, absolute, indexed, indexed+offset, and post-increment addressing modes
- **5-stage state machine**: FETCH, DECODE, EXECUTE, MEM, WB
- **64 KB SPRAM** for program and data (unified memory)
- **Memory-mapped I/O**: UART TX/RX at `0xFFFF0000`, LED register at `0xFFFF0008`, 8-bit GPIO at `0xFFFF0010`/`0xFFFF0014`, I²C master at `0xFFFF0018`/`0xFFFF001C`, sigma-delta ADC at `0xFFFF0020`

## Peripherals

| Block | MMIO | What you get | External hardware |
|---|---|---|---|
| **GPIO** | `0xFFFF0010` (data) / `0xFFFF0014` (direction) | 8 bidirectional pins, per-pin direction control. Outputs read back the driven value, inputs read the live pad state. | None required |
| **I²C master** | `0xFFFF0018` (data) / `0xFFFF001C` (cmd / status) | ~100 kHz I²C, 7-bit addressing, START / STOP / repeated-start / write / read with controllable ACK. The master blocks the CPU until each transaction completes via a `busy` bit. | 2.2 kΩ–10 kΩ pull-ups on SCL and SDA to 3.3 V |
| **Sigma-delta ADC** | `0xFFFF0020` | 12-bit single-ended ADC built from a 1-bit feedback loop closed by an external RC network. Conversion runs continuously; reading the register snapshots the latest count. | Two matched 10 kΩ resistors and a 1–10 nF capacitor (charge-balancing network) |

The standard library exposes all three as ordinary function calls — `gpio_set_dir`, `gpio_write`, `gpio_read`, `i2c_start`, `i2c_stop`, `i2c_write`, `i2c_read`, and `adc_read` — usable from C, BASIC, and Pascal. A complete worked example using the I²C master against a real BME280 sensor lives at [`testing/bme280demo.c`](testing/bme280demo.c) (and there are line-for-line ports in [`bme280demo.bas`](testing/bme280demo.bas) and [`bme280demo.pas`](testing/bme280demo.pas)).

## Hardware

The FPGA bitstream is synthesized with the fully open-source **Yosys** + **nextpnr** toolchain. Programs are uploaded at runtime over UART at 115,200 baud via a built-in bootloader — no FPGA re-synthesis needed to run new code.

```
mpu/
  top.v          Top-level: bootloader, MPU, UART, bus arbitration
  mpu.v          Processor core
  agu.v          Address Generation Unit
  mem.v          SPRAM interface (2x SB_SPRAM256KA)
  uart_tx.v      UART transmitter
  uart_rx.v      UART receiver
  bootloader.v   Loads programs from UART into SPRAM
  i2c.v          ~100 kHz I2C master peripheral
  mpu.pcf        Pin constraints for iCESugar 1.5
  Makefile        Build with: make
```

## Toolchain

All tools are single-file Python scripts with no dependencies (except `pyserial` for upload).

```
toolchain/
  asm.py         Assembler: .asm -> .mpu
  cc.py          C compiler: subset of C -> .mpu
  basic.py       Tiny BASIC compiler -> .mpu
  pas.py         Tiny Pascal compiler with real procedures/functions -> .mpu
  sim.py         Cycle-accurate simulator (--trace, --max-cycles, fake BME280 on the I²C bus)
  flash.py       Uploads .mpu binaries to the board via UART (--now skips the S2 prompt, --monitor opens a serial monitor after upload, --chunk=N and --delay=MS tune the upload pacing)
  stdlib.asm     Standard library (printf, putchar, puts, sleep, setleds, gpio_*, i2c_*, adc_read, ...)
```

All toolchain scripts accept an input filename without extension and assume the obvious one (`.asm`/`.c`/`.bas`/`.pas`/`.mpu`). Pass `-S` to `cc.py`, `basic.py`, or `pas.py` to keep the intermediate `.s` assembly file.

### Quick start

```bash
# Assemble and run
python3 toolchain/asm.py testing/hello.asm
python3 toolchain/flash.py testing/hello.mpu

# Compile C, assemble, and run
python3 toolchain/cc.py testing/printf.c
python3 toolchain/asm.py testing/printf.asm
python3 toolchain/flash.py testing/printf.mpu

# Simulate without hardware
python3 toolchain/sim.py testing/hello.mpu
python3 toolchain/sim.py testing/hello.mpu --trace
```

### Build the FPGA bitstream

Install OSS CAD Suite and activate the environment.

```bash
cd mpu
make            # synthesize + place & route + bitstream
make flash      # upload bitstream to iCESugar board
```

Requires [Yosys](https://github.com/YosysHQ/yosys), [nextpnr](https://github.com/YosysHQ/nextpnr), and [icestorm](https://github.com/YosysHQ/icestorm).

## Documentation

- **[doc/ISA.md](doc/ISA.md)** — Complete instruction set reference with encoding details and pipeline behavior
- **[doc/PERIPHERALS.md](doc/PERIPHERALS.md)** — Pinout, MMIO, and external-hardware reference for the iCESugar 1.5 (UART, LEDs, GPIO, I²C, ADC)
- **[doc/BOOKLET.md](doc/BOOKLET.md)** — *Programming the MPU*: a beginner's guide covering CPU history, hexadecimal, FPGAs, and hands-on assembly tutorials
- **[doc/toolchain/asm.md](doc/toolchain/asm.md)** — Assembler reference (syntax, labels, directives)
- **[doc/toolchain/cc.md](doc/toolchain/cc.md)** — C compiler reference
- **[doc/toolchain/basic.md](doc/toolchain/basic.md)** — BASIC compiler reference
- **[doc/toolchain/pas.md](doc/toolchain/pas.md)** — Pascal compiler reference
- **[doc/toolchain/sim.md](doc/toolchain/sim.md)** — Simulator reference
- **[doc/toolchain/stdlib.md](doc/toolchain/stdlib.md)** — Standard library function reference (UART, GPIO, I²C, ADC, LEDs, math helpers)

## Example

```
                ld.32   r6, #hello
.loop:
                ld.8    r1, [r6++]
                beq.8   r1, #0, stop
                call    output
                jmp     .loop

stop:           jmp     stop

output:
.wait:          ld.8    r2, 0xFFFF0004
                bne.8   r2, #0, .wait
                st.8    0xFFFF0000, r1
                ret

hello:          db      'Hello, world!\0'

                end
```
