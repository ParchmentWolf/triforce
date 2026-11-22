"""(Triforce, 11-22, the performance audit's LIFT-17, after Source A's) An opt-in -O2 for every lifted chunk, each cut
into parts of a few MB for the compile.

The build compiles the hot pieces (code_hot_*.c) at -O2 with the play profile and every other lifted chunk (code_NNN.c,
code_NNN_M.c) at -O1. RX_COLD_OPT asks for -O2 on those too:

    RX_COLD_OPT=O2        every lifted chunk but the hot pieces at -O2
    RX_COLD_OPT=<file>    only the chunks the file lists, one file name a line (code_012.c; # starts a comment)
    unset, empty, O1      as before: nothing here runs

-O2's time grows with the square of a function's size and its passes look across a whole file, so each -O2 chunk is
compiled as parts: RX_COLD_PART_MB (6 when unset; 0: no cut) is a part's size by the lift's own estimate
(nx2/chunks.py fn_cost). A part is the chunk's declarations and a run of its functions, cut only where a function
begins; the parts together hold the chunk's functions once, in order. They are written under <build>/split as
code_NNN.p0.c, code_NNN.p1.c ..., with a key file a chunk (the chunk's text and the part size): a build that finds
the key and the parts as it wrote them writes nothing. The chunk itself, the lift's file, is not touched, so nothing
of the lift or its key changes.

Source A's figures: +4.4% and +5.5% fps on two PCs where the game's update bounds the frame, for a lifted compile of
about twice the processor time (and 23 minutes against 5 without the cut); this build's hot list already runs most of
the lifted time at -O2. Opt-in for that cost. Inlining sees one part at a time.

This file is not part of the lift key (nx2/make_game.py LIFT_KEY_NOT): the lift reads none of it. nx2/build.py is the
one caller; tests/test_chunk_parts.py runs the rules on made-up chunks."""
import hashlib
import os
import re

import lifted_c

CHUNK = re.compile(r"code_\d{3}(?:_\d+)?\.c")   # (a lifted chunk or a part of one the lift cut: never code_hot*.c)
PART_MB_DEFAULT = 6
CUT_VERSION = "cold_parts 1"   # (in every key: a change to how chunk_parts cuts writes the parts again)


def cold_level(env):
    """What RX_COLD_OPT asks: None (nothing), "all", or the set of chunk file names its file lists"""
    v = (env.get("RX_COLD_OPT") or "").strip()
    if v in ("", "O1"):
        return None
    if v == "O2":
        return "all"
    if not os.path.isfile(v):   # (a level this does not know, or a list that is not there: not taken for "nothing")
        raise SystemExit("build: RX_COLD_OPT=%s: not O2, O1 or a file that lists chunks" % v)
    with open(v, encoding="utf-8") as f:
        names = {line.split("#", 1)[0].strip() for line in f}
    names.discard("")
    bad = sorted(n for n in names if not CHUNK.fullmatch(n))
    if bad:
        raise SystemExit("build: RX_COLD_OPT=%s: not a lifted chunk's file name: %s" % (v, ", ".join(bad[:5])))
    return frozenset(names)


def chunk_opt_o2(name, level):
    """Whether the lifted file `name` is compiled at -O2 under that level: a chunk it covers, never a hot piece"""
    if level is None or not CHUNK.fullmatch(name):
        return False
    return level == "all" or name in level


def part_bytes(env):
    """A part's size in bytes of estimated cost, from RX_COLD_PART_MB (6 when unset or empty); 0: no cut"""
    v = (env.get("RX_COLD_PART_MB") or "").strip()
    try:
        mb = float(v) if v else float(PART_MB_DEFAULT)
    except ValueError:
        mb = -1.0
    if not 0 <= mb <= 1024:
        raise SystemExit("build: RX_COLD_PART_MB=%s: not a size in MB (0: no cut)" % v)
    return int(mb * (1 << 20))


def cold_flags(fl, opt, env):
    """The chunks' flags for a -O2 chunk: -O2 where the level was, and the part size (so it is in every object's key)"""
    return ["-O2" if f == "-" + opt else f for f in fl] + ["-DRX_COLD_PART_MB=%d" % (part_bytes(env) >> 20)]


