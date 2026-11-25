// (hookshot) AMD FSR 4, one of the temporal upscaler's engines (vk_fsr4.h). The frame chain it draws with is
// vk_temporal.cpp's, the same as NVIDIA DLSS's: the colour as the game's network samples it, the depth, the motion (the
// camera's and the skinned draws' own) and the camera jitter. Here are AMD's library, the upscale context and its dispatch.
// The host side follows the API guide of FidelityFX SDK 2.4 (Kits/FidelityFX/docs/getting-started/ffx-api.md): a Vulkan
// backend description chained to the upscale context description, inputs read in SHADER_READ_ONLY_OPTIMAL, the output
// written in GENERAL. First written for Lichii's OoT branch (madebyjordan, vk_fsr4_upscaler.cpp), GPL-3.0-or-later; its Linux
// path (a Vulkan FSR 4 library through dlopen) by N3oTraX.
//
// AMD's library is looked for in RX_VK_FSR_DIR=<folder> when set, the executable's folder (bin\ beside the launcher), then
// the game folder: amd_fidelityfx_loader_vk.dll, with amd_fidelityfx_upscaler_vk.dll beside it (Linux: a Vulkan FSR 4
// library, amd_fidelityfx_upscaler_vk.so). Of the upscalers it lists for this GPU the newest FSR 4 is taken, never an older
// one in its place. RX_VK_FSR4=0: FSR 4 out for this run.
//
// (Triforce) AMD FSR 4's frame generation, the Frame generation row's AMD FSR 4, is at the end of this file (fsr4fg): the same
// loader, with amd_fidelityfx_framegeneration_vk.dll beside it.
#include "vk_fsr4.h"

#include <atomic>
#include <cstdlib>

#include "vk_dlssg.h"   // (Triforce: frame generation is not asked of AMD's library beside NVIDIA's)
#include "vk_internal.h"
#include "vk_menu.h"    // (Triforce: the Frame generation row, opts.framegen)
#include "vk_temporal.h"

#include "fsr4_models.h"   // ((Triforce) the FSR 4 model row: the providers' scan and hook)

#ifdef HOOKSHOT_FSR
#include <cfloat>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#ifndef _WIN32
#include <dlfcn.h>
#include <unistd.h>
#endif

#include "fsr4_tune.h"   // (the tuned passes: AMD's shaders rewritten as the library makes them)
#include "spirv_unroll.h"
#include "temporal_rules.h"   // ((Triforce, FSR4-9, FSR4-10) plan_context, frame_ms)
#include "vk_gprof.h"
#include "vk_paths.h"
#include "vk_texture.h"

#include "api/include/ffx_api.h"
#include "api/include/ffx_api_types.h"
#include "api/include/vk/ffx_api_vk.h"
#include "upscalers/include/ffx_upscale.h"
#ifdef _WIN32
#include "framegeneration/include/ffx_framegeneration.h"   // (Triforce: fsr4fg, at the end of this file)
#endif
#endif
#include "vk_work.h"   // (after the others: the barriers here count as work for full_barrier)

