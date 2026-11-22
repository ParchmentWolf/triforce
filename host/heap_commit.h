/* (Triforce, 11-21, the performance audit's MEM-09, after Source A's) The game's heap committed as it is touched.

   The guest window is reserved, and what the runtime hands out is committed (hos_commit): the game asks for a heap of
   ~6.9 GB at its start and all of it was committed there, though the game touches a part of it. Committed memory counts
   against the PC's RAM plus page file whether touched or not: on a 16 GB PC with a small page file that is where "out
   of memory" came from, with GBs of RAM free. On Windows the heap is now left reserved, and the first-touch handler
   that was there already for pages nothing handed out (mkw_glue.c commit_on_touch) commits it, 64 KB at a touch.

   What had to be there first, as Source A found:
   - two threads touching one new 64 KB at once: the second's fault finds the pages committed, and is tried again
     (heap_touch_again) where it went on to the crash report;
   - a commit refused at Windows' commit limit is tried again for 5 s (mkw_glue.c commit_wait), while the renderer's
     textures give commit back under their own rule: a first touch has no result to give the game;
   - the kernel does not fault pages in: a file read into heap pages nothing touched yet failed without an exception.
     The calls that hand guest memory to the kernel read each page of their range once first (mkw_glue.c
     hos_guest_touch), so that the handler commits the reserved ones.
   And a first touch commits only the reserved pages of its 64 KB (heap_touch_range): a commit over committed pages
   resets their protection, the lazy write-back's and the watches' too.

   HOS_HEAP_COMMIT=1: the heap committed whole at the start, as before. HOS_LARGE_PAGES: whole, as it is reserved so.
   Linux: as it was (its window does not charge untouched pages).

   The rules alone: tests/test_heap_commit_lazy.py compiles this file. */
#pragma once

#include <stdint.h>
#include <stdlib.h>

/* Whether SetMemoryHeapSize commits the new heap whole. asked: HOS_HEAP_COMMIT's value (not 0: whole); large: the heap
   is in large pages; windows: 0 on Linux */
static inline int heap_commit_whole(const char *asked, int large, int windows) {
    if (!windows || large) return 1;
    return asked && atoi(asked) != 0;
}

/* Whether a fault in the guest window is tried again with nothing done: its page is committed and read-write by now,
   another thread's first touch having got there between the fault and the look. Not an execute fault (kind 8): a jump
   into guest memory would fault again at once, for ever; it goes on to the crash report */
static inline int heap_touch_again(int committed, int read_write, uint64_t kind) {
    return committed && read_write && kind != 8;
}

/* The pages a first touch at `at` commits, [*lo, *hi): of the 64 KB around it, the run of reserved pages it lies in
   ([run_lo, run_hi): VirtualQuery's region) */
static inline void heap_touch_range(uint64_t at, uint64_t run_lo, uint64_t run_hi, uint64_t *lo, uint64_t *hi) {
    const uint64_t c_lo = at & ~0xFFFFULL, c_hi = c_lo + 0x10000;
    *lo = run_lo > c_lo ? run_lo : c_lo;
    *hi = run_hi < c_hi ? run_hi : c_hi;
}

/* Whether the n-th first touch of the heap gets a log line: the first, then each doubling from 4096 (256 MB) */
static inline int heap_touch_said(long n) { return n == 1 || (n >= 4096 && !(n & (n - 1))); }
