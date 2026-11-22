// Whether the caches still have what the light precompile's record says it built (no game, no GPU: the rules; vk_draw.cpp
// built_check_cold, precompile_run, built_play_build). After lib_check.h, which asks the same of the stage libraries, and
// predict_check.h, which asks it of the predicted pipelines.
//
// (Triforce, 11-22, the performance audit's PIPE-21, after Source A's and Source B's.) A light precompile (little RAM:
// precompile_keeps_all) builds the noted pipelines for the caches, lets them go, and records their keys in <notes>.built,
// the compute programs' as one key. A later start trusts that record on its stamp alone: what it lists is left to its first
// draw or dispatch, to be built from the caches there. When the caches lost it (the pipeline cache file deleted or refused,
// the play file lost, a driver's own cache cleared or past its cap), each of those first draws compiles in play while the
// record still says built: a draw left out or waiting for a whole build, a dispatch waiting 50 ms and then left out. Source A
// measured a cleared NVIDIA cache: 702,312 draws left out and 21.3 s of draw waits in 140 s of play, against 456 and none
// once everything was built again before the title.
//
// The check. Before the record is trusted, up to kGraphics of the recorded notes (spread over them from another place each
// start) are asked of Triforce's own caches as a draw asks, and up to kComputes of the listed compute programs as a dispatch
// asks, where the device can ask without compiling (FAIL_ON_PIPELINE_COMPILE_REQUIRED): the answer is the caches' own.
// Not a scratch cache of the check's own: AMD's Windows driver keeps no cache of its own (pcache_bound.h), so a question
// put to the driver alone would always be cold there. Without the flag, a pipeline is built twice and timed, as lib_check
// does: the second comes from the cache by construction, and a first over kRatio times it and kSlackMs more was compiled.
// Under kAnswers answers the sample says nothing (the record is trusted, as before); at half of them or more cold it is cold.
//
// Cold: the record is not trusted this start, everything noted and every listed compute program is built again before the
// title (as for a fresh record), and the record is written anew after it. <notes>.built.check keeps, for the stamp, that the
// check built them again (kStrikes 0): cold again right after that, the caches do not keep them on this PC (often a driver's
// shader cache that is too small), and they are left to their first draws, as before this check, with a hint in the log. A
// warm sample forgets that.
//
// In play, a counter of what the check is for: recorded pipelines whose first build took kSlowUs or more, and recorded
// compute programs the dispatch's ask did not find, logged at most every kSayMs while it grows.
//
// RX_VK_BUILT_CHECK: 1 by default; 0 no check and no counter, as before; 2 always cold (the lab's and the tests').
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace built_check {

inline constexpr int kGraphics = 24;          // (recorded notes asked: Source A asks 48, Source B six computes)
inline constexpr int kLook = 2 * kGraphics;   // (notes looked at for them: one may have lost its program)
inline constexpr int kComputes = 6;           // (listed compute programs asked)
inline constexpr int kAnswers = 16;           // (fewer answers say nothing)
inline constexpr double kRatio = 4.0;         // (without the flag: a first build against the second, compiled above)
inline constexpr double kSlackMs = 3.0;       // (and this much more)
inline constexpr int kStrikes = 0;            // (built again once, and cold again right after: left to the draws)
inline constexpr int64_t kSlowUs = 40000;     // (a play build of a recorded pipeline over this was compiled)
inline constexpr int64_t kSayMs = 10000;      // (the counter's line: at most this often)

/// RX_VK_BUILT_CHECK: 0 off, 1 on (unset too), 2 always cold
inline int mode(const char* env) {
    if (!env || !*env) return 1;
    const int v = std::atoi(env);
    return v <= 0 ? 0 : v >= 2 ? 2 : 1;
}

/// One pipeline asked. asked: asked of the caches only; answered_cold: they said a compile is required; made: it was made
/// (both times, not asked). One the driver refuses says nothing of the caches
struct Probe {
    bool asked = false, answered_cold = false, made = false;
    double first_ms = 0, again_ms = 0;
};
inline bool counts(const Probe& p) { return p.answered_cold || p.made; }
inline bool cold(const Probe& p) {
    return p.answered_cold || (!p.asked && p.made && p.first_ms > kRatio * p.again_ms + kSlackMs);
}

struct Tally {
    int got = 0, cold = 0, answered = 0;
};
inline Tally tally(const std::vector<Probe>& probes) {
    Tally t;
    for (const Probe& p : probes)
        if (counts(p)) t.got++, t.cold += cold(p), t.answered += p.answered_cold;
    return t;
}

enum class Verdict { Unknown, Warm, Cold };
/// Under kAnswers answers nothing; half of them or more cold: cold
inline Verdict verdict(const Tally& t) {
    if (t.got < kAnswers) return Verdict::Unknown;
    return t.cold * 2 >= t.got ? Verdict::Cold : Verdict::Warm;
}

/// k places spread over n, the first at seed's place in the first step: each start asks other pipelines
inline std::vector<size_t> spots(size_t n, size_t k, uint64_t seed) {
    std::vector<size_t> at;
    if (!n || !k) return at;
    const size_t step = std::max<size_t>(1, n / k);
    for (size_t i = (size_t)(seed % step); i < n && at.size() < k; i += step) at.push_back(i);
    return at;
}

// ---- <notes>.built.check: "built-check <stamp> <strikes>"

struct State {
    bool found = false;
    uint64_t stamp = 0;
    int strikes = 0;
};
inline State state_read(const std::string& path) {
    State s;
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return s;
    char line[96]{};
    const size_t n = fread(line, 1, sizeof line - 1, f);
    fclose(f);
    line[n] = 0;
    unsigned long long stamp = 0;
    int strikes = 0;
    if (sscanf(line, "built-check %16llx %d", &stamp, &strikes) == 2 && strikes >= 0)
        s.found = true, s.stamp = stamp, s.strikes = strikes;
    return s;
}
/// Written whole beside the old one, then put in place (a start that ends in the middle leaves the old file)
inline bool state_write(const std::string& path, uint64_t stamp, int strikes) {
    char line[96];
    const int n = snprintf(line, sizeof line, "built-check %016llx %d\n", (unsigned long long)stamp, strikes);
    const std::string tmp = path + ".tmp";
    FILE* f = fopen(tmp.c_str(), "wb");
    if (!f) return false;
    bool ok = fwrite(line, 1, (size_t)n, f) == (size_t)n;
    ok = fclose(f) == 0 && ok;
    if (ok) {
        remove(path.c_str());   // (rename does not replace on Windows)
        ok = rename(tmp.c_str(), path.c_str()) == 0;
    }
    if (!ok) remove(tmp.c_str());
    return ok;
}

enum class Do { Nothing, Again, Stop };
/// What a start does with the verdict, the record of the last starts and the stamp now. always: mode 2, built again at every
/// start whatever was recorded. *next: the strikes to record once they are built again (Again only)
inline Do decide(Verdict v, const State& had, uint64_t stamp, bool always, int* next) {
    if (always) return *next = 0, Do::Again;
    if (v != Verdict::Cold) return Do::Nothing;
    const bool same = had.found && had.stamp == stamp;   // (built again for this stamp, and cold again since)
    if (same && had.strikes >= kStrikes) return Do::Stop;
    *next = same ? had.strikes + 1 : 0;
    return Do::Again;
}

// ---- the counter: play builds of recorded pipelines the caches did not have

/// Whether a build of that many microseconds was compiled rather than found
inline bool slow(int64_t us) { return us >= kSlowUs; }
/// Whether the counter's line is due: said_ms, when it was last written (0: never)
inline bool say(int64_t now_ms, int64_t said_ms) { return !said_ms || now_ms - said_ms >= kSayMs; }
/// keys sorted without repeats, for has()
inline std::vector<uint64_t> sorted(std::vector<uint64_t> keys) {
    std::sort(keys.begin(), keys.end());
    keys.erase(std::unique(keys.begin(), keys.end()), keys.end());
    return keys;
}
inline bool has(const std::vector<uint64_t>& sorted_keys, uint64_t key) {
    return std::binary_search(sorted_keys.begin(), sorted_keys.end(), key);
}

}   // namespace built_check
