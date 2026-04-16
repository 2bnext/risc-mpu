TOOLCHAIN := ../toolchain

# Build any .mpu from a .c / .bas / .pas / .asm in c/, basic/, pascal/, asm/.
# e.g. make c/hello.mpu, make basic/primes.mpu, make asm/hello.mpu

%.mpu: %.c
	python3 $(TOOLCHAIN)/cc.py $<

%.mpu: %.bas
	python3 $(TOOLCHAIN)/basic.py $<

%.mpu: %.pas
	python3 $(TOOLCHAIN)/pas.py $<

%.mpu: %.asm
	python3 $(TOOLCHAIN)/asm.py --opcodes $<

# Convenience: build every source under a language folder.
C_SRCS     := $(wildcard c/*.c)
BASIC_SRCS := $(wildcard basic/*.bas)
PAS_SRCS   := $(wildcard pascal/*.pas)
ASM_SRCS   := $(wildcard asm/*.asm)

c:      $(C_SRCS:.c=.mpu)
basic:  $(BASIC_SRCS:.bas=.mpu)
pascal: $(PAS_SRCS:.pas=.mpu)
asm:    $(ASM_SRCS:.asm=.mpu)

all: c basic pascal asm

clean:
	rm -f c/*.mpu c/*.img c/*.s basic/*.mpu pascal/*.mpu asm/*.mpu

.PHONY: all c basic pascal asm clean
