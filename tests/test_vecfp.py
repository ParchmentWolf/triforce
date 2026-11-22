"""The SSE fast paths nx2/vecfp.py puts before float forms lifted lane by lane (A64_VECFP), bit-exact with the kit's
text and with the exact bodies (game-free).

(Triforce, 11-22, the performance audit's LIFT-03, after Source A's.) With A64_VECFP=1 at lift time (off by default)
FMUL .2S, FMLA and FMLS .2S and .4S, FDIV .2S and .4S, FMUL / FMLA / FMLS .2S by element, FMAX / FMIN / FMAXNM / FMINNM
(scalar S, .2S, .4S), FCVT S to D and D to S, FCVTL, FCVTL2 and FCVTN are lifted as
`if (!a64_vfpx_q_<form>(c, ...)) { <the C as before> }`: the helper does the op in SSE and writes the register only when
the scalar fast paths' rules prove the result is Arm's with no new FPSR bit.

The rule (nx2/vecfp.py groups, fast_call): A64_VECFP unset, empty or 0 wraps nothing; 1 wraps every form; a list wraps
its groups (elem, vec, minmax, fcvt) and anything else stops the lift. Forms the kit's own passes vectorize (FMUL .4S,
by element .4S, FADD, FSUB) and the double-precision and pairwise forms are never wrapped.

The lifted text: 137 guest words (every form with Vd apart, Vd = Vn, Vd = Vm, one register for all and registers
above 15; by element with indices 0, 1 and 3) go through a64emit.translate under insn.install() and vecfp.install(),
and a64_lift.op_text, three times: with A64_VECFP=1, without it (the kit's text) and with the fast path off (the exact
body inline). The first must be the helper's test around the second's text and nothing else; no line of it may start
with `}` (nx2/oot_patches.py ends a function at the first such line); the kit's mark grouping must take the helpers as
plain (a64_lift.MG_PLAIN: no run of stores ends at one).

The run: tests/vecfp_test.c runs all three from the same random Ctx (operands biased to zeros of both signs,
subnormals, infinities, NaNs of both kinds with payloads, the extreme normals, equal operands, tiny and huge products,
cancelling addends; FPCR 0, FZ, or other control bits; FPSR with the gate open and closed; every NZCV combination) and
compares the whole Ctx, FPSR in it. Built at -march=x86-64-v3 and -march=native (FMA3: the multiply-adds are one fused
op), -march=x86-64-v2 and -march=x86-64 (no FMA3: they must decline every state). Every other word's helper must do the
op in some states and decline in others, or the comparison would show nothing.

And reads the source: nx2/lift.py installs it after insn's, A64_VECFP is an A64_ name (in nx2/make_game.py's lift key,
as nx2/vecfp.py is), and the switch is in the switches table.

    python -I -B tests/test_vecfp.py [--cc clang] [--cxx clang++] [--random 20000]

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
MARCHES = ("x86-64-v3", "x86-64-v2", "x86-64", "native")
SWITCH = "A64_VECFP"
REGS = ((0, 5, 1), (5, 5, 1), (1, 5, 1), (2, 2, 2), (3, 30, 17))   # (rd, rn, rm)


def three(base, rd, rn, rm):
    return base | (rm << 16) | (rn << 5) | rd


def cases():
    """(name, guest word, rd, rn, rm, group, binary64 source, needs FMA3, helper)"""
    out = []
    for name, base, fused, helper in (("FMUL .2s", 0x2E20DC00, 0, "a64_vfpx_q_mul("), ("FMLA .2s", 0x0E20CC00, 1, "a64_vfpx_q_fma("),
                                      ("FMLA .4s", 0x4E20CC00, 1, "a64_vfpx_q_fma("), ("FMLS .2s", 0x0EA0CC00, 1, "a64_vfpx_q_fma("),
                                      ("FMLS .4s", 0x4EA0CC00, 1, "a64_vfpx_q_fma("), ("FDIV .2s", 0x2E20FC00, 0, "a64_vfpx_q_div("),
                                      ("FDIV .4s", 0x6E20FC00, 0, "a64_vfpx_q_div(")):
        for r in REGS:
            out.append(("%s v%d, v%d, v%d" % ((name,) + r), three(base, *r), r[0], r[1], r[2], "vec", 0, fused, helper))
    for name, base, fused, helper in (("FMUL .2s", 0x0F809000, 0, "a64_vfpx_q_mule("), ("FMLA .2s", 0x0F801000, 1, "a64_vfpx_q_fmae("),
                                      ("FMLS .2s", 0x0F805000, 1, "a64_vfpx_q_fmae(")):
        for index in (0, 1, 3):
            for r in ((0, 5, 1), (5, 5, 1), (2, 2, 2)):
                w = three(base, *r) | ((index >> 1) << 11) | ((index & 1) << 21)
                out.append(("%s v%d, v%d, v%d.s[%d]" % ((name,) + r + (index,)), w, r[0], r[1], r[2], "elem", 0, fused, helper))
    for name, vec, scalar in (("FMAX", 0x0E20F400, 0x1E204800), ("FMIN", 0x0EA0F400, 0x1E205800),
                              ("FMAXNM", 0x0E20C400, 0x1E206800), ("FMINNM", 0x0EA0C400, 0x1E207800)):
        for form, base in ((" s", scalar), (" .2s", vec), (" .4s", vec | 0x40000000)):
            for r in REGS:
                out.append(("%s%s v%d, v%d, v%d" % ((name, form) + r), three(base, *r), r[0], r[1], r[2], "minmax", 0, 0,
                            "a64_vfpx_q_minmax("))
    for name, base, dbl, helper in (("FCVT d, s", 0x1E22C000, 0, "a64_vfpx_q_cvtsd("), ("FCVT s, d", 0x1E624000, 1, "a64_vfpx_q_cvtds("),
                                    ("FCVTL .2d, .2s", 0x0E617800, 0, "a64_vfpx_q_cvtl("), ("FCVTL2 .2d, .4s", 0x4E617800, 0, "a64_vfpx_q_cvtl("),
                                    ("FCVTN .2s, .2d", 0x0E616800, 1, "a64_vfpx_q_cvtn(")):
        for rd, rn in ((0, 5), (5, 5), (17, 30)):
            out.append(("%s v%d, v%d" % (name, rd, rn), base | (rn << 5) | rd, rd, rn, rn, "fcvt", dbl, 0, helper))
    return out


# (never wrapped: what the kit's own passes vectorize, the double-precision and pairwise forms, FCVTN2, FMULX, FRECPS)
OTHERS = (("FMUL .4s", 0x6E22DC20), ("FMUL .4s by element", 0x4F829020), ("FMLA .4s by element", 0x4F821020),
          ("FADD .4s", 0x4E22D420), ("FSUB .2s", 0x0EA2D420), ("FMUL .2d", 0x6E62DC20), ("FMLA .2d", 0x4E62CC20),
          ("FDIV .2d", 0x6E62FC20), ("FMAX .2d", 0x4E62F420), ("FMAX d", 0x1E624820), ("FMAXP .4s", 0x6E22F420),
          ("FMAXNMP .4s", 0x6E22C420), ("FCVTN2", 0x4E616820), ("FMULX .2s", 0x0E22DC20), ("FRECPS .2s", 0x0E22FC20),
          ("FMUL s by element", 0x5F829020), ("FCVT half to single", 0x1EE24020), ("FCVTL half", 0x0E217820), ("FMUL s", 0x1E220820))


def with_switch(value, fn):
    old = os.environ.get(SWITCH)
    if value is None:
        os.environ.pop(SWITCH, None)
    else:
        os.environ[SWITCH] = value
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop(SWITCH, None)
        else:
            os.environ[SWITCH] = old


def check_rule(vecfp):
    for value in (None, "", "0", " 0 "):
        if with_switch(value, vecfp.groups):
            raise SystemExit("vecfp: %s=%r turns groups on" % (SWITCH, value))
    if with_switch("1", vecfp.groups) != frozenset(vecfp.GROUPS) or set(vecfp.GROUPS) != {"elem", "vec", "minmax", "fcvt"}:
        raise SystemExit("vecfp: %s=1 is not the four groups" % SWITCH)
    if with_switch("minmax, fcvt", vecfp.groups) != frozenset(("minmax", "fcvt")):
        raise SystemExit("vecfp: a list of groups is not taken as written")
    try:
        with_switch("all", vecfp.groups)
    except SystemExit:
        pass
    else:
        raise SystemExit("vecfp: an unknown group does not stop the lift")
    every = frozenset(vecfp.GROUPS)
    for c in cases():
        call = vecfp.fast_call(c[1], every)
        if not call or not call.startswith(c[8]):
            raise SystemExit("vecfp: %s (%08x) does not get %s: %r" % (c[0], c[1], c[8], call))
        for group in vecfp.GROUPS:   # (a word belongs to one group, and is wrapped only when that one is on)
            if bool(vecfp.fast_call(c[1], frozenset((group,)))) != (group == c[5]):
                raise SystemExit("vecfp: %s (%08x) is not in the group %s alone" % (c[0], c[1], c[5]))
        if vecfp.fast_call(c[1], frozenset()):
            raise SystemExit("vecfp: %s is wrapped with no group on" % c[0])
    for name, w in OTHERS:
        if vecfp.fast_call(w, every):
            raise SystemExit("vecfp: %s (%08x) is wrapped: it is not one of the forms" % (name, w))


def lifted(a64emit, a64_lift, used):
    """vecfp_lifted.h: each guest word lifted with A64_VECFP=1, as the kit writes it, and with the exact body inline"""
    all_cases = cases()
    words = [(0x1000 + 4 * i, c[1]) for i, c in enumerate(all_cases)]
    others = [(0x8000 + 4 * i, w) for i, (_, w) in enumerate(OTHERS)]

    def lift(items, all_translate=True):
        texts, flags = a64emit.translate(items)
        if all_translate and any(flags):
            raise SystemExit("vecfp: a64emit did not translate the guest words: %s" % flags)
        return texts
    raw_now, raw_old = with_switch("1", lambda: lift(words)), with_switch(None, lambda: lift(words))
    if with_switch("1", lambda: lift(others, False)) != with_switch(None, lambda: lift(others, False)):   # (FMULX: no translation)
        raise SystemExit("vecfp: a word that is not one of the forms changes with the switch")
    a64emit.lib().a64_config(1, 0)   # (the fast path off: the exact body inline, the reference)
    try:
        exact = with_switch(None, lambda: lift(words))
    finally:
        a64emit.lib().a64_config(1, 1)
    out = ["/* Generated by tests/test_vecfp.py: each guest word lifted with A64_VECFP=1, as the kit writes it, and exact. */"]
    for i, (rn, ro, ex, c) in enumerate(zip(raw_now, raw_old, exact, all_cases)):
        m = re.fullmatch(r"if \(!(a64_vfpx_q_\w+\([^{}]*?\))\) \{ (.*) \}\n", rn, re.S)
        if not m or not m.group(1).startswith(c[8]) or m.group(2) != ro.strip():
            raise SystemExit("vecfp: %s is not its helper's test around the kit's text: %s" % (c[0], rn[:200]))
        if "a64_vfpx_q_" in ro or "a64_vfpx_q_" in ex:
            raise SystemExit("vecfp: %s has the helper without the switch" % c[0])
        now, old = a64_lift.op_text(rn, used), a64_lift.op_text(ro, used)
        for text in (rn, now):
            if any(line.startswith("}") for line in text.split("\n")):
                raise SystemExit("vecfp: %s: a line of the wrapped text starts with }: %s" % (c[0], text[-200:]))
        if not now.startswith("if (!%s) { " % m.group(1)) or "recomp_fpx_" in ex:
            raise SystemExit("vecfp: %s: the helper's test does not survive the kit's passes, or the exact form has a fast path" % c[0])
        # (the kit's mark grouping: the helper is a plain call, as its own vector helpers are)
        if a64_lift.mg_ends_run("    if (!%s) { c->x[0]=c->x[1]; }" % m.group(1)):
            raise SystemExit("vecfp: mark_groups ends a run of stores at %s" % m.group(1))
        out.append("static void g_now%d(Ctx *__restrict c) { %s }" % (i, now))
        out.append("static void g_old%d(Ctx *__restrict c) { %s }" % (i, old))
        out.append("static void g_exact%d(Ctx *__restrict c) { %s }" % (i, ex))
    out.append("static const struct { const char *name; int rd, rn, rm, dbl; void (*now)(Ctx *), (*old)(Ctx *), (*exact)(Ctx *); } CASES[] = {%s};"
               % ", ".join('{"%s", %d, %d, %d, %d, g_now%d, g_old%d, g_exact%d}' % (c[0], c[2], c[3], c[4], c[6], i, i, i)
                           for i, c in enumerate(all_cases)))
    return "\n".join(out) + "\n", all_cases


def generate(cxx, tmp, flags):
    """a64_fpx.h (with the helpers), the kit's runtime header and C, and vecfp_lifted.h in tmp. Returns (cases, the C file)"""
    dll = os.path.join(tmp, "a64emit.dll" if os.name == "nt" else "liba64emit.so")
    fs.build([cxx, "-std=c++20", "-O0", "-shared", "-Wno-everything", "-o", dll, os.path.join(fs.KIT, "lift", "a64emit.cpp")]
             + flags + ([] if os.name == "nt" else ["-fPIC"]), "a64emit")
    import kit  # noqa: F401  (a64-kit on the path)
    import build_emit
    build_emit.build = lambda force=False: dll   # (not a64emit.dll beside the source)
    import a64_lift
    import a64_rtgen
    import a64emit
    import insn
    import vecfp
    check_rule(vecfp)
    insn.install()
    kit_header = a64_lift.fpx_header(set())
    vecfp.install()   # (the wrap under test, around insn's translate and the kit's fpx_header)
    used = set()
    try:
        a64_rtgen.write(tmp)
        text, all_cases = lifted(a64emit, a64_lift, used)
    finally:
        if a64emit._lib is not None:   # (unloaded, so the folder can go)
            import _ctypes
            (_ctypes.FreeLibrary if os.name == "nt" else _ctypes.dlclose)(a64emit._lib._handle)
            a64emit._lib = None
    if a64_lift.fpx_header(set()) != kit_header + vecfp.HEADER:
        raise SystemExit("vecfp: a64_fpx.h is not the kit's header with the helpers after it")
    rt_c = [f for f in sorted(os.listdir(tmp)) if f.startswith("a64_") and f.endswith(".c")]   # (what a64_rtgen wrote)
    if len(rt_c) != 1:
        raise SystemExit("vecfp: a64_rtgen wrote %s, not one C file" % rt_c)
    with open(os.path.join(tmp, "vecfp_lifted.h"), "w", newline="\n") as f:
        f.write(text)
    with open(os.path.join(tmp, "a64_fpx.h"), "w", newline="\n") as f:
        f.write(a64_lift.fpx_header(used))
    return all_cases, os.path.join(tmp, rt_c[0])


