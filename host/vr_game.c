/* (Triforce VR) VR's side in the game (vr_game.h), Ocarina of Time 1.1.1, for the renderer's VR (gpu/vk/vk_xr.cpp, through
   its table: rx_xr).

   The camera update (f_804e48c0) chooses its position, target and up, then builds the look-at camera from them and, further
   on, the perspective projection from the camera's vertical angle. Its site where every path of that choice joins
   (0x804e4e50, nx2/oot_patches.py patch_vr) has them in d0-d2, d3-d5 and s7, s16, s6: for the gameplay camera the head's
   pose is put on them there (hos_vr_camera). The site after the angle's load (0x804e52f8, ldr s0, [x19, #0x13c]) puts the
   headset's lens in its place for the same camera (hos_vr_lens). Rendering and the game's culling both follow, as they read
   what the update made. While an event plays (a cutscene, a conversation) the events' camera follows the head instead, from
   where the event puts it. In first person Link faces where the head looks (turn_link) and strafes when moved sideways or
   back (vr_pad_read). The Debug tab's free camera, when on, has the camera to itself.

   Reads of the game's memory go through oot_game_data.h, which answers 0 for a page that is not committed; writes only into
   memory committed read-write (poke). */
#include "vr_game.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "../gpu/vk/oot_game_data.h"
#include "../gpu/vk/vk_api.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

const MkwVkXr *rx_xr(void);   /* (rx_backend.c) */
int rx_option(int id, int otherwise);

static const uint8_t *gw(void) { return (const uint8_t *)GP(0); }
static int rd(uint64_t a, void *out, size_t n) { return oot_data_rd(gw(), a, out, n); }
static uint64_t rd_ptr(uint64_t a) { return oot_data_ptr(gw(), a); }
static uint64_t now_ns(void) { return (uint64_t)hos_now_ns(); }

/* n bytes at a are committed read-write memory of the game's */
static int game_rw(uint64_t a, size_t n) {
    /* (the game's heap is committed read-write whole (host/hos_mem.c): no VirtualQuery there, which costs milliseconds a
       call in this address space (gpu/vk/oot_game_data.h oot_data_rd); first person's poke runs every frame) */
    if (a >= HOS_HEAP_BASE && a - HOS_HEAP_BASE < hos_heap_size && n <= hos_heap_size - (a - HOS_HEAP_BASE)) return 1;
    MEMORY_BASIC_INFORMATION mi;
    if (!a || a >= OOT_DATA_SPACE || n > OOT_DATA_SPACE - a || !VirtualQuery(GP(a), &mi, sizeof mi) || mi.State != MEM_COMMIT ||
        !(mi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE)) || (mi.Protect & PAGE_GUARD))
        return 0;
    return (const uint8_t *)GP(a) + n <= (const uint8_t *)mi.BaseAddress + mi.RegionSize;
}
static int poke(uint64_t a, const void *from, size_t n) {
    if (!game_rw(a, n)) return 0;
    memcpy(GP(a), from, n);
    HOS_WRITTEN(GP(a), n);
    return 1;
}

/* the renderer's VR, NULL without it; and a VR row's value (gpu/vk/vk_menu.cpp vk_xr_cfg) */
static const MkwVkXr *xr(void) { return rx_xr(); }
static const char *cfg_value(const char *key) {
    const MkwVkXr *x = xr();
    return x && x->cfg ? x->cfg(key) : "";
}
static int cfg_int(const char *key) { return atoi(cfg_value(key)); }
static int head_active(void) {
    const MkwVkXr *x = xr();
    return x && x->head_active();
}

static double reg_d(const Ctx *c, int r) {
    double v;
    memcpy(&v, &c->vreg[r][0], 8);
    return v;
}
static void set_d(Ctx *c, int r, double v) { memcpy(&c->vreg[r][0], &v, 8), c->vreg[r][1] = 0; }
static float reg_s(const Ctx *c, int r) {
    float v;
    memcpy(&v, &c->vreg[r][0], 4);
    return v;
}
static void set_s(Ctx *c, int r, float v) {
    c->vreg[r][0] = c->vreg[r][1] = 0;
    memcpy(&c->vreg[r][0], &v, 4);
}

