/* (hookshot) NVIDIA DLSS's camera math, as plain functions: the jitter's sequence (host/rx_backend.c, in C) and the motion
   vectors' reprojection (gpu/vk/vk_dlss.cpp). No Vulkan, no NGX: tests/test_dlss_math.cpp checks them. */
#pragma once

#ifdef __cplusplus
#include <cmath>
#include <limits>
#include <utility>
#endif

/* The radical inverse of index in base: the Halton sequence's index-th value, in [0, 1) */
static inline float dlss_halton(int index, int base) {
    float f = 1.0f, r = 0.0f;
    for (int i = index; i > 0; i /= base) {
        f /= (float)base;
        r += f * (float)(i % base);
    }
    return r;
}

/* The frame's sub-pixel jitter, in pixels, each in [-0.5, 0.5): the Halton (2, 3) sequence over `phases` frames (from 1: its
   first value, 0, would put every phase's start on the pixel's corner) */
static inline void dlss_jitter_pixels(unsigned frame, int phases, float out[2]) {
    const int i = (int)(frame % (unsigned)(phases > 0 ? phases : 1)) + 1;
    out[0] = dlss_halton(i, 2) - 0.5f;
    out[1] = dlss_halton(i, 3) - 0.5f;
}

/* The frame's jitter for a projection matrix p (row major, as the game fills its views' uniform buffers: nx2/oot_jitter.py),
   in clip space (what p[0][2] and p[1][2] get) into out, for a scene of w x h pixels; 0 (none) when p is not one of the
   picture's: not perspective (its w row is not 0 0 -1 0: a shadow map's, the HUD's) or not of 16:9 or the window's ratio
   wide (0: 16:9 only), or when there is no scene size (DLSS not drawing) */
static inline int dlss_jitter_clip(const float p[16], float wide, unsigned frame, int phases, float w, float h, float out[2]) {
    if (!(w >= 1.0f) || !(h >= 1.0f)) return 0;
    if (p[12] != 0.0f || p[13] != 0.0f || p[14] != -1.0f || p[15] != 0.0f || !(p[0] > 0.0f)) return 0;
    const float r = p[5] / p[0], d = r - 16.0f / 9.0f, e = wide > 0.0f ? r - wide : 1.0f;
    if (!((d <= 0.01f && d >= -0.01f) || (e <= 0.01f && e >= -0.01f))) return 0;
    float px[2];
    dlss_jitter_pixels(frame, phases, px);
    out[0] = 2.0f * px[0] / w, out[1] = 2.0f * px[1] / h;
    return 1;
}

/* How many frames the jitter's sequence takes: NVIDIA's guide, 8 times the share of pixels DLSS fills in, (output / render)
   squared, so each output pixel is covered about 8 times; 8 at least (DLAA), 64 at most (a long sequence is seen less of
   before the camera moves) */
static inline int dlss_jitter_phases(unsigned render_w, unsigned render_h, unsigned out_w, unsigned out_h) {
    if (!render_w || !render_h) return 8;
    const double area = (double)out_w * (double)out_h / ((double)render_w * (double)render_h);
    const int n = (int)(8.0 * area + 0.5);
    return n < 8 ? 8 : n > 64 ? 64 : n;
}

#ifdef __cplusplus
namespace mkwvk::dlss_math {

/// This frame's clip space to the frame before's: previous * inverse(current), both row major (clip = M * position); false
/// when either input is not finite, current is singular, or the result cannot be represented as finite floats
inline bool reprojection(const float* current, const float* previous, float out[16]) {
    for (int i = 0; i < 16; i++)
        if (!std::isfinite(current[i]) || !std::isfinite(previous[i])) return false;
    double a[4][8];
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 8; c++) a[r][c] = c < 4 ? current[r * 4 + c] : (c - 4 == r ? 1.0 : 0.0);
    for (int c = 0; c < 4; c++) {   // (Gauss-Jordan with partial pivoting)
        int p = c;
        for (int r = c + 1; r < 4; r++)
            if (std::fabs(a[r][c]) > std::fabs(a[p][c])) p = r;
        if (std::fabs(a[p][c]) < 1e-12) return false;
        if (p != c)
            for (int k = 0; k < 8; k++) std::swap(a[p][k], a[c][k]);
        const double inv = 1.0 / a[c][c];
        for (int k = 0; k < 8; k++) a[c][k] *= inv;
        for (int r = 0; r < 4; r++) {
            if (r == c || a[r][c] == 0.0) continue;
            const double f = a[r][c];
            for (int k = 0; k < 8; k++) a[r][k] -= f * a[c][k];
        }
    }
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 4; c++) {
            double v = 0;
            for (int k = 0; k < 4; k++) v += previous[r * 4 + k] * a[k][c + 4];
            if (!std::isfinite(v) || std::fabs(v) > std::numeric_limits<float>::max()) return false;
            out[r * 4 + c] = (float)v;
        }
    return true;
}

