#!/usr/bin/env python3
"""Tiny BASIC compiler for the MPU.

Statements:
  Line numbers, LET (optional), PRINT, IF ... THEN ..., GOTO, GOSUB, RETURN,
  FOR var = expr TO expr [STEP expr], NEXT var, END, REM, POKE addr, value.
  Multiple statements per line separated by ':'.

Types:
  Integer variables (32-bit) and string variables (suffix '$', heap pointer).
  Conventional BASIC namespacing: A and A$ are independent.

Operators:
  + - * / on int. Comparisons = <> < > <= >= on int. AND OR on int.
  + on string concatenates (allocates new heap string). = and <> on strings.

Builtins:
  MALLOC(size) -> int   bump-allocate from the heap, return pointer
  PEEK(addr)   -> int   read byte at addr (zero-extended)
  POKE addr, value      store low byte of value at addr (statement)

Memory layout:
  Heap occupies the region ending at 0xF000 (4 KiB below SP=0x10000), grows
  upward from 0xE000. Bump allocator only — there is no FREE.

Notes:
  STEP is assumed non-negative (NEXT uses <=).
  String literals live in code memory; assignments and concatenation results
  live on the heap.
"""
import sys, os

KEYWORDS = {'LET', 'PRINT', 'IF', 'THEN', 'GOTO', 'GOSUB', 'RETURN',
            'FOR', 'TO', 'STEP', 'NEXT', 'END', 'REM', 'AND', 'OR', 'NOT',
            'MALLOC', 'PEEK', 'POKE', 'SLEEP',
            'I2CSTART', 'I2CSTOP', 'I2CWRITE', 'I2CREAD', 'SAR',
            'GPIODIR', 'GPIOWRITE', 'GPIOREAD', 'SETLEDS', 'ADCREAD'}


def tokenize(src):
    toks = []
    line = 1
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '\n':
            toks.append(('NL', None, line))
            line += 1
            i += 1
        elif c in ' \t\r':
            i += 1
        elif c.isdigit():
            if src[i:i+2] in ('0x', '0X'):
                j = i + 2
                while j < n and src[j] in '0123456789abcdefABCDEF':
                    j += 1
                toks.append(('NUM', int(src[i+2:j], 16), line))
                i = j
            else:
                j = i
                while j < n and src[j].isdigit():
                    j += 1
                toks.append(('NUM', int(src[i:j]), line))
                i = j
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 1
            toks.append(('STR', src[i+1:j], line))
            i = j + 1
        elif c.isalpha() or c == '_':
            j = i
            while j < n and (src[j].isalnum() or src[j] == '_'):
                j += 1
            if j < n and src[j] == '$':
                j += 1
            w = src[i:j].upper()
            if w == 'REM':
                while i < n and src[i] != '\n':
                    i += 1
                continue
            if w in KEYWORDS:
                toks.append((w, w, line))
            else:
                toks.append(('IDENT', w, line))
            i = j
        elif src[i:i+2] in ('<=', '>=', '<>', '<<', '>>'):
            toks.append((src[i:i+2], src[i:i+2], line))
            i += 2
        elif c in '+-*/=<>(),;:~':
            toks.append((c, c, line))
            i += 1
        else:
            raise SyntaxError(f"Line {line}: unexpected {c!r}")
    toks.append(('EOF', None, line))
    return toks


HEAP_BASE = 0xE000  # heap grows up; stack starts at 0x10000 → 4 KiB headroom