namespace mkwvk {

// (vk_draw.cpp: a pipeline cache of FSR 4's own beside the pipeline cache's file, apart from the translator's files; a pipeline
// built through it)
VkPipelineCache own_pipeline_cache(const char* name, size_t* read, bool* refused);
bool own_pipeline_cache_save(VkPipelineCache cache, const char* name, size_t* saved);
VkResult own_cache_compute_pipeline(VkPipelineCache cache, const VkComputePipelineCreateInfo* ci, VkPipeline* out);

namespace {
int env_switch(const char* name) {   // (-1: unset)
    const char* e = getenv(name);
    return e && *e ? atoi(e) : -1;
}
// (what is known of FSR on this device: -1 not yet, else an FsrWhy. Set when AMD's library has been asked)
std::atomic<int> g_why{-1};
// ((Triforce, FSR4-7) the names the menu shows, by the version AMD's library runs here: "AMD FSR 4.1" and "AMD FSR 4.1
// Native AA". Written once by load() before g_named is set, read on any thread without a lock (the menu never waits)
char g_name[2][40] = {"AMD FSR 4", "AMD FSR 4 Native AA"};
std::atomic<bool> g_named{false};
// ((Triforce) the FSR 4 model row: whether Lite can be chosen here (an AMD GPU, the known library's providers hooked), and
// whether a Lite context failed this run (Auto from then on, the saved value left as it is)
std::atomic<bool> g_lite_available{false};
std::atomic<bool> g_lite_failed{false};
// ((Triforce) RX_VK_FSR4_STANDIN=1: AMD's library lists no FSR 4 for this GPU and the hooked Lite provider stands in: every
// context is Lite's, whatever the row says, and there is nothing to choose)
std::atomic<bool> g_standin{false};
}  // namespace

const char* fsr4_name(bool native_aa) {
    static const char* const plain[2] = {"AMD FSR 4", "AMD FSR 4 Native AA"};
    return g_named.load(std::memory_order_acquire) ? g_name[native_aa ? 1 : 0] : plain[native_aa ? 1 : 0];
}

FsrWhy fsr4_why() {
    if (!fsr4_built()) return FSR_NOT_BUILT;
    static const bool env_off = env_switch("RX_VK_FSR4") == 0;
    if (env_off) return FSR_ENV_OFF;
    const int w = g_why.load(std::memory_order_relaxed);
    return w < 0 ? FSR_OK : (FsrWhy)w;
}

int fsr4_model_env() {
    static const int env = [] {
        const char* e = getenv("RX_VK_FSR4_MODEL");
        const int v = fsr4_models::parse_model_env(e);
        if (e && *e && v < 0) logf("vk: AMD FSR 4: RX_VK_FSR4_MODEL=%s is not auto|lite; using Auto", e);
        return e && *e && v < 0 ? (int)FSR4_MODEL_AUTO : v;
    }();
    return env;
}

Fsr4Model fsr4_model() {
    if (!fsr4_built()) return FSR4_MODEL_AUTO;
    const int env = fsr4_model_env();
    if (env >= 0) return (Fsr4Model)env;
    return opts.fsr4_model == 1 ? FSR4_MODEL_LITE : FSR4_MODEL_AUTO;
}

bool fsr4_lite_available() { return fsr4_built() && g_lite_available.load(std::memory_order_relaxed); }

#ifdef HOOKSHOT_FSR

namespace {

#ifdef _WIN32
constexpr const char* kLoader = "amd_fidelityfx_loader_vk.dll";
#else
// (linux) no AMD loader exists there: the upscaler library itself, which exports the ffx entry points (a Vulkan FSR 4 build)
constexpr const char* kLoader = "amd_fidelityfx_upscaler_vk.so";
#endif

/// AMD's library, loaded once (the menu's thread may ask first: fsr4_probe), and the upscaler it has for this device
struct Library {
    std::mutex mu;
    bool tried = false, ok = false;
    // (Triforce) the loader and its entry points alone, for frame generation too (fsr4fg): there or not whatever upscaler
    // it lists. dir: the folder it was found in, where its other libraries lie
    bool lib_tried = false, lib_ok = false;
    std::string dir;
    HMODULE lib = nullptr;
    PfnFfxCreateContext create = nullptr;
    PfnFfxDestroyContext destroy = nullptr;
    PfnFfxConfigure configure = nullptr;   // (frame generation's alone: an upscaler library without it still upscales)
    PfnFfxQuery query = nullptr;
    PfnFfxDispatch dispatch = nullptr;
    uint64_t version_id = 0;
    VkDeviceContext device_context{};
};
// (lib() and st() are never destroyed: Hookshot leaves through ExitProcess / exit() with the device alive, and a destructor
// then would call into AMD's library after its DLL_PROCESS_DETACH, or under a render thread still recording with it)
Library& lib() {
    static Library& l = *new Library;
    return l;
}

/// An upscale context and the descriptions it was made from: it keeps pointers into them until it is destroyed, which
/// happens a few frames after it is let go (temporal_later), so each context has its own
struct Context {
    ffxCreateBackendVKDesc backend{};
    ffxOverrideVersion version{};
    // ((Triforce, FSR4-4) the API version this program was built with, which the SDK asks every upscale context to say
    // (ffx_upscale.h: "must be set to FFX_UPSCALER_VERSION"), as NX2navi's does)
    ffxCreateContextDescUpscaleVersion built{};
#ifndef _WIN32
    ffxCreateBackendVKDesc_DEPRECATED legacy_backend{};   // (linux) the backend description a Vulkan FSR 4 build like fsr4-vk reads
#endif
    ffxCreateContextDescUpscale upscale{};
    ffxContext context = nullptr;
    uint32_t width = 0, height = 0;   // (its output)
    // ((Triforce, FSR4-9) the render size it was made for: with drs any size up to the output's (the game's dynamic
    // resolution), else that one alone, as AMD's sample makes them)
    uint32_t render_w = 0, render_h = 0;
    bool drs = false;
    bool hdr = false;                 // (made for linear HDR colour: the other kind of colour makes it again)
    Fsr4Model model = FSR4_MODEL_AUTO;       // ((Triforce) the model asked for: a change makes it again
    Fsr4Model effective = FSR4_MODEL_AUTO;   // (what AMD made: Auto when Lite could not be)
    bool tuned = false;                      // (tune's hooks rewrote its shaders)
    uint64_t memory = 0;              // (what AMD's library says it holds)
    ~Context() {
        if (context) lib().destroy(&context, nullptr);
    }
};

/// The engine's state: used with the temporal upscaler's lock held
struct State {
    std::shared_ptr<Context> context;
    uint32_t in_w = 0, in_h = 0;   // (the inputs' size under this context: the largest render size it has had)
    // ((Triforce, FSR4-9) the render size changed under an output: the game's dynamic resolution, one context for every size
    // from then on)
    bool dynamic = false;
    std::chrono::steady_clock::time_point last{};
    uint64_t evals = 0;
    int told_resets = 0;
    float told_sharpness = -1.0f;   // ((Triforce, S1) the sharpness the log last said)
};
State& st() {
    static State& s = *new State;   // (never destroyed: lib()'s note)
    return s;
}

void on_message(uint32_t type, const wchar_t* message) {
    char text[512] = {};
    if (message) WideCharToMultiByte(CP_UTF8, 0, message, -1, text, (int)sizeof text - 1, nullptr, nullptr);
    logf("vk: AMD FSR 4: AMD's %s: %s", type == FFX_API_MESSAGE_TYPE_ERROR ? "error" : "warning", text);
}

/// The folders the library is looked for in: RX_VK_FSR_DIR, the executable's (bin\ beside the launcher), the game folder
std::vector<std::string> library_dirs() {
    std::vector<std::string> d;
    if (const char* e = getenv("RX_VK_FSR_DIR"); e && *e) d.emplace_back(e);
    char exe[MAX_PATH];
    DWORD n = GetModuleFileNameA(nullptr, exe, MAX_PATH);
    if (n && n < MAX_PATH) {
        std::string s(exe, n);
        d.push_back(s.substr(0, s.find_last_of("\\/")));
    }
    n = game_module_path(exe, MAX_PATH);
    if (n && n < MAX_PATH) {
        std::string s(exe, n);
        s = s.substr(0, s.find_last_of("\\/"));
        if (d.empty() || d.back() != s) d.push_back(s);
    }
    return d;
}

void* symbol(const char* name) {
#ifdef _WIN32
    return (void*)GetProcAddress(lib().lib, name);
#else
    return dlsym(lib().lib, name);
#endif
}

#ifdef _WIN32
/// ((Triforce) The FSR 4 model row) The upscaler library beside the loader in `dir`, when its file is one whose layout is
/// known (fsr4_models::load_known: its SHA-256), with what the scan found in it. Before the loader is asked anything, so the
/// loader's own load of that name finds this module
fsr4_models::KnownModule probe_models(const std::string& dir) {
    const auto t0 = std::chrono::steady_clock::now();
    fsr4_models::KnownModule known = fsr4_models::load_known(dir);
    const double scan_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    logf("vk: AMD FSR 4: models: GPU %s (vendor 0x%04x, device 0x%04x)", dev.props.deviceName, dev.props.vendorID,
         dev.props.deviceID);
    logf("vk: AMD FSR 4: models: %s (%.1f ms)", known.note.c_str(), scan_ms);
    if (!known.library) return known;
    const auto& m = known.scan;
    if (m.result.providers.empty()) {
        logf("vk: AMD FSR 4: models: %s: %s", m.name.c_str(), m.result.reason && *m.result.reason ? m.result.reason : "no providers");
        return known;
    }
    logf("vk: AMD FSR 4: models: %s at %p (%zu bytes): %zu provider(s), shape %s, Lite %s, registry %s", m.name.c_str(),
         (void*)m.base, m.size, m.result.providers.size(), m.result.shape_ok ? "ok" : "not understood",
         m.result.lite_present ? "yes" : "no", m.result.registry_found ? "found" : "not found");
    for (const auto& pr : m.result.providers)
        logf("vk: AMD FSR 4: models: %s (%s) vtable %p IsSupported %p instance %p", fsr4_models::model_name(pr.model),
             pr.class_name ? pr.class_name : "?", (void*)pr.vtable, (void*)pr.is_supported, pr.instance);
    return known;
}
#endif

/// AMD's passes tuned as the library makes them (fsr4_tune.h: measured gains, outputs bit for bit AMD's on Adrenalin 26.10.1):
/// the device functions it is handed are ours where it makes and destroys buffers, layouts, shader modules and compute
/// pipelines, writes descriptors and records binds and dispatches. At once: the network's layers 64 lanes wide, and the
/// weights the layers and the postpass copy into per-thread arrays (scratch memory) read from a tail of the library's storage
/// buffer instead. Later: the smaller layers with their loops unrolled from the library's own code (spirv_unroll.h, its
/// weights then constants in the code), built one at a time on a thread of their own and bound in place of the library's once
/// made (about a minute each the first time, the pipeline cache after). On an RX 6700 XT at 720p -> 1440p: 8.97 ms -> 4.04 ms.
/// (Triforce) Off unless RX_VK_FSR4_TUNE=1: AMD's passes as AMD made them by default (bit for bit AMD's output was checked on
/// one driver only, and the unrolled layers' constants let another driver's compiler order the maths otherwise). With it,
/// RX_VK_FSR4_UNROLL=0: no unrolled layers. On AMD's GPUs only.
/// The tail is kept per buffer: a pipeline reads it only in the buffer it was rewritten against, while that buffer lives and
/// every binding of it seen takes the tail in (offset 0, the whole buffer). Otherwise (the buffer destroyed, a binding that
/// leaves the tail out, or none seen through the functions watched here) AMD's own shader is built and bound in its place,
/// and the log says so once: a slower picture, never a wrong one.
/// The unrolling's limits are what keep it safe: unrolled whole, the larger layers (passes 4, 5, 10) came to 200,000 words
/// and AMD's compiler took 40-55 GB of commit charge for them, three at a time, until a PC with 16 GB of RAM crashed. Now a
/// layer is unrolled only while it stays under kUnrollWords (passes 1, 2 and 12: ~107,000 words, ~3 GB to build), one build
/// runs at a time, only with kBuildHeadroom of memory to spare, and a build that fails is not tried again. The window closing
/// stops them (fsr4_close): one not started does not start, the one building is waited for (10 s at most)
namespace tune {
std::mutex mu;
PFN_vkCreateBuffer real_cb = nullptr;
PFN_vkDestroyBuffer real_db = nullptr;
PFN_vkCreateShaderModule real_csm = nullptr;
PFN_vkDestroyShaderModule real_dsm = nullptr;
PFN_vkCreateComputePipelines real_ccp = nullptr;
PFN_vkCreateDescriptorSetLayout real_cdsl = nullptr;
PFN_vkCreatePipelineLayout real_cpl = nullptr;
PFN_vkDestroyPipeline real_dp = nullptr;
PFN_vkUpdateDescriptorSets real_uds = nullptr;
PFN_vkCmdPushDescriptorSetKHR real_push = nullptr, real_push14 = nullptr;
PFN_vkGetDescriptorEXT real_gd = nullptr;
PFN_vkGetBufferDeviceAddress real_bda = nullptr, real_bda_khr = nullptr;
PFN_vkCmdBindPipeline real_bind = nullptr;
PFN_vkCmdDispatch real_dispatch = nullptr;
PFN_vkCmdUpdateBuffer real_update = nullptr;
PFN_vkCmdPipelineBarrier real_barrier = nullptr;
constexpr uint64_t kTail = 64 << 10;   // (bytes added to the library's big storage buffer: the weights of the layers and the postpass, ~32 KB)

/// The library's big storage buffer (each upscale context makes one) and the tail added to it, by generation: the shaders
/// rewritten against it read the tail at its size, in it alone
struct Big {
    VkBuffer buffer = VK_NULL_HANDLE;
    uint64_t size = 0;                // (as the library asked for it: the tail starts there)
    VkDeviceAddress address = 0;      // (descriptor buffers: where the library was told it is)
    std::vector<uint32_t> tail;       // (what the tail holds)
    bool due = false;                 // (to be written before the first dispatch that reads it)
    int bound = 0;                    // (its bindings seen: 0 none yet, 1 each took the tail in, -1 one left it out)
};
std::unordered_map<uint64_t, Big> bigs;              // (alive ones only: a generation not here was destroyed)
std::unordered_map<VkBuffer, uint64_t> big_of;
uint64_t cur = 0, next_gen = 1;                      // (cur: the newest alive, 0 none: new modules are rewritten against it)
std::unordered_set<uint64_t> told;                   // (generations whose pipelines the log has said fell back)

// (the library's descriptor set layouts and pipeline layouts as made, to make copies from: an unrolled layer's, AMD's own)
struct SetLayoutInfo {
    VkDescriptorSetLayoutCreateFlags flags = 0;
    std::vector<VkDescriptorSetLayoutBinding> bindings;
    std::vector<std::vector<VkSampler>> samplers;
};
std::unordered_map<VkDescriptorSetLayout, SetLayoutInfo> set_layouts;
struct LayoutInfo {
    std::vector<VkDescriptorSetLayout> sets;
    std::vector<VkPushConstantRange> push;
};
std::unordered_map<VkPipelineLayout, LayoutInfo> layouts;
/// A layout's definition, whole (the set layouts' too): what a copy is made from, whatever becomes of the library's
struct LayoutCopy {
    std::vector<SetLayoutInfo> sets;
    std::vector<VkPushConstantRange> push;
};

struct Module {
    uint8_t kind = 0;                                       // (flags) 1: 64 lanes, 2: reads the tail
    uint64_t gen = 0;                                       // (2: the Big it reads)
    std::shared_ptr<const std::vector<uint32_t>> code;      // (2: the library's own code, as it gave it)
    std::string entry;
};
std::unordered_map<VkShaderModule, Module> modules;

/// What one of the library's pipelines was made from, its own code: to make it as AMD made it when the tail cannot be read
struct Plain {
    std::shared_ptr<const std::vector<uint32_t>> code;
    std::string entry;
    VkPipelineCreateFlags flags = 0;
    VkPipelineShaderStageCreateFlags stage_flags = 0;
    uint32_t lanes = 0;   // (the lane count it asked for, 0 none)
    bool specialized = false;
    std::vector<VkSpecializationMapEntry> spec_map;
    std::vector<uint8_t> spec_data;
    LayoutCopy layout;
};
struct TailPipe {
    uint64_t gen = 0;
    std::shared_ptr<const Plain> plain;
    VkPipeline twin = VK_NULL_HANDLE;   // (AMD's own, made once the tail could not be read)
    bool twin_failed = false;
};
std::unordered_map<VkPipeline, TailPipe> tail_pipes;
std::atomic<int> tail_count{0};
/// (a command buffer's last compute bind: the library's pipeline, and whether its unrolled one was bound in its place.
/// cmd_dispatch goes by what was bound: a job may publish the unrolled one between the bind and the dispatch)
struct Bind {
    VkPipeline pipeline = VK_NULL_HANDLE;
    bool unrolled = false;
};
std::unordered_map<VkCommandBuffer, Bind> bound;
int layers64 = 0;

// (the unrolled pipelines: made by jobs, bound in the library's place; a job whose pipeline was destroyed meanwhile drops
// what it made)
std::unordered_map<VkPipeline, VkPipeline> better;
std::unordered_set<VkPipeline> pending, cancelled;
std::atomic<int> better_count{0};
/// The jobs: one builds at a time (a first build is a minute of CPU and ~3 GB of the driver's memory). Never destroyed, as
/// lib(): a job still in the driver when the process exits must not find them gone
struct Jobs {
    std::mutex mu;
    std::condition_variable cv;
    int slots = 1;
    int running = 0;   // (threads started and not yet ended: fsr4_close waits for them)
};
Jobs& jobs() {
    static Jobs& j = *new Jobs;
    return j;
}
std::atomic<bool> closing{false};   // (the window closed: no job starts, the one building leaves what it made)
std::atomic<bool> suppressed{false};   // ((Triforce) the context being made runs AMD's shaders: the create hooks pass through
constexpr size_t kUnrollWords = 120000;              // (a layer unrolled to more than this is left rolled)
constexpr uint64_t kBuildHeadroom = 8ull << 30;     // (memory to spare before a build starts)

bool on() {
    static const bool v = env_switch("RX_VK_FSR4_TUNE") == 1 && dev.props.vendorID == 0x1002;   // ((Triforce) opt-in)
    return v;
}
/// ((Triforce) The context being made is not tuned (Lite forced on a card whose own pick is another model): create_buffer,
/// create_shader_module and create_compute_pipelines pass through. cmd_dispatch is not gated: an older context's tail is
/// still served
void suppress(bool on) { suppressed.store(on, std::memory_order_relaxed); }
bool unroll_on() {
    static const bool v = env_switch("RX_VK_FSR4_UNROLL") != 0;
    return v;
}
/// What the system can still commit: Windows' commit charge left (RAM and page file), Linux's available memory and free swap.
/// True when unknown
bool build_headroom(uint64_t* avail) {
    *avail = 0;
#ifdef _WIN32
    MEMORYSTATUSEX m{};
    m.dwLength = sizeof m;
    if (!GlobalMemoryStatusEx(&m)) return true;
    *avail = m.ullAvailPageFile;
#else
    FILE* f = fopen("/proc/meminfo", "r");
    if (!f) return true;
    unsigned long long mem = 0, swap = 0, v = 0;
    char key[64];
    while (fscanf(f, "%63s %llu kB\n", key, &v) == 2) {
        if (!strcmp(key, "MemAvailable:")) mem = v;
        else if (!strcmp(key, "SwapFree:")) swap = v;
    }
    fclose(f);
    *avail = (uint64_t)(mem + swap) << 10;
#endif
    return *avail >= kBuildHeadroom;
}

/// (mu held) A buffer let go, or its handle given out again: if it was a Big, its tail with it. Its pipelines then read none
/// (cmd_dispatch binds AMD's own), and no new module is rewritten against it
void forget_locked(VkBuffer b) {
    auto it = big_of.find(b);
    if (it == big_of.end()) return;
    if (cur == it->second) cur = 0;
    bigs.erase(it->second);
    big_of.erase(it);
}

VKAPI_ATTR VkResult VKAPI_CALL create_buffer(VkDevice d, const VkBufferCreateInfo* ci, const VkAllocationCallbacks* a, VkBuffer* b) {
    if (suppressed.load(std::memory_order_relaxed)) return real_cb(d, ci, a, b);
    VkBufferCreateInfo c = *ci;
    const bool grow = (ci->usage & VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) && ci->size > (64ull << 20);
    // (the tail is written with vkCmdUpdateBuffer: its buffer a transfer's destination, whatever the library asked)
    if (grow) c.size += kTail, c.usage |= VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    const VkResult r = real_cb(d, &c, a, b);
    if (r == VK_SUCCESS) {
        std::lock_guard lk(mu);
        forget_locked(*b);   // (a handle given out before, its destruction not seen: not what it was)
        if (grow) {
            const uint64_t gen = next_gen++;
            Big& g = bigs[gen];
            g.buffer = *b, g.size = ci->size;
            big_of[*b] = gen, cur = gen;
        }
    }
    return r;
}
VKAPI_ATTR void VKAPI_CALL destroy_buffer(VkDevice d, VkBuffer b, const VkAllocationCallbacks* a) {
    if (b) {
        std::lock_guard lk(mu);
        forget_locked(b);
    }
    real_db(d, b, a);
}
/// Where the library is told a Big is (descriptor buffers: its descriptors are made from addresses)
VKAPI_ATTR VkDeviceAddress VKAPI_CALL buffer_address(VkDevice d, const VkBufferDeviceAddressInfo* info) {
    const VkDeviceAddress r = real_bda(d, info);
    std::lock_guard lk(mu);
    if (auto it = big_of.find(info->buffer); it != big_of.end()) bigs[it->second].address = r;
    return r;
}
VKAPI_ATTR VkDeviceAddress VKAPI_CALL buffer_address_khr(VkDevice d, const VkBufferDeviceAddressInfo* info) {
    const VkDeviceAddress r = real_bda_khr(d, info);
    std::lock_guard lk(mu);
    if (auto it = big_of.find(info->buffer); it != big_of.end()) bigs[it->second].address = r;
    return r;
}

/// (mu held) A storage-buffer binding of a Big seen: whether it takes the tail in (fsr4_tune::covers_tail). A binding of
/// exactly what the library asked for is widened to the tail first (*range), as the buffer is that large
void note_binding_locked(Big& g, uint64_t gen, bool dynamic, uint64_t offset, uint64_t* range) {
    if (!dynamic && *range == g.size && g.size + kTail <= dev.props.limits.maxStorageBufferRange)
        *range = fsr4_tune::widened_range(offset, *range, g.size, kTail);
    const bool ok = !dynamic && fsr4_tune::covers_tail(offset, *range, g.size, kTail);
    if (ok && g.bound == 0) g.bound = 1;
    if (!ok && g.bound != -1) {
        g.bound = -1;
        if (told.insert(gen).second)
            logf("vk: AMD FSR 4: its storage buffer is bound without the tail (%s, offset %llu, range %llu of %llu): AMD's own "
                 "shaders in place of the tuned ones that read it, for this context",
                 dynamic ? "dynamic" : "plain", (unsigned long long)offset, (unsigned long long)*range, (unsigned long long)g.size);
    }
}
/// (mu held) Descriptor writes (vkUpdateDescriptorSets, vkCmdPushDescriptorSet): each binding of a Big noted. When one is
/// widened, the writes to pass on are *out (copies, in `infos`); else the library's own
const VkWriteDescriptorSet* note_writes_locked(uint32_t n, const VkWriteDescriptorSet* w, std::vector<VkWriteDescriptorSet>& out,
                                               std::vector<std::vector<VkDescriptorBufferInfo>>& infos) {
    if (big_of.empty()) return w;
    for (uint32_t i = 0; i < n; i++) {
        const bool dynamic = w[i].descriptorType == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER_DYNAMIC;
        if ((w[i].descriptorType != VK_DESCRIPTOR_TYPE_STORAGE_BUFFER && !dynamic) || !w[i].pBufferInfo) continue;
        for (uint32_t k = 0; k < w[i].descriptorCount; k++) {
            auto it = big_of.find(w[i].pBufferInfo[k].buffer);
            if (it == big_of.end()) continue;
            uint64_t range = w[i].pBufferInfo[k].range;
            note_binding_locked(bigs[it->second], it->second, dynamic, w[i].pBufferInfo[k].offset, &range);
            if (range == w[i].pBufferInfo[k].range) continue;
            if (out.empty()) out.assign(w, w + n), infos.resize(n);
            if (infos[i].empty()) infos[i].assign(w[i].pBufferInfo, w[i].pBufferInfo + w[i].descriptorCount), out[i].pBufferInfo = infos[i].data();
            infos[i][k].range = range;
        }
    }
    return out.empty() ? w : out.data();
}
VKAPI_ATTR void VKAPI_CALL update_sets(VkDevice d, uint32_t n, const VkWriteDescriptorSet* w, uint32_t copies, const VkCopyDescriptorSet* c) {
    std::vector<VkWriteDescriptorSet> out;
    std::vector<std::vector<VkDescriptorBufferInfo>> infos;
    {
        std::lock_guard lk(mu);
        w = note_writes_locked(n, w, out, infos);
    }
    real_uds(d, n, w, copies, c);
}
VKAPI_ATTR void VKAPI_CALL push_set(VkCommandBuffer cb, VkPipelineBindPoint bp, VkPipelineLayout l, uint32_t set, uint32_t n,
                                    const VkWriteDescriptorSet* w) {
    std::vector<VkWriteDescriptorSet> out;
    std::vector<std::vector<VkDescriptorBufferInfo>> infos;
    {
        std::lock_guard lk(mu);
        w = note_writes_locked(n, w, out, infos);
    }
    real_push(cb, bp, l, set, n, w);
}
VKAPI_ATTR void VKAPI_CALL push_set14(VkCommandBuffer cb, VkPipelineBindPoint bp, VkPipelineLayout l, uint32_t set, uint32_t n,
                                      const VkWriteDescriptorSet* w) {
    std::vector<VkWriteDescriptorSet> out;
    std::vector<std::vector<VkDescriptorBufferInfo>> infos;
    {
        std::lock_guard lk(mu);
        w = note_writes_locked(n, w, out, infos);
    }
    real_push14(cb, bp, l, set, n, w);
}
/// (descriptor buffers) A storage buffer's descriptor made from an address in a Big: noted as a binding of it
VKAPI_ATTR void VKAPI_CALL get_descriptor(VkDevice d, const VkDescriptorGetInfoEXT* info, size_t size, void* out) {
    VkDescriptorGetInfoEXT copy;
    VkDescriptorAddressInfoEXT address;
    if (info && info->type == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER && info->data.pStorageBuffer) {
        std::lock_guard lk(mu);
        const VkDescriptorAddressInfoEXT& at = *info->data.pStorageBuffer;
        for (auto& [gen, g] : bigs) {
            if (!g.address || at.address < g.address || at.address >= g.address + g.size + kTail) continue;
            uint64_t range = at.range;
            note_binding_locked(g, gen, false, at.address - g.address, &range);
            if (range != at.range) {
                copy = *info, address = at, address.range = range, copy.data.pStorageBuffer = &address;
                info = &copy;
            }
            break;
        }
    }
    real_gd(d, info, size, out);
}

VKAPI_ATTR VkResult VKAPI_CALL create_set_layout(VkDevice d, const VkDescriptorSetLayoutCreateInfo* ci, const VkAllocationCallbacks* a,
                                                 VkDescriptorSetLayout* l) {
    const VkResult r = real_cdsl(d, ci, a, l);
    if (r == VK_SUCCESS) {
        std::lock_guard lk(mu);
        set_layouts.erase(*l);   // (a handle the driver gave out before: not what it was)
    }
    if (r == VK_SUCCESS && !ci->pNext) {   // (one with extension structures is not copied: its pipelines are left as they are)
        SetLayoutInfo s;
        s.flags = ci->flags;
        s.bindings.assign(ci->pBindings, ci->pBindings + ci->bindingCount);
        s.samplers.resize(ci->bindingCount);
        for (uint32_t i = 0; i < ci->bindingCount; i++)
            if (ci->pBindings[i].pImmutableSamplers)
                s.samplers[i].assign(ci->pBindings[i].pImmutableSamplers, ci->pBindings[i].pImmutableSamplers + ci->pBindings[i].descriptorCount);
        std::lock_guard lk(mu);
        set_layouts[*l] = std::move(s);
    }
    return r;
}
VKAPI_ATTR VkResult VKAPI_CALL create_pipeline_layout(VkDevice d, const VkPipelineLayoutCreateInfo* ci, const VkAllocationCallbacks* a,
                                                      VkPipelineLayout* l) {
    const VkResult r = real_cpl(d, ci, a, l);
    if (r == VK_SUCCESS) {
        std::lock_guard lk(mu);
        layouts.erase(*l);
    }
    if (r == VK_SUCCESS && !ci->pNext) {
        LayoutInfo li;
        li.sets.assign(ci->pSetLayouts, ci->pSetLayouts + ci->setLayoutCount);
        li.push.assign(ci->pPushConstantRanges, ci->pPushConstantRanges + ci->pushConstantRangeCount);
        std::lock_guard lk(mu);
        layouts[*l] = std::move(li);
    }
    return r;
}
/// (mu held) A pipeline layout of the library's, whole: false when it or one of its set layouts was not copied
bool layout_copy_locked(VkPipelineLayout l, LayoutCopy* out) {
    auto lay = layouts.find(l);
    if (lay == layouts.end()) return false;
    out->sets.clear();
    for (VkDescriptorSetLayout s : lay->second.sets) {
        auto sl = set_layouts.find(s);
        if (sl == set_layouts.end()) return false;
        out->sets.push_back(sl->second);
    }
    out->push = lay->second.push;
    return true;
}
/// A layout of our own, defined as the library's was: compatible with the sets it binds
bool make_layout(VkDevice d, const LayoutCopy& lc, VkPipelineLayout* layout, std::vector<VkDescriptorSetLayout>* sets) {
    *layout = VK_NULL_HANDLE;
    bool ok = true;
    for (const SetLayoutInfo& s : lc.sets) {
        std::vector<VkDescriptorSetLayoutBinding> b = s.bindings;
        for (size_t k = 0; k < b.size(); k++) b[k].pImmutableSamplers = s.samplers[k].empty() ? nullptr : s.samplers[k].data();
        VkDescriptorSetLayoutCreateInfo sci{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
        sci.flags = s.flags, sci.bindingCount = (uint32_t)b.size(), sci.pBindings = b.data();
        VkDescriptorSetLayout copy = VK_NULL_HANDLE;
        if (real_cdsl(d, &sci, nullptr, &copy) != VK_SUCCESS) { ok = false; break; }
        sets->push_back(copy);
    }
    if (ok) {
        VkPipelineLayoutCreateInfo lci{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
        lci.setLayoutCount = (uint32_t)sets->size(), lci.pSetLayouts = sets->data();
        lci.pushConstantRangeCount = (uint32_t)lc.push.size(), lci.pPushConstantRanges = lc.push.data();
        ok = real_cpl(d, &lci, nullptr, layout) == VK_SUCCESS;
    }
    if (!ok) {
        for (VkDescriptorSetLayout s : *sets) vkDestroyDescriptorSetLayout(d, s, nullptr);
        sets->clear();
    }
    return ok;
}

VKAPI_ATTR VkResult VKAPI_CALL create_shader_module(VkDevice d, const VkShaderModuleCreateInfo* ci, const VkAllocationCallbacks* a,
                                                   VkShaderModule* m) {
    if (suppressed.load(std::memory_order_relaxed)) return real_csm(d, ci, a, m);
    const uint32_t* code = ci->pCode;
    const size_t words = ci->codeSize / 4;
    const std::string entry = fsr4_tune::entry_name(code, words);
    Module mod;
    mod.entry = entry;
    std::vector<uint32_t> tuned;
    VkShaderModuleCreateInfo c = *ci;
    {
        std::lock_guard lk(mu);
        if (fsr4_tune::wants_wave64(entry) && dev.subgroup_max >= 64 && !fsr4_tune::lane_dependent(code, words)) mod.kind |= 1;
        // (the layers and the postpass copy constant weight tables into per-thread arrays, which the driver keeps in scratch
        // memory: read from the tail of the newest Big instead, while it has room)
        std::vector<uint32_t> add;
        auto g = bigs.find(cur);
        if ((fsr4_tune::is_postpass(entry) || fsr4_tune::wants_wave64(entry)) && g != bigs.end() &&
            fsr4_tune::arrays_to_buffer(code, words, (uint32_t)(g->second.size / 4 + g->second.tail.size()), tuned, add)) {
            std::vector<uint32_t>& tail = g->second.tail;
            if ((tail.size() + add.size()) * 4 <= kTail) {
                tail.insert(tail.end(), add.begin(), add.end());
                c.codeSize = tuned.size() * 4, c.pCode = tuned.data(), mod.kind |= 2, mod.gen = cur, g->second.due = true;
                logf("vk: AMD FSR 4: tuned %s: its constant arrays read from the end of its storage buffer (%zu words there)",
                     entry.c_str(), tail.size());
            } else {
                logf("vk: AMD FSR 4: %s: its constant arrays left as they were (the tail is full)", entry.c_str());
            }
        }
    }
    // (its own code kept: AMD's pipeline made from it when the tail cannot be read, and the layers unrolled from it)
    if (mod.kind & 2) mod.code = std::make_shared<const std::vector<uint32_t>>(code, code + words);
    const VkResult r = real_csm(d, &c, a, m);
    if (r == VK_SUCCESS) {
        std::lock_guard lk(mu);
        modules.erase(*m);   // (a handle given out before)
        if (mod.kind) modules[*m] = std::move(mod);
    }
    return r;
}
VKAPI_ATTR void VKAPI_CALL destroy_shader_module(VkDevice d, VkShaderModule m, const VkAllocationCallbacks* a) {
    if (m) {
        std::lock_guard lk(mu);
        modules.erase(m);
    }
    real_dsm(d, m, a);
}

/// AMD's own pipeline, from the library's code and a copy of its layout: bound in place of one whose tail cannot be read.
/// VK_NULL_HANDLE when it could not be made
VkPipeline make_plain(const Plain& p) {
    VkPipelineLayout layout = VK_NULL_HANDLE;
    std::vector<VkDescriptorSetLayout> sets;
    if (!make_layout(dev.device, p.layout, &layout, &sets)) return VK_NULL_HANDLE;
    VkPipeline made = VK_NULL_HANDLE;
    VkShaderModuleCreateInfo mci{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    mci.codeSize = p.code->size() * 4, mci.pCode = p.code->data();
    VkShaderModule module = VK_NULL_HANDLE;
    if (real_csm(dev.device, &mci, nullptr, &module) == VK_SUCCESS) {
        VkPipelineShaderStageRequiredSubgroupSizeCreateInfo lanes{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO};
        lanes.requiredSubgroupSize = p.lanes;
        VkSpecializationInfo spec{};
        spec.mapEntryCount = (uint32_t)p.spec_map.size(), spec.pMapEntries = p.spec_map.data();
        spec.dataSize = p.spec_data.size(), spec.pData = p.spec_data.data();
        VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
        ci.flags = p.flags & ~(VkPipelineCreateFlags)VK_PIPELINE_CREATE_DERIVATIVE_BIT;
        ci.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO};
        ci.stage.pNext = p.lanes ? &lanes : nullptr;
        ci.stage.flags = p.stage_flags, ci.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT, ci.stage.module = module;
        ci.stage.pName = p.entry.c_str(), ci.stage.pSpecializationInfo = p.specialized ? &spec : nullptr;
        ci.layout = layout, ci.basePipelineIndex = -1;
        if (real_ccp(dev.device, VK_NULL_HANDLE, 1, &ci, nullptr, &made) != VK_SUCCESS) made = VK_NULL_HANDLE;
        real_dsm(dev.device, module, nullptr);
    }
    vkDestroyPipelineLayout(dev.device, layout, nullptr);
    for (VkDescriptorSetLayout s : sets) vkDestroyDescriptorSetLayout(dev.device, s, nullptr);
    return made;
}

/// The unrolled layers' pipeline cache (mkw_vk_fsr4_pipelines.bin beside the pipeline cache's file): kept apart from the
/// translator's pipeline cache, whose file is kept for one set of translated shaders (vk_draw.cpp pcache_init), so that an
/// update that changes the translator keeps them. Before it, an update that changed the translator built them cold again at its first FSR 4 frame, about 50
/// s and 3 GB of memory each on an RX 6700 XT. Made at the first build; written after a layer's build when its data grew: the
/// driver may hand a layer over at once from its own disk cache, which a game folder of another path (an update's) does not
/// share, so a quick build is no sign that the file holds it
constexpr const char* kOwnCacheFile = "mkw_vk_fsr4_pipelines.bin";
std::mutex own_cache_save_mu;   // (a layer's job and the preparation's warm both write the file)
size_t own_cache_saved = 0;     // (the bytes last read or written: own_cache, save_own_cache)
VkPipelineCache own_cache() {
    static std::mutex m;
    static VkPipelineCache cache = VK_NULL_HANDLE;
    static bool made = false;
    std::lock_guard lk(m);
    if (made) return cache;
    made = true;
    size_t read = 0;
    bool refused = false;
    cache = own_pipeline_cache(kOwnCacheFile, &read, &refused);
    own_cache_saved = read;
    logf("vk: AMD FSR 4: the unrolled layers' pipeline cache: %s", read ? "read" : refused ? "made by another driver or GPU: starts empty" : "starts empty");
    return cache;
}
/// The unrolled layers' cache written to its file when it grew (false: it could not be)
bool save_own_cache() {
    std::lock_guard lk(own_cache_save_mu);
    return own_pipeline_cache_save(own_cache(), kOwnCacheFile, &own_cache_saved);
}
/// A job: the layer unrolled and built with copies of its layouts; bound in the library's pipeline's place when made. Its
/// thread counted in jobs().running from before it starts (fsr4_close waits for it)
void build_unrolled(VkPipeline original, std::shared_ptr<const std::vector<uint32_t>> code, std::string name, VkComputePipelineCreateInfo ci,
                    VkPipelineLayout layout, std::vector<VkDescriptorSetLayout> sets) {
    struct Ended {
        ~Ended() {
            Jobs& j = jobs();
            { std::lock_guard lk(j.mu); j.running--; }
            j.cv.notify_all();
        }
    } ended;
    Jobs& j = jobs();
    {
        std::unique_lock lk(j.mu);
        j.cv.wait(lk, [&j] { return j.slots > 0 || closing.load(); });
        if (closing) return;   // (the window closed: not started. What it holds goes with the process)
        j.slots--;
    }
    struct Slot {
        ~Slot() {
            Jobs& j = jobs();
            { std::lock_guard lk(j.mu); j.slots++; }
            j.cv.notify_all();
        }
    } slot;
    const auto t0 = std::chrono::steady_clock::now();
    std::vector<uint32_t> unrolled;
    int left = -1;
    const bool ok = spirv_unroll::unroll_all(code->data(), code->size(), unrolled, kUnrollWords, 64, &left) && left == 0;
    VkPipeline made = VK_NULL_HANDLE;
    bool cached = false;   // (taken from the cache, not compiled)
    if (ok && !closing) {
        VkShaderModuleCreateInfo mci{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
        mci.codeSize = unrolled.size() * 4, mci.pCode = unrolled.data();
        VkShaderModule module = VK_NULL_HANDLE;
        if (real_csm(dev.device, &mci, nullptr, &module) == VK_SUCCESS) {
            VkPipelineShaderStageRequiredSubgroupSizeCreateInfo lanes{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO};
            lanes.requiredSubgroupSize = 64;
            ci.stage.pNext = &lanes, ci.stage.module = module, ci.stage.pName = name.c_str(), ci.layout = layout;
            ci.stage.pSpecializationInfo = nullptr;   // (only layers without one are taken)
            ci.basePipelineHandle = VK_NULL_HANDLE, ci.basePipelineIndex = -1;
            ci.flags &= ~(VkPipelineCreateFlags)VK_PIPELINE_CREATE_DERIVATIVE_BIT;
            // (through its own pipeline cache, kept across runs and updates: built once, loaded after. Asked of the caches
            // first, with no compile: a layer built before costs nothing then, and the memory a compile wants is not asked
            // for it. Before, a PC with less than kBuildHeadroom to spare at the first FSR 4 frame (a 16 GB one, often) ran
            // without the unrolled layers even when their pipelines were in the caches. A failure is not tried again: the
            // library's pipeline stays)
            VkResult rr = VK_PIPELINE_COMPILE_REQUIRED;
            if (dev.vk13.pipelineCreationCacheControl) {
                VkComputePipelineCreateInfo ask = ci;
                ask.flags |= VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT;
                rr = own_cache_compute_pipeline(own_cache(), &ask, &made);
                cached = rr == VK_SUCCESS && made;
                if (!cached) made = VK_NULL_HANDLE, rr = VK_PIPELINE_COMPILE_REQUIRED;
            }
            uint64_t avail = 0;
            if (!cached && !closing) {
                if (build_headroom(&avail)) {
                    rr = own_cache_compute_pipeline(own_cache(), &ci, &made);
                } else {
                    logf("vk: AMD FSR 4: %s: not unrolled now: %llu MB of memory to spare, %llu wanted (the next start tries again)",
                         name.c_str(), (unsigned long long)(avail >> 20), (unsigned long long)(kBuildHeadroom >> 20));
                    rr = VK_PIPELINE_COMPILE_REQUIRED;
                }
            }
            // (the window closed while the driver built it: fsr4_close may have stopped waiting, and the process be ending.
            // Nothing more is touched, its cache not written either: the next start finds it in the driver's own disk cache, or
            // builds it again, and writes the file then)
            if (closing) return;
            if (rr != VK_SUCCESS) {
                made = VK_NULL_HANDLE;
                if (rr != VK_PIPELINE_COMPILE_REQUIRED)
                    logf("vk: AMD FSR 4: %s: its unrolled pipeline was not built (%d): AMD's stays", name.c_str(), (int)rr);
            }
            real_dsm(dev.device, module, nullptr);
        }
    }
    if (closing) return;
    vkDestroyPipelineLayout(dev.device, layout, nullptr);
    for (VkDescriptorSetLayout s : sets) vkDestroyDescriptorSetLayout(dev.device, s, nullptr);
    const double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    {
        std::lock_guard lk(mu);
        pending.erase(original);
        if (cancelled.erase(original) || !made) {
            if (made) real_dp(dev.device, made, nullptr);
        } else {
            better[original] = made;
            better_count++;
        }
    }
    // (each one kept as soon as it is built, whether or not the game closes normally: a build of a minute is not done again)
    if (made && !save_own_cache())
        logf("vk: AMD FSR 4: %s: its unrolled pipeline could not be saved (the next start builds it again)", name.c_str());
    if (made) logf("vk: AMD FSR 4: tuned %s: its loops unrolled (%zu -> %zu words), bound in its place from now (%.1f s %s)",
                   name.c_str(), code->size(), unrolled.size(), s, cached ? "from the caches" : "to build");
    else if (!ok) logf("vk: AMD FSR 4: %s left rolled (%d loops kept: unrolled whole it would pass %zu words, or they cannot be)",
                       name.c_str(), left, kUnrollWords);
}

VKAPI_ATTR VkResult VKAPI_CALL create_compute_pipelines(VkDevice d, VkPipelineCache cache, uint32_t n,
                                                       const VkComputePipelineCreateInfo* ci, const VkAllocationCallbacks* a,
                                                       VkPipeline* p) {
    if (suppressed.load(std::memory_order_relaxed)) return real_ccp(d, cache, n, ci, a, p);
    std::vector<VkComputePipelineCreateInfo> v(ci, ci + n);
    std::vector<VkPipelineShaderStageRequiredSubgroupSizeCreateInfo> lanes(n);
    std::vector<uint8_t> kind(n, 0);
    std::vector<uint64_t> gen(n, 0);
    std::vector<std::shared_ptr<const std::vector<uint32_t>>> code(n);
    std::vector<std::string> entry(n);
    std::vector<std::shared_ptr<Plain>> plain(n);
    std::vector<VkShaderModule> own(n, VK_NULL_HANDLE);   // (modules of the library's own code, made here: destroyed after)
    {
        std::lock_guard lk(mu);
        for (uint32_t i = 0; i < n; i++) {
            auto k = modules.find(ci[i].stage.module);
            if (k == modules.end()) continue;
            kind[i] = k->second.kind, gen[i] = k->second.gen, code[i] = k->second.code, entry[i] = k->second.entry;
            const VkBaseInStructure* s = (const VkBaseInStructure*)ci[i].stage.pNext;
            if (kind[i] & 2) {
                // (one that reads the tail: what AMD's own is made from, kept. A creation that carries more than a lane count
                // cannot be made again from that: AMD's own code then, now)
                auto pl = std::make_shared<Plain>();
                const bool simple = !ci[i].pNext && (!s || (s->sType == VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO && !s->pNext));
                if (simple && layout_copy_locked(ci[i].layout, &pl->layout)) {
                    pl->code = code[i], pl->entry = ci[i].stage.pName ? ci[i].stage.pName : "main";
                    pl->flags = ci[i].flags, pl->stage_flags = ci[i].stage.flags;
                    pl->lanes = s ? ((const VkPipelineShaderStageRequiredSubgroupSizeCreateInfo*)s)->requiredSubgroupSize : 0;
                    if (const VkSpecializationInfo* sp = ci[i].stage.pSpecializationInfo) {
                        pl->specialized = true;
                        pl->spec_map.assign(sp->pMapEntries, sp->pMapEntries + sp->mapEntryCount);
                        pl->spec_data.assign((const uint8_t*)sp->pData, (const uint8_t*)sp->pData + sp->dataSize);
                    }
                    plain[i] = std::move(pl);
                } else {
                    VkShaderModuleCreateInfo mci{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
                    mci.codeSize = code[i]->size() * 4, mci.pCode = code[i]->data();
                    if (real_csm(d, &mci, nullptr, &own[i]) != VK_SUCCESS) own[i] = VK_NULL_HANDLE;
                    if (own[i]) v[i].stage.module = own[i], kind[i] &= ~2;
                }
            }
            if (!(kind[i] & 1)) continue;
            // (its own lane count in place of the one asked: first in the stage's chain, or put first)
            if (s && s->sType != VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO) {
                bool deeper = false;
                for (const VkBaseInStructure* t = s; t; t = t->pNext)
                    deeper |= t->sType == VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO;
                if (deeper) { kind[i] &= ~1; continue; }   // (not where it can be swapped: left as asked)
            }
            lanes[i] = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO};
            lanes[i].requiredSubgroupSize = 64;
            lanes[i].pNext = (void*)(s && s->sType == VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO ? s->pNext : s);
            v[i].stage.pNext = &lanes[i];
            v[i].stage.flags &= ~(VkPipelineShaderStageCreateFlags)VK_PIPELINE_SHADER_STAGE_CREATE_ALLOW_VARYING_SUBGROUP_SIZE_BIT;
            layers64++;
        }
    }
    // (the library's own pipelines, where it gives no cache, into the unrolled layers' cache: kept across runs and updates with
    // them, and warmed by the preparation's frame, fsr4_prepare_shaders)
    const VkResult r = real_ccp(d, cache ? cache : own_cache(), n, v.data(), a, p);
    for (VkShaderModule m : own)
        if (m) real_dsm(d, m, nullptr);
    if (r != VK_SUCCESS) return r;
    std::lock_guard lk(mu);
    for (uint32_t i = 0; i < n; i++) {
        if (kind[i] & 2) {   // (without a Plain, only when the library's own module could not be made: no fallback then)
            auto [t, added] = tail_pipes.try_emplace(p[i]);
            if (added) tail_count++;
            t->second = TailPipe{gen[i], std::move(plain[i])};
            t->second.twin_failed = !t->second.plain;
        }
        // (a layer with weight tables, from the library's own code: unrolled, its weights become constants in the code, which
        // is where the gain is. One without tables gains nothing: pass 3, 0.07 ms either way. Only one whose creation carried
        // nothing else: no specialization, no other structures)
        if (!(kind[i] & 1) || !(kind[i] & 2) || !unroll_on() || closing || ci[i].stage.pSpecializationInfo || lanes[i].pNext || ci[i].pNext) continue;
        // (copies of its layouts, made now while the library's are alive: identically defined, so compatible with its sets)
        LayoutCopy lc;
        VkPipelineLayout layout = VK_NULL_HANDLE;
        std::vector<VkDescriptorSetLayout> sets;
        if (!layout_copy_locked(ci[i].layout, &lc) || !make_layout(d, lc, &layout, &sets)) continue;
        pending.insert(p[i]);
        VkComputePipelineCreateInfo job = ci[i];
        job.pNext = nullptr, job.stage.pNext = nullptr;
        { std::lock_guard jl(jobs().mu); jobs().running++; }
        std::thread(build_unrolled, p[i], code[i], entry[i], job, layout, std::move(sets)).detach();   // (counted: fsr4_close)
    }
    static bool told_lanes = false;
    if (!told_lanes && layers64) told_lanes = true, logf("vk: AMD FSR 4: tuned: its network's layers run 64 lanes wide (%d so far)", layers64);
    return r;
}
VKAPI_ATTR void VKAPI_CALL destroy_pipeline(VkDevice d, VkPipeline pl, const VkAllocationCallbacks* a) {
    if (pl) {
        std::lock_guard lk(mu);
        auto b = better.find(pl);
        if (b != better.end()) real_dp(d, b->second, nullptr), better.erase(b), better_count--;
        if (pending.count(pl)) cancelled.insert(pl);
        auto t = tail_pipes.find(pl);
        if (t != tail_pipes.end()) {
            if (t->second.twin) real_dp(d, t->second.twin, nullptr);
            tail_pipes.erase(t), tail_count--;
        }
    }
    real_dp(d, pl, a);
}
VKAPI_ATTR void VKAPI_CALL cmd_bind_pipeline(VkCommandBuffer cb, VkPipelineBindPoint bp, VkPipeline pl) {
    if (bp == VK_PIPELINE_BIND_POINT_COMPUTE && (tail_count.load(std::memory_order_relaxed) || better_count.load(std::memory_order_relaxed))) {
        std::lock_guard lk(mu);
        if (bound.size() > 256) bound.clear();   // (command buffers of the renderer's, made and freed: only the last bind matters)
        auto b = better.find(pl);
        bound[cb] = {pl, b != better.end()};
        if (b != better.end()) pl = b->second;
    }
    real_bind(cb, bp, pl);
}
/// Before a dispatch of a pipeline that reads the tail: the tail written into its Big if due, while that Big lives and its
/// bindings take the tail in; else AMD's own pipeline bound in its place (made the first time). An unrolled one bound in
/// its place reads no tail
VKAPI_ATTR void VKAPI_CALL cmd_dispatch(VkCommandBuffer cb, uint32_t x, uint32_t y, uint32_t z) {
    if (tail_count.load(std::memory_order_relaxed)) {
        VkPipeline use = VK_NULL_HANDLE, original = VK_NULL_HANDLE;
        std::shared_ptr<const Plain> make;
        {
            std::lock_guard lk(mu);
            auto b = bound.find(cb);
            auto t = b == bound.end() ? tail_pipes.end() : tail_pipes.find(b->second.pipeline);
            if (t != tail_pipes.end() && !b->second.unrolled) {
                auto g = bigs.find(t->second.gen);
                if (g != bigs.end() && g->second.bound == 1) {
                    Big& big = g->second;
                    if (big.due) {   // (the tail, before its first reader)
                        const size_t bytes = big.tail.size() * 4;
                        for (size_t o = 0; o < bytes; o += 65536)
                            real_update(cb, big.buffer, big.size + o, std::min<size_t>(65536, bytes - o), (const char*)big.tail.data() + o);
                        VkMemoryBarrier mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER};
                        mb.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, mb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
                        real_barrier(cb, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &mb, 0, nullptr, 0, nullptr);
                        big.due = false;
                    }
                } else {
                    if (told.insert(t->second.gen).second)
                        logf("vk: AMD FSR 4: %s: AMD's own shaders in place of the tuned ones that read it, for this context",
                             g == bigs.end() ? "the storage buffer they were tuned for is gone"
                                             : g->second.bound == 0 ? "its storage buffer was not seen bound (a way of binding not checked here)"
                                                                    : "its storage buffer is bound without the tail");
                    if (t->second.twin) use = t->second.twin;
                    else if (!t->second.twin_failed) make = t->second.plain, original = b->second.pipeline;
                }
            }
        }
        if (make) {   // (made outside the lock: a compile)
            const VkPipeline made = make_plain(*make);
            std::lock_guard lk(mu);
            auto t = tail_pipes.find(original);
            if (t == tail_pipes.end() || t->second.twin) {
                if (made) real_dp(dev.device, made, nullptr);
                if (t != tail_pipes.end()) use = t->second.twin;
            } else if (made) {
                t->second.twin = use = made;
            } else {
                t->second.twin_failed = true;
                logf("vk: AMD FSR 4: AMD's own pipeline could not be made again: the tuned one stays");
            }
        }
        if (use) real_bind(cb, VK_PIPELINE_BIND_POINT_COMPUTE, use);
    }
    real_dispatch(cb, x, y, z);
}
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL device_proc(VkDevice d, const char* name) {
    PFN_vkVoidFunction f = vkGetDeviceProcAddr(d, name);
    if (!f || !name) return f;
    if (!strcmp(name, "vkCreateBuffer")) return real_cb = (PFN_vkCreateBuffer)f, (PFN_vkVoidFunction)&create_buffer;
    if (!strcmp(name, "vkDestroyBuffer")) return real_db = (PFN_vkDestroyBuffer)f, (PFN_vkVoidFunction)&destroy_buffer;
    if (!strcmp(name, "vkGetBufferDeviceAddress")) return real_bda = (PFN_vkGetBufferDeviceAddress)f, (PFN_vkVoidFunction)&buffer_address;
    if (!strcmp(name, "vkGetBufferDeviceAddressKHR"))
        return real_bda_khr = (PFN_vkGetBufferDeviceAddress)f, (PFN_vkVoidFunction)&buffer_address_khr;
    if (!strcmp(name, "vkUpdateDescriptorSets")) return real_uds = (PFN_vkUpdateDescriptorSets)f, (PFN_vkVoidFunction)&update_sets;
    if (!strcmp(name, "vkCmdPushDescriptorSetKHR")) return real_push = (PFN_vkCmdPushDescriptorSetKHR)f, (PFN_vkVoidFunction)&push_set;
    if (!strcmp(name, "vkCmdPushDescriptorSet")) return real_push14 = (PFN_vkCmdPushDescriptorSetKHR)f, (PFN_vkVoidFunction)&push_set14;
    if (!strcmp(name, "vkGetDescriptorEXT")) return real_gd = (PFN_vkGetDescriptorEXT)f, (PFN_vkVoidFunction)&get_descriptor;
    if (!strcmp(name, "vkCreateShaderModule")) return real_csm = (PFN_vkCreateShaderModule)f, (PFN_vkVoidFunction)&create_shader_module;
    if (!strcmp(name, "vkDestroyShaderModule")) return real_dsm = (PFN_vkDestroyShaderModule)f, (PFN_vkVoidFunction)&destroy_shader_module;
    if (!strcmp(name, "vkCreateComputePipelines"))
        return real_ccp = (PFN_vkCreateComputePipelines)f, (PFN_vkVoidFunction)&create_compute_pipelines;
    if (!strcmp(name, "vkCreateDescriptorSetLayout"))
        return real_cdsl = (PFN_vkCreateDescriptorSetLayout)f, (PFN_vkVoidFunction)&create_set_layout;
    if (!strcmp(name, "vkCreatePipelineLayout")) return real_cpl = (PFN_vkCreatePipelineLayout)f, (PFN_vkVoidFunction)&create_pipeline_layout;
    if (!strcmp(name, "vkDestroyPipeline")) return real_dp = (PFN_vkDestroyPipeline)f, (PFN_vkVoidFunction)&destroy_pipeline;
    if (!strcmp(name, "vkCmdBindPipeline")) return real_bind = (PFN_vkCmdBindPipeline)f, (PFN_vkVoidFunction)&cmd_bind_pipeline;
    if (!strcmp(name, "vkCmdDispatch")) return real_dispatch = (PFN_vkCmdDispatch)f, (PFN_vkVoidFunction)&cmd_dispatch;
    return f;
}
void prepare_device() {   // (what the hooks call, fetched before the library can call any of them: ((Triforce) a pass-through
                          // may come before the library asked for that function)
    real_cb = (PFN_vkCreateBuffer)vkGetDeviceProcAddr(dev.device, "vkCreateBuffer");
    real_db = (PFN_vkDestroyBuffer)vkGetDeviceProcAddr(dev.device, "vkDestroyBuffer");
    real_bda = (PFN_vkGetBufferDeviceAddress)vkGetDeviceProcAddr(dev.device, "vkGetBufferDeviceAddress");
    real_bda_khr = (PFN_vkGetBufferDeviceAddress)vkGetDeviceProcAddr(dev.device, "vkGetBufferDeviceAddressKHR");
    real_uds = (PFN_vkUpdateDescriptorSets)vkGetDeviceProcAddr(dev.device, "vkUpdateDescriptorSets");
    real_push = (PFN_vkCmdPushDescriptorSetKHR)vkGetDeviceProcAddr(dev.device, "vkCmdPushDescriptorSetKHR");
    real_push14 = (PFN_vkCmdPushDescriptorSetKHR)vkGetDeviceProcAddr(dev.device, "vkCmdPushDescriptorSet");
    real_gd = (PFN_vkGetDescriptorEXT)vkGetDeviceProcAddr(dev.device, "vkGetDescriptorEXT");
    real_bind = (PFN_vkCmdBindPipeline)vkGetDeviceProcAddr(dev.device, "vkCmdBindPipeline");
    real_dispatch = (PFN_vkCmdDispatch)vkGetDeviceProcAddr(dev.device, "vkCmdDispatch");
    real_update = (PFN_vkCmdUpdateBuffer)vkGetDeviceProcAddr(dev.device, "vkCmdUpdateBuffer");
    real_barrier = (PFN_vkCmdPipelineBarrier)vkGetDeviceProcAddr(dev.device, "vkCmdPipelineBarrier");
    real_dp = (PFN_vkDestroyPipeline)vkGetDeviceProcAddr(dev.device, "vkDestroyPipeline");
    real_csm = (PFN_vkCreateShaderModule)vkGetDeviceProcAddr(dev.device, "vkCreateShaderModule");
    real_dsm = (PFN_vkDestroyShaderModule)vkGetDeviceProcAddr(dev.device, "vkDestroyShaderModule");
    real_ccp = (PFN_vkCreateComputePipelines)vkGetDeviceProcAddr(dev.device, "vkCreateComputePipelines");
    real_cdsl = (PFN_vkCreateDescriptorSetLayout)vkGetDeviceProcAddr(dev.device, "vkCreateDescriptorSetLayout");
    real_cpl = (PFN_vkCreatePipelineLayout)vkGetDeviceProcAddr(dev.device, "vkCreatePipelineLayout");
}
/// The window closing (fsr4_close): no job starts from now, and the one building is waited for, 10 s at most (as the
/// shaders' preparation is, vk_main.cpp): a driver can take longer on one pipeline, and that job then touches nothing more
void close() {
    if (closing.exchange(true)) return;
    Jobs& j = jobs();
    std::unique_lock lk(j.mu);
    j.cv.notify_all();
    if (!j.running) return;
    logf("vk: AMD FSR 4: the window was closed while %d of its layers were waiting or being unrolled: stopping them", j.running);
    if (!j.cv.wait_for(lk, std::chrono::seconds(10), [&j] { return j.running == 0; }))
        logf("vk: AMD FSR 4: an unrolled layer still building after 10 s: closing anyway (it is left to the driver)");
}
}  // namespace tune

/// (Triforce) AMD's loader and its entry points, once (l.mu held): false when it is not there, which the log says. The
/// upscaler (load) and frame generation (fsr4fg) both start here
bool load_library(Library& l) {
    if (l.lib_tried) return l.lib_ok;
    l.lib_tried = true;
    std::string where;
    for (const std::string& dir : library_dirs()) {
        where += (where.empty() ? "" : ", ") + dir;
#ifdef _WIN32
        const std::string path = dir + "\\" + kLoader;
        if (GetFileAttributesA(path.c_str()) == INVALID_FILE_ATTRIBUTES) continue;
        // (the upscaler DLL the loader picks lies beside it: the loader's folder first in the search)
        l.lib = LoadLibraryExA(path.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        // (there but not loaded: a DLL it needs missing, a bad signature, or a relative RX_VK_FSR_DIR, which the search
        // flags refuse)
        if (!l.lib) logf("vk: AMD FSR 4: %s not loaded (Windows error %lu)", path.c_str(), (unsigned long)GetLastError());
#else
        const std::string path = dir + "/" + kLoader;
        if (access(path.c_str(), R_OK) != 0) continue;
        l.lib = (HMODULE)dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
        if (!l.lib) logf("vk: AMD FSR 4: %s not loaded: %s", path.c_str(), dlerror());
#endif
        if (l.lib) {
            logf("vk: AMD FSR 4: %s", path.c_str());
            l.dir = dir;
            break;
        }
    }
    if (!l.lib) {
        logf("vk: AMD FSR 4: no %s in %s (the readme says where AMD's files come from)", kLoader, where.c_str());
        return false;
    }
    l.create = (PfnFfxCreateContext)symbol("ffxCreateContext");
    l.destroy = (PfnFfxDestroyContext)symbol("ffxDestroyContext");
    l.configure = (PfnFfxConfigure)symbol("ffxConfigure");
    l.query = (PfnFfxQuery)symbol("ffxQuery");
    l.dispatch = (PfnFfxDispatch)symbol("ffxDispatch");
    if (!l.create || !l.destroy || !l.query || !l.dispatch) {
        logf("vk: AMD FSR 4: %s lacks the FSR API's entry points", kLoader);
        return false;
    }
    l.device_context = VkDeviceContext{dev.device, dev.physical, vkGetDeviceProcAddr};
    return l.lib_ok = true;
}

/// AMD's library on this device, once: false when FSR 4 cannot run here (g_why says why, the log too)
bool load() {
    Library& l = lib();
    std::lock_guard lk(l.mu);
    if (l.tried) return l.ok;
    l.tried = true;
    const auto no = [](FsrWhy why) {
        g_why = why;
        return false;
    };
    if (!load_library(l)) return no(FSR_NO_LIBRARY);
    if (tune::on()) tune::prepare_device();   // ((Triforce) the upscale contexts alone get the tuned functions: make_context)
#ifdef _WIN32
    // ((Triforce) the FSR 4 model row's hook, for the one upscaler library whose layout is known, before the loader loads that
    // name itself). On AMD GPUs alone, where the row is offered, or with the stand-in asked for (RX_VK_FSR4_STANDIN=1): another
    // maker's GPU loads and runs AMD's library as before, unhooked
    const bool probe = dev.props.vendorID == 0x1002 || env_switch("RX_VK_FSR4_STANDIN") == 1;
    const fsr4_models::KnownModule known = probe ? probe_models(l.dir) : fsr4_models::KnownModule{};
    const bool hooked = known.library && !known.scan.result.providers.empty() &&
                        fsr4_models::install(known.scan.base, known.scan.result, known.library);
    if (known.library && !hooked) logf("vk: AMD FSR 4: models: its providers were not hooked; AMD's own choice of model");
#endif
    // (the library lists every upscaler this device can run: the newest 4.x is taken explicitly, so an FSR 3.1 provider never
    // stands in silently)
    ffxQueryDescGetVersions versions{};
    versions.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
    versions.createDescType = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    versions.device = &l.device_context;
    uint64_t count = 0;
    versions.outputCount = &count;
    if (l.query(nullptr, &versions.header) != FFX_API_RETURN_OK || !count) {
        logf("vk: AMD FSR 4: AMD's library lists no upscaler for this GPU");
        return no(FSR_NO_MODEL);
    }
    std::vector<uint64_t> ids(count);
    std::vector<const char*> names(count);
    versions.versionIds = ids.data();
    versions.versionNames = names.data();
    if (l.query(nullptr, &versions.header) != FFX_API_RETURN_OK) {
        logf("vk: AMD FSR 4: the upscalers could not be listed");
        return no(FSR_NO_MODEL);
    }
#ifdef _WIN32
    // ((Triforce) the loader has loaded its upscaler by now: the hook answers only while that is the module that was checked)
    if (hooked && !fsr4_models::known_module_is_loaders(known))
        logf("vk: AMD FSR 4: models: the loader uses another copy of %s: the hook answers as AMD does", known.scan.name.c_str());
#endif
    std::string listed;
    unsigned best[3] = {0, 0, 0};
    const auto pick_newest = [&] {
        listed.clear();
        std::memset(best, 0, sizeof best);
        l.version_id = 0;
        for (uint64_t i = 0; i < count; i++) {
            const char* name = names[i] ? names[i] : "";
            listed += (listed.empty() ? "" : ", ") + std::string(name);
            unsigned v[3] = {0, 0, 0};
            sscanf(name, "%u.%u.%u", &v[0], &v[1], &v[2]);
            // (the first of equal versions: a Vulkan FSR 4 build lists its Auto, which picks the GPU's model, before INT8 and FP8)
            if (v[0] == 4 && (!l.version_id || v[1] > best[1] || (v[1] == best[1] && v[2] > best[2]))) {
                std::memcpy(best, v, sizeof best);
                l.version_id = ids[i];
            }
        }
    };
    pick_newest();
    // ((Triforce) RX_VK_FSR4_STANDIN=1: no FSR 4 for this GPU in AMD's own list (a GPU of another maker, or a Radeon AMD names
    // no model for). Where the Lite provider is hooked it stands in, and the list is asked again with it answering. Off
    // unless set: FSR 4 stays off on such a GPU, as before)
    static const bool standin_allowed = env_switch("RX_VK_FSR4_STANDIN") == 1;
    if (!l.version_id && standin_allowed && fsr4_models::hook_installed() && fsr4_models::has_model(fsr4_models::MODEL_LITE)) {
        const std::string amds = listed;
        fsr4_models::set_model(fsr4_models::SELECT_LITE);
        count = 0;
        versions.versionIds = nullptr, versions.versionNames = nullptr;
        if (l.query(nullptr, &versions.header) == FFX_API_RETURN_OK && count) {
            ids.assign(count, 0), names.assign(count, nullptr);
            versions.versionIds = ids.data(), versions.versionNames = names.data();
            if (l.query(nullptr, &versions.header) == FFX_API_RETURN_OK) pick_newest();
        }
        if (l.version_id) {
            g_standin = true;
            logf("vk: AMD FSR 4: AMD lists no FSR 4 model for this GPU (it has: %s): INT8 Lite stands in (RX_VK_FSR4_STANDIN=1)",
                 amds.c_str());
        } else {
            fsr4_models::set_model(fsr4_models::SELECT_AUTO);
            listed = amds;
        }
    }
    if (!l.version_id) {
        // ((Triforce, FSR4-7) on a Radeon RX 6000 or 7000 the driver decides: AMD's 26.10.1 or newer brings FSR 4 there)
        logf("vk: AMD FSR 4: no FSR 4 for this GPU and driver (AMD's library has: %s; FSR 4 needs a Radeon RX 6000, 7000 or "
             "9000 and AMD's driver 26.10.1 or newer)", listed.c_str());
        return no(FSR_NO_MODEL);
    }
    logf("vk: AMD FSR 4: upscalers %s; using %u.%u.%u", listed.c_str(), best[0], best[1], best[2]);
    // ((Triforce, FSR4-7) the menu's name for it: its major and minor, as NX2navi's bd7d526 shows it)
    snprintf(g_name[0], sizeof g_name[0], "AMD FSR %u.%u", best[0], best[1]);
    snprintf(g_name[1], sizeof g_name[1], "AMD FSR %u.%u Native AA", best[0], best[1]);
    g_named.store(true, std::memory_order_release);
    // ((Triforce) the FSR 4 model row: a model to choose where AMD's own pick runs, on an AMD GPU)
    g_lite_available = dev.props.vendorID == 0x1002 && !g_standin && fsr4_models::hook_installed() &&
                       fsr4_models::has_model(fsr4_models::MODEL_LITE);
    if (g_lite_available) logf("vk: AMD FSR 4: model: Lite is available (the FSR 4 model row; RX_VK_FSR4_MODEL=lite)");
    else if (g_standin) logf("vk: AMD FSR 4: model: INT8 Lite is the only one here; the FSR 4 model row is not shown");
    else if (fsr4_models::has_model(fsr4_models::MODEL_LITE)) logf("vk: AMD FSR 4: model: Lite is hooked, and offered on AMD GPUs only; Auto");
    l.ok = true;
    g_why = FSR_OK;
    return true;
}

/// (Triforce) RX_VK_FSR4_AUTO_EXPOSURE=0: an HDR context without FFX_UPSCALE_ENABLE_AUTO_EXPOSURE (FSR takes the colour's
/// exposure as 1), to compare with the default where the colour is the tone mapped picture (FSR4-3)
bool hdr_auto_exposure() {
    static const bool on = env_switch("RX_VK_FSR4_AUTO_EXPOSURE") != 0;
    return on;
}

/// A context for outputs of ow x oh. drs: any render size up to the output's (the game's dynamic resolution); else the
/// render size rw x rh alone, as AMD's sample makes them ((Triforce, FSR4-9): NX2navi's 7e938ec saw AMD's driver fail in the
/// dispatch on an RX 7900 XT when the render size changed under one context, and moved to one context a render size)
/// ((Triforce) want: the FSR 4 model row's; Lite where it cannot be had, or failed this run, is Auto)
std::shared_ptr<Context> make_context(uint32_t rw, uint32_t rh, uint32_t ow, uint32_t oh, bool drs, bool hdr, Fsr4Model want) {
    Library& l = lib();
    auto c = std::make_shared<Context>();
    c->model = want;
    Fsr4Model effective = want;
    if (effective == FSR4_MODEL_LITE && !g_lite_available.load(std::memory_order_relaxed)) {
        static std::atomic<bool> told{false};
        if (!told.exchange(true)) logf("vk: AMD FSR 4: Lite was asked for but no Lite provider is hooked; using Auto");
        effective = FSR4_MODEL_AUTO;
    }
    if (effective == FSR4_MODEL_LITE && g_lite_failed.load(std::memory_order_relaxed)) {
        static std::atomic<bool> told{false};
        if (!told.exchange(true)) logf("vk: AMD FSR 4: Lite failed earlier in this run; using Auto");
        effective = FSR4_MODEL_AUTO;
    }
    const bool standin = g_standin.load(std::memory_order_relaxed);
    if (standin) effective = FSR4_MODEL_AUTO;   // (nothing to choose: the row's value changes nothing, and no retry as Auto)
    c->effective = effective;
    // (Lite on a card whose own pick is another model: AMD's shaders, the tune's rewrites are for the full networks)
    const bool lite = effective == FSR4_MODEL_LITE || standin;
    const bool suppress = lite && fsr4_models::native_model() != fsr4_models::MODEL_LITE;
    tune::suppress(suppress);
    fsr4_models::set_model(lite ? fsr4_models::SELECT_LITE : fsr4_models::SELECT_AUTO);
    c->tuned = tune::on() && !suppress;
    c->backend.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_VK;
    c->backend.deviceContext = l.device_context;
    // ((Triforce) AMD's passes tuned (tune, above): the device functions handed to the upscale context are ours where it makes
    // buffers, shaders and pipelines and records its dispatches. Frame generation (fsr4fg) keeps the driver's own, as before)
    if (tune::on()) c->backend.deviceContext.vkDeviceProcAddr = &tune::device_proc;
    c->version.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION;
    c->version.versionId = l.version_id;
    c->backend.header.pNext = &c->version.header;
    c->built.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE_VERSION;
    c->built.version = FFX_UPSCALER_VERSION;
    c->version.header.pNext = &c->built.header;
#ifndef _WIN32
    // (linux) fsr4-vk looks for the SDK's older backend description, not ffxCreateBackendVKDesc: without it, it finds no device
    // and creation returns FFX_API_RETURN_ERROR_PARAMETER. Both stay chained
    c->legacy_backend.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_VK_DEPRECATED;
    c->legacy_backend.vkDevice = l.device_context.vkDevice;
    c->legacy_backend.vkPhysicalDevice = l.device_context.vkPhysicalDevice;
    c->legacy_backend.vkDeviceProcAddr = c->backend.deviceContext.vkDeviceProcAddr;
    c->built.header.pNext = &c->legacy_backend.header;
#endif
    c->upscale.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    c->upscale.header.pNext = &c->backend.header;
    // (the chain's colour is tonemapped and square-root encoded already: LDR, perceptual, no auto exposure; depth not
    // inverted)
    c->upscale.flags = FFX_UPSCALE_ENABLE_NON_LINEAR_COLORSPACE;
    // (hdr, linear HDR colour: the chain before the game's bloom and tone mapping, the scene's light before the game's
    // exposure, so FSR finds the exposure itself; or (Triforce, FSR4-3) an RGBA16F picture's, RenoDX's HDR Native)
    if (hdr) c->upscale.flags = FFX_UPSCALE_ENABLE_HIGH_DYNAMIC_RANGE | (hdr_auto_exposure() ? FFX_UPSCALE_ENABLE_AUTO_EXPOSURE : 0);
    if (drs) c->upscale.flags |= FFX_UPSCALE_ENABLE_DYNAMIC_RESOLUTION;
    c->upscale.maxRenderSize = drs ? FfxApiDimensions2D{ow, oh} : FfxApiDimensions2D{rw, rh};
    c->upscale.maxUpscaleSize = {ow, oh};
    c->upscale.fpMessage = &on_message;
    const auto t0 = std::chrono::steady_clock::now();
    const auto create = [&](ffxContext* out) { return l.create(out, &c->upscale.header, nullptr); };
    const auto destroy = [&](ffxContext* out) { l.destroy(out, nullptr); };
    ffxReturnCode_t r = fsr4_models::create_attempt(c->context, (ffxReturnCode_t)FFX_API_RETURN_OK, create, destroy);
    if ((r != FFX_API_RETURN_OK || !c->context) && effective == FSR4_MODEL_LITE && !g_lite_failed.exchange(true)) {
        logf("vk: AMD FSR 4: AMD's library refused the Lite model; using Auto");
        effective = c->effective = FSR4_MODEL_AUTO;
        tune::suppress(false);
        fsr4_models::set_model(fsr4_models::SELECT_AUTO);
        c->tuned = tune::on();
        r = fsr4_models::create_attempt(c->context, (ffxReturnCode_t)FFX_API_RETURN_OK, create, destroy);
    }
    const double made_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    if (r != FFX_API_RETURN_OK || !c->context) {
        logf("vk: AMD FSR 4: its upscaler was not made (%d) for %ux%u -> %ux%u%s", (int)r, rw, rh, ow, oh,
             drs ? " (any render size)" : "");
        c->context = nullptr;
        return nullptr;
    }
    c->width = ow, c->height = oh, c->render_w = drs ? ow : rw, c->render_h = drs ? oh : rh, c->drs = drs, c->hdr = hdr;
    FfxApiEffectMemoryUsage usage{};
    ffxQueryDescUpscaleGetGPUMemoryUsage mem{};
    mem.header.type = FFX_API_QUERY_DESC_TYPE_UPSCALE_GPU_MEMORY_USAGE;
    mem.gpuMemoryUsageUpscaler = &usage;
    if (l.query(&c->context, &mem.header) == FFX_API_RETURN_OK) c->memory = usage.totalUsageInBytes;
    ffxQueryGetProviderVersion provider{};
    provider.header.type = FFX_API_QUERY_DESC_TYPE_GET_PROVIDER_VERSION;
    const bool known = l.query(&c->context, &provider.header) == FFX_API_RETURN_OK && provider.versionName;
    if (fsr4_models::hook_installed() || effective == FSR4_MODEL_LITE || standin)   // ((Triforce) the FSR 4 model row's)
        logf("vk: AMD FSR 4: model: %s%s",
             standin ? "Lite (INT8, standing in: AMD lists no FSR 4 model for this GPU)"
             : effective == FSR4_MODEL_LITE ? (suppress ? "Lite (INT8, forced)" : "Lite (INT8, AMD's own for this GPU)") : "Auto (AMD's)",
             c->tuned ? ", tuned" : tune::on() ? ", AMD's shaders" : "");
    logf("vk: AMD FSR 4: FSR %s made for %s%ux%u -> %ux%u, %s colour%s (frame %llu, %.1f ms of CPU; its own %llu MB)",
         known ? provider.versionName : "?", drs ? "render sizes up to " : "", c->render_w, c->render_h, ow, oh,
         hdr ? "HDR" : "LDR", hdr && !hdr_auto_exposure() ? " without auto exposure" : "", (unsigned long long)texture_frame_no(),
         made_ms, (unsigned long long)(c->memory >> 20));
    // ((Triforce, FSR4-8) the provider asked for the version it runs: anything but a 4.x means the loader gave another upscaler
    // in FSR 4's place, which is never shown under its name (NX2navi's vk_ffx4.cpp does the same). The context goes with c)
    if (known && atoi(provider.versionName) < 4) {
        logf("vk: AMD FSR 4: the context runs FSR %s, not FSR 4: FSR 4 off for this run", provider.versionName);
        {
            std::lock_guard lk(l.mu);
            l.ok = false;
        }
        g_why = FSR_NO_MODEL;
        return nullptr;
    }
    return c;
}

FfxApiResource resource(const TemporalImage& im, VkImageUsageFlags usage, uint32_t state) {
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.imageType = VK_IMAGE_TYPE_2D, ci.format = im.format, ci.extent = {im.width, im.height, 1};
    ci.mipLevels = 1, ci.arrayLayers = 1, ci.samples = VK_SAMPLE_COUNT_1_BIT, ci.tiling = VK_IMAGE_TILING_OPTIMAL;
    ci.usage = usage, ci.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    return ffxApiGetResourceVK((void*)im.image, ffxApiGetImageResourceDescriptionVK(im.image, ci, 0), state);
}

VkImageMemoryBarrier2 barrier(VkImage image, VkAccessFlags2 src, VkAccessFlags2 dst, VkImageLayout from, VkImageLayout to) {
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
    b.srcStageMask = b.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    b.srcAccessMask = src, b.dstAccessMask = dst, b.oldLayout = from, b.newLayout = to;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image, b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    return b;
}
void barriers(VkCommandBuffer cmd, const VkImageMemoryBarrier2* b, uint32_t n) {
    VkDependencyInfo di{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    di.imageMemoryBarrierCount = n, di.pImageMemoryBarriers = b;
    vkCmdPipelineBarrier2(cmd, &di);
}

#ifndef _WIN32
/// (linux) a Vulkan FSR 4 build takes no frame without an exposure, and the chain's colour is tonemapped already: a 1x1 R32F of 1
bool unit_exposure(VkCommandBuffer cmd, TemporalImage& out) {
    static VkImage image = VK_NULL_HANDLE;
    static VmaAllocation allocation{};
    const bool made = image != VK_NULL_HANDLE;
    if (!made) {
        VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
        ci.imageType = VK_IMAGE_TYPE_2D, ci.format = VK_FORMAT_R32_SFLOAT, ci.extent = {1, 1, 1}, ci.mipLevels = 1, ci.arrayLayers = 1;
        ci.samples = VK_SAMPLE_COUNT_1_BIT, ci.tiling = VK_IMAGE_TILING_OPTIMAL;
        ci.usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        if (!create_image(ci, image, allocation)) return image = VK_NULL_HANDLE, false;
    }
    out = TemporalImage{image, VK_NULL_HANDLE, VK_FORMAT_R32_SFLOAT, 1, 1};
    if (!made) {
        const VkImageMemoryBarrier2 to_clear = barrier(image, 0, VK_ACCESS_2_TRANSFER_WRITE_BIT, VK_IMAGE_LAYOUT_UNDEFINED,
                                                       VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        barriers(cmd, &to_clear, 1);
        const VkClearColorValue one{{1.0f, 0.0f, 0.0f, 0.0f}};
        const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        vkCmdClearColorImage(cmd, image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &one, 1, &range);
        const VkImageMemoryBarrier2 to_read = barrier(image, VK_ACCESS_2_TRANSFER_WRITE_BIT, VK_ACCESS_2_SHADER_READ_BIT,
                                                      VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
        barriers(cmd, &to_read, 1);
    }
    return true;
}
#endif

// ---- the engine (vk_temporal.h TemporalEngine) ----

bool start() { return load(); }

void release() {
    State& s = st();
    if (!s.context) return;
    std::shared_ptr<Context> old = std::move(s.context);
    temporal_later([old] {});   // (destroyed with the last copy, a few frames on: recorded dispatches may still use it)
    s.context.reset();
}

int prepare(VkCommandBuffer, uint32_t rw, uint32_t rh, uint32_t ow, uint32_t oh, bool hdr,
            uint32_t* in_w, uint32_t* in_h, const char** why) {
    State& s = st();
    int made = 1;
    // ((Triforce, FSR4-9) a fixed share has a context of its own size; the first time the render size changes under an output
    // (the game's dynamic resolution: Auto), one context for any size up to the output's from then on. RX_VK_FSR4_DRS=1:
    // that one from the start, as before)
    static const bool drs_env = env_switch("RX_VK_FSR4_DRS") > 0;
    const Context* const c = s.context.get();
    const temporal_rules::ContextPlan plan =
        c ? temporal_rules::plan_context(true, c->width, c->height, c->render_w, c->render_h, c->drs, c->hdr, rw, rh, ow, oh,
                                         hdr, s.dynamic, drs_env)
          : temporal_rules::plan_context(false, 0, 0, 0, 0, false, false, rw, rh, ow, oh, hdr, s.dynamic, drs_env);
    if (plan.went_dynamic)
        logf("vk: AMD FSR 4: the render size went from %ux%u to %ux%u: one context for every render size from now on (the "
             "game's dynamic resolution)", c->render_w, c->render_h, rw, rh);
    s.dynamic = plan.dynamic;
    const Fsr4Model want = fsr4_model();   // ((Triforce) the FSR 4 model row)
    if (plan.remake) {
        release();
        s.context = make_context(rw, rh, ow, oh, plan.drs, hdr, want);
        if (!s.context) return *why = "its upscaler was not made", -1;
        s.in_w = s.in_h = 0;
        made = 2;
    } else if (s.context->model != want) {
        // ((Triforce) the model changed, nothing else: the new context made before the old one goes, which stays when the
        // new one cannot be had (or would be the same Auto), the change then not tried again every frame)
        Context& old = *s.context;
        auto replacement = make_context(old.render_w, old.render_h, old.width, old.height, old.drs, old.hdr, want);
        if (!replacement || (want == FSR4_MODEL_LITE && replacement->effective == FSR4_MODEL_AUTO && old.effective == FSR4_MODEL_AUTO)) {
            old.model = want;
            logf("vk: AMD FSR 4: the model change made nothing new; the context there stays");
        } else {
            release();
            s.context = std::move(replacement);
            s.in_w = s.in_h = 0;
            made = 2;
        }
    }
    // (the inputs as large as the largest render size this context has had, never past the output: a fixed share keeps
    // images of its own size, and the game's dynamic resolution only makes them again when it goes past them)
    s.in_w = std::min(std::max(s.in_w, rw), ow), s.in_h = std::min(std::max(s.in_h, rh), oh);
    *in_w = s.in_w, *in_h = s.in_h;
    return made;
}

bool evaluate(VkCommandBuffer cmd, const TemporalFrame& f) {
    State& s = st();
    Library& l = lib();
#ifndef _WIN32
    TemporalImage exposure{};
    if (!unit_exposure(cmd, exposure)) return false;
#endif
    const auto now = std::chrono::steady_clock::now();
    // ((Triforce, FSR4-10) under 100 ms, else a 60th, as the frame generation's below: a single long hitch, or the first
    // frame, is no rate for FSR's history to follow)
    const float frame_ms = temporal_rules::frame_ms(!s.evals, std::chrono::duration<float, std::milli>(now - s.last).count());
    s.last = now;

    constexpr VkImageLayout G = VK_IMAGE_LAYOUT_GENERAL, R = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    constexpr VkAccessFlags2 any = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT;
    const VkImageMemoryBarrier2 in[4] = {barrier(f.color.image, VK_ACCESS_2_MEMORY_WRITE_BIT, VK_ACCESS_2_SHADER_READ_BIT, G, R),
                                         barrier(f.depth.image, VK_ACCESS_2_MEMORY_WRITE_BIT, VK_ACCESS_2_SHADER_READ_BIT, G, R),
                                         barrier(f.motion.image, VK_ACCESS_2_MEMORY_WRITE_BIT, VK_ACCESS_2_SHADER_READ_BIT, G, R),
                                         barrier(f.output.image, any, any, G, G)};
    barriers(cmd, in, 4);

    ffxDispatchDescUpscale d{};
    d.header.type = FFX_API_DISPATCH_DESC_TYPE_UPSCALE;
    d.commandList = cmd;
    d.color = resource(f.color, VK_IMAGE_USAGE_SAMPLED_BIT, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    d.depth = resource(f.depth, VK_IMAGE_USAGE_SAMPLED_BIT, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    d.motionVectors = resource(f.motion, VK_IMAGE_USAGE_SAMPLED_BIT, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    d.output = resource(f.output, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
#ifndef _WIN32
    d.exposure = resource(exposure, VK_IMAGE_USAGE_SAMPLED_BIT, FFX_API_RESOURCE_STATE_COMPUTE_READ);
#endif
    d.jitterOffset = {f.jitter[0], f.jitter[1]};   // (render pixels, as the projection was offset: the same as DLSS's)
    d.motionVectorScale = {1.0f, 1.0f};             // (render pixels already, towards the frame before)
    d.renderSize = {f.render_w, f.render_h};
    d.upscaleSize = {f.output.width, f.output.height};
    // ((Triforce, S1) the Sharpness row as FSR 4's own sharpening, in AMD's meaning (0 none, 1 the most), on the 3D before
    // the HUD: the window pass then sharpens nothing (vk_temporal.h temporal_sharpens_3d). It was off here, the row sharpening
    // the finished picture at the window, the HUD and text with it, and FSR 4's picture stayed as soft as it came)
    const float sharpness = temporal_sharpness();
    d.enableSharpening = sharpness > 0.0f;
    d.sharpness = sharpness;
    if (sharpness != s.told_sharpness) {
        s.told_sharpness = sharpness;
        if (sharpness > 0.0f) logf("vk: AMD FSR 4: its own sharpening at %.2f, before the HUD", sharpness);
        else logf("vk: AMD FSR 4: its own sharpening off");
    }
    d.frameTimeDelta = frame_ms;
    d.preExposure = 1.0f;
    d.reset = f.reset;
    d.cameraNear = f.near_z, d.cameraFar = f.far_z, d.cameraFovAngleVertical = f.fov_y;
    d.viewSpaceToMetersFactor = 1.0f;
    d.flags = s.context->hdr ? 0 : FFX_UPSCALE_FLAG_NON_LINEAR_COLOR_SRGB;   // (HDR: linear light as it is)
    ffxReturnCode_t r;
    {
        GprofSpan timed(cmd, "fsr4 ffxDispatch (AMD's passes)");   // (RX_VK_PASS_TIMING=1: AMD's own GPU time, named)
        ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (ffxDispatch records into cmd itself: what this thread recorded through vk_work.h reaches cmd first)
        r = l.dispatch(&s.context->context, &d.header);
        note_work(cmd);   // (AMD's dispatches: full_barrier must not take the next barrier for a repeat of the one before them)
    }

    const VkImageMemoryBarrier2 out[4] = {barrier(f.color.image, VK_ACCESS_2_SHADER_READ_BIT, any, R, G),
                                          barrier(f.depth.image, VK_ACCESS_2_SHADER_READ_BIT, any, R, G),
                                          barrier(f.motion.image, VK_ACCESS_2_SHADER_READ_BIT, any, R, G),
                                          barrier(f.output.image, any, any, G, G)};
    barriers(cmd, out, 4);
    if (r != FFX_API_RETURN_OK) {
        logf("vk: AMD FSR 4: its dispatch failed (%d)", (int)r);
        if (s.context->effective == FSR4_MODEL_LITE && !g_lite_failed.exchange(true)) {
            logf("vk: AMD FSR 4: the Lite model's dispatch failed; Auto from the next context");
            release();   // ((Triforce) the next prepare makes an Auto context: fsr4_model's Lite is taken as Auto from now)
        }
        return false;
    }
    // (the first evaluation, and the first resets: a camera cut each)
    if (s.evals++ == 0 || (f.reset && s.told_resets < 40))
        s.told_resets++, logf("vk: AMD FSR 4: %ux%u -> %ux%u, jitter %+.3f %+.3f px%s", f.render_w, f.render_h, f.output.width,
                              f.output.height, f.jitter[0], f.jitter[1], f.reset ? " (history reset)" : "");
    return true;
}

uint64_t memory() {
    State& s = st();
    return s.context ? s.context->memory : 0;
}

/// (fsr4_prepare_shaders) One frame of FSR 4 on cleared images, for the preparation: the library makes its pipelines (and the
/// tune its unrolled layers) before the game has a scene. Its images and command pool go with it, once the GPU is done
struct PrepareFrame {
    VkCommandPool pool = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    VmaAllocation allocations[4]{};
    TemporalFrame frame;

    ~PrepareFrame() {
        if (fence) vkDestroyFence(dev.device, fence, nullptr);
        if (pool) vkDestroyCommandPool(dev.device, pool, nullptr);
        TemporalImage* images[] = {&frame.color, &frame.depth, &frame.motion, &frame.output};
        for (size_t i = 0; i < 4; i++)
            if (images[i]->image) destroy_image(images[i]->image, allocations[i]);
    }

    bool record(VkCommandBuffer cmd, uint32_t ow, uint32_t oh) {
        TemporalImage* images[] = {&frame.color, &frame.depth, &frame.motion, &frame.output};
        constexpr VkFormat formats[] = {VK_FORMAT_R16G16B16A16_SFLOAT, VK_FORMAT_R32_SFLOAT, VK_FORMAT_R16G16_SFLOAT,
                                        VK_FORMAT_R16G16B16A16_SFLOAT};
        for (size_t i = 0; i < 4; i++) {
            TemporalImage& im = *images[i];
            const bool output = i == 3;
            VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
            ci.imageType = VK_IMAGE_TYPE_2D, ci.format = formats[i];
            ci.extent = {output ? ow : frame.render_w, output ? oh : frame.render_h, 1};
            ci.mipLevels = ci.arrayLayers = 1;
            ci.samples = VK_SAMPLE_COUNT_1_BIT, ci.tiling = VK_IMAGE_TILING_OPTIMAL;
            ci.usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | (output ? VK_IMAGE_USAGE_STORAGE_BIT : 0u);
            if (!create_image(ci, im.image, allocations[i])) return false;
            im.format = ci.format, im.width = ci.extent.width, im.height = ci.extent.height;
            const VkImageMemoryBarrier2 to_clear = barrier(im.image, 0, VK_ACCESS_2_TRANSFER_WRITE_BIT, VK_IMAGE_LAYOUT_UNDEFINED,
                                                           VK_IMAGE_LAYOUT_GENERAL);
            barriers(cmd, &to_clear, 1);
            const VkClearColorValue clear{{i == 1 ? 1.0f : 0.0f, 0.0f, 0.0f, 0.0f}};
            const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
            vkCmdClearColorImage(cmd, im.image, VK_IMAGE_LAYOUT_GENERAL, &clear, 1, &range);
        }
        return true;
    }

    /// Recorded, submitted (under the queue's lock, as every one-off submit) and waited for
    bool run(uint32_t ow, uint32_t oh) {
        frame.render_w = std::max(1u, ow * 2 / 3), frame.render_h = std::max(1u, oh * 2 / 3);   // (any size: the same pipelines)
        frame.reset = true;
        VkCommandPoolCreateInfo pi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
        pi.queueFamilyIndex = dev.queue_family;
        if (vkCreateCommandPool(dev.device, &pi, nullptr, &pool) != VK_SUCCESS) return false;
        VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
        ai.commandPool = pool, ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, ai.commandBufferCount = 1;
        VkCommandBuffer cmd = VK_NULL_HANDLE;
        if (vkAllocateCommandBuffers(dev.device, &ai, &cmd) != VK_SUCCESS) return false;
        VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
        if (vkCreateFence(dev.device, &fi, nullptr, &fence) != VK_SUCCESS) return false;
        VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
        bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        if (vkBeginCommandBuffer(cmd, &bi) != VK_SUCCESS) return false;
        const bool recorded = record(cmd, ow, oh) && evaluate(cmd, frame);
        if (vkEndCommandBuffer(cmd) != VK_SUCCESS || !recorded) return false;
        VkCommandBufferSubmitInfo cb{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO};
        cb.commandBuffer = cmd;
        VkSubmitInfo2 si{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};
        si.commandBufferInfoCount = 1, si.pCommandBufferInfos = &cb;
        bool sent;
        {
            std::lock_guard qk(dev.present_mu);   // (the queue's lock)
            queue_flush_locked();
            sent = vkQueueSubmit2(dev.queue, 1, &si, fence) == VK_SUCCESS;
        }
        // (the pool, the images and the context are let go only once the GPU is done with them)
        if (sent && vkWaitForFences(dev.device, 1, &fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS) device_lost("AMD FSR 4's preparation frame");
        return sent;
    }
};

const TemporalEngine kEngine{"AMD FSR 4", "FSR", start, prepare, evaluate, release, memory};

}  // namespace

bool fsr4_built() { return true; }
const TemporalEngine* fsr4_engine() { return &kEngine; }

void fsr4_probe() {
    if (fsr4_why() != FSR_OK || g_why.load(std::memory_order_relaxed) >= 0 || !dev.device) return;
    load();
}

/// (Triforce) In a start that only prepares (Setup's, HOOKSHOT_PREPARE_ONLY), with the tune on (RX_VK_FSR4_TUNE=1): AMD's
/// pipelines made, and its unrolled layers built, now, into their own cache (kOwnCacheFile), rather than at the first FSR 4
/// frame in play, about a minute each cold. A context for the preparation's output and one frame on cleared images; the
/// unrolled layers' jobs waited for, then the file written. SDR, and HDR too when the HDR row is at the game's own (Native)
void fsr4_prepare_shaders() {
    if (!tune::on() || !load()) return;
    const uint32_t ow = dev.swap_extent.width, oh = dev.swap_extent.height;
    if (!ow || !oh) return;
    const bool native_hdr = opts.hdr == 2;
    for (int mode = 0; mode <= (int)native_hdr; mode++) {
        const char* label = mode ? "HDR" : "SDR";
        logf("vk: AMD FSR 4: its %s pipelines made before the game (%ux%u)", label, ow, oh);
        State& s = st();
        bool ok = false;
        {
            PrepareFrame work;
            // (the model the player picked, as prepare asks for each frame: its pipelines are the ones the game will use)
            s.context = make_context(std::max(1u, ow * 2 / 3), std::max(1u, oh * 2 / 3), ow, oh, false, mode != 0, fsr4_model());
            ok = s.context && work.run(ow, oh);
        }
        // (the start ends after the preparation: the layers' jobs this frame started are waited for and their file written)
        tune::Jobs& jobs = tune::jobs();
        {
            std::unique_lock lk(jobs.mu);
            jobs.cv.wait(lk, [&jobs] { return jobs.running == 0; });
        }
        const int unrolled = tune::better_count.load();
        s.context.reset();
        s.evals = 0;
        const bool saved = tune::save_own_cache();
        if (ok && saved) logf("vk: AMD FSR 4: its %s pipelines made (%d unrolled layers ready)", label, unrolled);
        else logf("vk: AMD FSR 4: its %s pipelines could not be %s", label, ok ? "saved" : "made (no frame)");
    }
}

void fsr4_close() { tune::close(); }

bool fsr4_wants_descriptor_buffer() {
#ifdef _WIN32
    return false;
#else
    if (fsr4_why() == FSR_ENV_OFF) return false;
    for (const std::string& dir : library_dirs())
        if (access((dir + "/" + kLoader).c_str(), R_OK) == 0) return true;
    return false;
#endif
}

// ---- (Triforce) AMD FSR 4's frame generation (vk_fsr4.h fsr4fg) ----
//
// AMD's frame generation context, of the same FidelityFX SDK 2.4 as the upscaler. Its loader picks the provider for the
// card: the machine-learned FSR Frame Generation 4.x on the Radeon cards AMD lists it for (RX 9000), FSR Frame Generation
// 3.1.x on every other. ((Triforce, FG-1) Both are taken now, 4.x first where listed (framegen_rows.h pick_version), and the
// row names the version: "AMD FSR (3.1.6)" on an RX 7900 XT. Before, 3.1.x was refused and the row never offered AMD's
// frame generation on RX 6000 and 7000.)
//
// How it is driven. AMD's API has two ways to get the made frame on screen. One is a swapchain of AMD's in the window's
// place (ffxCreateContextDescFrameGenerationSwapChainVK), which presents and paces the frames on queues and threads of its
// own; NX2navi runs AMD's library that way (its runtime/vk_fg4.cpp). The other is to ask the context for the frame:
// ffxConfigure with FFX_FRAMEGENERATION_FLAG_NO_SWAPCHAIN_CONTEXT_NOTIFY ("the context should only run frame interpolation
// and not modify the swapchain", ffx_framegeneration.h), the preparation dispatch with the scene's depth and motion, then
// ffxDispatchDescFrameGeneration with the presented picture and an image of ours for the made frame: the description AMD's
// swapchain itself fills in for its callback. That is the way taken here, because this renderer already presents made
// frames itself: vk_framegen.cpp's display thread shows them between the game's, paced on its own line, through the one
// present path (the window scaling, HDR, the overlays). So nothing of the swapchain, the queues or the presents changes
// with this choice, AMD's library has no thread of its own to stop at the exit, and a present it does not take gets the
// renderer's own made frame.
//
// ((Triforce, FG-3) Why the swapchain-less way is kept. AMD's header describes the flag as a supported mode, "the context
// should only run frame interpolation and not modify the swapchain"; the generation's description
// (ffxDispatchDescFrameGeneration: a command list, the present colour, up to four outputs, the frame id) is a public
// dispatch type, and the very one AMD's swapchain hands its frameGenerationCallback, whose default in AMD's samples is
// ffxDispatch of it on the same context. Taking AMD's swapchain instead (NX2navi's runtime/vk_fg4.cpp) would put AMD's present
// and acquire queues and threads in place of this renderer's window, HDR, scaling, overlays and display thread, with the queue
// family work NX2navi 293731d needed on AMD's driver: a far larger change, for the same three calls. Not yet seen on a card:
// every way the library refuses is logged (fail, and the first frame's "the first made frame" line), and a refusal leaves
// the renderer's own interpolation.)
//
// The HUD ((Triforce, FG-2)): the picture given is the game's finished one, HUD included, and with it, as
// ffxConfigureDescFrameGeneration::HUDLessColor, the same picture without the HUD: the gameplay upscale's output before the
// HUD is drawn into it, encoded as the game's last pass encodes it (vk_framegen.cpp hudless_for). AMD's library moves the
// scene by that one and keeps what differs between the two, the HUD, where the game drew it. No frame is made without it
// (GAME: the game's frame alone, NX2navi 5bdf583's rule): FSR 3.1's frame interpolation here (vk_fsr3fi.cpp), without
// one, moved the HUD with the scene (#1635). Nor in HDR Native, whose picture without the HUD the game alone could encode,
// nor in a run with RenoDX's RGBA16F scene: those hold for every present (held()), and there the renderer's own
// interpolation makes the one frame, as at 2x, as a saved 9 ran before AMD's FSR 3.1 frame generation was offered.
#ifdef _WIN32
namespace fsr4fg {
namespace {
namespace fgr = framegen_rows;

constexpr const char* kFgFile = "amd_fidelityfx_framegeneration_vk.dll";
// (the images' uses, for AMD's descriptions of them: the made frame's image is ours, written as a storage image or as a
// colour attachment, whichever AMD's last pass does; the picture is vk_framegen.cpp's copy of the frame, the depth and the
// motion vk_fsr3_inputs.cpp's)
constexpr VkImageUsageFlags kOutUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT |
                                        VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
constexpr VkImageUsageFlags kColorUsage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
constexpr VkImageUsageFlags kInUsage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;

struct Fg {
    std::mutex mu;   // (every call into AMD's library for frame generation, and all of this)
    uint64_t version_id = 0;
    char version[24] = "";
    ffxContext context = nullptr;
    // (what the context was made from: the API asks that it stays until the context is destroyed)
    ffxCreateContextDescFrameGeneration desc{};
    ffxCreateContextDescFrameGenerationHudless hudless{};   // ((Triforce, FG-2) the picture without the HUD's format)
    ffxCreateContextDescFrameGenerationVersion api{};
    ffxCreateBackendVKDesc backend{};
    ffxOverrideVersion pin{};
    fgr::ContextKey key{};
    VkImage out = VK_NULL_HANDLE;   // (the made frame: R8G8B8A8_UNORM at the picture's size, GENERAL)
    VmaAllocation out_memory{};
    bool out_new = false;           // (made, and not in GENERAL yet)
    bool made = false;              // (the last generate answered MADE)
    uint64_t memory = 0;            // (what AMD's library says the context holds)
    uint64_t frame_id = 0;          // (AMD's: one more for each frame handed over)
    uint64_t sequence = 0;          // (Inputs::sequence of the last frame handed over)
    fgr::Pose pose{};               // (its camera, for the cuts)
    bool have_pose = false;
    uint64_t presents = 0, used_at = 0;   // (present_tick's count, and its value at the last frame handed over)
    uint64_t n_made = 0, n_skipped = 0, n_cuts = 0;
    // ((Triforce) each way a present is refused said once: no depth and motion, no picture without the HUD, HDR Native)
    bool told_bare = false, told_held[fgr::HELD_COUNT] = {};
    uint64_t n_held[fgr::HELD_COUNT] = {};
};
Fg& fg() {
    static Fg& f = *new Fg;   // (never destroyed: lib()'s note)
    return f;
}
std::atomic<int> g_fg_why{-1};          // (-1: AMD's library not asked yet; else a framegen_rows.h Why)
std::atomic<bool> g_fg_failed{false};   // (it failed in this run: off until the next start)
std::atomic<bool> g_fg_exiting{false};  // (HOS_OPT_EXITING: nothing of AMD's is called any more)
std::atomic<bool> g_fg_live{false};     // (a context exists: present_tick has something to look after)

int fg_env() {   // (RX_VK_FSR4_FG: 0 never; 4 FSR 4's alone, as before (FG-1); 1 or unset (-1): the newest AMD's library lists)
    static const int e = env_switch("RX_VK_FSR4_FG");
    return e;
}

/// AMD's library asked once (s.mu held, the device made): whether it has an FSR 4 frame generation for this card and driver
fgr::Why probe(Fg& s) {
    Library& l = lib();
    {
        std::lock_guard lk(l.mu);
        if (!load_library(l)) return fgr::FG_NO_LIBRARY;
    }
    if (!l.configure) {
        logf("vk: AMD FSR 4 frame generation: %s has no ffxConfigure", kLoader);
        return fgr::FG_NO_LIBRARY;
    }
    const std::string file = l.dir + "\\" + kFgFile;
    if (GetFileAttributesA(file.c_str()) == INVALID_FILE_ATTRIBUTES) {
        logf("vk: AMD FSR 4 frame generation: no %s beside AMD's loader in %s", kFgFile, l.dir.c_str());
        return fgr::FG_NO_FILE;
    }
    ffxQueryDescGetVersions versions{};
    versions.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
    versions.createDescType = FFX_API_CREATE_CONTEXT_DESC_TYPE_FRAMEGENERATION;
    versions.device = &l.device_context;
    uint64_t count = 0;
    versions.outputCount = &count;
    if (l.query(nullptr, &versions.header) != FFX_API_RETURN_OK || !count) {
        logf("vk: AMD FSR 4 frame generation: AMD's library lists no frame generation for this GPU");
        return fgr::FG_NO_MODEL;
    }
    std::vector<uint64_t> ids(count);
    std::vector<const char*> names(count);
    versions.versionIds = ids.data();
    versions.versionNames = names.data();
    if (l.query(nullptr, &versions.header) != FFX_API_RETURN_OK || !count || count > ids.size()) {
        logf("vk: AMD FSR 4 frame generation: the frame generations could not be listed");
        return fgr::FG_NO_MODEL;
    }
    std::string listed;
    for (uint64_t i = 0; i < count; i++) listed += (listed.empty() ? "" : ", ") + std::string(names[i] ? names[i] : "?");
    const bool only4 = fg_env() == 4;
    const int at = fgr::pick_version(names.data(), (int)count, only4);
    if (at < 0) {
        logf("vk: AMD FSR 4 frame generation: no frame generation it can take for this GPU (AMD's library has: %s%s)",
             listed.c_str(), only4 ? "; RX_VK_FSR4_FG=4: FSR 4's alone" : "");
        return fgr::FG_NO_MODEL;
    }
    s.version_id = ids[at];
    snprintf(s.version, sizeof s.version, "%s", names[at]);
    unsigned v[3];
    const bool fsr31 = fgr::parse_version(s.version, v) && v[0] < 4;
    logf("vk: AMD FSR 4 frame generation: AMD's library has %s; using %s%s (the Frame generation row's AMD FSR)", listed.c_str(),
         s.version, fsr31 ? ", FSR 3.1's frame generation: AMD lists FSR 4's for RX 9000 alone" : "");
    return fgr::FG_OK;
}

FfxApiResource image_resource(VkImage image, VkFormat format, uint32_t w, uint32_t h, VkImageUsageFlags usage, uint32_t more) {
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.imageType = VK_IMAGE_TYPE_2D, ci.format = format, ci.extent = {w, h, 1};
    ci.mipLevels = 1, ci.arrayLayers = 1, ci.samples = VK_SAMPLE_COUNT_1_BIT, ci.tiling = VK_IMAGE_TILING_OPTIMAL;
    ci.usage = usage, ci.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    // (GENERAL, which AMD's Vulkan backend takes for the unordered-access state, and leaves the image in: NX2navi hands it
    // the depth, the motion and its pictures the same way)
    return ffxApiGetResourceVK((void*)image, ffxApiGetImageResourceDescriptionVK(image, ci, more), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
}

/// framegen_rows.h teardown's steps in play (s.mu held by the caller: no call into AMD's library is in progress)
struct Down {
    Fg& s;
    void stop() { s.made = false; }
    void wait_gpu() {
        std::lock_guard qk(dev.present_mu);   // (every queue idle: the present queue's too, as vk_framegen.cpp's ensure_size)
        device_wait_idle_locked();
    }
    void destroy_context() {
        if (s.context) lib().destroy(&s.context, nullptr);
        s.context = nullptr, s.memory = 0;
    }
    void destroy_images() {
        if (s.out) destroy_image(s.out, s.out_memory);
        s.out = VK_NULL_HANDLE, s.out_memory = {}, s.out_new = false;
    }
};
/// ...and at the process's exit: the flag first, so that no call starts, then a call in progress is waited for (not for
/// ever: an exit never hangs on it)
struct AtExit {
    Fg& s;
    void stop() {
        g_fg_exiting.store(true);
        for (int i = 0; i < 200; i++) {
            if (s.mu.try_lock()) {
                s.made = false;
                s.mu.unlock();
                return;
            }
            Sleep(10);
        }
        logf("vk: AMD FSR 4 frame generation: a call into AMD's library did not return in 2 s at the exit");
    }
    void wait_gpu() {}
    void destroy_context() {}
    void destroy_images() {}
};

void release(Fg& s, const char* why) {
    if (!s.context && !s.out) return;
    logf("vk: AMD FSR 4 frame generation: its context is let go (%s; %llu frames made, %llu not made at a new history, %llu "
         "camera cuts among them; the game's frame alone %llu times without a picture without the HUD; %llu HDR Native "
         "pictures to the renderer's own)",
         why, (unsigned long long)s.n_made, (unsigned long long)s.n_skipped, (unsigned long long)s.n_cuts,
         (unsigned long long)s.n_held[fgr::HELD_NO_HUDLESS], (unsigned long long)s.n_held[fgr::HELD_HDR_NATIVE]);
    Down d{s};
    fgr::teardown(d, false);
    s.key = {}, s.have_pose = false, s.sequence = 0;
    g_fg_live.store(false);
}

void fail(Fg& s, const char* what, ffxReturnCode_t r) {
    // (the context stays until present_tick takes it down, two presents on: this frame's commands are recorded with it)
    logf("vk: AMD FSR 4 frame generation: %s failed (%d): off for this run, the renderer's own interpolation makes the frames",
         what, (int)r);
    s.made = false;
    g_fg_failed.store(true);
}

/// The context and the made frame's image for such frames. Each is made locally and published only when both exist
/// (docs/framegen-resource-failure.md): a failure leaves nothing behind and frame generation by AMD's library off for the run
bool make(Fg& s, const fgr::ContextKey& key) {
    Library& l = lib();
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.imageType = VK_IMAGE_TYPE_2D, ci.format = VK_FORMAT_R8G8B8A8_UNORM, ci.extent = {key.width, key.height, 1};
    ci.mipLevels = 1, ci.arrayLayers = 1, ci.samples = VK_SAMPLE_COUNT_1_BIT, ci.tiling = VK_IMAGE_TILING_OPTIMAL;
    ci.usage = kOutUsage;
    VkImage image = VK_NULL_HANDLE;
    VmaAllocation memory{};
    if (!create_image(ci, image, memory)) {
        fail(s, "the made frame's image", 0);
        return false;
    }
    s.backend = {};
    s.backend.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_VK;
    s.backend.deviceContext = l.device_context;
    // (the version asked of the library by its id, so an FSR 3.1 frame generation never stands in silently)
    s.pin = {};
    s.pin.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION;
    s.pin.versionId = s.version_id;
    s.backend.header.pNext = &s.pin.header;
    // (the version of the API this was built against, which the SDK asks for with every context)
    s.api = {};
    s.api.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_FRAMEGENERATION_VERSION;
    s.api.version = FFX_FRAMEGENERATION_VERSION;
    s.api.header.pNext = &s.backend.header;
    // ((Triforce, FG-2) the picture without the HUD, given each frame as HUDLessColor: 8 bits of sRGB as the picture is)
    s.hudless = {};
    s.hudless.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_FRAMEGENERATION_HUDLESS;
    s.hudless.hudlessBackBufferFormat = ffxApiGetSurfaceFormatVK(VK_FORMAT_R8G8B8A8_UNORM);
    s.hudless.header.pNext = &s.api.header;
    s.desc = {};
    s.desc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_FRAMEGENERATION;
    s.desc.header.pNext = &s.hudless.header;
    // (the depth it is given is reversed, 1 at the near plane: vk_fsr3_inputs.h. The picture is the presented one, 8 bits
    // of sRGB or of HDR10 codes: not the linear HDR that flag is for)
    s.desc.flags = FFX_FRAMEGENERATION_ENABLE_DEPTH_INVERTED | (key.infinite_depth ? FFX_FRAMEGENERATION_ENABLE_DEPTH_INFINITE : 0);
    s.desc.displaySize = {key.width, key.height};
    s.desc.maxRenderSize = {key.max_render_width, key.max_render_height};
    s.desc.backBufferFormat = ffxApiGetSurfaceFormatVK(VK_FORMAT_R8G8B8A8_UNORM);
    ffxContext context = nullptr;
    const auto t0 = std::chrono::steady_clock::now();
    const ffxReturnCode_t r = l.create(&context, &s.desc.header, nullptr);
    const double made_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    if (r != FFX_API_RETURN_OK || !context) {
        destroy_image(image, memory);
        fail(s, "its context", r);
        return false;
    }
    s.context = context, s.out = image, s.out_memory = memory, s.out_new = true, s.key = key;
    s.used_at = s.presents;
    g_fg_live.store(true);
    FfxApiEffectMemoryUsage usage{};
    ffxQueryDescFrameGenerationGetGPUMemoryUsage mem{};
    mem.header.type = FFX_API_QUERY_DESC_TYPE_FRAMEGENERATION_GPU_MEMORY_USAGE;
    mem.gpuMemoryUsageFrameGeneration = &usage;
    s.memory = l.query(&s.context, &mem.header) == FFX_API_RETURN_OK ? usage.totalUsageInBytes : 0;
    ffxQueryGetProviderVersion provider{};
    provider.header.type = FFX_API_QUERY_DESC_TYPE_GET_PROVIDER_VERSION;
    const bool known = l.query(&s.context, &provider.header) == FFX_API_RETURN_OK && provider.versionName;
    logf("vk: AMD FSR 4 frame generation: FSR frame generation %s made for pictures of %ux%u, scenes up to %ux%u, the far "
         "plane %s, with a picture without the HUD, no swapchain of AMD's (%.1f ms of CPU; its own %llu MB)",
         known ? provider.versionName : "?", key.width, key.height,
         key.max_render_width, key.max_render_height, key.infinite_depth ? "at infinity" : "finite", made_ms,
         (unsigned long long)(s.memory >> 20));
    return true;
}

}  // namespace

framegen_rows::Why why() {
    static const bool fsr_off = env_switch("RX_VK_FSR4") == 0;   // (FSR 4 out for this run: AMD's library is not loaded at all)
    if (fsr_off || fg_env() == 0) return fgr::FG_ENV_OFF;
    if (g_fg_failed.load(std::memory_order_relaxed)) return fgr::FG_FAILED;
    int w = g_fg_why.load(std::memory_order_relaxed);
    if (w >= 0) return (fgr::Why)w;
    if (!dev.device || dev.offscreen || g_fg_exiting.load()) return fgr::FG_NOT_YET;
    Fg& s = fg();
    std::lock_guard lk(s.mu);
    w = g_fg_why.load();
    if (w < 0 && g_fg_exiting.load()) return fgr::FG_NOT_YET;
    if (w < 0) w = (int)probe(s), g_fg_why.store(w);
    return (fgr::Why)w;
}

framegen_rows::Why why_known() {
    static const bool fsr_off = env_switch("RX_VK_FSR4") == 0;
    if (fsr_off || fg_env() == 0) return fgr::FG_ENV_OFF;
    if (g_fg_failed.load(std::memory_order_relaxed)) return fgr::FG_FAILED;
    const int w = g_fg_why.load(std::memory_order_relaxed);
    return w >= 0 ? (fgr::Why)w : fgr::FG_NOT_YET;
}

bool frames_wanted() {
    // (the row first: AMD's library is not asked anything, and nothing is logged, while the row is elsewhere)
    // ((Triforce) nor while HDR Native or an RGBA16F scene holds it from every present: no depth, motion or picture without
    // the HUD is made for frames AMD's library cannot be given, and the renderer's own makes the frame, as at 2x)
    return opts.framegen == fgr::FSR4 && fgr::fsr4_asked(opts.framegen, why(), dlssg::active()) &&
           !fgr::held_whole_run(held());
}

const char* version() { return g_fg_why.load(std::memory_order_relaxed) == fgr::FG_OK ? fg().version : ""; }

framegen_rows::Made generate(VkCommandBuffer cmd, const Inputs& in) {
    if (!cmd || !frames_wanted()) return fgr::OWN;
    Fg& s = fg();
    if (!in.color || !in.depth || !in.motion || !in.width || !in.height || !in.render_width || !in.render_height) {
        std::lock_guard lk(s.mu);
        if (!s.told_bare)   // ((Triforce) the lab's fgprobe1 run had no line for this, the reason AMD made no frame there)
            s.told_bare = true, logf("vk: AMD FSR 4 frame generation: a present without the scene's depth and motion (a menu, a movie, "
                                     "or no upscale's inputs made): the renderer's own interpolation makes its frame");
        return fgr::OWN;
    }
    std::lock_guard lk(s.mu);
    if (g_fg_exiting.load() || g_fg_failed.load()) return fgr::OWN;
    // ((Triforce, FG-2, FG-5) never a made frame with the HUD in the picture it moves. Without this frame's picture without
    // the HUD, the game's frame alone (GAME). In HDR Native (the game's own HDR encoding, which no picture without the HUD can
    // follow; frames_wanted already says no while present_native_pq is on, in.pq is this present's own word for it), the
    // renderer's own makes the frame (OWN, held_made), as a saved 9 ran on a card without AMD's frame generation
    const fgr::Held held = fgr::held_for(in.pq, false, in.hudless != VK_NULL_HANDLE);
    if (held != fgr::HELD_NONE) {
        s.n_held[held]++;
        if (!s.told_held[held]) {
            s.told_held[held] = true;
            logf("vk: AMD FSR 4 frame generation: %s (first at present %llu)",
                 held == fgr::HELD_HDR_NATIVE
                     ? "paused with HDR Native (the game encodes its HDR picture itself, and AMD's frame generation needs that "
                       "picture without the HUD, which only the game could encode): the renderer's own makes the frame, as at 2x"
                     : "no picture without the HUD this frame (it is taken at the gameplay upscale's output, before the HUD): "
                       "no made frame, the game's frame alone",
                 (unsigned long long)s.presents);
        }
        return fgr::held_made(held);
    }
    Library& l = lib();
    s.made = false;
    const bool infinite = !(in.far_plane < 1e8f);
    if (s.context && !fgr::context_fits(s.key, in.width, in.height, in.render_width, in.render_height, infinite))
        release(s, "another size or depth range");
    // (a new history: the caller's, a context made now, or a frame that does not follow the last one handed over)
    bool reset = in.reset || !s.context || in.sequence != s.sequence + 1;
    if (!s.context && !make(s, fgr::context_for(in.width, in.height, in.render_width, in.render_height, infinite))) return fgr::OWN;
    const fgr::Pose pose = fgr::pose_of(in.view);
    if (!reset && s.have_pose && fgr::camera_cut(s.pose, pose, in.frame_ms, fgr::kFrameGenCut)) {
        reset = true;
        if (s.n_cuts++ < 24)
            logf("vk: AMD FSR 4 frame generation: a camera cut (from %.1f %.1f %.1f to %.1f %.1f %.1f in %.1f ms): no made frame, a "
                 "new history", s.pose.pos[0], s.pose.pos[1], s.pose.pos[2], pose.pos[0], pose.pos[1], pose.pos[2], in.frame_ms);
    }
    s.pose = pose, s.have_pose = true;
    s.sequence = in.sequence, s.used_at = s.presents;
    s.frame_id++;

    if (s.out_new) {   // (the made frame's image starts UNDEFINED and stays in GENERAL)
        s.out_new = false;
        const VkImageMemoryBarrier2 b = barrier(s.out, 0, VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT,
                                                VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
        barriers(cmd, &b, 1);
    }
    full_barrier(cmd);   // (after what wrote the picture, the depth and the motion in this recording and before it)

    // 1. the configuration: generation on for this frame id, without a swapchain of AMD's and without its callbacks (the
    // frame is asked for below, not by a present)
    ffxConfigureDescFrameGeneration c{};
    c.header.type = FFX_API_CONFIGURE_DESC_TYPE_FRAMEGENERATION;
    c.frameGenerationEnabled = true;
    c.allowAsyncWorkloads = false;
    c.flags = FFX_FRAMEGENERATION_FLAG_NO_SWAPCHAIN_CONTEXT_NOTIFY;
    c.generationRect = {0, 0, (int32_t)in.width, (int32_t)in.height};
    c.frameID = s.frame_id;
    // ((Triforce, FG-2) the same picture without the HUD: what differs from it is kept where the game drew it, not moved)
    c.HUDLessColor = image_resource(in.hudless, VK_FORMAT_R8G8B8A8_UNORM, in.width, in.height, kInUsage, 0);
    ffxReturnCode_t r = l.configure(&s.context, &c.header);
    if (r != FFX_API_RETURN_OK) return fail(s, "the configuration", r), fgr::OWN;

    // 2. the preparation, from this frame's depth and motion and its camera, which FSR Frame Generation 4 needs
    ffxDispatchDescFrameGenerationPrepareV2 p{};
    p.header.type = FFX_API_DISPATCH_DESC_TYPE_FRAMEGENERATION_PREPARE_V2;
    p.frameID = s.frame_id;
    p.commandList = cmd;
    p.renderSize = {in.render_width, in.render_height};
    p.jitterOffset = {in.jitter[0], in.jitter[1]};
    p.motionVectorScale = {1.0f, 1.0f};   // (render pixels already, towards the frame before)
    p.frameTimeDelta = in.frame_ms > 0.0f && in.frame_ms < 100.0f ? in.frame_ms : 16.667f;
    p.reset = reset;
    p.cameraNear = in.near_plane;
    p.cameraFar = infinite ? 1e8f : in.far_plane;   // (read only for a finite far plane)
    p.cameraFovAngleVertical = in.fov_y;
    // (the game's world is in metres. NX2navi's note on this library: with 0.01 FSR frame generation 3.1.6 drew grey shapes
    // into the sky of its frames in a camera sweep, with 1 they were clean)
    p.viewSpaceToMetersFactor = 1.0f;
    p.depth = image_resource(in.depth, VK_FORMAT_R32_SFLOAT, in.render_width, in.render_height, kInUsage, 0);
    p.motionVectors = image_resource(in.motion, VK_FORMAT_R16G16_SFLOAT, in.render_width, in.render_height, kInUsage, 0);
    std::memcpy(p.cameraPosition, pose.pos, sizeof p.cameraPosition), std::memcpy(p.cameraUp, pose.up, sizeof p.cameraUp);
    std::memcpy(p.cameraRight, pose.right, sizeof p.cameraRight), std::memcpy(p.cameraForward, pose.fwd, sizeof p.cameraForward);
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (ffxDispatch records into cmd itself: what this thread recorded through vk_work.h reaches cmd first)
    r = l.dispatch(&s.context, &p.header);
    note_work(cmd);   // (AMD's dispatches: full_barrier must not take the next barrier for a repeat of the one before them)
    if (r != FFX_API_RETURN_OK) return fail(s, "the preparation", r), fgr::OWN;

    // 3. the generation: the one frame between the picture before and this one, into the image of ours. Given every frame,
    // a reset one too: the library keeps this picture as the next frame's start
    ffxDispatchDescFrameGeneration g{};
    g.header.type = FFX_API_DISPATCH_DESC_TYPE_FRAMEGENERATION;
    g.commandList = cmd;
    g.presentColor = image_resource(in.color, VK_FORMAT_R8G8B8A8_UNORM, in.width, in.height, kColorUsage, 0);
    g.outputs[0] = image_resource(s.out, VK_FORMAT_R8G8B8A8_UNORM, in.width, in.height, kOutUsage, FFX_API_RESOURCE_USAGE_RENDERTARGET);
    g.numGeneratedFrames = 1;
    g.reset = reset;
    g.backbufferTransferFunction = in.pq ? FFX_API_BACKBUFFER_TRANSFER_FUNCTION_PQ : FFX_API_BACKBUFFER_TRANSFER_FUNCTION_SRGB;
    g.minMaxLuminance[0] = 0.005f, g.minMaxLuminance[1] = in.pq ? in.peak_nits : 100.0f;   // (nits: read for an HDR picture)
    g.generationRect = c.generationRect;
    g.frameID = s.frame_id;
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);
    r = l.dispatch(&s.context, &g.header);
    note_work(cmd);
    if (r != FFX_API_RETURN_OK) return fail(s, "the generation", r), fgr::OWN;
    full_barrier(cmd);   // (before the made frame is copied)

    if (reset) {
        s.n_skipped++;
        return fgr::SKIP;
    }
    s.made = true;
    if (s.n_made++ == 0)
        logf("vk: AMD FSR 4 frame generation: the first made frame, %ux%u from depth and motion of %ux%u (near %.4f, far %.6g, fov "
             "%.2f deg, jitter %+.3f %+.3f px)", in.width, in.height, in.render_width, in.render_height, in.near_plane,
             infinite ? INFINITY : in.far_plane, in.fov_y * 57.2957795f, in.jitter[0], in.jitter[1]);
    return fgr::MADE;
}

VkImage made_image() {
    Fg& s = fg();
    std::lock_guard lk(s.mu);
    return s.made ? s.out : VK_NULL_HANDLE;
}

void present_tick() {
    if (!g_fg_live.load(std::memory_order_relaxed)) return;   // (no context: one atomic load a present)
    Fg& s = fg();
    std::lock_guard lk(s.mu);
    if (g_fg_exiting.load()) return;
    s.presents++;
    if (fgr::release_due(s.context != nullptr || s.out != VK_NULL_HANDLE, g_fg_failed.load(), s.presents, s.used_at))
        release(s, g_fg_failed.load() ? "after its failure" : "the Frame generation row left AMD FSR 4");
}

void exiting() {
    AtExit e{fg()};
    fgr::teardown(e, true);
}

}  // namespace fsr4fg
#else   // (not Windows: AMD publishes no frame generation library elsewhere)
namespace fsr4fg {
framegen_rows::Why why() { return framegen_rows::FG_NOT_BUILT; }
framegen_rows::Why why_known() { return framegen_rows::FG_NOT_BUILT; }
bool frames_wanted() { return false; }
const char* version() { return ""; }
framegen_rows::Made generate(VkCommandBuffer, const Inputs&) { return framegen_rows::OWN; }
VkImage made_image() { return VK_NULL_HANDLE; }
void present_tick() {}
void exiting() {}
}  // namespace fsr4fg
#endif

#else  // (no HOOKSHOT_FSR in this build: FSR is not there)

bool fsr4_built() { return false; }
const TemporalEngine* fsr4_engine() { return nullptr; }
void fsr4_probe() {}
void fsr4_prepare_shaders() {}
void fsr4_close() {}
bool fsr4_wants_descriptor_buffer() { return false; }
namespace fsr4fg {
framegen_rows::Why why() { return framegen_rows::FG_NOT_BUILT; }
framegen_rows::Why why_known() { return framegen_rows::FG_NOT_BUILT; }
bool frames_wanted() { return false; }
const char* version() { return ""; }
framegen_rows::Made generate(VkCommandBuffer, const Inputs&) { return framegen_rows::OWN; }
VkImage made_image() { return VK_NULL_HANDLE; }
void present_tick() {}
void exiting() {}
}  // namespace fsr4fg

#endif

// ((Triforce) in every build: the menu's Frame generation line reads it, and frames_wanted above)
extern std::atomic<bool> present_native_pq;   // (vk_replay.cpp: the game's picture is HDR10 codes, HDR Native)
framegen_rows::Held fsr4fg::held() {
    if (present_native_pq.load(std::memory_order_relaxed)) return framegen_rows::HELD_HDR_NATIVE;
    // (the run's scene is RGBA16F: decided at the start and kept for the run, whatever the HDR row says now)
    if (temporal_scene_format(VK_FORMAT_R16G16B16A16_SFLOAT)) return framegen_rows::HELD_HDR_SCENE;
    return framegen_rows::HELD_NONE;
}

}  // namespace mkwvk
