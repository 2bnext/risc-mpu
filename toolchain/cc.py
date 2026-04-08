#!/usr/bin/env python3
"""
Subset C compiler targeting the MPU ISA.

Supported:
  - Types: int (32-bit), char (8-bit), pointers
  - Operators: + - * & | ^ << >> == != < > <= >= && || !
  - Statements: if/else, while, for, return, variable declarations, assignments
  - Functions with arguments and local variables
  - String literals, character literals
  - Global variables
  - Pointer dereference and address-of
  - Array subscript

Register usage:
  r0  = always zero
  r1  = primary accumulator (expression result)
  r2  = secondary (right-hand operand)
  r3-r5 = temporaries (pushed when needed)
  r6  = frame pointer
  sp  = stack pointer (SP)

Calling convention:
  - Arguments pushed right-to-left onto the stack
  - Return value in r1
  - Caller saves r1-r5, callee saves r6
  - Frame: [old r6][arg0][arg1]...  locals grow downward from r6
"""

import sys
import os
import re

# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

TOKEN_SPEC = [
    ('COMMENT_LINE', r'//[^\n]*'),
    ('COMMENT_BLOCK', r'/\*[\s\S]*?\*/'),
    ('STRING',   r'"([^"\\]|\\.)*"'),
    ('CHAR_LIT', r"'([^'\\]|\\.)'"),
    ('HEX',      r'0[xX][0-9a-fA-F]+'),
    ('NUMBER',   r'[0-9]+'),
    ('IDENT',    r'[a-zA-Z_][a-zA-Z0-9_]*'),
    ('LSHIFT',   r'<<'),
    ('RSHIFT',   r'>>'),
    ('AND',      r'&&'),
    ('OR',       r'\|\|'),
    ('EQ',       r'=='),
    ('NE',       r'!='),
    ('LE',       r'<='),
    ('GE',       r'>='),
    ('LT',       r'<'),
    ('GT',       r'>'),
    ('PLUSPLUS', r'\+\+'),
    ('MINUSMINUS', r'--'),
    ('PLUS',     r'\+'),
    ('MINUS',    r'-'),
    ('STAR',     r'\*'),
    ('SLASH',    r'/'),
    ('PERCENT',  r'%'),
    ('AMP',      r'&'),
    ('PIPE',     r'\|'),
    ('CARET',    r'\^'),
    ('BANG',     r'!'),
    ('TILDE',    r'~'),
    ('ASSIGN',   r'='),
    ('SEMI',     r';'),
    ('COMMA',    r','),
    ('LPAREN',   r'\('),
    ('RPAREN',   r'\)'),
    ('LBRACE',   r'\{'),
    ('RBRACE',   r'\}'),
    ('LBRACKET', r'\['),
    ('RBRACKET', r'\]'),
    ('WS',       r'\s+'),
]

TOKEN_RE = re.compile('|'.join(f'(?P<{name}>{pat})' for name, pat in TOKEN_SPEC))

KEYWORDS = {'int', 'char', 'void', 'if', 'else', 'while', 'for', 'return',
            'break', 'continue'}


class Token:
    def __init__(self, kind, value, line):
        self.kind = kind
        self.value = value
        self.line = line

    def __repr__(self):
        return f'Token({self.kind}, {self.value!r})'


def tokenize(source):
    tokens = []
    for line_no, line_text in enumerate(source.split('\n'), 1):
        pass  # line tracking handled by pos
    line = 1
    for m in TOKEN_RE.finditer(source):
        kind = m.lastgroup
        value = m.group()
        line += value.count('\n')
        if kind in ('WS', 'COMMENT_LINE', 'COMMENT_BLOCK'):
            continue
        if kind == 'IDENT' and value in KEYWORDS:
            kind = value.upper()  # INT, CHAR, VOID, IF, ELSE, WHILE, FOR, RETURN
        tokens.append(Token(kind, value, line))
    tokens.append(Token('EOF', '', line))
    return tokens


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------

class Program:
    def __init__(self, decls):
        self.decls = decls

class FuncDecl:
    def __init__(self, ret_type, name, params, body):
        self.ret_type = ret_type
        self.name = name
        self.params = params  # list of (type, name)
        self.body = body

class GlobalVar:
    def __init__(self, var_type, name, init_val=None):
        self.var_type = var_type
        self.name = name
        self.init_val = init_val

class Block:
    def __init__(self, stmts):
        self.stmts = stmts

class VarDecl:
    def __init__(self, var_type, name, init_expr=None):
        self.var_type = var_type
        self.name = name
        self.init_expr = init_expr

