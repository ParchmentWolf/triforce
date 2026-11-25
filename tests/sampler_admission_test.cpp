#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <condition_variable>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <exception>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace fixture {
enum Cache { None = -1, Owner, Seen, Mine, Failure, Alias, Retire };
std::atomic<int> fail_cache{None};
std::atomic<unsigned> allocation_faults{0};
template<class T, int Tag> struct FaultAllocator : std::allocator<T> {
    using value_type = T;
    FaultAllocator() = default;
    template<class U> FaultAllocator(const FaultAllocator<U, Tag>&) {}
    template<class U> struct rebind { using other = FaultAllocator<U, Tag>; };
    T* allocate(size_t n) {
        int expected = Tag;
        if (fail_cache.compare_exchange_strong(expected, None)) { allocation_faults++; throw std::bad_alloc(); }
        return std::allocator<T>{}.allocate(n);
    }
};
template<class K, class V, int Tag, class H = std::hash<K>> using FaultMap = std::unordered_map<K, V, H, std::equal_to<K>, FaultAllocator<std::pair<const K, V>, Tag>>;
template<class K, int Tag> using FaultSet = std::unordered_set<K, std::hash<K>, std::equal_to<K>, FaultAllocator<K, Tag>>;
template<class T, int Tag> using FaultVector = std::vector<T, FaultAllocator<T, Tag>>;
/* PARAMS */
/* ENUMS */
struct {
    VkDevice device{}; VkPhysicalDeviceProperties props{}; VkPhysicalDeviceFeatures features{};
    bool custom_border_color = false;
} dev;
std::mutex replay_mu;
struct ParLock { std::lock_guard<std::mutex> lock; ParLock() : lock(replay_mu) {} };
std::atomic<uint64_t> generation{1};   // (sampler_registrations_generation: a registration, the bias, or the book moved it)
uint64_t frame_no = 1;
bool lod_per_id = false;   // (the limit cases: each id its own sampler, by its base level)
unsigned creates = 0, destroyed = 0;
VkResult create_result = VK_SUCCESS;
bool garbage = false, arm_owner_commit = false, arm_failure_commit = false, cache_off = false;
std::string policy;
std::string descriptor_policy;
float registration_lod_max = 8;
struct Saved {
    VkSamplerCreateInfo ci{};
    bool custom = false, reduced = false;
    VkSamplerReductionMode reduction{};
    float border[4]{};
};
std::unordered_map<VkSampler, Saved> live;
uint64_t mix(uint64_t a, uint64_t b) { return (a ^ b) * 0x9e3779b97f4a7c15ull; }
uint64_t texture_frame_no() { return frame_no; }
bool sampler_cache_on() { return !cache_off; }
uint64_t sampler_registrations_generation() { return generation; }
uint32_t sampler_slot_version(int) { return (uint32_t)generation; }
bool sampler_of(int id, nvn_samp_par* p) {
    if (id < 0) return false;
    *p = {};
    p->minf = NVN_MIN_FILTER_LINEAR_MIPMAP_LINEAR; p->magf = NVN_MAG_FILTER_LINEAR;
    p->aniso = 1; p->lod_max = registration_lod_max; p->lod_bias = id * 0.25f;
    if (policy == "nearest" || policy == "force-linear" || policy.find("compare") == 0) p->minf = NVN_MIN_FILTER_NEAREST, p->magf = NVN_MAG_FILTER_NEAREST;
    if (policy == "linear") p->minf = NVN_MIN_FILTER_LINEAR;
    if (policy == "compare-explicit") p->cmp_mode = 1, p->cmp_func = 1;
    if (policy == "custom-border" || policy == "custom-reduction") { p->border[0] = 0.25f; p->border[1] = 0.5f; p->border[2] = 0.75f; p->border[3] = 1; }
    if (policy == "standard-border") std::fill(std::begin(p->border), std::end(p->border), 1.0f);
    if (policy == "reduction" || policy == "compare-reduction" || policy == "custom-reduction") p->reduction = 1;
    if (policy == "wrap") p->ws = NVN_WRAP_MODE_REPEAT, p->wt = NVN_WRAP_MODE_MIRRORED_REPEAT, p->wr = NVN_WRAP_MODE_CLAMP_TO_BORDER;
    // ((Triforce, 11-18) anisotropy is raised only on samplers whose U and V repeat (EstebanGGM's aniso_tiled): a tiled one, and
    // a clamped one that stays as the game has it)
    if (policy == "anisotropy") p->ws = NVN_WRAP_MODE_REPEAT, p->wt = NVN_WRAP_MODE_MIRRORED_REPEAT;
    if (policy == "lod-clamp") p->lod_bias = 100, p->lod_min = -3, p->lod_max = -1;
    // ((Triforce, v0.5.2) the anisotropy only where U and V repeat: a clamped one (anisotropy-clamped) reads a screen buffer
    if (policy == "anisotropy") p->ws = NVN_WRAP_MODE_REPEAT, p->wt = NVN_WRAP_MODE_MIRRORED_REPEAT;
    if (policy == "limit-reuse") {   // (keys apart only in what no sample reaches share a sampler; 3, 5 and 6 sample otherwise)
        p->minf = NVN_MIN_FILTER_NEAREST, p->magf = NVN_MAG_FILTER_NEAREST, p->lod_bias = 0;
        if (id == 1) p->border[0] = 0.5f, p->border[3] = 1;   // (a custom border colour no address mode clamps to)
        if (id == 2) p->aniso = 4;      // (anisotropy on a device without anisotropic filtering: Vulkan ignores it)
        if (id == 3) p->cmp_func = 3;   // (a comparison the sampler is not enabled for: kept, a driver may compare anyway)
        if (id == 4) p->lod_max = 2;    // (no mip filter: the base level only, whatever the range)
        if (id >= 5) p->ws = NVN_WRAP_MODE_CLAMP_TO_BORDER, p->border[0] = id == 5 ? 0.5f : 0.25f, p->border[3] = 1;
    }
    if (lod_per_id) p->lod_bias = 0, p->lod_min = id / 64.0f;
    return true;
}
const char* getenv(const char* name) {
    if (!std::strcmp(name, "RX_VK_PUSH_STATE_OLD") && descriptor_policy == "descriptor-old") return "1";
    if (!std::strcmp(name, "RX_VK_PUSH_ALL") && descriptor_policy == "descriptor-whole") return "1";
    if (!std::strcmp(name, "RX_VK_SAMPLER_CACHE") && cache_off) return "0";
    if (!std::strcmp(name, "RX_VK_SHADOW_PCF") && policy == "compare-pcf-off") return "0";
    if (!std::strcmp(name, "RX_VK_ANISO") && policy.find("anisotropy") == 0) return "16";
    if (!std::strcmp(name, "RX_VK_FORCE_LINEAR") && policy == "force-linear") return "1";
    return nullptr;
}
void logf(const char*, ...) {}
// (sampler reuse) The recordings' timeline: the value the GPU reached, and the one the recording being made will signal, which
// vk_replay.cpp's vk_retirement_value gives (a signal after every recording made so far)
uint64_t gpu_done = 0, next_signal = 1;
uint64_t vk_timeline_completed() { return gpu_done; }
uint64_t vk_retirement_value() { return next_signal; }
void sampler_bias_changed() { generation++; }   // (vk_bank.cpp: moves sampler_registrations_generation)
unsigned limit_failures = 0;   // (creations the driver refused for its maxSamplerAllocationCount, as NVIDIA's does)
std::unordered_map<VkSampler, uint64_t> last_use;   // (the recording that last took each sampler, by use() below)
struct Saved;
extern std::unordered_map<VkSampler, Saved> live;
size_t live_count();
VkResult vkCreateSampler(VkDevice, const VkSamplerCreateInfo* ci, const VkAllocationCallbacks*, VkSampler* out) {
    creates++;
    *out = garbage ? reinterpret_cast<VkSampler>(uintptr_t(0xdead)) : VK_NULL_HANDLE;
    const uint32_t most = dev.props.limits.maxSamplerAllocationCount;   // (0: the other cases' device, no limit modelled)
    if (most && live_count() >= most) { limit_failures++; return VK_ERROR_OUT_OF_DEVICE_MEMORY; }
    if (create_result != VK_SUCCESS) {
        if (arm_failure_commit) { arm_failure_commit = false; fail_cache = Failure; }
        return create_result;
    }
    *out = reinterpret_cast<VkSampler>(uintptr_t(100 + creates));
    Saved saved; saved.ci = *ci; saved.ci.pNext = nullptr;
    for (auto* next = static_cast<const VkBaseInStructure*>(ci->pNext); next; next = next->pNext) {
        if (next->sType == VK_STRUCTURE_TYPE_SAMPLER_CUSTOM_BORDER_COLOR_CREATE_INFO_EXT) {
            auto* border = reinterpret_cast<const VkSamplerCustomBorderColorCreateInfoEXT*>(next);
            saved.custom = true; std::copy(std::begin(border->customBorderColor.float32), std::end(border->customBorderColor.float32), saved.border);
        }
        if (next->sType == VK_STRUCTURE_TYPE_SAMPLER_REDUCTION_MODE_CREATE_INFO) {
            saved.reduced = true; saved.reduction = reinterpret_cast<const VkSamplerReductionModeCreateInfo*>(next)->reductionMode;
        }
    }
    live.emplace(*out, saved);
    // Arm after the resource exists: target the operation, not an STL-dependent nth allocation.
    if (arm_owner_commit) { arm_owner_commit = false; fail_cache = Owner; }
    return VK_SUCCESS;
}
size_t live_count() { return live.size(); }
void vkDestroySampler(VkDevice, VkSampler sampler, const VkAllocationCallbacks*) {
    if (!sampler) return;   // (Vulkan permits null destruction; a non-null error output is still undefined)
    if (auto u = last_use.find(sampler); u != last_use.end()) {   // (destroyed only once the GPU is past every recording that took it)
        assert(u->second <= gpu_done); last_use.erase(u);
    }
    assert(live.erase(sampler) == 1); destroyed++;   // (not undefined error output or an already-owned sampler)
}
struct { int aniso = 0; } opts;   // (the Texture filtering row: off, the game's own)
/* ACTUAL */

