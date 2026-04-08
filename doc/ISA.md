# MPU Instruction Set Architecture

## Overview

- 32-bit fixed-width instructions, little-endian
- 8 general-purpose 32-bit registers (r0-sp)
- r0 is hardwired to zero
- sp is the stack pointer by convention (initialized to 0x10000)
- 32-bit program counter
- 5-stage state machine: FETCH, DECODE, EXECUTE, MEM, WB

## Registers

| Register | Convention                               |
|----------|------------------------------------------|
| r0       | Always zero (hardwired, writes ignored)  |
| r1-r6    | General purpose                          |
| sp       | Stack pointer (initialized to 0x10000)   |

### Why r0 is hardwired to zero

`r0` reading as a constant zero is a classic 1980s RISC trick (MIPS, SPARC, RISC-V all do this) and it's the single most load-bearing decision in the MPU's design. It does five distinct jobs that would otherwise each need their own opcode bit or instruction:

1. **Free zero immediate.** Anywhere an instruction takes a register source, you can use `r0` to mean "zero" without burning an instruction to load it.
2. **Register clear.** `ld.32 rD, r0` is "set rD to zero" in one instruction. The assembler exposes this as the `clr rD` pseudo.
3. **Unconditional branch.** `beq.32 r0, #0, target` is always taken because `0 == 0` is always true. The assembler exposes this as `jmp target`.
4. **"No base" / "no index" placeholder in AGU operands.** The AGU's two-bracket form is `[Rbase][Ridx+offset]`. Anywhere you don't want a base or don't want an index, you put `r0` and the address arithmetic just works (`0 + something = something`). This is why `[r0][sp+=4]` is the canonical pop, `[r0][r6+=1]` is the canonical post-increment, and `[r2][r0+8]` is the canonical struct-field load.
5. **Discard sink.** Writes to `r0` are silently ignored, so you can target it when you need an instruction's *side effect* (e.g. address computation, future flag updates) without producing a value you care about.

The assembler hides `r0` in cases (3) and (4) — `jmp`, `[sp+=4]`, `[r6++]`, `[sp+8]`, `[r2+8]` are all the same hardware encodings as the verbose forms, just typed without the redundant `r0`. But it's still architecturally there in every operand, and understanding *why* r0 is in those slots is the key to reading the encoded form when you're staring at a hex dump.

## Memory Map

| Address Range              | Description                              |
|----------------------------|------------------------------------------|
| 0x0000_0000 - 0x0000_FFFF | SPRAM (64KB)                             |
| 0xFFFF_0000                | UART TX data (write byte)                |
| 0xFFFF_0004                | UART TX status (read, bit 0 = busy)      |
| 0xFFFF_0008                | LED register (bits [2:0] = G, R, B)      |
| 0xFFFF_0010                | GPIO data (8 bidirectional pins)         |
| 0xFFFF_0014                | GPIO direction (1 = output, 0 = input)   |
| 0xFFFF_0018                | I²C data (W = tx byte, R = last rx byte) |
| 0xFFFF_001C                | I²C cmd / status                         |
| 0xFFFF_0020                | ADC sample (12-bit sigma-delta)          |

## Instruction Format

All instructions are 32 bits wide.

```
 31    27 26  24 23 22 21 20 19                  0
+--------+------+-----+--+--+--------------------+
| opcode |  rd  | size|rv|ai|      payload        |
+--------+------+-----+--+--+--------------------+
   5 bit   3 bit  2 b  1  1       20 bits
```

| Field     | Bits    | Description                                           |
|-----------|---------|-------------------------------------------------------|
| opcode    | [31:27] | Instruction (5 bits, 0-31)                            |
| rd        | [26:24] | Destination/source register (3 bits, r0-sp)           |
| size      | [23:22] | Operand/result size                                   |
| reg_value | [21]    | 0 = register addressing, 1 = immediate/absolute       |
| addr_imm  | [20]    | When reg_value=1: 0 = absolute addr, 1 = immediate   |
| payload   | [19:0]  | Operand data (20 bits)                                |

### Size Suffixes

| Bits | Suffix | Type               |
|------|--------|--------------------|
| 00   | .8     | unsigned 8-bit     |
| 01   | .16    | unsigned 16-bit    |
| 10   | .32    | unsigned 32-bit    |

## Addressing Modes (AGU)

The Address Generation Unit decodes the payload for LD, ST, ADD, SUB, AND, OR, XOR, SHL, SHR.

### Immediate / Absolute (reg_value = 1)

| addr_imm | Mode      | Syntax     | Description                              |
|----------|-----------|------------|------------------------------------------|
| 1        | Immediate | #value     | Operand is the literal value             |
| 0        | Absolute  | address    | Operand is loaded from memory address    |

The 20-bit payload is sign-extended to 32 bits.

### Register Modes (reg_value = 0)

Payload layout:

```
 19   17 16 15 14  12 11              0
+-------+-----+------+----------------+
|  base | mode| index|     offset     |
+-------+-----+------+----------------+
  3 bit  2 bit  3 bit    12 bits
```

| Mode | Syntax                    | Operand                           | Writeback                   |
|------|---------------------------|-----------------------------------|-----------------------------|
| 00   | Rbase                     | value of Rbase (register direct)  | none                        |
| 01   | [Rbase][Ridx]             | mem[Rbase + Ridx]                 | none                        |
| 10   | [Rbase][Ridx + offset]    | mem[Rbase + Ridx + sign_ext(off)] | none                        |
| 11   | [Rbase][Ridx += offset]   | mem[Rbase + Ridx]                 | Ridx += sign_ext(offset)    |

Mode 00 is register direct: the operand is the register value itself, no memory access. This enables register-to-register operations (e.g. `ld.32 r1, r2`, `add.32 r1, r3`).

Mode 11 computes the address before the writeback. The index register is updated after the memory operation completes.

### Assembler shorthands (r0 hiding)

`r0` is hardwired to zero, so any AGU operand that uses `r0` as a bookkeeping slot can be written without it. The assembler accepts both forms and produces identical encodings, but the shorthand is the convention used everywhere in the toolchain output, the standard library, and the example code in this document. **Write the shorthand in any new asm.**

| Shorthand     | Hardware form    | Effective address                  | Mode |
|---------------|------------------|------------------------------------|------|
| `[Rreg]`      | `[Rreg][r0]`     | `mem[Rreg]`                        | 01   |
| `[Rreg+off]`  | `[r0][Rreg+off]` | `mem[Rreg + sign_ext(off)]`        | 10   |
| `[Rreg+=off]` | `[r0][Rreg+=off]`| `mem[Rreg]`, then `Rreg += off`    | 11   |
| `[Rreg++]`    | `[r0][Rreg+=1]`  | `mem[Rreg]`, then `Rreg += 1`      | 11   |
| `[Rreg--]`    | `[r0][Rreg+=-1]` | `mem[Rreg]`, then `Rreg -= 1`      | 11   |

