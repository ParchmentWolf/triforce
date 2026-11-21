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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../gpu/vk/oot_game_data.h"
#include "../gpu/vk/vk_api.h"

const MkwVkRadialMenu *rx_radial_menu(void);   /* (rx_backend.c) */

static const uint8_t *gw(void) { return (const uint8_t *)GP(0); }
static uint64_t rd_ptr(uint64_t a) { return oot_data_ptr(gw(), a); }

/* the event manager's singleton (main+0x4c7e090) holds the manager, whose +104 is the event running, 0 when none */
int oot_event_playing(void) {
    const uint64_t singleton = rd_ptr(OOT_DATA_MAIN + 0x4c7e090), events = singleton ? rd_ptr(singleton) : 0;
    return events && rd_ptr(events + 104) != 0;
}

void oot_link_state_at(char out[48], uint32_t at) {
    out[0] = 0;
    const uint64_t actor = oot_data_player(gw()), components = actor ? rd_ptr(actor + 0x270) : 0;
    const uint64_t c107 = components ? rd_ptr(components + 107 * 8) : 0;
    if (!c107 || !oot_data_rd(gw(), c107 + at, out, 47)) out[0] = 0;
    out[47] = 0;
}

int oot_childhood(void) {
    int child = 1;
    oot_data_flag(gw(), "Sequence_IsChildhood", &child);
    return child;
}

int oot_paused(void) {
    int p = 0, pre = 0, post = 0;
    oot_data_flag(gw(), "Sequence_IsPause", &p), oot_data_flag(gw(), "Sequence_IsPreGamePause", &pre);
    oot_data_flag(gw(), "Sequence_IsPostGamePause", &post);
    return p || pre || post;
}

/* (f_80400980: manager, the value's hash, the name's hash) */
void oot_enum_set(Ctx *c, const char *name, const char *value) {
    A64Fn set = a64_lookup(0x80400980ULL);
    const uint64_t mgr = oot_data_gdm(gw());
    if (!set || !mgr) return;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
    c->x[0] = mgr, c->x[1] = oot_data_hash(value), c->x[2] = oot_data_hash(name);
    set(c);
    *c = saved;
}

/* a text member of a game data struct set through the game's own setter (f_80464840: manager, the value's char * (its
   address), the struct's handle {its descriptor: the struct entry (kind 32) of its name; 0; flags 0}, the member's name's
   hash), which queues it for the manager's next update as the Equipment page's does. The handle, the char * and the text
   go below the stack */
static void oot_text_member_set(Ctx *c, const char *strct, const char *member, const char *value) {
    A64Fn set = a64_lookup(0x80464840ULL);
    const uint64_t mgr = oot_data_gdm(gw()), desc = oot_data_entry(gw(), 32, 0x20, oot_data_hash(strct));
    const size_t n = strlen(value) + 1;
    if (!set || !mgr || !desc || n > 64) return;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
    const uint64_t handle = c->x[31] + 0x80, ptr = handle + 0x10, text = ptr + 0x10;
    recomp_store64(c, handle, desc), recomp_store64(c, handle + 8, 0);
    for (size_t i = 0; i < n; i++) recomp_store8(c, text + i, (uint8_t)value[i]);
    recomp_store64(c, ptr, text);
    c->x[0] = mgr, c->x[1] = ptr, c->x[2] = handle, c->x[3] = oot_data_hash(member);
    set(c);
    *c = saved;
}

/* Link's equipment is the pouch's: PlayerStatus is its copy in the game data. The pouch takes the copy's equipment again
   through f_80f401b0 (the pouch, 0), what the sequence's SeqOneShotPouchTargetSyncEquipmentIndex does after a save's load
   (the pouch at [[main 0x84c9e0d0]]); Link then makes the equipment's actors. pouch_sync: pad reads left to wait
   for the game data manager's update to take the change (its member's value read again each one; 0 none due) */
static int pouch_sync;
static char sync_key[48], sync_value[64];

static void pouch_take_equipment(Ctx *c) {
    A64Fn sync = a64_lookup(0x80f401b0ULL);
    const uint64_t slot = rd_ptr(0x84c9e0d0ULL), pouch = slot ? rd_ptr(slot) : 0;
    if (!sync || !pouch) return;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
    c->x[0] = pouch, c->x[1] = 0;
    sync(c);
    *c = saved;
}

