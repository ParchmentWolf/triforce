/* (Triforce, lab) In-run A/B. Two runs of one build differ by more than most changes are worth (the other programs on the GPU,
   which cores the threads landed on, the scene's state), so a change's effect is measured inside ONE run: the frames go in
   phases of RX_VK_LAB_AB_FRAMES presents (300): none, knob 1, none, knob 2, ... and around again, and the frame trace
   (RX_VK_FRAME_TRACE, vk_replay.cpp status_tick) carries the phase's knob in its last column (0: none, k: the k-th knob;
   negative for a phase's first RX_VK_LAB_AB_SKIP frames (30), which a reader leaves out). perf\lowend\lab_ab.py compares each
   knob's phases with the none-phases on both sides of them.

   RX_VK_LAB_AB=<name>[:<value>],<name>[:<value>],...   (at most 16)
   Knobs joined by '+' are one knob that turns each of them on ("reclast+tlrec+rbsettle").
   A knob named d_<site> is a delay: a busy wait of <value> microseconds at that site, at most once a frame (delay(), below):
   what the frame's time answers to a part of it taking longer, which is whether that part is on the frame's critical path
   (1 ms in for 1 ms of delay) or has slack (nothing). Any other name is a switch the code reads with on("<name>").
   (Triforce, 11-22, the performance audit's REPLAY-51, after Source B's) A knob named e_<event> is a delay at every
   occurrence of an event, not once a frame: a busy wait of <value> NANOseconds at each draw (e_draw) or dispatch
   (e_dispatch), first in vk_draw.cpp's draw() and dispatch() so that the profiles leave it out, on whichever thread
   records, counted (each(), below). The frame's change against the time spun says how much of that path is on the frame's
   critical path: 200 ns at ~3,050 draws a frame is 0.6 ms of work. One line a phase gives each knob's spins and ms a second
   (each_report). d_present_after is d_present's after: the same wait just after the present's drain(0), where d_present is
   just before it. Pin RX_VK_PARALLEL for e_ knobs: Automatic moves draws between threads (the replay warns).
   Not for players: nothing reads these without the variable. */
