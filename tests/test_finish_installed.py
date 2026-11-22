"""The finish passes over files the game folder already has from the same source (nx2/make_game.py INSTALLED_NOTE).

(Triforce, 11-22, the performance audit's IO-45, after Source A's.) Every build copied every file into the game folder
as <name>.new and swapped it in: the exe, the renderer, the prebuilt DLLs and image.bin, changed or not. The finish now
notes, per installed file, its source's SHA-1 and the installed copy's size, time, file number and mode, and the next
finish passes over a file whose source hashes the same and whose installed copy is still as noted. The installed file
is never read. HOOKSHOT_FINISH_COPY_ALL=1 copies everything and keeps no note, as before.

Runs the production finish statements themselves (tests/test_finish_output.py's finish_statements cuts them out of
main()) on made-up files in a temporary folder:
  - a first finish copies everything and writes the note; a second with the same sources calls neither shutil.copy2 nor
    os.replace, opens no installed file, and leaves the files and the note as they were;
  - a changed source is copied, alone, also when its size and time are the old ones; a source only touched is not;
  - an installed file changed by hand, a note that is broken or of another format, a file the note does not have, and a
    file system that gives no file number (st_ino 0) all copy;
  - the launcher layout (the game in bin, the launcher beside it) is passed over file by file;
  - a <name>.new left beside a file that is passed over is removed, and a read-only one is left locked;
  - a swap that is refused leaves no note saying the new file is there, and the retry installs it;
  - the switch copies everything and removes the note;
  - after every finish the installed files are the sources byte for byte.

The exe and the renderer are linked again at every build, and lld writes the link's time into them, so they are still
copied. HOOKSHOT_LINK_REPRO=1 (nx2/build.py repro_link, off unless asked: it changes the linked files' bytes) adds
/Brepro to those two links. Checked here: the rule and its two hooks, and, with --cc, that two links of one tiny object
a second apart are the same bytes with the flag and are not without it.

    python -I -B tests/test_finish_installed.py [--cc clang]
"""
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "clang"]
sys.path.insert(0, str(ROOT / "tests"))
from test_finish_output import FINISH, make_game   # (the production statements, and the module they came from)


class NoNumber:
    """An os.stat result on a file system that gives no file number"""
    def __init__(self, result):
        self._result = result

    st_ino = 0

    def __getattr__(self, name):
        return getattr(self._result, name)


