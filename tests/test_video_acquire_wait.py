"""A movie's Acquire waits for a picture up to 100 ms by the clock, not at all after a Stop or Flush with nothing submitted
since, and decodes without the thread's virtual core (host/nn_video.c dec_acquire).

The wait was 50 sleeps of 2 ms, each 4-5 ms long on Windows: ~250 ms after a movie's Stop, a frame that long at every load
from the title, while the decode held the game thread's core. host/nn_video.c's decoder record, Submit, Stop/Flush and
Acquire are cut out unchanged and run by tests/video_acquire_test.c over a clock that moves 5 ms at each sleep, a decoder
whose one picture comes out at a set time, and a watched virtual core. Checked: the wait ends at 100 ms; none after a Stop;
a picture still due is waited for, after a Stop and a new submission too; the decode runs without the core, which is
taken back at every exit and never under the decoder's lock; HOS_VIDEO_ACQUIRE_TRIES=1 and HOS_VIDEO_KEEP_CORE=1 as
before.

    python -I -B tests/test_video_acquire_wait.py [--cc gcc] [--source host/nn_video.c]
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
RESULT = re.compile(r"^RESULT (\w+) elapsed_ms=(\d+) ret=(\S+) index=(-?\d+) decodes=(\d+) decoded_with_core=(\d+) "
                    r"back_under_lock=(\d+) slept_under_lock=(\d+) core=(\d+) locks=(\d+) delivered=(\d+)$", re.M)


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def typedef(source, first, last):
    start = source.rindex("typedef struct", 0, source.index(first))
    return source[start:source.index(last, start) + len(last)]


def cut(source):
    types = "\n".join([
        typedef(source, "int w, h, format, count;", "} Pool;"),
        typedef(source, "uint8_t *rgba, *nv12; int w, h; int64_t pts; int last; }", "} Picture;"),
        typedef(source, "AVPacket *pkt; struct Pending *next; }", "} Pending;"),
        typedef(source, "AVCodecContext *ctx;", "} Dec;"),
    ])
    calls = "\n".join(block(source, marker) for marker in (
        "static void dec_submit(Ctx *c) {", "static void dec_flush(Ctx *c, const char *what) {",
        "static void dec_acquire(Ctx *c) {"))
    return types, calls


def run_case(binary, case, extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_VIDEO")}
    env.update(extra)
    done = subprocess.run([str(binary), case], env=env, capture_output=True, text=True, timeout=60)
    m = RESULT.search(done.stdout)
    if done.returncode or not m or m.group(1) != case:
        print(done.stdout + done.stderr)
        fail("%s: the fixture failed (exit %d)" % (case, done.returncode))
    keys = ("elapsed", "ret", "index", "decodes", "with_core", "back_under_lock", "slept_under_lock", "core", "locks",
            "delivered")
    values = dict(zip(keys, m.groups()[1:]))
    return {k: int(v, 0) for k, v in values.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--source", type=Path, default=ROOT / "host/nn_video.c")
    args = parser.parse_args()
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit("C compiler not found: " + args.cc)
    try:
        types, calls = cut(args.source.read_text(encoding="utf-8"))
    except ValueError as e:
        fail("a text this test reads moved (%s)" % e)
    problems = []
    with tempfile.TemporaryDirectory(prefix="video-acquire-") as temporary:
        folder = Path(temporary)
        (folder / "video_acquire_types.inc").write_text(types, encoding="utf-8")
        (folder / "video_acquire_block.inc").write_text(calls, encoding="utf-8")
        binary = folder / "fixture.exe"
        built = subprocess.run([compiler, "-std=gnu17", "-O1", "-Wall", "-Wno-unused-function", "-I" + str(folder),
                                str(ROOT / "tests/video_acquire_test.c"), "-o", str(binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")

        def check(case, extra, want, label):
            r = run_case(binary, case, extra)
            for what, ok in want(r):
                if not ok:
                    problems.append("%s (%s): %s; %s" % (case, label, what, r))
            return r

        def common(r):
            return [("the core is held again at the end", r["core"] == 1), ("no lock left held", r["locks"] == 0),
                    ("the core never taken back under the lock", r["back_under_lock"] == 0),
                    ("no sleep under the lock", r["slept_under_lock"] == 0)]

        default = {}
        check("empty", default, lambda r: common(r) + [
            ("the wait ends at 100 ms (was ~250)", 100 <= r["elapsed"] < 110),
            ("a buffer as it was, not refused", r["ret"] == 0 and r["index"] == 0),
            ("the decode ran without the core", r["with_core"] == 0)], "default")
        check("stopped", default, lambda r: common(r) + [
            ("no wait after a Stop", r["elapsed"] == 0),
            ("a buffer as it was, not refused", r["ret"] == 0 and r["index"] == 0)], "default")
        check("resubmit", default, lambda r: common(r) + [
            ("a submission after the Stop is waited for", r["delivered"] == 1 and 30 <= r["elapsed"] < 40),
            ("the decode ran without the core", r["with_core"] == 0)], "default")
        check("pending", default, lambda r: common(r) + [
            ("a picture 60 ms away is waited for", r["delivered"] == 1 and 60 <= r["elapsed"] < 70),
            ("the decode ran without the core", r["with_core"] == 0)], "default")
        check("noslot", default, lambda r: common(r) + [
            ("no buffer: refused", r["ret"] == 0x2a1ca)], "default")
        tries = {"HOS_VIDEO_ACQUIRE_TRIES": "1"}
        check("empty", tries, lambda r: common(r) + [("the 50 sleeps as before", r["elapsed"] == 250)],
              "HOS_VIDEO_ACQUIRE_TRIES=1")
        check("stopped", tries, lambda r: common(r) + [("the 50 sleeps as before", r["elapsed"] == 250)],
              "HOS_VIDEO_ACQUIRE_TRIES=1")
        keep = {"HOS_VIDEO_KEEP_CORE": "1"}
        check("pending", keep, lambda r: common(r) + [
            ("the core held while decoding, as before", r["with_core"] == r["decodes"] > 0),
            ("the picture still handed out", r["delivered"] == 1)], "HOS_VIDEO_KEEP_CORE=1")
    if problems:
        fail("\n  ".join([""] + problems))
    print("PASS: the movie's wait ends at 100 ms, none after a Stop, a due picture still waited for, the decode without the "
          "core and the core never taken under the lock; both switches as before (8 cases)")


if __name__ == "__main__":
    main()
