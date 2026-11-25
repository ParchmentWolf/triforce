/* (Triforce) The rules of the rows of how the game plays (gpu/vk/vk_menu.cpp; vk_api.h's options 200 and on), apart from the
   game's memory and the menu, so that tests/test_play_rows.py runs them without the game. Each answers with the game's own
   value while its row is at its default. */
#pragma once

#include <math.h>
#include <stdint.h>
#include <string.h>

/* The Field of view row (host/oot_fov.c): the camera's vertical angle, in radians, the game's own as it loaded it, at a row
   value of percent (50 to 150, 100 the game's own). The game's angle itself at 100, for a percent outside the row and for
   an angle that is not one (not finite, 0 or less, half a turn or more); otherwise its share, kept within 5 to 140
   degrees whatever a zoom of the game's makes of it. */
static inline float oot_fov_angle(float angle, int percent) {
    if (percent == 100 || percent < 50 || percent > 150) return angle;
    if (!isfinite(angle) || angle <= 0.0f || angle >= 3.141592654f) return angle;
    return fminf(2.443460953f, fmaxf(0.087266463f, angle * ((float)percent / 100.0f)));
}

/* The Text size row (host/oot_text_size.c): a choice's scale of the text of dialogue, Navi and signs. 1, the game's own
   size, for 0 (Normal) and for anything outside the row. */
static inline float oot_text_size_scale(int v) {
    static const float k[] = {1.0f, 1.10f, 1.25f, 1.50f, 1.75f};
    return v > 0 && v < (int)(sizeof k / sizeof k[0]) ? k[v] : 1.0f;
}

/* A field of the game's the Text size row scales (one of a text pane's two scales): where it is, the game's own value,
   the value written there last, and when it was last stepped. */
typedef struct {
    uint64_t addr;
    uint32_t game, written, seen;
} OotTextField;

/* The bits a field gets at scale s, where it holds now: the game's own value times s. A field that no longer holds what
   was written last was written by the game since, and that is its own value from then on. At a scale of 1 the answer is
   the game's own value, bit for bit. */
static inline uint32_t oot_text_size_value(OotTextField *f, uint32_t now, float s) {
    if (now != f->written) f->game = now;
    if (s == 1.0f) return f->written = f->game;
    float g, v;
    memcpy(&g, &f->game, 4);
    v = g * s;
    memcpy(&f->written, &v, 4);
    return f->written;
}

/* The Damage taken row (host/oot_damage.c): Link's life after a hit, in quarter hearts. old is his life before the hit,
   next what the game makes of it (the whole hit off, never below 0), hit the whole hit. The game's own next at Normal, for
   a value outside the row, for a write that takes nothing off (healing is never scaled) and for a hit of nothing. Half
   rounds the hit up, so that a hit of one quarter still takes one; Double and Quadruple never take life below 0. */
enum { OOT_DAMAGE_HALF, OOT_DAMAGE_NORMAL, OOT_DAMAGE_DOUBLE, OOT_DAMAGE_QUADRUPLE };
static inline uint32_t oot_damage_life(uint32_t old, uint32_t next, uint32_t hit, int setting) {
    if (next >= old || !hit) return next;
    uint64_t damage = hit;   /* (wide before it is multiplied: a deadly hit does not wrap) */
    switch (setting) {
    case OOT_DAMAGE_HALF: damage = (damage + 1) / 2; break;
    case OOT_DAMAGE_DOUBLE: damage *= 2; break;
    case OOT_DAMAGE_QUADRUPLE: damage *= 4; break;
    default: return next;
    }
    return damage >= old ? 0 : old - (uint32_t)damage;
}

/* The Autosave row (host/oot_autosave.c): whether a save request, at the head of the game's function that queues one
   (f_80bc72d0: x1 the reason, x2 the mode), is one of the autosaves of going from one area to another. Those come through
   the wrapper f_80bc7730 (the request's return address 0x80bc7764), in mode 0, from three places, each with its reason:
   the transition's own (the wrapper called from 0x80bc7710, reason 6) and the two the arrival makes (from 0x80bc7864,
   reason 2; through f_832aa030, whose caller's return address is 0x832a9764, reason 1). caller: the request's return
   address; parent: the wrapper's. Every other request (the pause menu's Save among them) is none of these. */
static inline int oot_autosave_transition(uint64_t caller, uint64_t parent, uint32_t reason, uint32_t mode) {
    if (caller != 0x80bc7764ULL || mode != 0) return 0;
    return (parent == 0x80bc7710ULL && reason == 6) || (parent == 0x80bc7864ULL && reason == 2) ||
           (parent == 0x832a9764ULL && reason == 1);
}
