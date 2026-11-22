"""(Triforce, 11-22, the performance audit's LIFT-06, after Source A's) A short way out of the exact fused multiply-add
bodies on a CPU without FMA3.

Where the build has no hardware FMA (x86-64-v2: RECOMP_FPX_FMA64 is 0) the kit's double-precision fast path declines every
FMADD, and the single-precision one declines what its binary64 form cannot prove (a binary32 midpoint, a closed gate), so
those calls run the exact bodies recomp_fpe_fma64 and recomp_fpe_fma32: integer code of many words, about 180 ns a call
by Source A's figure on an i7-3770, 13.7% of a core in its walk. Most of those calls are the plain case, which this
answers first, in the body's first lines:

  - only under the default FPCR (no bit of RECOMP_FPX_FPCR_MASK; FZ may be set), with three normal operands (no zero,
    subnormal, infinity or NaN) and, for binary64, factors whose exponents leave the product and its error exact;
  - binary64: the product as an exact pair (Dekker's, from Veltkamp's split), the addend added without error (TwoSum), the
    two small terms added and rounded to odd, then one rounding to nearest (Boldo and Melquiond's emulation of an FMA);
  - binary32: the product is exact in binary64; the addend is added there with its error, the sum rounded to odd, and one
    rounding to binary32;
  - kept only when the result is a normal finite number above the smallest normal (so neither overflow nor underflow, and
    FZ changes nothing); FPSR.IXC is set when the result is not the exact value, and no other flag can be raised;
  - anything else goes on into the exact body, unchanged.

The kit's files stay as they are (third_party/ is not edited): install(), called from nx2/lift.py, wraps the kit's
a64_rtgen.runtime_c and puts HEADER after its `#include "a64.h"` and one EARLY line group after each body's head, each
place required to be there exactly once, so a refreshed kit that moved them stops the lift with a message.

Switches: A64_NO_FMA_SOFT=1 at lift time (in the lift key, an A64_ name) leaves the kit's runtime text as it is.
HOS_FMA_FAST=0 when the game runs (read once) sends every call to the exact body. Where the build has FMA3 (x86-64-v3)
none of this is compiled. tests/test_fma_soft.py runs both bodies with the way out against without it."""
import os

import a64_rtgen

