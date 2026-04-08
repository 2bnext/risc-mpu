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

The complete list of mnemonics: `nop`, `ld`, `ldh`, `st`, `add`, `sub`, `and`, `or`, `xor`, `shl`, `shr`, `beq`, `bne`, `blt`, `bgt`, `ble`, `bge`, `call`, `ret`, plus the pseudo-instruction `jmp`.

`jmp target` is a pseudo for an unconditional branch — it expands to `beq.32 r0, #0, target` (since `r0` is hardwired to 0, the comparison is always true).

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

The full form is `[Rbase][Ridx+offset]`. Base, index, and offset are all optional in various combinations:

| Form                       | Effective address  | Mode | Notes                                |
|----------------------------|--------------------|------|--------------------------------------|
| `[Rbase]`                  | `Rbase`            | 01   | Plain indirect                       |
| `[Rbase][Ridx]`            | `Rbase + Ridx`     | 01   | Indexed                              |
| `[Rbase][Ridx+off]`        | `Rbase + Ridx+off` | 10   | Indexed with offset (no writeback)   |
| `[Rbase][Ridx+=off]`       | `Rbase + Ridx`     | 11   | Indexed; writes back `Ridx += off`   |
| `[Rbase][Ridx++]`          | `Rbase + Ridx`     | 11   | Post-increment by 1 (shorthand)      |
| `[Rbase][Ridx--]`          | `Rbase + Ridx`     | 11   | Post-decrement by 1 (shorthand)      |
| `[Rbase+=off]`             | `Rbase`            | 11   | Shorthand for `[r0][Rbase+=off]`     |
| `[Rbase++]` / `[Rbase--]`  | `Rbase`            | 11   | Shorthand for `[r0][Rbase+=±1]`      |

The offset is 12-bit signed (−2048 … 2047). Writeback updates the index register *after* the access — so `ld.8 r1, [r5++]` reads from `r5` and then increments `r5` by 1.

Idioms you'll see all over the codebase:

```asm
sub.32  sp, #4              ; \
st.32   [sp], r1            ; / push r1
ld.32   r1, [r0][sp+=4]     ;   pop into r1
ld.32   r1, [sp][r0+8]      ;   load arg from [sp+8]
ld.8    r1, [r5++]          ;   read byte and post-increment pointer
```

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
- **Cannot parse addressing mode** — usually a stray space or a missing bracket in something like `[r0][sp+=4]`.

## Limits

- 16-bit branch/call targets — programs must fit within the first 64 KiB of address space (which is the whole SPRAM anyway).
- 12-bit signed offsets in indexed addressing modes (−2048 … 2047).
- 20-bit signed immediates in `ld`/`add`/etc. (−524288 … 524287).
- No macros, no `.equ`, no `.org`, no expressions in operands beyond a bare integer or label.
- One source file at a time. To "include" the standard library, the C and BASIC compilers literally append `stdlib.asm` to their output before invoking the assembler.
