// (Triforce, 11-21, the upscaler audit's UPS-01) The render size NVIDIA DLSS's feature is made for.
//
// vk_dlss.cpp made every feature for the largest render size its quality mode allows, so that the game's dynamic
// resolution could change the render size under it without the feature being made again. NGX answers that largest size as
// the output's own (the owner's log of 11-21: "feature 1 made ...: 2944x1243 (2208x932 to 4416x1864) -> 4416x1864, mode
// 2, preset M"), so with the Render resolution row at a fixed share, where the render size never changes, the feature was
// still made for 2.25 times the pixels it was ever given at Quality, 4 times at Performance and 9 at Ultra Performance,
// and the chain's three input images with it. NVIDIA's guide (DLSS Programming Guide 310.6.0, 3.2 and 5.2.8) has the
// optimal render size passed to the creation "exactly as given", and says of the second generation transformer's presets
// L and M that their cost follows the size the feature is initialized for, which is why it is to be the dynamic range's
// largest only where there is a dynamic range. The same log has DLSS's own video memory at 1069 MB for that feature, where
// NVIDIA's table has 456 MB for preset M at 4K.
//
// So: a fixed share gets a feature of its own render size (exact), as AMD FSR 4 gets a context of its own
// (temporal_rules.h plan_context). Where the render size is the game's to change (the row's Auto), or once it has changed
// under one output in this run, the feature is made for the mode's whole range, as before. DLAA's is the output's either
// way.
//
// RX_VK_DLSS_FEATURE_MAX=1: every feature for its mode's largest render size, as before (whole_range()).
//
// No NGX, no Vulkan: tests/test_dlss_feature.py compiles this.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace dlss_feature {

/// RX_VK_DLSS_FEATURE_MAX (value, null when unset): not 0, every feature for its mode's largest render size, as before
inline bool whole_range(const char* value) { return value && *value && std::atoi(value) != 0; }

/// What a feature is made for: w x h, and whether that is the one render size it takes (exact) or the largest of a range
struct Size {
    uint32_t w, h;
    bool exact;
};

/// The size to make a feature for, for a frame of rw x rh in a mode whose render sizes go up to max_w x max_h. aa: DLAA,
/// the render size the output's (its range is that one size). range: the render size may change under this output (the
/// row's Auto, the size seen changing, or the switch)
inline Size size(bool aa, bool range, uint32_t rw, uint32_t rh, uint32_t max_w, uint32_t max_h) {
    if (aa || range || rw > max_w || rh > max_h) return {max_w, max_h, false};
    return {rw, rh, true};
}

/// Whether a feature made for fw x fh takes a frame of rw x rh: its one size (exact), or any from min_w x min_h up to its own
inline bool takes(bool exact, uint32_t fw, uint32_t fh, uint32_t min_w, uint32_t min_h, uint32_t rw, uint32_t rh) {
    if (exact) return rw == fw && rh == fh;
    return rw <= fw && rh <= fh && rw >= min_w && rh >= min_h;
}

/// Whether this frame shows that the render size changes under one output: a feature of one size (exact) for the same
/// output, preset and colour (same), and a frame of another size. The caller keeps it for the run: the next feature, and
/// every one after it, is made for the mode's whole range
inline bool found_range(bool same, bool exact, uint32_t fw, uint32_t fh, uint32_t rw, uint32_t rh) {
    return same && exact && (rw != fw || rh != fh);
}

}   // namespace dlss_feature
