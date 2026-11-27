/* (Triforce VR) A test port into the game's physics: an outside tool (notes/ghidra/runs/probe/push2.py) finds this
   mailbox in the process and asks for one game function call, which runs here on the game's thread at the camera
   update (hos_vr_camera). Nothing happens without a request.
   The grab (grab_step): a VR grip squeezed near a loose body (a pot) takes it at the spot the hand is on, holds it there with
   its turn, and lets it go with the hand's speed. notes/ghidra/physics.md has the game's side of it. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#endif

#include "hos.h"
#include "vr_game.h"
#include "../gpu/vk/vk_api.h"

const MkwVkXr *rx_xr(void);   /* (rx_backend.c) */

typedef struct {
    char magic[16];
    volatile uint32_t req, done;
    uint64_t fn, a0, a1, a3;
    float vec[4];
    uint64_t ret;
    int32_t status;   // 1 called, -1 no lifted function at fn
    volatile uint32_t calls;
    uint64_t a2;      // x2 when a2_raw, else x2 points at vec
    uint32_t a2_raw, pad;
    uint64_t a4;
    uint64_t hold_world, hold_id;
    volatile uint32_t hold_on, hold_frames;
    float hold_target[3], hold_body[3];
    int32_t hold_source;   // 1 a VR controller, 2 before Link's chest, 0 none
    float hold_gain, hold_max;   // 1/s, m/s
    float throw_vel[3];          // m/s, used at release when not all 0
    float release_vel[3];        // m/s
    // the grab (grab_step). A fake hand for runs without the headset: with fake_on the hands below stand in for the
    // controllers (in the game's world: place, where it points, the palm's facing; left then right), fake_grip their grips
    volatile uint32_t fake_on, fake_grip;
    float fake_pos[6], fake_point[6], fake_palm[6];
    uint32_t grab_off, grab_turn_off;   // 1: no grab; 1: hold the place only (no turning)
    float grab_reach, throw_gain;       // m from a body's outside (0: 0.06, from the fist's bone), the hand's speed times this at the let-go (0: 1)
    uint64_t grab_world[2], grab_id[2]; // what each hand holds, 0 none
    uint32_t grab_near, worlds_n;       // hands near a body to take (bits); physics worlds found
    uint64_t worlds[4];
    float grab_err[2];                  // m, a held body's distance from its spot
    float grab_throw[2][3];             // m/s, each hand's last let-go
    uint32_t grabs, throws;
    // the push (push_step): the arms, the hands and the item held out move loose bodies out of their way
    uint32_t push_off;
    float push_gain;                    // 1/s of the overlap (0: 15)
    float item_len;                     // m from the fist to the item's tip (0: by the item)
    uint32_t pushes, push_id;           // bodies pushed so far; the last one's id
    uint32_t push_segs;                 // segments on (bits: 0-1 left upper, fore; 2-3 right; 4 the item; 5-6 the hands)
    float push_max;                     // m/s (0: 3)
    // the hit (push_step): the item or a hand moving into a body faster than hit_min along the touch sends it off at
    // hit_gain times that speed (and a share of the sideways speed), at most hit_max
    float hit_min, hit_gain, hit_max;   // m/s (0: 1.5), times (0: 1.6), m/s (0: 12)
    uint32_t hits, impacts;             // hits so far; bodies given the impact flag so far
    float break_min;                    // m/s: a throw or hit this fast gives the body the impact flag (0: 2)
} VrPhysMailbox;

VrPhysMailbox vr_phys_mailbox = {{'V', 'R', 'P', 'H', 'Y', 'S', '_', 'M', 'A', 'I', 'L', 'B', 'O', 'X', '0', '2'}};

#define MAIN_BASE 0x80020000ULL
#define BODY_SET_TYPE (MAIN_BASE + 0x17adf20)
#define BODY_SET_VEL (MAIN_BASE + 0x17b0c20)
#define BODY_SET_VELS (MAIN_BASE + 0x17b0200)   /* world entry 50 (world, id, float4 *lin, float4 *ang, mode): guess */
#define WORLD_BODY_SLOT 0x118
#define WORLD_VT_GOT (MAIN_BASE + 0x4ca1b70)    /* [it] + 0x10: the hknpWorld vtable */
#define WORLD_CHAIN (MAIN_BASE + 0x4c7df00)     /* (guess, main+0x29f10) world 1 at [[[[it]] + 0xc0] + 0xc8] + 0xe0 */

static uint64_t game_call(Ctx *c, uint64_t fn, uint64_t sp, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3, uint64_t a4) {
    const A64Fn f = a64_lookup(fn);
    if (!f) return ~0ULL;
    const Ctx saved = *c;
    c->x[31] = sp, c->x[0] = a0, c->x[1] = a1, c->x[2] = a2, c->x[3] = a3, c->x[4] = a4;
    f(c);
    const uint64_t r = c->x[0];
    *c = saved;
    return r;
}

static uint64_t ld64(uint64_t a) { uint64_t v; memcpy(&v, GP(a), 8); return v; }

static int player_pose(float pos[3], float rot[9]) {
    const uint64_t m = ld64(MAIN_BASE + 0x4e371d0);
    const uint64_t link = m ? ld64(m + 0x480) : 0;
    if (!link) return 0;
    memcpy(pos, GP(link + 0x31c), 12);
    memcpy(rot, GP(link + 0x328), 36);
    return isfinite(pos[0]) && isfinite(pos[1]) && isfinite(pos[2]);
}

static int hold_target(float t[3]) {
    const MkwVkXr *x = rx_xr();
    double hand[6], point[6], palm[6];
    if (x && x->active && x->active() && x->hands && x->hands(hand, point, palm))
        for (int h = 1; h >= 0; h--)
            if (hand[h * 3] != 0 || hand[h * 3 + 1] != 0 || hand[h * 3 + 2] != 0) {
                for (int k = 0; k < 3; k++) t[k] = (float)hand[h * 3 + k];
                return 1;
            }
    float p[3], r[9];
    if (!player_pose(p, r)) return 0;
    for (int k = 0; k < 3; k++) t[k] = p[k] + r[k * 3 + 2] * 0.5f;
    t[1] += 1.0f;
    return 2;
}

static uint64_t body_record(Ctx *c, uint64_t frame, uint64_t w, uint64_t id) {
    if (!w || !ld64(w)) return 0;
    const uint64_t rec = game_call(c, ld64(ld64(w) + WORLD_BODY_SLOT), frame, w, id, 0, 0, 0);
    return rec == ~0ULL || rec < 0x10000 ? 0 : rec;
}

static void set_vel(Ctx *c, uint64_t frame, uint64_t w, uint64_t id, const float v3[3]) {
    const float v[4] = {v3[0], v3[1], v3[2], 0};
    const uint64_t vec = frame + 0x200;
    memcpy(GP(vec), v, sizeof v);
    game_call(c, BODY_SET_VEL, frame, w, id, vec, 0, 0);
}

#define TRAIL 32
typedef struct {
    struct { int64_t t; float p[3]; } at[TRAIL];
    int n;
} Trail;
static Trail trail;   // (the mailbox's hold)

static void trail_add(Trail *tr, int64_t now, const float p[3]) {
    const int i = tr->n++ % TRAIL;
    tr->at[i].t = now, memcpy(tr->at[i].p, p, 12);
}

static int trail_vel(const Trail *tr, int64_t now, float v[3]) {   // the speed over the last 0.08 s
    if (tr->n < 2) return 0;
    const int last = (tr->n - 1) % TRAIL;
    int j = last;
    for (int n = 1; n < TRAIL && n < tr->n; n++) {
        const int k = (tr->n - 1 - n) % TRAIL;
        j = k;
        if (now - tr->at[k].t > 80000000) break;
    }
    const double dt = (tr->at[last].t - tr->at[j].t) / 1e9;
    if (dt < 0.01) return 0;
    for (int k = 0; k < 3; k++) v[k] = (float)((tr->at[last].p[k] - tr->at[j].p[k]) / dt);
    return 1;
}

