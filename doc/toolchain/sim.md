# MPU Simulator

`toolchain/sim.py` is a cycle-level Python simulator for the MPU. It executes the same `.mpu` binaries the bootloader uploads to the FPGA, models the same memory map, and behaves like the hardware closely enough that programs developed in the sim usually run unchanged on the board.

The simulator is the inner loop of MPU development: assemble or compile, run in `sim.py`, see the output, iterate. It is faster than reflashing and gives you a clean trace whenever you need one.

## Usage

```sh
python3 toolchain/sim.py program.mpu                    # run the program
python3 toolchain/sim.py program.mpu --trace            # print every instruction
python3 toolchain/sim.py program.mpu --max-cycles=10000000
python3 toolchain/sim.py program                        # .mpu extension is implied
```

If the input filename has no extension, `.mpu` is appended automatically — so the same shorthand the assembler and compilers accept works here too.

## What is simulated

- The CPU itself: all 8 registers, the program counter, the AGU's addressing modes, sub-word size-merging on `ld.8`/`ld.16`, post-increment/post-decrement, and every opcode the assembler emits.
- 64 KiB of RAM at addresses `0x0000`–`0xFFFF`. The program is loaded at address 0 on start, the rest is zeroed, and `sp` (`r7`) is initialised to `0x10000`.
- The MMIO peripherals at `0xFFFF0000` and above:
  - **UART TX** at `0xFFFF0000` — bytes written here are appended to the simulator's stdout. The status register at `0xFFFF0004` always reads "idle", so `__putc` never spins.
  - **LEDs** at `0xFFFF0008` (low three bits = green/red/blue).
  - **GPIO** at `0xFFFF0010` (data) / `0xFFFF0014` (direction). Outputs read back the value the program drove; inputs read 0.
  - **I²C** at `0xFFFF0018` / `0xFFFF001C`. The simulator implements the master controller and dispatches transactions to attached fake devices.
  - **ADC** at `0xFFFF0020`. Always returns `0x800` (~ half-scale).
- A built-in **fake BME280** at I²C address `0x76`, with calibration constants and raw ADC samples lifted from the Bosch datasheet appendix. Running `bme280demo.c`, `.bas`, or `.pas` against the simulator reproduces the ICAO standard atmosphere at sea level (15 °C, 1013.25 hPa, 0 % RH).

## What is not simulated

- **Real-time speed.** Each iteration of `sleep`'s busy-wait counts as one cycle, so a 30 ms sleep on hardware takes essentially zero time in the sim. If you need accurate timing for a peripheral, build it on the board.
- **UART RX.** There is no input. Programs that try to read from UART (the bootloader, for example) will block forever in the sim.
- **External I²C devices** other than the built-in BME280. Add a new class to `sim.py` if you want to model another sensor.
- **Hardware quirks.** Anything that depends on real propagation delay, metastability, or genuine ADC behaviour will not show up in the sim.

## Tracing

`--trace` prints one line per executed instruction:

```
PC=0x0040  op=ld.32 r1, #42                 r1 <- 0x0000002a
PC=0x0044  op=add.32 r1, #1                 r1 <- 0x0000002b
PC=0x0048  op=st.32  _counter, r1
```

Use this when you have a program that runs but produces the wrong answer — the trace will show you exactly which instruction wrote which value. For long-running programs the trace is very large; pipe it through `grep` or `head` and increase `--max-cycles` if needed.

## Cycle limit

`--max-cycles=N` caps the number of instructions executed (default 1,000,000). When the limit is hit, the simulator prints `Halted: max cycles (N) reached` to stderr and exits. This is the usual symptom of a program that has fallen into an infinite loop, including the canonical end-of-program `__halt: jmp __halt` that all compiled programs end with.

If you see the "max cycles" message even though you expected the program to finish, raise the limit:

```sh
python3 toolchain/sim.py longrun.mpu --max-cycles=50000000
```

## Halt and exit conditions

- A program "ends" by jumping to its own `__halt` label, which is just a tight self-loop. The cycle limit will then trigger.
- Reading from an unmapped address returns 0 silently.
- Writing to an unmapped address is silently ignored.
- The simulator never raises an exception on a malformed instruction — it executes it as best it can. If your output looks like nonsense, run with `--trace` and look for the first surprising line.

## Differences from hardware (worth knowing)

- Sub-word stores work correctly in the simulator. There was a hardware bug where SPRAM byte stores clobbered the entire word (the `mem.v`/`top.v` `MASKWREN` issue); the simulator never had this bug, so a program that touched SPRAM with `st.8`/`st.16` could pass the sim but fail on the board until the bitstream was fixed.
- The simulator runs as fast as Python lets it (a few million instructions per second on a desktop). The board runs at 12 MHz. Programs that "feel slow" in the sim because of `printf` debug output will be much slower on real hardware.
- I²C transactions complete instantly in the sim — the busy bit at `0xFFFF001C` always reads as 0.

## Example

```sh
cd testing
make primes.mpu
python3 ../toolchain/sim.py primes.mpu
```

Or, when something is misbehaving:

```sh
python3 ../toolchain/sim.py primes.mpu --trace 2>&1 | head -40
```
