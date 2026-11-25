"""The lift key takes only the environment that shapes the lifted C (nx2/make_game.py lift_key).

(Triforce, 11-22, the performance audit's LIFT-27, after Source A's.) The key decides whether a build translates the
game again. It hashed every A64_, OOT_ and RX_ variable and the folders' paths, so a build from another folder, a
release build after a development one, or one more variable in the environment translated the same C again. It now
takes the lifter's own switches (A64_*) and the target (RX_TARGET); HOOKSHOT_KEEP_LIFT=0 is the key as it was.

What must hold for that to be safe, and is held here:
  - every environment variable the lift's files read (nx2/lift.py's and nx2/split_hot.py's imports, found as
    tests/test_lift_key_files.py finds them) is read by its literal name, and is either in the key (A64_*, RX_TARGET) or
    one of those listed below with why it cannot change the C: folders whose files the key hashes by their contents, job
    counts, where the compiler is. A variable read any other way, or a new one, fails this test until it is listed;
  - lift_key itself, on a made-up tree: a folder's path, RX_RELEASE, the profile's path, a job count and a stray RX_
    variable leave the key alone; an A64_ switch, in the environment or given, and RX_TARGET change it;
  - with HOOKSHOT_KEEP_LIFT=0 the key is the old formula's, computed here beside it, and each of those changes it again;
  - nx2/released_translation_stamp.json, which build.py alone reads, is out of the key, and back in with the switch.

    python -I -B tests/test_lift_key_env.py
"""
import ast
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_lift_key_files import lift_imports, production   # (the lift's files, and lift_key cut out of make_game.py)

# (what the lift's files read beside the key's own, and why none of it shapes the C)
NOT_IN_KEY = {
    "OOT_WORK": "the work folder: the files read there (hot_funcs.txt, image/chunks.txt) are hashed by their contents",
    "OOT_DUMP": "the game's folder: the lift is given the exefs, whose files are hashed by their contents",
    "OOT_EXEFS": "the game's code folder: its files are hashed by their contents",
    "OOT_ROMFS": "the game's data folder: kit.py names it, the lift reads nothing there",
    "HOOKSHOT_LIFT_JOBS": "how many processes write the C: the C is the same whatever the count (tests/test_spawn_emit.py)",
    "HOOKSHOT_JOBS": "the workers the build was asked for, a ceiling on HOOKSHOT_LIFT_JOBS's count (nx2/build_jobs.py): the same C",
    "HOOKSHOT_LIFTED_C_REGEX": "how nx2/lifted_c.py finds the definitions, by jumps or by the patterns: the same matches "
                               "either way (the performance audit's IO-40, tests/test_lifted_c_scan.py)",
    "RX_JOBS": "how many compilers run at once (the kit's toolchain.default_jobs)",
    "EMSDK": "where a compiler is (the kit's toolchain)",
    "HOOKSHOT_MINGW": "where a compiler is (the kit's toolchain)",
}


def in_key(name):
    return name.startswith("A64_") or name == "RX_TARGET"


