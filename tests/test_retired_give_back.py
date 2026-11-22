"""When a retired pool's import is given back (gpu/vk/retired_give_back.h, vk_memory.cpp retired_imports_give_back; no game,
no GPU).

(Triforce, 11-22, the performance audit's MEM-21, after Source A's.) A pool remade larger is retired; once the GPU is past
it, its import is pinned RAM nothing binds. Before: given back at once on Linux and with NVIDIA's driver on Windows, kept
with AMD's and Intel's on Windows, and never when the pool's mirror was refused. Now, OFF unless set:
RX_VK_KEEP_RETIRED=wait gives them back after a wait (RX_VK_RETIRE_SECS, 30; RX_VK_RETIRE_MIN_SECS, 2 while the system heap
is past 85%), and RX_VK_RETIRED_REFUSED=1 (on with wait unless 0) gives back the refused mirrors' imports too.

Compiles the header: the modes by OS, vendor and switch; on 200,000 random texts, vendors and OSes the mode keeps where the
old reading kept and gives back at once where it did, unless the text is "wait"; on 200,000 random pools, with the wait and
the refused rule off, want() is the old condition; with the wait, nothing goes back before it is due, nor while the pool
that took it in still copies from its mirror, nor before the GPU is past it; due() with and without pressure; settled();
a tour of 20 areas, three pools retired in each, where the wait keeps at most one area's and keep keeps them all.

And reads the source: retired_imports_give_back decides by want() with the old condition's parts and the push's shape,
the switch is read once through mode() with Windows and NVIDIA as before, retire_pool notes the time, the dead imports'
bytes are added at the push and taken off where reap_mirrors frees them, the pressure give-back reads settled() only with
the wait, the switches table has the row.

    python -I -B tests/test_retired_give_back.py [--cxx clang++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

PROGRAM = r"""
#include "retired_give_back.h"
#include <algorithm>
#include <cstdio>
#include <random>
#include <string>
#include <vector>
using namespace retired_give_back;
static int fails = 0;
#define CHECK(c) do { if (!(c)) { std::printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

