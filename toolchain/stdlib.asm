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
                mov     r3, r2                      ; r3 = value (register move!)
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
                mov     r3, r2                      ; r3 = value (register move!)
                ld.32   r2, #0              ; started flag
                ld.32   r5, #8              ; nibble count
.xnib:
                beq.32  r5, #0, .xdn
                ; Extract top nibble
                mov     r1, r3                      ; r1 = value (register move!)
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

; ---- __mul(a, b): unsigned multiply ----
; Shift-add, up to 32 iterations (bails out when multiplier is zero).
; Args: a at [sp+4], b at [sp+8]. Result in r1.
__mul:
                ld.32   r1, [sp+4]      ; r1 = a (shifts left)
                ld.32   r2, [sp+8]      ; r2 = b (shifts right)
                ld.32   r3, #0              ; accumulator
.loop:
                beq.32  r2, #0, .done
                mov     r4, r2                      ; test LSB of b
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
                mov     r1, r3
                ret

; ---- __div(a, b) / __mod(a, b): unsigned divide and modulo ----
; Shift-subtract, 32 iterations. Args: a at [sp+4], b at [sp+8].
; __div returns a/b in r1; __mod returns a%b in r1.
; Clobbers r2-r5; no caller-saves needed (caller pushed args).
__div:
                call    __divmod
                mov     r1, r3                      ; quotient
                ret
__mod:
                call    __divmod
                mov     r1, r4                      ; remainder
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
