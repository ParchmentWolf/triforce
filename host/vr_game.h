/* (Triforce VR) VR's side in the game (vr_game.c): its hooks in the game's camera update (nx2/oot_patches.py patch_vr), the
   pad's and the motion sensor's part, and the game's time held for Stereo Balanced. Everything does nothing without a VR
   session (the renderer's table, rx_xr) */
#ifndef VR_GAME_H
#define VR_GAME_H
#include <stdint.h>

#include "hos.h"
#include "hos_motion.h"

/* the camera update f_804e48c0 where its position, target and up are chosen (d0-d2, d3-d5, s7 s16 s6; x19 the camera's
   state): the head's view put on the gameplay camera, or on an event's while one plays */
void hos_vr_camera(Ctx *c);
/* the same update's load of the camera's vertical angle into s0 (from x19 + 0x13c): the headset's lens in its place */
void hos_vr_lens(Ctx *c);
/* the sequence's open-screen and close-screen nodes (x0): the item bar's background, for its place off the HUD's panel */
void hos_vr_screen(Ctx *c, int open);
/* nn_hid.c npad_states: the Touch controllers onto the pad (buttons, stick[0..1] left, [2..3] right), then first person's
   strafe (the game's thread) */
void vr_pad_read(Ctx *c, uint64_t *buttons, int32_t stick[4]);
/* nn_vi.c realtime_step: Stereo Balanced's hold of the game's time (1: the update about to run steps two frames' time, the
   next none), and the seconds the update steps, for the eye it draws */
int vr_holds_time(void);
void vr_update_step(double seconds);

/* (Triforce VR, VR_BODY "arms") Link's body in first person: his arms on the controllers, his head hidden (vr_body.c) */
/* hos_main.c hos_oot_lift_player, Link's movement update (Link known): his bones found, his head's materials kept hidden */
void vr_body_lift(Ctx *c, uint64_t actor);
/* after the late bone pass f_8030a320 (nx2/oot_patches.py patch_after_anim): his arms and head written into the bones' locals */
void hos_oot_after_anim(Ctx *c);
/* vr_game.c: first person's eyes are on Link now (the gameplay camera from his eyes, a moment ago) */
int vr_first_person_now(void);
/* vr_game.c: 1 and Link's feet as they were at the gameplay camera's last update with the head's view (where the hands were
   placed from), while that was a moment ago */
int vr_play_anchor(double feet[3]);
/* vr_game.c: the game paused by its own menus */
int vr_game_paused(void);
/* vr_game.c: Link a child now */
int vr_game_childhood(void);
/* vr_game.c: his sword is one for both hands (the Biggoron's Sword), and no item is in his hand */
int vr_game_two_handed(void);
/* nn_hid.c vibration_send: the game's rumble on a side (0 left, 1 right), 0 to 1, to the hand controllers */
void vr_rumble(int side, float strength);
/* vr_game.c: the item in his hand, its model's name ("" none) */
const char *vr_game_held(void);
/* vr_game.c: Link shows an item (a quest item held up) */
int vr_game_showing_item(void);
/* vr_body.c: Link as his movement update found him, 0 before */
uint64_t vr_body_link(void);
/* vr_body.c: 1 and his neck's height over his feet (metres) as the late bone pass last posed it, while that was a moment ago */
int vr_body_neck_height(double *height);
/* vr_body.c: each controller's arm (0 left, 1 right) as last posed, in the game's world: shoulder, elbow, wrist; ok[] the
   arms posed a moment ago; 0 neither */
int vr_body_arm_joints(float p[2][3][3], int ok[2]);
/* vr_body.c: 1 when the sword's hand is the right controller */
int vr_body_sword_right(void);
int vr_body_hand_bones(float m[24]);   /* (Triforce VR) Weapon_L's, Weapon_R's world 3x4s (rows), bits known; vr_body.c */
/* vr_game.c: what Link holds out now */
enum { VR_HELD_NONE, VR_HELD_SWORD, VR_HELD_DEKU_STICK, VR_HELD_HAMMER, VR_HELD_OTHER };
int vr_game_hand_held(void);
/* vr_game.c: a VR session playing Simplified: the sprint is Left stick click, Toggle (oot_sprint.c), whatever its rows say */
int vr_simplified_sprint(void);

#endif
