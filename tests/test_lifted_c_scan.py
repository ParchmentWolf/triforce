"""The scans for the lifted functions' definitions give the patterns' own matches (nx2/lifted_c.py definitions,
noted_starts).

(Triforce, 11-22, the performance audit's IO-40, after Source A's.) nx2/build.py's memory estimate, nx2/chunks.py's
costs and cuts and nx2/split_hot.py's pieces found the definitions with finditer of a pattern that begins with ^, tried
at every line of 1.5 GB of C. definitions and noted_starts jump from one "\nvoid f_" to the next and try the pattern only
there. What they return decides where the lifted files are cut, so it must be the patterns' answer to the byte.
HOOKSHOT_LIFTED_C_REGEX=1 is the patterns' own finditer, as before.

Game-free, on made-up C:
  - on fixtures with \n and with \r\n line ends (notes above definitions, two notes in a row, a note that does not end
    its line, a definition at offset 0, a definition after a note at offset 0, near-miss signatures, text with nothing
    in it, text without a final line end) and on 300 fixtures made from a seed: definitions' matches are HEAD's (the
    spans and the names), for str and for bytes, and noted_starts is HEAD_NOTED's starts;
  - the three callers on a made-up lift, both ways: chunks.text_cost and chunks.split_one write the same parts with the
    same costs, split_hot.split writes the same pieces, build.py's mem_need gives the same number;
  - the switch is read from the environment and turns both into the patterns' finditer; the four callers ask the scans.

    python -I -B tests/test_lifted_c_scan.py
"""
import ast
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
NX2 = ROOT / "nx2"
sys.path.insert(0, str(NX2))
import lifted_c  # noqa: E402

DEF = "void f_%08x(Ctx *__restrict A64_NOESC c) {"
PIECES = [
    DEF % 0x80001000 + "\n  c->x[0] = 1;\n}\n",
    "/* f_80002000: 3 blocks */\n" + DEF % 0x80002000 + "\n}\n",
    "/* one */\n/* two */\n" + DEF % 0x80003000 + "\n  /* inside */\n}\n",
    "/* not closed\n" + DEF % 0x80004000 + "\n}\n",
    "/* closed */ and more\n" + DEF % 0x80005000 + "\n}\n",
    "/* a */ b */\n" + DEF % 0x80006000 + "\n}\n",
    "/**/\n" + DEF % 0x80007000 + "\n}\n",                          # (no space inside: not a note)
    "  " + DEF % 0x80008000 + "\n}\n",                              # (not at the line's start)
    "static " + DEF % 0x80009000 + "\n}\n",
    "void f_8000a000(Ctx *__restrict A64_NOESC c);\n",              # (a declaration)
    "void f_8000B000(Ctx *__restrict A64_NOESC c) {\n}\n",          # (not lower-case hex)
    "void f_(Ctx *__restrict A64_NOESC c) {\n}\n",
    "void f_8000c000(Ctx *restrict c) {\n}\n",
    "void g_8000d000(Ctx *__restrict A64_NOESC c) {\n}\n",
    "\n\n",
    "/* a note with nothing under it */\n\n",
    "/* x */\n" + DEF % 0x8000e000 + " /* same line */\n}\n" + DEF % 0x8000f000 + "\n}\n",
    "#include \"a64.h\"\nstatic int t;\n",
    "  f_80001000(c);\n  void f_x;\n",
]


def made(seed, crlf, final_newline=True):
    """A made-up file of the pieces above in a seeded order"""
    r = random.Random(seed)
    text = "".join(r.choice(PIECES) for _ in range(r.randrange(0, 40)))
    if not final_newline:
        text = text.rstrip("\n")
    return text.replace("\n", "\r\n") if crlf else text


def spans(matches):
    return [(m.start(), m.end(), m.group(1)) for m in matches]