/* Link: his actor, his feet and his rotation (nine floats, a 3x3 matrix by rows) beside them */
static uint64_t player(void) { return oot_data_player(gw()); }
static int player_pos(float xyz[3]) {
    const uint64_t a = player();
    return a && rd(a + 0x31c, xyz, 12) && isfinite(xyz[0]) && isfinite(xyz[1]) && isfinite(xyz[2]);
}
static int player_rot(float m[9]) {
    const uint64_t a = player();
    if (!a || !rd(a + 0x328, m, 36)) return 0;
    for (int i = 0; i < 9; i++)
        if (!isfinite(m[i])) return 0;
    return 1;
}

/* an event plays (a cutscene, a conversation): the event manager's singleton (main+0x4c7e090) holds the manager, whose +104
   is the event running, 0 when none. The event camera updates every frame whether one plays or not. */
static int oot_event_playing(void) {
    const uint64_t singleton = rd_ptr(OOT_DATA_MAIN + 0x4c7e090), events = singleton ? rd_ptr(singleton) : 0;
    return events && rd_ptr(events + 104) != 0;
}
/* Link's state's name (his component 107's name at +at: 0x244 his state, "Wait", "CrouchGuard"...; 0x34c his upper body's,
   "BowChargeUpper"...), "" when there is none */
static void oot_link_state_at(char out[48], uint32_t at) {
    out[0] = 0;
    const uint64_t actor = player(), components = actor ? rd_ptr(actor + 0x270) : 0;
    const uint64_t c107 = components ? rd_ptr(components + 107 * 8) : 0;
    if (!c107 || !rd(c107 + at, out, 47)) out[0] = 0;
    out[47] = 0;
}
static int oot_childhood(void) {
    int child = 1;
    oot_data_flag(gw(), "Sequence_IsChildhood", &child);
    return child;
}
/* the game paused by its own menus (its three pause steps' flags) */
static int oot_paused(void) {
    int p = 0, pre = 0, post = 0;
    oot_data_flag(gw(), "Sequence_IsPause", &p), oot_data_flag(gw(), "Sequence_IsPreGamePause", &pre);
    oot_data_flag(gw(), "Sequence_IsPostGamePause", &post);
    return p || pre || post;
}

static uint64_t head_camera;   /* x19 of the update the head's view was put on (0: none); the game's thread alone */


/* First person's hiding of Link: the game fades him out when its camera comes close, through two of his components'
   alphas (the components at actor +0x270; at their +0x260 an object of vtable main+0x4b4a5a0 with its alpha at +0x118, at
   +0x278 one of vtable main+0x4b4b4a8 with its alpha at +0x130). Below zero they stay hidden through the game's easing back
   toward 1, every frame; what he holds is drawn by other actors and stays. Written while first person is on. */
static void hide_link(uint64_t actor) {
    static const struct { uint32_t slot; uint64_t vtable; uint32_t field; } fades[] = {
        {0x260, OOT_DATA_MAIN + 0x4b4a5a0, 0x118}, {0x278, OOT_DATA_MAIN + 0x4b4b4a8, 0x130}};
    static const float hidden = -1.0f;
    const uint64_t components = rd_ptr(actor + 0x270);
    if (!game_rw(components, 0x280)) return;
    for (unsigned i = 0; i < 2; i++) {
        const uint64_t object = rd_ptr(components + fades[i].slot);
        if (!game_rw(object, fades[i].field + 4)) continue;
        if (rd_ptr(object) == fades[i].vtable) poke(object + fades[i].field, &hidden, sizeof hidden);
    }
}

/* First person (VR_CAMERA first): the camera at Link's eyes, from his feet, his facing and his age; the offsets VR_EYE_UP,
   _SIDE and _FORWARD (centimetres, -30..30) move it from the place found right in a Quest 3 (below). 0 while there is no Link. */
static int first_person_eye(double eye[3]) {
    if (strcmp(cfg_value("VR_CAMERA"), "first")) return 0;
    const uint64_t actor = player();
    float feet[3], m[9];
    if (!actor || !player_pos(feet) || !player_rot(m)) return 0;
    double fx = m[2], fz = m[8], n = sqrt(fx * fx + fz * fz);   /* his facing: the rotation's third column, level */
    if (!(n > 1e-4)) return 0;
    fx /= n, fz /= n;
    /* (the eyes at his own head, with his arms shown or not: adult 1.73 m and 6 cm ahead of his feet, found right in a
       Quest 3 against his body with only his head hidden (the earlier 1.45 m and 18 cm sat 28 cm low and 12 cm ahead of
       it; hidden's 1.80 m and 8 cm was a guess with his model in the way); young Link scaled alike, 1.19 m and 4 cm) */
    const int child = oot_childhood();
    const double up = (child ? 1.19 : 1.73) + cfg_int("VR_EYE_UP") / 100.0;
    const double ahead = (child ? 0.04 : 0.06) + cfg_int("VR_EYE_FORWARD") / 100.0, side = cfg_int("VR_EYE_SIDE") / 100.0;
    eye[0] = feet[0] + ahead * fx - side * fz;   /* his right: (-fz, 0, fx) */
    eye[1] = feet[1] + up;
    eye[2] = feet[2] + ahead * fz + side * fx;
    /* (VR_BODY arms: he stays drawn, his arms on the controllers and his head hidden by vr_body.c; hidden: all of him) */
    if (strcmp(cfg_value("VR_BODY"), "arms")) hide_link(actor);
    return 1;
}