#pragma once

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace mkwvk::lab_ab {

struct Knob {
    char name[64];
    int64_t value;
};
inline Knob knobs[16];
inline int n_knobs = -1;                    // (-1: the variable not read yet)
inline std::atomic<int> active{0};          // (0: none; k: knobs[k - 1])
inline std::atomic<uint64_t> frame_no{0};   // (presents counted here)
inline std::atomic<uint64_t> fired[16];     // (the frame each delay last waited in)
inline std::atomic<uint32_t> pres_thread{0};   // (the thread that presents: the game's Presentation thread, in the plain mode)
inline int64_t phase_frames = 300, skip_frames = 30;
// ((Triforce, 11-22, REPLAY-51) the e_ knobs: each event's wait in this phase (ns, 0: none), and what was spun)
enum Each { E_DRAW = 0, E_DISPATCH = 1, E_COUNT = 2 };
inline const char* const each_names[E_COUNT] = {"e_draw", "e_dispatch"};
inline std::atomic<int64_t> each_ns[E_COUNT];
inline std::atomic<uint64_t> each_spins[E_COUNT], each_spun_ns[E_COUNT];
struct EachPhase {   // (the presenting thread's: the phase being counted)
    int knob = 0;
    std::chrono::steady_clock::time_point since{};
};
inline EachPhase each_phase;
inline char each_line[256];   // (the line of a phase just over, for the replay to log; empty: none)

inline void init() {
    if (n_knobs >= 0) return;
    int n = 0;
    const char* e = getenv("RX_VK_LAB_AB");
    while (e && *e && n < 16) {
        const char* end = strchr(e, ',');
        const size_t len = end ? (size_t)(end - e) : strlen(e);
        char item[96] = {};
        memcpy(item, e, len < sizeof item - 1 ? len : sizeof item - 1);
        char* colon = strchr(item, ':');
        knobs[n].value = colon ? atoll(colon + 1) : 1;
        if (colon) *colon = 0;
        strncpy(knobs[n].name, item, sizeof knobs[n].name - 1);
        if (knobs[n].name[0]) n++;
        e = end ? end + 1 : nullptr;
    }
    if (const char* f = getenv("RX_VK_LAB_AB_FRAMES")) phase_frames = atoll(f) > 0 ? atoll(f) : 300;
    if (const char* s = getenv("RX_VK_LAB_AB_SKIP")) skip_frames = atoll(s);
    n_knobs = n;
}
/// ((Triforce, 11-22, REPLAY-51) Whether any knob is an e_ one (the replay warns once unless RX_VK_PARALLEL is pinned)
inline bool any_each() {
    for (int i = 0; i < n_knobs; i++)
        for (const char* name : each_names)
            if (!strcmp(knobs[i].name, name)) return true;
    return false;
}
/// (phase_tick, the presenting thread) The phase is knob k (0: none): at a change, the line of the phase that ended (each_line,
/// when it had an e_ knob: its spins and ms a second), and the events' waits for this one
inline void each_tick(int k) {
    if (k == each_phase.knob && each_phase.since.time_since_epoch().count()) return;
    const auto now = std::chrono::steady_clock::now();
    each_line[0] = 0;
    const int was = each_phase.knob;
    if (was > 0 && each_phase.since.time_since_epoch().count()) {
        const double s = std::chrono::duration<double>(now - each_phase.since).count();
        for (int e = 0; e < E_COUNT; e++) {
            if (strcmp(knobs[was - 1].name, each_names[e])) continue;
            const uint64_t spins = each_spins[e].exchange(0, std::memory_order_relaxed);
            const uint64_t ns = each_spun_ns[e].exchange(0, std::memory_order_relaxed);
            snprintf(each_line, sizeof each_line, "vk: lab A/B: phase %s:%lld over: %.0f waits a second, %.2f ms a second spun "
                     "(%llu waits in %.1f s)", each_names[e], (long long)knobs[was - 1].value, s > 0 ? spins / s : 0.0,
                     s > 0 ? ns / 1e6 / s : 0.0, (unsigned long long)spins, s);
        }
    }
    for (int e = 0; e < E_COUNT; e++)
        each_ns[e].store(k > 0 && !strcmp(knobs[k - 1].name, each_names[e]) ? std::max<int64_t>(0, knobs[k - 1].value) : 0,
                         std::memory_order_relaxed);
    each_phase.knob = k, each_phase.since = now;
}
/// At every occurrence of an event (first in draw() and dispatch()): one relaxed load without its knob; with it, a busy wait
/// of the knob's nanoseconds, counted
inline void each(int event) {
    const int64_t ns = each_ns[event].load(std::memory_order_relaxed);
    if (!ns) return;
    const auto t0 = std::chrono::steady_clock::now(), until = t0 + std::chrono::nanoseconds(ns);
    auto now = t0;
    while (now < until) {
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
        __builtin_ia32_pause();
#endif
        now = std::chrono::steady_clock::now();
    }
    each_spins[event].fetch_add(1, std::memory_order_relaxed);
    each_spun_ns[event].fetch_add((uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(now - t0).count(),
                                  std::memory_order_relaxed);
}
/// Once a present, on the presenting thread: the phase this frame belongs to (the trace's column)
inline int phase_tick() {
    init();
    if (!n_knobs) return 0;
    const uint64_t f = frame_no.fetch_add(1) + 1;
    const uint64_t phase = f / (uint64_t)phase_frames;        // (0 none, 1 knob 1, 2 none, 3 knob 2, ...)
    const int k = (phase & 1) ? (int)((phase / 2) % (uint64_t)n_knobs) + 1 : 0;
    active.store(k, std::memory_order_relaxed);
    each_tick(k);   // ((Triforce, 11-22, REPLAY-51) the e_ knobs' waits for this phase, and the line of the one before)
    const bool settling = (int64_t)(f % (uint64_t)phase_frames) < skip_frames;
    return settling ? -(k + 1) : k;   // (-1: none, settling; -(k + 1): knob k, settling)
}
/// Is this switch on in this phase: the phase's knob is it, or names it among several joined by '+' ("reclast+tlrec":
/// both on in that knob's phases, so a combination is one knob)
inline bool on(const char* name) {
    if (n_knobs <= 0) return false;
    const int k = active.load(std::memory_order_relaxed);
    if (k <= 0) return false;
    const size_t len = strlen(name);
    for (const char* p = knobs[k - 1].name; p && *p;) {
        const char* plus = strchr(p, '+');
        const size_t n = plus ? (size_t)(plus - p) : strlen(p);
        if (n == len && !strncmp(p, name, len)) return true;
        p = plus ? plus + 1 : nullptr;
    }
    return false;
}
inline int64_t value_of(const char* name, int64_t otherwise) {
    if (n_knobs <= 0) return otherwise;
    const int k = active.load(std::memory_order_relaxed);
    return k > 0 && !strcmp(knobs[k - 1].name, name) ? knobs[k - 1].value : otherwise;
}
/// The delay site <site> (knob "d_<site>"): a busy wait of its microseconds, once a frame
inline void delay(const char* site) {
    if (n_knobs <= 0) return;
    const int k = active.load(std::memory_order_relaxed);
    if (k <= 0 || knobs[k - 1].name[0] != 'd' || knobs[k - 1].name[1] != '_' || strcmp(knobs[k - 1].name + 2, site)) return;
    const uint64_t f = frame_no.load(std::memory_order_relaxed);
    if (fired[k - 1].exchange(f, std::memory_order_relaxed) == f) return;
    const auto until = std::chrono::steady_clock::now() + std::chrono::microseconds(knobs[k - 1].value);
    while (std::chrono::steady_clock::now() < until) {
    }
}

}   // namespace mkwvk::lab_ab
