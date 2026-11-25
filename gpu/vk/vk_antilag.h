// AMD Anti-Lag 2 through VK_AMD_anti_lag (vk_antilag.cpp): the driver delays the start of the game's next frame so that its
// input is sampled later and the frame waits less in the queue, for less delay from input to the screen.
#pragma once

#include <vector>

#include "vk_internal.h"

namespace mkwvk {

/// The extension it needs (VK_AMD_anti_lag), added to `want` when the device has it
void antilag_device_extensions(std::vector<const char*>& want, const std::vector<VkExtensionProperties>& all);
/// Its feature (antiLag) into the device's feature chain (*tail), before the features are queried
void antilag_device_features(void**& tail);
/// After the device is made: whether Anti-Lag 2 can run (the feature there), its function loaded
void antilag_device_created();
/// Anti-Lag 2 can run on this device: the Insert menu's row offers it only then
bool antilag_available();
/// Before the present: the frame's present stage
void antilag_present();
/// ((Triforce) 11-24) Frame generation: the game frame a set is made at (framegen_record; 0 none), and, on the display thread
/// before each present, the frame that present shows: its set's frame for the set's game frame, 0 for a made frame (no present
/// stage). kAntiLagThisFrame, the default on every other thread: the frame being made, as before
constexpr uint64_t kAntiLagThisFrame = ~0ull;
uint64_t antilag_frame();
extern thread_local uint64_t antilag_present_frame;
/// After the present: the next frame's input stage, where the driver waits until that frame should start
void antilag_input();
/// (Triforce) Its stages are given now (the row on and the device able): the present thread (vk_replay.cpp,
/// RX_VK_PRESENT_THREAD) is not used then, as its present stage would come after the next frame's input stage
bool antilag_running();

} // namespace mkwvk
