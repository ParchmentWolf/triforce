// A pipeline cache file of stage libraries and compute pipelines alone, on NVIDIA PCs of little RAM (no game, no GPU: the
// rule, the driver's cache folder and its size, the record; vk_draw.cpp pcache_libs_decide, pcache_init, build_graphics,
// pcache_play_open). Apart from Vulkan so that tests/test_pcache_libs.py runs it on many made-up PCs.
//
// (Triforce, 11-22, the performance audit's PIPE-78, after Source A's and Source B's.) mkw_vk_pipelines.bin is read whole at
// every start and held by the driver all session: about 650 MB fresh, 1.1 to 1.6 GB with the play's pipelines on a 16 GB PC
// (pcache_bound.h), where paging is what hitches. Source A leaves its file unread on NVIDIA's own driver with 20 GB of RAM or
// less and 512 MB or more in the driver's own disk cache (GLCache), whole pipelines then coming from that cache: on a 16 GB
// RTX 3070 Ti, peak memory 12,481 -> 12,029 and 12,638 -> 11,822 MB over a tour, fps 54.3 -> 54.6, a pipeline's load 1.9 ->
// 5.0 ms. Triforce cannot drop the file: a stage library asked under the compile-required flag must be in the cache it hands
// the driver (21 of 21 cold otherwise). So the file keeps the libraries and the compute pipelines, and only whole graphics
// pipelines are left to the driver's cache, with no play file.
//
// Decided only when a fresh file begins (none read for these shaders), and kept in <file>.lean ("lean <stamp>") for that
// file's life: a full file stays full and a lean one lean until the next fresh one. Not in a start that only prepares.
//
// RX_VK_PCACHE_LIBS_ONLY: unset or 0, off (every pipeline in the file, as before); 1, by the rule; 2, at every fresh file
// whatever the PC (the lab's and the tests'). Off by default: the driver's cache is shared and capped, and on a 32 GB PC
// Source A measured p99 17.23 -> 18.58 ms.
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <system_error>

namespace pcache_libs {

inline constexpr uint64_t kRamMost = 20ull << 30;          // (20 GB of RAM or less)
inline constexpr uint64_t kGlCacheLeast = 512ull << 20;    // (512 MB or more in the driver's own cache)

/// RX_VK_PCACHE_LIBS_ONLY: 0 off (unset too), 1 by the rule, 2 forced
inline int mode(const char* env) {
    if (!env || !*env) return 0;
    const int v = std::atoi(env);
    return v <= 0 ? 0 : v >= 2 ? 2 : 1;
}

struct Pc {
    bool nvidia_proprietary = false;   // (VK_DRIVER_ID_NVIDIA_PROPRIETARY)
    uint64_t ram = 0;                  // (the PC's RAM, bytes; 0 unknown)
    uint64_t glcache = 0;              // (bytes in the driver's own cache folder)
    bool gpl = false;                  // (the stage libraries are wanted and kept in our cache: gpl_wanted, gpl_libs_cached)
    bool prepare_only = false;         // (a start that only prepares)
};
/// Whether the fresh file is a lean one
inline bool choose(int mode, const Pc& pc) {
    if (mode <= 0 || pc.prepare_only) return false;
    if (mode >= 2) return true;
    return pc.nvidia_proprietary && pc.gpl && pc.ram && pc.ram <= kRamMost && pc.glcache >= kGlCacheLeast;
}

/// The folder NVIDIA's driver keeps its Vulkan and OpenGL cache in: on Windows <LOCALAPPDATA>\NVIDIA\GLCache; elsewhere
/// __GL_SHADER_DISK_CACHE_PATH, else <XDG_CACHE_HOME>/nvidia/GLCache, else <HOME>/.cache/nvidia/GLCache. Empty: unknown
inline std::string nvidia_cache_dir(bool windows, const char* localappdata, const char* gl_path, const char* xdg, const char* home) {
    if (windows) return localappdata && *localappdata ? std::string(localappdata) + "\\NVIDIA\\GLCache" : std::string();
    if (gl_path && *gl_path) return gl_path;
    if (xdg && *xdg) return std::string(xdg) + "/nvidia/GLCache";
    if (home && *home) return std::string(home) + "/.cache/nvidia/GLCache";
    return {};
}
/// The bytes of the files under a folder, at most most_entries looked at (a folder that is not there: 0)
inline uint64_t folder_bytes(const std::string& dir, size_t most_entries = 200000) {
    uint64_t sum = 0;
    if (dir.empty()) return 0;
    std::error_code ec;
    const std::filesystem::path root(std::u8string(reinterpret_cast<const char8_t*>(dir.data()), dir.size()));   // (UTF-8)
    std::filesystem::recursive_directory_iterator it(root, std::filesystem::directory_options::skip_permission_denied, ec);
    for (size_t n = 0; !ec && it != std::filesystem::recursive_directory_iterator() && n < most_entries; it.increment(ec), n++) {
        std::error_code e2;
        if (it->is_regular_file(e2)) {
            const uint64_t s = it->file_size(e2);
            if (!e2) sum += s;
        }
    }
    return sum;
}

// ---- <file>.lean: "lean <stamp>"

inline bool lean_read(const std::string& path, const char* stamp16) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    char line[40]{};
    const size_t n = fread(line, 1, sizeof line - 1, f);
    fclose(f);
    line[n] = 0;
    return n >= 21 && !memcmp(line, "lean ", 5) && !memcmp(line + 5, stamp16, 16);
}
inline bool lean_write(const std::string& path, const char* stamp16) {
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    const bool ok = fprintf(f, "lean %.16s\n", stamp16) > 0;
    return fclose(f) == 0 && ok;
}

/// What a start does: fresh (no file read for these shaders), whether the rule says lean now, and the record of the file
/// read. Lean for the session: a fresh file the rule makes lean, or a file read whose record says lean (and the switch on)
inline bool lean_now(int mode, bool fresh, bool chose, bool recorded) {
    if (mode <= 0) return false;
    return fresh ? chose : recorded;
}

}   // namespace pcache_libs
