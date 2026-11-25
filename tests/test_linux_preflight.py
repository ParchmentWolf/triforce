"""A Linux build says every missing prerequisite at once, before the game is read (nx2/make_game.py check_linux_prerequisites;
no game, no compiler run).

It was one at a time: a missing Python module stopped the read, the compiler was probed after the lift, and the renderer's
headers and FFmpeg were found missing in the compile, each a new try minutes in. Now make_game.py asks the compile's own
lookups (nx2/build.py vulkan_headers, prebuilt_renderer, ffmpeg_linux(missing)) first and fails once with the whole list.

This loads make_game.py and build.py with the lookups answered by the test: with a pinned module, a header, FFmpeg and the
compilers all missing, one failure names every one; with the prebuilt renderer the headers are not asked for; with all there
it says OK. And it reads the source: on Linux the check runs before the read stage, after the DLSS SDK's fetch (which decides
the prebuilt renderer), and no compiler probe is left after the lift.

    python -I -B tests/test_linux_preflight.py
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


class Failed(Exception):
    pass


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LinuxPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path[:0] = [str(NX2)]
        cls.make = load("triforce_make_game_preflight", NX2 / "make_game.py")
        cls.build = load("build", NX2 / "build.py")

    def run_check(self, *, module_missing, headers, prebuilt, ffmpeg_missing, compilers):
        with tempfile.TemporaryDirectory(prefix="triforce-preflight-") as tmp:
            pins = "lz4==4.4.5\n" + ("triforce_not_a_module_xyz==1.0\n" if module_missing else "")
            Path(tmp, "requirements.txt").write_text(pins + "-r nx2/prompt_requirements.txt\n", encoding="utf-8")

            def ffmpeg(missing=None):
                if ffmpeg_missing and missing is not None:
                    missing.append("FFmpeg: libavcodec")
                return None if ffmpeg_missing else ([], [])

            def fail(text):
                raise Failed(text)

            asked = []

            def vulkan_headers(work=None):
                asked.append(work)
                return headers

            with mock.patch.dict(sys.modules, {"build": self.build}), \
                    mock.patch.object(self.make, "ROOT", tmp), mock.patch.object(self.make, "fail", fail), \
                    mock.patch.object(self.build, "prebuilt_renderer", lambda: prebuilt), \
                    mock.patch.object(self.build, "vulkan_headers", vulkan_headers), \
                    mock.patch.object(self.build, "ffmpeg_linux", ffmpeg), \
                    mock.patch.object(self.build.toolchain, "find",
                                      lambda name: __file__ if compilers else os.path.join(tmp, "no-" + name)):
                try:
                    self.make.check_linux_prerequisites(os.path.join(tmp, "work"))
                except Failed as e:
                    return str(e), asked
                return None, asked

    def test_every_missing_prerequisite_in_one_message(self):
        text, asked = self.run_check(module_missing=True, headers=[None, "/usr", "/usr"], prebuilt="", ffmpeg_missing=True,
                                     compilers=False)
        self.assertIsNotNone(text)
        self.assertTrue(text.startswith("Missing Linux build prerequisites: "), text)
        for part in ("Python module triforce_not_a_module_xyz", "Vulkan header vulkan/vulkan.h", "FFmpeg: libavcodec",
                     "clang compiler", "clang++ compiler"):
            self.assertIn(part, text)
        self.assertNotIn("\n", text)   # (one line: the builder shows the whole set)
        self.assertEqual(len(asked), 1)
        self.assertTrue(asked[0].endswith("work"))   # (the build's work folder: its CPM cache)

    def test_the_prebuilt_renderer_needs_no_headers(self):
        _, asked = self.run_check(module_missing=False, headers=[None, None, None], prebuilt=__file__, ffmpeg_missing=True,
                                  compilers=False)
        self.assertEqual(asked, [])

    def test_nothing_missing_is_ok(self):
        with mock.patch.object(self.make.subprocess, "run",
                               lambda *a, **k: mock.Mock(returncode=0, stdout="", stderr="")):
            text, _ = self.run_check(module_missing=False, headers=["/usr", "/usr", "/usr"], prebuilt="", ffmpeg_missing=False,
                                     compilers=True)
        self.assertIsNone(text)

    def test_the_check_comes_before_the_game_is_read(self):
        src = (NX2 / "make_game.py").read_text(encoding="utf-8")
        main = src[src.index("\ndef main(a=None):"):]
        fetch = main.index("fetch_ngx_sdk(a)")
        check = main.index("check_windows_sdk(work)")
        self.assertLess(fetch, check)
        self.assertLess(check, main.index('say("stage", "read"'))
        self.assertNotIn("check_linux_compiler()", main)   # (no second probe after the lift)
        sdk = src[src.index("def check_windows_sdk(work=None):"):]
        self.assertIn("return check_linux_prerequisites(work)", sdk[:sdk.index("\ndef ")])
        build = (NX2 / "build.py").read_text(encoding="utf-8")
        self.assertIn("vk_headers, spirv_headers, vma_headers = vulkan_headers()", build)
        self.assertIn("vk_prebuilt = prebuilt_renderer()", build)


if __name__ == "__main__":
    unittest.main()
