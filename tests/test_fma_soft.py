"""The exact fused multiply-add bodies' short way out on a CPU without FMA3, bit-exact with the bodies (game-free).

(Triforce, 11-22, the performance audit's LIFT-06, after Source A's.) Where the build has no hardware FMA (x86-64-v2)
every double-precision FMADD, and each single-precision one its binary64 fast path cannot prove, runs the kit's exact
body: integer code of many words. nx2/fma_soft.py puts a short way out at the head of recomp_fpe_fma64 and
recomp_fpe_fma32 for the plain case (default FPCR with or without FZ, three normal operands, a normal result): an exact
product and sum in binary64, rounded to odd, then rounded once, FPSR.IXC set when the result is inexact. Everything
else goes on into the body.

The text: the kit's runtime C from a64_rtgen.runtime_c() under fma_soft.install() must be the kit's own text with
three pieces put in (the header after `#include "a64.h"`, one group of lines after each body's head) and nothing else
changed; with A64_NO_FMA_SOFT=1 it must be the kit's text byte for byte.

The run: tests/fma_soft_test.c calls both bodies with the way out and without it (the same body past its first lines,
so the kit's code) from the same Ctx, and compares the value and every byte of the Ctx:
  - random: 10 million operand triples a width (zeros, subnormals, infinities, NaNs of both kinds with payloads, the
    extreme normals, exponents everywhere, at the way out's limits and matched to the product; addends that cancel the
    product within a few ulps, sit at its half ulp, or have the product at their half ulp), under random FPCR (FZ, DN,
    every rounding mode, FIZ/AH/NEP, the trap enables, FZ16, the host's kill switch) and FPSR states;
  - sweep: about 7 million: edge exponents and fractions for both factors, each with 71 addends placed against the
    product, under FZ on and off with IXC set and clear.
Built at -march=x86-64-v2 and -march=x86-64 (no FMA: the way out is compiled, and must answer calls, set IXC on some,
leave it clear on exact ones, and answer under FZ), and at -march=x86-64-v3 and -march=native (with FMA3 it is compiled
out: no call may be answered). A build without the test's hook checks HOS_FMA_FAST as the game reads it: unset and 1
answer, 0 answers none.

And reads the source: nx2/lift.py installs it, A64_NO_FMA_SOFT is an A64_ name (in nx2/make_game.py's lift key, as
nx2/fma_soft.py is), and both switches are in the switches table.

    python -I -B tests/test_fma_soft.py [--cc clang] [--cxx clang++] [--random 10000000] [--time]

Skipped (exit 0) on a host that is not x86-64 or has no C or C++ compiler.
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import test_fpx_sticky as fs  # noqa: E402  (the build helpers the kit's other lifted-code tests use)

RUN_ALL_ARGS = ["--cc", "clang", "--cxx", "{cxx}"]
SEED = 20261122
MARCHES = ("x86-64-v2", "x86-64", "x86-64-v3", "native")
HOOK = """/* tests/test_fma_soft.py: the way out switched by the driver, and its answers counted */
extern int fma_soft_test_on;
extern long long fma_soft_test_exits;
#define RECOMP_FMA_SOFT_PROBE() (fma_soft_test_exits++)
#ifndef FMA_SOFT_ENV
#define RECOMP_FMA_SOFT_ON() fma_soft_test_on
#endif
"""


def generate(cxx, tmp, flags):
    """The kit's runtime header and C (the C with the way out), a64_fpx.h and the hook header in tmp. Returns the C file"""
    dll = os.path.join(tmp, "a64emit.dll" if os.name == "nt" else "liba64emit.so")
    fs.build([cxx, "-std=c++20", "-O0", "-shared", "-Wno-everything", "-o", dll, os.path.join(fs.KIT, "lift", "a64emit.cpp")]
             + flags + ([] if os.name == "nt" else ["-fPIC"]), "a64emit")
    import kit  # noqa: F401  (a64-kit on the path)
    import build_emit
    build_emit.build = lambda force=False: dll   # (not a64emit.dll beside the source)
    import a64_lift
    import a64_rtgen
    import a64emit
    import fma_soft
    try:
        kit_text = a64_rtgen.runtime_c()
        fma_soft.install()   # (the wrapper under test, around the kit's runtime_c)
        now = a64_rtgen.runtime_c()
        os.environ["A64_NO_FMA_SOFT"] = "1"
        try:
            off = a64_rtgen.runtime_c()
        finally:
            del os.environ["A64_NO_FMA_SOFT"]
        before = set(os.listdir(tmp))
        a64_rtgen.write(tmp)
    finally:
        if a64emit._lib is not None:   # (unloaded, so the folder can go)
            import _ctypes
            (_ctypes.FreeLibrary if os.name == "nt" else _ctypes.dlclose)(a64emit._lib._handle)
            a64emit._lib = None
    if off != kit_text:
        raise SystemExit("fma soft: with A64_NO_FMA_SOFT=1 the runtime C is not the kit's text")
    pieces = [fma_soft.HEADER] + [fma_soft.EARLY % n for n in (32, 64)]
    stripped = now
    for piece in pieces:
        if stripped.count(piece) != 1:
            raise SystemExit("fma soft: the runtime C does not hold this piece once: %s" % piece.strip()[:80])
        stripped = stripped.replace(piece, "")
    if stripped != kit_text:
        raise SystemExit("fma soft: the runtime C differs from the kit's by more than the header and the two ways out")
    for n in (32, 64):   # (the way out is the body's first lines: right after its head)
        if (fma_soft.HEAD % n) + (fma_soft.EARLY % n) not in now:
            raise SystemExit("fma soft: recomp_fpe_fma%d does not begin with the way out" % n)
    rt_c = [f for f in sorted(set(os.listdir(tmp)) - before) if f.endswith(".c")]
    if len(rt_c) != 1:
        raise SystemExit("fma soft: a64_rtgen wrote %s, not one C file" % rt_c)
    with open(os.path.join(tmp, rt_c[0]), encoding="utf-8") as f:
        if f.read() != now:
            raise SystemExit("fma soft: a64_rtgen.write did not write the runtime C with the way out")
    with open(os.path.join(tmp, "a64_fpx.h"), "w", newline="\n") as f:
        f.write(a64_lift.fpx_header(set()))
    with open(os.path.join(tmp, "fma_soft_hook.h"), "w", newline="\n") as f:
        f.write(HOOK)
    return os.path.join(tmp, rt_c[0])


