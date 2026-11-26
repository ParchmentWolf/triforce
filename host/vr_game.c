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
static uint64_t player(void) {
    /* ((Triforce VR) the game's own pointer to him, else Link as vr_body.c found him: at a start from a file the pointer is
       filled only after its first event, which began third person) */
    const uint64_t a = oot_data_player(gw());
    return a ? a : vr_body_link();
}
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
static uint64_t oot_event(void) {
    const uint64_t singleton = rd_ptr(OOT_DATA_MAIN + 0x4c7e090), events = singleton ? rd_ptr(singleton) : 0;
    return events ? rd_ptr(events + 104) : 0;
}
static int oot_event_playing(void) { return oot_event() != 0; }
/* ((Triforce VR) the event's name, kept in the event at +0x14: "Dm_SY_BancChangeGo", "Npc_Hylia_Talon_Child_D_T"...) */
static void oot_event_name(uint64_t event, char out[64]) {
    out[0] = 0;
    if (!event || !rd(event + 0x14, out, 63)) out[0] = 0;
    out[63] = 0;
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

int vr_game_paused(void) { return oot_paused(); }
/* ((Triforce VR) Link moving sideways: sidehops and walking locked on (vr_body.c: his legs left as the animation makes them) */
static volatile int g_sidestep;
int vr_game_sidestep(void) { return g_sidestep; }
void hos_vr_screen(Ctx *c, int open) {
    if (!xr()) return;
    const uint64_t param = oot_data_ptr(gw(), c->x[0] + 32) & ~3ULL, text = param ? oot_data_ptr(gw(), param) : 0;
    char name[16] = "";
    if (!text || !oot_data_rd(gw(), text, name, sizeof name - 1)) return;
    name[sizeof name - 1] = 0;
    if (strncmp(name, "ShortCutBG_00", 13)) return;
    xr()->item_bar(open);
    hos_log("vr: the item bar %s", open ? "opened" : "closed");
}
static volatile int g_item_out;   /* (vr_tick: an item in his hand, not the sword) */
static char g_held[96];          /* (vr_tick: the item in his hand, its model's name; "" none) */
const char *vr_game_held(void) { return g_held; }
int vr_game_two_handed(void) {
    if (g_item_out) return 0;
    char weapon[64] = "";
    oot_data_text(gw(), "PlayerStatus.EquipWeapon", weapon);
    return strstr(weapon, "Biggoron") != NULL;
}

/* ---- ((Triforce VR) his head's item for the gestures: a mask or the Lens of Truth, worn by a flag of the game data beside
   PlayerStatus.EquipHeadArmor, which keeps the item while it is off (the game's own D-pad up sets and clears it). The flag set
   through the game's setter for a Bool (f_806a2b20: the manager, the value, the hash); another item put in the member through
   the game's setter for a struct's text member (f_80464840), and the pouch then takes the equipment again (f_80f401b0), as the
   game's own Equipment page does ---- */
#define WORN_HEAD 0xc27c80fbu
static int worn_head(void) {
    const uint64_t e = oot_data_entry(gw(), 0, 0x18, WORN_HEAD);
    uint8_t b = 0;
    return e && rd(e + 0x16, &b, 1) && (b & 1);
}
static void game_call(Ctx *c, uint64_t fn, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3) {
    A64Fn f = a64_lookup(fn);
    if (!f) return;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
    c->x[0] = a0, c->x[1] = a1, c->x[2] = a2, c->x[3] = a3;
    f(c);
    *c = saved;
}
static void worn_head_set(Ctx *c, int on) {
    const uint64_t mgr = oot_data_gdm(gw());
    if (mgr) game_call(c, 0x806a2b20ULL, mgr, (uint64_t)(on != 0), WORN_HEAD, 0);
}
static void head_item_set(Ctx *c, const char *value) {
    A64Fn set = a64_lookup(0x80464840ULL);
    const uint64_t mgr = oot_data_gdm(gw()), desc = oot_data_entry(gw(), 32, 0x20, oot_data_hash("PlayerStatus"));
    const size_t n = strlen(value) + 1;
    if (!set || !mgr || !desc || n > 64) return;
    const Ctx saved = *c;
    c->x[31] = (c->x[31] - 0x100) & ~0xfULL;
    const uint64_t handle = c->x[31] + 0x80, ptr = handle + 0x10, text = ptr + 0x10;
    recomp_store64(c, handle, desc), recomp_store64(c, handle + 8, 0);
    for (size_t i = 0; i < n; i++) recomp_store8(c, text + i, (uint8_t)value[i]);
    recomp_store64(c, ptr, text);
    c->x[0] = mgr, c->x[1] = ptr, c->x[2] = handle, c->x[3] = oot_data_hash("EquipHeadArmor");
    set(c);
    *c = saved;
}
/* an item got once (struct 0xade0ef78's Bool of its name): the Lens of Truth only once it is his */
static int got_once(const char *name) {
    const uint64_t desc = oot_data_entry(gw(), 32, 0x20, 0xade0ef78u), members = desc ? rd_ptr(desc + 8) : 0;
    uint32_t size = 0;
    if (!members || !rd(desc + 20, &size, 4) || !size) return 0;
    const uint32_t h = oot_data_hash(name);
    for (uint32_t k = 0, i = h % size; k < size; k++, i = (i + 1) % size) {
        uint32_t pair[2];
        if (!rd(members + (uint64_t)i * 8, pair, 8) || !pair[0]) return 0;
        if (pair[0] != h) continue;
        const uint64_t e = oot_data_entry(gw(), 0, 0x18, pair[1]);
        uint8_t b = 0;
        return e && rd(e + 0x16, &b, 1) && (b & 1);
    }
    return 0;
}
static int head_sync;   /* (pad reads left to wait for the manager to take the new item: then the pouch takes it) */
static char head_want[64];   /* (the item head_sync waits for) */
static char last_mask[64];   /* (the last mask in the member: dragged on again after the Lens of Truth took its place) */
static void head_take(Ctx *c, int request) {
    char now[64] = "";
    oot_data_text(gw(), "PlayerStatus.EquipHeadArmor", now);
    if (request == 3) worn_head_set(c, 0), hos_log("vr: head: off");
    else if (request == 1 && strstr(now, "Mask")) worn_head_set(c, 1), hos_log("vr: head: %s on", now);
    else if (request == 1 && last_mask[0]) {   /* (the Lens in its place: the last mask back) */
        head_item_set(c, last_mask), snprintf(head_want, sizeof head_want, "%s", last_mask), head_sync = 60;
        worn_head_set(c, 1), hos_log("vr: head: %s on (in place of the Lens of Truth)", last_mask);
    }
    else if (request == 2) {
        static const char lens[] = "Armor_GlassTruth";
        if (!got_once(lens)) {
            hos_log("vr: head: the Lens of Truth asked for, not his yet");
            return;
        }
        if (strcmp(now, lens)) head_item_set(c, lens), snprintf(head_want, sizeof head_want, "%s", lens), head_sync = 60;
        worn_head_set(c, 1), hos_log("vr: head: the Lens of Truth on%s", strcmp(now, lens) ? " (in place of the mask)" : "");
    }
}
static void head_sync_step(Ctx *c) {
    if (head_sync <= 0) return;
    char now[64] = "";
    oot_data_text(gw(), "PlayerStatus.EquipHeadArmor", now);
    if (!strcmp(now, head_want) || --head_sync == 0) {
        head_sync = 0;
        const uint64_t ps = rd_ptr(0x84c9e0d0ULL), pch = ps ? rd_ptr(ps) : 0;   /* (the pouch at [[main 0x84c9e0d0]]) */
        if (pch) game_call(c, 0x80f401b0ULL, pch, 0, 0, 0);
    }
}
/* ((Triforce VR) Link shows an item (a quest item: EvtShowItemSuccess, EvtShowItemFailure, and putting it back, EvtGet, in
   the ShowItem event) */
int vr_game_showing_item(void) {
    char state[48];
    oot_link_state_at(state, 0x244);
    if (!strncmp(state, "EvtShowItem", 11)) return 1;
    if (!strcmp(state, "EvtGet")) {
        char name[64];
        oot_event_name(oot_event(), name);
        return !strcmp(name, "ShowItem");
    }
    return 0;
}
int vr_game_childhood(void) { return oot_childhood(); }

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
static double base_s, base_c;   /* (below: the game's own camera's level way) */
static int first_person_eye(double eye[3]) {
    if (strcmp(cfg_value("VR_CAMERA"), "first")) return 0;
    const uint64_t actor = player();
    float feet[3], m[9];
    if (!actor || !player_pos(feet) || !player_rot(m)) return 0;
    double fx = m[2], fz = m[8], n = sqrt(fx * fx + fz * fz);   /* his facing: the rotation's third column, level */
    if (!(n > 1e-4)) fx = base_s, fz = base_c, n = 1;   /* ((Triforce VR) his rotation not set yet: the camera's level way */
    fx /= n, fz /= n;
    /* (the eyes on Link whatever the headset's own place (vk_xr_camera in_place): adult 1.43 m and 16 cm ahead of his feet, young
       Link 0.97 m and 12 cm, both found right in a Quest 3) */
    const int child = oot_childhood();
    double up = (child ? 0.97 : 1.43) + cfg_int("VR_EYE_UP") / 100.0;
    {   /* ((Triforce VR) crouched (a crawlspace too: Crouch, CrouchLockOnMove...): the eyes down by as much as his neck is
           below its height standing still, eased over about a tenth of a second) */
        static double stand = -1, drop, target;
        static int stand_child = -1;
        static uint64_t at;
        char state[48];
        oot_link_state_at(state, 0x244);
        const int crouch = !strncmp(state, "Crouch", 6);
        double neck;
        const int have = vr_body_neck_height(&neck);
        if (child != stand_child) stand = -1, stand_child = child;
        if (have && !strcmp(state, "Wait")) stand = stand < 0 ? neck : stand + 0.05 * (neck - stand);
        if (!crouch) target = 0;
        else if (have && stand > 0) target = fmax(0.0, stand - neck);
        const uint64_t t = now_ns();
        const double dt = at ? (t - at) / 1e9 : 0;
        at = t;
        drop += (target - drop) * (dt > 0 && dt < 0.5 ? 1.0 - exp(-dt / 0.1) : 1.0);
        up -= drop;
    }
    const double ahead = (child ? 0.12 : 0.16) + cfg_int("VR_EYE_FORWARD") / 100.0, side = cfg_int("VR_EYE_SIDE") / 100.0;
    eye[0] = feet[0] + ahead * fx - side * fz;   /* his right: (-fz, 0, fx) */
    eye[1] = feet[1] + up;
    eye[2] = feet[2] + ahead * fz + side * fx;
    /* (VR_BODY arms: he stays drawn, his arms on the controllers and his head hidden by vr_body.c; hidden: all of him) */
    if (strcmp(cfg_value("VR_BODY"), "arms") && !oot_paused()) hide_link(actor);   /* ((Triforce VR) whole in the menus) */
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


static volatile int g_ocarina;   /* (vr_tick: Link plays the ocarina) */
static volatile int g_held_boomerang;    /* (vr_tick: the boomerang in his hand) */
static volatile int g_held_hookshot;     /* (vr_tick: the hookshot or the longshot in his hand) */
static volatile int32_t stick_aim[2];       /* ((Triforce VR) steer_aim: the right stick that turns the aim onto the pointer */
static volatile uint64_t stick_aim_at;      /* (when it was made; used for 150 ms) */
static int g_aiming;           /* hand_item: Link aims or holds a ranged item ready now (the bow, slingshot, hookshot, boomerang) */
int vr_game_aiming(void) { return g_aiming; }
/* ((Triforce VR) nn_hid.c vibration_send: the game's rumble on a side (0 left, 1 right), 0 to 1, to the hand controllers */
void vr_rumble(int side, float strength) {
    const MkwVkXr *x = xr();
    if (!x || !x->rumble || !x->active || !x->active()) return;
    /* (as the gamepads have it, host/pad_sdl.c: the Controls tab's Rumble strength (option 9, percent, 0 Off) and Vibration
       curve, a power on the strength) */
    const int percent = rx_option(9, 100), curve = rx_option(HOS_OPT_RUMBLE_CURVE, 100);
    if (percent <= 0 || !(strength > 0.0f)) {
        x->rumble(side, 0.0f);
        return;
    }
    const double power = curve <= 0 || curve == 100 ? 1.0 : (curve < 20 ? 20 : curve > 150 ? 150 : curve) / 100.0;
    x->rumble(side, (float)fmin(1.0, pow(fmin(1.0, strength), power) * percent / 100.0));
}
/* ((Triforce VR) nn_hid.c: a VR session in focus, so the gamepad counts beside the hand controllers with the window behind */
int vr_session_on(void) {
    const MkwVkXr *x = xr();
    return x && x->active && x->active() && x->head_active && x->head_active();
}   /* ((Triforce VR) vr_body.c: the arms put on the controllers again before the mirror */
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
        {"BottleE", "E"}, {"Bomb", "Item_Bomb"}, {"Bombchu", "Item_Bombchu"}};
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
    g_ocarina = !strncmp(state, "DemoOcarina", 11);
    x->ocarina(g_ocarina);   /* playing the ocarina (a lesson's too) */
    {   /* what he holds out, for the controllers' gestures */
        char item[96] = "";
        x->child(oot_childhood());
        x->weapon_out(hand_item(item));
        x->hand_item(item);
        g_item_out = item[0] != 0;
        snprintf(g_held, sizeof g_held, "%s", item);
        if (x->two_handed_sword) x->two_handed_sword(vr_game_two_handed());
        if (x->game_paused) x->game_paused(oot_paused());   /* (no full-picture fade looked for in its menus: vk_xr.cpp) */   /* (the head tilt's Z-target: vk_xr.cpp) */
        g_held_boomerang = strstr(item, "Boomerang") != NULL;
        g_held_hookshot = strstr(item, "Hookshot") != NULL;
    }
    if (x->carrying) {   /* ((Triforce VR) something of the world's in his hands: from its lift (LiftReady, LiftUp) while his arms carry
                            it (CommonUpper among his states' names, an item's too: so only after a lift), through LiftThrow or LiftPut */
        static int carry, ending;   /* (ending: thrown or put down: over with that state, whatever his arms hold next) */
        static uint64_t arms_at;
        int arms = 0;
        char b[0x300];
        const uint64_t actor = player(), comps = actor ? rd_ptr(actor + 0x270) : 0, c107 = comps ? rd_ptr(comps + 107 * 8) : 0;
        if (c107 && rd(c107 + 0x200, b, sizeof b))
            for (int o = 0; o + 12 <= (int)sizeof b && !arms; o++) arms = !memcmp(b + o, "CommonUpper", 12);
        if (arms) arms_at = now_ns();
        if (!strcmp(state, "LiftReady") || !strcmp(state, "LiftUp") || (carry && !strncmp(state, "Lift", 4)))   /* (a pulled bomb's throw is LiftThrow too) */
            carry = 1, arms_at = now_ns(), ending = !strcmp(state, "LiftThrow") || !strcmp(state, "LiftPut") || !strcmp(state, "LiftStand");
        else if (ending || now_ns() - arms_at > 300000000ull) carry = ending = 0;
        x->carrying(carry);
    }
    if (x->head_worn) {   /* his head's item and whether it is worn: the mask's and the Lens of Truth's gestures */
        char head[64] = "";
        oot_data_text(gw(), "PlayerStatus.EquipHeadArmor", head);
        if (strstr(head, "Mask")) snprintf(last_mask, sizeof last_mask, "%s", head);
        x->head_worn((strstr(head, "Mask") ? 1 : strstr(head, "GlassTruth") ? 2 : 0) | (worn_head() ? 4 : 0) | (last_mask[0] ? 8 : 0));
    }
    head_sync_step(c);
    if (x->head_request) {
        const int request = x->head_request();
        if (request) head_take(c, request);
    }
    const int camera = !hooks_on || now_ns() - play_at < 200000000ull;   /* (without the hooks: Link's state alone) */
    /* ((Triforce VR) aiming counts as play whatever camera the aim has: the hookshot's trigger is its aim, not an item bar) */
    const int play = (camera || link_aims()) && !oot_event_playing() && state[0] && strncmp(state, "Demo", 4);
    x->in_play(play && !oot_paused());
}

