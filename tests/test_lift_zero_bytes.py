"""A translation with a zero byte is made again in the same build, once (nx2/make_game.py lifted_zero_bytes, lifted_before
and the lift's loop in main; no game).

The lift never writes a zero byte into its C. A player's build stopped in the compile with 17 translated files refused for one:
the PC's memory or drive changed them after they were written, their size and their end as they were, so the check by each
file's last two bytes (lifted_cut_short) let them through to the compile, where the build can only stop. Now the translation
this build made, and one kept from before with no record of the check, is looked through for zero bytes: found, the game is
translated again; found again, the build stops with how many files have one and what to check. A translation that passed
says so in its lift key's third line, "zero-checked", and is not read again.

This runs lifted_zero_bytes and lifted_before on a folder of its own, and reads the loop's source.

    python -I -B tests/test_lift_zero_bytes.py
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
NX2 = ROOT / "nx2"


def load():
    sys.path[:0] = [str(NX2)]
    spec = importlib.util.spec_from_file_location("triforce_make_game_zero", NX2 / "make_game.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiftZeroBytesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.make = load()

    def test_a_zero_byte_inside_a_whole_file_is_found(self):
        with tempfile.TemporaryDirectory(prefix="triforce-zero-") as gen:
            Path(gen, "code_000.c").write_bytes(b"int f(void) {\n    return 1;\n}\n")
            Path(gen, "code_001.c").write_bytes(b"int g(void) {\n    return \x002;\n}\n")
            Path(gen, "a64_table.c").write_bytes(b"\x00")   # (only the lifted code_*.c files are read)
            self.assertEqual(self.make.lifted_zero_bytes(gen), ["code_001.c"])
            self.assertEqual(self.make.lifted_cut_short(gen), [])   # (its end is as a function's: the old check passed it)
        self.assertEqual(self.make.lifted_zero_bytes(os.path.join(gen, "gone")), [])

    def test_the_lift_key_may_carry_the_record_of_the_check(self):
        with tempfile.TemporaryDirectory(prefix="triforce-zero-") as work:
            gen, image = Path(work, "sa", "gen"), Path(work, "sa", "image")
            gen.mkdir(parents=True)
            image.mkdir(parents=True)
            (gen / "code_000.c").write_bytes(b"x\n}\n")
            (gen / "a64_table.c").write_bytes(b"t\n")
            (image / "image.bin").write_bytes(b"i")
            with mock.patch.object(self.make, "gen_print", lambda g: "PRINT"):
                key = gen / self.make.LIFT_KEY
                key.write_text("KEY\nPRINT\n")
                self.assertTrue(self.make.lifted_before(work, "KEY"))
                key.write_text("KEY\nPRINT\nzero-checked\n")
                self.assertTrue(self.make.lifted_before(work, "KEY"))
                key.write_text("KEY\nPRINT\nsomething\n")
                self.assertFalse(self.make.lifted_before(work, "KEY"))
                key.write_text("OTHER\nPRINT\nzero-checked\n")
                self.assertFalse(self.make.lifted_before(work, "KEY"))

    def test_the_loop_translates_again_once_and_then_says_what_to_check(self):
        src = (NX2 / "make_game.py").read_text(encoding="utf-8")
        main = src[src.index("\ndef main(a=None):"):]
        loop = main[main.index("for _ in range(2):"):main.index('say("stage", "compile", "Compiling")')]
        self.assertIn("checked = False", loop[:200])
        self.assertIn('checked = f.read().split()[-1] == "zero-checked"', loop)
        self.assertIn("cut, zero = lifted_cut_short(gen_dir), [] if checked or compiled_kept else lifted_zero_bytes(gen_dir)", loop)
        at, i = [], 0
        for p in ('f.write("zero-checked\\n")', "break", "os.remove(key_file)", "translated files with a zero byte",
                  "came out damaged twice"):   # (in this order: the record and out, else the key gone, again, then the stop)
            i = loop.index(p, i)
            at.append(i)
        self.assertEqual(len(at), 5)
        # (the record goes after the key written for this translation, as its third line)
        self.assertLess(loop.index("write_lift_key(work, key)"), loop.index('f.write("zero-checked\\n")'))


if __name__ == "__main__":
    unittest.main()
