// (Triforce, 11-22) N64 Classic at work: see vk_n64.h (n64-classic-mode-plan.md, steps 2 to 8).
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <mutex>

#include "vk_n64.h"
#include "vk_internal.h"   // (logf)
#include "vk_menu.h"       // ((step 5) opts: the Insert menu's N64 Classic row and the Remembered page)
#include "vk_dlssg.h"      // ((step 4) dlssg::active: DLSS frame generation's frames are made after the window pass)
#include "vk_temporal.h"   // (temporal_scene_format: a RenoDX run's RGBA16F scene, which the 3D pass does not take)

namespace mkwvk {
namespace {

/// A switch's number, `unset` when it is not set or is not a number
int env_number(const char* name, int unset) {
    const char* e = getenv(name);
    return e && ((*e >= '0' && *e <= '9') || *e == '-') ? atoi(e) : unset;
}

} // namespace

namespace {
/// RX_VK_N64 for the run, -1 unset
int env_n64() {
    static const int env = [] {
        const int v = env_number("RX_VK_N64", -1);
        if (v >= 0) logf("vk: N64 Classic: RX_VK_N64=%d, %s, for this run over the menu's row", v, n64_rules::name(n64_rules::chosen(0, v)));
        return v;
    }();
    return env;
}
} // namespace

bool n64_env_set() { return env_n64() >= 0; }

namespace {
// ((step 8) the switch, ticked once a present (n64_tick); shown is read by every pass and by the host's answer, so it is an
// atomic of its own, -1 before the first present (then the preset chosen); the TV's frame, read once a present, under the lock)
std::atomic<int> shown_now{-1};
std::mutex switch_mu;
n64_rules::Switch switch_rule;
n64_rules::AnimFrame anim_now;
/// RX_VK_N64_TV_ANIM=0: no switching off and on, the choice at once
bool anim_on() {
    static const bool on = env_number("RX_VK_N64_TV_ANIM", 1) != 0;
    return on;
}
} // namespace

void n64_tick(bool native_pq) {
    const double t = std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
    std::lock_guard lk(switch_mu);
    const int before = shown_now.load(std::memory_order_relaxed);
    const n64_rules::Switch::Now now = switch_rule.at(t, n64_preset(), anim_on() && !native_pq && !dlssg::active());
    anim_now = now.frame;
    shown_now.store(now.shown, std::memory_order_relaxed);
    if (before >= 0 && now.shown != before)
        logf("vk: N64 Classic: %s from here (was %s)", n64_rules::name(now.shown), n64_rules::name(before));
}

int n64_shown() {
    const int s = shown_now.load(std::memory_order_relaxed);
    return s >= 0 ? s : n64_preset();
}

n64_rules::AnimFrame n64_anim() {
    std::lock_guard lk(switch_mu);
    return anim_now;
}

int n64_preset() { return n64_rules::chosen(opts.n64_classic, env_n64()); }   // ((step 5) the Insert menu's row, RX_VK_N64 over it)

n64_rules::Look n64_look() {
    static const n64_rules::Env env = [] {
        n64_rules::Env e;
        e.lines = env_number("RX_VK_N64_LINES", -1);
        if (const char* v = getenv("RX_VK_N64_LOD"); v && *v) e.lod = (float)atof(v);
        e.tv = env_number("RX_VK_N64_TV", -1);
        e.mask = env_number("RX_VK_N64_MASK", -1);
        e.fps = env_number("RX_VK_N64_FPS", -1);
        return e;
    }();
    // ((step 5) Remembered's page; (step 8) the preset shown, which changes at a switch's middle)
    return n64_rules::with_env(n64_rules::look_of(n64_shown(), n64_rules::rows_of(opts.n64_rem)), env);
}

bool n64_3d_now() {
    const n64_rules::Look l = n64_look();
    if (!l.on) return false;
    const bool rgba16f = temporal_scene_format(VK_FORMAT_R16G16B16A16_SFLOAT);
    static std::atomic<bool> told{false};
    if (rgba16f && !told.exchange(true, std::memory_order_relaxed))
        logf("vk: N64 Classic: this run's scene is RGBA16F (RenoDX's HDR): its 3D pass does not draw, the game's upscale does");
    return n64_rules::three_d_runs(l, rgba16f);
}

int n64_in_front() { return n64_3d_now() ? n64_shown() : (int)n64_rules::OFF; }

bool n64_tv_now(bool native_pq) { return n64_rules::tv_draws(n64_look(), n64_anim(), native_pq, dlssg::active()); }

namespace {
// ((11-22) the TV's screen: the present's own (the presenting thread's alone), and the last one done, which the mouse goes by
// from any thread, under its lock)
struct Screen {
    bool drawn = false;
    uint32_t x = 0, y = 0, w = 0, h = 0, window_w = 0, window_h = 0;
    float curve = 0.0f, anim_x = 1.0f, anim_y = 1.0f;
};
bool screen_open = false;
Screen screen_now;
std::mutex screen_mu;
Screen screen_done;
} // namespace

void n64_screen_begin(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint32_t window_w, uint32_t window_h) {
    screen_open = true;
    screen_now = Screen{};
    screen_now.x = x, screen_now.y = y, screen_now.w = w, screen_now.h = h, screen_now.window_w = window_w, screen_now.window_h = window_h;
}

void n64_screen_drawn(float curve, float anim_x, float anim_y) {
    if (!screen_open) return;   // (a shot's window pass: no window under it)
    screen_now.drawn = true, screen_now.curve = curve, screen_now.anim_x = anim_x, screen_now.anim_y = anim_y;
}

void n64_screen_end() {
    if (!screen_open) return;
    screen_open = false;
    std::lock_guard lk(screen_mu);
    screen_done = screen_now;
}

bool n64_screen_place(uint32_t* x, uint32_t* y, uint32_t* w, uint32_t* h, uint32_t* window_w, uint32_t* window_h) {
    if (!screen_open || !screen_now.w || !screen_now.h || !screen_now.window_w || !screen_now.window_h) return false;
    *x = screen_now.x, *y = screen_now.y, *w = screen_now.w, *h = screen_now.h;
    *window_w = screen_now.window_w, *window_h = screen_now.window_h;
    return true;
}

void n64_screen_point(int* x, int* y, int win_w, int win_h) {
    Screen s;
    {
        std::lock_guard lk(screen_mu);
        s = screen_done;
    }
    if (!s.drawn || win_w <= 0 || win_h <= 0 || !s.window_w || !s.window_h) return;
    // (the cursor's pixel's middle, in the window image's pixels; back in the window's, the pixel it falls in)
    const float kx = (float)s.window_w / (float)win_w, ky = (float)s.window_h / (float)win_h;
    const n64_rules::ScreenPoint p = n64_rules::screen_point(((float)*x + 0.5f) * kx, ((float)*y + 0.5f) * ky, (float)s.x, (float)s.y,
                                                             (float)s.w, (float)s.h, s.curve, s.anim_x, s.anim_y);
    *x = (int)std::floor(p.x / kx), *y = (int)std::floor(p.y / ky);
}

} // namespace mkwvk
