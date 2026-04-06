DEVICE = up5k
PACKAGE = sg48
PCF = mpu.pcf
TOP = top

SRCS = top.v mpu.v agu.v mem.v uart_tx.v uart_rx.v bootloader.v

all: mpu.bin

mpu.json: $(SRCS)
	yosys -p "synth_ice40 -top $(TOP) -json $@" $(SRCS)

mpu.asc: mpu.json $(PCF)
	nextpnr-ice40 --$(DEVICE) --package $(PACKAGE) --pcf $(PCF) --json mpu.json --asc $@

mpu.bin: mpu.asc
	icepack mpu.asc mpu.bin

flash: mpu.bin
	icesprog mpu.bin

clean:
	rm -f mpu.json mpu.asc mpu.bin

.PHONY: all flash clean
