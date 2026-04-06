 ; hello.asm - Hello, World! for the MPU

                ld.32   r6, #hello      ; r6 = pointer to string
.loop:
                ld.8    r1, [r6++]      ; load next byte, advance pointer
                beq.8   r1, #0, stop    ; if null terminator, we're done
                call    output          ; print the character
                jmp     .loop           ; next character

stop:           jmp     stop            ; halt (infinite loop)

; Subroutine: send byte in r1 to UART
output:
.wait:          ld.32   r2, 0xFFFF0004  ; read UART status
                bne.8   r2, #0, .wait   ; loop while busy
                st.8    0xFFFF0000, r1  ; send the byte
                ret

; The string data
hello:          db      'Hello, world!\0'

                end