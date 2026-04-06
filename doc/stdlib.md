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
