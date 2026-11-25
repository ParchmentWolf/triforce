// The Vulkan back end's shared state (gpu/vk).
#pragma once

#include <cstdint>
#include <array>
#include <atomic>
#include <mutex>
#include <string>
#include <vector>

#include "vk_loader.h"
#include "vk_api.h"
#include "vk_vendor.h"
#include "write_gen.h"   // (WriteGen: a page write generation, 64 bits)
#include "memory_priority.h"   // ((Triforce, 11-22, TEX-47) RX_VK_MEMORY_PRIORITY's tiers

#if defined(_MSC_VER) && (defined(_M_X64) || defined(_M_IX86))
#include <intrin.h>
#define HOOKSHOT_RDTSC() ((uint64_t)__rdtsc())
#define HOOKSHOT_PAUSE() _mm_pause()
#elif defined(__x86_64__) || defined(__i386__)
#include <x86intrin.h>
#define HOOKSHOT_RDTSC() ((uint64_t)__rdtsc())
#define HOOKSHOT_PAUSE() _mm_pause()
#endif

typedef struct VmaAllocation_T* VmaAllocation;   // (vk_mem_alloc.h's handle)

namespace mkwvk {

extern std::vector<std::string> gpu_device_names;
extern const MkwVkHost* host;
void logf(const char* fmt, ...);
// (Triforce) A line at another level than info, as host/hos.h's hos_log_at: "[trace] " (and error, warn, debug) leads its text,
// which the host writes after its thread's tag. Within the renderer: the host's log callback is unchanged (no API change)
enum LogLevel : int { log_error, log_warn, log_info, log_debug, log_trace };
void logf_at(LogLevel level, const char* fmt, ...);
// (Triforce, lab) RX_VK_FT=<present>, RX_VK_FT_N=<n>: the steps the renderer takes in those frames, by the clock of the host,
// in the plain mode too (vk_replay.cpp; the other half is HOS_FT, nvn_native.c; reader perf/night/ft.py)
bool vk_ft_on();
void recorder_auto(bool on);   // ((Triforce) vk_replay.cpp: the recorder thread's default, vk_recorder.h g_auto_thread)
// ((Triforce) Threaded rendering, threaded_rendering.h: vk_main.cpp resolves the row and RX_VK_THREADED once, at the device's pick.
// threaded_render_thread: its render thread (async_on, RX_VK_ASYNC unset); threaded_recorder_thread: its recorder thread
// (RX_VK_RECORDER unset); threaded_on: either, the design's other pieces with them (the recorder by part, the parts at the
// game's pass ends, the present thread, the next image ahead). All false with the row Off, the default)
bool threaded_render_thread();
bool threaded_recorder_thread();
bool threaded_on();
void vk_ft(const char* fmt, ...);
void queue_flush_locked();   // (vk_replay.cpp, RX_VK_BATCH: held submits out; dev.present_mu held)
void queue_flush();          // (the same, taking dev.present_mu)
// (hookshot) held submits out, then vkDeviceWaitIdle with the present queue's lock taken too (dev.present_mu held): the device's
// every queue is synchronized by the host around it
void device_wait_idle_locked();
// (Triforce) why the swapchain is SDR though the Insert menu's HDR is on (Device::hdr_sdr_why): no VK_EXT_swapchain_colorspace;
// HDR off in Windows' display settings; HDR on there but the driver lists no HDR10 surface; the display lists none and the
// system's setting is not known (Linux, or a Windows that doesn't say). hdr_sdr_count: how many, for the log's and the
// menu's line for each
enum HdrSdrWhy : int { hdr_sdr_none, hdr_sdr_no_extension, hdr_sdr_os_off, hdr_sdr_driver, hdr_sdr_unknown, hdr_sdr_count };

/// ((Triforce) Threaded rendering's recorder, RX_VK_RECORDER_PARTS) What a queue's lock tells the recorder thread (vk_recorder.h
/// queue_lock_event, installed by vk_replay.cpp; null: nothing, as in the checks): 0 before the lock is taken (lock(), not
/// try_lock()), 3 when it is held by another and the thread blocks for it, 1 once it is taken, 2 before it is let go
inline void (*queue_lock_hook)(int phase, bool settles) = nullptr;
/// ((Triforce) A queue's lock: a std::mutex that says when it is taken and let go (queue_lock_hook, which does nothing without
/// RX_VK_RECORDER_PARTS). With it the recorder thread makes a part's submit under dev.present_mu itself: a thread about to take
/// that lock first waits until the parts handed to the recorder are submitted (settles: the queue's order), and a thread holding
/// any queue lock never waits for a recorder that waits for it (vk_recorder.h queue_escaped)
struct QueueMutex {
    std::mutex m;
    const bool settles = true;
    QueueMutex() = default;
    explicit QueueMutex(bool s) : settles(s) {}
    void lock() {
        if (queue_lock_hook) queue_lock_hook(0, settles);
        if (!m.try_lock()) {
            if (queue_lock_hook) queue_lock_hook(3, settles);
            m.lock();
        }
        if (queue_lock_hook) queue_lock_hook(1, settles);
    }
    /// (no wait for the parts: a try is not to block. Its caller waits for them itself where the queue's order needs it)
    bool try_lock() {
        if (!m.try_lock()) return false;
        if (queue_lock_hook) queue_lock_hook(1, settles);
        return true;
    }
    void unlock() {
        if (queue_lock_hook) queue_lock_hook(2, settles);
        m.unlock();
    }
};

struct Device {
    VkInstance instance = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkPhysicalDeviceProperties props{};
    VkPhysicalDeviceMemoryProperties memory{};
    VkPhysicalDeviceFeatures features{};
    VkDevice device = VK_NULL_HANDLE;
    uint32_t queue_family = 0;
    VkQueue queue = VK_NULL_HANDLE;
    // extensions in use
    bool mesh_shader = false, mesh_queries = false, external_memory_host = false, external_memory_fd = false, dma_buf_import = false, pipeline_library = false,
         graphics_pipeline_library = false, custom_border_color = false, dynamic_state3 = false,
         depth_clip_control = false, null_descriptor = false, index_uint8 = false, push_descriptor = false,
         conditional_rendering = false, provoking_vertex = false, vertex_divisor = false, stencil_export = false, memory_budget = false,
         memory_priority = false,   // ((Triforce, 11-22, TEX-47) VK_EXT_memory_priority and its feature, asked for with RX_VK_MEMORY_PRIORITY alone
         checkpoints = false,   // (RX_VK_CHECKPOINTS: VK_NV_device_diagnostic_checkpoints)
         buffer_marker = false, // (RX_VK_CHECKPOINTS=1 without the NV extension: VK_AMD_buffer_marker, AMD and Intel)
         device_fault = false,  // (VK_EXT_device_fault: what a lost device faulted on)
         sparse_images = false, // (sparse resident 2D images on the queue: the terrain's huge arrays)
         sparse_buffers = false, // (sparse-bound buffers on the queue: a pool imported as several dma-bufs)
         view_2d_of_3d = false, // (VK_EXT_image_2d_view_of_3d: a 3D texture a 2D sample instruction reads)
         coop_matrix = false,   // (VK_KHR_cooperative_matrix with its feature)
         native_mma = false,    // (HMMA on it: the cooperative matrix test passed, vk_coopmat.cpp)
         // ((Triforce) VK_KHR_fragment_shading_rate with pipelineFragmentShadingRate, native mesh shaders and
         // RX_VK_FOLIAGE_SHADOW_VRS not off: the far cascades' foliage at 2 x 2, foliage_shadow.h)
         foliage_rate = false;
    bool float_atomic_add = false;   // (Triforce) VK_EXT_shader_atomic_float's shaderBufferFloat32AtomicAdd: the translator's float adds
    bool eds3_polygon = false, eds3_clamp = false, eds3_blend = false, eds3_a2c = false;
    bool swapchain_colorspace = false;   // (hookshot) VK_EXT_swapchain_colorspace: HDR10 surfaces are listed
    bool hdr = false;                    // (hookshot) the swapchain is HDR10 (ST 2084, Rec. 2020): framegen_hdr writes it
    // (Triforce) why it is SDR with HDR on, for the log and the menu's hint: written by create_swapchain and read by the menu on
    // the presenting thread both (menu_record), as hdr is
    HdrSdrWhy hdr_sdr_why = hdr_sdr_none;
    bool mesh_fallback = false;   // (hookshot) no VK_EXT_mesh_shader: task and mesh programs as compute shaders (vk_shader.cpp)
    bool task_mesh_fallback = false;
    // ((Triforce) AMD's Windows driver for RDNA 2: the workaround takes mesh-only programs too. vk_main.cpp create_device)
    bool mesh_only_fallback = false;
    bool uses_mesh_fallback(bool has_task) const {
        return mesh_fallback || (task_mesh_fallback && (has_task || mesh_only_fallback));
    }
    VkPhysicalDeviceVulkan12Features vk12{};
    VkPhysicalDeviceVulkan13Features vk13{};
    VkPhysicalDeviceFloatControlsProperties float_controls{};   // ((Triforce) the float execution modes shaders may declare: make_profile)
    VkShaderStageFlags subgroup_stages = 0;   // ((Triforce) subgroupSupportedStages: the stages subgroup operations may be used in)
    VkShaderStageFlags sg32_stages = 0;   // (stages that run at 32 lanes when asked: the size the translated programs assume)
    uint32_t max_workgroup_subgroups = 0;   // ((Triforce) maxComputeWorkgroupSubgroups: a workgroup held to 32 lanes has at most 32 times this)
    uint32_t max_mesh_groups = UINT32_MAX;   // ((Triforce) the workgroups {x, 1, 1} a native mesh draw may ask for: vk_draw.cpp sim_turf_max_records)
    uint32_t subgroup_min = 0;            // ((Triforce) the fewest lanes a stage can be held to: fallback_lanes.h)
    uint32_t subgroup_size = 32, subgroup_max = 32;   // (the lanes a stage not pinned runs at, and the most it can have)
    VkDriverId driver_id{};
    bool radv_gcn = false;   // ((Triforce, 11-22, MEM-23) RADV on a GCN 1 to 4 GPU: vk_vendor.h radv_gcn, set in create_device)
    VendorFixes fixes{};   // (hookshot) the vendor and driver workarounds this device needs (vk_vendor.h; vk_main.cpp create_device)
    bool amd_older_compiler = false;   // ((Triforce) AMD's Windows driver for RDNA 1 and 2, vk_vendor.h: the mesh fallback's strict multiplies)
    uint32_t max_push_descriptors = 0;
    uint32_t max_vertex_divisor = 0;   // (maxVertexAttribDivisor, with dev.vertex_divisor)
    // no window (HOS_HEADLESS): presents go to an image of their own, which RX_VK_SHOTS can write out
    bool offscreen = false;
    // the window
    VkSurfaceKHR surface = VK_NULL_HANDLE;
    VkSwapchainKHR swapchain = VK_NULL_HANDLE;
    VkFormat swap_format = VK_FORMAT_UNDEFINED;
    VkExtent2D swap_extent{};
    std::vector<VkImage> swap_images;
    std::vector<VkImageView> swap_views;   // (hookshot) a view of each, for Dear ImGui's overlays (VK_NULL_HANDLE: none)
    VkFormat swap_view_format = VK_FORMAT_UNDEFINED;   // (their format: the UNORM one of an sRGB swapchain when it can be)
    bool swap_mutable = false;   // (VK_KHR_swapchain_mutable_format: an sRGB swapchain's images viewed as UNORM)
    std::vector<VkSemaphore> swap_rendered;   // present waits belong to acquired images, not frame slots
    QueueMutex present_mu;   // (the swapchain: presents and resizes; (Triforce) the replay queue's submits: QueueMutex)
    std::atomic<uint64_t> swap_resize{0};   // (a new window size, width << 32 | height: the next present makes the swapchain)
    uint64_t swap_generation = 0;   // ((Triforce) one more for each swapchain made: an image present_image holds belongs to one)
    // (hookshot) a queue of a compute family for vkQueuePresentKHR alone (vk_main.cpp create_device; RX_VK_PRESENT_QUEUE=0 / 1).
    // VK_NULL_HANDLE: presents go on `queue` under present_mu. Its own lock: taken after present_mu, never before it
    VkQueue present_queue = VK_NULL_HANDLE;
    QueueMutex present_queue_mu{false};
    uint32_t present_family = 0;   // (present_queue's family, the swapchain's images shared with it)
};
extern Device dev;

/// (Triforce) Whether a stage of this many invocations runs at 32 lanes (pin_subgroup, profile_pinned, profile_graphics): one
/// the GPU pins, and for a stage with a workgroup (compute, task, mesh) 32-lane subgroups that cover it, at most
/// requiredSubgroupSize * maxComputeWorkgroupSubgroups invocations (VUID-VkPipelineShaderStageCreateInfo-pNext-02756), a
/// limit the spec sets no minimum for. The default, 64: a task or mesh workgroup has 63 threads at most (a 6-bit count), and
/// the mesh fallback runs the same workgroups as compute shaders
inline bool pins_32(VkShaderStageFlags stage, uint64_t invocations = 64) {
    if (!(dev.sg32_stages & stage)) return false;
    const VkShaderStageFlags workgroup = VK_SHADER_STAGE_COMPUTE_BIT | VK_SHADER_STAGE_TASK_BIT_EXT | VK_SHADER_STAGE_MESH_BIT_EXT;
    return !(stage & workgroup) || invocations <= 32ull * dev.max_workgroup_subgroups;
}

/// (hookshot) Where a storage buffer binding starts: the address rounded down to this, the shaders' offsets counted from there
/// (vk_shader.cpp make_profile / host_info, the translator's ssbo_align_mask; vk_draw.cpp's descriptor writer). At least 16
/// bytes, whatever the device allows: the translator reads 8- and 16-byte accesses through vector views (offset >> 3, >> 4),
/// exact only while a binding starts on a 16-byte boundary. At AMD's 4 bytes an aligned access could start at any word of the
/// binding and the view read the vector before it: OoT's light colours shifted (green lighting, cyan sky). Found for Lichii
/// (zortos293/Lichii#295, Fritchii 57ed438cd, from Matt Artist and sharkiix); NVIDIA's own alignment is 16 already
inline uint64_t storage_binding_align() {
    return dev.props.limits.minStorageBufferOffsetAlignment > 16 ? dev.props.limits.minStorageBufferOffsetAlignment : 16;
}

/// A range of guest memory as the GPU sees it: a buffer (an imported pool), the offset in it, and its device address
struct BufferRef {
    VkBuffer buffer = VK_NULL_HANDLE;
    uint64_t offset = 0, size = 0;
    VkDeviceAddress address = 0;
    explicit operator bool() const {
        return buffer != VK_NULL_HANDLE;
    }
};
bool memory_init();                                   // vk_memory.cpp
/// ((Triforce) vk_memory.cpp memory_table_cover, RX_VK_GP_TABLE) a storage buffer's pages in the guest page table: they already gave
/// its memory, were made to, were made to over another binding's this submission, or cannot be: outside the table's windows (or no
/// address), or the binding reads a copy rather than a pool's memory or its mirror's
enum class TableCover : uint8_t { Held, Written, Conflict, Outside, Copy };
TableCover memory_table_cover(uint64_t gpu, uint64_t n, uint64_t address);
void memory_table_cover_on();     // ((Triforce) the cover's bookkeeping kept from now on: vk_coopmat.cpp, RX_VK_GP_TABLE)
void page_table_census_log(const char* when);   // ((Triforce) the guest pools outside the page table's windows, page_table_census.h)
void page_table_check_close();   // ((Triforce, vk_draw.cpp) RX_VK_GP_TABLE's last line, the GPU waited for with =2)
bool pools_mirrored();   // ((Triforce, upstream #2464) vk_memory.cpp mirror_on: the buffer pools have VRAM mirrors)
// ((Triforce) The PC's RAM and what the process holds (vk_memory.cpp, mem_parts.h). memory_ram_watch: once a present (it asks
// every 60 presents, and every 600 has the memory line written on a thread of its own); the answers are those of its last look)
void memory_ram_watch(uint64_t presents);
bool memory_ram_low();                       // (under 3 GB available, or a tenth of a PC of more than 30 GB)
bool memory_ram_short();                     // (under 1.5 GB available at two looks in a row)
// ((Triforce, 11-22, the performance audit's MEM-141) the swap-aware pressure hold (vk_memory.cpp, linux_pressure.h; off unless
// RX_VK_SWAP_RESERVE_MB is set, never on Windows): whether it is on, the cut of an integrated GPU's texture budget, the bytes
// a valve gave (1: staging arenas, 2: capture spares; the imports count themselves), and the imports' limit for the episode
bool memory_swap_hold();
uint64_t memory_swap_cut();
void memory_swap_valve(int valve, uint64_t bytes);
uint64_t memory_swap_episode_want();
void memory_swap_gave(uint64_t bytes);
bool memory_ram_fits(uint64_t bytes);        // (a copy of that many bytes fits in the RAM available, with 2 GB to spare)
bool memory_ram_fits_now(uint64_t bytes);    // ((Triforce) the same with the RAM looked at now: the preparation's checkpoints)
void memory_process(uint64_t* working_set, uint64_t* private_bytes);   // (the process's, asked now; 0 when not known)
void pcache_let_go(uint64_t avail);          // (vk_draw.cpp: the pipeline cache let go for the RAM, once; pcache_gate.h)
// (vk_draw.cpp) the cache as last read or saved (-1: let go), the graphics pipelines kept, the stage libraries kept, how many
// of the pipelines a draw has looked up, and how many no draw used were given back for the RAM
void pipeline_parts(int64_t* cache_bytes, int64_t* pipelines_kept, int64_t* libraries_kept, int64_t* drawn, int64_t* released);
void pipelines_release_tick(uint64_t presents);   // (vk_draw.cpp, the thread presenting with replay_mu held: pipe_release.h)
int64_t vma_system_blocks();                 // (vk_vma.cpp: the allocator's blocks in system memory, bytes)
void memory_cpu_owned(uint64_t guest, uint64_t size);   // (hookshot: words the replay writes on the CPU, left out of write-backs)
// (hookshot) The replay's own CPU writes of guest memory, by GPU address: every one goes through guest_cpu_write (or, for a
// write made in pieces, host->gpu_write and then guest_cpu_wrote over the whole range), so that the write-back diff's shadows
// hear of it before this submission's write-back (vk_memory.cpp, "the write-back's diff"). tests/test_wb_diff_cpu_writes.py
int guest_cpu_write(uint64_t gpu, const void* src, uint64_t n);
void guest_cpu_wrote(uint64_t gpu, uint64_t n);
void memory_table_begin();                         // (hookshot: a recording's page table changes held back for its upload commands)
bool memory_table_flush();
void memory_table_segments_end();                  // (Triforce: a parallel replay's page table changes once more, in the order they were made)
uint64_t memory_guest_pages();                       // (hookshot: the device address of guest memory's page table, 0: none)
void memory_sync();                                   // (at each submit: pools the game made or let go)
extern std::atomic<int64_t> memsync_lock_wait_ns;     // (hookshot, diagnostics: time memory_sync waited for its two locks; the slow-submit line)
extern std::atomic<int64_t> memsync_part_ns[3];       // (hookshot, diagnostics: submit_memory_work's memory_sync, memory_take_capture, memory_collect_written)
BufferRef gpu_buffer(uint64_t gpu, uint64_t size);   // (empty when no pool holds the range)
/// A range as a binding of the replay sees it: the pool's VRAM mirror when it has one (vk_memory.cpp), else the
/// imported pool. written: the GPU may write it (copied back to guest memory at the submission's end).
BufferRef gpu_buffer_bind(uint64_t gpu, uint64_t size, bool written);
/// (Evil Hookshot) the binds that follow come from a compute program's storage buffers (1) or not (0): vk_memory.cpp's mirror trials
void memory_bind_from_compute(bool on);
BufferRef stream_copy(const void* src, uint64_t n);   // vk_draw.cpp: bytes in the recording's stream, as a binding
/// Authored constants in the recording's stream: never recycled until its recording completes.
/// Fill mapped, then flush memory through binding.offset + binding.size before GPU use.
struct UniformUpload {
    BufferRef binding;
    uint8_t* mapped = nullptr;
    VmaAllocation memory = nullptr;
};
UniformUpload uniform_upload(uint64_t size);   // empty: no recording or no room; no history consumed
/// Changes when a read binding remembered earlier must be looked up again (a pool left, a mirror was made, a new submission)
uint64_t gpu_bind_stamp();
/// Around each submission's recording: mirrors wanted since the last one are made (begin), what the GPU wrote into
/// mirrors goes back to guest memory (end, outside any pass, before the closing barrier)
void memory_begin_submission();
void memory_sync_mirrors_before_segments();   // (hookshot: vk_memory.cpp)
bool probe_on();                                // (hookshot: vk_draw.cpp, RX_VK_PROBE)
bool probe_serial();
void probe_dump_all(const char* why);
void probe_log(uint64_t frame);
void memory_end_submission(VkCommandBuffer cmd);
// (Triforce) The lazy write-back (vk_memory.cpp, the Debug tab's row; each returns at once with it off): a recording went
// onto the queue (submit_recording, dev.present_mu held); guest memory [p, p + n) is about to be handed to the kernel or
// to have its pages' state changed (host/rx_backend.c hos_guest_io_begin, import_pool), and that call is over (held: what
// the first returned)
void memory_lazy_submitted();
bool memory_lazy_running();   // ((Triforce) vk_memory.cpp: the lazy write-back runs (Threaded rendering's recorder: vk_replay.cpp submit_recording))
bool memory_lazy_io_begin(const void* p, uint64_t n);
void memory_lazy_io_end(bool held);
/// The game made a memory pool (gpu address, bytes): imported in the background, before it is used
/// RX_VK_CHECKPOINTS: the draws the GPU reached, logged once the device is lost (vk_draw.cpp)
void checkpoints_report();
/// The device is lost: that report once, then the process ends (vk_replay.cpp)
[[noreturn]] void device_lost(const char* why = nullptr);   // (why: the FATAL line, when it is not that the driver returned VK_ERROR_DEVICE_LOST: a hang it never reported, gpu_hang_watch_start)
/// VK_AMD_buffer_marker's buffer, for RX_VK_CHECKPOINTS on a device without the NV checkpoints (vk_draw.cpp)
void buffer_markers_init();
void coopmat_init();   // vk_coopmat.cpp (once the device is made)
/// ((Triforce) vk_cache_set.cpp, cache_set.h) The kept set of the shader caches: kept, put back or deleted for this start's
/// stamp, once the device is made and before anything opens a cache (vk_main.cpp mkwvk_init)
void cache_set_init();
/// ((Triforce) cache_set.h kStatesPending) A kept set was put back while the player's pipeline state list had grown since it
/// was kept: the prepare before the title goes through the state lists (vk_draw.cpp prepare_run). RX_VK_NO_STATE_LIST: false
bool cache_set_states_pending();
/// The lists were gone through (vk_draw.cpp state_list_prepare): the marker removed
void cache_set_states_done();
/// A marker of another kind of GPU work (m: mirror sync, b: write-back, u: texture upload, g: GPU unswizzle; key: its
/// pool or texture), RX_VK_CHECKPOINTS. (Triforce) And the boundaries between them (checkpoint_kinds.h): w the write-back diff
/// pass, r and z a recording begun and ended, v its uploads begun, p, M and P the present's blit begun, its menu, its end
void checkpoint_mark(VkCommandBuffer cmd, uint64_t key, char kind);
/// (Triforce) The device lost's report: the queue's timeline and the replay's ways (vk_replay.cpp), the memory work under way and
/// the mirrors' piece binds the submits wait for (vk_memory.cpp). Read without their locks: the thread that lost the device may
/// hold them
void replay_lost_report();
void memory_lost_report();

/// Parallel replay (vk_replay.cpp, RX_VK_PARALLEL): while segments of a submission are recorded on several threads,
/// what they share (textures and their uploads, programs, pipelines, samplers, pools and memory stamps) is used under
/// one lock; the per-draw caches are each thread's own
extern std::atomic<bool> par_active;
extern std::atomic<int64_t> par_lock_wait_ns, par_locks;   // (contention: the time threads waited for it)
std::recursive_mutex& par_mutex();
int64_t par_now_ns();
/// RX_VK_PARLOCK_SPIN=<n> (default 4000, 0: off): ParLock spins this many times before it sleeps. The lock is held for
/// microseconds at a time, and a recording thread put to sleep on it waited for the OS's wake-up (tens of microseconds) at
/// every collision
int par_spin();
inline void par_pause() {
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__)
    __builtin_ia32_pause();
#elif defined(__aarch64__)
    __asm__ __volatile__("yield");
#endif
}
struct ParLock {
    bool on;
    explicit ParLock(bool want = true) : on(want && par_active.load(std::memory_order_relaxed)) {
        if (!on) return;
        par_locks.fetch_add(1, std::memory_order_relaxed);
        if (par_mutex().try_lock()) return;
        for (int i = par_spin(); i > 0; i--) {
            par_pause();
            if (par_mutex().try_lock()) return;
        }
        const int64_t t0 = par_now_ns();
        par_mutex().lock();
        par_lock_wait_ns.fetch_add(par_now_ns() - t0, std::memory_order_relaxed);
    }
    ~ParLock() {
        if (on) par_mutex().unlock();
    }
    ParLock(const ParLock&) = delete;
    ParLock& operator=(const ParLock&) = delete;
};
void memory_pool_created(uint64_t gpu, uint64_t size);
/// Whether guest memory in [lo, hi) is in an imported pool, live or retired (the GPU may read or write it)
int memory_guest_imported(uint64_t lo, uint64_t hi);
void memory_stats(int64_t* mirrors, uint64_t* mirror_mb, int64_t* sync_bytes, int64_t* sync_copies, int64_t* wb_bytes);
// Page write generations (vk_memory.cpp, after totk-pc-recomp's vk_memory.c): at each submit the guest pages the CPU
// wrote since the last one (the soft write watch) are stamped with a new generation; a texture uploaded at
// generation g is stale when a page of its storage carries a newer one. GPU writes into guest memory that textures
// may be read from (storage buffers, buffer copies) are stamped the same way.
void memory_collect_written();
/// RX_VK_CAPTURE (on with the mirrors; =0 off): at a submit, on the submitting thread, the pages the CPU wrote since the
/// last one, and a copy of them as they are then; the replay stamps them and fills the mirrors from that copy
/// (Triforce) behind: the submitting thread replays this submission before it goes back to the game (vk_replay.cpp submit_q,
/// RX_VK_ASYNC off), so the capture's copies may be left to the copy helpers while it replays (capture_behind.h,
/// RX_VK_CAPTURE_BEHIND); memory_capture_copies_done before it returns
bool memory_capture_submit(bool behind = false);   // (true: a capture was queued for the replay to take)
/// (Triforce) The copies of a capture left to the helpers, all made and flushed (they are, before a recording is submitted:
/// memory_mirror_binds_flush). Nothing to do when none are
void memory_capture_copies_done();
/// (Triforce) The submit-time captures so far, for the 120-present line and the stall line (vk_replay.cpp status_tick)
struct MemoryCaptureStats {
    int64_t captures = 0, ns = 0, scan_ns = 0, copy_ns = 0;   // (capture_make: on the thread that submits; its scan; its copies)
    int64_t wait_ns = 0;      // (the copies behind made or waited for by the threads that replay, and before a submitting thread returns)
    int64_t pages = 0, behind = 0;   // (pages copied, of them left to the helpers)
    int64_t parts_helper = 0, parts_reader = 0, parts_finish = 0, waited = 0, failed = 0;
};
void memory_capture_stats(MemoryCaptureStats* s);
/// The replay of the next submit: its capture (false: none, the pages are collected now as before)
bool memory_take_capture(uint64_t value, uint64_t completed);
bool memory_capture_now(uint64_t value, uint64_t completed);   // (hookshot: made and taken at once)
uint64_t memory_captures_begun();   // (how many captures have been begun so far; any thread: vk_replay.cpp cpu_signal_uncaptured)
/// The submission the replay records next (bindings note it: a pool's mirror is in use until it is done)
void memory_recording_value(uint64_t value, uint64_t completed);
/// RX_VK_TEX_CAPTURE (on with the capture; =0 off): the storage of a texture uploaded from guest memory joins the
/// capture (its pool up to 256 MB, else its 2 MB regions), and what the capture took of it is kept for the uploads
void memory_note_texture_upload(uint64_t guest, uint64_t size);
/// Whether [guest, guest + n) has pages kept as a capture took them
bool memory_has_shadow(uint64_t guest, uint64_t n);
/// A read of guest memory by the replay as the submission being recorded had it: the pages a kept capture holds from
/// there (the game writes several submits ahead of the replay), the rest from guest memory. False when unreadable
bool memory_read_as_submitted(uint64_t gpu, void* dst, uint64_t n);
uint64_t memory_capture_view();          // (bumped when a capture is published or any page is stamped)
WriteGen memory_page_stamp(uint64_t gpu); // (that address's page only)
uint64_t gpu_pool_end(uint64_t gpu);   // (hookshot) where the memory pool holding that address ends, 0: in none (vk_memory.cpp)
uint64_t gpu_pool_start(uint64_t gpu); // (EvilOOT) and where it begins
bool create_buffer_cached(uint64_t size, VkBufferUsageFlags usage, VkBuffer& buffer, VmaAllocation& allocation,
                          void** mapped, bool dedicated = false);   // (vk_vma.cpp: cached host memory, mapped)