int main() {
    // (the modes by OS, vendor and switch)
    CHECK(mode(nullptr, true, false) == Mode::Keep && mode(nullptr, true, true) == Mode::AtOnce);
    CHECK(mode(nullptr, false, false) == Mode::AtOnce && mode(nullptr, false, true) == Mode::AtOnce);
    for (int w = 0; w < 2; w++)
        for (int n = 0; n < 2; n++) {
            CHECK(mode("wait", w, n) == Mode::Wait);
            CHECK(mode("0", w, n) == Mode::AtOnce && mode("00", w, n) == Mode::AtOnce && mode("0x", w, n) == Mode::AtOnce);
            CHECK(mode("1", w, n) == Mode::Keep && mode("", w, n) == Mode::Keep && mode("keep", w, n) == Mode::Keep);
            CHECK(mode("Wait", w, n) == Mode::Keep && mode("wait ", w, n) == Mode::Keep && mode("waits", w, n) == Mode::Keep);
        }
    // (old reading against new on random texts: the same everywhere but "wait")
    std::mt19937_64 rng(2111);
    const char* words[] = {"wait", "0", "1", "", "keep", "w", "00", "wai", "waitt", "2", "-1", " 0", "0 "};
    const char alpha[] = "wait01 x";
    for (int i = 0; i < 200000; i++) {
        std::string s;
        const bool unset = rng() % 8 == 0;
        if (rng() % 2) s = words[rng() % (sizeof words / sizeof *words)];
        else for (int k = (int)(rng() % 6); k > 0; k--) s += alpha[rng() % (sizeof alpha - 1)];
        const char* e = unset ? nullptr : s.c_str();
        const bool w = rng() % 2, n = rng() % 2;
        const Mode m = mode(e, w, n);
        if (e && s == "wait") { CHECK(m == Mode::Wait); continue; }
        CHECK(m != Mode::Wait);
        CHECK((m == Mode::Keep) == keep_before(e, w, n));
        // (and the refused mirrors' rule off unless asked, outside the wait)
        CHECK(!refused_too(nullptr, m));
    }
    CHECK(refused_too(nullptr, Mode::Wait) && !refused_too("0", Mode::Wait) && refused_too("1", Mode::AtOnce) && !refused_too("0", Mode::Keep));
    // (the seconds)
    CHECK(secs(nullptr, 30) == 30 && secs("", 30) == 30 && secs("5", 30) == 5 && secs("0", 2) == 0);
    CHECK(secs("-3", 30) == 30 && secs("x", 30) == 30 && secs("4s", 30) == 30);
    // (the pressure: past 85% of a known budget)
    CHECK(!pressure(85, 100) && pressure(86, 100) && !pressure(1000, 0));
    CHECK(pressure((uint64_t)7 << 30, (uint64_t)8 << 30) && !pressure((uint64_t)6 << 30, (uint64_t)8 << 30));
    // (due: 30 s, or 2 s while the heap is short)
    CHECK(!due(29999, 0, 30, 2, false) && due(30000, 0, 30, 2, false));
    CHECK(!due(1999, 0, 30, 2, true) && due(2000, 0, 30, 2, true));
    CHECK(due(5000, 5000, 0, 0, false));
    // (settled: the dead imports out of the heap's use, never below 0)
    CHECK(settled(100, 30) == 70 && settled(30, 100) == 0 && settled(5, 5) == 0);
    // (want against the old condition on random pools, and the wait's guards)
    for (int i = 0; i < 200000; i++) {
        const Mode m = (Mode)(rng() % 3);
        const bool refused = rng() % 2, none = rng() % 2, ref = !none && rng() % 2, inherit = rng() % 2, past = rng() % 2,
                   is_due = rng() % 2;
        const bool w = want(m, refused, none, ref, inherit, past, is_due);
        if (m != Mode::Wait && !refused) CHECK(w == want_before(m == Mode::Keep, none, inherit, past));
        if (m == Mode::Keep) CHECK(!w);
        if (m == Mode::Wait && !is_due) CHECK(!w);
        if (inherit || !past) CHECK(!w);
        if (!none && !(refused && ref)) CHECK(!w);
        if (m == Mode::Wait && is_due && !inherit && past && (none || (refused && ref))) CHECK(w);
    }
    // (a tour: 20 areas a minute apart, three pools retired in each; checked a second at a time for two minutes past the last)
    for (int mi = 0; mi < 3; mi++) {
        const Mode m = (Mode)mi;
        struct P { int64_t at; bool alive; };
        std::vector<P> pools;
        size_t most = 0;
        for (int64_t t = 0; t <= 21 * 60000; t += 1000) {
            if (t % 60000 == 0 && t < 20 * 60000)
                for (int k = 0; k < 3; k++) pools.push_back({t, true});
            size_t alive = 0;
            for (P& p : pools) {
                if (!p.alive) continue;
                const bool d = due(t, p.at, 30, 2, false);
                if (want(m, refused_too(nullptr, m), true, false, false, true, d)) p.alive = false;
                else alive++;
            }
            most = std::max(most, alive);
        }
        size_t left = 0;
        for (const P& p : pools) left += p.alive;
        if (m == Mode::Keep) CHECK(left == 60 && most == 60);
        if (m == Mode::AtOnce) CHECK(left == 0 && most == 0);
        if (m == Mode::Wait) CHECK(left == 0 && most == 3);
    }
    std::printf(fails ? "%d failed\n" : "ok\n", fails);
    return fails ? 1 : 0;
}
"""


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(text, steps, what):
    at = -1
    for s in steps:
        k = text.find(s, at + 1)
        if k < 0:
            raise SystemExit("FAIL: %s: %r is missing or out of its order" % (what, s))
        at = k


def check_source():
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    if '#include "retired_give_back.h"' not in mem:
        raise SystemExit("FAIL: vk_memory.cpp does not include retired_give_back.h")
    pool = block(mem, "struct Pool {")
    if "int64_t retired_ms = 0;" not in pool:
        raise SystemExit("FAIL: Pool has no retired_ms")
    retire = block(mem, "void retire_pool(std::map<uint64_t, Pool>::iterator it) {")
    in_order(retire, ["old->retired_value = std::max(old->last_value, mem_rec_value);",
                      "old->retired_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()"],
             "vk_memory.cpp retire_pool")
    mode = block(mem, "retired_give_back::Mode retired_mode() {")
    in_order(mode, ["static const retired_give_back::Mode m = [] {", "#ifdef _WIN32", "const bool windows = true;", "#else",
                    "const bool windows = false;", "#endif",
                    'retired_give_back::mode(getenv("RX_VK_KEEP_RETIRED"), windows, dev.props.vendorID == 0x10DE);'],
             "vk_memory.cpp retired_mode")
    give = block(mem, "void retired_imports_give_back() {")
    if "static const bool keep" in give or 'getenv("RX_VK_KEEP_RETIRED")' in give:
        raise SystemExit("FAIL: retired_imports_give_back reads RX_VK_KEEP_RETIRED itself, not through retired_mode")
    in_order(give, ["const rg::Mode mode = retired_mode();", 'rg::refused_too(getenv("RX_VK_RETIRED_REFUSED"), mode);',
                    'rg::secs(getenv("RX_VK_RETIRE_SECS"), 30)', 'rg::secs(getenv("RX_VK_RETIRE_MIN_SECS"), 2)',
                    "if (!p.memory) {",   # (DESC-06's walk: a pool with no import left is passed, and the walk's start moves past it)
                    "const bool gpu_past = p.retired_value <= mem_completed && p.last_value <= mem_completed;",
                    "if (mode == rg::Mode::Wait && gpu_past && !p.inherit_pending &&",
                    "is_due = rg::due(now_ms, p.retired_ms, wait_s, min_s, false);",
                    "if (!is_due && rg::due(now_ms, p.retired_ms, wait_s, min_s, true)) {",
                    "heap_short = system_heap_usage(&used, &budget) && rg::pressure(rg::settled(used, dead_import_bytes), budget);",
                    "if (pressed_back || rg::want(mode, refused, p.mstate == Pool::MIRROR_NONE, p.mstate == Pool::MIRROR_REFUSED, p.inherit_pending, gpu_past, is_due)) {",
                    "dead_import_bytes += p.hi - p.lo;", "dead_imports.push_back({p.buffer, p.memory,", "continue;",
                    "retired_alive++, retired_bytes += p.hi - p.lo;"], "vk_memory.cpp retired_imports_give_back")
    if give.count("dead_imports.push_back(") != 1 or mem.count("dead_imports.push_back(") != 1 or \
            mem.count("dead_import_bytes += ") != 1:
        raise SystemExit("FAIL: a retired import goes into dead_imports somewhere its bytes are not counted")
    reap = block(mem, "void reap_mirrors() {")
    in_order(reap, ["while (!dead_imports.empty() && dead_imports.front().value <= mem_completed) {",
                    "vkFreeMemory(dev.device, dead_imports.front().memory, nullptr);",
                    "dead_import_bytes -= std::min(dead_import_bytes, dead_imports.front().bytes);", "dead_imports.pop_front();"],
             "vk_memory.cpp reap_mirrors")
    valve = block(mem, "void imports_give_back() {")
    in_order(valve, ["if (!system_heap_usage(&used, &budget)) return;",
                     "if (retired_mode() == retired_give_back::Mode::Wait) used = retired_give_back::settled(used, dead_import_bytes);",
                     "const bool by_heap = small && used > measure / 100 * (uint64_t)high;"],   # (MEM-22: against its cap)
             "vk_memory.cpp imports_give_back")
    if valve.count("settled(") != 1:
        raise SystemExit("FAIL: imports_give_back reads settled() somewhere else")
    dev_md = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if not any(line.startswith("| `RX_VK_KEEP_RETIRED=wait`, `RX_VK_RETIRED_REFUSED=1` |") and "**off unless set**" in line
               and "RX_VK_RETIRE_SECS" in line and "RX_VK_RETIRE_MIN_SECS" in line for line in dev_md.splitlines()):
        raise SystemExit("FAIL: docs/development.md has no row for RX_VK_KEEP_RETIRED=wait with its default")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="retired-give-back-") as tmp:
        src = Path(tmp) / "t.cpp"
        exe = Path(tmp) / "t.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
        print(r.stdout.strip())
        if r.returncode:
            raise SystemExit("FAIL: retired_give_back.h")
    print("ok: test_retired_give_back")


if __name__ == "__main__":
    main()
