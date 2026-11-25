// (hookshot) The temporal upscaler's own motion (vk_temporal.cpp): what is worked out on the CPU for a draw drawn again, from
// its bones (actor_motion) or from the positions its vertex stage stored (capture_motion), kept apart so
// tests/test_dlss_actor.cpp checks it without a GPU. Header only, no Vulkan.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

namespace dlss_actor {

/// A draw's name across frames: its model (vertex and index buffers, count, base vertex, program) and which of the frame's
/// draws of that model it is (the same model drawn twice: the n-th draw of it is matched with the n-th the frame before)
inline uint64_t key(uint64_t vbuf, uint64_t ibuf, int count, int base_vertex, uint64_t program, int nth) {
    uint64_t h = 0x5bd1e995;
    for (uint64_t v : {vbuf, ibuf, (uint64_t)(uint32_t)count, (uint64_t)(uint32_t)base_vertex, program}) {
        h ^= v + 0x9e3779b97f4a7c15ull + (h << 6) + (h >> 2);
        h *= 0xff51afd7ed558ccdull;
    }
    return (h & ~0xffull) | (uint64_t)std::clamp(nth, 0, 255);
}
inline bool same_model(uint64_t a, uint64_t b) { return a >> 8 == b >> 8; }

/// (Triforce) A copy of a model, for pair_by_place: where it is (place_of) and which draw of the model it is (its n-th)
struct Placed {
    float place[3];
    int nth;
};

/// (Triforce) Which of the frame before's copies of a model each of this frame's copies is, by place: for each of `now`, an
/// index into `then`, or -1 (none: the camera's motion then, never another copy's). All copies are paired at once, the
/// nearest pairs first, and never further apart than `reach` (in world units, moved between the two frames). On a tie (the
/// same geometry drawn twice for one object, both at one place) the same n-th draw pairs first. The pairing by draw order
/// (each copy with the frame before's same n-th) is kept when it is as good: every pair of it within the reach, and either
/// more copies paired than nearest first, or as many with the distance moved over all of them no longer (two copies 0.9
/// apart both moving 0.5 pair one by nearest first, at 0.4, and two by draw order, at 0.5 each, which is right). So the
/// reach is all that keeps draw order from pairing a row of copies each with its neighbour: it must stay under the copies'
/// spacing (2 at the most: the Gossip Stones stand 2.3 apart).
/// By draw order alone, the four Gossip Stones (one skinned model drawn four times, in another order from frame to frame,
/// and by two models) took each other's places as their own frame before, and frame generation drew a stone part way to the
/// next one. Nearest first alone fails the other way: two copies 0.6 apart that both move 0.35 have the first one's new
/// place nearest the second's old one
inline std::vector<int> pair_by_place(const std::vector<Placed>& now, const std::vector<Placed>& then, float reach) {
    struct Candidate {
        double d;     // (squared)
        bool other;   // (not the same n-th: on a tie at one place, the same n-th pairs first)
        int i, j;
    };
    const auto distance2 = [&](int i, int j) {
        double d = 0.0;
        for (int c = 0; c < 3; c++) {
            const double e = (double)now[i].place[c] - (double)then[j].place[c];
            d += e * e;
        }
        return d;
    };
    std::vector<Candidate> candidates;
    const double r2 = (double)reach * (double)reach;
    for (int i = 0; i < (int)now.size(); i++)
        for (int j = 0; j < (int)then.size(); j++) {
            const double d = distance2(i, j);
            if (std::isfinite(d) && d <= r2) candidates.push_back({d, now[i].nth != then[j].nth, i, j});
        }
    std::sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
        return a.d != b.d ? a.d < b.d : a.other != b.other ? !a.other : a.i != b.i ? a.i < b.i : a.j < b.j;
    });
    std::vector<int> pairs(now.size(), -1);
    std::vector<char> taken(then.size(), 0);
    int nearest_n = 0;
    double nearest_total = 0.0;
    for (const Candidate& c : candidates)
        if (pairs[c.i] < 0 && !taken[c.j])
            pairs[c.i] = c.j, taken[c.j] = 1, nearest_n++, nearest_total += std::sqrt(c.d);
    // (by draw order: kept when it is no worse, as above. A copy without a same n-th then is left unpaired by it)
    std::vector<int> by_order(now.size(), -1);
    std::vector<char> used(then.size(), 0);
    int order_n = 0;
    double order_total = 0.0;
    for (int i = 0; i < (int)now.size(); i++) {
        int j = 0;
        while (j < (int)then.size() && then[j].nth != now[i].nth) j++;
        if (j == (int)then.size()) continue;
        const double d = std::sqrt(distance2(i, j));
        if (used[j] || !(d <= (double)reach)) return pairs;   // (not within the reach: nearest first; NaN fails here too)
        by_order[i] = j, used[j] = 1, order_n++, order_total += d;
    }
    if (order_n > nearest_n || (order_n == nearest_n && order_total <= nearest_total + 1e-6)) return by_order;
    return pairs;
}