static volatile uint64_t fp_eye_at;   /* when first person's eyes were last put on the gameplay camera */
static SRWLOCK anchor_lock = SRWLOCK_INIT;
static double anchor_feet[3];       /* Link's feet at the gameplay camera's last update with the head's view (anchor_lock) */
static uint64_t anchor_at;
int vr_first_person_now(void) { return now_ns() - fp_eye_at < 200000000ull; }
int vr_play_anchor(double feet[3]) {
    AcquireSRWLockShared(&anchor_lock);
    const int ok = anchor_at && now_ns() - anchor_at < 200000000ull;
    if (ok) memcpy(feet, anchor_feet, sizeof anchor_feet);
    ReleaseSRWLockShared(&anchor_lock);
    return ok;
}

static volatile uint64_t fp_at;     /* when Link was last turned to the head in first person */
static volatile uint64_t play_at;   /* when the gameplay camera last updated outside an event */
static volatile int hooks_on;       /* the camera hook has run with a session: play_at is kept */


/* Link aims a ranged item: his upper body in the bow's (the slingshot's too) or the hookshot's states */
static int link_aims(void) {
    char upper[48];
    oot_link_state_at(upper, 0x34c);
    return !strncmp(upper, "Bow", 3) || !strncmp(upper, "Hookshot", 8);
}


static int g_aiming;           /* hand_item: Link aims or holds a ranged item ready now (the bow, slingshot, hookshot, boomerang) */
static uint64_t zr_at, y_at;   /* the item button's (ZR) and the sword's (Y) last presses, vr_pad_read */

/* Whether Link holds something out, and the item in his hand as VR's hands draw it (a model of the game's files), "" for
   the sword. His state's names (all of component 107's, one after another) tell it: a weapon or item out (CommonUpper,
   WeaponEquipOnUpper), aiming or throwing (the bow's and slingshot's Bow...Upper, the hookshot's and boomerang's HoldItem,
   Hookshot..., FaceBattleBoomerang), a bottle's use, a swing; out until half a second without, or at once when he puts it
   away (WeaponEquipOff). The item button with a hand item on it puts that item in his hand, the sword's button followed by a
   sword's attack the sword again; aiming puts the item aimed. A bottle's model shows what it holds now (its BottleItem enum). */
