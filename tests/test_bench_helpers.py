"""(Triforce, 11-22) The benchmark's helper-thread test (host/hos_bench.c HOS_BENCH_HELPERS, gpu/vk/vk_replay.cpp par_forced,
launcher/Logic/Benchmark.cs). The source read: no game, no GPU.

- the renderer: HOS_OPT_HELPERS_FORCE's option_set holds the way (0 off, 1 on, -1 the tuner again), par_tune_present applies
  it before the tuner is told the frame (so a held frame is neither a trial's nor a window's), and its option says the helper
  threads a test can use (0 without the tuner: the row's Off, RX_VK_PARALLEL);
- the host: the test asks once what it can use, holds a scene's first way during that scene's settling, turns the order from
  scene to scene, measures both halves, settles again after the switch, writes both halves and the threads used, and gives
  the way back to the tuner once the run ends;
- the launcher: it sets HOS_BENCH_HELPERS=1 and the row's Automatic for the run (the row's Off has no helper threads), and
  the start dialog has the choice.

    python -I -B tests/test_bench_helpers.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def function(text, head):
    start = text.find(head)
    check(start >= 0, "%s is missing" % head.rstrip(" {("))
    return text[start:text.index("\n}\n", start) + 3]


def in_order(text, steps, what):
    at = 0
    for s in steps:
        i = text.find(s, at)
        check(i >= 0, "%s: %r is missing or out of order" % (what, s))
        at = i + len(s)


def main():
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
    check("enum { HOS_OPT_HELPERS_FORCE = 170 };" in api, "HOS_OPT_HELPERS_FORCE is not option 170 (165 to 169 are the achievements')")
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    check("std::atomic<int> par_forced{-1};" in replay, "par_forced: the tuner decides unless the benchmark holds a way")
    in_order(function(replay, "void par_tune_present() {"),
             ["if (!par_auto()) return;", "const replay_threads::Frame fr = par_frame_now(ms);",
              "if (const int forced = par_forced.load(std::memory_order_relaxed); forced >= 0) {", "par_auto_on = forced == 1;",
              "return;", "tuner.step(fr, par_auto_on, par_stream_order_only());"],
             "par_tune_present: a held way before the tuner")
    check("if (id == HOS_OPT_HELPERS_FORCE) return par_forced.store(value < 0 ? -1 : value ? 1 : 0, std::memory_order_relaxed);"
          in replay, "option_set HOS_OPT_HELPERS_FORCE no longer holds the way")
    check("if (id == HOS_OPT_HELPERS_FORCE) return par_auto() ? par_threads_max() : 0;" in replay,
          "option HOS_OPT_HELPERS_FORCE no longer says the threads a test can use")

    bench = (ROOT / "host" / "hos_bench.c").read_text(encoding="utf-8")
    check('getenv("HOS_BENCH_HELPERS")' in bench and "B.helper_threads = -1;" in bench, "HOS_BENCH_HELPERS is not read")
    present = function(bench, "void hos_bench_present(int64_t now) {")
    in_order(present, ["case MKWVK_BENCH_SETTLE:", "B.helper_threads = rx_option(HOS_OPT_HELPERS_FORCE, 0);",
                       "if (helper_test() && !B.way_set) {", "B.way = B.scene % 2, B.way_set = 1, B.t_phase = now;",
                       "rx_option_set(HOS_OPT_HELPERS_FORCE, B.way);", "if (now - B.t_phase >= SETTLE_NS) {"],
             "the settling: the scene's first way held, the order turned from scene to scene")
    in_order(present, ["case MKWVK_BENCH_MEASURE:", "if (helper_test()) {", "stats_of(&B.halves[B.way]);", "if (B.half == 0) {",
                       "B.half = 1, B.way ^= 1;", "rx_option_set(HOS_OPT_HELPERS_FORCE, B.way);",
                       "B.phase = MKWVK_BENCH_SETTLE, B.t_phase = now;", "scene_done();"],
             "the measurement: both halves, settled again after the switch")
    in_order(present, ["if (helper_test() && B.phase >= MKWVK_BENCH_DONE", "rx_option_set(HOS_OPT_HELPERS_FORCE, -1);"],
             "the run's end: the tuner decides again")
    check("B.half = 0, B.way_set = 0;" in function(bench, "static void go_scene(int64_t now) {"), "a new scene's halves")
    results = function(bench, "static void write_results(int stopped) {")
    in_order(results, ['if (r->tested) {', '\\"helpers\\":{\\"first\\":\\"%s\\",\\"off\\":', "json_half(f, &r->way[0]);",
                       '\\"on\\":', "json_half(f, &r->way[1]);"], "the results: both halves")
    check('if (B.helpers) fprintf(f, ",\\"helper_test\\":{\\"threads\\":%d}"' in results, "the results: the threads used")

    launcher = (ROOT / "launcher" / "Logic" / "Benchmark.cs").read_text(encoding="utf-8")
    check('if (helperTest) si.Environment["HOS_BENCH_HELPERS"] = "1";' in launcher, "the launcher does not ask for the test")
    check("keys[KHelpers] = HelpersAutomatic;" in launcher, "the launcher does not give the test Automatic's helper threads")
    backend = (ROOT / "launcher" / "App" / "Backend.Bench.cs").read_text(encoding="utf-8")
    check('("helpers", "With the helper-thread test", false)' in backend and '"helpers" => RunBench(compare: false, helperTest: true)'
          in backend, "the start dialog has no helper-thread test")
    print("PASS: the benchmark's helper-thread test holds each way past the tuner, measures both halves in turned order, "
          "writes them, and gives the way back; the launcher asks for it and suggests the row")


if __name__ == "__main__":
    main()
