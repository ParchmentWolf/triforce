// (Triforce VR) romfs/Mals/<language>.Product.110.sarc.zs: a SARC of MSBT files (LBL1 labels, TXT2 UTF-8 texts)
#pragma once

#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace mkwvk::msbt {

inline uint16_t u16(const unsigned char* p) { return (uint16_t)(p[0] | p[1] << 8); }
inline uint32_t u32(const unsigned char* p) { return (uint32_t)(p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24); }

/// The file `name` of a SARC: its bytes' start and size; false when the archive has no such file
inline bool sarc_member(const std::vector<unsigned char>& b, const char* name, size_t* at, size_t* size) {
    if (b.size() < 0x20 || memcmp(b.data(), "SARC", 4)) return false;
    const size_t hl = u16(&b[4]), data = u32(&b[12]);
    if (hl + 12 > b.size()) return false;
    const size_t n = u16(&b[hl + 6]), names = hl + 12 + 16 * n + 8;
    const size_t len = strlen(name);
    for (size_t i = 0; i < n; i++) {
        const size_t e = hl + 12 + 16 * i + 4;
        if (e + 12 > b.size()) return false;
        const uint32_t attr = u32(&b[e]), start = u32(&b[e + 4]), end = u32(&b[e + 8]);
        const size_t o = names + (size_t)(attr & 0xFFFFFF) * 4;
        if (o + len + 1 > b.size() || memcmp(&b[o], name, len + 1)) continue;
        if (start > end || data + end > b.size()) return false;
        *at = data + start, *size = end - start;
        return true;
    }
    return false;
}

/// A text without its tags (0x0E u16 group, u16 type, u16 size, then that many bytes; 0x0F u16 group, u16 type) and its end
inline std::string plain(const unsigned char* p, size_t n) {
    std::string out;
    for (size_t i = 0; i < n && p[i];) {
        if (p[i] == 0x0E && i + 7 <= n) {
            i += 7 + u16(p + i + 5);
        } else if (p[i] == 0x0F && i + 5 <= n) {
            i += 5;
        } else {
            out += (char)p[i++];
        }
    }
    return out;
}

/// An MSBT's texts by label (UTF-8 files only); empty when it is not one
inline std::map<std::string, std::string> texts(const unsigned char* m, size_t n) {
    std::map<std::string, std::string> out;
    if (n < 0x20 || memcmp(m, "MsgStdBn", 8) || m[8] != 0xFF || m[9] != 0xFE || m[0xC] != 0) return out;
    const unsigned char *lbl = nullptr, *txt = nullptr;
    size_t lbl_n = 0, txt_n = 0;
    const unsigned sections = u16(m + 0xE);
    size_t at = 0x20;
    for (unsigned s = 0; s < sections && at + 16 <= n; s++) {
        const size_t size = u32(m + at + 4);
        if (at + 16 + size > n) return out;
        if (!memcmp(m + at, "LBL1", 4)) lbl = m + at + 16, lbl_n = size;
        if (!memcmp(m + at, "TXT2", 4)) txt = m + at + 16, txt_n = size;
        at += 16 + size;
        at += (16 - at % 16) % 16;
    }
    if (!lbl || !txt || lbl_n < 4 || txt_n < 4) return out;
    const uint32_t count = u32(txt);
    if ((size_t)count * 4 + 4 > txt_n) return out;
    const uint32_t slots = u32(lbl);
    for (uint32_t i = 0; i < slots && 4 + 8 * (size_t)i + 8 <= lbl_n; i++) {
        uint32_t labels = u32(lbl + 4 + 8 * i), o = u32(lbl + 8 + 8 * i);
        for (; labels; labels--) {
            if (o >= lbl_n) return out;
            const size_t len = lbl[o];
            if (o + 1 + len + 4 > lbl_n) return out;
            const std::string label((const char*)lbl + o + 1, len);
            const uint32_t k = u32(lbl + o + 1 + len);
            o += (uint32_t)(5 + len);
            if (k >= count) continue;
            const uint32_t a = u32(txt + 4 + 4 * k), z = k + 1 < count ? u32(txt + 8 + 4 * k) : (uint32_t)txt_n;
            if (a <= z && z <= txt_n) out[label] = plain(txt + a, z - a);
        }
    }
    return out;
}

}  // namespace mkwvk::msbt
