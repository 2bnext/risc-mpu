# Project Notes (for Claude)

Context dump for future Claude Code sessions on this repo. Read this first before touching anything.

**This file should be kept up to date.** When you change the architecture, the toolchain, the layout, or learn a new gotcha, update the relevant section here in the same session. Future-you will thank present-you.

## What this project is

A handcrafted 32-bit soft-core CPU ("MPU") for the iCESugar 1.5 board (Lattice iCE40UP5K). It runs on real hardware and includes:

- A custom ISA with a single addressing-generation unit (AGU) shared by all instructions.
- A bootloader that loads programs over UART into SPRAM and then releases the CPU.
- A toolchain in Python: assembler, simulator, three high-level compilers (C / BASIC / Pascal), and a UART uploader.
- A small standard library written in MPU assembly.
- Documentation in `doc/` aimed at being readable as a booklet, plus per-tool reference pages in `doc/toolchain/`.

The project is at **v0.3**. A successor on the Alchitry Au (Artix-7) is planned for hardware FP, but this repo is the iCESugar version.

### Version history

**v0.3** (current) — ISA refinement, C preprocessor, hardware fixes.
- **ISA**: `call` and `jmp` now use the AGU — all addressing modes work (`call label`, `call r2`, `call [r2+4]`). `callr`/`jmpr` dropped. Branches are now PC-relative (16-bit signed offset). Total: **21 opcodes** (opcode 21 is free).
- **C compiler**: `#include "file"` with circular-include guard; `#define`/`#undef`/`#ifdef`/`#ifndef`/`#else`/`#endif`; `0b` binary literals; `_` digit separators in all numeric constants; function prototypes accepted (declaration without body); clean error messages instead of tracebacks; fixed sub-word array load bug (pre-clear clobbered the AGU base register).
- **Stdlib**: `sprintf(buf, fmt, ...)` — same format engine as printf, writes to a buffer.
- **Verilog**: ADC saturates at 4095 instead of wrapping to 0 at full scale; UART TX and LED MMIO address decode widened from `[3:0]` to `[7:0]` (GPIO/I²C writes no longer ghost-fire UART bytes or LEDs); GPIO pins remapped to P36–P46.
- **New files**: `ssd1306.h` (OLED driver), `bme280.h` (sensor driver), `stdlib.h` (function reference), `bme280displayed.c` (weather station on OLED), `adcpwm.c`, `ssd1306test.c`, `blink.c`.

**v0.2** — geometric math, soft-float bug fixes, new opcodes.
- ISA: added `asr` (opcode 19). `jmpr`/`callr` were introduced but later folded into AGU-based `jmp`/`call` in v0.3.
- Assembler: pseudo-ops (`jmp`, `push`, `pop`, `clr`, `ldi`), `r0` hiding, peephole rewriters.
- C compiler: function pointers, signed `>>` defaults to `asr`, struct/union/array support.
- Stdlib: 14 new geometric/math functions (`ftan`, `fatan`, `fasin`, `facos`, `fhypot`, `fdeg2rad`, `frad2deg`, `fmin`, `fmax`, `fclamp`, `fsign`, `flerp`, `ffloor`, `fceil`). Fixed critical bugs in `fsqrt` and `fatan2`.
- Verilog: `uart_tx` 16-byte FIFO. `flash.py` chunked upload (`--chunk=N --delay=MS`).
- Tests: `stdlibtest.c` (65 checks), `geomtest.c` (61 checks).

**v0.1** — first "finished" milestone. Working hardware, four language front-ends (asm/C/BASIC/Pascal), `.mpu` binary format.

## Repository layout

```
mpu/          Verilog: CPU, AGU, memory, UART, bootloader, top, I2C, ADC, PCF, build Makefile
toolchain/    Python: asm.py, sim.py, cc.py, basic.py, pas.py, flash.py, stdlib.asm
testing/      Sample programs (.asm hand-written, .c, .bas, .pas) and a Makefile chaining the toolchain
doc/          README/booklet-style docs:
              BOOKLET.md       — long-form beginner's guide
              ISA.md           — instruction set reference
              PERIPHERALS.md   — pinout + external-hardware reference for iCESugar 1.5
              CONVERSATIONS.md — saved chat logs (informal)
              CLAUDE.md        — this file (Claude's notes)
              toolchain/       — per-tool reference pages:
                                 asm.md, cc.md, basic.md, pas.md, sim.md, stdlib.md
```

