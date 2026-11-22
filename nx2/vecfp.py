"""(Triforce, 11-22, the performance audit's LIFT-03, after Source A's) SSE fast paths for the float forms the lifter
still writes lane by lane, behind A64_VECFP (off by default).

The kit turns straight FADD / FSUB, FMUL .4S and FMUL / FMLA / FMLS .4S by element into one SSE op with the scalar fast
path's tests on every lane (a64_lift.py's vectorize_fpx and vectorize_elem). These stay loops of one helper call a lane,
or exact integer code a lane:

  elem     FMUL, FMLA, FMLS .2S by element
  vec      FMUL .2S; FMLA and FMLS .2S and .4S; FDIV .2S and .4S
  minmax   FMAX, FMIN, FMAXNM, FMINNM: scalar S, .2S and .4S
  fcvt     FCVT S to D and D to S (scalar); FCVTL and FCVTL2 (.2S to .2D); FCVTN (.2D to .2S)

With A64_VECFP=1 (or a list of the groups above) each such instruction is lifted as

    if (!a64_vfpx_q_<form>(c, ...)) { <its C as before> }

The helper (HEADER, appended to a64_fpx.h) does the op in SSE and writes the register only when the result is provably
Arm's with no new FPSR bit, by the rules the kit's own helpers use (RECOMP_FPX_OPEN, RECOMP_FPX_KEEP32 / KEEPDIV32, no
subnormal operand under FZ); otherwise it writes nothing, returns 0, and the C as before runs:
  - multiplies, multiply-adds and divides: under the open gate (default FPCR but FZ, IXC already raised); a lane is kept
    when its result is a normal number above the smallest, or a finite result with a zero factor (dividend, for a divide);
    the multiply-adds are one fused op and need FMA3, without it they always decline;
  - min and max: under the default FPCR but FZ; kept unless a lane is a NaN or, under FZ, a subnormal. Zeros of both signs
    come out as Arm's (max of +0 and -0 is +0) by taking the op both ways round;
  - S to D: exact; kept unless the input is a NaN or, under FZ, a subnormal;
  - D to S: under the open gate; kept when the result is a normal number above the smallest, or the input is a zero.

The kit's files stay as they are (third_party/ is not edited): install(), called from nx2/lift.py after insn's, wraps
a64emit.translate (the word decides the form; the text behind the test is whatever the translator wrote, so no pattern
of its text is assumed) and a64_lift.fpx_header. A word whose text the kit's own passes already turn into a vector
helper is left alone (main_handles), so nothing is wrapped twice. The closing brace goes on the text's last line, never
at a line's start: nx2/oot_patches.py ends a function at the first `}` that starts a line.

A64_VECFP is read at lift time and is in the lift key (an A64_ name). Unset, empty or 0: the kit's text, the default
until it is measured in the game. tests/test_vecfp.py runs every form both ways and against the exact body."""
import os
import re

import a64emit
import a64_lift

GROUPS = ("elem", "vec", "minmax", "fcvt")


def groups():
    """The groups A64_VECFP turns on: none when unset, empty or 0; all for 1; else the listed ones"""
    v = os.environ.get("A64_VECFP", "0").strip()
    if v in ("", "0"):
        return frozenset()
    if v == "1":
        return frozenset(GROUPS)
    got = frozenset(p.strip() for p in v.split(",") if p.strip())
    if got - set(GROUPS):
        raise SystemExit("vecfp: A64_VECFP=%s: not 0, 1 or a list of %s" % (v, ", ".join(GROUPS)))
    return got