/// A view-projection's jitter taken off (row major): a jitter moves clip x and y by jitter * w, so jitter times the w row
/// comes off the first two rows
inline void unjitter(float m[16], const float jitter[2]) {
    for (int c = 0; c < 4; c++) {
        m[0 * 4 + c] -= jitter[0] * m[3 * 4 + c];
        m[1 * 4 + c] -= jitter[1] * m[3 * 4 + c];
    }
}

/// ((Triforce, 11-20) the owner's "DLSS flicker": the whole picture and the shadows, while the camera moves, with NVIDIA
/// DLSS frame generation on, and not without it.) Streamline's camera matrices are in the clip space of the depth buffer it
/// is given: its depth value is that clip space's z over w, 1 at the near plane with depthInverted. The game's projection
/// is NVN's, clip z from -1 at the near plane to 1 at the far one, and the depth frame generation gets is FSR's copy
/// (vk_fsr3_inputs.cpp): d = (1 - ndc z) / 2 where the game's buffer has 0 at the near plane (flipped: Camera::flip_depth),
/// (ndc z + 1) / 2 where it is reversed already. Given the game's own matrices with that depth, a depth read as clip z put
/// what is far a fifth of a metre from the camera and what is near at the far plane, so whatever Streamline works out from
/// the depth and the camera's move was wrong as soon as the camera moved, and right while it stood. Only DLSS frame
/// generation takes matrices (FSR takes the near and far planes and the field of view), so nothing else showed it.
/// The depth's clip space is the game's with z' = (w - z) / 2 (flipped) or (w + z) / 2: Z * clip, Z the identity but for
/// its z row, (0 0 -1/2 1/2) or (0 0 1/2 1/2).
/// A projection (or a view-projection) into the depth's clip space: Z * m, row major (clip = M * position)
inline void depth_clip_projection(const float m[16], bool flipped, float out[16]) {
    const float s = flipped ? -0.5f : 0.5f;
    for (int i = 0; i < 16; i++) out[i] = m[i];
    for (int c = 0; c < 4; c++) out[2 * 4 + c] = s * m[2 * 4 + c] + 0.5f * m[3 * 4 + c];
}
/// A clip-to-clip matrix of the game's (this frame's clip space to the frame before's: reprojection) between the depth's
/// clip spaces: Z * m * inverse(Z), inverse(Z)'s z row (0 0 -2 1) or (0 0 2 -1). The identity stays the identity
inline void depth_clip_reprojection(const float m[16], bool flipped, float out[16]) {
    const float k = flipped ? -2.0f : 2.0f, t = flipped ? 1.0f : -1.0f;
    float r[16];
    for (int row = 0; row < 4; row++) {   // (m * inverse(Z): the z column scaled, and added to the w column)
        r[row * 4 + 0] = m[row * 4 + 0], r[row * 4 + 1] = m[row * 4 + 1];
        r[row * 4 + 2] = k * m[row * 4 + 2];
        r[row * 4 + 3] = m[row * 4 + 3] + t * m[row * 4 + 2];
    }
    depth_clip_projection(r, flipped, out);   // (Z * that)
}

/// A jitter in clip space as DLSS takes it: in render pixels, x right and y down (clip y is up)
inline void jitter_to_pixels(const float clip[2], unsigned width, unsigned height, float out[2]) {
    out[0] = clip[0] * 0.5f * (float)width;
    out[1] = -clip[1] * 0.5f * (float)height;
}

} // namespace mkwvk::dlss_math
#endif
