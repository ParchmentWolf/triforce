"""AV1 movies on Windows: dav1d first where the FFmpeg has it, and one line a movie with what it took to decode
(host/video_av1.h, host/video_movie.h, host/nn_video.c dec_init_sized, decode_next, dec_flush and dec_finalize; no game,
no FFmpeg, no Media Foundation).

(Triforce, 11-22, the performance audit's IO-32, after Source A's.) Windows decoded the game's 1080p AV1 movies with
Media Foundation first, in software on every GPU, and with dav1d only on a PC without Microsoft's AV1 extension. Nothing
timed either. Now libdav1d goes first where the FFmpeg the build links has it, Media Foundation where it has not or
where libdav1d does not open, HOS_AV1=mf brings the old order back, and each movie logs its pictures, the mean and the
worst decode time and the pictures skipped.

On every system this compiles the two rule headers alone (the order for each HOS_AV1 with and without libdav1d; the
movie's counts and its line) and reads the source: the order is the rule's, by HOS_AV1 read once; the notice for a PC
with no AV1 decoder stays last; each submission is timed; a Stop, a Flush and a finalize end the movie's line; the
switch is in the switches table.

On Windows it also compiles nn_video.c whole over tests/video_standins.h and opens the AV1 decoder as the game does,
for each case of HOS_AV1, an FFmpeg with and without libdav1d, a libdav1d that does not open and a Media Foundation
with and without a decoder: which decoder the movie got, what was asked for in which order, the notice once and only
with no decoder at all. Then two movies are played: the first says its line once at its Stop (not again at the Flush
after it), the second at the decoder's end, with the pictures skipped while the game took them late.

    python -I -B tests/test_video_av1_order.py [--cc clang]
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
#include "video_av1.h"
#include "video_movie.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    /* libdav1d in the FFmpeg: first, unless HOS_AV1=mf */
    CHECK(!video_av1_mf_first(NULL, 1));
    CHECK(!video_av1_mf_first("dav1d", 1));   /* (the old way to ask for it: the default now) */
    CHECK(video_av1_mf_first("mf", 1));
    CHECK(!video_av1_mf_first("", 1) && !video_av1_mf_first("MF", 1) && !video_av1_mf_first("mfx", 1));
    /* none in it: Media Foundation, whatever is asked */
    CHECK(video_av1_mf_first(NULL, 0) && video_av1_mf_first("dav1d", 0) && video_av1_mf_first("mf", 0));

    VideoMovie m;
    char line[200] = "untouched";
    memset(&m, 0, sizeof m);
    CHECK(!video_movie_line(&m, "libdav1d", 0, line, sizeof line) && !strcmp(line, "untouched"));   /* (no picture: no line) */
    video_movie_decoded(&m, 7000000), m.pictures++;
    video_movie_decoded(&m, 2000000), m.pictures++;
    video_movie_decoded(&m, 0);          /* (the stream's end: a submission with no picture) */
    video_movie_decoded(&m, -5);         /* (a clock that went back: nothing taken off) */
    video_movie_decoded(&m, 3000000), m.pictures++;
    m.skipped = 4;
    CHECK(m.decode_ns == 12000000 && m.worst_ns == 7000000);
    CHECK(video_movie_line(&m, "libdav1d", 0, line, sizeof line));   /* (the gap between pictures not known: left out) */
    CHECK(!strcmp(line, "a movie of 3 pictures on libdav1d: 4.00 ms to decode each (worst 7.00); 4 skipped to catch up"));
    /* (THREAD-82) with the gap: a decoder faster than the movie, then one slower than it plays */
    CHECK(video_movie_line(&m, "libdav1d", 16683333, line, sizeof line));
    CHECK(!strcmp(line, "a movie of 3 pictures on libdav1d: 4.00 ms to decode each (worst 7.00), one shown every 16.68 ms; "
                        "4 skipped to catch up"));
    CHECK(video_movie_line(&m, "libdav1d", 3900000, line, sizeof line));
    CHECK(strstr(line, "(worst 7.00), one shown every 3.90 ms (slower than it plays); 4 skipped to catch up") != NULL);
    char small[16];
    CHECK(video_movie_line(&m, "Media Foundation", 16683333, small, sizeof small) && strlen(small) == 15);   /* (cut, never past) */
    return fails ? 1 : 0;
}
"""