`*.mpu` is gitignored, so compiled binaries don't show up in `git status`. Don't be alarmed when they vanish.

## Hardware layout

- **CPU**: 8 general-purpose 32-bit registers. `r0` is hardwired to 0; `r7` is the stack pointer (`sp`), initialised to `0x10000` on reset.
- **Memory**: two `SB_SPRAM256KA` blocks in parallel give a 64 KiB address space (`0x0000`–`0xFFFF`). Addresses above 16-bit wrap.
- **MMIO**:
  - `0xFFFF0000` UART TX data
  - `0xFFFF0004` UART TX status (bit 0 = busy) — **read with `ld.8`**, see gotchas
  - `0xFFFF0008` LED register (bits 0=G, 1=R, 2=B, active-high in software)
  - `0xFFFF0010` GPIO data
  - `0xFFFF0014` GPIO direction (1=output, 0=input)
  - `0xFFFF0018` I²C data (W=tx byte, R=last rx byte)
  - `0xFFFF001C` I²C cmd/status (W cmd bits `[0]start [1]stop [2]write [3]read [4]ack_send`, R `{ack_recv, busy}`)
  - `0xFFFF0020` ADC result (12-bit sigma-delta, latest sample)

## External components required by the peripherals

These are off-chip parts the user must wire up for each peripheral to actually work. The FPGA bitstream alone is not enough. The full pinout + wiring reference is [PERIPHERALS.md](PERIPHERALS.md); summary here:

- **UART** (`uart_tx`/`uart_rx`): none — handled by the on-board USB-serial bridge (ESP32-C3 running serialmon, exposed as `/dev/ttyACM1`).
- **LEDs**: none — on-board RGB LED.
- **GPIO** (`gpio[7:0]`): none required. Add series resistors / external pull-ups only if your specific application needs them. Pins are placeholder assignments in `mpu/mpu.pcf` — re-pin freely for whatever PMOD / header you actually use.
- **I²C** (`i2c_scl`, `i2c_sda`): two external pull-up resistors, **2.2 kΩ–10 kΩ** each, from SCL and SDA to Vcc (3.3 V). The iCE40's internal pull-up (`PULLUP=1` in `top.v`) is ~100 kΩ — not stiff enough for reliable I²C; treat it as belt-and-braces only. Most off-the-shelf I²C breakouts already include their own pull-ups.
- **Sigma-delta ADC** (`adc_in`, `adc_out`): a first-order RC charge-balancing network, all external:
  - `R1` ≈ 10 kΩ from `adc_out` pin to a summing node `S`.
  - `R2` ≈ 10 kΩ from the analog input (0–Vcc) to the same node `S`.
  - `C` ≈ 1–10 nF from `S` to GND.
  - `S` connects to `adc_in`.
  - `R1` and `R2` should be matched (1 % or better) for accuracy. The analog input must be bounded to 0–Vcc; clamp with diodes if not.
- **BME280** (optional, used by [testing/bme280demo.c](../testing/bme280demo.c) and the BASIC/Pascal ports): standard 3.3 V breakout. Wire VCC/GND, SDA/SCL to the I²C pins (which already need pull-ups, see above), and tie SDO to GND so the device responds at 7-bit address `0x76`.

### Memory map used by BASIC and the heap

```
0x10000  stack top (grows down)
0xF000   ~4 KiB stack reserve
0xE000   heap base (grows up via __halloc)
0x0000   code + globals + string literals (grows up)
```

C programs put locals on the stack, globals in a data section after code; the heap is only used by BASIC string concatenation and explicit `MALLOC`. Pascal has no heap.

## ISA in 30 seconds

All instructions are 32-bit. Every memory/ALU operation funnels through the AGU, which produces either an immediate or an effective address. Sub-word loads (`ld.8`, `ld.16`) **size-merge** into the destination register: only the low byte/halfword is overwritten, upper bits are preserved. This bites you if you forget to zero the destination first.

