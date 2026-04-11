#!/usr/bin/env python3
"""
MPU ISA simulator. Executes a .mpu file and prints UART output.

Usage: sim.py <program.mpu> [--trace] [--max-cycles N]
"""

import sys
import os
import struct

# ---- Opcodes ----
OP_NOP  = 0
OP_LD   = 1
OP_LDH  = 2
OP_ST   = 3
OP_ADD  = 4
OP_SUB  = 5
OP_BEQ  = 6
OP_BNE  = 7
OP_BLT  = 8
OP_BGT  = 9
OP_BLE  = 10
OP_BGE  = 11
OP_AND  = 12
OP_OR   = 13
OP_XOR  = 14
OP_SHL  = 15
OP_SHR  = 16
OP_CALL = 17
OP_RET  = 18
OP_ASR  = 19
OP_JMPR = 20
OP_CALLR = 21

OP_NAMES = {
    0: 'NOP', 1: 'LD', 2: 'LDH', 3: 'ST',
    4: 'ADD', 5: 'SUB',
    6: 'BEQ', 7: 'BNE', 8: 'BLT', 9: 'BGT', 10: 'BLE', 11: 'BGE',
    12: 'AND', 13: 'OR', 14: 'XOR', 15: 'SHL', 16: 'SHR',
    17: 'CALL', 18: 'RET',
    19: 'ASR', 20: 'JMPR', 21: 'CALLR',
}

SIZE_NAMES = {0: '.8', 1: '.16', 2: '.32'}

MASK32 = 0xFFFFFFFF


def sign_extend(val, bits):
    if val & (1 << (bits - 1)):
        val -= (1 << bits)
    return val


def to_signed32(val):
    val &= MASK32
    if val & 0x80000000:
        return val - 0x100000000
    return val


class FakeBME280:
    """Minimal BME280 model for the I2C sim. Implements register reads/writes
    against a sparse register map. Calibration constants and raw ADC values
    are taken from the BME280 datasheet appendix; the raw ADC samples
    have been chosen so that the int32 reference compensation in
    testing/bme280demo.c reproduces the ICAO standard atmosphere at
    sea level:
        T = 15 °C, P = 1013.25 hPa, RH = 0 % (dry air)
    """
    I2C_ADDR = 0x76

    def __init__(self):
        self.regs = {}
        # Chip ID
        self.regs[0xD0] = 0x60
        # Status / control / config — power-on defaults
        self.regs[0xF3] = 0x00
        self.regs[0xF2] = 0x00
        self.regs[0xF4] = 0x00
        self.regs[0xF5] = 0x00

        def put16(addr, value, signed):
            v = value & 0xFFFF
            self.regs[addr]     = v & 0xFF
            self.regs[addr + 1] = (v >> 8) & 0xFF

        # Temperature / pressure calibration at 0x88..0x9F
        put16(0x88, 27504,  False)   # dig_T1
        put16(0x8A, 26435,  True)    # dig_T2
        put16(0x8C, -1000,  True)    # dig_T3
        put16(0x8E, 36477,  False)   # dig_P1
        put16(0x90, -10685, True)    # dig_P2
        put16(0x92, 3024,   True)    # dig_P3
        put16(0x94, 2855,   True)    # dig_P4
        put16(0x96, 140,    True)    # dig_P5
        put16(0x98, -7,     True)    # dig_P6
        put16(0x9A, 15500,  True)    # dig_P7
        put16(0x9C, -14600, True)    # dig_P8
        put16(0x9E, 6000,   True)    # dig_P9

        # Humidity calibration
        self.regs[0xA1] = 75               # dig_H1
        put16(0xE1, 341, True)             # dig_H2
        self.regs[0xE3] = 0                # dig_H3
        # dig_H4 = 298 (0x12A), dig_H5 = 50 (0x032)
        self.regs[0xE4] = 0x12             # H4[11:4]
        self.regs[0xE5] = (0x2 << 4) | 0xA # H5[3:0]<<4 | H4[3:0]
        self.regs[0xE6] = 0x03             # H5[11:4]
        self.regs[0xE7] = 30               # dig_H6

        # Raw ADC samples at 0xF7..0xFE. Chosen so the int32 compensation
        # math in bme280demo.c yields roughly room conditions:
        #   T ≈ 25 °C, P ≈ 1013 hPa, RH ≈ 50 %
        self.regs[0xF7] = 0x62; self.regs[0xF8] = 0x30; self.regs[0xF9] = 0x00
        self.regs[0xFA] = 0x77; self.regs[0xFB] = 0x10; self.regs[0xFC] = 0x00
        self.regs[0xFD] = 0x00; self.regs[0xFE] = 0x00

        self.reg_ptr = 0
        self.write_count = 0     # bytes received in this write transaction

    def start_write(self):
        self.write_count = 0

    def start_read(self):
        pass

    def write(self, byte):
        # First byte after addr+W sets the register pointer; subsequent
        # bytes write to that pointer (auto-incrementing).
        if self.write_count == 0:
            self.reg_ptr = byte & 0xFF
        else:
            self.regs[self.reg_ptr] = byte & 0xFF
            self.reg_ptr = (self.reg_ptr + 1) & 0xFF
        self.write_count += 1
        return True   # ACK

    def read(self):
        v = self.regs.get(self.reg_ptr, 0)
        self.reg_ptr = (self.reg_ptr + 1) & 0xFF
        return v


