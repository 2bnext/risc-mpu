; Sanity-check __print_float from stdlib.asm.
; Prints 3.14159 (as float literal) then '\n', then -0.5 then '\n'.

                ; 3.141590 in IEEE 754 ≈ 0x40490FD0
                ldi     r1, #0x40490FD0
                push    r1
                call    __print_float
                add.32  sp, #4
                ld.32   r1, #10
                push    r1
                call    putchar
                add.32  sp, #4

                ; -0.5 = 0xBF000000
                ldi     r1, #0xBF000000
                push    r1
                call    __print_float
                add.32  sp, #4
                ld.32   r1, #10
                push    r1
                call    putchar
                add.32  sp, #4

                ; 0.0 = 0x00000000
                ld.32   r1, #0
                push    r1
                call    __print_float
                add.32  sp, #4
                ld.32   r1, #10
                push    r1
                call    putchar
                add.32  sp, #4

                ; 1000.5 = 0x447A2000
                ldi     r1, #0x447A2000
                push    r1
                call    __print_float
                add.32  sp, #4
                ld.32   r1, #10
                push    r1
                call    putchar
                add.32  sp, #4

                jmp     __halt
__halt:         jmp     __halt

_FMT_D: db 0x25, 0x64, 0x00

                end
