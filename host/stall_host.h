/* (Triforce, 11-22, the performance audit's OS-51, after Source B's) The host's part of a long frame.

   The renderer's stall line (gpu/vk/stall_watch.h) splits a frame of 50 ms or more on the replay's side and calls the
   rest "outside the replay and the present". This is that rest, counted where the host spends it: the game's file
   reads, writes, flushes and save commits, the discards, zero-fills and decommits of memory the game lets go, the
   give-back's passes, and the waits for a virtual core; with the process's page faults and its CPU time in the kernel
   and in its own code over the same frame. Each cause is added to with relaxed atomics where it happens (a clock read
   before and after: nothing else), and at each present all are taken: a present that comes the stall line's threshold
   or more after the last one logs them as one line beside the stall line, at most 3 a second and 1500 in a session:

     vi: stall, the host's part: frame 4812, 143.2 ms: file reads 3 (12.0 MB, longest 41.0 ms); discards 2 (180.0 MB,
     longest 6.1 ms); core waits 64.0 ms (212, longest 31.0); 41000 page faults; kernel 38.0 ms, user 120.0

   Source B's found a read pacing of its own that way, sleeps of 36 to 151 ms at boot and area loads. Triforce has no
   such pacing: what is ported is the log. No frame gets shorter by it; it names, or rules out, the host's causes.

   On whenever the stall line is (RX_VK_STALL_LOG, its threshold; 0 turns both off). HOS_STALL_HOST=0: off, nothing
   counted and no system call at a present.

   Plain C, no system calls: tests/test_stall_host.py compiles it. */
#ifndef STALL_HOST_H
#define STALL_HOST_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

enum {
    STALL_HOST_READ,       /* nn::fs ReadFile: the kernel's read into the game's memory (the virtual core given up) */
    STALL_HOST_WRITE,      /* nn::fs WriteFile (the core held) */
    STALL_HOST_FLUSH,      /* nn::fs FlushFile (the core held) */
    STALL_HOST_COMMIT,     /* nn::fs Commit: the save staged (the core given up) */
    STALL_HOST_DISCARD,    /* a freed region's or freed pages' discard */
    STALL_HOST_ZERO,       /* freed pages a GPU import holds, zeroed where they are */
    STALL_HOST_DECOMMIT,   /* FreeMemoryPages' decommit above 4 GB */
    STALL_HOST_GIVE_BACK,  /* a pass of the give-back of pages let go */
    STALL_HOST_CORE_WAIT,  /* waits for a virtual core, summed over the game's threads */
    STALL_HOST_CAUSES
};

/* One cause since the last present: the time in it, how often, the bytes it was about, its longest single time */
typedef struct { int64_t ns, count, bytes, longest; } StallHostCause;

