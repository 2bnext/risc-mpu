; MPU Standard Library
; Linked after compiled code. Provides runtime functions.

; ---- __putc: internal helper. Wait for UART idle, send byte in r1. ----
; Clobbers r4 (status read target). Preserves everything else.
__putc:
.wait:          ld.8    r4, 0xFFFF0004      ; read UART status (busy flag)
                bne.8   r4, #0, .wait       ; loop while busy
                st.8    0xFFFF0000, r1      ; send byte
                ret

; ---- putchar(char c) ----
; Argument: character on stack at [sp+8]
putchar:
                push    r6                          ; save r6
                ld.32   r1, [sp+8]      ; load arg from stack
                call    __putc
                pop     r6                          ; restore r6
                ret

; ---- puts(char *s) ----
; Argument: pointer on stack at [sp+12]
; Prints null-terminated string, appends newline.
puts:
                push    r6                          ; save r6
                push    r5                          ; save r5
                ld.32   r5, [sp+12]     ; load string pointer (8 + 1 retaddr)
.loop:
                ld.8    r1, [r5++]
                beq.8   r1, #0, .newline
                call    __putc
                jmp     .loop
.newline:
                ld.32   r1, #10             ; '\n'
                call    __putc
                pop     r5                          ; restore r5
                pop     r6                          ; restore r6
                ret

; ---- sleep(int ms) ----
; Argument: milliseconds on stack at [sp+8]
; At 12MHz, ~3000 loop iterations per ms.
sleep:
                push    r6                          ; save r6
                ld.32   r3, [sp+8]      ; load count
.loop:          beq.32  r3, #0, .done
                sub.32  r3, #1
                jmp     .loop
.done:
                pop     r6                          ; restore r6
                ret

; ---- setleds(int value) ----
; Argument: LED bits on stack at [sp+8]
; bit 0 = green, bit 1 = red, bit 2 = blue
setleds:
                push    r6                          ; save r6
                ld.32   r1, [sp+8]
                st.8    0xFFFF0008, r1
                pop     r6                          ; restore r6
                ret

; ---- printf(char *fmt, ...) ----
; Variadic printf supporting: %d %s %c %x %%
; After saving r3-r6 (4 saves = 16 bytes):
;   [sp+0]=r3, [sp+4]=r4, [sp+8]=r5, [sp+12]=r6
;   [sp+16]=retaddr, [sp+20]=fmt, [sp+24]=arg0, [sp+28]=arg1, ...
; r5 = format string pointer, r3 = offset to next vararg from sp
printf:
                push    r6
                push    r5
                push    r4
                push    r3
                ld.32   r5, [sp+20]     ; r5 = format string pointer
                ld.32   r3, #24             ; r3 = offset to first vararg

; ---- Main scan loop ----
.scan:
                ld.8    r1, [r5++]          ; next format char
                beq.8   r1, #0, .ret        ; null terminator -> done
                ld.32   r4, #37             ; '%' = 37
                beq.8   r1, r4, .spec       ; format specifier
                ; Regular character: send to UART
                call    __putc
                jmp     .scan

; ---- Format specifier dispatch ----
.spec:
                ld.8    r1, [r5++]          ; specifier char
                beq.8   r1, #0, .ret        ; premature end
                ld.32   r4, #100            ; 'd'
                beq.8   r1, r4, .dec
                ld.32   r4, #115            ; 's'
                beq.8   r1, r4, .str
                ld.32   r4, #99             ; 'c'
                beq.8   r1, r4, .chr
                ld.32   r4, #120            ; 'x'
                beq.8   r1, r4, .hex
                ld.32   r4, #37             ; '%'
                beq.8   r1, r4, .pct
                ; Unknown specifier: print as-is
                call    __putc
                jmp     .scan

; ---- %c: print character ----
.chr:
                ld.32   r1, [sp][r3+0]      ; load char arg
                add.32  r3, #4              ; advance to next arg
                call    __putc
                jmp     .scan

; ---- %%: print literal '%' ----
.pct:
                ld.32   r1, #37
                call    __putc
                jmp     .scan

; ---- %s: print string ----
.str:
                ld.32   r2, [sp][r3+0]      ; load string pointer arg
                add.32  r3, #4              ; advance to next arg
                push    r5                          ; save fmt pointer
.strl:
                ld.8    r1, [r2++]
                beq.8   r1, #0, .strd
                call    __putc
                jmp     .strl
.strd:
                pop     r5                          ; restore fmt pointer
                jmp     .scan

; ---- %d: print signed decimal ----
.dec:
                ld.32   r2, [sp][r3+0]      ; load int arg
                add.32  r3, #4              ; advance to next arg
                push    r5                          ; save fmt pointer
                push    r3                          ; save arg offset
                ld.32   r3, r2                      ; r3 = value (register move!)
                ; Handle negative
                bge.32  r3, #0, .dpos
                ld.32   r1, #45             ; '-'
                call    __putc
                xor.32  r3, #-1             ; negate: ~r3 + 1
                add.32  r3, #1
.dpos:
                ld.32   r5, #__printf_pow10 ; power-of-10 table
                ld.32   r2, #0              ; started flag
.dpow:
                ld.32   r4, [r5]            ; r4 = current power
                beq.32  r4, #0, .dend       ; sentinel -> done
                ld.32   r1, #0              ; digit = 0
.dsub:
                blt.32  r3, r4, .dsd        ; value < power -> done
                sub.32  r3, [r5]            ; value -= power (from table)
                add.32  r1, #1              ; digit++
                jmp     .dsub
.dsd:
                bne.32  r1, #0, .dpr        ; nonzero digit -> print
                bne.32  r2, #0, .dpr        ; already started -> print zero
                jmp     .dnx                ; skip leading zero
.dpr:
                ld.32   r2, #1              ; started = true
                add.32  r1, #48             ; '0' = 48
                call    __putc
.dnx:
                add.32  r5, #4              ; next power in table
                jmp     .dpow
.dend:
                ; If nothing printed (value was 0), print '0'
                bne.32  r2, #0, .ddn
                ld.32   r1, #48
                call    __putc
.ddn:
                pop     r3                          ; restore arg offset
                pop     r5                          ; restore fmt pointer
                jmp     .scan

; ---- %x: print hex ----
.hex:
                ld.32   r2, [sp][r3+0]      ; load int arg
                add.32  r3, #4              ; advance to next arg
                push    r5                          ; save fmt pointer
                push    r3                          ; save arg offset
                ld.32   r3, r2                      ; r3 = value (register move!)
                ld.32   r2, #0              ; started flag
                ld.32   r5, #8              ; nibble count
.xnib:
                beq.32  r5, #0, .xdn
                ; Extract top nibble
                ld.32   r1, r3                      ; r1 = value (register move!)
                shr.32  r1, #28
                and.32  r1, #15
                ; Leading zero check
                bne.32  r1, #0, .xpr
                bne.32  r2, #0, .xpr
                beq.32  r5, #1, .xpr        ; last nibble: must print
                jmp     .xsh
.xpr:
                ld.32   r2, #1              ; started
                ld.32   r4, #10
                blt.32  r1, r4, .xdg
                add.32  r1, #87             ; 'a' - 10 = 87
                jmp     .xsn
.xdg:
                add.32  r1, #48             ; '0'
.xsn:
                call    __putc
.xsh:
                shl.32  r3, #4              ; shift value left for next nibble
                sub.32  r5, #1
                jmp     .xnib
.xdn:
                pop     r3                          ; restore arg offset
                pop     r5                          ; restore fmt pointer
                jmp     .scan

; ---- Return ----
.ret:
                pop     r3                          ; restore r3
                pop     r4                          ; restore r4
                pop     r5                          ; restore r5
                pop     r6                          ; restore r6
                ret

