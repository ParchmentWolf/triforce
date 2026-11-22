// tests/test_gpu_waits.py: gpu/vk/gpu_wait_kinds.h (the host's time in calls that block on the GPU, by kind) and vk_work.h's
// five wrappers, put in the place of WRAPPERS and run over stand-ins for the driver's calls. No game, no GPU.
// (Triforce, 11-22, the performance audit's SYNC-27, after Source A's.)
//
// The calls below are vk_work.h's own five macros (their lines put in the place of MACROS), over its wrappers.
//   <exe> on    RX_VK_GPU_WAITS unset: everything below
//   <exe> off   RX_VK_GPU_WAITS=0 (set by the test): the calls are made, their results and arguments pass, nothing is counted
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>
#include "gpu_wait_kinds.h"

static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
namespace gw = gpu_wait_kinds;

// ---- stand-ins for the driver ----
typedef int VkResult;
typedef void* VkQueue;
typedef void* VkDevice;
typedef void* VkFence;
typedef void* VkQueryPool;
typedef uint32_t VkBool32;
typedef uint64_t VkDeviceSize;
typedef uint32_t VkQueryResultFlags;
struct VkSemaphoreWaitInfo { int tag; };
constexpr VkQueryResultFlags VK_QUERY_RESULT_64_BIT = 1, VK_QUERY_RESULT_WAIT_BIT = 2;
static int calls[5];
static int64_t sleep_us = 0;   // (what each driver call takes)
static uint64_t seen_timeout;
static VkQueryResultFlags seen_flags;
static void work() {
    if (sleep_us) std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
}
namespace vkx {
VkResult vkQueueWaitIdle(VkQueue q) { calls[0]++, work(); return q ? 11 : -1; }
VkResult vkDeviceWaitIdle(VkDevice d) { calls[1]++, work(); return d ? 12 : -1; }
VkResult vkWaitForFences(VkDevice d, uint32_t n, const VkFence* f, VkBool32 all, uint64_t timeout) {
    calls[2]++, seen_timeout = timeout, work();
    return d && n == 3 && f && all == 1 ? 13 : -1;
}
VkResult vkWaitSemaphores(VkDevice d, const VkSemaphoreWaitInfo* info, uint64_t timeout) {
    calls[3]++, seen_timeout = timeout, work();
    return d && info && info->tag == 77 ? 14 : -1;
}
VkResult vkGetQueryPoolResults(VkDevice d, VkQueryPool pool, uint32_t first, uint32_t count, size_t size, void* data, VkDeviceSize stride,
                               VkQueryResultFlags flags) {
    calls[4]++, seen_flags = flags, work();
    return d && pool && first == 4 && count == 5 && size == 40 && data && stride == 8 ? 15 : -1;
}
}   // namespace vkx

/* WRAPPERS */
// (the five macros as vk_work.h has them, the recorder's boundary a count here: the test puts their lines in the place of MACROS)
static int boundaries = 0;
namespace mkwvk::rec {
enum { B_vkQueueWaitIdle, B_vkDeviceWaitIdle, B_vkWaitForFences, B_vkWaitSemaphores, B_vkGetQueryPoolResults };
inline void boundary(int) { boundaries++; }
}
/* MACROS */

static int64_t ns_of(gw::Kind k) { return gw::totals.ns[k].load(); }
static int64_t n_of(gw::Kind k) { return gw::totals.n[k].load(); }
static int64_t n_all() { return n_of(gw::FENCE) + n_of(gw::TIMELINE) + n_of(gw::IDLE) + n_of(gw::QUERY); }

