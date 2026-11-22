"""A swap-aware memory pressure hold for Linux and the Steam Deck (gpu/vk/linux_pressure.h; no game, no GPU, no Linux).

(Triforce, 11-22, the performance audit's MEM-141, after Source A's.) The RAM rules looked at MemAvailable alone, which a
PC with swap keeps up by pushing the game's pages out. With RX_VK_SWAP_RESERVE_MB set the PC is also short when
MemAvailable and SwapFree together are under that reserve, and while it is short a hold gives memory back sooner:
capture spares, idle staging arenas, malloc_trim, idle imports (at most the episode's worst shortfall), an integrated
GPU's texture budget. Off unless the switch is set; never on Windows.

Compiles and runs tests/test_linux_pressure.cpp against the header:
  /proc/meminfo's text: the usual one, no swap (not known, never short by the sum), no MemAvailable (never short), swap
    nearly full (short while MemAvailable looks fine), SwapCached and MemFree not taken for the fields, the lab's played
    values;
  how short, the 256 MB to clear, the hold's entry and exit, the episode's limit for the imports and what was given,
    a new episode, a swapless PC, no reserve (never held), the budget's cut down at once and back 256 MB a sample;
  the valves' sizes held and not held.
Cuts the hold's own code (its state, swap_hold_step and the calls the valves make) out of gpu/vk/vk_memory.cpp and runs
it over a meminfo file of the test's and a log stand-in, each case a process of its own (the switch is read once):
  the reserve not set: /proc/meminfo is never opened, nothing is held;
  set: looked at every 30 presents only; the hold on at a short sample with its line, memory_swap_hold and
    memory_swap_cut following, the imports' limit counted down by memory_swap_gave, off at a clear sample with the
    line that says what each valve gave; RX_VK_TEST_SWAP_MB and RX_VK_TEST_AVAIL_MB played over the file.
And reads the source: memory_ram_watch steps the hold off Windows only; cap_buf_free, imports_give_back, the staging
arenas, malloc_trim and the integrated GPU's budget each ask the hold through the header's rule; the switches table.

    python -I -B tests/test_linux_pressure.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

FIXTURE = r'''#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include "linux_pressure.h"

static int checks, fails;
static std::string logged;
#define CHECK(x) do { checks++; if (!(x)) { fails++; printf("FAIL line %d: %s (logged: %s)\n", __LINE__, #x, logged.c_str()); } } while (0)
static void logf(const char* fmt, ...) {
    char line[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    logged += line, logged += "\n";
}
static const char* t_meminfo;   // (the file that plays /proc/meminfo)
static int t_opens;
static FILE* t_fopen(const char* path, const char* mode) {
    if (strcmp(path, "/proc/meminfo")) printf("FAIL: opened %s\n", path), exit(1);
    t_opens++;
    return fopen(t_meminfo, mode);
}
#define fopen t_fopen
@CUT@
#undef fopen
static void meminfo(long long avail_mb, long long swap_total_mb, long long swap_free_mb) {
    FILE* f = fopen(t_meminfo, "w");
    if (!f) printf("FAIL: cannot write %s\n", t_meminfo), exit(1);
    fprintf(f, "MemTotal:       16252084 kB\nMemFree:          100000 kB\nMemAvailable:   %lld kB\nSwapCached:        1000 kB\n"
               "SwapTotal:      %lld kB\nSwapFree:       %lld kB\n", avail_mb * 1024, swap_total_mb * 1024, swap_free_mb * 1024);
    fclose(f);
}
static bool said(const char* what) { return logged.find(what) != std::string::npos; }
static const uint64_t MB = 1ull << 20;

int main(int argc, char** argv) {
    if (argc < 3) return 2;
    const std::string mode = argv[1];
    t_meminfo = argv[2];
    if (mode == "off") {   // RX_VK_SWAP_RESERVE_MB not set (or 0): nothing is read, nothing is ever held
        meminfo(200, 8192, 0);
        for (uint64_t p = 0; p <= 600; p++) swap_hold_step(p);
        CHECK(t_opens == 0 && !memory_swap_hold() && memory_swap_cut() == 0 && memory_swap_episode_want() == 0 && logged.empty());
    } else if (mode == "on") {   // RX_VK_SWAP_RESERVE_MB=2560
        meminfo(8000, 8192, 6000);
        for (uint64_t p = 1; p < 30; p++) swap_hold_step(p);
        CHECK(t_opens == 0);   // (every 30 presents only)
        swap_hold_step(30);
        CHECK(t_opens == 1 && !memory_swap_hold() && logged.empty());
        meminfo(2000, 8192, 100);   // swap nearly full: 460 MB short of the reserve
        swap_hold_step(45);
        CHECK(t_opens == 1 && !memory_swap_hold());
        swap_hold_step(60);
        CHECK(t_opens == 2 && memory_swap_hold() && memory_swap_cut() == 460 * MB && memory_swap_episode_want() == 460 * MB);
        CHECK(said("vk: swap hold: on (2000 MB available, 100 MB of swap free: 460 MB short of 1536 MB available or 2560 MB with the swap)"));
        memory_swap_gave(200 * MB);     // (imports given back: counted against the episode's limit)
        memory_swap_valve(1, 128 * MB); // (staging arenas)
        memory_swap_valve(2, 64 * MB);  // (capture spares)
        memory_swap_valve(7, 1 * MB);   // (no such valve: nothing)
        CHECK(memory_swap_episode_want() == 260 * MB);
        meminfo(1800, 8192, 0);   // worse: 760 MB short
        swap_hold_step(90);
        CHECK(memory_swap_hold() && memory_swap_cut() == 760 * MB && memory_swap_episode_want() == 560 * MB);
        memory_swap_gave(600 * MB);
        CHECK(memory_swap_episode_want() == 0);
        meminfo(2000, 8192, 700);   // over the lines, not by 256 MB: still held
        swap_hold_step(120);
        CHECK(memory_swap_hold() && memory_swap_cut() == 504 * MB && !said("swap hold: off"));
        meminfo(4000, 8192, 4000);   // clear
        swap_hold_step(150);
        CHECK(!memory_swap_hold() && memory_swap_cut() == 248 * MB && memory_swap_episode_want() == 0);
        CHECK(said("vk: swap hold: off after ") && said("(4000 MB available, 4000 MB of swap free; 760 MB short at its worst); given back: "
                                                         "imports 800 MB, staging arenas 128 MB, capture spares not kept 64 MB"));
        swap_hold_step(180);
        CHECK(memory_swap_cut() == 0);
        // a swapless PC: only MemAvailable's own line
        logged.clear();
        meminfo(1400, 0, 0);
        swap_hold_step(210);
        CHECK(memory_swap_hold() && memory_swap_cut() == 136 * MB && said("(1400 MB available, swap not known: 136 MB short"));
        CHECK(memory_swap_episode_want() == 136 * MB);   // (a new episode: nothing given yet)
        meminfo(2000, 0, 0);
        swap_hold_step(240);
        CHECK(!memory_swap_hold() && said("imports 0 MB, staging arenas 0 MB, capture spares not kept 0 MB"));
    } else if (mode == "played") {   // RX_VK_SWAP_RESERVE_MB=2560 RX_VK_TEST_SWAP_MB=100 RX_VK_TEST_AVAIL_MB=2000
        meminfo(9000, 0, 0);   // (the file says plenty, and no swap: the played values are over it)
        swap_hold_step(30);
        CHECK(memory_swap_hold() && memory_swap_cut() == 460 * MB && said("(2000 MB available, 100 MB of swap free: 460 MB short"));
    } else return 2;
    if (fails) printf("linux pressure, the hold (%s): FAILED (%d of %d checks)\n", mode.c_str(), fails, checks);
    else printf("linux pressure, the hold (%s): all %d checks passed\n", mode.c_str(), checks);
    return fails != 0;
}
'''


def block(text, marker, what):
    start = text.find(marker)
    if start < 0:
        raise SystemExit("FAIL: %s has no '%s'" % (what, marker))
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(body, needles, what):
    order = [body.find(n) for n in needles]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("FAIL: %s (%r)" % (what, order))


def check_source():
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    api = (ROOT / "gpu/vk/vk_internal.h").read_text(encoding="utf-8")
    for name, text in (("vk_memory.cpp", mem), ("vk_texture.cpp", tex)):
        if '#include "linux_pressure.h"' not in text:
            raise SystemExit("FAIL: %s does not include linux_pressure.h" % name)
    for decl in ("bool memory_swap_hold();", "uint64_t memory_swap_cut();", "void memory_swap_valve(int valve, uint64_t bytes);",
                 "uint64_t memory_swap_episode_want();", "void memory_swap_gave(uint64_t bytes);"):
        if decl not in api:
            raise SystemExit("FAIL: vk_internal.h does not declare " + decl)
    # the hold's own code: from its state to the last of the calls the valves make
    first, last = "namespace {\nstd::mutex swap_hold_mu;\n", "void memory_swap_gave(uint64_t bytes) {"
    if mem.count(first) != 1 or mem.count(last) != 1:
        raise SystemExit("FAIL: vk_memory.cpp: the swap hold's code was not found")
    hold = mem[mem.index(first):mem.index(last)] + block(mem, last, "vk_memory.cpp")
    step = block(hold, "void swap_hold_step(uint64_t presents) {", "the hold")
    in_order(step, ['static const uint64_t reserve = linux_pressure::reserve_of(getenv("RX_VK_SWAP_RESERVE_MB"));',
                    "if (!reserve || presents % linux_pressure::kSampleEvery) return;",
                    'getenv("RX_VK_TEST_AVAIL_MB")', 'getenv("RX_VK_TEST_SWAP_MB")', 'fopen("/proc/meminfo", "r")',
                    "linux_pressure::sample_of(linux_pressure::parse(text), test_avail, test_swap);",
                    "std::lock_guard lk(swap_hold_mu);", "swap_hold.step(s, reserve);"],
             "swap_hold_step does not read its switch once, look every 30 presents, read SwapFree with MemAvailable from "
             "/proc/meminfo (the played values over it) and step the hold under its lock")
    watch = block(mem, "void memory_ram_watch(uint64_t presents) {", "vk_memory.cpp")
    in_order(watch, ["#ifndef _WIN32\n    swap_hold_step(presents);", "#endif\n    if (presents % 60) return;"],
             "memory_ram_watch does not step the hold off Windows only, before its own look every 60 presents")
    if mem.count("swap_hold_step(presents);") != 1:
        raise SystemExit("FAIL: the hold is stepped from more than one place (Windows keeps its own rules)")
    # the valves
    free = block(mem, "void cap_buf_free(VkBuffer buffer, VmaAllocation alloc, void* map, uint64_t size, bool from_worker = false) {",
                 "vk_memory.cpp")
    in_order(free, ["const bool swap_hold_on = memory_swap_hold();",
                    # ((Triforce, 11-22) merged over MEM-33: its rule takes the hold's cap and the smaller of that and 768 MB)
                    "linux_pressure::spare_cap(swap_hold_on, cap_spare_max()), keep_old)) {",
                    "if (swap_hold_on) memory_swap_valve(2, size);"],
             "cap_buf_free does not cap the capture spares by the hold")
    give = block(mem, "void imports_give_back() {", "vk_memory.cpp")
    in_order(give, ["const bool by_hold = ram_rule && !by_heap && memory_swap_hold();",
                    "if (!by_heap && !ram_short && !by_hold) return;",
                    ": by_hold ? memory_swap_episode_want() : (1ull << 30);", "if (by_hold && !want) return;",
                    "constexpr uint64_t kImportIdleRam = 3600;", "if (by_hold) memory_swap_gave(freed);"],
             "imports_give_back does not take the hold as a RAM trigger with the episode's limit, the idle rule kept")
    in_order(tex, ["const bool swap_hold_on = memory_swap_hold();", "const bool swap_hold_began = swap_hold_on && !swap_hold_was;",
                   "const int64_t idle_now = linux_pressure::arena_idle_s(swap_hold_on, idle_s);",
                   "const bool stale = idle_now && (swap_hold_began || std::chrono::steady_clock::now() - it->used_at > std::chrono::seconds(idle_now));",
                   "if (swap_hold_on) memory_swap_valve(1, it->size);",
                   "if (frame_no % linux_pressure::trim_every(swap_hold_on, 1800) == 0 && !busy.exchange(true))",
                   "const uint64_t trim_mb = linux_pressure::trim_mb(swap_hold_on, trim_set);",
                   "if (const uint64_t cut = memory_swap_cut(); cut && !vram_env && dev.props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU)",
                   "budget = linux_pressure::cut_budget(budget, cut);"],
             "vk_texture.cpp: the staging arenas, malloc_trim and the integrated GPU's budget do not ask the hold")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `RX_VK_SWAP_RESERVE_MB=<MB>`, `RX_VK_TEST_SWAP_MB=<n>` |" not in docs or "`gpu/vk/linux_pressure.h`" not in docs:
        raise SystemExit("FAIL: docs/development.md: the switches table has no RX_VK_SWAP_RESERVE_MB row")
    return hold


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    hold = check_source()
    with tempfile.TemporaryDirectory(prefix="linux-pressure-") as tmp:
        tmp = Path(tmp)
        flags = [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pthread", "-I" + str(ROOT / "gpu/vk")]
        exe = tmp / "linux-pressure.exe"
        subprocess.run(flags + [str(ROOT / "tests/test_linux_pressure.cpp"), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the pressure rule's checks failed")
        src, exe = tmp / "swap_hold_test.cpp", tmp / "swap-hold.exe"
        src.write_text(FIXTURE.replace("@CUT@", hold), encoding="utf-8")
        subprocess.run(flags + ["-Wno-unused-function", str(src), "-o", str(exe)], check=True)
        clean = {k: v for k, v in os.environ.items() if k not in ("RX_VK_SWAP_RESERVE_MB", "RX_VK_TEST_SWAP_MB", "RX_VK_TEST_AVAIL_MB")}
        for mode, env in (("off", {}), ("off", {"RX_VK_SWAP_RESERVE_MB": "0"}), ("on", {"RX_VK_SWAP_RESERVE_MB": "2560"}),
                          ("played", {"RX_VK_SWAP_RESERVE_MB": "2560", "RX_VK_TEST_SWAP_MB": "100", "RX_VK_TEST_AVAIL_MB": "2000"})):
            r = subprocess.run([str(exe), mode, str(tmp / "meminfo.txt")], capture_output=True, text=True, env=dict(clean, **env))
            print(r.stdout.rstrip())
            if r.returncode:
                raise SystemExit("FAIL: the hold's checks failed (%s, %r)" % (mode, env))


if __name__ == "__main__":
    main()