class IfStmt:
    def __init__(self, cond, then_body, else_body=None):
        self.cond = cond
        self.then_body = then_body
        self.else_body = else_body

class WhileStmt:
    def __init__(self, cond, body):
        self.cond = cond
        self.body = body

class ForStmt:
    def __init__(self, init, cond, update, body):
        self.init = init
        self.cond = cond
        self.update = update
        self.body = body

class ReturnStmt:
    def __init__(self, expr=None):
        self.expr = expr

class BreakStmt:
    pass

class ContinueStmt:
    pass

class ExprStmt:
    def __init__(self, expr):
        self.expr = expr

class BinOp:
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

class UnaryOp:
    def __init__(self, op, expr):
        self.op = op
        self.expr = expr

class NumLit:
    def __init__(self, value):
        self.value = value

class StrLit:
    def __init__(self, value):
        self.value = value  # raw string bytes

class CharLit:
    def __init__(self, value):
        self.value = value  # integer

class Ident:
    def __init__(self, name):
        self.name = name

class FuncCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args

class Assign:
    def __init__(self, target, expr):
        self.target = target
        self.expr = expr

class Deref:
    def __init__(self, expr):
        self.expr = expr

class AddrOf:
    def __init__(self, expr):
        self.expr = expr

class ArrayAccess:
    def __init__(self, array, index):
        self.array = array
        self.index = index