def check_sources():
    with open(os.path.join(ROOT, "nx2", "lift.py"), encoding="utf-8") as f:
        lift = f.read()
    at = [lift.find(p) for p in ("import fma_soft", "import a64_rtgen", "fma_soft.install()", "def main():")]
    if min(at) < 0 or not at[1] < at[2] < at[3]:
        raise SystemExit("fma soft: nx2/lift.py does not install nx2/fma_soft.py at module level")
    with open(os.path.join(ROOT, "nx2", "make_game.py"), encoding="utf-8") as f:
        make_game = f.read()
    if 'if k.startswith(("A64_", "OOT_", "RX_"))' not in make_game:
        raise SystemExit("fma soft: nx2/make_game.py's lift_key no longer takes the A64_ variables: A64_NO_FMA_SOFT is not in the key")
    not_keyed = re.search(r"^LIFT_KEY_NOT = \((.*?)\)   #", make_game, re.S | re.M)
    if not not_keyed or '"fma_soft.py"' in not_keyed.group(1):
        raise SystemExit("fma soft: nx2/fma_soft.py must stay a file of the lift key")
    with open(os.path.join(ROOT, "docs", "development.md"), encoding="utf-8") as f:
        if "| `HOS_FMA_FAST=0`, `A64_NO_FMA_SOFT=1` |" not in f.read():
            raise SystemExit("fma soft: docs/development.md: HOS_FMA_FAST and A64_NO_FMA_SOFT are not in the switches table")