void flush_mapped(VmaAllocation allocation, uint64_t size);
bool host_cached(VmaAllocation allocation);   // (its memory type has VK_MEMORY_PROPERTY_HOST_CACHED_BIT)
// ((Triforce, 11-22, MEM-39) vk_vma.cpp: the lab's capture buffer in uncached host memory; an allocation's memory type)
bool create_buffer_uncached(uint64_t size, VkBufferUsageFlags usage, VkBuffer& buffer, VmaAllocation& allocation,
                            void** mapped, bool dedicated = false);
uint32_t alloc_memory_type(VmaAllocation allocation, VkMemoryPropertyFlags* flags);
void flush_mapped_range(VmaAllocation allocation, uint64_t offset, uint64_t size);
void invalidate_mapped(VmaAllocation allocation, uint64_t size);   // (the CPU is to read what the GPU wrote: a no-op in coherent memory)
void memory_stamp_gpu(uint64_t guest, uint64_t size);   // (a GPU write: memory_stamp, and the pages noted)
void memory_protect_gpu(uint64_t guest, uint64_t size);  // (RX_VK_PROTECT_BARE=1: pages a shader writes through a table pointer)
/// (vk_replay.cpp) guest memory as the stream's place sees it: as submitted, the stream's uniform updates before it over it
bool ub_read(uint64_t addr, void* dst, uint64_t n);
/// [guest, guest + n) as of the submit being replayed: live itself, or scratch holding it with the kept pages over it
const uint8_t* memory_as_submitted(uint64_t guest, const uint8_t* live, uint64_t n, std::vector<uint8_t>& scratch);
/// (Triforce) the same bytes given to fn part by part, a part within one 4 KB page, with no copy of the whole (upload_same.h)
void memory_visit_as_submitted(uint64_t guest, const uint8_t* live, uint64_t n,
                               void (*fn)(void* ctx, uint64_t off, const uint8_t* bytes, uint64_t len), void* ctx);
