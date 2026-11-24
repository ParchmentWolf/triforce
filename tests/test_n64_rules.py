"""N64 Classic's rules (gpu/vk/n64_rules.h) and its 3D pass's per-pixel maths (gpu/vk/shaders/n64_common.glsl). No game,
no GPU. Step 1 of n64-classic-mode-plan.md: nothing in the renderer calls them yet.

Compiled and run:

- the N64 Classic row (Off, Faithful, Remembered) and RX_VK_N64 over it;
- the Remembered page's rows: their keys (unique, n64_rem_), ranges, steps and defaults, a saved value brought back to its
  row, the rows shown fixed while they have nothing to do (Dither with full colour, the TV's rows with the TV off, Mask
  strength with no mask);
- the looks: Faithful's fixed values (20 frames a second, 240 lines, 15-bit colour with the full dither, +2.5 texture
  blur, the TV), Remembered's defaults, Faithful ignoring the page, Copy Faithful giving Remembered exactly Faithful's
  look, Reset giving the defaults, the lab's switches over either;
- the 3D grid's size for the host's 4:3, 16:9 and 21:9 pictures; the TV's colour bleed in the picture's widths by its
  shape; the texture blur under a card's limit, and the draws
  that are the scene for it (a scene's size and shape for the picture: the dynamic resolution's sizes, not the shadow maps,
  the HUD or a quarter-size buffer); the scanlines' strength and the mask's Auto by the picture's height on the screen;
- what the mode stands in front of while it is on (the Upscaler, the Anti-aliasing, Sharpness) and when each pass runs
  (no 3D pass on RenoDX's RGBA16F scene, no TV on HDR Native's PQ picture or under DLSS frame generation);
- the frame rate the host is told and the rate the frames are then paced by under every cap;
- F7 between Off and the last preset, and the TV's half-second switch with the change at its middle: the preset shown
  through a switch (none at a start, a new choice while it closes, another after the middle, at once where none can be
  drawn), and the TV pass drawing it over any look;
- n64_common.glsl, compiled as C++ over a small GLSL stand-in (it is written in what the two share, as aa_common.glsl is):
  the 4 x 4 Bayer cell is each of 0 to 15 once, its thresholds centred; every level of 5 and 6 bits comes back exactly at
  any dither strength; a value between levels averages to itself over a cell; the output is always a level, inside 0..1;
  and for step 2's pass (shaders/n64_3d.comp): the sRGB curve both ways, a channel kept at 15-bit colour on a display
  level (white, HDR's highlights and full colour as they are, below black and NaN black), every grid row in order with 4
  to 6 output rows each, and the column's place along a line.

With glslangValidator on the PATH, n64_common.glsl also compiles as GLSL inside a stand-in compute shader.

    python -I -B tests/test_n64_rules.py [--cxx clang++]
"""
import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
SHADERS = VK / "shaders"

