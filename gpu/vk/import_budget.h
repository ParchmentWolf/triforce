// What the idle imports' valve measures the system heap against (no game, no GPU: a rule).
//
// (Triforce, 11-22, the performance audit's MEM-22, after Source A's.) An import is a pool of the game's memory the driver
// pins and counts in the system heap. vk_memory.cpp imports_give_back gives idle ones back past RX_VK_IMPORT_HIGH percent
// (85) of that heap's budget, down to RX_VK_IMPORT_LOW percent (75), but by default only where the budget is under 12 GB:
// on a PC with more, live imports pile up for the whole session (2.0 GB at a fresh Market, 6.5 GB after ten areas), and
// on Linux's amdgpu every submission pays for each one. Source A's numbers (Arch, RX 9070 XT, RADV, 32 GB, a 15,434 MB
// budget): uncapped after about two hours 221 live imports (7,392 MB), queue submit 1.11-1.14 ms, read-back waits
// 6.29-7.03 ms, 1,511 MB of swap, 44-48 fps; capped, 50-64 live (2,256-2,720 MB), 0.32-0.73 ms, 0.64-1.14 ms, no swap,
// 63-68 fps (with other settings changed in the same runs: the cap's own share is not known).
//
// So with Mesa's RADV and a budget of 12 GB or more the valve is on and measures the heap against 4,500 MB, not the whole
// budget, and a pass of it gives back 1 GB at most. Everything else is as it was:
//   - a budget under 12 GB: the whole budget, on (any driver);
//   - 12 GB or more on any other driver: off unless RX_VK_IMPORT_HIGH is set, then the whole budget;
//   - RX_VK_IMPORT_HIGH or RX_VK_IMPORT_LOW set by the player: the whole budget, as before, RADV too.
// RX_VK_IMPORT_CAP_MB=<n>: the cap on any driver and any budget (it turns the valve on); =0: no cap, which is RADV's
// behaviour before. A given-back import costs 5-45 ms when its pool is bound again, which is why only pools idle for 600
// submissions go.
#pragma once
#include <cstdint>

namespace import_budget {
constexpr uint64_t kMB = 1ull << 20;
constexpr uint64_t kBigBudget = 12ull << 30;   // from here the valve was off by default
constexpr uint64_t kCapMb = 4500;              // RADV's cap at a big budget
constexpr uint64_t kPassMost = 1ull << 30;     // a capped pass gives back this much at most

struct Rule {
    bool on = false;     // the heap's trigger runs
    uint64_t cap = 0;    // bytes the heap is measured against at most (0: the whole budget)
};

/// budget: the system heap's budget when the rule is first asked. high_set, low_set: the player set RX_VK_IMPORT_HIGH,
/// RX_VK_IMPORT_LOW. cap_mb: RX_VK_IMPORT_CAP_MB (-1: unset). radv: the driver is Mesa's RADV
constexpr Rule rule(uint64_t budget, bool high_set, bool low_set, int64_t cap_mb, bool radv) {
    const bool before = high_set || budget < kBigBudget;   // (as it was: on where the budget is small, or asked for)
    if (cap_mb > 0) return Rule{true, (uint64_t)cap_mb * kMB};
    if (cap_mb == 0 || high_set || low_set || !radv || budget < kBigBudget) return Rule{before, 0};
    return Rule{true, kCapMb * kMB};
}

/// What the heap's use is measured against now (the budget moves; the cap does not)
constexpr uint64_t measured(const Rule& r, uint64_t budget) {
    return r.cap && r.cap < budget ? r.cap : budget;
}

/// How much a pass by the heap's trigger wants back: down to the target, and 1 GB at most where the cap is what measures
constexpr uint64_t pass_want(const Rule& r, uint64_t budget, uint64_t used, uint64_t target) {
    const uint64_t want = used > target ? used - target : 0;
    return r.cap && r.cap < budget && want > kPassMost ? kPassMost : want;
}
} // namespace import_budget
