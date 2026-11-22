"""The movie decoder's catch-up is bounded by what a decode takes lately: an acquire stops decoding ahead when a decode
takes longer than the gap between two pictures, or once it has decoded for one gap (host/video_catchup.h, host/nn_video.c
decode_next, queue_frame and dec_acquire; no game, no FFmpeg).

(Triforce, 11-22, the performance audit's THREAD-82, after Source A's.) dec_acquire skips the pictures behind the
movie's clock and decodes the next ones to skip them too, with no bound but a guard of 600 steps. With a decoder slower
than the movie each picture decoded to catch up puts the clock further ahead: an acquire decoded hundreds of pictures
with its lock held and threw them away, and the next one started further behind. HOS_VIDEO_UNBOUNDED_CATCHUP=1 keeps
that.

On every system this compiles video_catchup.h alone (the gap from the pictures' own times, counted again from a movie
that loops; the decode time as seven parts old and one new; when the catch-up stops) and reads the source: each picture
gives its time to the gap, each decode that gave a picture its duration; the catch-up asks the rule before it decodes
ahead, with the time this acquire has spent; the switch is read once and is in the switches table.

On Windows it also compiles nn_video.c whole over tests/video_standins.h and plays a movie of 600 pictures 16.68 ms
apart on a clock a decode moves, the game taking a picture a frame and stalling for a second after the twelfth:
- a decoder of 19.5 ms a picture: no acquire decodes more than one picture ahead, and none at all once the decode time
  is known to be over the gap; the movie's line says it is slower than the movie plays. With the switch, the acquire
  after the stall decodes more than 50, as before;
- a decoder of 4 ms: it catches up with the clock within 40 acquires of the stall, a few pictures an acquire;
- a first decode of 200 ms, then 2 ms: the same (one slow decode does not stop the catch-up for good);
- HOS_VIDEO_NO_CATCHUP=1: nothing skipped, as before.
The whole movie is submitted at once, as the game did before the decoder's input limit (IO-34), which the runs turn off
with HOS_VIDEO_INPUT_LIMIT=0: with it an acquire has 16 submissions at most to decode ahead, and this rule is the only
bound under test here.

    python -I -B tests/test_video_catchup.py [--cc clang]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_fixture as vf   # noqa: E402

RUN_ALL_ARGS = ["--cc", "clang"]

RULES = r"""
#include <stdio.h>
#include <string.h>
#include "video_catchup.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    const int64_t gap = 16683333, ms = 1000000;
    VideoPace p;
    memset(&p, 0, sizeof p);
    CHECK(video_pace_spacing(&p) == 0);
    video_pace_picture(&p, 5 * gap);
    CHECK(video_pace_spacing(&p) == 0);                      /* (one picture: no gap yet) */
    for (int i = 6; i < 30; i++) video_pace_picture(&p, i * gap);
    CHECK(p.n == 25 && video_pace_spacing(&p) == gap);
    video_pace_picture(&p, 0);                                 /* a loop: counted again from it */
    CHECK(p.n == 1 && video_pace_spacing(&p) == 0);
    video_pace_picture(&p, 2 * gap), video_pace_picture(&p, 4 * gap);
    CHECK(video_pace_spacing(&p) == 2 * gap);
    video_pace_picture(&p, 4 * gap);                           /* (the same time twice: not a loop) */
    CHECK(p.n == 4 && video_pace_spacing(&p) == 4 * gap / 3);

    /* the decode time: seven parts old, one new. 19.5 ms decodes pass a 16.68 ms gap at the 15th, and stay */
    memset(&p, 0, sizeof p);
    int over = 0;
    for (int i = 1; i <= 40 && !over; i++) {
        video_pace_decoded(&p, 19500000);
        if (p.recent_ns > gap) over = i;
    }
    CHECK(over == 15);
    for (int i = 0; i < 100; i++) video_pace_decoded(&p, 19500000);
    CHECK(p.recent_ns > 19 * ms && p.recent_ns <= 19500000);
    /* one slow decode is forgotten: 200 ms, then 2 ms ones */
    memset(&p, 0, sizeof p);
    video_pace_decoded(&p, 200 * ms);
    CHECK(p.recent_ns == 25 * ms);
    for (int i = 0; i < 4; i++) video_pace_decoded(&p, 2 * ms);
    CHECK(p.recent_ns < gap);
    video_pace_decoded(&p, -7);                                /* (a clock that went back: as 0) */
    CHECK(p.recent_ns >= 0);

    /* video_catchup_stop(unbounded, gap, recent, spent in this acquire) */
    CHECK(!video_catchup_stop(0, gap, 4 * ms, 0));             /* a fast decoder: on */
    CHECK(!video_catchup_stop(0, gap, 4 * ms, 16 * ms));       /* ... while this acquire has decoded for less than a gap */
    CHECK(video_catchup_stop(0, gap, 4 * ms, gap));            /* ... and not past it */
    CHECK(video_catchup_stop(0, gap, 19500000, 0));            /* a decoder slower than the movie: not at all */
    CHECK(!video_catchup_stop(0, gap, gap, 0));                /* (as long as the gap exactly: on) */
    CHECK(!video_catchup_stop(0, 0, 19500000, 5000 * ms));     /* the gap not known yet: as before */
    CHECK(!video_catchup_stop(0, -gap, 19500000, 5000 * ms));
    CHECK(!video_catchup_stop(1, gap, 19500000, 5000 * ms));   /* the switch: never */
    return fails ? 1 : 0;
}
"""

MOVIE = r"""
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(int argc, char **argv) {
    CHECK(argc == 3);
    const int64_t gap = 16683333;
    si.decode_ns = atoll(argv[1]), si.first_decode_ns = atoll(argv[2]);
    si_open(64, 36, 2, 0);
    for (int i = 0; i < 600; i++) CHECK(si_submit(i * gap, i == 599) == 0);   /* (the whole movie at once, as the game does) */
    Dec *d = si_dec();
    for (int a = 0; a < 200; a++) {
        const int64_t before = si.decodes, skipped = d->movie.skipped;
        const int b = si_acquire();
        CHECK(b >= 0);
        int last = 0;
        const int64_t pts = si_pts(b, &last);
        printf("acquire %d: %lld decodes, %lld skipped, behind %lld ms\n", a, (long long)(si.decodes - before),
               (long long)(d->movie.skipped - skipped), (long long)((si_now - d->clock_ns - (pts - d->clock_pts)) / 1000000));
        si_release(b);
        if (last) break;
        si_now += gap;                          /* the game's frame */
        if (a == 11) si_now += 1000000000;      /* ... and one of a second */
    }
    si_stop();
    fputs(si_log, stdout);
    return fails ? 1 : 0;
}
"""


def acquires(out, case, at_least=100):
    rows = [tuple(int(x) for x in m) for m in re.findall(r"^acquire (\d+): (\d+) decodes, (\d+) skipped, behind (-?\d+) ms$", out, re.M)]
    vf.check("FAIL:" not in out and len(rows) >= at_least, case + ":\n" + out[-3000:])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    video = vf.video_source()

    vf.check('#include "video_catchup.h"' in video and "VideoPace pace;" in vf.block(video, "typedef struct {\n    AVCodecContext *ctx;"),
             "nn_video.c does not keep the movie's pace in its decoder")
    vf.check("video_pace_picture(&d->pace, f->pts);" in vf.block(video, "static void queue_frame(Dec *d, const AVFrame *f) {"),
             "queue_frame does not give each picture's time to the gap")
    nxt = vf.block(video, "static void decode_next(Dec *d) {")
    vf.check("const int64_t pictures = d->movie.pictures;" in nxt
             and "if (d->movie.pictures != pictures) video_pace_decoded(&d->pace, took);" in nxt,
             "decode_next does not keep what a decode that gave a picture took")
    vf.check("memset(&d->pace, 0, sizeof d->pace);" in vf.block(video, "static void movie_end(Dec *d) {"),
             "a movie's end does not start the pace again")
    acquire = vf.block(video, "static void dec_acquire(Ctx *c) {")
    read_once = 'unbounded = getenv("HOS_VIDEO_UNBOUNDED_CATCHUP") != NULL && atoi(getenv("HOS_VIDEO_UNBOUNDED_CATCHUP")) != 0;'
    stop = "if (video_catchup_stop(unbounded, video_pace_spacing(&d->pace), d->pace.recent_ns, hos_now_ns() - now)) {"
    vf.check("static int off = -1, unbounded = -1;" in acquire and "if (unbounded < 0)" in acquire and read_once in acquire,
             "HOS_VIDEO_UNBOUNDED_CATCHUP is not read once")
    vf.check(stop in acquire, "the catch-up does not ask the rule with the time this acquire has spent")
    loop = acquire[acquire.index("for (int guard = 0;"):]
    loop = loop[:loop.index("if (skipped && video_log())")]
    vf.check(loop.count("decode_next(d);") == 1 and loop.index("if (!d->phead) break;") < loop.index(stop) < loop.index("decode_next(d);"),
             "the catch-up decodes ahead before it asks the rule")
    vf.check('getenv("HOS_VIDEO_NO_CATCHUP")' in acquire and "guard < 600" in acquire, "the catch-up lost its switch or its guard")
    dev = (vf.ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    vf.check("`HOS_VIDEO_UNBOUNDED_CATCHUP=1`" in dev, "docs/development.md: HOS_VIDEO_UNBOUNDED_CATCHUP=1 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="video-catchup-") as tmp:
        src, exe = Path(tmp) / "rules.c", Path(tmp) / "rules.exe"
        src.write_text(RULES, encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(vf.HOST), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        vf.check(r.returncode == 0, "the pace or the catch-up's rule:\n" + r.stdout)
        if not vf.WINDOWS:
            print(vf.WINDOWS_ONLY)
            print("PASS: the movie catch-up is bounded by the recent decode time (the rule and the source)")
            return
        exe = vf.build(tmp, args.cc, MOVIE)

        # a decoder slower than the movie: 19.5 ms a picture against 16.68
        out = vf.run(exe, "19500000", "0", HOS_VIDEO_INPUT_LIMIT="0")
        rows = acquires(out, "19.5 ms decodes")
        # (one decode for the picture shown, and at most one ahead)
        vf.check(max(r[1] for r in rows) <= 2, "19.5 ms decodes: an acquire decoded %d pictures" % max(r[1] for r in rows))
        vf.check(all(r[1] == 1 and r[2] == 0 for r in rows[40:]),
                 "19.5 ms decodes: the catch-up still decodes ahead once a decode is known to take longer than the gap")
        vf.check(re.search(r"^video: a movie of \d+ pictures on libdav1d: 19\.50 ms to decode each \(worst 19\.50\), one shown every "
                           r"16\.68 ms \(slower than it plays\); \d+ skipped to catch up$", out, re.M) is not None,
                 "19.5 ms decodes: the movie's line does not say the decoder is slower than the movie plays:\n" + out[-600:])
        out = vf.run(exe, "19500000", "0", HOS_VIDEO_UNBOUNDED_CATCHUP="1", HOS_VIDEO_INPUT_LIMIT="0")
        rows = acquires(out, "19.5 ms decodes, unbounded", 13)   # (it skips to the movie's end long before 100 acquires)
        vf.check(rows[12][1] > 50 and rows[12][2] > 50,
                 "HOS_VIDEO_UNBOUNDED_CATCHUP=1: the acquire after the stall decoded %d pictures, not all it was behind by" % rows[12][1])
        out = vf.run(exe, "19500000", "0", HOS_VIDEO_UNBOUNDED_CATCHUP="0", HOS_VIDEO_INPUT_LIMIT="0")
        vf.check(max(r[1] for r in acquires(out, "19.5 ms decodes, =0")) <= 2, "HOS_VIDEO_UNBOUNDED_CATCHUP=0 is taken as the switch")

        # decoders faster than the movie catch up: a few pictures an acquire, until the picture shown is in time again
        for case, first in (("4 ms decodes", "0"), ("a first decode of 200 ms, then 2 ms", "200000000")):
            out = vf.run(exe, "4000000" if first == "0" else "2000000", first, HOS_VIDEO_INPUT_LIMIT="0")
            rows = acquires(out, case)
            vf.check(rows[12][3] > 700, "%s: the stall did not leave the movie most of a second behind (%d ms)" % (case, rows[12][3]))
            vf.check(max(r[3] for r in rows[52:]) <= 45, "%s: still %d ms behind 40 acquires after the stall" % (case, max(r[3] for r in rows[52:])))
            vf.check(sum(r[2] for r in rows[12:52]) >= 50, "%s: the catch-up skipped %d pictures" % (case, sum(r[2] for r in rows[12:52])))
            vf.check(2 <= max(r[1] for r in rows) <= 12, "%s: an acquire decoded %d pictures" % (case, max(r[1] for r in rows)))
            vf.check("(slower than it plays)" not in out and "one shown every 16.68 ms; " in out, case + ": the movie's line:\n" + out[-600:])

        out = vf.run(exe, "4000000", "0", HOS_VIDEO_NO_CATCHUP="1", HOS_VIDEO_INPUT_LIMIT="0")
        rows = acquires(out, "no catch-up")
        vf.check(all(r[1] == 1 and r[2] == 0 for r in rows), "HOS_VIDEO_NO_CATCHUP=1: pictures were decoded ahead or skipped")
    print("PASS: the movie catch-up stops when a decode takes longer than a picture's gap, or after one gap of decoding")


if __name__ == "__main__":
    main()
