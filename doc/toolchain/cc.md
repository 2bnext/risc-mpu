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

| C type     | Size    | ISA suffix | Notes                                     |
|------------|---------|------------|-------------------------------------------|
| `int`      | 32 bits | `.32`      | Signed, the default                       |
| `char`     | 8 bits  | `.8`       | Used for byte loads/stores                |
| `int8_t`   | 8 bits  | `.8`       | Same as `char`                            |
| `uint8_t`  | 8 bits  | `.8`       | Same as `char` (signedness not enforced)  |
| `int16_t`  | 16 bits | `.16`      | Native 16-bit, uses the ISA's `.16` ops   |
| `uint16_t` | 16 bits | `.16`      | Same width, signedness not enforced        |
| `int32_t`  | 32 bits | `.32`      | Same as `int`                             |
| `uint32_t` | 32 bits | `.32`      | Same as `int` (signedness not enforced)   |
| `void`     | —       | —          | Function return type only                 |
| pointers   | 32 bits | `.32`      | `int *`, `char *`, `uint8_t *`, etc.      |
| arrays     | n bytes | `.8`       | `char buf[N];` — fixed-size, byte-indexed |

These are first-class types, not aliases — the compiler emits `ld.8`, `st.8` for 8-bit types, `ld.16`, `st.16` for 16-bit types, and `ld.32`, `st.32` for 32-bit types. This maps directly to the MPU's three ISA size suffixes.

All types use 4-byte stack slots (locals are always word-aligned). Sub-word loads are zero-extended: the compiler clears the destination register before a `.8` or `.16` load to avoid the ISA's size-merge gotcha. There is no sign extension on load — `int8_t` and `uint8_t` behave identically at the load level, as do `int16_t` and `uint16_t`.

Arithmetic is always 32-bit — the truncation to the declared width happens at store time and at the next load. This matches C's integer promotion rules.

No `#include` is needed for the `stdint`-style names — they are built-in keywords.

### Float support

The `float` type is IEEE 754 single-precision (32 bits). All arithmetic is implemented in software via the standard library's soft-float routines — there is no FPU.

```c
float pi = 3.14159;
float area = pi * 5.0 * 5.0;    // calls fmul
float half = area / 2.0;         // calls fdiv
int rounded = ftoi(half);         // float → int
float back = itof(rounded);      // int → float
```

The operators `+`, `-`, `*`, `/` on float values automatically call `fadd`, `fsub`, `fmul`, `fdiv`. Comparison operators (`==`, `!=`, `<`, `>`, `<=`, `>=`) call `fcmp`. Float literals like `3.14` are encoded as IEEE 754 bit patterns at compile time.

Explicit conversion functions:
- `itof(x)` — signed int → float
- `ftoi(x)` — float → signed int (truncates toward zero)
- `fcmp(a, b)` — returns -1, 0, or +1

Limitations:
- **No `printf("%f")`** — use `ftoi()` and print the integer part, or scale and print digits manually.
- **Denormals are flushed to zero.** Inf and NaN are not handled.
- **Rounding is truncation**, not round-to-nearest. Results may be off by 1 ULP.
- **The soft-float routines are not reentrant** (they use global scratch variables).
- **No `double`** — only single-precision `float`.

The C-standard integer type modifiers are supported as built-in keywords:

| Type              | Size    | ISA suffix | Notes                              |
|-------------------|---------|------------|------------------------------------|
| `short`           | 16 bits | `.16`      | Same as `int16_t`                  |
| `unsigned short`  | 16 bits | `.16`      | Same as `uint16_t`                 |
| `long`            | 32 bits | `.32`      | Same as `int` (no 64-bit support)  |
| `unsigned long`   | 32 bits | `.32`      | Same as `unsigned int`             |
| `unsigned int`    | 32 bits | `.32`      | Signedness not enforced            |
| `unsigned char`   | 8 bits  | `.8`       | Same as `uint8_t`                  |
| `signed`          | 32 bits | `.32`      | Same as `int`                      |
| `unsigned`        | 32 bits | `.32`      | Same as `unsigned int`             |

Compound forms like `unsigned short int`, `signed long int` are accepted (the trailing `int` is optional, matching C). `signed` and `unsigned` without a following type default to `int`.

There is **no** `double`, `enum`, or `typedef` support, and no proper `void (*)()` syntax for function-pointer types — but function pointers themselves are supported via `int` variables and the `&funcname` operator. See **Function pointers** below.

## Function pointers

The MPU's `callr` instruction makes function pointers cheap. The C compiler doesn't support the `void (*fp)()` declaration syntax, but you can store function addresses in `int` variables and call through them — the compiler emits `callr` automatically when the call target is a variable rather than a function name.

```c
int square(int x) { return x * x; }
int cube(int x)   { return x * x * x; }

void main() {
    int fp;
    fp = &square;          // store function address
    int a = fp(5);         // indirect call → uses callr
    fp = &cube;
    int b = fp(3);

    // Dispatch table
    int ops[2];
    ops[0] = &square;
    ops[1] = &cube;
    int r = ops[0](7);
}
```

`&funcname` evaluates to the 16-bit code address of the function. The compiler tracks all function names and emits a `call` for direct calls (target known at compile time) or a `callr` for indirect calls (target loaded from a variable). The runtime cost is one extra `ld.32` to load the pointer into a register before the indirect call.

