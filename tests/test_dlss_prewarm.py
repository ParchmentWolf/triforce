"""NVIDIA DLSS at the output's size takes a scaled mode with RX_VK_DLSS_PREWARM=1, so the Render resolution row's Auto
makes one feature, not two (gpu/vk/dlss_checks.h dlaa_feature, vk_dlss.cpp prepare; no game, no GPU, no NVIDIA SDK).

(Triforce, 11-22, the performance audit's PRESENT-32, after Source A's: its first step.) prepare made a one-size feature
(NGX's DLAA mode) whenever the render size was the output's. With the row at Auto the game starts at the output's size
and lowers it some frames later: a second feature made in play. With the rule only NVIDIA DLAA gets the one-size mode;
DLSS at full size takes the scaled mode whose range holds it, which the smaller sizes reuse.

The entry's other steps (the feature, the chain's images and a first evaluation made ahead in a light frame) are not
built: see the commit. This checks what is.

It compiles dlss_checks.h and dlss_feature.h and runs prepare's decisions (the reuse test, the one-size test, the mode,
the size the feature is made for: the same functions in the same order, NGX's ranges as it answers them) over a load-in:
17 frames at the output's size, then the game's dynamic resolution going down and up. With the row at Auto: two
features without the rule, one with it, and that one takes every later size. With NVIDIA DLAA: one feature, of one
size, either way. With a fixed share: the same feature either way (the rule changes nothing there). Without the switch
every decision is the one from before.

Then the source: prepare asks dlaa_feature with the switch (read once) and whether DLAA is the Upscaler's choice, the
switch is on only at 1, and its row is in the development guide.

    python -I -B tests/test_dlss_prewarm.py [--cxx clang++]
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
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include "dlss_checks.h"
#include "dlss_feature.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
namespace dc = mkwvk::dlss_checks;

// vk_dlss.cpp prepare's decisions, without NGX: the feature there is, and what a frame of rw x rh into ow x oh does to it
struct Feature {
    bool has = false, exact = false, one_size = false;
    uint32_t w = 0, h = 0, ow = 0, oh = 0, min_w = 0, min_h = 0;
    int mode = -1;   // (the index into the scaled modes; -1: the one-size list's first, DLAA's)
};
struct Run {
    Feature f;
    bool range_seen = false;
    int made = 0, refused = 0;
    bool rule, dlaa, auto_row;
    Run(bool rule, bool dlaa, bool auto_row) : rule(rule), dlaa(dlaa), auto_row(auto_row) {}
    void frame(uint32_t rw, uint32_t rh, uint32_t ow, uint32_t oh) {
        const bool same = f.has && f.ow == ow && f.oh == oh;
        if (same && dlss_feature::takes(f.exact, f.w, f.h, f.min_w, f.min_h, rw, rh)) return;   // (the feature there is draws it)
        if (dlss_feature::found_range(same, f.exact, f.w, f.h, rw, rh)) range_seen = true;
        const bool aa = dc::dlaa_feature(rule, dlaa, rw, rh, ow, oh);
        uint32_t max_w = 0, max_h = 0, min_w = 0, min_h = 0;
        int mode = -1;
        if (aa) {
            max_w = min_w = ow, max_h = min_h = oh;
        } else {
            // (NGX's ranges for the scaled list: Quality, DLAA, Balanced, Performance from half the output to the output's own,
            // DLAA's and Ultra Performance's one size)
            const dc::ModeRange r[5] = {{ow / 2, oh / 2, ow, oh, true}, {ow, oh, ow, oh, true}, {ow / 2, oh / 2, ow, oh, true},
                                        {ow / 2, oh / 2, ow, oh, true}, {ow / 3, oh / 3, ow / 3, oh / 3, true}};
            bool widened = false;
            mode = dc::mode_for(r, 5, rw, rh, ow, oh, true, &widened);
            if (mode < 0) { refused++; return; }
            min_w = std::min(r[mode].min_w, rw), min_h = std::min(r[mode].min_h, rh);
            max_w = std::max(r[mode].max_w, rw), max_h = std::max(r[mode].max_h, rh);
        }
        const dlss_feature::Size s = dlss_feature::size(aa, range_seen || auto_row, rw, rh, max_w, max_h);
        f = {true, s.exact, aa, s.w, s.h, ow, oh, min_w, min_h, mode};
        made++;
    }
};
/// A load-in at an output of ow x oh: 17 frames at `start` percent, then the game's dynamic resolution moving
static void load_in(Run& run, uint32_t ow, uint32_t oh, unsigned start) {
    for (int i = 0; i < 17; i++) run.frame(ow * start / 100, oh * start / 100, ow, oh);
    for (unsigned pct : {95u, 90u, 80u, 75u, 60u, 50u, 65u, 85u, 100u, 70u}) run.frame(ow * pct / 100, oh * pct / 100, ow, oh);
}
int main() {
    const uint32_t outs[][2] = {{1920, 1080}, {2560, 1440}, {3840, 2160}, {4416, 1864}, {5120, 2160}};
    for (const auto& o : outs) {
        // NVIDIA DLSS, the Render resolution row at Auto, the game starting at the output's size
        Run before(false, false, true), with(true, false, true);
        load_in(before, o[0], o[1], 100), load_in(with, o[0], o[1], 100);
        CHECK(before.made == 2 && before.refused == 0);   // (the one-size feature, then the scaled mode's)
        CHECK(with.made == 1 && with.refused == 0);       // (the scaled mode's from the first frame)
        CHECK(with.f.mode == 0 && !with.f.one_size && !with.f.exact && with.f.w == o[0] && with.f.h == o[1]);
        CHECK(before.f.mode == with.f.mode && before.f.w == with.f.w && before.f.h == with.f.h && before.f.exact == with.f.exact);
        // NVIDIA DLAA: the output's one size, either way, and never a second feature at that size
        Run aa_before(false, true, false), aa_with(true, true, false);
        for (int i = 0; i < 40; i++) aa_before.frame(o[0], o[1], o[0], o[1]), aa_with.frame(o[0], o[1], o[0], o[1]);
        CHECK(aa_before.made == 1 && aa_with.made == 1 && aa_before.f.one_size && aa_with.f.one_size);
        CHECK(aa_with.f.w == o[0] && aa_with.f.h == o[1] && aa_with.f.mode == -1);
        // a fixed share (the row's Quality, 8 twelfths rounded up as the menu does): the rule changes nothing
        const uint32_t rw = (o[0] * 8 + 11) / 12, rh = o[1] * 8 / 12;
        Run fixed_before(false, false, false), fixed_with(true, false, false);
        for (int i = 0; i < 40; i++) fixed_before.frame(rw, rh, o[0], o[1]), fixed_with.frame(rw, rh, o[0], o[1]);
        CHECK(fixed_before.made == 1 && fixed_with.made == 1 && fixed_with.f.exact && fixed_with.f.w == rw && fixed_with.f.h == rh);
        CHECK(fixed_before.f.mode == fixed_with.f.mode && fixed_before.f.w == fixed_with.f.w);
        // DLSS with a fixed share of all of the output (one saved with the game's own): one size before, the scaled mode's with
        Run full_before(false, false, false), full_with(true, false, false);
        for (int i = 0; i < 40; i++) full_before.frame(o[0], o[1], o[0], o[1]), full_with.frame(o[0], o[1], o[0], o[1]);
        CHECK(full_before.made == 1 && full_with.made == 1 && full_before.f.one_size && !full_with.f.one_size && full_with.f.mode == 0);
    }
    std::printf("the row's Auto from the output's size down: 2 features before, 1 with the rule, at %d outputs\n",
                (int)(sizeof outs / sizeof outs[0]));
    return fails ? 1 : 0;
}
"""


