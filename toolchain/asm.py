#!/usr/bin/env python3
"""Assembler for the MPU ISA. Outputs a binary file."""

import sys
import os
import re
import struct

# ---- Opcodes ----
OPCODES = {
    'nop':  0,
    'ld':   1,  'ldh':  2,  'st':   3,
    'add':  4,  'sub':  5,
    'beq':  6,  'bne':  7,  'blt':  8,  'bgt':  9,  'ble': 10, 'bge': 11,
    'and': 12,  'or':  13,  'xor': 14,  'shl': 15,  'shr': 16,
    'call': 17, 'ret': 18,
}

SIZES = {'.8': 0, '.16': 1, '.32': 2}

REGS = {f'r{i}': i for i in range(7)}
REGS['sp'] = 7

# Instructions that use the AGU for their operand
AGU_OPS = {'ld', 'st', 'add', 'sub', 'and', 'or', 'xor', 'shl', 'shr'}

# Branch instructions
BRANCH_OPS = {'beq', 'bne', 'blt', 'bgt', 'ble', 'bge'}

# Pseudo-instructions. `push` is expanded by expand_pseudos() into a pair of
# native instructions; the rest are handled inline in encode_instruction().
PSEUDO_OPS = {'jmp', 'push', 'pop', 'clr', 'ldi'}

# All known mnemonics (with possible size suffixes) and directives
ALL_MNEMONICS = set(OPCODES.keys()) | PSEUDO_OPS
DIRECTIVES = {'db', 'end'}


def parse_int(s):
    """Parse an integer literal (decimal, hex, binary)."""
    s = s.strip()
    neg = s.startswith('-')
    if neg:
        s = s[1:]
    if s.startswith('0x') or s.startswith('0X'):
        v = int(s, 16)
    elif s.startswith('0b') or s.startswith('0B'):
        v = int(s, 2)
    else:
        v = int(s)
    return -v if neg else v


def mask(value, bits):
    """Mask a value to the given number of bits (two's complement)."""
    return value & ((1 << bits) - 1)


def parse_db(args_str):
    """Parse a db directive and return raw bytes.

    Supports:
        'string literal' with \\0 \\n \\r \\t \\\\
        comma-separated byte values: 0x0A, 10, 0b1111
    """
    data = bytearray()
    i = 0
    s = args_str.strip()
    while i < len(s):
        if s[i] in ("'", '"'):
            quote = s[i]
            i += 1
            while i < len(s) and s[i] != quote:
                if s[i] == '\\' and i + 1 < len(s):
                    esc = s[i + 1]
                    if esc == '0':
                        data.append(0)
                    elif esc == 'n':
                        data.append(0x0A)
                    elif esc == 'r':
                        data.append(0x0D)
                    elif esc == 't':
                        data.append(0x09)
                    elif esc == '\\':
                        data.append(0x5C)
                    else:
                        data.append(ord(esc))
                    i += 2
                else:
                    data.append(ord(s[i]))
                    i += 1
            i += 1  # skip closing quote
        elif s[i] == ',':
            i += 1
        elif s[i] in ' \t':
            i += 1
        else:
            # Numeric byte value
            end = i
            while end < len(s) and s[end] not in ', \t':
                end += 1
            data.append(parse_int(s[i:end]) & 0xFF)
            i = end
    return bytes(data)


def align4(n):
    """Round up to next multiple of 4."""
    return (n + 3) & ~3


def get_mnemonic(word):
    """Check if a word (ignoring size suffix) is a known mnemonic or directive."""
    w = word.lower()
    if w in ALL_MNEMONICS or w in DIRECTIVES:
        return True
    for suffix in SIZES:
        if w.endswith(suffix) and w[:-len(suffix)] in ALL_MNEMONICS:
            return True
    return False


def strip_label(line):
    """
    Strip a label from the front of a line. Returns (label_or_None, rest).
    Supports both 'label: instr' and 'label instr' (when first word isn't a mnemonic).
    """
    # Colon style: 'label: ...' or 'label:'
    if ':' in line and not line.startswith('['):
        label, rest = line.split(':', 1)
        return label.strip(), rest.strip()

    # No-colon style: first word is label if second word is a mnemonic/directive
    parts = line.split(None, 1)
    if len(parts) >= 2:
        first = parts[0]
        rest = parts[1]
        second = rest.split(None, 1)[0] if rest else ''
        if not get_mnemonic(first) and get_mnemonic(second):
            return first, rest

    return None, line