DRIVER = r'''
#include "n64_rules.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>

// (just enough of GLSL for n64_common.glsl, in a namespace of its own)
namespace glsl {
static float floor(float a) { return std::floor(a); }
static float clamp(float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; }
#include "shaders/n64_common.glsl"
}  // namespace glsl

using namespace mkwvk::n64_rules;
namespace ur = mkwvk::upscaler_rows;
namespace ar = mkwvk::aa_rows;

static int checks, fails;
static void want(bool ok, const char* what) {
    checks++;
    if (!ok) fails++, std::printf("FAIL %s\n", what);
}
static bool near(float a, float b, float eps = 1e-6f) { return std::fabs(a - b) <= eps; }

static void row_and_rows() {
    want(chosen(0, -1) == OFF && chosen(1, -1) == FAITHFUL && chosen(2, -1) == REMEMBERED, "the row's own values");
    want(chosen(7, -1) == OFF && chosen(-3, -1) == OFF, "a value past the row is Off");
    want(chosen(0, 2) == REMEMBERED && chosen(2, 0) == OFF && chosen(1, 9) == OFF, "RX_VK_N64 over the row");
    want(!std::strcmp(name(OFF), "Off") && !std::strcmp(name(FAITHFUL), "Faithful") &&
         !std::strcmp(name(REMEMBERED), "Remembered") && !std::strcmp(name(5), "Off"), "the row's names");

    bool keys = true;
    for (int i = 0; i < kRows; i++) {
        if (std::strncmp(kSpec[i].key, "n64_rem_", 8)) keys = false;
        for (int j = 0; j < i; j++)
            if (!std::strcmp(kSpec[i].key, kSpec[j].key)) keys = false;
        const RowSpec& s = kSpec[i];
        if (s.lo > s.hi || s.step <= 0 || s.def < s.lo || s.def > s.hi || (s.def - s.lo) % s.step || (s.hi - s.lo) % s.step)
            keys = false;
    }
    want(keys, "each row's key is its own and n64_rem_, its default on its steps inside its range");
    want(std::strncmp(kLastKey, "n64_rem_", 8) != 0, "F7's last preset has a key of its own");

    const Rows d = defaults();
    bool defs = true;
    for (int i = 0; i < kRows; i++) defs &= d.v[i] == kSpec[i].def;
    want(defs, "Reset: every row at its default");
    const Rows f = clamped(kFaithful);
    bool on_rows = true;
    for (int i = 0; i < kRows; i++) on_rows &= f.v[i] == kFaithful.v[i];
    want(on_rows, "Faithful's values are values the page's rows can hold (Copy Faithful copies them as they are)");

    want(clamp_row(FPS, 9) == 4 && clamp_row(FPS, -2) == 0, "the frame rate brought back to its row");
    want(clamp_row(SCANLINES, 37) == 35 && clamp_row(SCANLINES, 200) == 80 && clamp_row(SCANLINES, -5) == 0,
         "scanlines: on a step of 5, inside 0..80");
    want(clamp_row(MASK_STRENGTH, 0) == 5 && clamp_row(SATURATION, 151) == 150 && clamp_row(SATURATION, 52) == 50,
         "mask strength and saturation inside their rows, on their steps");
    want(clamp_row(-1, 3) == 0 && clamp_row(kRows, 3) == 0, "no row: 0");
    Rows wild{};
    for (int i = 0; i < kRows; i++) wild.v[i] = 999;
    const Look w = look_of(REMEMBERED, wild);
    want(w.on && w.fps == 17 && w.lines == 720 && w.colour_bits == 0 && near(w.lod_bias, 3.0f) && w.tv &&
         near(w.scanlines, 0.8f) && w.mask == MASK_SHADOW && near(w.saturation, 1.5f),
         "a file's values past every row: each row's last value, nothing read past a table");

    Rows r = d;
    want(row_fixed(r, DITHER), "Dither fixed while Colour is Full");
    r.v[COLOUR] = 0;
    want(!row_fixed(r, DITHER), "Dither changeable with 15-bit colour");
    r.v[TV] = 0;
    bool tv_rows = true;
    for (int i = SCANLINES; i <= SATURATION; i++) tv_rows &= row_fixed(r, i);
    want(tv_rows, "the TV's rows fixed while CRT TV is off");
    want(!row_fixed(r, FPS) && !row_fixed(r, LINES) && !row_fixed(r, COLOUR) && !row_fixed(r, BLUR) && !row_fixed(r, TV),
         "the frame rate, the 3D's rows and CRT TV itself never fixed");
    r.v[TV] = 1, r.v[MASK] = MASK_OFF;
    want(row_fixed(r, MASK_STRENGTH) && !row_fixed(r, MASK), "Mask strength fixed with no mask");
}

static void looks() {
    const Look f = look_of(FAITHFUL, defaults());
    want(f.on && f.fps == 20 && f.lines == 240 && f.colour_bits == 5 && near(f.dither, 1.0f) && near(f.lod_bias, 2.5f),
         "Faithful's 3D: 20 frames a second, 240 lines, 15-bit colour, the full dither, +2.5 blur");
    want(f.tv && near(f.scanlines, 0.6f) && f.mask == MASK_AUTO && near(f.mask_strength, 0.3f) && near(f.bleed, 3.0f) &&
         near(f.glow, 0.1f) && near(f.curvature, 0.03f) && near(f.saturation, 1.0f),
         "Faithful's TV: 60% scanlines, Auto's mask at 30%, a composite cable's bleed, 10% glow, curved, the game's colour");
    const Look m = look_of(REMEMBERED, defaults());
    want(m.on && m.fps == 0 && m.lines == 480 && m.colour_bits == 0 && m.dither == 0.0f && near(m.lod_bias, 1.5f),
         "Remembered's 3D: the cap's rate, 480 lines, full colour, no dither, +1.5 blur");
    want(m.tv && near(m.scanlines, 0.35f) && m.mask == MASK_AUTO && near(m.mask_strength, 0.15f) && near(m.bleed, 1.5f) &&
         near(m.glow, 0.25f) && near(m.curvature, 0.015f) && near(m.saturation, 1.1f), "Remembered's TV defaults");

    Rows odd = defaults();
    odd.v[FPS] = 1, odd.v[LINES] = 3, odd.v[TV] = 0, odd.v[BLUR] = 0;
    want(same(look_of(FAITHFUL, odd), f), "Faithful ignores the Remembered page");
    want(!same(look_of(REMEMBERED, odd), m), "Remembered follows its page");
    Rows copied = kFaithful;   // (Copy Faithful)
    want(same(look_of(REMEMBERED, copied), f), "after Copy Faithful, Remembered looks exactly as Faithful does, rate and all");
    want(same(look_of(REMEMBERED, defaults()), m), "after Reset, Remembered's defaults");

    Rows full = defaults();
    full.v[COLOUR] = 2, full.v[DITHER] = 2;
    want(look_of(REMEMBERED, full).dither == 0.0f, "full colour: no dither, whatever the Dither row holds");
    Rows notv = defaults();
    notv.v[TV] = 0;
    const Look n = look_of(REMEMBERED, notv);
    want(!n.tv && n.scanlines == 0.0f && n.mask == MASK_OFF && n.mask_strength == 0.0f && n.bleed == 0.0f && n.glow == 0.0f &&
         n.curvature == 0.0f && n.saturation == 1.0f && n.lines == 480 && near(n.lod_bias, 1.5f),
         "CRT TV off: none of the TV, the 3D as it was");
    const Look off = look_of(OFF, defaults());
    want(!off.on && fps(off) == 0 && lod_bias(off, 16.0f) == 0.0f && !three_d_runs(off, false) && !tv_runs(off, false, false),
         "Off: nothing at all");

    Env e;
    want(same(with_env(f, e), f), "no switch set: the look as it is");
    e.lines = 360, e.tv = 0, e.fps = 0, e.lod = 0.0f, e.mask = MASK_APERTURE;
    const Look fe = with_env(f, e);
    want(fe.lines == 360 && !fe.tv && fe.fps == 0 && fe.lod_bias == 0.0f && fe.mask == MASK_APERTURE,
         "the lab's switches over Faithful's fixed look");
    want(!with_env(off, e).on, "the switches do not turn the mode on");
}

static void grid_and_screen() {
    const auto is = [](Grid g, uint32_t w, uint32_t h) { return g.w == w && g.h == h; };
    want(is(grid(240, 1920, 1440), 320, 240), "4:3 at 240 lines: 320 x 240");
    want(is(grid(240, 2560, 1440), 427, 240) && is(grid(240, 2048, 1152), 427, 240), "16:9 at 240 lines: 427 x 240");
    want(is(grid(240, 3416, 1440), 569, 240), "the host's 21:9 picture (3416 x 1440) at 240 lines: 569 x 240");
    want(is(grid(480, 1920, 1440), 640, 480) && is(grid(480, 2560, 1440), 853, 480) && is(grid(480, 3416, 1440), 1139, 480),
         "480 lines: 640, 853, 1139");
    want(is(grid(720, 1280, 400), 1280, 400), "never more lines than the picture");
    want(is(grid(240, 0, 1440), 0, 0) && is(grid(0, 2560, 1440), 0, 0) && is(grid(240, 2560, 0), 0, 0), "a size not known: none");

    const Look f = look_of(FAITHFUL, defaults());
    want(near(lod_bias(f, 16.0f), 2.5f) && near(lod_bias(f, 2.0f), 2.0f) && lod_bias(f, 0.0f) == 0.0f,
         "the blur under the card's limit (Vulkan's least, 2, cuts Faithful's 2.5)");
    want(near(scanline_strength(0.6f, 1440), 0.6f) && near(scanline_strength(0.6f, 2160), 0.6f), "1440 and 2160: full");
    want(near(scanline_strength(0.6f, 720), 0.6f) && near(scanline_strength(0.6f, 800), 0.6f),
         "the Steam Deck's 720 and 800: 3 a line and more, full");
    want(near(scanline_strength(0.6f, 600), 0.3f) && scanline_strength(0.6f, 360) == 0.0f && scanline_strength(0.6f, 0) == 0.0f,
         "2.5 pixels a line: half; 1.5: none");
    want(mask_shown(MASK_AUTO, 800) == MASK_OFF && mask_shown(MASK_AUTO, 1080) == MASK_OFF, "Auto: no mask at 800 or 1080");
    want(mask_shown(MASK_AUTO, 1440) == MASK_SLOT && mask_shown(MASK_AUTO, 2160) == MASK_SLOT, "Auto: the slot mask at 1440 and up");
    want(mask_shown(MASK_APERTURE, 800) == MASK_APERTURE && mask_shown(MASK_SHADOW, 1080) == MASK_SHADOW,
         "a picked mask on any screen");
    want(mask_shown(MASK_OFF, 2160) == MASK_OFF && mask_shown(9, 2160) == MASK_OFF, "Off and a value past the row: none");

    // (step 4) the colour bleed in the picture's widths: a pixel of the 240-line grid, 1/427 of a 16:9 picture, 1/320 of 4:3
    want(near(tv_bleed_uv(3.0f, 1920, 1440), 3.0f / 320.0f) && near(tv_bleed_uv(3.0f, 2560, 1440), 3.0f * 1440.0f / (240.0f * 2560.0f)) &&
         near(tv_bleed_uv(1.5f, 3416, 1440), 1.5f * 1440.0f / (240.0f * 3416.0f)), "the bleed in the picture's widths, by its shape");
    want(tv_bleed_uv(0.0f, 2560, 1440) == 0.0f && tv_bleed_uv(3.0f, 0, 1440) == 0.0f && tv_bleed_uv(3.0f, 2560, 0) == 0.0f,
         "no bleed, or a size not known: none");

    // (step 3) the draws that are the scene for the texture blur, by their size and shape for the picture the pass drew
    want(scene_draw(1536, 864, 2048, 1152) && scene_draw(2048, 1152, 2560, 1440) && scene_draw(1707, 960, 2560, 1440),
         "the game's dynamic resolution's sizes for the picture: the scene");
    want(scene_draw(854, 480, 2560, 1440), "a third of the picture (Ultra Performance's share): the scene");
    want(scene_draw(1440, 1080, 1920, 1440) && scene_draw(2560, 1080, 3416, 1440), "the host's 4:3 and 21:9 pictures' scenes");
    want(!scene_draw(2560, 1440, 2560, 1440), "the picture's own size (the HUD, the output's passes): not the scene");
    want(!scene_draw(1024, 1024, 2560, 1440) && !scene_draw(2048, 2048, 2560, 1440) && !scene_draw(1024, 1024, 1920, 1440),
         "square shadow maps: not the scene, at 16:9 or at 4:3");
    want(!scene_draw(640, 360, 2560, 1440), "a quarter of the picture, past a third: not the scene");
    want(!scene_draw(1280, 540, 2560, 1440), "half its width, another shape: not the scene");
    want(!scene_draw(2600, 1440, 2560, 1440), "wider than the picture: not the scene");
    want(!scene_draw(1536, 864, 0, 0) && !scene_draw(0, 864, 2048, 1152), "a size not known: not the scene");
}

static void in_front_and_passes() {
    want(upscaler(FAITHFUL, ur::DLSS) == ur::GAME && upscaler(REMEMBERED, ur::FSR4_AA) == ur::GAME &&
         upscaler(OFF, ur::DLSS) == ur::DLSS, "DLSS and FSR step aside while the mode is on, and only then");
    want(anti_aliasing(FAITHFUL, ar::SMAA) == ar::OFF && anti_aliasing(OFF, ar::FXAA) == ar::FXAA,
         "the game's SMAA left out while the mode is on");
    want(sharpness(REMEMBERED, 50) == 0 && sharpness(OFF, 50) == 50, "no window Sharpness while the mode is on");
    want(fixes_rows(FAITHFUL) && fixes_rows(REMEMBERED) && !fixes_rows(OFF), "the overridden rows fixed while it is on");
    const Look f = look_of(FAITHFUL, defaults());
    want(three_d_runs(f, false) && !three_d_runs(f, true), "the 3D pass: not on RenoDX's RGBA16F scene");
    want(tv_runs(f, false, false) && !tv_runs(f, true, false) && !tv_runs(f, false, true),
         "the TV: not on HDR Native's PQ picture, not under DLSS frame generation");
    Rows notv = defaults();
    notv.v[TV] = 0;
    want(!tv_runs(look_of(REMEMBERED, notv), false, false) && three_d_runs(look_of(REMEMBERED, notv), false),
         "CRT TV off: the 3D pass alone");
}

static void frame_rate() {
    const Look f = look_of(FAITHFUL, defaults());
    bool twenty = true;
    for (int cap : {30, 40, 45, 60, 90, 120, 144, 165, 240}) twenty &= paced(fps(f), cap) == 20;
    want(fps(f) == 20 && twenty, "Faithful: 20 under every cap the game offers");
    const Look m = look_of(REMEMBERED, defaults());
    want(fps(m) == 0 && paced(fps(m), 60) == 60 && paced(fps(m), 144) == 144, "Remembered's default: the cap's own rate");
    Rows r = defaults();
    r.v[FPS] = 1;   // (60)
    want(paced(fps(look_of(REMEMBERED, r)), 45) == 45 && paced(fps(look_of(REMEMBERED, r)), 120) == 60,
         "a Remembered 60: 45 under a cap of 45, 60 under 120");
    r.v[FPS] = 4;
    want(fps(look_of(REMEMBERED, r)) == 17 && paced(17, 60) == 17, "17, the cartridge on a 50 Hz TV");
    r.v[FPS] = 2;
    want(fps(look_of(REMEMBERED, r)) == 30, "30");
    want(paced(fps(look_of(OFF, defaults())), 60) == 60, "Off: the cap's");
}

static void toggle_and_anim() {
    Toggle t;
    want(t.pressed(OFF) == FAITHFUL, "F7 from Off the first time: Faithful");
    want(t.pressed(FAITHFUL) == OFF, "F7 with a preset on: Off");
    t.noted(REMEMBERED);
    want(t.pressed(OFF) == REMEMBERED, "F7 from Off: the last preset chosen on the row");
    want(t.pressed(REMEMBERED) == OFF && t.pressed(OFF) == REMEMBERED, "and back again");
    t.noted(OFF);
    want(t.last == REMEMBERED, "Off chosen on the row is no preset to come back to");

    want(anim(-0.1f).done && !anim(-0.1f).after, "before a switch: the picture as it is");
    const AnimFrame start = anim(0.0f), end = anim(kAnimSeconds);
    want(!start.done && near(start.scale_x, 1.0f) && near(start.scale_y, 1.0f) && start.flash == 0.0f && !start.after,
         "the switch starts from the whole picture");
    want(end.done && end.after && near(end.scale_x, 1.0f) && near(end.scale_y, 1.0f) && end.flash == 0.0f,
         "and is over at half a second, with the new look whole");
    want(!anim(kAnimSeconds / 2 - 0.001f).after && anim(kAnimSeconds / 2).after, "the new look from the middle on");
    const AnimFrame mid = anim(kAnimSeconds / 2);
    want(near(mid.scale_x, kAnimDot) && near(mid.scale_y, kAnimLine) && near(mid.flash, 1.0f), "a bright dot at the middle");
    bool closing = true, opening = true;
    AnimFrame prev = start;
    for (int i = 1; i <= 100; i++) {
        const AnimFrame a = anim(kAnimSeconds / 2 * i / 100.0f);
        closing &= a.scale_y <= prev.scale_y + 1e-6f && a.scale_x <= prev.scale_x + 1e-6f;
        prev = a;
    }
    for (int i = 1; i <= 100; i++) {
        const AnimFrame a = anim(kAnimSeconds / 2 + kAnimSeconds / 2 * i / 100.0f);
        opening &= a.scale_y + 1e-6f >= prev.scale_y && a.scale_x + 1e-6f >= prev.scale_x;
        prev = a;
    }
    want(closing && opening, "it closes to the dot, then opens from it, never back and forth");

    // (step 8) the switch, once a present: the preset shown, and the TV's frame of it
    Switch sw;
    Switch::Now n = sw.at(10.0, FAITHFUL, true);
    want(n.shown == FAITHFUL && n.frame.done, "the first present: the preset as it is, no switch (a start does not switch the TV on)");
    want(sw.at(10.1, FAITHFUL, true).frame.done, "nothing chosen anew: nothing runs");
    n = sw.at(11.0, OFF, true);
    want(n.shown == FAITHFUL && !n.frame.done && !n.frame.after, "F7 off: the switch begins, Faithful still shown");
    want(sw.at(11.2, OFF, true).shown == FAITHFUL && sw.at(11.25, OFF, true).shown == OFF, "Off from the middle on");
    n = sw.at(11.5, OFF, true);
    want(n.shown == OFF && n.frame.done, "over at half a second: Off, nothing running");
    sw.at(12.0, REMEMBERED, true);
    n = sw.at(12.1, FAITHFUL, true);
    want(n.shown == OFF && !n.frame.done && sw.to == FAITHFUL && sw.t0 == 12.0,
         "a new choice while the picture still closes: what opens instead, the same switch");
    want(sw.at(12.3, FAITHFUL, true).shown == FAITHFUL, "and it opens on it");
    n = sw.at(12.4, REMEMBERED, true);
    want(n.shown == FAITHFUL && sw.from == FAITHFUL && sw.to == REMEMBERED && sw.t0 == 12.4,
         "a new choice after the middle: a new switch from what is shown");
    want(sw.at(12.9, REMEMBERED, true).shown == REMEMBERED && sw.at(12.9, REMEMBERED, true).frame.done, "and over");
    n = sw.at(13.0, OFF, false);
    want(n.shown == OFF && n.frame.done, "no switch to draw (RX_VK_N64_TV_ANIM=0, HDR Native, DLSS frame generation): at once");
    Look off = look_of(OFF, defaults());
    want(!tv_draws(off, AnimFrame{}, false, false) && tv_draws(off, anim(0.1f), false, false),
         "the TV pass draws the switch over an Off look, and nothing once it is over");
    want(!tv_draws(off, anim(0.1f), true, false) && !tv_draws(off, anim(0.1f), false, true) &&
         tv_draws(look_of(FAITHFUL, defaults()), AnimFrame{}, false, false), "never on HDR Native's picture nor under DLSS frame generation");
}

static void glsl_maths() {
    using namespace glsl;
    bool perm = true;
    int seen = 0;
    float sum = 0.0f, lo = 1.0f, hi = -1.0f;
    for (int y = 0; y < 4; y++)
        for (int x = 0; x < 4; x++) {
            const int b = n64_bayer4(x, y);
            if (b < 0 || b > 15 || (seen & (1 << b))) perm = false;
            seen |= 1 << (b & 15);
            const float d = n64_dither_offset(x, y);
            sum += d, lo = d < lo ? d : lo, hi = d > hi ? d : hi;
        }
    want(perm && seen == 0xffff, "the 4 x 4 cell holds each of 0 to 15 once");
    want(near(sum, 0.0f, 1e-5f) && near(lo, -15.0f / 32.0f) && near(hi, 15.0f / 32.0f), "its thresholds centred, -15/32 to 15/32");
    want(n64_bayer4(0, 0) == 0 && n64_bayer4(1, 0) == 8 && n64_bayer4(0, 1) == 12 && n64_bayer4(1, 1) == 4 &&
         n64_bayer4(2, 2) == 1, "the Bayer matrix's own order");
    want(n64_dither_offset(4, 0) == n64_dither_offset(0, 0) && n64_dither_offset(5, 6) == n64_dither_offset(1, 2),
         "the cell repeats every 4 grid pixels");

    bool levels = true;
    for (int bits : {5, 6}) {
        const int top = (1 << bits) - 1;
        for (int k = 0; k <= top; k++)
            for (float s : {0.0f, 0.5f, 1.0f})
                for (int y = 0; y < 4; y++)
                    for (int x = 0; x < 4; x++)
                        levels &= n64_quantize((float)k / (float)top, bits, s, x, y) == (float)k / (float)top;
    }
    want(levels, "every level of 5 and of 6 bits comes back exactly, at any dither strength, in every cell");

    bool mean = true, on_level = true, nearest = true;
    for (int i = 0; i <= 1000; i++) {
        const float v = i / 1000.0f;
        float total = 0.0f;
        for (int y = 0; y < 4; y++)
            for (int x = 0; x < 4; x++) {
                const float q = n64_quantize(v, 5, 1.0f, x, y);
                total += q;
                on_level &= near(q * 31.0f, std::round(q * 31.0f), 1e-4f) && q >= 0.0f && q <= 1.0f;
            }
        mean &= std::fabs(total / 16.0f - v) <= 1.0f / 16.0f / 31.0f + 1e-6f;
        const float q0 = n64_quantize(v, 5, 0.0f, 3, 1);
        nearest &= std::fabs(q0 - v) <= 0.5f / 31.0f + 1e-6f && near(q0 * 31.0f, std::round(q0 * 31.0f), 1e-4f);
    }
    want(mean, "a value between levels averages to itself over a cell, within a 16th of a step");
    want(on_level, "the output is always one of the 32 levels, inside 0..1");
    want(nearest, "no dither: the nearest level");
    want(n64_quantize(-0.2f, 5, 1.0f, 0, 0) == 0.0f && n64_quantize(1.3f, 5, 1.0f, 3, 3) == 1.0f, "below 0 and past 1: the ends");
    want(n64_quantize(0.123f, 0, 1.0f, 2, 1) == 0.123f && n64_quantize(1.7f, 0, 1.0f, 2, 1) == 1.7f,
         "full colour: the value as it is");

    // (step 2's pass: the sRGB curve both ways, a channel as the grid keeps it, where an output pixel finds the grid)
    bool round = true;
    for (int i = 0; i <= 1000; i++) {
        const float v = i / 1000.0f;
        round &= near(n64_decode(n64_encode(v)), v, 2e-5f) && near(n64_encode(n64_decode(v)), v, 2e-5f);
    }
    want(round && near(n64_encode(0.5f), 0.735357f, 1e-4f), "the sRGB curve, both ways");
    bool kept = true;
    for (int i = 0; i <= 200; i++) {
        const float v = i / 200.0f * 0.999f;
        const float k = n64_keep(v, 5, 1.0f, i & 3, (i >> 2) & 3);
        kept &= near(n64_encode(k) * 31.0f, std::round(n64_encode(k) * 31.0f), 2e-3f) && k >= 0.0f && k <= 1.0f;
    }
    want(kept, "kept at 15-bit colour: every channel on one of the 32 display levels");
    want(n64_keep(0.42f, 0, 1.0f, 1, 1) == 0.42f && n64_keep(1.0f, 5, 1.0f, 1, 1) == 1.0f && n64_keep(3.5f, 5, 1.0f, 0, 0) == 3.5f,
         "full colour, white and light above it (HDR's highlights) as they are");
    want(n64_keep(-0.3f, 5, 1.0f, 0, 0) == 0.0f && n64_keep(std::nanf(""), 5, 1.0f, 0, 0) == 0.0f, "below black, or not a number: black");
    bool bands = true;
    for (int y = 0; y < 1440; y++) bands &= n64_row(y, 240, 1440) == y / 6;
    want(bands, "1440 output rows on 240 grid rows: 6 each, hard edges");
    int first = 0, last = 0, shortest = 99, tallest = 0, height = 0;
    bool climbs = true;
    for (int y = 0; y < 1152; y++) {
        const int r = n64_row(y, 240, 1152);
        if (y == 0) first = r;
        if (y && r != last) {
            climbs &= r == last + 1;
            shortest = height < shortest ? height : shortest, tallest = height > tallest ? height : tallest, height = 0;
        }
        last = r, height++;
    }
    want(first == 0 && last == 239 && climbs && shortest >= 4 && tallest <= 5, "1152 rows on 240: every grid row, in order, 4 or 5 output rows each");
    want(n64_row(2159, 240, 2160) == 239 && n64_row(0, 240, 2160) == 0, "the first and the last output row: the first and the last grid row");
    want(near(n64_column(3, 427, 427), 3.0f) && near(n64_column(0, 320, 1920), -5.0f / 12.0f) &&
         near(n64_column(1919, 320, 1920), 319.0f + 5.0f / 12.0f), "the column: the grid pixel's centre at the same size, inside the grid's edges at 6x");
}

int main() {
    row_and_rows();
    looks();
    grid_and_screen();
    in_front_and_passes();
    frame_rate();
    toggle_and_anim();
    glsl_maths();
    if (fails) std::printf("n64 rules: FAILED (%d of %d checks)\n", fails, checks);
    else std::printf("n64 rules: all %d checks passed\n", checks);
    return fails != 0;
}
'''

