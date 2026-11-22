"""DMB of the load or the store kind as a compiler barrier in code lifted with A64_DMB_LIGHT=1 (game-free).

(Triforce, 11-22, the performance audit's LIFT-47, after Source B's.) The kit's translator writes every DMB and DSB as
recomp_barrier(), an out-of-line full fence. x86-64 keeps load-load, load-store and store-store order in hardware, so a
DMB that asks only for those (ISHLD, ISHST and the OSH, NSH and full-system forms: eight words) needs no instruction
there, only that the compiler moves no guest access across it. With A64_DMB_LIGHT=1 at lift time nx2/insn.py writes
A64_DMB_LDST() for those eight, which nx2/rtgen.py's a64.h defines as an empty asm with a "memory" clobber on x86-64 and
as recomp_barrier() on any other host. Off by default: unset, empty or 0 is the kit's text.

The rule (nx2/insn.py emit, dmb_light): with the switch the eight words give the macro; a full DMB (ISH, SY, OSH, NSH),
every DSB (the LD and ST kinds too, SSBB, PSSBB), ISB and CLREX give None, the kit's text; without the switch, or with
it empty or 0, every word gives None.

The lifted text: each word goes through the real translator (a64emit.translate under insn.install(), then
a64_lift.op_text) twice, with A64_DMB_LIGHT=1 and without. The eight must be the macro alone with the switch and the
kit's recomp_barrier() without; the others must be the same text both times. The kit's mark grouping
(a64_lift.mark_groups) must end a run of stores at the macro, as it does at the fence: no mark moves across it.

The run: tests/dmb_light_test.c runs every word both ways, alone and between a store and a load of the same guest
address (STR; DMB; LDR; STR; DMB; LDR), from the same random Ctx (every flag combination, registers and vector
registers random) and guest memory, and compares the whole Ctx and the bytes stored. It also counts the calls of
recomp_barrier: none in the light text on x86-64, one a barrier in the kit's. Built at -march=x86-64 and -march=native.
What a single thread cannot show, the order other threads see, is not tested here.

And reads the source: nx2/rtgen.py's a64.h holds the macro once, guarded by __x86_64__, with the fence for other
hosts; the switch is an A64_ name, which nx2/make_game.py's lift_key takes, and nx2/insn.py and nx2/rtgen.py are files of
the lift key; the switch is in the switches table.

    python -I -B tests/test_dmb_light.py [--cc clang] [--cxx clang++] [--random 20000]

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
MARCHES = ("x86-64", "native")
SWITCH = "A64_DMB_LIGHT"
MACRO = "A64_DMB_LDST();"
KINDS = {0: "OSH", 1: "NSH", 2: "ISH", 3: "SY"}
STR_X1, LDR_X3, STR_X4_8, LDR_X5_8 = 0xF9000041, 0xF9400043, 0xF9000444, 0xF9400445   # ([x2], [x2], [x2,#8], [x2,#8])


def dmb(crm):
    return 0xD50330BF | (crm << 8)


def dsb(crm):
    return 0xD503309F | (crm << 8)


def light_words():
    """(name, word): the eight DMBs of the load or store kind"""
    return [("DMB %s%s" % (KINDS[crm >> 2], "LD" if crm & 3 == 1 else "ST"), dmb(crm))
            for crm in range(16) if crm & 3 in (1, 2)]


def full_words():
    """(name, word): what keeps the fence. A full DMB of every domain, DSBs of every kind, the reserved CRm<1:0> = 00"""
    out = [("DMB %s" % KINDS[crm >> 2], dmb(crm)) for crm in (3, 7, 11, 15)]
    out += [("DMB crm=%d (reserved)" % crm, dmb(crm)) for crm in (0, 4, 8, 12)]
    out += [("DSB %sLD" % KINDS[crm >> 2], dsb(crm)) for crm in (1, 5, 9, 13)]
    out += [("DSB %sST" % KINDS[crm >> 2], dsb(crm)) for crm in (2, 6, 10, 14)]
    out += [("DSB %s" % KINDS[crm >> 2], dsb(crm)) for crm in (3, 7, 11, 15)]
    out += [("SSBB", dsb(0)), ("PSSBB", dsb(4))]
    return out


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


def check_rule(insn):
    assert len(light_words()) == 8
    assert (dmb(11), dmb(15), dsb(9)) == (0xD5033BBF, 0xD5033FBF, 0xD503399F)   # (DMB ISH, DMB SY, DSB ISHLD)
    others = full_words() + [("ISB", 0xD5033FDF), ("CLREX", 0xD503305F), ("NOP", 0xD503201F)]
    for name, w in light_words():
        if with_switch("1", lambda: insn.emit(w)) != MACRO:
            raise SystemExit("dmb light: %s (%08x) is not %s with %s=1" % (name, w, MACRO, SWITCH))
        for off in (None, "", "0"):
            if with_switch(off, lambda: insn.emit(w)) is not None:
                raise SystemExit("dmb light: %s (%08x) is rewritten with %s=%r" % (name, w, SWITCH, off))
    for name, w in others:
        for value in ("1", None):
            if with_switch(value, lambda: insn.emit(w)) is not None:
                raise SystemExit("dmb light: %s (%08x) is rewritten (%s=%r): it keeps the kit's text" % (name, w, SWITCH, value))


def shapes():
    """(name, guest words, barriers in it, of which light)"""
    out = []
    for name, w in light_words():
        out.append((name, [w], 1, 1))
        out.append(("STR; %s; LDR; STR; %s; LDR" % (name, name), [STR_X1, w, LDR_X3, STR_X4_8, w, LDR_X5_8], 2, 2))
    for name, w in full_words():
        out.append((name, [w], 1, 0))
    out.append(("STR; DMB ISHST; LDR; STR; DMB ISH; LDR", [STR_X1, dmb(10), LDR_X3, STR_X4_8, dmb(11), LDR_X5_8], 2, 1))
    return out


def lifted(a64emit, a64_lift, used):
    """dmb_lifted.h: each shape as lifted with the switch and without, as functions, and the CASES table"""
    all_shapes = shapes()
    out = ["/* Generated by tests/test_dmb_light.py: each shape lifted with A64_DMB_LIGHT=1 and without. */"]
    for i, (name, words, barriers, light) in enumerate(all_shapes):
        items = [(0x1000 + 4 * k, w) for k, w in enumerate(words)]

        def lift():
            texts, flags = a64emit.translate(items)
            if any(flags):
                raise SystemExit("dmb light: a64emit did not translate %s: %s" % (name, flags))
            return [a64_lift.op_text(t, used).strip() for t in texts]
        now, old = with_switch("1", lift), with_switch(None, lift)
        for w, n, o in zip(words, now, old):
            is_light = (w & 0xFFFFF0FF) == 0xD50330BF and (w >> 8) & 3 in (1, 2)
            if is_light and (n != MACRO or "recomp_barrier();" not in o or "A64_DMB_LDST" in o):
                raise SystemExit("dmb light: %08x in %s: with the switch %r, without %r" % (w, name, n, o))
            if not is_light and (n != o or "A64_DMB_LDST" in n):
                raise SystemExit("dmb light: %08x in %s changes with the switch: %r, %r" % (w, name, n, o))
        if sum(t.count("recomp_barrier();") for t in old) != barriers or \
                sum(t.count("recomp_barrier();") for t in now) != barriers - light:
            raise SystemExit("dmb light: %s: the fences in the lifted text are not %d and %d" % (name, barriers, barriers - light))
        out.append("static void g_now%d(Ctx *__restrict c) { %s }" % (i, " ".join(now)))
        out.append("static void g_old%d(Ctx *__restrict c) { %s }" % (i, " ".join(old)))
    out.append("static const struct { const char *name; void (*now)(Ctx *), (*old)(Ctx *); int barriers, light; } CASES[] = {%s};"
               % ", ".join('{"%s", g_now%d, g_old%d, %d, %d}' % (s[0], i, i, s[2], s[3]) for i, s in enumerate(all_shapes)))
    return "\n".join(out) + "\n", len(all_shapes)


def check_marks(a64_lift):
    """The kit's mark grouping ends a run of stores at the macro, as at the fence: the group's mark stays before it"""
    for end in ("    " + MACRO, "    recomp_barrier();"):
        if not a64_lift.mg_ends_run(end):
            raise SystemExit("dmb light: mark_groups does not end a run at %r" % end.strip())
        body = "\n".join(["void f_80000000(Ctx *A64_NOESC c) {", "    recomp_store32(c,c->x[21] + 0,c->x[1]);",
                          "    recomp_store32(c,c->x[21] + 4,c->x[2]);", end, "    recomp_store32(c,c->x[21] + 8,c->x[3]);",
                          "    return;", "}", ""])
        got = a64_lift.mark_groups(body).split("\n")
        at = got.index(end)
        if "A64_MARK(" not in got[at - 1] or any("A64_MARK(" in line for line in got[at + 1:at + 2]):
            raise SystemExit("dmb light: mark_groups moved a mark across %r:\n%s" % (end.strip(), "\n".join(got)))


def generate(cxx, tmp, flags):
    """a64.h (nx2/rtgen.py's, in tmp/rt64), a64_fpx.h, the kit's runtime C and dmb_lifted.h, by the generators the lift
    runs (a64emit built into tmp). Returns (the shapes, rt64, the runtime's C file)"""
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
    import rtgen
    check_rule(insn)
    insn.install()   # (the override point under test, around the kit's translate)
    check_marks(a64_lift)
    used = set()
    try:
        a64_rtgen.write(tmp)
        text, n = lifted(a64emit, a64_lift, used)
    finally:
        if a64emit._lib is not None:   # (unloaded, so the folder can go)
            import _ctypes
            (_ctypes.FreeLibrary if os.name == "nt" else _ctypes.dlclose)(a64emit._lib._handle)
            a64emit._lib = None
    with open(os.path.join(tmp, "dmb_lifted.h"), "w", newline="\n") as f:
        f.write(text)
    with open(os.path.join(tmp, "a64_fpx.h"), "w", newline="\n") as f:
        f.write(a64_lift.fpx_header(used))
    rt64 = rtgen.write(os.path.join(tmp, "rt64"))
    with open(os.path.join(rt64, "a64.h"), encoding="utf-8") as f:
        header = f.read()
    want = re.compile(r"#if defined\(__x86_64__\)\n#define A64_DMB_LDST\(\) __asm__ __volatile__\(\"\" ::: \"memory\"\)\n"
                      r"#else\n#define A64_DMB_LDST\(\) recomp_barrier\(\)\n#endif\n")
    if len(want.findall(header)) != 1 or header.count("#define A64_DMB_LDST") != 2:
        raise SystemExit("dmb light: nx2/rtgen.py's a64.h does not define A64_DMB_LDST once, guarded by __x86_64__")
    rt_c = [f for f in sorted(os.listdir(tmp)) if f.startswith("a64_") and f.endswith(".c")]   # (what a64_rtgen wrote)
    if len(rt_c) != 1:
        raise SystemExit("dmb light: a64_rtgen wrote %s, not one C file" % rt_c)
    return n, rt64, os.path.join(tmp, rt_c[0])


def check_sources():
    with open(os.path.join(ROOT, "nx2", "insn.py"), encoding="utf-8") as f:
        insn_text = f.read()
    for line in ('    return (w & 0xFFFFF0FF) == 0xD50330BF and ((w >> 8) & 3) in (1, 2) and '
                 'os.environ.get("A64_DMB_LIGHT", "0") not in ("", "0")',
                 '        return "A64_DMB_LDST();" if dmb_light(w) else None'):
        if insn_text.count(line) != 1:
            raise SystemExit("dmb light: nx2/insn.py no longer has the line %r" % line.strip())
    with open(os.path.join(ROOT, "nx2", "rtgen.py"), encoding="utf-8") as f:
        if "(RET_MISMATCH, RET_MISMATCH + POLL_DECL + DMB_LDST)," not in f.read():
            raise SystemExit("dmb light: nx2/rtgen.py no longer adds DMB_LDST to a64.h")
    with open(os.path.join(ROOT, "nx2", "make_game.py"), encoding="utf-8") as f:
        make_game = f.read()
    # (the lift key: every A64_ variable of the environment, and every file of nx2/ but LIFT_KEY_NOT's)
    if 'if k.startswith(("A64_", "OOT_", "RX_"))' not in make_game or not SWITCH.startswith("A64_"):
        raise SystemExit("dmb light: nx2/make_game.py's lift_key no longer takes the A64_ variables: %s is not in the key" % SWITCH)
    not_keyed = re.search(r"^LIFT_KEY_NOT = \((.*?)\)   #", make_game, re.S | re.M)
    if not not_keyed or '"insn.py"' in not_keyed.group(1) or '"rtgen.py"' in not_keyed.group(1):
        raise SystemExit("dmb light: nx2/insn.py and nx2/rtgen.py must stay files of the lift key")
    with open(os.path.join(ROOT, "docs", "development.md"), encoding="utf-8") as f:
        if "| `A64_DMB_LIGHT=1` |" not in f.read():
            raise SystemExit("dmb light: docs/development.md: A64_DMB_LIGHT is not in the switches table")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cc")
    p.add_argument("--cxx")
    p.add_argument("--random", type=int, default=20000)
    a = p.parse_args()
    check_sources()
    if platform.machine().lower() not in ("x86_64", "amd64"):
        fs.skip("not an x86-64 host: %s" % platform.machine())
    cc = fs.compiler(a.cc, "CC", ("clang", "gcc", "cc"), "clang")
    cxx = fs.compiler(a.cxx, "CXX", ("clang++", "g++", "c++"), "clang++")
    if not cc or not cxx:
        fs.skip("no C compiler" if not cc else "no C++ compiler")
    t0 = time.time()
    failed = []
    with tempfile.TemporaryDirectory(prefix="triforce-dmb-light-") as tmp:
        n, rt64, rt_c = generate(cxx, tmp, fs.target_flags(cxx, tmp))
        for march in MARCHES:
            exe = os.path.join(tmp, "dmb_light_test_%s.exe" % march)
            fs.build([cc] + fs.target_flags(cc, tmp) + ["-march=" + march] + fs.FLAGS +
                     ["-D_CRT_SECURE_NO_WARNINGS", "-I" + rt64, "-I" + os.path.join(fs.KIT, "rt"), "-I" + tmp,
                      os.path.join(ROOT, "tests", "dmb_light_test.c"), rt_c, "-o", exe], "the driver at " + march)
            r = fs.run([exe, str(a.random), str(SEED)], timeout=1200)
            print("%-10s %s" % (march, r.stdout.rstrip()))
            if r.returncode:
                failed.append("%s (exit %d)" % (march, r.returncode))
    if failed:
        raise SystemExit("FAIL: dmb light: %s" % ", ".join(failed))
    print("PASS: %d shapes lifted with A64_DMB_LIGHT=1 leave the same registers, flags and memory as the kit's text, "
          "the eight light DMBs without a fence (%.0f s)" % (n, time.time() - t0))


if __name__ == "__main__":
    main()