def fast_call(w, on):
    """The helper call for guest word w (C, nonzero when it did the op), or None: not one of the forms, or its group is off"""
    top = w & 0x1F000000
    if top not in (0x0E000000, 0x0F000000, 0x1E000000) or not on:
        return None
    rd, rn, rm = w & 31, (w >> 5) & 31, (w >> 16) & 31
    d, n, m = "c->vreg[%d]" % rd, "c->vreg[%d]" % rn, "c->vreg[%d]" % rm
    k = 4 if w & 0x40000000 else 2
    v = w & 0xBFE0FC00   # (the three-register vector forms of single precision, Q left out)
    if "vec" in on:
        if v == 0x2E20DC00 and k == 2:                    # FMUL .2S (.4S is the kit's a64_vfpx_mul32)
            return "a64_vfpx_q_mul(c,%s,%s,%s,2)" % (d, n, m)
        if v in (0x0E20CC00, 0x0EA0CC00):                 # FMLA, FMLS .2S / .4S
            return "a64_vfpx_q_fma(c,%s,%s,%s,%d,%d)" % (d, n, m, v == 0x0EA0CC00, k)
        if v == 0x2E20FC00:                               # FDIV .2S / .4S
            return "a64_vfpx_q_div(c,%s,%s,%s,%d)" % (d, n, m, k)
    if "minmax" in on:
        if v in (0x0E20F400, 0x0EA0F400, 0x0E20C400, 0x0EA0C400):   # FMAX, FMIN, FMAXNM, FMINNM .2S / .4S
            return "a64_vfpx_q_minmax(c,%s,%s,%s,%d,%d)" % (d, n, m, bool(v & 0x00800000), k)
        s = w & 0xFFE0FC00
        if s in (0x1E204800, 0x1E205800, 0x1E206800, 0x1E207800):   # FMAX, FMIN, FMAXNM, FMINNM S
            return "a64_vfpx_q_minmax(c,%s,%s,%s,%d,1)" % (d, n, m, bool(s & 0x00001000))
    if "elem" in on:
        e = w & 0xFFC0F400   # (.2S by element: Q = 0, size = 10; L, M:Rm and H left out)
        if e in (0x0F809000, 0x0F801000, 0x0F805000):     # FMUL, FMLA, FMLS .2S by element
            index = ((w >> 11) & 1) << 1 | ((w >> 21) & 1)
            if e == 0x0F809000:
                return "a64_vfpx_q_mule(c,%s,%s,%s,%d,2)" % (d, n, m, index)
            return "a64_vfpx_q_fmae(c,%s,%s,%s,%d,%d,2)" % (d, n, m, index, e == 0x0F805000)
    if "fcvt" in on:
        u = w & 0xFFFFFC00
        if u == 0x1E22C000:                               # FCVT Dd, Sn
            return "a64_vfpx_q_cvtsd(c,%s,%s)" % (d, n)
        if u == 0x1E624000:                               # FCVT Sd, Dn
            return "a64_vfpx_q_cvtds(c,%s,%s)" % (d, n)
        if (w & 0xBFFFFC00) == 0x0E617800:                # FCVTL / FCVTL2 .2D from .2S
            return "a64_vfpx_q_cvtl(c,%s,%s,%d)" % (d, n, k == 4)
        if u == 0x0E616800:                               # FCVTN .2S from .2D (FCVTN2 keeps the low half: not one)
            return "a64_vfpx_q_cvtn(c,%s,%s)" % (d, n)
    return None


KIT_VECTOR = re.compile(r"\ba64_vfpx_(?!q_)\w+\(|\ba64_vfcmp\(")


def main_handles(text):
    """Whether the kit's own passes already turn this instruction's text into a vector helper (then it is not wrapped)"""
    return KIT_VECTOR.search(a64_lift.vectorize_elem(a64_lift.widen_vstores(a64_lift.vectorize_fpx(
        a64_lift.outline_fpx(text, set()))))) is not None


def wrap(text, call):
    """The instruction's text behind the helper's test. The closing brace stays on the text's last line"""
    return "if (!%s) { %s }\n" % (call, text.strip())


