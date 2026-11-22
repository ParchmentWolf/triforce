/* (Triforce, 11-21, the performance audit's GAME-05, after Source B's) The side of a character's or an object's shadow
   map, in steps. nx2/oot_patches.py patch_shadow_step hooks the place; host/oot_shadow_step.c reads the switch.

   The game gives each nearby character or object a square depth shadow map of its own, sized by its size on screen
   (384 to 1,920 a side), so while anything moves the side changes every frame, and each frame asks for depth textures
   of sizes not seen before: an image, its memory and its views made, and the old ones destroyed. The render targets'
   pool gives an image back only to a target of exactly its shape. Rounded up to a multiple of 64 the sides are 25
   sizes, which come round again, and the pool serves them. Source B measured, strafing along a wall in Castle Town's
   pot room, 4,000 to 10,000 new depth images in 600 frames against 30 to 90.

   The one read of the side, before the texture is asked for, is rounded; the function's later uses read the same
   register, so the viewport and the texture stay in step. The projection is unchanged: a map has at most 63 more
   texels a side. 768 is 12 x 64, so no map crosses the renderer's rule for maps of 768 and less.

   HOS_OOT_SHADOW_STEP=<n>: the step, a power of two from 2 to 256; not set, 64; 0 or 1: the game's own side, as before.

   The rule alone, no game: tests/test_oot_shadow_step.py compiles it. */
#ifndef OOT_SHADOW_STEP_H
#define OOT_SHADOW_STEP_H
#include <stdint.h>

enum { OOT_SHADOW_STEP_DEFAULT = 64, OOT_SHADOW_STEP_MOST = 256 };

/* The switch's value as a step: not set, the default; 0 or 1, off (1); a power of two up to OOT_SHADOW_STEP_MOST, itself;
   anything else (not a number, not a power of two, more), the default */
static inline uint32_t oot_shadow_step(const char *asked) {
    if (!asked || !*asked) return OOT_SHADOW_STEP_DEFAULT;
    uint32_t v = 0;
    int digits = 0;
    const char *p = asked;
    for (; *p >= '0' && *p <= '9' && v < 100000; p++) v = v * 10 + (uint32_t)(*p - '0'), digits++;
    if (!digits || *p) return OOT_SHADOW_STEP_DEFAULT;
    if (v <= 1) return 1;
    return v <= OOT_SHADOW_STEP_MOST && !(v & (v - 1)) ? v : OOT_SHADOW_STEP_DEFAULT;
}

/* The side the game asks its shadow map with: the next multiple of step from side (step a power of two; 1: side itself) */
static inline uint32_t oot_shadow_side(uint32_t side, uint32_t step) {
    return step <= 1 ? side : (side + step - 1) & ~(step - 1);
}
#endif