static void hold_step(Ctx *c, uint64_t frame) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    const uint64_t w = m->hold_world, id = m->hold_id;
    const uint64_t rec = body_record(c, frame, w, id);
    if (!rec) return;
    if (m->hold_frames == 0) {
        game_call(c, BODY_SET_TYPE, frame, w, id, 2, 1, 1);
        trail.n = 0;
    }
    float body[3], t[3];
    memcpy(body, GP(rec + 0x30), 12);
    const int src = hold_target(t);
    m->hold_source = src;
    if (!src) return;
    trail_add(&trail, hos_now_ns(), t);
    const float gain = m->hold_gain > 0 ? m->hold_gain : 12.0f, vmax = m->hold_max > 0 ? m->hold_max : 12.0f;
    float v[3] = {(t[0] - body[0]) * gain, (t[1] - body[1]) * gain, (t[2] - body[2]) * gain};
    const float len = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (len > vmax) for (int k = 0; k < 3; k++) v[k] *= vmax / len;
    set_vel(c, frame, w, id, v);
    memcpy(m->hold_target, t, 12), memcpy(m->hold_body, body, 12);
    m->hold_frames++;
}

static void release(Ctx *c, uint64_t frame) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    if (!body_record(c, frame, m->hold_world, m->hold_id)) return;
    float v[3] = {0, 0, 0};
    if (m->throw_vel[0] != 0 || m->throw_vel[1] != 0 || m->throw_vel[2] != 0) memcpy(v, m->throw_vel, 12);
    else trail_vel(&trail, hos_now_ns(), v);
    set_vel(c, frame, m->hold_world, m->hold_id, v);
    memcpy(m->release_vel, v, 12);
}

/* ---- the grab */

static int heap_ok(uint64_t a, uint64_t n) {
    return a >= HOS_HEAP_BASE && a - HOS_HEAP_BASE < hos_heap_size && n <= hos_heap_size - (a - HOS_HEAP_BASE);
}
static uint64_t ldh(uint64_t a) { return heap_ok(a, 8) ? ld64(a) : 0; }
static uint32_t ld32(uint64_t a) { uint32_t v; memcpy(&v, GP(a), 4); return v; }

static uint64_t world_vt(void) {
    const uint64_t g = ld64(WORLD_VT_GOT);
    return g ? g + 0x10 : 0;
}
static int world_ok(uint64_t w, uint64_t vt) {   // a world: its vtable, and its body chunks' list in the heap
    return vt && heap_ok(w, 0x1100) && ld64(w) == vt && heap_ok(ldh(w + 0x48), 8);
}

/* the worlds: the chain the game's own per-frame body copy uses (guess), and a scan of the heap for the vtable on a thread of
   its own (once, and again 5 s after the worlds go away: a new room makes new ones) */
static volatile uint64_t scan_found[4];
static volatile int scan_n, scan_busy;
static uint64_t scan_vt;

static void scan_run(void) {
    uint64_t found[4] = {0};
    int n = 0;
    const uint64_t used = hos_heap_used ? hos_heap_used : hos_heap_size, vt = scan_vt;
    const uint8_t *base = (const uint8_t *)GP(HOS_HEAP_BASE);
    for (uint64_t o = 0; o + 0x1100 <= used && n < 4; o += 16) {
        uint64_t v;
        memcpy(&v, base + o, 8);
        if (v == vt && world_ok(HOS_HEAP_BASE + o, vt)) found[n++] = HOS_HEAP_BASE + o;
    }
    for (int i = 0; i < 4; i++) scan_found[i] = found[i];
    __atomic_store_n(&scan_n, n, __ATOMIC_RELEASE);
    __atomic_store_n(&scan_busy, 0, __ATOMIC_RELEASE);
    hos_log("vr: grab: the heap scan found %d physics world(s)", n);
}
#ifdef _WIN32
static DWORD WINAPI scan_thread(LPVOID arg) { (void)arg; scan_run(); return 0; }
#else
static void *scan_thread(void *arg) { (void)arg; scan_run(); return NULL; }
#endif

static int worlds_find(uint64_t out[4]) {
    static int64_t scan_at;
    static uint64_t logged;
    const uint64_t vt = world_vt();
    if (!vt) return 0;
    int n = 0;
    if (!__atomic_load_n(&scan_busy, __ATOMIC_ACQUIRE))
        for (int i = 0; i < __atomic_load_n(&scan_n, __ATOMIC_ACQUIRE) && n < 4; i++)
            if (world_ok(scan_found[i], vt)) out[n++] = scan_found[i];
    const uint64_t chained = ldh(ldh(ldh(ldh(ld64(WORLD_CHAIN)) + 0xc0) + 0xc8) + 0xe0);
    if (world_ok(chained, vt)) {
        int have = 0;
        for (int i = 0; i < n; i++) have |= out[i] == chained;
        if (!have && n < 4) out[n++] = chained;
        if (logged != chained) logged = chained, hos_log("vr: grab: physics world %#llx from the game's chain", (unsigned long long)chained);
    }
    const int64_t now = hos_now_ns();
    if (!n && !scan_busy && (!scan_at || now - scan_at > 5000000000LL)) {
        scan_at = now, scan_vt = vt, scan_busy = 1;
#ifdef _WIN32
        const HANDLE t = CreateThread(NULL, 0, scan_thread, NULL, 0, NULL);
        if (t) CloseHandle(t);
        else scan_busy = 0;
#else
        pthread_t t;
        if (!pthread_create(&t, NULL, scan_thread, NULL)) pthread_detach(t);
        else scan_busy = 0;
#endif
    }
    return n;
}

/* a body record (idx: its slot) of world w, 0 when that slot holds none */
static uint64_t body_at(uint64_t w, uint32_t idx) {
    const uint64_t chunk = ldh(ldh(w + 0x48) + (idx / 42) * 8ull);
    if (!heap_ok(chunk, 42 * 0xC0)) return 0;
    const uint64_t rec = chunk + (idx % 42) * 0xC0ull;
    return (ld32(rec + 0x58) & 0xffffff) == idx ? rec : 0;
}

/* ---- who owns a body. The actors in Link's list (+0x1b0: entries of 0x60, the actor at +0x40; vr_body.c walks it for
   Navi), each one's rigid body rb = [C + 400] with C = [[[actor+0x270]+0x50]+0x20], and that rb's own Havok body id at
   [rb+0x78]+8 (physics.md, verified on pots). A body record names its rb at +0xB8 (verified on pots). So a record is an
   actor's own body when its rb is one of theirs and its id is the one that rb names; a pot's other records (world 2)
   are not, and moving them moves nothing. Built again each second */
#define OWNERS 1024
typedef struct { uint64_t rb, actor; uint32_t id; char name[40]; } Owner;
static Owner owners[OWNERS];
static int owners_n;

