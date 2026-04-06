                jmp     __start

main:
                sub.32  r7, #4
                st.32   [r7], r6
                ld.32   r1, #1
                add.32 r1, #2
                sub.32  r7, #4
                st.32   [r7], r1
                ld.32   r1, #__str_1
                sub.32  r7, #4
                st.32   [r7], r1
                call    printf
                add.32  r7, #8
.epilogue:
                ld.32   r6, [r7+=4]
                ret

__start:
                call    main
.__halt:        jmp     .__halt

__str_1: db 0x48, 0x65, 0x6C, 0x6C, 0x6F, 0x20, 0x31, 0x2B, 0x32, 0x3D, 0x25, 0x64, 0x00

; ---- Standard Library ----
; MPU Standard Library
; Linked after compiled code. Provides runtime functions.

; ---- putchar(char c) ----
; Argument: character on stack at [r7+8]
putchar:
                sub.32  r7, #4              ; \
                st.32   [r7], r6            ; / save r6
                ld.32   r1, [r7][r0+8]      ; load arg from stack
                st.8    0xFFFF0000, r1      ; send byte
                ld.32   r4, #1500           ; delay for byte to transmit
.wait:          sub.32  r4, #1
                bne.32  r4, #0, .wait
                ld.32   r6, [r0][r7+=4]     ; restore r6
                ret

; ---- puts(char *s) ----
; Argument: pointer on stack at [r7+12]
; Prints null-terminated string, appends newline.
puts:
                sub.32  r7, #4              ; \
                st.32   [r7], r6            ; / save r6
                sub.32  r7, #4              ; \
                st.32   [r7], r5            ; / save r5
                ld.32   r5, [r7][r0+12]     ; load string pointer (8 + 1 retaddr)
.loop:
                ld.8    r1, [r5++]
                beq.8   r1, #0, .newline
                st.8    0xFFFF0000, r1      ; send byte
                ld.32   r4, #1500           ; delay
.wait:          sub.32  r4, #1
                bne.32  r4, #0, .wait
                jmp     .loop
.newline:
                ld.32   r1, #10             ; '\n'
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.waitnl:        sub.32  r4, #1
                bne.32  r4, #0, .waitnl
                ld.32   r5, [r0][r7+=4]     ; restore r5
                ld.32   r6, [r0][r7+=4]     ; restore r6
                ret

; ---- sleep(int ms) ----
; Argument: milliseconds on stack at [r7+8]
; At 12MHz, ~3000 loop iterations per ms.
sleep:
                sub.32  r7, #4              ; \
                st.32   [r7], r6            ; / save r6
                ld.32   r3, [r7][r0+8]      ; load count
.loop:          beq.32  r3, #0, .done
                sub.32  r3, #1
                jmp     .loop
.done:
                ld.32   r6, [r0][r7+=4]     ; restore r6
                ret

; ---- set_led(int value) ----
; Argument: LED bits on stack at [r7+8]
; bit 0 = green, bit 1 = red, bit 2 = blue
set_led:
                sub.32  r7, #4              ; \
                st.32   [r7], r6            ; / save r6
                ld.32   r1, [r7][r0+8]
                st.8    0xFFFF0008, r1
                ld.32   r6, [r0][r7+=4]     ; restore r6
                ret

; ---- printf(char *fmt, ...) ----
; Variadic printf supporting: %d %s %c %x %%
; After saving r3-r6 (4 saves = 16 bytes):
;   [r7+0]=r3, [r7+4]=r4, [r7+8]=r5, [r7+12]=r6
;   [r7+16]=retaddr, [r7+20]=fmt, [r7+24]=arg0, [r7+28]=arg1, ...
; r5 = format string pointer, r3 = offset to next vararg from r7
printf:
                sub.32  r7, #4
                st.32   [r7], r6
                sub.32  r7, #4
                st.32   [r7], r5
                sub.32  r7, #4
                st.32   [r7], r4
                sub.32  r7, #4
                st.32   [r7], r3
                ld.32   r5, [r7][r0+20]     ; r5 = format string pointer
                ld.32   r3, #24             ; r3 = offset to first vararg

; ---- Main scan loop ----
.scan:
                ld.8    r1, [r5++]          ; next format char
                beq.8   r1, #0, .ret        ; null terminator -> done
                ld.32   r4, #37             ; '%' = 37
                beq.32  r1, r4, .spec       ; format specifier
                ; Regular character: send to UART
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.cwait:         sub.32  r4, #1
                bne.32  r4, #0, .cwait
                jmp     .scan