# ---------------------------------------------------------------------------
# Parser (recursive descent)
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.advance()
        if t.kind != kind:
            raise SyntaxError(f"Line {t.line}: expected {kind}, got {t.kind} ({t.value!r})")
        return t

    def match(self, kind):
        if self.peek().kind == kind:
            return self.advance()
        return None

    def parse(self):
        decls = []
        while self.peek().kind != 'EOF':
            decls.append(self.parse_top_level())
        return Program(decls)

    def parse_type(self):
        """Parse a type: int, char, void, with optional pointer stars."""
        t = self.advance()
        if t.kind not in ('INT', 'CHAR', 'VOID'):
            raise SyntaxError(f"Line {t.line}: expected type, got {t.value!r}")
        type_name = t.value
        while self.peek().kind == 'STAR':
            self.advance()
            type_name += '*'
        return type_name

    def parse_top_level(self):
        type_name = self.parse_type()
        name = self.expect('IDENT').value
        if self.peek().kind == 'LPAREN':
            return self.parse_func(type_name, name)
        # Global variable
        init_val = None
        if self.match('ASSIGN'):
            init_val = self.parse_expr()
        self.expect('SEMI')
        return GlobalVar(type_name, name, init_val)

    def parse_func(self, ret_type, name):
        self.expect('LPAREN')
        params = []
        if self.peek().kind != 'RPAREN':
            params.append(self.parse_param())
            while self.match('COMMA'):
                params.append(self.parse_param())
        self.expect('RPAREN')
        body = self.parse_block()
        return FuncDecl(ret_type, name, params, body)

    def parse_param(self):
        type_name = self.parse_type()
        name = self.expect('IDENT').value
        return (type_name, name)

    def parse_block(self):
        self.expect('LBRACE')
        stmts = []
        while self.peek().kind != 'RBRACE':
            stmts.append(self.parse_stmt())
        self.expect('RBRACE')
        return Block(stmts)

    def parse_stmt(self):
        pk = self.peek()

        if pk.kind in ('INT', 'CHAR', 'VOID'):
            return self.parse_local_decl()
        if pk.kind == 'IF':
            return self.parse_if()
        if pk.kind == 'WHILE':
            return self.parse_while()
        if pk.kind == 'FOR':
            return self.parse_for()
        if pk.kind == 'RETURN':
            return self.parse_return()
        if pk.kind == 'BREAK':
            self.advance()
            self.expect('SEMI')
            return BreakStmt()
        if pk.kind == 'CONTINUE':
            self.advance()
            self.expect('SEMI')
            return ContinueStmt()
        if pk.kind == 'LBRACE':
            return self.parse_block()

        expr = self.parse_expr()
        self.expect('SEMI')
        return ExprStmt(expr)

    def parse_local_decl(self):
        type_name = self.parse_type()
        decls = []
        while True:
            name = self.expect('IDENT').value
            init_expr = None
            if self.match('ASSIGN'):
                init_expr = self.parse_expr()
            decls.append(VarDecl(type_name, name, init_expr))
            if not self.match('COMMA'):
                break
        self.expect('SEMI')
        return decls[0] if len(decls) == 1 else Block(decls)

    def parse_if(self):
        self.expect('IF')
        self.expect('LPAREN')
        cond = self.parse_expr()
        self.expect('RPAREN')
        then_body = self.parse_stmt()
        else_body = None
        if self.match('ELSE'):
            else_body = self.parse_stmt()
        return IfStmt(cond, then_body, else_body)

    def parse_while(self):
        self.expect('WHILE')
        self.expect('LPAREN')
        cond = self.parse_expr()
        self.expect('RPAREN')
        body = self.parse_stmt()
        return WhileStmt(cond, body)

    def parse_for(self):
        self.expect('FOR')
        self.expect('LPAREN')
        # init
        if self.peek().kind in ('INT', 'CHAR'):
            init = self.parse_local_decl()
        elif self.peek().kind != 'SEMI':
            init = ExprStmt(self.parse_expr())
            self.expect('SEMI')
        else:
            init = None
            self.expect('SEMI')
        # cond
        cond = None if self.peek().kind == 'SEMI' else self.parse_expr()
        self.expect('SEMI')
        # update
        update = None if self.peek().kind == 'RPAREN' else self.parse_expr()
        self.expect('RPAREN')
        body = self.parse_stmt()
        return ForStmt(init, cond, update, body)

    def parse_return(self):
        self.expect('RETURN')
        expr = None
        if self.peek().kind != 'SEMI':
            expr = self.parse_expr()
        self.expect('SEMI')
        return ReturnStmt(expr)

    # ---- Expression parsing (precedence climbing) ----

    def parse_expr(self):
        return self.parse_assign_expr()

    def parse_assign_expr(self):
        left = self.parse_or_expr()
        if self.peek().kind == 'ASSIGN':
            self.advance()
            right = self.parse_assign_expr()
            return Assign(left, right)
        return left

    def parse_or_expr(self):
        left = self.parse_and_expr()
        while self.peek().kind == 'OR':
            self.advance()
            right = self.parse_and_expr()
            left = BinOp('||', left, right)
        return left

    def parse_and_expr(self):
        left = self.parse_bitor_expr()
        while self.peek().kind == 'AND':
            self.advance()
            right = self.parse_bitor_expr()
            left = BinOp('&&', left, right)
        return left

    def parse_bitor_expr(self):
        left = self.parse_bitxor_expr()
        while self.peek().kind == 'PIPE':
            self.advance()
            right = self.parse_bitxor_expr()
            left = BinOp('|', left, right)
        return left

    def parse_bitxor_expr(self):
        left = self.parse_bitand_expr()
        while self.peek().kind == 'CARET':
            self.advance()
            right = self.parse_bitand_expr()
            left = BinOp('^', left, right)
        return left

    def parse_bitand_expr(self):
        left = self.parse_eq_expr()
        while self.peek().kind == 'AMP':
            self.advance()
            right = self.parse_eq_expr()
            left = BinOp('&', left, right)
        return left

    def parse_eq_expr(self):
        left = self.parse_rel_expr()
        while self.peek().kind in ('EQ', 'NE'):
            op = '==' if self.peek().kind == 'EQ' else '!='
            self.advance()
            right = self.parse_rel_expr()
            left = BinOp(op, left, right)
        return left

    def parse_rel_expr(self):
        left = self.parse_shift_expr()
        while self.peek().kind in ('LT', 'GT', 'LE', 'GE'):
            op_map = {'LT': '<', 'GT': '>', 'LE': '<=', 'GE': '>='}
            op = op_map[self.peek().kind]
            self.advance()
            right = self.parse_shift_expr()
            left = BinOp(op, left, right)
        return left

    def parse_shift_expr(self):
        left = self.parse_add_expr()
        while self.peek().kind in ('LSHIFT', 'RSHIFT'):
            op = '<<' if self.peek().kind == 'LSHIFT' else '>>'
            self.advance()
            right = self.parse_add_expr()
            left = BinOp(op, left, right)
        return left

    def parse_add_expr(self):
        left = self.parse_mul_expr()
        while self.peek().kind in ('PLUS', 'MINUS'):
            op = '+' if self.peek().kind == 'PLUS' else '-'
            self.advance()
            right = self.parse_mul_expr()
            left = BinOp(op, left, right)
        return left

    def parse_mul_expr(self):
        # No hardware multiply, but *, /, and % all lower to runtime helpers.
        left = self.parse_unary()
        while self.peek().kind in ('STAR', 'SLASH', 'PERCENT'):
            kind = self.peek().kind
            helper = {'STAR': '__mul', 'SLASH': '__div', 'PERCENT': '__mod'}[kind]
            self.advance()
            right = self.parse_unary()
            left = FuncCall(helper, [left, right])
        return left

    def parse_unary(self):
        pk = self.peek()
        if pk.kind == 'MINUS':
            self.advance()
            expr = self.parse_unary()
            # -x => 0 - x
            return BinOp('-', NumLit(0), expr)
        if pk.kind == 'BANG':
            self.advance()
            expr = self.parse_unary()
            return UnaryOp('!', expr)
        if pk.kind == 'TILDE':
            # ~x  ==>  x ^ -1   (bitwise NOT via XOR with all-ones)
            self.advance()
            expr = self.parse_unary()
            return BinOp('^', expr, NumLit(-1))
        if pk.kind == 'STAR':
            self.advance()
            expr = self.parse_unary()
            return Deref(expr)
        if pk.kind == 'AMP':
            self.advance()
            expr = self.parse_unary()
            return AddrOf(expr)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_primary()
        while True:
            if self.peek().kind in ('PLUSPLUS', 'MINUSMINUS'):
                op = '+' if self.peek().kind == 'PLUSPLUS' else '-'
                self.advance()
                # Desugar x++ to (x = x + 1). Value semantics match pre-inc,
                # which is fine for for-loop updates and standalone stmts.
                expr = Assign(expr, BinOp(op, expr, NumLit(1)))
                continue
            if self.peek().kind == 'LBRACKET':
                self.advance()
                index = self.parse_expr()
                self.expect('RBRACKET')
                expr = ArrayAccess(expr, index)
            elif self.peek().kind == 'LPAREN' and isinstance(expr, Ident):
                self.advance()
                args = []
                if self.peek().kind != 'RPAREN':
                    args.append(self.parse_expr())
                    while self.match('COMMA'):
                        args.append(self.parse_expr())
                self.expect('RPAREN')
                expr = FuncCall(expr.name, args)
            else:
                break
        return expr

    def parse_primary(self):
        pk = self.peek()
        if pk.kind == 'NUMBER':
            self.advance()
            return NumLit(int(pk.value))
        if pk.kind == 'HEX':
            self.advance()
            return NumLit(int(pk.value, 16))
        if pk.kind == 'CHAR_LIT':
            self.advance()
            ch = pk.value[1:-1]  # strip quotes
            if ch.startswith('\\'):
                ch = {'n': '\n', 'r': '\r', 't': '\t', '0': '\0', '\\': '\\',
                       "'": "'"}[ch[1]]
            return CharLit(ord(ch))
        if pk.kind == 'STRING':
            self.advance()
            s = pk.value[1:-1]  # strip quotes
            # Process escapes
            result = bytearray()
            i = 0
            while i < len(s):
                if s[i] == '\\' and i + 1 < len(s):
                    esc = {'n': 0x0A, 'r': 0x0D, 't': 0x09, '0': 0x00,
                           '\\': 0x5C, '"': 0x22}
                    result.append(esc.get(s[i+1], ord(s[i+1])))
                    i += 2
                else:
                    result.append(ord(s[i]))
                    i += 1
            return StrLit(bytes(result))
        if pk.kind == 'IDENT':
            self.advance()
            return Ident(pk.value)
        if pk.kind == 'LPAREN':
            self.advance()
            expr = self.parse_expr()
            self.expect('RPAREN')
            return expr
        raise SyntaxError(f"Line {pk.line}: unexpected token {pk.value!r}")


