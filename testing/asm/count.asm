; count99.asm - Print numbers 0 through 99

                ld.32   r3, #0           ; counter
                ld.32   r6, #10          ; constant 10 (too large for branch immediate)

.loop:
                ; Compute tens digit
                ld.32   r1, r3           ; r1 = counter
                ld.32   r5, #0           ; tens = 0
.tens:          blt.32  r1, r6, .units   ; r1 < 10?
                sub.32  r1, r6
                add.32  r5, #1
                jmp     .tens

.units:
                ; r5 = tens digit, r1 = units digit
                ; Print tens digit (skip if zero and counter < 10)
                blt.32  r3, r6, .skip_tens
                ld.32   r2, r5
                add.32  r2, #48          ; ASCII '0'
                st.8    0xFFFF0000, r2
                ld.32   r4, #1500
.w1:            sub.32  r4, #1
                bne.32  r4, #0, .w1

.skip_tens:
                ; Print units digit
                add.32  r1, #48          ; ASCII '0'
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.w2:            sub.32  r4, #1
                bne.32  r4, #0, .w2

                ; Print newline
                ld.32   r1, r6           ; 10 = '\n'
                st.8    0xFFFF0000, r1
                ld.32   r4, #1500
.w3:            sub.32  r4, #1
                bne.32  r4, #0, .w3

                ; Increment and loop
                add.32  r3, #1
                ld.32   r4, #100
                blt.32  r3, r4, .loop

.halt:          jmp     .halt

                end