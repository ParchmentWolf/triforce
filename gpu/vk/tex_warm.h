// (Triforce, 11-19) Textures made and uploaded ahead, while the frames are light (vk_texture.cpp texture_warm_step,
// RX_VK_TEX_WARM=1; off unless set), apart from Vulkan so that tests/test_tex_warm.py can run the rules.
//
// A texture is made and its bytes uploaded where a draw first samples it, on the thread that replays, and a frame's uploads
// are held to a budget (12 ms, 64 MB) with the picture held meanwhile. That budget applies only to draws into targets the
// game drew in the frame before (redrawn.h: a text box composed once must not keep the dummy). At an area's first frame the
// scene's targets are new, so nothing is left for later, and that one frame takes every texture of the area: in six
// as-shipped tours of ten areas (lab rounds 52 to 65) the 74 frames over 80 ms were 54% texture looks and uploads, with
// 350 to 800 uploads of 250 to 390 MB in the worst of them (100 to 180 ms each).
//
// The game registers an area's textures while its loading screen shows, and those frames are nearly empty (a few draws, 4 ms
// each). Here every registered slot is noted, and at the start of a submission whose frame before was light the noted
// textures are made and uploaded, oldest first, up to a budget a frame. The area's first frame then finds them made. A
// texture whose bytes the game writes after that is uploaded again where the CPU wrote, by the rules there were (the write
// marks), so what is drawn is what it was; a texture registered and never drawn is let go by the sweep as any other.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <unordered_set>
#include <vector>

