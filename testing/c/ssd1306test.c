// ssd1306test.c — font rendering test

char font[640];

void ssd_cmd(int c) {
    i2c_start();
    i2c_write(0x78);
    i2c_write(0x00);
    i2c_write(c);
    i2c_stop();
}

void ssd_init() {
    ssd_cmd(0xAE);
    ssd_cmd(0xD5); ssd_cmd(0x80);
    ssd_cmd(0xA8); ssd_cmd(0x3F);
    ssd_cmd(0xD3); ssd_cmd(0x00);
    ssd_cmd(0x40);
    ssd_cmd(0x8D); ssd_cmd(0x14);
    ssd_cmd(0x20); ssd_cmd(0x02);
    ssd_cmd(0xA1);
    ssd_cmd(0xC8);
    ssd_cmd(0xDA); ssd_cmd(0x12);
    ssd_cmd(0x81); ssd_cmd(0xCF);
    ssd_cmd(0xD9); ssd_cmd(0xF1);
    ssd_cmd(0xDB); ssd_cmd(0x40);
    ssd_cmd(0xA4);
    ssd_cmd(0xA6);
    ssd_cmd(0xAF);
}

void ssd_setpos(int col, int page) {
    ssd_cmd(0xB0 + page);
    ssd_cmd(col & 0x0F);
    ssd_cmd(0x10 + (col >> 4));
}

void main() {
    int i;
    int base;

    printf("font test\n");
    ssd_init();

    // Clear display
    int p;
    for (p = 0; p < 8; p = p + 1) {
        ssd_setpos(0, p);
        i2c_start();
        i2c_write(0x78);
        i2c_write(0x40);
        for (i = 0; i < 128; i = i + 1)
            i2c_write(0x00);
        i2c_stop();
    }

    // Store font data for 'A' at index 65*5=325
    base = 65 * 5;
    font[base]   = 0x7E;
    font[base+1] = 0x11;
    font[base+2] = 0x11;
    font[base+3] = 0x11;
    font[base+4] = 0x7E;

    // Verify readback
    printf("font[%d] = %x %x %x %x %x\n", base,
           font[base], font[base+1], font[base+2],
           font[base+3], font[base+4]);

    // Test 1: hardcoded 'A' bytes (no font array)
    ssd_setpos(0, 0);
    i2c_start();
    i2c_write(0x78);
    i2c_write(0x40);
    i2c_write(0x7E);
    i2c_write(0x11);
    i2c_write(0x11);
    i2c_write(0x11);
    i2c_write(0x7E);
    i2c_write(0x00);
    i2c_stop();

    // Test 2: same 'A' from font array
    ssd_setpos(12, 0);
    i2c_start();
    i2c_write(0x78);
    i2c_write(0x40);
    for (i = 0; i < 5; i = i + 1)
        i2c_write(font[base + i]);
    i2c_write(0x00);
    i2c_stop();

    printf("done\n");
}
