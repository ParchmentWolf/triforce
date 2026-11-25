/* ((Triforce) 11-24) Hold-to-toggle: a press of an enabled button holds it, the next press lets it go, for players who
   cannot keep a button held (the Controls tab's Hold to toggle rows; host/nn_hid.c npad_states). The buttons' edges,
   shared by the keyboard, the mouse and the pads after their remapping. No OS dependencies.
   down: the buttons held now; enabled: those that toggle; clear: every latch is dropped (the Insert menu, the window
   out of focus, a rebinding, Plus or Minus pressed, one of the game's menus opened), and an enabled button still held
   then counts again only once it was let go. What the game is given: the buttons that do not toggle as they are, and
   the latched ones. */
#pragma once
#include <stdint.h>
typedef struct { uint64_t previous, latched, blocked; } HoldToggle;
static inline uint64_t hold_toggle_apply(HoldToggle *s, uint64_t down, uint64_t enabled, int clear) {
    if (clear) {
        s->latched = 0;
        s->blocked = enabled;   /* (let go first: what is down at the next read is not a new press) */
        s->previous = down;
        return down & ~enabled;
    }
    s->blocked &= down;
    s->latched &= enabled;
    s->latched ^= down & ~s->previous & enabled & ~s->blocked;
    s->previous = down;
    return (down & ~enabled) | s->latched;
}
