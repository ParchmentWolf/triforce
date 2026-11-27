// The Vulkan back end's start: vulkan-1.dll, the instance, the device (Vulkan 1.3 and the extensions the NVN replay
// wants where the GPU has them: mesh shaders, host memory import, graphics pipeline libraries), the window's
// swapchain, and the rx_* table (vk_api.h). The NVN replay itself is vk_replay.cpp.
#include "vk_dlssg.h"
#include "vk_paths.h"
#include "cpu_count.h"   // ((Triforce, 11-22, OS-49) the threads to size by: HOS_SIM_CPU
#include "prepare_journal.h"   // ((Triforce, 11-24) kExitEntryLimit: the journalled preparation's exit status for one entry past its limit
#include "vk_loader.h"

#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <filesystem>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "vk_api.h"
#include "vk_draw.h"
#include "vk_framegen.h"
#include "vk_internal.h"
#include "gpu_choice.h"
#include "present_mode.h"   // (the swapchain's present mode: the VSync row and the switches)
#include "surface_lost.h"   // ((Triforce, 11-22, PRESENT-45) the window's surface lost: create_swapchain, invalidate_lost_surface)
#include "crash_markers.h"   // (mkwvk_close_asked: a close is not a crash)
#include "vk_menu.h"
#include "vk_dlss.h"
#include "vk_fsr4.h"
#include "vk_xess.h"   // ((Triforce) Intel XeSS's instance and device extensions and features, with its library beside the game)
#include "vk_reflex.h"
#include "vk_antilag.h"
#include "vk_progress.h"
#include "vk_programs.h"   // ((Triforce) RX_VK_LOAD=create: when programs are loaded
#include "vk_dump.h"   // (write_png: RX_VK_STARTUP_SHOTS)
#include "foliage_shadow.h"   // ((Triforce) RX_VK_FOLIAGE_SHADOW_VRS: whether the fragment shading rate is asked for)
#include "recorder_auto.h"   // ((Triforce) the recorder thread's default by the GPU and the cores)
#include "threaded_rendering.h"   // ((Triforce) the Threaded rendering row's rule: threaded_choice)
#include "vk_gpu_clock.h"   // ((Triforce, Linux) the GPU's stable power state: gpu_clock_device_created)
#include "mesa_spilling.h"    // ((Triforce, 11-22, PIPE-55) shader_spilling_rate=2 for Mesa's Intel compiler, Linux build)
#include "cxx_escape.h"       // ((Triforce) a C++ exception out of the renderer: said, and the game stopped on it
#include "renderer_guard.h"   // (every function the host is given, behind that)
#include "native_fadd.h"   // ((Triforce) RX_VK_NATIVE_FADD: where a float add to a storage buffer is the GPU's own atomic)
#include "new_wait.h"   // ((Triforce, 11-22, OS-04) a `new` refused at Windows' commit limit waits before it throws: new_refused)
#include <new>

