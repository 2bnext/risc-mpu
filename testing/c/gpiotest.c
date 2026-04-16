// Drives GPIO outputs and reads them back via the loopback in sim.
void main() {
    gpio_set_dir(0xFF);     // all 8 pins as outputs
    gpio_write(0xA5);
    printf("read=%x\n", gpio_read());
    gpio_set_dir(0x0F);     // low nibble out, high nibble in
    gpio_write(0xFF);
    printf("read=%x\n", gpio_read());
}