Combined with the `push`, `pop`, `mov`, `clr`, and `jmp` pseudo-instructions, the surface syntax of MPU assembly never needs to mention `r0` at all. A 68K-style function prologue reads:

```asm
my_func:
                push    r6                  ; save r6
                ld.32   r1, [sp+8]          ; load arg from caller's frame
                ld.8    r2, [r5++]          ; *p++ idiom
                pop     r6                  ; restore r6
                ret
```

Architecturally, every one of those instructions still goes through the AGU with `r0` filling the unused base/index slot — but you never have to type it.

## Branch Payload Format

Branch instructions (BEQ, BNE, BLT, BGT, BLE, BGE) use a different payload layout:

```
 19    18  16 15                 0
+----+------+--------------------+
|r/i | cmp  |      target        |
+----+------+--------------------+
 1 b   3 bit      16 bits
```

| Field       | Bits    | Description                                        |
|-------------|---------|----------------------------------------------------|
| reg_or_imm  | [19]    | 0 = compare against register, 1 = 3-bit immediate  |
| cmp_operand | [18:16] | Register select (r0-sp) or immediate (0-7)         |
| target      | [15:0]  | Branch target address (16-bit, covers full 64KB)    |

The size suffix affects comparison: `.8` compares lower 8 bits (sign-extended), `.16` lower 16 bits, `.32` full 32-bit. All comparisons are signed.

## Instruction Index

The MPU has 19 native opcodes. The assembler also accepts six pseudo-instructions (`mov`, `clr`, `ldi`, `jmp`, `push`, `pop`) that expand to one or two native instructions; the CPU never sees them, but they're how you should write assembly by hand. Both kinds appear in the alphabetical reference below — the table here groups them by function.

### Data movement

| Mnemonic     | Opcode      | Description                                              |
|--------------|-------------|----------------------------------------------------------|
| `ld`           | 1           | Load (immediate, register, absolute, or memory)          |
| `ldh`          | 2           | Load high 20 bits (combine with `ld` for 32-bit consts)  |
| `st`           | 3           | Store rd to memory                                       |
| `mov rD, rS`   | pseudo      | Register-to-register move (`ld.32 rD, rS`)               |
| `clr rD`       | pseudo      | Clear rD to zero (`ld.32 rD, r0`)                        |
| `ldi rD, #imm` | pseudo (×1–2) | Load any 32-bit constant; one `ld.32` if it fits in 20 bits, else `ld.32` + `ldh` |
| `push rN`      | pseudo (×2) | Decrement sp, store rN                                   |
| `pop rN`       | pseudo      | Load rN from sp, increment sp                            |

### Arithmetic

| Mnemonic | Opcode | Description                         |
|----------|--------|-------------------------------------|
| `add`    | 4      | Add operand to rd                   |
| `sub`    | 5      | Subtract operand from rd            |

### Bitwise

| Mnemonic | Opcode | Description    |
|----------|--------|----------------|
| `and`    | 12     | Bitwise AND    |
| `or`     | 13     | Bitwise OR     |
| `xor`    | 14     | Bitwise XOR    |

### Shift

| Mnemonic | Opcode | Description                         |
|----------|--------|-------------------------------------|
| `shl`    | 15     | Logical shift left (zero-fill)      |
| `shr`    | 16     | Logical shift right (zero-fill)     |

### Branches

| Mnemonic     | Opcode | Description                                    |
|--------------|--------|------------------------------------------------|
| `beq`        | 6      | Branch if equal                                |
| `bne`        | 7      | Branch if not equal                            |
| `blt`        | 8      | Branch if less than (signed)                   |
| `bgt`        | 9      | Branch if greater than (signed)                |
| `ble`        | 10     | Branch if less than or equal (signed)          |
| `bge`        | 11     | Branch if greater than or equal (signed)       |
| `jmp target` | pseudo | Unconditional jump (`beq.32 r0, #0, target`)   |

### Subroutines

| Mnemonic | Opcode | Description                                    |
|----------|--------|------------------------------------------------|
| `call`   | 17     | Push return address (PC+4) onto sp, jump       |
| `ret`    | 18     | Pop return address from sp, jump to it         |

### Control

| Mnemonic | Opcode | Description    |
|----------|--------|----------------|
| `nop`    | 0      | No operation   |

## Instruction Reference

Listed alphabetically, with native and pseudo-instructions interleaved. The opcode number for native instructions is shown in the **Encoding** line of each entry.

### ADD

**Encoding:** `00100 | rd | size | rv | ai | payload` (opcode 4)

Add the operand to rd and store the result in rd. Uses the full AGU to decode the operand. Writes to r0 are silently discarded.

**Pipeline:**

- Immediate and register-direct modes compute the result and write to rd in EXECUTE. No MEM or WB stages needed.
- Memory modes read the operand from memory (EXECUTE → MEM), then compute `rd + mem_rdata` and write the result in WB.

**Operation:**

```
rd = size_mask(rd + operand)
PC = PC + 4
```

Where `operand` is resolved by the AGU: a register value, sign-extended 20-bit immediate, or a value loaded from memory at the effective address.

**Size behavior:** The result is truncated to the width specified by the size suffix before being written to rd. Upper bits are zeroed:

- `.8`: result is masked to bits [7:0], upper 24 bits cleared. The result wraps at 255.
- `.16`: result is masked to bits [15:0], upper 16 bits cleared. The result wraps at 65535.
- `.32`: full 32-bit result, no truncation.

For memory operands, the size suffix also controls the memory read width.

**Examples:**

```
add.32 r1, r2               ; r1 = r1 + r2 (register-register, mode 00)
add.32 r1, #1               ; r1 = r1 + 1 (immediate)
add.32 r1, #-1              ; r1 = r1 + 0xFFFFFFFF = r1 - 1 (negative immediate)
add.8  r1, #1               ; r1 = (r1 + 1) & 0xFF (8-bit addition, wraps at 256)
add.16 r1, #1               ; r1 = (r1 + 1) & 0xFFFF (16-bit addition)
add.32 r1, [r2]             ; r1 = r1 + mem.32[r2] (memory indirect)
add.32 r1, [r2][r3]         ; r1 = r1 + mem.32[r2 + r3] (indexed)
add.32 r1, [r2][r3+8]       ; r1 = r1 + mem.32[r2 + r3 + 8] (indexed+offset)
add.32 r1, [r6+=4]          ; r1 = r1 + mem.32[r6], then r6 += 4 (post-increment)
add.32 r1, 0x100            ; r1 = r1 + mem.32[0x100] (absolute)
```

