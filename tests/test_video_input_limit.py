"""The movie decoder refuses a submission while 16 wait, and its ready event is clear until there is room
(host/video_input.h, host/nn_video.c dec_submit, input_room and ready_event, host/nn_os_sync.c; no game, no FFmpeg).

(Triforce, 11-22, the performance audit's IO-34, after Source A's.) The game submits a whole movie at once, on the
thread that also takes the pictures, and every submission was taken: the pictures that came due while it submitted
were skipped, a stutter at each movie's start. Now a submission is refused at once with the console's result for a
full decoder (0x1c266f) while 16 wait, not decoded yet or decoded and not taken; the game submits it again later. The
stream's last submission is never refused. Each decoder has its own "ready for a submission" event, clear from a
refusal until there is room. HOS_VIDEO_INPUT_LIMIT=<n> sets the limit; 0 takes every submission, as before.

A decoder left full with its event clear, or a refused last submission, would hang the movie on a black screen, so on
every system this compiles video_input.h alone and reads the source: the refusal comes before the submission is
counted, under the decoder's lock, with the event cleared there; every call that ends with the count possibly lower
(submit, Stop and Flush, the three exits of the acquire) sets the event again before it lets the lock go; a finalize
leaves it set; the event's clear and its set under a lock take no virtual-core checkpoint; the switch is read once and
is in the switches table.

On Windows it also compiles nn_video.c whole over tests/video_standins.h and, from one thread as the game does:
- submits to a fresh decoder: 16 are taken and the 17th is refused with 0x1c266f, its id not written and the count of
  submissions not moved; the event, set until then, is clear; an acquire sets it and one more submission fits; a Stop,
  a Flush and a finalize each set it again after a refusal; a last submission is taken while full;
- replays a movie of 600 pictures, submitting until refused before each picture it takes: never more than 16 wait before the last,
  every picture comes out in order with none skipped, the last one marked last, the event is set whenever there is
  room, and the movie's line counts the refusals;
- with HOS_VIDEO_INPUT_LIMIT=0 all 600 are taken at once and the event is never cleared; with =4 the 5th is refused;
- a decoder with no AV1 decoder behind it refuses nothing.

    python -I -B tests/test_video_input_limit.py [--cc clang]
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
#include "video_input.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    CHECK(VIDEO_INPUT_LIMIT == 16 && VIDEO_RESULT_INPUT_FULL == 0x1c266f);
    CHECK(video_input_limit(NULL) == 16 && video_input_limit("") == 16);
    CHECK(video_input_limit("0") == 0 && video_input_limit("4") == 4 && video_input_limit("64") == 64);
    CHECK(video_input_limit("-3") == 0 && video_input_limit("none") == 0);   /* (not a positive number: no limit) */
    /* video_input_full(limit, pending, queued) */
    CHECK(!video_input_full(16, 15, 0) && video_input_full(16, 16, 0) && video_input_full(16, 8, 8) && video_input_full(16, 9, 8));
    CHECK(!video_input_full(16, 7, 8) && !video_input_full(16, 0, 0));
    CHECK(!video_input_full(0, 1000, 8));                                     /* no limit: never full */
    /* video_input_refuse(limit, pending, queued, last) */
    CHECK(video_input_refuse(16, 16, 0, 0) && video_input_refuse(16, 10, 6, 0));
    CHECK(!video_input_refuse(16, 16, 0, 1) && !video_input_refuse(16, 400, 8, 1));   /* the stream's last: never */
    CHECK(!video_input_refuse(16, 15, 0, 0) && !video_input_refuse(0, 1000, 8, 0));
    return fails ? 1 : 0;
}
"""