def resolve_label(name, labels, scope):
    """Resolve a label name, expanding local labels with current scope."""
    if name.startswith('.'):
        full = scope + name
        if full in labels:
            return labels[full]
        raise ValueError(f"Unknown local label: {name} (looked up as {full})")
    if name in labels:
        return labels[name]
    raise ValueError(f"Unknown label: {name}")


def resolve_label_or_int(name, labels, scope):
    """Resolve a label or parse as integer."""
    if name.startswith('.'):
        return resolve_label(name, labels, scope)
    if name in labels:
        return labels[name]
    return parse_int(name)


def encode_agu(operand_str, labels, scope=''):
    """
    Parse an AGU operand and return (reg_value, addr_imm, payload_20).

    Formats:
        #imm                -> immediate
        Rreg                -> register direct (mode 00)
        .label              -> absolute address
        [Rbase]             -> indirect (mode 01 via r0)
        [Rbase][Ridx]       -> indexed
        [Rbase][Ridx+off]   -> indexed + offset
        [Rbase][Ridx+=off]  -> indexed + offset + writeback
    """
    operand = operand_str.strip()

    # Immediate: #value or #label
    if operand.startswith('#'):
        val_str = operand[1:]
        val = resolve_label_or_int(val_str, labels, scope)
        return 1, 1, mask(val, 20)

    # Register direct: bare register name -> mode 00
    if operand in REGS:
        base = REGS[operand]
        payload = (base << 17)  # mode=00, idx=0, offset=0
        return 0, 0, payload

    # Absolute address: .label or label
    if not operand.startswith('['):
        try:
            val = resolve_label_or_int(operand, labels, scope)
        except ValueError:
            val = parse_int(operand)
        return 1, 0, mask(val, 20)

    # Register modes: [Rbase]...
    # r0-implicit shorthands: r0 is the constant zero, so anything that
    # would otherwise need an explicit `[r0]` base can be elided.
    #   [Ridx+=off]  -> [r0][Ridx+=off]   (post-increment load/store)
    #   [Ridx++]     -> [r0][Ridx+=1]
    #   [Ridx+off]   -> [r0][Ridx+off]    (indexed read with offset)
    #   [Ridx]       -> already meaningful (mode 01 [Rbase] via r0)
    m_short = re.match(r'^\[(\w+)(\+\+|--|(([+-])=(-?\w+)))\]$', operand)
    if m_short:
        reg = m_short.group(1)
        if m_short.group(2) == '++':
            operand = f'[r0][{reg}+=1]'
        elif m_short.group(2) == '--':
            operand = f'[r0][{reg}+=-1]'
        else:
            operand = f'[r0][{reg}{m_short.group(3)}]'
    else:
        # [Rreg+offset] / [Rreg-offset] (no writeback) -> [r0][Rreg+offset]
        m_off = re.match(r'^\[(\w+)([+-])(-?\w+)\]$', operand)
        if m_off and m_off.group(1) in REGS:
            operand = f'[r0][{m_off.group(1)}{m_off.group(2)}{m_off.group(3)}]'

    # Parse full two-bracket form
    m = re.match(r'\[(\w+)\](?:\[(\w+)((\+\+|--)|([+-])=?(-?\w+))?\])?', operand)
    if not m:
        raise ValueError(f"Cannot parse addressing mode: {operand}")

    base_str = m.group(1)
    idx_str = m.group(2)
    shorthand = m.group(4)  # ++ or --
    op_char = m.group(5)    # + or -
    has_wb = shorthand is not None or '=' in (m.group(3) or '')
    off_str = m.group(6)

    if base_str not in REGS:
        raise ValueError(f"Unknown register: {base_str}")
    base = REGS[base_str]

    if idx_str is None:
        # [Rbase] - encode as mode 01 [Rbase][r0] (mode 00 is register direct)
        mode = 1
        idx = 0
        offset = 0
    elif shorthand is not None and off_str is None:
        # [Rbase][Ridx++] or [Rbase][Ridx--] - mode 11, offset +1/-1
        if idx_str not in REGS:
            raise ValueError(f"Unknown register: {idx_str}")
        idx = REGS[idx_str]
        mode = 3
        offset = 1 if shorthand == '++' else -1
    elif off_str is None:
        # [Rbase][Ridx] - mode 01
        if idx_str not in REGS:
            raise ValueError(f"Unknown register: {idx_str}")
        mode = 1
        idx = REGS[idx_str]
        offset = 0
    else:
        if idx_str not in REGS:
            raise ValueError(f"Unknown register: {idx_str}")
        idx = REGS[idx_str]
        off_val = parse_int(off_str)
        if op_char == '-':
            off_val = -off_val
        if has_wb:
            # [Rbase][Ridx+=offset] - mode 11
            mode = 3
        else:
            # [Rbase][Ridx+offset] - mode 10
            mode = 2
        offset = off_val

    payload = (base << 17) | (mode << 15) | (idx << 12) | mask(offset, 12)
    return 0, 0, payload


