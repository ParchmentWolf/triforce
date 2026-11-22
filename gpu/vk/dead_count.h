// (Triforce, 11-21, the performance audit's THREAD-21, its first step) What destroying the dead images costs a present.
//
// A texture let go waits in a list until the GPU is done with it, and texture_frame then destroys every one that is, in
// the middle of the present being recorded: a render target's image goes to the pool (cheap), every other image is
// destroyed with its views. The audit's port bounds that to a share a present, after the present's submit, as Source B
// does on its GPU thread's idle moments. Its own proof asks for the cost first: "if no present spends 3 ms in the loop,
// stop". This is that count, and nothing else changes: a line for a present whose loop took kSayMs or more, and every
// 600 presents the totals and the worst present.
//
// No Vulkan here: tests/test_dead_count.py compiles it.
#pragma once
#include <cstdint>

namespace dead_count {

inline constexpr double kSayMs = 2.0;       // (a present's loop that gets a line of its own)
inline constexpr double kWorthMs = 3.0;     // (the audit's line: under it in every present, the bounded step is not built)
inline constexpr uint64_t kReport = 600;    // (presents between the totals' lines)

struct Counts {
    uint64_t presents = 0, destroyed = 0, pooled = 0, over_say = 0, over_worth = 0;
    double ms = 0, worst_ms = 0;
    uint64_t worst_destroyed = 0, worst_left = 0;
    /// A present's loop: n_destroyed images destroyed and n_pooled put in the pool in loop_ms, left still waiting. True
    /// when the present gets a line of its own
    bool note(uint64_t n_destroyed, uint64_t n_pooled, double loop_ms, uint64_t left) {
        presents++, destroyed += n_destroyed, pooled += n_pooled, ms += loop_ms;
        if (loop_ms > worst_ms) worst_ms = loop_ms, worst_destroyed = n_destroyed, worst_left = left;
        if (loop_ms >= kWorthMs) over_worth++;
        if (loop_ms < kSayMs) return false;
        over_say++;
        return true;
    }
    /// Whether the totals' line is due, at present `present`
    bool due(uint64_t present) const { return presents != 0 && present % kReport == 0; }
    void reset() { *this = Counts{}; }
};

}   // namespace dead_count
