"""A large first read of a .nup extracts the game's code first and the rest beside the lift (nx2/make_game.py
overlap_package_read). Game-free.

  - the gate: a package of 1 GiB or more, more than one job, no copy of the game in the folder yet, 8 GB free and no hard
    drive; each of those missing (and HOOKSHOT_OVERLAP_READ=0) keeps the read whole before the lift, as before;
  - main(): the code is extracted with --only exefs and checked before the lift, the romfs with --only romfs beside it; the
    package is checked to be the same file after; the romfs read is waited for before the compile, its damaged files stood in
    for, and only then do the prompts (which read the romfs) start. Without the overlap, the order is as before.

    python -I -B tests/test_overlap_read.py
"""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
spec = importlib.util.spec_from_file_location("make_game_under_test", os.path.join(ROOT, "nx2", "make_game.py"))
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)

GIB = 1 << 30


class Gate(unittest.TestCase):
    def gate(self, jobs=8, size=20 * GIB, have=(), free=16000, spinning=False, env=None):
        with tempfile.TemporaryDirectory(prefix="overlap-read-") as tmp:
            out, work = os.path.join(tmp, "out"), os.path.join(tmp, "work")
            kept, romfs = os.path.join(out, ".triforce_exefs"), os.path.join(out, "romfs")
            for f in have:
                os.makedirs(os.path.join(out, f))
            build = types.ModuleType("build")
            build.free_mb = lambda: free
            with mock.patch.dict(sys.modules, {"build": build}), \
                    mock.patch.object(make_game, "spinning_disk", lambda folder: spinning), \
                    mock.patch.dict(os.environ, env or {}), mock.patch.object(make_game.os, "cpu_count", lambda: 16):
                if env is None:
                    os.environ.pop("HOOKSHOT_OVERLAP_READ", None)
                return make_game.overlap_package_read(jobs, types.SimpleNamespace(st_size=size), out, work, kept, romfs)

    def test_gate(self):
        self.assertTrue(self.gate())
        self.assertTrue(self.gate(jobs=None))   # (the build's own count)
        self.assertTrue(self.gate(spinning=None))   # (a drive that cannot be told: as an SSD)
        for what, kw in (("one job", dict(jobs=1)), ("a small package", dict(size=GIB - 1)),
                         ("a copy of the code", dict(have=(".triforce_exefs",))), ("a romfs", dict(have=("romfs",))),
                         ("little memory", dict(free=8191)), ("memory not known", dict(free=None)),
                         ("a hard drive", dict(spinning=True)), ("switched off", dict(env={"HOOKSHOT_OVERLAP_READ": "0"}))):
            self.assertFalse(self.gate(**kw), what)

    def test_identity(self):
        st = os.stat(__file__)
        self.assertEqual(make_game.package_identity(st), make_game.package_identity(os.stat(__file__)))


class Order(unittest.TestCase):
    def test_main(self):
        src = open(os.path.join(ROOT, "nx2", "make_game.py"), encoding="utf-8").read()
        body = src[src.index("def main("):]
        exefs_first = body.index('run(extract + ["--only", "exefs"])')
        self.assertLess(exefs_first, body.index("remaining_assets = read_assets"))
        self.assertIn('run(extract + (["--only", "romfs"] if overlap else []))', body)
        self.assertIn("package_identity(os.stat(a.nup)) != package_identity(st)", body)
        reader = body.index("reading = reader.submit(remaining_assets)")
        joined = body.index("reading.result()", reader)
        self.assertLess(body.index("\n    translate()\n", reader), joined)
        stand_in = body.index("stand_in_damaged_files(out, romfs, seen_holder[0])", joined)
        self.assertLess(stand_in, body.index("prompts = start_prompts()", joined))
        self.assertLess(joined, body.index('env["HOOKSHOT_TIMES"]'))   # (before the compile)
        self.assertIn("prompts = None if remaining_assets else start_prompts()", body)


if __name__ == "__main__":
    unittest.main()