; ---- gpio_set_dir(int mask) ----
; Sets the GPIO direction register at 0xFFFF0014. Bit 1 = output, 0 = input.
gpio_set_dir:
                ld.32   r1, [sp+4]
                st.32   0xFFFF0014, r1
                ret

; ---- gpio_write(int value) ----
; Writes the GPIO output data register at 0xFFFF0010. Only pins configured
; as outputs (via gpio_set_dir) actually drive the pad.
gpio_write:
                ld.32   r1, [sp+4]
                st.32   0xFFFF0010, r1
                ret

; ---- gpio_read() ----
; Returns the live GPIO pin state in r1 (8 bits, zero-extended).
gpio_read:
                ld.32   r1, 0xFFFF0010
                ret

; ---- __i2c_wait: spin until the I2C master finishes the current op ----
; Status reg layout at 0xFFFF001C: [0]=busy, [1]=ack_recv. Clobbers r4.
__i2c_wait:
.wait:          ld.32   r4, 0xFFFF001C
                and.32  r4, #1
                bne.32  r4, #0, .wait
                ret

; ---- i2c_start() — generate START condition ----
i2c_start:
                ld.32   r1, #1              ; cmd[0] = start
                st.32   0xFFFF001C, r1
                call    __i2c_wait
                ret

; ---- i2c_stop() — generate STOP condition ----
i2c_stop:
                ld.32   r1, #2              ; cmd[1] = stop
                st.32   0xFFFF001C, r1
                call    __i2c_wait
                ret

; ---- i2c_write(byte) — shift out one byte; returns 0 on ACK, 1 on NACK ----
i2c_write:
                ld.32   r1, [sp+4]
                st.32   0xFFFF0018, r1      ; load tx data
                ld.32   r1, #4              ; cmd[2] = write
                st.32   0xFFFF001C, r1
                call    __i2c_wait
                ld.32   r1, 0xFFFF001C      ; status
                and.32  r1, #2              ; isolate ack_recv
                ret

; ---- i2c_read(ack) — shift in one byte; ack=0 for ACK, 1 for NACK ----
i2c_read:
                ld.32   r1, [sp+4]      ; ack arg
                and.32  r1, #1
                shl.32  r1, #4              ; -> bit 4 (ack_send)
                or.32   r1, #8              ; cmd[3] = read
                st.32   0xFFFF001C, r1
                call    __i2c_wait
                ld.32   r1, 0xFFFF0018      ; rx data
                ret

; ---- adc_read() — return latest 12-bit sigma-delta ADC sample ----
adc_read:
                ld.32   r1, 0xFFFF0020
                ret

; ---- adc_readf() — return ADC sample as float in range -1.0 .. +1.0 ----
; Maps 0→-1.0, 2048→0.0, 4095→+1.0 (approximately).
; Computed as: (raw - 2048) / 2048.0
adc_readf:
                push    r6
                ld.32   r1, 0xFFFF0020      ; raw 0..4095
                sub.32  r1, #2048           ; centered: -2048..+2047
                push    r1
                call    itof                ; float(centered)
                add.32  sp, #4
                ld.32   r6, r1              ; save numerator
                ldi     r1, #1157627904     ; 2048.0 as IEEE 754 (0x45000000)
                push    r1                  ; push b (denominator) first
                push    r6                  ; push a (numerator) second
                call    fdiv                ; fdiv(a=[sp+4], b=[sp+8])
                add.32  sp, #8
                pop     r6
                ret

; ---- __mul(a, b): unsigned multiply ----
; Shift-add, up to 32 iterations (bails out when multiplier is zero).
; Args: a at [sp+4], b at [sp+8]. Result in r1.
__mul:
                ld.32   r1, [sp+4]      ; r1 = a (shifts left)
                ld.32   r2, [sp+8]      ; r2 = b (shifts right)
                ld.32   r3, #0              ; accumulator
.loop:
                beq.32  r2, #0, .done
                ld.32   r4, r2                      ; test LSB of b
                and.32  r4, #1
                beq.32  r4, #0, .skip
                push    r1                          ; acc += a (reg-reg via stack)
                add.32  r3, [sp]
                add.32  sp, #4
.skip:
                shl.32  r1, #1
                shr.32  r2, #1
                jmp     .loop
.done:
                ld.32   r1, r3
                ret

; ---- __div(a, b) / __mod(a, b): unsigned divide and modulo ----
; Shift-subtract, 32 iterations. Args: a at [sp+4], b at [sp+8].
; __div returns a/b in r1; __mod returns a%b in r1.
; Clobbers r2-r5; no caller-saves needed (caller pushed args).
__div:
                call    __divmod
                ld.32   r1, r3                      ; quotient
                ret
__mod:
                call    __divmod
                ld.32   r1, r4                      ; remainder
                ret

; Internal: returns quotient in r3, remainder in r4.
; After call here, retaddr is at [sp+0], caller's retaddr at [sp+4],
; a at [sp+8], b at [sp+12].
__divmod:
                ld.32   r1, [sp+8]      ; r1 = a (dividend, shifts out)
                ld.32   r2, [sp+12]     ; r2 = b (divisor)
                ld.32   r3, #0              ; quotient
                ld.32   r4, #0              ; remainder
                ld.32   r5, #32             ; bit counter
.loop:
                beq.32  r5, #0, .done
                shl.32  r4, #1              ; remainder <<= 1
                bge.32  r1, #0, .noset      ; top bit of r1 clear?
                or.32   r4, #1              ; else set LSB of remainder
.noset:
                shl.32  r1, #1              ; dividend <<= 1
                shl.32  r3, #1              ; quotient <<= 1
                blt.32  r4, r2, .nosub      ; remainder < divisor?
                push    r2                          ; reg-reg sub via stack
                sub.32  r4, [sp]              ; r4 -= r2
                add.32  sp, #4
                or.32   r3, #1              ; quotient |= 1
.nosub:
                sub.32  r5, #1
                jmp     .loop
.done:
                ret

; ===========================================================================
; Signed integer math
; ===========================================================================

; ---- __smul(a, b): signed multiply ----
; Args: a at [sp+4], b at [sp+8]. Result (signed) in r1.
__smul:
                push    r6
                ld.32   r1, [sp+8]
                ld.32   r2, [sp+12]
                clr     r6
                bge.32  r1, #0, .apos
                xor.32  r1, #-1
                add.32  r1, #1
                add.32  r6, #1
.apos:          bge.32  r2, #0, .bpos
                xor.32  r2, #-1
                add.32  r2, #1
                add.32  r6, #1
.bpos:          push    r2
                push    r1
                call    __mul
                add.32  sp, #8
                and.32  r6, #1
                beq.32  r6, #0, .done
                xor.32  r1, #-1
                add.32  r1, #1
.done:          pop     r6
                ret

; ---- __sdiv(a, b): signed divide (truncates toward zero) ----
; Args: a at [sp+4], b at [sp+8]. Result in r1.
__sdiv:
                push    r6
                ld.32   r1, [sp+8]
                ld.32   r2, [sp+12]
                clr     r6
                bge.32  r1, #0, .apos
                xor.32  r1, #-1
                add.32  r1, #1
                add.32  r6, #1
.apos:          bge.32  r2, #0, .bpos
                xor.32  r2, #-1
                add.32  r2, #1
                add.32  r6, #1
.bpos:          push    r2
                push    r1
                call    __div
                add.32  sp, #8
                and.32  r6, #1
                beq.32  r6, #0, .done
                xor.32  r1, #-1
                add.32  r1, #1
.done:          pop     r6
                ret

; ---- __smod(a, b): signed modulo (sign follows dividend) ----
; Args: a at [sp+4], b at [sp+8]. Result in r1.
__smod:
                push    r6
                ld.32   r1, [sp+8]
                ld.32   r2, [sp+12]
                clr     r6
                bge.32  r1, #0, .apos
                xor.32  r1, #-1
                add.32  r1, #1
                add.32  r6, #1
