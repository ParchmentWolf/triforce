/* (hookshot) Two small checks of NVIDIA DLSS's (gpu/vk/vk_dlss.cpp), as plain functions: which scene sizes DLSS can take
   for an output, and a Linux path (UTF-8) for NGX's wide strings. No Vulkan, no NGX: tests/test_dlss_checks.cpp
   checks them. */
#pragma once

#include <cstdint>
#include <cstdlib>
#include <string>
#include <string_view>

namespace mkwvk::dlss_checks {

/// Whether a scene of w x h can be DLSS's input for an output of ow x oh: the output 1 to 3 times its size on each axis
/// (DLAA at 1, Ultra Performance at 3: 512x288 for 1536x864, 683x384 for 2048x1152). False while the output is not known
/// (0). The scene's camera and the actor motion take only these, and the upscale draws only these.
inline bool scene_size_fits(uint32_t w, uint32_t h, uint32_t ow, uint32_t oh) {
    return w && h && ow && oh && w <= ow && h <= oh && (uint64_t)w * 3 >= ow && (uint64_t)h * 3 >= oh;
}

/// ((Triforce, 11-22, the performance audit's PRESENT-38, after Source A's) One quality mode's range of render sizes for
/// an output, as NGX answers it (ok: it answered one).
struct ModeRange {
    uint32_t min_w = 0, min_h = 0, max_w = 0, max_h = 0;
    bool ok = false;
};
/// How far outside a range a render size may be and still be that mode's: a 64th of the range's largest size on that
/// axis, 2 pixels at least. The Render resolution row's shares are twelfths of the output rounded up, NGX's own sizes
/// are rounded down: 854x480 against NGX's 853x480 for Ultra Performance at 2560x1440.
constexpr uint32_t mode_slack(uint32_t largest) { return largest / 64 > 2 ? largest / 64 : 2; }
/// The mode (an index into ranges) that takes a render size of w x h for an output of ow x oh, or -1. The first range
/// that holds the size; else, with slack on, the first it is outside of by no more than mode_slack on each axis, and
/// only for a size DLSS scales at all (scene_size_fits: the output 1 to 3 times it). *widened: taken by the slack.
inline int mode_for(const ModeRange* ranges, size_t n, uint32_t w, uint32_t h, uint32_t ow, uint32_t oh, bool slack, bool* widened) {
    *widened = false;
    for (size_t i = 0; i < n; i++) {
        const ModeRange& r = ranges[i];
        if (r.ok && w >= r.min_w && h >= r.min_h && w <= r.max_w && h <= r.max_h) return (int)i;
    }
    if (!slack || !scene_size_fits(w, h, ow, oh)) return -1;
    for (size_t i = 0; i < n; i++) {
        const ModeRange& r = ranges[i];
        if (!r.ok) continue;
        const uint32_t sw = mode_slack(r.max_w), sh = mode_slack(r.max_h);
        if (w + sw >= r.min_w && h + sh >= r.min_h && w <= r.max_w + sw && h <= r.max_h + sh) return *widened = true, (int)i;
    }
    return -1;
}

/// ((Triforce, 11-22, the performance audit's PRESENT-32, after Source A's) Whether a feature is made in a one-size mode
/// (NGX's DLAA mode: vk_dlss.cpp prepare's `same` list): its render size is the output's. Before, whenever the two sizes
/// were equal. NVIDIA DLSS with the Render resolution row at Auto starts at the output's size, so it got a one-size
/// feature, and the game's dynamic resolution left that size some frames later: a second feature made in play (Source
/// A's save load-in: 119 ms, then 29.5 ms 17 frames on). With the rule (rule: RX_VK_DLSS_PREWARM=1), one-size only where
/// NVIDIA DLAA is the Upscaler's choice (dlaa); DLSS at the output's size takes the scaled mode whose range holds it
/// (mode_for: Quality's reaches the output's size), and Auto's smaller sizes then draw with that same feature. Off by
/// default: DLSS at full size then draws with the scaled mode's network, not DLAA's, a picture nobody has compared yet
inline bool dlaa_feature(bool rule, bool dlaa, uint32_t rw, uint32_t rh, uint32_t ow, uint32_t oh) {
    const bool full = rw == ow && rh == oh;
    return rule ? full && dlaa : full;
}
/// RX_VK_DLSS_PREWARM (value, null when unset): the rule above is on only when it is 1
inline bool prewarm_rule(const char* text) { return text && *text && std::atoi(text) == 1; }

/// Whether s is all ASCII: NGX's Linux library takes only such paths (vk_dlss.cpp wide())
inline bool ascii(std::string_view s) {
    for (const char c : s)
        if ((unsigned char)c >= 0x80) return false;
    return true;
}

/// UTF-8 bytes (a Linux path) as wide characters: UTF-32 where wchar_t has 32 bits (Linux), UTF-16 where it has 16. Decoded
/// here, not through the process's locale. Bytes that are not well-formed UTF-8 (a stray continuation byte, a cut sequence,
/// an overlong form, a surrogate, past U+10FFFF) become U+FFFD, one for each maximal ill-formed part (Unicode's practice);
/// *bad is set when that happened. U+FFFD rather than the raw byte as a character: the raw byte would name another, real
/// path (0xE9 alone would become "é", which NGX writes back as C3 A9), U+FFFD names none.
inline std::wstring utf8_to_wide(std::string_view s, bool* bad = nullptr) {
    std::wstring out;
    out.reserve(s.size());
    const auto put = [&](uint32_t cp) {
        if (sizeof(wchar_t) == 2 && cp > 0xFFFF) {
            cp -= 0x10000;
            out += (wchar_t)(0xD800 + (cp >> 10));
            out += (wchar_t)(0xDC00 + (cp & 0x3FF));
        } else {
            out += (wchar_t)cp;
        }
    };
    const auto replace = [&] {
        put(0xFFFD);
        if (bad) *bad = true;
    };
    size_t i = 0;
    while (i < s.size()) {
        const unsigned char b = (unsigned char)s[i];
        if (b < 0x80) {
            put(b), i++;
            continue;
        }
        // (the lead byte: how many continuation bytes follow, and the first one's range, Unicode's table 3-7)
        int need = 0;
        uint32_t cp = 0;
        unsigned char lo = 0x80, hi = 0xBF;
        if (b >= 0xC2 && b <= 0xDF) {
            need = 1, cp = b & 0x1F;
        } else if (b >= 0xE0 && b <= 0xEF) {
            need = 2, cp = b & 0x0F;
            if (b == 0xE0) lo = 0xA0;   // (no overlongs)
            if (b == 0xED) hi = 0x9F;   // (no surrogates)
        } else if (b >= 0xF0 && b <= 0xF4) {
            need = 3, cp = b & 0x07;
            if (b == 0xF0) lo = 0x90;   // (no overlongs)
            if (b == 0xF4) hi = 0x8F;   // (nothing past U+10FFFF)
        } else {   // (a continuation byte alone, C0, C1, F5 to FF)
            replace(), i++;
            continue;
        }
        size_t j = i + 1;
        int got = 0;
        for (; got < need && j < s.size(); got++, j++) {
            const unsigned char c = (unsigned char)s[j];
            if (c < lo || c > hi) break;
            cp = (cp << 6) | (c & 0x3F);
            lo = 0x80, hi = 0xBF;
        }
        if (got < need) replace();   // (the lead and the good bytes after it: one U+FFFD; the bad byte is read again)
        else put(cp);
        i = j;
    }
    return out;
}

/// ((Triforce, 11-21, the performance audit's PRESENT-37, after Source A's) The preset DLSS draws with while the DLSS model
/// row is stepped through (vk_dlss.cpp prepare). The row goes K, M, L, NVIDIA's default and applies live, so K to L passes
/// M: a feature was made for each preset passed, tens of ms of CPU each, and NGX keeps a released feature's video memory for
/// some seconds: Source A's 16 GB card at 3440x1440 held 1419 MB of DLSS's for K, M and L at once against 813 MB for L
/// alone, and where memory was short NGX refused the next feature. A new preset is taken once the row has held it for
/// `frames`; until then the feature already made draws on with its own. With no feature (the first, or one let go) the
/// row's preset is taken at once
struct PresetSettle {
    unsigned wanted = ~0u;   // (the row's preset, as last seen)
    uint64_t since = 0;      // (the frame it was first seen in)
    /// The preset for frame `now`: want, the row's; have, the feature's; has: there is a feature
    unsigned pick(unsigned want, unsigned have, bool has, uint64_t now, uint64_t frames) {
        if (want != wanted) wanted = want, since = now;
        if (!has || want == have) return want;
        return now - since >= frames ? want : have;
    }
};
/// RX_VK_DLSS_MODEL_SETTLE's frames: 30 when not set; 0 (and what is no number, or less): at once, as before
inline uint64_t settle_frames(const char* text) {
    if (!text || !*text) return 30;
    const long v = std::atol(text);
    return v > 0 ? (uint64_t)v : 0;
}

} // namespace mkwvk::dlss_checks
