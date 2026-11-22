// (Triforce) The GPU held at amdgpu's stable power state while the game runs: Linux only, the rule in gpu_clock.h
// (RX_VK_GPU_CLOCK). The render node Vulkan names (VK_EXT_physical_device_drm) is opened, checked to be that device, and given an
// amdgpu context of the renderer's own whose stable power state is set; the file stays open to the process's end, when the kernel
// frees the context and gives the level back (a crash or kill -9 too). Elsewhere this file is empty.
#include "vk_gpu_clock.h"

#ifdef __linux__
#include "gpu_clock.h"
#include "vk_internal.h"   // (before sys/sysmacros.h: its major and minor are macros)

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

namespace mkwvk {

namespace {

// (union drm_amdgpu_ctx: what goes in, and what an allocation gives back)
union AmdgpuCtx {
    struct {
        uint32_t op, flags, ctx_id;
        int32_t priority;
    } in;
    struct {
        uint32_t ctx_id, pad;
    } alloc;
    uint64_t words[2];
};
static_assert(sizeof(AmdgpuCtx) == gpu_clock::kCtxArgBytes, "union drm_amdgpu_ctx is 16 bytes");

int held_fd = -1;   // (kept open to the process's end: closing it gives the level back)

/// power_dpm_force_performance_level's first word, into out; false when it cannot be read
bool read_level(long long minor, char* out, size_t cap) {
    char path[96];
    snprintf(path, sizeof path, "/sys/class/drm/renderD%lld/device/power_dpm_force_performance_level", minor);
    FILE* f = fopen(path, "r");
    if (!f) return false;
    const bool ok = fgets(out, (int)cap, f) != nullptr;
    fclose(f);
    if (!ok) return false;
    out[strcspn(out, " \t\r\n")] = 0;
    return *out != 0;
}

}   // namespace

void gpu_clock_device_created(bool drm_ext) {
    if (dev.props.vendorID != 0x1002) return;
    const bool integrated = dev.props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;
    const char* sw = getenv("RX_VK_GPU_CLOCK");
    if (sw && !strcmp(sw, "0")) {
        logf("vk: GPU clock: left to the driver (RX_VK_GPU_CLOCK=0)");
        return;
    }
    if (!drm_ext) {
        logf("vk: GPU clock: left to the driver (no VK_EXT_physical_device_drm to name the GPU's render node)");
        return;
    }
    VkPhysicalDeviceDrmPropertiesEXT drm{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRM_PROPERTIES_EXT};
    VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
    p2.pNext = &drm;
    vkGetPhysicalDeviceProperties2(dev.physical, &p2);
    if (!drm.hasRender) {
        logf("vk: GPU clock: left to the driver (the GPU has no render node)");
        return;
    }
    char level[32] = {};
    const bool have_level = read_level((long long)drm.renderMinor, level, sizeof level);
    const gpu_clock::Choice c = gpu_clock::choose(sw, dev.props.vendorID, integrated, dev.props.deviceName, getenv("SteamDeck"),
                                                  have_level ? level : nullptr);
    if (c.want == gpu_clock::kNone) {
        logf("vk: GPU clock: left to the driver (%s; level %s)", c.why, have_level ? level : "unread");
        return;
    }
    char node[64];
    snprintf(node, sizeof node, "/dev/dri/renderD%lld", (long long)drm.renderMinor);
    const int fd = open(node, O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        logf("vk: GPU clock: left to the driver (%s cannot be opened, errno %d)", node, errno);
        return;
    }
    struct stat st{};
    if (fstat(fd, &st) || !S_ISCHR(st.st_mode) || major(st.st_rdev) != (unsigned)drm.renderMajor ||
        minor(st.st_rdev) != (unsigned)drm.renderMinor) {
        logf("vk: GPU clock: left to the driver (%s is not the device Vulkan names, %lld:%lld)", node, (long long)drm.renderMajor,
             (long long)drm.renderMinor);
        close(fd);
        return;
    }
    AmdgpuCtx a{};
    a.in.op = gpu_clock::kCtxOpAlloc;
    if (ioctl(fd, gpu_clock::kCtxIoctl, &a)) {
        logf("vk: GPU clock: left to the driver (no amdgpu context, errno %d)", errno);
        close(fd);
        return;
    }
    AmdgpuCtx s{};
    s.in.op = gpu_clock::kCtxOpSetStablePstate;
    s.in.flags = c.want == gpu_clock::kPeak ? gpu_clock::kPstatePeak : gpu_clock::kPstateStandard;
    s.in.ctx_id = a.alloc.ctx_id;
    if (ioctl(fd, gpu_clock::kCtxIoctl, &s)) {
        // (EBUSY: another holds a stable power state, a profiler or RADV_PROFILE_PSTATE; EINVAL: a kernel before 5.18)
        logf("vk: GPU clock: left to the driver (the stable power state was refused, errno %d)", errno);
        close(fd);
        return;
    }
    held_fd = fd;
    logf("vk: GPU clock: held at amdgpu's %s stable power state while the game runs (%s; level was %s; the kernel gives it back at "
         "the end; RX_VK_GPU_CLOCK=0: left to the driver)", c.want == gpu_clock::kPeak ? "peak" : "standard", c.why,
         have_level ? level : "unread");
}

}   // namespace mkwvk
#endif