**Notes:**

- There is no carry flag or overflow detection. Use branch instructions to check for overflow if needed.
- `add.32 r1, #-N` is equivalent to `sub.32 r1, #N` for small N.
- `add.8 r1, #1` with r1 = 0xFF produces r1 = 0x00 (wraps to zero).

---

### AND (Bitwise AND)

**Encoding:** `01100 | rd | size | rv | ai | payload` (opcode 12)

Bitwise AND the operand with rd and store the result in rd. Uses the full AGU to decode the operand. Writes to r0 are silently discarded.

**Pipeline:** Identical to ADD — immediate/register-direct in EXECUTE, memory operands through MEM → WB.

**Operation:**

```
rd = size_mask(rd & operand)
PC = PC + 4
```

**Size behavior:** The result is truncated to the width specified by the size suffix before being written to rd. Upper bits are zeroed:

- `.8`: result is masked to bits [7:0], upper 24 bits cleared.
- `.16`: result is masked to bits [15:0], upper 16 bits cleared.
- `.32`: full 32-bit result, no truncation.

For memory operands, the size suffix also controls the memory read width.

**Examples:**

```
and.32 r1, #0xFF            ; r1 = r1 & 0xFF (mask lower byte)
and.8  r1, #0x0F            ; r1 = (r1 & 0x0F) & 0xFF (8-bit result)
and.32 r1, r2               ; r1 = r1 & r2 (register-register)
and.32 r1, [r2]             ; r1 = r1 & mem.32[r2] (memory indirect)
and.32 r1, [r2][r3]         ; r1 = r1 & mem.32[r2 + r3] (indexed)
and.32 r1, [r2][r3+8]       ; r1 = r1 & mem.32[r2 + r3 + 8] (indexed+offset)
and.32 r1, [r6+=4]          ; r1 = r1 & mem.32[r6], then r6 += 4 (post-increment)
and.32 r1, 0x100            ; r1 = r1 & mem.32[0x100] (absolute)
```

**Notes:**

- Useful for masking, clearing bits, and testing bit patterns.
- `and.8 r1, #0xFF` is a no-op on the lower byte but clears the upper 24 bits (the size mask zeroes them).
- The 20-bit immediate is sign-extended, so `#0xFF` becomes `0x000000FF` and `#-1` becomes `0xFFFFFFFF`.

---

### BEQ (Branch if Equal)

**Encoding:** `00110 | rd | size | r/i | cmp[2:0] | target[15:0]` (opcode 6)

Branch to the 16-bit target address if rd equals the compare operand. Does **not** use the AGU — the payload uses the branch format instead.

**Pipeline:** Completes in EXECUTE. The comparison is evaluated combinationally and PC is set to either the branch target or PC + 4. No MEM or WB stages.

**Operation:**

```
if (sized(rd) == sized(cmp_operand)):
    PC = zero_ext(target16)
else:
    PC = PC + 4
```

**Size behavior:** The size suffix determines how the comparison is performed. Before comparing, both rd and the compare operand are truncated and **sign-extended** from the specified width:

- `.8`: both values are sign-extended from bits [7:0] to 32 bits, then compared.
- `.16`: both values are sign-extended from bits [15:0] to 32 bits, then compared.
- `.32`: full 32-bit comparison, no truncation.

**Compare operand:** The `r/i` bit (payload bit 19) selects the compare source:

- `r/i = 0`: compare against a register. `cmp[2:0]` selects r0–sp.
- `r/i = 1`: compare against a 3-bit unsigned immediate (0–7). The immediate is zero-extended to 32 bits before the size-based sign extension is applied.

**Branch target:** The 16-bit target field (payload bits [15:0]) is zero-extended to 32 bits. This covers the full 64KB SPRAM address space (0x0000–0xFFFF).

**Examples:**

```
beq.32 r1, #0, .done        ; branch to .done if r1 == 0
beq.32 r1, r2, .match       ; branch to .match if r1 == r2
beq.8  r1, #0, .end         ; branch if low byte of r1 is 0 (sign-extended comparison)
beq.32 r0, #0, .always      ; always branches (r0 is always 0, 0 == 0)
```

**Notes:**

- `beq.32 r0, #0, target` is the canonical unconditional jump, exposed as the `jmp` pseudo-instruction.
- The immediate range is 0–7 only. To compare against larger values, load the value into a register and use register comparison.
- The target is an absolute address, not a PC-relative offset.

---

### BGE (Branch if Greater or Equal)

**Encoding:** `01011 | rd | size | r/i | cmp[2:0] | target[15:0]` (opcode 11)

Branch to the 16-bit target address if rd is **greater than or equal to** the compare operand, using **signed** comparison. Payload uses the branch format. Does not use the AGU.

**Pipeline:** Completes in EXECUTE. No MEM or WB stages.

**Operation:**

```
if (signed(sized(rd)) >= signed(sized(cmp_operand))):
    PC = zero_ext(target16)
else:
    PC = PC + 4
```

**Size behavior:** Same as other branches — truncate, sign-extend, then signed compare.

**Compare operand:** Register (r/i=0) or 3-bit immediate 0–7 (r/i=1).

**Examples:**

```
bge.32 r1, #0, .positive    ; branch if r1 >= 0 (non-negative)
bge.32 r1, r2, .ge          ; branch if r1 >= r2 (signed)
bge.8  r1, #1, .has_data    ; branch if low byte of r1 (signed) >= 1
```

**Notes:**

- `bge.32 r1, #0, target` is the standard "branch if non-negative" idiom.

---

### BGT (Branch if Greater Than)

**Encoding:** `01001 | rd | size | r/i | cmp[2:0] | target[15:0]` (opcode 9)

Branch to the 16-bit target address if rd is **greater than** the compare operand, using **signed** comparison. Payload uses the branch format. Does not use the AGU.

**Pipeline:** Completes in EXECUTE. No MEM or WB stages.

**Operation:**

```
if (signed(sized(rd)) > signed(sized(cmp_operand))):
    PC = zero_ext(target16)
else:
    PC = PC + 4
```

**Size behavior:** Same as other branches — truncate, sign-extend, then signed compare.

**Compare operand:** Register (r/i=0) or 3-bit immediate 0–7 (r/i=1).

**Examples:**

```
bgt.32 r1, r2, .bigger      ; branch if r1 > r2 (signed)
bgt.32 r1, #0, .positive    ; branch if r1 > 0 (strictly positive)
bgt.8  r1, #3, .high        ; branch if low byte of r1 (signed) > 3
```

