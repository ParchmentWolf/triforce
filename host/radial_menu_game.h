/* (Triforce) The radial menus' side in the game (radial_menu_game.c): the renderer's radial menus (gpu/vk/radial_menu.cpp,
   through its table: rx_radial_menu) shown in place of the game's item bar, and an item radial menu's slot equipped. */
#ifndef RADIAL_MENU_GAME_H
#define RADIAL_MENU_GAME_H
#include <stdint.h>

#include "hos.h"

/* nn_hid.c npad_states, the game's thread: the radial menus' part of a pad read (buttons, stick[0..1] left, [2..3] right) */
void radial_menu_pad_read(Ctx *c, uint64_t *buttons, int32_t stick[4]);
/* the sequence's open-screen (open 1) and close-screen (0) nodes, before they run (nx2/oot_patches.py): 1 when the screen is
   the item bar's (ShortCut_00; not its background) and the radial menus are on: the node is marked done, the screen left alone */
int hos_radial_screen(Ctx *c, int open);

#endif
