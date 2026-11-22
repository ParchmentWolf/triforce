"""The hot pieces stay where they were from one lift to the next, and each declares only what it uses
(nx2/split_hot.py), on a made-up code_hot.c (game-free).

(Triforce, 11-22, the performance audit's LIFT-30, after Source A's.) Every split dealt the hot functions out afresh by
their sizes and gave every piece code_hot.c's whole preamble, so an update that touched a few hot functions could change
most of the eight pieces, the longest files of the build. Now <work>/image/hot_pieces.txt keeps each function's piece,
and a piece keeps a declaration only if it uses the name.

  - A64_HOT_STICKY=0: the pieces are v0.6.0's byte for byte (their digest here was taken with v0.6.0's nx2/split_hot.py
    on the same made-up file), and hot_pieces.txt is neither written nor read.
  - With no hot_pieces.txt every function lands in the piece v0.6.0 put it in; the file is then written.
  - A piece's preamble is the whole one without the declarations it does not use: the lines that are not declarations
    stay in every piece, every f_ and hos_ name a piece uses is still declared in it, and no declaration of a name it
    does not use is left. Lines that read like declarations but are code stay too: a call inside an inline helper, a
    macro's continued line, a declaration whose attribute is on the line before. With clang, every piece compiles
    (-fsyntax-only, an undeclared name an error).
  - With clang, after the changes below (a grown function, a new declaration, two new functions): the whole code_hot.c
    and its eight sticky pieces, each built at -O2 with a driver and stand-ins for the hos_ names and the functions
    outside the hot list, run every hot function from the same 100 random register states (edge values among them);
    every register after every run must be the same. Leaving the helper's call out of the pieces that do not name it
    (as a first draft of the rule did) fails here and above.
  - One hot function grown by forty lines: exactly one piece changes.
  - One hot function given a call of a function no hot one named before (so the lift adds a declaration): exactly one
    piece changes. With A64_HOT_STICKY=0 the same change rewrites every piece: what this is for.
  - A new hot function goes to the piece it shares the most calls with; one that calls nothing hot, to the cheapest.
  - A function that left the hot list leaves its piece alone; the others stay.
  - When keeping the pieces would make the costliest more than 1.15 times a fresh split's, the split is the fresh one;
    so it is when hot_pieces.txt was made for another number of pieces, or is not what the splitter writes.
  - hot_pieces.txt lies in <work>/image for a gen folder <work>/sa/gen or <work>/gen, and is not in the lift key.

    python -I -B tests/test_sticky_hot_pieces.py [--cc clang]
"""
import argparse
import contextlib
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import kit  # noqa: E402,F401  (a64-kit on the path)
import chunks  # noqa: E402
import split_hot  # noqa: E402

RUN_ALL_ARGS = ["--cc", "clang"]
PIECES = 8
# (the eight pieces and their costs with A64_HOT_STICKY=0, as v0.6.0's nx2/split_hot.py made them from made_up()'s file)
V060_DIGEST = "3dae331a1bea79fd38c6b9b4ef71f9f89e0215e7"
# (lines of the preamble that every piece keeps. The last ones read like declarations but are code: a call inside an inline
# helper, a macro's continued line, a declaration whose attribute is on the line before. Leaving one out of a piece changes
# what the helper does there, or what the macro or the attribute takes in)
FIXED = ('#include "a64.h"\n'
         "__attribute__((returns_twice)) int recomp_sj_setjmp(void **slot);\n"
         "#define MADE_UP_SCALE(c) ((c)->x[9] = hos_fixed_scale_bits)\n"
         "extern void hos_probe_note(Ctx *c, uint64_t v);\n"
         "static inline void made_up_probe(Ctx *c) {\n"
         "    c->x[10] += 5;\n"
         "    hos_probe_note(c, c->x[10]);\n"
         "}\n"
         "#define MADE_UP_LATE_DECL \\\n"
         "    void hos_probe_late(Ctx *c);\n"
         "__attribute__((cold))\n"
         "void hos_probe_cold(void);\n")
