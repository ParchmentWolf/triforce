"""A build that fails in its compile keeps the files that did compile (nx2/make_game.py compile_alone_failed).

make_game deleted every compiled object after any failed build, so that a stale object could not fail the link at every
try (issue 1197). A compiler that runs out of memory, or a full disk, is the common failure, and it then cost the next
build all ~600 files again. Each object is stamped and cached under the hash of its source and flags only once its
compiler ended well, so after a compile that failed before any link the ones there are whole: they stay, and only a
build that failed at a link, or ended without saying how its compile went, loses them.

Game-free: build.py's own lines, authored.

    python -I -B tests/test_failed_compile_keeps_objects.py
"""
import ast
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
sys.path.insert(0, str(ROOT / "third_party/a64-kit/tools"))
spec = importlib.util.spec_from_file_location("make_game_failed_compile", ROOT / "nx2/make_game.py")
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


class WhichFailureKeepsTheObjects(unittest.TestCase):
    def test_a_failed_compile_keeps_them(self):
        self.assertTrue(make_game.compile_alone_failed(["compiled in 412s, 2 failed"]))
        self.assertTrue(make_game.compile_alone_failed(["compiled in 9s, 1 failed"]))

    def test_a_failed_link_does_not(self):
        self.assertFalse(make_game.compile_alone_failed(["compiled in 412s, 0 failed", "link FAILED (3s), 20 undefined symbols"]))
        self.assertFalse(make_game.compile_alone_failed(["compiled in 412s, 0 failed", "triforce_vk.dll link FAILED, 4 undefined symbols"]))
        # (never both in one run, but if a link is ever tried after failed files it still decides)
        self.assertFalse(make_game.compile_alone_failed(["compiled in 412s, 1 failed", "link FAILED (3s), 1 undefined symbols"]))

    def test_a_build_that_did_not_say_how_its_compile_went_does_not(self):
        self.assertFalse(make_game.compile_alone_failed([]))                               # (stopped, or failed before the compile)
        self.assertFalse(make_game.compile_alone_failed(["compiled in 412s, 0 failed"]))   # (failed after a clean compile, not at a link)

    def test_the_lines_are_build_pys_own(self):
        build = (ROOT / "nx2/build.py").read_text(encoding="utf-8")
        self.assertIn('print("compiled in %.0fs, %d failed" % (time.time() - t0, still), flush=True)', build)
        self.assertGreaterEqual(build.count("link FAILED"), 3)
        # (an object is stamped and cached only after its compiler returned 0)
        one = build[build.index("def compile_one(job):"):build.index("\ndef main():")]
        self.assertLess(one.index("if r.returncode:"), one.index('open(stamp, "w").write(key)\n    cache_put(obj, key)'))

    def test_the_failed_build_asks_before_it_deletes(self):
        body = (ROOT / "nx2/make_game.py").read_text(encoding="utf-8")
        body = body[body.index('run(PY + ["nx2/build.py", "--standalone"'):body.index("compile_seconds = time.time() - compile_started")]
        asked, deleted = body.index("if compile_alone_failed(said):"), body.index('os.path.join(work, "objcache")')
        self.assertLess(asked, deleted)
        # (the lift is forgotten before that, a lifted file cut short fails the same way at every try otherwise; unless the
        # compile failed only in the program's own files, once: the performance audit's LIFT-27, KeptLift below)
        self.assertLess(body.index("os.remove(key_file)"), asked)
        self.assertLess(body.index("lift_kept = keep_lift_after_failure(said, work)"), body.index("os.remove(key_file)"))
        self.assertIn("if os.path.exists(key_file) and not lift_kept:", body)


