// The pipeline cache saved before the title after a long precompile, and after a preparation without stage libraries
// (no game, no GPU: a rule; vk_draw.cpp precompile_run, prepare_run, prepare_compute_pipeline, pipeline_cache_save).
//
// (Triforce, 11-22, the performance audit's PIPE-23, after Source A's.) A precompile that keeps every pipeline (enough
// RAM: precompile_keeps_all) ended without a save: what it compiled was first written in play, at present 300 and only
// after 32 more builds, and on Intel only at a clean close. A crash, a kill or a power cut before that cost the whole
// build again at the next start, minutes of it when the driver's own cache did not have them either. Source A wrote its
// cache before the title once the precompile had built for 30 s or more (after a 1,454 s compile on a handheld: 439 MB
// in 821 ms, and the next start's precompile took 13 s).
//
// Here the same, with two differences that are this project's:
//   - the save is the play file's alone while there is a play cache (pcache_play.h): the precompile's compiles went into
//     it. The main cache's hits count as builds too (cached_create), and on NVIDIA the main cache grows by the driver's
//     copies, so an ordinary forced save would write the whole main file, 2 to 3 GB, before the title. With no play
//     cache (a start that folded the play file, or no pipelineCreationCacheControl) the main file is what there is, and
//     it is saved;
//   - not where something else saves or the workers still build: a precompile the game went on from (its workers build
//     behind the game: no fetch while they do, Intel's driver crashed there), a stopped one (the stop's own save), a
//     start that only prepares (its end saves), and the light precompile (it saves before its record, as before).
//
// The second gap: a preparation without stage libraries compiled its compute pipelines into the main cache, counted
// them nowhere the save looks (pcache_main_built) and ended without a save, where the one with libraries saves after
// them (warm_libraries). Now they are counted, and that preparation saves before its record says it is made.
//
// RX_VK_PRECOMPILE_SAVE_S=<seconds>: the build time from which the precompile's end saves, 30 by default, at most a day;
// 0: never, and the preparation's count and save are off too, all as before.
#pragma once
#include <cstdlib>

namespace mkwvk::precompile_save {

inline constexpr int kAfterS = 30;      // Source A's
inline constexpr int kMostS = 86400;

/// RX_VK_PRECOMPILE_SAVE_S: the seconds of building from which the precompile's end saves (0: never)
inline int after_s(const char* env) {
    if (!env || !*env) return kAfterS;
    const long v = std::atol(env);
    return v <= 0 ? 0 : v > kMostS ? kMostS : (int)v;
}

/// Whether the rule is on at all (the preparation's count and its save go by this too)
constexpr bool on(int save_s) {
    return save_s > 0;
}

/// Whether a precompile that built for build_s seconds is a long one: only those say anything
constexpr bool long_build(double build_s, int save_s) {
    return save_s > 0 && build_s >= (double)save_s;
}

/// Whether the keep-all precompile's end saves now. gone_on: the game went on while workers still build; stopped: a stop
/// was asked; prepare_only: a start that only prepares
constexpr bool due(double build_s, int save_s, bool gone_on, bool stopped, bool prepare_only) {
    return long_build(build_s, save_s) && !gone_on && !stopped && !prepare_only;
}

enum class Outcome {
    Saved,         // (written: the line gives its size and time)
    Nothing,       // (the cache holds nothing its files lack)
    GoneOn,
    Stopped,
    PrepareOnly,
    NoCache,       // (no pipeline cache this session)
};

/// Why a long precompile's end does not save (only asked when due() said no, or with no cache)
constexpr Outcome why_not(bool gone_on, bool stopped, bool prepare_only, bool cache) {
    return !cache ? Outcome::NoCache : stopped ? Outcome::Stopped : gone_on ? Outcome::GoneOn :
           prepare_only ? Outcome::PrepareOnly : Outcome::Nothing;
}

/// The log line's words after "vk: precompile: N s of building: "
constexpr const char* said(Outcome o) {
    switch (o) {
    case Outcome::Saved: return "the pipeline cache saved before the title";
    case Outcome::Nothing: return "the pipeline cache holds nothing new to save before the title";
    case Outcome::GoneOn: return "the pipeline cache is not saved before the title: the game went on and the workers still build";
    case Outcome::Stopped: return "the pipeline cache is not saved here: the stop's own save writes it";
    case Outcome::PrepareOnly: return "the pipeline cache is not saved here: this start only prepares and saves at its end";
    case Outcome::NoCache: return "there is no pipeline cache to save";
    }
    return "";
}

/// Whether a preparation without stage libraries saves the cache before its record is written: the rule on, not behind
/// the game, and compute pipelines built into the main cache
constexpr bool prepare_saves(int save_s, bool libraries_warmed, bool background, unsigned long long computes_built) {
    return on(save_s) && !libraries_warmed && !background && computes_built > 0;
}

} // namespace mkwvk::precompile_save