static int hand_item(char out[96]) {
    out[0] = 0;
    char names[512] = " ";
    const uint64_t actor = player(), components = actor ? rd_ptr(actor + 0x270) : 0;
    const uint64_t c107 = components ? rd_ptr(components + 107 * 8) : 0;
    char b[0x300];
    if (c107 && rd(c107 + 0x200, b, sizeof b)) {   /* all of component 107's names, one after another */
        size_t len = 1;
        for (int o = 0; o < 0x300; o++) {
            if (b[o] < 'A' || b[o] > 'Z' || (o && b[o - 1])) continue;
            int n = 0;
            while (o + n < 0x300 && b[o + n] > 32 && b[o + n] < 127) n++;
            if (n >= 4 && o + n < 0x300 && !b[o + n] && len + n + 2 < sizeof names)
                memcpy(names + len, b + o, n), len += n, names[len++] = ' ', names[len] = 0;
        }
    }
    const int child = oot_childhood();
    uint32_t item = 0;
    oot_data_enum(gw(), child ? "PlayerStatus.AssignableItem.Child" : "PlayerStatus.AssignableItem.Adult", &item);
    /* the hand items by their AssignableItem value; a bottle 'A'..'E' by its slot */
    static const struct { const char *value, *model; } items[] = {
        {"SlingShot", "Weapon_Range_SlingShot"}, {"Bow", "Weapon_Range_Bow"}, {"Hookshot", "Item_Hookshot.Item_Hookshot_Body"},
        {"Longshot", "Item_Hookshot.Item_Hookshot_Body"}, {"Boomerang", "Item_Boomerang"}, {"Hammer", "Item_Hammer"},
        {"DekuStick", "Item_DekuStick"}, {"BottleA", "A"}, {"BottleB", "B"}, {"BottleC", "C"}, {"BottleD", "D"},
        {"BottleE", "E"}};
    const char *now_item = NULL;
    for (size_t i = 0; i < sizeof items / sizeof *items && !now_item; i++)
        if (item == oot_data_hash(items[i].value)) now_item = items[i].model;
    static const char *held;   /* what the last button put in his hand (NULL the sword) */
    static uint64_t seen_zr, seen_y;
    if (zr_at != seen_zr) {
        seen_zr = zr_at;
        if (now_item) held = now_item;
    } else if (now_item && held && held != now_item && now_ns() - zr_at < 500000000ull) {
        held = now_item;   /* (an item set just before the press is equipped a few reads after it) */
    }
    /* the sword's button takes the sword back (as the game does); with a bottle out only when a sword's attack follows (the
       game ignores the button then); the hammer's own swing puts the hammer back */
    const uint64_t t0 = now_ns();
    if (y_at != seen_y && y_at < zr_at) seen_y = y_at;   /* (the item's button after it: the item's) */
    if (y_at != seen_y && t0 - zr_at > 400000000ull) {
        const int bottle = held && !held[1];
        if (!bottle) seen_y = y_at, held = NULL;
        else if (t0 - y_at < 400000000ull && (strstr(names, " Cut") || strstr(names, " Charge")) && !strstr(names, "Hammer"))
            seen_y = y_at, held = NULL;
    }
    {   /* an area entered (a new Link): everything put away */
        static uint64_t was;
        if (actor != was) was = actor, held = NULL;
    }
    if (strstr(names, "Hammer") && now_item && !strcmp(now_item, "Item_Hammer")) held = now_item;
    const int aiming = (strstr(names, " BowReLoadUpper ") || strstr(names, " BowChargeUpper ") ||
                        strstr(names, " BowShootUpper ") || strstr(names, " HoldItem") || strstr(names, " Hookshot") ||
                        strstr(names, " FaceBattleBoomerang ")) && now_item;
    if (aiming) held = now_item;
    g_aiming = aiming;
    static uint64_t out_at;
    const uint64_t t = now_ns();
    if (aiming || strstr(names, " CommonUpper ") || strstr(names, " WeaponEquipOnUpper ") || strstr(names, "Bottle") ||
        strstr(names, "Drink") || strstr(names, " Cut") || strstr(names, " DemoShield") || strstr(names, "Hammer"))
        out_at = t;
    /* put away: when he puts it away; otherwise what was brought out last stays his (no timer: an item held still shows
       none of those names, and a swing taken as the sword's would swap it for the sword) */
    const int away = strstr(names, " WeaponEquipOff") != NULL;
    if (away) held = NULL;
    if (away || t - out_at > 500000000ull) return 0;
    if (!held) return 1;
    if (held[1]) {
        snprintf(out, 96, "%s", held);
        return 1;
    }
    static const struct { const char *value, *model; } bottles[] = {
        {"RedPotion", "Item_Bottle_RedPotion"}, {"Fish", "Item_Bottle_Fish"}, {"Letter", "Item_Bottle_Letter"},
        {"BigPoe", "Item_Bottle_Poe"}, {"Poe", "Item_Bottle_Poe"}, {"Bug", "Item_Bottle_Bug"},
        {"Fairy", "Item_Bottle_Fairy"}, {"MaxMilk", "Item_Bottle_Milk"}, {"HalfMilk", "Item_Bottle_HalfMilk"}};
    char key[96];
    uint32_t what = 0;
    snprintf(key, sizeof key, "PlayerStatus.AssignableItem.BottleInfo.Bottle%c.BottleItem", held[0]);
    oot_data_enum(gw(), key, &what);
    snprintf(out, 96, "Item_Bottle");   /* empty, or what has no model of its own (the potions' other colours, fire) */
    for (size_t i = 0; i < sizeof bottles / sizeof *bottles; i++)
        if (what == oot_data_hash(bottles[i].value)) snprintf(out, 96, "%s", bottles[i].model);
    return 1;
}


