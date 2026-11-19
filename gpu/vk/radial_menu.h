// The radial menus (radial_menu.cpp): the D-pad's actions and the items, each in a fixed slot (0 up, clockwise), shown by the
// game's own icons for what the save owns. Any thread (game data reads).
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum { RADIAL_MENU_DPAD = 1, RADIAL_MENU_ITEMS = 2, RADIAL_MENU_ITEM_SLOTS = 16 };

// A texture of the game's files: its BNTX archive in the RomFS and its name in it
typedef struct {
    char file[96], tex[64];
} RadialMenuTex;

// What a slot shows: its icon and name, and small icons under it: the variants a tap swaps to, or the adult's arrows
// (then mini_selected frames the one in use; -1 none). Counts: the ammunition or stock left, -1 for an item without;
// maxes: how many can be carried now, -1 unknown
typedef struct {
    RadialMenuTex main;
    RadialMenuTex now;            // what is equipped from it: the variant in use (an arrow's own icon where main is the bow)
    const char *label;
    int count, max;
    RadialMenuTex mini[4];
    int mini_count[4], mini_max[4];
    int minis, mini_selected;
} RadialMenuSlot;

int radial_menu_slots(int kind);                        // the radial menu's slots
int radial_menu_slot(int kind, int slot, RadialMenuSlot *out);  // 1 when the slot holds something owned, and what it shows
int radial_menu_usable(int kind, int slot);             // the same without what it shows
void radial_menu_tap(int kind, int slot);               // a tap on the slot: its next owned variant (kept)
const char *radial_menu_equip(int slot);                // the item slot's AssignableItem value now, NULL when empty
int radial_menu_child(void);                            // Link is a child now (Sequence_IsChildhood)

// The radial menus' state (radial_menu.cpp), for the game's side (MkwVkRadialMenu) and the overlay (vk_menu.cpp):
// want = the radial menu the game's side asks for at this pad read (RADIAL_MENU_DPAD, RADIAL_MENU_ITEMS: while the game's item
// bar would show, host/radial_menu_game.c; 0 none, which closes one open), with the Radial menus row on; the stick of its side
// picks (left, right: -32767..32767, y up). Meanwhile the game gets the held L or R alone (its sequence keeps the bar open and
// the game paused): no stick or other button. 1 while one is open.
int radial_menu_pad(uint64_t *buttons, int32_t left[2], int32_t right[2], int want);
int menu_radial_menus(void);                  // the Radial menus row is on (vk_menu.cpp)
int radial_menu_used(int *kind, int *slot);   // a slot used at a radial menu's close (taken once): 1 with it
int radial_menu_open(int *slot);              // the radial menu open now (RADIAL_MENU_DPAD, RADIAL_MENU_ITEMS; 0 none) and its slot picked
const struct MkwVkRadialMenu *radial_menu_table(void);   // (vk_replay.cpp: the renderer's table's radial menu)

#ifdef __cplusplus
}

#include <cstdint>

// A radial menu's controller (radial_menu_pad): held = the buttons
// that open the radial menus (bit 0 the D-pad's, bit 1 the items'), sticks = each radial menu's stick (-1..1, x right, y up). A radial menu
// opens while its button is held (the first held wins) and allowed; the stick pushed past half picks the slot it points at;
// the stick toward a slot and back within flick_ns steps its variants (radial_menu_tap); the button's release uses the slot
// the stick is held toward (an empty slot, or none, does nothing).
struct RadialMenuCtl {
    static constexpr uint64_t flick_ns = 300000000ull;
    int open = 0, slot = -1;
    int tap_slot = -1;
    uint64_t tap_since = 0;
    struct Out {
        bool closed = false;
        int used_kind = 0, used_slot = -1;
    };
    Out step(int held, bool allowed, const float sticks[2][2], uint64_t now);
    void reset() { open = 0, slot = -1, tap_slot = -1; }
};
#endif
