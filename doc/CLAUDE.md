# Project Notes (for Claude)

Context dump for future Claude Code sessions on this repo. Read this first before touching anything.

## What this project is

A handcrafted 32-bit soft-core CPU ("MPU") for the iCESugar 1.5 board (Lattice iCE40UP5K). It runs on real hardware and includes:

- A custom ISA with a single addressing-generation unit (AGU) shared by all instructions.
- A bootloader that loads programs over UART into SPRAM and then releases the CPU.
- A toolchain in Python: assembler, simulator, C-like compiler, BASIC compiler, and a UART uploader.
- A small standard library written in MPU assembly.
- Documentation in `doc/` aimed at being readable as a booklet.

A successor project on the Alchitry Au (Artix-7) is planned for hardware FP, but this repo is the iCESugar version.

## Repository layout

```
mpu/          Verilog: CPU, AGU, memory, UART, bootloader, top, PCF, build Makefile
toolchain/    Python: asm.py, sim.py, cc.py, basic.py, flash.py, stdlib.asm
testing/      Sample programs (.asm hand-written, .c, .bas) and a Makefile chaining the toolchain
doc/          BOOKLET.md, ISA.md, stdlib.md, cc.md, basic.md, CLAUDE.md (this file)
```

## Hardware layout

- **CPU**: 8 general-purpose 32-bit registers. `r0` is hardwired to 0; `r7` is the stack pointer (`sp`), initialised to `0x10000` on reset.
- **Memory**: two `SB_SPRAM256KA` blocks in parallel give a 64 KiB address space (`0x0000`–`0xFFFF`). Addresses above 16-bit wrap.
- **MMIO**: `0xFFFF0000` UART TX, `0xFFFF0004` UART status, `0xFFFF0008` LED register (bits 0=G, 1=R, 2=B, active-high in software), `0xFFFF0010` GPIO data, `0xFFFF0014` GPIO direction (1=output, 0=input), `0xFFFF0018` I2C data (W=tx byte, R=last rx byte), `0xFFFF001C` I2C cmd/status (W cmd bits `[0]start [1]stop [2]write [3]read [4]ack_send`, R `{ack_recv, busy}`), `0xFFFF0020` ADC result (12-bit, latest sigma-delta sample).

## External components required by the peripherals

These are off-chip parts the user must wire up for each peripheral to actually work. The FPGA bitstream alone is not enough.

- **UART** (`uart_tx`/`uart_rx`): none — handled by the on-board USB-serial bridge.
- **LEDs**: none — on-board RGB LED.
- **GPIO** (`gpio[7:0]`): none required. Add series resistors / external pull-ups only if your specific application needs them.
- **I2C** (`i2c_scl`, `i2c_sda`): two external pull-up resistors, **2.2 kΩ–10 kΩ** each, from SCL and SDA to Vcc (3.3 V). The iCE40's internal pull-up (`PULLUP=1` in [top.v](../mpu/top.v)) is ~100 kΩ — not stiff enough for reliable I2C; treat it as belt-and-braces only.
- **Sigma-delta ADC** (`adc_in`, `adc_out`): a first-order RC charge-balancing network, all external:
  - `R1` ≈ 10 kΩ from `adc_out` pin to a summing node.
  - `R2` ≈ 10 kΩ from the analog input (0–Vcc) to the same summing node.
  - `C`  ≈ 1–10 nF from the summing node to GND.
  - The summing node connects to `adc_in`.
  - `R1` and `R2` should be matched (1 % or better) for accuracy. The analog input must be bounded to 0–Vcc; clamp with diodes if not.
- **BME280** (optional, used by [testing/bme280demo.c](../testing/bme280demo.c)): standard 3.3 V breakout. Wire VCC/GND, SDA/SCL to the I2C pins (which already need pull-ups, see above), and tie SDO to GND so the device responds at 7-bit address `0x76`.
- **Memory map used by BASIC**:
  ```
  0x10000  stack top (grows down)
  0xF000   ~4 KiB stack reserve
  0xE000   heap base (grows up)
  0x0000   code + globals + string literals (grows up)
  ```

## ISA in 30 seconds

All instructions are 32-bit. Every memory/ALU operation funnels through the AGU, which produces either an immediate or an effective address. Sub-word loads (`ld.8`, `ld.16`) **size-merge** into the destination register: only the low byte/halfword is overwritten, upper bits are preserved. This bites you if you forget to zero the destination first.

Branches compare an `rd` register against either a 3-bit immediate or another register, in `.8`/`.16`/`.32` widths.

The full ISA is in [ISA.md](ISA.md).

## Toolchain

- `toolchain/asm.py` — two-pass assembler. Labels can be global (no leading dot) or local (`.foo`, scoped to the most recent global label). Reads `.asm`, writes `.mpu` binary.
- `toolchain/sim.py` — cycle-level simulator. `--trace` for instruction trace, `--max-cycles=N` for longer runs. Stops with `Halted: max cycles` if the program loops forever (commonly because it reached the `__halt: jmp __halt` at the end).
- `toolchain/cc.py` — C-like compiler. Documented in [cc.md](cc.md). Notable: `/` and `%` lower to runtime calls (`__div`/`__mod`); there's no `*` natively in C output, but `__mul` exists in stdlib. No preprocessor, no float, no struct.
- `toolchain/basic.py` — Tiny BASIC compiler. Documented in [basic.md](basic.md). Heap, string vars, `MALLOC`/`PEEK`/`POKE`, `+`/`=`/`<>` on strings, `*` and `/` via runtime helpers.
- `toolchain/flash.py` — uploads a `.mpu` to the bootloader over UART. Default port `/dev/ttyACM1`, 115200 baud. Prompts the user to press the S2 button (FPGA reset) before uploading; pass `--now` to skip the prompt when the board is already in bootloader state.
- All toolchain scripts (`asm.py`, `cc.py`, `basic.py`, `sim.py`, `flash.py`) accept the input filename without an extension and append the obvious one (`.asm`/`.c`/`.bas`/`.mpu`/`.mpu`).
- `toolchain/stdlib.asm` — appended automatically by both `cc.py` and `basic.py`. Provides:
  - I/O: `__putc` (internal), `putchar`, `puts`, `printf` (`%d %x %s %c %%`), `setleds`, `sleep`
  - GPIO: `gpio_set_dir`, `gpio_write`, `gpio_read`
  - I2C: `i2c_start`, `i2c_stop`, `i2c_write` (returns ACK), `i2c_read` (takes ACK polarity)
  - Math: `__mul`, `__div`, `__mod`, `__divmod` (all unsigned, shift-add/subtract)
  - String/heap: `__halloc`, `__strlen`, `__strcpy`, `__strcmp`, `__strcat`
  - Globals used by helpers: `_heap_ptr`, `_strcat_a/b/p`, `_S_empty`, `__printf_pow10`