static uint64_t link_actor(void) {
    const uint64_t m = ld64(MAIN_BASE + 0x4e371d0);
    return m ? ldh(m + 0x480) : 0;
}
static int name_read(uint64_t actor, char out[40]) {
    const uint64_t p = ldh(actor + 0x20);
    out[0] = 0;
    if (!heap_ok(p, 40) && !(p >= hos_image_base && p + 40 <= hos_image_end)) return 0;
    const char *s = (const char *)GP(p);
    int n = 0;
    for (; n < 39 && s[n]; n++) {
        if (s[n] < 32 || s[n] > 126) return out[0] = 0, 0;
        out[n] = s[n];
    }
    out[n] = 0;
    return n >= 3 && n < 39;
}
static int owner_cmp(const void *a, const void *b) {
    const uint64_t x = ((const Owner *)a)->rb, y = ((const Owner *)b)->rb;
    return x < y ? -1 : x > y;
}
static void owners_build(void) {
    static int64_t at;
    const int64_t now = hos_now_ns();
    if (at && now - at < 1000000000LL) return;
    at = now;
    const uint64_t link = link_actor(), list = link ? ldh(link + 0x1b0) : 0;
    int n = 0;
    for (int i = 0; list && i < 4096 && n < OWNERS; i++) {
        const uint64_t e = list + (uint64_t)i * 0x60 + 0x40;
        if (!heap_ok(e, 8)) break;
        const uint64_t a = ldh(e);
        if (!a || !heap_ok(a, 0x280)) continue;
        const uint64_t C = ldh(ldh(ldh(a + 0x270) + 0x50) + 0x20), rb = C ? ldh(C + 400) : 0, b = rb ? ldh(rb + 0x78) : 0;
        if (!b || !heap_ok(b + 8, 4)) continue;
        Owner *o = &owners[n];
        if (!name_read(a, o->name)) continue;
        o->rb = rb, o->actor = a, o->id = ld32(b + 8), n++;
    }
    qsort(owners, (size_t)n, sizeof *owners, owner_cmp);
    if (n != owners_n) hos_log("vr: grab: %d actors with a rigid body in Link's list", n);
    owners_n = n;
}
/* the actor whose own body the record is, 0 none known */
static const Owner *owner_of(uint64_t rec) {
    const uint64_t rb = ld64(rec + 0xB8);
    const uint32_t rid = ld32(rec + 0x58);
    int lo = 0, hi = owners_n - 1;
    while (lo <= hi) {
        const int mid = (lo + hi) / 2;
        if (owners[mid].rb == rb) return owners[mid].id == rid ? &owners[mid] : NULL;
        if (owners[mid].rb < rb) lo = mid + 1;
        else hi = mid - 1;
    }
    return NULL;
}
/* characters by their actors' names: Link, people, enemies, animals; and what Link holds (his sword, shield, items) */
static int is_character(const char *name) {
    static const char *const no[] = {"Player", "Link", "Npc", "Enemy", "Boss", "Animal", "Horse", "Fairy", "Weapon_", "Item_"};
    for (unsigned i = 0; i < sizeof no / sizeof *no; i++)
        if (!strncmp(name, no[i], strlen(no[i]))) return 1;
    return 0;
}

/* a body a hand can take. An actor's own body (owner_of): any actor that is not a character, its body loose or static (a
   static one is made loose at the take: rocks may rest static, guess), not keyframed (bit 2: what the game moves, as doors
   and platforms), its world box under 2 m on every side. A body no actor owns: as before, ids 0x01xxxxxx, flags 0xc8 with
   bits 0 (static) and 2 (keyframed) clear (verified on pots). Both: the handle at +0xB0. owner: its actor, else NULL */
static int body_box(uint64_t rec, float lo[3], float hi[3]);
static int takeable_by(uint64_t rec, uint64_t *id, const Owner **owner) {
    const uint32_t rid = ld32(rec + 0x58), flags = ld32(rec + 0x50);
    const Owner *o = owner_of(rec);
    if (owner) *owner = o;
    if (rid >> 24 == 0 || flags & 4) return 0;
    if (o) {
        float lo[3], hi[3];
        if (is_character(o->name) || !body_box(rec, lo, hi)) return 0;
        for (int k = 0; k < 3; k++)
            if (hi[k] - lo[k] > 2.0f) return 0;
    } else if (rid >> 24 != 1 || flags >> 24 != 0xc8 || flags & 1) return 0;
    const uint64_t handle = ld64(rec + 0xB0);
    if (handle != (0x80000000ull << 32 | rid)) return 0;
    *id = handle;
    float p[3];
    memcpy(p, GP(rec + 0x30), 12);
    return isfinite(p[0]) && isfinite(p[1]) && isfinite(p[2]);
}
static int takeable(uint64_t rec, uint64_t *id) { return takeable_by(rec, id, NULL); }

typedef struct {
    int ok;
    float p[3], r[9];   // place; turn as 3 columns (the grip's x, y, z)
} Hand;

static void norm3(float v[3]) {
    const float n = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (n > 1e-6f) v[0] /= n, v[1] /= n, v[2] /= n;
}
static void cross3(const float a[3], const float b[3], float o[3]) {
    o[0] = a[1] * b[2] - a[2] * b[1], o[1] = a[2] * b[0] - a[0] * b[2], o[2] = a[0] * b[1] - a[1] * b[0];
}

/* the grip's frame from where it points (its -z) and its palm's facing (its +x) */
static int hand_from(const double pos[3], const double point[3], const double palm[3], Hand *h) {
    float x[3], z[3], y[3];
    for (int k = 0; k < 3; k++) h->p[k] = (float)pos[k], x[k] = (float)palm[k], z[k] = -(float)point[k];
    if (h->p[0] == 0 && h->p[1] == 0 && h->p[2] == 0) return h->ok = 0;
    if (x[0] == 0 && x[1] == 0 && x[2] == 0) x[0] = 1;
    if (z[0] == 0 && z[1] == 0 && z[2] == 0) z[2] = 1;
    norm3(z), cross3(z, x, y), norm3(y), cross3(y, z, x);
    for (int k = 0; k < 3; k++) h->r[k] = x[k], h->r[3 + k] = y[k], h->r[6 + k] = z[k];
    return h->ok = 1;
}

/* the hands and their grips (bit 0 left, 1 right): the mailbox's fake hand, else the controllers; 0 neither */
static int hands_read(Hand hd[2], int *grips) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    double pos[6], point[6], palm[6];
    if (m->fake_on) {
        for (int k = 0; k < 6; k++) pos[k] = m->fake_pos[k], point[k] = m->fake_point[k], palm[k] = m->fake_palm[k];
        *grips = (int)m->fake_grip & 3;
    } else {
        const MkwVkXr *x = rx_xr();
        if (!x || !x->active || !x->active() || !x->grips || !x->grab_hands || !x->hands || !x->hands(pos, point, palm))
            return 0;
        *grips = x->grips();
    }
    int any = 0;
    for (int h = 0; h < 2; h++) any |= hand_from(pos + h * 3, point + h * 3, palm + h * 3, &hd[h]);
    return any;
}

static struct {
    int on;
    uint64_t w, id;
    uint32_t idx;
    float off[3], turn[9];   // the body's place and turn in the hand's frame
    float spin[3];
    Trail tr;
} held[2];
static int grips_was;

static void mat_mul(const float a[9], const float b[9], float o[9]) {   // column-major 3x3: o = a b
    for (int c = 0; c < 3; c++)
        for (int r = 0; r < 3; r++) o[c * 3 + r] = a[r] * b[c * 3] + a[3 + r] * b[c * 3 + 1] + a[6 + r] * b[c * 3 + 2];
}
static void mat_tmul(const float a[9], const float b[9], float o[9]) {   // o = a^T b
    for (int c = 0; c < 3; c++)
        for (int r = 0; r < 3; r++)
            o[c * 3 + r] = a[r * 3] * b[c * 3] + a[r * 3 + 1] * b[c * 3 + 1] + a[r * 3 + 2] * b[c * 3 + 2];
}
static void body_pose(uint64_t rec, float p[3], float r[9]) {   // the record's 3 columns of 16 bytes, then its place
    float m[12];
    memcpy(m, GP(rec), 48);
    for (int c = 0; c < 3; c++) r[c * 3] = m[c * 4], r[c * 3 + 1] = m[c * 4 + 1], r[c * 3 + 2] = m[c * 4 + 2];
    memcpy(p, GP(rec + 0x30), 12);
}

