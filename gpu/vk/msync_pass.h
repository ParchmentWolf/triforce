// (Triforce, 11-21, the performance audit's MEM-48, after Source A's) A mirror sync's pages from the captures by one compute
// dispatch: the rules.
//
// A pool the GPU reads has a mirror in VRAM, and a sync brings the pages the CPU wrote into it. Those that come from a
// capture's buffer (host memory) went as copy regions, a page or a few each, 700 to 1,300 a frame: the GPU reads each
// region over PCIe after the one before. The write-back diff's pass (shaders/wb_diff.comp) reads a source, compares it
// with a shadow and writes a destination where they differ; with the shadow and the destination both the mirror it is a
// copy, a workgroup a chunk, every chunk of a sync in one dispatch. Source A's RTX 5080 in Hyrule Field: the syncs' GPU
// time 1.41 to 0.69 ms a frame, 79.7 to 83.1 fps where the GPU bounds the frame.
//
// What keeps it right:
// - a run goes as chunks only in whole words at word-aligned addresses (words); any other run of a sync is copied;
// - the chunk tables are host memory in a ring of blocks, each table from an atom of its own (the flush covers whole
//   atoms), a block taken again only once the GPU is done with the recording that last read it (Ring); a sync whose
//   table finds no room is copied, as before;
// - copies into one buffer are in order among themselves, a dispatch is not: where a mirror is written twice in one
//   upload command buffer and one of the two is the pass, a full barrier goes between (barrier_first). The pass's own
//   chunks and a sync's other copies never share a page.
// RX_VK_MSYNC_PASS: on for NVIDIA when not set (measured there; no gain on an RX 5600 XT), 1: on every GPU, 0: copies.
//
// No Vulkan here: tests/test_msync_pass.py compiles it.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace msync_pass {

inline constexpr int kBlocks = 16;
inline constexpr uint64_t kBlockBytes = 256u << 10;   // (8192 chunks of 32 bytes: a frame's syncs took about 1,300)
inline constexpr uint64_t kChunkBytes = 64u << 10;    // (the pass's chunk at most)

/// Whether the pass is used: asked, RX_VK_MSYNC_PASS's value; not set: on NVIDIA's GPUs
inline bool on(const char* asked, bool nvidia) {
    if (!asked || !*asked) return nvidia;
    return atoi(asked) != 0;
}

/// Whether a run from src to dst (addresses) of size bytes can go as chunks
constexpr bool words(uint64_t src, uint64_t dst, uint64_t size) { return size != 0 && !((src | dst | size) & 3); }

/// A run's chunks: emit(source, destination, count, vectors), the count in 16-byte vectors or in words. split(at, size,
/// e(at, bytes, vectors)) is the write-back diff's (wbd_split: the words before the first 16-byte line, the lines 64 KB
/// at a time, the words after). Addresses not alike within 16 bytes go in words alone
template <class Split, class Emit>
void run_chunks(uint64_t src, uint64_t dst, uint64_t size, Split&& split, Emit&& emit) {
    if ((src ^ dst) & 15) {
        for (uint64_t at = 0; at < size; at += kChunkBytes) {
            const uint64_t len = size - at < kChunkBytes ? size - at : kChunkBytes;
            emit(src + at, dst + at, (uint32_t)(len / 4), false);
        }
        return;
    }
    split(dst, size, [&](uint64_t a, uint64_t len, bool vecs) { emit(src + (a - dst), a, (uint32_t)(len / (vecs ? 16 : 4)), vecs); });
}

/// What wrote a mirror so far in an upload command buffer
enum : uint8_t { kCopies = 1, kPass = 2 };
/// Whether a full barrier goes before a write of kind `now` into a mirror that `before` wrote earlier in the same
/// upload command buffer: the pass after anything, and anything after the pass
constexpr bool barrier_first(uint8_t before, uint8_t now) { return now == kPass ? before != 0 : (before & kPass) != 0; }

/// The tables' blocks: which are made, the newest recording that reads each, and how far each is filled
struct Ring {
    struct Block {
        bool made = false;
        uint64_t value = 0, fill = 0;
    };
    Block b[kBlocks];
    int cur = -1;
    /// Room for a table of `bytes` read by the recording rec_value, the GPU done up to `completed`: the block's index
    /// and *at, the table's offset in it, a multiple of align; -1: none (too big, or the next block is still read).
    /// A block returned with made false is the caller's to make before it writes
    int get(uint64_t bytes, uint64_t align, uint64_t rec_value, uint64_t completed, uint64_t* at) {
        if (!bytes || bytes > kBlockBytes || !align) return -1;
        if (cur >= 0) {
            Block& c = b[cur];
            const uint64_t start = (c.fill + align - 1) / align * align;
            if (start + bytes <= kBlockBytes) {
                c.fill = start + bytes;
                if (rec_value > c.value) c.value = rec_value;
                *at = start;
                return cur;
            }
        }
        const int next = (cur + 1) % kBlocks;
        Block& n = b[next];
        if (n.made && n.value > completed) return -1;
        cur = next;
        n.fill = bytes, n.value = rec_value;
        *at = 0;
        return next;
    }
};

}   // namespace msync_pass
