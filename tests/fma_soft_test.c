/* tests/test_fma_soft.py's driver ((Triforce, 11-22, the performance audit's LIFT-06)): the exact fused multiply-add
   bodies recomp_fpe_fma64 and recomp_fpe_fma32 with nx2/fma_soft.py's short way out against the same bodies without it
   (the kit's text: the way out is the body's first lines and RECOMP_FMA_SOFT_ON() decides it, which the test's hook
   header makes a variable). Both run from one Ctx; the value and every byte of the Ctx must match.

   fma_soft_test random <n> <seed>   n operand triples a width: zeros, subnormals, infinities, NaNs of both kinds with
                                     payloads, the extreme normals, exponents everywhere and matched to the product,
                                     cancellations and half-ulp addends, under random FPCR and FPSR
   fma_soft_test sweep               edge exponents and fractions for both factors, each with addends placed against the
                                     product (cancelling it within a few ulps, at its half ulp, far below, far above),
                                     under FZ on and off with IXC set and clear
   fma_soft_test env                 (built without the hook) how many of 1000 plain calls the way out answers: what
                                     HOS_FMA_FAST decides
   fma_soft_test time                ns a call for plain operands, with the way out and without
   Exit 0: no mismatch. 1: a mismatch. 3: this CPU cannot run the build. */
#include "a64.h"
#include <stdio.h>
#include <stdlib.h>
#include <cpuid.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <time.h>
#endif

int fma_soft_test_on = 1;
long long fma_soft_test_exits;

static uint64_t rs = 1;
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }
static uint32_t rbelow(uint32_t n) { return (uint32_t)(((rnd() >> 32) * n) >> 32); }
static double d_of(uint64_t x) { double f; memcpy(&f, &x, 8); return f; }
static uint64_t d_bits(double f) { uint64_t x; memcpy(&x, &f, 8); return x; }
static float f_of(uint32_t x) { float f; memcpy(&f, &x, 4); return f; }
static uint32_t f_bits(float f) { uint32_t x; memcpy(&x, &f, 4); return x; }

/* ---- states ---- */
static uint64_t rand_fpcr(void) {
    static const uint64_t bits[] = {1u << 22, 1u << 23, 3u << 22, 1u << 25, 1u << 26, 1, 2, 4, 1u << 8, 1u << 9, 1u << 10,
                                    1u << 11, 1u << 12, 1u << 15, 1u << 19, UINT64_C(1) << 32};
    const uint32_t k = rbelow(100);
    if (k < 55) return 0;
    if (k < 80) return 1u << 24;                                                   /* FZ alone */
    uint64_t v = bits[rbelow(sizeof bits / sizeof bits[0])];
    if (rnd() & 1) v |= 1u << 24;
    if (!(rnd() & 3)) v |= bits[rbelow(sizeof bits / sizeof bits[0])];
    return v;
}
static uint64_t rand_fpsr(void) {
    uint64_t v = rnd() & 0x9f;
    if (!(rnd() & 3)) v |= 1u << 27;
    switch (rbelow(4)) {
    case 0: return v | 16u;
    case 1: return v & ~(uint64_t)16u;
    case 2: return 0;
    default: return v;
    }
}

