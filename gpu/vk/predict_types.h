// The prediction's checks (no game, no GPU: vk_predict.cpp predict_pipelines and vk_draw.cpp predict_run,
// predict_background): whether a predicted vertex layout can feed a program's vertex inputs, and the switch.
//
// (Triforce, 11-22, the performance audit's PIPE-44, after Source A's.) The predicted pipelines take a program no note names
// and give it the vertex layout of notes of the same vertex module, or else the layout most programs with its vertex inputs
// had. A program's key already says which of its inputs it reads as integers (vk_shader.cpp graphics_key), so a layout
// borrowed from another program can hand an integer input a float attribute, or the other signedness: such a pipeline is
// invalid (VUID-VkGraphicsPipelineCreateInfo-Input-08733), built for nothing or worse. Source A reads each vertex input's
// base type from the module's SPIR-V and drops a predicted layout whose attribute types definitely differ: 8,209 of 64,797
// predicted pipelines on its PC, none by colour. Scaled formats count as integers here (the translator reads them so).
//
// And a program's predictions can give the same pipeline twice (two layouts that differ only in what is dynamic, a stride):
// Source A found 420 built twice. Built once each now, by the pipeline's key, as play keys them: the same pipelines.
//
// RX_VK_PREDICT_TYPES: unset, each pipeline built once (the same pipelines as before, fewer builds); 1, that and the type
// check, which drops pipelines (off by default: it changes which pipelines exist, and a plan is made once for the shaders,
// so it applies to a plan made after it is set); 0, as before.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <unordered_map>
#include <vector>

namespace predict_types {

/// RX_VK_PREDICT_TYPES: 0 as before, 1 (unset) built once, 2 built once and the type check
inline int mode(const char* env) {
    if (!env || !*env) return 1;
    return std::atoi(env) == 0 ? 0 : std::atoi(env) == 1 ? 2 : 1;
}
inline bool once(int mode) { return mode >= 1; }
inline bool typed(int mode) { return mode >= 2; }

/// A module's vertex inputs by location (under 32): read, read as an integer, read as a signed integer
struct Locations {
    uint32_t mask = 0, ints = 0, sign = 0;
};

/// The Input (storage class 1) variables with a Location in a SPIR-V module, and each one's base type: through its
/// pointer type to a vector's or an array's element, an OpTypeInt (signedness) or anything else (float). Built-ins carry
/// no Location and are not counted
inline Locations locations(const std::vector<uint32_t>& w) {
    std::unordered_map<uint32_t, uint32_t> loc, pointee, element;
    std::unordered_map<uint32_t, int> int_sign;   // (OpTypeInt id: 1 signed, 0 unsigned)
    std::vector<std::pair<uint32_t, uint32_t>> inputs;   // (variable id, its pointer type)
    for (size_t i = 5; i < w.size();) {
        const uint32_t op = w[i] & 0xFFFF, n = w[i] >> 16;
        if (!n || i + n > w.size()) break;
        if (op == 71 && n >= 4 && w[i + 2] == 30) loc[w[i + 1]] = w[i + 3];                     // OpDecorate Location
        else if (op == 59 && n >= 4 && w[i + 3] == 1) inputs.push_back({w[i + 2], w[i + 1]});   // OpVariable Input
        else if (op == 32 && n >= 4) pointee[w[i + 1]] = w[i + 3];                                // OpTypePointer
        else if ((op == 23 || op == 28) && n >= 4) element[w[i + 1]] = w[i + 2];                  // OpTypeVector, OpTypeArray
        else if (op == 21 && n >= 4) int_sign[w[i + 1]] = w[i + 3] ? 1 : 0;                       // OpTypeInt
        i += n;
    }
    Locations out;
    for (const auto& [var, ptr] : inputs) {
        const auto l = loc.find(var);
        if (l == loc.end() || l->second >= 32) continue;
        const auto p = pointee.find(ptr);
        if (p == pointee.end()) continue;
        uint32_t t = p->second;
        for (int depth = 0; depth < 4; depth++) {   // (a vector of, an array of vectors of)
            const auto e = element.find(t);
            if (e == element.end()) break;
            t = e->second;
        }
        const uint32_t bit = 1u << l->second;
        out.mask |= bit;
        if (const auto s = int_sign.find(t); s != int_sign.end()) {
            out.ints |= bit;
            if (s->second) out.sign |= bit;
        }
    }
    return out;
}

/// What an attribute of the layout hands its location: nothing known (unset: it reads zeros, as play's), a float, an
/// unsigned or a signed integer (scaled formats are read as integers)
enum class Kind : uint8_t { Unknown, Float, Uint, Sint };

/// Whether a layout's attributes (kinds by location) can feed the module's inputs: false only where a read location's
/// attribute is definitely of the other kind (integer against float, or the other signedness)
inline bool fits(const Locations& in, const Kind kinds[16]) {
    for (int i = 0; i < 16; i++) {
        if (!(in.mask >> i & 1) || kinds[i] == Kind::Unknown) continue;
        const bool want_int = in.ints >> i & 1, want_sign = in.sign >> i & 1;
        if ((kinds[i] != Kind::Float) != want_int) return false;
        if (want_int && (kinds[i] == Kind::Sint) != want_sign) return false;
    }
    return true;
}

}   // namespace predict_types
