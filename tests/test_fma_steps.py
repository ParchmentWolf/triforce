"""The single-precision FRECPS and FRSQRTS steps as one fused instruction on x86-64-v3, bit-exact with the binary64 form
and with the exact bodies (game-free).

(Triforce, 11-22, the performance audit's LIFT-05, after Source A's.) The kit's fast path for the Newton-Raphson steps
(recomp_fpx_recps32: 2 - a*b; recomp_fpx_rsqrts32: (3 - a*b) / 2) computes them in binary64 on x86-64 and declines a
binary32 midpoint, because the baseline has no FMA. nx2/fma_steps.py gives both the guard the kit's fused multiply-add
already has: where the build has FMA3, one fused instruction, the step rounded once.

The text: the kit's runtime header from a64_rtgen.runtime_h() under fma_steps.install() must be the kit's own with those
two #if lines changed and nothing else, all three functions (fma32, recps32, rsqrts32) under the same guard; with
A64_NO_FMA_STEPS=1 it must be the kit's text byte for byte.

The run: guest words (FRECPS and FRSQRTS: scalar S, 2S and 4S, with Vd apart, Vd = Vn, Vd = Vm, one register for all
and registers above 15; and the D forms, which do not change) go through a64emit.translate and a64_lift.op_text once,
and that one text is compiled twice, against the header as written now and against the kit's (A64_NO_FMA_STEPS=1),
tests/fma_steps_side.c. tests/fma_steps_test.c runs each word as lifted and as a hot function has it on both sides,
and the exact body inline (the word translated with the fast path off), from the same random Ctx: operands biased to
zeros, infinities, NaNs of both kinds with payloads, subnormals, the extreme normals, steps that cancel and steps that are
exactly a binary32 midpoint; random FPCR (FZ, DN, the rounding modes, the other control bits) and FPSR (the gate open and
closed), every flag combination. The whole Ctx, FPSR in it, must be the same in all five. Then the two fast paths by
themselves: what both sides keep must be the same bits, what either keeps must be the exact body's value with FPSR
untouched, and the kit's side must keep nothing the new one declines, with one exception that the driver checks by its
size: an FRSQRTS step of 2^127 or more, whose fused 3 - a*b is past binary32's range before the halving, so the new side
declines it and the exact body answers (the same value).

Built at -march=x86-64-v3 and -march=native (with FMA3 the new side must keep midpoints the kit's declines, the audit's
two named pairs among them), at -march=x86-64-v2 and -march=x86-64 (no FMA3: both sides must decide alike on every pair),
and at -march=x86-64-v3 with -DA64_FPX_NO_FMA32 (the binary64 form again: alike too).

And reads the source: nx2/lift.py installs it, A64_NO_FMA_STEPS is an A64_ name (in nx2/make_game.py's lift key, as
nx2/fma_steps.py is), and the switch is in the switches table.

    python -I -B tests/test_fma_steps.py [--cc clang] [--cxx clang++] [--random 20000] [--direct 4000000]

Skipped (exit 0) on a host that is not x86-64 or has no C or C++ compiler.
"""
import argparse
import os
import platform
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import test_fpx_sticky as fs  # noqa: E402  (the build helpers the kit's other lifted-code tests use)

RUN_ALL_ARGS = ["--cc", "clang", "--cxx", "{cxx}"]
SEED = 20261122
# (-march, more flags, whether the steps are the fused instruction there; None: as this CPU has it)
BUILDS = (("x86-64-v3", [], True), ("x86-64-v2", [], False), ("x86-64", [], False), ("native", [], None),
          ("x86-64-v3", ["-DA64_FPX_NO_FMA32"], False))
REGS = ((0, 5, 1), (5, 5, 1), (1, 5, 1), (2, 2, 2), (3, 30, 17))   # (rd, rn, rm)


