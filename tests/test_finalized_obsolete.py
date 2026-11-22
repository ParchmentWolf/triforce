"""A finalized texture the GPU drew goes once the game has rewritten its storage (gpu/vk/finalized_obsolete.h,
vk_texture.cpp texture_sweep; no game, no GPU).

(Triforce, 11-21, the performance audit's TEX-43, after Source A's.) A texture the GPU drew in one frame is kept after
the game finalizes it, for being made again over that storage. Within the budget only a draw over one let it go: the
game's own CPU writes to that memory kept each for good, about 200 render target images an hour in players' logs.

This compiles finalized_obsolete.h alone: which textures can be one (finalized, GPU-written, in no virtual pool, 32 KB
or more), three quarters of the storage as the line, the look again every 60 presents, the switch; and 30 laps of 60
tile-sized targets whose storage the game then reuses: 1,800 alive without the rule, 120 with it.

And reads the source: the sweep's look uses the texture's own fields and write generations since its release, keeps
its answer with the texture, and a release starts it afresh; keep_finalized refuses an obsolete one; it counts as dead
in the hold's walk and as overwritten in the pass, so it is never written back; what goes is counted; the switch is in
the switches table.

    python -I -B tests/test_finalized_obsolete.py [--cxx clang++]
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


def in_order(text, parts, why):
    at = 0
    for p in parts:
        at = text.find(p, at)
        check(at >= 0, why + " (missing, or out of order: " + p + ")")
        at += len(p)


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include <vector>
#include "finalized_obsolete.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace finalized_obsolete;
struct Tex { bool released, gpu_written; uint64_t gpu, guest_size, written; bool obsolete; uint64_t checked; };
// the sweep's look, as vk_texture.cpp makes it of the rule
static bool look(Tex& t, uint64_t frame, bool keep_all) {
    if (keep_all || !candidate(t.released, t.gpu_written, t.gpu, t.guest_size)) return false;
    if (!t.obsolete && due(frame, t.checked)) t.checked = frame, t.obsolete = rewritten(t.written, t.guest_size);
    return t.obsolete;
}
int main() {
    CHECK(!keep(nullptr) && !keep("") && !keep("0") && keep("1"));
    CHECK(candidate(true, true, 0x8000000000ull, 32u << 10) && candidate(true, true, 1, 135200));
    CHECK(!candidate(false, true, 1, 135200));              // (not finalized: the game still has it)
    CHECK(!candidate(true, false, 1, 135200));              // (uploaded from memory: its own rules)
    CHECK(!candidate(true, true, 1ull << 40, 135200));      // (a virtual pool: its pages are mapped, not written)
    CHECK(!candidate(true, true, 1, (32u << 10) - 1));      // (a small one shares its pages)
    CHECK(rewritten(3, 4) && rewritten(4, 4) && rewritten(101400, 135200) && !rewritten(101399, 135200) && !rewritten(0, 135200));
    CHECK(!rewritten(0, 0));
    CHECK(due(100, 0) && !due(100, 41) && due(100, 40) && due(1000, 1) && !due(5, 5));

    // 30 laps, each makes 60 tile-sized targets (260 x 260 RG8) the GPU draws and the game finalizes; a lap later the game
    // has put other data in the storage of all but the newest two laps'
    for (const bool keep_all : {true, false}) {
        std::vector<Tex> alive;
        uint64_t frame = 1;
        for (int lap = 0; lap < 30; lap++) {
            for (int i = 0; i < 60; i++) alive.push_back({true, true, 0x100000ull + alive.size() * 0x40000, 135200, 0, false, 0});
            for (size_t i = 0; i + 120 < alive.size() + 0 && i < alive.size(); i++) alive[i].written = 135200;   // (older than two laps: rewritten)
            frame += 600;
            std::vector<Tex> kept;
            for (Tex& t : alive)
                if (!look(t, frame, keep_all)) kept.push_back(t);
            alive.swap(kept);
        }
        if (keep_all) CHECK(alive.size() == 1800);
        else CHECK(alive.size() == 120);
    }
    {   // one not rewritten yet is not looked at again before 60 presents; once rewritten it stays so
        Tex t{true, true, 1, 135200, 0, false, 0};
        CHECK(!look(t, 100, false) && t.checked == 100);
        t.written = 135200;
        CHECK(!look(t, 159, false) && t.checked == 100);
        CHECK(look(t, 160, false) && t.checked == 160);
        t.written = 0;
        CHECK(look(t, 400, false) && t.checked == 160);
    }
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = tex.rindex("void texture_sweep(")
    sweep = tex[start:]
    check('#include "finalized_obsolete.h"' in tex, "vk_texture.cpp does not use the rule")
    in_order(sweep, ['static const bool keep_obsolete = finalized_obsolete::keep(getenv("RX_VK_KEEP_OBSOLETE"));',
                     "const auto obsolete = [&](const Texture* tex) {",
                     "if (keep_obsolete || !finalized_obsolete::candidate(tex->released, tex->gpu_written, tex->gpu, tex->guest_size)) return false;",
                     "if (!tex->obsolete && finalized_obsolete::due(frame_no, tex->obsolete_checked)) {",
                     "tex->obsolete_checked = frame_no;",
                     "memory_written_runs(tex->guest, tex->guest_size, tex->release_gen, written, true);",
                     "tex->obsolete = finalized_obsolete::rewritten(sum, tex->guest_size);", "return tex->obsolete;",
                     "const auto keep_finalized = [&](const Texture* tex) {",
                     "tex->bytes > (4ull << 20) || obsolete(tex))",
                     "if (shifted || drawn_over(tex) || obsolete(tex)) hold_dead += tex->bytes + tex->pad;",
                     "const bool stale = obsolete(tex);", "const bool overwritten = shifted || drawn_over(tex) || stale;",
                     "if (sweep && !overwritten && !gone_early) continue;",
                     "!no_flush && !overwritten && tex->gpu_written && !tex->released && flushable(*tex)",
                     "if (stale && !shifted && !drawn_over(tex)) {", "st_obsolete_n"],
             "texture_sweep does not look at a finalized texture's storage by the rule, keep its answer, refuse it among the kept, "
             "count it dead in the hold's walk and overwritten in the pass, or count what goes")
    check("it->second->obsolete = false, it->second->obsolete_checked = 0;" in tex and
          # ((Triforce, 11-22, the performance audit's MEM-85) the release's generation is texture_released_at's gen)
          tex.index("it->second->released = true, it->second->release_gen = gen;") <
          tex.index("it->second->obsolete = false, it->second->obsolete_checked = 0;"),
          "a release does not start the look afresh: a texture rewritten before it stays obsolete after it")
    head = (VK / "vk_texture.h").read_text(encoding="utf-8")
    check("mutable bool obsolete = false;" in head and "mutable uint64_t obsolete_checked = 0;" in head,
          "the texture does not keep the look's answer")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_KEEP_OBSOLETE=1`" in dev, "docs/development.md: RX_VK_KEEP_OBSOLETE is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="finalized-obsolete-") as tmp:
        c, exe = Path(tmp) / "obsolete.cpp", Path(tmp) / "obsolete.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: a finalized texture the GPU drew goes once the game has rewritten its storage")


if __name__ == "__main__":
    main()
