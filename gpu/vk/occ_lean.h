// (Triforce, 11-22, the performance audit's DESC-82, after Source B's: its first step, the census) The game's occlusion tests
// draw proxies that write no colour, and each such draw runs its whole fragment shader and fills its fragment descriptors.
// Source B makes a sibling pipeline without the fragment stage for a counted draw that writes no colour and whose fragment
// shader has no effect but colour (no depth or sample-mask output, no demote, no stores, image writes, atomics or global
// memory) and whose state has neither alpha to coverage nor an alpha test. It was never on by default nor measured; its
// census at Kakariko counted about 2,570 colour-off draws of about 3,420 counted. The entry's own order is the census first,
// and the lean pipelines only if the census finds more than one fragment descriptor a proxy to save.
//
// This is the census alone. RX_VK_OCC_LEAN=3: each draw under an open occlusion query that writes no colour is classed
// (classify: lean, or the first refusal), and its fragment stage's descriptors added to its class; every 600 presents one
// line gives each class's draws and descriptors a frame (vk_replay.cpp status_tick). No pipeline, key or descriptor changes.
// 1 (the lean pipelines) and 2 (their check) are not built: they read as off. Unset: nothing of it runs.
//
// The rules alone: tests/test_occ_lean.py compiles them.
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

namespace occ_lean {

/// RX_VK_OCC_LEAN: 3 for the census; anything else is off (1 and 2: the steps after the census, not built)
inline int mode_of(const char* e) { return e && *e && std::atoi(e) == 3 ? 3 : 0; }

enum Class { kLean, kNoFragment, kDepth, kSampleMask, kDemote, kStores, kImageWrites, kAtomics, kGlobal, kA2c, kAlphaTest, kClasses };
inline const char* const kNames[kClasses] = {"lean",   "no fragment stage", "depth out", "sample mask",       "demote",    "stores",
                                             "image writes", "atomics",     "global memory", "alpha to coverage", "alpha test"};

/// What the class reads of a draw: its fragment stage's (Shader::Info) and its state's
struct Facts {
    bool has_fragment = true;
    bool depth_out = false, sample_mask = false, demote = false, stores = false, image_writes = false, atomics = false,
         global = false;
    bool a2c = false, alpha_test = false;
};

/// The draw's class: no fragment stage (nothing to leave out), the first refusal of the shader's then of the state's, or lean
inline Class classify(const Facts& f) {
    if (!f.has_fragment) return kNoFragment;
    if (f.depth_out) return kDepth;
    if (f.sample_mask) return kSampleMask;
    if (f.demote) return kDemote;
    if (f.stores) return kStores;
    if (f.image_writes) return kImageWrites;
    if (f.atomics) return kAtomics;
    if (f.global) return kGlobal;
    if (f.a2c) return kA2c;
    if (f.alpha_test) return kAlphaTest;
    return kLean;
}

/// The counts, any recording thread (relaxed)
struct Census {
    std::atomic<uint64_t> draws[kClasses]{};
    std::atomic<uint64_t> descriptors[kClasses]{};
    void note(Class c, uint32_t frag_descriptors) {
        draws[c].fetch_add(1, std::memory_order_relaxed);
        descriptors[c].fetch_add(frag_descriptors, std::memory_order_relaxed);
    }
    /// The line for `presents` presents (draws and fragment descriptors a frame, the lean ones' descriptors a draw, then each
    /// refusal that met any), and the counts set back. Its length
    int line(char* out, size_t n, uint64_t presents) {
        uint64_t d[kClasses], s[kClasses], all = 0;
        for (int i = 0; i < kClasses; i++)
            d[i] = draws[i].exchange(0, std::memory_order_relaxed), s[i] = descriptors[i].exchange(0, std::memory_order_relaxed),
            all += d[i];
        const double p = presents ? (double)presents : 1.0;
        int at = std::snprintf(out, n, "vk: occlusion proxies (RX_VK_OCC_LEAN=3, %llu presents): %.0f colour-off counted draws a frame; "
                               "lean %.0f a frame with %.2f fragment descriptors each", (unsigned long long)presents, all / p,
                               d[kLean] / p, d[kLean] ? (double)s[kLean] / (double)d[kLean] : 0.0);
        for (int i = 1; i < kClasses && at > 0 && (size_t)at < n; i++)
            if (d[i])
                at += std::snprintf(out + at, n - (size_t)at, "; %s %.0f (%.2f descriptors each)", kNames[i], d[i] / p,
                                    (double)s[i] / (double)d[i]);
        return at;
    }
};
inline Census census;

}  // namespace occ_lean
