# MPU Pascal Compiler

`toolchain/pas.py` is a tiny Pascal compiler that targets the MPU. The dialect is loosely based on Turbo Pascal — strict declarations, real procedures and functions with parameters and local variables, and `begin`/`end` blocks. Unlike `basic.py`, which has only `GOSUB`, the Pascal compiler builds proper stack frames and calling conventions, so functions can recurse and shadow each other's locals safely.

## Usage

```sh
python3 toolchain/pas.py program.pas          # writes program.mpu
python3 toolchain/pas.py -S program.pas       # also keep program.s
```

The Makefile in `testing/` recognises `.pas` files automatically:

```sh
make hello.mpu        # hello.pas -> hello.mpu
```

The standard library (`toolchain/stdlib.asm`) is appended to the generated assembly, so all stdlib functions (`printf`, `sleep`, `i2c_*`, …) are available without an `uses` clause.

## Program structure

```pascal
program hello;

const
  N = 10;

var
  i: integer;

function square(x: integer): integer;
begin
  square := x * x
end;

begin
  for i := 1 to N do
    writeln('square(', i, ') = ', square(i))
end.
```

A program has the shape `program <name>; [decls] begin <stmts> end.` — note the trailing dot, and that the final statement before `end` does not need a semicolon (Pascal's classic rule).

Identifiers and keywords are **case-insensitive**: `Square`, `SQUARE`, and `square` all refer to the same routine. Internally everything is folded to lower case.

## Comments

Three styles are accepted:

```pascal
{ a curly-brace comment, may span lines }
(* an old-school Pascal comment *)
// a line comment, extension for convenience
```

## Types

There is one numeric type: **`integer`** (32-bit signed). `char` is accepted as a synonym but is treated as a 32-bit value as well — there are no byte-sized variables. There are no records, arrays, sets, files, or strings *as a type*; string literals exist only as arguments to `write`/`writeln`.

## Constants and globals

```pascal
const
  PI100 = 314;
  MAX   = 1000;

var
  count, total: integer;
  flag: integer;
```

`const` accepts integer literals (decimal or `$hex`) and other previously-defined integer constants, with an optional unary minus. `var` declarations may group multiple names with one type.

## Procedures and functions

```pascal
procedure greet(times: integer);
var i: integer;
begin
  for i := 1 to times do
    writeln('hello')
end;

function gcd(a, b: integer): integer;
begin
  if b = 0 then
    gcd := a
  else
    gcd := gcd(b, a mod b)
end;
```

- Parameters are **value parameters only** (no `var` reference parameters in this dialect).
- Local variables are declared in a `var` block immediately after the header.
- A function returns its value by assigning to its own name (`gcd := …`). The compiler treats the function name as a hidden local.
- Recursion works — each call gets its own frame.
- `exit` returns immediately from the current routine (or halts the program if used at top level).

The calling convention matches `cc.py`: arguments are pushed right-to-left, the callee saves `r6` and reserves space for locals, the result comes back in `r1`, and the caller cleans up the argument area after the `call`.

## Statements

| Statement                                | Notes                                       |
|------------------------------------------|---------------------------------------------|
| `x := expr`                              | Assignment                                  |
| `proc(a, b)`                             | Procedure call                              |
| `begin … end`                            | Compound statement                          |
| `if c then s1 else s2`                   | `else` branch optional                      |
| `while c do s`                           | Pre-test loop                               |
| `for i := a to b do s`                   | Inclusive, `i` is updated each iteration    |
| `for i := a downto b do s`               | Counts down                                 |
| `repeat s1; s2 until c`                  | Loop until condition becomes true           |
| `writeln(...)` / `write(...)`            | Variadic — strings and integers may be mixed |
| `exit`                                   | Early return / program halt                 |

The `writeln`/`write` items are evaluated left-to-right; integer expressions are printed via `printf("%d", …)` and string literals via the inline `__print_str` helper.

## Expressions

### Operators

| Precedence | Operators                                       |
|------------|-------------------------------------------------|
| highest    | `not`, unary `-`, unary `+`                     |
|            | `*`, `div`, `mod`, `and`, `shl`, `shr`          |
|            | `+`, `-`, `or`, `xor`                           |
| lowest     | `=`, `<>`, `<`, `<=`, `>`, `>=`                 |

`and`, `or`, `xor`, `not`, `shl`, `shr` are **bitwise** integer operations (this dialect has no `boolean` type — comparisons return 0 or 1, and `if` tests "non-zero"). `*`, `div`, `mod` lower to runtime helper calls (`__mul`, `__div`, `__mod`). The helpers are unsigned, so signed division of negative operands gives unexpected results — use the built-in `sar` for arithmetic right shift, and prefer non-negative arithmetic where the math allows.

### Number literals

```pascal
42        { decimal }
$EC       { hexadecimal — Pascal convention }
-1
```

The compiler emits a single `ld.32` for values that fit in the 20-bit signed immediate, and an `ld + ldh` pair for anything larger, so constants like `1048576` and `419430400` work correctly even though the immediate field is only 20 bits.

### String literals

```pascal
writeln('it''s working');     { '' is an embedded apostrophe }
```

Strings live in code memory, like in C. They are valid only inside `write`/`writeln`.

## Built-in routines

The Pascal compiler exposes a handful of MPU-specific routines as if they were built into the language. They lower to direct calls into `stdlib.asm`:

| Builtin                     | Kind       | Description                                          |
|-----------------------------|------------|------------------------------------------------------|
| `sleep(ms)`                 | procedure  | Busy-wait the given number of milliseconds          |
| `i2cstart`                  | procedure  | Generate I²C START condition                         |
| `i2cstop`                   | procedure  | Generate I²C STOP condition                          |
| `i2cwrite(b)`               | procedure  | Shift one byte out                                   |
| `i2cread(ack)`              | function   | Shift one byte in; `ack=0` ACKs, `1` NACKs           |
| `peek(addr)`                | function   | Read one byte from memory (zero-extended)            |
| `poke(addr, val)`           | procedure  | Store low byte of `val` at `addr`                    |
| `sar(x, n)`                 | function   | Arithmetic shift right (signed `x`, `n` ≥ 0)         |

`sar` exists because the MPU's hardware `shr` is logical — for the BME280 reference compensation math (and anything else that uses `>>` on a signed value), you have to fold the high bits in by hand. The compiler emits an inline helper called `__sar` that does this once, and `sar(x, n)` calls it.

## What is missing

- `record`, `array`, `set`, `file`, string types
- Pointer types (`^integer`, `new`, `dispose`)
- `var` (reference) parameters
- Nested procedures with non-local variable access
- `case` statements
- Real boolean type (use 0/1 integers)
- Floating point of any kind
- `uses` and multi-unit compilation
- Forward declarations (functions must appear before their first call)

## Example

A small demo at `testing/hello.pas`:

```pascal
program hello;

var i: integer;

function square(x: integer): integer;
begin
  square := x * x
end;

begin
  for i := 1 to 10 do
    writeln('square(', i, ') = ', square(i))
end.
```

Build and run on the simulator:

```sh
cd testing
make hello.mpu
python3 ../toolchain/sim.py hello.mpu
```

A bigger example, [`testing/bme280demo.pas`](../../testing/bme280demo.pas), reads a BME280 sensor over I²C and prints compensated temperature, pressure, and humidity using the int32 reference compensation from the Bosch datasheet. It is a near line-for-line port of [`bme280demo.c`](../../testing/bme280demo.c) and produces identical output — a good demonstration of how much closer Pascal lets you get to C than BASIC does on this machine.