class FinishInstalled(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="triforce-finish-installed-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.addCleanup(self.unlock)
        self.work, self.out = self.root / "work", self.root / "game"
        self.built = self.work / "sa" / "build"
        self.built.mkdir(parents=True)
        self.out.mkdir()
        (self.work / "sa" / "image").mkdir()
        self.exe, self.dll = self.built / "Triforce.exe", self.built / "triforce_vk.dll"
        self.image = self.work / "sa" / "image" / "image.bin"
        self.exe.write_bytes(b"a made-up executable")
        self.dll.write_bytes(b"a made-up renderer")
        self.image.write_bytes(b"a made-up image")
        self.sources = {"Triforce.exe": self.exe, "triforce_vk.dll": self.dll, "image.bin": self.image}
        self.note = self.out / make_game.INSTALLED_NOTE
        environ = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_FINISH_COPY_ALL"}
        patched = mock.patch.dict(os.environ, environ, clear=True)
        patched.start()
        self.addCleanup(patched.stop)

    def unlock(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)

    def finish(self, launcher=False):
        """The production finish; returns (the sources copied, the targets swapped in, what it printed)"""
        if launcher:
            (self.root / "HookshotBuilder-Setup.exe").write_bytes(b"a made-up launcher")
        copied, swapped, said = [], [], io.StringIO()
        copy2, replace = make_game.shutil.copy2, os.replace

        def copy(src, dst):
            copied.append(Path(src).name)
            return copy2(src, dst)

        def swap(src, dst):
            swapped.append(Path(dst).name)
            return replace(src, dst)

        with mock.patch.object(make_game, "BESIDE", ["Triforce.exe", "triforce_vk.dll"]), \
                mock.patch.object(make_game.shutil, "copy2", side_effect=copy), \
                mock.patch.object(make_game.os, "replace", side_effect=swap), contextlib.redirect_stdout(said):
            namespace = dict(make_game.__dict__, built=str(self.built), out=str(self.out), work=str(self.work),
                             ROOT=str(self.root / "tools"), LINUX=False if launcher else make_game.LINUX)
            exec(FINISH, namespace)
        return copied, swapped, said.getvalue()

    def assert_installed(self, folder=None):
        for name, source in self.sources.items():
            where = self.out / "image.bin" if name == "image.bin" else (folder or self.out) / name
            self.assertEqual(where.read_bytes(), source.read_bytes(), name)

    def test_second_finish_copies_and_swaps_nothing(self):
        copied, swapped, said = self.finish()
        self.assertEqual(copied, ["Triforce.exe", "triforce_vk.dll", "image.bin"])
        self.assertEqual(swapped, ["Triforce.exe", "triforce_vk.dll", "image.bin", make_game.INSTALLED_NOTE])
        self.assert_installed()
        note = json.loads(self.note.read_text(encoding="utf-8"))
        self.assertEqual(sorted(note["files"]), ["Triforce.exe", "image.bin", "triforce_vk.dll"])
        self.assertEqual(note["files"]["Triforce.exe"]["sha1"], make_game.file_sha1(str(self.exe)))
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in self.out.iterdir()}
        opened = []
        real_open = open

        def watch(path, *a, **k):
            opened.append(os.path.normcase(os.path.abspath(path)))
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", side_effect=watch):
            copied, swapped, said = self.finish()
        self.assertEqual((copied, swapped), ([], []))
        self.assertIn("the game folder has 3 of this build's 3 files already", said)
        # (the installed files are never read: only the sources, for their hashes, and the note)
        inside = [p for p in opened if p.startswith(os.path.normcase(str(self.out)) + os.sep)]
        self.assertEqual(inside, [os.path.normcase(str(self.note))])
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in self.out.iterdir()})

    def test_changed_source_is_copied_alone(self):
        self.finish()
        self.dll.write_bytes(b"a made-up renderer, built again")
        copied, swapped, said = self.finish()
        self.assertEqual(copied, ["triforce_vk.dll"])
        self.assertEqual(swapped, ["triforce_vk.dll", make_game.INSTALLED_NOTE])
        self.assertIn("2 of this build's 3 files already (Triforce.exe, image.bin)", said)
        self.assert_installed()
        self.assertEqual(self.finish()[:2], ([], []))

    def test_changed_source_of_the_same_size_and_time_is_copied(self):
        self.finish()
        times = self.exe.stat()
        self.exe.write_bytes(b"A MADE-UP EXECUTABLE")   # (the same length)
        os.utime(self.exe, ns=(times.st_atime_ns, times.st_mtime_ns))
        self.assertEqual(self.finish()[0], ["Triforce.exe"])
        self.assert_installed()

    def test_touched_source_is_not_copied(self):
        self.finish()
        times = self.image.stat()
        os.utime(self.image, ns=(times.st_atime_ns, times.st_mtime_ns + 5_000_000_000))
        self.assertEqual(self.finish()[:2], ([], []))

    def test_installed_file_changed_by_hand_is_copied(self):
        self.finish()
        (self.out / "image.bin").write_bytes(b"another image, longer than the one installed")
        self.assertEqual(self.finish()[0], ["image.bin"])
        self.assert_installed()
        # the same length, written later: its time is not the noted one
        installed = self.out / "Triforce.exe"
        times = installed.stat()
        installed.write_bytes(b"x" * times.st_size)
        os.utime(installed, ns=(times.st_atime_ns, times.st_mtime_ns + 2_000_000_000))
        self.assertEqual(self.finish()[0], ["Triforce.exe"])
        self.assert_installed()
        # deleted
        (self.out / "triforce_vk.dll").unlink()
        self.assertEqual(self.finish()[0], ["triforce_vk.dll"])
        self.assert_installed()

    def test_broken_or_foreign_note_copies_everything(self):
        self.finish()
        good = self.note.read_text(encoding="utf-8")
        for text in ("", "{ not json", "[1, 2]", json.dumps({"format": 2, "files": json.loads(good)["files"]}),
                     json.dumps({"format": 1, "files": [1]}), json.dumps({"format": 1, "files": {"Triforce.exe": "x"}})):
            with self.subTest(note=text[:24]):
                self.note.write_text(text, encoding="utf-8")
                self.assertEqual(self.finish()[0], ["Triforce.exe", "triforce_vk.dll", "image.bin"])
                self.assert_installed()
                self.assertEqual(self.finish()[:2], ([], []))
        self.note.unlink()   # (deleting the note copies everything)
        self.assertEqual(self.finish()[0], ["Triforce.exe", "triforce_vk.dll", "image.bin"])

    def test_file_the_note_does_not_have_is_copied(self):
        self.finish()
        note = json.loads(self.note.read_text(encoding="utf-8"))
        del note["files"]["image.bin"]
        self.note.write_text(json.dumps(note), encoding="utf-8")
        self.assertEqual(self.finish()[0], ["image.bin"])
        self.assertEqual(sorted(json.loads(self.note.read_text(encoding="utf-8"))["files"]),
                         ["Triforce.exe", "image.bin", "triforce_vk.dll"])

    def test_no_file_number_always_copies(self):
        real = os.stat
        with mock.patch.object(make_game.os, "stat", side_effect=lambda p, *a, **k: NoNumber(real(p, *a, **k))):
            self.assertIsNone(make_game.installed_stat(str(self.exe)))
            for _ in range(2):
                self.assertEqual(self.finish()[0], ["Triforce.exe", "triforce_vk.dll", "image.bin"])
        self.assert_installed()
        self.assertFalse(self.note.exists() and json.loads(self.note.read_text(encoding="utf-8"))["files"])

    def test_launcher_layout_is_passed_over_file_by_file(self):
        copied, swapped, said = self.finish(launcher=True)
        self.assertEqual(copied, ["Triforce.exe", "triforce_vk.dll", "image.bin", "HookshotBuilder-Setup.exe"])
        self.assertEqual((self.out / "Triforce.exe").read_bytes(), b"a made-up launcher")
        self.assert_installed(self.out / "bin")
        note = json.loads(self.note.read_text(encoding="utf-8"))["files"]
        self.assertEqual(sorted(note), ["Triforce.exe", "bin/Triforce.exe", "bin/triforce_vk.dll", "image.bin"])
        self.assertEqual(self.finish(launcher=True)[:2], ([], []))
        self.exe.write_bytes(b"a made-up executable, built again")
        copied, swapped, said = self.finish(launcher=True)
        self.assertEqual(copied, ["Triforce.exe"])
        self.assertEqual((self.out / "Triforce.exe").read_bytes(), b"a made-up launcher")   # (the launcher: passed over)
        self.assert_installed(self.out / "bin")

    def test_leftover_new_beside_a_passed_over_file_goes_unless_locked(self):
        self.finish()
        left = self.out / "image.bin.new"
        left.write_bytes(b"an interrupted build's copy")
        self.assertEqual(self.finish()[:2], ([], []))
        self.assertFalse(left.exists())
        if os.name == "nt":   # (a read-only file is not deleted there, and the finish never unlocks one)
            left.write_bytes(b"an interrupted build's copy")
            left.chmod(stat.S_IREAD)
            with mock.patch.object(make_game.os, "chmod", wraps=os.chmod) as chmod:
                self.assertEqual(self.finish()[:2], ([], []))
            chmod.assert_not_called()
            self.assertEqual(left.read_bytes(), b"an interrupted build's copy")
            self.assertFalse(left.stat().st_mode & stat.S_IWRITE)

    def test_refused_swap_notes_nothing_and_the_retry_installs(self):
        self.finish()
        old_note = self.note.read_text(encoding="utf-8")
        self.exe.write_bytes(b"a made-up executable, built again")
        said = io.StringIO()
        with mock.patch.object(make_game, "BESIDE", ["Triforce.exe", "triforce_vk.dll"]), \
                mock.patch.object(make_game.os, "replace", side_effect=PermissionError("a made-up refusal")), \
                contextlib.redirect_stdout(said), self.assertRaises(SystemExit):
            exec(FINISH, dict(make_game.__dict__, built=str(self.built), out=str(self.out), work=str(self.work),
                              ROOT=str(self.root / "tools")))
        self.assertIn("@@error Could not replace", said.getvalue())
        self.assertEqual(self.note.read_text(encoding="utf-8"), old_note)
        self.assertEqual((self.out / "Triforce.exe").read_bytes(), b"a made-up executable")
        copied, swapped, said = self.finish()
        self.assertEqual(copied, ["Triforce.exe"])
        self.assert_installed()

    def test_switch_copies_everything_and_keeps_no_note(self):
        self.finish()
        self.assertTrue(self.note.exists())
        with mock.patch.dict(os.environ, {"HOOKSHOT_FINISH_COPY_ALL": "1"}):
            for _ in range(2):
                copied, swapped, said = self.finish()
                self.assertEqual(copied, ["Triforce.exe", "triforce_vk.dll", "image.bin"])
                self.assertEqual(swapped, ["Triforce.exe", "triforce_vk.dll", "image.bin"])
                self.assertFalse(self.note.exists())
                self.assertNotIn("not copied again", said)
        self.assert_installed()
        with mock.patch.dict(os.environ, {"HOOKSHOT_FINISH_COPY_ALL": "0"}):
            self.assertEqual(len(self.finish()[0]), 3)
            self.assertEqual(self.finish()[:2], ([], []))

    def test_helpers(self):
        self.assertEqual(make_game.file_sha1(str(self.exe)), hashlib.sha1(b"a made-up executable").hexdigest())
        self.assertIsNone(make_game.file_sha1(str(self.root / "missing")))
        self.assertIsNone(make_game.installed_stat(str(self.root / "missing")))
        self.assertIsNone(make_game.installed_stat(str(self.out)))   # (a folder is no installed file)
        st = self.exe.stat()
        self.assertEqual(make_game.installed_stat(str(self.exe)), [st.st_size, st.st_mtime_ns, st.st_ino, st.st_mode])
        self.assertEqual(make_game.installed_name(str(self.out), str(self.out / "bin" / "Triforce.exe")), "bin/Triforce.exe")
        self.assertEqual(make_game.read_installed(str(self.out)), {})
        note = {"Triforce.exe": {"sha1": "abc", "stat": make_game.installed_stat(str(self.exe))}}
        self.assertFalse(make_game.installed_same(note, str(self.built), str(self.exe), None))
        self.assertFalse(make_game.installed_same(note, str(self.built), str(self.exe), "abd"))
        self.assertTrue(make_game.installed_same(note, str(self.built), str(self.exe), "abc"))
        self.assertFalse(make_game.installed_same({}, str(self.built), str(self.exe), "abc"))

    def test_source_and_docs(self):
        source = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        main = source[source.index("def main(a=None):"):]
        for needle in ('copy_all = os.environ.get("HOOKSHOT_FINISH_COPY_ALL", "0") not in ("", "0")',
                       "installed_note = {} if copy_all else read_installed(out)",
                       "if installed_same(installed_note, out, dst, digest):",
                       "write_installed(out, installed_now)"):
            self.assertTrue(needle in main, needle)
        self.assertTrue(main.index("if installed_same(installed_note, out, dst, digest):") <
                        main.index("shutil.copy2(src, dst + \".new\")") < main.index("write_installed(out, installed_now)"))
        self.assertEqual(make_game.INSTALLED_NOTE, ".triforce_installed.json")
        docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
        rows = [line for line in docs.splitlines() if line.startswith("| `HOOKSHOT_FINISH_COPY_ALL=1` |")]
        self.assertEqual(len(rows), 1)
        self.assertTrue("IO-45" in rows[0] and ".triforce_installed.json" in rows[0])


