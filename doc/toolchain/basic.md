# MPU BASIC Compiler

`toolchain/basic.py` is a Tiny BASIC compiler in the spirit of the 1980s home-computer dialects (Microsoft / Commodore / Tiny BASIC). Programs are compiled — not interpreted — to MPU machine code, the same way `cc.py` produces code for C.

## Usage

```sh
python3 toolchain/basic.py program.bas        # writes program.s
python3 toolchain/basic.py program.bas out.s
```

The Makefile in `testing/` recognises `.bas` files automatically:

```sh
make demo.mpu       # demo.bas -> demo.s -> demo.mpu
```

## Program structure

A BASIC program is a sequence of numbered lines. Lines may contain multiple statements separated by `:`. Whitespace and case do not matter (everything is folded to upper case).

```basic
10 PRINT "HELLO, WORLD!"
20 FOR I = 1 TO 5 : PRINT I : NEXT I
30 END
```

Line numbers double as labels — `GOTO` and `GOSUB` jump to a line number directly. They do not need to be sequential, but it is conventional to leave gaps (10, 20, 30, …) so you can insert lines later.

## Variables and types

There are two kinds of variables, distinguished by suffix:

| Suffix | Type    | Example       | Notes                              |
|--------|---------|---------------|-------------------------------------|
| (none) | integer | `A`, `COUNT`  | Signed 32-bit                       |
| `$`    | string  | `A$`, `NAME$` | Pointer to a null-terminated string |

`A` and `A$` are independent variables. All variables are global; integer variables start at 0, string variables start pointing at the empty string. Names may be one or more letters/digits and are case-insensitive.

## Statements

### `LET` — assignment

```basic
LET X = 42
LET A$ = "HELLO"
```

The `LET` keyword is optional:

```basic
X = 42
```

### `PRINT`

`PRINT` accepts any number of items separated by `;` or `,` (treated identically — no zone formatting). String literals, numbers, and variables of either type can be mixed:

```basic
PRINT "X="; X; " NAME="; A$
```

A trailing `;` or `,` suppresses the newline. `PRINT` with no arguments prints just a newline.

### `IF ... THEN ...`

```basic
IF X > 10 THEN PRINT "BIG"
IF X = Y THEN 200          : REM implicit GOTO 200
IF A$ = "STOP" THEN END
```

`THEN` may be followed by either a line number (implicit `GOTO`) or any other statement. There is no `ELSE`.

### `FOR ... NEXT`

```basic
FOR I = 1 TO 10
  PRINT I
NEXT I

FOR J = 0 TO 100 STEP 5
  PRINT J
NEXT J
```

`STEP` is assumed non-negative — the `NEXT` exit test uses `<=`. If you want a downward loop, fake it with arithmetic.

The limit and step are evaluated **once** when the loop starts (matching MS BASIC behaviour).

### `GOTO` / `GOSUB` / `RETURN`

```basic
100 PRINT "FUNC"
110 GOSUB 1000
120 GOTO 100

1000 PRINT "  IN SUB"
1010 RETURN
```

`GOSUB` is implemented as a `call` to the target line label, `RETURN` as `ret`. Subroutines may nest and recurse, limited only by stack space (~4 KiB).

### `END`

Halts the program. Falling off the end of the program also halts.

### `REM`

Comment to end of line. The whole rest of the line after `REM` is discarded by the lexer, so you can write whatever you want.

### `POKE`

```basic
POKE addr, value
```

Stores the low byte of `value` at memory address `addr`. Combined with `PEEK` and `MALLOC`, this lets you build byte buffers in the heap.

### `SLEEP` — busy-wait delay

```basic
SLEEP 30000        : REM ~10 ms at 12 MHz
```

The argument is loop iterations, not milliseconds. About 3000 iterations per millisecond on real hardware.

### GPIO statements

```basic
GPIODIR    0x0F        : REM gpio[0..3] outputs, gpio[4..7] inputs
GPIOWRITE  0x05        : REM drive gpio[0] and gpio[2] high
LET V = GPIOREAD()     : REM read all 8 pins (low byte)
```

`GPIODIR mask` and `GPIOWRITE value` lower to the stdlib `gpio_set_dir` / `gpio_write` calls — see [stdlib.md](stdlib.md) for the underlying register layout. `GPIOREAD()` returns the live state of all 8 GPIO pins as the low 8 bits of an integer.

### `SETLEDS`

```basic
SETLEDS 7              : REM all colors on (white)
SETLEDS 3              : REM red + green (yellow)
SETLEDS 0              : REM off
```

Drives the on-board RGB LED. Bit 0 = green, bit 1 = red, bit 2 = blue.