---

### BLE (Branch if Less or Equal)

**Encoding:** `01010 | rd | size | r/i | cmp[2:0] | target[15:0]` (opcode 10)

Branch to the 16-bit target address if rd is **less than or equal to** the compare operand, using **signed** comparison. Payload uses the branch format. Does not use the AGU.

**Pipeline:** Completes in EXECUTE. No MEM or WB stages.

**Operation:**

```
if (signed(sized(rd)) <= signed(sized(cmp_operand))):
    PC = zero_ext(target16)
else:
    PC = PC + 4
```

**Size behavior:** Same as other branches — truncate, sign-extend, then signed compare.

**Compare operand:** Register (r/i=0) or 3-bit immediate 0–7 (r/i=1).

**Examples:**

```
ble.32 r1, #7, .small       ; branch if r1 <= 7 (signed)
ble.32 r1, r2, .not_greater ; branch if r1 <= r2 (signed)
```

---

### BLT (Branch if Less Than)

**Encoding:** `01000 | rd | size | r/i | cmp[2:0] | target[15:0]` (opcode 8)

Branch to the 16-bit target address if rd is **less than** the compare operand, using **signed** comparison. Payload uses the branch format. Does not use the AGU.

**Pipeline:** Completes in EXECUTE. No MEM or WB stages.

**Operation:**

```
if (signed(sized(rd)) < signed(sized(cmp_operand))):
    PC = zero_ext(target16)
else:
    PC = PC + 4
```

**Size behavior:** Both operands are truncated to the specified width and sign-extended to 32 bits, then compared as signed integers.

**Compare operand:** Register (r/i=0) or 3-bit immediate 0–7 (r/i=1).

**Examples:**

```
blt.32 r1, #5, .small       ; branch if r1 < 5 (signed)
blt.32 r1, r2, .less        ; branch if r1 < r2 (signed)
blt.8  r1, #0, .negative    ; branch if low byte of r1 is negative (bit 7 set)
```

**Notes:**

- All branch comparisons are signed. There is no unsigned less-than branch. To perform unsigned comparisons, use appropriate shifts or masks before comparing.
- With `.8` size, the value 0x80 in the low byte is interpreted as −128.

---

### BNE (Branch if Not Equal)

**Encoding:** `00111 | rd | size | r/i | cmp[2:0] | target[15:0]` (opcode 7)

Branch to the 16-bit target address if rd does **not** equal the compare operand. Payload uses the branch format. Does not use the AGU.

**Pipeline:** Completes in EXECUTE. No MEM or WB stages.

**Operation:**

```
if (sized(rd) != sized(cmp_operand)):
    PC = zero_ext(target16)
else:
    PC = PC + 4
```

**Size behavior:** Same as BEQ — both operands are truncated to the specified width and sign-extended to 32 bits before comparison.

**Compare operand:** Same as BEQ — register (r/i=0) or 3-bit immediate 0–7 (r/i=1).

**Examples:**

```
bne.8  r2, #0, .wait        ; branch if low byte of r2 != 0 (UART busy loop)
bne.32 r1, r2, .loop        ; branch if r1 != r2
bne.32 r1, #0, .nonzero     ; branch if r1 is not zero
bne.16 r1, #7, .next        ; branch if low 16 bits of r1 (sign-extended) != 7
```

**Notes:**

- Commonly used for polling loops: read a status register, branch back while the busy bit is nonzero.

---

### CALL (Call Subroutine)

**Encoding:** `10001 | --- | -- | - | - | payload[19:0]` (opcode 17)

Push the return address (PC + 4) onto the stack and jump to the target address. The stack pointer is sp, which is decremented by 4 before the store. The target address is the 20-bit payload sign-extended to 32 bits. Does **not** use the AGU.

The rd, size, reg_value, and addr_imm fields are present in the encoding but ignored by the hardware.

**Pipeline:** In EXECUTE, the hardware performs three actions simultaneously: decrements sp by 4, issues a 32-bit memory write of (PC + 4) to the new sp address, and latches the sign-extended target address into an internal `call_target` register. Waits in MEM for `mem_ready`. In WB, sets PC to the latched `call_target`.

**Operation (step by step):**

```
EXECUTE:
    sp = sp - 4
    mem_addr = sp - 4             (the new sp value)
    mem_wdata = PC + 4            (return address)
    mem_wr = 1                    (32-bit write)
    call_target = sign_ext(payload20)

MEM:
    wait for mem_ready

WB:
    PC = call_target
```

**Target address range:** The 20-bit payload is sign-extended to 32 bits. Positive values 0x00000–0x7FFFF cover 0 to 524287, which is more than enough for the 64KB SPRAM (0x0000–0xFFFF). Negative values would wrap into the upper address space.

**Examples:**

```
call my_function             ; push PC+4, jump to my_function
call 0x100                   ; push PC+4, jump to address 0x100
```

**Calling convention:** There is no hardware-enforced calling convention beyond sp being the stack pointer. Argument passing and register preservation are up to the programmer. The return address is the instruction immediately following the CALL.

**Notes:**

- CALL always uses sp as the stack pointer, regardless of the rd field.
- Nested calls work naturally: each CALL pushes a return address, and each RET pops one.
- The maximum callable address using the 20-bit sign-extended payload is 0x7FFFF (524287). Within the 64KB SPRAM this is never a limitation.

---

### CLR (Clear Register) — pseudo

**Type:** Pseudo-instruction. The assembler expands it into a single LD that copies from `r0` (which is hardwired to zero).

**Expansion:**

```
clr rD   →   ld.32 rD, r0
```

**Encoding:** identical to `ld.32 rD, r0` — a single LD with AGU mode 00, source register `r0`. The CPU sees an ordinary LD instruction.

**Examples:**

```
clr r1                       ; r1 = 0
clr r5                       ; r5 = 0
```

**Notes:**

- Equivalent in effect to `ld.32 rD, #0`, but reads more clearly as "clear this register" and is one byte shorter to type. Both forms encode to a single instruction and run in the same number of cycles.
- The high-level compilers' peephole pass also emits `clr` whenever they would otherwise produce `ld.32 rD, r0`.

---

### JMP (Unconditional Jump) — pseudo

**Type:** Pseudo-instruction. The assembler expands it into a single BEQ comparing `r0` against the immediate `0`. Since `r0` is hardwired to zero, the comparison `0 == 0` is always true, so the branch is always taken.

**Expansion:**

```
jmp target   →   beq.32 r0, #0, target
```

**Encoding:** identical to the BEQ form above — a single 32-bit instruction with the BEQ opcode (6).

**Examples:**