/* First person play: the left stick runs Link the way it points (forward, back or sideways) from the head's view, with no ZL.
   turn_link faces him that way. */
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
    /* the stick's way from the head's forward (head_s, head_c) and right (-head_c, head_s) */
    const double wx = head_s * *ly - head_c * *lx, wz = head_c * *ly + head_s * *lx;
    const double n = sqrt(wx * wx + wz * wz);
    run_s = wx / n, run_c = wz / n, run_at = now_ns();
}

static double wrap_pi(double a);
static double turn_w;      /* the view's yaw while the right stick has turned it: atan2(x, z) of its level forward */
static int turn_on;
static uint64_t turn_t;

static void vr_turn(int32_t *rx) {
    const uint64_t now = now_ns();
    const double dt = turn_t && now - turn_t < 100000000ull ? (now - turn_t) / 1e9 : 0;
    turn_t = now;
    if (now - fp_at > 1000000000ull || g_aiming) {
        turn_on = 0;
        return;
    }
    if (!turn_on) turn_w = atan2(base_s, base_c), turn_on = 1;
    if (!strcmp(cfg_value("VR_TURN"), "snap")) {   /* ((Triforce VR) Snap: one turn a push, again once the stick is back near the middle */
        static int armed = 1;
        const int push = abs(*rx);
        if (push < 9000) armed = 1;
        else if (armed && push > 22000) {
            const double a = cfg_int("VR_SNAP_ANGLE") * M_PI / 180.0;
            turn_w = wrap_pi(turn_w - (*rx > 0 ? a : -a)), armed = 0;
            const MkwVkXr *x = xr();
            if (x && x->turning) x->turning(1.0f);   /* (the Comfort vignette: a pulse at each snap) */
        }
        *rx = 0;
        return;
    }
    {   /* ((Triforce VR) Smooth: how hard the stick turns, for the Turn vignette (vk_xr.cpp) */
        const MkwVkXr *x = xr();
        if (x && x->turning) x->turning(abs(*rx) < 1000 ? 0.0f : (float)abs(*rx) / 32767.0f);
    }
    if (abs(*rx) < 1000) return;
    const double deg_per_second = 150.0 * cfg_int("VR_TURN_SPEED") / 10.0;   /* ((Triforce VR) Turn Speed, tenths */
    turn_w = wrap_pi(turn_w - *rx / 32767.0 * deg_per_second * M_PI / 180.0 * dt);
    *rx = 0;
}

