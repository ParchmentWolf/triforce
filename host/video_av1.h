/* (Triforce, 11-22, the performance audit's IO-32, after Source A's) Which AV1 decoder a movie gets first on Windows
   (nn_video.c dec_init_sized).

   The game's movies are 1080p AV1. Windows decoded them with Media Foundation first (the AV1 Video Extension, where the PC
   has it), and that path takes the extension's synchronous decoder with no D3D manager: software decoding on every GPU.
   dav1d, through the FFmpeg the build links, was the fallback for a PC without the extension, and what Linux always
   runs. It goes first now where that FFmpeg has it; Media Foundation stays the decoder of an FFmpeg without libdav1d,
   and the fallback when libdav1d does not open. HOS_AV1=mf: Media Foundation first, as before.

   The rule alone, no decoder: tests/test_video_av1_order.py compiles it. */
#pragma once
#include <string.h>

/* 1 when Media Foundation is tried before libdav1d. hos_av1: HOS_AV1's value, NULL when unset; have_dav1d: the FFmpeg
   this build links has libdav1d. (HOS_AV1=dav1d, the old way to ask for dav1d first, is the default now) */
static inline int video_av1_mf_first(const char *hos_av1, int have_dav1d) {
    if (!have_dav1d) return 1;
    return hos_av1 != NULL && !strcmp(hos_av1, "mf");
}