/// (Triforce) and those parts' hashes (upload_same.h content_hash), a kept page's kept with its copy until other bytes are copied in
void memory_hash_as_submitted(uint64_t guest, const uint8_t* live, uint64_t n,
                              void (*fn)(void* ctx, uint64_t off, uint64_t len, uint64_t hash), void* ctx);
void memory_drop_shadow(uint64_t guest, uint64_t size);   // (a write the capture did not take: the copies go)
/// (EvilBoyce) the newest submission value whose write-back reaches into [guest, guest + size) (0: none ever); *ever set
/// when any write-back ever did
uint64_t memory_writeback_value(uint64_t guest, uint64_t size, bool* ever);
/// ((Triforce, THREAD-25) page_marks.h, no lock) false: no write-back ever reached a page of the range: *ever above is false
bool memory_writeback_marked(uint64_t guest, uint64_t size);
void memory_note_readback(uint64_t guest, uint64_t size);   // (PR 430) a CPU read of GPU results: see memory_rb_refresh
/// (Triforce) around the write of an NVN event's word by a command buffer's signal: its write-back is not one the captures of
/// its page wait for (vk_memory.cpp). This thread's bindings while on
void memory_bind_event_write(bool on);
bool memory_rb_refresh(VkCommandBuffer up);
void memory_rb_recording_begun();   // (hookshot) at a recording's start, on its thread: the submission it joins (memory_rb_refresh)
void memory_rb_segments_begin(uint64_t base, uint64_t n);   // (and a parallel replay's segments: their order, base on)
/// (hookshot) a range a program may write in the mirror that is not bound as written (not copied back): memory_rb_refresh
void memory_note_gpu_write(uint64_t gpu, uint64_t size);
/// ((Triforce) RX_VK_UB_SNAPSHOT's guard, vk_memory.cpp) the GPU writes this thread's recordings have noted that guest memory
/// may not have yet: the submission being recorded's, in all its parts, and earlier submissions' until the GPU has done them.
/// Begun at a submission's start (not at a part's); asked by uniform_range for a uniform range (0 none, 1 in the submission
/// being recorded, 2 in an earlier one the GPU has not done)
void memory_gpu_writes_begin();
int memory_gpu_written(uint64_t guest, uint64_t size);
bool memory_gpu_writes_any();
/// (vk_draw.cpp) whether uniform buffers are copied into the stream as submitted (RX_VK_UB_SNAPSHOT; every Intel GPU)
bool uniform_snapshot_on();
/// (vk_replay.cpp) The GPU's progress on the recordings' timeline, and a wait for it to reach v
uint64_t vk_timeline_completed();
/// (vk_replay.cpp) The value the timeline reaches only after every recording made so far is done on the GPU (0: never)
uint64_t vk_retirement_value();
bool memory_direct_wb();   // ((Triforce) vk_memory.cpp: RX_VK_DIRECT_WB=1, off unless set)
/// (vk_replay.cpp) The renderer cannot go on: its FATAL line, the host's log written out, the process ended (exit code 3)
[[noreturn]] void vk_fatal(const char* why);
void vk_timeline_wait(uint64_t v);
/// ((Triforce, 11-22, the performance audit's SYNC-122) the same wait for a caller other than a capture's take: who is
/// wb_rec_wait.h's Caller (1 a read of a page put off, 2 a binding of one); its held part is counted under it
void vk_timeline_wait_from(uint64_t v, int who);
// ((Triforce) RX_VK_LATE_QUEUE: the highest timeline value on the queue; a wait for a sent one (no flush; false: not reached in 1 s);
// the late pages' fixes applied (dev.present_mu held; queue_flush_locked does it first); vk_memory.cpp's side
uint64_t vk_timeline_signal_sent();
bool vk_timeline_wait_sent(uint64_t v);
void late_fix_flush_locked();
void vk_late_queue_stats(int64_t* waits, int64_t* wait_ns, int64_t* timeouts);
uint64_t memory_late_fix_pending();
void memory_late_fix_apply(uint64_t done);
/// ((Triforce, wp20) of this thread's last vk_timeline_wait, the part after the writer's recording was done (ns): wb_rec_wait.h)
int64_t vk_timeline_wait_held_last();
WriteGen memory_generation();
WriteGen memory_generation_any_thread();   // ((Triforce, 11-22, MEM-85) the same, read with an atomic load: from a thread that makes none)
uintptr_t memory_stamp_who(uint64_t guest, WriteGen* gen, uintptr_t* anchor);   // (RX_VK_STAMP_SRC: who wrote that page last)
/// 1: a page of [guest, guest + size) was written after generation gen; 0: none was
bool memory_written_since(uint64_t guest, uint64_t size, WriteGen gen);
void memory_stamp(uint64_t guest, uint64_t size);   // a write the watch does not see (GPU writes, host writes)
/// (RX_VK_CAP_ONLY_GPU) a present: the capture's per-frame counts logged every 10 s (vk_memory.cpp)
void memory_cap_present();
/// The page runs of [guest, guest + size) written after gen, as byte ranges from guest (appended to out)
void memory_written_runs(uint64_t guest, uint64_t size, WriteGen gen, std::vector<std::pair<uint64_t, uint64_t>>& out, bool tex = false);
uint64_t memory_pages_collected();                  // (statistics)

