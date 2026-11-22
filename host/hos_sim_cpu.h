/* (Triforce, 11-22, the performance audit's OS-49, after Source B's) A lab switch: the process held to fewer of the PC's
   cores, so that a lab PC plays as one with fewer does: the game's threads, and the renderer's pools.

   HOS_SIM_CPU=<cores>/<threads> ("6/12"; "6" alone: as many threads as cores). The process's affinity becomes <cores> of
   the PC's physical cores (hos_sim_cpu_mask): the ones on the die with the largest L3 first where there is one (hos_x3d.h),
   the fastest class first, the last ones first, so that the core kept for the replay (the last of the fastest class,
   hos_thread.c last_fastest_core) is among them; at least one of the PC's cores always stays out. The renderer sizes its
   pools by <threads> (gpu/vk/cpu_count.h): an affinity mask alone does not change what std::thread::hardware_concurrency
   answers. Set in host/hos_main.c before any thread (hos_thread.c hos_sim_cpu_apply). Windows only. Unset, or a value that
   cannot be read or asks for all of the PC's cores: nothing changes, and the variable is cleared so the renderer agrees.

   The rules alone, plain C: tests/test_sim_cores.py compiles them. */
#pragma once
#include <stdint.h>
#include <stdlib.h>

typedef struct {
    int cores, threads;
} HosSimCpu;

/* 1 and *out for "<cores>/<threads>" or "<cores>": each 1 to 256, threads not under cores; else 0 */
static inline int hos_sim_cpu_parse(const char *e, HosSimCpu *out) {
    if (!e || !*e) return 0;
    char *end = NULL;
    const long c = strtol(e, &end, 10);
    if (end == e) return 0;
    long t = c;
    if (*end == '/') {
        const char *s = end + 1;
        t = strtol(s, &end, 10);
        if (end == s) return 0;
    }
    if (*end || c < 1 || c > 256 || t < c || t > 256) return 0;
    out->cores = (int)c, out->threads = (int)t;
    return 1;
}

/* The process's mask: `want` of the n cores listed (masks[i]: a core's logical processors; classes[i]: its efficiency class,
   higher is faster), the ones on `die` first when die is not 0, then the fastest class, then the last ones (the highest
   processors). 0 when want is not from 1 to n - 1: one of the PC's cores always stays out */
static inline uint64_t hos_sim_cpu_mask(const uint64_t *masks, const unsigned char *classes, int n, uint64_t die, int want) {
    if (n > 256 || want < 1 || want > n - 1) return 0;
    unsigned char taken[256] = {0};
    uint64_t mask = 0;
    for (int k = 0; k < want; k++) {
        int best = -1;
        for (int i = 0; i < n; i++) {
            if (taken[i]) continue;
            if (best < 0) {
                best = i;
                continue;
            }
            const int on_i = die && (masks[i] & die), on_best = die && (masks[best] & die);
            if (on_i != on_best) {
                if (on_i) best = i;
                continue;
            }
            if (classes[i] != classes[best]) {
                if (classes[i] > classes[best]) best = i;
                continue;
            }
            if (masks[i] > masks[best]) best = i;
        }
        taken[best] = 1;
        mask |= masks[best];
    }
    return mask;
}

/* The count of logical processors in a mask (vc_spin_max sizes by it while the switch holds the process) */
static inline int hos_sim_cpu_count(uint64_t mask) {
    int n = 0;
    for (; mask; mask &= mask - 1) n++;
    return n;
}