```
jmp .loop                    ; jump to local label
jmp main                     ; jump to global label
jmp 0x100                    ; jump to absolute address
```

**Notes:**

- The target is a 16-bit absolute address (0x0000–0xFFFF), the same as any other branch.
- This is *the* unconditional jump on the MPU; there is no dedicated JMP opcode.

---

### LD (Load)

**Encoding:** `00001 | rd | size | rv | ai | payload` (opcode 1)

Load a value into register rd. Uses the full AGU to decode the operand. The size suffix controls how many bytes are read from memory (for memory operands) or is informational (for immediate/register operands). Writes to r0 are silently discarded.

**Pipeline:**

- Immediate and register-direct modes complete in EXECUTE (no memory access needed). The AGU reports `is_immediate=1` and the value is written directly to rd. PC advances and the next FETCH begins immediately.
- Memory modes (absolute, indexed, post-increment) issue a memory read in EXECUTE, wait in MEM for `mem_ready`, then write the result to rd in WB. For post-increment mode (mode 11), the AGU writeback to the index register also occurs in WB.

**Operation:**

| Addressing Mode | Operation | Stages |
|---|---|---|
| Register direct (mode 00) | `rd = Rsrc` | FETCH → DECODE → EXECUTE |
| Immediate (`#value`) | `rd = sign_ext(imm20)` | FETCH → DECODE → EXECUTE |
| Absolute (`address`) | `rd = mem[sign_ext(payload20)]` | FETCH → DECODE → EXECUTE → MEM → WB |
| Indexed (`[Rbase][Ridx]`) | `rd = mem[Rbase + Ridx]` | FETCH → DECODE → EXECUTE → MEM → WB |
| Indexed+offset (`[Rbase][Ridx+off]`) | `rd = mem[Rbase + Ridx + sign_ext(off12)]` | FETCH → DECODE → EXECUTE → MEM → WB |
| Post-increment (`[Rbase][Ridx+=off]`) | `rd = mem[Rbase + Ridx]; Ridx += sign_ext(off12)` | FETCH → DECODE → EXECUTE → MEM → WB |

**Size behavior:** The size suffix controls which portion of the destination register is written. The upper bits of rd are **preserved**, not zeroed:

- `.8`: only rd[7:0] is written. rd[31:8] is unchanged.
- `.16`: only rd[15:0] is written. rd[31:16] is unchanged.
- `.32`: the full 32 bits of rd are written.

For memory operands, the size suffix also controls how many bytes are read from memory (1, 2, or 4 bytes). For immediate and register-direct modes, the value is truncated to the sized portion before merging into rd.

**Examples:**

```
ld.32  r1, r2               ; r1 = r2 (register move, mode 00)
ld.32  r1, #0x1234          ; r1 = 0x00001234 (immediate, sign-extended)
ld.32  r1, #-1              ; r1 = 0xFFFFFFFF (negative immediate, sign-extended)
ld.8   r2, [r3]             ; r2[7:0] = mem.8[r3], r2[31:8] unchanged
ld.16  r2, [r3]             ; r2[15:0] = mem.16[r3], r2[31:16] unchanged
ld.32  r1, [r2][r3]         ; r1 = mem.32[r2 + r3] (indexed, mode 01)
ld.32  r1, [r2][r3+8]       ; r1 = mem.32[r2 + r3 + 8] (indexed+offset, mode 10)
ld.32  r1, [r6+=4]          ; r1 = mem.32[r6], then r6 += 4 (post-increment, mode 11)
ld.8   r2, 0xFFFF0004       ; r2[7:0] = mem.8[0xFFFF0004] (absolute UART status read)
ld.8   r1, [r6++]           ; r1[7:0] = mem.8[r6], r1[31:8] unchanged, r6 += 1
```

**Notes:**

- `ld.32 r0, #5` is legal but has no effect (r0 stays zero).
- `ld.8` preserves the upper 24 bits. To zero-extend a byte load, follow with `and.32 r1, #0xFF` or use `.32` size and mask.
- For post-increment mode, the memory read uses the address *before* writeback. The index register update happens in the WB stage after the load completes.
- The 20-bit immediate is sign-extended: values 0x00000–0x7FFFF are positive (0 to 524287), values 0x80000–0xFFFFF are negative (−524288 to −1).

---

### LDH (Load High)

**Encoding:** `00010 | rd | size | rv | ai | payload` (opcode 2)

Load the raw 20-bit payload into the upper 20 bits of rd (bits [31:12]), leaving the lower 12 bits (bits [11:0]) unchanged. This instruction does **not** use the AGU — the payload is placed directly into the upper bits without sign extension or address generation.

**Pipeline:** Completes in EXECUTE. No MEM or WB stages.

**Operation:**

```
rd[31:12] = payload[19:0]
rd[11:0]  = rd[11:0]       (unchanged)
PC = PC + 4
```

**Syntax:**

```
ldh rd, #imm20
```

The size, reg_value, and addr_imm fields are present in the encoding but ignored by the hardware.

**Constructing 32-bit constants:** Since LD can only load a 20-bit sign-extended immediate, values that don't fit in 20 bits require an LD+LDH pair. The LD sets the lower bits (with sign extension filling the upper bits), then LDH overwrites the upper 20 bits to the desired value.

Example — loading 0xDEADBEEF into r1:

```
ld.32  r1, #0xDBEEF         ; r1 = 0xFFFDBEEF (sign-extended: bit 19 is 1)
ldh    r1, #0xDEADB         ; r1[31:12] = 0xDEADB → r1 = 0xDEADBEEF
```

How this works: after `ld.32 r1, #0xDBEEF`, r1 holds `0xFFFDBEEF` (the 20-bit value `0xDBEEF` sign-extended, since bit 19 = 1). The lower 12 bits are `0xEEF`. Then `ldh r1, #0xDEADB` replaces bits [31:12] with `0xDEADB`, giving `0xDEADB_EEF` = `0xDEADBEEF`.

**Examples:**

```
ldh    r1, #0xDEADB         ; r1[31:12] = 0xDEADB, r1[11:0] unchanged
ldh    r3, #0x00001         ; r3[31:12] = 0x00001, r3[11:0] unchanged
```

**Notes:**

- Writes to r0 are silently discarded.
- The assembler accepts `ldh` without a size suffix. If a size suffix is present, it is encoded but ignored by the hardware.

---

### LDI (Load Immediate) — pseudo

**Type:** Pseudo-instruction. The assembler picks the shortest expansion: a single `ld.32` if the value fits in the 20-bit signed immediate (−524288 … 524287), or an `ld.32` + `ldh` pair otherwise.

**Expansion:**

