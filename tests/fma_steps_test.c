/* tests/test_fma_steps.py's driver ((Triforce, 11-22, the performance audit's LIFT-05)): guest FRECPS and FRSQRTS words
   compiled against the runtime header nx2/fma_steps.py writes (now_*) and against the kit's (old_*), tests/fma_steps_side.c
   built twice.

   fma_steps_test lifted <n> <seed>   n random states for each guest word: the word as lifted and as a hot function has
                                      it, on both sides, and the exact body inline; the whole Ctx must be the same in all
   fma_steps_test direct <n> <seed>   the two fast paths by themselves on n operand pairs each, FZ on and off: what both
                                      sides keep must be the same bits, what either keeps must be the exact body's value
                                      with FPSR untouched, and the old side must keep nothing the new one declines, but
                                      for an FRSQRTS step of 2^127 or more: there the fused 3 - a*b is past binary32
                                      before its halving, the new side declines, and the exact body answers
   Operands: zeros, subnormals, infinities, NaNs of both kinds with payloads, the extreme normals, any exponent, products
   near 2 and near 3 (the step cancels), and pairs whose step is exactly a binary32 midpoint in binary64.
   Exit 0: no mismatch. 1: a mismatch. 3: this CPU cannot run the build. */
#include "a64.h"
#include <stdio.h>
#include <stdlib.h>
#include <cpuid.h>

#define SIDE_DECL(s) \
    void s##_run(int k, int form, Ctx *c); int s##_count(void); const char *s##_name(int k); int s##_rn(int k); \
    int s##_rm(int k); int s##_dbl(int k); int s##_recps32(uint64_t, uint64_t, uint32_t, uint64_t *); \
    int s##_rsqrts32(uint64_t, uint64_t, uint32_t, uint64_t *); int s##_fma(void);
SIDE_DECL(now)
SIDE_DECL(old)

static uint64_t rs = 1;
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }
static uint32_t rbelow(uint32_t n) { return (uint32_t)(((rnd() >> 32) * n) >> 32); }
static float f_of(uint32_t x) { float f; memcpy(&f, &x, 4); return f; }
static uint32_t f_bits(float f) { uint32_t x; memcpy(&x, &f, 4); return x; }

