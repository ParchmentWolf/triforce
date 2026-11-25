"""Translate's bar moves as the lift's steps end (nx2/make_game.py lift_progress). Game-free: the lines a lift of OoT printed
(11-24, abridged), fed to the on_line make_game.py gives the lift's run().

  - each step the lift prints moves the bar once, to that step's end, in the lift's order, and the last to near the end
    (split_hot comes after the lift, in the same stage);
  - other lines, and a step's line again, say nothing; the bar never goes back (one process prints the coverage report before
    the emit, spawned processes after it starts: the same order of ends here);
  - every line LIFT_STEPS looks for is one nx2/lift.py or nx2/chunks.py still prints.

    python -I -B tests/test_lift_progress.py
"""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
spec = importlib.util.spec_from_file_location("make_game_under_test", os.path.join(ROOT, "nx2", "make_game.py"))
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)

LINES = """standalone: 1203 HLE functions in host/, 153 OS-facing imports stubbed
image: rtld@0x80000000+0x20000, main@0x80020000+0x4ea0000; 295178 entries, 0 trampolines (0 unresolved non-weak imports) (3s)
discovery: 24 parts walked in 8 processes
discovered 294522 functions (12s)
emit: 8 processes (HOOKSHOT_LIFT_JOBS=<n> for another count, 1 for one process)
translated instructions: 100.0000% of 17646355 (shared tails counted once per function)
jump tables 1475 (bounded 1385, bounded by function 58, ADR table 1), BR without a table 0, PLT stubs 9917
coverage report (21s)
chunks: code_006.c (42 MB, cost 54 MB) in 3 parts
chunks: 68, boundaries kept
oot_patches: output size in code_042.c
standalone: hos_image.c (thread hooks 0x85e5dc40, 0x85e5dc48), 153 import stubs
standalone: nvn2_exports.c (22 sdk NVN functions routed to host/nvn2.c)
interrupt polls: 683145 loop headers in 113684 functions
wrote 68 code files to D:\\work\\sa\\gen (65s)
done (65s)""".splitlines()


class LiftProgress(unittest.TestCase):
    def test_steps(self):
        told = []
        on_line = make_game.lift_progress(told.append)
        for line in LINES:
            on_line(line)
        self.assertEqual(told, [f for _, f in make_game.LIFT_STEPS])
        self.assertEqual(told, sorted(told))
        self.assertTrue(0 < told[0] and told[-1] < 1)
        for line in LINES:   # (again: nothing, the bar is past every step)
            on_line(line)
        self.assertEqual(len(told), len(make_game.LIFT_STEPS))

    def test_never_back(self):
        told = []
        on_line = make_game.lift_progress(told.append)
        on_line("chunks: 68, boundaries kept")
        on_line("coverage report (21s)")   # (a step before: no line)
        on_line("discovered 294522 functions (12s)")
        self.assertEqual(len(told), 1)

    def test_the_lift_prints_them(self):
        text = "".join(open(os.path.join(ROOT, "nx2", f), encoding="utf-8").read() for f in ("lift.py", "chunks.py"))
        for needle in ('"discovered %d functions', '"coverage report (', '"chunks: %d, boundaries', '"standalone: hos_image.c',
                       '"wrote %d code files'):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