// main+0x136ae0 copies rb+0x80 (3x4 rows) onto the actor; main+0x29f10 fills it from the body only when rb+0x70 bit 6 is clear
static uint64_t rb_of(uint64_t rec) {
    const uint64_t rb = ldh(rec + 0xB8), b = rb && heap_ok(rb, 0xb0) ? ldh(rb + 0x78) : 0;
    return b && heap_ok(b + 8, 4) && ld32(b + 8) == ld32(rec + 0x58) ? rb : 0;
}
static void rb_follow(uint64_t rec) {
    const uint64_t rb = rb_of(rec);
    if (!rb) return;
    float p[3], r[9], row[12];
    body_pose(rec, p, r);
    for (int i = 0; i < 3; i++) row[i * 4] = r[i], row[i * 4 + 1] = r[3 + i], row[i * 4 + 2] = r[6 + i], row[i * 4 + 3] = p[i];
    memcpy(GP(rb + 0x80), row, sizeof row);
}
static int actor_place(uint64_t rec, float p[3]) {   // actor +0x31c (verified on pots)
    const Owner *o = owner_of(rec);
    if (!o || !heap_ok(o->actor + 0x31c, 12)) return 0;
    memcpy(p, GP(o->actor + 0x31c), 12);
    return 1;
}

static struct { uint64_t w, id; uint32_t idx; int64_t until, thrown_until; } loose[8];   // let go and still flying
static int loose_n;
static void loose_add(uint64_t w, uint64_t id, uint32_t idx, int thrown) {
    int e = 0;
    while (e < loose_n && !(loose[e].w == w && loose[e].id == id)) e++;
    if (e == loose_n) {
        if (loose_n == 8) e = 0;
        else loose_n++;
        loose[e].thrown_until = 0;
    }
    const int64_t now = hos_now_ns();
    loose[e].w = w, loose[e].id = id, loose[e].idx = idx, loose[e].until = now + 10000000000LL;
    if (thrown) loose[e].thrown_until = now + 1000000000LL;   // the push keeps off it for 1 s
}
static int just_thrown(uint64_t w, uint64_t id) {
    const int64_t now = hos_now_ns();
    for (int e = 0; e < loose_n; e++)
        if (loose[e].w == w && loose[e].id == id) return now < loose[e].thrown_until;
    return 0;
}
static void loose_step(void) {
    const int64_t now = hos_now_ns();
    for (int e = 0; e < loose_n;) {
        const uint64_t rec = body_at(loose[e].w, loose[e].idx);
        const int on = rec && ld64(rec + 0xB0) == loose[e].id && now < loose[e].until && ld32(rec + 0x50) & 8;   // (bit 3: awake)
        if (!on) {
            loose[e] = loose[--loose_n];
            continue;
        }
        rb_follow(rec), e++;
    }
}

static void set_vels(Ctx *c, uint64_t frame, uint64_t w, uint64_t id, const float lin[3], const float ang[3]) {
    set_vel(c, frame, w, id, lin);   // (verified: moves the body)
    if (!ang || vr_phys_mailbox.grab_turn_off) return;
    const float l[4] = {lin[0], lin[1], lin[2], 0}, a[4] = {ang[0], ang[1], ang[2], 0};
    memcpy(GP(frame + 0x200), l, 16), memcpy(GP(frame + 0x210), a, 16);
    game_call(c, BODY_SET_VELS, frame, w, id, frame + 0x200, frame + 0x210, 1);
}

/* The impact flag, record +0x50 bit 27. Pots carry it (flags 0xc8...) and break when they hit something hard enough with
   no code of ours (physics.md, speed_test.txt); rocks (Obj_LiftRock_A_01) and Land_Kokiri_Zenmai_A_02 do not (0xc0...)
   and a rock thrown at 14 m/s did not break (triforce_log.4.txt, 2026-11-27). guess: Havok's flag that reports contact
   impulses, which the game's ImpactIntensityParam (WeakObject: pots and rocks) breaks on; a body at rest is left without
   it and the game sets it when Link lifts one. So a body sent off fast gets it, and the game decides whether it breaks */
#define IMPACT_FLAG 0x08000000u
static void impact_arm(uint64_t rec, float speed, const char *how) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    const float min = m->break_min > 0 ? m->break_min : 2.0f;
    if (!rec || speed < min || ld32(rec + 0x50) & IMPACT_FLAG) return;
    const uint32_t was = __atomic_fetch_or((uint32_t *)GP(rec + 0x50), IMPACT_FLAG, __ATOMIC_RELAXED);   // (Havok's threads write it too)
    const Owner *own = owner_of(rec);
    m->impacts++;
    hos_log("vr: grab: %s body %#x of %s at %.1f m/s: impact flag set (flags %#x -> %#x)", how, ld32(rec + 0x58),
            own ? own->name : "no actor", speed, was, ld32(rec + 0x50));
}

static void grab_release(Ctx *c, uint64_t frame, int h, int throw_it) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    float v[3] = {0, 0, 0};
    if (throw_it && trail_vel(&held[h].tr, hos_now_ns(), v)) {
        const float gain = m->throw_gain > 0 ? m->throw_gain : 1.0f;
        for (int k = 0; k < 3; k++) v[k] *= gain;
    }
    const uint64_t rec = body_at(held[h].w, held[h].idx);
    float bp[3] = {0, 0, 0}, ap[3] = {0, 0, 0};
    if (rec) {
        impact_arm(rec, sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]), "thrown");
        set_vels(c, frame, held[h].w, held[h].id, v, held[h].spin), m->throws++;
        loose_add(held[h].w, held[h].id, held[h].idx, 1);
        memcpy(bp, GP(rec + 0x30), 12);
    }
    const int have_actor = rec && actor_place(rec, ap);
    memcpy(m->grab_throw[h], v, 12);
    hos_log("vr: grab: the %s hand let go of %#llx at %.2f %.2f %.2f m/s; body at %.2f %.2f %.2f, %s %.2f %.2f %.2f",
            h ? "right" : "left", (unsigned long long)held[h].id, v[0], v[1], v[2], bp[0], bp[1], bp[2],
            have_actor ? "its actor at" : "no actor", ap[0], ap[1], ap[2]);
    held[h].on = 0, m->grab_world[h] = m->grab_id[h] = 0;
}

static void grab_hold(Ctx *c, uint64_t frame, int h, const Hand *hd) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    const uint64_t rec = body_at(held[h].w, held[h].idx);
    uint64_t id;
    if (!rec || !takeable(rec, &id) || id != held[h].id) {   // (broken or gone)
        hos_log("vr: grab: the %s hand's body %#llx is gone", h ? "right" : "left", (unsigned long long)held[h].id);
        held[h].on = 0, m->grab_world[h] = m->grab_id[h] = 0;
        return;
    }
    float bp[3], br[9], tp[3], tr[9], hv[3] = {0, 0, 0};
    body_pose(rec, bp, br);
    for (int k = 0; k < 3; k++)
        tp[k] = hd->p[k] + hd->r[k] * held[h].off[0] + hd->r[3 + k] * held[h].off[1] + hd->r[6 + k] * held[h].off[2];
    mat_mul(hd->r, held[h].turn, tr);
    trail_add(&held[h].tr, hos_now_ns(), tp);
    trail_vel(&held[h].tr, hos_now_ns(), hv);
    // the place: the spot's own speed and 12/s of the gap, at most 15 m/s
    float v[3], d2 = 0;
    for (int k = 0; k < 3; k++) v[k] = hv[k] + (tp[k] - bp[k]) * 12.0f, d2 += (tp[k] - bp[k]) * (tp[k] - bp[k]);
    const float len = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (len > 15.0f)
        for (int k = 0; k < 3; k++) v[k] *= 15.0f / len;
    // the turn: the rotation from the body's to the spot's (tr br^T) as an axis and angle, 10/s of it, at most 20 rad/s
    float e[9], bt[9], w[3] = {0, 0, 0};
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++) bt[j * 3 + i] = br[i * 3 + j];
    mat_mul(tr, bt, e);
    const float ca = fmaxf(-1.0f, fminf(1.0f, (e[0] + e[4] + e[8] - 1) * 0.5f)), ang = acosf(ca);
    if (ang > 1e-3f) {
        float ax[3] = {e[5] - e[7], e[6] - e[2], e[1] - e[3]};   // (column-major: e(2,1) - e(1,2), e(0,2) - e(2,0), e(1,0) - e(0,1))
        norm3(ax);
        const float rate = fminf(ang * 10.0f, 20.0f);
        for (int k = 0; k < 3; k++) w[k] = ax[k] * rate;
    }
    memcpy(held[h].spin, w, 12);
    set_vels(c, frame, held[h].w, held[h].id, v, w);
    rb_follow(rec);
    m->grab_err[h] = sqrtf(d2);
}

