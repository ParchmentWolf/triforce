"""N64 Classic's frame rate (host/n64_pace.h; host/nn_vi.c n64_pace_decide and pace_fps; gpu/vk/vk_replay.cpp's answer to
HOS_OPT_N64_FPS). Step 7 of n64-classic-mode-plan.md. No game.

Compiles n64_pace.h alone, as tests/test_movie_pace.py does movie_pace.h: the switch read as HOS_MOVIE_PACE is; the rate
taken only under the cap, at 15 and up, with no movie playing and the switch on; the pace N64 Classic's where it has one,
else the cap's and a movie's; the present's interval 1 at its rate.

Runs nn_vi.c's own fps_cap_of, fps_max, movie_seen, movie_plays, pace_fps, movie_pace_decide and n64_pace_decide, cut out of
the file, on a clock of its own, with the renderer's answer stood in for: at caps of 60, 45, 120 and 30 and rates of 20,
17, 60, 30, 10 and none, a stretch of play, a movie, play again and the renderer's rate gone; with HOS_N64_PACE=0 too.
At the 60 cap a movie still raises the pace to 240 over N64 Classic's 20, and the 20 is back a quarter second after the
movie's last picture; each change is said once in the log.

Reads the sources: nn_vi.c takes n64_pace.h, its pace_fps is the rule's over the movie's, movie_pace_decide asks
n64_pace_decide once a present, the present's interval is 1 at the rate, and the vsync event and fps_max still go by the
cap; vk_api.h's HOS_OPT_N64_FPS is a number of its own; vk_replay.cpp answers it with n64_rules.h's rate while the 3D
pass draws; the development guide names HOS_N64_PACE.

    python -I -B tests/test_n64_pace.py [--cc clang]
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
#include "n64_pace.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    CHECK(n64_pace_on(NULL) && n64_pace_on("") && n64_pace_on("1") && !n64_pace_on("0") && !n64_pace_on("off"));
    CHECK(N64_PACE_LOWEST == 15);
    /* n64_pace_rate(on, asked, movie, cap) */
    CHECK(n64_pace_rate(1, 20, 0, 60) == 20 && n64_pace_rate(1, 17, 0, 60) == 17 && n64_pace_rate(1, 30, 0, 60) == 30);
    CHECK(n64_pace_rate(1, 20, 1, 60) == 0);                                   /* a movie plays */
    CHECK(n64_pace_rate(0, 20, 0, 60) == 0);                                   /* HOS_N64_PACE=0 */
    CHECK(n64_pace_rate(1, 60, 0, 60) == 0 && n64_pace_rate(1, 60, 0, 45) == 0);   /* never at or above the cap */
    CHECK(n64_pace_rate(1, 60, 0, 120) == 60 && n64_pace_rate(1, 30, 0, 30) == 0);
    CHECK(n64_pace_rate(1, 14, 0, 60) == 0 && n64_pace_rate(1, 15, 0, 60) == 15 && n64_pace_rate(1, 0, 0, 60) == 0);
    for (int cap = 30; cap <= 240; cap++)
        for (int asked = 0; asked <= 250; asked++) {
            const int r = n64_pace_rate(1, asked, 0, cap);
            CHECK(r == 0 || (r == asked && r < cap && r >= 15));               /* only ever lower, and the step's to take */
        }
    /* n64_pace_fps(rate, paced) */
    CHECK(n64_pace_fps(20, 60) == 20 && n64_pace_fps(0, 240) == 240 && n64_pace_fps(0, 60) == 60 && n64_pace_fps(17, 45) == 17);
    /* n64_pace_interval(rate, interval) */
    CHECK(n64_pace_interval(20, 2) == 1 && n64_pace_interval(20, 1) == 1 && n64_pace_interval(0, 2) == 2 && n64_pace_interval(0, 1) == 1);
    return fails ? 1 : 0;
}
"""

FIXTURE = r'''#define _CRT_SECURE_NO_WARNINGS
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pace_steady.h"
#include "movie_pace.h"
#include "n64_pace.h"
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
enum { HOS_OPT_DISPLAY_CAP = 60 };
enum { HOS_OPT_N64_FPS = 61 };
static int n64_asked;   /* (the renderer's answer: vk_replay.cpp, n64_rules.h fps) */
int rx_option(int id, int otherwise) { return id == HOS_OPT_N64_FPS ? n64_asked : otherwise; }
int hos_ini_option(const char *key, int otherwise) { (void)key; return otherwise; }
static volatile long long presents;
@HOST@
/* a present: the clock on by a frame, the decision as hos_vi_native_presented takes it */
static int present(void) {
    clock_ns += 16666667;
    movie_pace_decide();
    return pace_fps();
}
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    n64_asked = atoi(argv[1]);
    int play = 0, movie = 0, after = 0, gone = 0;
    for (int i = 0; i < 30; i++) play = present();
    for (int i = 0; i < 30; i++) movie_seen(), movie = present();          /* a movie: its player updates every frame */
    clock_ns += 260000000LL;                                                 /* a quarter second after its last picture */
    for (int i = 0; i < 30; i++) after = present();
    n64_asked = 0;                                                           /* the renderer asks none: N64 Classic off */
    for (int i = 0; i < 30; i++) gone = present();
    printf("%d %d %d %d %d %d %d\n", fps_max(), play, movie, after, gone, logged("vi: N64 Classic: frames paced at "),
           logged("vi: N64 Classic: frames paced at the cap again"));
    return 0;
}
'''