def encode_branch(args, labels, scope=''):
    """
    Parse branch arguments: rd, cmp_operand, target
    Returns (rd, payload_20).

    Formats:
        bne r1, r2, .label
        bne r1, #3, .label
    """
    parts = [a.strip() for a in args.split(',')]
    if len(parts) != 3:
        raise ValueError(f"Branch needs 3 arguments: rd, cmp, target (got: {args})")

    rd_str, cmp_str, target_str = parts

    if rd_str not in REGS:
        raise ValueError(f"Unknown register: {rd_str}")
    rd = REGS[rd_str]

    # Compare operand
    if cmp_str.startswith('#'):
        reg_or_imm = 1
        cmp_val = parse_int(cmp_str[1:])
        if cmp_val < 0 or cmp_val > 7:
            raise ValueError(f"Branch immediate must be 0-7, got {cmp_val}")
        cmp_bits = cmp_val & 0x7
    elif cmp_str in REGS:
        reg_or_imm = 0
        cmp_bits = REGS[cmp_str]
    else:
        raise ValueError(f"Invalid compare operand: {cmp_str}")

    # Target
    target_str = target_str.strip()
    target = resolve_label_or_int(target_str, labels, scope)

    if target < 0 or target > 0xFFFF:
        raise ValueError(f"Branch target out of 16-bit range: {target:#x}")

    payload = (reg_or_imm << 19) | (cmp_bits << 16) | (target & 0xFFFF)
    return rd, payload


SIZE_NAMES = {0: '.8', 1: '.16', 2: '.32'}

OPCODE_NAMES = {v: k.upper() for k, v in OPCODES.items()}

MODE_NAMES = {
    0: '[Rbase]',
    1: '[Rbase][Ridx]',
    2: '[Rbase][Ridx+off]',
    3: '[Rbase][Ridx+=off]',
}


def format_listing(addr, word, source_line):
    """Format a MASM-style listing line showing instruction field breakdown."""
    opcode = (word >> 27) & 0x1F
    rd     = (word >> 24) & 0x7
    size   = (word >> 22) & 0x3
    rv     = (word >> 21) & 0x1
    ai     = (word >> 20) & 0x1
    payload = word & 0xFFFFF

    op_name = OPCODE_NAMES.get(opcode, f'?{opcode}')
    sz_name = SIZE_NAMES.get(size, '??')

    # Field breakdown
    fields = f'op={op_name:<4s} rd=r{rd} sz={sz_name}'

    if op_name in ('BEQ', 'BNE', 'BLT', 'BGT', 'BLE', 'BGE'):
        ri  = (payload >> 19) & 1
        cmp = (payload >> 16) & 7
        tgt = payload & 0xFFFF
        if ri:
            fields += f' cmp=#{cmp} target={tgt:#06x}'
        else:
            fields += f' cmp=r{cmp} target={tgt:#06x}'
    elif op_name in ('CALL',):
        sx = payload if payload < 0x80000 else payload - 0x100000
        fields += f' target={sx:#x}'
    elif op_name in ('RET', 'NOP'):
        pass
    elif rv:
        sx = payload if payload < 0x80000 else payload | 0xFFF00000
        if ai:
            fields += f' #imm={sx:#010x}'
        else:
            fields += f' [abs={sx:#010x}]'
    else:
        base = (payload >> 17) & 7
        mode = (payload >> 15) & 3
        idx  = (payload >> 12) & 7
        off  = payload & 0xFFF
        if off & 0x800:
            off -= 0x1000
        fields += f' r{base}'
        if mode == 0:
            fields += f' =r{base}'
        elif mode == 1:
            fields += f' [r{base}][r{idx}]'
        elif mode == 2:
            fields += f' [r{base}][r{idx}+{off}]'
        elif mode == 3:
            fields += f' [r{base}][r{idx}+={off}]'

    return f'{addr:04X}: {word:08X}  {fields:<44s} {source_line}'