class Scans(unittest.TestCase):
    def setUp(self):
        self.assertFalse(lifted_c.REGEX_SCAN)

    def same(self, text):
        self.assertEqual(spans(lifted_c.definitions(text)), spans(lifted_c.HEAD.finditer(text)))
        self.assertEqual(list(lifted_c.noted_starts(text)), [m.start() for m in lifted_c.HEAD_NOTED.finditer(text)])
        data = text.encode()
        self.assertEqual(spans(lifted_c.definitions(data)), spans(lifted_c.HEAD_BYTES.finditer(data)))
        self.assertEqual(spans(lifted_c.definitions(bytearray(data))), spans(lifted_c.HEAD_BYTES.finditer(data)))
        return len(list(lifted_c.definitions(text)))

    def test_fixtures(self):
        found = 0
        for piece in PIECES:
            for text in (piece, piece + piece, "".join(PIECES), "".join(reversed(PIECES)), piece.rstrip("\n"), "x" + piece):
                for crlf in (False, True):
                    found += self.same(text.replace("\n", "\r\n") if crlf else text)
        self.assertGreater(found, 100)
        for text in ("", "\n", "void f_", "\nvoid f_", DEF % 1, "\n" + DEF % 2, "/* n */\n" + DEF % 3, "\r\n" + DEF % 4,
                     "/* n */\r" + DEF % 5, "/* n */\r\n\r\n" + DEF % 6):
            self.same(text)
        # (the answers themselves, not only that the two agree)
        text = "/* note */\n" + DEF % 0x10 + "\n}\n" + DEF % 0x20 + "\n}\n/* a */\n/* b */\r\n" + DEF % 0x30 + "\n}\n"
        self.assertEqual([m.group(1) for m in lifted_c.definitions(text)], ["f_00000010", "f_00000020", "f_00000030"])
        self.assertEqual(list(lifted_c.noted_starts(text)), [0, text.index(DEF % 0x20), text.index("/* b */")])
        self.assertEqual([m.start() for m in lifted_c.definitions(text)], [text.index(DEF % n) for n in (0x10, 0x20, 0x30)])

    def test_seeded_files(self):
        found = 0
        for seed in range(300):
            found += self.same(made(seed, crlf=seed % 3 == 0, final_newline=seed % 5 != 0))
        self.assertGreater(found, 1000)

    def test_switch(self):
        text = "".join(PIECES)
        with mock.patch.object(lifted_c, "REGEX_SCAN", True), \
                mock.patch.object(lifted_c, "_NOTE", None):   # (the jumps' own pattern is not used at all then)
            self.assertEqual(spans(lifted_c.definitions(text)), spans(lifted_c.HEAD.finditer(text)))
            self.assertEqual(list(lifted_c.noted_starts(text)), [m.start() for m in lifted_c.HEAD_NOTED.finditer(text)])
            self.assertEqual(spans(lifted_c.definitions(text.encode())), spans(lifted_c.HEAD_BYTES.finditer(text.encode())))
        for value, want in ((None, "False"), ("0", "False"), ("1", "True")):
            env = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_LIFTED_C_REGEX"}
            if value is not None:
                env["HOOKSHOT_LIFTED_C_REGEX"] = value
            said = subprocess.run([sys.executable, "-I", "-B", "-c",
                                   "import sys; sys.path.insert(0, sys.argv[1]); import lifted_c; print(lifted_c.REGEX_SCAN)",
                                   str(NX2)], env=env, capture_output=True, text=True)
            self.assertEqual(said.stdout.strip(), want, said.stderr)


def lift_text(seed, functions):
    """A made-up lifted file: a preamble, then functions of mixed sizes that call each other, some with a note above"""
    r = random.Random(seed)
    names = ["f_%08x" % (0x80000000 + 0x40 * i) for i in range(functions)]
    out = ["#include \"a64.h\"\n/* a made-up lift */\n"]
    for i, name in enumerate(names):
        if r.random() < 0.6:
            out.append("/* %s: %d blocks */\n" % (name, r.randrange(1, 9)))
        body = "".join("  %s(c);\n" % r.choice(names) if r.random() < 0.3 else "  c->x[%d] += %d;\n" % (r.randrange(31), j)
                       for j in range(r.choice((2, 5, 40, 400))))
        out.append("void %s(Ctx *__restrict A64_NOESC c) {\n%s}\n" % (name, body))
    return "".join(out)


