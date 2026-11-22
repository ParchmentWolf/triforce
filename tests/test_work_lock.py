"""One build at a time per work folder: make_game.py's OS lock on <work>/make_game.lock (no game, no tools).

(Triforce, 11-22, the performance audit's IO-47, after Source A's.) Two builds on one work folder compiled the same
objects twice and raced on the staged game folder; on Linux nothing stopped the second. make_game.py now holds an OS
lock for as long as it runs, taken after stop_stray_compilers (so Windows still replaces a build left running) and
before drop_stale_objects. HOOKSHOT_WORK_LOCK=0 turns it off.

With real processes on temporary folders:
  - while another process holds a folder's lock, lock_work stops the build (exit 1, an @@error naming the folder and the
    holder's process id), at once;
  - a holder that is killed frees the lock: the next lock_work, told to wait as main does after a stop, takes it;
  - asked again for the same folder it keeps the same open file; asked for another folder it lets the first go;
  - release_work frees the lock and leaves the file;
  - HOOKSHOT_WORK_LOCK=0 takes no lock and refuses nothing;
  - an error that is not "held by another" is said and the build goes on without the lock;
  - main() asks stop_stray_compilers, then lock_work (waiting 10 s only when something was stopped), then
    drop_stale_objects; the source and the switches table say the same.

    python -I -B tests/test_work_lock.py
"""
import contextlib
import errno
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "nx2" / "make_game.py"
spec = importlib.util.spec_from_file_location("make_game_work_lock", SOURCE)
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)

