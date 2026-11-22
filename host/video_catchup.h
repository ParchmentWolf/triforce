/* (Triforce, 11-22, the performance audit's THREAD-82, after Source A's) How far the movie decoder's acquire decodes
   ahead to catch up with the movie's clock (nn_video.c dec_acquire).

   The game takes one picture a frame and the sound plays on, so the acquire skips the pictures that are behind the
   movie's clock, decoding the next ones to skip them too. Nothing bounded that but a guard of 600 steps. With a
   decoder that takes longer than the gap between two pictures (19.5 ms a picture against 16.7), every picture decoded
   to catch up puts the clock further ahead: the acquire decoded up to about 300 pictures, near 6 s with its lock and
   the movie thread held, threw nearly all of them away, and the next acquire started further behind.

   Now each decode that gives a picture is timed, about the last 8 of them kept as one number, and the acquire stops
   decoding to catch up when that number is more than the gap between pictures, or once it has decoded for one gap:
   the late picture is shown. A decoder faster than the movie catches up as before, a few pictures an acquire.
   HOS_VIDEO_UNBOUNDED_CATCHUP=1: no bound, as before.

   The rule alone, no decoder and no clock: tests/test_video_catchup.py compiles it. */
#pragma once
#include <stdint.h>

typedef struct {
    int64_t n;                     /* pictures decoded since first_pts */
    int64_t first_pts, end_pts;    /* the first of them and the newest, by the movie's own time (ns) */
    int64_t recent_ns;             /* what a decode that gives a picture takes: about the last 8 */
} VideoPace;

/* a picture came out of the decoder, with its time in the movie. One whose time is before the last one's is a movie
   that started again (a loop): the gap is counted from it */
static inline void video_pace_picture(VideoPace *p, int64_t pts) {
    if (!p->n || pts < p->end_pts) p->n = 0, p->first_pts = pts;
    p->n++;
    p->end_pts = pts;
}
/* the submission that gave it took ns to decode: seven parts of the old number and one of this */
static inline void video_pace_decoded(VideoPace *p, int64_t ns) {
    if (ns < 0) ns = 0;
    p->recent_ns = (p->recent_ns * 7 + ns) / 8;
}
/* the gap between two pictures as the movie plays, in ns; 0 while fewer than two came out */
static inline int64_t video_pace_spacing(const VideoPace *p) {
    return p->n > 1 && p->end_pts > p->first_pts ? (p->end_pts - p->first_pts) / (p->n - 1) : 0;
}
/* 1 when the acquire stops decoding to catch up and shows the late picture it has. spent_ns: how long this acquire's
   catch-up has run. Never with the switch, and never before the gap is known */
static inline int video_catchup_stop(int unbounded, int64_t spacing_ns, int64_t recent_ns, int64_t spent_ns) {
    if (unbounded || spacing_ns <= 0) return 0;
    return recent_ns > spacing_ns || spent_ns >= spacing_ns;
}