/* the body's world box: record +0x60 max x, y, z; +0x6c min z, +0x70 min x, +0x74 min y (verified, aabb_probe.txt: a pot's
   box 0.68 m wide, 0.75 m tall about its place). 0 when it is not a box (not finite, inside out, over 3 m) */
static int body_box(uint64_t rec, float lo[3], float hi[3]) {
    float f[6];
    memcpy(f, GP(rec + 0x60), sizeof f);
    hi[0] = f[0], hi[1] = f[1], hi[2] = f[2], lo[2] = f[3], lo[0] = f[4], lo[1] = f[5];
    for (int k = 0; k < 3; k++)
        if (!isfinite(lo[k]) || !isfinite(hi[k]) || hi[k] < lo[k] || hi[k] - lo[k] > 3.0f) return 0;
    return 1;
}

/* the body's hull, when its shape is one: record +0x78 -> +0x30, class table main+0x4c31f90; its points (x, y, z floats in
   the body's own frame) at +0xd0, their count at +0xd8, a skin around them at +0xdc, m (verified on 3 pots, hull_probe.txt:
   24 points in rings of radius 0.21, 0.27, 0.18 m at 0, 0.31, 0.60 m up, skin 0.05). Its points' middle in c */
#define HULL_VT (MAIN_BASE + 0x4c31f90)
typedef struct { uint64_t pts; uint32_t n; float skin, c[3]; } Hull;
static int body_hull(uint64_t rec, Hull *hl) {
    const uint64_t s = ldh(rec + 0x78), a = s ? ldh(s + 0x30) : 0;
    if (!a || !heap_ok(a, 0xe0) || ld64(a) != HULL_VT) return 0;
    hl->pts = ld64(a + 0xd0), hl->n = ld32(a + 0xd8);
    memcpy(&hl->skin, GP(a + 0xdc), 4);
    if (hl->n < 4 || hl->n > 512 || !heap_ok(hl->pts, hl->n * 12ull) || !(hl->skin >= 0 && hl->skin < 0.5f)) return 0;
    hl->c[0] = hl->c[1] = hl->c[2] = 0;
    for (uint32_t i = 0; i < hl->n; i++) {
        float q[3];
        memcpy(q, GP(hl->pts + i * 12ull), 12);
        for (int k = 0; k < 3; k++) hl->c[k] += q[k] / (float)hl->n;
    }
    return isfinite(hl->c[0]) && isfinite(hl->c[1]) && isfinite(hl->c[2]);
}

/* a hand's distance from a body's outside, m (0 inside it); mid: its distance from the body's middle. With a hull: along the
   line from the hull's middle to the hand, the hand's distance less the hull's reach that way and its skin (exact where a face
   meets that line square on, a little short near edges). Else the box. -1 with neither */
static float body_gap(uint64_t rec, const float p[3], float *mid) {
    float lo[3], hi[3], g = 0, c = 0;
    Hull hl;
    if (body_hull(rec, &hl)) {
        float bp[3], br[9], d[3], l[3], len = 0, reach = -1e9f;
        body_pose(rec, bp, br);
        for (int k = 0; k < 3; k++) d[k] = p[k] - bp[k];
        for (int k = 0; k < 3; k++) l[k] = br[k * 3] * d[0] + br[k * 3 + 1] * d[1] + br[k * 3 + 2] * d[2] - hl.c[k], len += l[k] * l[k];
        len = sqrtf(len), *mid = len;
        if (len < 1e-4f) return 0;
        for (uint32_t i = 0; i < hl.n; i++) {
            float q[3];
            memcpy(q, GP(hl.pts + i * 12ull), 12);
            reach = fmaxf(reach, ((q[0] - hl.c[0]) * l[0] + (q[1] - hl.c[1]) * l[1] + (q[2] - hl.c[2]) * l[2]) / len);
        }
        return fmaxf(len - reach - hl.skin, 0);
    }
    if (!body_box(rec, lo, hi)) return *mid = -1, -1;
    for (int k = 0; k < 3; k++) {
        const float o = p[k] < lo[k] ? lo[k] - p[k] : p[k] > hi[k] ? p[k] - hi[k] : 0, m = p[k] - 0.5f * (lo[k] + hi[k]);
        g += o * o, c += m * m;
    }
    return *mid = sqrtf(c), sqrtf(g);
}

/* Link's own bodies (his 1.7 m capsule at his feet, 0x0100004a 0.23 m off it, aabb_probe.txt) have their boxes' middles within
   0.35 m of his place across the floor; a pot's cannot be (his capsule's radius 0.33 and a pot's 0.34 keep them 0.67 apart) */
static int on_link(uint64_t rec, const float link[3]) {
    float lo[3], hi[3];
    if (!body_box(rec, lo, hi)) return 1;
    const float dx = 0.5f * (lo[0] + hi[0]) - link[0], dz = 0.5f * (lo[2] + hi[2]) - link[2];
    return dx * dx + dz * dz < 0.35f * 0.35f;
}

/* the body a hand can take whose outside is nearest, within reach of it (its world, id, slot; the record), 0 none. miss: the
   nearest 0x01 body within 1 m that was not taken (its id, flags, gap), for the log */
typedef struct { uint32_t id, flags; float gap; int taken; char name[40]; } Miss;
static uint64_t grab_near(const uint64_t *worlds, int nw, const float p[3], float reach, uint64_t *w, uint64_t *id, uint32_t *idx,
                          Miss *miss) {
    float best = reach, best_mid = 1e9f, link[3], lr[9];
    const int have_link = player_pose(link, lr);
    uint64_t found = 0;
    miss->id = 0, miss->gap = 1.0f, miss->name[0] = 0;
    for (int i = 0; i < nw; i++) {
        const uint64_t chunks = ldh(worlds[i] + 0x48);
        for (uint32_t ci = 0; ci < 128; ci++) {
            const uint64_t chunk = ldh(chunks + ci * 8ull);
            if (!heap_ok(chunk, 42 * 0xC0)) break;
            for (uint32_t j = 0; j < 42; j++) {
                const uint32_t k = ci * 42 + j;
                const uint64_t rec = chunk + j * 0xC0ull;
                uint64_t bid = 0;
                const uint32_t rid = ld32(rec + 0x58);
                if ((rid & 0xffffff) != k || rid >> 24 == 0) continue;
                float q[3], d2 = 0;
                memcpy(q, GP(rec + 0x30), 12);
                for (int c = 0; c < 3; c++) d2 += (q[c] - p[c]) * (q[c] - p[c]);
                if (!(d2 < 9.0f)) continue;   // (more than 3 m off: no body is that big)
                float mid;
                const float gap = body_gap(rec, p, &mid);
                if (gap < 0) continue;
                const Owner *own = NULL;
                const int ok = takeable_by(rec, &bid, &own) && !(have_link && on_link(rec, link));
                int taken = 0;
                for (int h = 0; h < 2; h++) taken |= ok && held[h].on && held[h].id == bid && held[h].w == worlds[i];
                if (ok && !taken && (gap < best || (gap == best && mid < best_mid)))   // (in two boxes: the nearer middle)
                    best = gap, best_mid = mid, found = rec, *w = worlds[i], *id = bid, *idx = k;
                else if (gap < miss->gap) {
                    miss->id = rid, miss->flags = ld32(rec + 0x50), miss->gap = gap, miss->taken = taken;
                    snprintf(miss->name, sizeof miss->name, "%s", own ? own->name : "no actor");
                }
            }
        }
    }
    return found;
}

/* ---- the push */