```
ldi rD, #N      where -524288 ≤ N ≤ 524287
                →   ld.32 rD, #N

ldi rD, #N      where N is outside that range
                →   ld.32 rD, #(N & 0xFFFFF)
                    ldh   rD, #((N >> 12) & 0xFFFFF)
```

The two-instruction form works because `ld.32` writes the lower 20 bits of `rD` (sign-extended), and `ldh` then overwrites the upper 20 bits with the high portion of the constant. The fields overlap by 8 bits — the same bits go in both halves — so the final value is exactly `N`.

**Operand:** `ldi` accepts numeric literals (decimal, hex, binary, negative) and labels or expressions. For literals, the assembler can decide between the one- and two-instruction forms at expand time. For labels and other non-literal operands the address isn't known yet, so `ldi` conservatively reserves two instruction slots.

**Examples:**

```
ldi    r1, #42                  ; one instruction (fits in 20-bit signed)
ldi    r1, #-1                  ; one instruction
ldi    r2, #0xDEADBEEF          ; two instructions: ld.32 r2, #0xDBEEF + ldh r2, #0xDEADB
ldi    r3, #1048576             ; two instructions (>= 0x80000)
ldi    r4, #my_label            ; two instructions (label, conservative)
```

**Notes:**

- Use `ldi` whenever you have a runtime constant that might be larger than 20 bits — the assembler will keep it to a single instruction when possible. Use `ld.32 rD, #N` directly when you know the value is small and want to be explicit about that.
- The high-level compilers (`cc.py`, `basic.py`, `pas.py`) emit `ldi` for every numeric literal so they don't have to think about the 20-bit limit themselves.

---

### MOV (Register Move) — pseudo

**Type:** Pseudo-instruction. The assembler expands it into a single LD with AGU mode 00 (register direct).

**Expansion:**

```
mov rD, rS   →   ld.32 rD, rS
```

Copies the full 32-bit value of rS into rD. The CPU sees an ordinary LD.

**Examples:**

```
mov r1, r2                   ; r1 = r2
mov r5, sp                   ; r5 = sp
```

**Notes:**

- Use `clr rD` for the special case of `mov rD, r0` — same encoding, more obvious intent. The toolchain's peephole pass prefers `clr` over `mov rD, r0`.
- Both `mov rD, rS` and the underlying `ld.32 rD, rS` form are accepted.

---

### NOP (No Operation)

**Encoding:** `00000 | --- | -- | - | - | --------------------` (opcode 0)

No operation. The instruction word is all zeros (`0x00000000`). The rd, size, reg_value, addr_imm, and payload fields are all ignored. PC advances by 4.

**Pipeline:** Completes in EXECUTE. No MEM or WB stages.

**Operation:**

```
PC = PC + 4
```

**Syntax:**

```
nop
```

---

### OR (Bitwise OR)

**Encoding:** `01101 | rd | size | rv | ai | payload` (opcode 13)

Bitwise OR the operand with rd and store the result in rd. Uses the full AGU to decode the operand. Writes to r0 are silently discarded.

**Pipeline:** Identical to ADD — immediate/register-direct in EXECUTE, memory operands through MEM → WB.

**Operation:**

```
rd = size_mask(rd | operand)
PC = PC + 4
```

**Size behavior:** The result is truncated to the width specified by the size suffix before being written to rd. Upper bits are zeroed:

- `.8`: result is masked to bits [7:0], upper 24 bits cleared.
- `.16`: result is masked to bits [15:0], upper 16 bits cleared.
- `.32`: full 32-bit result, no truncation.

For memory operands, the size suffix also controls the memory read width.

**Examples:**

```
or.32  r1, #0x80            ; r1 = r1 | 0x80 (set bit 7)
or.8   r1, #0x80            ; r1 = (r1 | 0x80) & 0xFF (8-bit result)
or.32  r1, r2               ; r1 = r1 | r2 (register-register)
or.32  r1, [r2]             ; r1 = r1 | mem.32[r2] (memory indirect)
or.32  r1, [r2][r3]         ; r1 = r1 | mem.32[r2 + r3] (indexed)
or.32  r1, [r2][r3+8]       ; r1 = r1 | mem.32[r2 + r3 + 8] (indexed+offset)
or.32  r1, [r6+=4]          ; r1 = r1 | mem.32[r6], then r6 += 4 (post-increment)
or.32  r1, 0x100            ; r1 = r1 | mem.32[0x100] (absolute)
```

**Notes:**

- Useful for setting individual bits or combining bit fields.
- `or.32 r1, r2` with r1 initially zero acts as a register move (same as `ld.32 r1, r2` but less clear).

---

### POP (Pop from Stack) — pseudo

**Type:** Pseudo-instruction. The assembler expands it into a single LD with AGU post-increment writeback.

**Expansion:**

```
pop rN   →   ld.32 rN, [sp+=4]
```

Loads the 32-bit word at the address in sp into rN, then increments sp by 4. The architecture has no dedicated POP opcode — the AGU's mode-11 writeback does the work in a single instruction.

**Examples:**

```
pop r6                       ; r6 = mem[sp]; sp += 4
pop r1                       ; r1 = mem[sp]; sp += 4
```

**Notes:**

- The corresponding `push rN` decrements sp first, then stores. POP undoes that.
- See **Stack Operations** below for the full conventional pattern.

---

### PUSH (Push to Stack) — pseudo

**Type:** Pseudo-instruction. The assembler expands it into **two** native instructions — `sub.32 sp, #4` followed by `st.32 [sp], rN`. This is the only multi-word pseudo-op; the assembler runs the expansion before pass 1, so labels still resolve correctly. A label attached to a `push` line points at the first of the two expanded instructions.

**Expansion:**

```
push rN   →   sub.32 sp, #4
              st.32  [sp], rN
```

Decrements sp by 4, then stores rN at the new top of stack. After the sequence, sp points at the pushed value — the conventional "stack grows down, sp points at the top item" model.

**Examples:**

```
push r6                      ; sp -= 4; mem[sp] = r6
push r1                      ; sp -= 4; mem[sp] = r1
```

**Notes:**

- The corresponding `pop rN` reverses this.
- Two instructions is unavoidable: the AGU offers post-decrement writeback (`[sp+=-4]`), but post-decrement stores to the *old* sp and then decrements — that leaves sp pointing 4 bytes below the data, which is not the conventional stack layout. A real push needs a pre-decrement, which requires a separate `sub` instruction.
- See **Stack Operations** below for the full conventional pattern.

---

### RET (Return from Subroutine)

**Encoding:** `10010 | --- | -- | - | - | --------------------` (opcode 18)

Pop the return address from the stack and jump to it. The stack pointer is sp, which is incremented by 4 after the load. Does **not** use the AGU.