def format_db_listing(addr, data, source_line):
    """Format listing for db directive."""
    hex_str = ' '.join(f'{b:02X}' for b in data)
    return f'{addr:04X}: {hex_str:<18s} {"db":<44s} {source_line}'


def hide_r0(asm_text):
    """Strip the bookkeeping `r0` slot from AGU operands so the surface
    syntax matches what a human would write. Equivalences applied:

        [r0][Ridx+=N]  -> [Ridx+=N]
        [r0][Ridx++]   -> [Ridx++]
        [r0][Ridx-=N]  -> [Ridx-=N]
        [r0][Ridx--]   -> [Ridx--]
        [Rbase][r0+N]  -> [Rbase+N]
        [Rbase][r0-N]  -> [Rbase-N]
        [r0][Rreg+N]   -> [Rreg+N]
        [r0][Rreg-N]   -> [Rreg-N]
        [r0][Rreg]     -> [Rreg]

    These are pure surface-syntax rewrites; the assembler accepts both
    forms and produces identical encodings."""
    rules = [
        (re.compile(r'\[r0\]\[(\w+)(\+\+|--|[+-]=-?\w+)\]'), r'[\1\2]'),
        (re.compile(r'\[(\w+)\]\[r0([+-]\w+)\]'),            r'[\1\2]'),
        (re.compile(r'\[r0\]\[(\w+)([+-]\w+)\]'),            r'[\1\2]'),
        (re.compile(r'\[r0\]\[(\w+)\]'),                     r'[\1]'),
    ]
    for pat, repl in rules:
        asm_text = pat.sub(repl, asm_text)
    return asm_text


_PS_REG = r'(?:r[0-7]|sp)'
_PS_TAIL = r'(\s*(?:;.*)?)$'   # optional trailing whitespace + line comment
_PS_PUSH_A = re.compile(rf'^(\s*)sub\.32\s+sp,\s*#4{_PS_TAIL}')
_PS_PUSH_B = re.compile(rf'^\s*st\.32\s+\[sp\],\s*({_PS_REG}){_PS_TAIL}')
_PS_POP    = re.compile(rf'^(\s*)ld\.32\s+({_PS_REG}),\s*\[r0\]\[sp\+=4\]{_PS_TAIL}')
_PS_CLR    = re.compile(rf'^(\s*)ld(\.(?:8|16|32))\s+({_PS_REG}),\s*r0{_PS_TAIL}')


def _ps_clean_tail(t):
    """Strip whitespace and discard the decorative `\\` / `/` markers used
    by the stdlib's stack-pair pretty-printing (`; \\ save r6` /
    `; / save r6`). Pure decoration with no message becomes empty."""
    t = t.strip()
    if not t.startswith(';'):
        return ''
    body = t[1:].lstrip()
    if body.startswith('\\') or body.startswith('/'):
        body = body[1:].lstrip()
    if not body:
        return ''
    return '; ' + body


def _ps_format(indent, body, tail):
    """Format a pseudo-op line with the original indent and a tail comment
    aligned to the conventional column 36 (counted from after the indent)."""
    line = indent + body
    if tail:
        body_len = len(line) - len(indent)
        pad = ' ' * max(1, 36 - body_len)
        line += pad + tail
    return line


