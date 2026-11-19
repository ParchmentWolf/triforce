// The game's files the overlays read (the radial menus' names, item_names.cpp), from the player's romfs folder
// (MkwVkHost romfs_dir), in memory only: a file whole, a .zs one unpacked (with the game's dictionary where its frame names
// one), a BNTX archive's texture as RGBA8 (vk_game_tex.h), and the first file of a folder whose name starts so.
#pragma once

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <string>
#include <vector>

#include "vk_game_font.h"
#include "vk_game_tex.h"
#include "vk_internal.h"

namespace game_assets {

inline const mkwvk::game_font::Reader *reader() {
    static mkwvk::game_font::Reader r;
    static std::once_flag once;
    std::call_once(once, [] {
        const char *dir = mkwvk::host && mkwvk::host->romfs_dir ? mkwvk::host->romfs_dir() : nullptr;
        if (!dir || !r.open(dir)) mkwvk::logf("game files: could not be opened (%s)", dir ? dir : "no romfs folder");
        if (r.romfs.empty() && dir) r.romfs = std::string(dir) + "/";
    });
    return &r;
}

}   // namespace game_assets

// a file of the romfs (path from its folder), malloc'd, a .zs file unpacked; NULL when it is not there or does not unpack
inline uint8_t *game_asset_load(const char *rel, size_t *n) {
    const mkwvk::game_font::Reader *r = game_assets::reader();
    std::vector<unsigned char> raw, out;
    if (r->romfs.empty() || !mkwvk::game_font::read_file(r->romfs + rel, raw)) return nullptr;
    const size_t len = strlen(rel);
    if (len > 3 && !strcmp(rel + len - 3, ".zs")) {
        const bool dict = raw.size() >= 4 && ZSTD_getDictID_fromFrame(raw.data(), raw.size()) != 0;
        if (!mkwvk::game_font::unzstd(raw, dict ? r->dict : nullptr, out)) return nullptr;
    } else {
        out.swap(raw);
    }
    uint8_t *b = (uint8_t *)malloc(out.size() ? out.size() : 1);
    if (!b) return nullptr;
    memcpy(b, out.data(), out.size());
    if (n) *n = out.size();
    return b;
}

// texture name of a BNTX archive as RGBA8 (a BC4 mask: white, the mask in alpha); 1 with a malloc'd *rgba
inline int game_asset_texture(const uint8_t *bntx, size_t n, const char *name, uint8_t **rgba, uint32_t *w, uint32_t *h) {
    mkwvk::game_tex::Bntx archive;
    if (!archive.parse(std::vector<unsigned char>(bntx, bntx + n))) return 0;
    const mkwvk::game_tex::Bntx::Entry *e = archive.find(name);
    mkwvk::game_tex::Image im;
    if (!e || !archive.decode(*e, im)) return 0;
    *rgba = (uint8_t *)malloc(im.rgba.size());
    if (!*rgba) return 0;
    memcpy(*rgba, im.rgba.data(), im.rgba.size());
    *w = im.w, *h = im.h;
    return 1;
}

// the first file in folder (from the romfs) whose name starts with prefix and has part in it, as a path from the romfs
inline std::string game_asset_find(const char *folder, const char *prefix, const char *part) {
    const mkwvk::game_font::Reader *r = game_assets::reader();
    std::error_code ec;
    for (const auto &e : std::filesystem::directory_iterator(r->romfs + folder, ec)) {
        const std::string name = e.path().filename().string();
        if (!name.compare(0, strlen(prefix), prefix) && name.find(part) != std::string::npos) return std::string(folder) + "/" + name;
    }
    return {};
}
