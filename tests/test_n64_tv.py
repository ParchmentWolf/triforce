"""N64 Classic's TV (gpu/vk/shaders/n64_tv.comp and n64_tv.glsl; vk_framegen.cpp framegen_scale, init_tv; upscaler_rows.h
kTvFilter, tv_filter; vk_menu.cpp menu_note_present_sizes; vk_n64.cpp n64_tv_now). Step 4 of n64-classic-mode-plan.md, behind
RX_VK_N64 as the steps before. No game, no GPU.

Compiled and run: n64_tv.glsl, written in what GLSL and C++ share, over a small GLSL stand-in (as aa_common.glsl is): no
scanlines leave every channel as it is; the beam never takes light below 0 nor more than doubles it, its mean over a line by
its closed form is the mean summed, a flat picture keeps its brightness within 15% at the presets' scanlines at any level,
and a bright line is wider; the aperture grille and the shadow mask light one channel a pixel, the grille repeats every 3
pixels and the slot mask every 6 by 4 with one dark row in 4, neighbouring triads' 2 apart, each mask lights the three
colours alike and dims the picture less than a fifth at 30%; the colour to the composite signal and back, grey carrying no
colour, the bleed's weights; the screen's curve, which keeps the picture in order and loses its corners, the vignette and
the rounded corners only on a curved screen. And upscaler_rows.h's tv_filter: the TV's value while it runs, past the filters
RX_VK_UPSCALE names.

n64_tv_comp_spv.h names the hash of the sources it was compiled from (n64_tv.comp, n64_common.glsl, n64_tv.glsl), checked
with or without glslang; with glslangValidator of the version the header names, the rest of the header is the pass compiled
now, byte for byte. --write makes the header.

Read in the sources: the shader's bindings and push constants, and the C++ struct framegen_scale pushes, field for field; the
shader decodes the picture and encodes it again, warps it, takes the beam and the mask per channel at the window's own
pixels; framegen_scale runs the TV before AMD FSR 1 and the filter, only with n64_tv_now and its pipeline made, makes the
picture at 1/8 for the glow, draws ultrawide's menu sides first into an image of the window's size, and gives the TV the
screen's scanline strength and mask (n64_rules.h), the bleed in the picture's widths and (step 8) the switch's frame (the
squash to a line and a dot, the flash), ticked once a present from vk_replay.cpp; init_tv's pipeline; the filter the
present takes is tv_filter's over window_filter's; n64_tv_now asks n64_rules.h tv_runs with DLSS frame generation; the
development guide names the switches.

(11-22, after the owner's test: "None of the classic visual effects apply to any of the custom UI") The options' own screens
under the TV: the shader lays their layer over the picture where it reads the picture (every tap, the bleed's too), before
the TV's steps; framegen_scale says the TV drew (vk_n64.h n64_screen_drawn) and asks vk_menu.cpp menu_tv_layer for the layer
before its pass, binding it fourth; the present says where the picture goes before the window pass and is done after it;
menu_tv_layer draws the options into ImGui's background list and the layer (vk_imgui.cpp record_layer, cleared, GENERAL
for the pass), menu_record the rest over the window (record_rest). Compiled: n64_rules.h screen_point, the mouse's, takes a
window pixel to the very place of the picture n64_tv.comp samples for it (its squash and n64_warp), and leaves points
beside the place as they are.

    python -I -B tests/test_n64_tv.py [--cxx clang++] [--glslang glslangValidator] [--write]
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
SHADERS = VK / "shaders"
PARTS = ("n64_tv.comp", "n64_common.glsl", "n64_tv.glsl")
HEADER = SHADERS / "n64_tv_comp_spv.h"
FLAGS = ["-V", "--target-env", "vulkan1.2", "--vn", "N64_TV_COMP_SPV"]

DRIVER = r'''
#include "n64_rules.h"
#include "upscaler_rows.h"

#include <cmath>
#include <cstdio>
#include <initializer_list>

// (just enough of GLSL for n64_common.glsl and n64_tv.glsl, in a namespace of its own)
namespace glsl {
static float floor(float a) { return std::floor(a); }
static float clamp(float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; }
static float pow(float a, float b) { return std::pow(a, b); }
static float exp(float a) { return std::exp(a); }
static float sqrt(float a) { return std::sqrt(a); }
static float max(float a, float b) { return a < b ? b : a; }
static float abs(float a) { return std::fabs(a); }
#include "shaders/n64_common.glsl"
#include "shaders/n64_tv.glsl"
}  // namespace glsl

using namespace glsl;
static int checks, fails;
static void want(bool ok, const char* what) {
    checks++;
    if (!ok) fails++, std::printf("FAIL %s\n", what);
}

int main() {
    // ---- the beam ----
    bool flat = true, bounded = true;
    for (int i = 0; i <= 100; i++)
        for (int l = 0; l <= 10; l++) {
            const float f = -0.5f + i / 100.0f, level = l / 10.0f;
            flat &= n64_scan(f, level, 0.0f) == 1.0f;
            for (float s : {0.35f, 0.6f, 0.8f, 1.0f}) {
                const float m = n64_scan(f, level, s);
                bounded &= m >= 0.0f && m <= 2.0f;
            }
        }
    want(flat, "no scanlines: every channel as it is");
    want(bounded, "the beam never takes light below 0 nor more than doubles it");
    bool means = true, kept = true;
    float worst = 1.0f;
    for (int l = 0; l <= 20; l++) {
        const float level = l / 20.0f;
        double sum = 0.0;
        const int n = 4000;
        for (int i = 0; i < n; i++) sum += n64_beam(-0.5f + (i + 0.5f) / n, level);
        means &= std::fabs(sum / n - n64_beam_mean(level)) < 2e-3;
        for (float s : {0.35f, 0.6f, 0.8f}) {
            double a = 0.0;
            for (int i = 0; i < n; i++) a += n64_scan(-0.5f + (i + 0.5f) / n, level, s);
            a /= n;
            kept &= a >= 0.85 && a <= 1.1;
            worst = (float)a < worst ? (float)a : worst;
        }
    }
    want(means, "the beam's mean over a line, by its closed form, within two thousandths");
    want(kept, "a flat picture keeps its brightness within 15% at the presets' scanlines, any level");
    std::printf("(the darkest flat picture through the scanlines: %.3f of its light)\n", worst);
    want(n64_beam(0.4f, 1.0f) > n64_beam(0.4f, 0.2f) && n64_beam(0.0f, 0.5f) == 1.0f, "a bright line is wider; the line's middle is its peak");

    // ---- the mask ----
    bool one = true, repeats = true, breaks = true, none_off = true;
    for (int y = 0; y < 12; y++)
        for (int x = 0; x < 12; x++) {
            for (int type : {2, 4}) {
                float lit = 0.0f;
                for (int c = 0; c < 3; c++) lit += n64_mask_lit(x, y, type, c);
                one &= lit == 1.0f;
            }
            for (int c = 0; c < 3; c++) {
                repeats &= n64_mask_lit(x, y, 2, c) == n64_mask_lit(x + 3, y + 1, 2, c);
                repeats &= n64_mask_lit(x, y, 3, c) == n64_mask_lit(x + 6, y + 4, 3, c);
                none_off &= n64_mask(x, y, 1, c, 0.5f) == 1.0f && n64_mask(x, y, 2, c, 0.0f) == 1.0f;
            }
        }
    for (int x = 0; x < 12; x++) {
        int dark = 0, row = -1;
        for (int y = 0; y < 4; y++) {
            float lit = 0.0f;
            for (int c = 0; c < 3; c++) lit += n64_mask_lit(x, y, 3, c);
            if (lit == 0.0f) dark++, row = y;
            else breaks &= lit == 1.0f;
        }
        breaks &= dark == 1 && row == ((x / 3) % 2 ? 2 : 0);
    }
    want(one, "the aperture grille and the shadow mask light one channel a pixel");
    want(repeats, "the grille repeats every 3 pixels, the slot mask every 6 by 4");
    want(breaks, "the slot mask: one dark row in 4, neighbouring triads' 2 rows apart");
    want(none_off, "no mask, or no strength: every channel as it is");
    bool even = true;
    for (int type : {2, 3, 4}) {
        double sum[3] = {0, 0, 0};
        for (int y = 0; y < 4; y++)
            for (int x = 0; x < 6; x++)
                for (int c = 0; c < 3; c++) sum[c] += n64_mask(x, y, type, c, 0.3f);
        even &= std::fabs(sum[0] - sum[1]) < 1e-4 && std::fabs(sum[1] - sum[2]) < 1e-4 && sum[0] / 24.0 > 0.8 && sum[0] / 24.0 < 1.0;
    }
    want(even, "each mask lights the three colours alike (no cast), dimming the picture less than a fifth at 30%");

    // ---- the composite signal ----
    bool round = true, grey = true;
    for (int i = 0; i <= 10; i++)
        for (int j = 0; j <= 10; j++) {
            const float r = i / 10.0f, g = j / 10.0f, b = (i * j % 11) / 10.0f;
            const float y = n64_y(r, g, b), ii = n64_i(r, g, b), q = n64_q(r, g, b);
            round &= std::fabs(n64_red(y, ii, q) - r) < 2e-3f && std::fabs(n64_green(y, ii, q) - g) < 2e-3f &&
                     std::fabs(n64_blue(y, ii, q) - b) < 2e-3f;
            grey &= std::fabs(n64_i(r, r, r)) < 1e-6f && std::fabs(n64_q(r, r, r)) < 1e-6f;
        }
    want(round, "the colour to the signal and back, within two thousandths");
    want(grey, "grey carries no colour: the bleed leaves it grey");
    float wsum = 0.0f;
    for (int t = -2; t <= 2; t++) wsum += n64_bleed_weight(t);
    want(std::fabs(wsum - 1.0f) < 1e-6f && n64_bleed_weight(-1) == n64_bleed_weight(1) && n64_bleed_weight(0) > n64_bleed_weight(2),
         "the bleed's weights: symmetric, the middle heaviest, one in all");

    // ---- the screen ----
    want(n64_warp(0.3f, -0.7f, 0.0f) == 0.3f && n64_warp(0.0f, 0.9f, 0.05f) == 0.0f, "a flat screen, and the middle: as they are");
    want(n64_warp(1.0f, 1.0f, 0.03f) > 1.0f && n64_warp(0.98f, 0.98f, 0.015f) > 1.0f, "a curved screen loses the picture's corners");
    bool outward = true;
    for (int i = 1; i <= 100; i++) outward &= n64_warp(i / 100.0f, 0.5f, 0.03f) > n64_warp((i - 1) / 100.0f, 0.5f, 0.03f);
    want(outward, "the warp keeps the picture in order");
    bool vig = true;
    for (int i = 0; i <= 10; i++)
        for (int j = 0; j <= 10; j++) {
            vig &= n64_vignette(i / 10.0f, j / 10.0f, 0.0f) == 1.0f;
            vig &= n64_vignette(i / 10.0f, j / 10.0f, 0.05f) >= 0.399f;
        }
    want(vig && n64_vignette(0.5f, 0.5f, 0.03f) == 1.0f && n64_vignette(0.02f, 0.02f, 0.03f) < 0.8f,
         "the vignette: none on a flat screen, darker corners on a curved one, never below 0.4");
    want(n64_corner(0.0f, 0.0f, 0.03f) == 1.0f && n64_corner(1.0f, 1.0f, 0.03f) == 0.0f && n64_corner(1.0f, 1.0f, 0.0f) == 1.0f &&
         n64_corner(0.99f, 0.0f, 0.03f) == 1.0f, "the rounded corners: only at the corners, only on a curved screen");

    // ---- (11-22) the mouse: the place of the picture the TV samples for a window pixel, as n64_tv.comp finds it ----
    namespace nr = mkwvk::n64_rules;
    bool same_place = true, beside = true;
    const float px0 = 240.0f, py0 = 0.0f, pw = 1440.0f, ph = 1080.0f;   // (a 4:3 picture in a 16:9 window)
    for (float curve : {0.0f, 0.015f, 0.03f, 0.05f})
        for (float ax : {1.0f, 0.5f})
            for (int gy = 0; gy < 1080; gy += 27)
                for (int gx = 0; gx < 1440; gx += 31) {
                    // (n64_tv.comp: the pixel's middle in -1..1 of the place, the squash, the warp, the picture's uv)
                    float a = (gx + 0.5f) / pw * 2.0f - 1.0f, b = (gy + 0.5f) / ph * 2.0f - 1.0f;
                    a /= ax, b /= 1.0f;
                    const float u = n64_warp(a, b, curve) * 0.5f + 0.5f, v = n64_warp(b, a, curve) * 0.5f + 0.5f;
                    const nr::ScreenPoint s = nr::screen_point(px0 + gx + 0.5f, py0 + gy + 0.5f, px0, py0, pw, ph, curve, ax, 1.0f);
                    same_place &= std::fabs(s.x - (px0 + u * pw)) < 1e-2f && std::fabs(s.y - (py0 + v * ph)) < 1e-2f;
                }
    for (float x : {0.0f, 100.0f, 239.0f, 1681.0f, 1919.0f}) {
        const nr::ScreenPoint s = nr::screen_point(x, 500.0f, px0, py0, pw, ph, 0.03f, 1.0f, 1.0f);
        beside &= s.x == x && s.y == 500.0f;
    }
    const nr::ScreenPoint none = nr::screen_point(700.0f, 300.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.03f, 1.0f, 1.0f);
    want(same_place, "the mouse: a window pixel taken to the place of the picture n64_tv.comp samples for it, at every curve and squash");
    want(beside && none.x == 700.0f && none.y == 300.0f, "the mouse: beside the picture's place, or with no place, the point as it is");
    const nr::ScreenPoint mid = nr::screen_point(960.0f, 540.0f, px0, py0, pw, ph, 0.03f, 1.0f, 1.0f);
    const nr::ScreenPoint edge = nr::screen_point(px0 + 10.0f, 540.0f, px0, py0, pw, ph, 0.03f, 1.0f, 1.0f);
    want(mid.x == 960.0f && mid.y == 540.0f && edge.x < px0 + 10.0f, "the mouse: the middle as it is; near an edge, out toward it, as the curve drew it");

    // ---- the window's filter with the TV ----
    namespace ur = mkwvk::upscaler_rows;
    want(ur::tv_filter(3, true) == ur::kTvFilter && ur::tv_filter(0, true) == ur::kTvFilter && ur::tv_filter(3, false) == 3 &&
         ur::tv_filter(0, false) == 0, "the TV's filter while it runs, at 1:1 too; else the filter as it was chosen");
    want(ur::kTvFilter > 3 && ur::window_filter(2560, 1440, 3840, 2160, false) != ur::kTvFilter,
         "the TV's value is past the filters RX_VK_UPSCALE names and window_filter gives");

    if (fails) std::printf("n64 tv: FAILED (%d of %d checks)\n", fails, checks);
    else std::printf("n64 tv: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def fail(what):
    raise SystemExit("FAIL: " + what)


def source_line():
    """the header's first line: the hash of the pass's sources (each by its name and its bytes, line ends as LF) and how it is made"""
    digest = hashlib.sha256()
    for part in PARTS:
        digest.update(part.encode() + b"\0" + (SHADERS / part).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return ("// %s sha256 %s (tests/test_n64_tv.py --write: glslangValidator %s)\n"
            % (" + ".join(PARTS), digest.hexdigest(), " ".join(FLAGS))).encode()


def compiled(glslang, tmp):
    out = Path(tmp) / "n64_tv.h"
    r = subprocess.run([glslang, *FLAGS, "-o", str(out), str(SHADERS / "n64_tv.comp")], capture_output=True, text=True)
    if r.returncode:
        fail("n64_tv.comp does not compile:\n%s%s" % (r.stdout, r.stderr))
    return out.read_bytes().replace(b"\r\n", b"\n")


def glslang_version(glslang):
    got = subprocess.run([glslang, "--version"], capture_output=True, text=True).stdout
    m = re.search(r"Glslang Version: \d+:(\d+)\.(\d+)\.(\d+)", got)
    return m and "11%02d.%s.%s" % (int(m.group(1)), m.group(2), m.group(3))


def block(src, head):
    at = src.index(head)
    end = src.index("{", at) + 1
    depth = 1
    while depth:
        depth += (src[end] == "{") - (src[end] == "}")
        end += 1
    return src[at:end]


def in_order(text, parts, what):
    at = [text.find(p) for p in parts]
    if min(at) < 0 or at != sorted(at):
        fail("%s: %s" % (what, [p for p, a in zip(parts, at) if a < 0] or at))


def check_sources():
    comp = (SHADERS / "n64_tv.comp").read_text(encoding="utf-8")
    in_order(comp, ['#extension GL_GOOGLE_include_directive : require', '#include "n64_common.glsl"', '#include "n64_tv.glsl"',
                    "void main()"], "n64_tv.comp no longer includes n64_common.glsl and n64_tv.glsl")
    for b in ("layout(binding = 0) uniform sampler2D src;", "layout(binding = 1, rgba8) uniform writeonly image2D dst;",
              "layout(binding = 2) uniform sampler2D small;", "layout(binding = 3) uniform sampler2D menu;"):
        if b not in comp:
            fail("n64_tv.comp: %s is not its binding" % b)
    push = re.search(r"layout\(push_constant\) uniform P \{(.*?)\} pc;", comp, re.S)
    fields = re.findall(r"^\s*(\w+) (\w+);", push.group(1), re.M) if push else []
    want = [("float", "lines"), ("float", "scan"), ("float", "mask"), ("float", "bleed"), ("float", "glow"), ("float", "curve"),
            ("float", "saturation"), ("int", "mask_type"), ("float", "anim_x"), ("float", "anim_y"), ("float", "flash"),
            ("int", "menu")]
    if fields != want:
        fail("n64_tv.comp's push constants are not %s: %s" % (want, fields))
    # ((11-22) the options' layer over the picture wherever the picture is read, before main's steps)
    read = block(comp, "vec3 encoded(vec2 uv) {")
    in_order(read, ["vec3 c = clamp(textureLod(src, uv, 0.0).rgb, 0.0, 1.0);", "if (pc.menu != 0) {",
                    "const vec4 m = clamp(textureLod(menu, uv, 0.0), 0.0, 1.0);", "c = m.rgb + c * (1.0 - m.a);",
                    "return clamp(c, 0.0, 1.0);"],
             "n64_tv.comp: encoded no longer lays the options' layer (premultiplied) over the picture")
    if comp.index("vec3 encoded(vec2 uv) {") > comp.index("void main()") or "textureLod(src," in block(comp, "void main()"):
        fail("n64_tv.comp: main reads the picture past encoded (the options' layer would be left out of a tap)")
    # ((11-22, the owner's second look) the glow's 1/8 copy made again with the options over the picture: the block's mean of
    # encoded, before the TV's own steps; else the glow blurred the game's own panes through the options' plates)
    in_order(block(comp, "void main()"), ["if (pc.menu == 2) {", "for (int x = 0; x < 4; x++) sum += encoded(at + (vec2(x, y) - 1.5) * 0.25 * block);",
                                          "imageStore(dst, g, vec4(sum / 16.0, 1.0));\n        return;", "vec2 p = (vec2(g) + 0.5) / vec2(d) * 2.0 - 1.0;"],
             "n64_tv.comp: menu 2 does not make the 1/8 copy from the picture with the options over it, before the TV's steps")
    main = block(comp, "void main()")
    in_order(main, ["if (abs(p.x) > pc.anim_x || abs(p.y) > pc.anim_y) {", "imageStore(dst, g, vec4(0.0, 0.0, 0.0, 1.0));",
                    "p /= vec2(pc.anim_x, pc.anim_y);", "n64_warp(p.x, p.y, pc.curve)", "if (abs(w.x) > 1.0 || abs(w.y) > 1.0) {",
                    "n64_bleed_weight(t)",
                    "vec3 c = decode3(e);", "mix(vec3(luma), c, pc.saturation)", "fract(uv.y * pc.lines) - 0.5",
                    "n64_scan(f, c.r, pc.scan)", "n64_mask(g.x, g.y, pc.mask_type, 0, pc.mask)", "pc.glow * decode3(",
                    "n64_vignette(uv.x, uv.y, pc.curve) * n64_corner(w.x, w.y, pc.curve)",
                    "c = mix(c, vec3(0.9, 0.95, 1.0), clamp(pc.flash, 0.0, 1.0) * 0.8);", "encode3(clamp(c, 0.0, 1.0)) + dither(g)"],
             "n64_tv.comp's steps are no longer the switch's squash, the curve, the bleed, linear light, the beam, the mask, the glow, "
             "the vignette, the switch's flash")
    for ch in ("n64_scan(f, c.g, pc.scan)", "n64_scan(f, c.b, pc.scan)", "n64_mask(g.x, g.y, pc.mask_type, 1, pc.mask)",
               "n64_mask(g.x, g.y, pc.mask_type, 2, pc.mask)"):
        if ch not in main:
            fail("n64_tv.comp: the beam and the mask are not each channel's (%s)" % ch)

    framegen = (VK / "vk_framegen.cpp").read_text(encoding="utf-8")
    for inc in ('#include "vk_n64.h"', '#include "shaders/n64_tv_comp_spv.h"'):
        if inc not in framegen:
            fail("vk_framegen.cpp does not %s" % inc)
    init = block(framegen, "bool init_tv() {")
    if "make_pipe(scale.tv, N64_TV_COMP_SPV, sizeof N64_TV_COMP_SPV, {S, I, S, S}, 48)" not in init or "init_scale()" not in init:
        fail("init_tv: the TV's pipeline is not n64_tv.comp's, with its four bindings and 48 bytes of push constants")
    scale = block(framegen, "VkImage framegen_scale(")
    tv = block(scale, "if (!pq && n64_tv_now(pq) && init_tv()) {")
    in_order(scale, ["if (!pq && n64_tv_now(pq) && init_tv()) {", "const bool fsr1 = opts.upscale == 3"],
             "framegen_scale: the TV no longer runs before AMD FSR 1 and the filter")
    in_order(tv, ["const n64_rules::AnimFrame f = n64_anim();", "const uint32_t smw = std::max(1u, source.w / 8), smh = std::max(1u, source.h / 8);",
                  "pass(cmd, filter, {{src, scale.linear}, {scale.small.view, VK_NULL_HANDLE}, {src, scale.linear}}, smw, smh, &sp, sizeof sp);",
                  "if (wide.side) {", "picture = scale.tv_img.view;", "const int mask = n64_rules::mask_shown(look.mask, dh);",
                  "n64_screen_drawn(look.curvature, f.scale_x, f.scale_y);", "const VkImageView menu = menu_tv_layer(cmd);",
                  "struct { float lines, scan, mask, bleed, glow, curve, saturation; int mask_type; float anim_x, anim_y, flash; int menu; } tp{",
                  "(float)n64_rules::kTvLines, n64_rules::scanline_strength(look.scanlines, dh), look.mask_strength,",
                  "n64_rules::tv_bleed_uv(look.bleed, source.w, source.h), look.glow, look.curvature, look.saturation, mask,",
                  "f.scale_x, f.scale_y, f.flash, menu ? 1 : 0};",
                  "if (menu) {", "tp.menu = 2;",
                  "pass(cmd, scale.tv, {{picture, scale.linear}, {scale.small.view, VK_NULL_HANDLE}, {picture, scale.linear}, {menu, scale.linear}},",
                  "smw, smh, &tp, sizeof tp);", "tp.menu = 1;",
                  "pass(cmd, scale.tv, {{picture, scale.linear}, {scale.scaled.view, VK_NULL_HANDLE}, {scale.small.view, scale.linear},",
                  "{menu ? menu : scale.small.view, scale.linear}}, dw, dh, &tp, sizeof tp);",
                  "if (f.done && now != told) {",
                  "return scale.scaled.image;"],
             "framegen_scale's TV: the 1/8 copy, the menu sides first, the screen's scanlines and mask, the bleed, the pass, its image")
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    # ((11-22) the options under the TV: drawn into ImGui's background list and the layer; the rest over the window after)
    layer = block(menu, "VkImageView menu_tv_layer(VkCommandBuffer cmd) {")
    in_order(layer, ["if (!on || !n64_screen_place(&x, &y, &pw, &ph, &w, &h)) return VK_NULL_HANDLE;",
                     "if (s.start || !(s.open || s.game_tab || s.mods_row) || bugshot_state() == 1 || dev.hdr || !ui::begin(w, h))",
                     "draw_overlays(w, h, s, ImGui::GetBackgroundDrawList());", "ui::record_layer(cmd, x, y, pw, ph);",
                     "tv_drawn = true, tv_layer = layer != VK_NULL_HANDLE"],
             "menu_tv_layer: the options are not drawn under the TV only while they show, into the background list and the layer")
    record = block(menu, "void menu_record(VkCommandBuffer cmd, uint32_t index, uint32_t w, uint32_t h) {")
    in_order(record, ["if (tv_drawn) {", "bugshot_record(cmd, index, w, h);", "ui::record_rest(cmd, index, w, h);", "return;",
                      "draw_overlays(w, h, s, nullptr);"],
             "menu_record: the rest of a frame drawn under the TV is not drawn over the window, or the frame as before is gone")
    tail = record.rstrip()[-400:]
    if not record.rstrip().endswith("ui::record(cmd, index, w, h);\n}") or tail.find("draw_overlays(w, h, s, nullptr);") < 0:
        fail("menu_record: the frame as before no longer ends drawn over the window")
    overlays = block(menu, "void draw_overlays(uint32_t w, uint32_t h, const Showing& s, ImDrawList* under) {")
    for need in ("if (under) m.d = under;", "if (s.open) draw_menu(m, full && !over_row);", "if (s.game_tab) draw_game_tab(m);",
                 "else if (s.mods_row) draw_mods_row_shut(m);", "draw_fps(c, ", "if (s.note) draw_notice(c);"):
        if need not in overlays:
            fail("draw_overlays: %s is gone (the options under the TV, the counter and the notice over it)" % need)
    imgui = (VK / "vk_imgui.cpp").read_text(encoding="utf-8")
    rl = block(imgui, "VkImageView record_layer(VkCommandBuffer cmd, uint32_t x, uint32_t y, uint32_t w, uint32_t h) {")
    in_order(rl, ["part_of({ImGui::GetBackgroundDrawList()}, (float)x, (float)y, w, h);", "ca.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;",
                  "ImGui_ImplVulkan_RenderDrawData(&d, cmd);", "VK_IMAGE_LAYOUT_GENERAL, VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT",
                  "return layer.sample;"],
             "record_layer: the background list is not drawn into a cleared layer at the picture's place, GENERAL for the TV's pass")
    if "ii.ImageCount = 8;" not in imgui:
        fail("vk_imgui.cpp: the backend's vertex buffers are not enough for two draws a frame over three frames in flight")
    # ((11-22) the game's own menus' mouse under the curve: the renderer's screen_point, last of its table, at version 19 (16-18 ultrawide's on next/update))
    api = (VK / "vk_api.h").read_text(encoding="utf-8")
    if not re.search(r"void \(\*screen_point\)\(int \*x, int \*y, int w, int h\);\s*\} MkwVkRenderer;", api) or \
            "#define MKWVK_API_VERSION 19" not in api:
        fail("vk_api.h: MkwVkRenderer has no screen_point last, at version 19")
    if "void rx_screen_point(int *x, int *y, int w, int h) { if (vk && vk->screen_point) vk->screen_point(x, y, w, h); }" not in \
            (ROOT / "host" / "rx_backend.c").read_text(encoding="utf-8"):
        fail("host/rx_backend.c: rx_screen_point does not ask the renderer")
    oot = block((ROOT / "host" / "oot_menu.c").read_text(encoding="utf-8"), "static void mouse_tick_locked(Ctx *c, uint64_t screen) {")
    in_order(oot, ["const int got = hos_mouse_game_pointer(&px, &py, &w, &h, &pressed, &wheel);", "if (!got) return;",
                   "rx_screen_point(&px, &py, w, h);", "hit.x = (float)(px - w / 2) * scale"],
             "host/oot_menu.c: the game's menus' cursor is not taken through the TV's curve before it is tested")
    present = block((VK / "vk_replay.cpp").read_text(encoding="utf-8"), "void present_image(")
    in_order(present, ["n64_screen_begin(rect.x, rect.y, rect.w, rect.h, dev.swap_extent.width, dev.swap_extent.height);",
                       "framegen_scale(f.cmd, view, src, sw, sh, crop, rect.w, rect.h)", "n64_screen_end();",
                       "menu_record(f.cmd, index, dev.swap_extent.width, dev.swap_extent.height);"],
             "present_image: the TV's screen is not begun before the window pass and ended after it, before the overlays")
    note = block(menu, "void menu_note_present_sizes(")
    if "const int filter = ur::tv_filter(ur::window_filter(picture_w, picture_h, place.w, place.h, native_hdr), n64_tv_now(native_hdr));" not in note:
        fail("menu_note_present_sizes: the filter the present takes is not tv_filter's over window_filter's")
    if "opts.upscale = std::min(std::max(atoi(e), 0), 3);" not in menu:
        fail("RX_VK_UPSCALE can name the TV's filter value (it stops at 3)")
    rows = (VK / "upscaler_rows.h").read_text(encoding="utf-8")
    if "constexpr int kTvFilter = 4;" not in rows or "inline int tv_filter(int filter, bool tv) { return tv ? kTvFilter : filter; }" not in rows:
        fail("upscaler_rows.h: kTvFilter or tv_filter is gone")
    n64 = (VK / "vk_n64.cpp").read_text(encoding="utf-8")
    if "bool n64_tv_now(bool native_pq) { return n64_rules::tv_draws(n64_look(), n64_anim(), native_pq, dlssg::active()); }" not in n64:
        fail("vk_n64.cpp: n64_tv_now does not ask n64_rules.h tv_draws with the switch and DLSS frame generation")
    # ((step 8) the switch: ticked once a present beside the texture blur's, with HDR Native's picture; the look the preset shown)
    tick = block(n64, "void n64_tick(bool native_pq) {")
    for need in ("switch_rule.at(t, n64_preset(), anim_on() && !native_pq && !dlssg::active());", "anim_now = now.frame;",
                 "shown_now.store(now.shown, std::memory_order_relaxed);"):
        if need not in tick:
            fail("n64_tick: %s is gone" % need)
    if 'env_number("RX_VK_N64_TV_ANIM", 1) != 0' not in n64 or "n64_rules::look_of(n64_shown()," not in n64:
        fail("vk_n64.cpp: RX_VK_N64_TV_ANIM is not read, or the look is not the preset shown")
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    if "        upscale_lod_tick();" not in replay or "n64_tick(present_native_pq.load(std::memory_order_relaxed));" not in replay or \
            replay.index("        upscale_lod_tick();") > replay.index("n64_tick(present_native_pq.load("):
        fail("vk_replay.cpp: the switch is not ticked once a present, after the texture blur's tick")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if "`RX_VK_N64_TV=0` leaves it out" not in docs or "`RX_VK_N64_MASK=<0..4>`" not in docs or "`RX_VK_N64_TV_ANIM=0`" not in docs or \
            "`RX_VK_N64_TV_MENU=0`" not in docs:
        fail("docs/development.md: the TV's switches are not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--glslang", default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    glslang = args.glslang or shutil.which("glslangValidator")
    if args.write:
        if not glslang:
            fail("--write needs glslangValidator")
        with tempfile.TemporaryDirectory(prefix="n64-tv-") as tmp:
            HEADER.write_bytes(source_line() + compiled(glslang, tmp))
        print("wrote %s" % HEADER.relative_to(ROOT))
    check_sources()
    with tempfile.TemporaryDirectory(prefix="n64-tv-") as tmp:
        cpp, exe = Path(tmp) / "n64_tv_test.cpp", Path(tmp) / "n64-tv.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I" + str(VK), str(cpp),
                        "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            fail("N64 Classic's TV, per pixel")
    if not HEADER.exists():
        fail("n64_tv_comp_spv.h is missing: run with --write")
    header = HEADER.read_bytes().replace(b"\r\n", b"\n")
    first, _, rest = header.partition(b"\n")
    if first + b"\n" != source_line():
        fail("n64_tv_comp_spv.h was not made from n64_tv.comp, n64_common.glsl and n64_tv.glsl as they are now: run with --write")
    if glslang:
        named = rest.split(b"\n", 1)[0].decode("ascii", "replace").strip().lstrip("/ ").strip()
        if glslang_version(glslang) == named:
            with tempfile.TemporaryDirectory(prefix="n64-tv-") as tmp:
                if compiled(glslang, tmp) != rest:
                    fail("n64_tv_comp_spv.h is not n64_tv.comp compiled: run with --write")
            print("(the SPIR-V header is its source compiled, byte for byte)")
        else:
            print("(glslangValidator is not version %s: the header was not compiled again)" % named)
    else:
        print("(glslangValidator is not on the PATH: the header's hash was checked, not its bytes)")
    print("PASS: N64 Classic's TV, per pixel and in the window pass")


if __name__ == "__main__":
    main()
