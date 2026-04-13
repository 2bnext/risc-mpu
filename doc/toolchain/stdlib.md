# MPU Standard Library

The standard library is implemented in assembly (`toolchain/stdlib.asm`) and automatically linked after compiled C code. All functions use the UART at `0xFFFF0000` for I/O.

## Functions

### putchar

```c
void putchar(char c);
```

Sends a single character to the UART.

```c
putchar(65);   // prints 'A'
```

### puts

```c
void puts(char *s);
```

Prints a null-terminated string followed by a newline.

```c
puts("hello");  // prints "hello\n"
```

### printf

```c
void printf(char *fmt, ...);
```

Formatted output to UART. Supports the following format specifiers:

| Specifier | Description              | Example                |
|-----------|--------------------------|------------------------|
| `%d`      | Signed decimal integer   | `printf("%d", -42)`    |
| `%x`      | Hexadecimal (lowercase)  | `printf("%x", 255)`    |
| `%s`      | Null-terminated string   | `printf("%s", "hi")`   |
| `%c`      | Single character         | `printf("%c", 65)`     |
| `%%`      | Literal `%`              | `printf("100%%")`      |

```c
printf("val=%d hex=%x\n", 42, 42);  // prints "val=42 hex=2a\n"
```

### sprintf

```c
void sprintf(char *buf, char *fmt, ...);
```

Same format engine as `printf`, but writes to a `char *` buffer instead of UART. The output is null-terminated. Useful for building strings to send to an OLED or other non-UART output.

```c
char line[32];
sprintf(line, "Temp %d.%d C", 23, 5);   // line = "Temp 23.5 C\0"
ssd_puts(line);                          // send to SSD1306 OLED
```

Internally, `sprintf` redirects the `__putc` helper to a buffer pointer, calls the shared format engine, null-terminates, and restores UART mode. The redirection is global (not reentrant) — don't call `sprintf` from an interrupt context.

### sleep

```c
void sleep(int iterations);
```

Busy-wait delay loop. The argument is the number of loop iterations, not milliseconds. At 12 MHz, roughly 3000 iterations per millisecond.

```c
sleep(3000);  // ~1ms delay at 12MHz
```

### setleds

```c
void setleds(int value);
```

Controls the onboard RGB LED via the I/O register at `0xFFFF0008`.

| Bit | Color |
|-----|-------|
| 0   | Green |
| 1   | Red   |
| 2   | Blue  |

```c
setleds(7);  // all colors on (white)
setleds(3);  // green + red (yellow)
setleds(0);  // off
```

### gpio_set_dir

```c
void gpio_set_dir(int mask);
```

Sets the direction of the 8 GPIO pins via the register at `0xFFFF0014`. Bit `i = 1` makes `gpio[i]` an output, bit `i = 0` makes it an input. All pins are inputs on reset.

```c
gpio_set_dir(0x0F);   // gpio[0..3] outputs, gpio[4..7] inputs
```

### gpio_write

```c
void gpio_write(int value);
```

Writes the 8 GPIO output bits via the register at `0xFFFF0010`. Only pins configured as outputs actually drive the pad — bits for input-configured pins have no effect.

```c
gpio_write(0x05);   // drive gpio[0] and gpio[2] high
```

### gpio_read

```c
int gpio_read(void);
```

Returns the live state of all 8 GPIO pins as the low byte of the result. Bits for output-configured pins read back the value being driven; input pins read the pad voltage.

```c
int v = gpio_read();
if (v & 0x10) puts("gpio[4] is high");
```

### i2c_start

```c
void i2c_start(void);
```

Generates an I2C START condition on the master at `0xFFFF0018`/`0xFFFF001C`. Also used for repeated starts. Blocks until the bus operation completes.

### i2c_stop

```c
void i2c_stop(void);
```

Generates an I2C STOP condition. Blocks until the bus is released.

### i2c_write

```c
int i2c_write(int byte);
```

Shifts one byte out, MSB first, and reads back the slave's ACK bit. Returns `0` if the slave ACKed, non-zero if it NACKed (no device, or end of transfer). Blocks until the byte has been clocked out.

```c
i2c_start();
if (i2c_write(0xEC)) puts("no device at 0x76");  // 0x76<<1 | W
```

### i2c_read

```c
int i2c_read(int nack);
```

Shifts one byte in, MSB first, and drives the master's ACK bit afterwards. Pass `0` to ACK (continue reading more bytes from the same slave) or `1` to NACK (last byte before STOP, as required by the I2C spec). Returns the received byte in the low 8 bits.

```c
i2c_start();
i2c_write(0xEC);          // addr + W
i2c_write(0xD0);          // BME280 chip-id register
i2c_start();              // repeated start
i2c_write(0xED);          // addr + R
int id = i2c_read(1);     // one byte, NACK
i2c_stop();
printf("chip id = %x\n", id);
```

The underlying MMIO protocol is: write `0xFFFF0018` to load the byte to send, write `0xFFFF001C` with command bits `[0]=start, [1]=stop, [2]=write, [3]=read, [4]=ack_send`; read `0xFFFF0018` for the last received byte and `0xFFFF001C` for `{ack_recv, busy}`. The bus needs external 2.2 kΩ–10 kΩ pull-ups on SCL and SDA — the iCE40's internal pull-ups are too weak for reliable I²C.

### adc_read

```c
int adc_read(void);
```

Returns the latest sample from the on-chip sigma-delta ADC at `0xFFFF0020`. The result is a 12-bit value in the range `0`–`4095`, where `0` is GND and `4095` is approximately Vcc (3.3 V). The conversion runs continuously in the background — `adc_read` only takes a snapshot of the current count, it does not start a conversion.

