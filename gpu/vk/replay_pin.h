// (Triforce, 11-22, the performance audit's THREAD-09, after Source A's) Where a thread may run while it replays, on a processor with
// cores of more than one kind.
//
// A thread that replays is pinned for that time to the core the host keeps for the replay (vk_replay.cpp ReplayPin,
// hos_reserved_cpus). That core is kept from the game's threads, not from other programs': on a 6+8-core hybrid processor Source A
// saw Windows park one of its two logical processors while another program's thread at priority 15 held the other 30 to 40 ms at a
// time, and the pinned replay, raised only to the highest of the normal levels, waited for it ready to run: 14 to 37 frames over
// 40 ms in a 40 s run. So on a processor of two kinds of core the pin is soft: the thread may run on the reserved core and on the
// fastest-kind cores among its own processors, its ideal processor is the reserved core's last logical processor, and the core it
// is on when the pin starts is left out for that pin, so that it moves at once, to the reserved core when that is free. Widening
// alone would leave it where it is: that is the "only preferring the core" that gained nothing. After the replay it has the
// affinity and the ideal processor it had.
//
// A processor of one kind of core keeps the strict pin: there the pin itself is what was measured to help, and nothing changes.
//   RX_VK_REPLAY_PIN_SOFT unset or 1: soft where the cores are of more than one kind; 0: strict everywhere, as before;
//   2: soft everywhere (the lab).
// Plain rules over masks, no system calls: tests/test_replay_pin_soft.py runs them over made-up processors.
#pragma once

#include <cstdint>
#include <cstdlib>

namespace mkwvk::replay_pin {

constexpr int kStrict = 0, kHybrid = 1, kAlways = 2;

/// RX_VK_REPLAY_PIN_SOFT's value: unset (or empty, or 1) kHybrid, 0 (or anything that is no number above 0) kStrict, 2 and more kAlways
inline int mode(const char* env) {
    if (!env || !*env) return kHybrid;
    const int v = std::atoi(env);
    return v <= 0 ? kStrict : v == 1 ? kHybrid : kAlways;
}

struct Kinds {
    uint64_t fastest = 0;   // (the logical processors of the cores with the highest efficiency class)
    bool hybrid = false;    // (some core is of a lower class)
};
/// The fastest kind of core among n cores (each core's logical processors and its EfficiencyClass, higher the faster, as Windows
/// lists them; a core with no processors is not one). hybrid only when a listed core is not of that kind
inline Kinds kinds(const uint64_t* masks, const unsigned char* classes, int n) {
    Kinds k;
    int best = -1;
    uint64_t all = 0;
    for (int i = 0; i < n; i++) {
        if (!masks[i]) continue;
        all |= masks[i];
        if ((int)classes[i] > best) best = classes[i], k.fastest = masks[i];
        else if ((int)classes[i] == best) k.fastest |= masks[i];
    }
    k.hybrid = k.fastest != all;
    return k;
}

/// Whether the pin is soft: by the switch and the processor's kinds
inline bool soft(int mode, bool hybrid) {
    return mode >= kAlways || (mode == kHybrid && hybrid);
}

/// The soft pin's processors: the reserved core, and the fastest-kind ones among the thread's own (own: its affinity before the
/// pin, which keeps a thread held to one die, or to anything else, inside what it was held to). Never fewer than the reserved core
inline uint64_t wide(uint64_t reserved, uint64_t fastest, uint64_t own) {
    return reserved | (fastest & own);
}

/// The same without the core the thread is on now (now: that core's logical processors, 0 when not known), so that the thread
/// moves at once. Left whole when it is on the reserved core already or when nothing else would be left
inline uint64_t moved(uint64_t wide, uint64_t reserved, uint64_t now) {
    if (!now || (now & reserved) || !(wide & ~now)) return wide;
    return wide & ~now;
}

/// The ideal processor of a replaying thread: the reserved core's last logical processor (-1: no core reserved)
inline int ideal(uint64_t reserved) {
    return reserved ? 63 - __builtin_clzll(reserved) : -1;
}

} // namespace mkwvk::replay_pin
