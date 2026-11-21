/* (Triforce) A sound of one of the game's sound banks (Sound/Resource/<bank>.bars.zs: zstd, then BARS), for the sounds the
   game keeps whole in a bank and not as a stream file of its own (the pause menu's SE_Sys_PlusMenu_ItemInvalid00).
   BARS: "BARS", its size, the byte order mark, the version, the count, then the entries' CRC32s of their names (sorted),
   then each entry's two offsets: its AMTA and its BWAV. An entry's BWAV is kept whole when its sample count is its
   prefetch's (the bytes up to the next entry's BWAV, or the bank's end) */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "../third_party/zstd/lib/zstd.h"

uint8_t *hos_fs_rom_file(const char *rel, uint64_t most, uint64_t *size);   /* nn_fs.c */
uint32_t sz_crc32(uint32_t crc, const void *data, size_t n);                 /* save_zip.c */

static uint32_t rd32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }

/* rel: "<bank file>#<entry>"; a malloc'd BWAV and its size, NULL when the bank or the entry is missing */
uint8_t *hos_rom_bank_sound(const char *rel, uint64_t most, uint64_t *size) {
    const char *hash = strchr(rel, '#');
    if (!hash || hash == rel || !hash[1]) return NULL;
    char bank[256];
    const size_t n = (size_t)(hash - rel);
    if (n >= sizeof bank) return NULL;
    memcpy(bank, rel, n), bank[n] = 0;
    uint64_t zsize = 0;
    uint8_t *z = hos_fs_rom_file(bank, 64ull << 20, &zsize);
    if (!z) return NULL;
    const unsigned long long full = ZSTD_getFrameContentSize(z, (size_t)zsize);
    uint8_t *b = full && full <= (64ull << 20) ? (uint8_t *)malloc((size_t)full) : NULL;
    const size_t got = b ? ZSTD_decompress(b, (size_t)full, z, (size_t)zsize) : 0;
    free(z);
    if (!b || ZSTD_isError(got) || got < 0x10 || memcmp(b, "BARS", 4)) return free(b), NULL;
    const uint32_t count = rd32(b + 12), crc = sz_crc32(0, hash + 1, strlen(hash + 1));
    uint8_t *out = NULL;
    if (count && 0x10 + (uint64_t)count * 12 <= got)
        for (uint32_t i = 0; i < count && !out; i++) {
            if (rd32(b + 0x10 + 4 * i) != crc) continue;
            const uint32_t at = rd32(b + 0x10 + 4 * count + 8 * i + 4);
            uint64_t end = got;
            for (uint32_t k = 0; k < count; k++) {
                const uint32_t other = rd32(b + 0x10 + 4 * count + 8 * k + 4);
                if (other > at && other < end) end = other;
            }
            if (at + 0x10 + 0x4c > end || memcmp(b + at, "BWAV", 4) || end - at > most) break;
            /* (whole: the sample count of its first channel, +8, is its prefetch's, +12) */
            if (rd32(b + at + 0x10 + 8) != rd32(b + at + 0x10 + 12)) break;
            if ((out = (uint8_t *)malloc((size_t)(end - at)))) memcpy(out, b + at, (size_t)(end - at)), *size = end - at;
        }
    free(b);
    return out;
}
