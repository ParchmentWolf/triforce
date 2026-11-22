// (Triforce, 11-22, the performance audit's OS-08, after Source A's) Whether guest memory is offered to the driver as
// udmabuf dma-bufs at all, and what the start's line says (vk_memory.cpp import_dma_buf asks at its first call; plain code:
// tests/test_dmabuf_driver_gate.py runs it anywhere).
//
// On Linux the guest window is a memfd and each pool is first offered to the driver as a dma-buf made by udmabuf. NVIDIA's
// proprietary driver refuses every one (VK_ERROR_OUT_OF_DEVICE_MEMORY) and the pool ends as a host-pointer import anyway:
// 49-50 refused imports a run and a kernel message at each start on Source A's RTX 4090, the first refusal 2.5-3.7 ms, one
// of a 64 MB piece 198 ms on the presentation thread during a save load. So with that driver /dev/udmabuf is not opened
// and the pools are host-pointer imports from the start. NVK and RADV have other driver ids and keep their dma-bufs.
// RX_VK_DMABUF_NVIDIA=1: tried on NVIDIA's driver too, as before (for a later driver that takes them).
#pragma once

namespace dmabuf_gate {

/// What the start found. fn: the host gave its memfd function (false also with RX_VK_NO_DMABUF). memfd: the window is a
/// memfd. ext: the device imports dma-bufs (VK_EXT_external_memory_dma_buf and its fd properties call). nvidia: NVIDIA's
/// proprietary driver, and RX_VK_DMABUF_NVIDIA not set
struct Facts {
    bool fn = false, memfd = false, ext = false, nvidia = false;
};

/// Whether /dev/udmabuf is opened: only then can a pool be offered as a dma-buf
inline bool try_udmabuf(const Facts& f) { return f.fn && f.memfd && f.ext && !f.nvidia; }

/// As it was: NVIDIA's driver was offered them too
inline bool try_udmabuf_before(const Facts& f) { return f.fn && f.memfd && f.ext; }

/// The start's "vk: guest memory as dma-bufs: ..." answer. opened: /dev/udmabuf opened (asked only after try_udmabuf)
inline const char* answer(const Facts& f, bool opened) {
    if (try_udmabuf(f) && opened) return "yes";
    if (!f.fn) return "no (no memfd window, or RX_VK_NO_DMABUF)";
    if (!f.memfd) return "no (the window is anonymous memory)";
    if (!f.ext) return "no (VK_EXT_external_memory_dma_buf)";
    if (f.nvidia) return "no (NVIDIA's driver refuses them: host pointers)";
    return "no (/dev/udmabuf cannot be opened)";
}

}   // namespace dmabuf_gate