/* ((Triforce VR) Immersive: the right stick's up and down are a zoom toward Link, not the game's camera swinging above and below
   him (far above or below him in a headset, seeing what it should not): the camera's distance from what it looks at, at least
   kZoomLeast and at most kZoomMost times the game's own (beyond the game's own nothing keeps it out of walls). Pushed up nearer,
   down farther, kZoomRate a second times Zoom Speed */
static volatile double zoom_d = 0, zoom_game = 0;   /* (the zoom's distance, 0 the game's own until the stick moves it; the game's own last) */
static const double kZoomLeast = 0.8, kZoomMost = 2.0, kZoomRate = 1.2;
static void immersive_zoom(int32_t *ry) {
    static uint64_t at;
    const uint64_t now = now_ns();
    const double dt = at && now - at < 100000000ull ? (now - at) / 1e9 : 0.0;
    at = now;
    const double push = abs(*ry) < 3000 ? 0.0 : *ry / 32767.0;
    *ry = 0;
    if (push == 0.0 || !(zoom_game > 0.0)) return;
    double d = zoom_d > 0.0 ? fmin(zoom_d, zoom_game * kZoomMost) : zoom_game;
    d *= exp(-push * kZoomRate * (cfg_int("VR_ZOOM_SPEED") / 10.0) * dt);
    zoom_d = fmax(kZoomLeast, d);
}
void vr_pad_read(Ctx *c, uint64_t *buttons, int32_t stick[4]) {
    const MkwVkXr *x = xr();
    /* (no session, VR off or no headset: nothing of VR's here, which runs on every pad read the game makes) */
    if (!x || !x->active || !x->active()) return;
    if (!rx_option(1, 0)) x->pad(buttons, stick, stick + 2);   /* the hand controllers, as the pad (the Insert menu's own while it is open) */
    if (!rx_option(1, 0)) vr_pad(buttons, &stick[0], &stick[1]), vr_turn(&stick[2]);   /* (not while the Insert menu is open) */
    if (!rx_option(1, 0) && now_ns() - __atomic_load_n(&stick_aim_at, __ATOMIC_ACQUIRE) < 150000000ull)
        stick[2] = stick_aim[0], stick[3] = stick_aim[1];   /* ((Triforce VR) the pointed aim's stick: steer_aim */
    /* ((Triforce VR) Immersive: the right stick moves the view around Link the way it is pushed, as on a rail (the game's
       camera turns the other way, which on a flat screen reads right); Invert camera orbit keeps the game's */
    const int immersive = !rx_option(1, 0) && !g_aiming && !strcmp(cfg_value("VR_VIEW"), "head") && !strcmp(cfg_value("VR_CAMERA"), "third");
    if (immersive && !atoi(cfg_value("VR_ORBIT_INVERT"))) stick[2] = stick[2] == INT32_MIN ? INT32_MAX : -stick[2];
    if (immersive) {   /* (Turn Speed, tenths: the orbit's push scaled, the stick's range kept) */
        const double v = stick[2] * (cfg_int("VR_TURN_SPEED") / 10.0);
        stick[2] = (int32_t)fmax(-32767.0, fmin(32767.0, v));
    }
    if (immersive && !g_ocarina && !oot_paused()) immersive_zoom(&stick[3]);   /* (the notes and the menus keep the stick) */
    /* (the game reads the pad several times a frame, on its workers: what vr_tick tells VR changes at most once a frame,
       so it runs once in 4 ms, whichever reader comes first) */
    static uint64_t tick_at;
    const uint64_t now = now_ns();
    uint64_t was = __atomic_load_n(&tick_at, __ATOMIC_RELAXED);
    if (now - was >= 4000000ull && __atomic_compare_exchange_n(&tick_at, &was, now, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED))
        vr_tick(c, x);
}