MOVIE = r"""
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static int env_int(const char *name, int otherwise) { return getenv(name) ? atoi(getenv(name)) : otherwise; }
static int waiting(void) { return si_dec()->npending + si_dec()->qn; }
/* submissions until one is refused: how many were taken (never more than `most`) */
static int fill(int64_t *pts, int most) {
    int taken = 0;
    while (taken < most && si_submit(*pts, 0) == 0) taken++, *pts += 16683333;
    return taken;
}
int main(void) {
    const int64_t gap = 16683333;
    const int limit = env_int("SI_LIMIT", 16);   /* (what the run's HOS_VIDEO_INPUT_LIMIT means: 0 none) */
    si.have_dav1d = env_int("SI_DAV1D", 1), si.mf_ok = env_int("SI_MF", 1);
    si.decode_ns = 2000000;
    si_open(64, 36, 2, 0);
    Dec *d = si_dec();
    uint64_t ev = si_ready_event();
    CHECK(ev != 0 && ev == d->ready && si_event_set(ev));
    if (!d->ctx && !d->mf) {   /* no decoder behind it: every submission answered 0, as before, and nothing cleared */
        for (int i = 0; i < 40; i++) CHECK(si_submit(i * gap, 0) == 0);
        CHECK(si_event_set(ev) && si_event_clears(ev) == 0);
        printf("no decoder: 40 taken\n");
        return fails ? 1 : 0;
    }
    int64_t pts = 0;
    if (limit) {
        /* the limit's worth is taken, the next refused: no id, no submission counted, the event clear */
        CHECK(fill(&pts, limit) == limit && waiting() == limit && si_event_set(ev));
        const LONG64 counted = submissions;
        G64(SI_OUT) = 0x1234;
        CHECK(si_submit(pts, 0) == SI_FULL);
        CHECK(G64(SI_OUT) == 0x1234 && submissions == counted && waiting() == limit && d->submits == limit);
        CHECK(!si_event_set(ev) && d->ready_clear);
        CHECK(si_submit(pts, 0) == SI_FULL && si_event_clears(ev) == 1);   /* (again: refused, cleared once) */
        CHECK(si_ready_event() == ev);
        /* an acquire takes a picture: room, the event set, one more fits and the next is refused again */
        int b = si_acquire();
        CHECK(b >= 0 && si_pts(b, NULL) == 0);
        si_release(b);
        CHECK(waiting() == limit - 1 && si_event_set(ev) && !d->ready_clear);
        CHECK(fill(&pts, 100) == 1 && !si_event_set(ev));
        /* a Stop empties it: set; and a Flush after another refusal */
        si_stop();
        CHECK(waiting() == 0 && si_event_set(ev));
        CHECK(fill(&pts, 100) == limit && !si_event_set(ev));
        si_flush();
        CHECK(waiting() == 0 && si_event_set(ev));
        /* the stream's last submission is taken while full, and the refusals after it stay refusals */
        CHECK(fill(&pts, 100) == limit && !si_event_set(ev));
        CHECK(si_submit(pts, 1) == 0 && d->npending == limit + 2);   /* (it and the end's mark) */
        CHECK(si_submit(pts + gap, 0) == SI_FULL);
        /* a finalize leaves the event set, for a thread that still has it */
        si_finalize();
        CHECK(si_event_set(ev));
        si_open(64, 36, 2, 0);
        d = si_dec();
        CHECK(si_ready_event() != ev);   /* (a new decoder: an event of its own) */
        ev = si_ready_event();
        CHECK(si_event_set(ev));
        printf("first part: the refusals and the event\n");
    }
    /* a movie of 600 pictures: the game submits until it is refused, then takes a picture, every frame */
    int next = 0, most = 0, refusals_seen = 0, taken_at_once = 0, acquired = 0, last = 0;
    int64_t expect = 0;
    for (int frame = 0; frame < 2000 && !last; frame++) {
        const int taken = si_feed(&next, 600, gap);
        CHECK(taken >= 0);
        if (frame == 0) taken_at_once = taken;
        if (waiting() > most) most = waiting();
        if (next < 600) {   /* (refused: full, the event clear) */
            refusals_seen++;
            CHECK(waiting() >= limit && !si_event_set(ev));
        } else {
            CHECK(frame == 0 || !limit || si_event_set(ev) || waiting() >= limit);
        }
        const int b = si_acquire();
        CHECK(b >= 0);
        CHECK(si_pts(b, &last) == expect);   /* (in order, none skipped: the game keeps up here) */
        expect += gap, acquired++;
        si_release(b);
        CHECK(waiting() < limit || !limit ? si_event_set(ev) : 1);   /* (room: never left clear) */
        si_now += gap - si.decode_ns;
    }
    printf("movie: %d taken at once, %d acquired, last %d, most waiting %d, frames refused %d, event cleared %d times\n",
           taken_at_once, acquired, last, most, refusals_seen, si_event_clears(ev));
    si_stop();
    CHECK(si_event_set(ev));
    fputs(si_log, stdout);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    video = vf.video_source()
    sync = (vf.HOST / "nn_os_sync.c").read_text(encoding="utf-8")

    vf.check("void hos_system_event_clear(uint64_t key) { event_clear(obj_nockpt(key, K_EVENT)); }" in sync
             and "void hos_system_event_signal_held(uint64_t key) { event_signal(obj_nockpt(key, K_EVENT)); }" in sync,
             "nn_os_sync.c: the event's clear and its set under a lock are missing, or take the virtual-core checkpoint")
    vf.check('#include "video_input.h"' in video, "nn_video.c does not take video_input.h")
    limit = vf.block(video, "static int input_limit(void) {")
    vf.check('if (limit < 0) limit = video_input_limit(getenv("HOS_VIDEO_INPUT_LIMIT"));' in limit, "HOS_VIDEO_INPUT_LIMIT is not read once")
    room = vf.block(video, "static void input_room(Dec *d) {")
    vf.check("if (d->ready_clear && !input_full(d)) {" in room and "d->ready_clear = 0;" in room
             and "hos_system_event_signal_held(d->ready);" in room and "hos_system_event_signal(" not in room,
             "input_room does not set a cleared event once there is room, without a checkpoint")
    vf.check("d->npending++;" in vf.block(video, "static void pending_push(Dec *d, AVPacket *pkt) {")
             and "d->npending--;" in vf.block(video, "static void decode_next(Dec *d) {")
             and "d->npending = 0;" in vf.block(video, "static void pending_free(Dec *d) {"),
             "the count of pending submissions is not kept where the list changes")

    submit = vf.block(video, "static void dec_submit(Ctx *c) {")
    refuse = "const int refuse = video_input_refuse(input_limit(), d->npending, d->qn, (int)(ARG(5) & 1));"
    clear = "if (!d->ready_clear) d->ready_clear = 1, hos_system_event_clear(d->ready);"
    out = "if (refuse) { RET(VIDEO_RESULT_INPUT_FULL); return; }"
    vf.check("if (d && (d->ctx || d->mf) && input_limit()) {" in submit and refuse in submit and clear in submit and out in submit,
             "dec_submit does not refuse by the rule, only for a decoder that decodes")
    first_lock, first_unlock = submit.index("AcquireSRWLockExclusive(&d->lock);"), submit.index("ReleaseSRWLockExclusive(&d->lock);")
    vf.check(first_lock < submit.index(refuse) < submit.index(clear) < first_unlock < submit.index(out) < submit.index("submitted();"),
             "the refusal is not decided and the event cleared under the lock, before the submission is counted")
    vf.check(re.search(r"input_room\(d\);[^\n]*\n\s+ReleaseSRWLockExclusive\(&d->lock\);\n\s+RET\(0\);\n}$", submit) is not None,
             "dec_submit does not look for room before its last unlock")
    flush = vf.block(video, "static void dec_flush(Ctx *c, const char *what) {")
    vf.check(re.search(r"input_room\(d\);[^\n]*\n\s+ReleaseSRWLockExclusive\(&d->lock\);", flush) is not None
             and flush.index("pending_free(d);") < flush.index("input_room(d);"),
             "a Stop or a Flush does not set the event again before it lets the lock go")
    acquire = vf.block(video, "static void dec_acquire(Ctx *c) {")
    exits = re.findall(r"input_room\(d\);[^\n]*\n\s+ReleaseSRWLockExclusive\(&d->lock\);\n\s+if \(away\) hos_vcore_back\(\);", acquire)
    vf.check(len(exits) == 3 and acquire.count("if (away) hos_vcore_back();") == 3,
             "dec_acquire does not look for room before each of its three last unlocks (found %d)" % len(exits))
    final = vf.block(video, "static void dec_finalize(Ctx *c) {")
    vf.check("if (d->ready_clear) hos_system_event_signal(d->ready);" in final, "a finalized decoder can leave its event clear")
    init = vf.block(video, "static void dec_init_sized(Ctx *c, enum AVCodecID id, const char *what, int w, int h) {")
    vf.check("d->ready = ready_new();" in init and init.index("d->ready = ready_new();") < init.index("set_host(ARG(0), DEC_MAGIC, d);"),
             "a decoder does not have its ready event before the game can reach it")
    ready = vf.block(video, "static uint64_t ready_new(void) {")
    vf.check(ready.index("hos_system_event_init(event, 0);") < ready.index("hos_system_event_signal(event);"), "a new ready event is not set")
    vf.check(video.count("{ RET(ready_event(c)); }") == 3 and "if (d && d->ready) return d->ready;" in vf.block(video, "static uint64_t ready_event(Ctx *c) {"),
             "GetXDecoderSubmissionReadyEvent does not give the decoder's own event")
    dev = (vf.ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    vf.check("`HOS_VIDEO_INPUT_LIMIT=<n>`" in dev, "docs/development.md: HOS_VIDEO_INPUT_LIMIT is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="video-input-limit-") as tmp:
        src, exe = Path(tmp) / "rules.c", Path(tmp) / "rules.exe"
        src.write_text(RULES, encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(vf.HOST), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        vf.check(r.returncode == 0, "the input limit's rule:\n" + r.stdout)
        if not vf.WINDOWS:
            print(vf.WINDOWS_ONLY)
            print("PASS: the movie decoder refuses a submission while 16 wait, never the last (the rule and the source)")
            return
        exe = vf.build(tmp, args.cc, MOVIE)
        pattern = (r"^movie: (\d+) taken at once, (\d+) acquired, last (\d), most waiting (\d+), frames refused (\d+), "
                   r"event cleared (\d+) times$")
        # (HOS_VIDEO_INPUT_LIMIT, the limit it means, Media Foundation in place of libdav1d)
        for env, limit, mf in ((None, 16, 0), ("16", 16, 1), ("4", 4, 0), ("0", 0, 0), ("0", 0, 1)):
            out = vf.run(exe, HOS_VIDEO_INPUT_LIMIT=env, SI_LIMIT=limit, HOS_AV1="mf" if mf else None)
            case = "HOS_VIDEO_INPUT_LIMIT=%s%s" % (env, " on Media Foundation" if mf else "")
            vf.check("FAIL:" not in out, case + ":\n" + out[:3000])
            m = re.search(pattern, out, re.M)
            vf.check(m is not None, case + ":\n" + out[:3000])
            at_once, acquired, last, most, refused_frames, clears = (int(x) for x in m.groups())
            vf.check(acquired == 600 and last == 1, "%s: %d of 600 pictures came out, the last marked %d" % (case, acquired, last))
            line = re.search(r"^video: a movie of 600 pictures on .*; 0 skipped to catch up(?:, (\d+) submissions refused while its input was full)?$", out, re.M)
            vf.check(line is not None, case + ": the movie's line:\n" + out[-800:])
            if limit:
                vf.check("first part: the refusals and the event" in out, case + ": the first part did not run")
                # (the stream's last submission is taken though the decoder is full, and the end's mark with it: two over)
                vf.check(at_once == limit and limit <= most <= limit + 2, "%s: %d taken at once and %d waiting at most, not %d" % (case, at_once, most, limit))
                vf.check(refused_frames > 500 and clears == refused_frames and line.group(1) == str(refused_frames),
                         "%s: %d frames ended in a refusal, the event was cleared %d times and the line counts %s" % (case, refused_frames, clears, line.group(1)))
            else:
                vf.check(at_once == 600 and refused_frames == 0 and clears == 0 and line.group(1) is None,
                         "%s: %d taken at once, %d refusals, %d clears: not every submission taken as before" % (case, at_once, refused_frames, clears))
        out = vf.run(exe, SI_DAV1D=0, SI_MF=0)
        vf.check("FAIL:" not in out and "no decoder: 40 taken" in out, "a decoder with nothing behind it refuses submissions:\n" + out)
    print("PASS: the movie decoder refuses a submission while 16 wait, never the last, with its ready event clear until there is room")


if __name__ == "__main__":
    main()
