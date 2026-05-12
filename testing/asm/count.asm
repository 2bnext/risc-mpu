; count99.asm - Print numbers 0 through 99

                ld      r3, #0           ; counter
                ld      r6, #10          ; constant 10 (too large for branch immediate)

.loop:
                ; Compute tens digit
                ld      r1, r3           ; r1 = counter
                ld      r5, #0           ; tens = 0
.tens:          blt     r1, r6, .units   ; r1 < 10?
                sub     r1, r6
                add     r5, #1
                jmp     .tens

.units:
                ; r5 = tens digit, r1 = units digit
                ; Print tens digit (skip if zero and counter < 10)
                blt     r3, r6, .skip_tens
                ld      r2, r5
                add     r2, #48          ; ASCII '0'
                st.8    0xFFFF0000, r2
                ld      r4, #1500
.w1:            sub     r4, #1
                bne     r4, #0, .w1

.skip_tens:
                ; Print units digit
                add     r1, #48          ; ASCII '0'
                st.8    0xFFFF0000, r1
                ld      r4, #1500
.w2:            sub     r4, #1
                bne     r4, #0, .w2

                ; Print newline
                ld      r1, r6           ; 10 = '\n'
                st.8    0xFFFF0000, r1
                ld      r4, #1500
.w3:            sub     r4, #1
                bne     r4, #0, .w3

                ; Increment and loop
                add     r3, #1
                ld      r4, #100
                blt     r3, r4, .loop

.halt:          jmp     .halt

                end