.apos:          bge.32  r2, #0, .bpos
                xor.32  r2, #-1
                add.32  r2, #1
.bpos:          push    r2
                push    r1
                call    __mod
                add.32  sp, #8
                beq.32  r6, #0, .done
                xor.32  r1, #-1
                add.32  r1, #1
.done:          pop     r6
                ret

; ---- __sar(x, n): arithmetic shift right ----
; Args (BASIC/Pascal calling convention: caller pushes x, then n):
;   [sp+4] = n, [sp+8] = x.  Result in r1.
; Now a thin wrapper around the native ASR opcode.
__sar:
                ld.32   r1, [sp+8]          ; x
                ld.32   r2, [sp+4]          ; n
                push    r2
                asr.32  r1, [sp]
                add.32  sp, #4
                ret

; ---- abs(x): absolute value ----
abs:
                ld.32   r1, [sp+4]
                bge.32  r1, #0, .done
                xor.32  r1, #-1
                add.32  r1, #1
.done:          ret

; ---- min(a, b) / max(a, b): signed min/max ----
min:
                ld.32   r1, [sp+4]
                ld.32   r2, [sp+8]
                ble.32  r1, r2, .done
                ld.32   r1, r2
.done:          ret
max:
                ld.32   r1, [sp+4]
                ld.32   r2, [sp+8]
                bge.32  r1, r2, .done
                ld.32   r1, r2
.done:          ret

; ---- clamp(x, lo, hi): signed clamp ----
clamp:
                ld.32   r1, [sp+4]
                ld.32   r2, [sp+8]
                ld.32   r3, [sp+12]
                bge.32  r1, r2, .above
                ld.32   r1, r2
                ret
.above:         ble.32  r1, r3, .done
                ld.32   r1, r3
.done:          ret

; ---- clz(x): count leading zeros (0..32) ----
clz:
                ld.32   r2, [sp+4]
                clr     r1
                beq.32  r2, #0, .all
.loop:          blt.32  r2, #0, .done
                shl.32  r2, #1
                add.32  r1, #1
                jmp     .loop
.all:           ld.32   r1, #32
.done:          ret

; ---- isqrt(x): integer square root (unsigned) ----
; Restoring bit-by-bit; no multiply needed.
isqrt:
                push    r5
                ld.32   r3, [sp+8]
                clr     r1
                clr     r2
                ld.32   r5, #16
.loop:          beq.32  r5, #0, .done
                shl.32  r2, #2
                ld.32   r4, r3
                shr.32  r4, #30
                push    r4
                or.32   r2, [sp]
                add.32  sp, #4
                shl.32  r3, #2
                shl.32  r1, #1
                ld.32   r4, r1
                shl.32  r4, #1
                or.32   r4, #1
                blt.32  r2, r4, .nosub
                push    r4
                sub.32  r2, [sp]
                add.32  sp, #4
                or.32   r1, #1
.nosub:         sub.32  r5, #1
                jmp     .loop
.done:          pop     r5
                ret

; ===========================================================================
; Geometric / trigonometric functions (soft-float, NOT reentrant)
; ===========================================================================
; All take and return IEEE 754 floats in r1.
; sin/cos use a 7th-order polynomial (Bhaskara-style) approximation
; over [-pi, pi]. Accuracy ~0.001 for most inputs.

; ---- Constants (IEEE 754 bit patterns) ----
_f_pi:       db 0xDB, 0x0F, 0x49, 0x40  ; 3.14159265
_f_neg_pi:   db 0xDB, 0x0F, 0x49, 0xC0  ; -3.14159265
_f_two_pi:   db 0xDB, 0x0F, 0xC9, 0x40  ; 6.28318530
_f_half_pi:  db 0xDB, 0x0F, 0xC9, 0x3F  ; 1.57079632
_f_one:      db 0x00, 0x00, 0x80, 0x3F  ; 1.0
_f_neg_one:  db 0x00, 0x00, 0x80, 0xBF  ; -1.0
_f_two:      db 0x00, 0x00, 0x00, 0x40  ; 2.0
_f_four:     db 0x00, 0x00, 0x80, 0x40  ; 4.0
_f_zero:     db 0x00, 0x00, 0x00, 0x00  ; 0.0
_f_deg2rad:  db 0x35, 0xFA, 0x8E, 0x3C  ; 0.01745329 = pi/180
_f_rad2deg:  db 0xE1, 0x2E, 0x65, 0x42  ; 57.2957795 = 180/pi

; ---- fabs(x): float absolute value ----
; Clears the sign bit.
fabs:
                ld.32   r1, [sp+4]
                ldi     r2, #0x7FFFFFFF
                push    r2
                and.32  r1, [sp]
                add.32  sp, #4
                ret

; ---- fneg(x): float negate ----
; Flips the sign bit.
fneg:
                ld.32   r1, [sp+4]
                ldi     r2, #0x80000000
                push    r2
                xor.32  r1, [sp]
                add.32  sp, #4
                ret

; ---- fsqrt(x): float square root ----
; Uses Newton's method: y = y - (y*y - x) / (2*y), seeded with isqrt.
; 4 iterations gives ~6 digits of accuracy for normal floats.
fsqrt:
                push    r6
                push    r5
                ld.32   r6, [sp+12]         ; x
                ; If x <= 0, return 0
                ld.32   r1, _f_zero
                push    r1
                push    r6
                call    fcmp
                add.32  sp, #8
                ble.32  r1, #0, .retzero
                ; Seed: convert to int, isqrt, convert back.
                ; The seed must be parked in a callee-saved register (r5)
                ; BEFORE we call fcmp — fcmp returns its result in r1 and
                ; would otherwise clobber the seed.
                push    r6
                call    ftoi
                add.32  sp, #4
                push    r1
                call    isqrt
                add.32  sp, #4
                push    r1
                call    itof
                add.32  sp, #4
                ld.32   r5, r1              ; r5 = seed (safe across fcmp)
                ; If seed is 0 (very small x), use x itself as seed.
                ld.32   r2, _f_zero
                push    r2
                push    r5
                call    fcmp
                add.32  sp, #8
                bne.32  r1, #0, .has_seed
                ld.32   r5, r6              ; use x as seed
.has_seed:      ; r5 = y (current estimate), r6 = x (unchanged since entry).
                ; 2 Newton iterations: y = (y + x/y) / 2.
                ; Unrolled because fdiv/fadd clobber r4 — we can't use it
                ; as a loop counter across the body.
                ; ---- Iteration 1 ----
                push    r5                  ; b = y
                push    r6                  ; a = x
                call    fdiv                ; x / y
                add.32  sp, #8
                push    r1                  ; b = x/y
                push    r5                  ; a = y
                call    fadd                ; y + x/y
                add.32  sp, #8
                ld.32   r2, _f_two
                push    r2                  ; b = 2.0
                push    r1                  ; a = (y + x/y)
                call    fdiv                ; / 2
                add.32  sp, #8
                ld.32   r5, r1              ; y = new estimate
                ; ---- Iteration 2 ----
                push    r5                  ; b = y
                push    r6                  ; a = x
                call    fdiv                ; x / y
                add.32  sp, #8
                push    r1                  ; b = x/y
                push    r5                  ; a = y
                call    fadd                ; y + x/y
                add.32  sp, #8
                ld.32   r2, _f_two
                push    r2                  ; b = 2.0
                push    r1                  ; a = (y + x/y)
                call    fdiv                ; / 2
                add.32  sp, #8
                ld.32   r5, r1              ; y = final estimate
                ld.32   r1, r5
                pop     r5
                pop     r6
                ret
.retzero:       ld.32   r1, _f_zero
                pop     r5
                pop     r6
                ret

