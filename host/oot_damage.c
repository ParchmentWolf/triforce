/* (Triforce) The System tab's Damage taken row: Half, Normal, Double or Quadruple of each hit on Link.

   nx2/oot_patches.py (patch_damage) asks hos_oot_damage_scaled before the write of f_804bd8c0 that takes a hit off an
   actor's life, and only while that says 1 and the actor is Link does it call hos_oot_damage, with his life, the life
   the game was about to write and the whole hit. At Normal, the default, hos_oot_damage_scaled is 0: nothing else is
   called and the game writes its own value. Healing is another write and is never scaled. The Debug tab's heart
   protection comes first (its own guard keeps the life as it was, so no hit is left to scale; asked here again all the
   same). oot_play.h oot_damage_life has the rule. */
#include "oot_play.h"
#include "../gpu/vk/vk_api.h"

int rx_option(int id, int otherwise);
int hos_oot_hearts_enabled(void);   /* hos_main.c */

int hos_oot_damage_scaled(void) { return rx_option(HOS_OPT_DAMAGE_TAKEN, OOT_DAMAGE_NORMAL) != OOT_DAMAGE_NORMAL; }

uint32_t hos_oot_damage(uint32_t old, uint32_t next, uint32_t hit) {
    if (next >= old) return next;
    if (hos_oot_hearts_enabled()) return old;
    return oot_damage_life(old, next, hit, rx_option(HOS_OPT_DAMAGE_TAKEN, OOT_DAMAGE_NORMAL));
}
