// adcpwm.c — PWM-dim an LED on gpio[7] using the ADC as a knob.
//
// The ADC returns 0..4095. We use the top 8 bits (0..255) as the PWM
// duty cycle. The PWM loop runs fast enough that the LED appears to
// have a smooth brightness range from off to fully on.

void main() {
    gpio_set_dir(0b1000_0000);
    int duty;
    int counter;

    for (;;) {
        duty = adc_read() >> 4;     // 0..255

        for (counter = 0; counter < 256; counter++) {
            if (counter < duty) {
                gpio_write(0b1000_0000);
            } else {
                gpio_write(0);
            }
        }
    }
}
