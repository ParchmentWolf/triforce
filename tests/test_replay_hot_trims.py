"""Small per-draw and per-part costs cut on the replay thread, with the same results (vk_draw.cpp, vk_replay.cpp,
vk_dump.cpp, vk_memory.cpp; no game, no GPU).

(Triforce, 11-22, the performance audit's DESC-06, after Source A's.) Five places did work at every draw, uniform buffer,
dispatch or part of a submission that nothing needed there:
  1. a uniform buffer's offset tested against its alignment with a division: a mask (the alignment is a power of two);
  2. ub_overlay's allocator a std::function, made of a capturing lambda at every uniform buffer: a plain function and
     its alignment;
  3. dump_on() a call into vk_dump.cpp for one bool, at every draw: inline;
  4. dyn_same's 35 words and up to 160 bytes compared in loops: two memcmp (tests/test_same_dyn.py runs it);
  5. RX_VK_LOG_PUSH's program key formatted at every dispatch: only while the switch is set and its line not written;
  6. retired_imports_give_back summing every live pool and walking every retired pool at every part, for a line logged
     every 1200 epochs: summed when the line is due, and the walk begins past the retired pools with no import left.

Reads the source for 1 to 5. For 6, cuts retired_imports_give_back out of vk_memory.cpp and runs it beside the function
as it was (kept below) over the same authored session of 6000 parts, with the imports given back (NVIDIA's default,
RX_VK_KEEP_RETIRED=0) and kept (=1): the same imports given back at the same parts with the same values, the same
log lines, and the pools' state the same at the end; and the new one looks at far fewer retired pools.

Not done from the entry, and checked absent here so that nobody takes them for done: the read-back refresh's skip
without mirrors (its test, tests/test_parallel_rb_refresh.py, does not pass on v0.6.0 either) and the Linux-only lock
type of pools_mu (not compilable on Windows).

    python -I -B tests/test_replay_hot_trims.py [--cxx clang++]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

# retired_imports_give_back as it was before DESC-06 (v0.6.0), the oracle
BEFORE = r'''
void retired_imports_give_back() {   // (pools_mu held)
#ifdef _WIN32
    static const bool keep = getenv("RX_VK_KEEP_RETIRED") ? getenv("RX_VK_KEEP_RETIRED")[0] != '0' : dev.props.vendorID != 0x10DE;
#else
    static const bool keep = getenv("RX_VK_KEEP_RETIRED") && getenv("RX_VK_KEEP_RETIRED")[0] != '0';
#endif
    uint64_t live_bytes = 0, retired_bytes = 0;
    size_t retired_alive = 0;
    for (auto& [lo, p] : imported) live_bytes += p.hi - p.lo;
    for (auto& nh : retired_pools) {
        Pool& p = nh.mapped();
        if (!p.memory) continue;
        if (!keep && p.mstate == Pool::MIRROR_NONE && !p.inherit_pending && p.retired_value <= mem_completed &&
            p.last_value <= mem_completed) {
            dead_imports.push_back({p.buffer, p.memory, std::max(mem_rec_value, p.last_value), p.hi - p.lo, std::move(p.pieces), p.lo, p.hi});
            p.pieces.clear();
            p.buffer = VK_NULL_HANDLE, p.memory = VK_NULL_HANDLE, p.address = 0;
            pools_gen++;
            continue;
        }
        retired_alive++, retired_bytes += p.hi - p.lo;
    }
    static uint64_t logged_epoch;
    if (mirror_epoch - logged_epoch >= 1200) {
        logged_epoch = mirror_epoch;
        mirror_use_report();
        char touched[160] = "";
        if (const int64_t pages = st_touch_pages.load(std::memory_order_relaxed))
            snprintf(touched, sizeof touched, "; %lld MB of pages read before their imports in %.0f ms (RX_VK_IMPORT_TOUCH; %lld reads "
                     "stopped for a waiting lookup)", (long long)(pages >> 8), st_touch_ns.load(std::memory_order_relaxed) / 1e6,
                     (long long)st_touch_cut.load(std::memory_order_relaxed));
        logf("vk: imports: %zu live (%llu MB), %zu retired still imported (%llu MB), %llu retired given back (%llu MB)%s",
             imported.size(), (unsigned long long)(live_bytes >> 20), retired_alive, (unsigned long long)(retired_bytes >> 20),
             (unsigned long long)st_retired_imports_freed, (unsigned long long)(st_retired_import_bytes_freed >> 20), touched);
    }
}
'''

FIXTURE = r'''
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <string>
#include <vector>

#define VK_NULL_HANDLE 0
using VkBuffer = uint64_t;
using VkDeviceMemory = uint64_t;
struct { struct { uint32_t vendorID = 0x10DE; } props; } dev;
static uint64_t looked;   // (how many retired pools the walk asked for their memory)
struct Memory {           // (a pool's memory handle, counting each look at it)
    uint64_t h = 0;
    Memory& operator=(uint64_t v) { h = v; return *this; }
    explicit operator bool() const { looked++; return h != 0; }
    operator uint64_t() const { return h; }
    bool operator!() const { looked++; return h == 0; }
};
struct Pool {
    enum MState { MIRROR_NONE, MIRROR_ON, MIRROR_REFUSED };
    uint64_t lo = 0, hi = 0, address = 0, retired_value = 0, last_value = 0;
    int64_t retired_ms = 0;   // ((Triforce, 11-22) MEM-21's, merged into this walk)
    VkBuffer buffer = 0;
    Memory memory;
    MState mstate = MIRROR_NONE;
    bool inherit_pending = false;
    std::vector<VkDeviceMemory> pieces;
};
struct DeadImport { VkBuffer buffer; VkDeviceMemory memory; uint64_t value, bytes; std::vector<VkDeviceMemory> pieces; uint64_t lo, hi; };
std::map<uint64_t, Pool> imported;
std::deque<std::map<uint64_t, Pool>::node_type> retired_pools;
std::deque<DeadImport> dead_imports;
uint64_t mem_rec_value = 0, mem_completed = 0, mirror_epoch = 0, pools_gen = 0;
uint64_t st_retired_imports_freed = 0, st_retired_import_bytes_freed = 0;
std::atomic<int64_t> st_touch_pages{0}, st_touch_ns{0}, st_touch_cut{0};
// ((Triforce, 11-22) what MEM-21, merged into the walk, reads: its header, and RX_VK_KEEP_RETIRED read as the game reads
// it on Windows. Its wait (RX_VK_KEEP_RETIRED=wait) is MEM-21's own test's; here the three old readings must give the trace
// they gave before both changes)
uint64_t dead_import_bytes = 0;
bool system_heap_usage(uint64_t* used, uint64_t* budget) { *used = 0, *budget = 0; return false; }
/* RG_HEADER */
retired_give_back::Mode retired_mode() {
    return retired_give_back::mode(getenv("RX_VK_KEEP_RETIRED"), true, dev.props.vendorID == 0x10DE);
}
bool retired_keep_set() { return getenv("RX_VK_KEEP_RETIRED") != nullptr; }
static uint64_t trace = 1469598103934665603ull;   // (everything that happened, hashed in order)
static void note(const void* d, size_t n) {
    for (size_t i = 0; i < n; i++) trace = (trace ^ ((const uint8_t*)d)[i]) * 1099511628211ull;
}
static int lines, reports;
void mirror_use_report() { reports++, note("report", 6); }
void logf(const char* f, ...) {
    char b[1024];
    va_list ap;
    va_start(ap, f);
    vsnprintf(b, sizeof b, f, ap);
    va_end(ap);
    lines++, note(b, strlen(b));
    if (lines <= 2) printf("%s\n", b);
}
// (the system heap's rule for kept retired imports, (Triforce) 11-22: never pressed here, as with RX_VK_KEEP_RETIRED set,
// where it is not asked; NVIDIA's default gives them back without it)
std::atomic<int64_t> import_room_refused_ms{0};
int64_t import_now_ms() { return 0; }
namespace mem_parts {
[[maybe_unused]] constexpr int64_t kRefusedHoldMs = 60000;
bool retired_pressed(uint64_t, uint64_t, int, int64_t, int64_t) { return false; }
}
/* FUNCTION */

static uint64_t seed = 88172645463325252ull;
static uint32_t rnd(uint32_t n) {
    seed ^= seed << 13, seed ^= seed >> 7, seed ^= seed << 17;
    return (uint32_t)((seed >> 11) % n);
}
static uint64_t next_lo = 0x10000000;
static void retire() {
    Pool p;
    p.lo = next_lo, p.hi = next_lo + ((uint64_t)(1 + rnd(64)) << 20), next_lo = p.hi + (1u << 20);
    p.buffer = p.lo + 1, p.address = p.lo;
    if (rnd(10)) p.memory = p.lo + 2;                    // (one in ten retired with its import gone already)
    if (!rnd(6)) p.mstate = Pool::MIRROR_ON;             // (mirrored: its import stays)
    if (!rnd(5)) p.inherit_pending = true;               // (cleared later, below)
    p.retired_value = mem_rec_value, p.last_value = mem_rec_value + rnd(4);
    if (!rnd(3)) p.pieces = {p.lo + 3, p.lo + 4};
    std::map<uint64_t, Pool> one;
    one.emplace(p.lo, std::move(p));
    retired_pools.push_back(one.extract(one.begin()));
}

int main() {
    for (int i = 0; i < 40; i++) {   // (the live pools: their sizes are in the line)
        Pool p;
        p.lo = 0x1000000ull * (uint64_t)(i + 1), p.hi = p.lo + ((uint64_t)(1 + rnd(32)) << 20), p.memory = p.lo + 2;
        imported.emplace(p.lo, std::move(p));
    }
    size_t dead_seen = 0;
    for (int part = 0; part < 6000; part++) {
        mem_rec_value++;
        if (rnd(3)) mem_completed = mem_rec_value > 2 ? mem_rec_value - rnd(3) : 0;
        if (!rnd(4)) retire();
        if (!rnd(7)) {   // (the oldest inheritance ends, the oldest mirror goes: that pool can be given back from now)
            static size_t held;
            while (held < retired_pools.size() && !retired_pools[held].mapped().inherit_pending &&
                   retired_pools[held].mapped().mstate == Pool::MIRROR_NONE)
                held++;
            if (held < retired_pools.size()) retired_pools[held].mapped().inherit_pending = false, retired_pools[held].mapped().mstate = Pool::MIRROR_NONE;
        }
        if (part == 2000) st_touch_pages = 5 << 8, st_touch_ns = 3000000, st_touch_cut = 2;
        retired_imports_give_back();
        mirror_epoch++;
        for (; dead_seen < dead_imports.size(); dead_seen++) {
            const DeadImport& d = dead_imports[dead_seen];
            const uint64_t w[] = {(uint64_t)part, d.buffer, d.memory, d.value, d.bytes, d.lo, d.hi, d.pieces.size()};
            note(w, sizeof w);
            st_retired_imports_freed++, st_retired_import_bytes_freed += d.bytes;   // (as reap_mirrors counts them)
        }
    }
    for (auto& nh : retired_pools) {   // (and what is left of every retired pool)
        const Pool& p = nh.mapped();
        const uint64_t w[] = {p.lo, p.buffer, (uint64_t)p.memory, p.address, p.pieces.size(), (uint64_t)p.mstate, (uint64_t)p.inherit_pending};
        note(w, sizeof w);
    }
    printf("trace %016llx retired %zu dead %zu lines %d reports %d gen %llu\n", (unsigned long long)trace, retired_pools.size(),
           dead_imports.size(), lines, reports, (unsigned long long)pools_gen);
    printf("looked %llu\n", (unsigned long long)looked);
    return 0;
}
'''


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


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    uniform = block(draw, "VkDescriptorBufferInfo uniform_range(")
    # 1
    need("% align" not in uniform and "if (b && !(b.offset & (align - 1))) return {b.buffer, b.offset, n};" in uniform,
         "uniform_range still divides a buffer's offset by its alignment")
    need("const uint64_t align = std::max<uint64_t>(dev.props.limits.minUniformBufferOffsetAlignment, 16);" in uniform,
         "uniform_range's alignment is no longer the device's (a power of two): the mask needs that")
    # 2
    need("std::function" not in block(replay, "uint64_t ub_overlay(") and
         "uint64_t ub_overlay(uint64_t addr, uint64_t n, uint8_t* base, uint64_t (*alloc)(uint64_t, uint64_t), uint64_t align) {" in replay and
         "const uint64_t at = alloc(n, align);" in block(replay, "uint64_t ub_overlay("),
         "ub_overlay still takes a std::function, or does not hand its allocator the alignment")
    need("uint64_t ub_overlay(uint64_t addr, uint64_t n, uint8_t* base, uint64_t (*alloc)(uint64_t, uint64_t), uint64_t align);"
         in (ROOT / "gpu/vk/vk_draw.h").read_text(encoding="utf-8"), "vk_draw.h declares another ub_overlay")
    need("ub_overlay(u.addr, n, cur->mapped, stream_alloc, align); at != UINT64_MAX" in uniform and
         "uint64_t stream_alloc(uint64_t n, uint64_t align) {" in draw,
         "uniform_range does not hand ub_overlay stream_alloc and its alignment")
    need(not re.search(r"ub_overlay\([^;]*\[&\]", draw), "a caller of ub_overlay builds a capturing lambda for it")
    # 3
    dump_h = (ROOT / "gpu/vk/vk_dump.h").read_text(encoding="utf-8")
    dump = (ROOT / "gpu/vk/vk_dump.cpp").read_text(encoding="utf-8")
    need("extern bool dump_armed;" in dump_h and re.search(r"inline bool dump_on\(\) \{\s*return dump_armed;\s*\}", dump_h),
         "vk_dump.h's dump_on is not inline over dump_armed")
    need("bool dump_on()" not in dump and "\nbool dump_armed = false;\n" in dump and not re.search(r"(?<![A-Za-z0-9_`])armed(?![A-Za-z0-9_`])", dump),
         "vk_dump.cpp still has dump_on out of line, or a flag of its own beside dump_armed")
    need(dump.index("\nbool dump_armed = false;\n") < dump.index("\nnamespace {\n"), "dump_armed is inside vk_dump.cpp's own namespace")
    # 4
    same = block(draw, "bool dyn_same(")
    need(same.count("std::memcmp(") == 2 and same.count("for (") == 1 and "if (fp[i] != cfp[i]) return false;" in same,
         "dyn_same does not compare its floats by value and its words and bytes by two memcmp")
    # 5
    disp = block(draw, "void dispatch(VkCommandBuffer cmd, NvnState& s, uint32_t x, uint32_t y, uint32_t z, uint64_t indirect) {")
    at = disp.index('static const char* want = getenv("RX_VK_LOG_PUSH");')
    push = disp[at:disp.index("Program& p = const_cast<Program&>(*cp);", at)]
    # ((DESC-30) and in the lab's "diagold" phases, for what it cost)
    need("if ((want && !done) || dispatch_diag_old()) {" in push and push.index("if ((want && !done) || dispatch_diag_old()) {") < push.index("snprintf(") and
         "if (want && !done && !strncmp(hex, want, strlen(want))) {" in push and 'logf("%s", line);' in push,
         "dispatch formats RX_VK_LOG_PUSH's key before it knows the switch is set and its line not written")
    # what the entry also lists and this port left alone
    memory = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    need("using SrwMutex = std::mutex;" not in memory and "++unmirrored & 63" not in memory,
         "the lock type or the read-back skip changed: this test and its docstring say they did not")
    return memory


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    memory = check_source()
    now = block(memory, "void retired_imports_give_back() {")
    for line in ("const bool due = mirror_epoch - logged_epoch >= 1200;", "if (due)\n        for (auto& [lo, p] : imported) live_bytes += p.hi - p.lo;",
                 "static size_t gone = 0;", "if (gone > retired_pools.size()) gone = 0;", "if (give_back || due)",
                 "for (size_t i = gone; i < retired_pools.size(); i++) {", "if (i == gone) gone++;", "if (due) {"):
        need(line in now, "retired_imports_give_back lost: " + line)
    need("retired_pools.push_back(imported.extract(it));" in memory and
         not re.search(r"retired_pools\.(erase|pop_front|pop_back|clear|insert|resize|emplace_front|push_front)\(", memory),
         "the retired pools' list no longer only grows at its end: the walk's start past the given back ones needs that")
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="replay-hot-trims-") as tmp:
        exes = {}
        for name, fn in (("before", BEFORE), ("now", now)):
            cpp, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
            rg = (ROOT / "gpu" / "vk" / "retired_give_back.h").read_text(encoding="utf-8").replace("#pragma once", "")
            cpp.write_text(FIXTURE.replace("/* RG_HEADER */", rg).replace("/* FUNCTION */", fn), encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
            exes[name] = exe
        for keep in ("0", "1", None):
            out = {}
            for name, exe in exes.items():
                r = subprocess.run([str(exe)], capture_output=True, text=True, check=True, timeout=120,
                                   env=env if keep is None else {**env, "RX_VK_KEEP_RETIRED": keep})
                rows = r.stdout.strip().splitlines()
                out[name] = ("\n".join(rows[:-1]), int(rows[-1].split()[1]))
            what = "RX_VK_KEEP_RETIRED " + ("unset (NVIDIA: given back)" if keep is None else keep)
            need(out["before"][0] == out["now"][0], "%s: the retired imports are not given back, or the line not logged, as before:\n%s\n-- now:\n%s"
                 % (what, out["before"][0], out["now"][0]))
            need("vk: imports: 40 live" in out["now"][0], what + ": the imports line is gone")
            dead = int(re.search(r" dead (\d+) ", out["now"][0]).group(1))
            need((dead == 0) == (keep == "1") and (keep == "1" or dead > 1000), what + ": %d imports given back in the session" % dead)
            need(out["now"][1] * 4 < out["before"][1], "%s: the walk looks at %d retired pools where it looked at %d: not the cut"
                 % (what, out["now"][1], out["before"][1]))
            print("%s: same trace; %d looks at retired pools where there were %d" % (what, out["now"][1], out["before"][1]))
    print("PASS: the replay thread's small costs are cut and the results are the same")


if __name__ == "__main__":
    main()
