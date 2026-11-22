// Whether the driver still has the predicted pipelines, at a start whose record says they were all built (no game, no
// GPU: the rules; vk_draw.cpp predict_check_cold, predict_background, predicted_play_build). After lib_check.h, which
// asks the same of the stage libraries.
//
// (Triforce, 11-22, the performance audit's PIPE-68, after Source B's and Source A's.) The predicted pipelines (the ones
// the notes predict for programs no note names) are built once for the driver's own cache and let go, and a record
// (<notes>.predicted) says which programs are done; once it says all, no start looks again. But the driver's cache is
// the driver's: NVIDIA's has a size cap, AMD's Windows driver kept 30 to 44% of what Source B had prepared, and a cache
// folder can be cleared. Source B found 105 dispatches waiting 115 s in all on prepared pipelines the driver had dropped,
// while its record still said built. Then each of those programs' first draw compiles in play: the freezes on arrival
// the prediction is there to take away.
//
// The check. At a start whose record says all built, on the builder's idle thread after its delay and, as the builder,
// only while the frame shown is a light one: up to kSample predicted pipelines from the plan, spread over it from
// another place each start, each built for the driver's cache alone and timed, then built once more at once. The second
// comes from the driver's memory by construction, so it is this driver's warm time on this PC and no fixed time is
// needed: a first build over kRatio times the second and kSlackMs more was compiled. Not asked with
// FAIL_ON_PIPELINE_COMPILE_REQUIRED: under that flag a driver answers only from the cache it is handed, and these are in
// none of ours. The sample ends once its majority is decided.
//
// Cold (more than half of a sample): the record is removed, so the builder builds them all again behind the game at
// light frames, this session and the next, and <notes>.predicted.check takes a strike for this stamp. Cold again at a
// start after they were built again: this driver does not keep them. That is said once and recorded, and no later start
// checks for this stamp (the compiles of the check itself are not free), so the pipelines are left to their first draw
// as before the prediction. Warm: the strike is forgotten. Another stamp (a new driver, new shaders) begins anew.
//
// The counter, for what the check is worth: builds in play of programs the plan predicts that took over 20 ms, which a
// driver that had them does not need. Logged at most every 10 s while it grows.
//
// RX_VK_PREDICT_CHECK: 1 by default; 0: no check and no counter, as before; 2: checked at every start, a recorded
// "does not keep them" too (the lab's).
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

