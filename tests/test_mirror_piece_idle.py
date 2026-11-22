"""What the mirrors' pieces hold that no game pool covers, and how much of it no binding reached for a while: counted,
nothing released (gpu/vk/piece_idle.h, vk_memory.cpp piece_idle_for, pieces_touch and the 1200-submission line; no game,
no GPU).

(Triforce, 11-22, the performance audit's MEM-26, its FIRST STEP only, after Source A's.) A mirror in pieces keeps a
piece's memory until the whole mirror goes, also where no game pool is left. The entry's first step is to count what a
release would find before porting it; the release itself (the unbind, the free after two timelines) is not ported.

This compiles piece_idle.h and compares it with a model that asks every raw pool about every piece, on 3,000 random
mirrors: pools in any order, overlapping, nested, empty, touching a piece by one byte or ending exactly at its edge;
pieces of 64 KB to 1 MB; a mirror whose size is not a multiple of its piece; random residency and last bindings; the
idle wait 0 (not tracked) or set. held, uncovered and idle must each be the model's. merge() must give disjoint ascending
ranges that cover exactly the bytes the raw pools cover.

Then it cuts piece_idle_for and pieces_touch out of vk_memory.cpp and runs them over a stand-in pool: with
RX_VK_MIRROR_PIECE_IDLE unset or 0 a binding writes nothing; set, it writes this submission into the pieces of its range
and no other, a whole mirror or a pool with no table is left alone, and a range past the table's end stops at it.

And reads the source: both places gpu_buffer_bind returns a mirror in pieces touch them, the table is sized once where
res_bits is, the count follows the "mirrors in pieces" line under its own every-1200 test, nothing in the change frees or
unbinds, and the switches table says the release is not ported.

    python -I -B tests/test_mirror_piece_idle.py [--cxx clang++]
"""
import argparse
import os
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
    check(text.count(marker) == 1, "vk_memory.cpp does not have once: " + marker)
    start = text.index(marker)
    end = text.index("{", start + len(marker) - 1) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <string>
#include "piece_idle.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { if (fails++ < 10) std::printf("FAIL:%d %s\n", __LINE__, #x); } } while (0)
static uint64_t rnd_state = 0xBB67AE8584CAA73Bull;
static uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}
// ---- stand-ins for the cut code ----
static void logf(const char*, ...) {}
struct Pool {
    bool mpieces = true;
    uint32_t piece_shift = 18;
    std::vector<uint32_t> piece_last;
};
uint64_t mirror_epoch = 0;
@@CUT@@

