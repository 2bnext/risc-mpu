loop:
    ld.l r2, [0xFFFF0004]   ; read busy flag
    bne  r2, #loop          ; loop while busy
    st.b [0xFFFF0000], r1   ; send byte
    