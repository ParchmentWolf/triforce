"""(Triforce) a64_lift.Lifter.walk, the discovery's walk of one function, with the same result in less time and memory.

The kit's walk stores each instruction of a function as body[pc] = (kind, word): for OoT, 17.6 million entries, most of them
plain ops of far fewer distinct words. Each was a tuple of its own, about a gigabyte of the lift's process after the discovery;
that process holds them through the emit, and on Windows the emit's processes are one per GB of available memory
(nx2/chunks.py emit_jobs), so that gigabyte could be a process fewer on a 16 GB PC. Here every plain op of the same word is
one shared (("op",), word) tuple (nx2/insn.py's classify answers a plain op the same at every pc), and the image's lookups
(nx2/image.py EdenImage's word view and code ranges) are read inline. Shared after the fact, the duplicates' memory would stay
with Python's allocator: it is done as the walk makes them.

Everything else is the kit's walk, line for line in its order: the same instructions visited in the same order, the same jump
tables found and the same labels. tests/test_walk.py compares the two over a made-up image, and pins KIT_WALK, the sha256 of
the kit's own walk's source: a change to the kit's walk fails it until this copy is compared with it again.
install() is run by nx2/lift.py at its module level (so the emit's and the discovery's processes have it too).
"""
import a64_lift

KIT_WALK = "edf0c833a9b45d28848867ca0e7e1e982707f67efb6827db7f89fd4748f6149a"   # (sha256 of a64_lift.Lifter.walk's source this copies)

_installed = False


def walk(self, entry):
    """a64_lift.Lifter.walk: (body {pc: (kind, word)}, labels) of the function at entry"""
    img, entries = self.img, self.entries
    classify = a64_lift.classify   # (nx2/insn.py's, installed before any walk)
    ops = self.__dict__.setdefault("_op_entries", {})   # (word -> the shared (("op",), word) entry; never sent: emit_pool NOT_SENT)
    spans = getattr(img, "_spans", None)
    words = getattr(img, "_words", None)
    if spans is not None and words is not None:
        base, size = img._base, len(img.mem)

        def in_code(a):
            if a & 3:
                return False
            for lo, hi in spans:
                if lo <= a < hi:
                    return True
            return False

        def word(a):   # (only asked after in_code: a is word aligned)
            off = a - base
            return words[off >> 2] if 0 <= off < size else img.word(a)
    else:
        in_code, word = img.in_code, img.word
    body, labels, todo = {}, set(), [entry]

    def visit(t):
        if t != entry and t in entries:
            return
        if in_code(t):
            labels.add(t)
            todo.append(t)

    while todo:
        pc = todo.pop()
        while pc not in body:
            if (pc != entry and pc in entries) or not in_code(pc):
                break
            w = word(pc)
            kw = ops.get(w)
            if kw is not None:   # (a word seen before as a plain op: one at every pc, nx2/insn.py classify)
                body[pc] = kw
                pc += 4
                continue
            k = classify(w, pc)
            kind = k[0]
            if kind == "op":
                kw = ops[w] = (k, w)
                body[pc] = kw
                pc += 4
                continue
            body[pc] = (k, w)
            if kind == "b":
                visit(k[1])
                break
            if kind in ("bcond", "cbz", "tbz"):
                visit(k[1])
            elif kind == "br":
                targets = self.jump_table(pc, k[1])
                if targets:
                    self.jt[pc] = targets
                    self.add_jt_edges(pc, targets)
                    for t in targets:
                        visit(t)
                break
            elif kind in ("ret", "trap"):
                break
            pc += 4
    return body, labels


def install():
    global _installed
    if _installed:
        return
    _installed = True
    a64_lift.Lifter.walk = walk
