"""Game Mode's forced-VRS variable dropped before Vulkan loads, so prepared pipelines still match (host/hos_main.c
driver_env_choose; HOS_HALF_RATE_SHADING; Linux; no game).

Steam's Game Mode gives every game RADV_FORCE_VRS_CONFIG_FILE (Half Rate Shading). While the file exists RADV puts a forced shading
rate into every pipeline's key, whatever it holds, so pipelines prepared without it miss the driver's caches and compile again.

driver_env_choose is cut out of hos_main.c unchanged and compiled with a stand-in environment (getenv, unsetenv) over real files
(stat), so it runs on any system. Checked: a file holding 1x1 and an empty file: the variable dropped and the line says so; a
missing file, an empty value and no variable: left as it is, no line; HOS_HALF_RATE_SHADING=1 keeps it (the line says so), =0
drops it; RADV_FORCE_VRS untouched in every case. The source: Linux's main calls it after the env file is loaded and before the
display (and before the builder's --prepare-shaders run returns), the line joins the boot: lines, all of it Linux's alone, and the
switch has its docs row.

    python -I -B tests/test_radv_vrs_drop.py [--cc clang]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
/* (the environment: a few names, set from the arguments) */
static const char *names[3] = {"RADV_FORCE_VRS_CONFIG_FILE", "HOS_HALF_RATE_SHADING", "RADV_FORCE_VRS"};
static const char *values[3];
static const char *fake_getenv(const char *n) {
    for (int i = 0; i < 3; i++) if (!strcmp(n, names[i])) return values[i];
    return NULL;
}
static int fake_unsetenv(const char *n) {
    for (int i = 0; i < 3; i++) if (!strcmp(n, names[i])) values[i] = NULL;
    return 0;
}
#define getenv fake_getenv
#define unsetenv fake_unsetenv
@CUT@
int main(int argc, char **argv) {
    for (int i = 0; i < 3 && i + 1 < argc; i++) values[i] = strcmp(argv[i + 1], "-") ? argv[i + 1] : NULL;
    driver_env_choose();
    printf("vrs_file=%s\nvrs=%s\nnote=%s\n", values[0] ? values[0] : "(unset)", values[2] ? values[2] : "(unset)", driver_env_note);
    return 0;
}
'''


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check_source(src, dev):
    choose = src.index("static void driver_env_choose(void) {")
    linux = src.rfind("#ifdef __linux__", 0, choose)
    if linux < 0 or "#endif" in src[linux:choose]:
        fail("driver_env_choose is not Linux's alone")
    main = block(src, "int main(int argc, char **argv) {\n    int hos_display_init(void);")
    load, call = main.index("load_hookshot_env();"), main.index("driver_env_choose();")
    if not load < call < main.index("hos_display_init();") or call > main.index("--prepare-shaders"):
        fail("Linux's main does not call driver_env_choose between the env file and the display, before the builder's run")
    if "#ifdef __linux__" not in main[load:call]:
        fail("Linux's main calls driver_env_choose outside Linux")
    game = src[src.index("    memory_notice();\n#endif\n"):]
    if not game.startswith("    memory_notice();\n#endif\n#ifdef __linux__\n    if (driver_env_note[0]) hos_log(\"%s\", driver_env_note);"):
        fail("driver_env_choose's line does not join the boot: lines in the log")
    if "`HOS_HALF_RATE_SHADING=1`" not in dev:
        fail("docs/development.md has no HOS_HALF_RATE_SHADING row")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    try:
        check_source(src, dev)
        cut = "static char driver_env_note[640];\n" + block(src, "static void driver_env_choose(void) {")
    except ValueError as e:
        fail("a text this test reads moved (%s)" % e)
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    problems = []
    with tempfile.TemporaryDirectory(prefix="radv-vrs-") as tmp:
        one = Path(tmp) / "vrs_1x1.txt"
        one.write_text("1x1\n", encoding="ascii")
        empty = Path(tmp) / "vrs_empty.txt"
        empty.write_text("", encoding="ascii")
        missing = str(Path(tmp) / "no_such_file.txt")
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        c.write_text(FIXTURE.replace("@CUT@", cut), encoding="utf-8")
        built = subprocess.run([a.cc, "-std=gnu17", "-O1", "-Wall", "-Wno-unused-function", str(c), "-o", str(exe)],
                               capture_output=True, text=True, creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        # (RADV_FORCE_VRS_CONFIG_FILE, HOS_HALF_RATE_SHADING, RADV_FORCE_VRS) -> (dropped, the note's text or "" for none)
        cases = [
            ((str(one), "-", "2x2"), (True, "dropped")),
            ((str(empty), "-", "-"), (True, "dropped")),
            ((missing, "-", "2x2"), (False, "")),
            (("", "-", "-"), (False, "")),
            (("-", "-", "2x2"), (False, "")),
            ((str(one), "1", "2x2"), (False, "kept (HOS_HALF_RATE_SHADING=1")),
            ((str(one), "0", "-"), (True, "dropped")),
        ]
        for args, (dropped, note) in cases:
            done = subprocess.run([str(exe)] + list(args), capture_output=True, text=True, timeout=60, creationflags=flags)
            out = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)
            want_file = "(unset)" if dropped or args[0] == "-" else args[0]
            want_vrs = "(unset)" if args[2] == "-" else args[2]
            ok = (not done.returncode and out.get("vrs_file") == want_file and out.get("vrs") == want_vrs and
                  (note in out.get("note", "") if note else out.get("note") == ""))
            if ok and dropped and "HOS_HALF_RATE_SHADING=1 keeps it" not in out.get("note", ""):
                ok = False
            if not ok:
                problems.append("%s: %s" % (args, (done.stdout + done.stderr).strip()))
    if problems:
        fail("\n  ".join([""] + problems))
    print("PASS: RADV_FORCE_VRS_CONFIG_FILE dropped when it names a file, kept with HOS_HALF_RATE_SHADING=1, left alone otherwise; "
          "RADV_FORCE_VRS untouched; called before Vulkan on Linux (%d cases)" % len(cases))


if __name__ == "__main__":
    main()
