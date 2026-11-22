// (Triforce, 11-22, the performance audit's OS-49, after Source B's) The logical processors the renderer sizes its pools and
// its threads' counts by: std::thread::hardware_concurrency, or, while the lab's HOS_SIM_CPU=<cores>/<threads> holds the
// process to fewer of the PC's cores (host/hos_sim_cpu.h), its <threads>: an affinity mask alone does not change what
// hardware_concurrency answers, and the pools would be a 24-thread PC's on 6 cores. The host clears the variable when it did
// not apply it, so the two agree. Windows only, as the host's part; unset, hardware_concurrency as before. Every such count in
// gpu/ goes through cpu_count() but vk_shader.cpp's (a file the shader cache's stamp is made from):
// tests/test_sim_cores.py checks that, and the rule.
#pragma once
#include <cstdlib>
#include <thread>

namespace cpu_count_rule {
/// The threads HOS_SIM_CPU asks for ("6/12": 12; "6": 6), when fewer than the PC's hw (0: not known); else 0: not set, not
/// "<cores>[/<threads>]" with each from 1 to 256 and threads not under cores, or not fewer
inline unsigned sim_threads(const char* e, unsigned hw) {
    if (!e || !*e) return 0;
    char* end = nullptr;
    const long c = std::strtol(e, &end, 10);
    if (end == e) return 0;
    long t = c;
    if (*end == '/') {
        const char* s = end + 1;
        t = std::strtol(s, &end, 10);
        if (end == s) return 0;
    }
    if (*end || c < 1 || c > 256 || t < c || t > 256) return 0;
    return hw && (unsigned)t >= hw ? 0 : (unsigned)t;
}
}  // namespace cpu_count_rule

/// The logical processors to size by (read once)
inline unsigned cpu_count() {
    static const unsigned n = [] {
        const unsigned hw = std::thread::hardware_concurrency();
#ifdef _WIN32
        if (const unsigned sim = cpu_count_rule::sim_threads(std::getenv("HOS_SIM_CPU"), hw)) return sim;
#endif
        return hw;
    }();
    return n;
}