HEADER = r"""
/* ---- (Triforce, 11-22, the performance audit's LIFT-06, after Source A's) the exact fused multiply-add bodies' short way
   out where the CPU has no FMA3 (nx2/fma_soft.py): the plain case (default FPCR, FZ or not; normal operands; a normal
   result) by an exact product and sum in binary64, rounded to odd, then rounded once. 1 and the result's bits when it
   answers (FPSR.IXC set when inexact), 0 for the exact body. HOS_FMA_FAST=0: never. ---- */
#if RECOMP_FPX_HOST == 2 && !RECOMP_FPX_FMA64
#define RECOMP_FMA_SOFT 1
#include <stdlib.h>
#if defined(__clang__)
#pragma STDC FP_CONTRACT OFF
#endif
#ifndef RECOMP_FMA_SOFT_PROBE
#define RECOMP_FMA_SOFT_PROBE() ((void)0) /* (tests/test_fma_soft.py counts the calls answered here) */
#endif
#ifndef RECOMP_FMA_SOFT_ON
static int recomp_fma_soft_on(void) {   /* (read once; a race reads the same value twice) */
    static int on = -1;
    int v = __atomic_load_n(&on, __ATOMIC_RELAXED);
    if (v < 0) {
        const char *e = getenv("HOS_FMA_FAST");
        v = !(e && e[0] == '0' && !e[1]);
        __atomic_store_n(&on, v, __ATOMIC_RELAXED);
    }
    return v;
}
#define RECOMP_FMA_SOFT_ON() recomp_fma_soft_on()
#endif
/* (a sum's result moved to the neighbour with an odd last bit, on the side its error lies, when it is inexact and even) */
static inline double recomp_fma_soft_odd(double s, double err) {
    uint64_t u = recomp_fpx_db(s);
    if (!(u & 1u)) u += ((err > 0.0) == (s > 0.0)) ? 1u : (uint64_t)-1;
    return recomp_fpx_d(u);
}
static inline int recomp_fma_soft64(GuestContext *c, uint64_t a, uint64_t b, uint64_t z, uint64_t *out) {
    /* (the factors' biased exponents 543 to 1503: the split cannot overflow, the product is 2^-960 to 2^962 and its error
       term is exact; the addend any normal number) */
    if ((c->fpcr & RECOMP_FPX_FPCR_MASK) || (uint32_t)(((uint32_t)(a >> 52) & 0x7ffu) - 543u) > 960u ||
        (uint32_t)(((uint32_t)(b >> 52) & 0x7ffu) - 543u) > 960u || (uint32_t)(((uint32_t)(z >> 52) & 0x7ffu) - 1u) > 2045u ||
        !RECOMP_FMA_SOFT_ON())
        return 0;
    const double x = recomp_fpx_d(a), y = recomp_fpx_d(b), w = recomp_fpx_d(z);
    /* x * y = ph + pl exactly */
    const double ph = x * y;
    const double xt = x * 134217729.0, xh = xt - (xt - x), xl = x - xh;
    const double yt = y * 134217729.0, yh = yt - (yt - y), yl = y - yh;
    const double pl = (((xh * yh - ph) + xh * yl) + xl * yh) + xl * yl;
    /* w + ph = th + tl exactly */
    const double th = w + ph, tv = th - w, tl = (w - (th - tv)) + (ph - tv);
    /* v = tl + pl rounded to odd */
    double v = tl + pl;
    const double vv = v - tl, ve = (tl - (v - vv)) + (pl - vv);
    if (ve != 0.0) v = recomp_fma_soft_odd(v, ve);
    /* the result, rounded once; its own error for IXC */
    const double r = th + v, rv = r - th, re = (th - (r - rv)) + (v - rv);
    const uint64_t t = recomp_fpx_db(r);
    if (!RECOMP_FPX_BIG64(t)) return 0;
    if (ve != 0.0 || re != 0.0) c->fpsr |= 16u;
    RECOMP_FMA_SOFT_PROBE();
    *out = t;
    return 1;
}
static inline int recomp_fma_soft32(GuestContext *c, uint64_t a, uint64_t b, uint64_t z, uint64_t *out) {
    if ((c->fpcr & RECOMP_FPX_FPCR_MASK) || (uint32_t)(((uint32_t)a & 0x7f800000u) - 0x00800000u) >= 0x7f000000u ||
        (uint32_t)(((uint32_t)b & 0x7f800000u) - 0x00800000u) >= 0x7f000000u ||
        (uint32_t)(((uint32_t)z & 0x7f800000u) - 0x00800000u) >= 0x7f000000u || ((a | b | z) >> 32) || !RECOMP_FMA_SOFT_ON())
        return 0;
    const double p = (double)recomp_fpx_f(a) * (double)recomp_fpx_f(b);   /* (exact: 48 bits) */
    const double w = (double)recomp_fpx_f(z);
    double s = p + w;
    const double sv = s - p, se = (p - (s - sv)) + (w - sv);
    if (se != 0.0) s = recomp_fma_soft_odd(s, se);
    const float r = (float)s;
    const uint32_t t = (uint32_t)recomp_fpx_fb(r);
    if (!RECOMP_FPX_BIG32(t)) return 0;
    if (se != 0.0 || (double)r != s) c->fpsr |= 16u;
    RECOMP_FMA_SOFT_PROBE();
    *out = t;
    return 1;
}
#endif
"""

INCLUDE = '#include "a64.h"\n'
HEAD = "RECOMP_FPE_COLD uint64_t recomp_fpe_fma%d(GuestContext* c,uint64_t _a,uint64_t _b,uint64_t _z){uint64_t _v=0;\n"
EARLY = ("#ifdef RECOMP_FMA_SOFT\n"
         "{ uint64_t _s; if (recomp_fma_soft%d(c, _a, _b, _z, &_s)) return _s; }   /* (Triforce, LIFT-06: nx2/fma_soft.py) */\n"
         "#endif\n")


def patch(text):
    """The kit's runtime C with the header and the two ways out; the kit's own text with A64_NO_FMA_SOFT=1"""
    if os.environ.get("A64_NO_FMA_SOFT"):
        return text
    places = [(INCLUDE, INCLUDE + HEADER)] + [(HEAD % n, HEAD % n + EARLY % n) for n in (32, 64)]
    for old, new in places:
        if text.count(old) != 1:   # (the kit changed: the lift must not go on with half of it)
            raise SystemExit("fma_soft: %r is %d times in the kit's runtime C (expected once): update nx2/fma_soft.py"
                             % (old.strip()[:70], text.count(old)))
        text = text.replace(old, new)
    return text


_installed = False


def install():
    """patch() around the kit's a64_rtgen.runtime_c, which its write() calls by name. Once"""
    global _installed
    if _installed:
        return
    _installed = True
    base = a64_rtgen.runtime_c

    def runtime_c():
        return patch(base())

    a64_rtgen.runtime_c = runtime_c