static uint64_t rand_fpcr(void) {
    static const uint64_t bits[] = {1u << 22, 1u << 23, 3u << 22, 1u << 25, 1u << 26, 1, 2, 4, 1u << 8, 1u << 9, 1u << 10,
                                    1u << 11, 1u << 12, 1u << 15, 1u << 19, UINT64_C(1) << 32};
    const uint32_t k = rbelow(100);
    if (k < 50) return 0;
    if (k < 85) return 1u << 24;                                                   /* FZ alone */
    uint64_t v = bits[rbelow(sizeof bits / sizeof bits[0])];
    if (rnd() & 1) v |= 1u << 24;
    return v;
}
static uint64_t rand_fpsr(void) {   /* (IXC set, the fast path's gate, three times in four) */
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
    return sign | ((117 + rbelow(21)) << 23) | frac32();
}
/* a pair for a step: step 2 for FRECPS (2 - a*b), 3 for FRSQRTS ((3 - a*b) / 2) */
static void pair32(int step, uint32_t *a, uint32_t *b) {
    const uint32_t k = rbelow(100);
    *a = any32(), *b = any32();
    if (k < 40) return;
    if (k < 60) {   /* the step exactly a binary32 midpoint in binary64 (the pairs the binary64 form declines) */
        const uint32_t i = rbelow(512) * 2 + 1, j = rbelow(256) * 2 + 1;
        if (step == 2) *a = 0x3f800000u | (i << 11), *b = 0xbf800000u | (j << 12);   /* (1 + i/2^12) * -(1 + j/2^11) */
        else *a = 0x3f800000u | (i << 11), *b = 0x3f800000u | (j << 11);             /* (1 + i/2^12) * (1 + j/2^12) */
        if (rnd() & 1) { const uint32_t t = *a; *a = *b, *b = t; }
        return;
    }
    if (k < 80) {   /* a*b near the step's constant: the step cancels (a tiny, subnormal or zero result) */
        const uint32_t x = ((120 + rbelow(15)) << 23) | frac32();
        const uint32_t y = f_bits((float)step / f_of(x)) + (uint32_t)((int)rbelow(9) - 4);
        *a = x, *b = y;
        if (rnd() & 1) *a ^= 0x80000000u, *b ^= 0x80000000u;
        return;
    }
    if (k < 90) {   /* a large or a small product */
        *a = ((rnd() & 1 ? 180 + rbelow(74) : 1 + rbelow(60)) << 23) | frac32() | ((uint32_t)(rnd() & 1) << 31);
        *b = ((rnd() & 1 ? 180 + rbelow(74) : 1 + rbelow(60)) << 23) | frac32() | ((uint32_t)(rnd() & 1) << 31);
        return;
    }
    *a = ((122 + rbelow(11)) << 23) | frac32() | ((uint32_t)(rnd() & 1) << 31);   /* ordinary: the step is an ordinary number */
    *b = ((122 + rbelow(11)) << 23) | frac32() | ((uint32_t)(rnd() & 1) << 31);
}
static uint64_t any64(void) {
    const uint32_t k = rbelow(100);
    const uint64_t sign = (rnd() & 1) << 63, frac = rnd() & ((UINT64_C(1) << 52) - 1);
    if (k < 4) return sign;
    if (k < 8) return sign | (frac >> rbelow(52)) | 1;
    if (k < 10) return sign | UINT64_C(0x7ff0000000000000);
    if (k < 14) return sign | UINT64_C(0x7ff0000000000000) | (frac | 1);
    if (k < 30) return sign | ((uint64_t)(1 + rbelow(2046)) << 52) | frac;
    return sign | ((uint64_t)(1013 + rbelow(21)) << 52) | ((rnd() & 3) ? frac : 0);
}

static int lifted(long n) {
    const int ncases = now_count();
    long long checks = 0, bad = 0;
    for (int k = 0; k < ncases; k++) {
        const int rn = now_rn(k), rm = now_rm(k), dbl = now_dbl(k);
        const int step = strstr(now_name(k), "FRSQRTS") ? 3 : 2;
        for (long i = 0; i < n; i++) {
            static Ctx base, r[5];
            for (int v = 0; v < 32; v++) base.vreg[v][0] = rnd(), base.vreg[v][1] = rnd();
            if (dbl) {
                for (int h = 0; h < 2; h++) base.vreg[rn][h] = any64(), base.vreg[rm][h] = any64();
            } else {
                uint32_t a[4], b[4];
                for (int l = 0; l < 4; l++) pair32(step, &a[l], &b[l]);
                memcpy(base.vreg[rm], b, 16);   /* (rm first: where rn is rm the pairs are (a, a)) */
                memcpy(base.vreg[rn], a, 16);
            }
            for (int x = 0; x < 31; x++) base.x[x] = rnd();
            base.n = (uint8_t)(i & 1), base.z = (uint8_t)(i >> 1 & 1), base.c = (uint8_t)(i >> 2 & 1), base.v = (uint8_t)(i >> 3 & 1);
            base.fpcr = rand_fpcr(), base.fpsr = rand_fpsr();
            for (int j = 0; j < 5; j++) r[j] = base;
            now_run(k, 0, &r[0]), now_run(k, 1, &r[1]), old_run(k, 0, &r[2]), old_run(k, 1, &r[3]), now_run(k, 2, &r[4]);
            checks++;
            int diff = 0;
            for (int j = 0; j < 4; j++) diff |= memcmp(&r[j], &r[4], sizeof r[0]) ? 1 << j : 0;
            if (diff && bad++ < 8) {
                static const char *const who[4] = {"now", "now hot", "old", "old hot"};
                for (int j = 0; j < 4; j++)
                    if (diff >> j & 1)
                        printf("MISMATCH %s (%s against the exact body): fpcr %llx fpsr %llx; rn %016llx%016llx rm %016llx%016llx\n",
                               now_name(k), who[j], (unsigned long long)base.fpcr, (unsigned long long)base.fpsr,
                               (unsigned long long)base.vreg[rn][1], (unsigned long long)base.vreg[rn][0],
                               (unsigned long long)base.vreg[rm][1], (unsigned long long)base.vreg[rm][0]);
            }
        }
    }
    printf("lifted fused=%d shapes=%d checks=%lld mismatches=%lld\n", now_fma(), ncases, checks, bad);
    return bad ? 1 : 0;
}

