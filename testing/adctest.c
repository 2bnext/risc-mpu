// adcdemo.c — read the sigma-delta ADC and print the value as a raw
// 12-bit code and an estimated voltage assuming Vcc = 3.3 V.
//
// In the simulator the ADC always returns 0x800 (half-scale ≈ 1.65 V).
// On real hardware the value tracks the analog voltage at the summing
// node (see mpu/adc.v for the wiring).

void main() {
    int i, code, mv, whole, frac;

    for (i = 0; i < 5; i++) {
        code = adc_read();
        // Vcc = 3300 mV, full scale = 4096.
        // mv = code * 3300 / 4096
        mv = code * 3300 / 4096;
        whole = mv / 1000;
        frac  = mv - whole * 1000;
        printf("ADC: code=%d  V=%d.", code, whole);
        if (frac < 100) printf("0");
        if (frac < 10)  printf("0");
        printf("%d V\n", frac);
        sleep(30000);
    }
}