HOS = ("extern volatile int hos_fixed_resolution;\n", "extern volatile uint32_t hos_fixed_scale_bits;\n",
       "extern void hos_oot_menu_tick(Ctx *c, uint64_t screen);\n", "uint64_t hos_mods_table_size(uint64_t size, uint64_t path);\n",
       "extern volatile float hos_text_scale;\n")


def check(what, ok):
    if not ok:
        raise SystemExit("FAIL: sticky hot pieces: " + what)


def function(name, lines, calls=(), extra=""):
    body = "".join("c->x[%d] = c->x[%d] + %d;\n" % (1 + k % 7, 2 + k % 5, k) for k in range(lines))
    return "void %s(Ctx *__restrict A64_NOESC c) {\n" % name + body + extra + "".join("%s(c);\n" % t for t in calls) + "}\n"


def made_up():
    """{name: (lines, calls, extra)}: 240 hot functions of many sizes that call each other and functions outside"""
    fns = {}
    names = ["f_%08x" % (0x80100000 + 0x40 * i) for i in range(240)]
    for i, n in enumerate(names):
        lines = 40 + (i * 37) % 260 + (2600 if i % 53 == 7 else 0)
        calls = []
        if i % 3 == 0 and i + 1 < len(names):
            calls.append(names[i + 1])
        if i % 5 == 0:
            calls.append(names[(i * 7 + 3) % len(names)])
        if i % 11 == 0:
            calls.append("f_%08x" % (0x90000000 + 0x100 * (i % 13)))   # (not hot: declared, defined elsewhere)
        extra = ""
        if i == 10:
            extra = "if (hos_fixed_resolution) c->x[8] &= ~0x18ULL;\n"
        if i == 77:
            extra = "hos_oot_menu_tick(c, c->x[19]);\nMADE_UP_SCALE(c);\n"
        if i == 150:
            extra = "c->x[0] = hos_mods_table_size(c->x[0], c->x[1]);\n"
        if i % 17 == 4:
            extra += "made_up_probe(c);\n"
        fns[n] = (lines, tuple(c for c in calls if c != n), extra)
    return fns


def hot_text(fns):
    """code_hot.c as the lift and the patches write it: the fixed lines, the hos_ declarations, the declaration of every
    function a hot one names, then the functions in address order"""
    named = sorted({c for _, calls, _ in fns.values() for c in calls})
    preamble = FIXED + "".join(HOS) + "".join("void %s(Ctx *A64_NOESC);\n" % n for n in named)
    return preamble, preamble + "".join(function(n, *fns[n]) for n in sorted(fns))


def split(work, fns, sticky=True, pieces=PIECES):
    """One lift's split of the made-up file: {piece file name: text}, and what the splitter said"""
    gen = os.path.join(work, "sa", "gen")
    os.makedirs(gen, exist_ok=True)
    for old in os.listdir(gen):
        if old.startswith("code_hot"):
            os.remove(os.path.join(gen, old))
    with open(os.path.join(gen, "code_hot.c"), "w", encoding="utf-8", newline="") as f:
        f.write(hot_text(fns)[1])
    if sticky:
        os.environ.pop("A64_HOT_STICKY", None)
    else:
        os.environ["A64_HOT_STICKY"] = "0"
    said = io.StringIO()
    try:
        with contextlib.redirect_stdout(said):
            split_hot.split(gen, pieces)
    finally:
        os.environ.pop("A64_HOT_STICKY", None)
    out = {}
    for name in sorted(os.listdir(gen)):
        if name.startswith("code_hot_") and name.endswith(".c"):
            with open(os.path.join(gen, name), encoding="utf-8", newline="") as f:
                out[name] = f.read()
    with open(os.path.join(gen, chunks.COSTS), encoding="utf-8") as f:
        costs = f.read()
    return out, said.getvalue(), costs


def where(pieces):
    """{function: piece file} of a split"""
    return {m: name for name, text in pieces.items() for m in split_hot.HEAD.findall(text)}


def changed(a, b):
    return sorted(n for n in set(a) | set(b) if a.get(n) != b.get(n))