/* ---- operands ---- */
static uint64_t frac64(void) {
    switch (rbelow(8)) {
    case 0: return 0;
    case 1: return (UINT64_C(1) << 52) - 1;
    case 2: return rnd() & ((UINT64_C(1) << 52) - 1) & ~((UINT64_C(1) << (1 + rbelow(51))) - 1);   /* (low bits clear) */
    case 3: return (UINT64_C(1) << rbelow(52)) | (rnd() & 1);
    default: return rnd() & ((UINT64_C(1) << 52) - 1);
    }
}
static uint64_t any64(void) {
    const uint32_t k = rbelow(100);
    const uint64_t sign = (rnd() & 1) << 63;
    if (k < 4) return sign;                                                        /* zero */
    if (k < 8) return sign | (frac64() ? frac64() : 1);                            /* subnormal (or zero) */
    if (k < 10) return sign | UINT64_C(0x7ff0000000000000);                        /* infinity */
    if (k < 12) return sign | UINT64_C(0x7ff8000000000000) | (rnd() & ((UINT64_C(1) << 51) - 1));         /* quiet NaN */
    if (k < 14) return sign | UINT64_C(0x7ff0000000000000) | ((rnd() & ((UINT64_C(1) << 51) - 1)) | 1);   /* signalling */
    if (k < 17) return sign | ((rnd() & 1) ? UINT64_C(0x0010000000000000) | (rnd() & 3) : UINT64_C(0x7fefffffffffffff) - (rnd() & 3));
    if (k < 30) return sign | ((uint64_t)(1 + rbelow(2046)) << 52) | frac64();    /* any exponent */
    if (k < 40) {                                                                  /* around the way out's limits */
        static const uint32_t e[] = {1, 2, 123, 542, 543, 544, 1502, 1503, 1504, 1923, 2045, 2046};
        return sign | ((uint64_t)e[rbelow(sizeof e / sizeof e[0])] << 52) | frac64();
    }
    return sign | ((uint64_t)(983 + rbelow(81)) << 52) | frac64();                 /* ordinary */
}
static void triple64(uint64_t *a, uint64_t *b, uint64_t *z) {
    *a = any64(), *b = any64(), *z = any64();
    const uint32_t k = rbelow(100);
    if (k >= 60) return;
    const double p = d_of(*a) * d_of(*b);
    const uint64_t pb = d_bits(p);
    const uint32_t pe = (uint32_t)(pb >> 52) & 0x7ff;
    if (pe == 0 || pe == 0x7ff) return;
    if (k < 20) {   /* an addend that cancels the product within a few ulps */
        *z = (pb ^ (UINT64_C(1) << 63)) + (uint64_t)(int64_t)((int)rbelow(9) - 4);
    } else if (k < 35) {   /* an addend at the product's half ulp, quarter ulp, ulp ... (its fraction zero or random) */
        const int e = (int)pe - 55 + (int)rbelow(6);
        if (e >= 1) *z = ((rnd() & 1) << 63) | ((uint64_t)e << 52) | ((rnd() & 1) ? 0 : (rnd() & 3) ? frac64() : 1);
    } else if (k < 50) {   /* an addend near the product's size */
        const int e = (int)pe - 3 + (int)rbelow(7);
        if (e >= 1 && e <= 2046) *z = ((rnd() & 1) << 63) | ((uint64_t)e << 52) | frac64();
    } else {   /* the product at an addend's half ulp */
        const int e = (int)pe + 50 + (int)rbelow(6);
        if (e <= 2046) *z = ((rnd() & 1) << 63) | ((uint64_t)e << 52) | ((rnd() & 1) ? 0 : frac64());
    }
}
static uint32_t frac32(void) {
    switch (rbelow(8)) {
    case 0: return 0;
    case 1: return 0x7fffff;
    case 2: return (uint32_t)rnd() & 0x7fffff & ~((1u << (1 + rbelow(22))) - 1);
    case 3: return (1u << rbelow(23)) | ((uint32_t)rnd() & 1);
    default: return (uint32_t)rnd() & 0x7fffff;
    }
}
static uint32_t any32(void) {
    const uint32_t k = rbelow(100);
    const uint32_t sign = (uint32_t)(rnd() & 1) << 31;
    if (k < 4) return sign;
    if (k < 8) return sign | (frac32() ? frac32() : 1);
    if (k < 10) return sign | 0x7f800000u;
    if (k < 12) return sign | 0x7fc00000u | ((uint32_t)rnd() & 0x3fffff);
    if (k < 14) return sign | 0x7f800000u | (((uint32_t)rnd() & 0x3fffff) | 1);
    if (k < 17) return sign | ((rnd() & 1) ? 0x00800000u | ((uint32_t)rnd() & 3) : 0x7f7fffffu - ((uint32_t)rnd() & 3));
    if (k < 35) return sign | ((1 + rbelow(254)) << 23) | frac32();
    return sign | ((107 + rbelow(41)) << 23) | frac32();
}
static void triple32(uint32_t *a, uint32_t *b, uint32_t *z) {
    *a = any32(), *b = any32(), *z = any32();
    const uint32_t k = rbelow(100);
    if (k >= 60) return;
    const float p = f_of(*a) * f_of(*b);
    const uint32_t pb = f_bits(p), pe = (pb >> 23) & 0xff;
    if (pe == 0 || pe == 0xff) return;
    if (k < 20) {
        *z = (pb ^ 0x80000000u) + (uint32_t)((int)rbelow(9) - 4);
    } else if (k < 35) {
        const int e = (int)pe - 26 + (int)rbelow(6);
        if (e >= 1) *z = ((uint32_t)(rnd() & 1) << 31) | ((uint32_t)e << 23) | ((rnd() & 1) ? 0 : (rnd() & 3) ? frac32() : 1);
    } else if (k < 50) {
        const int e = (int)pe - 3 + (int)rbelow(7);
        if (e >= 1 && e <= 254) *z = ((uint32_t)(rnd() & 1) << 31) | ((uint32_t)e << 23) | frac32();
    } else {
        const int e = (int)pe + 21 + (int)rbelow(6);
        if (e <= 254) *z = ((uint32_t)(rnd() & 1) << 31) | ((uint32_t)e << 23) | ((rnd() & 1) ? 0 : frac32());
    }
}

