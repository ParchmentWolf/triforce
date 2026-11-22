// (Triforce, 11-22, the performance audit's MEM-141, after Source A's) gpu/vk/linux_pressure.h: the swap-aware memory
// pressure hold's rule. No game, no GPU, no Linux: tests/test_linux_pressure.py compiles and runs this.
#include "linux_pressure.h"

#include <cstdio>

static int checks, fails;
#define CHECK(x) do { checks++; if (!(x)) { fails++; printf("FAIL line %d: %s\n", __LINE__, #x); } } while (0)

using namespace linux_pressure;

static Sample at(long long avail_mb, long long swap_mb) {   // (swap_mb < 0: the swap not known)
    Sample s;
    s.avail_known = avail_mb >= 0, s.avail = avail_mb >= 0 ? (uint64_t)avail_mb * kMB : 0;
    s.swap_known = swap_mb >= 0, s.swap_free = swap_mb >= 0 ? (uint64_t)swap_mb * kMB : 0;
    return s;
}

int main() {
    const uint64_t R = kSourceReserve;   // (2560 MB)
    CHECK(R == 2560 * kMB && kAvailLine == 1536 * kMB && kClear == 256 * kMB && kSampleEvery == 30);

    // --- the switch ---
    CHECK(reserve_of(nullptr) == 0 && reserve_of("") == 0 && reserve_of("0") == 0 && reserve_of("x") == 0 && reserve_of("-5") == 0);
    CHECK(reserve_of("2560") == 2560 * kMB && reserve_of("1024") == 1024 * kMB);

    // --- /proc/meminfo ---
    const char* usual =
        "MemTotal:       16252084 kB\nMemFree:          412300 kB\nMemAvailable:    8388608 kB\nBuffers:           10000 kB\n"
        "Cached:          3000000 kB\nSwapCached:       123456 kB\nActive:          5000000 kB\nSwapTotal:       8388604 kB\n"
        "SwapFree:        6291456 kB\nZswap:            200000 kB\n";
    Meminfo m = parse(usual);
    CHECK(m.has_total && m.has_avail && m.has_swap_total && m.has_swap_free);
    CHECK(m.total == 16252084ull << 10 && m.avail == 8388608ull << 10 && m.swap_total == 8388604ull << 10 && m.swap_free == 6291456ull << 10);
    Sample s = sample_of(m);
    CHECK(s.avail_known && s.swap_known && s.avail == 8192 * kMB && s.swap_free == 6144 * kMB);
    CHECK(shortfall(s, R) == 0 && clear(s, R));

    // no swap at all: SwapTotal 0. Not known, never short by the sum
    m = parse("MemTotal: 16252084 kB\nMemAvailable: 2048000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n");
    s = sample_of(m);
    CHECK(m.has_swap_total && m.has_swap_free && s.avail_known && !s.swap_known);
    CHECK(shortfall(s, R) == 0 && clear(s, R));   // (2000 MB available: over the 1536 line and its 256)
    // ... but MemAvailable's own line still counts there
    s = sample_of(parse("MemTotal: 16252084 kB\nMemAvailable: 1048576 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"));
    CHECK(!s.swap_known && shortfall(s, R) == 512 * kMB && !clear(s, R));
    // the swap lines missing, or SwapFree alone missing: not known
    s = sample_of(parse("MemTotal: 16252084 kB\nMemAvailable: 2048000 kB\n"));
    CHECK(s.avail_known && !s.swap_known && shortfall(s, R) == 0);
    s = sample_of(parse("MemAvailable: 2048000 kB\nSwapTotal: 8388604 kB\n"));
    CHECK(!s.swap_known && shortfall(s, R) == 0);
    // SwapCached is not SwapFree; MemFree is not MemAvailable
    m = parse("MemTotal: 16252084 kB\nMemFree: 100 kB\nSwapCached: 5 kB\n");
    CHECK(m.has_total && !m.has_avail && !m.has_swap_total && !m.has_swap_free);
    // no MemAvailable (an old kernel): not known, never short, whatever the swap says
    s = sample_of(parse("MemTotal: 16252084 kB\nMemFree: 100 kB\nSwapTotal: 8388604 kB\nSwapFree: 0 kB\n"));
    CHECK(!s.avail_known && s.swap_known && shortfall(s, R) == 0 && clear(s, R));
    // nothing read at all, or not numbers
    s = sample_of(parse(""));
    CHECK(!s.avail_known && !s.swap_known && shortfall(s, R) == 0);
    m = parse("MemAvailable: lots\nSwapFree:\n");
    CHECK(!m.has_avail && !m.has_swap_free);
    // swap nearly full: MemAvailable looks fine, the sum does not
    s = sample_of(parse("MemTotal: 16252084 kB\nMemAvailable: 2048000 kB\nSwapTotal: 8388604 kB\nSwapFree: 102400 kB\n"));
    CHECK(s.avail == 2000 * kMB && s.swap_free == 100 * kMB && shortfall(s, R) == 460 * kMB && !clear(s, R));
    // the lab's played values, over what the file says
    s = sample_of(parse(usual), 900, -1);
    CHECK(s.avail == 900 * kMB && s.swap_free == 6144 * kMB && shortfall(s, R) == 636 * kMB);
    s = sample_of(parse(usual), 2000, 100);
    CHECK(shortfall(s, R) == 460 * kMB);
    s = sample_of(parse("MemTotal: 1 kB\nMemAvailable: 2048000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"), -1, 50);
    CHECK(s.swap_known && shortfall(s, R) == 510 * kMB);   // (a played swap counts as known)

    // --- how short ---
    CHECK(shortfall(at(1535, -1), R) == 1 * kMB && shortfall(at(1536, -1), R) == 0);
    CHECK(shortfall(at(1000, 100), R) == 1460 * kMB);   // (the larger: 536 by MemAvailable, 1460 by the sum)
    CHECK(shortfall(at(1000, 4000), R) == 536 * kMB);
    CHECK(shortfall(at(2000, 560), R) == 0 && shortfall(at(2000, 559), R) == 1 * kMB);
    CHECK(shortfall(at(500, 0), 0) == 0 && clear(at(500, 0), 0));   // (no reserve: no hold at all)
    CHECK(!clear(at(1791, 9000), R) && clear(at(1792, 9000), R));
    CHECK(!clear(at(2000, 815), R) && clear(at(2000, 816), R) && clear(at(1792, -1), R));

    // --- the hold ---
    {
        Hold h;
        CHECK(h.step(at(8000, 6000), R) == Hold::Same && !h.held && h.episode_want() == 0 && h.cut == 0);
        CHECK(h.step(at(2000, 100), R) == Hold::Entered && h.held && h.episodes == 1);
        CHECK(h.now == 460 * kMB && h.deepest == 460 * kMB && h.episode_want() == 460 * kMB && h.cut == 460 * kMB);
        CHECK(h.step(at(1800, 0), R) == Hold::Same && h.deepest == 760 * kMB && h.cut == 760 * kMB);
        h.gave(300 * kMB);
        CHECK(h.episode_want() == 460 * kMB);
        // better, not clear yet (within 256 MB of the lines): still held, nothing lacking now
        CHECK(h.step(at(2000, 700), R) == Hold::Same && h.held && h.now == 0 && h.deepest == 760 * kMB);
        CHECK(h.cut == 504 * kMB);   // (back up 256 MB a sample)
        h.gave(500 * kMB);
        CHECK(h.episode_want() == 0);   // (the episode has given back what it may: 800 of 760)
        // short again within the episode: the limit is the worst so far, less what went
        CHECK(h.step(at(1700, 0), R) == Hold::Same && h.deepest == 860 * kMB && h.episode_want() == 60 * kMB && h.cut == 860 * kMB);
        // clear of both lines by 256 MB: the hold ends; the cut keeps coming back
        CHECK(h.step(at(2100, 716), R) == Hold::Left && !h.held && h.episode_want() == 0 && h.now == 0);
        CHECK(h.cut == 604 * kMB);
        CHECK(h.step(at(4000, 4000), R) == Hold::Same && h.cut == 348 * kMB);
        CHECK(h.step(at(4000, 4000), R) == Hold::Same && h.cut == 92 * kMB);
        CHECK(h.step(at(4000, 4000), R) == Hold::Same && h.cut == 0);
        // a new episode starts from nothing
        CHECK(h.step(at(1400, -1), R) == Hold::Entered && h.episodes == 2 && h.deepest == 136 * kMB && h.given == 0);
        CHECK(h.episode_want() == 136 * kMB);
        // MemAvailable no longer readable: not known is not short, the hold ends
        CHECK(h.step(at(-1, 0), R) == Hold::Left && !h.held);
    }
    {   // no reserve: never held, whatever the PC says
        Hold h;
        for (int i = 0; i < 5; i++) CHECK(h.step(at(100, 0), 0) == Hold::Same && !h.held && h.cut == 0 && h.episode_want() == 0);
        CHECK(h.episodes == 0);
    }
    {   // swapless PC: only MemAvailable's line, with its own 256 MB to clear
        Hold h;
        CHECK(h.step(at(1600, -1), R) == Hold::Same && !h.held);
        CHECK(h.step(at(1500, -1), R) == Hold::Entered && h.now == 36 * kMB);
        CHECK(h.step(at(1700, -1), R) == Hold::Same && h.held);
        CHECK(h.step(at(1792, -1), R) == Hold::Left);
    }

    // --- the valves ---
    CHECK(spare_cap(false, 768 * kMB) == 768 * kMB && spare_cap(true, 768 * kMB) == 32 * kMB && spare_cap(true, 16 * kMB) == 16 * kMB);
    CHECK(arena_idle_s(false, 30) == 30 && arena_idle_s(true, 30) == 5 && arena_idle_s(true, 2) == 2 && arena_idle_s(true, 0) == 0);
    CHECK(trim_every(false, 1800) == 1800 && trim_every(true, 1800) == 600 && trim_every(true, 300) == 300);
    CHECK(trim_mb(false, 192) == 192 && trim_mb(true, 192) == 64 && trim_mb(true, 32) == 32 && trim_mb(true, 0) == 0);
    CHECK(cut_budget(2560 * kMB, 0) == 2560 * kMB && cut_budget(2560 * kMB, 460 * kMB) == 2100 * kMB);
    CHECK(cut_budget(2560 * kMB, 2500 * kMB) == 512 * kMB && cut_budget(2560 * kMB, 9000 * kMB) == 512 * kMB);
    CHECK(cut_budget(400 * kMB, 300 * kMB) == 400 * kMB && cut_budget(512 * kMB, 100 * kMB) == 512 * kMB);   // (never raised, never under the floor)
    for (uint64_t cut = 0; cut <= 4096 * kMB; cut += 64 * kMB) {
        const uint64_t b = cut_budget(2560 * kMB, cut);
        CHECK(b <= 2560 * kMB && b >= 512 * kMB);
    }

    if (fails) printf("linux pressure: FAILED (%d of %d checks)\n", fails, checks);
    else printf("linux pressure: all %d checks passed\n", checks);
    return fails != 0;
}
