/* (Triforce VR) Link's body in first person (vr_game.h): his arms on the hand controllers and his head hidden, VR_BODY "arms"
   (the VR tab's Body row; "hidden" keeps first person's fade of all of him, vr_game.c hide_link).

   - The arms: a two-bone IK per arm (upper arm, forearm, wrist) to where the controller is in the game's world
     (gpu/vk/vk_xr.cpp vk_xr_hands: the LOCAL space as the head's view maps it at the last camera update), the elbow toward a
     pole down, out and back, the hand turned as the controller is held. Written as the bones' local matrices right after
     the late bone pass f_8030a320 (nx2/oot_patches.py patch_after_anim: hos_oot_after_anim), the last to write them before
     the model's world matrices are made from them (f_801d7ac0); found with a guard-page watch on Arm_1_L's slot.
   - The head: its bone scaled to a thousandth and sunk into his chest (his hair's and hat's physics strands start there and
     keep their length; inside the body they are hidden), and the head's and shoulders' materials hidden the game's way
     (the model's part instance: find +0xd0, set visible +0x1c8, as OneshotModelSetMaterialVisible f_829837f0).

   Layouts (learned with dumps of the bones): a bone's local slot ([instance +0xf8] +0x18, 0x60 bytes a bone) and world
   entry ([instance +0xf8] +0x20, 64 bytes a bone, relative to the instance's origin at +0x2d0) are column-major 3x4 (the X,
   Y, Z axes, then the place), in metres; the arm bones run along their own +X on the left, -X on the right (upper arm
   0.236 m, forearm 0.245 m on adult Link); the model's +x is Link's left, +y up, +z ahead. A bone's id comes from
   f_801d3620(model, &name) (x8: {s16 part, s16 bone}); a local is set with f_80e6a110(model, &id, &matrix). Link's model:
   f_80994de0(actor). Ported from Ezra's Triforce VR mod (v0.4.0), 2026-11-19. */
#include "vr_game.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "../gpu/vk/vk_api.h"

const MkwVkXr *rx_xr(void);   /* (rx_backend.c) */

static const char *body_cfg(const char *key) {
    const MkwVkXr *x = rx_xr();
    return x && x->cfg ? x->cfg(key) : "";
}
static int body_arms(void) { return !strcmp(body_cfg("VR_BODY"), "arms"); }
/* the sword's hand in VR: the last two-grip draw's (VR_SWORD_HAND), else the Handedness row's; 1 right */
static int vr_sword_right(void) {
    const char *live = body_cfg("VR_SWORD_HAND");
    return live[0] ? !strcmp(live, "right") : !strcmp(body_cfg("VR_HANDEDNESS"), "right");
}

/* ---- the game's memory, and calls into its code ---- */
static int plausible(uint64_t a, uint64_t n) {
    /* ((Triforce VR) no wrap-around in either: a pointer of -1 (a thing half made, as at an age switch) passed the image's test) */
    return (a >= HOS_HEAP_BASE && a + n > a && a + n <= (uint64_t)HOS_SPACE_END) || (a >= hos_image_base && a + n > a && a + n <= hos_image_end);
}
static float ld_f(Ctx *c, uint64_t a) {
    const uint32_t b = recomp_load32(c, a);
    float f;
    memcpy(&f, &b, 4);
    return f;
}
static void st_f(Ctx *c, uint64_t a, double v) {
    const float f = (float)v;
    uint32_t b;
    memcpy(&b, &f, 4);
    recomp_store32(c, a, b);
}
static uint64_t vr_call(Ctx *c, uint64_t fn, uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x8) {
    const A64Fn f = a64_lookup(fn);
    if (!f) return 0;
    const Ctx saved = *c;
    c->x[0] = x0, c->x[1] = x1, c->x[2] = x2, c->x[8] = x8;
    f(c);
    const uint64_t r = c->x[0];
    *c = saved;
    return r;
}
static int bone_id(Ctx *c, uint64_t model, const char *name, uint32_t *id) {
    const uint64_t sp = (c->x[31] - 128) & ~15ULL;   /* (the name, a pointer to it and the result, on the guest's stack) */
    const size_t n = strlen(name);
    if (n > 40) return 0;
    for (size_t i = 0; i <= n; i++) recomp_store8_sp(c, sp + 16 + i, (uint8_t)name[i]);
    recomp_store64_sp(c, sp, sp + 16);
    recomp_store64_sp(c, sp + 8, 0xffffffffffffffffULL);
    Ctx call = *c;
    call.x[31] = sp;   /* (the callee's frame below ours) */
    vr_call(&call, 0x801d3620ULL, model, sp, 0, sp + 8);
    *id = recomp_load32(c, sp + 8);
    return *id != 0xffffffffu;
}
static uint64_t bone_slot(Ctx *c, uint64_t model, uint32_t id) {   /* (the bone's 0x60-byte local slot, or 0) */
    const int part = (int16_t)(id & 0xffff), bone = (int16_t)(id >> 16);
    if (part < 0 || bone < 0 || bone > 400 || part >= (int)recomp_load32(c, model + 0x20)) return 0;
    uint64_t p = recomp_load64(c, model + 0x28);
    if (!plausible(p + part * 8, 8)) return 0;
    p = recomp_load64(c, p + part * 8);
    if (!plausible(p, 8)) return 0;
    const uint64_t instance = recomp_load64(c, p);
    if (!plausible(instance + 0xf8, 8)) return 0;
    p = recomp_load64(c, instance + 0xf8);
    if (!plausible(p + 0x18, 8)) return 0;
    p = recomp_load64(c, p + 0x18);
    return plausible(p + bone * 0x60, 0x60) ? p + bone * 0x60 : 0;
}
static void bone_write(Ctx *c, uint64_t model, uint32_t id, double out[3][4]) {
    const uint64_t sp = (c->x[31] - 128) & ~15ULL;
    recomp_store32_sp(c, sp, id);
    for (int r = 0; r < 3; r++)
        for (int k = 0; k < 4; k++) {
            const float f = (float)out[r][k];
            uint32_t b;
            memcpy(&b, &f, 4);
            recomp_store32_sp(c, sp + 16 + (r * 4 + k) * 4, b);
        }
    Ctx call = *c;
    call.x[31] = sp;
    vr_call(&call, 0x80e6a110ULL, model, sp, sp + 16, 0);
}

