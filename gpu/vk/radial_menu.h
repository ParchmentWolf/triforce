// The radial menus (radial_menu.cpp): the gear (L: the swords, the tunics, the shields) and the items (R), each in a fixed slot
// (clockwise from the top), shown by the game's own icons for what the save owns. Any thread (game data reads).
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum { RADIAL_MENU_GEAR = 1, RADIAL_MENU_ITEMS = 2, RADIAL_MENU_ITEM_SLOTS = 16, RADIAL_MENU_GEAR_SLOTS = 9 };

// A texture of the game's files: its BNTX archive in the RomFS and its name in it; gray: drawn without colour (a gear Link's
// age cannot wear, as the game's Equipment page shows it)
typedef struct {
    char file[96], tex[64];
    int gray;
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
int radial_menu_usable(int kind, int slot);             // owned and usable now (a gray gear is not)
int radial_menu_can_swap(int kind, int slot);           // 1 when ZL/ZR would step the slot to another owned variant
int radial_menu_tap(int kind, int slot, int dir);       // the slot's next (dir 1) or previous (-1) owned variant (kept): 1 to a later one, 2 an earlier, 0 none
// The item slot's value now, NULL when empty: an AssignableItem value, an ocarina ("Item_Ocarina_Time": played as the game's
// D-pad plays it) or a gear's name (worn: radial_menu_gear_member)
const char *radial_menu_equip(int slot);
// The gear radial menu's slot's gear wearable now (owned, at Link's age), and its PlayerStatus member; NULL when not
const char *radial_menu_gear_equip(int slot, const char **member);
// A gear's PlayerStatus member ("EquipWeapon", "EquipHeadArmor"...) by its name, NULL when the name is no gear's
const char *radial_menu_gear_member(const char *name);
int radial_menu_child(void);                            // Link is a child now (Sequence_IsChildhood)

// The radial menus' state (radial_menu.cpp), for the game's side (MkwVkRadialMenu), the overlay (vk_menu.cpp) and other inputs:
// want = the radial menu the game's side asks for at this pad read (RADIAL_MENU_GEAR, RADIAL_MENU_ITEMS: while the game's item
// bar would show, host/radial_menu_game.c; 0 none, which closes one open), with the Radial menus row on; the right stick picks
// for both (-32767..32767, y up: the left thumb stays free for the D-pad). Meanwhile the game gets the held L or R alone (its
// sequence keeps the bar open and the game paused): no stick or other button. 1 while one is open.
int radial_menu_pad(uint64_t *buttons, int32_t left[2], int32_t right[2], int want);
int menu_radial_menus(void);                  // the Radial menus row is on (vk_menu.cpp)
int radial_menu_used(int *kind, int *slot);   // a slot used at a radial menu's close (taken once): 1 with it
int radial_menu_open(int *slot);              // the radial menu open now (RADIAL_MENU_GEAR, RADIAL_MENU_ITEMS; 0 none) and its slot picked
int radial_menu_allowed(void);                // the last pad read allowed a radial menu to open
uint64_t radial_menu_closed_at(void);         // when a radial menu last closed (mkwvk::now_ns), 0 never
// Another input's radial menu (a hook: its own RadialMenuCtl): open and its slot while open (0 when closed), and a slot it used
void radial_menu_external(int open, int slot);
void radial_menu_external_used(int kind, int slot);
const struct MkwVkRadialMenu *radial_menu_table(void);
// The Assignable D-Pad row (vk_menu.cpp, with the Radial menus row on): 0 off (the game's own D-pad), 1 three slots and Navi
// (up: Navi, as the game's right), 2 four slots
int radial_menu_dpad_mode(void);
// The D-pad's items (with an Assignable D-Pad): an item slot or a gear on each D-pad direction (0 up, clockwise), put there by
// a D-pad press while a radial menu is open (on the slot the stick points at; a direction is never emptied) or on the pause
// menu's Items and Equipment pages, kept in triforce_radial_dpad.txt beside the options file. In play a direction's press uses
// it (host/radial_menu_game.c); the game's D-pad icons stay off (its HUD's Is*Visible animations) and these show around it.
// Each direction keeps an item, not a slot: the first value of its variant (the one owned best is used: Longshot before
// Hookshot, the ocarinas, the mask held), or a gear's name; on one direction alone however it was put. The child and the
// adult keep their own four (the adult's down starts with the bombs)
const char *radial_menu_dpad_equip(int dir);   // its value now (radial_menu_equip's kind), NULL when none, not owned or not Link's age's
// its icon (gray: not owned, or the other age's), and its count (-1 none) and how many can be carried; 0 when nothing owned is on it
int radial_menu_dpad_icon(int dir, RadialMenuTex *out, int *count, int *max);
int radial_menu_dpad_hud(void);                // the game's HUD shows its D-pad now (in play, nothing over it)
const char *menu_radial_dpad_path(void);       // the file the D-pad's items are kept in (vk_menu.cpp)
// The pause menu's page shown now (host/radial_menu_game.c: 1 Equipment, 2 Items, 3 Collection; -1 none or another): on those the D-pad's
// items show (vk_menu.cpp), and a D-pad press puts the item the cursor is on (its item name, the game's: "Item_DekuStick")
void radial_menu_menu_page(int page);
int radial_menu_menu_page_now(void);
// 1 when the item is one of the radial menu's slots' or a gear's (put there); from_layout: (x, y) is where it was put from,
// in the pause menu's layout (its units: 3840 x 2160, from the middle, y up), and it flies from there to its direction
int radial_menu_dpad_put_item(int dir, const char *item, int from_layout, float x, float y);
// The last put's flight, while it lasts (1): its direction, the radial menu (RADIAL_MENU_GEAR, RADIAL_MENU_ITEMS) and slot it
// left (-1 none), or its start in the pause menu's layout (from_layout), and how far along (0..1). The direction shows its icon
// once it has landed
int radial_menu_dpad_fly(int *dir, int *radial_kind, int *radial_slot, int *from_layout, float *x, float *y, float *t);
// A put's sound due since the last call (vk_menu.cpp menu_take_sound): 1 put (HOS_MENU_SOUND_ITEM_EQUIP), 2 refused (not
// owned, the other age's, nothing there: HOS_MENU_SOUND_ITEM_ERROR), 0 none
int radial_menu_take_put_sound(void);   // 1 put, 2 refused, 3 a slot picked, 4 a slot's variants stepped
// A refused put's shake of the radial menu's slot it was put from: 1 while it lasts, *t how far along (0..1)
int radial_menu_shake(int kind, int slot, float *t);
// A ZL/ZR swap's turn of the slot's icons: 1 while it lasts, *t how far along (0..1), *id the swap's own (a new one each),
// *cw clockwise (to a later variant; to an earlier one: counter-clockwise)
int radial_menu_swap_anim(int kind, int slot, float *t, uint64_t *id, int *cw);
// A gear on the direction (from the Equipment page: a sword, a shield, a tunic, boots): its name and its PlayerStatus member
// ("EquipWeapon"), NULL when none or not wearable now (not owned, or not at Link's age)
const char *radial_menu_dpad_gear(int dir, const char **member);

#ifdef __cplusplus
}

#include <cstdint>

// A radial menu's controller, the same for every input that opens the radial menus (a gamepad's L and R: radial_menu_pad): held = the buttons
// that open the radial menus (bit 0 the gear's, bit 1 the items'), sticks = each radial menu's stick (-1..1, x right, y up). A radial menu
// opens while its button is held (the first held wins) and allowed; the stick pushed past half picks the slot it points at;
// swap steps the picked slot's variants (radial_menu_tap): 1 on (ZR), -1 back (ZL); the button's release uses the slot
// the stick is held toward (an empty slot, or none, does nothing).
struct RadialMenuCtl {
    int open = 0, slot = -1;
    struct Out {
        bool closed = false;
        int used_kind = 0, used_slot = -1;
    };
    Out step(int held, bool allowed, const float sticks[2][2], uint64_t now, int swap = 0);
    void reset() { open = 0, slot = -1; }
};
#endif
