// (Triforce) The recorder thread's default (vk_recorder.h g_auto_thread, RX_VK_RECORDER unset), chosen once the device is known
// (vk_main.cpp pick_device). Plain code with no Vulkan or system calls: tests/test_recorder_auto.py runs it on made-up PCs.
//
// - NVIDIA: on with 12 logical processors or more, as since 11-16 (lab, RTX 4070 SUPER + i7-13700K: Market +11%; held to 8
//   logical processors -10%: the recorder needs a core of its own).
// - AMD: on with 6 physical cores or more in the process's affinity. AMD's driver spends about twice NVIDIA's CPU time on a call,
//   so the replay thread's vkCmd* calls cost it more; taken out of a renderer of the same per-call design, the densest Market view
//   (~2,500 draws) fell 16-25% behind on RX 7900 XTX, 9070 XT and 9060 XT cards. Physical cores, not logical processors: the
//   recorder spins on a core while the replay records, and an SMT sibling of a busy core is not one (a 4-core Steam Deck: off).
//   Not on AMD's older Windows driver (vk_vendor.h amd_older_compiler, RX 5000 and RX 6000): it lost the device with commands
//   recorded beside the replay thread (replay_threads.h), so it waits for a lab of its own.
// - Anything else (Intel, a GPU not named): off, nothing measured.
// RX_VK_RECORDER=thread or =off goes over this either way.
#pragma once

#include <cstdint>

namespace mkwvk::recorder_default {

enum Why : int { kNvidia, kNvidiaFew, kAmd, kAmdFew, kAmdUnknown, kAmdOlder, kOther };

/// Why the recorder is on or off by default. logical: cpu_count() (cpu_count.h: hardware_concurrency, or the lab's HOS_SIM_CPU); physical: physical_cores (0: unknown)
constexpr Why why(uint32_t vendor_id, unsigned logical, unsigned physical, bool amd_older) {
    if (vendor_id == 0x10DE) return logical >= 12 ? kNvidia : kNvidiaFew;
    if (vendor_id == 0x1002) {
        if (amd_older) return kAmdOlder;
        if (!physical) return kAmdUnknown;
        return physical >= 6 ? kAmd : kAmdFew;
    }
    return kOther;
}
constexpr bool on(Why w) { return w == kNvidia || w == kAmd; }
constexpr bool rule(uint32_t vendor_id, unsigned logical, unsigned physical, bool amd_older) {
    return on(why(vendor_id, logical, physical, amd_older));
}
constexpr const char* text(Why w) {
    switch (w) {
    case kNvidia: return "NVIDIA, 12 logical processors or more";
    case kNvidiaFew: return "NVIDIA, under 12 logical processors";
    case kAmd: return "AMD, 6 physical cores or more";
    case kAmdFew: return "AMD, under 6 physical cores";
    case kAmdUnknown: return "AMD, the physical cores not known";
    case kAmdOlder: return "AMD's driver for RX 5000 and RX 6000 (not tried there)";
    default: return "not an NVIDIA or AMD GPU (not measured)";
    }
}

/// The physical cores with at least one logical processor in affinity: masks[i] is core i's logical processors (one
/// RelationProcessorCore entry each: GetLogicalProcessorInformation, which on Linux reads sysfs's package and core ids)
inline unsigned physical_cores(const uint64_t* masks, int n, uint64_t affinity) {
    unsigned cores = 0;
    for (int i = 0; i < n; i++) cores += (masks[i] & affinity) != 0;
    return cores;
}

}   // namespace mkwvk::recorder_default
