"""An image in the game's own BC or ASTC blocks is counted by whole blocks (gpu/vk/tex_count.h, vk_texture.cpp create;
no game, no GPU).

(Triforce, 11-22, the performance audit's TEX-86, after Source A's.) A texture the GPU samples as the game stores it
was counted by its texels: a byte a texel for BC (BC1 and BC4 are half that) and, for ASTC where the driver samples it,
the 16 bytes of a block for every texel: 64 times an 8 x 8 texture's size. The budget then let textures go for memory
nothing held.

Compiles tests/tex_count_test.cpp against the header: BC1, BC4 and BC7 and ASTC 4 x 4, 8 x 8, 10 x 5 and 12 x 12 chains
with their 1 x 1 tails, a 3D volume, layers, the levels from a first one on, the 1365 x 1365 x 90 ASTC 8 x 8 array at
53.8 MiB (3,410 as it was counted), and the switch's values.

And reads the source: create() asks the rule for the first size estimate (bytes_at) and for the budget's count, for an
image in the game's own format only (not one the renderer keeps as BC3 or BC1, x.bc), not a sparse one, before the pad
lifts the count to the allocation; the switch is read once and is in the switches table.

    python -I -B tests/test_tex_count_blocks.py [--cxx clang++]
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


def function(text, head):
    start = text.index(head)
    return text[start:text.index("\n}\n", start) + 3]


def check_source():
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    check('#include "tex_count.h"' in tex, "vk_texture.cpp does not include tex_count.h")
    on = function(tex, "bool count_by_blocks() {")
    check("static const bool on = [] {" in on and 'tex_count::by_texels(getenv("RX_VK_COUNT_BY_TEXELS"))' in on and on.count("logf(") == 2,
          "count_by_blocks no longer reads RX_VK_COUNT_BY_TEXELS once and says which count is on")
    create = function(tex, "Texture* create(const Key& key")
    # the first size estimate: asked while x.format is still the game's own format, for every level from `skip` on
    native = create.index("const bool native_blocks = (is_bc(x.format) || is_astc(x.format)) && count_by_blocks();")
    est = create.index("auto bytes_at = [&](uint32_t skip) -> uint64_t {")
    asked = create.index("if (native_blocks)\n                return tex_count::bytes(x.width, x.height, x.depth, skip, x.levels, x.layers, "
                         "(uint32_t)bw, (uint32_t)bh,\n                                        (uint32_t)bpb) * std::max(1, d.samples);")
    kept = create.index("x.bc = true")
    check(native < est < asked < create.index("x.sparse = np > 0;") < kept,
          "bytes_at no longer counts the game's own blocks by tex_count.h before anything is kept as BC3")
    check("return px * x.layers * texel * std::max(1, d.samples);" in create[asked:kept],
          "bytes_at no longer counts the other formats by their texels")
    # the budget's count: after the texels' count, before BC1's own line and the pad
    count = [create.index(n) for n in (
        "x.bytes = x.sparse ? 0 : px * x.layers * texel * x.samples;",
        "if (!x.sparse && !x.bc && (is_bc(x.format) || is_astc(x.format)) && count_by_blocks())\n"
        "        x.bytes = tex_count::bytes(x.width, x.height, x.depth, 0, x.levels, x.layers, (uint32_t)bw, (uint32_t)bh, (uint32_t)bpb) *\n"
        "                  x.samples;",
        "if (x.bc1) x.bytes = tex_bc1::bytes(x.width, x.height, x.levels, x.layers);",
        "if (!x.sparse && !by_estimate) x.pad = std::max(x.bytes, allocation_size(x.allocation)) - x.bytes;",
        "total_bytes += x.bytes + x.pad;")]
    check(count == sorted(count), "create() no longer counts the game's own blocks by tex_count.h between the texels' count and the pad")
    check(create.count("count_by_blocks()") == 2, "the count by blocks is asked somewhere else in create()")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `RX_VK_COUNT_BY_TEXELS=1` |" in docs and "`gpu/vk/tex_count.h`" in docs,
          "docs/development.md: RX_VK_COUNT_BY_TEXELS is not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="tex-count-") as tmp:
        exe = Path(tmp) / "tex-count.exe"
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK),
                        str(ROOT / "tests" / "tex_count_test.cpp"), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        check(r.returncode == 0, "the count by blocks: its checks failed")
    print("PASS: an image in the game's own BC or ASTC blocks is counted by whole blocks")


if __name__ == "__main__":
    main()