def environment_reads(path):
    """Each use of the environment in a Python file: (line, the variable's name, or None when it is not read by a
    literal name)"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    reads = []

    def literal(node):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":   # (under another name it would be read unseen)
            reads += [(node.lineno, None) for a in node.names if a.name in ("environ", "getenv") and a.asname]
        is_environ = isinstance(node, ast.Attribute) and node.attr == "environ" or isinstance(node, ast.Name) and node.id == "environ"
        is_getenv = isinstance(node, ast.Attribute) and node.attr == "getenv" or isinstance(node, ast.Name) and node.id == "getenv"
        if not (is_environ or is_getenv):
            continue
        up = parents.get(node)
        name = None
        if is_getenv and isinstance(up, ast.Call) and up.func is node and up.args:
            name = literal(up.args[0])
        elif is_environ and isinstance(up, ast.Subscript) and up.value is node:
            name = literal(up.slice)
        elif is_environ and isinstance(up, ast.Attribute) and up.attr in ("get", "pop", "setdefault"):
            call = parents.get(up)
            if isinstance(call, ast.Call) and call.func is up and call.args:
                name = literal(call.args[0])
        elif is_environ and isinstance(up, ast.Compare) and node in up.comparators and len(up.ops) == 1 and \
                isinstance(up.ops[0], (ast.In, ast.NotIn)):
            name = literal(up.left)
        reads.append((node.lineno, name))
    return reads


def old_key(exefs, work, env, here, root, implemented):
    """The lift key as nx2/make_game.py computed it before the performance audit's LIFT-27 (chunks.txt included)"""
    h = hashlib.sha1(sys.version.encode(), usedforsecurity=False)
    h.update(" ".join(sorted(implemented)).encode())
    not_key = ("make_game.py", "build.py", "nup.py", "version.py", "shader_census.py", "prompt_assets.py", "prompt_draw.py",
               "prompt_faces.py", "prompt_requirements.txt", "prompt_keys.py", "code_mods.py")

    def kept(rel):
        name = rel.rsplit("/", 1)[-1]
        return not (rel in not_key or rel.startswith("prompt_faces/") or (name.startswith("test_") and name.endswith(".py")))

    files = [(exefs, os.path.join(exefs, f)) for f in sorted(os.listdir(exefs))]
    for top in (here, os.path.join(root, "third_party", "a64-kit")):
        for d, dirs, fs in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            files += [(root, os.path.join(d, f)) for f in sorted(fs) if f.endswith((".py", ".c", ".h", ".cpp", ".hpp", ".txt", ".json"))
                      and (top != here or kept(os.path.relpath(os.path.join(d, f), here).replace(os.sep, "/")))]
    files.append((work, os.path.join(work, "hot_funcs.txt")))
    files.append((work, os.path.join(work, "image", "chunks.txt")))
    for base, f in files:
        if os.path.isfile(f):
            h.update(os.path.relpath(f, base).replace(os.sep, "/").encode() + bytes(1))
            with open(f, "rb") as src:
                h.update(hashlib.sha1(src.read(), usedforsecurity=False).digest())
    lift_env = dict(env, **{k: v for k, v in os.environ.items() if k.startswith(("A64_", "OOT_", "RX_"))})
    for name in ("RX_VK_PGO", "RX_VK_PGO_FILE"):
        lift_env.pop(name, None)
    h.update(repr(sorted(lift_env.items())).encode())
    return h.hexdigest()


