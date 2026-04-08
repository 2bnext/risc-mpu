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

The matching MMIO is described in [doc/CLAUDE.md](../CLAUDE.md): write `0xFFFF0018` to load the byte to send, write `0xFFFF001C` with command bits `[0]=start, [1]=stop, [2]=write, [3]=read, [4]=ack_send`; read `0xFFFF0018` for the last received byte and `0xFFFF001C` for `{ack_recv, busy}`.

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

The ADC is a single-bit sigma-delta loop closed by an external RC network — see [doc/CLAUDE.md](../CLAUDE.md) for the wiring (matched 10 kΩ resistors and a 1–10 nF integrating cap). Without that network the value is meaningless. In the simulator (`toolchain/sim.py`), `adc_read` always returns `0x800` (~ half-scale).