def cases():
    """(name, guest word, rn, rm, double)"""
    out = []
    for name, base, dbl in (("FRECPS s", 0x5E20FC00, 0), ("FRSQRTS s", 0x5EA0FC00, 0), ("FRECPS .2s", 0x0E20FC00, 0),
                            ("FRSQRTS .2s", 0x0EA0FC00, 0), ("FRECPS .4s", 0x4E20FC00, 0), ("FRSQRTS .4s", 0x4EA0FC00, 0),
                            ("FRECPS d", 0x5E60FC00, 1), ("FRSQRTS d", 0x5EE0FC00, 1), ("FRECPS .2d", 0x4E60FC00, 1),
                            ("FRSQRTS .2d", 0x4EE0FC00, 1)):
        for rd, rn, rm in (REGS[:2] if dbl else REGS):
            out.append(("%s v%d, v%d, v%d" % (name, rd, rn, rm), base | (rm << 16) | (rn << 5) | rd, rn, rm, dbl))
    return out


def lifted(a64emit, a64_lift, used):
    """fma_steps_lifted.h: each guest word as lifted, as a hot function has it and with the exact body inline"""
    all_cases = cases()
    words = [(0x1000 + 4 * i, c[1]) for i, c in enumerate(all_cases)]
    texts, flags = a64emit.translate(words)
    if any(flags):
        raise SystemExit("fma steps: a64emit did not translate the guest words: %s" % flags)
    texts = [a64_lift.op_text(t, used) for t in texts]
    a64emit.lib().a64_config(1, 0)   # (the fast path off: the exact body inline, the reference)
    try:
        exact, _ = a64emit.translate(words)
    finally:
        a64emit.lib().a64_config(1, 1)
    out = ["/* Generated by tests/test_fma_steps.py from guest words, as a64_lift.py lifts them. */"]
    for i, (t, ex, c) in enumerate(zip(texts, exact, all_cases)):
        helper = "a64_fpx_%s%d_" % ("rsqrts" if "FRSQRTS" in c[0] else "recps", 64 if c[4] else 32)
        if helper not in t or "recomp_fpx_" in ex:
            raise SystemExit("fma steps: %s is not lifted through %s, or its exact form has a fast path" % (c[0], helper))
        out.append("static void g_lifted%d(Ctx *__restrict c) { %s }" % (i, t))
        out.append("static void g_hot%d(Ctx *__restrict c) { %s }" % (i, a64_lift.hot_text(t)))
        out.append("static void g_exact%d(Ctx *__restrict c) { %s }" % (i, ex))
    out.append("static const struct { const char *name; int rn, rm, dbl; void (*lifted)(Ctx *), (*hot)(Ctx *), (*exact)(Ctx *); }"
               " CASES[] = {%s};" % ", ".join('{"%s", %d, %d, %d, g_lifted%d, g_hot%d, g_exact%d}' % (c[0], c[2], c[3], c[4], i, i, i)
                                               for i, c in enumerate(all_cases)))
    return "\n".join(out) + "\n", len(all_cases)


