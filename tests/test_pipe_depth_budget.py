"""A frame budget, then a skip, for depth-tested draws into passes drawn once (gpu/vk/pipe_wait.h depth_budget, choose's
depth_new; vk_draw.cpp draw, pipe_depth_budget, pipe_depth_timed_out; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-29, after Source B's.) A draw into a pass drawn once waits for its pipeline
however long it takes; Source B saw an Arc B580 freeze 11-13 s twice on some fifty new pipelines of such passes. With
RX_VK_PIPE_DEPTH_BUDGET=1, a depth-tested draw into such a pass whose shaders write no memory, outside a samples-passed
count and not into the icon capture's kept targets, waits from the frame's pool, then is left out, and its pipeline is left
out at once until it is built. Off by default on every driver: the entry's default for Intel's Windows driver waits for the
owner's word.

The header is compiled: the switch (off unless set, on any driver); choose() with depth_new waits from the pool and is left
out once it is spent; a writer, a kept pass and depth_new false choose as before, checked against the old choose() over a
grid of every input. Then the draw's miss block is cut out of draw() and run over stand-ins whose pipeline builds after a
set time:
  - unset: a depth-tested draw into a new pass waits for its pipeline, as before;
  - set: it waits from the pool and is drawn when the pipeline comes in time; when not, it is left out and its entry then
    left out at once (no wait) until the set is emptied; a spent pool leaves the next out at once;
  - set: a writer, a draw without depth (or its test off), one inside a samples-passed count, and one into targets kept
    from an earlier frame wait (or are left out) as before;
  - RX_VK_PIPE_SKIP=0 waits for all.
And reads the source for the hooks and the switches table's row.

    python -I -B tests/test_pipe_depth_budget.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

RULE = r"""
#include <cstdio>
#include "pipe_wait.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace pipe_wait;
// choose() as it was before depth_new
static Choice old_choose(const Rules& r, bool kept, bool writes, bool full, bool held, int64_t pool_ns, int64_t last_ns) {
    if (r.always_wait) return {Act::WaitAll, 0, K_NONE};
    if (!kept || writes) {
        if (!r.oneshot_budget) return {Act::WaitAll, 0, K_NONE};
        if (pool_ns >= kMinWaitNs) return {Act::Wait, pool_ns, K_ONESHOT};
        return {Act::Skip, 0, K_NONE};
    }
    if (!full || held || !r.full_wait) return {Act::Skip, 0, K_NONE};
    if (pool_ns >= kMinWaitNs) return {Act::Wait, pool_ns, K_FULL};
    if (last_ns >= kMinWaitNs) return {Act::Wait, last_ns, K_LAST};
    return {Act::Skip, 0, K_NONE};
}
static bool same(Choice a, Choice b) { return a.act == b.act && a.ns == b.ns && a.kind == b.kind; }
int main() {
    CHECK(!depth_budget(nullptr) && !depth_budget("") && !depth_budget("0") && depth_budget("1") && depth_budget("2"));
    const Rules plain;
    CHECK(same(choose(plain, false, false, false, false, 50 * kMs, 40 * kMs, true), Choice{Act::Wait, 50 * kMs, K_DEPTH}));
    CHECK(same(choose(plain, false, false, false, false, kMs - 1, 40 * kMs, true), Choice{Act::Skip, 0, K_NONE}));   // (spent)
    // as before wherever depth_new does not apply, over every input
    const int64_t pools[] = {0, kMs - 1, kMs, 50 * kMs};
    for (int always = 0; always < 2; always++)
        for (int oneshot = 0; oneshot < 2; oneshot++)
            for (int fw = 0; fw < 2; fw++)
                for (int kept = 0; kept < 2; kept++)
                    for (int writes = 0; writes < 2; writes++)
                        for (int full = 0; full < 2; full++)
                            for (int held = 0; held < 2; held++)
                                for (int64_t pool : pools)
                                    for (int64_t last : pools)
                                        for (int dn = 0; dn < 2; dn++) {
                                            Rules r;
                                            r.always_wait = always, r.oneshot_budget = oneshot, r.full_wait = fw;
                                            const Choice now = choose(r, kept, writes, full, held, pool, last, dn);
                                            const Choice was = old_choose(r, kept, writes, full, held, pool, last);
                                            const bool applies = dn && !always && !kept && !writes;
                                            if (!applies) CHECK(same(now, was));
                                            else CHECK(now.kind == K_DEPTH ? pool >= kMs : now.act == Act::Skip);
                                        }
    std::printf("ok\n");
    return 0;
}
"""

FIXTURE = r"""
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_set>
#include "pipe_wait.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
#define PROF_EXACT() ((void)0)
struct Program { uint64_t key = 0x1234; bool writes = false; };
struct PipeEntry { std::atomic<bool> ready{false}; };
struct Targets { bool kept = false; void* depth = nullptr; };
struct NvnState { struct { bool dt = false; } ds; };
struct DrawArgs {};
uint64_t frame_now = 1;
uint64_t texture_frame_no() { return frame_now; }
bool pass_kept(const Targets& at, bool) { return at.kept; }
bool targets_persistent(const Targets& at) { return at.kept; }
bool pipe_skip_new() { return true; }
bool writes_memory(const Program& p) { return p.writes; }
bool full_screen_draw(const NvnState&, const Targets&, const DrawArgs&) { return false; }
bool hold_takes_frame() { return false; }
bool counting = false;
bool occ_counting_now() { return counting; }
const pipe_wait::Rules& pipe_rules() {
    static const pipe_wait::Rules r = [] { pipe_wait::Rules x; x.always_wait = getenv("RX_VK_PIPE_SKIP") && atoi(getenv("RX_VK_PIPE_SKIP")) == 0; return x; }();
    return r;
}
pipe_wait::Pool& pipe_pool() { static pipe_wait::Pool p(50 * pipe_wait::kMs); return p; }
pipe_wait::Pool& pipe_last() { static pipe_wait::Pool p(40 * pipe_wait::kMs); return p; }
int64_t st_pending_skips, left;
int64_t st_pipe_new_waits, st_pipe_full_waits, st_pipe_full_held, st_pipe_full_left;
void left_out_pending() { left++; }
void logf(const char*, ...) {}
// (the pipeline: built after finish_ms; a bounded wait hurries it, a full wait runs it out)
int finish_ms = 0, bounded = 0, full_waits = 0;
bool pipe_wait_for(const std::atomic<bool>& ready, int64_t ns) {
    bounded++;
    const int ms = (int)(ns / pipe_wait::kMs);
    std::this_thread::sleep_for(std::chrono::milliseconds(std::min(ms, finish_ms)));
    if (finish_ms <= ms) const_cast<std::atomic<bool>&>(ready).store(true);
    return ready.load();
}
/* SWITCH */
static std::string run(PipeEntry* pe, Program& p, const Targets& at, const NvnState& s) {
    static const bool always_wait = getenv("RX_VK_PIPE_SKIP") && atoi(getenv("RX_VK_PIPE_SKIP")) == 0;
    std::atomic<int64_t> st_pipe_wait_us{0};
    DrawArgs d;
    auto wait_for = [&](const std::atomic<bool>& ready, std::atomic<int64_t>&) {
        full_waits++;
        const_cast<std::atomic<bool>&>(ready).store(true);
    };
    const int64_t l0 = left;
    [&] {
        /* MISS */
    }();
    return left != l0 ? "left" : full_waits ? "waited" : "drawn";
}
int main(int argc, char** argv) {
    const std::string arm = argc > 1 ? argv[1] : "";
    int depth_target = 0;
    Targets fresh_depth{false, &depth_target}, kept_depth{true, &depth_target}, no_depth{false, nullptr};
    NvnState dt, no_dt;
    dt.ds.dt = true;
    Program clean, writer;
    writer.writes = true;
    const auto go = [&](PipeEntry& e, Program& p, const Targets& at, const NvnState& s) {
        e.ready = false, full_waits = 0, bounded = 0;
        return run(&e, p, at, s);
    };
    PipeEntry a, b, c;
    if (arm == "off" || arm == "always") {
        finish_ms = 500;
        CHECK(go(a, clean, fresh_depth, dt) == "waited" && bounded == 0);
        CHECK(go(a, writer, fresh_depth, dt) == "waited" && bounded == 0);
        CHECK(st_pipe_depth_left == 0 && st_pipe_depth_waits == 0);
        std::printf("ok\n");
        return 0;
    }
    // set: in time, drawn from the pool
    finish_ms = 5;
    CHECK(go(a, clean, fresh_depth, dt) == "drawn" && bounded == 1 && st_pipe_depth_waits == 1);
    // not in time: left out, then its entry left out at once
    finish_ms = 500;
    CHECK(go(b, clean, fresh_depth, dt) == "left" && bounded == 1 && st_pipe_depth_left == 1);
    frame_now++;
    CHECK(go(b, clean, fresh_depth, dt) == "left" && bounded == 0 && st_pipe_depth_left == 2);
    // a spent pool leaves another entry out at once
    CHECK(go(c, clean, fresh_depth, dt) == "left");   // (this one spends the new frame's 50 ms)
    PipeEntry e2;
    CHECK(go(e2, clean, fresh_depth, dt) == "left" && bounded == 0);
    // emptied: waits again
    {
        std::lock_guard lk(pipe_depth_mu);
        pipe_depth_out.clear();
    }
    frame_now++, finish_ms = 2;
    CHECK(go(b, clean, fresh_depth, dt) == "drawn" && bounded == 1);
    // as before: a writer, no depth target, its test off, a samples-passed count open: waited for
    finish_ms = 500;
    PipeEntry f;
    CHECK(go(f, writer, fresh_depth, dt) == "waited" && bounded == 0);
    CHECK(go(f, clean, no_depth, dt) == "waited" && bounded == 0);
    CHECK(go(f, clean, fresh_depth, no_dt) == "waited" && bounded == 0);
    counting = true;
    CHECK(go(f, clean, fresh_depth, dt) == "waited" && bounded == 0);
    counting = false;
    // kept targets: left out as before (no full-screen draw), no budget spent
    CHECK(go(f, clean, kept_depth, dt) == "left" && bounded == 0);
    std::printf("ok\n");
    return 0;
}
"""


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    d = block(draw, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d) {")
    miss = d[d.index("if (!pe->ready.load(std::memory_order_acquire)) {"):d.index("const VkPipeline pl = pe->pipeline;")]
    for line in ("const bool depth_new = !always_wait && !kept && pipe_depth_budget() && at.depth && s.ds.dt && !targets_persistent(at) &&",
                 "!writes_memory(p) && !occ_counting_now();", "const bool depth_out = depth_new && pipe_depth_timed_out(pe);",
                 ": depth_out ? pipe_wait::Choice{pipe_wait::Act::Skip}", "pipe_last().left(frame), depth_new);",
                 "if (depth_new) {", "pipe_depth_time_out(pe);"):
        need(line in miss, "draw()'s miss block lost: " + line)
    switch = "\n".join(block(draw, m) for m in ("bool pipe_depth_budget() {", "bool pipe_depth_timed_out(const void* pe) {",
                                                 "void pipe_depth_time_out(const void* pe) {"))
    switch = ("std::mutex pipe_depth_mu;\nstd::unordered_set<const void*> pipe_depth_out;\n"
              "std::atomic<int64_t> st_pipe_depth_waits{0}, st_pipe_depth_left{0};\n" + switch)
    need("std::unordered_set<const void*> pipe_depth_out;" in draw and "pipe_depth_out.clear();" in block(draw, "int64_t draw_left_out_take() {"),
         "the timed-out entries are not let go at the presents")
    need("bool occ_counting_now() { return occ_live && occ_ctr().counting(" in (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8"),
         "vk_replay.cpp does not say whether a samples-passed count is open")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_PIPE_DEPTH_BUDGET=1`" in docs, "docs/development.md: the switches table has no RX_VK_PIPE_DEPTH_BUDGET row")
    base = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="pipe-depth-") as tmp:
        tmp = Path(tmp)
        fixture = FIXTURE.replace("/* SWITCH */", switch).replace("/* MISS */", miss)
        for name, text, runs in (("rule", RULE, [("", {})]),
                                 ("miss", fixture, [("on", {"RX_VK_PIPE_DEPTH_BUDGET": "1"}), ("off", {}),
                                                    ("always", {"RX_VK_PIPE_DEPTH_BUDGET": "1", "RX_VK_PIPE_SKIP": "0"})])):
            src, exe = tmp / (name + ".cpp"), tmp / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-variable",
                            "-I" + str(ROOT / "gpu/vk"), str(src), "-o", str(exe)], check=True)
            for arg, env in runs:
                r = subprocess.run([str(exe)] + ([arg] if arg else []), capture_output=True, text=True, timeout=60, env={**base, **env})
                need(r.returncode == 0 and r.stdout.strip() == "ok", "%s %s: %s" % (name, arg, r.stdout.strip() or r.returncode))
    print("PASS: RX_VK_PIPE_DEPTH_BUDGET=1 bounds a depth-tested draw into a new pass by the frame's pool, then leaves it out; "
          "unset (every driver), as before")


if __name__ == "__main__":
    main()