; ---- fsin(x): sine approximation ----
; Uses Bhaskara I's formula adapted for polynomials:
;   sin(x) ≈ 16x(pi - x) / (5*pi^2 - 4x(pi - x))
; Valid for 0 <= x <= pi. Extended to full range via symmetry.
; Input: x in radians (any range). Output: float in [-1, 1].
fsin:
                push    r6
                push    r5
                ld.32   r6, [sp+12]         ; x
                ; Reduce to [0, 2*pi] by computing x mod (2*pi)
                ; x = x - floor(x / (2*pi)) * (2*pi)
                ld.32   r1, _f_two_pi
                push    r1                  ; b = 2*pi
                push    r6                  ; a = x
                call    fdiv
                add.32  sp, #8
                push    r1
                call    ftoi                ; floor
                add.32  sp, #4
                push    r1
                call    itof
                add.32  sp, #4
                ld.32   r2, _f_two_pi
                push    r2
                push    r1
                call    fmul                ; floor * 2*pi
                add.32  sp, #8
                push    r1
                push    r6
                call    fsub                ; x - floor * 2*pi
                add.32  sp, #8
                ld.32   r6, r1              ; r6 = x in [0, 2*pi) approx
                ; If x > pi, use sin(x) = -sin(x - pi)
                clr     r5                  ; r5 = negate flag
                ld.32   r1, _f_pi
                push    r1
                push    r6
                call    fcmp
                add.32  sp, #8
                ble.32  r1, #0, .in_range
                ; x > pi: x = x - pi, negate result
                ld.32   r1, _f_pi
                push    r1
                push    r6
                call    fsub
                add.32  sp, #8
                ld.32   r6, r1
                ld.32   r5, #1              ; negate
.in_range:      ; Now x in [0, pi]. Compute Bhaskara:
                ; num = 16 * x * (pi - x)
                ; den = 5*pi^2 - 4*x*(pi - x)
                ; sin ≈ num / den
                ; pi - x
                push    r6
                ld.32   r1, _f_pi
                push    r1
                call    fsub                ; pi - x
                add.32  sp, #8
                ld.32   r4, r1              ; r4 = pi - x (saved in r4, will be clobbered by fmul)
                ; x * (pi - x)
                st.32   _gm_tmp1, r4        ; save pi-x
                push    r4
                push    r6
                call    fmul                ; x * (pi - x)
                add.32  sp, #8
                st.32   _gm_tmp2, r1        ; save x*(pi-x)
                ; 16 * x * (pi-x)
                ldi     r2, #1098907648     ; 16.0 = 0x41800000
                push    r2
                push    r1
                call    fmul
                add.32  sp, #8
                st.32   _gm_tmp3, r1        ; num = 16*x*(pi-x)
                ; 5 * pi^2
                ld.32   r1, _f_pi
                push    r1
                push    r1
                call    fmul                ; pi^2
                add.32  sp, #8
                ldi     r2, #1084227584     ; 5.0 = 0x40A00000
                push    r2
                push    r1
                call    fmul                ; 5*pi^2
                add.32  sp, #8
                st.32   _gm_tmp1, r1        ; save 5*pi^2
                ; 4 * x * (pi-x)
                ld.32   r1, _gm_tmp2        ; x*(pi-x)
                ld.32   r2, _f_four
                push    r2
                push    r1
                call    fmul
                add.32  sp, #8
                ; den = 5*pi^2 - 4*x*(pi-x)
                push    r1
                ld.32   r1, _gm_tmp1
                push    r1
                call    fsub
                add.32  sp, #8
                ; num / den
                push    r1                  ; den
                ld.32   r1, _gm_tmp3
                push    r1                  ; num
                call    fdiv
                add.32  sp, #8
                ; Apply negate if needed
                beq.32  r5, #0, .sin_done
                push    r1
                call    fneg
                add.32  sp, #4
.sin_done:      pop     r5
                pop     r6
                ret

; ---- fcos(x): cosine ----
; cos(x) = sin(x + pi/2)
fcos:
                ld.32   r1, _f_half_pi
                push    r1
                ld.32   r1, [sp+8]          ; x
                push    r1
                call    fadd                ; x + pi/2
                add.32  sp, #8
                push    r1
                call    fsin
                add.32  sp, #4
                ret

; ---- fatan2(y, x): two-argument arctangent ----
; Polynomial approximation. Returns angle in radians [-pi, pi].
; Uses: atan(z) ≈ z*(1 - 0.2447*z^2) for |z| <= 1
; with quadrant correction for the full atan2 range.
fatan2:
                push    r6
                push    r5
                ld.32   r6, [sp+12]         ; y (a = first arg)
                ld.32   r5, [sp+16]         ; x (b = second arg)
                ; Compute |x| and |y| to pick the right octant
                push    r6
                call    fabs
                add.32  sp, #4
                st.32   _gm_tmp1, r1        ; |y|
                push    r5
                call    fabs
                add.32  sp, #4
                st.32   _gm_tmp2, r1        ; |x|
                ; If |x| >= |y|: z = y/x, base angle = 0
                ; If |y| > |x|:  z = x/y, base angle = pi/2 - atan(z)
                ld.32   r1, _gm_tmp2        ; |x|
                ld.32   r2, _gm_tmp1        ; |y|
                push    r2
                push    r1
                call    fcmp
                add.32  sp, #8
                blt.32  r1, #0, .y_bigger
                ; |x| >= |y|: z = y / x
                push    r5                  ; x
                push    r6                  ; y
                call    fdiv
                add.32  sp, #8
                st.32   _gm_tmp3, r1        ; z = y/x
                ; atan(z) ≈ z / (1 + 0.28125*z^2). Max error ~1% over
                ; |z| <= 1, and hits pi/4 much closer at z=1 than the
                ; truncated Taylor series does.
                push    r1
                push    r1
                call    fmul                ; z^2
                add.32  sp, #8
                ldi     r2, #1049624576     ; 0.28125 = 0x3E900000
                push    r2
                push    r1
                call    fmul                ; 0.28125 * z^2
                add.32  sp, #8
                ld.32   r2, _f_one
                push    r2
                push    r1
                call    fadd                ; 1 + 0.28125*z^2
                add.32  sp, #8
                push    r1                  ; b = denominator
                ld.32   r1, _gm_tmp3
                push    r1                  ; a = z
                call    fdiv                ; z / (1 + 0.28125*z^2)
                add.32  sp, #8
                jmp     .atan_done
.y_bigger:      ; |y| > |x|: z = x / y
                push    r6                  ; y
                push    r5                  ; x
                call    fdiv
                add.32  sp, #8
                st.32   _gm_tmp3, r1        ; z = x/y
                ; atan(z) ≈ z / (1 + 0.28125*z^2)
                push    r1
                push    r1
                call    fmul                ; z^2
                add.32  sp, #8
                ldi     r2, #1049624576     ; 0.28125
                push    r2
                push    r1
                call    fmul                ; 0.28125 * z^2
                add.32  sp, #8
                ld.32   r2, _f_one
                push    r2
                push    r1
                call    fadd                ; 1 + 0.28125*z^2
                add.32  sp, #8
                push    r1                  ; b = denominator
                ld.32   r1, _gm_tmp3
                push    r1                  ; a = z
                call    fdiv                ; atan(z) ≈ z / (1 + ...)
                add.32  sp, #8
                ; result = pi/2 - atan(z) with sign of y
                push    r1
                ld.32   r1, _f_half_pi
                push    r1
                call    fsub                ; pi/2 - atan(z)
                add.32  sp, #8
                ; Copy sign of y
                ld.32   r2, r6
                shr.32  r2, #31             ; sign bit of y
                beq.32  r2, #0, .atan_done
                push    r1
                call    fneg
                add.32  sp, #4
