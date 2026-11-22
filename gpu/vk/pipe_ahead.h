// Where the pipelines the draws first need stand in the last sessions' order, against where the draws are (no game, no GPU:
// the rules; vk_draw.cpp order_met, graphics_pipeline, draw_left_out_take). Apart from Vulkan so that tests/test_pipe_ahead.py
// runs them.
//
// (Triforce, 11-22, the performance audit's PIPE-81, after Source B's: its first step.) Where the precompile keeps no
// pipelines (light mode: precompile_keeps_all), every pipeline of a load is new at its first draw: linked there from its
// stage libraries, or by the warm a moment earlier (pipe_warm.h, pipe_order.h). The entry proposes building whole pipelines
// just ahead of the draws on light frames, from the order's next places, and keeping them; and it says to count first:
// each pipeline first drawn, its place ahead of where the draws are (pipe_order.h Front) or none, and whether the warm had
// linked it. Under a third within the window: stop, the builder is not worth its RAM and its compiles.
//
// This is that count, and only it: nothing is built or kept. A line every 600 presents while it grows (with the order used):
// within the window ahead, further ahead, behind, not in the order, and how many of those within the window the warm had
// linked; and whether the builder would be worth it by the entry's rule.
//
// RX_VK_PIPE_AHEAD=<places>: the window, 1024 unset (1 to 4096); 0: not counted.
#pragma once

#include <cstdint>
#include <cstdlib>

namespace pipe_ahead {

inline constexpr int64_t kWindow = 1024;
inline constexpr int64_t kMost = 4096;

/// RX_VK_PIPE_AHEAD: the window in places, kWindow unset; 0 off; clamped to 1..kMost
inline int64_t window(const char* env) {
    if (!env || !*env) return kWindow;
    const long long v = std::atoll(env);
    return v <= 0 ? 0 : v > kMost ? kMost : (int64_t)v;
}

enum class Where { None, Near, Far, Behind };
/// A pipeline first drawn at place in the order (-1: not in it), the draws at front (Front::furthest; -1: not yet placed,
/// counted from the order's start)
inline Where where(int64_t place, int64_t front, int64_t window_places) {
    if (place < 0) return Where::None;
    const int64_t from = front < 0 ? 0 : front;
    if (place < from) return Where::Behind;
    return place - from <= window_places ? Where::Near : Where::Far;
}
/// The entry's rule for the builder: worth it when a third or more of the pipelines first drawn were within the window
inline bool worth(int64_t within, int64_t all) {
    return all > 0 && within * 3 >= all;
}

}   // namespace pipe_ahead