def digest(pieces, costs):
    h = hashlib.sha1(usedforsecurity=False)
    for name in sorted(pieces):
        h.update(name.encode() + bytes(1) + pieces[name].encode() + bytes(1))
    h.update(costs.encode())
    return h.hexdigest()


def body_of(text):
    marks = list(split_hot.HEAD.finditer(text))
    return text[:marks[0].start()] if marks else text, text[marks[0].start():] if marks else ""


STATES = 100   # (random register states a function, in run_both)
A64_H = "#include <stdint.h>\ntypedef struct { uint64_t x[32]; } Ctx;\n#define A64_NOESC\n"


def driver(fns):
    """The C that runs every hot function from the same random states and writes each state's registers after it: the hos_
    names and the functions outside the hot list as stand-ins that leave a mark in the registers"""
    outside = sorted({c for _, calls, _ in fns.values() for c in calls} - set(fns))
    hot = sorted(fns)
    return "".join([
        "#include <stdio.h>\n#include <stdint.h>\n#include <stdlib.h>\n#include \"a64.h\"\n",
        "volatile int hos_fixed_resolution;\nvolatile uint32_t hos_fixed_scale_bits;\nvolatile float hos_text_scale;\n",
        "void hos_oot_menu_tick(Ctx *c, uint64_t screen) { c->x[3] ^= screen * 0x9E3779B97F4A7C15ull; c->x[4] += 1; }\n",
        "uint64_t hos_mods_table_size(uint64_t size, uint64_t path) { return size * 0x100000001b3ull ^ (path << 40) ^ 0xabcdef12345ull; }\n",
        "void hos_probe_note(Ctx *c, uint64_t v) { c->x[11] = c->x[11] * 0x5851F42D4C957F2Dull + v + 1; }\n",
        "".join("void %s(Ctx *c) { c->x[5] = c->x[5] * 6364136223846793005ull + 0x%sull; c->x[6] ^= c->x[5] >> 17; }\n"
                % (n, n[2:]) for n in outside),
        "".join("void %s(Ctx *c);\n" % n for n in hot),
        "static void (*const hot[])(Ctx *) = {%s};\n" % ", ".join(hot),
        "static uint64_t seed = 0x2545F4914F6CDD1Dull;\n"
        "static uint64_t next(void) { uint64_t z = (seed += 0x9E3779B97F4A7C15ull);\n"
        "    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull; z = (z ^ (z >> 27)) * 0x94D049BB133111EBull; return z ^ (z >> 31); }\n"
        "static const uint64_t edge[] = {0, 1, ~0ull, 1ull << 63, (1ull << 63) - 1, 0xffffffffull, 1ull << 32, 0x18};\n"
        "int main(int argc, char **argv) {\n"
        "    FILE *out = fopen(argv[1], \"wb\");\n"
        "    if (!out) return 2;\n"
        "    for (unsigned f = 0; f < sizeof hot / sizeof hot[0]; f++)\n"
        "        for (int s = 0; s < %d; s++) {\n" % STATES,
        "            Ctx c;\n"
        "            for (int r = 0; r < 32; r++) { uint64_t v = next(); c.x[r] = (v & 3) == 0 ? edge[(v >> 2) & 7] : next(); }\n"
        "            hos_fixed_resolution = (int)(next() & 1);\n"
        "            hos_fixed_scale_bits = (uint32_t)next();\n"
        "            hot[f](&c);\n"
        "            if (fwrite(c.x, sizeof c.x, 1, out) != 1) return 3;\n"
        "        }\n"
        "    return fclose(out) != 0;\n"
        "}\n"])


