/* (Triforce, 11-21, the performance audit's TEX-85, after Source A's) The storage a character's shadow map reserves
   (host/nvn_native.c nvnTextureBuilderGetStorageSize and nvnTextureBuilderGetStorageAlignment).

   The game gives each shadow-casting character near the camera a square depth map (NVN format 0x34, one level) whose
   side it works out anew every frame from the camera's distance: 384 from afar, more from near, a few pixels different
   each frame while either moves. It makes a frame's render targets one after another, first fit, in its target heap,
   asking the size and alignment of each here. So a map a few pixels larger pushes every target made after it to another
   address, and each of those is a new texture to the game and, keyed by its address, a new image to the renderer:
   Source A counted 15 to 16 textures made a frame in the Market with the camera turning, and 6 with this.

   Such a map is answered the storage size and alignment of the next multiple of a step up (384: sides 768, 1152, 1536,
   1920), so the targets after it stay where they are until the map crosses a step. Only the bytes the game sets aside
   change, by less than one step's worth a map (1.8 MB at the first step, 5.3 MB at the worst); the texture keeps its own
   size and layout, and nothing is drawn or sampled differently.

   HOS_SHADOW_BUCKET=<step>: the step, 384 when not set; 0: every map its own size, as before. Not set, the step is 0
   where the target heap is pinned (HOS_RT_POOL_MB, or the 5120-wide outputs' 900 MB), where there is no room to give.

   The rule alone, no NVN: tests/test_shadow_slot.py compiles it. */
#ifndef HOS_SHADOW_SLOT_H
#define HOS_SHADOW_SLOT_H

#include <stdint.h>

enum { HOS_SHADOW_SLOT_STEP = 384, HOS_SHADOW_SLOT_FORMAT = 0x34, HOS_SHADOW_SLOT_LEAST = 384, HOS_SHADOW_SLOT_MOST = 1920 };

/* The side whose storage a texture of this description reserves: the next multiple of step from its own, for a square
   two-dimensional one-level depth map wider than 384 and up to 1920, and never more than 1920. 0: its own (not such a
   map, or step 0) */
static inline uint32_t hos_shadow_slot_side(int is_2d, int format, uint32_t levels, uint32_t depth, uint32_t width, uint32_t height,
                                            uint32_t step) {
    if (!step || !is_2d || format != HOS_SHADOW_SLOT_FORMAT || levels != 1 || depth > 1 || width != height ||
        width <= HOS_SHADOW_SLOT_LEAST || width > HOS_SHADOW_SLOT_MOST)
        return 0;
    const uint32_t side = (width + step - 1) / step * step;
    return side > HOS_SHADOW_SLOT_MOST ? HOS_SHADOW_SLOT_MOST : side;
}

/* The step: asked, HOS_SHADOW_BUCKET's value (NULL: not set); pinned: the target heap is held to a size (no room to give).
   Set: its value, 0 for off or a negative number. Not set: 0 on a pinned heap, else HOS_SHADOW_SLOT_STEP */
static inline uint32_t hos_shadow_slot_step(const char *asked, int pinned) {
    if (asked) {
        long v = 0;
        int digits = 0;
        const char *p = asked;
        for (; *p >= '0' && *p <= '9' && v < 100000; p++) v = v * 10 + (*p - '0'), digits++;
        return digits && !*p ? (uint32_t)v : *asked ? 0 : HOS_SHADOW_SLOT_STEP;   /* (not a number: off; empty: as not set) */
    }
    return pinned ? 0 : HOS_SHADOW_SLOT_STEP;
}

#endif
