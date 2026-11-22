"""The swapchain's image waited for on the CPU through the acquire's fence, not on the replay's queue (gpu/vk/vk_replay.cpp
present_image, acquire_fence, image_free, held_image_drop, RX_VK_ACQUIRE_FENCE).

AMD's Windows driver returns from vkAcquireNextImageKHR at once, the image not yet free: with the window covered the blit's
submit waited on the queue for the acquire's semaphore, every later submit of the replay queued behind it, and the game froze
for as long as the cover. present_image's acquire, its hold and its submit's waits are cut out unchanged and run against a model
presentation engine that hands out an image before it is free (its fence signaled only once it is). Checked:

- the image free at once: one acquire a present, with the fence and no semaphore; the submit waits for nothing;
- the window covered (images back after 1 s): the first present waits 250 ms and holds the image, no frame is submitted, later
  presents acquire nothing more and do not wait, and the first present after the image is back submits into it, waiting for
  nothing; the next acquire then gets an unsignaled fence;
- a swapchain made again during a hold: the hold let go, its fence abandoned (never reset or waited for again), the next
  acquire with a new, unsignaled fence;
- device loss in the fence's wait reported;
- RX_VK_ACQUIRE_FENCE=0, and DLSS frame generation running: the acquire signals the frame's semaphore and the submit waits for it,
  as before, and nothing is held.

    python -I -B tests/test_present_image_free.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def fail(message):
    raise SystemExit("FAIL: " + message)


HEAD = r'''#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <string>
#include <vector>
using VkResult = int;
using VkFence = uint64_t;
using VkSemaphore = uint64_t;
using VkCommandBuffer = uint64_t;
using VkSwapchainKHR = uint64_t;
constexpr uint64_t VK_NULL_HANDLE = 0;
constexpr VkResult VK_SUCCESS = 0, VK_NOT_READY = 1, VK_TIMEOUT = 2, VK_ERROR_DEVICE_LOST = -4,
                   VK_SUBOPTIMAL_KHR = 1000001003, VK_ERROR_OUT_OF_DATE_KHR = -1000001004;
constexpr int VK_TRUE = 1, VK_STRUCTURE_TYPE_FENCE_CREATE_INFO = 8, VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO = 1000314005,
              VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO = 1000314006, VK_STRUCTURE_TYPE_SUBMIT_INFO_2 = 1000314004;
constexpr uint64_t VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT = 0x10000;
struct VkFenceCreateInfo { int sType; };
struct VkSemaphoreSubmitInfo { int sType; const void* pNext; VkSemaphore semaphore; uint64_t value; uint64_t stageMask; uint32_t deviceIndex; };
struct VkCommandBufferSubmitInfo { int sType; const void* pNext; VkCommandBuffer commandBuffer; uint32_t deviceMask; };
struct VkSubmitInfo2 {
    int sType; const void* pNext; uint32_t flags; uint32_t waitSemaphoreInfoCount; const VkSemaphoreSubmitInfo* pWaitSemaphoreInfos;
    uint32_t commandBufferInfoCount; const VkCommandBufferSubmitInfo* pCommandBufferInfos; uint32_t signalSemaphoreInfoCount;
    const VkSemaphoreSubmitInfo* pSignalSemaphoreInfos;
};
struct Extent { uint32_t width = 1280, height = 720; };
struct {
    int device = 1;
    VkSwapchainKHR swapchain = 7;
    Extent swap_extent;
    std::vector<VkSemaphore> swap_rendered{0x51, 0x52, 0x53};
    std::mutex present_mu;
    uint64_t swap_generation = 1;
    std::atomic<uint64_t> swap_resize{0};
} dev;
namespace dlssg { bool on = false; bool active() { return on; } }
// (PRESENT-45: a lost surface's handling at the acquire; none is lost here, tests/test_present_surface_lost.py runs it)
bool surface_recover(VkResult) { return false; }
void invalidate_lost_surface() {}
struct { std::atomic<int64_t> paced_ns{0}; } present_fig;
struct Lost {};
int lost_reports = 0;
[[noreturn]] void device_lost() { ++lost_reports; throw Lost{}; }
void logf(const char*, ...) {}
#define CHECK(c) do { if (!(c)) { std::printf("CHECK failed line %d: %s\n", __LINE__, #c); std::exit(7); } } while (0)

// ---- the model presentation engine: it hands out an image at once, before it is free; the acquire's fence is signaled
// when the image is free. One clock, moved by the presents and by the fence waits
int64_t now_ms = 0;
struct Image { bool app = false; int64_t free_at = 0; };
std::vector<Image> images(3);
uint32_t next_image = 0;
struct FenceState { bool signaled = false, pending = false; int64_t at = 0; int resets = 0, waits = 0; };
std::map<VkFence, FenceState> fences;
VkFence next_fence = 0xf00;
int acquires = 0, acquire_with_semaphore = 0, remakes = 0;
bool wait_lost = false, bad_reset = false, bad_fence = false;
int64_t return_after_ms = 16;   // (an image presented is free again this long after)
VkResult vkCreateFence(int, const VkFenceCreateInfo* fi, const void*, VkFence* out) {
    CHECK(fi && fi->sType == VK_STRUCTURE_TYPE_FENCE_CREATE_INFO);
    *out = ++next_fence;
    fences[*out] = {};
    return VK_SUCCESS;
}
VkResult vkAcquireNextImageKHR(int, VkSwapchainKHR sc, uint64_t, VkSemaphore semaphore, VkFence fence, uint32_t* index) {
    CHECK(sc == dev.swapchain && (semaphore || fence) && !(semaphore && fence));
    acquires++;
    uint32_t i = next_image, tried = 0;
    while (images[i].app && tried++ < images.size()) i = (i + 1) % images.size();
    CHECK(!images[i].app);   // (the app never asks for more images than it may hold)
    next_image = (i + 1) % images.size();
    images[i].app = true;
    if (fence) {
        FenceState& s = fences.at(fence);
        if (s.signaled || s.pending) bad_fence = true;   // (a fence given to an acquire must be unsignaled)
        s.pending = true, s.at = images[i].free_at;
    } else {
        acquire_with_semaphore++;
    }
    *index = i;
    return VK_SUCCESS;
}
VkResult vkWaitForFences(int, uint32_t n, const VkFence* f, int all, uint64_t timeout_ns) {
    CHECK(n == 1 && all == VK_TRUE);
    FenceState& s = fences.at(*f);
    s.waits++;
    if (wait_lost) return VK_ERROR_DEVICE_LOST;
    const int64_t timeout_ms = (int64_t)(timeout_ns / 1000000);
    if (s.pending && s.at <= now_ms + timeout_ms) {
        if (s.at > now_ms) now_ms = s.at;
        s.pending = false, s.signaled = true;
    }
    if (s.signaled) return VK_SUCCESS;
    now_ms += timeout_ms;
    return VK_TIMEOUT;
}
VkResult vkResetFences(int, uint32_t n, const VkFence* f) {
    CHECK(n == 1);
    FenceState& s = fences.at(*f);
    if (s.pending) bad_reset = true;
    s.signaled = false, s.resets++;
    return VK_SUCCESS;
}
bool create_swapchain(uint32_t, uint32_t) { return ++remakes, true; }
void remake(int64_t free_at) {   // (a swapchain made again: its images new, the generation one more)
    for (auto& im : images) im = {false, free_at};
    next_image = 0;
    dev.swap_generation++;
}
struct Frame { VkSemaphore acquired = 0x5e0; VkCommandBuffer cmd = 0xc0; } frame_slot;
int submits = 0;
uint32_t submit_waits = 99, submitted_index = 99;
VkSemaphore submit_wait_semaphore = 0;
'''

STEP = r'''
/// One present, as present_image's (its image presented at the submit, back return_after_ms later)
void present_body() {
    Frame& f = frame_slot;
@ACQUIRE@
@SUBMIT@
    submits++;
    submit_waits = si.waitSemaphoreInfoCount;
    submit_wait_semaphore = si.waitSemaphoreInfoCount ? si.pWaitSemaphoreInfos[0].semaphore : 0;
    submitted_index = index;
    CHECK(si.signalSemaphoreInfoCount == 1 && si.pSignalSemaphoreInfos[0].semaphore == dev.swap_rendered[index]);
    images[index].app = false, images[index].free_at = now_ms + return_after_ms;
}
/// true when the present got to the submit
bool present_step() {
    const int before = submits;
    present_body();
    return submits > before;
}
int main(int argc, char** argv) {
    CHECK(argc == 2);
    const std::string k = argv[1];
    const bool off = getenv("RX_VK_ACQUIRE_FENCE") && !atoi(getenv("RX_VK_ACQUIRE_FENCE"));
    dlssg::on = getenv("TEST_DLSSG") != nullptr;
    const bool semaphore_way = off || dlssg::on;
    if (k == "free") {
        for (int i = 0; i < 30; i++, now_ms += 16) {
            CHECK(present_step());
            CHECK(acquires == i + 1);
            if (semaphore_way) CHECK(submit_waits == 1 && submit_wait_semaphore == frame_slot.acquired);
            else CHECK(submit_waits == 0 && acquire_with_semaphore == 0);
        }
        CHECK(!bad_fence && !bad_reset);
        if (!semaphore_way) CHECK(fences.size() == 1);   // (one fence, reset after each wait)
    } else if (k == "covered") {
        for (auto& im : images) im.free_at = 1000;   // (the window covered until 1 s)
        int shown = 0, first_shown_at = -1;
        for (int i = 0; i < 100; i++) {
            const int64_t before = now_ms;
            const int acquired_before = acquires;
            const bool went = present_step();
            if (semaphore_way) {
                CHECK(went && submit_waits == 1 && submit_wait_semaphore == frame_slot.acquired);   // (the queue waits, as before)
            } else {
                if (i == 0) CHECK(!went && now_ms - before == 250 && acquires == 1);   // (250 ms, then held)
                if (i > 0 && !went) CHECK(acquires == acquired_before && now_ms == before);   // (no second acquire, no wait)
                if (went) {
                    CHECK(submit_waits == 0);
                    if (first_shown_at < 0) {
                        first_shown_at = (int)now_ms;
                        CHECK(submitted_index == 0 && acquires == 1);   // (the held image, back)
                    }
                }
            }
            shown += went;
            now_ms += 16;
        }
        if (!semaphore_way) {
            CHECK(first_shown_at >= 1000 && first_shown_at < 1016 + 16);
            CHECK(shown > 0 && !bad_fence && !bad_reset);
        }
    } else if (k == "remake") {
        if (semaphore_way) { std::printf("OK %s\n", k.c_str()); return 0; }
        for (auto& im : images) im.free_at = 100000;
        CHECK(!present_step());   // (held)
        const VkFence old = fences.begin()->first;
        const int old_resets = fences.at(old).resets, old_waits = fences.at(old).waits;
        remake(now_ms);   // (made again, its images free)
        now_ms += 16;
        CHECK(present_step());
        CHECK(acquires == 2 && fences.size() == 2 && !bad_fence && !bad_reset);
        CHECK(fences.at(old).resets == old_resets && fences.at(old).waits == old_waits);   // (abandoned)
        now_ms += 16;
        CHECK(present_step() && acquires == 3 && fences.size() == 2 && submit_waits == 0);
    } else if (k == "lost") {
        if (semaphore_way) { std::printf("OK %s\n", k.c_str()); return 0; }
        wait_lost = true;
        try { present_step(); CHECK(!"went on past a device loss"); } catch (const Lost&) {}
        CHECK(lost_reports == 1 && submits == 0);
    } else {
        CHECK(!"no such case");
    }
    std::printf("OK %s\n", k.c_str());
    return 0;
}
'''


def fixture(replay):
    present = block(replay, "void present_image(VkImage src, uint32_t sw, uint32_t sh, const int crop[4], VkImageView view) {")
    a = present.index("    uint32_t index = 0;\n")
    acquire = present[a:present.index("    if (vkResetFences(dev.device, 1, &f.done)", a)]
    s = present.index("    VkSemaphoreSubmitInfo waits[1] = {{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO}};")
    e = present.index("    si.pSignalSemaphoreInfos = &signal;", s)
    submit = present[s:e] + "    si.pSignalSemaphoreInfos = &signal;\n"
    h = replay.index("bool acquire_fence_on() {")
    helpers = replay[h:replay.index(block(replay, "VkResult image_free(uint64_t timeout_ns) {"), h)] + \
        block(replay, "VkResult image_free(uint64_t timeout_ns) {")
    return HEAD + helpers + STEP.replace("@ACQUIRE@", acquire).replace("@SUBMIT@", submit)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    vk_main = (ROOT / "gpu" / "vk" / "vk_main.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    try:
        text = fixture(replay)
        made = vk_main[vk_main.index("    dev.swapchain = sc;"):]
        if "dev.swap_generation++;" not in made[:made.index("swap_views_make(")]:
            fail("create_swapchain does not count the swapchains it makes (dev.swap_generation)")
    except ValueError as e:
        fail("a text this test reads moved, or is not there (%s)" % e)
    if "`RX_VK_ACQUIRE_FENCE=0`" not in dev:
        fail("docs/development.md has no RX_VK_ACQUIRE_FENCE row")
    problems = []
    with tempfile.TemporaryDirectory(prefix="present-image-free-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(text, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wno-unused-function", "-Wno-unused-variable", str(cpp),
                                "-o", str(exe)], capture_output=True, text=True)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        base = {k: v for k, v in os.environ.items() if k not in ("RX_VK_ACQUIRE_FENCE", "TEST_DLSSG")}
        n = 0
        for label, extra in (("default", {}), ("=1", {"RX_VK_ACQUIRE_FENCE": "1"}), ("=0", {"RX_VK_ACQUIRE_FENCE": "0"}),
                             ("DLSS frame generation", {"TEST_DLSSG": "1"})):
            for case in ("free", "covered", "remake", "lost"):
                n += 1
                done = subprocess.run([str(exe), case], env={**base, **extra}, capture_output=True, text=True, timeout=30)
                if done.returncode or done.stdout.strip() != "OK " + case:
                    problems.append("%s (%s): %s" % (case, label, (done.stdout + done.stderr).strip()))
    if problems:
        fail("\n  ".join([""] + problems))
    print("PASS: the swapchain's image waited for on the CPU, held while covered with no second acquire, the blit's submit "
          "waiting for nothing; =0 and DLSS frame generation keep the semaphore (%d cases)" % n)


if __name__ == "__main__":
    main()
