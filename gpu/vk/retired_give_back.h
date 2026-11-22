// (Triforce, 11-22, the performance audit's MEM-21, after Source A's) When a retired pool's import is given back.
//
// A pool remade larger is retired: never bound again, and once the GPU is past it its import is pinned RAM nothing uses.
// vk_memory.cpp retired_imports_give_back gives such imports back at once on Linux and with NVIDIA's driver on Windows, and
// keeps them for the session with AMD's and Intel's drivers on Windows: given back at once there, an Intel Arc B390, an
// Ally X and an RX 6600 lost the device right after. It never gives back the import of a pool whose mirror was refused
// (RX_VK_NO_MIRROR_POOLS, a pool over 1 GB, VRAM refused), on any OS.
//
// Source A gives them back on Windows AMD and Intel after a wait instead: 30 s after the pool retired, or 2 s while the
// system heap is past 85% of its budget; and the refused mirrors' imports too. Here both are OFF unless asked:
//   RX_VK_KEEP_RETIRED=wait          the wait, on any driver (RX_VK_RETIRE_SECS, 30; RX_VK_RETIRE_MIN_SECS, 2)
//   RX_VK_RETIRED_REFUSED=1          the refused mirrors' imports too, by the mode in force (with `wait`: on unless =0)
// Unset, and every value RX_VK_KEEP_RETIRED took before, decide exactly as before: tests/test_retired_give_back.py compares
// want() with the old condition on random inputs. NVIDIA's driver on Windows keeps its behaviour.
//
// The rule alone, no Vulkan, no clock: the caller passes the times in milliseconds.
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace retired_give_back {

enum class Mode { AtOnce, Wait, Keep };

/// RX_VK_KEEP_RETIRED: "wait" the wait; any other value as it was read before (a value beginning with 0 gives back at once,
/// anything else keeps, the empty text too); unset: kept on Windows unless the card is NVIDIA's, given back at once elsewhere
inline Mode mode(const char* env, bool windows, bool nvidia) {
    if (env) {
        if (std::strcmp(env, "wait") == 0) return Mode::Wait;
        return env[0] != '0' ? Mode::Keep : Mode::AtOnce;
    }
    return windows && !nvidia ? Mode::Keep : Mode::AtOnce;
}
/// The old reading, for the test: whether retired imports were kept
inline bool keep_before(const char* env, bool windows, bool nvidia) {
    if (windows) return env ? env[0] != '0' : !nvidia;
    return env && env[0] != '0';
}

/// RX_VK_RETIRED_REFUSED: a number other than 0 on, 0 off; unset: on with the wait (Source A's rule whole), off otherwise
inline bool refused_too(const char* env, Mode m) {
    if (env) return std::atoi(env) != 0;
    return m == Mode::Wait;
}

/// RX_VK_RETIRE_SECS, RX_VK_RETIRE_MIN_SECS: whole seconds, 0 or more; unset or not a number of 0 or more: the default
inline int64_t secs(const char* env, int64_t fallback) {
    if (!env || !*env) return fallback;
    char* end = nullptr;
    const long long v = std::strtoll(env, &end, 10);
    return end && *end == 0 && v >= 0 ? (int64_t)v : fallback;
}

/// Whether the system heap is short: used past 85% of its budget (no budget known: not short)
inline bool pressure(uint64_t used, uint64_t budget) {
    return budget && used > budget / 100 * 85;
}

/// The wait over: now_ms - retired_ms at least min_s seconds while the heap is short, wait_s seconds otherwise
inline bool due(int64_t now_ms, int64_t retired_ms, int64_t wait_s, int64_t min_s, bool short_heap) {
    return now_ms - retired_ms >= (short_heap ? min_s : wait_s) * 1000;
}

/// Whether a retired pool's import goes back now. mirror_none, mirror_refused: its mirror's state; inherit: the pool that took
/// it in still copies from its mirror; gpu_past: the GPU is past its retirement and its last use; is_due: due() (the wait only)
inline bool want(Mode m, bool refused, bool mirror_none, bool mirror_refused, bool inherit, bool gpu_past, bool is_due) {
    if (m == Mode::Keep) return false;
    if (!mirror_none && !(refused && mirror_refused)) return false;
    if (inherit || !gpu_past) return false;
    return m == Mode::AtOnce || is_due;
}
/// The old condition, for the test
inline bool want_before(bool keep, bool mirror_none, bool inherit, bool gpu_past) {
    return !keep && mirror_none && !inherit && gpu_past;
}

/// The system heap's use as the pressure give-back (imports_give_back) should read it with the wait on: less the imports given
/// back and not freed yet (dead_imports, freed once the GPU is past them), which the driver still counts. One overshoot,
/// one valve: without this a burst of retired imports given back made it give back live ones as well
inline uint64_t settled(uint64_t used, uint64_t dead_bytes) {
    return used > dead_bytes ? used - dead_bytes : 0;
}

} // namespace retired_give_back
