"""(Triforce, 11-22, the performance audit's LIFT-05, after Source A's) The single-precision FRECPS and FRSQRTS steps as
one fused instruction where the build has FMA3.

The kit's fast path for the Newton-Raphson steps, recomp_fpx_recps32 (2 - a*b) and recomp_fpx_rsqrts32 ((3 - a*b) / 2),
has two forms: on an Arm host one fused multiply-add, the step rounded once as the guest rounds it; on x86-64 the step in
binary64 (two widenings, a multiply, a subtraction, a narrowing) and a test for a binary32 midpoint, which sends the call
to the exact body, because x86-64's baseline has no FMA. The game is built for x86-64-v3 where the CPU has it, and there
one FMA instruction is that same correctly rounded step. The kit already took this step for the fused multiply-add itself
(a64_rtgen.fma32_native, recomp_fpx_fma32); this gives the two steps the same guard. The tests that decide whether the
native result is kept (a normal result; under FZ no subnormal operand) are unchanged, and halving a normal result is
exact.

The kit's files stay as they are (third_party/ is not edited): install(), called from nx2/lift.py, wraps the kit's
a64_rtgen.runtime_h. Each function's head must be in its text exactly once, so a refreshed kit that changed one stops the
lift with a message, not the game.

Switches: A64_NO_FMA_STEPS=1 at lift time (in the lift key, an A64_ name) leaves the kit's text for the two steps. The
build define -DA64_FPX_NO_FMA32, the kit's own for the fused multiply-add, now returns all three to the binary64 form.
Nothing changes in a build without FMA3 (x86-64-v2). tests/test_fma_steps.py runs the guest instructions both ways."""
import os

import a64_rtgen

GUARD_OLD = "#if RECOMP_FPX_HOST == 1\n"
GUARD_NEW = "#if RECOMP_FPX_HOST == 1 || (RECOMP_FPX_HOST == 2 && defined(__FMA__) && !defined(A64_FPX_NO_FMA32))\n"
# (each function's head line through its #if line, and the line after it, so the form that follows is the one known here)
RECPS32_OLD = ("static RECOMP_INLINE int recomp_fpx_recps32(uint64_t a, uint64_t b, uint32_t fz, uint64_t* v) {\n" + GUARD_OLD +
               "    const uint64_t t = recomp_fpx_fb(__builtin_fmaf(-recomp_fpx_f(a), recomp_fpx_f(b), 2.0f));\n")
RSQRTS32_OLD = ("static RECOMP_INLINE int recomp_fpx_rsqrts32(uint64_t a, uint64_t b, uint32_t fz, uint64_t* v) {\n" + GUARD_OLD +
                "    /* Halving a normal result is exact, and a normal result is all that is kept. */\n"
                "    const uint64_t t = recomp_fpx_fb(__builtin_fmaf(-recomp_fpx_f(a), recomp_fpx_f(b), 3.0f) * 0.5f);\n")
RECPS32_NEW = RECPS32_OLD.replace(GUARD_OLD, GUARD_NEW)
RSQRTS32_NEW = RSQRTS32_OLD.replace(GUARD_OLD, GUARD_NEW)


def patch(h):
    """The kit's runtime header with the two steps' fused form on x86-64 with FMA3; the kit's text with A64_NO_FMA_STEPS=1"""
    if os.environ.get("A64_NO_FMA_STEPS"):
        return h
    for name, old, new in (("recomp_fpx_recps32", RECPS32_OLD, RECPS32_NEW), ("recomp_fpx_rsqrts32", RSQRTS32_OLD, RSQRTS32_NEW)):
        if h.count(old) != 1:   # (the kit changed: the lift must not go on)
            raise SystemExit("fma_steps: the kit's %s changed (its head is %d times in the runtime header): update "
                             "nx2/fma_steps.py" % (name, h.count(old)))
        h = h.replace(old, new)
    return h


_installed = False


def install():
    """patch() around the kit's a64_rtgen.runtime_h, which its write() calls by name. Once"""
    global _installed
    if _installed:
        return
    _installed = True
    base = a64_rtgen.runtime_h

    def runtime_h():
        return patch(base())

    a64_rtgen.runtime_h = runtime_h
