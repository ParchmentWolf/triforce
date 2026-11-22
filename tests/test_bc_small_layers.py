"""BC mip levels of 1024 or less are re-encoded 8 layers a run, through a small scratch (gpu/vk/bc_scratch.h, vk_texture.cpp
bc_small_layers, bc_scratch_make, bc_scratch_layout, bc_scratch_idle, bc_encode_into, upload_astc_gpu; no game, no GPU).

(Triforce, 11-21, the performance audit's TEX-09, after Source A's.) A run is a decode, an encode, a copy and three full
barriers, and one layer a run made a terrain array of 90 layers and 11 levels about 990 of them.

This compiles bc_scratch.h alone and checks the rule: the small scratch's layers are 8 unless RX_VK_BC_SMALL_LAYERS says 1
to 8, and 1 on AMD's cards when it is not set; a level of 1024 or less each way goes through it, a 1365 level, a level
1025 one way, a texture encoded at another size and a start with no small scratch do not; a layer of a run begins where the
encoder wrote it (16 bytes a block of 4 x 4, 8 as BC1, uneven sizes rounded up to blocks); and it counts a 1365 x 1365 x 90
array's runs: 990 at one layer a run, 210 with 8 for its levels from the second down.

And reads the source: the small scratch is made with the first, only at full texture detail and with more than one layer
asked, and given back with it; its layout is set before its first use; the one output buffer holds a run of either; a
level asks the rule which scratch and takes that scratch's run, view and encode source; the copy has a region a layer at
the rule's offsets; the switch is in the switches table.

    python -I -B tests/test_bc_small_layers.py [--cxx clang++]
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
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include "bc_scratch.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
// the runs of one array: every level, its layers in runs of the scratch it goes through
static int runs(uint32_t w, uint32_t h, uint32_t layers, uint32_t levels, bool have_small, uint32_t small_n, uint32_t big_n) {
    int n = 0;
    for (uint32_t l = 0; l < levels; l++) {
        const uint32_t lw = std::max(1u, w >> l), lh = std::max(1u, h >> l);
        const uint32_t run = bc_scratch::small_level(lw, lh, have_small, false) ? small_n : big_n;
        n += (int)((layers + run - 1) / run);
    }
    return n;
}
int main() {
    using namespace bc_scratch;
    CHECK(kSmallDim == 1024);
    const uint32_t nvidia = 0x10DE, amd = 0x1002, intel = 0x8086;
    CHECK(small_layers(nullptr, nvidia) == 8 && small_layers(nullptr, intel) == 8 && small_layers("", nvidia) == 8);
    CHECK(small_layers(nullptr, amd) == 1 && small_layers("", amd) == 1);          // (until the picture is checked there)
    CHECK(small_layers("8", amd) == 8 && small_layers("4", amd) == 4);             // (asked for: on any card)
    CHECK(small_layers("1", nvidia) == 1 && small_layers("0", nvidia) == 1 && small_layers("99", nvidia) == 8);
    CHECK(small_level(1024, 1024, true, false) && small_level(682, 682, true, false) && small_level(1, 1, true, false));
    CHECK(!small_level(1365, 1365, true, false) && !small_level(1025, 4, true, false) && !small_level(4, 1025, true, false));
    CHECK(!small_level(512, 512, false, false));     // (no small scratch: RX_VK_BC_SMALL_LAYERS=1, AMD, reduced detail)
    CHECK(!small_level(512, 512, true, true));       // (encoded at another size: the second scratch's)
    CHECK(small_out_bytes(8) == 8ull << 20 && small_out_bytes(1) == 1ull << 20 && small_image_bytes(8) == 32ull << 20);
    CHECK(small_out_bytes(8) > out_bytes(1));        // (so the one output buffer has to be the larger of the two)
    // where a run's layers are in the encoder's output
    CHECK(layer_offset(0, 682, 682, false) == 0);
    CHECK(layer_offset(1, 1024, 1024, false) == 256ull * 256 * 16 && layer_offset(7, 1024, 1024, false) == 7 * 256ull * 256 * 16);
    CHECK(layer_offset(1, 682, 682, false) == 171ull * 171 * 16);   // (682 texels: 171 blocks, rounded up)
    CHECK(layer_offset(3, 85, 43, false) == 3 * 22ull * 11 * 16);
    CHECK(layer_offset(2, 512, 512, true) == 2 * 128ull * 128 * 8);  // (kept as BC1: the colour half alone)
    CHECK(layer_offset(7, 1024, 1024, false) + 256ull * 256 * 16 <= small_out_bytes(8));   // (the last layer fits the buffer)
    // a terrain array, 1365 x 1365 x 90 with 11 levels
    CHECK(runs(1365, 1365, 90, 11, false, 8, 1) == 990);
    CHECK(runs(1365, 1365, 90, 11, true, 8, 1) == 90 + 10 * 12);     // (its first level one layer a run, the rest 8)
    CHECK(runs(1365, 1365, 90, 11, true, 8, 1) == 210);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")

    layers = block(tex, "uint32_t bc_small_layers() {")
    check('bc_scratch::small_layers(getenv("RX_VK_BC_SMALL_LAYERS"), dev.props.vendorID)' in layers,
          "the small scratch's layers are not the rule's of the switch and the card's vendor")
    make = block(tex, "bool bc_scratch_make() {")
    check("if (bc_small_layers() > 1 && texture_detail_level() == tex_detail::kFull) {" in make,
          "the small scratch is made with one layer asked, or at reduced texture detail")
    check("si.extent = {bc_scratch::kSmallDim, bc_scratch::kSmallDim, 1};" in make and "si.arrayLayers = bc_small_layers();" in make and
          "sv.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, bc_small_layers()};" in make,
          "the small scratch or its view is not 1024 x 1024 with a run's layers")
    check("const uint64_t out = std::max(bc_scratch::out_bytes(bc_scratch_layers()), small_out);" in make and
          "bc_small ? bc_scratch::small_out_bytes(bc_small_layers()) : 0" in make,
          "the output buffer does not hold a run of either scratch")
    check("bc_small_fresh = bc_small != VK_NULL_HANDLE;" in make, "a new small scratch's layout is not marked to be set")
    failed = make[make.index("!make_out()) {"):make.index("bc_scratch_fresh = true;")]
    check("if (bc_small) destroy_image(bc_small, bc_small_alloc);" in failed, "the small scratch stays when the first could not be made")
    layout = block(tex, "bool bc_scratch_layout(")
    check("|| (bc_small_fresh && bc_small));" in layout and "b.image = bc_small;" in layout and
          "b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, bc_small_layers()};" in layout and
          layout.index("b.image = bc_small;") < layout.index("if (!bc_scratch_fresh) return true;"),
          "the small scratch's layout is not set before its first use")
    idle = block(tex, "void bc_scratch_idle() {")
    check("dead.push_back(Dead{bc_last_value, bc_small, bc_small_alloc, {bc_small_view}, {}});" in idle and
          "bc_small = VK_NULL_HANDLE" in idle, "the small scratch is not given back with the first")
    start = tex.index("    if (tex.bc) {   // (decoded into the scratch a run of consecutive layers at a time, re-encoded, copied in)")
    loop = tex[start:tex.index("        st_astc++;", start)]
    check("const bool small = bc_scratch::small_level(g.w, g.h, bc_small != VK_NULL_HANDLE, tex.bc_resized);" in loop and
          "const uint32_t run = small ? bc_small_layers() : bc_layers();" in loop,
          "a level does not ask the rule which scratch it goes through, or does not take that scratch's run")
    check("VkDescriptorImageInfo ii{VK_NULL_HANDLE, small ? bc_small_view : bc_scratch_view, VK_IMAGE_LAYOUT_GENERAL};" in loop and
          "bc_encode_into(cmd, iw, ih, n, tex, level, layers[k0], 0, 0, small ? bc_small_view : VK_NULL_HANDLE);" in loop,
          "a small level is not decoded into the small scratch and encoded from it")
    check("bc_encode_resized(cmd, g.w, g.h, iw, ih, n, tex, level, layers[k0]);" in loop, "a resized texture's levels lost their own path")
    enc = block(tex, "void bc_encode_into(")
    check("VkBufferImageCopy c[kBcLayers];" in enc and
          "bc_scratch::layer_offset(k, w, h, dst.bc1), 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, level, layer + k, 1}" in enc and
          "vkCmdCopyBufferToImage(cmd, bc_out, dst.image, VK_IMAGE_LAYOUT_GENERAL, std::min(n, kBcLayers), c);" in enc,
          "a run's layers are not copied by a region each, at the encoder's layer stride")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_BC_SMALL_LAYERS=<n>`" in dev, "docs/development.md: RX_VK_BC_SMALL_LAYERS is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="bc-small-") as tmp:
        c, exe = Path(tmp) / "small.cpp", Path(tmp) / "small.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: BC levels of 1024 or less run 8 layers at once through the small scratch: a 90-layer array's 990 runs are 210")


if __name__ == "__main__":
    main()
