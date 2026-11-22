"""(Triforce, 11-21, the performance audit's LIFT-02, after Source A's) Vector moves the kit's translator writes slowly,
rewritten on the lifted text: two passes over one instruction's C, each with its helpers appended to a64_fpx.h. The
kit's files stay as they are (third_party/ is not edited: CONTRIBUTING.md); install(), called from nx2/lift.py beside
insn's and lift_fixes', wraps the kit's functions:

  - a64_lift.vectorize_fpx: vectorize_bytes before it, on the emitter's own text (TBL with a one-register table, EXT),
    so that widen_vstores, which comes after, no longer meets the loops' tails;
  - a64_lift.op_text: vectorize_moves on its result (128-bit vector loads, DUP by element);
  - a64_lift.fpx_header: VBYTE_HEADER and VMOVE_HEADER after the kit's VSET_HEADER, whose A64_OPAQUE and a64_vset64
    they use.

Each rewrite leaves the same bytes in the same registers; tests/test_vbytes.py runs every shape both ways. Source A
counted, in its market's game code, TBL 2,995 sites, EXT 29,451, 128-bit loads 139,843 and DUP 26,529, and its game
work a frame went from 15.46 to about 14.3 ms with these and one more rewrite that Triforce had already
(a64_lift.py's vectorize_elem).

Switches, read at lift time (the lift key holds the A64_ variables): A64_NO_VBYTES=1 and A64_NO_VMOVES=1 keep the kit's
text for that pass. The lift's emit processes run nx2/lift.py's module level again (nx2/emit_pool.py), so they have
the wrappers too."""
import os
import re

import a64_lift

# TBL with a one-register table, and EXT. The emitter writes each as a loop of 8 or 16 single bytes through arrays on
# the stack, then a 16-byte reload of the result that cannot be forwarded from the byte stores. On x86 each is one SSSE3
# instruction. TBL: an index of 16 or more gives 0, which PSHUFB does when the index byte's top bit is set; the index
# plus 0x70, saturated, keeps 0 to 15 below 0x80 with the same low four bits and takes 16 to 255 to 0x80 or more.
# EXT of 16 bytes is PALIGNR, of 8 bytes two shifts of the low halves. Both sources are read before Vd is written, so
# Vd may be Vn or Vm.
VBYTE_TBL = re.compile(
    r"\{ uint8_t _t\[16\],_x\[(8|16)\],_r\[\1\]; memcpy\(_t\+0,c->vreg\[(\d+)\],16\); memcpy\(_x,c->vreg\[(\d+)\],\1\); "
    r"for\(int _i=0;_i<\1;_i\+\+\)\{ unsigned _k=_x\[_i\]; if\(_k<16U\) _r\[_i\]=_t\[_k\]; else _r\[_i\]=0; \} "
    r"c->vreg\[(\d+)\]\[0\]=0; c->vreg\[\4\]\[1\]=0; memcpy\(c->vreg\[\4\],_r,\1\); \}")
VBYTE_EXT = re.compile(
    r"\{ uint8_t _a\[(8|16)\],_b\[\1\],_r\[\1\]; memcpy\(_a,c->vreg\[(\d+)\],\1\); memcpy\(_b,c->vreg\[(\d+)\],\1\); "
    r"for\(int _i=0;_i<\1;_i\+\+\)\{ int _k=_i\+(\d+); _r\[_i\] = \(_k<\1\) \? _a\[_k\] : _b\[_k-\1\]; \} "
    r"c->vreg\[(\d+)\]\[0\]=0; c->vreg\[\5\]\[1\]=0; memcpy\(c->vreg\[\5\],_r,\1\); \}")


def vectorize_bytes(text):
    if "uint8_t _" not in text or os.environ.get("A64_NO_VBYTES"):
        return text
    text = VBYTE_TBL.sub(lambda m: "a64_tbl1(c->vreg[%s],c->vreg[%s],c->vreg[%s],%d);"
                         % (m.group(4), m.group(2), m.group(3), m.group(1) == "16"), text)
    return VBYTE_EXT.sub(lambda m: "A64_EXT%s(c->vreg[%s],c->vreg[%s],c->vreg[%s],%s);"
                         % (m.group(1), m.group(5), m.group(2), m.group(3), m.group(4)), text)