namespace vkx {
#define VKX_DEFINE(f) PFN_##f f;
VKX_GLOBAL(VKX_DEFINE)
VKX_INSTANCE(VKX_DEFINE)
VKX_DEVICE(VKX_DEFINE)
VKX_DEVICE2(VKX_DEFINE)
VKX_DEVICE3(VKX_DEFINE)
#undef VKX_DEFINE

static PFN_vkGetInstanceProcAddr get_instance_proc;
// (Triforce, NVIDIA DLSS frame generation, vk_dlssg.cpp: while Streamline is up, get_instance_proc is its interposer's,
// so the instance, the device and every function of both are fetched through it; this is the loader's own)
static PFN_vkGetInstanceProcAddr loader_instance_proc;

bool load_global() {
#ifdef _WIN32   // (hookshot: the loader from System32 only, not from the current folder or PATH)
    HMODULE m = LoadLibraryExA("vulkan-1.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
#else
    HMODULE m = LoadLibraryA("vulkan-1.dll");   // (linux: libvulkan.so.1, host/posix/win32_posix.c)
#endif
    if (!m) return false;
    get_instance_proc = (PFN_vkGetInstanceProcAddr)(void*)GetProcAddress(m, "vkGetInstanceProcAddr");
    if (!get_instance_proc) return false;
    loader_instance_proc = get_instance_proc;
    if (const PFN_vkGetInstanceProcAddr interposer = mkwvk::dlssg::early()) get_instance_proc = interposer;
#define VKX_LOAD(f) f = (PFN_##f)get_instance_proc(nullptr, #f);
    VKX_GLOBAL(VKX_LOAD)
#undef VKX_LOAD
    return vkCreateInstance != nullptr;
}
PFN_vkGetInstanceProcAddr instance_proc_addr() { return get_instance_proc; }
void load_instance(VkInstance instance) {
#define VKX_LOAD(f) f = (PFN_##f)get_instance_proc(instance, #f);
    VKX_INSTANCE(VKX_LOAD)
#undef VKX_LOAD
}
/// (Triforce) Streamline is given up for this run before the device is made: the instance's functions from the loader again
void use_loader(VkInstance instance) {
    if (!loader_instance_proc || get_instance_proc == loader_instance_proc) return;
    get_instance_proc = loader_instance_proc;
    load_instance(instance);
}
void load_device(VkDevice device) {
#define VKX_LOAD(f) f = (PFN_##f)vkGetDeviceProcAddr(device, #f);
    VKX_DEVICE(VKX_LOAD)
    VKX_DEVICE2(VKX_LOAD)
    VKX_DEVICE3(VKX_LOAD)
#undef VKX_LOAD
}
} // namespace vkx

namespace mkwvk {

std::vector<std::string> gpu_device_names;
const MkwVkHost* host;
int64_t prof_ns[PROF_COUNT];
Device dev;
PFN_vkGetInstanceProcAddr instance_proc() { return vkx::instance_proc_addr(); }

static void vlogf(LogLevel level, const char* fmt, std::va_list a) {
    static const char* const tags[] = {"[error] ", "[warn] ", "", "[debug] ", "[trace] "};
    char b[1024];
    const int n = std::snprintf(b, sizeof b, "%s", tags[level >= log_error && level <= log_trace ? level : log_info]);
    std::vsnprintf(b + n, sizeof b - n, fmt, a);
    if (host) host->log(b);
}
void logf(const char* fmt, ...) {
    std::va_list a;
    va_start(a, fmt);
    vlogf(log_info, fmt, a);
    va_end(a);
}
void logf_at(LogLevel level, const char* fmt, ...) {
    std::va_list a;
    va_start(a, fmt);
    vlogf(level, fmt, a);
    va_end(a);
}

namespace {

bool has_extension(const std::vector<VkExtensionProperties>& all, const char* name) {
    for (const auto& e : all)
        if (!std::strcmp(e.extensionName, name)) return true;
    return false;
}

/// (vk_draw.cpp nv_own_folder_mark_path's file: beside the game)
std::string nv_own_folder_mark_path() {
    char exe[MAX_PATH];
    const DWORD n = game_module_path(exe, MAX_PATH);
    const std::string dir(exe, n);
    return dir.substr(0, dir.find_last_of("\\/") + 1) + "triforce_nvidia_cache.own";
}
/// ((Triforce, 11-26) a PC whose NVIDIA shader cache did not keep the game's (vk_draw.cpp nv_own_folder_mark_path has the lab
/// numbers and the player's report): the driver's cache in a folder of the game's own, triforce_nvidia_cache beside it, with
/// 10 GB of room, so other games' shaders do not push the game's out. Before the first Vulkan call, when the driver loads and
/// reads them; a path or size the player set wins. Windows' driver honours both (a probe at 100 MB stayed there); Linux's
/// main sets the size for every player already (host/hos_main.c driver_cache_room)
static void nv_own_folder() {
    FILE* m = fopen(nv_own_folder_mark_path().c_str(), "rb");
    if (!m) return;
    fclose(m);
    const std::string mark = nv_own_folder_mark_path();
    const std::string dir = mark.substr(0, mark.find_last_of("\\/") + 1) + "triforce_nvidia_cache";
    if (getenv("__GL_SHADER_DISK_CACHE_PATH")) {
        logf("vk: NVIDIA's shader cache: __GL_SHADER_DISK_CACHE_PATH is set already, kept (%s)", getenv("__GL_SHADER_DISK_CACHE_PATH"));
        return;
    }
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
#ifdef _WIN32
    // (the CRT's copy and the process's: the driver may read either)
    _putenv_s("__GL_SHADER_DISK_CACHE_PATH", dir.c_str());
    SetEnvironmentVariableA("__GL_SHADER_DISK_CACHE_PATH", dir.c_str());
    if (!getenv("__GL_SHADER_DISK_CACHE_SIZE")) {
        _putenv_s("__GL_SHADER_DISK_CACHE_SIZE", "10737418240");
        SetEnvironmentVariableA("__GL_SHADER_DISK_CACHE_SIZE", "10737418240");
    }
#else
    setenv("__GL_SHADER_DISK_CACHE_PATH", dir.c_str(), 0);
    setenv("__GL_SHADER_DISK_CACHE_SIZE", "10737418240", 0);
#endif
    logf("vk: NVIDIA's shader cache: a folder of the game's own, %s, %s bytes (this PC's driver did not keep the game's in its "
         "own folder: %s; remove that file to use the driver's folder again)", dir.c_str(), getenv("__GL_SHADER_DISK_CACHE_SIZE"),
         mark.c_str());
}
bool create_instance() {
    nv_own_folder();
    uint32_t version = VK_API_VERSION_1_0;
    if (vkEnumerateInstanceVersion) vkEnumerateInstanceVersion(&version);
    if (version < VK_API_VERSION_1_3) {
        logf("vk: the Vulkan loader is %u.%u: 1.3 is needed", VK_VERSION_MAJOR(version), VK_VERSION_MINOR(version));
        return false;
    }
#ifdef _WIN32
    const char* exts[] = {VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_WIN32_SURFACE_EXTENSION_NAME};
    const uint32_t n_exts = 2;
#else
    // (linux: every window system's surface the loader has, for whichever one SDL's window is on: X11 or Wayland)
    const char* exts[4] = {VK_KHR_SURFACE_EXTENSION_NAME};
    uint32_t n_exts = 1;
    {
        uint32_t n = 0;
        vkEnumerateInstanceExtensionProperties(nullptr, &n, nullptr);
        std::vector<VkExtensionProperties> all(n);
        vkEnumerateInstanceExtensionProperties(nullptr, &n, all.data());
        for (const char* want : {"VK_KHR_xlib_surface", "VK_KHR_xcb_surface", "VK_KHR_wayland_surface"})
            if (has_extension(all, want)) exts[n_exts++] = want;
    }
#endif
#ifndef _WIN32
    // ((Triforce, 11-22, the performance audit's PIPE-55, after Source A's) Mesa's Intel compiler spills registers at rate 2
    // (mesa_spilling.h): on an Iris Xe one compute program was not built after 20 minutes and 13 GB at the driver's own rate
    // and took 32 s and 1.7 GB at 2. Set before the instance is made, when the driver reads its options, and without
    // overwriting, so a value the player set wins. No other driver reads it. RX_VK_NO_SPILLING_RATE=1: the driver's own rate)
    if (mesa_spilling::wanted(false, getenv("RX_VK_NO_SPILLING_RATE"))) setenv("shader_spilling_rate", "2", 0);
#endif
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName = "mkw-recomp";
    app.apiVersion = VK_API_VERSION_1_3;
    VkInstanceCreateInfo ci{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ci.pApplicationInfo = &app;
    std::vector<const char*> ext_list(exts, exts + n_exts);
    {   // (hookshot) what NVIDIA DLSS needs (vk_dlss.cpp; nothing in a build without it)
        uint32_t n = 0;
        vkEnumerateInstanceExtensionProperties(nullptr, &n, nullptr);
        std::vector<VkExtensionProperties> all(n);
        vkEnumerateInstanceExtensionProperties(nullptr, &n, all.data());
        dlss_instance_extensions(ext_list, all);
        xess_instance_extensions(ext_list, all, app.apiVersion);   // ((Triforce) Intel XeSS's, when its library is there: vk_xess.cpp)
        // (hookshot) the HDR10 colour space for the Insert menu's HDR (the menu's settings are read after the instance is made, so
        // whenever the driver has it; the SDR choice in create_swapchain keeps to the sRGB surface)
        if (has_extension(all, VK_EXT_SWAPCHAIN_COLOR_SPACE_EXTENSION_NAME))
            ext_list.push_back(VK_EXT_SWAPCHAIN_COLOR_SPACE_EXTENSION_NAME), dev.swapchain_colorspace = true;
    }
    ci.enabledExtensionCount = (uint32_t)ext_list.size();
    ci.ppEnabledExtensionNames = ext_list.data();
    // RX_VK_VALIDATION=1: the Khronos validation layer (when installed)
    const char* layer = "VK_LAYER_KHRONOS_validation";
    if (getenv("RX_VK_VALIDATION")) ci.enabledLayerCount = 1, ci.ppEnabledLayerNames = &layer;
    if (vkCreateInstance(&ci, nullptr, &dev.instance) != VK_SUCCESS) {
        logf("vk: vkCreateInstance failed");
        return false;
    }
    load_instance(dev.instance);
    return true;
}

// (Triforce) The physical cores the process may run on (recorder_auto.h; 0: not known): the RelationProcessorCore entries with a
// logical processor in the process's affinity. The core kept for the replay thread (host->reserved_cpus) counts too: on Linux
// the process's mask is the one the loading thread had (host/posix/win32_posix.c), which may already be kept off that core
static unsigned process_physical_cores() {
    DWORD len = 0;
    GetLogicalProcessorInformation(nullptr, &len);
    std::vector<SYSTEM_LOGICAL_PROCESSOR_INFORMATION> info(len / sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION) + 1);
    len = (DWORD)(info.size() * sizeof info[0]);
    if (!GetLogicalProcessorInformation(info.data(), &len)) return 0;
    DWORD_PTR proc = 0, sys = 0;
    if (!GetProcessAffinityMask(GetCurrentProcess(), &proc, &sys) || !proc) return 0;
    std::vector<uint64_t> masks;
    for (DWORD i = 0; i < len / sizeof info[0]; i++)
        if (info[i].Relationship == RelationProcessorCore) masks.push_back((uint64_t)info[i].ProcessorMask);
    const uint64_t affinity = (uint64_t)proc | (host && host->reserved_cpus ? host->reserved_cpus() : 0);
    return recorder_default::physical_cores(masks.data(), (int)masks.size(), affinity);
}

// (Triforce) Threaded rendering (threaded_rendering.h), resolved once for the run: RX_VK_THREADED when it is set, else the Debug
// tab's row as the options file has it at the start (menu_init), the physical cores the process may run on (process_physical_cores)
// and, for Auto, whether the run is safe for it: the capture off (RX_VK_CAPTURE=0: a replay behind the game is right only from the
// capture), RX_VK_LOW_SPEC, a frame dump (RX_VK_DUMP), the bench (RX_VK_BENCH); then, only when Auto would pick the threads, the
// buffer pools' mirrors, which read the device (asked at pick_device, after it is known: a reader before it gets Auto off).
// On is the player's word: nothing is checked for it. Off, the default: every reader as before
const threaded::Choice& threaded_choice() {
    static const threaded::Choice choice = [] {
        menu_init();
        const int env = threaded::from_env(getenv("RX_VK_THREADED"));
        const int setting = env >= 0 ? env : opts.threaded_rendering;
        const unsigned cores = setting == threaded::AUTO ? process_physical_cores() : 0;
        const char* capture = getenv("RX_VK_CAPTURE");
        const char* unsafe = capture && atoi(capture) == 0                               ? "RX_VK_CAPTURE=0"
                             : getenv("RX_VK_LOW_SPEC") && atoi(getenv("RX_VK_LOW_SPEC")) ? "RX_VK_LOW_SPEC"
                             : getenv("RX_VK_DUMP")                                        ? "RX_VK_DUMP"
                             : getenv("RX_VK_BENCH")                                       ? "RX_VK_BENCH"
                                                                                           : nullptr;
        threaded::Choice c = threaded::choose(setting, cores, unsafe != nullptr);
        if (threaded::auto_picked(c)) {
            if (!dev.physical) {
                c = {false, false, threaded::Why::AutoUnsafe};
                unsafe = "asked before the GPU was picked";
            } else if (!pools_mirrored()) {
                c = threaded::without_mirrors(c, cores);
                unsafe = "the buffer pools have no mirrors";
            }
        }
        char line[256];
        threaded::describe(line, sizeof line, c, cores, unsafe, env >= 0);
        logf("vk: Threaded rendering: %s", line);
        return c;
    }();
    return choice;
}

bool pick_device() {
    menu_init();
    uint32_t n = 0;
    vkEnumeratePhysicalDevices(dev.instance, &n, nullptr);
    std::vector<VkPhysicalDevice> all(n);
    vkEnumeratePhysicalDevices(dev.instance, &n, all.data());

    std::vector<uint32_t> valid_gpus;
    std::vector<int> valid_types;   // ((Triforce) 11-22: their VkPhysicalDeviceType, for gpu_choice::unnamed_integrated)
    gpu_device_names.clear();
    for (uint32_t i = 0; i < n; i++) {
        VkPhysicalDeviceProperties p;
        vkGetPhysicalDeviceProperties(all[i], &p);
        logf("vk: device %u: %s, Vulkan %u.%u, driver %#x, type %d", i, p.deviceName, VK_API_VERSION_MAJOR(p.apiVersion),
             VK_API_VERSION_MINOR(p.apiVersion), p.driverVersion, (int)p.deviceType);
        if (p.apiVersion >= VK_API_VERSION_1_3) {
            valid_gpus.push_back(i);
            gpu_device_names.push_back(p.deviceName);
            valid_types.push_back((int)p.deviceType);
        }
    }
    menu_set_gpu_count((int)valid_gpus.size());
    {   // ((Triforce) 11-19, ticket "GPU read issue": the launcher named the GPU device row's choices in Windows' order of the
        // display adapters (an Intel UHD 770 first, the RTX 3050 second) while this row counts Vulkan's (the RTX first): its
        // "1: NVIDIA" saved the number that is the Intel here. The list as this row counts it, beside triforce_options.ini, for
        // the launcher's row: "<the row's value>\t<name>" a line)
        char exe[MAX_PATH];
        const DWORD n = game_module_path(exe, MAX_PATH);
        std::string dir(exe, n);
        dir = dir.substr(0, dir.find_last_of("\\/") + 1);
        std::string text;
        for (size_t k = 0; k < gpu_device_names.size(); k++) {
            std::string name = gpu_device_names[k];
            for (char& c : name)
                if ((unsigned char)c < 0x20) c = ' ';
            text += std::to_string(k + 1) + "\t" + name + "\n";
        }
        if (n && !text.empty()) {
            const std::string path = dir + "triforce_gpus.txt", part = path + ".part";
            if (FILE* f = fopen(part.c_str(), "wb")) {
                const bool ok = fwrite(text.data(), 1, text.size(), f) == text.size();
                if (fclose(f) == 0 && ok) MoveFileExA(part.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING);
                else remove(part.c_str());
            }
        }
    }

    // (AMD laptops) With AMD graphics in the processor and an AMD card, Windows has two AMD drivers installed, one an
    // adapter, and each one's Vulkan driver lists every AMD GPU: the card shows up twice. It came first through the
    // processor graphics' driver, which the card's own update leaves as it was: on an RX 7700S that older driver
    // (amdvlk64.dll 32.0.11036.4002) crashed in its shader compiler (0xc0000409) on the game's compute pipelines while
    // the card's 32.0.32015.7029 built them. The same kind of GPU twice: the one with the newer driver wins.
    // RX_VK_DEVICE=<n> or opts.gpu_device: that device, as listed in the log
    int best = -1, best_score = -1;
    uint32_t best_driver = 0;
    int target_raw_idx = -1;
    bool unnamed_integrated = false;   // ((Triforce) 11-22: the row's number alone on the processor graphics: Auto, the row follows)
    if (const char* want = getenv("RX_VK_DEVICE")) {
        if (*want) target_raw_idx = atoi(want);
    } else if (gpu_choice::unnamed_integrated(menu_gpu_name(), gpu_device_names, valid_types, opts.gpu_device)) {
        unnamed_integrated = true;
    } else if (const int k = gpu_choice::pick(menu_gpu_name(), gpu_device_names, opts.gpu_device); k >= 0) {
        target_raw_idx = (int)valid_gpus[k];
        if (opts.gpu_device != k + 1) {   // ((Triforce) 11-20: the saved name found the card under another number: the row follows it)
            logf("vk: GPU device: \"%s\" by its name is device %d here, not the %d saved with it: the row now says %d",
                 gpu_device_names[(size_t)k].c_str(), k + 1, opts.gpu_device, k + 1);
            opts.gpu_device = k + 1;
        }
        // ((Triforce) 11-20, ticket "Crash on opening", RX 7900 XTX with AMD processor graphics: heap corruption in amdvlk64.dll at
        // half the starts, the card driven through the processor graphics' older driver (device 0: Vulkan 1.3, 0x800126) because the
        // row named the card and its first listing is that driver's; its own driver (device 1: Vulkan 1.4, 0x80018b) is the one Auto
        // takes. The same card listed again with a newer driver (same vendor and device id, as the comment above has it): that one)
        VkPhysicalDeviceProperties chosen;
        vkGetPhysicalDeviceProperties(all[(size_t)target_raw_idx], &chosen);
        for (uint32_t i : valid_gpus) {
            VkPhysicalDeviceProperties p;
            vkGetPhysicalDeviceProperties(all[i], &p);
            if ((int)i == target_raw_idx || p.vendorID != chosen.vendorID || p.deviceID != chosen.deviceID ||
                p.deviceType != chosen.deviceType || p.driverVersion <= chosen.driverVersion)
                continue;
            logf("vk: GPU device: %s is listed again with a newer driver (device %u: %#x, against device %d: %#x): that one",
                 p.deviceName, i, p.driverVersion, target_raw_idx, chosen.driverVersion);
            target_raw_idx = (int)i, chosen = p;
        }
    }

    for (uint32_t i : valid_gpus) {
        VkPhysicalDeviceProperties p;
        vkGetPhysicalDeviceProperties(all[i], &p);
        if (target_raw_idx >= 0) {
            if ((int)i == target_raw_idx) best = (int)i, best_score = 3;
            continue;
        }
        const int score = p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU ? 2 :
                          p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU ? 1 : 0;
        if (score > best_score || (score == best_score && p.driverVersion > best_driver))
            best = (int)i, best_score = score, best_driver = p.driverVersion;
    }
    if (best < 0 && target_raw_idx >= 0) {
        logf("vk: preferred device %d not available or lacks Vulkan 1.3, falling back to auto selection", target_raw_idx);
        for (uint32_t i : valid_gpus) {
            VkPhysicalDeviceProperties p;
            vkGetPhysicalDeviceProperties(all[i], &p);
            const int score = p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU ? 2 :
                              p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU ? 1 : 0;
            if (score > best_score || (score == best_score && p.driverVersion > best_driver))
                best = (int)i, best_score = score, best_driver = p.driverVersion;
        }
    }
    if (best < 0) {
        logf("vk: no Vulkan 1.3 GPU");
        return false;
    }
    if (unnamed_integrated) {   // ((Triforce) 11-22) the row says the card Auto took: the menu's next save keeps it with its name
        for (size_t k = 0; k < valid_gpus.size(); k++) {
            if (valid_gpus[k] != (uint32_t)best) continue;
            logf("vk: GPU device: the row's %d is the processor graphics (%s) and no name was saved with it (a choice counted in "
                 "Windows' order before 11-20): %s, as Auto takes it; the row now says %d",
                 opts.gpu_device, gpu_device_names[(size_t)opts.gpu_device - 1].c_str(), gpu_device_names[k].c_str(), (int)k + 1);
            opts.gpu_device = (int)k + 1;
        }
    }
    dev.physical = all[best];
    vkGetPhysicalDeviceProperties(dev.physical, &dev.props);
    // (Triforce, 11-16) the recorder thread's default (vk_recorder.h mode_from_env): NVIDIA with 12 logical processors or more;
    // (Triforce, 11-21) AMD with 6 physical cores or more, but for its older Windows driver (recorder_auto.h)
    {
        VkPhysicalDeviceDriverProperties drv{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &drv;
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
        VendorFacts facts;
        facts.vendor_id = p2.properties.vendorID;
        facts.driver_id = drv.driverID;
        facts.device_type = p2.properties.deviceType;
        facts.driver_info = drv.driverInfo;
        const unsigned logical = cpu_count(), physical = process_physical_cores();
        const recorder_default::Why why = recorder_default::why(facts.vendor_id, logical, physical, amd_older_compiler(facts));
        recorder_auto(recorder_default::on(why));
        if (!getenv("RX_VK_RECORDER"))
            logf("vk: recorder thread %s by default (%s: %u logical processors, %u physical cores; RX_VK_RECORDER=thread or =off "
                 "decides)", recorder_default::on(why) ? "on" : "off", recorder_default::text(why), logical, physical);
        // ((Triforce) Threaded rendering, resolved here, the device known: its recorder thread over that default, the switch over both)
        if (threaded_choice().recorder_thread && !recorder_default::on(why)) {
            recorder_auto(true);
            if (!getenv("RX_VK_RECORDER")) logf("vk: recorder thread on: Threaded rendering (RX_VK_RECORDER=off: off)");
        }
    }
    vkGetPhysicalDeviceMemoryProperties(dev.physical, &dev.memory);
    return true;
}

bool create_device() {
    uint32_t n = 0;
    vkEnumerateDeviceExtensionProperties(dev.physical, nullptr, &n, nullptr);
    std::vector<VkExtensionProperties> exts(n);
    vkEnumerateDeviceExtensionProperties(dev.physical, nullptr, &n, exts.data());
    std::vector<const char*> want = {VK_KHR_SWAPCHAIN_EXTENSION_NAME};
    auto optional = [&](const char* name, bool& flag) {
        flag = has_extension(exts, name);
        if (flag) want.push_back(name);
    };
    // (RX_VK_FORCE_MESH_FALLBACK=1, a test: mesh shaders not used where they are, so the no-mesh fallback the GTX 10xx and RX 5000
    // cards run (issue 640) can be tried on any GPU)
    if (getenv("RX_VK_FORCE_MESH_FALLBACK") && atoi(getenv("RX_VK_FORCE_MESH_FALLBACK")) != 0) dev.mesh_shader = false;
    else optional(VK_EXT_MESH_SHADER_EXTENSION_NAME, dev.mesh_shader);
    optional(VK_EXT_EXTERNAL_MEMORY_HOST_EXTENSION_NAME, dev.external_memory_host);
    optional(VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME, dev.external_memory_fd);   // (guest memory as udmabufs: vk_memory.cpp import_dma_buf)
    if (dev.external_memory_fd) optional(VK_EXT_EXTERNAL_MEMORY_DMA_BUF_EXTENSION_NAME, dev.dma_buf_import);
    optional(VK_KHR_PIPELINE_LIBRARY_EXTENSION_NAME, dev.pipeline_library);
    // ((Triforce) RX_VK_LOAD=create or auto only: the load at a program's create call makes a compute pipeline from the caches by
    // its module's identifier, without the program's code (vk_programs.h). Without the switch the device is made as before.
    // Not a field of dev: vk_state.h is part of the translator's stamp)
    bool module_id = false;
    if (programs_load_asked()) optional(VK_EXT_SHADER_MODULE_IDENTIFIER_EXTENSION_NAME, module_id);
    if (dev.pipeline_library) optional(VK_EXT_GRAPHICS_PIPELINE_LIBRARY_EXTENSION_NAME, dev.graphics_pipeline_library);
    optional(VK_EXT_CUSTOM_BORDER_COLOR_EXTENSION_NAME, dev.custom_border_color);
    optional(VK_EXT_EXTENDED_DYNAMIC_STATE_3_EXTENSION_NAME, dev.dynamic_state3);
    optional(VK_EXT_DEPTH_CLIP_CONTROL_EXTENSION_NAME, dev.depth_clip_control);
    optional(VK_EXT_ROBUSTNESS_2_EXTENSION_NAME, dev.null_descriptor);
    optional(VK_EXT_INDEX_TYPE_UINT8_EXTENSION_NAME, dev.index_uint8);
    optional(VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME, dev.push_descriptor);
    optional(VK_EXT_CONDITIONAL_RENDERING_EXTENSION_NAME, dev.conditional_rendering);
    optional(VK_EXT_PROVOKING_VERTEX_EXTENSION_NAME, dev.provoking_vertex);
    optional(VK_EXT_VERTEX_ATTRIBUTE_DIVISOR_EXTENSION_NAME, dev.vertex_divisor);
    optional(VK_EXT_SHADER_STENCIL_EXPORT_EXTENSION_NAME, dev.stencil_export);
    optional(VK_EXT_MEMORY_BUDGET_EXTENSION_NAME, dev.memory_budget);
    // ((Triforce, 11-22, the performance audit's TEX-47, after Source A's) VK_EXT_memory_priority: which device memory the
    // system keeps in video memory when the card is short, the render targets before the sampled textures. Asked for only
    // with RX_VK_MEMORY_PRIORITY (1, or <targets>,<textures>: memory_priority.h); unset, nothing of it is on)
    const bool prio_asked = memory_priority::parse(getenv("RX_VK_MEMORY_PRIORITY")).on;
    if (prio_asked) optional(VK_EXT_MEMORY_PRIORITY_EXTENSION_NAME, dev.memory_priority);
    optional(VK_EXT_IMAGE_2D_VIEW_OF_3D_EXTENSION_NAME, dev.view_2d_of_3d);
    // ((Triforce) the far cascades' foliage at one fragment per 2 x 2 pixels, foliage_shadow.h: asked for only where mesh programs
    // can draw natively and RX_VK_FOLIAGE_SHADOW_VRS is not off; enabled below only with pipelineFragmentShadingRate)
    const int rate_from = foliage_shadow::parse_rate(getenv("RX_VK_FOLIAGE_SHADOW_VRS"));
    bool rate_ext = false;
    if (dev.mesh_shader && rate_from >= 0) optional(VK_KHR_FRAGMENT_SHADING_RATE_EXTENSION_NAME, rate_ext);
    // (hookshot) on by default: with a marker before each draw and dispatch the device has not been lost (five
    // runs); without them it was, every run, shortly after OoT's first gameplay frames (nvlddmkm event 153; the
    // extension alone, RX_VK_CHECKPOINTS=ext, did not keep it). The race they hide is not found yet.
    // RX_VK_CHECKPOINTS=0: off
    if (!getenv("RX_VK_CHECKPOINTS") || strcmp(getenv("RX_VK_CHECKPOINTS"), "0") != 0)
        optional(VK_NV_DEVICE_DIAGNOSTIC_CHECKPOINTS_EXTENSION_NAME, dev.checkpoints);
    // (asked for only: a marker written twice a draw, where the NV ones are not there to hide a race)
    if (const char* c = getenv("RX_VK_CHECKPOINTS"); !dev.checkpoints && c && strcmp(c, "0") != 0 && strcmp(c, "ext") != 0)
        optional(VK_AMD_BUFFER_MARKER_EXTENSION_NAME, dev.buffer_marker);
    optional(VK_EXT_DEVICE_FAULT_EXTENSION_NAME, dev.device_fault);
    optional(VK_KHR_COOPERATIVE_MATRIX_EXTENSION_NAME, dev.coop_matrix);
    // (Triforce) the GPU's own float add on storage buffers: the game's RED/ATOM.ADD.F32 become one OpAtomicFAddEXT instead
    // of a compare-exchange loop, which gives up after CAS_LOOP_MAX_TRIES attempts and loses that add, and with which Intel's
    // Windows driver lost the device at the sky's light sums (compute 499dbfd0721d2858, an Arc B580 after the intro). By
    // default on the drivers and GPU families it was run on (native_fadd.h has the list); RX_VK_NATIVE_FADD=1 asks for it on
    // any GPU, =0 keeps the loop on every one, the extension not even enabled
    const char* const fadd_env = getenv("RX_VK_NATIVE_FADD");
    VkPhysicalDeviceDriverProperties fadd_driver{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
    {
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &fadd_driver;
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
    }
#ifdef _WIN32
    constexpr bool fadd_windows = true;
#else
    constexpr bool fadd_windows = false;
#endif
    const bool fadd_wanted = native_fadd::wanted(fadd_env, fadd_driver.driverID, dev.props.deviceID, dev.props.driverVersion, fadd_windows);
    bool atomic_float = false;
    if (fadd_wanted) optional(VK_EXT_SHADER_ATOMIC_FLOAT_EXTENSION_NAME, atomic_float);
    optional(VK_KHR_SWAPCHAIN_MUTABLE_FORMAT_EXTENSION_NAME, dev.swap_mutable);   // (hookshot: the overlays, vk_imgui.cpp)
    dlss_device_extensions(want, exts);   // (hookshot: NVIDIA DLSS's, vk_dlss.cpp)
    bool fsr_descriptor_buffer = false;   // (hookshot, linux: only with a Vulkan FSR 4 library beside the game, vk_fsr4.cpp)
    if (fsr4_wants_descriptor_buffer()) optional(VK_EXT_DESCRIPTOR_BUFFER_EXTENSION_NAME, fsr_descriptor_buffer);
    // (Triforce, NVIDIA DLSS frame generation: Streamline's device asks for Reflex's extensions itself, and the renderer's
    // own Reflex stays off in such a run; another vendor's card is made by the loader, without it)
    if (dlssg::early() && dev.props.vendorID != 0x10de) {
        dlssg::gave_up("the graphics card in use is not an NVIDIA card");
        vkx::use_loader(dev.instance);
    }
    if (dlssg::early()) dlssg::device_extensions(want, exts);
    else reflex_device_extensions(want, exts);   // (hookshot: NVIDIA Reflex's, vk_reflex.cpp)
    antilag_device_extensions(want, exts);   // (hookshot: AMD Anti-Lag 2's, vk_antilag.cpp)
    // ((Triforce) Intel XeSS's, when its library is there and the instance took its own; last, so a device refused with them
    // is made again without: below, at vkCreateDevice)
    const size_t want_before_xess = want.size();
    xess_device_extensions(want, exts);
    const std::vector<const char*> xess_exts(want.begin() + (ptrdiff_t)want_before_xess, want.end());   // (its own, by name)

    // the queue: one family for graphics, compute and transfer
    vkGetPhysicalDeviceQueueFamilyProperties(dev.physical, &n, nullptr);
    std::vector<VkQueueFamilyProperties> families(n);
    vkGetPhysicalDeviceQueueFamilyProperties(dev.physical, &n, families.data());
    dev.queue_family = UINT32_MAX;
    for (uint32_t i = 0; i < n && dev.queue_family == UINT32_MAX; i++)
        if ((families[i].queueFlags & (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT)) ==
            (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT))
            dev.queue_family = i;
    if (dev.queue_family == UINT32_MAX) return false;
    const float priority = 1.0f;
    VkDeviceQueueCreateInfo q{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    q.queueFamilyIndex = dev.queue_family;
    q.queueCount = 1;
    q.pQueuePriorities = &priority;
    // (hookshot) The presents on a queue of a compute family of their own, beside the replay's (RX_VK_PRESENT_QUEUE=1 / 0: on /
    // off; on by default with NVIDIA's driver on Windows, where it was measured). On the replay's queue vkQueuePresentKHR blocked
    // with dev.present_mu held, ~0.8 ms a present with frame interpolation at 4x and up to 8, and the game's main and presentation
    // threads waited there to submit. A second queue of the graphics family took that lock off the presents, but its presents
    // blocked longer (~2-4 ms: the graphics work of the two queues takes turns on the GPU) and the made frames were shown late
    // four times as often. A compute family's queue runs beside the graphics work: in Hyrule Field (a 14700K and an RTX 5070 Ti,
    // 4x, 175 Hz) the game went from ~52 to ~58 fps standing and ~46.5 to ~53 running, its frames over 22 ms from ~13% to ~1%
    // standing and over 40 ms from ~4% to ~0.2% running, the made frames as evenly shown standing. The swapchain's images are
    // shared by both families (vk_main.cpp create_swapchain), and a family that cannot present to the window leaves it off.
    uint32_t compute_family = UINT32_MAX;
    {
        bool want = false;
#ifdef _WIN32
        VkPhysicalDeviceDriverProperties dp{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &dp;
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
        want = false;   // (v2.0.9: off by default with the write-back diff until issue 1161's device lost is placed; was:
        (void)dp;       //  NVIDIA's driver on Windows. RX_VK_PRESENT_QUEUE=1: on)
#endif
        if (const char* e = getenv("RX_VK_PRESENT_QUEUE")) want = atoi(e) != 0;
        for (uint32_t i = 0; want && i < n && compute_family == UINT32_MAX; i++)
            if ((families[i].queueFlags & VK_QUEUE_COMPUTE_BIT) && !(families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT))
                compute_family = i;
    }
    VkDeviceQueueCreateInfo qs[2] = {q, {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO}};
    qs[1].queueFamilyIndex = compute_family;
    qs[1].queueCount = 1;
    qs[1].pQueuePriorities = &priority;

    // features: what the hardware has of what the replay uses (all of them on the GPUs MKW-class hardware maps to)
    VkPhysicalDeviceMeshShaderFeaturesEXT mesh{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MESH_SHADER_FEATURES_EXT};
    VkPhysicalDeviceRobustness2FeaturesEXT robust2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT};
    VkPhysicalDeviceIndexTypeUint8FeaturesEXT u8{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_INDEX_TYPE_UINT8_FEATURES_EXT};
    VkPhysicalDeviceVulkan13Features f13{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
    VkPhysicalDeviceVulkan12Features f12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    VkPhysicalDeviceVulkan11Features f11{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES};
    VkPhysicalDeviceFeatures2 f{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
    f.pNext = &f11, f11.pNext = &f12, f12.pNext = &f13;
    VkPhysicalDeviceExtendedDynamicState3FeaturesEXT eds3{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTENDED_DYNAMIC_STATE_3_FEATURES_EXT};
    VkPhysicalDeviceCustomBorderColorFeaturesEXT border{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_CUSTOM_BORDER_COLOR_FEATURES_EXT};
    VkPhysicalDeviceDepthClipControlFeaturesEXT clip{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DEPTH_CLIP_CONTROL_FEATURES_EXT};
    VkPhysicalDeviceConditionalRenderingFeaturesEXT cond{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_CONDITIONAL_RENDERING_FEATURES_EXT};
    VkPhysicalDeviceProvokingVertexFeaturesEXT pv{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROVOKING_VERTEX_FEATURES_EXT};
    VkPhysicalDeviceGraphicsPipelineLibraryFeaturesEXT gpl{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GRAPHICS_PIPELINE_LIBRARY_FEATURES_EXT};
    void** tail = &f13.pNext;
    VkPhysicalDeviceShaderModuleIdentifierFeaturesEXT module_idf{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_MODULE_IDENTIFIER_FEATURES_EXT};
    if (module_id) *tail = &module_idf, tail = &module_idf.pNext;
    if (dev.mesh_shader) *tail = &mesh, tail = &mesh.pNext;
    if (dev.null_descriptor) *tail = &robust2, tail = &robust2.pNext;
    if (dev.index_uint8) *tail = &u8, tail = &u8.pNext;
    if (dev.dynamic_state3) *tail = &eds3, tail = &eds3.pNext;
    if (dev.custom_border_color) *tail = &border, tail = &border.pNext;
    if (dev.depth_clip_control) *tail = &clip, tail = &clip.pNext;
    if (dev.conditional_rendering) *tail = &cond, tail = &cond.pNext;
    if (dev.provoking_vertex) *tail = &pv, tail = &pv.pNext;
    VkPhysicalDeviceVertexAttributeDivisorFeaturesEXT vdiv{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VERTEX_ATTRIBUTE_DIVISOR_FEATURES_EXT};
    if (dev.vertex_divisor) *tail = &vdiv, tail = &vdiv.pNext;
    if (dev.graphics_pipeline_library) *tail = &gpl, tail = &gpl.pNext;
    VkPhysicalDeviceFaultFeaturesEXT fault{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FAULT_FEATURES_EXT};
    if (dev.device_fault) *tail = &fault, tail = &fault.pNext;
    VkPhysicalDeviceImage2DViewOf3DFeaturesEXT v2d3d{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_2D_VIEW_OF_3D_FEATURES_EXT};
    if (dev.view_2d_of_3d) *tail = &v2d3d, tail = &v2d3d.pNext;
    VkPhysicalDeviceMemoryPriorityFeaturesEXT mem_prio{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_PRIORITY_FEATURES_EXT};
    if (dev.memory_priority) *tail = &mem_prio, tail = &mem_prio.pNext;   // ((Triforce, 11-22, TEX-47) only with the switch)
    VkPhysicalDeviceCooperativeMatrixFeaturesKHR coop{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_COOPERATIVE_MATRIX_FEATURES_KHR};
    if (dev.coop_matrix) *tail = &coop, tail = &coop.pNext;
    VkPhysicalDeviceShaderAtomicFloatFeaturesEXT afloat{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_ATOMIC_FLOAT_FEATURES_EXT};
    if (atomic_float) *tail = &afloat, tail = &afloat.pNext;
    VkPhysicalDeviceDescriptorBufferFeaturesEXT descriptor_buffer{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_BUFFER_FEATURES_EXT};
    if (fsr_descriptor_buffer) *tail = &descriptor_buffer, tail = &descriptor_buffer.pNext;
    VkPhysicalDeviceFragmentShadingRateFeaturesKHR rate{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FRAGMENT_SHADING_RATE_FEATURES_KHR};
    void** rate_at = nullptr;   // (the pNext that names it: taken out of the chain again when it is of no use)
    if (rate_ext) rate_at = tail, *tail = &rate, tail = &rate.pNext;
    reflex_device_features(tail);   // (present ids, when NVIDIA Reflex's extensions are there)
    antilag_device_features(tail);   // (AMD Anti-Lag 2's, when its extension is there)
    vkGetPhysicalDeviceFeatures2(dev.physical, &f);
    if (module_id && module_idf.shaderModuleIdentifier) module_ids_on();   // ((Triforce) RX_VK_LOAD=create: vk_programs.h)
    descriptor_buffer.descriptorBufferCaptureReplay = VK_FALSE;
    dev.view_2d_of_3d = dev.view_2d_of_3d && v2d3d.sampler2DViewOf3D;
    dev.memory_priority = dev.memory_priority && mem_prio.memoryPriority;   // ((Triforce, 11-22, TEX-47) the allocator's bit: vma_init)
    if (prio_asked && !dev.memory_priority)
        logf("vk: RX_VK_MEMORY_PRIORITY: this driver has no VK_EXT_memory_priority: nothing changes");
    coop.cooperativeMatrixRobustBufferAccess = VK_FALSE;
    dev.coop_matrix = dev.coop_matrix && coop.cooperativeMatrix &&
                      f12.vulkanMemoryModel && f12.vulkanMemoryModelDeviceScope;
    {   // ((Triforce) only the float add on buffers on: the one the translator emits)
        dev.float_atomic_add = atomic_float && afloat.shaderBufferFloat32AtomicAdd;
        void* const next = afloat.pNext;
        afloat = VkPhysicalDeviceShaderAtomicFloatFeaturesEXT{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_ATOMIC_FLOAT_FEATURES_EXT};
        afloat.pNext = next;
        afloat.shaderBufferFloat32AtomicAdd = dev.float_atomic_add ? VK_TRUE : VK_FALSE;
        const char* const how = dev.float_atomic_add ? "native (VK_EXT_shader_atomic_float)"
                                : !fadd_wanted       ? "compare-exchange loop"
                                : atomic_float       ? "compare-exchange loop (no shaderBufferFloat32AtomicAdd)"
                                                     : "compare-exchange loop (no VK_EXT_shader_atomic_float)";
        if (fadd_env) logf("vk: float atomic add on storage buffers: %s, RX_VK_NATIVE_FADD=%s", how, fadd_env);
        else logf("vk: float atomic add on storage buffers: %s, %s", how,
                  !fadd_wanted ? "by default only with NVIDIA's driver, Intel's Windows driver on Meteor Lake, Arrow Lake, Panther Lake, "
                                 "Lunar Lake and Battlemage, and AMD's Windows driver on Radeon 860M/840M (RX_VK_NATIVE_FADD=1: native "
                                 "where the GPU has it)"
                  : fadd_driver.driverID == VK_DRIVER_ID_NVIDIA_PROPRIETARY ? "NVIDIA's driver"
                  : fadd_driver.driverID == VK_DRIVER_ID_AMD_PROPRIETARY    ? "AMD's Windows driver, Radeon 860M/840M (0x1114) from 0x8001a0"
                                                                            : "Intel's Windows driver, Meteor Lake, Arrow Lake, Panther Lake, Lunar Lake or Battlemage");
    }
    // (bounds-checked buffer access: an out-of-range access dropped instead of faulting the device. On by default: the GPU
    // culling pass 53caac5f faulted the device while a save loaded, about one start in three, and the scene's lighting read garbage
    // for single frames (the black flashes); with it, neither in A/B runs at the same GPU time. Lichii's OoT branch keeps it on too.
    // The 'Robust buffers' row of triforce_options.ini chooses (0 Auto: off since 11-17, the owner's call; 1 Off; 2 On); RX_VK_ROBUST=0 or 1
    // over it. Off is null descriptors only: some NVIDIA cards ran slower with it on, issues 394, 418, 419)
    static const bool robust = []() -> bool {
        if (const char* e = getenv("RX_VK_ROBUST")) return atoi(e) != 0;
        char exe[MAX_PATH];
        const DWORD n = game_module_path(exe, MAX_PATH);   // (the game folder, not bin beside the launcher: vk_paths.h)
        std::string ini(exe, n);
        ini = ini.substr(0, ini.find_last_of("\\/") + 1) + "triforce_options.ini";
        int v = 1;   // (no line: Off, the row's default)
        if (FILE* f = fopen(ini.c_str(), "r")) {
            char line[80];
            while (fgets(line, sizeof line, f))
                if (!strncmp(line, "robust_buffers=", 15)) {
                    v = atoi(line + 15);
                    break;
                }
            fclose(f);   // (once: the PR closed it twice when the row said Auto)
        }
        // ((Triforce) 11-17, the owner's "keep robust buffers off by default": Auto is off now; only On (2) turns it on)
        return v == 2;
    }();
    const bool robust_ok = robust && robust2.robustBufferAccess2 && f.features.robustBufferAccess;
    robust2.robustBufferAccess2 = robust_ok ? VK_TRUE : VK_FALSE;
    robust2.robustImageAccess2 = VK_FALSE;
    dev.null_descriptor = dev.null_descriptor && robust2.nullDescriptor;
    pv.transformFeedbackPreservesProvokingVertex = VK_FALSE;
    dev.provoking_vertex = dev.provoking_vertex && pv.provokingVertexLast;
    dev.vertex_divisor = dev.vertex_divisor && vdiv.vertexAttributeInstanceRateDivisor;   // (a divisor over 1 needs the feature, not only the extension)
    dev.conditional_rendering = dev.conditional_rendering && cond.conditionalRendering;
    dev.custom_border_color = dev.custom_border_color && border.customBorderColors && border.customBorderColorWithoutFormat;
    dev.depth_clip_control = dev.depth_clip_control && clip.depthClipControl;
    dev.graphics_pipeline_library = dev.graphics_pipeline_library && gpl.graphicsPipelineLibrary;
    if (dev.graphics_pipeline_library) {
        VkPhysicalDeviceGraphicsPipelineLibraryPropertiesEXT lp{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GRAPHICS_PIPELINE_LIBRARY_PROPERTIES_EXT};
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &lp;
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
        dev.graphics_pipeline_library = lp.graphicsPipelineLibraryFastLinking != VK_FALSE;
    }
    dev.eds3_polygon = dev.dynamic_state3 && eds3.extendedDynamicState3PolygonMode;
    dev.eds3_clamp = dev.dynamic_state3 && eds3.extendedDynamicState3DepthClampEnable;
    dev.eds3_blend = dev.dynamic_state3 && eds3.extendedDynamicState3ColorBlendEnable &&
                     eds3.extendedDynamicState3ColorBlendEquation && eds3.extendedDynamicState3ColorWriteMask;
    bool amd_older = false;   // (AMD's Windows driver for RDNA 1 and 2: vk_vendor.h amd_older_compiler; the task + mesh default below)
    {   // (hookshot) the vendor and driver workarounds this device needs: vk_vendor.h, each forced by its RX_VK_ switch
        VkPhysicalDeviceDriverProperties drv{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &drv;
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
        VendorFacts facts;
        facts.vendor_id = p2.properties.vendorID;
        facts.driver_id = drv.driverID;
        facts.device_type = p2.properties.deviceType;
        facts.driver_info = drv.driverInfo;
        // ((Triforce, 11-22, the performance audit's MEM-23, after Source A's) RADV on a GCN 1 to 4 GPU, by its missing 16-bit
        // storage input and output: a fact for the rules that need those cards told apart (the mesh fallback's stage sizes).
        // No line and nothing else on any other device
        facts.storage_io16 = f11.storageInputOutput16 != VK_FALSE;
        dev.radv_gcn = radv_gcn(facts);
        if (dev.radv_gcn) logf("vk: RADV on a GCN 1 to 4 GPU (no 16-bit storage input and output)");
        dev.fixes = vendor_fixes(facts);
        amd_older = amd_older_compiler(facts);
        dev.amd_older_compiler = amd_older;
        vendor_fixes_env(dev.fixes, [](const char* name) -> const char* { return getenv(name); });
        logf("vk: vendor fixes for %s (%s): out-of-bounds texel fetches 0 %d, NaN tests by bits %d, gather offset %d",
             drv.driverName, drv.driverInfo, (int)dev.fixes.fetch_bounds, (int)dev.fixes.nan_bits, (int)dev.fixes.gather_offset);
    }
    // ((Triforce, 11-18, EstebanGGM's port of NX2navi issue #67) AMD's older proprietary shader compiler (vk_vendor.h
    // amd_older_compiler) applies alpha to coverage while the dynamic state says off: white stippling over foliage, grass, Link's
    // hair and tunic on RX 470-590 (#bug-tracker "Texture glitch again ... (RX 580)", 11-18 screenshots). There the state goes in
    // the pipeline instead. Only where the driver has no fast-linking pipeline libraries (the RX 580's 26.5.2: "pipeline
    // libraries no"): fast pipeline link needs this dynamic state (gpl_wanted), and an RX 6000 card on the same driver keeps it.
    // Those cards' pipelines are new to the driver's caches once (the state is in them now). RX_VK_DYN_A2C=0/1 decides outright
    {
        const bool eds3_a2c = dev.dynamic_state3 && eds3.extendedDynamicState3AlphaToCoverageEnable;
        bool want = !(amd_older && !dev.graphics_pipeline_library);
        if (const char* e = getenv("RX_VK_DYN_A2C"); e && *e) want = atoi(e) != 0;
        dev.eds3_a2c = eds3_a2c && want;
        if (eds3_a2c && !dev.eds3_a2c)
            logf("vk: alpha to coverage in the pipelines, not dynamic (%s; RX_VK_DYN_A2C=1: dynamic)",
                 getenv("RX_VK_DYN_A2C") && *getenv("RX_VK_DYN_A2C") ? "RX_VK_DYN_A2C=0"
                                                                    : "AMD's older compiler draws it while it is off");
    }
    dev.vk12 = f12;
    dev.vk13 = f13;
    {   // (hookshot, after TotK Recomp's vk_caps.c) NVN's programs are written for 32 lanes: the translator is told 32, and the lane
        // shuffles of OoT's networks and the lane masks of its mesh programs depend on it. NVIDIA's GPUs have no other size; AMD's
        // default to 64 where they like, and the networks' output came out as coloured noise (Hookshot issues 10 and 14)
        VkPhysicalDeviceFloatControlsProperties fc{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FLOAT_CONTROLS_PROPERTIES};
        VkPhysicalDeviceDriverProperties drv{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
        drv.pNext = &fc;
        VkPhysicalDeviceSubgroupSizeControlProperties sc{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_SIZE_CONTROL_PROPERTIES};
        sc.pNext = &drv;
        VkPhysicalDeviceSubgroupProperties sg{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_PROPERTIES};
        sg.pNext = &sc;
        VkPhysicalDeviceMeshShaderPropertiesEXT mesh_props{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MESH_SHADER_PROPERTIES_EXT};
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &sg;
        if (dev.mesh_shader) fc.pNext = &mesh_props;   // ((Triforce) with the extension only: the simulated turf's pools, sim_turf_max_records)
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
        if (dev.mesh_shader) dev.max_mesh_groups = std::min(mesh_props.maxMeshWorkGroupCount[0], mesh_props.maxMeshWorkGroupTotalCount);
        const bool pin = f13.subgroupSizeControl && sc.minSubgroupSize <= 32 && sc.maxSubgroupSize >= 32 && !getenv("RX_VK_NO_SUBGROUP_PIN");
        dev.sg32_stages = pin ? sc.requiredSubgroupSizeStages : 0;
        dev.max_workgroup_subgroups = sc.maxComputeWorkgroupSubgroups;
        dev.subgroup_size = sg.subgroupSize;
        dev.subgroup_stages = sg.supportedStages;
        fc.pNext = nullptr;
        dev.float_controls = fc;
        logf("vk: shader caps: subgroup stages %#x; denorm independence %d, fp32 denorm preserve %u flush %u, signed zero fp16 %u fp32 %u; "
             "int64 buffer atomics %u", (unsigned)sg.supportedStages, (int)fc.denormBehaviorIndependence, fc.shaderDenormPreserveFloat32,
             fc.shaderDenormFlushToZeroFloat32, fc.shaderSignedZeroInfNanPreserveFloat16, fc.shaderSignedZeroInfNanPreserveFloat32,
             dev.vk12.shaderBufferInt64Atomics);
        dev.subgroup_min = sc.minSubgroupSize;
        dev.subgroup_max = sc.maxSubgroupSize > sg.subgroupSize ? sc.maxSubgroupSize : sg.subgroupSize;
        dev.driver_id = drv.driverID;
        logf("vk: subgroups: default %u lanes, %u-%u, pinned to 32 on stages %#x, at most %u subgroups a workgroup", sg.subgroupSize,
             sc.minSubgroupSize, sc.maxSubgroupSize, (unsigned)dev.sg32_stages, dev.max_workgroup_subgroups);
        // ((Triforce, 11-22, PIPE-55) the rate create_instance asked Mesa's Intel compiler for, as this process sees it)
        if (mesa_spilling::told(drv.driverID == VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA)) {
            const char* rate = getenv(mesa_spilling::kName);
            logf("vk: Mesa's Intel compiler spills at rate %s (driconf shader_spilling_rate: 2 unless set)",
                 rate && *rate ? rate : "of its own");
        }
    }
    if (!f13.dynamicRendering || !f13.synchronization2 || !f12.timelineSemaphore) {
        logf("vk: the GPU lacks dynamic rendering, synchronization2 or timeline semaphores");
        return false;
    }
    mesh.multiviewMeshShader = mesh.primitiveFragmentShadingRateMeshShader = VK_FALSE;   // (not used)
    dev.mesh_shader = dev.mesh_shader && mesh.meshShader && mesh.taskShader;
    // ((Triforce) the shading rate per draw alone, set by the draws: no rate image, no rate a primitive writes. Neither of those
    // two features is enabled, so the combiners stay KEEP. Of no use (no pipelineFragmentShadingRate, no native mesh shaders):
    // the extension not enabled at all, the device as it was without it)
    rate.attachmentFragmentShadingRate = rate.primitiveFragmentShadingRate = VK_FALSE;
    dev.foliage_rate = rate_ext && rate.pipelineFragmentShadingRate && dev.mesh_shader;
    if (rate_ext && !dev.foliage_rate) {
        *rate_at = rate.pNext;
        for (size_t i = 0; i < want.size(); i++)
            if (!strcmp(want[i], VK_KHR_FRAGMENT_SHADING_RATE_EXTENSION_NAME)) want.erase(want.begin() + (ptrdiff_t)i--);
    }
    if (rate_from < 0) logf("vk: the far shadow cascades' foliage at 2 x 2: off (RX_VK_FOLIAGE_SHADOW_VRS)");
    else if (dev.foliage_rate)
        logf("vk: the far shadow cascades' foliage at 2 x 2: from layer %d (VK_KHR_fragment_shading_rate; RX_VK_FOLIAGE_SHADOW_VRS=off: "
             "off)", rate_from);
    else
        logf("vk: the far shadow cascades' foliage at 2 x 2: not on this device (%s)",
             !dev.mesh_shader ? "no native mesh shaders" : !rate_ext ? "no VK_KHR_fragment_shading_rate" : "no pipelineFragmentShadingRate");
    // (task and mesh shader counts in pipeline statistics, a feature of their own: RADV has it off on RDNA2, and a query
    // pool made with those counts all the same can hang the GPU)
    dev.mesh_queries = dev.mesh_shader && mesh.meshShaderQueries;
    // (hookshot, issue 640) RDNA1 and older GPUs: no mesh shaders, but task and mesh programs run as compute shaders
    // that write their vertices to buffers, drawn through an ordinary graphics pipeline. It needs buffer device addresses.
    dev.mesh_fallback = !dev.mesh_shader && f12.bufferDeviceAddress && !getenv("RX_VK_NO_MESH_FALLBACK");
    if (dev.mesh_fallback) logf("vk: no mesh shaders: task and mesh programs run as compute shaders (issue 640 fallback)");
    bool task_mesh_fallback = false;
#ifdef _WIN32
    // Navi 22 can time out on task + mesh draws in the AMD Windows driver (issue 996), and so can Navi 21: on an RX 6800 XT
    // (driver 0x800161) the native path lost the device within minutes at Hyrule Castle's entrance, while the fallback played
    // 25 minutes there with none. Navi 21 is 0x73bf (RX 6800, 6800 XT, 6900 XT), 0x73af (RX 6900 XT, XTXH boards) and 0x73a5
    // (RX 6950 XT): the same chip on the same driver, not tested on their own. Navi 22 is 0x73df (RX 6700 XT)
    // (Triforce, after NX2navi's mesh_fallback = auto) Every GPU of that driver branch now, not those four chips alone: AMD's
    // Windows driver for RDNA 1 and 2, the one whose driverInfo names the "AMD proprietary shader compiler" (vk_vendor.h
    // amd_older_compiler). It has mesh shaders on RDNA 2 only, so this is the RX 6000 cards and that generation's integrated
    // GPUs. NX2navi's players lost the device minutes into play on RX 6600 to RX 6950 XT cards alike, with the pass in
    // progress one that starts with a native mesh draw, and the reports here of a game that stops after the first cutscene
    // name an RX 6600 beside the RX 6700 XT. That the native mesh path is the cause on the other chips is not shown: this
    // is the path that played where it was tried, at the cost of a compute pass for each mesh draw. The driver for RDNA 3
    // and 4 (LLPC) draws them natively, as before. tests/test_task_mesh_fallback_devices.py
    task_mesh_fallback = dev.props.vendorID == 0x1002 && amd_older;
#endif
    // ((Triforce, 11-24) and on those cards the draws of a mesh stage with no task stage too: an RX 6800 XT lost the GPU near
    // Saria at such a draw, which the rule for task + mesh draws let through to the driver's mesh shaders. Only where the
    // rule above chose the fallback: the Mesh shaders row's Compute fallback and RX_VK_TASK_MESH_FALLBACK=1 on another GPU
    // move task + mesh draws alone, as before. RX_VK_MESH_ONLY_FALLBACK=0: task + mesh draws alone on these cards too)
    const bool amd_older_windows = task_mesh_fallback;
    {   // ((Triforce, 11-18) the menu's Mesh shaders row, mesh_shaders= in triforce_options.ini: 1 Compute fallback on any GPU with
        // mesh shaders (an RX 7700S's glowing walls went with it, #bug-tracker); 0 Auto, the rule above. RX_VK_TASK_MESH_FALLBACK over it)
        char exe[MAX_PATH];
        const DWORD n = game_module_path(exe, MAX_PATH);
        std::string ini(exe, n);
        ini = ini.substr(0, ini.find_last_of("\\/") + 1) + "triforce_options.ini";
        if (FILE* f = fopen(ini.c_str(), "r")) {
            char line[80];
            while (fgets(line, sizeof line, f))
                if (!strncmp(line, "mesh_shaders=", 13)) {
                    if (atoi(line + 13) == 1) task_mesh_fallback = true;
                    break;
                }
            fclose(f);
        }
    }
    if (const char* e = getenv("RX_VK_TASK_MESH_FALLBACK")) task_mesh_fallback = atoi(e) != 0;
    dev.task_mesh_fallback = task_mesh_fallback && dev.mesh_shader && f12.bufferDeviceAddress && !getenv("RX_VK_NO_MESH_FALLBACK");
    dev.mesh_only_fallback = dev.task_mesh_fallback && amd_older_windows &&
                             !(getenv("RX_VK_MESH_ONLY_FALLBACK") && !atoi(getenv("RX_VK_MESH_ONLY_FALLBACK")));
    if (dev.task_mesh_fallback)
        logf("vk: %s programs use the compute fallback (RX_VK_TASK_MESH_FALLBACK=0: native%s)",
             dev.mesh_only_fallback ? "mesh-only and task + mesh" : "task + mesh",
             dev.mesh_only_fallback ? "; RX_VK_MESH_ONLY_FALLBACK=0: task + mesh alone" : "");
    if (robust) logf("vk: robust buffer access %s", robust_ok ? "on" : "not supported");
    f.features.robustBufferAccess = robust_ok ? VK_TRUE : VK_FALSE;   // (off by default: the game's accesses stay in their buffers)
    dev.features = f.features;
    dev.sparse_images = (families[dev.queue_family].queueFlags & VK_QUEUE_SPARSE_BINDING_BIT) && f.features.sparseBinding &&
                        f.features.sparseResidencyImage2D && !(getenv("RX_VK_SPARSE") && !atoi(getenv("RX_VK_SPARSE")));
    dev.sparse_buffers = (families[dev.queue_family].queueFlags & VK_QUEUE_SPARSE_BINDING_BIT) && f.features.sparseBinding;
    // ((Triforce) Intel XeSS's features (vk_xess.cpp), last, into the chain as it will be made: the library sets what it needs
    // in the renderer's structures and adds what it lacks (VK_EXT_mutable_descriptor_type's); nothing without its library, and
    // a refusal leaves the chain as it was and XeSS out for the run)
    VkBaseOutStructure* chain_end = (VkBaseOutStructure*)&f;
    while (chain_end->pNext) chain_end = chain_end->pNext;
    void* chain = &f;
    xess_device_features(&chain, tail);
    VkDeviceCreateInfo ci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    ci.pNext = chain;
    ci.queueCreateInfoCount = compute_family != UINT32_MAX ? 2 : 1;
    ci.pQueueCreateInfos = qs;
    ci.enabledExtensionCount = (uint32_t)want.size();
    ci.ppEnabledExtensionNames = want.data();
    VkResult made = vkCreateDevice(dev.physical, &ci, nullptr, &dev.device);
    if (made != VK_SUCCESS && xess_device_refused()) {   // ((Triforce) refused with XeSS's: made again as without its library)
        logf("vk: vkCreateDevice failed with Intel XeSS's extensions and features (VkResult %d): made again without them", (int)made);
        for (const char* x : xess_exts)   // (by name: the list may have lost one of the renderer's since)
            for (size_t i = 0; i < want.size(); i++)
                if (!strcmp(want[i], x)) want.erase(want.begin() + (ptrdiff_t)i--);
        chain_end->pNext = nullptr;
        ci.pNext = &f;
        ci.enabledExtensionCount = (uint32_t)want.size();
        ci.ppEnabledExtensionNames = want.data();
        made = vkCreateDevice(dev.physical, &ci, nullptr, &dev.device);
    }
    if (made != VK_SUCCESS && dlssg::early()) {   // (Streamline's refused it: the loader's, without frame generation)
        char why[96];
        snprintf(why, sizeof why, "Streamline could not make the device (VkResult %d)", (int)made);
        dlssg::gave_up(why);
        vkx::use_loader(dev.instance);
        made = vkCreateDevice(dev.physical, &ci, nullptr, &dev.device);
    }
    if (made != VK_SUCCESS) {
        logf("vk: vkCreateDevice failed (VkResult %d)", (int)made);
        return false;
    }


    load_device(dev.device);
    // ((Triforce) when programs are loaded: RX_VK_LOAD, before the title without it (vk_programs.h). Without mesh shaders, or with
    // the task + mesh draws through the fallback, a start in create mode still keeps the fallback's programs ready; only the
    // log's reason depends on it (load_default.h))
    programs_load_decide(dev.mesh_shader && !dev.mesh_fallback && !dev.task_mesh_fallback);
    vkGetDeviceQueue(dev.device, dev.queue_family, 0, &dev.queue);
    dev.present_queue = VK_NULL_HANDLE;
    dev.present_family = dev.queue_family;
    if (compute_family != UINT32_MAX) vkGetDeviceQueue(dev.device, compute_family, 0, &dev.present_queue), dev.present_family = compute_family;
    dlssg::device_ready(dev.physical, dev.device);
    // (with DLSS frame generation the presents stay on the replay's queue: the generated frames are Streamline's work
    // inside the present, on that queue)
    if (dlssg::active()) dev.present_queue = VK_NULL_HANDLE, dev.present_family = dev.queue_family;
    if (dev.buffer_marker) buffer_markers_init();
    coopmat_init();
    reflex_device_created();
    antilag_device_created();
#ifdef __linux__
    // ((Triforce) the Steam Deck's GPU held at amdgpu's peak stable power state while the game runs: vk_gpu_clock.cpp, RX_VK_GPU_CLOCK)
    gpu_clock_device_created(has_extension(exts, VK_EXT_PHYSICAL_DEVICE_DRM_EXTENSION_NAME));
#endif
    if (dev.push_descriptor) {
        VkPhysicalDevicePushDescriptorPropertiesKHR pp{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PUSH_DESCRIPTOR_PROPERTIES_KHR};
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &pp;
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
        dev.max_push_descriptors = pp.maxPushDescriptors;
    }
    if (dev.vertex_divisor) {
        VkPhysicalDeviceVertexAttributeDivisorPropertiesEXT vp{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VERTEX_ATTRIBUTE_DIVISOR_PROPERTIES_EXT};
        VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
        p2.pNext = &vp;
        vkGetPhysicalDeviceProperties2(dev.physical, &p2);
        dev.max_vertex_divisor = vp.maxVertexAttribDivisor;
    }
    return true;
}

} // namespace

// ((Triforce) Threaded rendering's halves, for the other files: vk_internal.h)
bool threaded_render_thread() { return threaded_choice().render_thread; }
bool threaded_recorder_thread() { return threaded_choice().recorder_thread; }
bool threaded_on() { return threaded_choice().on(); }

/// (hookshot) The UNORM format of an sRGB one (the same bytes, read and written as they are), else the format itself
VkFormat unorm_of(VkFormat f) {
    switch (f) {
    case VK_FORMAT_B8G8R8A8_SRGB: return VK_FORMAT_B8G8R8A8_UNORM;
    case VK_FORMAT_R8G8B8A8_SRGB: return VK_FORMAT_R8G8B8A8_UNORM;
    case VK_FORMAT_A8B8G8R8_SRGB_PACK32: return VK_FORMAT_A8B8G8R8_UNORM_PACK32;
    default: return f;
    }
}
/// (hookshot) The views of the swapchain's images let go (before the swapchain they view: the device idle already)
void swap_views_drop() {
    for (auto view : dev.swap_views)
        if (view) vkDestroyImageView(dev.device, view, nullptr);
    dev.swap_views.clear();
}
/// (hookshot) A view of each of the swapchain's images, for Dear ImGui's overlays (vk_imgui.cpp), when they can be drawn into,
/// in the format given (the swapchain's, or its UNORM one when the swapchain was made mutable)
void swap_views_make(VkImageUsageFlags usage, VkFormat format) {
    swap_views_drop();
    dev.swap_views.assign(dev.swap_images.size(), VK_NULL_HANDLE);
    dev.swap_view_format = format;
    if (!(usage & VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT)) return;
    for (size_t i = 0; i < dev.swap_images.size(); i++) {
        VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        vi.image = dev.swap_images[i];
        vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
        vi.format = format;
        vi.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        if (vkCreateImageView(dev.device, &vi, nullptr, &dev.swap_views[i]) != VK_SUCCESS) dev.swap_views[i] = VK_NULL_HANDLE;
    }
}

// (Triforce) the present mode of the swapchain there is (present_mode.h's numbers; -1 none yet, or offscreen): the VSync row
// says what its choice came to on this driver
static std::atomic<int> present_mode_now{-1};
int swapchain_present_mode() { return present_mode_now.load(std::memory_order_relaxed); }

// (Triforce) The GPU the game renders on, its LUID (VkPhysicalDeviceIDProperties.deviceLUID, 8 bytes), for the performance
// overlay's GPU load: Windows' counters name an adapter by it (perf_machine.cpp; after NX2navi's perf_gpu_once). False when
// there is no device yet or the driver gives none
bool gpu_device_luid(uint8_t out[8]) {
    if (!dev.physical) return false;
    VkPhysicalDeviceIDProperties id{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES};
    VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, &id};
    vkGetPhysicalDeviceProperties2(dev.physical, &p2);
    if (!id.deviceLUIDValid) return false;
    std::memcpy(out, id.deviceLUID, VK_LUID_SIZE);
    return true;
}

// ---- (Triforce, 11-22, the performance audit's PRESENT-45, after Source A's) The window's surface lost (surface_lost.h),
// RX_VK_SURFACE_RECOVER (on unless =0)
namespace { bool open_window_surface(bool log_failure); }   // (below, with the window's own code: start)
namespace { int system_hdr_on(std::string* display); }      // (below too: Windows' own HDR setting for the window's display)
bool surface_recover(VkResult result) {
    static const bool on = surface_lost::on(getenv("RX_VK_SURFACE_RECOVER"));
    return surface_lost::recovers(result == VK_ERROR_SURFACE_LOST_KHR, on, dlssg::active());
}
/// What hangs on the lost surface let go, in Vulkan's order: the device idle first (frames in flight name the swapchain's
/// images), then the swapchain as create_swapchain lets an old one go (Reflex off it, the overlays' views, the images'
/// semaphores, the swapchain), then the surface. The first 8 losses are said. dev.present_mu held
void invalidate_lost_surface() {
    static int said;
    if (said++ < 8)
        logf("vk: the window's surface is lost: its swapchain and the surface are let go, and made again at the next present "
             "(RX_VK_SURFACE_RECOVER=0: not handled, as before)");
    device_wait_idle_locked();
    if (dev.swapchain) {
        reflex_swapchain_destroyed();
        swap_views_drop();
        for (auto semaphore : dev.swap_rendered) vkDestroySemaphore(dev.device, semaphore, nullptr);
        vkDestroySwapchainKHR(dev.device, dev.swapchain, nullptr);
        dev.swapchain = VK_NULL_HANDLE;
        dev.swap_rendered.clear();
        dev.swap_images.clear();
    }
    if (dev.surface) vkDestroySurfaceKHR(dev.instance, dev.surface, nullptr);
    dev.surface = VK_NULL_HANDLE;
}

bool create_swapchain(uint32_t width, uint32_t height) {
    // ((Triforce, 11-22, PRESENT-45) no surface: it was lost and let go (invalidate_lost_surface; start makes the first one
    // before it comes here). Made again with the startup's calls while the window has a size, one try each 250 ms at most)
    if (!dev.surface) {
        static int64_t tried_ms;
        const int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        if (!surface_lost::retry_due(now_ms, tried_ms)) return false;
        tried_ms = now_ms;
        if (!open_window_surface(true)) return false;
        logf("vk: the window's surface is made again");
    }
    VkSurfaceCapabilitiesKHR caps;
    VkResult result = vkGetPhysicalDeviceSurfaceCapabilitiesKHR(dev.physical, dev.surface, &caps);
    if (result != VK_SUCCESS) {
        if (surface_recover(result)) return invalidate_lost_surface(), false;   // ((Triforce, PRESENT-45) lost at the query)
        logf("vk: querying surface capabilities failed (VkResult %d)", (int)result);
        return false;
    }
    if (caps.currentExtent.width != UINT32_MAX) width = caps.currentExtent.width, height = caps.currentExtent.height;
    logf("vk: surface caps images %u..%u extent %ux%u..%ux%u usage %#x alpha %#x transform %#x",
         caps.minImageCount, caps.maxImageCount, caps.minImageExtent.width, caps.minImageExtent.height,
         caps.maxImageExtent.width, caps.maxImageExtent.height, caps.supportedUsageFlags,
         caps.supportedCompositeAlpha, caps.supportedTransforms);
    if (!(caps.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_DST_BIT)) {
        logf("vk: surface does not support transfer-destination swapchain images");
        return false;
    }
    if (!width || !height) return false;
    uint32_t n = 0;
    result = vkGetPhysicalDeviceSurfaceFormatsKHR(dev.physical, dev.surface, &n, nullptr);
    if (result != VK_SUCCESS || !n) {
        if (surface_recover(result)) return invalidate_lost_surface(), false;   // ((Triforce, PRESENT-45) lost at the query)
        logf("vk: querying surface formats failed (VkResult %d, count %u)", (int)result, n);
        return false;
    }
    std::vector<VkSurfaceFormatKHR> formats(n);
    vkGetPhysicalDeviceSurfaceFormatsKHR(dev.physical, dev.surface, &n, formats.data());
    VkSurfaceFormatKHR fmt = formats[0];
    for (const auto& f : formats)   // (an UNORM target: the game's window textures are presented as they are)
        // (in sRGB: RADV on Wayland lists every format again with PASS_THROUGH_EXT and the compositor's colour spaces,
        // and the last UNORM entry left the compositor an untagged surface, a grey picture. Still the last sRGB one, so
        // a driver that lists only sRGB (NVIDIA, X11, Windows) keeps the format it had.)
        if ((f.format == VK_FORMAT_B8G8R8A8_UNORM || f.format == VK_FORMAT_R8G8B8A8_UNORM) &&
            f.colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR)
            fmt = f;
    // (hookshot) the Insert menu's HDR: a 10-bit HDR10 surface when the display lists one (Windows: "Use HDR" on in its display
    // settings), the picture then written by framegen_hdr. Otherwise the SDR one above, and why (dev.hdr_sdr_why: Windows'
    // own setting tells "HDR off" from "the driver lists none with HDR on", as NVIDIA's can), said
    // again when the reason or the display asked about changes, and when the menu's HDR was turned off in between
    dev.hdr = false;
    dev.hdr_sdr_why = hdr_sdr_none;
    static int told = -1;   // (the HdrSdrWhy last said, hdr_sdr_none an HDR10 surface; -1 nothing yet, or HDR off since)
    static std::string told_display;
    if (!opts.hdr) told = -1;
    if (opts.hdr) {
        for (const auto& f : formats)
            if ((f.format == VK_FORMAT_A2B10G10R10_UNORM_PACK32 || f.format == VK_FORMAT_A2R10G10B10_UNORM_PACK32) &&
                f.colorSpace == VK_COLOR_SPACE_HDR10_ST2084_EXT)
                fmt = f, dev.hdr = true;
        std::string display;   // (the display Windows was asked about, named in the line: a PC can have several)
        if (!dev.hdr) {
            const int system_hdr = dev.swapchain_colorspace ? system_hdr_on(&display) : -1;
            dev.hdr_sdr_why = !dev.swapchain_colorspace ? hdr_sdr_no_extension
                              : system_hdr == 0     ? hdr_sdr_os_off
                              : system_hdr == 1     ? hdr_sdr_driver
                                                    : hdr_sdr_unknown;
            if (!display.empty()) display = " (" + display + ")";
        }
        if ((int)dev.hdr_sdr_why != told || display != told_display) {
            told = dev.hdr_sdr_why, told_display = display;
            static const char* const why[] = {
                "", " (no VK_EXT_swapchain_colorspace)", " (HDR is off for this display in Windows' display settings)",
                (" though Windows has HDR on for this display: the graphics driver offers the game none (a clean reinstall of "
                 "the driver, then a restart of the PC)"),
                " (is HDR on in the display settings?)"};
            static_assert(sizeof why / sizeof *why == hdr_sdr_count, "create_swapchain: a line for each HdrSdrWhy");
            if (dev.hdr)
                logf("vk: HDR: an HDR10 surface (format %d), paper white %d nits, peak %d nits", (int)fmt.format, opts.hdr_white,
                     opts.hdr_peak);
            else
                logf("vk: HDR: the display%s lists no HDR10 surface%s: SDR", display.c_str(), why[dev.hdr_sdr_why]);
        }
    }
    // mailbox when the driver has it (latest frame, no tear). The game paces itself (nn_vi.c).
    n = 0;
    result = vkGetPhysicalDeviceSurfacePresentModesKHR(dev.physical, dev.surface, &n, nullptr);
    std::vector<VkPresentModeKHR> modes;
    if (result == VK_SUCCESS && n) {
        modes.resize(n);
        result = vkGetPhysicalDeviceSurfacePresentModesKHR(dev.physical, dev.surface, &n, modes.data());
    }
    if (result != VK_SUCCESS || modes.empty())
        logf("vk: querying present modes failed (VkResult %d, count %u); trying mandatory FIFO mode", (int)result, n);
    const bool fifo_env = getenv("RX_VK_FIFO") != nullptr;   // (as on a card or driver with vsync forced)
    // (Windows, no mailbox: AMD's driver has none, and FIFO held anything under 60 fps at 30.
    //  Linux: immediate on NVIDIA's X11 path turns vblank off for every output, so the other
    //  monitor and other programs tear. RX_VK_IMMEDIATE=1 still asks for it.)
    const bool want_immediate = getenv("RX_VK_IMMEDIATE") != nullptr;
    // ((Triforce) 11-24: the VSync row's Every refresh, 2: FIFO, each frame waiting for the display's refresh, as RX_VK_FIFO;
    // RX_VK_IMMEDIATE still over the row)
    const bool force_fifo = fifo_env || (opts.vsync == 2 && !want_immediate);
    // (Triforce) the Insert menu's VSync row off asks for immediate too, wherever the surface lists it; on, the choice is the
    // one above, from before the row. present_mode.h has the rule, the two switches still over the row
    bool has_mailbox = false, has_immediate = false;
    for (auto m : modes) has_mailbox |= m == VK_PRESENT_MODE_MAILBOX_KHR, has_immediate |= m == VK_PRESENT_MODE_IMMEDIATE_KHR;
#ifdef _WIN32
    const bool windows = true;
#else
    const bool windows = false;
#endif
    const present_mode::Mode chosen = present_mode::choose(has_mailbox, has_immediate, opts.vsync != 0, windows, force_fifo, want_immediate);
    const VkPresentModeKHR mode = chosen == present_mode::kMailbox     ? VK_PRESENT_MODE_MAILBOX_KHR
                                  : chosen == present_mode::kImmediate ? VK_PRESENT_MODE_IMMEDIATE_KHR
                                                                       : VK_PRESENT_MODE_FIFO_KHR;
    VkSwapchainCreateInfoKHR ci{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR};
    ci.surface = dev.surface;
    ci.minImageCount = std::max(caps.minImageCount, 4u);   // (hookshot: mailbox with frame interpolation: an image always free)
    if (caps.maxImageCount) ci.minImageCount = std::min(ci.minImageCount, caps.maxImageCount);
    ci.imageFormat = fmt.format;
    ci.imageColorSpace = fmt.colorSpace;
    ci.imageExtent = {width, height};
    ci.imageArrayLayers = 1;
    ci.imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    // The renderer copies into swapchain images. Readback is optional and only available on surfaces that allow it.
    if (caps.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_SRC_BIT)
        ci.imageUsage |= VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    // (hookshot) the overlays Dear ImGui draws (vk_imgui.cpp) render into it. Every surface allows it (the Vulkan spec)
    if (caps.supportedUsageFlags & VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT)
        ci.imageUsage |= VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
    ci.preTransform = caps.currentTransform;
    ci.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    if (!(caps.supportedCompositeAlpha & ci.compositeAlpha)) {
        for (VkCompositeAlphaFlagBitsKHR alpha : {VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR,
                                                  VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR,
                                                  VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR})
            if (caps.supportedCompositeAlpha & alpha) { ci.compositeAlpha = alpha; break; }
    }
    ci.presentMode = mode;
    const uint32_t sharing[2] = {dev.queue_family, dev.present_family};
    if (dev.present_queue && dev.present_family != dev.queue_family) {   // (presented from another family: no ownership moves)
        ci.imageSharingMode = VK_SHARING_MODE_CONCURRENT;
        ci.queueFamilyIndexCount = 2;
        ci.pQueueFamilyIndices = sharing;
    }
    ci.clipped = VK_TRUE;
    ci.oldSwapchain = dev.swapchain;
    // (hookshot) an sRGB swapchain (some drivers list no UNORM format) made mutable when the driver can: the overlays draw
    // through UNORM views, their colours as they are, as on a UNORM swapchain. Without it, vk_imgui.cpp makes them linear
    const VkFormat view_formats[2] = {fmt.format, unorm_of(fmt.format)};
    VkImageFormatListCreateInfo format_list{VK_STRUCTURE_TYPE_IMAGE_FORMAT_LIST_CREATE_INFO};
    const bool mutable_view = dev.swap_mutable && view_formats[1] != fmt.format && (ci.imageUsage & VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT);
    if (mutable_view) {
        ci.flags |= VK_SWAPCHAIN_CREATE_MUTABLE_FORMAT_BIT_KHR;
        format_list.viewFormatCount = 2;
        format_list.pViewFormats = view_formats;
        format_list.pNext = ci.pNext;
        ci.pNext = &format_list;
    }
    reflex_swapchain_info(ci);   // (NVIDIA Reflex: latency mode on)
    VkSwapchainKHR sc;
    result = vkCreateSwapchainKHR(dev.device, &ci, nullptr, &sc);
    // Passing oldSwapchain retires it even when creation fails. Nothing may acquire from it again.
    if (dev.swapchain) {
        device_wait_idle_locked();   // (the present queue's presents of the old swapchain done too)
        reflex_swapchain_destroyed();   // (no latency sleep or markers may use the destroyed chain)
        swap_views_drop();   // (hookshot: the overlays' views of its images, before it)
        for (auto semaphore : dev.swap_rendered) vkDestroySemaphore(dev.device, semaphore, nullptr);
        vkDestroySwapchainKHR(dev.device, dev.swapchain, nullptr);
        dev.swapchain = VK_NULL_HANDLE;
        dev.swap_rendered.clear();
        dev.swap_images.clear();
    }
    if (result != VK_SUCCESS) {
        // ((Triforce, 11-22, PRESENT-45) the surface lost at the creation: it goes too (the old swapchain went just above),
        // and the next present's creation makes one for the window again)
        if (surface_recover(result)) return invalidate_lost_surface(), false;
        logf("vk: vkCreateSwapchainKHR failed (VkResult %d, extent %ux%u, format %d, usage %#x, mode %d, images %u)",
             (int)result, width, height, (int)fmt.format, ci.imageUsage, (int)mode, ci.minImageCount);
        return false;
    }
    if (vkGetSwapchainImagesKHR(dev.device, sc, &n, nullptr) != VK_SUCCESS || !n) {
        vkDestroySwapchainKHR(dev.device, sc, nullptr);
        return false;
    }
    std::vector<VkImage> images(n);
    if (vkGetSwapchainImagesKHR(dev.device, sc, &n, images.data()) != VK_SUCCESS || !n) {
        vkDestroySwapchainKHR(dev.device, sc, nullptr);
        return false;
    }
    images.resize(n);
    std::vector<VkSemaphore> rendered(n, VK_NULL_HANDLE);
    VkSemaphoreCreateInfo si{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    for (auto& semaphore : rendered) {
        if (vkCreateSemaphore(dev.device, &si, nullptr, &semaphore) != VK_SUCCESS) {
            for (auto made : rendered)
                if (made) vkDestroySemaphore(dev.device, made, nullptr);
            vkDestroySwapchainKHR(dev.device, sc, nullptr);
            return false;
        }
    }
    dev.swapchain = sc;
    dev.swap_rendered = std::move(rendered);
    dev.swap_format = fmt.format;
    dev.swap_extent = {width, height};
    dev.swap_images = std::move(images);
    logf("vk: swapchain %ux%u, %u images, %s%s", width, height, n, present_mode::name(chosen),
         fifo_env ? " (RX_VK_FIFO)" : force_fifo ? " (VSync every refresh)" : want_immediate ? " (RX_VK_IMMEDIATE)" : opts.vsync ? "" : " (VSync off)");
    dev.swap_generation++;   // ((Triforce) an image held from the one before is let go: present_image, RX_VK_ACQUIRE_FENCE)
    present_mode_now.store((int)chosen, std::memory_order_relaxed);
    swap_views_make(ci.imageUsage, mutable_view ? view_formats[1] : fmt.format);
    reflex_swapchain_created(sc);   // (NVIDIA Reflex: its sleep mode on the new swapchain)
    dlssg::swapchain_created();     // (Triforce, DLSS frame generation: Streamline's Reflex mode is the swapchain's too)
    return true;
}

namespace {

HWND main_window = nullptr;
#ifdef _WIN32
// (Triforce) Windows 11 24H2's advanced colour info (DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2 and the names of its numbers in
// the Windows SDK), written out for headers that lack it or keep it behind NTDDI_VERSION
struct AdvancedColorInfo2 {
    DISPLAYCONFIG_DEVICE_INFO_HEADER header;
    UINT32 flags, color_encoding, bits_per_color_channel, active_color_mode;
};
enum : UINT32 {
    kGetAdvancedColorInfo2 = 15,   // (DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO_2)
    kAdvancedColorModeHdr = 2      // (DISPLAYCONFIG_ADVANCED_COLOR_MODE_HDR; 0 SDR, 1 wide colour)
};
#endif
// (Triforce) whether the system has HDR on for the window's display: 1 on, 0 off, -1 not known. Windows' own setting ("Use
// HDR"), as its display settings show it: create_swapchain's word on why the swapchain is SDR. *display is given the
// display's name (the monitor's, else Windows' "\\.\DISPLAYn") once it is found, for the log. Windows 11 24H2 tells the mode
// (activeColorMode). An older one only tells "advanced colour", which is HDR or the wide colour an SDR display is given:
// off is off, on without "wide colour enforced" is HDR, and on with it is not told apart here (not known, so the old
// question and no wrong word). Elsewhere not known (a Linux compositor lists HDR10 when it has HDR on).
// Asked at each swapchain while HDR is on and the surface SDR: a few hundredths of a millisecond beside a swapchain's
// tens, and an answer kept could outlive Windows' setting
int system_hdr_on(std::string* display) {
#ifdef _WIN32
    MONITORINFOEXW mi{};
    mi.cbSize = sizeof mi;
    if (!main_window || !GetMonitorInfoW(MonitorFromWindow(main_window, MONITOR_DEFAULTTONEAREST), &mi)) return -1;
    std::vector<DISPLAYCONFIG_PATH_INFO> paths;
    std::vector<DISPLAYCONFIG_MODE_INFO> modes;
    LONG r = ERROR_INSUFFICIENT_BUFFER;
    for (int tries = 0; r == ERROR_INSUFFICIENT_BUFFER && tries < 4; tries++) {   // (the displays can change in between)
        UINT32 np = 0, nm = 0;
        if (GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, &np, &nm) != ERROR_SUCCESS) return -1;
        paths.resize(np), modes.resize(nm);
        r = QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, &np, paths.data(), &nm, modes.data(), nullptr);
        paths.resize(np), modes.resize(nm);
    }
    if (r != ERROR_SUCCESS) return -1;
    for (const DISPLAYCONFIG_PATH_INFO& p : paths) {
        DISPLAYCONFIG_SOURCE_DEVICE_NAME source{};
        source.header = {DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME, sizeof source, p.sourceInfo.adapterId, p.sourceInfo.id};
        if (DisplayConfigGetDeviceInfo(&source.header) != ERROR_SUCCESS || wcscmp(source.viewGdiDeviceName, mi.szDevice)) continue;
        if (display) {
            DISPLAYCONFIG_TARGET_DEVICE_NAME target{};
            target.header = {DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME, sizeof target, p.targetInfo.adapterId, p.targetInfo.id};
            const bool named = DisplayConfigGetDeviceInfo(&target.header) == ERROR_SUCCESS && target.monitorFriendlyDeviceName[0];
            char utf8[256] = "";
            WideCharToMultiByte(CP_UTF8, 0, named ? target.monitorFriendlyDeviceName : mi.szDevice, -1, utf8, sizeof utf8 - 1,
                                nullptr, nullptr);
            *display = utf8;
        }
        AdvancedColorInfo2 info2{};
        info2.header = {(DISPLAYCONFIG_DEVICE_INFO_TYPE)kGetAdvancedColorInfo2, sizeof info2, p.targetInfo.adapterId,
                        p.targetInfo.id};
        if (DisplayConfigGetDeviceInfo(&info2.header) == ERROR_SUCCESS) return info2.active_color_mode == kAdvancedColorModeHdr;
        DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO info{};
        info.header = {DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO, sizeof info, p.targetInfo.adapterId, p.targetInfo.id};
        if (DisplayConfigGetDeviceInfo(&info.header) != ERROR_SUCCESS) return -1;
        return !info.advancedColorEnabled ? 0 : info.wideColorEnforced ? -1 : 1;
    }
#else
    (void)display;
#endif
    return -1;
}
// (hookshot) hookshot --prepare-shaders (a builder, after a build): the same work with no game, its progress as
// "@@progress" lines on stdout. A skip there leaves triforce_prepare_skipped beside the game: its own starts then
// leave the work out too (what was not prepared is built when first drawn), until a --prepare-shaders run ends it
bool prepare_only() { return getenv("HOOKSHOT_PREPARE_ONLY") != nullptr; }
// ((Triforce, 11-24) The journalled run's own limit, per entry (prepare_journal.h, --prepare-entry-limit <s>): with a journal,
// an entry that has been inside the driver for longer than one gets is named in the journal and the run ends at once with exit
// status 6 (prepare_journal::kExitEntryLimit), to be started again without that program. Looked at once a second, on a thread
// of its own. No journal, or no limit: nothing to do
void prepare_entry_watch() {
    const char* limit = getenv("HOOKSHOT_PREPARE_ENTRY_S");
    const char* journal = getenv("HOOKSHOT_PREPARE_JOURNAL");
    if (!limit || atoi(limit) <= 0 || !journal || !*journal) return;
    std::thread([] {
        for (;;) {
            Sleep(1000);
            if (prepare_journal_overdue()) {
                if (host && host->log_flush) host->log_flush();
                std::_Exit(prepare_journal::kExitEntryLimit);
            }
        }
    }).detach();
}
/// Before the parts of a --prepare-shaders run: what one a supervisor started needs. Nothing in a game run
void prepare_supervised() {
    if (!prepare_only()) return;
    prepare_entry_watch();
    prepare_restart_forgive();
}
std::string skipped_path() {
    char exe[MAX_PATH];
    const DWORD n = game_module_path(exe, MAX_PATH);
    std::string path(exe, n);
    return path.substr(0, path.find_last_of("\\/") + 1) + "triforce_prepare_skipped";
}
// ((Triforce, 11-18) A --prepare-shaders run asked from outside to stop: the file triforce_prepare.stop beside the game
// (nx2/make_game.py, when the run has been silent too long), or on Windows the event TRIFORCE_PREPARE_STOP names set (the
// builder's Cancel: a name of its own run's, Local\TriforcePrepareStop.<id>, which reaches the game through make_game.py's
// environment; not an RX_VK_ name, which would be in the shaders' stamp). Answered as a closed window is, prepare_stop:
// the part under way ends "stopped", what was made is saved and no journal is left (vk_draw.cpp warm_end). Killed instead,
// a start in the driver's part used one of its tries (gpl_rules.h kTries) and left what its workers had in the driver's
// hands on the skip list for good. Whoever asks still kills the run when it has not ended in a while: a driver call that
// hangs does not see the flag)
std::string stop_path() {
    char exe[MAX_PATH];
    const DWORD n = game_module_path(exe, MAX_PATH);
    std::string path(exe, n);
    return path.substr(0, path.find_last_of("\\/") + 1) + "triforce_prepare.stop";
}
class PrepareStopWatch {
public:
    PrepareStopWatch() {
#ifdef _WIN32
        const char* name = getenv("TRIFORCE_PREPARE_STOP");
        if (name && !strncmp(name, "Local\\TriforcePrepareStop.", 26)) event_ = CreateEventA(nullptr, TRUE, FALSE, name);
#endif
        thread_ = std::thread([this] {
            const std::string stop = stop_path();
            while (!over_.load()) {
                bool asked = false;
                if (FILE* f = fopen(stop.c_str(), "rb")) fclose(f), asked = true;
#ifdef _WIN32
                asked = asked || (event_ && WaitForSingleObject(event_, 0) == WAIT_OBJECT_0);
#endif
                if (asked) {
                    logf("vk: the shaders' preparation was asked to stop (%s or the builder's Cancel): stopping, what is done is kept",
                         stop.c_str());
                    prepare_stop();
                    return;
                }
                Sleep(200);
            }
        });
    }
    ~PrepareStopWatch() {
        over_.store(true);
        thread_.join();
#ifdef _WIN32
        if (event_) CloseHandle(event_);
#endif
        if (prepare_stopped()) remove(stop_path().c_str());   // (answered: the request is not left for a later run)
    }

private:
    std::atomic<bool> over_{false};
    std::thread thread_;
#ifdef _WIN32
    HANDLE event_ = nullptr;
#endif
};
// (hookshot) The first start after an update prepares every shader (prepare_run) and the pipelines the last sessions noted
// (precompile_run): a minute and more, before the game's first frame. They run on a thread of their own while this one, the
// renderer's start, shows the window at once with what they are doing on it, and keeps it shown and sized; on Windows it is also
// the window's thread, and handles its messages meanwhile (it would not answer otherwise). Closing the window stops them
// (mkwvk_close_asked): what was made is kept, the next start goes on from there. RX_VK_STARTUP_SCREEN=0: as before, all
// of it before the window shows anything (and a console with the count on Windows)
std::atomic<int> prep_stage{0};   // 0 the programs, 1 the pipelines the notes predict (a first start), 2 the noted pipelines
std::atomic<size_t> prep_done{0}, prep_total{0};
std::atomic<bool> prep_running{false}, prep_finished{false};
HANDLE prep_ended = nullptr;
#ifndef _WIN32
const MkwVkWindow* prep_window = nullptr;   // (its size)
#endif
void prep_progress(size_t done, size_t total) {
    prep_done.store(done, std::memory_order_relaxed);
    prep_total.store(total, std::memory_order_relaxed);
}
bool screen_wanted() {
    const char* e = getenv("RX_VK_STARTUP_SCREEN");
    return !e || atoi(e) != 0;
}
/// The window's size now (0x0: minimized, or unknown)
void window_size(uint32_t* w, uint32_t* h) {
    *w = *h = 0;
#ifdef _WIN32
    RECT r{};
    if (main_window && GetClientRect(main_window, &r)) *w = (uint32_t)(r.right - r.left), *h = (uint32_t)(r.bottom - r.top);
#else
    int width = 0, height = 0;
    if (prep_window) prep_window->drawable_size(prep_window->window, &width, &height);
    if (width > 0 && height > 0) *w = (uint32_t)width, *h = (uint32_t)height;
#endif
}
// (triforce) RX_VK_STARTUP_SHOTS=<folder>, a debug aid for a run with no window (HOS_HEADLESS): the start-up screen is shown
// all the same, into pictures. Without a window it is not shown at all (no swapchain to present to), and the shots of
// RX_VK_SHOTS are of the game's own presents. With this the painter draws each picture through the same menu_record as over a
// window's image, into an image of its own, and writes it to the folder as startup_<n>.png twice a second (the times in
// startup_shots.txt). The preparation runs behind it as behind the window's screen.
struct StartupShots {
    std::string dir;
    uint32_t w = 0, h = 0;
    VkImage image = VK_NULL_HANDLE;
    VmaAllocation alloc = nullptr;
    VkImageView view = VK_NULL_HANDLE;
    VkBuffer buf = VK_NULL_HANDLE;
    VmaAllocation buf_alloc = nullptr;
    void* map = nullptr;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkCommandBuffer cmd = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    bool on = false;
    int written = 0, painted = 0;
    double next = 0, every = 0.5;   // (seconds between the pictures written: RX_VK_STARTUP_SHOT_SECS, 0 every one)
    double ms_draw = 0, ms_gpu = 0, ms_write = 0, first_ms = 0, t_first = -1, t_last = 0;   // (where a picture's time goes)
};
StartupShots startup_shots;
const char* startup_shots_dir() {
    const char* e = getenv("RX_VK_STARTUP_SHOTS");
    return e && *e && dev.offscreen ? e : nullptr;
}
void startup_shot_layout(VkCommandBuffer cmd, VkImage image, VkImageLayout from, VkImageLayout to) {
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
    b.srcStageMask = b.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    b.srcAccessMask = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT, b.dstAccessMask = b.srcAccessMask;
    b.oldLayout = from, b.newLayout = to;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image;
    b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    VkDependencyInfo d{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    d.imageMemoryBarrierCount = 1, d.pImageMemoryBarriers = &b;
    vkCmdPipelineBarrier2(cmd, &d);
}
bool startup_shots_init() {
    StartupShots& s = startup_shots;
    s.dir = startup_shots_dir();
    if (const char* e = getenv("RX_VK_STARTUP_SHOT_SECS")) s.every = atof(e);
    s.w = dev.swap_extent.width, s.h = dev.swap_extent.height;
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.imageType = VK_IMAGE_TYPE_2D;
    ci.format = VK_FORMAT_R8G8B8A8_UNORM;   // (what the overlays draw into without a window: vk_imgui.cpp target_format)
    ci.extent = {s.w, s.h, 1};
    ci.mipLevels = ci.arrayLayers = 1;
    ci.samples = VK_SAMPLE_COUNT_1_BIT;
    ci.tiling = VK_IMAGE_TILING_OPTIMAL;
    ci.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    ci.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
    vi.format = ci.format;
    vi.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    VkCommandPoolCreateInfo pi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    pi.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pi.queueFamilyIndex = dev.queue_family;
    VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    ai.commandBufferCount = 1;
    VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    bool ok = create_image(ci, s.image, s.alloc);
    if (ok) vi.image = s.image, ok = vkCreateImageView(dev.device, &vi, nullptr, &s.view) == VK_SUCCESS;
    // (cached host memory: the picture is read back out of it)
    ok = ok && create_buffer_cached((uint64_t)s.w * s.h * 4, VK_BUFFER_USAGE_TRANSFER_DST_BIT, s.buf, s.buf_alloc, &s.map);
    ok = ok && vkCreateCommandPool(dev.device, &pi, nullptr, &s.pool) == VK_SUCCESS;
    if (ok) ai.commandPool = s.pool, ok = vkAllocateCommandBuffers(dev.device, &ai, &s.cmd) == VK_SUCCESS;
    ok = ok && vkCreateFence(dev.device, &fi, nullptr, &s.fence) == VK_SUCCESS;
    if (!ok) {
        logf("vk: start-up: RX_VK_STARTUP_SHOTS: the picture's image could not be made: no start-up screen in this run");
        return false;
    }
    // (menu_record draws over the window's image of an index: this one stands in for it while the screen shows)
    dev.swap_images.assign(1, s.image), dev.swap_views.assign(1, s.view);
    s.on = true;
    logf("vk: start-up: RX_VK_STARTUP_SHOTS: the start-up screen with no window, %ux%u, pictures in %s", s.w, s.h, s.dir.c_str());
    return true;
}
/// One picture of the screen, secs after the start; written out when `every` seconds have passed since the last one
void startup_shot_paint(double secs) {
    StartupShots& s = startup_shots;
    VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    if (vkBeginCommandBuffer(s.cmd, &bi) != VK_SUCCESS) return;
    startup_shot_layout(s.cmd, s.image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    const VkClearColorValue black{};
    const VkImageSubresourceRange all{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdClearColorImage(s.cmd, s.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &black, 1, &all);
    using clock = std::chrono::steady_clock;
    const auto ms_since = [](clock::time_point t) { return std::chrono::duration<double, std::milli>(clock::now() - t).count(); };
    const auto t_draw = clock::now();
    menu_record(s.cmd, 0, s.w, s.h);
    const double draw = ms_since(t_draw);
    const bool shot = secs >= s.next;
    if (shot) {
        startup_shot_layout(s.cmd, s.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        const VkBufferImageCopy c{0, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {s.w, s.h, 1}};
        vkCmdCopyImageToBuffer(s.cmd, s.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, s.buf, 1, &c);
    }
    vkEndCommandBuffer(s.cmd);
    VkCommandBufferSubmitInfo ci{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO};
    ci.commandBuffer = s.cmd;
    VkSubmitInfo2 si{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};
    si.commandBufferInfoCount = 1, si.pCommandBufferInfos = &ci;
    const auto t_gpu = clock::now();
    {
        std::lock_guard qk(dev.present_mu);   // (one queue: submits take turns)
        if (vkQueueSubmit2(dev.queue, 1, &si, s.fence) != VK_SUCCESS) return;
    }
    vkWaitForFences(dev.device, 1, &s.fence, VK_TRUE, UINT64_MAX);
    vkResetFences(dev.device, 1, &s.fence);
    // (the first picture makes ImGui, its fonts and the screen's textures: counted apart)
    if (!s.painted++) s.first_ms = draw + ms_since(t_gpu), s.t_first = secs;
    else s.ms_draw += draw, s.ms_gpu += ms_since(t_gpu);
    s.t_last = secs;
    if (!shot) return;
    const auto t_write = clock::now();
    invalidate_mapped(s.buf_alloc, (uint64_t)s.w * s.h * 4);
    char name[64];
    snprintf(name, sizeof name, "/startup_%04d.png", s.written);
    if (write_png((s.dir + name).c_str(), (const uint8_t*)s.map, s.w, s.h)) {
        if (FILE* f = fopen((s.dir + "/startup_shots.txt").c_str(), s.written ? "a" : "w")) {
            fprintf(f, "startup_%04d.png %.2f s, picture %d\n", s.written, secs, s.painted);
            fclose(f);
        }
        s.written++;
    }
    s.ms_write += ms_since(t_write);
    s.next = secs + s.every;
}
void startup_shots_done() {
    StartupShots& s = startup_shots;
    if (!s.on) return;
    s.on = false;
    dev.swap_images.clear(), dev.swap_views.clear();
    if (s.fence) vkDestroyFence(dev.device, s.fence, nullptr);
    if (s.pool) vkDestroyCommandPool(dev.device, s.pool, nullptr);
    if (s.view) vkDestroyImageView(dev.device, s.view, nullptr);
    if (s.image) destroy_image(s.image, s.alloc);
    if (s.buf) destroy_buffer(s.buf, s.buf_alloc);
    const int n = std::max(1, s.painted - 1);
    logf("vk: start-up: RX_VK_STARTUP_SHOTS: %d pictures painted in %.1f s (%.1f a second), %d written; the first took %.0f ms, the others %.2f ms "
         "to draw and record and %.2f ms on the GPU each; a written one %.0f ms more",
         s.painted, s.t_last - s.t_first, n / std::max(0.001, s.t_last - s.t_first), s.written, s.first_ms, s.ms_draw / n, s.ms_gpu / n,
         s.ms_write / std::max(1, s.written));
    s = StartupShots{};
}
void prepare_with_screen() {
    prep_ended = CreateEventA(nullptr, TRUE, FALSE, nullptr);
    prep_running.store(true);
    std::thread worker([] {
        const bool update = prepare_is_update();   // (an update, RX_VK_PREPARE_BACKGROUND=1: what the notes name now, the rest in play)
        const bool prepared = !update && prepare_run(prep_progress, false);
        if (update) state_list_run();   // (as the start without a screen does, below: the state lists' pipelines before the precompile)
        // (a first start only: the pipelines the notes predict, into the driver's cache. (Triforce, 11-24) As Compile shaders says:
        // predict_before_title)
        if (!update && !prepare_stopped() && predict_before_title(prepared)) {
            prep_done.store(0), prep_total.store(0);
            prep_stage.store(1);
            predict_run(prep_progress);
        }
        if (!prepare_stopped()) {
            prep_done.store(0), prep_total.store(0);
            prep_stage.store(2);
            predict_plan_ensure();
            precompile_run(prep_progress);
            predict_background();
        }
        if (prepare_stopped()) pipeline_cache_save(true);   // (the driver's part built so far, for the next start)
        else if (update) prepare_background();
        prep_finished.store(true, std::memory_order_release);
        SetEvent(prep_ended);
    });
    // (the screen is drawn and presented on a thread of its own: a present can wait for as long as the window cannot be seen (FIFO
    // on Wayland, a locked screen), and that must hold neither the window's messages nor the game's start)
    using clock = std::chrono::steady_clock;
    const auto t0 = clock::now();
    static std::atomic<bool> paint_stop{false};
    HANDLE painted = CreateEventA(nullptr, TRUE, FALSE, nullptr);
    // (the screen moves: 60 pictures a second, RX_VK_STARTUP_FPS=30: as it was before it did. A picture is a few thousand
    // vertices and one present, on this thread alone)
    static int paint_ms = 16;
    if (const char* e = getenv("RX_VK_STARTUP_FPS")) paint_ms = 1000 / std::clamp(atoi(e), 10, 240);
    std::thread painter([t0, painted] {
        ProgressClock eta;
        int eta_stage = -1;
        double next_log = 10;
        bool prepared = false;   // (this start prepares the programs: a first start after an update, two steps)
        uint32_t last_w = dev.swap_extent.width, last_h = dev.swap_extent.height;
        for (;;) {
            const bool finished = prep_finished.load(std::memory_order_acquire);
            const double secs = std::chrono::duration<double>(clock::now() - t0).count();
            const int stage = prep_stage.load();
            const int pass = stage == 0 ? prepare_pass() : 0;   // (the programs: translated, then the driver's part of them)
            const size_t done = prep_done.load(std::memory_order_relaxed), total = prep_total.load(std::memory_order_relaxed);
            if (stage * 2 + pass != eta_stage) eta.reset(), eta_stage = stage * 2 + pass;
            if (total) eta.note(secs, done, total);
            const double left = total ? eta.left() : -1;
            if (secs >= next_log && total) {
                logf("vk: start-up: %s %zu of %zu%s%s", stage == 2 ? "pipelines" : stage ? "predicted pipelines" : pass ? "shaders compiled" : "shaders", done, total, left >= 0 ? ", " : "",
                     left_text(left).c_str());
                next_log = secs + 10;
            }
            if (stage == 0 && total) prepared = true;
            StartupState st;
            st.stage = stage, st.pass = pass, st.done = done, st.total = total, st.left = left, st.secs = secs;
            st.prepared = prepared, st.finished = finished, st.stopping = prepare_stopped();
            st.overdue = total && eta.overdue(secs);
            st.compile = prepare_compiles();
            StartupView view = startup_view(st);
            view.device = dev.props.deviceName;
            // (an sRGB window image with no UNORM view blends the overlays in linear light, vk_imgui.cpp: the screen's lights allow for it)
            view.linear = dev.swap_view_format == VK_FORMAT_B8G8R8A8_SRGB || dev.swap_view_format == VK_FORMAT_R8G8B8A8_SRGB ||
                          dev.swap_view_format == VK_FORMAT_A8B8G8R8_SRGB_PACK32;
            startup_screen(&view);
            uint32_t w, h;
            window_size(&w, &h);
            if (w && h && (w != last_w || h != last_h)) {   // (resized: the window's thread leaves it to the renderer, not started yet)
                dev.swap_resize.store((uint64_t)w << 32 | h, std::memory_order_release);
                last_w = w, last_h = h;
            }
            if (startup_shots.on) startup_shot_paint(secs);   // (no window, RX_VK_STARTUP_SHOTS: a picture)
            else if (w && h) present_image(nullptr, dev.swap_extent.width, dev.swap_extent.height, nullptr);
            if (finished || paint_stop.load()) break;
            Sleep((DWORD)paint_ms);
        }
        // (the end: a fade to black over 0.4 s, so the game's first frame comes out of black, not cut in over the screen; none
        // after a screen of under 1.5 s, a blink, or when the window is not shown (paint_stop: its presents wait))
        const double shown = std::chrono::duration<double>(clock::now() - t0).count();
        if (shown >= 1.5 && !paint_stop.load()) {
            const auto f0 = clock::now();
            for (;;) {
                const double f = std::chrono::duration<double>(clock::now() - f0).count() / 0.4;
                startup_fade_to((float)std::min(f, 1.0));
                uint32_t w, h;
                window_size(&w, &h);
                if (startup_shots.on) startup_shot_paint(std::chrono::duration<double>(clock::now() - t0).count());
                else if (w && h) present_image(nullptr, dev.swap_extent.width, dev.swap_extent.height, nullptr);
                if (f >= 1 || paint_stop.load()) break;
                Sleep(8);
            }
        }
        // (the screen's own textures are let go in one last picture, black, that draws none of them: vk_startup_screen.h. Not
        // when the window is not being shown: that present would wait, and the screen is gone by then)
        if (!paint_stop.load()) {
            startup_fade_to(2);
            uint32_t w, h;
            window_size(&w, &h);
            if (startup_shots.on) startup_shot_paint(std::chrono::duration<double>(clock::now() - t0).count());
            else if (w && h) present_image(nullptr, dev.swap_extent.width, dev.swap_extent.height, nullptr);
        }
        SetEvent(painted);
    });
    // (this thread: the window's messages on Windows, until the work is done)
    for (;;) {
#ifdef _WIN32
        MSG m;
        while (PeekMessageA(&m, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&m);
            DispatchMessageA(&m);
        }
#endif
        if (WaitForSingleObject(prep_ended, 33) == WAIT_OBJECT_0) break;
    }
    worker.join();
    // (the painter ends by itself once the work is finished, after its fade; it is told to stop only when it has not by then)
    if (startup_shots.on) WaitForSingleObject(painted, INFINITE);   // (pictures, not a window: no present of it waits to be seen)
    if (WaitForSingleObject(painted, 1500) == WAIT_OBJECT_0) painter.join();
    else {
        paint_stop.store(true);   // (its present waits for the window to be seen: the game's own presents will, too)
        logf("vk: start-up: the window is not being shown; the game starts without waiting for it");
        painter.detach();
    }
    startup_screen(nullptr);
    prep_running.store(false);
    logf("vk: start-up: the shaders took %.1f s", std::chrono::duration<double>(clock::now() - t0).count());
}
bool started_up() {
    if (const char* e = getenv("RX_VK_START_DELAY")) Sleep((DWORD)atoi(e) * 1000);   // (diagnosis: a long start, as the first one is)
    if (!replay_start()) return false;
    // (Triforce, 11-13: vk_draw.cpp driver_fault_restart)
    struct StartupWork {
        StartupWork() { startup_work_on.store(true); }
        ~StartupWork() { startup_work_on.store(false), programs_play_begin(); }   // ((Triforce) the life log's census: play from here)
    } startup_work;
    if (prepare_only()) {
        // (three parts: the programs, the pipelines the notes predict, then those they name; most of the time is the first)
        static int part;
        // ((Triforce, 11-18) the bar's share of each part as it takes its time: on NVIDIA the programs are most of it (56 s of
        // ~70 on an RTX 4070 SUPER); elsewhere the pipelines, which AMD's driver builds in seconds each (an update on an AMD card
        // ran over an hour in that last part and sat at 90% and more: Setup's "Preparing shaders" row shows this bar)
        static const bool nvidia = dev.props.vendorID == 0x10de;
        const auto progress = [](size_t done, size_t total) {
            static size_t last = ~(size_t)0;
            if (!total) return;
            static const size_t from_nv[3] = {0, 700, 900}, span_nv[3] = {700, 200, 100};
            static const size_t from_other[3] = {0, 300, 400}, span_other[3] = {300, 100, 600};
            const size_t* from = nvidia ? from_nv : from_other;
            const size_t* span = nvidia ? span_nv : span_other;
            const size_t at = from[part] + done * span[part] / total;
            if (at == last) return;
            last = at;
            printf("@@progress %.3f\n", at / 1000.0);
            fflush(stdout);
        };
        printf("@@stage shaders Preparing shaders\n");
        fflush(stdout);
        // ((Triforce, 11-24) a run a supervisor started (prepare_journal.h): the run before taken off the crash markers, and the
        // watch of one entry's time inside the driver (HOOKSHOT_PREPARE_ENTRY_S with HOOKSHOT_PREPARE_JOURNAL; none without)
        prepare_supervised();
        // ((Triforce) AMD FSR 4's pipelines with its tune on (RX_VK_FSR4_TUNE=1), first: its unrolled layers ask several GB of
        // memory to build, before the shader caches are read)
        fsr4_prepare_shaders();
        {
            const PrepareStopWatch watch;   // ((Triforce, 11-18) a stop asked from outside, while the work lasts)
            part = 0;
            bool prepared = prepare_run(progress, false);
            // ((Triforce) the pipeline cache carried over the stamp change grew past what it may hold, or would at the rate it
            // grew (pcache_carry.h, the early drop): not kept, a fresh one built again, from the driver's own cache for what this
            // run compiled. Nothing is translated again; the bar starts its part again, as it does between the programs and their
            // driver part, and Setup's log says why. Not after a stop: pcache_carry_rebuild says no then)
            if (pcache_carry_rebuild()) {
                printf("The old pipeline cache grew, or would grow, too large to keep: building the shaders' driver part again "
                       "into a fresh one (nothing is translated again)\n");
                fflush(stdout);
                prepared = prepare_run(progress, false);
            }
            part = 1;
            if (!prepare_stopped() && predict_before_title(prepared)) predict_run(progress);   // ((Triforce, 11-24) compile_level.h)
            part = 2;
            if (!prepare_stopped()) {   // (as prepare_with_screen: a stopped run goes no further, and keeps what it made)
                predict_plan_ensure();
                precompile_run(progress);
                predict_background();
            }
        }
        pipeline_cache_save(true);
        if (prepare_stopped()) {   // (the builders read this line's start: nx2/make_game.py NOT_PREPARED)
            printf("the shaders were not prepared now (the preparation was asked to stop): the game goes on with them at its "
                   "first start\n");
            fflush(stdout);
            return true;
        }
        // ((Triforce) gone through to its end and saved: a carried cache's history is no longer open, so the next start reads
        // the file as these shaders' own. A stopped one stays open: the preparation begun again is carried still, capped)
        pcache_carry_done();
        remove(skipped_path().c_str());
        return true;
    }
    if (FILE* f = fopen(skipped_path().c_str(), "rb")) {
        fclose(f);
        logf("vk: the shaders' preparation was skipped at the build: left to when each is first drawn");
        texture_pipelines_unprepared();   // ((Triforce) no precompile: the texture converters' pipelines made here all the same)
        return true;
    }
    if (precompile_wanted()) {   // (a release build, before the game: nothing to build during play)
        if (startup_shots_dir() && startup_shots_init()) {   // (no window, a debug aid: the screen all the same, as pictures)
            prepare_with_screen();
            startup_shots_done();
            return true;
        }
        if (!dev.offscreen && screen_wanted()) {
            prepare_with_screen();
            return true;
        }
        // (a console while it lasts: there is no window yet, and a long wait with nothing on screen looks like a hang)
        static HANDLE console = nullptr;
        const auto progress = [](size_t done, size_t total) {
            static bool tried = false;
            if (!total) return;
            if (!tried) {
                tried = true;
                if (AllocConsole()) {
#ifdef _WIN32
                    // This console is ours. Selection must not block preparation's progress writes.
                    const HANDLE input = CreateFileA("CONIN$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                                     nullptr, OPEN_EXISTING, 0, nullptr);
                    if (input != INVALID_HANDLE_VALUE) {
                        DWORD mode;
                        if (GetConsoleMode(input, &mode))
                            SetConsoleMode(input, (mode & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS);
                        CloseHandle(input);
                    }
#endif
                    SetConsoleTitleA("Triforce");
                    console = CreateFileA("CONOUT$", GENERIC_WRITE, FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
                    if (console == INVALID_HANDLE_VALUE) console = nullptr;
                }
            }
            {   // (in the log too, every 10 s: a run with no window has nothing else to show it)
                static DWORD next_log = 0;
                const DWORD now = GetTickCount();
                if (!next_log) next_log = now + 10000;
                if ((int32_t)(now - next_log) >= 0) {
                    logf("vk: start-up: %zu of %zu", done, total);
                    next_log = now + 10000;
                }
            }
            if (!console) return;
            char line[80];
            const int n = snprintf(line, sizeof line, "%cPreparing shaders: %zu of %zu (%zu%%)   ", 13, done, total, done * 100 / total);
            DWORD wrote = 0;
            WriteFile(console, line, (DWORD)n, &wrote, nullptr);
        };
        const bool update = prepare_is_update();   // (an update: what the notes name now, the rest in play)
        if (!update && predict_before_title(prepare_run(progress, false))) predict_run(progress);   // ((Triforce, 11-24) compile_level.h)
        predict_plan_ensure();
        if (update) state_list_run();
        precompile_run(progress);
        predict_background();
        if (update) prepare_background();
        if (console) CloseHandle(console), console = nullptr, FreeConsole();
    }
    return true;
}
// (the window's surface made: the presents' own queue kept where its family can present to it, create_device)
static void choose_present_queue() {
    if (!dev.present_queue) return;
    VkBool32 ok = VK_FALSE;
    if (vkGetPhysicalDeviceSurfaceSupportKHR(dev.physical, dev.present_family, dev.surface, &ok) != VK_SUCCESS || !ok) {
        logf("vk: queue family %u cannot present to the window: presents on the replay's queue", dev.present_family);
        dev.present_queue = VK_NULL_HANDLE, dev.present_family = dev.queue_family;
        return;
    }
    logf("vk: presents on a queue of their own, of compute family %u (RX_VK_PRESENT_QUEUE=0: off)", dev.present_family);
}

/// (Triforce, 11-22, the performance audit's PRESENT-45, after Source A's) A surface for the window again, after the one
/// before was lost and let go (invalidate_lost_surface): the calls start() makes below, for the window it was given.
/// False, with no surface, while the window has no size (minimized: it waits), or when the surface cannot be made or the
/// replay's queue cannot present to it (said when log_failure, the first 8 times). The presents' own queue is chosen
/// again for the new surface. From create_swapchain, dev.present_mu held
bool open_window_surface(bool log_failure) {
    static int said;
#ifdef _WIN32
    if (!main_window) return false;
    RECT r{};
    GetClientRect(main_window, &r);
    if (r.right - r.left <= 0 || r.bottom - r.top <= 0) return false;
    VkWin32SurfaceCreateInfoKHR si{VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR};
    si.hinstance = GetModuleHandleA(nullptr);
    si.hwnd = main_window;
    if (vkCreateWin32SurfaceKHR(dev.instance, &si, nullptr, &dev.surface) != VK_SUCCESS) {
        dev.surface = VK_NULL_HANDLE;
        if (log_failure && said++ < 8) logf("vk: the window's surface could not be made again: tried again every 250 ms");
        return false;
    }
#else
    const MkwVkWindow* w = prep_window;
    if (!w) return false;
    int width = 0, height = 0;
    w->drawable_size(w->window, &width, &height);
    if (width <= 0 || height <= 0) return false;
    if (!w->create_surface(w->window, (void*)dev.instance, (void*)&dev.surface)) {
        dev.surface = VK_NULL_HANDLE;
        if (log_failure && said++ < 8) logf("vk: the window's surface could not be made again: tried again every 250 ms");
        return false;
    }
#endif
    VkBool32 ok = VK_FALSE;
    if (vkGetPhysicalDeviceSurfaceSupportKHR(dev.physical, dev.queue_family, dev.surface, &ok) != VK_SUCCESS || !ok) {
        if (log_failure && said++ < 8)
            logf("vk: the replay's queue cannot present to the window's new surface: tried again every 250 ms");
        vkDestroySurfaceKHR(dev.instance, dev.surface, nullptr);
        dev.surface = VK_NULL_HANDLE;
        return false;
    }
    choose_present_queue();
    return true;
}

int start(void* hwnd) {
    main_window = (HWND)hwnd;
    if (!hwnd) {   // (HOS_HEADLESS: no window; the frames are rendered all the same, RX_VK_SHOTS writes them out)
        dev.offscreen = true;
        dev.swap_extent = {1920, 1080};
        dev.swap_format = VK_FORMAT_R8G8B8A8_UNORM;
        logf("vk: no window: presents render offscreen (%ux%u)", dev.swap_extent.width, dev.swap_extent.height);
        return started_up() ? 1 : 0;
    }
#ifdef _WIN32
    VkWin32SurfaceCreateInfoKHR si{VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR};
    si.hinstance = GetModuleHandleA(nullptr);
    si.hwnd = (HWND)hwnd;
    if (vkCreateWin32SurfaceKHR(dev.instance, &si, nullptr, &dev.surface) != VK_SUCCESS) return 0;
    VkBool32 ok = VK_FALSE;
    vkGetPhysicalDeviceSurfaceSupportKHR(dev.physical, dev.queue_family, dev.surface, &ok);
    if (!ok) return 0;
    choose_present_queue();
    RECT r{};
    GetClientRect((HWND)hwnd, &r);
    if (!create_swapchain((uint32_t)(r.right - r.left), (uint32_t)(r.bottom - r.top))) return 0;
#else
    const MkwVkWindow* w = (const MkwVkWindow*)hwnd;
    prep_window = w;
    if (w->version < 1 || w->version > MKWVK_WINDOW_VERSION) {   // (1: no refresh_mhz)
        logf("vk: unsupported SDL window bridge version %u (expected %u)", w->version, MKWVK_WINDOW_VERSION);
        return 0;
    }
    if (!w->create_surface(w->window, (void*)dev.instance, (void*)&dev.surface)) {
        logf("vk: SDL_Vulkan_CreateSurface failed; check SDL_VIDEODRIVER and the Vulkan window-system extensions");
        return 0;
    }
    VkBool32 ok = VK_FALSE;
    VkResult present = vkGetPhysicalDeviceSurfaceSupportKHR(dev.physical, dev.queue_family, dev.surface, &ok);
    if (present != VK_SUCCESS || !ok) {
        logf("vk: queue-family present support failed (VkResult %d, supported %u)", (int)present, ok);
        return 0;
    }
    choose_present_queue();
    int width = 0, height = 0;
    w->drawable_size(w->window, &width, &height);
    if (width <= 0 || height <= 0) {
        logf("vk: SDL returned zero drawable size %dx%d", width, height);
        return 0;
    }
    if (!create_swapchain((uint32_t)width, (uint32_t)height)) {
        logf("vk: swapchain creation failed for drawable %dx%d", width, height);
        return 0;
    }
#endif
    if (!started_up()) {
        logf("vk: renderer startup failed after window and swapchain initialization");
        return 0;
    }
    return 1;
}

// (the window's thread: only noted. The swapchain is remade by whoever presents next, in present_image: made here, it went from under a
// frame between its acquire and its submit, and the frame's commands named images of the swapchain just destroyed: a lost device)
void resize(int width, int height) {
    if (dev.offscreen || width <= 0 || height <= 0) return;
    dev.swap_resize.store((uint64_t)(uint32_t)width << 32 | (uint32_t)height, std::memory_order_release);
}

const char* describe() {
    static std::string d;
    d = std::string(dev.props.deviceName) + " (Vulkan, native)";
    return d.c_str();
}

MkwVkRenderer table;

} // namespace
/// ((Triforce, 11-22, PIPE-23) prepare_only, above, for vk_draw.cpp's precompile_end_save (vk_internal.h))
bool prepare_only_start() { return prepare_only(); }
} // namespace mkwvk

// (hookshot) The window is being closed (host/display.c, host/posix/display_sdl.c, before they end the process): while the
// shaders are prepared, their workers are stopped and what they made is kept first (10 s at most: a driver can take longer on one
// pipeline). Before that, the file that counts the starts that crashed in the precompile is put back as this start found it
// (crash_markers.h): a quit is not a crash, nor is a process ended while it closes. Looked up by name, so an executable and
// a back end of different versions still close
extern "C"
#ifdef _WIN32
__declspec(dllexport)
#else
__attribute__((visibility("default")))
#endif
void mkwvk_close_asked(void) {
    using namespace mkwvk;
    // (before anything that takes time: the 10 s for the workers below, with the window not answering. A player who quits
    // again then ends the process (End task), and so does the system at a log-out: that end comes after a quit, and must not
    // count as a crash either)
    crash_markers::close();
    programs_census_log("close");   // ((Triforce) RX_VK_LOG_PROGRAM_LIFE or RX_VK_LOAD=create: vk_programs.h)
    module_ids_flush();
    page_table_census_log("close");   // ((Triforce) the guest pools the page table cannot reach: how many came, vk_memory.cpp)
    page_table_check_close();         // ((Triforce) RX_VK_GP_TABLE: its bindings covered, and with =2 the loads checked, vk_draw.cpp)
    fsr4_close();   // (AMD FSR 4's tuned layers: their background builds stopped before the exit's saves)
    if (!prep_running.load() || prepare_stopped()) return;
    logf("vk: the window was closed while the shaders were prepared: stopping, what is done is kept");
    prepare_stop();
    if (WaitForSingleObject(prep_ended, 10000) != WAIT_OBJECT_0) logf("vk: the preparation did not stop within 10 s: closing anyway");
}

// ---- (Triforce, 11-22, the performance audit's OS-04, after Source A's and Source B's: new_wait.h) a refused `new` ----
namespace mkwvk {
/// The system's commit left (false: not known: elsewhere a card's memory is not charged to it)
bool new_commit_left(uint64_t* avail) {
#ifdef _WIN32
    MEMORYSTATUSEX ms{};
    ms.dwLength = sizeof ms;
    if (!GlobalMemoryStatusEx(&ms)) return false;
    *avail = ms.ullAvailPageFile;
    return true;
#else
    (void)avail;
    return false;
#endif
}
/// The renderer's new handler: at Windows' commit limit a refused allocation sleeps 50 ms and is tried again, up to
/// HOS_COMMIT_WAIT_MS (5 s) a thread; then, or with 4 GiB of commit or more left, or in a NoWait scope, it throws as before
void new_refused() {
    static const int max_ms = new_wait::wait_ms(getenv("HOS_COMMIT_WAIT_MS"));
    uint64_t avail = 0;
    const bool known = new_commit_left(&avail);
    if (!new_wait::waits(known, avail, new_wait::t_waited_ms, max_ms, new_wait::t_no_wait)) throw std::bad_alloc();
    static std::atomic<int> told{0};
    const int n = told.fetch_add(1);
    if (n == 0) {   // ((Triforce, 11-26) as host/mkw_glue.c hos_commit_limit_mark: the next start says so, once)
        // (no allocation here: this is the new handler, at the commit limit)
        char path[MAX_PATH + 32];
        const DWORD len = game_module_path(path, MAX_PATH);
        char* slash = len ? strrchr(path, '\\') : nullptr;
        if (!slash && len) slash = strrchr(path, '/');
        if (slash) {
            snprintf(slash + 1, sizeof path - (size_t)(slash + 1 - path), "triforce_commit_limit.txt");
            if (FILE* f = fopen(path, "w")) {
                fputs("Windows' commit limit (RAM and page file) was reached in the last session: the next start says so\n", f);
                fclose(f);
            }
        }
    }
    if (n < 8)
        logf("vk: an allocation refused with %llu MB of the system's commit left: tried again for up to %d ms (HOS_COMMIT_WAIT_MS)",
             (unsigned long long)(avail >> 20), max_ms);
    Sleep(new_wait::kStepMs);
    new_wait::t_waited_ms += new_wait::kStepMs;
}
} // namespace mkwvk

static const MkwVkRenderer* init_body(const MkwVkHost* h);
extern "C"
#ifdef _WIN32
__declspec(dllexport)
#else
__attribute__((visibility("default")))
#endif
const MkwVkRenderer* mkwvk_init(const MkwVkHost* h) {
    try {
        return init_body(h);
    } catch (const std::exception& e) {
        mkwvk::cxx_escape::escaped("mkwvk_init", e);   // (said, then the game stops; before the hooks are set, on stderr)
    }
}
/// mkwvk_init's work, behind its catch
static const MkwVkRenderer* init_body(const MkwVkHost* h) {
    using namespace mkwvk;
    if (!h || h->version != MKWVK_API_VERSION) return nullptr;
    host = h;
    std::set_new_handler(new_refused);   // ((Triforce, OS-04) a `new` refused at the commit limit waits before it throws)
    // ((Triforce) a C++ exception out of the renderer, the bad_alloc that handler throws in the end among them: said with its
    // type and what(), then the FATAL line (cxx_escape.h; no out-of-memory hook: the host has no notice of its own to call))
    cxx_escape::g_hooks.log = [](const char* line) { logf("%s", line); };
    cxx_escape::g_hooks.fatal = [](const char* why) { vk_fatal(why); };   // (vk_replay.cpp replay_fatal: logged, the host's log written out, exit code 3)
    if (!load_global()) {
#ifdef _WIN32
        logf("vk: vulkan-1.dll not found");
#else   // ((Triforce, 11-24) linux: why libvulkan.so.1 did not load, kept by LoadLibraryA from dlerror(); "" if it loaded)
        const char* why = hos_load_error();
        logf("vk: the Vulkan loader (libvulkan.so.1) or its vkGetInstanceProcAddr was not found%s%s", *why ? ": " : "", why);
#endif
        return nullptr;
    }
    if (!create_instance() || !pick_device() || !create_device()) return nullptr;
    // ((Triforce) the stamp is whole once the device is (coopmat_init's switches): the caches' kept set, before any of them
    // is opened. cache_set.h)
    cache_set_init();
    logf("vk: %s, Vulkan %u.%u, driver %#x; mesh shaders %s, host memory import %s, pipeline libraries %s",
         dev.props.deviceName, VK_VERSION_MAJOR(dev.props.apiVersion), VK_VERSION_MINOR(dev.props.apiVersion),
         dev.props.driverVersion, dev.mesh_shader ? "yes" : "no", dev.external_memory_host ? "yes" : "no",
         dev.graphics_pipeline_library ? "yes" : "no");
    // ((Triforce, 11-22, the performance audit's PRESENT-46, after Source A's) the card is known now, which menu_init (inside
    // pick_device) was not given: a first start on a weak card takes its Render resolution, with RX_VK_FIRST_START_AUTO
    menu_first_start();
    if (!dev.mesh_shader && !dev.mesh_fallback && !getenv("RX_VK_NO_MESH_WARNING")) {
        // (the game draws its foliage, grass and many effects with mesh shaders: without them those draws are left out and the
        // picture is broken (an RX 580's "static"-like scenes, 2026-11-08). Said once, on its own thread, and the game goes on.)
        // (a GPU with no buffer device addresses has no fallback to run either)
        logf("vk: this GPU has no mesh shaders: the game's foliage, grass and many effects cannot be drawn");
#ifdef _WIN32
        std::thread([name = std::string(dev.props.deviceName)] {
            const std::string text = "Your graphics card (" + name + ") or its driver has no mesh shader support, which Ocarina of Time "
                "uses for foliage, grass and many effects, so parts of the picture will be missing or broken.\n\nTriforce needs a GPU "
                "with mesh shaders: NVIDIA GeForce RTX 20 series or newer, AMD Radeon RX 6000 series or newer, or Intel Arc. If your "
                "card is one of those, update its driver.";
            MessageBoxA(nullptr, text.c_str(), "Triforce: graphics card", MB_OK | MB_ICONWARNING | MB_TOPMOST);
        }).detach();
#endif
    }
    table.version = MKWVK_API_VERSION;
    table.start = start;
    table.resize = resize;
    table.describe = describe;
    fill_replay_table(table);
    guard_renderer(table);   // ((Triforce) each function's exceptions said and stopped on, not left to the host's C: renderer_guard.h)
    return &table;
}

namespace mkwvk {
HWND app_window() { return main_window; }   // (hookshot: the Insert menu's Fullscreen row)

/// (hookshot) The refresh rate of the display the window is on, in mHz; 0 when not known (frame generation's Auto). Asked
/// again once a second at most: the window may move to another display, and Windows' answer costs a few system calls
int display_refresh_mhz() {
    static std::atomic<int> cached{0};
    static std::atomic<int64_t> asked_at{0};
    const int64_t now = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
    const int64_t last = asked_at.load(std::memory_order_relaxed);
    if (last && now - last < 1000) return cached.load(std::memory_order_relaxed);
    asked_at.store(now, std::memory_order_relaxed);
    int mhz = 0;
#ifdef _WIN32
    MONITORINFOEXW mi{};
    mi.cbSize = sizeof mi;
    DEVMODEW dm{};
    dm.dmSize = sizeof dm;
    if (main_window && GetMonitorInfoW(MonitorFromWindow(main_window, MONITOR_DEFAULTTONEAREST), &mi) &&
        EnumDisplaySettingsW(mi.szDevice, ENUM_CURRENT_SETTINGS, &dm) && dm.dmDisplayFrequency > 1)   // (0 and 1: the default)
        // (whole Hz: a 59.94 Hz mode often says 59, and Auto would then make a frame too few a second. One under a
        // multiple of 6 (24, 30, 60, 120, 144, 240 Hz) is taken as that rate's /1.001)
        mhz = (dm.dmDisplayFrequency + 1) % 6 == 0 ? (int)((dm.dmDisplayFrequency + 1) * 1000000ull / 1001)
                                                    : (int)dm.dmDisplayFrequency * 1000;
#else
    const MkwVkWindow* w = (const MkwVkWindow*)main_window;
    if (w && w->version >= 2 && w->refresh_mhz) mhz = w->refresh_mhz(w->window);
#endif
    cached.store(mhz, std::memory_order_relaxed);
    return mhz;
}
} // namespace mkwvk