.atan_done:     ; r1 = computed angle in the "right-half-plane" sense.
                ; If x >= 0 we're done. If x < 0 we shift by ±pi based on
                ; sign of y. We check signs DIRECTLY on r5/r6 (no fcmp) so
                ; r1 doesn't get clobbered.
                ld.32   r2, r5
                shr.32  r2, #31             ; bit 31 of x
                beq.32  r2, #0, .final      ; x >= 0 — no adjustment
                ; x < 0
                ld.32   r2, r6
                shr.32  r2, #31             ; bit 31 of y
                bne.32  r2, #0, .subpi      ; y < 0 → subtract pi
                ; y >= 0 → angle + pi
                ld.32   r2, _f_pi
                push    r2                  ; b = pi
                push    r1                  ; a = angle
                call    fadd                ; angle + pi
                add.32  sp, #8
                jmp     .final
.subpi:         ld.32   r2, _f_pi
                push    r2                  ; b = pi
                push    r1                  ; a = angle
                call    fsub                ; angle - pi
                add.32  sp, #8
.final:         pop     r5
                pop     r6
                ret

; ---- ftan(x): tangent = sin(x) / cos(x) ----
; Uses the stack (not _gm_tmp1) to save sin(x) across the fcos call,
; because fcos → fsin internally clobbers _gm_tmp1.
ftan:
                ld.32   r1, [sp+4]          ; x
                push    r1
                call    fsin
                add.32  sp, #4
                push    r1                  ; save sin(x) on stack
                ld.32   r1, [sp+8]          ; x (shifted by the push above)
                push    r1
                call    fcos
                add.32  sp, #4
                ; r1 = cos(x); saved sin(x) is at [sp]
                push    r1                  ; b = cos(x)
                ld.32   r1, [sp+4]          ; a = sin(x) (from saved slot)
                push    r1
                call    fdiv                ; sin/cos
                add.32  sp, #8              ; drop fdiv args
                add.32  sp, #4              ; drop saved sin(x)
                ret

; ---- fatan(x): single-arg arctangent = fatan2(x, 1.0) ----
fatan:
                ld.32   r1, _f_one
                push    r1                  ; b = 1.0
                ld.32   r1, [sp+8]          ; x (slid down by one push)
                push    r1                  ; a = x
                call    fatan2
                add.32  sp, #8
                ret

; ---- fasin(x): arcsine = fatan2(x, sqrt(1 - x*x)) ----
; Input: x in [-1, 1]. Output: angle in [-pi/2, pi/2].
fasin:
                ld.32   r1, [sp+4]          ; x
                push    r1
                push    r1
                call    fmul                ; x*x
                add.32  sp, #8
                push    r1                  ; b = x*x
                ld.32   r1, _f_one
                push    r1                  ; a = 1.0
                call    fsub                ; 1 - x*x
                add.32  sp, #8
                push    r1
                call    fsqrt               ; sqrt(1 - x*x)
                add.32  sp, #4
                push    r1                  ; b = sqrt(1 - x*x)
                ld.32   r1, [sp+8]          ; x
                push    r1                  ; a = x
                call    fatan2
                add.32  sp, #8
                ret

; ---- facos(x): arccosine = pi/2 - fasin(x) ----
facos:
                ld.32   r1, [sp+4]          ; x
                push    r1
                call    fasin
                add.32  sp, #4
                push    r1                  ; b = fasin(x)
                ld.32   r1, _f_half_pi
                push    r1                  ; a = pi/2
                call    fsub                ; pi/2 - fasin(x)
                add.32  sp, #8
                ret

; ---- fhypot(x, y): sqrt(x*x + y*y) ----
fhypot:
                ld.32   r1, [sp+4]          ; x
                push    r1
                push    r1
                call    fmul                ; x*x
                add.32  sp, #8
                st.32   _gm_tmp1, r1
                ld.32   r1, [sp+8]          ; y
                push    r1
                push    r1
                call    fmul                ; y*y
                add.32  sp, #8
                push    r1                  ; b = y*y
                ld.32   r1, _gm_tmp1
                push    r1                  ; a = x*x
                call    fadd                ; x*x + y*y
                add.32  sp, #8
                push    r1
                call    fsqrt
                add.32  sp, #4
                ret

; ---- fdeg2rad(x): degrees to radians = x * (pi/180) ----
fdeg2rad:
                ld.32   r1, _f_deg2rad
                push    r1                  ; b = pi/180
                ld.32   r1, [sp+8]          ; x
                push    r1                  ; a = x
                call    fmul
                add.32  sp, #8
                ret

; ---- frad2deg(x): radians to degrees = x * (180/pi) ----
frad2deg:
                ld.32   r1, _f_rad2deg
                push    r1                  ; b = 180/pi
                ld.32   r1, [sp+8]          ; x
                push    r1                  ; a = x
                call    fmul
                add.32  sp, #8
                ret

; ---- fmin(a, b): float minimum ----
fmin:
                ld.32   r1, [sp+8]          ; b
                push    r1
                ld.32   r1, [sp+8]          ; a (was sp+4, shifted by push)
                push    r1
                call    fcmp
                add.32  sp, #8
                bgt.32  r1, #0, .fmin_retb  ; a > b → return b
                ld.32   r1, [sp+4]          ; return a
                ret
.fmin_retb:     ld.32   r1, [sp+8]          ; return b
                ret

; ---- fmax(a, b): float maximum ----
fmax:
                ld.32   r1, [sp+8]          ; b
                push    r1
                ld.32   r1, [sp+8]          ; a
                push    r1
                call    fcmp
                add.32  sp, #8
                blt.32  r1, #0, .fmax_retb  ; a < b → return b
                ld.32   r1, [sp+4]          ; return a
                ret
.fmax_retb:     ld.32   r1, [sp+8]          ; return b
                ret

; ---- fclamp(x, lo, hi): x clamped to [lo, hi] ----
; Equivalent to fmin(fmax(x, lo), hi)
fclamp:
                ld.32   r1, [sp+8]          ; lo
                push    r1
                ld.32   r1, [sp+8]          ; x (was sp+4, shifted)
                push    r1
                call    fmax
                add.32  sp, #8
                ld.32   r2, [sp+12]         ; hi
                push    r2
                push    r1
                call    fmin
                add.32  sp, #8
                ret

; ---- fsign(x): -1.0, 0.0, or 1.0 ----
fsign:
                ld.32   r1, _f_zero
                push    r1                  ; b = 0
                ld.32   r1, [sp+8]          ; x
                push    r1                  ; a = x
                call    fcmp
                add.32  sp, #8
                bgt.32  r1, #0, .fsign_pos
                blt.32  r1, #0, .fsign_neg
                ld.32   r1, _f_zero
                ret
.fsign_pos:     ld.32   r1, _f_one
                ret
.fsign_neg:     ld.32   r1, _f_neg_one
                ret

; ---- flerp(a, b, t): linear interpolation = a + t*(b-a) ----
flerp:
                ; Compute b - a
                ld.32   r1, [sp+4]          ; a
                push    r1                  ; fsub b = a
                ld.32   r1, [sp+12]         ; b (was sp+8, shifted)
                push    r1                  ; fsub a = b
                call    fsub                ; b - a
                add.32  sp, #8
                ; Multiply by t
                ld.32   r2, [sp+12]         ; t
                push    r2                  ; fmul b = t
                push    r1                  ; fmul a = (b - a)
                call    fmul                ; t * (b - a)
                add.32  sp, #8
                ; Add a
                push    r1                  ; fadd b = t*(b-a)
                ld.32   r2, [sp+8]          ; a (was sp+4, shifted)
                push    r2                  ; fadd a = a
                call    fadd                ; a + t*(b-a)
                add.32  sp, #8
                ret