/// An NVN format as Vulkan stores it (vk_formats.cpp): ASTC is decoded to RGBA8, block_w x block_h
/// Bytes per block and block size of an NVN format (ASTC blocks are 16 bytes)
int nvn_block_size(int format, int* bw, int* bh);

struct VkFormatInfo {
    VkFormat format;
    bool astc;
    int block_w, block_h;
};
VkFormatInfo vk_format(int nvn_format);
bool is_depth_format(VkFormat f);
bool has_stencil(VkFormat f);

// device memory (vk_vma.cpp, Vulkan Memory Allocator)
bool vma_init(PFN_vkGetInstanceProcAddr gipa);
/// ((Triforce, 11-22, the performance audit's TEX-47, after Source A's) RX_VK_MEMORY_PRIORITY's tiers where the device has
/// VK_EXT_memory_priority (dev.memory_priority), else none: memory_priority.h. First asked once the device is made
const memory_priority::Tiers& memory_tiers();
extern uint64_t test_card_ballast;   // (vk_vma.cpp, RX_VK_TEST_CARD_MB: 0 outside that lab test)
/// (vk_memory.cpp) The card's video memory in bytes: its largest device-local heap, less RX_VK_TEST_CARD_MB's ballast
uint64_t device_vram_bytes();
void vma_blocks_ahead_check();   // (vk_vma.cpp: the blocks made ahead given back while VRAM is short; every 600 presents)
/// (Triforce) What an image of this create info needs (size, alignment, memory types), without making one; false where the
/// driver cannot say or the image must have memory of its own (vkGetDeviceImageMemoryRequirements, Vulkan 1.3)
bool image_requirements(const VkImageCreateInfo& ci, VkMemoryRequirements* mr);
/// An image's requirements, asked of the driver once however often they are read (vk_texture.cpp create: the take by size, the
/// size class and create_image's check of the render targets' pools' memory type)
struct ImageNeed {
    const VkImageCreateInfo* ci;
    VkMemoryRequirements mr{};
    int8_t asked = -1;
    const VkMemoryRequirements* get() {
        if (asked < 0) asked = image_requirements(*ci, &mr) ? 1 : 0;
        return asked > 0 ? &mr : nullptr;
    }
};
/// (textures: from the textures' own pool, the one image_compact_* moves allocations in: vk_texture.cpp's compaction; need: the
/// image's requirements where the caller asked already, read for the render targets' pools' memory type)
bool create_image(const VkImageCreateInfo& ci, VkImage& image, VmaAllocation& allocation, bool dedicated = false, bool target = false,
                  bool textures = false, ImageNeed* need = nullptr);
