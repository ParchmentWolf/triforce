// (Triforce) Ultrawide's menu sides: when the renderer shows them, as plain code (vk_framegen.cpp wide_sides;
// tests/test_wide_sides.py). No Vulkan, no host.
//
// With the Insert menu's Ultrawide menus row on Centred the game's menus keep their 16:9 shape in the middle of a wider
// picture, and the renderer treats what is beside them: out of focus (1) or black (2). It shows the sides while a menu
// shows, which it tells by what the frame draws:
//   - the world's lighting composite drawn (vk_draw.cpp world_drawn_at): play, no menu, no sides;
//   - the blur of the last picture drawn (vk_draw.cpp wheel_drawn_at, program 02ff9920): the item wheel's background, the
//     last frame of play blurred over the whole picture, which the game keeps whole (host/oot_wide_hud.h's keep class 0):
//     its sides are the game's own, none of ours.
// The same program also draws the backdrop of a system menu opened over the title (the file select, seen in the game: the
// title movie behind it, blurred). That backdrop is the system menus' (keep class 1), which the row puts in the middle
// 16:9, so it needs the sides: taken for the wheel's it got none, and the sharp movie stood beside the blurred middle.
// The program alone cannot tell the two apart; the host can, by the game's menu screens that run (MkwVkHost.wide_backdrop:
// a menu whose backdrop is the centred one). While such a menu runs the blur drawn is its backdrop and not the wheel's.
#pragma once
#include <cstdint>

namespace mkwvk::wide_sides_rule {

/// (a frame the world or the wheel skips: 3 presents' grace)
constexpr int64_t kGrace = 3;

/// The sides to show: 0 none, else the row's value (1 out of focus, 2 black). setting: the Ultrawide menus row. margin: the
/// middle 16:9's margin at either side, 0 for a 16:9 picture or while the host wants none (the filled title movie alone).
/// now, world_at, blur_at: the present now, and the last ones whose frames drew the world and the blur of the last
/// picture. centred_menu: the host says a menu with the centred backdrop runs
constexpr int show(int setting, float margin, int64_t now, int64_t world_at, int64_t blur_at, bool centred_menu) {
    if (!setting || !(margin > 0.0f)) return 0;
    if (now - world_at <= kGrace) return 0;                    // (the world: play)
    if (now - blur_at <= kGrace && !centred_menu) return 0;    // (the item wheel's background, whole by the game)
    return setting;
}

}  // namespace mkwvk::wide_sides_rule