def chunk_parts(text, budget, fn_cost):
    """A chunk's text as parts of about `budget` cost each (fn_cost of each function's size): the text before the first
    function in every part, then a run of whole functions. A function dearer than the budget is a part by itself. One
    part, the text itself, when the chunk fits the budget, has no two functions, or budget is 0"""
    marks = [m.start() for m in lifted_c.HEAD_NOTED.finditer(text)]
    if budget <= 0 or len(marks) < 2:
        return [text]
    ends = marks[1:] + [len(text)]
    cuts, run = [0], 0   # (indexes into marks where a part starts)
    for i, (a, b) in enumerate(zip(marks, ends)):
        cost = fn_cost(b - a)
        if i > cuts[-1] and run + cost > budget:
            cuts.append(i)
            run = 0
        run += cost
    if len(cuts) == 1:
        return [text]
    preamble = text[:marks[0]]
    bounds = [marks[i] for i in cuts] + [len(text)]
    return [preamble + text[a:b] for a, b in zip(bounds, bounds[1:])]


def parts_key(text, budget):
    """What a chunk's parts depend on: its text, the part size, and how this file cuts"""
    return hashlib.sha1(("%s %d\n" % (CUT_VERSION, budget)).encode() + text.encode("utf-8"), usedforsecurity=False).hexdigest()


def part_name(chunk_name, i):
    return "%s.p%d.c" % (chunk_name[:-2], i)


def write_parts(src, split_dir, budget, fn_cost, stats=None):
    """The parts of the chunk file `src` under split_dir, written unless its key file says these are they: their paths, in
    order. Parts an earlier cut of this chunk left and this one does not make are removed. stats: counts "written" and
    "kept" chunks, for the build's log and the test"""
    name = os.path.basename(src)
    with open(src, encoding="utf-8", newline="") as f:
        text = f.read()
    key = parts_key(text, budget)
    key_path = os.path.join(split_dir, name + ".key")
    try:
        with open(key_path, encoding="utf-8") as f:
            had = f.read().split()
    except OSError:
        had = []
    if had[:1] == [key] and len(had) > 1 and all(os.path.isfile(os.path.join(split_dir, p)) for p in had[1:]):
        if stats is not None:
            stats["kept"] = stats.get("kept", 0) + 1
        return [os.path.join(split_dir, p) for p in had[1:]]
    os.makedirs(split_dir, exist_ok=True)
    if os.path.exists(key_path):   # (first: a build stopped while it writes leaves no key that vouches for half the parts)
        os.remove(key_path)
    parts = chunk_parts(text, budget, fn_cost)
    names = [part_name(name, i) for i in range(len(parts))]
    for part, piece in zip(names, parts):
        with open(os.path.join(split_dir, part), "w", encoding="utf-8", newline="") as f:
            f.write(piece)
    stale = re.compile(re.escape(name[:-2]) + r"\.p\d+\.c")
    for old in os.listdir(split_dir):
        if stale.fullmatch(old) and old not in names:
            os.remove(os.path.join(split_dir, old))
    with open(key_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(key + "\n" + "".join(n + "\n" for n in names))
    if stats is not None:
        stats["written"] = stats.get("written", 0) + 1
    return [os.path.join(split_dir, n) for n in names]


def expand(srcs, split_dir, env, fn_cost=None, stats=None):
    """The build's sources with each -O2 chunk replaced by its parts, and the set of paths that take the -O2 flags (a
    chunk's parts, or the chunk itself with RX_COLD_PART_MB=0). With RX_COLD_OPT unset: (srcs as given, nothing)"""
    level = cold_level(env)
    if level is None:
        return srcs, frozenset()
    budget = part_bytes(env)
    if fn_cost is None:
        import chunks   # (the lift's own estimate; imported only here, when asked: the default build never loads the lifter)
        fn_cost = chunks.fn_cost
    out, cold = [], set()
    for s in srcs:
        if not chunk_opt_o2(os.path.basename(s), level):
            out.append(s)
            continue
        parts = [s] if budget <= 0 else write_parts(s, split_dir, budget, fn_cost, stats)
        out += parts
        cold.update(parts)
    return out, frozenset(cold)