// ((Triforce, RX_VK_TARGET_REUSE_MEMORY) a render target's image on the memory of a pooled one: vk_texture.cpp pool_take_memory)
/// What target_pool::fits reads of an allocation: its size, its offset in its memory object, its memory type, and whether it is
/// to be taken as memory of its own (anything but a share of the render targets' blocks, which create_image tags)
bool allocation_fit_info(VmaAllocation allocation, uint64_t* bytes, uint64_t* offset, uint32_t* memory_type, bool* dedicated);
/// The size of the render targets' blocks (RX_VK_TARGET_BLOCK_MB): an image larger is not in them
uint64_t target_block_bytes();
/// The memory types in VRAM (DEVICE_LOCAL), as a mask
uint32_t device_local_types();
/// A render target of the pooled kind on an allocation of its size class (target_pool::class_bytes) in the targets' blocks, so a
/// later image of the class fits it; false where it cannot be (no pool, over a block, a small target, refused: made as before)
bool create_image_in_class(ImageNeed& need, VkImage& image, VmaAllocation& allocation);
/// A new image bound at the start of an allocation another image held (vmaCreateAliasingImage); that one must be past its last
/// use. The allocation stays the caller's: destroy_image frees it with the new image
bool create_aliasing_image(const VkImageCreateInfo& ci, VmaAllocation allocation, VkImage& image);
// (hookshot) the textures' pool compacted: VMA's defragmentation, a pass at a time (vk_texture.cpp's compact_step)
struct ImageMove {
    VmaAllocation src;   // (the allocation to move: it stays the texture's, and points at the new place once the pass ends)
};
/// The free space inside the textures' pool's blocks, and what the blocks hold in all; false without the pool
bool textures_pool_usage(uint64_t* block_bytes, uint64_t* free_bytes);
bool target_floor_kept();   // (the render targets' pool keeps a floor of blocks for the session: RX_VK_TARGET_FLOOR_MB)
bool image_compact_begin(uint64_t max_bytes_a_pass, uint32_t max_moves_a_pass);
bool image_compact_active();
/// A pass begun: the moves VMA asks for. False: nothing left to move, the compaction is over (then *freed_bytes and
/// *freed_blocks say what went back to the driver in all)
bool image_compact_pass(std::vector<ImageMove>& moves, uint64_t* freed_bytes, uint32_t* freed_blocks);
/// The new image of move i bound at its new place; false: not bound (the caller destroys the image and ignores the move)
bool image_compact_bind(size_t i, VkImage image);
void image_compact_ignore(size_t i);
/// The pass ended (its old images destroyed by the caller, nothing of the pool freed since it began). False: that was
/// the last one; then *freed_bytes and *freed_blocks say what went back to the driver in all
bool image_compact_pass_end(uint64_t* freed_bytes, uint32_t* freed_blocks);
void destroy_image(VkImage image, VmaAllocation allocation);
/// What an allocation really takes (VkMemoryRequirements.size: padding, alignment, the driver's metadata), 0 for none
uint64_t allocation_size(VmaAllocation allocation);
/// (dedicated: its own memory object, not a share of a 64 MB block: for the 16 to 32 MB ones that fit two to a block and leave
/// the rest of it free; RX_VK_BLOCK_BUFFERS=1: as before)
bool create_buffer(uint64_t size, VkBufferUsageFlags usage, bool host_visible, VkBuffer& buffer,
                   VmaAllocation& allocation, void** mapped, bool dedicated = false);