int main(int argc, char** argv) {
    const uint64_t want_idle = argc > 1 ? (uint64_t)std::atoll(argv[1]) : 0;
    // ---- the count against a model that asks every pool about every piece ----
    for (int t = 0; t < 3000; t++) {
        const uint32_t shift = 16 + (uint32_t)(rnd() % 5);
        const uint64_t piece = 1ull << shift, lo = (0x1000ull + rnd() % 64) << 20;
        const uint64_t size = (2 + rnd() % 40) * piece - (rnd() % 3 == 0 ? rnd() % piece : 0);
        const uint64_t n = (size + piece - 1) >> shift, now = 5000 + rnd() % 100000, idle_for = t % 3 == 0 ? 0 : 1 + rnd() % 1200;
        std::vector<uint8_t> res(n);
        std::vector<uint64_t> last(n);
        for (uint64_t i = 0; i < n; i++) res[i] = rnd() % 3 != 0, last[i] = now - rnd() % 2400;
        piece_idle::Ranges raw;
        for (int k = (int)(rnd() % 12); k > 0; k--) {
            uint64_t a = lo - 4 * piece + rnd() % (size + 8 * piece), len = rnd() % 5 == 0 ? rnd() % (6 * piece) : rnd() % (piece / 2 + 1);
            if (rnd() % 4 == 0) a = lo + (rnd() % (n + 1)) * piece;                  // (begins at a piece's edge)
            if (rnd() % 4 == 0 && a > lo) len = ((a - lo) / piece + 1) * piece + lo - a;   // (ends at one)
            if (rnd() % 9 == 0) len = 0;                                             // (an empty one)
            raw.push_back({a, a + len});
        }
        piece_idle::Count want;
        for (uint64_t i = 0; i < n; i++) {
            if (!res[i]) continue;
            const uint64_t a = lo + i * piece, b = lo + std::min(size, (i + 1) * piece);
            want.held += b - a;
            bool touched = false;
            for (const auto& r : raw) touched = touched || (r.first < r.second && r.first < b && a < r.second);
            if (touched) continue;
            want.uncovered += b - a;
            if (idle_for && now - last[i] >= idle_for) want.idle += b - a;
        }
        piece_idle::Ranges merged = raw;
        piece_idle::merge(merged);
        uint64_t covered = 0;
        for (size_t k = 0; k < merged.size(); k++) {
            CHECK(merged[k].first < merged[k].second && (!k || merged[k - 1].second < merged[k].first));
            covered += merged[k].second - merged[k].first;
        }
        if (t % 50 == 0) {   // (the merged ranges cover the raw pools' bytes, counted 4 KB at a time: the pools here are not page aligned, so by sample)
            for (int s = 0; s < 400; s++) {
                const uint64_t x = lo - 4 * piece + rnd() % (size + 8 * piece);
                bool in_raw = false, in_merged = false;
                for (const auto& r : raw) in_raw = in_raw || (x >= r.first && x < r.second);
                for (const auto& r : merged) in_merged = in_merged || (x >= r.first && x < r.second);
                CHECK(in_raw == in_merged);
            }
        }
        piece_idle::Count got;
        piece_idle::count(lo, size, shift, [&](uint64_t i) { return res[i] != 0; }, [&](uint64_t i) { return last[i]; }, merged, now, idle_for, got);
        CHECK(got.held == want.held && got.uncovered == want.uncovered && got.idle == want.idle);
        CHECK(got.idle <= got.uncovered && got.uncovered <= got.held && (idle_for || !got.idle));
        (void)covered;
    }
    // ---- the cut code: a binding's note in its pieces ----
    CHECK(piece_idle_for() == want_idle);
    Pool p;
    p.piece_last.assign(64, 7);
    mirror_epoch = 0x100000123ull;   // (past 32 bits: the low ones are kept)
    pieces_touch(&p, 3 * (1ull << 18) + 5, 2 * (1ull << 18));   // (pieces 3, 4 and 5)
    for (size_t i = 0; i < 64; i++) CHECK(p.piece_last[i] == (want_idle && i >= 3 && i <= 5 ? 0x123u : 7u));
    pieces_touch(&p, 62 * (1ull << 18), 40 * (1ull << 18));     // (past the table's end: pieces 62 and 63 only)
    CHECK(p.piece_last[62] == (want_idle ? 0x123u : 7u) && p.piece_last[63] == (want_idle ? 0x123u : 7u) && p.piece_last[61] == 7u);
    pieces_touch(&p, 10 * (1ull << 18), 0);                     // (nothing bound)
    CHECK(p.piece_last[10] == 7u);
    Pool whole;
    whole.mpieces = false, whole.piece_last.assign(8, 7);
    pieces_touch(&whole, 0, 1 << 20);                           // (a whole mirror: no pieces)
    CHECK(whole.piece_last[0] == 7u);
    Pool untracked;
    pieces_touch(&untracked, 0, 1 << 20);                       // (no table: made before the switch could matter)
    CHECK(untracked.piece_last.empty());
    if (fails) std::printf("piece idle: FAILED (%d checks)\n", fails);
    else std::printf("piece idle (RX_VK_MIRROR_PIECE_IDLE %s): 3,000 mirrors counted as the model counts them; a binding %s\n",
                     want_idle ? "set" : "unset", want_idle ? "notes its pieces and no other" : "notes nothing");
    return fails != 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check((VK / "piece_idle.h").exists(), "gpu/vk/piece_idle.h is missing")
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    check('#include "piece_idle.h"' in mem, "vk_memory.cpp does not include piece_idle.h")
    idle_for = block(mem, "uint64_t piece_idle_for() {")
    check('getenv("RX_VK_MIRROR_PIECE_IDLE")' in idle_for and "static const uint64_t v" in idle_for and "e && atoi(e) > 0 ? (uint64_t)atoi(e) : 0" in idle_for,
          "RX_VK_MIRROR_PIECE_IDLE is not read once, off unless a number above 0")
    touch = block(mem, "inline void pieces_touch(Pool* p, uint64_t off, uint64_t size) {")
    check("if (!piece_idle_for() || !p->mpieces || !size || p->piece_last.empty()) return;" in touch, "pieces_touch does something without the switch")
    bind = block(mem, "BufferRef gpu_buffer_bind(uint64_t gpu, uint64_t size, bool written) {")
    check(bind.count("pieces_touch(p, off, size);") == 2 and mem.count("pieces_touch(") == 3, "pieces_touch is not called at gpu_buffer_bind's two returns of a mirror")
    check("if (pieces_resident(p, off, size)) {\n                pieces_touch(p, off, size);" in bind and
          bind.rstrip().endswith("return remember({p->mirror, off, size, 0});\n}") and
          "pieces_touch(p, off, size);" in bind[bind.rindex("for (uint64_t q = a; q <= b; q++)"):],
          "gpu_buffer_bind: a binding given a mirror does not note its pieces before it returns")
    check("if (piece_idle_for() && p->piece_last.size() != words * 64) p->piece_last.assign(words * 64, (uint32_t)mirror_epoch);" in mem and
          mem.index("if (p->res_bits.size() != words) p->res_bits.assign(words, 0);") < mem.index("p->piece_last.assign(words * 64"),
          "the pieces' table is not sized once, where res_bits is")
    begin = block(mem, "void memory_begin_submission() {")
    order = [begin.find(s) for s in ("if (mirror_pieces_on() && mirror_epoch - at >= 1200) {", "vk: mirrors in pieces: %zu mirrors hold",
                                    "for (const GuestPool& g : guest_pools) game.push_back({g.lo, g.hi});", "piece_idle::merge(game);",
                                    "piece_idle::count(p.lo, p.hi - p.lo, p.piece_shift,", "are pieces no game pool covers now")]
    check(min(order) >= 0 and order == sorted(order), "the count is not made after the mirrors-in-pieces line, every 1200 submissions")
    # (the first step only: the change frees and unbinds nothing)
    header = (VK / "piece_idle.h").read_text(encoding="utf-8")
    for word in ("vma_piece_free", "vmaFreeMemory", "piece_binds", "res_bits[", "__atomic_fetch_and"):
        check(word not in touch and word not in header, "the count's code touches the pieces' memory or bits (%s)" % word)
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_MIRROR_PIECE_IDLE=<submissions>`" in dev and "NOT ported" in dev, "docs/development.md: the switch's row does not say the release is not ported")

    base_env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="piece-idle-") as tmp:
        src, exe = Path(tmp) / "idle.cpp", Path(tmp) / "idle.exe"
        src.write_text(PROGRAM.replace("@@CUT@@", idle_for + "\n" + touch), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        for value in (None, "0", "600"):
            env = dict(base_env) if value is None else dict(base_env, RX_VK_MIRROR_PIECE_IDLE=value)
            r = subprocess.run([str(exe), value or "0"], env=env, capture_output=True, text=True, timeout=120)
            print(r.stdout.rstrip())
            check(r.returncode == 0, "RX_VK_MIRROR_PIECE_IDLE %s: the checks failed" % value)
    print("PASS: the pieces no game pool covers are counted as a page-by-page model counts them; nothing is released")


if __name__ == "__main__":
    main()