Branches compare an `rd` register against either a 3-bit immediate or another register, in `.8`/`.16`/`.32` widths. Branch targets are PC-relative (16-bit signed offset). `call` and `jmp` use the AGU, so they accept any addressing mode (label, register, memory-indirect).

21 native opcodes (0-20, slot 21 free):
- 0 NOP, 1 LD, 2 LDH, 3 ST
- 4 ADD, 5 SUB
- 6-11 BEQ/BNE/BLT/BGT/BLE/BGE
- 12 AND, 13 OR, 14 XOR, 15 SHL, 16 SHR
- 17 CALL (via AGU), 18 RET
- 19 ASR, 20 JMP (via AGU)

The full ISA is in [ISA.md](ISA.md).

## Toolchain

- **`toolchain/asm.py`** — two-pass assembler. Labels can be global (no leading dot) or local (`.foo`, scoped to the most recent global label). Reads `.asm`, writes `.mpu` binary. Documented in [toolchain/asm.md](toolchain/asm.md).
  - **Pseudo-instructions**: `clr[.sz] rD` → `ld.<sz> rD, r0` (default `.32`; `.8`/`.16` size-merge clears); `pop rN` → `ld.32 rN, [sp+=4]`; `push rN` → `sub.32 sp,#4 ; st.32 [sp], rN`; `ldi rD, #imm` → either `ld.32 rD, #imm` (if it fits in 20-bit signed) or `ld.32 rD, #low20 ; ldh rD, #high20` (otherwise). `push` and `ldi` are the variable-length pseudos, expanded by `expand_pseudos()` before pass 1; labels may be attached to either. `jmp` is a real opcode (20) using the AGU — not a pseudo any more. `to_pseudo_ops()` rewrites compiler-emitted `ld.<sz> rD, r0` as `clr.<sz> rD` and preserves the size suffix end-to-end. All three high-level compilers emit `ldi` for every numeric literal. There is no `mov`/`mv` pseudo — `ld.32 rD, rS` is already the canonical register-to-register move (AGU mode 00 makes the source register the operand).
  - **r0-implicit AGU shorthand**: anywhere `r0` would appear as the bookkeeping slot of an AGU operand it can be elided. `[sp+=4]` ≡ `[r0][sp+=4]`, `[r6++]` ≡ `[r0][r6+=1]`, `[sp+8]` ≡ `[r0][sp+8]`, `[reg]` ≡ `[r0][reg]` (mode 01). The verbose form is still accepted for compat, but nothing in the toolchain output emits it.
  - **Surface-syntax rewriters**: `to_pseudo_ops(asm_text)` rewrites compiler-style native sequences → push/pop/clr; `hide_r0(asm_text)` strips `[r0]` from AGU operands. Both are textual peepholes that produce semantically identical output. All three compilers run their generated asm through `to_pseudo_ops()` then `hide_r0()` before assembling and before writing the `-S` listing. `stdlib.asm` was rewritten with the same passes and now uses pseudo-ops and the r0-implicit shorthand directly.

- **`toolchain/sim.py`** — cycle-level simulator. `--trace` prints every instruction; `--max-cycles=N` (default 1,000,000) caps runaway loops. Stops with `Halted: max cycles` if the program loops forever (commonly because it reached the `__halt: jmp __halt` at the end). Includes a **fake BME280** at I²C address `0x76` so the bme280demo programs run end-to-end against a known reference (15 °C, 1013.25 hPa, 0 % RH). Documented in [toolchain/sim.md](toolchain/sim.md).

- **`toolchain/cc.py`** — C-like compiler. Documented in [toolchain/cc.md](toolchain/cc.md). Has `#include`, `#define`/`#ifdef`/`#ifndef`/`#endif`, `float`, `struct`, `union`, arrays, function pointers, `0b` binary literals, `_` digit separators, `>>` sign-aware (asr for signed, shr for unsigned). `*`/`/`/`%` lower to signed runtime calls. Outputs `.mpu` directly; pass `-S` to also keep the intermediate `.s`.

