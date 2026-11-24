// (Triforce, 11-22) N64 Classic at work (n64-classic-mode-plan.md): what is in effect for the frame being recorded, for the
// passes that draw it (vk_draw.cpp n64_upscale) and for what it stands in front of (vk_temporal.cpp temporal_mode,
// vk_fsr3.cpp fsr3_wanted, vk_aa.cpp). The rules themselves are n64_rules.h.
//
// The Insert menu's N64 Classic row (Graphics) and its Remembered page (step 5), RX_VK_N64=<0..2> and the lab's switches over
// them for a run. Off (the default), nothing here is on and every caller does what it did before.
#pragma once

#include <cstdint>

#include "n64_rules.h"

namespace mkwvk {

/// The N64 Classic row's value in effect (n64_rules.h OFF, FAITHFUL, REMEMBERED): the Insert menu's row (opts.n64_classic),
/// RX_VK_N64 over it for a run
int n64_preset();
/// RX_VK_N64 sets the mode for this run (the row then has nothing to choose, and F7 does nothing)
bool n64_env_set();
/// The frame's look: the preset's (Remembered's from its rows), the lab's switches over it (n64_rules.h with_env)
n64_rules::Look n64_look();
/// N64 Classic's 3D pass takes the gameplay upscale this frame: the mode is on and the scene is the game's B10G11R11 (not a
/// RenoDX run's RGBA16F, n64_rules.h three_d_runs). What DLSS, FSR and the game's SMAA step aside for
bool n64_3d_now();
/// The preset while the 3D pass takes the upscale (n64_3d_now), else OFF: what n64_rules.h upscaler and anti_aliasing are
/// asked with, so DLSS, FSR and the game's SMAA step aside only while the pass draws in their place
int n64_in_front();
/// (step 4) N64 Classic's TV draws at the window this present: the look's TV on, or (step 8) the TV switching off and on, and
/// not on HDR Native's PQ picture (native_pq) nor while DLSS frame generation makes its frames from the finished image
/// (n64_rules.h tv_draws)
bool n64_tv_now(bool native_pq);
/// (step 8) Once a present (vk_replay.cpp, beside the texture blur's tick): the switch from the preset shown to the one
/// chosen (n64_rules.h Switch), half a second of the TV switching off and on at an F7 or a change of the row, the preset
/// the passes and the host go by changing at its middle. native_pq: HOS Native's picture, where no TV pass draws it
void n64_tick(bool native_pq);
/// (step 8) The preset the passes and the host go by now: the one chosen (n64_preset), or while a switch closes, the one
/// before it. n64_look is its look
int n64_shown();
/// (step 8) The TV's frame of the switch now (n64_rules.h AnimFrame; done: none running)
n64_rules::AnimFrame n64_anim();

// ((11-22, after the owner's test) The TV's screen at a present, for the options drawn under it (vk_menu.cpp menu_tv_layer)
// and for the mouse (n64_screen_point). The present (vk_replay.cpp present_image) says where the picture goes in the window
// before its window pass (begin) and is done after it (end); the TV's pass says it drew, with what curve and squash, in
// between (drawn). Outside a present's window pass (a headless shot's) there is no place: nothing goes under the TV)

/// The present's window pass begins: the picture goes to x, y, w, h of a window_w x window_h window image
void n64_screen_begin(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint32_t window_w, uint32_t window_h);
/// The TV drew this present's picture, through this curve and squash (n64_tv.comp's curve, anim_x, anim_y)
void n64_screen_drawn(float curve, float anim_x, float anim_y);
/// The present's window pass is over: what it drew is what the mouse goes by until the next one
void n64_screen_end();
/// Between begin and end: where the picture goes, and the window's size. false outside a present's window pass
bool n64_screen_place(uint32_t* x, uint32_t* y, uint32_t* w, uint32_t* h, uint32_t* window_w, uint32_t* window_h);
/// A point of a win_w x win_h window (the cursor's, in its pixels) taken to the point of the picture the TV showed there at
/// the last present (n64_rules.h screen_point): where the options' and the game's own controls were drawn. As it is when
/// the TV did not draw that present. Any thread (the host's game menus ask from the game's)
void n64_screen_point(int* x, int* y, int win_w, int win_h);

} // namespace mkwvk