class LiftKeyEnvironment(unittest.TestCase):
    def test_the_lift_reads_no_variable_that_is_not_listed(self):
        files = sorted(p for p in lift_imports() if p.suffix == ".py")
        self.assertTrue(any(p.name == "a64_lift.py" for p in files) and any(p.name == "kit.py" for p in files))
        seen = set()
        for path in files:
            for line, name in environment_reads(path):
                where = "%s:%d" % (path.relative_to(ROOT).as_posix(), line)
                self.assertIsNotNone(name, "%s uses the environment other than by a variable's literal name: the lift key "
                                           "cannot tell what it reads" % where)
                self.assertTrue(in_key(name) or name in NOT_IN_KEY,
                                "%s reads %s, which the lift key does not hash: put it in the key (lift_key) if it can change "
                                "the lifted C, or list it in this test with why it cannot" % (where, name))
                seen.add(name)
        # (the scan did find the lift's reads, of both kinds, and the list holds nothing the lift no longer reads)
        self.assertTrue({"A64_HOT_FUNCS", "A64_NO_VFPX", "RX_TARGET", "OOT_WORK", "HOOKSHOT_LIFT_JOBS"} <= seen, sorted(seen))
        self.assertEqual(sorted(n for n in NOT_IN_KEY if n not in seen), [])

    def test_the_scan_sees_each_way_of_reading(self):
        with tempfile.TemporaryDirectory(prefix="lift-key-env-") as tmp:
            path = Path(tmp) / "reads.py"
            path.write_text("import os\nfrom os import environ, getenv\n"
                            "a = os.environ.get('A64_ONE')\nb = os.environ['A64_TWO']\nc = 'A64_THREE' in os.environ\n"
                            "d = os.getenv('A64_FOUR')\ne = getenv('A64_FIVE', '')\nf = environ.get('A64_SIX')\n"
                            "g = os.environ.get(name)\nh = dict(os.environ)\nfor k in os.environ:\n    pass\n"
                            "from os import environ as hidden\n", encoding="utf-8")
            names = [name for _, name in environment_reads(path)]
        self.assertEqual(sorted(n for n in names if n), ["A64_FIVE", "A64_FOUR", "A64_ONE", "A64_SIX", "A64_THREE", "A64_TWO"])
        self.assertEqual(names.count(None), 4)   # (a name not written out, the whole environment twice, and another name for it)

    def test_the_key_follows_what_shapes_the_c_only(self):
        scope = production()
        self.addCleanup(lambda: scope.update(HERE=str(ROOT / "nx2"), ROOT=str(ROOT)))
        with tempfile.TemporaryDirectory(prefix="lift-key-env-") as tmp:
            root = Path(tmp)
            here = root / "nx2"
            (root / "third_party" / "a64-kit").mkdir(parents=True)
            here.mkdir()
            exefs, work, other_work = root / "exefs", root / "work", root / "other-work"
            exefs.mkdir()
            for w in (work, other_work):
                (w / "image").mkdir(parents=True)
                (w / "hot_funcs.txt").write_text("f_80000000\n")
                (w / "image" / "chunks.txt").write_text("80001000\n")
            (exefs / "main").write_bytes(b"game code")
            (here / "lift.py").write_text("# the lift\n", encoding="utf-8")
            (here / "build.py").write_text("# the build\n", encoding="utf-8")
            stamp_json = here / "released_translation_stamp.json"
            stamp_json.write_text('{"stamp": "1"}\n', encoding="utf-8")
            (root / "third_party" / "a64-kit" / "a64_lift.py").write_text("# kit\n", encoding="utf-8")
            scope.update(HERE=str(here), ROOT=str(root))
            implemented = ["nn::os::A", "nn::os::B"]
            standalone = types.ModuleType("standalone")
            standalone.implemented = lambda: implemented
            given = {"OOT_WORK": str(work), "OOT_EXEFS": str(exefs), "OOT_ROMFS": str(root / "romfs"), "OOT_DUMP": str(root),
                     "RX_RELEASE": "1", "A64_HOT_CHUNK": "1", "RX_PGO": str(work / "pieces.prof")}
            clean = {k: v for k, v in os.environ.items()
                     if not k.startswith(("A64_", "OOT_", "RX_")) and k not in ("HOOKSHOT_KEEP_LIFT", "HOOKSHOT_LIFT_JOBS")}

            def key(env=given, where=work, **environ):
                with mock.patch.dict(os.environ, dict(clean, **environ), clear=True):
                    return scope["lift_key"](str(exefs), str(where), env)

            def before(env=given, where=work, **environ):
                with mock.patch.dict(os.environ, dict(clean, **environ), clear=True):
                    return old_key(str(exefs), str(where), env, str(here), str(root), implemented)

            with mock.patch.dict(sys.modules, {"kit": types.ModuleType("kit"), "standalone": standalone}):
                first = key()
                self.assertEqual(first, key())
                # ---- what does not shape the C leaves the key alone
                same = {
                    "another work folder with the same files": key(dict(given, OOT_WORK=str(other_work), RX_PGO="x"), other_work),
                    "the game's folders elsewhere": key(dict(given, OOT_ROMFS="r", OOT_DUMP="d", OOT_EXEFS="e")),
                    "not a release build": key({k: v for k, v in given.items() if k != "RX_RELEASE"}),
                    "a job count": key(RX_JOBS="3", HOOKSHOT_LIFT_JOBS="2"),
                    "a stray RX_ variable": key(RX_SOMETHING_ELSE="1", RX_MARCH="x86-64-v2"),
                    "a folder variable in the environment": key(OOT_WORK="elsewhere", OOT_ROMFS="there"),
                    "the switch itself, on": key(HOOKSHOT_KEEP_LIFT="1"),
                    # ((Triforce, 11-24) the build's value over the shell's, as run() gives them to the lift)
                    "a lifter switch the build sets, other in the shell": key(A64_HOT_CHUNK="0"),
                }
                for what, k in same.items():
                    self.assertEqual(k, first, what)
                # ((Triforce, 11-24) the work folder's own hot list in another folder: the same key; a list named in the shell
                # by its contents, so an edit to it changes the key)
                hot_env = dict(given, A64_HOT_FUNCS=str(work / "hot_funcs.txt"))
                self.assertEqual(key(hot_env), key(dict(given, OOT_WORK=str(other_work), A64_HOT_FUNCS=str(other_work / "hot_funcs.txt")),
                                                   other_work))
                own = root / "own_hot.txt"
                own.write_text("f_80000000\n")
                listed = key(A64_HOT_FUNCS=str(own))
                (root / "elsewhere").mkdir()
                (root / "elsewhere" / "own_hot.txt").write_text("f_80000000\n")
                self.assertEqual(key(A64_HOT_FUNCS=str(root / "elsewhere" / "own_hot.txt")), listed)
                own.write_text("f_80000040\n")
                self.assertNotEqual(key(A64_HOT_FUNCS=str(own)), listed)
                # ---- what does changes it
                different = {
                    "a lifter switch in the environment": key(A64_NO_VFPX="1"),
                    "a lifter switch given": key(dict(given, A64_HOT_CHUNK="")),
                    "the hot list's variable": key(dict(given, A64_HOT_FUNCS=str(work / "hot_funcs.txt"))),
                    "the target": key(RX_TARGET="windows"),
                }
                for what, k in different.items():
                    self.assertNotEqual(k, first, what)
                self.assertEqual(len(set(different.values())), len(different))
                # ---- the release's translation stamp: out of the key
                stamp_json.write_text('{"stamp": "2"}\n', encoding="utf-8")
                self.assertEqual(key(), first)
                stamp_json.write_text('{"stamp": "1"}\n', encoding="utf-8")
                (here / "lift.py").write_text("# the lift, changed\n", encoding="utf-8")
                self.assertNotEqual(key(), first)   # (a file of the translator still changes it)
                (here / "lift.py").write_text("# the lift\n", encoding="utf-8")

                # ---- HOOKSHOT_KEEP_LIFT=0: the key as it was, to the digit, and everything above changes it again
                old = key(HOOKSHOT_KEEP_LIFT="0")
                self.assertEqual(old, before())
                self.assertNotEqual(old, first)   # (the key changes once with this change: one lift again, the same C)
                for what, env, where, environ in (
                        ("another work folder", dict(given, OOT_WORK=str(other_work)), other_work, {}),
                        ("not a release build", {k: v for k, v in given.items() if k != "RX_RELEASE"}, work, {}),
                        ("a stray RX_ variable", given, work, {"RX_SOMETHING_ELSE": "1"}),
                        ("a lifter switch", given, work, {"A64_NO_VFPX": "1"})):
                    was = key(env, where, HOOKSHOT_KEEP_LIFT="0", **environ)
                    self.assertEqual(was, before(env, where, **environ), what)
                    self.assertNotEqual(was, old, what)
                stamp_json.write_text('{"stamp": "2"}\n', encoding="utf-8")
                changed = key(HOOKSHOT_KEEP_LIFT="0")
                self.assertEqual(changed, before())
                self.assertNotEqual(changed, old)
                # (the profile's path was never in it, before or now: LIFT-10)
                self.assertEqual(key(HOOKSHOT_KEEP_LIFT="0", RX_VK_PGO="p"), changed)

    def test_source_and_docs(self):
        source = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        body = source[source.index("def lift_key(exefs, work, env, chunks=True):"):source.index("def key_after_lift(")]
        for needle in ('key_as_before = os.environ.get("HOOKSHOT_KEEP_LIFT", "1") == "0"',
                       'lift_env = {k: v for k, v in lift_env.items() if k.startswith("A64_") or k == "RX_TARGET"}',
                       'or (key_as_before and d == HERE and f == "released_translation_stamp.json")'):
            self.assertTrue(needle in body, needle)
        self.assertTrue('"released_translation_stamp.json"' in source[source.index("LIFT_KEY_NOT = ("):source.index("def lift_key_file(")])
        build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        self.assertTrue("released_translation_stamp.json" in build)   # (its one reader)
        docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
        rows = [line for line in docs.splitlines() if line.startswith("| `HOOKSHOT_KEEP_LIFT=0` |")]
        self.assertEqual(len(rows), 1)
        self.assertTrue("LIFT-27" in rows[0])


if __name__ == "__main__":
    unittest.main()
