"""RX_A64_RT_O2=1 (nx2/build.py a64_rt_flags): the shared A64 helpers (a64_rt.c, a64_suyu.c) at -O2, the lifted chunks and the
hot pieces as they were. Off by default, the flags then the cold code's own, so the objects and their keys are as before.
Game-free.

python -I -B tests/test_a64_helper_flags.py
"""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "third_party" / "a64-kit" / "tools")]
spec = importlib.util.spec_from_file_location("build_a64_helpers", ROOT / "nx2" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

FL = ["--target=x86_64-w64-mingw32", "-O1", "-g0", "-DA64_POLLING"]


class A64HelperFlags(unittest.TestCase):
    def test_off_by_default_the_same_flags(self):
        for value in (None, "", "0", "off"):
            env = {} if value is None else {"RX_A64_RT_O2": value}
            with mock.patch.dict(os.environ, env, clear=False):
                if value is None:
                    os.environ.pop("RX_A64_RT_O2", None)
                self.assertIs(build.a64_rt_flags(FL, "O1"), FL)

    def test_on_only_the_level_changes(self):
        with mock.patch.dict(os.environ, {"RX_A64_RT_O2": "1"}):
            fl = build.a64_rt_flags(FL, "O1")
        self.assertEqual(fl, ["--target=x86_64-w64-mingw32", "-O2", "-g0", "-DA64_POLLING"])
        self.assertNotEqual(build.flag_text(fl), build.flag_text(FL))   # (another object key: compiled again)

    def test_the_build_gives_them_to_the_two_helpers_alone(self):
        src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        self.assertIn('rt_fl if os.path.basename(s) in ("a64_rt.c", "a64_suyu.c") else\n', src)
        make = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        self.assertIn('"RX_A64_RT_O2")', make[make.index("COMPILE_ONLY_ENV = "):][:120])   # (no new translation for it)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
