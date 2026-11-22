"""Game-free: a package's unpack writes each member in place and looks at each folder once (nx2/nup.py extract,
Destination).

(Triforce, 11-22, the performance audit's IO-51, after Source A's.) extract wrote every member to <member>.part and
renamed it, and extraction_path resolved the output folder and looked at every folder above the member for every one of
the game's 186,583 members. Under a virus scanner on NTFS those creates, renames and looks were most of a small member's
cost.

On made-up packages in a temporary folder:
  - a fresh unpack calls no os.replace, makes no <member>.part, unlinks nothing, and asks os.lstat once for each folder
    and once for each member; the old loop asks more than that and renames every member;
  - the files and the .zs notes are the same as the old loop's, byte for byte, nested and non-ASCII names included;
  - a member that is there whole is kept and not opened for writing (its .zs head is read back);
  - a member whose write fails is removed, and the next run writes it;
  - a short member is written again;
  - a hard-linked member of another size is replaced and its twin keeps its data;
  - a file that appears between the look and the create is not written over (the create is exclusive);
  - a <member>.part an older run left in a folder that was there is removed; a link is refused as before;
  - HOOKSHOT_NUP_IN_PLACE=0 brings the old loop back, and the switches table says so.

    python -I -B nx2/test_nup_in_place.py
"""
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nup

ZSTD = b"\x28\xb5\x2f\xfd"


class Package:
    """Made-up members: name -> bytes."""
    def __init__(self, members):
        self.members = dict(members)

    def walk(self, directory):
        for name, data in self.members.items():
            yield name, (name, 0, len(data), 0, len(data))

    def copy_to(self, record, output, name):
        output.write(self.members[name][:5])
        output.write(self.members[name][5:])


MEMBERS = {
    "Model/Forest/tree.bfres.zs": ZSTD + b"a tree" * 9,
    "Model/Forest/rock.bfres.zs": b"\0\0\0\0 a damaged file",
    "Model/Forest/Deep/leaf.bin": b"leaf",
    "Model/empty.bin": b"",
    "Text/Français.msbt.zs": b"\x50\x2a\x4d\x18 a skippable frame",
    "top.bin": b"top level",
    ".hidden": b"h",
}
FOLDERS = {"", "Model", "Model/Forest", "Model/Forest/Deep", "Text"}   # (under romfs; "" is romfs itself)


def tree(root):
    out = {}
    for folder, dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, root).replace(os.sep, "/")] = f.read()
    return out


def plain(path):
    """A path without Windows' extended-length prefix, in one case, to compare what os.lstat was asked"""
    path = os.path.normcase(os.path.abspath(path))
    return path[4:] if path.startswith("\\\\?\\") else path