def check_source():
    dlss = (VK / "vk_dlss.cpp").read_text(encoding="utf-8")
    prepare = dlss[dlss.index("int prepare(VkCommandBuffer cmd"):]
    prepare = prepare[:prepare.index("\n}\n")]
    check('static const bool dlaa_rule = dlss_checks::prewarm_rule(getenv("RX_VK_DLSS_PREWARM"));' in prepare,
          "prepare does not read RX_VK_DLSS_PREWARM once")
    one = "const bool aa = dlss_checks::dlaa_feature(dlaa_rule, temporal_mode() == upscaler_rows::DLAA, rw, rh, ow, oh);"
    check(one in prepare and "const bool aa = rw == ow && rh == oh;" not in prepare and prepare.count("const bool aa =") == 1,
          "prepare's one-size test is not dlaa_feature's, with the switch and the Upscaler's choice")
    check(prepare.index(one) < prepare.index("const NVSDK_NGX_PerfQuality_Value* modes = aa ? same : scaled;")
          < prepare.index("dlss_feature::size(aa, "), "prepare picks its modes or its size before the one-size test")
    checks = (VK / "dlss_checks.h").read_text(encoding="utf-8")
    check("return rule ? full && dlaa : full;" in checks and "return text && *text && std::atoi(text) == 1;" in checks,
          "dlss_checks.h: the rule is not off unless RX_VK_DLSS_PREWARM=1, or is not the entry's")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `RX_VK_DLSS_PREWARM=1` |" in docs, "docs/development.md has no row for RX_VK_DLSS_PREWARM")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="dlss-prewarm-") as tmp:
        src, exe = Path(tmp) / "prewarm.cpp", Path(tmp) / "prewarm.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(VK), str(src), "-o", str(exe)], check=True)
        out = subprocess.run([str(exe)], stdout=subprocess.PIPE, text=True, timeout=60)
        print(out.stdout.strip())
        if out.returncode:
            raise SystemExit("FAIL: the rule's run")
    print("PASS: with RX_VK_DLSS_PREWARM=1 DLSS at the output's size takes a scaled mode (one feature for the row's Auto); "
          "off, every decision is the one from before")


if __name__ == "__main__":
    main()
