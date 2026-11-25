// (Triforce) What the programs' loader (vk_programs.cpp) asks of the pipelines' code (vk_draw.cpp): the precompile's notes by
// their place in the file, a pipeline made from the caches alone, and a place for pipelines made ahead of their first draw.
#pragma once

#include <cstdint>
#include <cstdio>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

#include "vk_internal.h"
#include "vk_draw.h"

namespace mkwvk {

struct Program;

/// A note of triforce_pipelines.bin by its place in the file (its record's index, as pipe_note_read takes it), with what the
/// programs' index needs of it: the pipeline's key, its program and variant, and the vertex input formats and colour output
/// types its program's key was made with
struct NoteRef {
    uint64_t key = 0, prog = 0, variant = 0;
    int64_t at = 0;
    uint32_t vattr[16]{};
    uint8_t color_types[8]{};
};
/// Every note's reference, read by position (26 KB a note: none is read whole)
std::vector<NoteRef> pipe_notes_refs();
std::string load_fallback_path();   // (triforce_load_start.txt beside the notes: load_default.h)
std::string pipe_notes_file();      // (triforce_pipelines.bin's path)
/// The note at a place pipe_notes_refs gave, through the caller's own handle on the file, checked as every note read is.
/// False: it does not read, or is not sane
bool pipe_note_read(FILE* f, int64_t at, PipeNote* out);
/// ((Triforce, 11-24) Whether a note's key is the one this build makes of it from p (vk_draw.cpp note_key_holds): the notes are
/// kept across a translator change, and a note whose key is another translator's is not kept ready under it
bool note_key_ok(const Program& p, const PipeNote& n);
/// A note's pipeline for its program from the caches alone, nothing compiled (the start's cache in memory first, then the
/// play cache and the driver's own: pcache_play.h). Null: no cache has it (*cold), or it failed
VkPipeline pipeline_from_caches(const Program& p, const PipeNote& n, bool* cold);
/// A compute program's pipeline the same way
VkPipeline compute_pipeline_from_caches(const Program& p);
/// The same for a program read without its code (no module): by its module's identifier. Null: no cache has it
VkPipeline compute_pipeline_by_module_id(const Program& p, const uint8_t* id, uint32_t size);
/// A pipeline made ahead of its first draw: the draw's lookup takes it (graphics_pipeline). False: that key has one already,
/// and pl is destroyed
bool pipeline_keep_ready(uint64_t key, VkPipeline pl);
/// A noted state whose probe of the caches a load left to its first draw (a first use was waiting for the load): that draw's
/// lookup asks the caches for it before it queues a build (graphics_pipeline)
void pipeline_defer(uint64_t key);
void program_layout(Program& p);   // (ensure_layout)
/// The compute program variants this install's play dispatched before (triforce_compute_variants.bin): key, variant
std::vector<std::pair<uint64_t, uint64_t>> compute_variants_learned();
/// Whether every note there is now was built into the pipeline cache by a start that got to its end (precompile_run,
/// precompile_warm): a load from the caches alone then never finds one the prepare should have compiled
bool precompile_covers_notes();
/// (programs_play_begin) RX_VK_LOAD=create without the shader preparation (RX_VK_PRECOMPILE=0: a dev build's default), where
/// precompile_run did not run: the kept programs and the notes indexed now, nothing compiled, so that create calls load them
/// from the caches ahead of their first use instead of finding no index
void precompile_index_unprepared();

} // namespace mkwvk
