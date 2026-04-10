                    ld.8    r2, #0x0
                    st.8    0xffff0008, r2
                    ld.8    r3, #0b110
                    ld.32   r4, #0x7ffff

blink:
                    st.8    0xffff0008, r2

                    ld.32   r1, r4
.wait1:
                    sub     r1, #1
                    bne     r1, #0, .wait1

                    st.8    0xffff0008, r3

                    ld.32   r1, r4
.wait2:
                    sub     r1, #1
                    bne     r1, #0, .wait2

                    jmp     blink

                    end