typedef struct { float a[3], b[3], r; } Seg;
enum { SEGS = 7, SEG_ITEM = 4, SEG_HAND = 5 };

static float seg_closest(const Seg *s, const float q[3], float o[3]) {
    float d[3], dd = 0, t = 0;
    for (int k = 0; k < 3; k++) d[k] = s->b[k] - s->a[k], dd += d[k] * d[k], t += (q[k] - s->a[k]) * d[k];
    t = dd > 1e-8f ? fmaxf(0, fminf(1, t / dd)) : 0;
    for (int k = 0; k < 3; k++) o[k] = s->a[k] + d[k] * t;
    return t;
}

/* the body's middle in the world: its hull's points' middle, else its box's */
static int body_mid(uint64_t rec, float o[3]) {
    Hull hl;
    if (body_hull(rec, &hl)) {
        float bp[3], br[9];
        body_pose(rec, bp, br);
        for (int k = 0; k < 3; k++) o[k] = bp[k] + br[k] * hl.c[0] + br[3 + k] * hl.c[1] + br[6 + k] * hl.c[2];
        return 1;
    }
    float lo[3], hi[3];
    if (!body_box(rec, lo, hi)) return 0;
    for (int k = 0; k < 3; k++) o[k] = 0.5f * (lo[k] + hi[k]);
    return 1;
}

const char *vr_body_sword(void);   /* (vr_body.c) */
float vr_body_sword_scale(void);

/* the item's tip from the fist and its radius, m: its mesh's (vk_xr_item_shape), else a guess until that is read */
static float item_capsule(int what, float *radius) {
    char actor[48] = "";
    const char *sw = vr_body_sword();
    switch (what) {
    case VR_HELD_SWORD: snprintf(actor, sizeof actor, "%s", sw && sw[0] ? sw : vr_game_childhood() ? "Weapon_Sword_Kokiri" : "Weapon_Sword_Master"); break;
    case VR_HELD_DEKU_STICK: snprintf(actor, sizeof actor, "Item_DekuStick"); break;
    case VR_HELD_HAMMER: snprintf(actor, sizeof actor, "Item_Hammer"); break;
    default: return 0;
    }
    const MkwVkXr *x = rx_xr();
    float shape[3];
    float len = what == VR_HELD_SWORD ? (vr_game_two_handed() ? 1.25f : vr_game_childhood() ? 0.55f : 0.85f) : what == VR_HELD_DEKU_STICK ? 0.85f : 0.70f;
    *radius = what == VR_HELD_HAMMER ? 0.08f : 0.04f;
    if (x && x->item_shape && x->item_shape(actor, shape) == 1 && shape[0] > 0.15f && shape[0] < 2.5f && shape[2] > 0.005f && shape[2] < 0.2f)
        len = shape[0], *radius = shape[2];
    const float s = what == VR_HELD_SWORD ? vr_body_sword_scale() : 0;
    if (s > 0.2f && s < 2.0f) len *= s, *radius *= s;
    if (vr_phys_mailbox.item_len > 0) len = vr_phys_mailbox.item_len;
    return len;
}

/* ---- the hands' bones: Weapon_L and Weapon_R (vr_body_hand_bones), where what Link holds hangs from, in his fist. Each
   is given to the controller nearest it (within 0.3 m; the model's mirrored pose swaps their names) */
typedef struct { int ok; float p[3], ax[3][3]; } Bone;   // place; its axes (columns), of length 1
static void bones_read(const Hand hd[2], Bone bn[2]) {
    float m[24];
    const int ok = vr_body_hand_bones(m);
    float dist[2] = {0.3f, 0.3f};
    bn[0].ok = bn[1].ok = 0;
    for (int b = 0; b < 2; b++) {
        if (!(ok >> b & 1)) continue;
        const float *r = m + b * 12, p[3] = {r[3], r[7], r[11]};
        for (int h = 0; h < 2; h++) {
            if (!hd[h].ok) continue;
            const float dx = p[0] - hd[h].p[0], dy = p[1] - hd[h].p[1], dz = p[2] - hd[h].p[2], d = sqrtf(dx * dx + dy * dy + dz * dz);
            if (d >= dist[h]) continue;
            dist[h] = d, bn[h].ok = 1, memcpy(bn[h].p, p, 12);
            for (int k = 0; k < 3; k++) {
                bn[h].ax[k][0] = r[k], bn[h].ax[k][1] = r[4 + k], bn[h].ax[k][2] = r[8 + k];
                norm3(bn[h].ax[k]);
            }
        }
    }
}
/* the point a hand grabs and pushes from: its bone (in the fist), else the controller (at the wrist, as the game's hand
   is drawn on it) */
static const float *hand_point(const Hand *hd, const Bone *bn) { return bn->ok ? bn->p : hd->p; }

/* the held item's axis on its hand's bone, from the fist out: the bone's axis (either way) the controller pointed along
   when first seen within 25 degrees of it, kept for that item from then on (what the bone's axes are: not known) */
static int item_axis(int what, const Hand *hd, const Bone *bn, float out[3]) {
    static signed char axis[8] = {-1, -1, -1, -1, -1, -1, -1, -1};
    if (!bn->ok || what < 0 || what >= 8) return 0;
    if (axis[what] < 0) {
        float best = 0;
        int k_best = -1;
        for (int k = 0; k < 3; k++) {
            const float d = -(bn->ax[k][0] * hd->r[6] + bn->ax[k][1] * hd->r[7] + bn->ax[k][2] * hd->r[8]);   // (pointing: -z)
            if (fabsf(d) > fabsf(best)) best = d, k_best = k;
        }
        if (fabsf(best) < 0.9f) return 0;
        axis[what] = (signed char)(k_best * 2 + (best < 0));
        hos_log("vr: push: item %d lies along its bone's %c%c axis (%.2f with the controller)", what, best < 0 ? '-' : '+', "xyz"[k_best], best);
    }
    const float s = axis[what] & 1 ? -1.0f : 1.0f;
    for (int k = 0; k < 3; k++) out[k] = bn->ax[axis[what] >> 1][k] * s;
    return 1;
}

static int segs_build(const Hand hd[2], Seg sg[SEGS]) {
    int on = 0;
    float j[2][3][3];
    int ok[2] = {0, 0};
    if (vr_body_arm_joints(j, ok))
        for (int s = 0; s < 2; s++) {
            if (!ok[s]) continue;
            Seg *up = &sg[s * 2], *fore = &sg[s * 2 + 1];
            memcpy(up->a, j[s][0], 12), memcpy(up->b, j[s][1], 12), up->r = 0.06f, on |= 1 << (s * 2);
            memcpy(fore->a, j[s][1], 12), memcpy(fore->b, j[s][2], 12), fore->r = 0.05f, on |= 1 << (s * 2 + 1);
        }
    Bone bn[2];
    bones_read(hd, bn);
    for (int h = 0; h < 2; h++)
        if (hd[h].ok) {   // (smaller than the grab's reach: a hand can take what it touches)
            Seg *hs = &sg[SEG_HAND + h];
            const float *p = hand_point(&hd[h], &bn[h]);
            memcpy(hs->a, p, 12), memcpy(hs->b, p, 12), hs->r = 0.04f, on |= 1 << (SEG_HAND + h);
        }
    const int what = vr_game_hand_held(), h = vr_body_sword_right() ? 1 : 0;
    float r = 0;
    const float len = item_capsule(what, &r);
    if (len > 0.1f && hd[h].ok) {
        // the item as the game holds it: along its hand's bone from the fist (its swing is the game's, not the
        // controller's); else from the controller where it points (its -z)
        float pt[3], base[3];
        if (item_axis(what, &hd[h], &bn[h], pt)) memcpy(base, bn[h].p, 12);
        else
            for (int k = 0; k < 3; k++) pt[k] = -hd[h].r[6 + k], base[k] = hd[h].p[k];
        Seg *it = &sg[SEG_ITEM];
        for (int k = 0; k < 3; k++) it->a[k] = base[k] + pt[k] * 0.08f, it->b[k] = base[k] + pt[k] * len;
        it->r = r, on |= 1 << SEG_ITEM;
    }
    return on;
}