```c
int v = adc_read();                       // 0..4095
int mv = v * 3300 / 4095;                 // approximate millivolts
printf("V = %d mV\n", mv);
```

### adc_readf

```c
float adc_readf(void);
```

Float-valued wrapper around `adc_read`. Returns the latest ADC sample as a `float` normalised to the range `[-1.0, +1.0]` — `0` → `-1.0`, `2048` → `0.0`, `4095` → `+1.0`. Convenient for audio or control-loop code that wants a zero-centred signed value. In the simulator this always returns approximately `0.0` because the simulated ADC returns half-scale (`0x800`).

### Signed integer math

```c
int abs(int x);                   // absolute value
int min(int a, int b);            // signed minimum
int max(int a, int b);            // signed maximum
int clamp(int x, int lo, int hi); // signed clamp to [lo, hi]
int clz(int x);                   // count leading zeros (0..32)
int isqrt(int x);                 // integer square root (unsigned)
```

Internal signed helpers used by the compilers (not normally called directly):

```c
int __smul(int a, int b);         // signed multiply
int __sdiv(int a, int b);         // signed divide (truncate toward zero)
int __smod(int a, int b);         // signed modulo (sign follows dividend)
int __sar(int x, int n);          // arithmetic shift right (wraps asr)
```

### IEEE 754 soft-float

Software floating point — no FPU needed. All functions take and return `float` values as raw 32-bit words in `r1`. Denormals are flushed to zero; inf/NaN are not handled. Mantissa rounding is truncation, so results may be off by 1 ULP.

#### Core arithmetic

```c
float fadd(float a, float b);     // a + b
float fsub(float a, float b);     // a - b
float fmul(float a, float b);     // a * b
float fdiv(float a, float b);     // a / b
int   fcmp(float a, float b);     // -1 if a<b, 0 if a==b, +1 if a>b
float itof(int x);                // signed int -> float
int   ftoi(float x);              // float -> signed int (truncate toward zero)
```

When using `float` variables in the C compiler, `+`/`-`/`*`/`/` and the comparison operators automatically call the corresponding soft-float helpers.

#### Sign and magnitude

```c
float fabs(float x);              // |x| — clears the sign bit
float fneg(float x);              // -x  — flips the sign bit
float fsign(float x);             // -1.0, 0.0, or +1.0
```

`fabs` and `fneg` are pure bitfield twiddles — no arithmetic cost.

#### Square root and hypotenuse

```c
float fsqrt(float x);             // Newton iteration, 2 steps from isqrt seed
float fhypot(float a, float b);   // sqrt(a*a + b*b)
```

`fsqrt` seeds itself from `isqrt(ftoi(x))` converted back via `itof`, then runs two unrolled Newton iterations (`y = (y + x/y) / 2`). This is exact for perfect squares in the `int` range and within ~0.1% for non-squares. `fsqrt(0)` returns 0; negative inputs return 0.

#### Trigonometry

```c
float fsin(float x);              // sin(x), full range via modulo reduction
float fcos(float x);              // cos(x) = fsin(x + pi/2)
float ftan(float x);              // fsin(x) / fcos(x)
float fatan(float x);             // single-arg arctangent
float fatan2(float y, float x);   // two-arg arctangent, returns [-pi, pi]
float fasin(float x);             // arcsine, input in [-1, 1]
float facos(float x);             // arccosine, input in [-1, 1]
```

`fsin`/`fcos` use the Bhaskara polynomial `sin(x) ≈ 16x(pi−x) / (5·pi² − 4x(pi−x))` over `[0, pi]`, extended to the full range via symmetry and modulo `2·pi`. Accuracy is ~0.001 for most inputs.

`fatan2` uses the rational approximation `atan(z) ≈ z / (1 + 0.28125·z²)` with quadrant adjustment based on the sign bits of `x` and `y` — max error ~1% for `|z| ≤ 1`. `fatan`, `fasin`, and `facos` are thin wrappers around `fatan2`: `fatan(x) = fatan2(x, 1)`, `fasin(x) = fatan2(x, sqrt(1−x²))`, `facos(x) = pi/2 − fasin(x)`.

**Performance note:** every trig call is hundreds of thousands of soft-float cycles. A single `fsin` takes several milliseconds of simulated time at 12 MHz. Fine for control loops and demos; not a replacement for an FPU.

#### Angle conversion

```c
float fdeg2rad(float x);          // x * (pi/180)
float frad2deg(float x);          // x * (180/pi)
```

Each is a single `fmul` against a precomputed constant.

#### Comparison and interpolation utilities

```c
float fmin(float a, float b);                  // smaller
float fmax(float a, float b);                  // larger
float fclamp(float x, float lo, float hi);     // max(lo, min(x, hi))
float flerp(float a, float b, float t);        // a + t*(b - a)
float ffloor(float x);                         // round toward -inf
float fceil(float x);                          // round toward +inf
```

These are all cheap (1–4 soft-float calls each) and are the fast path if you just need the bulk-data operations without the trig.

**Not reentrant:** all soft-float routines use global scratch variables internally (`_fa_*`, `_fm_*`, `_gm_tmp*`). Do not call them from interrupt handlers or nested contexts.

The ADC is a single-bit sigma-delta loop closed by an external RC charge-balancing network: a 10 kΩ resistor from the `adc_out` pin to a summing node, a matching 10 kΩ resistor from the analog input to the same node, a 1–10 nF capacitor from the node to GND, and the node itself wired to `adc_in`. Without that network the value is meaningless. In the simulator (`toolchain/sim.py`), `adc_read` always returns `0x800` (~ half-scale).
