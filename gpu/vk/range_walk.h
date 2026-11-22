// (Triforce, 11-22, the performance audit's MEM-42, after Source A's) Is an address in a sorted list of ranges, asked for
// the pages of a whole loop: a cursor that only moves forward.
//
// The capture and collection loops ask of every page whether it lies in a range list sorted by first address (the
// captures' ranges, the texture storage's), and each asked with a binary search. A loop's pages come ascending, or
// nearly, so one pass over the ranges serves the whole loop. An address below the last one asked searches again, so any
// order gives the answers the search gave: tests/test_range_walk.py compares the two.
//
// A walk lives inside one loop, under the lock of its list: the list must not change while it is used.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <utility>
#include <vector>

namespace range_walk {

using Ranges = std::vector<std::pair<uint64_t, uint64_t>>;   // ([first, second), sorted by first)

struct RangeWalk {
    const Ranges& r;
    bool search = false;   // (always search, as before: RX_VK_RANGE_WALK=0, the lab knob norangewalk)
    size_t next = 0;       // (the first range that begins after the last address asked)
    uint64_t last = 0;

    /// a lies in one of the ranges: std::upper_bound(r, {a, ~0}) != begin && a < prev->second, as the loops asked
    bool in(uint64_t a) {
        if (search || a < last) next = (size_t)(std::upper_bound(r.begin(), r.end(), std::make_pair(a, ~uint64_t(0))) - r.begin());
        else
            while (next < r.size() && r[next].first <= a) next++;
        last = a;
        return next != 0 && a < r[next - 1].second;
    }
};

}   // namespace range_walk
