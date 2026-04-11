// floatdemo.c — IEEE 754 soft-float demo for the MPU
// All four arithmetic operations, int↔float conversion, and comparison.

void main() {
    float pi = 3.14159;
    float r = 5.0;
    float area = pi * r * r;
    printf("area of circle r=5: %d (expect 78)\n", ftoi(area));

    float c = 100.0;
    float f = c * 1.8 + itof(32);
    printf("100 C in F: %d (expect 212)\n", ftoi(f));

    float a = 355.0;
    float b = 113.0;
    float approx_pi = a / b;
    printf("355/113 = %d.%d (expect 3.14)\n",
        ftoi(approx_pi),
        ftoi((approx_pi - itof(ftoi(approx_pi))) * 100.0));

    // ADC voltage conversion
    int raw = adc_read();
    float voltage = itof(raw) * 3.3 / 4095.0;
    printf("ADC raw=%d voltage*100=%d mV\n", raw,
        ftoi(voltage * 100.0));

    // Comparison
    if (fcmp(pi, 3.0) > 0) printf("pi > 3: yes\n");
    if (fcmp(2.71, pi) < 0) printf("e < pi: yes\n");
}
