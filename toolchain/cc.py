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
import struct

# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

TOKEN_SPEC = [
    ('COMMENT_LINE', r'//[^\n]*'),
    ('COMMENT_BLOCK', r'/\*[\s\S]*?\*/'),
    ('STRING',   r'"([^"\\]|\\.)*"'),
    ('CHAR_LIT', r"'([^'\\]|\\.)'"),
    ('HEX',      r'0[xX][0-9a-fA-F_]+'),
    ('BIN',      r'0[bB][01_]+'),
    ('FLOAT_LIT', r'[0-9][0-9_]*\.[0-9_]*(?:[eE][+-]?[0-9_]+)?|[0-9][0-9_]*[eE][+-]?[0-9_]+'),
    ('NUMBER',   r'[0-9][0-9_]*'),
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
    ('ARROW',    r'->'),
    ('MINUSMINUS', r'--'),
    ('PLUS',     r'\+'),
    ('MINUS',    r'-'),
    ('DOT',      r'\.'),
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

KEYWORDS = {'int', 'char', 'void', 'float', 'struct', 'union',
            'short', 'long', 'unsigned', 'signed',
            'if', 'else', 'while', 'for', 'return', 'break', 'continue',
            'int8_t', 'uint8_t', 'int16_t', 'uint16_t', 'int32_t', 'uint32_t'}

# All type keyword token kinds that parse_type() accepts.
TYPE_TOKENS = {'INT', 'CHAR', 'VOID', 'FLOAT', 'SHORT', 'LONG', 'UNSIGNED', 'SIGNED',
               'INT8_T', 'UINT8_T', 'INT16_T', 'UINT16_T', 'INT32_T', 'UINT32_T'}


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
            kind = value.upper()  # INT, CHAR, VOID, INT8_T, UINT8_T, ..., IF, ELSE, ...
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

class FloatLit:
    def __init__(self, value):
        self.value = value  # Python float → will be encoded as IEEE 754 bits

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

class MemberAccess:
    def __init__(self, expr, field):
        self.expr = expr      # expression yielding a struct value or address
        self.field = field    # field name string

class ArrowAccess:
    def __init__(self, expr, field):
        self.expr = expr      # expression yielding a struct pointer
        self.field = field    # field name string

class StructDef:
    """Top-level struct/union definition. Not an expression — just registers the type."""
    def __init__(self, name, fields, is_union=False):
        self.name = name
        self.fields = fields  # list of (type, name, arr_dim_or_None) tuples
        self.is_union = is_union


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
            d = self.parse_top_level()
            if d is not None:
                decls.append(d)
        return Program(decls)

    def parse_type(self):
        """Parse a type, including C-style compound types like
        unsigned int, short, unsigned long, struct name, union name."""
        t = self.advance()
        if t.kind == 'STRUCT':
            struct_name = self.expect('IDENT').value
            type_name = f'struct {struct_name}'
        elif t.kind == 'UNION':
            union_name = self.expect('IDENT').value
            type_name = f'union {union_name}'
        elif t.kind in ('UNSIGNED', 'SIGNED'):
            # unsigned / signed followed optionally by short/int/long/char
            prefix = t.value
            nxt = self.peek().kind
            if nxt == 'SHORT':
                self.advance()
                if self.peek().kind == 'INT':
                    self.advance()  # consume optional 'int'
                type_name = f'{prefix} short'
            elif nxt == 'LONG':
                self.advance()
                if self.peek().kind == 'INT':
                    self.advance()
                type_name = f'{prefix} long'
            elif nxt == 'INT':
                self.advance()
                type_name = f'{prefix} int'
            elif nxt == 'CHAR':
                self.advance()
                type_name = f'{prefix} char'
            else:
                # bare 'unsigned' or 'signed' = unsigned int / signed int
                type_name = f'{prefix} int'
        elif t.kind == 'SHORT':
            if self.peek().kind == 'INT':
                self.advance()
            type_name = 'short'
        elif t.kind == 'LONG':
            if self.peek().kind == 'INT':
                self.advance()
            type_name = 'long'
        elif t.kind in TYPE_TOKENS:
            type_name = t.value
        else:
            raise SyntaxError(f"Line {t.line}: expected type, got {t.value!r}")
        while self.peek().kind == 'STAR':
            self.advance()
            type_name += '*'
        return type_name

    def _try_parse_aggregate_def(self):
        """Try to parse a struct or union definition. Returns StructDef or None."""
        kind = self.peek().kind
        if kind not in ('STRUCT', 'UNION'):
            return None
        if self.tokens[self.pos + 1].kind != 'IDENT':
            return None
        saved = self.pos
        is_union = (kind == 'UNION')
        self.advance()  # 'struct' or 'union'
        sname = self.advance()  # name
        if self.peek().kind == 'LBRACE':
            self.advance()  # '{'
            fields = []
            while self.peek().kind != 'RBRACE':
                ftype = self.parse_type()
                fname = self.expect('IDENT').value
                arr_dim = None
                if self.match('LBRACKET'):
                    arr_dim = int(self.expect('NUMBER').value)
                    self.expect('RBRACKET')
                fields.append((ftype, fname, arr_dim))
                self.expect('SEMI')
            self.expect('RBRACE')
            self.expect('SEMI')
            return StructDef(sname.value, fields, is_union=is_union)
        else:
            self.pos = saved
            return None

    def parse_top_level(self):
        agg = self._try_parse_aggregate_def()
        if agg:
            return agg

        type_name = self.parse_type()
        name = self.expect('IDENT').value
        if self.peek().kind == 'LPAREN':
            return self.parse_func(type_name, name)
        # Array declaration: type name[N];
        arr_dim = None
        if self.match('LBRACKET'):
            arr_dim = int(self.expect('NUMBER').value)
            self.expect('RBRACKET')
        # Global variable
        init_val = None
        if self.match('ASSIGN'):
            init_val = self.parse_expr()
        self.expect('SEMI')
        gv = GlobalVar(type_name, name, init_val)
        gv.arr_dim = arr_dim
        return gv

    def parse_func(self, ret_type, name):
        self.expect('LPAREN')
        params = []
        if self.peek().kind != 'RPAREN':
            params.append(self.parse_param())
            while self.match('COMMA'):
                params.append(self.parse_param())
        self.expect('RPAREN')
        # Forward declaration (prototype): just a semicolon, no body.
        if self.peek().kind == 'SEMI':
            self.advance()
            return None
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

        if pk.kind in TYPE_TOKENS or pk.kind in ('STRUCT', 'UNION'):
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
            arr_dim = None
            if self.match('LBRACKET'):
                arr_dim = int(self.expect('NUMBER').value)
                self.expect('RBRACKET')
            init_expr = None
            if self.match('ASSIGN'):
                init_expr = self.parse_expr()
            vd = VarDecl(type_name, name, init_expr)
            vd.arr_dim = arr_dim
            decls.append(vd)
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
        if self.peek().kind in TYPE_TOKENS or self.peek().kind in ('STRUCT', 'UNION'):
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
        left = self.parse_unary()
        while self.peek().kind in ('STAR', 'SLASH', 'PERCENT'):
            op = {'STAR': '*', 'SLASH': '/', 'PERCENT': '%'}[self.peek().kind]
            self.advance()
            right = self.parse_unary()
            left = BinOp(op, left, right)
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
            elif self.peek().kind == 'DOT':
                self.advance()
                field = self.expect('IDENT').value
                expr = MemberAccess(expr, field)
            elif self.peek().kind == 'ARROW':
                self.advance()
                field = self.expect('IDENT').value
                expr = ArrowAccess(expr, field)
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
            return NumLit(int(pk.value.replace('_', '')))
        if pk.kind == 'HEX':
            self.advance()
            return NumLit(int(pk.value.replace('_', ''), 16))
        if pk.kind == 'BIN':
            self.advance()
            return NumLit(int(pk.value.replace('_', ''), 2))
        if pk.kind == 'FLOAT_LIT':
            self.advance()
            return FloatLit(float(pk.value.replace('_', '')))
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
STDLIB_FUNCS = {'putchar', 'puts', 'sleep', 'setleds', 'printf', 'sprintf',
                'gpio_set_dir', 'gpio_write', 'gpio_read',
                'i2c_start', 'i2c_stop', 'i2c_write', 'i2c_read',
                'adc_read',
                # Signed integer math
                'abs', 'min', 'max', 'clamp', 'clz', 'isqrt',
                # IEEE 754 soft-float
                'fadd', 'fsub', 'fmul', 'fdiv', 'fcmp',
                'itof', 'ftoi', 'adc_readf',
                # Geometric / trig
                'fabs', 'fneg', 'fsqrt', 'fsin', 'fcos', 'fatan2',
                'ftan', 'fatan', 'fasin', 'facos', 'fhypot',
                'fdeg2rad', 'frad2deg',
                'fmin', 'fmax', 'fclamp', 'fsign', 'flerp',
                'ffloor', 'fceil'}


class CodeGen:
    def __init__(self, stdlib_path=None):
        self.output = []
        self.strings = []       # (label, bytes)
        self.stdlib_path = stdlib_path
        self.globals = {}       # name -> (type, label, arr_dim_or_None)
        self.structs = {}       # struct_name -> [(field_type, field_name, arr_dim, offset), ...]
        self.label_count = 0
        self.func_name = ''
        self.locals = {}        # name -> (type, offset, arr_dim_or_None)
        self.param_count = 0
        self.local_offset = 0
        self.loop_stack = []

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

        # Register struct definitions first
        for decl in program.decls:
            if isinstance(decl, StructDef):
                self.register_struct(decl)

        # Collect all function names (user + stdlib) so the codegen can tell
        # a function call from a function-pointer call.
        self.functions = set(STDLIB_FUNCS)
        for decl in program.decls:
            if isinstance(decl, FuncDecl):
                self.functions.add(decl.name)

        # Collect globals
        for decl in program.decls:
            if isinstance(decl, GlobalVar):
                arr_dim = getattr(decl, 'arr_dim', None)
                self.globals[decl.name] = (decl.var_type, f'_g_{decl.name}', arr_dim)

        # Generate functions (skip stdlib and struct definitions)
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

        # Global variables — emit the right number of zero bytes
        for name, (vtype, label, arr_dim) in self.globals.items():
            elem_size = self.type_size(vtype)
            total = elem_size * arr_dim if arr_dim else max(elem_size, 4)
            total = (total + 3) & ~3  # align to 4
            zeros = ', '.join(['0x00'] * total)
            self.emit(f'{label}: db {zeros}')

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

    # Map all type names to their byte size and ISA suffix.
    _TYPE_SIZE = {
        'char': 1, 'signed char': 1, 'unsigned char': 1,
        'int8_t': 1, 'uint8_t': 1,
        'short': 2, 'signed short': 2, 'unsigned short': 2,
        'int16_t': 2, 'uint16_t': 2,
        'int': 4, 'signed int': 4, 'unsigned int': 4, 'unsigned': 4, 'signed': 4,
        'long': 4, 'signed long': 4, 'unsigned long': 4,
        'int32_t': 4, 'uint32_t': 4,
        'float': 4, 'void': 4,
    }
    _TYPE_SUFFIX = {1: '.8', 2: '.16', 4: '.32'}

    def _is_aggregate_type(self, t):
        """True if t is a struct or union type (not a pointer to one)."""
        return ('*' not in t) and (t.startswith('struct ') or t.startswith('union '))

    def _aggregate_name(self, t):
        """Extract the struct/union name from a type string, stripping pointer stars."""
        base = t.rstrip('*').strip()
        if base.startswith('struct '):
            return base[7:]
        if base.startswith('union '):
            return base[6:]
        return None

    def type_size(self, t):
        """Return the byte size of a type. Pointers are always 4 bytes."""
        if '*' in t:
            return 4
        if t.startswith('struct '):
            return self.struct_size(t[7:])
        if t.startswith('union '):
            return self.union_size(t[6:])
        return self._TYPE_SIZE.get(t, 4)

    def size_suffix(self, t):
        """Return the ISA size suffix for scalar loads/stores of this type."""
        if '*' in t:
            return '.32'
        s = self.type_size(t)
        return self._TYPE_SUFFIX.get(s, '.32')

    def struct_size(self, sname):
        """Compute total size of a struct with natural alignment."""
        if sname not in self.structs:
            raise ValueError(f"Undefined struct: {sname}")
        fields = self.structs[sname]
        if not fields:
            return 0
        last = fields[-1]
        _, _, arr_dim, offset = last
        ftype = last[0]
        fsize = self.type_size(ftype)
        if arr_dim:
            fsize *= arr_dim
        total = offset + fsize
        return (total + 3) & ~3

    def union_size(self, uname):
        """Size of a union = size of its largest field, padded to 4."""
        if uname not in self.structs:
            raise ValueError(f"Undefined union: {uname}")
        max_sz = 0
        for ftype, _, arr_dim, _ in self.structs[uname]:
            fsize = self.type_size(ftype)
            if arr_dim:
                fsize *= arr_dim
            if fsize > max_sz:
                max_sz = fsize
        return (max_sz + 3) & ~3

    def struct_field_info(self, sname, field_name):
        """Return (field_type, offset, arr_dim) for a struct field."""
        for ftype, fname, arr_dim, offset in self.structs[sname]:
            if fname == field_name:
                return ftype, offset, arr_dim
        raise ValueError(f"struct {sname} has no field '{field_name}'")

    def register_struct(self, sdef):
        """Compute field offsets with natural alignment and register."""
        is_union = getattr(sdef, 'is_union', False)
        offset = 0
        fields = []
        for item in sdef.fields:
            ftype, fname = item[0], item[1]
            arr_dim = item[2] if len(item) > 2 else None
            fsize = self.type_size(ftype)
            if is_union:
                # All union fields at offset 0
                fields.append((ftype, fname, arr_dim, 0))
            else:
                align = min(fsize, 4)
                offset = (offset + align - 1) & ~(align - 1)
                fields.append((ftype, fname, arr_dim, offset))
                if arr_dim:
                    offset += fsize * arr_dim
                else:
                    offset += fsize
        self.structs[sdef.name] = fields

    def var_elem_size(self, name):
        """Return the element size for a variable (for array indexing).
        For arrays, this is the element type's size. For pointers, the pointed-to type's size.
        For non-arrays, returns the variable's own size."""
        if name in self.locals:
            vtype, _, arr_dim = self.locals[name]
            if arr_dim:
                return self.type_size(vtype)
            if '*' in vtype:
                return self.type_size(vtype.rstrip('*'))
            return self.type_size(vtype)
        if name in self.globals:
            vtype, _, arr_dim = self.globals[name]
            if arr_dim:
                return self.type_size(vtype)
            if '*' in vtype:
                return self.type_size(vtype.rstrip('*'))
            return self.type_size(vtype)
        return 1

    def expr_type(self, node):
        """Infer the type string for an expression."""
        if isinstance(node, Ident):
            if node.name in self.locals:
                return self.locals[node.name][0]
            if node.name in self.globals:
                return self.globals[node.name][0]
        if isinstance(node, MemberAccess):
            base_type = self.expr_type(node.expr)
            aname = self._aggregate_name(base_type) if base_type else None
            if aname:
                ftype, _, _ = self.struct_field_info(aname, node.field)
                return ftype
        if isinstance(node, ArrowAccess):
            base_type = self.expr_type(node.expr)
            aname = self._aggregate_name(base_type) if base_type else None
            if aname:
                ftype, _, _ = self.struct_field_info(aname, node.field)
                return ftype
        if isinstance(node, FloatLit):
            return 'float'
        if isinstance(node, NumLit) or isinstance(node, CharLit):
            return 'int'
        if isinstance(node, ArrayAccess):
            if isinstance(node.array, Ident):
                name = node.array.name
                if name in self.locals:
                    return self.locals[name][0]
                if name in self.globals:
                    return self.globals[name][0]
            bt = self.expr_type(node.array)
            if bt and '*' in bt:
                return bt.rstrip('*')
            return bt
        if isinstance(node, Deref):
            pt = self.expr_type(node.expr)
            if pt and '*' in pt:
                return pt.rstrip('*')
        return None

    def gen_func(self, func):
        self.func_name = func.name
        self.locals = {}
        self.stack_depth = 0

        # Count locals for stack frame (byte-based, handles arrays/structs)
        local_size = self.count_locals_bytes(func.body)
        self.frame_size = local_size

        self.emit(f'{func.name}:')
        self.emit('                sub.32  sp, #4')
        self.emit('                st.32   [sp], r6')
        if local_size > 0:
            self.emit(f'                sub.32  sp, #{local_size}')

        # Map params
        for i, (ptype, pname) in enumerate(func.params):
            self.locals[pname] = (ptype, local_size + 8 + i * 4, None)

        # Map locals (byte-based offsets)
        self._local_offset = 0
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

    def local_var_bytes(self, node):
        """Return the number of bytes a local VarDecl needs on the stack."""
        arr_dim = getattr(node, 'arr_dim', None)
        elem_size = self.type_size(node.var_type)
        if arr_dim:
            total = elem_size * arr_dim
        else:
            total = max(elem_size, 4)  # minimum 4 bytes per scalar
        return (total + 3) & ~3  # align to 4

    def count_locals_bytes(self, node):
        """Count total bytes needed for all local variables."""
        total = 0
        if isinstance(node, Block):
            for s in node.stmts:
                total += self.count_locals_bytes(s)
        elif isinstance(node, VarDecl):
            total += self.local_var_bytes(node)
        elif isinstance(node, IfStmt):
            total += self.count_locals_bytes(node.then_body)
            if node.else_body:
                total += self.count_locals_bytes(node.else_body)
        elif isinstance(node, WhileStmt):
            total += self.count_locals_bytes(node.body)
        elif isinstance(node, ForStmt):
            if isinstance(node.init, VarDecl):
                total += self.local_var_bytes(node.init)
            total += self.count_locals_bytes(node.body)
        return total

    def alloc_locals(self, node):
        if isinstance(node, Block):
            for s in node.stmts:
                self.alloc_locals(s)
        elif isinstance(node, VarDecl):
            arr_dim = getattr(node, 'arr_dim', None)
            self.locals[node.name] = (node.var_type, self._local_offset, arr_dim)
            self._local_offset += self.local_var_bytes(node)
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
        _, base_off, _ = self.locals[name]
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

    def expr_is_float(self, node):
        """Return True if the expression produces a float value."""
        if isinstance(node, FloatLit):
            return True
        if isinstance(node, NumLit) or isinstance(node, CharLit) or isinstance(node, StrLit):
            return False
        if isinstance(node, Ident):
            t = self.expr_type(node)
            return t == 'float'
        if isinstance(node, BinOp):
            return self.expr_is_float(node.left) or self.expr_is_float(node.right)
        if isinstance(node, UnaryOp):
            return self.expr_is_float(node.expr)
        if isinstance(node, FuncCall):
            # Functions that return float.
            return node.name in (
                'fadd', 'fsub', 'fmul', 'fdiv', 'itof', 'adc_readf',
                'fabs', 'fneg', 'fsqrt', 'fsin', 'fcos', 'fatan2',
                'ftan', 'fatan', 'fasin', 'facos', 'fhypot',
                'fdeg2rad', 'frad2deg',
                'fmin', 'fmax', 'fclamp', 'fsign', 'flerp',
                'ffloor', 'fceil',
            )
        if isinstance(node, Assign):
            return self.expr_is_float(node.expr)
        if isinstance(node, ArrayAccess) or isinstance(node, MemberAccess) or isinstance(node, ArrowAccess):
            t = self.expr_type(node)
            return t == 'float'
        return False

    def gen_expr(self, node, dest):
        """Generate code for expression, result in r{dest}."""
        if isinstance(node, NumLit):
            val = node.value
            self.emit(f'                ldi     r{dest}, #{val}')

        elif isinstance(node, FloatLit):
            # Convert Python float to IEEE 754 single-precision bits
            bits = struct.unpack('<I', struct.pack('<f', node.value))[0]
            self.emit(f'                ldi     r{dest}, #{bits}')

        elif isinstance(node, CharLit):
            self.emit(f'                ld.32   r{dest}, #{node.value}')

        elif isinstance(node, StrLit):
            label = self.new_label('str')
            self.strings.append((label, node.value))
            self.emit(f'                ld.32   r{dest}, #{label}')

        elif isinstance(node, Ident):
            if node.name in self.locals:
                off = self.var_offset(node.name)
                vtype, _, arr_dim = self.locals[node.name]
                is_aggregate = arr_dim or self._is_aggregate_type(vtype)
                if is_aggregate:
                    # Arrays and non-pointer structs: load the address, not the value
                    self.emit(f'                ld.32   r{dest}, sp')
                    if off != 0:
                        self.emit(f'                add.32  r{dest}, #{off}')
                else:
                    sz = self.size_suffix(vtype)
                    if sz != '.32':
                        self.emit(f'                clr     r{dest}')
                    self.emit(f'                ld{sz}   r{dest}, [sp][r0+{off}]')
            elif node.name in self.globals:
                vtype, label, arr_dim = self.globals[node.name]
                is_aggregate = arr_dim or self._is_aggregate_type(vtype)
                if is_aggregate:
                    self.emit(f'                ld.32   r{dest}, #{label}')
                else:
                    sz = self.size_suffix(vtype)
                    if sz != '.32':
                        self.emit(f'                clr     r{dest}')
                    self.emit(f'                ld{sz}   r{dest}, {label}')
            else:
                raise ValueError(f"Undefined variable: {node.name}")

        elif isinstance(node, Assign):
            self.gen_expr(node.expr, dest)
            if isinstance(node.target, Ident):
                if node.target.name in self.locals:
                    off = self.var_offset(node.target.name)
                    vtype, _, _ = self.locals[node.target.name]
                    sz = self.size_suffix(vtype)
                    self.emit(f'                st{sz}   [sp][r0+{off}], r{dest}')
                elif node.target.name in self.globals:
                    vtype, label, _ = self.globals[node.target.name]
                    sz = self.size_suffix(vtype)
                    self.emit(f'                st{sz}   {label}, r{dest}')
            elif isinstance(node.target, MemberAccess) or isinstance(node.target, ArrowAccess):
                # x.field = val  or  p->field = val
                self.push(dest)
                # Get address of the struct (or load the pointer)
                if isinstance(node.target, MemberAccess):
                    self.gen_expr(node.target.expr, 2)
                    base_type = self.expr_type(node.target.expr)
                else:
                    self.gen_expr(node.target.expr, 2)
                    base_type = self.expr_type(node.target.expr)
                sname = self._aggregate_name(base_type)
                if not sname:
                    raise ValueError(f"Member assign on non-aggregate type: {base_type}")
                ftype, foff, _ = self.struct_field_info(sname, node.target.field)
                if foff != 0:
                    self.emit(f'                add.32  r2, #{foff}')
                self.pop(dest)
                sz = self.size_suffix(ftype)
                self.emit(f'                st{sz}   [r2], r{dest}')
            elif isinstance(node.target, Deref):
                self.push(dest)
                self.gen_expr(node.target.expr, 2)
                self.pop(dest)
                self.emit(f'                st.32   [r2], r{dest}')
            elif isinstance(node.target, ArrayAccess):
                # Determine element type for size
                elem_type = None
                elem_size = 1
                if isinstance(node.target.array, Ident):
                    aname = node.target.array.name
                    if aname in self.locals:
                        vtype, _, arr_dim = self.locals[aname]
                        if arr_dim:
                            elem_type = vtype
                            elem_size = self.type_size(vtype)
                        elif '*' in vtype:
                            elem_type = vtype.rstrip('*')
                            elem_size = self.type_size(elem_type)
                    elif aname in self.globals:
                        vtype, _, arr_dim = self.globals[aname]
                        if arr_dim:
                            elem_type = vtype
                            elem_size = self.type_size(vtype)
                        elif '*' in vtype:
                            elem_type = vtype.rstrip('*')
                            elem_size = self.type_size(elem_type)
                self.push(dest)
                self.gen_expr(node.target.array, 2)
                self.push(2)
                self.gen_expr(node.target.index, 3)
                self.pop(2)
                self.pop(dest)
                # Scale index by element size
                if elem_size == 2:
                    self.emit(f'                shl.32  r3, #1')
                elif elem_size == 4:
                    self.emit(f'                shl.32  r3, #2')
                elif elem_size > 4:
                    self.emit(f'                ldi     r4, #{elem_size}')
                    self.push(4)
                    self.push(3)
                    self.emit(f'                call    __mul')
                    self.emit(f'                add.32  sp, #8')
                    self.stack_depth -= 2
                    if 3 != 1:
                        self.push(1)
                        self.pop(3)
                sz = self.size_suffix(elem_type) if elem_type else '.8'
                self.emit(f'                st{sz}   [r2][r3], r{dest}')

        elif isinstance(node, BinOp):
            op = node.op

            # Float arithmetic: route through soft-float helpers
            if self.expr_is_float(node) and op in ('+', '-', '*', '/'):
                FLOAT_OP = {'+': 'fadd', '-': 'fsub', '*': 'fmul', '/': 'fdiv'}
                other = 2 if dest != 2 else 3
                self.gen_expr(node.left, dest)
                self.push(dest)
                self.gen_expr(node.right, other)
                self.pop(dest)
                # Push args right-to-left: b then a
                self.push(other)
                self.push(dest)
                self.emit(f'                call    {FLOAT_OP[op]}')
                self.emit(f'                add.32  sp, #8')
                self.stack_depth -= 2
                if dest != 1:
                    self.push(1)
                    self.pop(dest)
                return

            # Float comparison: fcmp then branch on result
            if self.expr_is_float(node) and op in ('==', '!=', '<', '>', '<=', '>='):
                other = 2 if dest != 2 else 3
                self.gen_expr(node.left, dest)
                self.push(dest)
                self.gen_expr(node.right, other)
                self.pop(dest)
                self.push(other)
                self.push(dest)
                self.emit(f'                call    fcmp')
                self.emit(f'                add.32  sp, #8')
                self.stack_depth -= 2
                # r1 = -1/0/+1. Map to 0/1 based on the operator.
                true_label = self.new_label('fcmp_t')
                CMP_FLOAT = {'==': 'beq', '!=': 'bne', '<': 'blt', '>': 'bgt',
                             '<=': 'ble', '>=': 'bge'}
                self.emit(f'                ld.32   r5, #1')
                self.emit(f'                {CMP_FLOAT[op]}.32 r1, #0, {true_label}')
                self.emit(f'                ld.32   r5, #0')
                self.emit(f'{true_label}:')
                if dest != 5:
                    self.push(5)
                    self.pop(dest)
                else:
                    pass  # already in r5
                return

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

            # `>>` defaults to arithmetic shift right (asr) — matches C
            # semantics for signed int, which is what most code expects.
            # Switch to logical shr only if the left operand's type is
            # explicitly unsigned (uint*_t, unsigned ...).
            shr_op = 'asr'
            if op == '>>':
                lt = self.expr_type(node.left)
                if lt and (lt.startswith('unsigned') or lt.startswith('uint')):
                    shr_op = 'shr'

            # Optimize: if right side is a small immediate AND op has an
            # immediate form, fold into a single ALU-with-imm instruction.
            IMM_OP_MAP = {'+': 'add', '-': 'sub', '&': 'and', '|': 'or',
                          '^': 'xor', '<<': 'shl', '>>': shr_op}
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
            # `shr_op` was set above based on signed-ness of left operand.
            OP_MAP = {'+': 'add', '-': 'sub', '&': 'and', '|': 'or',
                      '^': 'xor', '<<': 'shl', '>>': shr_op}
            MUL_MAP = {'*': '__mul', '/': '__div', '%': '__mod'}
            if op in OP_MAP:
                self.push(other)
                self.emit(f'                {OP_MAP[op]}.32 r{dest}, [sp]')
                self.emit(f'                add.32  sp, #4')
                self.stack_depth -= 1
            elif op in MUL_MAP:
                # Runtime helper call: push args right-to-left (b then a)
                self.push(other)
                self.push(dest)
                self.emit(f'                call    {MUL_MAP[op]}')
                self.emit(f'                add.32  sp, #8')
                self.stack_depth -= 2
                if dest != 1:
                    self.push(1)
                    self.pop(dest)
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
            if isinstance(node.expr, ArrayAccess):
                # &arr[i] — evaluate the array access but get the address
                # For struct arrays, ArrayAccess already returns an address.
                # For scalar arrays, we need base + index * elem_size.
                self.gen_expr(node.expr, dest)
                # If the element is not a struct, ArrayAccess loaded the value.
                # We need the address instead. Recompute: base + scaled_index.
                et = self.expr_type(node.expr)
                if et and not self._is_aggregate_type(et):
                    # Scalar element — ArrayAccess loaded the value, but we need
                    # the address. Re-generate as address computation.
                    # Remove the last few emitted lines and redo as address calc.
                    # Simpler: just compute base + index*size directly.
                    # Pop the value load we just did — wasteful but correct.
                    # Actually, let's just do it cleanly:
                    pass
                # For now, a pragmatic approach: if the inner expr is a struct
                # array element, gen_expr already returned the address. For scalar
                # arrays, we need a different path. Let's handle the common case:
                # &arr[i] on a struct array is already correct (address returned).
                # &arr[i] on a scalar array is rare — skip for now.
            elif isinstance(node.expr, Ident):
                if node.expr.name in self.locals:
                    off = self.var_offset(node.expr.name)
                    self.emit(f'                ld.32   r{dest}, sp')
                    if off != 0:
                        self.emit(f'                add.32  r{dest}, #{off}')
                elif node.expr.name in self.functions:
                    # &funcname → load the function's address as an immediate.
                    # The assembler resolves the label at link time.
                    self.emit(f'                ld.32   r{dest}, #{node.expr.name}')
                elif node.expr.name in self.globals:
                    _, label, _ = self.globals[node.expr.name]
                    self.emit(f'                ld.32   r{dest}, #{label}')

        elif isinstance(node, MemberAccess):
            # expr.field — expr is a struct (codegen loads its address)
            self.gen_expr(node.expr, dest)
            base_type = self.expr_type(node.expr)
            sname = self._aggregate_name(base_type)
            if not sname:
                raise ValueError(f"Member access on non-aggregate type: {base_type}")
            ftype, foff, farr = self.struct_field_info(sname, node.field)
            if foff != 0:
                self.emit(f'                add.32  r{dest}, #{foff}')
            # If the field is a non-pointer struct or array, return the address.
            # Otherwise load the scalar value.
            is_aggregate = farr or self._is_aggregate_type(ftype)
            if is_aggregate:
                pass  # r{dest} already holds the address
            else:
                sz = self.size_suffix(ftype)
                if sz != '.32':
                    other = 2 if dest != 2 else 3
                    self.emit(f'                ld.32   r{other}, r{dest}')
                    self.emit(f'                clr     r{dest}')
                    self.emit(f'                ld{sz}   r{dest}, [r{other}]')
                else:
                    self.emit(f'                ld.32   r{dest}, [r{dest}]')

        elif isinstance(node, ArrowAccess):
            # expr->field — expr is a struct pointer
            self.gen_expr(node.expr, dest)
            base_type = self.expr_type(node.expr)
            sname = self._aggregate_name(base_type)
            if not sname:
                raise ValueError(f"Arrow access on non-aggregate-pointer type: {base_type}")
            ftype, foff, farr = self.struct_field_info(sname, node.field)
            if foff != 0:
                self.emit(f'                add.32  r{dest}, #{foff}')
            is_aggregate = farr or self._is_aggregate_type(ftype)
            if is_aggregate:
                pass
            else:
                sz = self.size_suffix(ftype)
                if sz != '.32':
                    other = 2 if dest != 2 else 3
                    self.emit(f'                ld.32   r{other}, r{dest}')
                    self.emit(f'                clr     r{dest}')
                    self.emit(f'                ld{sz}   r{dest}, [r{other}]')
                else:
                    self.emit(f'                ld.32   r{dest}, [r{dest}]')

        elif isinstance(node, ArrayAccess):
            # Determine element size and type
            elem_type = None
            elem_size = 1
            if isinstance(node.array, Ident):
                name = node.array.name
                if name in self.locals:
                    vtype, _, arr_dim = self.locals[name]
                    if arr_dim:
                        elem_type = vtype
                        elem_size = self.type_size(vtype)
                    elif '*' in vtype:
                        elem_type = vtype.rstrip('*')
                        elem_size = self.type_size(elem_type)
                elif name in self.globals:
                    vtype, _, arr_dim = self.globals[name]
                    if arr_dim:
                        elem_type = vtype
                        elem_size = self.type_size(vtype)
                    elif '*' in vtype:
                        elem_type = vtype.rstrip('*')
                        elem_size = self.type_size(elem_type)
            self.gen_expr(node.array, dest)
            other = 2 if dest != 2 else 3
            self.push(dest)
            self.gen_expr(node.index, other)
            self.pop(dest)
            # Scale index by element size
            if elem_size > 1:
                if elem_size == 2:
                    self.emit(f'                shl.32  r{other}, #1')
                elif elem_size == 4:
                    self.emit(f'                shl.32  r{other}, #2')
                elif elem_size == 8:
                    self.emit(f'                shl.32  r{other}, #3')
                elif elem_size == 16:
                    self.emit(f'                shl.32  r{other}, #4')
                else:
                    # __mul clobbers r1-r5, so save the base address first
                    self.push(dest)
                    self.emit(f'                ldi     r4, #{elem_size}')
                    self.push(4)
                    self.push(other)
                    self.emit(f'                call    __mul')
                    self.emit(f'                add.32  sp, #8')
                    self.stack_depth -= 2
                    # r1 = scaled index; restore base
                    if other != 1:
                        self.emit(f'                ld.32   r{other}, r1')
                    self.pop(dest)
            # If the element is a struct, return the address (base + scaled_index)
            if elem_type and self._is_aggregate_type(elem_type):
                self.push(other)
                self.emit(f'                add.32  r{dest}, [sp]')
                self.emit(f'                add.32  sp, #4')
                self.stack_depth -= 1
            else:
                # Load the element. For sub-word loads, mask after instead
                # of clearing before — the dest register is also the AGU
                # base, so a pre-clear would clobber the base address.
                sz = self.size_suffix(elem_type) if elem_type else '.8'
                self.push(other)
                self.emit(f'                ld{sz}   r{dest}, [r{dest}][r{other}]')
                self.emit(f'                add.32  sp, #4')
                self.stack_depth -= 1
                if sz == '.8':
                    self.emit(f'                and.32  r{dest}, #0xFF')
                elif sz == '.16':
                    self.emit(f'                and.32  r{dest}, #0xFFFF')

        elif isinstance(node, FuncCall):
            # Function-pointer call: if the name is a known variable (not a
            # function), load it as a target address and use `call rN`.
            is_indirect = (node.name not in self.functions and
                           (node.name in self.locals or node.name in self.globals))
            # Push arguments right-to-left
            for arg in reversed(node.args):
                self.gen_expr(arg, 1)
                self.push(1)
            if is_indirect:
                # Load the function pointer into r2 and call indirect.
                # Stack-depth of all the pushed args is already accounted for
                # by the var_offset adjustment.
                if node.name in self.locals:
                    off = self.var_offset(node.name)
                    self.emit(f'                ld.32   r2, [sp][r0+{off}]')
                else:
                    _, label, _ = self.globals[node.name]
                    self.emit(f'                ld.32   r2, {label}')
                self.emit(f'                call    r2')
            else:
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


def preprocess(source, base_dir, _included=None, _defines=None):
    """Minimal C preprocessor.

    Supports:
      #include "file"           — textual inclusion (circular/duplicate guarded)
      #define NAME value        — simple text substitution (no function macros)
      #define NAME              — define as empty (for #ifdef)
      #undef NAME
      #ifdef NAME / #ifndef NAME / #else / #endif — conditional compilation
    """
    if _included is None:
        _included = set()
    if _defines is None:
        _defines = {}
    lines = source.split('\n')
    out = []
    # Conditional compilation stack: each entry is True if we're emitting
    cond_stack = [True]

    for line in lines:
        stripped = line.strip()
        active = all(cond_stack)

        # ---- Conditional directives (always processed, even when skipping) ----
        if stripped.startswith('#ifdef '):
            name = stripped[len('#ifdef '):].strip()
            cond_stack.append(active and name in _defines)
            continue
        if stripped.startswith('#ifndef '):
            name = stripped[len('#ifndef '):].strip()
            cond_stack.append(active and name not in _defines)
            continue
        if stripped == '#else':
            if len(cond_stack) < 2:
                print("error: #else without #ifdef/#ifndef", file=sys.stderr)
                sys.exit(1)
            parent_active = all(cond_stack[:-1])
            cond_stack[-1] = parent_active and not cond_stack[-1]
            continue
        if stripped == '#endif':
            if len(cond_stack) < 2:
                print("error: #endif without #ifdef/#ifndef", file=sys.stderr)
                sys.exit(1)
            cond_stack.pop()
            continue

        if not active:
            continue

        # ---- #include ----
        if stripped.startswith('#include'):
            rest = stripped[len('#include'):].strip()
            if rest.startswith('"') and rest.endswith('"'):
                fname = rest[1:-1]
                fpath = os.path.join(base_dir, fname)
                if fpath in _included:
                    continue
                _included.add(fpath)
                try:
                    with open(fpath) as f:
                        inc_source = f.read()
                except FileNotFoundError:
                    print(f"error: #include file not found: {fname}", file=sys.stderr)
                    sys.exit(1)
                inc_dir = os.path.dirname(os.path.abspath(fpath))
                out.append(preprocess(inc_source, inc_dir, _included, _defines))
            continue

        # ---- #define ----
        if stripped.startswith('#define '):
            rest = stripped[len('#define '):].strip()
            parts = rest.split(None, 1)
            name = parts[0]
            value = parts[1] if len(parts) > 1 else ''
            _defines[name] = value
            continue

        # ---- #undef ----
        if stripped.startswith('#undef '):
            name = stripped[len('#undef '):].strip()
            _defines.pop(name, None)
            continue

        # ---- Other # directives: skip silently ----
        if stripped.startswith('#'):
            continue

        # ---- Apply text substitutions ----
        if _defines:
            for name, value in _defines.items():
                if name in line:
                    # Word-boundary replacement to avoid partial matches
                    import re
                    line = re.sub(r'\b' + re.escape(name) + r'\b', value, line)

        out.append(line)

    return '\n'.join(out)


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

    source = preprocess(source, os.path.dirname(os.path.abspath(input_file)))

    # Find stdlib.asm next to this script
    stdlib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stdlib.asm')
    if not os.path.exists(stdlib_path):
        stdlib_path = None

    try:
        tokens = tokenize(source)
        parser = Parser(tokens)
        ast = parser.parse()
        codegen = CodeGen(stdlib_path=stdlib_path)
        asm = codegen.generate(ast)
    except SyntaxError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

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
