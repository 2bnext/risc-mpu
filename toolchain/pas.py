#!/usr/bin/env python3
"""Tiny Pascal compiler for the MPU.

Supported subset:
  program <name>; [const ...] [var ...] [proc/func ...] begin ... end.
  Types: integer (32-bit), char alias (also 32-bit; no array-of-char).
  const NAME = <int>;            (integer constants only)
  var name1, name2 : integer;
  procedure / function with value parameters and local var blocks.
    function name(...) : integer; var ...; begin ... name := expr; ... end;
  Statements: := , if/then[/else], while/do, for/to/downto/do, repeat/until,
              begin/end, procedure call, writeln/write, exit (early return).
  Operators:
      not -                                       (unary)
      *  div  mod  and  shl  shr                  (multiplicative)
      +  -    or   xor                            (additive)
      =  <>  <  <=  >  >=                         (relational)
  Built-in routines (proxied to stdlib.asm):
      writeln/write — variadic, accept string literals and integer expressions
      sleep(ms), i2cstart, i2cstop, i2cwrite(b), peek(addr), poke(addr, val)
      function i2cread(ack: integer): integer
      function sar(x, n: integer): integer        (true arithmetic shift right)

Calling convention:
  Caller pushes args right-to-left, then `call`. Callee saves r6, reserves
  local frame. After prologue, the frame is:
      sp+0 .. sp+L-4   = local variables (slot 0 = function result)
      sp+L             = saved r6
      sp+L+4           = return address
      sp+L+8           = arg0 (leftmost)
      sp+L+12          = arg1, ...
  The compiler tracks `temp_depth` for expression-temp pushes and adjusts
  every variable access by temp_depth*4 so [sp+...] still resolves correctly
  when intermediates are sitting on top of the frame.
"""
import sys, os

# ---------- tokenizer ----------

KEYWORDS = {
    'PROGRAM', 'CONST', 'VAR', 'BEGIN', 'END', 'IF', 'THEN', 'ELSE',
    'WHILE', 'DO', 'FOR', 'TO', 'DOWNTO', 'REPEAT', 'UNTIL',
    'PROCEDURE', 'FUNCTION', 'INTEGER', 'CHAR',
    'AND', 'OR', 'XOR', 'NOT', 'DIV', 'MOD', 'SHL', 'SHR',
    'TRUE', 'FALSE', 'EXIT',
    # Built-in routine names (special-cased in primary/statement parser)
    'WRITELN', 'WRITE', 'SLEEP',
    'I2CSTART', 'I2CSTOP', 'I2CWRITE', 'I2CREAD',
    'PEEK', 'POKE', 'SAR',
}