static inline void stall_host_add(StallHostCause *c, int64_t ns, int64_t bytes) {
    if (ns < 0) ns = 0;
    __atomic_add_fetch(&c->ns, ns, __ATOMIC_RELAXED);
    __atomic_add_fetch(&c->count, 1, __ATOMIC_RELAXED);
    if (bytes) __atomic_add_fetch(&c->bytes, bytes, __ATOMIC_RELAXED);
    int64_t was = __atomic_load_n(&c->longest, __ATOMIC_RELAXED);
    while (ns > was && !__atomic_compare_exchange_n(&c->longest, &was, ns, 1, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {}
}
/* What was counted, the counters left at zero (an add in the middle of a take lands in this frame or the next) */
static inline StallHostCause stall_host_take(StallHostCause *c) {
    StallHostCause t;
    t.ns = __atomic_exchange_n(&c->ns, 0, __ATOMIC_RELAXED);
    t.count = __atomic_exchange_n(&c->count, 0, __ATOMIC_RELAXED);
    t.bytes = __atomic_exchange_n(&c->bytes, 0, __ATOMIC_RELAXED);
    t.longest = __atomic_exchange_n(&c->longest, 0, __ATOMIC_RELAXED);
    return t;
}

/* The threshold in microseconds, 0 for off. stall_log: RX_VK_STALL_LOG's value (NULL: not set, the stall line's 50 ms; a
   number: that many ms; 0 or no number: no stall line, and none of this); host: HOS_STALL_HOST's (0: off) */
static inline int64_t stall_host_threshold_us(const char *stall_log, const char *host) {
    if (host && atoi(host) == 0) return 0;
    const double ms = stall_log ? atof(stall_log) : 50.0;
    return ms > 0 ? (int64_t)(ms * 1000.0 + 0.5) : 0;
}

/* At most per_second lines a second (a burst of that many after a quiet stretch) and total in a session: the stall
   line's own bound (stall_watch.h Bound) */
typedef struct { double per_second, tokens; int64_t last_ns, total, told, held; } StallHostBound;
#define STALL_HOST_BOUND {3.0, 3.0, 0, 1500, 0, 0}
static inline int stall_host_bound_take(StallHostBound *b, int64_t now_ns) {
    if (b->last_ns) {
        b->tokens += (double)(now_ns - b->last_ns) / 1e9 * b->per_second;
        if (b->tokens > b->per_second) b->tokens = b->per_second;
    }
    b->last_ns = now_ns;
    if (b->told >= b->total || b->tokens < 1.0) {
        b->held++;
        return 0;
    }
    b->tokens -= 1.0;
    b->told++;
    return 1;
}

/* One long frame's account */
typedef struct {
    int64_t frame, gap_ns;                    /* the present's number, the time since the one before */
    StallHostCause cause[STALL_HOST_CAUSES];
    uint64_t page_faults;                     /* soft and hard together, as Windows counts them */
    int64_t kernel_ns, user_ns;               /* the process's CPU time over the frame, all threads */
    int64_t held;                             /* lines the bound left out since the last one */
} StallHostFrame;

/* The line. Causes that did not happen are left out; with none, it says so (the frame's time was not the host's) */
static inline int stall_host_line(const StallHostFrame *f, char *out, size_t cap) {
    static const char *const name[STALL_HOST_CAUSES] = {"file reads", "file writes", "flushes", "save commits", "discards",
                                                        "zero-fills", "decommits", "give-backs", "core waits"};
    int n = snprintf(out, cap, "vi: stall, the host's part: frame %lld, %.1f ms:", (long long)f->frame, f->gap_ns / 1e6);
    int any = 0;
    for (int i = 0; i < STALL_HOST_CAUSES && n > 0 && (size_t)n < cap; i++) {
        const StallHostCause *c = &f->cause[i];
        if (!c->count) continue;
        const char *sep = any ? (i == STALL_HOST_DISCARD || i == STALL_HOST_CORE_WAIT ? ";" : ",") : "";
        any = 1;
        if (i == STALL_HOST_CORE_WAIT)   /* (summed over threads: more than the frame's own time is usual) */
            n += snprintf(out + n, cap - n, "%s core waits %.1f ms (%lld, longest %.1f)", sep, c->ns / 1e6, (long long)c->count,
                          c->longest / 1e6);
        else if (c->bytes)
            n += snprintf(out + n, cap - n, "%s %s %lld (%.1f MB, %.1f ms, longest %.1f)", sep, name[i], (long long)c->count,
                          c->bytes / 1048576.0, c->ns / 1e6, c->longest / 1e6);
        else
            n += snprintf(out + n, cap - n, "%s %s %lld (%.1f ms, longest %.1f)", sep, name[i], (long long)c->count, c->ns / 1e6,
                          c->longest / 1e6);
    }
    if (n > 0 && (size_t)n < cap)
        n += snprintf(out + n, cap - n, "%s %llu page faults; kernel %.1f ms, user %.1f", any ? ";" : " none of the host's causes;",
                      (unsigned long long)f->page_faults, f->kernel_ns / 1e6, f->user_ns / 1e6);
    if (f->held && n > 0 && (size_t)n < cap) n += snprintf(out + n, cap - n, " (%lld such lines left out before this one)", (long long)f->held);
    return n;
}

/* ---- the counters, and the two calls a counted place makes (host/mkw_glue.c has the counters and the present's look) ---- */
extern StallHostCause hos_stall_host[STALL_HOST_CAUSES];
extern int64_t hos_stall_host_us;   /* (the threshold; -1: the switches not read yet) */
int64_t hos_now_ns(void);

static inline int64_t stall_host_us(void) {
    int64_t us = __atomic_load_n(&hos_stall_host_us, __ATOMIC_RELAXED);
    if (us < 0) {
        us = stall_host_threshold_us(getenv("RX_VK_STALL_LOG"), getenv("HOS_STALL_HOST"));
        __atomic_store_n(&hos_stall_host_us, us, __ATOMIC_RELAXED);
    }
    return us;
}
/* The clock before a counted call, 0 when nothing is counted; and the call counted after it */
static inline int64_t stall_host_begin(void) { return stall_host_us() ? hos_now_ns() : 0; }
static inline void stall_host_end(int cause, int64_t began, uint64_t bytes) {
    if (began) stall_host_add(&hos_stall_host[cause], hos_now_ns() - began, (int64_t)bytes);
}
#endif
