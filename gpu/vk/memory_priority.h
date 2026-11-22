// VK_EXT_memory_priority: which device memory the system should keep in video memory when the card is short (no game, no
// GPU: the switch's reading and the tiers). tests/test_memory_priority.py
//
// (Triforce, 11-22, the performance audit's TEX-47, after Source A's.) When a card is short of video memory, Windows moves
// some of a program's device memory to system memory, which the GPU then reads over the bus, and it picks what goes. With
// this extension a program ranks its memory from 0 to 1: the lower goes first. Source A gives the render targets 1.0,
// the sampled textures 0.25 and the rest 0.5, and measured it on an RTX 4090 with the video memory taken by other
// programs and the textures held to an 8 GB card's blocks: with 1.3 GB moved out, the GPU's median frame was 109 to
// 179 ms unset and 24 to 29 ms on. The textures' low rank is the lever: with them at 0.5 (`1,0.5`) it ended at 68 ms.
//
// Off unless RX_VK_MEMORY_PRIORITY is set: no small card has run it, drivers may ignore it, and in Source A's runs the
// wrong tiers were worse than none. Unset, the extension is not asked for and nothing here is used.
//   RX_VK_MEMORY_PRIORITY   unset, empty, 0, off, no: off
//                           1: render targets 1.0, textures 0.25, the rest 0.5
//                           <targets>,<textures>: those two, each from 0 to 1; the rest 0.5
//                           anything else (one number that is not 0 or 1, three numbers, a number outside 0 to 1): off
// With the extension on, the allocator (VMA) gives every pool and every allocation of its own the priority its create
// info names, and one that names none gets 0, below the textures: so every one in vk_vma.cpp names its tier.
#pragma once
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <cstring>

namespace memory_priority {

inline constexpr float kDefault = 0.5f;   // (what a driver gives memory that names no priority)

struct Tiers {
    bool on = false;
    float targets = kDefault, textures = kDefault, other = kDefault;
};

/// RX_VK_MEMORY_PRIORITY as written (see the top of the file); what cannot be read is off
inline Tiers parse(const char* env) {
    Tiers t;
    if (!env) return t;
    while (*env == ' ' || *env == '\t') env++;
    char word[32] = {};
    size_t n = std::strlen(env);
    while (n && (env[n - 1] == ' ' || env[n - 1] == '\t')) n--;
    if (!n || n >= sizeof word) return t;
    for (size_t i = 0; i < n; i++) word[i] = (char)std::tolower((unsigned char)env[i]);
    if (!std::strcmp(word, "0") || !std::strcmp(word, "off") || !std::strcmp(word, "no")) return t;
    if (!std::strcmp(word, "1")) {
        t.on = true, t.targets = 1.0f, t.textures = 0.25f;
        return t;
    }
    // (two numbers and a comma between them, nothing else)
    char* end = nullptr;
    const double a = std::strtod(word, &end);
    if (end == word || *end != ',') return t;
    const char* second = end + 1;
    const double b = std::strtod(second, &end);
    if (end == second || *end) return t;
    if (!std::isfinite(a) || !std::isfinite(b) || a < 0 || a > 1 || b < 0 || b > 1) return t;
    t.on = true, t.targets = (float)a, t.textures = (float)b;
    return t;
}

/// The tiers a run uses: the switch's where the device has the extension and its feature, else none (all the default)
inline Tiers active(const char* env, bool device_has_it) { return device_has_it ? parse(env) : Tiers{}; }

/// What a piece of device memory is for. Held: the lab's ballast (RX_VK_TEST_CARD_MB), which must stay on the card
enum class Kind { Target, Texture, Other, Held };

/// Its priority under the tiers; the default for everything while they are off
inline float of(const Tiers& t, Kind k) {
    if (!t.on) return kDefault;
    return k == Kind::Target ? t.targets : k == Kind::Texture ? t.textures : k == Kind::Held ? 1.0f : t.other;
}

} // namespace memory_priority
