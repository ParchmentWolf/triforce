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

/* ---- the game's memory, and calls into its code ---- */
static int plausible(uint64_t a, uint64_t n) {
    return (a >= HOS_HEAP_BASE && a + n > a && a + n <= (uint64_t)HOS_SPACE_END) || (a >= hos_image_base && a + n <= hos_image_end);
}
static float ld_f(Ctx *c, uint64_t a) {
    const uint32_t b = recomp_load32(c, a);
    float f;
    memcpy(&f, &b, 4);
    return f;
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
   (Mt_Cloth) and its knot, the collar Angin_Parts_Collar_R (Mt_Cloth_Parts), the feather, the shoulder belt) */
static const char *const head_materials[] = {
    "Mt_Hairs",        "Mt_Face",         "Mt_Face_SoftEdge", "Mt_Face_Eyelid", "Mt_Eye_Outer", "Mt_Eye_Inner",
    "Mt_Eyelashes",    "Mt_Eyelashes_01", "Mt_Eyelashes_02",  "Mt_Eyelashes_03", "Mt_Eyeshadow", "Mt_EyeShadow_test",
    "Mt_Eyebrow",      "Mt_Teeth",        "Mt_Angin",         "Mt_Cloth",       "Mt_Cloth_Parts_AlphaMask", "Mt_Cloth_Parts",
    "Mt_Vest",         "Mt_Leater_Upper", "Mt_Leather_Upper_Metal", "Mt_Angin_Acs", "Mt_Angin_Acs_AlphaMask", "Mt_Feather",
    "Mt_ShoulderBelt"};
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
    {"Armor_Adult_Goron", 0, {"Mt_Leather", "Mt_Vest", "Mt_Beads_A", "Mt_Beads_B", "Mt_HoodAcs", "Mt_Leater_Upper", "Mt_Leather_Upper_Metal"}},
    {"Armor_Adult_Zora", 0, {"Mt_Angin", "Mt_Angin_Acs", "Mt_Vest", "Mt_Feather", "Mt_Parts", "Mt_Leater_Upper", "Mt_Leather_Upper_Metal"}},
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
        if (changed) {
            for (int i = 0; i < m; i++) hidden[i] = -1;
            memcpy(found, got, sizeof got[0] * m), n = m;
            if (logs < 20) logs++, hos_log("vr: body: %d things he carries or wears found (weapons, tunic, glasses, mask)", m);
        }
    }
    const int drawn = first_person ? weapons_drawn(c, link) : -1;
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

void vr_body_lift(Ctx *c, uint64_t actor) {
    const MkwVkXr *x = rx_xr();
    if (!x || !x->hands || !x->active) return;
    const int on = x->active();   /* (no session: no bones looked for; what was hidden is shown again) */
    if (on) pose_cache(c, actor);
    const int fp = on && vr_first_person_now();
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
/* the head sunk this far into the chest (metres), in the neck's frame */
#define HEAD_SINK 0.25

void hos_oot_after_anim(Ctx *c) {
    /* (it follows every model's late bone pass, hundreds a frame: the cheapest checks first) */
    if (!ob.valid || !vr_first_person_now()) return;
    const MkwVkXr *x = rx_xr();
    if (!x || !x->hands || !body_arms()) return;
    /* (quick, for every model's pass: Link's slots as this hook left them: the animation has not been back, leave) */
    if (ob_unchanged(c, OB_ARM1_L) && ob_unchanged(c, OB_ARM1_R) && ob_unchanged(c, OB_HEAD)) return;
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
    if (x->hands(hand, point, palm) && vr_play_anchor(cam_feet)) {
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
        /* his left arm holds the sword: the sword hand's controller (VR_HANDEDNESS), his right the other */
        const int sword = !strcmp(body_cfg("VR_HANDEDNESS"), "right");
        if (xf_inv(&root, &root_inv))
            for (int s = 0; s < 2; s++) {   /* (s 0: Link's left arm, the sword's; 1: his right, the shield's) */
                const int h = s == 0 ? sword : 1 - sword;   /* (the controller: 0 left, 1 right) */
                if (hand[h * 3] == 0 && hand[h * 3 + 1] == 0 && hand[h * 3 + 2] == 0) continue;   /* (not tracked: his own) */
                const int clav = s ? OB_CLAV_R : OB_CLAV_L, b1 = s ? OB_ARM1_R : OB_ARM1_L;
                const double side = s ? -1 : 1;
                /* the clavicle now: its last frame in Link's frame, carried to where he is now */
                Xf cw, cm, cn, cinv, L1, L2, L3;
                xf_load(c, ob.world[clav], &cw);
                xf_mul(&root_inv, &cw, &cm);
                xf_mul(&root_now, &cm, &cn);
                if (!xf_inv(&cn, &cinv)) continue;
                /* the wrist's target: the controller, a little back from it along where it points */
                double pt[3] = {point[h * 3], point[h * 3 + 1], point[h * 3 + 2]};
                const int have_pt = v3_norm(pt);
                double T[3];
                for (int k = 0; k < 3; k++) T[k] = hand[h * 3 + k] - origin[k] - (have_pt ? pt[k] * 0.03 : 0);
                xf_pt(&cinv, T, T);
                /* the elbow's pole in Link's frame: down, out to his side and a little back; then in the clavicle's */
                double P[3] = {side * 0.35, -1, -0.3}, D[3], N[3] = {palm[h * 3], palm[h * 3 + 1], palm[h * 3 + 2]};
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
                ob_write(c, b1, &L1), ob_write(c, b1 + 1, &L2), ob_write(c, b1 + 2, &L3);
            }
        static int arms_logged;
        if (!arms_logged++) hos_log("vr: body: Link's arms follow the controllers");
    }
    ob_snap(c, OB_ARM1_L), ob_snap(c, OB_ARM1_R), ob_snap(c, OB_HEAD);
    ReleaseSRWLockExclusive(&ob_lock);
}
