"""A movie's picture is not handed out ahead of its clock: the one before is shown again (host/nn_video.c dec_acquire).

The game takes a movie's next picture when its own count of the movie's 60ths says so (hos_movie_frames, host/nn_vi.c).
While a movie plays at the 60 cap the frames are paced at 240 (host/movie_pace.h), and the count then follows the
frames' time, not the clock: the opening's picture ran ahead of its clock, 0.2 s after 6 s and 0.73 s by its end, while
its sound kept the clock, so the sound came late. dec_acquire already skips pictures that are late
(tests/test_video_catchup.py); a picture more than 25 ms early is now held back, and the buffer handed out shows the
last picture again. Not the first picture of a movie, not its last, and not into a pool the game reads from memory (no
copy is made there). HOS_VIDEO_NO_HOLD=1 hands every picture out when asked, as before.

On every system this reads the source. On Windows it also compiles nn_video.c whole over tests/video_standins.h and
plays a movie of 300 pictures 16.68 ms apart, the game taking a picture every 15 ms (a tenth too fast), its pools read
through ReadDecoderOutputImage* as OoT's are:
- no picture is handed out more than 25 ms ahead of the movie's clock, the held buffers show the last picture again
  (its time, and its bytes in the other buffer), every picture is still shown in order, and the movie's end says how
  often the last was shown again;
- HOS_VIDEO_NO_HOLD=1: the picture runs ahead, over 300 ms by the end, as before;
- pools the game reads from its own memory: nothing held.

    python -I -B tests/test_video_hold_early.py [--cc clang]
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_fixture as vf   # noqa: E402

RUN_ALL_ARGS = ["--cc", "clang"]

MOVIE = r"""
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(int argc, char **argv) {
    CHECK(argc == 2);
    const int by_api = atoi(argv[1]);   /* (the pools read through ReadDecoderOutputImage*, as OoT's) */
    const int64_t gap = 16683333, frame = 14000000;   /* (and a decode a picture moves the clock 1 ms: 15 ms a picture) */
    si.decode_ns = 1000000;   /* (the stand-in clock moves with each decode) */
    si_open(64, 36, 2, 0);
    for (int i = 0; i < 2; i++) si_pool(i)->read_by_api = by_api;
    int next = 0;
    Dec *d = si_dec();
    int64_t shown_pts = -1, pictures = 0, held = 0, ahead_most = 0;
    int was = -1;
    for (int a = 0; a < 2000; a++) {
        CHECK(si_feed(&next, 300, gap) >= 0);
        const int b = si_acquire();
        CHECK(b >= 0);
        int last = 0;
        const int64_t pts = si_pts(b, &last);
        const int64_t ahead = (pts - d->clock_pts) - (si_now - d->clock_ns);
        if (ahead > ahead_most) ahead_most = ahead;
        if (pts == shown_pts) {
            held++;
            /* the last picture again: the same bytes as the buffer that had it */
            if (was >= 0 && was != b)
                CHECK(!memcmp(si_pool(b)->nv12, si_pool(was)->nv12, (size_t)si_pool(b)->w * si_pool(b)->h * 3 / 2));
        } else {
            CHECK(pts > shown_pts);                                  /* in order */
            if (shown_pts >= 0) CHECK(pts - shown_pts < gap + 1000);   /* and none left out: the next one */
            pictures++;
        }
        shown_pts = pts;
        if (was >= 0) si_release(was);   /* (the game keeps the buffer it shows until it has the next) */
        was = b;
        if (last) break;
        si_now += frame;
    }
    printf("pictures %lld, held %lld, ahead most %lld ms, counted %lld\n", (long long)pictures, (long long)held,
           (long long)(ahead_most / 1000000), (long long)d->held);
    si_stop();
    fputs(si_log, stdout);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    video = vf.video_source()

    acquire = vf.block(video, "static void dec_acquire(Ctx *c) {")
    vf.check('no_hold = getenv("HOS_VIDEO_NO_HOLD") != NULL' in acquire and "static int no_hold = -1;" in acquire,
             "HOS_VIDEO_NO_HOLD is not read once in dec_acquire")
    vf.check("!next->last" in acquire and "to->read_by_api && from->read_by_api" in acquire,
             "the hold does not leave out the last picture, or pools the game reads from memory")
    vf.check(acquire.index("d->movie.skipped += skipped;") < acquire.index("static int no_hold = -1;") < acquire.index("Picture *p = &d->queue[d->qhead];"),
             "the hold is not between the catch-up and the picture handed out")
    vf.check("d->held = 0, d->shown_slot = 0;" in vf.block(video, "static void movie_end(Dec *d) {"),
             "a movie's end does not start the holds again: the next movie's first picture could be held")

    if not vf.WINDOWS:
        print(vf.WINDOWS_ONLY)
        print("PASS: a movie's early picture is held back (the source)")
        return
    with tempfile.TemporaryDirectory(prefix="video-hold-early-") as tmp:
        exe = vf.build(tmp, args.cc, MOVIE)

        def numbers(out, case):
            m = re.search(r"^pictures (\d+), held (\d+), ahead most (-?\d+) ms, counted (\d+)$", out, re.M)
            vf.check("FAIL:" not in out and m is not None, case + ":\n" + out[-3000:])
            return tuple(int(x) for x in m.groups())

        out = vf.run(exe, "1")
        pictures, held, ahead, counted = numbers(out, "the hold")
        vf.check(pictures == 300, "the hold: %d of the movie's 300 pictures were shown" % pictures)
        vf.check(ahead <= 25, "the hold: a picture was handed out %d ms ahead of the movie's clock" % ahead)
        vf.check(20 <= held <= 45 and counted == held, "the hold: the last picture was shown again %d times (counted %d), "
                 "for a game a tenth too fast over 300 pictures" % (held, counted))
        vf.check(re.search(r"^video: %d times the last picture was shown again, the next one ahead of the movie's clock$" % held,
                           out, re.M) is not None, "the hold: the movie's end does not say how often:\n" + out[-600:])

        out = vf.run(exe, "1", HOS_VIDEO_NO_HOLD="1")
        pictures, held, ahead, counted = numbers(out, "HOS_VIDEO_NO_HOLD=1")
        vf.check(pictures == 300 and held == 0 and counted == 0 and ahead > 300,
                 "HOS_VIDEO_NO_HOLD=1: %d pictures, %d held, %d ms ahead at most: not as before" % (pictures, held, ahead))
        vf.check("shown again" not in out, "HOS_VIDEO_NO_HOLD=1: the log speaks of pictures shown again")

        out = vf.run(exe, "0")
        pictures, held, ahead, counted = numbers(out, "pools read from memory")
        vf.check(pictures == 300 and held == 0 and counted == 0,
                 "pools the game reads from its memory: %d pictures, %d held" % (pictures, held))
    print("PASS: a movie's picture more than 25 ms ahead of its clock waits, and the last is shown again")


if __name__ == "__main__":
    main()
