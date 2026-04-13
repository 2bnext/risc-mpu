// bme280displayed.c — BME280 weather station on SSD1306 OLED.

#include "stdlib.h"
#include "bme280.h"
#include "ssd1306.h"

#define UPDATE_DELAY  5_000_000
#define BME280_CHIPID 0x60

// BME280 register addresses
#define REG_CTRL_HUM  0xF2
#define REG_CTRL_MEAS 0xF4
#define REG_CHIPID    0xD0
#define REG_PRESS_MSB 0xF7
#define REG_TEMP_MSB  0xFA
#define REG_HUM_MSB   0xFD

void main() {
    int id;
    char line[22];

    ssd_init();
    ssd_clear();

    id = bme_read8(REG_CHIPID);
    if (id != BME280_CHIPID) {
        ssd_setpos(0, 0);
        ssd_puts("no BME280");
        printf("BME280 not found (id=%x)\n", id);
        return;
    }
    printf("BME280 + SSD1306 running\n");

    bme_load_cal();
    bme_writereg(REG_CTRL_HUM, 0x01);    // humidity oversample x1
    bme_writereg(REG_CTRL_MEAS, 0x27);   // temp x1, press x1, normal mode

    for (;;) {
        int adc_T;
        int adc_P;
        int adc_H;
        adc_P = (bme_read8(REG_PRESS_MSB) << 12)
              | (bme_read8(REG_PRESS_MSB + 1) << 4)
              | ((bme_read8(REG_PRESS_MSB + 2) >> 4) & 0x0F);
        adc_T = (bme_read8(REG_TEMP_MSB) << 12)
              | (bme_read8(REG_TEMP_MSB + 1) << 4)
              | ((bme_read8(REG_TEMP_MSB + 2) >> 4) & 0x0F);
        adc_H = (bme_read8(REG_HUM_MSB) << 8)
              | bme_read8(REG_HUM_MSB + 1);

        int T = compensate_T(adc_T);
        int P = compensate_P(adc_P);
        int H = compensate_H(adc_H);

        float temp = itof(T) / 100.0;
        float press = itof(P) / 100.0;
        float hum = itof(H) / 1024.0;

        int tw = ftoi(temp);
        int td = ftoi((temp - itof(tw)) * 10.0);
        if (td < 0) td = 0 - td;

        int pw = ftoi(press);
        int pd = ftoi((press - itof(pw)) * 10.0);
        if (pd < 0) pd = 0 - pd;

        int hw = ftoi(hum);
        int hd = ftoi((hum - itof(hw)) * 10.0);
        if (hd < 0) hd = 0 - hd;

        sprintf(line, "Temp  %d.%d C", tw, td);
        ssd_setpos(0, 0);
        ssd_puts(line);

        sprintf(line, "Press %d.%d hPa", pw, pd);
        ssd_setpos(0, 2);
        ssd_puts(line);

        sprintf(line, "Hum   %d.%d %%", hw, hd);
        ssd_setpos(0, 4);
        ssd_puts(line);

        printf("T=%d.%d C  P=%d.%d hPa  H=%d.%d %%\n",
               tw, td, pw, pd, hw, hd);

        sleep(UPDATE_DELAY);
    }
}