HEADER = r"""
/* ---- (Triforce, 11-22, the performance audit's LIFT-03, after Source A's) SSE fast paths for float forms lifted lane by
   lane (nx2/vecfp.py, A64_VECFP): each returns 1 when it did the op and wrote Vd, 0 with nothing written when the C behind
   it must run. k: the lanes (4, 2, or 1 for a scalar). A lane is kept by the scalar fast paths' rules. ---- */
#ifndef A64_VFPX_Q_PROBE
#define A64_VFPX_Q_PROBE() ((void)0) /* (tests/test_vecfp.py counts the ops done here) */
#endif
#if RECOMP_FPX_HOST == 2
#if defined(__FMA__)
#include <immintrin.h>
#endif
static inline __m128i a64_vq_ult(__m128i x, uint32_t k) {   /* unsigned x < k, per lane */
    return _mm_cmplt_epi32(_mm_xor_si128(x, _mm_set1_epi32((int)0x80000000u)), _mm_set1_epi32((int)(k ^ 0x80000000u)));
}
static inline __m128i a64_vq_abs(__m128i x) { return _mm_and_si128(x, _mm_set1_epi32(0x7fffffff)); }
static inline __m128i a64_vq_big(__m128i t) { return a64_vq_ult(_mm_sub_epi32(a64_vq_abs(t), _mm_set1_epi32(0x00800001)), 0x7effffffu); }
static inline __m128i a64_vq_zero(__m128i x) { return _mm_cmpeq_epi32(a64_vq_abs(x), _mm_setzero_si128()); }
static inline __m128i a64_vq_nonfin(__m128i t) { const __m128i e = _mm_set1_epi32(0x7f800000); return _mm_cmpeq_epi32(_mm_and_si128(t, e), e); }
static inline __m128i a64_vq_nan(__m128i x) { return _mm_cmpgt_epi32(a64_vq_abs(x), _mm_set1_epi32(0x7f800000)); }
static inline __m128i a64_vq_subn(__m128i x) { return a64_vq_ult(_mm_sub_epi32(_mm_slli_epi32(x, 1), _mm_set1_epi32(1)), 0x00ffffffu); }
/* an operand's low k lanes, repeated to fill the register: the unused lanes then hold what the used ones do, so every
   test is made on all four and no lane computes on bytes the instruction does not read */
static inline __attribute__((always_inline)) __m128i a64_vq_load(const uint64_t *p, int k) {
    if (k == 4) return _mm_loadu_si128((const __m128i *)p);
    if (k == 2) { const __m128i x = _mm_loadl_epi64((const __m128i *)p); return _mm_unpacklo_epi64(x, x); }
    return _mm_set1_epi32((int)(uint32_t)p[0]);
}
static inline __attribute__((always_inline)) __m128i a64_vq_lane(const uint64_t *p, int index) {   /* one lane in all four */
    uint32_t e;
    memcpy(&e, (const uint8_t *)p + 4 * index, 4);
    return _mm_set1_epi32((int)e);
}
/* the result's low k lanes into Vd, the rest of the register zero */
static inline __attribute__((always_inline)) void a64_vq_store(uint64_t *d, __m128i r, int k) {
    if (k == 4) _mm_storeu_si128((__m128i *)d, r);
    else if (k == 2) a64_vst_lo64(d, r);
    else a64_vset64(d, (uint32_t)_mm_cvtsi128_si32(r));
}
static inline __attribute__((always_inline)) int a64_vq_mul(const Ctx *c, uint64_t *d, __m128i a, __m128i b, int k) {
    if (!RECOMP_FPX_OPEN(c)) return 0;
    const __m128i t = _mm_castps_si128(_mm_mul_ps(_mm_castsi128_ps(a), _mm_castsi128_ps(b)));
    /* kept: big, or a finite product of a zero (RECOMP_FPX_KEEP32); under FZ no subnormal operand */
    const __m128i keep = _mm_or_si128(a64_vq_big(t), _mm_andnot_si128(a64_vq_nonfin(t), _mm_or_si128(a64_vq_zero(a), a64_vq_zero(b))));
    __m128i bad = _mm_andnot_si128(keep, _mm_set1_epi32(-1));
    if (RECOMP_FPX_FZ(c)) bad = _mm_or_si128(bad, _mm_or_si128(a64_vq_subn(a), a64_vq_subn(b)));
    if (_mm_movemask_epi8(bad)) return 0;
    a64_vq_store(d, t, k);
    A64_VFPX_Q_PROBE();
    return 1;
}
static inline __attribute__((always_inline)) int a64_vq_fma(const Ctx *c, uint64_t *d, __m128i a, __m128i b, int neg, int k) {
#if defined(__FMA__)
    if (!RECOMP_FPX_OPEN(c)) return 0;
    const __m128i z = a64_vq_load(d, k);
    if (neg) a = _mm_xor_si128(a, _mm_set1_epi32((int)0x80000000u));
    const __m128i t = _mm_castps_si128(_mm_fmadd_ps(_mm_castsi128_ps(a), _mm_castsi128_ps(b), _mm_castsi128_ps(z)));
    /* kept: big, or a finite result of a zero factor (RECOMP_FPX_KEEP32); under FZ no subnormal operand */
    const __m128i keep = _mm_or_si128(a64_vq_big(t), _mm_andnot_si128(a64_vq_nonfin(t), _mm_or_si128(a64_vq_zero(a), a64_vq_zero(b))));
    __m128i bad = _mm_andnot_si128(keep, _mm_set1_epi32(-1));
    if (RECOMP_FPX_FZ(c)) bad = _mm_or_si128(bad, _mm_or_si128(_mm_or_si128(a64_vq_subn(a), a64_vq_subn(b)), a64_vq_subn(z)));
    if (_mm_movemask_epi8(bad)) return 0;
    a64_vq_store(d, t, k);
    A64_VFPX_Q_PROBE();
    return 1;
#else
    (void)c; (void)d; (void)a; (void)b; (void)neg; (void)k; return 0;   /* (no FMA3: a fused op is not one instruction here) */
#endif
}
static inline __attribute__((always_inline)) int a64_vfpx_q_mul(const Ctx *c, uint64_t *d, const uint64_t *n, const uint64_t *m, int k) {
    return a64_vq_mul(c, d, a64_vq_load(n, k), a64_vq_load(m, k), k);
}
static inline __attribute__((always_inline)) int a64_vfpx_q_mule(const Ctx *c, uint64_t *d, const uint64_t *n, const uint64_t *m, int index, int k) {
    return a64_vq_mul(c, d, a64_vq_load(n, k), a64_vq_lane(m, index), k);
}
static inline __attribute__((always_inline)) int a64_vfpx_q_fma(const Ctx *c, uint64_t *d, const uint64_t *n, const uint64_t *m, int neg, int k) {
    return a64_vq_fma(c, d, a64_vq_load(n, k), a64_vq_load(m, k), neg, k);
}
static inline __attribute__((always_inline)) int a64_vfpx_q_fmae(const Ctx *c, uint64_t *d, const uint64_t *n, const uint64_t *m, int index, int neg, int k) {
    return a64_vq_fma(c, d, a64_vq_load(n, k), a64_vq_lane(m, index), neg, k);
}
static inline __attribute__((always_inline)) int a64_vfpx_q_div(const Ctx *c, uint64_t *d, const uint64_t *n, const uint64_t *m, int k) {
    if (!RECOMP_FPX_OPEN(c)) return 0;
    const __m128i a = a64_vq_load(n, k), b = a64_vq_load(m, k);
    const __m128i t = _mm_castps_si128(_mm_div_ps(_mm_castsi128_ps(a), _mm_castsi128_ps(b)));
    /* kept: big, or a finite quotient of a zero (RECOMP_FPX_KEEPDIV32); under FZ no subnormal operand */
    const __m128i keep = _mm_or_si128(a64_vq_big(t), _mm_andnot_si128(a64_vq_nonfin(t), a64_vq_zero(a)));
    __m128i bad = _mm_andnot_si128(keep, _mm_set1_epi32(-1));
    if (RECOMP_FPX_FZ(c)) bad = _mm_or_si128(bad, _mm_or_si128(a64_vq_subn(a), a64_vq_subn(b)));
    if (_mm_movemask_epi8(bad)) return 0;
    a64_vq_store(d, t, k);
    A64_VFPX_Q_PROBE();
    return 1;
}
/* FMAX / FMIN / FMAXNM / FMINNM (the NM forms differ only for a NaN, which is never kept). x86's MAXPS and MINPS give
   their second operand for two zeros; taking the op both ways round and combining (and for max, or for min) gives Arm's
   zero, and changes nothing where the operands are not both zeros (equal numbers have equal bits). No FPSR bit. */
static inline __attribute__((always_inline)) int a64_vfpx_q_minmax(const Ctx *c, uint64_t *d, const uint64_t *n, const uint64_t *m, int min, int k) {
    if (c->fpcr & RECOMP_FPX_FPCR_MASK) return 0;
    const __m128i a = a64_vq_load(n, k), b = a64_vq_load(m, k);
    __m128i bad = _mm_or_si128(a64_vq_nan(a), a64_vq_nan(b));
    if (RECOMP_FPX_FZ(c)) bad = _mm_or_si128(bad, _mm_or_si128(a64_vq_subn(a), a64_vq_subn(b)));
    if (_mm_movemask_epi8(bad)) return 0;
    const __m128 x = _mm_castsi128_ps(a), y = _mm_castsi128_ps(b);
    const __m128 r = min ? _mm_or_ps(_mm_min_ps(x, y), _mm_min_ps(y, x)) : _mm_and_ps(_mm_max_ps(x, y), _mm_max_ps(y, x));
    a64_vq_store(d, _mm_castps_si128(r), k);
    A64_VFPX_Q_PROBE();
    return 1;
}
/* FCVT Dd, Sn: every binary32 number is a binary64 number. A NaN (quieted, IOC) and, under FZ, a subnormal (flushed, IDC)
   are left to the C behind it */
static inline __attribute__((always_inline)) int a64_vq_s_to_d(const Ctx *c, uint32_t x, uint64_t *r) {
    if ((x & 0x7fffffffu) > 0x7f800000u || (RECOMP_FPX_FZ(c) && RECOMP_FPX_SUBN32(x))) return 0;
    *r = recomp_fpx_db((double)recomp_fpx_f(x));
    return 1;
}
/* FCVT Sd, Dn: one rounding to nearest. Kept when the result is a normal number above the smallest (no overflow, not
   tiny; an inexact result raises IXC, already raised under the open gate), or the input is a zero */
static inline __attribute__((always_inline)) int a64_vq_d_to_s(uint64_t x, uint32_t *r) {
    const uint32_t t = (uint32_t)recomp_fpx_fb((float)recomp_fpx_d(x));
    if (!(RECOMP_FPX_BIG32(t) || RECOMP_FPX_ZERO64(x))) return 0;
    *r = t;
    return 1;
}
static inline __attribute__((always_inline)) int a64_vfpx_q_cvtsd(const Ctx *c, uint64_t *d, const uint64_t *n) {
    uint64_t r;
    if ((c->fpcr & RECOMP_FPX_FPCR_MASK) || !a64_vq_s_to_d(c, (uint32_t)n[0], &r)) return 0;
    a64_vset64(d, r);
    A64_VFPX_Q_PROBE();
    return 1;
}
static inline __attribute__((always_inline)) int a64_vfpx_q_cvtds(const Ctx *c, uint64_t *d, const uint64_t *n) {
    uint32_t r;
    if (!RECOMP_FPX_OPEN(c) || !a64_vq_d_to_s(n[0], &r)) return 0;
    a64_vset64(d, r);
    A64_VFPX_Q_PROBE();
    return 1;
}
static inline __attribute__((always_inline)) int a64_vfpx_q_cvtl(const Ctx *c, uint64_t *d, const uint64_t *n, int hi) {
    const uint64_t x = n[hi ? 1 : 0];
    uint64_t r0, r1;
    if ((c->fpcr & RECOMP_FPX_FPCR_MASK) || !a64_vq_s_to_d(c, (uint32_t)x, &r0) || !a64_vq_s_to_d(c, (uint32_t)(x >> 32), &r1)) return 0;
    a64_vset128(d, r0, r1);
    A64_VFPX_Q_PROBE();
    return 1;
}
static inline __attribute__((always_inline)) int a64_vfpx_q_cvtn(const Ctx *c, uint64_t *d, const uint64_t *n) {
    const uint64_t x0 = n[0], x1 = n[1];
    uint32_t r0, r1;
    if (!RECOMP_FPX_OPEN(c) || !a64_vq_d_to_s(x0, &r0) || !a64_vq_d_to_s(x1, &r1)) return 0;
    a64_vset64(d, (uint64_t)r1 << 32 | r0);
    A64_VFPX_Q_PROBE();
    return 1;
}
#else   /* (no SSE2 host path: the C behind each test always runs) */
#define a64_vfpx_q_mul(c, d, n, m, k) 0
#define a64_vfpx_q_mule(c, d, n, m, index, k) 0
#define a64_vfpx_q_fma(c, d, n, m, neg, k) 0
#define a64_vfpx_q_fmae(c, d, n, m, index, neg, k) 0
#define a64_vfpx_q_div(c, d, n, m, k) 0
#define a64_vfpx_q_minmax(c, d, n, m, min, k) 0
#define a64_vfpx_q_cvtsd(c, d, n) 0
#define a64_vfpx_q_cvtds(c, d, n) 0
#define a64_vfpx_q_cvtl(c, d, n, hi) 0
#define a64_vfpx_q_cvtn(c, d, n) 0
#endif
"""


_installed = False


def install():
    """The wrap around a64emit.translate (insn's, installed before) and HEADER at the end of the kit's fpx_header. Once"""
    global _installed
    if _installed:
        return
    _installed = True
    base_translate, base_header = a64emit.translate, a64_lift.fpx_header

    def translate(items, batch=65536):
        texts, flags = base_translate(items, batch)
        on = groups()
        if not on:
            return texts, flags
        texts = list(texts)
        for k, (pc, w) in enumerate(items):
            call = fast_call(w, on)
            if call and not flags[k] and not main_handles(texts[k]):
                texts[k] = wrap(texts[k], call)
        return texts, flags

    def fpx_header(used):
        return base_header(used) + HEADER   # (after the kit's VSET_HEADER, whose a64_vst_lo64, a64_vset64 and a64_vset128 it uses)

    a64emit.translate, a64_lift.fpx_header = translate, fpx_header
