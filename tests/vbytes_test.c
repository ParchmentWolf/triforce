/* tests/test_vbytes.py's driver ((Triforce, 11-21, the performance audit's LIFT-02)): each guest word as nx2/fastvec.py
   rewrites it (a64_tbl1, A64_EXT16, A64_EXT8, a64_vld16, a64_vdup) against the same word as the kit's translator writes
   it (A64_NO_VBYTES=1, A64_NO_VMOVES=1). Both start from one random Ctx and guest memory; every vector and general
   register must match after.

   vbytes_test <n> <seed>   n random states for each guest word; index bytes biased to the edges
   vbytes_test time         ns for each kind of guest word, now and as the kit writes it
   Exit 0: no mismatch. 1: a mismatch. 2: no guest memory where the loads read. */
#include "a64.h"
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <sys/mman.h>
#include <time.h>
#endif
#include "vbytes_lifted.h"

enum { kGuestLo = 0x10000, kGuestLen = 1 << 20 };   /* (the guest memory the loads read, at A64_PTR(kGuestLo)) */
static int map_at(void *p, size_t n) {
#ifdef _WIN32
    return VirtualAlloc(p, n, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE) == p;
#else
    return mmap(p, n, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) == p;
#endif
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
static uint64_t rs;
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }
static uint8_t edge_byte(void) {   /* (TBL's index: around 16, and around the 0x80 the saturated add makes of it) */
    static const uint8_t e[] = {0, 1, 7, 8, 14, 15, 16, 17, 31, 32, 0x6f, 0x70, 0x7f, 0x80, 0x8f, 0x90, 0xf0, 0xfe, 0xff};
    switch (rnd() % 4) {
    case 0: return e[rnd() % sizeof e];
    case 1: return (uint8_t)(rnd() % 16);
    default: return (uint8_t)rnd();
    }
}
static void fill(Ctx *c) {
    memset(c, 0, sizeof *c);
    for (int r = 0; r < 32; r++) {
        uint8_t b[16];
        for (int k = 0; k < 16; k++) b[k] = (rnd() & 1) ? edge_byte() : (uint8_t)rnd();
        memcpy(c->vreg[r], b, 16);
    }
    /* (the loads: guest addresses inside the mapped window, unaligned too; some of the memory new for each state) */
    for (int r = 0; r < 31; r++) c->x[r] = kGuestLo + 0x1000 + (rnd() % (kGuestLen - 0x2000));
    for (int k = 0; k < 64; k++) ((uint64_t *)A64_PTR(kGuestLo))[rnd() % (kGuestLen / 8)] = rnd();
}

int main(int argc, char **argv) {
    if (!map_at(A64_PTR(kGuestLo), kGuestLen)) {
        printf("no guest memory at %p\n", (void *)A64_PTR(kGuestLo));
        return 2;
    }
    for (uint64_t k = 0; k < kGuestLen / 8; k++) ((uint64_t *)A64_PTR(kGuestLo))[k] = k * 0x9e3779b97f4a7c15ULL;
    if (argc > 1 && !strcmp(argv[1], "time")) {   /* ns for each guest word, now and as the kit writes it: the best of 3 */
        static Ctx c;
        rs = 7;
        fill(&c);
        uint64_t x0[32];
        memcpy(x0, c.x, sizeof x0);
        const int iters = 400000, ncase = (int)(sizeof CASES / sizeof CASES[0]);
        double sum[4][2] = {{0}};
        int count[4] = {0};
        for (int k = 0; k < ncase; k++) {
            const int kind = CASES[k].name[0] == 'T' ? 0 : CASES[k].name[0] == 'E' ? 1 : CASES[k].name[0] == 'L' ? 2 : 3;
            for (int w = 0; w < 2; w++) {
                double best = 1e30;
                void (*fn)(Ctx *) = w ? CASES[k].old : CASES[k].now;
                for (int rep = 0; rep < 3; rep++) {
                    const double t0 = now_ns();
                    for (int i = 0; i < iters; i += 1000) {   /* (x put back each 1000: a post-indexed load moves its base) */
                        memcpy(c.x, x0, sizeof x0);
                        for (int j = 0; j < 1000; j++) fn(&c);
                    }
                    const double ns = (now_ns() - t0) / iters;
                    if (ns < best) best = ns;
                }
                sum[kind][w] += best;
            }
            count[kind]++;
        }
        static const char *const kinds[4] = {"TBL", "EXT", "128-bit load", "DUP"};
        for (int k = 0; k < 4; k++)
            printf("  %-13s %3d words: now %5.2f ns, as the kit writes it %5.2f ns (%.1fx)\n", kinds[k], count[k], sum[k][0] / count[k],
                   sum[k][1] / count[k], sum[k][1] / sum[k][0]);
        return 0;
    }
    const long n = argc > 1 ? atol(argv[1]) : 200000;
    rs = argc > 2 ? strtoull(argv[2], 0, 10) : 1;
    if (!rs) rs = 1;
    const int ncases = (int)(sizeof CASES / sizeof CASES[0]);
    long bad = 0, checks = 0;
    for (int k = 0; k < ncases; k++)
        for (long i = 0; i < n; i++) {
            static Ctx a, b;
            fill(&a);
            b = a;
            CASES[k].now(&a);
            CASES[k].old(&b);
            checks++;
            if (memcmp(a.vreg, b.vreg, sizeof a.vreg) || memcmp(a.x, b.x, sizeof a.x)) {
                if (bad++ < 5) {
                    printf("MISMATCH %s:", CASES[k].name);
                    for (int r = 0; r < 32; r++)
                        if (memcmp(a.vreg[r], b.vreg[r], 16))
                            printf(" v%d now %016llx%016llx kit %016llx%016llx", r, (unsigned long long)a.vreg[r][1],
                                   (unsigned long long)a.vreg[r][0], (unsigned long long)b.vreg[r][1],
                                   (unsigned long long)b.vreg[r][0]);
                    printf("\n");
                }
            }
        }
    printf("%d guest words, %ld checks, %ld mismatches\n", ncases, checks, bad);
    return bad ? 1 : 0;
}
