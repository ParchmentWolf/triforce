"""The guest window is a memfd's when /dev/udmabuf opens, even when udmabuf's size limit cannot be read (host/hos_main.c, the
window's setup on Linux; HOS_GUEST_MEMFD; no game).

Flatpak and other sandboxes hide /sys/module while /dev/udmabuf opens, and the window stayed anonymous memory there: amdgpu checks
every page of a host-pointer import again at each submission, 15-45 ms a submission. The limit file now decides only when it
reads 0 (udmabuf then refuses every dma-buf); unreadable, it counts as udmabuf's default, 64 MB, as the renderer takes it.

The rule, from HOS_GUEST_MEMFD's read to the test that makes the memfd, is cut out of hos_main.c unchanged and compiled with
stand-ins for open, close and the limit file (any compiler: the rule has no Linux calls of its own). Checked: usable with the limit
file missing (the 64 MB line logged), holding 64, 256, x or nothing; not with 0 or when /dev/udmabuf does not open (the line that
says why logged); HOS_GUEST_MEMFD=1 and =0 over all of them; HOS_GUEST_MEMFD has its docs row.

    python -I -B tests/test_udmabuf_limit_unreadable.py [--cc clang]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#ifndef O_RDWR
#define O_RDWR 2
#endif
#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
static int dev_opens;
static const char *limit_path;   /* (NULL: the limit file missing) */
static int fake_open(const char *p, int flags) { (void)flags; return !strcmp(p, "/dev/udmabuf") && dev_opens ? 5 : -1; }
static int fake_close(int fd) { (void)fd; return 0; }
static FILE *fake_fopen(const char *p, const char *mode) {
    if (strcmp(p, "/sys/module/udmabuf/parameters/size_limit_mb")) return NULL;
    return limit_path ? fopen(limit_path, mode) : NULL;
}
static char logged[4096];
static void hos_log(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    vsnprintf(logged + strlen(logged), sizeof logged - strlen(logged), fmt, a);
    va_end(a);
    strncat(logged, "\n", sizeof logged - strlen(logged) - 1);
}
#define open fake_open
#define close fake_close
#define fopen fake_fopen
static int memfd_chosen(void) {
@CUT@
        return 1;
    }
    return 0;
}
int main(int argc, char **argv) {
    dev_opens = atoi(argv[1]);
    limit_path = argc > 2 ? argv[2] : NULL;
    printf("%d\n%s", memfd_chosen(), logged);
    return 0;
}
'''

# (/dev/udmabuf opens, the limit file's text or None for missing, HOS_GUEST_MEMFD or None) -> (memfd chosen, a text the log has)
CASES = [
    ((1, None, None), (1, "udmabuf's size_limit_mb cannot be read (in a container?): its default, 64 MB, assumed")),
    ((1, "64\n", None), (1, None)),
    ((1, "256\n", None), (1, None)),
    ((1, "x\n", None), (1, None)),
    ((1, "", None), (1, None)),
    ((1, "0\n", None), (0, "udmabuf's size_limit_mb is 0")),
    ((0, "64\n", None), (0, "/dev/udmabuf cannot be opened")),
    ((0, None, None), (0, "/dev/udmabuf cannot be opened")),
    ((0, None, "1"), (1, None)),
    ((1, "0\n", "1"), (1, None)),
    ((1, None, "0"), (0, None)),
    ((1, "64\n", "0"), (0, None)),
]


def fail(message):
    raise SystemExit("FAIL: " + message)


def cut(main):
    start = main.index('        const char *e = getenv("HOS_GUEST_MEMFD");')
    end = main.index("        if (e ? atoi(e) != 0 : usable) {", start)
    return main[start:end] + "        if (e ? atoi(e) != 0 : usable) {\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    try:
        text = FIXTURE.replace("@CUT@", cut(src))
    except ValueError as e:
        fail("a text this test reads moved (%s)" % e)
    if "`HOS_GUEST_MEMFD=0`" not in dev:
        fail("docs/development.md has no HOS_GUEST_MEMFD row")
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    problems = []
    with tempfile.TemporaryDirectory(prefix="udmabuf-limit-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        c.write_text(text, encoding="utf-8")
        built = subprocess.run([a.cc, "-std=gnu17", "-O1", "-Wall", "-Wno-unused-function", str(c), "-o", str(exe)],
                               capture_output=True, text=True, creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        base = {k: v for k, v in os.environ.items() if k != "HOS_GUEST_MEMFD"}
        for i, ((opens, limit, switch), (want, line)) in enumerate(CASES):
            args = [str(exe), str(opens)]
            if limit is not None:
                path = Path(tmp) / ("limit%d" % i)
                path.write_text(limit, encoding="ascii")
                args.append(str(path))
            env = dict(base, **({"HOS_GUEST_MEMFD": switch} if switch is not None else {}))
            done = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60, creationflags=flags)
            out = done.stdout.split("\n", 1)
            got = int(out[0]) if not done.returncode and out[0].strip() in ("0", "1") else None
            log = out[1] if len(out) > 1 else ""
            if got != want or (line and line not in log):
                problems.append("udmabuf %s, limit %r, HOS_GUEST_MEMFD=%r: memfd %s (wanted %d), log %r"
                                % ("opens" if opens else "does not open", limit, switch, got, want, log.strip()))
    if problems:
        fail("\n  ".join([""] + problems))
    print("PASS: the guest window a memfd's where /dev/udmabuf opens, its limit unreadable too; not with a limit of 0 or no "
          "udmabuf; HOS_GUEST_MEMFD over both (%d cases)" % len(CASES))


if __name__ == "__main__":
    main()
