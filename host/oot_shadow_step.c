/* (Triforce, 11-21, the performance audit's GAME-05, after Source B's) The side of a character's or an object's shadow
   map rounded up to a step: the lifted code's read of the side goes through hos_oot_shadow_side (nx2/oot_patches.py
   patch_shadow_step). host/oot_shadow_step.h has why and the rule.
   HOS_OOT_SHADOW_STEP=<n>: the step (64 when not set); 0 or 1: the game's own side, as before. */
#include "hos.h"
#include "oot_shadow_step.h"
#include <stdlib.h>

uint32_t hos_oot_shadow_side(uint32_t side) {
    static int step = -1;           /* (read once: the same value whichever thread is first) */
    static volatile long rounded;   /* (the log's count) */
    int s = __atomic_load_n(&step, __ATOMIC_RELAXED);
    if (s < 0) {
        s = (int)oot_shadow_step(getenv("HOS_OOT_SHADOW_STEP"));
        int unset = -1;
        if (__atomic_compare_exchange_n(&step, &unset, s, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED))
            hos_log("oot: shadow maps' sides rounded up to a multiple of %d (HOS_OOT_SHADOW_STEP; 0: the game's own, as before)", s <= 1 ? 0 : s);
    }
    const uint32_t out = oot_shadow_side(side, (uint32_t)s);
    if (out != side) {
        const long n = __atomic_add_fetch(&rounded, 1, __ATOMIC_RELAXED);
        if (n >= 4096 && !(n & (n - 1))) hos_log("oot: shadow maps' sides rounded: %ld so far (the last %u as %u)", n, side, out);
    }
    return out;
}
