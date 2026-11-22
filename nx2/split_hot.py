"""code_hot.c in pieces that compile side by side: 83 MB in one file took 79 minutes on one core, and every full build waited for it.

    python -I nx2/split_hot.py [gen folder] [pieces, default 8]

Functions that call each other stay together, heaviest calls first, so what used to inline still can. The pieces cost about the
same to compile (chunks.fn_cost). code_hot.c stays as it was, renamed code_hot.c.whole, and build.py compiles code_hot_*.c at the
hot flags. A profile from the whole file fits the pieces: its counters go by function name and shape.

(Triforce, 11-22, the performance audit's LIFT-30, after Source A's) The pieces are sticky, and each declares only what it
uses. Every split dealt the functions out afresh by their sizes, so a few more lines in one hot function could move
functions between most of the pieces, and every piece began with code_hot.c's whole preamble, so one new declaration
changed all of them: an update that touched a few hot functions compiled up to eight pieces of about ten MB again, the
longest files of the build. Now:
  - <work>/image/hot_pieces.txt keeps each hot function's piece. The next split leaves the functions it knows where they
    are and puts a new one in the piece it shares the most calls with, else in the cheapest; when that leaves the costliest
    piece more than STICKY_SLACK times a fresh split's costliest, or the file is not there, or it names more pieces than
    this split makes, the split is the fresh one, as before, and the file is written again from it;
  - a piece keeps a declaration of code_hot.c's preamble only if it uses the name: the lift's `void f_<address>(Ctx
    *A64_NOESC);` lines and the patches' one-line `hos_` declarations (a function's, or a variable's with extern), each a
    whole statement at the top level (declared()). Every other line of the preamble stays in every piece.
A64_HOT_STICKY=0 (at lift time; an A64_ name, in the lift key): the fresh split and the whole preamble, byte for byte as
before, and hot_pieces.txt is neither read nor written. The file is not in the lift key: any map gives the same functions.
tests/test_sticky_hot_pieces.py.
"""
import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (python -I leaves the script folder off)
import kit  # noqa: E402,F401  (a64-kit on the path, for chunks)
import chunks  # noqa: E402
import lifted_c  # noqa: E402

HEAD = lifted_c.HEAD
CALL = re.compile(r"\b(f_[0-9a-f]{8})\(c\)")


STICKY_SLACK = 1.15   # (how much dearer than a fresh split's the costliest sticky piece may be)
DECL = re.compile(r"void (f_[0-9a-f]+)\(Ctx \*A64_NOESC\);")   # (the lift's declaration of a function a hot one names)
# (a one-line declaration of a hos_ name, nx2/oot_patches.py's: a function's, extern or not, or a variable's with extern. A
# variable's without extern is a definition, and stays in every piece as before)
EXTERN = re.compile(r"(?P<ext>extern\s+)?(?:[A-Za-z_]\w*[\s*]+)+(?P<name>hos_\w+)\s*(?P<args>\([^;{}=#]*\))?\s*;")
NAME = re.compile(r"\b(?:f_[0-9a-f]+|hos_\w+)\b")
TOKEN = re.compile(r'/\*|\*/|//|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}()]')


def sticky():
    """Whether the pieces are sticky with their own declarations: unless A64_HOT_STICKY=0"""
    return os.environ.get("A64_HOT_STICKY", "1").strip() != "0"


def pieces_file(gen):
    """<work>/image/hot_pieces.txt for a gen folder (<work>/gen or <work>/sa/gen): beside chunks.txt, which a player's build keeps"""
    up = os.path.dirname(os.path.abspath(gen))
    work = os.path.dirname(up) if os.path.basename(up) == "sa" else up
    return os.path.join(work, "image", "hot_pieces.txt")


def call_edges(bodies):
    """How often each hot function calls each other one: {(caller, callee): calls}"""
    edges = collections.Counter()
    for f, b in bodies.items():
        for callee in CALL.findall(b):
            if callee in bodies and callee != f:
                edges[(f, callee)] += 1
    return edges