# ---------------------------------------------------------------------------
# Code generator
# ---------------------------------------------------------------------------

# Standard library functions — don't generate code for these, they're in stdlib.asm
STDLIB_FUNCS = {'putchar', 'puts', 'sleep', 'setleds', 'printf',
                'gpio_set_dir', 'gpio_write', 'gpio_read',
                'i2c_start', 'i2c_stop', 'i2c_write', 'i2c_read',
                'adc_read'}


class CodeGen:
    def __init__(self, stdlib_path=None):
        self.output = []
        self.strings = []       # (label, bytes)
        self.stdlib_path = stdlib_path
        self.globals = {}       # name -> (type, label)
        self.label_count = 0
        self.func_name = ''
        self.locals = {}        # name -> (type, offset from r6)
        self.param_count = 0
        self.local_offset = 0   # current stack frame size for locals
        self.loop_stack = []    # stack of (continue_label, break_label)

    def new_label(self, hint='L'):
        # Most internal labels are local to a function (if/while/cmp/...).
        # Prefix them with '.' so the assembler scopes them — otherwise an
        # internal label like __endif_2 would clobber the local-label scope
        # and break later .epilogue references in the same function. String
        # literal labels live in the data section and must stay global.
        self.label_count += 1
        prefix = '' if hint == 'str' else '.'
        return f'{prefix}__{hint}_{self.label_count}'

    def emit(self, line):
        self.output.append(line)

    def comment(self, text):
        self.emit(f'                ; {text}')

    def generate(self, program):
        self.emit('                jmp     __start')
        self.emit('')

        # Collect globals and strings first
        for decl in program.decls:
            if isinstance(decl, GlobalVar):
                self.globals[decl.name] = (decl.var_type, f'_g_{decl.name}')

        # Generate functions (skip stdlib — they come from stdlib.asm)
        for decl in program.decls:
            if isinstance(decl, FuncDecl) and decl.name not in STDLIB_FUNCS:
                self.gen_func(decl)

        # Entry point
        self.emit('__start:')
        self.emit('                call    main')
        self.emit('.__halt:        jmp     .__halt')
        self.emit('')

        # String literals
        for label, data in self.strings:
            escaped = data + b'\x00'
            hex_bytes = ', '.join(f'0x{b:02X}' for b in escaped)
            self.emit(f'{label}: db {hex_bytes}')

        # Global variables
        for name, (vtype, label) in self.globals.items():
            self.emit(f'{label}: db 0x00, 0x00, 0x00, 0x00')

        # Append standard library
        if self.stdlib_path:
            self.emit('')
            self.emit('; ---- Standard Library ----')
            with open(self.stdlib_path) as f:
                for line in f:
                    self.emit(line.rstrip())

        self.emit('')
        self.emit('                end')

        return '\n'.join(self.output)

    def type_size(self, t):
        if t == 'char':
            return 1
        return 4  # int, pointers

    def size_suffix(self, t):
        if t == 'char':
            return '.8'
        return '.32'

    def gen_func(self, func):
        self.func_name = func.name
        self.locals = {}
        self.stack_depth = 0

        # Count locals for stack frame
        local_size = self.count_locals(func.body) * 4
        self.frame_size = local_size

        self.emit(f'{func.name}:')
        # Prologue: save r6 (pre-decrement push)
        self.emit('                sub.32  sp, #4')
        self.emit('                st.32   [sp], r6')
        if local_size > 0:
            self.emit(f'                sub.32  sp, #{local_size}')

        # Stack layout after prologue:
        #   sp+0 .. sp+local_size-4   = local variables
        #   sp+local_size              = saved r6
        #   sp+local_size+4            = return address (pushed by call)
        #   sp+local_size+8            = arg0
        #   sp+local_size+12           = arg1, etc.

        # Map params
        for i, (ptype, pname) in enumerate(func.params):
            self.locals[pname] = (ptype, local_size + 8 + i * 4)

        # Map locals
        self.local_idx = 0
        self.alloc_locals(func.body)

        # Generate body
        self.gen_stmt(func.body)

        # Epilogue
        self.emit(f'.epilogue:')
        if local_size > 0:
            self.emit(f'                add.32  sp, #{local_size}')
        self.emit('                ld.32   r6, [sp+=4]')
        self.emit('                ret')
        self.emit('')

    def count_locals(self, node):
        count = 0
        if isinstance(node, Block):
            for s in node.stmts:
                count += self.count_locals(s)
        elif isinstance(node, VarDecl):
            count += 1
        elif isinstance(node, IfStmt):
            count += self.count_locals(node.then_body)
            if node.else_body:
                count += self.count_locals(node.else_body)
        elif isinstance(node, WhileStmt):
            count += self.count_locals(node.body)
        elif isinstance(node, ForStmt):
            if isinstance(node.init, VarDecl):
                count += 1
            count += self.count_locals(node.body)
        return count

    def alloc_locals(self, node):
        if isinstance(node, Block):
            for s in node.stmts:
                self.alloc_locals(s)
        elif isinstance(node, VarDecl):
            self.locals[node.name] = (node.var_type, self.local_idx * 4)
            self.local_idx += 1
        elif isinstance(node, IfStmt):
            self.alloc_locals(node.then_body)
            if node.else_body:
                self.alloc_locals(node.else_body)
        elif isinstance(node, WhileStmt):
            self.alloc_locals(node.body)
        elif isinstance(node, ForStmt):
            if isinstance(node.init, VarDecl):
                self.alloc_locals(node.init)
            self.alloc_locals(node.body)

    def var_offset(self, name):
        """Get the stack offset for a variable, adjusted for current push depth."""
        _, base_off = self.locals[name]
        return base_off + self.stack_depth * 4

    def push(self, reg):
        self.emit(f'                sub.32  sp, #4')
        self.emit(f'                st.32   [sp], r{reg}')
        self.stack_depth += 1

    def pop(self, reg):
        self.emit(f'                ld.32   r{reg}, [r0][sp+=4]')
        self.stack_depth -= 1

    def gen_stmt(self, node):
        if isinstance(node, Block):
            for s in node.stmts:
                self.gen_stmt(s)
        elif isinstance(node, VarDecl):
            if node.init_expr:
                self.gen_expr(node.init_expr, 1)
                off = self.var_offset(node.name)
                sz = self.size_suffix(node.var_type)
                self.emit(f'                st{sz}   [sp+{off}], r1')
                # Can't use [sp+off] syntax. Use add to compute address.
                # Actually our AGU supports [Rbase][Ridx+offset] mode.
                # st.32 [sp][r0+offset], r1 — but we need base=sp, idx=r0.
                # Rewrite:
                self.output[-1] = f'                st{sz}   [sp][r0+{off}], r1'
        elif isinstance(node, ExprStmt):
            self.gen_expr(node.expr, 1)
        elif isinstance(node, ReturnStmt):
            if node.expr:
                self.gen_expr(node.expr, 1)
            self.emit(f'                jmp     .epilogue')
        elif isinstance(node, IfStmt):
            else_label = self.new_label('else')
            end_label = self.new_label('endif')
            self.gen_expr(node.cond, 1)
            if node.else_body:
                self.emit(f'                beq.32  r1, #0, {else_label}')
                self.gen_stmt(node.then_body)
                self.emit(f'                jmp     {end_label}')
                self.emit(f'{else_label}:')
                self.gen_stmt(node.else_body)
            else:
                self.emit(f'                beq.32  r1, #0, {end_label}')
                self.gen_stmt(node.then_body)
            self.emit(f'{end_label}:')
        elif isinstance(node, WhileStmt):
            top_label = self.new_label('while')
            end_label = self.new_label('endwhile')
            self.emit(f'{top_label}:')
            self.gen_expr(node.cond, 1)
            self.emit(f'                beq.32  r1, #0, {end_label}')
            self.loop_stack.append((top_label, end_label))
            self.gen_stmt(node.body)
            self.loop_stack.pop()
            self.emit(f'                jmp     {top_label}')
            self.emit(f'{end_label}:')
        elif isinstance(node, ForStmt):
            top_label = self.new_label('for')
            cont_label = self.new_label('forcont')
            end_label = self.new_label('endfor')
            if node.init:
                self.gen_stmt(node.init)
            self.emit(f'{top_label}:')
            if node.cond:
                self.gen_expr(node.cond, 1)
                self.emit(f'                beq.32  r1, #0, {end_label}')
            self.loop_stack.append((cont_label, end_label))
            self.gen_stmt(node.body)
            self.loop_stack.pop()
            self.emit(f'{cont_label}:')
            if node.update:
                self.gen_expr(node.update, 1)
            self.emit(f'                jmp     {top_label}')
            self.emit(f'{end_label}:')
        elif isinstance(node, BreakStmt):
            self.emit(f'                jmp     {self.loop_stack[-1][1]}')
        elif isinstance(node, ContinueStmt):
            self.emit(f'                jmp     {self.loop_stack[-1][0]}')

    def gen_expr(self, node, dest):
        """Generate code for expression, result in r{dest}."""
        if isinstance(node, NumLit):
            val = node.value
            if -0x80000 <= val <= 0x7FFFF:
                self.emit(f'                ld.32   r{dest}, #{val}')
            else:
                # Need ld + ldh for large values
                low = val & 0xFFFFF
                high = (val >> 12) & 0xFFFFF
                self.emit(f'                ld.32   r{dest}, #{low}')
                self.emit(f'                ldh     r{dest}, #{high}')

        elif isinstance(node, CharLit):
            self.emit(f'                ld.32   r{dest}, #{node.value}')

        elif isinstance(node, StrLit):
            label = self.new_label('str')
            self.strings.append((label, node.value))
            self.emit(f'                ld.32   r{dest}, #{label}')

        elif isinstance(node, Ident):
            if node.name in self.locals:
                off = self.var_offset(node.name)
                vtype, _ = self.locals[node.name]
                sz = self.size_suffix(vtype)
                self.emit(f'                ld{sz}   r{dest}, [sp][r0+{off}]')
            elif node.name in self.globals:
                vtype, label = self.globals[node.name]
                sz = self.size_suffix(vtype)
                self.emit(f'                ld{sz}   r{dest}, {label}')
            else:
                raise ValueError(f"Undefined variable: {node.name}")

        elif isinstance(node, Assign):
            self.gen_expr(node.expr, dest)
            if isinstance(node.target, Ident):
                if node.target.name in self.locals:
                    off = self.var_offset(node.target.name)
                    vtype, _ = self.locals[node.target.name]
                    sz = self.size_suffix(vtype)
                    self.emit(f'                st{sz}   [sp][r0+{off}], r{dest}')
                elif node.target.name in self.globals:
                    vtype, label = self.globals[node.target.name]
                    sz = self.size_suffix(vtype)
                    self.emit(f'                st{sz}   {label}, r{dest}')
            elif isinstance(node.target, Deref):
                # *ptr = val: compute ptr into r2, val already in r{dest}
                self.push(dest)
                self.gen_expr(node.target.expr, 2)
                self.pop(dest)
                self.emit(f'                st.32   [r2], r{dest}')
            elif isinstance(node.target, ArrayAccess):
                self.push(dest)
                self.gen_expr(node.target.array, 2)
                self.push(2)
                self.gen_expr(node.target.index, 3)
                self.pop(2)
                self.pop(dest)
                # addr = r2 + r3
                self.emit(f'                st.8    [r2][r3], r{dest}')

        elif isinstance(node, BinOp):
            op = node.op
            # Short-circuit for && and ||
            if op == '&&':
                end_label = self.new_label('and')
                self.gen_expr(node.left, dest)
                self.emit(f'                beq.32  r{dest}, #0, {end_label}')
                self.gen_expr(node.right, dest)
                self.emit(f'{end_label}:')
                return
            if op == '||':
                end_label = self.new_label('or')
                self.gen_expr(node.left, dest)
                self.emit(f'                bne.32  r{dest}, #0, {end_label}')
                self.gen_expr(node.right, dest)
                self.emit(f'{end_label}:')
                return

            # Optimize: if right side is a small immediate AND op has an
            # immediate form, fold into a single ALU-with-imm instruction.
            IMM_OP_MAP = {'+': 'add', '-': 'sub', '&': 'and', '|': 'or',
                          '^': 'xor', '<<': 'shl', '>>': 'shr'}
            if (op in IMM_OP_MAP
                    and isinstance(node.right, NumLit)
                    and -0x80000 <= node.right.value <= 0x7FFFF):
                self.gen_expr(node.left, dest)
                self.emit(f'                {IMM_OP_MAP[op]}.32 r{dest}, #{node.right.value}')
                return

            # Comparison ops
            CMP_OPS = {'==': 'beq', '!=': 'bne', '<': 'blt', '>': 'bgt',
                       '<=': 'ble', '>=': 'bge'}
            if op in CMP_OPS:
                # Evaluate both sides into registers, then use the branch
                # instruction's built-in reg-reg compare.
                true_label = self.new_label('cmp_t')
                other = 2 if dest != 2 else 3
                self.gen_expr(node.left, dest)
                self.push(dest)
                self.gen_expr(node.right, other)
                self.pop(dest)
                branch = CMP_OPS[op]
                self.emit(f'                ld.32   r5, #1')
                self.emit(f'                {branch}.32 r{dest}, r{other}, {true_label}')
                self.emit(f'                ld.32   r5, #0')
                self.emit(f'{true_label}:')
                if dest != 5:
                    self.push(5)
                    self.pop(dest)
                return

            # General binary: left in dest, right in other reg, combine
            self.gen_expr(node.left, dest)
            other = 2 if dest != 2 else 3
            self.push(dest)
            self.gen_expr(node.right, other)
            self.pop(dest)

            # For reg-reg ALU ops, we need to go through memory.
            # Push right operand, then use stack-relative addressing.
            OP_MAP = {'+': 'add', '-': 'sub', '&': 'and', '|': 'or',
                      '^': 'xor', '<<': 'shl', '>>': 'shr'}
            if op in OP_MAP:
                self.push(other)
                self.emit(f'                {OP_MAP[op]}.32 r{dest}, [sp]')
                # Pop without loading (just adjust SP)
                self.emit(f'                add.32  sp, #4')
                self.stack_depth -= 1
            else:
                raise ValueError(f"Unsupported operator: {op}")

        elif isinstance(node, UnaryOp):
            if node.op == '!':
                end_label = self.new_label('not')
                self.gen_expr(node.expr, dest)
                self.emit(f'                ld.32   r5, #1')
                self.emit(f'                beq.32  r{dest}, #0, {end_label}')
                self.emit(f'                ld.32   r5, #0')
                self.emit(f'{end_label}:')
                if dest != 5:
                    self.push(5)
                    self.pop(dest)

        elif isinstance(node, Deref):
            self.gen_expr(node.expr, dest)
            self.emit(f'                ld.32   r{dest}, [r{dest}]')

        elif isinstance(node, AddrOf):
            if isinstance(node.expr, Ident):
                if node.expr.name in self.locals:
                    off = self.var_offset(node.expr.name)
                    self.emit(f'                ld.32   r{dest}, #0')
                    self.emit(f'                add.32  r{dest}, [r0][sp]')
                    # That loads mem[sp], not sp itself. Need sp's value.
                    # Use: push sp, load from stack... same problem.
                    # Workaround: compute sp + offset via immediate add
                    self.output.pop()
                    self.output.pop()
                    # We'll store sp to a temp stack slot and load it
                    self.push(7)  # this changes sp!
                    self.emit(f'                ld.32   r{dest}, [sp]')  # load old sp
                    # Actually: push stores old sp at [old_sp - 4], then sp = old_sp - 4
                    # [sp] = old_sp - 4... no. We stored sp (the pre-decrement value) at the
                    # effective address. Wait, let's check:
                    # st [r0][sp+=-4], sp: eff_addr = r0+sp = sp. Stores sp at [sp].
                    # Then sp = sp - 4. So [old_sp] has old_sp value. [sp+4] has old_sp.
                    self.emit(f'                ld.32   r{dest}, [sp][r0+4]')
                    self.output[-2] = f'                ; addr-of via stack'
                    self.emit(f'                add.32  r{dest}, #{off + 4}')  # +4 for the push
                    # Restore sp
                    self.emit(f'                add.32  sp, #4')
                    self.stack_depth -= 1
                elif node.expr.name in self.globals:
                    _, label = self.globals[node.expr.name]
                    self.emit(f'                ld.32   r{dest}, #{label}')

        elif isinstance(node, ArrayAccess):
            self.gen_expr(node.array, dest)
            other = 2 if dest != 2 else 3
            self.push(dest)
            self.gen_expr(node.index, other)
            self.pop(dest)
            self.emit(f'                ; array access — push index, load via [base][idx]')
            self.push(other)
            self.emit(f'                ld.8    r{dest}, [r{dest}][r{other}]')
            self.emit(f'                add.32  sp, #4')
            self.stack_depth -= 1

        elif isinstance(node, FuncCall):
            # Push arguments right-to-left
            for arg in reversed(node.args):
                self.gen_expr(arg, 1)
                self.push(1)
            self.emit(f'                call    {node.name}')
            # Clean up args
            arg_size = len(node.args) * 4
            if arg_size > 0:
                self.emit(f'                add.32  sp, #{arg_size}')
                self.stack_depth -= len(node.args)
            # Result is in r1
            if dest != 1:
                self.push(1)
                self.pop(dest)


