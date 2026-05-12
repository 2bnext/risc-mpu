// uniondemo.c — unions, type punning, and C integer types on the MPU

union bits32 {
    int i;
    float f;
    unsigned short halves[2];
};

struct color {
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t a;
};

union pixel {
    int rgba;
    struct color *c;
};

void print_hex(int v) {
    // Print as 8-digit hex manually since we have %x
    printf("0x%x", v);
}

void main() {
    // ---- Type punning: float ↔ int ----
    union bits32 u;
    u.f = 1.0;
    printf("1.0 as int: ");
    print_hex(u.i);
    printf(" (expect 0x3f800000)\n");

    u.i = 0x40490FDB;  // pi in IEEE 754
    printf("0x40490FDB as float: %d/100 (expect 314)\n",
        ftoi(u.f * 100.0));

    // ---- Half-word access ----
    u.i = 0x12345678;
    printf("lo16=%d hi16=%d (expect 22136 4660)\n",
        u.halves[0], u.halves[1]);

    // ---- C integer types ----
    short s = -1000;
    unsigned short us = 60000;
    long l = 100000;
    unsigned long ul = 3000000;
    unsigned char uc = 255;
    signed int si = -42;

    printf("short=%d ushort=%d\n", s, us);
    printf("long=%d ulong=%d\n", l, ul);
    printf("uchar=%d signed=%d\n", uc, si);

    // ---- Overflow behavior matches ISA width ----
    unsigned short wrap = 65535;
    wrap = wrap + 1;
    printf("ushort 65535+1=%d (expect 0)\n", wrap);

    unsigned char bwrap = 255;
    bwrap = bwrap + 1;
    printf("uchar 255+1=%d (expect 0)\n", bwrap);

    // ---- Struct inside union via pointer ----
    struct color col;
    col.r = 255;
    col.g = 128;
    col.b = 0;
    col.a = 255;

    printf("color: r=%d g=%d b=%d a=%d\n", col.r, col.g, col.b, col.a);
}
