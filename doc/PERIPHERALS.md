# Peripherals and Pinout (iCESugar 1.5)

This document is the practical wiring reference for the MPU's peripherals on the iCESugar 1.5 board (Lattice iCE40UP5K, package SG48). It tells you which iCE40 ball each signal lives on, what header pin that maps to on the board, what external hardware (if any) each peripheral needs, and how to talk to it from software.

The authoritative source of pin assignments is [`mpu/mpu.pcf`](../mpu/mpu.pcf). If you change a pin there, also update this file.

## Memory map at a glance

| MMIO       | Peripheral                                       |
|------------|--------------------------------------------------|
| `0xFFFF0000` | UART TX data (write a byte — pushes into the 16-byte FIFO) |
| `0xFFFF0004` | UART TX status (bit 0 = FIFO full)             |
| `0xFFFF0008` | LED register (bit 0 = G, 1 = R, 2 = B)         |
| `0xFFFF0010` | GPIO data (read = live pin state, write = drives outputs) |
| `0xFFFF0014` | GPIO direction (1 = output, 0 = input)         |
| `0xFFFF0018` | I²C data (W = byte to send, R = last byte received) |
| `0xFFFF001C` | I²C cmd / status                               |
| `0xFFFF0020` | ADC sample (12-bit sigma-delta)                |

The full ISA-level memory map is in [ISA.md](ISA.md). Each peripheral is detailed below.

---

## Clock and reset

| Signal  | iCE40 ball | iCESugar net | Notes                              |
|---------|------------|--------------|------------------------------------|
| `clk`   | **35**     | 12 MHz osc   | Single global clock for everything |
| `btn_s2`| **18**     | S2 button    | Active-low; bootloader uses it as a soft reset |

The S2 button drops the CPU back into the bootloader so a new `.mpu` can be uploaded over UART without a power cycle. `flash.py` prompts you to press it before upload.

---

## UART

| Signal     | iCE40 ball | iCESugar net          |
|------------|------------|-----------------------|
| `uart_tx`  | **4**      | USB-serial bridge RX  |
| `uart_rx`  | **6**      | USB-serial bridge TX  |

**External hardware:** none. The board has a built-in ESP32-C3 USB-serial bridge running `serialmon` firmware that exposes itself to the host as `/dev/ttyACM1` (Linux) or `COMn` (Windows). 115200 baud, 8-N-1.

**Software:** the bootloader and `flash.py` use UART RX; `printf`, `puts`, `putchar`, and the `__putc` low-level helper all use UART TX. See [stdlib.md](toolchain/stdlib.md).

**Ring buffer:** `uart_tx.v` has a 16-byte FIFO between the CPU and the shift register. The `busy` bit at `0xFFFF0004` now means "FIFO is full" rather than "currently shifting" — the CPU can burst up to 16 bytes at full clock speed without stalling, and only spins when the FIFO actually fills up. At 115200 baud that's ~1.4 ms of buffering. The existing `__putc` busy-wait loop (`ld.8 r4, 0xFFFF0004; bne.8 r4, #0, .wait`) needs no changes — it just almost never trips now.

---

## RGB LED

| Signal  | iCE40 ball | iCESugar net      |
|---------|------------|-------------------|
| `led_g` | **41**     | On-board green LED |
| `led_r` | **40**     | On-board red LED   |
| `led_b` | **39**     | On-board blue LED  |

**External hardware:** none — the LEDs are on the board.

**Software:** write to MMIO `0xFFFF0008`, low three bits. Bit 0 = green, bit 1 = red, bit 2 = blue. `setleds(value)` in [stdlib.asm](../toolchain/stdlib.asm) wraps this.

```c
setleds(7);   // white
setleds(3);   // red + green = yellow
setleds(0);   // off
```

The MPU register is active-high in software regardless of the polarity of the physical LEDs.

---

## GPIO

Eight bidirectional pins, individually configurable as input or output via the direction register. Outputs read back the value the program drove; inputs read the live pad state.

