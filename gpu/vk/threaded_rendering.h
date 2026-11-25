// (Triforce) Threaded rendering, the Debug tab's row (vk_menu.cpp, threaded_rendering= in triforce_options.ini) and its switch
// RX_VK_THREADED (over the row: 0 or off, 1 or on, 2 or auto): one rule for every reader. Off by default, the row and the switch
// both: Off changes nothing at all, every piece below keeps its own switch and default as before.
//
// What On turns on, as one design (the threads of a renderer of the same base, rewritten there as one: a render thread for the
// replay, the recorder thread beside it handed whole parts, the presents on a thread of their own, parts that end where the
// game ends its render passes). Each piece is one Triforce already has, driven from here, not a second one:
//
//   the render thread       the replay thread (RX_VK_ASYNC=1, vk_replay.cpp async_on, with Triforce's rules: async_rules.h);
//                           the host asks the renderer whether it runs (HOS_OPT_RENDER_THREAD: host/rx_backend.c rx_async_replay)
//   the recorder thread     vk_recorder.h's (RX_VK_RECORDER=thread), handed a part at a time: its packets published at the part's
//                           end and its end and submit made by the recorder (RX_VK_RECORDER_PARTS), the recorder waiting on its
//                           ring between batches; the render thread goes on into the next part at once
//   the presents            the present thread (present_thread.h, RX_VK_PRESENT_THREAD), and the next image asked for on it
//                           right after each present (RX_VK_ACQUIRE_AHEAD) on every card, with a zero timeout where the driver
//                           waits in the acquire; not under frame generation or FIFO. Each present is held on the present
//                           thread until its blit is done on the GPU (vk_replay.cpp present_hold_for_blit, RX_VK_PRESENT_HOLD),
//                           and the next image asked for only after a present made as it is: the window is given only
//                           finished frames, in order (RX_VK_PRESENT_CHECK=1 counts any present that is not)
//   the parts               a submission's part ends where the game has ended its render pass, from 120 draws (the first part
//                           from 32), at 512 at the latest (vk_replay.cpp maybe_split; RX_VK_PART_MIN, RX_VK_PART_FIRST,
//                           RX_VK_PART_MAX), not every RX_VK_CHUNK draws wherever that falls
//
// Each piece's own switch, when set, still goes over this (RX_VK_ASYNC, RX_VK_RECORDER, RX_VK_RECORDER_PARTS,
// RX_VK_PRESENT_THREAD, RX_VK_ACQUIRE_AHEAD, RX_VK_CHUNK). The replay helper threads (the parallel replay) are not part of it:
// with the render thread on there are none, whatever their row says (vk_replay.cpp par_threads_max; RX_VK_PARALLEL or
// RX_VK_PARALLEL_AUTO still goes over this).
//
//   Off    (the default) as before: the replay on the game's submitting thread, the recorder as Triforce chooses it
//   On     all of the above, whatever the CPU
//   Auto   decided from the physical cores the process may run on (its affinity mask, a core's SMT siblings counted once):
//            kAutoCores (4) or more: all of the above;
//            fewer: off, as Off.
//          With no buffer-pool mirrors (an integrated GPU, RX_VK_MIRROR=0) the render thread, which runs a frame behind the
//          game, stays off; the recorder thread alone (with the rest of the design) from kAutoRecorderOnlyCores (6), else off.
//          And off where the run is not safe for it: the capture off (RX_VK_CAPTURE=0), RX_VK_LOW_SPEC, a frame dump
//          (RX_VK_DUMP), the bench (RX_VK_BENCH).
//
// Measured there (a Ryzen 9 9950X3D held to N cores, the Market's entrance, before the threads were rewritten): on 4 cores the
// render thread alone 67.6 / 67.9 fps against 65.5 / 65.0 serial; from 6 cores both threads 72.9 / 72.4 against 67.4 / 68.4.
// After the rewrite (a Ryzen 7 5700X3D held to 4 cores, RX 9070 XT): both threads 78.7 fps against the render thread alone's
// 64.6 (4 cores, 8 threads). The recorder alone at 6 or more cores without mirrors: +18.0% 1% lows, +5.6% fps in the Market.
// Not measured here: the coordinator's lab A/B is RX_VK_THREADED=0 against RX_VK_THREADED=1.
// Read once, at the start (vk_main.cpp threaded_choice): a change of the row applies at the next start.
// Plain code with no Vulkan or system calls: tests/test_threaded_rendering.py compiles it alone.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace mkwvk::threaded {

