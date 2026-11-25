// NVN2 programs as SPIR-V modules (vk_shader.cpp) and what the pipelines need of them.
#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdio>
#include <functional>
#include <memory>
#include <string>
#include <unordered_set>
#include <vector>

#include "shader_recompiler/runtime_info.h"
#include "shader_recompiler/shader_info.h"

#include "spv_store.h"
#include "compute_pin.h"   // ((Triforce, 11-22, PIPE-52) which compute programs are held to 32 lanes: compute_pin_mode)
#include "compute_gate.h"   // ((Triforce) the compute compiles' memory gate: compute_gate_radv)
#include "fallback_size_policy.h"
#include "fallback_lanes.h"   // ((Triforce) the lanes a mesh fallback stage with no subgroup instruction runs at)   // ((Triforce, 11-22, PIPE-56) the mesh fallback's stages too big for two Mesa drivers)
#include "vk_internal.h"
#include "vk_state.h"

namespace mkwvk {

struct Stage {
    int nvn_stage = 0;   // 0 vertex, 1 fragment, 5 compute (what its banks are read for)
    VkShaderStageFlagBits vk_stage = VK_SHADER_STAGE_VERTEX_BIT;
    VkShaderModule module = VK_NULL_HANDLE;
    // (Triforce, RX_VK_SPV_PACK: spv_store.h) Its SPIR-V packed, in the module's place: module is null then, and one is
    // made for each pipeline's creation and let go after it. Null with RX_VK_SPV_PACK=0, and for the programs that keep
    // their modules (compute programs, those a draw reads itself: vk_shader.cpp PackSkip): the module above is kept for the
    // run, as before. Whoever creates a pipeline takes the module through StageModule, never from the field
    std::shared_ptr<spv_store::Code<VkShaderModule>> code;
    Shader::Info info;
    std::vector<uint8_t> c1;   // its c1 constants (the code area's tail)
    uint32_t crc = 0;          // (local, RenoDX port) the CRC-32 of the module the translation gave (fragment stages)
    uint32_t renodx = 0;       // (local, RenoDX port) its module is RenoDX's replacement, named by the CRC-32 of the one replaced (0: not): the program takes set 1 (vk_renodx.h)
};

/// A texture handle the stage reads from a storage buffer: its handle program (Shader::Info::handle_programs, Eden's
/// recompiler) run over the stage's constant banks and storage buffers as the draw has them
uint32_t stage_handle(const NvnState& s, const Stage& st, uint32_t program, uint32_t element = 0);
/// (Triforce) How many of such a table's count elements are the game's own this draw: the elements at and behind it name no
/// texture (handle 0), and are not computed. count itself for anything that is not a table with the game's count in its
/// header (vk_shader.cpp handle_table_live). key: the program's, for the log line that names which programs a count cuts
uint32_t stage_handle_table_live(const NvnState& s, const Stage& st, uint32_t program, uint32_t count, uint64_t key = 0);

/// (Triforce, texture detail) Whether the module reads the texture at that binding by texel position or asks its size
/// (spv_exact.h); false on a card whose textures are whole anyway. Any thread of the replay.
bool shader_reads_exact(VkShaderModule module, uint32_t binding);

/// (Triforce, spv_store.h) A stage's shader module for the time a pipeline is created with it: the one accessor of
/// Stage::module. Without packing it is the stage's own module and costs nothing. With a packed stage the module is made
/// from the packed SPIR-V here (or shared with another builder of the same stage that holds one now) and destroyed when
/// the last holder is done. get() is null when it could not be made: the caller then makes no pipeline. Any thread
class StageModule {
public:
    explicit StageModule(const Stage& st);
    ~StageModule();
    StageModule(StageModule&& o) noexcept : code_(std::move(o.code_)), m_(o.m_) { o.m_ = VK_NULL_HANDLE; }
    StageModule(const StageModule&) = delete;
    StageModule& operator=(const StageModule&) = delete;
    StageModule& operator=(StageModule&&) = delete;
    VkShaderModule get() const { return m_; }

private:
    std::shared_ptr<spv_store::Code<VkShaderModule>> code_;   // (the store the module is pinned in; null: the stage's own module)
    VkShaderModule m_ = VK_NULL_HANDLE;
};
/// What shader_reads_exact is asked by for a stage: its module, or, packed, the store that stands in the module's place
inline VkShaderModule stage_exact_key(const Stage& st) {
    return st.code ? (VkShaderModule)(uintptr_t)st.code.get() : st.module;
}
/// Whether stages are packed in this run (on unless RX_VK_SPV_PACK=0)
bool spv_pack_on();
/// ((Triforce, 11-22, the performance audit's PIPE-52) RX_VK_COMPUTE_PIN on this driver (compute_pin.h; read once, logged once
/// where it is not "all"), and whether a compute module was looked at and has no barrier of Subgroup scope (false for a
/// module nobody looked at, and always with "all", where no module is looked at)
compute_pin::Mode compute_pin_mode();
bool compute_lanes_free(VkShaderModule m);
/// ((Triforce, 11-22, the performance audit's PIPE-56) Which of the two drivers with a limit on a mesh-fallback stage's size
/// this is (fallback_size_policy.h; Other on every other driver, where no module is counted), and a stage's OpPhi and
/// OpFunctionCall counts as make_module took them (0 and 0 for a stage nobody counted). Any thread
fallback_size::Driver fallback_size_driver();
fallback_size::Size stage_size(const Stage& st);
/// ((Triforce) where the counts above are taken: on those two drivers, and on RADV with an integrated GPU on a PC with under 13 GB
/// of RAM (compute_gate_radv), whose compute compiles the memory gate weighs by their phis (vk_draw.cpp ComputeTurn)
bool stage_sizes_counted();
/// ((Triforce) vk_draw.cpp) A shader module made inside the driver fault guard: -77 for a fault there, or a program the driver faulted
/// on before where the quarantine is on (driver_faults.h); program 0: none known
VkResult extern_guarded_shader_module(const VkShaderModuleCreateInfo* ci, VkShaderModule* m, uint64_t program);
/// ((Triforce) vk_draw.cpp) A graphics pipeline of the renderer's own made inside the driver fault guard (guarded_graphics):
/// the ReShade preset's passes (reshade/fx_runtime.cpp)
VkResult extern_guarded_graphics(VkPipelineCache cache, const VkGraphicsPipelineCreateInfo* ci, VkPipeline* pl);
bool compute_gate_radv();
/// (Triforce) A program stage's module let go (vkDestroyShaderModule), and forgotten by the memory line's count (mem_parts.h):
/// every place that lets a program's module go does it through this
void stage_module_destroy(VkShaderModule m);
/// (Triforce) The program variants' shader modules alive and the SPIR-V they were made of; the packed stores alive and their bytes
void program_module_stats(int64_t* modules, int64_t* module_bytes, int64_t* packed, int64_t* packed_bytes);

/// A translated program variant: its stages, in descriptor order. The pipeline layout and pipelines made for it live
/// in vk_pipeline.cpp (keyed by key).
struct Program {
    uint64_t key = 0;
    bool compute = false, failed = false;
    std::atomic<bool> ready{false};   // translated (graphics programs are translated on a worker: vk_jobs.h)
    // ((Triforce, 11-22, the performance audit's DESC-22, after Source A's; desc_counts.h) Its descriptor counts as
    // build_descriptors sums them (buffers, images, texel views), packed: ~0u until its first build once it is ready.
    // It sits in the four bytes of padding before stages, and THIS FIELD MUST NOT GROW THE STRUCT: sizeof(Program) is in
    // the program cache's stamp (vk_shader.cpp disk_stamp), and a change of it throws every player's shader and pipeline
    // caches away (it did on 11-18, 272 to 280: vk_draw.cpp). The static_assert under the struct holds it there)
    mutable std::atomic<uint32_t> desc_n{~0u};
    std::vector<Stage> stages;
    std::array<uint32_t, 3> workgroup{1, 1, 1};
    uint32_t shared_memory = 0;
    // made by vk_pipeline.cpp at first use
    VkDescriptorSetLayout set_layout = VK_NULL_HANDLE;
    VkPipelineLayout layout = VK_NULL_HANDLE;
    std::vector<VkDescriptorType> binding_types;   // by binding (what each descriptor write is)
    VkPipeline compute_pipeline = VK_NULL_HANDLE;
    // (the compute pipeline's build: 0 not started, 1 on a worker, 2 done (compute_pipeline made, or failed): vk_draw.cpp dispatch)
    std::atomic<int> compute_state{0};
    mutable std::atomic<bool> dispatched{false};   // (hookshot) noted in triforce_computes.bin (vk_draw.cpp compute_note)
    bool push = false;             // its set is pushed (VK_KHR_push_descriptor)
    uint32_t frag_crc = 0;         // (local, RenoDX port) its fragment stage's Stage::crc, for RX_VK_RENODX_TRACE
    uint32_t renodx = 0;           // (local, RenoDX port) a stage is RenoDX's (its Stage::renodx): its layout has set 1, bound before each draw
    VkShaderStageFlags push_stages = 0;
    bool uses_render_area = false;
    bool uses_push = true;   // (a stage reads the push constants: render area or rescaling)
    bool captures = false;   // (hookshot) its vertex stage stores its positions where pushed (vk_draw.cpp push_capture)
    bool mesh = false;              // task / mesh stages (VK_EXT_mesh_shader)
    // (hookshot) the GPU has no mesh shaders: the task and mesh stages are compute pipelines, and a generated vertex
    // stage reads the records they write. Its stages are (task,) mesh, vertex, fragment.
    bool fallback = false;
    bool fallback_task = false;   // (a task stage before the mesh stage: its payloads are per mesh workgroup)
    VkPrimitiveTopology fallback_topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    uint32_t fallback_vertices_per_workgroup = 1;   // (max primitives x corners: the records of one mesh workgroup)
    uint32_t fallback_record_words = 1;             // (validity, then the vertex and primitive lines)
    uint32_t fallback_payload_words = 0;
    uint32_t fallback_task_threads = 1;             // (mesh workgroups one task workgroup may start)
    std::vector<VkPipeline> fallback_compute;       // (per stage: the mesh program's dispatches)
    // What the translator was told about the bound textures (when it asked: most texture instructions carry their
    // type themselves), by stage and texture descriptor: the variant stands while the textures still answer the same
    struct Answer {
        uint16_t stage, desc;
        uint8_t type;   // Shader::TextureType | 0x80 when the format is integer
        bool image = false;   // (hookshot) a storage image descriptor's: only whether its format is integer
    };
    std::vector<Answer> answers;
    uint64_t variant = 0;   // (a hash of the answers: key alone names all the variants of these stages)
    mutable std::atomic<int64_t> wm_sig{-1};   // (hookshot: what its write masks are made from, vk_draw.cpp program_wm_sig; -1: not asked yet)
    // (hookshot) the translation's texture questions as answered, in the order asked: what makes this variant again with nothing
    // bound (the pipeline state list, vk_draw.cpp)
    std::vector<uint8_t> questions;
    uint64_t codes[4]{};   // (hookshot) its stages' code keys: vertex (mesh), fragment, task, the header-only stage (the state list)
};
// ((Triforce, 11-22, DESC-22) desc_n in the padding between ready and stages, where it changes no size: see the field)
static_assert(sizeof(std::atomic<uint32_t>) == 4 && offsetof(Program, desc_n) + 4 <= offsetof(Program, stages) &&
                  offsetof(Program, stages) == 16,
              "Program::desc_n must fit the padding before Program::stages: sizeof(Program) is in the program cache's stamp");

enum class ProgramKind { Graphics, Compute, Mesh };

/// The program variant for the bound state (translated at first use; null when it does not translate).
/// color_types: the attachments' Shader::AttributeType (Float / SignedInt / UnsignedInt), for the fragment outputs.
/// Graphics programs may come back not ready yet (translation queued): the draw leaves itself out or program_wait()s.
const Program* program_for(const NvnState& s, ProgramKind kind, const uint8_t color_types[8]);
uint64_t compute_code_key(const NvnState& s);   // (hookshot) the bound compute program's code key, 0: none
std::string program_textures(const NvnState& s, const Program& p);   // (hookshot, for logs)
std::string program_code_keys(const NvnState& s);   // (hookshot) " stage:key" for each of the bound program's codes
const Program* program_pick(const NvnState& s, ProgramKind kind, const uint8_t color_types[8]);   // (program_for without its cache)
void program_wait(const Program* p);
uint64_t program_cache_stamp();   // (what the kept programs and pipelines are good for)
int shader_water_mode();          // ((Triforce) make_module's water simplification: 0 off, 1 medium, 2 low (vk_shader.cpp))
uint64_t program_cache_build_part();   // ((Triforce) the part of it only a new build changes: cache_set.h)
size_t program_cache_load_some(const std::unordered_set<uint64_t>& wanted, const std::function<void(Program&)>& fn,
                               bool computes = true, bool fallbacks = false);   // (computes: and every kept compute program)
/// (Triforce) The pipeline notes' programs, one key a note in their order: the order the program read-ahead reads in
void program_readahead_notes(const std::vector<uint64_t>& note_programs);
/// (Triforce, vk_draw.cpp) The noted pipelines of variants a read-ahead worker has just read, made before their draws: pipe_warm.h.
/// ((Triforce, test18) at: their place in the read-ahead's order, -1: none; a compute program's pipeline too)
void pipelines_warm(std::vector<std::unique_ptr<Program>>& variants, int64_t at);
/// ((Triforce, test18) vk_draw.cpp: the draws consumed the program at at in the read-ahead's order (where they are: pipe_warm.h)
void pipelines_warm_consumed(int64_t at);
/// ((Triforce, test18) vk_shader.cpp, the RAM short: the compute pipelines the warm made for programs still read ahead, taken
/// off them into out (the caller destroys them: no dispatch had one). False: the shelf was busy, nothing taken
bool readahead_computes_let_go(std::vector<VkPipeline>& out);
/// The precompile of every shader of the game (triforce_shaders.bin, from nx2/shader_census.py): how many programs it names, 0: none
size_t seed_open();
std::string seed_path();   // (triforce_shaders.bin, beside the game)
void seed_close();
/// Program i of the seed, translated and kept for the default state (null: kept already, or it does not translate); its modules are yours
std::unique_ptr<Program> seed_program(size_t i, int inputs = 0);
bool seed_is_compute(size_t i);
/// (hookshot) Seed program i, a compute program, kept in triforce_programs.bin with every texture variant its questions can make (up
/// to cap variants); made is given each variant not kept before
struct SeedVariants {
    size_t variants = 0, questions = 0;
    bool kept = false, failed = false, capped = false;
};
SeedVariants seed_compute(size_t i, size_t cap, const std::function<void(Program&)>& made);
/// (hookshot, the prediction: vk_predict.cpp) a kept graphics program variant as triforce_programs.bin has it: each stage's SPIR-V
struct KeptProgram {
    uint64_t key = 0, variant = 0;
    int64_t at = 0;   // ((Triforce, 11-24) the record's place in the file: program_cache_each calls in no order)
    bool mesh = false;
    std::vector<std::pair<VkShaderStageFlagBits, std::vector<uint32_t>>> stages;
};
void program_cache_each(const std::function<void(const KeptProgram&)>& fn);
void program_cache_borrow(uint64_t key, const std::function<void(Program&)>& fn);   // (made for fn, then let go; still kept)
/// (hookshot) Every kept graphics and mesh program's key, in the file's order, no record read; *loaded: the variants in memory already
std::vector<uint64_t> program_cache_keys(std::vector<Program*>* loaded);
const Program* program_find(uint64_t key, uint64_t variant);
/// (hookshot) The pipeline state list's variants, the same on every GPU: the answers with their stages numbered without the mesh
/// fallback's generated vertex stage, and their hash (a graphics or native mesh program's: its own); a loaded variant by that hash
std::vector<Program::Answer> answers_portable(const Program& p);
std::vector<Program::Answer> answers_here(const Program& p, std::vector<Program::Answer> portable);   // (the inverse)
uint64_t answers_hash_of(const std::vector<Program::Answer>& answers);   // (a variant's: Program::variant)
uint64_t portable_variant(const Program& p);
const Program* program_find_portable(uint64_t key, uint64_t variant);
/// (hookshot) The pipeline state list (vk_draw.cpp): a program by its stages' code keys (graphics: vertex, fragment; mesh: mesh,
/// fragment, task) and the vertex inputs and colour output types it was drawn with, from the seed (seed_open first): translated
/// and kept unless kept already (null then, or when it does not translate). *key_out: its key, 0 when a stage is not in the seed
std::unique_ptr<Program> seed_program_of(const uint64_t code[3], bool mesh, const uint32_t attributes[16], const uint8_t color_types[8],
                                         uint64_t* key_out);
/// (hookshot) The same for a program variant made by other textures' answers: translated with the answers given in the order asked
/// (Program::questions) and taking those answers (Program::answers, numbered as answers_portable has them); kept in memory for the
/// precompile, and in the program cache.
/// Null when a stage is not in the seed or it does not translate
const Program* seed_variant_of(const uint64_t code[3], bool mesh, const uint32_t attributes[16], const uint8_t color_types[8],
                               const std::vector<uint8_t>& questions, const std::vector<Program::Answer>& answers);
/// (hookshot) The variant nothing bound makes (each texture as its instruction declares it), kept the same way: what a state list
/// record with variant 0 and no answers or questions stands for (one converted from records that hold no texture answers)
const Program* seed_plain_of(const uint64_t code[3], bool mesh, const uint32_t attributes[16], const uint8_t color_types[8]);
/// (hookshot) That variant if it is loaded and ready: every slot answering the type its instruction declares. Its own variant is
/// the hash of those answers, not 0, so program_find_portable(key, 0) does not find it (state_list_prepare looks here first)
const Program* program_find_plain(uint64_t key);
/// The NVN stages of the bound program, for logs (stage field of each control section)
void log_program_stages(const NvnState& s, const char* why);
Shader::AttributeType attribute_type_of(uint32_t vattr);
Shader::TextureType handle_texture_type(uint32_t handle);
void shader_stats(int64_t* translated, int64_t* failed);
/// (Triforce) After the preparation's "N failed": a line for each "not translated" line's programs, all of them (those lines stop at 30)
void shader_fail_lines();
double shader_translate_ms();
void program_released(const nvn_prog* p);
/// ((Triforce) program_released, once no program pick has the shaders' lock let go for a read: program_read_once.h)
void program_released_after_reads(const nvn_prog* p);

// ---- ((Triforce) RX_VK_LOAD=create: the load of a program's kept variants when the game makes it, vk_programs.cpp) ----
/// A guest program as the game makes it (nvnProgramSetShaders), before any draw: its stages' code keys as Program::codes has
/// them (vertex or mesh, fragment, task, the header-only stage; a compute program's stage in codes[0]), read from the game's
/// memory now and hashed, nothing lowered. ok: it has a stage a draw or dispatch can use
struct CreatedProgram {
    uint64_t codes[4]{};
    bool ok = false, compute = false, mesh = false;
    int stages = 0;
};
CreatedProgram program_created_read(const nvn_prog& prog);   // (the game's thread; kept by the program's serial)
/// The key a pick makes for that program drawn with these vertex input formats and colour output types (a compute program's:
/// its stage's key); 0: no such serial was read
uint64_t program_created_key(uint64_t serial, const uint32_t vattr[16], const uint8_t color_types[8]);
void program_created_forget(uint64_t serial);
int64_t shader_translated();   // (programs translated so far, by any thread)
/// Where a kept record is in the program cache's file (its DiskRecord, as the load at a create call takes it)
struct CacheRecord {
    int64_t at = 0;
    size_t size = 0;
    uint32_t kind = 0;
};
/// Every kept program key not read in yet (the index's own copy: a create call on the game's thread then takes no lock a disk
/// read holds), and the kept compute programs' keys (the first start's warm builds their pipelines into the caches)
std::unordered_set<uint64_t> program_cache_kept_keys();
std::vector<uint64_t> program_cache_compute_keys();
/// The records of key not read in yet, as the list has them (none: no such key, or all read in)
std::vector<CacheRecord> program_cache_records(uint64_t key);
/// A record's variant (the hash of its answers) from its head alone, read by position through the caller's own handle. False:
/// the head does not read that way
bool program_cache_variant(FILE* in, uint64_t key, const CacheRecord& d, uint64_t* variant);
/// Those of want still not read in become read in (as program_cache_load takes them): the ones taken
std::vector<CacheRecord> program_cache_take(uint64_t key, const std::vector<CacheRecord>& want);
/// The kept variants of key in those records read through the caller's own handle and made ready, to out
void program_cache_read_records(FILE* in, uint64_t key, const std::vector<CacheRecord>& recs, std::vector<std::unique_ptr<Program>>& out);
/// A kept compute record's program without its code (its head and descriptors, by position around the SPIR-V): what a pick
/// needs. program_cache_complete reads the code and makes the module. Null: not a record to read this way
std::unique_ptr<Program> program_cache_read_light(FILE* in, uint64_t key, const CacheRecord& d);
/// A compute program read without its code (RX_VK_LOAD=create, program_cache_load): its SPIR-V read and its module made here,
/// before the first use of the module (vk_draw.cpp dispatch). True: it is whole (or was). False: its code did not read or
/// made no module; it is marked failed
bool program_cache_complete(Program& p);
bool program_cache_complete_unshared(Program& p, FILE* in);   // (the same for a program no other thread has yet, on the caller's handle)
/// The words of SPIR-V such a program has still to read (0: it has its module, or never lacked it). Where its code is, is kept by
/// the program's address in vk_shader.cpp, not in Program: Program's size is in the program cache's stamp
uint64_t program_cache_code_words(const Program& p);
/// (shader_mu held: programs_load_wait) a program a load made, into key's list; one whose variant is there already is let go
void program_cache_publish_locked(uint64_t key, std::unique_ptr<Program> p);
std::string program_cache_path();   // (the cache's file, for a thread's own handle on it; empty: no cache)

} // namespace mkwvk