STAND_IN_SHADER = '''#version 450
#extension GL_GOOGLE_include_directive : require
#include "n64_common.glsl"
layout(local_size_x = 8, local_size_y = 8) in;
layout(binding = 0, rgba8) uniform writeonly image2D dst;
void main() {
    const ivec2 g = ivec2(gl_GlobalInvocationID.xy);
    imageStore(dst, g, vec4(n64_quantize(0.4, 5, 1.0, g.x, g.y), 0.0, 0.0, 1.0));
}
'''


def check_sources():
    rules = (VK / "n64_rules.h").read_text(encoding="utf-8")
    if re.search(r'#include\s*[<"](vulkan|vk_)', rules):
        raise SystemExit("FAIL: n64_rules.h includes Vulkan or the renderer: its rules are to stay plain")
    common = (SHADERS / "n64_common.glsl").read_text(encoding="utf-8")
    code = "\n".join(line.split("//", 1)[0] for line in common.splitlines())
    if "#version" in code or "[" in code or re.search(r"\.\s*[xyzwrgba]{2,4}\b", code):
        raise SystemExit("FAIL: n64_common.glsl is an include in what GLSL and C++ share: no #version, no arrays, no swizzles")


def check_glsl(tmp):
    glslang = shutil.which("glslangValidator")
    if not glslang:
        print("(glslangValidator is not on the PATH: n64_common.glsl was not compiled as GLSL)")
        return
    comp = Path(tmp) / "stand_in.comp"
    comp.write_text(STAND_IN_SHADER, encoding="utf-8")
    r = subprocess.run([glslang, "-V", "--target-env", "vulkan1.3", "-I" + str(SHADERS), str(comp), "-o", str(Path(tmp) / "s.spv")],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("FAIL: n64_common.glsl does not compile as GLSL:\n" + r.stdout + r.stderr)
    print("(n64_common.glsl compiles as GLSL in a stand-in compute shader)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_sources()
    with tempfile.TemporaryDirectory(prefix="n64-rules-") as tmp:
        cpp, exe = Path(tmp) / "n64_rules_test.cpp", Path(tmp) / "n64-rules.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I" + str(VK), str(cpp),
                        "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: N64 Classic's rules")
        check_glsl(tmp)
    print("PASS: N64 Classic's rules and its 3D pass's per-pixel maths")


if __name__ == "__main__":
    main()