- **`toolchain/basic.py`** — Tiny BASIC compiler. Documented in [toolchain/basic.md](toolchain/basic.md). Heap, string vars, `MALLOC`/`PEEK`/`POKE`, `+`/`=`/`<>` on strings, `*` and `/` via runtime helpers. Has been extended over time with: hex literals (`0x..`), bitwise ops (`<<`, `>>`, `~`/`NOT`, `AND`/`OR` are bitwise), `SAR(x, n)` for arithmetic shift right, `SLEEP n`, the `I2C*` builtins, the `GPIO*` builtins, `SETLEDS n`, and `ADCREAD()`. The compiler emits `ld + ldh` for constants outside the 20-bit immediate range — without this, anything ≥ 524288 silently truncated (the bug that broke the BME280 port until it was found).

- **`toolchain/pas.py`** — Tiny Pascal compiler. Documented in [toolchain/pas.md](toolchain/pas.md). The big thing Pascal adds over BASIC is **real procedures and functions with value parameters and proper stack frames** — the same calling convention as `cc.py`. Pascal is case-insensitive (the tokenizer lowercases all identifiers) and has the same set of GPIO/I²C/ADC/LED/`sleep`/`peek`/`poke`/`sar` builtins as BASIC, plus `writeln`/`write`/`exit` as language built-ins. Function calls use a defer-and-replay trick: argument expressions are scanned to find their token ranges, then re-parsed in reverse to push right-to-left. A `temp_depth` counter on the compiler tracks expression-temp pushes so variable accesses through `[sp+offset]` stay correct when intermediates are sitting on top of the frame.

- **`toolchain/flash.py`** — uploads a `.mpu` to the bootloader over UART. Default port `/dev/ttyACM1`, 115200 baud. Prompts the user to press the S2 button (FPGA reset) before uploading; pass `--now` to skip the prompt when the board is already in bootloader state. Pass `--monitor` to keep the serial port open after upload and stream device output until Ctrl-C. Pass `--chunk=N --delay=MS` to tune the chunked upload pacing — default is 8 bytes per 1 ms chunk, which is reliable for 14 KB+ binaries but slow; raise the chunk size or lower the delay for faster small-binary uploads if your USB path can handle it. The chunked-send workaround exists because the bootloader has zero margin on back-to-back bytes at 115200 baud.

- **All toolchain scripts** (`asm.py`, `cc.py`, `basic.py`, `pas.py`, `sim.py`, `flash.py`) accept the input filename without an extension and append the obvious one (`.asm`/`.c`/`.bas`/`.pas`/`.mpu`). All three high-level compilers support `-S` to keep the intermediate `.s` file. All tools print a clean `error: input file not found` message and exit 1 instead of dumping a Python traceback when the input is missing.

- **`toolchain/stdlib.asm`** — appended automatically by `cc.py`, `basic.py`, and `pas.py`. Provides:
  - I/O: `__putc` (internal), `putchar`, `puts`, `printf` (`%d %x %s %c %%`), `sprintf`, `setleds`, `sleep`
  - GPIO: `gpio_set_dir`, `gpio_write`, `gpio_read`
  - I²C: `i2c_start`, `i2c_stop`, `i2c_write` (returns ACK), `i2c_read` (takes ACK polarity), `__i2c_wait` (internal busy spin)
  - ADC: `adc_read`
  - Math: `__mul`, `__div`, `__mod`, `__divmod` (all unsigned, shift-add/subtract)
  - String/heap: `__halloc`, `__strlen`, `__strcpy`, `__strcmp`, `__strcat`
  - Globals used by helpers: `_heap_ptr`, `_strcat_a/b/p`, `_S_empty`, `__printf_pow10`

## testing/Makefile

```
make foo.mpu     # foo.c | foo.bas | foo.pas | foo.asm -> foo.mpu (in one step)
make clean       # removes *.mpu
```

The current Makefile chains directly from source to `.mpu` — the compilers no longer write `.s` by default. There are four `%.mpu:` rules, one per source extension. Pick one source extension per program; don't mix.

The full set of canonical demo programs is:
- `hello.{asm,c,bas,pas}` — print "Hello!"
- `primes.{c,bas,pas}` — primes up to 1000
- `bme280demo.{c,bas,pas}` — read a BME280 over I²C and print compensated T/P/H

