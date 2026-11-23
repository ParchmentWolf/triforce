/* (Triforce, 11-22) N64 Classic: the Insert menu's N64 Classic row and the Remembered page's rows, as plain functions (the
   plan: n64-classic-mode-plan.md, step 1). What each preset looks like, the grid the 3D pass draws on, the texture blur
   on a card, how strong the scanlines are on a screen, when the mask shows, what the mode stands in front of while it is
   on, the frame rate the host is told, F7, and the TV's switch-off and switch-on. No Vulkan, no menu:
   tests/test_n64_rules.py compiles and runs them. Nothing calls them yet.

   Two presets with two jobs. Faithful is fixed (kFaithful): the 1998 cartridge on a 1998 TV, always 20 frames a second.
   Remembered is the player's own: its rows (Rows) are kept in triforce_options.ini under kSpec's keys, and start as
   kSpec's defaults. Both become a Look the same way (look_of_rows), so the page's Copy Faithful is kFaithful copied into
   the rows and nothing more, and Remembered then looks exactly as Faithful does.

   The per-pixel maths of the 3D pass (the colour depth and the ordered dither) is in shaders/n64_common.glsl, which the
   shaders include and the test compiles as C++. */
#pragma once

#include <cstdint>

#include "aa_rows.h"   // (the Anti-aliasing row's Off, and through it the Upscaler row's values: upscaler_rows.h)