class ReproLink(unittest.TestCase):
    """nx2/build.py repro_link: HOOKSHOT_LINK_REPRO=1 takes the link's time out of the exe and the renderer (off unless
    asked: it changes the linked files' bytes), so that the finish above can pass an unchanged exe over"""

    def rule(self, link_opt=lambda o: "<" + o + ">"):
        source = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "repro_link"]
        scope = {"os": os, "LINUX": False, "toolchain": types.SimpleNamespace(link_opt=link_opt)}
        exec(compile(ast.Module(body=function, type_ignores=[]), "build.py", "exec"), scope)
        return scope["repro_link"], source

    def test_rule_and_hooks(self):
        repro, source = self.rule()
        self.assertEqual(repro(""), [])
        self.assertEqual(repro("0"), [])
        self.assertEqual(repro("yes"), [])
        self.assertEqual(repro("1"), ["</Brepro>"])
        self.assertEqual(repro("1", linux=True), [])
        with mock.patch.dict(os.environ, {"HOOKSHOT_LINK_REPRO": "1"}):
            self.assertEqual(repro(), ["</Brepro>"])
        environ = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_LINK_REPRO"}
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertEqual(repro(), [])   # (the default: the link is the command it was)
        # the two Windows links that the finish installs ask it: the exe's and the renderer's
        self.assertEqual(source.count("repro_link()"), 2)
        exe = source[source.index('exe = os.path.join(out, "Triforce.exe")'):]
        self.assertTrue("repro_link() +" in exe[:exe.index("capture_output=True")])
        dll = source[source.index('["-shared", "-o", vdll, toolchain.link_opt("/map:" + vdll[:-4] + ".map")'):]
        self.assertTrue("+ repro_link()" in dll[:dll.index("\n")])
        docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
        self.assertEqual(len([l for l in docs.splitlines() if l.startswith("| `HOOKSHOT_LINK_REPRO=1` |") and "IO-45" in l]), 1)

    def test_two_links_of_one_object_are_the_same_bytes_only_with_the_flag(self):
        cc = CC and shutil.which(CC)
        if os.name != "nt" or not cc:
            self.skipTest("needs --cc <an llvm-mingw clang> on Windows")
        target = subprocess.run([cc, "-dumpmachine"], capture_output=True, text=True).stdout.strip()
        if "windows-gnu" not in target and "mingw" not in target:
            self.skipTest("not llvm-mingw: %s" % target)
        repro, _ = self.rule(lambda o: "-Wl,-Xlink=" + o)   # (toolchain.link_opt's form for llvm-mingw)
        with tempfile.TemporaryDirectory(prefix="triforce-repro-link-") as folder:
            source = os.path.join(folder, "tiny.c")
            with open(source, "w") as f:
                f.write("int main(void) { return 0; }\n")
            subprocess.run([cc, "-c", source, "-o", os.path.join(folder, "tiny.o")], check=True)

            def link(flags):
                digests = []
                for i in range(2):
                    exe = os.path.join(folder, "tiny.exe")
                    subprocess.run([cc, os.path.join(folder, "tiny.o"), "-o", exe] + flags, check=True)
                    digests.append(make_game.file_sha1(exe))
                    os.remove(exe)
                    if i == 0:
                        time.sleep(1.2)   # (the link's time is in whole seconds)
                return digests

            first, second = link(repro("1"))
            self.assertEqual(first, second)
            first, second = link(repro("0"))
            self.assertNotEqual(first, second, "this linker writes no link time: the switch has nothing to do")


CC = None

if __name__ == "__main__":
    if "--cc" in sys.argv:
        at = sys.argv.index("--cc")
        CC = sys.argv[at + 1]
        del sys.argv[at:at + 2]
    unittest.main()