void destroy_buffer(VkBuffer buffer, VmaAllocation allocation);
/// A buffer in VRAM only (within the driver's budget), or false
bool create_device_buffer(uint64_t size, VkBufferUsageFlags usage, VkBuffer& buffer, VmaAllocation& allocation, bool dedicated = false);
/// (Triforce) device memory for a piece of a sparse buffer, and its release (vk_vma.cpp)
bool vma_piece_alloc(uint64_t size, uint64_t alignment, uint32_t type_bits, VmaAllocation& allocation, VkDeviceMemory& memory,
                     uint64_t& offset);
void vma_piece_free(VmaAllocation allocation);
/// (Triforce) the mirrors' pieces made resident in this recording, bound before it is submitted (vk_memory.cpp)
void memory_mirror_binds_flush();
bool memory_mirror_bind_wait(VkSemaphoreSubmitInfo* wait);   // (and the wait a queue submission makes for those binds)
/// (Triforce, vk_memory.cpp) The memory handling played on NVIDIA cards only (mirrors in pieces, compacted textures): on there,
/// and on trial on a card of another make until triforce_memtrial.txt says it passed or failed. tick: at the 600th presents;
/// device_lost: from device_lost(). used: a part's first real use (a piece of a mirror bound, a texture made in the compacted
/// pool): a session counts for the trial only once the handling runs in it, and passes once all of it has run for the trial's time
enum MemoryTrialPart { MEMTRIAL_PIECES, MEMTRIAL_COMPACT, MEMTRIAL_PARTS };
bool memory_trial_on();
void memory_trial_used(MemoryTrialPart part);
void memory_trial_refused(MemoryTrialPart part);   // (a part this card has could not be made: the trial does not wait for it)
void memory_trial_tick();
void memory_trial_device_lost();
void memory_trial_orderly_end();   // (the menu's Restart and Exit: no verdict for a session ended on purpose)
/// (Triforce) Set while the start's own shader work runs (vk_main.cpp started_up): a fault in the driver then starts the game
/// again (vk_draw.cpp driver_fault_restart, Windows)
extern std::atomic<bool> startup_work_on;
/// Device-local memory this process uses and what the driver allows it now (VK_EXT_memory_budget), summed over the
/// device-local heaps; false when unknown
bool vram_usage(uint64_t* used, uint64_t* budget, uint64_t* block_free = nullptr);
/// vram_usage asked of the driver now (VMA asks again for a new frame index), for the status line; false when the driver
/// gives no budget (VK_EXT_memory_budget): used is then the game's own allocations
bool vram_usage_now(uint64_t* used, uint64_t* budget);
void vma_log_heaps();
void vma_log_image_blocks();   // (the image pools' blocks: what they hold, and their free ranges)
PFN_vkGetInstanceProcAddr instance_proc();   // vk_main.cpp