class Compiler:
    def __init__(self):
        self.body = []
        self.tok = []
        self.pos = 0
        self.int_vars = set()
        self.str_vars = set()       # names without the trailing '$'
        self.strings = []
        self.for_stack = []
        self.for_count = 0
        self.label_n = 0

    # ---- helpers ----
    def emit(self, s=''):
        self.body.append(s)

    def peek(self, k=0):
        return self.tok[self.pos + k]

    def advance(self):
        t = self.tok[self.pos]
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.advance()
        if t[0] != kind:
            raise SyntaxError(f"Line {t[2]}: expected {kind}, got {t[0]}")
        return t

    def match(self, *kinds):
        if self.peek()[0] in kinds:
            return self.advance()
        return None

    def syntax(self, msg):
        raise SyntaxError(f"Line {self.peek()[2]}: {msg}")

    def new_label(self, hint):
        self.label_n += 1
        return f'_{hint}_{self.label_n}'

    def use_int_var(self, name):
        if name.endswith('$'):
            raise SyntaxError(f"Variable {name} is a string variable")
        self.int_vars.add(name)
        return f'_V_{name}'

    def use_str_var(self, name):
        # name still has the trailing '$'
        bare = name[:-1]
        self.str_vars.add(bare)
        return f'_VS_{bare}'

    def add_string(self, s):
        idx = len(self.strings)
        self.strings.append(s)
        return f'_S_{idx}'

    # ---- top-level ----
    def compile(self, src):
        self.tok = tokenize(src)

        while self.peek()[0] != 'EOF':
            if self.peek()[0] == 'NL':
                self.advance()
                continue
            line_tok = self.expect('NUM')
            self.emit(f'_L{line_tok[1]}:')
            # An empty line (e.g. just a REM that the lexer dropped) is allowed.
            if self.peek()[0] not in ('NL', 'EOF'):
                self.parse_stmt_list()
            if self.peek()[0] == 'NL':
                self.advance()
            elif self.peek()[0] != 'EOF':
                raise SyntaxError(f"Line {line_tok[1]}: expected newline")

        if self.for_stack:
            raise SyntaxError(f"Unclosed FOR: {self.for_stack[-1][0]}")

        out = []
        out.append('                jmp     __start')
        out.append('')

        # Inline helper: print null-terminated string (no newline).
        out.append('__print_str:')
        out.append('                sub.32  sp, #4')
        out.append('                st.32   [sp], r6')
        out.append('                sub.32  sp, #4')
        out.append('                st.32   [sp], r5')
        out.append('                ld.32   r5, [sp][r0+12]')
        out.append('.loop:          ld.8    r1, [r5++]')
        out.append('                beq.8   r1, #0, .done')
        out.append('                call    __putc')
        out.append('                jmp     .loop')
        out.append('.done:          ld.32   r5, [r0][sp+=4]')
        out.append('                ld.32   r6, [r0][sp+=4]')
        out.append('                ret')
        out.append('')

        # Inline helper: arithmetic shift right.
        # Caller pushes x then n, so at entry [sp+0]=ret, [sp+4]=n, [sp+8]=x.
        # Returns shifted value in r1.
        out.append('__sar:')
        out.append('                ld.32   r1, [sp][r0+8]')
        out.append('                ld.32   r2, [sp][r0+4]')
        out.append('                ld.32   r3, #0')
        out.append('                bge.32  r1, r3, .pos')
        out.append('                xor.32  r1, #-1')
        out.append('.nloop:         beq.32  r2, #0, .ndone')
        out.append('                shr.32  r1, #1')
        out.append('                sub.32  r2, #1')
        out.append('                jmp     .nloop')
        out.append('.ndone:         xor.32  r1, #-1')
        out.append('                ret')
        out.append('.pos:           beq.32  r2, #0, .pdone')
        out.append('                shr.32  r1, #1')
        out.append('                sub.32  r2, #1')
        out.append('                jmp     .pos')
        out.append('.pdone:         ret')
        out.append('')

        out.append('__start:')
        # Initialise heap pointer.
        out.append(f'                ld.32   r1, #{HEAP_BASE}')
        out.append('                st.32   _heap_ptr, r1')
        # All string variables start out pointing at the empty string.
        if self.str_vars:
            out.append('                ld.32   r1, #_S_empty')
            for v in sorted(self.str_vars):
                out.append(f'                st.32   _VS_{v}, r1')

        out.extend(self.body)

        out.append('__halt:         jmp     __halt')
        out.append('')

        for v in sorted(self.int_vars):
            out.append(f'_V_{v}: db 0x00, 0x00, 0x00, 0x00')
        for v in sorted(self.str_vars):
            out.append(f'_VS_{v}: db 0x00, 0x00, 0x00, 0x00')
        for i in range(1, self.for_count + 1):
            out.append(f'_FL_{i}: db 0x00, 0x00, 0x00, 0x00')
            out.append(f'_FS_{i}: db 0x00, 0x00, 0x00, 0x00')

        out.append('_FMT_D: db 0x25, 0x64, 0x00')

        for idx, s in enumerate(self.strings):
            data = s.encode('utf-8') + b'\x00'
            hx = ', '.join(f'0x{b:02X}' for b in data)
            out.append(f'_S_{idx}: db {hx}')

        return '\n'.join(out) + '\n'

    # ---- statements ----
    def parse_stmt_list(self):
        self.parse_stmt()
        while self.match(':'):
            self.parse_stmt()

    def parse_stmt(self):
        t = self.peek()
        k = t[0]
        if k == 'LET':
            self.advance()
            self.parse_let()
        elif k == 'IDENT' and self.peek(1)[0] == '=':
            self.parse_let()
        elif k == 'PRINT':
            self.advance()
            self.parse_print()
        elif k == 'IF':
            self.advance()
            self.parse_if()
        elif k == 'GOTO':
            self.advance()
            n = self.expect('NUM')[1]
            self.emit(f'                jmp     _L{n}')
        elif k == 'GOSUB':
            self.advance()
            n = self.expect('NUM')[1]
            self.emit(f'                call    _L{n}')
        elif k == 'RETURN':
            self.advance()
            self.emit(f'                ret')
        elif k == 'FOR':
            self.advance()
            self.parse_for()
        elif k == 'NEXT':
            self.advance()
            self.parse_next()
        elif k == 'END':
            self.advance()
            self.emit(f'                jmp     __halt')
        elif k == 'POKE':
            self.advance()
            self.parse_poke()
        elif k == 'SLEEP':
            self.advance()
            if self.gen_expr() != 'int':
                self.syntax("SLEEP argument must be int")
            self.push_r1()
            self.emit(f'                call    sleep')
            self.emit(f'                add.32  sp, #4')
        elif k == 'I2CSTART':
            self.advance()
            self.emit(f'                call    i2c_start')
        elif k == 'I2CSTOP':
            self.advance()
            self.emit(f'                call    i2c_stop')
        elif k == 'I2CWRITE':
            self.advance()
            if self.gen_expr() != 'int':
                self.syntax("I2CWRITE argument must be int")
            self.push_r1()
            self.emit(f'                call    i2c_write')
            self.emit(f'                add.32  sp, #4')
        elif k == 'GPIODIR':
            self.advance()
            if self.gen_expr() != 'int':
                self.syntax("GPIODIR argument must be int")
            self.push_r1()
            self.emit(f'                call    gpio_set_dir')
            self.emit(f'                add.32  sp, #4')
        elif k == 'GPIOWRITE':
            self.advance()
            if self.gen_expr() != 'int':
                self.syntax("GPIOWRITE argument must be int")
            self.push_r1()
            self.emit(f'                call    gpio_write')
            self.emit(f'                add.32  sp, #4')
        elif k == 'SETLEDS':
            self.advance()
            if self.gen_expr() != 'int':
                self.syntax("SETLEDS argument must be int")
            self.push_r1()
            self.emit(f'                call    setleds')
            self.emit(f'                add.32  sp, #4')
        else:
            raise SyntaxError(f"Line {t[2]}: unexpected {k}")

    def parse_let(self):
        name = self.expect('IDENT')[1]
        self.expect('=')
        ty = self.gen_expr()
        if name.endswith('$'):
            if ty != 'str':
                self.syntax("type mismatch: assigning int to string variable")
            label = self.use_str_var(name)
        else:
            if ty != 'int':
                self.syntax("type mismatch: assigning string to int variable")
            label = self.use_int_var(name)
        self.emit(f'                st.32   {label}, r1')

    def parse_print(self):
        suppress_nl = False
        if self.peek()[0] not in ('NL', 'EOF', ':'):
            self.emit_print_item()
            while self.peek()[0] in (';', ','):
                self.advance()
                if self.peek()[0] in ('NL', 'EOF', ':'):
                    suppress_nl = True
                    break
                self.emit_print_item()
        if not suppress_nl:
            self.emit(f'                ld.32   r1, #10')
            self.emit(f'                call    __putc')

    def emit_print_item(self):
        ty = self.gen_expr()
        if ty == 'str':
            self.emit(f'                sub.32  sp, #4')
            self.emit(f'                st.32   [sp], r1')
            self.emit(f'                call    __print_str')
            self.emit(f'                add.32  sp, #4')
        else:
            self.emit(f'                sub.32  sp, #4')
            self.emit(f'                st.32   [sp], r1')
            self.emit(f'                ld.32   r1, #_FMT_D')
            self.emit(f'                sub.32  sp, #4')
            self.emit(f'                st.32   [sp], r1')
            self.emit(f'                call    printf')
            self.emit(f'                add.32  sp, #8')

    def parse_if(self):
        ty = self.gen_expr()
        if ty != 'int':
            self.syntax("IF condition must be int")
        self.expect('THEN')
        end_label = self.new_label('endif')
        self.emit(f'                beq.32  r1, #0, {end_label}')
        if self.peek()[0] == 'NUM':
            n = self.advance()[1]
            self.emit(f'                jmp     _L{n}')
        else:
            self.parse_stmt_list()
        self.emit(f'{end_label}:')

    def parse_for(self):
        self.for_count += 1
        loop_id = self.for_count
        name = self.expect('IDENT')[1]
        var = self.use_int_var(name)
        self.expect('=')
        if self.gen_expr() != 'int':
            self.syntax("FOR start must be int")
        self.emit(f'                st.32   {var}, r1')
        self.expect('TO')
        if self.gen_expr() != 'int':
            self.syntax("FOR limit must be int")
        self.emit(f'                st.32   _FL_{loop_id}, r1')
        if self.match('STEP'):
            if self.gen_expr() != 'int':
                self.syntax("FOR step must be int")
        else:
            self.emit(f'                ld.32   r1, #1')
        self.emit(f'                st.32   _FS_{loop_id}, r1')
        self.emit(f'_FORBODY_{loop_id}:')
        self.for_stack.append((name, loop_id))

    def parse_next(self):
        name = self.expect('IDENT')[1]
        if not self.for_stack:
            raise SyntaxError("NEXT without FOR")
        top_name, loop_id = self.for_stack[-1]
        if top_name != name:
            raise SyntaxError(f"NEXT {name} does not match FOR {top_name}")
        self.for_stack.pop()
        var = self.use_int_var(name)
        self.emit(f'                ld.32   r1, {var}')
        self.emit(f'                ld.32   r2, _FS_{loop_id}')
        self.emit(f'                sub.32  sp, #4')
        self.emit(f'                st.32   [sp], r2')
        self.emit(f'                add.32  r1, [sp]')
        self.emit(f'                add.32  sp, #4')
        self.emit(f'                st.32   {var}, r1')
        self.emit(f'                ld.32   r2, _FL_{loop_id}')
        self.emit(f'                ble.32  r1, r2, _FORBODY_{loop_id}')

    def parse_poke(self):
        if self.gen_expr() != 'int':
            self.syntax("POKE address must be int")
        self.expect(',')
        self.push_r1()
        if self.gen_expr() != 'int':
            self.syntax("POKE value must be int")
        # r1 = value, [sp] = address
        self.emit(f'                ld.32   r2, [r0][sp+=4]')
        self.emit(f'                st.8    [r2], r1')

    # ---- expressions (result always in r1; returns 'int' or 'str') ----
    def push_r1(self):
        self.emit(f'                sub.32  sp, #4')
        self.emit(f'                st.32   [sp], r1')

    def gen_expr(self):
        return self.gen_or()

    def gen_or(self):
        t = self.gen_and()
        while self.peek()[0] == 'OR':
            if t != 'int':
                self.syntax("OR requires int")
            self.advance()
            self.push_r1()
            if self.gen_and() != 'int':
                self.syntax("OR requires int")
            self.emit(f'                or.32   r1, [sp]')
            self.emit(f'                add.32  sp, #4')
        return t

    def gen_and(self):
        t = self.gen_rel()
        while self.peek()[0] == 'AND':
            if t != 'int':
                self.syntax("AND requires int")
            self.advance()
            self.push_r1()
            if self.gen_rel() != 'int':
                self.syntax("AND requires int")
            self.emit(f'                and.32  r1, [sp]')
            self.emit(f'                add.32  sp, #4')
        return t

    def gen_rel(self):
        t = self.gen_shift()
        CMP = {'=': 'beq', '<>': 'bne', '<': 'blt', '>': 'bgt',
               '<=': 'ble', '>=': 'bge'}
        if self.peek()[0] in CMP:
            op = self.advance()[0]
            if t == 'str':
                if op not in ('=', '<>'):
                    self.syntax("string compare supports only = and <>")
                self.push_r1()
                if self.gen_add() != 'str':
                    self.syntax("type mismatch in string compare")
                # __strcmp(a, b): need [sp+4]=a (left), [sp+8]=b (right).
                self.emit(f'                ld.32   r2, [r0][sp+=4]')  # pop left
                self.push_r1()                                          # push right
                self.emit(f'                sub.32  sp, #4')
                self.emit(f'                st.32   [sp], r2')          # push left
                self.emit(f'                call    __strcmp')
                self.emit(f'                add.32  sp, #8')
                tl = self.new_label('cmpt')
                self.emit(f'                ld.32   r3, #1')
                if op == '=':
                    self.emit(f'                beq.32  r1, #0, {tl}')
                else:
                    self.emit(f'                bne.32  r1, #0, {tl}')
                self.emit(f'                ld.32   r3, #0')
                self.emit(f'{tl}:')
                self.emit(f'                ld.32   r1, r3')
                return 'int'
            self.push_r1()
            if self.gen_shift() != 'int':
                self.syntax("type mismatch in compare")
            self.emit(f'                ld.32   r2, [r0][sp+=4]')
            tl = self.new_label('cmpt')
            self.emit(f'                ld.32   r3, #1')
            self.emit(f'                {CMP[op]}.32 r2, r1, {tl}')
            self.emit(f'                ld.32   r3, #0')
            self.emit(f'{tl}:')
            self.emit(f'                ld.32   r1, r3')
            return 'int'
        return t

    def gen_shift(self):
        t = self.gen_add()
        while self.peek()[0] in ('<<', '>>'):
            if t != 'int':
                self.syntax("shift requires int")
            op = self.advance()[0]
            self.push_r1()                          # save left
            if self.gen_add() != 'int':
                self.syntax("shift requires int")
            self.push_r1()                          # save right
            self.emit(f'                ld.32   r1, [sp][r0+4]')   # left
            mnem = 'shl' if op == '<<' else 'shr'
            self.emit(f'                {mnem}.32 r1, [sp]')
            self.emit(f'                add.32  sp, #8')
        return t

    def gen_add(self):
        t = self.gen_mul()
        while self.peek()[0] in ('+', '-'):
            op = self.advance()[0]
            if t == 'str':
                if op != '+':
                    self.syntax("strings only support + (concatenation)")
                self.push_r1()
                if self.gen_mul() != 'str':
                    self.syntax("type mismatch in concatenation")
                # __strcat(a, b): need [sp+4]=a, [sp+8]=b.
                self.emit(f'                ld.32   r2, [r0][sp+=4]')  # pop a
                self.push_r1()                                          # push b
                self.emit(f'                sub.32  sp, #4')
                self.emit(f'                st.32   [sp], r2')          # push a
                self.emit(f'                call    __strcat')
                self.emit(f'                add.32  sp, #8')
                # t stays 'str'
            else:
                self.push_r1()
                if self.gen_mul() != 'int':
                    self.syntax("type mismatch in arithmetic")
                if op == '+':
                    self.emit(f'                add.32  r1, [sp]')
                    self.emit(f'                add.32  sp, #4')
                else:
                    self.push_r1()
                    self.emit(f'                ld.32   r1, [sp][r0+4]')
                    self.emit(f'                sub.32  r1, [sp]')
                    self.emit(f'                add.32  sp, #8')
        return t

    def gen_mul(self):
        t = self.gen_unary()
        while self.peek()[0] in ('*', '/'):
            if t != 'int':
                self.syntax("* and / require int")
            op = self.advance()[0]
            self.push_r1()
            if self.gen_unary() != 'int':
                self.syntax("* and / require int")
            self.emit(f'                ld.32   r2, [r0][sp+=4]')  # pop left
            self.push_r1()                                          # push right
            self.emit(f'                sub.32  sp, #4')
            self.emit(f'                st.32   [sp], r2')          # push left
            if op == '*':
                self.emit(f'                call    __mul')
            else:
                self.emit(f'                call    __div')
            self.emit(f'                add.32  sp, #8')
        return t

    def gen_unary(self):
        if self.peek()[0] == '-':
            self.advance()
            if self.gen_unary() != 'int':
                self.syntax("unary - requires int")
            self.push_r1()
            self.emit(f'                ld.32   r1, #0')
            self.emit(f'                sub.32  r1, [sp]')
            self.emit(f'                add.32  sp, #4')
            return 'int'
        if self.peek()[0] in ('~', 'NOT'):
            self.advance()
            if self.gen_unary() != 'int':
                self.syntax("~ requires int")
            self.emit(f'                xor.32  r1, #-1')
            return 'int'
        return self.gen_primary()

    def gen_primary(self):
        t = self.peek()
        k = t[0]
        if k == 'NUM':
            self.advance()
            self.emit(f'                ldi     r1, #{t[1]}')
            return 'int'
        if k == 'STR':
            s = self.advance()[1]
            lbl = self.add_string(s)
            self.emit(f'                ld.32   r1, #{lbl}')
            return 'str'
        if k == 'IDENT':
            name = self.advance()[1]
            if name.endswith('$'):
                lbl = self.use_str_var(name)
                self.emit(f'                ld.32   r1, {lbl}')
                return 'str'
            lbl = self.use_int_var(name)
            self.emit(f'                ld.32   r1, {lbl}')
            return 'int'
        if k == 'MALLOC':
            self.advance()
            self.expect('(')
            if self.gen_expr() != 'int':
                self.syntax("MALLOC size must be int")
            self.expect(')')
            self.push_r1()
            self.emit(f'                call    __halloc')
            self.emit(f'                add.32  sp, #4')
            return 'int'
        if k == 'PEEK':
            self.advance()
            self.expect('(')
            if self.gen_expr() != 'int':
                self.syntax("PEEK address must be int")
            self.expect(')')
            # ld.8 only writes the low byte, preserving upper bits — so move
            # the address out of r1, zero r1, then load the byte to get a
            # clean zero-extended value.
            self.emit(f'                ld.32   r2, r1')
            self.emit(f'                ld.32   r1, #0')
            self.emit(f'                ld.8    r1, [r2]')
            return 'int'
        if k == 'I2CREAD':
            self.advance()
            self.expect('(')
            if self.gen_expr() != 'int':
                self.syntax("I2CREAD argument must be int")
            self.expect(')')
            self.push_r1()
            self.emit(f'                call    i2c_read')
            self.emit(f'                add.32  sp, #4')
            return 'int'
        if k == 'GPIOREAD':
            self.advance()
            # Optional empty parens for symmetry.
            if self.peek()[0] == '(':
                self.advance()
                self.expect(')')
            self.emit(f'                call    gpio_read')
            return 'int'
        if k == 'ADCREAD':
            self.advance()
            if self.peek()[0] == '(':
                self.advance()
                self.expect(')')
            self.emit(f'                call    adc_read')
            return 'int'
        if k == 'SAR':
            self.advance()
            self.expect('(')
            if self.gen_expr() != 'int':
                self.syntax("SAR x must be int")
            self.push_r1()
            self.expect(',')
            if self.gen_expr() != 'int':
                self.syntax("SAR n must be int")
            self.push_r1()
            self.expect(')')
            self.emit(f'                call    __sar')
            self.emit(f'                add.32  sp, #8')
            return 'int'
        if k == '(':
            self.advance()
            ty = self.gen_expr()
            self.expect(')')
            return ty
        raise SyntaxError(f"Line {t[2]}: expected value, got {k}")