; ---- Format specifier dispatch ----
.spec:
                ld.8    r1, [r5++]          ; specifier char
                beq.8   r1, #0, .ret        ; premature end
                ld.32   r4, #100            ; 'd'
                beq.32  r1, r4, .dec
                ld.32   r4, #115            ; 's'
                beq.32  r1, r4, .str
                ld.32   r4, #99             ; 'c'
                beq.32  r1, r4, .chr
                ld.32   r4, #120            ; 'x'
                beq.32  r1, r4, .hex
                ld.32   r4, #37             ; '%'
                beq.32  r1, r4, .pct
                ; Unknown specifier: print as-is
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.uwait:         sub.32  r4, #1
                bne.32  r4, #0, .uwait
                jmp     .scan

; ---- %c: print character ----
.chr:
                ld.32   r1, [r7][r3+0]      ; load char arg
                add.32  r3, #4              ; advance to next arg
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.chrw:          sub.32  r4, #1
                bne.32  r4, #0, .chrw
                jmp     .scan

; ---- %%: print literal '%' ----
.pct:
                ld.32   r1, #37
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.pctw:          sub.32  r4, #1
                bne.32  r4, #0, .pctw
                jmp     .scan

; ---- %s: print string ----
.str:
                ld.32   r2, [r7][r3+0]      ; load string pointer arg
                add.32  r3, #4              ; advance to next arg
                sub.32  r7, #4              ; \
                st.32   [r7], r5            ; / save fmt pointer
.strl:
                ld.8    r1, [r2++]
                beq.8   r1, #0, .strd
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.strw:          sub.32  r4, #1
                bne.32  r4, #0, .strw
                jmp     .strl
.strd:
                ld.32   r5, [r0][r7+=4]     ; restore fmt pointer
                jmp     .scan

; ---- %d: print signed decimal ----
.dec:
                ld.32   r2, [r7][r3+0]      ; load int arg
                add.32  r3, #4              ; advance to next arg
                sub.32  r7, #4              ; \
                st.32   [r7], r5            ; / save fmt pointer
                sub.32  r7, #4              ; \
                st.32   [r7], r3            ; / save arg offset
                ld.32   r3, r2              ; r3 = value (register move!)
                ; Handle negative
                bge.32  r3, #0, .dpos
                ld.32   r1, #45             ; '-'
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.dnw:           sub.32  r4, #1
                bne.32  r4, #0, .dnw
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
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.ddw:           sub.32  r4, #1
                bne.32  r4, #0, .ddw
.dnx:
                add.32  r5, #4              ; next power in table
                jmp     .dpow
.dend:
                ; If nothing printed (value was 0), print '0'
                bne.32  r2, #0, .ddn
                ld.32   r1, #48
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.dzw:           sub.32  r4, #1
                bne.32  r4, #0, .dzw
.ddn:
                ld.32   r3, [r0][r7+=4]     ; restore arg offset
                ld.32   r5, [r0][r7+=4]     ; restore fmt pointer
                jmp     .scan

; ---- %x: print hex ----
.hex:
                ld.32   r2, [r7][r3+0]      ; load int arg
                add.32  r3, #4              ; advance to next arg
                sub.32  r7, #4              ; \
                st.32   [r7], r5            ; / save fmt pointer
                sub.32  r7, #4              ; \
                st.32   [r7], r3            ; / save arg offset
                ld.32   r3, r2              ; r3 = value (register move!)
                ld.32   r2, #0              ; started flag
                ld.32   r5, #8              ; nibble count
.xnib:
                beq.32  r5, #0, .xdn
                ; Extract top nibble
                ld.32   r1, r3              ; r1 = value (register move!)
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
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.xw:            sub.32  r4, #1
                bne.32  r4, #0, .xw
.xsh:
                shl.32  r3, #4              ; shift value left for next nibble
                sub.32  r5, #1
                jmp     .xnib
.xdn:
                ld.32   r3, [r0][r7+=4]     ; restore arg offset
                ld.32   r5, [r0][r7+=4]     ; restore fmt pointer
                jmp     .scan

; ---- Return ----
.ret:
                ld.32   r3, [r0][r7+=4]     ; restore r3
                ld.32   r4, [r0][r7+=4]     ; restore r4
                ld.32   r5, [r0][r7+=4]     ; restore r5
                ld.32   r6, [r0][r7+=4]     ; restore r6
                ret

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

                end