# (the cap, by HOS_FPS_MAX; the rate the renderer asks; HOS_N64_PACE) -> the cap, the pace in play, in the movie, after it,
# with the rate gone; the changes said, those back to the cap said
CASES = (
    ((60, 20, None), "60 20 240 20 60 4 2"),    # (a movie at the 60 cap: 240 over the 20, and back)
    ((60, 17, None), "60 17 240 17 60 4 2"),
    ((45, 20, None), "45 20 45 20 45 4 2"),     # (no movie raise at 45: the cap's while it plays)
    ((120, 60, None), "120 60 120 60 120 4 2"),
    ((30, 30, None), "30 30 30 30 30 0 0"),     # (at the cap: nothing to lower)
    ((60, 10, None), "60 60 240 60 60 0 0"),    # (under the step's floor: not taken)
    ((60, 0, None), "60 60 240 60 60 0 0"),     # (N64 Classic off)
    ((60, 20, "0"), "60 60 240 60 60 0 0"),     # (HOS_N64_PACE=0)
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    vi = (HOST / "nn_vi.c").read_text(encoding="utf-8")
    check('#include "n64_pace.h"' in vi, "nn_vi.c does not take n64_pace.h")
    check("return n64_pace_fps(n64_rate, movie_pace_fps(movie_raise, fps_max()));" in block(vi, "static int pace_fps(void) {"),
          "pace_fps is not N64 Classic's rate over the cap's and the movie's")
    decide = block(vi, "static void movie_pace_decide(void) {")
    check(decide.rstrip().endswith("n64_pace_decide();   /* ((Triforce, N64 Classic, step 7) its rate, beside the movie's */\n}"),
          "movie_pace_decide does not ask n64_pace_decide once a present, after the movie's decision")
    n64 = block(vi, "static void n64_pace_decide(void) {")
    for need in ('n64_pace_on(getenv("HOS_N64_PACE"))', "n64_rate = n64_pace_rate(on, on ? rx_option(HOS_OPT_N64_FPS, 0) : 0, movie_plays(), fps_max());"):
        check(need in n64, "n64_pace_decide: %s is gone" % need)
    presented = block(vi, "void hos_vi_native_presented(void) {")
    check("const int interval = n64_pace_interval(n64_rate, fps_max() < 60 ? 1 : present_interval);" in presented and
          presented.index("const int interval =") < presented.index("movie_pace_decide();") < presented.index("pace_fps() * interval"),
          "the present's interval is not 1 at N64 Classic's rate, or the period is not taken after the decision")
    check("1000000000LL / fps_max()" in block(vi, "static DWORD WINAPI vsync_main(void *p) {"), "the vsync event no longer goes by the cap")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
    check("enum { HOS_OPT_N64_FPS = 61 };" in api and "enum { HOS_OPT_DISPLAY_CAP = 60 };" in api,
          "vk_api.h: HOS_OPT_N64_FPS is not 61, beside HOS_OPT_DISPLAY_CAP")
    taken = [int(v) for v in re.findall(r"HOS_OPT_\w+ = (\d+)", api)]
    check(taken.count(61) == 1 and not re.search(r"HOS_OPT_DISPLAY_CAP = 60, ", api), "vk_api.h: another option has 61")
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    check("if (id == HOS_OPT_N64_FPS) return n64_3d_now() ? n64_rules::fps(n64_look()) : 0;" in replay and '#include "vk_n64.h"' in replay,
          "vk_replay.cpp does not answer HOS_OPT_N64_FPS with n64_rules.h's rate while the 3D pass draws")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_N64_PACE=0`" in dev and "`HOS_OPT_N64_FPS`" in dev, "docs/development.md: HOS_N64_PACE and HOS_OPT_N64_FPS are not said")

    movie = vi[vi.index("static volatile LONG64 movie_seen_ns;"):vi.index("static int pace_handed(void) {")]
    host = "\n".join([block(vi, "static int fps_cap_of("), block(vi, "static int fps_max(void) {"), movie, "static int movie_raise;",
                      "static int n64_rate;", block(vi, "static int pace_fps(void) {"), n64, decide])
    with tempfile.TemporaryDirectory(prefix="n64-pace-") as tmp:
        src, exe = Path(tmp) / "rules.c", Path(tmp) / "rules.exe"
        src.write_text(RULES, encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(HOST), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rules:\n" + r.stdout)
        src, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture.exe"
        src.write_text(FIXTURE.replace("@HOST@", host), encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I", str(HOST), str(src),
                        "-o", str(exe), "-lm"], check=True)
        bad = []
        for (cap, asked, pace_env), expect in CASES:
            env = {k: v for k, v in os.environ.items() if not k.startswith(("HOS_", "RX_"))}
            env["HOS_FPS_MAX"] = str(cap)
            if pace_env is not None:
                env["HOS_N64_PACE"] = pace_env
            got = subprocess.run([str(exe), str(asked)], capture_output=True, text=True, env=env).stdout.strip()
            if got != expect:
                bad.append("cap %d, asked %d, HOS_N64_PACE %s: %s, expected %s" % (cap, asked, pace_env, got, expect))
        if bad:
            raise SystemExit("FAIL:\n  " + "\n  ".join(bad))
    print("PASS: N64 Classic's frame rate paces the game under the cap, gives way to movies, and goes with the mode")


if __name__ == "__main__":
    main()