/* the boots and the head's piece (a mask, the Lens of Truth) are worn by a flag of the game data beside their PlayerStatus
   member, which keeps the piece while it is off (the game's own D-pad down and up set and clear it: its press puts the
   member's piece on). Their names are not in the game's files: the game data list's hashes. Set through the game's own
   setter for a Bool (f_806a2b20: the manager, the value, the hash), as host/hos_main.c oot_gd_set does */
#define WORN_BOOT 0xa6719419u
#define WORN_HEAD 0xc27c80fbu
static int worn_flag(uint32_t hash) {
    const uint64_t e = oot_data_entry(gw(), 0, 0x18, hash);
    uint8_t b = 0;
    return e && oot_data_rd(gw(), e + 0x16, &b, 1) && (b & 1);
}
static void worn_set(Ctx *c, uint32_t hash, int on) {
    A64Fn set = a64_lookup(0x806a2b20ULL);
    const uint64_t mgr = oot_data_gdm(gw());
    if (!set || !mgr) return;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
    c->x[0] = mgr, c->x[1] = (uint64_t)(on != 0), c->x[2] = hash;
    set(c);
    *c = saved;
}

/* a gear on the D-pad put on (radial_menu.h radial_menu_dpad_gear): the boots, a mask or the Lens of Truth already on are
   taken off (their flag cleared, the piece kept, as the game's own D-pad does) */