class MPU:
    def __init__(self, program, trace=False):
        self.mem = bytearray(65536)  # 64KB RAM
        self.mem[:len(program)] = program
        self.regs = [0] * 8
        self.regs[7] = 0x10000  # SP at top of RAM
        self.pc = 0
        self.trace = trace
        self.cycles = 0
        self.uart_tx_busy = 0
        self.uart_output = []
        self.gpio_dir = 0
        self.gpio_out = 0
        # I2C bus + attached fake devices
        self.i2c_devices = {FakeBME280.I2C_ADDR: FakeBME280()}
        self.i2c_tx = 0          # data register (last write or last read)
        self.i2c_ack = 1         # 1 = NACK, 0 = ACK
        self.i2c_started = False
        self.i2c_slave = None    # currently-addressed device
        self.i2c_dir_read = False
        self.halted = False

    def mem_read(self, addr, size):
        addr &= MASK32
        # UART status register
        if addr == 0xFFFF0004:
            return self.uart_tx_busy
        if addr == 0xFFFF0000:
            return 0
        # GPIO: outputs read back their driven value, inputs read 0.
        if addr == 0xFFFF0010:
            return self.gpio_out & self.gpio_dir
        if addr == 0xFFFF0014:
            return self.gpio_dir
        if addr == 0xFFFF0018:
            return self.i2c_tx
        if addr == 0xFFFF001C:
            # busy bit always 0 in sim (operations complete instantly)
            return self.i2c_ack << 1
        if addr == 0xFFFF0020:
            # Sigma-delta ADC: simulate ~half-scale (Vin ≈ Vcc/2)
            return 0x800
        if addr >= 0x10000:
            if self.trace:
                print(f"  WARNING: read from unmapped address {addr:#010x}")
            return 0
        if size == 0:  # .8
            return self.mem[addr]
        elif size == 1:  # .16
            return struct.unpack_from('<H', self.mem, addr)[0]
        else:  # .32
            return struct.unpack_from('<I', self.mem, addr)[0]

    def mem_write(self, addr, size, val):
        addr &= MASK32
        val &= MASK32
        # UART TX data register
        if addr == 0xFFFF0000:
            if size == 0:
                ch = val & 0xFF
            else:
                ch = val & 0xFF
            self.uart_output.append(ch)
            if self.trace:
                c = chr(ch) if 32 <= ch < 127 else f'\\x{ch:02x}'
                print(f"  UART TX: {c}")
            else:
                sys.stdout.write(chr(ch) if ch < 128 else f'\\x{ch:02x}')
                sys.stdout.flush()
            return
        if addr == 0xFFFF0010:
            self.gpio_out = val & 0xFF
            return
        if addr == 0xFFFF0014:
            self.gpio_dir = val & 0xFF
            return
        if addr == 0xFFFF0018:
            self.i2c_tx = val & 0xFF
            return
        if addr == 0xFFFF001C:
            self._i2c_cmd(val & 0x1F)
            return
        if addr >= 0x10000:
            if self.trace:
                print(f"  WARNING: write to unmapped address {addr:#010x}")
            return
        if size == 0:
            self.mem[addr] = val & 0xFF
        elif size == 1:
            struct.pack_into('<H', self.mem, addr, val & 0xFFFF)
        else:
            struct.pack_into('<I', self.mem, addr, val & MASK32)

    def _i2c_cmd(self, cmd):
        # Operations are processed in the same order as the hardware FSM:
        # start → write → read → stop. The sim performs them instantly.
        if cmd & 0x01:        # START
            self.i2c_started = True
            self.i2c_slave = None
            self.i2c_dir_read = False
        if cmd & 0x04:        # WRITE byte from data reg
            if self.i2c_started:
                addr7 = (self.i2c_tx >> 1) & 0x7F
                self.i2c_dir_read = bool(self.i2c_tx & 1)
                self.i2c_slave = self.i2c_devices.get(addr7)
                self.i2c_started = False
                if self.i2c_slave is None:
                    self.i2c_ack = 1
                else:
                    self.i2c_ack = 0
                    if self.i2c_dir_read:
                        self.i2c_slave.start_read()
                    else:
                        self.i2c_slave.start_write()
            else:
                if self.i2c_slave is not None and not self.i2c_dir_read:
                    self.i2c_slave.write(self.i2c_tx)
                    self.i2c_ack = 0
                else:
                    self.i2c_ack = 1
        if cmd & 0x08:        # READ byte into data reg
            if self.i2c_slave is not None and self.i2c_dir_read:
                self.i2c_tx = self.i2c_slave.read()
            else:
                self.i2c_tx = 0xFF
        if cmd & 0x02:        # STOP
            self.i2c_started = False
            self.i2c_slave = None
            self.i2c_dir_read = False

    def reg_read(self, r):
        if r == 0:
            return 0
        return self.regs[r] & MASK32

    def reg_write(self, r, val):
        if r != 0:
            self.regs[r] = val & MASK32

    def agu(self, reg_val, addr_imm, payload, base_val, idx_val):
        """Returns (eff_addr, is_imm, imm_value, wb_en, wb_reg, wb_val)"""
        if reg_val:
            sx = sign_extend(payload, 20) & MASK32
            if addr_imm:
                return 0, True, sx, False, 0, 0
            else:
                return sx, False, 0, False, 0, 0
        else:
            base_sel = (payload >> 17) & 7
            mode = (payload >> 15) & 3
            idx_sel = (payload >> 12) & 7
            offset = sign_extend(payload & 0xFFF, 12) & MASK32

            if mode == 0:
                # Register direct: value IS the base register
                return 0, True, base_val & MASK32, False, 0, 0
            elif mode == 1:
                return (base_val + idx_val) & MASK32, False, 0, False, 0, 0
            elif mode == 2:
                return (base_val + idx_val + offset) & MASK32, False, 0, False, 0, 0
            elif mode == 3:
                addr = (base_val + idx_val) & MASK32
                new_idx = (idx_val + offset) & MASK32
                return addr, False, 0, True, idx_sel, new_idx

    def step(self):
        if self.pc >= 0x10000:
            self.halted = True
            return

        # Fetch
        ir = self.mem_read(self.pc, 2)
        opcode = (ir >> 27) & 0x1F
        rd = (ir >> 24) & 0x7
        size = (ir >> 22) & 0x3
        reg_val = (ir >> 21) & 1
        addr_imm = (ir >> 20) & 1
        payload = ir & 0xFFFFF

        base_sel = (payload >> 17) & 7
        idx_sel = (payload >> 12) & 7
        base_val = self.reg_read(base_sel)
        idx_val = self.reg_read(idx_sel)

        eff_addr, is_imm, imm_value, wb_en, wb_reg, wb_val = self.agu(
            reg_val, addr_imm, payload, base_val, idx_val)

        op_name = OP_NAMES.get(opcode, f'?{opcode}')
        if self.trace:
            sz = SIZE_NAMES.get(size, '??')
            print(f"{self.pc:04X}: {ir:08X}  {op_name}{sz}  r{rd}  "
                  f"{'imm=' + hex(imm_value) if is_imm else 'addr=' + hex(eff_addr)}"
                  f"  regs={[hex(self.reg_read(i)) for i in range(8)]}")

        self.cycles += 1

        if opcode == OP_NOP:
            self.pc += 4

        elif opcode == OP_LD:
            if is_imm:
                new_val = imm_value
            else:
                new_val = self.mem_read(eff_addr, size)
            # Size merge: only write the sized portion, preserve upper bits
            old_val = self.reg_read(rd)
            if size == 0:  # .8
                merged = (old_val & 0xFFFFFF00) | (new_val & 0xFF)
            elif size == 1:  # .16
                merged = (old_val & 0xFFFF0000) | (new_val & 0xFFFF)
            else:  # .32
                merged = new_val
            self.reg_write(rd, merged)
            if wb_en:
                self.reg_write(wb_reg, wb_val)
            self.pc += 4

        elif opcode == OP_LDH:
            old = self.reg_read(rd)
            self.reg_write(rd, (payload << 12) | (old & 0xFFF))
            self.pc += 4

        elif opcode == OP_ST:
            if is_imm:
                # st [rd], #imm
                addr = self.reg_read(rd)
                self.mem_write(addr, size, imm_value)
            else:
                self.mem_write(eff_addr, size, self.reg_read(rd))
            if wb_en:
                self.reg_write(wb_reg, wb_val)
            self.pc += 4

        elif opcode in (OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR, OP_ASR):
            if is_imm:
                operand = imm_value
            else:
                operand = self.mem_read(eff_addr, size)
            rd_val = self.reg_read(rd)
            if opcode == OP_ADD:
                result = rd_val + operand
            elif opcode == OP_SUB:
                result = rd_val - operand
            elif opcode == OP_AND:
                result = rd_val & operand
            elif opcode == OP_OR:
                result = rd_val | operand
            elif opcode == OP_XOR:
                result = rd_val ^ operand
            elif opcode == OP_SHL:
                result = rd_val << (operand & 0x1F)
            elif opcode == OP_SHR:
                result = rd_val >> (operand & 0x1F)
            elif opcode == OP_ASR:
                # Arithmetic right shift: preserve sign
                result = to_signed32(rd_val) >> (operand & 0x1F)
                result &= MASK32
            # Size merge: write only the sized portion, preserve upper bits
            old_val = self.reg_read(rd)
            if size == 0:  # .8
                result = (old_val & 0xFFFFFF00) | (result & 0xFF)
            elif size == 1:  # .16
                result = (old_val & 0xFFFF0000) | (result & 0xFFFF)
            self.reg_write(rd, result)
            if wb_en:
                self.reg_write(wb_reg, wb_val)
            self.pc += 4

        elif opcode in (OP_BEQ, OP_BNE, OP_BLT, OP_BGT, OP_BLE, OP_BGE):
            br_is_imm = (payload >> 19) & 1
            br_cmp_sel = (payload >> 16) & 7
            br_target = payload & 0xFFFF

            rd_val = self.reg_read(rd)
            if br_is_imm:
                cmp_val = br_cmp_sel
            else:
                cmp_val = self.reg_read(br_cmp_sel)

            # Size-mask for comparison
            if size == 0:  # .8
                rd_val = sign_extend(rd_val & 0xFF, 8) & MASK32
                cmp_val = sign_extend(cmp_val & 0xFF, 8) & MASK32
            elif size == 1:  # .16
                rd_val = sign_extend(rd_val & 0xFFFF, 16) & MASK32
                cmp_val = sign_extend(cmp_val & 0xFFFF, 16) & MASK32

            rd_s = to_signed32(rd_val)
            cmp_s = to_signed32(cmp_val)

            taken = False
            if opcode == OP_BEQ:
                taken = (rd_val == cmp_val)
            elif opcode == OP_BNE:
                taken = (rd_val != cmp_val)
            elif opcode == OP_BLT:
                taken = (rd_s < cmp_s)
            elif opcode == OP_BGT:
                taken = (rd_s > cmp_s)
            elif opcode == OP_BLE:
                taken = (rd_s <= cmp_s)
            elif opcode == OP_BGE:
                taken = (rd_s >= cmp_s)

            if self.trace:
                print(f"  branch: rd_val={rd_s} cmp_val={cmp_s} taken={taken} target={br_target:#06x}")

            if taken:
                self.pc = br_target
            else:
                self.pc += 4

        elif opcode == OP_CALL:
            # 16-bit absolute target (matches branch encoding).
            target = payload & 0xFFFF
            sp = self.reg_read(7)
            sp = (sp - 4) & MASK32
            self.mem_write(sp, 2, (self.pc + 4) & MASK32)
            self.regs[7] = sp
            if self.trace:
                print(f"  call: target={target:#x} ret={self.pc+4:#x} sp={sp:#x}")
            self.pc = target

        elif opcode == OP_RET:
            sp = self.reg_read(7)
            ret_addr = self.mem_read(sp, 2)
            self.regs[7] = (sp + 4) & MASK32
            if self.trace:
                print(f"  ret: addr={ret_addr:#x} sp={self.regs[7]:#x}")
            self.pc = ret_addr

        elif opcode == OP_JMPR:
            # PC = rD
            self.pc = self.reg_read(rd)
            if self.trace:
                print(f"  jmpr: r{rd} = {self.pc:#x}")

        elif opcode == OP_CALLR:
            # sp -= 4, [sp] = PC+4, PC = rD
            target = self.reg_read(rd)
            sp = self.reg_read(7)
            sp = (sp - 4) & MASK32
            self.mem_write(sp, 2, (self.pc + 4) & MASK32)
            self.regs[7] = sp
            if self.trace:
                print(f"  callr: r{rd}={target:#x} ret={self.pc+4:#x}")
            self.pc = target

        else:
            if self.trace:
                print(f"  unknown opcode {opcode}, treating as NOP")
            self.pc += 4

    def run(self, max_cycles=1000000):
        prev_pc = -1
        same_count = 0
        while self.cycles < max_cycles and not self.halted:
            old_pc = self.pc
            self.step()
            # Detect infinite loop (same PC twice in a row)
            if self.pc == old_pc:
                same_count += 1
                if same_count > 1:
                    if self.trace:
                        print(f"\nHalted: infinite loop at {self.pc:#06x}")
                    break
            else:
                same_count = 0
        if self.cycles >= max_cycles:
            print(f"\nHalted: max cycles ({max_cycles}) reached", file=sys.stderr)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    trace = '--trace' in flags

    max_cycles = 1000000
    for f in flags:
        if f.startswith('--max-cycles='):
            max_cycles = int(f.split('=')[1])

    if not args:
        print(f"Usage: {sys.argv[0]} [--trace] [--max-cycles=N] <program.mpu>", file=sys.stderr)
        sys.exit(1)

    prog_path = args[0]
    if '.' not in os.path.basename(prog_path):
        prog_path += '.mpu'
    try:
        with open(prog_path, 'rb') as f:
            program = f.read()
    except FileNotFoundError:
        print(f"error: input file not found: {prog_path}", file=sys.stderr)
        sys.exit(1)

    mpu = MPU(program, trace=trace)
    mpu.run(max_cycles)

    if not trace:
        print()  # newline after UART output

    if trace:
        print(f"\n{mpu.cycles} cycles executed")
        uart_str = ''.join(chr(c) if 32 <= c < 127 else '\\x{:02x}'.format(c) for c in mpu.uart_output)
        print(f"UART output: {uart_str}")


if __name__ == '__main__':
    main()
