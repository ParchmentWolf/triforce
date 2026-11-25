"""RX_COLD_OPT: the lifted chunks at -O2, each compiled as parts cut where a function begins (nx2/cold_parts.py), on
made-up chunks (game-free).

(Triforce, 11-22, the performance audit's LIFT-17, after Source A's.) The build compiles the hot pieces at -O2 and every
other lifted chunk at -O1. RX_COLD_OPT=O2 (or a file that lists chunks) asks for -O2 on those too, and each such chunk is
then compiled as parts of RX_COLD_PART_MB, written under <build>/split.

The rules:
  - RX_COLD_OPT unset, empty or O1 is nothing: the build's sources come back as the same list, no file takes other flags,
    and nothing is written. O2 is every lifted chunk (code_NNN.c and the lift's own parts code_NNN_M.c), a file is the
    chunks it lists; a hot piece, the hot file and the runtime's files never. Any other value, or a list with a name that
    is not a chunk's, stops the build with a message.
  - RX_COLD_PART_MB: 6 when unset, 0 for no cut; anything that is not a size stops the build.
  - The flags of a -O2 chunk are the chunks' flags with -O2 where the level was and the part size as a define, so the size
    is in every object's key; nothing else changes.
  - The parts hold the chunk's functions once and in order; every part begins with the chunk's declarations and then
    with a function's first line (or the note above it); no part is past the budget unless it is one function; a chunk
    that fits the budget is one part, its own text.
  - The key file: a second call with the same chunk and size writes no file; another size, another chunk text, a part
    gone or a key gone writes them again, and parts the new cut does not make are removed. The key holds the size.
  - The lift's files are not touched: the chunk's bytes and its folder's listing are the same after.

The compile (clang; skipped without one): a made-up chunk of functions that call each other is built whole and as its
parts, both at -O2, and run on the same contexts: the same registers after every function.

And reads the source: nx2/build.py asks cold_parts.expand for its sources and gives the parts cold_fl, the hot pieces
their own flags as before; nx2/make_game.py leaves nx2/cold_parts.py out of the lift key; the switches are in the table.

    python -I -B tests/test_chunk_parts.py [--cc clang]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import kit  # noqa: E402,F401  (a64-kit on the path, for chunks)
import chunks  # noqa: E402
import cold_parts  # noqa: E402
import lifted_c  # noqa: E402

RUN_ALL_ARGS = ["--cc", "clang"]


def check(what, ok):
    if not ok:
        raise SystemExit("FAIL: chunk parts: " + what)


def stops(fn):
    try:
        fn()
    except SystemExit as e:
        return bool(str(e))
    return False


def function(addr, size, callee=None, note=None):
    head = "void f_%08x(Ctx *__restrict A64_NOESC c) {\n" % addr
    line = "c->x[1] = c->x[1] * 3 + c->x[2] + %d;\n" % (addr & 0xff)
    call = "f_%08x(c);\n" % callee if callee else ""
    return ("/* %s */\n" % note if note else "") + head + line * max(1, (size - len(head) - len(call) - 2) // len(line)) + call + "}\n"


def made_up_chunk(n, giant=0):
    """(the preamble, the functions): n small functions, each calling the one after it now and then; one giant among them"""
    addrs = [0x80000000 + 16 * i for i in range(n)]
    preamble = '#include "a64.h"\n' + "".join("void f_%08x(Ctx *A64_NOESC);\n" % a for a in addrs)
    fns = []
    for i, a in enumerate(addrs):
        size = giant if giant and i == n // 3 else 1500 + 37 * (i % 11)
        fns.append(function(a, size, addrs[i + 1] if i % 4 == 0 and i + 1 < n else None, "a note" if i % 7 == 3 else None))
    return preamble, fns


def check_rules(tmp):
    lvl = cold_parts.cold_level
    check("unset, empty and O1 ask nothing", lvl({}) is None and lvl({"RX_COLD_OPT": ""}) is None and lvl({"RX_COLD_OPT": " O1 "}) is None)
    check("O2 is every chunk", lvl({"RX_COLD_OPT": "O2"}) == "all")
    check("another level stops the build", all(stops(lambda v=v: lvl({"RX_COLD_OPT": v})) for v in ("O3", "o2", "-O2", "1", "all")))
    listed = os.path.join(tmp, "cold.txt")
    with open(listed, "w") as f:
        f.write("# the next tier\ncode_003.c\n\ncode_012_1.c   # the giant's part\n")
    check("a file lists chunks", lvl({"RX_COLD_OPT": listed}) == frozenset(("code_003.c", "code_012_1.c")))
    for bad in ("code_hot_2.c", "code_hot.c", "a64_table.c", "code_3.c", "code_003.p0.c"):
        with open(os.path.join(tmp, "bad.txt"), "w") as f:
            f.write("code_001.c\n%s\n" % bad)
        check("a list naming %s stops the build" % bad, stops(lambda: lvl({"RX_COLD_OPT": os.path.join(tmp, "bad.txt")})))
    o2 = cold_parts.chunk_opt_o2
    check("every chunk under O2", o2("code_000.c", "all") and o2("code_047.c", "all") and o2("code_012_3.c", "all"))
    check("the hot pieces and the runtime's files never", not any(o2(n, "all") for n in (
        "code_hot.c", "code_hot_0.c", "code_hot_7.c", "a64_table.c", "a64_hooks.c", "hos_image.c", "a64_stubs.c", "code_000.p0.c",
        "code_000.c.whole")))
    some = frozenset(("code_003.c",))
    check("only the listed chunks under a list", o2("code_003.c", some) and not o2("code_004.c", some) and not o2("code_hot_3.c", some))
    check("no chunk when nothing is asked", not o2("code_003.c", None))
    pb = cold_parts.part_bytes
    check("6 MB when unset", pb({}) == 6 << 20 == pb({"RX_COLD_PART_MB": ""}) and cold_parts.PART_MB_DEFAULT == 6)
    check("the size as given", pb({"RX_COLD_PART_MB": "8"}) == 8 << 20 and pb({"RX_COLD_PART_MB": "2.5"}) == int(2.5 * (1 << 20)))
    check("0 is no cut", pb({"RX_COLD_PART_MB": "0"}) == 0)
    check("what is not a size stops the build", all(stops(lambda v=v: pb({"RX_COLD_PART_MB": v})) for v in ("-1", "six", "1e9", "nan")))
    fl = ["-march=x86-64-v3", "-ffp-contract=off", "-Igen", "-O1", "-g0", "-mllvm", "-rotation-max-header-size=0", "-DA64_POLLING"]
    cold = cold_parts.cold_flags(fl, "O1", {})
    check("the flags: -O2 where the level was, the part size, nothing else",
          cold == [f if f != "-O1" else "-O2" for f in fl] + ["-DRX_COLD_PART_MB=6"] and fl.count("-O1") == 1)
    check("the part size is in the flags", cold_parts.cold_flags(fl, "O1", {"RX_COLD_PART_MB": "8"}) != cold)


def check_cut():
    preamble, fns = made_up_chunk(400, giant=90000)
    text = preamble + "".join(fns)
    budget = 60000
    parts = cold_parts.chunk_parts(text, budget, chunks.fn_cost)
    check("the chunk is cut", len(parts) > 5)
    check("every part has the chunk's declarations", all(p.startswith(preamble) for p in parts))
    bodies = [p[len(preamble):] for p in parts]
    check("the parts hold the chunk's functions once, in order", "".join(bodies) == "".join(fns))
    check("every part begins where a function begins", all(lifted_c.HEAD_NOTED.match(b) for b in bodies))
    check("a note stays with its function", not any(b.rstrip().endswith("*/") for b in bodies))
    for b in bodies:
        marks = [m.start() for m in lifted_c.HEAD_NOTED.finditer(b)] + [len(b)]
        cost = sum(chunks.fn_cost(y - x) for x, y in zip(marks, marks[1:]))
        check("no part is past the budget unless it is one function", cost <= budget or len(marks) == 2)
    giant = [b for b in bodies if len(b) > 80000]
    check("the giant function is a part by itself", len(giant) == 1 and len(lifted_c.HEAD_NOTED.findall(giant[0])) == 1)
    check("a chunk that fits is its own text", cold_parts.chunk_parts(text, 1 << 30, chunks.fn_cost) == [text])
    check("no cut at 0", cold_parts.chunk_parts(text, 0, chunks.fn_cost) == [text])
    one = preamble + fns[0]
    check("a chunk of one function is its own text", cold_parts.chunk_parts(one, 10, chunks.fn_cost) == [one])
    check("the key holds the size and the text", len({cold_parts.parts_key(text, budget), cold_parts.parts_key(text, budget + 1),
                                                       cold_parts.parts_key(text + " ", budget)}) == 3)
    return preamble, fns, text


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def check_files(tmp, preamble, fns, text):
    gen, split = os.path.join(tmp, "gen"), os.path.join(tmp, "build", "split")
    os.makedirs(gen)
    small_pre, small_fns = made_up_chunk(12)
    names = {"code_000.c": text, "code_001.c": small_pre + "".join(small_fns), "code_002_1.c": text.replace("f_8", "f_9"),
             "code_hot_0.c": text.replace("f_8", "f_a"), "a64_table.c": "int a64_table;\n"}
    for name, body in names.items():
        with open(os.path.join(gen, name), "w", encoding="utf-8", newline="") as f:
            f.write(body)
    srcs = [os.path.join(gen, n) for n in sorted(names)]
    listing = sorted(os.listdir(gen))

    # nothing asked: the same list, nothing cold, nothing written
    out, cold = cold_parts.expand(srcs, split, {})
    check("with RX_COLD_OPT unset the sources are the list given, with no cold file", out is srcs and cold == frozenset())
    check("with RX_COLD_OPT unset nothing is written", not os.path.exists(os.path.join(tmp, "build")))

    env = {"RX_COLD_OPT": "O2", "RX_COLD_PART_MB": "0.05"}   # (about 52 KB a part)
    stats = {}
    out, cold = cold_parts.expand(srcs, split, env, stats=stats)   # (fn_cost: chunks.fn_cost, found by expand itself)
    budget = cold_parts.part_bytes(env)
    check("the hot piece and the runtime's file stay in the list, with their flags", all(
        s in out and s not in cold for s in srcs if os.path.basename(s) in ("code_hot_0.c", "a64_table.c")))
    check("the chunks are replaced by their parts", not any(s in out for s in srcs if cold_parts.CHUNK.fullmatch(os.path.basename(s))))
    check("every part takes the cold flags, and nothing else does", cold == frozenset(s for s in out if os.path.dirname(s) == split))
    check("the order is the chunks' order, a chunk's parts together",
          [os.path.basename(s).split(".p")[0] for s in out if s in cold] == sorted(os.path.basename(s).split(".p")[0] for s in out if s in cold))
    check("three chunks written", stats == {"written": 3})
    for chunk in ("code_000.c", "code_001.c", "code_002_1.c"):
        mine = [s for s in out if os.path.basename(s).startswith(chunk[:-2] + ".p")]
        check("%s: its parts are named after it, in order" % chunk,
              [os.path.basename(s) for s in mine] == [cold_parts.part_name(chunk, i) for i in range(len(mine))])
        check("%s: its parts are the cut of its text" % chunk,
              [read(s) for s in mine] == cold_parts.chunk_parts(names[chunk], budget, chunks.fn_cost))
        key = read(os.path.join(split, chunk + ".key")).split()
        check("%s: the key file names the key and the parts" % chunk,
              key == [cold_parts.parts_key(names[chunk], budget)] + [os.path.basename(s) for s in mine])
    check("the small chunk is one part, its own text", [read(s) for s in out if "code_001.p" in s] == [names["code_001.c"]])
    check("the lift's files are as they were", sorted(os.listdir(gen)) == listing and all(
        read(os.path.join(gen, n)) == body for n, body in names.items()))

    # a second build: nothing written (every part given an old date first: a rewrite would change it)
    for s in cold:
        os.utime(s, (1000000000, 1000000000))
    stats = {}
    out2, cold2 = cold_parts.expand(srcs, split, env, stats=stats)
    check("a second build makes the same parts", out2 == out and cold2 == cold and stats == {"kept": 3})
    check("a second build writes no part", all(int(os.path.getmtime(s)) == 1000000000 for s in cold))

    # another size: cut again, the parts the new cut does not make removed
    before = len([s for s in out if "code_000.p" in s])
    stats = {}
    out3, cold3 = cold_parts.expand(srcs, split, dict(env, RX_COLD_PART_MB="0.2"), stats=stats)
    after = [s for s in out3 if "code_000.p" in s]
    check("another part size cuts the chunks again", stats == {"written": 3} and 1 < len(after) < before)
    check("the parts of the old cut are removed", sorted(f for f in os.listdir(split) if f.startswith("code_000.p")) ==
          sorted(os.path.basename(s) for s in after))
    check("the new parts hold the chunk once", "".join(read(s)[len(preamble):] for s in after) == "".join(fns))

    # a changed chunk, a part gone, a key gone: that chunk alone is cut again
    env = dict(env, RX_COLD_PART_MB="0.2")
    with open(os.path.join(gen, "code_001.c"), "a", encoding="utf-8", newline="") as f:
        f.write(function(0x80008000, 900))
    stats = {}
    cold_parts.expand(srcs, split, env, stats=stats)
    check("a changed chunk alone is cut again", stats == {"written": 1, "kept": 2})
    os.remove(after[1])
    stats = {}
    cold_parts.expand(srcs, split, env, stats=stats)
    check("a chunk with a part gone is cut again", stats == {"written": 1, "kept": 2} and os.path.isfile(after[1]))
    os.remove(os.path.join(split, "code_002_1.c.key"))
    stats = {}
    cold_parts.expand(srcs, split, env, stats=stats)
    check("a chunk with its key gone is cut again", stats == {"written": 1, "kept": 2})

    # a list of chunks, and no cut
    listed = os.path.join(tmp, "listed.txt")
    with open(listed, "w") as f:
        f.write("code_002_1.c\n")
    out4, cold4 = cold_parts.expand(srcs, split, dict(env, RX_COLD_OPT=listed))
    check("a list: only its chunks are replaced", {os.path.basename(s).split(".p")[0] for s in cold4} == {"code_002_1"} and
          os.path.join(gen, "code_000.c") in out4 and os.path.join(gen, "code_000.c") not in cold4)
    out5, cold5 = cold_parts.expand(srcs, split, {"RX_COLD_OPT": "O2", "RX_COLD_PART_MB": "0"})
    check("no cut at 0: the chunks themselves take the cold flags", out5 == srcs and cold5 == frozenset(
        s for s in srcs if cold_parts.CHUNK.fullmatch(os.path.basename(s))))
    return [s for s in after]


STAND_IN = """/* tests/test_chunk_parts.py: a stand-in for the guest model, enough for made-up functions */
#include <stdint.h>
typedef struct { uint64_t x[32]; } Ctx;
#define A64_NOESC
"""
MAIN = """#include <stdio.h>
#include "a64.h"
%(decls)s
static void (*const fns[])(Ctx *) = {%(names)s};
int main(void) {
    Ctx c;
    uint64_t sum = 0;
    for (unsigned k = 0; k < sizeof fns / sizeof fns[0]; k++) {
        for (int r = 0; r < 32; r++) c.x[r] = 0x9e3779b97f4a7c15ULL * (k + 1) + r;
        fns[k](&c);
        sum = sum * 31 + c.x[1];
        printf("%%u %%016llx\\n", k, (unsigned long long)c.x[1]);
    }
    printf("sum %%016llx\\n", (unsigned long long)sum);
    return 0;
}
"""


def check_compile(tmp, cc, preamble, fns, text):
    """The chunk whole and as parts, at -O2: the same results"""
    work = os.path.join(tmp, "cc")
    os.makedirs(work)
    with open(os.path.join(work, "a64.h"), "w", newline="\n") as f:
        f.write(STAND_IN)
    names = lifted_c.HEAD.findall(text)
    with open(os.path.join(work, "main.c"), "w", newline="\n") as f:
        f.write(MAIN % {"decls": "".join("void %s(Ctx *);\n" % n for n in names), "names": ", ".join(names)})
    whole = os.path.join(work, "code_000.c")
    with open(whole, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    parts = cold_parts.write_parts(whole, os.path.join(work, "split"), 40000, chunks.fn_cost)
    check("the chunk to compile is cut", len(parts) > 3)
    import test_fpx_sticky as fs   # (the build helpers the lifted-code tests use: the target and linker flags)
    outs = []
    for label, srcs in (("whole", [whole]), ("parts", parts)):
        exe = os.path.join(work, label + ".exe")
        cmd = [cc] + fs.target_flags(cc, work) + ["-O2", "-g0", "-Wno-everything", "-I" + work, os.path.join(work, "main.c")] + srcs + ["-o", exe]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        check("the chunk compiles %s:\n%s" % (label, r.stdout[-2000:]), r.returncode == 0)
        outs.append(subprocess.run([exe], stdout=subprocess.PIPE, text=True, timeout=120).stdout)
    check("the parts compute what the whole chunk computes", outs[0] == outs[1] and outs[0].count("\n") == len(names) + 1)
    return len(names), len(parts)


def check_sources():
    with open(os.path.join(ROOT, "nx2", "build.py"), encoding="utf-8") as f:
        build = f.read()
    for line in ('    srcs, cold = (srcs, set()) if KEPT else cold_parts.expand(srcs, os.path.join(out, "split"), os.environ, stats=cold_stats)\n',
                 "    cold_fl = cold_parts.cold_flags(fl, a.opt, os.environ) if cold else fl",
                 '             hot_fl if os.path.basename(s).startswith("code_hot") else cold_fl if s in cold else\n'):
        check("nx2/build.py no longer has the line %r" % line.strip(), build.count(line) == 1)
    at = [build.find(p) for p in ("    srcs, cold = (srcs, set()) if KEPT else cold_parts.expand(","    srcs.sort(key=lambda s: -compile_cost(s, costs))",
                                  "    cold_fl = cold_parts.cold_flags(", "    jobs = [(cc, s, os.path.join(obj_dir,")]
    check("nx2/build.py expands its sources before it orders them and makes the jobs", min(at) >= 0 and at == sorted(at))
    with open(os.path.join(ROOT, "nx2", "make_game.py"), encoding="utf-8") as f:
        make_game = f.read()
    not_keyed = re.search(r"^LIFT_KEY_NOT = \((.*?)\)   #", make_game, re.S | re.M)
    check("nx2/make_game.py leaves nx2/cold_parts.py out of the lift key", bool(not_keyed) and '"cold_parts.py"' in not_keyed.group(1))
    for lift_file in ("lift.py", "split_hot.py", "chunks.py"):   # (the lift reads none of it)
        with open(os.path.join(ROOT, "nx2", lift_file), encoding="utf-8") as f:
            check("nx2/%s names cold_parts" % lift_file, "cold_parts" not in f.read())
    with open(os.path.join(ROOT, "docs", "development.md"), encoding="utf-8") as f:
        check("docs/development.md: RX_COLD_OPT and RX_COLD_PART_MB are not in the switches table",
              "| `RX_COLD_OPT=O2` or `=<file>`, `RX_COLD_PART_MB=<n>` |" in f.read())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cc")
    a = p.parse_args()
    check_sources()
    with tempfile.TemporaryDirectory(prefix="triforce-chunk-parts-") as tmp:
        check_rules(tmp)
        preamble, fns, text = check_cut()
        check_files(tmp, preamble, fns, text)
        cc = shutil.which(a.cc) if a.cc else shutil.which("clang")
        if not cc:
            print("PASS: the rules, the cut and the key files (the compile skipped: no clang)")
            return
        n, parts = check_compile(tmp, cc, preamble, fns, text)
    print("PASS: the rules, the cut and the key files; %d made-up functions compute the same whole and in %d parts at -O2" % (n, parts))


if __name__ == "__main__":
    main()
