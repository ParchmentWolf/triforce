/* (Triforce) When the game's texture data manager may ask its compaction thread for a round (host/oot_tex_compact.c
   hos_oot_tex_compact_due, nx2/oot_patches.py patch_tex_ask), apart from the game so that tests/test_oot_tex_compact.py can
   compile it alone.

   The manager steps every frame (f_80797240): with no round asked for (its +776) and bit 1 of its +960 set, it asks for one
   and sends the thread the message, so a round could start every frame. Each round moves texture data in the game's heap,
   and each texture moved is a new address to the renderer: captured, compared and hashed again. With a gap, an ask is let
   through only once that gap has passed since the last one let through; a round started always finishes, and the game asks
   again at its next step.

   HOS_OOT_TEX_ASK_MS=<n>: at most one ask every n ms. Unset, empty or not a number: 1000. 0: every ask, as shipped. off (or a
   negative number): none. */
#pragma once

#include <stdint.h>
#include <stdlib.h>

enum { HOS_OOT_TEX_ASK_DEFAULT_MS = 1000 };

/* The switch's value: the gap in ms, 0 every ask, -1 none */
static inline int hos_oot_tex_ask_ms(const char *e) {
    if (!e || !*e) return HOS_OOT_TEX_ASK_DEFAULT_MS;
    if (e[0] == 'o' && e[1] == 'f' && e[2] == 'f' && !e[3]) return -1;
    char *end;
    const long v = strtol(e, &end, 10);
    if (end == e || *end) return HOS_OOT_TEX_ASK_DEFAULT_MS;
    if (v < 0) return -1;
    return v > 3600000 ? 3600000 : (int)v;
}

/* Whether an ask goes through now. ms: the switch's value; now: the clock (ns); last: the time of the last ask let through,
   negative before the first, set here when this one goes through */
static inline int hos_oot_tex_ask_due(int ms, int64_t now, int64_t *last) {
    if (ms == 0) return 1;
    if (ms < 0) return 0;
    if (*last >= 0 && now - *last < (int64_t)ms * 1000000) return 0;
    *last = now;
    return 1;
}
