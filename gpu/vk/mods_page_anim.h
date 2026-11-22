// (Triforce, 11-20) The Mods screen as it opens. The owner: "Mod menu fade in". The entry that opens it is animated as the
// game's own entries are (mods_entry_anim.h on the title, focus_anim.h under the pause menu's System list), and Quit's
// dialog opens as the game's SystemWindow_00; the screen itself came at once, whole, on the frame after the press. It
// fades in now as the game's lists and windows do: the alpha of Title_00's list and of SystemWindow_00's N_In_00 (the
// same keys in both layouts: 0 to 1 over 15 frames, slow to start, slopes 0.02 and 0.14), with no rise, as a whole screen
// has none. It takes input once that has played, as the game's own screens and Quit's dialog do. Back is a cut, as the
// game's windows go in 2 frames.
// No ImGui and no Vulkan: tests/test_mods_page_anim.py compiles it alone.
#pragma once
#include <algorithm>
#include <cstdint>
#include "mods_entry_anim.h"   // (the layouts' curves: Key, curve, frames)

namespace mods_page {

using mods_entry::curve;
using mods_entry::frames;
using mods_entry::Key;
using mods_entry::kFrameNs;

constexpr Key kInAlpha[] = {{0, 0, 0.02f}, {15, 1, 0.14f}};
constexpr int64_t kInNs = 15 * kFrameNs;

/// How much of the screen shows t ns after it opened (0 to 1)
inline float in_alpha(int64_t t) {
    if (t <= 0) return 0;
    return std::clamp(curve(kInAlpha, frames(t)), 0.0f, 1.0f);
}

/// The screen from one tick to the next: whether it is shown, and since when
struct Page {
    bool shown = false;      // (it was the page shown at the last step)
    int64_t since_ns = 0;    // (when it came; 0 while it is not shown)
    /// One tick at now: whether the Mods screen is the page shown. A screen that comes starts its In; one that goes has none
    void step(int64_t now, bool on) {
        if (on && !shown) since_ns = now;
        if (!on) since_ns = 0;
        shown = on;
    }
    /// How much of it shows at now. settle: as it stands once its In is done (a still, a picture that compares). A screen
    /// asked for and not stepped yet (the page was set this tick, the step comes at the tick's end) shows nothing: drawn in
    /// between at full, it flashed whole for a frame before its In began
    float alpha(int64_t now, bool settle = false) const { return settle ? 1.0f : !shown ? 0.0f : in_alpha(now - since_ns); }
    /// (it takes input once its In has played, as the game's)
    bool ready(int64_t now) const { return shown && now - since_ns >= kInNs; }
};

}   // namespace mods_page
