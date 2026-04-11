# MPU Assembler

`toolchain/asm.py` is a two-pass assembler for the MPU ISA. It reads `.asm` source and writes a flat binary `.mpu` file that the bootloader can upload directly.

For the instruction encoding itself, see [ISA.md](ISA.md). This document covers the source-level syntax the assembler accepts.

## Usage

```sh
python3 toolchain/asm.py program.asm                # writes program.mpu
python3 toolchain/asm.py program.asm out.mpu        # explicit output
python3 toolchain/asm.py --opcodes program.asm      # also print a listing
```

The Makefile in `testing/` chains things automatically:

```sh
make foo.mpu      # foo.asm -> foo.mpu
```

## Source format

One statement per line. Whitespace is mostly insignificant. Mnemonics, register names, and directives are case-insensitive; labels are case-sensitive.

```asm
; comments start with a semicolon and run to end of line
                ld.32   r1, #42         ; load immediate
                add.32  r1, #1
                st.32   _counter, r1
                jmp     .done
.done:          ret
```

## Labels

A label is a name followed by `:`, or any name appearing as the first word of a line whose second word is a recognised mnemonic or directive (the colon is optional).

- **Global labels** start with anything other than `.`. They live in a single global namespace.
- **Local labels** start with `.` and are scoped to the most recent global label. The same `.loop` can appear under several functions without colliding.

```asm
puts:
                sub.32  sp, #4
                st.32   [sp], r6
.loop:
                ld.8    r1, [r5++]
                beq.8   r1, #0, .done
                call    __putc
                jmp     .loop
.done:
                ret
```

References to a local label resolve relative to the enclosing global label. To reference a local label from a different scope, use the global form by name (or just use a global label).

## Number literals

```asm
ld.32 r1, #42       ; decimal
ld.32 r1, #0xFF     ; hex
ld.32 r1, #0b1010   ; binary
ld.32 r1, #-1       ; negative
```

## Mnemonics and sizes

Most data-touching instructions take a `.8`, `.16`, or `.32` size suffix:

```asm
ld.8   r1, [r2]
ld.16  r1, [r2]
ld.32  r1, [r2]
st.8   [r2], r1
add.32 r1, #1
beq.8  r1, #0, .done
```

The complete instruction list — the assembler accepts both real opcodes and a small set of pseudo-instructions that expand to one or two real ones. The pseudos make hand-written code read like a conventional ISA without changing what the CPU executes; they're called out in the table.

| Mnemonic     | Kind   | Description                                               |
|--------------|--------|-----------------------------------------------------------|
| `nop`        | real   | No operation                                              |
| `ld`         | real   | Load (register, immediate, memory — uses the AGU)         |
| `ldh`        | real   | Load high 20 bits (combine with `ld` for 32-bit constants)|
| `st`         | real   | Store to memory                                           |
| `add`        | real   | Add operand to `rd`                                       |
| `sub`        | real   | Subtract operand from `rd`                                |
| `and`        | real   | Bitwise AND                                               |
| `or`         | real   | Bitwise OR                                                |
| `xor`        | real   | Bitwise XOR                                               |
| `shl`        | real   | Logical shift left                                        |
| `shr`        | real   | Logical shift right                                       |
| `asr`        | real   | Arithmetic shift right (sign-fill)                        |
| `beq` / `bne` / `blt` / `bgt` / `ble` / `bge` | real | Conditional branches (compare `rd` against reg or `#imm`) |
| `call`       | real   | Push return address, jump (16-bit absolute target)        |
| `callr rD`   | real   | Indirect call: push PC+4, jump to address in `rD`         |
| `ret`        | real   | Pop return address, jump to it                            |
| `jmpr rD`    | real   | Indirect jump: PC = `rD` (no stack push)                  |
| `clr rD`     | pseudo | Clear `rD` to zero. Expands to `ld.<sz> rD, r0`. Size suffix is honoured (`.8`/`.16` clear only the low byte/halfword and preserve the upper bits — same size-merge behaviour as `ld`). |
| `ldi rD, #imm` | pseudo | Load any 32-bit constant into `rD`. Expands to a single `ld.32` if the value fits in the 20-bit signed immediate, otherwise an `ld.32` + `ldh` pair. |
| `jmp target` | pseudo | Unconditional branch. Expands to `beq.32 r0, #0, target`. |
| `push rN`    | pseudo | Two instructions: `sub.32 sp, #4` then `st.32 [sp], rN`. A label on a `push` line points at the first expanded instruction. |
| `pop rN`     | pseudo | One instruction: `ld.32 rN, [sp+=4]`.                     |

```asm
                push    r6              ; save r6
                clr     r1              ; r1 = 0
                ld.32   r2, r3          ; r2 = r3 (register-to-register move)
                ldi     r3, #0xDEADBEEF ; load any 32-bit constant
                call    do_thing
                pop     r6              ; restore r6
                jmp     done
```

`push` and `ldi` are the variable-length pseudos: `push` always becomes two instructions, `ldi` becomes one if the value fits in the 20-bit signed immediate (−524288 … 524287) and two otherwise. Both are expanded by `expand_pseudos()` before pass 1, so labels resolve correctly. `ldi` accepts label and expression operands as well as numeric literals; for non-literal operands it conservatively reserves two instruction slots.

## Operands

### Register direct

```asm
ld.32 r1, r2        ; mode 00 — register-to-register move (load value of r2 into r1)
add.32 r1, r2       ; r1 += r2 (no — see below)
```

**Important:** the operand register is read through the AGU. For ALU ops the operand is a *memory operand*, so `add.32 r1, r2` is `r1 += mem[r2]`, not `r1 += r2`. To compute `r1 += r2` register-to-register you need a stack roundtrip:

```asm
sub.32  sp, #4
st.32   [sp], r2
add.32  r1, [sp]
add.32  sp, #4
```

`ld.32 r1, r2` works as a register move because the load *uses* the AGU's immediate-mode output as the value to write.

### Immediate

```asm
ld.32 r1, #42
add.32 r1, #-1
ld.32 r1, #_some_label   ; label address as immediate
```

Immediates are 20-bit sign-extended (range −524288 … 524287). The `ldh` (load high) instruction can be used in tandem with `ld` to construct full 32-bit immediates if you need values outside that range.

### Absolute address

A bare label or numeric literal (no `#`, no `[]`) is treated as an absolute address. The CPU loads/stores from/to that address directly.

```asm
ld.8  r4, 0xFFFF0004      ; read UART status (busy flag)
st.32 _counter, r1        ; store r1 at the address of _counter
```

### Memory addressing modes

The full form is `[Rbase][Ridx+offset]`. Both `Rbase` and `Ridx` can be `r0` (the constant zero) — the assembler accepts a number of shorthands that elide an explicit `r0`, and you should always use the shorthand in human-written code:

| Form                       | Effective address  | Mode | Notes                                  |
|----------------------------|--------------------|------|----------------------------------------|
| `[Rbase]`                  | `Rbase`            | 01   | Plain indirect                         |
| `[Rbase][Ridx]`            | `Rbase + Ridx`     | 01   | Indexed                                |
| `[Rbase][Ridx+off]`        | `Rbase + Ridx+off` | 10   | Indexed with offset (no writeback)     |
| `[Rbase][Ridx+=off]`       | `Rbase + Ridx`     | 11   | Indexed; writes back `Ridx += off`     |
| `[Rbase][Ridx++]`          | `Rbase + Ridx`     | 11   | Post-increment by 1 (shorthand)        |
| `[Rbase][Ridx--]`          | `Rbase + Ridx`     | 11   | Post-decrement by 1 (shorthand)        |
| `[Rreg+off]`               | `Rreg + off`       | 10   | Shorthand for `[r0][Rreg+off]`         |
| `[Rreg+=off]`              | `Rreg`             | 11   | Shorthand for `[r0][Rreg+=off]`        |
| `[Rreg++]` / `[Rreg--]`    | `Rreg`             | 11   | Shorthand for `[r0][Rreg+=±1]`         |

The offset is 12-bit signed (−2048 … 2047). Writeback updates the index register *after* the access — so `ld.8 r1, [r5++]` reads from `r5` and then increments `r5` by 1.

Idioms you'll see all over the codebase:

```asm
push    r1                  ; sp -= 4 ; mem[sp] = r1
pop     r1                  ; r1 = mem[sp] ; sp += 4
ld.32   r1, [sp+8]          ; load argument from [sp+8]
ld.8    r1, [r5++]          ; read byte and post-increment pointer
```

Because `r0` is hardwired to zero, anywhere `r0` would appear inside the brackets you can just leave it out — the assembler inserts it for you. The verbose two-bracket form (e.g. `[r0][sp+=4]`) is still accepted, but the high-level compilers and the standard library no longer emit it.

## Branches

```asm
beq.8   r1, #0, .done       ; branch if low byte of r1 == 0
bne.32  r1, r2, .loop       ; branch if r1 != r2
blt.32  r1, #10, .small     ; branch if r1 < 10  (signed)
```

The branch comparand can be a 3-bit immediate (`#0` … `#7`) or a register. The `.8`/`.16`/`.32` suffix sets the comparison width — sub-word forms mask the operands to that width before comparing, which avoids the size-merge gotcha that bites loads.

The branch target is a 16-bit absolute address. Both labels and integer literals work as targets.

## Directives

### `db` — define bytes

```asm
hello: db 'Hello, world!\n', 0x00
table: db 0x01, 0x02, 0x03, 0x04
mixed: db "MPU", 0
```

`db` accepts string literals (single or double quoted, with `\0 \n \r \t \\` escapes) and comma-separated numeric byte values, in any combination. The data is placed inline at the current address. **Be careful**: `db` does not align — the next instruction may end up unaligned, and the assembler will silently break things if you don't pad. Conventionally, put `db` directives at the *end* of the program, after any `jmp __halt`.

### `end`

Marks the end of assembly. Anything after it is ignored. Both `cc.py` and `basic.py` emit it as the last line of their generated `.s`.

## Listing output

`--opcodes` prints a one-line listing per source line, including the assembled hex word, the address, and the source. Useful for sanity-checking instruction encoding by hand.

```
0000: 06000004  beq.32 r0, #0, 0x4         jmp __start
0004: 1A000000  ret
...
```

## Errors

Error messages include the source line number and the offending instruction:

```
Error on line 56: Unknown label: __mod
  call    __mod
```

The most common causes:

- **Unknown label** — usually a typo, a missing definition, or a stale `.s` that was generated before the symbol existed (re-run the compiler).
- **Invalid literal for int()** — same root cause: a label name appearing where a number was expected, because the label wasn't found in the table.
- **Cannot parse addressing mode** — usually a stray space or a missing bracket in something like `[sp+=4]`.

## Limits

- 16-bit branch/call targets — programs must fit within the first 64 KiB of address space (which is the whole SPRAM anyway).
- 12-bit signed offsets in indexed addressing modes (−2048 … 2047).
- 20-bit signed immediates in `ld`/`add`/etc. (−524288 … 524287).
- No macros, no `.equ`, no `.org`, no expressions in operands beyond a bare integer or label.
- One source file at a time. To "include" the standard library, the C and BASIC compilers literally append `stdlib.asm` to their output before invoking the assembler.