bool create_swapchain(uint32_t width, uint32_t height);
/// (Triforce, 11-22, the performance audit's PRESENT-45, after Source A's; vk_main.cpp, surface_lost.h) A result of an
/// acquire, a present or a swapchain's creation is a lost surface that is recovered from: VK_ERROR_SURFACE_LOST_KHR, with
/// RX_VK_SURFACE_RECOVER on (unless =0) and no DLSS frame generation
bool surface_recover(VkResult result);
/// ...and what hangs on the lost surface let go, the surface last (dev.present_mu held; no present in hand on the present
/// thread): the next create_swapchain makes a surface for the window again
void invalidate_lost_surface();
bool replay_start();                          // vk_replay.cpp
bool precompile_wanted();                     // vk_draw.cpp
void precompile_run(void (*progress)(size_t done, size_t total));
void texture_pipelines_unprepared();         // ((Triforce) vk_draw.cpp: no precompile: the cache read, the converters made)
VkResult shared_cache_compute(const VkComputePipelineCreateInfo* ci, VkPipeline* out);   // (vk_draw.cpp: through that cache)
/// (vk_draw.cpp) One of the renderer's own compute pipelines made with no cache; asked once more without the driver's
/// optimizer where the driver refuses the optimized build (compute_plain_wanted)
VkResult bare_compute_pipeline(const VkComputePipelineCreateInfo* ci, VkPipeline* out);
void texture_pipelines_warm();                // ((Triforce) vk_texture.cpp: the texture converters' pipelines, before the game)
bool prepare_run(void (*progress)(size_t done, size_t total), bool background);
bool pcache_carry_rebuild();   // ((Triforce) after prepare_run: the carried pipeline cache over its cap, a fresh one: pcache_carry.h)
void pcache_carry_done();      // ((Triforce) the preparation gone through and saved: a carried history no longer open: pcache_carry.h)
bool prepare_is_update();
void prepare_background();
void state_list_run();                        // (an update: the state list's pipelines noted before precompile_run)
void predict_background();   // (Triforce: the predicted pipelines predict_run did not get to, built behind the game)
void frame_shown_note(int draws);   // (Triforce, 11-14: a frame was shown with this many draws; the builder rests in play)
void predict_plan_ensure();  // (Triforce: its plan, made before the precompile when an older build prepared this install)
void predict_run(void (*progress)(size_t done, size_t total));   // (after a prepare_run that prepared: the notes' predictions)
bool predict_before_title(bool prepared);   // ((Triforce, 11-24) whether predict_run runs now: Compile shaders, compile_level.h)
/// ((Triforce, 11-24, vk_draw.cpp) The --prepare-shaders run's journal (prepare_journal.h): an entry has been inside the driver
/// for longer than one gets, and its line is written: the run ends with prepare_journal::kExitEntryLimit (vk_main.cpp)
bool prepare_journal_overdue();
/// ((Triforce, 11-24, vk_draw.cpp) A run started again past a shader the run before died in (--prepare-from): the run before
/// is taken off the precompile's crash markers
void prepare_restart_forgive();
/// (hookshot) The window was closed while the shaders were prepared: prepare_run and precompile_run take nothing more and return,
/// what is done kept (the program cache, the driver's) and not counted as a start that ended inside them
void prepare_stop();
bool prepare_stopped();
/// ((Triforce, 11-22, PIPE-23) Whether this start only prepares the shaders and plays no game (vk_main.cpp prepare_only): its
/// end saves the pipeline cache itself, so the precompile's end leaves that to it (vk_draw.cpp precompile_end_save)
bool prepare_only_start();
/// What prepare_run is doing, for the start-up screen: 0 the shaders translated, 1 the graphics driver's part of them
int prepare_pass();
/// Whether prepare_run has that second pass at all here (off unless the stage libraries are switched on): the screen's steps
bool prepare_compiles();
void fill_replay_table(MkwVkRenderer& t);     // vk_replay.cpp

} // namespace mkwvk