# (another build: takes the folder's lock as make_game does, says so, and holds it until its input ends)
HOLDER = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("make_game_lock_holder", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.lock_work(sys.argv[2])
print("held", flush=True)
sys.stdin.read()
'''


class Stop(Exception):
    """main() stopped by the test at drop_stale_objects"""


class WorkLock(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="triforce-work-lock-")
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(make_game.release_work)   # (before the folder goes: Windows deletes no open file)
        self.root = Path(self.temporary.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.holders = []
        self.addCleanup(self.stop_holders)
        self.env = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_WORK_LOCK"}
        patched = mock.patch.dict(os.environ, self.env, clear=True)
        patched.start()
        self.addCleanup(patched.stop)

    def stop_holders(self):
        for p in self.holders:
            if p.poll() is None:
                p.kill()
            p.communicate()

    def holder(self, folder=None, hold=True):
        """Another process that locks the folder: (the process, whether it got the lock, what it said)"""
        p = subprocess.Popen([sys.executable, "-I", "-B", "-c", HOLDER, str(SOURCE), str(folder or self.work)],
                             stdin=subprocess.PIPE if hold else subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=self.env)
        self.holders.append(p)
        if not hold:
            out, err = p.communicate(timeout=60)
            return p, p.returncode == 0 and out.strip() == "held", out + err
        line = p.stdout.readline()
        return p, line.strip() == "held", line

    def lock(self, folder=None, **kw):
        """lock_work here: (what it returned or the exit code it stopped with, what it printed, the seconds it took)"""
        said = io.StringIO()
        began = time.monotonic()
        try:
            with contextlib.redirect_stdout(said):
                result = make_game.lock_work(str(folder or self.work), **kw)
        except SystemExit as e:
            result = "exit %s" % e.code
        return result, said.getvalue(), time.monotonic() - began

    def test_a_held_folder_stops_the_second_build_and_names_the_holder(self):
        p, held, said = self.holder()
        self.assertTrue(held, said)
        result, text, seconds = self.lock()
        self.assertEqual(result, "exit 1")
        self.assertIn("@@error Another build is already working in %s (process %d)." % (self.work, p.pid), text)
        self.assertLess(seconds, 2.0)
        self.assertIsNone(make_game._work_lock)
        self.assertEqual(make_game.work_lock_holder(str(self.work / make_game.WORK_LOCK)), p.pid)
        # (and the holder still has it: a refused build took nothing away)
        self.assertFalse(self.holder(hold=False)[1])

    def test_a_killed_holder_frees_the_lock(self):
        p, held, said = self.holder()
        self.assertTrue(held, said)
        p.kill()
        p.wait()
        result, text, seconds = self.lock(wait=10)   # (as main does after stop_stray_compilers stopped a build)
        self.assertIs(result, True, text)
        self.assertLess(seconds, 10.0)
        self.assertEqual(make_game.work_lock_holder(str(self.work / make_game.WORK_LOCK)), os.getpid())

    def test_wait_is_bounded_while_the_holder_lives(self):
        p, held, said = self.holder()
        self.assertTrue(held, said)
        result, text, seconds = self.lock(wait=1.0)
        self.assertEqual(result, "exit 1")
        self.assertGreaterEqual(seconds, 1.0)
        self.assertLess(seconds, 5.0)

    def test_again_for_the_same_folder_keeps_the_file(self):
        self.assertIs(self.lock()[0], True)
        first = make_game._work_lock[0]
        self.assertIs(self.lock(self.work / "." )[0], True)   # (the same folder, spelled another way)
        self.assertIs(make_game._work_lock[0], first)
        self.assertFalse(first.closed)
        self.assertFalse(self.holder(hold=False)[1])   # (another process is refused)
        self.assertTrue((self.work / make_game.WORK_LOCK).is_file())

    def test_another_folder_lets_the_first_go(self):
        other = self.root / "other"
        other.mkdir()
        self.assertIs(self.lock()[0], True)
        self.assertIs(self.lock(other)[0], True)
        self.assertEqual(os.path.normcase(make_game._work_lock[1]), os.path.normcase(str(other)))
        p, held, said = self.holder(self.work, hold=False)
        self.assertTrue(held, said)       # (the first folder is free)
        p, held, said = self.holder(other, hold=False)
        self.assertFalse(held, said)      # (the second is this process's)
        self.assertIn("@@error Another build is already working in", said)
        self.assertEqual(p.returncode, 1)

    def test_release_frees_the_lock_and_leaves_the_file(self):
        self.assertIs(self.lock()[0], True)
        make_game.release_work()
        self.assertIsNone(make_game._work_lock)
        self.assertTrue((self.work / make_game.WORK_LOCK).is_file())
        self.assertTrue(self.holder(hold=False)[1])
        make_game.release_work()   # (nothing held: nothing happens)

    def test_switch_off_takes_no_lock(self):
        p, held, said = self.holder()
        self.assertTrue(held, said)
        with mock.patch.dict(os.environ, {"HOOKSHOT_WORK_LOCK": "0"}):
            result, text, seconds = self.lock()
        self.assertIs(result, False)
        self.assertEqual(text, "")
        self.assertIsNone(make_game._work_lock)
        with mock.patch.dict(os.environ, {"HOOKSHOT_WORK_LOCK": "1"}):
            self.assertEqual(self.lock()[0], "exit 1")

    def test_another_error_builds_without_the_lock(self):
        for error in (OSError(errno.ENOSYS, "no locks on this file system"), OSError(errno.EIO, "a made-up error")):
            with self.subTest(error=error.errno), mock.patch.object(make_game, "_lock_first_byte", side_effect=error):
                result, text, seconds = self.lock()
                self.assertIs(result, False)
                self.assertIn("this build runs without the work folder's lock", text)
                self.assertIsNone(make_game._work_lock)
        # and a held error, however the OS words it, refuses
        for number in make_game.WORK_LOCK_HELD:
            with self.subTest(held=number), mock.patch.object(make_game, "_lock_first_byte", side_effect=OSError(number, "held")):
                self.assertEqual(self.lock()[0], "exit 1")

    def test_main_locks_after_the_stop_and_before_the_stale_objects(self):
        out = self.root / "out"
        for stopped, wait in ((2, 10), (0, 0), (None, 0)):
            calls = []
            argv = ["make_game.py", "--work", str(self.work), "--out", str(out), "--romfs", str(self.root / "r"),
                    "--exefs", str(self.root / "e")]
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(sys, "argv", argv))
                stack.enter_context(mock.patch.object(make_game, "check_windows_sdk"))
                stack.enter_context(mock.patch.object(make_game, "check_cpu"))
                stack.enter_context(mock.patch.object(make_game, "no_throttle"))
                stack.enter_context(mock.patch.object(make_game, "warn_slow_disk"))
                stack.enter_context(mock.patch("ctypes.WinDLL", create=True))
                stack.enter_context(mock.patch.object(
                    make_game, "stop_stray_compilers", side_effect=lambda work, default: calls.append("stop") or stopped))
                stack.enter_context(mock.patch.object(
                    make_game, "lock_work", side_effect=lambda work, wait=0.0: calls.append(("lock", work, wait))))

                def stale(work):
                    calls.append("stale")
                    raise Stop

                stack.enter_context(mock.patch.object(make_game, "drop_stale_objects", side_effect=stale))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                with self.assertRaises(Stop):
                    make_game.main()
            self.assertEqual(calls, ["stop", ("lock", os.path.abspath(str(self.work)), wait), "stale"])

    def test_source_and_docs(self):
        source = SOURCE.read_text(encoding="utf-8")
        main = source[source.index("def main(a=None):"):source.index("def cli():")]
        stop = main.index("stopped = stop_stray_compilers(work, a.default_work)")
        lock = main.index("lock_work(work, wait=10 if stopped else 0)")
        stale = main.index("drop_stale_objects(work)")
        self.assertTrue(stop < lock < stale)
        self.assertEqual(main.count("lock_work("), 1)
        self.assertIn('if os.environ.get("HOOKSHOT_WORK_LOCK") == "0":', source)
        self.assertIn("fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)", source)
        self.assertIn("msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)", source)
        self.assertIn("make_game.py", make_game.LIFT_KEY_NOT)   # (the lock changes no lift key: nothing is translated again)
        docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
        rows = [line for line in docs.splitlines() if line.startswith("| `HOOKSHOT_WORK_LOCK=0` |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("IO-47", rows[0])
        for name in ("test_make_game_cache.py", "test_missing_nup.py"):   # (they run main() in temporary folders)
            self.assertTrue("self.addCleanup(make_game.release_work)" in (ROOT / "tests" / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