def generate(cxx, tmp, flags):
    """tmp/now and tmp/old: the kit's runtime header and C as written now and with A64_NO_FMA_STEPS=1; tmp: a64_fpx.h and
    fma_steps_lifted.h. Returns (the shapes, the runtime C file)"""
    dll = os.path.join(tmp, "a64emit.dll" if os.name == "nt" else "liba64emit.so")
    fs.build([cxx, "-std=c++20", "-O0", "-shared", "-Wno-everything", "-o", dll, os.path.join(fs.KIT, "lift", "a64emit.cpp")]
             + flags + ([] if os.name == "nt" else ["-fPIC"]), "a64emit")
    import kit  # noqa: F401  (a64-kit on the path)
    import build_emit
    build_emit.build = lambda force=False: dll   # (not a64emit.dll beside the source)
    import a64_lift
    import a64_rtgen
    import a64emit
    import fma_steps
    now_dir, old_dir = os.path.join(tmp, "now"), os.path.join(tmp, "old")
    used = set()
    try:
        kit_h = a64_rtgen.runtime_h()
        fma_steps.install()   # (the wrapper under test, around the kit's runtime_h)
        now_h = a64_rtgen.runtime_h()
        a64_rtgen.write(now_dir)
        os.environ["A64_NO_FMA_STEPS"] = "1"
        try:
            old_h = a64_rtgen.runtime_h()
            a64_rtgen.write(old_dir)
        finally:
            del os.environ["A64_NO_FMA_STEPS"]
        text, n = lifted(a64emit, a64_lift, used)
    finally:
        if a64emit._lib is not None:   # (unloaded, so the folder can go)
            import _ctypes
            (_ctypes.FreeLibrary if os.name == "nt" else _ctypes.dlclose)(a64emit._lib._handle)
            a64emit._lib = None
    if old_h != kit_h:
        raise SystemExit("fma steps: with A64_NO_FMA_STEPS=1 the runtime header is not the kit's text")
    want = kit_h
    for old, new in ((fma_steps.RECPS32_OLD, fma_steps.RECPS32_NEW), (fma_steps.RSQRTS32_OLD, fma_steps.RSQRTS32_NEW)):
        if want.count(old) != 1:
            raise SystemExit("fma steps: the kit's header no longer has %r once" % old.split("\n")[0])
        want = want.replace(old, new)
    if now_h != want or now_h == kit_h:
        raise SystemExit("fma steps: the runtime header is not the kit's with the two steps' guards changed and nothing else")
    for name in ("fma32", "recps32", "rsqrts32"):   # (all three under one guard, so -DA64_FPX_NO_FMA32 returns all three)
        if not re.search(r"static RECOMP_INLINE int recomp_fpx_%s\([^\n]*\{\n%s" % (name, re.escape(fma_steps.GUARD_NEW)), now_h):
            raise SystemExit("fma steps: recomp_fpx_%s is not under the FMA3 guard" % name)
    if now_h.count(fma_steps.GUARD_NEW) != 3 or kit_h.count(fma_steps.GUARD_NEW) != 1:
        raise SystemExit("fma steps: the FMA3 guard is not on three functions now and one in the kit's text")
    files = {}
    for side, text_h in ((now_dir, now_h), (old_dir, old_h)):
        names = sorted(os.listdir(side))
        heads, srcs = [f for f in names if f.endswith(".h")], [f for f in names if f.endswith(".c")]
        if len(heads) != 1 or len(srcs) != 1:
            raise SystemExit("fma steps: a64_rtgen wrote %s" % names)
        with open(os.path.join(side, heads[0]), encoding="utf-8") as f:
            if f.read() != text_h:
                raise SystemExit("fma steps: a64_rtgen.write did not write the header under test into %s" % side)
        with open(os.path.join(side, srcs[0]), encoding="utf-8") as f:
            files[side] = (srcs[0], f.read())
    if files[now_dir] != files[old_dir]:
        raise SystemExit("fma steps: the runtime C differs between the two sides (only the header should)")
    with open(os.path.join(tmp, "fma_steps_lifted.h"), "w", newline="\n") as f:
        f.write(text)
    with open(os.path.join(tmp, "a64_fpx.h"), "w", newline="\n") as f:
        f.write(a64_lift.fpx_header(used))
    return n, os.path.join(now_dir, files[now_dir][0])


def check_sources():
    with open(os.path.join(ROOT, "nx2", "lift.py"), encoding="utf-8") as f:
        lift = f.read()
    at = [lift.find(p) for p in ("import fma_steps", "import a64_rtgen", "fma_steps.install()", "def main():")]
    if min(at) < 0 or not at[1] < at[2] < at[3]:
        raise SystemExit("fma steps: nx2/lift.py does not install nx2/fma_steps.py at module level")
    with open(os.path.join(ROOT, "nx2", "make_game.py"), encoding="utf-8") as f:
        make_game = f.read()
    if 'if k.startswith(("A64_", "OOT_", "RX_"))' not in make_game:
        raise SystemExit("fma steps: nx2/make_game.py's lift_key no longer takes the A64_ variables: A64_NO_FMA_STEPS is not in the key")
    not_keyed = re.search(r"^LIFT_KEY_NOT = \((.*?)\)   #", make_game, re.S | re.M)
    if not not_keyed or '"fma_steps.py"' in not_keyed.group(1):
        raise SystemExit("fma steps: nx2/fma_steps.py must stay a file of the lift key")
    with open(os.path.join(ROOT, "docs", "development.md"), encoding="utf-8") as f:
        if "| `A64_NO_FMA_STEPS=1` |" not in f.read():
            raise SystemExit("fma steps: docs/development.md: A64_NO_FMA_STEPS is not in the switches table")


