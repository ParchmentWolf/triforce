// (Triforce, 11-21, the performance audit's TEX-21, after Source A's) A texture the GPU drew gets its page map at its first
// draw.
//
// A texture in a virtual pool (its storage mapped 64 KB a page) is checked through its mapping: texture_dirty keeps each
// page's guest address (page_map) and says which pages were mapped anew or written since. The map is recorded at the
// texture's first check, which for a texture uploaded from memory is its first upload. One the GPU drew first is marked
// uploaded by the draw and never checked, so it has no map; once the game finalizes it, its first check finds none, takes
// that as "everything was mapped since", and the whole storage is uploaded from memory over what the GPU drew: a HUD
// label or a render target gone blank after an area change, and an upload of up to 15 MB each. Source A's sessions from
// Hyrule Field to Castle Town: such whole uploads of HUD labels 6, other HUD 4 to 6, render targets 4 to 9, all to 0.
// Here: the map is recorded at the first draw that says who drew it, by one walk of the mapping (the storage's size / 64 KB
// lookups, once a texture). The later check then gives only the pages mapped anew or written by the CPU.
// Not for a write that gives no reason ("?": a clear, the movie upscaler): those keep the path that brings a font cache's
// letters back from memory. RX_VK_DRAWN_PAGE_MAP=0: no map at the draw, as before.
//
// The rule alone: tests/test_drawn_page_map.py compiles it, and texture_dirty cut from the source.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace drawn_page_map {

inline constexpr uint64_t kVirtual = 1ull << 40;   // (a virtual pool's addresses start here)
inline constexpr uint64_t kPage = 1ull << 16;      // (and its pages are 64 KB)

/// RX_VK_DRAWN_PAGE_MAP: off only with 0
inline bool on(const char* asked) { return !asked || !*asked || atoi(asked) != 0; }

/// The pages of a storage of guest_size bytes
constexpr size_t pages(uint64_t guest_size) { return (size_t)((guest_size + kPage - 1) / kPage); }

/// Whether a write by `why` into a texture at gpu, of guest_size bytes of storage, whose map holds map_pages pages now,
/// records its map first
inline bool seeds(bool switch_on, const char* why, uint64_t gpu, uint64_t guest_size, size_t map_pages) {
    if (!switch_on || !why || !std::strcmp(why, "?")) return false;
    return gpu >= kVirtual && guest_size != 0 && map_pages != pages(guest_size);
}

}   // namespace drawn_page_map