; ---- ffloor(x): floor (largest integer <= x) ----
; Implementation: trunc toward 0 via ftoi/itof. If original x was negative
; and not an exact integer, subtract 1 to round toward -infinity.
ffloor:
                push    r6
                ld.32   r6, [sp+8]          ; x (saved in callee-saved r6)
                push    r6
                call    ftoi
                add.32  sp, #4
                push    r1
                call    itof                ; r1 = trunc(x) as float
                add.32  sp, #4
                st.32   _gm_tmp1, r1        ; save trunc(x)
                push    r1                  ; b = trunc(x)
                push    r6                  ; a = x
                call    fcmp
                add.32  sp, #8
                bge.32  r1, #0, .ffl_done   ; x >= trunc → return trunc
                ld.32   r1, _f_one
                push    r1                  ; b = 1.0
                ld.32   r1, _gm_tmp1
                push    r1                  ; a = trunc
                call    fsub                ; trunc - 1
                add.32  sp, #8
                pop     r6
                ret
.ffl_done:      ld.32   r1, _gm_tmp1
                pop     r6
                ret

; ---- fceil(x): ceiling (smallest integer >= x) = -floor(-x) ----
fceil:
                ld.32   r1, [sp+4]          ; x
                push    r1
                call    fneg                ; -x
                add.32  sp, #4
                push    r1
                call    ffloor              ; floor(-x)
                add.32  sp, #4
                push    r1
                call    fneg                ; -floor(-x)
                add.32  sp, #4
                ret

; Geometric scratch globals (NOT reentrant)
_gm_tmp1: db 0,0,0,0
_gm_tmp2: db 0,0,0,0
_gm_tmp3: db 0,0,0,0

; ===========================================================================
; IEEE 754 single-precision soft-float (globals-based, NOT reentrant)
; ===========================================================================
;
; Format: 1 sign + 8 exponent (bias 127) + 23 mantissa (implicit leading 1)
;   Bit 31      = sign (0 = positive, 1 = negative)
;   Bits 30:23  = exponent (0 = zero/denorm, 255 = inf/NaN)
;   Bits 22:0   = mantissa (the fractional part; leading 1 is implicit)
;
; Floats are passed and returned in r1 as 32-bit words — the same register
; as integers. The caller must know whether a value is float or int.
;
; Denormals are flushed to zero. Inf/NaN are not handled — results that
; overflow saturate to the largest finite value. This is adequate for sensor
; math but not for general numerical work.
;
; Internal convention for unpacked floats:
;   r1 = sign (0 or 1)
;   r2 = exponent (biased, 0..254)
;   r3 = mantissa with implicit bit restored (24 bits: bit 23 = leading 1)


; ---- __funpack: unpack float in r1 → r1=sign, r2=exp, r3=mantissa ----
; On return: r1=sign (0/1), r2=biased exponent, r3=mantissa with bit 23 set.
; If the number is zero (exp==0), r3=0.
__funpack:
                ld.32   r3, r1
                shr.32  r1, #31
                ld.32   r2, r3
                shr.32  r2, #23
                and.32  r2, #0xFF
                shl.32  r3, #9
                shr.32  r3, #9
                beq.32  r2, #0, .zero
                ldi     r4, #0x800000
                push    r4
                or.32   r3, [sp]
                add.32  sp, #4
                ret
.zero:          clr     r3
                ret

; ---- __fpack: pack sign=r1, exp=r2, mant=r3 → r1=float ----
__fpack:
                beq.32  r3, #0, .retzero
                bge.32  r2, #1, .notunder
                clr     r1
                ret
.notunder:      ld.32   r4, #254
                ble.32  r2, r4, .notover
                ld.32   r2, #254
                ldi     r3, #0xFFFFFF
.notover:       ldi     r4, #0x7FFFFF
                push    r4
                and.32  r3, [sp]
                add.32  sp, #4
                shl.32  r1, #31
                shl.32  r2, #23
                push    r2
                or.32   r1, [sp]
                add.32  sp, #4
                push    r3
                or.32   r1, [sp]
                add.32  sp, #4
                ret
.retzero:       clr     r1
                ret

; ---- __fnorm: normalise mantissa in r3, adjusting exponent in r2 ----
__fnorm:
                beq.32  r3, #0, .done
.loop:          ldi     r4, #0x800000
                push    r4
                ld.32   r4, r3
                and.32  r4, [sp]
                add.32  sp, #4
                bne.32  r4, #0, .done
                shl.32  r3, #1
                sub.32  r2, #1
                bgt.32  r2, #0, .loop
                clr     r3
.done:          ret

; ---- fadd(a, b): float addition (uses globals, NOT reentrant) ----
fadd:
                push    r6
                push    r5
                ld.32   r1, [sp+12]
                call    __funpack
                st.32   _fa_as, r1
                st.32   _fa_ae, r2
                st.32   _fa_am, r3
                ld.32   r1, [sp+16]
                call    __funpack
                ld.32   r5, r2
                ld.32   r6, r3
                ld.32   r4, _fa_am
                beq.32  r4, #0, .ret_b
                beq.32  r6, #0, .ret_a
                ld.32   r4, _fa_ae
                push    r5
                sub.32  r4, [sp]
                add.32  sp, #4
                bge.32  r4, #0, .a_bigger
                xor.32  r4, #-1
                add.32  r4, #1
                ld.32   r3, _fa_am
                push    r4
                shr.32  r3, [sp]
                add.32  sp, #4
                st.32   _fa_am, r3
                st.32   _fa_ae, r5
                jmp     .aligned
.a_bigger:      beq.32  r4, #0, .aligned
                push    r4
                shr.32  r6, [sp]
                add.32  sp, #4
.aligned:       ld.32   r4, _fa_as
                push    r1
                push    r4
                ld.32   r4, [sp]
                sub.32  r4, [sp+4]
                add.32  sp, #8
                bne.32  r4, #0, .diff_sign
                ld.32   r3, _fa_am
                push    r6
                add.32  r3, [sp]
                add.32  sp, #4
                ldi     r4, #0x1000000
                blt.32  r3, r4, .no_carry
                shr.32  r3, #1
                ld.32   r2, _fa_ae
                add.32  r2, #1
                st.32   _fa_ae, r2
.no_carry:      ld.32   r1, _fa_as
                ld.32   r2, _fa_ae
                call    __fpack
                pop     r5
                pop     r6
                ret
.diff_sign:     ld.32   r3, _fa_am
                push    r6
                sub.32  r3, [sp]
                add.32  sp, #4
                bgt.32  r3, #0, .a_larger
                beq.32  r3, #0, .ret_zero
                xor.32  r3, #-1
                add.32  r3, #1
                ld.32   r2, _fa_ae
                call    __fnorm
                call    __fpack
                pop     r5
                pop     r6
                ret
.a_larger:      ld.32   r1, _fa_as
                ld.32   r2, _fa_ae
                call    __fnorm
                call    __fpack
                pop     r5
                pop     r6
                ret
.ret_zero:      clr     r1
                pop     r5
                pop     r6
                ret
.ret_b:         ld.32   r1, [sp+16]
                pop     r5
                pop     r6
                ret
.ret_a:         ld.32   r1, [sp+12]
                pop     r5
                pop     r6
                ret

; ---- fsub(a, b): flip sign of b, call fadd ----
fsub:
                ld.32   r1, [sp+8]
                ldi     r2, #0x80000000
                push    r2
                xor.32  r1, [sp]
                add.32  sp, #4
                push    r1
                ld.32   r1, [sp+8]
                push    r1
                call    fadd
                add.32  sp, #8
                ret

