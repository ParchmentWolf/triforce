/* (Triforce) The System tab's Skip opening row: a new game without its opening, the story movie and Navi waking Link.

   The new-game opening, build e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348. Sequence/Opening.module.ainb requests
   Opening_Introduction and Opening_LoadingKokiriForest (SeqOneShotRequestEvent, f_80d9a820; the event's name is the
   pointer at the request's arg + 6800, as host/hos_main.c's own requests write it). Opening_Introduction's flowchart
   writes the state on both of its paths: the clock at 6:00, Meet_DekuTree's challenge Step01, the forest terrain pin,
   then EventTransition of the timeline Dm_Kokiri_0030. Its own skip query (IsEventSkipedMostRecent, f_80de6cb0) then
   takes the short edge: Navi warped to the position that edge names, the in-game music, Navi's talked flag, the camera
   handed back, and an autosave. Opening_LoadingKokiriForest's flowchart plays the timeline Dm_Kokiri_0000 and then waits
   until the forest has loaded. Neither timeline writes save data. Meet_DekuTree is a later flow and none of these names.

   With the row On the request is still sent, so the flowchart applies that edge. The two timelines are not started:
   f_83b5bfb0 is their only starter (EventTransition's call at 0x80eaba00), and leaving bit 0 of the timeline player's
   +0xf25 clear makes that caller take its own exit at 0x80eac5e0, which finishes the action, in place of the one at
   0x80eac640 that leaves the timeline running. The skip query is answered yes only while one of these two requests is
   the current one, so the short edge runs and a title demo that uses the same query does not.

   nx2/oot_patches.py (patch_opening) calls hos_oot_opening at the head of those three functions. mode 0 sees a request,
   1 a timeline's start (returns 1: do not start it), 2 the skip query (returns 1: x0 is 1), 3 Link is updated and no
   event plays (the opening has let him go: host/hos_main.c). With the row Off, the default, every mode returns 0 before
   it reads anything of the game, and the game's functions run as they are. */
#include "hos.h"
#include "../gpu/vk/vk_api.h"
#include <string.h>

int rx_option(int id, int otherwise);
void hos_log(const char *fmt, ...);

static volatile int armed;   /* (one of the opening's two requests is the current one) */

/* 1 while a request of the opening's is the current one (never with the row Off) */
int hos_oot_opening_armed(void) { return armed; }

int hos_oot_opening(Ctx *c, int mode) {
    static char logged[64];
    char name[80];
    uint64_t p = 0;
    if (mode == 3) {
        armed = 0;
        logged[0] = 0;
        return 0;
    }
    if (!c || rx_option(HOS_OPT_SKIP_OPENING, 0) <= 0) {
        armed = 0;
        return 0;
    }
    name[0] = 0;
    if (mode == 0) {
        const uint64_t arg = c->x[1];
        p = arg ? recomp_load64(c, arg + 6800) : 0;
    } else if (mode == 1 && c->x[1]) {
        p = recomp_load64(c, c->x[1]);   /* (EventTransition passes a pointer to the timeline's name) */
    }
    if (p) {
        size_t i = 0;
        for (; i + 1 < sizeof name; i++) {
            name[i] = (char)recomp_load8(c, p + i);
            name[i + 1] = 0;
            if (!name[i]) break;
        }
    }
    if (mode == 0) {
        if (!strcmp(name, "Opening_Introduction") || !strcmp(name, "Opening_LoadingKokiriForest")) {
            armed = 1;
            if (strcmp(logged, name)) {
                size_t i = 0;
                for (; name[i] && i + 1 < sizeof logged; i++) logged[i] = name[i];
                logged[i] = 0;
                hos_log("opening skip: %s request sent", name);
            }
        } else if (name[0]) {
            /* (another event, Meet_DekuTree among them, is not skipped and ends the watch) */
            armed = 0;
            logged[0] = 0;
        }
        return 0;   /* (the request is still sent) */
    }
    if (!armed) return 0;
    if (mode == 2) {
        c->x[0] = 1;
        return 1;
    }
    if (mode == 1 && (!strcmp(name, "Dm_Kokiri_0000") || !strcmp(name, "Dm_Kokiri_0030"))) {
        const uint64_t player = c->x[0];
        if (player) recomp_store8(c, player + 0xf25, recomp_load8(c, player + 0xf25) & ~(uint64_t)1);
        return 1;
    }
    return 0;
}