/* The game's thread at each pad read: whether Link plays the ocarina (a DemoOcarina state, a lesson's too), what he holds,
   and whether the game is in play (the gameplay camera updated a moment ago, not the title, a load or an event; Link there and
   not in one of his scripted Demo states; the game not paused by its menus), for the controllers' play roles */
static void vr_tick(Ctx *c, const MkwVkXr *x) {
    (void)c;
    char state[48];
    oot_link_state_at(state, 0x244);
    x->ocarina(!strncmp(state, "DemoOcarina", 11));   /* playing the ocarina (a lesson's too) */
    {   /* what he holds out, for the controllers' gestures */
        char item[96];
        x->child(oot_childhood());
        x->weapon_out(hand_item(item));
        x->hand_item(item);
    }
    const int camera = !hooks_on || now_ns() - play_at < 200000000ull;   /* (without the hooks: Link's state alone) */
    const int play = camera && !oot_event_playing() && state[0] && strncmp(state, "Demo", 4);
    x->in_play(play && !oot_paused());
}

/* In first person play, while the left stick is pushed sideways or back the game gets ZL held, so Link strafes as Z-targeting
   does, facing the way he faced (the head's, from running forward or standing). Pushed forward (within 45 degrees) he runs
   where the head looks, unless the head is within VR_RUN_ZONE degrees of its rest (the game's own camera's way, which the
   head turns from): then straight that way, so a head held about forward never steers him. The stick is turned so the game,
   which moves him relative to the head's view, runs him so, and turn_link faces him that way. The player's own ZL is kept. */
static double head_s, head_c = 1;   /* the head's view's level direction (sin, cos of its yaw), from the last camera update */
static double base_s, base_c = 1;   /* the game's own camera's, before the head turned it */
static double run_s, run_c = 1;     /* the way a run straight ahead takes */
static uint64_t run_at;             /* when the stick last ran him straight ahead */

static void vr_pad(uint64_t *buttons, int32_t *lx, int32_t *ly) {
    {   /* the item button's and the sword's presses, for the item in hand (hand_item) */
        static int zr_was, y_was;
        const int zr = (int)(*buttons >> HOS_SW_ZR & 1), y = (int)(*buttons >> HOS_SW_Y & 1);
        if (zr && !zr_was) zr_at = now_ns();
        if (y && !y_was) y_at = now_ns();
        zr_was = zr, y_was = y;
    }
    if (now_ns() - fp_at > 200000000ull) return;
    const int64_t m2 = (int64_t)*lx * *lx + (int64_t)*ly * *ly;
    if (m2 < (int64_t)8000 * 8000) return;
    if (!(*ly > 0 && 2 * (int64_t)*ly * *ly >= m2)) {
        *buttons |= 1ULL << HOS_SW_ZL;
        return;
    }
    const double zone = cfg_int("VR_RUN_ZONE") * M_PI / 180.0;
    const double off = atan2(head_s * base_c - head_c * base_s, head_c * base_c + head_s * base_s);
    if (!(fabs(off) < zone)) return;
    /* the stick's way from the rest's forward (s, c) and right (-c, s), then given relative to the head's */
    const double wx = base_s * *ly - base_c * *lx, wz = base_c * *ly + base_s * *lx;
    const double f = wx * head_s + wz * head_c, r = -wx * head_c + wz * head_s;
    *ly = (int32_t)fmax(-32767, fmin(32767, f));
    *lx = (int32_t)fmax(-32767, fmin(32767, r));
    const double n = sqrt(wx * wx + wz * wz);
    run_s = wx / n, run_c = wz / n, run_at = now_ns();
}

void vr_pad_read(Ctx *c, uint64_t *buttons, int32_t stick[4]) {
    const MkwVkXr *x = xr();
    /* (no session, VR off or no headset: nothing of VR's here, which runs on every pad read the game makes) */
    if (!x || !x->active || !x->active()) return;
    if (!rx_option(1, 0)) x->pad(buttons, stick, stick + 2);   /* the hand controllers, as the pad (the Insert menu's own while it is open) */
    if (!rx_option(1, 0)) vr_pad(buttons, &stick[0], &stick[1]);   /* (not while the Insert menu is open) */
    /* (the game reads the pad several times a frame, on its workers: what vr_tick tells VR changes at most once a frame,
       so it runs once in 4 ms, whichever reader comes first) */
    static uint64_t tick_at;
    const uint64_t now = now_ns();
    uint64_t was = __atomic_load_n(&tick_at, __ATOMIC_RELAXED);
    if (now - was >= 4000000ull && __atomic_compare_exchange_n(&tick_at, &was, now, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED))
        vr_tick(c, x);
}

