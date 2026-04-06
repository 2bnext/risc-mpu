TOOLCHAIN := ../toolchain

%.mpu: %.c
	python3 $(TOOLCHAIN)/cc.py $<

%.mpu: %.bas
	python3 $(TOOLCHAIN)/basic.py $<

%.mpu: %.asm
	python3 $(TOOLCHAIN)/asm.py --opcodes $<

clean:
	rm -f *.mpu

.PHONY: clean
