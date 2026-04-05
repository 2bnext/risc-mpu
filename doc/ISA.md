# MPU Instruction Set Architecture

## Overview

- 32-bit fixed-width instructions, little-endian
- 8 general-purpose 32-bit registers (r0-r7)
- r0 is hardwired to zero
- r7 is the stack pointer by convention (initialized to 0x10000)
- 32-bit program counter
- 5-stage state machine: FETCH, DECODE, EXECUTE, MEM, WB

## Registers

| Register | Convention                               |
|----------|------------------------------------------|
| r0       | Always zero (hardwired, writes ignored)  |
| r1-r6    | General purpose                          |
| r7       | Stack pointer (initialized to 0x10000)   |

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
| rd        | [26:24] | Destination/source register (3 bits, r0-r7)           |
| size      | [23:22] | Operand size                                          |
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

Assembler shorthand: `[Rbase]` expands to `[r0][Rbase]` (mode 01). `[r6++]` expands to `[r0][r6+=1]`, `[r7+=-4]` expands to `[r0][r7+=-4]`.

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
| cmp_operand | [18:16] | Register select (r0-r7) or immediate (0-7)         |
| target      | [15:0]  | Branch target address (16-bit, covers full 64KB)    |

The size suffix affects comparison: `.8` compares lower 8 bits (sign-extended), `.16` lower 16 bits, `.32` full 32-bit. All comparisons are signed.

## Opcode Reference

### 0 — NOP

No operation. Advances PC.

```
nop
```

---

### 1 — LD (Load)

Load a value into rd. Full AGU support.

- Register: `rd = Rsrc` (move)
- Immediate: `rd = sign_ext(imm20)`
- Memory: `rd = mem[eff_addr]`

```
ld.32  r1, r2               ; r1 = r2 (register move)
ld.32  r1, #0x1234          ; r1 = 0x1234
ld.8   r2, [r3]             ; r2 = mem.8[r3]
ld.32  r1, [r0][r6+=4]      ; r1 = mem.32[r6], r6 += 4 (pop)
ld.32  r2, 0xFFFF0004       ; r2 = mem.32[0xFFFF0004] (absolute)
ld.8   r1, [r6++]           ; r1 = mem.8[r6], r6 += 1
```

---

### 2 — LDH (Load High)

Load payload into upper 20 bits of rd, keep lower 12 bits unchanged. Uses raw payload, not AGU.

```
ldh r1, #0xDEADB            ; r1[31:12] = 0xDEADB, r1[11:0] unchanged
```

To construct a full 32-bit value (e.g. 0xDEADBEEF):

```
ld.32  r1, #0xDBEEF         ; r1 = 0xFFFDBEEF (sign-extended 20-bit)
ldh    r1, #0xDEADB         ; r1 = 0xDEADBEEF
```

---

### 3 — ST (Store)

Store rd to memory. Full AGU support.

- Absolute/register: `mem[eff_addr] = rd`
- Immediate: `mem[rd] = sign_ext(imm20)` (stores immediate value to address in rd)

```
st.8   0xFFFF0000, r1       ; mem.8[0xFFFF0000] = r1 (UART TX)
st.32  [r3], r1             ; mem.32[r3] = r1
st.32  [r0][r7+=-4], r1     ; mem.32[r7] = r1, r7 -= 4 (push)
```

---

### 4 — ADD

`rd = rd + operand`. Full AGU support.

```
add.32 r1, r2               ; r1 = r1 + r2 (register-register)
add.32 r1, #1               ; r1 = r1 + 1
add.32 r1, [r2]             ; r1 = r1 + mem.32[r2]
```

---

### 5 — SUB

`rd = rd - operand`. Full AGU support.

```
sub.32 r1, #10              ; r1 = r1 - 10
sub.32 r7, #16              ; allocate 16 bytes on stack
```

---

### 6 — BEQ (Branch if Equal)

Branch to target if `rd == cmp_operand`.

```
beq.32 r1, #0, .done        ; branch if r1 == 0
beq.32 r1, r2, .match       ; branch if r1 == r2
```

---

### 7 — BNE (Branch if Not Equal)

Branch to target if `rd != cmp_operand`.

```
bne.8  r2, #0, .wait        ; branch if lower byte of r2 != 0
bne.32 r1, r2, .loop        ; branch if r1 != r2
```

---

### 8 — BLT (Branch if Less Than)

Branch to target if `rd < cmp_operand` (signed).

```
blt.32 r1, #5, .label       ; branch if r1 < 5
```

---

### 9 — BGT (Branch if Greater Than)

Branch to target if `rd > cmp_operand` (signed).

```
bgt.32 r1, r2, .label       ; branch if r1 > r2
```

---

### 10 — BLE (Branch if Less or Equal)

Branch to target if `rd <= cmp_operand` (signed).

```
ble.32 r1, #7, .label       ; branch if r1 <= 7
```

---

### 11 — BGE (Branch if Greater or Equal)

Branch to target if `rd >= cmp_operand` (signed).

```
bge.32 r1, #0, .positive    ; branch if r1 >= 0
```

---

### 12 — AND

`rd = rd & operand`. Full AGU support.

```
and.32 r1, #0xFF            ; mask lower byte
and.32 r1, [r2]             ; r1 = r1 & mem.32[r2]
```

---

### 13 — OR

`rd = rd | operand`. Full AGU support.

```
or.32  r1, #0x80            ; set bit 7
```

---

### 14 — XOR

`rd = rd ^ operand`. Full AGU support.

```
xor.32 r1, #-1              ; bitwise NOT (complement)
```

---

### 15 — SHL (Shift Left)

`rd = rd << operand[4:0]`. Logical shift. Full AGU support.

```
shl.32 r1, #8               ; shift left by 8
```

---

### 16 — SHR (Shift Right)

`rd = rd >> operand[4:0]`. Logical shift (zero-fill). Full AGU support.

```
shr.32 r1, #4               ; shift right by 4
```

---

### 17 — CALL

Push return address, jump to target. Uses r7 as stack pointer.

`r7 -= 4, mem.32[r7] = PC + 4, PC = sign_ext(payload20)`

```
call my_function             ; push return addr, jump
```

---

### 18 — RET

Pop return address, jump to it.

`PC = mem.32[r7], r7 += 4`

```
ret                          ; return from subroutine
```

---

## Pseudo-Instructions

| Pseudo       | Expands to               | Description             |
|--------------|--------------------------|-------------------------|
| jmp target   | beq r0, #0, target       | Unconditional jump      |

## Stack Operations

No dedicated PUSH/POP. Use AGU writeback mode with r7:

```
st.32 [r0][r7+=-4], r1      ; push r1
ld.32 r1, [r0][r7+=4]       ; pop r1
```

Or with shorthand:

```
st.32 [r7+=-4], r1          ; push r1
ld.32 r1, [r7+=4]           ; pop r1
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