; ---- fmul(a, b): float multiplication (uses globals, NOT reentrant) ----
fmul:
                push    r6
                push    r5
                ld.32   r1, [sp+12]
                call    __funpack
                st.32   _fm_as, r1
                st.32   _fm_ae, r2
                st.32   _fm_am, r3
                ld.32   r1, [sp+16]
                call    __funpack
                ld.32   r4, _fm_as
                push    r1
                xor.32  r4, [sp]
                add.32  sp, #4
                st.32   _fm_rs, r4
                ld.32   r4, _fm_am
                beq.32  r4, #0, .retzero
                beq.32  r3, #0, .retzero
                ld.32   r5, _fm_ae
                push    r2
                add.32  r5, [sp]
                add.32  sp, #4
                sub.32  r5, #127
                st.32   _fm_re, r5
                ; Split mantissas into hi12/lo12
                ld.32   r6, _fm_am
                ld.32   r1, r6
                shr.32  r1, #12
                st.32   _fm_ah, r1
                ld.32   r1, r6
                and.32  r1, #0xFFF
                st.32   _fm_al, r1
                ld.32   r1, r3
                shr.32  r1, #12
                st.32   _fm_bh, r1
                and.32  r3, #0xFFF
                st.32   _fm_bl, r3
                ; aH * bH
                ld.32   r1, _fm_bh
                push    r1
                ld.32   r1, _fm_ah
                push    r1
                call    __mul
                add.32  sp, #8
                ld.32   r6, r1
                ; aH * bL
                ld.32   r1, _fm_bl
                push    r1
                ld.32   r1, _fm_ah
                push    r1
                call    __mul
                add.32  sp, #8
                ld.32   r5, r1
                ; aL * bH
                ld.32   r1, _fm_bh
                push    r1
                ld.32   r1, _fm_al
                push    r1
                call    __mul
                add.32  sp, #8
                push    r5
                add.32  r1, [sp]
                add.32  sp, #4
                shr.32  r1, #12
                push    r1
                add.32  r6, [sp]
                add.32  sp, #4
                ; r6 has bits [47:24] of the 48-bit product.
                ; We need bits [47:23] (one more), so shift left by 1.
                ld.32   r3, r6
                shl.32  r3, #1
                ; Also pick up the top bit of the cross term that we shifted out:
                ; (cross & 0x800) >> 11 — but we've already lost it. Approximate
                ; by just the shift, which is correct to 23 bits.
                ; Now normalise: if bit 24 is set, shift right and bump exp.
                ldi     r4, #0x1000000
                blt.32  r3, r4, .nonorm
                shr.32  r3, #1
                ld.32   r2, _fm_re
                add.32  r2, #1
                st.32   _fm_re, r2
.nonorm:        ld.32   r2, _fm_re
                call    __fnorm
                ld.32   r1, _fm_rs
                call    __fpack
                pop     r5
                pop     r6
                ret
.retzero:       clr     r1
                pop     r5
                pop     r6
                ret

; ---- fdiv(a, b): float division (uses globals, NOT reentrant) ----
fdiv:
                push    r6
                push    r5
                ld.32   r1, [sp+12]
                call    __funpack
                st.32   _fm_as, r1
                st.32   _fm_ae, r2
                ld.32   r6, r3
                ld.32   r1, [sp+16]
                call    __funpack
                beq.32  r3, #0, .divzero
                beq.32  r6, #0, .retzero
                ld.32   r4, _fm_as
                push    r1
                xor.32  r4, [sp]
                add.32  sp, #4
                st.32   _fm_rs, r4
                ld.32   r5, _fm_ae
                push    r2
                sub.32  r5, [sp]
                add.32  sp, #4
                add.32  r5, #127
                ; Mantissa divide: a_mant / b_mant → quotient mantissa.
                ; Both are 24-bit with bit 23 = implicit 1. The quotient
                ; needs to be a 24-bit Q23 number. Shift dividend left by
                ; 23 bits to get (a_mant << 23) / b_mant, which gives a
                ; Q23 result. Since we can't shift a 24-bit number left by
                ; 23 in 32 bits without overflow, we use __divmod on
                ; (a_mant << 7) / b_mant and then shift the quotient left
                ; by 16. This gives us (a_mant << 23) / b_mant = Q23 result.
                ; Actually simpler: (a_mant / b_mant) << 23, but integer
                ; division truncates. Better: use a loop.
                ; Actually cleanest: shift dividend left by 8 (fits in 32 bits:
                ; max 0xFFFFFF << 8 = 0xFFFFFF00), divide by the 24-bit divisor
                ; using __div, then shift quotient left by 15.
                ; (a << 8) / b gives Q8 result (8 extra fractional bits).
                ; We need Q23, so multiply result by 2^15... that's another mul.
                ; Let me just do the shift-subtract correctly:
                ; Shift dividend left by 8 to put leading 1 at bit 31.
                ; Do 24 iterations. The quotient = (dividend << 8) / divisor.
                ; The quotient has 24 bits and represents a/b * 2^8.
                ; So the real mantissa result is quotient << (23-8) = quotient << 15.
                ; Wait — that overflows 32 bits.
                ;
                ; SIMPLEST correct approach: just do more iterations.
                ; Put dividend in bits [23:0] (no shift). Do 24 iterations.
                ; After 24 iterations, quotient = floor(dividend * 2^24 / divisor) >> 24.
                ; No... that's 0 for equal-sized numbers.
                ;
                ; The textbook approach for IEEE mantissa divide:
                ; quotient = 0; remainder = a_mant.
                ; For i = 23 downto 0:
                ;   remainder <<= 1
                ;   if remainder >= divisor:
                ;     remainder -= divisor
                ;     quotient |= (1 << i)
                ; This produces a Q23 quotient directly.
                ; Equivalent to: shift remainder left and test, 24 times,
                ; building the quotient MSB-first. This IS the shift-subtract
                ; algo, but the "dividend" that shifts out is the remainder
                ; itself (starting from a_mant), not a separate register.
                ;
                ; Implementation: r2 = remainder (starts at a_mant), r1 = quotient.
                ; Each iteration: shift r2 left by 1, compare to divisor (r3),
                ; subtract if >=, set quotient bit.
                ; IEEE mantissa division: produce 24-bit quotient from two
                ; 24-bit mantissas. We use the compare-shift variant:
                ;   remainder = a_mant; quotient = 0;
                ;   for 24 iterations:
                ;     quotient <<= 1
                ;     if remainder >= divisor:
                ;       remainder -= divisor
                ;       quotient |= 1
                ;     remainder <<= 1
                ; This produces Q23 quotient directly.
                ld.32   r2, r6              ; remainder = a_mant
                clr     r1                  ; quotient = 0
                ld.32   r4, #24
.dloop:         beq.32  r4, #0, .ddone
                shl.32  r1, #1              ; quotient <<= 1
                blt.32  r2, r3, .dnosub     ; remainder < divisor?
                push    r3
                sub.32  r2, [sp]            ; remainder -= divisor
                add.32  sp, #4
                or.32   r1, #1              ; quotient |= 1
.dnosub:        shl.32  r2, #1              ; remainder <<= 1
                sub.32  r4, #1
                jmp     .dloop
.ddone:         ld.32   r3, r1
                ld.32   r2, r5
                call    __fnorm
                ld.32   r1, _fm_rs
                call    __fpack
                pop     r5
                pop     r6
                ret
.retzero:       clr     r1
                pop     r5
                pop     r6
                ret
.divzero:       ld.32   r1, _fm_as
                ld.32   r2, #254
                ldi     r3, #0xFFFFFF
                call    __fpack
                pop     r5
                pop     r6
                ret

; ---- fcmp(a, b): float compare → -1 / 0 / +1 in r1 ----
fcmp:
                ld.32   r1, [sp+4]
                ld.32   r2, [sp+8]
                ld.32   r3, r1
                shl.32  r3, #1
                ld.32   r4, r2
                shl.32  r4, #1
                push    r4
                or.32   r3, [sp]
                add.32  sp, #4
                beq.32  r3, #0, .eq
                ld.32   r3, r1
                shr.32  r3, #31
                ld.32   r4, r2
                shr.32  r4, #31
                push    r4
                ld.32   r4, r3
                sub.32  r4, [sp]
                add.32  sp, #4
                bgt.32  r4, #0, .lt
                blt.32  r4, #0, .gt
                push    r2
                sub.32  r1, [sp]
                add.32  sp, #4
                beq.32  r1, #0, .eq
                bne.32  r3, #0, .neg_both
                blt.32  r1, #0, .lt
                jmp     .gt
