# Programming the MPU

*A guide to a handcrafted processor*

---

## Table of Contents

1. [Before There Were Computers](#1-before-there-were-computers)
2. [What Is a CPU, Really?](#2-what-is-a-cpu-really)
3. [Counting in Hexadecimal](#3-counting-in-hexadecimal)
4. [A Brief History of Instruction Sets](#4-a-brief-history-of-instruction-sets)
5. [Enter the MPU](#5-enter-the-mpu)
6. [What Is an FPGA?](#6-what-is-an-fpga)
7. [The Hardware](#7-the-hardware)
8. [Architecture at a Glance](#8-architecture-at-a-glance)
9. [The Beauty of the Instruction Format](#9-the-beauty-of-the-instruction-format)
10. [Your First Program: Hello, World!](#10-your-first-program-hello-world)
11. [Understanding Memory](#11-understanding-memory)
12. [Working with Registers](#12-working-with-registers)
13. [The Address Generation Unit](#13-the-address-generation-unit)
14. [Branching and Loops](#14-branching-and-loops)
15. [Subroutines and the Stack](#15-subroutines-and-the-stack)
16. [Bit Manipulation](#16-bit-manipulation)
17. [A Complete Program: Counting](#17-a-complete-program-counting)
18. [From C to Assembly](#18-from-c-to-assembly)
19. [Closing Thoughts](#19-closing-thoughts)

---

## 1. Before There Were Computers

In 1837, Charles Babbage designed the Analytical Engine on paper. It had a "mill" (processor), a "store" (memory), and could be programmed with punched cards. Ada Lovelace wrote the first algorithm for it. The machine was never built, but the ideas were all there: fetch an instruction, do the work, store the result, move to the next instruction. Nearly two centuries later, every processor on earth still follows that same loop.

The first electronic computers in the 1940s filled entire rooms. ENIAC had 18,000 vacuum tubes and was programmed by physically rewiring cables. Then came stored-program machines like EDSAC (1949), where the program lived in memory alongside the data. You could change what the computer did without touching a single wire. That was the revolution.

From there the path leads through transistors, integrated circuits, and microprocessors. The Intel 4004 (1971) put a complete CPU on a single chip: 2,300 transistors, 4-bit words, 740 kHz. The 6502 (1975) powered the Apple II and Commodore 64 with 3,510 transistors at 1 MHz. The Z80 (1976) ran CP/M and countless home computers. These chips were simple enough that one person could understand every transistor. That simplicity was their magic.

The modern world lost that. A current Intel or AMD processor has billions of transistors, thousands of pages of documentation, and so many layers of microarchitectural complexity that no single person can hold the full design in their head. We gained performance, but we lost something too: the ability to *see* the whole machine, from the instruction you type to the wires that carry it.

This booklet is about getting that back.

---

## 2. What Is a CPU, Really?

Strip away the marketing and the acronyms, and a CPU does three things:

1. **Fetch** an instruction from memory.
2. **Execute** that instruction (add two numbers, load a value, check a condition).
3. **Repeat** with the next instruction.

That's it. Every complex behavior emerges from this loop running millions of times per second. A CPU is a machine that reads a list of very simple orders and follows them one by one, very fast.

The instructions live in memory as numbers. There's nothing special about them: they're just bytes at certain addresses. What makes them instructions is that the CPU reads them with its **program counter** (PC), a register that holds the address of the next instruction to execute. After each instruction, the PC moves forward. Branch instructions change the PC to a different address, which is how loops and decisions work.

The CPU also has **registers**: a handful of small, fast storage slots inside the processor itself. Loading data from memory into a register is slow compared to working with data already in a register. So the programmer's job is to load what they need, do the work in registers, and store the result back when they're done.

---

## 3. Counting in Hexadecimal

Before we go further, you need to be comfortable with **hexadecimal** (base 16). It appears everywhere in low-level programming: memory addresses, instruction encodings, register values, byte patterns. If you've only worked with decimal (base 10), this section will get you up to speed.

### Why Not Decimal?

Computers work in binary: ones and zeros. A 32-bit register holds 32 binary digits. Writing that out is painful:

```
11011110101011011011111011101111
```

Decimal is more compact, but it hides the bit structure. The number above is 3,735,928,559 in decimal. There's no way to look at that and see which bits are set.

Hexadecimal solves this. Each hex digit represents exactly 4 bits (one **nibble**). A 32-bit value is always exactly 8 hex digits. The binary above becomes:

```
1101 1110 1010 1101 1011 1110 1110 1111
 D    E    A    D    B    E    E    F

= 0xDEADBEEF
```

You can instantly see the bit pattern. The `0x` prefix tells you the number is in hex.

### The Digits

Hex uses 16 digits. Since we only have 10 decimal digits (0-9), the letters A through F fill in for 10 through 15:

| Decimal | Hex | Binary |
|---------|-----|--------|
| 0       | 0   | 0000   |
| 1       | 1   | 0001   |
| 2       | 2   | 0010   |
| 3       | 3   | 0011   |
| 4       | 4   | 0100   |
| 5       | 5   | 0101   |
| 6       | 6   | 0110   |
| 7       | 7   | 0111   |
| 8       | 8   | 1000   |
| 9       | 9   | 1001   |
| 10      | A   | 1010   |
| 11      | B   | 1011   |
| 12      | C   | 1100   |
| 13      | D   | 1101   |
| 14      | E   | 1110   |
| 15      | F   | 1111   |

Lowercase (a-f) and uppercase (A-F) both work. The MPU assembler and toolchain accept either.

### Converting in Your Head

**Hex to decimal**: multiply each digit by its power of 16.

```
0xFF = 15 * 16 + 15 = 255
0x100 = 1 * 256 = 256
0x10000 = 65536 (64 KB — the MPU's memory size)
```

**Decimal to hex**: divide repeatedly by 16, read remainders bottom to top.

```
255 / 16 = 15 remainder 15 → FF
1000 / 16 = 62 remainder 8, 62 / 16 = 3 remainder 14 → 3E8
```

In practice, you'll develop intuition for the common values and won't need to convert manually.

### Common Values You'll See

| Hex | Decimal | What It Is |
|-----|---------|-----------|
| `0x00` | 0 | Zero, null terminator |
| `0x0A` | 10 | Newline character (`\n`) |
| `0x0D` | 13 | Carriage return (`\r`) |
| `0x20` | 32 | Space character |
| `0x30` | 48 | ASCII `'0'` |
| `0x41` | 65 | ASCII `'A'` |
| `0x61` | 97 | ASCII `'a'` |
| `0xFF` | 255 | Maximum unsigned byte, 8 bits all set |
| `0xFFFF` | 65535 | Maximum unsigned 16-bit value |
| `0xFFFF0000` | — | UART base address on the MPU |
| `0x10000` | 65536 | 64 KB — initial stack pointer |

### Hex in the MPU Assembler

The assembler uses the `0x` prefix for hex literals:

```
ld.32   r1, #0xFF           ; r1 = 255
ld.32   r2, #0x1234          ; r2 = 4660
st.8    0xFFFF0000, r1      ; write to UART at hex address
```

You can also use plain decimal (`#255`) or binary (`#0b11111111`). But hex is conventional for addresses and bit masks, because it maps directly to the underlying bits.

### Bit Masks

Hex is especially natural for bit manipulation. Each hex digit controls 4 bits independently:

```
0x0F = 0000 1111     (lower nibble mask)
0xF0 = 1111 0000     (upper nibble mask)
0xFF = 1111 1111     (full byte mask)
0x80 = 1000 0000     (bit 7 only — sign bit of a byte)
```

When you see `and.32 r1, #0xFF`, you immediately know: "keep the lower 8 bits, clear everything else." In decimal that would be `and.32 r1, #255`, which doesn't tell you anything about bits.

---

## 4. A Brief History of Instruction Sets

The **instruction set architecture** (ISA) is the language a CPU speaks. It defines what instructions exist, how they're encoded in binary, how many registers there are, and how memory is accessed. The ISA is the contract between hardware and software.

### CISC: The Complex Approach

Early microprocessors like the Intel 8086 (1978) and Motorola 68000 (1979) used **Complex Instruction Set Computing** (CISC). The idea was to make assembly programming easier by giving the CPU powerful, high-level instructions. The 68000 had instructions that could read from memory, compute, and write back in a single operation. It had many addressing modes, variable-length instructions (2 to 10 bytes), and special instructions for string operations, BCD arithmetic, and more.

This made assembly code compact and expressive, but it made the hardware complex. Each instruction could take a wildly different number of clock cycles. The control unit needed a microcode ROM to sequence the internal steps. The processor became hard to pipeline (overlap multiple instructions in flight).

The x86 line continued this tradition. By the time the Pentium arrived, the processor was internally translating CISC instructions into simpler micro-operations just to make the pipeline work. The ISA became a compatibility layer, not a description of what the hardware actually does.

### RISC: The Simplicity Revolution

In the 1980s, researchers at Berkeley and Stanford asked: what if we threw away the complex instructions and made every instruction simple, fast, and the same size? **Reduced Instruction Set Computing** (RISC) was born. The key insights were:

- **Fixed-width instructions** are easy to decode. The hardware can fetch and decode the next instruction without knowing what the current one is.
- **Load/store architecture**: only load and store instructions touch memory. All computation happens between registers. This simplifies the pipeline.
- **Many registers**: since memory access is slow, give the programmer more registers to work with.
- **Simple operations**: each instruction does one thing. Complex operations are built from sequences of simple ones.

The MIPS R2000 (1985), SPARC (1987), and ARM (1985) followed this philosophy. ARM in particular found a sweet spot: simple enough to implement in few transistors, powerful enough to be useful. Today ARM derivatives power virtually every phone on the planet.

RISC-V (2010) continued the tradition as an open standard, designed from scratch without legacy baggage. Its base integer ISA has just 47 instructions.

### Where the MPU Fits

The MPU is a RISC design, but it pushes the simplicity further than most. Only 19 instructions. Only 8 registers. Fixed 32-bit instruction width. One addressing mode system (the AGU) shared across all instructions that need an operand. No flags register, no interrupts, no virtual memory, no caches. Just the bare essence of what a CPU needs to be useful.

And yet it runs C. It has a printf. It fits on a $30 FPGA board. The entire processor, memory system, UART, and bootloader are about 500 lines of Verilog. You can read every line, understand every signal, and trace an instruction from fetch to writeback.

That is the beauty of this design.

---

## 5. Enter the MPU

The MPU (Minimal Processing Unit) is a 32-bit RISC processor designed from scratch to fit on a small FPGA. It was born from a desire to build something real, something you can hold in your hand, where you understand every part of the machine: the hardware, the instruction set, the assembler, the compiler, and the programs.

Here's what defines it:

- **32-bit architecture**: addresses, registers, and instructions are all 32 bits.
- **8 registers**: r0 through sp. r0 is always zero. sp is the stack pointer.
- **19 instructions**: NOP, LD, LDH, ST, ADD, SUB, six branches, AND, OR, XOR, SHL, SHR, CALL, RET.
- **Unified instruction format**: every instruction is 32 bits with the same field layout.
- **Address Generation Unit (AGU)**: one flexible system handles all operand addressing for nine different instructions.
- **Memory-mapped I/O**: the UART and LEDs appear as memory addresses. No special I/O instructions needed.
- **UART bootloader**: programs are uploaded over a serial connection at 115,200 baud.
- **Complete toolchain**: assembler, C compiler, simulator, and upload tool, all in Python.

---

## 6. What Is an FPGA?

Before we talk about the MPU's hardware, you need to know what it's built on.

An **FPGA** (Field-Programmable Gate Array) is a chip full of configurable logic blocks connected by a programmable routing network. Unlike a normal CPU, which has a fixed design etched into silicon at the factory, an FPGA's internal wiring can be changed after manufacturing. You describe the circuit you want in a hardware description language (like Verilog), run it through a synthesis tool, and upload the resulting **bitstream** to the FPGA. The chip reconfigures itself to become that circuit.

Think of it like this: a CPU is a finished building. An FPGA is a warehouse full of walls, doors, and wiring that you can arrange into any building you want.

### What's Inside

An FPGA contains thousands of small building blocks:

- **Look-Up Tables (LUTs)**: small truth tables that implement any Boolean function of a few inputs. A 4-input LUT can compute any function of 4 bits. These are the basic logic elements.
- **Flip-flops**: one-bit memory cells that store state, clocked by the system clock. Every LUT typically comes paired with a flip-flop.
- **Routing fabric**: a grid of programmable interconnects that wire LUTs and flip-flops together. The synthesis tool decides which wires connect to where.
- **Block RAM**: dedicated memory blocks for larger storage (kilobytes).
- **SPRAM**: on some FPGAs (like the iCE40UP5K), large single-port RAM blocks. The MPU uses two of these for its 64 KB memory.
- **Hard IP blocks**: fixed-function hardware like PLLs (clock multipliers), SPI controllers, or I2C interfaces.

The iCE40UP5K that the MPU runs on has about 5,280 LUTs, 128 KB of SPRAM, and 120 KB of block RAM. That's small by modern FPGA standards, but it's enough to build a complete 32-bit processor with UART, bootloader, and LED control.

### How a Design Becomes a Chip

The flow from code to running hardware:

```
Verilog source  --->  Yosys (synthesis)  --->  nextpnr (place & route)  --->  bitstream  --->  FPGA
   (.v files)           logic netlist           physical layout              (.bin file)
```

1. **Synthesis** (Yosys): translates your Verilog into a netlist of LUTs, flip-flops, and RAM blocks. This is like compiling code, but for hardware.
2. **Place and Route** (nextpnr): assigns each logic element to a physical location on the FPGA and routes the wires between them. This is the hard part, it's a constraint-satisfaction problem.
3. **Bitstream generation**: encodes the placement and routing into a binary file that the FPGA understands.
4. **Upload**: the bitstream is sent to the FPGA (usually over USB). The chip reconfigures in milliseconds.

The entire MPU toolchain uses **open-source** tools: Yosys for synthesis and nextpnr for place-and-route. No vendor licenses, no proprietary software. This matters because it means anyone can build and modify the MPU without asking permission.

### Why an FPGA Instead of a Real Chip?

Fabricating a custom silicon chip (an ASIC) costs hundreds of thousands of dollars and takes months. You get one shot: if the design has a bug, you throw away the wafers and start over.

An FPGA lets you iterate in seconds. Change a line of Verilog, re-synthesize, upload, test. If there's a bug, fix it and upload again. The MPU went through dozens of revisions this way, from first instruction fetch to running C programs with printf.

The trade-off is performance and efficiency. An FPGA is slower and uses more power than a purpose-built chip. The MPU runs at 12 MHz on the iCE40UP5K. In custom silicon, the same design could run at hundreds of MHz. But for learning, experimenting, and building something real, an FPGA is unbeatable.

---

## 7. The Hardware

The MPU runs on the **iCESugar 1.5** development board, which carries a Lattice **iCE40UP5K** FPGA. The MPU uses 64 KB of the FPGA's SPRAM for both program and data memory.

### The System on Chip

```
              +------------------------------------------+
              |              iCE40UP5K FPGA              |
              |                                          |
 USB/UART <-->|  UART RX --> Bootloader --> SPRAM (64KB) |
              |                              ^           |
              |                              |           |
              |                     MPU Core (32-bit)    |
              |                       |     |            |
              |                       v     v            |
              |                  UART TX   LED Register  |
              |                    |          |          |
              +--------------------+----------+----------+
                                   |          |
                                 TX pin    RGB LEDs
```

When the board powers on, the **bootloader** takes control. It listens on the UART, receives a program binary byte by byte, and writes it into SPRAM starting at address 0. Once the transfer is complete, the bootloader releases the MPU from reset. The MPU begins fetching instructions from address 0 and runs the program.

This means you don't need to re-synthesize the FPGA to run a different program. Just send a new binary over the serial port. The development cycle is: edit assembly (or C), assemble, upload, run.

### Memory Map

| Address Range | What Lives There |
|---|---|
| `0x00000000 - 0x0000FFFF` | SPRAM: 64 KB of program and data memory |
| `0xFFFF0000` | UART TX: write a byte here to send it over serial |
| `0xFFFF0004` | UART status: bit 0 = busy (read to check if TX is done) |
| `0xFFFF0008` | LED register: bits [2:0] control blue, red, green |

There is no ROM, no flash, no separate instruction and data memory. Everything is in one flat address space. The program, the stack, the data, and the I/O devices all share the same 32-bit address bus.

---

## 8. Architecture at a Glance

### Registers

| Register | Purpose |
|---|---|
| r0 | Hardwired to zero. Writes are ignored. Reads always return 0. |
| r1 - r6 | General purpose. Use them for anything. |
| sp | Stack pointer. Initialized to 0x10000 (top of 64 KB). Grows downward. |

Having r0 hardwired to zero is a classic RISC trick. It gives you a constant you always need without burning an instruction to load it. It also lets you express common operations elegantly:

- `ld.32 r1, r0` clears r1 (move zero into it).
- `beq.32 r0, #0, target` is an unconditional jump (r0 always equals 0).
- `[r0][r3]` means "the address in r3" (base of zero plus index).

### The Pipeline

The MPU uses a 5-stage state machine, not a pipelined design (one instruction at a time, no overlapping):

```
FETCH --> DECODE --> EXECUTE --> MEM --> WB
```

- **FETCH**: send the PC to memory, request a 32-bit read.
- **DECODE**: latch the instruction from memory into the instruction register.
- **EXECUTE**: decode fields, run the AGU, perform ALU operations, or start a memory access. Simple instructions (NOP, branches, immediate ALU) complete here and go directly back to FETCH.
- **MEM**: wait for memory to respond (for loads, stores, CALL, RET).
- **WB**: write the result to the register file. Apply AGU writeback (post-increment).

Simple instructions (immediate add, register move, branches) take 3 cycles: FETCH, DECODE, EXECUTE. Memory instructions take 5 cycles: all five stages. At 12 MHz, that's 250 ns for a simple instruction, 417 ns for a memory instruction.

---

## 9. The Beauty of the Instruction Format

This is where the MPU design really shines. Every instruction is 32 bits, and they all share the same layout:

```
 31    27 26  24 23 22 21 20 19                  0
+--------+------+-----+--+--+--------------------+
| opcode |  rd  | size|rv|ai|      payload        |
+--------+------+-----+--+--+--------------------+
   5 bit   3 bit  2 b  1  1       20 bits
```

Five bits of opcode give room for 32 instructions (19 are used). Three bits of rd select one of 8 registers. Two bits of size select byte/halfword/word. One bit (`rv`) selects between register and immediate/absolute addressing. One bit (`ai`) distinguishes immediate values from absolute addresses. And the remaining 20 bits are the payload.

### Why This is Elegant

**Uniformity**: the decoder doesn't need to look at the opcode to know where the fields are. The opcode, register, size, and addressing mode are always in the same bit positions. This makes the hardware trivially simple: you wire bits [31:27] to the opcode decoder, bits [26:24] to the register file, and so on. No variable-length instruction complications, no mode-dependent field positions.

**Orthogonality**: nine instructions (LD, ST, ADD, SUB, AND, OR, XOR, SHL, SHR) all route their payload through the same Address Generation Unit. The AGU doesn't know or care which instruction is asking. It just decodes the addressing mode and produces either an effective address or an immediate value. This means every ALU instruction can work with a register, an immediate, a memory indirect, or a post-increment load, all for free. The hardware cost of supporting `add.32 r1, [r2][r3+=4]` is zero beyond what LD already needed.

**Composability**: the few instructions combine to express complex operations:

- No PUSH/POP? Use `st.32 [sp+=-4], r1` (store and decrement) and `ld.32 r1, [sp+=4]` (load and increment).
- No MOV? Use `ld.32 r1, r2` (register-direct AGU mode).
- No NOT? Use `xor.32 r1, #-1` (XOR with all ones).
- No NEG? Use `xor.32 r1, #-1` then `add.32 r1, #1` (two's complement).
- No unconditional jump? Use `beq.32 r0, #0, target` (r0 is always zero).
- No NOP? Well, there is one, but `add.32 r0, #0` would also work.

This is the RISC philosophy at its purest: a small number of composable primitives that cover a large space of operations. Every special case was resisted. There is no instruction that does something only one instruction can do, except where the hardware truly requires it (CALL and RET, which manipulate both the stack and the PC atomically).

---

## 10. Your First Program: Hello, World!

Let's write the classic first program. The MPU has a UART for serial output: write a byte to address `0xFFFF0000` and it gets sent out at 115,200 baud. Write to `0xFFFF0004` to read whether the transmitter is busy.

```
; hello.asm - Hello, World! for the MPU

                ld.32   r6, #hello      ; r6 = pointer to string
.loop:
                ld.8    r1, [r6++]      ; load next byte, advance pointer
                beq.8   r1, #0, stop    ; if null terminator, we're done
                call    output          ; print the character
                jmp     .loop           ; next character

stop:           jmp     stop            ; halt (infinite loop)

; Subroutine: send byte in r1 to UART
output:
.wait:          ld.32   r2, 0xFFFF0004  ; read UART status
                bne.8   r2, #0, .wait   ; loop while busy
                st.8    0xFFFF0000, r1  ; send the byte
                ret

; The string data
hello:          db      'Hello, world!\0'

                end
```

Let's walk through this line by line.

**`ld.32 r6, #hello`** loads the address of the `hello` label into r6. The `#` means immediate: the assembler resolves `hello` to its address and encodes it as a 20-bit value in the payload. After this, r6 points to the first byte of "Hello, world!".

**`ld.8 r1, [r6++]`** is where the AGU shows its power. This is shorthand for `ld.8 r1, [r0][r6+=1]`: load one byte from the address in r6 (base r0 + index r6), then increment r6 by 1. It reads the current character and advances the pointer in a single instruction. This is post-increment addressing mode (mode 11).

**`beq.8 r1, #0, stop`** checks if the byte we just loaded is zero (the null terminator). The `.8` suffix means the comparison uses only the lower 8 bits, sign-extended. If r1 is zero, we branch to `stop`.

**`call output`** pushes the return address onto the stack and jumps to the `output` subroutine. Internally: sp decreases by 4, the address of the next instruction (PC + 4) is written to [sp], and PC is set to the address of `output`.

**`jmp .loop`** is the pseudo-instruction for `beq.32 r0, #0, .loop`. Since r0 is always zero and the immediate is zero, the branch is always taken. Unconditional jump.

**`ld.32 r2, 0xFFFF0004`** loads from an absolute address. No `#`, no brackets: the assembler encodes this as reg_value=1, addr_imm=0, meaning the payload is a memory address, not an immediate. The UART status register is read into r2.

**`bne.8 r2, #0, .wait`** loops back if the UART busy flag (bit 0) is nonzero. The `.8` suffix means we only look at the lower byte.

**`st.8 0xFFFF0000, r1`** writes the lower byte of r1 to the UART transmit register. This is what actually sends the character out the serial port.

**`ret`** pops the return address from the stack and jumps to it. Internally: PC is loaded from [sp], then sp increases by 4.

**`db 'Hello, world!\0'`** defines raw bytes in the program. The string is placed in memory right after the code. The `\0` is the null terminator.

### Running It

```bash
python3 toolchain/asm.py hello.asm           # assemble to hello.mpu
python3 toolchain/run.py hello.mpu           # upload via UART and run
```

Connect a terminal to the serial port at 115,200 baud and you'll see: `Hello, world!`

---

## 11. Understanding Memory

The MPU has a flat, unified memory space. Programs and data share the same 64 KB of SPRAM. There is no separation between code and data, no memory protection, no virtual memory. Address 0 is where the first instruction lives. The stack starts at address 0x10000 (the top of the 64 KB) and grows downward.

### Sizes

Memory can be accessed in three sizes:

| Suffix | Width | Use Case |
|---|---|---|
| `.8` | 1 byte | Characters, flags, small values |
| `.16` | 2 bytes | 16-bit values |
| `.32` | 4 bytes | Addresses, integers, most data |

When you load a `.8` or `.16` value, only the corresponding bits of the destination register are written; the upper bits are preserved. When you store, only the relevant bytes are written.

### Byte Ordering

The MPU is **little-endian**: the least significant byte is stored at the lowest address. A 32-bit value `0xDEADBEEF` at address 0x100 is laid out as:

```
Address:  0x100  0x101  0x102  0x103
Value:     0xEF   0xBE   0xAD   0xDE
```

### Alignment

Memory accesses should be naturally aligned: `.32` reads from addresses divisible by 4, `.16` from addresses divisible by 2. The SPRAM interface relies on alignment for correct byte extraction.

### Example: Storing and Loading Data

```
; Store the value 42 at address 0x200, then load it back
                ld.32   r1, #42
                ld.32   r2, #0x200
                st.32   [r2], r1         ; mem[0x200] = 42
                ld.32   r3, [r2]         ; r3 = mem[0x200] = 42
```

---

## 12. Working with Registers

With only 8 registers, you must think carefully about allocation. Here are the conventions:

| Register | Typical Use |
|---|---|
| r0 | Zero constant. Always available for "nothing". |
| r1 | Temporary / return value / function argument. |
| r2 - r4 | Temporaries. Subroutines may clobber these freely. |
| r5 - r6 | Callee-saved. Subroutines must save and restore them. |
| sp | Stack pointer. Touched only for push/pop/call/ret. |

### Loading Values

Small values (that fit in 20 bits signed, i.e., -524288 to 524287):

```
                ld.32   r1, #100         ; r1 = 100
                ld.32   r1, #-1          ; r1 = 0xFFFFFFFF
```

Large 32-bit values require LD + LDH:

```
                ld.32   r1, #0xDBEEF     ; r1 = sign_ext(0xDBEEF) = 0xFFFDBEEF
                ldh     r1, #0xDEADB     ; r1[31:12] = 0xDEADB -> r1 = 0xDEADBEEF
```

The trick: LD sets all 32 bits (via sign extension of the 20-bit immediate), then LDH overwrites the upper 20 bits while preserving the lower 12. Together they can construct any 32-bit value in two instructions.

### Register-to-Register Operations

```
                ld.32   r1, r2           ; r1 = r2 (copy)
                add.32  r1, r2           ; r1 = r1 + r2
                sub.32  r1, r2           ; r1 = r1 - r2
                and.32  r1, r2           ; r1 = r1 & r2
                xor.32  r1, r2           ; r1 = r1 ^ r2
```

These all use AGU mode 00 (register direct), where the payload encodes a register select and the AGU returns that register's value as the operand. The MPU doesn't need a separate "register-register" instruction encoding, as the AGU gives it for free.

### Clearing a Register

```
                ld.32   r1, r0           ; r1 = 0 (copy from r0)
                ld.32   r1, #0           ; also works (immediate zero)
```

The first form uses the register-direct AGU mode. The second uses the immediate path. Both produce the same result. The register form is one cycle shorter on the pipeline (no memory access needed either way, but it's a stylistic choice).

---

## 13. The Address Generation Unit

The AGU is the heart of the MPU's operand system. Understanding it is the key to writing efficient code.

Nine instructions route their operand through the AGU: **LD, ST, ADD, SUB, AND, OR, XOR, SHL, SHR**. The AGU decodes the 20-bit payload and produces either an effective memory address or an immediate value. The instruction itself doesn't care which, it just uses whatever the AGU gives it.

### Mode Summary

When `rv=1` (bit 21), the payload is an immediate or absolute address:

```
rv=1, ai=1:  #value          Immediate. The 20-bit payload, sign-extended.
rv=1, ai=0:  address         Absolute. Memory is read/written at this address.
```

When `rv=0` (bit 21), the payload encodes registers and an addressing mode:

```
 19   17 16 15 14  12 11              0
+-------+-----+------+----------------+
|  base | mode| index|     offset     |
+-------+-----+------+----------------+
```

| Mode | Syntax | Meaning |
|---|---|---|
| 00 | `Rbase` | Register direct: operand is the value of Rbase |
| 01 | `[Rbase][Ridx]` | Indexed: memory at Rbase + Ridx |
| 10 | `[Rbase][Ridx+off]` | Indexed + offset: memory at Rbase + Ridx + sign_ext(off) |
| 11 | `[Rbase][Ridx+=off]` | Post-increment: memory at Rbase + Ridx, then Ridx += sign_ext(off) |

### Why This is Powerful

Consider what you get from these four modes:

**Simple register access** (mode 00): `add.32 r1, r3` means "add the value in r3 to r1." The AGU returns r3's value as an immediate.

**Array indexing** (mode 01): `ld.32 r1, [r2][r3]` loads from address r2+r3. If r2 is the base of an array and r3 is an offset, this is array[offset].

**Struct field access** (mode 10): `ld.32 r1, [r2][r0+8]` loads from r2+8. The constant offset 8 selects a specific field within a structure pointed to by r2.

**String/array traversal** (mode 11): `ld.8 r1, [r0][r6+=1]` loads a byte from r6 and increments r6 by 1 after. This is the classic `*ptr++` operation. You can walk through an array without a separate increment instruction.

**Stack push/pop**: `st.32 [r0][sp+=-4], r1` decrements sp by 4 and stores r1. This is `push`. `ld.32 r1, [r0][sp+=4]` loads and increments sp by 4. This is `pop`. No dedicated push/pop instructions needed.

### Assembler Shorthands

The assembler provides shortcuts for common patterns:

| You Write | It Becomes | Why |
|---|---|---|
| `[r3]` | `[r0][r3]` | Base is zero, so address = 0 + r3 = r3 |
| `[r6++]` | `[r0][r6+=1]` | Post-increment by 1 |
| `[r6--]` | `[r0][r6+=-1]` | Post-decrement by 1 |
| `[sp+=-4]` | `[r0][sp+=-4]` | Pre-decrement (used for push) |

---

## 14. Branching and Loops

The MPU has six branch instructions: BEQ, BNE, BLT, BGT, BLE, BGE. They all follow the same format:

```
branch.size rd, comparand, target
```

The comparand is either a register or a small immediate (0-7). The target is a 16-bit absolute address, covering the full 64 KB.

All comparisons are **signed**. The size suffix controls the comparison width: `.8` sign-extends both operands from 8 bits, `.16` from 16 bits, `.32` uses the full value.

### A Simple Loop

Count from 1 to 10, printing each digit:

```
; count.asm - Count 1 to 10

                ld.32   r3, #1           ; r3 = counter, starting at 1
                ld.32   r4, #10          ; r4 = limit

.loop:          ld.32   r1, r3           ; r1 = current count
                add.32  r1, #48          ; convert to ASCII ('0' = 48)
                call    output           ; print digit
                ld.32   r1, #10          ; newline
                call    output

                add.32  r3, #1           ; counter++
                ble.32  r3, r4, .loop    ; loop while counter <= 10

.halt:          jmp     .halt            ; done

output:
.wait:          ld.32   r2, 0xFFFF0004
                bne.8   r2, #0, .wait
                st.8    0xFFFF0000, r1
                ret

                end
```

The key line is `ble.32 r3, r4, .loop`: "branch to .loop if r3 <= r4 (signed)." When r3 reaches 11, the condition fails and execution falls through to the halt loop.

### Conditional Execution

There's no conditional move or predicated execution. Use branches:

```
; r1 = abs(r1)
                bge.32  r1, #0, .positive
                xor.32  r1, #-1          ; bitwise NOT
                add.32  r1, #1           ; +1 = two's complement negate
.positive:
```

### While Loop Pattern

```
; while (r3 != 0) { body }
.while:         beq.32  r3, #0, .end
                ; ... body ...
                jmp     .while
.end:
```

### Do-While Loop Pattern

```
; do { body } while (r3 != 0);
.top:
                ; ... body ...
                bne.32  r3, #0, .top
```

---

## 15. Subroutines and the Stack

The MPU has dedicated CALL and RET instructions that use sp as the stack pointer.

**CALL** does three things atomically:
1. Decrement sp by 4.
2. Store the return address (PC + 4) to the new [sp].
3. Set PC to the target address.

**RET** does the reverse:
1. Load PC from [sp].
2. Increment sp by 4.

### A Complete Subroutine

```
; multiply r1 by r2, result in r1
; Uses r3 as accumulator (caller-saved)
multiply:
                ld.32   r3, #0           ; accumulator = 0
.loop:          beq.32  r2, #0, .done    ; while r2 != 0
                add.32  r3, r1           ;   accumulator += r1
                sub.32  r2, #1           ;   r2--
                jmp     .loop
.done:          ld.32   r1, r3           ; result in r1
                ret
```

### Saving and Restoring Registers

If your subroutine uses registers that the caller might need, save them on the stack:

```
my_function:
                ; prologue: save callee-saved registers
                st.32   [sp+=-4], r6     ; push r6
                st.32   [sp+=-4], r5     ; push r5

                ; ... function body using r5 and r6 ...

                ; epilogue: restore and return
                ld.32   r5, [sp+=4]      ; pop r5
                ld.32   r6, [sp+=4]      ; pop r6
                ret
```

The push/pop pattern uses the AGU post-increment mode: `[sp+=-4]` decrements sp by 4 after computing the address (push), and `[sp+=4]` increments sp by 4 after loading (pop).

### Passing Arguments

Arguments are passed on the stack. The caller pushes arguments right-to-left, calls the function, then cleans up the stack after:

```
; calling putchar('A')
                ld.32   r1, #65          ; 'A'
                st.32   [sp+=-4], r1     ; push argument
                call    putchar
                add.32  sp, #4           ; clean up stack (1 arg * 4 bytes)
```

Inside the function, arguments are accessed relative to sp with an offset that accounts for the saved registers and the return address.

### Stack Frame Layout

After a function saves r6 and r5:

```
Address        Contents
sp + 12       argument 0  (pushed by caller)
sp + 8        return address  (pushed by CALL)
sp + 4        saved r6  (pushed by function)
sp + 0        saved r5  (pushed by function)   <-- sp points here
```

To access argument 0: `ld.32 r1, [sp][r0+12]` (base sp, index r0=0, offset 12).

---

## 16. Bit Manipulation

The MPU has AND, OR, XOR, SHL, and SHR. These are the building blocks for all bit-level operations.

### Common Patterns

**Extract a bit field:**

```
; Extract bits [7:4] of r1 into r1
                shr.32  r1, #4           ; shift right by 4
                and.32  r1, #0xF         ; mask to 4 bits
```

**Set a bit:**

```
; Set bit 3 of r1
                or.32   r1, #8           ; 8 = 1 << 3
```

**Clear a bit:**

```
; Clear bit 3 of r1 (need the inverted mask)
                ld.32   r2, #8           ; mask
                xor.32  r2, #-1          ; invert: r2 = 0xFFFFFFF7
                and.32  r1, r2           ; clear bit 3
```

**Toggle a bit:**

```
; Toggle bit 3 of r1
                xor.32  r1, #8           ; flip bit 3
```

**Bitwise NOT:**

```
                xor.32  r1, #-1          ; r1 = ~r1
```

**Multiply by a power of 2:**

```
                shl.32  r1, #3           ; r1 = r1 * 8
```

**Unsigned divide by a power of 2:**

```
                shr.32  r1, #3           ; r1 = r1 / 8 (unsigned)
```

---

## 17. A Complete Program: Counting

Let's put it all together. This program counts from 0 to 99 and prints each number to the UART with a newline:

```
; count99.asm - Print numbers 0 through 99

                ld.32   r3, #0           ; counter
                ld.32   r6, #10          ; constant 10 (too large for branch immediate)

.loop:
                ; Compute tens digit
                ld.32   r1, r3           ; r1 = counter
                ld.32   r5, #0           ; tens = 0
.tens:          blt.32  r1, r6, .units   ; r1 < 10?
                sub.32  r1, r6
                add.32  r5, #1
                jmp     .tens

.units:
                ; r5 = tens digit, r1 = units digit
                ; Print tens digit (skip if zero and counter < 10)
                blt.32  r3, r6, .skip_tens
                ld.32   r2, r5
                add.32  r2, #48          ; ASCII '0'
                st.8    0xFFFF0000, r2
                ld.32   r4, #1500
.w1:            sub.32  r4, #1
                bne.32  r4, #0, .w1

.skip_tens:
                ; Print units digit
                add.32  r1, #48          ; ASCII '0'
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.w2:            sub.32  r4, #1
                bne.32  r4, #0, .w2

                ; Print newline
                ld.32   r1, r6           ; 10 = '\n'
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.w3:            sub.32  r4, #1
                bne.32  r4, #0, .w3

                ; Increment and loop
                add.32  r3, #1
                ld.32   r4, #100
                blt.32  r3, r4, .loop

.halt:          jmp     .halt

                end
```

This program demonstrates several techniques:

- **Division by subtraction**: to get the tens digit, repeatedly subtract 10 until the value is less than 10.
- **Conditional output**: the tens digit is skipped for single-digit numbers.
- **UART delay loops**: after each byte sent, we wait about 1500 iterations for the UART to finish transmitting.
- **Multi-register coordination**: r3 holds the counter across the outer loop, r5 holds the tens digit, r1 the units digit.

It's not the most efficient way to print numbers (the stdlib's printf does it more cleverly with a powers-of-10 table), but it shows how much you can do with a handful of instructions and some creative register use.

---

## 18. From C to Assembly

The MPU comes with a C compiler (`toolchain/cc.py`) that translates a subset of C into assembly. The assembly is then assembled and linked with the standard library.

Here's a simple C program:

```c
int main() {
    printf("Hello 1+2=%d", 1 + 2);
}
```

The compiler generates:

```
                jmp     __start

main:
                sub.32  sp, #4
                st.32   [sp], r6             ; save return address register
                ld.32   r1, #1
                add.32  r1, #2               ; compute 1 + 2 = 3
                sub.32  sp, #4
                st.32   [sp], r1             ; push argument: 3
                ld.32   r1, #__str_1
                sub.32  sp, #4
                st.32   [sp], r1             ; push argument: format string
                call    printf
                add.32  sp, #8               ; clean up 2 arguments
.epilogue:
                ld.32   r6, [sp+=4]          ; restore saved register
                ret

__start:
                call    main
.__halt:        jmp     .__halt

__str_1: db 'Hello 1+2=%d\0'
```

The compiler generates straightforward code: compute the expression, push arguments right-to-left, call the function, clean up the stack. The `__start` entry point calls `main` and halts when it returns.

The standard library (linked after the compiled code) provides `printf`, `putchar`, `puts`, `sleep`, and `setleds`.

### The Development Workflow

```
    C source          Assembly            Binary
   printf.c  ------>  printf.asm  ------>  printf.mpu  ------> MPU
              cc.py                asm.py               run.py
```

Or write assembly directly:

```
   hello.asm  ------>  hello.mpu  ------> MPU
               asm.py              run.py
```

You can also use the simulator to test without hardware:

```bash
python3 toolchain/sim.py hello.mpu
```

The simulator executes instructions step by step, printing UART output and optionally showing register state and memory traces.

---

## 19. Closing Thoughts

The MPU is not fast. It's not practical for production use. It can't run an operating system or browse the web. But that's not the point.

The point is that you can *understand it*. All of it. The Verilog is about 500 lines. The assembler is a single Python file. The instruction set fits on one page. You can trace a `ld.8 r1, [r6++]` instruction from the moment it's fetched as four bytes from SPRAM, through the decoder, into the AGU, out to the memory bus, back into the register file, and watch r6 increment by 1 in the writeback stage. You can do this because the machine is small enough to fit in your head.

The great processors of the 1970s had this quality. The 6502, the Z80, the 68000: they were machines that one person could master completely. The MPU carries that spirit forward. It's not a replica of those machines. It's a new design, built with modern tools (FPGAs, open-source synthesis, Python toolchains), but guided by the same principle: **simplicity is a feature, not a limitation.**

The AGU is the design's signature idea. Instead of hard-coding addressing modes into individual instructions, a single unit handles operand decoding for all instructions uniformly. This gives nine instructions the full power of register-direct, immediate, absolute, indexed, indexed-with-offset, and post-increment addressing, at no additional hardware cost per instruction. The AGU is written once and wired to every instruction that needs an operand. That's the kind of decision that makes a design elegant rather than merely functional.

If you want to go further:

- Read `mpu/mpu.v` and `mpu/agu.v`. The entire processor is there.
- Read `toolchain/asm.py`. The assembler is one file, under 600 lines.
- Write your own programs. Start with blinking the LED. Move to string processing. Try implementing a simple game.
- Modify the hardware. Add a new instruction. Add a timer. Add a second UART.

The machine is yours. Every bit of it.