def run_both(tmp, cc, gen, fns, label):
    """The hot functions built from the whole code_hot.c and built from its pieces, each run from the same random states:
    every register after every run must be the same. Returns how many runs were compared"""
    root = os.path.join(tmp, "run-" + label)
    os.makedirs(root)
    with open(os.path.join(root, "a64.h"), "w", newline="\n") as f:
        f.write(A64_H)
    with open(os.path.join(root, "driver.c"), "w", newline="\n") as f:
        f.write(driver(fns))
    shutil.copyfile(os.path.join(gen, "code_hot.c.whole"), os.path.join(root, "code_hot.c"))
    pieces = sorted(os.path.join(gen, n) for n in os.listdir(gen) if chunks.HOT_PIECE.fullmatch(n))
    dumps = []
    for kind, srcs in (("whole", [os.path.join(root, "code_hot.c")]), ("pieces", pieces)):
        exe = os.path.join(root, kind + ".exe")
        r = subprocess.run([cc, "-O2", "-fno-strict-aliasing", "-Werror=implicit-function-declaration", "-I" + root] + srcs
                           + [os.path.join(root, "driver.c"), "-o", exe], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        check("%s: the %s build compiles:\n%s" % (label, kind, r.stdout[-1500:]), r.returncode == 0)
        dump = os.path.join(root, kind + ".bin")
        check("%s: the %s build runs" % (label, kind), subprocess.run([exe, dump]).returncode == 0)
        with open(dump, "rb") as f:
            dumps.append(f.read())
    runs = len(fns) * STATES
    check("%s: %d runs written by each build" % (label, runs), len(dumps[0]) == len(dumps[1]) == runs * 32 * 8)
    if dumps[0] != dumps[1]:
        at = next(i for i in range(len(dumps[0])) if dumps[0][i] != dumps[1][i]) // 8
        check("%s: the pieces compute what the whole file computes: first difference in %s, state %d, x%d"
              % (label, sorted(fns)[at // 32 // STATES], at // 32 % STATES, at % 32), False)
    return runs


def check_all(tmp, cc):
    fns = made_up()
    preamble, whole = hot_text(fns)
    map_file = os.path.join(tmp, "w", "image", "hot_pieces.txt")
    work = os.path.join(tmp, "w")
    check("the pieces file is <work>/image/hot_pieces.txt for <work>/sa/gen and for <work>/gen",
          split_hot.pieces_file(os.path.join(work, "sa", "gen")) == map_file == split_hot.pieces_file(os.path.join(work, "gen")))

    # A64_HOT_STICKY=0: v0.6.0's pieces, and no pieces file
    old, said, costs = split(work, fns, sticky=False)
    check("with A64_HOT_STICKY=0 there are eight pieces", sorted(old) == ["code_hot_%d.c" % i for i in range(PIECES)])
    check("with A64_HOT_STICKY=0 the pieces are v0.6.0's byte for byte (digest %s)" % digest(old, costs), digest(old, costs) == V060_DIGEST)
    check("with A64_HOT_STICKY=0 every piece has the whole preamble", all(t.startswith(preamble) for t in old.values()))
    check("with A64_HOT_STICKY=0 no pieces file is written", not os.path.exists(map_file) and "sticky" not in said and "fresh" not in said)
    check("the made-up file is big enough to mean something", all(len(split_hot.HEAD.findall(t)) > 5 for t in old.values()))

    # no pieces file: v0.6.0's piece for every function; the preamble cut to what each piece uses
    new, said, _ = split(work, fns)
    check("with no pieces file every function lands in v0.6.0's piece", where(new) == where(old) and "fresh (no pieces file)" in said)
    check("the pieces file is written", split_hot.read_pieces(map_file) == {f: int(n[len("code_hot_"):-2]) for f, n in where(new).items()})
    kept_lines = 0
    for name, text in new.items():
        head, body = body_of(text)
        check("%s holds its functions as before" % name, body == body_of(old[name])[1])
        lines, all_lines = head.splitlines(keepends=True), preamble.splitlines(keepends=True)
        it = iter(all_lines)
        check("%s: its preamble is the whole one with lines left out" % name, all(line in it for line in lines))
        check("%s: the lines that are not declarations stay" % name, head.startswith(FIXED))
        used = set(split_hot.NAME.findall(body)) | set(split_hot.NAME.findall(FIXED))
        declared = {n for line in lines[len(FIXED.splitlines()):] for n in split_hot.NAME.findall(line)}
        whole_declared = {n for line in all_lines[len(FIXED.splitlines()):] for n in split_hot.NAME.findall(line)}
        check("%s: every name it uses is still declared" % name, used & whole_declared <= declared)
        check("%s: no declaration of a name it does not use is left: %s" % (name, sorted(declared - used)[:4]), declared <= used)
        kept_lines += len(lines)
    check("the pieces declare less than the whole preamble eight times over", kept_lines < PIECES * len(preamble.splitlines()) // 2)
    check("the piece with the macro's name keeps the declaration the macro needs, as every piece does",
          all("hos_fixed_scale_bits;" in t for t in new.values()))
    check("hos_text_scale, which nothing uses, is declared nowhere", not any("hos_text_scale" in t for t in new.values()))
    if cc:   # (every piece is C that compiles: no declaration it needs was left out)
        inc = os.path.join(tmp, "inc")
        os.makedirs(inc)
        with open(os.path.join(inc, "a64.h"), "w", newline="\n") as f:
            f.write(A64_H)
        for name in new:
            r = subprocess.run([cc, "-fsyntax-only", "-Wno-everything", "-Werror=implicit-function-declaration", "-I" + inc,
                                os.path.join(work, "sa", "gen", name)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            check("%s compiles:\n%s" % (name, r.stdout[-1500:]), r.returncode == 0)

    # one function grown: one piece changes
    grown = dict(fns)
    victim = sorted(fns)[61]
    grown[victim] = (fns[victim][0] + 40,) + fns[victim][1:]
    after, said, _ = split(work, grown)
    check("a grown function changes exactly one piece (%s)" % changed(new, after), changed(new, after) == [where(new)[victim]] and "sticky (240 functions where they were, 0 new)" in said)

    # a new declaration, used by one function: one piece changes; with the switch at 0, all of them
    called = dict(grown)
    called[victim] = (grown[victim][0], grown[victim][1] + ("f_9000beef",), grown[victim][2])
    check("the call adds a declaration to code_hot.c's preamble", hot_text(called)[0] != hot_text(grown)[0])
    after2, _, _ = split(work, called)
    check("a declaration one function uses changes exactly one piece (%s)" % changed(after, after2), changed(after, after2) == [where(new)[victim]])
    plain_before, _, _ = split(os.path.join(tmp, "plain"), grown, sticky=False)
    plain_after, _, _ = split(os.path.join(tmp, "plain"), called, sticky=False)
    check("with A64_HOT_STICKY=0 the same declaration changes every piece", len(changed(plain_before, plain_after)) == PIECES)

    # new hot functions: beside what they call; else in the cheapest piece
    friend = sorted(fns)[200]
    more = dict(called)
    more["f_80200000"] = (30, (friend, friend), "")
    more["f_80200040"] = (30, (), "")
    cost = {n: sum(chunks.fn_cost(len(function(f, *called[f]))) for f in split_hot.HEAD.findall(t)) for n, t in after2.items()}
    cost[where(after2)[friend]] += chunks.fn_cost(len(function("f_80200000", *more["f_80200000"])))   # (placed first, by name)
    after3, said, _ = split(work, more)
    check("a new function goes to the piece it shares the most calls with", where(after3)["f_80200000"] == where(after2)[friend])
    check("a new function that calls nothing hot goes to the cheapest piece", where(after3)["f_80200040"] == min(cost, key=lambda n: (cost[n], n)))
    check("the others stay", all(where(after3)[f] == p for f, p in where(after2).items()) and "sticky (240 functions where they were, 2 new)" in said)
    check("two new functions change two pieces at most", len(changed(after2, after3)) <= 2)
    runs = run_both(tmp, cc, os.path.join(work, "sa", "gen"), more, "sticky") if cc else 0

    # a function that left the hot list
    fewer = dict(more)
    gone = sorted(fns)[5]
    del fewer[gone]
    after4, _, _ = split(work, fewer)
    check("a function that left the hot list changes its piece and its callers' alone",
          all(where(after4)[f] == p for f, p in where(after3).items() if f != gone) and where(after3)[gone] in changed(after3, after4))

    # past the slack: the fresh split
    huge = dict(fewer)
    for k in range(6):
        huge["f_8030%04x" % (0x40 * k)] = (9000, (friend,), "")
    after5, said, _ = split(work, huge)
    fresh, _, _ = split(os.path.join(tmp, "fresh"), huge)
    check("past %.2f times a fresh split's costliest piece the split is the fresh one: %s" % (split_hot.STICKY_SLACK, said.splitlines()[0]),
          "fresh (kept where they were, the costliest piece is" in said and where(after5) == where(fresh))
    check("the pieces file follows the fresh split", split_hot.read_pieces(map_file) == {f: int(n[len("code_hot_"):-2]) for f, n in where(after5).items()})
    again, said, _ = split(work, huge)
    check("the next split keeps the fresh one's pieces", again == after5 and "sticky (" in said)

    # another number of pieces, or a file that is not the splitter's
    four, said, _ = split(work, huge, pieces=4)
    four_fresh, _, _ = split(os.path.join(tmp, "four"), huge, pieces=4)
    check("a pieces file for another number of pieces is not kept to", "another number of pieces" in said and where(four) == where(four_fresh))
    with open(map_file, "w") as f:
        f.write("not a pieces file\n")
    check("a file that is not the splitter's reads as none", split_hot.read_pieces(map_file) == {})
    junk, said, _ = split(work, huge, pieces=4)
    check("and the split is the fresh one", "fresh (no pieces file)" in said and where(junk) == where(four_fresh))

    # the rule by itself: the slack is measured against the fresh split
    bodies = {n: function(n, *more[n]) for n in more}
    edges = split_hot.call_edges(bodies)
    fresh_bins, _ = split_hot.fresh_split(bodies, PIECES, edges)
    one_piece = {n: 0 for n in bodies}
    bins, why = split_hot.sticky_split(bodies, PIECES, one_piece, edges, fresh_bins)
    check("everything in one piece is past the slack", bins is fresh_bins and why.startswith("fresh (kept where they were"))
    check("no pieces file, the fresh split", split_hot.sticky_split(bodies, PIECES, {}, edges, fresh_bins)[0] is fresh_bins)
    check("STICKY_SLACK is 1.15", split_hot.STICKY_SLACK == 1.15)
    return len(fns), runs


def check_sources():
    with open(os.path.join(ROOT, "nx2", "make_game.py"), encoding="utf-8") as f:
        make_game = f.read()
    check("nx2/make_game.py names hot_pieces.txt (it must stay out of the lift key: any map gives the same functions)",
          "hot_pieces.txt" not in make_game)
    check("nx2/make_game.py's lift_key no longer takes the A64_ variables: A64_HOT_STICKY is not in the key",
          'if k.startswith(("A64_", "OOT_", "RX_"))' in make_game)
    with open(os.path.join(ROOT, "nx2", "split_hot.py"), encoding="utf-8") as f:
        src = f.read()
    for line in ('    return os.environ.get("A64_HOT_STICKY", "1").strip() != "0"\n',
                 "        bins, how = sticky_split(bodies, pieces, read_pieces(pieces_file(gen)), edges, bins)\n",
                 "        head = piece_preamble(preamble, {n for name in names for n in NAME.findall(bodies[name])}) if keep else preamble\n"):
        check("nx2/split_hot.py no longer has the line %r" % line.strip(), src.count(line) == 1)
    with open(os.path.join(ROOT, "docs", "development.md"), encoding="utf-8") as f:
        check("docs/development.md: A64_HOT_STICKY is not in the switches table", "| `A64_HOT_STICKY=0` |" in f.read())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cc")
    a = p.parse_args()
    check_sources()
    cc = shutil.which(a.cc) if a.cc else shutil.which("clang")
    with tempfile.TemporaryDirectory(prefix="triforce-sticky-hot-") as tmp:
        n, runs = check_all(tmp, cc)
    print("PASS: %d made-up hot functions: v0.6.0's pieces with A64_HOT_STICKY=0 and with no pieces file; one piece changes for a "
          "grown function or a new declaration; new functions beside their callees; the fresh split past the slack; %s"
          % (n, "the sticky pieces and the whole file built and run from the same %d random states, every register the same" % runs
             if cc else "the compile skipped: no clang"))


if __name__ == "__main__":
    main()