Caveats:
- No type checking on function pointers — the variable type is just `int`.
- No `void (*)(int)` syntax. Don't try to declare them.
- No `(int)&funcname` cast — the `&` is enough since everything is untyped at the variable level.

## Structs

```c
struct point {
    int x;
    int y;
};

struct sensor {
    int id;
    int16_t temp;
    uint8_t status;
};

void main() {
    struct point p;
    p.x = 10;
    p.y = 20;

    struct point *q = &p;
    q->x = 99;                  // arrow access

    struct point pts[3];        // array of structs
    pts[0].x = 1;
    pts[2].y = 42;
}
```

Structs use bit-perfect layout with natural alignment — each field is aligned to `min(field_size, 4)` bytes, and the total struct size is padded to 4-byte alignment. Fields can be any type including other structs, pointers, floats, and fixed-size arrays (`int buf[8]`).

- `.` (member access) and `->` (pointer-to-member access) are both supported.
- `&s` takes the address of a struct; `struct point *p` declares a pointer to one.
- Struct values on the stack are passed by address — `printf` and other functions receive the address, not a copy.
- Structs cannot be assigned as a whole (`p = q` does not copy); assign fields individually.
- No nested struct *definitions* (but a struct field can be a pointer to another struct type).

## Unions

```c
union reg32 {
    int i;
    float f;
    uint8_t bytes[4];
};

void main() {
    union reg32 r;
    r.f = 3.14;
    printf("float bits = %d\n", r.i);   // type-punning: same memory
    r.i = 0;
    r.bytes[0] = 0xAA;
    printf("int = %d\n", r.i);          // reads 170 (0xAA in byte 0)
}
```

Unions use the same syntax as structs but all fields share offset 0. The size of the union is the size of its largest field, padded to 4-byte alignment. Member access uses `.` and `->` just like structs. Union pointers work the same way.

This gives you bit-perfect type punning — write as `float`, read as `int` to inspect the IEEE 754 bits, or write as `int` and read individual bytes.

## Arrays

```c
int arr[10];                     // 10 ints (40 bytes, element size 4)
float vals[4];                   // 4 floats (16 bytes)
uint8_t buf[32];                 // 32 bytes
struct point pts[5];             // 5 structs (40 bytes if struct point is 8)

arr[0] = 42;
int x = arr[3];
vals[1] = 3.14;
pts[2].x = 100;
```

Arrays are fixed-size, declared with `type name[N]`. Element access `arr[i]` automatically scales the index by the element size — `int arr[10]` scales by 4, `uint8_t buf[32]` scales by 1, `struct point pts[5]` scales by `sizeof(struct point)`. Both local and global arrays are supported.

Array names evaluate to the base address (like C pointers). You can pass an array to a function that takes a pointer parameter.

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

`/` and `%` lower to calls on the signed helpers `__sdiv` / `__smod`, which sign-adjust the unsigned `__div`/`__mod` primitives. They handle negative operands correctly: `__sdiv` truncates toward zero (C semantics) and `__smod` follows the dividend's sign.

`>>` defaults to **arithmetic** shift (`asr`) on signed operands and **logical** shift (`shr`) on unsigned operands — matching C's signed/unsigned distinction. Declare your operand as `unsigned int` / `uint32_t` if you need zero-fill behaviour.

```c
int   s = -100;
int   a = s >> 2;        // -25 (asr — sign bit fills in)
unsigned int u = -1;
int   b = u >> 4;        // 0x0FFFFFFF (shr — zero fills in)
```

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

## Standard library

The standard library (`toolchain/stdlib.asm`) is appended to every compiled program automatically. Notable functions:

| Category   | Functions                                                                                   |
|------------|---------------------------------------------------------------------------------------------|
| I/O        | `putchar`, `puts`, `printf`, `sleep`, `setleds`                                             |
| Integer    | `abs`, `min`, `max`, `clamp`, `clz`, `isqrt`                                                |
| GPIO       | `gpio_set_dir`, `gpio_write`, `gpio_read`                                                   |
| I²C        | `i2c_start`, `i2c_stop`, `i2c_write`, `i2c_read`                                            |
| ADC        | `adc_read` (raw 0..4095), `adc_readf` (normalised to `[-1.0, +1.0]`)                        |
| Float core | `fadd`, `fsub`, `fmul`, `fdiv`, `fcmp`, `itof`, `ftoi`, `fabs`, `fneg`, `fsign`             |
| Float math | `fsqrt`, `fhypot`, `fsin`, `fcos`, `ftan`, `fatan`, `fatan2`, `fasin`, `facos`              |
| Angles     | `fdeg2rad`, `frad2deg`                                                                      |
| Utility    | `fmin`, `fmax`, `fclamp`, `flerp`, `ffloor`, `fceil`                                        |

The GPIO/I²C peripherals require external hardware: I²C needs 2.2 kΩ–10 kΩ pull-ups on SCL and SDA, and the GPIO pins are bare iCE40 pads. See [stdlib.md](stdlib.md) for per-function signatures, semantics, accuracy notes, the underlying MMIO protocols, and the ADC's external RC network.

A complete I²C example lives at [`testing/bme280demo.c`](../../testing/bme280demo.c).

## What is missing

- `double` (only single-precision `float`)
- `enum`, `typedef`
- Proper function-pointer *type syntax* (`void (*fp)(int)`) — function pointers themselves work, stored as `int`; see **Function pointers** above
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
