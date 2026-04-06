# MPU C Compiler

`toolchain/cc.py` is a small C-like compiler that targets the MPU assembler. It is not a full ISO C implementation — it covers the subset that makes sense on a 12 MHz soft-core with 64 KiB of RAM and no hardware multiply or divide.

## Usage

```sh
python3 toolchain/cc.py program.c             # writes program.s
python3 toolchain/cc.py program.c out.s       # explicit output path
```

In the `testing/` directory, the Makefile chains everything:

```sh
make program.mpu      # program.c -> program.s -> program.mpu
```

The standard library (`toolchain/stdlib.asm`) is automatically appended to the generated assembly, so all stdlib functions (`printf`, `puts`, `setleds`, …) are available without an `#include`.

## Types

| C type   | Size    | Notes                                        |
|----------|---------|----------------------------------------------|
| `int`    | 32 bits | Signed                                       |
| `char`   | 8 bits  | Used for byte loads/stores                   |
| `void`   | —       | Function return type only                    |
| pointers | 32 bits | `int *`, `char *`                            |
| arrays   | n bytes | `char buf[N];` — fixed-size, byte-indexed    |

There is **no** `float`, `double`, `short`, `long`, `struct`, `union`, `enum`, `typedef`, or function pointer support.

## Declarations

```c
int x;                  // global, zero-initialised
int y = 42;             // global with initialiser (constant only)
char buf[16];           // global byte array

void main() {
    int a;              // local
    int b = a + 1;      // local with initialiser
    int i, j;           // multiple declarators allowed
}
```

Locals live in the function's stack frame. Globals are placed in a data section after the code.

## Statements

All standard control flow is supported:

```c
if (cond) { ... } else { ... }
while (cond) { ... }
for (init; cond; update) { ... }
return expr;
break;
continue;
```

Blocks use `{ ... }`. The semicolon-as-statement-terminator rule is the usual one.

## Expressions

| Category    | Operators                                       |
|-------------|-------------------------------------------------|
| Arithmetic  | `+ - * / %` (`*`, `/`, `%` call runtime helpers) |
| Bitwise     | `& \| ^ << >> ~`                                |
| Comparison  | `== != < > <= >=`                               |
| Logical     | `&& \|\|` (short-circuit)                       |
| Assignment  | `=`                                             |
| Postfix     | `x++`, `x--` (desugared to `x = x + 1`)         |
| Address-of  | `&x`                                            |
| Dereference | `*p`                                            |
| Indexing    | `a[i]` (byte access)                            |
| Calls       | `f(a, b, ...)`                                  |

`++` and `--` are supported only in *postfix* form and have pre-increment value semantics — fine for `for` updates and statement-level use, but don't embed them in larger expressions and expect the C definition.

`/` and `%` lower to calls on the unsigned helpers `__div` / `__mod`. They produce wrong results for negative operands — keep arithmetic non-negative if you care about correctness.

## Functions

```c
int max(int a, int b) {
    if (a > b) return a;
    return b;
}

void main() {
    int m = max(3, 5);
    printf("max=%d\n", m);
}
```

- All parameters are passed on the stack, right-to-left, with the caller cleaning up after the call.
- The return value comes back in `r1`.
- `void` functions may omit `return`.
- Recursion works (each call gets its own stack frame).

`main` is the entry point; the runtime calls it once and then halts.

## Strings and arrays

String literals are zero-terminated and live in code memory:

```c
char *msg = "hello";
puts(msg);
```

Arrays are fixed-size and byte-indexed. `a[i]` reads/writes a single byte; there is no element-size scaling, so it is most useful for `char` buffers:

```c
char buf[8];
buf[0] = 'H';
buf[1] = 'i';
buf[2] = 0;
puts(buf);
```

For pointer arithmetic on words, do it manually with `int *` and explicit offsets.

## What is missing

- Floating point, `double`, `short`, `long`, `unsigned`
- `struct`, `union`, `enum`, `typedef`
- Function pointers
- The preprocessor (`#include`, `#define`, `#ifdef`, …) — there is no preprocessor at all
- `switch` / `case`
- `do { } while ()`
- `goto`
- Multi-file compilation / linking
- Most of the C standard library — only the symbols in [stdlib.md](stdlib.md) are available

## Example

```c
// primes.c — print primes up to 1000
void main() {
    int i, j;
    for (i = 3; i < 1000; i++) {
        for (j = 2; j < i; j++) {
            if (i % j == 0)
                break;
        }
        if (i == j)
            printf("%d\n", i);
    }
}
```

Build and run on the simulator:

```sh
cd testing
make primes.mpu
python3 ../toolchain/sim.py primes.mpu
```