## testing/Makefile

```
make foo.mpu     # foo.c|foo.bas -> foo.s -> foo.mpu
make clean       # removes *.mpu and *.s
```

Compiler output uses **`.s`** (gcc convention) to distinguish it from hand-written **`.asm`** sources. The Makefile has `%.mpu: %.s` and `%.mpu: %.asm` rules so the same `make foo.mpu` target works for either kind of source. `%.s: %.c` and `%.s: %.bas` rules coexist; pick one source extension per program.

## Calling convention

- Arguments are pushed right-to-left by the caller. After `call`, the stack looks like `[sp+0]=retaddr, [sp+4]=arg0, [sp+8]=arg1, …`.
- The return value comes back in `r1`.
- Caller cleans up the stack with `add sp, #4*nargs` after the `call`.
- Callees that need to preserve `r3`–`r6` save them by hand (`printf` is the main example).
- `r0` is the constant zero, used as a base in many `[r0][reg+off]` AGU forms (e.g. `ld.32 r1, [r0][sp+=4]` is the canonical pop-into-r1).

## Key gotchas (lessons from past sessions)

- **`ld.8` / `ld.16` size-merge.** Never assume the upper bits of the destination are zero after a sub-word load. Either zero the destination first, or use `.32`. The BASIC compiler's `PEEK` does the zero-then-ld.8 dance for exactly this reason.
- **`beq.8` vs `beq.32` on a sub-word load.** `printf`'s format-specifier dispatch was broken before because it loaded a byte with `ld.8` and then compared with `beq.32` against a 32-bit constant — the upper-bit garbage would intermittently hide matches. Match the compare width to the load width.
- **No reg-reg ALU.** All ALU ops go through the AGU, so to compute `r1 = r1 - r2` you need a stack roundtrip: `sub sp,#4; st [sp],r2; sub r1,[sp]; add sp,#4`. The compilers do this; if you write asm by hand, expect to push.
- **`mem_ready` must fire for every bus transaction.** Adding a new MMIO peripheral without driving `ready` deadlocks the CPU in the `S_MEM` state. The original UART/LED-IO handling had this bug.
- **Byte stores into SPRAM.** Until recently, `mem.v` hardwired `MASKWREN=4'b1111`, so `st.8`/`st.16` clobbered the entire word. Fixed by computing per-nibble masks and shifting `wdata` into the right lane in `top.v`. C programs were unaffected only because their byte stores went to UART/LED MMIO, not SPRAM. Anything that touches SPRAM with sub-word stores depends on the fixed bitstream — C uses byte buffers and BASIC uses byte stores via `__strcpy`/`POKE`.
- **`__strcat` is not reentrant.** It uses globals `_strcat_a/b/p` as scratch. Don't call it recursively (BASIC doesn't, but worth knowing).
- **Stale `*.s` files.** Both compilers append the stdlib in a single `f.write`, so partial files shouldn't happen — but if you ever see `Error … invalid literal for int(): '__putc'`, the `.s` on disk is from an older compiler version; `make clean && make foo.mpu` fixes it.
- **`*.mpu` is gitignored**, so binaries don't show up in `git status`. Don't be alarmed when they vanish.

## Hardware build flow (in `mpu/`)

```
make           # yosys -> nextpnr -> icepack
make flash     # icesprog mpu.bin
```

The user builds and flashes themselves — Claude can't run the OSS CAD Suite from this sandbox. After any change to `*.v` or the PCF, the bitstream must be rebuilt and reflashed.

PCF pin notes worth remembering: `clk=35`, `uart_tx=4`, `uart_rx=6`, `led_g=41`, `led_r=40`, `led_b=39`. The serial bridge is an ESP32-C3 running serialmon firmware on GPIO4(TX)/GPIO5(RX), exposed as `/dev/ttyACM1` on the host.

## Testing in the sandbox

`python3 toolchain/sim.py prog.mpu` is the fast inner loop; both compilers and the assembler run in a fraction of a second on small programs. The simulator's behaviour matches hardware **except** for the byte-store bug (now fixed) — historically this is where divergences hide. If something works in `sim.py` but not on the board, double-check sub-word memory ops and `mem_ready`.

## Style

- The user prefers terse, direct explanations without preamble or trailing summaries. Don't restate what they just said.
- Don't add documentation/comments unless asked or unless the logic is genuinely non-obvious.
- Don't add defensive code for conditions that can't happen by design (see `feedback_no_defensive_code` in auto-memory).
- All instructions go through the AGU uniformly; do not add per-opcode operand decoding paths (`feedback_agu_consistency`).
- Confirm before risky/destructive actions; confirm before bitstream rebuilds since the user does those manually.
