// (Triforce, 11-23) The GPU's busy time as the union of the recordings' timestamp intervals, for the game's dynamic resolution's
// clock (vk_replay.cpp ts_dyn_present). The clock summed each recording's interval, top of the pipe to its end. On AMD's
// Windows driver a recording's first timestamp is written when the command processor reaches it, while the recording before
// it still runs, so the intervals of a frame's 20 to 30 recordings overlap and their sum counts the overlaps again: on an RX
// 6700 XT at 2560 x 1440 the sum came to 14.9 ms where the replay's whole span was 7.8 ms (scale 1.9), and Resolution Auto
// drew the 3D at 854 x 480 with the card half idle. The union counts each moment once.
//
// Intervals come in the order their recordings are read back, which on one queue is the order they ran; one that begins
// before the last one's end adds only what lies past that end. One read back out of order (it began before an interval
// already counted) adds only its part past the latest end: the busy time is then under, never over, the truth.
// tests/test_gpu_busy.py
#pragma once

#include <cstdint>

namespace mkwvk::gpu_busy {

struct Union {
    uint64_t end = 0;     // (the latest end counted, in timestamp ticks)
    uint64_t ticks = 0;   // (the busy ticks counted so far)

    /// A recording's interval [begin, finish), in the queue's timestamp ticks
    void add(uint64_t begin, uint64_t finish) {
        if (finish <= begin) return;
        if (begin >= end) {
            ticks += finish - begin;
            end = finish;
        } else if (finish > end) {
            ticks += finish - end;
            end = finish;
        }
    }
};

}  // namespace mkwvk::gpu_busy
