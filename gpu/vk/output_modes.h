// (Triforce) More sizes for the Output resolution row (vk_menu.cpp output_entries): every display mode of the screen the game's
// window is on, and the common sizes of each shape the picture can take (16:9, 16:10, 21:9, 32:9, 48:9, 4:3, 5:4) up to that
// screen's own size. Each is offered as the connected screens' sizes are: chosen, it is Custom with that size in the Output
// width and Output height rows (output_sizes.h), so a saved file holds a size and every saved value keeps what it meant. A size
// of another shape than 16:9 is its own picture, as any such size is (output_sizes.h); the Aspect ratio row keeps its fixed
// shapes (ultrawide_rows.h: none of its values follows the monitor, the owner's rule of 11-16) and its migrations as they are.
// Plain code: tests/test_output_modes.py compiles it.
#pragma once

#include <algorithm>
#include <cstdint>
#include <vector>

namespace mkwvk::output_modes {

struct Size {
    unsigned w = 0, h = 0;
};
inline bool operator==(Size a, Size b) { return a.w == b.w && a.h == b.h; }

/// The common sizes, by shape
constexpr Size kCommon[] = {
    {1280, 720},  {1600, 900},  {1920, 1080}, {2560, 1440}, {3200, 1800}, {3840, 2160},                 // 16:9
    {1280, 800},  {1440, 900},  {1680, 1050}, {1920, 1200}, {2560, 1600}, {2880, 1800}, {3840, 2400},   // 16:10
    {2560, 1080}, {3440, 1440}, {3840, 1600}, {5120, 2160},                                             // 21:9
    {3840, 1080}, {5120, 1440},                                                                         // 32:9
    {5760, 1080}, {7680, 1440},                                                                         // 48:9
    {1024, 768},  {1440, 1080}, {1600, 1200}, {2048, 1536},                                             // 4:3
    {1280, 1024},                                                                                       // 5:4
};

/// A display mode worth a place in the row: 1280 x 720 or more (the smaller ones are for old programs)
inline bool mode_worth(unsigned w, unsigned h) { return w >= 1280 && h >= 720; }

/// The sizes to offer for a screen of sw x sh (0 x 0: not known) with these display modes: its modes worth a place, then the
/// common sizes no larger than the screen either way (every one when the screen is not known), each once, in that order.
/// The row sorts and makes them the sizes the game takes (output_size_used) itself
inline std::vector<Size> offered(unsigned sw, unsigned sh, const std::vector<Size>& modes) {
    std::vector<Size> out;
    const auto add = [&](Size s) {
        if (std::find(out.begin(), out.end(), s) == out.end()) out.push_back(s);
    };
    for (const Size& m : modes)
        if (mode_worth(m.w, m.h)) add(m);
    for (const Size& c : kCommon)
        if (!sw || !sh || (c.w <= sw && c.h <= sh)) add(c);
    return out;
}

} // namespace mkwvk::output_modes
