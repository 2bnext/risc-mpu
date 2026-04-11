// structdemo.c — structs, arrays, and pointers on the MPU

struct vec2 {
    float x;
    float y;
};

struct particle {
    struct vec2 *pos;
    struct vec2 *vel;
    int mass;
};

float vec2_length_sq(struct vec2 *v) {
    return v->x * v->x + v->y * v->y;
}

void vec2_add(struct vec2 *dst, struct vec2 *a, struct vec2 *b) {
    dst->x = a->x + b->x;
    dst->y = a->y + b->y;
}

void vec2_print(struct vec2 *v) {
    // Print with one decimal: scale by 10, print integer and fraction
    int xi = ftoi(v->x * 10.0);
    int yi = ftoi(v->y * 10.0);
    printf("(%d.%d, %d.%d)",
        xi / 10, abs(xi) - abs(xi / 10) * 10,
        yi / 10, abs(yi) - abs(yi / 10) * 10);
}

void main() {
    // ---- Basic struct and pointer ----
    struct vec2 a;
    a.x = 3.0;
    a.y = 4.0;

    struct vec2 b;
    b.x = 1.5;
    b.y = 2.5;

    struct vec2 c;
    vec2_add(&c, &a, &b);

    printf("a = "); vec2_print(&a); printf("\n");
    printf("b = "); vec2_print(&b); printf("\n");
    printf("a + b = "); vec2_print(&c); printf("\n");

    int len_sq = ftoi(vec2_length_sq(&a));
    printf("|a|^2 = %d (expect 25)\n", len_sq);

    // ---- Typed arrays ----
    int primes[8];
    primes[0] = 2;  primes[1] = 3;  primes[2] = 5;  primes[3] = 7;
    primes[4] = 11; primes[5] = 13; primes[6] = 17; primes[7] = 19;

    int sum = 0;
    int i;
    for (i = 0; i < 8; i++)
        sum = sum + primes[i];
    printf("sum of first 8 primes = %d (expect 77)\n", sum);

    // ---- Float array ----
    float samples[4];
    samples[0] = 1.2;
    samples[1] = 3.4;
    samples[2] = 5.6;
    samples[3] = 7.8;

    float total = 0.0;
    for (i = 0; i < 4; i++)
        total = total + samples[i];
    printf("float sum * 10 = %d (expect 180)\n", ftoi(total * 10.0));

    // ---- Array of structs ----
    struct vec2 path[3];
    path[0].x = 0.0; path[0].y = 0.0;
    path[1].x = 3.0; path[1].y = 4.0;
    path[2].x = 6.0; path[2].y = 0.0;

    printf("path: ");
    for (i = 0; i < 3; i++) {
        vec2_print(&path[i]);
        printf(" ");
    }
    printf("\n");

    // ---- Struct with pointers ----
    struct vec2 pos;
    pos.x = 10.0;
    pos.y = 20.0;
    struct vec2 vel;
    vel.x = 0.5;
    vel.y = -1.0;

    struct particle p;
    p.pos = &pos;
    p.vel = &vel;
    p.mass = 42;

    // Simulate one step: pos += vel
    p.pos->x = p.pos->x + p.vel->x;
    p.pos->y = p.pos->y + p.vel->y;

    printf("particle mass=%d pos=", p.mass);
    vec2_print(p.pos);
    printf(" (expect 10.5, 19.0)\n");
}
