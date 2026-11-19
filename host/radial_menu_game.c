/* (Triforce) The radial menus' side in the game (radial_menu_game.h), Ocarina of Time 1.1.1, for the renderer's radial menus
   (gpu/vk/radial_menu.cpp, through its table: rx_radial_menu).

   The game's item bar is its sequence's ShortCut.module: L or R held in play pauses the game and opens the bar's screens,
   their release closes them. With the radial menus on, the bar's screen is never opened (hos_radial_screen, at the start of the
   sequence's open-screen and close-screen nodes: nx2/oot_patches.py patch_radial_screens; its background, the paused game's
   blurred picture, still is): the game decides when the bar
   would show, and a radial menu shows instead for as long as it would have, the D-pad's for L and the items' for R (the last
   of the two pressed). The pause stays the game's own. An item radial menu's slot is equipped (its era's AssignableItem
   enum) a few reads after the release, once the game's sequence closed the bar. Reads of the game's memory go through
   gpu/vk/oot_game_data.h, which answers 0 for a page that is not committed. */
#include "radial_menu_game.h"

#include <string.h>

#include "../gpu/vk/oot_game_data.h"
#include "../gpu/vk/vk_api.h"

const MkwVkRadialMenu *rx_radial_menu(void);   /* (rx_backend.c) */

static const uint8_t *gw(void) { return (const uint8_t *)GP(0); }

/* the game paused by its own menus (its three pause steps' flags) */
static int oot_paused(void) {
    int p = 0, pre = 0, post = 0;
    oot_data_flag(gw(), "Sequence_IsPause", &p), oot_data_flag(gw(), "Sequence_IsPreGamePause", &pre);
    oot_data_flag(gw(), "Sequence_IsPostGamePause", &post);
    return p || pre || post;
}

/* Link is a child now (Sequence_IsChildhood) */
static int oot_childhood(void) {
    int child = 1;
    oot_data_flag(gw(), "Sequence_IsChildhood", &child);
    return child;
}

/* an enum of the game data set through the game's own setter (f_80400980: manager, the value's hash, the name's hash), which
   queues it for the manager's next update */
static void oot_enum_set(Ctx *c, const char *name, const char *value) {
    A64Fn set = a64_lookup(0x80400980ULL);
    const uint64_t mgr = oot_data_gdm(gw());
    if (!set || !mgr) return;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
    c->x[0] = mgr, c->x[1] = oot_data_hash(value), c->x[2] = oot_data_hash(name);
    set(c);
    *c = saved;
}

/* the sequence's item bar: its screen opened (hos_radial_screen) and not closed since; the radial menu its L or R asked for
   (the last of the two pressed: 1 the D-pad's, 2 the items') */
static volatile int bar_open;
static int last_kind = 2;

int hos_radial_screen(Ctx *c, int open) {
    const MkwVkRadialMenu *w = rx_radial_menu();
    if (!w || !w->enabled()) return 0;
    const uint64_t node = c->x[0], param = oot_data_ptr(gw(), node + 32) & ~3ULL, text = param ? oot_data_ptr(gw(), param) : 0;
    char name[16] = "";
    if (!text || !oot_data_rd(gw(), text, name, sizeof name - 1)) return 0;
    name[sizeof name - 1] = 0;
    if (strcmp(name, "ShortCut_00")) return 0;   /* (its background, ShortCutBG_00, opens: the paused game's blurred picture) */
    __atomic_store_n(&bar_open, open, __ATOMIC_RELEASE);
    const uint32_t v = recomp_load32(c, node + 24);   /* (done, as the node marks itself: the top bit, its count kept) */
    recomp_store32(c, node + 24, 0x80000000u | (v & 0x3fffffffu));
    return 1;
}

void radial_menu_pad_read(Ctx *c, uint64_t *buttons, int32_t stick[4]) {
    const MkwVkRadialMenu *w = rx_radial_menu();
    if (!w) return;
    static uint64_t was;
    static int idle;   /* (reads with neither L nor R held while the bar is taken as open: a close the sequence never made) */
    const uint64_t pressed = *buttons & ~was;
    was = *buttons;
    if (pressed >> 6 & 1) last_kind = 1;
    else if (pressed >> 7 & 1) last_kind = 2;
    int open = __atomic_load_n(&bar_open, __ATOMIC_ACQUIRE);
    if (open && !(*buttons >> 6 & 1) && !(*buttons >> 7 & 1) && ++idle > 30) __atomic_store_n(&bar_open, 0, __ATOMIC_RELEASE), open = 0;
    if (!open) idle = 0;
    /* a D-pad radial menu's slot pressed as the D-pad once the game's sequence has closed the bar and the game runs again (a
       press while it closes is the bar's), 8 reads (the D-pad's slots, 0 up and clockwise: Up 13, Right 14, Down 15, Left 12) */
    static const int dpad_bits[4] = {13, 14, 15, 12};
    static int dpad_bit = -1, dpad_reads;
    if (dpad_bit >= 0 && !open && !oot_paused() && dpad_reads < 8) *buttons |= 1ull << dpad_bit, dpad_reads++;
    if (dpad_reads >= 8) dpad_bit = -1, dpad_reads = 0;
    w->pad(buttons, stick, stick + 2, open ? last_kind : 0);
    static int pending_slot = -1, pending_wait;
    int used_kind = 0, used_slot = -1;
    if (w->used(&used_kind, &used_slot)) {
        if (used_kind == 1 && used_slot >= 0 && used_slot < 4) dpad_bit = dpad_bits[used_slot], dpad_reads = 0;
        if (used_kind == 2) pending_slot = used_slot, pending_wait = 12;   /* (the items') */
    }
    if (pending_slot >= 0 && --pending_wait <= 0) {
        const char *item = w->equip(pending_slot);
        if (item) oot_enum_set(c, oot_childhood() ? "PlayerStatus.AssignableItem.Child" : "PlayerStatus.AssignableItem.Adult", item);
        pending_slot = -1;
    }
}