def failed_build_handler():
    """The statements main() runs when nx2/build.py failed, cut out of make_game.py: its except block, behind a raise"""
    source = (ROOT / "nx2/make_game.py").read_text(encoding="utf-8")
    main = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    tries = [n for n in ast.walk(main) if isinstance(n, ast.Try) and any(
        isinstance(c, ast.Constant) and c.value == "nx2/build.py" for s in n.body for c in ast.walk(s))]
    assert len(tries) == 1 and len(tries[0].handlers) == 1
    stop = ast.parse("raise SystemExit(1)").body
    block = ast.Try(body=stop, handlers=tries[0].handlers, orelse=[], finalbody=[])
    return compile(ast.fix_missing_locations(ast.Module(body=[block], type_ignores=[])), "make_game.py", "exec")


class KeptLift(unittest.TestCase):
    """(11-22, the performance audit's LIFT-27, after Source A's) A compile that failed only in the program's own files
    keeps the translated game too, once: failed_only_own_sources, keep_lift_after_failure, and main()'s own except block
    run on a made-up work folder"""
    OWN = ["FAILED vk_draw.cpp (1 MB, 12s, alone too):", "vk_draw.cpp:10:1: error: a made-up error", "compiled in 412s, 1 failed"]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="triforce-kept-lift-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name) / "work"
        self.gen = self.work / "sa" / "gen"
        self.gen.mkdir(parents=True)
        (self.work / "sa" / "build" / "gen").mkdir(parents=True)
        for name in ("code_000.c", "code_hot_0.c", "a64_table.c", "a64_fpx.h"):
            (self.gen / name).write_text("// lifted\n")
        (self.work / "sa" / "build" / "gen" / "ui_fonts.cpp").write_text("// generated\n")
        self.key = self.gen / make_game.LIFT_KEY
        self.key.write_text("key\nprint\n")
        self.objects = self.work / "objcache"
        self.objects.mkdir()
        (self.objects / "one.o").write_bytes(b"object")
        self.mark = self.work / "sa" / make_game.LIFT_KEPT_ONCE
        environ = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_KEEP_LIFT"}
        patched = mock.patch.dict(os.environ, environ, clear=True)
        patched.start()
        self.addCleanup(patched.stop)

    def lines(self, *names, count=None):
        return ["FAILED %s (3 MB, 40s, alone too):" % n for n in names] + \
            ["compiled in 412s, %d failed" % (len(names) if count is None else count)]

    def test_only_the_programs_own_files(self):
        own = lambda *names, **k: make_game.failed_only_own_sources(self.lines(*names, **k), str(self.work))
        self.assertTrue(own("vk_draw.cpp"))
        self.assertTrue(own("hos_main.c", "vk_shader.cpp", "imgui.cpp"))
        self.assertTrue(make_game.failed_only_own_sources(self.OWN, str(self.work)))
        self.assertFalse(own("code_021.c"))                       # (a lifted file)
        self.assertFalse(own("code_hot_3.c"))
        self.assertFalse(own("vk_draw.cpp", "code_021.c"))        # (one of them is)
        self.assertFalse(own("a64_table.c"))                      # (a file of the lift's folder)
        self.assertFalse(own("ui_fonts.cpp"))                     # (a file the build generated)
        self.assertFalse(own("vk_draw.cpp", count=2))             # (a failed file that was not named)
        self.assertFalse(own())                                   # (none named)
        self.assertFalse(make_game.failed_only_own_sources([], str(self.work)))
        self.assertFalse(make_game.failed_only_own_sources(["FAILED vk_draw.cpp (1 MB, 2s, alone too):"], str(self.work)))

    def test_kept_once_and_not_twice_in_a_row(self):
        keep = lambda lines, environ=None: make_game.keep_lift_after_failure(lines, str(self.work), environ)
        self.assertTrue(keep(self.OWN))
        self.assertTrue(self.mark.exists())
        self.assertFalse(keep(self.OWN))          # (the same kind of failure again: the lift is forgotten this time)
        self.assertFalse(self.mark.exists())
        self.assertTrue(keep(self.OWN))           # (and after that lift, once again)
        self.mark.unlink()
        self.assertFalse(keep(self.lines("code_021.c")))
        self.assertFalse(self.mark.exists())
        self.assertFalse(keep(["compiled in 412s, 0 failed", "link FAILED (3s), 20 undefined symbols"]))
        self.assertFalse(keep(self.OWN + ["link FAILED (3s), 1 undefined symbols"]))
        self.assertFalse(keep([]))
        self.assertFalse(keep(self.OWN, {"HOOKSHOT_KEEP_LIFT": "0"}))   # (the switch: forgotten after every failed build)
        self.assertFalse(self.mark.exists())
        self.assertTrue(keep(self.OWN, {"HOOKSHOT_KEEP_LIFT": "1"}))

    def fail_build(self, said):
        """main()'s own except block after a failed build.py that said these lines: what it printed"""
        stopped = []
        printed = io.StringIO()
        scope = dict(make_game.__dict__, said=list(said), work=str(self.work),
                     prompts=types.SimpleNamespace(stop=lambda: stopped.append(True)))
        with contextlib.redirect_stdout(printed), self.assertRaises(SystemExit):
            exec(failed_build_handler(), scope)
        self.assertEqual(stopped, [True])
        return printed.getvalue()

    def test_the_failed_builds_own_statements(self):
        # (the program's own file failed: the key and the objects stay)
        said = self.fail_build(self.OWN)
        self.assertTrue(self.key.exists() and (self.objects / "one.o").exists() and self.mark.exists())
        self.assertIn("the translated game and the files that did compile are kept", said)
        # (the same again at the next build: the key goes, the objects stay)
        said = self.fail_build(self.OWN)
        self.assertFalse(self.key.exists() or self.mark.exists())
        self.assertTrue((self.objects / "one.o").exists())
        self.assertIn("the next build translates the game again and compiles only the rest", said)
        # (a lifted file failed: the key goes at once)
        self.key.write_text("key\nprint\n")
        said = self.fail_build(self.lines("code_021.c"))
        self.assertFalse(self.key.exists() or self.mark.exists())
        self.assertTrue((self.objects / "one.o").exists())
        self.assertIn("the next build translates the game again and compiles only the rest", said)
        # (a link failed: the key and the objects go, as before)
        self.key.write_text("key\nprint\n")
        said = self.fail_build(["compiled in 412s, 0 failed", "link FAILED (3s), 20 undefined symbols"])
        self.assertFalse(self.key.exists() or self.objects.exists())
        self.assertIn("nothing of this one is reused", said)

    def test_the_switch_forgets_after_every_failed_build(self):
        with mock.patch.dict(os.environ, {"HOOKSHOT_KEEP_LIFT": "0"}):
            said = self.fail_build(self.OWN)
        self.assertFalse(self.key.exists() or self.mark.exists())
        self.assertTrue((self.objects / "one.o").exists())
        self.assertIn("the next build translates the game again and compiles only the rest", said)

    def test_the_lines_and_the_marks_place(self):
        build = (ROOT / "nx2/build.py").read_text(encoding="utf-8")
        self.assertIn('print("FAILED %s (%d MB, %.0fs, alone too):\\n%s" % (os.path.basename(src), size, secs, err), flush=True)', build)
        source = (ROOT / "nx2/make_game.py").read_text(encoding="utf-8")
        self.assertIn('if line.startswith("compiled in ") or "link FAILED" in line or line.startswith("FAILED "):', source)
        # (the mark is not in sa/gen: gen_print vouches for every file there, and a new one would be a new lift)
        self.assertIn('mark = os.path.join(work, "sa", LIFT_KEPT_ONCE)', source)
        after = source[source.index("        prompts.stop()\n        raise\n"):source.index("compile_seconds = time.time() - compile_started")]
        self.assertIn('os.remove(os.path.join(work, "sa", LIFT_KEPT_ONCE))', after)
        before = make_game.gen_print(str(self.gen))
        make_game.keep_lift_after_failure(self.OWN, str(self.work))
        self.assertEqual(make_game.gen_print(str(self.gen)), before)


if __name__ == "__main__":
    unittest.main()