namespace predict_check {

inline constexpr int kSample = 12;            // (pipelines sampled, as lib_check's)
inline constexpr int kLook = 2 * kSample;     // (plan entries looked at for them: one may have lost its notes or its program)
inline constexpr double kRatio = 4.0;         // (the first build against the second: compiled above)
inline constexpr double kSlackMs = 3.0;       // (and this much more: lookups of a few milliseconds say nothing)
inline constexpr int kStrikes = 1;            // (the record removed once; cold again after that: stop)
inline constexpr int64_t kSlowUs = 20000;     // (a play build of a predicted program over this was compiled)
inline constexpr int64_t kSayMs = 10000;      // (the counter's line: at most this often)

/// RX_VK_PREDICT_CHECK: 0 off, 1 on (unset too), 2 every start
inline int mode(const char* env) {
    if (!env || !*env) return 1;
    const int v = std::atoi(env);
    return v <= 0 ? 0 : v >= 2 ? 2 : 1;
}

/// One pipeline sampled: made both times, and what each took (ms). One the driver refuses says nothing of its cache
struct Probe {
    bool made = false;
    double first_ms = 0, again_ms = 0;
};
inline bool cold(const Probe& p) {
    return p.made && p.first_ms > kRatio * p.again_ms + kSlackMs;
}

struct Tally {
    int got = 0, cold = 0;
    double first_median = 0, again_median = 0;
};
inline double median(std::vector<double> v) {
    if (v.empty()) return 0;
    std::sort(v.begin(), v.end());
    return v[v.size() / 2];
}
inline Tally tally(const std::vector<Probe>& probes) {
    Tally t;
    std::vector<double> first, again;
    for (const Probe& p : probes) {
        if (!p.made) continue;
        t.got++, t.cold += cold(p);
        first.push_back(p.first_ms), again.push_back(p.again_ms);
    }
    t.first_median = median(first), t.again_median = median(again);
    return t;
}

enum class Verdict { Unknown, Warm, Cold };
/// Cold when more than half of the sample is; under half a sample says nothing
inline Verdict verdict(const Tally& t) {
    if (t.got * 2 < kSample) return Verdict::Unknown;
    return t.cold * 2 > t.got ? Verdict::Cold : Verdict::Warm;
}
/// Whether the sample needs no more probes: it is full, or what is still to come cannot change its verdict
inline bool decided(const Tally& t) {
    return t.got >= kSample || t.cold * 2 > kSample || (t.got - t.cold) * 2 >= kSample;
}

/// k places spread over n, the first at seed's place in the first step: each start samples other pipelines
inline std::vector<size_t> spots(size_t n, size_t k, uint64_t seed) {
    std::vector<size_t> at;
    if (!n || !k) return at;
    const size_t step = std::max<size_t>(1, n / k);
    for (size_t i = (size_t)(seed % step); i < n && at.size() < k; i += step) at.push_back(i);
    return at;
}

/// The records of some notes in the notes file f, read from its start: a head of {stamp, rec_bytes}, then records of
/// rec_bytes whose first 8 bytes are the key (0: the first after the head). Only the keys are read, each record's rest
/// stepped over, and the walk ends once every wanted key is found. A key twice keeps its first record. Empty when the
/// head is another build's
inline std::unordered_map<uint64_t, uint32_t> find(FILE* f, uint64_t stamp, uint64_t rec_bytes, const std::vector<uint64_t>& keys) {
    std::unordered_map<uint64_t, uint32_t> at;
    uint64_t head[2] = {0, 0};
    if (!f || rec_bytes < 8 || rec_bytes > (1u << 30) || fread(head, 8, 2, f) != 2 || head[0] != stamp || head[1] != rec_bytes) return at;
    std::unordered_map<uint64_t, bool> want;
    for (const uint64_t k : keys) want.emplace(k, false);
    size_t left = want.size();
    uint64_t key = 0;
    for (uint32_t i = 0; left && fread(&key, 8, 1, f) == 1; i++) {
        const auto w = want.find(key);
        if (w != want.end() && !w->second) w->second = true, at.emplace(key, i), left--;
        if (fseek(f, (long)(rec_bytes - 8), SEEK_CUR) != 0) break;
    }
    return at;
}

// ---- <notes>.predicted.check: "predict-check <stamp> <strikes>"

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
    if (sscanf(line, "predict-check %16llx %d", &stamp, &strikes) == 2 && strikes >= 0)
        s.found = true, s.stamp = stamp, s.strikes = strikes;
    return s;
}
/// Written whole beside the old one, then put in place (a start that ends in the middle leaves the old file)
inline bool state_write(const std::string& path, uint64_t stamp, int strikes) {
    char line[96];
    const int n = snprintf(line, sizeof line, "predict-check %016llx %d\n", (unsigned long long)stamp, strikes);
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

/// Whether the record says this driver does not keep them, for this stamp: cold again after they were built again
inline bool stopped(const State& had, uint64_t stamp) {
    return had.found && had.stamp == stamp && had.strikes > kStrikes;
}
/// Whether a start checks at all: the switch, and (but for mode 2) not once the record says stop for this stamp
inline bool runs(int mode, const State& had, uint64_t stamp) {
    return mode >= 2 || (mode == 1 && !stopped(had, stamp));
}

enum class Do { Nothing, Again, Stop };
/// What a start does with a sample's verdict, the record of the last starts and the stamp now. *next: the strikes to
/// record (Again and Stop). Again: the record of what is built is removed, and the builder builds them again
inline Do decide(Verdict v, const State& had, uint64_t stamp, int* next) {
    if (v != Verdict::Cold) return Do::Nothing;
    const bool same = had.found && had.stamp == stamp;   // (found cold for this stamp before, and built again since)
    *next = same ? had.strikes + 1 : 1;
    return same && had.strikes >= kStrikes ? Do::Stop : Do::Again;
}

// ---- the counter: play builds of predicted programs the driver compiled

/// Whether a build of that many microseconds was compiled rather than found
inline bool slow(int64_t us) {
    return us > kSlowUs;
}
/// Whether the counter's line is due: said_ms, when it was last written (0: never)
inline bool say(int64_t now_ms, int64_t said_ms) {
    return !said_ms || now_ms - said_ms >= kSayMs;
}
/// The plan's programs as a sorted list without repeats, for has() (Plan: entries with .prog)
template <class Plan>
std::vector<uint64_t> programs(const std::vector<Plan>& plan) {
    std::vector<uint64_t> keys;
    keys.reserve(plan.size());
    for (const Plan& p : plan) keys.push_back(p.prog);
    std::sort(keys.begin(), keys.end());
    keys.erase(std::unique(keys.begin(), keys.end()), keys.end());
    return keys;
}
inline bool has(const std::vector<uint64_t>& sorted, uint64_t prog) {
    return std::binary_search(sorted.begin(), sorted.end(), prog);
}

}   // namespace predict_check
