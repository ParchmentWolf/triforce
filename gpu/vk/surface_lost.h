// (Triforce, 11-22, the performance audit's PRESENT-45, after Source A's) Presentation made again after the window's
// surface is lost.
//
// An acquire, a present or a swapchain's creation can answer VK_ERROR_SURFACE_LOST_KHR: the surface itself is gone (a
// display driver reset, a monitor change, a remote session), and no swapchain can be made for it again. Nothing handled
// that result: every acquire after it failed without a word, so the picture stayed frozen while the game ran on, until a
// restart.
//
// Now the renderer lets go of what hangs on the surface, in the order Vulkan asks (vk_main.cpp invalidate_lost_surface:
// the device idle, the swapchain's views, its semaphores, the swapchain, then the surface), and the next swapchain's
// creation first makes a surface for the window again with the startup's own calls (open_window_surface): only while the
// window has a size (a minimized window waits), one try each kRetryMs at most, and with the presents' queue chosen again
// for the new surface.
//
// RX_VK_SURFACE_RECOVER=0: as before, the result is not handled. Nor is it while NVIDIA DLSS frame generation runs: the
// swapchain is Streamline's there, and that path has not been tried.
//
// No Vulkan: tests/test_present_surface_lost.py compiles this, and runs vk_main.cpp's and vk_replay.cpp's side against a
// model of a driver that loses its surface.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace surface_lost {

/// RX_VK_SURFACE_RECOVER (value, null when unset): on unless it is 0
inline bool on(const char* value) { return !(value && *value && std::atoi(value) == 0); }

/// A Vulkan result is a lost surface that is recovered from: lost (the result is VK_ERROR_SURFACE_LOST_KHR), the switch
/// on, and the swapchain the renderer's own (not Streamline's)
inline bool recovers(bool lost, bool on, bool dlssg_active) { return lost && on && !dlssg_active; }

/// The least time between two tries to make the surface again
constexpr int64_t kRetryMs = 250;

/// A try is due at now_ms: none made yet (last_ms 0), or the last one kRetryMs ago or more
inline bool retry_due(int64_t now_ms, int64_t last_ms) { return !last_ms || now_ms - last_ms >= kRetryMs; }

}   // namespace surface_lost
