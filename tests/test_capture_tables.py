"""The stored draws' tables keep their memory from frame to frame (gpu/vk/capture_tables.h, vk_temporal.cpp
capture_motion, temporal_capture_draw and take_captures; no game, no GPU).

(Triforce, 11-21, the upscaler audit's UPS-02.) While DLSS, FSR 4 or FSR 3.1 upscales, every plain draw into the scene
stores its positions and is drawn again into the motion vectors. The count of a model's draws and the frame before's draws
by key were std::unordered_map, emptied and filled every frame: a node from the heap for every stored draw, about 1,400 of
each a frame in the owner's log, on the thread that records the frame.

This compiles capture_tables.h alone and checks it: both ways (kept, and std::unordered_map with RX_VK_CAPTURE_TABLES=0)
answer the same over frames of draws with repeated keys, draws that come and go and a clear; the frame before's entries
are found until the next turn and no longer after it; and, with the heap's calls counted, a kept frame the size of the one
before takes nothing from the heap while the old way takes a node an entry.

And reads the source: the chain's two tables are capture_tables' with the switch read once, capture_motion turns the table
before it fills it and looks the frame before's up through it, the draws are counted through next(), take_captures gives
the next frame's list its room, and the switch is in the switches table.

    python -I -B tests/test_capture_tables.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


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


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <new>
#include "capture_tables.h"
static long news = 0;
void* operator new(std::size_t n) { news++; if (void* p = std::malloc(n ? n : 1)) return p; throw std::bad_alloc(); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace capture_tables;
struct Draw { uint64_t address; uint32_t first, count; };
static uint32_t rng = 12345;
static uint32_t next_random() { rng = rng * 1664525u + 1013904223u; return rng >> 8; }
int main() {
    CHECK(kept(nullptr) && kept("") && kept("1") && kept("2") && !kept("0"));
    CHECK(room(1444, true) == 1444 && room(1444, false) == 0 && room(0, true) == 0);
    {   // the n-th of a model, both ways the same; a clear starts every model at 0 again
        Nth a(true), b(false);
        for (int frame = 0; frame < 6; frame++) {
            for (int i = 0; i < 3000; i++) {
                const uint64_t model = (next_random() % 700) * 0x9E3779B97F4A7C15ull;
                const int x = a.next(model), y = b.next(model);
                CHECK(x == y);
            }
            CHECK(a.size() == b.size());
            a.clear(), b.clear();
            CHECK(a.size() == 0 && a.next(7) == 0 && b.next(7) == 0 && a.next(7) == 1);
            a.clear(), b.clear();
        }
    }
    {   // the frame before's entries, both ways the same: repeated keys (the last stands), draws that come and go
        Before<Draw> a(true), b(false);
        for (int frame = 0; frame < 8; frame++) {
            a.turn(), b.turn();
            const uint32_t n = 500 + next_random() % 1500;
            for (uint32_t i = 0; i < n; i++) {
                const uint64_t key = ((uint64_t)(next_random() % 2500) << 8) | (next_random() % 3);
                const Draw d{0x1000ull * frame + i, i, n};
                a.put(key, d), b.put(key, d);
            }
            CHECK(a.size() == b.size());
            for (uint32_t k = 0; k < 2500; k++)
                for (uint32_t nth = 0; nth < 3; nth++) {
                    const uint64_t key = ((uint64_t)k << 8) | nth;
                    const Draw* x = a.before(key);
                    const Draw* y = b.before(key);
                    CHECK(!x == !y);
                    if (x && y) CHECK(x->address == y->address && x->first == y->first && x->count == y->count);
                    if (frame == 0) CHECK(!x);   // (nothing before the first frame)
                }
        }
        // (a frame's entries are the frame before's only after the turn, and gone after the next one)
        Before<Draw> t(true);
        t.turn();
        t.put(5, {50, 1, 2});
        t.put(5, {51, 1, 2});   // (the last with a key stands)
        CHECK(t.size() == 1 && !t.before(5));
        t.turn();
        CHECK(t.before(5) && t.before(5)->address == 51 && !t.before(6));
        t.turn();
        CHECK(!t.before(5));
        t.put(9, {90, 0, 0});
        t.turn();
        t.clear();
        CHECK(!t.before(9) && t.size() == 0);
        a.clear(), b.clear();
        a.turn(), b.turn();
        CHECK(!a.before(0) && !b.before(0));
    }
    {   // the heap: a kept frame the size of the one before takes nothing from it; the old way a node an entry
        for (int keep = 1; keep >= 0; keep--) {
            Nth nth(keep != 0);
            Before<Draw> before(keep != 0);
            long steady = 0;
            for (int frame = 0; frame < 12; frame++) {
                const long from = news;
                before.turn();
                for (uint32_t i = 0; i < 1444; i++) {
                    const uint64_t model = (uint64_t)(i / 2) * 0x100000001B3ull;
                    const int n = nth.next(model);
                    before.put(model << 8 | (uint64_t)n, {i, i, 1});
                    if (frame) CHECK(before.before(model << 8 | (uint64_t)n) != nullptr);
                }
                nth.clear();
                if (frame >= 4) steady += news - from;
            }
            if (keep) CHECK(steady == 0);
            else CHECK(steady >= 8 * (1444 + 722));
        }
    }
    {   // an array far larger than what a frame puts in it is given back, so emptying it does not walk all of it
        FlatMap<uint64_t, int> m;
        for (uint64_t i = 0; i < 40000; i++) m[i * 977] = 1;
        const size_t large = m.capacity();
        empty_for_next(m);
        CHECK(m.size() == 0 && m.capacity() == large);   // (it held that many: kept for a frame as large)
        for (uint64_t i = 0; i < 100; i++) m[i] = 1;
        empty_for_next(m);                                // (100 entries in an array for 40,000: given back)
        CHECK(m.size() == 0 && m.capacity() < large);
        for (uint64_t i = 0; i < 1400; i++) m[i] = 1;
        const size_t fits = m.capacity();
        empty_for_next(m);
        CHECK(m.size() == 0 && m.capacity() == fits);
    }
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    src = (VK / "vk_temporal.cpp").read_text(encoding="utf-8")

    check('#include "capture_tables.h"' in src, "vk_temporal.cpp does not use the tables")
    check('const bool capture_tables_kept = capture_tables::kept(getenv("RX_VK_CAPTURE_TABLES"));' in src,
          "the switch is not RX_VK_CAPTURE_TABLES, read once with the chain's state")
    check("capture_tables::Nth captured_models{capture_tables_kept};" in src and
          "capture_tables::Before<Captured> captured_before{capture_tables_kept};" in src,
          "the chain's two tables are not capture_tables' with the switch")
    check("std::unordered_map<uint64_t, Captured> captured_before" not in src and
          "std::unordered_map<uint64_t, int> captured_models" not in src, "a table is still a std::unordered_map of the chain's own")
    motion = block(src, "int capture_motion(VkCommandBuffer cmd, const Camera& cam, const float* before, const float* reproject, uint32_t rw,")
    at = [motion.index(part) for part in (
        "s.captured_before.turn();",
        "const bool old_ok = history && s.captured_frame && s.captured_frame == to.last;",
        "if (c.k.depth == cam.depth) s.captured_before.put(c.key, c);",
        "if (caps.empty() || !make_capture_pipeline()) return 0;",
        "const State::Captured* const was = old_ok ? s.captured_before.before(c.key) : nullptr;",
        "const State::Captured& o = *was;")]
    check(at == sorted(at), "capture_motion does not turn the table, fill it with this frame's draws and then look up the frame before's")
    check("old.find(" not in motion and "std::unordered_map<uint64_t, State::Captured> old" not in motion,
          "capture_motion still moves the table into a map of its own")
    draw = block(src, "void temporal_capture_draw(const CaptureDraw& k, CaptureSlot* out) {")
    check("const int nth = s.captured_models.next(model >> 8);" in draw, "a stored draw is not counted through the kept table")
    take = block(src, "std::vector<State::Captured> take_captures() {")
    check(take.index("std::vector<State::Captured> c = std::move(s.captured);") <
          take.index("s.captured.reserve(capture_tables::room(c.size(), s.capture_tables_kept));"),
          "take_captures does not give the next frame's list its room")
    drop = block(src, "void drop_all() {")
    check("s.captured_models.clear(), s.captured_before.clear()" in drop, "the chain let go does not empty the tables")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_CAPTURE_TABLES=0`" in dev, "docs/development.md: RX_VK_CAPTURE_TABLES=0 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="capture-tables-") as tmp:
        c, exe = Path(tmp) / "tables.cpp", Path(tmp) / "tables.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the tables as made:\n" + r.stdout)
    print("PASS: the stored draws' tables keep their memory from frame to frame, and answer as std::unordered_map did")


if __name__ == "__main__":
    main()
