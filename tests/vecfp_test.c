/* tests/test_vecfp.py's driver ((Triforce, 11-22, the performance audit's LIFT-03)): each guest word as lifted with
   A64_VECFP=1 (its C behind an SSE helper's test, nx2/vecfp.py), as the kit's translator writes it (A64_VECFP unset) and
   with the exact body inline (translated with the fast path off). All three start from one random Ctx; the whole Ctx,
   every vector and general register, the flags and FPSR, must match after.

   vecfp_test <n> <seed>   n random states for each guest word. Half the states have ordinary numbers in every lane (so
                           the helper does the op), half any operand in any lane: zeros of both signs, subnormals,
                           infinities, NaNs of both kinds with payloads, the extreme normals, any exponent, equal operands,
                           products at the underflow and overflow edges, cancelling multiply-adds; FPCR mostly 0 or FZ,
                           sometimes any other control bit; FPSR with IXC (the gate) set three times in four; NZCV through
                           all sixteen combinations.
   It prints, for each word, how many states the helper did (counted by A64_VFPX_Q_PROBE).
   Exit 0: no mismatch. 1: a mismatch. 3: this CPU cannot run the build. */
#include <stdint.h>
static long long vq_done;
#define A64_VFPX_Q_PROBE() (vq_done++)
#include "a64.h"
#include <stdio.h>
#include <stdlib.h>
#include <cpuid.h>
#include "vecfp_lifted.h"

static uint64_t rs = 1;
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }
static uint32_t rbelow(uint32_t n) { return (uint32_t)(((rnd() >> 32) * n) >> 32); }
static float f_of(uint32_t x) { float f; memcpy(&f, &x, 4); return f; }
static uint32_t f_bits(float f) { uint32_t x; memcpy(&x, &f, 4); return x; }

