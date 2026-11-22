"""The idle staging arenas stay through a load's burst (gpu/vk/staging_keep.h, vk_texture.cpp staging and texture_frame;
no game, no GPU).

(Triforce, 11-22, the performance audit's TEX-28, after Source A's.) An arena is taken again once the GPU is done with
the submission that read it, known a present later, so frames that stage in a row use two arenas in turn. Where 64 MB
are kept (the driver allows 6.5 GB or less) the one that had its turn was freed at every second present and made again
the present after. An idle arena staged into in the last 2 seconds may now stay while the arenas add up to 256 MB,
unless VRAM is over 90% of the allowance.

This cuts the arenas, staging() and texture_frame's give-back loop out of vk_texture.cpp and runs them with stand-ins
(no memory is really taken), a process a case since the switch and what is kept are read once:
  - a card allowed 6,000 MB, 20 frames that stage 32 MB each: 2 arenas made, not 11, and every make counted; 128 MB
    kept through the burst; 64 MB again once 2 seconds have passed since the last staging;
  - the same with RX_VK_STAGING_BURST_S=0, and with VRAM short (pool_pressed): 11 made, as before;
  - one frame that stages 6 arenas' worth: the idle ones are trimmed to 256 MB at the next present, and an arena over
    64 MB goes at once, burst or not;
  - a card allowed 31,000 MB (256 MB kept anyway), a card that reports nothing, and a 6,000 MB card with VRAM short:
    300 frames of mixed staging with rests give the same makes, frees and sizes present by present with the rule and
    with =0.
And the header's rules by their values, and the source: the loop reads the switch once and asks the header, the
condition is the one it was but for the allowance, staging() counts every arena it makes, the memory line says so, the
switch is in the switches table.

    python -I -B tests/test_staging_burst.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

LOOP_HEAD = "        static const uint64_t keep = []() -> uint64_t {\n"
LOOP_END = "        if (frame_no % 600 == 0) {   // (the process's memory now and then: what the host side holds)\n"

FIXTURE = r'''
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "staging_keep.h"

using VkBuffer = void*;
using VmaAllocation = void*;
#define VK_NULL_HANDLE nullptr
enum { VK_BUFFER_USAGE_TRANSFER_SRC_BIT = 1, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT = 32 };
static struct { struct { struct { uint64_t nonCoherentAtomSize = 64; } limits; } props; } dev;
static uint64_t rec_value = 0;
static bool pool_pressed = false;
static uint64_t card_mb = 0;
static int makes, frees;
static uint64_t live_bytes;
// (no memory is taken: nothing here writes through an arena's pointer)
static bool create_buffer(uint64_t size, int, bool, VkBuffer& b, VmaAllocation& a, void** m) {
    static char mem[16];
    uint64_t* tag = new uint64_t(size);
    b = tag, a = tag, *m = mem;
    makes++, live_bytes += size;
    return true;
}
static void destroy_buffer(VkBuffer, VmaAllocation a) {
    frees++, live_bytes -= *(uint64_t*)a;
    delete (uint64_t*)a;
}
static bool vram_usage(uint64_t* used, uint64_t* allowed) {
    *used = 0, *allowed = card_mb << 20;
    return card_mb != 0;
}
static void logf(const char*, ...) {}
// ((Triforce, 11-22) MEM-141's swap hold, merged into the loop: off, as it always is on Windows
#include "linux_pressure.h"
static bool memory_swap_hold() { return false; }
static void memory_swap_valve(int, uint64_t) {}

/* ARENAS */
/* STAGING */

static uint64_t give_back(uint64_t completed) {
/* LOOP */
    return kept;
}

static int fails;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
constexpr uint64_t MB = 1ull << 20;

static uint64_t frame_at, kept_bytes;
// one frame: its recording stages, then its present learns that the GPU is done with the frame before
static void frame(std::initializer_list<uint64_t> stages_mb) {
    rec_value = ++frame_at;
    for (uint64_t mb : stages_mb) CHECK(staging(mb * MB).data != nullptr);
    completed_value = frame_at - 1;
    kept_bytes = give_back(frame_at - 1);
}
static void age(int ms) {   // (time passes: every arena was last staged into that much longer ago)
    for (Arena& a : arenas) a.used_at -= std::chrono::milliseconds(ms);
}
static void say() {
    std::printf("%llu: made %d freed %d kept %llu MB in %zu arenas, counted %lld\n", (unsigned long long)frame_at, makes, frees,
                (unsigned long long)(kept_bytes / MB), arenas.size(), (long long)st_arena_makes.load());
}

int main(int argc, char** argv) {
    if (argc < 3) return 2;
    card_mb = (uint64_t)std::atoll(argv[1]);
    const char* what = argv[2];
    pool_pressed = argc > 3 && argv[3][0] == 'p';
    if (!std::strcmp(what, "rule")) {
        using namespace staging_keep;
        CHECK(burst_s(nullptr) == 2 && burst_s("") == 2 && burst_s("2") == 2 && burst_s("5") == 5 && burst_s("99999") == 3600);
        CHECK(burst_s("0") == 0 && burst_s("-3") == 0 && burst_s("off") == 0);
        CHECK(recent(2, false, 0) && recent(2, false, 1999) && !recent(2, false, 2000) && !recent(2, false, 60000));
        CHECK(!recent(2, true, 0) && !recent(0, false, 0) && !recent(2, false, -1) && recent(1, false, 999) && !recent(1, false, 1000));
        CHECK(allowance(64 * MB, true) == 256 * MB && allowance(64 * MB, false) == 64 * MB);
        CHECK(allowance(256 * MB, true) == 256 * MB && allowance(256 * MB, false) == 256 * MB);       // (a card over 6.5 GB: no change)
        CHECK(allowance(512 * MB, true) == 512 * MB && allowance(0, false) == 0 && allowance(0, true) == 256 * MB);
    } else if (!std::strcmp(what, "row")) {
        // 20 frames that stage 32 MB each, then a present with nothing staged, then 2 seconds later another
        for (int i = 0; i < 20; i++) frame({32});
        say();
        frame({});
        say();
        age(2000);
        frame({});
        say();
    } else if (!std::strcmp(what, "big")) {
        frame({60, 60, 60, 60, 60, 60});   // (60 + 60 do not fit one arena: six of them, all read by this frame)
        say();
        frame({});                          // (the GPU is done with them: idle, and staged into a moment ago)
        say();
        frame({100});                       // (an arena of 100 MB)
        say();
        frame({});                          // (idle: over 64 MB, it goes at once)
        say();
        age(2000);
        frame({});
        say();
    } else if (!std::strcmp(what, "mix")) {
        uint32_t r = 12345;
        const auto next = [&] { return (r = r * 1664525u + 1013904223u) >> 8; };
        for (int i = 0; i < 300; i++) {
            const uint32_t n = next() % 6;
            rec_value = ++frame_at;
            for (uint32_t k = 0; k < n; k++) CHECK(staging((1 + next() % 60) * MB).data != nullptr);
            if (next() % 7 == 0) age(700 * (int)(1 + next() % 4));
            completed_value = frame_at - 1;
            kept_bytes = give_back(frame_at - 1);
            say();
        }
    } else {
        return 2;
    }
    CHECK(makes == (int)st_arena_makes.load());   // (every make counted)
    CHECK(st_arena_make_ns.load() >= 0);
    uint64_t held = 0;
    for (const Arena& a : arenas) held += a.size;
    CHECK(held == live_bytes && (size_t)(makes - frees) == arenas.size());
    return fails != 0;
}
'''


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check_source(tex):
    check('#include "staging_keep.h"' in tex, "vk_texture.cpp does not include staging_keep.h")
    staging = block(tex, "Staging staging(uint64_t n, uint64_t align = 256) {")
    made = staging.index("const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t_make).count();")
    check(staging.index("if (!small) return {};") < made <
          staging.index("st_arena_makes.fetch_add(1, std::memory_order_relaxed);") <
          staging.index("st_arena_make_ns.fetch_add((int64_t)(ms * 1e6), std::memory_order_relaxed);") < staging.index("arenas.push_back(a);"),
          "staging() does not count every arena it makes, and its time, before it keeps the arena")
    check(staging.count("st_arena_makes") == 1, "staging() counts an arena somewhere else too")
    loop = tex[tex.index(LOOP_HEAD):tex.index(LOOP_END)]
    at = [loop.index(n) for n in (
        'static const int64_t burst_s = staging_keep::burst_s(getenv("RX_VK_STAGING_BURST_S"));',
        "const bool idle = it->value <= completed && it->value != rec_value;",
        # ((Triforce, 11-22) MEM-141's swap hold merged in: a shorter idle while it is on, and no burst's room then
        "const bool stale = idle_now && (swap_hold_began || std::chrono::steady_clock::now() - it->used_at > std::chrono::seconds(idle_now));",
        "swap_hold_on ? keep : staging_keep::allowance(keep, staging_keep::recent(burst_s, pool_pressed, since_used_ms));",
        "if (idle && (it->size > kArena || kept + it->size > allowance || stale)) {",
        "destroy_buffer(it->buffer, it->allocation);")]
    check(at == sorted(at), "the give-back loop no longer reads the switch once and asks staging_keep.h for what may stay")
    check("kept + it->size > keep" not in loop, "the give-back loop still tests what is kept without the burst's allowance")
    check('"vk: memory: working set %llu MB (peak %llu), private %llu MB, staging %llu MB in %zu arenas, %lld made so "' in tex and
          "(long long)st_arena_makes.load(std::memory_order_relaxed)," in tex,
          "the memory line no longer says how many arenas were made")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `RX_VK_STAGING_BURST_S=<seconds>` |" in docs and "`gpu/vk/staging_keep.h`" in docs,
          "docs/development.md: RX_VK_STAGING_BURST_S is not in the switches table")
    arenas = tex[tex.index("struct Arena {"):tex.index("// (GPU writes into guest memory by buffers")]
    check("std::atomic<int64_t> st_arena_makes{0}, st_arena_make_ns{0};" in arenas, "the arenas' counters are not beside the arenas")
    return arenas, staging, loop


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check((VK / "staging_keep.h").is_file(), "gpu/vk/staging_keep.h is not there")
    arenas, staging, loop = check_source((VK / "vk_texture.cpp").read_text(encoding="utf-8"))
    env0 = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_STAGING_")}
    with tempfile.TemporaryDirectory(prefix="staging-burst-") as tmp:
        cpp, exe = Path(tmp) / "burst.cpp", Path(tmp) / "burst.exe"
        cpp.write_text(FIXTURE.replace("/* ARENAS */", arenas).replace("/* STAGING */", staging).replace("/* LOOP */", loop),
                       encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(cpp), "-o", str(exe)],
                       check=True)

        def run(card, what, burst=None, pressed=False):
            env = dict(env0)
            if burst is not None:
                env["RX_VK_STAGING_BURST_S"] = burst
            r = subprocess.run([str(exe), str(card), what] + (["pressed"] if pressed else []), capture_output=True, text=True, env=env)
            check(r.returncode == 0, "%s on a card allowed %d MB (RX_VK_STAGING_BURST_S %s%s):\n%s"
                  % (what, card, burst or "unset", ", VRAM short" if pressed else "", r.stdout + r.stderr))
            return r.stdout.splitlines()

        run(6000, "rule")
        # frames that stage in a row, where 64 MB are kept
        check(run(6000, "row") == ["20: made 2 freed 0 kept 128 MB in 2 arenas, counted 2",
                                   "21: made 2 freed 0 kept 128 MB in 2 arenas, counted 2",
                                   "22: made 2 freed 1 kept 64 MB in 1 arenas, counted 2"],
              "20 frames staging in a row on a card allowed 6,000 MB: not 2 arenas made, or not 64 MB again 2 s later:\n"
              + "\n".join(run(6000, "row")))
        before = ["20: made 11 freed 9 kept 128 MB in 2 arenas, counted 11",
                  "21: made 11 freed 10 kept 64 MB in 1 arenas, counted 11",
                  "22: made 11 freed 10 kept 64 MB in 1 arenas, counted 11"]
        check(run(6000, "row", burst="0") == before, "RX_VK_STAGING_BURST_S=0 is not the loop as it was:\n" + "\n".join(run(6000, "row", burst="0")))
        check(run(6000, "row", pressed=True) == before, "with VRAM short the arenas are not given back as before:\n"
              + "\n".join(run(6000, "row", pressed=True)))
        check(run(6000, "row", burst="1")[1] == "21: made 2 freed 0 kept 128 MB in 2 arenas, counted 2", "RX_VK_STAGING_BURST_S=1 is no burst rule")
        # a frame that stages six arenas' worth, and an arena over 64 MB
        check(run(6000, "big") == ["1: made 6 freed 0 kept 384 MB in 6 arenas, counted 6",
                                   "2: made 6 freed 2 kept 256 MB in 4 arenas, counted 6",
                                   "3: made 7 freed 2 kept 356 MB in 5 arenas, counted 7",
                                   "4: made 7 freed 3 kept 256 MB in 4 arenas, counted 7",
                                   "5: made 7 freed 6 kept 64 MB in 1 arenas, counted 7"],
              "a burst's idle arenas are not held to 256 MB, or an arena over 64 MB stays:\n" + "\n".join(run(6000, "big")))
        check(run(6000, "big", burst="0")[1] == "2: made 6 freed 5 kept 64 MB in 1 arenas, counted 6", "=0 keeps more than 64 MB idle on a small card")
        # where nothing may change: 256 MB kept anyway, or VRAM short
        for card, pressed, why in ((31000, False, "a card allowed 31,000 MB"), (0, False, "a card that reports nothing"),
                                   (6657, False, "a card allowed just over 6.5 GB"), (6000, True, "a small card with VRAM short")):
            a, b = run(card, "mix", pressed=pressed), run(card, "mix", burst="0", pressed=pressed)
            check(len(a) == 300 and a == b, why + ": the rule changes what is made or given back there")
        check(run(6000, "mix") != run(6000, "mix", burst="0"), "the mixed frames do not exercise the rule on a small card")
        small, small0 = run(6000, "mix")[-1], run(6000, "mix", burst="0")[-1]
        made = lambda line: int(line.split("made ")[1].split()[0])
        check(made(small) < made(small0), "on a small card the rule does not make fewer arenas over the mixed frames: %s against %s" % (small, small0))
        print("a card allowed 6,000 MB, 300 mixed frames: %d arenas made with the rule, %d without" % (made(small), made(small0)))
    print("PASS: the idle staging arenas stay through a load's burst, and nothing changes where 256 MB are kept")


if __name__ == "__main__":
    main()