namespace mkwvk::n64_rules {

// ---- the N64 Classic row ----

/// The N64 Classic row (opts.n64_classic, saved as n64_classic; RX_VK_N64 over it). Off by default, as every feature is
enum { OFF = 0, FAITHFUL = 1, REMEMBERED = 2, kPresets = 3 };
inline const char* name(int v) {
    switch (v) {
    case FAITHFUL: return "Faithful";
    case REMEMBERED: return "Remembered";
    default: return "Off";   // (also for a value past the row)
    }
}
/// The row's value as one of its choices, RX_VK_N64=<0..2> over it for a run (env: its number, -1 unset). Anything else is
/// Off
constexpr int chosen(int row, int env) {
    const int v = env >= 0 ? env : row;
    return v >= OFF && v < kPresets ? v : OFF;
}

// ---- the Remembered page's rows ----

/// The page's rows, in the page's order, and their place in Rows
enum Row { FPS, LINES, COLOUR, DITHER, BLUR, TV, SCANLINES, MASK, MASK_STRENGTH, BLEED, GLOW, CURVATURE, SATURATION, kRows };
/// A row's key in the options file, its range, its step and the value it starts at (Remembered's own defaults)
struct RowSpec {
    const char* key;
    int lo, hi, step, def;
};
constexpr RowSpec kSpec[kRows] = {
    {"n64_rem_fps", 0, 4, 1, 0},                 // (kFps: Frame rate cap)
    {"n64_rem_lines", 0, 3, 1, 2},               // (kLines: 480)
    {"n64_rem_colour", 0, 2, 1, 2},              // (kColourBits: Full)
    {"n64_rem_dither", 0, 2, 1, 0},              // (kDither: Off)
    {"n64_rem_blur", 0, 6, 1, 3},                // (halves of a mip level: +1.5)
    {"n64_rem_tv", 0, 1, 1, 1},                  // (On)
    {"n64_rem_scanlines", 0, 80, 5, 35},         // (percent: how dark the gaps between TV lines are)
    {"n64_rem_mask", 0, 4, 1, 0},                // (the Mask enum below: Auto)
    {"n64_rem_mask_strength", 5, 50, 5, 15},     // (percent)
    {"n64_rem_bleed", 0, 2, 1, 1},               // (kBleed: Light)
    {"n64_rem_glow", 0, 50, 5, 25},              // (percent)
    {"n64_rem_curvature", 0, 3, 1, 1},           // (kCurvature: Slight)
    {"n64_rem_saturation", 50, 150, 5, 110},     // (percent)
};
/// What the rows' values stand for. Frame rate: 0 the Frame rate cap row's own rate, else frames a second (20 and 17: the
/// 1998 cartridge on a 60 Hz and on a 50 Hz TV, a third of each)
constexpr int kFps[] = {0, 60, 30, 20, 17};
constexpr int kLines[] = {240, 360, 480, 720};
/// Colour: bits a channel, 0 Full (as it is). 5 is the console's 16-bit picture, 6 the 18 bits of a cheap panel
constexpr int kColourBits[] = {5, 6, 0};
constexpr float kDither[] = {0.0f, 0.5f, 1.0f};
/// Colour bleed: how far the colour (not the brightness) blurs sideways, in pixels of a 320-wide picture (a composite
/// cable's is about 3)
constexpr float kBleed[] = {0.0f, 1.5f, 3.0f};
/// Curvature: the screen's barrel, as a share of the picture at its corners (0 flat)
constexpr float kCurvature[] = {0.0f, 0.015f, 0.03f, 0.05f};
/// The Mask row. Auto: the slot mask on a picture placed 1440 lines tall or more, none below (kMaskAutoLines); a mask the
/// player picks is shown on any screen
enum Mask { MASK_AUTO = 0, MASK_OFF = 1, MASK_APERTURE = 2, MASK_SLOT = 3, MASK_SHADOW = 4 };
/// The texture blur: a row step is half a mip level
constexpr float kBlurStep = 0.5f;

/// The page's values, by Row
struct Rows {
    int v[kRows];
};
/// The rows of values kept as a plain array (vk_menu.h Options's n64_rem), in Row's order
constexpr Rows rows_of(const int* v) {
    Rows r{};
    for (int i = 0; i < kRows; i++) r.v[i] = v ? v[i] : kSpec[i].def;
    return r;
}
/// Remembered as it starts (the page's Reset)
constexpr Rows defaults() {
    Rows r{};
    for (int i = 0; i < kRows; i++) r.v[i] = kSpec[i].def;
    return r;
}
/// Faithful, which is never changed: 20 frames a second, 240 lines, 15-bit colour with the full dither, textures 2.5 mip
/// levels blurrier, the TV on with 60% scanlines, Auto's slot mask at 30%, a composite cable's bleed, 10% glow, a curved
/// screen, the game's own saturation. The page's Copy Faithful copies it into Remembered's rows
constexpr Rows kFaithful = {{3, 0, 0, 2, 5, 1, 60, MASK_AUTO, 30, 2, 10, 2, 100}};

/// A row's value as the row has it: inside its range, on its steps (a hand-edited or older file's value is brought back to
/// the row, rounded down to a step)
constexpr int clamp_row(int row, int v) {
    if (row < 0 || row >= kRows) return 0;
    const RowSpec& s = kSpec[row];
    if (v < s.lo) return s.lo;
    if (v > s.hi) return s.hi;
    return s.lo + (v - s.lo) / s.step * s.step;
}
constexpr Rows clamped(Rows r) {
    for (int i = 0; i < kRows; i++) r.v[i] = clamp_row(i, r.v[i]);
    return r;
}
/// A row with nothing to do just now, shown fixed (greyed, no arrows; Left and Right leave it alone): Dither while Colour is
/// Full (nothing to dither), the TV's rows while CRT TV is off, Mask strength while Mask is Off
constexpr bool row_fixed(const Rows& r, int row) {
    const Rows c = clamped(r);
    if (row == DITHER) return kColourBits[c.v[COLOUR]] == 0;
    if (row >= SCANLINES && row <= SATURATION && !c.v[TV]) return true;
    if (row == MASK_STRENGTH) return c.v[MASK] == MASK_OFF;
    return false;
}

// ---- the look ----

/// What the three passes and the host are given: one of these for the frame
struct Look {
    bool on = false;
    int fps = 0;               // frames a second the host is asked for; 0 the Frame rate cap row's own
    int lines = 0;             // the 3D grid's lines (its width follows the picture's shape: grid)
    int colour_bits = 0;       // bits a channel; 0 the picture as it is
    float dither = 0.0f;       // the ordered dither's strength, 0 to 1 (0 with full colour: nothing to dither)
    float lod_bias = 0.0f;     // the texture blur in mip levels, before the card's limit (lod_bias)
    bool tv = false;           // the TV pass at the window
    float scanlines = 0.0f;    // how dark the gaps between TV lines are, 0 to 1, before the screen's say (scanline_strength)
    int mask = MASK_OFF;       // the Mask row's choice; Auto is decided by the screen (mask_shown)
    float mask_strength = 0.0f;
    float bleed = 0.0f;        // kBleed's
    float glow = 0.0f;
    float curvature = 0.0f;    // kCurvature's
    float saturation = 1.0f;
};
/// The look of a set of rows (Faithful's or Remembered's): what each value stands for
constexpr Look look_of_rows(Rows rows) {
    const Rows r = clamped(rows);
    Look l;
    l.on = true;
    l.fps = kFps[r.v[FPS]];
    l.lines = kLines[r.v[LINES]];
    l.colour_bits = kColourBits[r.v[COLOUR]];
    l.dither = l.colour_bits ? kDither[r.v[DITHER]] : 0.0f;
    l.lod_bias = r.v[BLUR] * kBlurStep;
    l.tv = r.v[TV] != 0;
    l.scanlines = l.tv ? r.v[SCANLINES] / 100.0f : 0.0f;
    l.mask = l.tv ? r.v[MASK] : (int)MASK_OFF;
    l.mask_strength = l.tv && l.mask != MASK_OFF ? r.v[MASK_STRENGTH] / 100.0f : 0.0f;
    l.bleed = l.tv ? kBleed[r.v[BLEED]] : 0.0f;
    l.glow = l.tv ? r.v[GLOW] / 100.0f : 0.0f;
    l.curvature = l.tv ? kCurvature[r.v[CURVATURE]] : 0.0f;
    l.saturation = l.tv ? r.v[SATURATION] / 100.0f : 1.0f;
    return l;
}
/// The look for the N64 Classic row's value: nothing with Off; Faithful's whatever the page holds; Remembered's rows
constexpr Look look_of(int preset, const Rows& remembered) {
    if (preset == FAITHFUL) return look_of_rows(kFaithful);
    if (preset == REMEMBERED) return look_of_rows(remembered);
    return Look{};
}
/// Two looks the same, field by field (Copy Faithful's promise)
constexpr bool same(const Look& a, const Look& b) {
    return a.on == b.on && a.fps == b.fps && a.lines == b.lines && a.colour_bits == b.colour_bits && a.dither == b.dither &&
           a.lod_bias == b.lod_bias && a.tv == b.tv && a.scanlines == b.scanlines && a.mask == b.mask &&
           a.mask_strength == b.mask_strength && a.bleed == b.bleed && a.glow == b.glow && a.curvature == b.curvature &&
           a.saturation == b.saturation;
}

/// The lab's switches for a run, over the look of either preset (an A/B, Faithful's too). -1 (or below 0) unset:
/// RX_VK_N64_LINES=<lines>, RX_VK_N64_LOD=<mip levels>, RX_VK_N64_TV=0|1, RX_VK_N64_MASK=<0..4> (the Mask enum),
/// RX_VK_N64_FPS=<frames a second, 0 the cap's>
struct Env {
    int lines = -1;
    float lod = -1.0f;
    int tv = -1;
    int mask = -1;
    int fps = -1;
};
constexpr Look with_env(Look l, const Env& e) {
    if (!l.on) return l;
    if (e.lines > 0) l.lines = e.lines;
    if (e.lod >= 0.0f) l.lod_bias = e.lod;
    if (e.tv == 0) l.tv = false;
    if (e.tv > 0) l.tv = true;
    if (e.mask >= MASK_AUTO && e.mask <= MASK_SHADOW) l.mask = e.mask;
    if (e.fps >= 0) l.fps = e.fps;
    return l;
}

// ---- the 3D pass's grid ----

/// The lines of a TV of then: the scanlines follow these whatever the 3D's own lines
constexpr int kTvLines = 240;
struct Grid {
    uint32_t w = 0, h = 0;
};
/// The grid the 3D pass draws on for a picture of picture_w x picture_h: `lines` tall (never more than the picture) and as
/// wide as the picture's shape makes it, rounded: 240 lines are 320 at 4:3, 427 at 16:9, 569 at the host's 21:9 picture
/// (3416 x 1440). Nothing when a size is not known
constexpr Grid grid(int lines, uint32_t picture_w, uint32_t picture_h) {
    if (lines <= 0 || !picture_w || !picture_h) return {};
    const uint32_t h = (uint32_t)lines < picture_h ? (uint32_t)lines : picture_h;
    const uint64_t w = (2ull * h * picture_w + picture_h) / (2ull * picture_h);
    return {w ? (uint32_t)w : 1u, h};
}

// ---- the texture blur ----

/// The texture LOD bias for the scene's material samplers (vk_draw.cpp sampler_make, through the scene-only path the
/// upscalers' bias takes): the look's, never past the card's maxSamplerLodBias (Vulkan promises 2 at least), never below 0.
/// 0 with the mode off
constexpr float lod_bias(const Look& l, float card_max) {
    if (!l.on || l.lod_bias <= 0.0f || card_max <= 0.0f) return 0.0f;
    return l.lod_bias < card_max ? l.lod_bias : card_max;
}
/// (step 3) A draw into a target of w x h (sharpen_rules.h lod_scene_size: its smallest colour target, or a depth-only
/// draw's depth) is the scene for the picture N64 Classic's 3D pass last drew, ow x oh, while its blur is on: the picture
/// 1 to 3 times its size on each axis, smaller on one at least, and of its shape (within a 32nd). The upscalers' bias goes
/// by the last upscale's render size and this frame's scene camera, which their own hooks note; with N64 Classic those
/// hooks are off, so the game's dynamic resolution, which makes new targets at each size, is taken by its shape here, the
/// frame of a new size included. The sun's and the characters' shadow maps (square), half-size buffers past a third, and
/// the HUD and the output's passes (the picture's own size) are not the scene. (At a fixed 100% the scene is the picture's
/// size: the last upscale's render size, as before, takes it.) Nothing while a size is not known
constexpr bool scene_draw(uint32_t w, uint32_t h, uint32_t ow, uint32_t oh) {
    if (!w || !h || !ow || !oh || w > ow || h > oh || (w == ow && h == oh)) return false;
    if ((uint64_t)w * 3 < ow || (uint64_t)h * 3 < oh) return false;
    const uint64_t a = (uint64_t)w * oh, b = (uint64_t)h * ow;   // (the two shapes, cross-multiplied)
    const uint64_t d = a > b ? a - b : b - a, big = a > b ? a : b;
    return d * 32 <= big;
}

// ---- the TV, on a screen ----

/// The scanlines' strength on a picture placed place_h window pixels tall: the look's while a TV line has 3 window pixels
/// or more, fading to none at 2 (thinner, they only make moire). The Steam Deck's 720 lines for a 16:9 picture are 3 a line
constexpr float scanline_strength(float strength, uint32_t place_h, int tv_lines = kTvLines) {
    if (strength <= 0.0f || !place_h || tv_lines <= 0) return 0.0f;
    const float px = (float)place_h / (float)tv_lines;
    const float k = px >= 3.0f ? 1.0f : px <= 2.0f ? 0.0f : px - 2.0f;
    return strength * k;
}
/// (step 4) The colour bleed (Look's, in pixels of a 320-wide 4:3 picture) in the widths of a picture of picture_w x
/// picture_h, as the TV shader steps along a line: a pixel of the 240-line grid is a 240th of the height, so the picture is
/// 240 x its shape such pixels wide (427 at 16:9). 0 when a size is not known
constexpr float tv_bleed_uv(float bleed, uint32_t picture_w, uint32_t picture_h) {
    if (bleed <= 0.0f || !picture_w || !picture_h) return 0.0f;
    return bleed * (float)picture_h / ((float)kTvLines * (float)picture_w);
}
/// Mask Auto: shown on a picture placed this tall or more (3 window pixels a triad stay fine there), none below
constexpr uint32_t kMaskAutoLines = 1440;
/// The mask drawn on a picture placed place_h window pixels tall: Auto's slot mask or none by the height; a mask the player
/// picked, as it is
constexpr int mask_shown(int mask, uint32_t place_h) {
    if (mask == MASK_AUTO) return place_h >= kMaskAutoLines ? (int)MASK_SLOT : (int)MASK_OFF;
    return mask >= MASK_OFF && mask <= MASK_SHADOW ? mask : (int)MASK_OFF;
}

// ---- what the mode stands in front of ----

/// While N64 Classic is on, its 3D pass takes the gameplay upscale: DLSS, DLAA, FSR 3.1 and FSR 4 step aside (the game's own
/// as far as they are concerned), the game's SMAA is left out (the grid's averaging smooths the edges), and the window's
/// Sharpness is none. The rows keep their saved values: off again, each is what it was
constexpr int upscaler(int preset, int chosen_upscaler) { return preset != OFF ? (int)upscaler_rows::GAME : chosen_upscaler; }
constexpr int anti_aliasing(int preset, int chosen_aa) { return preset != OFF ? (int)aa_rows::OFF : chosen_aa; }
constexpr int sharpness(int preset, int chosen_sharpness) { return preset != OFF ? 0 : chosen_sharpness; }
/// The Upscaler, Render resolution, Anti-aliasing and Sharpness rows shown fixed, their text "N64 Classic"
constexpr bool fixes_rows(int preset) { return preset != OFF; }
/// The 3D pass runs: not on a RenoDX run's RGBA16F scene (scene_rgba16f), whose upscale output it does not take
constexpr bool three_d_runs(const Look& l, bool scene_rgba16f) { return l.on && !scene_rgba16f; }
/// The TV pass runs at the window: not on HDR Native's PQ picture (native_pq, RenoDX's too), nor while DLSS frame
/// generation makes its frames from the finished image after it (dlssg: its motion would move the scanlines and the mask)
constexpr bool tv_runs(const Look& l, bool native_pq, bool dlssg) { return l.on && l.tv && !native_pq && !dlssg; }

// ---- the frame rate ----

/// What the renderer tells the host (host/nn_vi.c pace_fps, step 7): the look's rate, 0 for the cap's own and with the
/// mode off
constexpr int fps(const Look& l) { return l.on ? l.fps : 0; }
/// The rate the frames are paced by with that answer under the Frame rate cap row's cap: the mode's where it is lower,
/// the cap's otherwise (a Remembered 60 under a cap of 45 is 45). The caps the game offers are 30 and up, so Faithful's 20
/// is always 20
constexpr int paced(int n64_fps, int cap) { return n64_fps > 0 && n64_fps < cap ? n64_fps : cap; }

// ---- F7 ----

/// The preset F7 turns on from Off (saved as kLastKey, so a start finds the player's own): Faithful until another is
/// chosen
constexpr const char* kLastKey = "n64_classic_last";
struct Toggle {
    int last = FAITHFUL;
    /// The row now holds row (a press of F7, the row itself, the options file at the start)
    constexpr void noted(int row) {
        if (row == FAITHFUL || row == REMEMBERED) last = row;
    }
    /// F7 pressed with the row at row: what the row becomes
    constexpr int pressed(int row) {
        if (row == FAITHFUL || row == REMEMBERED) {
            last = row;
            return OFF;
        }
        return last;
    }
};

// ---- the TV switching off and on ----

/// Half a second at each change of the row or F7: the old picture squashed to a bright line, then to a dot (the first
/// half), the new one opening from the dot to a line, then to the whole picture (the second). The 3D, the TV and the
/// frame rate change at the middle, where the screen is a dot (`after`), so the change of rate is not seen
constexpr float kAnimSeconds = 0.5f;
struct AnimFrame {
    float scale_x = 1.0f, scale_y = 1.0f;   // the picture's width and height, shares of the whole
    float flash = 0.0f;                     // the brightness added, 0 to 1: the most at the dot
    bool after = false;                     // the new look's frame (from the middle on)
    bool done = true;                       // the switch is over: the picture as it is
};
constexpr float kAnimLine = 0.004f, kAnimDot = 0.01f;   // (the line's height and the dot's width, shares of the picture)
constexpr AnimFrame anim(float t) {
    if (t < 0.0f) return AnimFrame{};
    if (t >= kAnimSeconds) return {1.0f, 1.0f, 0.0f, true, true};
    const float half = kAnimSeconds / 2.0f;
    const bool after = t >= half;
    const float u = after ? (kAnimSeconds - t) / half : t / half;   // (0 at either end, 1 at the middle)
    AnimFrame f;
    f.after = after, f.done = false, f.flash = u;
    if (u < 0.6f) {
        f.scale_y = 1.0f - (1.0f - kAnimLine) * (u / 0.6f);
    } else {
        f.scale_y = kAnimLine;
        f.scale_x = 1.0f - (1.0f - kAnimDot) * ((u - 0.6f) / 0.4f);
    }
    return f;
}

/// (step 8) The switch from one preset to another, taken once a present (vk_n64.cpp n64_tick): which preset the passes and
/// the host go by now (shown: the one before until the switch's middle, the one chosen from it), and the TV's frame of it.
/// The first present takes the preset as it is, with no switch (a start does not switch the TV on). A new choice while the
/// picture still closes is what opens instead; one after the middle switches again from what is shown. animate false
/// (RX_VK_N64_TV_ANIM=0, or no TV pass can draw it: HDR Native's picture, DLSS frame generation): the choice at once
struct Switch {
    int from = OFF, to = OFF;   // the preset before the switch and the one chosen
    double t0 = -1.0;           // when the switch began, in seconds; below 0, none
    bool started = false;
    struct Now {
        int shown = OFF;
        AnimFrame frame;        // (done: no switch running, the picture as it is)
    };
    constexpr Now at(double now, int chosen, bool animate) {
        if (!started || !animate) {
            started = true, from = to = chosen, t0 = -1.0;
            return {chosen, AnimFrame{}};
        }
        const bool running = t0 >= 0.0 && now - t0 < kAnimSeconds;
        if (chosen != to) {
            if (running && now - t0 < kAnimSeconds / 2.0) {
                to = chosen;                         // (still closing: the new choice opens)
            } else {
                from = to, to = chosen, t0 = now;    // (a new switch, from what is shown)
            }
        }
        if (t0 < 0.0 || now - t0 >= kAnimSeconds) {
            from = to, t0 = -1.0;
            return {to, AnimFrame{}};
        }
        const AnimFrame f = anim((float)(now - t0));
        return {f.after ? to : from, f};
    }
};

/// (step 8) The TV pass draws at the window: for the look's TV, or for the TV switching off and on (anim not done: the
/// squash over whatever look is shown, an Off one's too), never on HDR Native's PQ picture nor under DLSS frame generation
constexpr bool tv_draws(const Look& l, const AnimFrame& frame, bool native_pq, bool dlssg) {
    return ((l.on && l.tv) || !frame.done) && !native_pq && !dlssg;
}

// ---- (11-22, the owner's test: "the extra menu UI, and the options isn't in the exact position it should be") the TV's
// screen, for the mouse. The options are drawn under the TV now (vk_menu.cpp menu_tv_layer), so they bend with the game's
// own screens; the cursor is still where the window has it, flat. A point of the window is taken to the point of the
// picture the TV shows there, as n64_tv.comp finds it (its squash, then n64_tv.glsl n64_warp), and the controls are
// tested there, where they were drawn ----

/// A point in a window's pixels
struct ScreenPoint {
    float x = 0.0f, y = 0.0f;
};
/// The point of the picture the TV shows at (px, py) of the window: the picture fills the place x, y, w, h of the window
/// (the same pixels) through the screen's curve (curve) and the switch's squash (ax, ay: n64_tv.comp's anim_x, anim_y, 1
/// at rest). Outside the place, or with no place: the point as it is. A point the TV shows black (off the curved picture,
/// or around the squash) is taken past the picture's edge, where nothing was drawn
constexpr ScreenPoint screen_point(float px, float py, float x, float y, float w, float h, float curve, float ax, float ay) {
    if (w <= 0.0f || h <= 0.0f || ax <= 0.0f || ay <= 0.0f) return {px, py};
    float a = (px - x) / w * 2.0f - 1.0f, b = (py - y) / h * 2.0f - 1.0f;
    if (a < -1.0f || a > 1.0f || b < -1.0f || b > 1.0f) return {px, py};
    a /= ax, b /= ay;
    const float r = 1.0f + curve * (a * a + b * b);   // (n64_warp: the same for both axes)
    return {x + (a * r * 0.5f + 0.5f) * w, y + (b * r * 0.5f + 0.5f) * h};
}

} // namespace mkwvk::n64_rules