class InPlace(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(os.path.realpath(self.temporary.name))
        self.out = self.root / "out"
        self.out.mkdir()
        self.assertTrue(nup.IN_PLACE)

    def extract(self, members=MEMBERS, out=None, zs=None):
        return nup.extract(Package(members), {"romfs": 0}, str(out or self.out), only="romfs", quiet=True, zs=zs)

    def test_fresh_unpack_one_look_each_and_no_rename(self):
        asked = []
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            asked.append(plain(path))
            return real_lstat(path, *args, **kwargs)

        with patch.object(nup.os, "lstat", side_effect=lstat), \
                patch.object(nup.os, "replace", side_effect=AssertionError("a rename")) as replace, \
                patch.object(nup.os, "unlink", side_effect=AssertionError("an unlink")) as unlink:
            self.assertEqual(self.extract(), (len(MEMBERS), sum(len(d) for d in MEMBERS.values())))
        replace.assert_not_called()
        unlink.assert_not_called()   # (romfs was made by this run: no stale .part can be in it)
        base = plain(str(self.out / "romfs"))
        under = [p for p in asked if p == base or p.startswith(base + os.sep)]
        want = sorted(plain(str(self.out / "romfs" / f)) for f in FOLDERS) + \
            sorted(plain(str(self.out / "romfs" / m)) for m in MEMBERS)
        self.assertEqual(sorted(under), sorted(want))   # (each folder once, each member once, nothing twice)
        self.assertEqual(tree(self.out / "romfs"), MEMBERS)
        self.assertEqual([p for p in tree(self.out) if p.endswith(".part")], [])

    def test_the_old_loop_looks_more_and_renames(self):
        # (what the count above is compared with, and the switch back)
        asked = []
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            asked.append(plain(path))
            return real_lstat(path, *args, **kwargs)

        with patch.object(nup, "IN_PLACE", False), patch.object(nup.os, "lstat", side_effect=lstat), \
                patch.object(nup.os, "replace", wraps=os.replace) as replace:
            self.extract()
        self.assertEqual(replace.call_count, len(MEMBERS))
        base = plain(str(self.out / "romfs"))
        under = [p for p in asked if p == base or p.startswith(base + os.sep)]
        self.assertGreater(len(under), 2 * (len(FOLDERS) + len(MEMBERS)))
        self.assertEqual(tree(self.out / "romfs"), MEMBERS)

    def test_same_files_and_notes_as_the_old_loop(self):
        new, old = self.root / "new", self.root / "old"
        zs_new, zs_old = {}, {}
        counts_new = self.extract(out=new, zs=zs_new)
        with patch.object(nup, "IN_PLACE", False):
            counts_old = self.extract(out=old, zs=zs_old)
        self.assertEqual(counts_new, counts_old)
        self.assertEqual(tree(new), tree(old))
        self.assertEqual(tree(new), {"romfs/" + k: v for k, v in MEMBERS.items()})
        self.assertEqual(zs_new, zs_old)
        self.assertEqual(zs_new, dict(files=3, damaged=["Model/Forest/rock.bfres.zs"]))
        # and a second run over each: nothing written, the notes read back from the files
        again_new, again_old = {}, {}
        self.assertEqual(self.extract(out=new, zs=again_new), (0, 0))
        with patch.object(nup, "IN_PLACE", False):
            self.assertEqual(self.extract(out=old, zs=again_old), (0, 0))
        self.assertEqual(again_new, zs_new)
        self.assertEqual(again_old, zs_new)

    def test_whole_member_is_kept_and_not_opened_for_writing(self):
        self.extract()
        before = {p: os.stat(self.out / "romfs" / p).st_mtime_ns for p in MEMBERS}
        with patch.object(nup.os, "open", side_effect=AssertionError("a create")), \
                patch.object(nup.os, "unlink", wraps=os.unlink) as unlink:
            self.assertEqual(self.extract(), (0, 0))
        self.assertEqual(before, {p: os.stat(self.out / "romfs" / p).st_mtime_ns for p in MEMBERS})
        # (romfs was there this time: nothing was written, so no <member>.part was looked for either)
        unlink.assert_not_called()

    def test_failed_member_is_removed_then_written_on_retry(self):
        package = Package(MEMBERS)
        failing = "Model/Forest/rock.bfres.zs"
        real = package.copy_to

        def copy_to(record, output, name):
            if name == failing:
                output.write(b"half")
                raise OSError(errno.EIO, "a made-up read error")
            real(record, output, name)

        with patch.object(package, "copy_to", side_effect=copy_to), self.assertRaises(OSError) as error:
            nup.extract(package, {"romfs": 0}, str(self.out), only="romfs", quiet=True)
        self.assertEqual(error.exception.errno, errno.EIO)
        self.assertFalse((self.out / "romfs" / failing).exists())
        done = tree(self.out / "romfs")
        self.assertEqual(done, {k: v for k, v in MEMBERS.items() if k in done})   # (what was written is whole)
        n, total = nup.extract(package, {"romfs": 0}, str(self.out), only="romfs", quiet=True)
        self.assertEqual(n, len(MEMBERS) - len(done))
        self.assertEqual(tree(self.out / "romfs"), MEMBERS)

    def test_short_member_is_written_again(self):
        self.extract()
        short = self.out / "romfs" / "top.bin"
        short.write_bytes(b"top")
        long = self.out / "romfs" / "Model" / "Forest" / "Deep" / "leaf.bin"
        long.write_bytes(b"leaf and more than the package has")
        self.assertEqual(self.extract(), (2, len(b"top level") + len(b"leaf")))
        self.assertEqual(tree(self.out / "romfs"), MEMBERS)

    def test_hard_linked_member_is_replaced_and_its_twin_keeps_its_data(self):
        (self.out / "romfs").mkdir()
        twin = self.root / "twin.bin"
        twin.write_bytes(b"another file's data, of another size")
        os.link(twin, self.out / "romfs" / "top.bin")
        self.extract({"top.bin": b"top level"})
        self.assertEqual((self.out / "romfs" / "top.bin").read_bytes(), b"top level")
        self.assertEqual(twin.read_bytes(), b"another file's data, of another size")
        self.assertEqual(os.stat(twin).st_nlink, 1)

    def test_member_link_is_refused(self):
        (self.out / "romfs").mkdir()
        outside = self.root / "outside.bin"
        outside.write_bytes(b"keep outside data")
        try:
            os.symlink(outside, self.out / "romfs" / "top.bin")
        except OSError as error:
            self.skipTest("no symbolic links here: %s" % error)
        with self.assertRaisesRegex(SystemExit, "^extraction path is a link or reparse point: "):
            self.extract({"top.bin": b"top level"})
        self.assertEqual(outside.read_bytes(), b"keep outside data")
        self.assertTrue((self.out / "romfs" / "top.bin").is_symlink())

    def test_file_that_appears_after_the_look_is_not_written_over(self):
        (self.out / "romfs").mkdir()
        planted = self.out / "romfs" / "top.bin"
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            if plain(path) == plain(str(planted)):   # (the look sees nothing; then the file is there)
                planted.write_bytes(b"planted")
                raise FileNotFoundError(errno.ENOENT, "not there yet", str(path))
            return real_lstat(path, *args, **kwargs)

        with patch.object(nup.os, "lstat", side_effect=lstat), self.assertRaises(FileExistsError):
            self.extract({"top.bin": b"top level"})
        self.assertEqual(planted.read_bytes(), b"planted")

    def test_stale_part_in_a_folder_that_was_there_is_removed(self):
        (self.out / "romfs" / "Model").mkdir(parents=True)
        stale = self.out / "romfs" / "Model" / "empty.bin.part"
        stale.write_bytes(b"an interrupted older run")
        self.extract()
        self.assertFalse(stale.exists())
        self.assertEqual(tree(self.out / "romfs"), MEMBERS)

    def test_folder_that_is_a_file_stops_the_unpack(self):
        (self.out / "romfs").mkdir()
        (self.out / "romfs" / "Model").write_bytes(b"not a folder")
        with self.assertRaisesRegex(SystemExit, "^extraction path is not a folder: "):
            self.extract()
        self.assertEqual((self.out / "romfs" / "Model").read_bytes(), b"not a folder")

    def test_destination_checks_each_folder_once(self):
        where = nup.Destination(str(self.out / "new" / "deeper"))
        with patch.object(nup.os, "lstat", wraps=os.lstat) as lstat:
            first, fresh = where.member("romfs", "A/B/one.bin")
            calls = lstat.call_count
            second, fresh_again = where.member("romfs", "A/B/two.bin")
            self.assertEqual(lstat.call_count, calls)       # (the same folder: no further look)
            where.member("romfs", "A/C/three.bin")
            self.assertEqual(lstat.call_count, calls + 1)   # (one new folder: one look)
        self.assertTrue(fresh and fresh_again)
        self.assertEqual(os.path.dirname(first), os.path.dirname(second))
        self.assertTrue(os.path.isdir(self.out / "new" / "deeper" / "romfs" / "A" / "C"))
        with self.assertRaisesRegex(SystemExit, "^unsafe path in the package: "):
            where.member("romfs", "A/../../outside.bin")

    def test_switch_is_read_from_the_environment(self):
        for value, want in ((None, "True"), ("1", "True"), ("0", "False")):
            env = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_NUP_IN_PLACE"}
            if value is not None:
                env["HOOKSHOT_NUP_IN_PLACE"] = value
            said = subprocess.run([sys.executable, "-I", "-B", "-c",
                                   "import sys; sys.path.insert(0, sys.argv[1]); import nup; print(nup.IN_PLACE)", HERE],
                                  env=env, capture_output=True, text=True)
            self.assertEqual(said.stdout.strip(), want, said.stderr)

    def test_source_and_docs(self):
        source = Path(HERE, "nup.py").read_text(encoding="utf-8")
        extract = source[source.index("def extract("):source.index("def heal(")]
        self.assertIn("where = Destination(out) if IN_PLACE else None", extract)
        self.assertIn("os.O_WRONLY | os.O_CREAT | os.O_EXCL", extract)
        self.assertIn('IN_PLACE = os.environ.get("HOOKSHOT_NUP_IN_PLACE", "1") != "0"', source)
        # (heal and the .plain path keep the per-member check)
        self.assertIn('p = extraction_path(out, "exefs", m)', source)
        self.assertIn('extraction_path(a.extract, "exefs", m, temporary_suffix=".plain")', source)
        docs = Path(HERE).parent.joinpath("docs", "development.md").read_text(encoding="utf-8")
        row = [line for line in docs.splitlines() if line.startswith("| `HOOKSHOT_NUP_IN_PLACE=0`")]
        self.assertEqual(len(row), 1)
        self.assertIn("IO-51", row[0])


if __name__ == "__main__":
    unittest.main()