struct Program { bool push = true; VkPipelineLayout layout{}; VkDescriptorSetLayout set_layout{}; uint32_t renodx = 0, frag_crc = 0; };
struct DescriptorWrites { std::vector<VkWriteDescriptorSet> writes; } descriptor_writes;
DescriptorWrites& dw() { return descriptor_writes; }
std::atomic<bool> renodx_tracing{false};   // (the RenoDX port's set 1: none here)
void renodx_bind(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t) {}
void renodx_trace_draw(uint32_t) {}
// (Triforce, vk_draw.cpp: the descriptors' counts, and the set path's kept set and update template, which tests/test_desc_sets.py
// runs; here a set is allocated and written whole each time, as before)
std::atomic<int64_t> st_push_full{0}, st_push_full_n{0}, st_push_delta{0}, st_push_delta_n{0}, st_push_none{0};
std::atomic<int64_t> st_set_new{0}, st_set_new_n{0}, st_set_again{0};
void count_add(std::atomic<int64_t>& c, int64_t n) { c += n; }
int64_t descs_of(const VkWriteDescriptorSet* w, size_t n) { int64_t k = 0; for (size_t i = 0; i < n; i++) k += w[i].descriptorCount; return k; }
VkDescriptorSet set_kept(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout) { return VK_NULL_HANDLE; }
bool set_write_template(VkDescriptorSet, const Program&) { return false; }
bool push_write_template(VkCommandBuffer, VkPipelineBindPoint, const Program&) { return false; }   // ((Triforce) the push template: tests/test_desc_sets.py)
void set_written(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, VkDescriptorSet) {}
struct Pushed;
std::array<Pushed, 2>& pushed();
struct Recording { VkDescriptorPool pool{}; std::vector<VkDescriptorPool> extra; } recording;
Recording* cur = &recording;
bool g_fine = false;
enum { FC_PUSH_FULL, FC_PUSH_WRITES, FC_PUSH_DESCS, FC_PUSH_DELTA, FC_POOL_SETS, FC_POOL_DESCS };
int64_t fine_n[6]{};
#define FINE_SCOPE(x) (void)0
#define FINE_N(x, n) (void)0
unsigned descriptor_allocs = 0, descriptor_updates = 0, descriptor_binds = 0, descriptor_pushes = 0;
void check_writes(uint32_t n, const VkWriteDescriptorSet* writes) {
    for (uint32_t i = 0; i < n; i++)
        if (writes[i].descriptorType == VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER)
            for (uint32_t k = 0; k < writes[i].descriptorCount; k++)
                assert(live.count(writes[i].pImageInfo[k].sampler));
}
void vkCmdPushDescriptorSetKHR(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t, uint32_t n, const VkWriteDescriptorSet* writes) {
    check_writes(n, writes); descriptor_pushes++;
}
VkDescriptorPool make_pool() { return reinterpret_cast<VkDescriptorPool>(uintptr_t(11)); }
void pool_took(const VkWriteDescriptorSet*, size_t) {}   // ((Triforce, 11-22, DESC-33) vk_draw.cpp: the sets a recording took, counted)
void vkDestroyDescriptorPool(VkDevice, VkDescriptorPool pool, const VkAllocationCallbacks*) { assert(pool); }
VkResult vkAllocateDescriptorSets(VkDevice, const VkDescriptorSetAllocateInfo*, VkDescriptorSet* out) {
    descriptor_allocs++; *out = reinterpret_cast<VkDescriptorSet>(uintptr_t(12)); return VK_SUCCESS;
}
void vkUpdateDescriptorSets(VkDevice, uint32_t n, const VkWriteDescriptorSet* writes, uint32_t, const VkCopyDescriptorSet*) {
    check_writes(n, writes); descriptor_updates++;
}
void vkCmdBindDescriptorSets(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t, uint32_t, const VkDescriptorSet*, uint32_t, const uint32_t*) {
    descriptor_binds++;
}
/* DESCRIPTORS */
std::array<Pushed, 2>& pushed() { static std::array<Pushed, 2> state; return state; }