def main():
    args = sys.argv[1:]
    save_asm = False
    if '-S' in args:
        save_asm = True
        args.remove('-S')
    if len(args) < 1:
        print(f"Usage: {sys.argv[0]} [-S] <input.bas>", file=sys.stderr)
        sys.exit(1)
    inp = args[0]
    if '.' not in os.path.basename(inp):
        inp += '.bas'
    try:
        with open(inp) as f:
            src = f.read()
    except FileNotFoundError:
        print(f"error: input file not found: {inp}", file=sys.stderr)
        sys.exit(1)

    c = Compiler()
    asm = c.compile(src)

    stdlib = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stdlib.asm')
    if os.path.exists(stdlib):
        asm += '\n; ---- Standard Library ----\n'
        with open(stdlib) as f:
            asm += f.read()

    asm += '\n                end\n'

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import asm as _asm
    asm = _asm.to_pseudo_ops(asm)
    asm = _asm.hide_r0(asm)

    if save_asm:
        s_file = inp.rsplit('.', 1)[0] + '.s'
        with open(s_file, 'w') as f:
            f.write(asm)
        print(f"Wrote {s_file}")

    binary = _asm.assemble(asm)
    mpu_file = inp.rsplit('.', 1)[0] + '.mpu'
    with open(mpu_file, 'wb') as f:
        f.write(binary)
    print(f"Compiled {inp} -> {mpu_file} ({len(binary)} bytes)")


if __name__ == '__main__':
    main()
