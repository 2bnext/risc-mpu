#ifndef BME280_H
#define BME280_H
// bme280.h — BME280 I2C driver and compensation (address 0x76).
//
// Provides: bme_read8, bme_read16, bme_writereg, bme_load_cal,
//           compensate_T, compensate_P, compensate_H, t_fine.
// Requires: i2c_start, i2c_stop, i2c_write, i2c_read from stdlib.

#define BME280_ADDR  0x76
#define BME280_WRITE 0xEC
#define BME280_READ  0xED

int dig_T1; int dig_T2; int dig_T3;
int dig_P1; int dig_P2; int dig_P3; int dig_P4; int dig_P5;
int dig_P6; int dig_P7; int dig_P8; int dig_P9;
int dig_H1; int dig_H2; int dig_H3; int dig_H4; int dig_H5; int dig_H6;
int t_fine;

int sext(int v, int bits) {
    int sign;
    sign = 1 << (bits - 1);
    if (v & sign) return v - (sign << 1);
    return v;
}

void bme_writereg(int reg, int val) {
    i2c_start();
    i2c_write(BME280_WRITE);
    i2c_write(reg);
    i2c_write(val);
    i2c_stop();
}

int bme_read8(int reg) {
    int v;
    i2c_start();
    i2c_write(BME280_WRITE);
    i2c_write(reg);
    i2c_start();
    i2c_write(BME280_READ);
    v = i2c_read(1);
    i2c_stop();
    return v;
}

int bme_read16(int reg) {
    int lo;
    int hi;
    lo = bme_read8(reg);
    hi = bme_read8(reg + 1);
    return (hi << 8) | lo;
}

void bme_load_cal() {
    int e4;
    int e5;
    dig_T1 =       bme_read16(0x88);
    dig_T2 = sext(bme_read16(0x8A), 16);
    dig_T3 = sext(bme_read16(0x8C), 16);
    dig_P1 =       bme_read16(0x8E);
    dig_P2 = sext(bme_read16(0x90), 16);
    dig_P3 = sext(bme_read16(0x92), 16);
    dig_P4 = sext(bme_read16(0x94), 16);
    dig_P5 = sext(bme_read16(0x96), 16);
    dig_P6 = sext(bme_read16(0x98), 16);
    dig_P7 = sext(bme_read16(0x9A), 16);
    dig_P8 = sext(bme_read16(0x9C), 16);
    dig_P9 = sext(bme_read16(0x9E), 16);
    dig_H1 = bme_read8(0xA1);
    dig_H2 = sext(bme_read16(0xE1), 16);
    dig_H3 = bme_read8(0xE3);
    e4 = bme_read8(0xE4);
    e5 = bme_read8(0xE5);
    dig_H4 = sext((e4 << 4) | (e5 & 0x0F), 12);
    dig_H5 = sext((bme_read8(0xE6) << 4) | ((e5 >> 4) & 0x0F), 12);
    dig_H6 = sext(bme_read8(0xE7), 8);
}

// Compensation — int32 reference from BME280 datasheet section 8.2.
// Returns: T in degC*100, P in Pa, H in %RH*1024.

int compensate_T(int adc_T) {
    int var1;
    int var2;
    int x;
    var1 = ((adc_T >> 3) - (dig_T1 << 1)) * dig_T2 >> 11;
    x    = (adc_T >> 4) - dig_T1;
    var2 = ((x * x >> 12) * dig_T3) >> 14;
    t_fine = var1 + var2;
    return (t_fine * 5 + 128) >> 8;
}

int compensate_P(int adc_P) {
    int var1;
    int var2;
    int p;
    var1 = (t_fine >> 1) - 64000;
    var2 = ((var1 >> 2) * (var1 >> 2) >> 11) * dig_P6;
    var2 = var2 + ((var1 * dig_P5) << 1);
    var2 = (var2 >> 2) + (dig_P4 << 16);
    var1 = ((dig_P3 * (((var1 >> 2) * (var1 >> 2)) >> 13) >> 3)
               + ((dig_P2 * var1) >> 1)) >> 18;
    var1 = ((32768 + var1) * dig_P1) >> 15;
    if (var1 == 0) return 0;
    p = (1048576 - adc_P - (var2 >> 12)) * 3125;
    if ((p >> 31) == 0) p = (p << 1) / var1;
    else                p = (p / var1) * 2;
    var1 = (dig_P9 * ((p >> 3) * (p >> 3) >> 13)) >> 12;
    var2 = ((p >> 2) * dig_P8) >> 13;
    return p + ((var1 + var2 + dig_P7) >> 4);
}

int compensate_H(int adc_H) {
    int v;
    int a;
    int b;
    v = t_fine - 76800;
    a = ((adc_H << 14) - (dig_H4 << 20) - (dig_H5 * v) + 16384) >> 15;
    b = ((((v * dig_H6 >> 10) * ((v * dig_H3 >> 11) + 32768)) >> 10)
            + 2097152) * dig_H2 + 8192 >> 14;
    v = a * b;
    v = v - ((((v >> 15) * (v >> 15)) >> 7) * dig_H1 >> 4);
    if (v < 0) v = 0;
    if (v > 419430400) v = 419430400;
    return v >> 12;
}

#endif
