/* (Triforce, 11-22, the performance audit's IO-34, after Source A's) How many submissions the movie decoder holds before
   it refuses one (nn_video.c dec_submit).

   The game's movie library submits a whole movie at once, on the thread that also takes the pictures, and every
   submission was taken. While it submits it takes a picture only now and then, so at a movie's start the pictures
   that came due meanwhile were skipped by the catch-up: a stutter at each movie's start. The console's decoder holds
   only so much input and refuses a submission with a result of its own while it is full; the library submits it again
   later. So does this one now: while 16 submissions wait, not decoded yet or decoded and not taken, a submission is
   refused at once with that result. The stream's last submission is never refused: nothing would mark the end. The
   decoder's "ready for a submission" event is clear while it is full and set again when there is room.
   HOS_VIDEO_INPUT_LIMIT=<n>: that many instead of 16; 0: no limit, every submission taken, as before.

   The rule alone, no decoder: tests/test_video_input_limit.py compiles it. */
#pragma once
#include <stdlib.h>

#define VIDEO_INPUT_LIMIT 16                 /* submissions waiting, pending or decoded, before one is refused */
#define VIDEO_RESULT_INPUT_FULL 0x1c266fu    /* the console's result for a submission its decoder has no room for */

/* The limit from HOS_VIDEO_INPUT_LIMIT's value (NULL or empty: unset): 0 is no limit, and so is anything not a
   positive number */
static inline int video_input_limit(const char *value) {
    if (!value || !*value) return VIDEO_INPUT_LIMIT;
    const int n = atoi(value);
    return n > 0 ? n : 0;
}
/* 1 while the decoder holds as much as the limit. pending: submissions not decoded yet; queued: pictures decoded and
   not taken */
static inline int video_input_full(int limit, int pending, int queued) { return limit > 0 && pending + queued >= limit; }
/* 1 when this submission is refused. last: it is the stream's last */
static inline int video_input_refuse(int limit, int pending, int queued, int last) {
    return !last && video_input_full(limit, pending, queued);
}
