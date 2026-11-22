// (Triforce, 11-22, the performance audit's OS-05, after Source A's) The textures give commit back near Windows' commit limit,
// and the page files' room to grow counts as commit still to come.
//
// Windows charges every block of a discrete card's memory to the process's commit, as it does the game's own memory. Where the
// system's commit runs out (RAM and the page files full) an allocation is refused, and the game ends unless the refusal passes
// (OS-04's wait, HOS_COMMIT_WAIT_MS, helps only if commit comes back). Source A takes the shortfall under a reserve of free
// commit (2,560 MB) off the texture budget on any card, so that eviction and compaction give blocks back. Its first rule fired
// while a page file Windows manages could still grow (292,526 textures retired in 90 minutes, black textures); the fix counts
// each page file's room to grow, capped by its drive's free space, as commit still free.
//
// The rules here, apart from Windows so that tests/test_commit_room.py can run them:
// - reserve_of: RX_VK_TEX_COMMIT_RESERVE_MB, the reserve. Off (0) unless set: the entry's 2560 is not measured on this tree
// - growth_on: RX_VK_TEX_COMMIT_GROWTH, whether the growth is counted: 0 never, another number always, unset where a reserve is
// - low_line, read_growth: the growth is read only while less is free than the higher of the reserve and the line of
//   tex_pressure::commit_low (whose fall-back to the fixed size then gets the growth too: vk_texture.cpp commit_now)
// - cap: the textures at most what they hold less the shortfall under the reserve, never under 1 GB (Source A has no floor,
//   and its false cut went to 0)
// - growth: the page files' room to grow, from the records of NtQuerySystemInformation's class 0x90 (undocumented: each
//   record is checked against the buffer, and one that is not inside it ends the walk), a drive's page files capped together
//   by its free space. vk_texture.cpp page_file_growth asks Windows, at most once a second, and answers 0 on any failure.
// Written from the audit's description: Source A's file is not on this PC.
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace commit_room {

inline constexpr uint64_t kFloor = 1ull << 30;   // (the textures are never capped under 1 GB)
inline constexpr int64_t kMostMb = 65536;        // (the reserve at most)

/// RX_VK_TEX_COMMIT_RESERVE_MB in bytes: 0 (unset, empty, no number, 0 or less): no cut, as before; at most kMostMb MB
inline uint64_t reserve_of(const char* env) {
    if (!env || !*env) return 0;
    const long long mb = std::atoll(env);
    return mb <= 0 ? 0 : (uint64_t)std::min<long long>(mb, kMostMb) << 20;
}

/// RX_VK_TEX_COMMIT_GROWTH: unset or empty, counted where a reserve is set; 0 (or no number), never; another number, always
inline bool growth_on(const char* env, uint64_t reserve) {
    if (!env || !*env) return reserve != 0;
    return std::atoi(env) != 0;
}

/// tex_pressure::commit_low's line in bytes: want_mb MB; -1 (less than 0) the larger of 4 GB and a tenth of the limit; 0, or a
/// limit not known (0), none
inline uint64_t low_line(uint64_t limit, int64_t want_mb) {
    if (!limit || !want_mb) return 0;
    return want_mb > 0 ? (uint64_t)want_mb << 20 : std::max<uint64_t>(4096ull << 20, limit / 10);
}

/// Whether the page files' growth is read at this look: counted (on), and less free (avail) than the higher of the reserve and
/// commit_low's line (low)
inline bool read_growth(bool on, uint64_t avail, uint64_t reserve, uint64_t low) { return on && avail < std::max(reserve, low); }

/// The textures' cap: what they hold (total) less the shortfall of what is free (avail, the growth in it) under the reserve,
/// never under kFloor. UINT64_MAX (no cap) with no reserve, or with the reserve free
inline uint64_t cap(uint64_t total, uint64_t avail, uint64_t reserve) {
    if (!reserve || avail >= reserve) return UINT64_MAX;
    const uint64_t shortfall = reserve - avail;
    return std::max(kFloor, total > shortfall ? total - shortfall : 0);
}

/// NtQuerySystemInformation's class for the page files' records (SystemPageFileInformationEx)
inline constexpr unsigned kPageFileClass = 0x90;

/// One record of that class as 64-bit Windows lays it out; sizes in pages
struct PageFileRecord {
    uint32_t next;                   // (bytes from this record to the next; 0: the last)
    uint32_t total_pages;            // (its size now)
    uint32_t in_use_pages, peak_pages;
    uint16_t name_bytes, name_room;  // (the name: UTF-16, such as \??\C:\pagefile.sys, in the same buffer)
    const uint16_t* name;
    uint32_t min_pages, max_pages;   // (the size it may grow to)
};
static_assert(sizeof(void*) != 8 || sizeof(PageFileRecord) == 40, "the record as 64-bit Windows lays it out");

/// The drive letter of a page file's name ('C' for \??\C:\pagefile.sys), 0 where it has none
inline char drive_of(const uint16_t* name, size_t chars) {
    for (size_t i = 0; i + 1 < chars; i++) {
        const uint16_t c = name[i];
        if (name[i + 1] == ':' && ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'))) return (char)(c >= 'a' ? c - 32 : c);
    }
    return 0;
}

/// The page files' room to grow in bytes, from the records in buf[0, len): a record's (max - size) pages of `page` bytes, the
/// records of one drive summed and capped by that drive's free space (free_of('C'), bytes). A record that is not wholly inside
/// the buffer, whose name is not, or whose next one would overlap it, ends the walk: what came before it counts
template <class FreeOf>
inline uint64_t growth(const uint8_t* buf, size_t len, uint64_t page, FreeOf free_of) {
    uint64_t by_drive[26] = {};
    const uintptr_t base = (uintptr_t)buf;
    for (size_t at = 0; len >= sizeof(PageFileRecord) && at <= len - sizeof(PageFileRecord);) {
        PageFileRecord r;
        std::memcpy(&r, buf + at, sizeof r);
        char drive = 0;
        if (r.name_bytes) {
            const uintptr_t n = (uintptr_t)r.name;
            if (n < base || n - base > len || r.name_bytes > len - (n - base)) break;
            uint16_t chars[64] = {};
            const size_t count = std::min<size_t>(r.name_bytes / 2, 64);
            std::memcpy(chars, buf + (n - base), count * 2);
            drive = drive_of(chars, count);
        }
        if (drive && r.max_pages > r.total_pages) by_drive[drive - 'A'] += (uint64_t)(r.max_pages - r.total_pages) * page;
        if (!r.next) break;
        if (r.next < sizeof r || r.next > len - at) break;
        at += r.next;
    }
    uint64_t sum = 0;
    for (int d = 0; d < 26; d++)
        if (by_drive[d]) sum += std::min<uint64_t>(by_drive[d], free_of((char)('A' + d)));
    return sum;
}

} // namespace commit_room