Each language version of a given demo produces identical output, which makes them useful regression tests when touching compiler internals.

## Calling convention

- Arguments are pushed right-to-left by the caller. After `call`, the stack looks like `[sp+0]=retaddr, [sp+4]=arg0, [sp+8]=arg1, …`.
- The return value comes back in `r1`.
- Caller cleans up the stack with `add sp, #4*nargs` after the `call`.
- Callees that need to preserve `r3`–`r6` save them by hand (`printf` is the main example).
- Pascal and C callees additionally save `r6` and reserve a local frame in their prologue:
  ```
  sub.32  sp, #4
  st.32   [sp], r6
  sub.32  sp, #<local_size>
  ```
  Stack inside such a callee: `[sp+0..L-4]` = locals (slot 0 = function result for Pascal `function`s), `[sp+L]` = saved r6, `[sp+L+4]` = ret addr, `[sp+L+8..]` = args.
- `r0` is the constant zero. Architecturally it's the bookkeeping slot in many AGU operand forms (e.g. the canonical pop is `ld.32 r1, [r0][sp+=4]`), but the assembler hides it behind shorthands (`[sp+=4]`, `[sp+8]`, `[r6++]`, etc.) — write the shorthand in any new asm.

## Key gotchas (lessons from past sessions)

- **`ld.8` / `ld.16` size-merge.** Never assume the upper bits of the destination are zero after a sub-word load. Either zero the destination first, or use `.32`. The BASIC compiler's `PEEK` does the zero-then-ld.8 dance for exactly this reason.
- **Match compare width to load width.** `printf`'s format-specifier dispatch was broken before because it loaded a byte with `ld.8` and then compared with `beq.32` against a 32-bit constant — the upper-bit garbage would intermittently hide matches. **The same rule applies to UART status reads**: all examples and the stdlib `__putc` use `ld.8 r4, 0xFFFF0004 ; bne.8 r4, #0, .wait`. If you write a new asm example that touches a sub-word MMIO register, use the matching `.8` size on both the load and the compare.
- **No reg-reg ALU.** All ALU ops go through the AGU, so to compute `r1 = r1 - r2` you need a stack roundtrip: `sub sp,#4; st [sp],r2; sub r1,[sp]; add sp,#4`. The compilers do this; if you write asm by hand, expect to push.
- **`mem_ready` must fire for every bus transaction.** Adding a new MMIO peripheral without driving `ready` deadlocks the CPU in the `S_MEM` state. The original UART/LED-IO handling had this bug.
- **Byte stores into SPRAM.** Until recently, `mem.v` hardwired `MASKWREN=4'b1111`, so `st.8`/`st.16` clobbered the entire word. Fixed by computing per-nibble masks and shifting `wdata` into the right lane in `top.v`. Anything that touches SPRAM with sub-word stores depends on the fixed bitstream — C uses byte buffers, BASIC uses byte stores via `__strcpy`/`POKE`.
- **20-bit immediates.** The `ld.32 r, #imm` encoding holds a 20-bit signed value (range −524288..524287). Constants outside that range need `ld + ldh` (low 20 bits then high 20 bits, the fields overlap by 8 bits). Both `cc.py` and `basic.py` (and now `pas.py`) emit this automatically. If you ever see a literal in a `.bas` or `.pas` file silently get the wrong value, this is the first thing to check — the BME280 BASIC port hit this exact bug.
- **`__mul` / `__div` / `__mod` are unsigned.** The shift-and-add multiply gives the right low-32 bits for two's-complement signed operands too (which is why BASIC and Pascal multiply works for negative numbers), but division of negative numbers will not. Use `sar(x, n)` for arithmetic right shift; for actual signed division, currently nothing — write the math to keep operands non-negative.
- **`__strcat` is not reentrant.** It uses globals `_strcat_a/b/p` as scratch. Don't call it recursively (BASIC doesn't, but worth knowing).
- **Pascal `temp_depth` accounting.** When adding a new operator codegen path in `pas.py`, every push that affects `sp` must increment `temp_depth` by 1, every matching pop must decrement it. Manual `sub.32 sp, #4` / `add.32 sp, #N` that aren't paired with `push_r1`/pop need explicit `self.temp_depth ±=` to compensate. The `*` / `div` / `mod` codegen got this wrong initially — symptom was that `square := x * x` wrote the result to local slot 4 instead of slot 0.
- **`*.mpu` is gitignored**, so binaries don't show up in `git status`. Don't be alarmed when they vanish.