/// (Triforce) Where a skinned draw is, to tell copies of one model apart: its origin (3 floats) plus the mean of its bones'
/// translations (nbones 3 x 4 row-major matrices: world = sum(w B p) + origin). A model placed by its origin differs there;
/// copies placed by their bones at one origin (the game's copies of one model share an origin, the Gossip Stones among them)
/// differ in the bones; the sum is the place either way. Bones with a translation that is not finite are left out
inline void place_of(const uint8_t* origin, const uint8_t* bones, uint32_t nbones, float place[3]) {
    float o[3];
    std::memcpy(o, origin, sizeof o);
    double t[3] = {0.0, 0.0, 0.0};
    uint32_t used = 0;
    for (uint32_t b = 0; b < nbones; b++) {
        float m[12];
        std::memcpy(m, bones + (size_t)b * 48, sizeof m);
        if (!std::isfinite(m[3]) || !std::isfinite(m[7]) || !std::isfinite(m[11])) continue;
        t[0] += m[3], t[1] += m[7], t[2] += m[11];
        used++;
    }
    for (int c = 0; c < 3; c++) place[c] = o[c] + (used ? (float)(t[c] / used) : 0.0f);
}

/// (Triforce) The reach of pair_by_place: speed (world units a second) times the time between the two frames, that time
/// taken as 1/60 s at the least and 1/30 s at the most (at the default 60 a second, 1 to 2 units: under the Gossip Stones'
/// 2.3 after any gap, and some ten times a running Link a frame)
inline float place_reach(float speed, double seconds) {
    return speed * (float)std::clamp(std::isfinite(seconds) ? seconds : 1.0 / 60.0, 1.0 / 60.0, 1.0 / 30.0);
}

/// shaders/dlss_actor.vert's push constants (the fragment stage's the same)
struct Push {
    uint64_t vertices;   // (the vertex stream's device address)
    uint64_t indices;    // (the index buffer's, 4-aligned down: first says where the draw's indices start in it)
    uint64_t origins[2]; // (the draw's origin, xyz: this frame's and the frame before's, copied into the pose buffers)
    uint64_t bones[2];   // (its palettes: 3 x 4 row-major matrices, 12 floats a bone)
    uint32_t nbones;
    uint32_t stride;     // (in words)
    uint32_t count;      // (the vertices in the stream: an index past them draws nothing)
    uint32_t first;      // (in indices, from the address)
    uint32_t itype;      // (0: 8-bit, 1: 16-bit, 2: 32-bit indices)
    int32_t base_vertex;
    uint32_t pos, sets;  // (bytes in a vertex: the position; the joint and weight sets, 1 or 2)
    uint32_t joints[2], weights[2];
    uint32_t formats;    // (kHalfPosition, kByteJoints << set)
    uint32_t tolerance;  // (unused: dlss_actor.frag reads the cameras' buffer's word 66)
};
static_assert(sizeof(Push) == 6 * 8 + 14 * 4 && sizeof(Push) <= 128, "dlss_actor.vert's push constants");

/// A draw's pose in a pose buffer: its origin (12 bytes, at 0), the view it was drawn with (3 x 4 row major, at 16), its
/// projection (4 x 4, at 64), then its bones (at kPoseHead); Push::origins and bones point there
constexpr uint32_t kPoseHead = 128;

/// Push::itype of a draw without indices (a plain vertex array): its vertex i is base_vertex + i
constexpr int kNoIndices = 3;

/// Where a draw's indices are for the shader: the address 4-aligned down, and its first index from there
inline void index_start(uint64_t address, int itype, uint64_t* aligned, uint32_t* first) {
    *aligned = address & ~3ull;
    *first = (uint32_t)((address & 3) >> (itype < 0 ? 0 : itype > 2 ? 2 : itype));
}

/// Push::formats: the position is RGBA16F (else RGB32F); a set's joints are 8-bit (else 16-bit); how many joints and weights
/// a set has (kCountShift + 2 * set: 0 four, 1 one, 2 two: RGBA, R or RG formats); kRigid: no weights, set 0's one joint has
/// all of the vertex (a part that moves with one bone). Joints and weights are read byte by byte, at any offset
constexpr uint32_t kHalfPosition = 1, kByteJoints = 2, kCountShift = 4, kRigid = 1u << 8;
/// The count code of a set of n joints and weights (1, 2 or 4), for Push::formats; 3 (none) for any other n
inline uint32_t count_code(int n) { return n == 4 ? 0u : n == 1 ? 1u : n == 2 ? 2u : 3u; }
/// How many joints and weights a set has, from Push::formats
inline int set_count(uint32_t formats, int set) {
    const uint32_t c = (formats >> (kCountShift + 2 * set)) & 3u;
    return c == 0 ? 4 : c == 1 ? 1 : c == 2 ? 2 : 0;
}