static struct { uint64_t w, id; uint32_t idx, call; } pushed[16];
static int pushed_n;

/* each touched body moved straight out of what touches it, by gain/s of the overlap (no speed of the arm's carried on), and
   stopped when nothing touches it any more */
static void push_step(Ctx *c, uint64_t frame, const Hand hd[2], const uint64_t *worlds, int nw) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    static uint32_t call;
    call++;
    Seg sg[SEGS];
    float link[3], lr[9];
    const int on = m->push_off || !nw || !player_pose(link, lr) ? 0 : segs_build(hd, sg);
    m->push_segs = (uint32_t)on;
    float lo[3] = {1e9f, 1e9f, 1e9f}, hi[3] = {-1e9f, -1e9f, -1e9f};
    for (int s = 0; s < SEGS; s++)
        if (on >> s & 1)
            for (int k = 0; k < 3; k++)
                lo[k] = fminf(lo[k], fminf(sg[s].a[k], sg[s].b[k]) - 0.8f), hi[k] = fmaxf(hi[k], fmaxf(sg[s].a[k], sg[s].b[k]) + 0.8f);
    const float gain = m->push_gain > 0 ? m->push_gain : 15.0f, vmax = m->push_max > 0 ? m->push_max : 3.0f;
    const float hit_min = m->hit_min > 0 ? m->hit_min : 1.5f, hit_gain = m->hit_gain > 0 ? m->hit_gain : 1.6f,
                hit_max = m->hit_max > 0 ? m->hit_max : 12.0f;
    // each segment's ends' speeds (the item's and the hands' only: they are what hits)
    static Trail seg_tr[SEGS][2];
    float seg_v[SEGS][2][3];
    const int64_t now = hos_now_ns();
    for (int s = 0; s < SEGS; s++) {
        memset(seg_v[s], 0, sizeof seg_v[s]);
        if (!(on >> s & 1) || s < SEG_ITEM) {
            seg_tr[s][0].n = seg_tr[s][1].n = 0;
            continue;
        }
        trail_add(&seg_tr[s][0], now, sg[s].a), trail_add(&seg_tr[s][1], now, sg[s].b);
        trail_vel(&seg_tr[s][0], now, seg_v[s][0]), trail_vel(&seg_tr[s][1], now, seg_v[s][1]);
    }
    for (int i = 0; on && i < nw; i++) {
        const uint64_t chunks = ldh(worlds[i] + 0x48);
        for (uint32_t ci = 0; ci < 128; ci++) {
            const uint64_t chunk = ldh(chunks + ci * 8ull);
            if (!heap_ok(chunk, 42 * 0xC0)) break;
            for (uint32_t jx = 0; jx < 42; jx++) {
                const uint32_t k = ci * 42 + jx;
                const uint64_t rec = chunk + jx * 0xC0ull;
                const uint32_t rid = ld32(rec + 0x58);
                if ((rid & 0xffffff) != k || rid >> 24 == 0) continue;
                float q[3];
                memcpy(q, GP(rec + 0x30), 12);
                if (!(q[0] > lo[0] && q[0] < hi[0] && q[1] > lo[1] && q[1] < hi[1] && q[2] > lo[2] && q[2] < hi[2])) continue;
                uint64_t id;
                const Owner *own = NULL;
                if (!takeable_by(rec, &id, &own) || on_link(rec, link) || just_thrown(worlds[i], id)) continue;
                int taken = 0;
                for (int h = 0; h < 2; h++) taken |= held[h].on && held[h].id == id && held[h].w == worlds[i];
                float mid[3];
                if (taken || !body_mid(rec, mid)) continue;
                float v[3] = {0, 0, 0}, hv[3] = {0, 0, 0}, hit = 0;
                int by = 0, hit_by = -1;
                for (int s = 0; s < SEGS; s++) {
                    if (!(on >> s & 1)) continue;
                    float p[3], n[3], nl = 0, dummy;
                    const float t = seg_closest(&sg[s], mid, p);
                    const float gap = body_gap(rec, p, &dummy);
                    if (gap < 0 || gap >= sg[s].r) continue;
                    for (int x = 0; x < 3; x++) n[x] = mid[x] - p[x], nl += n[x] * n[x];
                    if (nl < 1e-6f) continue;
                    norm3(n);
                    for (int x = 0; x < 3; x++) v[x] += n[x] * (sg[s].r - gap) * gain;
                    by |= 1 << s;
                    // a hit: the touching point's own speed into the body (the ends' speeds mixed by where it touches)
                    float sv[3], vn = 0;
                    for (int x = 0; x < 3; x++) sv[x] = seg_v[s][0][x] + (seg_v[s][1][x] - seg_v[s][0][x]) * t, vn += sv[x] * n[x];
                    // (a hand needs twice the speed: one reaching to take a body should not knock it off)
                    if (s >= SEG_ITEM && vn > (s == SEG_ITEM ? hit_min : 2 * hit_min) && vn > hit) {   // the fastest wins: along the touch, a third of the sideways speed
                        hit = vn, hit_by = s;
                        for (int x = 0; x < 3; x++) hv[x] = n[x] * vn * hit_gain + (sv[x] - n[x] * vn) * 0.33f;
                    }
                }
                if (hit_by >= 0) {   // (sent off, not pushed: the push keeps off it for 1 s, as after a throw)
                    float hl = sqrtf(hv[0] * hv[0] + hv[1] * hv[1] + hv[2] * hv[2]);
                    if (hl > hit_max)
                        for (int x = 0; x < 3; x++) hv[x] *= hit_max / hl;
                    hl = fminf(hl, hit_max);
                    if (!(ld32(rec + 0x50) & 8)) game_call(c, BODY_SET_TYPE, frame, worlds[i], id, 2, 1, 1);
                    impact_arm(rec, hl, "hit");
                    set_vel(c, frame, worlds[i], id, hv);
                    loose_add(worlds[i], id, k, 1);
                    m->hits++;
                    hos_log("vr: push: body %#x of %s hit by %s at %.2f m/s into it: sent at %.2f %.2f %.2f m/s", rid,
                            own ? own->name : "no actor", hit_by == SEG_ITEM ? "the item" : "a hand", hit, hv[0], hv[1], hv[2]);
                    continue;
                }
                const float len = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
                if (len < 0.02f) continue;
                if (len > vmax)
                    for (int x = 0; x < 3; x++) v[x] *= vmax / len;
                const uint32_t flags = ld32(rec + 0x50);
                if (!(flags & 8)) {   // (bit 3: awake)
                    game_call(c, BODY_SET_TYPE, frame, worlds[i], id, 2, 1, 1);
                    if (rid != m->push_id)
                        hos_log("vr: push: body %#x of %s (flags %#x) moved at %.2f %.2f %.2f m/s, touched by %s%s%s", rid,
                                own ? own->name : "no actor", flags, v[0], v[1], v[2], by & 1 << SEG_ITEM ? "the item " : "",
                                by & (3 << SEG_HAND) ? "a hand " : "", by & 0xf ? "an arm" : "");
                }
                set_vel(c, frame, worlds[i], id, v);
                loose_add(worlds[i], id, k, 0);
                m->pushes++, m->push_id = rid;
                int e = 0;
                while (e < pushed_n && !(pushed[e].w == worlds[i] && pushed[e].id == id)) e++;
                if (e == pushed_n && pushed_n < 16) pushed_n++;
                if (e < pushed_n) pushed[e].w = worlds[i], pushed[e].id = id, pushed[e].idx = k, pushed[e].call = call;
            }
        }
    }
    const float zero[3] = {0, 0, 0};
    for (int e = 0; e < pushed_n;) {
        if (pushed[e].call == call) {
            e++;
            continue;
        }
        const uint64_t rec = body_at(pushed[e].w, pushed[e].idx);
        uint64_t id;
        int taken = 0;
        for (int h = 0; h < 2; h++) taken |= held[h].on && held[h].id == pushed[e].id && held[h].w == pushed[e].w;
        if (rec && !taken && takeable(rec, &id) && id == pushed[e].id && !just_thrown(pushed[e].w, id)) set_vel(c, frame, pushed[e].w, id, zero);
        pushed[e] = pushed[--pushed_n];
    }
}