.neg_both:      blt.32  r1, #0, .gt
                jmp     .lt
.lt:            ld.32   r1, #-1
                ret
.gt:            ld.32   r1, #1
                ret
.eq:            clr     r1
                ret

; ---- itof(x): signed int → float ----
itof:
                push    r5
                ld.32   r3, [sp+8]
                beq.32  r3, #0, .zero
                clr     r1
                bge.32  r3, #0, .pos
                ld.32   r1, #1
                xor.32  r3, #-1
                add.32  r3, #1
.pos:           push    r1
                push    r3
                call    clz
                ld.32   r5, r1
                pop     r3
                ld.32   r2, #158
                push    r5
                sub.32  r2, [sp]
                add.32  sp, #4
                ld.32   r4, r5
                sub.32  r4, #8
                blt.32  r4, #0, .shr
                push    r4
                shl.32  r3, [sp]
                add.32  sp, #4
                jmp     .pack
.shr:           xor.32  r4, #-1
                add.32  r4, #1
                push    r4
                shr.32  r3, [sp]
                add.32  sp, #4
.pack:          pop     r1
                call    __fpack
                pop     r5
                ret
.zero:          clr     r1
                pop     r5
                ret

; ---- ftoi(x): float → signed int (truncate toward zero) ----
ftoi:
                ld.32   r1, [sp+4]
                call    __funpack
                ld.32   r4, #127
                blt.32  r2, r4, .zero
                ld.32   r4, #150
                push    r4
                sub.32  r2, [sp]
                add.32  sp, #4
                blt.32  r2, #0, .shr
                push    r2
                shl.32  r3, [sp]
                add.32  sp, #4
                jmp     .sign
.shr:           xor.32  r2, #-1
                add.32  r2, #1
                push    r2
                shr.32  r3, [sp]
                add.32  sp, #4
.sign:          beq.32  r1, #0, .pos
                xor.32  r3, #-1
                add.32  r3, #1
.pos:           ld.32   r1, r3
                ret
.zero:          clr     r1
                ret

; Float scratch globals (NOT reentrant)
_fa_as: db 0,0,0,0
_fa_ae: db 0,0,0,0
_fa_am: db 0,0,0,0
_fm_as: db 0,0,0,0
_fm_ae: db 0,0,0,0
_fm_am: db 0,0,0,0
_fm_rs: db 0,0,0,0
_fm_re: db 0,0,0,0
_fm_ah: db 0,0,0,0
_fm_al: db 0,0,0,0
_fm_bh: db 0,0,0,0
_fm_bl: db 0,0,0,0
; ===========================================================================
; Heap and string helpers
; ===========================================================================

; ---- __halloc(size) ----
; Bump allocator. Returns the previous _heap_ptr value in r1 and advances
; _heap_ptr by size. No bounds check, no free.
; Caller must initialise _heap_ptr before the first call.
__halloc:
                ld.32   r1, _heap_ptr       ; r1 = old top (return value)
                ld.32   r2, [sp+4]      ; r2 = size
                push    r1                          ; stash old top on stack
                push    r2                          ; push size
                add.32  r1, [sp]            ; r1 = old + size
                add.32  sp, #4              ; pop size
                st.32   _heap_ptr, r1       ; new heap top
                pop     r1                          ; restore return value
                ret

; ---- __strlen(s) ----
; Length of null-terminated string at [sp+4]. Result in r1.
__strlen:
                push    r5
                ld.32   r5, [sp+8]      ; s
                ld.32   r1, #0
.loop:
                ld.8    r2, [r5]
                beq.8   r2, #0, .done
                add.32  r1, #1
                add.32  r5, #1
                jmp     .loop
.done:
                pop     r5
                ret

; ---- __strcpy(dst, src) ----
; Copies src (incl. null) to dst. Args: dst at [sp+4], src at [sp+8].
__strcpy:
                ld.32   r2, [sp+4]      ; dst
                ld.32   r3, [sp+8]      ; src
.loop:
                ld.8    r1, [r3]
                st.8    [r2], r1
                beq.8   r1, #0, .done
                add.32  r2, #1
                add.32  r3, #1
                jmp     .loop
.done:
                ret

; ---- __strcmp(a, b) ----
; Returns 0 if equal, otherwise (first differing byte of a) - (b) in r1.
__strcmp:
                ld.32   r2, [sp+4]      ; a
                ld.32   r3, [sp+8]      ; b
.loop:
                ld.8    r1, [r2]
                ld.8    r4, [r3]
                bne.8   r1, r4, .diff
                beq.8   r1, #0, .eq
                add.32  r2, #1
                add.32  r3, #1
                jmp     .loop
.eq:
                ld.32   r1, #0
                ret
.diff:
                push    r4
                sub.32  r1, [sp]
                add.32  sp, #4
                ret

; ---- __strcat(a, b) ----
; Allocates a new string in heap holding a ++ b and returns its pointer.
; Uses globals _strcat_a/_strcat_b/_strcat_p as scratch (NOT reentrant).
__strcat:
                ld.32   r1, [sp+4]
                st.32   _strcat_a, r1
                ld.32   r1, [sp+8]
                st.32   _strcat_b, r1
                ; len(a) -> stash in _strcat_p temporarily
                ld.32   r1, _strcat_a
                push    r1
                call    __strlen
                add.32  sp, #4
                st.32   _strcat_p, r1
                ; len(b) -> r1
                ld.32   r1, _strcat_b
                push    r1
                call    __strlen
                add.32  sp, #4
                ; total = la + lb + 1
                ld.32   r2, _strcat_p
                push    r2
                add.32  r1, [sp]
                add.32  sp, #4
                add.32  r1, #1
                ; alloc(total) -> r1
                push    r1
                call    __halloc
                add.32  sp, #4
                st.32   _strcat_p, r1       ; remember new buffer
                ; strcpy(p, a)  — push a (src) then p (dst)
                ld.32   r1, _strcat_a
                push    r1
                ld.32   r1, _strcat_p
                push    r1
                call    __strcpy
                add.32  sp, #8
                ; dest2 = p + la (recompute la)
                ld.32   r1, _strcat_a
                push    r1
                call    __strlen
                add.32  sp, #4
                ld.32   r2, _strcat_p
                push    r2
                add.32  r1, [sp]
                add.32  sp, #4
                ; strcpy(p+la, b) — push b (src) then dst
                ld.32   r2, _strcat_b
                push    r2
                push    r1
                call    __strcpy
                add.32  sp, #8
                ld.32   r1, _strcat_p       ; return new pointer
                ret

; ---- Heap and string helper globals ----
_heap_ptr:   db 0x00, 0x00, 0x00, 0x00
_strcat_a:   db 0x00, 0x00, 0x00, 0x00
_strcat_b:   db 0x00, 0x00, 0x00, 0x00
_strcat_p:   db 0x00, 0x00, 0x00, 0x00
_S_empty:    db 0x00

; ---- Powers of 10 table (little-endian 32-bit, zero sentinel) ----
__printf_pow10:
                db 0x00, 0xCA, 0x9A, 0x3B
                db 0x00, 0xE1, 0xF5, 0x05
                db 0x80, 0x96, 0x98, 0x00
                db 0x40, 0x42, 0x0F, 0x00
                db 0xA0, 0x86, 0x01, 0x00
                db 0x10, 0x27, 0x00, 0x00
                db 0xE8, 0x03, 0x00, 0x00
                db 0x64, 0x00, 0x00, 0x00
                db 0x0A, 0x00, 0x00, 0x00
                db 0x01, 0x00, 0x00, 0x00
                db 0x00, 0x00, 0x00, 0x00