def check_sources():
    with open(os.path.join(ROOT, "nx2", "lift.py"), encoding="utf-8") as f:
        lift = f.read()
    at = [lift.find(p) for p in ("import vecfp", "insn.install()", "vecfp.install()", "def main():")]
    if min(at) < 0 or not at[1] < at[2] < at[3]:
        raise SystemExit("vecfp: nx2/lift.py does not install nx2/vecfp.py at module level after insn's")
    with open(os.path.join(ROOT, "nx2", "make_game.py"), encoding="utf-8") as f:
        make_game = f.read()
    if 'if k.startswith(("A64_", "OOT_", "RX_"))' not in make_game or not SWITCH.startswith("A64_"):
        raise SystemExit("vecfp: nx2/make_game.py's lift_key no longer takes the A64_ variables: %s is not in the key" % SWITCH)
    not_keyed = re.search(r"^LIFT_KEY_NOT = \((.*?)\)   #", make_game, re.S | re.M)
    if not not_keyed or '"vecfp.py"' in not_keyed.group(1):
        raise SystemExit("vecfp: nx2/vecfp.py must stay a file of the lift key")
    with open(os.path.join(ROOT, "docs", "development.md"), encoding="utf-8") as f:
        if "| `A64_VECFP=1` |" not in f.read():
            raise SystemExit("vecfp: docs/development.md: A64_VECFP is not in the switches table")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cc")
    p.add_argument("--cxx")
    p.add_argument("--random", type=int, default=20000)
    p.add_argument("--verbose", action="store_true", help="print how many states each word's helper did")
    a = p.parse_args()
    check_sources()
    if platform.machine().lower() not in ("x86_64", "amd64"):
        fs.skip("not an x86-64 host: %s" % platform.machine())
    cc = fs.compiler(a.cc, "CC", ("clang", "gcc", "cc"), "clang")
    cxx = fs.compiler(a.cxx, "CXX", ("clang++", "g++", "c++"), "clang++")
    if not cc or not cxx:
        fs.skip("no C compiler" if not cc else "no C++ compiler")
    t0 = time.time()
    failed, checks = [], 0
    with tempfile.TemporaryDirectory(prefix="triforce-vecfp-") as tmp:
        all_cases, rt_c = generate(cxx, tmp, fs.target_flags(cxx, tmp))
        for march in MARCHES:
            exe = os.path.join(tmp, "vecfp_test_%s.exe" % march)
            fs.build([cc] + fs.target_flags(cc, tmp) + ["-march=" + march] + fs.FLAGS +
                     ["-D_CRT_SECURE_NO_WARNINGS", "-Wno-everything", "-I" + os.path.join(fs.KIT, "rt"), "-I" + tmp,
                      os.path.join(ROOT, "tests", "vecfp_test.c"), rt_c, "-o", exe], "the driver at " + march)
            r = fs.run([exe, str(a.random), str(SEED)], timeout=3600)
            lines = r.stdout.splitlines()
            total = [l for l in lines if l.startswith("total ")]
            print("%-10s %s" % (march, "\n           ".join(l for l in lines if a.verbose or not l.startswith("case "))))
            if r.returncode == 3:
                print("vecfp: %s skipped (this CPU cannot run it)" % march)
                continue
            if r.returncode or len(total) != 1:
                failed.append("%s (exit %d)" % (march, r.returncode))
                continue
            t = {k: int(v) for k, v in (kv.split("=") for kv in total[0].split()[1:])}
            checks += t["checks"]
            if march == "x86-64-v3" and not t["fma"] or march in ("x86-64-v2", "x86-64") and t["fma"]:
                failed.append("%s: built with%s FMA3" % (march, "" if t["fma"] else "out"))
            done = {int(m.group(1)): int(m.group(2)) for m in (re.match(r"case (\d+) done (\d+) of", l) for l in lines) if m}
            for i, c in enumerate(all_cases):
                if c[7] and not t["fma"]:   # (a fused op without FMA3: never)
                    if done.get(i):
                        failed.append("%s: %s was done %d times without FMA3" % (march, c[0], done[i]))
                elif not 0 < done.get(i, 0) < a.random:   # (done in some states and declined in others)
                    failed.append("%s: %s: its helper did %d of %d states" % (march, c[0], done.get(i, 0), a.random))
    if failed:
        raise SystemExit("FAIL: vecfp: %s" % "; ".join(failed[:12]))
    print("PASS: %d guest words lifted with A64_VECFP=1 leave the same registers, flags and FPSR as the kit's text and "
          "the exact bodies: %d states, each three ways (%.0f s)" % (len(all_cases), checks, time.time() - t0))


if __name__ == "__main__":
    main()
