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

## Memory Map

| Address Range              | Description                              |
|----------------------------|------------------------------------------|
| 0x0000_0000 - 0x0000_FFFF | SPRAM (64KB)                             |
| 0xFFFF_0000                | UART TX data (write byte)                |
| 0xFFFF_0004                | UART TX status (read, bit 0 = busy)      |

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

Assembler shorthand: `[Rbase]` expands to `[r0][Rbase]` (mode 01). `[r6++]` expands to `[r0][r6+=1]`, `[sp+=-4]` expands to `[r0][sp+=-4]`.

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

## Opcode Reference

### 0 — NOP

**Encoding:** `00000 | --- | -- | - | - | --------------------`

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

### 1 — LD (Load)

**Encoding:** `00001 | rd | size | rv | ai | payload`

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
ld.32  r1, [r0][r6+=4]      ; r1 = mem.32[r6], then r6 += 4 (post-increment, mode 11)
ld.32  r2, 0xFFFF0004       ; r2 = mem.32[0xFFFF0004] (absolute, sign-extended address)
ld.8   r1, [r6++]           ; r1[7:0] = mem.8[r6], r1[31:8] unchanged, r6 += 1
```

**Notes:**

- `ld.32 r0, #5` is legal but has no effect (r0 stays zero).
- `ld.8` preserves the upper 24 bits. To zero-extend a byte load, follow with `and.32 r1, #0xFF` or use `.32` size and mask.
- For post-increment mode, the memory read uses the address *before* writeback. The index register update happens in the WB stage after the load completes.
- The 20-bit immediate is sign-extended: values 0x00000–0x7FFFF are positive (0 to 524287), values 0x80000–0xFFFFF are negative (−524288 to −1).

---

### 2 — LDH (Load High)

**Encoding:** `00010 | rd | size | rv | ai | payload`

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

### 3 — ST (Store)

**Encoding:** `00011 | rd | size | rv | ai | payload`

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
st.32  [r3], r1             ; mem.32[r3] = r1 (shorthand for [r0][r3])
st.32  [r2][r3], r1         ; mem.32[r2 + r3] = r1 (indexed)
st.32  [r2][r3+8], r1       ; mem.32[r2 + r3 + 8] = r1 (indexed+offset)
st.32  [r0][sp+=-4], r1     ; mem.32[sp] = r1, then sp -= 4 (push)
st.32  [sp+=-4], r1         ; same as above (shorthand)
st.8   #0x41, r2            ; mem.8[r2] = 0x41 (store immediate 'A' to addr in r2)
```

**Notes:**

- For post-increment mode, the memory write uses the address *before* writeback. The index register update happens in WB.
- When rd is r0, the value stored is always zero (since r0 is hardwired to 0).
- Register-direct mode (mode 00) would make the AGU report an immediate with the base register's value — for ST this means `mem[rd] = base_reg_val`, which is a valid but unusual operation.

---

### 4 — ADD

**Encoding:** `00100 | rd | size | rv | ai | payload`

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
add.32 r1, [r0][r6+=4]      ; r1 = r1 + mem.32[r6], then r6 += 4 (post-increment)
add.32 r1, 0x100            ; r1 = r1 + mem.32[0x100] (absolute)
```

**Notes:**

- There is no carry flag or overflow detection. Use branch instructions to check for overflow if needed.
- `add.32 r1, #-N` is equivalent to `sub.32 r1, #N` for small N.
- `add.8 r1, #1` with r1 = 0xFF produces r1 = 0x00 (wraps to zero).

---

### 5 — SUB (Subtract)

**Encoding:** `00101 | rd | size | rv | ai | payload`

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
sub.32 r1, [r0][r6+=4]      ; r1 = r1 - mem.32[r6], then r6 += 4 (post-increment)
sub.32 r1, 0x100            ; r1 = r1 - mem.32[0x100] (absolute)
```

**Notes:**

- There is no borrow flag.
- `sub.8 r1, #1` with r1 = 0x00 produces r1 = 0xFF (wraps to 255).
- `sub.32 sp, #N` / `add.32 sp, #N` is the standard pattern for allocating/deallocating stack space.

---

### 6 — BEQ (Branch if Equal)

**Encoding:** `00110 | rd | size | r/i | cmp[2:0] | target[15:0]`

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

### 7 — BNE (Branch if Not Equal)

**Encoding:** `00111 | rd | size | r/i | cmp[2:0] | target[15:0]`

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

### 8 — BLT (Branch if Less Than)

**Encoding:** `01000 | rd | size | r/i | cmp[2:0] | target[15:0]`

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

### 9 — BGT (Branch if Greater Than)

