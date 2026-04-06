# icesugar-mpu

A 32-bit RISC processor with a custom instruction set, built from scratch in Verilog and running on an iCESugar 1.5 FPGA board (Lattice iCE40UP5K). The entire system — processor, memory, UART, bootloader, assembler, C compiler, and simulator — fits in about 1000 lines of Verilog and 1000 lines of Python.


## Architecture

- **32-bit fixed-width instructions** with a uniform encoding: 5-bit opcode, 3-bit register, 2-bit size, and a 20-bit payload
- **8 registers** (r0 hardwired to zero, r7 aliased as sp (stack pointer))
- **19 instructions**: LD, LDH, ST, ADD, SUB, AND, OR, XOR, SHL, SHR, 6 branches, CALL, RET, NOP
- **Address Generation Unit (AGU)** shared by 9 instructions, providing register-direct, immediate, absolute, indexed, indexed+offset, and post-increment addressing modes
- **5-stage state machine**: FETCH, DECODE, EXECUTE, MEM, WB
- **64 KB SPRAM** for program and data (unified memory)
- **Memory-mapped I/O**: UART TX/RX at `0xFFFF0000`, LED register at `0xFFFF0008`

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
  mpu.pcf        Pin constraints for iCESugar 1.5
  Makefile        Build with: make
```

## Toolchain

All tools are single-file Python scripts with no dependencies (except `pyserial` for upload).

```
toolchain/
  asm.py         Assembler: .asm -> .mpu
  cc.py          C compiler: .c -> .asm (subset of C)
  sim.py         Cycle-accurate simulator with optional trace output
  run.py         Uploads .mpu binaries to the board via UART
  stdlib.asm     Standard library (printf, putchar, puts, sleep, setleds)
```

### Quick start

```bash
# Assemble and run
python3 toolchain/asm.py testing/hello.asm
python3 toolchain/run.py testing/hello.mpu

# Compile C, assemble, and run
python3 toolchain/cc.py testing/printf.c
python3 toolchain/asm.py testing/printf.asm
python3 toolchain/run.py testing/printf.mpu

# Simulate without hardware
python3 toolchain/sim.py testing/hello.mpu
python3 toolchain/sim.py testing/hello.mpu --trace
```

### Build the FPGA bitstream

```bash
cd mpu
make            # synthesize + place & route + bitstream
make flash      # upload bitstream to iCESugar board
```

Requires [Yosys](https://github.com/YosysHQ/yosys), [nextpnr](https://github.com/YosysHQ/nextpnr), and [icestorm](https://github.com/YosysHQ/icestorm).

## Documentation

- **[doc/ISA.md](doc/ISA.md)** — Complete instruction set reference with encoding details and pipeline behavior
- **[doc/BOOKLET.md](doc/BOOKLET.md)** — *Programming the MPU*: a beginner's guide covering CPU history, hexadecimal, FPGAs, and hands-on assembly tutorials
- **[doc/stdlib.md](doc/stdlib.md)** — Standard library function reference

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
.wait:          ld.32   r2, 0xFFFF0004
                bne.8   r2, #0, .wait
                st.8    0xFFFF0000, r1
                ret

hello:          db      'Hello, world!\0'

                end
```
