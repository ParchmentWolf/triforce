// (Triforce, 11-22, the performance audit's OS-49, after Source B's) A lab switch: a slower GPU, so that a lab PC's renderer
// meets the GPU-bound frames a weaker card's player has (the write-back waits, the capture's late pages, the recording slots,
// the pacing), on the same 5090. RX_VK_SIM_GPU_SLOW=<factor> (over 1, at most 10; 2.5 is read): for each ms of work the
// recordings measure, (factor - 1) ms more, a one-invocation compute loop (shaders/sim_gpu_burn.comp) at the end of the
// replay's own recordings, between full barriers, inside the span the GPU time is measured over, so that the frame's GPU time
// and Resolution Auto see the slower card (vk_replay.cpp sim_burn). What a burn took is measured by a third timestamp between
// the recording's work and the burn, and the difference is carried: the debt below. It repeats the fast card's relative
// answer only: no bandwidth, no other driver, no upscaler's cost. Unset: nothing of it runs, two timestamps a recording.
//
// The rules alone, no Vulkan: tests/test_sim_cores.py compiles them.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdlib>

namespace sim_gpu {

inline constexpr int64_t kLeastNs = 1'000'000;       // (a burn is planned for 1 ms at least: less owed waits)
inline constexpr int64_t kMostNs = 16'000'000;       // (and 16 ms at most: the rest goes to the next recordings)
inline constexpr int64_t kDebtLeast = -50'000'000;   // (the time owed is held between these: a burn that ran long is not
inline constexpr int64_t kDebtMost = 100'000'000;    // carried for seconds, nor a backlog after a hitch)
inline constexpr double kFirstNsPerLoop = 4.0;       // (a loop's time before the first measure)

/// RX_VK_SIM_GPU_SLOW: the factor, over 1 and at most 10; 0 (off) for anything else
inline double factor_of(const char* e) {
    if (!e || !*e) return 0;
    char* end = nullptr;
    const double f = std::strtod(e, &end);
    if (end == e || *end || !(f > 1.0) || f > 10.0) return 0;
    return f;
}
/// The time owed after a recording measured `work_ns` of work and `added_ns` of burn, before the bounds
inline double owed(int64_t debt, int64_t work_ns, int64_t added_ns, double factor) {
    return (double)debt + (double)work_ns * (factor - 1.0) - (double)added_ns;
}
/// And within them
inline int64_t held(double owed_ns) { return (int64_t)std::clamp(owed_ns, (double)kDebtLeast, (double)kDebtMost); }
/// The time the next burn is planned for: what is owed, less the burns planned and not measured yet; 0 under kLeastNs
inline int64_t plan_ns(int64_t debt, int64_t in_flight) {
    const int64_t o = debt - in_flight;
    return o < kLeastNs ? 0 : std::min(o, kMostNs);
}
/// The loop count for a planned time, at the measured time a loop takes
inline uint32_t loops_for(int64_t ns, double ns_per_loop) {
    if (ns <= 0) return 0;
    const double l = (double)ns / (ns_per_loop > 0.01 ? ns_per_loop : 0.01);
    return (uint32_t)std::clamp(l, 1.0, (double)(1u << 30));
}
/// The time a loop takes after a burn of `loops` took `added_ns`: 0.8 of what it was, 0.2 of what this one measured
inline double calibrated(double ns_per_loop, int64_t added_ns, uint32_t loops) {
    if (!loops || added_ns <= 0) return ns_per_loop;
    const double m = (double)added_ns / loops;
    return ns_per_loop > 0 ? 0.8 * ns_per_loop + 0.2 * m : m;
}

}  // namespace sim_gpu
