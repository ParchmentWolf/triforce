/* (Triforce, 11-22, the performance audit's PRESENT-30, after Source A's) The frames paced at 240 while a movie plays at
   the 60 cap (nn_vi.c movie_pace_decide, pace_fps, realtime_step).

   The game's movie player takes one picture at each of its updates at most, and its updates follow the frame loop. At
   a cap of 60 the loop runs 60 times a second at best, a movie has 59.94 pictures a second, and every frame that comes
   late is a picture the player never takes: the decoder skips it (nn_video.c's catch-up). A PC that misses 60 in a
   movie skips a picture for every frame it misses. While a movie plays, at a cap of exactly 60, the frames are now
   paced by 240, with the game's own limiter and its time step following as they do at a cap of 240: after a late
   frame the next comes at once, and the player takes the picture that is due. Game time stays real time. When no
   movie player has updated for a quarter second the cap is 60 again.

   Not at any other cap (above 60 the loop is fast enough already; under 60 the player asked for it), and not with the
   Steady frame rate row on, which paces by a period of its own. HOS_MOVIE_PACE=0: the cap kept through movies, as
   before.

   The rules alone, no game and no clock: tests/test_movie_pace.py compiles them. */
#pragma once

#define MOVIE_PACE_FPS 240   /* what the frames are paced by while a movie plays at the 60 cap */

/* 1 when this present is paced at MOVIE_PACE_FPS. on: HOS_MOVIE_PACE is not 0; cap: the frame rate cap; steady: the
   Steady frame rate row is on; movie: a movie player updated in the last quarter second */
static inline int movie_pace_raise(int on, int cap, int steady, int movie) { return on && cap == 60 && !steady && movie; }

/* the rate the pacing, the game's limiter and its time step go by */
static inline int movie_pace_fps(int raise, int cap) { return raise ? MOVIE_PACE_FPS : cap; }

/* The game's own frame limiter (its rate, 0 or less: none) under the rate the frames are paced by. Above 60 it is
   raised to that rate where it is lower, as it always was for a cap above 60; what it was before is kept, and put back
   once the rate is 60 or less again, unless the game has written another value over the raised one meanwhile */
typedef struct { int before, raised; } MovieLimit;
static inline int movie_pace_limit(MovieLimit *m, int limit, int pace) {
    if (pace > 60) {
        if (limit > 0 && limit < pace) {
            if (!m->before) m->before = limit;
            m->raised = pace;
            return pace;
        }
        return limit;
    }
    if (m->before) {
        const int back = limit == m->raised ? m->before : limit;
        m->before = m->raised = 0;
        return back;
    }
    return limit;
}

/* The game's frame rate slot when the rate the frames are paced by comes down to 60 or less from `before`: a rate above
   60 that the time step left in it (only without the frame-time hook, where the slot follows the pace) goes back to 60,
   which the step then moves as before. Without this the step would find a rate it does not own and leave it alone */
static inline int movie_pace_slot(int slot, int before, int pace) {
    return before > 60 && pace <= 60 && slot > 60 && slot <= before ? 60 : slot;
}
