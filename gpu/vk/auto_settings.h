// (Triforce) The Graphics tab's "Auto (this PC)" row: the settings this PC's hardware suits, set once when the row is turned
// On, and tuned in play while it stays On (vk_menu.cpp auto_apply, menu_auto_tune). tests/test_auto_settings.py
//
// Triforce has no Quality preset (gone at options_version 7): Auto sets the rows themselves, the Upscaler, Render resolution,
// Texture detail, Shadow resolution and Grass distance, from what the PC reports reliably: the card's video memory, its maker
// and kind (integrated or not, mesh shaders), which upscalers run on it, the RAM and the processor's threads. No list of GPU
// models: how fast the card is, which a model list would only guess, is left to the tuning in play. Off (the default) sets and
// tunes nothing. Each choice says why, for the log line a bug report carries.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace auto_settings {

enum Vendor : int { OTHER = 0, NVIDIA = 1, AMD = 2, INTEL = 3 };

struct Hardware {
    int vendor = OTHER;
    bool integrated = false;    // (an integrated GPU, a handheld's among them: its memory is the system's)
    bool mesh_native = true;    // (the device has mesh shaders; false: the compute fallback runs them)
    bool dlss_runs = false;     // (NVIDIA DLSS runs here: an RTX card, the build and the driver's libraries)
    bool fsr4_runs = false;     // (AMD FSR 4 runs here: an RDNA 4 card and AMD's library)
    uint32_t vram_mb = 0;
    uint32_t ram_mb = 0;        // (0: not known)
    int threads = 0;            // (0: not known)
};

// The rows Auto sets, by their values in the menu: the Upscaler (upscaler_rows.h GAME, DLSS, FSR4), the Render resolution
// (upscaler_rows.h kPercent's index), Texture detail (0 Automatic), Shadow resolution (0 the game's, 1 High, 2 Highest) and
// Grass distance (0 the game's, 1 2x, 2 3x, 3 4x)
struct Choice {
    int tier = 0;               // (1 the lightest ... 5 the heaviest, by the card's memory)
    int upscaler = 0;
    int resolution = 0;
    int tex_detail = 0;
    int shadow_res = 0;
    int grass = 0;
    char why[480] = {};
};

// (upscaler_rows.h's, kept here so the rules compile on their own; tests/test_auto_settings.py checks they agree)
enum { GAME = 0, DLSS = 1, FSR3 = 3, FSR4 = 4 };
enum { RES_FULL = 1, RES_75 = 2, RES_QUALITY = 3, RES_PERFORMANCE = 4, RES_BALANCED = 5, RES_ULTRA_PERFORMANCE = 6 };

// The Render resolution with the game's own upscaler at each tier (index: the tier): 50%, 75%, then 100%
constexpr int kTierResolution[] = {0, RES_PERFORMANCE, RES_75, RES_FULL, RES_FULL, RES_FULL};

// The tier by the card's memory: up to 4.5 GB 1, 6.5 GB 2, 11.5 GB 3 (10 and 11 GB cards: not the heavier rows' memory),
// 13 GB 4, more 5. An integrated GPU or a card without mesh shaders is 1 whatever its memory says: the memory it reports is
// shared with the system, or the fallback costs the frame more than the memory saves (first_start.h's tier 1). Under 12 GB of
// RAM it is held at 2: the game's memory and the copies the driver keeps of its textures leave little
inline int tier_of(const Hardware& h) {
    if (h.integrated || !h.mesh_native) return 1;
    const uint32_t mb = h.vram_mb;
    int t = mb <= 4608 ? 1 : mb <= 6656 ? 2 : mb <= 11776 ? 3 : mb <= 13312 ? 4 : 5;
    if (h.ram_mb && h.ram_mb < 12288 && t > 2) t = 2;
    return t;
}

inline void add(Choice& c, const char* text) {
    const size_t n = std::strlen(c.why);
    std::snprintf(c.why + n, sizeof c.why - n, "%s%s", n ? "; " : "", text);
}

