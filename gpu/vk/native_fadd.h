/* (Triforce) Where the shaders' float adds to storage buffers are the GPU's own atomic (VK_EXT_shader_atomic_float's
   shaderBufferFloat32AtomicAdd, one OpAtomicFAddEXT) and not the translator's compare-exchange loop (vk_main.cpp
   create_device asks; eden spirv_emit_context.cpp DefineStorageBuffers emits).

   The loop gives up after CAS_LOOP_MAX_TRIES attempts, and an add that gives up is lost. Intel's Windows driver does worse
   with it in the sky's light sums (compute 499dbfd0721d2858): the device is lost at that dispatch on Arc B-series cards and
   Lunar Lake iGPUs, and on Panther Lake the exposure's adds are lost (a milky white haze). The GPU's own add has neither.

   listed(): the drivers and GPU families the native add was run on in the game, and no other: a driver that reports the
   feature but was never run with it keeps the loop until RX_VK_NATIVE_FADD=1 asks.
   - NVIDIA's driver, every GPU;
   - AMD's Windows driver on the Radeon 860M / 840M (PCI device 0x1114) from driver 0x8001a0 (Adrenalin 26.10.1);
   - Intel's Windows driver (driverVersion is 101 << 14 | build on every family) on
       Meteor Lake and Arrow Lake iGPUs (0x7Dxx) from 101.9175,
       Arc B-series, Battlemage (0xE2xx) from 101.9154,
       Panther Lake iGPUs (0xB0xx) from 101.9150,
       Lunar Lake iGPUs (0x64xx) from 101.8991.
   Intel's other GPUs on Windows (Iris Xe, UHD, Arc A-series), older drivers, AMD's other GPUs, RADV and Mesa's Intel driver
   (which numbers its versions otherwise) are never listed.
   RX_VK_NATIVE_FADD: 0, false, off, no or empty keeps the loop on every GPU (the extension is not even enabled); any other
   value asks for the native add wherever the GPU has it. Plain functions: tests/test_native_fadd_rule.py compiles them. */
#pragma once

#include <cstdint>

#include <vulkan/vulkan_core.h>

namespace mkwvk::native_fadd {

inline bool listed(VkDriverId driver, uint32_t device, uint32_t version, bool windows) {
    if (driver == VK_DRIVER_ID_NVIDIA_PROPRIETARY) return true;
    if (driver == VK_DRIVER_ID_AMD_PROPRIETARY) return windows && device == 0x1114u && version >= 0x8001a0u;
    if (driver != VK_DRIVER_ID_INTEL_PROPRIETARY_WINDOWS) return false;
    return ((device & 0xFF00u) == 0x7D00u && version >= (101u << 14 | 9175u)) ||
           ((device & 0xFF00u) == 0xE200u && version >= (101u << 14 | 9154u)) ||
           ((device & 0xFF00u) == 0xB000u && version >= (101u << 14 | 9150u)) ||
           ((device & 0xFF00u) == 0x6400u && version >= (101u << 14 | 8991u));
}

/// The switch's value as off: 0, false, off, no (any case, spaces around it left out) or empty
inline bool value_off(const char* v) {
    const auto blank = [](char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; };
    while (blank(*v)) v++;
    const char* end = v;
    for (const char* c = v; *c; c++)
        if (!blank(*c)) end = c + 1;
    const auto is = [&](const char* w) {
        const char* a = v;
        for (; a < end && *w; a++, w++)
            if ((*a | 0x20) != *w) return false;
        return a == end && !*w;
    };
    return v == end || is("0") || is("false") || is("off") || is("no");
}

/// Whether the native add is asked of the device: the switch when set, else the list
inline bool wanted(const char* env, VkDriverId driver, uint32_t device, uint32_t version, bool windows) {
    if (env) return !value_off(env);
    return listed(driver, device, version, windows);
}

} // namespace mkwvk::native_fadd
