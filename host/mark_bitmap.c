/* (Triforce) The pages the GPU can read, a bit each, for the lifted code's page marks (build.py RX_MARK_BITMAP=1, nx2/rtgen.py
   A64_MARK_BITMAP): a lifted store marks its pages only if its first byte is on one (the page before each mapping counts as
   one). The renderer reads the marks of GPU pages only (hos_gpu_guest_ranges: the GPU mappings and the native NVN pools), and
   OoT's GPU pools lie in the heap among its CPU data, so most of the game's stores mark a page nobody reads; the marks were
   ~5-8% of the game threads' CPU at the Market (build.py, RX_MARK_ONE). A page's bit is set when a mapping covering it is made
   (nvdrv.c map_add, which the native pools' hos_gpu_track goes through), before the mapping counts, and is never cleared: a
   page once GPU memory is marked for good, the same as without the bitmap. Writes made before the mapping are not marked: the
   renderer takes a new pool's memory as it is.
   Only in a build with RX_MARK_BITMAP=1 (the host's files then get -DHOS_MARK_BITMAP): 16 MB of zeroed static data for the
   512 GB window, only the heap's part ever touched (~210 KB). HOS_MARK_BITMAP_ALL=1 when the game runs sets every bit at the
   start: every store marks, as without the bitmap, plus the test's cost (the control of an A/B).
   The host's own writes (hos_mark_written) mark every page, as before. */
#include "hos.h"
#include <stdlib.h>
#include <string.h>

#ifdef HOS_MARK_BITMAP
#ifndef A64_DIRTY_PAGES
#define A64_DIRTY_PAGES (1ull << 27)
#endif
uint8_t a64_gpu_pages[A64_DIRTY_PAGES / 8];

__attribute__((constructor)) static void gpu_pages_all(void) {
    const char *e = getenv("HOS_MARK_BITMAP_ALL");
    if (e && atoi(e)) memset(a64_gpu_pages, 0xff, sizeof a64_gpu_pages);
}

void hos_gpu_pages_set(uint64_t guest, uint64_t size) {
    if (!size) return;
    /* (and the page before: the lifted code tests a store's first byte only, and a store from there may cross into this one;
       a store, and a group of stores sharing one mark, is at most 4 KB long) */
    uint64_t p = guest >> 12 ? (guest >> 12) - 1 : 0;
    const uint64_t end = (guest + size + 0xFFF) >> 12;
    for (; p < end; p++) {
        const uint64_t i = p & (A64_DIRTY_PAGES - 1);
        __atomic_fetch_or(&a64_gpu_pages[i >> 3], (uint8_t)(1u << (i & 7)), __ATOMIC_RELEASE);
    }
}
#else
void hos_gpu_pages_set(uint64_t guest, uint64_t size) { (void)guest, (void)size; }
#endif
