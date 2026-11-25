/* (Triforce, Evil HD) The Graphics tab's Evil HD row, read each frame (host/nn_vi.c, option HOS_OPT_EVIL_HD), and its
   render distance: the foliage's distances (host/evil_hd.h has why and the rule). Off, as it is unless chosen, nothing of
   the game is written. HOS_EVIL_HD=0 or 1 over the row; HOS_EVIL_HD_DIST=<1..4>: the factor (4), 1 the game's own. */
#include "hos.h"
#include "evil_hd.h"
#include <stdlib.h>
#include <string.h>

volatile float hos_evil_hd_factor = 1.0f;   /* (the render distance's factor now: 1, the game's own, with Evil HD off) */

void hos_evil_hd_tick(int row) {
    static int looked, refused;
    static const char *mode, *dist;
    static float applied = 1.0f;   /* (what the defaults hold now: the image as loaded has the game's own) */
    if (!looked) {
        looked = 1;
        mode = getenv("HOS_EVIL_HD");
        dist = getenv("HOS_EVIL_HD_DIST");
    }
    const float f = evil_hd_factor(row, mode, dist);
    hos_evil_hd_factor = f;
    if (f == applied || refused) return;
    float have[EVIL_HD_FOLIAGE_COUNT], want[EVIL_HD_FOLIAGE_COUNT];
    memcpy(have, GP(EVIL_HD_FOLIAGE_DEFAULTS), sizeof have);
    if (!evil_hd_foliage_known(have)) {   /* (another game version: these bytes are something else) */
        refused = 1;
        hos_log("evil hd: main+0x3eefd38 holds %g, %g, %g ..., not the foliage's distances this build knows: left alone",
                (double)have[0], (double)have[1], (double)have[2]);
        return;
    }
    evil_hd_foliage(f, want);
    memcpy(GP(EVIL_HD_FOLIAGE_DEFAULTS), want, sizeof want);
    applied = f;
    hos_log("evil hd: %s: the foliage drawn %.2fx as far (grass %.0f and %.0f m, ornaments %.0f m, low trees %.0f m and "
            "their shadows %.0f m) in the areas not visited yet this run (a restart: in all; HOS_EVIL_HD, HOS_EVIL_HD_DIST)", f == 1.0f ? "off" : "on",
            (double)f, (double)want[0], (double)want[1], (double)want[2], (double)want[5], (double)want[4]);
}