def tokenize(src):
    toks = []
    line = 1
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '\n':
            line += 1
            i += 1
        elif c in ' \t\r':
            i += 1
        elif c == '{':                          # { ... } comment
            while i < n and src[i] != '}':
                if src[i] == '\n':
                    line += 1
                i += 1
            i += 1
        elif src[i:i+2] == '(*':                # (* ... *) comment
            i += 2
            while i < n and src[i:i+2] != '*)':
                if src[i] == '\n':
                    line += 1
                i += 1
            i += 2
        elif src[i:i+2] == '//':                # // line comment (extension)
            while i < n and src[i] != '\n':
                i += 1
        elif c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            toks.append(('NUM', int(src[i:j]), line))
            i = j
        elif c == '$':                          # $hex literal
            j = i + 1
            while j < n and src[j] in '0123456789abcdefABCDEF':
                j += 1
            toks.append(('NUM', int(src[i+1:j], 16), line))
            i = j
        elif c == "'":                          # 'string'
            j = i + 1
            buf = []
            while j < n:
                if src[j] == "'":
                    if j + 1 < n and src[j+1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(src[j])
                j += 1
            toks.append(('STR', ''.join(buf), line))
            i = j + 1
        elif c.isalpha() or c == '_':
            j = i
            while j < n and (src[j].isalnum() or src[j] == '_'):
                j += 1
            w = src[i:j].upper()
            if w in KEYWORDS:
                toks.append((w, w, line))
            else:
                # Pascal is case-insensitive: canonicalize identifiers.
                toks.append(('IDENT', src[i:j].lower(), line))
            i = j
        elif src[i:i+2] in (':=', '<=', '>=', '<>'):
            toks.append((src[i:i+2], src[i:i+2], line))
            i += 2
        elif c in '+-*/=<>(),;:.':
            toks.append((c, c, line))
            i += 1
        else:
            raise SyntaxError(f"Line {line}: unexpected {c!r}")
    toks.append(('EOF', None, line))
    return toks


# ---------- compiler ----------

class Compiler:
    def __init__(self):
        self.tok = []
        self.pos = 0
        self.body = []                  # current function body asm
        self.funcs_asm = []              # all emitted functions
        self.strings = []                # (label, bytes)
        self.label_n = 0

        self.globals = {}                # name -> ('global', label)
        self.consts = {}                 # name -> int value
        self.routines = {}               # name -> (kind, asm_label, [param_names], is_func)
                                         # kind: 'user' | 'builtin'
        # Per-function compilation state
        self.locals = {}                 # name -> ('local'|'param', offset)
        self.frame_size = 0
        self.temp_depth = 0
        self.cur_func = None             # name of current function (or None)
        self.cur_is_func = False
        self.epilogue_label = None

    # ---- token helpers ----
    def peek(self, k=0):
        return self.tok[self.pos + k]

    def advance(self):
        t = self.tok[self.pos]
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.advance()
        if t[0] != kind:
            raise SyntaxError(f"Line {t[2]}: expected {kind}, got {t[0]} ({t[1]!r})")
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

    def emit(self, s=''):
        self.body.append(s)

    def add_string(self, s):
        idx = len(self.strings)
        label = f'_PS_{idx}'
        self.strings.append((label, s))
        return label

    # ---- code helpers ----
    def push_r1(self):
        self.emit('                sub.32  sp, #4')
        self.emit('                st.32   [sp], r1')
        self.temp_depth += 1

    def pop_r2(self):
        self.emit('                ld.32   r2, [r0][sp+=4]')
        self.temp_depth -= 1

    def load_imm(self, reg, val):
        # Always use the `ldi` pseudo; the assembler picks ld or ld+ldh.
        self.emit(f'                ldi     r{reg}, #{val}')

    def var_addr_load(self, name):
        """Emit code to load variable's value into r1."""
        if name in self.locals:
            kind, base = self.locals[name]
            off = base + self.temp_depth * 4
            self.emit(f'                ld.32   r1, [sp][r0+{off}]')
            return
        if name in self.globals:
            label = self.globals[name][1]
            self.emit(f'                ld.32   r1, {label}')
            return
        if name in self.consts:
            self.load_imm(1, self.consts[name])
            return
        self.syntax(f"undefined identifier {name}")

    def var_store_r1(self, name):
        if name in self.locals:
            kind, base = self.locals[name]
            off = base + self.temp_depth * 4
            self.emit(f'                st.32   [sp][r0+{off}], r1')
            return
        if name in self.globals:
            label = self.globals[name][1]
            self.emit(f'                st.32   {label}, r1')
            return
        self.syntax(f"cannot assign to {name}")

    # ---- top-level ----
    def compile(self, src):
        self.tok = tokenize(src)
        self.expect('PROGRAM')
        self.expect('IDENT')
        self.expect(';')

        # Pre-register built-in routines so calls resolve.
        # (kind, asm_label, num_args_or_None, is_func)
        BUILTINS = {
            'SLEEP':       ('builtin', 'sleep',        1, False),
            'I2CSTART':    ('builtin', 'i2c_start',    0, False),
            'I2CSTOP':     ('builtin', 'i2c_stop',     0, False),
            'I2CWRITE':    ('builtin', 'i2c_write',    1, False),
            'I2CREAD':     ('builtin', 'i2c_read',     1, True),
            'GPIO_SET_DIR':('builtin', 'gpio_set_dir', 1, False),
            'GPIO_WRITE':  ('builtin', 'gpio_write',   1, False),
            'GPIO_READ':   ('builtin', 'gpio_read',    0, True),
            'ADC_READ':    ('builtin', 'adc_read',     0, True),
            'SETLEDS':     ('builtin', 'setleds',      1, False),
            'PEEK':        ('builtin', None,           1, True),  # special
            'POKE':        ('builtin', None,           2, False), # special
            'SAR':         ('builtin', None,           2, True),  # special
        }
        self.builtins = BUILTINS

        # const / var blocks at program scope, plus procedure/function decls.
        while True:
            k = self.peek()[0]
            if k == 'CONST':
                self.advance()
                while self.peek()[0] == 'IDENT':
                    name = self.advance()[1]
                    self.expect('=')
                    val = self.parse_const_int()
                    self.expect(';')
                    self.consts[name] = val
            elif k == 'VAR':
                self.advance()
                while self.peek()[0] == 'IDENT':
                    names = [self.advance()[1]]
                    while self.match(','):
                        names.append(self.expect('IDENT')[1])
                    self.expect(':')
                    self.parse_type()
                    self.expect(';')
                    for n in names:
                        self.globals[n] = ('global', f'_G_{n}')
            elif k in ('PROCEDURE', 'FUNCTION'):
                self.parse_routine()
            else:
                break

        # Main program
        self.expect('BEGIN')
        self.cur_func = None
        self.cur_is_func = False
        self.locals = {}
        self.frame_size = 0
        self.temp_depth = 0
        self.body = []
        self.body.append('__main:')
        self.parse_stmt_list_until('END')
        self.expect('END')
        self.expect('.')
        self.body.append('                jmp     __halt')
        main_asm = list(self.body)

        # Assemble the output file.
        out = []
        out.append('                jmp     __main')
        out.append('')
        for fn in self.funcs_asm:
            out.extend(fn)
            out.append('')
        out.extend(main_asm)
        out.append('__halt:         jmp     __halt')
        out.append('')

        # Globals
        for name, (kind, label) in sorted(self.globals.items()):
            out.append(f'{label}: db 0x00, 0x00, 0x00, 0x00')

        # String literals
        for label, s in self.strings:
            data = s.encode('utf-8') + b'\x00'
            hx = ', '.join(f'0x{b:02X}' for b in data)
            out.append(f'{label}: db {hx}')

        # Format string for integer printing
        out.append('_FMT_D: db 0x25, 0x64, 0x00')

        return '\n'.join(out) + '\n'

    def parse_type(self):
        t = self.advance()
        if t[0] not in ('INTEGER', 'CHAR'):
            raise SyntaxError(f"Line {t[2]}: expected type, got {t[1]}")

    def parse_const_int(self):
        sign = 1
        if self.match('-'):
            sign = -1
        t = self.advance()
        if t[0] == 'NUM':
            return sign * t[1]
        if t[0] == 'IDENT' and t[1] in self.consts:
            return sign * self.consts[t[1]]
        raise SyntaxError(f"Line {t[2]}: expected integer constant")

    # ---- routines ----
    def parse_routine(self):
        kind_tok = self.advance()                    # PROCEDURE or FUNCTION
        is_func = (kind_tok[0] == 'FUNCTION')
        name = self.expect('IDENT')[1]
        params = []                                  # list of param names
        if self.match('('):
            if self.peek()[0] != ')':
                while True:
                    pnames = [self.expect('IDENT')[1]]
                    while self.match(','):
                        pnames.append(self.expect('IDENT')[1])
                    self.expect(':')
                    self.parse_type()
                    params.extend(pnames)
                    if not self.match(';'):
                        break
            self.expect(')')
        if is_func:
            self.expect(':')
            self.parse_type()
        self.expect(';')

        # Local var declarations
        local_names = []
        if self.match('VAR'):
            while self.peek()[0] == 'IDENT':
                names = [self.advance()[1]]
                while self.match(','):
                    names.append(self.expect('IDENT')[1])
                self.expect(':')
                self.parse_type()
                self.expect(';')
                local_names.extend(names)

        # Set up frame: slot 0 reserved for result if function.
        self.cur_func = name
        self.cur_is_func = is_func
        self.locals = {}
        self.temp_depth = 0
        self.body = []

        slot = 0
        if is_func:
            self.locals[name] = ('local', 0)         # function name = result
            slot = 1
        for ln in local_names:
            self.locals[ln] = ('local', slot * 4)
            slot += 1
        local_size = slot * 4
        self.frame_size = local_size

        # Map params: at sp+L+8, sp+L+12, ...  (after r6 and ret-addr)
        for i, pn in enumerate(params):
            self.locals[pn] = ('param', local_size + 8 + i * 4)

        # Register routine before parsing body so it can recurse.
        self.routines[name.upper()] = ('user', name, params, is_func)

        # Prologue
        self.body.append(f'{name}:')
        self.body.append('                sub.32  sp, #4')
        self.body.append('                st.32   [sp], r6')
        if local_size > 0:
            self.body.append(f'                sub.32  sp, #{local_size}')

        self.epilogue_label = self.new_label('epi')

        # Body
        self.expect('BEGIN')
        self.parse_stmt_list_until('END')
        self.expect('END')
        self.expect(';')

        # Epilogue
        self.body.append(f'{self.epilogue_label}:')
        if is_func:
            # Load result into r1.
            self.body.append(f'                ld.32   r1, [sp][r0+0]')
        if local_size > 0:
            self.body.append(f'                add.32  sp, #{local_size}')
        self.body.append('                ld.32   r6, [r0][sp+=4]')
        self.body.append('                ret')

        self.funcs_asm.append(self.body)
        self.body = []
        self.cur_func = None
        self.cur_is_func = False
        self.locals = {}
        self.epilogue_label = None

    # ---- statements ----
    def parse_stmt_list_until(self, *enders):
        while self.peek()[0] not in enders:
            self.parse_stmt()
            if self.peek()[0] == ';':
                self.advance()
            elif self.peek()[0] in enders:
                break
            else:
                # Pascal allows missing semi before END.
                if self.peek()[0] != 'END':
                    self.syntax("expected ';' or end")

    def parse_stmt(self):
        t = self.peek()
        k = t[0]
        if k == 'BEGIN':
            self.advance()
            self.parse_stmt_list_until('END')
            self.expect('END')
        elif k == 'IF':
            self.advance()
            self.parse_if()
        elif k == 'WHILE':
            self.advance()
            self.parse_while()
        elif k == 'FOR':
            self.advance()
            self.parse_for()
        elif k == 'REPEAT':
            self.advance()
            self.parse_repeat()
        elif k == 'WRITELN':
            self.advance()
            self.parse_write(newline=True)
        elif k == 'WRITE':
            self.advance()
            self.parse_write(newline=False)
        elif k == 'EXIT':
            self.advance()
            target = self.epilogue_label if self.epilogue_label else '__halt'
            self.emit(f'                jmp     {target}')
        elif k == 'IDENT':
            self.parse_ident_stmt()
        elif k in ('SLEEP', 'I2CSTART', 'I2CSTOP', 'I2CWRITE', 'POKE'):
            self.parse_builtin_call_stmt()
        else:
            self.syntax(f"unexpected {k}")

    def parse_ident_stmt(self):
        name = self.advance()[1]
        if self.peek()[0] == ':=':
            self.advance()
            self.gen_expr()
            self.var_store_r1(name)
            return
        # Procedure call
        args = []
        if self.match('('):
            if self.peek()[0] != ')':
                args.append(self.collect_arg())
                while self.match(','):
                    args.append(self.collect_arg())
            self.expect(')')
        self.gen_call(name, args)

    def collect_arg(self):
        # We need to defer argument codegen so the caller can push them
        # right-to-left. Easiest: parse the expression now into a saved
        # token slice — but that needs more machinery. Instead, since each
        # argument is a separate expression, we record (start, end) token
        # positions and re-parse when emitting.
        start = self.pos
        depth = 0
        while True:
            k = self.peek()[0]
            if depth == 0 and k in (',', ')'):
                break
            if k == '(':
                depth += 1
            elif k == ')':
                depth -= 1
            self.advance()
        return (start, self.pos)

    def gen_call(self, name, arg_ranges):
        key = name.upper()
        # Built-in special cases that aren't simple call/pop wrappers
        if key == 'PEEK':
            if len(arg_ranges) != 1:
                self.syntax("peek expects 1 argument")
            self.gen_expr_range(arg_ranges[0])
            self.emit(f'                ld.32   r2, r1')
            self.emit(f'                ld.32   r1, #0')
            self.emit(f'                ld.8    r1, [r2]')
            return
        if key == 'POKE':
            if len(arg_ranges) != 2:
                self.syntax("poke expects 2 arguments")
            self.gen_expr_range(arg_ranges[0])     # addr
            self.push_r1()
            self.gen_expr_range(arg_ranges[1])     # value
            self.emit('                ld.32   r2, [r0][sp+=4]')
            self.temp_depth -= 1
            self.emit('                st.8    [r2], r1')
            return
        if key == 'SAR':
            if len(arg_ranges) != 2:
                self.syntax("sar expects 2 arguments")
            # Push x then n, call __sar (defined in BASIC prologue style; we
            # emit our own helper at end of file).
            self.gen_expr_range(arg_ranges[0])     # x
            self.push_r1()
            self.gen_expr_range(arg_ranges[1])     # n
            self.push_r1()
            self.emit('                call    __sar')
            self.emit('                add.32  sp, #8')
            self.temp_depth -= 2
            return

        # Generic call: push args right-to-left, call, pop.
        if key in self.builtins:
            kind, label, nargs, is_func = self.builtins[key]
            if nargs is not None and len(arg_ranges) != nargs:
                self.syntax(f"{name} expects {nargs} argument(s)")
            target = label
        elif key in self.routines:
            r_kind, label, params, is_func = self.routines[key]
            if len(arg_ranges) != len(params):
                self.syntax(f"{name} expects {len(params)} argument(s)")
            target = label
        else:
            self.syntax(f"unknown routine {name}")

        for rng in reversed(arg_ranges):
            self.gen_expr_range(rng)
            self.push_r1()
        self.emit(f'                call    {target}')
        if arg_ranges:
            self.emit(f'                add.32  sp, #{len(arg_ranges) * 4}')
            self.temp_depth -= len(arg_ranges)

    def parse_builtin_call_stmt(self):
        name = self.advance()[1]
        args = []
        if self.match('('):
            if self.peek()[0] != ')':
                args.append(self.collect_arg())
                while self.match(','):
                    args.append(self.collect_arg())
            self.expect(')')
        self.gen_call(name, args)

    def parse_if(self):
        self.gen_expr()
        self.expect('THEN')
        else_label = self.new_label('else')
        end_label = self.new_label('endif')
        self.emit(f'                beq.32  r1, #0, {else_label}')
        self.parse_stmt()
        if self.peek()[0] == ';' and self.peek(1)[0] == 'ELSE':
            self.advance()                     # consume optional ;
        if self.match('ELSE'):
            self.emit(f'                jmp     {end_label}')
            self.emit(f'{else_label}:')
            self.parse_stmt()
            self.emit(f'{end_label}:')
        else:
            self.emit(f'{else_label}:')

    def parse_while(self):
        top = self.new_label('wtop')
        end = self.new_label('wend')
        self.emit(f'{top}:')
        self.gen_expr()
        self.emit(f'                beq.32  r1, #0, {end}')
        self.expect('DO')
        self.parse_stmt()
        self.emit(f'                jmp     {top}')
        self.emit(f'{end}:')

    def parse_for(self):
        name = self.expect('IDENT')[1]
        self.expect(':=')
        self.gen_expr()
        self.var_store_r1(name)
        direction = self.advance()
        if direction[0] not in ('TO', 'DOWNTO'):
            raise SyntaxError(f"Line {direction[2]}: expected TO/DOWNTO")
        up = (direction[0] == 'TO')
        self.gen_expr()                                 # limit in r1
        # Stash limit on the stack — for/downto compares against it each iter.
        self.push_r1()
        limit_off = (self.temp_depth - 1) * 4           # offset within frame
        self.expect('DO')
        top = self.new_label('ftop')
        end = self.new_label('fend')
        self.emit(f'{top}:')
        # Compare current value vs limit
        self.var_addr_load(name)
        self.emit(f'                ld.32   r2, [sp][r0+{limit_off}]')
        if up:
            self.emit(f'                bgt.32  r1, r2, {end}')
        else:
            self.emit(f'                blt.32  r1, r2, {end}')
        self.parse_stmt()
        # Increment / decrement
        self.var_addr_load(name)
        if up:
            self.emit(f'                add.32  r1, #1')
        else:
            self.emit(f'                sub.32  r1, #1')
        self.var_store_r1(name)
        self.emit(f'                jmp     {top}')
        self.emit(f'{end}:')
        # Pop limit
        self.emit(f'                add.32  sp, #4')
        self.temp_depth -= 1

    def parse_repeat(self):
        top = self.new_label('rtop')
        self.emit(f'{top}:')
        # Statements until UNTIL
        while self.peek()[0] != 'UNTIL':
            self.parse_stmt()
            if self.peek()[0] == ';':
                self.advance()
            elif self.peek()[0] != 'UNTIL':
                self.syntax("expected ';' or UNTIL")
        self.expect('UNTIL')
        self.gen_expr()
        # repeat until <cond>: loop while cond is false
        self.emit(f'                beq.32  r1, #0, {top}')

    def parse_write(self, newline):
        if self.match('('):
            if self.peek()[0] != ')':
                self.emit_write_item()
                while self.match(','):
                    self.emit_write_item()
            self.expect(')')
        if newline:
            self.emit('                ld.32   r1, #10')
            self.emit('                call    __putc')

    def emit_write_item(self):
        # Strings emitted via __print_str helper; integers via printf %d.
        if self.peek()[0] == 'STR':
            s = self.advance()[1]
            label = self.add_string(s)
            self.emit(f'                ld.32   r1, #{label}')
            self.push_r1()
            self.emit('                call    __print_str')
            self.emit('                add.32  sp, #4')
            self.temp_depth -= 1
            return
        self.gen_expr()
        self.push_r1()
        self.emit('                ld.32   r1, #_FMT_D')
        self.push_r1()
        self.emit('                call    printf')
        self.emit('                add.32  sp, #8')
        self.temp_depth -= 2

    # ---- expressions (Pascal precedence) ----
    def gen_expr_range(self, rng):
        """Re-evaluate a saved token range as an expression."""
        saved = self.pos
        self.pos = rng[0]
        self.gen_expr()
        self.pos = saved

    def gen_expr(self):
        return self.gen_rel()

    def gen_rel(self):
        self.gen_add()
        CMP = {'=': 'beq', '<>': 'bne', '<': 'blt', '>': 'bgt',
               '<=': 'ble', '>=': 'bge'}
        if self.peek()[0] in CMP:
            op = self.advance()[0]
            self.push_r1()
            self.gen_add()
            self.emit(f'                ld.32   r2, [r0][sp+=4]')
            self.temp_depth -= 1
            tl = self.new_label('cmpt')
            self.emit(f'                ld.32   r3, #1')
            self.emit(f'                {CMP[op]}.32 r2, r1, {tl}')
            self.emit(f'                ld.32   r3, #0')
            self.emit(f'{tl}:')
            self.emit(f'                ld.32   r1, r3')

    def gen_add(self):
        self.gen_mul()
        while self.peek()[0] in ('+', '-', 'OR', 'XOR'):
            op = self.advance()[0]
            self.push_r1()                    # left
            self.gen_mul()                    # r1 = right
            if op == '+':
                self.emit('                add.32  r1, [sp]')
            elif op == '-':
                # right is in r1, left at [sp]; compute left - right.
                self.push_r1()                # save right
                self.emit('                ld.32   r1, [sp][r0+4]')
                self.emit('                sub.32  r1, [sp]')
                self.emit('                add.32  sp, #4')
                self.temp_depth -= 1
            elif op == 'OR':
                self.emit('                or.32   r1, [sp]')
            elif op == 'XOR':
                self.emit('                xor.32  r1, [sp]')
            self.emit('                add.32  sp, #4')
            self.temp_depth -= 1

    def gen_mul(self):
        self.gen_unary()
        while self.peek()[0] in ('*', 'DIV', 'MOD', 'AND', 'SHL', 'SHR'):
            op = self.advance()[0]
            self.push_r1()
            self.gen_unary()
            if op in ('*', 'DIV', 'MOD'):
                helper = {'*': '__mul', 'DIV': '__div', 'MOD': '__mod'}[op]
                self.emit('                ld.32   r2, [r0][sp+=4]')
                self.temp_depth -= 1
                self.push_r1()                # right (tracked)
                self.emit('                sub.32  sp, #4')      # manual push left
                self.emit('                st.32   [sp], r2')
                self.emit(f'                call    {helper}')
                self.emit('                add.32  sp, #8')
                self.temp_depth -= 1          # balance the tracked push above
            elif op == 'AND':
                self.emit('                and.32  r1, [sp]')
                self.emit('                add.32  sp, #4')
                self.temp_depth -= 1
            elif op in ('SHL', 'SHR'):
                # left << right or left >> right; right is in r1, left in [sp].
                self.push_r1()
                self.emit('                ld.32   r1, [sp][r0+4]')
                mnem = 'shl' if op == 'SHL' else 'shr'
                self.emit(f'                {mnem}.32 r1, [sp]')
                self.emit('                add.32  sp, #8')
                self.temp_depth -= 2
                # Re-balance: we popped left manually above (sp-=8 not -4).
                # The outer balancing will not run for this branch; account
                # for the original `push_r1()` of left.
                continue

    def gen_unary(self):
        k = self.peek()[0]
        if k == '-':
            self.advance()
            self.gen_unary()
            self.push_r1()
            self.emit('                ld.32   r1, #0')
            self.emit('                sub.32  r1, [sp]')
            self.emit('                add.32  sp, #4')
            self.temp_depth -= 1
            return
        if k == '+':
            self.advance()
            self.gen_unary()
            return
        if k == 'NOT':
            self.advance()
            self.gen_unary()
            self.emit('                xor.32  r1, #-1')
            return
        self.gen_primary()

    def gen_primary(self):
        t = self.peek()
        k = t[0]
        if k == 'NUM':
            self.advance()
            self.load_imm(1, t[1])
            return
        if k == 'TRUE':
            self.advance()
            self.emit('                ld.32   r1, #1')
            return
        if k == 'FALSE':
            self.advance()
            self.emit('                ld.32   r1, #0')
            return
        if k == '(':
            self.advance()
            self.gen_expr()
            self.expect(')')
            return
        if k in ('PEEK', 'SAR', 'I2CREAD'):
            name = self.advance()[1]
            args = []
            self.expect('(')
            if self.peek()[0] != ')':
                args.append(self.collect_arg())
                while self.match(','):
                    args.append(self.collect_arg())
            self.expect(')')
            self.gen_call(name, args)
            return
        if k == 'IDENT':
            name = self.advance()[1]
            # Function call?
            if self.peek()[0] == '(' or name.upper() in self.routines:
                args = []
                if self.match('('):
                    if self.peek()[0] != ')':
                        args.append(self.collect_arg())
                        while self.match(','):
                            args.append(self.collect_arg())
                    self.expect(')')
                self.gen_call(name, args)
                return
            self.var_addr_load(name)
            return
        self.syntax(f"expected expression, got {k}")


# ---------- driver ----------

PROLOGUE = r"""
__putc:
                ld.32   r1, [sp][r0+4]
                call    putchar
                ret

__print_str:
                sub.32  sp, #4
                st.32   [sp], r6
                sub.32  sp, #4
                st.32   [sp], r5
                ld.32   r5, [sp][r0+12]
.loop:          ld.8    r1, [r5++]
                beq.8   r1, #0, .done
                call    __putc
                jmp     .loop
.done:          ld.32   r5, [r0][sp+=4]
                ld.32   r6, [r0][sp+=4]
                ret

__sar:
                ld.32   r1, [sp][r0+8]
                ld.32   r2, [sp][r0+4]
                ld.32   r3, #0
                bge.32  r1, r3, .pos
                xor.32  r1, #-1
.nloop:         beq.32  r2, #0, .ndone
                shr.32  r1, #1
                sub.32  r2, #1
                jmp     .nloop
.ndone:         xor.32  r1, #-1
                ret
.pos:           beq.32  r2, #0, .pdone
                shr.32  r1, #1
                sub.32  r2, #1
                jmp     .pos
.pdone:         ret
"""


def main():
    args = sys.argv[1:]
    save_asm = False
    if '-S' in args:
        save_asm = True
        args.remove('-S')
    if len(args) < 1:
        print(f"Usage: {sys.argv[0]} [-S] <input.pas>", file=sys.stderr)
        sys.exit(1)
    inp = args[0]
    if '.' not in os.path.basename(inp):
        inp += '.pas'
    try:
        with open(inp) as f:
            src = f.read()
    except FileNotFoundError:
        print(f"error: input file not found: {inp}", file=sys.stderr)
        sys.exit(1)

    c = Compiler()
    body_asm = c.compile(src)

    asm = body_asm + PROLOGUE

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
