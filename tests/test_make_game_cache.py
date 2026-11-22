"""Game-free checks of make_game's NUP cache selection and replacement.

Run with: python -I tests/test_make_game_cache.py
"""
import contextlib
import errno
import importlib.util
import io
import os
import shutil
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


SOURCE = Path(os.environ.get("HOOKSHOT_CACHE_TEST_SOURCE", Path(__file__).resolve().parents[1] / "nx2" / "make_game.py"))
spec = importlib.util.spec_from_file_location("make_game_under_test", SOURCE)
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


class Prepared(Exception):
    """Stop at the first lift request, before compiling or reading any game."""


def module_bytes(supported=True, payload=b"new authored module"):
    header = bytearray(0x60)
    header[:4] = b"NSO0"
    header[0x40:0x44] = bytes.fromhex(make_game.BUILD_ID if supported else "01234567")
    return bytes(header) + payload


class NupCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hookshot-cache-test-")
        self.addCleanup(self.temporary.cleanup)
        # (the performance audit's IO-47: main() locks its work folder; let go before the folder is deleted)
        self.addCleanup(make_game.release_work)
        self.root = Path(self.temporary.name).resolve()
        self.out = self.root / "output"
        self.work = self.root / "work"
        self.addCleanup(self.assert_owned_fixture)
        self.out.mkdir()
        self.work.mkdir()
        self.old_nup = self.root / "old.nup"
        self.old_nup.write_bytes(b"old authored input")
        self.new_nup = self.root / "new.nup"
        self.new_nup.write_bytes(b"new authored input of a different size")
        (self.out / "romfs").mkdir()
        (self.out / "romfs" / "asset.txt").write_bytes(b"old authored assets")
        (self.out / ".hookshot_exefs").mkdir()
        (self.out / ".hookshot_exefs" / "main").write_bytes(module_bytes(payload=b"old authored module"))
        self.marker = self.out / ".hookshot_romfs"
        self.marker.write_text(self.stamp(self.old_nup) + "\n")
        save = self.out / "user" / "save"
        save.mkdir(parents=True)
        (save / "sentinel.txt").write_bytes(b"authored save sentinel")
        self.extractions = []
        self.output = ""

    def assert_owned_fixture(self):
        # The builder only receives descendants of this test-owned temporary directory.
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.out.resolve().is_relative_to(self.root))
        self.assertTrue(self.work.resolve().is_relative_to(self.root))

    def stamp(self, nup):
        return "unpacked by this builder: %s %d" % (nup.name, nup.stat().st_size)

    def cache(self):
        return {path.relative_to(self.out).as_posix(): path.read_bytes()
                for path in self.out.rglob("*") if path.is_file() and ".game" not in path.parts}

    def run_to_lift(self, nup, failure=None, supported=True, include_romfs=True, update=False, folders=None):
        self.assert_owned_fixture()

        def run(cmd, env=None, on_line=None):
            if "nx2/nup.py" in cmd:
                target = Path(cmd[cmd.index("--extract") + 1]).resolve()
                self.assertTrue(target.is_relative_to(self.root))
                self.extractions.append(nup)
                (target / "exefs").mkdir(parents=True)
                (target / "exefs" / "main").write_bytes(module_bytes(supported=supported))
                if failure:
                    (target / "romfs").mkdir()
                    (target / "romfs" / "asset.txt.part").write_bytes(b"incomplete authored asset")
                    make_game.fail(failure)
                if include_romfs:
                    (target / "romfs").mkdir()
                    (target / "romfs" / "asset.txt").write_bytes(b"new authored assets")
                    (target / "romfs" / "new-only.txt").write_bytes(b"new authored file")
                return
            if "nx2/lift.py" in cmd:
                raise Prepared
            self.fail("Unexpected build subprocess: %r" % cmd)

        argv = ["make_game.py", "--work", str(self.work)]
        if update:
            argv += ["--update", str(self.out)]
        elif folders:
            argv += ["--romfs", str(folders[0]), "--exefs", str(folders[1]), "--out", str(self.out)]
        else:
            argv += ["--nup", str(nup), "--out", str(self.out)]
        # The only external operation exercised is authored extraction above; no compiler, SDK,
        # translation, power-state update or real game is involved.
        with contextlib.ExitStack() as stack:
            blocked = [
                stack.enter_context(mock.patch.object(make_game.subprocess, "Popen",
                                                     side_effect=AssertionError("Unexpected process launch"))),
                stack.enter_context(mock.patch.object(os, "system",
                                                     side_effect=AssertionError("Unexpected shell command"))),
                stack.enter_context(mock.patch.object(os, "startfile", create=True,
                                                     side_effect=AssertionError("Unexpected file launch"))),
            ]
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(mock.patch.object(make_game, "check_windows_sdk"))
            stack.enter_context(mock.patch.object(make_game, "stop_stray_compilers"))   # (Windows: powershell, taskkill)
            stack.enter_context(mock.patch.object(make_game, "drop_stale_objects"))
            stack.enter_context(mock.patch.object(make_game, "no_throttle"))
            stack.enter_context(mock.patch("ctypes.WinDLL", create=True))
            stack.enter_context(mock.patch.object(make_game, "run", side_effect=run))
            output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            try:
                make_game.main()
            finally:
                self.output = output.getvalue()
                for launch in blocked:
                    launch.assert_not_called()

    def test_failed_scratch_exefs_cleanup_stops_before_copy_or_extraction(self):
        scratch = self.work / "exefs"
        scratch.mkdir()
        stale = scratch / "locked"
        stale.write_bytes(b"authored stale module")
        before = self.cache()
        remove = shutil.rmtree

        def remove_with_lock(path, *args, **kwargs):
            if Path(path) == scratch:
                if not kwargs.get("ignore_errors"):
                    raise PermissionError(errno.EACCES, "authored locked file", str(stale))
                return
            return remove(path, *args, **kwargs)

        rename = os.rename

        def rename_locked(src, dst, *args, **kwargs):   # (clear_folder's last resort, moving the folder aside, held too)
            if Path(src) == scratch:
                raise PermissionError(errno.EACCES, "authored locked file", str(stale))
            return rename(src, dst, *args, **kwargs)

        for update in (True, False):
            with self.subTest(update=update), mock.patch.object(shutil, "rmtree", side_effect=remove_with_lock), \
                    mock.patch.object(os, "rename", side_effect=rename_locked), mock.patch.object(make_game.time, "sleep"):
                with self.assertRaises(SystemExit) as result:
                    self.run_to_lift(self.new_nup, update=update)
                self.assertEqual(result.exception.code, 1)
                self.assertIn("@@error Could not clear", self.output)
                self.assertIn(str(scratch), self.output)
                self.assertIn("authored locked file", self.output)
                self.assertEqual(self.extractions, [])
                self.assertEqual(self.cache(), before)
                self.assertEqual(stale.read_bytes(), b"authored stale module")

    def test_update_replaces_clearable_scratch_exefs(self):
        scratch = self.work / "exefs"
        scratch.mkdir()
        stale = scratch / "stale"
        stale.write_bytes(b"authored stale module")
        before = self.cache()
        with self.assertRaises(Prepared):
            self.run_to_lift(None, update=True)
        self.assertFalse(stale.exists())
        self.assertEqual(self.extractions, [])
        after = self.cache()
        # (the one file added: the damaged-texture check's note that this unpack was checked, nup.stand_in_damaged)
        self.assertEqual(after.pop(".hookshot_romfs_checked", None), before[".hookshot_romfs"])
        self.assertEqual(after, before)
        self.assertEqual((scratch / "main").read_bytes(), (self.out / ".hookshot_exefs/main").read_bytes())

    def test_changed_source_replaces_romfs_and_exefs_together(self):
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual((self.out / "romfs" / "asset.txt").read_bytes(), b"new authored assets")
        self.assertTrue((self.out / "romfs" / "new-only.txt").is_file())
        self.assertEqual((self.out / ".hookshot_exefs" / "main").read_bytes(), module_bytes())
        self.assertEqual(self.marker.read_text(), self.stamp(self.new_nup) + "\n")
        self.assertEqual((self.out / "user/save/sentinel.txt").read_bytes(), b"authored save sentinel")

    def test_same_source_reuses_the_cache(self):
        before = self.cache()
        with self.assertRaises(Prepared):
            self.run_to_lift(self.old_nup)
        self.assertEqual(self.extractions, [])
        after = self.cache()
        # (the one file added: the damaged-texture check's note that this unpack was checked, nup.stand_in_damaged)
        self.assertEqual(after.pop(".hookshot_romfs_checked", None), before[".hookshot_romfs"])
        self.assertEqual(after, before)
        self.assertEqual((self.work / "exefs/main").read_bytes(),
                         (self.out / ".hookshot_exefs/main").read_bytes())

    def test_failed_extraction_preserves_the_previous_cache_and_save(self):
        before = self.cache()
        failure = "nup.py stopped (exit status 1): OSError: [Errno 28] No space left on device"
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, failure=failure)
        self.assertEqual(result.exception.code, 1)
        self.assertIn("@@error " + failure, self.output)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual(self.cache(), before)
        self.assertFalse((self.out / ".game").exists())

    def test_unsupported_build_preserves_the_previous_cache_and_save(self):
        before = self.cache()
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, supported=False)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual(result.exception.code, 1)
        self.assertIn("This is build 01234567. Hookshot supports build %s." % make_game.BUILD_ID, self.output)
        self.assertEqual(self.cache(), before)
        self.assertFalse((self.out / ".game").exists())

    def test_missing_romfs_preserves_the_previous_cache_and_save(self):
        before = self.cache()
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, include_romfs=False)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual(result.exception.code, 1)
        self.assertIn("The package did not contain a romfs folder.", self.output)
        self.assertEqual(self.cache(), before)
        self.assertFalse((self.out / ".game").exists())

    def test_reparse_cache_is_rejected_before_extraction_or_replacement(self):
        before = self.cache()
        original_lstat = os.lstat

        def reparse_romfs(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            if Path(path).absolute() != self.out / "romfs":
                return result

            class ReparseStat:
                st_file_attributes = getattr(result, "st_file_attributes", 0) | 0x400

                def __getattr__(self, name):
                    return getattr(result, name)

            return ReparseStat()

        source_romfs = self.root / "source-romfs"
        source_romfs.mkdir()
        (source_romfs / "new.bin").write_bytes(b"authored source asset")
        source_exefs = self.root / "source-exefs"
        source_exefs.mkdir()
        (source_exefs / "main").write_bytes(module_bytes())
        for folders in (None, (source_romfs, source_exefs)):
            with self.subTest(folders=folders), mock.patch.object(os, "lstat", side_effect=reparse_romfs):
                with self.assertRaises(SystemExit) as result:
                    self.run_to_lift(self.new_nup, folders=folders)
                self.assertEqual(result.exception.code, 1)
                self.assertIn("not a normal path inside the build folder", self.output)
                self.assertFalse((self.work / "exefs").exists())
                self.assertEqual(self.extractions, [])
                self.assertEqual(self.cache(), before)


class RomfsCopyTests(unittest.TestCase):
    def test_interrupted_cross_volume_copy_can_be_retried(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-romfs-copy-") as folder:
            src, dst = Path(folder) / "source", Path(folder) / "destination"
            src.mkdir()
            dst.mkdir()
            payload = b"complete authored asset"
            (src / "asset.bin").write_bytes(payload)
            (src / "existing.bin").write_bytes(b"source asset")
            (dst / "existing.bin").write_bytes(b"existing destination asset")

            def run_out_of_space(source, target):
                Path(target).write_bytes(Path(source).read_bytes()[:4])
                raise OSError(errno.ENOSPC, "authored disk-full failure")

            with mock.patch.object(make_game.os, "link", side_effect=OSError(errno.EXDEV, "different volumes")), \
                    contextlib.redirect_stdout(io.StringIO()):
                with mock.patch.object(make_game.shutil, "copy2", side_effect=run_out_of_space):
                    with self.assertRaises(OSError) as failure:
                        make_game.link_or_copy(src, dst)
                self.assertEqual(failure.exception.errno, errno.ENOSPC)
                self.assertEqual({p.name for p in dst.iterdir()}, {"existing.bin"})
                make_game.link_or_copy(src, dst)

            self.assertEqual((dst / "asset.bin").read_bytes(), payload)
            self.assertEqual((dst / "existing.bin").read_bytes(), b"existing destination asset")
            self.assertEqual({p.name for p in dst.iterdir()}, {"asset.bin", "existing.bin"})

    def test_failed_replacement_removes_the_staged_read_only_copy(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-romfs-replace-") as folder:
            src, dst = Path(folder) / "source", Path(folder) / "destination"
            src.mkdir()
            source = src / "asset.bin"
            source.write_bytes(b"authored read-only asset")
            source.chmod(stat.S_IREAD)
            with mock.patch.object(make_game.os, "link", side_effect=OSError(errno.EXDEV, "different volumes")), \
                    mock.patch.object(make_game.os, "replace", side_effect=PermissionError("authored replacement failure")):
                with self.assertRaisesRegex(PermissionError, "authored replacement failure"):
                    make_game.link_or_copy(src, dst)
            self.assertEqual(list(dst.iterdir()), [])
            self.assertEqual(source.read_bytes(), b"authored read-only asset")
            self.assertFalse(source.stat().st_mode & stat.S_IWRITE)

    def test_links_in_an_extracted_dump_are_refused(self):
        # (a link in --romfs or --exefs was followed: the file it named was hard-linked or copied into the game folder)
        with tempfile.TemporaryDirectory(prefix="hookshot-dump-links-") as folder:
            src, secret = Path(folder) / "romfs", Path(folder) / "secret"
            (src / "Model").mkdir(parents=True)
            (src / "Model" / "a.zs").write_bytes(b"game data")
            secret.write_bytes(b"not the game's")
            make_game.refuse_dump_links(src)   # (plain files and folders)
            for name, target in (("b.zs", secret), ("Link", Path(folder))):
                link = src / "Model" / name
                try:
                    link.symlink_to(target)
                except OSError:
                    self.skipTest("no symbolic links here")
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                    make_game.refuse_dump_links(src)
                link.unlink()

    # ---- (11-21, the performance audit's IO-41) the link check from the folders' listings, each folder made once ----

    def test_the_link_check_asks_no_file_one_by_one(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-dump-listing-") as folder:
            src = Path(folder) / "romfs"
            (src / "Model" / "Deep" / "er").mkdir(parents=True)
            for name in ("a.zs", "Model/b.zs", "Model/Deep/c.zs", "Model/Deep/er/d.zs"):
                (src / name).write_bytes(b"game data")
            with mock.patch.object(make_game.os, "lstat", side_effect=AssertionError("an os.lstat for one entry")), \
                    mock.patch.object(make_game.os, "walk", side_effect=AssertionError("os.walk passes over what it cannot list")):
                make_game.refuse_dump_links(src)
            with mock.patch.dict(os.environ, {"HOOKSHOT_DUMP_LINKS_LSTAT": "1"}), \
                    mock.patch.object(make_game.os, "lstat", side_effect=AssertionError("asked")):
                with self.assertRaisesRegex(AssertionError, "asked"):   # (the switch: as before)
                    make_game.refuse_dump_links(src)

    def test_a_link_three_folders_down_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-dump-deep-") as folder:
            src, outside = Path(folder) / "romfs", Path(folder) / "outside"
            deep = src / "Model" / "Deep" / "er"
            deep.mkdir(parents=True)
            outside.mkdir()
            (outside / "secret").write_bytes(b"not the game's")
            (deep / "d.zs").write_bytes(b"game data")
            make_game.refuse_dump_links(src)
            made = 0
            try:
                (deep / "link.zs").symlink_to(outside / "secret")
                made += 1
            except OSError:
                pass
            else:
                with contextlib.redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
                    make_game.refuse_dump_links(src)
                self.assertIn("contain a link", said.getvalue())
                (deep / "link.zs").unlink()
            if os.name == "nt":   # (a junction needs no privilege: a folder that is a reparse point)
                import subprocess
                junction = deep / "Junction"
                if subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True).returncode == 0:
                    made += 1
                    with contextlib.redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
                        make_game.refuse_dump_links(src)
                    self.assertIn("contain a link", said.getvalue())
                    self.assertIn("Junction", said.getvalue())
                    os.rmdir(junction)
            if not made:
                self.skipTest("neither symbolic links nor junctions here")
            make_game.refuse_dump_links(src)   # (with the links gone: plain again)

    def test_a_folder_that_cannot_be_listed_stops_the_build(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-dump-unlisted-") as folder:
            src = Path(folder) / "romfs"
            (src / "Model" / "Locked").mkdir(parents=True)
            (src / "Model" / "a.zs").write_bytes(b"game data")
            real = os.scandir

            def listing(path):
                if os.path.basename(str(path)) == "Locked":
                    raise PermissionError(errno.EACCES, "authored: access denied")
                return real(path)
            with mock.patch.object(make_game.os, "scandir", side_effect=listing), \
                    contextlib.redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
                make_game.refuse_dump_links(src)
            self.assertIn("Could not read the game files at", said.getvalue())
            self.assertIn("Locked", said.getvalue())

    def test_the_copy_makes_each_folder_once_and_asks_for_no_target(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-romfs-walk-") as folder:
            src, dst = Path(folder) / "source", Path(folder) / "destination"
            (src / "Model" / "Deep").mkdir(parents=True)
            names = ["top.bin"] + ["Model/m%d.bin" % i for i in range(40)] + ["Model/Deep/d%d.bin" % i for i in range(40)]
            for name in names:
                (src / name).write_bytes(name.encode())
            real_makedirs, made = os.makedirs, []

            def makedirs(path, *a, **k):
                made.append(os.path.normcase(str(path)))
                return real_makedirs(path, *a, **k)
            real_exists = os.path.exists

            def exists(path):   # (os.makedirs asks about folders itself: only a file's target counts)
                if str(path).endswith(".bin"):
                    raise AssertionError("asked whether a target exists: " + str(path))
                return real_exists(path)
            with mock.patch.object(make_game.os, "makedirs", side_effect=makedirs), \
                    mock.patch.object(make_game.os.path, "exists", side_effect=exists), \
                    contextlib.redirect_stdout(io.StringIO()):
                make_game.link_or_copy(src, dst)
            self.assertEqual(len(made), 3, "one makedirs a folder, not one a file: %r" % made)
            self.assertEqual(len(set(made)), 3)
            for name in names:   # (the top folder's files and the nested ones: the same file, not a copy)
                self.assertTrue(os.path.samefile(src / name, dst / name), name)
            with contextlib.redirect_stdout(io.StringIO()):
                make_game.link_or_copy(src, dst)   # (again over what is there: every link says it exists, and is passed over)
            self.assertEqual(sorted(p.name for p in dst.iterdir()), ["Model", "top.bin"])


if __name__ == "__main__":
    unittest.main()
