// (Triforce, 11-24) Compile shaders: All or Most, how much of the driver's work the shader preparation does before the title
// (no game, no GPU: the rules; vk_draw.cpp compile_level, predict_run's callers in vk_main.cpp, the compute warm and the
// precompile's compute programs). Apart from Vulkan so that tests/test_compile_level.py runs it alone.
//
// A first preparation (a new install, an update that changed the translator, a new driver) is mostly the driver compiling.
// Two parts of it build pipelines that play seldom asks for:
// - the predicted pipelines (vk_predict.cpp, predict_run): the notes' layouts given to the program variants no note names,
//   built for the driver's cache before the title for up to RX_VK_PREDICT_S (90 s), the rest behind the game in light
//   frames (predict_background). Measured elsewhere, a full cold preparation on an RTX 3090 and 12 cores: 415 and 413 s with
//   them, 292 s without (about 136 s of predicted pipelines; here the budget caps it at 90 s);
// - the compute pipelines of every compute program the seed has (prepare_run's warm, about 9,700 variants), where play and the
//   shipped state list name a few hundred programs: on Most only those (RX_VK_WARM_COMPUTES=listed with the shipped list's
//   programs counted), and the precompile's compute programs as RX_VK_PRECOMPILE_COMPUTES=listed. Measured elsewhere on an
//   RTX 3090: the translation step 226.8 s -> 128.7 s. A program left out is compiled at its first dispatch, as any compute
//   pipeline the caches miss.
// So on Most a draw or a dispatch that needs one of those pipelines compiles it in play (a hitch), which is why All, what
// the preparation did before, stays the default. Most is the player's choice: the Debug tab's Compile shaders row
// (compile_shaders= in triforce_options.ini, 0 All, 1 Most), or RX_VK_COMPILE_SHADERS=all or most over it. Applies at the
// next preparation. On Most the predicted pipelines are still built behind the game in light frames (predict_background:
// the net under the pipeline list, against the seconds-long first draws of AMD's driver), just not before the title.
//
// All after a preparation on Most: the preparation that skipped the prediction leaves a mark (<notes>.predicted.most, its
// stamp in it), and a later start on All runs the prediction before the title even though nothing was translated, until
// the predicted pipelines' record says every one is built for this driver (then the mark goes). Without the mark a start
// on All after Most found the programs prepared and never ran it before the title.
#pragma once

#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace compile_level {

enum Level { kAll = 0, kMost = 1 };

/// The level: RX_VK_COMPILE_SHADERS ("all" or "most"; anything else as not set) over the options file's compile_shaders=
/// (ini: its value, -1 when it has none; 1 Most, anything else All). *from: what decided it
inline Level level(const char* env, int ini, const char** from = nullptr) {
    if (env && *env) {
        if (!strcmp(env, "all")) return from ? (*from = "RX_VK_COMPILE_SHADERS", kAll) : kAll;
        if (!strcmp(env, "most")) return from ? (*from = "RX_VK_COMPILE_SHADERS", kMost) : kMost;
    }
    if (ini >= 0) {
        if (from) *from = "the Compile shaders row";
        return ini == 1 ? kMost : kAll;
    }
    if (from) *from = "the default";
    return kAll;
}

/// Whether the prediction runs before the title: on All after a preparation that translated (prepared), or one that a
/// preparation on Most left owed (owed: its mark is there for these shaders and driver, and the record lacks some); never
/// on Most
inline bool predict_now(Level l, bool prepared, bool owed) { return l == kAll && (prepared || owed); }

/// Whether a preparation that skips the prediction leaves the mark: on Most, where it would have run on All
inline bool mark_owed(Level l, bool prepared) { return l == kMost && prepared; }

/// The compute programs' rule where its switch is not set (RX_VK_WARM_COMPUTES, RX_VK_PRECOMPILE_COMPUTES: asked, null when
/// unset): "listed" on Most, else what the switch says or nullptr (the rule of before: the caller's own default)
inline const char* computes(Level l, const char* asked) {
    if (asked && *asked) return asked;
    return l == kMost ? "listed" : nullptr;
}

}  // namespace compile_level
