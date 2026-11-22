"""NVIDIA DLSS's feature is made for a fixed share's own render size, not for the largest of its mode's range
(gpu/vk/dlss_feature.h, vk_dlss.cpp prepare; no game, no GPU, no NGX).

(Triforce, 11-21, the upscaler audit's UPS-01.) Every feature was made for the largest render size its quality mode
allows, which NGX answers as the output's own: with the Render resolution row at Quality the owner's log has a feature
"2944x1243 (2208x932 to 4416x1864) -> 4416x1864" made for 4416x1864, 2.25 times the pixels it is ever given, and DLSS's
own video memory at 1069 MB. NVIDIA's guide has the render size passed to the creation, and says the cost of presets L and
M follows the size the feature is initialized for.

This compiles dlss_feature.h alone and checks the rule: a fixed share's feature is its own render size and takes that size
alone; the row's Auto, a size seen changing and the switch give the mode's largest, which takes its whole range as
before; DLAA's is the output's; a render size over the mode's largest never makes a feature larger than it; a frame of
another size under an exact feature of the same output is what shows the range, and nothing else is.

And reads the source: prepare asks the rule for the feature it has and for the size it makes, with the row's Auto, what
this run saw and RX_VK_DLSS_FEATURE_MAX; the feature's size, not the mode's largest, is what NGX is given and what the
chain's inputs are made at; the log says which; and the switch is in the switches table.

    python -I -B tests/test_dlss_feature.py [--cxx clang++]
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
#include "dlss_feature.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace dlss_feature;
int main() {
    CHECK(!whole_range(nullptr) && !whole_range("") && !whole_range("0") && whole_range("1"));
    // (the owner's log: Quality, 2944x1243 into 4416x1864, the mode's range 2208x932 to 4416x1864)
    {   // a fixed share: its own render size, and that size alone
        const Size s = size(false, false, 2944, 1243, 4416, 1864);
        CHECK(s.w == 2944 && s.h == 1243 && s.exact);
        CHECK(takes(s.exact, s.w, s.h, 2208, 932, 2944, 1243));
        CHECK(!takes(s.exact, s.w, s.h, 2208, 932, 2943, 1243) && !takes(s.exact, s.w, s.h, 2208, 932, 2944, 1244));
        CHECK(!takes(s.exact, s.w, s.h, 2208, 932, 2208, 932) && !takes(s.exact, s.w, s.h, 2208, 932, 4416, 1864));
        CHECK((uint64_t)s.w * s.h * 2 < (uint64_t)4416 * 1864);   // (under half the pixels of the largest)
    }
    {   // the row's Auto, a size seen changing, the switch: the mode's largest, every size of its range, as before
        const Size s = size(false, true, 2944, 1243, 4416, 1864);
        CHECK(s.w == 4416 && s.h == 1864 && !s.exact);
        CHECK(takes(s.exact, s.w, s.h, 2208, 932, 2944, 1243) && takes(s.exact, s.w, s.h, 2208, 932, 2208, 932) &&
              takes(s.exact, s.w, s.h, 2208, 932, 4416, 1864));
        CHECK(!takes(s.exact, s.w, s.h, 2208, 932, 2207, 932) && !takes(s.exact, s.w, s.h, 2208, 932, 2208, 931) &&
              !takes(s.exact, s.w, s.h, 2208, 932, 4417, 1864));
    }
    {   // DLAA: the output's, its one size, whatever the rest says
        for (int range = 0; range < 2; range++) {
            const Size s = size(true, range != 0, 4416, 1864, 4416, 1864);
            CHECK(s.w == 4416 && s.h == 1864 && !s.exact);
            CHECK(takes(s.exact, s.w, s.h, 4416, 1864, 4416, 1864) && !takes(s.exact, s.w, s.h, 4416, 1864, 2944, 1243));
        }
    }
    {   // a render size past the mode's largest (never asked: the mode is found by its range) makes none larger than it
        const Size s = size(false, false, 5000, 1243, 4416, 1864);
        CHECK(s.w == 4416 && s.h == 1864 && !s.exact);
    }
    {   // what shows that the render size changes: an exact feature of the same output, and a frame of another size
        CHECK(found_range(true, true, 2944, 1243, 2800, 1182));
        CHECK(found_range(true, true, 2944, 1243, 2944, 1242));
        CHECK(!found_range(true, true, 2944, 1243, 2944, 1243));     // (the same size: nothing)
        CHECK(!found_range(false, true, 2944, 1243, 2800, 1182));    // (another output, preset or colour: a feature of its own)
        CHECK(!found_range(true, false, 4416, 1864, 2800, 1182));    // (a feature for the range already)
    }
    {   // every share the Render resolution row has, at 3840x2160: the feature's pixels against the largest's
        const uint32_t ow = 3840, oh = 2160;
        const uint32_t shares[4][2] = {{2560, 1440}, {2240, 1260}, {1920, 1080}, {1280, 720}};
        for (const auto& r : shares) {
            const Size s = size(false, false, r[0], r[1], ow, oh);
            CHECK(s.exact && s.w == r[0] && s.h == r[1] && takes(s.exact, s.w, s.h, 0, 0, r[0], r[1]));
        }
    }
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    src = (VK / "vk_dlss.cpp").read_text(encoding="utf-8")

    check('#include "dlss_feature.h"' in src, "vk_dlss.cpp does not use the rule")
    prep = block(src, "int prepare(VkCommandBuffer cmd, uint32_t rw, uint32_t rh, uint32_t ow, uint32_t oh, bool hdr, uint32_t* in_w,")
    at = [prep.index(part) for part in (
        "const bool same_feature = s.feature && s.feature_ow == ow && s.feature_oh == oh && s.feature_preset == preset && s.feature_hdr == hdr;",
        "if (same_feature && dlss_feature::takes(s.feature_exact, s.feature_rw, s.feature_rh, s.min_rw, s.min_rh, rw, rh))",
        "return *in_w = s.feature_rw, *in_h = s.feature_rh, 1;",
        "const bool found_range = dlss_feature::found_range(same_feature, s.feature_exact, s.feature_rw, s.feature_rh, rw, rh);",
        "if (found_range) s.range_seen = true;",
        'static const bool whole_range = dlss_feature::whole_range(getenv("RX_VK_DLSS_FEATURE_MAX"));',
        "dlss_feature::size(aa, whole_range || s.range_seen || opts.resolution == 0, rw, rh, max_w, max_h);",
        "cp.Feature.InWidth = made.w, cp.Feature.InHeight = made.h, cp.Feature.InTargetWidth = ow, cp.Feature.InTargetHeight = oh;",
        "NGX_VULKAN_CREATE_DLSS_EXT(cmd, 1, 1, &s.feature, s.params, &cp);",
        "s.feature_rw = made.w, s.feature_rh = made.h, s.feature_ow = ow, s.feature_oh = oh, s.min_rw = min_w, s.min_rh = min_h;",
        "s.feature_exact = made.exact;",
        "*in_w = s.feature_rw, *in_h = s.feature_rh;",
        "return 2;")]
    check(at == sorted(at), "prepare does not ask the rule for the feature it has, then for the size it makes, and keep what it made")
    check("cp.Feature.InWidth = max_w" not in prep and "s.feature_rw = max_w" not in prep,
          "a feature is still made for its mode's largest render size whatever the row says")
    check("this render size alone (RX_VK_DLSS_FEATURE_MAX=1: its mode's largest)" in prep and "the largest of its range" in prep,
          "the log does not say what size the feature was made for")
    check("for its mode's whole range from now on" in prep, "the log does not say why a feature is made again when the render size changes")
    rel = block(src, "void release() {")
    check("s.feature_exact = false;" in rel, "a feature let go keeps its size's kind")
    # (unchanged, as the chain reads them: the evaluation is given the frame's own render size, whatever the feature's)
    ev = block(src, "bool evaluate(VkCommandBuffer cmd, const TemporalFrame& f) {")
    check("ep.InRenderSubrectDimensions = {f.render_w, f.render_h};" in ev, "the evaluation is not given the frame's render size")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_DLSS_FEATURE_MAX=1`" in dev, "docs/development.md: RX_VK_DLSS_FEATURE_MAX=1 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="dlss-feature-") as tmp:
        c, exe = Path(tmp) / "feature.cpp", Path(tmp) / "feature.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: NVIDIA DLSS's feature is made for a fixed share's own render size, the mode's largest only where the size changes")


if __name__ == "__main__":
    main()
