// A bounded wait for a draw whose program is still translating (no game, no GPU: the switch, the choice and the notes of
// which programs write memory; vk_draw.cpp draw, translate_note). Apart from Vulkan so that tests/test_translate_wait.py runs
// it alone.
//
// (Triforce, 11-22, the performance audit's PIPE-30, after Source A's.) A draw whose program is still being translated
// waits for it, its thread running the job if it is still queued (jobs_wait); RX_VK_PIPE_SKIP=2 leaves such a draw out
// when its targets hold an earlier frame, with no bound and no regard for what its shaders write. Source A, with its switch
// at 8 ms: a draw into targets that hold an earlier frame waits at most that much in all a frame, never running the job
// itself, then is left out (new targets and compute still wait). On its RTX 4070 SUPER, title to Castle Town to the field
// on a cold bank, fps 44.9/45.3 -> 50.0/47.4, the summed wait 4.94/4.85 -> 1.80/1.70 s, frames over 100 ms 39/34 -> 22/23,
// but 4.4k -> 21-23k draws left out, mostly in black load frames.
//
// With the guard the audit asked for: an untranslated program cannot be asked whether it writes memory, so only a program
// key whose variants translated before are known to write none is bounded (the variants of a key share their stage code).
// A key never translated, or one with a variant that writes, waits as before, and so does a draw into new targets.
//
// RX_VK_TRANSLATE_WAIT_MS=<ms>: 1 to 100 ms a frame in all, digits only (8 to try); unset, 0 or anything else: off, every
// such draw waits, as before. RX_VK_PIPE_SKIP=0 and =2 keep their meaning.
#pragma once

#include <cstdint>
#include <mutex>
#include <unordered_map>

namespace translate_wait {

inline constexpr int64_t kMs = 1000000;   // (ns)
inline constexpr int kMostMs = 100;

/// RX_VK_TRANSLATE_WAIT_MS: the milliseconds a frame, strictly: digits only, 1 to kMostMs; anything else 0 (off)
inline int parse(const char* env) {
    if (!env || !*env) return 0;
    int v = 0;
    for (const char* c = env; *c; c++) {
        if (*c < '0' || *c > '9') return 0;
        v = v * 10 + (*c - '0');
        if (v > kMostMs) return 0;
    }
    return v;
}

enum class Act { AsBefore, Bounded, Skip };
/// A draw whose program is still translating. kept: its targets hold an earlier frame (pass_kept); clean: its program key is
/// known to write no memory; left_ns: what the frame's budget has left. Bounded: wait at most left_ns, then leave it out;
/// Skip: the budget is spent, left out at once; AsBefore: waited for
inline Act choose(int ms, bool kept, bool clean, int64_t left_ns) {
    if (ms <= 0 || !kept || !clean) return Act::AsBefore;
    return left_ns >= kMs ? Act::Bounded : Act::Skip;
}

/// Which program keys write memory, from their variants once translated: a key is clean only when every variant noted
/// wrote none; one that writes sticks
class Notes {
public:
    void note(uint64_t key, bool writes) {
        std::lock_guard lk(mu_);
        bool& w = by_[key];
        w = w || writes;
    }
    bool clean(uint64_t key) const {
        std::lock_guard lk(mu_);
        const auto it = by_.find(key);
        return it != by_.end() && !it->second;
    }

private:
    mutable std::mutex mu_;
    std::unordered_map<uint64_t, bool> by_;   // (key -> some variant writes)
};

}   // namespace translate_wait
