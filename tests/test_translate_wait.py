"""A bounded wait for a draw whose program is still translating (gpu/vk/translate_wait.h; vk_draw.cpp draw, translate_note,
translate_wait_ms; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-30, after Source A's.) A draw whose program was still translating waited for
it, its thread running the job if it was still queued. With RX_VK_TRANSLATE_WAIT_MS=<ms> (off by default; 8 to try), a draw
into targets that hold an earlier frame, of a program key whose translated variants write no memory, waits at most that
much a frame in all, never running the job, then is left out; a spent budget leaves it out at once. A key never translated,
a key with a writing variant and a draw into new targets wait as before.

The header is compiled and run: the strict parse (digits only, 1 to 100), the choice, the notes of which keys write.
Then the draw's translation block is cut out of draw() and run over stand-ins whose translation finishes after a set time:
  - off (unset or a bad value): every draw waits for it, as before (RX_VK_PIPE_SKIP=2's skip kept);
  - on: a known clean key into kept targets waits at most the budget, hurried and not run here, and is drawn when the
    translation comes in time; left out and counted when not; the budget is charged, and a spent one leaves the next out
    at once; a new frame fills it again;
  - on: an unknown key, a writer's key and a draw into new targets wait as before;
  - RX_VK_PIPE_SKIP=0 waits for all.
And translate_note, cut out, notes a key only while the switch is on, and a writer sticks. The source: the notes are taken
at graphics_pipeline's new entry and the precompile's loads; the switches table has the row.

    python -I -B tests/test_translate_wait.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

HEADER = r"""
#include <cstdio>
#include "translate_wait.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace translate_wait;
int main() {
    CHECK(parse(nullptr) == 0 && parse("") == 0 && parse("8") == 8 && parse("100") == 100 && parse("1") == 1);
    CHECK(parse("0") == 0 && parse("101") == 0 && parse("8ms") == 0 && parse("-8") == 0 && parse(" 8") == 0 && parse("99999999999") == 0);
    CHECK(choose(0, true, true, 8 * kMs) == Act::AsBefore && choose(8, false, true, 8 * kMs) == Act::AsBefore);
    CHECK(choose(8, true, false, 8 * kMs) == Act::AsBefore && choose(8, true, true, 8 * kMs) == Act::Bounded);
    CHECK(choose(8, true, true, kMs) == Act::Bounded && choose(8, true, true, kMs - 1) == Act::Skip && choose(8, true, true, 0) == Act::Skip);
    Notes n;
    CHECK(!n.clean(1));
    n.note(1, false);
    CHECK(n.clean(1));
    n.note(1, true);
    n.note(1, false);
    CHECK(!n.clean(1));   // (a writing variant sticks)
    n.note(2, true);
    CHECK(!n.clean(2) && !n.clean(3));
    std::printf("ok\n");
    return 0;
}
"""

FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <thread>
#include "pipe_wait.h"
#include "translate_wait.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
struct Program { uint64_t key; bool failed = false, compute = false; bool writes = false; std::atomic<bool> ready{false}; };
struct Targets { bool kept; };
uint64_t frame_now = 1;
uint64_t texture_frame_no() { return frame_now; }
bool pass_kept(const Targets& at, bool) { return at.kept; }
bool targets_persistent(const Targets& at) { return at.kept; }
bool pipe_skip_new() { return true; }
int64_t left_count, st_pending_skips;
void left_out_pending() { left_count++; }
std::atomic<int64_t> st_shader_wait_us{0}, st_translate_bounded{0}, st_translate_left{0};
void note_wait(std::chrono::steady_clock::time_point, std::atomic<int64_t>&) {}
// (the translation: done after finish_ms of waiting; a bounded wait hurries it and never runs it)
int finish_ms = 0, bounded_calls = 0, full_waits = 0, last_bound_ms = 0;
bool jobs_wait_for(const std::atomic<bool>& flag, int ms) {
    bounded_calls++, last_bound_ms = ms;
    if (finish_ms <= ms) const_cast<std::atomic<bool>&>(flag).store(true);
    std::this_thread::sleep_for(std::chrono::milliseconds(std::min(ms, finish_ms)));
    return flag.load();
}
bool writes_memory(const Program& p) { return p.writes; }
/* SWITCH */
/* NOTE */
static std::string run(Program& prog, const Targets& at) {
    const Program* cp = &prog;
    static const bool always_wait = getenv("RX_VK_PIPE_SKIP") && atoi(getenv("RX_VK_PIPE_SKIP")) == 0;
    static const bool legacy_translation_skip = getenv("RX_VK_PIPE_SKIP") && atoi(getenv("RX_VK_PIPE_SKIP")) == 2;
    auto wait_for = [&](const std::atomic<bool>& ready, std::atomic<int64_t>&) {
        full_waits++;
        const_cast<std::atomic<bool>&>(ready).store(true);   // (waited out: the job ran here)
    };
    const int64_t left_before = left_count;
    [&] {
        /* BLOCK */
    }();
    return left_count != left_before ? "left" : full_waits ? "waited" : "drawn";
}
int main(int argc, char** argv) {
    const std::string arm = argc > 1 ? argv[1] : "";
    const Targets kept{true}, fresh{false};
    Program clean{1}, writer{2}, unknown{3};
    writer.writes = true;
    translate_note(clean);
    translate_note(writer);
    const auto reset = [&](Program& p) { p.ready = false, full_waits = 0, bounded_calls = 0; };
    if (arm == "off" || arm == "bad" || arm == "always") {   // (every draw waits, as before)
        for (Program* p : {&clean, &writer, &unknown})
            for (const Targets* t : {&kept, &fresh}) {
                reset(*p);
                CHECK(run(*p, *t) == "waited" && bounded_calls == 0);
            }
        CHECK(st_translate_bounded == 0 && st_translate_left == 0 && left_count == 0);
        std::printf("ok\n");
        return 0;
    }
    if (arm == "legacy") {   // (RX_VK_PIPE_SKIP=2: its skip, as before)
        reset(clean);
        CHECK(run(clean, kept) == "left" && bounded_calls == 0 && st_pending_skips == 1);
        std::printf("ok\n");
        return 0;
    }
    // on, 8 ms: a known clean key into kept targets, translated in time: drawn, no full wait, the job not run here
    finish_ms = 3, reset(clean);
    CHECK(run(clean, kept) == "drawn" && bounded_calls == 1 && last_bound_ms == 8 && full_waits == 0 && st_translate_bounded == 1);
    // not in time: left out and counted
    finish_ms = 50, reset(clean);
    CHECK(run(clean, kept) == "left" && st_translate_left == 1 && st_pending_skips == 1 && full_waits == 0);
    // the budget is spent: the next is left out at once, not waited for
    reset(clean);
    CHECK(run(clean, kept) == "left" && bounded_calls == 0 && st_translate_left == 2);
    // a new frame fills it again
    frame_now++, finish_ms = 2, reset(clean);
    CHECK(run(clean, kept) == "drawn" && bounded_calls == 1);
    // an unknown key, a writer's key, new targets: waited for, as before
    finish_ms = 50;
    for (Program* p : {&unknown, &writer}) {
        reset(*p);
        CHECK(run(*p, kept) == "waited" && bounded_calls == 0);
    }
    reset(clean);
    CHECK(run(clean, fresh) == "waited" && bounded_calls == 0);
    // a program already translated: nothing of it
    clean.ready = true, full_waits = 0, bounded_calls = 0;
    CHECK(run(clean, kept) == "drawn" && bounded_calls == 0 && full_waits == 0);
    std::printf("ok\n");
    return 0;
}
"""