VBYTE_HEADER = r"""
/* ---- (Triforce, LIFT-02) TBL with one table register, and EXT, as one SSSE3 instruction each (nx2/fastvec.py
   vectorize_bytes). Without SSSE3 (a baseline x86-64 build): plain C, the same bytes ---- */
#if defined(__SSSE3__)
#include <tmmintrin.h>
static inline __attribute__((always_inline)) void a64_tbl1(uint64_t *d, const uint64_t *t, const uint64_t *x, int q) {
    const __m128i tv = _mm_loadu_si128((const __m128i *)t);
    const __m128i xv = q ? _mm_loadu_si128((const __m128i *)x) : _mm_loadl_epi64((const __m128i *)x);
    __m128i r = _mm_shuffle_epi8(tv, _mm_adds_epu8(xv, _mm_set1_epi8(0x70)));
    if (!q) r = _mm_move_epi64(r);
    A64_OPAQUE(r);
    _mm_storeu_si128((__m128i *)d, r);
}
/* (EXT of 16 bytes: Vn's bytes from imm up, then Vm's; PALIGNR takes the high source first) */
#define A64_EXT16(d, n, m, imm) do { \
    const __m128i a64_e_n_ = _mm_loadu_si128((const __m128i *)(n)), a64_e_m_ = _mm_loadu_si128((const __m128i *)(m)); \
    __m128i a64_e_r_ = _mm_alignr_epi8(a64_e_m_, a64_e_n_, imm); \
    A64_OPAQUE(a64_e_r_); \
    _mm_storeu_si128((__m128i *)(d), a64_e_r_); } while (0)
#else
static inline void a64_tbl1(uint64_t *d, const uint64_t *t, const uint64_t *x, int q) {
    uint8_t tb[16], xb[16], r[16] = {0};
    memcpy(tb, t, 16); memcpy(xb, x, 16);
    for (int i = 0; i < (q ? 16 : 8); i++) r[i] = xb[i] < 16 ? tb[xb[i]] : 0;
    memcpy(d, r, 16);
}
#define A64_EXT16(d, n, m, imm) do { uint8_t a64_e_a_[32], a64_e_r_[16]; memcpy(a64_e_a_, (n), 16); \
    memcpy(a64_e_a_ + 16, (m), 16); memcpy(a64_e_r_, a64_e_a_ + (imm), 16); memcpy((d), a64_e_r_, 16); } while (0)
#endif
/* (EXT of 8 bytes: the low halves, Vn's from byte imm up, then Vm's; the top half zero) */
#define A64_EXT8(d, n, m, imm) do { uint64_t a64_e_n_ = (n)[0], a64_e_m_ = (m)[0]; \
    const uint64_t a64_e_r_ = (imm) ? (a64_e_n_ >> (8 * (imm))) | (a64_e_m_ << ((64 - 8 * (imm)) & 63)) : a64_e_n_; \
    a64_vset64((d), a64_e_r_); } while (0)
"""


# Two moves the compiler leaves slow, on the final text (after widen_vstores):
# - a 128-bit vector load (LDR Q, LDP Q, LD1 of one register) is recomp_ldp64 into the register's two halves: two
#   8-byte stores, from which the next 16-byte read of the register cannot be forwarded. Now one 16-byte load and one
#   16-byte store (a64_vld16); guest memory is read the same way, recomp_load64 being a plain copy.
# - DUP Vd, Vn.T[i] is a loop through the stack and a 16-byte reload: one broadcast (a64_vdup). The element is read
#   before Vd is written, so Vd may be Vn.
VMOVE_LDQ = re.compile(r"recomp_ldp64\(c,([^;]*?),&c->vreg\[(\d+)\]\[0\],&c->vreg\[\2\]\[1\]\);")
VMOVE_DUP = re.compile(
    r"\{ uint8_t _s\[16\]; memcpy\(_s,c->vreg\[(\d+)\],16\); uint64_t _e=0; memcpy\(&_e,_s\+(\d+),(1|2|4|8)\); "
    r"uint8_t _d\[16\]; memset\(_d,0,16\); for\(int _i=0;_i<(\d+);_i\+\+\) memcpy\(_d\+_i\*\3,&_e,\3\); "
    r"a64_vst16\(c->vreg\[(\d+)\],_d\); \}")


