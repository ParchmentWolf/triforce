"""Room in the driver's shader cache for the pipelines the game prepares (Linux; no game, no Linux needed to check).

(Triforce, 11-22, the performance audit's PIPE-97, after Source A's and Source B's.) The game builds its ~41,400
predicted pipelines into the driver's own disk cache. NVIDIA's and Mesa's caches hold 1 GiB unless told otherwise and
trim themselves to it, so part of a full preparation is dropped and compiled again in play. The Linux main sets both
drivers' sizes to 10 GiB before Vulkan loads, without overwriting a size the player set.

Cuts driver_cache_room out of host/hos_main.c and runs it over a small environment of the test's own:
  nothing set                          __GL_SHADER_DISK_CACHE_SIZE=10737418240 (at least 4 GiB, in bytes) and
                                       MESA_SHADER_CACHE_MAX_SIZE=10G, both set without overwriting
  the player's own sizes               kept, each by itself
  HOS_DRIVER_CACHE_ROOM=0              neither set, the line says so; =1 or empty: set
  __GL_SHADER_DISK_CACHE_SKIP_CLEANUP  never set
  one line on stderr, kept for the log
And reads the source: the last main calls it after the env-file loader and before hos_display_init, so the builder's
--prepare-shaders run gets it too; game_main logs the kept line; the switches table has the row.

    python -I -B tests/test_driver_cache_room.py [--cc clang]
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
#define CHECK(x) do { checks++; if (!(x)) { fprintf(stdout, "FAIL:%d %s (line kept: \"%s\")\n", __LINE__, #x, driver_room_line); fails++; } } while (0)
static int checks, fails;
/* the test's own environment */
static const char *const t_names[] = {"HOS_DRIVER_CACHE_ROOM", "__GL_SHADER_DISK_CACHE_SIZE", "MESA_SHADER_CACHE_MAX_SIZE"};
static char t_values[3][128];
static int t_set[3], t_overwrites, t_sets;
static int t_index(const char *name) {
    for (int i = 0; i < 3; i++)
        if (!strcmp(name, t_names[i])) return i;
    fprintf(stdout, "FAIL: the environment was asked for %s\n", name);   /* (SKIP_CLEANUP, APP_NAME or any other) */
    exit(1);
}
static char *t_getenv(const char *name) { const int i = t_index(name); return t_set[i] ? t_values[i] : NULL; }
static int t_setenv(const char *name, const char *value, int overwrite) {
    const int i = t_index(name);
    t_sets++, t_overwrites += overwrite != 0;
    if (t_set[i] && !overwrite) return 0;
    t_set[i] = 1;
    snprintf(t_values[i], sizeof t_values[i], "%s", value);
    return 0;
}
static void put(const char *name, const char *value) {
    const int i = t_index(name);
    t_set[i] = value != NULL;
    if (value) snprintf(t_values[i], sizeof t_values[i], "%s", value);
}
#define getenv t_getenv
#define setenv t_setenv
@CUT@
#undef getenv
#undef setenv
static int is(const char *name, const char *want) {
    const char *v = t_getenv(name);
    return want ? v && !strcmp(v, want) : !v;
}
static void start(const char *room, const char *nv, const char *mesa) {
    put("HOS_DRIVER_CACHE_ROOM", room), put("__GL_SHADER_DISK_CACHE_SIZE", nv), put("MESA_SHADER_CACHE_MAX_SIZE", mesa);
    driver_room_line[0] = 0, t_sets = t_overwrites = 0;
    driver_cache_room();
    CHECK(t_overwrites == 0);   /* (never over a size the player set) */
    CHECK(is("HOS_DRIVER_CACHE_ROOM", room));
}
int main(void) {
    start(NULL, NULL, NULL);   /* out of the box */
    CHECK(is("__GL_SHADER_DISK_CACHE_SIZE", "10737418240") && is("MESA_SHADER_CACHE_MAX_SIZE", "10G") && t_sets == 2);
    CHECK(strtoull(t_getenv("__GL_SHADER_DISK_CACHE_SIZE"), NULL, 10) >= 4ull << 30);   /* (in bytes, well past the 1 GiB default) */
    CHECK(strstr(driver_room_line, "__GL_SHADER_DISK_CACHE_SIZE=10737418240, MESA_SHADER_CACHE_MAX_SIZE=10G"));
    CHECK(!strncmp(driver_room_line, "boot: ", 6));

    start(NULL, "2147483648", NULL);   /* the player's own size for NVIDIA's stays; Mesa's is still set */
    CHECK(is("__GL_SHADER_DISK_CACHE_SIZE", "2147483648") && is("MESA_SHADER_CACHE_MAX_SIZE", "10G"));
    CHECK(strstr(driver_room_line, "__GL_SHADER_DISK_CACHE_SIZE=2147483648, MESA_SHADER_CACHE_MAX_SIZE=10G"));
    start(NULL, NULL, "2G");
    CHECK(is("__GL_SHADER_DISK_CACHE_SIZE", "10737418240") && is("MESA_SHADER_CACHE_MAX_SIZE", "2G"));
    start(NULL, "1", "1K");
    CHECK(is("__GL_SHADER_DISK_CACHE_SIZE", "1") && is("MESA_SHADER_CACHE_MAX_SIZE", "1K"));

    start("0", NULL, NULL);   /* the switch: as before, nothing set */
    CHECK(is("__GL_SHADER_DISK_CACHE_SIZE", NULL) && is("MESA_SHADER_CACHE_MAX_SIZE", NULL) && t_sets == 0);
    CHECK(strstr(driver_room_line, "left as they are (HOS_DRIVER_CACHE_ROOM=0)"));
    start("0", "5", "6");
    CHECK(is("__GL_SHADER_DISK_CACHE_SIZE", "5") && is("MESA_SHADER_CACHE_MAX_SIZE", "6") && t_sets == 0);
    start("1", NULL, NULL);
    CHECK(is("__GL_SHADER_DISK_CACHE_SIZE", "10737418240") && is("MESA_SHADER_CACHE_MAX_SIZE", "10G"));
    start("", NULL, NULL);
    CHECK(is("__GL_SHADER_DISK_CACHE_SIZE", "10737418240") && is("MESA_SHADER_CACHE_MAX_SIZE", "10G"));

    if (fails) printf("driver cache room: FAILED (%d of %d checks)\n", fails, checks);
    else printf("driver cache room: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check_source(main_c):
    at = main_c.rfind("\nint main(int argc, char **argv) {")
    if at < 0:
        raise SystemExit("FAIL: host/hos_main.c has no main")
    body = main_c[at:main_c.index("\n}\n", at)]
    loader = re.search(r"\n    load_\w+_env\(\);\n", body)   # (the env-file loader's call: the switch can be in that file)
    order = [loader.start() if loader else -1] + [body.find(n) for n in ("    driver_cache_room();", "hos_display_init();")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("FAIL: the Linux main does not call driver_cache_room() after the env-file loader and before "
                         "hos_display_init() (%r)" % (order,))
    if body.find("    driver_cache_room();") > body.find("if (!strcmp(argv[i], \"--prepare-shaders\")) prepare_shaders = 1;"):
        raise SystemExit("FAIL: driver_cache_room() is called after the --prepare-shaders parse")
    game = main_c[main_c.index("static int game_main(int argc, char **argv) {"):at]
    order = [game.find(n) for n in ('hos_log("triforce %s",', 'if (driver_room_line[0]) hos_log("%s", driver_room_line);',
                                    "rx_prepare_shaders()")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("FAIL: game_main does not log the kept line after the version line, before the preparation")
    fn = block(main_c, "static void driver_cache_room(void) {")
    for needle in ('setenv("__GL_SHADER_DISK_CACHE_SIZE", "10737418240", 0);', 'setenv("MESA_SHADER_CACHE_MAX_SIZE", "10G", 0);'):
        if needle not in fn:
            raise SystemExit("FAIL: driver_cache_room() no longer has: " + needle)
    if "SKIP_CLEANUP" in fn or "APP_NAME" in fn:
        raise SystemExit("FAIL: driver_cache_room() sets more than the two sizes")
    before = main_c[:main_c.index("static void driver_cache_room(void) {")]
    # (the block for the systems other than Windows: #ifndef _WIN32, or the Linux block driver_env_choose is in)
    if max(before.rfind("#ifndef _WIN32\n"), before.rfind("#ifdef __linux__\n")) < before.rfind("#endif"):
        raise SystemExit("FAIL: driver_cache_room() is not in the block for the systems other than Windows")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `HOS_DRIVER_CACHE_ROOM=0` |" not in docs or "`__GL_SHADER_DISK_CACHE_SIZE`" not in docs:
        raise SystemExit("FAIL: docs/development.md: the switches table has no HOS_DRIVER_CACHE_ROOM row")
    return "static char driver_room_line[320];\n" + fn


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    main_c = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    if "static char driver_room_line[320];\nstatic void driver_cache_room(void) {" not in main_c:
        raise SystemExit("FAIL: host/hos_main.c has no driver_cache_room() with its kept line")
    fn = check_source(main_c)
    with tempfile.TemporaryDirectory(prefix="driver-cache-room-") as tmp:
        tmp = Path(tmp)
        src, exe = tmp / "driver_cache_room_test.c", tmp / "driver-cache-room.exe"
        src.write_text(FIXTURE.replace("@CUT@", fn), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror", str(src),
                        "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the driver cache room's checks failed")
        lines = r.stderr.splitlines()
        if len(lines) != 8 or not all(l.startswith("boot: ") for l in lines):
            raise SystemExit("FAIL: stderr has %d lines, one for each of the 8 starts expected:\n%s" % (len(lines), r.stderr))


if __name__ == "__main__":
    main()