inline Choice choose(const Hardware& h) {
    Choice c;
    c.tier = tier_of(h);
    char b[160];
    if (h.integrated) add(c, "integrated GPU: tier 1");
    else if (!h.mesh_native) add(c, "no mesh shaders (the compute fallback): tier 1");
    else {
        std::snprintf(b, sizeof b, "%u MB of video memory: tier %d", (unsigned)h.vram_mb, c.tier);
        add(c, b);
        if (h.ram_mb && h.ram_mb < 12288 && c.tier == 2 && h.vram_mb > 6656) add(c, "under 12 GB of RAM: held at tier 2");
    }
    // The upscaler the card has hardware for (by its maker: NVIDIA's DLSS, AMD's FSR 4), else the game's own, on every card
    c.resolution = kTierResolution[c.tier];
    const char* mode = c.tier == 2 ? "Performance" : c.tier == 3 ? "Balanced" : "Quality";
    const int res = c.tier == 2 ? RES_PERFORMANCE : c.tier == 3 ? RES_BALANCED : RES_QUALITY;
    if (c.tier >= 2 && h.vendor == NVIDIA && h.dlss_runs) {
        c.upscaler = DLSS, c.resolution = res;
        std::snprintf(b, sizeof b, "NVIDIA: DLSS %s", mode);
        add(c, b);
    } else if (c.tier >= 2 && h.vendor == AMD && h.fsr4_runs) {
        c.upscaler = FSR4, c.resolution = res;
        std::snprintf(b, sizeof b, "AMD: FSR 4 %s", mode);
        add(c, b);
    } else {
        add(c, h.vendor == NVIDIA && c.tier >= 2 ? "the game's own upscaler (DLSS does not run here)"
               : h.vendor == AMD && c.tier >= 2 ? "the game's own upscaler (FSR 4 does not run here)"
                                                : "the game's own upscaler");
    }
    // (an integrated GPU beside 4 threads or fewer: 33%, first_start.h's rule: an i3-1115G4's own GPU took 60 to 220 ms a
    // frame at 50%. The game's own upscaler's lowest step is 50%: the menu shows and runs the saved 33% at that, ur::snap, as
    // first_start.h's)
    if (h.integrated && h.threads > 0 && h.threads <= 4) {
        c.resolution = RES_ULTRA_PERFORMANCE;
        add(c, "4 threads or fewer: the game's own at its lowest");
    }
    // The detail rows: the game's own up to tier 3; High shadows and twice the grass at 4; Highest and three times at 5. The
    // grass's extra blades are drawn by the recording threads: with 4 threads or fewer it stays the game's
    c.tex_detail = 0;   // (Automatic: texture_budget's own choice for the card's memory)
    c.shadow_res = c.tier >= 5 ? 2 : c.tier == 4 ? 1 : 0;
    c.grass = c.tier >= 5 ? 2 : c.tier == 4 ? 1 : 0;
    if (c.grass && h.threads > 0 && h.threads <= 4) {
        c.grass = 0;
        add(c, "4 threads or fewer: the game's grass distance");
    }
    if (c.shadow_res || c.grass) {
        std::snprintf(b, sizeof b, "shadows %s, grass %dx", c.shadow_res == 2 ? "Highest" : c.shadow_res ? "High" : "the game's",
                      c.grass + 1);
        add(c, b);
    }
    return c;
}

// The fingerprint the options file keeps (auto_for=): turned On, Auto chooses again at a start whose hardware differs
inline int32_t fingerprint(const Hardware& h, uint32_t vendor_id, uint32_t device_id) {
    uint64_t f = 1469598103934665603ull;
    const uint64_t parts[] = {vendor_id, device_id, h.vram_mb >> 8, (uint64_t)h.dlss_runs, (uint64_t)h.fsr4_runs,
                              (uint64_t)h.mesh_native};
    for (uint64_t p : parts) f = (f ^ p) * 1099511628211ull;
    return (int32_t)((f ^ (f >> 32)) & 0x7fffffff);
}

