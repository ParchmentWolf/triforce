"""The BC3 scratch has the layers one run uses, not 8 (gpu/vk/bc_scratch.h, vk_texture.cpp bc_layers, bc_scratch_layers,
bc_scratch_make, bc_scratch2_make, bc_scratch_layout, texture_copy_into_bc; no game, no GPU).

(Triforce, 11-21, the performance audit's TEX-10, after Source A's.) Big ASTC textures are decoded into a 2048 x 2048
RGBA8 scratch and encoded again as BC3 into an output buffer. Both were made with 8 layers, 160 MB, while a run decodes
one layer: 140 MB held and never written, for good once made.

This compiles bc_scratch.h alone and checks the rule: a run is 1 layer unless RX_VK_BC_LAYERS says 1 to 8; the scratch
has a run's layers, or 8 with RX_VK_BC_SCRATCH_FULL; one layer is 16 MB of image and 4 MB of output, 20 MB, 36 with the
second scratch, and 8 layers are the 160 and 288 MB it was.

And reads the source: both scratch images, their views, the layout's barriers and the output buffer are sized by
bc_scratch_layers(), nowhere by kBcLayers; a run's layers are bc_layers(), which the scratch is sized from; the copy into
a BC3 texture takes no more layers at once than the scratch has; the made line says the size; the switches are in the
switches table.

    python -I -B tests/test_bc_scratch_layers.py [--cxx clang++]
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
#include <initializer_list>
#include "bc_scratch.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main() {
    using namespace bc_scratch;
    CHECK(kDim == 2048 && kMost == 8);
    CHECK(run_layers(nullptr) == 1 && run_layers("") == 1 && run_layers("x") == 1 && run_layers("0") == 1 && run_layers("-3") == 1);
    CHECK(run_layers("1") == 1 && run_layers("4") == 4 && run_layers("8") == 8 && run_layers("99") == 8);
    for (uint32_t run : {1u, 2u, 8u}) CHECK(layers(run, false) == run && layers(run, true) == 8);
    CHECK(layers(0, false) == 1 && layers(64, false) == 8);
    CHECK(out_bytes(1) == 4ull << 20 && out_bytes(8) == 32ull << 20);
    CHECK(mb(1, false) == 20 && mb(1, true) == 36);      // (16 MB of image, 4 MB of output; the second image 16 more)
    CHECK(mb(8, false) == 160 && mb(8, true) == 288);    // (what it was)
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")

    check('#include "bc_scratch.h"' in tex, "vk_texture.cpp does not use the rule")
    run = block(tex, "uint32_t bc_layers() {")
    check('bc_scratch::run_layers(getenv("RX_VK_BC_LAYERS"))' in run, "a run's layers are not the rule's of RX_VK_BC_LAYERS")
    size = block(tex, "uint32_t bc_scratch_layers() {")
    check('bc_scratch::layers(bc_layers(), getenv("RX_VK_BC_SCRATCH_FULL") != nullptr)' in size,
          "the scratch's layers are not a run's, with all 8 behind RX_VK_BC_SCRATCH_FULL")
    for name in ("bool bc_scratch_make() {", "bool bc_scratch2_make() {"):
        body = block(tex, name)
        check("kBcLayers" not in body and "ii.arrayLayers = bc_scratch_layers();" in body and
              "vi.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, bc_scratch_layers()};" in body,
              name.split("(")[0] + ": the image or its view is not sized by bc_scratch_layers()")
    make = block(tex, "bool bc_scratch_make() {")
    # ((11-21, TEX-09) the one buffer holds a run of either scratch: the first's, or the small one's when it is larger)
    check("const uint64_t out = std::max(bc_scratch::out_bytes(bc_scratch_layers()), small_out);" in make,
          "the output buffer is not the rule's size")
    check('logf("vk: the BC3 scratch is made: %u layer' in make, "the made scratch's size is not logged")
    layout = block(tex, "bool bc_scratch_layout(")
    check("kBcLayers" not in layout and layout.count("0, 1, 0, bc_scratch_layers()};") == 2,
          "bc_scratch_layout's barriers cover layers the scratch may not have")
    copy = block(tex, "bool texture_copy_into_bc(")
    check("kBcLayers" not in copy and "l0 += bc_scratch_layers()" in copy and "std::min(bc_scratch_layers(), layers - l0)" in copy,
          "a copy into a BC3 texture takes more layers at once than the scratch has")
    # ((11-21, TEX-09) a level the small scratch holds runs its layers; any other, bc_layers(), what the first is sized by)
    check("const uint32_t run = small ? bc_small_layers() : bc_layers();" in tex,
          "the upload's run through the first scratch is not bc_layers(), what that scratch is sized by")
    idle = block(tex, "void bc_scratch_idle() {")
    check("bc_scratch::mb(bc_scratch_layers(), second)" in idle, "the given-back line still states 160 or 288 MB")
    stub = (ROOT / "tests" / "parallel_init_order_test.cpp").read_text(encoding="utf-8")
    check("uint32_t bc_scratch_layers() { return kBcLayers; }" in stub, "parallel_init_order_test.cpp cannot compile bc_scratch_layout")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_BC_LAYERS=<n>`, `RX_VK_BC_SCRATCH_FULL=1`" in dev, "docs/development.md: the BC scratch's switches are not in the table")

    with tempfile.TemporaryDirectory(prefix="bc-scratch-") as tmp:
        src, exe = Path(tmp) / "scratch.cpp", Path(tmp) / "scratch.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: the BC3 scratch has the layers one run uses: 20 MB, not 160")


if __name__ == "__main__":
    main()