MOVIES = r"""
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static int env_int(const char *name, int otherwise) { return getenv(name) ? atoi(getenv(name)) : otherwise; }
static const char *decoder(void) {
    Dec *d = si_dec();
    return !d ? "no Dec" : d->ctx ? d->ctx->codec->name : d->mf ? "Media Foundation" : "none";
}
int main(void) {
    const int64_t gap = 16683333;   /* (a picture every 16.7 ms) */
    si.have_dav1d = env_int("SI_DAV1D", 1), si.mf_ok = env_int("SI_MF", 1), si.open_fails = env_int("SI_OPEN_FAILS", 0);
    si.decode_ns = 2000000, si.first_decode_ns = 7000000;
    si_open(64, 36, 2, 0);
    printf("decoder %s\norder %s\nthreads %d\n", decoder(), si.order, si_threads);
    si_finalize();
    si.order[0] = 0;
    si_open(64, 36, 2, 0);   /* (a second decoder: the same choice, and the notice not a second time) */
    printf("again %s\norder-again %s\nthreads-again %d\nboxes %d\n", decoder(), si.order, si_threads, si_boxes);
    Dec *d = si_dec();
    if (d->ctx || d->mf) {
        /* the first movie: 12 pictures, each taken in time; a Stop, then a Flush */
        for (int i = 0; i < 12; i++) CHECK(si_submit(i * gap, i == 11) == 0);
        for (int i = 0; i < 12; i++) {
            const int b = si_acquire();
            CHECK(b >= 0 && si_pts(b, NULL) == i * gap);
            si_release(b);
            si_now += gap - 2000000;
        }
        printf("lines-playing %d\n", si_logged("video: a movie of "));
        si_stop();
        printf("lines-stop %d\n", si_logged("video: a movie of "));
        si_flush();
        printf("lines-flush %d\n", si_logged("video: a movie of "));
        /* the second: 40 pictures, the game taking one every three pictures' time; then the decoder's end */
        int next = 0;
        for (int i = 0; i < 9; i++) {
            CHECK(si_feed(&next, 40, gap) >= 0);   /* (as many as the decoder takes: IO-34's input limit) */
            const int b = si_acquire();
            CHECK(b >= 0);
            si_release(b);
            si_now += 3 * gap;
        }
        printf("second %lld pictures, %lld skipped\n", (long long)d->movie.pictures, (long long)d->movie.skipped);
        si_finalize();
        printf("lines-end %d\n", si_logged("video: a movie of "));
    }
    fputs(si_log, stdout);
    return fails ? 1 : 0;
}
"""

# (HOS_AV1, libdav1d in the FFmpeg, Media Foundation has a decoder, libdav1d fails to open) -> the decoder, what was
# asked in order (d libdav1d by name, o its open, M Media Foundation quietly, T Media Foundation telling why), notices
CASES = [
    ((None, 1, 1, 0), "libdav1d", "do", 0),            # the default: dav1d, Media Foundation never asked
    ((None, 1, 0, 0), "libdav1d", "do", 0),            # ... with or without the AV1 extension
    (("dav1d", 1, 1, 0), "libdav1d", "do", 0),         # the old switch for it: the same
    (("mf", 1, 1, 0), "Media Foundation", "dM", 0),    # HOS_AV1=mf: as before
    (("mf", 1, 0, 0), "libdav1d", "dMo", 0),           # ... and dav1d where the extension is missing, as before
    ((None, 0, 1, 0), "Media Foundation", "dM", 0),    # an FFmpeg without libdav1d: Media Foundation
    ((None, 0, 0, 0), "none", "dMT", 1),               # ... and neither: the notice, once
    ((None, 1, 1, 1), "Media Foundation", "doT", 0),   # a libdav1d that does not open: Media Foundation after it
    ((None, 1, 0, 1), "none", "doT", 1),               # ... and the notice when that has none either
]