namespace tex_warm {

/// RX_VK_TEX_WARM: on when set to something other than 0
inline bool on_of(const char* env) { return env && *env && std::atoi(env) != 0; }

inline constexpr int64_t kLightWork = 400;        // (the draws and dispatches of the frame before: under it, a loading screen or a menu)
inline constexpr int64_t kBudgetNs = 6'000'000;   // (a light frame's uploads ahead, and the time looked for them)
inline constexpr uint64_t kAgeFrames = 8;         // (a slot is taken this many frames after it was registered: its bytes may still be coming)
inline constexpr size_t kMaxPending = 16384;      // (noted slots; more are not noted, and are made at their first draw as before)
inline constexpr uint64_t kRoomPct = 40;          // (made ahead only while the card's memory in use, or the textures' share of their
                                                  // budget, is under this: the game registers far more than a view draws, and a
                                                  // stand in the lab made 6,200 textures ahead, 9.5 GB for the 4 GB it draws from)

/// Whether a submission's start may make and upload noted textures: the switch, a light frame before, and this frame's
/// uploads and its looks ahead so far (a frame has several submissions: one budget for them all) under the budget
inline bool may_warm(bool on, int64_t last_frame_work, int64_t frame_upload_ns, int64_t frame_spent_ns) {
    return on && last_frame_work < kLightWork && frame_upload_ns < kBudgetNs && frame_spent_ns < kBudgetNs;
}
/// Whether there is room to make textures nothing has drawn yet. known: the card says what is in use (used of allowed);
/// else the textures' own bytes of their budget (0 or all ones: none is set, no room is known)
inline bool has_room(bool known, uint64_t used, uint64_t allowed, uint64_t texture_bytes, uint64_t budget) {
    if (known && allowed) return used / 100 * 100 < allowed / 100 * kRoomPct;
    if (!budget || budget == ~0ull) return false;
    return texture_bytes < budget / 100 * kRoomPct;
}
/// Whether a slot noted in `noted` is old enough in `frame`
inline bool ripe(uint64_t noted, uint64_t frame) { return frame >= noted + kAgeFrames; }
/// Whether the look goes on after a texture: neither the time spent nor the frame's uploads took the budget
inline bool goes_on(int64_t spent_ns, int64_t frame_upload_ns) { return spent_ns < kBudgetNs && frame_upload_ns < kBudgetNs; }

// ---- (Triforce, 11-22, the performance audit's TEX-23, after Source A's) The list of what was drawn ----
// Every registered slot made ahead needs the 40% rule above, and on a card of 8 GB that rule stops the warming at once (40% is
// about 2.8 GB, below the 4 GB a stand in the lab drew from). Source A keeps a list of the textures a draw used within 90 s of
// the game making them, between runs, and makes those ahead with a room of their own: while the textures and 256 MB more fit
// their budget. A texture is named in the list by its place: its shape and eight 64-byte samples of its bytes (the signature),
// mixed with its storage's address, so that a texture at a new address is not taken for one the list has (it is made at its
// draw as before, and learnt then). RX_VK_TEX_WARM_LIST=1: the listed slots first, the others after them while the 40% rule
// allows; 2: the listed slots alone; unset or 0: every slot as above. The list is learnt only while it is on. The file is
// triforce_textures_drawn.bin beside the game, its own magic and version; one cut short or of another version is not read.
inline int list_mode_of(const char* env) {
    if (!env || !*env) return 0;
    const int v = std::atoi(env);
    return v == 1 || v == 2 ? v : 0;
}

inline constexpr int64_t kLearnNs = 90'000'000'000;    // (a texture drawn within this of the game making it is learnt)
inline constexpr size_t kListMost = 32768;            // (places in the list: past it the list starts again)
inline constexpr uint64_t kListRoom = 256ull << 20;   // (listed textures are made while the textures and this fit their budget)
inline constexpr uint64_t kSaveEvery = 300;           // (presents between saves of a list that changed)
inline constexpr int kSamples = 8;
inline constexpr uint64_t kSampleBytes = 64;
inline constexpr char kListMagic[8] = {'T', 'F', 'D', 'R', 'A', 'W', 'N', 0};
inline constexpr uint32_t kListVersion = 1;

/// What a texture's signature takes of its shape (its descriptor and its storage's size)
struct Shape {
    uint32_t width, height, depth, levels, format, target, layers;
    uint64_t size;
};

/// Whether a texture the game made at born_ns (0: not known) and drawn at now_ns is learnt: within kLearnNs of it
inline bool learnable(int64_t born_ns, int64_t now_ns) { return born_ns > 0 && now_ns >= born_ns && now_ns - born_ns <= kLearnNs; }

/// Where sample i (0 to kSamples - 1) of a storage of `size` bytes starts: spread from its start to its end, 64-byte aligned
inline uint64_t sample_at(uint64_t size, int i) {
    if (size <= kSampleBytes) return 0;
    return ((size - kSampleBytes) * (uint64_t)i / (kSamples - 1)) & ~(kSampleBytes - 1);
}
/// How many bytes each sample reads: kSampleBytes, or the whole of a smaller storage
inline uint64_t sample_len(uint64_t size) { return size < kSampleBytes ? size : kSampleBytes; }

/// The signature: the shape and the samples (kSamples * kSampleBytes bytes, sample i at i * kSampleBytes), FNV-1a
inline uint64_t signature(const Shape& s, const uint8_t* samples) {
    uint64_t h = 0xCBF29CE484222325ull;
    const auto add = [&h](uint64_t v) {
        for (int i = 0; i < 8; i++) h = (h ^ ((v >> (8 * i)) & 0xFF)) * 1099511628211ull;
    };
    add(s.width), add(s.height), add(s.depth), add(s.levels), add(s.format), add(s.target), add(s.layers), add(s.size);
    for (uint64_t i = 0; i < kSamples * kSampleBytes; i++) h = (h ^ samples[i]) * 1099511628211ull;
    return h;
}
/// A signature at a storage address: what the list holds (never 0)
inline uint64_t place(uint64_t sig, uint64_t gpu) {
    uint64_t h = sig ^ (gpu * 0x9E3779B97F4A7C15ull);
    h ^= h >> 31, h *= 0xBF58476D1CE4E5B9ull, h ^= h >> 29, h *= 0x94D049BB133111EBull, h ^= h >> 32;
    return h | 1;
}
/// A place learnt: true when the list changed. A full list (kListMost) starts again, so that it follows what the game draws now
inline bool remember(std::unordered_set<uint64_t>& list, uint64_t p) {
    if (!p || list.count(p)) return false;
    if (list.size() >= kListMost) list.clear();
    list.insert(p);
    return true;
}
/// Whether a listed texture may be made: the target pool is not being given back (VRAM near the allowance), and the textures
/// with kListRoom more fit their budget (0 or all ones: none is set, no room is known)
inline bool listed_room(bool pressed, uint64_t texture_bytes, uint64_t budget) {
    if (pressed || !budget || budget == ~0ull) return false;
    return texture_bytes <= budget && budget - texture_bytes >= kListRoom;
}

inline uint64_t list_check(const uint8_t* b, size_t n) {
    uint64_t h = 0xCBF29CE484222325ull;
    for (size_t i = 0; i < n; i++) h = (h ^ b[i]) * 1099511628211ull;
    return h;
}
/// The file's bytes: the magic, the version, the count, the places, and a check of the places
inline std::vector<uint8_t> encode(const std::unordered_set<uint64_t>& list) {
    std::vector<uint8_t> o(16 + list.size() * 8 + 8);
    const uint32_t head[2] = {kListVersion, (uint32_t)list.size()};
    std::memcpy(o.data(), kListMagic, 8), std::memcpy(o.data() + 8, head, 8);
    size_t at = 16;
    for (const uint64_t p : list) std::memcpy(o.data() + at, &p, 8), at += 8;
    const uint64_t check = list_check(o.data() + 16, list.size() * 8);
    std::memcpy(o.data() + at, &check, 8);
    return o;
}
/// The places of a file's bytes into `out`; false, and `out` left empty, for anything that is not a whole file of this version
inline bool decode(const uint8_t* b, size_t n, std::unordered_set<uint64_t>& out) {
    out.clear();
    if (!b || n < 24 || std::memcmp(b, kListMagic, 8)) return false;
    uint32_t head[2];
    std::memcpy(head, b + 8, 8);
    if (head[0] != kListVersion || head[1] > kListMost || n != 16 + (size_t)head[1] * 8 + 8) return false;
    uint64_t check;
    std::memcpy(&check, b + n - 8, 8);
    if (check != list_check(b + 16, (size_t)head[1] * 8)) return false;
    for (uint32_t i = 0; i < head[1]; i++) {
        uint64_t p;
        std::memcpy(&p, b + 16 + (size_t)i * 8, 8);
        if (p) out.insert(p);
    }
    return true;
}

} // namespace tex_warm