| Signal     | iCE40 ball | Notes                                          |
|------------|------------|------------------------------------------------|
| `gpio[0]`  | **36**     | Directly accessible iCESugar 1.5 header pins   |
| `gpio[1]`  | **37**     |                                                |
| `gpio[2]`  | **38**     |                                                |
| `gpio[3]`  | **42**     |                                                |
| `gpio[4]`  | **43**     |                                                |
| `gpio[5]`  | **44**     |                                                |
| `gpio[6]`  | **45**     |                                                |
| `gpio[7]`  | **46**     |                                                |

**External hardware:** none required by the MPU itself. Add series resistors, pull-ups, or level-shifting only if your specific application needs them. The iCE40 pads are 3.3 V CMOS — do not feed in voltages above Vcc + 0.3 V.

**MMIO:**

- `0xFFFF0010` — data. Write to drive outputs; read for live pin state. Bit `i` corresponds to `gpio[i]`.
- `0xFFFF0014` — direction. Bit `i = 1` makes `gpio[i]` an output, `0` an input. All pins are inputs on reset.

**Software helpers:** `gpio_set_dir(mask)`, `gpio_write(value)`, `gpio_read()` in C; `GPIODIR`, `GPIOWRITE`, `GPIOREAD()` in BASIC; `gpio_set_dir`, `gpio_write`, `gpio_read` in Pascal.

```c
gpio_set_dir(0x0F);   // gpio[0..3] = outputs
gpio_write(0x05);     // drive gpio[0] and gpio[2] high
int v = gpio_read();
if (v & 0x10) puts("gpio[4] is high");
```

> **Re-pinning.** The eight balls above were chosen because they were free; nothing on the iCESugar prevents you from moving any of them. Edit `mpu/mpu.pcf`, rebuild the bitstream (`cd mpu && make && make flash`), and you're done — no software change is needed because the MMIO interface stays the same.

---

## I²C master

A small synchronous I²C master at ~100 kHz. Supports START, repeated START, STOP, byte write with ACK readback, and byte read with controllable ACK polarity.

| Signal     | iCE40 ball | Notes                                          |
|------------|------------|------------------------------------------------|
| `i2c_scl`  | **25**     | Open-drain — needs an external pull-up         |
| `i2c_sda`  | **26**     | Open-drain — needs an external pull-up         |

