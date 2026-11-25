"""Translated files the PC changed are found, named and compiled again, unless HOOKSHOT_LIFT_RECHECK=0 (nx2/make_game.py
refused_lift, changed_lift, run's again, and the compile step in main; no game).

Players' builds stopped in the compile on one-character typos in the translated C, in other files at each try: a bit the
PC's memory changed. The translation is the same each time from the same inputs, so when every final compile failure is in a
translated file with a compiler error at a place, the game is translated again and compared: files that came out different
are named and compiled again in the same build; refused again, the build says to check the memory; the same, the compiler's
error stands. On by default: HOOKSHOT_LIFT_RECHECK=0 turns it off.

    python -I -B tests/test_damaged_translation.py
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NX2 = ROOT / "nx2"


def load():
    sys.path[:0] = [str(NX2)]
    spec = importlib.util.spec_from_file_location("triforce_make_game_damaged", NX2 / "make_game.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DamagedTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.make = load()

    def test_only_the_lifts_files_with_a_compiler_error_at_a_place(self):
        m = self.make
        self.assertTrue(m.COMPILE_ERROR.match(r"D:\w\sa\gen\code_020.c:12:5: error: unknown type name 'uint65_t'"))
        self.assertTrue(m.COMPILE_ERROR.match("/w/sa/gen/code_020.c:1:2: fatal error: x"))
        self.assertFalse(m.COMPILE_ERROR.match("clang: error: unable to execute command: Killed"))
        with tempfile.TemporaryDirectory(prefix="triforce-damaged-") as gen:
            Path(gen, "code_020.c").write_text("x")
            self.assertTrue(m.refused_lift(gen, ["code_020.c"], [True]))
            self.assertFalse(m.refused_lift(gen, ["code_020.c"], [False]))   # (out of memory: no place)
            self.assertFalse(m.refused_lift(gen, ["code_020.c", "vk_draw.cpp"], [True, True]))   # (a source of the repository)
            self.assertFalse(m.refused_lift(gen, [], []))

    def test_the_files_that_came_out_different(self):
        with tempfile.TemporaryDirectory(prefix="triforce-damaged-") as gen:
            Path(gen, "code_000.c").write_text("uint65_t a;\n}\n")
            Path(gen, "code_001.c").write_text("int b;\n}\n")
            Path(gen, "a64_table.h").write_text("t\n")

            def translate():
                Path(gen, "code_000.c").write_text("uint64_t a;\n}\n")

            names, of = self.make.changed_lift(gen, translate)
            self.assertEqual((names, of), (["code_000.c"], 3))
            self.assertEqual(self.make.changed_lift(gen, lambda: None), ([], 3))

    def test_a_failed_step_asks_again_before_it_fails_the_build(self):
        cmd = [sys.executable, "-I", "-c", "import sys; sys.exit(3)"]
        asked = []
        self.assertEqual(self.make.run(cmd, again=lambda: asked.append(1) or True, show=lambda line: None), 3)
        self.assertEqual(asked, [1])
        with self.assertRaises(SystemExit):
            self.make.run(cmd, again=lambda: False, show=lambda line: None)

    def test_the_compile_step_is_behind_its_switch(self):
        src = (NX2 / "make_game.py").read_text(encoding="utf-8")
        main = src[src.index("\ndef main(a=None):"):]
        changed = main[main.index("    def lift_changed():"):main.index("    def changed_twice():")]
        self.assertIn('os.environ.get("HOOKSHOT_LIFT_RECHECK") == "0"', changed)
        self.assertIn("lift_key(exefs, work, env) != key", changed)
        self.assertIn("changed_lift(gen_dir, translate_again)", changed)
        self.assertIn('run(PY + ["nx2/build.py", "--standalone", "--jobs", str(a.jobs)], env, compile_line, again=lift_changed)', main)
        self.assertIn("again=changed_twice)", main)
        self.assertIn("    def translate():", main)
        self.assertIn("\n    translate()\n", main)


if __name__ == "__main__":
    unittest.main()