/* ---- 3x4 transforms (m[r][k]: column k: 0..2 the axes, 3 the place) and 3x3 turns ---- */
typedef struct { double m[3][4]; } Xf;
static void xf_load(Ctx *c, uint64_t a, Xf *x) {
    for (int r = 0; r < 3; r++)
        for (int k = 0; k < 4; k++) x->m[r][k] = ld_f(c, a + k * 16 + r * 4);
}
static void xf_mul(const Xf *a, const Xf *b, Xf *o) {   /* (o = a b) */
    Xf t;
    for (int r = 0; r < 3; r++)
        for (int k = 0; k < 4; k++) {
            double s = k == 3 ? a->m[r][3] : 0;
            for (int j = 0; j < 3; j++) s += a->m[r][j] * b->m[j][k];
            t.m[r][k] = s;
        }
    *o = t;
}
static int xf_inv(const Xf *a, Xf *o) {   /* (any invertible 3x3, not only a rotation) */
    const double (*m)[4] = a->m;
    const double det = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
                       m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    if (fabs(det) < 1e-12) return 0;
    Xf t;
    t.m[0][0] = (m[1][1] * m[2][2] - m[1][2] * m[2][1]) / det, t.m[0][1] = (m[0][2] * m[2][1] - m[0][1] * m[2][2]) / det;
    t.m[0][2] = (m[0][1] * m[1][2] - m[0][2] * m[1][1]) / det, t.m[1][0] = (m[1][2] * m[2][0] - m[1][0] * m[2][2]) / det;
    t.m[1][1] = (m[0][0] * m[2][2] - m[0][2] * m[2][0]) / det, t.m[1][2] = (m[0][2] * m[1][0] - m[0][0] * m[1][2]) / det;
    t.m[2][0] = (m[1][0] * m[2][1] - m[1][1] * m[2][0]) / det, t.m[2][1] = (m[0][1] * m[2][0] - m[0][0] * m[2][1]) / det;
    t.m[2][2] = (m[0][0] * m[1][1] - m[0][1] * m[1][0]) / det;
    for (int r = 0; r < 3; r++) t.m[r][3] = -(t.m[r][0] * m[0][3] + t.m[r][1] * m[1][3] + t.m[r][2] * m[2][3]);
    *o = t;
    return 1;
}
static void xf_pt(const Xf *a, const double p[3], double o[3]) {
    double t[3];
    for (int r = 0; r < 3; r++) t[r] = a->m[r][0] * p[0] + a->m[r][1] * p[1] + a->m[r][2] * p[2] + a->m[r][3];
    memcpy(o, t, sizeof t);
}
static void xf_dir(const Xf *a, const double p[3], double o[3]) {
    double t[3];
    for (int r = 0; r < 3; r++) t[r] = a->m[r][0] * p[0] + a->m[r][1] * p[1] + a->m[r][2] * p[2];
    memcpy(o, t, sizeof t);
}
static double v3_dot(const double a[3], const double b[3]) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
static double v3_len(const double a[3]) { return sqrt(v3_dot(a, a)); }
static void v3_cross(const double a[3], const double b[3], double o[3]) {
    const double t[3] = {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
    memcpy(o, t, sizeof t);
}
static int v3_norm(double a[3]) {
    const double l = v3_len(a);
    if (l < 1e-9) return 0;
    a[0] /= l, a[1] /= l, a[2] /= l;
    return 1;
}
typedef double M3[3][3];
static void m3_axis(const double n[3], double ang, M3 R) {   /* (Rodrigues: about the unit axis n) */
    const double c = cos(ang), s = sin(ang), t = 1 - c;
    R[0][0] = t * n[0] * n[0] + c, R[0][1] = t * n[0] * n[1] - s * n[2], R[0][2] = t * n[0] * n[2] + s * n[1];
    R[1][0] = t * n[0] * n[1] + s * n[2], R[1][1] = t * n[1] * n[1] + c, R[1][2] = t * n[1] * n[2] - s * n[0];
    R[2][0] = t * n[0] * n[2] - s * n[1], R[2][1] = t * n[1] * n[2] + s * n[0], R[2][2] = t * n[2] * n[2] + c;
}
static void m3_between(const double from[3], const double to[3], M3 R) {   /* (the shortest turn taking from onto to) */
    double a[3] = {from[0], from[1], from[2]}, b[3] = {to[0], to[1], to[2]}, n[3];
    if (!v3_norm(a) || !v3_norm(b)) {
        m3_axis((double[3]){1, 0, 0}, 0, R);
        return;
    }
    v3_cross(a, b, n);
    const double s = v3_len(n), cth = v3_dot(a, b);
    if (s < 1e-9) {   /* (parallel: nothing; opposite: half a turn about any perpendicular) */
        double p[3] = {0, 1, 0};
        if (fabs(a[1]) > 0.9) p[0] = 1, p[1] = 0;
        v3_cross(a, p, n), v3_norm(n);
        m3_axis(n, cth > 0 ? 0 : 3.14159265358979, R);
        return;
    }
    n[0] /= s, n[1] /= s, n[2] /= s;
    m3_axis(n, atan2(s, cth), R);
}
static void m3_of(const Xf *x, M3 R) {
    for (int r = 0; r < 3; r++)
        for (int k = 0; k < 3; k++) R[r][k] = x->m[r][k];
}
static void m3_set(Xf *x, M3 R) {
    for (int r = 0; r < 3; r++)
        for (int k = 0; k < 3; k++) x->m[r][k] = R[r][k];
}
static void m3_mul(M3 a, M3 b, M3 o) {
    M3 t;
    for (int r = 0; r < 3; r++)
        for (int k = 0; k < 3; k++) t[r][k] = a[r][0] * b[0][k] + a[r][1] * b[1][k] + a[r][2] * b[2][k];
    memcpy(o, t, sizeof t);
}
static void m3_t(M3 a, M3 o) {
    M3 t;
    for (int r = 0; r < 3; r++)
        for (int k = 0; k < 3; k++) t[r][k] = a[k][r];
    memcpy(o, t, sizeof t);
}
static void m3_v(M3 a, const double v[3], double o[3]) {
    double t[3];
    for (int r = 0; r < 3; r++) t[r] = a[r][0] * v[0] + a[r][1] * v[1] + a[r][2] * v[2];
    memcpy(o, t, sizeof t);
}

/* Two-bone IK, all in the shoulder's parent's (the clavicle's) frame: L1 the upper arm's local, L2 the forearm's, L3 the
   wrist's. The wrist to T (clamped to the arm's reach, or both bones stretched alike up to `stretch` times), the elbow
   toward the pole P, and, when D (the controller's pointing) and N (its palm) are given, the hand turned as the controller
   is held, then by `off` in the hand's own frame. Only the rotations change (and the stretch); rest[] the bones' own
   lengths, the shortest seen, so a second pass in a frame cannot stretch a stretched arm. */
static void ik_arm(Xf *L1, Xf *L2, Xf *L3, const double T[3], const double P[3], const double *D, double side, const double *N,
                   M3 off, double stretch, const double rest[2]) {
    const double S[3] = {L1->m[0][3], L1->m[1][3], L1->m[2][3]};
    double t2[3] = {L2->m[0][3], L2->m[1][3], L2->m[2][3]}, t3[3] = {L3->m[0][3], L3->m[1][3], L3->m[2][3]};
    double a = v3_len(t2), b = v3_len(t3);
    if (a < 1e-4 || b < 1e-4) return;
    if (rest && rest[0] > 0.01 && rest[1] > 0.01) {   /* (back to the bones' own lengths first: idempotent passes) */
        for (int i = 0; i < 3; i++) t2[i] *= rest[0] / a, t3[i] *= rest[1] / b, L2->m[i][3] = t2[i], L3->m[i][3] = t3[i];
        a = rest[0], b = rest[1];
    }
    {   /* (a target past his reach stretches both bones alike, up to `stretch` times their length, so the hand still meets
           the controller: his arms are shorter than a player's) */
        const double dv0[3] = {T[0] - S[0], T[1] - S[1], T[2] - S[2]};
        const double reach = (a + b) * 0.995, d0 = v3_len(dv0);
        if (stretch > 1 && d0 > reach) {
            const double k = d0 / reach < stretch ? d0 / reach : stretch;
            for (int i = 0; i < 3; i++) t2[i] *= k, t3[i] *= k, L2->m[i][3] = t2[i], L3->m[i][3] = t3[i];
            a *= k, b *= k;
        }
    }
    M3 R1, R2, R3, Rn, tmp, R1t;
    m3_of(L1, R1), m3_of(L2, R2), m3_of(L3, R3);
    double dv[3] = {T[0] - S[0], T[1] - S[1], T[2] - S[2]};
    const double d = v3_len(dv);
    const double lo = fabs(a - b) + 0.01, hi = (a + b) * 0.995;
    if (d < 1e-6) return;
    const double dc = d < lo ? lo : d > hi ? hi : d;
    /* 1. the elbow's bend: the angle at the elbow that puts the wrist dc from the shoulder */
    double e[3], w[3], u[3], v[3], n[3];
    m3_v(R1, t2, e);   /* (the elbow, from the shoulder) */
    m3_mul(R1, R2, tmp);
    m3_v(tmp, t3, w);
    w[0] += e[0], w[1] += e[1], w[2] += e[2];   /* (the wrist, from the shoulder) */
    u[0] = -e[0], u[1] = -e[1], u[2] = -e[2];   /* (elbow to shoulder) */
    v[0] = w[0] - e[0], v[1] = w[1] - e[1], v[2] = w[2] - e[2];   /* (elbow to wrist) */
    v3_cross(u, v, n);
    if (!v3_norm(n)) {   /* (a straight arm: bend it in the plane of the arm and the pole) */
        v3_cross(u, P, n);
        if (!v3_norm(n)) return;
    }
    double cu = v3_dot(u, v) / (v3_len(u) * v3_len(v));
    cu = cu > 1 ? 1 : cu < -1 ? -1 : cu;
    double cd = (a * a + b * b - dc * dc) / (2 * a * b);
    cd = cd > 1 ? 1 : cd < -1 ? -1 : cd;
    m3_axis(n, acos(cd) - acos(cu), Rn);   /* (in the clavicle's frame, about the elbow) */
    m3_t(R1, R1t);
    m3_mul(Rn, R1, tmp), m3_mul(R1t, tmp, tmp), m3_mul(tmp, R2, R2);   /* (R2 = R1^T Rn R1 R2) */
    /* 2. the swing: the shoulder turned so the wrist lies along the way to the target */
    m3_mul(R1, R2, tmp);
    m3_v(tmp, t3, w);
    m3_v(R1, t2, e);
    w[0] += e[0], w[1] += e[1], w[2] += e[2];
    m3_between(w, dv, Rn);
    m3_mul(Rn, R1, R1);
    /* 3. the elbow turned about the shoulder-to-target line toward the pole */
    double ax[3] = {dv[0], dv[1], dv[2]};
    v3_norm(ax);
    m3_v(R1, t2, e);
    double ep[3], pp[3];
    const double de = v3_dot(e, ax), dp = v3_dot(P, ax);
    for (int i = 0; i < 3; i++) ep[i] = e[i] - ax[i] * de, pp[i] = P[i] - ax[i] * dp;
    if (v3_norm(ep) && v3_norm(pp)) {
        double cr[3];
        v3_cross(ep, pp, cr);
        m3_axis(ax, atan2(v3_dot(cr, ax), v3_dot(ep, pp)), Rn);
        m3_mul(Rn, R1, R1);
    }
    /* 4. the hand as the controller is held: its own axis (+X the left, -X the right) along D, its Z along the palm's facing
       on the left, against it on the right (the bones are mirrored), then `off` in the hand's own frame. Without N, only the
       least turn onto D. */
    if (D && N) {
        double x[3] = {side * D[0], side * D[1], side * D[2]}, z[3] = {side * N[0], side * N[1], side * N[2]}, y[3];
        if (v3_norm(x)) {
            const double dz = v3_dot(z, x);
            for (int i = 0; i < 3; i++) z[i] -= x[i] * dz;
            if (v3_norm(z)) {
                v3_cross(z, x, y);   /* (right-handed: x cross y = z) */
                M3 W = {{x[0], y[0], z[0]}, {x[1], y[1], z[1]}, {x[2], y[2], z[2]}}, R12, R12t;
                m3_mul(W, off, W);
                m3_mul(R1, R2, R12);
                m3_t(R12, R12t);
                m3_mul(R12t, W, R3);   /* (R1 R2 R3 = W: the hand's turn in the clavicle's frame) */
                D = NULL;
            }
        }
    }
    if (D) {
        M3 R12, R12t;
        m3_mul(R1, R2, R12);
        m3_mul(R12, R3, tmp);
        double h[3];
        m3_v(tmp, (double[3]){side, 0, 0}, h);
        m3_between(h, D, Rn);
        m3_t(R12, R12t);
        m3_mul(Rn, R12, tmp), m3_mul(R12t, tmp, tmp), m3_mul(tmp, R3, R3);   /* (R3 = R12^T Rn R12 R3) */
    }
    m3_set(L1, R1), m3_set(L2, R2), m3_set(L3, R3);
}

/* ---- Link's bones, found in his movement update (vr_body_lift) and cached ---- */
enum { OB_ROOT, OB_CLAV_L, OB_ARM1_L, OB_ARM2_L, OB_WRIST_L, OB_CLAV_R, OB_ARM1_R, OB_ARM2_R, OB_WRIST_R, OB_HEAD, OB_N };
static const char *const ob_names[OB_N] = {"Root",       "Clavicle_L", "Arm_1_L", "Arm_2_L", "Wrist_L",
                                           "Clavicle_R", "Arm_1_R",    "Arm_2_R", "Wrist_R", "Head"};
static struct {
    uint64_t actor, model, origin;   /* (origin: the instance's +0x2d0, the world entries' zero) */
    uint32_t id[OB_N];
    uint64_t slot[OB_N], world[OB_N];
    uint64_t neck_world;   /* (the head's parent, Neck: its world entry, for sinking the head; 0 if none) */
    uint64_t cap_world[7];   /* ((Triforce VR) the cap's physics bones Ph_Cap_1..7: their world entries, 0 for one not found */
    double rest[2][2];     /* (each arm's forearm and hand offsets' own lengths (side 0 left), the shortest seen) */
    int valid;
} ob;
static SRWLOCK ob_lock = SRWLOCK_INIT;
static void pose_cache(Ctx *c, uint64_t actor) {
    const uint64_t model = vr_call(c, 0x80994de0ULL, actor, 0, 0, 0);
    static int64_t tried;   /* (a model whose bones were not all found: looked at again every 2 s) */
    const int64_t now = hos_now_ns();
    if (model == ob.model && actor == ob.actor && (ob.valid || now - tried < 2000000000LL)) return;
    if (!TryAcquireSRWLockExclusive(&ob_lock)) return;
    tried = now;
    ob.valid = 0, ob.actor = actor, ob.model = model;
    int ok = model && plausible(model, 0x30);
    for (int i = 0; ok && i < OB_N; i++) {
        ok = bone_id(c, model, ob_names[i], &ob.id[i]);
        const uint64_t slot = ok ? bone_slot(c, model, ob.id[i]) : 0;
        ok = slot != 0;
        if (!ok) break;
        uint64_t inst = recomp_load64(c, recomp_load64(c, model + 0x28) + (int16_t)(ob.id[i] & 0xffff) * 8);
        inst = recomp_load64(c, inst);
        ob.slot[i] = slot;
        ob.world[i] = recomp_load64(c, recomp_load64(c, inst + 0xf8) + 0x20) + (uint64_t)(int16_t)(ob.id[i] >> 16) * 64;
        ob.origin = inst + 0x2d0;
        ok = plausible(ob.world[i], 64);
    }
    memset(ob.rest, 0, sizeof ob.rest);
    ob.neck_world = 0;
    for (int n = 0; n < 7; n++) {   /* (optional: the cap, collapsed into the hidden head in first person, cap_hide) */
        char name[16];
        uint32_t id;
        snprintf(name, sizeof name, "Ph_Cap_%d", n + 1);
        ob.cap_world[n] = 0;
        if (!ok || !bone_id(c, model, name, &id)) continue;
        uint64_t inst = recomp_load64(c, recomp_load64(c, model + 0x28) + (int16_t)(id & 0xffff) * 8);
        inst = recomp_load64(c, inst);
        const uint64_t w = recomp_load64(c, recomp_load64(c, inst + 0xf8) + 0x20) + (uint64_t)(int16_t)(id >> 16) * 64;
        if (plausible(w, 64)) ob.cap_world[n] = w;
    }
    for (int n = 0; ok && n < 3 && !ob.neck_world; n++) {   /* (optional: without it the head is only shrunk; Link has "Neck") */
        uint32_t nid;
        if (!bone_id(c, model, n == 0 ? "Neck" : n == 1 ? "Neck_2" : "Neck_1", &nid) || !bone_slot(c, model, nid)) continue;
        uint64_t inst = recomp_load64(c, recomp_load64(c, model + 0x28) + (int16_t)(nid & 0xffff) * 8);
        inst = recomp_load64(c, inst);
        const uint64_t w = recomp_load64(c, recomp_load64(c, inst + 0xf8) + 0x20) + (uint64_t)(int16_t)(nid >> 16) * 64;
        if (plausible(w, 64)) ob.neck_world = w;
    }
    ob.valid = ok;
    hos_log("vr: body: Link %#llx, model %#llx: %s%s", (unsigned long long)actor, (unsigned long long)model,
            ok ? "bones found" : "bones not all found (the arms wait)", ok && !ob.neck_world ? " (no neck bone: the head not sunk)" : "");
    ReleaseSRWLockExclusive(&ob_lock);
}
static float ob_last[OB_N][12];   /* (each watched slot's matrix as the hook last left it) */
static int ob_owned[OB_N];
static int ob_unchanged(Ctx *c, int i) {   /* (the slot as the hook left it: the animation has not been back) */
    if (!ob_owned[i]) return 0;
    for (int k = 0; k < 12; k++)
        if (ld_f(c, ob.slot[i] + 0x20 + (k / 3) * 16 + (k % 3) * 4) != ob_last[i][k]) return 0;
    return 1;
}
static void ob_snap(Ctx *c, int i) {   /* (what the slot holds now, to tell the animation's next write) */
    for (int k = 0; k < 12; k++) ob_last[i][k] = ld_f(c, ob.slot[i] + 0x20 + (k / 3) * 16 + (k % 3) * 4);
    ob_owned[i] = 1;
}
static void ob_write(Ctx *c, int i, Xf *x) { bone_write(c, ob.model, ob.id[i], x->m); }

/* ---- the head's and shoulders' materials ---- */
/* (names from romfs Model/Player_Adult and Player_Child .bfres, whose meshes are named mesh__material; a name a model lacks
   is skipped. The hair and the cap are physics-driven bones the head's own bone does not carry: they stay at the eyes'
   height with the head sunk, so hiding them by material is the sure way. Adult: the cap is Hood_A (Mt_Vest) and Hood_B
   (Mt_Angin), with Feather (Mt_Feather) on it, which swung across the view running, turning and rolling (found with a
   watch of his bones in front of the eyes: the cap's Ph_Cap_1..7 came within 6-26 cm); the shoulders' cape, collar and belts
   (Mt_Angin_Acs*, Mt_Leater_Upper, Mt_Leather_Upper_Metal) sat at the view's lower edge. Young Link: the cap Head_Band
   (Mt_Cloth) and its knot, the collar Angin_Parts_Collar_R (Mt_Cloth_Parts), the feather, the shoulder belt).
   ((Triforce VR, 11-26) Only the head's own now: the adult's tunic is the cap's meshes (Hood_A Mt_Vest, Hood_B Mt_Angin), so
   hiding those hid his whole tunic; the cap goes by its bones instead (cap_hide). Young Link's back lacing (String_Back_1,
   Mt_Vest), collar and shoulder belt shown too, the tunic whole) */
static const char *const head_materials[] = {
    "Mt_Hairs",        "Mt_Face",         "Mt_Face_SoftEdge", "Mt_Face_Eyelid", "Mt_Eye_Outer", "Mt_Eye_Inner",
    "Mt_Eyelashes",    "Mt_Eyelashes_01", "Mt_Eyelashes_02",  "Mt_Eyelashes_03", "Mt_Eyeshadow", "Mt_EyeShadow_test",
    "Mt_Eyebrow",      "Mt_Teeth",        "Mt_Cloth",         "Mt_Cloth_Parts_AlphaMask", "Mt_Feather"};
/* hidden (want) or shown again: every part of Link's model, each material by name the first time; kept hidden after that by
   setting the same slots (part instance, its set method, the index) again at every update of Link, one call each (the game
   may show them again; redone a part at a time, what it showed stayed seen until its turn: flashing cloth) */
static void head_materials_set(Ctx *c, int want) {
    static int hidden;
    static uint64_t hidden_model;
    static struct { uint64_t inst, set; int32_t idx; } kept[64];
    static int n_kept;
    static SRWLOCK lock = SRWLOCK_INIT;   /* (two workers updating Link at once: one does it) */
    if (!ob.valid || (!want && !hidden)) return;
    if (!TryAcquireSRWLockExclusive(&lock)) return;
    if (want && hidden && hidden_model == ob.model && n_kept) {
        const uint64_t ksp = (c->x[31] - 256) & ~15ULL;
        for (int k = 0; k < n_kept; k++) {
            Ctx call = *c;
            call.x[31] = ksp - 64;
            vr_call(&call, kept[k].set, kept[k].inst, (uint64_t)kept[k].idx, 0, 0);
        }
        ReleaseSRWLockExclusive(&lock);
        return;
    }
    if (!want && hidden_model != ob.model) {   /* (another model since: nothing of ours on this one) */
        hidden = 0;
        ReleaseSRWLockExclusive(&lock);
        return;
    }
    const uint64_t parts = recomp_load64(c, ob.model + 0x28);
    const uint32_t nparts = recomp_load32(c, ob.model + 0x20);
    if (!plausible(parts, 8) || nparts == 0 || nparts > 16) {
        ReleaseSRWLockExclusive(&lock);
        return;
    }
    const uint64_t sp = (c->x[31] - 256) & ~15ULL;
    int done = 0;
    n_kept = 0;
    for (uint32_t part = 0; part < nparts; part++) {
        const uint64_t pp = recomp_load64(c, parts + part * 8);
        const uint64_t inst = plausible(pp, 8) ? recomp_load64(c, pp) : 0;
        if (!inst || !plausible(inst, 0x300)) continue;
        const uint64_t vt = recomp_load64(c, inst);
        if (vt < hos_image_base || vt >= hos_image_end) continue;
        const uint64_t find = recomp_load64(c, vt + 0xd0), set = recomp_load64(c, vt + 0x1c8);
        if (find < hos_image_base || find >= hos_image_end || set < hos_image_base || set >= hos_image_end) continue;
        for (unsigned i = 0; i < sizeof head_materials / sizeof *head_materials; i++) {
            const char *name = head_materials[i];
            const size_t n = strlen(name);
            for (size_t k = 0; k <= n; k++) recomp_store8_sp(c, sp + 16 + k, (uint8_t)name[k]);
            recomp_store64_sp(c, sp, sp + 16);
            Ctx call = *c;
            call.x[31] = sp - 64;
            const int32_t idx = (int32_t)vr_call(&call, find, inst, sp, 0, 0);
            if (idx < 0 || idx > 4096) continue;
            call = *c;
            call.x[31] = sp - 64;
            vr_call(&call, set, inst, (uint64_t)idx, want ? 0 : 1, 0);
            if (want && n_kept < 64) kept[n_kept].inst = inst, kept[n_kept].set = set, kept[n_kept].idx = idx, n_kept++;
            done++;
        }
    }
    static int logs;
    if (logs < 10) logs++, hos_log("vr: body: %d of his head's and shoulders' materials %s", done, want ? "hidden (first person)" : "shown again");
    hidden = want, hidden_model = ob.model;
    ReleaseSRWLockExclusive(&lock);
}

/* ---- what Link carries on his back, hidden in first person ---- */
/* (In first person the eyes stand where his head was, and what hangs on his back swung over his shoulders into the view
   jumping, rolling and running: the sheath, the quiver, and the sword and shield while put away (the Biggoron's Sword is
   longer than he is tall). Each is an actor of its own, drawn whatever Body says, so this applies to both. The sheaths and
   the quiver are hidden always, the sword and the shield while put away: drawn they are in his hands. Material names from
   romfs Model/Weapon_*.bfres, every mesh's: the Master Sword's grip wrap (Grip_Coart, Mt_Weapon_Sword_Master_Coat) left
   alone, a dark red strip swung up over his shoulder into the view jumping) */
#define BACK_MATS 8
static const struct { const char *prefix; int when_put_away; const char *mats[BACK_MATS]; } back_items[] = {
    {"Weapon_Sheath_", 0, {"Mt_Weapon_Sheath_Kokiri", "Mt_Weapon_Sheath_Master", "Mt_Weapon_Sheath_Biggoron", "Mt_Weapon_Sheath_Master_Dark",
                           "Mt_Player_Adult_Dark_Emc"}},
    {"Weapon_Lsheath_", 0, {"Mt_Weapon_Sheath_Biggoron"}},
    {"Weapon_Quiver_", 0, {"Mt_Leather", "Mt_Arrow_002"}},
    {"Weapon_Sword_", 1, {"Mt_Weapon_Sword_Biggoron", "Mt_Weapon_Sword_Master", "Mt_Weapon_Sword_Master_Metal", "Mt_Weapon_Sword_Master_Coat",
                          "Mt_Weapon_Sword_Master_Cav", "Mt_Weapon_Sword_Kokiri", "Mt_Weapon_Sword_Master_Dark", "Mt_Weapon_Sword_Master_Metal_Dark"}},
    {"Weapon_Shield_", 1, {"Mt_Weapon_Shield_Hylian", "Mt_Weapon_Shield_Mirror", "Mt_Weapon_Shield_Mirror_Sphere_Emc",
                           "Mt_Wespon_Shield_Mirror_Parts", "Mt_Body", "Mt_Weapon_Shield_Hylian_Dark", "Mt_Player_Adult_Dark_Emc"}},
    /* (what he wears is an actor of its own too, drawn over his own model (romfs Model/Armor_*.bfres): the Goron and Zora
       tunics bring their own hood, cape and belts, which flapped in front of the eyes as his own did (the Goron tunic's
       hood, Pg_Hood_low1 on Mt_Leather, the red strip seen jumping); hidden as his own are, the shirt and sleeves (Mt_Inner)
       kept for the arms. The Lens of Truth's glasses and young Link's masks sit on his face, at the eyes) */
    /* ((Triforce VR, 11-26) the tunic is the hood's meshes there too (romfs Model/Armor_Adult_*.bfres: Pg_Hood_low1 with the
       Goron vest and belts, the Zora's Hood_Base with its pattern): only the Zora's feather hidden; the hood goes by its cap's
       bones, as his own (cap_hide)) */
    {"Armor_Adult_Goron", 0, {NULL}},
    {"Armor_Adult_Zora", 0, {"Mt_Feather"}},
    {"Armor_Adult_GlassTruth", 0, {"Mt_GlassTruth", "Mt_Lenses", "Mt_LensesSpecular"}},
    {"Armor_Child_GlassTruth", 0, {"Mt_GlassTruth", "Mt_Lenses", "Mt_LensesSpecular"}},
    {"Armor_Child_Mask_", 0, {"Mt_Mask", "Mt_Body", "Mt_Body_AlphaMask", "Mt_Parts"}},
};
/* one material shown or hidden on every part of a model (part instance: find +0xd0, set +0x1c8); how many parts had it */
static int model_material_vis(Ctx *c, uint64_t model, const char *name, int visible) {
    if (!model || !plausible(model, 0x30)) return 0;
    const uint64_t parts = recomp_load64(c, model + 0x28);
    const uint32_t nparts = recomp_load32(c, model + 0x20);
    if (!plausible(parts, 8) || nparts == 0 || nparts > 16) return 0;
    const uint64_t sp = (c->x[31] - 256) & ~15ULL;
    const size_t n = strlen(name);
    int done = 0;
    for (uint32_t part = 0; part < nparts; part++) {
        const uint64_t pp = recomp_load64(c, parts + part * 8);
        const uint64_t inst = plausible(pp, 8) ? recomp_load64(c, pp) : 0;
        if (!inst || !plausible(inst, 0x300)) continue;
        const uint64_t vt = recomp_load64(c, inst);
        if (vt < hos_image_base || vt >= hos_image_end) continue;
        const uint64_t find = recomp_load64(c, vt + 0xd0), set = recomp_load64(c, vt + 0x1c8);
        if (find < hos_image_base || find >= hos_image_end || set < hos_image_base || set >= hos_image_end) continue;
        for (size_t k = 0; k <= n; k++) recomp_store8_sp(c, sp + 16 + k, (uint8_t)name[k]);
        recomp_store64_sp(c, sp, sp + 16);
        Ctx call = *c;
        call.x[31] = sp - 64;
        const int32_t idx = (int32_t)vr_call(&call, find, inst, sp, 0, 0);
        if (idx < 0 || idx > 4096) continue;
        call = *c, call.x[31] = sp - 64;
        vr_call(&call, set, inst, (uint64_t)idx, visible ? 1 : 0, 0);
        done++;
    }
    return done;
}
/* an actor's name (+0x20 points at it), "" when it is not a printable name of 3 to 47 characters */
static int actor_name(Ctx *c, uint64_t actor, char out[48]) {
    out[0] = 0;
    const uint64_t p = plausible(actor + 0x20, 8) ? recomp_load64(c, actor + 0x20) : 0;
    if (!plausible(p, 48)) return 0;
    int n = 0;
    for (; n < 47; n++) {
        const char ch = (char)recomp_load8(c, p + n);
        if (!ch) break;
        if (ch < 32 || ch > 126) return out[0] = 0, 0;
        out[n] = ch;
    }
    out[n] = 0;
    return n >= 3 && n < 47;
}
/* the sword and the shield drawn: the game's QueryPlayerIsEquipStateDrawnAny (evaluate f_82ae4c10) asks f_80f760a0(actor),
   which needs his equipment component ([actor +0x270] +0x200) and its drawn state (+0x358). 1 drawn, 0 put away, -1 not known */
static int weapons_drawn(Ctx *c, uint64_t actor) {
    const uint64_t comps = plausible(actor + 0x270, 8) ? recomp_load64(c, actor + 0x270) : 0;
    if (!comps || !plausible(comps + 0x358, 8) || !recomp_load64(c, comps + 0x200) || !recomp_load64(c, comps + 0x358)) return -1;
    return (int)(vr_call(c, 0x80f760a0ULL, actor, 0, 0, 0) & 1);
}
/* his weapons, from the game's list of actors ([link +0x1b0]: an entry each 0x60 bytes, its actor at +0x40; ~300 in use of
   1024), walked every 2 s (a weapon changed in the menu is found within that); each Link update each one's materials are
   hidden again while they should be (the game may show them again), and shown once when they should not */
#define WORN_MAX 16
static volatile int weapon_drawn;   /* (the sword out, as hide_back_items last asked) */
static void armor_caps_find(Ctx *c, const uint64_t *actors, int n);   /* (below, by cap_hide) */
static void hide_back_items(Ctx *c, uint64_t link, int first_person) {
    static uint64_t found[WORN_MAX];
    static int n, hidden[WORN_MAX], logs, any_hidden;
    static int64_t walked_at;
    static SRWLOCK lock = SRWLOCK_INIT;   /* (two workers updating Link at once: one does it) */
    if (!first_person && !any_hidden) return;   /* (not first person and nothing of ours hidden: no walk, nothing to do) */
    if (!TryAcquireSRWLockExclusive(&lock)) return;
    const int64_t now = hos_now_ns();
    if (now - walked_at > 2000000000LL) {
        walked_at = now;
        const uint64_t list = plausible(link + 0x1b0, 8) ? recomp_load64(c, link + 0x1b0) : 0;
        uint64_t got[WORN_MAX];
        int m = 0;
        char name[48];
        for (int i = 0; plausible(list, 1024 * 0x60) && i < 1024 && m < WORN_MAX; i++) {
            const uint64_t w = recomp_load64(c, list + (uint64_t)i * 0x60 + 0x40);
            if (!w || !plausible(w, 0x40) || recomp_load64(c, w) != 0x84b45e18ULL || !actor_name(c, w, name)) continue;
            for (unsigned k = 0; k < sizeof back_items / sizeof *back_items; k++)
                if (!strncmp(name, back_items[k].prefix, strlen(back_items[k].prefix))) {
                    got[m++] = w;
                    break;
                }
        }
        int changed = m != n;
        for (int i = 0; !changed && i < m; i++) changed = got[i] != found[i];
        armor_caps_find(c, got, m);
        if (changed) {
            for (int i = 0; i < m; i++) hidden[i] = -1;
            memcpy(found, got, sizeof got[0] * m), n = m;
            if (logs < 20) logs++, hos_log("vr: body: %d things he carries or wears found (weapons, tunic, glasses, mask)", m);
        }
    }
    const int drawn = first_person ? weapons_drawn(c, link) : -1;
    weapon_drawn = drawn == 1;
    any_hidden = 0;
    for (int i = 0; i < n; i++) {
        char name[48];
        if (!plausible(found[i], 0x40) || recomp_load64(c, found[i]) != 0x84b45e18ULL || !actor_name(c, found[i], name)) continue;
        int kind = -1;
        for (unsigned k = 0; k < sizeof back_items / sizeof *back_items; k++)
            if (!strncmp(name, back_items[k].prefix, strlen(back_items[k].prefix))) kind = (int)k;
        if (kind < 0) continue;
        const int hide = first_person && (!back_items[kind].when_put_away || drawn == 0);
        any_hidden |= hide;
        if (!hide && hidden[i] == 0) continue;   /* (shown already: nothing to do) */
        const uint64_t model = vr_call(c, 0x80994de0ULL, found[i], 0, 0, 0);
        int done = 0;
        for (int k = 0; k < BACK_MATS && back_items[kind].mats[k]; k++) done += model_material_vis(c, model, back_items[kind].mats[k], !hide);
        if (hide != hidden[i] && logs < 40)
            logs++, hos_log("vr: body: %s %s (%d materials)", name, hide ? "hidden (first person)" : "shown", done);
        hidden[i] = hide;
    }
    ReleaseSRWLockExclusive(&lock);
}

/* ---- right-handed by the animation: Link's pose mirrored left for right as the animation leaves it (after the late bone
   pass, before the world pass), his body itself not: each bone given its partner's (Wrist_L for Wrist_R; a centre bone its
   own) pose reflected in his model's x, through the two bones' rest frames, so the mesh is never turned inside out ---- */
#define MA_BONES 512
#define MA_PARTS 4
typedef struct {
    uint64_t bones, res;   /* (the part's skeleton object, [inst+0xf8], and its BFRES skeleton, [bones]) */
    int n;
    int16_t par[MA_BONES], mate[MA_BONES];
    uint8_t leg[MA_BONES];   /* (Waist and every bone under it: his legs and skirt) */
    int16_t hand_l, hand_r;   /* (Weapon_L and Weapon_R: what he holds hangs from them; their places swapped, -1 if none) */
    Xf F[MA_BONES];   /* (B_mate^-1 S B: the rest frames' reflection, S = his model's x) */
    Xf orig[MA_BONES];   /* (each local as the animation last made it) */
    float last[MA_BONES][12];   /* (each local as written here, read back: the animation's next write differs) */
    Xf Mo[MA_BONES], Mmir[MA_BONES];   /* (his model-space pose as the animation made it, and as mirrored) */
    int16_t strap;   /* (Ph_ArmStrap: a physics bone the shield's strap follows; -1 if none) */
    int16_t bangle;   /* (Ph_Bangle: a physics bone on his wrist his bracelets hang from; -1 if none) */
    Xf bangle_rest;   /* (its rest local) */
    int written;
} MaPart;
static struct {
    uint64_t actor, model;
    MaPart part[MA_PARTS];
    int parts;
    int64_t told_at, runs;
} ma;
static SRWLOCK ma_lock = SRWLOCK_INIT;
static __thread int arms_forced;   /* ((Triforce VR) the world pass's arms call while aiming: past the "unchanged" check */
static int ma_wanted(void) {
    static int64_t at;
    static int off;
    const int64_t now = hos_now_ns();
    if (now - at > 1000000000LL) {   /* (research: ~/.app/pc_port/triforce-runs/mirror_anim_off.txt there: the mirror off) */
        at = now;
        const char *home = getenv("HOME");
        char path[512];
        snprintf(path, sizeof path, "%s/.app/pc_port/triforce-runs/mirror_anim_off.txt", home ? home : "");
        FILE *f = fopen(path, "r");
        const int was = off;
        off = f != NULL;
        if (f) fclose(f);
        if (off != was) hos_log("vr: body: mirrored animation: %s", off ? "off (research switch)" : "on again");
    }
    if (off) return 0;
    static int64_t paused_at;
    static int paused;
    if (now - paused_at > 100000000LL) {   /* (the menus show him posed as the game has him) */
        paused_at = now;
        const int was = paused;
        paused = vr_game_paused();
        if (paused != was) hos_log("vr: body: mirrored animation: %s", paused ? "held while the game is paused" : "on again after the pause");
    }
    if (paused) return 0;
    const char *e = getenv("RX_MIRROR_ANIM");
    if (e && *e) return *e == '1';
    static int64_t opt_at;
    static int opt, file = -1;
    if (now - opt_at > 250000000LL) {   /* (the Controls tab's Right handed Link row, asked four times a second) */
        int rx_option(int id, int otherwise);
        int hos_ini_option(const char *key, int otherwise);
        opt_at = now;
        if (file < 0) file = hos_ini_option("right_handed_link", 0);
        opt = rx_option(HOS_OPT_RIGHT_HANDED, file) != 0;
    }
    /* ((Triforce VR) a quest item shown is held in the other hand from the sword's: the mirror the other way meanwhile) */
    static int64_t show_at;
    static int showing;
    if (now - show_at > 50000000LL) show_at = now, showing = vr_game_showing_item();
    {   /* (in VR what the hands last did decides: the sword's hand, an item's, the ocarina's pointing) */
        const char *m = body_cfg("VR_MIRROR");
        if (m[0]) return !strcmp(m, "on") != showing;
    }
    return (opt || vr_sword_right()) != showing;
}
static void xf_id(Xf *x) {
    memset(x, 0, sizeof *x);
    x->m[0][0] = x->m[1][1] = x->m[2][2] = 1;
}
static void ma_rest_local(Ctx *c, uint64_t e, Xf *x) {   /* (a ResBone's rest scale, turn and place as a 3x4) */
    const uint32_t fl = recomp_load32(c, e + 0x2c);
    double sc[3], r[4], t[3];
    for (int k = 0; k < 3; k++) sc[k] = ld_f(c, e + 0x30 + k * 4), t[k] = ld_f(c, e + 0x4c + k * 4);
    for (int k = 0; k < 4; k++) r[k] = ld_f(c, e + 0x3c + k * 4);
    M3 R;
    if (fl & 0x1000) {   /* (Euler XYZ: X first, R = Rz Ry Rx) */
        const double cx = cos(r[0]), sx = sin(r[0]), cy = cos(r[1]), sy = sin(r[1]), cz = cos(r[2]), sz = sin(r[2]);
        R[0][0] = cz * cy, R[0][1] = cz * sy * sx - sz * cx, R[0][2] = cz * sy * cx + sz * sx;
        R[1][0] = sz * cy, R[1][1] = sz * sy * sx + cz * cx, R[1][2] = sz * sy * cx - cz * sx;
        R[2][0] = -sy, R[2][1] = cy * sx, R[2][2] = cy * cx;
    } else {   /* (a quaternion x y z w) */
        const double qx = r[0], qy = r[1], qz = r[2], qw = r[3];
        R[0][0] = 1 - 2 * (qy * qy + qz * qz), R[0][1] = 2 * (qx * qy - qz * qw), R[0][2] = 2 * (qx * qz + qy * qw);
        R[1][0] = 2 * (qx * qy + qz * qw), R[1][1] = 1 - 2 * (qx * qx + qz * qz), R[1][2] = 2 * (qy * qz - qx * qw);
        R[2][0] = 2 * (qx * qz - qy * qw), R[2][1] = 2 * (qy * qz + qx * qw), R[2][2] = 1 - 2 * (qx * qx + qy * qy);
    }
    for (int i = 0; i < 3; i++) {
        for (int k = 0; k < 3; k++) x->m[i][k] = R[i][k] * sc[k];
        x->m[i][3] = t[i];
    }
}
static int ma_name(Ctx *c, uint64_t e, char *out, int cap) {
    const uint64_t p = recomp_load64(c, e);
    if (!plausible(p, 2)) return 0;
    const int n = recomp_load16(c, p);
    if (n <= 0 || n >= cap || !plausible(p + 2, (uint64_t)n)) return 0;
    for (int i = 0; i < n; i++) out[i] = (char)recomp_load8(c, p + 2 + i);
    out[n] = 0;
    return 1;
}
static int ma_side_swap(const char *in, char *out, int at) {   /* (_L <-> _R at a token's end: end, '_' or a digit after) */
    const size_t n = strlen(in);
    if (at < 0 || (size_t)at + 2 > n || in[at] != '_' || (in[at + 1] != 'L' && in[at + 1] != 'R')) return 0;
    const char next = in[at + 2];
    if (next && next != '_' && !(next >= '0' && next <= '9')) return 0;
    memcpy(out, in, n + 1);
    out[at + 1] = in[at + 1] == 'L' ? 'R' : 'L';
    return 1;
}
static int ma_part_load(Ctx *c, uint64_t bones, MaPart *mp) {
    static char names[MA_BONES][64];
    const uint64_t res = recomp_load64(c, bones);
    if (!plausible(res, 0x40)) return 0;
    const int n = recomp_load16(c, res + 0x38);
    const uint64_t arr = recomp_load64(c, res + 0x10);
    if (n <= 0 || n > MA_BONES || !plausible(arr, (uint64_t)n * 0x58)) return 0;
    static Xf B[MA_BONES];
    for (int i = 0; i < n; i++) {
        const uint64_t e = arr + (uint64_t)i * 0x58;
        if (!ma_name(c, e, names[i], 64)) return 0;
        mp->par[i] = (int16_t)recomp_load16(c, e + 0x22);
        if (mp->par[i] >= i) return 0;   /* (parents first, as the world pass wants them) */
        Xf L;
        ma_rest_local(c, e, &L);
        if (mp->par[i] < 0) B[i] = L;
        else xf_mul(&B[mp->par[i]], &L, &B[i]);
    }
    int paired = 0;
    for (int i = 0; i < n; i++) {
        mp->mate[i] = (int16_t)i;
        char other[64];
        for (int at = 0; names[i][at] && mp->mate[i] == i; at++)
            if (ma_side_swap(names[i], other, at))
                for (int j = 0; j < n; j++)
                    if (!strcmp(names[j], other)) {
                        mp->mate[i] = (int16_t)j, paired++;
                        break;
                    }
        Xf S, Bi, t;
        xf_id(&S);
        S.m[0][0] = -1;
        if (!xf_inv(&B[mp->mate[i]], &Bi)) return 0;
        xf_mul(&Bi, &S, &t);
        xf_mul(&t, &B[i], &mp->F[i]);
    }
    for (int i = 0; i < n; i++) mp->leg[i] = !strcmp(names[i], "Waist") || (mp->par[i] >= 0 && mp->leg[mp->par[i]]);
    mp->hand_l = mp->hand_r = mp->strap = mp->bangle = -1;
    for (int i = 0; i < n; i++) {
        if (!strcmp(names[i], "Ph_ArmStrap")) mp->strap = (int16_t)i;
        if (!strcmp(names[i], "Ph_Bangle") && mp->par[i] >= 0) {
            mp->bangle = (int16_t)i;
            ma_rest_local(c, arr + (uint64_t)i * 0x58, &mp->bangle_rest);
        }
    }
    for (int i = 0; i < n; i++) {
        if (!strcmp(names[i], "Weapon_L")) mp->hand_l = (int16_t)i;
        if (!strcmp(names[i], "Weapon_R")) mp->hand_r = (int16_t)i;
    }
    mp->bones = bones, mp->res = res, mp->n = n, mp->written = 0;
    hos_log("vr: body: mirrored animation: a skeleton of %d bones, %d of them in left/right pairs (%s, %s...); hands %d/%d", n, paired,
            names[0], n > 1 ? names[1] : "", mp->hand_l, mp->hand_r);
    return 1;
}
static void ma_snap(Ctx *c, uint64_t slots, MaPart *mp, int b) {
    for (int k = 0; k < 12; k++) mp->last[b][k] = ld_f(c, slots + (uint64_t)b * 0x60 + 0x20 + (k / 3) * 16 + (k % 3) * 4);
}
static int ma_same(Ctx *c, uint64_t slots, MaPart *mp, int b) {
    for (int k = 0; k < 12; k++)
        if (ld_f(c, slots + (uint64_t)b * 0x60 + 0x20 + (k / 3) * 16 + (k % 3) * 4) != mp->last[b][k]) return 0;
    return 1;
}
static int64_t ma_done, ma_skipped;
static void ma_part_mirror(Ctx *c, int part, MaPart *mp) {
    const uint64_t slots = recomp_load64(c, mp->bones + 0x18);
    if (!plausible(slots, (uint64_t)mp->n * 0x60)) return;
    static Xf M[MA_BONES], Mm[MA_BONES];
    for (int b = 0; b < mp->n; b++) {   /* (a bone the animation wrote anew: its local as made; one it left: the last made) */
        if (!mp->written || !ma_same(c, slots, mp, b)) xf_load(c, slots + (uint64_t)b * 0x60 + 0x20, &mp->orig[b]);
        if (mp->par[b] < 0) M[b] = mp->orig[b];
        else xf_mul(&M[mp->par[b]], &mp->orig[b], &M[b]);
    }
    Xf S;
    xf_id(&S);
    S.m[0][0] = -1;
    for (int b = 0; b < mp->n; b++) {
        Xf t;
        xf_mul(&S, &M[mp->mate[b]], &t);
        xf_mul(&t, &mp->F[b], &Mm[b]);
    }
    {   /* ((Triforce VR) moving sideways: from his waist down as the animation made it, not mirrored, so his legs go the way he goes */
        int vr_game_sidestep(void);
        if (vr_game_sidestep()) {
            int waist = -1;
            for (int b = 0; b < mp->n && waist < 0; b++)
                if (mp->leg[b]) waist = b;
            double d[3] = {0, 0, 0};   /* (moved so his waist stays where the mirrored body has it) */
            if (waist >= 0)
                for (int r = 0; r < 3; r++) d[r] = Mm[waist].m[r][3] - M[waist].m[r][3];
            for (int b = 0; b < mp->n; b++)
                if (mp->leg[b]) {
                    Mm[b] = M[b];
                    for (int r = 0; r < 3; r++) Mm[b].m[r][3] += d[r];
                }
        }
    }
    memcpy(mp->Mo, M, sizeof(Xf) * mp->n), memcpy(mp->Mmir, Mm, sizeof(Xf) * mp->n);
    if (mp->hand_l >= 0 && mp->hand_r >= 0) {   /* (what he holds in a hand to the other: his mirrored pose's sword hand is the right) */
        const Xf t = Mm[mp->hand_l];
        Mm[mp->hand_l] = Mm[mp->hand_r], Mm[mp->hand_r] = t;
        for (int h = 0; h < 2; h++) {   /* (each where its own pose is, reflected: the rest frames' reflection moves it when the two
                                           hands' rest places are not each other's mirror, as the child's are not) */
            const int b = h ? mp->hand_r : mp->hand_l;
            for (int r = 0; r < 3; r++) Mm[b].m[r][3] = r ? M[b].m[r][3] : -M[b].m[r][3];
        }
        const int ax = 2;   /* (z: a half turn about that axis of the hand's, so what he holds faces the right way, found in the headset) */
        if (ax >= 0)
            for (int h = 0; h < 2; h++) {
                Xf *x = &Mm[h ? mp->hand_r : mp->hand_l];
                for (int r = 0; r < 3; r++)
                    for (int k = 0; k < 3; k++)
                        if (k != ax) x->m[r][k] = -x->m[r][k];
            }
    }
    for (int b = 0; b < mp->n; b++) {
        Xf L, pi;
        if (mp->par[b] < 0) L = Mm[b];
        else {
            if (!xf_inv(&Mm[mp->par[b]], &pi)) continue;
            xf_mul(&pi, &Mm[b], &L);
        }
        bone_write(c, ma.model, (uint32_t)part | ((uint32_t)b << 16), L.m);
    }
    for (int b = 0; b < mp->n; b++) ma_snap(c, slots, mp, b);
    mp->written = 1;
    ma_done++;
}
static void ma_seen(Ctx *c, uint64_t actor) {   /* (his movement update: his model noted, for the late bone pass's hook;
                                                    with the mirror off too, for the things fixed always) */
    const uint64_t model = vr_call(c, 0x80994de0ULL, actor, 0, 0, 0);
    if (model == ma.model && actor == ma.actor) return;
    AcquireSRWLockExclusive(&ma_lock);
    ma.actor = actor, ma.model = model, ma.parts = 0;
    if (model && plausible(model, 0x30)) {
        const int np = (int)recomp_load32(c, model + 0x20);
        const uint64_t parts = recomp_load64(c, model + 0x28);
        for (int k = 0; k < np && k < 16 && ma.parts < MA_PARTS && plausible(parts, 8); k++) {
            const uint64_t pk = recomp_load64(c, parts + (uint64_t)k * 8);
            if (!plausible(pk, 8)) continue;
            const uint64_t inst = recomp_load64(c, pk);
            if (!plausible(inst + 0xf8, 8)) continue;
            const uint64_t bones = recomp_load64(c, inst + 0xf8);
            int seen = 0;
            for (int i = 0; i < ma.parts; i++) seen |= ma.part[i].bones == bones;
            if (seen || !plausible(bones, 0x28)) continue;
            if (ma_part_load(c, bones, &ma.part[ma.parts])) ma.part[ma.parts].written = 0, ma.parts++;
            else hos_log("vr: body: mirrored animation: part %d's skeleton not read", k);
        }
    }
    hos_log("vr: body: mirrored animation: Link %#llx, model %#llx: %d skeletons", (unsigned long long)actor, (unsigned long long)model, ma.parts);
    ReleaseSRWLockExclusive(&ma_lock);
}
static int ma_part_index(Ctx *c, uint64_t bones) {   /* (the part of the model with these bones, for its bone ids) */
    const int np = (int)recomp_load32(c, ma.model + 0x20);
    const uint64_t parts = recomp_load64(c, ma.model + 0x28);
    for (int k = 0; k < np && k < 16; k++) {
        const uint64_t pk = recomp_load64(c, parts + (uint64_t)k * 8);
        if (plausible(pk, 8) && plausible(recomp_load64(c, pk) + 0xf8, 8) && recomp_load64(c, recomp_load64(c, pk) + 0xf8) == bones) return k;
    }
    return -1;
}
/* the shield's placing (f_81500960: its bones from the base matrix x1, the skeleton x0): with his pose mirrored, a left arm's
   shield is mirrored too (the handle on its other side), its base reflected in one of its own axes and the placing run with
   that; the renderer turns its faces (gpu/vk xr_draw_mirrored). 1: done here, the game's own run skipped */
static __thread int shield_inside;
/* what is mirrored besides his pose: a table of actor name prefixes and the axis of each one's own base it is reflected in,
   read once a second from a file (lines "<prefix> <x|y|z>"; without one: the shield in x), so a thing's axis can be found
   while she watches. Their skeletons found again every half second among the actors near him (his list at +0x1b0) */
typedef struct {
    char prefix[40];
    int age;   /* (prefix@child or prefix@adult: that age's only, 1 child 2 adult; 0 both) */
    int always;   /* (a line ending in "always": put away, its K with the mirror off too: a fix of the game's own) */
    int hand, back;   /* (axes to reflect, bits x 1 y 2 z 4: in a hand, put away; back -1: the matrix K instead) */
    float K[12];      /* (put away: the base taken through this, rows of a 3x4 in the thing's own frame: the measured mirror) */
} MirItem;
static MirItem mir_items[32] = {{"Weapon_Shield_", 0, 1, 0, {0}}};
static int mir_items_n = 1;
/* the table as measured in the headset (2026-11-23/24): each thing's mirror in a hand and put away, by age; a file of the same
   lines (~/.app/pc_port/triforce-runs/mirror_items.txt) in its place while tuning */
static const char mir_items_builtin[] =
    "Weapon_Shield_Hylian@adult x K -0.8537 0.1319 -0.5042 0.1943 0.1245 0.9911 0.0505 -0.0093 -0.5058 0.0202 0.8626 0.0520\n"
    "Weapon_Shield_Hylian@child - -\n"
    "Weapon_Shield_Mirror@adult x K -0.8556 0.1269 -0.5020 0.1826 0.1202 0.9918 0.0476 -0.0128 -0.5034 0.0198 0.8629 0.0460\n"
    "Weapon_Shield_Mirror@child - K 0.8659 -0.0098 -0.5015 0.0305 0.0004 1.0001 -0.0182 0.0090 0.5006 0.0151 0.8652 -0.0416 always\n"
    "Weapon_Shield_Deku@adult x K -0.8663 0.0531 -0.4964 0.0428 0.0497 0.9983 0.0195 -0.0072 -0.4968 0.0083 0.8680 0.0094\n"
    "Weapon_Shield_Deku@child x K -0.4725 0.1887 -0.8605 0.1641 0.1693 0.9782 0.1214 -0.0221 -0.8654 0.0885 0.4936 0.0915\n"
    "Weapon_Shield_ x -\n"
    "Weapon_Sword_Kokiri@adult - K -0.8134 0.0477 0.5798 -0.2143 0.0584 0.9980 -0.0021 -0.0006 0.5782 -0.0320 0.8153 0.0690\n"
    "Weapon_Sheath_Kokiri@adult - K -0.8134 0.0477 0.5798 -0.2143 0.0584 0.9980 -0.0021 -0.0006 0.5782 -0.0320 0.8153 0.0690\n"
    "Weapon_Sword_Kokiri@child - K -0.4102 0.1057 0.9053 -0.2055 0.0925 0.9932 -0.0745 0.0162 0.9075 -0.0524 0.4175 0.1304\n"
    "Weapon_Sheath_Kokiri@child - K -0.4102 0.1057 0.9053 -0.2055 0.0925 0.9932 -0.0745 0.0162 0.9075 -0.0524 0.4175 0.1304\n"
    "Item_Ocarina_ x -\n"
    "Item_Hammer xy -\n"
    "Weapon_Sword_Master@adult - K -0.8716 0.0385 0.4883 -0.2508 0.0537 0.9978 0.0167 -0.0055 0.4867 -0.0405 0.8723 0.0735\n"
    "Weapon_Sheath_070@adult - K -0.8716 0.0385 0.4883 -0.2508 0.0537 0.9978 0.0167 -0.0055 0.4867 -0.0405 0.8723 0.0735\n"
    "Weapon_Sword_Biggoron@adult - K -0.7472 -0.1872 -0.6373 0.2956 -0.1369 0.9819 -0.1291 0.0316 -0.6508 0.0091 0.7598 0.1289\n"
    "Weapon_Sword_Biggoron@child - K -0.3239 0.0716 -0.9434 0.3341 0.0688 0.9969 0.0516 -0.0140 -0.9437 0.0485 0.3272 0.2375\n"
    "Weapon_Range_Hookshot x -\n"
    "Weapon_Range_Bow x -\n"
    "Weapon_Range_SlingShot xy -\n"
    "Item_Boomerang xy -\n"
    "Item_CojiroCucco - P\n"
    "Weapon_Sword_Master@child - K -0.4960 0.1490 0.8549 -0.3230 0.1267 0.9869 -0.0988 0.0337 0.8584 -0.0595 0.5087 0.1821\n"
    "Weapon_Sheath_070@child - K -0.4960 0.1490 0.8549 -0.3230 0.1267 0.9869 -0.0988 0.0337 0.8584 -0.0595 0.5087 0.1821\n"
    "Item_AlarmCucco - P\n"
    "Item_ZeldaLetter - P\n"
    "Item_WeirdEgg - P\n"
    "Item_ScrubBusinessSeed - P\n"
    "Item_MagicBean - P\n"
    "Item_PocketCucco - P\n"
    "Item_OddMushroom - P\n"
    "Item_OddPowder - P\n"
    "Item_PoacherSaw - P\n"
    "Item_EyeballFrog - P\n"
    "Item_EyeDrop - P\n"
    "Item_ClaimCheck - P\n"
    "Item_Prescription - P\n"
    "Item_RutoLetter - P\n";
static void mir_items_read(void) {
    static int64_t at;
    const int64_t now = hos_now_ns();
    if (now - at < 1000000000LL) return;
    at = now;
    const char *home = getenv("HOME");
    char path[512], line[256];
    static char text[8192];
    snprintf(path, sizeof path, "%s/.app/pc_port/triforce-runs/mirror_items.txt", home ? home : "");
    FILE *f = fopen(path, "r");
    size_t len = 0;
    if (f) {
        len = fread(text, 1, sizeof text - 1, f);
        fclose(f);
    } else {
        len = strlen(mir_items_builtin);
        if (len > sizeof text - 1) len = sizeof text - 1;
        memcpy(text, mir_items_builtin, len);
    }
    text[len] = 0;
    static MirItem t[32];
    int n = 0;
    for (const char *q = text; n < 32 && *q;) {
        const char *e = strchr(q, '\n');
        size_t l = e ? (size_t)(e - q) : strlen(q);
        if (l >= sizeof line) l = sizeof line - 1;
        memcpy(line, q, l), line[l] = 0;
        q = e ? e + 1 : q + strlen(q);
        char pre[40], a[8] = "-", b[8] = "-";
        int used = 0;
        if (sscanf(line, "%39s %7s %7s%n", pre, a, b, &used) >= 2) {
            char *tag = strchr(pre, '@');
            t[n].age = 0;
            if (tag) {
                t[n].age = !strcmp(tag, "@child") ? 1 : !strcmp(tag, "@adult") ? 2 : 0;
                *tag = 0;
            }
            snprintf(t[n].prefix, sizeof t[n].prefix, "%s", pre);
            t[n].always = strstr(line, " always") != NULL;
            t[n].hand = t[n].back = 0;
            memset(t[n].K, 0, sizeof t[n].K);
            for (const char *p = a; *p; p++) t[n].hand |= *p == 'x' ? 1 : *p == 'y' ? 2 : *p == 'z' ? 4 : 0;
            if (!strcmp(b, "K")) {   /* (then 12 numbers: rows of the 3x4) */
                const char *p = line + used;
                int got = 0;
                for (; got < 12; got++) {
                    char *e;
                    t[n].K[got] = strtof(p, &e);
                    if (e == p) break;
                    p = e;
                }
                t[n].back = got == 12 ? -1 : 0;
            } else if (!strcmp(b, "P"))   /* (its place alone reflected through his body, in a hand or not: what he holds up) */
                t[n].back = -2;
            else
                for (const char *p = b; *p; p++) t[n].back |= *p == 'x' ? 1 : *p == 'y' ? 2 : *p == 'z' ? 4 : 0;
            n++;
        }
    }
    int changed = n != mir_items_n;
    for (int k = 0; !changed && k < n; k++) changed = strcmp(t[k].prefix, mir_items[k].prefix) || t[k].hand != mir_items[k].hand || t[k].age != mir_items[k].age || t[k].always != mir_items[k].always || t[k].back != mir_items[k].back || memcmp(t[k].K, mir_items[k].K, sizeof t[k].K);
    if (changed) {
        memcpy(mir_items, t, sizeof t[0] * n), mir_items_n = n;
        for (int k = 0; k < n; k++) hos_log("vr: body: mirrored animation: %s%s reflected in axes %d in a hand, %d put away (x 1, y 2, z 4)", t[k].prefix, t[k].age == 1 ? " (child)" : t[k].age == 2 ? " (adult)" : "", t[k].hand, t[k].back);
    }
}
static uint64_t mi_bones[16], mi_inst[16];
static int mi_hand[16], mi_back[16], mi_item[16], mi_always[16], mi_n;
static int mirrored_item(Ctx *c, uint64_t bones) {   /* (this skeleton's index in the found things, -1 if none) */
    static int64_t at;
    static SRWLOCK lock = SRWLOCK_INIT;
    const int64_t now = hos_now_ns();
    static uint64_t link_was;
    if (ma.actor != link_was) mi_n = 0, at = 0, link_was = ma.actor;   /* ((Triforce VR) a new Link (an age switch, an area): his
                                                                         old things' skeletons are being deleted, found again now */
    if (now - at > 500000000LL && TryAcquireSRWLockExclusive(&lock)) {
        at = now;
        mir_items_read();
        int n = 0;
        const uint64_t link = ma.actor;
        const uint64_t list = plausible(link + 0x1b0, 8) ? recomp_load64(c, link + 0x1b0) : 0;
        char name[48];
        for (int i = 0; plausible(list, 1024 * 0x60) && i < 1024 && n < 16; i++) {
            const uint64_t w = recomp_load64(c, list + (uint64_t)i * 0x60 + 0x40);
            if (!w || !plausible(w, 0x40) || recomp_load64(c, w) != 0x84b45e18ULL || !actor_name(c, w, name)) continue;
            int it = -1;
            const int age = vr_game_childhood() ? 1 : 2;
            for (int k = 0; k < mir_items_n && it < 0; k++)
                if ((!mir_items[k].age || mir_items[k].age == age) && !strncmp(name, mir_items[k].prefix, strlen(mir_items[k].prefix))) it = k;
            if (it < 0 || !(mir_items[it].hand | mir_items[it].back)) continue;
            const uint64_t model = vr_call(c, 0x80994de0ULL, w, 0, 0, 0);
            if (!plausible(model, 0x30)) continue;
            const uint64_t parts = recomp_load64(c, model + 0x28);
            const int np = (int)recomp_load32(c, model + 0x20);
            for (int k = 0; k < np && k < 8 && n < 16 && plausible(parts, 8); k++) {
                const uint64_t pk = recomp_load64(c, parts + (uint64_t)k * 8);
                if (!plausible(pk, 8) || !plausible(recomp_load64(c, pk) + 0xf8, 8)) continue;
                mi_inst[n] = recomp_load64(c, pk), mi_bones[n] = recomp_load64(c, mi_inst[n] + 0xf8), mi_hand[n] = mir_items[it].hand, mi_item[n] = it, mi_always[n] = mir_items[it].always, mi_back[n++] = mir_items[it].back;
            }
        }
        if (n != mi_n) hos_log("vr: body: mirrored animation: %d skeleton(s) of mirrored things near him", n);
        mi_n = n;
        ReleaseSRWLockExclusive(&lock);
    }
    /* (the thing still the one found: its instance's skeleton this one, not a deleted thing's place used again) */
    for (int i = 0; i < mi_n; i++)
        if (mi_bones[i] == bones && plausible(mi_inst[i] + 0xf8, 8) && recomp_load64(c, mi_inst[i] + 0xf8) == bones) return i;
    return -1;
}
/* his strap (Ph_ArmStrap, a physics bone whose simulation goes astray with the arm mirrored under it) where the mirror wants
   it: his own pose's strap reflected in his model's x, placed through his root's world as mirrored. Into his world entry and,
   when given, a thing's bone (the shield's ArmStrap, which follows his) relative to that thing's origin */
static void strap_place(Ctx *c, uint64_t thing_bones, uint64_t thing_inst, int reflected) {
    const MaPart *mp = &ma.part[0];
    const int part = ma_part_index(c, mp->bones);
    if (mp->strap < 0 || part < 0 || !mp->written) return;
    const uint64_t link_inst = recomp_load64(c, recomp_load64(c, recomp_load64(c, ma.model + 0x28) + (uint64_t)part * 8));
    const uint64_t worlds = recomp_load64(c, mp->bones + 0x20);
    if (!plausible(link_inst + 0x2d0, 12) || !plausible(worlds, (uint64_t)mp->n * 64)) return;
    Xf root, mi, T, S, t, want;
    xf_load(c, worlds, &root);
    if (!xf_inv(&mp->Mmir[0], &mi)) return;
    xf_mul(&root, &mi, &T);   /* (model to world, relative to his origin) */
    xf_id(&S);
    S.m[0][0] = -1;
    xf_mul(&T, &S, &t);
    xf_mul(&t, &mp->Mo[mp->strap], &want);   /* (reflected: the mirrored shield's strap) */
    Xf his;
    xf_mul(&T, &mp->Mmir[mp->strap], &his);   /* (his own, not turned inside out: the reflection through the bone's rest frames) */
    const uint64_t e = worlds + (uint64_t)mp->strap * 64;
    for (int k = 0; k < 4; k++)
        for (int r = 0; r < 3; r++) st_f(c, e + k * 16 + r * 4, his.m[r][k]);
    if (!thing_bones || !plausible(thing_inst + 0x2d0, 12)) return;
    const int strap_his = reflected ? 0 : 2;   /* (a shield only turned, or left as it is, keeps its strap on itself) */
    if (strap_his == 2) return;
    const uint64_t res = recomp_load64(c, thing_bones), tw = recomp_load64(c, thing_bones + 0x20);
    const int n = plausible(res + 0x38, 2) ? (int)recomp_load16(c, res + 0x38) : 0;
    const uint64_t arr = plausible(res + 0x10, 8) ? recomp_load64(c, res + 0x10) : 0;
    for (int b = 0; b < n && b < 16 && plausible(arr, (uint64_t)(b + 1) * 0x58) && plausible(tw, (uint64_t)(b + 1) * 64); b++) {
        char nm[64];
        if (!ma_name(c, arr + (uint64_t)b * 0x58, nm, 64) || strcmp(nm, "ArmStrap")) continue;
        for (int k = 0; k < 4; k++)
            for (int r = 0; r < 3; r++) {
                double v = k == 3 && strap_his ? his.m[r][3] : want.m[r][k];   /* (the child's: where his own strap is) */
                if (k == 3) v += ld_f(c, link_inst + 0x2d0 + r * 4) - ld_f(c, thing_inst + 0x2d0 + r * 4);
                st_f(c, tw + (uint64_t)b * 64 + k * 16 + r * 4, v);
            }
    }
}
/* his bracelet's bone (Ph_Bangle, a physics bone whose simulation goes astray with the arm mirrored under it): at rest on the
   wrist it hangs from, that wrist as mirrored, through his root's world as mirrored. Into his world entry */
static void bangle_place(Ctx *c) {
    const MaPart *mp = &ma.part[0];
    if (mp->bangle < 0 || !mp->written || ma_part_index(c, mp->bones) < 0) return;
    const uint64_t worlds = recomp_load64(c, mp->bones + 0x20);
    if (!plausible(worlds, (uint64_t)mp->n * 64)) return;
    Xf root, mi, T, t, want;
    xf_load(c, worlds, &root);
    if (!xf_inv(&mp->Mmir[0], &mi)) return;
    xf_mul(&root, &mi, &T);
    xf_mul(&T, &mp->Mmir[mp->par[mp->bangle]], &t);
    xf_mul(&t, &mp->bangle_rest, &want);
    const uint64_t e = worlds + (uint64_t)mp->bangle * 64;
    for (int k = 0; k < 4; k++)
        for (int r = 0; r < 3; r++) st_f(c, e + k * 16 + r * 4, want.m[r][k]);
}
/* a thing placed in one of his hands (its base within 12 cm of Weapon_L's or Weapon_R's place, in the world): mirrored only
   there; put away (his back, his belt) it sits on his body, which is not mirrored */
static int in_his_hand(Ctx *c, uint64_t bones, uint64_t base) {
    uint64_t inst = 0;
    for (int i = 0; i < mi_n; i++)
        if (mi_bones[i] == bones) inst = mi_inst[i];
    const MaPart *mp = &ma.part[0];
    const int part = ma_part_index(c, mp->bones);
    if (!plausible(inst + 0x2d0, 12) || part < 0 || mp->hand_l < 0 || mp->hand_r < 0) return 0;
    const uint64_t link_inst = recomp_load64(c, recomp_load64(c, recomp_load64(c, ma.model + 0x28) + (uint64_t)part * 8));
    const uint64_t worlds = recomp_load64(c, mp->bones + 0x20);
    if (!plausible(link_inst + 0x2d0, 12) || !plausible(worlds, (uint64_t)mp->n * 64)) return 0;
    double at[3];
    for (int k = 0; k < 3; k++) at[k] = ld_f(c, base + 0x30 + k * 4) + ld_f(c, inst + 0x2d0 + k * 4);
    for (int h = 0; h < 2; h++) {
        const uint64_t e = worlds + (uint64_t)(h ? mp->hand_r : mp->hand_l) * 64;
        double d2 = 0;
        for (int k = 0; k < 3; k++) {
            const double d = ld_f(c, e + 0x30 + k * 4) + ld_f(c, link_inst + 0x2d0 + k * 4) - at[k];
            d2 += d * d;
        }
        if (d2 < 0.12 * 0.12) return 1;
    }
    return 0;
}
/* a thing's placing (f_81500960, f_81500720: its bones from the base matrix x1, the skeleton x0), for a thing in the table:
   its base reflected in its axis and the placing run with that; the renderer turns its faces. 1: done here */
/* ((Triforce VR) the Goron or Zora tunic worn (an actor of its own over his model): its cap's physics bones (Ph_Cap_1..7)
   and its model's origin, for cap_hide; looked for at each walk of what he carries (hide_back_items) */
static struct { uint64_t world[7], origin; } armor_cap;
static void armor_caps_find(Ctx *c, const uint64_t *actors, int n) {
    memset(&armor_cap, 0, sizeof armor_cap);
    char name[48];
    for (int i = 0; i < n; i++) {
        if (!plausible(actors[i], 0x40) || !actor_name(c, actors[i], name) || strncmp(name, "Armor_Adult_", 12) ||
            (strncmp(name + 12, "Goron", 5) && strncmp(name + 12, "Zora", 4)))
            continue;
        const uint64_t model = vr_call(c, 0x80994de0ULL, actors[i], 0, 0, 0);
        if (!plausible(model, 0x30)) continue;
        for (int k = 0; k < 7; k++) {
            char bone[16];
            uint32_t id;
            snprintf(bone, sizeof bone, "Ph_Cap_%d", k + 1);
            if (!bone_id(c, model, bone, &id)) continue;
            uint64_t inst = recomp_load64(c, recomp_load64(c, model + 0x28) + (int16_t)(id & 0xffff) * 8);
            inst = recomp_load64(c, inst);
            const uint64_t w = recomp_load64(c, recomp_load64(c, inst + 0xf8) + 0x20) + (uint64_t)(int16_t)(id >> 16) * 64;
            if (plausible(w, 64) && plausible(inst + 0x2d0, 12)) armor_cap.world[k] = w, armor_cap.origin = inst + 0x2d0;
        }
        return;
    }
}
/* ((Triforce VR) his cap in first person with his head hidden: its physics bones (Ph_Cap_1..7, which the head's own bone does
   not carry) given the head's world entry, shrunk and sunk, so the cap goes with it and the tunic of the same meshes stays.
   After his skeleton's world pass, as the things he holds are placed (mirror_attach) */
static void cap_hide(Ctx *c) {
    if (!ob.valid || !vr_first_person_now() || !body_arms() || !plausible(ob.world[OB_HEAD], 64)) return;
    uint32_t head[16];
    for (int k = 0; k < 16; k++) head[k] = recomp_load32(c, ob.world[OB_HEAD] + (uint64_t)k * 4);
    for (int n = 0; n < 7; n++)
        if (ob.cap_world[n] && plausible(ob.cap_world[n], 64))
            for (int k = 0; k < 16; k++) recomp_store32_sp(c, ob.cap_world[n] + (uint64_t)k * 4, head[k]);
    /* (the tunic's cap the same, its place moved from his model's origin to the tunic's) */
    if (!armor_cap.origin || !plausible(armor_cap.origin, 12) || !plausible(ob.origin, 12)) return;
    float at[3];
    for (int k = 0; k < 3; k++) {
        float hp;
        memcpy(&hp, &head[12 + k], 4);
        at[k] = (float)(hp + ld_f(c, ob.origin + (uint64_t)k * 4) - ld_f(c, armor_cap.origin + (uint64_t)k * 4));
    }
    for (int n = 0; n < 7; n++)
        if (armor_cap.world[n] && plausible(armor_cap.world[n], 64)) {
            for (int k = 0; k < 12; k++) recomp_store32_sp(c, armor_cap.world[n] + (uint64_t)k * 4, head[k]);
            for (int k = 0; k < 3; k++) st_f(c, armor_cap.world[n] + 48 + (uint64_t)k * 4, at[k]);
            recomp_store32_sp(c, armor_cap.world[n] + 60, head[15]);
        }
}
/* ((Scout, 11-26) right-handed Link: an effect laid out in the frame of one of his center bones (no left/right mate: the spine,
   neck, head...; the sword's slash trail, Wpn_Sword_Slash_00's SwordBlur drawn by the game's WeaponBlurRenderer, is laid out
   in Spine_2's frame) followed the mirror's turn of that bone (S M F, F = B^-1 S B: kept a turn by the axis along his x turned
   round), so the trail's sideways axis pointed the other way and the slash arced over and behind him. Measured against the
   game's own swing: x and y the reflection's, z dot -1. Each such bone's world as the GPU will see it (his origin added) and
   that frame times F, the exact reflection of the game's own (F is its own inverse), to the renderer, which draws an effect
   whose emitter frame is the first in the second (gpu/vk/vk_draw.cpp xr_effect_frame_fix). After his world pass, as the
   things he holds are placed (mirror_attach), once a pass */
static void mirror_frames_publish(Ctx *c) {
    static SRWLOCK lk = SRWLOCK_INIT;
    static float pairs[MA_BONES][24], last[MA_BONES][12];
    static int last_n;
    const MaPart *mp = &ma.part[0];
    const int part = ma_part_index(c, mp->bones);
    if (!mp->written || part < 0 || !TryAcquireSRWLockExclusive(&lk)) return;
    const uint64_t link_inst = recomp_load64(c, recomp_load64(c, recomp_load64(c, ma.model + 0x28) + (uint64_t)part * 8));
    const uint64_t worlds = recomp_load64(c, mp->bones + 0x20);
    int n = 0;
    if (plausible(link_inst + 0x2d0, 12) && plausible(worlds, (uint64_t)mp->n * 64)) {
        double org[3];
        for (int r = 0; r < 3; r++) org[r] = ld_f(c, link_inst + 0x2d0 + (uint64_t)r * 4);
        for (int b = 0; b < mp->n; b++) {
            if (mp->mate[b] != b) continue;
            Xf W, T;
            xf_load(c, worlds + (uint64_t)b * 64, &W);
            for (int r = 0; r < 3; r++) W.m[r][3] += org[r];
            xf_mul(&W, &mp->F[b], &T);
            for (int k = 0; k < 4; k++)
                for (int r = 0; r < 3; r++) pairs[n][k * 3 + r] = (float)W.m[r][k], pairs[n][12 + k * 3 + r] = (float)T.m[r][k];
            n++;
        }
    }
    int same = n == last_n;   /* (this pass's already sent: the same frames as last time) */
    for (int i = 0; i < n && same; i++) same = !memcmp(pairs[i], last[i], sizeof last[i]);
    if (n && !same) {
        void hos_vk_mirror_frames_publish(const float *pairs, int n);
        hos_vk_mirror_frames_publish(&pairs[0][0], n);
        for (int i = 0; i < n; i++) memcpy(last[i], pairs[i], sizeof last[i]);
        last_n = n;
    }
    ReleaseSRWLockExclusive(&lk);
}
/* ((Triforce VR) the trade item last placed in his hand, and when (vr_body_held_quest) */
static char quest_name[48];
static int64_t quest_at;
int vr_body_held_quest(char out[48]) {
    if (hos_now_ns() - __atomic_load_n(&quest_at, __ATOMIC_ACQUIRE) > 400000000LL) return 0;
    snprintf(out, 48, "%s", quest_name);
    return out[0] != 0;
}
static int mirror_attach(Ctx *c, uint64_t fn) {
    /* ((Triforce VR) never on the game's thread that makes and deletes things (BaseProcCreateAndDeleteThread): it places a
       thing as it is made, its skeleton and his not all there yet at a load or an age switch, and putting ours in there
       crashed the game; the game places those itself, ours from the next frame on */
    static __thread int maker = -1;
    if (maker < 0) {
        HosThread *t = hos_self();
        const char *n = t ? hos_thread_name(t) : NULL;
        maker = n && strstr(n, "CreateAndDelete") != NULL;
    }
    if (maker) return 0;
    cap_hide(c);
    if (shield_inside || !ma.parts) return 0;
    const int wanted = ma_wanted();
    if (wanted) bangle_place(c), mirror_frames_publish(c);
    const int it = mirrored_item(c, c->x[0]);
    const uint64_t base = c->x[1];
    if (it < 0 || !plausible(base, 64)) return 0;
    if (mi_back[it] == -2) {   /* ((Triforce VR) a thing only ever in his hand (a trade item): which, for the hands (vr_game.c) */
        snprintf(quest_name, sizeof quest_name, "%s", mir_items[mi_item[it]].prefix);
        __atomic_store_n(&quest_at, hos_now_ns(), __ATOMIC_RELEASE);
    }
    const int hand = mi_back[it] == -2 ? 0 : in_his_hand(c, c->x[0], base);
    if (!wanted && (hand || !mi_always[it] || mi_back[it] != -1)) return 0;   /* (the mirror off: only the always-fixed, put away) */
    const int axes = hand ? mi_hand[it] : mi_back[it];
    if (!axes) return 0;
    const uint64_t m = (c->x[31] - 256) & ~15ULL;   /* (the reflected base on the guest's stack, the call's frame below it) */
    int odd;
    if (axes == -2) {   /* (its place reflected in his x, through his place; its turn as the game has it) */
        const uint64_t inst = mi_inst[it];
        if (!plausible(inst + 0x2d0, 12) || !plausible(ma.actor + 0x328, 36)) return 0;
        double nx[3], d = 0, w[3];
        for (int r = 0; r < 3; r++) {
            nx[r] = ld_f(c, ma.actor + 0x328 + (uint64_t)r * 12);   /* (his x in the world: the first column of his rows) */
            w[r] = ld_f(c, base + 0x30 + (uint64_t)r * 4) + ld_f(c, inst + 0x2d0 + (uint64_t)r * 4);
            d += (w[r] - ld_f(c, ma.actor + 0x31c + (uint64_t)r * 4)) * nx[r];
        }
        for (int k = 0; k < 16; k++) {
            uint32_t v = recomp_load32(c, base + (uint64_t)k * 4);
            if (k >= 12 && k < 15) {
                const float f = (float)(ld_f(c, base + (uint64_t)k * 4) - 2 * d * nx[k - 12]);
                memcpy(&v, &f, 4);
            }
            recomp_store32_sp(c, m + (uint64_t)k * 4, v);
        }
        odd = 0;
    } else if (axes > 0) {
        for (int k = 0; k < 16; k++) {
            uint32_t v = recomp_load32(c, base + (uint64_t)k * 4);
            if (k / 4 < 3 && (axes >> (k / 4) & 1) && k % 4 < 3) v ^= 0x80000000u;   /* (those columns: their axes turned round) */
            recomp_store32_sp(c, m + (uint64_t)k * 4, v);
        }
        odd = __builtin_popcount((unsigned)axes) & 1;
    } else {   /* (the base through K: base K, columns: the base's axes mixed by K's, its place moved by K's) */
        const float *K = mir_items[mi_item[it]].K;
        float B[4][4];   /* (column k, row r) */
        for (int k = 0; k < 4; k++)
            for (int r = 0; r < 4; r++) B[k][r] = ld_f(c, base + (uint64_t)(k * 16 + r * 4));
        for (int j = 0; j < 4; j++)
            for (int r = 0; r < 4; r++) {
                float v = j == 3 ? B[3][r] : 0;
                for (int i = 0; i < 3; i++) v += B[i][r] * K[i * 4 + j];
                if (r == 3) v = B[j][3];
                uint32_t bits;
                memcpy(&bits, &v, 4);
                recomp_store32_sp(c, m + (uint64_t)(j * 16 + r * 4), bits);
            }
        const double det = K[0] * (K[5] * K[10] - K[6] * K[9]) - K[1] * (K[4] * K[10] - K[6] * K[8]) + K[2] * (K[4] * K[9] - K[5] * K[8]);
        odd = det < 0;
    }
    Ctx call = *c;
    call.x[31] = m;
    shield_inside = 1;
    vr_call(&call, fn, c->x[0], m, c->x[2], c->x[8]);
    if (wanted) strap_place(c, c->x[0], mi_inst[it], odd);
    shield_inside = 0;
    if (odd) {   /* (reflected: its bones' turns, rows, to the renderer: the draws it turns the faces of) */
        extern void hos_vk_mirror_publish(const float *turns, int n);
        const uint64_t worlds = recomp_load64(c, c->x[0] + 0x20);
        const uint64_t head = recomp_load64(c, c->x[0]);
        int n = plausible(head + 56, 2) ? (int)recomp_load16(c, head + 56) : 0;
        if (n > 8) n = 8;
        float t[16 * 12];
        int got = 0;
        for (int b = 0; b < n && got < 16 && plausible(worlds, (uint64_t)(b + 1) * 64); b++)   /* (rows of the 3x4, the place last in each: as */
            for (int q = 0, g = got++; q < 12; q++)                                             /* kept, relative to its origin) */
                t[g * 12 + q] = ld_f(c, worlds + (uint64_t)b * 64 + (q % 4) * 16 + (q / 4) * 4);
        if (got) hos_vk_mirror_publish(t, got);
    }
    return 1;
}
int hos_oot_shield_attach(Ctx *c) { return mirror_attach(c, 0x81500960ULL); }
int hos_oot_sword_attach(Ctx *c) { return mirror_attach(c, 0x81500720ULL); }

/* (research, SWORD-TURN: the slash's trail) the bone world accessor's end (f_803a1360: instance x0, bone x2, its world as rows
   of a 3x4 into x1): his hands asked for, counted by caller (the return address) every 5 s; and, from
   ~/.app/pc_port/triforce-runs/sword_turn.txt (read once a second; lines "<caller hex, 0 any> <L|R|B> <x|y|z> <degrees>", in
   order), the answer's turn turned further about its own axis, its place kept */
static struct { uint64_t at; int64_t n[2]; } jw_callers[32];
static int jw_n;
static int64_t jw_told;
static struct { uint64_t at; int hand, ax; double deg; } jw_turn[16];
static int jw_turn_n;
static void jw_turns_read(void) {
    static int64_t at;
    const int64_t now = hos_now_ns();
    if (now - at < 1000000000LL) return;
    at = now;
    const char *home = getenv("HOME");
    char path[512], line[128];
    snprintf(path, sizeof path, "%s/.app/pc_port/triforce-runs/sword_turn.txt", home ? home : "");
    FILE *f = fopen(path, "r");
    int n = 0;
    while (f && n < 16 && fgets(line, sizeof line, f)) {
        unsigned long long a;
        char h, ax;
        double deg;
        /* (A: any bone of anything that caller asks for; t: the place raised that many metres instead of a turn) */
        if (sscanf(line, "%llx %c %c %lf", &a, &h, &ax, &deg) == 4 && (h == 'L' || h == 'R' || h == 'B' || h == 'A') &&
            ((ax >= 'x' && ax <= 'z') || (ax >= 'X' && ax <= 'Z') || ax == 't'))   /* (X|Y|Z: that axis flipped) */
            jw_turn[n].at = a, jw_turn[n].hand = h == 'L' ? 1 : h == 'R' ? 2 : h == 'B' ? 3 : 4,
            jw_turn[n].ax = ax == 't' ? 3 : ax >= 'x' ? ax - 'x' : 4 + ax - 'X',
            jw_turn[n].deg = deg, n++;
    }
    if (f) fclose(f);
    static char last[256];
    char now_s[256] = "";
    for (int k = 0, o = 0; k < n && o < 200; k++)
        o += snprintf(now_s + o, sizeof now_s - o, " %llx:%d:%c:%g", (unsigned long long)jw_turn[k].at, jw_turn[k].hand,
                      jw_turn[k].ax == 3 ? 't' : jw_turn[k].ax >= 4 ? 'X' + jw_turn[k].ax - 4 : 'x' + jw_turn[k].ax, jw_turn[k].deg);
    if (strcmp(now_s, last)) hos_log("vr: body: sword turn:%s", n ? now_s : " none"), snprintf(last, sizeof last, "%s", now_s);
    jw_turn_n = n;
}
static struct { uint64_t at; int64_t n; } jw_all[128];
static int jw_all_n;
static int64_t jw_all_told;
static void jw_all_note(Ctx *c) {
    static SRWLOCK lk = SRWLOCK_INIT;
    const uint64_t caller = c->x[30];
    AcquireSRWLockExclusive(&lk);
    int i = 0;
    while (i < jw_all_n && jw_all[i].at != caller) i++;
    if (i == jw_all_n && jw_all_n < 128) jw_all[jw_all_n++].at = caller;
    if (i < 128) jw_all[i].n++;
    jw_turns_read();
    const int64_t now = hos_now_ns();
    if (now - jw_all_told > 5000000000LL) {
        if (jw_all_told) {
            char line[4096];
            int o = snprintf(line, sizeof line, "vr: body: bone reads by caller in 5 s:");
            for (int k = 0; k < jw_all_n && o < (int)sizeof line - 40; k++)
                if (jw_all[k].n) o += snprintf(line + o, sizeof line - o, " %llx=%lld", (unsigned long long)jw_all[k].at, (long long)jw_all[k].n);
            hos_log("%s", line);
        }
        jw_all_told = now;
        for (int k = 0; k < jw_all_n; k++) jw_all[k].n = 0;
    }
    ReleaseSRWLockExclusive(&lk);
}
static void jw_apply(Ctx *c, uint64_t out, int ax, double v) {
    if (!plausible(out, 48)) return;
    if (ax == 3) {
        st_f(c, out + 16 + 12, ld_f(c, out + 16 + 12) + v);
        return;
    }
    if (ax >= 4) {
        for (int row = 0; row < 3; row++) st_f(c, out + (uint64_t)row * 16 + (uint64_t)(ax - 4) * 4, -ld_f(c, out + (uint64_t)row * 16 + (uint64_t)(ax - 4) * 4));
        return;
    }
    const double r = v * 3.14159265358979 / 180.0, cs = cos(r), sn = sin(r);
    const int a = (ax + 1) % 3, b = (ax + 2) % 3;   /* (the two columns the turn mixes) */
    for (int row = 0; row < 3; row++) {
        const uint64_t ra = out + (uint64_t)row * 16;
        const double va = ld_f(c, ra + (uint64_t)a * 4), vb = ld_f(c, ra + (uint64_t)b * 4);
        st_f(c, ra + (uint64_t)a * 4, va * cs + vb * sn), st_f(c, ra + (uint64_t)b * 4, -va * sn + vb * cs);
    }
}
/* (research, SPINE-FLIP: while triforce-runs/spine_flip.txt exists and the mirror is on, a center bone (one that is its own
   left/right partner: the spine, neck, head, waist) read by the game comes back with its sideways (z) axis turned round: the
   reflection of the game's own frame, as the trail's renderer fix draws it, for what the game itself works out from those bones
   (a spin's way round, a sidestep's) */
static int spine_flip_on(void) {
    static int on = -1;
    static int64_t looked;
    const int64_t now = hos_now_ns();
    if (now - looked > 1000000000LL) {
        looked = now;
        char path[512];
        const char *home = getenv("HOME");
        snprintf(path, sizeof path, "%s/.app/pc_port/triforce-runs/spine_flip.txt", home ? home : "");
        FILE *f = fopen(path, "r");
        const int v = f != NULL;
        if (f) fclose(f);
        if (v != on) hos_log("vr: body: center bones' reads %s", v ? "reflected (spine_flip.txt)" : "as the mirror leaves them");
        on = v;
    }
    return on;
}
void hos_oot_joint_world(Ctx *c) {
    if (spine_flip_on() && ma.parts && ma_wanted() && plausible(c->x[0] + 0xf8, 8)) {
        const uint64_t bones = recomp_load64(c, c->x[0] + 0xf8);
        const int bone = (int)(int32_t)c->x[2];
        for (int i = 0; i < ma.parts; i++)
            if (ma.part[i].bones == bones) {
                if (bone >= 0 && bone < ma.part[i].n && ma.part[i].mate[bone] == bone) jw_apply(c, c->x[1], 6, 0);
                break;
            }
    }
    jw_all_note(c);
    if (jw_turn_n)
        for (int k = 0; k < jw_turn_n; k++)
            if (jw_turn[k].hand == 4 && jw_turn[k].at == c->x[30]) jw_apply(c, c->x[1], jw_turn[k].ax, jw_turn[k].deg);
    if (!ma.parts || !ma_wanted()) return;
    const MaPart *mp = &ma.part[0];
    const int bone = (int)(int32_t)c->x[2];
    if (bone != mp->hand_l && bone != mp->hand_r) return;
    if (!plausible(c->x[0] + 0xf8, 8) || recomp_load64(c, c->x[0] + 0xf8) != mp->bones) return;
    const uint64_t caller = c->x[30], out = c->x[1];
    static SRWLOCK lock = SRWLOCK_INIT;
    AcquireSRWLockExclusive(&lock);
    int i = 0;
    while (i < jw_n && jw_callers[i].at != caller) i++;
    if (i == jw_n && jw_n < 32) jw_callers[jw_n++].at = caller;
    if (i < 32) jw_callers[i].n[bone == mp->hand_r]++;
    const int hand = bone == mp->hand_l ? 1 : 2;
    for (int k = 0; k < jw_turn_n; k++) {
        if (jw_turn[k].hand == 4 || (jw_turn[k].at && jw_turn[k].at != caller) || !(jw_turn[k].hand & hand)) continue;
        jw_apply(c, out, jw_turn[k].ax, jw_turn[k].deg);
    }
    const int64_t now = hos_now_ns();
    if (now - jw_told > 5000000000LL) {
        if (jw_told)
            for (int k = 0; k < jw_n; k++)
                if (jw_callers[k].n[0] + jw_callers[k].n[1])
                    hos_log("vr: body: hands asked for by %#llx: Weapon_L %lld, Weapon_R %lld in 5 s", (unsigned long long)jw_callers[k].at,
                            (long long)jw_callers[k].n[0], (long long)jw_callers[k].n[1]);
        jw_told = now;
        for (int k = 0; k < jw_n; k++) jw_callers[k].n[0] = jw_callers[k].n[1] = 0;
    }
    ReleaseSRWLockExclusive(&lock);
}

/* the world pass's start (f_81501400, x0 the skeleton, x1..x2 its bones: its ranges may run on several workers): his
   locals mirrored before any of his worlds is made from them; the lock waited for, so no range reads them half done */
void hos_oot_world_pass(Ctx *c) {
    if (!ma.parts) return;
    const uint64_t bones = c->x[0];
    int i = 0;
    while (i < ma.parts && ma.part[i].bones != bones) i++;
    if (i == ma.parts || !ma_wanted()) return;
    {   /* ((Triforce VR) aiming: the game turns his upper body to the aim after the arms' hook, which the mirror would turn the
           other way; the arms put on the controllers again here, just before the mirror (the hook leaves at once if nothing
           has rewritten his arms since) */
        int vr_game_aiming(void);
        void hos_oot_after_anim(Ctx *c);
        if (i == 0 && vr_game_aiming()) {
            static int told;
            if (!told++) hos_log("vr: body: aiming: the arms put on the controllers again before the mirror");
            arms_forced = 1, hos_oot_after_anim(c), arms_forced = 0;
        }
    }
    AcquireSRWLockExclusive(&ma_lock);
    MaPart *mp = &ma.part[i];
    if (i < ma.parts && mp->bones == bones && recomp_load64(c, bones) == mp->res && plausible(ma.actor, 0x330) &&
        recomp_load64(c, ma.actor) == 0x84b45e18ULL) {
        const uint64_t slots = recomp_load64(c, bones + 0x18);
        int fresh = !mp->written;
        for (int b = 0; !fresh && b < mp->n; b++) fresh = !ma_same(c, slots, mp, b);
        if (fresh) {
            const int part = ma_part_index(c, bones);
            if (part >= 0) ma_part_mirror(c, part, mp);
        } else ma_skipped++;
    }
    const int64_t now = hos_now_ns();
    if (now - ma.told_at > 5000000000LL) {
        if (ma.told_at) hos_log("vr: body: mirrored animation: %lld poses mirrored in 5 s, %lld world passes with nothing new", (long long)ma_done, (long long)ma_skipped);
        ma.told_at = now, ma_done = ma_skipped = 0;
    }
    ReleaseSRWLockExclusive(&ma_lock);
}

void vr_body_lift(Ctx *c, uint64_t actor) {
    ma_seen(c, actor);
    const MkwVkXr *x = rx_xr();
    if (!x || !x->hands || !x->active) return;
    const int on = x->active();   /* (no session: no bones looked for; what was hidden is shown again) */
    if (on) pose_cache(c, actor);
    const int fp = on && vr_first_person_now() && !vr_game_paused();   /* ((Triforce VR) the menus show him whole) */
    head_materials_set(c, fp && body_arms());
    hide_back_items(c, actor, fp);
}

/* (the One-Euro filter (Casiez, Roussel, Vogel 2012) on a 3-vector, in place: a low-pass whose cut-off rises with the
   speed: min_cut Hz when still, plus beta per unit a second of movement; the speed itself low-passed at 1 Hz. A gap
   (dt not between 1 ms and 0.2 s) starts it again) */
typedef struct { double x[3], dx[3]; int init; } Euro;
static void euro3(Euro *f, double v[3], double dt, double min_cut, double beta) {
    if (f->init && dt >= 0 && dt < 0.002) {   /* (a second pass in the same frame: this frame's value again) */
        memcpy(v, f->x, sizeof f->x);
        return;
    }
    if (!f->init || dt > 0.2) {
        memcpy(f->x, v, sizeof f->x), memset(f->dx, 0, sizeof f->dx), f->init = 1;
        return;
    }
    const double pi2 = 6.283185307179586;
    const double ad = 1.0 / (1.0 + 1.0 / (pi2 * 1.0 * dt));
    double speed = 0;
    for (int k = 0; k < 3; k++) {
        f->dx[k] += ad * ((v[k] - f->x[k]) / dt - f->dx[k]);
        speed += f->dx[k] * f->dx[k];
    }
    const double a = 1.0 / (1.0 + 1.0 / (pi2 * (min_cut + beta * sqrt(speed)) * dt));
    for (int k = 0; k < 3; k++) f->x[k] += a * (v[k] - f->x[k]), v[k] = f->x[k];
}

/* the hand's grip: turned -90 degrees about its palm's axis, so what it holds stands out of the fist as from a held
   controller (without it the sword and the shield, which Link holds across his fist, pointed back at the player) */
#define HAND_GRIP_DEG (-90.0)
/* the hands' distance on a two-handed hilt (metres) */
#define HILT_SPACING 0.10
/* ((Triforce VR) what both hands hold, as the game's own animation holds it (Link left-handed, the mirror off): the holding
   (left) wrist's turn in his root's frame (rows), the other (right) wrist's place in the holding wrist's frame (metres), and
   its turn in that frame (rows). In VR the thing points from the holding hand's controller to the other's, the holding wrist
   turned the least from the game's hold that does it, and the other wrist set where the game has it on the thing */
typedef struct { double L[9], o[3], R[9]; } Grip;
/* (generated from vr_research/hand_capture/*.txt, 2026-11-26: Link hidden, the mirror off, the game's own hold) */
static const Grip GRIP_BIGGORON_CHILD = {{0.3071, -0.3371, -0.8900, -0.9143, 0.1550, -0.3742, 0.2641, 0.9286, -0.2606}, {-0.1372, 0.1506, 0.3991}, {-0.8102, -0.2075, -0.5483, -0.2055, -0.7753, 0.5972, -0.5490, 0.5965, 0.5855}};
static const Grip GRIP_STICK_CHILD = {{-0.2794, 0.3076, -0.9096, 0.1452, 0.9499, 0.2767, 0.9491, -0.0548, -0.3101}, {0.0188, -0.0655, 0.0932}, {-0.8138, -0.1347, 0.5653, 0.0676, -0.9881, -0.1381, 0.5772, -0.0742, 0.8132}};
static const Grip GRIP_BIGGORON_ADULT = {{-0.3929, 0.4328, -0.8114, -0.0885, 0.8605, 0.5018, 0.9153, 0.2689, -0.2998}, {0.0511, -0.2393, 0.1344}, {-0.7637, 0.0385, 0.6445, -0.0131, -0.9989, 0.0442, 0.6455, 0.0253, 0.7633}};
static const Grip GRIP_HAMMER_ADULT = {{0.0503, 0.2819, 0.9581, -0.9330, -0.3290, 0.1459, 0.3564, -0.9012, 0.2465}, {0.0151, -0.5284, -0.0191}, {-0.3324, 0.0127, -0.9431, 0.0052, -0.9999, -0.0153, -0.9431, -0.0100, 0.3323}};
/* the head sunk this far into the chest (metres), in the neck's frame */
#define HEAD_SINK 0.25

static volatile double neck_height;
static volatile int64_t neck_at;
/* ((Triforce VR) vr_game.c: Link as his movement update found him, 0 before (the game's own pointer to him is filled later at a
   start from a file) */
uint64_t vr_body_link(void) { return ob.valid ? ob.actor : 0; }
int vr_body_neck_height(double *height) {
    if (!neck_at || hos_now_ns() - neck_at > 200000000LL) return 0;
    *height = neck_height;
    return isfinite(*height);
}

/* (HANDS-CAPTURE, research: Link hidden (Visibility Hidden), so his arms are the game's own animation, and a file
   ~/.app/pc_port/triforce-runs/hand_capture.txt there: twice a second his wrists' and root's world entries (rows of 3x4) and
   what he holds, for the two-handed things' hands) */
static void hands_capture(Ctx *c) {
    static int64_t at, looked;
    static int on;
    const int64_t now = hos_now_ns();
    if (now - looked > 1000000000LL) {
        looked = now;
        char path[512];
        const char *home = getenv("HOME");
        snprintf(path, sizeof path, "%s/.app/pc_port/triforce-runs/hand_capture.txt", home ? home : "");
        FILE *f = fopen(path, "r");
        on = f != NULL;
        if (f) fclose(f);
    }
    if (!on || now - at < 500000000LL) return;
    at = now;
    char line[1600];
    int n = snprintf(line, sizeof line, "vr: hands capture: %s \"%s\" mirror %d", vr_game_childhood() ? "child" : "adult", vr_game_held(), ma.parts && ma_wanted());
    static const int bones[3] = {OB_ROOT, OB_WRIST_L, OB_WRIST_R};
    static const char *const names[3] = {"root", "L", "R"};
    for (int b = 0; b < 3 && n < (int)sizeof line - 200; b++) {
        Xf w;
        xf_load(c, ob.world[bones[b]], &w);
        n += snprintf(line + n, sizeof line - n, " %s", names[b]);
        for (int r = 0; r < 3; r++)
            for (int k = 0; k < 4; k++) n += snprintf(line + n, sizeof line - n, " %.4f", w.m[r][k]);
    }
    hos_log("%s", line);
}

void hos_oot_after_anim(Ctx *c) {
    /* (it follows every model's late bone pass, hundreds a frame: the cheapest checks first) */
    if (!ob.valid || !vr_first_person_now()) return;
    const MkwVkXr *x = rx_xr();
    if (!x || !x->hands) return;
    /* ((Triforce VR) Link hidden: only his neck's height, for the eyes while he crouches, a few times a frame at most) */
    const int arms = body_arms();
    if (!arms && hos_now_ns() - neck_at < 4000000LL) return;
    /* (quick, for every model's pass: Link's slots as this hook left them: the animation has not been back, leave) */
    if (arms && !arms_forced && ob_unchanged(c, OB_ARM1_L) && ob_unchanged(c, OB_ARM1_R) && ob_unchanged(c, OB_HEAD)) return;
    if (!TryAcquireSRWLockExclusive(&ob_lock)) return;
    /* (the cache still Link's: a level change frees his model before the movement update notices; never write a freed one) */
    if (!ob.valid || !plausible(ob.actor, 0x330) || recomp_load64(c, ob.actor) != 0x84b45e18ULL ||
        vr_call(c, 0x80994de0ULL, ob.actor, 0, 0, 0) != ob.model) {
        ob.valid = 0;
        ReleaseSRWLockExclusive(&ob_lock);
        return;
    }
    static int64_t runs;
    if (runs++ == 0) hos_log("vr: body: the arms' hook after the late bone pass runs");
    if (ob.neck_world) {   /* (his neck's height over his feet, before the head is sunk: first person's eyes while he crouches) */
        Xf nk;
        xf_load(c, ob.neck_world, &nk);
        neck_height = nk.m[1][3] + ld_f(c, ob.origin + 4) - ld_f(c, ob.actor + 0x31c + 4);
        neck_at = hos_now_ns();
    }
    if (!arms) {
        hands_capture(c);
        ReleaseSRWLockExclusive(&ob_lock);
        return;
    }
    /* the head to a thousandth, sunk into the chest. Not twice: a second pass in the same frame finds it shrunk already */
    Xf head_now;
    xf_load(c, ob.slot[OB_HEAD] + 0x20, &head_now);
    const double head_scale = sqrt(head_now.m[0][0] * head_now.m[0][0] + head_now.m[1][0] * head_now.m[1][0] + head_now.m[2][0] * head_now.m[2][0]);
    if (!ob_unchanged(c, OB_HEAD) && head_scale > 0.01) {
        Xf h = head_now, neck, neck_inv;
        for (int r = 0; r < 3; r++)
            for (int k = 0; k < 3; k++) h.m[r][k] *= 0.001;
        if (ob.neck_world) {
            xf_load(c, ob.neck_world, &neck);
            if (xf_inv(&neck, &neck_inv)) {
                double down[3] = {0, -HEAD_SINK, 0};
                xf_dir(&neck_inv, down, down);
                for (int r = 0; r < 3; r++) h.m[r][3] += down[r];
            }
        }
        ob_write(c, OB_HEAD, &h);
    }
    double hand[6], point[6], palm[6], cam_feet[3];
    /* ((Triforce VR) a bow or slingshot drawn, a hammer swing: his arms the game's animation for now (the shot's own pose),
       his head still hidden */
    const int arms_own = x->arms_own && x->arms_own();
    if (!arms_own && x->hands(hand, point, palm) && vr_play_anchor(cam_feet)) {
        /* the hands were placed from where Link stood at the camera update: moved by however far he has gone since (a
           run's frame is ~8 cm), and smoothed relative to him, so only the hand's own motion is smoothed (One-Euro: still
           hands lose their tremor, moving ones keep up) */
        static Euro f_pos[2], f_point[2], f_palm[2];
        static int64_t smoothed_at;
        const int64_t now_s = hos_now_ns();
        const double dt = smoothed_at ? (now_s - smoothed_at) / 1e9 : 0;
        smoothed_at = now_s;
        double link_now[3];
        for (int k = 0; k < 3; k++) link_now[k] = ld_f(c, ob.actor + 0x31c + k * 4);
        const int anchored = fabs(link_now[0] - cam_feet[0]) + fabs(link_now[2] - cam_feet[2]) < 2.0;
        for (int h = 0; h < 2; h++) {
            if (hand[h * 3] == 0 && hand[h * 3 + 1] == 0 && hand[h * 3 + 2] == 0) {
                f_pos[h].init = f_point[h].init = f_palm[h].init = 0;
                continue;
            }
            if (anchored)
                for (int k = 0; k < 3; k++) hand[h * 3 + k] += link_now[k] - cam_feet[k];
            double rel[3];
            for (int k = 0; k < 3; k++) rel[k] = hand[h * 3 + k] - link_now[k];
            euro3(&f_pos[h], rel, dt, 1.0, 0.8);
            for (int k = 0; k < 3; k++) hand[h * 3 + k] = rel[k] + link_now[k];
            euro3(&f_point[h], point + h * 3, dt, 1.5, 0.4);
            euro3(&f_palm[h], palm + h * 3, dt, 1.5, 0.4);
        }
        const Grip *grip = NULL;   /* ((Triforce VR) the game's own hold of what both hands hold, NULL: the old placing below */
        {   /* ((Triforce VR) held in both hands: the Biggoron's Sword out (not while it is the shield alone that is), the hammer, the Deku
               Stick: the other hand on its handle under the holding one (along where that one points, the handle's way), its palm
               to it from the other side, wherever its controller is */
            static int64_t asked_at;
            static int big;
            if (now_s - asked_at > 100000000LL) asked_at = now_s, big = vr_game_two_handed();
            const char *item = body_cfg("VR_TWO_HANDS");
            const int by_item = !strcmp(item, "left") || !strcmp(item, "right");
            const int both = by_item || (big && weapon_drawn && strcmp(item, "alone"));
            if (both) {
                const char *held = vr_game_held();
                grip = strstr(held, "Hammer") ? &GRIP_HAMMER_ADULT : strstr(held, "DekuStick") ? &GRIP_STICK_CHILD
                       : vr_game_childhood() ? &GRIP_BIGGORON_CHILD : &GRIP_BIGGORON_ADULT;
            }
            const int sw = by_item ? !strcmp(item, "right") : vr_sword_right() ? 1 : 0, o = 1 - sw;
            double along[3] = {point[sw * 3], point[sw * 3 + 1], point[sw * 3 + 2]};
            if (both && !grip && (hand[sw * 3] != 0 || hand[sw * 3 + 1] != 0 || hand[sw * 3 + 2] != 0) && v3_norm(along))
                for (int k = 0; k < 3; k++) {
                    hand[o * 3 + k] = hand[sw * 3 + k] - along[k] * HILT_SPACING;
                    point[o * 3 + k] = along[k], palm[o * 3 + k] = -palm[sw * 3 + k];
                }
        }
        M3 off;
        m3_axis((double[3]){0, 0, 1}, HAND_GRIP_DEG * 3.14159265358979 / 180, off);
        double stretch = atoi(body_cfg("VR_ARM_REACH")) / 100.0;
        if (!(stretch >= 1.0 && stretch <= 2.0)) stretch = 1.35;
        /* Link's frame now: the root's last world entry turned as it was, at his place now (the origin's offset taken off) */
        Xf root, root_now, root_inv;
        xf_load(c, ob.world[OB_ROOT], &root);
        root_now = root;
        const double origin[3] = {ld_f(c, ob.origin), ld_f(c, ob.origin + 4), ld_f(c, ob.origin + 8)};
        for (int r = 0; r < 3; r++) root_now.m[r][3] = link_now[r] - origin[r];
        /* each arm its own side's controller; with his animation mirrored (ma_wanted) each arm as posed here becomes the
           other side's once mirrored, so it takes the other controller reflected through his body, and ends on its own */
        const int mirrored = ma.parts && ma_wanted();
        Xf root_now_inv;
        const int have_inv = xf_inv(&root_now, &root_now_inv);
        /* ((Triforce VR) a grip: both arms' targets first (as below), the thing's way between them, then each wrist's turn and
           the other wrist's place (gripped: the wrists' turns in the world, set after each arm's reach) */
        int gripped = 0;
        M3 grip_turn[2];
        double grip_off[3];
        if (grip && have_inv) {
            double Tg[2][3];
            int ok = 1;
            for (int s = 0; s < 2 && ok; s++) {
                const int h = mirrored ? 1 - s : s;
                if (hand[h * 3] == 0 && hand[h * 3 + 1] == 0 && hand[h * 3 + 2] == 0) ok = 0;
                double pt[3] = {point[h * 3], point[h * 3 + 1], point[h * 3 + 2]};
                const int have_pt = v3_norm(pt);
                for (int k = 0; k < 3; k++) Tg[s][k] = hand[h * 3 + k] - origin[k] - (have_pt ? pt[k] * 0.03 : 0);
                if (mirrored) xf_pt(&root_now_inv, Tg[s], Tg[s]), Tg[s][0] = -Tg[s][0], xf_pt(&root_now, Tg[s], Tg[s]);
            }
            double u[3] = {Tg[1][0] - Tg[0][0], Tg[1][1] - Tg[0][1], Tg[1][2] - Tg[0][2]};
            if (ok && v3_norm(u)) {
                M3 Rr, Lr, RL, S, relR;
                m3_of(&root_now, Rr);
                for (int i = 0; i < 9; i++) Lr[i / 3][i % 3] = grip->L[i], relR[i / 3][i % 3] = grip->R[i];
                m3_mul(Rr, Lr, RL);
                double oh[3] = {grip->o[0], grip->o[1], grip->o[2]}, a[3];
                v3_norm(oh);
                m3_v(RL, oh, a);
                m3_between(a, u, S);
                m3_mul(S, RL, grip_turn[0]);
                m3_mul(grip_turn[0], relR, grip_turn[1]);
                m3_v(grip_turn[0], grip->o, grip_off);
                for (int k = 0; k < 3; k++) grip_off[k] += Tg[0][k];
                gripped = 1;
            }
        }
        if (xf_inv(&root, &root_inv))
            for (int s = 0; s < 2; s++) {   /* (s 0: Link's left arm; 1: his right) */
                const int h = mirrored ? 1 - s : s;   /* (the controller: 0 left, 1 right) */
                if (hand[h * 3] == 0 && hand[h * 3 + 1] == 0 && hand[h * 3 + 2] == 0) continue;   /* (not tracked: his own) */
                const int clav = s ? OB_CLAV_R : OB_CLAV_L, b1 = s ? OB_ARM1_R : OB_ARM1_L;
                const double side = s ? -1 : 1;
                /* the clavicle now: its last frame in Link's frame, carried to where he is now */
                Xf cw, cm, cn, cinv, L1, L2, L3;
                xf_load(c, ob.world[clav], &cw);
                xf_mul(&root_inv, &cw, &cm);
                xf_mul(&root_now, &cm, &cn);
                {   /* ((Triforce VR) mirrored: the worlds are the mirrored pose's, the other side's clavicle reflected, off by any
                       turn of his upper body (the aim's) the other way; the clavicle as the animation has it instead (MaPart Mo),
                       through his root as the animation has it (the mirrored root's world taken back through Mmir, on through Mo) */
                    const MaPart *mp = &ma.part[0];
                    const int bc = (int16_t)(ob.id[clav] >> 16), br = (int16_t)(ob.id[OB_ROOT] >> 16);
                    Xf mri, base, rpre, moi;
                    if (mirrored && mp->written && bc >= 0 && bc < mp->n && br >= 0 && br < mp->n && xf_inv(&mp->Mmir[br], &mri) &&
                        xf_inv(&mp->Mo[br], &moi)) {
                        xf_mul(&root, &mri, &base);   /* (model to world, relative to the origin) */
                        xf_mul(&base, &mp->Mo[br], &rpre);
                        for (int r = 0; r < 3; r++) rpre.m[r][3] = root_now.m[r][3];
                        xf_mul(&moi, &mp->Mo[bc], &cm);
                        xf_mul(&rpre, &cm, &cn);
                    }
                }
                if (!xf_inv(&cn, &cinv)) continue;
                /* the wrist's target: the controller, a little back from it along where it points */
                double pt[3] = {point[h * 3], point[h * 3 + 1], point[h * 3 + 2]};
                const int have_pt = v3_norm(pt);
                double T[3];
                for (int k = 0; k < 3; k++) T[k] = hand[h * 3 + k] - origin[k] - (have_pt ? pt[k] * 0.03 : 0);
                double Nm[3] = {palm[h * 3], palm[h * 3 + 1], palm[h * 3 + 2]};
                if (mirrored && have_inv) {   /* (the target, its pointing and its palm reflected in his x) */
                    xf_pt(&root_now_inv, T, T), T[0] = -T[0], xf_pt(&root_now, T, T);
                    xf_dir(&root_now_inv, pt, pt), pt[0] = -pt[0], xf_dir(&root_now, pt, pt);
                    xf_dir(&root_now_inv, Nm, Nm), Nm[0] = -Nm[0], xf_dir(&root_now, Nm, Nm);
                }
                if (gripped && s == 1) for (int k = 0; k < 3; k++) T[k] = grip_off[k];   /* (the other wrist where the game grips) */
                xf_pt(&cinv, T, T);
                /* the elbow's pole in Link's frame: down, out to his side and a little back; then in the clavicle's */
                double P[3] = {side * 0.35, -1, -0.3}, D[3], N[3] = {Nm[0], Nm[1], Nm[2]};
                xf_dir(&root_now, P, P), xf_dir(&cinv, P, P);
                if (have_pt) xf_dir(&cinv, pt, D);
                const int have_palm = v3_norm(N);
                if (have_palm) xf_dir(&cinv, N, N);
                xf_load(c, ob.slot[b1] + 0x20, &L1);
                xf_load(c, ob.slot[b1 + 1] + 0x20, &L2);
                xf_load(c, ob.slot[b1 + 2] + 0x20, &L3);
                for (int j = 0; j < 2; j++) {   /* (the bones' own lengths: the shortest seen, never a stretched one) */
                    const Xf *L = j ? &L3 : &L2;
                    const double len = sqrt(L->m[0][3] * L->m[0][3] + L->m[1][3] * L->m[1][3] + L->m[2][3] * L->m[2][3]);
                    if (len > 0.01 && (ob.rest[s][j] <= 0 || len < ob.rest[s][j])) ob.rest[s][j] = len;
                }
                ik_arm(&L1, &L2, &L3, T, P, have_pt ? D : NULL, side, have_pt && have_palm ? N : NULL, off, stretch, ob.rest[s]);
                if (gripped) {   /* (the wrist turned as the grip has it: its local = (clavicle arm forearm)^-1 the turn) */
                    M3 Rc, R1, R2, P12, Pc, Pt, W;
                    m3_of(&cn, Rc), m3_of(&L1, R1), m3_of(&L2, R2);
                    m3_mul(R1, R2, P12), m3_mul(Rc, P12, Pc), m3_t(Pc, Pt);
                    m3_mul(Pt, grip_turn[s], W);
                    m3_set(&L3, W);
                }
                ob_write(c, b1, &L1), ob_write(c, b1 + 1, &L2), ob_write(c, b1 + 2, &L3);
            }
        static int arms_logged;
        if (!arms_logged++) hos_log("vr: body: Link's arms follow the controllers");
    }
    ob_snap(c, OB_ARM1_L), ob_snap(c, OB_ARM1_R), ob_snap(c, OB_HEAD);
    ReleaseSRWLockExclusive(&ob_lock);
}