/* Show physics shapes (the VR options' Debug row, vk_xr.cpp make_phys): the push's capsules as push_step has them (kind 0
   an arm, 1 a hand, 2 the item) and each hand's grab reach, a ball of `reach` at the point the grab measures from (3, 4
   near a body to take, 5 holding one). Sent each step; the renderer draws them only while the row is on */
static void shapes_send(const MkwVkXr *x, const Hand hd[2], const Bone bn[2], float reach, int close_by, int mark) {
    if (!x || !x->phys_shapes) return;
    float caps[16][8];
    int n = 0;
    Seg sg[SEGS];
    const int on = segs_build(hd, sg);
    for (int s = 0; s < SEGS; s++) {
        if (!(on >> s & 1)) continue;
        float *o = caps[n++];
        memcpy(o, sg[s].a, 12), o[3] = sg[s].r, memcpy(o + 4, sg[s].b, 12);
        o[7] = s < SEG_ITEM ? 0.0f : s == SEG_ITEM ? 2.0f : 1.0f;
    }
    for (int h = 0; h < 2; h++) {
        if (!hd[h].ok) continue;
        float *o = caps[n++];
        const float *p = hand_point(&hd[h], &bn[h]);
        memcpy(o, p, 12), o[3] = reach, memcpy(o + 4, p, 12);
        o[7] = held[h].on ? 5.0f : (close_by | mark) >> h & 1 ? 4.0f : 3.0f;
    }
    x->phys_shapes(&caps[0][0], n);
}

static void grab_step(Ctx *c, uint64_t frame) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    Hand hd[2];
    int grips = 0;
    const MkwVkXr *x = rx_xr();
    loose_step();
    const int have = !m->grab_off && hands_read(hd, &grips);
    if (!have) {
        for (int h = 0; h < 2; h++)
            if (held[h].on) grab_release(c, frame, h, 0);
        if (x && x->grab_hands && m->grab_near) x->grab_hands(0);
        if (x && x->phys_shapes) x->phys_shapes(NULL, 0);
        m->grab_near = 0, grips_was = 0;
        return;
    }
    uint64_t worlds[4];
    const int nw = worlds_find(worlds);
    m->worlds_n = (uint32_t)nw;
    for (int i = 0; i < 4; i++) m->worlds[i] = i < nw ? worlds[i] : 0;
    owners_build();
    const float reach = m->grab_reach > 0 ? m->grab_reach : 0.06f;   // (from the fist's bone: half the 0.12 it was from the wrist)
    Bone bn[2];
    bones_read(hd, bn);
    int mark = 0, close_by = 0;   // (not "near": windows.h defines it)
    for (int h = 0; h < 2; h++) {
        const int grip = grips >> h & 1, fresh = grip && !(grips_was >> h & 1);
        if (held[h].on) {
            if (!grip || !hd[h].ok) grab_release(c, frame, h, hd[h].ok);
            else grab_hold(c, frame, h, &hd[h]), mark |= held[h].on << h;
            continue;
        }
        if (!hd[h].ok || !nw || (grip && !fresh)) continue;   // (a grip held for something else keeps its role)
        uint64_t w = 0, id = 0;
        uint32_t idx = 0;
        Miss miss;
        const uint64_t rec = grab_near(worlds, nw, hand_point(&hd[h], &bn[h]), reach, &w, &id, &idx, &miss);
        if (!rec) {
            if (fresh && miss.id)
                hos_log("vr: grab: the %s hand's grip took nothing: body %#x of %s (flags %#x%s) %.2f m from its outside", h ? "right" : "left",
                        miss.id, miss.name, miss.flags, miss.taken ? ", held" : "", miss.gap);
            else if (fresh)
                hos_log("vr: grab: the %s hand's grip took nothing: no body within 1 m (%d world(s))", h ? "right" : "left", nw);
            continue;
        }
        close_by |= 1 << h, mark |= 1 << h;
        if (!fresh) continue;
        float bp[3], br[9], d[3], lo[3] = {0, 0, 0}, hi[3] = {0, 0, 0}, mid, link[3] = {0, 0, 0}, lr[9];
        body_pose(rec, bp, br), body_box(rec, lo, hi), player_pose(link, lr);
        for (int k = 0; k < 3; k++) d[k] = bp[k] - hd[h].p[k];
        for (int k = 0; k < 3; k++) held[h].off[k] = hd[h].r[k * 3] * d[0] + hd[h].r[k * 3 + 1] * d[1] + hd[h].r[k * 3 + 2] * d[2];
        mat_tmul(hd[h].r, br, held[h].turn);
        held[h].on = 1, held[h].w = w, held[h].id = id, held[h].idx = idx, held[h].tr.n = 0;
        memset(held[h].spin, 0, sizeof held[h].spin);
        game_call(c, BODY_SET_TYPE, frame, w, id, 2, 1, 1);   // (type 2: Havok moves it, the floor stops it)
        m->grab_world[h] = w, m->grab_id[h] = id, m->grabs++;
        const float gap = body_gap(rec, hand_point(&hd[h], &bn[h]), &mid);
        const Owner *own = owner_of(rec);
        const uint64_t rb = rb_of(rec);
        hos_log("vr: grab: the %s hand (%.2f %.2f %.2f) took %#llx of %s, flags %#x (world %#llx) at %.2f %.2f %.2f, box %.2f %.2f %.2f to %.2f %.2f "
                "%.2f: %.2f m from it, %.2f from its middle; Link at %.2f %.2f %.2f; rb %#llx, rb+0x70 %#x", h ? "right" : "left", hd[h].p[0], hd[h].p[1],
                hd[h].p[2], (unsigned long long)id, own ? own->name : "no actor", ld32(rec + 0x50), (unsigned long long)w, bp[0], bp[1], bp[2], lo[0], lo[1], lo[2], hi[0], hi[1],
                hi[2], gap, mid, link[0], link[1], link[2], (unsigned long long)rb, rb ? ld32(rb + 0x70) : 0);
        grab_hold(c, frame, h, &hd[h]);
    }
    push_step(c, frame, hd, worlds, nw);
    shapes_send(x, hd, bn, reach, close_by, mark);
    m->grab_near = (uint32_t)close_by;
    if (x && x->grab_hands && !m->fake_on) x->grab_hands(mark);
    grips_was = grips;
}

void hos_vr_physics(Ctx *c) {
    VrPhysMailbox *m = &vr_phys_mailbox;
    m->calls++;
    const uint64_t frame = (c->x[31] - 0x400) & ~0xfULL, vec = frame + 0x200;
    if (m->hold_on) hold_step(c, frame);
    else if (m->hold_frames) m->hold_frames = 0, release(c, frame);
    else {   // (the game calls this from up to 6 threads at once, about 157 times a second: one at a time here, the rest skip)
        static volatile int busy;
        if (!__atomic_exchange_n(&busy, 1, __ATOMIC_ACQUIRE)) grab_step(c, frame), __atomic_store_n(&busy, 0, __ATOMIC_RELEASE);
    }
    const uint32_t req = m->req;
    if (req == m->done) return;
    memcpy(GP(vec), m->vec, sizeof m->vec);
    if (!a64_lookup(m->fn)) m->status = -1, m->ret = 0;
    else m->ret = game_call(c, m->fn, frame, m->a0, m->a1, m->a2_raw ? m->a2 : vec, m->a3, m->a4), m->status = 1;
    __atomic_store_n(&m->done, req, __ATOMIC_RELEASE);
}