def to_pseudo_ops(asm_text):
    """Rewrite the compiler-style native sequences `sub sp,#4 / st [sp],rN`,
    `ld rN, [r0][sp+=4]`, and `ld rD, r0` as their `push` / `pop` / `clr`
    pseudo-op equivalents. Used by the high-level compilers so the `.s`
    output (and the asm fed to the assembler) reads naturally. Plain
    register-to-register `ld.32 rD, rS` is left untouched — it's already
    the canonical surface form for a register move."""
    lines = asm_text.split('\n')
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m1 = _PS_PUSH_A.match(line)
        if m1 and i + 1 < n:
            m2 = _PS_PUSH_B.match(lines[i + 1])
            if m2:
                t1 = _ps_clean_tail(m1.group(2))
                t2 = _ps_clean_tail(m2.group(2))
                tail = t1 or t2
                out.append(_ps_format(m1.group(1), f'push    {m2.group(1)}', tail))
                i += 2
                continue
        m = _PS_POP.match(line)
        if m:
            tail = _ps_clean_tail(m.group(3))
            out.append(_ps_format(m.group(1), f'pop     {m.group(2)}', tail))
            i += 1
            continue
        m = _PS_CLR.match(line)
        if m:
            tail = _ps_clean_tail(m.group(4))
            sz = m.group(2)                              # ".8" / ".16" / ".32"
            sz_suffix = '' if sz == '.32' else sz        # default clr is .32
            out.append(_ps_format(m.group(1), f'clr{sz_suffix:<4} {m.group(3)}', tail))
            i += 1
            continue
        out.append(line)
        i += 1
    # Second pass: clean up the ASCII bracket art (`; \`, `; |`, `; /`) that
    # the original stdlib used to group multi-line stack-pair sequences. Now
    # that those sequences have collapsed into single push/pop pseudos, the
    # orphan markers either become content-free comments (drop them) or have
    # extra content (drop just the leading marker).
    cleaned = []
    for line in out:
        code, sep, comment = line.partition(';')
        if sep:
            body = comment.lstrip()
            if body in ('/', '|', '\\'):
                cleaned.append(code.rstrip())
                continue
            if body[:2] in ('| ', '/ ', '\\ '):
                cleaned.append(f'{code.rstrip()}              ; {body[2:]}')
                continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def expand_pseudos(source):
    """Expand variable-length pseudo-ops to native instructions before the
    two-pass assembler runs. `push` always expands to two instructions;
    `ldi` expands to one or two depending on whether the immediate fits in
    the 20-bit signed payload of LD. Single-instruction pseudo-ops (`pop`,
    `clr`, `jmp`) are encoded directly in encode_instruction()."""
    out = []
    for raw in source.split('\n'):
        code = raw.split(';')[0]
        stripped = code.strip()
        if not stripped:
            out.append(raw)
            continue
        label, rest = strip_label(stripped)
        parts = rest.split(None, 1) if rest else []

        if parts and parts[0].lower() == 'push':
            reg = (parts[1] if len(parts) > 1 else '').strip()
            if label:
                out.append(f'{label}:')
            out.append('                sub.32  sp, #4')
            out.append(f'                st.32   [sp], {reg}')
            continue

        if parts and parts[0].lower() == 'ldi':
            args_str = (parts[1] if len(parts) > 1 else '').strip()
            m = re.match(r'^(\w+)\s*,\s*#(.+)$', args_str)
            if m:
                reg = m.group(1)
                val_str = m.group(2).strip()
                # If the value is a literal we can resolve here, decide
                # whether one ld is enough. Otherwise (label, expression)
                # always emit ld + ldh — labels in the 64KB code space
                # would fit in a single ld, but at this stage we don't
                # know addresses yet, so we conservatively reserve two
                # instruction slots.
                emit_pair = True
                try:
                    val = parse_int(val_str)
                    if -0x80000 <= val <= 0x7FFFF:
                        emit_pair = False
                except (ValueError, KeyError):
                    pass
                if label:
                    out.append(f'{label}:')
                if emit_pair:
                    try:
                        val = parse_int(val_str)
                        low = val & 0xFFFFF
                        high = (val >> 12) & 0xFFFFF
                        out.append(f'                ld.32   {reg}, #{low}')
                        out.append(f'                ldh     {reg}, #{high}')
                    except (ValueError, KeyError):
                        # Label or expression: pass through to the encoder.
                        out.append(f'                ld.32   {reg}, #{val_str}')
                        out.append(f'                ldh     {reg}, #{val_str}')
                else:
                    out.append(f'                ld.32   {reg}, #{val}')
                continue

        out.append(raw)
    return '\n'.join(out)


