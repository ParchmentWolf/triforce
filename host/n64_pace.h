/* (Triforce, 11-22) N64 Classic's frame rate (n64-classic-mode-plan.md, step 7): the frames paced at the rate the renderer
   asks for (HOS_OPT_N64_FPS: Faithful's 20, or the Remembered page's row; gpu/vk/n64_rules.h fps), in play, with no restart
   (nn_vi.c n64_pace_decide, pace_fps).

   The host already changes the rate it paces the game by while it runs: 240 while a movie plays at the 60 cap
   (movie_pace.h). pace_fps is what the pacing, the game's frame limiter, its rate slot and the real-time step go by, and
   the step's average starts again whenever it changes. N64 Classic's rate is one more input to it, asked once a present
   beside the movie's. It only ever lowers the rate (a rate at or above the cap is the cap's), and gives way while a movie
   plays: the movie player takes one picture a frame at most, so at 20 it would skip pictures. The real-time step stops at
   4/60 of a second (15 a second) and the game's rate slot takes 15 and up, so a rate under 15 is not taken. Game time
   stays real time. fps_max stays the cap itself, read once, as it does for movies; the vsync event keeps the cap's rate,
   as it does while a movie raises the pace.

   HOS_N64_PACE=0: the renderer's rate is not taken, the cap's as before. The rules alone, no game and no clock:
   tests/test_n64_pace.py compiles them. */
#pragma once

#include <stdlib.h>

/* The lowest rate taken: the real-time step's floor, 4/60 of a second */
#define N64_PACE_LOWEST 15

/* Whether the renderer's rate is taken (HOS_N64_PACE: env, its value or NULL): unset, empty or not a 0, as HOS_MOVIE_PACE
   is read */
static inline int n64_pace_on(const char *env) { return !(env && *env && atoi(env) == 0); }

/* The rate N64 Classic paces the frames at this present, 0 none: the renderer's (asked: frames a second, 0 none) where it is
   on, no movie plays (movie: a movie player updated in the last quarter second), it is the real-time step's to take, and it
   is under the cap (cap: the Frame rate cap's rate); else none */
static inline int n64_pace_rate(int on, int asked, int movie, int cap) {
    return on && !movie && asked >= N64_PACE_LOWEST && asked < cap ? asked : 0;
}

/* The rate the frames are paced by: N64 Classic's where it has one, else the one the cap and a movie give (movie_pace_fps) */
static inline int n64_pace_fps(int rate, int paced) { return rate > 0 ? rate : paced; }

/* The present's interval in vsyncs with N64 Classic's rate: 1, for it paces by itself, as a cap under 60 does (the game's
   own request for 2 vsyncs a frame would make 20 into 10); else as it was */
static inline int n64_pace_interval(int rate, int interval) { return rate > 0 ? 1 : interval; }