// The tuning in play, while the row is On: each window is the replay's 120 presents (vk_replay.cpp): the GPU's time a frame,
// the draws a frame and the frame rate. Only windows of play count (150 draws a frame or more; menus and loading screens draw
// fewer). After kWindows of them their middle values decide, lowering the load only where frames are missed and raising it
// only with room to spare:
// - frames missed (under 95% of the cap) and the GPU over 90% of the cap's frame time: one step lighter
// - frames missed with the GPU under 90% of the cap's frame time and idle a quarter of the frame shown or more: the processor
//   holds it, and a lighter picture would not help: done for this run, nothing changed (the next start measures again)
// - the cap held and the GPU under 50% of its frame time: one step heavier, up to the best step that still upscales
//   (best_step), never native
// - else: done
// At most kMaxSteps changes in all; a step down is never followed by a step up (no seesaw). steps and went_down are kept in
// the options file (auto_tune=), so both hold across restarts
constexpr int kWindows = 8;
constexpr int kMaxSteps = 2;
enum Verdict : int { WAIT = 0, KEEP = 1, CPU_BOUND = 2, LIGHTER = 3, HEAVIER = 4 };
struct Tuning {
    float gpu_ms[kWindows] = {}, fps[kWindows] = {};
    int n = 0;          // (play windows gathered since the last change)
    int steps = 0;
    bool went_down = false;
    bool done = false;
    float gpu_mid = 0, fps_mid = 0;   // (the middle values the last verdict was made on: for the log)
};
inline float middle(float* v, int n) {   // (the median; sorts v)
    for (int i = 1; i < n; i++)
        for (int j = i; j > 0 && v[j] < v[j - 1]; j--) { const float t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
    return n % 2 ? v[n / 2] : (v[n / 2 - 1] + v[n / 2]) / 2;
}
// The largest Render resolution the tuning raises to for an upscaler: Quality (67%) for DLSS, FSR 3.1 and FSR 4, 100% for
// the game's own
inline int best_step(int upscaler) { return upscaler == DLSS || upscaler == FSR3 || upscaler == FSR4 ? RES_QUALITY : RES_FULL; }
// One window: WAIT while gathering, else the verdict. cap_fps: the cap the game runs to (the display's refresh when uncapped);
// can_lighter, can_heavier: whether there is a step that way
inline Verdict tune(Tuning& t, float gpu_ms, float draws, float fps, float cap_fps, bool can_lighter, bool can_heavier) {
    if (t.done || draws < 150 || !(gpu_ms > 0) || !(fps > 0) || !(cap_fps > 0)) return WAIT;
    t.gpu_ms[t.n] = gpu_ms, t.fps[t.n] = fps;
    if (++t.n < kWindows) return WAIT;
    const float g = middle(t.gpu_ms, t.n), f = middle(t.fps, t.n), budget = 1000.0f / cap_fps;
    t.n = 0, t.gpu_mid = g, t.fps_mid = f;
    const bool missed = f < cap_fps * 0.95f;
    if (missed && g > 0.9f * budget && can_lighter && t.steps < kMaxSteps) return t.steps++, t.went_down = true, LIGHTER;
    if (missed && g < 0.9f * budget && g < 0.75f * (1000.0f / f)) return t.done = true, CPU_BOUND;
    if (!missed && g < 0.5f * budget && can_heavier && !t.went_down && t.steps < kMaxSteps) return t.steps++, HEAVIER;
    t.done = true;
    return KEEP;
}

// (the tuning's state as the options file keeps it, auto_tune=: steps in bits 0-1, went_down bit 2, done for good bit 3)
inline int pack(const Tuning& t, bool settled) { return (t.steps & 3) | (t.went_down ? 4 : 0) | (settled ? 8 : 0); }
inline void unpack(int v, Tuning& t, bool& settled) {
    t.steps = v & 3, t.went_down = (v & 4) != 0, settled = (v & 8) != 0;
    if (settled) t.done = true;
}

} // namespace auto_settings