def fresh_split(bodies, pieces, edges):
    """The split from the sizes alone, as every split was: (the pieces' function names, the calls that stay in one group)"""
    # (groups joined along the calls: small callees first, those are what the optimiser inlines)
    limit = sum(len(b) for b in bodies.values()) * 1.1 / pieces
    parent = {f: f for f in bodies}
    size = {f: len(b) for f, b in bodies.items()}

    def root(f):
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f
    for (f, callee), n in sorted(edges.items(), key=lambda e: (len(bodies[e[0][1]]) / e[1], e[0])):
        a, b = root(f), root(callee)
        if a != b and size[a] + size[b] <= limit:
            parent[b] = a
            size[a] += size[b]

    groups = collections.defaultdict(list)
    for f in bodies:
        groups[root(f)].append(f)
    # (the groups dealt out by their compile cost, not their size: a piece's time goes with the square of its functions' sizes, and by
    # size one piece took 333 s and another 60)
    cost = {f: chunks.fn_cost(len(b)) for f, b in bodies.items()}
    bins = [[0, []] for _ in range(pieces)]
    for g in sorted(groups.values(), key=lambda g: (-sum(cost[f] for f in g), min(g))):
        b = min(bins, key=lambda x: x[0])
        b[0] += sum(cost[f] for f in g)
        b[1].extend(g)
    kept = sum(n for (f, c), n in edges.items() if root(f) == root(c))
    return [names for _, names in bins], kept


def read_pieces(path):
    """{function: piece} from hot_pieces.txt, or {} when it is not there or not what save_pieces writes"""
    try:
        with open(path, encoding="utf-8") as f:
            rows = [line.split() for line in f if line.strip()]
    except OSError:
        return {}
    if not all(len(r) == 2 and r[1].isdigit() for r in rows):
        return {}
    return {name: int(piece) for name, piece in rows}


def save_pieces(path, bins):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join("%s %d\n" % (name, i) for i, names in enumerate(bins) for name in sorted(names)))


def sticky_split(bodies, pieces, saved, edges, fresh):
    """The pieces with the functions `saved` knows left where they are: (the pieces' names, why), or (fresh, why) when
    there is nothing to keep or keeping it costs more than STICKY_SLACK times the fresh split's costliest piece"""
    if not saved:
        return fresh, "fresh (no pieces file)"
    if max(saved.values()) >= pieces:
        return fresh, "fresh (the pieces file is for another number of pieces)"   # (fewer: the slack below decides)
    cost = {f: chunks.fn_cost(len(b)) for f, b in bodies.items()}
    bins = [[] for _ in range(pieces)]
    where = {}
    for f in sorted(bodies):
        if f in saved:
            bins[saved[f]].append(f)
            where[f] = saved[f]
    if not where:
        return fresh, "fresh (none of the pieces file's functions is hot now)"
    known = len(where)
    load = [sum(cost[f] for f in names) for names in bins]
    calls = collections.defaultdict(collections.Counter)   # (each function's calls with every other, either way)
    for (f, callee), n in edges.items():
        calls[f][callee] += n
        calls[callee][f] += n
    for f in sorted(bodies):   # (a new one: beside the function it shares the most calls with, else in the cheapest piece)
        if f in where:
            continue
        shared = collections.Counter()
        for other, n in calls[f].items():
            if other in where:
                shared[where[other]] += n
        i = min(range(pieces), key=lambda i: (-shared[i], load[i], i))
        bins[i].append(f)
        where[f] = i
        load[i] += cost[f]
    fresh_top = max(sum(cost[f] for f in names) for names in fresh)
    if max(load) > STICKY_SLACK * fresh_top:
        return fresh, "fresh (kept where they were, the costliest piece is %.2f times a fresh split's)" % (max(load) / max(1, fresh_top))
    return bins, "sticky (%d functions where they were, %d new)" % (known, len(where) - known)


