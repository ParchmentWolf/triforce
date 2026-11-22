// (Triforce) Whether the renderer holds an AMD GPU at amdgpu's stable power state while the game runs, and which one (Linux:
// vk_gpu_clock.cpp; RX_VK_GPU_CLOCK). Plain code with no system calls: tests/test_gpu_clock.py runs it on made-up devices.
//
// The Steam Deck's automatic GPU clock drops while the frame waits on the CPU or a readback (200 MHz for 27% of a Kokiri run), so
// the GPU work after the wait runs slow. amdgpu lets any process that opens the GPU's render node ask for a stable power state
// through a context of its own (DRM_IOCTL_AMDGPU_CTX, AMDGPU_CTX_OP_SET_STABLE_PSTATE, Linux 5.18): no root and no sysfs write.
// The kernel gives the level back when that context goes, at the process's end too, a crash or kill -9 included. Measured on a
// Deck OLED (SteamOS 3.9.5, plugged in): Kokiri handheld 11.1 -> 16.2 fps, 1% low 6.8 -> 12.1, GPU time 58 -> 32 ms at the same
// 15 W; Hyrule Field +19% for 4 W more. It costs battery where the APU was under its power cap.
//
// - Unset: the peak state, on the Deck's APU only (its Vulkan name, or SteamDeck=1 from Steam on an integrated AMD GPU), and
//   only while the level is amdgpu's own (power_dpm_force_performance_level "auto"): a level the player set is left alone.
// - RX_VK_GPU_CLOCK=0: nothing opened. =peak (or 1), =standard: that state on any AMD GPU, whatever the level.
#pragma once

#include <cstdint>
#include <cstring>

namespace mkwvk::gpu_clock {

enum Want { kNone, kPeak, kStandard };

// (uapi/drm/amdgpu_drm.h, written out: no libdrm and no kernel headers needed to build)
constexpr uint32_t kCtxOpAlloc = 1, kCtxOpSetStablePstate = 6;
constexpr uint32_t kPstateStandard = 1, kPstatePeak = 4;
constexpr uint32_t kCtxArgBytes = 16;   // (union drm_amdgpu_ctx)
/// DRM_IOCTL_AMDGPU_CTX: DRM_IOWR(DRM_COMMAND_BASE + DRM_AMDGPU_CTX, union drm_amdgpu_ctx) = _IOWR('d', 0x40 + 0x02, 16 bytes)
constexpr unsigned long kCtxIoctl = (3ul << 30) | ((unsigned long)kCtxArgBytes << 16) | ((unsigned long)'d' << 8) | 0x42ul;

/// The Deck's APU: "AMD Custom GPU 0405" (LCD) or "0932" (OLED) in its Vulkan name; or SteamDeck=1 (Steam sets it there) on an
/// integrated GPU
inline bool deck_apu(const char* device_name, bool integrated, const char* steam_deck_env) {
    if (device_name && (std::strstr(device_name, "Custom GPU 0405") || std::strstr(device_name, "Custom GPU 0932"))) return true;
    return integrated && steam_deck_env && !std::strcmp(steam_deck_env, "1");
}

struct Choice {
    Want want;
    const char* why;
};

/// switch_value: RX_VK_GPU_CLOCK (nullptr unset); level: power_dpm_force_performance_level's text, first word (nullptr: unread)
inline Choice choose(const char* switch_value, uint32_t vendor_id, bool integrated, const char* device_name,
                     const char* steam_deck_env, const char* level) {
    if (vendor_id != 0x1002) return {kNone, "not an AMD GPU"};
    if (switch_value && *switch_value) {
        if (!std::strcmp(switch_value, "0")) return {kNone, "RX_VK_GPU_CLOCK=0"};
        if (!std::strcmp(switch_value, "peak") || !std::strcmp(switch_value, "1")) return {kPeak, "RX_VK_GPU_CLOCK=peak"};
        if (!std::strcmp(switch_value, "standard")) return {kStandard, "RX_VK_GPU_CLOCK=standard"};
    }
    if (!deck_apu(device_name, integrated, steam_deck_env)) return {kNone, "not a Steam Deck (RX_VK_GPU_CLOCK=peak: any AMD GPU)"};
    if (!level) return {kNone, "the GPU's performance level could not be read"};
    if (std::strcmp(level, "auto")) return {kNone, "the GPU's performance level is set by hand"};
    return {kPeak, "the Steam Deck's GPU, its level amdgpu's own"};
}

}   // namespace mkwvk::gpu_clock
