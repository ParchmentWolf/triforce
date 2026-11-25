"""At a Frame rate cap of 60 or under, frames slower than a whole step keep the game's counters at the clock (HOS_FRAME_CARRY).

With Game speed Real time, host/nn_vi.c realtime_step gives the engine the rate of the last frames (+0x2c8, 15 to 60), and the
game steps 60 / rate a frame: 1.30 at 46 fps. The counters the game cuts to whole frames (nx2/oot_patches.py patch_whole_frames:
the time of day, the water's ripple substeps, the pick-up indicator; patch_battle_steps) and the clock of a loop of one frame or
less (patch_loop_steps, patch_loop_pose: the frozen Zoras) carried their fractions only while the frames' own time is the step,
a cap above 60. At a cap of 60 the cut threw the fraction away: 46 frames of 1.30 counted 46 whole frames, not the 60 that a
second at 60 fps counts, and the day ran at 77 %. A cap under 60 that is no whole step (45: 1.33) lost it on every frame.

Here the host's own carries (carry_fractions and the hooks, cut out of host/nn_vi.c) are handed the rate realtime_step would
give the game and what it paced by, and each frame's counters take the step the game makes from that rate:
- 46 and 50 fps at cap 60, and a cap of 45: a second hands out 60 whole frames, the time of day 120 game seconds, the water's 4
  substeps 240, and a loop of one frame takes whole steps that add up to the clock, its pose the loop's start;
- a whole step (60, 30, 20, 15 fps: steps 1, 2, 3, 4) is cut as the game cuts it, a fraction of an amount included, as before;
- HOS_FRAME_CARRY=0: cut as before (46 a second at 46 fps);
- a cap above 60 is unchanged: with the frames' own time (the hook) the carries go on as before; without it (HOS_FPS_STEP=0: the
  rate up to the cap, or a rate under 60 there) the cut as before;
- before realtime_step has run once (nothing paced yet) the cut as before;
- HOS_FPS_LOG: the "vi: whole-frame counters" line says what the counters took against the step (1.000 kept, 0.77 cut at 46 fps).

python -I -B tests/test_frame_carry_cap60.py [--cc gcc]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#define _CRT_SECURE_NO_WARNINGS
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
static int fails;
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
typedef int SRWLOCK;   /* (one thread here) */
#define SRWLOCK_INIT 0
#define AcquireSRWLockExclusive(l) ((void)(l))
#define ReleaseSRWLockExclusive(l) ((void)(l))
static uint8_t guest[0x4000];
#define GP(a) ((void *)(guest + (a)))
#define MOD 0x1000u
static char whole_line[256];   /* (the last "vi: whole-frame counters" line: HOS_FPS_LOG) */
static void hos_log(const char *fmt, ...) {
    char text[256];
    va_list args; va_start(args, fmt); vsnprintf(text, sizeof text, fmt, args); va_end(args);
    if (!strncmp(text, "vi: whole-frame counters", 24)) memcpy(whole_line, text, sizeof text);
}
volatile uint64_t hos_gfx_module = MOD;
volatile uint32_t hos_frame_seconds_bits;
@HOST@
static uint32_t bits(float f) { uint32_t b; memcpy(&b, &f, 4); return b; }
static float real(uint32_t b) { float f; memcpy(&f, &b, 4); return f; }
/* (what realtime_step leaves the game: what it paced by, the rate in the game's slot, and the frame's seconds with the hook) */
static void given(int pace, int rate, float seconds) {
    step_pace = pace;
    *(int *)GP(MOD + 0x2c8) = rate;
    hos_frame_seconds_bits = seconds > 0.0f ? bits(seconds) : 0;
}
/* (the game's step, as the engine makes it at its two divides: 60 / the rate it was given, or 60 * the frame's seconds with the
   hook) */
static float game_step(void) {
    const uint32_t s = hos_frame_seconds_bits;
    return s ? 60.0f * real(s) : 60.0f / (float)*(int *)GP(MOD + 0x2c8);
}
typedef struct { uint32_t frames, day, water; float loop, loop_steps; int loop_whole, pose_start; } Second;
/* (`count` frames: each frame the counters take this frame's step) */
static Second second(int count) {
    Second s = {0, 0, 0, 0.0f, 0.0f, 1, 1};
    for (int i = 0; i < count; i++) {
        const float step = game_step();
        s.frames += hos_frame_whole(0x7000, bits(step));                /* (a counter of whole frames) */
        s.day += hos_frame_whole(0x7100, bits(2.0f * step));            /* (the time of day: 2 game seconds a 60th) */
        s.water += hos_frame_whole_times(0x7200, bits(step), 4);        /* (the water's 4 ripple substeps a frame) */
        const float taken = real(hos_loop_step(0x7300, bits(step), bits(0.0f), bits(1.0f)));   /* (a loop of one frame) */
        s.loop_steps += taken;
        s.loop_whole &= taken == (float)(int)taken;
        s.loop += taken;
        while (s.loop >= 1.0f) s.loop -= 1.0f;
        s.pose_start &= hos_loop_pose(bits(s.loop), bits(0.0f), bits(1.0f)) == bits(0.0f);
    }
    return s;
}
int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "";
    if (!strcmp(mode, "carry")) {   /* (Real time, the switch's default) */
        CHECK(!hos_frame_carry());            /* (nothing paced yet: the game's cut) */
        given(0, 46, 0.0f);
        CHECK(!hos_frame_carry() && second(46).frames == 46);
        given(60, 46, 0.0f);                  /* (cap 60, the PC at 46 fps) */
        CHECK(hos_frame_carry());
        Second s = second(46);
        printf("46 fps: %u frames, %u day, %u water substeps, loop steps %.3f\n", s.frames, s.day, s.water, s.loop_steps);
        CHECK(s.frames == 60);            /* (cut: 46) */
        CHECK(s.day == 120);              /* (cut: 92, the day at 77 %) */
        CHECK(s.water == 240);            /* (cut: 184) */
        CHECK(s.loop_whole && s.loop_steps > 59.5f && s.loop_steps < 60.5f && s.pose_start);   /* (the Zoras keep their pose) */
        s = second(460);                  /* (ten seconds) */
        CHECK(s.frames >= 599 && s.frames <= 601 && s.day >= 1199 && s.day <= 1201 && s.water >= 2399 && s.water <= 2401);
        given(60, 50, 0.0f);
        s = second(50);
        printf("50 fps: %u frames, %u day, %u water substeps\n", s.frames, s.day, s.water);
        CHECK(s.frames == 60 && s.day == 120 && s.water == 240);
        given(45, 45, 0.0f);                  /* (a cap of 45, held: every frame steps 1.33) */
        CHECK(hos_frame_carry());
        s = second(450);
        printf("cap 45: %u frames, %u day, %u water substeps in ten seconds\n", s.frames, s.day, s.water);
        CHECK(s.frames >= 599 && s.frames <= 601 && s.day >= 1199 && s.day <= 1201 && s.water >= 2399 && s.water <= 2401);
    }
    if (!strcmp(mode, "carry") || !strcmp(mode, "off")) {
        /* (whole steps 1, 2, 3, 4: cut as the game cuts them, an amount's fraction too (the pick-up indicator's step * distance /
           50), and a loop of one frame keeps the game's step and time) */
        static const int whole[] = {60, 30, 20, 15};
        for (int k = 0; k < 4; k++) {
            given(whole[k] == 60 ? 60 : k & 1 ? 60 : whole[k], whole[k], 0.0f);   /* (a slow PC at cap 60, or that cap itself) */
            CHECK(!hos_frame_carry());
            const float step = game_step();
            CHECK(step == (float)(int)step);
            uint32_t sum = 0;
            for (int i = 0; i < 10; i++) sum += hos_frame_whole(0x7400 + k, bits(0.7f * step));
            CHECK(sum == 10 * (uint32_t)(0.7f * step));
            CHECK(hos_loop_step(0x7500, bits(step), bits(0.0f), bits(1.0f)) == bits(step));
            CHECK(hos_loop_pose(bits(0.25f), bits(0.0f), bits(1.0f)) == bits(0.25f));
        }
    }
    if (!strcmp(mode, "off")) {   /* (HOS_FRAME_CARRY=0: cut as before) */
        given(60, 46, 0.0f);
        CHECK(!hos_frame_carry());
        const Second s = second(46);
        printf("%s, 46 fps: %u frames, %u day, %u water substeps\n", mode, s.frames, s.day, s.water);
        CHECK(s.frames == 46 && s.day == 92 && s.water == 184);
        CHECK(!s.loop_whole);
    }
    if (!strcmp(mode, "cap 120")) {
        given(120, 60, 1.0f / 90.0f);   /* (the frames' own time, the PC at 90 fps: carried as before) */
        CHECK(hos_frame_carry());
        Second s = second(90);
        printf("cap 120, 90 fps: %u frames, %u day, %u water substeps\n", s.frames, s.day, s.water);
        CHECK(s.frames >= 59 && s.frames <= 61 && s.day >= 119 && s.day <= 121 && s.water >= 239 && s.water <= 241);
        CHECK(s.loop_whole && s.pose_start);
        given(120, 90, 0.0f);           /* (HOS_FPS_STEP=0: the rate up to the cap, steps under 1, cut as before) */
        CHECK(!hos_frame_carry());
        s = second(90);
        printf("cap 120 step off, 90 fps: %u frames, %u day\n", s.frames, s.day);
        CHECK(s.frames == 0 && s.day == 90);
        given(120, 46, 0.0f);           /* (and a rate under 60 there: cut as before too) */
        CHECK(!hos_frame_carry() && second(46).frames == 46);
    }
    if (!strncmp(mode, "log", 3)) {   /* (HOS_FPS_LOG: what the counters took against the step, 46 fps at cap 60) */
        given(60, 46, 0.0f);
        second(1000);   /* (3000 calls: one line) */
        printf("%s\n", whole_line);
        const char *kept = strstr(whole_line, "fractions kept"), *cut = strstr(whole_line, "fractions cut");
        double ratio = 0;
        const char *open = strchr(whole_line, '(');
        CHECK(open && sscanf(open, "(%lf)", &ratio) == 1);
        if (!strcmp(mode, "log")) CHECK(kept && ratio > 0.999 && ratio < 1.001);
        else CHECK(cut && ratio > 0.76 && ratio < 0.78);   /* (46 / 60: what a second of 46 frames loses) */
    }
    if (!fails) printf("PASS: %s\n", mode);
    return fails != 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    vi = (ROOT / "host" / "nn_vi.c").read_text(encoding="utf-8")
    # (carry_fractions, the whole frames' hooks and the loops': from the pace realtime_step notes to the next thing in the file)
    start, end = "static volatile int step_pace;", "volatile uint64_t hos_res_module"
    if vi.count(start) != 1 or vi.count(end) != 1 or vi.index(start) > vi.index(end):
        raise SystemExit("FAIL: host/nn_vi.c no longer has its carries between %r and %r" % (start, end))
    host = vi[vi.index(start):vi.index(end)]
    # (realtime_step tells the carries what it paced by, before it can return)
    step = vi[vi.index("static void realtime_step(int64_t now) {"):]
    if not 0 < step.find("__atomic_store_n(&step_pace, pace, __ATOMIC_RELAXED);") < step.find("if (!rx_option(0, 1) && pace == 60) {"):
        raise SystemExit("FAIL: host/nn_vi.c realtime_step does not note its pace for the carries before its returns")
    with tempfile.TemporaryDirectory(prefix="frame-carry-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture.exe"
        c.write_text(FIXTURE.replace("@HOST@", host), encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-I", str(ROOT / "host"), str(c), "-o", str(exe)], check=True)
        failed = []
        for mode, switches in (("carry", {}), ("off", {"HOS_FRAME_CARRY": "0"}), ("cap 120", {}),
                               ("log", {"HOS_FPS_LOG": "1"}), ("log off", {"HOS_FPS_LOG": "1", "HOS_FRAME_CARRY": "0"})):
            env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}
            if subprocess.run([str(exe), mode], env=dict(env, **switches)).returncode:
                failed.append(mode)
        if failed:
            raise SystemExit("FAIL: " + ", ".join(failed))


if __name__ == "__main__":
    main()