def vectorize_moves(text):
    if "c->vreg" not in text or os.environ.get("A64_NO_VMOVES"):
        return text
    text = VMOVE_LDQ.sub(lambda m: "a64_vld16(c->vreg[%s],%s);" % (m.group(2), m.group(1)), text)

    def dup(m):
        s, off, w, n, d = m.groups()
        if int(w) * int(n) not in (8, 16):   # (a shape that fills neither half nor the whole register: left alone)
            return m.group(0)
        return "a64_vdup(c->vreg[%s],c->vreg[%s],%s,%s,%d);" % (d, s, off, w, int(w) * int(n) == 16)
    return VMOVE_DUP.sub(dup, text)


VMOVE_HEADER = r"""
/* ---- (Triforce, LIFT-02) a whole vector register loaded at once, and DUP by element as one broadcast (nx2/fastvec.py
   vectorize_moves). Without the SSE2 host path: plain C, the same bytes ---- */
#if RECOMP_FPX_HOST == 2
static inline __attribute__((always_inline)) void a64_vld16(uint64_t *d, uint64_t a) {
    __m128i x = _mm_loadu_si128((const __m128i *)A64_PTR(a));
    A64_OPAQUE(x);
    _mm_storeu_si128((__m128i *)d, x);
}
static inline __attribute__((always_inline)) void a64_vdup(uint64_t *d, const uint64_t *s, int off, int w, int q) {
    uint64_t e = 0;
    memcpy(&e, (const uint8_t *)s + off, w);
    __m128i r = w == 1 ? _mm_set1_epi8((char)e) : w == 2 ? _mm_set1_epi16((short)e) : w == 4 ? _mm_set1_epi32((int)e)
                                                                                           : _mm_set1_epi64x((long long)e);
    if (!q) r = _mm_move_epi64(r);
    A64_OPAQUE(r);
    _mm_storeu_si128((__m128i *)d, r);
}
#else
static inline void a64_vld16(uint64_t *d, uint64_t a) { memcpy(d, A64_PTR(a), 16); }
static inline void a64_vdup(uint64_t *d, const uint64_t *s, int off, int w, int q) {
    uint8_t r[16] = {0};
    uint64_t e = 0;
    memcpy(&e, (const uint8_t *)s + off, w);
    for (int i = 0; i < (q ? 16 : 8) / w; i++) memcpy(r + i * w, &e, w);
    memcpy(d, r, 16);
}
#endif
"""


_installed = False


def install():
    """The two passes around the kit's vectorize_fpx and op_text, and their helpers into its fpx_header. Once"""
    global _installed
    if _installed:
        return
    _installed = True
    base_vfpx, base_op_text, base_header = a64_lift.vectorize_fpx, a64_lift.op_text, a64_lift.fpx_header

    def vectorize_fpx(text):
        return base_vfpx(vectorize_bytes(text))

    def op_text(text, fpx):
        return vectorize_moves(base_op_text(text, fpx))

    def fpx_header(used):
        text = base_header(used)
        at = a64_lift.VSET_HEADER + "\n"
        if text.count(at) != 1:   # (the kit changed: the helpers have nowhere known to go, and the lift must not go on)
            raise SystemExit("fastvec: a64_fpx.h no longer holds the kit's VSET_HEADER once: where its helpers go")
        return text.replace(at, at + VBYTE_HEADER + "\n" + VMOVE_HEADER + "\n")

    a64_lift.vectorize_fpx, a64_lift.op_text, a64_lift.fpx_header = vectorize_fpx, op_text, fpx_header