enum { OFF = 0, ON = 1, AUTO = 2 };   // (the row's values, in its order: Off, On, Auto; 0 the default)

/// Auto's tier, in physical cores the process may run on: from here the render thread and the recorder thread
constexpr unsigned kAutoCores = 4;
/// Auto with no buffer-pool mirrors: the recorder thread alone from here (4- and 5-core handhelds such as the Steam Deck stay off)
constexpr unsigned kAutoRecorderOnlyCores = 6;

enum class Why {
    On,                 // the row (or RX_VK_THREADED) says On
    Off,                // it says Off
    AutoUnsafe,         // Auto, and the run is not safe for it
    AutoFewCores,       // Auto, fewer than kAutoCores cores (or their count unknown: 0)
    AutoRecorderOnly,   // Auto, no mirrors, kAutoRecorderOnlyCores or more: the recorder thread alone
    AutoBothThreads,    // Auto, kAutoCores or more: the render thread and the recorder thread
};
/// The answer in two halves, each read by its own reader; on() is the design as a whole (the parts, the presents)
struct Choice {
    bool render_thread;     // the render thread (vk_replay.cpp async_on, RX_VK_ASYNC unset)
    bool recorder_thread;   // the recorder thread (vk_recorder.h, RX_VK_RECORDER unset)
    Why why;
    constexpr bool on() const { return render_thread || recorder_thread; }
};

/// RX_VK_THREADED's value as the row's: -1 unset or not one of them (the row decides)
inline int from_env(const char* e) {
    if (!e || !*e) return -1;
    if (!std::strcmp(e, "0") || !std::strcmp(e, "off") || !std::strcmp(e, "Off")) return OFF;
    if (!std::strcmp(e, "1") || !std::strcmp(e, "on") || !std::strcmp(e, "On")) return ON;
    if (!std::strcmp(e, "2") || !std::strcmp(e, "auto") || !std::strcmp(e, "Auto")) return AUTO;
    return -1;
}

/// What Auto picks for `cores` physical cores where the run is safe
constexpr Choice auto_picks(unsigned cores) {
    if (cores >= kAutoCores) return {true, true, Why::AutoBothThreads};
    return {false, false, Why::AutoFewCores};
}

/// The rule: the row's value (a value that is none of the row's is Off), the physical cores, whether the run is unsafe
constexpr Choice choose(int setting, unsigned cores, bool unsafe) {
    if (setting == ON) return {true, true, Why::On};
    if (setting != AUTO) return {false, false, Why::Off};
    if (unsafe) return {false, false, Why::AutoUnsafe};
    return auto_picks(cores);
}

/// Auto picked the threads: the caller's last check, one that reads the device (the buffer pools' mirrors), is asked only then
constexpr bool auto_picked(const Choice& c) { return c.why == Why::AutoBothThreads; }

/// Auto with no buffer-pool mirrors: the render thread off; the recorder thread alone from kAutoRecorderOnlyCores, else off
constexpr Choice without_mirrors(const Choice& c, unsigned cores) {
    if (c.why != Why::AutoBothThreads) return c;
    if (cores >= kAutoRecorderOnlyCores) return {false, true, Why::AutoRecorderOnly};
    return {false, false, Why::AutoUnsafe};
}

/// The start's line (vk_main.cpp logs it after "vk: Threaded rendering: "). `unsafe`: what made Auto not safe, or "no mirrors"
inline void describe(char* out, size_t size, const Choice& c, unsigned cores, const char* unsafe, bool by_env) {
    const char* src = by_env ? " (RX_VK_THREADED)" : "";
    switch (c.why) {
    case Why::On: std::snprintf(out, size, "On%s: the render thread, the recorder thread by part, the present thread", src); return;
    case Why::Off: std::snprintf(out, size, "Off%s: as before", src); return;
    case Why::AutoUnsafe: std::snprintf(out, size, "Auto%s: off (not safe on this run: %s)", src, unsafe ? unsafe : "?"); return;
    case Why::AutoFewCores:
        std::snprintf(out, size, "Auto%s: off (%u physical cores; on from %u)", src, cores, kAutoCores);
        return;
    case Why::AutoRecorderOnly:
        std::snprintf(out, size, "Auto%s: the recorder thread only (%u physical cores; the render thread off: %s)", src, cores,
                      unsafe ? unsafe : "?");
        return;
    case Why::AutoBothThreads:
        std::snprintf(out, size, "Auto%s: on, the render thread and the recorder thread (%u physical cores)", src, cores);
        return;
    }
    std::snprintf(out, size, "?");
}

} // namespace mkwvk::threaded
