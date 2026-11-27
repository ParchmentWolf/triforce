// VR through OpenXR (vk_xr.cpp), the VR row on at start. Off, the functions below
// do nothing and make no OpenXR call. The game's side (host/vr_game.c, nn_hid.c, nn_vi.c) reaches the ones it calls through
// the renderer's table (vk_api.h MkwVkXr, vk_xr_table); the renderer calls the rest itself.
#pragma once

#include <stdint.h>

#include "vk_loader.h"

struct MkwVkXr;

#ifdef __cplusplus
extern "C" {
#endif

// vk_main.cpp create_instance: the OpenXR instance and the headset found, and the Vulkan instance extensions the runtime
// needs appended to ext[*n..cap)
void vk_xr_instance_exts(const char **ext, uint32_t *n, uint32_t cap);
// vk_main.cpp pick_device: the GPU the headset's runtime draws with (VK_NULL_HANDLE: no VR), and the one picked: VR goes
// off when they differ
VkPhysicalDevice vk_xr_device(VkInstance instance);
void vk_xr_device_picked(VkPhysicalDevice picked);
// vk_main.cpp create_device: the device extensions the runtime needs appended to ext[*n..cap), those the device has
void vk_xr_device_exts(const VkExtensionProperties *have, uint32_t n_have, const char **ext, uint32_t *n, uint32_t cap);
// vk_main.cpp create_device: the index of the graphics family's queue VR copies on, first_free when the family has it
// (the device is then made with one queue more), else UINT32_MAX and VR off
uint32_t vk_xr_queue(uint32_t family_queues, uint32_t first_free);
// vk_main.cpp, the device made: VR's queue and semaphore, and the session's thread started
void vk_xr_device_ready(VkInstance instance, VkPhysicalDevice phys, VkDevice device, uint32_t family);

// The head's view (the VR view row's Head): the game's camera follows the headset
int vk_xr_head_wanted(void);
// Depth stereo (the VR depth row above 0 with the head's view): each eye's picture made from the game's one and its
// depth; vk_draw.cpp keeps the scene's camera and depth for each present while this is 1 (vk_temporal.cpp's camera)
int vk_xr_depth_wanted(void);
// vk_draw.cpp xr_stand_in, once the scene is drawn and before later passes reuse its depth target: the scene's depth (a sampled
// view, in GENERAL) copied for this frame's depth stereo; binds a compute pipeline and push descriptors of its own
void vk_xr_keep_depth(VkCommandBuffer cb, VkImageView depth, uint32_t w, uint32_t h);
// Stereo Accurate: metres from the left eye's camera to the right's while it is on (0: not now); the right eye's pass (vk_replay.cpp)
// begins (phase 1: the left eye's target copied apart) and ends (0)
float vk_xr_accurate_shift(void);
// Stereo Balanced: metres to move the frame before's camera onto this picture's eye (+ right), 0 not now
float vk_xr_balanced_prev_shift(void);
// Flatscreen 3D (the VR tab's Flatscreen 3D rows, no headset): wanted now; the window's picture made in 3D before the menu is
// drawn over it (window in TRANSFER_DST_OPTIMAL; rect: the game's picture's own size, to: its place in the window)
int vk_xr_flat_wanted(void);
void vk_xr_flat3d(VkCommandBuffer cb, VkImage window, int hdr, const int rect[4], const int to[4]);
void vk_xr_second_eye(VkCommandBuffer cb, int phase);
// vk_draw.cpp xr_stand_in, with the depth: the view the scene was drawn with (rows 0-2 of its 3x4 view: right, up, back, each with
// its translation), so the picture is matched to the camera update that gave it (the game draws a frame behind them)
void vk_xr_scene_camera(const float rows[12]);
// The head's view is on now (the session running, the menu closed): vr_game.c's first person applies
int vk_xr_head_active(void);
// vr_game.c, the gameplay camera's update: 1 when the head's view applies now, the camera's position, target and up
// (game units) then turned and moved by the head (its yaw kept, the horizon level); the pose is kept for the picture
// drawn from it
int vk_xr_camera(double pos[3], double at[3], float up[3], int in_place);
// Stereo Balanced (host/nn_vi.c realtime_step): 1 while the game's time is held for every second update, the right eye's
int vk_xr_holds_time(void);
// vr_game.c, before vk_xr_camera: the game seconds the update running now steps (-1 unknown), which tells Stereo
// Balanced's eye: the held update draws the right one
void vk_xr_update_step(double seconds);
// vr_game.c, the same update's angle load: 1 and the vertical angle (radians) the headset's lens needs, after a
// vk_xr_camera that applied
int vk_xr_lens(float *angle);
// host/nn_hid.c, each pad read: the hand controllers' buttons ORed onto *buttons (1 << HOS_SW_* bits) and each stick
// (left[2], right[2]: x, y, up +y, -32767..32767) replaced by the controller's where it is pushed farther; 1 when a
// controller is in use now
int vk_xr_pad(uint64_t *buttons, int32_t left[2], int32_t right[2]);
// vr_game.c, the game's thread: Link plays the ocarina now (the controllers' notes then on the right stick)
void vk_xr_ocarina(int on);
// vr_game.c, the game's thread: Link holds his sword and shield (or another weapon) out now, so the draw gesture puts
// them away
void vk_xr_weapon_out(int out);
void vk_xr_two_handed_sword(int on);   // ((Triforce VR) vr_game.c: his sword is the Biggoron's, for the head tilt's Z-target
int vk_xr_arms_own(void);   // ((Triforce VR) vr_body.c: his arms the animation's now (a bow or slingshot drawn, a hammer swing)
void vk_xr_game_paused(int on);   // ((Triforce VR) vr_game.c: the game paused by its menus
void vk_xr_rumble(int side, float strength);   // ((Triforce VR) nn_hid.c: the game's rumble, to the hand controllers
void vk_xr_turning(float strength);   // ((Triforce VR) vr_game.c: Smooth turning now, for the Turn vignette
// vr_game.c, each frame: Link is a child (VR's hands draw his own for his age on a hand that holds nothing)
void vk_xr_child(int child);
// vr_game.c, the game's thread: the item Link uses now, by its model's name ("Item_DekuStick"), "" none
void vk_xr_hand_item(const char *model);
// vr_physics.c: an item's size from its mesh (vk_xr_item_shape)
int vk_xr_item_shape(const char *actor, float out[3]);
// vr_game.c's room capture: shot >= 0 saves that shot from this camera (cam: pos, at, up), -1 only says it runs
void vk_xr_room_shot(int shot, const double cam[9], const double link[3]);
// vr_body.c, each frame: Link's Weapon_L then Weapon_R in the world (rows of a 3x4, metres); ok bit 0 left, bit 1 right
void vk_xr_hand_bones(const float bones[24], int ok);
/* (Triforce VR) the physics' shapes for Show physics shapes: n capsules of 8 floats (end a x y z, radius, end b x y z, kind), world, metres */
void vk_xr_phys_shapes(const float *caps, int n);
// vr_game.c, the game's thread: in play now (not a menu, a pause, an event), the Touch controllers' play roles on
void vk_xr_in_play(int on);
void vk_xr_item_bar(int open);
// vr_game.c, the gameplay camera's update: while the controller steers the aim, the view's base yaw held (on); and
// where the sword hand's controller points, a unit direction in the game's world; 0 when its pose is not known
void vk_xr_aim_freeze(int on);
int vk_xr_pointer(double dir[3]);
// vr_game.c, the gameplay camera's update before vk_xr_camera: Link aims (on) along the game's own camera's ray
// (origin, unit direction; game units): the head's view draws the reticle where it lands
void vk_xr_aim(int on, const double origin[3], const double dir[3]);
// The game's own view this frame (the head's view not applied); its pictures go on the screen
void vk_xr_untracked(void);
// host/vr_body.c (VR_BODY arms), the game's thread: each hand controller (0 left, 1 right) in the game's world as the head's
// view maps the LOCAL space at the last camera update: its grip's place (game units), where it points (the grip's -z) and
// its palm's facing (the grip's +x out of the left palm, into the right), unit directions; a hand not tracked all 0. 1
// when any is tracked and the head's view is on
int vk_xr_hands(double pos[6], double point[6], double palm[6]);
void vk_xr_item_menu(const MkwVkItemMenu *menu);
int vk_xr_item_pick(void);
// host/vr_physics.c, the grab: the grips squeezed in play (bit 0 left, 1 right; 0 out of play or without a session), and the
// hands it marks as near a body it can take or holding one: their grips then have no play roles (item, sword, bow, mask, shield)
int vk_xr_grips(void);
void vk_xr_grab_hands(int hands);

// vk_draw.cpp, the game's scene upscaled into target (w x h, format), the HUD still to
// be drawn over it: the image VR keeps it in (the caller copies it there in its stream), VK_NULL_HANDLE when the HUD's
// panel is not made now. *init 1: the image is new (UNDEFINED; the caller makes it GENERAL first)
VkImage vk_xr_scene_image(VkImage target, uint32_t w, uint32_t h, VkFormat format, int *init);
// after it: the picture the HUD is drawn apart in (vk_draw.cpp xr_hud_again), twice as wide as the scene, over black in its left half
// and over white in its right; *init as the scene's. Null: none, the panel is made from what the HUD changed
VkImageView vk_xr_hud_layer(VkImage *image, int *init);
/* the game's item bar is open (its background screen: vr_game.c); and while the game is paused for it, its frame's first draw
   into the HUD's target: 1 while that is the target the layer is for, the layer then this frame's panel */
int vk_xr_item_bar_open(void);
int vk_xr_item_bar_layer(VkImage target, uint32_t w, uint32_t h);
// (diagnostics) a gameplay upscale's dispatch seen while VR is on; taken: its output found and kept for VR
void vk_xr_note_upscale(int taken);
// the hand controllers' buttons (HOS_SW_* bits, as labelled) and sticks while they are a menu's (not in play): 1, for this
// menu's own input (vk_menu.cpp); 0 none
int vk_xr_menu_buttons(uint64_t *buttons, float sticks[2][2]);

// vk_replay.cpp present_image: 1 when VR takes this present's window image (then in TRANSFER_SRC_OPTIMAL for
// vk_xr_capture); 0 records nothing
int vk_xr_wants_capture(int hdr);
// The game's picture (picture, its layout and rect {x, y, w, h}) when it was drawn from the head, else the window's
// image, copied into one of VR's own images; *signal: what the present's submit signals for it
void vk_xr_capture(VkCommandBuffer cb, VkImage window, VkExtent2D extent, VkFormat format, VkImage picture,
                   VkImageLayout picture_layout, const int rect[4], VkSemaphoreSubmitInfo *signal);
// The present's submit went out with that signal: the image is the newest
void vk_xr_captured(const VkSemaphoreSubmitInfo *signal);

// vk_temporal.cpp, the scene's camera: its projection (row major, clip = P * view position) and whether the depth's clip range is
// -w..w; vk_xr_planes then gives the stored depth d of a view distance z as planes[0] + planes[1] / z, 0 without a recent one
void vk_xr_note_projection(const float proj[16], int minus_w);
void vk_xr_note_view(const float view[12]);
int vk_xr_planes(float planes[2]);
// a session runs: frame generation and the present's hold stand aside
int vk_xr_active(void);
// the VR row is on in the options file (read from the file: before the menu has it)
int vk_xr_row_on(void);
// the Insert menu's VR rows (vk_menu.cpp) by key ("VR_VIEW"): the value as text, "" for none
const char *vk_xr_cfg(const char *key);
// the game's side's table (vk_api.h MkwVkXr)
const struct MkwVkXr *vk_xr_table(void);

#ifdef __cplusplus
}
#endif
