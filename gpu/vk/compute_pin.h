// Which compute programs are held to 32 lanes (requiredSubgroupSize), by what the program can tell (no game, no GPU: a rule).
//
// (Triforce, 11-22, the performance audit's PIPE-52, after Source A's and Source B's.) The console's programs are written
// for warps of 32 lanes, so every compute pipeline asked for subgroups of 32 (vk_draw.cpp pin_subgroup). Most programs
// cannot tell how many lanes run beside them: they never vote, never read a lane mask or their lane's index, never
// shuffle between lanes. Mesa's Intel driver compiles a pinned program for 32 lanes only (SIMD32), which on its large
// programs is minutes and gigabytes: Source A measured a 730 KB program at 0.8-1 GB over 23-25 s pinned and at most 300 MB
// unpinned (an Iris Xe, Mesa 26.2.4), with 271 of 1046 variants still pinned by this rule.
//
// A program is pinned when it can see its lanes:
//   - a vote, a lane mask, the lane's index, a shuffle, FSWZADD or a matrix multiply (Shader::Info's flags);
//   - a barrier of Subgroup scope in its module: this translator's own case, the barrier its lowering puts between a
//     warp's shared-memory store and load, which takes the subgroup to be the warp. No flag records it, so the module is
//     looked at (subgroup_barrier below), and a module nobody looked at counts as having one;
//   - shared memory in a workgroup of 32 invocations or fewer, where the workgroup is one warp and its lanes run in step.
// Everything else gets the driver's own choice: no required size, and no full-subgroups flag either.
//
// RX_VK_COMPUTE_PIN, read once:
//   all      every compute program pinned, as it was (the default on every driver but Mesa's Intel one)
//   lanes    the rule above (the default on Mesa's Intel driver)
//   shared   the rule above, and any shared memory pins, whatever the workgroup: for a program whose warps keep
//            shared memory in step in a workgroup over 32, which nothing else here sees
// A doubt pins: an unknown value of the switch is the driver's default, a program without a stage is pinned.
// The graphics stages and the mesh fallback's compute stages are not asked here: they stay with pin_subgroup.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace compute_pin {
enum class Mode { All, Lanes, Shared };

/// What one compute program is, as the rule needs it
struct Facts {
    bool has_stage = false;          // (false: nothing known, pinned)
    bool vote = false;               // Shader::Info::uses_subgroup_vote
    bool mask = false;               // uses_subgroup_mask
    bool lane_index = false;         // uses_subgroup_invocation_id
    bool shuffles = false;           // uses_subgroup_shuffles
    bool fswzadd = false;            // uses_fswzadd
    bool matrices = false;           // uses_cooperative_matrix
    bool subgroup_barrier = true;    // its module has an OpControlBarrier of Subgroup scope (true until a look says no)
    uint32_t shared_memory = 0;      // bytes of shared memory
    uint64_t invocations = 0;        // the workgroup's x * y * z
};

/// The program can tell how many lanes run in its subgroup, or which one it is
constexpr bool sees_lanes(const Facts& f) {
    return f.vote || f.mask || f.lane_index || f.shuffles || f.fswzadd || f.matrices || f.subgroup_barrier;
}

/// RX_VK_COMPUTE_PIN's value (nullptr: unset) on this driver
inline Mode mode_for(const char* env, bool mesa_intel) {
    if (env && !std::strcmp(env, "all")) return Mode::All;
    if (env && !std::strcmp(env, "lanes")) return Mode::Lanes;
    if (env && !std::strcmp(env, "shared")) return Mode::Shared;
    return mesa_intel ? Mode::Lanes : Mode::All;
}

inline const char* name(Mode m) {
    return m == Mode::All ? "all" : m == Mode::Lanes ? "lanes" : "shared";
}

/// The program's pipeline asks for subgroups of 32
constexpr bool needed(Mode m, const Facts& f) {
    if (m == Mode::All || !f.has_stage) return true;
    if (sees_lanes(f)) return true;
    if (f.shared_memory) return m == Mode::Shared || f.invocations <= 32;
    return false;
}