def block(text, marker, start_at=0):
    start = text.index(marker, start_at)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def ordered(text, parts, why):
    last = 0
    for p in parts:
        k = text.find(p, last)
        need(k >= 0, why + " (missing, or out of order: " + p + ")")
        last = k + len(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need('#include "translate_wait.h"' in draw, "vk_draw.cpp does not include translate_wait.h")
    after = draw.index("    auto wait_for = [&](const std::atomic<bool>& ready, std::atomic<int64_t>& into) {")
    blk = block(draw, "if (!cp->ready.load(std::memory_order_acquire)) {", after)
    ordered(blk, ["if (legacy_translation_skip && targets_persistent(at)) return left_out_pending(), void(st_pending_skips++);",
                  "if (translate_wait_ms() && !always_wait) {",
                  "translate_wait::choose(translate_wait_ms(), pass_kept(at, pipe_skip_new()),", "translate_notes().clean(cp->key), translate_pool().left(frame));",
                  "jobs_wait_for(cp->ready,", "translate_pool().charge(frame,", "if (!got) return st_translate_left.fetch_add(1",
                  "if (!cp->ready.load(std::memory_order_acquire)) wait_for(cp->ready, st_shader_wait_us);"],
            "draw() does not bound the wait for a translating program as the switch says")
    need("jobs_wait(" not in blk.replace("wait_for(cp->ready, st_shader_wait_us)", ""), "the bounded wait runs the job on the draw's thread")
    switch = "\n".join(block(draw, m) for m in ("int translate_wait_ms() {", "pipe_wait::Pool& translate_pool() {",
                                                 "translate_wait::Notes& translate_notes() {"))
    note = block(draw, "void translate_note(const Program& p) {")
    gp = block(draw, "PipeEntry* graphics_pipeline(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, const uint8_t color_types[8]) {")
    ordered(gp, ["pipeline_note(key, p, s, at, topo, color_types);", "translate_note(p);"], "graphics_pipeline's new entry takes no note")
    pre = block(draw, "void precompile_run(void (*progress)(size_t done, size_t total)) {")
    ordered(pre, ["program_cache_load_some(wanted, [&](Program& p) {", "ensure_layout(p);", "translate_note(p);"],
            "the precompile's loads take no note")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_TRANSLATE_WAIT_MS=<ms>`" in docs, "docs/development.md: the switches table has no RX_VK_TRANSLATE_WAIT_MS row")
    base = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="translate-wait-") as tmp:
        tmp = Path(tmp)
        fixture = (FIXTURE.replace("/* SWITCH */", "void logf(const char*, ...) {}\n" + switch)
                   .replace("/* NOTE */", note).replace("/* BLOCK */", blk))
        for name, text, runs in (("header", HEADER, [("", {})]),
                                 ("draw", fixture, [("on", {"RX_VK_TRANSLATE_WAIT_MS": "8"}), ("off", {}),
                                                    ("bad", {"RX_VK_TRANSLATE_WAIT_MS": "8ms"}),
                                                    ("always", {"RX_VK_TRANSLATE_WAIT_MS": "8", "RX_VK_PIPE_SKIP": "0"}),
                                                    ("legacy", {"RX_VK_TRANSLATE_WAIT_MS": "8", "RX_VK_PIPE_SKIP": "2"})])):
            src, exe = tmp / (name + ".cpp"), tmp / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-I" + str(ROOT / "gpu/vk"),
                            str(src), "-o", str(exe)], check=True)
            for arg, env in runs:
                r = subprocess.run([str(exe)] + ([arg] if arg else []), capture_output=True, text=True, timeout=60, env={**base, **env})
                need(r.returncode == 0 and r.stdout.strip() == "ok", "%s %s: %s" % (name, arg, r.stdout.strip() or r.returncode))
    print("PASS: RX_VK_TRANSLATE_WAIT_MS bounds the wait for a translating program known to write no memory into kept targets; "
          "unset, every such draw waits as before")


if __name__ == "__main__":
    main()
