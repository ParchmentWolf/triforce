#pragma once

#include "vk_internal.h"

#include <filesystem>

namespace mkwvk::reshade {

/// (Triforce) The game folder (vk_paths.h game_module_path's rule: above bin when the exe is in bin beside image.bin), as a
/// path from its UTF-8 name: the process's code page is UTF-8 (the exe's manifest)
std::filesystem::path game_dir();

class PipelineCache {
public:
    PipelineCache();
    ~PipelineCache();
    PipelineCache(const PipelineCache&) = delete;
    PipelineCache& operator=(const PipelineCache&) = delete;

    VkPipelineCache handle() const { return cache_; }
    void save() const;

private:
    std::filesystem::path path_;
    VkPipelineCache cache_{};
};

}  // namespace mkwvk::reshade
