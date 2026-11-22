/* tests/test_dmb_light.py's driver ((Triforce, 11-22, the performance audit's LIFT-47)): each shape (a barrier alone, or
   between a store and a load of the same guest address) as lifted with A64_DMB_LIGHT=1 against the same words as the
   kit's translator writes them. Both start from one random Ctx and guest memory; the whole Ctx and the bytes the shape
   stores must match after, and the calls of recomp_barrier (counted here) must be the kit's count without the light
   barriers' on x86-64.

   dmb_light_test <n> <seed>   n random states for each shape; the flags go through all sixteen combinations
   Exit 0: no mismatch. 1: a mismatch. 2: no guest memory where the shapes store. */
#include "a64.h"
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <sys/mman.h>
#endif

static long fences;   /* (the runtime's full fence, a64_rt.c's, counted) */
void recomp_barrier(void) {
    fences++;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
}
#include "dmb_lifted.h"

enum { kGuestLo = 0x10000, kGuestLen = 1 << 20 };   /* (the guest memory the shapes use, at A64_PTR(kGuestLo)) */
static int map_at(void *p, size_t n) {
#ifdef _WIN32
    return VirtualAlloc(p, n, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE) == p;
#else
    return mmap(p, n, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) == p;
#endif
}

static uint64_t rs;
static uint64_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }
static uint64_t edge64(void) {
    static const uint64_t e[] = {0, 1, 0x7fffffffffffffffULL, 0x8000000000000000ULL, ~0ULL, 0xffffffffULL, 0x100000000ULL};
    return (rnd() & 3) ? rnd() : e[rnd() % (sizeof e / sizeof e[0])];
}
static void fill(Ctx *c, long i) {
    memset(c, 0, sizeof *c);
    for (int r = 0; r < 31; r++) c->x[r] = edge64();
    c->x[2] = kGuestLo + 0x1000 + (rnd() % (kGuestLen - 0x2000));   /* (the shapes' base register: unaligned too) */
    c->x[31] = kGuestLo + 0x800;
    c->n = (uint8_t)(i & 1), c->z = (uint8_t)(i >> 1 & 1), c->c = (uint8_t)(i >> 2 & 1), c->v = (uint8_t)(i >> 3 & 1);
    for (int r = 0; r < 32; r++) c->vreg[r][0] = edge64(), c->vreg[r][1] = edge64();
    c->fpcr = (rnd() & 1) ? 0x01000000u : 0, c->fpsr = rnd() & 0x9f;
}

int main(int argc, char **argv) {
    if (!map_at(A64_PTR(kGuestLo), kGuestLen)) {
        printf("no guest memory at %p\n", (void *)A64_PTR(kGuestLo));
        return 2;
    }
    const long n = argc > 1 ? atol(argv[1]) : 20000;
    rs = argc > 2 ? strtoull(argv[2], 0, 10) : 1;
    if (!rs) rs = 1;
    const int ncases = (int)(sizeof CASES / sizeof CASES[0]);
#if defined(__x86_64__)
    const int host_light = 1;
#else
    const int host_light = 0;   /* (any other host: the light barrier is the full fence too) */
#endif
    long bad = 0, checks = 0;
    for (int k = 0; k < ncases; k++)
        for (long i = 0; i < n; i++) {
            static Ctx a, b;
            uint8_t before[16], ma[16], mb[16];
            fill(&a, i);
            b = a;
            uint8_t *mem = A64_PTR(a.x[2]);
            for (int j = 0; j < 16; j++) mem[j] = (uint8_t)rnd();
            memcpy(before, mem, 16);
            fences = 0;
            CASES[k].now(&a);
            const long fa = fences;
            memcpy(ma, mem, 16);
            memcpy(mem, before, 16);
            fences = 0;
            CASES[k].old(&b);
            const long fb = fences;
            memcpy(mb, mem, 16);
            checks++;
            const int state = memcmp(&a, &b, sizeof a) || memcmp(ma, mb, 16);
            const int count = fb != CASES[k].barriers || fa != CASES[k].barriers - (host_light ? CASES[k].light : 0);
            if (state || count) {
                if (bad++ < 5)
                    printf("MISMATCH %s: %s%sfences now %ld, kit %ld (of %d, %d light)\n", CASES[k].name,
                           state ? "registers, flags or memory differ; " : "", count ? "fence count; " : "", fa, fb,
                           CASES[k].barriers, CASES[k].light);
            }
        }
    printf("%d shapes, %ld checks, %ld mismatches\n", ncases, checks, bad);
    return bad ? 1 : 0;
}
