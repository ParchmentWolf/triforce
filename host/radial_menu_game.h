/* (Triforce) The radial menus' side in the game (radial_menu_game.c): the renderer's radial menus (gpu/vk/radial_menu.cpp,
   through its table: rx_radial_menu) shown in place of the game's item bar, and an item radial menu's slot equipped. And a
   few reads of the game's state the radial menus and other parts share. */
#ifndef RADIAL_MENU_GAME_H
#define RADIAL_MENU_GAME_H
#include <stdint.h>

#include "hos.h"

/* nn_hid.c npad_states, the game's thread: the radial menus' part of a pad read (buttons, stick[0..1] left, [2..3] right) */
void radial_menu_pad_read(Ctx *c, uint64_t *buttons, int32_t stick[4]);
/* the sequence's open-screen (open 1) and close-screen (0) nodes, before they run (nx2/oot_patches.py): 1 when the screen is
   the item bar's (ShortCut_00; not its background) and the radial menus are on: the node is marked done, the screen left alone */
int hos_radial_screen(Ctx *c, int open);
/* the HUD's D-pad's setup (f_833dad80, nx2/oot_patches.py) hands over its controller; hos_radial_dpad_icon, at the start of an
   animation's show (f_802f0f00) or frame (f_802f2d90): 1 when it is one of that D-pad's icons' and the radial menus are on (the
   animation is put at its start, the icon off, instead). It also keeps the D-pad's own picture hidden while they are on */
void hos_radial_dpad_hud(uint64_t hud);
int hos_radial_dpad_icon(Ctx *c, uint64_t anim);

/* an event plays (a cutscene, a conversation) */
int oot_event_playing(void);
/* Link's state's name (his component 107's name at +at: 0x244 his state, 0x34c his upper body's), "" when there is none */
void oot_link_state_at(char out[48], uint32_t at);
/* Link is a child now (Sequence_IsChildhood) */
int oot_childhood(void);
/* the game paused by its own menus (its three pause steps' flags) */
int oot_paused(void);
/* an enum of the game data set through the game's own setter (f_80400980), which queues it for the manager's next update */
void oot_enum_set(Ctx *c, const char *name, const char *value);

#endif
