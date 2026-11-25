// (Triforce) The FPS counter row's levels between On and Full (vk_menu.cpp draw_fps, fps_detail_sample): the frame time, a
// graph of the newest frames, where the frame's time goes (Breakdown) and the renderer's own numbers (Dev). Plain functions:
// tests/test_fps_levels.py compiles them.
//
// The row's saved values keep what they meant (fps_counter= in the options file): 0 Off, 1 On (the number alone), 2 Full
// (the performance panel, draw_perf). The levels are new values after them, 3 to 6, and the row steps through them in the
// order of how much they show: Off, On, Frame time, Graph, Breakdown, Dev, Full. Every level from Frame time on measures the
// game's frames as Full does (menu_note_frame, perf_stats.h's ring); Breakdown and Dev read, twice a second, the counts the
// renderer keeps anyway (the time it takes to record a frame, the GPU's time, its waits for pipelines and translations, the
// draws, passes and uploads): nothing is timed for them that is not timed already.
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdio>

namespace mkwvk::fps_levels {

enum Level { kOff = 0, kOn = 1, kFull = 2, kFrameTime = 3, kGraph = 4, kBreakdown = 5, kDev = 6, kMax = 6 };
/// The row's order, lightest first
constexpr int kOrder[] = {kOff, kOn, kFrameTime, kGraph, kBreakdown, kDev, kFull};
constexpr int kCount = sizeof kOrder / sizeof kOrder[0];
inline int place_of(int v) {
    for (int i = 0; i < kCount; i++)
        if (kOrder[i] == v) return i;
    return 0;
}
/// The row's next value from v, dir +1 Right, -1 Left: it stops at its ends, as the counter's sizes do
inline int step(int v, int dir) {
    const int p = std::clamp(place_of(v) + (dir > 0 ? 1 : -1), 0, kCount - 1);
    return kOrder[p];
}
inline const char* name(int v) {
    switch (v) {
    case kOn: return "On";
    case kFull: return "Full";
    case kFrameTime: return "Frame time";
    case kGraph: return "Graph";
    case kBreakdown: return "Breakdown";
    case kDev: return "Dev";
    default: return "Off";
    }
}
/// What a level shows past the number: the frame time, the graph, the breakdown, the renderer's numbers (Full: its own panel)
inline bool shows_time(int v) { return v >= kFrameTime && v <= kDev; }
inline bool shows_graph(int v) { return v >= kGraph && v <= kDev; }
inline bool shows_breakdown(int v) { return v >= kBreakdown && v <= kDev; }
inline bool shows_dev(int v) { return v == kDev; }
/// The game's frames are measured (the ring) at Full and at every level past On
inline bool measures(int v) { return v == kFull || shows_time(v); }

/// The frame time's text: "16.7 ms"
inline int frame_time_text(char* b, size_t n, double ms) { return snprintf(b, n, ms >= 100 ? "%.0f ms" : "%.1f ms", ms); }
/// The 1% low as a frame time beside it ("1% low 20.4 ms"); "1% low -" while there is none yet
inline int low_text(char* b, size_t n, double low_fps) {
    if (!(low_fps > 0)) return snprintf(b, n, "1%% low -");
    const double ms = 1000.0 / low_fps;
    return snprintf(b, n, ms >= 100 ? "1%% low %.0f ms" : "1%% low %.1f ms", ms);
}

/// The graph's top, ms: twice the target frame time, doubled until the usual frame fits (typical: a high percentile, so one
/// spike does not flatten the rest), four times the target at most. No target (Uncapped): from 4 ms, doubled until half
/// again the usual frame fits, 100 at most. A frame past the top is drawn at it
inline double graph_top(double target, double typical) {
    if (target <= 0) {
        double top = 4;
        while (top < typical * 1.5 && top < 100) top *= 2;
        return std::min(top, 100.0);
    }
    double top = 2 * target;
    while (top < typical * 1.1 && top < 4 * target) top *= 2;
    return std::min(top, 4 * target);
}
/// The 90th percentile of n frame times (0 for none); ms is reordered
inline double typical_ms(float* ms, int n) {
    if (n <= 0) return 0;
    const int k = std::min(n - 1, n * 9 / 10);
    std::nth_element(ms, ms + k, ms + n);
    return ms[k];
}
/// The counter's colour for a frame rate against the cap's: 0 at it (5% under counts), 1 under it, 2 at under two thirds.
/// No target: against the console's 60
inline int rate_grade(double fps, double target_ms) {
    const double want = target_ms > 0 ? 1000.0 / target_ms : 60.0;
    return fps >= want * 0.95 ? 0 : fps >= want * 2 / 3 ? 1 : 2;
}

/// Where a frame's time goes, as the renderer's counts give it (ms a frame over the last half second): the game's own code
/// (what is left of the frame), the renderer's recording and submitting (its time less its waits), its waits for pipelines
/// and for shader translations. The GPU's time runs beside them, in a lane of its own
enum Part { kGame, kRender, kPipeWait, kShaderWait, kParts };
inline const char* part_name(int p) {
    static const char* const t[] = {"Game", "Renderer", "Pipeline waits", "Shader waits"};
    return p >= 0 && p < kParts ? t[p] : "";
}
/// The parts of a frame of frame_ms from the renderer's time to record it (prep, its waits inside it) and those waits: each
/// at least 0, the renderer's own the prep less the waits, and the game's the rest; scaled down to the frame if they are more
/// (a sample's counts and frames a little apart)
inline void split(double frame_ms, double prep_ms, double pipe_ms, double shader_ms, double out[kParts]) {
    frame_ms = std::max(frame_ms, 0.0), prep_ms = std::max(prep_ms, 0.0);
    pipe_ms = std::max(pipe_ms, 0.0), shader_ms = std::max(shader_ms, 0.0);
    double waits = pipe_ms + shader_ms;
    const double own = std::max(prep_ms - waits, 0.0);
    double sum = own + waits;
    const double k = sum > frame_ms && sum > 0 ? frame_ms / sum : 1.0;
    out[kRender] = own * k, out[kPipeWait] = pipe_ms * k, out[kShaderWait] = shader_ms * k;
    out[kGame] = std::max(0.0, frame_ms - sum * k);
}

/// The Dev level's lines: their names
enum DevLine { kVram, kDraws, kDispatches, kPasses, kSkipped, kUploads, kPipelines, kDevLines };
inline const char* dev_name(int i) {
    static const char* const t[] = {"VRAM", "Draws", "Dispatches", "Passes", "Skipped", "Uploads", "Pipelines"};
    return i >= 0 && i < kDevLines ? t[i] : "";
}
/// A count a frame: what a counter moved over the window by the frames in it ("2481"; "-" without a frame)
inline int per_frame_line(char* b, size_t n, int64_t moved, int64_t frames) {
    if (frames <= 0) return snprintf(b, n, "-");
    return snprintf(b, n, "%lld", (long long)((std::max<int64_t>(moved, 0) + frames / 2) / frames));
}
/// "5.2 of 7.8 GB": the game's video memory of what the driver allows it; without a budget its own "5.2 GB"
inline int vram_line(char* b, size_t n, uint64_t used, uint64_t allowed, bool known) {
    const double g = 1024.0 * 1024.0 * 1024.0;
    if (known && allowed) return snprintf(b, n, "%.1f of %.1f GB", used / g, allowed / g);
    return snprintf(b, n, "%.1f GB", used / g);
}

} // namespace mkwvk::fps_levels
