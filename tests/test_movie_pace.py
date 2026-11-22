"""While a movie plays at a frame rate cap of exactly 60 the frames are paced by 240, with the game's limiter and its time
step following, and the cap is back a quarter second after the movie player's last update (host/movie_pace.h,
host/nn_vi.c movie_pace_decide, pace_fps, realtime_step and hos_vi_native_presented; no game).

(Triforce, 11-22, the performance audit's PRESENT-30, after Source A's.) The game's movie player takes one picture an
update at most and its updates follow the frame loop, so at the 60 cap every frame that came late was a picture the
decoder skipped. HOS_MOVIE_PACE=0 keeps the cap through movies, as before.

This compiles movie_pace.h alone (when the pace is raised; the limiter raised, kept, and put back unless the game wrote
over it; the game's rate slot brought back down), reads the source (the decision once a present, before the period;
realtime_step by the pace and no longer by the cap; the Steady row and the vsync event still by the cap; the switch
read once and in the switches table), and runs nn_vi.c's own fps_max, movie_seen, movie_plays, pace_fps,
movie_pace_decide and realtime_step, cut out of the file, on a clock of its own:
- the decision: 240 only at a cap of 60 with a movie player's update in the last 250 ms; not with HOS_MOVIE_PACE=0, not
  with the Steady frame rate row on (by its environment switch or its options line), not at a cap of 45, 120 or 240;
  still 240 at 249 ms after the update and the cap again at 251; one line in the log at the start and one at the end;
- the step, through a movie between two stretches at 60: the limiter goes 60, 240, 60; with the frame-time hook the game
  is given each frame's own time during the movie (1/240 s) and none before or after, its rate slot staying 60; without
  the hook the slot follows the pace to 240 and comes back to 60 with it, where the step goes on moving it.

    python -I -B tests/test_movie_pace.py [--cc clang]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"
RUN_ALL_ARGS = ["--cc", "clang"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(source, marker):
    """From marker to the first line that starts with a closing brace"""
    start = source.index(marker)
    return source[start:start + re.search(r"^}", source[start:], re.M).end()]


RULES = r"""
#include <stdio.h>
#include "movie_pace.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    /* movie_pace_raise(on, cap, steady, movie) */
    CHECK(MOVIE_PACE_FPS == 240);
    CHECK(movie_pace_raise(1, 60, 0, 1));
    CHECK(!movie_pace_raise(1, 60, 0, 0));    /* no movie */
    CHECK(!movie_pace_raise(0, 60, 0, 1));    /* HOS_MOVIE_PACE=0 */
    CHECK(!movie_pace_raise(1, 60, 1, 1));    /* the Steady frame rate row */
    for (int cap = 20; cap <= 240; cap++) CHECK(movie_pace_raise(1, cap, 0, 1) == (cap == 60));   /* a cap of exactly 60 */
    CHECK(movie_pace_fps(1, 60) == 240 && movie_pace_fps(0, 60) == 60 && movie_pace_fps(0, 144) == 144 && movie_pace_fps(0, 45) == 45);

    /* the game's limiter: 60, raised through a movie, back after it */
    MovieLimit m = {0, 0};
    CHECK(movie_pace_limit(&m, 60, 60) == 60 && !m.before);
    CHECK(movie_pace_limit(&m, 60, 240) == 240 && m.before == 60);
    CHECK(movie_pace_limit(&m, 240, 240) == 240 && m.before == 60);   /* (already there: nothing to do, the old value kept) */
    CHECK(movie_pace_limit(&m, 240, 60) == 60 && !m.before && !m.raised);
    CHECK(movie_pace_limit(&m, 60, 60) == 60);
    /* the game lowered it during the movie (its own controller): raised again, and what it was before the first raise kept */
    CHECK(movie_pace_limit(&m, 60, 240) == 240 && movie_pace_limit(&m, 90, 240) == 240 && m.before == 60);
    CHECK(movie_pace_limit(&m, 240, 60) == 60);
    /* the game wrote another value over the raised one: left as the game has it */
    CHECK(movie_pace_limit(&m, 60, 240) == 240);
    CHECK(movie_pace_limit(&m, 300, 240) == 300 && movie_pace_limit(&m, 300, 60) == 300 && !m.before);
    /* no limiter (0 or less): never touched */
    CHECK(movie_pace_limit(&m, 0, 240) == 0 && movie_pace_limit(&m, -1, 240) == -1 && movie_pace_limit(&m, 0, 60) == 0 && !m.before);
    /* a cap above 60 for good: raised and never lowered, as before */
    MovieLimit c = {0, 0};
    for (int i = 0; i < 5; i++) CHECK(movie_pace_limit(&c, i ? 144 : 60, 144) == 144);
    /* a cap under 60: left alone */
    MovieLimit low = {0, 0};
    CHECK(movie_pace_limit(&low, 60, 45) == 60 && !low.before);

    /* movie_pace_slot(slot, the pace before, the pace now) */
    CHECK(movie_pace_slot(240, 240, 60) == 60 && movie_pace_slot(100, 240, 60) == 60);   /* the raise ended: back to 60 */
    CHECK(movie_pace_slot(60, 240, 60) == 60 && movie_pace_slot(40, 240, 60) == 40);     /* (60 or less: the step's own) */
    CHECK(movie_pace_slot(240, 240, 240) == 240 && movie_pace_slot(240, 60, 240) == 240);/* during it, and at its start */
    CHECK(movie_pace_slot(240, 60, 60) == 240 && movie_pace_slot(300, 240, 60) == 300);  /* (not the step's: left alone) */
    return fails ? 1 : 0;
}
"""

FIXTURE = r'''#define _CRT_SECURE_NO_WARNINGS
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "step_steady.h"
#include "pace_steady.h"
#include "movie_pace.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
typedef long long LONG64;
static int64_t clock_ns = 1000000000LL;
int64_t hos_now_ns(void) { return clock_ns; }
static char log_text[1 << 15];
static void hos_log(const char *fmt, ...) {
    va_list ap;
    const size_t n = strlen(log_text);
    va_start(ap, fmt);
    if (n + 600 < sizeof log_text) vsnprintf(log_text + n, 500, fmt, ap), strcat(log_text, "\n");
    va_end(ap);
}
static int logged(const char *text) {
    int n = 0;
    for (const char *p = log_text; (p = strstr(p, text)) != NULL; p += strlen(text)) n++;
    return n;
}
static int64_t pace_period_ns;   /* (the period the presents are paced by: hos_vi_native_presented) */
static uint8_t guest[0x4000];
#define GP(a) ((void *)(guest + (a)))
#define MOD 0x1000u
int rx_option(int id, int otherwise) { (void)id; return otherwise; }
static int steady_row;           /* (the options file's steady_frame_rate) */
int hos_ini_option(const char *key, int otherwise) { return strcmp(key, "steady_frame_rate") ? otherwise : steady_row; }
enum { HOS_OPT_DISPLAY_CAP = 60 };
static volatile long long presents;
volatile uint64_t hos_gfx_module = MOD;
volatile int hos_fixed_resolution, hos_dynres_runs;
volatile uint32_t hos_fixed_scale_bits;
volatile float hos_text_scale;
volatile uint64_t hos_step_probe, hos_res_module;
volatile uint32_t hos_frame_seconds_bits;
@HOST@
/* one frame: the movie player's update when a movie plays, the frame's time, then what the present does in this order */
static void present(int movie, int64_t frame_ns) {
    if (movie) movie_seen();
    clock_ns += frame_ns;
    movie_pace_decide();
    pace_period_ns = 1000000000LL / pace_fps();
    realtime_step(clock_ns);
}
static float seconds_given(void) {   /* (what the frame-time hook reads: 0 when the game steps by its own rate) */
    const uint32_t bits = hos_frame_seconds_bits;
    float f;
    memcpy(&f, &bits, 4);
    return bits ? f : 0.0f;
}
static int near(float a, double b) { return a > b * 0.999 && a < b * 1.001; }
int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "";
    const int cap = argc > 2 ? atoi(argv[2]) : 60, raised = argc > 3 ? atoi(argv[3]) : 240;
    const int64_t ms = 1000000;
    int *limit = (int *)GP(MOD + 0xfc), *rate = (int *)GP(MOD + 0x2c8);
    steady_row = getenv("SI_STEADY_ROW") ? atoi(getenv("SI_STEADY_ROW")) : 0;
    *limit = 60, *rate = 60;
    if (!strcmp(mode, "decide")) {
        CHECK(pace_fps() == cap);
        movie_pace_decide();
        CHECK(pace_fps() == cap && fps_max() == cap);                      /* no movie player has updated */
        for (int movie = 1; movie <= 2; movie++) {
            movie_seen();
            clock_ns += 4 * ms;
            movie_pace_decide();
            CHECK(pace_fps() == raised && fps_max() == cap);               /* a movie plays (the cap itself never moves) */
            CHECK(pace_fps() == raised);                                   /* (asked again within the present: the same) */
            clock_ns += 245 * ms;                                          /* 249 ms after the update: still */
            movie_pace_decide();
            CHECK(pace_fps() == raised);
            clock_ns += 2 * ms;                                            /* 251 ms: the cap again */
            movie_pace_decide();
            CHECK(pace_fps() == cap);
            CHECK(logged("vi: a movie plays at the 60 cap: frames paced at 240") == (raised != cap ? movie : 0));
            CHECK(logged("vi: the movie is over: frames paced at the 60 cap again") == (raised != cap ? movie : 0));
            clock_ns += 5000 * ms;
            movie_pace_decide();
            CHECK(pace_fps() == cap);
        }
    } else {
        const int hook = !strcmp(mode, "step"), off = !strcmp(mode, "step-off");
        hos_step_probe = hook || off ? 0x2000 : 0;   /* (the lifted code sets it when the frame-time hook is in the build) */
        for (int i = 0; i < 120; i++) {              /* before the movie: 60 */
            present(0, 1000000000LL / 60);
            CHECK(pace_fps() == 60 && *limit == 60 && *rate == 60 && seconds_given() == 0.0f);
        }
        for (int i = 0; i < 480; i++) {              /* the movie: its player updates every frame */
            present(1, 1000000000LL / pace_fps());
            if (off) {
                CHECK(pace_fps() == 60 && *limit == 60 && *rate == 60 && seconds_given() == 0.0f);
                continue;
            }
            CHECK(pace_fps() == 240 && pace_period_ns == 1000000000LL / 240 && *limit == 240);
            if (hook && i > 20) CHECK(near(seconds_given(), 1.0 / 240) && *rate == 60);   /* (each frame's own time; the rate the engine's) */
            if (!hook && i > 20) CHECK(seconds_given() == 0.0f && *rate == 240);          /* (no hook: the rate up to the pace) */
        }
        int still = 0;
        for (int i = 0; i < 200; i++) {              /* its player has stopped: a quarter second more, then 60 */
            present(0, 1000000000LL / pace_fps());
            still += pace_fps() == 240;
        }
        CHECK(off ? still == 0 : still >= 55 && still <= 60);   /* (250 ms of frames 4.17 ms apart) */
        CHECK(pace_fps() == 60 && pace_period_ns == 1000000000LL / 60);
        CHECK(*limit == 60);                         /* the limiter where it was */
        CHECK(*rate == 60 && seconds_given() == 0.0f);   /* the game steps by its own rate again, and the step still moves it */
        for (int i = 0; i < 30; i++) present(0, 1000000000LL / 40);
        CHECK(*rate >= 36 && *rate <= 41 && *limit == 60);   /* (frames of 25 ms: the rate follows them, a hitch repaid slowly) */
        CHECK(logged("vi: a movie plays at the 60 cap") == !off && logged("vi: the movie is over") == !off);
        CHECK(!logged("no real-time step"));
    }
    if (fails) fputs(log_text, stdout);
    printf("%s: %s %d %d\n", fails ? "FAILED" : "PASS", mode, cap, raised);
    return fails ? 1 : 0;
}
'''

# (mode, the cap expected, the pace expected while a movie plays, the environment)
CASES = [
    ("decide", 60, 240, {}),
    ("decide", 60, 240, {"HOS_MOVIE_PACE": "1"}),
    ("decide", 60, 60, {"HOS_MOVIE_PACE": "0"}),                           # the switch: the cap kept
    ("decide", 60, 60, {"HOS_FPS_STEADY": "1"}),                           # the Steady frame rate row, by its switch
    ("decide", 60, 60, {"HOS_FPS_STEADY": "2"}),
    ("decide", 60, 60, {"SI_STEADY_ROW": "1"}),                            # ... and by its line in the options file
    ("decide", 60, 240, {"SI_STEADY_ROW": "2", "HOS_FPS_STEADY": "0"}),    # (the switch over the line, as steady_period reads it)
    ("decide", 60, 240, {"SI_STEADY_ROW": "7"}),                           # (a value that is no row: off)
    ("decide", 45, 45, {"HOS_FPS_MAX": "45"}),                             # any other cap: never
    ("decide", 120, 120, {"HOS_FPS_MAX": "120"}),
    ("decide", 240, 240, {"HOS_FPS_MAX": "240"}),
    ("step", 60, 240, {}),
    ("step-nohook", 60, 240, {}),
    ("step", 60, 240, {"HOS_STEP_STEADY": "0"}),                           # (the mean of five in place of the steady step)
    ("step-off", 60, 60, {"HOS_MOVIE_PACE": "0"}),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    vi = (HOST / "nn_vi.c").read_text(encoding="utf-8")

    check('#include "movie_pace.h"' in vi, "nn_vi.c does not take movie_pace.h")
    check("return movie_pace_fps(movie_raise, fps_max());" in block(vi, "static int pace_fps(void) {"), "pace_fps is not the rule's")
    decide = block(vi, "static void movie_pace_decide(void) {")
    check('if (on < 0) on = !(getenv("HOS_MOVIE_PACE") && *getenv("HOS_MOVIE_PACE") && atoi(getenv("HOS_MOVIE_PACE")) == 0);' in decide,
          "HOS_MOVIE_PACE is not read once, on unless 0")
    check("const int raise = movie_pace_raise(on, fps_max(), steady != PACE_STEADY_OFF, movie_plays());" in decide
          and "movie_raise = raise;" in decide, "the decision is not the rule's, from the cap, the Steady row and the movie's stamp")
    steady = block(vi, "static int64_t steady_period(int64_t base, int64_t now) {")
    for read in ('getenv("HOS_FPS_STEADY");', 'e && *e ? atoi(e) : hos_ini_option("steady_frame_rate", PACE_STEADY_OFF);'):
        check(read in decide and read in steady, "the decision does not read the Steady frame rate row as steady_period does: " + read)
    check("if (cap != fps_max()) {" in steady and "pace_fps()" not in steady, "the Steady frame rate row no longer goes by the cap itself")
    check("return seen && hos_now_ns() - seen < 250000000LL;" in block(vi, "static int movie_plays(void) {"),
          "a movie no longer plays for a quarter second after its player's update")
    check("movie_seen();" in block(vi, "uint32_t hos_movie_frames(uint64_t player) {")[:400], "a movie player's update is not noted")

    presented = block(vi, "void hos_vi_native_presented(void) {")
    order = [presented.index(s) for s in ("const int interval = fps_max() < 60 ? 1 : present_interval;", "movie_pace_decide();",
                                          "const int64_t period = steady_period(1000000000LL / pace_fps() * interval, now);",
                                          "pace_period_ns = period;", "realtime_step(now);")]
    check(order == sorted(order) and presented.count("movie_pace_decide();") == 1,
          "the present does not decide once, before the period it paces by and the step")
    step = block(vi, "static void realtime_step(int64_t now) {")
    check("fps_max()" not in step and step.count("pace_fps()") == 1 and "const int pace = pace_fps();" in step,
          "realtime_step does not go by the pace, asked once")
    for line in ("const int was = *limit, to = movie_pace_limit(&raised, was, pace);", "if (to != was) *limit = to;",
                 "const int was = *slot, back = movie_pace_slot(was, before, pace);", "if (back != was) *slot = back;",
                 "if (!rx_option(0, 1) && pace == 60) {", "const int timed = pace > 60 && timed_step && hos_step_probe;",
                 "const int top = timed ? 60 : pace;", "if (*slot < 15 || *slot > (pace > 60 ? pace : 60)) {",
                 "if (paced && paced != pace) { count = next = 0; carry = 0; step_steady_reset(&steady); }"):
        check(line in step, "realtime_step lost: " + line)
    check(step.index("const int pace = pace_fps();") < step.index("movie_pace_slot(") < step.index("movie_pace_limit(")
          < step.index("if (!rx_option(0, 1) && pace == 60) {"), "the slot and the limiter are not settled before the per-frame speed's early return")
    vsync = block(vi, "static DWORD WINAPI vsync_main(void *p) {")
    check("1000000000LL / fps_max()" in vsync and "pace_fps" not in vsync, "the vsync event no longer goes by the cap itself")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_MOVIE_PACE=0`" in dev, "docs/development.md: HOS_MOVIE_PACE=0 is not in the switches table")

    movie = vi[vi.index("static volatile LONG64 movie_seen_ns;"):vi.index("static int pace_handed(void) {")]
    host = "\n".join([block(vi, "static int fps_cap_of("), block(vi, "static int fps_max(void) {"), movie, "static int movie_raise;",
                      block(vi, "static int pace_fps(void) {"), decide, block(vi, "static float text_scale("),
                      block(vi, "static int realtime_rate("), step])
    with tempfile.TemporaryDirectory(prefix="movie-pace-") as tmp:
        src, exe = Path(tmp) / "rules.c", Path(tmp) / "rules.exe"
        src.write_text(RULES, encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(HOST), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the movie pace's rules:\n" + r.stdout)
        src, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture.exe"
        src.write_text(FIXTURE.replace("@HOST@", host), encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I", str(HOST), str(src),
                        "-o", str(exe), "-lm"], check=True)
        for mode, cap, raised, env in CASES:
            e = {k: v for k, v in os.environ.items() if not k.startswith(("HOS_", "SI_"))}
            e.update(env)
            r = subprocess.run([str(exe), mode, str(cap), str(raised)], capture_output=True, text=True, env=e)
            check(r.returncode == 0 and "PASS: %s %d %d" % (mode, cap, raised) in r.stdout,
                  "%s at a cap of %d with %s:\n%s%s" % (mode, cap, env or "nothing set", r.stdout, r.stderr))
    print("PASS: a movie at the 60 cap is paced at 240 with the limiter and the time step following, and the cap is back after it")


if __name__ == "__main__":
    main()
