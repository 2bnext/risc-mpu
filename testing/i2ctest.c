// Read the BME280 chip ID register (0xD0). Should print 0x60.
// In the sim a fake BME280 lives at 7-bit address 0x76.

void main() {
    int id;

    i2c_start();
    i2c_write(0xEC);    // 0x76<<1 | 0 — addr + W
    i2c_write(0xD0);    // register pointer
    i2c_start();        // repeated start
    i2c_write(0xED);    // 0x76<<1 | 1 — addr + R
    id = i2c_read(1);   // read one byte, NACK
    i2c_stop();

    printf("chip id = %x\n", id);
}
