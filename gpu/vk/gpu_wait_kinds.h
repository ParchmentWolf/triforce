// (Triforce, 11-22, the performance audit's SYNC-27, after Source A's) The host's time in calls that block on the GPU,
// counted by kind where the Vulkan calls are wrapped (vk_work.h).
//
// The log's "GPU-bound wait" counts only the waits for a recording slot: it reads about 0 while threads wait on the GPU
// elsewhere (a fence of the game's, a write-back, the present's frame fence, a device idle, a query read that waits).
// Those were timed apart or not at all. Here every blocking wait is timed in one place and summed by kind:
//   fences     vkWaitForFences with a timeout above 0
//   timelines  vkWaitSemaphores with a timeout above 0
//   idle       vkQueueWaitIdle, vkDeviceWaitIdle
//   queries    vkGetQueryPoolResults with VK_QUERY_RESULT_WAIT_BIT
// A poll (timeout 0, no wait bit) counts nothing. A wait made inside another counts once, as the outer one (a depth of
// the thread's). A wait inside an Exclude scope counts nothing: pacing (the driver's low-latency sleep), which is not a
// wait for the GPU's work. The totals only grow; each reader keeps its own last values (Reader), so the log's line and
// the frame trace's column each see every nanosecond.
//
// The cost is two clock reads a blocking wait. RX_VK_GPU_WAITS=0, or the lab knob nogpuwaits in its phases: the calls
// straight through, nothing counted. No Vulkan here: tests/test_gpu_waits.py compiles it.
#pragma once
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>

#include "lab_ab.h"

namespace gpu_wait_kinds {

enum Kind : int { FENCE = 0, TIMELINE = 1, IDLE = 2, QUERY = 3, KINDS = 4 };

struct Totals {
    std::atomic<int64_t> ns[KINDS]{}, n[KINDS]{};
};
inline Totals totals;                   // (every thread's, since the start: they only grow)
inline thread_local int depth = 0;      // (this thread is inside a counted wait)
inline thread_local int excluded = 0;   // (this thread is inside an Exclude scope)

/// Counted at all (RX_VK_GPU_WAITS, read once; on unless 0), and not in the lab knob's phases
inline bool on() {
    static const bool env = [] {
        const char* e = getenv("RX_VK_GPU_WAITS");
        return !(e && *e && atoi(e) == 0);
    }();
    return env && !mkwvk::lab_ab::on("nogpuwaits");
}

/// The waits made on this thread while one of these lives count nothing
struct Exclude {
    Exclude() { excluded++; }
    ~Exclude() { excluded--; }
    Exclude(const Exclude&) = delete;
    Exclude& operator=(const Exclude&) = delete;
};

/// call(), and its time under `kind` when it blocks (blocks: a timeout above 0, the wait bit), unless this thread is
/// inside a counted wait or an Exclude scope, or the count is off. What call() returns
template <class Call>
inline auto timed(Kind kind, bool blocks, Call&& call) -> decltype(call()) {
    if (!blocks || depth || excluded || !on()) return call();
    depth++;
    const auto t0 = std::chrono::steady_clock::now();
    const auto result = call();
    const int64_t ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - t0).count();
    depth--;
    totals.ns[kind].fetch_add(ns, std::memory_order_relaxed);
    totals.n[kind].fetch_add(1, std::memory_order_relaxed);
    return result;
}

/// One reader's last values: take() gives what was counted since its last take (ns and waits by kind, either may be
/// null) and returns the nanoseconds of all kinds together
struct Reader {
    int64_t last_ns[KINDS]{}, last_n[KINDS]{};
    int64_t take(int64_t* ns_by_kind, int64_t* n_by_kind) {
        int64_t all = 0;
        for (int k = 0; k < KINDS; k++) {
            const int64_t ns = totals.ns[k].load(std::memory_order_relaxed), n = totals.n[k].load(std::memory_order_relaxed);
            if (ns_by_kind) ns_by_kind[k] = ns - last_ns[k];
            if (n_by_kind) n_by_kind[k] = n - last_n[k];
            all += ns - last_ns[k];
            last_ns[k] = ns, last_n[k] = n;
        }
        return all;
    }
};

}   // namespace gpu_wait_kinds
