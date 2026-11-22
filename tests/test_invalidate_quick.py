"""An invalidate with nothing to wait for is not made, and its thread keeps its virtual core: RX_VK_INVALIDATE_QUICK=1
(gpu/vk/page_marks.h, vk_replay.cpp invalidate_quick, host/rx_backend.c rx_nvn_invalidate; no game, no GPU).

(Triforce, 11-22, the performance audit's THREAD-25, after Source A's.) Off unless set. The wait at stake is the one a
readback of GPU results needs: the thread that reads is the waiter, the write-back's registration is what it would wait
for, and "nothing to wait for" may only be said when no registration for the range was ever made.

- PageMarks compiled and run: single pages, ranges that end inside a page, the edges of a word, of a chunk and of 512 GB
  (past which nothing is kept and everything answers as marked), and 20,000 random marks and asks against a plain set
  of pages;
- the two tables beside their marks, cut out of the sources (vk_memory.cpp's WbPages, wb_pages_note,
  memory_writeback_value and memory_writeback_marked; vk_texture.cpp's vw_note, texture_gpu_written_in and
  texture_gpu_written_marked) over random notes: wherever a table says "ever" or "written in", the marks say marked,
  and a range no note touched is not marked;
- on threads: one thread notes write-backs while four ask. A note that has returned is seen by every ask that begins
  after it (nothing registered is missed), and whenever the table itself, asked under its lock, says "ever", the marks
  asked after it say marked (the mark is made first);
- the rule (inv_quick::nothing_to_wait_for) over every case, and the switch: off unless RX_VK_INVALIDATE_QUICK is a
  number other than 0, and off with a switch that makes invalidate() log or wait at every call;
- the sources: the mark is made before the table's entry and under its lock, wb_pages has one writer, a texture is
  listed in vw only by vw_note; invalidate_quick reads the ticket before the sections left and asks the three things
  the rule names; invalidate() still returns without waiting exactly where the rule says it does (its ticket wait first,
  then "ever written back", then "no texture written there, no texture storage there": a new wait added to it must be
  added to the rule, and this check says so); the host asks before it gives the core up, only a Vulkan back end, found
  by name; the switch is in the switches table.
tests/test_invalidate_vcore.py runs the host's wrapper with the question answered yes (no release, no take, no call) and no.

    python -I -B tests/test_invalidate_quick.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <thread>
#include <vector>
#include "page_marks.h"
static std::atomic<int> fails{0};
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
namespace mkwvk {
// ---- vk_memory.cpp's table of write-backs, as it is ----
constexpr uint64_t kPageShift = 12, kChunkPages = 65536, kPages = 2048 * kChunkPages;
static std::mutex wb_pages_mu;
/* WBPAGES */ wb_pages;
PageMarks wb_marks;
struct WbRun { uint64_t lo, hi, value; };
static std::vector<WbRun> wb_runs_recent;
static uint64_t wb_runs_lost = 0;
static uint64_t vk_timeline_completed() { return ~0ull; }
/* WBNOTE */
/* WBVALUE */
/* WBMARKED */
// ---- vk_texture.cpp's list of textures the GPU wrote, as it is ----
struct Texture { uint64_t gpu = 0, guest_size = 0; bool vw_listed = false; };
static bool flushable(const Texture& t) { return t.guest_size != 0; }
constexpr uint64_t kFlushMax = 16ull << 20;
static std::mutex vw_mu;
static std::map<uint64_t, uint64_t> vw;
PageMarks vw_marks;
/* VWNOTE */
/* VWIN */
/* VWMARKED */
} // namespace mkwvk
using namespace mkwvk;

static uint64_t rnd_state = 0x9E3779B97F4A7C15ull;
static uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}
static const uint64_t GB = 1ull << 30, SPAN = PageMarks::kSpan;

static void marks_alone() {
    static PageMarks m;
    CHECK(PageMarks::kSpan == (1ull << 39) && PageMarks::kPages == (1ull << 27) && PageMarks::kChunks * PageMarks::kChunkPages == PageMarks::kPages);
    CHECK(!m.any(0, SPAN) && !m.any(0x1000, 1) && !m.any(0, 0));
    m.mark(0x5000, 0x5001);                                            // one byte: its page
    CHECK(m.any(0x5000, 1) && m.any(0x5fff, 1) && m.any(0x4fff, 2) && m.any(0x5fff, 2) && m.any(0x4000, 0x3000));
    CHECK(!m.any(0x4000, 0x1000) && !m.any(0x6000, 0x1000) && !m.any(0x4fff, 1) && !m.any(0x6000, 1));
    CHECK(!m.any(0x5000, 0));                                          // (nothing to invalidate: nothing marked)
    m.mark(0x7000, 0x7000), m.mark(0x9000, 0x8000);                    // empty and backwards: nothing
    CHECK(!m.any(0x7000, 0x3000));
    m.mark(0x10000 - 1, 0x10000 + 1);                                  // two bytes across a page edge: both pages
    CHECK(m.any(0xf000, 1) && m.any(0x10000, 1) && !m.any(0xe000, 0x1000) && !m.any(0x11000, 0x1000));
    // the edge of a word (64 pages) and of a chunk (1 GB)
    const uint64_t w = 64 * 0x1000 * 5;
    m.mark(w - 0x1000, w + 0x1000);
    CHECK(m.any(w - 0x1000, 1) && m.any(w, 1) && !m.any(w - 0x2000, 0x1000) && !m.any(w + 0x1000, 0x1000));
    m.mark(3 * GB - 0x2000, 3 * GB + 0x2000);                          // across a chunk's edge
    CHECK(m.any(3 * GB - 1, 1) && m.any(3 * GB, 1) && m.any(3 * GB - 0x2000, 1) && m.any(3 * GB + 0x1fff, 1));
    CHECK(!m.any(3 * GB - 0x3000, 0x1000) && !m.any(3 * GB + 0x2000, 0x1000));
    CHECK(m.chunks[2].load() && m.chunks[3].load() && !m.chunks[1].load() && !m.chunks[4].load());   // (made where marked only)
    m.mark(7 * GB, 9 * GB);                                            // two whole chunks
    CHECK(m.any(7 * GB, 1) && m.any(9 * GB - 1, 1) && m.any(8 * GB + 12345, 77) && !m.any(9 * GB, 0x1000) && !m.any(7 * GB - 0x1000, 0x1000));
    CHECK(m.any(6 * GB, 2 * GB) && !m.any(5 * GB, GB) && m.any(0, SPAN));   // (asks that skip chunks never made)
    // 512 GB: nothing kept at or past it, and every ask there answers as marked
    CHECK(!m.any(SPAN - 0x1000, 0x1000));
    m.mark(SPAN - 0x800, SPAN + 0x100000);                             // (the part below is kept)
    CHECK(m.any(SPAN - 0x1000, 0x1000) && m.any(SPAN - 1, 1));
    m.mark(SPAN, SPAN + 0x1000), m.mark(SPAN * 4, SPAN * 4 + 1);       // (nothing kept, no fault)
    CHECK(m.any(SPAN, 1) && m.any(SPAN - 1, 2) && m.any(SPAN * 3, 0x1000) && m.any(~0ull, 1) && m.any(0x1000, ~0ull));
    CHECK(!m.any(SPAN - 0x3000, 0x2000));

    // random marks and asks against a set of pages (addresses in a few chunks, so pages meet)
    static PageMarks r;
    std::set<uint64_t> pages;
    auto where = [] { return (rnd() % 6) * 97 * GB / 16 + rnd() % (8ull << 20); };
    for (int i = 0; i < 20000; i++) {
        const uint64_t lo = where(), size = rnd() % 3 ? rnd() % 0x3000 + 1 : rnd() % 0x80000 + 1;
        if (i % 2) {
            r.mark(lo, lo + size);
            for (uint64_t p = lo >> 12; p <= (lo + size - 1) >> 12; p++) pages.insert(p);
        } else {
            const auto it = pages.lower_bound(lo >> 12);
            const bool want = it != pages.end() && *it <= (lo + size - 1) >> 12;
            if (r.any(lo, size) != want) { CHECK(!"a random ask disagrees with the pages marked"); break; }
        }
    }
}

static void tables() {
    // write-backs: the marks say marked wherever the table says ever, and not where no note reached
    std::set<uint64_t> noted;
    auto where = [] { return 4 * GB + (rnd() % 3) * 5 * GB + rnd() % (4ull << 20); };
    for (int i = 0; i < 6000; i++) {
        const uint64_t lo = where(), size = rnd() % 0x5000 + 1;
        if (i % 3 == 0) {
            wb_pages_note(lo, lo + size, 1 + rnd() % 1000);
            for (uint64_t p = lo >> 12; p <= (lo + size - 1) >> 12; p++) noted.insert(p);
        } else {
            bool ever = false;
            memory_writeback_value(lo, size, &ever);
            const auto it = noted.lower_bound(lo >> 12);
            const bool want = it != noted.end() && *it <= (lo + size - 1) >> 12;
            if (ever != want || memory_writeback_marked(lo, size) != want) { CHECK(!"the write-backs' table and its marks disagree"); break; }
        }
    }
    wb_pages_note(20 * GB, 20 * GB + 0x1000, 0);                    // (a note with no value is none: no mark either)
    CHECK(!memory_writeback_marked(20 * GB, 0x1000));
    bool ever = true;
    CHECK(memory_writeback_value(0, 64, &ever) == 0 && !ever && !memory_writeback_marked(0, 64));   // (an unmapped address: page 0)
    // GPU-written textures: marked wherever a listed one lies; a texture listed twice, and one that is not flushable
    static Texture t[400];
    std::set<uint64_t> listed;
    for (int i = 0; i < 400; i++) {
        t[i].gpu = 2 * GB + (rnd() % 2) * 9 * GB + (rnd() % (2ull << 20) & ~0xfull), t[i].guest_size = i % 9 == 0 ? 0 : rnd() % 0x9000 + 16;
        vw_note(t[i]), vw_note(t[i]);
        if (t[i].guest_size)
            for (uint64_t p = t[i].gpu >> 12; p <= (t[i].gpu + t[i].guest_size - 1) >> 12; p++) listed.insert(p);
        CHECK(t[i].vw_listed == (t[i].guest_size != 0));
    }
    for (int i = 0; i < 6000; i++) {
        const uint64_t lo = 2 * GB + (rnd() % 2) * 9 * GB + rnd() % (2ull << 20) - 0x2000, size = rnd() % 0x4000 + 1;
        const auto it = listed.lower_bound(lo >> 12);
        const bool pages = it != listed.end() && *it <= (lo + size - 1) >> 12;
        const bool in = texture_gpu_written_in(lo, size), marked = texture_gpu_written_marked(lo, size);
        if ((in && !marked) || marked != pages) { CHECK(!"the GPU-written textures' list and its marks disagree"); break; }
    }
    CHECK(!texture_gpu_written_marked(30 * GB, GB));
    Texture far;                                                    // (a virtual pool past 512 GB: not kept, so always "marked")
    far.gpu = SPAN + 5 * GB, far.guest_size = 0x4000;
    vw_note(far);
    CHECK(texture_gpu_written_in(far.gpu, 16) && texture_gpu_written_marked(far.gpu, 16));
}

// One thread notes write-backs; four ask. noted: how many notes have returned
static void threads() {
    const int N = 4000;
    const uint64_t base = 40 * GB;
    auto range = [&](int i) { return base + (uint64_t)i * 0x3000; };   // (a page each, a free page on both sides)
    std::atomic<int> noted{0};
    std::atomic<long> asks{0};
    std::thread writer([&] {
        for (int i = 0; i < N; i++) {
            wb_pages_note(range(i), range(i) + 0x1000, (uint64_t)i + 1);
            noted.store(i + 1, std::memory_order_seq_cst);
        }
    });
    std::vector<std::thread> readers;
    for (int r = 0; r < 4; r++)
        readers.emplace_back([&, r] {
            uint64_t s = 1234567 + (uint64_t)r * 7919;
            while (noted.load() < N && !fails.load()) {
                s = s * 6364136223846793005ull + 1442695040888963407ull;
                const int k = noted.load(std::memory_order_seq_cst);
                if (k) {                                               // a note that has returned is seen
                    const int j = (int)((s >> 33) % (uint64_t)k);
                    if (!memory_writeback_marked(range(j), 0x1000)) { CHECK(!"a write-back noted before the ask was not seen"); break; }
                }
                const int any = (int)((s >> 20) % (uint64_t)N);         // the table first, under its lock, then the marks
                bool ever = false;
                memory_writeback_value(range(any), 0x1000, &ever);
                if (ever && !memory_writeback_marked(range(any), 0x1000)) { CHECK(!"the table had a value its marks did not have"); break; }
                if (memory_writeback_marked(range(any) + 0x1000, 0x1000)) { CHECK(!"a page no note reached is marked"); break; }
                asks++;
            }
        });
    writer.join();
    for (auto& t : readers) t.join();
    for (int i = 0; i < N; i++)
        if (!memory_writeback_marked(range(i), 0x1000)) { CHECK(!"a note is missing at the end"); break; }
    std::printf("threads: %d notes beside %ld asks\n", N, asks.load());
}

static void rule() {
    using namespace inv_quick;
    Look l;
    l.gpu = 0x80000000, l.size = 64;
    CHECK(nothing_to_wait_for(l));                                   // (an occlusion slot nothing ever happened to)
    for (int which = 0; which < 4; which++) {                        // (each reason alone makes the call)
        Look x = l;
        (which == 0 ? x.ticket_pending : which == 1 ? x.tex_storage : which == 2 ? x.vw_marked : x.wb_marked) = true;
        CHECK(!nothing_to_wait_for(x));
    }
    Look z = l;
    z.size = 0, z.ticket_pending = z.tex_storage = z.vw_marked = z.wb_marked = true;
    CHECK(nothing_to_wait_for(z));                                   // (nothing to invalidate: invalidate() waits for nothing)
    z.gpu = SPAN * 2;
    CHECK(nothing_to_wait_for(z));
    Look far = l;
    far.gpu = SPAN;
    CHECK(!nothing_to_wait_for(far));                                // (past 512 GB: not known, the call is made)
    far.gpu = SPAN - 32;
    CHECK(!nothing_to_wait_for(far));                                // (a range that reaches past it)
    far.gpu = SPAN - 64;
    CHECK(nothing_to_wait_for(far));
    far.gpu = 0x1000, far.size = ~0ull;
    CHECK(!nothing_to_wait_for(far));
    // the switch: off unless asked for, and off with a switch that logs or waits at every call
    CHECK(!on(nullptr, nullptr, nullptr, nullptr) && !on("0", nullptr, nullptr, nullptr) && !on("", nullptr, nullptr, nullptr));
    CHECK(!on("off", nullptr, nullptr, nullptr));
    CHECK(on("1", nullptr, nullptr, nullptr) && on("2", nullptr, nullptr, nullptr));
    CHECK(!on("1", "1", nullptr, nullptr) && !on("1", nullptr, "300", nullptr) && !on("1", nullptr, nullptr, "1") && !on("1", "", nullptr, nullptr));
}

int main() {
    marks_alone();
    tables();
    threads();
    rule();
    if (!fails) std::printf("PASS: the marks, the tables beside them, a note seen by every later ask, and the rule\n");
    return fails ? 1 : 0;
}
'''


def ordered(text, needles, what):
    at = -1
    for needle in needles:
        try:
            nxt = text.index(needle, at + 1)
        except ValueError:
            fail("%s: %r is not there, or not after what comes before it" % (what, needle))
        at = nxt


def read_sources():
    memory = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    texture = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    note = block(memory, "void wb_pages_note(uint64_t guest_lo, uint64_t guest_hi, uint64_t value) {")
    ordered(note, ["std::lock_guard lk(wb_pages_mu);", "wb_marks.mark(guest_lo, guest_hi);", "wb_pages.set(p, value);"],
            "vk_memory.cpp wb_pages_note (the mark under the table's lock and before its value)")
    if memory.count("wb_pages.set(") != 1:
        fail("vk_memory.cpp: wb_pages has more than one writer: each must make its mark first")
    vw_note = block(texture, "void vw_note(Texture& t) {")
    ordered(vw_note, ["std::lock_guard lk(vw_mu);", "vw_marks.mark(t.gpu, t.gpu + t.guest_size);", "uint64_t& end = vw[t.gpu];", "t.vw_listed = true;"],
            "vk_texture.cpp vw_note (the mark under the list's lock and before its entry)")
    if texture.count("vw_listed = true") != 1:
        fail("vk_texture.cpp: a texture is listed in vw somewhere other than vw_note: that place must make the mark first")
    forget = block(texture, "void vw_forget(const Texture& t) {")
    if "if (it->second != &t && it->second->vw_listed) {" not in forget or texture.count("vw[t.gpu]") != 2:
        fail("vk_texture.cpp: vw gains an entry for a texture vw_note did not list (vw_forget puts back listed ones only)")
    quick = block(replay, "int invalidate_quick(uint64_t gpu, uint64_t size) {")
    ordered(quick, ['inv_quick::on(getenv("RX_VK_INVALIDATE_QUICK"), getenv("RX_VK_LOG_INVALIDATE"),', 'getenv("RX_VK_LOG_READBACK"), getenv("RX_VK_INVALIDATE_WAIT"));',
                    "if (!asked) return 0;", 'if (!lab_ab::on("noinvq")) {',
                    "const uint64_t ticket = fence_poll_fast_on() ? order_ticket.load(std::memory_order_seq_cst) : 0;",
                    "l.ticket_pending = sync_order_mu.left.load(std::memory_order_acquire) < ticket;",
                    "l.tex_storage = tex_pages_any(gpu, size);", "l.vw_marked = texture_gpu_written_marked(gpu, size);",
                    "l.wb_marked = memory_writeback_marked(host->gpu_guest(gpu), size);", "nothing = inv_quick::nothing_to_wait_for(l);",
                    "return nothing ? 1 : 0;"], "vk_replay.cpp invalidate_quick")
    for forbidden in ("std::lock_guard", "std::unique_lock", "wait_queue_empty", "wait_value", "wait_recorded", "sync_settle", "order_ticket_wait("):
        if forbidden in quick:
            fail("vk_replay.cpp invalidate_quick takes a lock or waits (%s): its caller holds a virtual core" % forbidden)
    # (invalidate() itself: the path the rule says is taken without a wait, in the order the rule assumes)
    inv = block(replay, "void invalidate(uint64_t gpu, uint64_t size) {")
    ordered(inv, ["if (size && fence_poll_fast_on()) order_ticket_wait();",
                  'static const bool log_inv = getenv("RX_VK_LOG_INVALIDATE") != nullptr;',
                  'getenv("RX_VK_LOG_READBACK") ? atoll(getenv("RX_VK_LOG_READBACK")) : -1;',
                  "if (!off && (v0 = memory_writeback_value(host->gpu_guest(gpu), size, &ever), ever)) {",   # (SYNC-19 keeps the value)
                  'static const bool always = getenv("RX_VK_INVALIDATE_WAIT") != nullptr;', "if (!size) return;",
                  "if (!texture_gpu_written_in(gpu, size)) {", "if (!replay_behind()) return;",
                  "if (!always && !tex_pages_any(gpu, size)) return;"],
            "vk_replay.cpp invalidate() no longer returns without waiting where invalidate_quick says it does: bring the rule up to it")
    head = inv[:inv.index("if (!off && (v0 = memory_writeback_value(")]
    for call in ("wait_queue_empty()", "sync_settle()", "wait_value(", "wait_recorded("):
        if call in head:
            fail("vk_replay.cpp invalidate() waits (%s) before it asks whether the range was ever written back: the rule does not know it" % call)
    ordered(replay, ["int mkwvk_invalidate_quick(uint64_t gpu, uint64_t size) {", "return mkwvk::invalidate_quick(gpu, size);"], "the export")
    wrapper = block(backend, "void rx_nvn_invalidate(uint64_t gpu, uint64_t size) {")
    ordered(wrapper, ["if (vk && invalidate_quick_fn && invalidate_quick_fn(gpu, size)) return;", "const int away = hos_vcore_away();",
                      "vk ? vk->nvn_invalidate(gpu, size) : wgr_nvn_invalidate(gpu, size);", "if (away) hos_vcore_back();"],
            "host/rx_backend.c rx_nvn_invalidate (the question before the core is given up)")
    if 'invalidate_quick_fn = (int (*)(uint64_t, uint64_t))(void *)GetProcAddress(vk_module, "mkwvk_invalidate_quick");' not in backend:
        fail("host/rx_backend.c: mkwvk_invalidate_quick is not looked up by name when the Vulkan back end starts")
    if "| `RX_VK_INVALIDATE_QUICK=1` |" not in dev:
        fail("docs/development.md: RX_VK_INVALIDATE_QUICK is not in the switches table")
    return memory, texture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    try:
        memory, texture = read_sources()
        source = FIXTURE
        for mark, text, marker in (("/* WBPAGES */", memory, "struct WbPages {"),
                                   ("/* WBNOTE */", memory, "void wb_pages_note(uint64_t guest_lo, uint64_t guest_hi, uint64_t value) {"),
                                   ("/* WBVALUE */", memory, "uint64_t memory_writeback_value(uint64_t guest, uint64_t size, bool* ever) {"),
                                   ("/* WBMARKED */", memory, "bool memory_writeback_marked(uint64_t guest, uint64_t size) {"),
                                   ("/* VWNOTE */", texture, "void vw_note(Texture& t) {"),
                                   ("/* VWIN */", texture, "bool texture_gpu_written_in(uint64_t lo, uint64_t size) {"),
                                   ("/* VWMARKED */", texture, "bool texture_gpu_written_marked(uint64_t lo, uint64_t size) {")):
            source = source.replace(mark, block(text, marker))
    except (ValueError, OSError) as e:
        fail("a text this test reads is not there (%s)" % e)
    with tempfile.TemporaryDirectory(prefix="invalidate-quick-") as tmp:
        src, exe = Path(tmp) / "quick.cpp", Path(tmp) / "quick.exe"
        src.write_text(source, encoding="utf-8")
        built = subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                                "-pthread", "-I" + str(VK), str(src), "-o", str(exe)], capture_output=True, text=True)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        print(done.stdout.strip())
        if done.returncode or "PASS" not in done.stdout:
            fail("the marks, the tables or the rule")
    print("PASS: an invalidate is left out only where nothing was ever registered for its range, and the question is off unless asked for")


if __name__ == "__main__":
    main()