All fields other than the opcode (rd, size, reg_value, addr_imm, payload) are present in the encoding but ignored by the hardware. The instruction is typically assembled as all zeros except for the opcode bits.

**Pipeline:** In EXECUTE, issues a 32-bit memory read from the address in sp. Waits in MEM for `mem_ready`. In WB, sets PC to the value read from memory and increments sp by 4.

**Operation (step by step):**

```
EXECUTE:
    mem_addr = sp
    mem_rd = 1                    (32-bit read)

MEM:
    wait for mem_ready

WB:
    PC = mem_rdata                (the return address)
    sp = sp + 4
```

**Examples:**

```
ret                          ; pop return address, jump to it
```

**Notes:**

- RET always uses sp as the stack pointer, regardless of the rd field.
- If sp does not point to a valid return address (e.g., stack corruption or calling RET without a matching CALL), the PC will be set to whatever value is in memory at sp, leading to undefined behavior.
- RET and CALL are complementary: CALL pushes (PC+4) and decrements sp, RET pops the address and increments sp.

---

### SHL (Shift Left)

**Encoding:** `01111 | rd | size | rv | ai | payload` (opcode 15)

Logical shift rd left by the number of positions given in the operand (only bits [4:0] of the operand are used, giving a shift range of 0–31). Zeros are shifted in from the right. Uses the full AGU to decode the operand. Writes to r0 are silently discarded.

**Pipeline:** Identical to ADD — immediate/register-direct in EXECUTE, memory operands through MEM → WB.

**Operation:**

```
rd = rd << operand[4:0]
PC = PC + 4
```

Only the lowest 5 bits of the operand determine the shift amount. The remaining bits are ignored.

**Examples:**

```
shl.32 r1, #8               ; r1 = r1 << 8 (multiply by 256)
shl.32 r1, #1               ; r1 = r1 << 1 (multiply by 2)
shl.32 r1, r2               ; r1 = r1 << r2[4:0] (variable shift)
shl.32 r1, [r2]             ; r1 = r1 << mem.32[r2][4:0] (memory indirect)
shl.32 r1, [r2][r3]         ; r1 = r1 << mem.32[r2 + r3][4:0] (indexed)
shl.32 r1, [r2][r3+8]       ; r1 = r1 << mem.32[r2 + r3 + 8][4:0] (indexed+offset)
shl.32 r1, [r6+=4]          ; r1 = r1 << mem.32[r6][4:0], then r6 += 4
shl.32 r1, 0x100            ; r1 = r1 << mem.32[0x100][4:0] (absolute)
```

**Notes:**

- `shl.32 r1, #N` is equivalent to multiplying by 2^N (for N in 0–31).
- A shift of 0 leaves rd unchanged.
- Bits shifted out the left side are lost (no carry flag).

---

### SHR (Shift Right)

**Encoding:** `10000 | rd | size | rv | ai | payload` (opcode 16)

Logical shift rd right by the number of positions given in the operand (only bits [4:0] of the operand are used, giving a shift range of 0–31). **Zeros** are shifted in from the left (logical shift, not arithmetic). Uses the full AGU to decode the operand. Writes to r0 are silently discarded.

**Pipeline:** Identical to ADD — immediate/register-direct in EXECUTE, memory operands through MEM → WB.

**Operation:**

```
rd = rd >> operand[4:0]      (logical, zero-fill)
PC = PC + 4
```

Only the lowest 5 bits of the operand determine the shift amount. The remaining bits are ignored.

**Examples:**

```
shr.32 r1, #4               ; r1 = r1 >> 4 (unsigned divide by 16)
shr.32 r1, #1               ; r1 = r1 >> 1 (unsigned divide by 2)
shr.32 r1, r2               ; r1 = r1 >> r2[4:0] (variable shift)
shr.32 r1, [r2]             ; r1 = r1 >> mem.32[r2][4:0] (memory indirect)
shr.32 r1, [r2][r3]         ; r1 = r1 >> mem.32[r2 + r3][4:0] (indexed)
shr.32 r1, [r2][r3+8]       ; r1 = r1 >> mem.32[r2 + r3 + 8][4:0] (indexed+offset)
shr.32 r1, [r6+=4]          ; r1 = r1 >> mem.32[r6][4:0], then r6 += 4
shr.32 r1, 0x100            ; r1 = r1 >> mem.32[0x100][4:0] (absolute)
```

**Notes:**

- This is a **logical** (unsigned) shift. The MSB is always filled with zero. There is no arithmetic right shift instruction; to perform sign-preserving division, you must implement it manually (e.g., save the sign bit, shift, then restore).
- `shr.32 r1, #N` is equivalent to unsigned division by 2^N.
- Bits shifted out the right side are lost (no carry flag).

---

### ST (Store)

**Encoding:** `00011 | rd | size | rv | ai | payload` (opcode 3)

Store the value of register rd to a memory address. Uses the full AGU to decode the destination operand. The size suffix controls how many bytes are written: `.8` writes the lowest byte of rd, `.16` the lowest two bytes, `.32` the full word.

**Pipeline:** Issues a memory write in EXECUTE, waits in MEM for `mem_ready`, then advances PC in WB. For post-increment mode, the AGU writeback to the index register also occurs in WB.

**Operation:**

| Addressing Mode | Operation |
|---|---|
| Absolute (`address`) | `mem[sign_ext(payload20)] = rd` |
| Indexed (`[Rbase][Ridx]`) | `mem[Rbase + Ridx] = rd` |
| Indexed+offset (`[Rbase][Ridx+off]`) | `mem[Rbase + Ridx + sign_ext(off12)] = rd` |
| Post-increment (`[Rbase][Ridx+=off]`) | `mem[Rbase + Ridx] = rd; Ridx += sign_ext(off12)` |
| Immediate (`#value`) | `mem[rd] = sign_ext(imm20)` |

**Important — immediate mode is special for ST:** When the AGU reports an immediate operand, the roles are swapped: the *address* comes from rd (the register value), and the *data* written is the sign-extended immediate. This allows storing a small constant to the address held in a register without needing a separate register for the constant.

**Assembler syntax:** For ST, the operand order is `st.size destination, source`:

```
st.size  address_operand, rd
```

This is the reverse of LD (where rd comes first) because it reads more naturally: "store to [address], the value in rd."

**Examples:**

```
st.8   0xFFFF0000, r1       ; mem.8[0xFFFF0000] = r1 (write byte to UART TX)
st.32  [r3], r1             ; mem.32[r3] = r1 (shorthand for [r3])
st.32  [r2][r3], r1         ; mem.32[r2 + r3] = r1 (indexed)
st.32  [r2][r3+8], r1       ; mem.32[r2 + r3 + 8] = r1 (indexed+offset)
st.8   #0x41, r2            ; mem.8[r2] = 0x41 (store immediate 'A' to addr in r2)
```