static uint64_t rand_fpcr(void) {
    static const uint64_t bits[] = {1u << 22, 1u << 23, 3u << 22, 1u << 25, 1u << 26, 1, 2, 4, 1u << 8, 1u << 9, 1u << 10,
                                    1u << 11, 1u << 12, 1u << 15, 1u << 19, UINT64_C(1) << 32};
    const uint32_t k = rbelow(100);
    if (k < 45) return 0;
    if (k < 80) return 1u << 24;                                                   /* FZ alone */
    uint64_t v = bits[rbelow(sizeof bits / sizeof bits[0])];
    if (rnd() & 1) v |= 1u << 24;
    if (!(rnd() & 3)) v |= bits[rbelow(sizeof bits / sizeof bits[0])];
    return v;
}
static uint64_t rand_fpsr(void) {
    uint64_t v = rnd() & 0x9f;
    if (!(rnd() & 3)) v |= 1u << 27;
    return (rnd() & 3) ? v | 16u : v & ~(uint64_t)16u;
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
static uint32_t ord32(void) { return ((uint32_t)(rnd() & 1) << 31) | ((117 + rbelow(21)) << 23) | frac32(); }
static uint32_t any32(void) {
    const uint32_t k = rbelow(100);
    const uint32_t sign = (uint32_t)(rnd() & 1) << 31;
    if (k < 8) return sign;                                                        /* zero */
    if (k < 15) return sign | (frac32() ? frac32() : 1);                           /* subnormal (or zero) */
    if (k < 20) return sign | 0x7f800000u;                                         /* infinity */
    if (k < 24) return sign | 0x7fc00000u | ((uint32_t)rnd() & 0x3fffff);          /* quiet NaN */
    if (k < 28) return sign | 0x7f800000u | (((uint32_t)rnd() & 0x3fffff) | 1);    /* signalling NaN */
    if (k < 34) return sign | ((rnd() & 1) ? 0x00800000u | ((uint32_t)rnd() & 3) : 0x7f7fffffu - ((uint32_t)rnd() & 3));
    if (k < 55) return sign | ((1 + rbelow(254)) << 23) | frac32();                /* any exponent */
    return ord32();
}
static uint64_t frac64(void) {
    switch (rbelow(6)) {
    case 0: return 0;
    case 1: return (UINT64_C(1) << 52) - 1;
    case 2: return (rnd() & ((UINT64_C(1) << 52) - 1)) & ~((UINT64_C(1) << (1 + rbelow(51))) - 1);   /* (often a binary32 number) */
    default: return rnd() & ((UINT64_C(1) << 52) - 1);
    }
}
static uint64_t ord64(void) { return ((rnd() & 1) << 63) | ((uint64_t)(1003 + rbelow(41)) << 52) | frac64(); }
static uint64_t any64(void) {
    const uint32_t k = rbelow(100);
    const uint64_t sign = (rnd() & 1) << 63;
    static const uint32_t edge[] = {1, 2, 872, 873, 874, 895, 896, 897, 898, 1023, 1149, 1150, 1151, 1152, 2045, 2046};
    if (k < 8) return sign;
    if (k < 15) return sign | (frac64() ? frac64() : 1);
    if (k < 20) return sign | UINT64_C(0x7ff0000000000000);
    if (k < 24) return sign | UINT64_C(0x7ff8000000000000) | (rnd() & ((UINT64_C(1) << 51) - 1));
    if (k < 28) return sign | UINT64_C(0x7ff0000000000000) | ((rnd() & ((UINT64_C(1) << 51) - 1)) | 1);
    if (k < 45) return sign | ((uint64_t)edge[rbelow(sizeof edge / sizeof edge[0])] << 52) | frac64();   /* binary32's edges */
    if (k < 60) return sign | ((uint64_t)(1 + rbelow(2046)) << 52) | frac64();
    return ord64();
}

/* the operands of case k into the context: rn, rm and (the multiply-adds' addend) rd */
static void operands(Ctx *c, int k, int mixed) {
    const int rd = CASES[k].rd, rn = CASES[k].rn, rm = CASES[k].rm;
    if (CASES[k].dbl) {   /* (FCVT Sd, Dn and FCVTN: binary64 lanes) */
        for (int h = 0; h < 2; h++) c->vreg[rn][h] = mixed ? any64() : ord64();
        return;
    }
    uint32_t a[4], b[4], z[4];
    for (int l = 0; l < 4; l++) {
        a[l] = mixed ? any32() : ord32(), b[l] = mixed ? any32() : ord32(), z[l] = mixed ? any32() : ord32();
        const uint32_t pick = mixed ? rbelow(16) : 15;
        if (pick == 0) b[l] = a[l];                                               /* equal operands */
        else if (pick == 1) b[l] = a[l] ^ 0x80000000u;                            /* a and -a (min and max of zeros among them) */
        else if (pick == 2) z[l] = f_bits(-(f_of(a[l]) * f_of(b[l]))) + (uint32_t)((int)rbelow(5) - 2);   /* a cancelling addend */
        else if (pick == 3) a[l] = ((1 + rbelow(40)) << 23) | frac32(), b[l] = ((87 + rbelow(40)) << 23) | frac32();   /* a tiny product or a huge quotient */
        else if (pick == 4) a[l] = ((200 + rbelow(54)) << 23) | frac32(), b[l] = ((150 + rbelow(54)) << 23) | frac32();   /* a huge product */
    }
    memcpy(c->vreg[rd], z, 16);   /* (rd first: where rd is rn or rm the addend is that operand, as in the guest) */
    memcpy(c->vreg[rm], b, 16);
    memcpy(c->vreg[rn], a, 16);
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
    const long n = argc > 1 ? atol(argv[1]) : 20000;
    rs = argc > 2 ? strtoull(argv[2], 0, 10) : 1;
    if (!rs) rs = 1;
    const int ncases = (int)(sizeof CASES / sizeof CASES[0]);
    long long bad = 0, checks = 0;
#if defined(__FMA__)
    const int fma = 1;
#else
    const int fma = 0;
#endif
    for (int k = 0; k < ncases; k++) {
        long long done = 0;
        for (long i = 0; i < n; i++) {
            static Ctx base, a, b, e;
            for (int v = 0; v < 32; v++) base.vreg[v][0] = rnd(), base.vreg[v][1] = rnd();
            for (int x = 0; x < 31; x++) base.x[x] = rnd();
            operands(&base, k, (int)(i & 1));
            base.n = (uint8_t)(i >> 1 & 1), base.z = (uint8_t)(i >> 2 & 1), base.c = (uint8_t)(i >> 3 & 1), base.v = (uint8_t)(i >> 4 & 1);
            base.fpcr = rand_fpcr(), base.fpsr = rand_fpsr();
            a = base, b = base, e = base;
            const long long before = vq_done;
            CASES[k].now(&a);
            done += vq_done - before;
            CASES[k].old(&b);
            CASES[k].exact(&e);
            checks++;
            const int da = memcmp(&a, &e, sizeof a) != 0, db = memcmp(&b, &e, sizeof b) != 0;
            if ((da || db) && bad++ < 8) {
                const int rd = CASES[k].rd, rn = CASES[k].rn, rm = CASES[k].rm;
                printf("MISMATCH %s (%s%s against the exact body): fpcr %llx fpsr %llx -> now %llx kit %llx exact %llx\n"
                       "  rn %016llx%016llx rm %016llx%016llx rd %016llx%016llx\n  now %016llx%016llx kit %016llx%016llx exact %016llx%016llx\n",
                       CASES[k].name, da ? "now " : "", db ? "kit " : "", (unsigned long long)base.fpcr, (unsigned long long)base.fpsr,
                       (unsigned long long)a.fpsr, (unsigned long long)b.fpsr, (unsigned long long)e.fpsr,
                       (unsigned long long)base.vreg[rn][1], (unsigned long long)base.vreg[rn][0], (unsigned long long)base.vreg[rm][1],
                       (unsigned long long)base.vreg[rm][0], (unsigned long long)base.vreg[rd][1], (unsigned long long)base.vreg[rd][0],
                       (unsigned long long)a.vreg[rd][1], (unsigned long long)a.vreg[rd][0], (unsigned long long)b.vreg[rd][1],
                       (unsigned long long)b.vreg[rd][0], (unsigned long long)e.vreg[rd][1], (unsigned long long)e.vreg[rd][0]);
            }
        }
        printf("case %d done %lld of %ld: %s\n", k, done, n, CASES[k].name);
    }
    printf("total fma=%d words=%d checks=%lld mismatches=%lld\n", fma, ncases, checks, bad);
    return bad ? 1 : 0;
}