**Encoding:** `01001 | rd | size | r/i | cmp[2:0] | target[15:0]`

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

### 10 — BLE (Branch if Less or Equal)

**Encoding:** `01010 | rd | size | r/i | cmp[2:0] | target[15:0]`

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

### 11 — BGE (Branch if Greater or Equal)

**Encoding:** `01011 | rd | size | r/i | cmp[2:0] | target[15:0]`

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

### 12 — AND (Bitwise AND)

**Encoding:** `01100 | rd | size | rv | ai | payload`

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
and.32 r1, [r0][r6+=4]      ; r1 = r1 & mem.32[r6], then r6 += 4 (post-increment)
and.32 r1, 0x100            ; r1 = r1 & mem.32[0x100] (absolute)
```

**Notes:**

- Useful for masking, clearing bits, and testing bit patterns.
- `and.8 r1, #0xFF` is a no-op on the lower byte but clears the upper 24 bits (the size mask zeroes them).
- The 20-bit immediate is sign-extended, so `#0xFF` becomes `0x000000FF` and `#-1` becomes `0xFFFFFFFF`.

---

### 13 — OR (Bitwise OR)

**Encoding:** `01101 | rd | size | rv | ai | payload`

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
or.32  r1, [r0][r6+=4]      ; r1 = r1 | mem.32[r6], then r6 += 4 (post-increment)
or.32  r1, 0x100            ; r1 = r1 | mem.32[0x100] (absolute)
```

**Notes:**

- Useful for setting individual bits or combining bit fields.
- `or.32 r1, r2` with r1 initially zero acts as a register move (same as `ld.32 r1, r2` but less clear).

---

### 14 — XOR (Bitwise Exclusive OR)

**Encoding:** `01110 | rd | size | rv | ai | payload`

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
xor.32 r1, [r0][r6+=4]      ; r1 = r1 ^ mem.32[r6], then r6 += 4 (post-increment)
xor.32 r1, 0x100            ; r1 = r1 ^ mem.32[0x100] (absolute)
```

**Notes:**

- `xor.32 r1, #-1` is the standard bitwise NOT, since `#-1` sign-extends to `0xFFFFFFFF`.
- `xor.8 r1, #-1` inverts only the lower byte and clears the upper 24 bits.
- XOR is its own inverse: applying it twice restores the original value.

---

### 15 — SHL (Shift Left)

**Encoding:** `01111 | rd | size | rv | ai | payload`

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
shl.32 r1, [r0][r6+=4]      ; r1 = r1 << mem.32[r6][4:0], then r6 += 4
shl.32 r1, 0x100            ; r1 = r1 << mem.32[0x100][4:0] (absolute)
```

**Notes:**

- `shl.32 r1, #N` is equivalent to multiplying by 2^N (for N in 0–31).
- A shift of 0 leaves rd unchanged.
- Bits shifted out the left side are lost (no carry flag).

---

### 16 — SHR (Shift Right)

**Encoding:** `10000 | rd | size | rv | ai | payload`

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
shr.32 r1, [r0][r6+=4]      ; r1 = r1 >> mem.32[r6][4:0], then r6 += 4
shr.32 r1, 0x100            ; r1 = r1 >> mem.32[0x100][4:0] (absolute)
```

**Notes:**

- This is a **logical** (unsigned) shift. The MSB is always filled with zero. There is no arithmetic right shift instruction; to perform sign-preserving division, you must implement it manually (e.g., save the sign bit, shift, then restore).
- `shr.32 r1, #N` is equivalent to unsigned division by 2^N.
- Bits shifted out the right side are lost (no carry flag).

---

### 17 — CALL (Call Subroutine)

**Encoding:** `10001 | --- | -- | - | - | payload[19:0]`

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

### 18 — RET (Return from Subroutine)

**Encoding:** `10010 | --- | -- | - | - | --------------------`

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

## Pseudo-Instructions

| Pseudo       | Expands to               | Description             |
|--------------|--------------------------|-------------------------|
| jmp target   | beq r0, #0, target       | Unconditional jump      |

## Stack Operations

No dedicated PUSH/POP. Use AGU writeback mode with sp:

```
st.32 [r0][sp+=-4], r1      ; push r1
ld.32 r1, [r0][sp+=4]       ; pop r1
```

Or with shorthand:

```
st.32 [sp+=-4], r1          ; push r1
ld.32 r1, [sp+=4]           ; pop r1
```

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
.wait:          ld.32   r2, 0xFFFF0004      ; read UART busy flag
                bne.8   r2, #0, .wait       ; loop while busy
                st.8    0xFFFF0000, r1      ; send byte
                ret

hello:          db      'Hello, world!\0'

                end
```