def assemble(source, listing=False):
    """Two-pass assembler. Returns bytes, or (bytes, listing_lines) if listing=True."""
    source = expand_pseudos(source)
    lines = source.split('\n')

    # ---- Pass 1: collect labels ----
    labels = {}
    scope = ''
    addr = 0
    for line in lines:
        line = line.split(';')[0].strip()
        if not line:
            continue

        label, line = strip_label(line)
        if label:
            if label.startswith('.'):
                # Local label: scope it to the current global
                full = scope + label
            else:
                # Global label: update scope
                scope = label
                full = label
            labels[full] = addr
        if not line:
            continue

        parts = line.split(None, 1)
        if parts[0].lower() == 'end':
            break
        if parts[0].lower() == 'db':
            data = parse_db(parts[1] if len(parts) > 1 else '')
            addr += align4(len(data))
            continue

        addr += 4

    # ---- Pass 2: encode ----
    output = bytearray()
    listing_lines = []
    scope = ''
    addr = 0
    for line_no, line in enumerate(lines, 1):
        raw_line = line
        line = line.split(';')[0].strip()
        if not line:
            continue

        label, line = strip_label(line)
        if label:
            if label.startswith('.'):
                pass  # local, scope unchanged
            else:
                scope = label
        if not line:
            continue

        parts = line.split(None, 1)
        if parts[0].lower() == 'end':
            break

        # db directive
        if parts[0].lower() == 'db':
            data = parse_db(parts[1] if len(parts) > 1 else '')
            padded = data + b'\x00' * (align4(len(data)) - len(data))
            if listing:
                listing_lines.append(format_db_listing(addr, data, raw_line.rstrip()))
            output += padded
            addr += len(padded)
            continue

        try:
            word = encode_instruction(line, labels, scope)
        except Exception as e:
            print(f"Error on line {line_no}: {e}", file=sys.stderr)
            print(f"  {line}", file=sys.stderr)
            sys.exit(1)

        if listing:
            listing_lines.append(format_listing(addr, word, raw_line.rstrip()))
        output += struct.pack('<I', word)
        addr += 4

    if listing:
        return bytes(output), listing_lines
    return bytes(output)


