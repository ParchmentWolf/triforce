// (Triforce, 11-22, the performance audit's MEM-141, after Source A's) A memory pressure hold for Linux and the Steam Deck that
// counts the swap too (vk_memory.cpp steps it from memory_ram_watch, off Windows; this is the rule, plain code:
// tests/test_linux_pressure.py runs it anywhere).
//
// The RAM rules looked at MemAvailable alone. A Linux PC with swap keeps MemAvailable up by pushing the game's pages out:
// on a 16 GB Steam Deck Source A saw the swap fill (4,036 MB at the peak, 0 MB free at the lowest) while MemAvailable said
// little, and the stalls were the pages coming back. So the swap left counts: the PC is short when MemAvailable is under
// 1536 MB (the imports' own line), or when MemAvailable and SwapFree together are under the reserve (RX_VK_SWAP_RESERVE_MB).
// While it is short a hold is on and the renderer gives memory back sooner:
//   - a capture buffer is kept as a spare only up to 32 MB of spares (not 768);
//   - the staging arenas the GPU is done with are freed when the hold begins, then after 5 s unused (not 30);
//   - malloc_trim is asked every 600 presents from 64 MB free (not every 1800 from 192);
//   - idle imports are given back, in all of one episode at most as many bytes as the PC was short at its worst (not up to
//     1 GB a pass: the thrash of imports given back and made again was seen here before), and still only after 3,600 idle
//     submissions;
//   - on an integrated GPU, whose "VRAM" is the same RAM, the texture budget is less by what the PC is short (never under
//     512 MB), and comes back 256 MB a sample.
// The hold ends once MemAvailable and the sum are both 256 MB clear of their lines. A PC without swap, or one whose swap
// cannot be read, is never short by the sum: not known is not short. The program modules are let go by the program pack
// already (vk_shader.cpp), so the hold has no valve for them.
//
// RX_VK_SWAP_RESERVE_MB=<MB>: the reserve; 0 or not set: no hold at all, as before. Source A's is 2560; it is off here until
// a Steam Deck run has shown it. RX_VK_TEST_SWAP_MB=<n> plays that much swap free, as RX_VK_TEST_AVAIL_MB plays MemAvailable.
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace linux_pressure {

constexpr uint64_t kMB = 1ull << 20;
constexpr uint64_t kAvailLine = 1536 * kMB;        // (short under this much MemAvailable, whatever the swap)
constexpr uint64_t kClear = 256 * kMB;             // (the hold ends once both are this far clear of their lines)
constexpr uint64_t kSourceReserve = 2560 * kMB;    // (Source A's reserve: MemAvailable + SwapFree)
constexpr uint64_t kSampleEvery = 30;              // (presents between two looks)
constexpr uint64_t kSpareCap = 32 * kMB;           // (capture spares while held)
constexpr int64_t kArenaIdleS = 5;                 // (a staging arena unused this long goes, while held)
constexpr uint64_t kTrimEvery = 600;               // (presents between two malloc_trim looks, while held)
constexpr uint64_t kTrimMB = 64;                   // (free MB in the arenas from which malloc_trim is asked, while held)
constexpr uint64_t kBudgetFloor = 512 * kMB;       // (an integrated GPU's textures are never cut under this)
constexpr uint64_t kBudgetBack = 256 * kMB;        // (the cut comes back this much a sample)

/// RX_VK_SWAP_RESERVE_MB's text as bytes; 0 (not set, empty, 0, not a number): no hold
inline uint64_t reserve_of(const char* e) {
    const long long mb = e && *e ? atoll(e) : 0;
    return mb > 0 ? (uint64_t)mb * kMB : 0;
}

/// What /proc/meminfo said. A field that is not there is not known (has_*), never 0
struct Meminfo {
    uint64_t total = 0, avail = 0, swap_total = 0, swap_free = 0;
    bool has_total = false, has_avail = false, has_swap_total = false, has_swap_free = false;
};

/// /proc/meminfo's text ("Name:   <n> kB" a line)
inline Meminfo parse(const char* text) {
    Meminfo m;
    auto field = [text](const char* name, uint64_t* out) {
        const size_t len = strlen(name);
        for (const char* p = text; p && *p; p = strchr(p, '\n'), p = p ? p + 1 : p) {
            if (strncmp(p, name, len) || p[len] != ':') continue;
            const char* v = p + len + 1;
            while (*v == ' ' || *v == '\t') v++;
            if (*v < '0' || *v > '9') return false;
            *out = strtoull(v, nullptr, 10) << 10;   // (kB)
            return true;
        }
        return false;
    };
    m.has_total = field("MemTotal", &m.total);
    m.has_avail = field("MemAvailable", &m.avail);
    m.has_swap_total = field("SwapTotal", &m.swap_total);
    m.has_swap_free = field("SwapFree", &m.swap_free);
    return m;
}

/// One look at the PC's memory. swap_known: there is swap and what is free of it was read
struct Sample {
    bool avail_known = false, swap_known = false;
    uint64_t avail = 0, swap_free = 0;
};

/// The sample of a meminfo, with the lab's played values over it (negative: not played). Swapless (SwapTotal 0), or SwapFree
/// or SwapTotal unreadable: the swap is not known. A played swap counts as known
inline Sample sample_of(const Meminfo& m, long long test_avail_mb = -1, long long test_swap_mb = -1) {
    Sample s;
    s.avail_known = m.has_avail, s.avail = m.avail;
    s.swap_known = m.has_swap_total && m.has_swap_free && m.swap_total > 0, s.swap_free = s.swap_known ? m.swap_free : 0;
    if (test_avail_mb >= 0) s.avail_known = true, s.avail = (uint64_t)test_avail_mb * kMB;
    if (test_swap_mb >= 0) s.swap_known = true, s.swap_free = (uint64_t)test_swap_mb * kMB;
    return s;
}

/// How many bytes the PC is short: the larger of what MemAvailable lacks to its line and what the sum lacks to the reserve.
/// 0: not short, or not known
inline uint64_t shortfall(const Sample& s, uint64_t reserve) {
    if (!reserve || !s.avail_known) return 0;
    const uint64_t by_avail = s.avail < kAvailLine ? kAvailLine - s.avail : 0;
    const uint64_t sum = s.avail + s.swap_free;
    const uint64_t by_sum = s.swap_known && sum < reserve ? reserve - sum : 0;
    return std::max(by_avail, by_sum);
}

/// Both lines cleared by kClear (the hold may end). Not known: clear
inline bool clear(const Sample& s, uint64_t reserve) {
    if (!reserve || !s.avail_known) return true;
    if (s.avail < kAvailLine + kClear) return false;
    return !s.swap_known || s.avail + s.swap_free >= reserve + kClear;
}

/// The hold: on from a short sample until a clear one. One episode is one stretch of it
struct Hold {
    bool held = false;
    uint64_t deepest = 0;    // (the episode's largest shortfall)
    uint64_t given = 0;      // (the bytes of imports given back in this episode)
    uint64_t now = 0;        // (the last sample's shortfall)
    uint64_t cut = 0;        // (an integrated GPU's texture budget is less by this)
    uint64_t episodes = 0;

    enum Step { Same, Entered, Left };
    /// One sample. reserve 0: never held
    Step step(const Sample& s, uint64_t reserve) {
        const uint64_t lacking = shortfall(s, reserve);
        Step r = Same;
        if (!held && lacking) held = true, deepest = 0, given = 0, episodes++, r = Entered;
        else if (held && clear(s, reserve)) held = false, r = Left;
        now = held ? lacking : 0;
        if (held) deepest = std::max(deepest, lacking);
        // (the budget's cut: down at once to what is lacking, back up kBudgetBack a sample)
        cut = now > cut ? now : std::max(now, cut > kBudgetBack ? cut - kBudgetBack : 0);
        return r;
    }
    /// The bytes of idle imports this episode may still give back: its largest shortfall, less what it gave
    uint64_t episode_want() const { return held && deepest > given ? deepest - given : 0; }
    void gave(uint64_t bytes) { given += bytes; }
};

/// The valves' sizes, held or not
inline uint64_t spare_cap(bool held, uint64_t usual) { return held ? std::min(usual, kSpareCap) : usual; }
/// (idle_s 0: the player keeps the arenas: kept while held too)
inline int64_t arena_idle_s(bool held, int64_t usual) { return held && usual > kArenaIdleS ? kArenaIdleS : usual; }
inline uint64_t trim_every(bool held, uint64_t usual) { return held ? std::min(usual, kTrimEvery) : usual; }
/// (trim_mb 0: never, held or not)
inline uint64_t trim_mb(bool held, uint64_t usual) { return held && usual ? std::min(usual, kTrimMB) : usual; }
/// An integrated GPU's texture budget less the cut: never under the floor, never more than it was
inline uint64_t cut_budget(uint64_t budget, uint64_t cut) {
    if (!cut || budget <= kBudgetFloor) return budget;
    return std::max(kBudgetFloor, budget > cut ? budget - cut : 0);
}

}   // namespace linux_pressure