/* his facing as the game keeps it, from which his rotation, his physics and the rest are made each frame: the object
   component 0 points at (+0x60), its 3x4 matrix by rows at +0x1f8 (the position in each row's fourth float); s, co the
   sine and cosine of the way he faces. 0 when he is not upright now */
static int face_link(uint64_t actor, float s, float co) {
    const uint64_t components = rd_ptr(actor + 0x270), c0 = components ? rd_ptr(components) : 0;
    const uint64_t facing = c0 ? rd_ptr(c0 + 0x60) : 0;
    float t[12];
    if (!game_rw(facing, 0x1f8 + sizeof t)) return 0;
    rd(facing + 0x1f8, t, sizeof t);
    if (fabsf(t[5] - 1.0f) > 0.01f) return 0;   /* not upright now */
    const float r[12] = {co, 0, s, t[3], 0, 1, 0, t[7], -s, 0, co, t[11]};
    return poke(facing + 0x1f8, r, sizeof r);
}
static void turn_link(const double ahead[3]) {
    const uint64_t actor = player();
    if (!actor || strcmp(cfg_value("VR_CAMERA"), "first")) return;
    const double n = sqrt(ahead[0] * ahead[0] + ahead[2] * ahead[2]);
    if (!(n > 1e-4)) return;
    head_s = ahead[0] / n, head_c = ahead[2] / n;
    const int straight = now_ns() - run_at < 100000000ull;   /* running straight ahead: that way */
    const float s = (float)(straight ? run_s : head_s), co = (float)(straight ? run_c : head_c);
    if (!face_link(actor, s, co)) return;
    fp_at = now_ns();
}