/* ---- one comparison ---- */
static struct { long long checks, bad, exits, new_ixc, exact, fz; } st[2];   /* [0] binary64, [1] binary32 */
static void check(int w32, uint64_t a, uint64_t b, uint64_t z, uint64_t fpcr, uint64_t fpsr) {
    static Ctx base;
    Ctx on, off;
    if (!st[0].checks && !st[1].checks)   /* (the rest of the context: bytes that must stay as they are) */
        for (size_t i = 0; i < sizeof base; i++) ((uint8_t *)&base)[i] = (uint8_t)rnd();
    base.fpcr = fpcr, base.fpsr = fpsr;
    on = base, off = base;
    const long long before = fma_soft_test_exits;
    fma_soft_test_on = 1;
    const uint64_t von = w32 ? recomp_fpe_fma32(&on, a, b, z) : recomp_fpe_fma64(&on, a, b, z);
    const int took = fma_soft_test_exits != before;
    fma_soft_test_on = 0;
    const uint64_t voff = w32 ? recomp_fpe_fma32(&off, a, b, z) : recomp_fpe_fma64(&off, a, b, z);
    st[w32].checks++;
    if (took) {
        st[w32].exits++;
        st[w32].new_ixc += !(fpsr & 16u) && (on.fpsr & 16u);
        st[w32].exact += !(fpsr & 16u) && !(on.fpsr & 16u);
        st[w32].fz += (fpcr >> 24) & 1;
    }
    if (von != voff || memcmp(&on, &off, sizeof on)) {
        if (st[w32].bad++ < 8)
            printf("MISMATCH fma%d a %016llx b %016llx z %016llx fpcr %llx fpsr %llx: with the way out %016llx fpsr %llx, "
                   "without %016llx fpsr %llx\n", w32 ? 32 : 64, (unsigned long long)a, (unsigned long long)b,
                   (unsigned long long)z, (unsigned long long)fpcr, (unsigned long long)fpsr, (unsigned long long)von,
                   (unsigned long long)on.fpsr, (unsigned long long)voff, (unsigned long long)off.fpsr);
    }
}

static void random_cases(long long n) {
    for (long long i = 0; i < n; i++) {
        uint64_t a, b, z;
        uint32_t x, y, w;
        triple64(&a, &b, &z);
        check(0, a, b, z, rand_fpcr(), rand_fpsr());
        triple32(&x, &y, &w);
        check(1, x, y, w, rand_fpcr(), rand_fpsr());
    }
}

