"""HOOKSHOT_LIGHT_PASSES=1 (nx2/build.py lifted_flags): lifted chunks whose functions are all under HOOKSHOT_LIGHT_PASSES_KB
compile at -O1 without its module passes; the giants, the hot pieces and the other files keep their flags. Off by default: every
chunk's flags (and so its object key) as before. Game-free.

python -I -B tests/test_light_passes.py
"""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "third_party" / "a64-kit" / "tools")]
spec = importlib.util.spec_from_file_location("build_light_passes", ROOT / "nx2" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

FL, DEPS = ["-O1", "-DA64_POLLING"], b"headers"


def lifted(sizes):
    """a lifted file's text with functions of these sizes (bytes)"""
    out = b"#include \"a64_guest.h\"\n"
    for i, size in enumerate(sizes):
        head = b"\nvoid f_%08x(Ctx *__restrict A64_NOESC c) {\n" % (0x80000000 + 16 * i)
        out += head + b" " * max(0, size - len(head) - 3) + b"}\n"
    return out


class LightPasses(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="triforce-light-")
        self.addCleanup(self.temporary.cleanup)
        build.load_hashes(self.temporary.name)

    def write(self, name, sizes):
        p = Path(self.temporary.name) / name
        p.write_bytes(lifted(sizes))
        return str(p)

    def test_on_by_default_off_by_zero(self):   # ((Triforce, 11-24) on by default after the lab: no fps change)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOOKSHOT_LIGHT_PASSES", None)
            os.environ.pop("HOOKSHOT_LIGHT_PASSES_KB", None)
            self.assertEqual(build.light_passes_kb(), 1024)
            os.environ["HOOKSHOT_LIGHT_PASSES"] = "0"
            self.assertIsNone(build.light_passes_kb())
            self.assertIs(build.lifted_flags(self.write("code_000.c", [4000]), FL, DEPS, None), FL)

    def test_small_functions_light_a_giant_not(self):
        with mock.patch.dict(os.environ, {"HOOKSHOT_LIGHT_PASSES": "1", "HOOKSHOT_LIGHT_PASSES_KB": "8"}):
            bar = build.light_passes_kb()
        self.assertEqual(bar, 8)
        small = build.lifted_flags(self.write("code_001.c", [2000, 3000]), FL, DEPS, bar)
        giant = build.lifted_flags(self.write("code_002.c", [2000, 9000]), FL, DEPS, bar)
        self.assertEqual(small, FL + build.LIGHT_FLAGS)
        self.assertEqual(giant, FL)
        self.assertNotEqual(build.flag_text(small), build.flag_text(FL))   # (a light object is another key)

    def test_the_build_gives_them_to_the_lifted_chunks_alone(self):
        src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        self.assertIn('lifted_flags(s, fl + giants_fl, deps, bar_kb) if os.path.basename(s).startswith("code_") and os.path.dirname(s) == gen\n'
                      '             else fl', src)
        self.assertLess(src.index('hot_fl if os.path.basename(s).startswith("code_hot")'), src.index("lifted_flags(s, fl + giants_fl, deps"))


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