**External hardware:** **two pull-up resistors, 2.2 kΩ–10 kΩ each**, from `SCL` and `SDA` to **3.3 V** (the iCE40's Vcc). The iCE40 has internal pull-ups (`PULLUP=1` in [top.v](../mpu/top.v)) but they are roughly 100 kΩ — far too weak for reliable I²C. Treat them as belt-and-braces only.

```
              +3.3V
                │
        ┌───────┴───────┐
        Rp              Rp        Rp = 2.2 kΩ–10 kΩ
        │               │         (4.7 kΩ is a safe default)
        ├──── i2c_scl   ├──── i2c_sda
        │               │
       ─┴─             ─┴─        (to slave devices)
```

Most off-the-shelf I²C breakouts (BME280, BMP280, MPU-6050, SSD1306, …) already include their own pull-ups — if you wire one such breakout to the bus, you usually don't need to add more. Two breakouts on the same bus may need you to remove one set.

**MMIO:**

- `0xFFFF0018` — data. Write the byte to send before issuing a write command; read it after a read command to get the received byte.
- `0xFFFF001C` — command (write) / status (read).
  - Write bits: `[0]=start`, `[1]=stop`, `[2]=write`, `[3]=read`, `[4]=ack_send`. Set exactly one of bits 0–3 per command; bit 4 is the ACK polarity for a read.
  - Read bits: `[0]=busy`, `[1]=ack_recv`. The CPU should poll until `busy` is clear before issuing the next command (the stdlib helpers do this for you).

**Software helpers:** `i2c_start`, `i2c_stop`, `i2c_write`, `i2c_read` in [stdlib.md](toolchain/stdlib.md). A complete worked example reading a BME280 is at [`testing/bme280demo.c`](../testing/bme280demo.c) (with line-for-line ports in [`bme280demo.bas`](../testing/bme280demo.bas) and [`bme280demo.pas`](../testing/bme280demo.pas)).

```c
i2c_start();
i2c_write(0xEC);          // 0x76<<1 | W
i2c_write(0xD0);          // BME280 chip-id register
i2c_start();              // repeated start
i2c_write(0xED);          // 0x76<<1 | R
int id = i2c_read(1);     // one byte, NACK to terminate
i2c_stop();
printf("chip id = %x\n", id);
```

---

## Sigma-delta ADC

A 12-bit single-ended ADC built in fabric — the FPGA only contains a 1-bit feedback loop and a counter; the analog smarts live in an **external RC charge-balancing network**.

| Signal     | iCE40 ball | Direction                  |
|------------|------------|----------------------------|
| `adc_out`  | **28**     | Digital output (0 / Vcc)   |
| `adc_in`   | **27**     | Digital input (Schmitt)    |

**External hardware:**

```
   adc_out ──── R1 ────┐
   (FPGA out)  10 kΩ   │
                       ├──── S ──── adc_in   (FPGA in)
   Vin     ──── R2 ────┘    │
   (0..Vcc)  10 kΩ          │
                            C  1–10 nF
                            │
                           GND
```

- `R1` and `R2` should be matched (1 % metal-film recommended). Mismatch becomes gain error and offset.
- `C` typically 4.7 nF — smaller is faster but noisier, larger is calmer but slower to track.
- Keep the summing node `S` short and physically close to the FPGA pins; it is a high-impedance node and will pick up hum from anything nearby.
- `Vin` must stay between 0 V and Vcc (3.3 V). If your source can exceed those rails, clamp it with diodes.

**How it works:** the FPGA toggles `adc_out` between high and low to drive the integrator at node `S` toward the Schmitt threshold. Over a 4096-cycle window the FPGA counts how often `adc_out` was high. That count *is* the 12-bit reading: `0` ≈ GND, `4095` ≈ Vcc.

**MMIO:** `0xFFFF0020` — read-only, 12-bit value in the low bits, updated continuously in the background. Reading it just snapshots the current count; there is no "start conversion" command.

**Software helpers:** `adc_read()` in C, BASIC, and Pascal.

```c
int v  = adc_read();              // 0..4095
int mv = v * 3300 / 4095;         // approximate millivolts
printf("V = %d mV\n", mv);
```

**Quick sanity test without an analog source:**

1. Tie `Vin` to **GND** — `adc_read` should report ≈ 0.
2. Tie `Vin` to **+3.3 V** — should report ≈ 4095.
3. Tie `Vin` to a divider made of two equal resistors between Vcc and GND — should report ≈ 2048.

If those three points line up, the loop is working and you can wire up a real signal.

In the simulator (`toolchain/sim.py`) the ADC always returns `0x800` (~ half-scale) regardless of the input — there is no analog model.

---

## Pin summary

The full pin list lives in [`mpu/mpu.pcf`](../mpu/mpu.pcf). Here it is in one place for reference:

| iCE40 ball | Signal      | Direction | Group |
|------------|-------------|-----------|-------|
| 4          | `uart_tx`   | out       | UART  |
| 6          | `uart_rx`   | in        | UART  |
| 18         | `btn_s2`    | in        | Reset |
| 25         | `i2c_scl`   | bidir     | I²C   |
| 26         | `i2c_sda`   | bidir     | I²C   |
| 27         | `adc_in`    | in        | ADC   |
| 28         | `adc_out`   | out       | ADC   |
| 35         | `clk`       | in        | Clock |
| 36         | `gpio[0]`   | bidir     | GPIO  |
| 37         | `gpio[1]`   | bidir     | GPIO  |
| 38         | `gpio[2]`   | bidir     | GPIO  |
| 39         | `led_b`     | out       | LED   |
| 40         | `led_r`     | out       | LED   |
| 41         | `led_g`     | out       | LED   |
| 42         | `gpio[3]`   | bidir     | GPIO  |
| 43         | `gpio[4]`   | bidir     | GPIO  |
| 44         | `gpio[5]`   | bidir     | GPIO  |
| 45         | `gpio[6]`   | bidir     | GPIO  |
| 46         | `gpio[7]`   | bidir     | GPIO  |

All MPU peripherals are 3.3 V CMOS. Nothing is 5 V tolerant.