static void gear_put_on(Ctx *c, const char *member, const char *gear) {
    char key[48], now[64] = "";
    snprintf(key, sizeof key, "PlayerStatus.%s", member);
    oot_data_text(gw(), key, now);
    const uint32_t worn = !strcmp(member, "EquipBoot") ? WORN_BOOT : !strcmp(member, "EquipHeadArmor") ? WORN_HEAD : 0;
    const int on = !strcmp(now, gear) && (!worn || worn_flag(worn));
    if (on && !worn) return;
    if (!on) oot_text_member_set(c, "PlayerStatus", member, gear);
    if (worn) worn_set(c, worn, !on);
    snprintf(sync_key, sizeof sync_key, "%s", key), snprintf(sync_value, sizeof sync_value, "%s", gear);
    pouch_sync = 60;
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

/* the HUD's D-pad (its controller, handed over at its setup f_833dad80): its icons' animations, IsOcarinaVisible (+48),
   IsHeadVisible (+64), IsBootVisible (+72), IsNaviIconVisible (+88), kept at their start (off) while the radial menus are on:
   the D-pad's items show around it instead (radial_menu.h) */
static volatile uint64_t dpad_hud;

void hos_radial_dpad_hud(uint64_t hud) { __atomic_store_n(&dpad_hud, hud, __ATOMIC_RELEASE); }

/* the D-pad's own picture, the button font's D-pad in its text pane T_ShortCutUD_00, found through the layout's find-pane-by-
   name (f_8045e1e0: the layout, the D-pad's +32; the name), hidden while the radial menus are on: bit 0 of the pane's flags
   (+168) is its visibility, as the game's own hiding of a layout's root shows */
static void dpad_glyph(Ctx *c, uint64_t hud, int hide) {
    static const char name[] = "T_ShortCutUD_00";
    static uint64_t for_hud, pane;
    static int hidden;
    if (for_hud != hud) {
        for_hud = hud, pane = 0, hidden = 0;
        A64Fn find = a64_lookup(0x8045e1e0ULL);
        const uint64_t layout = rd_ptr(hud + 32);
        if (!find || !layout) return;
        const Ctx saved = *c;
        c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
        const uint64_t at = c->x[31] + 0x80;
        for (size_t i = 0; i < sizeof name; i++) recomp_store8(c, at + i, (uint8_t)name[i]);
        c->x[0] = layout, c->x[1] = at;
        find(c);
        pane = c->x[0];
        *c = saved;
        hos_log("radial menus: the HUD D-pad's picture, pane %#llx", (unsigned long long)pane);
    }
    if (!pane || hide == hidden) return;
    const uint32_t flags = recomp_load32(c, pane + 168);
    recomp_store32(c, pane + 168, hide ? flags & ~1u : flags | 1u);
    hidden = hide;
}

static const int dpad_icon_at[4] = {48, 64, 72, 88};

/* the Assignable D-Pad turned on while the HUD's own D-pad icons already show: each icon's animation put at its start (f_802f0fe0,
   as hos_radial_dpad_icon does to their next show), which leaves the icon off; the game shows them again itself when it is
   turned off (their next show) */
static void dpad_icons_off(Ctx *c) {
    const uint64_t hud = __atomic_load_n(&dpad_hud, __ATOMIC_ACQUIRE);
    A64Fn reset = a64_lookup(0x802f0fe0ULL);
    if (!hud || !reset) return;
    for (int i = 0; i < 4; i++) {
        const uint64_t anim = rd_ptr(hud + dpad_icon_at[i]);
        if (!anim) continue;
        const Ctx saved = *c;
        c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
        c->x[0] = anim;
        reset(c);
        *c = saved;
    }
    dpad_glyph(c, hud, 1);
}

int hos_radial_dpad_icon(Ctx *c, uint64_t anim) {
    static const int *const at = dpad_icon_at;
    const uint64_t hud = __atomic_load_n(&dpad_hud, __ATOMIC_ACQUIRE);
    if (!hud || !anim) return 0;
    int mine = 0;
    for (int i = 0; i < 4 && !mine; i++) mine = rd_ptr(hud + at[i]) == anim;
    if (!mine) return 0;
    const MkwVkRadialMenu *w = rx_radial_menu();
    const int on = w && w->dpad_mode();   /* (with an Assignable D-Pad: the game's own D-pad otherwise) */
    dpad_glyph(c, hud, on);
    return on;
}

/* the pause menu's page (0 Collection, 1 Equipment, 2 Items, 3 System; -1 none seen) and its focused pane, as its focus
   handler f_802ed660 (screen, pane) sees them: the pane's page object (+32, or through +32 then +48 for a pane in a part:
   flag 0x20 of +65), named at +128 -> +248 -> +24 */
static volatile int menu_page = -1;
static volatile uint64_t menu_pane, menu_screen;


static const char *guest_text(uint64_t a, char *buf, size_t cap) {
    buf[0] = 0;
    if (!a || !oot_data_rd(gw(), a, buf, cap - 1)) return buf;
    buf[cap - 1] = 0;
    for (size_t i = 0; buf[i]; i++)
        if ((unsigned char)buf[i] < 32 || (unsigned char)buf[i] > 126) return buf[i] = 0, buf;
    return buf;
}

/* the item or gear's name of the slot that holds the pane on the Items page (the pause menu's screen +776: its slots'
   count +112, list +120; a slot's pane +232, its item's name +144) or the Equipment page (+784: +72, +80; +216, +136) */
static const char *page_slot_name(int at, int count, int list, int pane_at, int name_at, char *buf, size_t cap) {
    const uint64_t screen = __atomic_load_n(&menu_screen, __ATOMIC_ACQUIRE), pane = __atomic_load_n(&menu_pane, __ATOMIC_ACQUIRE);
    const uint64_t pg = screen ? rd_ptr(screen + at) : 0, arr = pg ? rd_ptr(pg + list) : 0;
    int32_t n = 0;
    buf[0] = 0;
    if (!arr || !oot_data_rd(gw(), pg + count, &n, 4) || n <= 0 || n > 200) return NULL;
    int bottles = 0;   /* (the Items page's bottles are Item_Bottle, or named by what they hold: the first in its list is bottle A...) */
    for (int i = 0; i < n; i++) {
        const uint64_t slot = rd_ptr(arr + 8ull * i);
        char name[32];
        const int bottle = slot && !strncmp(guest_text(rd_ptr(slot + name_at), name, sizeof name), "Item_Bottle", 11);
        if (slot && rd_ptr(slot + pane_at) == pane) {
            if (bottle && bottles < 5) return snprintf(buf, cap, "Bottle%c", 'A' + bottles), buf;
            return guest_text(rd_ptr(slot + name_at), buf, cap)[0] ? buf : NULL;
        }
        bottles += bottle;
    }
    return NULL;
}

/* the slot's item under the cursor on the Items page (2), the Equipment page (1) or the Collection page (0: +792, two lists,
   the upgrades' (+72, +80) and the ocarinas' (+88, +96); a slot's pane +200, its name +120) */
static const char *menu_slot_name(int page, char *buf, size_t cap) {
    if (page == 2) return page_slot_name(776, 112, 120, 232, 144, buf, cap);
    if (page == 1) return page_slot_name(784, 72, 80, 216, 136, buf, cap);
    if (page == 0 && page_slot_name(792, 88, 96, 200, 120, buf, cap)) return buf;
    return page == 0 ? page_slot_name(792, 72, 80, 200, 120, buf, cap) : NULL;
}

/* the middle of a pause menu button's picture, in the layout's units (3840 x 2160, from the screen's middle, y up), as
   host/oot_menu.c button_rect reads its boxes: the hit box's middle (+0x58: its global matrix at +0x28, scale m[0], m[4],
   translation m[9], m[10]; its rectangle at +0x84), or the second box's translation (+0xfc, +0x100) when that box is shown
   (its scale, +0xd8) and near the hit box (a hit box over a side of its picture). The Items page keeps the other age's
   pictures away from their slots (off the screen): the hit box then. 1 when it has one */
static int button_middle(uint64_t button, float *x, float *y) {
    float m[12], b[4], c[2], s2 = 0;
    const uint64_t box = button ? rd_ptr(button + 0x58) : 0;
    if (!box || !oot_data_rd(gw(), box + 0x28, m, sizeof m) || !oot_data_rd(gw(), box + 0x84, b, sizeof b)) return 0;
    if (!(m[0] > 1e-3f) || !(m[4] > 1e-3f)) return 0;
    const float w = m[0] * b[2], h = m[4] * b[3];
    *x = m[9] + m[0] * b[0] + w * 0.5f, *y = m[10] + m[4] * b[1] + h * 0.5f;
    if (oot_data_rd(gw(), box + 0xd8, &s2, 4) && s2 > 1e-3f && oot_data_rd(gw(), box + 0xfc, c, sizeof c) &&
        c[0] - *x < w && *x - c[0] < w && c[1] - *y < h && *y - c[1] < h)
        *x = c[0], *y = c[1];
    return 1;
}

void hos_radial_menu_focus(uint64_t screen, uint64_t pane) {
    static const char *const pages[] = {"PaCollectMenu_00", "PaEquipmentMenu_00", "PaItemMenu_00", "PaSystemMenu_00"};
    uint8_t flags = 0;
    oot_data_rd(gw(), pane + 65, &flags, 1);
    const uint64_t at = (flags & 0x20) ? rd_ptr(pane + 32) + 48 : pane + 32, obj = rd_ptr(at);
    char page[64];
    guest_text(rd_ptr(rd_ptr(rd_ptr(obj + 128) + 248) + 24), page, sizeof page);
    int p = -1;
    for (int i = 0; i < 4; i++)
        if (!strcmp(page, pages[i])) p = i;
    __atomic_store_n(&menu_page, p, __ATOMIC_RELEASE), __atomic_store_n(&menu_pane, pane, __ATOMIC_RELEASE);
    __atomic_store_n(&menu_screen, screen, __ATOMIC_RELEASE);
}

/* a press of the game's own D-pad made for it (an ocarina played, Navi called): its bit and the reads it is held for, once the
   game's sequence has closed the bar and the game runs again (a press while it closes is the bar's); the game's pad: Up 13,
   Right 14 (Navi), Down 15, Left 12 (the ocarina) */
static int game_dpad_bit = -1, game_dpad_reads;

/* a value from a radial menu or the D-pad used: an ocarina played (the game's D-pad left), a gear worn (or taken off: the
   boots, a mask, the Lens), the rest assigned to ZR (the game's manager takes it at its next update). 1 for one held on ZR */
static int use_value(Ctx *c, const MkwVkRadialMenu *w, const char *value) {
    if (!value) return 0;
    if (!strncmp(value, "Item_Ocarina_", 13)) return game_dpad_bit = 12, game_dpad_reads = 0, 0;
    const char *member = w->gear_member(value);
    if (member) return gear_put_on(c, member, value), 0;
    oot_enum_set(c, oot_childhood() ? "PlayerStatus.AssignableItem.Child" : "PlayerStatus.AssignableItem.Adult", value);
    return 1;
}

void radial_menu_pad_read(Ctx *c, uint64_t *buttons, int32_t stick[4]) {
    const MkwVkRadialMenu *w = rx_radial_menu();
    if (!w) return;
    const int mode = w->dpad_mode();   /* (the Assignable D-Pad: 0 the game's own, 1 three slots and Navi, 2 four slots) */
    {
        static int mode_was;
        if (mode && !mode_was && !oot_paused()) dpad_icons_off(c);
        if (!oot_paused()) mode_was = mode;
    }
    static uint64_t was;
    static int idle;   /* (reads with neither L nor R held while the bar is taken as open: a close the sequence never made) */
    const uint64_t pressed = *buttons & ~was;
    was = *buttons;
    if (pressed >> 6 & 1) last_kind = 1;
    else if (pressed >> 7 & 1) last_kind = 2;
    int open = __atomic_load_n(&bar_open, __ATOMIC_ACQUIRE);
    if (open && !(*buttons >> 6 & 1) && !(*buttons >> 7 & 1) && ++idle > 30) __atomic_store_n(&bar_open, 0, __ATOMIC_RELEASE), open = 0;
    if (!open) idle = 0;
    /* the pause menu's Items and Equipment pages, with an Assignable D-Pad: the D-pad's items show (radial_menu.h), and a D-pad
       press puts what the cursor is on there; the D-pad does not move the cursor meanwhile (the stick does). Its page is
       forgotten once the game runs again */
    {
        int page = __atomic_load_n(&menu_page, __ATOMIC_ACQUIRE);
        if (!oot_paused()) __atomic_store_n(&menu_page, -1, __ATOMIC_RELEASE), page = -1;
        if (page != 0 && page != 1 && page != 2) page = -1;
        w->menu_page(page == 0 ? 3 : page);
        if (page >= 0 && mode) {
            static const int bits[4] = {13, 14, 15, 12};
            for (int d = 0; d < 4; d++)
                if (pressed >> bits[d] & 1) {
                    char name[64];
                    float x, y;
                    if (menu_slot_name(page, name, sizeof name)) {
                        const int at = button_middle(__atomic_load_n(&menu_pane, __ATOMIC_ACQUIRE), &x, &y);
                        w->dpad_put_item(d, name, at, x, y);
                    }
                }
            *buttons &= ~(0xfull << 12);
        }
    }
    /* in play, with an Assignable D-Pad, the D-pad is its items' (radial_menu.h), not the game's: a direction's press uses its
       item (use_value; one assigned to ZR: ZR (9) held while the direction is held, from 3 reads on, 9 at least). With three
       slots and Navi, up held is the game's right held (Navi) */
    static const int item_bits[4] = {13, 14, 15, 12};
    static int use_dir = -1, use_reads;
    if (mode && !open && oot_data_player(gw()) && !oot_paused() && !oot_event_playing()) {
        const int navi = mode == 1 && (*buttons >> 13 & 1);
        if (use_dir < 0)
            for (int d = mode == 1 ? 1 : 0; d < 4; d++) {
                if (!(pressed >> item_bits[d] & 1)) continue;
                const char *member = NULL, *item = w->dpad_equip(d), *gear = item ? NULL : w->dpad_gear(d, &member);
                if (gear) gear_put_on(c, member, gear);
                else if (use_value(c, w, item)) use_dir = d, use_reads = 0;
                break;
            }
        const int held = use_dir >= 0 && (*buttons >> item_bits[use_dir] & 1);
        *buttons &= ~(0xfull << 12);
        if (navi) *buttons |= 1ull << 14;
        if (use_dir >= 0) {
            if (++use_reads > 3 && (held || use_reads <= 9)) *buttons |= 1ull << 9;
            if (!held && use_reads > 9) use_dir = -1;
        }
    } else use_dir = -1;
    if (pouch_sync > 0) {   /* (once the change is in the game data, or a second on) */
        char now[64] = "";
        oot_data_text(gw(), sync_key, now);
        if (!strcmp(now, sync_value) || --pouch_sync == 0) pouch_sync = 0, pouch_take_equipment(c);
    }
    if (game_dpad_bit >= 0 && !open && !oot_paused() && game_dpad_reads < 8) *buttons |= 1ull << game_dpad_bit, game_dpad_reads++;
    if (game_dpad_reads >= 8) game_dpad_bit = -1, game_dpad_reads = 0;
    w->pad(buttons, stick, stick + 2, open ? last_kind : 0);
    /* a radial menu's slot used at its close, 12 reads on (once the game's sequence has closed the bar): the gear's worn, the
       items' used */
    static int pending_kind, pending_slot = -1, pending_wait;
    int used_kind = 0, used_slot = -1;
    if (w->used(&used_kind, &used_slot)) pending_kind = used_kind, pending_slot = used_slot, pending_wait = 12;
    if (pending_slot >= 0 && --pending_wait <= 0) {
        const char *member = NULL, *gear = pending_kind == 1 ? w->gear_equip(pending_slot, &member) : NULL;
        if (gear) gear_put_on(c, member, gear);
        else if (pending_kind == 2) use_value(c, w, w->equip(pending_slot));
        pending_slot = -1;
    }
}