// ---- a scoped timer per phase of the replay (logged per frame with the frame statistics) ----
namespace mkwvk {
enum ProfPhase { PROF_SUBMIT, PROF_PRESENT, PROF_DRAW, PROF_DESC, PROF_TEXGET, PROF_UPLOAD, PROF_PIPE, PROF_PROGRAM,
                 PROF_CMDS, PROF_DISPATCH, PROF_MEMSYNC, PROF_QSUBMIT, PROF_SLOTWAIT, PROF_COUNT };
extern int64_t prof_ns[PROF_COUNT];
/// Nanoseconds from a performance-counter reading. An integer number of nanoseconds per tick is a multiply, so a
/// reading past 2^53 does not lose its low bits the way the double divide does.
inline int64_t perf_ticks_to_ns(int64_t ticks, int64_t freq) {
    if (freq > 0 && 1000000000LL % freq == 0)
        return ticks * (1000000000LL / freq);
    if (freq <= 0) return 0;
    return (int64_t)((double)ticks * 1e9 / (double)freq);
}
// A cheap nanosecond clock for the per-phase replay timers. Ten QueryPerformanceCounter reads a draw were ~4% of
// the GPU thread (gpu/render/rx_internal.h). The hot path reads the invariant TSC; the counter calibrates the scale once.
inline int64_t prof_now() {
#if defined(HOOKSHOT_RDTSC)
    struct Scale { double ns_per; bool ok; };
    static const Scale scale = [] {
        LARGE_INTEGER f, a, b;
        QueryPerformanceFrequency(&f);
        const uint64_t c0 = HOOKSHOT_RDTSC();
        QueryPerformanceCounter(&a);
        volatile int sink = 0;
        for (int i = 0; i < 400000; i++) { HOOKSHOT_PAUSE(); sink += 1; }
        const uint64_t c1 = HOOKSHOT_RDTSC();
        QueryPerformanceCounter(&b);
        const int64_t dns = perf_ticks_to_ns(b.QuadPart - a.QuadPart, f.QuadPart);
        Scale s;
        s.ok = c1 > c0 && dns > 0 && sink > 0;
        s.ns_per = s.ok ? (double)dns / (double)(c1 - c0) : 0.0;
        return s;
    }();
    if (scale.ok) return (int64_t)((double)HOOKSHOT_RDTSC() * scale.ns_per);
#endif
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    static const int64_t freq = [] { LARGE_INTEGER f; QueryPerformanceFrequency(&f); return f.QuadPart; }();
    return perf_ticks_to_ns(t.QuadPart, freq);
}
// (hookshot) The per-draw phases (PROF_HOT) run a few thousand times a frame, and each timer is two counter reads: ~25k
// reads a frame were ~2% of the replay thread. One draw in eight is timed, picked at random per thread, and counted eight
// times: the outermost PROF_HOT on the thread picks, and those nested in it follow, so a phase never reads more than the
// one around it. What is slow and rare inside (a program or pipeline made, a texture created or uploaded, a wait) is timed
// by PROF / PROF_EXACT and counted once as it is, sampled draw or not: the PROF_HOT scopes around it weigh only the rest.
// Every scope timed (prof_full): RX_VK_PROF_ALL=1, RX_VK_SLOW_LOG, and while RX_VK_BENCH replays its frame.
inline std::atomic<int> prof_full{getenv("RX_VK_PROF_ALL") || getenv("RX_VK_SLOW_LOG") ? 1 : 0};
struct ProfThread {
    uint32_t rng;    // (xorshift32, seeded at the thread's first pick)
    int open, k;     // (the PROF_HOT scopes open, and the outermost one's weight: 0 not timed)
    int64_t exact;   // (the nanoseconds PROF / PROF_EXACT timed on this thread so far)
};
inline constinit thread_local ProfThread prof_t{};
struct ProfScope {
    int phase;   // (-1: PROF_EXACT, no phase of its own)
    int64_t t0, x0;
    explicit ProfScope(int p) : phase(p), t0(prof_now()), x0(prof_t.exact) {}
    ~ProfScope() {
        const int64_t dt = prof_now() - t0;
        if (phase >= 0) prof_ns[phase] += dt;
        prof_t.exact = x0 + dt;   // (what was exact inside is part of dt: not counted twice)
    }
};
/// A thread's first state: splitmix64 of a counter, so the threads' sequences are unrelated; never 0, xorshift's fixed point
inline uint32_t prof_seed() {
    static std::atomic<uint64_t> threads{0};
    uint64_t z = (threads.fetch_add(1, std::memory_order_relaxed) + 1) * 0x9E3779B97F4A7C15ull;
    z = (z ^ z >> 30) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ z >> 27) * 0x94D049BB133111EBull;
    return (uint32_t)((z ^ z >> 31) >> 32) | 1u;
}
inline int prof_pick(ProfThread& t) {   // (the weight: 8 one time in eight, else 0; 1 when every scope is timed)
    if (prof_full.load(std::memory_order_relaxed)) return 1;
    if (!t.rng) t.rng = prof_seed();
    t.rng ^= t.rng << 13, t.rng ^= t.rng >> 17, t.rng ^= t.rng << 5;
    return t.rng >> 29 ? 0 : 8;   // (the top bits: xorshift's low ones are its weakest)
}
struct ProfScopeHot {
    int phase, k;
    int64_t t0, x0;
    explicit ProfScopeHot(int p) : phase(p) {
        ProfThread& t = prof_t;
        if (!t.open++) t.k = prof_pick(t);
        k = t.k, x0 = t.exact, t0 = k ? prof_now() : 0;
    }
    ~ProfScopeHot() {
        ProfThread& t = prof_t;
        const int64_t x = t.exact - x0;   // (timed exactly inside: once, as it is)
        if (k) prof_ns[phase] += (prof_now() - t0 - x) * k + x;
        else if (x) prof_ns[phase] += x;
        t.open--;
    }
};
} // namespace mkwvk
#define PROF(phase) ::mkwvk::ProfScope prof_scope_##phase(::mkwvk::phase)
#define PROF_HOT(phase) ::mkwvk::ProfScopeHot prof_scope_##phase(::mkwvk::phase)   // (the per-draw phases: sampled, above)
#define PROF_EXACT() ::mkwvk::ProfScope prof_scope_exact(-1)   // (a slow, rare path inside them: timed exactly, above)