std::string route;
VkSampler get(int id = 0, bool compare = false, bool scene = false) {
    return route == "make" ? sampler_make(id, compare, scene) : sampler_for(id, compare, scene);
}
void valid(VkSampler sampler) { assert(sampler && live.count(sampler)); }
void retry(const std::string& test) {
    create_result = test == "host-oom" ? VK_ERROR_OUT_OF_HOST_MEMORY : test == "unknown" ? VK_ERROR_UNKNOWN : VK_ERROR_OUT_OF_DEVICE_MEMORY;
    garbage = test == "error-output";
    assert(!get()); assert(!get()); assert(creates == 1 && live.empty() && destroyed == 0);
    create_result = VK_SUCCESS;
    assert(!get()); assert(creates == 1);   // (bounded until a later present)
    frame_no++;
    if (test == "generation-retry") generation++;
    VkSampler next{};
    if (test == "thread-retry") { std::thread worker([&] { next = get(); }); worker.join(); }
    else next = get();
    valid(next); assert(creates == 2 && get() == next);
}
// (sampler reuse) A recording thread that lives through a whole case, as a parallel replay's segment workers do: its own tables
// (sampler_for's by id, sampler_make's mine) stay from one recording to the next
struct Worker {
    std::mutex m;
    std::condition_variable cv;
    std::function<void()> job;
    bool busy = false, quit = false;
    std::thread t{[this] {
        std::unique_lock l(m);
        for (;;) {
            cv.wait(l, [this] { return busy || quit; });
            if (quit) return;
            l.unlock(); job(); l.lock();
            busy = false; cv.notify_all();
        }
    }};
    void start(std::function<void()> f) { { std::lock_guard l(m); job = std::move(f); busy = true; } cv.notify_all(); }
    void join() { std::unique_lock l(m); cv.wait(l, [this] { return !busy; }); }
    ~Worker() { { std::lock_guard l(m); quit = true; } cv.notify_all(); t.join(); }
};
// A draw's sampler for id in the recording that will signal next_signal: checked under the replay's lock (the fake driver's tables
// change under it), its own key's (lod_per_id), and noted as used by that recording
VkSampler use(int id) {
    const VkSampler s = get(id);
    std::lock_guard g(replay_mu);
    valid(s); assert(live.at(s).ci.minLod == id / 64.0f);
    last_use[s] = next_signal;
    return s;
}
// A present, the GPU `behind` recordings behind the one made next
void present(uint64_t behind = 0) {
    frame_no++, next_signal++;
    gpu_done = next_signal > behind + 1 ? next_signal - 1 - behind : 0;
}
// The limit cases: a driver that makes at most 80 samplers, as NVIDIA's makes about 4000 (vkCreateSampler fails past it). The
// renderer's room is 60 of them (80 less a quarter for its other samplers), retiring from 45. vkDestroySampler above checks no
// sampler goes before the GPU is past the last recording that took it. (Triforce) What is retired is what no draw took for a
// whole frame (vk_draw.cpp sampler_book): the book asks which are in use by moving the samplers' generation, and waits two
// presents for the answer
bool limit_case(const std::string& test) {
    if (test == "limit") {   // (300 recordings on two threads, each drawing with 10 samplers every recording uses and 20 of a window
        // that moves 5 a recording: 1525 in all. The GPU 2 recordings behind)
        lod_per_id = true; dev.props.limits.maxSamplerAllocationCount = 80;
        Worker worker;
        size_t most = 0;
        for (uint64_t r = 0; r < 300; r++) {
            next_signal = r + 1, gpu_done = r ? r - 1 : 0;
            const auto draws = [r] {
                for (int id = 0; id < 10; id++) use(id);
                for (int id = 100 + 5 * (int)r; id < 120 + 5 * (int)r; id++) use(id);
            };
            worker.start(draws); draws(); worker.join();
            most = std::max(most, live.size());
            frame_no++;   // (a present)
        }
        // (each made once: none retired while recordings still drew with it, the 10 of every recording kept throughout; none
        // refused by the room or by the driver)
        assert(!limit_failures && creates == 1525 && most <= 60 && destroyed == creates - live.size() && destroyed > 1400);
        return true;
    }
    if (test == "limit-full") {   // (the room filled within one frame, the GPU stopped: nothing is known to be unused yet)
        lod_per_id = true; dev.props.limits.maxSamplerAllocationCount = 80;
        std::vector<VkSampler> first;
        for (int id = 0; id < 60; id++) first.push_back(use(id));
        assert(creates == 60 && destroyed == 0 && !limit_failures);
        assert(!get(60) && !get(60) && creates == 60 && !limit_failures);   // (none made past the room: the draw waits, as for a failure)
        // (the book asked which are in use before the room filled, in that same frame, when all of them were; two presents on it
        // asks again, the draws going on with 30 to 59)
        for (int k = 0; k < 3; k++) {
            present(8);
            assert(!get(60) && creates == 60 && destroyed == 0);
            for (int id = 30; id < 60; id++) assert(use(id) == first[id]);
        }
        present(8);
        // (two presents after that, 0 to 29 were not drawn with: 16 of them retired, the least recently resolved, but the GPU has them still)
        assert(!get(60) && creates == 60 && destroyed == 0 && live.size() == 60);
        present(0);   // (the GPU past every recording made)
        use(60);
        assert(destroyed == 16 && creates == 61 && live.size() == 45 && !limit_failures);
        for (int id = 30; id < 60; id++) assert(use(id) == first[id]);   // (those drawn with were never retired)
        assert(use(29) == first[29] && creates == 61);   // (the 16 retired were 0 to 15)
        assert(use(0) != first[0] && creates == 62);     // (a retired one's key made anew)
        return true;
    }
    if (test == "limit-reuse") {   // (keys apart only in what no sample reaches share one sampler; the others do not)
        policy = test; dev.features.samplerAnisotropy = VK_FALSE;
        const VkSampler s0 = get(0); valid(s0);
        assert(get(1) == s0 && get(2) == s0 && get(4) == s0 && creates == 1);
        const VkSampler s3 = get(3), s5 = get(5), s6 = get(6);
        valid(s3); valid(s5); valid(s6);
        assert(s3 != s0 && s5 != s0 && s6 != s0 && s5 != s6 && creates == 4 && live.size() == 4);
        assert(!live.at(s3).ci.compareEnable && live.at(s3).ci.compareOp == VK_COMPARE_OP_EQUAL);
        assert(live.at(s5).custom && live.at(s5).border[0] == 0.5f && live.at(s6).border[0] == 0.25f);
        return true;
    }
    if (test == "limit-alias-commit") {   // (the keys' table could not take a key: its sampler is found again by what it samples)
        fail_cache = Alias; const VkSampler s = get(); valid(s);
        assert(allocation_faults == 1 && get() == s && creates == 1 && destroyed == 0);
        return true;
    }
    if (test == "limit-retire-commit") {   // (no room to note a retirement: that sampler stays made, none lost or destroyed early)
        lod_per_id = true; dev.props.limits.maxSamplerAllocationCount = 80;
        for (int id = 0; id < 45; id++) use(id);   // (the book's first question on the way, when all of them were just made)
        present(); use(45);
        present(); for (int id = 20; id < 46; id++) use(id);
        use(46);   // (past the retiring point and none known unused: the book asks again; made meanwhile)
        present(); for (int id = 20; id < 47; id++) use(id);
        present(); for (int id = 20; id < 47; id++) use(id);
        assert(creates == 47 && destroyed == 0 && live.size() == 47);
        fail_cache = Retire; use(47);   // (0 to 19 were not drawn with for a frame; the first retirement cannot be noted)
        assert(allocation_faults == 1 && creates == 48 && destroyed == 0 && live.size() == 48);
        use(48); assert(creates == 49 && destroyed == 0 && live.size() == 49);   // (back to 44 made, then this one: 4 retired, the GPU's still)
        present(); use(49);   // (the GPU past them: destroyed; one more retired for this one)
        assert(destroyed == 4 && creates == 50 && live.size() == 45 + 1 && !limit_failures);
        return true;
    }
    if (test == "limit-held") {   // (Triforce) what a draw may still hold when its sampler is retired: all of it follows the generation
        lod_per_id = true; dev.props.limits.maxSamplerAllocationCount = 80;
        const VkSampler old0 = use(0);
        for (int id = 1; id < 45; id++) use(id);   // (the book's first question on the way)
        present(8); for (int id = 1; id < 45; id++) use(id);
        present(8); for (int id = 1; id < 45; id++) use(id);
        use(45);   // (at the retiring point, and every sampler resolved in or after the frame of that question: asked again)
        const uint64_t g0 = sampler_registrations_generation();
        present(8); for (int id = 1; id < 46; id++) use(id);
        present(8); for (int id = 1; id < 46; id++) use(id);
        assert(creates == 46 && sampler_registrations_generation() == g0);
        use(46);   // (0 was not drawn with for a frame: retired, though the GPU has not passed its recordings; 1 to 45 stay)
        assert(live.count(old0) && destroyed == 0 && creates == 47);
        // (a kept descriptor or a thread's table made before stands on a generation that is gone: kept_texture's now.samp,
        // sampler_for's e.gen, sampler_make's mine_gen)
        assert(sampler_registrations_generation() != g0);
        const VkSampler new0 = use(0);
        assert(new0 != old0 && live.count(old0) && creates == 48);   // (made anew, another handle, while the old one is the GPU's)
        for (int id = 1; id < 47; id++) use(id);
        assert(creates == 48);   // (none of those drawn with was retired)
        present(0); use(47);     // (the GPU past every recording that may hold it: destroyed)
        assert(!live.count(old0) && live.count(new0) && destroyed >= 1);
        return true;
    }
    return false;
}
void run(const std::string& test) {
    cache_off = route == "cache-off";
    dev.props.limits.maxSamplerLodBias = 16; dev.props.limits.maxSamplerAnisotropy = 8;
    dev.features.samplerAnisotropy = VK_TRUE; dev.custom_border_color = true;
    if (limit_case(test)) return;
    if (test.find("descriptor-") == 0) {
        descriptor_policy = test;
        recording.pool = make_pool();   // A live recording already owns its initial pool before binding.
        Program p; p.push = test != "descriptor-pool";
        p.layout = reinterpret_cast<VkPipelineLayout>(uintptr_t(20));
        const auto bp = test == "descriptor-compute" ? VK_PIPELINE_BIND_POINT_COMPUTE : VK_PIPELINE_BIND_POINT_GRAPHICS;
        const auto cmd = reinterpret_cast<VkCommandBuffer>(uintptr_t(21));
        auto first = get(); valid(first);
        VkDescriptorImageInfo images[2]{{first, {}, VK_IMAGE_LAYOUT_GENERAL}, {first, {}, VK_IMAGE_LAYOUT_GENERAL}};
        VkWriteDescriptorSet w{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
        w.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER; w.descriptorCount = 2; w.pImageInfo = images;
        dw().writes = {w};
        create_result = VK_ERROR_OUT_OF_DEVICE_MEMORY; images[1].sampler = get(1);
        assert(!images[1].sampler && !bind_descriptors(cmd, bp, p));
        assert(!descriptor_allocs && !descriptor_updates && !descriptor_binds && !descriptor_pushes);
        create_result = VK_SUCCESS; frame_no++; images[1].sampler = get(1); valid(images[1].sampler);
        assert(bind_descriptors(cmd, bp, p));
        auto before = pushed()[bp == VK_PIPELINE_BIND_POINT_COMPUTE];
        const auto allocs = descriptor_allocs, updates = descriptor_updates, binds = descriptor_binds, pushes = descriptor_pushes;
        create_result = VK_ERROR_OUT_OF_DEVICE_MEMORY;
        images[1].sampler = get(2); assert(!images[1].sampler);
        assert(!bind_descriptors(cmd, bp, p));
        assert(descriptor_allocs == allocs && descriptor_updates == updates && descriptor_binds == binds && descriptor_pushes == pushes);
        const auto& after = pushed()[bp == VK_PIPELINE_BIND_POINT_COMPUTE];
        assert(after.cmd == before.cmd && after.layout == before.layout && after.n == before.n && after.words == before.words && after.writes == before.writes && after.at == before.at);
        create_result = VK_SUCCESS; frame_no++; images[1].sampler = get(2); valid(images[1].sampler);
        assert(bind_descriptors(cmd, bp, p));
        assert(p.push ? descriptor_pushes == pushes + 1 : descriptor_updates == updates + 1 && descriptor_binds == binds + 1);
        // Storage images do not consume a sampler: their null sampler remains legal.
        dw().writes[0].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; images[0].sampler = images[1].sampler = VK_NULL_HANDLE;
        assert(bind_descriptors(cmd, bp, p));
        return;
    }
    if (test == "host-oom" || test == "device-oom" || test == "unknown" || test == "error-output" ||
        test == "generation-retry" || test == "thread-retry") { retry(test); return; }
    if (test == "independent") {
        create_result = VK_ERROR_OUT_OF_HOST_MEMORY; assert(!get()); create_result = VK_SUCCESS;
        auto second = get(1); valid(second); assert(creates == 2 && !get() && get(1) == second); return;
    }
    if (test == "owner-commit") {
        arm_owner_commit = true; assert(!get()); assert(live.empty() && destroyed == 1 && allocation_faults == 1);
        assert(!get() && creates == 1); frame_no++; valid(get()); assert(creates == 2); return;
    }
    if (test == "concurrent") {
        std::vector<std::thread> workers;
        for (int i = 0; i < 4; i++) workers.emplace_back([] { for (int j = 0; j < 50; j++) assert(get()); });
        for (auto& worker : workers) worker.join();
        assert(creates == 1 && live.size() == 1); return;
    }
    if (test == "seen-commit") {
        auto first = get(); valid(first);
        // A distinct ID forces the parameter acceleration insertion.
        // Use sampler_make directly to test this cache even when the outer ID table is bypassed.
        if (!cache_off) {
            fail_cache = Seen; auto next = sampler_make(1, false, false); valid(next); assert(allocation_faults == 1);
            assert(live.at(next).ci.mipLodBias == 0.25f && live.at(next).ci.maxLod == 8);
        } else valid(get(1));
        assert(destroyed == 0); return;
    }
    if (test == "mine-commit") {
        auto first = sampler_make(0, false, false); valid(first);
        fail_cache = Mine; assert(sampler_make(0, false, false) == first);
        assert(allocation_faults == 1 && creates == 1 && destroyed == 0 && live.size() == 1); return;
    }
    if (test == "valid-after-failure" || test == "failure-commit") {
        auto first = get(); valid(first); create_result = VK_ERROR_OUT_OF_DEVICE_MEMORY;
        arm_failure_commit = test == "failure-commit"; assert(!get(1)); assert(get() == first);
        create_result = VK_SUCCESS;
        if (test == "failure-commit") { assert(allocation_faults == 1 && !get(2) && creates == 2); }
        else valid(get(2));
        assert(!get(1)); frame_no++; valid(get(1)); assert(get() == first && destroyed == 0); return;
    }
    if (test == "registration") {
        auto first = get(); valid(first); generation++; registration_lod_max = 3;
        auto second = get(); valid(second); assert(second != first && creates == 2 && live.at(second).ci.maxLod == 3); return;
    }
    // ((Triforce, S8) the upscaler's texture LOD bias: added only for a draw into the jittered scene (scene), on a wrapping,
    // trilinear sampler; the other passes' sampler of the same id is its own, unbiased, and neither is taken for the other)
    if (test == "scene-bias" || test == "scene-clamped" || test == "scene-off") {
        policy = test == "scene-bias" ? "wrap" : "";
        upscale_lod_bias = test == "scene-off" ? 0.0f : -1.5f;
        const VkSampler other = get(4), scene = get(4, false, true);   // (id 4: the game's own bias 1)
        valid(other); valid(scene);
        assert(live.at(other).ci.mipLodBias == 1.0f);
        if (test == "scene-bias") {
            assert(scene != other && creates == 2 && live.at(scene).ci.mipLodBias == -0.5f);
            assert(get(4, false, true) == scene && get(4) == other && creates == 2);   // (each kept apart)
            assert(get(4, true, true) != scene);   // (a depth compare: never biased, another sampler)
            assert(live.at(get(4, true, true)).ci.mipLodBias == 1.0f && live.at(get(4, true)).ci.mipLodBias == 1.0f);
        } else   // (clamped, or no bias in use: the same sampler for both)
            assert(scene == other && creates == 1 && live.at(scene).ci.mipLodBias == 1.0f);
        return;
    }
    if (test == "shared-thread") {
        auto first = get(); valid(first); VkSampler other{};
        std::thread worker([&] { other = get(); }); worker.join();
        assert(other == first && creates == 1); return;
    }
    policy = test;
    const bool compare = test.find("compare") == 0;
    const int id = test == "unknown-id" ? -1 : 0;
    auto sampler = get(id, compare); valid(sampler);
    const auto& saved = live.at(sampler); const auto& ci = saved.ci;
    assert(get(id, compare) == sampler && creates == 1);
    if (test == "nearest") assert(ci.minFilter == VK_FILTER_NEAREST && ci.magFilter == VK_FILTER_NEAREST && ci.maxLod == 0.25f);
    if (test == "linear") assert(ci.minFilter == VK_FILTER_LINEAR && ci.maxLod == 0.25f);
    if (test == "unknown-id" || test == "force-linear") assert(ci.minFilter == VK_FILTER_LINEAR && ci.magFilter == VK_FILTER_LINEAR && ci.maxLod == 0.25f);
    if (test == "wrap") assert(ci.addressModeU == VK_SAMPLER_ADDRESS_MODE_REPEAT && ci.addressModeV == VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT && ci.addressModeW == VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_BORDER);
    if (test == "lod-clamp") assert(ci.mipLodBias == 16 && ci.minLod == 0 && ci.maxLod == 0);
    if (compare) {
        assert(ci.compareEnable && ci.compareOp == (test == "compare-explicit" ? VK_COMPARE_OP_NEVER : VK_COMPARE_OP_LESS_OR_EQUAL));
        assert(ci.minFilter == (test == "compare-pcf-off" ? VK_FILTER_NEAREST : VK_FILTER_LINEAR));
    }
    if (test == "custom-border" || test == "custom-reduction") assert(saved.custom && ci.borderColor == VK_BORDER_COLOR_FLOAT_CUSTOM_EXT && saved.border[0] == 0.25f && saved.border[3] == 1);
    if (test == "standard-border") assert(!saved.custom && ci.borderColor == VK_BORDER_COLOR_FLOAT_OPAQUE_WHITE);
    if (test == "reduction" || test == "custom-reduction") assert(saved.reduced && saved.reduction == VK_SAMPLER_REDUCTION_MODE_MIN);
    if (test == "compare-reduction") assert(!saved.reduced);
    if (test == "anisotropy") assert(ci.anisotropyEnable && ci.maxAnisotropy == 8);
    if (test == "anisotropy-clamped") assert(!ci.anisotropyEnable);
}
} // namespace fixture
int main(int argc, char** argv) {
    assert(argc == 3); fixture::route = argv[1]; fixture::run(argv[2]); return 0;
}
