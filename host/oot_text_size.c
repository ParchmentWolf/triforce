/* (Triforce) The System tab's Text size row: the text of dialogue, Navi and signs drawn larger.

   nx2/oot_patches.py (patch_text_size) calls hos_oot_text_pane from f_80b1e140, the step of a LetterAnimControl (the text
   panes with "LetterAnimOn"), with that control, in the block the Text speed row's scale is in. The control's +0x28 is
   the game's pane wrapper: its +8 is the Layout2 text box pane, and its +0x28 and +0x38 are the diagonal of the text's 2D
   scale (0.8 each for dialogue). Each of the two keeps the game's own value, taken again whenever the game has written it
   since, and gets that value times the row's scale (oot_play.h has the rule).

   At Normal, the default, nothing of the game is read or written until a size was chosen in this run: the call returns
   at once. Back at Normal after another size, a field that was scaled gets the game's value back, and one never scaled
   is left alone.

   HOS_TEXT_SIZE=<0..4> stands over the row (0 Normal, 1 110%, 2 125%, 3 150%, 4 175%), as HOS_TEXT_SPEED does over Text
   speed (host/nn_vi.c). */
#include "hos.h"
#include "oot_play.h"
#include "../gpu/vk/vk_api.h"
#include <stdlib.h>
#include <string.h>

int rx_option(int id, int otherwise);

enum { TEXT_ANIM_WRAPPER = 0x28, TEXT_WRAPPER_PANE = 0x08, TEXT_WRAPPER_SCALE_X = 0x28, TEXT_WRAPPER_SCALE_Y = 0x38 };

void hos_oot_text_pane(Ctx *c, uint64_t anim) {
    static const char *env;
    static int looked;
    static volatile long scaled;   /* (a size other than Normal was seen in this run: fields may hold a value of ours) */
    if (!looked) env = getenv("HOS_TEXT_SIZE"), looked = 1;
    const float s = oot_text_size_scale(env && *env ? atoi(env) : rx_option(HOS_OPT_TEXT_SIZE, 0));
    if (s == 1.0f && !scaled) return;   /* (Normal, and nothing was ever scaled: the game's own, untouched) */
    const uint64_t wrapper = anim ? recomp_load64(c, anim + TEXT_ANIM_WRAPPER) : 0;
    if (!wrapper || !recomp_load64(c, wrapper + TEXT_WRAPPER_PANE)) return;   /* (a pane not set up yet) */

    /* (the fields of the panes seen: a new one takes the place of the one stepped longest ago. Only the text on screen is
       stepped, so that one's text is gone) */
    static OotTextField kept[64];
    static uint32_t tick;
    static volatile long lock;
    static const unsigned offs[] = {TEXT_WRAPPER_SCALE_X, TEXT_WRAPPER_SCALE_Y};
    while (__sync_lock_test_and_set(&lock, 1)) {}
    scaled = 1;
    tick++;
    for (unsigned i = 0; i < sizeof offs / sizeof offs[0]; i++) {
        const uint64_t a = wrapper + offs[i];
        const uint32_t now = (uint32_t)recomp_load32(c, a);
        OotTextField *f = NULL, *oldest = &kept[0];
        for (unsigned k = 0; k < sizeof kept / sizeof kept[0] && !f; k++) {
            if (kept[k].addr == a) f = &kept[k];
            else if (kept[k].seen < oldest->seen) oldest = &kept[k];
        }
        if (!f) {
            if (s == 1.0f) continue;   /* (Normal: a field never scaled stays the game's) */
            f = oldest, f->addr = a, f->game = f->written = now;
        }
        f->seen = tick;
        const uint32_t v = oot_text_size_value(f, now, s);
        if (v != now) recomp_store32(c, a, v);
    }
    __sync_lock_release(&lock);
}