/* the sweep's addends, placed against the product p (kind k; i varies the sign and the last bits) */
static uint64_t addend64(double p, int k, unsigned i) {
    const uint64_t pb = d_bits(p), neg = pb ^ (UINT64_C(1) << 63), sign = (uint64_t)(i & 1) << 63;
    const int pe = (int)((pb >> 52) & 0x7ff);
    static const int rel[] = {-108, -106, -105, -56, -55, -54, -53, -52, -51, -2, -1, 0, 1, 2, 51, 52, 53, 54, 55, 106};
    if (k < 9) return neg + (uint64_t)(int64_t)(k - 4);                            /* -p within four ulps */
    if (k < 11) return (k == 9 ? pb : neg) ^ ((uint64_t)(i >> 1 & 1) << 52);       /* +-p, or its neighbour binade */
    k -= 11;
    if (k < 20) {   /* 2^rel times the product's binade: fraction 0 */
        const int e = pe + rel[k];
        return e >= 1 && e <= 2046 ? sign | ((uint64_t)e << 52) : sign | UINT64_C(0x3ff0000000000000);
    }
    k -= 20;
    {   /* the same with a fraction: 1, all ones */
        const int e = pe + rel[k % 20];
        const uint64_t f = k < 20 ? 1 : (UINT64_C(1) << 52) - 1;
        return e >= 1 && e <= 2046 ? sign | ((uint64_t)e << 52) | f : sign | UINT64_C(0x4000000000000000) | f;
    }
}
static uint32_t addend32(float p, int k, unsigned i) {
    const uint32_t pb = f_bits(p), neg = pb ^ 0x80000000u, sign = (uint32_t)(i & 1) << 31;
    const int pe = (int)((pb >> 23) & 0xff);
    static const int rel[] = {-50, -48, -47, -27, -26, -25, -24, -23, -22, -2, -1, 0, 1, 2, 22, 23, 24, 25, 26, 48};
    if (k < 9) return neg + (uint32_t)(k - 4);
    if (k < 11) return (k == 9 ? pb : neg) ^ ((uint32_t)(i >> 1 & 1) << 23);
    k -= 11;
    if (k < 20) {
        const int e = pe + rel[k];
        return e >= 1 && e <= 254 ? sign | ((uint32_t)e << 23) : sign | 0x3f800000u;
    }
    k -= 20;
    {
        const int e = pe + rel[k % 20];
        const uint32_t f = k < 20 ? 1 : 0x7fffff;
        return e >= 1 && e <= 254 ? sign | ((uint32_t)e << 23) | f : sign | 0x40000000u | f;
    }
}
enum { kKinds = 11 + 20 + 40 };
static void sweep(void) {
    static const uint32_t e64[] = {1, 2, 123, 542, 543, 544, 1000, 1022, 1023, 1024, 1050, 1502, 1503, 1504, 2046};
    static const uint64_t f64[] = {0, 1, 2, 3, (UINT64_C(1) << 26) - 1, UINT64_C(1) << 26, (UINT64_C(1) << 26) + 1,
                                   (UINT64_C(1) << 27) - 1, UINT64_C(1) << 51, (UINT64_C(1) << 52) - 1, (UINT64_C(1) << 52) - 2,
                                   UINT64_C(0x5555555555555), UINT64_C(0xaaaaaaaaaaaaa), UINT64_C(0x8000000000001),
                                   UINT64_C(0xfffffff800000), UINT64_C(0x921fb54442d18)};
    static const uint32_t e32[] = {1, 2, 24, 25, 64, 100, 126, 127, 128, 150, 190, 230, 253, 254};
    static const uint32_t f32[] = {0, 1, 2, 3, 0xfff, 0x1000, 0x1001, 0x400000, 0x7fffff, 0x7ffffe, 0x555555, 0x2aaaaa,
                                   0x400001, 0x7ff000, 0x490fdb};
    static const uint64_t fpcr[] = {0, 1u << 24, 0, 1u << 24}, fpsr[] = {0x1f, 0x1f, 0, 0x8f};
    const int ne = sizeof e64 / sizeof e64[0], nf = sizeof f64 / sizeof f64[0];
    unsigned i = 0;
    for (int ea = 0; ea < ne; ea++) for (int fa = 0; fa < nf; fa++)
        for (int eb = 0; eb < ne; eb++) for (int fb = 0; fb < nf; fb++) {
            const uint64_t a = ((uint64_t)e64[ea] << 52) | f64[fa] | ((uint64_t)(fa & 1) << 63);
            const uint64_t b = ((uint64_t)e64[eb] << 52) | f64[fb] | ((uint64_t)(eb & 1) << 63);
            const double p = d_of(a) * d_of(b);
            for (int k = 0; k < kKinds; k++, i++)
                check(0, a, b, addend64(p, k, i), fpcr[i & 3], fpsr[i & 3]);
        }
    const int me = sizeof e32 / sizeof e32[0], mf = sizeof f32 / sizeof f32[0];
    for (int ea = 0; ea < me; ea++) for (int fa = 0; fa < mf; fa++)
        for (int eb = 0; eb < me; eb++) for (int fb = 0; fb < mf; fb++) {
            const uint32_t a = (e32[ea] << 23) | f32[fa] | ((uint32_t)(fa & 1) << 31);
            const uint32_t b = (e32[eb] << 23) | f32[fb] | ((uint32_t)(eb & 1) << 31);
            const float p = f_of(a) * f_of(b);
            for (int k = 0; k < kKinds; k++, i++)
                check(1, a, b, addend32(p, k, i), fpcr[i & 3], fpsr[i & 3]);
        }
}