def value(out, name):
    m = re.search(r"^%s (.*)$" % re.escape(name), out, re.M)
    vf.check(m is not None, "the fixture printed no %r line:\n%s" % (name, out))
    return m.group(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    video = vf.video_source()

    vf.check('#include "video_av1.h"' in video and '#include "video_movie.h"' in video, "nn_video.c does not take the two rule headers")
    first = vf.block(video, "static const char *av1_first(void) {")
    vf.check('if (!read) value = getenv("HOS_AV1"), read = 1;' in first, "HOS_AV1 is not read once")
    init = vf.block(video, "static void dec_init_sized(Ctx *c, enum AVCodecID id, const char *what, int w, int h) {")
    by_name = 'codec = avcodec_find_decoder_by_name("libdav1d");'
    rule = "if (video_av1_mf_first(av1_first(), codec != NULL)) d->mf = mf_av1_open(w, h, 0);"
    told = "d->mf = mf_av1_open(w, h, 1);"
    windows = init[init.index("#ifdef _WIN32"):]
    vf.check(by_name in windows and rule in windows and windows.index(by_name) < windows.index(rule),
             "dec_init_sized does not ask the rule, with libdav1d looked up first")
    vf.check('getenv("HOS_AV1")' not in init, "dec_init_sized reads HOS_AV1 itself")
    vf.check(told in init and init.index(rule) < init.index("avcodec_open2(") < init.index(told) < init.index("av1_notice"),
             "Media Foundation is no longer the fallback of a libdav1d that does not open, with the notice last")
    nxt = vf.block(video, "static void decode_next(Dec *d) {")
    vf.check("const int64_t began = hos_now_ns();" in nxt and "const int64_t took = hos_now_ns() - began;" in nxt
             and "video_movie_decoded(&d->movie, took);" in nxt
             and nxt.index("began = hos_now_ns()") < nxt.index("mf_av1_decode(") < nxt.index("took = hos_now_ns() - began"),
             "decode_next does not time each submission")
    vf.check("d->movie.pictures++;" in vf.block(video, "static void queue_frame(Dec *d, const AVFrame *f) {"),
             "queue_frame does not count the movie's pictures")
    vf.check("d->movie.skipped += skipped;" in vf.block(video, "static void dec_acquire(Ctx *c) {"),
             "the catch-up does not count what it skipped for the movie's line")
    end = vf.block(video, "static void movie_end(Dec *d) {")
    vf.check("video_movie_line(&d->movie," in end and "video_pace_spacing(&d->pace)" in end and 'hos_log("video: %s", line);' in end
             and "memset(&d->movie, 0, sizeof d->movie);" in end,
             "movie_end does not log the line and start the counts again")
    flush = vf.block(video, "static void dec_flush(Ctx *c, const char *what) {")
    vf.check("movie_end(d);" in flush and
             flush.index("AcquireSRWLockExclusive(&d->lock);") < flush.index("movie_end(d);") < flush.index("pending_free(d);"),
             "a Stop or a Flush does not end the movie's line under the decoder's lock")
    vf.check("movie_end(d);" in vf.block(video, "static void dec_finalize(Ctx *c) {"), "the decoder's end does not end the movie's line")
    dev = (vf.ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    vf.check("`HOS_AV1=mf`" in dev, "docs/development.md: HOS_AV1=mf is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="video-av1-order-") as tmp:
        src, exe = Path(tmp) / "rules.c", Path(tmp) / "rules.exe"
        src.write_text(RULES, encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(vf.HOST), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        vf.check(r.returncode == 0, "the order rule or the movie's line:\n" + r.stdout)
        if not vf.WINDOWS:
            print(vf.WINDOWS_ONLY)
            print("PASS: AV1 movies ask for libdav1d first unless HOS_AV1=mf, and a movie's line is written once (the rules and the source)")
            return
        exe = vf.build(tmp, args.cc, MOVIES)
        for (hos_av1, dav1d, mf, open_fails), decoder, order, notices in CASES:
            out = vf.run(exe, HOS_AV1=hos_av1, SI_DAV1D=dav1d, SI_MF=mf, SI_OPEN_FAILS=open_fails)
            case = "HOS_AV1=%s, libdav1d %d, Media Foundation %d, open fails %d" % (hos_av1, dav1d, mf, open_fails)
            vf.check("FAIL:" not in out, case + ":\n" + out)
            vf.check(value(out, "decoder") == decoder and value(out, "again") == decoder,
                     "%s: the movie got %s, not %s" % (case, value(out, "decoder"), decoder))
            vf.check(value(out, "order") == order and value(out, "order-again") == order,
                     "%s: asked in the order %s, not %s" % (case, value(out, "order"), order))
            vf.check(value(out, "threads") == str(notices) and value(out, "threads-again") == str(notices) and value(out, "boxes") == "0",
                     "%s: %s notices after one decoder and %s after two, not %d once" % (case, value(out, "threads"), value(out, "threads-again"), notices))
            vf.check(out.count("video: no AV1 decoder: install") == notices, case + ": the log's line for no decoder")
            if decoder == "none":
                continue
            vf.check("video: AV1 decoder ready" + (": libdav1d" if decoder == "libdav1d" else " on Media Foundation") in out,
                     case + ": the log does not name the decoder")
            vf.check([value(out, "lines-" + k) for k in ("playing", "stop", "flush", "end")] == ["0", "1", "1", "2"],
                     case + ": a movie's line is not written once at its Stop and once at the decoder's end:\n" + out)
            lines = re.findall(r"^video: a movie of (\d+) pictures on (.+?): ([\d.]+) ms to decode each \(worst ([\d.]+)\).*; (\d+) skipped to catch up(?:, \d+ submissions refused while its input was full)?$", out, re.M)
            vf.check(len(lines) == 2, case + ": the two movie lines:\n" + out)
            # (12 submissions: 7 ms the first, 2 ms the others, and the stream's end, which costs nothing)
            vf.check(lines[0] == ("12", decoder, "2.42", "7.00", "0"), "%s: the first movie's line is %r" % (case, lines[0]))
            m = re.search(r"^second (\d+) pictures, (\d+) skipped$", out, re.M)
            vf.check(m and int(m.group(2)) > 0 and lines[1][0] == m.group(1) and lines[1][4] == m.group(2) and lines[1][1] == decoder,
                     "%s: the second movie's line %r against its counts %r" % (case, lines[1], m and m.groups()))
    print("PASS: AV1 movies get libdav1d first on Windows, Media Foundation with HOS_AV1=mf or without it, and say what they took")


if __name__ == "__main__":
    main()