static void turn_link(const double ahead[3]) {
    const uint64_t actor = player();
    if (!actor || strcmp(cfg_value("VR_CAMERA"), "first")) return;
    const double n = sqrt(ahead[0] * ahead[0] + ahead[2] * ahead[2]);
    if (!(n > 1e-4)) return;
    head_s = ahead[0] / n, head_c = ahead[2] / n;
    const int straight = now_ns() - run_at < 100000000ull;   /* running straight ahead: that way */
    const float s = (float)(straight ? run_s : head_s), co = (float)(straight ? run_c : head_c);
    /* his facing as the game keeps it, from which his rotation, his physics and the rest are made each frame: the object
       component 0 points at (+0x60), its 3x4 matrix by rows at +0x1f8 (the position in each row's fourth float) */
    const uint64_t components = rd_ptr(actor + 0x270), c0 = components ? rd_ptr(components) : 0;
    const uint64_t facing = c0 ? rd_ptr(c0 + 0x60) : 0;
    float t[12];
    if (!game_rw(facing, 0x1f8 + sizeof t)) return;
    rd(facing + 0x1f8, t, sizeof t);
    if (fabsf(t[5] - 1.0f) > 0.01f) return;   /* not upright now */
    const float r[12] = {co, 0, s, t[3], 0, 1, 0, t[7], -s, 0, co, t[11]};
    poke(facing + 0x1f8, r, sizeof r);
    fp_at = now_ns();
}

/* Play style Motion: while Link aims (g_aiming), the game's aim (its camera's ray, d) steered onto where the sword hand's
   controller points, through the game's own motion aiming: its six-axis sensor (vr_motion_history) is given turn rates
   proportional to the yaw and pitch between the two, every camera update, so the aim follows the controller wherever it
   points and does not drift; the right stick still adds to it. The view's base yaw is held meanwhile (aim_freeze), else it
   would turn with the aim it chases. The sensor's axes that turn the aim's pitch and yaw: x and z (VR_GYRO=x+z+, a sign or
   an axis changed for a test). */
static SRWLOCK motion_lock = SRWLOCK_INIT;
static HosMotionSample motion_hist[HOS_MOTION_HISTORY];
static int motion_head, motion_count;
static int64_t motion_n, motion_last_ns;
static double motion_r[3][3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};   /* the controller's orientation: lying face up at the start */
static float motion_angle[3];

static double wrap_pi(double a) {
    while (a > M_PI) a -= 2 * M_PI;
    while (a < -M_PI) a += 2 * M_PI;
    return a;
}
/* one reading: rates in radians a second about the controller's own axes (the Switch's frame), lying face up */
static void motion_feed(const double gyro[3]) {
    const int64_t now = hos_now_ns();
    AcquireSRWLockExclusive(&motion_lock);
    double dt = motion_last_ns && now > motion_last_ns ? (now - motion_last_ns) / 1e9 : 0.005;
    if (dt > 0.05) {   /* a new aim: from rest */
        dt = 0.005, memset(motion_angle, 0, sizeof motion_angle);
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++) motion_r[i][j] = i == j;
    }
    motion_last_ns = now;
    {   /* R = R * exp(w dt) (the body frame), kept orthonormal */
        const double a[3] = {gyro[0] * dt, gyro[1] * dt, gyro[2] * dt};
        const double k[3][3] = {{1, -a[2], a[1]}, {a[2], 1, -a[0]}, {-a[1], a[0], 1}};
        double m[3][3];
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++) m[i][j] = motion_r[i][0] * k[0][j] + motion_r[i][1] * k[1][j] + motion_r[i][2] * k[2][j];
        for (int j = 0; j < 3; j++) {   /* (Gram-Schmidt on the columns) */
            for (int p = 0; p < j; p++) {
                const double d = m[0][j] * m[0][p] + m[1][j] * m[1][p] + m[2][j] * m[2][p];
                for (int i = 0; i < 3; i++) m[i][j] -= d * m[i][p];
            }
            const double l = sqrt(m[0][j] * m[0][j] + m[1][j] * m[1][j] + m[2][j] * m[2][j]);
            for (int i = 0; i < 3; i++) m[i][j] /= l;
        }
        memcpy(motion_r, m, sizeof m);
    }
    HosMotionSample s;
    memset(&s, 0, sizeof s);
    s.st.accel[2] = -1;
    for (int i = 0; i < 3; i++) {
        const float turns = (float)(gyro[i] / (2 * M_PI));
        motion_angle[i] += turns * (float)dt;
        s.st.gyro[i] = turns, s.st.rotation[i] = motion_angle[i];
        for (int j = 0; j < 3; j++) s.st.direction[i * 3 + j] = (float)motion_r[j][i];   /* (row i: the controller's axis i) */
    }
    s.n = ++motion_n, s.dt_ns = (int64_t)(dt * 1e9);
    motion_head = (motion_head + 1) % HOS_MOTION_HISTORY;
    motion_hist[motion_head] = s;
    if (motion_count < HOS_MOTION_HISTORY) motion_count++;
    ReleaseSRWLockExclusive(&motion_lock);
}
int vr_motion_history(HosMotionSample *out, int max) {
    AcquireSRWLockShared(&motion_lock);
    const int live = motion_last_ns && hos_now_ns() - motion_last_ns < 100000000LL;
    const int n = !live ? 0 : motion_count < max ? motion_count : max;
    for (int i = 0; i < n; i++) out[i] = motion_hist[(motion_head - i + HOS_MOTION_HISTORY) % HOS_MOTION_HISTORY];
    ReleaseSRWLockShared(&motion_lock);
    return n;
}

