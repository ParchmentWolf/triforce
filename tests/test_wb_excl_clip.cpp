// gpu/vk/wb_excl_clip.h without the game or a GPU: which parts of a written binding are copied back, and the 0.6.0 heap
// corruption it is for, played on a page of bytes (tests/test_wb_excl_clip.py)
#include "../gpu/vk/wb_excl_clip.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>

using wb_excl_clip::Range;

static int fails = 0;
#define CHECK(c)                                                         \
    do {                                                                 \
        if (!(c)) {                                                      \
            std::fprintf(stderr, "%s:%d: CHECK(%s)\n", __FILE__, __LINE__, #c); \
            fails++;                                                     \
        }                                                                \
    } while (0)

static std::vector<Range> kept(uint64_t lo, uint64_t hi, const std::vector<Range>& ex, uint64_t* dropped = nullptr) {
    std::vector<Range> out;
    const uint64_t d = wb_excl_clip::kept(lo, hi, ex, out);
    if (dropped) *dropped = d;
    return out;
}

// A write-back as the diff does it: the mirror's words that differ from the shadow (guest memory) copied over guest memory
static void write_back(uint8_t* guest, const uint8_t* mirror, uint64_t base, const std::vector<Range>& parts) {
    for (const auto& [a, b] : parts)
        for (uint64_t i = a; i < b; i++)
            if (mirror[i - base] != guest[i - base]) guest[i - base] = mirror[i - base];
}

int main() {
    const std::vector<Range> none;
    const std::vector<Range> ex = {{0x2000, 0x3000}, {0x5000, 0x6000}};
    uint64_t d = 0;

    // nothing left out: the whole binding, as before
    CHECK((kept(0x1000, 0x1040, none, &d) == std::vector<Range>{{0x1000, 0x1040}}) && d == 0);
    // outside every left-out range: whole
    CHECK((kept(0x1000, 0x2000, ex, &d) == std::vector<Range>{{0x1000, 0x2000}}) && d == 0);
    CHECK((kept(0x3000, 0x5000, ex, &d) == std::vector<Range>{{0x3000, 0x5000}}) && d == 0);
    CHECK((kept(0x6000, 0x7000, ex, &d) == std::vector<Range>{{0x6000, 0x7000}}) && d == 0);
    // a bare entry's 64-byte head inside one: nothing copied back
    CHECK(kept(0x2000, 0x2040, ex, &d).empty() && d == 0x40);
    CHECK(kept(0x2fc0, 0x3000, ex, &d).empty() && d == 0x40);
    // across one edge, either way
    CHECK((kept(0x1f00, 0x2100, ex, &d) == std::vector<Range>{{0x1f00, 0x2000}}) && d == 0x100);
    CHECK((kept(0x2f00, 0x3100, ex, &d) == std::vector<Range>{{0x3000, 0x3100}}) && d == 0x100);
    // across both: the parts between and beside them
    CHECK((kept(0x1000, 0x8000, ex, &d) == std::vector<Range>{{0x1000, 0x2000}, {0x3000, 0x5000}, {0x6000, 0x8000}}) &&
          d == 0x2000);
    // over a whole range exactly, and an empty binding
    CHECK(kept(0x5000, 0x6000, ex, &d).empty() && d == 0x1000);
    CHECK(kept(0x5000, 0x5000, ex, &d).empty() && d == 0);
    // what was kept and what was left out always make the binding
    for (uint64_t lo = 0x1800; lo < 0x6800; lo += 0x1c0)
        for (uint64_t n = 0x40; n < 0x3000; n += 0x3c0) {
            uint64_t sum = 0, at = lo;
            bool inside = true;
            for (const auto& [a, b] : kept(lo, lo + n, ex, &d)) {
                inside = inside && a >= at && b > a && b <= lo + n;
                for (const auto& [ea, eb] : ex) inside = inside && (b <= ea || a >= eb);
                sum += b - a, at = b;
            }
            CHECK(inside && sum + d == n);
        }

    // the switch: on unless "0", and only while the capture leaves memory out (RX_VK_CAP_ONLY_GPU=1)
    CHECK(wb_excl_clip::on(nullptr, 1) && wb_excl_clip::on("", 1) && wb_excl_clip::on("1", 1));
    CHECK(!wb_excl_clip::on("0", 1));
    CHECK(!wb_excl_clip::on(nullptr, 0) && !wb_excl_clip::on(nullptr, 2) && !wb_excl_clip::on("1", 0));

    // The crash, on a page: a pool at 0x10000, the heap's 12-byte block at +0x18 (its header at +0x10) written by the CPU
    // after the mirror was made; the page is left out, so the mirror still holds what was there before (the counts the logs
    // show: 0x9ed00000001). A bare entry's head [base, base + 0x40) is the written binding
    const uint64_t base = 0x10000;
    uint8_t guest[0x1000], mirror[0x1000];
    std::memset(guest, 0, sizeof guest);
    std::memset(mirror, 0, sizeof mirror);
    const uint64_t header = 0x0000000014a40005ull, stale = 0x000009ed00000001ull;
    std::memcpy(guest + 0x10, &header, 8);   // (the CPU's block header, guest memory only)
    std::memcpy(mirror + 0x10, &stale, 8);   // (the mirror's stale copy)
    const std::vector<Range> left_out = {{base, base + 0x1000}};
    uint8_t before[0x1000];
    std::memcpy(before, guest, sizeof guest);
    // as 0.6.0 did: the whole head written back, and the header is the stale value (0x803b44e0 then reads 0x9ed00000012)
    write_back(guest, mirror, base, {{base, base + 0x40}});
    uint64_t got = 0;
    std::memcpy(&got, guest + 0x10, 8);
    CHECK(got == stale);
    // clipped: guest memory as the CPU left it
    std::memcpy(guest, before, sizeof guest);
    write_back(guest, mirror, base, kept(base, base + 0x40, left_out));
    std::memcpy(&got, guest + 0x10, 8);
    CHECK(got == header && std::memcmp(guest, before, sizeof guest) == 0);
    // a pool's own page is still written back (the GPU's results the CPU reads)
    const uint64_t result = 0x1234;
    std::memcpy(mirror + 0x20, &result, 8);
    write_back(guest, mirror, base, kept(base, base + 0x40, none));
    std::memcpy(&got, guest + 0x20, 8);
    CHECK(got == result);

    if (fails) {
        std::fprintf(stderr, "%d checks failed\n", fails);
        return 1;
    }
    std::puts("wb_excl_clip: all checks passed");
    return 0;
}
