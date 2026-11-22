/* (Triforce, 11-22, the performance audit's IO-36, after Source A's) A decoded movie picture kept as NV12 alone
   (nn_video.c queue_frame).

   Media Foundation's pictures come as NV12 and were kept as that: the pool makes RGBA from it only if the game reads
   RGBA (pool_rgba), which this game's movie library does not. libdav1d's come as planar 4:2:0 (Y, U and V planes), and
   each one was converted to RGBA on the movie thread all the same: a full-size swscale pass, an 8 MB allocation and
   an 8 MB row copy for a 1080p picture, with its NV12 made beside it in a zeroed buffer, one byte at a time. Planar
   4:2:0 is now kept as NV12 alone too. HOS_VIDEO_RGBA=1: its RGBA made for every picture, as before.

   The rules and the U/V interleave alone, no decoder: tests/test_video_lazy_rgba.py compiles them. */
#pragma once
#include <stddef.h>
#include <stdint.h>
#if (defined(__x86_64__) || defined(_M_X64)) && !defined(__EMSCRIPTEN__)
#include <emmintrin.h>
#define VIDEO_NV12_SSE2 1
#endif

/* 1 when a picture is kept as NV12 alone, its RGBA left to the pool that is read. nv12: the decoder gave NV12 (always
   lazy, as before); planar420: it gave planar 4:2:0 without alpha (with alpha the RGBA is made at once: one made later
   from NV12 would have lost it); eager: HOS_VIDEO_RGBA=1 */
static inline int video_rgba_lazy(int eager, int nv12, int planar420) { return nv12 || (planar420 && !eager); }

/* 1 when the picture's NV12 buffer (w * h * 3 / 2 bytes) is zeroed before it is filled. written: the format is one
   queue_frame copies into it (NV12, planar 4:2:0 with or without alpha); any other leaves it as it is, so it is zeroed,
   as the buffer always was. An odd width or height leaves bytes no copy reaches: a chroma row's last byte, and the
   rows past h / 2 */
static inline int video_nv12_zero(int w, int h, int written) { return ((w | h) & 1) != 0 || !written; }

/* One row of NV12's chroma from a row of U and a row of V: n pairs, uv[2x] = u[x] and uv[2x + 1] = v[x]. 16 pairs a
   step with SSE2 on x86-64, then one at a time */
static inline void video_uv_interleave(uint8_t *uv, const uint8_t *u, const uint8_t *v, int n) {
    int x = 0;
#ifdef VIDEO_NV12_SSE2
    for (; x + 16 <= n; x += 16) {
        const __m128i us = _mm_loadu_si128((const __m128i *)(u + x)), vs = _mm_loadu_si128((const __m128i *)(v + x));
        _mm_storeu_si128((__m128i *)(uv + 2 * (size_t)x), _mm_unpacklo_epi8(us, vs));
        _mm_storeu_si128((__m128i *)(uv + 2 * (size_t)x + 16), _mm_unpackhi_epi8(us, vs));
    }
#endif
    for (; x < n; x++) uv[2 * (size_t)x] = u[x], uv[2 * (size_t)x + 1] = v[x];
}