def encode_instruction(line, labels, scope=''):
    """Encode a single instruction line into a 32-bit word."""
    # Split mnemonic from arguments
    parts = line.split(None, 1)
    mnem_full = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ''

    # Parse size suffix
    size = 2  # default .l
    for suffix, sz in SIZES.items():
        if mnem_full.endswith(suffix):
            mnem = mnem_full[:-len(suffix)]
            size = sz
            break
    else:
        mnem = mnem_full

    # ---- JMP pseudo-instruction: beq r0, #0, target ----
    if mnem == 'jmp':
        target_str = args.strip()
        target = resolve_label_or_int(target_str, labels, scope)
        if target < 0 or target > 0xFFFF:
            raise ValueError(f"JMP target out of 16-bit range: {target:#x}")
        opcode = OPCODES['beq']
        # rd=r0, reg_or_imm=1, cmp=0, target
        payload = (1 << 19) | (0 << 16) | (target & 0xFFFF)
        return (opcode << 27) | (0 << 24) | (size << 22) | payload

    # ---- POP rN — single-instruction pseudo: ld.32 rN, [sp+=4] ----
    if mnem == 'pop':
        reg = args.strip()
        return encode_instruction(f'ld.32   {reg}, [sp+=4]', labels, scope)

    # ---- CLR rD — single-instruction pseudo: ld.<size> rD, r0 ----
    # Size suffix is honoured. Default is `.32` (which clears the whole
    # register); `.8`/`.16` clear only the low byte/halfword and preserve
    # the upper bits, matching ld's size-merge behaviour.
    if mnem == 'clr':
        reg = args.strip()
        sz_name = SIZE_NAMES[size]
        return encode_instruction(f'ld{sz_name}   {reg}, r0', labels, scope)

    if mnem not in OPCODES:
        raise ValueError(f"Unknown mnemonic: {mnem}")
    opcode = OPCODES[mnem]

    # ---- NOP ----
    if mnem == 'nop':
        return 0

    # ---- RET ----
    if mnem == 'ret':
        return opcode << 27

    # ---- CALL ----
    if mnem == 'call':
        target_str = args.strip()
        target = resolve_label_or_int(target_str, labels, scope)
        payload = mask(target, 20)
        return (opcode << 27) | payload

    # ---- LDH ----
    if mnem == 'ldh':
        arg_parts = [a.strip() for a in args.split(',')]
        if len(arg_parts) != 2:
            raise ValueError("LDH needs 2 arguments: rd, #imm")
        rd_str, imm_str = arg_parts
        if rd_str not in REGS:
            raise ValueError(f"Unknown register: {rd_str}")
        rd = REGS[rd_str]
        if imm_str.startswith('#'):
            imm_str = imm_str[1:]
        val = parse_int(imm_str)
        payload = mask(val, 20)
        return (opcode << 27) | (rd << 24) | (size << 22) | payload

    # ---- Branches ----
    if mnem in BRANCH_OPS:
        rd, payload = encode_branch(args, labels, scope)
        return (opcode << 27) | (rd << 24) | (size << 22) | payload

    # ---- AGU instructions (LD, ST, ADD, SUB, AND, OR, XOR, SHL, SHR) ----
    if mnem in AGU_OPS:
        arg_parts = split_args(args)

        if mnem == 'st':
            # st operand, rd  OR  st [addr], rd
            if len(arg_parts) != 2:
                raise ValueError("ST needs 2 arguments")
            addr_str, rd_str = arg_parts
            if rd_str not in REGS:
                raise ValueError(f"Unknown register: {rd_str}")
            rd = REGS[rd_str]
            reg_value, addr_imm, payload = encode_agu(addr_str, labels, scope)
            # For ST with immediate: swap meaning - imm is the value, rd has the address
            return (opcode << 27) | (rd << 24) | (size << 22) | (reg_value << 21) | (addr_imm << 20) | payload
        else:
            # rd, operand
            if len(arg_parts) != 2:
                raise ValueError(f"{mnem.upper()} needs 2 arguments: rd, operand")
            rd_str, operand_str = arg_parts
            if rd_str not in REGS:
                raise ValueError(f"Unknown register: {rd_str}")
            rd = REGS[rd_str]
            reg_value, addr_imm, payload = encode_agu(operand_str, labels, scope)
            return (opcode << 27) | (rd << 24) | (size << 22) | (reg_value << 21) | (addr_imm << 20) | payload

    raise ValueError(f"Unhandled mnemonic: {mnem}")


def split_args(args_str):
    """Split arguments respecting brackets. 'r1, [r2][r3+=4]' -> ['r1', '[r2][r3+=4]']"""
    result = []
    current = ''
    depth = 0
    for ch in args_str:
        if ch == '[':
            depth += 1
            current += ch
        elif ch == ']':
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            result.append(current.strip())
            current = ''
        else:
            current += ch
    if current.strip():
        result.append(current.strip())
    return result


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    show_listing = '--opcodes' in flags

    if len(args) < 1:
        print(f"Usage: {sys.argv[0]} [--opcodes] <input.asm> [output.mpu]", file=sys.stderr)
        sys.exit(1)

    input_file = args[0]
    if '.' not in os.path.basename(input_file):
        # Prefer hand-written .asm; fall back to compiler-generated .s.
        if os.path.exists(input_file + '.asm'):
            input_file += '.asm'
        else:
            input_file += '.s'
    if len(args) >= 2:
        output_file = args[1]
    else:
        output_file = input_file.rsplit('.', 1)[0] + '.mpu'

    try:
        with open(input_file) as f:
            source = f.read()
    except FileNotFoundError:
        print(f"error: input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    result = assemble(source, listing=show_listing)

    if show_listing:
        binary, listing_lines = result
        print()
        for line in listing_lines:
            print(line)
        print()
    else:
        binary = result

    with open(output_file, 'wb') as f:
        f.write(binary)

    print(f"Assembled {len(binary)} bytes ({len(binary)//4} instructions) -> {output_file}")


if __name__ == '__main__':
    main()
