"""The renderer's own code can be built with a play profile (nx2/build.py vk_pgo_flags, flag_text and the renderer's
jobs; nx2/make_game.py; host/pgo_rt.c; the packers; no compiler, no game).

(Triforce, 11-21, the performance audit's LIFT-10, after Source A's.) The back end runs the replay on the game's render
thread and was built at plain -O2 whatever it does most. RX_VK_PGO=gen builds it counting its branches, a run writes the
counts, llvm-profdata merges them, and RX_VK_PGO=<file> builds with that profile.

Runs build.py's own vk_pgo_flags and flag_text, cut out through the AST:
- not set, empty or 0: no flags; gen: the counting flags; a file: built with it, its contents' SHA-1 in the flags;
- two copies of one profile at different paths give the same object key text, another profile another;
- the include folders and the sysroot are still left out of the key text.
And reads the sources: only the renderer's own files get the flags, the vendored recompiler does not; gen adds the
counters' writer to the DLL, compiled for RX_VK_PGO_FILE; the writer reads PGO_ENV, HOS_PGO unless told; make_game
copies the shipped profile, passes it only when RX_VK_PGO is not set and the compiler can read it, and keeps both
variables out of the lift's key; both packers carry the file; the switches are in the switches table.

    python -I -B tests/test_vk_pgo.py
"""
import ast
import hashlib
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def functions(source, names, **scope):
    """the named top-level functions of a file, compiled alone into scope"""
    tree = ast.parse(source)
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    check(len(body) == len(names), "build.py no longer has %s" % ", ".join(names))
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), "build.py", "exec"), scope)
    return scope


def main():
    build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    check('VK_PGO = os.environ.get("RX_VK_PGO", "")' in build, "build.py does not read RX_VK_PGO")
    with tempfile.TemporaryDirectory(prefix="vk-pgo-") as tmp:
        a, b, c = (os.path.join(tmp, n) for n in ("a.profdata", os.path.join("other", "a.profdata"), "c.profdata"))
        os.makedirs(os.path.dirname(b))
        for path, data in ((a, b"one profile"), (b, b"one profile"), (c, b"another profile")):
            with open(path, "wb") as f:
                f.write(data)
        scope = functions(build, ("vk_pgo_flags", "flag_text"), os=os, hashlib=hashlib, VK_PGO="", kit=SimpleNamespace(ROOT=tmp))
        flags, text = scope["vk_pgo_flags"], scope["flag_text"]
        check(flags("") == [] and flags("0") == [], "no profile asked for still adds flags")
        check(flags() == [], "the environment's value is not the default")
        check(flags("gen") == ["-fprofile-instr-generate", "-mllvm", "-disable-vp=true"], "gen does not count the branches")
        sha = hashlib.sha1(b"one profile").hexdigest()[:16]
        use = flags(a)
        check(use[:2] == ["-fprofile-instr-use=" + a, "-DTRIFORCE_VK_PROFILE_SHA1=" + sha], "a profile is not used, or its contents are not in the flags")
        check("-Wno-profile-instr-out-of-date" in use, "a profile of an older renderer would stop the build with a warning as an error")
        keys = []
        for path in (a, b, c):
            scope["VK_PGO"] = path
            keys.append(text(["-O2", "-Iinclude/here", "--sysroot=/tmp/.mount_x"] + flags(path)))
        check(keys[0] == keys[1], "the same profile at another path is another object key: a second work folder compiles everything again")
        check(keys[0] != keys[2], "another profile is the same object key: an update's new profile would not be compiled in")
        check("<vk profile>" in keys[0] and a not in keys[0] and "-Iinclude" not in keys[0] and "--sysroot=<sysroot>" in keys[0],
              "the key text names the profile by its path, or lost its other rules")
        scope["VK_PGO"] = ""
        check(text(["-fprofile-instr-use=" + a]) == "-fprofile-instr-use=" + a.replace(tmp, "<root>"),
              "the hot code's own profile flag is renamed too: its key would change")

    jobs = build[build.index("vk_pgo = vk_pgo_flags()"):build.index("if NGX_SDK and not LINUX and toolchain.mingw():")]
    check('vflags + ([] if lib else vk_pgo + ["-MD"]) +' in jobs and 'lib = os.path.relpath(src, vk).split(os.sep)[0] in ("eden", "sirit")' in jobs,
          "the profile's flags are not on the renderer's own files alone")
    check('if VK_PGO == "gen" and not LINUX:' in jobs and 'os.path.join(HOST, "pgo_rt.c"), os.path.join(obj_dir, "vk_pgo_rt.o")' in jobs and
          "'-DPGO_ENV=\"RX_VK_PGO_FILE\"'" in jobs, "a counting renderer has nothing to write its counters, or writes them for another variable")
    rt = (ROOT / "host" / "pgo_rt.c").read_text(encoding="utf-8")
    check('#define PGO_ENV "HOS_PGO"' in rt and "getenv(PGO_ENV)" in rt and "#ifndef PGO_ENV" in rt,
          "the counters' writer does not read PGO_ENV, HOS_PGO unless told")

    make = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
    check('"hookshot_pieces.prof", "triforce_vk.profdata", "hookshot.res"' in make, "make_game does not copy the shipped renderer profile")
    check('if "RX_VK_PGO" not in os.environ and os.path.exists(vk_profile) and profile_readable(vk_profile):' in make and
          'env["RX_VK_PGO"] = vk_profile' in make,
          "the shipped profile is passed over a set RX_VK_PGO, or without asking whether the compiler can read it")
    check('COMPILE_ONLY_ENV = ("RX_VK_PGO", "RX_VK_PGO_FILE"' in make, "the renderer profile's variables are not named as the compile's alone")
    key = make[make.index("def lift_key(exefs, work, env, chunks=True):"):make.index("def key_after_lift(")]
    check(key.index("lift_env = dict(env,") < key.index("for name in COMPILE_ONLY_ENV:") < key.index("lift_env.pop(name, None)") <
          key.index("h.update(repr(sorted(lift_env.items())).encode())"),
          "a renderer profile changes the lift's key: the whole game would be translated again for it")
    check("'hookshot_pieces.prof', 'triforce_vk.profdata'" in (ROOT / "setup" / "pack_tools.ps1").read_text(encoding="utf-8"),
          "setup/pack_tools.ps1 does not carry the renderer's profile")
    check("hookshot_pieces.prof triforce_vk.profdata" in (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8"),
          "scripts/linux/appimage.sh does not carry the renderer's profile")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_PGO=gen`, `=<file>`, `=0`; `RX_VK_PGO_FILE=<path>`" in dev, "docs/development.md: RX_VK_PGO is not in the switches table")
    print("PASS: the renderer's own files take a play profile by its contents; the lift's key does not change")


if __name__ == "__main__":
    main()
