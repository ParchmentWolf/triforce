// (Triforce, 11-22, the performance audit's THREAD-11, after Source B's) The hold of a fence wait that needs stopped work.
//
// A wait of the game's for a fence whose work is stopped at an event's wait gives the other queues a moment to let it on (up to
// RX_VK_WAIT_HOLD_US, 3 ms) before it forces it: vk_replay.cpp wait(). That hold is a loop of looks: flush, the timeline's value,
// the order lock to ask whether the stopped work is still needed, and a yield of the processor (SwitchToThread). The main thread
// comes there about 15 times a second.
//
// Counted now, in the order line: the holds, their looks, the time held, the takes of the order lock, and how each hold ended
// (the fence done, the stopped work let on by another thread, the wait's own time up, or forced on at the hold's bound).
//
// RX_VK_WAIT_HOLD_PAUSE_US=<us>, off (0) unless set, 1000 at most: between two looks a gap of PAUSEs, 16 at a time until that
// long has passed, instead of a yield a look (Source B's gap of 2 us on a like loop left the other half of the core free and
// measured 59.2 to 59.9 fps there, on a loop that runs far more often than this one); and the order lock taken only when it can
// say something new. What the lock is asked (is the oldest unfinished stopped submission at or below this fence) is state that
// changes only inside a section of that lock, and the lock counts the sections that have left. The waiter reads that count
// inside its own section; one more than that is its own section having left; while the count is still that, no other section
// has finished and the answer is the one it has. A section in progress is seen when it leaves, which is when a waiter blocked on
// the lock would have got it. The fence's own value is still read at every look, and the bound and the forced drain stay.
// A signal of the CPU's is the one thing that reaches the order without a section: it is only queued (ev_cpu_any), and acts in
// the next section that looks at the stopped queues. While one is queued the lock is taken at every look, as before, so that a
// look made inside the waiter's own section (the audit's SYNC-59 gives the hold one) is never skipped.
//
// Plain rules: tests/test_wait_hold_pause.py runs them and the loop cut out of vk_replay.cpp.
#pragma once

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

namespace mkwvk::wait_hold {

constexpr int64_t kMostUs = 1000;
constexpr int kPauses = 16;   // (PAUSEs between two looks at the clock)

/// RX_VK_WAIT_HOLD_PAUSE_US in nanoseconds: 0 (unset, empty, no number, or 0): a yield a look and the lock at each, as before
inline int64_t pause_ns(const char* env) {
    if (!env || !*env) return 0;
    const long long us = std::atoll(env);
    return us <= 0 ? 0 : (us > kMostUs ? kMostUs : us) * 1000;
}

/// Whether this look takes the order lock. pause: pause_ns's; asked: the waiter has asked under the lock before, and `seen` is the
/// lock's count of sections that had left when it did (read inside its section); left: that count now; signal: a signal of the
/// CPU's is queued and no section has acted on it yet
inline bool takes_lock(int64_t pause, bool asked, uint64_t seen, uint64_t left, bool signal) {
    return !pause || !asked || signal || left != seen + 1;
}

/// The gap between two looks: pause() kPauses at a time until `ns` have passed on now()
template <class Now, class Pause>
inline void gap(int64_t ns, Now now, Pause pause) {
    const int64_t until = now() + ns;
    do {
        for (int i = 0; i < kPauses; i++) pause();
    } while (now() < until);
}

/// How a hold ended
enum End { kMet, kLetOn, kTimedOut, kForced, kEnds };

/// What the order line says of the holds (relaxed counts: the waiters are the game's threads, each on its own)
struct Stats {
    std::atomic<int64_t> holds{0}, looks{0}, locks{0}, held_ns{0}, ended[kEnds] = {};
    void done(End how, int64_t looked, int64_t locked, int64_t ns) {
        holds.fetch_add(1, std::memory_order_relaxed);
        looks.fetch_add(looked, std::memory_order_relaxed);
        locks.fetch_add(locked, std::memory_order_relaxed);
        held_ns.fetch_add(ns, std::memory_order_relaxed);
        ended[how].fetch_add(1, std::memory_order_relaxed);
    }
};
inline int describe(const Stats& s, int64_t pause, char* out, size_t cap) {
    return snprintf(out, cap, "vk: fence waits held for stopped work: %lld holds, %lld looks, %.1f ms held, the order lock taken %lld "
                    "times; ended by the fence done %lld, the work let on %lld, the wait's time up %lld, forced on at the bound %lld "
                    "(RX_VK_WAIT_HOLD_PAUSE_US=%lld)", (long long)s.holds.load(), (long long)s.looks.load(), (double)s.held_ns.load() / 1e6,
                    (long long)s.locks.load(), (long long)s.ended[kMet].load(), (long long)s.ended[kLetOn].load(),
                    (long long)s.ended[kTimedOut].load(), (long long)s.ended[kForced].load(), (long long)(pause / 1000));
}

} // namespace mkwvk::wait_hold