def fields(line):
    return {k: int(v) for k, v in (kv.split("=") for kv in line.split()[1:])}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cc")
    p.add_argument("--cxx")
    p.add_argument("--random", type=int, default=20000)
    p.add_argument("--direct", type=int, default=4000000)
    a = p.parse_args()
    check_sources()
    if platform.machine().lower() not in ("x86_64", "amd64"):
        fs.skip("not an x86-64 host: %s" % platform.machine())
    cc = fs.compiler(a.cc, "CC", ("clang", "gcc", "cc"), "clang")
    cxx = fs.compiler(a.cxx, "CXX", ("clang++", "g++", "c++"), "clang++")
    if not cc or not cxx:
        fs.skip("no C compiler" if not cc else "no C++ compiler")
    t0 = time.time()
    failed, states, pairs, shapes = [], 0, 0, 0
    with tempfile.TemporaryDirectory(prefix="triforce-fma-steps-") as tmp:
        shapes, rt_c = generate(cxx, tmp, fs.target_flags(cxx, tmp))
        for at, (march, more, fused) in enumerate(BUILDS):
            what = "%s%s" % (march, " " + " ".join(more) if more else "")
            common = [cc] + fs.target_flags(cc, tmp) + ["-march=" + march] + fs.FLAGS + more + \
                ["-D_CRT_SECURE_NO_WARNINGS", "-Wno-everything", "-I" + os.path.join(fs.KIT, "rt"), "-I" + tmp]
            objs = []
            for side in ("now", "old"):   # (the same lifted text against each side's runtime header)
                obj = os.path.join(tmp, "side_%s_%d.o" % (side, at))
                fs.build(common + ["-DSIDE=" + side, "-I" + os.path.join(tmp, side), "-c",
                                   os.path.join(ROOT, "tests", "fma_steps_side.c"), "-o", obj], "the %s side at %s" % (side, what))
                objs.append(obj)
            exe = os.path.join(tmp, "fma_steps_test_%d.exe" % at)
            fs.build(common + ["-I" + os.path.join(tmp, "now"), os.path.join(ROOT, "tests", "fma_steps_test.c"), rt_c] + objs +
                     ["-o", exe], "the driver at " + what)
            for mode, n in (("lifted", a.random), ("direct", a.direct)):
                r = fs.run([exe, mode, str(n), str(SEED)], timeout=3600)
                print("%-28s %s" % (what, r.stdout.rstrip()))
                if r.returncode == 3:
                    print("fma steps: %s skipped (this CPU cannot run it)" % what)
                    break
                line = [l for l in r.stdout.splitlines() if l.startswith(mode + " ")]
                if r.returncode or len(line) != 1:
                    failed.append("%s %s (exit %d)" % (what, mode, r.returncode))
                    continue
                c = fields(line[0])
                if fused is not None and bool(c["fused"]) != fused:
                    failed.append("%s: the steps are %sfused there" % (what, "" if c["fused"] else "not "))
                if mode == "lifted":
                    states += c["checks"]
                    continue
                pairs += c["checks"]
                if not c["named"] or not c["kept_old"]:
                    failed.append("%s direct: %s" % (what, c))
                elif c["fused"] and not c["now_only"]:
                    failed.append("%s direct: the fused form kept no pair the binary64 form declines" % what)
                elif not c["fused"] and (c["now_only"] or c["kept_now"] != c["kept_old"]):
                    failed.append("%s direct: the sides decide differently without FMA3: %s" % (what, c))
    if failed:
        raise SystemExit("FAIL: fma steps: %s" % "; ".join(failed))
    print("PASS: %d guest words, %d random states (each five ways) and %d operand pairs: the fused steps leave what the "
          "kit's and the exact bodies leave (%.0f s)" % (shapes, states, pairs, time.time() - t0))


if __name__ == "__main__":
    main()
