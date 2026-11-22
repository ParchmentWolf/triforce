// (Triforce, 11-21, the performance audit's PRESENT-18, after Source A's) When frame generation's images are let go.
//
// The built-in interpolation's frames, lumas, flows and made-frame sets (and, for AMD FSR 4's frame generation, the four
// images of the picture without the HUD) are made at the first frame that needs them and were kept until a resize: turned
// off, or left for NVIDIA's own frame generation, they stayed in VRAM for the run. Source A measured 150 to 160 MiB given
// back at 2560 x 1440 with 2x after its switch away. They are let go after kPresents presents in a row with frame
// generation off, about two seconds at 60: a row stepped through on the way to another choice keeps them. A present that
// recorded made frames counts as on whatever the row says by then: its set is busy until the display thread has shown
// it, and a drain then would wait for a job that is only queued afterwards. So the count is taken after the present's
// queue (vk_replay.cpp, after framegen_queue). They are made again at the next frame that needs them, as after a resize.
// RX_VK_FG_KEEP=1: kept, as before.
//
// The rule alone, no Vulkan: tests/test_framegen_idle.py compiles it.
#pragma once
#include <cstdint>

namespace framegen_idle {

inline constexpr uint32_t kPresents = 120;

/// The presents in a row off, after this one: on now, or used at this present, starts again
inline uint32_t next_off(uint32_t off, bool on_now, bool used) { return on_now || used ? 0 : off < UINT32_MAX ? off + 1 : off; }

/// Whether this present lets them go: there are some, and they have been off long enough
inline bool due(uint32_t off, bool have) { return have && off >= kPresents; }

/// One present, as framegen_idle sees it after the present's queue
struct Present {
    bool on;               // frame generation on by the row, read again (framegen_on)
    bool recorded;         // this present recorded made frames (framegen_record's true)
    bool hudless_wanted;   // AMD FSR 4's frame generation is the row's (fsr4fg::frames_wanted)
    bool have_images;      // the shared images are there (fg.w)
    bool have_hudless;     // the images of the picture without the HUD are there
};
struct Counts {
    uint32_t off = 0, hudless_off = 0;
};
struct Release {
    bool shared, hudless;
};
/// The two counts after this present, and what it lets go. keep: RX_VK_FG_KEEP, nothing ever
inline Release step(Counts& c, const Present& p, bool keep) {
    c.off = next_off(c.off, p.on, p.recorded);
    c.hudless_off = next_off(c.hudless_off, p.on && p.hudless_wanted, false);
    if (keep) return {false, false};
    return {due(c.off, p.have_images), due(c.hudless_off, p.have_hudless)};
}

}   // namespace framegen_idle
