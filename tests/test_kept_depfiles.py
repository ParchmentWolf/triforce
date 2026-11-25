"""The renderer's and the runtime's depfiles kept beside the object cache (nx2/build.py kept_depfile, keep_depfile): a player's
build lets the build folder go once the game folder is ready, and the object cache keeps only the depfile keys the last build's
stamps name. Without a kept depfile the next update named those objects by the folders' blob, which the cache no longer held, and
compiled them all again. Game-free.

python -I -B tests/test_kept_depfiles.py
"""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


def esc(p):
    """a path as clang's depfile writes it: a space escaped"""
    return str(p).replace(" ", chr(92) + " ")


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "third_party" / "a64-kit" / "tools")]
spec = importlib.util.spec_from_file_location("build_kept_depfiles", ROOT / "nx2" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class KeptDepfiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="triforce kept depfiles ")
        self.addCleanup(self.temporary.cleanup)
        d = Path(self.temporary.name)
        self.vk, self.obj_dir, self.cache = d / "gpu" / "vk", d / "sa" / "build" / "obj", d / "objcache"
        for p in (self.vk, self.obj_dir):
            p.mkdir(parents=True)
        (self.vk / "a.h").write_bytes(b"int a;\n")
        (self.vk / "b.h").write_bytes(b"int b;\n")
        self.obj = str(self.obj_dir / "vk_x.o")
        Path(build.depfile_of(self.obj)).write_text("%s: %s %s\n" % (esc(self.obj), esc(self.vk / "x.cpp"), esc(self.vk / "a.h")),
                                                    encoding="utf-8")
        patch = mock.patch.object(build, "OBJ_CACHE", str(self.cache))
        patch.start()
        self.addCleanup(patch.stop)
        build._HEADER_DIGESTS.clear()

    def test_the_kept_copy_names_the_object_when_the_build_folder_is_gone(self):
        key = build.renderer_deps(b"blob", (str(self.vk),), self.obj)
        self.assertTrue(key.startswith(build.DEPFILE_DEPS))
        build.keep_depfile(self.obj)
        self.assertTrue(os.path.isfile(build.kept_depfile(self.obj)))
        os.remove(build.depfile_of(self.obj))   # (the clean-up after a player's build)
        self.assertEqual(build.renderer_deps(b"blob", (str(self.vk),), self.obj), key)

    def test_no_depfile_anywhere_is_the_blob(self):
        os.remove(build.depfile_of(self.obj))
        self.assertEqual(build.renderer_deps(b"blob", (str(self.vk),), self.obj), b"blob")

    def test_the_one_beside_the_object_comes_first(self):
        build.keep_depfile(self.obj)
        Path(build.depfile_of(self.obj)).write_text("%s: %s %s\n" % (esc(self.obj), esc(self.vk / "x.cpp"), esc(self.vk / "b.h")),
                                                    encoding="utf-8")
        build._HEADER_DIGESTS.clear()
        (self.vk / "a.h").write_bytes(b"int a2;\n")   # (read by the kept copy alone: no change to the key)
        first = build.renderer_deps(b"blob", (str(self.vk),), self.obj)
        build._HEADER_DIGESTS.clear()
        (self.vk / "b.h").write_bytes(b"int b2;\n")
        self.assertNotEqual(build.renderer_deps(b"blob", (str(self.vk),), self.obj), first)

    def test_rekey_keeps_it(self):
        src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        rekey = src[src.index("\ndef rekey_depfiles("):src.index("\ndef keep_depfile(")]
        self.assertIn("keep_depfile(obj)", rekey)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
