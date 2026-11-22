/* (Triforce, 11-22, the performance audit's OS-04, after Source A's) The wait at Windows' commit limit.

   When RAM and the page file are full Windows refuses a commit (error 1455), and a refusal often ends in moments: a
   page file set to grow grows, another program lets memory go, the renderer gives its textures' commit back. The
   game's own commits already wait for that (mkw_glue.c commit_wait, since the heap is committed as it is touched). The
   host's own tables did not: a malloc that failed there ended the game at once. Now those allocations wait the same
   way, tried again every 50 ms for up to 5 s, and only then end the game as before, after the out-of-memory notice.
   The renderer's failed `new` waits too (gpu/vk/new_wait.h).

   HOS_COMMIT_WAIT_MS=<ms>: how long all three wait, 5000 unless set, 60000 at most; 0: none, a refusal fails at once.

   The numbers and the loop alone, no system calls: tests/test_commit_limit.py compiles them. */
#ifndef HOST_ALLOC_H
#define HOST_ALLOC_H
#include <stddef.h>
#include <stdlib.h>

enum { HOST_ALLOC_STEP_MS = 50, HOST_ALLOC_WAIT_MS = 5000, HOST_ALLOC_WAIT_MOST_MS = 60000 };

/* HOS_COMMIT_WAIT_MS's value in ms: not set (or empty) 5000; a number that many, 0 and less none, 60000 at most */
static inline int host_alloc_wait_ms(const char *env) {
    if (!env || !*env) return HOST_ALLOC_WAIT_MS;
    const long v = atol(env);
    return v <= 0 ? 0 : v > HOST_ALLOC_WAIT_MOST_MS ? HOST_ALLOC_WAIT_MOST_MS : (int)v;
}
/* How often a refusal is tried again: once a step for the wait (5000 ms: 100 times; under a step: never) */
static inline int host_alloc_tries(int wait_ms) { return wait_ms > 0 ? wait_ms / HOST_ALLOC_STEP_MS : 0; }

/* After a first refusal: a step slept and try_again(ctx) called, up to `tries` times, until it gives something. What it
   gave (NULL: still refused), and in *waited_ms how long that took */
static inline void *host_alloc_retry(void *(*try_again)(void *ctx), void *ctx, int tries, void (*sleep_ms)(int ms), int *waited_ms) {
    void *p = NULL;
    *waited_ms = 0;
    for (int i = 0; i < tries && !p; i++) {
        sleep_ms(HOST_ALLOC_STEP_MS);
        *waited_ms += HOST_ALLOC_STEP_MS;
        p = try_again(ctx);
    }
    return p;
}

/* malloc, calloc and realloc that wait at the limit before they answer NULL (mkw_glue.c); a size of 0 is answered as the
   C library answers it. The caller still ends the game on NULL, as before */
void *hos_xmalloc(size_t n);
void *hos_xcalloc(size_t count, size_t size);
void *hos_xrealloc(void *p, size_t n);
int hos_commit_wait_ms(void);   /* (HOS_COMMIT_WAIT_MS, read once) */
#endif