**Notes:**

- For post-increment mode, the memory write uses the address *before* writeback. The index register update happens in WB.
- When rd is r0, the value stored is always zero (since r0 is hardwired to 0).
- Register-direct mode (mode 00) would make the AGU report an immediate with the base register's value — for ST this means `mem[rd] = base_reg_val`, which is a valid but unusual operation.

---

### SUB (Subtract)

**Encoding:** `00101 | rd | size | rv | ai | payload` (opcode 5)

Subtract the operand from rd and store the result in rd. Uses the full AGU to decode the operand. Writes to r0 are silently discarded.

**Pipeline:** Identical to ADD — immediate/register-direct in EXECUTE, memory operands go through MEM → WB.

**Operation:**

```
rd = size_mask(rd - operand)
PC = PC + 4
```

**Size behavior:** The result is truncated to the width specified by the size suffix before being written to rd. Upper bits are zeroed:

- `.8`: result is masked to bits [7:0], upper 24 bits cleared. Wraps on underflow (0 - 1 = 0xFF).
- `.16`: result is masked to bits [15:0], upper 16 bits cleared. Wraps on underflow (0 - 1 = 0xFFFF).
- `.32`: full 32-bit result. Wraps on underflow (two's complement).

For memory operands, the size suffix also controls the memory read width.

**Examples:**

```
sub.32 r1, r2               ; r1 = r1 - r2 (register-register)
sub.32 r1, #10              ; r1 = r1 - 10 (immediate)
sub.8  r1, #1               ; r1 = (r1 - 1) & 0xFF (8-bit subtraction)
sub.16 r1, #1               ; r1 = (r1 - 1) & 0xFFFF (16-bit subtraction)
sub.32 sp, #16              ; sp = sp - 16 (allocate 16 bytes on stack)
sub.32 r1, [r2]             ; r1 = r1 - mem.32[r2] (memory indirect)
sub.32 r1, [r2][r3]         ; r1 = r1 - mem.32[r2 + r3] (indexed)
sub.32 r1, [r2][r3+8]       ; r1 = r1 - mem.32[r2 + r3 + 8] (indexed+offset)
sub.32 r1, [r6+=4]          ; r1 = r1 - mem.32[r6], then r6 += 4 (post-increment)
sub.32 r1, 0x100            ; r1 = r1 - mem.32[0x100] (absolute)
```

**Notes:**

- There is no borrow flag.
- `sub.8 r1, #1` with r1 = 0x00 produces r1 = 0xFF (wraps to 255).
- `sub.32 sp, #N` / `add.32 sp, #N` is the standard pattern for allocating/deallocating stack space.

---

### XOR (Bitwise Exclusive OR)

**Encoding:** `01110 | rd | size | rv | ai | payload` (opcode 14)

Bitwise XOR the operand with rd and store the result in rd. Uses the full AGU to decode the operand. Writes to r0 are silently discarded.

**Pipeline:** Identical to ADD — immediate/register-direct in EXECUTE, memory operands through MEM → WB.

**Operation:**

```
rd = size_mask(rd ^ operand)
PC = PC + 4
```

**Size behavior:** The result is truncated to the width specified by the size suffix before being written to rd. Upper bits are zeroed:

- `.8`: result is masked to bits [7:0], upper 24 bits cleared.
- `.16`: result is masked to bits [15:0], upper 16 bits cleared.
- `.32`: full 32-bit result, no truncation.

For memory operands, the size suffix also controls the memory read width.

**Examples:**

```
xor.32 r1, #-1              ; r1 = r1 ^ 0xFFFFFFFF = ~r1 (bitwise NOT)
xor.8  r1, #-1              ; r1 = (r1 ^ 0xFFFFFFFF) & 0xFF (8-bit NOT of lower byte)
xor.32 r1, r2               ; r1 = r1 ^ r2 (register-register)
xor.32 r1, [r2]             ; r1 = r1 ^ mem.32[r2] (memory indirect)
xor.32 r1, [r2][r3]         ; r1 = r1 ^ mem.32[r2 + r3] (indexed)
xor.32 r1, [r2][r3+8]       ; r1 = r1 ^ mem.32[r2 + r3 + 8] (indexed+offset)
xor.32 r1, [r6+=4]          ; r1 = r1 ^ mem.32[r6], then r6 += 4 (post-increment)
xor.32 r1, 0x100            ; r1 = r1 ^ mem.32[0x100] (absolute)
```

**Notes:**

- `xor.32 r1, #-1` is the standard bitwise NOT, since `#-1` sign-extends to `0xFFFFFFFF`.
- `xor.8 r1, #-1` inverts only the lower byte and clears the upper 24 bits.
- XOR is its own inverse: applying it twice restores the original value.

## Stack Operations

There are no dedicated PUSH/POP machine instructions — the architecture doesn't need them. `push rN` is a two-instruction pseudo (`sub.32 sp, #4` then `st.32 [sp], rN`) and `pop rN` is a single-instruction pseudo using AGU post-increment writeback (`ld.32 rN, [sp+=4]`). After a `push`, sp points at the pushed value; after a matching `pop`, sp is restored to its pre-push state.

A 68K-style function prologue and epilogue:

```asm
my_func:
                push    r6                  ; save callee-saved register
                ld.32   r1, [sp+8]          ; load arg0 from caller's frame
                ; ... body ...
                pop     r6                  ; restore r6
                ret                         ; return to caller
```

The argument at `[sp+8]` is two slots above sp because the prologue pushed r6 (4 bytes) and the call itself pushed the return address (another 4 bytes). The full calling convention is documented in [doc/CLAUDE.md](CLAUDE.md).

## Assembler Directives

| Directive         | Description                                  |
|-------------------|----------------------------------------------|
| label: or label   | Define a label (colon optional)              |
| .label:           | Local label (scoped to previous global)      |
| db 'string\0'    | Define bytes (string or comma-separated)     |
| end               | End of assembly source                       |

## Complete Example

```
                ld.32   r6, #hello
.loop:
                ld.8    r1, [r6++]
                beq.8   r1, #0, stop
                call    output
                jmp     .loop

stop:           jmp     stop

output:
.wait:          ld.8    r2, 0xFFFF0004      ; read UART busy flag
                bne.8   r2, #0, .wait       ; loop while busy
                st.8    0xFFFF0000, r1      ; send byte
                ret

hello:          db      'Hello, world!\0'

                end
```
