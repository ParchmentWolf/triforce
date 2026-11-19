/* Ocarina of Time 1.1.1's game data and Link's actor read straight from
   guest memory, for VR's side in the game (host/vr_game.c). A read
   of a guest page that is not committed answers 0 instead of faulting (Windows reserves the window PAGE_NOACCESS; on Linux
   every page reads). C and C++, header-only: each side passes the guest window's base.

   The game data's manager is **[main+0x4c7e180] (OOT_GAMEDATA_SLOT in host/hos_main.c): a section of 0x60 bytes for each
   kind (the kind's number times 0x60: +0x10 the entries' count, +0x18 the entries, +0x20 the {hash, index} table probed
   from hash % size, +0x2c its size). Kinds: 0 bool (0x18 bytes, its bit at +0x16), 2 int (0x28, at +0x1c), 6 enum (0x38,
   the value's name's hash at +0x1c), 16 a 64-character text (0x108, its pointer at +0x68). A name is known to the game by
   its MurmurHash3 alone (oot_name_hash). Link's actor: [[main+0x4e371d0]+0x480], named "Player". */
#ifndef OOT_GAME_DATA_H
#define OOT_GAME_DATA_H
#include <stdint.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include "oot_debug_link.h"   /* (oot_name_hash) */

#ifdef __cplusplus
extern "C" {
#endif

#define OOT_DATA_MAIN 0x80020000ULL   /* main's place in the image (Eden's layout): main+X is OOT_DATA_MAIN + X */
#define OOT_DATA_SPACE (1ULL << 39)

/* the committed region a read last fell in, a thread's own: most reads land in one again */
static inline int oot_data_rd(const uint8_t *base, uint64_t a, void *out, size_t n) {
#if defined(_MSC_VER)
    static __declspec(thread) uint64_t lo, hi;
#else
    static __thread uint64_t lo, hi;
#endif
    if (!base || !a || a >= OOT_DATA_SPACE || n > OOT_DATA_SPACE - a) return 0;
    if (!(a >= lo && a + n <= hi)) {
        MEMORY_BASIC_INFORMATION mi;
        for (uint64_t at = a; at < a + n;) {
            if (!VirtualQuery(base + at, &mi, sizeof mi) || mi.State != MEM_COMMIT ||
                (mi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) || !mi.Protect)
                return 0;
            const uint64_t r0 = (uint64_t)((const uint8_t *)mi.BaseAddress - base), r1 = r0 + mi.RegionSize;
            if (at == a) lo = r0, hi = r1;
            at = r1;
        }
        if (!(a >= lo && a + n <= hi)) lo = hi = 0;
    }
    memcpy(out, base + a, n);
    return 1;
}
static inline uint64_t oot_data_ptr(const uint8_t *base, uint64_t a) {
    uint64_t p = 0;
    return oot_data_rd(base, a, &p, 8) ? p : 0;
}

static inline uint32_t oot_data_hash(const char *name) { return oot_name_hash(name, strlen(name)); }

static inline uint64_t oot_data_gdm(const uint8_t *base) {
    const uint64_t slot = oot_data_ptr(base, OOT_DATA_MAIN + 0x4c7e180);
    return slot ? oot_data_ptr(base, slot) : 0;
}

/* the entry of kind's name hash, 0 when the game has none */
static inline uint64_t oot_data_entry(const uint8_t *base, int kind, uint32_t stride, uint32_t hash) {
    const uint64_t m = oot_data_gdm(base), sec = m + (uint64_t)kind * 0x60;
    const uint64_t table = m ? oot_data_ptr(base, sec + 0x20) : 0, entries = m ? oot_data_ptr(base, sec + 0x18) : 0;
    uint32_t count = 0, size = 0;
    if (!table || !entries || !oot_data_rd(base, sec + 0x10, &count, 4) || !oot_data_rd(base, sec + 0x2c, &size, 4) || !size ||
        size > 100000)
        return 0;
    for (uint32_t i = hash % size, n = 0; n < size; i = i + 1 < size ? i + 1 : 0, n++) {
        uint32_t pr[2];
        if (!oot_data_rd(base, table + (uint64_t)i * 8, pr, 8) || !pr[0]) return 0;
        if (pr[0] == hash) return pr[1] < count ? entries + (uint64_t)pr[1] * stride : 0;
    }
    return 0;
}

static inline int oot_data_flag(const uint8_t *base, const char *name, int *on) {
    const uint64_t e = oot_data_entry(base, 0, 0x18, oot_data_hash(name));
    uint8_t b;
    if (!e || !oot_data_rd(base, e + 0x16, &b, 1)) return 0;
    *on = b & 1;
    return 1;
}
static inline int oot_data_int(const uint8_t *base, const char *name, int32_t *v) {
    const uint64_t e = oot_data_entry(base, 2, 0x28, oot_data_hash(name));
    return e && oot_data_rd(base, e + 0x1c, v, 4);
}
static inline int oot_data_enum(const uint8_t *base, const char *name, uint32_t *value_hash) {
    const uint64_t e = oot_data_entry(base, 6, 0x38, oot_data_hash(name));
    return e && oot_data_rd(base, e + 0x1c, value_hash, 4);
}
static inline int oot_data_text(const uint8_t *base, const char *name, char out[64]) {
    const uint64_t e = oot_data_entry(base, 16, 0x108, oot_data_hash(name)), text = e ? oot_data_ptr(base, e + 0x68) : 0;
    out[0] = 0;
    if (!text || !oot_data_rd(base, text, out, 63)) return 0;
    out[63] = 0;
    return 1;
}

/* Link's actor, 0 while there is none */
static inline uint64_t oot_data_player(const uint8_t *base) {
    const uint64_t manager = oot_data_ptr(base, OOT_DATA_MAIN + 0x4e371d0), actor = manager ? oot_data_ptr(base, manager + 0x480) : 0;
    const uint64_t np = actor ? oot_data_ptr(base, actor + 0x20) : 0;
    char name[7];
    return np && oot_data_rd(base, np, name, 7) && !memcmp(name, "Player", 7) ? actor : 0;
}

#ifdef __cplusplus
}
#endif
#endif