class Callers(unittest.TestCase):
    """What the scans decide, with the jumps and with the patterns' finditer: the same files and numbers"""

    def both(self, run):
        results = []
        for regex in (False, True):
            with tempfile.TemporaryDirectory(prefix="lifted-c-scan-") as tmp, mock.patch.object(lifted_c, "REGEX_SCAN", regex):
                results.append(run(Path(tmp)))
        self.assertEqual(results[0], results[1])
        return results[0]

    @staticmethod
    def files(folder):
        return {p.name: p.read_bytes() for p in sorted(folder.iterdir())}

    def test_chunks_costs_and_cuts(self):
        import kit  # noqa: F401  (a64-kit on the path, for chunks)
        import chunks
        text = lift_text(1, 220)

        def run(tmp):
            path = tmp / "code_007.c"
            path.write_bytes(text.encode())
            made_, costs, said = chunks.split_one(str(tmp), str(path), 40000)
            return chunks.text_cost(text), sorted(os.path.basename(p) for p in made_), costs, said, self.files(tmp)

        cost, parts, costs, said, files = self.both(run)
        self.assertGreater(len(parts), 2)   # (the file was cut)
        self.assertEqual(sum(data.count(b"\nvoid f_") for data in files.values()), 220)   # (every function, in one part each)

    def test_split_hot_pieces(self):
        import split_hot
        text = lift_text(2, 150)

        def run(tmp):
            (tmp / "code_hot.c").write_bytes(text.encode())
            with open(os.devnull, "w") as quiet, mock.patch.object(sys, "stdout", quiet):
                split_hot.split(str(tmp), 4)
            return self.files(tmp)

        files = self.both(run)
        pieces = [n for n in files if n.startswith("code_hot_")]
        self.assertEqual(len(pieces), 4)
        self.assertEqual(sum(files[n].count(b"\nvoid f_") for n in pieces), 150)

    def test_build_memory_estimate(self):
        source = (NX2 / "build.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "mem_need"]
        self.assertEqual(len(function), 1)
        scope = dict(os=os, lifted_c=lifted_c, GIANT_MB=1500, GIANT_BYTES=2000, COMPILER_MB=1500, giants_counted=lambda: True)
        exec(compile(ast.Module(body=function, type_ignores=[]), "build.py", "exec"), scope)
        text = lift_text(3, 120)

        def run(tmp):
            needs = []
            for name in ("code_003.c", "code_hot_1.c"):
                (tmp / name).write_bytes(text.encode())
                needs.append(scope["mem_need"](str(tmp / name)))
            return needs

        needs = self.both(run)
        self.assertTrue(all(n > 300 for n in needs), needs)

    def test_the_callers_ask_the_scans(self):
        for name, needle in (("build.py", "starts = [m.start() - 1 for m in lifted_c.definitions(text)] + [len(text)]"),
                             ("chunks.py", "marks = list(lifted_c.noted_starts(text)) + [len(text)]"),
                             ("chunks.py", "marks = list(lifted_c.noted_starts(text))   #"),
                             ("split_hot.py", "marks = list(lifted_c.definitions(text))")):
            text = (NX2 / name).read_text(encoding="utf-8")
            self.assertTrue(needle in text, "%s: %s" % (name, needle))
            self.assertIsNone(re.search(r"^[^#\n]*HEAD(_BYTES|_NOTED)?\.finditer\(", text, re.M), name)   # (outside a comment)
        docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
        rows = [line for line in docs.splitlines() if line.startswith("| `HOOKSHOT_LIFTED_C_REGEX=1` |")]
        self.assertEqual(len(rows), 1)
        self.assertTrue("IO-40" in rows[0])


if __name__ == "__main__":
    unittest.main()