def counts(text, mode):
    """{(mode, width): {name: number}} from the driver's lines"""
    out = {}
    for line in text.splitlines():
        m = re.match(r"%s fma(\d+) (.*)" % mode, line)
        if m:
            out[int(m.group(1))] = {k: int(v) for k, v in (kv.split("=") for kv in m.group(2).split())}
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cc")
    p.add_argument("--cxx")
    p.add_argument("--random", type=int, default=10000000)
    p.add_argument("--time", action="store_true", help="also time a plain call with the way out and without, at x86-64-v2")
    a = p.parse_args()
    check_sources()
    if platform.machine().lower() not in ("x86_64", "amd64"):
        fs.skip("not an x86-64 host: %s" % platform.machine())
    cc = fs.compiler(a.cc, "CC", ("clang", "gcc", "cc"), "clang")
    cxx = fs.compiler(a.cxx, "CXX", ("clang++", "g++", "c++"), "clang++")
    if not cc or not cxx:
        fs.skip("no C compiler" if not cc else "no C++ compiler")
    t0 = time.time()
    failed, total = [], 0
    with tempfile.TemporaryDirectory(prefix="triforce-fma-soft-") as tmp:
        rt_c = generate(cxx, tmp, fs.target_flags(cxx, tmp))

        def build(march, extra, name):
            exe = os.path.join(tmp, "%s_%s.exe" % (name, march))
            fs.build([cc] + fs.target_flags(cc, tmp) + ["-march=" + march] + fs.FLAGS + extra +
                     ["-D_CRT_SECURE_NO_WARNINGS", "-include", os.path.join(tmp, "fma_soft_hook.h"),
                      "-I" + os.path.join(fs.KIT, "rt"), "-I" + tmp, os.path.join(ROOT, "tests", "fma_soft_test.c"), rt_c,
                      "-o", exe], "the driver at " + march)
            return exe

        for march in MARCHES:
            exe = build(march, [], "fma_soft_test")
            for mode, args in (("random", ["random", str(a.random), str(SEED)]), ("sweep", ["sweep"])):
                r = fs.run([exe] + args, timeout=3600)
                print("%-10s %s" % (march, r.stdout.rstrip().replace("\n", "\n           ")))
                if r.returncode == 3:
                    print("fma soft: %s skipped (this CPU cannot run it)" % march)
                    break
                got = counts(r.stdout, mode)
                if r.returncode or sorted(got) != [32, 64]:
                    failed.append("%s %s (exit %d)" % (march, mode, r.returncode))
                    continue
                for width, c in sorted(got.items()):
                    total += c["checks"]
                    if c["fma64"]:   # (FMA3: compiled out)
                        if c["exits"]:
                            failed.append("%s %s fma%d: the way out answered %d calls in a build with FMA3" % (march, mode, width, c["exits"]))
                    elif not (c["exits"] and c["new_ixc"] and c["exact"] and c["fz"]):
                        failed.append("%s %s fma%d: the way out is not exercised: %s" % (march, mode, width, c))
                    if not c["fma64"] and march in ("x86-64-v3",):
                        failed.append("%s: built without FMA3" % march)
                    if c["fma64"] and march in ("x86-64-v2", "x86-64"):
                        failed.append("%s: built with FMA3" % march)
        # HOS_FMA_FAST as the game reads it (the build without the hook's switch): unset and 1 answer, 0 answers none
        exe = build("x86-64-v2", ["-DFMA_SOFT_ENV"], "fma_soft_env")
        sums = set()
        for value, want in ((None, True), ("1", True), ("0", False)):
            env = {k: v for k, v in os.environ.items() if k != "HOS_FMA_FAST"}
            if value is not None:
                env["HOS_FMA_FAST"] = value
            r = subprocess.run([exe, "env"], stdout=subprocess.PIPE, text=True, env=env, timeout=120)
            m = re.match(r"fma64=0 exits=(\d+) sum=(\w+)", r.stdout)
            if r.returncode == 3:
                break
            if not m or (int(m.group(1)) == 2000) != want or (int(m.group(1)) == 0) == want:
                failed.append("HOS_FMA_FAST=%s: %s" % (value, r.stdout.strip()))
            elif m:
                sums.add(m.group(2))
        if len(sums) > 1:
            failed.append("HOS_FMA_FAST changes a result: %s" % sorted(sums))
        if a.time and not failed:
            print("timing at -O2 -march=x86-64-v2:")
            print(fs.run([build("x86-64-v2", [], "fma_soft_test"), "time"], timeout=1200).stdout.rstrip())
    if failed:
        raise SystemExit("FAIL: fma soft: %s" % "; ".join(failed))
    print("PASS: %d calls of the exact FMA bodies give the same value and context with the short way out as without (%.0f s)"
          % (total, time.time() - t0))


if __name__ == "__main__":
    main()
