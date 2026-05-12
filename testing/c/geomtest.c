// geomtest.c — geometric/math stdlib test suite.
//
// Covers every float function the stdlib exposes beyond basic arithmetic:
//   - fast ops: fmin/fmax/fclamp, fsign, flerp, ffloor/fceil, fdeg2rad/frad2deg
//   - fsqrt-based: fhypot
//   - core trig:  fsin, fcos, fatan2
//   - derived:    ftan, fatan, fasin, facos
//
// Pairs every call with a scale-int comparison to catch numeric drift.
// Tolerance is generous on trig because the soft-float polynomial/rational
// approximations only give ~2–3 decimal digits of accuracy.
//
// The trig section is slow on this ISA (fsqrt/fsin/fcos/fatan2 are Newton
// iterations over software multiply) — expect a few minutes in the sim.

int pass_count;
int fail_count;

void check_int(char *name, int got, int expect) {
    if (got == expect) {
        pass_count = pass_count + 1;
        printf("  PASS  %s\n", name);
    } else {
        fail_count = fail_count + 1;
        printf("  FAIL  %s: expected %d got %d\n", name, expect, got);
    }
}

// tolerance in units of (1 / scale)
void check_float(char *name, float got, float expect, int scale, int tol) {
    int gi = ftoi(got * itof(scale));
    int ei = ftoi(expect * itof(scale));
    int diff = gi - ei;
    if (diff < 0) diff = 0 - diff;
    if (diff <= tol) {
        pass_count = pass_count + 1;
        printf("  PASS  %s (got %d/%d)\n", name, gi, scale);
    } else {
        fail_count = fail_count + 1;
        printf("  FAIL  %s: expected %d/%d got %d/%d\n", name, ei, scale, gi, scale);
    }
}

void section(char *name) {
    printf("\n[%s]\n", name);
}