## Hardware build flow (in `mpu/`)

```
make           # yosys -> nextpnr -> icepack
make flash     # icesprog mpu.bin
```

The user builds and flashes themselves — Claude can't run the OSS CAD Suite from this sandbox. After any change to `*.v` or the PCF, the bitstream must be rebuilt and reflashed. **Confirm before suggesting a bitstream rebuild** — the user does these manually and they take real time.

PCF pin notes worth remembering: `clk=35`, `uart_tx=4`, `uart_rx=6`, `led_g=41`, `led_r=40`, `led_b=39`, `gpio[0..3]=9..12`, `gpio[4..7]=19..23`, `i2c_scl=25`, `i2c_sda=26`, `adc_in=27`, `adc_out=28`, `btn_s2=18`. The serial bridge is an ESP32-C3 running serialmon firmware on GPIO4(TX)/GPIO5(RX), exposed as `/dev/ttyACM1` on the host. The full table is in [PERIPHERALS.md](PERIPHERALS.md).

## Testing in the sandbox

`python3 toolchain/sim.py prog.mpu` is the fast inner loop; the assembler and all three compilers run in a fraction of a second on small programs. The simulator's behaviour matches hardware **except** for:

- Real-time speed (`sleep` is essentially zero-cost in the sim).
- UART RX is not modelled — programs that try to read input block forever.
- The fake BME280 at address `0x76` is the only I²C device; nothing else is on the bus.
- The ADC always returns `0x800` (~ half-scale).
- Sub-word stores work correctly in the sim — historically this is where divergences hide. If something works in `sim.py` but not on the board, double-check sub-word memory ops and `mem_ready`.

A quick regression sweep when touching compiler internals:
```sh
cd testing
for prog in hello primes bme280demo; do
  for ext in c bas pas; do
    if [ -f $prog.$ext ]; then
      python3 ../toolchain/${ext/c/cc}*.py $prog.$ext >/dev/null && \
      python3 ../toolchain/sim.py $prog.mpu --max-cycles=200000000 | tail -3
    fi
  done
done
```

## Style

- The user prefers terse, direct explanations without preamble or trailing summaries. Don't restate what they just said.
- Don't add documentation/comments unless asked or unless the logic is genuinely non-obvious.
- Don't add defensive code for conditions that can't happen by design (see `feedback_no_defensive_code` in auto-memory).
- All instructions go through the AGU uniformly; do not add per-opcode operand decoding paths (`feedback_agu_consistency`).
- **Size suffix and AGU are mandatory for new opcodes.** When adding or modifying a real opcode or a pseudo-instruction: it must accept `.8` / `.16` / `.32` size suffixes (default `.32`) and respect size-merge semantics, AND route through the AGU wherever it has an operand. This is what makes every instruction inherit the full set of addressing modes for free. Pseudo-ops that wrap a sized opcode must propagate the size suffix through their expansion (e.g. `clr.16 r1` → `ld.16 r1, r0`); the textual peephole `to_pseudo_ops()` must capture the size group when matching and emit the matching size when rewriting. Exceptions where size genuinely doesn't apply: `nop`, `ret`, `call`, `jmp`, the branches (size selects compare width, not operand width), `ldh` (operates on a fixed bit field), `push`/`pop` (always 32-bit on the stack), `ldi` (immediates are always sign-extended to 32 bits, the assembler chooses one or two `ld`/`ldh` instructions instead).
- Confirm before risky/destructive actions; confirm before bitstream rebuilds since the user does those manually.
- **Keep this file (`doc/CLAUDE.md`) up to date.** When you add a feature, fix a gotcha, change the calling convention, or rename a tool, update the relevant section in the same session. Don't let it drift.