static double wrap_pi(double a) {
    while (a > M_PI) a -= 2 * M_PI;
    while (a < -M_PI) a += 2 * M_PI;
    return a;
}

/* ((Triforce VR) the aim set where the pointer is, in the gameplay camera's state (x19) while Link aims: the angles it turns
   toward (+0xa384, and again at +0xa38c) and its own (+0x1178), in degrees, the way's height's asin held to the game's -85
   to 70. The yaw beside them (+0xa388, +0x117c) is made again each update, and in third person turns the camera itself.
   1 when it is set */
static int set_aim(uint64_t state, const double t[3]) {
    /* (the game's pitch is down positive: the height's asin taken the other way) */
    const double pitch = fmax(-85.0, fmin(70.0, -asin(fmax(-1, fmin(1, t[1]))) * 180 / M_PI));
    /* (the pitch alone: the yaw written there turns the camera itself in third person, not the aim) */
    const float target = (float)pitch;
    if (!state || !poke(state + 0xa384, &target, 4) || !poke(state + 0xa38c, &target, 4) || !poke(state + 0x1178, &target, 4)) return 0;
    return 1;
}
static void steer_aim(const MkwVkXr *x, const double d[3], uint64_t state, const double pos[3]) {
    const int pointed = d && g_aiming && !strcmp(cfg_value("VR_PLAY"), "motion") && x->head_active();
    x->aim_freeze(pointed);
    double t[3];
    const int pointer = pointed && x->pointer(t);
    if (!pointer) return;
    {   /* ((Triforce VR) the aim onto the pointer: the bow's and the slingshot's pitch set in the camera's state (set_aim); the
           rest through the right stick, which the game's aim always takes (its own yaw, the hookshot's and the boomerang's
           aim are made again each update from a state not found): full past kStickFull degrees off, in proportion below,
           none within kStickDead. A full push turns the aim some 49 degrees a second */
        /* (kStickLeast: the least push off kStickDead, past the game's own dead zone, so the last degrees close too) */
        static const double kStickFull = 10.0, kStickDead = 0.3, kStickLeast = 0.25;
        char upper[48];
        oot_link_state_at(upper, 0x34c);
        const int pose = link_aims(), boomerang = g_held_boomerang, hookshot = g_held_hookshot || !strncmp(upper, "Hookshot", 8);
        if (!pose && !boomerang && !hookshot) return;
        if (boomerang && !pose) {   /* (the boomerang's aim is the game's camera's, behind and above him: in first person that
                                       camera is turned onto the point 15 m out along the gaze from his eyes) */
            double eye[3];
            if (first_person_eye(eye)) {
                double v[3], n = 0;
                for (int i = 0; i < 3; i++) v[i] = eye[i] + 15.0 * t[i] - pos[i], n += v[i] * v[i];
                n = sqrt(n);
                if (n > 1e-3) for (int i = 0; i < 3; i++) t[i] = v[i] / n;
            }
        }
        const int pitch_set = pose && !hookshot && set_aim(state, t);
        const double yaw_err = wrap_pi(atan2(t[0], t[2]) - atan2(d[0], d[2])) * 180 / M_PI;
        const double up_err = (asin(fmax(-1, fmin(1, t[1]))) - asin(fmax(-1, fmin(1, d[1])))) * 180 / M_PI;
#define STICK_PUSH(e) (fabs(e) < kStickDead ? 0 : copysign(fmax(kStickLeast, fmin(1, fabs(e) / kStickFull)), (e)))
        const double sx = STICK_PUSH(-yaw_err);
        /* (out of the aiming pose (the boomerang, the hookshot held) the aim is the third-person camera's, whose up and down go
           the other way from the aiming pose's) */
        const double sy = pitch_set ? 0 : STICK_PUSH(pose ? -up_err : up_err);
#undef STICK_PUSH
        stick_aim[0] = (int32_t)(sx * 32767), stick_aim[1] = (int32_t)(sy * 32767);
        __atomic_store_n(&stick_aim_at, now_ns(), __ATOMIC_RELEASE);
    }
}

