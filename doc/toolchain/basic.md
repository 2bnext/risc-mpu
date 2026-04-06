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

## Expressions

### Operators

| Category    | Operators                                       |
|-------------|-------------------------------------------------|
| Arithmetic  | `+ - * /` (integer)                             |
| Comparison  | `=  <>  <  >  <=  >=`                           |
| Logical     | `AND`, `OR` (bitwise on integers)               |
| String ops  | `+` (concatenation), `=`, `<>`                  |
| Grouping    | `( ... )`                                       |
| Unary       | `-x`                                            |

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

| Function    | Returns | Description                                     |
|-------------|---------|-------------------------------------------------|
| `MALLOC(n)` | int     | Allocates `n` bytes from the heap, returns ptr  |
| `PEEK(addr)`| int     | Reads one byte from memory (zero-extended)      |

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
