#ifndef STDLIB_H
#define STDLIB_H
// stdlib.h — function declarations for the MPU standard library.
//
// These functions are always available (stdlib.asm is linked automatically).
// This file exists purely for documentation — #include it if you want a
// quick reference while writing code.

// ---- I/O ----
void putchar(int c);
void puts(char *s);
void printf(char *fmt);             // variadic: %d %x %s %c %%
void sprintf(char *buf, char *fmt); // variadic, same specifiers, null-terminates
void sleep(int iterations);         // busy-wait, ~0.75 us per iteration at 12 MHz
void setleds(int value);            // bit 0=green, 1=red, 2=blue

// ---- GPIO ----
void gpio_set_dir(int mask);        // 1=output, 0=input per bit
void gpio_write(int value);         // drive output pins
int  gpio_read();                   // read live pin state (8 bits)

// ---- I2C ----
void i2c_start();
void i2c_stop();
int  i2c_write(int byte);           // returns 0=ACK, non-zero=NACK
int  i2c_read(int nack);            // nack=1 for last byte before stop

// ---- ADC ----
int   adc_read();                   // 12-bit raw (0..4095)
float adc_readf();                  // normalised to -1.0 .. +1.0

// ---- Integer math ----
int abs(int x);
int min(int a, int b);
int max(int a, int b);
int clamp(int x, int lo, int hi);
int clz(int x);                     // count leading zeros (0..32)
int isqrt(int x);                   // integer square root

// ---- Float core ----
float fadd(float a, float b);
float fsub(float a, float b);
float fmul(float a, float b);
float fdiv(float a, float b);
int   fcmp(float a, float b);       // -1, 0, or +1
float itof(int x);                  // int -> float
int   ftoi(float x);                // float -> int (truncate toward zero)

// ---- Float sign / magnitude ----
float fabs(float x);                // |x|
float fneg(float x);                // -x
float fsign(float x);               // -1.0, 0.0, or 1.0

// ---- Square root / distance ----
float fsqrt(float x);               // Newton, 2 iterations
float fhypot(float a, float b);     // sqrt(a*a + b*b)

// ---- Trigonometry ----
float fsin(float x);                // Bhaskara approximation
float fcos(float x);
float ftan(float x);
float fatan(float x);               // single-arg arctangent
float fatan2(float y, float x);     // two-arg, returns [-pi, pi]
float fasin(float x);               // input [-1, 1]
float facos(float x);               // input [-1, 1]

// ---- Angle conversion ----
float fdeg2rad(float x);
float frad2deg(float x);

// ---- Float utilities ----
float fmin(float a, float b);
float fmax(float a, float b);
float fclamp(float x, float lo, float hi);
float flerp(float a, float b, float t);  // a + t*(b-a)
float ffloor(float x);
float fceil(float x);

#endif
