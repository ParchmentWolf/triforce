// How much of the idle staging arenas a present may keep (no game, no GPU: rules). tests/test_staging_burst.py
//
// (Triforce, 11-22, the performance audit's TEX-28, after Source A's.) The uploads stage their bytes in host-visible
// arenas of 64 MB (vk_texture.cpp staging()). An arena is taken again once the GPU is done with the submission that read
// it, which texture_frame learns a present later: frames that stage one after another need two arenas in turn. Each
// present gives the idle ones back beyond what is kept, 256 MB, and 64 MB on a card of 6.5 GB or less, where an arena may
// be VRAM behind a resizable BAR. With 64 MB kept, the arena that had its turn was idle at every second present of a load,
// was freed, and was made again the present after: Source A counted 16 arenas made, 225 ms of them on the thread that
// replays, in one arrival on a handheld (15.5 ms each), and 4 with this rule.
//
// The rule: an idle arena that something staged into less than RX_VK_STAGING_BURST_S seconds ago (2) is one of a burst's,
// and while such an arena is looked at the idle ones may add up to 256 MB instead of what is kept. Not while VRAM is over
// 90% of the allowance (the render targets' pool's own flag, pool_pressed): a full card keeps what it kept. Where 256 MB
// are kept anyway, every card over 6.5 GB, nothing changes. The arenas over 64 MB still go at once, and the 30 s rule
// (RX_VK_STAGING_IDLE_S) stays. RX_VK_STAGING_BURST_S=0: as before.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdlib>

namespace staging_keep {

inline constexpr uint64_t kBurstKeep = 256ull << 20;   // (what the idle arenas of a burst may add up to)
inline constexpr int64_t kBurstS = 2;                  // (how long after its last staging an arena is one of a burst's)

/// RX_VK_STAGING_BURST_S: unset or empty kBurstS; a number of seconds, at most an hour; 0, less or not a number: no rule
inline int64_t burst_s(const char* env) {
    if (!env || !*env) return kBurstS;
    const long long v = std::atoll(env);
    return v > 0 ? (int64_t)std::min<long long>(v, 3600) : 0;
}

/// Whether an arena last staged into `since_used_ms` ago is one of a burst's: `pressed` is VRAM over 90% of the allowance
constexpr bool recent(int64_t burst_s, bool pressed, int64_t since_used_ms) {
    return burst_s > 0 && !pressed && since_used_ms >= 0 && since_used_ms < burst_s * 1000;
}

/// What the arenas looked at so far and this one may add up to for this one to stay: `keep` is what a present keeps anyway
constexpr uint64_t allowance(uint64_t keep, bool recent) { return recent ? std::max(keep, kBurstKeep) : keep; }

} // namespace staging_keep