int main(int argc, char** argv) {
    const bool on = !(argc > 1 && std::string(argv[1]) == "off");
    int dev = 0, x = 0;
    VkFence list[3] = {&x, &x, &x};
    VkSemaphoreWaitInfo info{77};
    uint64_t data[5];
    CHECK(gw::on() == on);

    // ---- the wrappers: the driver is called with what they were given, its result comes back, and they count by kind when they block
    sleep_us = 0;
    CHECK(vkWaitForFences(&dev, 3, list, 1, 0) == 13 && calls[2] == 1 && seen_timeout == 0 && n_all() == 0);            // (a poll: nothing)
    CHECK(vkWaitSemaphores(&dev, &info, 0) == 14 && calls[3] == 1 && seen_timeout == 0 && n_all() == 0);              // (a poll: nothing)
    CHECK(vkGetQueryPoolResults(&dev, &x, 4, 5, 40, data, 8, VK_QUERY_RESULT_64_BIT) == 15 && calls[4] == 1 && seen_flags == VK_QUERY_RESULT_64_BIT && n_all() == 0);
    sleep_us = 3000;
    CHECK(vkWaitForFences(&dev, 3, list, 1, 250000000ull) == 13 && seen_timeout == 250000000ull);
    CHECK(n_of(gw::FENCE) == (on ? 1 : 0) && n_of(gw::TIMELINE) == 0 && n_of(gw::IDLE) == 0 && n_of(gw::QUERY) == 0);
    if (on) CHECK(ns_of(gw::FENCE) >= 3000000 && ns_of(gw::TIMELINE) == 0 && ns_of(gw::IDLE) == 0 && ns_of(gw::QUERY) == 0);
    CHECK(vkWaitSemaphores(&dev, &info, ~0ull) == 14 && seen_timeout == ~0ull && n_of(gw::TIMELINE) == (on ? 1 : 0));
    CHECK(vkQueueWaitIdle(&dev) == 11 && vkDeviceWaitIdle(&dev) == 12 && calls[0] == 1 && calls[1] == 1 && n_of(gw::IDLE) == (on ? 2 : 0));
    CHECK(vkGetQueryPoolResults(&dev, &x, 4, 5, 40, data, 8, VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT) == 15 && n_of(gw::QUERY) == (on ? 1 : 0));
    if (on) CHECK(ns_of(gw::TIMELINE) >= 3000000 && ns_of(gw::IDLE) >= 6000000 && ns_of(gw::QUERY) >= 3000000);
    CHECK(n_all() == (on ? 5 : 0) && gw::depth == 0 && gw::excluded == 0);
    CHECK(boundaries == 8);   // (the recorder's boundary before each of the eight calls so far, counted or not)
    if (!on) {
        CHECK(ns_of(gw::FENCE) + ns_of(gw::TIMELINE) + ns_of(gw::IDLE) + ns_of(gw::QUERY) == 0);
        gw::Reader r;
        CHECK(r.take(nullptr, nullptr) == 0);
        std::printf("off: the five calls made, nothing counted\n");
        return fails != 0;
    }

    // ---- two readers: each sees every nanosecond and every wait, whenever it reads
    gw::Reader a, b;
    int64_t ns[gw::KINDS], n[gw::KINDS];
    const int64_t a1 = a.take(ns, n);
    CHECK(a1 == ns[0] + ns[1] + ns[2] + ns[3] && n[gw::FENCE] == 1 && n[gw::TIMELINE] == 1 && n[gw::IDLE] == 2 && n[gw::QUERY] == 1);
    CHECK(a.take(ns, n) == 0 && n[0] + n[1] + n[2] + n[3] == 0);   // (nothing since)
    vkWaitForFences(&dev, 3, list, 1, 1);
    const int64_t a2 = a.take(ns, n);
    CHECK(a2 >= 3000000 && n[gw::FENCE] == 1 && ns[gw::FENCE] == a2);
    const int64_t b1 = b.take(ns, n);   // (the other reader reads once, later: all of it)
    CHECK(b1 == a1 + a2 && n[gw::FENCE] == 2 && n[0] + n[1] + n[2] + n[3] == 6);
    CHECK(b1 == ns_of(gw::FENCE) + ns_of(gw::TIMELINE) + ns_of(gw::IDLE) + ns_of(gw::QUERY));

    // ---- a wait inside a wait counts once, as the outer one
    {
        const int64_t f0 = n_of(gw::FENCE), t0 = n_of(gw::TIMELINE), fns = ns_of(gw::FENCE), tns = ns_of(gw::TIMELINE);
        const int r = gw::timed(gw::FENCE, true, [&] { return vkWaitSemaphores(&dev, &info, 5) + 100; });
        CHECK(r == 114 && n_of(gw::FENCE) == f0 + 1 && n_of(gw::TIMELINE) == t0 && ns_of(gw::TIMELINE) == tns);
        CHECK(ns_of(gw::FENCE) - fns >= 3000000 && gw::depth == 0);
    }
    // ---- excluded waits count nothing, and the count comes back after the scope (one inside another too)
    {
        const int64_t all0 = n_all();
        {
            const gw::Exclude pacing;
            CHECK(vkWaitSemaphores(&dev, &info, 100000000ull) == 14 && n_all() == all0);
            {
                const gw::Exclude again;
                CHECK(vkWaitForFences(&dev, 3, list, 1, 9) == 13 && n_all() == all0);
            }
            CHECK(vkQueueWaitIdle(&dev) == 11 && n_all() == all0);
        }
        CHECK(gw::excluded == 0 && vkQueueWaitIdle(&dev) == 11 && n_all() == all0 + 1);
    }
    // ---- every thread's waits are counted; one thread inside a wait or an Exclude does not hide another's
    {
        sleep_us = 0;
        const int64_t all0 = n_all();
        std::atomic<bool> go{false}, inside{false}, done{false};
        std::thread outer([&] {
            const gw::Exclude pacing;   // (this thread: excluded for as long as the others run)
            inside = true;
            while (!done) std::this_thread::yield();
        });
        while (!inside) std::this_thread::yield();
        std::vector<std::thread> threads;
        for (int t = 0; t < 4; t++)
            threads.emplace_back([&] {
                while (!go) std::this_thread::yield();
                for (int i = 0; i < 500; i++) vkWaitForFences(&dev, 3, list, 1, 1), vkWaitForFences(&dev, 3, list, 1, 0);
            });
        go = true;
        for (auto& t : threads) t.join();
        done = true;
        outer.join();
        CHECK(n_all() == all0 + 4 * 500);
    }
    std::printf("on: polls and excluded waits count nothing, a nested wait once, the kinds apart, two readers the whole each, 2,000 waits of 4 threads\n");
    return fails != 0;
}
