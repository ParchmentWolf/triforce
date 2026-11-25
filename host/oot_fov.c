/* (Triforce) The System tab's Field of view row: the camera's vertical angle in play, in percent of the game's own.

   nx2/oot_patches.py (patch_fov) calls hos_oot_fov in the camera update f_804e48c0, right after it loads the angle (the
   camera's +0x13c, into s0) and before it writes the angle and its half angle's sine, cosine and tangent into the
   projection: the picture and the game's own culling are then both made from the angle chosen.

   Only the view of the game's first camera is changed, the one Link is played through; an event's camera (a cutscene)
   keeps the angle it was written with. The camera's own angle is never written: the game's zooms still move it, every
   update starts from it again, and at 100% the call returns before it reads anything, so the angle is the game's
   (oot_play.h oot_fov_angle has the rule). */
#include "hos.h"
#include "oot_play.h"
#include "../gpu/vk/vk_api.h"
#include <string.h>

int rx_option(int id, int otherwise);

void hos_oot_fov(Ctx *c, uint64_t camera) {
    const int percent = rx_option(HOS_OPT_FOV, 100);
    if (percent == 100 || percent < 50 || percent > 150 || !camera) return;

    const uint64_t views = recomp_load64(c, camera + 0x18);
    const uint64_t view = views ? recomp_load64(c, views + 8) : 0;
    if (!view || recomp_load64(c, view) != 0x84c18a88ULL) return;   /* (sead::LookAtCamera's vtable) */

    /* (CameraMgr's first camera gives the view of play, as host/hos_main.c oot_gameplay_view finds it for the free camera:
       portraits, reflections and the interface's views are others') */
    const uint64_t singleton = recomp_load64(c, 0x84ca6bc0ULL);
    const uint64_t manager = singleton ? recomp_load64(c, singleton) : 0;
    const uint64_t cameras = manager && recomp_load32(c, manager + 32) ? recomp_load64(c, manager + 40) : 0;
    const uint64_t main_camera = cameras ? recomp_load64(c, cameras) : 0;
    if (!main_camera || recomp_load64(c, main_camera + 120) != view) return;

    /* (an event plays: its camera is the event's own) */
    const uint64_t event_singleton = recomp_load64(c, 0x84c9e090ULL);
    const uint64_t events = event_singleton ? recomp_load64(c, event_singleton) : 0;
    if (events && recomp_load64(c, events + 104)) return;

    float angle;
    memcpy(&angle, c->vreg[0], sizeof angle);
    const float wide = oot_fov_angle(angle, percent);
    if (wide == angle) return;
    uint32_t bits;
    memcpy(&bits, &wide, sizeof bits);
    a64_vset64(c->vreg[0], bits);
}
