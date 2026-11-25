"""XInput's triggers press only once they have read let go for a second since their controller was connected
(host/nn_hid.c, xinput_trigger), as SDL's do (host/pad_sdl.c trigger_pull, tests/test_trigger_rest.py).

A device whose trigger reads held for good held ZL or ZR for every pad when XInput's pads are the ones read (SDL has
none, or HOS_XINPUT=1). xinput_trigger is cut out of the source and compiled over a stand-in log, polled every 2 ms
as XInput's thread does:

- a trigger held from the connection never presses, nor one let go only for moments;
- a trigger at rest at the connection presses from its first pull after a second, and lets go at the threshold;
- one pulled in the first second presses once it has been let go for a second; each trigger and slot is its own;
- a second without polls in it does not count as a second let go; a new connection starts again;
- the log says once that a trigger does not count, 3 s after the connection, not before.

python -I -B tests/test_xinput_trigger_rest.py [--cc clang]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host/nn_hid.c").read_text(encoding="utf-8")
    at = src.index("#define XINPUT_TRIGGER_REST_NS")
    cut = src[at:src.index("static void xinput_poll(", at)]
    poll = src[src.index("static void xinput_poll("):]
    poll = poll[:poll.index("\n}\n")]
    for line in ("const int fresh = !xinput_was[p];",
                 "if (xinput_trigger(p, 0, xs.Gamepad.bLeftTrigger, now, fresh)) raw |= 1ULL << HOS_PAD_LTRIGGER;",
                 "if (xinput_trigger(p, 1, xs.Gamepad.bRightTrigger, now, fresh)) raw |= 1ULL << HOS_PAD_RTRIGGER;"):
        if line not in poll:
            raise SystemExit("FAIL: xinput_poll lacks: " + line)
    if "bLeftTrigger > 64" in poll or "bRightTrigger > 64" in poll:
        raise SystemExit("FAIL: xinput_poll presses a trigger past xinput_trigger")
    fixture = r'''#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#define XUSER_MAX_COUNT 4
static int said;
static void hos_log(const char *f, ...) { (void)f; said++; }
''' + cut + r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); return 1; } } while (0)
#define MS 1000000LL
static int64_t now = 5000 * MS;
/* polls slot p's trigger t at reading a for ms milliseconds, every 2 ms: how many polls pressed */
static int run(int p, int t, int a, int ms, int fresh) {
    int pressed = 0;
    for (int i = 0; i < ms / 2; i++) { now += 2 * MS; pressed += xinput_trigger(p, t, a, now, fresh && !i); }
    return pressed;
}
int main(void) {
    /* held from the connection: never, and said once after 3 s */
    CHECK(run(0, 0, 255, 2900, 1) == 0 && said == 0);
    CHECK(run(0, 0, 255, 4000, 0) == 0 && said == 1);
    /* let go for moments only: still never */
    for (int i = 0; i < 5; i++) { CHECK(run(0, 0, 0, 500, 0) == 0); CHECK(run(0, 0, 200, 500, 0) == 0); }
    /* let go for a second: counts from the next pull, and stays counted through a long hold */
    CHECK(run(0, 0, 10, 1100, 0) == 0);
    CHECK(run(0, 0, 65, 100, 0) == 50 && run(0, 0, 64, 100, 0) == 0 && run(0, 0, 255, 5000, 0) == 2500);
    CHECK(said == 1);
    /* the right trigger of the same slot, at rest at the connection: its own second */
    CHECK(run(0, 1, 0, 600, 1) == 0 && run(0, 1, 255, 100, 0) == 0);    /* (pulled in the first second) */
    CHECK(run(0, 1, 0, 990, 0) == 0 && run(0, 1, 255, 100, 0) == 0);    /* (let go, but not for a second) */
    CHECK(run(0, 1, 0, 1010, 0) == 0 && run(0, 1, 255, 100, 0) == 50);
    /* another slot: its own; a second with no polls in it is no second let go */
    CHECK(run(2, 0, 0, 400, 1) == 0);
    now += 3000 * MS;
    CHECK(run(2, 0, 255, 100, 0) == 0);
    CHECK(run(2, 0, 0, 1010, 0) == 0 && run(2, 0, 255, 100, 0) == 50);
    /* connected again: starts again */
    CHECK(run(2, 0, 255, 100, 1) == 0 && run(2, 0, 0, 1010, 0) == 0 && run(2, 0, 255, 10, 0) == 5);
    puts("ok");
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as d:
        c = Path(d) / "t.c"
        c.write_text(fixture, encoding="utf-8")
        exe = Path(d) / ("t.exe" if sys.platform == "win32" else "t")
        r = subprocess.run([a.cc, "-O1", "-o", str(exe), str(c)], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("FAIL: the fixture does not compile:\n" + r.stderr)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        if r.returncode or "ok" not in r.stdout:
            raise SystemExit("FAIL: " + r.stderr + r.stdout)
    print("PASS: XInput's triggers press only once they have read let go for a second since the connection")


if __name__ == "__main__":
    main()