void main() {
    pass_count = 0;
    fail_count = 0;
    printf("MPU geometric stdlib test\n");
    printf("=========================\n");

    // ---- fmin / fmax / fclamp (fast — just fcmp) ----
    section("fmin/fmax/fclamp");
    check_float("fmin(1.5, 2.5)", fmin(1.5, 2.5), 1.5, 10, 0);
    check_float("fmin(2.5, 1.5)", fmin(2.5, 1.5), 1.5, 10, 0);
    check_float("fmin(-3.0, -1.0)", fmin(-3.0, -1.0), -3.0, 10, 0);
    check_float("fmax(1.5, 2.5)", fmax(1.5, 2.5), 2.5, 10, 0);
    check_float("fmax(2.5, 1.5)", fmax(2.5, 1.5), 2.5, 10, 0);
    check_float("fmax(-3.0, -1.0)", fmax(-3.0, -1.0), -1.0, 10, 0);
    check_float("fclamp(5.0, 0, 10)",  fclamp(5.0, 0.0, 10.0), 5.0, 10, 0);
    check_float("fclamp(-1, 0, 10)",   fclamp(-1.0, 0.0, 10.0), 0.0, 10, 0);
    check_float("fclamp(20, 0, 10)",   fclamp(20.0, 0.0, 10.0), 10.0, 10, 0);

    // ---- fsign (fast) ----
    section("fsign");
    check_float("fsign(3.14)", fsign(3.14), 1.0, 10, 0);
    check_float("fsign(-2.5)", fsign(-2.5), -1.0, 10, 0);
    check_float("fsign(0.0)",  fsign(0.0),  0.0, 10, 0);

    // ---- flerp (fast) ----
    section("flerp");
    check_float("flerp(10, 20, 0.5)",  flerp(10.0, 20.0, 0.5), 15.0, 10, 0);
    check_float("flerp(10, 20, 0.0)",  flerp(10.0, 20.0, 0.0), 10.0, 10, 0);
    check_float("flerp(10, 20, 1.0)",  flerp(10.0, 20.0, 1.0), 20.0, 10, 0);
    check_float("flerp(0, 100, 0.25)", flerp(0.0, 100.0, 0.25), 25.0, 10, 0);

    // ---- ffloor / fceil (fast) ----
    section("ffloor/fceil");
    check_float("ffloor(3.7)",  ffloor(3.7),  3.0,  10, 0);
    check_float("ffloor(3.0)",  ffloor(3.0),  3.0,  10, 0);
    check_float("ffloor(-2.3)", ffloor(-2.3), -3.0, 10, 0);
    check_float("ffloor(-2.0)", ffloor(-2.0), -2.0, 10, 0);
    check_float("ffloor(0.5)",  ffloor(0.5),  0.0,  10, 0);
    check_float("fceil(3.2)",   fceil(3.2),   4.0,  10, 0);
    check_float("fceil(3.0)",   fceil(3.0),   3.0,  10, 0);
    check_float("fceil(-2.7)",  fceil(-2.7), -2.0, 10, 0);
    check_float("fceil(-2.0)",  fceil(-2.0), -2.0, 10, 0);

    // ---- fdeg2rad / frad2deg (one fmul each — fast) ----
    section("fdeg2rad/frad2deg");
    check_float("fdeg2rad(180)", fdeg2rad(180.0), 3.14159, 100, 1);
    check_float("fdeg2rad(90)",  fdeg2rad(90.0),  1.5708,  100, 1);
    check_float("fdeg2rad(0)",   fdeg2rad(0.0),   0.0,     100, 0);
    check_float("frad2deg(pi)",  frad2deg(3.14159), 180.0, 10,  1);
    check_float("frad2deg(pi/2)", frad2deg(1.5708), 90.0,  10,  1);

    // ---- fhypot (fsqrt-based) ----
    section("fhypot");
    check_float("fhypot(3, 4)",  fhypot(3.0, 4.0),  5.0,       10,  1);
    check_float("fhypot(5, 12)", fhypot(5.0, 12.0), 13.0,      10,  2);
    check_float("fhypot(1, 1)",  fhypot(1.0, 1.0),  1.41421,   100, 3);

    // ---- fsqrt (Newton iteration) ----
    section("fsqrt");
    check_float("fsqrt(1)",   fsqrt(1.0),    1.0,     100, 1);
    check_float("fsqrt(4)",   fsqrt(4.0),    2.0,     100, 1);
    check_float("fsqrt(9)",   fsqrt(9.0),    3.0,     100, 1);
    check_float("fsqrt(25)",  fsqrt(25.0),   5.0,     100, 1);
    check_float("fsqrt(100)", fsqrt(100.0), 10.0,     100, 2);
    check_float("fsqrt(0)",   fsqrt(0.0),    0.0,     100, 0);

    // ---- fsin / fcos (Bhaskara polynomial) ----
    section("fsin/fcos");
    check_float("fsin(0)",      fsin(0.0),         0.0,     100, 1);
    check_float("fsin(pi/6)",   fsin(0.5235987),   0.5,     100, 2);
    check_float("fsin(pi/4)",   fsin(0.7853981),   0.7071,  100, 2);
    check_float("fsin(pi/2)",   fsin(1.5707963),   1.0,     100, 2);
    check_float("fsin(pi)",     fsin(3.14159265),  0.0,     100, 2);
    check_float("fcos(0)",      fcos(0.0),         1.0,     100, 1);
    check_float("fcos(pi/4)",   fcos(0.7853981),   0.7071,  100, 2);
    check_float("fcos(pi/2)",   fcos(1.5707963),   0.0,     100, 2);
    check_float("fcos(pi)",     fcos(3.14159265), -1.0,     100, 2);

    // ---- fatan2 (rational approximation, quadrant coverage) ----
    section("fatan2");
    check_float("fatan2(0,1)",   fatan2( 0.0,  1.0),  0.0,       100, 1);
    check_float("fatan2(1,1)",   fatan2( 1.0,  1.0),  0.7853981, 100, 2);  // Q1: +pi/4
    check_float("fatan2(1,-1)",  fatan2( 1.0, -1.0),  2.356194,  100, 3);  // Q2: +3pi/4
    check_float("fatan2(-1,-1)", fatan2(-1.0, -1.0), -2.356194,  100, 3);  // Q3: -3pi/4
    check_float("fatan2(-1,1)",  fatan2(-1.0,  1.0), -0.7853981, 100, 2);  // Q4: -pi/4

    // ---- Derived trig (wrappers around fsin/fcos/fsqrt/fatan2) ----
    section("ftan/fatan/fasin/facos");
    check_float("ftan(0)",     ftan(0.0),        0.0,       100, 1);
    check_float("ftan(pi/4)",  ftan(0.7853981),  1.0,       100, 2);
    check_float("fatan(0)",    fatan(0.0),       0.0,       100, 1);
    check_float("fatan(1)",    fatan(1.0),       0.7853981, 100, 2);
    check_float("fasin(0)",    fasin(0.0),       0.0,       100, 1);
    check_float("fasin(0.5)",  fasin(0.5),       0.5235987, 100, 2);
    check_float("facos(1)",    facos(1.0),       0.0,       100, 1);
    check_float("facos(0.5)",  facos(0.5),       1.047197,  100, 3);

    // ---- Summary ----
    printf("\n=========================\n");
    printf("RESULTS: %d passed, %d failed\n", pass_count, fail_count);
    if (fail_count == 0) {
        printf("ALL TESTS PASSED\n");
    } else {
        printf("SOME TESTS FAILED\n");
    }
}