static void steer_aim(const MkwVkXr *x, const double d[3]) {
    const int pointed = d && g_aiming && !strcmp(cfg_value("VR_PLAY"), "motion") && !strcmp(cfg_value("VR_CONTROLS"), "meta") &&
                        x->head_active();
    x->aim_freeze(pointed);
    double t[3];
    if (!pointed || !x->pointer(t)) return;
    const double yaw_err = wrap_pi(atan2(t[0], t[2]) - atan2(d[0], d[2]));
    const double pitch_err = asin(fmax(-1, fmin(1, t[1]))) - asin(fmax(-1, fmin(1, d[1])));
    const char *spec = getenv("VR_GYRO");
    if (!spec || strlen(spec) < 4) spec = "x+z+";
    double gyro[3] = {0, 0, 0};
    const double k = 10.0, most = 8.0;
    const double rate[2] = {fmax(-most, fmin(most, k * pitch_err)), fmax(-most, fmin(most, k * yaw_err))};
    for (int i = 0; i < 2; i++) {
        const int axis = spec[2 * i] == 'x' ? 0 : spec[2 * i] == 'y' ? 1 : 2;
        gyro[axis] += spec[2 * i + 1] == '-' ? -rate[i] : rate[i];
    }
    motion_feed(gyro);
}

/* the camera's state (x19) has its actor at +0x10, the actor its name at +0x20: 1 the camera that follows Link, 2 the
   events' camera, 0 another (the interface's 3D models', the sound's) */
static int scene_camera(uint64_t state) {
    char name[16] = "";
    const uint64_t actor = rd_ptr(state + 0x10), np = actor ? rd_ptr(actor + 0x20) : 0;
    if (!np || !rd(np, name, 13)) return 0;
    return !memcmp(name, "PlayerCamera", 13) ? 1 : !memcmp(name, "EventCamera", 12) ? 2 : 0;
}

static volatile double step_seconds = -1;   /* (nn_vi.c realtime_step: the seconds the next update steps, -1 the game's own) */
extern volatile uint64_t hos_step_probe;   /* (nn_vi.c: the frame step's object, its game clock at +0xd58 in 1/60 s) */
/* the seconds this update stepped, from the game clock's move since the camera's last update: the step it really took
   (realtime_step runs on the presenting thread, and may already have given the next update's while this one runs); the
   step given last when the clock is not there or did not move */
static double update_seconds(void) {
    static double last;
    static int have;
    double clock;
    const uint64_t probe = hos_step_probe;
    if (!probe || !rd(probe + 0xd58, &clock, sizeof clock) || !isfinite(clock)) return have = 0, step_seconds;
    const double moved = clock - last;
    const int ok = have && moved > 0 && moved < 8;
    last = clock, have = 1;
    return ok ? moved / 60.0 : step_seconds;
}
void vr_update_step(double seconds) { step_seconds = seconds; }
int vr_holds_time(void) {
    const MkwVkXr *x = xr();
    return x && x->holds_time();
}

