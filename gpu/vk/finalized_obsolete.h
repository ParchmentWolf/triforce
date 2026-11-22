// (Triforce, 11-21, the performance audit's TEX-43, after Source A's) A finalized texture the GPU drew whose storage the
// game has since written over.
//
// A texture the GPU drew in one frame is kept after the game finalizes it (texture_sweep keep_finalized, up to
// RX_VK_KEEP_FINALIZED_MB): the game may make a texture over that storage again and sample it without drawing it, as the
// terrain does with its 260 x 260 tiles. Within the budget only a draw over one let it go, and the game's own CPU writes
// to that memory never did: in players' logs about 200 render target images an hour stayed for good, most of them such
// tiles, with the blocks they pin. Source A's rule: once the CPU has written three quarters or more of the storage since
// the release, the game has put other data there, the image holds nothing that memory holds on the console, and the
// sweep lets it go whatever the budget says. Only one of 32 KB or more (a small one shares its pages with what the game
// keeps beside it, and a write there says nothing of it) and not one in a virtual pool. Its laps of Hyrule Field at a
// 6 GB allowance: render target images 129, 166, 221 against 128, 131, 129; the kept ones 131 against 41.
// The answer is kept with the texture: once rewritten it stays so until it is released again, and one not yet rewritten
// is looked at again at most every kRecheck presents (the look walks its pages' write generations).
// RX_VK_KEEP_OBSOLETE=1: kept, as before.
//
// The rule alone: tests/test_finalized_obsolete.py compiles it.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace finalized_obsolete {

inline constexpr uint64_t kMinBytes = 32u << 10;
inline constexpr uint64_t kVirtual = 1ull << 40;
inline constexpr uint64_t kRecheck = 60;

/// RX_VK_KEEP_OBSOLETE: not 0 keeps them, as before
inline bool keep(const char* asked) { return asked && atoi(asked) != 0; }

/// Whether a texture can be one: finalized after the GPU wrote it, in no virtual pool, of 32 KB of storage or more
constexpr bool candidate(bool released, bool gpu_written, uint64_t gpu, uint64_t guest_size) {
    return released && gpu_written && gpu < kVirtual && guest_size >= kMinBytes;
}

/// Whether `written` bytes of a storage of guest_size, written by the CPU since the release, make it rewritten
constexpr bool rewritten(uint64_t written, uint64_t guest_size) { return guest_size != 0 && written * 4 >= guest_size * 3; }

/// Whether one not rewritten when last looked at, in present `checked` (0: never), is looked at again in present `frame`
constexpr bool due(uint64_t frame, uint64_t checked) { return !checked || frame - checked >= kRecheck; }

}   // namespace finalized_obsolete
