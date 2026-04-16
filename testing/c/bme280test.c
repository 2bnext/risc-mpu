// bme280demo.c — read environmental data from a BME280 sensor over I2C
// and print compensated temperature, pressure, and humidity.
//
// Works in the simulator (which has a fake BME280 wired to address 0x76)
// and on real hardware: connect a BME280 to the iCESugar's I2C pins with
// its SDO grounded so it answers at 7-bit address 0x76.
//
// The compensation math is the int32 reference implementation from the
// BME280 datasheet (Bosch, section 8.2). It avoids 64-bit arithmetic
// and is therefore slightly less accurate than the int64 pressure path,
// but it stays within the MPU's 32-bit signed integers.

// 7-bit address 0x76: write byte = 0xEC, read byte = 0xED.

int dig_T1; int dig_T2; int dig_T3;
int dig_P1; int dig_P2; int dig_P3; int dig_P4; int dig_P5;
int dig_P6; int dig_P7; int dig_P8; int dig_P9;
int dig_H1; int dig_H2; int dig_H3; int dig_H4; int dig_H5; int dig_H6;
int t_fine;

// ---- Bit helpers ----

// Sign-extend a value of `bits` width to 32 bits.
int sext(int v, int bits) {
    int sign;
    sign = 1 << (bits - 1);
    if (v & sign) return v - (sign << 1);
    return v;
}

// Arithmetic shift right. The MPU's shr is logical, so for signed
// operands we have to fold the high bits in by hand.
int sar(int x, int n) {
    if (x < 0) return ~((~x) >> n);
    return x >> n;
}

// ---- I2C primitives ----

void bme_writereg(int reg, int val) {
    i2c_start();
    i2c_write(0xEC);
    i2c_write(reg);
    i2c_write(val);
    i2c_stop();
}

int bme_read8(int reg) {
    int v;
    i2c_start();
    i2c_write(0xEC);
    i2c_write(reg);
    i2c_start();
    i2c_write(0xED);
    v = i2c_read(1);
    i2c_stop();
    return v;
}

// Little-endian 16-bit read from `reg` and `reg+1` (raw, no sign-extend).
int bme_read16(int reg) {
    int lo, hi;
    lo = bme_read8(reg);
    hi = bme_read8(reg + 1);
    return (hi << 8) | lo;
}

// ---- Calibration ----

void bme_load_cal() {
    int e4, e5;

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

// ---- Compensation (BME280 datasheet, int32 reference) ----

// Returns temperature in degrees Celsius * 100.
int compensate_T(int adc_T) {
    int var1, var2, x, T;
    var1 = sar((sar(adc_T, 3) - (dig_T1 << 1)) * dig_T2, 11);
    x    = sar(adc_T, 4) - dig_T1;
    var2 = sar(sar(x * x, 12) * dig_T3, 14);
    t_fine = var1 + var2;
    T = sar(t_fine * 5 + 128, 8);
    return T;
}

// Returns pressure in pascals.
int compensate_P(int adc_P) {
    int var1, var2, p;
    var1 = sar(t_fine, 1) - 64000;
    var2 = sar(sar(var1, 2) * sar(var1, 2), 11) * dig_P6;
    var2 = var2 + ((var1 * dig_P5) << 1);
    var2 = sar(var2, 2) + (dig_P4 << 16);
    var1 = sar(sar(dig_P3 * sar(sar(var1, 2) * sar(var1, 2), 13), 3)
               + sar(dig_P2 * var1, 1), 18);
    var1 = sar((32768 + var1) * dig_P1, 15);
    if (var1 == 0) return 0;
    p = (1048576 - adc_P - sar(var2, 12)) * 3125;
    if ((p >> 31) == 0) p = (p << 1) / var1;
    else                p = (p / var1) * 2;
    var1 = sar(dig_P9 * sar(sar(p, 3) * sar(p, 3), 13), 12);
    var2 = sar(sar(p, 2) * dig_P8, 13);
    p = p + sar(var1 + var2 + dig_P7, 4);
    return p;
}

// Returns relative humidity * 1024.
int compensate_H(int adc_H) {
    int v, a, b;
    v = t_fine - 76800;
    a = sar((adc_H << 14) - (dig_H4 << 20) - (dig_H5 * v) + 16384, 15);
    b = sar((sar(sar(v * dig_H6, 10) * (sar(v * dig_H3, 11) + 32768), 10)
            + 2097152) * dig_H2 + 8192, 14);
    v = a * b;
    v = v - sar(sar(sar(v, 15) * sar(v, 15), 7) * dig_H1, 4);
    if (v < 0) v = 0;
    if (v > 419430400) v = 419430400;
    return sar(v, 12);
}

// ---- Demo ----

void main() {
    int id;
    int adc_T, adc_P, adc_H;
    int p_msb, p_lsb, p_xlsb;
    int t_msb, t_lsb, t_xlsb;
    int h_msb, h_lsb;
    int T, P, H;
    int frac, hpa, dec;

    id = bme_read8(0xD0);
    if (id != 0x60) {
        printf("BME280 not found (id=%x)\n", id);
        return;
    }
    printf("BME280 detected (chip id %x)\n", id);

    bme_load_cal();

    // ctrl_hum: humidity oversample x1
    bme_writereg(0xF2, 0x01);
    // ctrl_meas: temp x1, pressure x1, normal mode
    bme_writereg(0xF4, 0x27);

    // Wait for the first measurement to land (~10 ms on real hardware).
    sleep(30000);

    p_msb  = bme_read8(0xF7);
    p_lsb  = bme_read8(0xF8);
    p_xlsb = bme_read8(0xF9);
    t_msb  = bme_read8(0xFA);
    t_lsb  = bme_read8(0xFB);
    t_xlsb = bme_read8(0xFC);
    h_msb  = bme_read8(0xFD);
    h_lsb  = bme_read8(0xFE);

    adc_P = (p_msb << 12) | (p_lsb << 4) | ((p_xlsb >> 4) & 0x0F);
    adc_T = (t_msb << 12) | (t_lsb << 4) | ((t_xlsb >> 4) & 0x0F);
    adc_H = (h_msb << 8) | h_lsb;

    T = compensate_T(adc_T);
    P = compensate_P(adc_P);
    H = compensate_H(adc_H);

    // Temperature: T is degC * 100. Print one decimal.
    frac = T - (T / 100) * 100;
    if (frac < 0) frac = 0 - frac;
    printf("Temperature: %d.", T / 100);
    if (frac < 10) printf("0%d C\n", frac);
    else           printf("%d C\n", frac);

    // Pressure: P is Pa. Print as hPa with one decimal.
    hpa = P / 100;
    dec = (P - hpa * 100) / 10;
    printf("Pressure:    %d.%d hPa\n", hpa, dec);

    // Humidity: H is RH * 1024. Convert to %RH * 10 for one decimal.
    H = H * 10 / 1024;
    printf("Humidity:    %d.%d %%\n", H / 10, H - (H / 10) * 10);
}