def declared(lines):
    """For each line of code_hot.c's preamble the name it declares when a piece may leave it out, else None. Only a whole
    statement at the top level is taken: not a line inside braces or parentheses, a comment, a macro's continued lines, or
    after an unfinished statement (an attribute on the line before), where a line that reads like a declaration is code"""
    out = []
    depth = paren = 0
    comment = cont = False
    done = True
    for line in lines:
        s = line.strip()
        name = None
        if depth == 0 and paren == 0 and not comment and not cont and done and not s.startswith(("typedef", "static")):
            m = DECL.fullmatch(s)
            e = None if m else EXTERN.fullmatch(s)
            name = m.group(1) if m else e.group("name") if e and (e.group("ext") or e.group("args")) else None
        out.append(name)
        directive = cont or s.startswith("#")
        cont = line.rstrip("\r\n").endswith("\\")
        code, pos = [], 0   # (the line without its comments, and the braces and parentheses it opens and closes)
        for t in TOKEN.finditer(line):
            g = t.group()
            if comment:
                if g == "*/":
                    comment, pos = False, t.end()
            elif g in ("//", "/*"):
                code.append(line[pos:t.start()])
                pos = len(line)
                if g == "//":
                    break
                comment = True
            elif g in ("{", "}", "(", ")") and not directive:
                depth += (g == "{") - (g == "}")
                paren += (g == "(") - (g == ")")
        if not comment:
            code.append(line[pos:])
        code = " ".join(code).strip()
        if not directive and code:
            done = code.endswith((";", "{", "}"))
    return out


def piece_preamble(preamble, names_used):
    """code_hot.c's preamble for one piece: a declaration of a function or of a hos_ name stays only if the piece uses the
    name (names_used: every f_ and hos_ word of its functions); every other line stays"""
    lines = preamble.splitlines(keepends=True)
    names = declared(lines)
    # (a name a line that always stays uses is used too: a macro or an inline helper the preamble may carry)
    used = set(names_used)
    for line, name in zip(lines, names):
        if name is None:
            used.update(NAME.findall(line))
    return "".join(line for line, name in zip(lines, names) if name is None or name in used)


def split(gen, pieces):
    path = os.path.join(gen, "code_hot.c")
    whole = path + ".whole"
    if os.path.exists(path):
        os.replace(path, whole)
    for old in glob.glob(os.path.join(glob.escape(gen), "code_hot_*.c")):
        os.remove(old)
    with open(whole, encoding="utf-8", newline="") as f:
        text = f.read()
    marks = list(lifted_c.definitions(text))   # ((Triforce, 11-22, the performance audit's IO-40) HEAD's matches, found by jumps)
    if not marks:
        raise SystemExit("split_hot: no functions in %s" % whole)
    preamble = text[:marks[0].start()]
    bodies = {m.group(1): text[m.start():(marks[i + 1].start() if i + 1 < len(marks) else len(text))] for i, m in enumerate(marks)}

    edges = call_edges(bodies)
    bins, kept = fresh_split(bodies, pieces, edges)
    keep = sticky()
    if keep:   # ((Triforce, LIFT-30) the functions the last split placed stay where they are)
        bins, how = sticky_split(bodies, pieces, read_pieces(pieces_file(gen)), edges, bins)
        where = {f: i for i, names in enumerate(bins) for f in names}
        kept = sum(n for (f, c), n in edges.items() if where[f] == where[c])
        save_pieces(pieces_file(gen), bins)
        print("split_hot: %s" % how)
    cost = {f: chunks.fn_cost(len(b)) for f, b in bodies.items()}
    costs = {}
    for i, names in enumerate(bins):
        c = sum(cost[f] for f in names)
        head = piece_preamble(preamble, {n for name in names for n in NAME.findall(bodies[name])}) if keep else preamble
        with open(os.path.join(gen, "code_hot_%d.c" % i), "w", encoding="utf-8", newline="") as f:
            f.write(head)
            for name in sorted(names):
                f.write(bodies[name])
        costs["code_hot_%d.c" % i] = len(head) + c
        print("split_hot: piece %d: %d functions, %d MB, cost %d MB" % (i, len(names), sum(len(bodies[f]) for f in names) >> 20, c >> 20))
    chunks.write_costs(gen, costs)
    print("split_hot: %d of %d calls stay in one %s" % (kept, sum(edges.values()), "piece" if keep else "group"))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    split(sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "work", "sa", "gen"), int(sys.argv[2]) if len(sys.argv) > 2 else 8)