static double now_ns(void) {
#ifdef _WIN32
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f), QueryPerformanceCounter(&t);
    return (double)t.QuadPart * 1e9 / (double)f.QuadPart;
#else
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e9 + t.tv_nsec;
#endif
}
static void timing(void) {
    enum { kN = 4096, kRounds = 300 };
    static uint64_t a[kN], b[kN], z[kN];
    static Ctx c;
    for (int w32 = 0; w32 < 2; w32++) {
        for (int i = 0; i < kN; i++) {
            if (w32) a[i] = ((107 + rbelow(41)) << 23) | frac32(), b[i] = ((107 + rbelow(41)) << 23) | frac32(), z[i] = ((107 + rbelow(41)) << 23) | frac32();
            else a[i] = ((uint64_t)(983 + rbelow(81)) << 52) | frac64(), b[i] = ((uint64_t)(983 + rbelow(81)) << 52) | frac64(), z[i] = ((uint64_t)(983 + rbelow(81)) << 52) | frac64();
        }
        double ns[2];
        for (int on = 1; on >= 0; on--) {
            fma_soft_test_on = on;
            double best = 1e30;
            uint64_t sink = 0;
            for (int rep = 0; rep < 3; rep++) {
                const double t0 = now_ns();
                for (int r = 0; r < kRounds; r++)
                    for (int i = 0; i < kN; i++) sink += w32 ? recomp_fpe_fma32(&c, a[i], b[i], z[i]) : recomp_fpe_fma64(&c, a[i], b[i], z[i]);
                const double t = (now_ns() - t0) / ((double)kRounds * kN);
                if (t < best) best = t;
            }
            ns[on] = best;
            if (!sink) printf(" ");
        }
        printf("  recomp_fpe_fma%d, plain operands: %.1f ns with the way out, %.1f ns without (%.1fx)\n", w32 ? 32 : 64, ns[1], ns[0], ns[0] / ns[1]);
    }
}

int main(int argc, char **argv) {
    unsigned eax, ebx, ecx, edx;
#ifdef __SSE4_2__
    if (!__get_cpuid(1, &eax, &ebx, &ecx, &edx) || !(ecx >> 9 & 1) || !(ecx >> 20 & 1) || !(ecx >> 23 & 1)) {
        printf("this CPU has no SSSE3/SSE4.2/POPCNT\n");
        return 3;
    }
#endif
#ifdef __FMA__
    if (!__get_cpuid(1, &eax, &ebx, &ecx, &edx) || !(ecx >> 12 & 1)) {
        printf("this CPU has no FMA\n");
        return 3;
    }
#endif
    (void)eax, (void)ebx, (void)ecx, (void)edx;
    if (argc == 2 && !strcmp(argv[1], "env")) {   /* (built without the hook: HOS_FMA_FAST as the game reads it) */
        Ctx c;
        memset(&c, 0, sizeof c);
        uint64_t sink = 0;
        for (int i = 0; i < 1000; i++)
            sink += recomp_fpe_fma64(&c, d_bits(1.5 + i), d_bits(3.25), d_bits(0.1)) + recomp_fpe_fma32(&c, f_bits(1.5f + i), f_bits(3.25f), f_bits(0.1f));
        printf("fma64=%d exits=%lld sum=%llx\n", RECOMP_FPX_FMA64, fma_soft_test_exits, (unsigned long long)sink);
        return 0;
    }
    if (argc == 2 && !strcmp(argv[1], "time")) { timing(); return 0; }
    if (argc == 4 && !strcmp(argv[1], "random")) {
        rs = strtoull(argv[3], 0, 10);
        if (!rs) rs = 1;
        random_cases(atoll(argv[2]));
    } else if (argc == 2 && !strcmp(argv[1], "sweep")) {
        sweep();
    } else {
        fprintf(stderr, "usage: random <n> <seed> | sweep | env | time\n");
        return 2;
    }
    for (int w = 0; w < 2; w++)
        printf("%s fma%d fma64=%d checks=%lld mismatches=%lld exits=%lld new_ixc=%lld exact=%lld fz=%lld\n", argv[1], w ? 32 : 64,
               RECOMP_FPX_FMA64, st[w].checks, st[w].bad, st[w].exits, st[w].new_ixc, st[w].exact, st[w].fz);
    return st[0].bad || st[1].bad ? 1 : 0;
}