/* the camera's state (x19) has its actor at +0x10, the actor its name at +0x20: 1 the camera that follows Link, 2 the
   events' camera, 0 another (the interface's 3D models', the sound's) */
static int scene_camera(uint64_t state) {
    char name[16] = "";
    const uint64_t actor = rd_ptr(state + 0x10), np = actor ? rd_ptr(actor + 0x20) : 0;
    if (!np || !rd(np, name, 15)) return 0;
    name[15] = 0;
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

/* ((Triforce VR) how the event playing is seen, by its name and Link's state: from Link's eyes always (load zones, a void out,
   the castle guards' throw-out, a conversation, getting an item, showing one), with the HUD panel hidden for a transition,
   or as the Cutscenes row says (classic: the events' camera) */
enum { EV_CUTSCENE, EV_EYES, EV_EYES_NO_HUD };
static int event_view(uint64_t event) {
    static uint64_t was;
    static char name[64];
    static int shot, flinched;   /* (this event: Link has been in a directed shot's state; in the guards' flinch) */
    if (event != was) {
        oot_event_name(event, name);
        was = event, shot = flinched = 0;
        hos_log("vr: event \"%s\"", name);
    }
    char state[48];
    oot_link_state_at(state, 0x244);
    const size_t n = strlen(name);
    /* a load zone's two halves (Dm_SY_BancChangeGo and ..._Arrive_<place>) and a void out (DmF_SY_FallDown): no HUD; the system's
       others (the ocarina, Dm_SY_Ocarina) with it */
    if (strstr(name, "BancChange") || strstr(name, "FallDown")) return EV_EYES_NO_HUD;
    if (strstr(name, "_SY_")) return EV_EYES;
    /* caught by the castle's guards: the talk, then the throw-out to the gate (from his flinch's end on) */
    if (!strcmp(name, "HyruleCastle_FoundBySecurity")) {
        if (!strcmp(state, "EvtFlinchLong")) flinched = 1;
        else if (flinched) return EV_EYES_NO_HUD;
        return EV_EYES;
    }
    /* showing an item (ShowItem with no one to show it to; EvtShowItemSuccess at the start of the one it is shown to) */
    if (!strcmp(name, "ShowItem") || !strncmp(state, "EvtShowItem", 11)) return EV_EYES;
    /* getting an item (an event of its own, its name ending _D_S) */
    if (n > 4 && !strcmp(name + n - 4, "_D_S")) return EV_EYES;
    /* a conversation (_D_T), until Link is in a directed shot's state (C and a number: C06, C08_Loop...): a lesson's
       cutscene from there on */
    if (n > 4 && !strcmp(name + n - 4, "_D_T")) {
        if (state[0] == 'C' && state[1] >= '0' && state[1] <= '9') shot = 1;
        if (!shot) return EV_EYES;
    }
    return strcmp(cfg_value("VR_CUTSCENES"), "first") ? EV_CUTSCENE : EV_EYES;
}

void hos_vr_camera(Ctx *c) {
    static const int up_reg[3] = {7, 16, 6};
    const MkwVkXr *x = xr();
    const int scene = x ? scene_camera(c->x[19]) : 0;
    if (scene != 1 && scene != 2) return;
    if (rx_option(HOS_OPT_CHEAT_CAMERA, 0)) return;   /* (the Debug tab's free camera has it) */
    hooks_on = 1;
    const uint64_t event_now = oot_event();
    const int event = event_now != 0;
    const int view = event ? event_view(event_now) : EV_CUTSCENE;
    if (x->hud_hidden) x->hud_hidden(view == EV_EYES_NO_HUD);
    {
        static int was_view = -1, was_event = -1;
        if (view != was_view || event != was_event)
            hos_log("vr: event view: %s", !event ? "none (play)" : view == EV_EYES_NO_HUD ? "Link's eyes, no HUD" : view == EV_EYES ? "Link's eyes" : "the cutscene's");
        was_view = view, was_event = event;
    }
    {   /* (research: Link's state names as they change) */
        static char was[48], was_up[48];
        char st[48], up[48];
        oot_link_state_at(st, 0x244), oot_link_state_at(up, 0x34c);
        if (strcmp(st, was) || strcmp(up, was_up)) hos_log("vr: state: \"%s\" upper \"%s\"", st, up);
        g_sidestep = !strcmp(st, "SideStep") || !strcmp(st, "SideStepLand") || !strcmp(st, "LockOnMove");
        memcpy(was, st, sizeof was), memcpy(was_up, up, sizeof was_up);
    }
    const int k = scene - 1;
    if (scene == 1) head_camera = 0;
    /* the camera that shows: Link's in play, the events' in an event. ((Triforce VR) An event with no camera of its own (the
       game's start from a file, DefaultBootEvent, keeps Link's): Link's while the events' has not updated for 200 ms, from his
       eyes as in play; it began third person until the event ended) */
    static uint64_t event_cam_at;
    if (scene == 2) event_cam_at = now_ns();
    if (scene == 2 ? !event : event && now_ns() - event_cam_at < 200000000ull) return;
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
    if (scene == 1 && turn_on) {
        const double dx = at[0] - pos[0], dz = at[2] - pos[2], n = sqrt(dx * dx + dz * dz);
        if (n > 1e-6) at[0] = pos[0] + n * sin(turn_w), at[2] = pos[2] + n * cos(turn_w);
    }
    if (scene == 1) {   /* the game's own camera's level way: the head's rest, for a run straight ahead */
        const double fx = at[0] - pos[0], fz = at[2] - pos[2], n = sqrt(fx * fx + fz * fz);
        if (n > 1e-6) base_s = fx / n, base_c = fz / n;
    }
    if (scene == 1) {   /* aiming: the game's own camera's ray, where its shots go, for the head's view's reticle */
        const int aims = link_aims();
        double d[3] = {at[0] - pos[0], at[1] - pos[1], at[2] - pos[2]};
        const double l = sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
        if (l > 1e-6) d[0] /= l, d[1] /= l, d[2] /= l;
        x->aim((aims || g_aiming) && l > 1e-6, pos, d);   /* ((Triforce VR) the boomerang's and the slingshot's too */
        steer_aim(x, l > 1e-6 ? d : NULL, c->x[19], pos);
    }
    double eye[3];
    int fp_eye = 0;
    if (scene == 1 && x->head_active() && first_person_eye(eye)) {   /* the game's camera's direction kept, from his eyes */
        for (int i = 0; i < 3; i++) at[i] += eye[i] - pos[i], pos[i] = eye[i];
        fp_eye = 1;
    }
    if (scene == 2 && view != EV_CUTSCENE && x->head_active() && first_person_eye(eye)) {
        /* ((Triforce VR) an event seen from Link's eyes: facing as the gameplay camera last did, the head turning from there.
           A load zone's or a void out's (no HUD): the way Link faces, the new place's entrance, not the old place's way, and
           play goes on from it) */
        float m[9];
        if (view == EV_EYES_NO_HUD && player_rot(m)) {
            const double fx = m[2], fz = m[8], n = sqrt(fx * fx + fz * fz);
            if (n > 1e-4) base_s = fx / n, base_c = fz / n, turn_on = 0;
        }
        for (int i = 0; i < 3; i++) pos[i] = eye[i];
        at[0] = eye[0] + base_s, at[1] = eye[1], at[2] = eye[2] + base_c;
        up[0] = 0, up[1] = 1, up[2] = 0;
        fp_eye = 1;
    } else if (scene == 2) {   /* an event's camera, VR_EVENT_UP cm up */
        const double lift = cfg_int("VR_EVENT_UP") / 100.0;
        pos[1] += lift, at[1] += lift;
    }
    if (scene == 1 && !fp_eye && x->head_active() && !strcmp(cfg_value("VR_CAMERA"), "third") && !g_aiming) {
        /* ((Triforce VR) Immersive's zoom (immersive_zoom): the camera moved toward what it looks at, never past the game's own */
        const double v[3] = {pos[0] - at[0], pos[1] - at[1], pos[2] - at[2]};
        const double len = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
        if (len > 1e-3) {
            zoom_game = len;
            const double want = zoom_d > 0.0 ? fmin(zoom_d, len * kZoomMost) : len;
            if (fabs(want - len) > 1e-4)
                for (int i = 0; i < 3; i++) pos[i] = at[i] + v[i] * (want / len);
        }
    }
    x->update_step(step_seconds < 0 ? -1 : update_seconds());
    if (!x->camera(pos, at, up, fp_eye)) return;
    for (int i = 0; i < 3; i++) set_d(c, i, pos[i]), set_d(c, 3 + i, at[i]), set_s(c, up_reg[i], up[i]);
    memcpy(out_pos[k], pos, sizeof pos), memcpy(out_at[k], at, sizeof at), have_out[k] = 1;
    head_camera = c->x[19];
    if (fp_eye) fp_eye_at = now_ns();   /* (vr_body.c: his head hidden; his arms on the controllers in play alone: the anchor) */
    if (scene != 1) return;   /* Link turns in play alone */
    {   /* (vr_body.c: where Link stood for this view, the hands' anchor; and first person's eyes on him) */
        float feet[3];
        if (player_pos(feet)) {
            AcquireSRWLockExclusive(&anchor_lock);
            for (int i = 0; i < 3; i++) anchor_feet[i] = feet[i];
            anchor_at = now_ns();
            ReleaseSRWLockExclusive(&anchor_lock);
        }
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