static struct { long long checks, kept_now, kept_old, now_only, old_only, bad; } st;
static void one(int half, uint32_t a, uint32_t b, uint32_t fz) {
    uint64_t vn = 0, vo = 0;
    const int kn = half ? now_rsqrts32(a, b, fz, &vn) : now_recps32(a, b, fz, &vn);
    const int ko = half ? old_rsqrts32(a, b, fz, &vo) : old_recps32(a, b, fz, &vo);
    st.checks++, st.kept_now += kn, st.kept_old += ko, st.now_only += kn && !ko, st.old_only += ko && !kn;
    int bad = (kn && ko && vn != vo) || (ko && !kn && !(half && (vo & 0x7f800000u) == 0x7f000000u));
    if (kn || ko) {   /* (what a fast path keeps is Arm's value, and the exact body raises no new flag for it) */
        Ctx c;
        memset(&c, 0, sizeof c);
        c.fpcr = fz, c.fpsr = 0x10 | (rnd() & 0x8f);
        const uint64_t s = c.fpsr;
        const uint64_t e = half ? recomp_fpe_rsqrts32(&c, a, b) : recomp_fpe_recps32(&c, a, b);
        bad |= (kn && vn != e) || (ko && vo != e) || c.fpsr != s;
    }
    if (bad && st.bad++ < 8)
        printf("MISMATCH %s a %08x b %08x fz %d: now %d %08llx, old %d %08llx\n", half ? "rsqrts32" : "recps32", a, b, fz != 0, kn,
               (unsigned long long)vn, ko, (unsigned long long)vo);
}
static int direct(long n) {
    /* the audit's two midpoint pairs first: kept by the fused form, declined by the binary64 one */
    static const uint32_t named[2][2] = {{0x3f800800u, 0xbf801000u}, {0x3f800800u, 0x3f800800u}};
    int named_ok = 1;
    for (int half = 0; half < 2; half++) {
        uint64_t vn = 0, vo = 0;
        const int kn = half ? now_rsqrts32(named[1][0], named[1][1], 0, &vn) : now_recps32(named[0][0], named[0][1], 0, &vn);
        const int ko = half ? old_rsqrts32(named[1][0], named[1][1], 0, &vo) : old_recps32(named[0][0], named[0][1], 0, &vo);
        if (ko || kn != now_fma()) named_ok = 0;
        one(half, named[half][0], named[half][1], 0);
    }
    for (long i = 0; i < n; i++)
        for (int half = 0; half < 2; half++) {
            uint32_t a, b;
            pair32(half ? 3 : 2, &a, &b);
            one(half, a, b, (rnd() & 1) ? 0x01000000u : 0);
        }
    printf("direct fused=%d named=%d checks=%lld kept_now=%lld kept_old=%lld now_only=%lld old_only=%lld mismatches=%lld\n", now_fma(),
           named_ok, st.checks, st.kept_now, st.kept_old, st.now_only, st.old_only, st.bad);
    return st.bad ? 1 : 0;
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
    if (argc != 4 || (strcmp(argv[1], "lifted") && strcmp(argv[1], "direct"))) {
        fprintf(stderr, "usage: lifted <n> <seed> | direct <n> <seed>\n");
        return 2;
    }
    rs = strtoull(argv[3], 0, 10);
    if (!rs) rs = 1;
    return argv[1][0] == 'l' ? lifted(atol(argv[2])) : direct(atol(argv[2]));
}
