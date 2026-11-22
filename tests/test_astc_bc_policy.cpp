// astc_bc_policy::all_by_vram and all (gpu/vk/astc_bc_policy.h): the cards that keep every large ASTC texture as BC3.
// tests/test_astc_bc_policy.py
#include "../gpu/vk/astc_bc_policy.h"

#include <cstdio>
#include <cstdlib>

static int failures = 0;
static void expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        failures++;
    }
}

int main() {
    const uint64_t MB = 1ull << 20;
    using astc_bc_policy::all_by_vram;
    expect(!all_by_vram(0), "unknown: as before (the finer ones as RGBA8)");
    expect(all_by_vram(3379 * MB), "a 4 GB laptop card (3.3 GB allowed, issue 519)");
    expect(all_by_vram(5900 * MB), "a 6 GB card");
    expect(all_by_vram(7133 * MB), "an 8 GB RX 7700S (7.1 GB allowed)");
    expect(all_by_vram(7700 * MB), "an 8 GB card allowed more");
    expect(!all_by_vram(9400 * MB), "a 10 GB card");
    expect(!all_by_vram(11200 * MB), "a 12 GB card");
    expect(!all_by_vram(15000 * MB), "a 16 GB card");
    // (Triforce, 11-22, the performance audit's TEX-12, after Source A's) every integrated GPU, whatever it is allowed
    using astc_bc_policy::all;
    expect(all(10232 * MB, true), "an integrated GPU allowed 10.2 GB (a 16 GB handheld)");
    expect(all(0, true), "an integrated GPU whose allowance is not known");
    expect(all(7402 * MB, true), "an integrated GPU allowed 7.4 GB");
    expect(all(21000 * MB, true), "an integrated GPU allowed 21 GB (a PC with 32 GB)");
    expect(!all(15000 * MB, false), "a discrete 16 GB card: as before");
    expect(!all(0, false), "a discrete card whose allowance is not known: as before");
    expect(!all(9400 * MB, false) && !all(11200 * MB, false) && !all(31000 * MB, false), "discrete 10, 12 and 32 GB cards: as before");
    expect(all(3379 * MB, false) && all(7133 * MB, false) && all(8703 * MB, false) && !all(8704 * MB, false),
           "discrete cards under 8.5 GB: as before, and the line itself");
    for (uint64_t mb = 0; mb <= 49152; mb += 37)   // (a discrete card is the old rule at every size)
        expect(all(mb * MB, false) == all_by_vram(mb * MB), "a discrete card differs from the rule by the allowance alone");
    if (failures) return EXIT_FAILURE;
    std::printf("astc bc policy: all checks passed\n");
    return EXIT_SUCCESS;
}
