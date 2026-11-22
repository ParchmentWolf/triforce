// (Triforce, 11-22, after Casual Gamer's #dev-fixes post) Two ways a start took its shaders for prepared when they were not, apart
// from Vulkan so that tests/test_prepare_again.py runs them (vk_draw.cpp prepare_run).
//
// The program cache made again for another GPU. triforce_prepared.bin says the shaders were translated for this stamp
// (program_cache_stamp: the translator and what of the GPU and its driver changes a translation). A start on another GPU or
// with other settings that did not prepare (or did not rewrite the record) makes triforce_programs.bin again for its own
// stamp: back here the record still matches, prepare_check says nothing to do, the program cache opens with none of these
// shaders (vk_shader.cpp disk_init throws the other stamp's away), and every program is translated in play. So when the
// record says nothing to do, the program cache's head (kDiskMagic, its stamp) and size are read: a cache of another stamp, or
// of its head alone, holds none of them, and the shaders are prepared again. A cache carried over an update keeps the stamp in
// its head (its second word, the build that wrote it, is another: program_carry.h) and passes.
//
// The mark of the driver's part without stage libraries, <prepared>.warming: "this step began and did not end", an empty file.
// A start that found it left the part out for good, on whatever GPU and driver came next. Now it holds what the part is made
// for (vk_draw.cpp libraries_stamp: the GPU, the driver, the programs), as the libraries' journal does (gpl_rules.h
// journal_left): a mark of another stamp is another driver's, and the part goes on. An empty one (an older build's) is this
// driver's, as before.
// RX_VK_PREPARE_RECHECK=0: neither, as before.
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <string>
#include <system_error>

namespace prepare_again {

inline constexpr uint32_t kProgramsMagic = 0x31505348;   // (vk_shader.cpp kDiskMagic: the program cache's head)
inline constexpr uint64_t kProgramsHead = 16;            // (the magic, the build that wrote it, the stamp)

/// RX_VK_PREPARE_RECHECK: on unless it is 0
inline bool on(const char* env) { return !(env && env[0] == '0' && !env[1]); }

/// Whether a program cache, by its first n bytes (head) and its size, holds none of the shaders of stamp: no program cache's
/// head, another stamp's, or its head alone
inline bool programs_none(const uint8_t* head, size_t n, uint64_t size, uint64_t stamp) {
    if (n < kProgramsHead || size <= kProgramsHead) return true;
    uint32_t magic;
    uint64_t was;
    std::memcpy(&magic, head, 4), std::memcpy(&was, head + 8, 8);
    return magic != kProgramsMagic || was != stamp;
}
/// The same for the file at path (none there: none of them). *size: its size, 0 when there is none
inline bool programs_none_at(const std::string& path, uint64_t stamp, uint64_t* size = nullptr) {
    std::error_code ec;
    const uint64_t n = std::filesystem::is_regular_file(path, ec) && !ec ? (uint64_t)std::filesystem::file_size(path, ec) : 0;
    const uint64_t whole = ec ? 0 : n;
    if (size) *size = whole;
    uint8_t head[kProgramsHead]{};
    size_t got = 0;
    if (FILE* f = std::fopen(path.c_str(), "rb")) {
        got = std::fread(head, 1, sizeof head, f);
        std::fclose(f);
    }
    return programs_none(head, got, whole, stamp);
}

/// What the last start left of the driver's part without stage libraries: no mark, a mark of this stamp (or an empty one, an
/// older build's; or any, with by_stamp false: RX_VK_PREPARE_RECHECK=0), or one of another stamp
enum class Mark { None, Ours, Other };
inline Mark mark_left(const std::string& path, uint64_t stamp, bool by_stamp) {
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) return Mark::None;
    uint64_t was = 0;
    const bool stamped = std::fread(&was, 8, 1, f) == 1;
    std::fclose(f);
    return !by_stamp || !stamped || was == stamp ? Mark::Ours : Mark::Other;
}
/// The mark written before the part: the stamp it is made for (empty with by_stamp false, as before). False: not written
inline bool mark_write(const std::string& path, uint64_t stamp, bool by_stamp) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    const bool ok = !by_stamp || std::fwrite(&stamp, 8, 1, f) == 1;
    return std::fclose(f) == 0 && ok;
}

}   // namespace prepare_again
