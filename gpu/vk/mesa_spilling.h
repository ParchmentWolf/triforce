// Mesa's Intel shader compiler told to spill registers at rate 2, before the driver is loaded (no game, no GPU: a rule).
//
// (Triforce, 11-22, the performance audit's PIPE-55, after Source A's.) Mesa's drivers read their options (driconf) from
// the environment by name. shader_spilling_rate is read by the Intel compiler alone: after a register allocation that
// failed, it spills that many times more registers at once, so a program that does not fit is built in fewer, larger
// steps. A program that does not spill builds the same. Source A's numbers on an Iris Xe (i9-13900H, 32 GB, Mesa 26.2.4):
// one compute program not built after 20 minutes and 13 GB at the driver's own rate, 32 s and 1.7 GB at rate 2; another
// 531 s and 7.6 GB against 87 s and 4 GB; rate 3 took 165 s there and rate 4 did not finish in 8 minutes. The driver's
// own estimate for a spilling program's speed at rate 2 is from 12% better to 53% worse.
//
// The Linux build sets it in create_instance (vk_main.cpp) without overwriting, so a value the player set wins.
// RX_VK_NO_SPILLING_RATE=1 leaves the driver as it is. The Windows build sets nothing: under Proton the driver reads the
// Linux environment, which the Windows build cannot write, and those players put shader_spilling_rate=2 in the launch
// options.
// Nothing here is read by NVIDIA's or AMD's drivers, RADV included.
#pragma once
#include <cstdlib>

namespace mesa_spilling {
constexpr const char* kName = "shader_spilling_rate";
constexpr const char* kRate = "2";

/// The build sets the rate: off Windows, unless RX_VK_NO_SPILLING_RATE is set to something other than 0. off: its value
inline bool wanted(bool windows_build, const char* off) {
    return !windows_build && !(off && std::atoi(off) != 0);
}

/// What the driver will read once the build has done its part: the player's own value where there is one (set without
/// overwriting), else the rate where it is wanted, else nullptr (the driver's own rate)
inline const char* effective(const char* players, bool is_wanted) {
    return players ? players : is_wanted ? kRate : nullptr;
}

/// The log names the rate on Mesa's Intel driver alone
constexpr bool told(bool mesa_intel) {
    return mesa_intel;
}
} // namespace mesa_spilling