def main():
    args = sys.argv[1:]
    save_asm = False
    if '-S' in args:
        save_asm = True
        args.remove('-S')
    if len(args) < 1:
        print(f"Usage: {sys.argv[0]} [-S] <input.c>", file=sys.stderr)
        sys.exit(1)

    input_file = args[0]
    if '.' not in os.path.basename(input_file):
        input_file += '.c'

    try:
        with open(input_file) as f:
            source = f.read()
    except FileNotFoundError:
        print(f"error: input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    # Find stdlib.asm next to this script
    stdlib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stdlib.asm')
    if not os.path.exists(stdlib_path):
        stdlib_path = None

    tokens = tokenize(source)
    parser = Parser(tokens)
    ast = parser.parse()
    codegen = CodeGen(stdlib_path=stdlib_path)
    asm = codegen.generate(ast)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import asm as _asm
    asm = _asm.to_pseudo_ops(asm)
    asm = _asm.hide_r0(asm)

    if save_asm:
        s_file = input_file.rsplit('.', 1)[0] + '.s'
        with open(s_file, 'w') as f:
            f.write(asm)
            f.write('\n')
        print(f"Wrote {s_file}")

    binary = _asm.assemble(asm + '\n')
    mpu_file = input_file.rsplit('.', 1)[0] + '.mpu'
    with open(mpu_file, 'wb') as f:
        f.write(binary)
    print(f"Compiled {input_file} -> {mpu_file} ({len(binary)} bytes)")


if __name__ == '__main__':
    main()