/// The cameras' buffer: this frame's camera (as drawn, jittered), the frame before's (its jitter taken off), this frame's
/// jitter in clip space, the render size (words 0 to 35); then this frame's view (3 x 4, row major) and projection (4 x 4),
/// apart, as the game's vertex shaders apply them (36 to 63); then its near and far planes (0: not a plain perspective
/// projection), for the fragment stage's test in distance (64, 65); the tolerance of that test in thousandths of the
/// distance, kMarkBit for RX_VK_DLSS_DEBUG=actors and kOwnBit with it for =characters (66); the frame before's jitter in clip space (68, 69), which
/// dlss_capture.vert takes off the positions stored then; this frame's clip space to the frame before's (72 to 87, as
/// shaders/dlss_prep.comp's reproject: the camera's motion), which the fragment stage's mark compares the draw's own with
constexpr uint32_t kHeadWords = 88;
constexpr uint32_t kToleranceWord = 66, kJitterBeforeWord = 68, kReprojectWord = 72, kMarkBit = 0x80000000u;
/// (with kMarkBit: the mark is not a motion but kOwnMark in x, which no motion is, and in y how far the draw's own motion
/// is from the camera's, in render pixels: shaders/dlss_prep.comp's flag 8 shows those pixels blue on grey)
constexpr uint32_t kOwnBit = 0x40000000u;
constexpr float kOwnMark = -30000.0f;

/// shaders/dlss_capture.vert's push constants: a draw's slots this frame and the frame before (the address of the first, the
/// vertex index it is, how many)
struct CapturePush {
    uint64_t now;
    uint64_t before;
    uint32_t first_now;
    uint32_t first_before;
    uint32_t count_now;
    uint32_t count_before;
    float jitter_now[2];      // (the jitter of the camera the draw was drawn with, in clip space: this frame's, the frame before's)
    float jitter_before[2];
};
static_assert(sizeof(CapturePush) == 48, "dlss_capture.vert's push constants");

/// The jitter of the camera a draw was drawn with, from its projection (4 x 4 row major, the vertex stage's uniform buffer 3
/// at 0x70): the offset in its third column, as the scene's (vk_temporal.cpp temporal_note_scene_draw). False when it is not
/// a perspective projection (its w row not 0, 0, -1, 0) or the offset is not a sub-pixel one: the scene's is used then
inline bool camera_jitter(const float proj[16], float out[2]) {
    if (proj[12] != 0.0f || proj[13] != 0.0f || proj[14] != -1.0f || proj[15] != 0.0f) return false;
    const float x = -proj[2], y = -proj[6];
    if (!(x > -0.05f && x < 0.05f && y > -0.05f && y < 0.05f)) return false;
    out[0] = x, out[1] = y;
    return true;
}

/// The vertices an indexed draw's count indices name (itype 0, 1, 2: 8, 16, 32 bits): the least and the greatest. With
/// restart, the restart index (all ones) is none. False when there is none
inline bool index_range(const void* indices, int count, int itype, bool restart, uint32_t* lo, uint32_t* hi) {
    if (count <= 0 || itype < 0 || itype > 2) return false;
    const uint32_t size = 1u << itype;
    const uint32_t cut = itype == 0 ? 0xffu : itype == 1 ? 0xffffu : 0xffffffffu;
    uint32_t a = UINT32_MAX, b = 0;
    bool any = false;
    for (int i = 0; i < count; i++) {
        uint32_t v = 0;
        std::memcpy(&v, (const uint8_t*)indices + (size_t)i * size, size);
        if (restart && v == cut) continue;
        a = std::min(a, v), b = std::max(b, v), any = true;
    }
    if (any) *lo = a, *hi = b;
    return any;
}

/// A draw's slots for its stored positions: the vertex index of the first (as the vertex stage sees it, the base vertex in it)
/// and how many, at most max. Indexed (itype 0 to 2): base_vertex + lo to base_vertex + hi; without indices (kNoIndices):
/// base_vertex (the draw's first) and count on. False when there are none, or more than max
inline bool capture_span(int itype, int count, int base_vertex, uint32_t lo, uint32_t hi, uint32_t max, uint32_t* first,
                         uint32_t* n) {
    if (count <= 0) return false;
    uint64_t many;
    if (itype == kNoIndices) *first = (uint32_t)base_vertex, many = (uint64_t)count;
    else if (itype >= 0 && itype <= 2 && lo <= hi) *first = (uint32_t)base_vertex + lo, many = (uint64_t)hi - lo + 1;
    else return false;
    if (many > max) return false;
    *n = (uint32_t)many;
    return true;
}

/// The slot of a vertex (its VertexIndex) in a span, as the vertex stages take it (unsigned, wrapping): false when outside
inline bool capture_slot(int32_t vertex_index, uint32_t first, uint32_t n, uint32_t* slot) {
    const uint32_t s = (uint32_t)vertex_index - first;
    if (s >= n) return false;
    *slot = s;
    return true;
}

/// A clip position stored the frame before, its jitter taken off (dlss_capture.vert; dlss_math::unjitter on a camera)
inline void unjitter_position(float p[4], const float jitter[2]) {
    p[0] -= jitter[0] * p[3];
    p[1] -= jitter[1] * p[3];
}

} // namespace dlss_actor
