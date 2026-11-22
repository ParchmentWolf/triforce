// (Triforce, 11-22, the performance audit's SYNC-19, after Source A's) Late readbacks: ranges the CPU reads back without
// the wait for their write-back. The replay's invalidate (vk_replay.cpp) waits for the write-back of every range the game is
// about to read: without it the game read 0 from its exposure meter one frame and twice the sum the next (the white flashes).
// Some ranges the game reads right after it submitted the work that fills them, so the console cannot count on that work
// either: there the wait is the GPU's whole latency for nothing but a value one frame newer. Source A names such ranges and
// reads them from what guest memory holds, the last write-back made:
//   a size in hex   every range of that size (Source A's default is 3980: the culling camera block, 0x3980 bytes)
//   newest          a range whose writer is the newest submission handed out (the game cannot have waited for it)
// RX_VK_READBACK_LATE=<rule>[,<rule>...]. Unset: NO rule here until the lab has run it (the audit's lab proof: a handheld or an
// AMD iGPU, where the waits are long); =0: none either. The lab knob rblate (lab_ab.h) turns the rules a later default would
// have (default_rules: 3980) on in its phases when the variable is unset. A late range keeps its note for the CPU's
// write-back (memory_note_readback) and skips the catch-up and the wait, nothing else.
// What it risks: a late read hands the game the frame before's values; with mirrors, when the CPU resets a range read late,
// the pending write-back lands over its reset (the exposure meter's 2x flashes). `newest` can catch that meter, so it is
// never a default. RX_VK_LOG_READBACK_RANGES=1 counts the readbacks by range (RangeLog) to find such ranges on other hardware.
// tests/test_readback_late.py
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <utility>
#include <vector>

namespace mkwvk::readback_late {

constexpr int kMaxSizes = 8;
/// The size Source A reads late by default: the culling camera block
constexpr uint64_t kCameraBlock = 0x3980;

struct Rules {
    uint64_t sizes[kMaxSizes] = {};
    int n = 0;
    bool newest = false;
    int bad = 0;   // (parts of the text that were neither a hex size nor "newest", or sizes past kMaxSizes: left out)
    bool any() const { return n > 0 || newest; }
    bool has(uint64_t size) const {
        for (int i = 0; i < n; i++)
            if (sizes[i] == size) return true;
        return false;
    }
};

/// The rules a default would have once the lab has passed them (and the knob rblate has now): the camera block's size alone
inline Rules default_rules() {
    Rules r;
    r.sizes[r.n++] = kCameraBlock;
    return r;
}

/// RX_VK_READBACK_LATE's text. Unset or empty: no rule (until the lab passes; then default_rules()). "0": none. Otherwise parts
/// separated by commas: "newest", or a size in hex with or without 0x. A part that is neither is left out and counted in bad
inline Rules parse(const char* text) {
    Rules r;
    if (!text || !*text) return r;
    for (const char* p = text; *p;) {
        const char* end = std::strchr(p, ',');
        const size_t len = end ? (size_t)(end - p) : std::strlen(p);
        if (len == 6 && !std::strncmp(p, "newest", 6)) {
            r.newest = true;
        } else if (len > 0 && len < 20) {
            char part[24] = {};
            std::memcpy(part, p, len);
            char* stop = nullptr;
            const unsigned long long v = std::strtoull(part, &stop, 16);
            if (stop == part || *stop) r.bad++;
            else if (v == 0) {}   // ("0": none, and no rule of its own)
            else if (r.has(v)) {}
            else if (r.n < kMaxSizes) r.sizes[r.n++] = v;
            else r.bad++;
        } else if (len) {
            r.bad++;
        }
        if (!end) break;
        p = end + 1;
    }
    return r;
}

/// Whether a readback of `size` bytes is read late. writer_newest: its write-back's value is at or past the newest value
/// handed out (the fence a game's submit got last)
inline bool wanted(const Rules& r, uint64_t size, bool writer_newest) {
    return (r.newest && writer_newest) || r.has(size);
}
/// The decision invalidate makes: only a range whose write-back is still ahead of the GPU (pending) can be late; one whose
/// write-back is done waits for nothing anyway
inline bool late(const Rules& r, uint64_t size, uint64_t writer_value, uint64_t gpu_done, uint64_t newest_handed_out) {
    return r.any() && writer_value > gpu_done && wanted(r, size, writer_value >= newest_handed_out);
}

/// RX_VK_LOG_READBACK_RANGES: the readbacks by range. Not thread safe: the caller locks
struct RangeLog {
    struct Row {
        int64_t readbacks = 0, waits = 0, wait_ns = 0, newest = 0, late = 0;
    };
    std::map<std::pair<uint64_t, uint64_t>, Row> rows;   // ((address, size))
    size_t cap = 4096;        // (the game reads a ring of slots at new addresses: past this, the rest is counted together)
    Row other;
    void note(uint64_t gpu, uint64_t size, bool waited, int64_t ns, bool writer_newest, bool was_late) {
        Row* row = &other;
        auto it = rows.find({gpu, size});
        if (it != rows.end()) row = &it->second;
        else if (rows.size() < cap) row = &rows[{gpu, size}];
        row->readbacks++, row->waits += waited, row->wait_ns += waited ? ns : 0, row->newest += writer_newest, row->late += was_late;
    }
    struct Line {
        uint64_t gpu = 0, size = 0;
        Row row;
    };
    /// The n ranges that waited longest in all, longest first (ties: the lower address first)
    std::vector<Line> top(size_t n) const {
        std::vector<Line> all;
        all.reserve(rows.size());
        for (const auto& [key, row] : rows) all.push_back({key.first, key.second, row});
        std::stable_sort(all.begin(), all.end(), [](const Line& a, const Line& b) { return a.row.wait_ns > b.row.wait_ns; });
        if (all.size() > n) all.resize(n);
        return all;
    }
};

} // namespace mkwvk::readback_late
