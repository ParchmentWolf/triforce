// (Triforce, 11-21, the upscaler audit's UPS-05) A fixed multiplier's frames, no more than the display can show.
//
// The Frame generation row's 2x to 8x make that many frames for each of the game's whatever the display's refresh rate
// is; only the row's Auto goes by it. The owner's log of 11-20 has 5x on a 165 Hz display with the game near 66 frames a
// second: 1,655 frames shown in every 5 s (331 a second, two for each refresh), each present call 2.2 to 3.0 ms where it
// takes 0.03 ms without frame generation, and the display thread's line "0 frames shown on time, 1655 late". Half of the
// made frames were never on the screen (the swapchain is mailbox: the newest at each refresh), and each was a pass over
// the whole picture and a present the display thread could not keep up with.
//
// With the switch, a fixed multiplier makes no more frames than refreshes fall in one frame of the game: the game's
// recent frame time over the display's period, rounded up, a tenth of a refresh forgiven so a game at a whole fraction
// of the refresh rate is not given one more for its frames' jitter. Never more than the row asks, never fewer than the
// game's own frame. The row's Auto and AMD FSR's own are not touched.
//
// RX_VK_FRAMEGEN_REFRESH=1: on. Off unless set (the row's number is the frames made, as before): it changes what a row
// the player set shows, so it is the owner's to turn on.
//
// No Vulkan: tests/test_framegen_refresh.py compiles this.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace framegen_refresh {

/// RX_VK_FRAMEGEN_REFRESH (value, null when unset): on when it is not 0; unset, off
inline bool on(const char* value) { return value && *value && std::atoi(value) != 0; }

/// The frames shown for each of the game's (the game's own among them) with a fixed multiplier m, the game's frames game_ns
/// apart, the display refreshing every period_ns. An unknown frame time or period: m
inline int frames(int m, int64_t game_ns, int64_t period_ns) {
    if (m <= 1 || game_ns <= 0 || period_ns <= 0) return m;
    // (the refreshes in a frame of the game, rounded up, a tenth of one forgiven: ceil(game / period - 0.1))
    const int64_t most = (game_ns * 10 + period_ns * 9 - 1) / (period_ns * 10);
    return most < 1 ? 1 : most < m ? (int)most : m;
}

/// The display's period for a refresh rate in mHz (vk_main.cpp display_refresh_mhz); 0 when it is not known
inline int64_t period_ns(int refresh_mhz) { return refresh_mhz > 0 ? (int64_t)(1000000000000LL / refresh_mhz) : 0; }

}   // namespace framegen_refresh
