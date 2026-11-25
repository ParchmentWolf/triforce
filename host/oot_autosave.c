/* (Triforce) The System tab's Autosave row: Off skips the game's autosaves of going from one area to another.

   nx2/oot_patches.py (patch_autosave) calls hos_oot_save_request at the head of f_80bc72d0, where the game asks its save
   manager for a save, before the request is queued. With the row On, the default, the call returns 0 before it reads
   anything and the request goes on as the game made it. With it Off, a request that is one of a crossing's three (the
   transition's own and the arrival's two: oot_play.h oot_autosave_transition) is answered with 0, "not queued", and the
   function returns; every other request, the pause menu's Save among them, goes on. Other things the game autosaves at
   are not known here and still save.

   HOS_OOT_TRACE_SAVES=1 logs each request (its reason, mode and where it came from) and each one skipped. */
#include "hos.h"
#include "oot_play.h"
#include "../gpu/vk/vk_api.h"
#include <stdlib.h>

int rx_option(int id, int otherwise);

int hos_oot_save_request(Ctx *c) {
    static int trace = -1;
    if (trace < 0) {
        const char *e = getenv("HOS_OOT_TRACE_SAVES");
        trace = e && *e && *e != '0';
    }
    const int on = rx_option(HOS_OPT_AUTOSAVE, 1) != 0;
    if (on && !trace) return 0;   /* (the row On: the game's own, nothing read) */
    const uint64_t caller = c->x[30];
    const uint64_t parent = caller == 0x80bc7764ULL ? recomp_load64(c, c->x[31] + 24) : 0;   /* (the wrapper's saved return address) */
    const uint32_t reason = (uint32_t)c->x[1], mode = (uint32_t)c->x[2];
    if (trace)
        hos_log("save trace: reason=%u mode=%u caller=%#llx request_site=%#llx", (unsigned)reason, (unsigned)mode,
                (unsigned long long)caller, (unsigned long long)(parent ? parent : caller));
    if (on || !oot_autosave_transition(caller, parent, reason, mode)) return 0;
    if (trace) hos_log("save trace: an area's autosave skipped (the Autosave row is Off)");
    c->x[0] = 0;
    return 1;
}
