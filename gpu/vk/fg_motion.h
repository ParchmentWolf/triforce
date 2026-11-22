// (Triforce, 11-22, the owner's DLSS frame generation flicker, again) Whose motion vectors frame generation is given.
//
// Since FG-4 (vk_fsr3_inputs.cpp chain_motion), while NVIDIA DLSS or AMD FSR 4 upscales, frame generation's motion is the
// upscaler chain's: the camera's from the depth, with every draw of the scene that stored its positions drawn again over
// it (vk_temporal.cpp capture_motion). With NVIDIA DLSS frame generation that showed as the owner's flicker of 11-20 again
// (the whole picture while the camera moved), on a build with the clip-space fix of that day (dlss_math.h
// depth_clip_projection) in it. The owner's runs of 11-22 (DLSS at 50%, 2x frame generation, HDR, before the bloom):
//  - RX_VK_FG_OWN_MOTION=0, the camera's motion alone: no flicker;
//  - the chain's motion with the upscaler audit's commits all set back (RX_VK_CAPTURE_TABLES=0, RX_VK_REDRAW_STATE=0,
//    RX_VK_DLSS_FEATURE_MAX=1): the flicker, so it is not theirs;
//  - RX_VK_DLSS_PROBE=1 in that run: the redraw's motion of the scene's largest draw within 0.03 px of the camera's.
// What in the chain's motion Streamline takes for a flicker is not known: its made frames are not in any log or shot. DLSS
// frame generation finds what moves by itself with its own optical flow, and FSR's inputs give it the depth and the
// camera, so it is given the camera's motion alone: what the first run showed. AMD's frame generation and FSR 3.1's
// interpolation keep the chain's, as since FG-4 (no flicker of theirs is reported).
//
// RX_VK_DLSSG_OWN_MOTION=1: DLSS frame generation is given the chain's motion again, as before. RX_VK_FG_OWN_MOTION=0 still
// gives every generator the camera's alone.
//
// No Vulkan: tests/test_fg_motion.py compiles this.
#pragma once
#include <cstdlib>

namespace fg_motion {

/// A switch read as the renderer reads its others: set and not 0 (value null when unset)
inline bool set_on(const char* value) { return value && *value && std::atoi(value) != 0; }
/// RX_VK_FG_OWN_MOTION=0 (value null when unset): the camera's motion alone, for every generator
inline bool camera_alone(const char* value) { return value && *value && std::atoi(value) == 0; }

/// Whether frame generation is given the upscaler chain's motion this frame. dlssg: NVIDIA DLSS frame generation runs in
/// this session (vk_dlssg.h active). fg_own: RX_VK_FG_OWN_MOTION; dlssg_own: RX_VK_DLSSG_OWN_MOTION (null when unset)
inline bool chain(bool dlssg, const char* fg_own, const char* dlssg_own) {
    if (camera_alone(fg_own)) return false;
    return !dlssg || set_on(dlssg_own);
}

}   // namespace fg_motion
