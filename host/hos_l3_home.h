/* (Triforce, 11-23) One L3 cache for the frame's two hot threads, on a processor with two or more L3 caches of the same size: AMD's
   two-die Ryzen 9 parts (a 5900X or 5950X, a 7900X or 7950X, a 9900X or 9950X), each die of six or eight cores with an L3
   of its own. The replay reads what the game's main thread has just written (its command buffers, the uniforms and
   vertices it filled), and on those parts the core kept for the replay was the processor's last, on the second die, while
   Windows ran the main thread mostly on the first, where its preferred cores are: every line the replay read crossed
   from one die's L3 to the other's over the fabric (an RX 6700 XT with a 5900X, 11-22: 12 ms of replay a frame in play).

   Here the die of the lowest logical processor the process may use (the first die, where Windows' preferred cores are)
   is the home: the core kept for the replay is its last core (host/hos_thread.c last_fastest_core), and the game's main
   thread and its presenting thread (where the replay runs) are kept on its other cores (hos_thread_pin). The game's other
   threads, the renderer's helper and recorder threads and the driver's stay where Windows puts them, on both dies: NX2navi
   measured that the game held to six cores loses more than the shared cache gives (host/hos_x3d.h), and only the two
   threads that hand the frame over are held here.

   Nothing is done:
   - with one L3 (a 5600X, a 5800X3D, a 7800X3D, an Intel processor of either kind);
   - with L3 caches of different sizes: a two-die X3D part, which host/hos_x3d.h handles;
   - where the home has fewer than HOS_L3_HOME_MIN_CORES cores the process may use (a 3900X's three-core CCXs, a 7900X3D's
     six-core die has no home here as its caches differ): the main thread would be left fewer than five cores beside the
     replay's;
   - with more than one processor group, or a list that puts a processor under two L3 caches.
   HOS_L3_HOME=0 turns it off. Plain code over the caches and cores the system lists: tests/test_l3_home.py runs it on
   authored topologies. */
#ifndef HOS_L3_HOME_H
#define HOS_L3_HOME_H
#include <stdint.h>
#include <string.h>

#include "hos_x3d.h"   /* (HosCache) */

enum {
    HOS_L3_HOME_NONE,     /* no L3 listed, or a list that contradicts itself */
    HOS_L3_HOME_GROUPS,   /* more than one processor group */
    HOS_L3_HOME_ONE,      /* one L3 among the processors the process may use */
    HOS_L3_HOME_MIXED,    /* L3 caches of different sizes (host/hos_x3d.h) */
    HOS_L3_HOME_FEW,      /* the home has fewer than HOS_L3_HOME_MIN_CORES cores */
    HOS_L3_HOME_USED      /* the home: the processors to keep the two threads and the replay's core on */
};
#define HOS_L3_HOME_MIN_CORES 6

typedef struct {
    int why;          /* HOS_L3_HOME_* */
    uint64_t home;    /* the allowed logical processors under the home's L3 (FEW, USED) */
    uint64_t bytes;   /* each L3's size */
    int cores;        /* the cores in home */
    int domains;      /* the L3 caches with a processor the process may use */
} HosL3Home;

/* caches: every cache listed (the L3 ones are looked at); cores: each core's logical processors; allowed: the process's
   affinity; groups: the active processor groups. The home's mask when it is used (HOS_L3_HOME_USED), else 0 */
static inline uint64_t hos_l3_home_pick(const HosCache *caches, int ncaches, const uint64_t *cores, int ncores,
                                        uint64_t allowed, int groups, HosL3Home *out) {
    HosL3Home h = {HOS_L3_HOME_NONE, 0, 0, 0, 0};
    *out = h;
    if (groups != 1) {
        out->why = HOS_L3_HOME_GROUPS;
        return 0;
    }
    uint64_t seen = 0, first = 0;
    for (int i = 0; i < ncaches; i++) {
        const uint64_t m = caches[i].mask & allowed;
        if (caches[i].level != 3 || !m || !caches[i].bytes) continue;
        if (seen & m) return 0;   /* (a processor under two L3 caches: not a list to act on) */
        seen |= m;
        if (!h.bytes) h.bytes = caches[i].bytes;
        else if (caches[i].bytes != h.bytes) h.why = HOS_L3_HOME_MIXED;
        h.domains++;
        if (m & (allowed & (0 - allowed))) first = m;   /* (the L3 of the lowest allowed logical processor) */
    }
    out->bytes = h.bytes, out->domains = h.domains;
    if (!h.domains) return 0;
    if (h.domains < 2) {
        out->why = HOS_L3_HOME_ONE;
        return 0;
    }
    if (h.why == HOS_L3_HOME_MIXED || !first) {
        out->why = h.why == HOS_L3_HOME_MIXED ? HOS_L3_HOME_MIXED : HOS_L3_HOME_NONE;
        return 0;
    }
    for (int i = 0; i < ncores; i++)
        if (cores[i] & first) h.cores++;
    out->home = first, out->cores = h.cores;
    if (h.cores < HOS_L3_HOME_MIN_CORES) {
        out->why = HOS_L3_HOME_FEW;
        return 0;
    }
    out->why = HOS_L3_HOME_USED;
    return first;
}

/* The two threads that hand the frame over: the game's main thread (named MainThread at the boot, sead::MainThread once
   the game names it) and its presenting thread, where the replay runs (gpu/vk/vk_replay.cpp ReplayPin pins it to the
   kept core while it replays and gives back this affinity after) */
static inline int hos_l3_home_thread(const char *name) {
    return name && (!strcmp(name, "sead::MainThread") || !strcmp(name, "MainThread") || !strcmp(name, "Presentation Thread"));
}

/* Their affinity, 0 for none set: the home's processors the process may use, without the core kept for the replay; none
   where that leaves nothing */
static inline uint64_t hos_l3_home_thread_mask(uint64_t process, uint64_t home, uint64_t reserved) {
    const uint64_t m = process & home & ~reserved;
    return home ? m : 0;
}
#endif
