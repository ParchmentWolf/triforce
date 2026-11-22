"""The folder __GL_SHADER_DISK_CACHE_PATH names is made before Vulkan loads; the Linux binary keeps its name (no game).

(Triforce, 11-22, the performance audit's PIPE-98, after Source A's.) NVIDIA's Linux driver keeps no shader cache at
all when __GL_SHADER_DISK_CACHE_PATH names a folder that is not there: every prepared pipeline is compiled again at
each start. The Linux main makes the folder and its parents (0700) and never changes the value. The driver files its
cache by the program's file name, so that name is pinned here too.

Cuts driver_cache_folder out of host/hos_main.c and runs it on real folders under a temporary one (mkdir through a
stand-in that notes the mode, so it runs on Windows too), over an environment of the test's own:
  a missing folder three levels deep        made, every mkdir with 0700, no line
  a folder that is there                     left as it is, with what it holds, no line
  a trailing slash, a double slash           made
  a path under a file, a file at that name   not made, one "is not a folder and cannot be made one" line
  an empty value, or unset                   nothing made, nothing asked of the file system
  HOS_DRIVER_CACHE_FOLDER=0                  nothing made, no line
And reads the source: the function sets no variable; the last main calls it after the env-file loader and before
hos_display_init; game_main logs the kept line; nx2/build.py still has EXE = "triforce" if LINUX and
__GL_SHADER_DISK_CACHE_APP_NAME appears nowhere in host/ or gpu/vk as something set; the switches table has the row.

    python -I -B tests/test_driver_cache_folder.py [--cc clang]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "clang"]


def block(text, marker):
    start = text.find(marker)
    if start < 0:
        raise SystemExit("FAIL: host/hos_main.c has no '%s'" % marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#endif
#define CHECK(x) do { checks++; if (!(x)) { fprintf(stdout, "FAIL:%d %s (line kept: \"%s\")\n", __LINE__, #x, driver_folder_line); fails++; } } while (0)
static int checks, fails;
static int t_mkdirs, t_other_modes;
static int t_mkdir(const char *path, int mode) {   /* (the real folder, and the mode asked for noted) */
    t_mkdirs++, t_other_modes += mode != 0700;
#ifdef _WIN32
    return _mkdir(path);
#else
    return mkdir(path, (mode_t)mode);
#endif
}
/* the test's own environment */
static const char *t_path, *t_off;
static char *t_getenv(const char *name) {
    if (!strcmp(name, "__GL_SHADER_DISK_CACHE_PATH")) return (char *)t_path;
    if (!strcmp(name, "HOS_DRIVER_CACHE_FOLDER")) return (char *)t_off;
    fprintf(stdout, "FAIL: the environment was asked for %s\n", name);
    exit(1);
}
#define getenv t_getenv
#define mkdir(path, mode) t_mkdir(path, mode)
@CUT@
#undef getenv
#undef mkdir
static int is_dir(const char *path) { struct stat st; return stat(path, &st) == 0 && S_ISDIR(st.st_mode); }
static int is_file(const char *path) { struct stat st; return stat(path, &st) == 0 && S_ISREG(st.st_mode); }
static const char *root;
static const char *under(const char *rest) {
    static char p[8][1024];
    static int k;
    k = (k + 1) % 8;
    snprintf(p[k], sizeof p[k], "%s/%s", root, rest);
    return p[k];
}
static void start(const char *path, const char *off) {
    t_path = path, t_off = off, t_mkdirs = t_other_modes = 0, driver_folder_line[0] = 0;
    driver_cache_folder();
    CHECK(t_other_modes == 0);   /* (for the user alone) */
}
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    root = argv[1];   /* (a temporary folder holding "there" with "kept.bin" in it, and the file "afile") */

    start(under("a/b/c"), NULL);   /* missing, three levels deep */
    CHECK(is_dir(under("a")) && is_dir(under("a/b")) && is_dir(under("a/b/c")) && !driver_folder_line[0] && t_mkdirs >= 3);
    start(under("a/b/c"), NULL);   /* and again: there already */
    CHECK(is_dir(under("a/b/c")) && !driver_folder_line[0]);

    start(under("there"), NULL);   /* a folder that is there, with a file in it */
    CHECK(is_dir(under("there")) && is_file(under("there/kept.bin")) && !driver_folder_line[0]);

    start(under("t1/t2/"), NULL);   /* a trailing slash */
    CHECK(is_dir(under("t1/t2")) && !driver_folder_line[0]);

    start(under("d1//d2"), NULL);   /* a double slash */
    CHECK(is_dir(under("d1/d2")) && !driver_folder_line[0]);

    start(under("afile/sub"), NULL);   /* under a file */
    CHECK(!is_dir(under("afile/sub")) && is_file(under("afile")));
    CHECK(strstr(driver_folder_line, "boot: __GL_SHADER_DISK_CACHE_PATH=") && strstr(driver_folder_line, "afile/sub is not a folder and cannot be made one"));

    start(under("afile"), NULL);   /* a file at that name */
    CHECK(is_file(under("afile")) && strstr(driver_folder_line, "afile is not a folder and cannot be made one"));

    start("", NULL);   /* empty, unset: nothing asked of the file system */
    CHECK(t_mkdirs == 0 && !driver_folder_line[0]);
    start(NULL, NULL);
    CHECK(t_mkdirs == 0 && !driver_folder_line[0]);

    start(under("off/x"), "0");   /* the switch: as before, nothing made */
    CHECK(t_mkdirs == 0 && !is_dir(under("off")) && !driver_folder_line[0]);
    start(under("off/x"), "1");
    CHECK(is_dir(under("off/x")) && !driver_folder_line[0]);
    start(under("afile/sub"), "0");   /* and nothing said */
    CHECK(t_mkdirs == 0 && !driver_folder_line[0]);

    {   /* a path longer than the function copies: not made, said */
        static char longp[2200];
        size_t n = (size_t)snprintf(longp, sizeof longp, "%s/long", root);
        while (n < 1500) longp[n++] = 'x';
        longp[n] = 0;
        start(longp, NULL);
        CHECK(t_mkdirs == 0 && strstr(driver_folder_line, "is not a folder and cannot be made one"));
    }

    if (fails) printf("driver cache folder: FAILED (%d of %d checks)\n", fails, checks);
    else printf("driver cache folder: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check_source(main_c):
    at = main_c.rfind("\nint main(int argc, char **argv) {")
    if at < 0:
        raise SystemExit("FAIL: host/hos_main.c has no main")
    body = main_c[at:main_c.index("\n}\n", at)]
    loader = re.search(r"\n    load_\w+_env\(\);\n", body)   # (the env-file loader's call: the switch can be in that file)
    order = [loader.start() if loader else -1] + [body.find(n) for n in ("    driver_cache_folder();", "hos_display_init();")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("FAIL: the Linux main does not call driver_cache_folder() after the env-file loader and before "
                         "hos_display_init() (%r)" % (order,))
    game = main_c[main_c.index("static int game_main(int argc, char **argv) {"):at]
    order = [game.find(n) for n in ('hos_log("triforce %s",', 'if (driver_folder_line[0]) hos_log("%s", driver_folder_line);',
                                    "rx_prepare_shaders()")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("FAIL: game_main does not log the kept line after the version line, before the preparation")
    fn = block(main_c, "static void driver_cache_folder(void) {")
    if "setenv" in fn or "putenv" in fn:
        raise SystemExit("FAIL: driver_cache_folder() changes the environment (the variable's value must stay)")
    if fn.count("mkdir(dir, 0700);") != 2:
        raise SystemExit("FAIL: driver_cache_folder() no longer makes each parent and the folder for the user alone")
    before = main_c[:main_c.index("static void driver_cache_folder(void) {")]
    # (the block for the systems other than Windows: #ifndef _WIN32, or the Linux block driver_env_choose is in)
    if max(before.rfind("#ifndef _WIN32\n"), before.rfind("#ifdef __linux__\n")) < before.rfind("#endif"):
        raise SystemExit("FAIL: driver_cache_folder() is not in the block for the systems other than Windows")
    # (the driver files its cache by the program's file name: a rename starts every Linux NVIDIA player's cache over)
    build = (ROOT / "nx2/build.py").read_text(encoding="utf-8")
    if '\nEXE = "triforce" if LINUX else ' not in build:
        raise SystemExit('FAIL: nx2/build.py no longer has EXE = "triforce" if LINUX: renaming the Linux binary starts '
                         "every NVIDIA player's driver shader cache over")
    for path in sorted((ROOT / "host").rglob("*.c")) + sorted((ROOT / "gpu/vk").glob("*.cpp")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r'(setenv|putenv)\(\s*"__GL_SHADER_DISK_CACHE_APP_NAME', text):
            raise SystemExit("FAIL: %s sets __GL_SHADER_DISK_CACHE_APP_NAME: every player's cache would start over" % path.name)
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `HOS_DRIVER_CACHE_FOLDER=0` |" not in docs or "`__GL_SHADER_DISK_CACHE_PATH`" not in docs:
        raise SystemExit("FAIL: docs/development.md: the switches table has no HOS_DRIVER_CACHE_FOLDER row")
    if "The game builds as `Triforce.exe` + `triforce_vk.dll` (`triforce` + `triforce_vk.so` on Linux)." not in docs:
        raise SystemExit("FAIL: docs/development.md does not give the game's file names as nx2/build.py builds them")
    return "static char driver_folder_line[1200];\n" + fn


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    main_c = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    if "static char driver_folder_line[1200];\nstatic void driver_cache_folder(void) {" not in main_c:
        raise SystemExit("FAIL: host/hos_main.c has no driver_cache_folder() with its kept line")
    fn = check_source(main_c)
    with tempfile.TemporaryDirectory(prefix="driver-cache-folder-") as tmp:
        tmp = Path(tmp)
        src, exe = tmp / "driver_cache_folder_test.c", tmp / "driver-cache-folder.exe"
        src.write_text(FIXTURE.replace("@CUT@", fn), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror", str(src),
                        "-o", str(exe)], check=True)
        root = tmp / "root"
        (root / "there").mkdir(parents=True)
        (root / "there" / "kept.bin").write_bytes(b"kept")
        (root / "afile").write_bytes(b"a file")
        r = subprocess.run([str(exe), root.as_posix()], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the driver cache folder's checks failed")
        if (root / "there" / "kept.bin").read_bytes() != b"kept" or (root / "afile").read_bytes() != b"a file":
            raise SystemExit("FAIL: a file that was there was changed")
        lines = r.stderr.splitlines()
        if len(lines) != 3 or not all(l.startswith("boot: __GL_SHADER_DISK_CACHE_PATH=") for l in lines):
            raise SystemExit("FAIL: stderr has %d lines, 3 expected (under a file, a file at that name, too long):\n%s"
                             % (len(lines), r.stderr))


if __name__ == "__main__":
    main()
