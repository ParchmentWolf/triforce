// (Triforce, 11-21, the performance audit's TEX-76, after Source B's) When a depth target that another size has replaced at its
// start is let go.
//
// The game draws each character's shadow map (D32, one level) at a fixed address, sized from the camera every frame. An
// image is kept by its storage, width and height, so each new size is a new texture, and the one before it has been drawn
// over. The sweep took such a texture only once it was unused for 120 presents (60 over a fixed budget): a pile of dead maps
// at every slot, in VRAM for two seconds each. Source B's rule, as it ended after its earlier ones retired targets the game
// drew into again (after 1 frame; colour targets; depth of the same size): a depth target of one level and layer at the
// same start and of the same format as a newer target of another width or height, the newer one written after its last
// use, goes once it is unused for kWait presents. Its VRAM peak in the night market fell from 5,972 to 5,482 MiB, and no
// retired image was wanted again within 16 frames (29 were with a wait of 1). Nothing is written back: the newer target's
// texels are in that storage. The image goes to the render targets' pool by its create info, as any dead target's.
// RX_VK_SLOT_RETIRE=<presents>: the wait, 16 when not set; 0: only after the sweep's own 120, as before.
//
// The rule alone, no Vulkan: tests/test_slot_retire.py compiles it.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace slot_retire {

inline constexpr uint64_t kWait = 16;

/// The wait in presents: asked, RX_VK_SLOT_RETIRE's value; not set or empty kWait; 0 or less (and what is no number): 0, off
inline uint64_t wait(const char* asked) {
    if (!asked || !*asked) return kWait;
    const long v = atol(asked);
    return v > 0 ? (uint64_t)v : 0;
}

/// What the rule looks at of a texture
struct Target {
    bool gpu_written, depth;          // (the GPU drew it; its aspect is depth)
    uint32_t levels, layers, deep;    // (deep: its depth in texels, 1 for a 2D one)
    int nvn_format;
    uint32_t width, height;
    uint64_t last_frame, last_written;   // (the present it was last used in; the frame the GPU last wrote it in)
};

/// Whether old, unused for `unused` presents, is let go because newer took its place: both at the same start
inline bool retired_by(const Target& old, const Target& newer, uint64_t unused, uint64_t wait_presents) {
    if (!wait_presents || unused < wait_presents) return false;
    if (!old.gpu_written || !old.depth || old.levels != 1 || old.layers != 1 || old.deep > 1) return false;
    if (newer.nvn_format != old.nvn_format) return false;
    if (newer.width == old.width && newer.height == old.height) return false;   // (the same size: the game may draw into it again)
    return newer.last_written > old.last_frame;                                 // (written after its last use: drawn over)
}

}   // namespace slot_retire
