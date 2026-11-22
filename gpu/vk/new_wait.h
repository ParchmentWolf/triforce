// (Triforce, 11-22, the performance audit's OS-04, after Source A's and Source B's) A `new` of the renderer's that fails at
// Windows' commit limit waits before it throws.
//
// A refused allocation in the renderer was an uncaught std::bad_alloc: the game ended. At the commit limit (RAM and the page
// file full) a refusal often ends in moments, as the page file grows or commit is given back, so the renderer's new handler
// (vk_main.cpp new_refused, set in mkwvk_init) sleeps 50 ms and lets the allocation be tried again, for up to 5 s a thread
// (HOS_COMMIT_WAIT_MS, the host's switch for the same wait: 0, none), and throws after that. Only while the system has less
// than 4 GiB of commit left: a `new` refused with more than that free was not refused for the limit (a size no memory could
// hold), and throws at once, as before. Source A's is the wait; the 4 GiB rule is Source B's, written anew here.
//
// A `new (std::nothrow)` whose caller has its own answer to a refusal (a staging block, a copy that is only a saving, the
// recorder's ring) is not held up: NoWait around it makes the handler throw at once, and the nothrow new answers null.
//
// The rule alone, no system calls: tests/test_commit_limit.py compiles it.
#pragma once

#include <cstdint>
#include <cstdlib>

namespace mkwvk::new_wait {

constexpr uint64_t kNear = 4ull << 30;   // (the commit left under which a refusal is taken for the limit's)
constexpr int kStepMs = 50, kWaitMs = 5000, kMostMs = 60000;

/// HOS_COMMIT_WAIT_MS in ms: not set (or empty) 5000; a number that many, 0 and less none, 60000 at most
inline int wait_ms(const char* env) {
    if (!env || !*env) return kWaitMs;
    const long v = std::atol(env);
    return v <= 0 ? 0 : v > kMostMs ? kMostMs : (int)v;
}

inline thread_local int t_waited_ms = 0;   // (what this thread has waited in all: its 5 s are not given twice)
inline thread_local int t_no_wait = 0;     // (NoWait scopes open on this thread)

/// Around a new (std::nothrow) that must answer at once
struct NoWait {
    NoWait() { t_no_wait++; }
    ~NoWait() { t_no_wait--; }
    NoWait(const NoWait&) = delete;
    NoWait& operator=(const NoWait&) = delete;
};

/// A `new` was refused. true: sleep a step and let it be tried again; false: throw. known and avail: the system's commit left,
/// when it could be read; waited_ms: this thread's waits so far; max_ms: wait_ms's; no_wait: NoWait scopes open
inline bool waits(bool known, uint64_t avail, int waited_ms, int max_ms, int no_wait) {
    return !no_wait && known && avail < kNear && waited_ms < max_ms;
}

} // namespace mkwvk::new_wait