void hos_vr_camera(Ctx *c) {
    static const int up_reg[3] = {7, 16, 6};
    const MkwVkXr *x = xr();
    const int scene = x ? scene_camera(c->x[19]) : 0;
    if (scene != 1 && scene != 2) return;
    if (rx_option(HOS_OPT_CHEAT_CAMERA, 0)) return;   /* (the Debug tab's free camera has it) */
    hooks_on = 1;
    const int event = oot_event_playing();
    const int k = scene - 1;
    if (scene == 1) head_camera = 0;
    if (scene == 2 ? !event : event) return;   /* the camera that shows: Link's in play, the events' in an event */
    if (scene == 1) play_at = now_ns();
    double pos[3], at[3];
    float up[3];
    for (int i = 0; i < 3; i++) pos[i] = reg_d(c, i), at[i] = reg_d(c, 3 + i), up[i] = reg_s(c, up_reg[i]);
    /* the view put on last time handed back as it was (the game did not choose its camera again): the game's own from before
       it is used, so the head is never put on twice */
    static double in_pos[2][3], in_at[2][3], out_pos[2][3], out_at[2][3];
    static float in_up[2][3];
    static int have_out[2];
    static unsigned fed_back;
    if (have_out[k] && !memcmp(pos, out_pos[k], sizeof pos) && !memcmp(at, out_at[k], sizeof at)) {
        memcpy(pos, in_pos[k], sizeof pos), memcpy(at, in_at[k], sizeof at), memcpy(up, in_up[k], sizeof up);
        if (!fed_back++) hos_log("vr: the game's camera handed back the head's view: its own view from before used");
    }
    memcpy(in_pos[k], pos, sizeof pos), memcpy(in_at[k], at, sizeof at), memcpy(in_up[k], up, sizeof up);
    have_out[k] = 0;
    if (scene == 1) {   /* the game's own camera's level way: the head's rest, for a run straight ahead */
        const double fx = at[0] - pos[0], fz = at[2] - pos[2], n = sqrt(fx * fx + fz * fz);
        if (n > 1e-6) base_s = fx / n, base_c = fz / n;
    }
    if (scene == 1) {   /* aiming: the game's own camera's ray, where its shots go, for the head's view's reticle */
        const int aims = link_aims();
        double d[3] = {at[0] - pos[0], at[1] - pos[1], at[2] - pos[2]};
        const double l = sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
        if (l > 1e-6) d[0] /= l, d[1] /= l, d[2] /= l;
        x->aim(aims && l > 1e-6, pos, d);
        steer_aim(x, l > 1e-6 ? d : NULL);
    }
    double eye[3];
    int fp_eye = 0;
    if (scene == 1 && x->head_active() && first_person_eye(eye)) {   /* the game's camera's direction kept, from his eyes */
        for (int i = 0; i < 3; i++) at[i] += eye[i] - pos[i], pos[i] = eye[i];
        fp_eye = 1;
    }
    if (scene == 2) {   /* an event's camera raised by Link's height for his age, and VR_EVENT_UP cm more */
        const double lift = (oot_childhood() ? 1.27 : 1.80) + cfg_int("VR_EVENT_UP") / 100.0;
        pos[1] += lift, at[1] += lift;
    }
    x->update_step(step_seconds < 0 ? -1 : update_seconds());
    if (!x->camera(pos, at, up)) return;
    for (int i = 0; i < 3; i++) set_d(c, i, pos[i]), set_d(c, 3 + i, at[i]), set_s(c, up_reg[i], up[i]);
    memcpy(out_pos[k], pos, sizeof pos), memcpy(out_at[k], at, sizeof at), have_out[k] = 1;
    head_camera = c->x[19];
    if (scene != 1) return;   /* Link turns in play alone */
    {   /* (vr_body.c: where Link stood for this view, the hands' anchor; and first person's eyes on him) */
        float feet[3];
        if (player_pos(feet)) {
            AcquireSRWLockExclusive(&anchor_lock);
            for (int i = 0; i < 3; i++) anchor_feet[i] = feet[i];
            anchor_at = now_ns();
            ReleaseSRWLockExclusive(&anchor_lock);
        }
        if (fp_eye) fp_eye_at = now_ns();
    }
    const double ahead[3] = {at[0] - pos[0], at[1] - pos[1], at[2] - pos[2]};
    turn_link(ahead);
}

void hos_vr_lens(Ctx *c) {
    const MkwVkXr *x = xr();
    float headset;
    if (x && head_camera && c->x[19] == head_camera && x->lens(&headset) && isfinite(headset) && headset > 0.05f &&
        headset < 3.0f)
        set_s(c, 0, headset);
}