### I²C statements

```basic
I2CSTART
I2CWRITE 0xEC          : REM 0x76<<1 | W: BME280 address
I2CWRITE 0xD0          : REM register pointer
I2CSTART               : REM repeated start
I2CWRITE 0xED          : REM 0x76<<1 | R
LET ID = I2CREAD(1)    : REM one byte, NACK to terminate
I2CSTOP
PRINT "chip id = "; ID
```

`I2CSTART`, `I2CSTOP`, `I2CWRITE byte` are statements; `I2CREAD(ack)` is an expression that returns the received byte. Pass `ack=0` to ACK (continue reading) or `ack=1` to NACK (last byte before STOP, as required by the I²C spec). All four lower to the matching stdlib helpers; see [stdlib.md](stdlib.md) for the underlying register protocol and pull-up requirements.

## Expressions

### Number literals

```basic
LET A = 42
LET B = 0xFF        : REM hex literal
LET C = -1
```

The compiler emits `ld + ldh` for constants outside the 20-bit immediate range, so values like `1048576` or `0xE000` work just as well as small ones.

### Operators

| Category    | Operators                                       |
|-------------|-------------------------------------------------|
| Arithmetic  | `+ - * /` (integer)                             |
| Comparison  | `=  <>  <  >  <=  >=`                           |
| Bitwise     | `AND`, `OR`, `<<`, `>>`, `~` / `NOT`            |
| String ops  | `+` (concatenation), `=`, `<>`                  |
| Grouping    | `( ... )`                                       |
| Unary       | `-x`, `~x`, `NOT x`                             |

`*`, `/`, and string concatenation are runtime helper calls (no hardware multiply or divide).

### String operations

```basic
LET A$ = "HELLO"
LET B$ = ", WORLD"
LET C$ = A$ + B$           : REM concatenation -> heap
IF C$ = "HELLO, WORLD" THEN PRINT "MATCH"
IF A$ <> B$ THEN PRINT "DIFFERENT"
```

`+` on strings allocates a new string in the heap holding the concatenation. There is no string slicing, length, or character extraction in the language itself — use `MALLOC`/`POKE`/`PEEK` if you need to build strings byte-by-byte.

### Builtins

| Function       | Returns | Description                                                |
|----------------|---------|------------------------------------------------------------|
| `MALLOC(n)`    | int     | Allocates `n` bytes from the heap, returns ptr             |
| `PEEK(addr)`   | int     | Reads one byte from memory (zero-extended)                 |
| `SAR(x, n)`    | int     | Arithmetic shift right (signed `x`, the `>>` operator is logical) |
| `I2CREAD(ack)` | int     | Reads one I²C byte; `ack=0` ACKs, `ack=1` NACKs            |
| `GPIOREAD()`   | int     | Reads the live GPIO pin state (low 8 bits)                 |
| `ADCREAD()`    | int     | Reads the on-chip sigma-delta ADC (12-bit, 0..4095)        |

There is no `FREE`. The heap is a bump allocator — once used, memory is gone until the program restarts.

## Memory layout

```
0x10000  +---------------+
         |     stack     |  (grows down, ~4 KiB)
0xF000   +---------------+
         |  (free area)  |  
0xE000   +---------------+  HEAP_BASE
         |     heap      |  (grows up via __halloc / string concat)
         |               |
         |  program +    |
         |  globals +    |
         |  string lits  |
0x0000   +---------------+
```

Programs share RAM with the heap and stack. There is no protection — a runaway loop that allocates too much will collide with the stack and crash quietly.

## What is missing

- Floating point (`A!`, `A#`), single/double precision
- Arrays (`DIM`)
- `INPUT` (no UART RX from compiled BASIC, although the bootloader uses it)
- `READ`/`DATA`
- `WHILE`/`WEND`, `DO`/`LOOP`
- `ON ... GOTO/GOSUB`
- String functions: `LEN`, `MID$`, `LEFT$`, `RIGHT$`, `CHR$`, `STR$`, `VAL`
- `ELSE` clause on `IF`
- `FREE` for the heap
- Negative `STEP` in `FOR`
- File I/O of any kind

## Example

A small demo exercising most features lives at `testing/demo.bas`. Build and run it with:

```sh
cd testing
make demo.mpu
python3 ../toolchain/sim.py demo.mpu
```

A minimal example to start from:

```basic
10 REM count the digits of N in base 10
20 LET N = 12345
30 LET C = 0
40 IF N = 0 THEN GOTO 80
50 LET N = N / 10
60 LET C = C + 1
70 GOTO 40
80 PRINT "DIGITS = "; C
90 END
```