/// Whether a SPIR-V module's entry point is a compute shader's (OpEntryPoint with the GLCompute model): the only modules
/// the rule is asked about, so the only ones worth a note. One that does not read as SPIR-V: no
inline bool compute_entry(const uint32_t* code, size_t words) {
    constexpr uint32_t kMagic = 0x07230203, kOpEntryPoint = 15, kOpFunction = 54, kGLCompute = 5;
    if (!code || words < 5 || code[0] != kMagic) return false;
    for (size_t at = 5; at < words;) {
        const uint32_t count = code[at] >> 16, op = code[at] & 0xffffu;
        if (!count || at + count > words || op == kOpFunction) return false;
        if (op == kOpEntryPoint && count >= 2) return code[at + 1] == kGLCompute;
        at += count;
    }
    return false;
}

/// Whether a SPIR-V module has an OpControlBarrier whose execution scope is the constant Subgroup (3). A module that does
/// not read as SPIR-V counts as having one. words: the module's 32-bit words
inline bool subgroup_barrier(const uint32_t* code, size_t words) {
    constexpr uint32_t kMagic = 0x07230203, kOpConstant = 43, kOpControlBarrier = 224, kScopeSubgroup = 3;
    if (!code || words < 5 || code[0] != kMagic) return true;
    // (the scopes are constants, and constants come before the functions: one pass for the barriers' scope ids, kept small,
    // and their values looked up at the end)
    constexpr size_t kMost = 64;
    uint32_t scopes[kMost];
    size_t n_scopes = 0;
    for (size_t at = 5; at < words;) {
        const uint32_t count = code[at] >> 16, op = code[at] & 0xffffu;
        if (!count || at + count > words) return true;
        if (op == kOpControlBarrier && count >= 4) {
            const uint32_t id = code[at + 1];
            bool seen = false;
            for (size_t i = 0; i < n_scopes; i++) seen = seen || scopes[i] == id;
            if (!seen) {
                if (n_scopes == kMost) return true;   // (more scope ids than a module has: a doubt)
                scopes[n_scopes++] = id;
            }
        }
        at += count;
    }
    if (!n_scopes) return false;
    size_t resolved = 0;
    for (size_t at = 5; at < words;) {
        const uint32_t count = code[at] >> 16, op = code[at] & 0xffffu;
        if (op == kOpConstant && count >= 4) {
            for (size_t i = 0; i < n_scopes; i++)
                if (scopes[i] == code[at + 2]) {
                    if (code[at + 3] == kScopeSubgroup) return true;
                    resolved++;
                }
        }
        at += count;
    }
    return resolved != n_scopes;   // (a scope that is no plain constant: a doubt)
}
// (Triforce) Too big for Mesa's Intel compiler held to 32 lanes (vk_draw.cpp compute_refused). Its time goes to register
// allocation: at SIMD32 an Iris Xe thread has 32 registers a lane, and a program needing far more spills them in rounds, each
// one allocating the whole program again. Two of the game's compute programs are about 12,400 phis each (045df6f2e27d05e6 and
// 184791cd4644065f: 2.2 MB of SPIR-V, one function with 5,700 small branches); every other one held to 32 lanes has 2,650
// phis or fewer. Measured alone (i9-13900H, Iris Xe, Mesa 26.2.4): 045df6f2e27d05e6 was at 17.6 GB and not done after 30
// minutes held to 32 lanes; the worst below the limit, 7a548525c239b91b (2,534 phis), took 531 s and 7.6 GB. Their dispatches
// are left out, as a program the driver refuses
constexpr uint32_t kIntelPhiLimit = 6000;   // (between the 2,650 that build in seconds to minutes and the 12,300 that never did)

/// A compute stage not given to the driver: Mesa's Intel, held to 32 lanes, over the limit (0: no limit). The mesh
/// fallback's stages are not judged here (fallback_size_policy.h)
inline bool too_big(bool intel_mesa, bool pinned, uint32_t phis, uint32_t limit) {
    return intel_mesa && pinned && limit && phis > limit;
}

} // namespace compute_pin
