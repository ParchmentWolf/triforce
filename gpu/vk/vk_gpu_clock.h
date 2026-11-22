// (Triforce) The GPU held at amdgpu's stable power state while the game runs (Linux; gpu_clock.h has the rule, RX_VK_GPU_CLOCK)
#pragma once

#ifdef __linux__
namespace mkwvk {
/// Once, after vkCreateDevice (vk_main.cpp create_device). drm_ext: the device has VK_EXT_physical_device_drm, which names its
/// render node. A log line on AMD GPUs; nothing at all on others
void gpu_clock_device_created(bool drm_ext);
}   // namespace mkwvk
#endif
