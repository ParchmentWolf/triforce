// A program's descriptor counts kept with the program (no game, no GPU: a rule; vk_shader.h Program::desc_n, vk_draw.cpp
// build_descriptors).
//
// (Triforce, 11-22, the performance audit's DESC-22, after Source A's.) build_descriptors sums the program's buffers,
// images and texel views at every build, six lists a stage, only to size three reserve() calls that keep the pointers
// it hands the writes stable. The sums are fixed once the program is translated: its stages are filled before it is
// ready and never after. So the three are packed into one word kept on the program, stored at its first build once
// ready and read at every later one; a word that is not a count walks as before.
//
// The word is 32 bits because that is what the program has room for: the padding after Program::ready. The struct must
// not grow: sizeof(Program) is in the program cache's stamp, and a change of it throws every player's caches away. So
// three counts of 10 bits; a program with more than 1023 of a kind is not kept (kUnset is what its pack gives) and walks
// at every build, as before.
//
// A short count would let a vector move in the middle of a build and leave the writes with stale pointers. It cannot
// come from the walk that stores it, but the build checks all the same that none of the three moved, and a program
// whose did is marked kNever, walked from then on, and built again at once.
//
// RX_VK_DESC_COUNTS=0: the walk at every build, as before. The lab's knob "descwalk" does the same in its phases.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>

namespace mkwvk::desc_counts {

inline constexpr uint32_t kUnset = ~0u;          // not counted yet, or too many of a kind to pack
inline constexpr uint32_t kNever = 0xFFFFFFFEu;  // its kept counts were short once: walked at every build from then on
inline constexpr uint32_t kMost = 1023;          // the most of a kind a word holds (10 bits)

/// RX_VK_DESC_COUNTS: on unless set to 0
inline bool on(const char* env) {
    return !env || std::atoi(env) != 0;
}

/// The three counts as one word, or kUnset where one does not fit
constexpr uint32_t pack(size_t bufs, size_t imgs, size_t views) {
    if (bufs > kMost || imgs > kMost || views > kMost) return kUnset;
    return (uint32_t)bufs | (uint32_t)imgs << 10 | (uint32_t)views << 20;
}

/// Whether the word holds counts (its two top bits are clear: kUnset and kNever have them set)
constexpr bool holds(uint32_t word) {
    return (word >> 30) == 0;
}

/// The counts of a word that holds them; false, and nothing written, for one that does not (walk)
constexpr bool unpack(uint32_t word, size_t* bufs, size_t* imgs, size_t* views) {
    if (!holds(word)) return false;
    *bufs = word & kMost, *imgs = (word >> 10) & kMost, *views = (word >> 20) & kMost;
    return true;
}

/// Whether a build that walked stores its counts: the rule on, the program translated (its stages do not change after),
/// and the word still unset (never over kNever)
constexpr bool stores(bool on, bool ready, uint32_t word) {
    return on && ready && word == kUnset;
}

/// The guard at a build's end: whether one of the three vectors' storage moved since the reserve (before/after: their
/// data() pointers), in a build that went by kept counts. A build that walked reserved exactly, as it always did
constexpr bool moved(bool walked, const void* bufs0, const void* bufs1, const void* imgs0, const void* imgs1, const void* views0,
                     const void* views1) {
    return !walked && (bufs0 != bufs1 || imgs0 != imgs1 || views0 != views1);
}

} // namespace mkwvk::desc_counts
