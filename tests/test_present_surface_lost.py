"""Presentation made again after the window's surface is lost (gpu/vk/surface_lost.h, vk_main.cpp create_swapchain,
invalidate_lost_surface and open_window_surface, vk_replay.cpp present_image and present_out, RX_VK_SURFACE_RECOVER; no
game, no GPU).

(Triforce, 11-22, the performance audit's PRESENT-45, after Source A's.) VK_ERROR_SURFACE_LOST_KHR from an acquire, a
present or a swapchain's creation was not handled: every later acquire failed without a word and the picture stayed
frozen until a restart. Now what hangs on the surface is let go and the next swapchain's creation makes a surface for
the window again.

The scripted runs have no window, so this is the proof there is. It compiles surface_lost.h (the rule) and the real
code cut out of the two files: invalidate_lost_surface and open_window_surface whole (the Windows branch and the other
one, each compiled here as code), create_swapchain's first step (the missing surface and the capabilities' query) and its
creation step, present_image's first step and its acquire, and present_out's last step; against a model of a driver that
can lose its surface at each of those calls and counts every handle. It runs:

- the loss at the acquire: the present thread settled first, then the device idle, the views, the image semaphores, the
  swapchain and the surface destroyed in that order, each once; nothing recorded or submitted; the next present makes a
  surface (the startup's calls, the presents' queue chosen again) and a swapchain, and shows a frame;
- the loss at the present, on the presenting thread (let go there) and on the present thread (only noted: no Vulkan
  call from that thread; the next present_image lets go and makes again);
- the loss at the creation and at the capabilities' query: the surface goes too, nothing is left published;
- a window with no size (minimized): no surface is made and none is asked of the driver until it has one again;
- a surface that cannot be made, or that the replay's queue cannot present to: tried again no sooner than 250 ms later,
  the first 8 failures said, nothing leaked;
- many losses in a row: every handle made is destroyed once (a steady handle count), never one in use;
- RX_VK_SURFACE_RECOVER=0 and NVIDIA DLSS frame generation: nothing is let go, as before;
- a held image (RX_VK_ACQUIRE_FENCE) of a swapchain that went with a lost surface is left behind, not looked at again.

Then the source: every new statement of the default path is behind the lost result or the missing surface; start() is
untouched (it still makes the first surface itself); the switch is read once; and the switch's row is in the guide.

    python -I -B tests/test_present_surface_lost.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def between(text, first, last, inclusive=True):
    start = text.index(first)
    end = text.index(last, start)
    return text[start:end + (len(last) if inclusive else 0)]


FIXTURE = r'''
#include <algorithm>
#include <atomic>
#include <chrono>
#include <climits>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>
#include <chrono>
#include "surface_lost.h"

static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)

// ---- Vulkan's names, as far as the cut code uses them
using VkFence = uint64_t;
using VkSemaphore = uint64_t;
using VkSwapchainKHR = uint64_t;
using VkSurfaceKHR = uint64_t;
using VkImage = uint64_t;
using VkImageView = uint64_t;
using VkResult = int;
using VkBool32 = uint32_t;
constexpr uint64_t VK_NULL_HANDLE = 0;
enum { VK_SUCCESS = 0, VK_NOT_READY = 1, VK_TIMEOUT = 2, VK_SUBOPTIMAL_KHR = 1000001003, VK_ERROR_OUT_OF_DATE_KHR = -1000001004,
       VK_ERROR_SURFACE_LOST_KHR = -1000000000, VK_ERROR_DEVICE_LOST = -4, VK_TRUE = 1, VK_FALSE = 0 };
enum { VK_STRUCTURE_TYPE_FENCE_CREATE_INFO = 8, VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO = 9,
       VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR = 1000009000, VK_STRUCTURE_TYPE_IMAGE_FORMAT_LIST_CREATE_INFO = 1000147000 };
enum { VK_PRESENT_MODE_MAILBOX_KHR = 1, VK_PRESENT_MODE_IMMEDIATE_KHR = 0, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT = 16,
       VK_SWAPCHAIN_CREATE_MUTABLE_FORMAT_BIT_KHR = 4 };
using VkFormat = int;
struct VkFenceCreateInfo { int sType; const void* pNext = nullptr; unsigned flags = 0; };
struct VkSemaphoreCreateInfo { int sType; };
struct VkExtent2D { uint32_t width = 0, height = 0; };
struct VkSurfaceCapabilitiesKHR { VkExtent2D currentExtent; };
struct VkImageFormatListCreateInfo { int sType; const void* pNext = nullptr; uint32_t viewFormatCount = 0; const VkFormat* pViewFormats = nullptr; };
struct VkSwapchainCreateInfoKHR { VkSurfaceKHR surface = 0; VkSwapchainKHR oldSwapchain = 0; unsigned imageUsage = 1, minImageCount = 4, flags = 0;
                                  const void* pNext = nullptr; };
// (the window's side: Windows' names for the Windows branch, the SDL bridge's for the other)
struct RECT { long left = 0, top = 0, right = 0, bottom = 0; };
using HWND = void*;
struct VkWin32SurfaceCreateInfoKHR { int sType; void* hinstance = nullptr; HWND hwnd = nullptr; };
struct MkwVkWindow {
    uint32_t version;
    int (*create_surface)(void* window, void* instance, void* surface_out);
    void (*drawable_size)(void* window, int* width, int* height);
    void* window;
};

// ---- the renderer's names
struct Device {
    uint64_t instance = 7, physical = 8;
    int device = 1, queue = 2;
    uint32_t queue_family = 0, present_family = 3;
    uint64_t present_queue = 55;   // (the presents' own queue, asked for at the start)
    VkSurfaceKHR surface = 0;
    VkSwapchainKHR swapchain = 0;
    uint64_t swap_generation = 0;
    int swap_format = 0;
    VkExtent2D swap_extent{640, 480};
    bool swap_mutable = false;
    std::vector<VkImage> swap_images;
    std::vector<VkImageView> swap_views;
    std::vector<VkSemaphore> swap_rendered;
    std::atomic<uint64_t> swap_resize{0};
    std::mutex present_mu;
} dev;
struct { int hdr = 0, vsync = 1; } opts;
struct Frame { VkFence done; VkSemaphore acquired; int cmd; };
Frame frames[3] = {{900, 800, 1}, {901, 801, 2}, {902, 802, 3}};
uint32_t frame_index = 0;
struct Lost {};
[[noreturn]] void device_lost() { throw Lost{}; }
int log_lines = 0;
std::string last_log;
template <class... A> void logf(const char* f, A...) { ++log_lines, last_log = f; }
bool vk_ft_on() { return false; }
template <class... A> void vk_ft(const char*, A...) {}
bool dlssg_active = false;
namespace dlssg { bool active() { return dlssg_active; } }
namespace gpu_wait_kinds { struct Exclude {}; }   // ((Triforce, 11-23) image_free's compositor wait, not counted)
namespace pace {
int64_t steady_floor_ns() { return 0; }
void steady_held(int64_t) {}
}
struct Host { int64_t (*now_ns)(); };
int64_t clock_ns = 1000000000;
Host host_model{[]() -> int64_t { return clock_ns; }};
Host* host = &host_model;
VkFormat unorm_of(VkFormat f) { return f; }
void reflex_swapchain_info(VkSwapchainCreateInfoKHR&) {}
bool reflex_swapchain_stale() { return false; }

// ---- the model: a driver that counts its handles, and loses its surface when told
struct Model {
    uint64_t serial = 1000;
    std::set<uint64_t> surfaces, swapchains, semaphores, views, fences;
    std::vector<std::string> order;   // (what was destroyed or waited for, in order)
    int bad = 0;
    bool idle = false;                // (the device was waited for since the last work)
    bool in_flight = false;           // (a frame names the swapchain's images)
    // what the next call of each kind answers
    VkResult acquire_result = VK_SUCCESS, present_result = VK_SUCCESS, create_result = VK_SUCCESS, caps_result = VK_SUCCESS,
             surface_result = VK_SUCCESS;
    VkBool32 can_present = VK_TRUE, own_queue_can_present = VK_TRUE;
    long window_w = 640, window_h = 480;
    int surfaces_made = 0, swapchains_made = 0, surface_tries = 0, support_asked = 0, acquires = 0, presents = 0, submits = 0, settles = 0;
    int queue_chosen = 0, invalidated = 0, reflex_off = 0;
    bool on_present_thread = false;
    int thread_calls = 0;             // (Vulkan calls made while the model is on the present thread, the present itself apart)
} m;
void fail(const char* why) { std::printf("MODEL: %s\n", why); m.bad++; }
void touch() { if (m.on_present_thread) m.thread_calls++; }
void queue_flush_locked() {}
void device_wait_idle_locked() { touch(); m.idle = true, m.in_flight = false; m.order.push_back("idle"); }
void reflex_swapchain_destroyed() { m.reflex_off++; m.order.push_back("reflex"); }
void swap_views_drop() {
    touch();
    for (auto v : dev.swap_views) {
        if (!m.idle) fail("a view destroyed with the device busy");
        if (!m.views.erase(v)) fail("a view destroyed twice");
        m.order.push_back("view");
    }
    dev.swap_views.clear();
}
void swap_views_make(unsigned, VkFormat) {
    swap_views_drop();
    for (size_t i = 0; i < dev.swap_images.size(); i++) dev.swap_views.push_back(++m.serial), m.views.insert(m.serial);
}
void vkDestroySemaphore(int, VkSemaphore s, void*) {
    touch();
    if (!m.idle) fail("a semaphore destroyed with the device busy");
    if (!m.semaphores.erase(s)) fail("a semaphore destroyed twice, or never made");
    m.order.push_back("semaphore");
}
VkResult vkCreateSemaphore(int, const VkSemaphoreCreateInfo*, void*, VkSemaphore* out) {
    *out = ++m.serial, m.semaphores.insert(*out);
    return VK_SUCCESS;
}
void vkDestroySwapchainKHR(int, VkSwapchainKHR sc, void*) {
    touch();
    if (!m.idle) fail("a swapchain destroyed with the device busy");
    if (!m.views.empty() && sc == dev.swapchain) fail("the swapchain destroyed before its views");
    if (!m.swapchains.erase(sc)) fail("a swapchain destroyed twice, or never made");
    m.order.push_back("swapchain");
}
void vkDestroySurfaceKHR(uint64_t, VkSurfaceKHR s, void*) {
    touch();
    if (!m.swapchains.empty()) fail("the surface destroyed before its swapchain");
    if (!m.surfaces.erase(s)) fail("a surface destroyed twice, or never made");
    m.order.push_back("surface");
}
VkResult vkCreateSwapchainKHR(int, const VkSwapchainCreateInfoKHR* ci, void*, VkSwapchainKHR* out) {
    if (!ci->surface || !m.surfaces.count(ci->surface)) fail("a swapchain asked for a surface that is not there");
    if (ci->oldSwapchain && !m.swapchains.count(ci->oldSwapchain)) fail("an old swapchain that is not there");
    if (m.create_result != VK_SUCCESS) return m.create_result;
    *out = ++m.serial, m.swapchains.insert(*out), m.swapchains_made++;
    m.idle = false;
    return VK_SUCCESS;
}
VkResult vkGetSwapchainImagesKHR(int, VkSwapchainKHR, uint32_t* n, VkImage* out) {
    *n = 4;
    if (out) for (uint32_t i = 0; i < 4; i++) out[i] = 5000 + i;
    return VK_SUCCESS;
}
VkResult vkGetPhysicalDeviceSurfaceCapabilitiesKHR(uint64_t, VkSurfaceKHR s, VkSurfaceCapabilitiesKHR* caps) {
    if (!s || !m.surfaces.count(s)) fail("the capabilities asked of a surface that is not there");
    if (m.caps_result != VK_SUCCESS) return m.caps_result;
    caps->currentExtent = {(uint32_t)m.window_w, (uint32_t)m.window_h};
    return VK_SUCCESS;
}
VkResult vkGetPhysicalDeviceSurfaceSupportKHR(uint64_t, uint32_t family, VkSurfaceKHR s, VkBool32* ok) {
    if (!s || !m.surfaces.count(s)) fail("present support asked of a surface that is not there");
    m.support_asked++;
    *ok = family == dev.queue_family ? m.can_present : m.own_queue_can_present;
    return VK_SUCCESS;
}
// (the window: Windows' calls, and the SDL bridge's)
HWND main_window = (HWND)&m;
int GetClientRect(HWND, RECT* r) { *r = {0, 0, m.window_w, m.window_h}; return 1; }
void* GetModuleHandleA(const char*) { return nullptr; }
VkResult vkCreateWin32SurfaceKHR(uint64_t, const VkWin32SurfaceCreateInfoKHR* si, void*, VkSurfaceKHR* out) {
    m.surface_tries++;
    if (si->hwnd != main_window) fail("a surface for another window");
    if (m.window_w <= 0 || m.window_h <= 0) fail("a surface asked for a window with no size");
    if (m.surface_result != VK_SUCCESS) return m.surface_result;
    *out = ++m.serial, m.surfaces.insert(*out), m.surfaces_made++;
    return VK_SUCCESS;
}
MkwVkWindow sdl{2,
                [](void*, void*, void* out) -> int {
                    m.surface_tries++;
                    if (m.window_w <= 0 || m.window_h <= 0) fail("a surface asked for a window with no size");
                    if (m.surface_result != VK_SUCCESS) return 0;
                    *(VkSurfaceKHR*)out = ++m.serial, m.surfaces.insert(m.serial), m.surfaces_made++;
                    return 1;
                },
                [](void*, int* w, int* h) { *w = (int)m.window_w, *h = (int)m.window_h; }, nullptr};
const MkwVkWindow* prep_window = &sdl;
/// vk_main.cpp's, whole
@CHOOSE@

// ---- vk_main.cpp's own code
bool open_window_surface(bool log_failure);
@SURFACE_RECOVER@
@INVALIDATE@
@OPEN@

/// create_swapchain: its first step and its creation step as they are, the surface's formats and modes between them left out
bool create_swapchain(uint32_t width, uint32_t height) {
@CREATE_HEAD@
    if (!width || !height) return false;
    uint32_t n = 0;
    struct { int format = 1; } fmt;
    VkSwapchainCreateInfoKHR ci;
    ci.surface = dev.surface;
    int mode = 0;
@CREATE_TAIL@
    dev.swap_generation++;   // (create_swapchain's own, after its log line: check_source finds it there)
    swap_views_make(ci.imageUsage, 1);
    return true;
}

VkResult vkAcquireNextImageKHR(int, VkSwapchainKHR sc, uint64_t, VkSemaphore, VkFence fence, uint32_t* index) {
    m.acquires++;
    if (!sc || !m.swapchains.count(sc)) fail("an acquire from a swapchain that is not there");
    if (m.acquire_result != VK_SUCCESS) return m.acquire_result;
    if (fence) m.fences.insert(fence);
    *index = 1;
    return VK_SUCCESS;
}
VkResult vkCreateFence(int, const VkFenceCreateInfo*, void*, VkFence* out) { *out = ++m.serial; return VK_SUCCESS; }
VkResult vkResetFences(int, uint32_t, const VkFence*) { return VK_SUCCESS; }
int fence_waits = 0;
bool image_back = true;
VkResult vkWaitForFences(int, uint32_t, const VkFence* f, int, uint64_t) {
    if (*f >= 900 && *f < 903) return VK_SUCCESS;
    fence_waits++;
    return image_back ? VK_SUCCESS : VK_TIMEOUT;
}

// ---- vk_replay.cpp's own code
std::mutex present_image_mu;
void present_thread_settle() { m.settles++; m.order.push_back("settle"); }
void present_note_game(int64_t) {}
struct { std::atomic<int64_t> paced_ns{0}; } present_fig;   // (the acquire's wait, counted as the pacing's)
@HELPERS@
int recorded = 0;
/// present_image: its first step, its acquire and its hold as they are; then the blit's recording and submit stood in for
void present_image_model() {
@BEGIN@
    Frame& f = frames[frame_index];
    frame_index = (frame_index + 1) % 3;
@ACQUIRE@
    ++recorded, m.submits++, m.in_flight = true, m.idle = false;
}
/// present_out's last step as it is: the present's result handled
struct QueueLock {
    bool held = false;
    bool owns_lock() const { return held; }
    void lock() { held = true; }
    void unlock() { held = false; }
};
void present_out_model(VkResult res, QueueLock& qk, bool on_thread) {
    m.presents++;
@OUT@
}

static bool nothing_published() { return !dev.swapchain && !dev.surface && dev.swap_rendered.empty() && dev.swap_images.empty() && dev.swap_views.empty(); }
static bool nothing_left() { return m.surfaces.empty() && m.swapchains.empty() && m.semaphores.empty() && m.views.empty(); }
static bool whole() { return m.surfaces.size() == 1 && m.swapchains.size() == 1 && m.semaphores.size() == 4 && m.views.size() == 4 &&
                             dev.surface && dev.swapchain && dev.swap_rendered.size() == 4; }
/// The teardown's order: the device idle, then every view, every semaphore, the swapchain, the surface, each once
static bool in_order(size_t from) {
    const std::vector<std::string> want = {"idle", "reflex", "view", "view", "view", "view", "semaphore", "semaphore", "semaphore",
                                           "semaphore", "swapchain", "surface"};
    return m.order.size() == from + want.size() && std::equal(want.begin(), want.end(), m.order.begin() + from);
}
/// Past the 250 ms between two tries: the cut code reads the steady clock, so the tries' own time is moved back
static void later() { tried_back(); }

int main(int argc, char** argv) {
    const bool want_on = argc > 1 && argv[1][0] == 'r';
    {   // the rule
        using namespace surface_lost;
        CHECK(on(nullptr) && on("") && on("1") && !on("0"));
        CHECK(recovers(true, true, false) && !recovers(false, true, false) && !recovers(true, false, false) && !recovers(true, true, true));
        CHECK(kRetryMs == 250 && retry_due(1000, 0) && !retry_due(1000, 900) && !retry_due(1149, 900) && retry_due(1150, 900));
    }
    CHECK(surface_recover(VK_ERROR_SURFACE_LOST_KHR) == want_on && !surface_recover(VK_SUCCESS) && !surface_recover(VK_ERROR_OUT_OF_DATE_KHR) &&
          !surface_recover(VK_ERROR_DEVICE_LOST));
    // the start, as start() does it: the surface, then the first swapchain
    CHECK(open_window_surface(true) && create_swapchain(640, 480) && whole() && dev.swap_generation == 1);
    present_image_model();
    CHECK(recorded == 1 && m.acquires == 1);

    if (!want_on) {   // RX_VK_SURFACE_RECOVER=0: the result is not handled, as before
        m.acquire_result = VK_ERROR_SURFACE_LOST_KHR;
        const size_t o = m.order.size();
        for (int i = 0; i < 5; i++) present_image_model();
        CHECK(recorded == 1 && whole() && m.invalidated == 0 && m.surfaces_made == 1 && m.swapchains_made == 1);
        QueueLock qk;
        present_out_model(VK_ERROR_SURFACE_LOST_KHR, qk, false), present_out_model(VK_ERROR_SURFACE_LOST_KHR, qk, true);
        CHECK(whole() && !surface_lost_noted.load());
        for (size_t i = o; i < m.order.size(); i++) CHECK(m.order[i] == "settle");
        CHECK(m.bad == 0);
        std::puts("=0: a lost surface is not handled: nothing let go, nothing made");
        return fails ? 1 : 0;
    }

    {   // lost at the acquire
        const size_t o = m.order.size();
        const int r = recorded;
        m.acquire_result = VK_ERROR_SURFACE_LOST_KHR;
        present_image_model();
        CHECK(m.order[o] == "settle" && in_order(o + 1) && nothing_published() && nothing_left() && recorded == r);
        CHECK(dev.swap_resize.load() == ((uint64_t)640 << 32 | 480));
        m.acquire_result = VK_SUCCESS;
        later();
        present_image_model();   // (the next present: a surface and a swapchain again, and a frame)
        CHECK(whole() && recorded == r + 1 && m.surfaces_made == 2 && m.swapchains_made == 2 && dev.swap_generation == 2 && !dev.swap_resize.load());
        CHECK(m.queue_chosen == 2 && dev.present_queue == 55);   // (the presents' own queue asked of the new surface)
    }
    {   // lost at the present, on the presenting thread: let go there, the queue's lock taken
        const size_t o = m.order.size();
        QueueLock qk;
        present_out_model(VK_ERROR_SURFACE_LOST_KHR, qk, false);
        CHECK(qk.held && in_order(o) && nothing_published() && nothing_left() && !surface_lost_noted.load());
        later();
        present_image_model();
        CHECK(whole() && m.surfaces_made == 3);
    }
    {   // lost at the present, on the present thread: only noted there; the next present_image lets go and makes again
        const size_t o = m.order.size();
        const int r = recorded;
        QueueLock qk;
        m.on_present_thread = true;
        present_out_model(VK_ERROR_SURFACE_LOST_KHR, qk, true);
        m.on_present_thread = false;
        CHECK(m.thread_calls == 0 && !qk.held && whole() && surface_lost_noted.load() && m.order.size() == o);
        later();
        present_image_model();
        CHECK(m.order[o] == "settle" && whole() && !surface_lost_noted.load() && recorded == r + 1 && m.surfaces_made == 4);
        // (let go between the settle and the new swapchain, in order)
        const std::vector<std::string> head(m.order.begin() + o + 1, m.order.begin() + o + 13);
        CHECK(head.front() == "idle" && head.back() == "surface");
    }
    {   // lost at the creation: the old swapchain went with the attempt, and the surface goes too
        m.create_result = VK_ERROR_SURFACE_LOST_KHR;
        dev.swap_resize.store((uint64_t)800 << 32 | 600);
        const int r = recorded;
        present_image_model();
        CHECK(nothing_published() && nothing_left() && recorded == r && dev.swap_resize.load() == ((uint64_t)800 << 32 | 600));
        m.create_result = VK_SUCCESS;
        later();
        present_image_model();
        CHECK(whole() && recorded == r + 1);
    }
    {   // lost at the capabilities' query
        m.caps_result = VK_ERROR_SURFACE_LOST_KHR;
        dev.swap_resize.store((uint64_t)800 << 32 | 600);
        present_image_model();
        CHECK(nothing_published() && nothing_left());
        m.caps_result = VK_SUCCESS;
        later();
        present_image_model();
        CHECK(whole());
    }
    {   // a window with no size: it waits, and nothing is asked of the driver for it
        m.acquire_result = VK_ERROR_SURFACE_LOST_KHR;
        present_image_model();
        m.acquire_result = VK_SUCCESS;
        CHECK(nothing_published());
        m.window_w = 0, m.window_h = 0;
        const int tries = m.surface_tries, r = recorded;
        for (int i = 0; i < 20; i++) later(), present_image_model();
        CHECK(m.surface_tries == tries && nothing_published() && nothing_left() && recorded == r);
        m.window_w = 1280, m.window_h = 720;
        later();
        present_image_model();
        CHECK(whole() && recorded == r + 1 && dev.swap_extent.width == 1280 && dev.swap_extent.height == 720);
    }
    {   // a surface that cannot be made: one try each 250 ms at most, the first 8 failures said
        m.acquire_result = VK_ERROR_SURFACE_LOST_KHR;
        present_image_model();
        m.acquire_result = VK_SUCCESS;
        m.surface_result = -1;
        const int tries = m.surface_tries;
        later();
        const int lines = log_lines;
        for (int i = 0; i < 50; i++) present_image_model();   // (50 presents inside the 250 ms)
        CHECK(m.surface_tries == tries + 1 && log_lines == lines + 1 && nothing_published() && nothing_left());
        later();
        present_image_model();
        CHECK(m.surface_tries == tries + 2 && log_lines == lines + 2);
        // ...and one the replay's queue cannot present to: let go again, nothing leaked
        m.surface_result = VK_SUCCESS, m.can_present = VK_FALSE;
        for (int i = 0; i < 20; i++) later(), present_image_model();
        CHECK(m.surface_tries == tries + 22 && nothing_published() && nothing_left() && log_lines == lines + 8);
        m.can_present = VK_TRUE;
        later();
        present_image_model();
        CHECK(whole());
    }
    {   // the presents' own queue cannot present to the new surface: the replay's queue from then on, as at the start
        m.acquire_result = VK_ERROR_SURFACE_LOST_KHR;
        present_image_model();
        m.acquire_result = VK_SUCCESS, m.own_queue_can_present = VK_FALSE;
        later();
        present_image_model();
        CHECK(whole() && dev.present_queue == 0 && dev.present_family == dev.queue_family);
        m.own_queue_can_present = VK_TRUE;
    }
    {   // many losses in a row, at each call in turn: a steady handle count
        const int made = m.surfaces_made;
        for (int i = 0; i < 30; i++) {
            if (i % 3 == 0) {
                m.acquire_result = VK_ERROR_SURFACE_LOST_KHR;
                present_image_model();
                m.acquire_result = VK_SUCCESS;
            } else {
                QueueLock qk;
                present_out_model(VK_ERROR_SURFACE_LOST_KHR, qk, i % 3 == 2);
            }
            later();
            present_image_model();
            CHECK(whole());
        }
        CHECK(m.surfaces_made == made + 30 && m.surfaces.size() == 1 && m.swapchains.size() == 1 && m.semaphores.size() == 4);
    }
    {   // a held image (RX_VK_ACQUIRE_FENCE) of a swapchain that went with its surface: left behind, not looked at again
        image_back = false;
        present_image_model();
        CHECK(held_image.on && held_image.generation == dev.swap_generation);
        const VkFence left = acquire_fence_now;
        QueueLock qk;
        present_out_model(VK_ERROR_SURFACE_LOST_KHR, qk, false);
        image_back = true;
        later();
        const int a = m.acquires, r = recorded;
        present_image_model();
        CHECK(whole() && !held_image.on && m.acquires == a + 1 && recorded == r + 1 && acquire_fence_now != left);
    }
    {   // NVIDIA DLSS frame generation runs: the swapchain is Streamline's, the result is not handled
        dlssg_active = true;
        const int s = m.surfaces_made;
        m.acquire_result = VK_ERROR_SURFACE_LOST_KHR;
        present_image_model();
        QueueLock qk;
        present_out_model(VK_ERROR_SURFACE_LOST_KHR, qk, false);
        CHECK(whole() && m.surfaces_made == s && !surface_lost_noted.load());
        m.acquire_result = VK_SUCCESS, dlssg_active = false;
    }
    CHECK(m.bad == 0 && m.thread_calls == 0);
    std::printf("recovered: %d surfaces and %d swapchains made, one of each left; %d presents drew\n", m.surfaces_made, m.swapchains_made, recorded);
    return fails ? 1 : 0;
}
'''

# (the cut's own clock: create_swapchain reads the steady clock for its 250 ms. The test moves the last try's time back
# instead of sleeping: its static is made the fixture's own variable, the statement that reads it left as it is)
TRIED = "        static int64_t tried_ms;\n"


def cut_source():
    main = (VK / "vk_main.cpp").read_text(encoding="utf-8")
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    swap = block(main, "bool create_swapchain(uint32_t width, uint32_t height) {")
    parts = {}
    parts["SURFACE_RECOVER"] = block(main, "bool surface_recover(VkResult result) {")
    parts["INVALIDATE"] = block(main, "void invalidate_lost_surface() {")
    parts["OPEN"] = block(main, "bool open_window_surface(bool log_failure) {")
    parts["CHOOSE"] = block(main, "static void choose_present_queue() {").replace(
        "static void choose_present_queue() {", "static void choose_present_queue() {\n    m.queue_chosen++;", 1)
    head = between(swap, "    // ((Triforce, 11-22, PRESENT-45) no surface:", "    logf(\"vk: surface caps images", inclusive=False)
    check(head.count(TRIED) == 1, "create_swapchain's retry clock changed")
    parts["CREATE_HEAD"] = head.replace(TRIED, "        int64_t& tried_ms = tried_ms_model;\n")
    parts["CREATE_TAIL"] = between(swap, "    ci.oldSwapchain = dev.swapchain;", "    logf(\"vk: swapchain %ux%u", inclusive=False)
    image = block(replay, "void present_image(VkImage src, uint32_t sw, uint32_t sh, const int crop[4], VkImageView view) {")
    parts["BEGIN"] = between(image, "    std::lock_guard lk(present_image_mu);", "    if (src) {", inclusive=False)
    parts["ACQUIRE"] = between(image, "    uint32_t index = 0;\n", "    if (vkResetFences(dev.device, 1, &f.done) == VK_ERROR_DEVICE_LOST) device_lost();\n")
    # (RX_VK_ACQUIRE_FENCE's helpers, from its switch to the note of a surface lost on the present thread)
    helpers = between(replay, "bool acquire_fence_on() {", "std::atomic<bool> surface_lost_noted{false};") + "\n"
    check("std::atomic<bool> surface_lost_noted{false};" in replay, "vk_replay.cpp has no note of a surface lost on the present thread")
    parts["HELPERS"] = "// ((Triforce) RX_VK_PRESENT_CHECK's note of an acquire: nothing here)\nstatic void present_check_acquired(uint32_t, uint64_t) {}\n" + helpers
    out = block(replay, "static void present_out(const PresentOut& o, std::unique_lock<QueueMutex>& qk, bool on_thread) {")
    parts["OUT"] = between(out, "    if (surface_recover(res)) {", "    if (res == VK_ERROR_OUT_OF_DATE_KHR || res == VK_SUBOPTIMAL_KHR) {",
                           inclusive=False)
    return main, replay, swap, image, out, parts


def check_source(main, replay, swap, image, out):
    # the default path: every new statement is behind the lost result or the missing surface
    check(swap.count("surface_recover(result)") == 3 and swap.count("invalidate_lost_surface()") == 3,
          "create_swapchain does not hand a lost surface on at its two queries and its creation")
    for line in swap.splitlines():
        if "invalidate_lost_surface()" in line:
            check(line.strip().startswith("if (surface_recover(result)) return invalidate_lost_surface(), false;"),
                  "create_swapchain lets go of the surface for another result than a lost surface")
    check(swap.index("    if (!dev.surface) {") < swap.index("vkGetPhysicalDeviceSurfaceCapabilitiesKHR(") and
          swap.count("open_window_surface(") == 1 and swap.index("open_window_surface(") < swap.index("vkGetPhysicalDeviceSurfaceCapabilitiesKHR("),
          "create_swapchain makes a surface anywhere but first, for a missing one")
    check(image.count("invalidate_lost_surface()") == 2 and out.count("invalidate_lost_surface()") == 1,
          "present_image or present_out lets go of the surface in more places than the acquire, the note and the present")
    at = [image.index(p) for p in ("present_thread_settle();", "if (surface_lost_noted.exchange(false, std::memory_order_acq_rel)) {",
                                   "dev.swap_resize.exchange(0", "vkAcquireNextImageKHR(", "if (surface_recover(res)) {",
                                   "if (res == VK_ERROR_OUT_OF_DATE_KHR) {", "if (vkResetFences(dev.device, 1, &f.done)")]
    check(at == sorted(at), "present_image does not settle the present thread before it lets go, or handles the loss after it records")
    thread = out[out.index("    if (surface_recover(res)) {"):out.index("    if (res == VK_ERROR_OUT_OF_DATE_KHR || res == VK_SUBOPTIMAL_KHR) {")]
    check(thread.index("if (on_thread) {") < thread.index("surface_lost_noted.store(true") < thread.index("return;") < thread.index("invalidate_lost_surface();"),
          "the present thread lets go of the swapchain itself")
    recover = block(main, "bool surface_recover(VkResult result) {")
    check('static const bool on = surface_lost::on(getenv("RX_VK_SURFACE_RECOVER"));' in recover and
          "surface_lost::recovers(result == VK_ERROR_SURFACE_LOST_KHR, on, dlssg::active())" in recover, "RX_VK_SURFACE_RECOVER is not read once")
    check(swap.count("dev.swap_generation++;") == 1 and swap.index("    dev.swapchain = sc;") < swap.index("dev.swap_generation++;"),
          "create_swapchain does not count a new swapchain's generation where it publishes it")
    # start() still makes the first surface itself, as it did
    start = block(main, "int start(void* hwnd) {")
    check("open_window_surface" not in start and "vkCreateWin32SurfaceKHR(dev.instance, &si, nullptr, &dev.surface)" in start and
          "w->create_surface(w->window, (void*)dev.instance, (void*)&dev.surface)" in start and start.count("choose_present_queue();") == 2,
          "start() was changed: the first surface is the startup's own code")
    check(main.count("vkDestroySurfaceKHR(") == 2, "the surface is destroyed somewhere else than the two places of the recovery")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `RX_VK_SURFACE_RECOVER=0` |" in docs and "tests/test_present_surface_lost.py" in docs, "docs/development.md has no row for RX_VK_SURFACE_RECOVER")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    main_text, replay, swap, image, out, parts = cut_source()
    check_source(main_text, replay, swap, image, out)
    env = {k: v for k, v in os.environ.items() if k not in ("RX_VK_SURFACE_RECOVER", "RX_VK_ACQUIRE_FENCE")}
    with tempfile.TemporaryDirectory(prefix="present-surface-lost-") as tmp:
        for name in ("windows", "not-windows"):
            text = FIXTURE
            for key, value in parts.items():
                text = text.replace("@" + key + "@", value)
            # (each platform's branch compiled here as code, whatever this PC is)
            win = name == "windows"
            text = text.replace("#ifdef _WIN32\n", "#if 1\n" if win else "#if 0\n").replace("#ifndef _WIN32\n", "#if 0\n" if win else "#if 1\n")
            text = text.replace("// ---- vk_main.cpp's own code\n",
                                "// ---- vk_main.cpp's own code\nint64_t tried_ms_model = 0;\nvoid tried_back() { tried_ms_model -= 1000; }\n")
            src, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-I", str(VK), str(src), "-o", str(exe)], check=True)
            for value, mode in ((None, "recover"), ("1", "recover"), ("0", "off")):
                run_env = dict(env)
                if value is not None:
                    run_env["RX_VK_SURFACE_RECOVER"] = value
                got = subprocess.run([str(exe), mode], env=run_env, stdout=subprocess.PIPE, text=True, timeout=60)
                if got.returncode:
                    print(got.stdout)
                    raise SystemExit("FAIL: the %s branch with RX_VK_SURFACE_RECOVER %s" % (name, "unset" if value is None else "=" + value))
                if value != "1":
                    print("%s branch, RX_VK_SURFACE_RECOVER %s: %s" % (name, "unset" if value is None else "=" + value,
                                                                       got.stdout.strip().splitlines()[-1]))
    print("PASS: a lost surface at the acquire, the present, the creation or the query is let go in order and made again at the "
          "next present; =0 and DLSS frame generation leave it as before")


if __name__ == "__main__":
    main()
