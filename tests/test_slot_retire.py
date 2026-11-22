"""A depth target another size replaced at its start is let go 16 presents after its last use (gpu/vk/slot_retire.h,
vk_texture.cpp texture_sweep; no game, no GPU).

(Triforce, 11-21, the performance audit's TEX-76, after Source B's.) The game draws each character's shadow map at a
fixed address, sized from the camera every frame; each size is a texture of its own, and the sizes before it, drawn
over, waited 120 presents unused before the sweep took them: a pile of dead maps at every slot.

This compiles slot_retire.h alone and checks the rule: a 768 map replaced by a 1024 one and unused 16 presents is
retired, at 15 it is not; nor one replaced by the same size, a colour target, another format's, one of two levels or
layers or a 3D one, one the GPU never drew, one whose newer target was written before its last use; a wait of 0 retires
nothing; the switch's values.

And reads the source: the sweep's two gates that hold a young texture back let a retired one through, and only those;
the rule is asked with the texture's own fields and the others at its start; a retired one is counted; the switch is in
the switches table.

    python -I -B tests/test_slot_retire.py [--cxx clang++]
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


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include "slot_retire.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace slot_retire;
int main() {
    CHECK(kWait == 16);
    CHECK(wait(nullptr) == 16 && wait("") == 16 && wait("16") == 16 && wait("4") == 4 && wait("120") == 120);
    CHECK(wait("0") == 0 && wait("-1") == 0 && wait("off") == 0);
    // a 768 map last used in present 1000, and the 1024 one drawn over its start in frame 1001
    const Target old{true, true, 1, 1, 1, 0x34, 768, 768, 1000, 1000};
    const Target newer{true, true, 1, 1, 1, 0x34, 1024, 1024, 1040, 1001};
    CHECK(retired_by(old, newer, 16, 16) && retired_by(old, newer, 40, 16));
    CHECK(!retired_by(old, newer, 15, 16) && !retired_by(old, newer, 0, 16));
    CHECK(!retired_by(old, newer, 1000, 0));                              // (the switch at 0: never)
    { Target n = newer; n.width = n.height = 768; CHECK(!retired_by(old, n, 16, 16)); }      // (the same size: drawn into again)
    { Target n = newer; n.height = 768; CHECK(retired_by(old, n, 16, 16)); }                 // (another width alone is another size)
    { Target n = newer; n.nvn_format = 0x32; CHECK(!retired_by(old, n, 16, 16)); }           // (another format at that start)
    { Target n = newer; n.last_written = 1000; CHECK(!retired_by(old, n, 16, 16)); }         // (not written after its last use)
    { Target n = newer; n.last_written = 999; CHECK(!retired_by(old, n, 16, 16)); }
    { Target o = old; o.depth = false; CHECK(!retired_by(o, newer, 16, 16)); }               // (a colour target)
    { Target o = old; o.gpu_written = false; CHECK(!retired_by(o, newer, 16, 16)); }         // (the GPU never drew it)
    { Target o = old; o.levels = 2; CHECK(!retired_by(o, newer, 16, 16)); }
    { Target o = old; o.layers = 2; CHECK(!retired_by(o, newer, 16, 16)); }
    { Target o = old; o.deep = 2; CHECK(!retired_by(o, newer, 16, 16)); }
    { Target o = old; o.deep = 0; CHECK(retired_by(o, newer, 16, 16)); }                     // (0 or 1: a plain 2D one)
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    start = tex.index("void texture_sweep(")
    start = tex.index("void texture_sweep(", start + 1) if tex.count("void texture_sweep(") > 1 else start
    sweep = tex[start:]
    check('#include "slot_retire.h"' in tex, "vk_texture.cpp does not use the rule")
    check('static const uint64_t retire_wait = slot_retire::wait(getenv("RX_VK_SLOT_RETIRE"));' in sweep, "the switch is not the rule's")
    check("slot_retire::Target{t->gpu_written, (t->aspect & VK_IMAGE_ASPECT_DEPTH_BIT) != 0, t->levels, t->layers, t->depth," in sweep and
          "t->nvn_format, t->width, t->height, t->last_frame, t->last_written};" in sweep,
          "the rule is not asked with the texture's own fields")
    asks = sweep[sweep.index("const auto slot_retired = [&](const Texture* tex) {"):]
    asks = asks[:asks.index("    };") + 6]
    at = [asks.index(p) for p in ("if (!retire_wait || !tex->gpu_written || frame_no - tex->last_frame < retire_wait) return false;",
                                  "auto [a, e] = by_gpu.equal_range(tex->gpu);",
                                  "slot_retire::retired_by(old, slot_target(o->second), frame_no - tex->last_frame, retire_wait)")]
    check(at == sorted(at), "a retire does not look at the other targets at the texture's start")
    check("if (age60(frame_no - last) < need_unused && !shifted && !slot_retired(tex)) continue;" in sweep,
          "the hold's first pass still holds a retired depth target back for the sweep's own wait")
    check("const bool retired = young && !shifted && !gone_early && slot_retired(tex);" in sweep and
          "if (young && !shifted && !gone_early && !retired) continue;" in sweep,
          "the sweep's gate still holds a retired depth target back, or lets other young textures through")
    gate = sweep.index("if (young && !shifted && !gone_early && !retired) continue;")
    check(gate < sweep.index("const bool overwritten = shifted || drawn_over(tex) || stale;") < sweep.index("        if (sweep && !overwritten && !gone_early) continue;\n"),
          "a retired target is no longer taken as drawn over: it would be written back, or kept by a sweep")
    check("st_slot_retired" in sweep and "let go %llu presents after their last use" in sweep, "the retired targets are not counted in the log")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_SLOT_RETIRE=<presents>`" in dev, "docs/development.md: RX_VK_SLOT_RETIRE is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="slot-retire-") as tmp:
        c, exe = Path(tmp) / "retire.cpp", Path(tmp) / "retire.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: a depth target another size replaced at its start is let go 16 presents after its last use")


if __name__ == "__main__":
    main()
