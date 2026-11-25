// Mesh-fallback compute stages too big for two Mesa drivers are not handed to them (no game, no GPU: a rule).
//
// (Triforce, 11-22, the performance audit's PIPE-56, after Source A's.) A mesh program on a GPU without mesh shaders runs
// as compute stages (vk_draw.cpp fallback_compute_pipelines). Every stage went to the driver, and a refusal was only
// remembered after the build. Two drivers do not get that far on the largest stages:
//   - Mesa's RADV on GCN 1 to 4 (GFX6-8: vk_vendor.h radv_gcn). Source A's numbers under drm-shim with a 6 GB cap: the
//     79,947-phi stage not built after 45-90 s and killed (25 GB at 150 s), where GFX9 and Navi built it in 13-14 s at
//     2.9 GB. Limit: 50,000 OpPhi in one stage (2 of about 800 modules are over it);
//   - Mesa's Intel driver. An Iris Xe: a 251-call stage hit a 14 GB cap unfinished after 27 minutes. Limits: 20,000 OpPhi
//     or 200 OpFunctionCall in one stage (10 of 376 stages left out in Source A's full preparation).
// A program with a stage over its driver's limit goes into the failed set before anything is built, as a program the
// driver refused does: its draws are left out. Which objects those are is not known. No other driver has a limit, and the
// switches set none there: NVIDIA, Intel's Windows driver, AMD's own drivers and RADV from Vega on build every stage.
//
// RX_VK_FALLBACK_PHI_LIMIT=<n>, RX_VK_FALLBACK_CALL_LIMIT=<n>: the two limits on those two drivers; 0: no limit.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>

namespace fallback_size {
constexpr uint32_t kOpFunctionCall = 57, kOpPhi = 245;
constexpr uint32_t kGcnPhis = 50000, kIntelPhis = 20000, kIntelCalls = 200;

struct Size {
    uint32_t phis = 0, calls = 0;
    bool lane_free = false;   // ((Triforce) nothing in it depends on the subgroup it runs in: fallback_lanes.h, vk_shader.cpp size_note)
};
struct Limits {
    uint32_t phis = 0, calls = 0;   // (0: none)
};
enum class Driver { Other, RadvGcn, MesaIntel };

/// A module's OpPhi and OpFunctionCall instructions. One that does not read as SPIR-V counts 0 of both
inline Size count(const uint32_t* code, size_t words) {
    Size s;
    if (!code || words < 5 || code[0] != 0x07230203u) return s;
    for (size_t at = 5; at < words;) {
        const uint32_t n = code[at] >> 16, op = code[at] & 0xffffu;
        if (!n || at + n > words) return Size{};
        s.phis += op == kOpPhi, s.calls += op == kOpFunctionCall;
        at += n;
    }
    return s;
}
inline uint32_t spirv_phis(const uint32_t* code, size_t words) { return count(code, words).phis; }
inline uint32_t spirv_calls(const uint32_t* code, size_t words) { return count(code, words).calls; }

/// A limit's switch: unset, empty or not a number, the driver's own; 0, none; else the number
inline uint32_t parse_limit(const char* env, uint32_t own) {
    if (!env || !*env) return own;
    char* end = nullptr;
    const unsigned long long v = std::strtoull(env, &end, 10);
    if (end == env || *end) return own;
    return v > 0xffffffffull ? 0xffffffffu : (uint32_t)v;
}

/// The driver: RADV on a GCN 1 to 4 GPU first (it is never Mesa's Intel driver), then Mesa's Intel driver
constexpr Driver driver_of(bool radv_gcn, bool mesa_intel) {
    return radv_gcn ? Driver::RadvGcn : mesa_intel ? Driver::MesaIntel : Driver::Other;
}

/// The limits on that driver, with the two switches' values (nullptr: unset). None on any other driver, whatever is set
inline Limits limits(Driver d, const char* phi_env, const char* call_env) {
    if (d == Driver::Other) return Limits{};
    const Limits own = d == Driver::RadvGcn ? Limits{kGcnPhis, 0} : Limits{kIntelPhis, kIntelCalls};
    return Limits{parse_limit(phi_env, own.phis), parse_limit(call_env, own.calls)};
}

/// The stage is over a limit: its program is not built
constexpr bool refused(const Limits& l, const Size& s) {
    return (l.phis && s.phis > l.phis) || (l.calls && s.calls > l.calls);
}
} // namespace fallback_size
