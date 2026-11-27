// The Insert menu. Drawn with Dear ImGui over the window's image at the last step of a present (menu_record; vk_imgui.h, in the
// game's style: vk_ui.h), so it costs nothing while closed and it never touches the game's picture, nor what frame interpolation
// sees. The FPS counter and the start-up screen are drawn the same way. F1 always opens and closes it, Insert too by default.
// Up and Down choose, Left and Right change, Esc closes; the game gets no keyboard input while it is open.
// (hookshot) A gamepad's Home button, or Select and Start together, opens it too; the D-pad chooses and changes, the button
// the Switch's A is bound to changes too (and opens a page), the one B is bound to goes back (vk_menu_keys.h). The game gets no gamepad input while it is open either.
// Its Controls page binds the Switch's buttons to gamepad inputs and keys.
// (hookshot) The mouse is free while it is open (the window lets it go: WM_APP + 8, host/display.c and
// host/posix/display_sdl.c): the row under the cursor is selected, a click on a tab shows it, on a value's left or right
// half changes it down or up, on a toggle flips it, on a slider's track sets it (or drag it); the wheel scrolls the rows
// (never a value, wherever the cursor is); a right click is Esc. On the Cheats page and its lists a click is Enter (on a
// choice's or an amount's left or right half, Left or Right) and a right click goes back. The drawing records each control's
// place and the mouse is tested against that (vk_menu_hit.h).
// (hookshot) The rows that take a restart (Row::restart) are tagged "After restart" while their value is not the one the game
// started with, and the Graphics tab's help lists them. Closing the menu then asks whether to restart now (menu_restart.h):
// Later keeps the saved settings for the next start and is not asked again until they change; Restart now saves and
// closes the window as the player would, and the game starts again (WM_APP + 9: host/hos_relaunch.c).
// (Triforce, 11-10) The menu is drawn as the game's own Options screen (SystemOption_00 of its layout archive): the System
// screens' header with the options' categories across it as the pause menu has its own (Display, Graphics, Audio, Controls,
// System; L and R, Q and E), the rows on the game's plates in its list column, the caption plate at the right, the guides at
// the foot, in the game's fonts and with its button icons (vk_ui.h, vk_game_tex.h, vk_imgui.cpp: all read from the player's
// game files at run time). The Debug tab is always shown (11-15, the owner: "make debug on by default and remove the alt+g
// shortcut"; Alt+G unlocked it before). The Menu size row is gone: the game's menus have one size. The FPS counter is a HUD counter (the
// HUD's own digits, no plate). tests/ui_preview.cpp draws all of it into pictures without the game.
// (Triforce, options_version 7, the owner: "group them correctly, such as HDR should be its own group, the upscaling should be
// its own group ... Add the in-game filigree to group them" and "multiple settings that do multiple things and they contradict
// each other ... If a setting can be implemented in some other way, then remove the setting entirely") Each tab's rows come in
// groups, each under a heading drawn as the game's list separator with the group's title (MENU_HEADING, ui::heading); a row
// that does nothing with the others as they are is not shown (row_shown). The rows that chose one thing twice are one row each
// (merged_rows.h: HDR with RenoDX, Frame generation with DLSS's, Frame pacing with Steady, Low latency for Reflex or Anti-Lag
// 2, the Upscaler's native AA as the Render resolution's Native (100%)), and the Quality preset, the Window scaling filter,
// the Reflex frame limit, the Handheld profile and the shared Stick dead zone are gone, their jobs done otherwise.
#include <atomic>
#include <chrono>
#include <cmath>
#include <utility>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <mutex>
#include <string>
#include <thread>   // ((Triforce) the name pages' read of the game's files)
#include <vector>

#include "vk_dlssg.h"
#include "cpu_count.h"   // ((Triforce, 11-22, OS-49) the threads to size by: HOS_SIM_CPU
#include "vk_pace.h"      // (Triforce: who holds the frames, for the rows that hand them to another limiter)
#include "vk_bugshot.h"   // (Triforce: a bug capture's picture, taken before the overlays are drawn)
#include "vk_paths.h"
#include "vk_menu.h"
#include "vk_menu_hit.h"
#include "vk_draw.h"   // (pipeline_cache_save: Restart now keeps what was built)
#include "oot_cheat_items.h"
#include "debug_names.h"   // ((Triforce) the Debug tab's name pages: their lists, and oot_debug_link.h's lines)
#include "debug_pending.h"      // ((Triforce) the Inventory's change waiting for the game)
#include "vk_progress.h"   // (StartupView, version_text: the start-up screen)
#if __has_include("vk_startup_draw.h")   // (the shader-screen branch's file: with it the start-up screen is its drawing)
#include "vk_startup_draw.h"   // (the start-up screen's drawing: draw_startup_screen)
#endif
#include "vk_ui.h"
#include "vk_menu_keys.h"   // (which gamepad buttons confirm and go back: those A and B are bound to)         // (how it looks: Dear ImGui, vk_imgui.h)
#include "vk_dlss.h"
#include "vk_fsr3.h"      // (the Upscaler row: whether AMD FSR 3.1 runs on this GPU)
#include "vk_fsr3fi.h"    // (the Frame generation row: whether FSR 3.1 makes the frame)
#include "vk_framegen.h"   // ((Triforce) 11-24: framegen_maker, who made the last frames: perf_framegen_text)
#include "vk_fsr4.h"
#include "vk_xess.h"   // ((Triforce) the Upscaler row: whether Intel XeSS runs here)
#include "vk_temporal.h"
#include "vk_fsr3_inputs.h"   // (Triforce: the render size while AMD FSR 3.1 draws, for the performance overlay)
#include "perf_stats.h"       // (Triforce: the performance overlay's frame times)
#include "perf_machine.h"     // (Triforce: and the machine's numbers, sampled on a thread of their own)
#include "vk_renodx.h"    // (renodx_built: the RenoDX rows only in a build with its shaders)
#include "vk_reflex.h"
#include "vk_antilag.h"
#include "upscaler_rows.h"
#include "output_modes.h"   // ((Triforce) the Output resolution's display modes and common sizes: mode_sizes
#include "fps_levels.h"   // ((Triforce) the FPS counter row's levels between On and Full: draw_fps, fps_detail_sample
#include "auto_settings.h"   // ((Triforce) the Graphics tab's Auto (this PC) row: auto_apply, menu_auto_tune
#ifndef _WIN32
#include <unistd.h>   // ((Triforce) sysconf: the RAM, Auto (this PC)'s auto_hardware)
#endif
#include "first_start.h"   // ((Triforce, 11-22, PRESENT-46) the Render resolution of a first start on a weak card: menu_first_start)
#include "vk_present_rect.h"   // ((Triforce, options_version 7) where the picture goes in the window: the filter it takes)
#include "text_spread.h"   // ((Triforce, 11-19) the title entry's shadow and glow as the game's entries'
#include "game_grid.h"   // ((Triforce, 11-19) where the game's layouts are in the window: the Mods entry on its list)
#include "merged_rows.h"   // ((Triforce, options_version 7) the rows that each choose two saved values, and the older files' migration)
#include "aa_rows.h"        // (Triforce, the Anti-aliasing row: its choices, and when it does not apply)
#include "vk_aa.h"          // (...RX_VK_AA over it, and whether the game's pass was there to replace)
#include "vk_n64.h"         // ((Triforce, N64 Classic, step 4) its TV in the window filter's place)
#include "evil_hd.h"         // ((Triforce, 11-23) the Evil HD row: what it puts over the rows below it)
#include "tex_detail.h"     // (the Texture detail row: the levels' names, RX_VK_TEX_DETAIL)
#include "fps_cap.h"        // (the Game frame rate cap row's Monitor's rate)
#include "ultrawide_rows.h" // ((Triforce) the Ultrawide row's shapes, and its old Monitor's shape read before options_version 6)
#include "output_sizes.h"   // ((Triforce) the Output resolution row's sizes: the fixed ones, Screen and Custom)
#include "present_mode.h"   // (the VSync row: what its choice comes to on this driver)
#include "game_language.h"  // (the Game language row: what language.txt chooses and offers)
#include "vk_xr.h"          // ((Triforce VR) vk_xr_cfg)
#include "vk_menu_i18n.h"   // ((Triforce) the menu's languages: the Menu language row, the texts looked up (vk_ui.h))
#include "menu_restart.h"
#include "mod_cheat_rows.h"   // (Triforce: the System tab's rows for the cheats of the mods' cheat files)
#include "achievement_rows.h"   // (Triforce: the achievements the host names, their notice and their page)
#include "save_file_rows.h"     // (Triforce: the save files the host names, and the title's file select)
#include "menu_sound_events.h"   // (Triforce: the options' own sounds: which one a tick asks for, and their queue to the host)
#include "mods_entry_anim.h"     // ((Triforce, 11-19) the Mods entry under the title's list: the game's entries' animations)
#include "focus_anim.h"          // ((Triforce, 11-19) Mods and Quit under the System list, Quit's dialog: the game's buttons' and dialogs')
#include "mods_page_anim.h"      // ((Triforce, 11-20) the Mods screen as it opens: its In)
#include "vk_mods.h"   // (Triforce: the Mods page's engine, GameBanana's list and the installs)
#include "vk_salesman.h"   // (Triforce: the Happy Mask Salesman beside the cards)
#include "imgui_internal.h"   // (RegisterUserTexture: the mods' pictures)
#include "ini_merge.h"   // ((Triforce, handoff §9) the options file's lines merged by key with a change made outside the game)
#include "file_whole.h"  // (and the file written whole: file_writers::write_whole)
#include "reshade_menu.h"   // ((Triforce) 11-24: the Graphics tab's Post-processing group, the ReShade preset's rows and comparison)
#include "sim_turf.h"   // ((Triforce) the Simulated turf page: its rows' values, the area, its file)
#include "vk_work.h"   // (after the others: counts the commands that do GPU work, for full_barrier)
#ifndef HOOKSHOT_VERSION   // (nx2/build.py gives it to this file: nx2/version.py)
#define HOOKSHOT_VERSION "unknown"
#endif

namespace mkwvk {
HWND app_window();
int texture_detail_auto();   // (vk_texture.cpp: what the video memory gives this card, -1 before the first texture)
int display_refresh_mhz();   // (vk_main.cpp: the window's display, mHz; 0 when not known)
int swapchain_present_mode();   // (vk_main.cpp: the swapchain's present mode, present_mode.h's numbers; -1 none)
// ((Triforce) the performance overlay on Full: the rendering GPU's LUID (vk_main.cpp), the GPU's time in the recordings and their
// uploads so far (vk_replay.cpp), the textures uploaded so far (vk_texture.cpp), whether frame generation makes frames now
// (vk_framegen.cpp))
bool gpu_device_luid(uint8_t out[8]);
int64_t gpu_time_busy_ns();
void texture_stats(int64_t* uploads, int64_t* astc_gpu, int64_t* bytes_uploaded);
bool framegen_on();

Options opts;

namespace {

// (Triforce) The tabs across the Options screen's header, as the pause menu's categories: a kind of option each. Debug is the
// last, always shown (debug_shown)
enum MenuTab {
    TAB_DISPLAY = 0,
    TAB_GRAPHICS = 1,
    TAB_AUDIO = 2,
    TAB_CONTROLS = 3,
    TAB_SYSTEM = 4,
    TAB_DEBUG = 5,   // (the OoT debug tools of #785 and the developer's rows, a tab of their own)
    TAB_COUNT = 6,
    TAB_MOTION = TAB_COUNT,   // (hookshot: not a tab of the strip, the Motion page that the Controls tab's Motion row
                              // opens: one past the strip's tabs, so a tab added before TAB_COUNT moves it along)
    TAB_VRPAGE = TAB_MOTION + 1,   // ((Triforce VR) the VR Controls page that the Controls tab's VR Controls row opens)
    TAB_3DPAGE = TAB_VRPAGE + 1,   // ((Triforce VR) the 3D Settings page (Display's 3D Style)
    TAB_VRSET = TAB_3DPAGE + 1,    // ((Triforce VR) the VR Settings page (Display's 3D Style)
    TAB_PAGE = TAB_VRSET + 1,   // (hookshot: the Controls page's rows, above its grid; no tab shows them)
    TAB_N64 = TAB_PAGE + 1,      // ((Triforce, 11-22, N64 Classic, step 5) the Remembered page that the Graphics tab's
                                 // Remembered settings row opens: no tab shows it)
    TAB_SIM_TURF = TAB_N64 + 1,   // ((Triforce, 11-24) the Simulated turf page that the Graphics tab's Simulated turf row opens:
                                  // no tab shows it. Its values are each area's, in sim_turf_settings.ini, read after the options
                                  // file: the options file's lines of its rows are the last ones shown, read by nothing)
    TAB_HIDDEN = TAB_SIM_TURF + 1    // ((Triforce, options_version 7) saved values a merged row stands for: never shown, merged_rows.h)
};

struct Row {
    MenuTab tab;
    const char* name;
    int* value;
    int lo, hi, step;
    const char* (*text)(int v);
    const char* help;   // (shown under the list while the row is selected: what the row is, the same whatever its value)
    // (a line about the value chosen, under the help, or nullptr: hint(v, -1) is the one to show now for v, hint(v, 0),
    // hint(v, 1), ... every one v can have (those that depend on the other rows or on the GPU), until nullptr, so the
    // menu keeps the height of the tallest: measure_help)
    const char* (*hint)(int v, int variant) = nullptr;
    bool restart = false;   // (read once, at the start: a change applies after a restart)
    // (a change here left the Quality preset alone: the controls, the window, the counter, frame generation. (Triforce,
    // options_version 7) The preset is gone and nothing reads it; the rows keep their shape)
    bool preset_exempt = false;
    signed char cheat = -1;   // (a debug tool, on the Debug tab with the tools on: its index in the cheat_ tables, -1 none)
    bool heading = false;     // (a section's title on its tab, not a row: the selection steps over it)
    const char* key = nullptr;   // ((Triforce VR) the options file's key, where it is not the name's (ini_key))
};
/// A row's hints from a table, the value lo first (nullptr: none for that value)
const char* hint_in(const char* const* t, int n, int lo, int v, int variant) {
    return variant <= 0 && v - lo >= 0 && v - lo < n ? t[v - lo] : nullptr;
}
#define MENU_HINTS(fn, lo, ...)                                                                                              \
    const char* fn(int v, int variant) {                                                                                     \
        static const char* const t[] = {__VA_ARGS__};                                                                        \
        return hint_in(t, (int)(sizeof t / sizeof t[0]), lo, v, variant);                                                    \
    }
const char* tx_framegen(int v) {
    // (Triforce: the last is AMD's frame generation library, vk_fsr4.h fsr4fg. A saved AMD FSR 4 on a PC where the library
    // cannot make the frames shows what runs there, 2x: framegen_rows.h shown. (FG-1) Named by the version AMD's library makes
    // the frames with: "AMD FSR (3.1.6)" on an RX 6000 or 7000, "AMD FSR (4.0.2)" on an RX 9000)
    static const char* t[] = {"Off", "Auto", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "AMD FSR"};
    const int shown = std::clamp(framegen_rows::shown(v, fsr4fg::offered_known()), 0, (int)framegen_rows::kRowMax);   // ((Triforce) as known: menu_ahead)
    if (shown != framegen_rows::FSR4) return t[shown];
    static char label[32];
    return framegen_rows::row_label(label, sizeof label, fsr4fg::version());
}
const char* tx_onoff(int v) { return v ? "On" : "Off"; }
// (Triforce VR) the VR tab's values
const char* tx_vr_view(int v) { return v ? "Immersive" : "Theater"; }
const char* tx_normal_inverted(int v) { return v ? "Inverted" : "Normal"; }
const char* tx_vr_turn(int v) { return v ? "Snap" : "Smooth"; }
const char* tx_tenths(int v) {   // ((Triforce VR) tenths as a decimal: 10 is "1.0"
    static thread_local char b[16];
    snprintf(b, sizeof b, "%d.%d", v / 10, v % 10);
    return b;
}
const char* tx_vr_mode(int v) { return v >= 2 ? "Full Dive" : v ? "Immersive" : "Theater"; }
const char* tx_view3d(int v) {   // ((Triforce VR) each flat screen 3D style followed by VR with it on the desktop: Mode = style * 2 + VR
    static const char* const t[] = {"Flatscreen", "VR", "Red/cyan glasses", "VR + Red/cyan glasses", "Side by side (3D TV)",
                                    "VR + Side by side (3D TV)", "Crossed eyes", "VR + Crossed eyes", "Above and below",
                                    "VR + Above and below", "Side by side (Cardboard)", "VR + Side by side (Cardboard)"};
    return t[v >= 0 && v < 12 ? v : 0];
}
const char* tx_vr_camera(int v) { return v ? "Third person" : "First person"; }
const char* tx_vr_cutscenes(int v) { return v ? "First person" : "Classic"; }
const char* tx_resolution(int v);
const char* tx_vr_resolution(int v) { return v <= 0 ? "As in Graphics" : tx_resolution(v); }
const char* tx_flat3d(int v) {
    static const char* const t[] = {"Off", "Red/cyan glasses", "Side by side (3D TV)", "Crossed eyes", "Above and below", "Side by side (Cardboard)"};
    return t[v >= 0 && v < 6 ? v : 0];
}
const char* tx_flat3d_screen(int v) {
    static char b[24];
    if (v <= 0) return "Auto (nearest thing)";
    snprintf(b, sizeof b, "%d cm", v);
    return b;
}
const char* tx_vr_stereo(int v) { return v == 2 ? "Accurate" : v == 1 ? "Balanced" : "Performant"; }
const char* tx_vr_body(int v) { return v ? "Shown" : "Hidden"; }
const char* tx_vr_scheme(int v) { return v ? "Simplified" : "Full Gesture"; }
const char* tx_unit(int v, const char* fmt) {
    static char b[24];
    snprintf(b, sizeof b, fmt, v);
    return b;
}
const char* tx_degrees(int v) { return tx_unit(v, "%d degrees"); }
const char* tx_cm(int v) { return tx_unit(v, "%d cm"); }
const char* tx_cm_signed(int v) { return tx_unit(v, "%+d cm"); }
const char* tx_cm_s(int v) { return tx_unit(v, "%d cm/s"); }
const char* tx_dlssg(int v) { return v == 1 ? "2x" : v == 2 ? "3x" : v == 3 ? "4x" : "Off"; }
/// (what runs in this session, or why not: vk_dlssg.cpp. Variant 0 stands for the longest line, for the menu's height)
const char* hn_dlssg(int v, int variant) {
    if (variant > 0) return nullptr;
    if (variant == 0) return "Not on this graphics card or driver: it needs an RTX 40 or 50 card.";
    if (!v) return "Off.";
    return mkwvk::dlssg::asked() ? mkwvk::dlssg::status() : "Starts with the next start of the game.";
}
const char* tx_menu_shortcut(int v) {
    // (F1 is never turned off: the menu is always one key away. Esc as well, as a PC game's pause menu)
    // (and a DualShock 4's or DualSense's touchpad click, as F1)
    static const char* const names[] = {"Insert or F1", "F1 only", "Insert, F1 or Esc", "Insert, F1 or touchpad",
                                        "Insert, F1, Esc or touchpad"};
    return names[std::clamp(v, 0, 4)];
}
const char* tx_hdr(int v) { return v == 1 ? "Expanded" : v == 2 ? "Native" : "Off"; }   // ((Triforce, 11-16) "Native", the owner's word)
namespace mr7 = merged_rows;
/// ((Triforce, options_version 7) the HDR row: opts.hdr with RenoDX HDR as its fourth value, merged_rows.h)
const char* tx_hdr_mode(int v) { return v == mr7::HDR_RENODX ? "Native + RenoDX" : tx_hdr(v); }
/// The row's value in words; and with HDR on while the swapchain stayed SDR, why instead (dev.hdr_sdr_why, vk_main.cpp
/// create_swapchain): the player is told what to change, not sent to a setting that is already right. Variants: the
/// value's own line, then each reason
const char* hn_hdr_mode(int v, int variant) {
    static const char* const t[] = {
        "The usual SDR picture.",
        "The game's SDR picture shown on an HDR display: its white at Paper white, its highlights up to Peak brightness.",
        "The game's own HDR, told your display's Paper white and Peak brightness.",
        ("The game's own HDR with RenoDX's tone mapping, eye adaptation and color grading in place of the game's (the RenoDX "
         "rows below). RenoDX is by Carlos Lopez (clshortfuse), under the MIT license.")};
    static const char* const why[] = {
        "The picture stays SDR: the graphics driver offers no HDR output (no VK_EXT_swapchain_colorspace).",
        "The picture stays SDR: HDR is off for this display in Windows' display settings.",
        ("The picture stays SDR: Windows has HDR on, but the graphics driver offers the game no HDR output. Reinstall the "
         "driver with a clean install, then restart the PC."),
        "The picture stays SDR: the display offers no HDR output. Is HDR on in the display settings?"};
    const int reasons = hdr_sdr_count - 1;   // (every HdrSdrWhy but hdr_sdr_none)
    static_assert(sizeof why / sizeof *why == hdr_sdr_count - 1, "hn_hdr_mode: a line for each HdrSdrWhy but hdr_sdr_none");
    if (v < 0 || v >= (int)(sizeof t / sizeof *t)) return nullptr;
    if (variant < 0)   // (the one to show now. The swapchain is made again when the row changes, so the reason is this value's)
        return v && opts.hdr && !dev.hdr && dev.hdr_sdr_why != hdr_sdr_none ? why[std::clamp((int)dev.hdr_sdr_why, 1, reasons) - 1] : t[v];
    if (variant == 0) return t[v];
    return v && variant <= reasons ? why[variant - 1] : nullptr;
}
const char* tx_nits(int v) {
    static char b[24];
    snprintf(b, sizeof b, "%d nits", v);
    return b;
}
static_assert(fps_cap::kMonitor == 6, "the Game frame rate cap row's last value is Monitor's rate");
const char* tx_fps_cap(int v) {
    static const char* const t[] = {"60 (the console's)", "90", "120", "144", "165", "240"};
    if (v < 0) return v == -1 ? "45" : v == -2 ? "40" : "30";   // (Triforce: the limits under 60, host/nn_vi.c fps_max)
    if (v >= fps_cap::kUncapped) return "Uncapped";   // ((Triforce) as fast as the PC can, at real time: host/nn_vi.c fps_cap_of)
    if (v >= fps_cap::kMonitor) {   // (Triforce: Monitor's rate, with what this display gives now: fps_cap.h, as the host asks it)
        static char b[32];
        const int cap = fps_cap::of_display(display_refresh_mhz());
        if (!cap) return "Monitor's rate";
        snprintf(b, sizeof b, "Monitor's rate (%d)", cap);
        return b;
    }
    return t[v];
}
// (Triforce) The Steady frame rate row (host/pace_steady.h's PACE_STEADY_*)
const char* tx_steady_fps(int v) { return v == 1 ? "Any rate" : v == 2 ? "Refresh steps" : "Off"; }
/// ((Triforce, options_version 7) the Frame pacing row: Frame pacing and Steady frame rate in one, merged_rows.h)
const char* tx_pacing(int v) {
    static const char* const t[] = {"Off", "Even", "Steady, any rate", "Steady, refresh steps"};
    return t[std::clamp(v, 0, 3)];
}
MENU_HINTS(hn_pacing, 0, "Each frame as soon as it is ready.", "Frames at an even interval: less stutter, at up to a frame of delay.",
           "The game paced to a rate this PC holds here, under the Frame rate cap, each frame shown evenly: for a display with "
           "G-SYNC or FreeSync, or VSync off. Applies after a restart.",
           "As Steady, any rate, kept to whole divisions of the refresh rate (at 240 Hz: 120, 80, 60): for VSync without G-SYNC or "
           "FreeSync. Applies after a restart.")
// (Triforce) The VSync row (opts.vsync; present_mode.h has what On and Off ask for): the line under its help says what the
// choice came to on this driver, by the present mode of the swapchain there is, or which switch decides for the run.
// Variants (every one): each mode the value can come to, then the two switches
/// ((Triforce) 11-24) its third value, Every refresh: FIFO, as RX_VK_FIFO (vk_main.cpp create_swapchain)
const char* tx_vsync(int v) { return v == 2 ? "Every refresh" : tx_onoff(v); }
const char* hn_vsync(int v, int variant) {
    static const char* const on[] = {
        "Each frame waits for the screen's next refresh: no tearing.",
        "The newest finished frame at each refresh of the screen: no tearing, and nothing held back.",
        "This driver has no tear-free mode that does not hold the frame rate down: frames are shown at once, as with Off.",
    };
    static const char* const off[] = {
        "This graphics driver cannot show frames at once here: as On.",
        "This graphics driver cannot show frames at once here: as On.",
        "Each frame is shown the moment it is ready: a little less delay, and the picture can tear.",
    };
    static const char* const fifo_env = "Set for this run by RX_VK_FIFO: each frame waits for the screen's next refresh.";
    static const char* const immediate_env = "RX_VK_IMMEDIATE asks for frames shown at once in this run, whatever is chosen here.";
    static const char* const every = "Each frame waits for the screen's next refresh (FIFO): no tearing, at most the screen's rate, "
                                     "and a frame late for one refresh waits for the next.";
    if (variant < 0) {
        static const bool fifo = getenv("RX_VK_FIFO") != nullptr, immediate = getenv("RX_VK_IMMEDIATE") != nullptr;
        if (fifo || immediate) return fifo ? fifo_env : immediate_env;
        if (v == 2) return every;
        const int mode = swapchain_present_mode();
        if (mode < present_mode::kFifo || mode > present_mode::kImmediate) return nullptr;   // (no swapchain: nothing to say)
        return (v ? on : off)[mode];
    }
    if (variant <= present_mode::kImmediate) return (v ? on : off)[variant];
    return variant == 3 ? fifo_env : variant == 4 ? immediate_env : variant == 5 ? every : nullptr;
}
// (hookshot) Motion controls: the choice, and whether a connected controller has a gyroscope (host/pad_sdl.c). Either can be
// chosen whatever is connected: a pad plugged in later is read when it comes
const char* tx_gyro(int v) {
    const int status = host && host->gyro_status ? host->gyro_status() : -1;
    if (status == 2) return v ? "On (gyro found)" : "Off (gyro found)";
    if (status == 1) return v ? "On (no gyro on this pad)" : "Off (no gyro on this pad)";
    if (status == 0) return v ? "On (no controller)" : "Off (no controller)";
    return v ? "On" : "Off";
}
const char* tx_mousecam(int v) { return v == 2 ? "Off" : v ? "Native" : "As the stick"; }   // ((Triforce) 2: Off)
const char* tx_sens(int v) {
    static char b[12];
    snprintf(b, sizeof b, "%.2f", v / 100.0);
    return b;
}
// (the game's picture and the window it is shown in, as the last present had them: menu_note_present_sizes. (Triforce,
// options_version 7) The Window scaling filter row is gone: those sizes choose the filter there, upscaler_rows.h auto_filter)
std::atomic<uint64_t> present_sizes{0};
// ((Triforce, options_version 7) The Low latency row: NVIDIA Reflex on an NVIDIA card, AMD Anti-Lag 2 on an AMD one, one row
// for either (merged_rows.h); none where neither runs. With DLSS frame generation Reflex is Streamline's)
mr7::Vendor latency_vendor() {
    return reflex_available() || mkwvk::dlssg::reflex_on() ? mr7::LATENCY_NVIDIA : antilag_available() ? mr7::LATENCY_AMD : mr7::LATENCY_NONE;
}
const char* tx_latency(int v) {
    static const char* t[] = {"Off", "On", "On + Boost"};
    // ((Triforce, 11-16: the owner saw Off and "not available" with DLSS frame generation on an NVIDIA card) With DLSS frame
    // generation Reflex is Streamline's and always on (vk_dlssg.cpp reflex_apply): its Off shows On, Boost as chosen
    if (mkwvk::dlssg::reflex_on()) return t[std::clamp(v, 1, 2)];
    return t[std::clamp(v, 0, mr7::latency_hi(latency_vendor()))];
}
/// Low latency: the value with NVIDIA Reflex (variants 0 to 2: each value's line), with AMD Anti-Lag 2 (3), or that Reflex runs
/// through Streamline with DLSS frame generation (4)
const char* hn_latency(int v, int variant) {
    static const char* const nv[] = {"Off.", "NVIDIA Reflex: each frame starts as late as it can, for less input delay.",
                                     "As On, and the graphics card's clocks are kept up as well."};
    static const char* const amd[] = {"Off.", "AMD Anti-Lag 2: each frame starts as late as it can, for less input delay. Not "
                                              "used with frame generation."};
    static const char* const sl = "With DLSS frame generation Reflex runs through NVIDIA Streamline and stays on, as frame "
                                  "generation needs it. On + Boost keeps the graphics card's clocks up as well.";
    if (variant < 0) {
        if (mkwvk::dlssg::reflex_on()) return sl;
        return latency_vendor() == mr7::LATENCY_AMD ? amd[std::clamp(v, 0, 1)] : nv[std::clamp(v, 0, 2)];
    }
    return variant == 0 ? nv[std::clamp(v, 0, 2)] : variant == 1 ? amd[std::clamp(v, 0, 1)] : variant == 2 ? sl : nullptr;
}
// The Upscaler (opts.dlss): what scales the 3D up to the output. DLSS and DLAA only where dlss_why() lets them run, FSR 3.1
// only where vk_fsr3.cpp says it does, FSR 4 and its native AA only where fsr4_why() does; the menu shows (and steps from)
// what runs, and keeps the saved choice for a PC where it can
namespace ur = upscaler_rows;
/// One bit per upscaler that runs here (upscaler_rows.h bit). Each backend caches its own answer, so this costs nothing
unsigned upscalers_available() {
    // ((Triforce) 11-24: Off, no upscaler, everywhere)
    return ur::bit(ur::GAME) | ur::bit(ur::OFF) | ur::dlss_bits(dlss_why() == DLSS_OK) | ur::fsr3_bits(fsr3::supported()) |
           ur::fsr4_bits(fsr4_why() == FSR_OK) | ur::xess_bits(xess_why() == XESS_OK);   // ((Triforce) Intel XeSS where it runs)
}
/// (FSR 3.1 has inputs of its own, at the Render resolution's mode or as its Native AA; DLSS and FSR 4 run on the frame
/// chain they share, temporal_mode)
int upscaler() {
    if (fsr3_wanted()) return fsr3_native() ? ur::FSR3_AA : ur::FSR3;
    const int t = temporal_mode();
    return t == ur::GAME && opts.dlss == ur::OFF ? (int)ur::OFF : t;   // ((Triforce) 11-24: Off, no engine: upscale_off_wanted)
}
/// ((Triforce, options_version 7) the engine alone: an engine's native AA is the Render resolution row's Native (100%))
const char* tx_upscaler(int) {
    if (n64_in_front() != n64_rules::OFF) return "N64 Classic";   // ((Triforce, N64 Classic) its 3D pass draws in their place)
    static const char* t[ur::kUpscalers] = {"Game", "NVIDIA DLSS", "NVIDIA DLSS", "AMD FSR 3.1", "AMD FSR 4", "AMD FSR 4",
                                            "AMD FSR 3.1", "Off", "Intel XeSS", "Intel XeSS"};
    // ((Triforce, FSR4-7) FSR 4 by the version AMD's library runs here, "AMD FSR 4.1", once it has been asked. up is the
    // engine (ur::engine), so FSR 4's Native AA reads as its engine too, "AMD FSR 4.1": the Render resolution says Native)
    const int up = ur::engine(std::clamp(upscaler(), 0, ur::kUpscalers - 1));
    if (ur::is_fsr4(up)) return fsr4_name(up == ur::FSR4_AA);
    return t[up];
}
/// The Upscaler: the one shown (what runs, upscaler()), and with the game's own, why DLSS and FSR are not offered. Variants
/// (every one): each value, then the game's own with each of DLSS's reasons, then with each of FSR's
const char* hn_upscaler(int v, int variant) {
    static const char* const t[ur::kUpscalers] = {
        // ((Triforce, options_version 7) one line per engine: an engine's native AA is the Render resolution's Native (100%),
        // whose own line says so, and its value reads as its engine here (v = ur::engine(v) below). (S7) DLSS's line, DLAA's
        // too, names AMD's RCAS before the HUD; (FSR3-03) FSR 3.1 gives what moves by itself its own motion: no trails said)
        "The game's own upscaler.",
        "NVIDIA's, on RTX graphics cards. Sharpness sharpens its 3D before the HUD, with AMD's RCAS. Things that move by "
        "themselves can trail for now.",
        nullptr,
        "AMD's, on any graphics card, built from AMD's own shaders.",
        "AMD's machine-learned upscaler, with AMD's files beside the game. Things that move by themselves can trail for now.",
        nullptr,
        nullptr,
        // ((Triforce) 11-24)
        "No upscaler, not even the game's network: the 3D stretched to the output with a plain filter. The fastest, and the "
        "roughest picture: softer below 100%.",
        // ((Triforce) Intel XeSS, its Native AA the Render resolution's Native (100%) as the others')
        "Intel's machine-learned upscaler, with Intel's libxess.dll beside the game. Sharpness sharpens its 3D before the HUD, "
        "with AMD's RCAS. Things that move by themselves can trail for now.",
        nullptr,
    };
    static const char* const dlss_no[DLSS_WHY_COUNT] = {
        nullptr,
        "DLSS and DLAA: not in this build (built without NVIDIA's DLSS SDK, see the readme).",
        "DLSS and DLAA: off for this run (RX_VK_DLSS=0).",
        "DLSS and DLAA: need an NVIDIA RTX GPU.",
        "DLSS and DLAA: need a newer NVIDIA driver.",
        "DLSS and DLAA: DLSS's runtime was not found (the game folder's ngx folder, see the readme).",
        "DLSS and DLAA: NVIDIA's NGX on Linux loads DLSS's runtime only from a folder named in ASCII (see the readme).",
        "DLSS and DLAA: NVIDIA's NGX started but gave DLSS nothing to work with (see the log).",
    };
    static const char* const fsr_no[FSR_WHY_COUNT] = {
        nullptr,
        "AMD FSR 4: not in this build (see the readme).",
        "AMD FSR 4: off for this run (RX_VK_FSR4=0).",
        "AMD FSR 4: AMD's files were not found beside the game (see the readme).",
        "AMD FSR 4: AMD's files have no FSR 4 for this GPU and driver: it needs a Radeon RX 6000, 7000 or 9000 and AMD's "
        "driver 26.10.1 or newer.",
    };
    // ((Triforce) why Intel XeSS is not offered (vk_xess.h XessWhy). Its library missing is said on an Intel GPU alone: on
    // another, the line would be on every PC without Intel's file)
    static const char* const xess_no[XESS_WHY_COUNT] = {
        nullptr,
        "Intel XeSS: Windows only (Intel makes no XeSS library for Linux).",
        "Intel XeSS: off for this run (RX_VK_XESS=0).",
        "Intel XeSS: Intel's libxess.dll was not found beside the game (see the readme).",
        "Intel XeSS: the GPU or its Vulkan driver lacks what XeSS needs (the log says what).",
        "Intel XeSS: Intel's library does not run on this GPU or driver.",
    };
    // ((Triforce, FSR4-1) the engine chosen, off after failing again and again: the game's own stands in for it. FSR 4 by the
    // version AMD's library ran, as the Upscaler row names it (fsr4_name: "AMD FSR 4.1"; "AMD FSR 4" until it was asked).
    // (The reasons above are for an FSR 4 that does not run here, whose version no library has given: its plain name)
    static char fsr4_stood_in[160];
    snprintf(fsr4_stood_in, sizeof fsr4_stood_in, "The game's own stands in: %s failed four times in a row (the log says "
             "why). Set the Upscaler again to try it anew.", fsr4_name(false));
    const char* const stood_in[3] = {
        "The game's own stands in: NVIDIA DLSS failed four times in a row (the log says why). Set the Upscaler again to try "
        "it anew.",
        fsr4_stood_in,
        "The game's own stands in: Intel XeSS failed four times in a row (the log says why). Set the Upscaler again to try "
        "it anew.",
    };
    // (now: the value shown and what runs here, with every engine's reasons; every one: as said above, then ((Triforce)
    // XeSS's reasons and its stand-in line after them)
    int d = 0, f = 0, x = 0;
    constexpr int kXessAt = DLSS_WHY_COUNT + FSR_WHY_COUNT + 1;   // (the first of XeSS's variants)
    if (variant < 0) {
        v = std::clamp(upscaler(), 0, ur::kUpscalers - 1), d = (int)dlss_why(), f = (int)fsr4_why(), x = (int)xess_why();
        if (x == XESS_NO_LIBRARY && dev.props.vendorID != 0x8086) x = 0;   // (Intel's file named on Intel's GPUs alone)
        if (const int in = temporal_stood_in(); v == ur::GAME && in != ur::GAME)
            return stood_in[ur::is_xess(in) ? 2 : ur::is_fsr4(in) ? 1 : 0];
    } else if (v == ur::GAME) {
        if (variant < DLSS_WHY_COUNT) d = variant;
        else if (variant < DLSS_WHY_COUNT + FSR_WHY_COUNT - 1) f = variant - DLSS_WHY_COUNT + 1;
        else if (variant < DLSS_WHY_COUNT + FSR_WHY_COUNT + 1) return stood_in[variant - (DLSS_WHY_COUNT + FSR_WHY_COUNT - 1)];
        else if (variant < kXessAt + XESS_WHY_COUNT - 1) x = variant - kXessAt + 1;
        else if (variant == kXessAt + XESS_WHY_COUNT - 1) return stood_in[2];
        else return nullptr;
    } else if (variant > 0) {
        return nullptr;
    }
    v = ur::engine(v);   // ((Triforce, options_version 7) a native AA is its engine's: the Render resolution says Native)
    // (the reasons are said only where the engine is in the build: one without FSR does not tell an NVIDIA user why)
    const char* dn = dlss_built() || variant >= 0 ? dlss_no[d] : nullptr;
    const char* fn = fsr4_built() || variant >= 0 ? fsr_no[f] : nullptr;
    const char* xn = xess_built() || variant >= 0 ? xess_no[x] : nullptr;   // ((Triforce) a Linux build says nothing of XeSS)
    if (v != ur::GAME || (!dn && !fn && !xn)) return t[v];
    static char b[DLSS_WHY_COUNT][FSR_WHY_COUNT][XESS_WHY_COUNT][400];
    snprintf(b[d][f][x], sizeof b[d][f][x], "%s%s%s%s%s%s%s", t[0], dn ? " " : "", dn ? dn : "", fn ? " " : "", fn ? fn : "",
             xn ? " " : "", xn ? xn : "");
    return b[d][f][x];
}
/// The DLSS model row (opts.dlss_model): NVIDIA's network by its preset, or RX_VK_DLSS_PRESET's for this run
const char* dlss_preset_env() {
    static const char* const e = getenv("RX_VK_DLSS_PRESET");
    return ur::preset_env(e) ? e : nullptr;
}
const char* tx_dlss_model(int v) {
    static const char* const t[] = {"Transformer (K)", "Transformer 2 (M)", "Transformer 2 (L)", "NVIDIA default"};
    if (const char* e = dlss_preset_env()) {
        static char b[48];
        const unsigned p = ur::dlss_preset(v, e);
        if (p) snprintf(b, sizeof b, "Preset %c (RX_VK_DLSS_PRESET)", ur::preset_letter(p));
        else snprintf(b, sizeof b, "NVIDIA default (RX_VK_DLSS_PRESET)");
        return b;
    }
    // ((Triforce, 11-22, the performance audit's PRESENT-36, after Source A's) with RX_VK_DLSS_CNN_VRAM=1 the K row on a card
    // under 7 GB draws with NVIDIA's CNN model, preset E, and says so: what DLSS asks for, vk_dlss.cpp wanted_preset)
    if (ur::cnn_for_vram(v, dlss_cnn_vram())) return "CNN (E)";
    return t[std::clamp(v, 0, ur::kModels - 1)];
}
/// The DLSS model: the value chosen; variant 1: set for this run by RX_VK_DLSS_PRESET. ((Triforce, options_version 7) The row
/// shows only while NVIDIA DLSS is the Upscaler: row_shown)
const char* hn_dlss_model(int v, int variant) {
    static const char* const t[] = {
        "NVIDIA's transformer model: the one tested most here.",
        "NVIDIA's second-generation transformer, its pick for Performance: sharper, at a little more GPU time.",
        "The second-generation transformer as NVIDIA tuned it for Ultra Performance, the smallest Render resolutions.",
        "Lets DLSS's runtime pick for each mode: what it picks can change with a runtime update.",
    };
    static const char* const env = "Set for this run by RX_VK_DLSS_PRESET.";
    // ((Triforce, 11-22, PRESENT-36) variant 2, the K row's alone: preset E for this card (RX_VK_DLSS_CNN_VRAM=1))
    static const char* const cnn = "Chosen for this card's video memory (under 7 GB): less GPU time than K.";
    if (variant < 0) variant = dlss_preset_env() ? 1 : ur::cnn_for_vram(v, dlss_cnn_vram()) ? 2 : 0;
    if (variant == 1) return env;
    if (variant == 2) return v == ur::MODEL_K ? cnn : nullptr;
    return variant == 0 ? t[std::clamp(v, 0, ur::kModels - 1)] : nullptr;
}
/// ((Triforce) The FSR 4 model row (opts.fsr4_model): AMD's own pick for this GPU, or the smaller INT8 Lite network
const char* tx_fsr4_model(int v) { return v ? "Lite (INT8)" : "Auto (AMD's)"; }
/// The FSR 4 model: the value chosen; variant 1: set for this run by RX_VK_FSR4_MODEL
const char* hn_fsr4_model(int v, int variant) {
    static const char* const t[] = {
        "AMD's own choice for this GPU: FP8 on RDNA 4, full INT8 on RDNA 3 and Strix Halo, the Navi 2 INT8 model on RX 6000, "
        "Lite on Strix Point and Van Gogh.",
        "AMD's smaller FSR 4 network. On a GPU AMD already runs Lite on, this setting does nothing.",
    };
    static const char* const env = "Set for this run by RX_VK_FSR4_MODEL.";
    if (variant < 0) variant = fsr4_model_env() >= 0 ? 1 : 0;
    if (variant == 1) return env;
    return variant == 0 ? t[std::clamp(v, 0, ur::kFsr4Models - 1)] : nullptr;
}
const char* tx_aniso(int v) {   // (Triforce: the Texture filtering row)
    static const char* t[] = {"Game", "2x", "4x", "8x", "16x"};   // ((Triforce, 11-16) "Game", the owner's word)
    if ((unsigned)v >= sizeof t / sizeof t[0]) return t[0];
    return t[v];
}
// (Triforce) The Texture detail row (opts.tex_detail, tex_detail.h): Automatic is the card's own level by its video memory,
// which the row says once the first texture was made; RX_VK_TEX_DETAIL goes over the row for a run
int tex_detail_env() {
    static const int e = tex_detail::parse(getenv("RX_VK_TEX_DETAIL"));
    return e;
}
const char* tx_tex_detail(int v) {
    static const char* const t[] = {"Automatic", "Full", "Reduced", "Low"};
    static const char* const picked[] = {"Automatic (Full)", "Automatic (Reduced)", "Automatic (Low)"};
    if ((unsigned)v >= sizeof t / sizeof t[0]) v = 0;
    const int here = texture_detail_auto();
    return v == 0 && here >= 0 && here <= 2 ? picked[here] : t[v];
}
/// ((Triforce, 11-23) the Evil HD row, evil_hd.h: what each value does here
MENU_HINTS(hn_evil_hd, 0,
           "Off: the picture as the rows below are set.",
           "On: SMAA Ultra, 16x filtering and ambient occlusion now; every texture whole from the next start. A little more GPU "
           "time and video memory: a card with less than 12 GB can run out. With DLSS or FSR it is their own edges, and no "
           "ambient occlusion.")
/// ((Triforce, 11-23) the Texture filtering row: nothing for its value; while Evil HD is on, that it is 16x whatever is chosen
const char* hn_aniso(int, int variant) {
    static const char* const evil = "Evil HD is on: 16x, whatever is chosen here.";
    if (variant < 0) return opts.evil_hd ? evil : nullptr;
    return variant == 0 ? evil : nullptr;
}
/// The Texture detail: the value chosen; variant 1: set for this run by RX_VK_TEX_DETAIL; ((Triforce) 4: Evil HD on)
const char* hn_tex_detail(int v, int variant) {
    static const char* const t[] = {
        "By this graphics card's video memory: Full from 12 GB (never on integrated graphics), Reduced on 8 and 10 GB cards, "
        "Low under that. The value shows what it gives here.",
        "Every texture whole. On a card with less than 12 GB the video memory can run out, and the frame rate then falls to a "
        "fraction.",
        "The game's large textures at half their size each way, a quarter of their video memory. Text, icons and the HUD stay "
        "whole.",
        "As Reduced, and the largest textures at a quarter of their size each way.",
    };
    static const char* const env[] = {"Full for this run (RX_VK_TEX_DETAIL=full), whatever is chosen here.",
                                      "Reduced for this run (RX_VK_TEX_DETAIL=reduced), whatever is chosen here.",
                                      "Low for this run (RX_VK_TEX_DETAIL=low), whatever is chosen here."};
    static const char* const evil = "Evil HD is on: Full from the next start, whatever is chosen here.";
    if (variant < 0) variant = tex_detail_env() >= 0 ? 1 + tex_detail_env() : opts.evil_hd ? 4 : 0;
    if (variant == 0) return t[(unsigned)v < sizeof t / sizeof t[0] ? v : 0];
    return variant <= 3 ? env[variant - 1] : variant == 4 ? evil : nullptr;
}
// ((Triforce) 11-24) The Detail rows. Shadow resolution (opts.shadow_res): the sun's cascades at the game's own sizes
// (host/oot_shadow.c; on Highest the nearest one kept steady, host/oot_shadow_fit.c). Game's is the default: as shipped
const char* tx_shadow_res(int v) {
    static const char* const t[] = {"Game's", "High", "Highest"};
    return t[(unsigned)v < 3 ? v : 0];
}
MENU_HINTS(hn_shadow_res, 0, "1600 pixels a side, the console's. About 31 MB of video memory.",
           "2200 pixels a side. About 58 MB of video memory.",
           "3072 pixels a side, the game's own highest, and the shadows near you shimmer less while the camera moves. About "
           "113 MB of video memory.")
// ((Triforce) 11-24) Colour vision correction (opts.colour_vision; colour_vision.h): the finished picture's colours moved onto
// an axis the player sees. Off is the default: the picture as the game makes it
const char* tx_colour_vision(int v) {
    static const char* const t[] = {"Off", "Protan (red-green)", "Deutan (red-green)", "Tritan (blue-yellow)"};
    return t[(unsigned)v < 4 ? v : 0];
}
MENU_HINTS(hn_colour_vision, 0, "The picture's colors as the game makes them.",
           "For protanopia and protanomaly: reds told apart from greens, the difference moved towards blue and yellow.",
           "For deuteranopia and deuteranomaly: greens told apart from reds, the difference moved towards blue and yellow.",
           "For tritanopia and tritanomaly: blues told apart from yellows, the difference moved towards red and green.")
// (Grass distance (opts.grass_distance): the short grass blades' reach, vk_draw.cpp grass_reach. Game's is the default)
const char* tx_grass_distance(int v) {
    static const char* const t[] = {"Game's", "2x", "3x", "4x"};
    return t[(unsigned)v < 4 ? v : 0];
}
MENU_HINTS(hn_auto_pc, 0, "The rows are as you set them.",
           "Set for this PC: the log says what was chosen and why. A new graphics card chooses again.")
/// (Triforce) Opaque textures as BC1 (opts.tex_bc1, tex_bc1.h): nothing about the value itself; variants 0 and 1:
/// RX_VK_TEX_BC1 decides for this run, off or on
const char* hn_tex_bc1(int, int variant) {
    static const char* const t[] = {"Off for this run (RX_VK_TEX_BC1=0), whatever is chosen here.",
                                    "On for this run (RX_VK_TEX_BC1), whatever is chosen here."};
    if (variant < 0) {
        static const char* const e = getenv("RX_VK_TEX_BC1");
        return !e || !*e ? nullptr : t[atoi(e) != 0];
    }
    return variant < 2 ? t[variant] : nullptr;
}
// ((Triforce) 11-24) The Audio tab's Test microphone row: while on, the chosen microphone's level before and after the
// Microphone gain row (host->mic_test, host/nn_audio_in.c), in the row's own cell as a meter; what goes on in the line under
// its help. For this run only: never saved, and off as the Audio tab is left, the options close, the window loses the focus
// or the Microphone row is Off (mic_test_tick)
constexpr const char* kTestMic = "Test microphone";
// ((Triforce) 11-24) The System tab's NFC group: the Scan amiibo page (host/nn_nfp.c, the game folder's amiibo folder) for every
// player, not only with the Debug tab's tools on. The same page as the Debug tab's row, which stays (names_open)
constexpr const char* kNfcTag = "NFC tag";
bool mic_testing = false;
int mic_levels[2] = {}, mic_test_state = 0;
/// The Test microphone row's line under its help: what the meter shows, and what is wrong when something is
const char* mic_test_line() {
    if (!(mic_test_state & HOS_MIC_TEST_ON))
        return "Start the test, then play a note or hum: the bar shows how loud the microphone is after the gain.";
    static std::string line;
    line = !(mic_test_state & HOS_MIC_TEST_OPEN) ? "The microphone could not be opened."
         : !(mic_test_state & HOS_MIC_TEST_FRESH) ? "Waiting for the microphone's sound."
         : (mic_test_state & HOS_MIC_TEST_CLIP) ? "Too loud: the sound is clipped. Lower the Microphone gain."
                                                 : "The first figure is the microphone's level, the second after the gain.";
    if (mic_test_state & HOS_MIC_TEST_STANDIN) line += " The default microphone stands in for the one chosen.";
    return line.c_str();
}
const char* tx_percent(int v) {
    static char b[8];
    snprintf(b, sizeof b, "%d%%", v);
    return b;
}
// (local, RenoDX port: vk_renodx.cpp)
const char* tx_rdx_tonemap(int v) { return v == 2 ? "RenoDRT" : v ? "PsychoV35" : "Vanilla"; }   // (Triforce: RenoDRT)
const char* tx_rdx_gamma(int v) { return v == 1 ? "2.2" : v == 2 ? "BT.1886 (2.4)" : "Off"; }   // (Triforce)
const char* tx_rdx_midgray(int v) { return v == 1 ? "Vanilla" : v == 2 ? "Eye adaptation" : "Render"; }
const char* tx_rdx_space(int v) { return v == 1 ? "BT.709" : v == 2 ? "DCI-P3" : "Vanilla"; }
const char* tx_rdx_grade(int v) {
    static char b[8];
    snprintf(b, sizeof b, "%d", v);
    return b;
}
// The output the menu's sizes are shown for: the Output resolution row's (applied at the next start), so the rows below follow a change
// at once; the handheld profile runs the game's own (1536x864)
struct Out {
    uint32_t w, h;
};
// ((Triforce, 11-16, the owner: "Add a resolution of 5120x2160 before 5120x2880") 6 is 5120x2160, after the others so that the
// saved numbers keep their sizes. (Triforce) 8 Screen and 9 Custom take their sizes from outside the build. The rule for all of
// them is output_sizes.h's: the size is the picture's, the game's frame 16:9 at its height
constexpr Out kOutputs[] = {{2048, 1152}, {2560, 1440}, {3840, 2160}, {1920, 1080}, {5120, 1440}, {5120, 2880}, {5120, 2160}, {1536, 864}};
static_assert(std::size(kOutputs) == OUTPUT_FIXED_N);
constexpr int kLastOutput = OUTPUT_LAST;
int output_choice(int v) { return v >= 0 && v <= kLastOutput ? v : 0; }
// The connected screens as the host found them at the start (MkwVkHost.screens, at menu_init): each one's native size, the
// size the game takes it at (output_size_used: {0, 0} for none), the monitor's own name, and whether the window opens on it.
// The row offers each one's size; what is saved is that size, as Custom's (output_width=, output_height=), never a place in
// this list: the same file means the same picture with other screens connected, and a size whose screen is gone is Custom
struct Screen {
    Out native, used;
    std::string name;
    bool opens;
};
std::vector<Screen> screens;
void screen_add(uint32_t w, uint32_t h, const char* name, bool opens) {
    unsigned uw = 0, uh = 0;
    if (!output_size_used(w, h, &uw, &uh)) return;
    screens.push_back(Screen{Out{w, h}, Out{uw, uh}, name ? name : "", opens});
}
/// The screen the window opens on, nullptr when the host knows none
const Screen* screen_opening() {
    for (const Screen& s : screens)
        if (s.opens) return &s;
    return nullptr;
}
/// The main monitor's size, for an options file from before options_version 6 whose Ultrawide row was Monitor's shape: the
/// one the host reads that row by (host/hos_main.c, host/nn_applet.c: GetSystemMetrics). Off Windows that is the desktop's
/// main display (host/posix/win32_posix.c, display_sdl.c), which is the screen the window opens on; the renderer has no
/// GetSystemMetrics there, and takes it from the host's screens. {0, 0} when none is known: 16:9, for the host as well
Out main_screen() {
#ifdef _WIN32
    return Out{(uint32_t)std::max(GetSystemMetrics(SM_CXSCREEN), 0), (uint32_t)std::max(GetSystemMetrics(SM_CYSCREEN), 0)};
#else
    return screen_opening() ? screen_opening()->native : Out{0, 0};
#endif
}
/// The connected screens of a size, as the game takes them, by name: "LG ULTRAGEAR", "2x LG ULTRAGEAR", "DELL U2720Q, LG
/// ULTRAGEAR"; one the system gives no name is "Screen". "" when no screen has that size
std::string screen_names(Out size) {
    std::vector<std::pair<std::string, int>> names;
    for (const Screen& s : screens) {
        if (s.used.w != size.w || s.used.h != size.h) continue;
        const std::string name = s.name.empty() ? "Screen" : s.name;
        const auto at = std::find_if(names.begin(), names.end(), [&](const auto& n) { return n.first == name; });
        if (at == names.end()) names.push_back({name, 1});
        else at->second++;
    }
    std::string all;
    for (const auto& [name, count] : names)
        all += (all.empty() ? "" : ", ") + (count > 1 ? std::to_string(count) + "x " : std::string()) + name;
    return all;
}
/// HOS_OUTPUT_SIZE's size, which the host takes over the Custom rows for the run: true and the sides while it is set (a
/// value that is not <w>x<h>: 0 x 0, no size, as the host)
bool custom_env(long* w = nullptr, long* h = nullptr) {
    const char* e = getenv("HOS_OUTPUT_SIZE");
    if (!e) return false;
    long ew = 0, eh = 0;
    if (!output_parse_size(e, &ew, &eh)) ew = eh = 0;
    if (w) *w = ew;
    if (h) *h = eh;
    return true;
}
/// Custom's size as the game takes it: the Output width and Output height rows' (HOS_OUTPUT_SIZE's over them) within what a
/// picture can be, output_size_used; {0, 0} for none (a HOS_OUTPUT_SIZE that is not a size)
Out custom_size() {
    long w = opts.output_width, h = opts.output_height;
    custom_env(&w, &h);
    unsigned uw = 0, uh = 0;
    return output_size_used(w, h, &uw, &uh) ? Out{uw, uh} : Out{0, 0};
}
/// The Custom rows' values from the options file's output_width= and output_height= (0: no line), at menu_init: as written
/// where the rows can hold them, else the size the game takes them as (output_size_used: its shape kept, which keeping each
/// row to its own ends would not), so that the menu shows and saves what the host ran (host/nn_applet.c flex_read)
void custom_rows_read(long w, long h) {
    output_custom_read(&w, &h);
    unsigned uw = 0, uh = 0;
    const bool held = w >= OUTPUT_MIN_W && w <= OUTPUT_MAX_W && h >= OUTPUT_MIN_H && h <= OUTPUT_MAX_H;
    if (!held && output_size_used(w, h, &uw, &uh)) w = uw, h = uh;
    opts.output_width = (int)w, opts.output_height = (int)h;
}
// While a screen occupies the two active output fields, retain the player's unrounded Custom input.
Out remembered_custom{};
void restore_custom() {
    if (!remembered_custom.h) return;
    opts.output_width = (int)remembered_custom.w;
    opts.output_height = (int)remembered_custom.h;
    remembered_custom = {};
}
void choose_screen(Out size) {
    if (!remembered_custom.h) remembered_custom = Out{(unsigned)opts.output_width, (unsigned)opts.output_height};
    unsigned w, h;
    if (output_size_used(remembered_custom.w, remembered_custom.h, &w, &h) && w == size.w && h == size.h) {
        restore_custom();
        return;
    }
    opts.output_width = (int)size.w;
    opts.output_height = (int)size.h;
}
void read_remembered_custom(const char* text) {
    long w = 0, h = 0;
    if (output_parse_size(text, &w, &h) &&
        w >= OUTPUT_MIN_W && w <= OUTPUT_MAX_W && h >= OUTPUT_MIN_H && h <= OUTPUT_MAX_H)
        remembered_custom = Out{(unsigned)w, (unsigned)h};
}
/// The size of a saved value: a fixed one's, Custom's, or the old Screen's ({0, 0}: none)
Out row_size(int v) {
    v = output_choice(v);
    if (v == OUTPUT_SCREEN) return screen_opening() ? screen_opening()->used : Out{0, 0};   // (the old Screen value: as the host)
    return v < OUTPUT_SCREEN ? kOutputs[v] : custom_size();
}
/// The size a choice runs at: the row's, 2560x1440 when Screen or Custom has none, as the host
Out output_size_of(int v) {
    const Out s = row_size(v);
    return s.h ? s : kOutputs[1];
}
/// Whether a choice's size has a shape of its own, not 16:9: its picture is that size, and the Ultrawide row has nothing to
/// choose (docked only: the handheld profile runs the game's own output)
bool output_shaped(int v) {
    const Out s = output_size_of(v);
    return opts.output_res != merged_rows::kHandheldOutput && output_size_shaped(s.w, s.h);
}
/// The game's frame for a choice, its HUD, menus and story movies: the size, or 16:9 at its height when it has another shape
Out output_frame(int v) {
    const Out s = output_size_of(v);
    return output_size_shaped(s.w, s.h) ? Out{output_frame_width(s.h), s.h} : s;
}
/// HOS_ASPECT's shape, which the host takes over the Output resolution's and the Ultrawide row's for the run; 0 when not set
float aspect_env() {
    const char* e = getenv("HOS_ASPECT");
    return e ? (float)atof(e) : 0.0f;
}
/// The picture the options give at the next start, as host/hos_main.c makes it (output_picture): the Output resolution's size
/// when it has its own shape, else its height in the Ultrawide row's shape (HOS_ASPECT's over both). 2048x1152 is the game's
/// 2560x1440 at its graphics scale 0.8 (host/nn_applet.c), its wider picture too
Out output_picture_of(int v, int ultrawide_row) {
    v = output_choice(v);
    const Out size = output_size_of(v), frame = v ? output_frame(v) : kOutputs[1];
    const bool env = getenv("HOS_ASPECT") != nullptr;
    const bool sized = !env && output_size_shaped(size.w, size.h);
    const double want = env ? aspect_env() : sized ? (double)size.w / (double)size.h : ultrawide_row_ratio(ultrawide_row);
    unsigned w = 0, h = 0;
    if (!output_picture(frame.h, want, sized, &w, &h)) return v ? frame : kOutputs[0];
    return v ? Out{w, h} : Out{w * 4 / 5, h * 4 / 5};
}
/// ((Triforce) the sizes of the screen the game's window is on, its display modes and the common sizes of each shape up to its
/// size, as the game takes them (output_modes.h; read_mode_sizes, as the menu opens): none until then
std::vector<Out> mode_list;
// The row's choices: the fixed sizes, each connected screen's size that is not one of those (once for screens of one size), and
// Custom where its size is not a screen's. Smallest to largest, by width and then height; of one size a fixed one first; one
// with no size at the end. A choice is saved as its value: a fixed size's number, or OUTPUT_CUSTOM with the size in the Output
// width and Output height rows, which choosing a screen's size fills in with the size the game takes that screen at (size;
// native: that screen's own, {0, 0} for a choice that is no screen's)
struct OutEntry {
    int id;
    Out size, native;
};
std::vector<OutEntry> output_entries() {
    std::vector<OutEntry> e;
    const auto has = [&](int id, Out s) {
        return std::any_of(e.begin(), e.end(), [&](const OutEntry& x) { return x.id == id && x.size.w == s.w && x.size.h == s.h; });
    };
    // (a screen of a fixed size is that fixed choice, the same picture; but not of 2048x1152, which is the game's 2560x1440 at
    // its own scale and not a 2048x1152 picture)
    const auto fixed = [](Out s) {
        for (int v = 1; v < OUTPUT_FIXED_N; v++)
            if (v != merged_rows::kHandheldOutput && kOutputs[v].w == s.w && kOutputs[v].h == s.h) return true;
        return false;
    };
    for (int v = 0; v < OUTPUT_FIXED_N; v++) e.push_back(OutEntry{v, kOutputs[v], Out{0, 0}});
    // (HOS_OUTPUT_SIZE is Custom's size for the run: a screen's size cannot be chosen then)
    for (const Screen& s : screens)
        if (!custom_env() && !fixed(s.used) && !has(OUTPUT_CUSTOM, s.used)) e.push_back(OutEntry{OUTPUT_CUSTOM, s.used, s.native});
    // ((Triforce) the screen's display modes and the common sizes of each shape: chosen, Custom with that size, as a screen's)
    for (const Out& m : mode_list)
        if (!custom_env() && !fixed(m) && !has(OUTPUT_CUSTOM, m)) e.push_back(OutEntry{OUTPUT_CUSTOM, m, m});
    // (the old Screen value, only while it is still what is chosen: menu_init makes it the screen's size, output_adopt_screen)
    if (output_choice(opts.output_res) == OUTPUT_SCREEN) e.push_back(OutEntry{OUTPUT_SCREEN, row_size(OUTPUT_SCREEN), Out{0, 0}});
    // A fixed choice can have a remembered Custom in an edited file. Only the remembered pair is restored.
    if ((opts.output_res == OUTPUT_CUSTOM || !remembered_custom.h || custom_env()) && !has(OUTPUT_CUSTOM, custom_size()))
        e.push_back(OutEntry{OUTPUT_CUSTOM, custom_size(), Out{0, 0}});
    if (remembered_custom.h && !custom_env()) {
        unsigned w, h;
        if (output_size_used(remembered_custom.w, remembered_custom.h, &w, &h) && !has(OUTPUT_CUSTOM, Out{w, h}))
            e.push_back(OutEntry{OUTPUT_CUSTOM, Out{w, h}, Out{0, 0}});
    }
    const auto key = [](const OutEntry& x) { return x.size.h ? (uint64_t)x.size.w << 32 | x.size.h : ~0ull; };
    std::stable_sort(e.begin(), e.end(), [&](const OutEntry& a, const OutEntry& b) { return key(a) < key(b); });
    return e;
}
/// The choice the options have now: the saved value's, and for Custom the one of its size (a screen's, or Custom itself)
int output_entry_now(const std::vector<OutEntry>& e) {
    const int v = output_choice(opts.output_res);
    const Out c = custom_size();
    for (size_t i = 0; i < e.size(); i++)
        if (e[i].id == v && (v != OUTPUT_CUSTOM || (e[i].size.w == c.w && e[i].size.h == c.h))) return (int)i;
    return 0;
}
/// A choice as the row shows it: the size, with the names of the connected screens that have it ("3840x1600 (LG ULTRAGEAR)");
/// Custom with its size
std::string output_label(const OutEntry& x) {
    if (!x.size.h) return x.id == OUTPUT_SCREEN ? "Screen (not known)" : "Custom (not set)";
    if (x.id == merged_rows::kHandheldOutput) return "1536x864 (handheld)";
    const std::string size = std::to_string(x.size.w) + "x" + std::to_string(x.size.h);
    if (x.id == OUTPUT_CUSTOM && !x.native.h) return "Custom (" + size + ")";
    if (x.id == 0) return size;   // (the game's own: no screen's size, output_entries)
    const std::string names = screen_names(x.size);
    return names.empty() ? (x.id == OUTPUT_SCREEN ? "Screen (" + size + ")" : size) : size + " (" + names + ")";
}
/// One choice down or up the row (dir -1 or 1): false at its end. With apply the options take it: its value, and a
/// screen's size as Custom's
bool output_step(int dir, bool apply) {
    const std::vector<OutEntry> e = output_entries();
    const int at = output_entry_now(e), to = std::clamp(at + dir, 0, (int)e.size() - 1);
    if (to == at) return false;
    if (apply) {
        opts.output_res = e[to].id;
        // (the size as the game takes it, which the rows can always hold: a 7680x4320 screen's is 5120x2880, not each side cut
        // to the rows' ends, which would be another shape)
        if (e[to].native.h) choose_screen(e[to].size);
        else restore_custom();
    }
    return true;
}
/// An options file's output_res=8, Screen (and HOS_OUTPUT_RES=8): the size of the screen the window opens on, which
/// is what the host ran it as at this start (host/nn_applet.c). The menu keeps it as that size, Custom's, so that the next
/// save writes a size and not "whichever screen" (a fixed size's number where it is one); with no screen known, the
/// 2560x1440 the host ran. Left alone while
/// HOS_OUTPUT_SIZE is Custom's size
void output_adopt_screen() {
    if (output_choice(opts.output_res) != OUTPUT_SCREEN || custom_env()) return;
    const Screen* s = screen_opening();
    opts.output_res = s ? OUTPUT_CUSTOM : 1;
    for (int v = 1; s && v < OUTPUT_FIXED_N; v++)   // (a screen of a fixed size: that fixed choice)
        if (v != merged_rows::kHandheldOutput && kOutputs[v].w == s->used.w && kOutputs[v].h == s->used.h) opts.output_res = v;
    if (s && opts.output_res == OUTPUT_CUSTOM) choose_screen(s->used);
}
/// The picture the menu's sizes are shown for (the Render resolution's, the performance panel's)
Out shown_output() {
    return opts.output_res == merged_rows::kHandheldOutput ? Out{1536, 864} : output_picture_of(opts.output_res, opts.ultrawide);
}
// The size the game draws the 3D at for a fixed scale of its output, a twelfth of it: every twelfth asked came out exact at the three
// outputs (2048x1152: 0.58 drew 1195x672, 0.6667 1366x768). So the scale the game is given is the twelfth too: 0.67 drew 2615x1471 at
// 3840x2160, not the 2560x1440 of 8/12.
int twelfths(float scale) { return std::min(std::max((int)(scale * 12.0f + 0.5f), 1), 12); }
void game_size(float scale, uint32_t& w, uint32_t& h) {
    const Out o = shown_output();
    const int k = twelfths(scale);
    w = (o.w * k + 11) / 12, h = o.h * k / 12;
}
const char* tx_resolution(int v) {
    static char b[48];
    const int up = upscaler();
    if (ur::full_scale(up)) return "Native (100%)";   // ((Triforce, options_version 7) DLAA, FSR 4's and FSR 3.1's native AA)
    v = ur::snap(up, v);   // ((Triforce) 11-24: the Upscaler's own step for the saved scale, which stays the player's: set_row)
    if (!ur::percent(v)) return "Auto (dynamic)";
    // ((Triforce) Intel XeSS: the preset whose range holds the share, upscaler_rows.h xess_mode_name)
    if (const char* mode = up == ur::XESS ? ur::xess_mode_name(v) : ur::scales_by_mode(up) ? ur::dlss_mode_name(v) : nullptr) {
        snprintf(b, sizeof b, "%s (%d%%)", mode, ur::percent(v));
        return b;
    }
    uint32_t w, h;
    game_size(ur::percent(v) / 100.0f, w, h);
    snprintf(b, sizeof b, "%d%% (%ux%u)", ur::percent(v), w, h);
    return b;
}
/// The Render resolution: the value chosen, for the Upscaler shown (every one: each value with each Upscaler)
const char* hn_resolution(int v, int variant) {
    const int up = variant < 0 ? std::clamp(upscaler(), 0, ur::kUpscalers - 1) : variant;
    if (up >= ur::kUpscalers) return nullptr;
    if (ur::full_scale(up))   // ((Triforce, options_version 7) Native (100%): the engine's native anti-aliasing)
        // ((Triforce, FSR4-2) chosen in play, the engine scales the smaller 3D up to the output until the next start)
        return "The 3D at the output's full size, its edges smoothed by the upscaler: the sharpest, and the slowest. The 3D "
               "takes its full size at the next start.";
    const int p = ur::percent(ur::snap(up, v));   // ((Triforce) 11-24: as tx_resolution shows it)
    if (up == ur::DLSS) {
        switch (p) {
        case 0: return "The game lowers it when the GPU is busy, and DLSS follows.";
        case 67: return "DLSS's Quality mode: its sharpest from a smaller 3D.";
        case 58: return "DLSS's Balanced mode, between Quality and Performance.";
        case 50: return "DLSS's Performance mode: faster, and softer.";
        case 33: return "DLSS's Ultra Performance mode: its fastest, and its softest.";
        default: return nullptr;   // (not one of DLSS's steps: the row moves to one)
        }
    }
    if (up == ur::FSR3 || up == ur::FSR4) {   // (the same modes, AMD's ratios)
        switch (p) {
        case 0: return "The game lowers it when the GPU is busy, and FSR follows.";
        case 67: return "FSR's Quality mode, 1.5x: its sharpest.";
        case 58: return "FSR's Balanced mode, 1.7x.";
        case 50: return "FSR's Performance mode, 2x: faster, and softer.";
        case 33: return "FSR's Ultra Performance mode, 3x: its fastest, and its softest.";
        default: return nullptr;   // (not one of FSR's steps: the row moves to one)
        }
    }
    if (up == ur::XESS) {   // ((Triforce) each step under the XeSS preset whose range holds it: xess_rules.h)
        switch (p) {
        case 0: return "The game lowers it when the GPU is busy, and XeSS follows.";
        case 67: return "XeSS's Ultra Quality mode, 1.5x: its sharpest from a smaller 3D.";
        case 58: return "Between XeSS's Quality and Balanced, under its Balanced mode, 2x.";
        case 50: return "XeSS's Balanced mode, 2x: faster, and softer.";
        case 33: return "XeSS's Ultra Performance mode, 3x: its fastest, and its softest.";
        default: return nullptr;   // (not one of its steps: the row moves to one)
        }
    }
    if (!p) return "The game lowers it when the GPU is busy.";
    if (p == 100) return "The 3D at the output's full size: the sharpest, and the slowest.";
    return "A steady size: lower is faster, and softer.";
}
/// (Triforce) The Anti-aliasing row (aa_rows.h, vk_aa.h): its choice, RX_VK_AA's for the run over it; while DLSS or FSR
/// draws, whose anti-aliasing the picture has instead
const char* tx_aa(int v) {
    if (n64_in_front() != n64_rules::OFF) return "N64 Classic";   // ((Triforce, N64 Classic) its grid smooths the edges)
    const int up = upscaler();
    if (ur::is_dlss(up)) return "DLSS's own";
    if (ur::is_xess(up)) return "XeSS's own";   // ((Triforce) Intel XeSS)
    if (aa_rows::upscaler_own(up)) return "FSR's own";
    return aa_rows::name(aa_rows::chosen(v, aa_env_choice()));
}
/// The Anti-aliasing: the value chosen (variant 0); that it does not apply while NVIDIA DLSS or DLAA (1) or AMD FSR (2)
/// draws; that RX_VK_AA set it for this run (3); that the game's pass was not there to replace (4); ((Triforce) that it does
/// not apply while Intel XeSS draws (6)
const char* hn_aa(int v, int variant) {
    static const char* const t[aa_rows::kValues] = {
        "The game's own SMAA, as on the console.",
        "None: the 3D's edges as they were drawn. The sharpest, with stair steps on edges and shimmer on thin things.",
        "FXAA in place of the game's SMAA: a fast smoothing of the finished 3D's edges, a little softer on fine detail.",
        "SMAA at its highest preset in place of the game's own: long and diagonal edges smoother, for more GPU time."};
    static const char* const own[2] = {
        "NVIDIA DLSS and DLAA smooth the 3D's edges themselves, from frames the game's SMAA has not been over: nothing to set "
        "here. The choice is kept for the game's own upscaler.",
        "AMD FSR smooths the 3D's edges itself, from frames the game's SMAA has not been over: nothing to set here. The choice "
        "is kept for the game's own upscaler."};
    static const char* const env = "Set for this run by RX_VK_AA, whatever is chosen here.";
    static const char* const missing =
        "No frame of the last minute had the game's own anti-aliasing pass to replace (a screen without the 3D, or another "
        "version of the game): the picture is the game's.";
    static const char* const n64 =   // ((Triforce, N64 Classic) variant 5)
        "N64 Classic draws the 3D on its own grid, which smooths the edges: nothing to set here while it is on. The choice is "
        "kept for when it is off.";
    if (variant < 0) {
        const int up = upscaler();
        const bool asked = aa_rows::chosen(evil_hd::aa(opts.evil_hd, v), aa_env_choice()) != aa_rows::GAME;
        variant = n64_in_front() != n64_rules::OFF ? 5 : ur::is_dlss(up) ? 1 : ur::is_xess(up) ? 6 : aa_rows::upscaler_own(up) ? 2
                  : asked && aa_state() == aa_rows::MISSING ? 4 : aa_env_choice() >= 0 ? 3 : opts.evil_hd ? 7 : 0;
    }
    switch (variant) {
    case 0: return t[v >= 0 && v < aa_rows::kValues ? v : 0];
    case 1: return own[0];
    case 2: return own[1];
    case 3: return env;
    case 4: return missing;
    case 5: return n64;
    case 6:   // ((Triforce) Intel XeSS)
        return "Intel XeSS smooths the 3D's edges itself, from frames the game's SMAA has not been over: nothing to set here. "
               "The choice is kept for the game's own upscaler.";
    case 7: return "Evil HD is on: SMAA Ultra, whatever is chosen here.";   // ((Triforce, 11-23) evil_hd.h)
    default: return nullptr;
    }
}
int shape_owner();
// ---- ((Triforce, 11-22, N64 Classic, step 5) its row and the Remembered page (n64_rules.h; vk_n64.cpp) ----
void save();   // (below)
/// The N64 Classic row: its value's name, RX_VK_N64's for the run over it
const char* tx_n64(int v) { return n64_rules::name(n64_env_set() ? n64_preset() : v); }
/// The N64 Classic row: the value chosen (variant 0), or that RX_VK_N64 set it for this run (1)
const char* hn_n64(int v, int variant) {
    static const char* const t[n64_rules::kPresets] = {
        "The remake as it is.",
        "The 1998 cartridge on a TV of then: the 3D on 240 lines with 16-bit colour and its dither, blurry textures, scanlines "
        "and a curved screen, at 20 frames a second. Always the same.",
        "How you remember it: sharper and richer than the real thing. Set it to your taste in Remembered settings."};
    static const char* const env = "Set for this run by RX_VK_N64, whatever is chosen here.";
    if (variant < 0) variant = n64_env_set() ? 1 : 0;
    if (variant == 0) return t[v >= 0 && v < n64_rules::kPresets ? v : 0];
    return variant == 1 ? env : nullptr;
}
const char* tx_n64_fps(int v) {
    static const char* const t[] = {"Frame rate cap", "60", "30", "20 (1998)", "17 (1998, 50 Hz)"};
    return t[std::clamp(v, 0, 4)];
}
const char* tx_n64_lines(int v) {
    static const char* const t[] = {"240 lines", "360 lines", "480 lines", "720 lines"};
    return t[std::clamp(v, 0, 3)];
}
const char* tx_n64_colour(int v) {
    static const char* const t[] = {"15-bit (1998)", "18-bit", "Full"};
    return t[std::clamp(v, 0, 2)];
}
const char* tx_n64_dither(int v) {
    static const char* const t[] = {"Off", "Light", "Full"};
    return t[std::clamp(v, 0, 2)];
}
const char* tx_n64_blur(int v) {
    static char b[16];
    if (v <= 0) return "Off";
    snprintf(b, sizeof b, "+%.1f", v * n64_rules::kBlurStep);
    return b;
}
const char* tx_n64_mask(int v) {
    static const char* const t[] = {"Auto", "Off", "Aperture grille", "Slot mask", "Shadow mask"};
    return t[std::clamp(v, 0, 4)];
}
const char* tx_n64_bleed(int v) {
    static const char* const t[] = {"Off", "Light", "Composite"};
    return t[std::clamp(v, 0, 2)];
}
const char* tx_n64_curve(int v) {
    static const char* const t[] = {"Flat", "Slight", "Curved", "Very curved"};
    return t[std::clamp(v, 0, 3)];
}
/// A Remembered page row's place in n64_rules::Rows (its value is opts.n64_rem's), -1 for any other value
int n64_rem_row(const int* value) {
    const int* first = &opts.n64_rem[0];
    return value && value >= first && value < first + n64_rules::kRows ? (int)(value - first) : -1;
}
/// The Graphics tab's row that opens the Remembered page (the TAB_N64 rows), as the Motion row opens the Motion page
bool is_n64_page_row(const Row& r) { return r.tab == TAB_GRAPHICS && !r.value && !strcmp(r.name, "Remembered settings"); }
/// ((Triforce, 11-24) the Graphics tab's row that opens the Simulated turf page (the TAB_SIM_TURF rows), and the page's action
bool is_sim_turf_page_row(const Row& r) { return r.tab == TAB_GRAPHICS && !r.value && !strcmp(r.name, "Simulated turf"); }
bool is_sim_turf_reset_row(const Row& r) { return r.tab == TAB_SIM_TURF && !r.value && !strcmp(r.name, "Reset current area"); }
/// (the page's rows by Use global multipliers: on, the four multipliers of every area's own values; off, this area's own four
/// values and its Reset)
bool sim_turf_row_shown(const Row& r) {
    namespace sts = sim_turf_settings;
    if (r.tab != TAB_SIM_TURF || r.value == &sts::global) return true;
    for (int& m : sts::multipliers)
        if (r.value == &m) return sts::global != 0;
    return sts::global == 0;
}
const char* hn_sim_turf_area(int, int variant) { return variant <= 0 ? sim_turf_area_note() : nullptr; }
const char* hn_sim_turf_reset(int, int variant) {
    if (variant > 0) return nullptr;
    if (variant == 0) return "This area already has the game's own values.";
    return !sim_turf_ready() ? "Go to an area first." : sim_turf_can_reset() ? nullptr : "This area already has the game's own values.";
}
/// The Remembered page's two actions: 1 Copy Faithful, 2 Reset to defaults; 0 another row
int n64_action(const Row& r) {
    if (r.tab != TAB_N64 || r.value) return 0;
    return !strcmp(r.name, "Copy Faithful") ? 1 : !strcmp(r.name, "Reset to defaults") ? 2 : 0;
}
/// An action pressed: Faithful's values into Remembered's rows (20 frames a second too), or Remembered's defaults; saved
void n64_act(int action) {
    if (action != 1 && action != 2) return;
    const n64_rules::Rows to = action == 1 ? n64_rules::kFaithful : n64_rules::defaults();
    std::copy(std::begin(to.v), std::end(to.v), opts.n64_rem);
    save();
}
/// A row with nothing else to choose here: shown without its arrows, Left and Right leave it (and the saved value) alone
bool row_fixed(const int* value) {
    // ((Triforce) the Ultrawide row while the Output resolution's own shape or HOS_ASPECT is the picture's; the Custom rows
    // while HOS_OUTPUT_SIZE is Custom's size)
    if (value == &opts.ultrawide && shape_owner() != 0) return true;
    if ((value == &opts.output_width || value == &opts.output_height) && custom_env()) return true;
    // ((Triforce, options_version 7) the rows that showed fixed where they could do nothing (Reflex, Anti-Lag, the window's
    // filter, the Render resolution with a native AA) are hidden there, or gone: row_shown)
    return (value == &opts.aa && aa_rows::fixed(upscaler(), aa_env_choice() >= 0)) ||
           (value == &opts.dlss && ur::upscaler_fixed(upscalers_available())) ||
           (value == &opts.dlss_model && ur::model_fixed(upscaler(), dlss_preset_env() != nullptr)) ||
           (value == &opts.fsr4_model && ur::fsr4_model_fixed(upscaler(), fsr4_model_env() >= 0)) ||   // ((Triforce))
           // ((Triforce, 11-22, N64 Classic) the Upscaler and the Anti-aliasing while its 3D pass draws in their place; its own
           // row with RX_VK_N64 set for the run; a Remembered row with nothing to do (n64_rules.h row_fixed)
           ((value == &opts.dlss || value == &opts.aa) && n64_in_front() != n64_rules::OFF) ||
           (value == &opts.n64_classic && n64_env_set()) ||
           (n64_rem_row(value) >= 0 && n64_rules::row_fixed(n64_rules::rows_of(opts.n64_rem), n64_rem_row(value)));
}
const char* tx_output_res(int v) {
    static char b[200];
    const std::vector<OutEntry> e = output_entries();
    v = output_choice(v);
    if (v == merged_rows::kHandheldOutput) return "1536x864 (handheld)";
    size_t at = (size_t)output_entry_now(e);
    if (e[at].id != v) {   // (not the value chosen: a fixed size's own choice, or Custom's)
        for (size_t i = 0; i < e.size(); i++)
            if (e[i].id == v && (e[at].id != v || !e[i].native.h)) at = i;
    }
    snprintf(b, sizeof b, "%s", output_label(e[at]).c_str());
    return b;
}
/// (Triforce) The Output width and Output height rows (output_width=, output_height=): a side in pixels as chosen, or
/// HOS_OUTPUT_SIZE's while it is set. What the game makes of the two is the Output resolution row's Custom (custom_size)
const char* tx_custom_side(int v, bool height) {
    static char b[2][16];
    long w = 0, h = 0;
    if (custom_env(&w, &h)) v = (int)(height ? h : w);
    if (v > 0) snprintf(b[height], sizeof b[height], "%d", v);
    else snprintf(b[height], sizeof b[height], "Not set");
    return b[height];
}
const char* tx_custom_width(int v) { return tx_custom_side(v, false); }
const char* tx_custom_height(int v) { return tx_custom_side(v, true); }
const char* tx_speed(int v) { return v ? "Real time" : "Per frame"; }
const char* tx_text_speed(int v) {
    static const char* t[] = {"Normal", "2x", "4x", "Instant"};
    if ((unsigned)v >= sizeof t / sizeof t[0]) return t[0];
    return t[v];
}
// (Triforce) The Text size row (host/oot_text_size.c, host/oot_play.h oot_text_size_scale has the scales)
const char* tx_text_size(int v) {
    static const char* t[] = {"Normal", "110%", "125%", "150%", "175%"};
    if ((unsigned)v >= sizeof t / sizeof t[0]) return t[0];
    return t[v];
}
// (Triforce) The Damage taken row (host/oot_damage.c, host/oot_play.h OOT_DAMAGE_*)
const char* tx_damage_taken(int v) {
    static const char* const t[] = {"Half", "Normal", "Double", "Quadruple"};
    return t[v >= 0 && v < 4 ? v : 1];
}
// (Triforce) The Field of view row (host/oot_fov.c): percent of the game's own angle
const char* tx_fov(int v) {
    static char b[24];
    snprintf(b, sizeof b, v == 100 ? "100%% (the game's)" : "%d%%", v);
    return b;
}
const char* tx_ultrawide(int v) {   // (Triforce: 1 to 4, the fixed shapes, ultrawide_rows.h; host/hos_main.c ultrawide_ratio)
    static const char* const t[] = {"16:9", "16:10", "21:9", "32:9", "4:3"};
    return t[std::min(std::max(v, 0), 4)];
}
/// A shape, width over height, by name: one of the Ultrawide row's where it is that one, else its width for a height of 1
/// (3840x1600: 2.40:1)
const char* shape_name(double ratio) {
    static char b[16];
    for (int row = 1; row <= 3; row++)
        if (fabs(ratio / (double)ultrawide_row_ratio(row) - 1.0) < 0.001) return tx_ultrawide(row);
    snprintf(b, sizeof b, "%.2f:1", ratio);
    return b;
}
/// What decides the picture's shape at the next start, as host/hos_main.c takes it: 2 HOS_ASPECT, 1 the Output resolution's
/// own shape (a size that is not 16:9), 0 the Ultrawide row
int shape_owner() { return getenv("HOS_ASPECT") ? 2 : output_shaped(opts.output_res) ? 1 : 0; }
/// The picture's shape at the next start by name: the Ultrawide row's choice v, or the shape that is the picture's whatever
/// is chosen there (shape_owner)
const char* shape_now(int v) {
    const int owner = shape_owner();
    if (owner == 0) return tx_ultrawide(v);
    if (owner == 2) return aspect_env() > 1.0f && !output_shape_is_game(aspect_env()) ? shape_name(aspect_env()) : tx_ultrawide(0);
    const Out o = output_size_of(opts.output_res);
    return shape_name((double)o.w / (double)o.h);
}
/// The Ultrawide row's value: its choice, or the shape the picture has whatever is chosen here, with where it comes from
const char* tx_shape(int v) {
    static char b[48];
    const int owner = shape_owner();
    if (owner == 0) return tx_ultrawide(v);
    const Out o = output_size_of(opts.output_res);
    if (owner == 2) snprintf(b, sizeof b, "%s (HOS_ASPECT)", shape_now(v));
    else snprintf(b, sizeof b, "%s (%ux%u)", shape_now(v), o.w, o.h);
    return b;
}
const char* tx_wide_hud(int v) { return v ? "Screen edges" : "Middle"; }
// ((Triforce) The HUD placement row and Custom's rows (host/hos_wide_ui.c places the three groups at each present)
const char* tx_hud_placement(int v) { return v ? "Custom" : "Game's"; }
MENU_HINTS(hn_hud_placement, 0, "The hearts, buttons and minimap where the game puts them.",
           "Move and resize the hearts, the buttons and the minimap from their usual places.")
bool hud_custom_row(const int* v) {
    return v == &opts.hud_health_x || v == &opts.hud_health_y || v == &opts.hud_health_scale || v == &opts.hud_buttons_x ||
           v == &opts.hud_buttons_y || v == &opts.hud_buttons_scale || v == &opts.hud_minimap_x || v == &opts.hud_minimap_y ||
           v == &opts.hud_minimap_scale;
}
int pack_placement(int x, int y, int scale) { return (x + 16) | ((y + 16) << 6) | (scale << 12); }
const char* tx_prompts(int v) {
    static const char* t[HOS_PROMPT_N + 1] = {"Auto", "Switch", "Xbox", "PlayStation 4", "PlayStation 5", "Steam Deck",
                                              "Keyboard & mouse"};
    return t[std::min(std::max(v, 0), (int)HOS_PROMPT_N)];
}
// ((Triforce) 11-24) The Fullscreen screen row (opts.fs_screen): Automatic, the screen the window is on, or each connected
// screen as the host listed them at the start, by its name and size (fs_screen_labels). The choice is kept by that label too
// (fullscreen_screen_name), so the same screen is found when the list's order changes; one that is gone is Automatic.
// host/display.c moves the window there (HOS_OPT_FULLSCREEN_SCREEN). Windows only: the row is not shown elsewhere
std::vector<std::string> fs_screen_labels;
std::string fs_screen_want;   // (the label the options file had, until menu_init has found it)
const char* tx_fs_screen(int v) {
    if (v <= 0 || v > (int)fs_screen_labels.size()) return "Automatic";
    return fs_screen_labels[(size_t)v - 1].c_str();
}
const char* tx_gpu(int v) {
    static char buf[300];
    const int idx = v - 1;
    if (v <= 0) snprintf(buf, sizeof buf, "Auto");
    else if (idx < (int)gpu_device_names.size()) snprintf(buf, sizeof buf, "%d: %s", idx, gpu_device_names[idx].c_str());
    else snprintf(buf, sizeof buf, "%d: Device %d", idx, idx);
    // (the whole name shows: the selected row slides through it, see marquee_pos)
    return buf;
}
const char* tx_pad_layout(int v);
// (hookshot) the Microphone row: Off, the system's default, or one of the host's microphones (host/nn_audio_in.c: the
// ocarina's input streams), told to the host by its name (host->mic_select) whenever it changes. The chosen one is kept by
// its name, mic_want, also while it is unplugged: the row then has one more entry for it, "<name> (not connected)", the
// host lets the default stand in and opens it again once it is back, and the name stays in the ini. In the ini the name is
// cut to kMicNameKept bytes (at a character's start), so the line fits the 80-byte readers of the file (host/nn_hid.c,
// nn_applet.c, hos_main.c), and a name is matched by that much of it
constexpr int kMaxMics = 64;
constexpr size_t kMicNameKept = 60;
std::string mic_want;      // (the chosen microphone's name, cut to kMicNameKept; empty: Off or the default chosen)
// ((Triforce) 11-20) the GPU device row's card by its name (triforce_options.ini gpu_device_name, written beside the number by
// the launcher and by save below; empty: none saved, or Auto). pick_device finds the card by it (gpu_choice.h pick)
std::string gpu_want;
bool mic_missing = false;  // (mic_want is not plugged in: the row's last entry, 2 + mic_listed, stands for it)
int mic_listed = 0;        // (the microphones as the host last listed them)
bool can_mic() { return host && host->mic_count && host->mic_name && host->mic_select; }
size_t text_char_start(const std::string& text, size_t at) {
    while (at > 0 && at < text.size() && ((unsigned char)text[at] & 0xc0) == 0x80) at--;
    return at;
}
std::string mic_key(const char* name) {
    std::string k(name ? name : "");
    for (char& c : k)   // (a device's name goes into triforce_options.ini: a line break in it would add lines there)
        if ((unsigned char)c < 0x20 || c == 0x7f) c = ' ';
    if (k.size() > kMicNameKept) k = k.substr(0, text_char_start(k, kMicNameKept));
    // (and no spaces at the end: a saved line's end, made one above, and those an older build saved with the name)
    while (!k.empty() && k.back() == ' ') k.pop_back();
    return k;
}
/// ((Triforce) 11-24) The Fullscreen screen row's label as the options file keeps it: mic_key's, cut so that its line fits the
/// file's 80-byte readers
std::string fs_key(const std::string& label) {
    std::string k = mic_key(label.c_str());
    if (k.size() > 54) k = k.substr(0, text_char_start(k, 54));
    while (!k.empty() && k.back() == ' ') k.pop_back();
    return k;
}
/// buf cut back to whole UTF-8 characters (snprintf may have cut one)
void utf8_whole(char* buf) {
    size_t n = strlen(buf), i = n;
    while (i > 0 && ((unsigned char)buf[i - 1] & 0xC0) == 0x80) i--;   // (the last character's continuation bytes)
    if (i == 0) return;
    const unsigned char lead = (unsigned char)buf[i - 1];
    const size_t want = lead >= 0xF0 ? 4 : lead >= 0xE0 ? 3 : lead >= 0xC0 ? 2 : 1;
    if (n - (i - 1) < want) buf[i - 1] = 0;
}
const char* tx_mic(int v) {
    static char buf[160];
    if (v <= 0) return "Off";
    if (v == 1) return "Default";
    if (mic_missing && v == 2 + mic_listed) {
        const int room = (int)sizeof buf - (int)sizeof " (not connected)";
        snprintf(buf, (size_t)room + 1, "%s", mic_want.c_str());
        utf8_whole(buf);
        strcat(buf, " (not connected)");
        return buf;
    }
    const char* n = can_mic() ? host->mic_name(v - 2) : "";
    snprintf(buf, sizeof buf, "%s", n && *n ? n : "Microphone");
    utf8_whole(buf);
    return buf;
}
// ((Triforce) 11-24) The Audio tab's Output device row: the default, or one of the host's playback devices
// (host/audio_output_devices.c), told to the host by its endpoint id (host->audio_output_select), which the sound's thread
// opens at its next block. The choice is kept by that id, output_want, never by the device's place or its name (two devices
// can share one); also while it is unplugged: the row then has one more entry for it, "<name> (not connected)", the default
// stands in and the host tries it again. The options file's audio_output_device_id= and audio_output_device_name= (the name
// for that entry); the row's own number is not saved (ini_row). HOS_AUDIO_DEVICE over it for a run
struct OutputChoice { std::string id, name; };
std::vector<OutputChoice> output_devices;   // (as the host last listed them)
int output_pick = 0;                        // (the row: 0 the default, n the nth device, one past them the unplugged one)
std::string output_want, output_saved_name;
bool output_missing = false;
bool can_outputs() {
    return host && host->audio_output_count && host->audio_output_info && host->audio_output_select && host->audio_output_state;
}
bool output_forced() { const char* e = getenv("HOS_AUDIO_DEVICE"); return e && *e; }
/// An endpoint id as the file has it, or "" when it cannot be one: too long, or a control character in it
std::string output_id_key(const char* text) {
    std::string s(text ? text : "");
    while (!s.empty() && (s.back() == '\r' || s.back() == '\n')) s.pop_back();
    if (s.size() >= HOS_OUTPUT_ID_CAP) return std::string();
    for (const char c : s)
        if ((unsigned char)c < 0x20 || c == 0x7f) return std::string();
    return s;
}
const char* tx_output_device(int v) {
    static std::string text;
    if (output_forced()) return "Set by HOS_AUDIO_DEVICE";
    if (v <= 0) return "Default";
    if (output_missing && v == (int)output_devices.size() + 1) {
        text = (output_saved_name.empty() ? std::string("The chosen device") : output_saved_name) + " (not connected)";
        return text.c_str();
    }
    if ((size_t)(v - 1) >= output_devices.size()) return "Default";
    text = output_devices[(size_t)v - 1].name;
    int same = 0;   // (two devices of one name: their places as well)
    for (const auto& d : output_devices) same += d.name == text;
    if (same > 1) text += " [" + std::to_string(v) + "]";
    return text.c_str();
}
const char* hn_output_device(int, int variant) {
    if (variant > 0) return nullptr;
    if (variant < 0) return "Where the game plays its sound. A change restarts only the sound, at once.";
    if (output_forced()) return "HOS_AUDIO_DEVICE chooses the device for this run. The row's choice is kept.";
    const int state = can_outputs() ? host->audio_output_state() : 0;
    if (state & HOS_OUTPUT_UNAVAILABLE) return "No device could be opened. The game keeps trying.";
    if (output_missing || (state & HOS_OUTPUT_FALLBACK))
        return "The default plays for now. The chosen device is kept and tried again while the game runs.";
    return output_pick ? "This device, whatever the system's default is." : "The system's default playback device, as it changes.";
}
/// The Microphone row: Off, the default, a microphone of the list, or the chosen one while it is unplugged (variant 1)
const char* hn_mic(int v, int variant) {
    if (v <= 0) return variant <= 0 ? "The game hears silence." : nullptr;
    if (v == 1)
        return variant <= 0 ? "The system's default recording device. On Windows, desktop apps must be allowed to use the "
                              "microphone (Settings, Privacy & security)."
                            : nullptr;
    const bool missing = variant < 0 ? mic_missing && v == 2 + mic_listed : variant == 1;
    if (variant > 1) return nullptr;
    return missing ? "Not plugged in: Default stands in until it is back." : "This microphone, by its name. A change applies at once.";
}
// (Triforce) The Game language row. The game's language is the host's to read, once, at the start: language.txt in the
// game folder (host/nn_applet.c desired_language), which Setup writes at a build and which lists the game's languages;
// HOS_LANGUAGE goes over it for a run. The row's entries are the languages that file names (game_language.h), and a choice
// is written back into the file as its choice line, everything else in it as it was (lang_store, at each save). It is not
// kept in triforce_options.ini. No row while the file is not there or names nothing to choose from
namespace gl = game_language;
int lang_entries[gl::kCount];   // (the row's entries: places in gl::kLanguages, in its order)
int lang_count = 0;
int lang_saved = -1;            // (the entry language.txt chooses now: as read at the start, or as last written)
bool lang_failed = false;       // (the last choice could not be written: the row is back on the file's)
const char* tx_language(int v) {   // ((Triforce) each by its own name: Deutsch, Русский, 日本語, in any menu language)
    return lang_count > 0 ? i18n::game_lang_name(lang_entries[std::min(std::max(v, 0), lang_count - 1)]) : "";
}
/// The Game language: nothing about the value itself; variant 0: HOS_LANGUAGE decides for this run; variant 1: the choice
/// could not be written
const char* hn_language(int, int variant) {
    static const char* const env = "This run's language is set by HOS_LANGUAGE. The choice here is for runs without it.";
    static const char* const failed = "language.txt in the game folder could not be written: the language stays as it was.";
    if (variant < 0) {
        static const bool by_env = getenv("HOS_LANGUAGE") != nullptr;
        return lang_failed ? failed : by_env ? env : nullptr;
    }
    return variant == 0 ? env : variant == 1 ? failed : nullptr;
}
// ((Triforce) The Menu language row (opts.menu_lang): Auto, then each language by its own name (vk_menu_i18n.h). Not the
// game's: the menu's texts alone, at once)
const char* tx_menu_lang(int v) {
    if (v <= 0) return "Auto (game's language)";
    return i18n::lang_name(v - 1);
}
const char* hn_menu_lang(int v, int variant) {   // (a language of its own: the help says it all)
    return v <= 0 && variant <= 0 ? "Follows the game's language (language.txt in the game folder)." : nullptr;
}
const char* tx_rumble(int v) { return v ? tx_percent(v) : "Off"; }
// ((Triforce) 11-24) Vibration (host/vibration.h): what plays each controller. Auto plays the best a controller can do, Basic
// its motors, Off nothing; Rumble strength stays every backend's strength. The host writes back what plays the controller
// used last (HOS_OPT_VIBRATION_STATUS: its kind times 16, plus what it says), which the row's help line says.
const char* tx_vibration(int v) {
    static const char* t[] = {"Auto", "Basic", "Off"};
    return (unsigned)v < 3 ? t[v] : t[0];
}
std::atomic<int> vibration_status_cache{0};   // (no controller until the host reports)
int vibration_says() { return vibration_status_cache.load(std::memory_order_relaxed) % 16; }
const char* vibration_why(int s) {
    static const char* t[] = {
        "No controller is connected.", "Vibration is Off.", "Its two motors play the game's vibration.",
        "Its own HD rumble plays the game's vibration as it is.",
        "Its voice coils play the game's fine vibration, through its USB cable.",
        "Its voice coils play the game's fine vibration over Bluetooth.",
        "All four of its motors play, the triggers' too.",
        "RenHDrum makes its HD rumble.",
        "Its fine haptics play through the sound card it has on a USB cable, which was not found: its motors play "
        "meanwhile.",
        "Its fine haptics need RenHDrum beside the game (renhdrum.dll, or renhdrum.so on Linux), which is not there: its "
        "motors play.",
        "Its Bluetooth connection can't be written to here, so its motors play; on a USB cable, its voice coils play the "
        "game's fine vibration.",
        "Its grips play the game's fine vibration. Experimental: made from one person's measurements of the controller."};
    return (unsigned)s < sizeof t / sizeof t[0] ? t[s] : nullptr;
}
// ((Triforce) 11-24) the Controller speaker rows (host/pad_speaker.c): where each kind of sound plays, the sync, the headphones
const char* tx_pad_speaker(int v) { return v == 1 ? "Controller only" : v == 2 ? "Controller + TV" : "Off"; }
const char* tx_pad_headphones(int v) { return v == 1 ? "Controller sounds" : v == 2 ? "All sound" : "Off"; }
const char* tx_pad_sync(int v) {   // (above 0 the controller waits, below 0 the TV's copy of its sounds does)
    static char b[48];
    if (v < 0) snprintf(b, sizeof b, "TV waits %d ms", -v);
    else if (v > 0) snprintf(b, sizeof b, "Controller waits %d ms", v);
    else snprintf(b, sizeof b, "%d ms", 0);
    return b;
}
// (under the Vibration row's help: what plays the controller used last now; every one, for the help's height)
const char* hn_vibration(int v, int variant) {
    (void)v;
    return vibration_why(variant < 0 ? vibration_says() : variant);
}
const char* tx_volume(int v) { return v ? tx_percent(v) : "Muted"; }
const char* tx_menu_sounds(int v) { return v ? tx_percent(v) : "Off"; }   // (Triforce: the Menu sounds row)
const char* tx_sprint(int v) { return v == 1 ? "Left stick click" : v == 2 ? "B" : "Off"; }
const char* tx_sprint_mode(int v) { return v ? "Hold" : "Toggle"; }
// (hookshot) Menu size: how large the overlays are drawn (vk_ui.h unit); Auto is Large in fullscreen at 1080 lines and up while
// a controller is the menu's input, else Medium
bool pad_last = false;   // (a controller was the menu's last input: its buttons in the prompts)
// (Auto's choice: the controller or not, decided as the menu opens by the input that opened it. A controller's input makes it
// Large at any time; the keys and the mouse never make it smaller while the menu is open, so it never changes size under the
// cursor)
bool auto_pad = false;
int pad_confirm = 0, pad_back = 1;   // (the face buttons that confirm and go back, HOS_PAD_*: menu_keys::confirm_back, each tick)
bool auto_large(uint32_t h) { return opts.fullscreen && h >= 1080 && auto_pad; }
const char* tx_menu_size(int v) {
    static const char* t[] = {"Auto", "Small", "Medium", "Large"};
    if (v == 0) return auto_large(dev.swap_extent.height) ? "Auto (Large)" : "Auto (Medium)";
    return (unsigned)v < 4 ? t[v] : t[0];
}
// (Triforce) a stick's own dead zone: XInput's own (~24%, the default), or 0% to 50%. ((Triforce, options_version 7) The shared
// Stick dead zone row is gone: an older file's is each stick's own now, merged_rows.h migrate)
const char* tx_own_dead_zone(int v) { return v < 0 ? "Default (24%)" : tx_percent(v); }
// (Triforce) the Walk key row's keys, in host/nn_hid.c walk_key_code's order
const char* tx_walk_key(int v) {
    static const char* t[] = {"Off", "Caps Lock", "Shift", "Ctrl", "Tab"};
    return (unsigned)v < 5 ? t[v] : t[0];
}
// (hookshot) Audio output: the speakers the game mixes for, read once at its start (host/nn_audio.c au_menu_output)
const char* tx_audio_output(int v) {
    static const char* t[] = {"Auto", "Stereo", "5.1", "Mono"};   // ((Triforce) Mono: stereo's layout, averaged as it is mixed)
    return (unsigned)v < 4 ? t[v] : t[0];
}
// (hookshot) the motion's deadzone: the console's three zero-drift modes, the rate under which the pad counts as still
const char* tx_deadzone(int v) {
    static const char* t[] = {"Low", "Standard", "High"};
    return t[v < 0 ? 0 : v > 2 ? 2 : v];
}
const char* tx_robust(int v) {
    static const char* t[] = {"Auto", "Off", "On"};
    return (unsigned)v < 3 ? t[v] : t[0];
}
// ((Triforce, 11-24) the Debug tab's Compile shaders row (opts.compile_shaders; gpu/vk/compile_level.h)
const char* tx_compile_shaders(int v) { return v == 1 ? "Most" : "All"; }
MENU_HINTS(hn_compile_shaders, 0,
           "The shader preparation builds every pipeline it can before the title, as before: the longest preparation, the "
           "fewest compiles in play.",
           "The preparation leaves out the predicted pipelines (built behind the game while a menu or the title is shown) "
           "and the compute pipelines no list names: a shorter first preparation, and a short hitch where play first needs "
           "one of those.")
const char* tx_mesh(int v) { return v == 1 ? "Compute fallback" : "Auto"; }   // ((Triforce, 11-18) opts.mesh_mode, vk_main.cpp)
// (Triforce) The Debug tab's Replay helper threads row (opts.replay_threads; vk_replay.cpp par_threads_max): Off, or the
// parallel replay tried on 2 to 8 threads as RX_VK_PARALLEL_AUTO=<n> does. The switches go over the row for a run
const char* replay_threads_env() {
    static const char* const e = getenv("RX_VK_PARALLEL") ? "RX_VK_PARALLEL" : getenv("RX_VK_PARALLEL_AUTO") ? "RX_VK_PARALLEL_AUTO" : nullptr;
    return e;
}
const char* tx_replay_threads(int v) {
    // (Triforce: 8, Automatic, is the count replay_threads.h gives this PC, tried as the fixed counts are)
    static const char* const t[] = {"Off", "Auto, 2 threads", "Auto, 3 threads", "Auto, 4 threads", "Auto, 5 threads",
                                    "Auto, 6 threads", "Auto, 7 threads", "Auto, 8 threads", "Automatic"};
    static_assert(replay_threads_of(1) == 2 && replay_threads_of(7) == 8 && !replay_threads_of(0) && !replay_threads_of(8));
    static_assert(replay_threads::kRowAutomatic == 8 && replay_threads::of_row(8, 3) == 3 && replay_threads::of_row(7, 3) == 8);
    return t[(unsigned)v < sizeof t / sizeof t[0] ? v : 0];
}
/// Replay helper threads: variants 0 and 1: a switch decides for this run; variant 2, Automatic's own line (the row's value
/// unless the options file says otherwise, replay_threads.h)
const char* hn_replay_threads(int v, int variant) {
    static const char* const by_default = "The default. The log's \"replay helper threads\" line at the start says how many this PC "
                                          "gets, and its \"parallel replay, trial\" lines when they are in use.";
    static const char* const t[] = {"Set for this run by RX_VK_PARALLEL, whatever is chosen here.",
                                    "Set for this run by RX_VK_PARALLEL_AUTO, whatever is chosen here.", by_default};
    const bool automatic = v == replay_threads::kRowAutomatic;
    if (variant < 0) {
        const char* e = replay_threads_env();
        return e ? (!strcmp(e, "RX_VK_PARALLEL") ? t[0] : t[1]) : automatic ? t[2] : nullptr;
    }
    return variant < 2 || (variant == 2 && automatic) ? t[variant] : nullptr;
}
MENU_HINTS(hn_gpu, 0, "The best dedicated GPU.")
/// (Triforce) The Frame generation row's AMD FSR 4 (framegen_rows.h FSR4): what makes the frame, or, for a choice saved
/// where it could, why AMD's library cannot here (fsr4fg::why) and what makes the frame in its place. Variants: every line
/// it can show
const char* hn_framegen_fsr4(int variant) {
    // ((Triforce, FG-1, FG-2, FG-5) AMD's library of either version, the HUD kept out of what it moves, and paused while
    // HDR Native or RenoDX's RGBA16F scene holds it from every present (fsr4fg::held, not the HDR row alone: HDR Native
    // without an HDR display is no pause, and RenoDX's scene stays for the run whatever the row says now). There the
    // renderer's own makes the frame, as at 2x (framegen_rows.h held_made). The last variant is that pause)
    static const char* const ok = "One made frame between each two of the game's, by AMD's frame generation library (its version "
                                  "is on the row) from the scene's depth and motion, the HUD kept where the game drew it.";
    static const char* const native = "Paused with HDR Native or RenoDX: AMD's needs the picture without the HUD, which only the "
                                      "game encodes there. The renderer's own makes the one frame, as at 2x; HDR Expanded works.";
    static const char* const no[framegen_rows::FG_WHY_COUNT] = {
        nullptr,
        "AMD FSR is not in this build: the renderer's own makes the one frame, as at 2x.",
        "AMD's frame generation is switched off for this run (RX_VK_FSR4_FG=0 or RX_VK_FSR4=0): the renderer's own makes the frame.",
        "Not known yet: asked of AMD's library once the game's picture is up.",
        "AMD's files were not found beside the game: the renderer's own makes the one frame, as at 2x.",
        "AMD's frame generation library was not found beside the game: the renderer's own makes the frame.",
        "AMD's library has no frame generation for this GPU and driver: the renderer's own makes the frame.",
        "AMD's frame generation failed in this run (the log says where): the renderer's own makes the frame."};
    if (variant < 0) {
        const int w = (int)fsr4fg::why_known();   // ((Triforce) as known: "not known yet" until menu_ahead has asked)
        if (w == framegen_rows::FG_OK) return framegen_rows::held_whole_run(fsr4fg::held()) ? native : ok;
        return no[std::clamp(w, 1, (int)framegen_rows::FG_WHY_COUNT - 1)];
    }
    return variant == 0 ? ok : variant < (int)framegen_rows::FG_WHY_COUNT ? no[variant]
                                                                           : variant == (int)framegen_rows::FG_WHY_COUNT ? native : nullptr;
}
/// Frame generation: how many frames are made for each of the game's
const char* hn_framegen(int v, int variant) {
    if (v == framegen_rows::FSR4) return hn_framegen_fsr4(variant);   // (Triforce: AMD's library makes the frame)
    // ((Triforce) 11-24: by AMD FSR 3.1 where the Frame generation by row has it make them and it runs, from the scene's depth and
    // motion: vk_framegen.cpp. Variant 1 is the longest such text, for the menu's height)
    if (v >= 2 && v <= 8 && (variant < 0 ? fsr3fi::frames_wanted() != 0 : variant == 1)) {
        static char f[9][112];
        const int k = variant == 1 ? 8 : v;
        snprintf(f[k], sizeof f[k], "%s between each two of the game's, by AMD FSR 3.1 from the scene's depth and motion.",
                 k == 2 ? "One made frame" : k == 3 ? "Two made frames" : k == 4 ? "Three made frames" : k == 5 ? "Four made frames"
                 : k == 6 ? "Five made frames" : k == 7 ? "Six made frames" : "Seven made frames");
        return f[k];
    }
    if (variant > 0) return nullptr;
    if (v <= 0) return "Only the game's own frames: no added delay.";
    if (v == 1) return "A frame for each of the display's refreshes: none made when the game keeps up. Frame pacing does not apply.";
    static char b[9][96];
    snprintf(b[v], sizeof b[v], "%s between each two of the game's.", v == 2 ? "One made frame" : v == 3 ? "Two made frames" : v == 4 ? "Three made frames"
             : v == 5 ? "Four made frames" : v == 6 ? "Five made frames" : v == 7 ? "Six made frames" : "Seven made frames");
    return b[std::clamp(v, 2, 8)];
}
/// ((Triforce) 11-24) The Frame generation by row (opts.fg_by, framegen_rows.h BY_*): who makes the frames at Auto and 2x to 8x
const char* tx_fg_by(int v) { return v == framegen_rows::BY_FSR3 ? "AMD FSR 3.1" : "Triforce"; }
/// Its line: what makes them, and for AMD FSR 3.1 where it cannot run here, why (variants: every line it can show)
const char* hn_fg_by(int v, int variant) {
    static const char* const own = "Triforce's own interpolation, from the picture alone: the lightest on the GPU.";
    static const char* const fsr = "AMD FSR 3.1's frame interpolation, from the scene's depth and motion, the HUD kept still: "
                                   "less ghosting, more GPU time. Any GPU.";
    static const char* const cannot = "This GPU lacks what AMD FSR 3.1's passes need: Triforce's own makes the frames.";
    static const char* const native = "Paused with HDR Native: Triforce's own makes the frames, in their 10 bits.";
    if (variant >= 0) return variant == 0 ? own : variant == 1 ? fsr : variant == 2 ? cannot : variant == 3 ? native : nullptr;
    if (v != framegen_rows::BY_FSR3) return own;
    if (opts.hdr == 2) return native;   // (the picture is HDR Native's where the display has HDR: vk_fsr3fi.cpp frames_wanted)
    return !dev.device || fsr3fi::capable() ? fsr : cannot;
}
/// ((Triforce, options_version 7) The Frame generation row: the renderer's own and AMD FSR 4's (opts.framegen), then NVIDIA
/// DLSS 2x to 4x (opts.dlssg), which was a row of its own: merged_rows.h)
const char* tx_framegen_row(int v) {
    static const char* const dlss[] = {"NVIDIA DLSS 2x", "NVIDIA DLSS 3x", "NVIDIA DLSS 4x"};
    return v >= mr7::FG_DLSS ? dlss[std::clamp(v - mr7::FG_DLSS, 0, 2)] : tx_framegen(v);
}
/// Frame generation: the renderer's own and AMD FSR 4's lines (hn_framegen), and for NVIDIA DLSS what runs, or that it starts
/// with the next start (hn_dlssg)
const char* hn_framegen_row(int v, int variant) {
    if (v < mr7::FG_DLSS) return hn_framegen(v, variant);
    if (variant > 1) return nullptr;
    if (variant == 0) return "NVIDIA DLSS frame generation, from the scene's depth and motion, with NVIDIA Reflex: RTX 40 and 50 cards.";
    if (variant == 1) return hn_dlssg(1, 0);
    return mkwvk::dlssg::asked() ? mkwvk::dlssg::status() : "Starts with the next start of the game.";
}
MENU_HINTS(hn_output_res, 0, "The game's own size.",
           "The sharpest on a 2560x1440 screen: nothing to scale to the window.",
           "The sharpest on a 3840x2160 screen. The game's render targets get a bigger GPU pool, so a full-size 3D fits.",
           "The sharpest on a 1920x1080 screen: the HUD and text pixel for pixel, nothing to scale to the window.",
           "A 32:9 picture, the sharpest on a 5120x1440 ultrawide screen: pixel for pixel, the HUD in its 16:9 shape in the middle. The game's render targets get a bigger GPU pool, so a full-size 3D fits.",
           "The sharpest on a 5120x2880 (5K) screen: the whole frame pixel for pixel. The game's render targets get a bigger GPU pool, so a full-size 3D fits.",
           "A 21:9 picture, the sharpest on a 5120x2160 ultrawide screen: pixel for pixel, the HUD in its 16:9 shape in the middle. The game's render targets get a bigger GPU pool, so a full-size 3D fits.",
           "The game's handheld profile, as if the console were undocked: lighter on the graphics card, and softer.",
           "The size of the screen the game opens on, whatever its shape: pixel for pixel in fullscreen, the HUD in its 16:9 shape in the middle of a wider screen.",
           "A connected screen's own size, pixel for pixel in fullscreen there, or any size set with Output width and Output height below (HOS_OUTPUT_SIZE over them, when it is set): up to the pixels of 5120x2880, the HUD in its 16:9 shape in the middle of a wider picture.")
// ((Triforce, options_version 7) the Window scaling filter row is gone, and with it its hint: the sizes choose the filter,
// upscaler_rows.h window_filter. FSR 1's RCAS follows the Sharpness row: none at 0, vk_framegen.cpp framegen_scale)
/// Sharpness: off at 0; ((Triforce, S1, S7) else where it sharpens: the upscaler's 3D before the HUD (variant 1), or the
/// finished picture at the window (2). Variants: every line it can show
const char* hn_sharpness(int v, int variant) {
    static const char* const t[3] = {"Off: the picture as it is.",
                                     "The upscaler sharpens the 3D before the HUD: the HUD and text stay as they are.",
                                     "The finished picture at the window, the HUD and text with it."};
    if (variant < 0) variant = v == 0 ? 0 : temporal_sharpens_3d() ? 1 : 2;
    return variant < 3 ? t[variant] : nullptr;
}
MENU_HINTS(hn_ultrawide, 0, "The game's own shape.",
           "A 16:10 picture whatever the screen (as a 1920x1200 or 2560x1600 screen), the world a little narrower at the sides: "
           "the window opens in that shape, and a screen of another shape shows it between black bars.",
           "A 21:9 picture whatever the screen (64:27, as a 2560x1080 screen): the window opens in that shape, and a screen of "
           "another shape shows it between black bars. The HUD keeps its 16:9 shape in the middle.",
           "A 32:9 picture whatever the screen (as a 5120x1440 screen): the window opens in that shape, and a screen of "
           "another shape shows it between black bars. The HUD keeps its 16:9 shape in the middle.",
           // ((Triforce, 11-22, N64 Classic, step 6) the 1998 TV's shape)
           "A 4:3 picture whatever the screen, the shape of a TV of 1998: the world narrower at the sides, the HUD across its "
           "width, and a screen of another shape shows it between black bars. With N64 Classic, its 3D is 320 x 240.")
/// The Ultrawide row's line: its value's (variant 0), or what sets the shape in its place (shape_owner): the Output
/// resolution's own shape (1), HOS_ASPECT (2)
const char* hn_shape(int v, int variant) {
    if (variant < 0) variant = shape_owner();
    switch (variant) {
    case 0: return hn_ultrawide(v, 0);
    case 1:
        return "The Output resolution's own shape: its size is the whole picture, and the HUD keeps its 16:9 shape in the "
               "middle of a wider one. Nothing to set here; a 16:9 Output resolution takes its shape from this row.";
    case 2: return "Set for this run by HOS_ASPECT, whatever is chosen here.";
    default: return nullptr;
    }
}
const char* tx_wide_menus(int v) {
    static const char* t[] = {"Full width", "Centred, blurred sides", "Centred, black bars", "Extended"};
    return t[std::min(std::max(v, 0), 3)];
}
MENU_HINTS(hn_wide_menus, 0, "The menus stretched over the whole screen, as before.",
           "The menus in the middle 16:9; beside them, what the game draws there, out of focus.",
           "The menus in the middle 16:9; black beside them.",
           // ((Triforce) host/hos_wide_ui.c: the menus' layouts planned as the HUD's)
           "The menus at their 16:9 size, what sits at their sides moved out to the screen's edges.")
MENU_HINTS(hn_robust, 0, "Off, on every card.", "Can be faster on some NVIDIA cards.", "Always on.")
MENU_HINTS(hn_mesh, 0, "As the game finds best for this GPU: the fallback on AMD's RX 6000 driver, native mesh shaders elsewhere.",
           "Every mesh draw through compute shaders: a little slower. Try it if walls glow or the GPU stops responding on an AMD "
           "card. The shaders are prepared again once.")
MENU_HINTS(hn_fps, 0, nullptr, "With frame generation on, the game's own rate too.",
           "In the counter's place in the top right corner, a see-through panel: the GPU's and the CPU's load, temperatures and memory, "
           "the frame rate with its lows, the frame times and their graph, the waits per frame and the picture's settings. It "
           "measures only while it is shown.",
           // ((Triforce) the levels between On and Full, fps_levels.h: the values after Full's, shown before it)
           "The frame rate, and under it the frame time and the 1% low as a frame time.",
           "Frame time, and a graph of the last frames against the Frame rate cap's frame time.",
           "Graph, and where the frame's time goes: the game, the renderer, its waits for pipelines and shaders, and the GPU's time "
           "beside them.",
           "Breakdown, and the renderer's own numbers: video memory, draws, dispatches, passes and uploads a frame, pipelines built.")
/// (Triforce) The FPS counter row's third value, Full, after NX2navi's perf_overlay (off, fps, full): 0 and 1 are Off and
/// On as before. The row keeps its name, and with it its key in the options file (fps_counter)
const char* tx_perf(int v) { return fps_levels::name(v); }   // ((Triforce) and the levels between On and Full: fps_levels.h
MENU_HINTS(hn_menu_size, 0, "Large in fullscreen on a screen of 1080 lines or more while a controller is in use, else Medium.",
           "Smaller, for a desk.", "The usual size.", "Larger, for a TV across the room.")
MENU_HINTS(hn_speed, 0, "A step each frame: the game slows down whenever it runs below 60 fps.",
           "Normal speed down to 15 fps, by taking longer steps.")
MENU_HINTS(hn_text_speed, 0, "The game's own pace, with its pauses.", "Twice as fast.", "Four times as fast.",
           "Each page at once, as pressing A does.")
MENU_HINTS(hn_text_size, 0, "The game's own size.", "A little larger.", "Larger.", "Much larger.", "The largest.")
MENU_HINTS(hn_audio_output, 0, "5.1 when the output device has 5.1 or more speakers, else stereo.",
           "Stereo, whatever the device has.", "5.1, whatever the device has. Mixed down on stereo speakers.",
           "The same sound in both ears: the average of stereo's two channels. At once from Stereo; after a restart from 5.1.")
MENU_HINTS(hn_background, 0, "Only while the game's window has the focus.",
           "Also behind other windows, for streaming or other apps. The keyboard and mouse still need the game's window.")
MENU_HINTS(hn_mousecam, 0, "The mouse stands in for the right stick, with its curve and top speed.",
           "The mouse turns the camera itself, one to one, as in a PC game.",
           "The mouse plays no part: a click in the window does not capture it. For a controller or the keyboard alone.")
MENU_HINTS(hn_mouse_invert, 0, nullptr, "Moving the mouse forward tilts the camera down.")
MENU_HINTS(hn_gyro, 0, "The sticks alone aim.",
           "Switch Pro controllers and pads in Switch mode, DualSense and DualShock 4. The value says whether the "
           "connected pad has a gyroscope.")
MENU_HINTS(hn_pad_layout, 0, "The Switch's order: A on the right, B at the bottom, X at the top, Y on the left.",
           "A at the bottom (action and talk), B on the right, X on the left, Y at the top.",
           "A at the bottom, B on the right; X and Y as on the Switch.",
           "Bindings of your own, from the Controls page.")
// ((Triforce) Auto's choice is host/prompts.c auto_face's; the keyboard and mouse face is nx2/prompt_keys.py's)
MENU_HINTS(hn_prompts, 0,
           "Those of the first controller, from its name (SDL's); the Xbox's for a controller that has no name, as with "
           "XInput alone. When the game starts with no controller: those of the device you used last in the game before, "
           "the keys' and the mouse's the first time.",
           nullptr, nullptr, nullptr, nullptr, nullptr,
           "Each button shows the first key or mouse button bound to it on this page, moving shows the movement keys, and "
           "the camera shows the mouse. These menus show the buttons of a controller you use.")
// (Triforce) what each walk key is bound to out of the box (host/nn_hid.c key_default), which it stops pressing while chosen
MENU_HINTS(hn_walk_key, 0, "The movement keys always push the stick all the way: Link runs.",
           "Caps Lock presses no button by default. The system still switches capitals on and off with each press.",
           "Shift is B's key by default. While it is the walk key it does not press B: give B another key on the "
           "Controls page.",
           "Ctrl is the left stick press's key by default, which the Sprint button's Left stick click uses. While it is "
           "the walk key it does not press it.",
           "Tab is one of Plus's keys by default. While it is the walk key it does not press Plus; Enter still does.")
// (Triforce) the Lazy write-back row (vk_memory.cpp lazy_decide, wb_lazy_state.h choose)
// ((Triforce) the Threaded rendering row: Off, On, Auto (threaded_rendering.h's order)
const char* tx_threaded(int v) { return v == 2 ? "Auto" : tx_onoff(v); }
MENU_HINTS(hn_threaded, 0, "The game's own thread turns its commands into the graphics card's, as always.",
           "A render thread, a recorder thread and a present thread, whatever the processor.",
           "On with 4 processor cores or more; with no video memory mirrors only the recorder thread, from 6 cores.")
MENU_HINTS(hn_lazy_write_back, 0,"Copied back after every submission, as always.",
           "Copied back when it is read. Stays off with an AMD card's driver unless RX_VK_LAZY_WB=1 is set, and does nothing "
           "with no VRAM mirrors.")

// (Triforce) The cheats of the mods' cheat files (mods/<name>/cheats/<build id>.txt), which the host reads and runs
// (host/mod_cheats.c) and names for the menu at the first frame (menu_option_set: HOS_OPT_MODCHEAT_*). Each has a row on the
// System tab with the file's own name, On | Off as the toggles; the table below holds mod_cheat_rows::kSlots rows for them and
// a heading, not shown until the host has named its cheats (row_shown). A row has no value of the menu's: its switch is the
// list's, which the host asks for every frame (menu_take_mod_cheat) and keeps for the next start itself
mod_cheat_rows::List mod_cheats;
constexpr char kModCheatHeading[] = "Mod cheats";   // (the heading row's name in the table below: row_shown tells it by it)
constexpr char kModCheatHelp[] =
    "A cheat from a mod's cheat file, in the mods folder. On: its code runs once every frame of the game. Off at first; one you "
    "switch on stays on at the next start.";
/// A row's place among the mods' cheats (its name is the list's own), -1 for every other row
int mod_cheat_slot(const char* name) { return mod_cheats.slot_of(name); }
#define MOD_CHEAT_ROW(i) {TAB_SYSTEM, mod_cheats.names[i], nullptr, 0, 0, 0, nullptr, kModCheatHelp, nullptr, false, true},
#define MOD_CHEAT_ROWS8(i)                                                                                                  \
    MOD_CHEAT_ROW(i) MOD_CHEAT_ROW(i + 1) MOD_CHEAT_ROW(i + 2) MOD_CHEAT_ROW(i + 3) MOD_CHEAT_ROW(i + 4) MOD_CHEAT_ROW(i + 5)  \
    MOD_CHEAT_ROW(i + 6) MOD_CHEAT_ROW(i + 7)
static_assert(mod_cheat_rows::kSlots == 96, "MOD_CHEAT_ROWS8 below is used twelve times: a row for every slot");

// ((Triforce, options_version 7) The rows that each choose two saved values (merged_rows.h): their values as the rows show
// them, made from the saved ones before each tick and each drawing (merged_sync) and written back to them by set_row
// (merged_store). Never saved themselves (ini_row): the saved values keep their own keys, in the hidden rows below)
struct Merged {
    int hdr = 0, framegen = 0, pacing = 0, latency = 0;
    int vr_mode = 2, view3d = 0;   // ((Triforce VR) VR mode: vr_view with vr_camera; 3D Style's Mode: vr with flat3d)
};
Merged merged;
bool is_merged(const int* v) {
    return v == &merged.hdr || v == &merged.framegen || v == &merged.pacing || v == &merged.latency || v == &merged.vr_mode ||
           v == &merged.view3d;
}

// ((Triforce, options_version 7, the owner: "group them correctly, such as HDR should be its own group, the upscaling should be
// its own group, etc. Add the in-game filigree to group them, separate them") A group's heading: the game's separator with
// the group's title under it (ui::heading). The selection steps over it, the mouse has nothing on it, and it is hidden while
// every row of its group is (row_shown). The Debug tab has its own layout and its one heading, Developer (debug_rows)
#define MENU_HEADING(tab, title) {tab, title, nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true}
// (Triforce) Achievements (host/achievements.c keeps them, on unless HOS_ACHIEVEMENTS=0, and names them for the menu:
// menu_option_set, HOS_OPT_ACH_*; achievement_rows.h has the list). The System tab's Achievements row opens their page,
// kAchPage: every one with its icon, earned or not. The row is not shown until the host has named them (row_shown). One
// earned while the game runs has a notice at the top of the screen for a moment, draw_ach_notice
achievement_rows::List ach_list;
achievement_rows::View ach_view;
constexpr int kAchPage = 10;                // (page: see kModsPage)
constexpr char kAchRow[] = "View achievements";  // (the row's name in the table below: is_ach_row tells it by it)
constexpr int64_t kAchNoticeMs = 4000;      // (how long a notice stays: host/achievements.c waits a little longer between two)
int ach_columns = 2, ach_capacity = 8;      // (the page's cards as last drawn: the keys move by them)
int ach_notice = -1;                        // (the achievement the notice shows, -1 none)
int64_t ach_notice_at = 0;                  // (and since when, prof_now)
// (Triforce) Save files, as the Nintendo 64 game had them (host/save_files.c keeps them, on unless HOS_SAVE_FILES=0, and names
// them for the menu: menu_option_set, HOS_OPT_FILES_*; save_file_rows.h has the list). The game reads its saves once, at its
// start, so a file is a start: the game starts on the file played last and shows its title as ever, and the title's list has
// an entry of ours under Mods, Save Select (draw_files_row), which opens the file select, kFilesPage. There the file this
// run plays goes on at once; another is asked of the host and the game restarts on it. (It opened by itself over the
// title's list at first: he did not want that.) The System tab's Save files row opens the same page; not shown until the
// host has named the files
save_file_rows::List save_files;
constexpr int kFilesPage = 11;              // (page: see kModsPage)
constexpr char kFilesRow[] = "Save files";  // (the row's name in the table below: is_files_row tells it by it)
int files_choice = 0;                       // (the card chosen)
bool files_at_title = false;                // (the page was opened by the title, not by its row: Back and Play give the game its list)
int files_wait = -1;                        // (the file asked of the host, until it answers)
bool files_failed = false;                  // (the host could not keep the last choice)
bool is_files_row(const Row& r) { return r.tab == TAB_SYSTEM && !r.value && !strcmp(r.name, kFilesRow); }
/// The System tab's Achievements row: confirm opens their page
bool is_ach_row(const Row& r) { return r.tab == TAB_SYSTEM && !r.value && !strcmp(r.name, kAchRow); }
// ((Triforce, 11-22, N64 Classic, step 5) a row of the Remembered page: its value opts.n64_rem's, its range and step
// n64_rules.h kSpec's (its key kSpec's too, through ini_key's table of names), taken at once
#define N64_ROW(row, title, text, help)                                                                                       \
    {TAB_N64, title, &opts.n64_rem[n64_rules::row], n64_rules::kSpec[n64_rules::row].lo, n64_rules::kSpec[n64_rules::row].hi, \
     n64_rules::kSpec[n64_rules::row].step, text, help, nullptr, false, true}

constexpr char kUseWindowSize[] = "Use current window size";
Row rows[] = {
    // ---- Display ----
    MENU_HEADING(TAB_DISPLAY, "Screen"),
    {TAB_DISPLAY, "Fullscreen", &opts.fullscreen, 0, 1, 1, tx_onoff,
     "The game fills the whole screen, without the window's border. F10 and Alt+Enter do the same.", nullptr, false, true},
    {TAB_DISPLAY, "Fullscreen screen", &opts.fs_screen, 0, 15, 1, tx_fs_screen,
     "Which screen Fullscreen fills: Automatic, the one the window is on, or one of the connected screens. Changes at once.",
     nullptr, false, true},
    {TAB_DISPLAY, "Output resolution", &opts.output_res, 0, kLastOutput, 1, tx_output_res,
     "The picture's size, before it is scaled to the window: the fixed sizes, and the size of each connected screen by its "
     "name. A size that is not 16:9 is a wider or narrower picture: the HUD, menus and story movies keep their 16:9 shape at its "
     "height. Docked only. Applies after a restart.",
     hn_output_res, true},
    // ((Triforce) the Custom size's two sides, output_width= and output_height= by their names, shown while Custom or a
    // screen's size is chosen: row_shown. No line about the value: the Output resolution row above shows the size the game
    // makes of the two)
    {TAB_DISPLAY, kUseWindowSize, nullptr, 0, 0, 0, nullptr,
     "Copy the current window's pixel size to Custom. In fullscreen this uses the fullscreen size. Applies after a restart."},
    {TAB_DISPLAY, "Output width", &opts.output_width, OUTPUT_MIN_W, OUTPUT_MAX_W, 8, tx_custom_width,
     "The output resolution's width in pixels, where it is a screen's size or Custom; hold Left or Right to move faster, or type "
     "a number and press Enter. Output resolution shows the size the game takes: 5:4 to 48:9 in shape, at most the pixels of "
     "5120x2880. Applies after a restart.",
     nullptr, true},
    {TAB_DISPLAY, "Output height", &opts.output_height, OUTPUT_MIN_H, OUTPUT_MAX_H, 8, tx_custom_height,
     "The output resolution's height in pixels, where it is a screen's size or Custom; hold Left or Right to move faster, or type "
     "a number and press Enter. Output resolution shows the size the game takes: 5:4 to 48:9 in shape, at most the pixels of "
     "5120x2880. Applies after a restart.",
     nullptr, true},
    {TAB_DISPLAY, "GPU device", &opts.gpu_device, 0, 8, 1, tx_gpu,
     "Which graphics card the game runs on. Applies after a restart.", hn_gpu, true, true},
    MENU_HEADING(TAB_DISPLAY, "3D Style"),
    {TAB_DISPLAY, "Mode", &merged.view3d, 0, 11, 1, tx_view3d,
     "How the game is shown. Flatscreen: on the screen as usual. VR: in a VR headset through OpenXR (for example WiVRn on "
     "Linux, SteamVR or Meta's runtime on Windows), with the headset connected before the game starts; turning VR on or off "
     "applies after a restart. The rest are 3D on a flat screen without a headset. Red/cyan: glasses with a red and a cyan "
     "lens. Side by side (3D TV): each eye squeezed into its half, for a 3D TV's side by side mode. Crossed eyes: the right "
     "eye's picture on the left, for viewing with crossed eyes. Above and below: each eye in its half, one over the other. "
     "Side by side (Cardboard): each eye's whole picture in its own half, for a phone in a viewer such as Google Cardboard. "
     "VR + one of these: the headset as VR, and the desktop window showing the headset's two eyes in that 3D style (for a "
     "stream or someone watching with glasses).",
     nullptr, true, true},
    {TAB_DISPLAY, "3D Settings", nullptr, 0, 0, 0, nullptr,   // ((Triforce VR) opens the 3D Settings page, the TAB_3DPAGE rows)
     "Flat screen 3D: how strong the 3D is, and where the screen sits in it."},
    {TAB_DISPLAY, "VR Settings", nullptr, 0, 0, 0, nullptr,   // ((Triforce VR) opens the VR Settings page, the TAB_VRSET rows)
     "The headset: the VR mode, cutscenes, the HUD, the theater screen, the view and where your eyes sit."},
    // ((Triforce VR) the 3D Settings page
    {TAB_3DPAGE, "Depth", &opts.flat3d_depth, 0, 800, 10, tx_percent,
     "How strong the 3D is on the screen: the eyes' distance, 100% a person's (6.4 cm); the farther you sit from the screen, "
     "the more it takes. Not VR's Depth.", nullptr, false, true, -1,
     false, "flat3d_depth"},
    {TAB_3DPAGE, "Screen distance", &opts.flat3d_screen, 0, 2000, 10, tx_flat3d_screen,
     "How far into the world the screen sits: things nearer come out of it, farther ones stay behind it. Auto: at the nearest "
     "thing in the picture's middle, so the world sits behind the screen, as the 3DS does.", nullptr, false, true, -1, false,
     "flat3d_screen"},
    MENU_HEADING(TAB_DISPLAY, "Ultrawide"),
    {TAB_DISPLAY, "Aspect ratio", &opts.ultrawide, 0, 4, 1, tx_shape,
     "The picture's shape for a 16:9 Output resolution: the game's own 16:9, or a fixed 16:10, 21:9 or 32:9 at the same height, "
     "for a screen or a window of that shape, or 4:3, a TV's of 1998. A screen of another shape shows the picture between black bars. An Output "
     "resolution that is not 16:9 has its own shape, shown here. Applies after a restart.", hn_shape, true},
    // (Triforce: host/oot_wide_hud.c)
    // ((Triforce) Screen edges: host/hos_wide_ui.c plans the HUD's layouts for the picture at each present, so it changes at once)
    {TAB_DISPLAY, "HUD position", &opts.wide_hud, 0, 1, 1, tx_wide_hud,
     "With a picture wider than 16:9: where corner HUD elements, tips and notices sit. Middle: in the "
     "middle 16:9, as on a normal screen. Screen edges: out in the screen's corners. Changes at once.", nullptr,
     false, true},
    {TAB_DISPLAY, "Menu sides", &opts.wide_menus, 0, 3, 1, tx_wide_menus,   // ((Triforce) 3 Extended: host/hos_wide_ui.c)
     "With a picture wider than 16:9: the pause, item and map menus, and what shows beside them. Loading screens and story movies, "
     "which draw no world either, get the same sides (the title's movie fills the picture up to 12:5); a fade always covers the "
     "whole screen. Changes at once.", hn_wide_menus},
    // ((Triforce) the HUD's three groups moved and sized, on a 16:9 or wider picture: host/hos_wide_ui.c, changes at once)
    MENU_HEADING(TAB_DISPLAY, "HUD"),
    {TAB_DISPLAY, "HUD placement", &opts.hud_placement, 0, 1, 1, tx_hud_placement,
     "Where the hearts, the buttons and the minimap sit in play. Custom moves and resizes each group. Changes at once.",
     hn_hud_placement, false, true},
    {TAB_DISPLAY, "Hearts and magic across", &opts.hud_health_x, -15, 15, 1, tx_percent,
     "Moves the hearts and magic left or right, as a share of the picture's width.", nullptr, false, true},
    {TAB_DISPLAY, "Hearts and magic up", &opts.hud_health_y, -15, 15, 1, tx_percent,
     "Moves the hearts and magic down or up, as a share of the picture's height.", nullptr, false, true},
    {TAB_DISPLAY, "Hearts and magic size", &opts.hud_health_scale, 75, 125, 1, tx_percent,
     "Resizes the hearts and magic together.", nullptr, false, true},
    {TAB_DISPLAY, "Buttons across", &opts.hud_buttons_x, -15, 15, 1, tx_percent,
     "Moves the action prompts and the item buttons left or right, as a share of the picture's width.", nullptr, false, true},
    {TAB_DISPLAY, "Buttons up", &opts.hud_buttons_y, -15, 15, 1, tx_percent,
     "Moves the action prompts and the item buttons down or up, as a share of the picture's height.", nullptr, false, true},
    {TAB_DISPLAY, "Buttons size", &opts.hud_buttons_scale, 75, 125, 1, tx_percent,
     "Resizes the action prompts and the item buttons together.", nullptr, false, true},
    {TAB_DISPLAY, "Minimap across", &opts.hud_minimap_x, -15, 15, 1, tx_percent,
     "Moves the minimap left or right, as a share of the picture's width.", nullptr, false, true},
    {TAB_DISPLAY, "Minimap up", &opts.hud_minimap_y, -15, 15, 1, tx_percent,
     "Moves the minimap down or up, as a share of the picture's height.", nullptr, false, true},
    {TAB_DISPLAY, "Minimap size", &opts.hud_minimap_scale, 75, 125, 1, tx_percent, "Resizes the minimap.", nullptr, false, true},
    MENU_HEADING(TAB_DISPLAY, "HDR"),
    // (HDR and RenoDX HDR in one row: merged_rows.h. Off, Expanded and Native change at once, as the HDR row did; Native +
    // RenoDX, which the scene's format and RenoDX's shaders are chosen for at the start (host/nn_vi.c hos_scene_rgba16f),
    // after a restart: restart_value_of)
    {TAB_DISPLAY, "HDR", &merged.hdr, 0, 3, 1, tx_hdr_mode,
     "HDR10 on an HDR display (Windows: Use HDR on in the display settings). Native + RenoDX applies after a restart.",
     hn_hdr_mode, true, true},
    {TAB_DISPLAY, "Paper white", &opts.hdr_white, 80, 400, 10, tx_nits,
     "How bright white is: around 200 nits for a normal room, higher for a bright one.", nullptr, false, true},
    // (Triforce: up to HDR10's own 10,000 nits, as NX2navi's hdr_peak_nits; it stopped at 4,000. Every reader takes that much)
    {TAB_DISPLAY, "Peak brightness", &opts.hdr_peak, 400, 10000, 100, tx_nits,
     "The brightest highlights: set it to your display's peak brightness.", nullptr, false, true},
    {TAB_DISPLAY, "UI brightness", &opts.rdx_ui_white, 80, 400, 10, tx_nits,
     "How bright the HUD's and the menus' white is with RenoDX. The scene's white is Paper white.", nullptr, false, true},
    // (local, RenoDX port: vk_renodx.cpp. Shown with HDR Native + RenoDX, where its shaders run; the rows of one tone mapper
    // while it is chosen, rdx_applies. Ranges and steps as NX2navi's menu has them)
    MENU_HEADING(TAB_DISPLAY, "RenoDX"),
    {TAB_DISPLAY, "Tonemapper", &opts.rdx_tonemap, 0, 2, 1, tx_rdx_tonemap,
     "How the scene's light is brought to the display. Vanilla: the game's own curve. PsychoV35: keeps hue and saturation "
     "into the highlights. RenoDRT: carries the game's SDR look up to the peak brightness.", nullptr, false, true},
    {TAB_DISPLAY, "Gamma correction", &opts.rdx_gamma, 0, 2, 1, tx_rdx_gamma,
     "Shows the picture as a 2.2 or BT.1886 (2.4) display would, as the game was made to be seen: darker shadows. Off keeps "
     "the sRGB curve.", nullptr, false, true},
    {TAB_DISPLAY, "Color space", &opts.rdx_space, 0, 2, 1, tx_rdx_space,
     "The colors the picture is taken to be in. Vanilla: the game's own. BT.709: as the SDR picture. DCI-P3: more "
     "saturated.", nullptr, false, true},
    {TAB_DISPLAY, "Exposure", &opts.rdx_exposure, 0, 200, 5, tx_percent,
     "The scene's brightness before tone mapping. 100% is the game's.", nullptr, false, true},
    {TAB_DISPLAY, "Middle gray", &opts.rdx_midgray, 0, 2, 1, tx_rdx_midgray,
     "What the scene's middle gray is held to. Render: as rendered. Vanilla: where the game's curve puts it. Eye "
     "adaptation: it follows what is on screen over a few seconds.", nullptr, false, true},
    {TAB_DISPLAY, "Match tone slope", &opts.rdx_match_slope, 0, 1, 1, tx_onoff,
     "PsychoV35: the mid tones get the contrast of the game's own curve. Off: PsychoV35's own, softer.", nullptr, false, true},
    {TAB_DISPLAY, "Tone slope", &opts.rdx_tone_slope, 0, 100, 1, tx_rdx_grade,
     "PsychoV35: how steep the tone curve is through middle gray. 50 leaves it unchanged.", nullptr, false, true},
    {TAB_DISPLAY, "Hue clip", &opts.rdx_hue_clip, 0, 100, 5, tx_percent,
     "PsychoV35: how much bright colors turn as they do where the SDR picture clips, fire towards yellow and white. 0% "
     "keeps their hue.", nullptr, false, true},
    {TAB_DISPLAY, "Highlight saturation", &opts.rdx_highlight_sat, 0, 100, 1, tx_rdx_grade,
     "RenoDRT: how strong the colors of the brightest parts are. 50 leaves them unchanged.", nullptr, false, true},
    {TAB_DISPLAY, "Blowout", &opts.rdx_blowout, 0, 100, 1, tx_rdx_grade,
     "RenoDRT: turns the brightest parts towards white. 0 keeps their color.", nullptr, false, true},
    {TAB_DISPLAY, "Flare", &opts.rdx_flare, 0, 100, 1, tx_rdx_grade,
     "RenoDRT: lifts the darkest parts as a little stray light would. 0 keeps black black.", nullptr, false, true},
    {TAB_DISPLAY, "Hue correction", &opts.rdx_hue, 0, 100, 5, tx_percent,
     "RenoDRT: how much bright colors keep the hue they had before tone mapping.", nullptr, false, true},
    {TAB_DISPLAY, "Color grading", &opts.rdx_grade, 0, 100, 5, tx_percent,
     "RenoDRT: how much of the game's own color grading is kept. 0% is the scene without it.", nullptr, false, true},
    {TAB_DISPLAY, "Highlights", &opts.rdx_highlights, 0, 100, 5, tx_rdx_grade,
     "The bright parts of the scene. 50 is neutral.", nullptr, false, true},
    {TAB_DISPLAY, "Shadows", &opts.rdx_shadows, 0, 100, 5, tx_rdx_grade,
     "The dark parts of the scene. 50 is neutral.", nullptr, false, true},
    {TAB_DISPLAY, "Contrast", &opts.rdx_contrast, 0, 100, 5, tx_rdx_grade, "The scene's contrast. 50 is neutral.", nullptr,
     false, true},
    {TAB_DISPLAY, "Saturation", &opts.rdx_saturation, 0, 100, 5, tx_rdx_grade, "The scene's color. 50 is neutral.",
     nullptr, false, true},
    {TAB_DISPLAY, "Bloom", &opts.rdx_bloom, 0, 100, 5, tx_rdx_grade,
     "The glow around bright things. 50 is the game's. RenoDX is by Carlos Lopez (clshortfuse), under the MIT license.",
     nullptr, false, true},
    // ((Triforce) 11-24) the picture's colours for a colour vision deficiency (vk_framegen.cpp framegen_scale). Taken at once
    MENU_HEADING(TAB_DISPLAY, "Accessibility"),
    {TAB_DISPLAY, "Color vision correction", &opts.colour_vision, 0, 3, 1, tx_colour_vision,
     "Recolors the finished picture for red-green or blue-yellow color vision deficiency, keeping its brightness. Not with "
     "HDR Native. Changes at once.", hn_colour_vision, false, true},
    MENU_HEADING(TAB_DISPLAY, "Overlay"),
    // (Triforce, after NX2navi's perf_overlay: a third value, Full, NX2navi's full performance overlay: perf_sample, draw_perf)
    {TAB_DISPLAY, "FPS counter", &opts.show_fps, 0, fps_levels::kMax, 1, tx_perf,
     "Frames per second in the top right corner. Full: a performance panel in its place: the GPU's and the CPU's load, "
     "temperatures and memory, the frame rate and its lows, the frame times and their graph, the waits per frame and the "
     "picture's settings.", hn_fps, false, true},

    // ---- Graphics: the picture, top to bottom ----
    // ((Triforce, 11-23) Evil HD, the owner's one switch for a powerful PC: evil_hd.h. First, over the rows it stands for)
    MENU_HEADING(TAB_GRAPHICS, "Evil HD"),
    {TAB_GRAPHICS, "Evil HD", &opts.evil_hd, 0, 1, 1, tx_onoff,
     "The fullest picture the game can give, for a powerful PC: SMAA Ultra edges, 16x texture filtering, every texture whole, "
     "the shadows of distant grass and leaves as the game draws them, and soft shadows in corners and creases (ambient "
     "occlusion), and the grass, plants, flowers and stones drawn 4 times as far (in the areas you enter after it is turned on). "
     "Your own choices in those rows come back when it is off. F2 turns it on and off.", hn_evil_hd, false, true},
    // ((Triforce) Auto (this PC): auto_settings.h, auto_apply. Off by default: nothing set, nothing tuned)
    MENU_HEADING(TAB_GRAPHICS, "This PC"),
    {TAB_GRAPHICS, "Auto (this PC)", &opts.auto_pc, 0, 1, 1, tx_onoff,
     "On: the Upscaler, Render resolution, Texture detail, Shadow resolution and Grass distance are set for this PC's graphics "
     "card, memory and processor, and adjusted in the first minutes of play to hold the Frame rate cap. Changing one of those "
     "rows yourself turns it Off. The Render resolution and Upscaler apply after a restart.", hn_auto_pc, false, true},
    MENU_HEADING(TAB_GRAPHICS, "Upscaling"),
    // (the Upscaler only in a build with DLSS or FSR 4, or where AMD FSR 3.1 runs: row_shown. An engine's native anti-aliasing
    // is the Render resolution's Native (100%), upscaler_rows.h)
    {TAB_GRAPHICS, "Upscaler", &opts.dlss, 0, ur::kUpscalers - 1, 1, tx_upscaler, "What draws the 3D up to the Output resolution.",
     hn_upscaler},
    {TAB_GRAPHICS, "DLSS model", &opts.dlss_model, 0, ur::kModels - 1, 1, tx_dlss_model,
     "Which of NVIDIA's DLSS networks draws the picture.", hn_dlss_model, false, true},
    {TAB_GRAPHICS, "FSR 4 model", &opts.fsr4_model, 0, ur::kFsr4Models - 1, 1, tx_fsr4_model,   // ((Triforce))
     "The FSR 4 network: Auto lets AMD pick for this GPU, Lite is the faster INT8 network.", hn_fsr4_model, false, true},
    // (Triforce: read once, at the start (host/nn_vi.c): Auto -> 100% in game left the 3D at the dynamic path's size)
    {TAB_GRAPHICS, "Render resolution", &opts.resolution, 0, ur::kValues - 1, 1, tx_resolution,
     "The size the 3D is drawn at; the upscaler fills in the rest. Applies after a restart.", hn_resolution, true},
    // (Triforce, 11-13: vk_temporal.cpp pre_wanted. Shown with DLSS or FSR: row_shown)
    {TAB_GRAPHICS, "Upscale before bloom", &opts.upscale_pre, 0, 1, 1, tx_onoff,
     "On: the upscaler works on the scene before the game's glow and tone mapping, which are then made at full size. "
     "Evil HD's ambient occlusion and light shafts are not drawn with this on. Applies after a restart.", nullptr, true, true},
    {TAB_GRAPHICS, "Sharpness", &opts.sharpness, 0, 100, 10, tx_percent,
     "With DLSS, DLAA or AMD FSR as the Upscaler, the 3D before the HUD (FSR's own sharpening; AMD's RCAS for DLSS); with "
     "the game's own upscaler, the picture at the window. 0 is off. Too much shows halos around edges.", hn_sharpness},
    // (Triforce, after NX2navi's aa setting: aa_rows.h, vk_aa.cpp. Taken at each frame. Shown with the game's own upscaler:
    // DLSS and FSR smooth the edges themselves)
    MENU_HEADING(TAB_GRAPHICS, "Anti-aliasing"),
    {TAB_GRAPHICS, "Anti-aliasing", &opts.aa, 0, aa_rows::kValues - 1, 1, tx_aa,
     "How the 3D's edges are smoothed: the game's own SMAA, none, FXAA, or SMAA at its Ultra preset. Changes at once.", hn_aa,
     false, true},
    // ((Triforce, 11-22, N64 Classic, step 5) the 1998 look (n64_rules.h, vk_n64.cpp): Off, Faithful (fixed), Remembered (its
    // page). Taken at each frame; F7 turns it between Off and the last preset (n64_classic_last); RX_VK_N64 over it
    MENU_HEADING(TAB_GRAPHICS, "N64 Classic"),
    {TAB_GRAPHICS, "N64 Classic", &opts.n64_classic, 0, n64_rules::kPresets - 1, 1, tx_n64,
     "The game as the 1998 cartridge on a TV of then. F7 turns it on and off. Changes at once.", hn_n64, false, true},
    {TAB_GRAPHICS, "Remembered settings", nullptr, 0, 0, 0, nullptr,   // (opens the Remembered page, the TAB_N64 rows)
     "Remembered's frame rate, its 3D and its TV, each to your taste."},
    // (the Remembered page (TAB_N64), which Remembered settings opens: Remembered's own look and pace, every row taken at
    // once. N64_ROW takes each row's range, step and key from n64_rules.h kSpec; row_fixed greys those with nothing to do)
    MENU_HEADING(TAB_N64, "Pace"),
    N64_ROW(FPS, "Frame rate", tx_n64_fps,
            "How many frames a second the game runs at with Remembered: the Frame rate cap's, or fewer. 20 is the 1998 "
            "cartridge's, 17 its own on a 50 Hz TV. Movies keep the cap's."),
    MENU_HEADING(TAB_N64, "The 3D"),
    N64_ROW(LINES, "3D resolution", tx_n64_lines, "How many lines the 3D is drawn on. 240 is the console's; more is sharper."),
    N64_ROW(COLOUR, "Colour", tx_n64_colour, "How many colours the 3D has. 15-bit is the console's 16-bit picture."),
    N64_ROW(DITHER, "Dither", tx_n64_dither,
            "The fine pattern that hides the steps between fewer colours. Nothing to dither with full colour."),
    N64_ROW(BLUR, "Texture blur", tx_n64_blur,
            "How much less detail the textures show, in steps of half a mip level, as the console's small textures did."),
    MENU_HEADING(TAB_N64, "The TV"),
    N64_ROW(TV, "CRT TV", tx_onoff, "The TV over the picture. Off: the 3D's look alone, for a real CRT or a capture card."),
    N64_ROW(SCANLINES, "Scanlines", tx_percent, "How dark the gaps between the TV's lines are."),
    N64_ROW(MASK, "Mask", tx_n64_mask,
            "The pattern of the TV's red, green and blue phosphors. Auto: the slot mask on a picture 1440 lines tall or more, "
            "none on smaller screens."),
    N64_ROW(MASK_STRENGTH, "Mask strength", tx_percent, "How strongly the mask shows."),
    N64_ROW(BLEED, "Colour bleed", tx_n64_bleed, "Colour smeared sideways, as a composite cable carried it; brightness stays sharp."),
    N64_ROW(GLOW, "Glow", tx_percent, "Light glowing around the bright parts of the picture."),
    N64_ROW(CURVATURE, "Curvature", tx_n64_curve, "How curved the screen is. A curved one has darker, rounded corners."),
    N64_ROW(SATURATION, "Colour saturation", tx_percent, "How rich the colours are. 100% is the game's."),
    MENU_HEADING(TAB_N64, "Start again"),
    {TAB_N64, "Copy Faithful", nullptr, 0, 0, 0, nullptr, "Remembered set to Faithful's values: a start for your own."},
    {TAB_N64, "Reset to defaults", nullptr, 0, 0, 0, nullptr, "Remembered as it was at first."},
    // ((Triforce, 11-24) the Simulated turf page (TAB_SIM_TURF), which Simulated turf opens: each area's own values, or
    // multipliers of every area's. Each change at once, kept in sim_turf_settings.ini (vk_sim_turf.cpp takes the rows' changes)
    {TAB_SIM_TURF, "Use global multipliers", &sim_turf_settings::global, 0, 1, 1, tx_onoff,
     "On: every area's own simulated turf scaled by the four multipliers below (1.0x is the area's own). Off: this area's own "
     "values, set one by one.", nullptr, false, true},
    {TAB_SIM_TURF, "Fade start multiplier", &sim_turf_settings::multipliers[0], 0, 100, 1, sim_turf_text_multiplier,
     "Scales each area's fade start within the game's fade range.", nullptr, false, true},
    {TAB_SIM_TURF, "Turf density multiplier", &sim_turf_settings::multipliers[1], 0, 100, 1, sim_turf_text_multiplier,
     "Scales each area's simulated turf density. 0.0x leaves almost none.", nullptr, false, true},
    {TAB_SIM_TURF, "Minimum blades multiplier", &sim_turf_settings::multipliers[2], 0, 100, 1, sim_turf_text_multiplier,
     "Scales each area's fewest simulated turf blades, rounded to a whole blade.", nullptr, false, true},
    {TAB_SIM_TURF, "Far power multiplier", &sim_turf_settings::multipliers[3], 0, 100, 1, sim_turf_text_multiplier,
     "Scales how quickly each area's simulated turf thins with distance.", nullptr, false, true},
    {TAB_SIM_TURF, "Fade start", &sim_turf_settings::values[0], 0, 649, 1, sim_turf_text_fade,
     "How far away the simulated turf begins to fade. 0 with Minimum blades 0: none in this area, for a slower PC.",
     hn_sim_turf_area, false, true},
    {TAB_SIM_TURF, "Turf density", &sim_turf_settings::values[1], 1, 500, 1, sim_turf_text_count,
     "How densely the simulated turf is laid. The game divides by it: lower is denser.", hn_sim_turf_area, false, true},
    {TAB_SIM_TURF, "Minimum blades", &sim_turf_settings::values[2], 0, 128, 1, sim_turf_text_count,
     "The fewest blades the simulated turf keeps as it thins with distance.", hn_sim_turf_area, false, true},
    {TAB_SIM_TURF, "Far power", &sim_turf_settings::values[3], 0, 400, 5, sim_turf_text_power,
     "How the simulated turf's density falls with distance.", hn_sim_turf_area, false, true},
    {TAB_SIM_TURF, "Reset current area", nullptr, 0, 0, 0, nullptr,
     "This area's edits gone: the game's own simulated turf here again.", hn_sim_turf_reset},
    MENU_HEADING(TAB_GRAPHICS, "Frame generation"),
    // (Frame generation and DLSS frame generation in one row, merged_rows.h: the renderer's own, AMD FSR 4 where its library
    // makes the frames, NVIDIA DLSS where it can run (vk_dlssg.cpp: read at the start, so it takes a restart))
    {TAB_GRAPHICS, "Frame generation", &merged.framegen, 0, mr7::FG_DLSS_LAST, 1, tx_framegen_row,
     "Makes frames between the game's own, for smoother motion, at a little input delay. Fast motion and camera cuts can "
     "show artifacts. NVIDIA DLSS applies after a restart.", hn_framegen_row, true, true},
    // ((Triforce) 11-24) who makes them at Auto and 2x to 8x: the renderer's own (the default, as before) or AMD FSR 3.1's frame
    // interpolation, vk_fsr3fi.h. Shown with those values alone (row_shown)
    {TAB_GRAPHICS, "Frame generation by", &opts.fg_by, 0, framegen_rows::kByMax, 1, tx_fg_by,
     "Who makes the frames at Auto and 2x to 8x.", hn_fg_by, false, true},
    MENU_HEADING(TAB_GRAPHICS, "Frame rate & latency"),
    {TAB_GRAPHICS, "Frame rate cap", &opts.fps_cap, -3, 7, 1, tx_fps_cap,   // (6: Monitor's rate, 7: Uncapped, fps_cap.h)
     "The most frames the game renders a second; made frames come on top. 60 is the safe choice: past it some cutscenes and "
     "bosses can misbehave. 30, 40 and 45 are for a PC that holds one of them where 60 swings. Monitor's rate: the refresh "
     "rate of the screen the game starts on. Uncapped: as fast as the PC can, still at real time; with VSync on, the screen's "
     "refresh rate is the limit. Changes at once.", nullptr, false, true},
    // (Triforce, after NX2navi's VSync switch: the swapchain's present mode, made again at once. present_mode.h, vk_main.cpp)
    {TAB_GRAPHICS, "VSync", &opts.vsync, 0, 2, 1, tx_vsync,
     "Whether a finished frame waits for the screen's next refresh. Off: a little less delay, and the picture can tear. "
     "Every refresh: always the screen's own pacing (FIFO), for a display that tears or stutters otherwise. Changes at once.", hn_vsync, false, true},
    // (Frame pacing and Steady frame rate in one row, merged_rows.h: host/pace_steady.h, host/nn_vi.c steady_period)
    {TAB_GRAPHICS, "Frame pacing", &merged.pacing, 0, 3, 1, tx_pacing,
     "When each frame is shown. Steady paces the game to a rate this PC holds where you are: steadier, at some frame rate.",
     hn_pacing, true},
    // (NVIDIA Reflex and AMD Anti-Lag 2 in one row, by the card's maker, merged_rows.h; none where neither runs)
    {TAB_GRAPHICS, "Low latency", &merged.latency, 0, 2, 1, tx_latency,
     "Each frame starts as late as it can, for less input delay: NVIDIA Reflex on NVIDIA cards, AMD Anti-Lag 2 on AMD ones.",
     hn_latency},
    MENU_HEADING(TAB_GRAPHICS, "Textures"),
    {TAB_GRAPHICS, "Texture filtering", &opts.aniso, 0, 4, 1, tx_aniso,   // (Triforce: vk_draw.cpp sampler_for)
     "Keeps ground, paths and walls sharp where they slope away from the camera. Game: what the game asks for; 16x is the "
     "sharpest, at a small cost.", hn_aniso},
    // (Triforce, after NX2navi's texture_detail: tex_detail.h, vk_texture.cpp texture_detail_level. Read at the first texture)
    {TAB_GRAPHICS, "Texture detail", &opts.tex_detail, 0, 3, 1, tx_tex_detail,
     "How large the game's textures are kept in video memory. Automatic suits the graphics card. Applies after a restart.",
     hn_tex_detail, true},
    // ((Triforce) 11-24) the ReShade presets (reshade_menu.h, reshade/fx_runtime.cpp): Off, the default, runs nothing. The User
    // preset file and Rescan rows with User chosen (row_shown); the file itself is the game folder's reshade/selected.txt
    MENU_HEADING(TAB_GRAPHICS, "Post-processing"),
    {TAB_GRAPHICS, "ReShade preset", &opts.reshade, 0, reshade::last_builtin_preset, 1, reshade_menu::tx_preset,
     "Native HDR supports built-in and LinearHDR presets. Use Expanded HDR for imported SDR presets.", reshade_menu::hn_preset,
     false, true},
    {TAB_GRAPHICS, kReshadeCompare, nullptr, 0, 0, 0, nullptr, "Preview presets. Back restores your saved selection."},
    {TAB_GRAPHICS, "User preset file", &reshade_menu::user_pick, 0, 0, 1, reshade_menu::tx_user,
     "Copy INI files to reshade/presets and FX and FXH files to reshade/shaders, then rescan.", nullptr, false, true},
    {TAB_GRAPHICS, kReshadeRescan, nullptr, 0, 0, 0, nullptr,
     "Refreshes the user preset list and reloads the selected file."},
    // ((Triforce) 11-24) how far and how fine the scene's details go: the short grass's reach (vk_draw.cpp grass_reach) and the
    // sun's shadow maps (host/oot_shadow.c, HOS_OPT_SHADOW_RES). Both taken at once; Game's, the default, is as shipped
    MENU_HEADING(TAB_GRAPHICS, "Detail"),
    {TAB_GRAPHICS, "Grass distance", &opts.grass_distance, 0, 3, 1, tx_grass_distance,
     "How far away short grass blades reach, such as Kokiri Forest's tufts and the moss on its stones. The game stops them at "
     "about 20 m. Higher extends their reach for some GPU time. Changes at once."},
    // ((Triforce, 11-24) opens the Simulated turf page, the TAB_SIM_TURF rows: vk_sim_turf.cpp, sim_turf_settings.h)
    {TAB_GRAPHICS, "Simulated turf", nullptr, 0, 0, 0, nullptr,
     "The broad field grass the game's wind and fluid simulation moves: the dense carpet that bends and ripples around Link. "
     "Its fade, density and blades, area by area. Grass distance is the separate short blades."},
    {TAB_GRAPHICS, "Shadow resolution", &opts.shadow_res, 0, 2, 1, tx_shadow_res,
     "The size of the sun's shadow maps: higher keeps the shadows of thin things near you, such as chains, fences and leaves, "
     "smooth instead of stair-stepped, for more video memory and a little GPU time. Highest also makes them shimmer less while "
     "the camera moves. Changes at once.",
     hn_shadow_res},
    // ((Triforce, 11-18, v0.5.1) a player's RX 7700S: glowing doors and walls with native mesh shaders, gone with the compute
    // fallback (#bug-tracker). The row's key, mesh_shaders, is read where the device is made: vk_main.cpp. Its own group, as
    // v0.5.1's Advanced section had it, after the picture's)
    MENU_HEADING(TAB_GRAPHICS, "Advanced"),
    {TAB_GRAPHICS, "Mesh shaders", &opts.mesh_mode, 0, 1, 1, tx_mesh,
     "How the game's mesh-shader draws run. Try Compute fallback on an AMD card that shows glowing walls or loses the GPU. "
     "Applies after a restart.", hn_mesh, true},

    // ---- System ----
    // ((Triforce) 11-23, his "can we move [achievements] to a more pronounced place for people to find (and disable or
    // enable)": a group of their own, the tab's first. The list's page (host/achievements.c's list; shown once the host has
    // named it), whether anything is earned, and whether one earned shows its notice. They were a row under Saves &
    // reports, and off only by HOS_ACHIEVEMENTS=0 in triforce_env.txt)
    MENU_HEADING(TAB_SYSTEM, "Achievements"),
    {TAB_SYSTEM, "View achievements", nullptr, 0, 0, 0, nullptr,   // (kAchRow)
     "Every achievement, and the ones you have earned. They are earned as you play; nothing is set here."},
    {TAB_SYSTEM, "Achievements", &opts.achievements, 0, 1, 1, tx_onoff,
     "Whether things you do in the game are marked as earned. Off: nothing is checked or earned, and what you have earned "
     "is kept.", nullptr, false, true},
    {TAB_SYSTEM, "Achievement notices", &opts.achievement_notices, 0, 1, 1, tx_onoff,
     "Whether a notice and a sound tell you when you earn one. Off: they are still earned, and listed under View "
     "achievements.", nullptr, false, true},
    // ---- System: the game's ----
    MENU_HEADING(TAB_SYSTEM, "Game"),
    // (Triforce: language.txt's choice, not the options file's. Its entries are counted when the file is read: lang_load)
    {TAB_SYSTEM, "Game language", &opts.language, 0, 0, 1, tx_language,
     "The language of the game's texts, of those your game has (language.txt in the game folder). Applies after a restart.",
     hn_language, true, true},
    // ((Triforce) this menu's own language: English by default, as before the row; the texts its tables lack stay English)
    {TAB_SYSTEM, "Menu language", &opts.menu_lang, 0, i18n::lang_count(), 1, tx_menu_lang, "The language of this menu.",
     hn_menu_lang, false, true},
    {TAB_SYSTEM, "Text speed", &opts.text_speed, 0, 3, 1, tx_text_speed,
     "How fast the letters of dialogue and other messages appear.", hn_text_speed},
    // (Triforce: host/oot_text_size.c, the text panes' own scale; taken at once)
    {TAB_SYSTEM, "Text size", &opts.text_size, 0, 4, 1, tx_text_size,
     "How large the text of dialogue, Navi and signs is drawn.", hn_text_size, false, true},
    // (host/nn_vi.c realtime_step, hos_vi_native_interval: Per frame is the console's, paced to the game's own interval)
    {TAB_SYSTEM, "Game speed", &opts.realtime, 0, 1, 1, tx_speed, "How the game keeps time when it runs below 60 fps.",
     hn_speed},
    // (Triforce: host/oot_fov.c, the camera's angle as the game builds its projection; taken at once)
    {TAB_SYSTEM, "Field of view", &opts.fov, 50, 150, 5, tx_fov,
     "How much of the world the camera shows while you play: higher is wider. Cutscenes keep their own view.", nullptr, false,
     true},
    // (Triforce: host/oot_damage.c, Link's life as the game writes it after a hit; taken at once)
    {TAB_SYSTEM, "Damage taken", &opts.damage_taken, 0, 3, 1, tx_damage_taken,
     "How much of his hearts Link loses from a hit. Half rounds up to the next quarter heart. Healing stays as it is.",
     nullptr, false, true},
    // (Triforce: host/oot_autoload.c, the title's list and the file select pressed through as benchmark mode does; read once,
    // when the title's list first shows, so a change is the next start's)
    {TAB_SYSTEM, "Skip title screen", &opts.skip_title, 0, 1, 1, tx_onoff,
     "Starts the game straight on your newest save: Continue and Load are pressed for you, unless you press something "
     "first. From the game's next start.", nullptr, false, true},
    // (Triforce: host/oot_opening.c, the opening's two movies not started; for a new game started with it on)
    {TAB_SYSTEM, "Skip opening", &opts.skip_opening, 0, 1, 1, tx_onoff,
     "A new game starts without its opening, the story movie and Navi waking Link. Every later cutscene plays as it does.",
     nullptr, false, true},
    // ---- Audio ----
    MENU_HEADING(TAB_AUDIO, "Sound"),
    // (Triforce, after NX2navi's volume row: over the game's own mix, host/nn_audio.c; the game's own Options have none)
    {TAB_AUDIO, "Master volume", &opts.volume, 0, 100, 5, tx_volume,
     "How loud the game is, in percent of its own volume.", nullptr, false, true},
    // (Triforce, after NX2navi's menu_sound_volume: the options' own sounds, host/menu_sound.c; under the Master volume)
    {TAB_AUDIO, "Menu sounds", &opts.menu_sounds, 0, 100, 5, tx_menu_sounds,
     "How loud these options' own sounds are, the game's interface sounds from your game files.", nullptr, false, true},
    // (Triforce: host/nn_audio.c master_volume, the Master volume's gain 0 while another window is in front; taken at once)
    {TAB_AUDIO, "Mute in background", &opts.mute_background, 0, 1, 1, tx_onoff,
     "No sound while another window has the focus.", nullptr, false, true},
    {TAB_AUDIO, "Audio output", &opts.audio_output, 0, 3, 1, tx_audio_output,
     "The speakers the game mixes its sound for. Applies after a restart; Stereo and Mono change at once.", hn_audio_output,
     true, true},
    // ((Triforce) 11-24: host/audio_output_devices.c, host/nn_audio.c output_route_update; taken at once. Shown where the host
    // lists devices: row_shown. Saved by the device's id, not its number: save)
    {TAB_AUDIO, "Output device", &output_pick, 0, 0, 1, tx_output_device,
     "The device the game plays its sound on: the system's default, or one you choose.", hn_output_device, false, true},
    MENU_HEADING(TAB_AUDIO, "Microphone"),
    {TAB_AUDIO, "Microphone", &opts.mic, 0, 2 + kMaxMics, 1, tx_mic,
     "What the ocarina hears when the game's microphone option is on (playing an instrument, or humming).", hn_mic, false,
     true},
    // (Triforce: host/nn_audio_in.c pump, the microphone's samples scaled before the game's streams get them; taken at once.
    // Shown with a microphone chosen: row_shown)
    {TAB_AUDIO, "Microphone gain", &opts.mic_gain, 25, 400, 25, tx_percent,
     "How loud the microphone is for the ocarina, in percent of what it gives. Raise it if your notes are not heard.",
     nullptr, false, true},
    // ((Triforce) 11-24: an action; the meter in its cell while on: mic_testing. Shown with a microphone chosen: row_shown)
    {TAB_AUDIO, kTestMic, nullptr, 0, 0, 0, nullptr,
     "Listens to the microphone while you set its gain, and shows how loud it is. Nothing is played back or recorded; the "
     "test stops when you leave the Audio tab."},
    // ((Triforce) 11-24) a DualSense's own speaker and headphones (host/pad_speaker.c, host/audio_source.c; the host reads
    // them packed: HOS_OPT_PAD_SPEAKER_*). Every kind Off and the headphones Off by default: nothing opens, as before
    MENU_HEADING(TAB_AUDIO, "Controller speaker"),
    {TAB_AUDIO, "Speaker volume", &opts.pad_speaker_volume, 0, 200, 10, tx_percent,
     "How loud a DualSense's own speaker plays the sounds sent to it below (the controller on a USB cable). A short tone "
     "plays on it when you change this.", nullptr, false, true},
    {TAB_AUDIO, "Controller sync", &opts.pad_speaker_sync, -100, 150, 10, tx_pad_sync,
     "Lines up the sounds set to Controller + TV. If the controller plays later than the TV, go below 0: the TV waits. If "
     "the TV plays later, go above 0: the controller waits.", nullptr, false, true},
    {TAB_AUDIO, "Headphones on the controller", &opts.pad_speaker_headphones, 0, 2, 1, tx_pad_headphones,
     "With headphones in a DualSense's jack (on a USB cable). All sound: the whole game plays on them and the TV is silent, "
     "as on the console. Controller sounds: only the sounds set to play on the controller go to them. Off: they are left "
     "out.", nullptr, false, true},
    {TAB_AUDIO, "Headphone volume", &opts.pad_speaker_headphone_volume, 0, 100, 10, tx_percent,
     "How loud the headphones in the controller's jack play.", nullptr, false, true},
    {TAB_AUDIO, "Navi's voice", &opts.pad_speaker[0], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Navi's flight sounds", &opts.pad_speaker[1], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Z-targeting", &opts.pad_speaker[2], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Ocarina", &opts.pad_speaker[3], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Pick-ups", &opts.pad_speaker[4], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Items", &opts.pad_speaker[5], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Fairies", &opts.pad_speaker[6], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Interface sounds", &opts.pad_speaker[7], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Stone of Agony", &opts.pad_speaker[8], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Low health alarm", &opts.pad_speaker[9], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Fishing", &opts.pad_speaker[10], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    {TAB_AUDIO, "Bottles", &opts.pad_speaker[11], 0, 2, 1, tx_pad_speaker,
     "Where this kind of sound plays with a DualSense on a USB cable. Off: with the rest of the game's sound. Controller "
     "only: on the controller's speaker, and no longer on the TV. Controller + TV: on both.", nullptr, false, true},
    MENU_HEADING(TAB_SYSTEM, "Saves & reports"),
    // (Triforce, after NX2navi's save rows: they act on a press, share_row; the host does the work, host/save_share.c)
    {TAB_SYSTEM, "Export save", nullptr, 0, 0, 0, nullptr,
     "Writes your save as a zip into your Downloads folder: to keep, or to give to someone. No game file is in it."},
    {TAB_SYSTEM, "Export save for a bug report", nullptr, 0, 0, 0, nullptr,
     "The same zip with the game's logs, its settings and its freeze report added: what to send with a problem report."},
    {TAB_SYSTEM, "Import a save", nullptr, 0, 0, 0, nullptr,
     "Takes a save export of Triforce or NX2navi that you put into the game folder's save-import folder. It becomes your "
     "save at the next start; the save it replaces is kept. For an emulator's save: Convert saves in Triforce Setup."},
    // (Triforce, after NX2navi's F8: host/bug_capture.c writes the folder, vk_bugshot.cpp its picture)
    {TAB_SYSTEM, "Bug capture (F8)", nullptr, 0, 0, 0, nullptr,
     "Writes what a problem report needs into a folder of its own under captures in the game folder: a picture, your "
     "settings, the end of the log and your save. F8 does the same while you play."},
    // (Triforce: host/save_files.c's files, the title's file select again; shown once the host has named them)
    {TAB_SYSTEM, "Save files", nullptr, 0, 0, 0, nullptr,   // (kFilesRow)
     "Your save files: each is a playthrough of its own, with its own saves and autosaves. Choosing another restarts the game "
     "on it, so save first."},
    // (Triforce: host/oot_autosave.c, the save requests of a crossing answered "not queued"; taken at once.
    // The group's last row: the rows that act on a press stand together after Microphone, tests/test_save_rows.py)
    {TAB_SYSTEM, "Autosave", &opts.autosave, 0, 1, 1, tx_onoff,
     "Whether the game saves by itself as you go from one area to another. Off skips those saves; saving from the pause "
     "menu still works.", nullptr, false, true},
    // ((Triforce) 11-24: NFC: opens the Scan amiibo page, menu_tick)
    MENU_HEADING(TAB_SYSTEM, "NFC"),
    {TAB_SYSTEM, kNfcTag, nullptr, 0, 0, 0, nullptr,
     "Hold one of your own amiibo to the game's reader: choose a dump (.bin, or a Flipper .nfc) from the folder \"amiibo\" in the game folder, "
     "then use amiibo in the game. Choose it again to take it off."},
    MENU_HEADING(TAB_SYSTEM, "Online"),
    {TAB_SYSTEM, "Discord status", &opts.discord, 0, 1, 1, tx_onoff,
     "Shows \"Playing Triforce\" and the time played in your Discord status, while Discord runs on this PC.", nullptr, false,
     true},
    // (Triforce, after NX2navi's Cheats tab: the cheats of the mods' cheat files, a row each once the host has named them)
    MENU_HEADING(TAB_SYSTEM, "Mod cheats"),   // (kModCheatHeading)
    MOD_CHEAT_ROWS8(0) MOD_CHEAT_ROWS8(8) MOD_CHEAT_ROWS8(16) MOD_CHEAT_ROWS8(24) MOD_CHEAT_ROWS8(32) MOD_CHEAT_ROWS8(40)
    MOD_CHEAT_ROWS8(48) MOD_CHEAT_ROWS8(56) MOD_CHEAT_ROWS8(64) MOD_CHEAT_ROWS8(72) MOD_CHEAT_ROWS8(80) MOD_CHEAT_ROWS8(88)

    // ---- Controls (Motion opens the 6 TAB_MOTION rows, Controls its page with the 2 TAB_PAGE rows) ----
    MENU_HEADING(TAB_CONTROLS, "Controller"),
    {TAB_CONTROLS, "Controller in background", &opts.pad_background, 0, 1, 1, tx_onoff,
     "Whether the controller plays the game while another window has the focus.", hn_background},
    // (Triforce, after NX2navi's lstick_deadzone and rstick_deadzone: host/nn_hid.c hos_stick_axis_own)
    {TAB_CONTROLS, "Left stick dead zone", &opts.lstick_dead_zone, -1, 50, 1, tx_own_dead_zone,
     "How far the left stick moves from its centre before the game sees it, in percent of its travel: lower for a precise "
     "stick, higher for one that drifts. The game's own dead zone still follows.", nullptr, false, true},
    {TAB_CONTROLS, "Right stick dead zone", &opts.rstick_dead_zone, -1, 50, 1, tx_own_dead_zone,
     "How far the right stick moves from its centre before the game sees it, in percent of its travel: lower for a precise "
     "stick, higher for one that drifts. The game's own dead zone still follows.", nullptr, false, true},
    // (Triforce: host/prompts.c build_camera)
    {TAB_CONTROLS, "Camera speed", &opts.camera_speed, 25, 300, 5, tx_sens,
     "How fast the right stick turns the camera, times the game's own speed. Applies after a restart.", nullptr, true, true},
    {TAB_CONTROLS, "Invert camera X", &opts.invert_cam_x, 0, 1, 1, tx_onoff,
     "Swaps left and right for the right stick's camera.", nullptr, false, true},
    {TAB_CONTROLS, "Invert camera Y", &opts.invert_cam_y, 0, 1, 1, tx_onoff,
     "Swaps up and down for the right stick's camera.", nullptr, false, true},
    MENU_HEADING(TAB_CONTROLS, "Mouse & keyboard"),
    {TAB_CONTROLS, "Mouse camera", &opts.mouse_native, 0, 2, 1, tx_mousecam, "How the captured mouse turns the camera.",
     hn_mousecam, false, true},
    {TAB_CONTROLS, "Mouse sensitivity", &opts.mouse_sens, 10, 500, 10, tx_sens,
     "How far the camera turns for a mouse movement. The - and = keys change it in game too.", nullptr, false, true},
    {TAB_CONTROLS, "Invert mouse vertical", &opts.mouse_invert, 0, 1, 1, tx_onoff, "Swaps up and down for the mouse.",
     hn_mouse_invert, false, true},
    // ((Triforce) 11-24: with Mouse camera on Native the game's own camera inversion, and Invert camera X, which turn the
    // right stick around, never reach the mouse: this row swaps its left and right, in both modes)
    {TAB_CONTROLS, "Invert mouse horizontal", &opts.mouse_invert_x, 0, 1, 1, tx_onoff,
     "Swaps left and right for the mouse.", nullptr, false, true},
    // (Triforce, after NX2navi's walk_key and walk_scale: host/nn_hid.c walk_key_code, walk_keys)
    {TAB_CONTROLS, "Walk key", &opts.walk_key, 0, 4, 1, tx_walk_key,
     "A key that makes Link walk: held with the movement keys, they push the stick only as far as Walk scale. While it is "
     "chosen the key presses nothing else.", hn_walk_key, false, true},
    {TAB_CONTROLS, "Walk scale", &opts.walk_scale, 20, 90, 1, tx_sens,
     "How far the movement keys push the stick while the Walk key is held: 1.00 would be all the way.", nullptr, false, true},
    {TAB_CONTROLS, "Menu shortcut", &opts.menu_shortcut, 0, 4, 1, tx_menu_shortcut,
     "Which keys open and close these options from anywhere. F1 always does; F1 only leaves Insert free for an overlay. With "
     "Esc, Esc opens them too, as a PC game's pause menu (open, Esc still goes back a page or closes them). With touchpad, a "
     "DualShock 4's or DualSense's touchpad click opens and closes them as F1 does.",
     nullptr, false, true},
    MENU_HEADING(TAB_CONTROLS, "Rumble"),
    // (Triforce: to 300 as NX2navi's rumble_strength, 150 before)
    {TAB_CONTROLS, "Rumble strength", &opts.rumble, 0, 300, 25, tx_rumble,
     "How strongly the controller rumbles, in percent of the game's rumble. Off turns it off.", nullptr, false, true},
    // (Triforce, after NX2navi's rumble_curve: host/pad_sdl.c rumble_curve)
    {TAB_CONTROLS, "Vibration curve", &opts.rumble_curve, 20, 150, 5, tx_sens,
     "Shapes the rumble: 1.00 is the game's. Lower makes the many weak rumbles easier to feel; higher quiets them. A Switch "
     "controller's HD rumble is not changed.", nullptr, false, true},
    // (Triforce, after NX2navi's rumble_triggers: host/pad_sdl.c trigger_poll)
    {TAB_CONTROLS, "Trigger vibration", &opts.rumble_triggers, 0, 1, 1, tx_onoff,
     "Xbox One and Series controllers: the motors in the triggers rumble too.", nullptr, false, true},
    // ((Triforce) 11-24) Vibration (host/vibration.h) and RenHDrum's HD Haptics (host/rumble_renhdrum.c). Without
    // renhdrum.dll beside the game, Auto plays as before: a Switch controller's own HD rumble, every other one's motors
    {TAB_CONTROLS, "Vibration", &opts.vibration, 0, 2, 1, tx_vibration,
     "How the controller vibrates. Auto plays the best it can: with RenHDrum beside the game a DualSense its voice coils, a "
     "Switch controller and an Xbox controller RenHDrum's HD rumble, a Steam Controller (2026) its grips; without it a "
     "Switch controller its own HD rumble and every other controller its motors. Basic plays the motors on every "
     "controller. Off stops it. The line below says what plays the controller used last.", hn_vibration, false, true},
    {TAB_CONTROLS, "DualSense HD Haptics", &opts.ds_hd_haptics, 0, 1, 1, tx_onoff,
     "A DualSense that RenHDrum plays also taps its speaker and kicks back on L2 and R2 while you hold them, from the "
     "game's vibration, with deeper heavy hits. Off: its fine haptics alone.", nullptr, false, true},
    MENU_HEADING(TAB_CONTROLS, "Gameplay"),
    // (Triforce, after NX2navi's sprint button: host/oot_sprint.h)
    {TAB_CONTROLS, "Sprint button", &opts.sprint_button, 0, 2, 1, tx_sprint,
     "Link sprints from a button press, without rolling first. Left stick click: the game has no other use for it. B: "
     "sprints while Link moves (with the game's Swap Jump Controls B is the jump: use the stick's click).", nullptr, false,
     true},
    {TAB_CONTROLS, "Sprint mode", &opts.sprint_mode, 0, 1, 1, tx_sprint_mode,
     "Toggle: a press starts the sprint, the next press or stopping ends it. Hold: Link sprints while the button is held.",
     nullptr, false, true},
    {TAB_CONTROLS, "Right handed Link", &opts.right_handed, 0, 1, 1, tx_onoff,
     "Link holds his sword and what he uses in his right hand, his shield on his left arm: his moves are mirrored, his body "
     "is not.", nullptr, false, true},
    // (Triforce: nx2/oot_patches.py patch_camera_centering, host/mouse_native.c hos_disable_camera_centering; taken at once)
    {TAB_CONTROLS, "Camera centering", &opts.camera_centering, 0, 1, 1, tx_onoff,
     "Whether the camera turns by itself the way Link moves. Off: it stays where you put it, which suits the mouse; the "
     "game's own recentring still works.", nullptr, false, true},
    {TAB_MOTION, "Motion controls", &opts.gyro, 0, 1, 1, tx_gyro,
     "Aims and looks with the controller's gyroscope where the game uses motion, as on the Switch: Switch Pro controllers "
     "and pads in Switch mode, DualSense and DualShock 4.", hn_gyro, false, true},
    {TAB_MOTION, "Motion sensitivity X", &opts.gyro_sens_x, 10, 600, 10, tx_percent,
     "How far the aim moves left and right for a turn of the controller. 100% is the console's.", nullptr, false, true},
    {TAB_MOTION, "Motion sensitivity Y", &opts.gyro_sens_y, 10, 300, 10, tx_percent,
     "How far the aim moves up and down for a tilt of the controller. 100% is the console's.", nullptr, false, true},
    {TAB_MOTION, "Invert motion X", &opts.gyro_inv_x, 0, 1, 1, tx_onoff, "Swaps the motion aim's left and right.", nullptr,
     false, true},
    {TAB_MOTION, "Invert motion Y", &opts.gyro_inv_y, 0, 1, 1, tx_onoff, "Swaps the motion aim's up and down.", nullptr,
     false, true},
    {TAB_MOTION, "Motion deadzone", &opts.gyro_deadzone, 0, 2, 1, tx_deadzone,
     "How slow a turn counts as none, the console's three settings: Standard is its own. High steadies a pad that jitters; "
     "Low keeps the smallest movements.", nullptr, false, true},
    // ((Triforce) 11-24: hold-to-toggle, for players who cannot keep a button held: a row for each of the Switch's buttons
    // that the game holds (not Plus, Minus or the directions). The rows' names are their keys, toggle_<button>;
    // host/hold_toggle.h has the rule, host/nn_hid.c npad_states reads them as one mask, HOS_OPT_HOLD_TOGGLE)
    MENU_HEADING(TAB_CONTROLS, "Hold to toggle"),
    {TAB_CONTROLS, "Toggle ZL", &opts.toggle[HOS_SW_ZL], 0, 1, 1, tx_onoff,
     "One press of ZL holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle ZR", &opts.toggle[HOS_SW_ZR], 0, 1, 1, tx_onoff,
     "One press of ZR holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle L", &opts.toggle[HOS_SW_L], 0, 1, 1, tx_onoff,
     "One press of L holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle R", &opts.toggle[HOS_SW_R], 0, 1, 1, tx_onoff,
     "One press of R holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle A", &opts.toggle[HOS_SW_A], 0, 1, 1, tx_onoff,
     "One press of A holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle B", &opts.toggle[HOS_SW_B], 0, 1, 1, tx_onoff,
     "One press of B holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle X", &opts.toggle[HOS_SW_X], 0, 1, 1, tx_onoff,
     "One press of X holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle Y", &opts.toggle[HOS_SW_Y], 0, 1, 1, tx_onoff,
     "One press of Y holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle LS", &opts.toggle[HOS_SW_LS], 0, 1, 1, tx_onoff,
     "One press of the left stick's click holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    {TAB_CONTROLS, "Toggle RS", &opts.toggle[HOS_SW_RS], 0, 1, 1, tx_onoff,
     "One press of the right stick's click holds it, the next lets it go, with whatever is bound to it. Opening a menu or pressing Plus or Minus lets it go too.",
     nullptr, false, true},
    MENU_HEADING(TAB_CONTROLS, "Motion & buttons"),
    {TAB_CONTROLS, "Motion", nullptr, 0, 0, 0, nullptr,   // (hookshot: opens the Motion page, the TAB_MOTION rows)
     "Aiming with the controller's gyroscope: on or off, its sensitivity and its inverts."},
    // ((Triforce VR) the VR Controls page: Link's body, then the hand controllers' swings and pointing
    {TAB_VRPAGE, "Control Scheme", &opts.vr_scheme, 0, 1, 1, tx_vr_scheme,
     "How the hand controllers play. Full Gesture: Link's moves from your own: draw from behind your head, swing to slash, "
     "raise the shield, pull back the bow, point to aim. Simplified: fewer gestures. In play the right trigger holds the item "
     "panel over the item box (the right stick picks, let go to choose; the left stick presses the D-pad meanwhile), and "
     "the right grip uses the item chosen, as a pad's item button, whatever it is (a swing does too). The left trigger "
     "locks on (Z); the left Y button is the sword's button; the shield is raised only with the sword in his hand.", nullptr, false, true, -1,
     false, "vr_scheme"},
    MENU_HEADING(TAB_VRPAGE, "Camera"),
    {TAB_VRPAGE, "Turn Speed", &opts.vr_turn_speed, 1, 50, 1, tx_tenths,
     "How fast the right stick's left and right turn you: around Link in Immersive, Smooth turning in Full Dive. 1.0: as "
     "before.", nullptr, false, true, -1, false, "vr_turn_speed"},
    {TAB_VRPAGE, "Zoom Speed", &opts.vr_zoom_speed, 1, 50, 1, tx_tenths,
     "Immersive: how fast the right stick's up and down bring you nearer to Link or farther from him. 1.0: as before.",
     nullptr, false, true, -1, false, "vr_zoom_speed"},
    MENU_HEADING(TAB_VRPAGE, "Comfort"),
    {TAB_VRPAGE, "Vignette", &opts.vr_vignette, 0, 1, 1, tx_onoff,
     "Full Dive: the edges of the view darken while you move or turn, more the faster (a run, a roll, a knockback), with "
     "either turning style, easier on the stomach.", nullptr, false, true, -1, false, "vr_vignette"},
    {TAB_VRPAGE, "Turning style", &opts.vr_turn, 0, 1, 1, tx_vr_turn,
     "Full Dive: how the right stick turns you. Smooth: a steady turn while it is held. Snap: one turn of the Snap angle each "
     "time it is pushed, easier on the stomach.", nullptr, false, true, -1, false, "vr_turn"},
    {TAB_VRPAGE, "Snap angle", &opts.vr_snap_angle, 15, 90, 15, tx_degrees,
     "Turning style Snap: how far each push of the right stick turns you.", nullptr, false, true, -1, false, "vr_snap_angle"},
    MENU_HEADING(TAB_VRPAGE, "Body"),
    {TAB_VRPAGE, "Visibility", &opts.vr_body, 0, 1, 1, tx_vr_body,
     "Full Dive: Shown: Link stays drawn, his arms follow your hands with what they hold, and his head is hidden. "
     "Hidden: all of Link is hidden, what he holds stays in view.", nullptr, false, true, -1, false, "vr_body"},
    {TAB_VRPAGE, "Arm reach", &opts.vr_arm_reach, 100, 160, 5, tx_percent,
     "Visibility Shown: how far Link's arms may stretch to meet your hands, his arms being shorter than yours. 100%: never "
     "stretched.", nullptr, false, true, -1, false, "vr_arm_reach"},
    MENU_HEADING(TAB_VRPAGE, "Controls"),
    {TAB_VRPAGE, "Swing speed", &opts.vr_swing_speed, 100, 500, 10, tx_cm_s,
     "How fast your hand must move for a swing to count as a sword slash. Lower: gentler swings slash.", nullptr, false, true, -1, false, "vr_swing_speed"},
    {TAB_VRPAGE, "Charge reach", &opts.vr_charge_reach, 25, 70, 1, tx_cm,
     "How far out from your body a swing must leave your hand to keep charging the sword; bringing the hand back in "
     "releases it. Lower suits shorter arms.", nullptr, false, true, -1, false, "vr_charge_reach"},
    {TAB_VRPAGE, "Pointing angle", &opts.vr_aim_tilt, 0, 60, 1, tx_degrees,
     "Motion: how far below the controller's own pointing line your aim goes. Raise it if the aim sits above where you "
     "point, lower it if below.", nullptr, false, true, -1, false, "vr_aim_tilt"},
    // (hookshot) the Controls page's own rows, above its grid (TAB_PAGE: no tab shows them)
    {TAB_PAGE, "Layout preset", &opts.pad_layout, 0, 3, 1, tx_pad_layout,
     "Which face button is which. Binding one yourself on the Controls page makes it Custom.", hn_pad_layout},
    {TAB_PAGE, "Button prompts", &opts.prompts, 0, HOS_PROMPT_N, 1, tx_prompts,
     "The button icons the game shows in its texts and menus: those of this controller, or the keyboard's and the mouse's.",
     hn_prompts, true, true},
    {TAB_CONTROLS, "Controls", nullptr, 0, 0, 0, nullptr,   // (hookshot: opens its page)
     "The layout preset, the button prompts, and which button and keys press each of the Switch's buttons."},
    {TAB_CONTROLS, "VR Controls", nullptr, 0, 0, 0, nullptr,   // ((Triforce VR) opens the VR Controls page, the TAB_VRPAGE rows)
     "The VR hand controllers: Link's body in Full Dive, and how swings and pointing are read."},

    // (Triforce VR) VR through OpenXR (vk_xr.cpp; host/vr_game.c for the camera's rows)
    // ((Triforce VR) Display's VR Settings page (TAB_VRSET; vk_xr.cpp and host/vr_game.c read them through vk_xr_cfg)
    {TAB_VRSET, "VR mode", &merged.vr_mode, 0, 2, 1, tx_vr_mode,
     "Theater: the game on a large screen floating in front of you, with its own camera. Immersive: the world surrounds you, "
     "the game's own camera behind Link, turned by your head. Full Dive: the world surrounds you from Link's own eyes; he "
     "faces where you look while he stands. This menu always shows on the screen.", nullptr, false, true},
    {TAB_VRSET, "Cutscenes", &opts.vr_cutscenes, 0, 1, 1, tx_vr_cutscenes,
     "Full Dive: how cutscenes are seen. Classic: the game's own cutscene camera, turned by your head. First "
     "person: from Link's eyes. Load zones, conversations, getting an item and showing one are always from Link's eyes.",
     nullptr, false, true, -1, false, "vr_cutscenes"},
    {TAB_VRSET, "HUD size", &opts.vr_hud_size, 40, 200, 5, tx_cm,
     "The width of the HUD's panel, a metre in front of you.", nullptr, false, true, -1, false, "vr_hud_size"},
    MENU_HEADING(TAB_VRSET, "Theater"),
    {TAB_VRSET, "Screen size", &opts.vr_screen_size, 45, 125, 5, tx_degrees,
     "How much of your view the floating screen fills, in degrees across: Theater mode, this menu and the title.", nullptr, false, true, -1, false, "vr_screen_size"},
    {TAB_VRSET, "Curved screen", &opts.vr_screen_curve, 0, 1, 1, tx_onoff,
     "Curves the floating screen around you, like a cinema's, so its edges stay as near as its middle. Off: a flat "
     "screen.", nullptr, false, true, -1, false, "vr_screen_curve"},
    MENU_HEADING(TAB_VRSET, "View"),
    {TAB_VRSET, "Render resolution", &opts.vr_resolution, 0, ur::kValues - 1, 1, tx_vr_resolution,
     "The size the 3D is drawn at while VR is on, in every stereo mode. As in Graphics: the Graphics tab's Render resolution "
     "(Auto lowers it under load, which looks blocky in the headset). A fixed size costs more GPU time but stays sharp. "
     "Applies after a restart.", nullptr, true, true, -1, false, "vr_resolution"},
    {TAB_VRSET, "Stereo Vision", &opts.vr_stereo, 0, 2, 1, tx_vr_stereo,
     "Performant: the game draws one picture and each eye's is made from it and its depth at the game's full rate; "
     "edges beside near things can smear. Balanced: each eye is drawn in turn, true depth everywhere, with the game's "
     "time standing still for the second eye, so both eyes see the same moment; the world moves at half the game's "
     "rate. Accurate: the frame is drawn twice, once for each eye, true depth everywhere at the game's full rate, for about twice "
     "the GPU time. The desktop window shows the left eye in Balanced and the right eye in Accurate.", nullptr, false, true, -1, false, "vr_stereo"},
    {TAB_VRSET, "Field of view", &opts.vr_view_scale, 50, 200, 5, tx_percent,
     "How much of the world the view takes in. The default, 100%, matches the headset's lenses exactly. Higher fits "
     "more of the world into your view, so everything looks smaller; lower zooms in. Away from 100%, the world seems "
     "to swim as you turn your head.", nullptr, false, true, -1, false, "vr_view_scale"},
    {TAB_VRSET, "Depth", &opts.vr_depth, 0, 200, 5, tx_percent,
     "How far apart your eyes are in the game's world. 100% matches your own eyes; 0% shows both eyes the same flat "
     "picture.", nullptr, false, true, -1, false, "vr_depth"},
    MENU_HEADING(TAB_VRSET, "Eye position"),
    {TAB_VRSET, "Head Vertical", &opts.vr_eye_up, -30, 30, 1, tx_cm_signed,
     "Moves your eyes up or down from the height of Link's eyes.", nullptr, false, true, -1, false, "vr_eye_up"},
    {TAB_VRSET, "Head Horizontal", &opts.vr_eye_side, -30, 30, 1, tx_cm_signed,
     "Moves your eyes to Link's right (more) or left (less).", nullptr, false, true, -1, false, "vr_eye_side"},
    {TAB_VRSET, "Head Forward", &opts.vr_eye_forward, -30, 30, 1, tx_cm_signed,
     "Moves your eyes forward or back from Link's face.", nullptr, false, true, -1, false, "vr_eye_forward"},
    {TAB_VRSET, "Cutscene height", &opts.vr_event_up, -50, 50, 1, tx_cm_signed,
     "Moves your eyes up or down from the game's own cutscene camera.", nullptr, false, true, -1, false, "vr_event_up"},
    // ---- Debug: the tools' switch, the tools themselves below it while they are on (cheat: menu_tick does what they do),
    // then the developer's rows ----
    {TAB_DEBUG, "Show physics shapes", &opts.vr_phys_show, 0, 1, 1, tx_onoff,
     "VR: draws what the hands touch the world with: the arms (blue), the hands (green), the sword or item (yellow) and each "
     "hand's grab reach (white, cyan near something to take, red holding it). Faint where something is in front.",
     nullptr, false, true, -1, false, "vr_phys_show"},
    {TAB_DEBUG, "Debug tools", &opts.debug_tools, 0, 1, 1, tx_onoff,
     "Testing tools: no-clip flight, a free camera, teleport, Link's age, the inventory, the clock, heart protection and "
     "movement speed. Off puts flight, the free camera and heart protection away and Link back to his own speed.", nullptr,
     false, true},
    {TAB_DEBUG, "Heart protection", nullptr, 0, 0, 0, nullptr,
     "Protects Link's hearts. Hits can still knock him back.", nullptr, false, true, 0},
    {TAB_DEBUG, "No-clip flight", nullptr, 0, 0, 0, nullptr,
     "Enable double-tap Jump for takeoff and landing: X (Space), or B with the game's Swap Jump Controls. Hold Jump or R to "
     "climb, L to descend.", nullptr, false, true, 1},
    {TAB_DEBUG, "Mark position", nullptr, 0, 0, 0, nullptr,
     "Remember Link's position for this loaded scene.", nullptr, false, true, 2},
    {TAB_DEBUG, "Return to mark", nullptr, 0, 0, 0, nullptr,
     "Teleport Link to the marked position in the current scene.", nullptr, false, true, 3},
    {TAB_DEBUG, "Set time", nullptr, 0, 0, 0, nullptr,
     "Choose an hour with Left or Right. Enter sets the world clock.", nullptr, false, true, 4},
    {TAB_DEBUG, "Inventory item", nullptr, 0, 0, 0, nullptr,
     "Choose a consumable with Left or Right.", nullptr, false, true, 5},
    {TAB_DEBUG, "Change quantity", nullptr, 0, 0, 0, nullptr,
     "Choose how many to add or remove. Enter applies the change.", nullptr, false, true, 6},
    {TAB_DEBUG, "Free camera", nullptr, 0, 0, 0, nullptr,
     "Move and look with your usual controls. Page Up / Page Down or R / L changes height.", nullptr, false, true, 7},
    {TAB_DEBUG, "Teleport", nullptr, 0, 0, 0, nullptr,
     "Opens the map list. Link travels through the game's own map change, in his current age.", nullptr, false, true, 8},
    {TAB_DEBUG, "Switch age", nullptr, 0, 0, 0, nullptr,
     "Swaps Link between child and adult and reloads this map in the other age (the Market when this map has no match).", nullptr, false, true, 9},
    {TAB_DEBUG, "Inventory", nullptr, 0, 0, 0, nullptr,
     "Enter opens the inventory editor: unlock or relock equipment, items, upgrades and quest items, and change amounts.", nullptr, false, true, 10},
    // (Triforce: host/hos_main.c hos_oot_cct_speed, the forward speed the game sets on Link's character controller; 1x at
    // every start, and with the tools off)
    {TAB_DEBUG, "Movement speed", nullptr, 0, 0, 0, nullptr,
     "How fast Link walks, runs and swims, as a multiple of his own speed. Choose with Left or Right.", nullptr, false, true, 14},
    // (Triforce: the name pages, after NX2navi's flags by name, cutscene starter and amiibo. Nothing is read, listed or sent
    // until one is opened)
    {TAB_DEBUG, "Game flags", nullptr, 0, 0, 0, nullptr,
     "Opens the game's story and world flags by name, in groups, read from your game files. See which are set in your save, and "
     "set or clear one. The game takes a change when it runs again.", nullptr, false, true, 11},
    {TAB_DEBUG, "Cutscenes", nullptr, 0, 0, 0, nullptr,
     "Opens the game's events by name, read from your game files, and starts one as the game's own actors do. Many belong to "
     "one place or one moment of the story and may not play as they should anywhere else. Save first.", nullptr, false, true, 12},
    {TAB_DEBUG, "Scan amiibo", nullptr, 0, 0, 0, nullptr,
     "Opens the dumps in the folder \"amiibo\" in the game folder (.bin files, or Flipper .nfc files, you made of your own figures). Choose one, then use "
     "amiibo in the game: the figure is on the reader when the game looks for one.", nullptr, false, true, 13},
    {TAB_DEBUG, "Developer", nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true},
    {TAB_DEBUG, "Descriptor reuse", &opts.descriptor_reuse, 0, 1, 1, tx_onoff,
     "A draw keeps its descriptors while the texture slots it samples are unchanged, so streaming elsewhere in the game no longer "
     "rebuilds every set each frame. Changes at once.", nullptr},
    // (Triforce: vk_draw.cpp gpl_wanted, what RX_VK_GPL=1 does; gpl_rules.h. On by default since options_version 5)
    {TAB_DEBUG, "Fast pipeline link", &opts.fast_pipeline_link, 0, 1, 1, tx_onoff,
     "Experimental. A new pipeline is first linked from its shaders' libraries, in milliseconds where the graphics driver has "
     "them compiled, and the optimised one takes its place once it is built. The first start with it compiles those libraries "
     "once, which takes minutes. Needs a card with pipeline libraries. Applies after restart.", nullptr, true, true},
    // ((Triforce, 11-24) gpu/vk/compile_level.h: read by the shader preparation, compile_level_now; RX_VK_COMPILE_SHADERS over it)
    {TAB_DEBUG, "Compile shaders", &opts.compile_shaders, 0, 1, 1, tx_compile_shaders,
     "How much of the graphics driver's work the shader preparation does before the title, after an update, a new driver "
     "or a new install. Applies at the next preparation.", hn_compile_shaders, true, true},
    {TAB_DEBUG, "Sampler cache", &opts.sampler_cache, 0, 1, 1, tx_onoff,
     "What a sampler holds is kept beside it on the replay thread, so resolving a sampler that was not registered anew takes no "
     "lock. Helps while the game streams textures. Changes at once.", nullptr},
    // (Triforce: vk_memory.cpp "lazy write-back", wb_lazy_state.h; RX_VK_LAZY_WB over it. On by default since options_version
    // 5, but nowhere on AMD's driver by this row alone. Windows only: row_shown)
    {TAB_DEBUG, "Lazy write-back", &opts.lazy_write_back, 0, 1, 1, tx_onoff,
     "Experimental. What the GPU writes into memory the game shares with it is copied back only when the game, the system or "
     "the GPU next reads it there, not after every submission. Saves memory traffic where the game reads little of it. "
     "Applies after restart.", hn_lazy_write_back, true, true},
    // (Triforce: vk_replay.cpp par_threads_max, what RX_VK_PARALLEL_AUTO=<n> does. Automatic unless set here: replay_threads.h)
    {TAB_DEBUG, "Replay helper threads", &opts.replay_threads, 0, 8, 1, tx_replay_threads,
     "A frame's large command buffers are recorded on this many threads wherever short trials, made every so often as the game "
     "runs, find that faster than the replay thread alone. Automatic: 2 or 3 threads by this PC's processors, none with four "
     "cores or fewer. Off: the replay thread alone, always: choose it if frames flicker. Used with DLSS or FSR on too, for "
     "upscaling or frame generation: what comes after the upscale is recorded in order. Applies after restart.",
     hn_replay_threads, true, true},
    // (Triforce, after NX2navi's tail_early: vk_replay.cpp the early tail, tail_early.h. Read at the start. The owner, 11-16:
    // "implement this in debug under developer" and "on by default": a Developer row, on by default since options_version 6)
    {TAB_DEBUG, "Start next frame early", &opts.tail_early, 0, 1, 1, tx_onoff,
     "Experimental. The game starts its next frame while the graphics card still draws the end of this one (the upscaling "
     "and the interface), where that end holds nothing the game reads back. Other frames run as before. Applies after "
     "restart.", nullptr, true, true},
    // ((Triforce) Threaded rendering: threaded_rendering.h, vk_main.cpp threaded_choice; RX_VK_THREADED over it. Read at the start;
    // Off by default again (11-24): the owner saw whole-screen flashes with it on in play that the frame log (taken before the
    // window's image) does not show; +3% fps on a moving tour in the lab. On again once the flashes are fixed)
    {TAB_DEBUG, "Threaded rendering", &opts.threaded_rendering, 0, 2, 1, tx_threaded,
     "Experimental. The graphics work runs on threads of its own: the game's commands are turned into the graphics card's on a "
     "render thread while the game goes on with its next frame, the driver's calls are made by a recorder thread beside it, "
     "and the picture is shown from a thread of its own. Auto: on with 4 processor cores or more. Turn it off if frames "
     "flicker. Applies after restart.",
     hn_threaded, true, true},
    // (Triforce, after NX2navi's astc_bc1: tex_bc1.h, vk_texture.cpp bc1_on. Read at the first texture; on by default since
    // options_version 5. The owner, 11-16: "put this in debug dev tab too": a Developer row, after Start next frame early)
    {TAB_DEBUG, "Opaque textures as BC1", &opts.tex_bc1, 0, 1, 1, tx_onoff,
     "Keeps the game's large textures that have no transparency in half the video memory, with the same picture. Off: as "
     "before. Turn it off if textures look wrong. Applies after a restart.",
     hn_tex_bc1, true, true},
    // ((Triforce) 11-19, the owner: Restart and Quit moved to the pause menu's System page, as the game's own button under
    // Mods (draw_mods_row; its dialog draw_quit_ask)
    {TAB_DEBUG, "Robust buffers", &opts.robust, 0, 2, 1, tx_robust,   // ((Triforce, options_version 7) from the Graphics tab)
     "Bounds-checked buffer reads: a read past a buffer's end is dropped instead of stopping the GPU. Applies after a "
     "restart. On AMD and Intel cards, changing it prepares every shader again at the next start (a long first start on "
     "AMD); on NVIDIA cards it does not. Switching back is quick when the shaders of the setting before were kept (one "
     "earlier set is kept when the disk has room for it).",
     hn_robust, true},

    // ---- (Triforce, options_version 7) The saved values the merged rows above stand for (merged_rows.h): no tab shows them.
    // Each keeps its key in triforce_options.ini (the row's name: ini_key), loaded and saved as before, for the renderer and the
    // host read them, some before the menu (host/nn_vi.c renodx_hdr= and steady_frame_rate=, vk_dlssg.cpp
    // dlss_frame_generation=). Their merged rows take the restarts (restart_value_of) ----
    {TAB_HIDDEN, "HDR", &opts.hdr, 0, 2, 1, tx_hdr, nullptr},
    // ((Triforce VR) the saved values that VR mode and 3D Style's Mode stand for)
    {TAB_HIDDEN, "VR", &opts.vr, 0, 1, 1, tx_onoff,
     "Shows the game in a VR headset through OpenXR (for example WiVRn on Linux, SteamVR or Meta's runtime on "
     "Windows), with the headset connected before the game starts. Applies after a restart.", nullptr, false, true, -1, false, "vr"},
    {TAB_HIDDEN, "VR view", &opts.vr_view, 0, 1, 1, tx_vr_view,
     "Immersive: the world surrounds you in play and in cutscenes, and the game's camera follows your head. Theater: "
     "the game on a large screen floating in front of you. This menu always shows on the screen.", nullptr, false, true, -1, false, "vr_view"},
    {TAB_HIDDEN, "Camera", &opts.vr_camera, 0, 1, 1, tx_vr_camera,
     "First person: you see from Link's eyes, Link is hidden while what he holds stays in view, and he faces where you "
     "look while he stands. Third person: the game's own camera, turned by your head.", nullptr, false, true, -1, false, "vr_camera"},
    {TAB_HIDDEN, "3D on the screen", &opts.flat3d, 0, 5, 1, tx_flat3d,
     "The game in 3D on a flat screen, without a headset (when VR is off or no headset is connected). Red/cyan: glasses with "
     "a red and a cyan lens. Side by side (3D TV): each eye squeezed into its half, for a 3D TV's side by side mode. Crossed "
     "eyes: the right eye's picture on the left, for viewing with crossed eyes. Above and below: each eye in its half, one "
     "over the other. Side by side (Cardboard): each eye's whole picture in its own half, for a phone in a viewer such as "
     "Google Cardboard, or for showing a stream in 3D; with this one, while VR runs, the desktop shows both of the headset's "
     "eyes side by side.", nullptr, false, true, -1, false, "flat3d"},
    {TAB_HIDDEN, "RenoDX HDR", &opts.renodx, 0, 1, 1, tx_onoff, nullptr},
    {TAB_HIDDEN, "Frame generation", &opts.framegen, 0, framegen_rows::kRowMax, 1, tx_framegen, nullptr},
    {TAB_HIDDEN, "DLSS frame generation", &opts.dlssg, 0, 3, 1, tx_dlssg, nullptr},
    {TAB_HIDDEN, "Frame pacing", &opts.pace, 0, 1, 1, tx_onoff, nullptr},
    {TAB_HIDDEN, "Steady frame rate", &opts.steady_fps, 0, 2, 1, tx_steady_fps, nullptr},
    {TAB_HIDDEN, "NVIDIA Reflex", &opts.reflex, 0, 2, 1, tx_latency, nullptr},
    {TAB_HIDDEN, "AMD Anti-Lag 2", &opts.antilag, 0, 1, 1, tx_onoff, nullptr},
    // ((Triforce) Auto (this PC)'s state: its tuning (auto_tune=) and the hardware it chose for (auto_for=), auto_settings.h)
    {TAB_HIDDEN, "Auto tune", &opts.auto_tune, 0, 15, 1, nullptr, nullptr},
    {TAB_HIDDEN, "Auto for", &opts.auto_for, 0, 0x7fffffff, 1, nullptr, nullptr},
    // ((Triforce, N64 Classic, step 5) F7's preset from Off (n64_rules.h Toggle): saved as n64_classic_last, its name's key)
    {TAB_HIDDEN, "N64 Classic last", &opts.n64_last, n64_rules::FAITHFUL, n64_rules::REMEMBERED, 1, nullptr, nullptr},

};
constexpr int kRowsEnd = sizeof rows / sizeof rows[0];   // (the table's end: tests read the table up to here)
const Row* pending = nullptr;   // (Restart or Quit: shows Confirm until its second press)
bool cheats_env = false;   // (HOS_OOT_CHEATS=1: on whatever the Debug tab says)
/// The debug tools: the Debug tab's row, or HOS_OOT_CHEATS=1
bool cheats_on() { return cheats_env || opts.debug_tools; }
// (Triforce) The Debug tab: shown always since 11-15 (the owner: "make debug on by default and remove the alt+g shortcut").
// Alt+G, which unlocked it and put it away again, is gone; the options file's old debug_tab= line is dropped at the next save
bool debug_shown() { return true; }
int tabs_shown() { return debug_shown() ? TAB_COUNT : TAB_COUNT - 1; }
// (Triforce) Inside the game's own Options screen. host/oot_menu.c says each frame that screen runs (menu_option_set,
// HOS_OPT_GAME_OPTIONS). While it does, the options' tabs are drawn over its header with one more in front, "Game": the
// game's own list, which stays the game's (drawn by it, its input its own). L and R (the buttons the Switch's L and R are
// bound to, or their keys: Q and E are the game's own keys there) go on to our tabs and back; on ours the game's list,
// caption and guides are under the same plates, ours, which are opaque. Back on one of ours is the game's Back too
// (host/nn_hid.c). TRIFORCE_OPTIONS_TABS=0: off (the game's Options as it is, ours through F1 alone)
std::atomic<int64_t> game_options_ns{0};   // (prof_now at the last frame the host said so; 0 never)
// ((Triforce, 11-20) that screen chosen from the pause menu (the host's word 2): its guides band may end sooner, game_grid.h
// kPauseGuideBandRight)
std::atomic<bool> game_options_from_pause{false};
bool embed_open = false;                   // (our tabs are open from inside the game's Options: leaving them is its own tab again)
int64_t embed_since = 0;                   // (when that screen was first seen running: the tabs fade in over its opening)
constexpr int kGameTab = 99;               // (the tabs' hit for the game's own tab)
// ((Triforce) the mouse over the tabs on the game's own tab (draw_game_tab): where they are in the window, as menu_map is
// draw_menu's ((11-19) the game's grid: game_grid.h column_of), and whether the mouse has been read since the game's screen
// came: a click from before is not the tabs')
game_grid::Map game_tab_map;
bool game_tab_read = false;
bool hits_game_tab = false;   // (the hits are draw_game_tab's: its tabs were drawn last, not the open menu)
// (Triforce) Mods: an entry of the tab strip after System (before Debug) that opens a page of its own, kModsPage (vk_mods.h:
// GameBanana's mods for this game, installed into the mods folder). Not a MenuTab: it has no rows
constexpr int kModsTab = 98;               // (the tabs' hit for it, and draw_tabs' sel while its page is open)
constexpr int kModsPage = 8;               // (page: 0 the options, 1 controls, 3 teleport, 4 inventory, 5 the restart question, 6 names)
int mods_choice = 0;                       // (the card chosen)
float mods_scroll_px = 0, mods_want_px = 0;
int mods_wheel = 0, mods_page_rows = 1;
// ((Triforce) 11-17, his "theres not even a way to scroll down on the mods description on the right side") The description's
// own scroll: the right stick, or the mouse wheel over the details; back to its top when the choice moves
int mods_desc_wheel = 0, mods_desc_for = -2;
// ((Triforce) 11-17, his layout A) The Mods screen's categories, a strip of tabs under the banner turned by L and R: the loaded
// list filtered by GameBanana's root category (or installed). A mod whose category none names is in All alone
constexpr int kModsCats = 6;
const char* const kModsCatNames[kModsCats] = {"All", "Gameplay", "Models", "Audio", "Interface", "Installed"};
int mods_cat = 0;
int mods_cat_pick = -1;   // (a click on a category's tab: taken by the next tick)
/// ((Triforce) 11-18) after a card's author and category: a WiP or a kit (a program of its own) says so
std::string mods_kind(const mods::Mod& m) {
    return m.kit ? "  \xC2\xB7  Own program" : m.wip ? "  \xC2\xB7  Work in progress" : "";
}
bool mods_in_cat(const mods::Mod& m, int cat) {
    auto has = [&m](const char* w) { return m.category.find(w) != std::string::npos; };
    switch (cat) {
    case 1: return has("Gameplay") || has("Mechanic") || has("Cheat");
    case 2: return has("Model") || has("Texture") || has("Skin") || has("Character");
    case 3: return has("Audio") || has("Sound") || has("Music") || has("Voice");
    case 4: return has("UI") || has("HUD") || has("Interface") || has("Menu") || has("Font");
    case 5: return m.installed;
    default: return true;
    }
}
float mods_desc_px = 0, mods_desc_x0 = 1e9f;
uint32_t menu_pad_raw = 0;   // (the pads' bits at this tick, host/nn_hid.c hos_pad_raw: the sticks' menu bits too)
bool mods_follow = true;                   // (the cards follow the choice; the wheel lets go of it until the choice moves)
int mods_btn = 0;                          // (a dialog's button chosen: 0 the upper one)
// (Triforce) The Mods entry under a game list's last button (host/oot_menu.c tells where: HOS_OPT_MODS_*): the pause menu's
// System page and the title's list. While the cursor is on it the menu is "open" on kModsRowPage, which draws the entry alone
// over the game's list (the game's input is ours then, and the host lets its cursor go); A opens kModsPage
constexpr int kModsRowPage = 9;
std::atomic<int> mods_list_bits{0};        // (HOS_MODS_LIST_*, as the last report had them)
std::atomic<int> mods_list_alpha{-1};      // ((Triforce, 11-20) HOS_OPT_MODS_ALPHA: the game's own buttons' alpha, thousandths; -1 not told)
std::atomic<int> mods_box[5];              // (the last button's box and the pitch, the layout's units: x0 x1 y0 y1 pitch)
std::atomic<int64_t> mods_list_ns{0};      // (prof_now at the last report)
std::atomic<int64_t> mods_list_frame{0};   // ((Triforce, 11-19) and game_frames then: a slow game frame is not a list gone)
std::atomic<int> mods_enter{0};            // (the host's word: 1 the cursor onto the entry, 2 a click on it; 3 a click on Quit,
                                           // 4 the cursor onto Quit)
std::atomic<int> mods_press{0};            // (presses the host passed on while Mods has the cursor: HOS_MODS_PRESS_*)
// ((Triforce, 11-19) and the directions held at its last read (HOS_MODS_PRESS_DIRS bits), and when: repeated as a pad's are)
std::atomic<int> mods_held_dirs{0};
std::atomic<int64_t> mods_held_ns{0};
// ((Triforce) 11-19, the owner: "I want quit and restart moved from our custom settings menu to [under Mods on the pause menu's
// System page]. IT NEEDS TO LOOK NATIVE". One button fits under Mods at the list's own pitch above the prompts, so it is Quit,
// as the game's own button, and its dialog asks Quit Game / Restart Game / Cancel (his choice). The title's list has Mods only)
int mods_row_sel = 0;                      // (the entry with the cursor: 0 Mods, 1 Quit)
bool quit_ask = false;                     // (Quit's dialog is open)
int quit_sel = 0;                          // (its choice: 0 Quit Game, 1 Restart Game, 2 Cancel)
// ((Triforce, 11-19) the owner: "the mods and quit tabs do not have any sound effects when selecting them, have no animations
// either ... The quit menu submenu also has no animations and sound effects". Mods and Quit fade their cursor in and out as
// the System list's own buttons do (focus_anim.h: PaCommonBtnThin_00's Select and UnSelect), and Quit's dialog opens and
// closes as the game's SystemWindow_00 (In, Out), its buttons as the same part; it takes input once its In has played)
focus_anim::Focus mods_focus[2];           // (Mods, Quit)
// ((Triforce, 11-20) the owner: "Mod menu fade in". The Mods screen came whole on the frame after the press; it fades in as
// the game's lists and windows do (mods_page_anim.h), stepped by menu_tick, and takes input once that has played)
mods_page::Page mods_screen;
focus_anim::Focus quit_focus[3];           // (the dialog's buttons)
int64_t quit_open_ns = 0;                  // (prof_now when the dialog opened: its In; 0 shut)
int64_t quit_shut_ns = 0;                  // (when B or Cancel closed it: its Out; 0 none playing)
bool quit_fresh = false;                   // (just opened: its buttons as they stand, the first one chosen)
bool quit_ended = false;                   // (Quit Game or Restart Game chosen at this tick: the game goes, no cursor sound after)
/// (Quit's dialog opens: In from now, Quit Game chosen)
void quit_open() { quit_ask = true, quit_sel = 0, quit_open_ns = prof_now(), quit_shut_ns = 0, quit_fresh = true; }
/// (B or Cancel: it closes with its Out; Quit keeps the cursor)
void quit_cancel() { quit_ask = false, quit_open_ns = 0, quit_shut_ns = prof_now(); }
/// (it goes with the entries, their list gone or the menu shut: no Out)
void quit_gone() { quit_ask = false, quit_open_ns = 0, quit_shut_ns = 0; }
/// (its Out still playing)
bool quit_closing() { return !quit_ask && quit_shut_ns && prof_now() - quit_shut_ns < focus_anim::kOutNs; }
bool quit_entry_shown() { return (mods_list_bits.load(std::memory_order_relaxed) & HOS_MODS_LIST_TITLE) == 0; }
/// (Triforce) Save Select, the entry under Mods on the title's list while the host has named the save files (host/save_files.c):
/// where Quit is under the System list's Mods, and mods_row_sel 1 as it is. Not on the pause menu: a file is changed at the title
bool files_row_shown() {
    return save_files.shown() > 0 && (mods_list_bits.load(std::memory_order_relaxed) & HOS_MODS_LIST_TITLE) != 0;
}
std::atomic<int64_t> game_frames{0};   // (the game's frames shown: menu_note_frame)
/// ((Triforce, 11-19) the lab's "one DOWN from Options on the title did nothing and logged nothing": with the game's window
/// behind another one its frames came 80 to 235 ms apart, and a list told of at each of them counted as gone after 150 ms, so
/// the host's word that the cursor goes onto Mods was dropped (and the host's own 80 ms, host/oot_menu.c hos_oot_mods_down,
/// gave the Down to the game, which has nothing under its last button). A list told of at the game's last frame or the one
/// before is there however long ago that was: the age the entry's animations take (0 then))
int64_t mods_list_age() {
    const int64_t t = mods_list_ns.load(std::memory_order_relaxed);
    if (!t) return INT64_MAX;
    const int64_t frames = game_frames.load(std::memory_order_relaxed) - mods_list_frame.load(std::memory_order_relaxed);
    return frames >= 0 && frames <= 2 ? 0 : prof_now() - t;
}
bool mods_list_fresh() { return mods_list_age() < 150000000LL; }
/// ((Triforce, 11-20) the owner: "the mods button ... should be synced with the timing of the other button ui so it
/// seamlessly moves and disappears with them". How much of its own list's buttons the game shows this frame, 0 to 1, as
/// the host reads it from the game (host/oot_menu.c, HOS_OPT_MODS_ALPHA); under 0 while it has not said (an older host)
float mods_list_shown() {
    const int a = mods_list_alpha.load(std::memory_order_relaxed);
    // (as the overlay has to draw it to look as the game's own buttons at that alpha: mods_entry_anim.h list_amount)
    return a < 0 ? -1.0f : mods_entry::list_amount((float)a / 1000.0f, dev.hdr);
}
// ((Triforce, 11-19) the title's list, the owner: "make it the same as the other options, with the green filigree, the same
// animations: when you select it, it just pops in". The entry is drawn as the game's own entries (draw_title_mods, with
// mods_entry_anim.h's times): it fades with the list, and A on it plays the game's Decide before the Mods screen opens)
bool mods_title_list() { return (mods_list_bits.load(std::memory_order_relaxed) & HOS_MODS_LIST_TITLE) != 0; }
/// (the title's entry as it goes with its list: drawn a little past the list's last word, fading)
bool mods_title_fading() { return mods_title_list() && mods_list_age() < mods_entry::kListShownNs; }
int64_t mods_decide_ns = 0;   // (A on the title's entry: when, while its Decide plays; 0 none)
float mods_entry_px[5] = {};   // (the Mods entry as last drawn, the menu's column's pixels: its hit x0 y0 x1 y1, and the pitch)
bool mods_decided = false;     // (its Decide ended this tick: the Mods screen opened with no sound of its own, it had the press's)
// ((Triforce) 11-17, his ask "We need a search bar for mods") The Mods screen's search: a bar above the cards (mods_choice -1 is
// the bar), typed into from the keyboard anywhere on the screen (host/display.c: HOS_OPT_TEXT_CHAR), or from a keyboard of the
// game's look on the screen for a controller (A on the bar). The text is searched 0.5 s after the typing stops, or at once
// with Confirm; fewer than 2 characters is the whole list again, where it was (vk_mods.cpp search)
std::string mods_query;              // (the bar's text as typed, UTF-8)
std::string mods_query_sent;         // (the text the list is the search of)
int64_t mods_query_edit_ns = 0;      // (the last change of the text)
bool mods_kbd = false;               // (the on-screen keyboard open)
int mods_kbd_row = 1, mods_kbd_col = 0;
int mods_browse_choice = 0;          // (the whole list's choice and scroll when a search began: given back when it ends)
float mods_browse_px = 0;
std::mutex mods_typed_mu;
std::vector<int> mods_typed;         // (code points typed, from the window's thread: taken by mods_tick)
std::atomic<bool> mods_text_wanted{false};
// ((Triforce) The Output width and Output height rows typed into: with either selected, the keyboard's digits are the row's
// (host/display.c sends them as the Mods search's text, HOS_OPT_TEXT_CHAR, while size_text_wanted): the first starts a new
// number, Backspace takes one off, Enter takes the number (rounded down to the row's step of 8, held to its range), Esc
// leaves it as it was. Left and Right step it as before)
std::atomic<bool> size_text_wanted{false};
std::vector<int> size_typed;   // (code points typed for the two rows, under mods_typed_mu)
int* size_edit = nullptr;      // (the row typed into now, nullptr none)
std::string size_text;         // (its digits so far)
float mods_kbd_box[4] = {0, 0, 0, 0};   // (the on-screen keyboard's box as last drawn, pixels: x0 y0 x1 y1)
// (the keyboard: four rows of ten keys, the letters shown capital and typed small, and a row of Space, Delete, Clear, Search)
const char* const kKbdRows[4] = {"1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm-.&"};
const char* const kKbdWide[4] = {"Space", "Delete", "Clear", "Search"};
constexpr int kKbdWideAt[5] = {0, 4, 6, 8, 10};   // (the wide keys' first columns, and the row's end)
int kbd_wide(int col) { return col < 4 ? 0 : col < 6 ? 1 : col < 8 ? 2 : 3; }
void utf8_add(std::string& s, int cp) {
    if (cp < 0x80) s += (char)cp;
    else if (cp < 0x800) s += (char)(0xC0 | cp >> 6), s += (char)(0x80 | (cp & 63));
    else if (cp < 0x10000) s += (char)(0xE0 | cp >> 12), s += (char)(0x80 | (cp >> 6 & 63)), s += (char)(0x80 | (cp & 63));
    else s += (char)(0xF0 | cp >> 18), s += (char)(0x80 | (cp >> 12 & 63)), s += (char)(0x80 | (cp >> 6 & 63)), s += (char)(0x80 | (cp & 63));
}
bool utf8_pop(std::string& s) {   // (the last character, all its bytes)
    if (s.empty()) return false;
    while (!s.empty() && ((unsigned char)s.back() & 0xC0) == 0x80) s.pop_back();
    if (!s.empty()) s.pop_back();
    return true;
}
bool embed_allowed() {
    static const bool on = !getenv("TRIFORCE_OPTIONS_TABS") || atoi(getenv("TRIFORCE_OPTIONS_TABS")) != 0;
    return on;
}
/// (Triforce, 11-13, the user: "Remove f1 menu (we have it in options now natively)") Whether Insert, F1, a gamepad's Home and
/// Select+Start open these options over the game from anywhere. Not any more: they are the tabs inside the game's own
/// Options screen. TRIFORCE_INGAME_MENU=1 (triforce_env.txt) brings the keys back; with TRIFORCE_OPTIONS_TABS=0 (no tabs in
/// the game's screen) they stay, or there would be no way to the options at all
bool overlay_allowed() {
    static const bool on = (getenv("TRIFORCE_INGAME_MENU") && atoi(getenv("TRIFORCE_INGAME_MENU")) != 0) || !embed_allowed();
    return on;
}
/// The game's Options screen ran within the last quarter second
bool game_options_shown() {
    const int64_t t = game_options_ns.load(std::memory_order_relaxed);
    return embed_allowed() && t && prof_now() - t < 250000000LL;
}
// (a line shown for a moment at the foot of the screen: the Debug tab unlocked or locked while the options are closed)
char notice_text[64] = "";
int64_t notice_until = 0;
std::atomic<int> protect_hearts{-1};
// -1 disables the shortcut, 0 enables it on the ground, and 1 means flying.
std::atomic<int> player_flight{-1};
std::atomic<int> free_camera{0};
std::atomic<int> cheat_action{0};
std::atomic<int> link_age{-1};   // (the game side's report, OOT_CHEAT_AGE_ID: 0 child, 1 adult, -1 no save loaded)
// ((Triforce) Movement speed: the choice, an index of link_speeds; the game side reads it in percent, HOS_OPT_CHEAT_SPEED)
constexpr int link_speeds[] = {100, 125, 150, 200, 300};
constexpr const char* link_speed_names[] = {"1x", "1.25x", "1.5x", "2x", "3x"};
constexpr int kLinkSpeeds = sizeof link_speeds / sizeof link_speeds[0];
std::atomic<int> link_speed{0};
int clock_hour = 12;
int pouch_item = 0;
int pouch_delta = 1;
constexpr const char* pouch_items[] = {"Deku Seeds", "Deku Nuts", "Deku Sticks", "Bombs", "Arrows"};
constexpr int kPouchItems = sizeof pouch_items / sizeof pouch_items[0];
// (teleport list: generated by work/oot-teleport-tools/write_destinations.py)
// (the order of oot_destinations in host/hos_main.c; Enter sends 1000 + the index)
constexpr const char* teleport_names[] = {
    "Kokiri Forest",
    "Hyrule Field",
    "Kakariko Village",
    "Market",
    "Hyrule Castle",
    "Lost Woods",
    "Sacred Forest Meadow",
    "Lake Hylia",
    "Graveyard",
    "Death Mountain Trail",
    "Death Mountain Crater",
    "Goron City",
    "Zora's River",
    "Zora's Domain",
    "Zora's Fountain",
    "Gerudo Valley",
    "Gerudo Fortress",
    "Haunted Wasteland",
    "Desert Colossus",
    "Inside the Deku Tree",
    "Dodongo's Cavern",
    "Jabu-Jabu's Belly",
    "Forest Temple",
    "Fire Temple",
    "Water Temple",
    "Shadow Temple",
    "Spirit Temple",
    "Bottom of the Well",
    "Ice Cavern",
    "Gerudo Training Ground",
    "Ganon's Castle"};
constexpr const char* teleport_notes[] = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "adult only", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
struct TeleportSection { const char* name; int first; };
constexpr TeleportSection teleport_sections[] = {{"Overworld", 0}, {"Dungeons", 19}};
constexpr int kTeleportSections = sizeof teleport_sections / sizeof teleport_sections[0];
// (end of the generated teleport list)
constexpr int kTeleports = sizeof teleport_names / sizeof teleport_names[0];
int teleport_choice = 0;
int teleport_columns = 1, teleport_page_rows = 1;   // (as last drawn: the cards in a row, the rows that fit: Page Up / Down)
float teleport_scroll_px = 0, teleport_want_px = 0;   // (the cards' scroll, eased toward teleport_want_px)
bool teleport_follow = true;   // (the scroll follows the choice; the wheel lets go of it until the choice moves)
int teleport_wheel = 0;        // (the wheel's notches since the last drawing: it scrolls by them)
int teleport_section_of(int i) {
    int section = 0;
    while (section + 1 < kTeleportSections && i >= teleport_sections[section + 1].first) ++section;
    return section;
}
int teleport_section_end(int section) {
    return section + 1 < kTeleportSections ? teleport_sections[section + 1].first : kTeleports;
}
/// The destination rows rows down (up when negative) from i, in the grid the Teleport page draws: each section's cards
/// teleport_columns to a row, under the section's heading; the column kept where the next row has it
int teleport_step_rows(int i, int rows) {
    const int cols = std::max(1, teleport_columns);
    for (; rows > 0; --rows) {
        const int section = teleport_section_of(i), first = teleport_sections[section].first, end = teleport_section_end(section);
        const int p = i - first;
        if (p + cols < end - first) i += cols;
        else if (p / cols < (end - first - 1) / cols) i = end - 1;   // (the section's last row, a short one)
        else if (section + 1 < kTeleportSections) i = std::min(end + p % cols, teleport_section_end(section + 1) - 1);
        else break;
    }
    for (; rows < 0; ++rows) {
        const int section = teleport_section_of(i), first = teleport_sections[section].first, p = i - first;
        if (p >= cols) i -= cols;
        else if (section > 0) {
            const int prev = teleport_sections[section - 1].first, n = first - prev;
            i = std::min(prev + (n - 1) / cols * cols + p, first - 1);
        } else break;
    }
    return i;
}
// the Inventory page (gpu/vk/oot_cheat_items.h): items and their section headings, counts from the game side
#define OOT_MENU_ITEM_LABEL(label, name, kind) label,
#define OOT_MENU_ITEM_KIND(label, name, kind) kind,
#define OOT_MENU_NO_SECTION(name)
constexpr const char* item_names[] = {OOT_CHEAT_ITEMS(OOT_MENU_NO_SECTION, OOT_MENU_ITEM_LABEL)};
constexpr unsigned char item_kinds[] = {OOT_CHEAT_ITEMS(OOT_MENU_NO_SECTION, OOT_MENU_ITEM_KIND)};
constexpr int kItems = sizeof item_names / sizeof item_names[0];
// (each section's first item: a counter that a section heading reads and an item bumps)
constexpr int item_section_count() {
    int n = 0;
#define OOT_MENU_COUNT_SECTION(title) n++;
#define OOT_MENU_SKIP_ITEM(label, name, kind)
    OOT_CHEAT_ITEMS(OOT_MENU_COUNT_SECTION, OOT_MENU_SKIP_ITEM)
    return n;
}
constexpr int kItemSections = item_section_count();
struct ItemSections { TeleportSection s[kItemSections]; };
constexpr ItemSections make_item_sections() {
    ItemSections r{};
    int section = 0, item = 0;
#define OOT_MENU_ADD_SECTION(title) r.s[section].name = title, r.s[section].first = item, section++;
#define OOT_MENU_ADD_ITEM(label, name, kind) item++;
    OOT_CHEAT_ITEMS(OOT_MENU_ADD_SECTION, OOT_MENU_ADD_ITEM)
    return r;
}
constexpr ItemSections item_sections = make_item_sections();
std::atomic<int> item_counts[kItems];   // (-1 until the game side reports: OOT_CHEAT_ITEM_BASE + i)
int item_choice = 0;
int inventory_columns = 1, inventory_capacity = 1;   // (as last drawn: the cards in a row, on a page)
int inventory_filter = 0;   // (All, then the item sections)
int inventory_page = 0;     // (the page shown: the choice's, or another the wheel turned to)
bool inventory_amount = false;   // (Left and Right change the chosen item's amount)
int inventory_begin() { return inventory_filter ? item_sections.s[inventory_filter - 1].first : 0; }
int inventory_end() { return inventory_filter && inventory_filter < kItemSections ? item_sections.s[inventory_filter].first : kItems; }
void inventory_reveal() { inventory_page = (item_choice - inventory_begin()) / std::max(1, inventory_capacity); }
void choose_inventory_filter(int filter) {
    inventory_filter = filter;
    item_choice = inventory_begin();
    inventory_amount = false;
    inventory_reveal();
}
constexpr int kCheatRows = 15;   // (the debug tools' rows: Row::cheat 0 to 14; 11 to 13 Triforce's name pages, 14 Movement speed)
/// A debug tool's value as its row shows it ("" an action: confirm does it)
std::string cheat_value(int i) {
    char t[16];
    switch (i) {
    case 0: return tx_onoff(protect_hearts.load() == 1);
    case 1: return tx_onoff(player_flight.load() >= 0);
    case 4: return snprintf(t, sizeof t, "%02d:00", clock_hour), t;
    case 5: return pouch_items[pouch_item];
    case 6: return snprintf(t, sizeof t, "%+d", pouch_delta), t;
    case 7: return tx_onoff(free_camera.load());
    case 14: return link_speed_names[std::clamp(link_speed.load(), 0, kLinkSpeeds - 1)];
    default: return "";
    }
}
/// The tools that choose with Left and Right (arrows at their value's ends): Set time, Inventory item, Change quantity,
/// Movement speed
bool cheat_chooses(int i) { return i == 4 || i == 5 || i == 6 || i == 14; }
/// Switch age as Kid | Adult, Link's age lit: once the game side has said it (a save loaded)
bool age_shown(int i) { return i == 9 && link_age.load(std::memory_order_relaxed) >= 0; }
/// What confirm does on a tool's row, for its prompt (nullptr: nothing)
const char* cheat_confirm(int i) {
    static const char* const says[kCheatRows] = {"Toggle", "Toggle", "Apply", "Apply", "Set", nullptr, "Apply", "Toggle", "Open list",
                                                 "Switch", "Open", "Open list", "Open list", "Open list", nullptr};
    return i >= 0 && i < kCheatRows ? says[i] : nullptr;
}
constexpr int kRows = sizeof rows / sizeof rows[0];

int cur_tab = TAB_DISPLAY;
int tab_selected[TAB_SIM_TURF + 1] = {};   // (and the pages the rows open: Motion, VR Controls, 3D Settings, VR Settings, Remembered, Simulated turf)
bool is_motion_row(const Row& r) { return r.tab == TAB_CONTROLS && !r.value && !strcmp(r.name, "Motion"); }
/// ((Triforce VR) the page a row opens (Controls: VR Controls; Display: 3D Settings, VR Settings), -1 none. Motion keeps its own
int row_page(const Row& r) {
    if (r.value || r.heading) return -1;
    if (r.tab == TAB_CONTROLS && !strcmp(r.name, "VR Controls")) return TAB_VRPAGE;
    if (r.tab == TAB_DISPLAY && !strcmp(r.name, "3D Settings")) return TAB_3DPAGE;
    if (r.tab == TAB_DISPLAY && !strcmp(r.name, "VR Settings")) return TAB_VRSET;
    return -1;
}
/// ((Triforce VR) a page a row opens: under its row's tab, Back to it
bool sub_page(int tab) { return tab == TAB_MOTION || tab == TAB_VRPAGE || tab == TAB_3DPAGE || tab == TAB_VRSET ||
                                tab == TAB_N64 || tab == TAB_SIM_TURF; }
int page_parent(int tab) {
    return tab == TAB_3DPAGE || tab == TAB_VRSET ? TAB_DISPLAY
         : tab == TAB_N64 || tab == TAB_SIM_TURF ? TAB_GRAPHICS : sub_page(tab) ? TAB_CONTROLS : tab;
}

// (Triforce) The System tab's rows that act on a press, after NX2navi's: Export save, Export save for a bug report, Import a
// save and Bug capture. The work is the host's, on a thread of its own (host/save_share.c, host/bug_capture.c): a press leaves
// what was asked for it to take (HOS_OPT_SHARE_ASK), and it sends back the line the row shows under its help
// (HOS_OPT_SHARE_TEXT, HOS_OPT_SHARE_SAID).
/// Which of them a row is: its HOS_SHARE_* (vk_api.h), what the host is asked and its place in share_lines; 0: none
int share_row(const Row& r) {
    if (r.tab != TAB_SYSTEM || r.value || r.cheat >= 0) return 0;
    if (!strcmp(r.name, "Export save")) return HOS_SHARE_EXPORT;
    if (!strcmp(r.name, "Export save for a bug report")) return HOS_SHARE_EXPORT_BUG;
    if (!strcmp(r.name, "Import a save")) return HOS_SHARE_IMPORT;
    if (!strcmp(r.name, "Bug capture (F8)")) return HOS_SHARE_CAPTURE;
    return 0;
}
std::atomic<int> share_ask{0};              // (what a row asked for, until the host takes it)
std::atomic<int> share_import_waits{0};     // (an imported save waits for the next start: the Import row cancels it)
std::atomic<int64_t> share_busy_until{0};   // (a press waits for the host's answer until then: no second one meanwhile)
std::atomic<int> share_busy_row{0};         // (the row that press was on: its line is the answer)
std::mutex share_mu;                        // (the lines: the host's thread writes them, the drawing reads them)
std::string share_in;                       // (the line the host is sending, a byte a call)
std::string share_lines[HOS_SHARE_NOTICE + 1];   // (by HOS_SHARE_*: what each row shows under its help; the notice's until shown)
std::atomic<bool> share_notice_new{false};   // (a line for the foot of the screen came: menu_tick shows it)
constexpr const char* kShareWorking = "Working...";
/// What a share row shows in its value's place and in the guides: what a press does
const char* share_label(int row) {
    if (row == HOS_SHARE_CAPTURE) return "Capture";
    if (row != HOS_SHARE_IMPORT) return "Export";
    return share_import_waits.load(std::memory_order_relaxed) ? "Cancel the import" : "Import";
}
/// The line under a share row's help: the host's last word on it
std::string share_line(int row) {
    std::lock_guard lk(share_mu);
    if (share_lines[row] == kShareWorking && prof_now() > share_busy_until.load(std::memory_order_relaxed))
        return "The game did not answer. Try again in a moment.";
    return share_lines[row];
}
/// A press on a share row: asked of the host, once until it answers (or ten seconds went by)
void share_press(int row) {
    const int64_t now = prof_now();
    if (now < share_busy_until.load(std::memory_order_relaxed)) return;
    share_busy_until.store(now + 10000000000LL, std::memory_order_relaxed);
    share_busy_row.store(row, std::memory_order_relaxed);
    {
        std::lock_guard lk(share_mu);
        share_lines[row] = kShareWorking;
    }
    const bool cancel = row == HOS_SHARE_IMPORT && share_import_waits.load(std::memory_order_relaxed);
    share_ask.store(cancel ? HOS_SHARE_IMPORT_CANCEL : row, std::memory_order_relaxed);
}

// ---- the rows that take a restart: their values at the start (menu_init, the GPU's at menu_set_gpu_count) ----
namespace mr = menu_restart;
mr::State restart_state;
int restart_slot[kRows];             // (a row's slot in restart_state, -1 none)
const char* restart_names[mr::kMax];
/// What of a row takes the restart: its value; ((Triforce, options_version 7) of a merged row only what of it is read at the
/// start: HDR's Native + RenoDX (the scene's RGBA16F target and RenoDX's shaders, host/nn_vi.c hos_scene_rgba16f and
/// vk_temporal.cpp, from hdr_at_start and renodx_at_start; Off, Expanded and Native change at once: the swapchain is made
/// again at the next present, and the game asks nn::vi for the display's HDR as it goes), Frame generation's NVIDIA DLSS
/// (vk_dlssg.cpp), Frame pacing's Steady (host/nn_vi.c), and the Render resolution's Native (100%) with its share
int restart_value_of(const Row& r) {
    if (r.value == &merged.hdr) return opts.hdr == 2 && opts.renodx ? 1 : 0;
    if (r.value == &merged.framegen) return opts.dlssg;
    if (r.value == &merged.pacing) return opts.steady_fps;
    if (r.value == &merged.view3d) return opts.vr;   // ((Triforce VR) VR on or off alone: the 3D styles apply at once)
    if (r.value == &opts.resolution) return ur::snap(upscaler(), opts.resolution) + (ur::full_scale(opts.dlss) ? 100 : 0);
    // ((Triforce) Audio output: Mono is stereo's layout, the game asked for the same speakers; its average is taken at once)
    if (r.value == &opts.audio_output && *r.value == 3) return 1;
    return *r.value;
}
void restart_init() {
    static bool done = false;
    if (done) return;
    done = true;
    for (int i = 0; i < kRows; i++) {
        restart_slot[i] = rows[i].restart && rows[i].value ? restart_state.add(restart_value_of(rows[i])) : -1;
        if (restart_slot[i] >= 0) restart_names[restart_slot[i]] = rows[i].name;
    }
}
int restart_slot_of(const Row& r) { return restart_slot[&r - rows]; }
/// A row that takes a restart, changed from what the game started with (a row past menu_restart.h's kMax has no slot: never)
bool restart_changed(const Row& r) {
    const int slot = restart_slot_of(r);
    return r.value && r.restart && slot >= 0 && restart_value_of(r) != restart_state.start[slot];
}
/// (Triforce) A row whose value the game does not read as the options are: the Custom size's two sides while the Output
/// resolution is a fixed size (walking the row past a screen's size leaves that size in them). Such a row asks for no restart
bool restart_inert(const Row& r) {
    return (r.value == &opts.output_width || r.value == &opts.output_height) && output_choice(opts.output_res) != OUTPUT_CUSTOM;
}
void restart_values(int* now) {
    for (int i = 0; i < kRows; i++)
        if (restart_slot[i] >= 0) now[restart_slot[i]] = restart_inert(rows[i]) ? restart_state.start[restart_slot[i]] : restart_value_of(rows[i]);
}
/// The rows whose value is not the one the game runs with (a bit a slot)
unsigned restart_pending() {
    int now[mr::kMax];
    restart_values(now);
    return restart_state.pending(now);
}
/// Whether closing the menu now asks to restart: something pending, not declined with Later, and a window to close
bool restart_ask() {
    int now[mr::kMax];
    restart_values(now);
    return app_window() && restart_state.ask(now);
}
std::string restart_list(const char* last) {
    return mr::names(restart_names, restart_state.n, restart_pending(), ", ", last);
}
/// ((Triforce) restart_list in the menu's language, for the restart question: the log keeps the English)
std::string restart_list_shown(const char* last) {
    const char* names[mr::kMax];
    for (int i = 0; i < restart_state.n; i++) names[i] = i18n::tr(restart_names[i]);
    return mr::names(names, restart_state.n, restart_pending(), ", ", last);
}
int ask_sel = 0;   // (the restart question's choice: 0 Later, 1 Restart now)

/// A row on its tab: the debug tools only with them on, the Upscaler only in a build with DLSS or FSR 4, or where AMD
/// FSR 3.1 runs
bool rdx_row(const int* v) {   // (local, RenoDX port)
    return v == &opts.rdx_tonemap || v == &opts.rdx_midgray || v == &opts.rdx_ui_white || v == &opts.rdx_space || v == &opts.rdx_exposure ||
           v == &opts.rdx_highlights || v == &opts.rdx_shadows || v == &opts.rdx_contrast || v == &opts.rdx_saturation ||
           v == &opts.rdx_bloom ||
           // (Triforce: NX2navi's HDR rows)
           v == &opts.rdx_gamma || v == &opts.rdx_match_slope || v == &opts.rdx_tone_slope || v == &opts.rdx_hue_clip ||
           v == &opts.rdx_highlight_sat || v == &opts.rdx_blowout || v == &opts.rdx_flare || v == &opts.rdx_hue || v == &opts.rdx_grade;
}
/// (Triforce) A RenoDX row applies to the tonemapper chosen: the rows only PsychoV35 reads show with PsychoV35 (1), those
/// only RenoDRT reads with RenoDRT (2); every other row whatever is chosen, as before
bool rdx_applies(const int* v) {
    if (v == &opts.rdx_match_slope || v == &opts.rdx_tone_slope || v == &opts.rdx_hue_clip) return opts.rdx_tonemap == 1;
    if (v == &opts.rdx_highlight_sat || v == &opts.rdx_blowout || v == &opts.rdx_flare || v == &opts.rdx_hue || v == &opts.rdx_grade)
        return opts.rdx_tonemap == 2;
    return true;
}
/// (Triforce) The Frame generation row offers AMD FSR 4 only where AMD's library can make the frames (vk_fsr4.h fsr4fg), and
/// ((Triforce, options_version 7) NVIDIA DLSS 2x to 4x, which was a row of its own, only where DLSS frame generation can run:
/// a build with it, on an NVIDIA RTX card DLSS runs on, or where it was asked for at this start). Asked when the menu opens, as
/// the Upscaler's choices are. The saved value's own row (TAB_HIDDEN) ends at AMD FSR 4, so an options file with it loads as
/// it is, before the graphics card is known; a saved AMD FSR 4 that cannot run here stays saved, shows as 2x (tx_framegen)
/// and the arrows step from it as from 8x. As known: the library is asked off the menu's thread (menu_ahead), and the row is
/// set again once it has answered
int framegen_list[mr7::FG_DLSS_LAST + 1];
int framegen_count = 0;
bool dlssg_offered() {
    return mkwvk::dlssg::built() &&
           (mkwvk::dlssg::asked() || (dev.device && dev.props.vendorID == 0x10DE && dlss_why() == DLSS_OK));
}
void framegen_row_sync() {
    static_assert(framegen_rows::kRowMax == 9 && mr7::FG_DLSS == framegen_rows::kRowMax + 1,
                  "the Frame generation row's own values end at 9, NVIDIA DLSS's follow");
    framegen_count = mr7::framegen_choices(framegen_list, fsr4fg::offered_known(), dlssg_offered());
}
/// ((Triforce, options_version 7) The merged rows' values, from the saved ones: before each tick's input and each drawing)
void merged_sync() {
    merged.hdr = mr7::hdr_row(opts.hdr, opts.renodx);
    merged.framegen = mr7::framegen_row(opts.framegen, opts.dlssg);
    merged.pacing = mr7::pacing_row(opts.pace, opts.steady_fps);
    merged.latency = mr7::latency_row(latency_vendor(), opts.reflex, opts.antilag);
    merged.vr_mode = !opts.vr_view ? 0 : opts.vr_camera ? 1 : 2;   // (Theater; Immersive: third person; Full Dive: first)
    merged.view3d = opts.flat3d * 2 + (opts.vr ? 1 : 0);
}
/// ...and a merged row's new value into the saved ones it stands for
void merged_store(const int* v) {
    if (v == &merged.hdr) mr7::hdr_set(merged.hdr, opts.hdr, opts.renodx);
    if (v == &merged.framegen) mr7::framegen_set(merged.framegen, opts.framegen, opts.dlssg);
    if (v == &merged.pacing) mr7::pacing_set(merged.pacing, opts.pace, opts.steady_fps);
    if (v == &merged.latency) mr7::latency_set(merged.latency, latency_vendor(), opts.reflex, opts.antilag);
    if (v == &merged.vr_mode) opts.vr_view = merged.vr_mode > 0, opts.vr_camera = merged.vr_mode == 1;
    if (v == &merged.view3d) opts.vr = merged.view3d & 1, opts.flat3d = merged.view3d >> 1;
}
/// A merged row's next value from v (dir): its choices here
int merged_step(const int* value, int v, int dir) {
    if (value == &merged.framegen) {
        if (!framegen_count) framegen_row_sync();
        return mr7::step_in(framegen_list, framegen_count, v, dir);
    }
    int list[16], n = 0;
    const int hi = value == &merged.vr_mode ? 2 : value == &merged.view3d ? 11 : value == &merged.hdr ? (renodx_built() ? 3 : 2)
                 : value == &merged.pacing ? 3 : mr7::latency_hi(latency_vendor());
    for (int k = 0; k <= hi; k++) list[n++] = k;
    return mr7::step_in(list, n, v, dir);
}
// (Triforce) What the rows ask of NVIDIA's and AMD's libraries: whether DLSS, AMD FSR 4 and FSR 4's frame generation run
// here. Asked at the menu's open on its thread (the presenting one), NGX's start and AMD's loader held the first open of
// the options 2.1 s (test11). Now asked once, on a thread of its own, once the game's first frame is up (menu_tick), or at an open
// before that; until the answers are in, the rows show what is known (DLSS and FSR 4 as offered, AMD FSR 4's frame
// generation as not known yet), and are set again when they come. A choice of DLSS or FSR 4 before then starts it where it
// runs, as before (its start waits for the answer there). The probes are the libraries' own (dlss_probe, fsr4_probe,
// fsr4fg::why): once each, under their own locks. TRIFORCE_MENU_AHEAD=0: asked at the open on the menu's thread, as before
std::atomic<int> ahead_state{0};   // (0 not asked, 1 being asked, 2 answered)
bool ahead_allowed() {
    static const bool on = !getenv("TRIFORCE_MENU_AHEAD") || atoi(getenv("TRIFORCE_MENU_AHEAD")) != 0;
    return on;
}
void ahead_thread() {
    const int64_t t0 = prof_now();
    dlss_probe();
    const int64_t t1 = prof_now();
    fsr4_probe();
    const int64_t t2 = prof_now();
    (void)fsr4fg::why();
    const int64_t t3 = prof_now();
    xess_probe();   // ((Triforce) Intel XeSS's context made once, where its library is there)
    const int64_t t4 = prof_now();
    logf("menu: the upscalers asked ahead of the menu, on a thread of their own: NVIDIA DLSS %.0f ms, AMD FSR 4 %.0f ms, its frame "
         "generation %.0f ms, Intel XeSS %.0f ms", (t1 - t0) / 1e6, (t2 - t1) / 1e6, (t3 - t2) / 1e6, (t4 - t3) / 1e6);
    ahead_state.store(2, std::memory_order_release);
}
void menu_ahead() {
    if (!dev.device) return;
    if (!ahead_allowed()) {   // (as before: on this thread, at the open)
        dlss_probe(), fsr4_probe(), (void)fsr4fg::why(), xess_probe();
        ahead_state.store(2, std::memory_order_release);
        return;
    }
    int none = 0;
    if (ahead_state.compare_exchange_strong(none, 1)) std::thread(ahead_thread).detach();
}
bool group_shown(int heading);
/// A row on its tab: the debug tools only with them on, the Upscaler only in a build with DLSS or FSR 4, or where AMD FSR 3.1
/// runs, ...; ((Triforce, options_version 7) a group's heading while a row of its group is shown, group_shown)
bool row_shown(int i) {
    const int up = rows[i].value == &opts.upscale_pre || rows[i].value == &opts.dlss_model || rows[i].value == &opts.aa ||
                           rows[i].value == &opts.fsr4_model
                       ? upscaler()
                       : ur::GAME;
    return (rows[i].cheat < 0 || cheats_on()) &&
           (rows[i].name != kUseWindowSize || (opts.output_res == OUTPUT_CUSTOM && !custom_env())) &&
           // ((Triforce) the Custom size's two sides only while the Output resolution is Custom)
           ((rows[i].value != &opts.output_width && rows[i].value != &opts.output_height) ||
            output_choice(opts.output_res) == OUTPUT_CUSTOM) &&
           // ((Triforce) 11-24: the Upscaler everywhere: its Off runs on any GPU)
           (rows[i].value != &opts.dlss || ur::upscaler_shown(true)) &&
           // ((Triforce, options_version 7) the DLSS model with NVIDIA DLSS as the Upscaler alone; Upscale before bloom with any
           // upscaler but the game's own, which it does nothing with (vk_temporal.cpp pre_wanted); Anti-aliasing with the game's
           // own alone: DLSS and FSR smooth the edges themselves (aa_rows.h))
           (rows[i].value != &opts.dlss_model || (ur::model_shown(dlss_built()) && ur::is_dlss(up))) &&
           // ((Triforce) the FSR 4 model with AMD FSR 4 as the Upscaler alone, where its Lite provider is hooked: vk_fsr4.cpp)
           (rows[i].value != &opts.fsr4_model ||
            (ur::fsr4_model_shown(fsr4_why() == FSR_OK, fsr4_lite_available()) && ur::is_fsr4(up))) &&
           // ((Triforce) 11-24: Off as the game's own here: the game's SMAA still runs on its input, nothing to upscale early)
           (rows[i].value != &opts.upscale_pre || (up != ur::GAME && up != ur::OFF)) &&
           (rows[i].value != &opts.aa || up == ur::GAME || up == ur::OFF) &&
           // ((Triforce, 11-22, N64 Classic) Remembered settings with Remembered chosen)
           (!is_n64_page_row(rows[i]) || n64_preset() == n64_rules::REMEMBERED) &&
           sim_turf_row_shown(rows[i]) &&   // ((Triforce, 11-24) the Simulated turf page's, by Use global multipliers)
           // (local, RenoDX port: its rows with HDR Native, in a build with its shaders; Triforce: and its own row on, and
           // of the rows one tonemapper alone reads those of the one chosen. (options_version 7) The UI brightness is one of them:
           // without RenoDX the HUD's white is the picture's, Paper white)
           (!rdx_row(rows[i].value) || (opts.hdr == 2 && renodx_built() && opts.renodx && rdx_applies(rows[i].value))) &&
           // ((Triforce, options_version 7) Paper white and Peak brightness with HDR on; the Ultrawide's HUD and menu sides with a
           // shape wider than 16:9 (21:9 and 32:9: 16:10 is narrower, ultrawide_rows.h); Sprint mode with a sprint button, Walk
           // scale with a walk key; Low latency where Reflex or Anti-Lag 2 runs)
           ((rows[i].value != &opts.hdr_white && rows[i].value != &opts.hdr_peak) || opts.hdr != 0) &&
           ((rows[i].value != &opts.wide_hud && rows[i].value != &opts.wide_menus) || (output_picture_of(opts.output_res, opts.ultrawide).w > output_picture_of(opts.output_res, opts.ultrawide).h * (16.0 / 9.0) * 1.01)) &&
           (rows[i].value != &opts.sprint_mode || opts.sprint_button != 0) && (rows[i].value != &opts.walk_scale || opts.walk_key != 0) &&
           (rows[i].value != &opts.mic_gain || opts.mic != 0) &&   // ((Triforce) the Microphone gain with a microphone chosen)
           // ((Triforce) HUD placement on a 16:9 or wider picture (host/hos_wide_ui.c leaves a narrower one), Custom's rows with it)
           ((rows[i].value != &opts.hud_placement && !hud_custom_row(rows[i].value)) ||
            (output_picture_of(opts.output_res, opts.ultrawide).w >= output_picture_of(opts.output_res, opts.ultrawide).h * (16.0 / 9.0) * 0.99 &&
             (rows[i].value == &opts.hud_placement || opts.hud_placement == 1))) &&
           (rows[i].name != kTestMic || (opts.mic != 0 && host && host->mic_test)) &&   // ((Triforce) 11-24: and its test)
           // ((Triforce) 11-24: the ReShade User preset's file and Rescan rows with User chosen)
           (!reshade_menu::user_row(rows[i].name, rows[i].value) || opts.reshade == reshade::user_preset) &&
           // ((Triforce) 11-24: the Output device row where the host lists devices, or one was chosen)
           (rows[i].value != &output_pick || (can_outputs() && (!output_devices.empty() || output_missing))) &&
           (rows[i].value != &merged.latency || latency_vendor() != mr7::LATENCY_NONE) &&
           // ((Triforce) 11-24: Frame generation by with Frame generation at Auto or 2x to 8x, the renderer's own values)
           (rows[i].value != &opts.fg_by || framegen_rows::by_applies(opts.framegen)) &&
#ifdef _WIN32   // ((Triforce) the Fullscreen screen with two screens or more: host/display.c, Windows only)
           (rows[i].value != &opts.fs_screen || fs_screen_labels.size() > 1) &&
#else
           rows[i].value != &opts.fs_screen &&
#endif
#ifndef _WIN32   // (Triforce: the lazy write-back's fault handler pays on Windows only, vk_memory.cpp)
           rows[i].value != &opts.lazy_write_back &&
#endif
           // (Triforce, 11-13: the Menu shortcut row chooses the keys that open the options from anywhere: gone with them)
           (rows[i].value != &opts.menu_shortcut || overlay_allowed()) &&
           // (Triforce: the Game language row only with a language.txt that names languages to choose from)
           (rows[i].value != &opts.language || lang_count > 1) &&
           // (Triforce: the mods' cheats: as many rows as the host named, and their heading with them)
           (!rows[i].heading || strcmp(rows[i].name, kModCheatHeading) || mod_cheats.shown() > 0) &&
           // (Triforce: the Achievements row once the host has named them: off, or none, and there is no such row)
           (strcmp(rows[i].name, kAchRow) || rows[i].tab != TAB_SYSTEM || ach_list.shown() > 0) &&
           // (Triforce: and the Save files row once the host has named the files)
           (strcmp(rows[i].name, kFilesRow) || rows[i].tab != TAB_SYSTEM || save_files.shown() > 0) &&
           (mod_cheat_slot(rows[i].name) < 0 || mod_cheat_slot(rows[i].name) < mod_cheats.shown()) &&
           (!rows[i].heading || rows[i].tab == TAB_DEBUG || group_shown(i));
}
/// ((Triforce, options_version 7) A group's heading is shown while a row of its group is: the rows of its tab after it, up to the
/// next heading there. The Debug tab's Developer heading is debug_rows')
bool group_shown(int heading) {
    for (int j = heading + 1; j < kRows; j++) {
        if (rows[j].tab != rows[heading].tab) continue;
        if (rows[j].heading) return false;
        if (row_shown(j)) return true;
    }
    return false;
}
int tab_row_count(int t) {
    int c = 0;
    for (int i = 0; i < kRows; i++) if (rows[i].tab == (MenuTab)t && row_shown(i)) c++;
    return c;
}

int tab_row_to_global(int t, int local_idx) {
    int count = 0;
    for (int i = 0; i < kRows; i++) {
        if (rows[i].tab == (MenuTab)t && row_shown(i)) {
            if (count == local_idx) return i;
            count++;
        }
    }
    return 0;
}

std::atomic<bool> open_now{false};
bool menu_refresh = false;
// (a value too long for its row, a GPU's name: the selected row's slides through it, a character a step, resting at
// each end; the other rows end it with "...". The drawing (fit) says how far it can slide, menu_tick moves it)
int marquee_pos = 0, marquee_max = 0;
int64_t marquee_next = 0;
constexpr int64_t kMarqueeStep = 150000000LL, kMarqueeRest = 1200000000LL;   // (ns)
// (hookshot) the mouse (menu_tick): the tab strip's part under the cursor (a tab 0 to TAB_COUNT - 1, TAB_COUNT the previous,
// TAB_COUNT + 1 the next; -1 none); the slider held with the left button (its row in the tab, -1 none)
int hover_tab = -1;
int drag_row = -1;
bool mouse_read = false;   // (the menu has read the mouse since it opened)
bool is_slider(const Row& r) { return r.value == &opts.sharpness || r.value == &opts.mouse_sens || r.value == &opts.gyro_sens_x || r.value == &opts.gyro_sens_y || r.value == &opts.output_width || r.value == &opts.output_height ||
                                    ((r.tab == TAB_VRSET || r.tab == TAB_VRPAGE) && r.value && r.hi - r.lo > 2); }
/// (a scale: the arrows and a click stop at its ends; Rumble strength would go from Off to its strongest)
bool stops_at_ends(const Row& r) { return (r.tab == TAB_SIM_TURF && r.hi > 1) || r.value == &opts.mouse_sens || r.value == &opts.fov || r.value == &opts.mic_gain || r.value == &opts.rumble || r.value == &opts.rumble_curve || r.value == &opts.lstick_dead_zone || r.value == &opts.rstick_dead_zone || r.value == &opts.walk_scale || r.value == &opts.gyro_sens_x || r.value == &opts.gyro_sens_y || r.value == &opts.output_width || r.value == &opts.output_height; }
/// (the ini's Rumble strength on the menu's steps: 0 to 300, the nearest 25)
int rumble_step(int v) { return (std::min(std::max(v, 0), 300) + 12) / 25 * 25; }
std::string ini_path() {
    char exe[MAX_PATH];
    const DWORD n = game_module_path(exe, MAX_PATH);
    std::string dir(exe, n);
    return dir.substr(0, dir.find_last_of("\\/") + 1) + "triforce_options.ini";
}
// (Triforce VR) the VR rows by their key (vk_xr_cfg; its lower case is the options file's), and their values as text where a
// value is a choice (choices[v], "|"-separated); a number's text is the number
struct VrKey {
    const char* key;
    int* value;
    const char* choices;
};
const VrKey vr_keys[] = {
    {"VR", &opts.vr, nullptr},
    {"VR_VIEW", &opts.vr_view, "screen|head"},
    {"VR_SCREEN_SIZE", &opts.vr_screen_size, nullptr},
    {"VR_SCREEN_CURVE", &opts.vr_screen_curve, nullptr},
    {"VR_CAMERA", &opts.vr_camera, "first|third"},
    {"VR_VIEW_SCALE", &opts.vr_view_scale, nullptr},
    {"VR_STEREO", &opts.vr_stereo, "performant|balanced|accurate"},
    {"FLAT3D", &opts.flat3d, "off|anaglyph|sbs|crosseye|tab|cardboard"},
    {"FLAT3D_DEPTH", &opts.flat3d_depth, nullptr},
    {"FLAT3D_SCREEN", &opts.flat3d_screen, nullptr},
    {"VR_DEPTH", &opts.vr_depth, nullptr},
    {"VR_EYE_UP", &opts.vr_eye_up, nullptr},
    {"VR_EYE_SIDE", &opts.vr_eye_side, nullptr},
    {"VR_EYE_FORWARD", &opts.vr_eye_forward, nullptr},
    {"VR_EVENT_UP", &opts.vr_event_up, nullptr},
    {"VR_CUTSCENES", &opts.vr_cutscenes, "classic|first"},
    {"VR_AIM_TILT", &opts.vr_aim_tilt, nullptr},
    {"VR_TURN_SPEED", &opts.vr_turn_speed, nullptr},
    {"VR_ZOOM_SPEED", &opts.vr_zoom_speed, nullptr},
    {"VR_TURN", &opts.vr_turn, "smooth|snap"},
    {"VR_SNAP_ANGLE", &opts.vr_snap_angle, nullptr},
    {"VR_VIGNETTE", &opts.vr_vignette, "off|on"},
    {"VR_PHYS_SHOW", &opts.vr_phys_show, nullptr},
    {"VR_SWING_SPEED", &opts.vr_swing_speed, nullptr},
    {"VR_CHARGE_REACH", &opts.vr_charge_reach, nullptr},
    {"VR_HUD_SIZE", &opts.vr_hud_size, nullptr},
    {"VR_BODY", &opts.vr_body, "hidden|arms"},
    {"VR_SCHEME", &opts.vr_scheme, "gesture|simplified"},
    {"VR_ARM_REACH", &opts.vr_arm_reach, nullptr},
};
const char* ini_key(const Row& r) {
    if (r.key) return r.key;
    if (r.value == &opts.output_res) return "output_res";   // (host/nn_applet.c reads it at the start)
    // (rows renamed since their values were first saved keep their keys: an options file from before still loads, and the
    // readers before the menu find them: host/hos_main.c ultrawide=, host/oot_wide_hud.c ultrawide_hud=. (Triforce,
    // options_version 7) The rows renamed as their groups came, a group's name taken off theirs)
    static const char* const kept[][2] = {   // (the row's name now, the key its value was saved under)
        {"Aspect ratio", "ultrawide"}, {"HUD position", "ultrawide_hud"},
        {"Menu sides", "ultrawide_menus"}, {"Paper white", "hdr_paper_white"}, {"Peak brightness", "hdr_peak_brightness"},
        {"UI brightness", "renodx_ui_brightness"}, {"Tonemapper", "renodx_tonemapper"}, {"Gamma correction", "renodx_gamma_correction"},
        {"Color space", "renodx_color_space"}, {"Exposure", "renodx_exposure"}, {"Middle gray", "renodx_midgray"},
        {"Match tone slope", "renodx_match_tone_slope"}, {"Tone slope", "renodx_tone_slope"}, {"Hue clip", "renodx_hue_clip"},
        {"Highlight saturation", "renodx_highlight_saturation"}, {"Blowout", "renodx_blowout"}, {"Flare", "renodx_flare"},
        {"Hue correction", "renodx_hue_correction"}, {"Color grading", "renodx_color_grading"}, {"Highlights", "renodx_highlights"},
        {"Shadows", "renodx_shadows"}, {"Contrast", "renodx_contrast"}, {"Saturation", "renodx_saturation"},
        {"Bloom", "renodx_bloom"},
        // ((Triforce) HUD placement's Custom rows, by the keys their values are)
        {"Hearts and magic across", "hud_health_x"}, {"Hearts and magic up", "hud_health_y"}, {"Hearts and magic size", "hud_health_scale"},
        {"Buttons across", "hud_buttons_x"}, {"Buttons up", "hud_buttons_y"}, {"Buttons size", "hud_buttons_scale"},
        {"Minimap across", "hud_minimap_x"}, {"Minimap up", "hud_minimap_y"}, {"Minimap size", "hud_minimap_scale"},
        // ((Triforce, 11-22, N64 Classic) the Remembered page's rows, under n64_rules.h kSpec's keys (tests/test_n64_row.py holds
        // the two the same; its saturation is Colour saturation, RenoDX's row having Saturation)
        {"Frame rate", "n64_rem_fps"}, {"3D resolution", "n64_rem_lines"}, {"Colour", "n64_rem_colour"}, {"Dither", "n64_rem_dither"},
        {"Texture blur", "n64_rem_blur"}, {"CRT TV", "n64_rem_tv"}, {"Scanlines", "n64_rem_scanlines"}, {"Mask", "n64_rem_mask"},
        {"Mask strength", "n64_rem_mask_strength"}, {"Colour bleed", "n64_rem_bleed"}, {"Glow", "n64_rem_glow"},
        {"Curvature", "n64_rem_curvature"}, {"Colour saturation", "n64_rem_saturation"},
        // ((Triforce) Auto (this PC) and its state, auto_settings.h)
        {"Auto (this PC)", "auto_pc"}, {"Auto tune", "auto_tune"}, {"Auto for", "auto_for"},
        // ((Triforce) 11-24) the Controller speaker rows, by the host's HOS_PAD_SPEAKER_* switches' names (host/pad_speaker.c)
        {"Speaker volume", "pad_speaker_volume"}, {"Controller sync", "pad_speaker_sync"},
        {"Headphones on the controller", "pad_speaker_headphones"}, {"Headphone volume", "pad_speaker_headphone_volume"},
        {"Navi's voice", "pad_speaker_navi_voice"}, {"Navi's flight sounds", "pad_speaker_navi_sound"},
        {"Z-targeting", "pad_speaker_target"}, {"Ocarina", "pad_speaker_ocarina"}, {"Pick-ups", "pad_speaker_pickup"},
        {"Items", "pad_speaker_item"}, {"Fairies", "pad_speaker_fairy"}, {"Interface sounds", "pad_speaker_ui"},
        {"Stone of Agony", "pad_speaker_agony"}, {"Low health alarm", "pad_speaker_low_health"},
        {"Fishing", "pad_speaker_fishing"}, {"Bottles", "pad_speaker_bottle"},
    };
    for (const auto& k : kept)
        if (r.value && !strcmp(r.name, k[0])) return k[1];
    if (r.value == &opts.resolution) return "resolution";
    if (r.value == &opts.fps_cap) return "frame_rate_cap";   // (host/nn_vi.c reads it at the start)
    if (r.value == &opts.dlss) return "dlss";   // (as opts.dlss and RX_VK_DLSS)
    // ((Triforce) NX2navi's key, not the name cut at 31 letters; vk_replay.cpp tail_wanted reads it at the start)
    if (!strcmp(r.name, "Start next frame early")) return "tail_early";
    static char k[32];
    size_t n = 0;
    for (const char* p = r.name; *p && n + 1 < sizeof k; p++) k[n++] = *p == ' ' ? '_' : (char)tolower(*p);
    k[n] = 0;
    return k;
}
/// (Triforce) A row kept in triforce_options.ini: every row with a value but the Game language, whose choice is
/// language.txt's
bool ini_row(const Row& r) { return r.value && r.value != &opts.language && !is_merged(r.value) && r.value != &output_pick; }
// ((Triforce, handoff §9) The options file's other writers. ini_base: what the game had for each of the file's lines when it last
// read (menu_init) or wrote (save) the file; save merges each line it writes by its key with what the file has now
// (ini_merge.h) and writes the file whole (file_whole.h: a reader at a start, the host's or the renderer's, never meets half a
// file). RX_VK_OPTIONS_MERGE=0: the game's own values written over the file in place, as before)
ini_merge::Map ini_base;
std::mutex ini_mu;   // (save runs on the presenting thread and, for the mouse's sensitivity keys, on the host's: option 7)
bool options_merge_on() {
    static const bool on = !(getenv("RX_VK_OPTIONS_MERGE") && !strcmp(getenv("RX_VK_OPTIONS_MERGE"), "0"));
    return on;
}
// (Triforce) the Game language row's file, beside the options file: the game folder's language.txt
std::string lang_path() {
    const std::string ini = ini_path();
    return ini.substr(0, ini.find_last_of("\\/") + 1) + "language.txt";
}
/// Its bytes as they are (64 KiB at most: a larger file is not that one)
bool lang_read(std::string& text) {
    constexpr size_t kMost = 65536;
    text.clear();
    FILE* f = fopen(lang_path().c_str(), "rb");
    if (!f) return false;
    char part[4096];
    for (size_t n; text.size() <= kMost && (n = fread(part, 1, sizeof part, f)) > 0;) text.append(part, n);
    fclose(f);
    return text.size() <= kMost;
}
/// The file written whole beside it and put in its place, so that a write that fails leaves the file as it was
bool lang_write(const std::string& text) {
    const std::string path = lang_path(), fresh = path + ".new";
    FILE* f = fopen(fresh.c_str(), "wb");
    if (!f) return false;
    bool ok = fwrite(text.data(), 1, text.size(), f) == text.size();
    ok = fclose(f) == 0 && ok;
#ifdef _WIN32
    ok = ok && MoveFileExA(fresh.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING) != 0;
#else
    ok = ok && rename(fresh.c_str(), path.c_str()) == 0;
#endif
    if (!ok) remove(fresh.c_str());
    return ok;
}
/// The row from the file, at the start: its entries, and the one the file chooses (English (US) when it chooses none, as
/// the host answers then)
void lang_load() {
    std::string text;
    lang_count = 0, lang_saved = -1;
    if (lang_read(text)) {
        const gl::File f = gl::read(text);
        lang_count = gl::offered(f, lang_entries);
        const int now = f.chosen >= 0 ? f.chosen : gl::kDefault;
        for (int i = 0; i < lang_count; i++)
            if (lang_entries[i] == now) lang_saved = i;
    }
    if (lang_saved < 0) lang_count = 0;
    opts.language = std::max(lang_saved, 0);
    {   // ((Triforce) the language the game runs in, as the host reads it: HOS_LANGUAGE over the file; English (US) when the
        // one it names is none of the game's. The Menu language row's Auto follows it)
        const char* env = getenv("HOS_LANGUAGE");
        const int file = text.empty() ? -1 : gl::read(text).chosen;
        const int run = env ? gl::find(env) : file;
        i18n::set_game_started(run >= 0 ? run : gl::kDefault);
    }
    for (Row& r : rows)
        if (r.value == &opts.language) r.hi = std::max(lang_count - 1, 0);
}
/// At a save: the row's choice into language.txt, when it is not the file's already. The file is read again first (it may
/// have been edited since the start) and only its choice line changes; a language it no longer names is not written, and
/// the row goes back to the file's
void lang_store() {
    if (lang_count < 2 || opts.language == lang_saved || opts.language < 0 || opts.language >= lang_count) return;
    const int language = lang_entries[opts.language];
    std::string text;
    bool ok = false;
    if (lang_read(text)) {
        const std::string out = gl::write(text, language);
        ok = gl::read(out).chosen == language && (out == text || lang_write(out));
    }
    lang_failed = !ok;
    if (ok) {
        lang_saved = opts.language;
        logf("menu: the game's language from the next start: %s (language.txt)", gl::kLanguages[language].code);
    } else {
        logf("menu: language.txt could not be written, or no longer names %s: the game's language stays as it was",
             gl::kLanguages[language].code);
        opts.language = lang_saved;
    }
}
// (hookshot) the controls, kept by the host (host/nn_hid.c reads them back from here): pad_<button>, key_<button>
const char* const bind_names[HOS_KEY_N] = {"a", "b", "x", "y", "ls", "rs", "l", "r", "zl", "zr", "plus", "minus",
                                           "left", "up", "right", "down", "move_up", "move_down", "move_left",
                                           "move_right", "cam_up", "cam_down", "cam_left", "cam_right",
                                           "note_l", "note_r", "note_a", "note_y", "note_x",
                                           "toggle_hud"};   // ((Triforce) Toggle HUD, host/nn_hid.c hud_shortcut)
bool can_bind() { return host && host->binding && host->bind && host->pad_raw; }
const char* tx_pad_layout(int v) {
    static const char* t[] = {"Nintendo (Def)", "Xbox / PC", "Swap Face", "Custom"};
    return t[std::min(std::max(v, 0), 3)];
}
void apply_pad_layout(int layout) {
    if (!can_bind()) return;
    if (layout == 0) { // Nintendo (Default: Bottom=B, Right=A, Top=X, Left=Y)
        host->bind(HOS_BIND_PAD, HOS_SW_A, 0, HOS_PAD_EAST);
        host->bind(HOS_BIND_PAD, HOS_SW_B, 0, HOS_PAD_SOUTH);
        host->bind(HOS_BIND_PAD, HOS_SW_X, 0, HOS_PAD_NORTH);
        host->bind(HOS_BIND_PAD, HOS_SW_Y, 0, HOS_PAD_WEST);
    } else if (layout == 1) { // Xbox / PC Standard (Bottom=A, Right=B, Left=X, Top=Y)
        host->bind(HOS_BIND_PAD, HOS_SW_A, 0, HOS_PAD_SOUTH);
        host->bind(HOS_BIND_PAD, HOS_SW_B, 0, HOS_PAD_EAST);
        host->bind(HOS_BIND_PAD, HOS_SW_X, 0, HOS_PAD_WEST);
        host->bind(HOS_BIND_PAD, HOS_SW_Y, 0, HOS_PAD_NORTH);
    } else if (layout == 2) { // Swap Face Buttons (Bottom=A, Right=B, Top=X, Left=Y)
        host->bind(HOS_BIND_PAD, HOS_SW_A, 0, HOS_PAD_SOUTH);
        host->bind(HOS_BIND_PAD, HOS_SW_B, 0, HOS_PAD_EAST);
        host->bind(HOS_BIND_PAD, HOS_SW_X, 0, HOS_PAD_NORTH);
        host->bind(HOS_BIND_PAD, HOS_SW_Y, 0, HOS_PAD_WEST);
    }
}
int detect_pad_layout() {
    if (!can_bind()) return opts.pad_layout;
    const int a = host->binding(HOS_BIND_PAD, HOS_SW_A, 0);
    const int b = host->binding(HOS_BIND_PAD, HOS_SW_B, 0);
    const int x = host->binding(HOS_BIND_PAD, HOS_SW_X, 0);
    const int y = host->binding(HOS_BIND_PAD, HOS_SW_Y, 0);
    if (a == HOS_PAD_EAST && b == HOS_PAD_SOUTH && x == HOS_PAD_NORTH && y == HOS_PAD_WEST) return 0;
    if (a == HOS_PAD_SOUTH && b == HOS_PAD_EAST && x == HOS_PAD_WEST && y == HOS_PAD_NORTH) return 1;
    if (a == HOS_PAD_SOUTH && b == HOS_PAD_EAST && x == HOS_PAD_NORTH && y == HOS_PAD_WEST) return 2;
    return 3;
}
// (hookshot) the row's choice to the host: off, the default, or a microphone by its name (and its place in the host's list,
// -1 while it is unplugged: of two with one name, the one chosen). Unplugged, the name is the kept one, cut: the host takes
// a name that starts with it
// ((Triforce) 11-24) The playback devices listed again (one plugged in since shows up), the row on output_want's
void refresh_outputs() {
    output_devices.clear();
    if (can_outputs()) {
        const int count = std::min(std::max(0, host->audio_output_count()), 256);
        for (int i = 0; i < count; i++) {
            char id[HOS_OUTPUT_ID_CAP], name[HOS_OUTPUT_NAME_CAP];
            if (host->audio_output_info(i, id, sizeof id, name, sizeof name)) output_devices.push_back({id, name});
        }
    }
    output_pick = 0;
    for (size_t i = 0; i < output_devices.size(); i++)
        if (!output_want.empty() && output_devices[i].id == output_want) output_pick = (int)i + 1, output_saved_name = output_devices[i].name;
    output_missing = !output_want.empty() && !output_pick;
    if (output_missing) output_pick = (int)output_devices.size() + 1;
    for (Row& r : rows)
        if (r.value == &output_pick) r.hi = (int)output_devices.size() + (output_missing ? 1 : 0);
}
// (the row changed by the player: the choice is now this device, by its id; the "(not connected)" entry only while chosen)
void output_chosen() {
    if (output_forced() || !can_outputs()) return;
    if (output_pick <= 0) output_want.clear(), output_saved_name.clear();
    else if ((size_t)(output_pick - 1) < output_devices.size()) {
        output_want = output_devices[(size_t)output_pick - 1].id;
        output_saved_name = mic_key(output_devices[(size_t)output_pick - 1].name.c_str());
    }
    host->audio_output_select(output_want.c_str());
    refresh_outputs();
}
void mic_tell_host() {
    if (!can_mic()) return;
    if (opts.mic <= 1) host->mic_select(opts.mic <= 0 ? 0 : 1, "", -1);
    else if (mic_missing && opts.mic == 2 + mic_listed) host->mic_select(2, mic_want.c_str(), -1);   // (the kept name, cut)
    else host->mic_select(2, host->mic_name(opts.mic - 2), opts.mic - 2);   // (its whole name: the ini's cut is only the ini's)
}
void mic_row_ends() {
    for (Row& r : rows)
        if (r.value == &opts.mic) r.hi = 1 + mic_listed + (mic_missing ? 1 : 0);
}
// (hookshot) the microphones listed again (one plugged in since shows up), the row on mic_want's: the one at the row's place
// when it still has that name (two microphones of one name: the second stays chosen), else the first of that name, else
// its "(not connected)" entry while it is unplugged
void refresh_mics() {
    if (!can_mic()) {
        if (opts.mic >= 2) opts.mic = 1;
        return;
    }
    mic_listed = std::min(host->mic_count(), kMaxMics);
    int at = -1;
    if (!mic_want.empty()) {
        if (opts.mic >= 2 && opts.mic - 2 < mic_listed && mic_key(host->mic_name(opts.mic - 2)) == mic_want) at = opts.mic - 2;
        for (int i = 0; i < mic_listed && at < 0; i++)
            if (mic_key(host->mic_name(i)) == mic_want) at = i;
        opts.mic = at >= 0 ? at + 2 : 2 + mic_listed;
    } else if (opts.mic >= 2) {
        opts.mic = 1;
    }
    mic_missing = !mic_want.empty() && at < 0;
    mic_row_ends();
    mic_tell_host();
}
// (the row changed by the player: the choice is now this one, by its name; the "(not connected)" entry is kept only while
// it is the one chosen)
void mic_chosen() {
    if (opts.mic >= 2 && !(mic_missing && opts.mic == 2 + mic_listed)) {
        mic_want = mic_key(host->mic_name(opts.mic - 2)), mic_missing = false;
    } else if (opts.mic < 2) {
        mic_want.clear(), mic_missing = false;
    }
    mic_row_ends();
    mic_tell_host();
}
void save() {
    lang_store();   // (Triforce: the Game language row's choice is language.txt's, not this file's)
    const std::lock_guard ini_lock(ini_mu);
    const bool merge = options_merge_on();
    // (hookshot) the lines that are not the menu's are kept: the controls, pad_ and key_ (host/nn_hid.c)
    // (and every other line the menu does not write, such as discord_app_id=: they were dropped at the next save)
    std::string kept, others;
    // With no remembered size, leave a line first added outside after menu_init to its writer.
    const bool own_custom = remembered_custom.h || ini_base.count("output_custom_size") || !merge;
    ini_merge::Map disk;   // ((Triforce) the file's lines as they are now)
    if (FILE* f = fopen(ini_path().c_str(), "r")) {
        char line[1024];   // ((Triforce) a discord_text= template is up to 512 bytes: a line cut in two lost its end)
        while (fgets(line, sizeof line, f)) {
            ini_merge::add_line(disk, line);
            if (!strncmp(line, "pad_", 4) || !strncmp(line, "key_", 4)) {
                kept += line;
                continue;
            }
            const char* eq = strchr(line, '=');
            if (!eq || eq == line) continue;
            const std::string key(line, (size_t)(eq - line));
            bool mine = (key == "output_custom_size" && own_custom) || key == "microphone_device" || key == "options_version" || key == "debug_tab" || key == "gpu_device_name" ||
                        key == "fullscreen_screen_name" || key == "audio_output_device_id" || key == "audio_output_device_name";
            // (Triforce: the RivaTuner limit row of the test builds is gone, RivaTuner being the limiter wherever it can be:
            // its line is read by nothing and is not written again. (options_version 7) Nor are the lines of the rows whose job
            // is done otherwise now: merged_rows.h kDropped, read once by menu_init's migration)
            mine |= key == "rivatuner_limit";
            for (const char* dropped : merged_rows::kDropped) mine |= key == dropped;
            for (const Row& r : rows)
                if (!mine && r.value && key == ini_key(r)) mine = true;
            if (!mine) others += line, others += others.back() == '\n' ? "" : "\n";
        }
        fclose(f);
    }
    // ((Triforce) each line the game writes: its value, or the file's where it was changed outside and not in the game since
    // (ini_merge::pick); now: the game's own values, the base for the next save)
    std::string out, outside;
    ini_merge::Map now;
    const auto put = [&](const std::string& key, const std::string& value) {
        bool taken = false;
        out += key + "=" + (merge ? ini_merge::pick(key, value, ini_base, disk, &taken) : value) + "\n";
        now[key] = value;
        if (taken) outside += (outside.empty() ? "" : ", ") + key;
    };
    for (const Row& r : rows)
        if (ini_row(r)) put(ini_key(r), std::to_string(*r.value));
    if (remembered_custom.h) put("output_custom_size", std::to_string(remembered_custom.w) + "x" + std::to_string(remembered_custom.h));
    else if (own_custom && disk.count("output_custom_size")) put("output_custom_size", "");
    if (!mic_want.empty()) put("microphone_device", mic_want);   // (hookshot: also while it is unplugged)
    if (!output_want.empty()) {   // ((Triforce) 11-24: the Output device row's device, by its id; also while it is unplugged)
        put("audio_output_device_id", output_want);
        put("audio_output_device_name", output_saved_name);
    }
    // ((Triforce) 11-20) the GPU device row's card by its name beside its number: the chosen card's as this run lists them;
    // a choice past the list (the card taken out) keeps the name it had; Auto writes none
    if (opts.gpu_device <= 0) gpu_want.clear();
    else if ((size_t)opts.gpu_device <= gpu_device_names.size()) gpu_want = mic_key(gpu_device_names[(size_t)opts.gpu_device - 1].c_str());
    if (!gpu_want.empty()) put("gpu_device_name", gpu_want);
    // ((Triforce) 11-24) the Fullscreen screen by its name and size beside its number; Automatic writes none
    if (opts.fs_screen > 0 && opts.fs_screen <= (int)fs_screen_labels.size()) put("fullscreen_screen_name", fs_key(fs_screen_labels[(size_t)opts.fs_screen - 1]));
    // (2: game_speed below 2 was only ever the old default, see menu_init; 3: the mouse's buttons are bindings, see
    // host/nn_hid.c binds_load; 4: Descriptor reuse on by default, see menu_init and vk_draw.cpp desc_slotgen_on; 5: Sampler
    // cache, Fast pipeline link, Lazy write-back, Opaque textures as BC1 and NVIDIA Reflex On + Boost by default, see menu_init;
    // (Triforce) 6: Start next frame early on by default, see menu_init and vk_replay.cpp tail_wanted; the Ultrawide row's 1 is
    // 16:10, no longer the monitor's shape, see ultrawide_rows.h; (Triforce) 7: Frame pacing on by default, see menu_init;
    // 8: the rows merged and grouped, the handheld profile an Output resolution, the shared stick dead zone each stick's own,
    // see merged_rows.h migrate (the 436f9ac-based builds wrote 7 for that: such a file has none of the dropped lines, so
    // migrate leaves it as it is))
    static_assert(merged_rows::kVersion == 8, "the options file's version as merged_rows.h migrates to it");
    // (Triforce) 9: stock and native output numbers share one schema, see output_sizes.h; 10: Plus is Tab alone, Enter no
    // longer its second key, see host/nn_hid.c binds_load (the keys alone: every rule here that reads a 9 reads a 10 the same))
    out += "options_version=10\n";
    out += others;
    if (!can_bind()) out += kept;
    // (the stick's and the camera's rows, HOS_KEY_MOVE_* and HOS_KEY_CAM_*, have no pad_ line; (Triforce, 11-24) the
    // ocarina's note rows have one)
    for (int i = 0; i < HOS_KEY_N && can_bind(); i++) {
        if (i < HOS_SW_N || (i >= HOS_KEY_OC_NOTE_L && i <= HOS_KEY_OC_NOTE_X) || i == HOS_KEY_TOGGLE_HUD)
            put(std::string("pad_") + bind_names[i], std::to_string(host->binding(HOS_BIND_PAD, i, 0)) +   // ((Triforce) and Input 2)
                (i < HOS_SW_N && host->binding(HOS_BIND_PAD, i, 1) >= 0 ? "," + std::to_string(host->binding(HOS_BIND_PAD, i, 1)) : ""));
        put(std::string("key_") + bind_names[i],
            std::to_string(host->binding(HOS_BIND_KEY, i, 0)) + "," + std::to_string(host->binding(HOS_BIND_KEY, i, 1)));
    }
#ifdef _WIN32
    {   // (the line ends the file always had there: it was written in text mode)
        std::string crlf;
        for (const char ch : out) crlf += ch == '\n' ? std::string("\r\n") : std::string(1, ch);
        out.swap(crlf);
    }
#endif
    const auto in_place = [&out] {   // (as before: over the file itself)
        FILE* f = fopen(ini_path().c_str(), "wb");
        if (!f) return false;
        const bool ok = fwrite(out.data(), 1, out.size(), f) == out.size();
        return fclose(f) == 0 && ok;
    };
    // ((Triforce) whole, beside it and then in its place; in place where that cannot be (another program holds the file open
    // without letting it be replaced), so that the change is not lost)
    bool written = merge && file_writers::write_whole(ini_path(), out);
    if (!written && !file_writers::stopping()) written = in_place();
    if (written) ini_base = std::move(now);
    static std::string said;   // (once for each set of such lines, not at every save)
    if (!outside.empty() && outside != said)
        logf("menu: options: %s changed in triforce_options.ini outside the game since it read the file, and not in the game: kept as "
             "the file has them (the game takes them at its next start; RX_VK_OPTIONS_MERGE=0: the game's own)", outside.c_str());
    said = outside;
}

/// ((Triforce) the button prompts' live part) The Button prompts row: a controller's face shows at once where the game has every
/// part of the prompts from host/prompts.c (MkwVkHost prompts_live), nothing to restart for then; the keyboard and mouse face,
/// or a game without them, at the next start as the other restart rows
void prompts_at_once(const Row& r) {
    if (r.value != &opts.prompts || *r.value == HOS_PROMPT_KEYBOARD + 1 || !host || !host->prompts_live) return;
    const int slot = restart_slot_of(r);
    if (slot >= 0 && (host->prompts_live() & HOS_PROMPTS_LIVE_ALL) == HOS_PROMPTS_LIVE_ALL)
        restart_state.restart_value(slot, restart_value_of(r));
}

/// A row's new value v, as the arrows set it (dir: 1 up, -1 down, for the rows that skip or wrap), saved unless !keep
/// (a slider's drag: saved once it is let go)
void auto_row_set(const int* value);   // ((Triforce) Auto (this PC), below)
void set_row(Row& r, int v, int dir, bool keep = true) {
    // (nothing else to choose: no change, no save. A saved choice that cannot run here is kept)
    if (row_fixed(r.value)) return;
    if (r.value == &output_pick && output_forced()) return;   // ((Triforce) HOS_AUDIO_DEVICE has the device this run)
    // (the scaling rows: only what can run here. (Triforce, options_version 7) The Upscaler steps through the engines, the Render
    // resolution through the Upscaler's own steps with Native (100%) among them, an engine's native AA: upscaler_rows.h)
    int upscaler_now = -1;   // (the Upscaler's value the step chose with it, -1 none)
    if (r.value == &opts.dlss) {
        const ur::Scaling to = ur::step_engine(upscaler(), opts.resolution, dir, upscalers_available());
        v = to.upscaler, opts.resolution = to.resolution;
    }
    if (r.value == &opts.resolution) {
        const ur::Scaling to = ur::step_resolution(upscaler(), ur::snap(upscaler(), *r.value), dir);
        v = to.resolution;
        if (to.upscaler != upscaler()) upscaler_now = to.upscaler;   // (Native (100%) on or off: the engine's native AA)
    }
    if (r.value == &opts.output_res) {   // (smallest to largest, the screens' sizes among the fixed ones: output_entries)
        if (!output_step(dir, true)) return;
        v = *r.value;
    }
    if (is_merged(r.value)) v = merged_step(r.value, *r.value, dir);   // ((Triforce, options_version 7) its choices here)
    if (r.value == &opts.show_fps) v = fps_levels::step(*r.value, dir);   // ((Triforce) the levels in the order of what they show
    if (stops_at_ends(r)) v = std::min(std::max(v, r.lo), r.hi);   // (a scale: it stops at its ends)
    if ((r.value == &opts.output_width || r.value == &opts.output_height) && v != *r.value) remembered_custom = {};
    if (r.value == &opts.pad_layout) {
        if (v > 2) v = dir > 0 ? 0 : 2;
        if (v < 0) v = 2;
        *r.value = v;
        apply_pad_layout(*r.value);
    } else {
        *r.value = v > r.hi ? r.lo : v < r.lo ? r.hi : v;
        if (upscaler_now >= 0) opts.dlss = upscaler_now;
        // ((Triforce) 11-24) Another Upscaler no longer moves the saved Render resolution to the nearest of its steps: the
        // player's scale is kept, and each Upscaler takes its own step for it where it is read (ur::snap: tx_resolution,
        // resolution_scale, restart_value_of), so a scale another engine lacks comes back on return. Before, FSR 3.1's 58%
        // through DLSS became DLSS's 50% for good
        if (is_merged(r.value)) merged_store(r.value), merged_sync();   // (the saved values it stands for)
    }
    if (r.value == &opts.mic && can_mic()) mic_chosen();   // (hookshot)
    if (r.value == &output_pick) output_chosen();   // ((Triforce) 11-24)
    auto_row_set(r.value);   // ((Triforce) Auto (this PC): On applies it; a row it sets changed by hand turns it Off)
    prompts_at_once(r);   // ((Triforce) the button prompts' live part)
    if (r.value == &opts.reshade) reshade_menu::preset_chosen();   // ((Triforce) 11-24: the ReShade preset, prepared anew)
    if (r.value == &reshade_menu::user_pick) reshade_menu::user_picked();
    {   // (a row that takes a restart: asked again at the next close)
        int now[mr::kMax];
        restart_values(now);
        restart_state.note(now);
    }
    if (keep) save();
}

// Snapshot the drawable in pixels when confirmed. Both dimensions share one save and restart prompt.
void use_window_size(unsigned width, unsigned height) {
    unsigned w, h;
    if (!output_size_used(width, height, &w, &h)) return;
    remembered_custom = {};
    for (Row& dimension : rows) {
        if (dimension.value == &opts.output_width) set_row(dimension, (int)w, 1, false);
        if (dimension.value == &opts.output_height) set_row(dimension, (int)h, 1, false);
    }
    save();
}

// ---- (hookshot) the Controls page: what presses each of the Switch's buttons, a gamepad input and up to two keys ----
struct Control {
    int button;   // HOS_SW_*, or HOS_KEY_* (keys only)
    const char* name;
};
const Control controls[] = {{HOS_SW_A, "A"}, {HOS_SW_B, "B"}, {HOS_SW_X, "X"}, {HOS_SW_Y, "Y"}, {HOS_SW_L, "L"},
                            {HOS_SW_R, "R"}, {HOS_SW_ZL, "ZL"}, {HOS_SW_ZR, "ZR"}, {HOS_SW_PLUS, "Plus"},
                            {HOS_SW_MINUS, "Minus"}, {HOS_SW_LS, "Left stick press"}, {HOS_SW_RS, "Right stick press"},
                            {HOS_SW_UP, "D-pad up"}, {HOS_SW_DOWN, "D-pad down"}, {HOS_SW_LEFT, "D-pad left"},
                            {HOS_SW_RIGHT, "D-pad right"}, {HOS_KEY_MOVE_UP, "Move forward"},
                            {HOS_KEY_MOVE_DOWN, "Move back"}, {HOS_KEY_MOVE_LEFT, "Move left"},
                            {HOS_KEY_MOVE_RIGHT, "Move right"}, {HOS_KEY_CAM_UP, "Camera up"},
                            {HOS_KEY_CAM_DOWN, "Camera down"}, {HOS_KEY_CAM_LEFT, "Camera left"},
                            {HOS_KEY_CAM_RIGHT, "Camera right"},
                            // ((Triforce) 11-24: the ocarina's notes on inputs of their own, none out of the box: the game's
                            // buttons play until a row is bound. Named by the button each note is in the game, host/nn_hid.c)
                            {HOS_KEY_OC_NOTE_L, "Ocarina note (L)"}, {HOS_KEY_OC_NOTE_R, "Ocarina note (R)"},
                            {HOS_KEY_OC_NOTE_A, "Ocarina note (A)"}, {HOS_KEY_OC_NOTE_Y, "Ocarina note (Y)"},
                            {HOS_KEY_OC_NOTE_X, "Ocarina note (X)"},
                            // ((Triforce) hides or shows the HUD in play, unbound out of the box: host/nn_hid.c hud_shortcut)
                            {HOS_KEY_TOGGLE_HUD, "Toggle HUD"}};
constexpr int kControls = sizeof controls / sizeof controls[0];   // (then "Reset to defaults")
// (the stick's and the camera's directions: keys only; the ocarina's note rows take a gamepad input too, and no mouse button)
bool keys_only(int i) { return i < kControls && controls[i].button >= HOS_KEY_MOVE_UP && controls[i].button <= HOS_KEY_CAM_RIGHT; }
bool note_row(int i) { return i >= 0 && i < kControls && controls[i].button >= HOS_KEY_OC_NOTE_L && controls[i].button <= HOS_KEY_OC_NOTE_X; }
// ((Triforce) 11-24) The Controls page's columns: a Switch button's two gamepad inputs (Input 1 and Input 2, either presses
// it: host/nn_hid.c) and its keys. A note row has one gamepad input, the keys-only controls none
// ((Triforce) per-control reset) and, at the right, a control's own Reset: there while its bindings are not its defaults
// (MkwVkHost binding_is_default, reset_binding; a host without them, never)
enum { kColPad, kColAlt, kColKeys, kColReset, kCols };
bool has_alt(int i) { return i >= 0 && i < kControls && controls[i].button < HOS_SW_N; }
bool can_reset_rows() { return host && host->reset_binding && host->binding_is_default && host->rebind_control; }
bool reset_usable(int i) { return i >= 0 && i < kControls && can_reset_rows() && !host->binding_is_default(controls[i].button); }
bool col_usable(int i, int col) {
    if (col == kColReset) return reset_usable(i);
    return col == kColKeys || (!keys_only(i) && (col == kColPad || has_alt(i)));
}
// a pad input's name on the controller of the button prompts (the Button prompts row's choice; Auto: the face in use),
// else by its place ((Triforce) by its place too with the keyboard and mouse face, which is no controller's)
const char* pad_name(int p) {
    static const char* t[HOS_PROMPT_KEYBOARD + 1][HOS_PAD_N] = {   // (by place, then HOS_PROMPT_*, the controllers')
        {"Bottom button", "Right button", "Left button", "Top button", "Select / Back", "Home", "Start", "Left stick press",
         "Right stick press", "L1 / LB", "R1 / RB", "D-pad up", "D-pad down", "D-pad left", "D-pad right", "L2 / LT", "R2 / RT"},
        {"B", "A", "Y", "X", "Minus", "Home", "Plus", "Left stick press", "Right stick press", "L", "R", "D-pad up",
         "D-pad down", "D-pad left", "D-pad right", "ZL", "ZR"},
        {"A", "B", "X", "Y", "View", "Xbox", "Menu", "Left stick press", "Right stick press", "LB", "RB", "D-pad up",
         "D-pad down", "D-pad left", "D-pad right", "LT", "RT"},
        {"Cross", "Circle", "Square", "Triangle", "Share", "PS", "Options", "L3", "R3", "L1", "R1", "D-pad up", "D-pad down",
         "D-pad left", "D-pad right", "L2", "R2"},
        {"Cross", "Circle", "Square", "Triangle", "Create", "PS", "Options", "L3", "R3", "L1", "R1", "D-pad up", "D-pad down",
         "D-pad left", "D-pad right", "L2", "R2"},
        {"A", "B", "X", "Y", "View", "Steam", "Menu", "L3", "R3", "L1", "R1", "D-pad up", "D-pad down", "D-pad left",
         "D-pad right", "L2", "R2"}};
    int face = opts.prompts ? opts.prompts - 1 : host && host->prompt_face ? host->prompt_face() : -1;
    // ((Triforce, 11-19) with the keys' face, the controller used last's names, as the overlay's icons (vk_imgui.cpp))
    if ((face < 0 || face == HOS_PROMPT_KEYBOARD) && host && host->prompt_pad_face && host->prompt_pad_face() >= 0)
        face = host->prompt_pad_face();
    static const char* const paddles[] = {"R4", "L4", "R5", "L5"};   // ((Triforce) 11-24: the rear paddles, by SDL's names)
    if (p >= HOS_PAD_RPADDLE1 && p <= HOS_PAD_LPADDLE2) return paddles[p - HOS_PAD_RPADDLE1];
    return p >= 0 && p < HOS_PAD_N ? t[face >= 0 && face < HOS_PROMPT_KEYBOARD ? face + 1 : 0][p] : "None";
}
const char* key_name(int vk) {
    static char b[16];
    if ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9')) return b[0] = (char)vk, b[1] = 0, b;
    if (vk >= VK_F1 && vk <= VK_F12) return snprintf(b, sizeof b, "F%d", vk - VK_F1 + 1), b;
    if (vk >= VK_NUMPAD0 && vk <= VK_NUMPAD0 + 9) return snprintf(b, sizeof b, "Num %d", vk - VK_NUMPAD0), b;
    switch (vk) {
    case VK_SPACE: return "Space";
    case VK_SHIFT: return "Shift";
    case VK_CONTROL: return "Ctrl";
    case VK_MENU: return "Alt";
    case VK_TAB: return "Tab";
    case VK_RETURN: return "Enter";
    case VK_BACK: return "Backspace";
    case VK_CAPITAL: return "Caps Lock";
    case VK_UP: return "Up";
    case VK_DOWN: return "Down";
    case VK_LEFT: return "Left";
    case VK_RIGHT: return "Right";
    case VK_HOME: return "Home";
    case VK_END: return "End";
    case VK_PRIOR: return "Page Up";
    case VK_NEXT: return "Page Down";
    case VK_ADD: return "Num +";
    case VK_SUBTRACT: return "Num -";
    case VK_MULTIPLY: return "Num *";
    case VK_DIVIDE: return "Num /";
    case VK_DECIMAL: return "Num .";
    case VK_OEM_1: return ";";
    case VK_OEM_PLUS: return "=";
    case VK_OEM_COMMA: return ",";
    case VK_OEM_MINUS: return "-";
    case VK_OEM_PERIOD: return ".";
    case VK_OEM_2: return "/";
    case VK_OEM_3: return "`";
    case VK_OEM_4: return "[";
    case VK_OEM_5: return "\\";
    case VK_OEM_6: return "]";
    case VK_OEM_7: return "'";
    case VK_LBUTTON: return "Left click";
    case VK_RBUTTON: return "Right click";
    case VK_MBUTTON: return "Middle click";
    case 0x05: return "Mouse 4";   // (VK_XBUTTON1)
    case 0x06: return "Mouse 5";
    }
    return snprintf(b, sizeof b, "Key %d", vk), b;
}
/// (Triforce) A key the menu has a use of its own for (menu_tick's keys, F8 the bug capture's): bound to the Switch's L, R or B
/// it keeps that use in the menu
bool menu_own_key(int vk) {
    switch (vk) {
    case VK_INSERT: case VK_UP: case VK_DOWN: case VK_LEFT: case VK_RIGHT: case VK_ESCAPE: case VK_F1: case VK_RETURN:
    case VK_DELETE: case VK_BACK: case 'Q': case 'E': case VK_TAB: case VK_PRIOR: case VK_NEXT: case VK_HOME: case VK_END:
    case VK_F8:
        return true;
    }
    return false;
}
/// (Triforce) A key the menu takes as it is let go (menu_tick): Shift, Ctrl and Alt are held for other keys too (Shift+Tab)
bool menu_modifier_key(int vk) { return vk == VK_SHIFT || vk == VK_CONTROL || vk == VK_MENU; }
/// (Triforce) Whether the key k is the modifier vk itself or its left or right key (VK_LSHIFT, VK_RSHIFT for VK_SHIFT): held
/// with vk, any other key makes vk no press of its own (menu_tick)
bool menu_same_modifier(int vk, int k) {
    switch (vk) {
    case VK_SHIFT: return k == VK_SHIFT || k == VK_LSHIFT || k == VK_RSHIFT;
    case VK_CONTROL: return k == VK_CONTROL || k == VK_LCONTROL || k == VK_RCONTROL;
    case VK_MENU: return k == VK_MENU || k == VK_LMENU || k == VK_RMENU;
    }
    return k == vk;
}
/// (Triforce) The key in the slot of the Switch's button (HOS_SW_L, HOS_SW_R, HOS_SW_B) that the menu takes as that button too,
/// as the game's own Options tab does: a key (not a mouse button: the mouse's clicks are the menu's own) the menu has no
/// other use for. 0: none
int menu_bound_key(int button, int slot) {
    const int vk = host && host->binding ? host->binding(HOS_BIND_KEY, button, slot) : 0;
    return vk >= 8 && vk < 256 && !menu_own_key(vk) ? vk : 0;
}
// the keys a binding can take (Esc cancels, Insert and F1 are the menu's, Delete clears)
const std::vector<int>& bindable_keys() {
    static std::vector<int> k;
    if (k.empty()) {
        for (int c = 'A'; c <= 'Z'; c++) k.push_back(c);
        for (int c = '0'; c <= '9'; c++) k.push_back(c);
        for (int c = VK_F2; c <= VK_F12; c++) k.push_back(c);
        for (int c = VK_NUMPAD0; c <= VK_NUMPAD0 + 9; c++) k.push_back(c);
        for (int c : {VK_SPACE, VK_SHIFT, VK_CONTROL, VK_MENU, VK_TAB, VK_RETURN, VK_BACK, VK_CAPITAL, VK_UP, VK_DOWN,
                      VK_LEFT, VK_RIGHT, VK_HOME, VK_END, VK_PRIOR, VK_NEXT, VK_ADD, VK_SUBTRACT, VK_MULTIPLY,
                      VK_DIVIDE, VK_DECIMAL, VK_OEM_1, VK_OEM_PLUS, VK_OEM_COMMA, VK_OEM_MINUS, VK_OEM_PERIOD,
                      VK_OEM_2, VK_OEM_3, VK_OEM_4, VK_OEM_5, VK_OEM_6, VK_OEM_7, VK_LBUTTON, VK_RBUTTON, VK_MBUTTON,
                      0x05, 0x06})   // (the mouse's buttons too: they count while the mouse is captured)
            k.push_back(c);
    }
    return k;
}
// ((Triforce) the tuning bar: the options page as one row in a bar at the foot of the screen, the game seen whole above it, for
// judging a setting's change live (draw_tune_bar). Right Ctrl or the gamepad's left face button switches to it and back on the
// options page over play; Right Ctrl held while the menu opens opens it so. Not inside the game's own Options screen)
bool tune_mode = false;
int page = 0;          // 0 the options, 1 the controls, 3 the teleport list, 4 the inventory, 5 the restart question (2: was the
                       // debug tools' own page, now on the Debug tab), 6 (Triforce) a name page: Game flags, Cutscenes, Scan amiibo
/// (Triforce) Whether the Mods screen's search takes the keyboard's text now (mods_text_wanted): the keys bound to the Switch's
/// L, R and B (R and Shift by default) type there, so they are not our tabs and Back then (menu_tick), and the guides name
/// the menu's own Q, E and Esc (ui_ctx), as the Mods screen had them before the bound keys came
bool menu_mods_typing() { return open_now.load() && page == kModsPage && mods_text_wanted.load(std::memory_order_relaxed); }
int csel = 0, ccol = 0;   // the page's row (kTop first: its own rows, then the controls, then reset) and column (0 the
                          // gamepad, 1 the keyboard)
const int kTop = tab_row_count(TAB_PAGE);   // (Layout preset and Button prompts: a preset shows in the grid at once)
int listening = 0;     // waiting for the new input: 1 a gamepad's, 2 a key
bool listen_armed = false;   // (once what started it was let go)
int64_t listen_end = 0;
// ---- ((Triforce) per-control reset and confirmed rebinds) What the Controls page asks before it changes: a control reset,
// all of them reset, or a new input another control has (its name said: that control loses it, or trades a gamepad input for
// this one's, host/nn_hid.c hos_bind's rules). Cancel is the choice at first ----
enum ControlAsk { kAskNone, kAskRebind, kAskResetRow, kAskResetAll };
struct ControlConfirmation {
    int action = kAskNone;
    int row = -1, set = 0, slot = 0, code = 0, choice = 0;
    uint64_t conflicts = 0;
};
ControlConfirmation control_confirmation;
int blocked_reset_row = -1;   // (a reset refused: another control has one of the row's defaults; its help says so)
int pad_clear = HOS_PAD_NORTH;   // (the Controls page's Clear on a controller: a face button neither Bind's nor Back's)
/// The next row Up or Down (direction -1, 1) goes to: on the Reset column, the next control with a Reset of its own
/// (wrapping, the column kept); elsewhere the next row of the page
int next_control_selection(int selection, int col, int direction) {
    const int row = selection - kTop, n = kTop + kControls + 1;
    if (row < 0 || row >= kControls || col != kColReset) return (selection + n + direction) % n;
    for (int step = 1, next = row; step < kControls; step++) {
        next = (next + kControls + direction) % kControls;
        if (col_usable(next, col)) return kTop + next;
    }
    return selection;
}
/// The names of the controls of conflicts' bits (HOS_SW_* / HOS_KEY_*), as the page lists them
std::string control_names(uint64_t conflicts) {
    std::string out;
    for (int i = 0; i < kControls; i++)
        if (conflicts >> controls[i].button & 1) out += (out.empty() ? "" : ", ") + std::string(i18n::tr(controls[i].name));
    return out;
}
void after_binding(int set) {   // (a binding changed: the Layout preset as the face buttons now are, and saved)
    if (set == HOS_BIND_PAD) opts.pad_layout = detect_pad_layout();
    save();
}
/// A new input for row's slot: bound at once, or asked about first when it takes the input from other controls (a host
/// without rebind_control binds as before)
void bind_or_ask(int set, int row, int slot, int code) {
    const int button = controls[row].button;
    if (!can_reset_rows()) {
        host->bind(set, button, set == HOS_BIND_PAD ? slot : 0, code);
        if (set == HOS_BIND_KEY) host->bind(HOS_BIND_KEY, button, 1, 0);
        after_binding(set);
        return;
    }
    uint64_t conflicts = 0;
    if (host->rebind_control(set, button, slot, code, 0, &conflicts)) after_binding(set);
    else if (conflicts) control_confirmation = {kAskRebind, row, set, slot, code, 0, conflicts};
}
std::string keys_text(int button) {
    const int a = host->binding(HOS_BIND_KEY, button, 0), b = host->binding(HOS_BIND_KEY, button, 1);
    std::string t = a ? key_name(a) : "";
    if (b) t += std::string(a ? ", " : "") + key_name(b);
    return t.empty() ? "None" : t;
}

// ---- what is drawn: Dear ImGui over the window's image (vk_imgui.h) in the game's own style (vk_ui.h). Built anew at each
// present while something shows, from the menu's state (menu_tick and menu_record run on the presenting thread, one at a time:
// present_image's lock); nothing at all while nothing shows ----
std::mutex startup_mu;   // (the start-up screen's view, set from its own thread)
StartupView startup;
std::atomic<bool> startup_on{false};
std::atomic<float> startup_fade{0};   // (the start-up screen's fade to black at its end, 0 to 1: startup_fade_to)
std::atomic<int64_t> shown_frames{0};   // (game_frames: above, mods_list_age)
char fps_text[48] = "";
char fps_sub[32] = "";
// (Triforce) The performance overlay, the FPS counter row on Full (opts.show_fps == 2; draw_perf): NX2navi's full panel. The
// game's frame times go into the ring as the frames are counted (menu_note_frame), under perf_mu: with frame generation that
// is the display thread, else the replay's. The machine's numbers are sampled on a thread of their own while the row is on
// Full (perf_machine.cpp, started and stopped in menu_tick). The panel's texts are made twice a second where the counter's
// number is (menu_tick, perf_sample) and drawn by the same thread. Nothing of it runs while the row is not on Full: one
// comparison a frame
std::mutex perf_mu;
perf_stats::Ring perf_ring;
constexpr int kPerfGraph = 120;   // (the graph's frames: NX2navi's PERF_HISTORY)
// (the game's version: Triforce makes the game from build e0f3ccfa alone, the game's 1.1.1 (nx2/make_game.py BUILD_ID,
// check_supported_build); the renderer is not told the build at run time)
constexpr const char* kGameVersion = "1.1.1";
// (the panel's rows, top to bottom, with NX2navi's names and in its order: the machine and the frames in three columns, then
// the figures per frame, then the settings that shape the picture (NX2navi's "3D scene" is hidden on this game: not here))
constexpr const char* kPerfTop[] = {"GPU", "VRAM", "CPU", "RAM", "FPS", "FG", "Frame"};
constexpr int kPerfTopRows = 7, kPerfFG = 5;
constexpr const char* kPerfFrame[] = {"GPU frame prep", "GPU busy per frame", "Pipeline waits", "Shader waits", "Texture uploads"};
constexpr int kPerfFrameRows = 5;
constexpr const char* kPerfSetting[] = {"Window", "Game image", "Upscaling", "Anti-aliasing", "Frame limit", "VSync",
                                        "Widescreen", "Resolution", "HDR output", "Frame generation"};
constexpr int kPerfSettings = 10;
// (the panel's opacity: the options' caption plate under it at the share the options dim the game by (ui::kDimAlpha), so the
// game shows through it as through the dim; its texts and dividers are drawn whole)
constexpr float kPerfOpacity = ui::kDimAlpha / 255.0f;
/// (Triforce) The panel's scale, NX2navi's menu_scale: the window's lines over 1080 (on a window narrower than 1.47:1, 0.68 of
/// its width's), and at least 720 lines at the window's display scale (its DPI over 96: sizes are physical pixels, so a small
/// window on a 150% display still has text as large as the display asks for). draw_perf and prebake both size by it
float perf_scale(float w, float h) {
    float dpi = 96;
#ifdef _WIN32
    typedef UINT(WINAPI * GetDpi)(HWND);   // (Windows 10 1607 on: looked up, as host/display.c window_dpi does)
    static const GetDpi get = (GetDpi)(void*)GetProcAddress(GetModuleHandleA("user32.dll"), "GetDpiForWindow");
    if (const UINT d = get ? get(app_window()) : 0) dpi = (float)d;
#endif
    return std::max(std::min(h, w * 0.68f), 720.0f * dpi / 96.0f) / 1080.0f;
}
/// The panel's text size at scale k: its menu font's 25.5 at the window's 0.72 (NX2navi's SetWindowFontScale)
float perf_px(float k) { return 25.5f * 0.72f * k; }
struct PerfCell {
    char t[32] = "";   // (the text; empty: an empty cell)
    bool dim = false;  // ("-": the machine or the game gives no number)
};
struct PerfView {
    bool have = false;                         // (made: false until the first sample)
    bool full = false;                         // (the row was on Full at the sample before: a ring from an earlier time is emptied)
    char title[96] = "";                       // ("Triforce <this build>, game 1.1.1": perf_title)
    PerfCell top[kPerfTopRows][3];             // (GPU, VRAM, CPU, RAM; FPS, FG, Frame: three cells each)
    bool fg = false;                           // (the FG row shows: frame generation makes frames)
    PerfCell frame[kPerfFrameRows];            // (one each)
    char setting[kPerfSettings][48] = {};      // (kPerfSetting's values; an empty one: its row is left out, as NX2navi's)
    char gpu_name[96] = "", cpu_name[64] = "";
    // (the running counts as of the sample before: the figures per frame are what came since, over the game's frames since,
    // perf_stats::per_frame)
    perf_stats::Base base;
} perf_view;
menu_hit::Map hits;      // (the menu's controls as last drawn: the mouse's, menu_tick)
// ((Triforce, 11-22, N64 Classic) the options were drawn under its TV at the last present (menu_tv_layer): the mouse is
// taken through the TV's curve to where they were drawn (vk_n64.h n64_screen_point). The presenting thread's, as hits is
bool options_under_tv = false;
float scroll_at[TAB_SIM_TURF + 1];   // (the first row shown, eased toward the selection: the options' tabs and the pages rows open,
                                // the Controls page: kControlsSlot, then the Remembered page)
constexpr int kControlsSlot = TAB_PAGE;
int wheel_rows[TAB_SIM_TURF + 1];   // (the mouse wheel's notches since the last drawing, a slot each: scroll_rows scrolls by them)
int scrolled_to[TAB_SIM_TURF + 1] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1};   // (the selection scroll_rows last brought into view)
static_assert(TAB_SIM_TURF + 1 == 13, "scrolled_to: a slot for each tab, each page a row opens, the Controls page, the Remembered page and the Simulated turf page");
float scroll_want[TAB_SIM_TURF + 1];   // (where scroll_at is going: the wheel moves it, a new selection too)
float ease_step = 0;     // (this drawing's share of the way: the time since the last one)
bool ease_live = false;  // ((Triforce) menu_record steps the easing: a window's frames. Without them a still is drawn settled)

ui::Ctx ui_ctx(uint32_t w, uint32_t h) {
    ui::Ctx c{ImGui::GetForegroundDrawList(), ui::fonts(), 1, (float)w, (float)h, 0, pad_last};
    c.confirm_dot = menu_keys::dot(pad_confirm), c.back_dot = menu_keys::dot(pad_back);
    {   // ((Triforce) per-control reset) the Controls page's Clear on a controller: the icon of the Switch face button bound to it
        static const int face[4] = {HOS_SW_A, HOS_SW_B, HOS_SW_X, HOS_SW_Y};
        static const char* const icons[4] = {ui::kIconA, ui::kIconB, ui::kIconX, ui::kIconY};
        for (int i = 0; i < 4 && host && host->binding; i++)
            if (host->binding(HOS_BIND_PAD, face[i], 0) == pad_clear) c.clear_icon = icons[i];
        c.clear_name = pad_name(pad_clear);
    }
    {   // ((Triforce) the keys the tab strip's ends and the guides name: those bound to the Switch's L, R and B where the menu
        // takes them (menu_bound_key), as the game's own guides name the bindings; else the menu's own Q, E and Esc)
        static char names[3][24];   // (fixed places: a Ctx made before keeps pointing at them)
        static const int buttons[3] = {HOS_SW_L, HOS_SW_R, HOS_SW_B};
        static const char* const own[3] = {"Q", "E", "Esc"};
        const bool typing = menu_mods_typing();   // (the Mods search takes the bound keys as text: the menu's own then)
        for (int b = 0; b < 3; b++) {
            int vk = typing ? 0 : menu_bound_key(buttons[b], 0);
            if (!vk && !typing) vk = menu_bound_key(buttons[b], 1);
            snprintf(names[b], sizeof names[b], "%s", vk ? key_name(vk) : own[b]);
        }
        c.key_tab_l = names[0], c.key_tab_r = names[1], c.key_back = names[2];
    }
    c.s = ui::unit((float)h, 0, false, false, &c.safe);
    // (the cursor's glow breathes, as the game's: a 2 s cycle; RX_VK_UI_STILL=1 holds it, for pictures that compare)
    static const bool still = getenv("RX_VK_UI_STILL") != nullptr;
    c.pulse = still ? 0.6f : 0.5f + 0.5f * std::sin((float)((prof_now() % 2000000000LL) / 2e9 * 6.2831853));
    return c;
}
/// (Triforce) The menu's, the counter's and the notice's: the game's menu fonts where the pages draw their text (body its
/// "Normal", strong its "Special"); the start-up screen keeps ui_ctx's
ui::Ctx menu_ctx(uint32_t w, uint32_t h) {
    ui::Ctx c = ui_ctx(w, h);
    if (c.f.menu) c.f.body = c.f.menu, c.f.strong = c.f.heading;
    return c;
}
/// The header's height (SystemOverlay_00's P_SystemHeader_00: 200 units)
float banner_h(const ui::Ctx& c) { return ui::banner_height(c); }
/// ((Triforce, 11-19) the draw list draw_menu has split while the Full panel goes between a page and its header (our tabs inside
/// the game's Options screen, as on the game's own tab the panel is over the game's panes and under our header): the header
/// into its channel 1, the rest of the page into 0. header_layer(c, true) before a page's header, false after it; nothing
/// while the list is not split
ImDrawList* header_split = nullptr;
void header_layer(const ui::Ctx& c, bool on) {
    if (header_split && header_split == c.d) c.d->ChannelsSetCurrent(on ? 1 : 0);
}
/// ((Triforce, 11-20) the Full panel while it waits to go between the page and its header (draw_menu's perf_between): window,
/// the window's context it is drawn in; keep, the window's clip rectangle; v0 to v1 its vertices once drawn (in the window's
/// pixels: put_on_grid leaves them)
struct PanelWait {
    ui::Ctx* window = nullptr;
    ImVec4 keep;
    int v0 = 0, v1 = 0;
};
PanelWait panel_wait;
/// ((Triforce, 11-20) the draw list draw_menu has split while the Full panel waits: inside the game's Options screen the page
/// in channel 0 and its header in 1 (header_split); over play the pages in 1, channel 0 left for the panel under them
ImDrawList* panel_split = nullptr;
void draw_perf(ui::Ctx& c);
/// (the waiting Full panel drawn now, where the list's drawing is, in the window's clip and pixels)
void panel_draw(ImDrawList* d) {
    d->PushClipRect(ImVec2(panel_wait.keep.x, panel_wait.keep.y), ImVec2(panel_wait.keep.z, panel_wait.keep.w), false);   // (the window's)
    panel_wait.v0 = d->VtxBuffer.Size;
    draw_perf(*panel_wait.window);
    panel_wait.v1 = d->VtxBuffer.Size;
    d->PopClipRect();
    panel_wait.window = nullptr;
}
/// ((Triforce, 11-20) the waiting Full panel at the page's end (draw_menu), into channel 0 and the list merged: inside the
/// game's Options screen over the page and under its header (as on the game's own tab), over play under the pages (as
/// NX2navi keeps its panel under its menu). A dialog's dim draws it before (dim_page): then this has nothing to do
void panel_between(ImDrawList* d) {
    if (!panel_wait.window || panel_wait.window->d != d || panel_split != d) return;
    d->ChannelsSetCurrent(0);
    panel_draw(d);
    d->ChannelsMerge();
    panel_split = header_split = nullptr;
}
/// ((Triforce, 11-20) a dialog's dim (dim_page): the page and its header made one list first, the panel still waiting, so
/// that the dim goes over both; the panel then over the dim (panel_over), under the dialog's box. The game's own dialogs never
/// dim our overlay (it is drawn over the game), and over Quit's dialog the panel was already bright (menu_record); the
/// restart question's, the Mods dialogs' and the keyboard's dim went over it (26670c0): now bright over all of ours, as the
/// FPS counter always was)
void panel_merge(ImDrawList* d) {
    if (panel_split != d) return;
    d->ChannelsMerge();
    panel_split = header_split = nullptr;
}
void panel_over(ImDrawList* d) {
    if (panel_wait.window && panel_wait.window->d == d && panel_split != d) panel_draw(d);
}
/// (a dim over the whole page before a dialog: dim_page, after menu_map)
void dim_page(ui::Ctx& c, ImU32 col);
// (the caption's texts: PaGuideKey's 48 units for the help, a little smaller for the line about the value)
// (the game's caption is 54 units, 65 as drawn; ours say more than its one line, so a little smaller: 57 and 50)
constexpr float kHelpPt = 19.0f, kHintPt = 16.6f;
constexpr float kModsDescPt = 15.2f;   // ((Triforce, 11-18) the Mods description: a step under the hints, more of it in the panel)
// ((Triforce, 11-18) a page's floor: the caption's plate stops this far above the prompt bar, for a page with something of
// its own at the foot (the Mods page's Salesman). Set while that page draws, 0 for every other
float caption_floor = 0;
// (...and its margin: the plate's right end stays this far inside the window's edge while the Mods page draws; 0, every
// other page: the plate runs off the screen as the game's own caption plate does)
float caption_edge = 0;

/// The tallest help a row of the options can have, in pixels at width: its help and the tallest line any of its values can
/// have: the help box keeps that height whichever row is selected and whatever its value
float measure_help(ui::Ctx& c, float width) {
    float most = 0;
    for (const Row& r : rows) {
        float hint = 0;
        for (int v = r.lo; r.value && r.hint && v <= r.hi; v++)
            for (int k = 0; const char* t = r.hint(v, k); k++)
                hint = std::max(hint, ui::para(c, c.f.body, kHintPt * c.s, ImVec2(), 0, t, width - 18 * c.s, false));
        if (r.help) most = std::max(most, ui::para(c, c.f.body, kHelpPt * c.s, ImVec2(), 0, r.help, width, false) + (hint ? 14 * c.s + hint : 0));
    }
    return most;
}
/// label in room pixels: as it is when it fits; the selected row's slides through it (marquee_pos, marquee_max for menu_tick);
/// another's ends with "..."
/// (UTF-8: the byte offsets where its characters start, and the end; labels are cut and slid a character at a time, never
/// inside one: a microphone's name can be in any script)
std::vector<size_t> char_starts(const std::string& t) {
    std::vector<size_t> at;
    for (size_t i = 0; i < t.size(); i++)
        if (((unsigned char)t[i] & 0xC0) != 0x80) at.push_back(i);
    at.push_back(t.size());
    return at;
}
std::string fit(ui::Ctx& c, ImFont* f, float px, float room, const std::string& english, bool sel) {
    const std::string label = i18n::tr(english.c_str());   // ((Triforce) in the menu's language: cut and slid as it is drawn)
    auto width = [&](const std::string& t) { return ui::size_of(f, px, t.c_str()).x; };
    if (width(label) <= room) return label;
    const std::vector<size_t> at = char_starts(label);
    const int chars = (int)at.size() - 1;
    if (sel) {   // (marquee_pos and marquee_max count characters)
        int start = chars;   // (the last start that still shows the label's end)
        while (start > 0 && width(label.substr(at[start - 1])) <= room) start--;
        marquee_max = start;
        const int from = std::min(marquee_pos, marquee_max);
        int end = chars;
        while (end > from + 1 && width(label.substr(at[from], at[end] - at[from])) > room) end--;
        return label.substr(at[from], at[end] - at[from]);
    }
    int end = chars;
    while (end > 1 && width(label.substr(0, at[end]) + "...") > room) end--;
    std::string t = label.substr(0, at[end]);
    while (!t.empty() && t.back() == ' ') t.pop_back();
    return t + "...";
}
/// A list of rows from top to bottom (pixels), n of them pitch apart, the selection sel kept in view: the first one shown,
/// eased toward its place (scroll_at[slot]); *shown how many fit
float scroll_rows(int slot, int n, int sel, float top, float bottom, float pitch, int* shown) {
    const int fit = std::max(1, (int)((bottom - top) / pitch));
    *shown = fit;
    float& at = scroll_at[slot];
    float& want = scroll_want[slot];
    const int wheel = std::exchange(wheel_rows[slot], 0);
    if (n <= fit) want = 0;   // (nothing to scroll: the wheel does nothing)
    else {
        want -= (float)wheel;   // (the wheel scrolls the rows and leaves the selection, and every value, as they are)
        static int fits[sizeof scroll_at / sizeof *scroll_at];   // (and after a resize: the rows that fit changed)
        if (sel != scrolled_to[slot] || fit != std::exchange(fits[slot], fit)) {   // (a new selection, by the keys or the pad: brought into view)
            const int margin = fit > 4 ? 1 : 0;   // (a row of context above and below the selection)
            if (sel - margin < want) want = (float)(sel - margin);
            if (sel + margin + 1 > want + fit) want = (float)(sel + margin + 1 - fit);
        }
        want = std::round(std::clamp(want, 0.0f, (float)(n - fit)));
    }
    scrolled_to[slot] = sel;
    at += (want - at) * ease_step;
    if (std::fabs(want - at) < 0.01f) at = want;
    return at;
}
/// The scroll bar at x, beside a list of n rows of which shown fit, the first at `first`: the game's (PaScrollBar_00: a short
/// bar, 32 x 312 units, at the list's middle; its lit part the rows in view)
void scroll_bar(ui::Ctx& c, float x, float top, float bottom, int n, int shown, float first) {
    if (n <= shown && !c.over_game) return;   // (over the game's own list its bar is under ours: drawn, whole, even so)
    if (n <= shown) n = shown = 1, first = 0;
    const float mid = (top + bottom) * 0.5f, half = ui::lu(c, 156), w = ui::lu(c, 16);
    const float y0 = mid - half + 2 * half * first / n, y1 = mid - half + 2 * half * (first + shown) / n;
    if (const ui::Art* t = ui::skin("ScrollBarBase_00")) {
        ui::image(c, t, ImVec2(x - w, mid - half), ImVec2(x + w, mid + half), ui::rgba(18, 14, 9, 235));
        c.d->PushClipRect(ImVec2(x - w, y0), ImVec2(x + w, y1), true);
        ui::image(c, t, ImVec2(x - w, mid - half), ImVec2(x + w, mid + half), ui::rgba(200, 146, 66));
        c.d->PopClipRect();
        return;
    }
    c.d->AddRectFilled(ImVec2(x - w * 0.4f, mid - half), ImVec2(x + w * 0.4f, mid + half), ui::rgba(18, 14, 9, 235), w * 0.4f);
    c.d->AddRectFilled(ImVec2(x - w * 0.4f, y0), ImVec2(x + w * 0.4f, y1), ui::rgba(200, 146, 66), w * 0.4f);
}
/// The header with a page's title in the middle (the Controls, Motion and list pages: as the game's "Load"), its height
float title_banner(ui::Ctx& c, const char* title, const char* right) {
    header_layer(c, true);
    ui::banner(c, 0, title);
    if (right) ui::text_mid_right(c, c.f.body, ui::lu(c, 50), ui::at(c, 1800, 0).x, ui::at(c, 0, 990).y, ui::kBannerInk, right);
    header_layer(c, false);
    return banner_h(c);
}
/// The caption plate from (x0, y0) to x1 (what shows of it): a title when the page has one, the help, a line about the value
/// set off by a bar, a line at its foot; the text in the plate's middle, as the game sets its caption. min_h: its text's
/// room at least; kept between y_min and y_max. bleed: how far the plate goes on to the right of x1, off the screen (the
/// game's caption plate does)
void help_box(ui::Ctx& c, float x0, float x1, float y0, const char* title, const char* help, const char* hint, const char* gold_line,
              float min_h = 0, bool after_restart = false, float y_min = 0, float y_max = FLT_MAX, float bleed = 0) {
    const float s = c.s, pad_x = ui::lu(c, 72), pad_y = ui::lu(c, 56), w = x1 - x0 - 2 * pad_x;
    const float th = help ? ui::para(c, c.f.body, kHelpPt * s, ImVec2(), 0, help, w, false) : 0,
                hh = hint ? ui::para(c, c.f.body, kHintPt * s, ImVec2(), 0, hint, w - 18 * s, false) : 0;
    const float text_h = th + (hint ? 14 * s + hh : 0), note = after_restart ? 30 * s : 0;
    const float content = (title ? 34 * s : 0) + note + text_h + (gold_line ? 46 * s : 0);
    float tall = std::max(min_h, content + 2 * pad_y);
    if (y0 + tall > y_max) y0 = std::max(y_min, y_max - tall);
    const float y1 = std::min(y0 + tall, y_max);
    // ((Triforce, 11-18) on the Mods page (caption_edge) the plate's bleed stops short of the window's edge: at a large menu
    // unit hx1 is 3770 of a 3840 column and the bleed ran off the screen; flush with the edge read as on it (his "fix the
    // search bar being on the edge of the 16:9 window"), so it keeps a margin there. Never short of the text's own end, x1.
    // The options' own pages keep the plate off the screen, as the game's caption plate is)
    const float plate_x1 = caption_edge > 0 ? std::max(x1, std::min(x1 + bleed, (float)c.w - caption_edge)) : x1 + bleed;
    ui::box(c, ImVec2(x0, y0), ImVec2(plate_x1, y1));
    c.d->PushClipRect(ImVec2(x0, y0), ImVec2(x1, y1), true);
    float y = std::max(y0 + pad_y * 0.5f, (y0 + y1 - content) * 0.5f);
    if (title) ui::text(c, c.f.strong, 21.6f * s, ImVec2(x0 + pad_x, y), ui::kInk, title), y += 34 * s;
    if (after_restart) {   // (this row's change applies at the next start: said here, not in the row, where it would cut the name)
        ui::diamond(c, ImVec2(x0 + pad_x + 5 * s, y + 10 * s), 4 * s, ui::kGoldHi);
        ui::text_mid(c, c.f.strong, kHintPt * s, x0 + pad_x + 16 * s, y + 10 * s, ui::kGoldHi, "Takes effect after a restart");
        y += note;
    }
    if (help) ui::para(c, c.f.body, kHelpPt * s, ImVec2(x0 + pad_x, y), ui::kInk, help, w);
    y += th;
    if (hint) {
        const float hy = y + 14 * s;
        c.d->AddRectFilled(ImVec2(x0 + pad_x, hy + 2 * s), ImVec2(x0 + pad_x + 2.5f * s, hy + hh - 2 * s), ui::kAccent, s);
        ui::para(c, c.f.body, kHintPt * s, ImVec2(x0 + pad_x + 14 * s, hy), ui::kSoft, hint, w - 18 * s);
        y = hy + hh;
    }
    if (gold_line) {
        y += 14 * s;
        c.d->AddLine(ImVec2(x0 + pad_x, y), ImVec2(x1 - pad_x, y), ui::alpha(ui::kEdge, 0.8f), std::max(1.0f, s));
        ui::diamond(c, ImVec2(x0 + pad_x + 5 * s, y + 18 * s), 4 * s, ui::kGoldHi);
        ui::text_mid(c, c.f.strong, kHintPt * s, x0 + pad_x + 16 * s, y + 18 * s, ui::kGoldHi, gold_line);
    }
    c.d->PopClipRect();
}
/// The caption of a page at the options' place (SystemOption_00's N_Caption: its plate 90 units under the screen's middle, off the
/// screen's right edge), as tall as its text asks, between the header and the guides
void caption(ui::Ctx& c, float hx0, float hx1, const char* title, const char* help, const char* hint, const char* gold_line, float min_h = 0,
             bool after_restart = false);
/// The game's Options layout (SystemOption_00): the list's column 2240 units wide, its middle 730 left of the screen's (drawn by
/// draw_menu, under the header); the caption plate to its right, what shows of it from 440 to the screen's edge
constexpr float kListX = -730;   // (N_List_00)
void columns(const ui::Ctx& c, float* x0, float* x1, float* hx0, float* hx1, bool* narrow) {
    *x0 = ui::at(c, kListX - 1120, 0).x, *x1 = ui::at(c, kListX + 1120, 0).x;
    *hx0 = ui::at(c, 456, 0).x, *hx1 = ui::at(c, 1850, 0).x;
    *narrow = false;
}
void column(ui::Ctx&, float, float, float) {}   // (the column is under the header: draw_menu draws it first)
void caption(ui::Ctx& c, float hx0, float hx1, const char* title, const char* help, const char* hint, const char* gold_line, float min_h,
             bool after_restart) {
    // (the game's: 476 units of plate about a line 90 under the screen's middle; taller, about the same line, for a long text)
    const float s = c.s, hh = banner_h(c), bar_top = ui::prompt_bar_top(c), w = hx1 - hx0 - 2 * ui::lu(c, 72);
    const float th = help ? ui::para(c, c.f.body, kHelpPt * s, ImVec2(), 0, help, w, false) : 0,
                nh = hint ? 14 * s + ui::para(c, c.f.body, kHintPt * s, ImVec2(), 0, hint, w - 18 * s, false) : 0;
    const float content = std::max(min_h, th + nh) + (title ? 34 * s : 0) + (after_restart ? 30 * s : 0) + (gold_line ? 46 * s : 0);
    const float tall = std::max(ui::lu(c, 476), content + 2 * ui::lu(c, 56)), mid = ui::at(c, 0, -90).y;
    const float y0 = std::max(hh + 14 * s, mid - tall * 0.5f);
    // ((Triforce, 11-17) the plate's right end where the game's own ends on a window wider than 16:9 (measured at 3440 x 1440:
    // 51 pixels short of ours), off a 16:9 screen as before. Only the plate: the text keeps its width, hx0 to hx1)
    help_box(c, hx0, hx1, y0, title, help, hint, gold_line, tall, after_restart, hh + 14 * s, bar_top - 8 * s - caption_floor,
             ui::lu(c, 252));
}
/// A row's name on its plate; pending: a change that applies after a restart, the game's corner mark at its top left in
/// gold (the help says it in words). The selected row's plate is as the others': the game's cursor alone marks it
void name_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const char* name, bool sel, bool pending = false, float px = 18.0f * ui::kType) {
    const float s = c.s, mid = (a.y + b.y) * 0.5f;
    (void)sel;
    ui::plate(c, a, b);
    if (pending) {
        if (const ui::Art* t = ui::skin("OptionCheckMark_00")) ui::image(c, t, a + ImVec2(ui::lu(c, -8), ui::lu(c, -8)), a + ImVec2(ui::lu(c, 82), ui::lu(c, 82)), ui::kGoldHi);
        else ui::diamond(c, ImVec2(a.x + 10 * s, a.y + 10 * s), 4 * s, ui::kGoldHi);
    }
    const float room = b.x - a.x - ui::lu(c, 110);
    const std::string shown = fit(c, c.f.body, px * s, room, name, false);
    ui::text_mid(c, c.f.body, px * s, a.x + ui::lu(c, 72), mid - ui::lu(c, 2), ui::kInk, shown.c_str());
}
/// A value, as the game's choices: the near-black panel a..b, on it the orange plate with the value in white and the game's
/// small arrows at its ends (left, right: whether it can go that way); the cursor round the panel when selected. fixed:
/// nothing else to choose here, dim. plain: no plate (a row that opens a page: its word and an arrow)
void choice_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const std::string& value, bool sel, bool left, bool right, bool fixed = false,
                 bool plain = false) {
    const float mid = (a.y + b.y) * 0.5f, px = std::min(ui::lu(c, 54 * ui::kType), (b.y - a.y) * 0.62f), in = ui::lu(c, 8);
    ui::value_plate(c, a, b);
    if (!plain) ui::value_plate(c, a + ImVec2(in, in), b - ImVec2(in, in), true, fixed ? 0.30f : 1.0f);
    const ImU32 ink = fixed ? ui::kDim : ui::kInk;
    if (left) ui::arrow(c, ImVec2(a.x + ui::lu(c, 40), mid), false, ink);
    if (right) ui::arrow(c, ImVec2(b.x - ui::lu(c, 40), mid), true, ink);
    const std::string shown = fit(c, c.f.body, px, b.x - a.x - ui::lu(c, left || right ? 150 : 50), value, sel);   // (room for arrows)
    ui::text_mid_centre(c, c.f.body, px, (a.x + b.x) * 0.5f, mid - ui::lu(c, 2), ink, shown.c_str());
    if (sel) ui::cursor(c, a - ImVec2(ui::lu(c, 2.5f), ui::lu(c, 3)), b + ImVec2(ui::lu(c, 2.5f), ui::lu(c, 3)));
}
/// (Triforce) Where a value's two halves meet (halves_cell): 606 of the panel's 98 to 902. The mouse's halves are split there too
float halves_meet(ImVec2 a, ImVec2 b) { return a.x + (b.x - a.x) * 0.632f; }
/// A value of two halves, as the game's toggles (On at the left, Off at the right): the one chosen on its orange plate in
/// white, the other dim on the panel; the left one's plate the wider (the layout's 516 and 320 of 836). high: the right
/// one is chosen
void halves_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const char* lo, const char* hi, bool high, bool sel, bool fixed) {
    const float mid = (a.y + b.y) * 0.5f, in = ui::lu(c, 8), px = std::min(ui::lu(c, 54 * ui::kType), (b.y - a.y) * 0.62f);
    const float xm = halves_meet(a, b);   // (where the two meet)
    ui::value_plate(c, a, b);
    const ImVec2 fa = high ? ImVec2(xm, a.y + in) : a + ImVec2(in, in), fb = high ? b - ImVec2(in, in) : ImVec2(xm, b.y - in);
    ui::value_plate(c, fa, fb, true, fixed ? 0.30f : 1.0f);
    const ImU32 on = fixed ? ui::kDim : ui::kInk;
    ui::text_mid_centre(c, c.f.body, px, (a.x + xm) * 0.5f, mid - ui::lu(c, 2), high ? ui::kDim : on, lo);
    ui::text_mid_centre(c, c.f.body, px, (xm + b.x) * 0.5f, mid - ui::lu(c, 2), high ? on : ui::kDim, hi);
    if (sel) ui::cursor(c, a - ImVec2(ui::lu(c, 2.5f), ui::lu(c, 3)), b + ImVec2(ui::lu(c, 2.5f), ui::lu(c, 3)));
}
/// A scale's value: as a choice with its arrows (the game's Options have no sliders: its levels are choices too), a fine
/// line under the value for how far along it is; *t0, *t1 the line (for the mouse)
void slider_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const char* value, int permille, bool sel, float* t0, float* t1) {
    choice_cell(c, a, b, value, sel, permille > 0, permille < 1000);
    const float x0 = a.x + ui::lu(c, 150), x1 = b.x - ui::lu(c, 150), y = b.y - ui::lu(c, 22), h = std::max(1.0f, ui::lu(c, 2.5f));
    c.d->AddRectFilled(ImVec2(x0, y - h), ImVec2(x1, y + h), ui::rgba(60, 36, 8, 110), h);
    c.d->AddRectFilled(ImVec2(x0, y - h), ImVec2(x0 + (x1 - x0) * permille / 1000.0f, y + h), ui::kInk, h);
    *t0 = x0, *t1 = x1;
}
/// "Restart needed: " and the pending rows, on one line of width: the last ones as "and N more" when they do not fit
std::string restart_line(ui::Ctx& c, float px, float width) {
    const unsigned all = restart_pending();
    std::string line;
    for (int keep = restart_state.n; keep >= 0; keep--) {   // (the first `keep` pending rows by name)
        unsigned shown = 0;
        int named = 0, more = 0;
        for (int i = 0; i < restart_state.n; i++)
            if ((all >> i) & 1) (named < keep ? (shown |= 1u << i, named++) : more++);
        // ((Triforce) in the menu's language: the rows' names and the pieces between them)
        const char* names[mr::kMax];
        for (int i = 0; i < restart_state.n; i++) names[i] = i18n::tr(restart_names[i]);
        line = i18n::tr("Restart needed: ") + mr::names(names, restart_state.n, shown);
        if (more) {   // (" settings (many)": the form Russian and Polish take for 5 and up, i18n::plural; never asked in English)
            const int form = i18n::plural(more);
            line += std::string(named ? i18n::tr(" and ") : "") + std::to_string(more) +
                    i18n::tr(named ? " more" : form == 0 ? " setting" : form == 1 ? " settings" : " settings (many)");
        }
        if (ui::size_of(c.f.strong, px, line.c_str()).x <= width) break;
    }
    return line;
}

/// (hookshot) The Debug tab's order: the tools' rows by their group (Row::cheat), Up and Down walking them so; Inventory item
/// and Change quantity are not shown (the Inventory page edits every amount)
struct DebugGroup { const char* title; int from, to; };   // (debug_tools_order[from, to))
// ((Triforce) Story & amiibo: the name pages' rows, after Player; Movement speed (14) with Player's)
constexpr int debug_tools_order[] = {0, 1, 14, 9, 10, 11, 12, 13, 8, 2, 3, 7, 4};
constexpr DebugGroup debug_groups[] = {{"Player", 0, 5}, {"Story & amiibo", 5, 8}, {"Travel", 8, 11}, {"Camera & world", 11, 13}};
constexpr int kDebugGroups = sizeof debug_groups / sizeof debug_groups[0];
/// (Triforce) The Debug tab's list from the top, drawn as every other tab's (draw_options: the same column, rows and headings):
/// the Debug tools switch; while the tools are on, each group of them under its heading (a group with no row shown has
/// none, and nothing between the groups but their headings); the Developer heading and its rows. Each entry is a row of the
/// tab (its number, tab_row_to_global's) or, -1 - g, group g's heading. Their count (kDebugList at most)
constexpr int kDebugList = kRows + kDebugGroups;   // (every row of the tab, and the groups' headings)
int debug_list(int* out) {
    const int count = tab_row_count(TAB_DEBUG);
    int n = 0;
    for (int k = 0; k < count; ++k)
        if (rows[tab_row_to_global(TAB_DEBUG, k)].value == &opts.debug_tools) out[n++] = k;
    for (int g = 0; g < kDebugGroups; ++g) {
        const int head = n++;
        for (int t = debug_groups[g].from; t < debug_groups[g].to; ++t)
            for (int k = 0; k < count; ++k)
                if (rows[tab_row_to_global(TAB_DEBUG, k)].cheat == debug_tools_order[t]) out[n++] = k;
        if (n == head + 1) n = head;   // (no row of the group shown: no heading)
        else out[head] = -1 - g;
    }
    int dev_head = -1;
    bool dev_titled = false;
    for (int k = 0; k < count; ++k) {
        const Row& r = rows[tab_row_to_global(TAB_DEBUG, k)];
        if (r.heading) dev_head = k;
        else if (dev_head >= 0 && r.cheat < 0 && r.value != &opts.debug_tools) {
            if (!dev_titled) out[n++] = dev_head, dev_titled = true;   // (the Developer heading, over its first row)
            out[n++] = k;
        }
    }
    return n;
}
/// The Debug tab's row after sel (dir 1) or before it (dir -1), in debug_list's order, over the headings
int debug_step(int sel, int dir) {
    int list[kDebugList], order[kDebugList], n = 0;
    const int all = debug_list(list);
    for (int j = 0; j < all; ++j)
        if (list[j] >= 0 && !rows[tab_row_to_global(TAB_DEBUG, list[j])].heading) order[n++] = list[j];
    if (!n) return sel;
    int at = 0;
    while (at < n && order[at] != sel) at++;
    if (at == n) return order[0];
    return order[(at + n + dir) % n];
}
/// (Triforce) A row that does something or opens a page (Export, Restart, Open list, Edit items...): its word on the game's
/// orange plate with its arrow at the right, as the game's own rows that go on (its Targeting Type's). One style on every
/// tab: the System tab's were the dark panel, the Debug tab's orange without the arrow. fixed: nothing to do here now, dim
void action_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const std::string& word, bool sel, bool fixed = false) {
    choice_cell(c, a, b, word, sel, false, !fixed, fixed);
}

/// The tabs across the header (as the pause menu's categories: MenuOverlay_00, 460 units apart, L and R at their ends; closer
/// with more than five). sel: the one shown, -1 the game's own. game: "Game" in front of ours, inside the game's Options
/// screen. hit: the mouse's places noted
void draw_tabs(ui::Ctx& c, int sel, bool game, bool hit) {
    static const char* const ours[TAB_COUNT] = {"Display", "Graphics", "Audio", "Controls", "System", "Debug"};
    const float s = c.s, hh = banner_h(c);
    // (Triforce) the strip's entries in their order: the game's own (-1), ours to System, Debug when shown (Mods is not one:
    // it is an entry of its own under the game's System list and the title's, kModsRowPage)
    int entry[TAB_COUNT + 2], tabs = 0;
    if (game) entry[tabs++] = -1;
    for (int t = 0; t < TAB_DEBUG; t++) entry[tabs++] = t;
    if (debug_shown()) entry[tabs++] = TAB_DEBUG;
    const float ty = ui::at(c, 0, 998).y, step = ui::lu(c, tabs > 7 ? 320 : tabs > 6 ? 350 : tabs > 5 ? 400 : 460), tpx = ui::lu(c, 54 * ui::kType);
    const float tx0 = c.w * 0.5f - step * (tabs - 1) * 0.5f;
    for (int i = 0; i < tabs; i++) {
        const int tab = entry[i];   // (-1: the game's own)
        const float x = tx0 + i * step;
        const bool shown = tab == sel;
        if (shown) {   // (the chosen category: the pause menu's own plate behind its name, MenuHeaderSelect: PaMenuCategory's
            // 540 x 260 pane, 34 units under the header's middle line, in the brown the pause menu's System tab has: the
            // texture as P_PlusMenuBg_00 colours it, vk_game_tex.h tab_select; was the texture times a measured 190,125,62)
            const ImVec2 m = ui::at(c, 0, 966), a(x - std::min(ui::lu(c, 270), step * 0.5f + ui::lu(c, 40)), m.y - ui::lu(c, 130));
            const ImVec2 b(2 * x - a.x, m.y + ui::lu(c, 130));
            if (const ui::Art* t = ui::skin("tab_select")) ui::image(c, t, a, b);
            else if (const ui::Art* g = ui::skin("MenuHeaderSelect_00")) ui::image(c, g, a, b, ui::rgba(190, 125, 62));
            else c.d->AddRectFilled(ImVec2(x - step * 0.5f, 0), ImVec2(x + step * 0.5f, hh + ui::lu(c, 6)), ui::kTabInset);
        } else if (hit && tab >= 0 && tab == hover_tab) {
            c.d->AddRectFilled(ImVec2(x - step * 0.5f + 4 * s, ty - ui::lu(c, 60)), ImVec2(x + step * 0.5f - 4 * s, ty + ui::lu(c, 60)), ui::rgba(60, 42, 22, 70), 6 * s);
        }
        ui::text_mid_centre(c, c.f.strong, tpx, x, ty, ui::kInk, tab < 0 ? "Game" : tab == kModsTab ? "Mods" : ours[tab]);
        if (hit) hits.add(x - step * 0.5f, 0, x + step * 0.5f, hh, menu_hit::kTab, tab < 0 ? kGameTab : tab);
    }
    for (int i = 0; i < 2; i++) {   // (L and R at the tabs' ends, the game's icons: MenuOverlay_00's T_BtnL and T_BtnR, 90 units)
        const float x = i ? tx0 + (tabs - 1) * step + ui::lu(c, 298) : tx0 - ui::lu(c, 298);
        if (c.pad && c.f.glyph) {
            const char* code = i ? ui::kIconR : ui::kIconL;
            const ImVec2 sz = ui::size_of(c.f.glyph, ui::lu(c, 90), code);
            c.d->AddText(c.f.glyph, ui::lu(c, 90), ImVec2(x - sz.x * 0.5f, ty - sz.y * 0.5f + ui::lu(c, 2)), ui::kInk, code);
        } else {   // (the keys: on our tabs the ones they take, as the guides name them (ui_ctx: the keys bound to the Switch's L and
            // R, else Q and E); on the game's own tab the keys bound to L and R, which are its own there and open ours)
            std::string label = c.pad ? (i ? "R" : "L") : (i ? c.key_tab_r : c.key_tab_l);
            if (!c.pad && sel < 0 && can_bind())
                if (const int vk = host->binding(HOS_BIND_KEY, i ? HOS_SW_R : HOS_SW_L, 0)) label = key_name(vk);
            const float kh = ui::lu(c, 62), kw = std::max(ui::lu(c, 62), ui::size_of(c.f.strong, ui::lu(c, 40), label.c_str()).x + ui::lu(c, 30));
            c.d->AddRectFilled(ImVec2(x - kw * 0.5f, ty - kh * 0.5f), ImVec2(x + kw * 0.5f, ty + kh * 0.5f), ui::kInk, ui::lu(c, 14));
            ui::text_mid_centre(c, c.f.strong, ui::lu(c, 40), x, ty, ui::rgba(40, 30, 20), label.c_str());
        }
        if (hit) hits.add(i ? x - ui::lu(c, 90) : 0, 0, i ? c.w : x + ui::lu(c, 90), hh, i ? menu_hit::kTabNext : menu_hit::kTabPrev, -1);
    }
    {   // ((Triforce) the logo and the name at the banner's left, left of the L key: at the tabs' size, smaller until they fit
        // (on half-point steps, to 34 units), or not at all where the strip leaves no room. The version stays on the System
        // tab, as before)
        float aspect = 1;
        ImTextureData* logo = ui::logo(&aspect);
        const float room = tx0 - ui::lu(c, 298) - ui::lu(c, 90) - c.safe - ui::lu(c, 40);
        const auto width = [&](float p) { return (logo ? p * 1.25f * aspect + ui::lu(c, 24) : 0) + ui::size_of(c.f.strong, p, "Triforce").x; };
        float px = tpx;
        while (px > ui::lu(c, 34) && width(px) > room) px -= 0.5f * s;
        if (room > 0 && width(px) <= room) {
            float lx = c.safe + ui::lu(c, 40);
            if (logo) {
                const float lh = px * 1.25f;
                c.d->AddImage(logo->GetTexRef(), ImVec2(lx, ty - lh * 0.5f), ImVec2(lx + lh * aspect, ty + lh * 0.5f));
                lx += lh * aspect + ui::lu(c, 24);
            }
            ui::text_mid(c, c.f.strong, px, lx, ty, ui::kInk, "Triforce");
        }
    }
}

/// A row's value cell over va..vb, as the options' list draws it and (Triforce) the tuning bar (draw_tune_bar): a mod's cheat, a
/// debug tool, a page, a slider, a toggle's halves or a choice. *t0, *t1: a slider's track; returns where a toggle's halves meet
/// (0: none), for the mouse
float row_value_cell(ui::Ctx& c, const Row& r, ImVec2 va, ImVec2 vb, bool selected, float* t0_out, float* t1_out) {
    float t0 = 0, t1 = 0, vm = 0;   // ((Triforce) vm: where a toggle's halves meet, for the mouse)
    if (const int cheat = mod_cheat_slot(r.name); cheat >= 0) {   // (Triforce: a mod's cheat: On | Off as the toggles, or why not)
        if (mod_cheats.fixed(cheat)) choice_cell(c, va, vb, mod_cheats.fixed_text(cheat), selected, false, false, true);
        else {
            halves_cell(c, va, vb, "On", "Off", !mod_cheats.is_on(cheat), selected, false);
            vm = halves_meet(va, vb);
        }
    } else if (r.cheat >= 0) {   // (a debug tool: On and Off, Link's age, a choice of its own, or a button that acts)
        if (r.cheat == 0 || r.cheat == 1 || r.cheat == 7) {
            halves_cell(c, va, vb, "On", "Off", cheat_value(r.cheat) != "On", selected, false);
            vm = halves_meet(va, vb);
        } else if (age_shown(r.cheat)) {   // (Link's age now: the other half switches)
            halves_cell(c, va, vb, "Kid", "Adult", link_age.load(std::memory_order_relaxed) == 1, selected, false);
            vm = halves_meet(va, vb);
        } else {
            static const char* const buttons[kCheatRows] = {"", "", "Mark", "Return", "", "", "", "", "Choose map", "Switch",
                                                            "Edit items", "Open list", "Open list", "Choose file", ""};
            const std::string v = cheat_value(r.cheat);
            if (cheat_chooses(r.cheat)) choice_cell(c, va, vb, v, selected, true, true);
            else action_cell(c, va, vb, v.empty() ? buttons[r.cheat] : v, selected, r.cheat == 9);   // (Switch age: none known yet)
        }
    } else if (!r.value) {   // (a page, or Restart and Quit: Confirm until the second press)
        const bool ends = false;
        if (pending == &r) choice_cell(c, va, vb, "Press again", selected, false, false);
        else if (r.name == kTestMic && mic_testing) {   // ((Triforce) 11-24: the level after the gain, both figures in words)
            char level[48];
            snprintf(level, sizeof level, "%d%% > %d%%", std::clamp(mic_levels[0], 0, 1000) / 10, std::clamp(mic_levels[1], 0, 1000) / 10);
            slider_cell(c, va, vb, level, std::clamp(mic_levels[1], 0, 1000), selected, &t0, &t1);
            t0 = t1 = 0;   // (a meter: nothing to drag)
        } else if (r.name == kTestMic) action_cell(c, va, vb, "Start test", selected);
        else if (reshade_menu::action_label(r.name)) action_cell(c, va, vb, reshade_menu::action_label(r.name), selected);
        else action_cell(c, va, vb, r.name == kUseWindowSize ? "Copy" : ends ? r.name : share_row(r) ? share_label(share_row(r)) : "Open", selected);
    } else {
        const bool fixed = row_fixed(r.value);
        // ((Triforce) the Output width or height being typed into: the digits so far and a caret, size_edit)
        const std::string typing = size_edit && size_edit == r.value ? size_text + "_" : std::string();
        if (is_slider(r) && !fixed) {   // ((Triforce) a fixed one: its value alone, as a choice with nothing to choose)
            slider_cell(c, va, vb, typing.empty() ? r.text(*r.value) : typing.c_str(),
                        menu_hit::slider_permille(*r.value, r.lo, r.hi), selected, &t0, &t1);
            t0 = t1 = 0;   // (no track to drag: the arrows step it)
        } else if (r.text == tx_onoff && !fixed) {   // (a toggle as the game's: On at the left, Off at the right)
            halves_cell(c, va, vb, "On", "Off", *r.value == 0, selected, fixed);
            vm = halves_meet(va, vb);
        } else {
            const bool output_row = r.value == &opts.output_res;
            bool left = !fixed && (!output_row || output_step(-1, false)) && (!stops_at_ends(r) || *r.value > r.lo);
            bool right = !fixed && (!output_row || output_step(1, false)) && (!stops_at_ends(r) || *r.value < r.hi);
            if (r.value == &opts.show_fps)   // ((Triforce) the FPS counter's levels stop at Off and Full: fps_levels.h step
                left = fps_levels::step(*r.value, -1) != *r.value, right = fps_levels::step(*r.value, 1) != *r.value;
            choice_cell(c, va, vb, r.text(*r.value), selected, left, right, fixed);
        }
    }
    *t0_out = t0, *t1_out = t1;
    return vm;
}

/// ((Triforce) The tuning bar (tune_mode): the options page's selected row at the foot of the screen, over the game seen whole,
/// with its tab's name, the row's name and value as in the list, and the guides; Up and Down choose the row, Left and Right
/// change it, L and R the tab, as on the page (menu_tick's page 0)
void draw_tune_bar(ui::Ctx& c) {
    const int count = tab_row_count(cur_tab), sel = tab_selected[cur_tab];
    if (count <= 0) return;
    const Row& r = rows[tab_row_to_global(cur_tab, std::clamp(sel, 0, count - 1))];
    static const char* const names[TAB_COUNT] = {"Display", "Graphics", "Audio", "Controls", "System", "Debug"};
    const char* tab = cur_tab == TAB_MOTION ? "Motion" : cur_tab == TAB_N64 ? "N64 Classic" : cur_tab < TAB_COUNT ? names[cur_tab] : "";
    // (the bar: the caption plate, 3000 x 330 units, its foot 60 units over the screen's)
    const ImVec2 a = ui::at(c, -1500, -1080 + 390), b = ui::at(c, 1500, -1080 + 60);
    ui::box(c, a, b, 0.92f);
    const float px = ui::lu(c, 40 * ui::kType), ty = a.y + ui::lu(c, 46);
    ui::text_mid(c, c.f.heading, px, a.x + ui::lu(c, 40), ty, ui::kGoldHi, tab);
    if (restart_changed(r))
        ui::text_mid(c, c.f.body, ui::lu(c, 36 * ui::kType), a.x + ui::lu(c, 80) + ui::size_of(c.f.heading, px, tab).x, ty, ui::kGoldHi,
                     "Applies after a restart");
    // (the row: as in the list, its plate 2200 units wide here, its value's panel 804 x 108 at its right)
    const float rh = ui::lu(c, 124), y = a.y + ui::lu(c, 96), my = y + rh * 0.5f;
    const float rx0 = a.x + ui::lu(c, 40), rx1 = b.x - ui::lu(c, 40), vx = rx1 - ui::lu(c, 452);
    name_cell(c, ImVec2(rx0, y), ImVec2(rx1, y + rh), r.name, true, restart_changed(r));
    const ImVec2 va(vx - ui::lu(c, 402), my - ui::lu(c, 54)), vb(vx + ui::lu(c, 402), my + ui::lu(c, 54));
    float t0 = 0, t1 = 0;
    const float vm = r.heading ? 0 : row_value_cell(c, r, va, vb, true, &t0, &t1);
    hits.add(rx0, y, rx1, y + rh, menu_hit::kRow, sel, va.x, vb.x, t0, t1, 0, vm);
    // (the guides, inside the bar's foot)
    const ui::Prompt list[4] = {{ui::kUpDown, "Choose"}, {ui::kLeftRight, "Change"}, {ui::kKey, "Full menu", "RCtrl"}, {ui::kBack, "Close"}};
    const float pw = ui::prompts(c, 0, 0, list, 4, false);
    ui::prompts(c, (a.x + b.x - pw) * 0.5f, b.y - ui::lu(c, 50), list, 4, true);
}

/// The Options screen: the header with the tabs across it (as the pause menu's categories: MenuOverlay_00, 460 units apart,
/// L and R at their ends), the rows in the list's column (SystemOption_00 and its rows' layouts: a row 1836 x 136 units, 170
/// apart, its name 840 left of the list's middle, its value's plate 820 x 116 at 500 right of it, the cursor round the
/// value), the caption plate at the right with what the selected row is, the guides at the foot
void draw_options(ui::Ctx& c) {
    merged_sync();   // ((Triforce, options_version 7) as menu_tick: the merged rows as the saved values are now)
    const float s = c.s, hh = banner_h(c);
    header_layer(c, true);   // ((Triforce, 11-19) over the Full panel inside the game's Options screen: draw_menu)
    ui::banner(c, hh);
    // (the pages rows open: under their tab, Motion and VR Controls under Controls, ((Triforce, N64 Classic) Remembered under Graphics)
    draw_tabs(c, page_parent(cur_tab), embed_open, true);
    header_layer(c, false);
    // the rows, in the column; the caption beside it
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    const int count = tab_row_count(cur_tab), sel = tab_selected[cur_tab];
    const Row& selr = rows[tab_row_to_global(cur_tab, sel)];
    const char* hint = selr.value && selr.hint ? selr.hint(*selr.value, -1) : nullptr;
    if (selr.name == kTestMic) hint = mic_test_line();   // ((Triforce) 11-24: what the test shows now)
    const std::string share_hint = share_row(selr) ? share_line(share_row(selr)) : std::string();   // (Triforce: what the host did)
    if (!share_hint.empty()) hint = share_hint.c_str();
    const int sel_cheat = mod_cheat_slot(selr.name);   // (Triforce: a mod's cheat: the mod it is from, or why it cannot be switched)
    if (sel_cheat >= 0 && mod_cheats.line(sel_cheat)[0]) hint = mod_cheats.line(sel_cheat);
    const float cap_w = hx1 - hx0 - 2 * ui::lu(c, 76);
    const std::string pending_line = restart_pending() ? restart_line(c, kHintPt * s, cap_w - 20 * s) : "";
    static float help_tall = 0, help_tall_w = 0;
    static int help_tall_lang = -1;   // ((Triforce) the menu's language it was measured in: another one's texts are longer or shorter)
    if (help_tall_w != cap_w || help_tall_lang != i18n::lang_now())
        help_tall_w = cap_w, help_tall_lang = i18n::lang_now(), help_tall = measure_help(c, cap_w);
    // (the guides: what the buttons do on this row, as the game's own say only that)
    const bool confirms = false;   // ((Triforce) 11-19: no Restart and Quit rows any more: the pause menu's Quit)
    ui::Prompt prompt_list[5] = {{ui::kLeftRight, "Change"}, {ui::kTabs, "Category"}, {ui::kBack, "Back"}};
    int prompts_n = 3;
    if (!selr.value) prompt_list[0] = {ui::kConfirm, confirms ? (pending == &selr ? "Confirm" : selr.name) : "Open"};
    if (share_row(selr)) prompt_list[0] = {ui::kConfirm, share_label(share_row(selr))};
    if (n64_action(selr)) prompt_list[0] = {ui::kConfirm, "Apply"};   // ((Triforce, N64 Classic) Copy Faithful, Reset to defaults)
    if (sel_cheat >= 0) prompt_list[0] = {ui::kLeftRight, "Change"};   // (Triforce: a mod's cheat, On | Off)
    if (sub_page(cur_tab)) prompt_list[1] = {ui::kBack, "Back"}, prompts_n = 2;   // (Esc: to the tab it is under)
    if (is_sim_turf_reset_row(selr)) prompt_list[0] = {ui::kConfirm, "Reset"};
    if (selr.cheat >= 0) {   // (a debug tool: Change when Left and Right do something, then what confirm does)
        prompts_n = 0;
        if (selr.cheat <= 1 || selr.cheat == 7 || cheat_chooses(selr.cheat) || age_shown(selr.cheat))
            prompt_list[prompts_n++] = {ui::kLeftRight, "Change"};
        if (const char* says = cheat_confirm(selr.cheat)) prompt_list[prompts_n++] = {ui::kConfirm, says};
        prompt_list[prompts_n++] = {ui::kTabs, "Category"}, prompt_list[prompts_n++] = {ui::kBack, "Back"};
    }
    // ((Triforce) over play, with the keys: Right Ctrl's tuning bar, draw_tune_bar)
    if (!embed_open && !c.pad && prompts_n < 5) prompt_list[prompts_n++] = {ui::kKey, "Tuning bar", "RCtrl"};
    const float bar_top = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    const bool after = restart_changed(selr);
    caption(c, hx0, hx1, nullptr, selr.help, hint, pending_line.empty() ? nullptr : pending_line.c_str(), help_tall, after);
    // (measured on the game's screen: a row's plate 1824 x 124, 170 apart, the first one's top 344 under the screen's top; the
    // value's near-black panel 804 x 108, its middle 500 right of the list's)
    const float rx = ui::at(c, kListX, 0).x, half = ui::lu(c, 912), rx0 = rx - half, rx1 = rx + half;
    const float rh = ui::lu(c, 124), pitch = ui::lu(c, 170), top = ui::at(c, 0, 736).y, bottom = ui::at(c, 0, -790).y;
    const float vx = rx + ui::lu(c, 500), vhw = ui::lu(c, 402), vhh = ui::lu(c, 54);
    const float clip0 = hh - ui::lu(c, 14), clip1 = bar_top + ui::lu(c, 50);
    // (the list from the top: the tab's rows in their order, headings among them. (Triforce) The Debug tab's the same way, in
    // its own order (debug_list: its groups' headings among its rows), with the same column, rows, headings and buttons as
    // every other tab: it had a layout of its own before, a plain rule for a heading, blank rows between its groups, other
    // widths and orange buttons without their arrow)
    static int list[kDebugList];
    int listed = 0;
    if (cur_tab == TAB_DEBUG) listed = debug_list(list);
    else
        for (int i = 0; i < count; i++) list[listed++] = i;
    int sel_at = 0;
    for (int j = 0; j < listed; j++)
        if (list[j] == sel) sel_at = j;
    int shown = 0;
    const float first = scroll_rows(cur_tab, listed, sel_at, top, bottom, pitch, &shown);
    scroll_bar(c, ui::at(c, kListX - 1102, 0).x, ui::at(c, 0, 100).y, ui::at(c, 0, -212).y, listed, shown, first);   // (PaScrollBar: 56 under the middle)
    marquee_max = 0;   // (set again below while the selected row's value is too long)
    c.d->PushClipRect(ImVec2(cx0, clip0), ImVec2(cx1, clip1), true);
    for (int j = 0; j < listed; j++) {
        const float y = top + (j - first) * pitch, my = y + rh * 0.5f;
        // ((Triforce) a row whose top would be under the header is not drawn: the row above the first one in view slid under
        // the tabs with its top cut off. Toward the guides a row may go on, as the game's own list goes off the screen)
        if (y < clip0 || y > clip1) continue;
        const int i = list[j];   // (the row on the tab; negative: a Debug group's heading, -1 - its group)
        const Row& r = rows[tab_row_to_global(cur_tab, std::max(i, 0))];
        if (i < 0 || r.heading) {   // (a group: the game's separator, its title under it in gold at the names' place; no hit)
            ui::heading(c, ImVec2(rx0, y), ImVec2(rx1, y + rh), rx0 + ui::lu(c, 72), i < 0 ? debug_groups[-1 - i].title : r.name);
            continue;
        }
        const bool selected = i == sel;
        name_cell(c, ImVec2(rx0, y), ImVec2(rx1, y + rh), r.name, selected, restart_changed(r));
        const ImVec2 va(vx - vhw, my - vhh), vb(vx + vhw, my + vhh);
        float t0 = 0, t1 = 0;
        const float vm = row_value_cell(c, r, va, vb, selected, &t0, &t1);
        hits.add(rx0, std::max(y, clip0), rx1, std::min(y + rh, clip1), menu_hit::kRow, i, va.x, vb.x, t0, t1, 0, vm);
    }
    c.d->PopClipRect();
    if (cur_tab == TAB_SYSTEM) {   // (which build, so a report can say it without opening the log)
        const std::string ver = std::string("Triforce ") + HOOKSHOT_VERSION;
        ui::text_mid(c, c.f.body, ui::lu(c, 36), ui::at(c, -1840, 0).x, ui::at(c, 0, -1030).y, ui::rgba(255, 251, 238, 120), ver.c_str());
    }
    ui::prompt_bar(c, prompt_list, prompts_n);   // (the guides, on top of the caption and the rows)
}

/// ((Triforce) per-control reset and confirmed rebinds) The Controls page's question (control_confirmation) over it, as the
/// restart question is drawn: its title in the banner, what changes, Cancel (the lower button, the choice at first) and the
/// change (the upper one)
void draw_control_confirmation(ui::Ctx& c) {
    const ControlConfirmation& q = control_confirmation;
    dim_page(c, ui::rgba(8, 5, 2, 110));
    std::string ask;
    const char *title = "Reset Control", *accept = "Reset";
    if (q.action == kAskRebind) {
        title = "Input In Use", accept = "Bind";
        const std::string what = q.set == HOS_BIND_PAD ? pad_name(q.code) : key_name(q.code);
        ask = what + i18n::tr(" is bound to ") + control_names(q.conflicts) + i18n::tr(". Bind it to ") +
              i18n::tr(controls[q.row].name) +
              (q.set == HOS_BIND_PAD ? i18n::tr(" anyway? That control takes this one's gamepad input in its place, or loses it.")
                                     : i18n::tr(" anyway? That control loses it."));
    } else if (q.action == kAskResetRow) {
        ask = i18n::tr(controls[q.row].name) + std::string(i18n::tr(": its default gamepad input and keys back?"));
    } else {
        title = "Reset All Controls", accept = "Reset All";
        ask = i18n::tr("Every control's gamepad inputs and keys back to their defaults, and the Layout preset to its first?");
    }
    ui::banner(c, 0, title);
    const float wrap = ui::lu(c, 1440), px = ui::lu(c, 54 * ui::kType);
    const float th = ui::para(c, c.f.body, px, ImVec2(), 0, ask.c_str(), wrap, false);
    float y = ui::at(c, 0, 250).y - th * 0.5f;
    for (const char *t = ask.c_str(), *end = t + ask.size(); t < end;) {   // (each line centred, as draw_ask's)
        const char* cut = c.f.body->CalcWordWrapPosition(px, t, end, wrap);
        if (cut == t) cut = t + 1;
        const float lw = c.f.body->CalcTextSizeA(px, FLT_MAX, 0, t, cut).x;
        c.d->AddText(c.f.body, px, ImVec2(c.w * 0.5f - lw * 0.5f, y), ui::kInk, t, cut);
        y += px * 1.3f;
        t = cut;
        while (t < end && (*t == ' ' || *t == '\n')) t++;
    }
    const float bw = ui::lu(c, 336), bh = ui::lu(c, 72);
    const char* labels[2] = {"Cancel", accept};
    for (int i = 0; i < 2; i++) {
        const float my = ui::at(c, 0, i ? -330.0f : -518.0f).y;
        const ImVec2 a(c.w * 0.5f - bw, my - bh), b(c.w * 0.5f + bw, my + bh);
        ui::button(c, a, b, labels[i], i == q.choice);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, i);
    }
    const ui::Prompt prompt_list[] = {{ui::kConfirm, "Confirm"}, {ui::kBack, "Cancel"}};
    ui::prompt_bar(c, prompt_list, 2);
}

void draw_controls(ui::Ctx& c) {
    // (the page's own rows first, kTop of them (the layout preset, the button prompts), then a row per control and Reset to
    // defaults: one list, csel its selection)
    const float s = c.s, hh = title_banner(c, "Controls", nullptr);
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const int n = kTop + kControls + 1, sel_i = csel - kTop;   // (sel_i: the control's, kControls Reset; negative: a page row)
    // ((Triforce) per-control reset: Clear by a controller's free face button too, ui::kClear)
    const ui::Prompt idle[] = {{ui::kUpDown, "Choose"}, {ui::kLeftRight, "Column"}, {ui::kConfirm, "Bind"}, {ui::kClear, "Clear"},
                               {ui::kBack, "Back"}};
    const ui::Prompt option[] = {{ui::kUpDown, "Choose"}, {ui::kLeftRight, "Change"}, {ui::kBack, "Back"}};
    const ui::Prompt wait[] = {{ui::kKey, "Cancel", "Esc"}};   // ((Triforce) Esc alone while it waits: B's key may be the one bound)
    const ui::Prompt reset[] = {{ui::kUpDown, "Choose"}, {ui::kLeftRight, "Column"}, {ui::kConfirm, "Reset"}, {ui::kBack, "Back"}};
    const bool on_reset = sel_i >= 0 && sel_i < kControls && ccol == kColReset && col_usable(sel_i, kColReset);
    const float bar_top = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    const Row* page_row = sel_i < 0 ? &rows[tab_row_to_global(TAB_PAGE, csel)] : nullptr;
    const char* title = page_row ? page_row->name : sel_i < kControls ? controls[sel_i].name : "Reset to defaults";
    const char* help = listening ? (listening == 1 ? "Press the gamepad button to use. Esc cancels." : "Press the key to use. Esc cancels.")
                       : page_row ? page_row->help
                       : on_reset ? (blocked_reset_row == sel_i ? "Another control has one of this control's defaults. Clear it there first."
                                                                : "Puts this control's default gamepad input and keys back.")
                                  : "Which gamepad inputs and which keys press each of the Switch's buttons: either of its two "
                                    "gamepad inputs presses it. Enter binds the one selected; Delete clears it. A button's only "
                                    "gamepad input stays with it. The game's button icons follow after a restart.";
    const char* hint = page_row ? (page_row->hint ? page_row->hint(*page_row->value, -1) : nullptr)
                       : note_row(sel_i) ? "An ocarina note's input is a note only while the ocarina waits for one; away from it, it "
                                           "does its other job. Unset, the game's own button plays the note."
                       : sel_i < kControls && controls[sel_i].button == HOS_KEY_TOGGLE_HUD
                           ? "A press hides the HUD in play, the next shows it again. Its inputs are its own while it has them; "
                             "another control bound to one has it back once this is cleared."
                                         : "Gamepad: the D-pad moves, A binds, B goes back.";
    const float bottom = bar_top - 6 * s;   // (the rows end above the guides)
    caption(c, hx0, hx1, title, help, hint, nullptr, 0, page_row && restart_changed(*page_row));
    // (the options' rows, a little lower: 30 controls. A plate across the row, its name at the left, the gamepad's input and the
    // keys on value plates at the right)
    const float rxm = ui::at(c, kListX, 0).x, rx0 = rxm - ui::lu(c, 912), rx1 = rxm + ui::lu(c, 912);
    // ((Triforce) 11-24: three value cells, the gamepad's two inputs and the keys)
    const float pad_x = rx0 + (rx1 - rx0) * 0.30f, alt_x = rx0 + (rx1 - rx0) * 0.51f, key_x = rx0 + (rx1 - rx0) * 0.72f;
    const float rh = ui::lu(c, 112), pitch = ui::lu(c, 140), vin = ui::lu(c, 8);
    // ((Triforce) per-control reset: a square at the row's right end, the keys' cell narrower by it, where the host has it)
    const float reset_side = can_reset_rows() ? rh - 2 * vin : 0, reset_x1 = rx1 - ui::lu(c, 8), reset_x0 = reset_x1 - reset_side;
    const float col_x[kColReset + 1] = {pad_x, alt_x, key_x, can_reset_rows() ? reset_x0 - 3 * s : rx1 - ui::lu(c, 8)};
    float top = hh + 12 * s;
    ui::text_mid_centre(c, c.f.body, ui::lu(c, 40), (pad_x + alt_x) * 0.5f, top + 9 * s, ui::kSoft, "Input 1");
    ui::text_mid_centre(c, c.f.body, ui::lu(c, 40), (alt_x + key_x) * 0.5f, top + 9 * s, ui::kSoft, "Input 2");
    ui::text_mid_centre(c, c.f.body, ui::lu(c, 40), (key_x + rx1) * 0.5f - ui::lu(c, 8), top + 9 * s, ui::kSoft, "Keyboard");
    top += 24 * s;
    int shown = 0;
    const float first = scroll_rows(kControlsSlot, n, csel, top, bottom, pitch, &shown);
    scroll_bar(c, cx0 + 20 * s, top, top + shown * pitch - (pitch - rh), n, shown, first);
    c.d->PushClipRect(ImVec2(cx0, top - 8 * s), ImVec2(cx1, bottom + 8 * s));
    for (int j = 0; j < n; j++) {
        const float y = top + (j - first) * pitch;
        if (y + rh < top - 8 * s || y > bottom + 8 * s) continue;
        const bool sel = j == csel;
        const int i = j - kTop;
        const float y0 = std::max(y, top - 8 * s), y1 = std::min(y + rh, bottom + 8 * s);
        if (i < 0) {   // (one of the page's own rows: a name and a choice, as on the tabs)
            const Row& r = rows[tab_row_to_global(TAB_PAGE, j)];
            // (their names wider than a control's, as wide as the tabs' rows': "Button prompts" whole at any size)
            const float opt_x = rx0 + (rx1 - rx0) * 0.5f;
            name_cell(c, ImVec2(rx0, y), ImVec2(rx1, y + rh), r.name, sel, restart_changed(r), 17);
            choice_cell(c, ImVec2(opt_x, y + vin), ImVec2(rx1 - vin, y + rh - vin), r.text(*r.value), sel, *r.value > r.lo, *r.value < r.hi);
            hits.add(rx0, y0, rx1, y1, menu_hit::kCtlOption, j, opt_x, rx1);
            continue;
        }
        if (i == kControls) {
            ui::button(c, ImVec2(rx0, y + ui::lu(c, 10)), ImVec2(pad_x + ui::lu(c, 120), y + rh + ui::lu(c, 10)), "Reset to defaults", sel);
            hits.add(rx0, y0, pad_x + ui::lu(c, 120), y1 + ui::lu(c, 10), menu_hit::kCtlRow, i);
            continue;
        }
        const Control& ctl = controls[i];
        name_cell(c, ImVec2(rx0, y), ImVec2(rx1, y + rh), ctl.name, sel, false, 17);
        hits.add(rx0, y0, pad_x, y1, menu_hit::kCtlRow, i);
        if (can_reset_rows()) {   // ((Triforce) per-control reset: its square, an arrow turning back; dim when there is nothing to reset)
            const bool usable = col_usable(i, kColReset), here = sel && ccol == kColReset && usable;
            const ImVec2 va(reset_x0, y + vin), vb(reset_x1, y + rh - vin);
            choice_cell(c, va, vb, "", here, false, false, !usable);
            const ImVec2 m = (va + vb) * 0.5f;
            const float r = reset_side * 0.26f, end = -0.92f;   // (an arc from the left round to the top right, its head there)
            const ImU32 ink = usable ? ui::kInk : ui::kSoft;
            c.d->PathArcTo(m, r, 4.06f, end, 20);
            c.d->PathStroke(ink, ImDrawFlags_None, std::max(1.0f, reset_side * 0.06f));
            const ImVec2 radial(std::cos(end), std::sin(end)), tangent(radial.y, -radial.x), head = m + radial * r;
            const ImVec2 base = head - tangent * (reset_side * 0.1f), wing = radial * (reset_side * 0.11f);
            c.d->AddTriangleFilled(head + tangent * (reset_side * 0.11f), base + wing, base - wing, ink);
            if (usable) hits.add(va.x, y0, vb.x, y1, menu_hit::kCtlCell, i, 0, 0, 0, 0, kColReset);
        }
        for (int col = 0; col < kColReset; col++) {   // (three value cells, gaps between them, each drawn as the tabs' values are)
            const float a = col_x[col] + (col ? 3 * s : 0), b = col_x[col + 1] - (col + 1 < kColReset ? 3 * s : 0);
            const bool usable = col_usable(i, col);
            std::string v = col == kColKeys ? keys_text(ctl.button) : !usable ? "-"
                          : pad_name(host->binding(HOS_BIND_PAD, ctl.button, col == kColAlt ? 1 : 0));
            const bool here = sel && col == ccol;
            const ImVec2 va(a, y + vin), vb(b, y + rh - vin);
            if (here && listening) {   // (waiting for the new input: the light plate, the cursor round it)
                ui::value_plate(c, va, vb);
                ui::text_mid_centre(c, c.f.body, ui::lu(c, 50), (a + b) * 0.5f, y + rh * 0.5f - ui::lu(c, 2), ui::kInk,
                                    col != kColKeys ? "Press a button..." : "Press a key...");
                ui::cursor(c, va - ImVec2(ui::lu(c, 2.5f), ui::lu(c, 3)), vb + ImVec2(ui::lu(c, 2.5f), ui::lu(c, 3)));
            } else {
                choice_cell(c, va, vb, v, here, false, false, !usable);
            }
            if (usable) hits.add(a, y0, b, y1, menu_hit::kCtlCell, i, 0, 0, 0, 0, col);
        }
    }
    c.d->PopClipRect();
    if (control_confirmation.action != kAskNone) draw_control_confirmation(c);   // ((Triforce) its own prompts)
    else (void)(listening ? ui::prompt_bar(c, wait, 1) : sel_i < 0 ? ui::prompt_bar(c, option, 3)
                : on_reset || sel_i == kControls ? ui::prompt_bar(c, reset, 4) : ui::prompt_bar(c, idle, 5));   // (the prompts, on top of the help and the rows)
}

// ---- (Triforce) The Debug tab's name pages: Game flags, Cutscenes and Scan amiibo (page 6) ----
// After NX2navi's F9 panel (its flags by name and its cutscene starter) and its amiibo page, in this menu's own form; none
// of that code is here. One page for the three: a list of names in groups (debug_names.h), the cards of the group shown,
// the chosen one's action. The flags' and the events' names are read from the player's own game files, in memory, on a
// thread of its own the first time one of the two pages opens (ui::game_files); the amiibo page lists the game folder's
// amiibo folder each time it opens. What a page wants goes to the game's side as lines (oot_debug_link.h): the flags' and
// the events' through HOS_OPT_DEBUG_ASK, read at Link's update (host/hos_main.c), a figure's file through
// HOS_OPT_AMIIBO_ASK, read at the pad read (host/nn_nfp.c); what the game's side says comes back through
// menu_option_set. The game's side reads only while the game runs: a change asked for inside the game's paused Options
// screen is made when the game goes on. Nothing is read, listed or sent before a page is opened.
enum { kNamesFlags, kNamesEvents, kNamesAmiibo, kNamesKinds };
namespace dn = debug_names;
int names_kind = kNamesFlags;
dn::Page names_page[kNamesKinds];
bool names_edit = false;   // (a flag's On and Off are chosen with Left and Right)
std::mutex names_mu;       // (the scan's lists and the lines either way: the scan's thread and the host's threads use them too)
std::atomic<int> names_scan{0};   // (0 not started, 1 the game's files are being read, 2 read, 3 the game's files were not found)
dn::List names_scanned[2];        // (the flags' and the events', until the pages take them)
std::atomic<bool> names_new{false};
dn::Lines names_ask, amiibo_ask;  // (HOS_OPT_DEBUG_ASK's and HOS_OPT_AMIIBO_ASK's lines)
dn::States names_states;          // (the flags' states for the cards shown)
bool names_watching = false;      // (the game's side was asked for some flags' states)
std::string names_in;             // (the line the game's side is sending, a byte a call)
std::string names_status;         // (what became of the last flag or event asked for)
std::string names_status_of;      // (the flag or the event that was: its line shows while that name is the chosen one)
int names_status_kind = -1;       // (and which: a flag and an event may have the same name)
std::atomic<bool> names_asked{false};   // (a flag or an event was asked for since the Debug tools were last seen off)
std::atomic<bool> names_status_new{false};
std::atomic<int> amiibo_said{HOS_AMIIBO_NONE};   // (what became of the figure: HOS_AMIIBO_*)
std::atomic<bool> amiibo_new{false};
std::string amiibo_chosen;        // (the file last sent, "" none)
/// What the Scan amiibo page says became of the figure (short: the line at the foot of the screen while the options are closed)
const char* amiibo_text(int said, bool brief) {
    switch (said) {
    case HOS_AMIIBO_WAITING: return brief ? "amiibo: waiting for the game to look for it" : "Chosen. It is on the reader as soon as the game looks for a figure.";
    case HOS_AMIIBO_ON_READER: return brief ? "amiibo: the game found the figure" : "The game found the figure and reads it.";
    case HOS_AMIIBO_READ: return brief ? "amiibo: read by the game" : "The game has read the figure. Choose it again for another touch.";
    case HOS_AMIIBO_REFUSED: return brief ? "amiibo: not a figure's dump" : "That file is not a figure's dump (532, 540 or 572 bytes, as a tag has them, or a Flipper .nfc file of one).";
    case HOS_AMIIBO_NO_FILE: return brief ? "amiibo: the file could not be read" : "The file could not be read.";
    }
    return nullptr;
}
/// What a name page is, for its caption
const char* names_help(int kind) {
    static const char* const help[kNamesKinds] = {
        "The game's flags by name, as your game files have them. Confirm, then Left sets the chosen flag and Right clears it. The game "
        "takes a change when it runs.",
        "The game's events by name, as your game files have them. Start asks the game for the chosen one as one of its own actors "
        "would. It starts when the game runs. Save first.",
        "Dumps of your own figures. Scan puts the chosen one on the reader when the game looks for a figure. Only the figure's serial "
        "number and which figure it is are read from the file: no key is needed."};
    return help[kind];
}
/// The flags' and the events' names from the player's game files, on a thread of its own (once a run): the Bools' hashes of
/// the GameDataList (the last by name: the highest version), then every event flow, for the flags' names in it and whether
/// it is an event. In memory only; the log gets the counts
void names_scan_thread() {
    std::vector<uint32_t> bools;
    std::vector<std::string> flags, events;
    const int64_t t0 = prof_now();
    bool found = ui::game_files("GameData", ".byml.zs", [&](const std::string& name, const std::vector<unsigned char>& bytes) {
        std::vector<uint32_t> got;
        if (!name.compare(0, 13, "GameDataList.") && dn::gamedata_bools(bytes, got)) bools = std::move(got);
    });
    found = found && ui::game_files("Event/EventFlow", ".bfevfl.zs", [&](const std::string& name, const std::vector<unsigned char>& bytes) {
        if (dn::event_has_script(bytes)) events.push_back(dn::event_of_file(name));
        dn::flag_names(bytes, bools, flags);
    });
    dn::List flag_list = dn::make_list(std::move(flags)), event_list = dn::make_list(std::move(events));
    logf("menu: the Debug tab's names, from the game's files: %d flags' names for %d Bools, %d events (%.0f ms)%s", (int)flag_list.names.size(),
         (int)bools.size(), (int)event_list.names.size(), (prof_now() - t0) / 1e6, found ? "" : "; the game's files were not found");
    {
        std::lock_guard lk(names_mu);
        names_scanned[0] = std::move(flag_list), names_scanned[1] = std::move(event_list);
    }
    names_scan.store(found ? 2 : 3, std::memory_order_release);
    names_new.store(true, std::memory_order_release);
}
/// A name page opened from its row on the Debug tab
void names_open(int kind) {
    names_kind = kind, names_edit = false, page = 6;
    if (kind == kNamesAmiibo) {   // (the folder as it is now: a dump put there since shows without a restart)
        char exe[MAX_PATH];
        const DWORD n = game_module_path(exe, MAX_PATH);
        const std::string dir(exe, n);
        // ((Triforce) a tag's bytes, .bin, and a Flipper Zero's NFC files, .nfc: host/amiibo.h amiibo_flipper)
        const std::string folder = dir.substr(0, dir.find_last_of("\\/") + 1) + "amiibo";
        std::vector<std::string> dumps = ui::folder_files(folder, ".bin"), nfc = ui::folder_files(folder, ".nfc");
        dumps.insert(dumps.end(), nfc.begin(), nfc.end());
        names_page[kind].set_list(dn::make_list(std::move(dumps), false, "Your figures"));
    } else {
        int none = 0;
        if (names_scan.compare_exchange_strong(none, 1)) std::thread(names_scan_thread).detach();
    }
}
/// The chosen flag asked to be set or cleared. Once: Left or Right held repeats the key, and the same request is not queued
/// again behind itself
void names_send_flag(bool on) {
    const dn::Page& p = names_page[kNamesFlags];
    char line[32];
    if (p.empty() || !oot_ask_flag(line, sizeof line, p.list.hashes[p.choice], on)) return;
    std::lock_guard lk(names_mu);
    if (!names_ask.repeats(line)) names_ask.push(line);
    names_asked.store(true, std::memory_order_relaxed);
    names_status = on ? "Asked to set it: done when the game runs." : "Asked to clear it: done when the game runs.";
    names_status_of = p.list.names[p.choice], names_status_kind = kNamesFlags;
}
/// Confirm on the chosen name: a flag's On and Off are chosen next; an event is asked for, and the options close (it starts
/// when the game goes on); a figure's file is sent, or the figure taken away when it is the one that waits or is being read
void names_confirm(bool& changed) {
    dn::Page& p = names_page[names_kind];
    const std::string& name = p.list.names[p.choice];
    changed = true;
    if (names_kind == kNamesFlags) {
        names_edit = true;
        return;
    }
    std::lock_guard lk(names_mu);
    if (names_kind == kNamesEvents) {
        char line[OOT_LINE_MAX + 1];
        if (oot_ask_event(line, sizeof line, name.c_str())) names_ask.push(line);
        names_asked.store(true, std::memory_order_relaxed);
        names_status = "Asked for: it starts when the game runs.";
        names_status_of = name, names_status_kind = kNamesEvents;
        open_now = false, page = 0;
        return;
    }
    const int said = amiibo_said.load(std::memory_order_relaxed);
    const bool away = (said == HOS_AMIIBO_WAITING || said == HOS_AMIIBO_ON_READER) && amiibo_chosen == name;
    amiibo_chosen = away ? std::string() : name;
    if (amiibo_ask.waiting.size() > (amiibo_ask.at ? 1u : 0u)) amiibo_ask.waiting.resize(amiibo_ask.at ? 1 : 0);   // (the newest choice alone)
    amiibo_ask.push(amiibo_chosen);
}
/// (Triforce) the mouse on a name page: a card is chosen by a click, the action button acts, the group's and the page's
/// arrows turn them, a flag's halves set and clear it; the wheel turns the page shown and leaves the choice; a right click
/// goes back
void names_mouse(const MkwVkPointer& ptr, int mx, int my, bool* press, bool& changed) {
    dn::Page& p = names_page[names_kind];
    const menu_hit::Hit hit = hits.at((float)mx, (float)my);
    if (ptr.pressed & HOS_MOUSE_LEFT) {
        if (hit.part == menu_hit::kListLine && p.choose(hit.index)) names_edit = false, changed = true;
        else if (hit.part == menu_hit::kButton && hit.index == 0) press[7] = true;
        else if (hit.part == menu_hit::kButton && hit.index == 1 && hit.side) press[hit.side < 0 ? 3 : 4] = true;
        else if (hit.part == menu_hit::kButton && (hit.index == 2 || hit.index == 3)) press[hit.index == 2 ? 13 : 14] = true, names_edit = false;
        else if (hit.part == menu_hit::kButton && hit.index == 4 && hit.side) p.turn_group(hit.side), names_edit = false, changed = true;
    }
    if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
    if (ptr.wheel) p.turn_shown(-ptr.wheel), changed = true;
}
/// (Triforce) the keys on a name page: back leaves a flag's On and Off first, then the page (to the Debug tab, its row still
/// selected); L and R another group; the arrows, Page Up and Down, Home and End move the choice; confirm acts
void names_press(const bool* press, bool tab_left, bool tab_right, bool& changed) {
    dn::Page& p = names_page[names_kind];
    if (press[5] && names_edit) names_edit = false, changed = true;
    else if (press[5]) page = 0, changed = true;
    else if (p.empty()) return;
    else if (tab_left || tab_right) p.turn_group(tab_left ? -1 : 1), names_edit = false, changed = true;
    else if (names_edit) {   // (a flag: Left sets it, Right clears it, as its halves are drawn)
        if (press[7]) names_edit = false, changed = true;
        else if (press[3] || press[4]) names_send_flag(press[3]), changed = true;
    } else {
        const int cards = press[4] - press[3], card_rows = press[2] - press[1], pages = press[14] - press[13];
        if (cards || card_rows || pages || press[15] || press[16]) p.move(cards, card_rows, pages, press[15], press[16]), changed = true;
        else if (press[7]) names_confirm(changed);
    }
}
/// (Triforce) Each tick: the lists the scan made are taken; the game's side is asked for the states of the flags shown (and
/// told when none is shown any more); and what it said while the options are closed is the line at the foot of the screen
void names_tick() {
    if (names_new.exchange(false, std::memory_order_acquire)) {
        std::lock_guard lk(names_mu);
        names_page[kNamesFlags].set_list(std::move(names_scanned[0]));
        names_page[kNamesEvents].set_list(std::move(names_scanned[1]));
        names_edit = false;   // (another list under the choice: not in the middle of a flag's On and Off)
    }
    // (the Debug tools turned off: what was asked of the game and not yet taken by it is not done after all)
    if (!cheats_on() && names_asked.exchange(false, std::memory_order_relaxed)) {
        std::lock_guard lk(names_mu);
        names_ask.drop_but('W');
    }
    const bool open = open_now.load(), shows_flags = open && page == 6 && names_kind == kNamesFlags;
    if (shows_flags || names_watching) {
        const std::vector<uint32_t> shown = shows_flags ? names_page[kNamesFlags].watched() : std::vector<uint32_t>();
        char line[OOT_LINE_MAX + 1];
        std::lock_guard lk(names_mu);
        if (names_states.ask(shown) && oot_ask_watch(line, sizeof line, shown.data(), (int)shown.size())) names_ask.push(line, 'W');
        names_watching = !shown.empty();
    }
    if (!open || page != 6) names_edit = false;
    const bool said = names_status_new.exchange(false, std::memory_order_relaxed), figure = amiibo_new.exchange(false, std::memory_order_relaxed);
    if (open || (!said && !figure)) return;
    const char* text = figure ? amiibo_text(amiibo_said.load(std::memory_order_relaxed), true) : nullptr;
    std::lock_guard lk(names_mu);
    if (!text && !said) return;
    snprintf(notice_text, sizeof notice_text, "%s", text ? text : names_status.c_str());
    notice_until = prof_now() + 2500000000LL;
}

/// A small square page arrow at a (its size side): dir 0 back, 1 on; dim when it cannot go that way
void page_arrow(ui::Ctx& c, ImVec2 a, float side, int dir, bool can) {
    const float s = c.s;
    const ImVec2 b = a + ImVec2(side, side);
    c.d->AddRectFilled(a, b, can ? ui::kCellName : ui::alpha(ui::kCellName, 0.4f), 3 * s);
    c.d->AddRect(a, b, can ? ui::kEdge : ui::alpha(ui::kEdge, 0.4f), 3 * s, std::max(1.0f, s));
    ui::triangle(c, (a + b) * 0.5f, 10 * s, dir, can ? ui::kInkBright : ui::kDim);
}

/// A tag at the right end of a card (its right edge x, its middle y): the text on an accent plate; its width
float card_tag(ui::Ctx& c, float x, float y, const char* tag, bool draw = true) {
    const float s = c.s, tw = ui::size_of(c.f.strong, 13 * s, tag).x + 14 * s;
    if (draw) {
        const ImVec2 g(x - tw, y - 10 * s);
        c.d->AddRectFilled(g, g + ImVec2(tw, 20 * s), ui::kAccent, 2 * s);
        ui::text_mid(c, c.f.strong, 13 * s, g.x + 7 * s, y, ui::kGoldInk, tag);
    }
    return tw;
}
/// (Triforce) A card's second line when it says "not": Locked, Quantity 0, Not in this save. Quieter than a line that says
/// "has", and still read at a glance: ui::kDim, which it was, is the plate's own tone and could not be read on it
const ImU32 kCardOff = ui::alpha(ui::kSoft, 0.62f);

void draw_inventory(ui::Ctx& c) {
    const float s = c.s;
    const int begin = inventory_begin(), end = inventory_end();
    bool loaded = false;   // (a save's counts reported: -1 for all until the game side has a save to read)
    for (int i = 0; i < kItems && !loaded; ++i) loaded = item_counts[i].load(std::memory_order_relaxed) >= 0;
    char count_text[48];
    snprintf(count_text, sizeof count_text, "%d items", end - begin);
    const float hh = title_banner(c, "Inventory", count_text);
    // ((Triforce) the cards and the amount show the change asked and not yet taken by the game: in its paused Options screen
    // it is taken when the game goes on, and a press that changed nothing on the screen read as one that did nothing)
    const int pending = cheat_action.load(std::memory_order_relaxed);
    const int have = debug_pending::shown(pending, item_choice, item_counts[item_choice].load(std::memory_order_relaxed));
    const char* edit = item_kinds[item_choice] ? (inventory_amount ? "Done" : "Edit amount") : (have ? "Relock" : "Unlock");
    // ((Triforce) no "Move" for Up and Down while an amount is changed: they do nothing then)
    ui::Prompt prompts[5];
    int prompts_n = 0;
    if (!inventory_amount) prompts[prompts_n++] = {ui::kUpDown, "Move"};
    prompts[prompts_n++] = {ui::kLeftRight, inventory_amount ? "Amount" : "Move"};
    prompts[prompts_n++] = {ui::kTabs, "Section"};
    if (have >= 0) prompts[prompts_n++] = {ui::kConfirm, edit};
    prompts[prompts_n++] = {ui::kBack, inventory_amount ? "Done" : "Back"};
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const float bar = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    const float left = cx0 + 24 * s, right = cx1 - 24 * s;
    const float gap = 10 * s;
    // the sections, as tabs over the grid (Q and E, or a click)
    // (on one line: their padding, then their text, made smaller as far as needed for the column's width)
    float tpx = 16 * s, tpad = 26 * s, tgap = 8 * s;
    auto tabs_w = [&] {
        float w = 0;
        for (int i = 0; i <= kItemSections; ++i) w += ui::size_of(c.f.strong, tpx, i ? item_sections.s[i - 1].name : "All").x + tpad + tgap;
        return w - tgap;
    };
    if (tabs_w() > right - left) tpad = 16 * s, tgap = 6 * s;
    if (const float w = tabs_w(); w > right - left) {
        const float text = w - (kItemSections + 1) * tpad - kItemSections * tgap;
        tpx = std::max(12 * s, tpx * (right - left - (w - text)) / text);
    }
    float x = left, y = hh + 18 * s;
    for (int i = 0; i <= kItemSections; ++i) {
        const char* label = i ? item_sections.s[i - 1].name : "All";
        const float w = ui::size_of(c.f.strong, tpx, label).x + tpad;
        if (x > left && x + w > right) x = left, y += 36 * s;
        const ImVec2 a(x, y), b(std::min(x + w, right), y + 30 * s);
        const bool active = i == inventory_filter;
        ui::value_plate(c, a, b, active);
        ui::text_mid_centre(c, c.f.strong, tpx, (a.x + b.x) * .5f, y + 15 * s, active ? ui::kValueOnInk : ui::kInk, label);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kRow, i);
        x += w + tgap;
    }
    float top = y + 44 * s;
    const float pitch = (loaded ? 62 : 46) * s;   // (the title screen: the names alone, no line under them)
    if (!loaded) {   // (the title screen: one note for the page, not "Load a save" on every card)
        ui::diamond(c, ImVec2(left + 5 * s, top - 2 * s), 4 * s, ui::kGoldHi);
        ui::text_mid(c, c.f.body, 16 * s, left + 18 * s, top - 2 * s, ui::kSoft, "Load a save to edit the inventory.");
        top += 30 * s;
    }
    const float strip = 58 * s, detail = bar - 14 * s - strip, grid_bottom = std::max(top, detail - 8 * s);
    // ((Triforce) the card shows a change at once; the game makes it when it runs, as the name pages say of theirs)
    const char* help = have < 0 ? "Load a save to edit this item." : item_kinds[item_choice] ?
        "Choose Edit amount, then use Left and Right to change the quantity. The game takes a change when it runs." :
        "Unlock or relock this item. The game takes a change when it runs.";
    caption(c, hx0, hx1, item_names[item_choice], help, nullptr, nullptr);
    // (as many columns as fit the longest name, at most 5; whole pages of cards, the range and the page under them)
    static float name_w = 0, name_s = 0;
    if (name_s != s) {
        name_s = s, name_w = 0;
        for (int i = 0; i < kItems; ++i) name_w = std::max(name_w, ui::size_of(c.f.strong, 15.5f * s, item_names[i]).x);
    }
    inventory_columns = std::clamp((int)((right - left + gap) / std::max(name_w + 26 * s + gap, 150 * s)), 1, 5);
    inventory_capacity = inventory_columns * std::max(1, (int)((grid_bottom - top + gap) / pitch));
    const int pages_n = std::max(1, (end - begin + inventory_capacity - 1) / inventory_capacity);
    inventory_page = std::clamp(inventory_page, 0, pages_n - 1);
    const int first = begin + inventory_page * inventory_capacity;
    const float width = (right - left + gap) / inventory_columns;
    c.d->PushClipRect(ImVec2(left - 12 * s, top - 12 * s), ImVec2(right + 12 * s, grid_bottom + 12 * s));
    ImVec2 glow_a{}, glow_b{};   // ((Triforce, 11-18) the chosen one's cursor, drawn after every item: the next one's
    bool glow_have = false;     // plate covered part of it, which read as the highlight clipped)
    for (int i = first; i < std::min(end, first + inventory_capacity); ++i) {
        const int cell = i - first;
        const ImVec2 a(left + (cell % inventory_columns) * width, top + (cell / inventory_columns) * pitch);
        const ImVec2 b(a.x + width - gap, a.y + pitch - gap);
        const int count = debug_pending::shown(pending, i, item_counts[i].load(std::memory_order_relaxed));
        const bool selected = i == item_choice, owned = count > 0, editing = selected && inventory_amount;
        ui::plate(c, a, b, owned);
        c.d->PushClipRect(a + ImVec2(8 * s, 0), b - ImVec2(8 * s, 0), true);
        ui::text_mid(c, c.f.strong, 15.5f * s, a.x + 13 * s, loaded ? a.y + 17 * s : (a.y + b.y) * 0.5f, count < 0 ? ui::kDim : ui::kInkBright, item_names[i]);
        char amount[40];
        if (count < 0) snprintf(amount, sizeof amount, "%s", loaded ? "Unavailable" : "");
        else if (item_kinds[i]) snprintf(amount, sizeof amount, "Quantity %d", count);
        else snprintf(amount, sizeof amount, "%s", count ? "Unlocked" : "Locked");
        const float ly = a.y + 37 * s;
        if (editing) {   // (the amount being changed: its arrows, gold)
            ui::triangle(c, ImVec2(a.x + 18 * s, ly), 8 * s, 0, ui::kGoldHi);
            ui::text_mid(c, c.f.strong, 15 * s, a.x + 28 * s, ly, ui::kGoldHi, amount);
            ui::triangle(c, ImVec2(a.x + 38 * s + ui::size_of(c.f.strong, 15 * s, amount).x, ly), 8 * s, 1, ui::kGoldHi);
        } else {
            ui::text_mid(c, c.f.body, 15 * s, a.x + 13 * s, ly, owned ? ui::kAccent : kCardOff, amount);
        }
        c.d->PopClipRect();
        if (selected) glow_a = a, glow_b = b, glow_have = true;
        if (a.y < grid_bottom) hits.add(a.x, a.y, b.x, std::min(b.y, grid_bottom), menu_hit::kListLine, i);
    }
    if (glow_have) ui::glow(c, glow_a, glow_b);
    c.d->PopClipRect();
    if (detail >= top) {   // (the page: its arrows, Page n of m and the range; the selected item's action at the right)
        c.d->AddLine(ImVec2(left, detail), ImVec2(right, detail), ui::alpha(ui::kEdge, 0.8f));
        const int pages = (end - begin + inventory_capacity - 1) / inventory_capacity, at = (first - begin) / inventory_capacity;
        const float my = detail + strip * 0.5f + 2 * s, side = 32 * s;
        float px0 = left;
        if (pages > 1) {
            page_arrow(c, ImVec2(px0, my - side * 0.5f), side, 0, at > 0);
            hits.add(px0, my - side * 0.5f, px0 + side, my + side * 0.5f, menu_hit::kButton, 2);
            char page_text[32];
            snprintf(page_text, sizeof page_text, "Page %d of %d", at + 1, pages);
            const float tw = ui::size_of(c.f.strong, 17 * s, page_text).x;
            ui::text_mid(c, c.f.strong, 17 * s, px0 + side + 12 * s, my, ui::kInkBright, page_text);
            const float nx = px0 + side + 24 * s + tw;
            page_arrow(c, ImVec2(nx, my - side * 0.5f), side, 1, at + 1 < pages);
            hits.add(nx, my - side * 0.5f, nx + side, my + side * 0.5f, menu_hit::kButton, 3);
            px0 = nx + side + 18 * s;
        }
        char range[64];
        snprintf(range, sizeof range, "%d\xe2\x80\x93%d of %d", first - begin + 1, std::min(end, first + inventory_capacity) - begin, end - begin);
        ui::text_mid(c, c.f.body, 15 * s, px0, my, ui::kSoft, range);
        if (have >= 0) {
            const float bw = ui::size_of(c.f.strong, 18 * s, "Edit amount").x + 36 * s;
            const ImVec2 a(right - bw, my - 17 * s), b(right, my + 17 * s);
            ui::button(c, a, b, edit, false);
            hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 0);
            if (inventory_amount) {
                char amount[32];
                snprintf(amount, sizeof amount, "%d", have);
                const ImVec2 av(a.x - 118 * s, a.y), bv(a.x - 10 * s, b.y);
                choice_cell(c, av, bv, amount, true, true, true);
                hits.add(av.x, av.y, bv.x, bv.y, menu_hit::kButton, 1, av.x, bv.x);
            }
        }
    }
    ui::prompt_bar(c, prompts, prompts_n);   // (the prompts, on top of the help and the cards)
}

void draw_teleport(ui::Ctx& c) {
    const float s = c.s;
    char count[32];
    snprintf(count, sizeof count, "%d of %d", teleport_choice + 1, kTeleports);
    const float hh = title_banner(c, "Teleport", count);
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const ui::Prompt prompts[] = {{ui::kUpDown, "Move"}, {ui::kLeftRight, "Move"}, {ui::kTabs, "Section"},
        {ui::kConfirm, "Travel"}, {ui::kBack, "Back"}};
    const float bar = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    const float left = cx0 + 24 * s, right = cx1 - 24 * s, top = hh + 16 * s;
    const float strip = 58 * s, detail = bar - 14 * s - strip;
    const float bottom = std::max(top, detail - 6 * s), gap = 10 * s, pitch = 48 * s, head = 40 * s;
    const char* const note = teleport_notes[teleport_choice];
    caption(c, hx0, hx1, teleport_names[teleport_choice],
            "Select a destination, then Travel to go to its map entrance. Link keeps his current age.", note, nullptr);   // ((Triforce) no "Enter": the guides name the key, a controller's too)
    // (as many columns as fit the longest name and its tag, at most 4; each section under its heading, the cards scrolled to
    // keep the selected one in view)
    static float card_w = 0, card_s = 0;
    if (card_s != s) {
        card_s = s, card_w = 0;
        for (int i = 0; i < kTeleports; ++i)
            card_w = std::max(card_w, ui::size_of(c.f.body, 17 * s, teleport_names[i]).x +
                                          (teleport_notes[i] ? card_tag(c, 0, 0, teleport_notes[i], false) + 12 * s : 0));
    }
    teleport_columns = std::clamp((int)((right - left + gap) / (card_w + 36 * s + gap)), 1, 4);
    const int cols = teleport_columns;
    const float width = (right - left + gap) / cols;
    // (the y of each section's heading and first row, from the top of the list)
    float section_y[kTeleportSections + 1];
    float total = 0;
    for (int k = 0; k < kTeleportSections; ++k) {
        section_y[k] = total;
        const int n = teleport_section_end(k) - teleport_sections[k].first;
        total += head + (n + cols - 1) / cols * pitch + (k + 1 < kTeleportSections ? 10 * s : 0);
    }
    section_y[kTeleportSections] = total;
    auto card_y = [&](int i) {
        const int k = teleport_section_of(i);
        return section_y[k] + head + (i - teleport_sections[k].first) / cols * pitch;
    };
    const float view = bottom - top;
    teleport_page_rows = std::max(1, (int)(view / pitch) - 1);
    float& at = teleport_scroll_px;
    float& want = teleport_want_px;
    if (teleport_wheel) want -= teleport_wheel * pitch, teleport_wheel = 0;   // (the wheel: the cards move, the choice stays)
    if (total <= view) want = 0;
    else if (!teleport_follow) want = std::clamp(want, 0.0f, total - view);
    else {
        const int k = teleport_section_of(teleport_choice);
        const bool first_row = teleport_choice - teleport_sections[k].first < cols;
        const float y0 = first_row ? section_y[k] : card_y(teleport_choice) - pitch * 0.5f, y1 = card_y(teleport_choice) + pitch * 1.5f;
        if (y0 < want) want = y0;
        if (y1 > want + view) want = y1 - view;
        want = std::clamp(want, 0.0f, total - view);
    }
    at += (want - at) * ease_step;
    if (std::fabs(want - at) < 0.5f) at = want;
    if (total > view) scroll_bar(c, cx0 + 12 * s, top, bottom, (int)total, (int)view, at);
    c.d->PushClipRect(ImVec2(left - 12 * s, top), ImVec2(right + 12 * s, bottom), true);
    for (int k = 0; k < kTeleportSections; ++k) {
        const float hy = top + section_y[k] - at + head * 0.5f;
        if (hy > bottom + head || hy < top - head) continue;
        ui::text_mid(c, c.f.heading, 20 * s, left, hy, ui::kInkBright, teleport_sections[k].name);
        const float tw = ui::size_of(c.f.heading, 20 * s, teleport_sections[k].name).x;
        char n_text[16];
        snprintf(n_text, sizeof n_text, "%d", teleport_section_end(k) - teleport_sections[k].first);
        const float nw = ui::size_of(c.f.body, 15 * s, n_text).x;
        ui::text_mid(c, c.f.body, 15 * s, right - nw, hy, ui::kSoft, n_text);
        c.d->AddLine(ImVec2(left + tw + 14 * s, hy + s), ImVec2(right - nw - 12 * s, hy + s), ui::alpha(ui::kAccent, 0.45f),
                     std::max(1.0f, s));
    }
    ImVec2 glow_a{}, glow_b{};   // ((Triforce, 11-18) the chosen one's cursor, drawn after every item: the next one's
    bool glow_have = false;     // plate covered part of it, which read as the highlight clipped)
    for (int i = 0; i < kTeleports; ++i) {
        const int k = teleport_section_of(i), cell = i - teleport_sections[k].first;
        const ImVec2 a(left + cell % cols * width, top + card_y(i) - at);
        const ImVec2 b(a.x + width - gap, a.y + pitch - 8 * s);
        if (b.y < top || a.y > bottom) continue;
        const bool selected = i == teleport_choice;
        ui::plate(c, a, b, selected);
        float name_end = b.x - 10 * s;
        if (teleport_notes[i]) name_end -= card_tag(c, b.x - 8 * s, (a.y + b.y) * 0.5f, teleport_notes[i]) + 8 * s;
        c.d->PushClipRect(a, ImVec2(name_end, b.y), true);
        ui::text_mid(c, c.f.body, 17 * s, a.x + 16 * s, (a.y + b.y) * 0.5f, ui::kInk, teleport_names[i]);
        c.d->PopClipRect();
        if (selected) glow_a = a, glow_b = b, glow_have = true;
        hits.add(a.x, std::max(a.y, top), b.x, std::min(b.y, bottom), menu_hit::kListLine, i);
    }
    if (glow_have) ui::glow(c, glow_a, glow_b);
    c.d->PopClipRect();
    if (detail >= top) {   // (the selection, its section and note, and Travel: what Enter does)
        c.d->AddLine(ImVec2(left, detail), ImVec2(right, detail), ui::alpha(ui::kEdge, 0.8f));
        const float my = detail + strip * 0.5f + 2 * s;
        const float bw = ui::size_of(c.f.strong, 20 * s, "Travel").x + 56 * s;
        const ImVec2 a(right - bw, my - 18 * s), b(right, my + 18 * s);
        c.d->PushClipRect(ImVec2(left, detail), ImVec2(a.x - 12 * s, detail + strip), true);
        ui::text_mid(c, c.f.strong, 18 * s, left, my - 10 * s, ui::kInkBright, teleport_names[teleport_choice]);
        char where[64];
        snprintf(where, sizeof where, note ? "%s \xc2\xb7 %s" : "%s", teleport_sections[teleport_section_of(teleport_choice)].name, note);
        ui::text_mid(c, c.f.body, 15 * s, left, my + 12 * s, ui::kAccent, where);
        c.d->PopClipRect();
        ui::button(c, a, b, "Travel", false);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 0);
    }
    ui::prompt_bar(c, prompts, 5);   // (the prompts, on top of the help and the cards)
}

/// (Triforce) A name page (Game flags, Cutscenes, Scan amiibo): the group shown as a choice across the top (L and R, or a
/// click on its arrows), the group's names as cards in whole pages, and under them the page's arrows, the range and the
/// chosen name's action; the caption has the chosen name whole, what it is and what the game's side last said
void draw_names(ui::Ctx& c) {
    const float s = c.s;
    dn::Page& p = names_page[names_kind];
    const bool flags = names_kind == kNamesFlags, events = names_kind == kNamesEvents;
    static const char* const titles[kNamesKinds] = {"Game flags", "Cutscenes", "Scan amiibo"};   // ((Triforce) as their rows say)
    char count_text[48];
    snprintf(count_text, sizeof count_text, flags ? "%d flags" : events ? "%d events" : "%d files", (int)p.list.names.size());
    const float hh = title_banner(c, titles[names_kind], p.empty() ? nullptr : count_text);
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const float bar = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    const float left = cx0 + 24 * s, right = cx1 - 24 * s, gap = 10 * s;
    const float y = hh + 18 * s, top = y + 50 * s, pitch = (flags ? 62 : 46) * s;   // (a flag's card: its state under its name)
    const float strip = 58 * s, detail = bar - 14 * s - strip, grid_bottom = std::max(top, detail - 8 * s);
    // (as many columns as fit, at most 3: the names are long; whole pages of cards, never more than a W line's flags)
    p.columns = std::clamp((int)((right - left + gap) / (340 * s + gap)), 1, 3);
    p.capacity = std::min(p.columns * std::max(1, (int)((grid_bottom - top + gap) / pitch)), (int)OOT_WATCH_MAX);
    p.shown = std::clamp(p.shown, 0, p.pages() - 1);
    // (what the game's side last said, while the chosen name is the one it said it of: under another name it would read as
    // that name's. A flag's or an event's line, or what became of the figure whose file was sent)
    std::string status;
    std::string states;   // (the shown flags' states, a character each from p.first())
    char state = '?';     // (the chosen flag's)
    const int figure = amiibo_said.load(std::memory_order_relaxed);
    {
        std::lock_guard lk(names_mu);
        if (flags) {
            for (int i = p.first(); i < p.last(); ++i) states += names_states.of(p.list.hashes[i]);
            if (!p.empty()) state = names_states.of(p.list.hashes[p.choice]);
        }
        if (!p.empty() && names_kind == names_status_kind && names_status_of == p.list.names[p.choice]) status = names_status;
    }
    if (!p.empty() && names_kind == kNamesAmiibo && amiibo_chosen == p.list.names[p.choice])
        if (const char* text = amiibo_text(figure, false)) status = text;
    if (p.empty()) {   // (no names yet, or none at all: one note for the page)
        const int scan = names_scan.load(std::memory_order_acquire);
        const char* note = names_kind == kNamesAmiibo ? "No dumps yet. Put .bin dumps of your own figures into the folder \"amiibo\" in the game folder."
                           : scan == 3 ? "The game's files were not found." : scan == 2 ? "Your game files name none." : "Reading the names from your game files...";
        ui::diamond(c, ImVec2(left + 5 * s, hh + 34 * s), 4 * s, ui::kGoldHi);
        ui::para(c, c.f.body, 16 * s, ImVec2(left + 18 * s, hh + 24 * s), ui::kSoft, note, right - left - 18 * s);
        caption(c, hx0, hx1, titles[names_kind], names_help(names_kind), nullptr, nullptr);
        const ui::Prompt back[] = {{ui::kBack, "Back"}};
        ui::prompt_bar(c, back, 1);
        return;
    }
    const std::string& chosen = p.list.names[p.choice];
    const bool figure_waits = names_kind == kNamesAmiibo && amiibo_chosen == chosen && (figure == HOS_AMIIBO_WAITING || figure == HOS_AMIIBO_ON_READER);
    const char* action = flags ? (names_edit ? "Done" : "Change") : events ? "Start" : figure_waits ? "Take away" : "Scan";
    const int groups = (int)p.list.groups.size();
    // (the guides say what the keys do here: Up and Down nothing while a flag's On and Off are chosen, L and R nothing with one
    // group)
    ui::Prompt prompts[5];
    int prompts_n = 0;
    if (!names_edit) prompts[prompts_n++] = {ui::kUpDown, "Move"};
    prompts[prompts_n++] = {ui::kLeftRight, names_edit ? "On / Off" : "Move"};
    if (groups > 1) prompts[prompts_n++] = {ui::kTabs, "Group"};
    prompts[prompts_n++] = {ui::kConfirm, action};
    prompts[prompts_n++] = {ui::kBack, names_edit ? "Done" : "Back"};
    // the group shown: a choice with its arrows, the group's place among them at its right
    const dn::Group& group = p.list.groups[p.group];
    {
        char label[160], place[32];
        snprintf(label, sizeof label, "%s (%d)", group.title.c_str(), group.count);
        const ImVec2 a(left, y), b(std::min(right, left + 560 * s), y + 36 * s);
        choice_cell(c, a, b, label, false, groups > 1, groups > 1);
        if (groups > 1) {
            hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 4, a.x, b.x);
            snprintf(place, sizeof place, "Group %d of %d", p.group + 1, groups);
            if (b.x + 16 * s + ui::size_of(c.f.body, 15 * s, place).x <= right) ui::text_mid(c, c.f.body, 15 * s, b.x + 16 * s, y + 18 * s, ui::kSoft, place);
        }
    }
    {   // the caption: what the page is, the chosen name whole (a long one takes lines), what it is now, and the last answer
        std::string about = chosen;
        if (flags) about += state == '1' ? "\nSet in this save." : state == '0' ? "\nNot set in this save." : state == '-' ? "\nThis save's data has no such flag." :
                            "\nNot known now: no save is loaded, or the game is paused.";
        // (the last answer: the line at the caption's foot when it fits that one line, else with the text above it, which takes
        // lines: a line cut off at the plate's edge said half of "the file is not a figure's dump")
        const float line_w = hx1 - hx0 - 2 * ui::lu(c, 72) - 20 * s;
        const bool one_line = !status.empty() && ui::size_of(c.f.strong, kHintPt * s, status.c_str()).x <= line_w;
        if (!status.empty() && !one_line) about += "\n" + status;
        caption(c, hx0, hx1, titles[names_kind], names_help(names_kind), about.c_str(), one_line ? status.c_str() : nullptr);
    }
    const int first = p.first(), last = p.last();
    const float width = (right - left + gap) / p.columns;
    c.d->PushClipRect(ImVec2(left - 12 * s, top - 12 * s), ImVec2(right + 12 * s, grid_bottom + 12 * s));
    ImVec2 glow_a{}, glow_b{};   // ((Triforce, 11-18) the chosen one's cursor, drawn after every item: the next one's
    bool glow_have = false;     // plate covered part of it, which read as the highlight clipped)
    for (int i = first; i < last; ++i) {
        const int cell = i - first;
        const ImVec2 a(left + (cell % p.columns) * width, top + (cell / p.columns) * pitch);
        const ImVec2 b(a.x + width - gap, a.y + pitch - gap);
        const char st = flags && cell < (int)states.size() ? states[cell] : '?';
        const bool selected = i == p.choice;
        const bool sent = names_kind == kNamesAmiibo && amiibo_chosen == p.list.names[i];   // (the file the figure is of)
        // (the figure's card says where the figure is, whichever card is chosen: a tag at its right end, as the Teleport's, and
        // lit while it has one. (Triforce) Not lit for a file the game refused or could not read: that read as the one in use)
        const char* tag = !sent ? nullptr : figure == HOS_AMIIBO_WAITING ? "waiting" : figure == HOS_AMIIBO_ON_READER ? "on the reader" :
                          figure == HOS_AMIIBO_READ ? "read" : nullptr;
        ui::plate(c, a, b, flags ? st == '1' : tag != nullptr);
        float name_end = b.x - 13 * s;
        if (tag) name_end -= card_tag(c, b.x - 8 * s, (a.y + b.y) * 0.5f, tag) + 8 * s;
        c.d->PushClipRect(a + ImVec2(8 * s, 0), ImVec2(name_end, b.y), true);
        // (the name without what its group is named for, and cut in its middle when it is still too long: the names of a group
        // begin alike and differ at their ends, which a cut at the end left out; the caption has the chosen one whole)
        const float room = name_end - (a.x + 13 * s);
        const std::string name = dn::elide_middle(dn::card_label(p.list, p.group, i),
                                                  [&](const std::string& t) { return ui::size_of(c.f.strong, 15.5f * s, t.c_str()).x <= room; });
        ui::text_mid(c, c.f.strong, 15.5f * s, a.x + 13 * s, flags ? a.y + 17 * s : (a.y + b.y) * 0.5f, ui::kInkBright, name.c_str());
        if (flags)   // (the state is what the page is for: legible when it is not Set too; kDim on a plate could not be read)
            ui::text_mid(c, c.f.body, 15 * s, a.x + 13 * s, a.y + 37 * s, st == '1' ? ui::kAccent : st == '0' ? ui::kSoft : kCardOff,
                         st == '1' ? "Set" : st == '0' ? "Not set" : st == '-' ? "Not in this save" : "Not known");
        c.d->PopClipRect();
        if (selected) glow_a = a, glow_b = b, glow_have = true;
        if (a.y < grid_bottom) hits.add(a.x, a.y, b.x, std::min(b.y, grid_bottom), menu_hit::kListLine, i);
    }
    if (glow_have) ui::glow(c, glow_a, glow_b);
    c.d->PopClipRect();
    if (detail >= top) {   // (the page: its arrows, Page n of m and the range; the chosen name's action at the right)
        c.d->AddLine(ImVec2(left, detail), ImVec2(right, detail), ui::alpha(ui::kEdge, 0.8f));
        const int pages = p.pages(), at = (first - p.begin()) / std::max(1, p.capacity);
        const float my = detail + strip * 0.5f + 2 * s, side = 32 * s;
        float px0 = left;
        if (pages > 1) {
            page_arrow(c, ImVec2(px0, my - side * 0.5f), side, 0, at > 0);
            hits.add(px0, my - side * 0.5f, px0 + side, my + side * 0.5f, menu_hit::kButton, 2);
            char page_text[32];
            snprintf(page_text, sizeof page_text, "Page %d of %d", at + 1, pages);
            const float tw = ui::size_of(c.f.strong, 17 * s, page_text).x;
            ui::text_mid(c, c.f.strong, 17 * s, px0 + side + 12 * s, my, ui::kInkBright, page_text);
            const float nx = px0 + side + 24 * s + tw;
            page_arrow(c, ImVec2(nx, my - side * 0.5f), side, 1, at + 1 < pages);
            hits.add(nx, my - side * 0.5f, nx + side, my + side * 0.5f, menu_hit::kButton, 3);
            px0 = nx + side + 18 * s;
        }
        char range[64];
        snprintf(range, sizeof range, "%d\xe2\x80\x93%d of %d", first - p.begin() + 1, last - p.begin(), p.end() - p.begin());   // ((Triforce) as the Inventory's)
        ui::text_mid(c, c.f.body, 15 * s, px0, my, ui::kSoft, range);
        const float bw = ui::size_of(c.f.strong, 18 * s, "Take away").x + 36 * s;
        const ImVec2 a(right - bw, my - 17 * s), b(right, my + 17 * s);
        ui::button(c, a, b, action, false);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 0);
        if (names_edit) {   // (a flag's two halves: On at the left, Off at the right, the one it is lit when that is known)
            const ImVec2 av(a.x - 190 * s, a.y), bv(a.x - 10 * s, b.y);
            const float xm = av.x + (bv.x - av.x) * 0.632f;   // (where halves_cell's two halves meet)
            if (state == '1' || state == '0') {
                halves_cell(c, av, bv, "On", "Off", state == '0', true, false);
            } else {   // (not known which it is: neither half lit, and neither dim, for both can be had; dim halves read as "cannot".
                       // (Triforce) The save has no such flag ('-'): neither lit, both dim, for neither can be had)
                const float mid = (av.y + bv.y) * 0.5f, px = std::min(ui::lu(c, 54 * ui::kType), (bv.y - av.y) * 0.62f);
                const ImU32 ink = state == '-' ? ui::kDim : ui::kInk;
                ui::value_plate(c, av, bv);
                ui::text_mid_centre(c, c.f.body, px, (av.x + xm) * 0.5f, mid - ui::lu(c, 2), ink, "On");
                ui::text_mid_centre(c, c.f.body, px, (xm + bv.x) * 0.5f, mid - ui::lu(c, 2), ink, "Off");
                c.d->AddLine(ImVec2(xm, av.y + 8 * s), ImVec2(xm, bv.y - 8 * s), ui::alpha(ui::kEdge, 0.9f), std::max(1.0f, s));
                ui::cursor(c, av - ImVec2(ui::lu(c, 2.5f), ui::lu(c, 3)), bv + ImVec2(ui::lu(c, 2.5f), ui::lu(c, 3)));
            }
            hits.add(av.x, av.y, xm, bv.y, menu_hit::kButton, 1, 0, 0, 0, 0, -1);
            hits.add(xm, av.y, bv.x, bv.y, menu_hit::kButton, 1, 0, 0, 0, 0, 1);
        }
    }
    ui::prompt_bar(c, prompts, prompts_n);   // (the prompts, on top of the help and the cards)
}

// ---- (Triforce) the Mods page: GameBanana's mods for this game (vk_mods.h) ----

std::string mods_size(uint64_t b) {
    char t[32];
    if (b >= (1ull << 30)) snprintf(t, sizeof t, "%.1f GB", b / (double)(1ull << 30));
    else if (b >= (1ull << 20)) snprintf(t, sizeof t, "%.1f MB", b / (double)(1ull << 20));
    else snprintf(t, sizeof t, "%.0f KB", b / 1024.0);
    return t;
}
std::string mods_count(int n) {   // ("3,638")
    std::string t = std::to_string(n);
    for (int i = (int)t.size() - 3; i > 0; i -= 3) t.insert((size_t)i, ",");
    return t;
}
/// (Triforce, 11-17) A texture let go: the backend frees it while it is still registered (ImGui hands it the texture list of
/// the registered ones only), so it is unregistered and deleted once it is Destroyed, by textures_reap. Unregistered at once,
/// its image and descriptor set were never freed: the Mods screen's pictures used up the overlays' pool that way
std::vector<ImTextureData*> textures_retiring;
void texture_retire(ImTextureData* t) {
    if (!t) return;
    // (WantDestroyNextFrame too: ImGui's SetStatus(Destroyed) makes a texture that still has its pixels WantCreate again
    // unless it is set, and the backend's destroy is then a re-creation, every frame)
    t->WantDestroyNextFrame = true;
    t->SetStatus(ImTextureStatus_WantDestroy);
    textures_retiring.push_back(t);
    static int let_go = 0;
    if (++let_go % 50 == 1) logf("menu: %d pictures let go so far (far out of view, or resized)", let_go);
}
void textures_reap() {
    for (size_t i = 0; i < textures_retiring.size();) {
        ImTextureData* t = textures_retiring[i];
        if (t->Status != ImTextureStatus_Destroyed) { i++; continue; }
        ImGui::UnregisterUserTexture(t);
        IM_DELETE(t);
        textures_retiring[i] = textures_retiring.back(), textures_retiring.pop_back();
    }
}
/// A mod's picture over a..b, cut to the box's shape (its middle kept); its texture made from the pixels once they came
void mods_picture(ui::Ctx& c, mods::Mod& m, ImVec2 a, ImVec2 b, int* made) {
    if (!m.texture && m.thumb_state == 2 && !m.thumb_rgba.empty() && *made < 3) {   // (a few a frame: no hitch while scrolling)
        ImTextureData* t = IM_NEW(ImTextureData)();
        t->Create(ImTextureFormat_RGBA32, m.thumb_w, m.thumb_h);
        memcpy(t->GetPixels(), m.thumb_rgba.data(), m.thumb_rgba.size());
        t->UseColors = true;
        ImGui::RegisterUserTexture(t);
        m.texture = t;
        m.thumb_rgba.clear(), m.thumb_rgba.shrink_to_fit();
        (*made)++;
    }
    c.d->AddRectFilled(a, b, ui::rgba(18, 13, 8, 255));
    if (ImTextureData* t = (ImTextureData*)m.texture) {
        const float bw = b.x - a.x, bh = b.y - a.y, iw = (float)m.thumb_w, ih = (float)m.thumb_h;
        ImVec2 uv0(0, 0), uv1(1, 1);
        if (iw / ih > bw / bh) { const float k = (bh / bw) * iw / ih; uv0.x = (1 - 1 / k) * 0.5f, uv1.x = 1 - uv0.x; }   // (wider: its sides cut)
        else { const float k = (bw / bh) * ih / iw; uv0.y = (1 - 1 / k) * 0.5f, uv1.y = 1 - uv0.y; }                     // (taller: top and foot cut)
        c.d->AddImage(t->GetTexRef(), a, b, uv0, uv1);
    } else {
        const char* what = m.thumb_state == 3 ? "No picture" : "...";
        ui::text_mid_centre(c, c.f.body, 13 * c.s, (a.x + b.x) * 0.5f, (a.y + b.y) * 0.5f, ui::kDim, what);
    }
    c.d->AddRect(a, b, ui::alpha(ui::kEdge, 0.9f), 0, std::max(1.0f, c.s));
}

/// A dialog over the page: the game's caption plate in the middle, its title, its text, and up to two buttons (the upper one
/// first); the progress bar between them when frac >= 0
void mods_dialog(ui::Ctx& c, const char* title, const std::string& text, const char* const* labels, int n, float frac = -1,
                 const char* bar_left = nullptr, const char* bar_right = nullptr) {
    const float s = c.s;
    dim_page(c, ui::rgba(8, 5, 2, 120));
    const float w = ui::lu(c, 1500), pad = ui::lu(c, 80), px = kHelpPt * s;
    const float th = ui::para(c, c.f.body, px, ImVec2(), 0, text.c_str(), w - 2 * pad, false);
    const float bar_h = frac >= 0 ? 74 * s : 0, btn_h = ui::lu(c, 144), btns = n ? n * (btn_h + ui::lu(c, 44)) : 0;
    const float tall = pad + 34 * s + th + 18 * s + bar_h + btns + pad * 0.6f;
    const ImVec2 a(c.w * 0.5f - w * 0.5f, std::max(banner_h(c) + 20 * s, c.h * 0.5f - tall * 0.5f)), b(a.x + w, a.y + tall);
    ui::box(c, a, b);
    float y = a.y + pad * 0.7f;
    ui::text_mid_centre(c, c.f.strong, 21.6f * s, c.w * 0.5f, y + 10 * s, ui::kInk, title);
    y += 34 * s;
    {   // (each line centred, as the game's dialogs set their text)
        const char* t = text.c_str();
        const char* end = t + text.size();
        while (t < end) {
            const char* nl = (const char*)memchr(t, '\n', (size_t)(end - t));
            const char* line_end = nl ? nl : end;
            const char* cut = c.f.body->CalcWordWrapPosition(px, t, line_end, w - 2 * pad);
            if (cut == t) cut = t + 1;
            const float lw = c.f.body->CalcTextSizeA(px, FLT_MAX, 0, t, cut).x;
            c.d->AddText(c.f.body, px, ImVec2(c.w * 0.5f - lw * 0.5f, y), ui::kSoft, t, cut);
            y += px * 1.3f;
            t = cut;
            while (t < end && (*t == ' ' || *t == '\n')) t++;
        }
    }
    y += 18 * s;
    if (frac >= 0) {   // (the bar: the game's value channel, filled in gold as the HUD's magic, the numbers over it)
        const float bx0 = a.x + pad, bx1 = b.x - pad, by = y + 30 * s;
        if (bar_left) ui::text_mid(c, c.f.body, 15 * s, bx0, y + 8 * s, ui::kSoft, bar_left);
        if (bar_right) ui::text_mid_right(c, c.f.body, 15 * s, bx1, y + 8 * s, ui::kSoft, bar_right);
        ui::value_plate(c, ImVec2(bx0, by), ImVec2(bx1, by + 20 * s));
        const float fx = bx0 + 3 * s + (bx1 - bx0 - 6 * s) * std::clamp(frac, 0.0f, 1.0f);
        if (fx > bx0 + 3 * s) {
            c.d->AddRectFilledMultiColor(ImVec2(bx0 + 3 * s, by + 3 * s), ImVec2(fx, by + 17 * s), ui::rgba(170, 236, 120), ui::rgba(170, 236, 120),
                                         ui::rgba(52, 160, 52), ui::rgba(52, 160, 52));
            c.d->AddRectFilled(ImVec2(bx0 + 3 * s, by + 4 * s), ImVec2(fx, by + 7 * s), ui::rgba(255, 255, 255, 80));
        }
        y += bar_h;
    }
    const float bw = ui::lu(c, 336);
    for (int i = 0; i < n; i++) {
        const float my = y + btn_h * 0.5f + i * (btn_h + ui::lu(c, 44));
        const ImVec2 ba(c.w * 0.5f - bw, my - btn_h * 0.5f), bb(c.w * 0.5f + bw, my + btn_h * 0.5f);
        ui::button(c, ba, bb, labels[i], i == mods_btn);
        hits.add(ba.x, ba.y, bb.x, bb.y, menu_hit::kButton, i);
    }
}

// (the Salesman: his newest picture from his thread (vk_salesman.h), as a texture updated in place)
ImTextureData* salesman_tex = nullptr;
uint64_t salesman_seq = 0;
int salesman_w = 0, salesman_h = 0;   // (the size his corner has on screen, pixels: what his thread draws for)
bool salesman_said_hello = false;     // (a smile the first time the page shows each run)
int64_t salesman_line_at = 0;
int salesman_line = 0;
const char* const salesman_lines[] = {
    "Oh! A customer with taste... Every one of these has a story.",
    "Take your time. I have all the time in the world.",
    "Each of these was made by someone's own hands. Mostly.",
    "That one... yes. That one would suit you.",
    "A new face for an old friend. How delightful.",
};
void salesman_picture(ui::Ctx& c, ImVec2 a, ImVec2 b) {
    salesman_w = (int)(b.x - a.x), salesman_h = (int)(b.y - a.y);
    static std::vector<unsigned char> buf;
    int w = 0, h = 0;
    if (salesman::take(buf, &w, &h, &salesman_seq)) {
        if (salesman_tex && (salesman_tex->Width != w || salesman_tex->Height != h)) {   // (a new size: a new texture)
            texture_retire(salesman_tex);
            salesman_tex = nullptr;
        }
        if (!salesman_tex) {
            salesman_tex = IM_NEW(ImTextureData)();
            salesman_tex->Create(ImTextureFormat_RGBA32, w, h);
            salesman_tex->UseColors = true;
            memcpy(salesman_tex->GetPixels(), buf.data(), buf.size());
            ImGui::RegisterUserTexture(salesman_tex);
        } else if (salesman_tex->Status == ImTextureStatus_OK) {   // (the last copy done: this one in its place)
            memcpy(salesman_tex->GetPixels(), buf.data(), buf.size());
            const ImTextureRect r{0, 0, (unsigned short)w, (unsigned short)h};
            salesman_tex->Updates.resize(0);
            salesman_tex->Updates.push_back(r);
            salesman_tex->UpdateRect = r;
            salesman_tex->SetStatus(ImTextureStatus_WantUpdates);
        }
    }
    if (salesman_tex && salesman_tex->Width > 0) {   // (his picture's own shape, at the foot of his corner)
        const float k = std::min((b.x - a.x) / salesman_tex->Width, (b.y - a.y) / salesman_tex->Height);
        const float pw = salesman_tex->Width * k, ph = salesman_tex->Height * k;
        const ImVec2 pa((a.x + b.x - pw) * 0.5f, b.y - ph);
        c.d->AddImage(salesman_tex->GetTexRef(), pa, pa + ImVec2(pw, ph));
    }
}
/// What he says, in a box at the foot of his corner: the game's caption plate, his name over it
void salesman_says(ui::Ctx& c, float x0, float x1, float y1, const char* line) {
    const float s = c.s, pad = 12 * s, px = 15 * s, w = x1 - x0;
    const float th = ui::para(c, c.f.body, px, ImVec2(), 0, line, w - 2 * pad, false);
    const ImVec2 a(x0, y1 - th - 2 * pad - 6 * s), b(x1, y1);
    ui::box(c, a, b);
    ui::text_mid(c, c.f.strong, 13 * s, a.x + pad, a.y - 2 * s, ui::kAccent, "Happy Mask Salesman");
    ui::para(c, c.f.body, px, ImVec2(a.x + pad, a.y + pad + 3 * s), ui::kInk, line, w - 2 * pad);
}

/// ((Triforce) 11-17) The search's text in a..b at px, its end kept in view when it is longer; a caret after it while sel
void mods_query_text(ui::Ctx& c, ImVec2 a, ImVec2 b, float px, bool sel, const char* empty_hint) {
    const float my = (a.y + b.y) * 0.5f, room = b.x - a.x;
    // ((Triforce, 11-18) the clip keeps the caret's whole line: drawn on the clip's first pixel, half of it was cut, which
    // read as the highlight clipped (the hint starts clear of it too))
    c.d->PushClipRect(ImVec2(a.x - 2 * c.s, a.y), ImVec2(b.x + 2 * c.s, b.y), true);
    const float caret_x = a.x + 1.5f * c.s;
    if (mods_query.empty()) {
        ui::text_mid(c, c.f.body, px * 0.92f, sel ? caret_x + 7 * c.s : a.x, my, ui::alpha(ui::kSoft, 0.55f), empty_hint);
        if (sel && (prof_now() / 500000000LL) % 2 == 0)
            c.d->AddLine(ImVec2(caret_x, my - px * 0.55f), ImVec2(caret_x, my + px * 0.55f), ui::kInk, std::max(1.5f, 1.6f * c.s));
    } else {
        const float w = ui::size_of(c.f.body, px, mods_query.c_str()).x;
        const float x = w + 6 * c.s > room ? b.x - w - 6 * c.s : a.x;
        ui::text_mid(c, c.f.body, px, x, my, ui::kInkBright, mods_query.c_str());
        if (sel && (prof_now() / 500000000LL) % 2 == 0)
            c.d->AddLine(ImVec2(x + w + 2 * c.s, my - px * 0.55f), ImVec2(x + w + 2 * c.s, my + px * 0.55f), ui::kInk, std::max(1.5f, 1.6f * c.s));
    }
    c.d->PopClipRect();
}

/// ((Triforce) 11-17) The search bar over the cards: a plate as the cards have, a magnifying glass, the text typed or what to
/// do, a caret while it is chosen; at its right what the search found
void mods_search_bar(ui::Ctx& c, ImVec2 a, ImVec2 b, const std::string& searched, mods::Feed feed, int n, bool more) {
    const float s = c.s, my = (a.y + b.y) * 0.5f;
    const bool sel = mods_choice < 0 || mods_kbd;
    ui::plate(c, a, b, sel);
    const ImVec2 g(a.x + 25 * s, my - 2.5f * s);   // (the glass)
    c.d->AddCircle(g, 8.5f * s, ui::kSoft, 24, 2.2f * s);
    c.d->AddLine(g + ImVec2(6 * s, 6 * s), g + ImVec2(12.5f * s, 12.5f * s), ui::kSoft, 3 * s);
    std::string found;
    if (!searched.empty()) {
        if (feed == mods::Feed::Failed) found = "Not reached";
        else if (feed == mods::Feed::Loading && !n) found = "Searching...";
        else found = (n == 1 ? std::string("1 found") : std::to_string(n) + (more ? "+ found" : " found"));
    }
    // ((Triforce, 11-18) the count capped at two fifths of the bar, so the field keeps its room)
    const float found_max = std::max(0.0f, (b.x - a.x) * 0.4f);
    std::string found_fit;
    const float found_w = found.empty() ? 0 : ui::fit_text(found.c_str(), c.f.body, 15 * s, found_max, &found_fit) + 16 * s;
    if (!found_fit.empty()) ui::text_mid_right(c, c.f.body, 15 * s, b.x - 14 * s, my, ui::kAccent, found_fit.c_str());
    mods_query_text(c, ImVec2(a.x + 46 * s, a.y), ImVec2(b.x - 14 * s - found_w, b.y), 18 * s, sel && !mods_kbd,
                    sel ? "Type to search, or press Confirm for a keyboard" : "Search mods");
    if (sel && !mods_kbd) ui::glow(c, a, b);
    hits.add(a.x, a.y, b.x, b.y, menu_hit::kSearch, 0);
}

/// ((Triforce) 11-17) The keyboard for a controller: a box over the page as the game's dialogs have, the text at its top, four
/// rows of ten keys (the letters shown capital, typed small) and a row of four wide keys; the chosen one lit as the game's
/// chosen value is, the cursor round it. A click types a key too (kKey)
void mods_keyboard(ui::Ctx& c) {
    const float s = c.s, kw = 62 * s, kh = 50 * s, gap = 7 * s, pad = 24 * s, field_h = 52 * s;
    const float w = 10 * kw + 9 * gap + 2 * pad, h = pad + field_h + 16 * s + 5 * kh + 4 * gap + pad;
    dim_page(c, ui::rgba(8, 5, 2, 120));   // (the page behind it darker)
    const float x0 = std::floor((c.w - w) * 0.5f), y0 = std::max(banner_h(c) + 8 * s, ui::prompt_bar_top(c) - h - 16 * s);
    ui::box(c, ImVec2(x0, y0), ImVec2(x0 + w, y0 + h));
    mods_kbd_box[0] = x0, mods_kbd_box[1] = y0, mods_kbd_box[2] = x0 + w, mods_kbd_box[3] = y0 + h;
    const ImVec2 fa(x0 + pad, y0 + pad), fb(x0 + w - pad, y0 + pad + field_h);
    ui::value_plate(c, fa, fb, false);
    mods_query_text(c, ImVec2(fa.x + 14 * s, fa.y), ImVec2(fb.x - 14 * s, fb.y), 20 * s, true, "Type a word to search for");
    const float ky = fb.y + 16 * s;
    ImVec2 glow_a{}, glow_b{};   // ((Triforce, 11-18) the chosen one's cursor, drawn after every item: the next one's
    bool glow_have = false;     // plate covered part of it, which read as the highlight clipped)
    for (int row = 0; row < 5; row++) {
        const int keys = row < 4 ? 10 : 4;
        for (int k = 0; k < keys; k++) {
            const int col0 = row < 4 ? k : kKbdWideAt[k], col1 = row < 4 ? k + 1 : kKbdWideAt[k + 1];
            const ImVec2 ka(x0 + pad + col0 * (kw + gap), ky + row * (kh + gap));
            const ImVec2 kb(x0 + pad + col1 * (kw + gap) - gap, ka.y + kh);
            const bool on = row == mods_kbd_row && (row < 4 ? k == mods_kbd_col : k == kbd_wide(mods_kbd_col));
            ui::value_plate(c, ka, kb, on);
            char label[2] = {row < 4 ? (char)toupper((unsigned char)kKbdRows[row][k]) : 0, 0};
            const char* t = row < 4 ? label : kKbdWide[k];
            const ImU32 ink = on ? ui::kValueOnInk : row == 4 && k == 3 ? ui::kGoldHi : ui::kInk;
            ui::text_mid_centre(c, row < 4 ? c.f.strong : c.f.body, (row < 4 ? 21 : 17) * s, (ka.x + kb.x) * 0.5f, (ka.y + kb.y) * 0.5f, ink, t);
            if (on) glow_a = ka, glow_b = kb, glow_have = true;
            hits.add(ka.x, ka.y, kb.x, kb.y, menu_hit::kKey, row * 10 + col0);
        }
    }
    if (glow_have) {
        // ((Triforce, 11-18) his "the highlight left and right inside showing black bars": the cursor's opening stands a
        // few units off the key's plate and the dark box showed between them. The chosen key's own plate is drawn a
        // little larger under the cursor, its letter with it, so the gold runs to the frame on every side)
        const float g = ui::lu(c, 13);
        ui::value_plate(c, ImVec2(glow_a.x - g, glow_a.y - g), ImVec2(glow_b.x + g, glow_b.y + g), true);
        const int row = mods_kbd_row, col = mods_kbd_col;
        char label[2] = {row < 4 ? (char)toupper((unsigned char)kKbdRows[row][col]) : 0, 0};
        const char* t = row < 4 ? label : kKbdWide[kbd_wide(col)];
        ui::text_mid_centre(c, row < 4 ? c.f.strong : c.f.body, (row < 4 ? 21 : 17) * s,
                            (glow_a.x + glow_b.x) * 0.5f, (glow_a.y + glow_b.y) * 0.5f, ui::kValueOnInk, t);
        ui::glow(c, glow_a, glow_b);
    }
}

void draw_mods(ui::Ctx& c) {
    const float s = c.s, hh = banner_h(c);
    ui::banner(c, hh);
    title_banner(c, "Mods", nullptr);   // (its own screen: opened from the game's System list or the title's, not a tab)
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    const float bar = ui::prompt_bar_top(c);
    // (the Salesman's corner: the right of the cards' column, by the details; the cards narrower while he is there)
    if (salesman::state() == salesman::State::Idle && host && host->romfs_dir) salesman::start(host->romfs_dir());
    const bool salesman_on = salesman::state() != salesman::State::Failed && mods::available();
    // ((Triforce) 11-17, layout A: the list at the left with the category tabs over it, the details at the right)
    const float tabs_h = mods::available() && mods::accepted() ? 44 * s : 0;
    // ((Triforce, 11-18) the mods expanded out, more of them on screen: the cards run to the prompt bar, and the Salesman has
    // a band of his own at the right column's foot, under its plate, with his line beside him, over nothing)
    // ((Triforce, 11-18) his band, but never over a quarter of the page: at a large menu unit 258 * s took almost all of a
    // 2160-high window's room and the details panel had none left)
    const float sales_h = salesman_on && mods::accepted() ? std::max(0.0f, std::min(300 * s, (bar - hh) * 0.26f)) : 0;
    // (the caption plates stop above his band, and short of the window's edge, while this page draws, wherever it returns from)
    struct CaptionFor {
        float floor_was, edge_was;
        CaptionFor(float floor, float edge) : floor_was(caption_floor), edge_was(caption_edge) { caption_floor = floor, caption_edge = edge; }
        ~CaptionFor() { caption_floor = floor_was, caption_edge = edge_was; }
    } const caption_for(sales_h, 16 * s);
    const float left = cx0 + 34 * s, right = cx1 - 34 * s, top = hh + 18 * s + tabs_h, bottom = bar - 10 * s;
    const float search_h = 50 * s, list_top = top + search_h + 12 * s;   // ((Triforce) the search bar over the cards)
    if (tabs_h > 0) {   // (the categories: a strip of tabs over the list, the chosen one light on dark as the game's own tabs)
        const float ty = hh + 14 * s, th = 32 * s, gap = 8 * s, px = 15 * s;
        float w = 0;
        for (int k = 0; k < kModsCats; k++) w += ui::size_of(c.f.strong, px, kModsCatNames[k]).x + 28 * s + (k ? gap : 0);
        float x = (left + right) * 0.5f - w * 0.5f;
        for (int k = 0; k < kModsCats; k++) {
            const float tw = ui::size_of(c.f.strong, px, kModsCatNames[k]).x + 28 * s;
            const bool on = k == mods_cat;
            c.d->AddRectFilled(ImVec2(x, ty), ImVec2(x + tw, ty + th), on ? ui::rgba(239, 228, 204, 235) : ui::rgba(40, 30, 20, 170), 6 * s);
            ui::text_mid_centre(c, c.f.strong, px, x + tw * 0.5f, ty + th * 0.5f, on ? ui::rgba(58, 43, 27) : ui::kSoft, kModsCatNames[k]);
            hits.add(x, ty, x + tw, ty + th, menu_hit::kTab, 100 + k);
            x += tw + gap;
        }
        ui::text_mid_centre(c, c.f.strong, 14 * s, (left + right) * 0.5f - w * 0.5f - 22 * s, ty + th * 0.5f, ui::kDim, "L");
        ui::text_mid_centre(c, c.f.strong, 14 * s, x + 14 * s, ty + th * 0.5f, ui::kDim, "R");
    }
    if (!mods::available()) {
        caption(c, hx0, hx1, "Mods", "Browsing and installing mods from inside the game is not available on this system yet. Put a mod's "
                "folder (the one holding romfs) into the mods folder beside the game.", nullptr, nullptr);
        const ui::Prompt p[] = {{ui::kBack, "Back"}};
        ui::prompt_bar(c, p, 1);
        return;
    }
    if (!mods::accepted()) {   // (the warning, once: Install at your own risk)
        static const char* const labels[] = {"I understand", "Not now"};
        mods_dialog(c, "Mods from GameBanana",
                    "These mods are made by players and shared on GameBanana. Triforce does not check them: install them at your own "
                    "risk.\nIf one breaks the game, turn it off or remove it in Triforce Setup's Mods page, or start with Play "
                    "without mods there.", labels, 2);
        const ui::Prompt p[] = {{ui::kUpDown, "Move"}, {ui::kConfirm, "Choose"}, {ui::kBack, "Back"}};
        ui::prompt_bar(c, p, 3);
        return;
    }
    std::string err;
    const mods::Feed feed = mods::feed_state(&err);
    const mods::InstallState inst = mods::install_state();
    const bool more = mods::more();
    const std::string searched = mods::search_text();   // ((Triforce) before the lock: it takes it)
    mods::lock();
    std::vector<mods::Mod>& list = mods::list();
    const int n_all = (int)list.size();
    if (n_all) mods_choice = std::clamp(mods_choice, -1, n_all - 1);   // ((Triforce) -1: the search bar)
    std::vector<int> vis;   // ((Triforce) the cards of the category chosen, by their place in the list)
    for (int i = 0; i < n_all; i++)
        if (mods_in_cat(list[i], mods_cat)) vis.push_back(i);
    const int n = (int)vis.size();
    int choice_at = -1;   // (the chosen one's place among them)
    for (int k = 0; k < n; k++)
        if (vis[k] == mods_choice) choice_at = k;
    int made = 0;
    // (the cards: the picture at the left as the game's save cards have it, the name, the author and category, the counts; the
    // installed ones tagged; the cards scrolled to keep the chosen one in view)
    const float card_h = 92 * s, pitch = 102 * s, pic_w = card_h * 16 / 9;
    const float view = bottom - list_top, total_h = n * pitch + (more || feed == mods::Feed::Loading ? 40 * s : 0);
    mods_page_rows = std::max(1, (int)(view / pitch) - 1);
    float& at = mods_scroll_px;
    float& want = mods_want_px;
    if (mods_wheel) want -= mods_wheel * pitch, mods_wheel = 0, mods_follow = false;
    if (total_h <= view || (mods_follow && choice_at < 0)) want = 0;
    else if (!mods_follow) want = std::clamp(want, 0.0f, total_h - view);
    else {
        const float y0 = choice_at * pitch - pitch * 0.5f, y1 = (choice_at + 1) * pitch + pitch * 0.5f;
        if (y0 < want) want = y0;
        if (y1 > want + view) want = y1 - view;
        want = std::clamp(want, 0.0f, total_h - view);
    }
    at += (want - at) * ease_step;
    if (std::fabs(want - at) < 0.5f) at = want;
    if (total_h > view) scroll_bar(c, cx0 + 12 * s, list_top, bottom, (int)total_h, (int)view, at);
    c.d->PushClipRect(ImVec2(left - 14 * s, list_top), ImVec2(right + 14 * s, bottom), true);
    std::vector<int> ask_thumbs;   // (asked for once the list is let go: the engine's calls lock it themselves)
    int ask_details = -1;
    textures_reap();
    for (int i = 0; i < n_all; i++) {   // (the pictures of another category's cards let go)
        if (list[i].texture && i != mods_choice && !mods_in_cat(list[i], mods_cat)) {
            texture_retire((ImTextureData*)list[i].texture);
            list[i].texture = nullptr, list[i].thumb_state = 0;
        }
    }
    ImVec2 glow_a{}, glow_b{};   // ((Triforce, 11-18) the chosen one's cursor, drawn after every item: the next one's
    bool glow_have = false;     // plate covered part of it, which read as the highlight clipped)
    for (int k = 0; k < n; k++) {
        const int i = vis[k];
        const ImVec2 a(left, list_top + k * pitch - at), b(right, a.y + card_h);
        // ((Triforce) a picture 12 cards or more out of view let go, the chosen one's kept: made again from its kept file
        // when it comes near. Kept all, the fifth page of mods used up the overlays' textures, 11-17)
        if ((b.y < list_top - 12 * pitch || a.y > bottom + 12 * pitch) && list[i].texture && i != mods_choice) {
            texture_retire((ImTextureData*)list[i].texture);
            list[i].texture = nullptr, list[i].thumb_state = 0;
        }
        if (b.y < list_top - pitch || a.y > bottom + pitch) continue;
        mods::Mod& m = list[i];
        if (!m.thumb_state) ask_thumbs.push_back(i);   // (the ones in view and the next few)
        if (b.y < list_top || a.y > bottom) continue;
        const bool sel = i == mods_choice;
        ui::plate(c, a, b, sel);
        const ImVec2 pa(a.x + 8 * s, a.y + 8 * s), pb(pa.x + pic_w - 16 * s, b.y - 8 * s);
        mods_picture(c, m, pa, pb, &made);
        const float tx = pb.x + 16 * s;
        float tag_w = 0;
        if (m.installed) tag_w = card_tag(c, b.x - 12 * s, a.y + 20 * s, m.update ? "Update" : "Installed") + 10 * s;
        c.d->PushClipRect(ImVec2(tx, a.y), ImVec2(b.x - 12 * s - tag_w, b.y), true);
        // ((Triforce, 11-18) each line cut on whole characters with an ellipsis where it does not fit, not by the clip alone)
        ui::text_mid_fit(c, c.f.strong, 19 * s, tx, a.y + 22 * s, ui::kInkBright, m.name.c_str(), b.x - 12 * s - tag_w - tx);
        c.d->PopClipRect();
        c.d->PushClipRect(ImVec2(tx, a.y), ImVec2(b.x - 12 * s, b.y), true);
        const std::string by = "by " + m.author + (m.category.empty() ? "" : "  \xC2\xB7  " + m.category) + mods_kind(m);
        ui::text_mid_fit(c, c.f.body, 15 * s, tx, a.y + 48 * s, ui::kSoft, by.c_str(), b.x - 12 * s - tx);
        const std::string counts = mods_count(m.likes) + " likes  \xC2\xB7  " + mods_count(m.views) + " views";
        ui::text_mid_fit(c, c.f.body, 13.5f * s, tx, a.y + 70 * s, ui::alpha(ui::kSoft, 0.72f), counts.c_str(), b.x - 12 * s - tx);
        c.d->PopClipRect();
        if (sel) glow_a = a, glow_b = b, glow_have = true;
        hits.add(a.x, std::max(a.y, list_top), b.x, std::min(b.y, bottom), menu_hit::kListLine, i);
    }
    if (glow_have) ui::glow(c, glow_a, glow_b);
    if (n && (more || feed == mods::Feed::Loading)) {   // ((Triforce) 11-18, the foot of the list: the pages come by themselves)
        const float y = list_top + n * pitch - at + 16 * s;
        if (y < bottom) ui::text_mid_centre(c, c.f.body, 15 * s, (left + right) * 0.5f, y, feed == mods::Feed::Failed ? ui::kAccent : ui::kDim,
                                            feed == mods::Feed::Failed ? "GameBanana stopped answering: Confirm on the search bar tries again"
                                                                       : "Loading more...");
    }
    c.d->PopClipRect();
    if (!n) {   // (no list yet: asking, or the answer that failed; (Triforce) a search's: asking, or none found)
        const float my = list_top + view * 0.38f, mx_ = (left + right) * 0.5f;
        std::string t = feed == mods::Feed::Failed ? "GameBanana could not be reached." : "Asking GameBanana for mods...";
        if (n_all && mods_cat) t = feed == mods::Feed::Loading || more ? "Looking for more in " + std::string(kModsCatNames[mods_cat]) + "..."
                                                                         : "None in " + std::string(kModsCatNames[mods_cat]) + " yet";
        if (!searched.empty() && feed != mods::Feed::Failed)
            t = feed == mods::Feed::Ready ? "No mods match \xE2\x80\x9C" + searched + "\xE2\x80\x9D" : "Searching for \xE2\x80\x9C" + searched + "\xE2\x80\x9D...";
        c.d->PushClipRect(ImVec2(left, list_top), ImVec2(right, bottom), true);
        ui::text_mid_centre(c, c.f.strong, 20 * s, mx_, my, ui::kInk, t.c_str());
        if (feed == mods::Feed::Failed) {
            ui::text_mid_centre(c, c.f.body, 15 * s, mx_, my + 34 * s, ui::kSoft, err.c_str());
            ui::text_mid_centre(c, c.f.body, 15 * s, mx_, my + 62 * s, ui::kAccent, "Press Confirm to try again");
        } else if (!searched.empty() && feed == mods::Feed::Ready) {
            ui::text_mid_centre(c, c.f.body, 15 * s, mx_, my + 34 * s, ui::kSoft, "Try another word, or Back for the whole list.");
        }
        c.d->PopClipRect();
    }
    mods_search_bar(c, ImVec2(left, top), ImVec2(right, top + search_h), searched, feed, n, more);   // (the lock held: no engine calls in it)
    // (the chosen mod at the right, on the caption plate: its picture large, what it is, its counts, the file, its description)
    const char* install_label = "Install";
    bool can_install = false;
    int files = 0;
    if (n && mods_choice >= 0 && choice_at >= 0) {
        mods::Mod& m = list[mods_choice];
        if (!m.details_state) ask_details = mods_choice;
        if (!m.thumb_state) ask_thumbs.push_back(mods_choice);
        files = (int)m.files.size();
        can_install = m.details_state == 2 && files > 0;
        install_label = m.update ? "Update" : m.installed ? "Reinstall" : "Install";
        if (m.kit) install_label = m.update ? "Update and start" : m.installed ? "Start" : "Install and start";
        const float x0 = hx0, x1 = hx1, pad = ui::lu(c, 64), y0 = top, y1 = bar - 8 * s - sales_h;   // ((Triforce, 11-18) his band kept clear)
        ui::box(c, ImVec2(x0, y0), ImVec2(x1, y1));
        c.d->PushClipRect(ImVec2(x0, y0), ImVec2(x1, y1), true);
        const float w = x1 - x0 - 2 * pad;
        float y = y0 + pad * 0.6f;
        // (the file chosen, its line, and a kit's note: measured for the header before they are drawn)
        static const char* const kit_note = "A program of its own: it goes into the kits folder beside the game and starts in a window of "
                                            "its own, where it shows its steps. No restart.";
        const mods::File* file = m.details_state == 2 && files ? &m.files[std::clamp(m.file_choice, 0, files - 1)] : nullptr;
        const std::string file_line = !file ? std::string()
                                            : (files > 1 ? "File " + std::to_string(m.file_choice + 1) + " of " + std::to_string(files) + ":  " : std::string("File:  ")) +
                                                  file->name + "  (" + mods_size(file->bytes) + ")";
        float file_h = 0;
        if (file) {
            file_h = ui::para(c, c.f.strong, 14 * s, ImVec2(), 0, file_line.c_str(), w - 16 * s, false) + 2 * s;
            if (!file->description.empty()) file_h += ui::para(c, c.f.body, 13.5f * s, ImVec2(), 0, file->description.c_str(), w - 16 * s, false);
            if (m.kit) file_h += ui::para(c, c.f.body, 13.5f * s, ImVec2(), 0, kit_note, w - 16 * s, false) + 2 * s;
            file_h += 8 * s;
        }
        // ((Triforce, 11-18) his "the actual mod detail preview windows information to be compacted and actually be
        // readable in that window size": the header's own height is measured at this menu's unit, the description keeps
        // three lines, and the picture is a 16:9 box of what is left over (none when that is nothing: the words matter
        // more), so nothing the panel holds is cut whatever the window and the unit do)
        const float panel_h = y1 - y0;
        const float title_max = 2 * 1.3f * 20 * s;   // ((Triforce, 11-18) a long name is two lines at most)
        const float title_h = std::min(ui::para(c, c.f.strong, 20 * s, ImVec2(), 0, m.name.c_str(), w, false), title_max) + 4 * s;
        // (under the picture: 16, the name, the author's and the counts' lines (24 each), the file, the rule's 12)
        const float header_h = 16 * s + title_h + 48 * s + file_h + 12 * s;
        const float desc_need = 3 * kModsDescPt * s * 1.5f;
        const float pic_room = panel_h - pad * 1.2f - header_h - desc_need;
        const float pic_h = pic_room > 60 * s ? std::min(pic_room, std::min(panel_h * 0.42f, 420 * s)) : 0.0f;
        const float pic_w = pic_h > 0 ? std::min(w, pic_h * 16.0f / 9.0f) : 0.0f;
        const ImVec2 pa(x0 + pad, y), pb(x0 + pad + pic_w, y + pic_h);
        {   // (what the panel measured: once for each mod chosen, for a run's log)
            static int64_t told_for = -2;
            if (told_for != mods_choice)
                told_for = mods_choice, logf("menu: mods details: panel %.0f..%.0f (%.0f tall), picture %.0fx%.0f at %.0f, "
                                             "files %d, details %d, window %ux%u, unit %.3f, header %.0f, description %.0f, search %.0f..%.0f x %.0f..%.0f",
                                             y0, y1, panel_h, pic_w, pic_h, pa.x, files, m.details_state, (unsigned)c.w, (unsigned)c.h, s,
                                             header_h, panel_h - pad * 1.2f - header_h - pic_h, left, right, top, top + search_h);
        }
        if (pic_h > 0) mods_picture(c, m, pa, pb, &made);
        y = (pic_h > 0 ? pb.y : y) + 16 * s;
        {   // ((Triforce, 11-18) drawn in the room the header was measured with: the rest is cut, not pushed down)
            c.d->PushClipRect(ImVec2(x0 + pad, y), ImVec2(x1 - pad, y + title_max), true);
            ui::para(c, c.f.strong, 20 * s, ImVec2(x0 + pad, y), ui::kInk, m.name.c_str(), w);
            c.d->PopClipRect();
            y += title_h;
        }
        // ((Triforce, 11-18) no blank "by " line: the category alone without an author, the kind alone without either)
        std::string by = m.author.empty() ? m.category : "by " + m.author + (m.category.empty() ? "" : "  \xC2\xB7  " + m.category);
        if (const std::string kind = mods_kind(m); !kind.empty()) by += by.empty() ? kind.substr(6) : kind;   // (6: its "  ·  " in front)
        if (!by.empty()) ui::text_fit(c, c.f.body, 15 * s, ImVec2(x0 + pad, y), ui::kAccent, by.c_str(), w);
        y += 24 * s;
        std::string counts = mods_count(m.likes) + " likes  \xC2\xB7  " + mods_count(m.views) + " views";
        if (m.downloads >= 0) counts += "  \xC2\xB7  " + mods_count(m.downloads) + " downloads";
        ui::text_fit(c, c.f.body, 14 * s, ImVec2(x0 + pad, y), ui::kSoft, counts.c_str(), w);
        y += 24 * s;
        if (file) {
            ui::diamond(c, ImVec2(x0 + pad + 5 * s, y + 9 * s), 4 * s, ui::kGoldHi);
            y += ui::para(c, c.f.strong, 14 * s, ImVec2(x0 + pad + 16 * s, y), ui::kGoldHi, file_line.c_str(), w - 16 * s) + 2 * s;
            if (!file->description.empty()) y += ui::para(c, c.f.body, 13.5f * s, ImVec2(x0 + pad + 16 * s, y), ui::kSoft, file->description.c_str(), w - 16 * s);
            if (m.kit)   // ((Triforce) 11-18) a program of its own, not a mod in the game's mods folder
                y += ui::para(c, c.f.body, 13.5f * s, ImVec2(x0 + pad + 16 * s, y + 2 * s), ui::kAccent, kit_note, w - 16 * s) + 2 * s;
            y += 8 * s;
        }
        c.d->AddLine(ImVec2(x0 + pad, y), ImVec2(x1 - pad, y), ui::alpha(ui::kEdge, 0.8f), std::max(1.0f, s));
        y += 12 * s;
        const char* text = m.details_state == 2 ? m.text.c_str() : m.details_state == 3 ? "The details could not be read from GameBanana." : "Loading the details...";
        if (m.details_state == 2 && !files) text = "This mod has no file to download on GameBanana.";
        if (m.details_state == 2 && files && m.text.empty()) text = "No description on GameBanana.";   // ((Triforce, 11-18))
        {   // ((Triforce) 11-17) the description in its own window down to the panel's foot, scrolled by the right stick or the wheel
            const float dtop = y, dbot = y1 - pad * 0.6f;
            if (mods_desc_for != mods_choice) mods_desc_for = mods_choice, mods_desc_px = 0;
            const float th = ui::para(c, c.f.body, kModsDescPt * s, ImVec2(x0 + pad, dtop), ui::kInk, text, w, false);   // ((Triforce, 11-18) smaller)
            const float room = std::max(0.0f, dbot - dtop), most = std::max(0.0f, th - room);
            if (menu_pad_raw >> HOS_PAD_RS_DOWN & 1) mods_desc_px += 10 * s;
            if (menu_pad_raw >> HOS_PAD_RS_UP & 1) mods_desc_px -= 10 * s;
            if (mods_desc_wheel) mods_desc_px -= mods_desc_wheel * 60 * s, mods_desc_wheel = 0;
            mods_desc_px = std::clamp(mods_desc_px, 0.0f, most);
            c.d->PushClipRect(ImVec2(x0, dtop), ImVec2(x1, dbot), true);
            ui::para(c, c.f.body, kModsDescPt * s, ImVec2(x0 + pad, dtop - mods_desc_px), ui::kInk, text, w);
            c.d->PopClipRect();
            if (most > 0) scroll_bar(c, x1 - pad * 0.45f, dtop, dbot, (int)th, (int)room, mods_desc_px);
            mods_desc_x0 = x0;
        }
        c.d->PopClipRect();
    } else if (mods_choice < 0) {   // ((Triforce) the search bar chosen)
        caption(c, hx0, hx1, "Search", "Search GameBanana's mods for this game: type a word (a name, a character, an item, an "
                "author), or press Confirm for a keyboard. The list shows what matches as you type; Back shows the whole list again.",
                nullptr, nullptr);
    } else {
        caption(c, hx0, hx1, "Mods", "Mods for this game from GameBanana: choose one to see what it does, then install it. It is "
                "in the game at its next start.", nullptr, nullptr);
    }
    mods::unlock();
    if (ask_details >= 0) mods::want_details(ask_details);
    for (int i : ask_thumbs) mods::want_thumb(i);
    if (salesman_on) {   // (him, and a line now and then: a new one when the choice moves, not more than every 9 s)
        // ((Triforce, 11-18) his "move the text box ... not covering the mods and make the model ... not cover mods either":
        // in the details column's foot, under its plate, where nothing is drawn, with his line beside him to the left: the
        // cards keep the list's whole height and neither he nor his box is over them)
        const float sy1 = bar - 8 * s, sy0 = sy1 - sales_h;
        const float sx1 = hx1, sx0 = hx1 - sales_h * 0.82f;   // ((Triforce, 11-18) his width follows the band: he keeps his shape)
        salesman_picture(c, ImVec2(sx0, sy0), ImVec2(sx1, sy1));
        const int64_t now = prof_now();
        static int last_choice = -1;
        if (last_choice != mods_choice && now - salesman_line_at > 9000000000LL) {
            last_choice = mods_choice, salesman_line_at = now;
            salesman_line = (salesman_line + 1) % (int)(sizeof salesman_lines / sizeof *salesman_lines);
        }
        if (salesman::state() == salesman::State::Ready && inst.job == mods::Job::None)
            salesman_says(c, hx0, sx0 - 10 * s, bar - 14 * s, salesman_lines[salesman_line]);
    }
    // (the install under way, or its end: over the page)
    if (inst.job == mods::Job::Downloading || inst.job == mods::Job::Unpacking) {
        static const char* const labels[] = {"Cancel"};
        mods_btn = 0;
        char left_t[96] = "", right_t[64] = "";
        float frac = 0;
        if (inst.job == mods::Job::Downloading) {
            frac = inst.total ? (float)inst.done / (float)inst.total : 0;
            snprintf(left_t, sizeof left_t, "Downloading...  %s / %s", mods_size(inst.done).c_str(), inst.total ? mods_size(inst.total).c_str() : "?");
            if (inst.rate > 1024 && inst.total > inst.done) {
                const int secs = (int)((inst.total - inst.done) / inst.rate);
                snprintf(right_t, sizeof right_t, "%.0f%%  \xC2\xB7  about %d:%02d left", frac * 100, secs / 60, secs % 60);
            } else snprintf(right_t, sizeof right_t, "%.0f%%", frac * 100);
        } else {
            frac = 1;
            snprintf(left_t, sizeof left_t, "Unpacking...");
        }
        mods_dialog(c, ("Installing " + inst.mod_name).c_str(), inst.file_name, labels, 1, frac, left_t, right_t);
        const ui::Prompt p[] = {{ui::kBack, "Cancel"}};
        ui::prompt_bar(c, p, 1);
        return;
    }
    if (inst.job == mods::Job::Done && inst.kit) {   // ((Triforce) 11-18) a kit: started in its own window, no restart
        static const char* const labels[] = {"OK"};
        mods_btn = 0;
        mods_dialog(c, "Started!", inst.mod_name + "\n" + inst.message, labels, 1, 1, "Started", "In its own window");
        const ui::Prompt p[] = {{ui::kConfirm, "OK"}};
        ui::prompt_bar(c, p, 1);
        return;
    }
    if (inst.job == mods::Job::Done) {
        static const char* const labels[] = {"Restart Now", "Later"};
        mods_dialog(c, "Installed!", inst.mod_name + "\n" + inst.message + "\nRestart the game to play with it.", labels, 2, 1, "Installed", "Restart to apply");
        const ui::Prompt p[] = {{ui::kUpDown, "Move"}, {ui::kConfirm, "Choose"}, {ui::kBack, "Later"}};
        ui::prompt_bar(c, p, 3);
        return;
    }
    if (inst.job == mods::Job::Failed || inst.job == mods::Job::Cancelled) {
        static const char* const labels[] = {"OK"};
        mods_btn = 0;
        mods_dialog(c, inst.job == mods::Job::Cancelled ? "Cancelled" : "Not installed", inst.mod_name + "\n" + inst.message, labels, 1);
        const ui::Prompt p[] = {{ui::kConfirm, "OK"}};
        ui::prompt_bar(c, p, 1);
        return;
    }
    if (mods_kbd) {   // ((Triforce) the on-screen keyboard, over the page)
        mods_keyboard(c);
        const ui::Prompt p[] = {{ui::kUpDown, "Move"}, {ui::kConfirm, "Type"}, {ui::kBack, mods_query.empty() ? "Close" : "Delete"}};
        ui::prompt_bar(c, p, 3);
        return;
    }
    ui::Prompt prompts[7];
    int pn = 0;
    const bool clears = !searched.empty() || !mods_query.empty();
    prompts[pn++] = {ui::kUpDown, "Move"};
    prompts[pn++] = {ui::kTabs, "Category"};
    if (mods_choice < 0)
        prompts[pn++] = {ui::kConfirm, mods_query != mods_query_sent ? "Search" : !n && feed == mods::Feed::Failed ? "Try again"
                                       : pad_last || !n ? "Keyboard" : "Results"};
    else {
        if (files > 1) prompts[pn++] = {ui::kLeftRight, "File"};
        if (mods_query != mods_query_sent) prompts[pn++] = {ui::kConfirm, "Search"};
        else if (can_install) prompts[pn++] = {ui::kConfirm, install_label};
        else if (!n && feed == mods::Feed::Failed) prompts[pn++] = {ui::kConfirm, "Try again"};
    }
    prompts[pn++] = {ui::kBack, clears ? "Clear search" : "Back"};
    ui::prompt_bar(c, prompts, pn);
}

/// (the menu's column in the window: its left edge (more than 0 only on a window wider than 16:9), and (Triforce, 11-19) with
/// the Mods entry's page the game's grid it is drawn on (put_on_grid): menu_tick takes the mouse back through it)
game_grid::Map menu_map;
float menu_window_w = 0, menu_window_h = 0;   // ((Triforce, 11-20) the window draw_menu draws in, in its pixels: dim_page's)
/// ((Triforce, 11-19) the game's layouts' grid in a w x h window (game_grid.h), from the picture the last present showed
game_grid::Place menu_grid(float w, float h) {
    const uint64_t ps = present_sizes.load(std::memory_order_relaxed);
    const double aspect = host && host->aspect_ratio ? host->aspect_ratio() : 0.0;
    return game_grid::of((uint32_t)(ps >> 48 & 0xffff), (uint32_t)(ps >> 32 & 0xffff), (uint32_t)w, (uint32_t)h, aspect);
}
/// ((Triforce, 11-20) a dim over the whole w x h window, drawn in m's pixels (back_x, back_y: a drawing put on the grid
/// after): col over the game's picture g, black at col's alpha over the bars beside, above or below it (game_grid.h
/// dim_parts). The lab's check 3 of 26670c0: the bars turned a dark brown under our dialogs (luminance about 9 where they
/// were 0); over the picture the dim is as it was)
void dim_window(ImDrawList* d, const game_grid::Map& m, const game_grid::Place& g, float w, float h, ImU32 col) {
    game_grid::Rect r[5];
    const int n = game_grid::dim_parts(g, w, h, r);
    for (int i = 0; i < n; i++)
        d->AddRectFilled(ImVec2(m.back_x(r[i].x0), m.back_y(r[i].y0)), ImVec2(m.back_x(r[i].x1), m.back_y(r[i].y1)), i ? (col & IM_COL32_A_MASK) : col);
}
/// ((Triforce, 11-20) a dialog's dim over the page (the restart question, the Mods page's dialogs and keyboard): the whole
/// window in the column's pixels (menu_map, as draw_quit_ask's), over the page and its header wherever the grid is
/// (panel_merge first); the bars black under it (dim_window) where the game's own black is under it: inside the game's Options
/// screen (embed_open). ((Triforce, 11-20, a review of 408e2dc) Over play (F1, the Mods page from the game's lists) draw_menu
/// covered the whole window with our own background first (ui::system_bg, or the flat dim) and our page and header are on
/// the window's column, over the bars too: there one rectangle, in the dim's colour, as on 26670c0; cut at the picture's
/// edges it left a straight step of the tint across our background and header (y 112 and 787 in a 1600 x 900 window with
/// a 21:9 picture). The Full panel, if it waits, then over the dim (panel_over)
void dim_page(ui::Ctx& c, ImU32 col) {
    panel_merge(c.d);
    const float w = menu_window_w > 0 ? menu_window_w : c.w, h = menu_window_h > 0 ? menu_window_h : c.h;
    const bool game_black = embed_open || page == kModsRowPage;   // (the game's picture and its bars under our page)
    dim_window(c.d, menu_map, game_black ? menu_grid(w, h) : game_grid::Place{}, w, h, col);
    panel_over(c.d);
}
/// (the clip rectangle drawing goes on with now: the window's, put_on_grid's `keep`)
ImVec4 clip_now(const ImDrawList* d) {
    const ImVec2 a = d->GetClipRectMin(), b = d->GetClipRectMax();
    return ImVec4(a.x, a.y, b.x, b.y);
}
/// (a drawing of the Mods entry's, from vtx0 and cmd0 on, made on the grid's 16:9 column (grid_ctx), put where the grid is.
/// keep: the window's clip rectangle (clip_now before the drawing), which stays; the column's own ones move with it.
/// ((Triforce, 11-19) the vertices from skip0 to skip1 stay where they are: the Full panel's, drawn among a page's in the
/// window's own pixels (draw_menu). Was: every clip rectangle from the window's left edge to its right one kept, which also
/// kept a column's own as wide as the window where the grid is lower than the window's top (16:9 picture, 16:10 window))
void put_on_grid(ImDrawList* d, int vtx0, int cmd0, const game_grid::Map& m, const ImVec4& keep, int skip0 = 0, int skip1 = 0) {
    for (int i = vtx0; i < d->VtxBuffer.Size; i++)
        if (i < skip0 || i >= skip1) d->VtxBuffer[i].pos = ImVec2(m.x(d->VtxBuffer[i].pos.x), m.y(d->VtxBuffer[i].pos.y));
    for (int i = std::max(0, cmd0 - 1); i < d->CmdBuffer.Size; i++) {   // (the column's clip rectangles with it; the window's stay)
        ImVec4& r = d->CmdBuffer[i].ClipRect;
        if (r.x == keep.x && r.y == keep.y && r.z == keep.z && r.w == keep.w) continue;
        r = ImVec4(m.x(r.x), m.y(r.y), m.x(r.z), m.y(r.w));
    }
}
/// ((Triforce, 11-19) the window's clip rectangle in a column's own pixels, pushed while a page draws on it: the page's own
/// rectangles are cut to it, then put back on the window with them. On a grid narrower than 16:9 (squeezed across) the
/// column is wider than the window, and the window's rectangle as it is would cut the page's right side)
void push_window_clip(ImDrawList* d, const game_grid::Map& m, float window_w, float window_h) {
    d->PushClipRect(ImVec2(m.back_x(0), m.back_y(0)), ImVec2(m.back_x(window_w), m.back_y(window_h)), false);
}
/// (the grid's 16:9 column, its own pixels from 0: as a window of the grid's height)
ui::Ctx grid_ctx(const ui::Ctx& c, const game_grid::Place& g) {
    ui::Ctx k = c;
    k.h = g.h, k.w = game_grid::column_w(g);
    k.s = ui::unit(g.h, 0, false, false, &k.safe);
    return k;
}
/// ((Triforce, 11-19) our options' pages are over the game's own panes: our tabs open inside its Options screen (embed_open), or
/// that screen showing with them shut (the bake ahead of their open: prebake, draw_menu's dry run), or its own tab's header
bool pages_on_game() { return embed_open || (!open_now.load(std::memory_order_relaxed) && game_options_shown()); }
/// (the column the options' pages are drawn on in a w x h window, and where it goes: game_grid.h column_of)
game_grid::Column pages_column(float w, float h, bool on_game) {
    return game_grid::column_of(on_game ? menu_grid(w, h) : game_grid::Place{}, w, h, on_game);
}
/// (a context for that column: its size and its unit)
ui::Ctx column_ctx(const ui::Ctx& c, const game_grid::Column& col) {
    ui::Ctx k = c;
    k.w = col.w, k.h = col.h;
    if (col.h != c.h) k.s = ui::unit(col.h, 0, false, false, &k.safe);
    return k;
}
/// ((Triforce, 11-19) the title's entry, as each of the list's entries is the part PaCommonBtnTitle_00 (vk_game_tex.h
/// make_title_skin, mods_entry_anim.h): in the part's own units round (cx, cy), times k, the list's scale (the last button's
/// hit box, 60 units in the part). Not chosen: the text (65 x 0.8 units, the game's "Normal" font) in its cream, its shadow
/// 2 units under it (T_BtnSh_00). Chosen: the dark band under it (W_Bg_00), the filigree either side (P_Deco_L_00 mirrored,
/// P_Deco_R_00, each over its glow), the text white over its blue glow (P_BtnGlow_00, the text's own shape blurred). The
/// filigree is placed by the part's alignment pane: beside the text however wide it is, and the band reaches past it as
/// far. Measured from the lab's shot of the game's own chosen Continue (runs/pt-menu, 1440 high: 2/3 of a pixel a unit):
/// the filigree's middles 93 units out from the text's ends, the band 198 past them and 144 high (W_Bg_00 is 160: its
/// texture's band is 0.84 of that, and the shot's 120 is that with its wavy edges), the glow (120,140,255), the text 2 units
/// above the band's middle (N_Text_00). The colours are the layout's materials', the glow's and the band's the shot's. ((11-19)
/// The shadow's dark edge and the glow's reach: text_spread.h, fitted to the game's entries)
constexpr float kTitleText = 65 * 0.8f, kTitleDecoGap = 93, kTitleBandPast = 198, kTitleBandH = 144, kTitleDeco = 128;
constexpr ImU32 kTitleInk = ui::rgba(255, 254, 228);      // (T_Btn_01's material: the layout's colour 5, linear 1 0.988 0.776)
constexpr ImU32 kTitleInkSel = ui::rgba(255, 255, 255);   // (T_Btn_02's: white)
constexpr ImU32 kTitleDecoInk = ui::rgba(131, 115, 22);   // (P_Deco_*_00's: colour 4, linear 0.227 0.173 0.008)
constexpr ImU32 kTitleGlow = ui::rgba(120, 140, 255);
mods_entry::Anim title_anim;
// ((Triforce) Save Select under it is the same part with its own label and animation: draw_title_files sets these for its call)
const char* title_label = "Mods";
int title_entry = 0;   // (0 Mods, 1 Save Select: its hit, and Mods' Decide and place are Mods' alone)
void draw_title_mods(ui::Ctx& c, bool sel, float cx, float cy, float k, float pitch) {
    const int64_t now = prof_now(), age = mods_list_age();
    title_anim.step(now, sel, std::min<int64_t>(age, mods_entry::kListShownNs), mods_list_shown());
    const float show = title_anim.shown, f = title_anim.focus;
    const ImVec2 m = ui::at(c, cx, cy);
    const char* const label = title_label;
    const float px = ui::lu(c, kTitleText * ui::kType * k), tw = ui::size_of(c.f.body, px, label).x;
    const float deco_x = tw * 0.5f + ui::lu(c, kTitleDecoGap * k);
    const mods_entry::Decide d = mods_entry::decide_at(mods_decide_ns && !title_entry ? now - mods_decide_ns : -1);
    if (f > 0 && show > 0) {
        const float hw = deco_x + ui::lu(c, kTitleBandPast * k), hh = ui::lu(c, kTitleBandH * 0.5f * k);
        const ImVec2 a(m.x - hw, m.y - hh), b(m.x + hw, m.y + hh);
        if (const ui::Art* band = ui::art("title_band")) {
            ui::image(c, band, a, b, ui::alpha(IM_COL32_WHITE, f * show));
            const ui::Art* sparkle = ui::art("title_decide");
            if (sparkle && d.flash > 0) ui::image(c, sparkle, a, b, ui::alpha(IM_COL32_WHITE, 0.5f * d.flash * show));   // (W_Bg_01)
        } else {   // (no title textures in the game's files: a plain band, fading out at its ends)
            const float core = hw * 0.7f;
            const ImU32 dark = ui::rgba(8, 6, 12, (int)(205 * f * show)), none = ui::rgba(8, 6, 12, 0);
            c.d->AddRectFilled(ImVec2(m.x - core, a.y), ImVec2(m.x + core, b.y), dark);
            c.d->AddRectFilledMultiColor(a, ImVec2(m.x - core, b.y), none, dark, dark, none);
            c.d->AddRectFilledMultiColor(ImVec2(m.x + core, a.y), b, dark, none, none, dark);
        }
        const ui::Art *deco = ui::art("TitleBtnDeco_00"), *glow = ui::art("TitleBtnDecoGlow_00");
        const float strength = f * show * title_anim.loop(now);   // (LoopRandom: the filigree breathes)
        for (int side = -1; deco && side <= 1; side += 2) {   // (the left one is the texture mirrored: its point to the text)
            const float x = m.x + side * deco_x;
            const float ds = ui::lu(c, kTitleDeco * 0.5f * k * d.deco), gs = ui::lu(c, kTitleDeco * 0.5f * k * d.glow);
            if (glow) ui::image(c, glow, ImVec2(x - gs, m.y - gs), ImVec2(x + gs, m.y + gs), ui::alpha(kTitleDecoInk, 0.1f * strength), side < 0);
            ui::image(c, deco, ImVec2(x - ds, m.y - ds), ImVec2(x + ds, m.y + ds), ui::alpha(kTitleDecoInk, strength), side < 0);
        }
    }
    const float ty = m.y - ui::lu(c, 2 * k);
    // (the text's top left: as text_mid_centre puts it. (Triforce, 11-20) On a whole pixel, where ImGui would put the text,
    // so that the copies round it can be put at their own offsets from it)
    const ImVec2 at(std::floor(m.x - tw * 0.5f), std::floor(ui::mid_top(c.f.body, px, ty)));
    // (the text's own shape spread round it, ring after ring: T_BtnSh_00's dark edge, P_BtnGlow_00's glow (text_spread.h))
    // ((Triforce, 11-19) each copy's alpha a whole step of 255 and the copies as many as keep the fit's coverage
    // (text_spread::ring_drawn): ui::alpha's cut to a whole step took off most of the faint rings' alpha, some to 0)
    // ((11-20) each copy at its offset from the text, a part of a pixel too (ImDrawListFlags_TextNoPixelSnap): snapped,
    // ImGui cut each to the pixel left of and above it, and an offset under a pixel (the hard shadow's 2.5 units: 0.83 of a
    // pixel at 720 lines, 0.42 at 1440) became 0 or 1 by where the entry was)
    auto spread = [&](const text_spread::Spread& sp, ImU32 col, float amount) {
        const float own = (float)(col >> IM_COL32_A_SHIFT & 0xFF) / 255.0f;
        const ImU32 rgb = col & ~IM_COL32_A_MASK;
        const ImDrawListFlags flags = c.d->Flags;
        c.d->Flags |= ImDrawListFlags_TextNoPixelSnap;
        text_spread::each_copy(sp, amount * own, [&](float dx, float dy, int a) {
            c.d->AddText(c.f.body, px, ImVec2(at.x + ui::lu(c, dx * k), at.y + ui::lu(c, dy * k)), rgb | (ImU32)a << IM_COL32_A_SHIFT, label);
        });
        c.d->Flags = flags;
    };
    if (f < 1 && show > 0) {   // (N_TextUnSelect_00: the shadow, then the text)
        // ((11-20) the hard shadow under the soft edge, and the text at the game's weight)
        // ((Triforce, 11-20, lab check 3) per output (text_spread.h kLookHdr, kLookSdr): with HDR off the overlay blends in
        // 8-bit code values, where the HDR fit's black copies darkened a third as much (the lab's "edge much too weak, Mods
        // reads pale"). The weight by the text's size in pixels (its lines: 2160 units): copies across, a part of a unit out,
        // that widen the strokes (two in place have the same coverage at every size: 1 pixel with grey beside it at 674
        // lines, 20% light at 1440). On a 16:10 grid the copies are squeezed across with the text (put_on_grid's kx))
        const float a = (1 - f) * show;
        const text_spread::Look& look = text_spread::look_of(dev.hdr);
        spread(look.core, ui::rgba(0, 0, 0), a);
        spread(look.shadow, ui::rgba(0, 0, 0), a);
        const ImU32 ink_rgb = kTitleInk & ~IM_COL32_A_MASK;
        const ImDrawListFlags flags = c.d->Flags;
        c.d->Flags |= ImDrawListFlags_TextNoPixelSnap;
        text_spread::each_weight_copy(look.weight, ui::lu(c, 2160 * k), a, [&](float dx, float dy, int q) {
            c.d->AddText(c.f.body, px, ImVec2(at.x + ui::lu(c, dx * k), at.y + ui::lu(c, dy * k)), ink_rgb | (ImU32)q << IM_COL32_A_SHIFT, label);
        });
        c.d->Flags = flags;
    }
    if (f > 0 && show > 0) {   // (N_TextSelect_00: the glow, then the text)
        // ((Triforce, 11-20) the text kTextWeight times over itself here too: the chosen text is the same font at the same size
        // (T_Btn_02), as bold as the game's chosen Continue and Options, and no step in weight across the Select's fade)
        spread(text_spread::kGlow, kTitleGlow, f * show);
        const ImU32 ink_sel = ui::alpha(kTitleInkSel, text_spread::weight_alpha(f * show));
        for (int i = 0; i < text_spread::kTextWeight; i++) c.d->AddText(c.f.body, px, at, ink_sel, label);
    }
    // (the entry's hit: across the line as the host takes the game's (host/oot_menu.c list_boxes: 1100 wide), a pitch high)
    const float hw = ui::lu(c, 550 * k), hh = ui::lu(c, pitch * 0.5f);
    hits.add(m.x - hw, m.y - hh, m.x + hw, m.y + hh, menu_hit::kButton, title_entry);
    if (title_entry) return;
    mods_entry_px[0] = m.x - hw, mods_entry_px[1] = m.y - hh, mods_entry_px[2] = m.x + hw, mods_entry_px[3] = m.y + hh;
    mods_entry_px[4] = ui::lu(c, pitch);
}
/// (Triforce) Save Select on the title's list: the same entry a pitch under Mods, with its own animation
mods_entry::Anim files_title_anim;
void draw_title_files(ui::Ctx& c, bool sel, float cx, float cy, float k, float pitch) {
    std::swap(title_anim, files_title_anim);
    title_label = "Save Select", title_entry = 1;
    draw_title_mods(c, sel, cx, cy, k, pitch);
    title_label = "Mods", title_entry = 0;
    std::swap(title_anim, files_title_anim);
}

/// (Triforce) The Mods entry, under the game list's last button by the list's own pitch (host/oot_menu.c): on the pause menu's
/// System page a button as the game's own (PaCommonBtnThin: the plate with the curls, 672 x 144 units, its text 54; the
/// cursor round it when chosen, faded in and out as the part's Select and UnSelect: focus_anim.h), on the title as the list's
/// own entries are (draw_title_mods). c: the 16:9 column, where the layout's units are
void draw_mods_row(ui::Ctx& c, bool sel) {
    const float x0 = (float)mods_box[0].load(std::memory_order_relaxed), x1 = (float)mods_box[1].load(std::memory_order_relaxed);
    const float y0 = (float)mods_box[2].load(std::memory_order_relaxed), y1 = (float)mods_box[3].load(std::memory_order_relaxed);
    const float pitch = (float)mods_box[4].load(std::memory_order_relaxed);
    const float cx = (x0 + x1) * 0.5f, cy = (y0 + y1) * 0.5f - pitch;
    const bool title = (mods_list_bits.load(std::memory_order_relaxed) & HOS_MODS_LIST_TITLE) != 0;
    if (!title) {   // (Mods, then Quit under it by the list's own pitch: the game's own buttons)
        static const char* const names[2] = {"Mods", "Quit"};
        static const bool still = getenv("RX_VK_UI_STILL") != nullptr;   // (pictures that compare: as it stands)
        const int64_t now = prof_now();
        const int vtx_row = c.d->VtxBuffer.Size;
        for (int i = 0; i < 2; i++) {
            const float y = cy - pitch * i;
            const ImVec2 a = ui::at(c, cx - 336, y + 72), b = ui::at(c, cx + 336, y - 72);
            mods_focus[i].step(now, sel && mods_row_sel == i, !ease_live || still);
            ui::button(c, a, b, names[i], mods_focus[i].shown);
            hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, i);
            if (i == 0) mods_entry_px[0] = a.x, mods_entry_px[1] = a.y, mods_entry_px[2] = b.x, mods_entry_px[3] = b.y;
        }
        // ((Triforce, 11-20) Mods and Quit as much there as the game's own buttons above them are (mods_list_shown): they
        // come and go with the System page, not a frame before or after)
        if (const float list = mods_list_shown(); list >= 0 && list < 1)
            for (int v = vtx_row; v < c.d->VtxBuffer.Size; v++) c.d->VtxBuffer[v].col = ui::alpha(c.d->VtxBuffer[v].col, list);
        mods_entry_px[4] = ui::lu(c, pitch);
        return;
    }
    // (the list's scale: the part's 60-unit hit box as the host finds it; one not told, the part's own size)
    const float k = x1 - x0 > 6 && x1 - x0 < 600 ? (x1 - x0) / 60.0f : 1.0f;
    // ((Triforce) Save Select under it while the save files are on: the cursor is on one of the two)
    if (files_row_shown()) draw_title_files(c, sel && mods_row_sel == 1, cx, cy - pitch, k, pitch), sel = sel && mods_row_sel == 0;
    draw_title_mods(c, sel, cx, cy, k, pitch);
}

/// (the entry while the menu is shut: on the game's grid, where its list is (game_grid.h). (Triforce, 11-19) It was on a 16:9
/// column of the window's whole height: with the picture between bars at the top and the bottom (a 21:9 picture in a 16:9
/// window) it was larger than the list and under the picture)
void draw_mods_row_shut(ui::Ctx& c) {
    const game_grid::Place g = menu_grid(c.w, c.h);
    ui::Ctx k = grid_ctx(c, g);
    const int vtx0 = c.d->VtxBuffer.Size, cmd0 = c.d->CmdBuffer.Size;
    const ImVec4 window_clip = clip_now(c.d);
    const menu_hit::Map saved = hits;   // (its hit is not the menu's: the host takes clicks on it while the menu is shut)
    draw_mods_row(k, false);
    hits = saved;
    put_on_grid(c.d, vtx0, cmd0, game_grid::map_of(g), window_clip);
}

/// ((Triforce) 11-19) Quit's dialog, as the game's own system dialogs: the game dimmed, the question, its buttons on
/// PaCommonBtnThin's plate (as draw_ask), the chosen one with the game's cursor round it; A chooses, B is Cancel.
/// (11-19) It opens and closes as SystemWindow_00 (focus_anim.h): the question and the buttons rise into place and fade in
/// over the In's 20 frames, the dim fading with them; B or Cancel fades it all out over the Out's 2. Its buttons' cursor
/// fades in and out as the System list's buttons' do. Its dim the whole window's (menu_window_w x _h, in c's pixels through menu_map)
/// ((Triforce, 11-19) the lab's "the Quit banner text shows on top of the game's tab strip before the banner plate": it had a
/// banner (ui::banner, "Quit") of its own over the pause menu's header. SystemWindow_00 has none: its panes are N_In_00 (the
/// text and the three Pa_Button_*) under its RootPane, and its In curves N_In_00's alpha and height alone; the System page's
/// own header (the game's tab strip) stays under the dialog, dimmed with the rest. So no banner: the question, the buttons
/// and the dim, on N_In_00's one alpha)
void draw_quit_ask(ui::Ctx& c) {
    static const bool still = getenv("RX_VK_UI_STILL") != nullptr;   // (pictures that compare: open, as it stands)
    const bool settle = !ease_live || still;
    const int64_t now = prof_now();
    const focus_anim::Window w = settle ? focus_anim::Window{}
                               : quit_ask ? focus_anim::window_at(now - quit_open_ns) : focus_anim::window_at(now - quit_shut_ns, true);
    const int vtx0 = c.d->VtxBuffer.Size;
    // (the game behind dimmed as its own dialogs do it, deep enough that the Basic Controls panel's text does not show through:
    // the whole window, the picture's sides too; ((11-20) the bars beside or above the picture black under it: dim_window)
    dim_window(c.d, menu_map, menu_grid(menu_window_w, menu_window_h), menu_window_w, menu_window_h, ui::rgba(8, 5, 2, 220));
    const int vtx_in = c.d->VtxBuffer.Size;   // (from here N_In_00's: the question and the buttons)
    ui::text_mid_centre(c, c.f.body, ui::lu(c, 54 * ui::kType), c.w * 0.5f, ui::at(c, 0, 300).y, ui::kInk, "Quit the game?");
    ui::text_mid_centre(c, c.f.body, ui::lu(c, 52), c.w * 0.5f, ui::at(c, 0, 200).y, ui::kSoft, "Progress since your last save is lost.");
    const float bw = ui::lu(c, 336), bh = ui::lu(c, 72);
    static const char* const labels[3] = {"Quit Game", "Restart Game", "Cancel"};
    // ((Triforce, 11-19) while it is open or closing the mouse takes only its buttons: Mods and Quit under the dim are not
    // there for it (a second click on Quit's place, the dialog fading in, was A on its Quit Game))
    hits.clear(0, 0, c.w, c.h);
    for (int i = 0; i < 3; i++) {
        const float my = ui::at(c, 0, -10.0f - 188.0f * i).y;
        const ImVec2 a(c.w * 0.5f - bw, my - bh), b(c.w * 0.5f + bw, my + bh);
        quit_focus[i].step(now, i == quit_sel, settle || quit_fresh);
        ui::button(c, a, b, labels[i], quit_focus[i].shown);
        // (where it stands: no input is taken while it rises; while its Out plays none, it is going)
        if (quit_ask) hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 10 + i);
    }
    quit_fresh = false;
    // (no prompts of its own: the pause menu's Select and Back stay under it, and say the same)
    const float drop = ui::lu(c, w.drop);
    for (int i = vtx_in; drop > 0 && i < c.d->VtxBuffer.Size; i++) c.d->VtxBuffer[i].pos.y += drop;
    for (int i = vtx0; w.alpha < 1 && i < c.d->VtxBuffer.Size; i++) c.d->VtxBuffer[i].col = ui::alpha(c.d->VtxBuffer[i].col, w.alpha);
}

/// ((Triforce) 11-19) Quit Game / Restart Game: as the old Restart and Quit rows did, the settings and the pipeline cache kept first
void end_game(bool restart) {
    save();
    pipeline_cache_save(true);
    memory_trial_orderly_end();
    logf(restart ? "menu: Restart Game" : "menu: Quit Game");
    if (const HWND window = app_window()) PostMessageA(window, restart ? WM_APP + 9 : WM_CLOSE, 0, 0);
}

/// (Triforce) 11-18, his "if you can draw these in game style can you not do that for the achievements too?": the game's own
/// picture for an achievement's icon, where it has one (vk_game_tex.h takes them from his game's files when they are there):
/// a Spiritual Stone and a medallion by their colours, as the load list's plate has them (DataFileImportantIcon_00 to _08:
/// the stones of the forest, of fire, of water; the medallions of light, forest, fire, water, spirit, shadow); a song's icon
/// for a note; a Gold Skulltula's mark for a token, and a rupee for the green one. nullptr: none, the drawn icon
const char* ach_art_name(int icon) {
    namespace ar = achievement_rows;
    const int tone = ar::tone_of(icon);
    switch (ar::shape_of(icon)) {
    case ar::kGem:
        return tone == ar::kGreen ? "DataFileImportantIcon_00" : tone == ar::kRed ? "DataFileImportantIcon_01" : tone == ar::kBlue ? "DataFileImportantIcon_02" : nullptr;
    case ar::kMedal:
        return tone == ar::kYellow ? "DataFileImportantIcon_03" : tone == ar::kGreen ? "DataFileImportantIcon_04" : tone == ar::kRed ? "DataFileImportantIcon_05" :
               tone == ar::kBlue ? "DataFileImportantIcon_06" : tone == ar::kOrange ? "DataFileImportantIcon_07" : tone == ar::kPurple ? "DataFileImportantIcon_08" : nullptr;
    case ar::kNote: return "OcarinaMelodyIcon_00";
    case ar::kToken: return tone == ar::kGreen ? "RupeeIconNew_00" : "MapIconCollectSkullSign_00";
    }
    return nullptr;
}
/// (Triforce) An achievement's icon: the game's own picture of what it is about where there is one (ach_art_name), else
/// drawn: a dark disc with a ring, and on it one of achievement_rows.h's shapes in one of its tones. One not earned in grey.
/// m its middle, r its radius
void ach_icon(ui::Ctx& c, ImVec2 m, float r, int icon, bool earned) {
    namespace ar = achievement_rows;
    if (const char* const name = ach_art_name(icon)) {
        if (const ui::Art* t = ui::art(name)) {
            static const ImU32 tints[ar::kTones] = {ui::rgba(232, 184, 74),  ui::rgba(96, 196, 104),  ui::rgba(226, 92, 76),   ui::rgba(92, 158, 236),
                                                    ui::rgba(168, 112, 226), ui::rgba(238, 146, 62),  ui::rgba(246, 228, 128), ui::rgba(200, 208, 218)};
            // (a picture as it is, a mask in the icon's tone; one not earned dark and half there)
            const ImU32 col = !earned ? ui::rgba(96, 90, 78, 150) : t->mask ? tints[ar::tone_of(icon)] : IM_COL32_WHITE;
            const float hw = r * 1.2f, hh = hw * t->h / t->w;
            ui::image(c, t, ImVec2(m.x - hw, m.y - hh), ImVec2(m.x + hw, m.y + hh), col);
            return;
        }
    }
    static const ImU32 tones[ar::kTones] = {ui::rgba(232, 184, 74),  ui::rgba(96, 196, 104),  ui::rgba(226, 92, 76),   ui::rgba(92, 158, 236),
                                            ui::rgba(168, 112, 226), ui::rgba(238, 146, 62),  ui::rgba(246, 228, 128), ui::rgba(200, 208, 218)};
    const ImU32 tone = earned ? tones[ar::tone_of(icon)] : ui::rgba(112, 106, 92), dark = ui::rgba(20, 15, 9, 245);
    const ImU32 cut = ui::alpha(dark, 0.6f);   // (a line drawn on a shape: its facets)
    const float line = std::max(1.5f, r * 0.09f), g = r * 0.56f;
    c.d->AddCircleFilled(m, r, dark, 48);
    c.d->AddCircle(m, r - line * 0.5f, earned ? tone : ui::alpha(tone, 0.7f), 48, line);
    const auto p = [&](float x, float y) { return ImVec2(m.x + x * g, m.y + y * g); };   // (a place of the shape: -1 to 1 each way, y down)
    switch (ar::shape_of(icon)) {
    case ar::kSword: {   // (point up and to the right: the blade and its point, the guard across, the grip and its pommel)
        c.d->AddLine(p(-0.28f, 0.28f), p(0.62f, -0.62f), tone, g * 0.30f);
        c.d->AddTriangleFilled(p(0.50f, -0.74f), p(0.74f, -0.50f), p(0.96f, -0.96f), tone);
        c.d->AddLine(p(-0.72f, -0.10f), p(0.10f, 0.72f), tone, g * 0.20f);
        c.d->AddLine(p(-0.31f, 0.31f), p(-0.78f, 0.78f), tone, g * 0.18f);
        c.d->AddCircleFilled(p(-0.84f, 0.84f), g * 0.15f, tone, 16);
        break;
    }
    case ar::kGem: {
        const ImVec2 pts[] = {p(-0.55f, -0.80f), p(0.55f, -0.80f), p(0.95f, -0.22f), p(0, 0.95f), p(-0.95f, -0.22f)};
        c.d->AddConvexPolyFilled(pts, 5, tone);
        c.d->AddLine(p(-0.95f, -0.22f), p(0.95f, -0.22f), cut, line * 0.8f);
        c.d->AddLine(p(-0.38f, -0.22f), p(0, 0.95f), cut, line * 0.8f), c.d->AddLine(p(0.38f, -0.22f), p(0, 0.95f), cut, line * 0.8f);
        c.d->AddLine(p(-0.38f, -0.22f), p(-0.20f, -0.80f), cut, line * 0.8f), c.d->AddLine(p(0.38f, -0.22f), p(0.20f, -0.80f), cut, line * 0.8f);
        break;
    }
    case ar::kMedal:
        c.d->AddCircleFilled(m, g * 0.92f, tone, 32);
        c.d->AddCircle(m, g * 0.62f, cut, 32, line);
        ui::diamond(c, m, g * 0.26f, cut);
        break;
    case ar::kNote:   // (its head, its stem, its flag)
        c.d->AddCircleFilled(p(-0.28f, 0.55f), g * 0.36f, tone, 24);
        c.d->AddLine(p(0, 0.55f), p(0, -0.85f), tone, g * 0.17f);
        c.d->AddLine(p(0, -0.80f), p(0.62f, -0.42f), tone, g * 0.22f);
        c.d->AddLine(p(0.62f, -0.42f), p(0.46f, 0.02f), tone, g * 0.14f);
        break;
    case ar::kToken:
        c.d->AddCircle(m, g * 0.72f, tone, 32, g * 0.30f);
        c.d->AddCircleFilled(m, g * 0.22f, tone, 16);
        break;
    case ar::kShield: {
        const ImVec2 pts[] = {p(-0.78f, -0.85f), p(0.78f, -0.85f), p(0.78f, 0.05f), p(0, 0.95f), p(-0.78f, 0.05f)};
        c.d->AddConvexPolyFilled(pts, 5, tone);
        c.d->AddLine(p(0, -0.85f), p(0, 0.95f), cut, line), c.d->AddLine(p(-0.78f, -0.25f), p(0.78f, -0.25f), cut, line);
        break;
    }
    default: {   // (a star: its five points about a pentagon)
        ImVec2 in[5], out[5];
        for (int i = 0; i < 5; i++) {
            const float a = -1.5707963f + i * 1.2566371f, h = a + 0.6283185f;
            out[i] = p(cosf(a), sinf(a)), in[i] = p(0.42f * cosf(h), 0.42f * sinf(h));
        }
        c.d->AddConvexPolyFilled(in, 5, tone);
        for (int i = 0; i < 5; i++) c.d->AddTriangleFilled(in[(i + 4) % 5], out[i], in[i], tone);
    }
    }
}

/// (Triforce) The Achievements page (kAchPage): a card for each the host named, its icon, its name and whether it is earned,
/// in pages; the chosen one's line about it in the caption. Nothing is set here: they are earned in the game
void draw_achievements(ui::Ctx& c) {
    const float s = c.s;
    const int n = ach_list.shown();
    char count_text[48];
    snprintf(count_text, sizeof count_text, "%d of %d earned", ach_list.earned_count(), n);
    const float hh = title_banner(c, "Achievements", count_text);
    const ui::Prompt prompts[] = {{ui::kUpDown, "Move"}, {ui::kLeftRight, "Move"}, {ui::kTabs, "Page"}, {ui::kBack, "Back"}};
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const float bar = ui::prompt_bar_top(c);
    const float left = cx0 + 24 * s, right = cx1 - 24 * s, gap = 10 * s;
    const float top = hh + 22 * s, pitch = 74 * s;
    const float strip = 58 * s, detail = bar - 14 * s - strip, grid_bottom = std::max(top, detail - 8 * s);
    ach_columns = right - left >= 620 * s ? 2 : 1;
    ach_capacity = ach_columns * std::max(1, (int)((grid_bottom - top + gap) / pitch));
    ach_view.keep(n, ach_capacity);
    const int choice = ach_view.choice;
    if (n > 0) {
        const bool got = ach_list.is_earned(choice);
        char when[48] = "Earned";
        if (got && ach_list.days[choice][0]) snprintf(when, sizeof when, "Earned on %s", ach_list.days[choice]);
        caption(c, hx0, hx1, ach_list.names[choice], ach_list.abouts[choice][0] ? ach_list.abouts[choice] : nullptr,
                got ? nullptr : "Not earned yet.", got ? when : nullptr);
    }
    const int first = ach_view.page * ach_capacity, last = std::min(n, first + ach_capacity);
    const float width = (right - left + gap) / ach_columns;
    c.d->PushClipRect(ImVec2(left - 12 * s, top - 12 * s), ImVec2(right + 12 * s, grid_bottom + 12 * s));
    for (int i = first; i < last; ++i) {
        const int cell = i - first;
        const ImVec2 a(left + (cell % ach_columns) * width, top + (cell / ach_columns) * pitch);
        const ImVec2 b(a.x + width - gap, a.y + pitch - gap);
        const bool earned = ach_list.is_earned(i);
        ui::plate(c, a, b, earned);
        const float r = 23 * s, tx = a.x + 14 * s + 2 * r + 13 * s;
        ach_icon(c, ImVec2(a.x + 14 * s + r, (a.y + b.y) * 0.5f), r, ach_list.icons[i], earned);
        c.d->PushClipRect(ImVec2(tx, a.y), b - ImVec2(8 * s, 0), true);
        ui::text_mid(c, c.f.strong, 15.5f * s, tx, a.y + 21 * s, earned ? ui::kInkBright : ui::kSoft, ach_list.names[i]);
        char line[40] = "Locked";
        if (earned && ach_list.days[i][0]) snprintf(line, sizeof line, "Earned %s", ach_list.days[i]);
        else if (earned) snprintf(line, sizeof line, "Earned");
        ui::text_mid(c, c.f.body, 14 * s, tx, a.y + 43 * s, earned ? ui::kAccent : kCardOff, line);
        c.d->PopClipRect();
        if (i == choice) ui::glow(c, a, b);
        if (a.y < grid_bottom) hits.add(a.x, a.y, b.x, std::min(b.y, grid_bottom), menu_hit::kListLine, i);
    }
    c.d->PopClipRect();
    if (detail >= top && n > 0) {   // (the page: its arrows, Page n of m and the range, as the Inventory's)
        c.d->AddLine(ImVec2(left, detail), ImVec2(right, detail), ui::alpha(ui::kEdge, 0.8f));
        const int pages = achievement_rows::View::pages(n, ach_capacity), at = ach_view.page;
        const float my = detail + strip * 0.5f + 2 * s, side = 32 * s;
        float px0 = left;
        if (pages > 1) {
            page_arrow(c, ImVec2(px0, my - side * 0.5f), side, 0, at > 0);
            hits.add(px0, my - side * 0.5f, px0 + side, my + side * 0.5f, menu_hit::kButton, 2);
            char page_text[32];
            snprintf(page_text, sizeof page_text, "Page %d of %d", at + 1, pages);
            const float tw = ui::size_of(c.f.strong, 17 * s, page_text).x;
            ui::text_mid(c, c.f.strong, 17 * s, px0 + side + 12 * s, my, ui::kInkBright, page_text);
            const float nx = px0 + side + 24 * s + tw;
            page_arrow(c, ImVec2(nx, my - side * 0.5f), side, 1, at + 1 < pages);
            hits.add(nx, my - side * 0.5f, nx + side, my + side * 0.5f, menu_hit::kButton, 3);
            px0 = nx + side + 18 * s;
        }
        char range[64];
        snprintf(range, sizeof range, "%d\xe2\x80\x93%d of %d", first + 1, last, n);
        ui::text_mid(c, c.f.body, 15 * s, px0, my, ui::kSoft, range);
    }
    ui::prompt_bar(c, prompts, (int)(sizeof prompts / sizeof prompts[0]));
}

/// (Triforce) A save file's picture and time on its card: those of its newest save, as the game's own load list shows them.
/// Each of the file's slots has a caption file (the host names where they are: host/save_files.c), in which the game keeps
/// the save's picture, a JPEG, and when it was made. Looked for once a run, when the file select first opens: every slot's
/// caption read whole, its time found (save_file_rows.h caption_time), and of the one saved last the JPEG (jpeg_in) decoded
/// with Windows' own decoder (vk_mods.h: none on Linux, and no picture then); its texture made at the first drawing. The
/// saves are only read. A file none of whose slots tells a time shows its first slot's picture and the folder's date
struct FilePicture {
    int state = 0;   // (0 not looked for, 1 its pixels wait for their texture, 2 shown, 3 none)
    std::vector<unsigned char> rgba;
    int w = 0, h = 0;
    ImTextureData* texture = nullptr;
    char when[32] = "";   // (the newest save's own time, as the game writes one; "" not found: the host's, the folder's date)
};
FilePicture file_pictures[save_file_rows::kSlots];
void files_pictures_load() {
    for (int i = 0, n = save_files.shown(); i < n; i++) {
        FilePicture& p = file_pictures[i];
        if (p.state) continue;
        p.state = 3;
        if (!save_files.pictures[i][0]) continue;
        std::string newest;   // (the newest save's picture, as it is in its caption)
        save_file_rows::SaveTime latest;
        int from = -1, slots = 0;
        // ((Triforce) 11-18, his picture: "the date doesn't match lol neither does the picture": a time of 2093 was found among
        // a caption's other bytes. The slot the game saved in last is known where the file was played with this: the host saw
        // it written and kept it with the card (host/save_files.c hos_save_card_wrote). That slot's picture and that time,
        // then; a file not saved in since: the latest time a caption tells that can be a save's, 2025 to now, as before)
        const int known = save_files.slots[i];
        const time_t now = time(nullptr) + 86400;
        const tm* const now_tm = localtime(&now);
        const int max_year = now_tm ? now_tm->tm_year + 1900 : 2100;
        for (int slot = 0; slot < 12; slot++) {   // (the game looks for slot_00 to slot_11)
            if (known >= 0 && slot != known) continue;
            char path[save_file_rows::kPath + 32];
            // (the folder's own separator: host/save_files.c writes the start of the path with '/' on Linux, where fopen
            // takes no '\')
            snprintf(path, sizeof path, "%s%02d%ccaption.sav", save_files.pictures[i], slot, strchr(save_files.pictures[i], '\\') ? '\\' : '/');
            FILE* f = fopen(path, "rb");
            if (!f) continue;
            std::string bytes(size_t(1) << 20, '\0');   // (a save's caption is some tens of kilobytes)
            bytes.resize(fread(bytes.data(), 1, bytes.size(), f));
            fclose(f);
            slots++;
            size_t at = 0, len = 0;
            const bool pictured = save_file_rows::jpeg_in((const unsigned char*)bytes.data(), bytes.size(), &at, &len);
            const save_file_rows::SaveTime t =
                save_file_rows::caption_time((const unsigned char*)bytes.data(), bytes.size(), pictured ? at : bytes.size(), pictured ? len : 0, max_year,
                                             (int64_t)now);
            if (from >= 0 && !t.after(latest)) continue;   // (the first slot, until one tells a later time)
            from = slot, latest = t;
            newest = pictured ? bytes.substr(at, len) : std::string();
        }
        if (from < 0) continue;
        if (known >= 0) snprintf(p.when, sizeof p.when, "%s", save_files.made[i]);
        else if (latest.kind == 1) save_file_rows::game_time(p.when, sizeof p.when, latest.year, latest.month, latest.day, latest.hour, latest.minute);
        else if (latest.kind == 2) {
            const time_t made = (time_t)latest.seconds;
            if (const tm* local = localtime(&made))
                save_file_rows::game_time(p.when, sizeof p.when, local->tm_year + 1900, local->tm_mon + 1, local->tm_mday, local->tm_hour, local->tm_min);
        }
        if (known >= 0) logf("menu: save file %d: slot_%02d is the one the game saved in last, %s (kept with its card)", i + 1, from, p.when);
        else
            logf("menu: save file %d: of its %d slots slot_%02d is the newest%s%s%s", i + 1, slots, from,
                 latest.kind ? ", saved " : ": none of them tells when it was saved (its first slot is shown, and the folder's date)", p.when,
                 latest.kind == 1 ? " (a calendar time in its caption)" : latest.kind == 2 ? " (a count of seconds in its caption)" : "");
        if (newest.empty()) {
            logf("menu: save file %d: no picture found in that save", i + 1);
            continue;
        }
        if (mods::decode_image(newest, 512, p.rgba, &p.w, &p.h) && p.w > 0 && p.h > 0 && p.rgba.size() == (size_t)p.w * p.h * 4) p.state = 1;
        else logf("menu: save file %d: its save's picture could not be read (%zu bytes of it)", i + 1, newest.size());
    }
}/// The file select opened: the choice on the file this run plays
void files_open(bool at_title) {
    page = kFilesPage, files_at_title = at_title, files_wait = -1, files_failed = false;
    files_choice = std::max(0, save_files.current());
    files_pictures_load();
}
/// (Triforce) The file select (kFilesPage): a card for each file the host named, its number, its name and when it was last
/// saved; the one this run plays is marked. The caption says what choosing the chosen one does
void draw_files(ui::Ctx& c) {
    const float s = c.s;
    const int n = save_files.shown(), cur = save_files.current();
    files_choice = std::clamp(files_choice, 0, std::max(0, n - 1));
    const bool here = files_choice == cur, waiting = files_wait >= 0;
    const float hh = title_banner(c, "Select a file", nullptr);
    const char* act = here ? "Play" : "Switch file";
    const ui::Prompt prompts[] = {{ui::kUpDown, "Move"}, {ui::kConfirm, act}, {ui::kBack, "Back"}};
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const float bar = ui::prompt_bar_top(c);
    const float left = cx0 + 24 * s, right = cx1 - 24 * s, top = hh + 22 * s, pitch = 124 * s;
    if (n > 0) {
        const bool saved = save_files.saved(files_choice);
        char when[64] = "No save in it yet.";
        const char* const made = file_pictures[files_choice].when[0] ? file_pictures[files_choice].when : save_files.whens[files_choice];
        if (saved && made[0]) snprintf(when, sizeof when, "Last saved %s", made);
        else if (saved) snprintf(when, sizeof when, "Has a save.");
        const char* help = here ? "The file the game is playing now. Its saves and autosaves are its own." :
                           saved ? "Another file, with its own saves and autosaves. The game starts again to play it: what is not saved in "
                                   "the file you are playing now is lost." :
                                   "An empty file: a new game of its own. The game starts again to play it.";
        caption(c, hx0, hx1, save_files.names[files_choice], help, when,
                waiting ? "Starting the game on this file..." : files_failed ? "The choice could not be kept: nothing changed." : nullptr);
    }
    for (int i = 0; i < n; ++i) {
        const ImVec2 a(left, top + i * pitch), b(right, a.y + pitch - 12 * s);
        const bool saved = save_files.saved(i);
        ui::plate(c, a, b, i == cur);
        const float my = (a.y + b.y) * 0.5f;
        // (its save's picture at the left, 16:9; a file without one: a dark plate that says so)
        const float ph = b.y - a.y - 20 * s, pw = ph * 16.0f / 9.0f;
        const ImVec2 pa(a.x + 12 * s, a.y + 10 * s), pb(pa.x + pw, pa.y + ph);
        FilePicture& pic = file_pictures[i];
        if (pic.state == 1) {   // (its texture, at the first drawing)
            pic.texture = IM_NEW(ImTextureData)();
            pic.texture->Create(ImTextureFormat_RGBA32, pic.w, pic.h);
            memcpy(pic.texture->GetPixels(), pic.rgba.data(), pic.rgba.size());
            pic.texture->UseColors = true;
            ImGui::RegisterUserTexture(pic.texture);
            pic.rgba.clear(), pic.rgba.shrink_to_fit();
            pic.state = 2;
        }
        c.d->AddRectFilled(pa, pb, ui::rgba(18, 13, 8, 255));
        if (pic.state == 2 && pic.texture) {
            const float iw = (float)pic.w, ih = (float)pic.h;
            ImVec2 uv0(0, 0), uv1(1, 1);
            if (iw / ih > pw / ph) { const float k = (ph / pw) * iw / ih; uv0.x = (1 - 1 / k) * 0.5f, uv1.x = 1 - uv0.x; }   // (wider: its sides cut)
            else { const float k = (pw / ph) * ih / iw; uv0.y = (1 - 1 / k) * 0.5f, uv1.y = 1 - uv0.y; }
            c.d->AddImage(pic.texture->GetTexRef(), pa, pb, uv0, uv1);
        } else {
            ui::text_mid_centre(c, c.f.body, 13 * s, (pa.x + pb.x) * 0.5f, my, ui::kDim, saved ? "No picture" : "New game");
        }
        c.d->AddRect(pa, pb, ui::alpha(ui::kEdge, 0.9f), 0, std::max(1.0f, s));
        // (Triforce, 11-18, his picture of the game's own load list: "can we show progress of the latest autosave like this?")
        // The card as the game's: the save's time over the place it was played last, a line, the hearts under it, and at the
        // right the plate with the six medallions round the three Spiritual Stones, each in its place when held. The file's
        // name on the tag where the game says Autosave. What the host kept as the file was played (host/save_files.h
        // SaveCard): a file not played with this yet has its name and its time alone
        namespace ar = achievement_rows;
        const bool carded = saved && (save_files.places[i][0] || save_files.items[i] || save_files.hearts[i]);
        const float R = 44 * s, tx = pb.x + 18 * s;
        const ImVec2 wc(b.x - 18 * s - R, my);
        const float text_right = carded ? wc.x - R - 16 * s : b.x - 16 * s;
        {   // (the tag: the file's name; the one this run plays in gold, "Playing" before it)
            const float tw = ui::size_of(c.f.strong, 13.5f * s, save_files.names[i]).x + 22 * s;
            const ImVec2 g(text_right - tw, a.y + 10 * s);
            c.d->AddRectFilled(g, g + ImVec2(tw, 23 * s), i == cur ? ui::kAccent : ui::alpha(ui::kAccent, 0.45f), 4 * s);
            ui::text_mid_centre(c, c.f.strong, 13.5f * s, g.x + tw * 0.5f, g.y + 11.5f * s, ui::kGoldInk, save_files.names[i]);
            if (i == cur) ui::text_mid_right(c, c.f.strong, 13.5f * s, g.x - 10 * s, g.y + 11.5f * s, ui::kGoldHi, "Playing");
        }
        c.d->PushClipRect(ImVec2(tx, a.y), ImVec2(text_right, b.y), true);
        ui::text_mid(c, c.f.body, 15 * s, tx, a.y + 21 * s, saved ? ui::kSoft : kCardOff,
                     saved ? (pic.when[0] ? pic.when : save_files.whens[i][0] ? save_files.whens[i] : "Saved") : "No save yet");
        const char* const place = !saved ? "New game" : save_files.places[i][0] ? save_files.places[i] : "Saved game";
        ui::text_mid(c, c.f.strong, 23 * s, tx, a.y + 50 * s, saved ? ui::kInkBright : ui::kSoft, place);
        c.d->PopClipRect();
        c.d->AddLine(ImVec2(tx, a.y + 71 * s), ImVec2(text_right, a.y + 71 * s), ui::alpha(ui::kEdge, 0.7f), std::max(1.0f, s));
        for (int k = 0, hearts = carded ? save_files.hearts[i] : 0; k < hearts; k++) {   // (a heart: two lobes over a point)
            const float w = 15 * s, hx = tx + w * 0.5f + k * (w + 4 * s), hy = a.y + 90 * s;
            if (hx + w * 0.5f > text_right) break;
            if (const ui::Art* heart = ui::art("HeartBase_00")) {   // (the game's own heart: its base in its red, its frame over it)
                // ((Triforce) 11-18, his picture: the hearts were small and grey. The game's heart is a pale picture in the middle
                // of a square of margin, which its layout colours and draws larger than its slot: twice the slot's width here,
                // a slot apart, the base in the load list's red-orange and the frame's line over it a shade lighter)
                const float slot_w = 21 * s, hw = slot_w * 2.1f, hh2 = hw * heart->h / heart->w, mx = tx + slot_w * 0.5f + k * slot_w;
                if (mx + slot_w * 0.5f > text_right) break;
                const ImVec2 ha(mx - hw * 0.5f, hy - hh2 * 0.5f), hb(mx + hw * 0.5f, hy + hh2 * 0.5f);
                // ((Triforce) 11-18, his next picture: the frame came out right, an orange outline, but the heart inside it dark
                // brown. HeartBase_00 is the heart's dark ground, not its red: the game lays the fill over it from other layers.
                // The fill is drawn here, in the load list's red-orange with a lighter upper half, inside the game's own frame)
                (void)heart;
                const float fw = slot_w * 0.80f, fy = hy - fw * 0.02f;
                const ImU32 fill = ui::rgba(238, 92, 48), lit = ui::rgba(250, 128, 70);
                c.d->AddCircleFilled(ImVec2(mx - fw * 0.24f, fy - fw * 0.13f), fw * 0.27f, fill, 20);
                c.d->AddCircleFilled(ImVec2(mx + fw * 0.24f, fy - fw * 0.13f), fw * 0.27f, fill, 20);
                c.d->AddTriangleFilled(ImVec2(mx - fw * 0.49f, fy - fw * 0.02f), ImVec2(mx + fw * 0.49f, fy - fw * 0.02f), ImVec2(mx, fy + fw * 0.50f), fill);
                c.d->AddCircleFilled(ImVec2(mx - fw * 0.24f, fy - fw * 0.17f), fw * 0.15f, lit, 16);
                c.d->AddCircleFilled(ImVec2(mx + fw * 0.24f, fy - fw * 0.17f), fw * 0.15f, lit, 16);
                if (const ui::Art* frame = ui::art("HeartFrame_00")) ui::image(c, frame, ha, hb, ui::rgba(255, 150, 96));
                continue;
            }
            const ImU32 red = ui::rgba(236, 86, 52), rim = ui::rgba(140, 34, 22);
            c.d->AddCircleFilled(ImVec2(hx - w * 0.25f, hy - w * 0.14f), w * 0.31f, rim, 16), c.d->AddCircleFilled(ImVec2(hx + w * 0.25f, hy - w * 0.14f), w * 0.31f, rim, 16);
            c.d->AddTriangleFilled(ImVec2(hx - w * 0.55f, hy + w * 0.02f), ImVec2(hx + w * 0.55f, hy + w * 0.02f), ImVec2(hx, hy + w * 0.60f), rim);
            c.d->AddCircleFilled(ImVec2(hx - w * 0.25f, hy - w * 0.14f), w * 0.25f, red, 16), c.d->AddCircleFilled(ImVec2(hx + w * 0.25f, hy - w * 0.14f), w * 0.25f, red, 16);
            c.d->AddTriangleFilled(ImVec2(hx - w * 0.46f, hy + w * 0.01f), ImVec2(hx + w * 0.46f, hy + w * 0.01f), ImVec2(hx, hy + w * 0.50f), red);
            c.d->AddCircleFilled(ImVec2(hx - w * 0.28f, hy - w * 0.20f), w * 0.08f, ui::rgba(255, 190, 160, 200), 8);
        }
        if (carded) {   // (the plate: the medallions of light, forest, fire, water, spirit and shadow round it from the top, the stones in its middle)
            static const int medal_tones[save_file_rows::kMedals] = {ar::kYellow, ar::kGreen, ar::kRed, ar::kBlue, ar::kOrange, ar::kPurple};
            static const int stone_tones[save_file_rows::kStones] = {ar::kGreen, ar::kRed, ar::kBlue};
            // (the game's own pictures of them, DataFileImportantIcon_00 to _08, when its archive gave them. kFileIcon: the
            // picture's number for each of the items' bits. The stones first (forest, fire, water), then the medallions as the
            // plate has them round it from the top: light, forest, fire, water, spirit, shadow. (11-18: taken first to be in
            // gpu/vk/oot_cheat_items.h's order, light last: his card had Shadow's picture where Light is held and Light's where
            // Forest is. _03 is Light, then, and the six go round the plate; _08, Shadow's, was drawn for Light))
            static const int kFileIcon[save_file_rows::kStones + save_file_rows::kMedals] = {0, 1, 2, 3, 4, 5, 6, 7, 8};
            const auto game_icon = [&](int bit, ImVec2 m, float r) {
                char name[32];
                snprintf(name, sizeof name, "DataFileImportantIcon_%02d", kFileIcon[bit]);
                const ui::Art* t = ui::art(name);
                if (!t || t->mask) return false;   // (a mask is a shape without its colours: the drawn icon then)
                const float hw = r * 1.45f, hh2 = hw * t->h / t->w;
                ui::image(c, t, ImVec2(m.x - hw, m.y - hh2), ImVec2(m.x + hw, m.y + hh2));
                return true;
            };
            const ImU32 socket = ui::rgba(30, 22, 12, 230);
            c.d->AddNgonFilled(wc, R, ui::rgba(74, 56, 30, 240), 6);
            c.d->AddNgon(wc, R, ui::alpha(ui::kEdge, 0.9f), 6, std::max(1.0f, 1.3f * s));
            for (int k = 0; k < save_file_rows::kMedals; k++) {
                const float ang = -1.5707963f + k * 1.0471976f, r = R * 0.19f;
                const ImVec2 m(wc.x + std::cos(ang) * R * 0.66f, wc.y + std::sin(ang) * R * 0.66f);
                if (!(save_files.items[i] >> (save_file_rows::kStones + k) & 1)) c.d->AddCircleFilled(m, r, socket, 24);
                else if (game_icon(save_file_rows::kStones + k, m, r)) {}
                else ach_icon(c, m, r, ar::kMedal | medal_tones[k] << 4, true);
            }
            for (int k = 0; k < save_file_rows::kStones; k++) {
                const float r = R * 0.17f;
                const ImVec2 m(wc.x + (k - 1) * R * 0.36f, wc.y);
                if (!(save_files.items[i] >> k & 1)) c.d->AddCircleFilled(m, r, socket, 24);
                else if (game_icon(k, m, r)) {}
                else ach_icon(c, m, r, ar::kGem | stone_tones[k] << 4, true);
            }
        }
        if (i == files_choice) ui::glow(c, a, b);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kListLine, i);
    }
    if (n > 0 && !waiting) {   // (the chosen file's action, for the mouse)
        const float my = bar - 14 * s - 29 * s, bw = ui::size_of(c.f.strong, 18 * s, "Switch file").x + 36 * s;
        const ImVec2 a(right - bw, my - 17 * s), b(right, my + 17 * s);
        ui::button(c, a, b, act, false);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 0);
    }
    ui::prompt_bar(c, prompts, (int)(sizeof prompts / sizeof prompts[0]));
}

/// (Triforce) The notice of an achievement earned: a plate at the top of the screen, its icon, "Achievement earned" and its
/// name, slid in from above and out again (achievement_rows.h notice_in). Over the game and over the options alike.
/// ((Triforce) 11-23: and under the name where the list is, kAchWhere: the moment a player wants to know)
constexpr char kAchWhere[] = "See all: Options > System";
void draw_ach_notice(ui::Ctx& c) {
    const int slot = ach_notice;
    if (slot < 0 || slot >= ach_list.shown()) return;
    const float k = achievement_rows::notice_in((prof_now() - ach_notice_at) / 1000000, kAchNoticeMs);
    if (k <= 0) return;
    const float s = c.s, in = 1 - (1 - k) * (1 - k), r = 26 * s, pad = 16 * s;
    const float text_w = std::max({ui::size_of(c.f.strong, 21 * s, ach_list.names[slot]).x, ui::size_of(c.f.strong, 13.5f * s, "Achievement earned").x,
                                   ui::size_of(c.f.body, 12 * s, kAchWhere).x});
    const float w = pad + 2 * r + 16 * s + text_w + 28 * s, h = 94 * s;
    const ImVec2 a((c.w - w) * 0.5f, -h + (h + 34 * s) * in), b(a.x + w, a.y + h);
    // ((Triforce) 11-18: the game's own plate, as the file select's cards and the Achievements page's, with a gold rim; it was a
    // dark rounded box of the menu's own)
    ui::plate(c, a, b, true);
    c.d->AddRect(a, b, ui::alpha(ui::kGoldHi, 0.9f), 0, 0, std::max(1.5f, 1.6f * s));
    ach_icon(c, ImVec2(a.x + pad + r, (a.y + b.y) * 0.5f), r, ach_list.icons[slot], true);
    const float tx = a.x + pad + 2 * r + 16 * s;
    ui::text_mid(c, c.f.strong, 13.5f * s, tx, a.y + 25 * s, ui::kGoldHi, "Achievement earned");
    ui::text_mid(c, c.f.strong, 21 * s, tx, a.y + 51 * s, ui::kInkBright, ach_list.names[slot]);
    ui::text_mid(c, c.f.body, 12 * s, tx, a.y + 75 * s, ui::kSoft, kAchWhere);
}

void draw_ask(ui::Ctx& c) {
    const float s = c.s;
    dim_page(c, ui::rgba(8, 5, 2, 110));   // (the dialog over the page: darker still; the whole window, the Full panel with it)
    ui::banner(c, 0, "Restart Needed");
    const std::string ask = i18n::tr("Restart to apply ") + restart_list_shown(i18n::tr(" and ")) + "?";   // ((Triforce) translated)
    const float wrap = ui::lu(c, 1440), px = ui::lu(c, 54 * ui::kType);
    const float th = ui::para(c, c.f.body, px, ImVec2(), 0, ask.c_str(), wrap, false);
    float y = ui::at(c, 0, 250).y - th * 0.5f;
    {   // (each line centred, as the game's dialogs set their text)
        const char* t = ask.c_str();
        const char* end = t + ask.size();
        while (t < end) {
            const char* cut = c.f.body->CalcWordWrapPosition(px, t, end, wrap);
            if (cut == t) cut = t + 1;
            const float lw = c.f.body->CalcTextSizeA(px, FLT_MAX, 0, t, cut).x;
            c.d->AddText(c.f.body, px, ImVec2(c.w * 0.5f - lw * 0.5f, y), ui::kInk, t, cut);
            y += px * 1.3f;
            t = cut;
            while (t < end && (*t == ' ' || *t == '\n')) t++;
        }
    }
    ui::text_mid_centre(c, c.f.body, ui::lu(c, 52), c.w * 0.5f, y + 16 * s, ui::kSoft, "Progress since your last save is lost.");
    // (SystemWindow_00's buttons: PaCommonBtnThin's plate, 684 x 156 units, 188 apart; the upper one acts, the lower one backs out)
    const float bw = ui::lu(c, 336), bh = ui::lu(c, 72);
    const char* labels[2] = {"Later", "Restart Now"};
    for (int i = 0; i < 2; i++) {
        const float my = ui::at(c, 0, i ? -330.0f : -518.0f).y;
        const ImVec2 a(c.w * 0.5f - bw, my - bh), b(c.w * 0.5f + bw, my + bh);
        ui::button(c, a, b, labels[i], i == ask_sel);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, i);
    }
    const ui::Prompt prompt_list[] = {{ui::kConfirm, "Confirm"}, {ui::kBack, "Later"}};
    ui::prompt_bar(c, prompt_list, 2);
}

void draw_menu(ui::Ctx& c, bool perf_under = false);
void draw_perf(ui::Ctx& c);
// ((Triforce VR) where the Full panel was drawn this frame, window pixels {x, y, w, h}; width 0: not drawn. vk_xr.cpp lifts it
// onto the HUD's panel: menu_perf_rect)
float perf_rect[4];
/// The menu's text sizes at this window's unit (and, with Menu size Auto, at the other size Auto can pick), baked ahead by
/// vk_imgui.cpp a few a frame: the first open then draws with no glyphs to make (it took 2.6 ms at 1080p)
float prebaked[4] = {0, 0, 0, 0};   // (the units and the width prebake last did; (Triforce) and the Full panel's text size, 0 off)
/// The menu's units now (with Auto, both it can pick) for a window w x h: whether prebake has not done them yet
/// ((Triforce, 11-19) the height the pages are drawn at: the game's grid's while its Options screen shows, where our tabs open
/// (draw_menu: pages_column), else the window's)
float pages_h(float w, float h) { return pages_on_game() ? pages_column(w, h, true).h : h; }
bool prebake_needed(uint32_t w, uint32_t h) {
    float m = 0;
    const float ph = pages_h((float)w, (float)h);
    const float u0 = ui::unit(ph, opts.menu_size, opts.fullscreen != 0, auto_pad, &m);
    const float u1 = opts.menu_size == 0 ? ui::unit(ph, 0, opts.fullscreen != 0, !auto_pad, &m) : u0;
    return u0 != prebaked[0] || u1 != prebaked[1] || (float)w != prebaked[2];
}
/// (Triforce) The Full panel's glyphs at its one text size px, in the font draw_perf writes with, baked now: ui::prebake only
/// queues a size for the next begin (vk_imgui.cpp bake_some), which bakes printable ASCII alone, never the temperatures'
/// degree sign, so the panel's first frame at a new size would make its glyphs while it draws. Again for a new size (a
/// resize, a new DPI) or a new font (the game's, once read from the player's files); px 0: off, the next Full bakes anew
void bake_perf(const ui::Ctx& c, float px) {
    static const ImFont* done_font = nullptr;
    static float done_px = 0;
    ImFont* font = c.f.body ? c.f.body : c.f.strong;   // (draw_perf's)
    if (px <= 0) done_px = 0;
    if (px <= 0 || !font || (font == done_font && px == done_px)) return;
    done_font = font, done_px = px;
    ImFontBaked* b = font->GetFontBaked(px);
    for (ImWchar ch = 32; ch < 127; ch++) b->FindGlyph(ch);
    b->FindGlyph(0x00B0);   // (U+00B0: the temperatures' degree sign)
}
void prebake(const ui::Ctx& c) {
    float units[2] = {c.s, c.s}, margins[2] = {c.safe, c.safe};
    const float ph = pages_h(c.w, c.h);   // ((Triforce, 11-19) the game's grid's inside its Options screen)
    if (ph != c.h) units[0] = units[1] = ui::unit(ph, opts.menu_size, opts.fullscreen != 0, auto_pad, &margins[0]), margins[1] = margins[0];
    if (opts.menu_size == 0) units[1] = ui::unit(ph, 0, opts.fullscreen != 0, !auto_pad, &margins[1]);
    // ((Triforce) the Full panel's one text size, as draw_perf sizes it, while the row is on Full: baked here at once when it
    // changes (bake_perf), before draw_perf in the same frame, and kept by ui::prebake with the menu's sizes. Its first
    // frame, and one after a resize, then make no glyphs while drawing)
    const float perf = opts.show_fps == 2 ? perf_px(perf_scale(c.w, c.h)) : 0;
    bake_perf(c, perf);
    if (units[0] == prebaked[0] && units[1] == prebaked[1] && c.w == prebaked[2] && perf == prebaked[3]) return;
    prebaked[0] = units[0], prebaked[1] = units[1], prebaked[2] = c.w, prebaked[3] = perf;
    static const float points[] = {12, 12.5f, 13, 13.6f, 14, 14.28f, 14.5f, 15, 15.5f, 16, 16.5f, 17, 18, 18.5f, 19, 20, 21, 23, 24};
    constexpr int n = sizeof points / sizeof points[0];
    float px[2 * n + 1];
    for (int u = 0; u < 2; u++)
        for (int i = 0; i < n; i++) px[u * n + i] = points[i] * units[u];
    int baked = units[1] == units[0] ? n : 2 * n;
    if (perf > 0) px[baked++] = perf;
    ui::prebake(px, baked);
    if (open_now.load(std::memory_order_relaxed)) return;
    // (and the page itself drawn once into a list of its own, thrown away: what the first open would measure and bake (the
    // help's height over every row, the exact sizes) done now, the menu's state as it was)
    const menu_hit::Map saved_hits = hits;
    const int saved_marquee = marquee_max;
    const int saved_tele[2] = {teleport_columns, teleport_page_rows}, saved_inv[3] = {inventory_columns, inventory_capacity, inventory_page};
    const float saved_tele_px[2] = {teleport_scroll_px, teleport_want_px};
    const float saved_ease = ease_step;
    float saved_scroll[sizeof scroll_at / sizeof *scroll_at], saved_want[sizeof scroll_at / sizeof *scroll_at];
    int saved_to[sizeof scroll_at / sizeof *scroll_at];   // (the scratch drawing's scroll, given back: the next is the menu's)
    memcpy(saved_scroll, scroll_at, sizeof scroll_at);
    memcpy(saved_want, scroll_want, sizeof scroll_want);
    memcpy(saved_to, scrolled_to, sizeof scrolled_to);
    ImDrawList scratch(ImGui::GetDrawListSharedData());
    scratch._ResetForNewFrame();
    scratch.PushTexture(ImGui::GetIO().Fonts->TexRef);
    scratch.PushClipRectFullScreen();
    ease_step = 0;
    for (int u = 0; u < (units[1] == units[0] ? 1 : 2); u++) {
        ui::Ctx dry = c;
        dry.d = &scratch;
        dry.s = units[u], dry.safe = margins[u];
        draw_menu(dry);
    }
    hits = saved_hits, marquee_max = saved_marquee, ease_step = saved_ease;
    teleport_columns = saved_tele[0], teleport_page_rows = saved_tele[1], teleport_scroll_px = saved_tele_px[0], teleport_want_px = saved_tele_px[1];
    inventory_columns = saved_inv[0], inventory_capacity = saved_inv[1], inventory_page = saved_inv[2];
    memcpy(scroll_at, saved_scroll, sizeof scroll_at);
    memcpy(scroll_want, saved_want, sizeof scroll_want);
    memcpy(scrolled_to, saved_to, sizeof scrolled_to);
}

/// ((Triforce, 11-20) how much of the Mods screen shows now, as its In plays (mods_page_anim.h); 1 on every other page, and
/// in a still (no window's frames stepping the easing, or RX_VK_UI_STILL for pictures that compare): as it stands
float mods_screen_alpha() {
    static const bool still = getenv("RX_VK_UI_STILL") != nullptr;
    return page == kModsPage ? mods_screen.alpha(prof_now(), !ease_live || still) : 1.0f;
}

/// The menu: the game dimmed across the whole window, the pages in a column as wide as a 16:9 screen of this height, in the
/// middle (a window of 16:9 or narrower: the whole of it). The pages draw from 0 as on 16:9; their vertices and clip
/// rectangles are moved over after, and menu_tick moves the mouse back through menu_map before it tests the hits. (Triforce)
/// perf_under: the FPS counter row's Full panel, over the dim and under the pages, as NX2navi keeps its panel under its menu.
/// ((Triforce, 11-19) The Mods entry's page (Mods and Quit under the game's list, Quit's dialog) on the game's own grid, where
/// its list is: game_grid.h)
void draw_menu(ui::Ctx& c, bool perf_under) {
    if (reshade_menu::comparing()) {   // ((Triforce) 11-24: the ReShade comparison's bar alone, over the game seen whole)
        menu_map = {};
        reshade_menu::draw_comparison(c, hits);
        return;
    }
    const bool row = page == kModsRowPage;   // ((Triforce) the Mods entry has the cursor: over the game's list, nothing dimmed)
    // ((Triforce, 11-20) the Mods screen's In: while it plays, the entries that opened it (Mods, and Quit under it) are still
    // drawn under it, on the game's list, and go as the screen comes; without them the list stood a frame without its Mods
    // entry before the screen covered it)
    const float mods_in = mods_screen_alpha();
    if (mods_in < 1 && (mods_list_fresh() || mods_title_fading())) {
        const int vtx_under = c.d->VtxBuffer.Size;
        draw_mods_row_shut(c);
        for (int i = vtx_under; i < c.d->VtxBuffer.Size; i++) c.d->VtxBuffer[i].col = ui::alpha(c.d->VtxBuffer[i].col, 1 - mods_in);
    }
    const int vtx_page = c.d->VtxBuffer.Size;   // (from here the page: its background, its column and all it draws)
    // (the game behind: inside its own Options screen its own background, untouched; over play the System screens' own
    // (ui::system_bg), or dimmed flat without its textures)
    const bool tuning = tune_mode && page == 0 && !embed_open && !row;   // ((Triforce) the tuning bar: the game seen whole
    if (!embed_open && !row && !tuning && !ui::system_bg(c)) c.d->AddRectFilled(ImVec2(0, 0), ImVec2(c.w, c.h), ui::rgba(8, 5, 2, ui::kDimAlpha));
    // ((Triforce, 11-19) inside the game's own Options screen the Full panel between our page and our header, as on the game's
    // own tab it is over the game's panes and under our header (menu_record: draw_perf, then draw_game_tab): the lab's "our
    // help box draws over part of the stats panel" (fullscreen 3440 x 1440). ((11-20) Over play under the pages, as before.
    // Either way it waits (panel_wait) in a list split in two, so that a dialog's dim can go under it (dim_page: our dialogs
    // keep it bright, as the game's own dialogs and Quit's do), the restart question's too)
    const bool perf_between = perf_under && !row;
    // ((Triforce, 11-19) the pages over the game's own Options screen on the game's grid, as its panes under them (game_grid.h
    // column_of): the lab's "16:9 window, 21:9 picture letterboxed: the game's Default Settings (X) / Back (A) and the left
    // edge of its help box show through mid-screen beside our panel" was our column of the window's whole height over the
    // picture's grid. Over play (F1), the window's column as before)
    const bool on_game = !row && pages_on_game();
    const game_grid::Column col = pages_column(c.w, c.h, on_game);
    ui::Ctx k = column_ctx(c, col);
    k.over_game = embed_open;   // (inside the game's own Options screen: its background stays, its list is under our plates)
    // ((Triforce, 11-20) its guides band's end, past the column on a wide picture; sooner from the pause menu (a review of 1104352))
    k.guides_x1 = game_grid::guide_band_x1(col, game_options_from_pause.load(std::memory_order_relaxed) ? game_grid::kPauseGuideBandRight
                                                                                                          : game_grid::kGuideBandRight);
    menu_map = col.map;
    menu_window_w = c.w, menu_window_h = c.h;
    if (row) {
        const game_grid::Place g = menu_grid(c.w, c.h);
        k = grid_ctx(c, g), k.over_game = false;
        menu_map = game_grid::map_of(g);
    }
    const int vtx0 = c.d->VtxBuffer.Size, cmd0 = c.d->CmdBuffer.Size;
    const ImVec4 window_clip = clip_now(c.d);
    if (perf_between) {   // (inside the game's Options screen the header into channel 1 (header_layer); over play the pages into 1)
        c.d->ChannelsSplit(2), panel_split = c.d, panel_wait = {&c, window_clip, 0, 0};
        if (embed_open) header_split = c.d;
        else c.d->ChannelsSetCurrent(1);
    }
    if (on_game) push_window_clip(c.d, menu_map, c.w, c.h);
    hits.clear(0, 0, k.w, k.h);
    hits_game_tab = false;
    if (row) draw_mods_row(k, true);
    else if (page != 5 && !tuning) {   // (the System screens' dark column behind the list: SystemBg_05, under the header)
        float cx0, cx1, hx0, hx1;
        bool narrow;
        columns(k, &cx0, &cx1, &hx0, &hx1, &narrow);
        // (over the game's own Options screen its column is under ours: only our opaque middle, over its list, so its soft
        // edges stay as the game draws them, once)
        ui::column_bg(k, cx0, cx1, k.over_game);
    }
    if (row) {   // (the entries: drawn above; Quit's dialog over them, and its Out; its dim the window's)
        if (quit_ask || quit_closing())
            draw_quit_ask(k);
    }
    else if (page == 5) draw_ask(k);
    else if (page == 1) draw_controls(k);
    else if (page == 3) draw_teleport(k);
    else if (page == 4) draw_inventory(k);
    else if (page == 6) draw_names(k);   // ((Triforce) Game flags, Cutscenes, Scan amiibo)
    else if (page == kModsPage) draw_mods(k);
    else if (page == kAchPage) draw_achievements(k);   // ((Triforce) the System tab's Achievements)
    else if (page == kFilesPage) draw_files(k);        // ((Triforce) the title's file select, and the System tab's Save files)
    else if (tuning) draw_tune_bar(k);
    else draw_options(k);
    if (on_game) c.d->PopClipRect();
    int perf0 = 0, perf1 = 0;   // (the Full panel's vertices: in the window's pixels already)
    if (perf_between) {   // (the panel under the header, unless a dialog's dim drew it already: dim_page)
        panel_between(c.d);
        perf0 = panel_wait.v0, perf1 = panel_wait.v1;
    }
    // ((Triforce, 11-20) the Mods screen fades in whole: the background, the column, the cards, the details, the Salesman's
    // picture and the prompts; not the Full panel, which was there before it)
    for (int i = vtx_page; mods_in < 1 && i < c.d->VtxBuffer.Size; i++)
        if (i < perf0 || i >= perf1) c.d->VtxBuffer[i].col = ui::alpha(c.d->VtxBuffer[i].col, mods_in);
    if (menu_map.ox <= 0 && menu_map.oy <= 0 && menu_map.kx == 1) return;
    // (a clip rectangle of the column's: moved with it; the whole window's (the dim's, and the draw list's own) stays, as it
    // holds the column wherever it is)
    put_on_grid(c.d, vtx0, cmd0, menu_map, window_clip, perf0, perf1);
    // (the draw list's current header, for whatever is drawn next: the window's again after the pages' pops)
}

// ---- ((Triforce) the FPS counter's levels between On and Full (fps_levels.h): Frame time, Graph, Breakdown, Dev. Their texts
// are made twice a second where the counter's number is (menu_tick, fps_detail_sample), from the frames' ring Full measures
// with (perf_ring) and the counts the renderer keeps anyway; the graph is drawn from the ring's newest frames. The render
// thread's lane shows only once a render thread has told its times (menu_fps_render_thread): none in a build without one ----
std::atomic<int64_t> rt_work_ns{0}, rt_wait_ns{0};
std::atomic<bool> rt_seen{false};
struct FpsDetail {
    bool have = false;
    char time[32] = "", low[32] = "";
    double frame_ms = 0, part[fps_levels::kParts] = {}, gpu_ms = -1;   // (ms a frame; gpu_ms -1: no timestamps)
    bool rt = false;
    double rt_work_ms = 0, rt_wait_ms = 0;
    char dev[fps_levels::kDevLines][40] = {};
    perf_stats::Base base;
    int64_t frames = 0, draws = 0, skipped = 0, dispatches = 0, passes = 0, uploads = 0, pipelines = 0, rt_work = 0, rt_wait = 0;
    int level = 0;   // (the level the counts were taken at: another one starts them anew)
} fps_detail;
float auto_cap_fps();   // (below: the Frame rate cap's rate)
void edged_text(ui::Ctx& c, ImFont* f, float px, ImVec2 p, ImU32 col, const char* t);   // (below)
/// The Frame rate cap's frame time, ms; 0 with Uncapped (no target)
double fps_target_ms() { return opts.fps_cap >= fps_cap::kUncapped ? 0.0 : 1000.0 / std::max(1.0f, auto_cap_fps()); }
void fps_detail_sample() {
    FpsDetail& d = fps_detail;
    const bool fresh = d.level != opts.show_fps;
    d.level = opts.show_fps;
    perf_stats::Summary second, ten;
    {
        std::lock_guard lk(perf_mu);
        second = perf_stats::summarize(perf_ring, 1000000000ll);
        ten = perf_stats::summarize(perf_ring);
    }
    if (second.frames) fps_levels::frame_time_text(d.time, sizeof d.time, second.avg_ms), d.frame_ms = second.avg_ms;
    else snprintf(d.time, sizeof d.time, "-");
    fps_levels::low_text(d.low, sizeof d.low, ten.low1_fps);
    d.have = true;
    if (!fps_levels::shows_breakdown(opts.show_fps)) return;
    // (the parts a frame since the sample before, as Full's figures per frame: perf_stats::per_frame)
    perf_stats::Counts now;
    now.frames = game_frames.load(std::memory_order_relaxed);
    now.prep_ns = prof_ns[PROF_SUBMIT] + prof_ns[PROF_PRESENT], now.gpu_ns = gpu_time_busy_ns();
    int64_t astc = 0, bytes = 0;
    texture_stats(&now.uploads, &astc, &bytes);
    draw_wait_split(&now.pipe_us, &now.shader_us);
    perf_stats::PerFrame f;
    const perf_stats::Step st = perf_stats::per_frame(d.base, now, fresh, &f);
    if (st == perf_stats::STEP_NEW) {
        fps_levels::split(d.frame_ms, f.prep_ms, f.pipe_ms, f.shader_ms, d.part);
        d.gpu_ms = f.gpu_ms;
    }
    // (the render thread's lane, once it has told its times: its work and its waits a game frame)
    const int64_t work = rt_work_ns.load(std::memory_order_relaxed), wait = rt_wait_ns.load(std::memory_order_relaxed);
    const int64_t n = now.frames - d.frames;
    d.rt = rt_seen.load(std::memory_order_relaxed);
    if (d.rt && n > 0 && !fresh) d.rt_work_ms = (work - d.rt_work) / 1e6 / n, d.rt_wait_ms = (wait - d.rt_wait) / 1e6 / n;
    d.rt_work = work, d.rt_wait = wait;
    if (fps_levels::shows_dev(opts.show_fps)) {   // (the renderer's own numbers a frame since the sample before)
        int64_t draws = 0, skipped = 0, dispatches = 0, pipelines = 0, passes = 0, mesh = 0;
        double pipeline_ms = 0;
        draw_stats(&draws, &skipped, &dispatches, &pipelines);
        draw_stats2(&passes, &mesh, &pipeline_ms);
        const int64_t frames = fresh ? 0 : n;
        uint64_t used = 0, allowed = 0;
        const bool known = vram_usage(&used, &allowed);
        fps_levels::vram_line(d.dev[fps_levels::kVram], sizeof d.dev[0], used, allowed, known);
        fps_levels::per_frame_line(d.dev[fps_levels::kDraws], sizeof d.dev[0], draws - d.draws, frames);
        fps_levels::per_frame_line(d.dev[fps_levels::kDispatches], sizeof d.dev[0], dispatches - d.dispatches, frames);
        fps_levels::per_frame_line(d.dev[fps_levels::kPasses], sizeof d.dev[0], passes - d.passes, frames);
        fps_levels::per_frame_line(d.dev[fps_levels::kSkipped], sizeof d.dev[0], skipped - d.skipped, frames);
        fps_levels::per_frame_line(d.dev[fps_levels::kUploads], sizeof d.dev[0], now.uploads - d.uploads, frames);
        snprintf(d.dev[fps_levels::kPipelines], sizeof d.dev[0], "%lld", (long long)pipelines);   // (built since the start)
        d.draws = draws, d.skipped = skipped, d.dispatches = dispatches, d.passes = passes, d.pipelines = pipelines;
    }
    d.uploads = now.uploads, d.frames = now.frames;
}
/// (draw_fps) The levels' lines under the counter, right-aligned at x1 from y down: the frame time and the 1% low; the graph
/// of the newest frames against the cap's frame time; the frame's parts as a bar, the GPU's (and the render thread's) lanes
/// under it, each part named with its time; the renderer's numbers. In the counter's look: the HUD's dark edge, no plate but
/// the graph's and the bars' own
void draw_fps_detail(ui::Ctx& c, float x1, float y) {
    const FpsDetail& d = fps_detail;
    const int level = opts.show_fps;
    if (!d.have || !fps_levels::shows_time(level)) return;
    ImFont* f = c.f.strong;
    const float px = ui::lu(c, 34), line = ui::lu(c, 46), w = ui::lu(c, 640);
    auto right = [&](float yy, const char* t, ImU32 col) {   // (a line's text, its right end at x1, its middle at yy)
        edged_text(c, f, px, ImVec2(x1 - ui::size_of(f, px, t).x, ui::mid_top(f, px, yy)), col, t);
    };
    char b[96];
    snprintf(b, sizeof b, "%s   %s", d.time, d.low);
    right(y, b, ui::kInk);
    y += line;
    const double target = fps_target_ms();
    if (fps_levels::shows_graph(level)) {   // (the newest frames: the cap's frame time a line across, a frame past the top at it)
        float ms[kPerfGraph];
        int n = 0;
        {
            std::lock_guard lk(perf_mu);
            n = perf_stats::newest(perf_ring, ms, kPerfGraph);
        }
        float sorted[kPerfGraph];
        std::copy(ms, ms + n, sorted);
        const double top = fps_levels::graph_top(target, fps_levels::typical_ms(sorted, n));
        const float gh = ui::lu(c, 140), gx0 = x1 - w, gy0 = y - line * 0.3f, gy1 = gy0 + gh;
        c.d->AddRectFilled(ImVec2(gx0, gy0), ImVec2(x1, gy1), ui::rgba(0, 0, 0, 110), ui::kRound * c.s);
        if (target > 0 && target < top) {
            const float ty = gy1 - (float)(target / top) * gh;
            c.d->AddLine(ImVec2(gx0, ty), ImVec2(x1, ty), ui::alpha(ui::kAccent, 0.6f), std::max(1.0f, ui::lu(c, 2)));
        }
        for (int i = 1; i < n; i++) {
            const auto at = [&](int k) {
                return ImVec2(gx0 + w * (float)(kPerfGraph - n + k) / (kPerfGraph - 1),
                              gy1 - (float)(std::min<double>(ms[k], top) / top) * gh);
            };
            const int grade = fps_levels::rate_grade(ms[i] > 0 ? 1000.0 / ms[i] : 0, target);
            const ImU32 col = grade == 0 ? ui::kInk : grade == 1 ? ui::rgba(240, 190, 80) : ui::rgba(240, 96, 80);
            c.d->AddLine(at(i - 1), at(i), col, std::max(1.0f, ui::lu(c, 3)));
        }
        snprintf(b, sizeof b, "%.0f ms", top);
        edged_text(c, f, ui::lu(c, 26), ImVec2(gx0 + ui::lu(c, 8), gy0 + ui::lu(c, 4)), ui::kSoft, b);
        y = gy1 + line * 0.8f;
    }
    if (fps_levels::shows_breakdown(level) && d.frame_ms > 0) {   // (the parts as a bar over the frame time, the lanes under it)
        static const ImU32 cols[fps_levels::kParts] = {ui::rgba(120, 190, 120), ui::rgba(110, 150, 240), ui::rgba(240, 190, 80),
                                                       ui::rgba(240, 110, 90)};
        const float bh = ui::lu(c, 26), bx0 = x1 - w;
        const double span = std::max(d.frame_ms, d.gpu_ms > 0 ? d.gpu_ms : 0.0);
        auto bar = [&](float yy, double ms, ImU32 col, float x) {   // (a part from x, its share of the span)
            const float wpx = (float)(ms / span) * w;
            if (wpx > 0.5f) c.d->AddRectFilled(ImVec2(x, yy), ImVec2(x + wpx, yy + bh), col);
            return x + wpx;
        };
        float x = bx0;
        c.d->AddRectFilled(ImVec2(bx0, y - bh * 0.5f), ImVec2(x1, y + bh * 0.5f), ui::rgba(0, 0, 0, 110));
        for (int p = 0; p < fps_levels::kParts; p++) x = bar(y - bh * 0.5f, d.part[p], cols[p], x);
        y += line * 0.8f;
        if (d.gpu_ms > 0) {
            c.d->AddRectFilled(ImVec2(bx0, y - bh * 0.5f), ImVec2(x1, y + bh * 0.5f), ui::rgba(0, 0, 0, 110));
            bar(y - bh * 0.5f, d.gpu_ms, ui::rgba(200, 140, 230), bx0);
            snprintf(b, sizeof b, "GPU %.1f ms", d.gpu_ms);
            right(y, b, ui::kSoft);
            y += line * 0.8f;
        }
        if (d.rt) {   // (the render thread's lane: its work, then its waits)
            c.d->AddRectFilled(ImVec2(bx0, y - bh * 0.5f), ImVec2(x1, y + bh * 0.5f), ui::rgba(0, 0, 0, 110));
            bar(y - bh * 0.5f, d.rt_wait_ms, ui::rgba(90, 90, 100), bar(y - bh * 0.5f, d.rt_work_ms, ui::rgba(110, 150, 240), bx0));
            snprintf(b, sizeof b, "Render thread %.1f ms, waits %.1f ms", d.rt_work_ms, d.rt_wait_ms);
            right(y, b, ui::kSoft);
            y += line * 0.8f;
        }
        for (int p = 0; p < fps_levels::kParts; p++) {
            snprintf(b, sizeof b, "%s %.1f ms", fps_levels::part_name(p), d.part[p]);
            right(y, b, cols[p]);
            y += line * 0.8f;
        }
    }
    if (fps_levels::shows_dev(level))
        for (int i = 0; i < fps_levels::kDevLines; i++) {
            snprintf(b, sizeof b, "%s %s", fps_levels::dev_name(i), d.dev[i][0] ? d.dev[i] : "-");
            right(y, b, ui::kSoft);
            y += line * 0.8f;
        }
}

/// The FPS counter, as a counter of the game's HUD: the rate in the HUD's own digits (NinDev-Number, the rupee counter's
/// font), white with the HUD's soft dark edge, "FPS" small beside it in the menus' font; with frame generation the game's
/// own rate after a slash, smaller, as the HUD writes an amount of its most ("12 / 99"). No plate: the HUD has none.
/// Where: at the top, its right end 500 units left of the screen's right edge, its middle 60 units down. Measured on the
/// game's own screens (1920 x 1080), that strip is free in play and in the menus alike: left of the item box, its page dots
/// and R key (from 1725 px) and above the fishing slots (from 53 px down); in the pause menu between the tabs' R icon
/// (to 1470 px) and the rupee counter (from 1715 px); right of the hearts and the mini-game timer. Under the header, at
/// the right, while our own options are open (their tabs' R icon is in that strip)
/// The HUD's soft dark edge under a text, then the text, its top left at p: the text eight times a little to each side of
/// itself and down, dark and half seen, e (px / 20, a pixel at least) from it. The FPS counter's, and (Triforce) the Full
/// panel's texts', so that they read over a bright scene and the HUD's own art
void edged_text(ui::Ctx& c, ImFont* f, float px, ImVec2 p, ImU32 col, const char* t) {
    t = i18n::tr(t);   // ((Triforce) in the menu's language, as ui::size_of measures it)
    const float e = std::max(1.0f, px * 0.05f);
    for (int k = 0; k < 8; k++) {
        const float ang = k * 0.785398f;
        c.d->AddText(f, px, ImVec2(p.x + std::cos(ang) * e, p.y + std::sin(ang) * e + e * 0.6f), ui::rgba(20, 14, 6, 150), t);
    }
    c.d->AddText(f, px, p, col, t);
}

void draw_fps(ui::Ctx& window, bool under_banner) {
    if (!fps_text[0]) return;
    // ((Triforce, 11-19) under our header over the game's own Options screen: on the game's grid with the header (draw_menu,
    // draw_game_tab), in the column's pixels, put there after. (11-20) Over play, the title and the pause menu too: on the
    // game's grid, as a counter of its HUD, so that it keeps its 16:9 place among the game's own header items (between the
    // pause menu's R and its rupees) in every shape. The lab's check 3 of 26670c0, a 1680 x 1050 window with a 16:10
    // picture: it ended 235 px in from the right edge, toward the middle of that gap, as it was laid out on the window's
    // 16:9 column of its whole height, not squeezed across (x 0.9) with the game's layouts; and with bars above and below
    // the picture (a 21:9 picture in 1600 x 900) it was at the window's top, in the bar, sized by the window's height.
    // Under our header over play (F1): the window's column with that header, as before. ((11-20, a review of ca33bee) The
    // restart question (page 5) too: under our "Restart Needed" banner it is on the column draw_menu lays that page and its
    // banner on (pages_on_game: the window's over play, the grid inside the game's Options screen). Was: page 5 always on
    // the grid, over play below the banner it had sat over (1600 x 900, 21:9 picture: from (1392, 25) to (1244, 131)))
    const bool on_game = under_banner ? pages_on_game() : true;
    const game_grid::Column col = pages_column(window.w, window.h, on_game);
    ui::Ctx c = on_game ? column_ctx(window, col) : window;
    const int vtx0 = c.d->VtxBuffer.Size, cmd0 = c.d->CmdBuffer.Size;
    const ImVec4 window_clip = clip_now(c.d);
    // ((Triforce, 11-20) the window's clip in the column's pixels while it draws there, as draw_game_tab's: on a grid narrower
    // than 16:9 (a 16:10 or 4:3 picture) the column is wider than the window, the counter at its right past the window's
    // width in the column's pixels, and ImGui drops a glyph past the clip's right edge as it adds it (a review of c3d2d32:
    // no counter under our header at 16:10))
    if (on_game) push_window_clip(c.d, col.map, window.w, window.h);
    ImFont* digits = c.f.number ? c.f.number : c.f.strong;
    const float big = ui::lu(c, 72), small = ui::lu(c, 46), label = ui::lu(c, 34), gap = ui::lu(c, 12);
    const char* game = fps_sub[0] ? fps_sub : nullptr;   // ("60": the game's own rate, with frame generation)
    const float nw = ui::size_of(digits, big, fps_text).x, lw = ui::size_of(c.f.strong, label, "FPS").x;
    const float sw = game ? ui::size_of(digits, small, "/").x + ui::lu(c, 8) + ui::size_of(digits, small, game).x + gap : 0;
    const float total = nw + gap + sw + lw;
    const bool below = under_banner && page != 5;   // (our options open: under their header)
    // (a window wider than 16:9: the HUD keeps its 16:9 shape in the middle, and so does the counter)
    const float hud_w = std::min(c.w, std::floor(c.h * 16.0f / 9.0f + 0.5f)), hud_x1 = (c.w + hud_w) * 0.5f;
    const float x1 = below ? hud_x1 - ui::lu(c, 80) : hud_x1 - ui::lu(c, 500);
    const float my = below ? banner_h(c) + ui::lu(c, 50) : ui::lu(c, 60);
    auto edged = [&](ImFont* f, float px, float x, float y, const char* t, ImU32 col) {   // (the HUD's dark edge: edged_text, its middle at y)
        edged_text(c, f, px, ImVec2(x, ui::mid_top(f, px, y)), col, t);
        return ui::size_of(f, px, t).x;
    };
    float x = x1 - total;
    x += edged(digits, big, x, my, fps_text, ui::kInk) + gap;
    if (game) {
        x += edged(digits, small, x, my + ui::lu(c, 8), "/", ui::kSoft) + ui::lu(c, 8);
        x += edged(digits, small, x, my + ui::lu(c, 8), game, ui::kSoft) + gap;
    }
    edged(c.f.strong, label, x, my + ui::lu(c, 12), "FPS", ui::kAccent);
    draw_fps_detail(c, x1, my + ui::lu(c, 74));   // ((Triforce) the levels between On and Full under it: fps_levels.h
    if (on_game) c.d->PopClipRect(), put_on_grid(c.d, vtx0, cmd0, col.map, window_clip);
}

/// (Triforce) The performance overlay on Full: NX2navi's full panel, laid out as its own is, to the pixel of its scale
/// ((Triforce: from NX2navi runtime/ui/perf_panel.cpp perf_panel_draw, machine_and_frames, frame_plot, waits, picture and
/// divider, and runtime/ui/menu.cpp menu_scale, at 62cc3b13; MIT, the notice in perf_machine.h). Drawn with Dear ImGui's draw
/// list in place of its window and tables, by the metrics those had there, in pixels at its scale (the window's lines over
/// 1080; on a window taller than 0.68 of its width, that width's; 720 lines at the display's scale at least): the window's
/// padding 24 x 20, the cells' 7 x 1.5, items 12 apart, the text its menu font's 25.5 at the window's 0.72, a divider 26 x
/// 0.72 high, the graph 48 high inside its frame's padding of 14 x 8, its line a pixel wide. Top to bottom: the title (perf_title: this build of Triforce and the game's version); a divider; the
/// machine (GPU, VRAM, CPU, RAM); a divider; the frames (FPS with its 1% and 0.1% lows, FG while frame generation makes
/// frames, Frame), the two in a name column and three right-aligned columns, each as wide as the widest text it can hold
/// (NX2navi's samples of 8s), so the panel keeps its width as the numbers change; the newest kPerfGraph frame times as a line
/// over a dark band, 0 at the bottom, 50 ms or the longest of them at the top, frames not seen yet 0; the figures per frame;
/// a divider; the settings that shape the picture (a row without a value left out); a divider and the GPU's and the CPU's names.
/// Themed as the options are, with what they draw with from the player's own game files at run time (vk_game_tex.h): the
/// panel is the options' caption plate (SystemCaptionBg_00, ui::box) at kPerfOpacity, so the game shows through it; each
/// divider the options' separator (OptionSeparateMark_00 and SystemLine_03, ui::separator) at NX2navi's divider's size, in its
/// divider's tints; the text in the options' own font (the game's "Normal", menu_ctx), the names in the options' gold
/// (ui::kAccent), the values in their white (ui::kInk), the title, the GPU's and CPU's names and a "-" where the machine gives
/// no number in their soft white (ui::kSoft), each text with the FPS counter's thin dark edge (edged_text) so that it reads
/// through the plate over a bright scene. Where the game's files have none of it, ui::box and ui::separator draw their plain
/// plates. Where: NX2navi's, the window's top right corner 12 in from both edges, at every shape of window; Full draws no FPS
/// counter (menu_record), and while the options are open the panel is under them, over their dim (draw_menu), as NX2navi's
/// is under its menu's window; ((Triforce, 11-19) inside the game's own Options screen over our page and under its header,
/// as on the game's own tab, and over the Mods entry's page). The scale is NX2navi's menu_scale with its DPI floor (perf_scale), at which prebake has baked
/// the text's size. perf_sample made the texts
void draw_perf(ui::Ctx& c) {
    const PerfView& v = perf_view;
    if (!v.have) return;
    ImFont* font = c.f.body ? c.f.body : c.f.strong;
    if (!font) return;
    const float k = perf_scale(c.w, c.h);   // (NX2navi's menu_scale, its DPI floor too: the size prebake baked)
    const float px = perf_px(k), cell_y = 1.5f * k, gap = 2 * 7.0f * k, item = 12 * k, row = px + 2 * cell_y;
    const float pad_x = 24 * k, pad_y = 20 * k, ds = 0.72f * k, div_h = 26 * ds, graph_h = 48 * k;
    const ImU32 label_col = ui::kAccent, value_col = ui::kInk, dim_col = ui::alpha(ui::kSoft, 0.8f);
    const auto tw = [&](const char* t) { return ui::size_of(font, px, t).x; };
    // (the columns of the machine and the frames)
    float col[4] = {tw("-"), 0, 0, 0};
    for (const char* n : kPerfTop) col[0] = std::max(col[0], tw(n));
    static const char* const samples[3][5] = {{"100%", "888.8 GB", "888", "888.8 ms", ""},
                                              {"188 \xC2\xB0" "C", "/ 888.8 GB", "1% low 888", "max 8888.8 ms", ""},
                                              {"", "8888 MHz", "game 100%", "game 888.8 GB", "0.1% low 888"}};
    for (int j = 0; j < 3; j++) {
        for (const char* s : samples[j]) col[j + 1] = std::max(col[j + 1], tw(s));
        for (int r = 0; r < kPerfTopRows; r++) col[j + 1] = std::max(col[j + 1], tw(v.top[r][j].t));   // (a longer text all the same)
    }
    float wait_name = 0, wait_value = std::max(tw("888.88 ms"), tw("888.8 per frame")), set_name = 0, set_value = 0;
    for (int i = 0; i < kPerfFrameRows; i++) wait_name = std::max(wait_name, tw(kPerfFrame[i])), wait_value = std::max(wait_value, tw(v.frame[i].t));
    int settings = 0;
    for (int i = 0; i < kPerfSettings; i++)
        if (v.setting[i][0]) settings++, set_name = std::max(set_name, tw(kPerfSetting[i])), set_value = std::max(set_value, tw(v.setting[i]));
    const float inner = std::ceil(std::max({col[0] + col[1] + col[2] + col[3] + 3 * gap, wait_name + gap + wait_value,
                                            set_name + gap + set_value, tw(v.title), tw(v.gpu_name), tw(v.cpu_name)}));
    const bool names = v.gpu_name[0] || v.cpu_name[0];
    const float content = px + item + div_h + item + 4 * row + item + div_h + item + (v.fg ? 3 : 2) * row + item + 4 * k + item +
                          graph_h + item + 2 * k + item + kPerfFrameRows * row + item + div_h + item + settings * row +
                          (names ? item + div_h + item + (v.gpu_name[0] ? px : 0) + (v.gpu_name[0] && v.cpu_name[0] ? item : 0) +
                                       (v.cpu_name[0] ? px : 0)
                                 : 0);
    // (the panel: the window's top right corner, 12 in from both edges at every shape of window, as NX2navi's
    // perf_panel_draw; Full draws no FPS counter beside it, as NX2navi's perf_draw)
    const float m = 12 * k, panel_w = std::ceil(inner + 2 * pad_x), panel_h = std::ceil(content + 2 * pad_y);
    const ImVec2 a(std::floor(c.w - m - panel_w), std::floor(m)), b(a.x + panel_w, a.y + panel_h);
    perf_rect[0] = a.x, perf_rect[1] = a.y, perf_rect[2] = panel_w, perf_rect[3] = panel_h;   // ((Triforce VR) for the HUD's panel)
    ui::box(c, a, b, kPerfOpacity);
    // (the contents, from the padding in)
    const float x0 = a.x + pad_x, x1 = x0 + inner;
    float y = a.y + pad_y;
    ui::Ctx dc = c;
    dc.s = 0.7035f * k;   // (the separator's ornament (342 layout units) as wide as NX2navi's divider's: 111 of its scale's 0.72)
    const auto divider = [&] {
        ui::separator(dc, x0 - 4 * ds, x1 + 4 * ds, std::floor(y + div_h * 0.5f) + 0.5f, ui::rgba(196, 164, 112), ui::rgba(150, 126, 90));
        y += div_h + item;
    };
    // (every text with the FPS counter's thin dark edge, edged_text: it reads over a bright scene or the HUD's art through the
    // see-through plate)
    const auto text = [&](ImVec2 p, ImU32 col, const char* t) { edged_text(c, font, px, p, col, t); };
    const auto label = [&](const char* t) { text(ImVec2(x0, y + cell_y), label_col, t); };
    const auto right = [&](float x_end, const char* t, bool dim) {
        if (t[0]) text(ImVec2(x_end - tw(t), y + cell_y), dim ? dim_col : value_col, t);
    };
    const auto table = [&](int r0, int r1) {   // (the top block's rows r0 to r1: a name and three cells)
        for (int r = r0; r < r1; r++) {
            if (r == kPerfFG && !v.fg) continue;
            label(kPerfTop[r]);
            float x = x0 + col[0];
            for (int j = 0; j < 3; j++) x += gap + col[j + 1], right(x, v.top[r][j].t, v.top[r][j].dim);
            y += row;
        }
        y += item;
    };
    text(ImVec2(x0, y), dim_col, v.title);   // (the build first: a screenshot in a bug report carries it)
    y += px + item;
    divider();
    table(0, 4);
    divider();
    table(4, kPerfTopRows);
    y += 4 * k + item;
    {   // (the graph: NX2navi's PlotLines, its frame black at 0.32, the line in the names' gold)
        static float ms[kPerfGraph];
        int n;
        {
            std::lock_guard lk(perf_mu);
            n = perf_stats::newest(perf_ring, ms, kPerfGraph);
        }
        const ImVec2 g0(x0, y), g1(x1, y + graph_h), p0(g0.x + 14 * k, g0.y + 8 * k), p1(g1.x - 14 * k, g1.y - 8 * k);
        c.d->AddRectFilled(g0, g1, ui::rgba(0, 0, 0, 82));
        float most = 50;
        for (int i = 0; i < n; i++) most = std::max(most, ms[i]);
        static ImVec2 pts[kPerfGraph];
        for (int i = 0; i < kPerfGraph; i++) {   // (the oldest at the left; before the first frames, 0)
            const float t = i < kPerfGraph - n ? 0.0f : ms[i - (kPerfGraph - n)];
            pts[i] = ImVec2(p0.x + (p1.x - p0.x) * (float)i / (kPerfGraph - 1), p1.y - std::min(t, most) / most * (p1.y - p0.y));
        }
        c.d->AddPolyline(pts, kPerfGraph, label_col, ImDrawFlags_None, 1.0f);   // (PlotLines' line: 1 pixel at every scale)
    }
    y += graph_h + item + 2 * k + item;
    for (int i = 0; i < kPerfFrameRows; i++) label(kPerfFrame[i]), right(x1, v.frame[i].t, v.frame[i].dim), y += row;
    y += item;
    divider();
    for (int i = 0; i < kPerfSettings; i++)
        if (v.setting[i][0]) label(kPerfSetting[i]), right(x1, v.setting[i], false), y += row;
    if (names) {
        y += item;
        divider();
        if (v.gpu_name[0]) text(ImVec2(x0, y), dim_col, v.gpu_name), y += px + item;
        if (v.cpu_name[0]) text(ImVec2(x0, y), dim_col, v.cpu_name);
    }
}

/// (Triforce) The game's own tab inside its Options screen: our header over the screen's own (the same picture), the tabs on
/// it with "Game" chosen; the rest is the game's. It comes in over the screen's opening and goes with its closing
/// ((Triforce, 11-19) whether the game's own prompts show a controller's buttons: the face it was given at its start
/// (host/prompts.c), a controller's unless the keys' (-1: the game's own icons, the Switch's)
bool game_prompts_pad() {
    const int face = host && host->prompt_face ? host->prompt_face() : -1;
    return face != HOS_PROMPT_KEYBOARD;
}
void draw_game_tab(ui::Ctx& c) {
    // ((Triforce, 11-19) on the game's grid, over its own header wherever the picture is in the window (game_grid.h column_of):
    // in a 16:9 window with a 21:9 picture between bars it was at the window's top, above the game's header, and our tabs'
    // pages below it covered the game's panes as far as the picture's bottom only)
    const game_grid::Column col = pages_column(c.w, c.h, true);
    ui::Ctx k = column_ctx(c, col);
    // ((Triforce, 11-19) the lab's "the tab strip's ends show LB/RB pad icons while the footer shows the keyboard's Shift": the
    // footer under our tabs here is the game's own (its Default Settings and Back), in the face the game was given; the
    // strip's ends took the overlay's own device used last (pad_last, which a test's scripted press sets as a pad's). They
    // name the game's face now, as the footer beside them)
    k.pad = game_prompts_pad();
    const int vtx0 = c.d->VtxBuffer.Size, cmd0 = c.d->CmdBuffer.Size;
    const ImVec4 window_clip = clip_now(c.d);
    push_window_clip(c.d, col.map, c.w, c.h);
    ui::banner(k, 0);
    // ((Triforce) the tabs as the mouse takes them, as draw_menu's are: their places in k's pixels, and the map right after)
    hits.clear(0, 0, k.w, k.h);
    game_tab_map = col.map, hits_game_tab = true;
    draw_tabs(k, -1, true, true);
    c.d->PopClipRect();
    put_on_grid(c.d, vtx0, cmd0, col.map, window_clip);
    static const bool still = getenv("RX_VK_UI_STILL") != nullptr;
    const int64_t now = prof_now(), seen = game_options_ns.load(std::memory_order_relaxed);
    float f = 1;
    if (!still) {
        f = std::clamp((float)((now - embed_since - 120000000LL) / 180e6), 0.0f, 1.0f);              // (in: after the screen's first frames)
        f *= 1 - std::clamp((float)((now - seen - 60000000LL) / 150e6), 0.0f, 1.0f);                  // (out: once it no longer runs)
    }
    if (f < 1)
        for (int i = vtx0; i < c.d->VtxBuffer.Size; i++) c.d->VtxBuffer[i].col = ui::alpha(c.d->VtxBuffer[i].col, f);
}

/// (Triforce) A line at the foot of the screen for a moment, as a guide of the game's: the Debug tab unlocked or locked
void draw_notice(ui::Ctx& c) {
    const float my = ui::at(c, 0, -1018).y, right = ui::at(c, 1840, 0).x, px = ui::lu(c, 48);
    const float w = ui::size_of(c.f.body, px, notice_text).x;
    if (const ui::Art* t = ui::skin("SystemGuideBase_00")) ui::image(c, t, ImVec2(right - w - ui::lu(c, 300), ui::prompt_bar_top(c)), ImVec2(c.w + ui::lu(c, 4), c.h), ui::rgba(0, 0, 0, 215), true);
    else c.d->AddRectFilled(ImVec2(right - w - ui::lu(c, 60), my - px), ImVec2(c.w, c.h), ui::kBar);
    ui::text_mid(c, c.f.body, px, right - w, my, ui::kInk, notice_text);
}

/// The start-up screen: the logo, the wordmark, what the start is doing, a bar, on a warm dark. A little below the middle; what
/// is under the logo at 0.86 of the logo's scale. startup_fade, 0 to 1, darkens it all to black as it ends
void draw_startup(ui::Ctx& c) {
    StartupView v;
    {
        std::lock_guard lk(startup_mu);
        v = startup;
    }
#if __has_include("vk_startup_draw.h")   // (the start-up screen's own drawing, when that file is in the tree; a fade of 2 is its last picture)
    draw_startup_screen(c, v, startup_fade.load(std::memory_order_relaxed));
    return;
#endif
    const float s = c.s, w = c.w, h = c.h, cx = w * 0.5f, k = s * 0.86f;   // (k: the scale of what is under the logo)
    c.d->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), ui::rgba(14, 10, 6));
    const float lh = 112 * s, top = h * 0.5f - 176 * s;
    for (int i = 40; i >= 1; i--) c.d->AddCircleFilled(ImVec2(cx, top + lh * 0.5f + 70 * s), h * 0.021f * i, ui::rgba(46, 33, 18, 4), 128);
    float aspect = 1;
    ImTextureData* logo = ui::logo(&aspect);
    if (logo) c.d->AddImage(logo->GetTexRef(), ImVec2(cx - lh * aspect * 0.5f, top), ImVec2(cx + lh * aspect * 0.5f, top + lh));
    float y = top + lh + 16 * s;
    ui::spaced(c, c.f.heading, 42 * k, ImVec2(cx, y), ui::rgba(246, 232, 204), "TRIFORCE", 6 * k);
    ui::flourish(c, cx - 190 * k, cx + 190 * k, y + 66 * k, ui::kAccent);
    ui::text_centre(c, c.f.body, 14.5f * k, ImVec2(cx, y + 78 * k), ui::kDim, v.version.c_str());
    if (!v.title.empty()) {
        y += 120 * k;
        if (!v.step.empty()) {   // ("STEP 2 OF 2" as "Step 2 of 2")
            std::string step = v.step;
            for (size_t i = 1; i < step.size(); i++) step[i] = (char)tolower((unsigned char)step[i]);
            ui::text_centre(c, c.f.body, 15 * k, ImVec2(cx, y), ui::kAccent, step.c_str());
        }
        ui::text_centre(c, c.f.heading, 24 * k, ImVec2(cx, y + 20 * k), ui::kInk, v.title.c_str());
        const float x0 = cx - 270 * k, x1 = cx + 270 * k, by = y + 64 * k;
        float under = by;
        if (v.fraction >= 0) {   // (the bar as a value cell: a dark cell, gold inside, the percentage on it)
            const float bh = 26 * k, in = 4 * k, fx = x0 + in + (x1 - x0 - 2 * in) * (float)std::min(v.fraction, 1.0);
            c.d->AddRectFilled(ImVec2(x0, by), ImVec2(x1, by + bh), ui::kCellDark);
            c.d->AddRect(ImVec2(x0, by), ImVec2(x1, by + bh), ui::kEdge, 0, std::max(1.0f, s));
            if (fx > x0 + in) ui::gold(c, ImVec2(x0 + in, by + in), ImVec2(fx, by + bh - in));
            // (the percentage in the middle of the whole bar, drawn twice: dark ink where the gold is under it, light where the
            // empty bar is, each clipped to its part, so every letter keeps its contrast as the edge passes through it)
            const float split = std::max(fx, x0 + in);
            c.d->PushClipRect(ImVec2(x0, by), ImVec2(split, by + bh), true);
            ui::text_mid_centre(c, c.f.strong, 15 * k, cx, by + bh * 0.5f, ui::kGoldInk, v.pct.c_str());
            c.d->PopClipRect();
            c.d->PushClipRect(ImVec2(split, by), ImVec2(x1, by + bh), true);
            ui::text_mid_centre(c, c.f.strong, 15 * k, cx, by + bh * 0.5f, ui::kInk, v.pct.c_str());
            c.d->PopClipRect();
            under = by + bh;
        }
        const float px = 16.5f * k;
        ui::text(c, c.f.body, px, ImVec2(v.fraction >= 0 ? x0 : cx - ui::size_of(c.f.body, px, v.left.c_str()).x * 0.5f, under + 12 * k),
                 ui::kSoft, v.left.c_str());
        if (!v.right.empty())
            ui::text(c, c.f.body, px, ImVec2(x1 - ui::size_of(c.f.body, px, v.right.c_str()).x, under + 12 * k), ui::kSoft, v.right.c_str());
        if (!v.hint.empty()) ui::text_centre(c, c.f.body, 15.5f * k, ImVec2(cx, by + 92 * k), ui::kDim, v.hint.c_str());
    }
    if (const float f = startup_fade.load(std::memory_order_relaxed); f > 0)   // (the end: to black, the game's first frame next)
        c.d->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), ui::rgba(0, 0, 0, (int)(std::min(f, 1.0f) * 255 + 0.5f)));
}

} // namespace
/// ((Triforce) 11-24, reshade_menu.h) the User preset file row's last choice: its files' count (outside
/// the unnamed namespace: the header declares it in mkwvk's)
void reshade_user_rows(int hi) {
    for (Row& r : rows)
        if (r.value == &reshade_menu::user_pick) r.hi = hi;
}

void startup_fade_to(float f) { startup_fade.store(f, std::memory_order_relaxed); }

void startup_screen(const StartupView* view) {
    if (!view) {
        startup_on.store(false, std::memory_order_release);
        startup_fade.store(0, std::memory_order_relaxed);
        return;
    }
    StartupView v = *view;
    if (v.version.empty()) v.version = version_text(HOOKSHOT_VERSION);   // ("v2.0.5"; "v2.0.5 dev" between releases)
    {
        std::lock_guard lk(startup_mu);
        startup = v;
    }
    startup_on.store(true, std::memory_order_release);
}

int hdr_at_start = 0;
int renodx_at_start = 0, upscale_pre_at_start = 0;
// ((Triforce, 11-21, the performance audit's TEX-50) the row's own default, not 0: with no options file (a first start)
// nothing set it, and the textures stayed BC3 although the row said On
int tex_bc1_at_start = Options().tex_bc1;
static_assert(Options().tex_bc1 == 1, "Opaque textures as BC1 is on by default: a first start takes it");
int tex_detail_at_start = 0;
extern int64_t presents_now;   // (vk_replay.cpp)
int evil_hd_now() {
    static const int64_t flip = [] {
        const char* e = getenv("RX_VK_EVIL_FLIP");
        const int64_t n = e && *e ? atoll(e) : 0;
        if (n > 0) logf("vk: RX_VK_EVIL_FLIP=%lld: Evil HD turned the other way every %lld presents (the lab's before and after)",
                        (long long)n, (long long)n);
        return n > 0 ? n : 0;
    }();
    const int row = opts.evil_hd ? 1 : 0;
    return flip ? row ^ (int)((presents_now / flip) & 1) : row;
}
int replay_threads_at_start = replay_threads::kDefaultRow;
static_assert(Options().replay_threads == replay_threads::kDefaultRow, "the row's default is replay_threads.h's");
bool renodx_chosen() {
    static const char* const e = getenv("RX_VK_RENODX");
    return e && *e ? atoi(e) != 0 : renodx_at_start != 0;
}

// ((Triforce, 11-22, the performance audit's PRESENT-46) menu_init found no options file: a first start, menu_first_start)
static bool first_start_no_file = false;

void menu_init() {
    static bool done;
    if (done) return;
    done = true;
    for (auto& count : item_counts) count.store(-1, std::memory_order_relaxed);
    bool has_options = false;
    const char* cheats = getenv("HOS_OOT_CHEATS");
    cheats_env = cheats && !strcmp(cheats, "1");
    if (cheats_env) {
        const char* hearts = getenv("HOS_OOT_PROTECT_HEARTS");
        protect_hearts.store(hearts && !strcmp(hearts, "1"));
    }
    if (host && host->screens) {   // ((Triforce) the connected screens, as the host found them at the start: before the file,
                                   // which an old Ultrawide row is read with)
        MkwVkScreen list[16];
        const int n = host->screens(list, 16);
        for (int i = 0; i < n; i++) {
            list[i].name[sizeof list[i].name - 1] = 0;
            screen_add(list[i].w, list[i].h, list[i].name, list[i].opens != 0);
            // ((Triforce) 11-24) the Fullscreen screen row's entries, in the host's order (host/display.c counts them so)
            char label[96];
            snprintf(label, sizeof label, "%s (%ux%u)", list[i].name[0] ? list[i].name : ("Screen " + std::to_string(i + 1)).c_str(),
                     list[i].w, list[i].h);
            fs_screen_labels.push_back(label);
        }
        for (Row& r : rows)
            if (r.value == &opts.fs_screen) r.hi = (int)fs_screen_labels.size();
    }
    if (FILE* f = fopen(ini_path().c_str(), "r")) {
        has_options = true;
        char line[80];
        bool has_resolution = false;
        bool v2 = false;
        int version = 0;
        int old_dynres = -1;   // (the row before Resolution: 0, the full scale, is its 100%; 1 is Auto)
        merged_rows::Before7 before7;   // ((Triforce) the keys a file before options_version 7 had for rows that are gone)
        while (fgets(line, sizeof line, f)) {
            ini_merge::add_line(ini_base, line);   // ((Triforce, handoff §9) the file as the game read it: save's base)
            char* eq = strchr(line, '=');
            if (!eq) continue;
            *eq = 0;
            for (Row& r : rows) {
                if (!ini_row(r) || strcmp(line, ini_key(r))) continue;
                const int v = atoi(eq + 1);
                *r.value = r.value == &opts.output_res ? output_choice(v) : std::min(std::max(v, r.lo), r.hi);
            }
            has_resolution |= !strcmp(line, "resolution");
            v2 |= !strcmp(line, "options_version");
            if (!strcmp(line, "options_version")) version = atoi(eq + 1);
            if (!strcmp(line, "dynamic_resolution")) old_dynres = atoi(eq + 1);
            if (!strcmp(line, "handheld_profile")) before7.handheld = atoi(eq + 1) != 0;
            if (!strcmp(line, "stick_dead_zone")) before7.stick_shared = atoi(eq + 1);
            if (!strcmp(line, "microphone_device")) {   // (hookshot: the microphone, by its name)
                mic_want = mic_key(eq + 1);
            }
            if (!strcmp(line, "gpu_device_name")) gpu_want = mic_key(eq + 1);   // ((Triforce) 11-20: the GPU device row's card, by its name)
            if (!strcmp(line, "fullscreen_screen_name")) fs_screen_want = fs_key(mic_key(eq + 1));   // ((Triforce) 11-24: the Fullscreen screen, by its name)
        }
        fclose(f);
        if (!fs_screen_want.empty()) {   // ((Triforce) 11-24) the Fullscreen screen found by its name and size where it is now; gone: Automatic
            opts.fs_screen = 0;
            for (size_t i = 0; i < fs_screen_labels.size(); i++)
                if (fs_key(fs_screen_labels[i]) == fs_screen_want) opts.fs_screen = (int)i + 1;
        }
        {   // ((Triforce) Custom's size from the file's own two numbers, not each kept to its row's ends: custom_rows_read)
            const auto side = [](const char* key) {
                const auto at = ini_base.find(key);
                return at == ini_base.end() ? 0L : atol(at->second.c_str());
            };
            custom_rows_read(side("output_width"), side("output_height"));
            const auto remembered = ini_base.find("output_custom_size");
            if (remembered != ini_base.end()) read_remembered_custom(remembered->second.c_str());
        }
        // ((Triforce) options_version 8 (7 in the 436f9ac-based builds; v0.5.1's 7 still had the rows): the handheld profile is
        // an Output resolution, the shared stick dead zone each stick's own; the other rows that went keep nothing to move (merged_rows.h kDropped). Before the values at the start are taken)

        hdr_at_start = opts.hdr;   // (local, RenoDX port: vk_menu.h)
        renodx_at_start = opts.renodx, upscale_pre_at_start = opts.upscale_pre;
        tex_detail_at_start = evil_hd::tex_detail(opts.evil_hd, opts.tex_detail);   // ((Triforce, 11-23) Evil HD: Full)
        tex_bc1_at_start = opts.tex_bc1;
        replay_threads_at_start = opts.replay_threads;
        {   // ((Triforce) 11-24) the Output device row's device, by its id: read whole (the lines above are cut at 80 bytes),
            // the base for the next save as the file has it, and told to the host
            if (FILE* g = fopen(ini_path().c_str(), "r")) {
                char text[HOS_OUTPUT_ID_CAP + 64];
                while (fgets(text, sizeof text, g)) {
                    if (!strchr(text, '\n') && !feof(g)) {   // (longer than any id: not one, and its rest no line of its own)
                        int c;
                        while ((c = fgetc(g)) != '\n' && c != EOF) {}
                        continue;
                    }
                    if (!strncmp(text, "audio_output_device_id=", 23)) output_want = output_id_key(text + 23);
                    if (!strncmp(text, "audio_output_device_name=", 25)) output_saved_name = mic_key(output_id_key(text + 25).c_str());
                }
                fclose(g);
            }
            if (ini_base.count("audio_output_device_id")) ini_base["audio_output_device_id"] = output_want;
            if (ini_base.count("audio_output_device_name")) ini_base["audio_output_device_name"] = output_saved_name;
            refresh_outputs();
            if (can_outputs()) host->audio_output_select(output_want.c_str());
        }
        // (the saved microphone by its name, not its place; the host told the row's choice. Off or the default: no list, no SDL
        // audio at the start)
        if (!mic_want.empty()) refresh_mics();
        else {
            if (opts.mic >= 2) opts.mic = 1;
            mic_tell_host();
        }
        if (!has_resolution && old_dynres >= 0) opts.resolution = old_dynres ? 0 : 1;
        opts.rumble = rumble_step(opts.rumble);   // (a hand-edited 60: 50, on the arrows' steps)
        opts.vibration = std::min(std::max(opts.vibration, 0), 2);   // ((Triforce) 11-24: Auto, Basic or Off)
        opts.ds_hd_haptics = opts.ds_hd_haptics != 0;
        // (Game speed is Real time by default now: Per frame played at half speed at 30 fps, the "slow motion" players
        // reported. An options file from before kept the old default whether chosen or not: Real time for it too)
        if (!v2) opts.realtime = 1;
        // (Descriptor reuse is on by default from options_version 4: a file from before wrote its 0 whether chosen or not, as
        // the off default it then was; fewer stutters and a better 1% low in the field, the flash checks clean, 2026-11-10)
        if (version < 4) opts.descriptor_reuse = 1;
        // ((Triforce, 11-16, the owner: "make these game defaults also") From options_version 5 Sampler cache, Fast pipeline
        // link, Lazy write-back and Opaque textures as BC1 are on and NVIDIA Reflex is On + Boost by default: a file from before
        // wrote their old off defaults whether chosen or not. The rows read before the menu (vk_draw.cpp menu_env_on, vk_memory.cpp
        // lazy_decide) take the same rule; Replay helper threads are Automatic and Descriptor reuse on already)
        if (version < 5) {
            opts.sampler_cache = 1, opts.fast_pipeline_link = 1, opts.lazy_write_back = 1, opts.tex_bc1 = 1, opts.reflex = 2;
            tex_bc1_at_start = opts.tex_bc1;
        }
        // ((Triforce, 11-16, the owner: "on by default") From options_version 6 Start next frame early is on by default: a file
        // from before wrote its old off default whether chosen or not. vk_replay.cpp tail_wanted reads it before the menu, by the
        // same rule)
        if (version < 6) opts.tail_early = 1;
        // ((Triforce, 11-17, the owner: "Have frame pacing be on by default for all current installs") From options_version 7
        // Frame pacing is on by default: a file from before wrote its old off default whether chosen or not, so every install
        // turns it on once; one written from 7 on keeps what was chosen)
        if (version < 7) opts.pace = 1;
        // ((Triforce, 11-16, the owner: "remove monitors shape as a option keep 16:9 16:10 21:9 32:9") Before options_version 6
        // the Ultrawide row's 1 was Monitor's shape; now it is 16:10. Such a file's 1 becomes the shape nearest the main
        // monitor's, as host/hos_main.c read it at this start (ultrawide_rows.h), on every system (main_screen)
        opts.ultrawide = ultrawide_row_read(opts.ultrawide, version, (int)main_screen().w, (int)main_screen().h);
        // ((Triforce) Before options_version 8 the sizes 5120x1440 and 5120x2160 were the game's frame, and the Ultrawide row
        // gave the picture's shape there too: with the row on another shape than theirs, the 16:9 size of their height, which
        // gives that picture now, as host/nn_applet.c read it at this start (output_sizes.h output_res_read))
        const bool legacy_output = output_legacy_file(version, ini_base.count("output_width") || ini_base.count("output_height") || ini_base.count("output_custom_size"));
        opts.output_res = output_file_read(opts.output_res, version, opts.ultrawide,
                                          ini_base.count("output_width") || ini_base.count("output_height") || ini_base.count("output_custom_size"));
        merged_rows::migrate(legacy_output && version == 8 ? 7 : version, before7,
                             opts.output_res, opts.lstick_dead_zone, opts.rstick_dead_zone);
    }
    // An opt-in profile for 4 GB cards: keep existing options authoritative, but make a first run usable on
    // low-VRAM hardware without requiring the menu to render first. ((Triforce, options_version 7) What the Quality preset's
    // Minimum set, without the preset: the 3D at 50%, the handheld profile's output, the smallest textures, frames shown
    // evenly; the memory budgets are the card's own)
    first_start_no_file = !has_options;   // ((Triforce, 11-22, PRESENT-46) for menu_first_start, once the card is known)
    sim_turf_init(ini_path());   // ((Triforce, 11-24) the Simulated turf page's own file, beside this one)
    if (!has_options && getenv("RX_VK_LOW_SPEC") && atoi(getenv("RX_VK_LOW_SPEC")) != 0) {
        opts.resolution = ur::snap(upscaler(), 4), opts.output_res = merged_rows::kHandheldOutput, opts.tex_detail = 3;
        opts.pace = 1, opts.realtime = 1, opts.sharpness = 0;
    }
    // ((Triforce, FG-9) the row's whole range, 0 Off to 9 AMD's frame generation, for a lab run's pin: 2 to 8 alone before.
    // (options_version 7) The merged Frame generation row follows it at merged_sync below)
    if (const char* e = getenv("RX_VK_FRAMEGEN_MULT")) opts.framegen = framegen_rows::env_row(e);
    if (const char* e = getenv("RX_VK_PACE")) opts.pace = atoi(e) != 0;
    // ((Triforce, options_version 7) Reflex holding the frame rate cap with DLSS frame generation, for a run: off otherwise,
    // until it has been played (vk_menu.h reflex_limit). The same switch as without frame generation, vk_reflex.cpp reflex_pace)
    if (const char* e = getenv("RX_VK_REFLEX_LIMIT")) opts.reflex_limit = atoi(e) != 0;
    // ((Triforce, options_version 7) the window's filter for this run, in place of the one the sizes choose: menu_note_present_sizes)
    if (const char* e = getenv("RX_VK_UPSCALE")) opts.upscale = std::min(std::max(atoi(e), 0), 3);
    if (const char* e = getenv("HOS_REALTIME_STEP")) opts.realtime = atoi(e) != 0;
    if (const char* e = getenv("HOS_DYNRES")) opts.resolution = atoi(e) != 0 ? 0 : 1;
    if (const char* e = getenv("HOS_OUTPUT_RES")) opts.output_res = output_choice(atoi(e));
    output_adopt_screen();   // (an old file's Screen: that screen's size, as a size)
    lang_load();   // (Triforce: the Game language row, from language.txt)
    merged_sync();   // ((Triforce, options_version 7) the merged rows from what was read)
    restart_init();   // (what this run started with: the rows that take a restart differ from it once changed)
}

namespace {
// ---- ((Triforce) Auto (this PC), the Graphics tab's first row: auto_settings.h. Off (the default): nothing here runs but one
// comparison. On: auto_apply sets the rows from the hardware when the row is turned On, or at a start whose hardware differs
// from the one it chose for (auto_start); the replay's 120-present windows tune them in play (menu_auto_tune, on the replay's
// thread, asks; auto_tick, on the menu's, sets). RX_VK_AUTO_TUNE=0: no tuning in play ----
bool auto_applying = false;   // (auto_apply's own changes: no row turns Auto Off)
std::atomic<int> auto_generation{0};   // (a new choice: the tuning starts again)
std::atomic<int> auto_request{0};      // (the tuning's step for auto_tick: action | packed state << 8, 0 none)
enum { AUTO_GRASS = 1, AUTO_SHADOW, AUTO_RES_LIGHTER, AUTO_RES_HEAVIER, AUTO_SETTLED };
auto_settings::Hardware auto_hardware() {
    auto_settings::Hardware hw;
    const VkPhysicalDeviceProperties& p = dev.props;
    hw.vendor = p.vendorID == 0x10de ? auto_settings::NVIDIA : p.vendorID == 0x1002 ? auto_settings::AMD
              : p.vendorID == 0x8086 ? auto_settings::INTEL : auto_settings::OTHER;
    hw.integrated = p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;
    // (the device's mesh shaders; a card the Mesh shaders row runs as compute has them all the same)
    hw.mesh_native = dev.mesh_shader || opts.mesh_mode == 1;
    hw.dlss_runs = dlss_why() == DLSS_OK;
    hw.fsr4_runs = fsr4_why() == FSR_OK;
    hw.vram_mb = (uint32_t)(device_vram_bytes() >> 20);
    if (const char* e = getenv("RX_VK_AUTO_VRAM_MB")) hw.vram_mb = (uint32_t)std::max(0, atoi(e));   // (the lab: another card's memory)
    hw.threads = (int)cpu_count();
#ifdef _WIN32
    MEMORYSTATUSEX m{};
    m.dwLength = sizeof m;
    if (GlobalMemoryStatusEx(&m)) hw.ram_mb = (uint32_t)(m.ullTotalPhys >> 20);
#else
    const long pages = sysconf(_SC_PHYS_PAGES), page = sysconf(_SC_PAGE_SIZE);
    if (pages > 0 && page > 0) hw.ram_mb = (uint32_t)(((uint64_t)pages * (uint64_t)page) >> 20);
#endif
    return hw;
}
/// The rows set from the hardware (when: for the log). keep: saved here (at a start; set_row saves its own)
void auto_apply(const char* when, bool keep) {
    if (!dev.device) return;   // (no card yet: auto_start chooses once it is known)
    const auto_settings::Hardware hw = auto_hardware();
    const auto_settings::Choice c = auto_settings::choose(hw);
    auto_applying = true;
    opts.dlss = c.upscaler;
    opts.resolution = c.resolution;
    opts.tex_detail = c.tex_detail;
    __atomic_store_n(&opts.shadow_res, c.shadow_res, __ATOMIC_RELAXED);
    __atomic_store_n(&opts.grass_distance, c.grass, __ATOMIC_RELAXED);
    opts.auto_for = auto_settings::fingerprint(hw, dev.props.vendorID, dev.props.deviceID);
    opts.auto_tune = 0;
    auto_generation.fetch_add(1, std::memory_order_relaxed);
    auto_applying = false;
    logf("menu: Auto (this PC): %s: %s: Upscaler %s, Render resolution %s, Texture detail %s, Shadow resolution %s, Grass "
         "distance %s (%s, %u MB of video memory, %u MB of RAM, %d threads)", when, c.why, tx_upscaler(opts.dlss),
         tx_resolution(opts.resolution), tx_tex_detail(opts.tex_detail), tx_shadow_res(opts.shadow_res),
         tx_grass_distance(opts.grass_distance), dev.props.deviceName, (unsigned)hw.vram_mb, (unsigned)hw.ram_mb, hw.threads);
    if (keep) save();
}
/// (set_row, after a row's change) The Auto row turned On: its choice now. A row it sets changed by hand while it is On: Off
void auto_row_set(const int* value) {
    if (auto_applying) return;
    if (value == &opts.auto_pc) {
        if (opts.auto_pc) auto_apply("turned On", false);
        else logf("menu: Auto (this PC): turned Off (the rows stay as they are)");
        return;
    }
    if (opts.auto_pc && (value == &opts.dlss || value == &opts.resolution || value == &opts.tex_detail ||
                         value == &opts.shadow_res || value == &opts.grass_distance)) {
        opts.auto_pc = 0;
        logf("menu: Auto (this PC): Off, a row it sets changed by hand");
    }
}
/// (menu_first_start: the card is known, before the host's one read of the rows that take a restart) Auto On: chosen again
/// for hardware other than the one it chose for, the rows that take a restart then this run's
void auto_start() {
    static bool done;
    if (done || !opts.auto_pc) return;
    done = true;
    const int32_t fp = auto_settings::fingerprint(auto_hardware(), dev.props.vendorID, dev.props.deviceID);
    if (fp == opts.auto_for) {
        logf("menu: Auto (this PC): the settings chosen for this PC before (tuning state %d)", opts.auto_tune);
        return;
    }
    auto_apply("new hardware", true);
    for (const Row& r : rows)
        if (r.value == &opts.resolution || r.value == &opts.dlss) restart_state.restart_value(restart_slot_of(r), restart_value_of(r));
}
/// (the tuning's Render resolution steps, dir -1 lighter, +1 heavier: the upscaler's own steps by size, up to best_step;
/// none from Auto (dynamic) or an engine's native AA)
int auto_res_step(int up, int res, int dir) {
    if (ur::full_scale(up)) return res;
    const int p = ur::percent(ur::snap(up, res));
    if (!p) return res;
    const int top = ur::percent(auto_settings::best_step(ur::engine(up)));
    int n = 0, best = res, best_p = dir < 0 ? 0 : 1000;
    const int* s = ur::steps(up, n);
    for (int i = 0; i < n; i++) {
        const int q = ur::percent(s[i]);
        if (!q) continue;
        if (dir < 0 ? (q < p && q > best_p) : (q > p && q < best_p && q <= top)) best = s[i], best_p = q;
    }
    return best;
}
/// (the cap the game runs to: the Frame rate cap row's, the display's refresh for Monitor's rate and Uncapped)
float auto_cap_fps() {
    const int v = opts.fps_cap;
    static const int caps[] = {60, 90, 120, 144, 165, 240};
    if (v < 0) return v == -1 ? 45.0f : v == -2 ? 40.0f : 30.0f;
    if (v >= fps_cap::kMonitor) {
        const int cap = fps_cap::of_display(display_refresh_mhz());
        return cap ? (float)cap : 60.0f;
    }
    return (float)caps[std::min(v, 5)];
}
/// (menu_tick, the menu's thread: the tuning's step set, saved, said)
void auto_tick() {
    const int req = auto_request.exchange(0, std::memory_order_acquire);
    if (!req || !opts.auto_pc) return;
    const int action = req & 0xff;
    const int up = upscaler();
    char was[48];
    snprintf(was, sizeof was, "%s", tx_resolution(opts.resolution));
    if (action == AUTO_GRASS) __atomic_store_n(&opts.grass_distance, std::max(0, opts.grass_distance - 1), __ATOMIC_RELAXED);
    if (action == AUTO_SHADOW) __atomic_store_n(&opts.shadow_res, std::max(0, opts.shadow_res - 1), __ATOMIC_RELAXED);
    if (action == AUTO_RES_LIGHTER || action == AUTO_RES_HEAVIER)
        opts.resolution = auto_res_step(up, opts.resolution, action == AUTO_RES_LIGHTER ? -1 : 1);
    opts.auto_tune = req >> 8;
    save();
    if (action == AUTO_GRASS || action == AUTO_SHADOW)
        logf("menu: Auto (this PC): frames missed with the GPU busy: %s one step lower, to %s (at once)",
             action == AUTO_GRASS ? "Grass distance" : "Shadow resolution",
             action == AUTO_GRASS ? tx_grass_distance(opts.grass_distance) : tx_shadow_res(opts.shadow_res));
    else if (action != AUTO_SETTLED)
        logf("menu: Auto (this PC): %s: Render resolution %s to %s, from the next start", action == AUTO_RES_LIGHTER
             ? "frames missed with the GPU busy" : "the cap held with the GPU under half busy", was, tx_resolution(opts.resolution));
    else logf("menu: Auto (this PC): the settings hold this PC's cap: tuning done");
}
/// ((Triforce) the replay's thread, every 120 presents: Auto (this PC)'s tuning while the row is On (not with frame
/// generation, whose made frames are not the game's). Lighter: the Grass distance, then the Shadow resolution, a step at
/// once; then the Render resolution, for the next start (it takes a restart: the tuning is done for this run). Heavier: the
/// Render resolution, for the next start
void auto_tune_window(double gpu_ms, double draws, double fps) {
    static const bool off = getenv("RX_VK_AUTO_TUNE") && atoi(getenv("RX_VK_AUTO_TUNE")) == 0;
    if (off || !__atomic_load_n(&opts.auto_pc, __ATOMIC_RELAXED) || framegen_on()) return;
    static auto_settings::Tuning t;
    static int generation = -1;
    static bool settled;
    if (generation != auto_generation.load(std::memory_order_relaxed)) {
        generation = auto_generation.load(std::memory_order_relaxed);
        t = auto_settings::Tuning{};
        auto_settings::unpack(__atomic_load_n(&opts.auto_tune, __ATOMIC_RELAXED), t, settled);
    }
    const int grass = __atomic_load_n(&opts.grass_distance, __ATOMIC_RELAXED);
    const int shadow = __atomic_load_n(&opts.shadow_res, __ATOMIC_RELAXED);
    const int up = upscaler(), res = __atomic_load_n(&opts.resolution, __ATOMIC_RELAXED);
    const bool lighter_res = auto_res_step(up, res, -1) != res, heavier_res = auto_res_step(up, res, 1) != res;
    const auto_settings::Verdict v = auto_settings::tune(t, (float)gpu_ms, (float)draws, (float)fps, auto_cap_fps(),
                                                         grass > 0 || shadow > 0 || lighter_res, heavier_res);
    int action = 0;
    if (v == auto_settings::LIGHTER) action = grass > 0 ? AUTO_GRASS : shadow > 0 ? AUTO_SHADOW : AUTO_RES_LIGHTER;
    if (v == auto_settings::HEAVIER) action = AUTO_RES_HEAVIER;
    if (action == AUTO_RES_LIGHTER || action == AUTO_RES_HEAVIER) t.done = true;   // (it applies at the next start)
    if (v == auto_settings::KEEP) action = AUTO_SETTLED, settled = true;
    if (v == auto_settings::CPU_BOUND)
        logf("menu: Auto (this PC): %.1f fps of %.0f with the GPU %.1f ms a frame: the processor holds it; nothing changed this run",
             t.fps_mid, auto_cap_fps(), t.gpu_mid);
    if (action) auto_request.store(action | auto_settings::pack(t, settled) << 8, std::memory_order_release);
}
}   // namespace
/// ((Triforce) vk_replay.cpp, every 120 presents: Auto (this PC)'s tuning (auto_tune_window)
void menu_auto_tune(double gpu_ms, double draws, double fps) { auto_tune_window(gpu_ms, draws, fps); }
/// ((Triforce) a render thread's frame for the FPS counter's Breakdown lane (fps_detail_sample): its time recording and its
/// time waiting, ns, added each frame. Never called without a render thread: the lane is not shown then
void menu_fps_render_thread(int64_t work_ns, int64_t wait_ns) {
    rt_work_ns.fetch_add(work_ns, std::memory_order_relaxed), rt_wait_ns.fetch_add(wait_ns, std::memory_order_relaxed);
    rt_seen.store(true, std::memory_order_relaxed);
}

namespace {
/// ((Triforce) The Output resolution's mode_list: the display modes of the screen the game's window is on (the main one with no
/// window), and the common sizes of each shape up to its size (output_modes.h), as the game takes them (output_size_used), each
/// once. Read the first time the menu opens (Windows: EnumDisplaySettingsW; elsewhere the renderer cannot ask SDL for the
/// modes: the common sizes up to the screen the window opens on)
void read_mode_sizes() {
    static bool read = false;
    if (read) return;
    read = true;
    std::vector<Out>& sizes = mode_list;
    std::vector<output_modes::Size> modes;
    unsigned sw = 0, sh = 0;
#ifdef _WIN32
    MONITORINFOEXW mi{};
    mi.cbSize = sizeof mi;
    const HWND w = app_window();
    const bool known = GetMonitorInfoW(w ? MonitorFromWindow(w, MONITOR_DEFAULTTONEAREST) : MonitorFromPoint(POINT{0, 0}, MONITOR_DEFAULTTOPRIMARY), &mi);
    DEVMODEW dm{};
    dm.dmSize = sizeof dm;
    if (known && EnumDisplaySettingsW(mi.szDevice, ENUM_CURRENT_SETTINGS, &dm)) sw = dm.dmPelsWidth, sh = dm.dmPelsHeight;
    for (DWORD i = 0; known && i < 4096; i++) {
        DEVMODEW m{};
        m.dmSize = sizeof m;
        if (!EnumDisplaySettingsW(mi.szDevice, i, &m)) break;
        modes.push_back({(unsigned)m.dmPelsWidth, (unsigned)m.dmPelsHeight});
        sw = std::max(sw, (unsigned)m.dmPelsWidth), sh = std::max(sh, (unsigned)m.dmPelsHeight);   // (its largest mode: its own)
    }
#else
    if (const Screen* s = screen_opening()) sw = s->native.w, sh = s->native.h;
#endif
    for (const output_modes::Size& m : output_modes::offered(sw, sh, modes)) {
        unsigned uw = 0, uh = 0;
        if (!output_size_used(m.w, m.h, &uw, &uh)) continue;
        if (std::none_of(sizes.begin(), sizes.end(), [&](const Out& o) { return o.w == uw && o.h == uh; })) sizes.push_back(Out{uw, uh});
    }
    logf("menu: the Output resolution offers %zu sizes of the screen's %zu display modes and the common ones (screen %ux%u)",
         sizes.size(), modes.size(), sw, sh);
}
}   // namespace

/// (Triforce, 11-22, the performance audit's PRESENT-46, after Source A's) A first start sized to the card, with
/// RX_VK_FIRST_START_AUTO (off unless set: first_start.h): with no options file, RX_VK_LOW_SPEC not asked and no switch
/// setting the Render resolution, a weak card (an integrated GPU, no mesh shaders, 4.5 GB of video memory or less) starts
/// with the Render resolution row at 50%, or at 33% for an integrated GPU beside 4 threads or fewer, in place of Auto.
/// Only that row: the upscaler, the textures and the output stay as they are, and nothing is saved, so every start chooses
/// again until the player saves options of their own. Called once the device is made (vk_main.cpp mkwvk_init: menu_init
/// runs before the card is known), before the host's one read of the row
void menu_first_start() {
    static bool done;
    if (done) return;
    done = true;
    auto_start();   // ((Triforce) Auto (this PC) On: chosen again for new hardware)
    const int64_t asked = first_start::switch_mb(getenv("RX_VK_FIRST_START_AUTO"));
    const bool low_spec = getenv("RX_VK_LOW_SPEC") && atoi(getenv("RX_VK_LOW_SPEC")) != 0;
    if (!first_start::applies(!first_start_no_file, low_spec, getenv("HOS_DYNRES") != nullptr, asked)) return;
    first_start::Card card;
    card.integrated = dev.props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;
    card.mesh_shaders = dev.mesh_shader;
    card.vram_mb = asked > 0 ? (uint64_t)asked : device_vram_bytes() >> 20;
    card.threads = cpu_count();
    const first_start::Choice choice = first_start::choose(card);
    if (!choice.row) {
        logf("menu: first start: no change (%s: %llu MB of video memory%s, mesh shaders %s; RX_VK_FIRST_START_AUTO)",
             first_start::why_text(choice.why), (unsigned long long)card.vram_mb, asked > 0 ? " asked" : "",
             card.mesh_shaders ? "yes" : "no");
        return;
    }
    opts.resolution = ur::snap(upscaler(), choice.row);
    // (the row takes a restart: what this run starts with is this, not menu_init's)
    for (const Row& r : rows)
        if (r.value == &opts.resolution) restart_state.restart_value(restart_slot_of(r), restart_value_of(r));
    logf("menu: first start: tier 1 (%s, %llu MB of video memory%s, %u threads): Render resolution %s "
         "(RX_VK_FIRST_START_AUTO; nothing is saved)", first_start::why_text(choice.why), (unsigned long long)card.vram_mb,
         asked > 0 ? " asked" : "", card.threads, tx_resolution(opts.resolution));
}

// ((Triforce VR) the VR tab's Render resolution over the Graphics tab's while VR is on: read once, at the start, as both are)
static int resolution_in_effect() {
    static const int v = opts.vr && opts.vr_resolution > 0 && opts.vr_resolution < ur::kValues ? opts.vr_resolution : -1;
    return v >= 0 ? v : opts.resolution;
}
bool resolution_auto() { return resolution_in_effect() == 0; }
int resolution_scale() {
    // ((Triforce) 11-24: the Upscaler's own step for the saved scale, set_row)
    const float s = upscaler_rows::percent(ur::snap(upscaler(), resolution_in_effect())) / 100.0f;
    return s > 0 ? (int)(twelfths(s) * 10000.0f / 12.0f + 0.5f) : 0;   // (the twelfth game_size labels)
}

const std::string& menu_gpu_name() { return gpu_want; }

void menu_set_gpu_count(int count) {
    for (Row& r : rows) {
        if (r.value == &opts.gpu_device) {
            r.hi = count;
            if (opts.gpu_device > count) opts.gpu_device = 0;
        }
    }
    restart_init();
    for (int i = 0; i < kRows; i++)   // (the row's value the game started with, the cards counted)
        if (rows[i].value == &opts.gpu_device) restart_state.restart_value(restart_slot[i], opts.gpu_device);
}

bool menu_is_open() { return open_now.load(std::memory_order_relaxed); }
bool menu_embedded() { return open_now.load(std::memory_order_relaxed) && embed_open; }
bool menu_game_options() { return game_options_shown(); }   // ((Triforce VR) the game's Options screen runs, our tabs over it)
int menu_grass_distance() { return __atomic_load_n(&opts.grass_distance, __ATOMIC_RELAXED); }   // (the menu's thread writes it)
// (the tools off on the Debug tab: flight, the free camera and heart protection put away; -1, heart protection never set, is the
// host's own HOS_OOT_PROTECT_HEARTS)
int menu_heart_protection() {
    const int v = protect_hearts.load(std::memory_order_relaxed);
    return cheats_on() || v < 0 ? v : 0;
}
int menu_player_flight() { return cheats_on() ? player_flight.load(std::memory_order_relaxed) : -1; }
int menu_free_camera() { return cheats_on() ? free_camera.load(std::memory_order_relaxed) : 0; }
int menu_link_speed() { return cheats_on() ? link_speeds[std::clamp(link_speed.load(std::memory_order_relaxed), 0, kLinkSpeeds - 1)] : 100; }
/// (Triforce: with the Debug tools turned off meanwhile, what a tool asked and the game's side had not yet taken is dropped,
/// as flight, the free camera and heart protection are put away: the game's side takes it at Link's update, not while paused)
int menu_take_cheat_action() {
    const int action = cheat_action.exchange(0, std::memory_order_relaxed);
    return cheats_on() ? action : 0;
}
int menu_take_share_ask() { return share_ask.exchange(0, std::memory_order_relaxed); }
int menu_take_debug_ask() {
    std::lock_guard lk(names_mu);
    return names_ask.take();
}
int menu_take_amiibo_ask() {
    std::lock_guard lk(names_mu);
    return amiibo_ask.take();
}
int menu_take_mod_cheat() { return mod_cheats.take(); }   // (Triforce: a mod's cheat the player switched, for the host)
int menu_take_file_ask() { return save_files.take_ask(); }   // (Triforce: the save file chosen that is not this run's, for the host)

// ---- (Triforce) the options' own sounds: the game's interface sounds, after NX2navi's menu sounds. menu_tick says which
// (menu_sound_events.h), the host's sound thread takes them (vk_api.h HOS_OPT_MENU_SOUND) and plays them from the player's
// game files (host/menu_sound.c), at the Audio tab's Menu sounds row's level ----
static_assert(menu_sound::kOpen == HOS_MENU_SOUND_OPEN && menu_sound::kClose == HOS_MENU_SOUND_CLOSE &&
              menu_sound::kCursor == HOS_MENU_SOUND_CURSOR && menu_sound::kDecide == HOS_MENU_SOUND_DECIDE &&
              menu_sound::kCancel == HOS_MENU_SOUND_CANCEL && menu_sound::kTabLeft == HOS_MENU_SOUND_TAB_LEFT &&
              menu_sound::kTabRight == HOS_MENU_SOUND_TAB_RIGHT && menu_sound::kFanfare == HOS_MENU_SOUND_FANFARE &&
              menu_sound::kSysCursor == HOS_MENU_SOUND_SYS_CURSOR && menu_sound::kSysDecide == HOS_MENU_SOUND_SYS_DECIDE &&
              menu_sound::kLast + 1 == HOS_MENU_SOUND_N,
              // ((Triforce) the fanfare and the system menu's two: the Mods screen's and entry's own, not the options')
              "menu_sound_events.h's sounds are vk_api.h's HOS_MENU_SOUND_*");
static_assert(menu_sound::kPageAsk == 5, "the restart question is page 5");
static menu_sound::Queue sound_queue;
constexpr int kSoundPageMotion = 7;   // (the Motion page is a tab no strip shows, opened from a row of Controls: a page, to the ear)
// ((Triforce, 11-22, N64 Classic, after the owner's test: "do a pass for the SfX playing in the new sub menu") and the
// Remembered page, opened from a row of Graphics, likewise. As Graphics' rows alone its opening and its Back were silent:
// both take their press for themselves (press[7], press[5] false again by the sound's turn), and the row and value the
// cursor stood on could be the same number on both)
constexpr int kSoundPageN64 = 10;
static_assert(kSoundPageN64 != kModsPage && kSoundPageN64 != kModsRowPage && kSoundPageN64 != kSoundPageMotion,
              "the Remembered page's page, to the ear, is a number of its own");
constexpr int kSoundPageSimTurf = 11;   // ((Triforce, 11-24) and the Simulated turf page, as the Remembered page)
static_assert(kSoundPageSimTurf != kModsPage && kSoundPageSimTurf != kModsRowPage && kSoundPageSimTurf != kSoundPageMotion &&
              kSoundPageSimTurf != kSoundPageN64, "the Simulated turf page's page, to the ear, is a number of its own");
/// What the options show now, as far as their sounds go (menu_sound::State): menu_tick takes it before and after its input
static menu_sound::State sound_state() {
    menu_sound::State s;
    s.open = open_now.load();
    if (!s.open) return s;
    s.embedded = embed_open || game_options_shown();
    const bool n64_page = page == 0 && cur_tab == TAB_N64;   // ((Triforce, N64 Classic) the Remembered page)
    const bool turf_page = page == 0 && cur_tab == TAB_SIM_TURF;   // ((Triforce, 11-24) the Simulated turf page)
    const bool motion = page == 0 && sub_page(cur_tab) && !n64_page && !turf_page;   // (the Motion page, and the other pages rows open, as it)
    s.page = motion ? kSoundPageMotion : n64_page ? kSoundPageN64 : turf_page ? kSoundPageSimTurf : page;
    s.tab = motion || n64_page || turf_page ? page_parent(cur_tab) : cur_tab;
    auto hashed = [](const std::string& t) {
        int64_t h = 1469598103934665603LL;
        for (const char ch : t) h = (h ^ (unsigned char)ch) * 1099511628211LL;
        return h;
    };
    if (page == 0) {   // (a tab's rows: the row chosen and what it is set to; a debug tool's and a mod's cheat's as they show it)
        const Row& r = rows[tab_row_to_global(cur_tab, tab_selected[cur_tab])];
        s.cursor = tab_selected[cur_tab];
        s.mode = pending ? menu_sound::kModeConfirm : menu_sound::kModeNone;
        if (r.value) s.value = *r.value;
        else if (mod_cheat_slot(r.name) >= 0) s.value = mod_cheats.is_on(mod_cheat_slot(r.name));
        else if (r.cheat >= 0) s.value = hashed(cheat_value(r.cheat));
    } else if (page == 1) {   // (Controls: its own rows' values, a control's bindings)
        const int i = csel - kTop;
        s.cursor = csel * kCols + ccol;
        s.mode = listening ? menu_sound::kModeListen : menu_sound::kModeNone;
        if (i < 0) {
            const Row& r = rows[tab_row_to_global(TAB_PAGE, csel)];
            if (r.value) s.value = *r.value;
        } else if (i < kControls && can_bind()) {
            const int b = controls[i].button;
            s.value = keys_only(i) ? 0 : host->binding(HOS_BIND_PAD, b, 0);
            s.value = (s.value * 4099 + host->binding(HOS_BIND_KEY, b, 0)) * 4099 + host->binding(HOS_BIND_KEY, b, 1);
        }
    } else if (page == 3) {
        s.cursor = teleport_choice;
    } else if (page == 4) {
        s.cursor = item_choice, s.group = inventory_filter;
        s.mode = inventory_amount ? menu_sound::kModeEdit : menu_sound::kModeNone;
        // ((Triforce) what the card shows for the chosen item, the change waiting for the game included: an amount stepped
        // or an item unlocked ticks as a value of a tab's row does)
        s.value = debug_pending::shown(cheat_action.load(std::memory_order_relaxed), item_choice,
                                       item_counts[item_choice].load(std::memory_order_relaxed));
    } else if (page == 5) {
        s.cursor = ask_sel;
    } else if (page == 6) {
        s.cursor = names_page[names_kind].choice, s.group = names_page[names_kind].group;
        s.mode = names_edit ? menu_sound::kModeEdit : menu_sound::kModeNone;
    } else if (page == kAchPage) {
        s.cursor = ach_view.choice, s.group = ach_view.page;
    } else if (page == kFilesPage) {
        s.cursor = files_choice, s.mode = files_wait >= 0 ? menu_sound::kModeConfirm : menu_sound::kModeNone;
    }
    return s;
}
int menu_take_sound() { return sound_queue.take(prof_now()); }   // (the options' next sound, for the host's sound thread)
void mods_sound(int id) { if (opts.menu_sounds > 0) sound_queue.put(id, prof_now()); }   // ((Triforce) the Mods entry's and screen's own sounds
int menu_mods_selected() {   // ((Triforce) and the file select opened from Save Select, the entry under Mods on the title)
    return open_now.load(std::memory_order_relaxed) && (page == kModsRowPage || page == kModsPage || (page == kFilesPage && files_at_title));
}
/// ((Triforce, 11-20) the owner: "have the in game mods menu in the title screen play the shop theme quietly in the
/// background ... it mutes the title screen music's audio while in the mod menu and fades in/out". What the host's sound
/// thread asks each block (host/mods_music.c): 2 while the Mods screen is open from the title's list, 1 while that list is
/// there with its entry (the tune is read then, ahead of the screen), 0 otherwise: the pause menu's Mods screen keeps the
/// music of where the player is
int menu_mods_music() {
    if (!mods_title_list()) return 0;
    if (open_now.load(std::memory_order_relaxed) && page == kModsPage) return 2;
    return mods_list_fresh() || mods_title_fading() ? 1 : 0;
}
// ((Triforce) the HUD placement rows for host/hos_wide_ui.c (vk_replay.cpp's option): pack_placement above
int menu_hud_option(int id) {
    switch (id) {
    case HOS_OPT_HUD_PLACEMENT: return opts.hud_placement;
    case HOS_OPT_HUD_HEALTH: return opts.hud_placement ? pack_placement(opts.hud_health_x, opts.hud_health_y, opts.hud_health_scale) : HOS_HUD_DEFAULT_PLACEMENT;
    case HOS_OPT_HUD_BUTTONS: return opts.hud_placement ? pack_placement(opts.hud_buttons_x, opts.hud_buttons_y, opts.hud_buttons_scale) : HOS_HUD_DEFAULT_PLACEMENT;
    case HOS_OPT_HUD_MINIMAP: return opts.hud_placement ? pack_placement(opts.hud_minimap_x, opts.hud_minimap_y, opts.hud_minimap_scale) : HOS_HUD_DEFAULT_PLACEMENT;
    default: return 0;
    }
}
int menu_text_wanted() {   // ((Triforce) the Mods screen's search; the Output width and height rows' digits)
    return mods_text_wanted.load(std::memory_order_relaxed) || size_text_wanted.load(std::memory_order_relaxed) ? 1 : 0;
}
int menu_bug_shot() { return bugshot_state(); }

// ((Triforce) 11-24) A bug capture's settings changed from the defaults (HOS_OPT_BUG_SETTINGS, host/bug_capture.c's
// capture.txt): the rows whose saved value is not the built-in default's (Options{}), as the menu shows them, a
// "Name: value (default: value)" line each. Every row's default is a fixed value here (an Automatic or Auto is a value of
// its own, not one worked out for this PC), so a default is never guessed. The hidden rows are written too: they hold what
// the merged rows (HDR, Frame generation, ...) stand for. The Custom size's sides only while the Output resolution is
// Custom (restart_inert); a microphone chosen by its name is not named (a device's name can be a person's). Written on the
// capture's thread, as the host's other option reads are: nothing is changed
std::mutex bug_settings_mu;
std::string bug_settings_text;
size_t bug_settings_at = 0;
std::string changed_rows_text() {
    static const Options defaults{};
    std::string out;
    int changed = 0;
    const int* said[kRowsEnd];
    int said_n = 0;
    for (int i = 0; i < kRowsEnd; i++) {
        const Row& r = rows[i];
        const char* at = (const char*)r.value;
        if (!r.value || !r.text || r.heading || at < (const char*)&opts || at >= (const char*)(&opts + 1)) continue;
        if (restart_inert(r) || std::find(said, said + said_n, r.value) != said + said_n) continue;
        const int was = *(const int*)((const char*)&defaults + (at - (const char*)&opts));
        if (*r.value == was) continue;
        said[said_n++] = r.value;
        changed++;
        out += r.name;
        out += ": ";
        out += r.value == &opts.mic && *r.value >= 2 ? "a microphone by its name" : r.text(*r.value);
        out += " (default: ";
        out += r.value == &opts.mic && was >= 2 ? "a microphone by its name" : r.text(was);
        if (restart_changed(r)) out += "; takes effect after a restart";
        out += ")\n";
    }
    if (!changed) out = "Every option is at its default.\n";
    return out;
}
void menu_bug_settings_begin() {
    std::string text = changed_rows_text();
    std::lock_guard<std::mutex> lk(bug_settings_mu);
    bug_settings_text = std::move(text);
    bug_settings_at = 0;
}
int menu_take_bug_settings() {
    std::lock_guard<std::mutex> lk(bug_settings_mu);
    if (bug_settings_at >= bug_settings_text.size()) {
        bug_settings_text.clear();
        bug_settings_at = 0;
        return 0;
    }
    return (unsigned char)bug_settings_text[bug_settings_at++];
}

void menu_note_present_sizes(uint32_t picture_w, uint32_t picture_h, uint32_t window_w, uint32_t window_h) {
    const auto c = [](uint32_t v) { return (uint64_t)std::min(v, 0xffffu); };
    present_sizes.store(c(picture_w) << 48 | c(picture_h) << 32 | c(window_w) << 16 | c(window_h), std::memory_order_relaxed);
    // ((Triforce, options_version 7) the Window scaling filter row is gone: the picture is scaled to its place in the window by
    // AMD FSR 1 when it is enlarged, and by the plain linear copy otherwise (upscaler_rows.h auto_filter). RX_VK_UPSCALE fixes
    // it for a run (menu_init)
    // (its place: the window, or the part of it the picture's shape leaves between black bars, as vk_replay.cpp present_image
    // puts it, present_rect with the game's aspect)
    // (and the plain copy with HDR Native: the game's picture is HDR10 PQ in 10 bits, which the blit takes as it is
    // (upscaler_rows.h window_filter). framegen_scale takes it through RGBA16F images now ((Triforce, S5) for Sharpness at
    // the window and ultrawide's sides), but no filter pass is added at every present for it. The swapchain is made again
    // before this at a change of HDR (do_present), so dev.hdr is this present's)
    static const bool fixed = getenv("RX_VK_UPSCALE") != nullptr;
    if (fixed) return;
    const PresentAspect aspect{host && host->aspect_ratio ? host->aspect_ratio() : 0.0f};
    const PresentRect place = present_rect(picture_w, picture_h, nullptr, window_w, window_h, aspect);
    const bool native_hdr = dev.hdr && opts.hdr == 2;
    // ((Triforce, 11-22, N64 Classic, step 4) its TV in the filter's place while it runs, at 1:1 too (upscaler_rows.h tv_filter)
    const int filter = ur::tv_filter(ur::window_filter(picture_w, picture_h, place.w, place.h, native_hdr), n64_tv_now(native_hdr));
    const bool same = picture_w == place.w && picture_h == place.h;
    const int tell = filter * 4 + native_hdr * 2 + same;
    static int told = -1;
    if (tell != told)
        logf("menu: the window's filter: %s (the picture %ux%u, shown at %ux%u)",
             filter == ur::kTvFilter ? "N64 Classic's TV" : filter == 3 ? "AMD FSR 1" : same ? "none, the sizes are the same"
             : native_hdr ? "the plain copy (HDR Native: its 10 bits kept)" : "the plain copy",
             picture_w, picture_h, place.w, place.h);
    told = tell;
    opts.upscale = filter;
}
void menu_note_frame(bool game_frame, int shown) {
    if (shown) shown_frames.fetch_add(shown, std::memory_order_relaxed);
    if (game_frame) game_frames.fetch_add(1, std::memory_order_relaxed);
    if (game_frame && fps_levels::measures(opts.show_fps)) {   // (Triforce: the frame times, on Full and the levels past On only)
        std::lock_guard lk(perf_mu);
        perf_stats::note(perf_ring, prof_now());
    }
}

// The Fullscreen row, F10 and Alt+Enter are one setting: the row asks the window's thread (host/display.c), Alt+Enter shows in the row
void fullscreen_tick() {
    static int applied = 0, settle = 0;
    const HWND main_window = app_window();
    if (!main_window) return;
    static const bool env = getenv("HOS_FULLSCREEN") != nullptr;   // (a test's own choice: the row is left alone)
    if (env) return;
    static int applied_screen = 0;   // ((Triforce) the Fullscreen screen row: while fullscreen, a change moves the window there)
    if (opts.fullscreen != applied || (applied && opts.fs_screen != applied_screen)) {
        applied = opts.fullscreen, applied_screen = opts.fs_screen;
        settle = 60;
        PostMessageA(main_window, WM_APP + 7, (WPARAM)applied, 0);
        return;
    }
    if (settle > 0) { settle--; return; }
    const int now = !(GetWindowLongA(main_window, GWL_STYLE) & WS_CAPTION);
    if (now != applied) {
        opts.fullscreen = applied = now;
        menu_refresh = true;
        save();
    }
}

/// A rate over the half-second that just ended. The first call only starts that interval: the frames since launch,
/// divided by one second, were shown as the rate the moment the counter was turned on.
bool fps_take(int64_t now, int64_t shown, int64_t game, int64_t* next, int64_t* last_shown, int64_t* last_game,
              double* shown_rate, double* game_rate) {
    if (now < *next) return false;
    const bool have = *next != 0;
    if (have) {
        const double secs = (now - *next + 500000000) / 1e9;
        *shown_rate = (shown - *last_shown) / secs;
        *game_rate = (game - *last_game) / secs;
    }
    *last_shown = shown;
    *last_game = game;
    *next = now + 500000000;
    return have;
}

/// (Triforce) The performance overlay's title: "Triforce <this build>, game <the game's version>" in NX2navi's words ("NX2navi
/// %s, game %s"): the build as nx2/version.py stamps it (HOOKSHOT_VERSION: the release's name, "v0.4.0-test41", or git
/// describe's between releases, "v0.4.0-254-g436f9ac-dirty"; as the System tab shows it) without the fingerprint of its
/// sources after it, which would make the panel wider than NX2navi's; the game's 1.1.1, the one build Triforce makes it from
void perf_title(char* out, size_t n) {
    std::string build = HOOKSHOT_VERSION;
    if (const size_t at = build.find(" ("); at != std::string::npos) build.resize(at);
    snprintf(out, n, "Triforce %s, game %s", build.c_str(), kGameVersion);
}
/// (Triforce) A frame rate cap's text as NX2navi's Frame limit says it, "<n> FPS": its first number ("60 (the console's)",
/// "Monitor's rate (144)"); a text with no number as it is ("Monitor's rate", a display that gives none)
const char* perf_rate_text(const char* cap, char* out, size_t n) {
    const char* d = cap;
    while (*d && (*d < '0' || *d > '9')) d++;
    if (*d) snprintf(out, n, "%d FPS", atoi(d));
    else snprintf(out, n, "%s", cap);
    return out;
}
/// (Triforce) The Upscaling setting's value on the panel: the upscaler in effect with its mode ("NVIDIA DLAA (native)", "NVIDIA
/// DLSS, Quality (67%)"); with the game's own the words of its own way ("Game's own (dynamic)", "Game's own, 75% (1440x810)":
/// NX2navi names no scaler of the game's own, its Ocarina leaving the row out). The Upscaler and Render resolution rows
/// keep their own texts
const char* perf_upscaling_text(char* out, size_t n) {
    const char* res = tx_resolution(opts.resolution);
    if (upscaler() == ur::GAME) {
        if (resolution_auto()) snprintf(out, n, "Game's own (dynamic)");
        else snprintf(out, n, "Game's own, %s", res);
    } else if (!strncmp(res, "Native (", 8)) {
        snprintf(out, n, "%s (native)", tx_upscaler(0));
    } else {
        snprintf(out, n, "%s, %s", tx_upscaler(0), res);
    }
    return out;
}
/// (Triforce) Generated frames are shown now: DLSS frame generation's (its multiplier past 1) or frame generation's
/// (vk_framegen.cpp framegen_on: the renderer's own, AMD FSR 3.1's or AMD FSR 4's), as NX2navi shows its FG row by what runs
bool perf_fg_running() { return mkwvk::dlssg::multiplier() > 1 || framegen_on(); }
/// (Triforce) The Frame generation setting's value on the panel: what makes the frames, by name, as NX2navi's (its
/// perf_picture): "NVIDIA DLSS <n>x" while DLSS frame generation runs; while frame generation runs, AMD's FSR 4 library (with
/// the version it runs, NX2navi's fg4_label) where the row is at AMD FSR 4 and the library can make the frame, "AMD FSR 3.1, 4x"
/// where FSR 3.1 made the last frames (the Frame generation by row), else the renderer's own, "Triforce's own" with the row's value ("Triforce's own, 4x",
/// "Triforce's own, Auto"); "Off" while nothing makes frames (the row set where none can run too). AMD's library is never
/// asked here (why_known, version: what is known)
const char* perf_framegen_text(char* out, size_t n) {
    if (mkwvk::dlssg::multiplier() > 1) snprintf(out, n, "NVIDIA DLSS %dx", mkwvk::dlssg::multiplier());
    else if (!framegen_on()) snprintf(out, n, "Off");
    else if (opts.framegen == framegen_rows::FSR4 && fsr4fg::offered_known()) {
        const char* ver = fsr4fg::version();
        if (ver[0]) snprintf(out, n, "AMD FSR 4 library (%s)", ver);
        else snprintf(out, n, "AMD FSR 4 library");
    } else if (fsr3fi::frames_wanted() && framegen_maker() == kMakerFsr3) {   // ((Triforce) 11-24: who made the last set)
        snprintf(out, n, "AMD FSR 3.1, %s", tx_framegen(opts.framegen));
    } else {
        snprintf(out, n, "Triforce's own, %s", tx_framegen(opts.framegen));
    }
    return out;
}

/// (Triforce) The performance overlay's texts (NX2navi's full panel, draw_perf), made twice a second while the row is on Full
/// (menu_tick): the machine's latest sample (perf_machine.cpp's thread: nothing here waits for it), the frames' (the ring: the
/// rate, the mean and the longest over the last second, the lows over the last ten, as NX2navi's), the figures per frame
/// since the sample before, and the settings. The counts the figures come from are what the replay keeps anyway, plain counters
/// other threads write: read as they are, a value a moment old is as good here. shown and game: the counter's rates of the
/// last half second, frame generation's frames in shown
static void perf_sample(double shown, double game) {
    PerfView& v = perf_view;
    perf_stats::Summary second, ten;
    {
        std::lock_guard lk(perf_mu);
        if (!v.full) perf_ring = perf_stats::Ring{};   // (Full turned on now: the frames of the time before are not this window's)
        second = perf_stats::summarize(perf_ring, 1000000000ll);
        ten = perf_stats::summarize(perf_ring);
    }
    const bool fresh = !v.full;   // (Full turned on now: the figures per frame start anew too, perf_stats::per_frame)
    v.full = true;
    const auto cell = [](PerfCell& c, const char* fmt, double x) {   // (x < 0: the machine or the game gives none, "-", dimmed)
        c.dim = perf_machine::cell_text(c.t, sizeof c.t, fmt, x);
    };
    const auto empty = [](PerfCell& c) { c.t[0] = 0, c.dim = false; };
    const auto gb = [](double mb) { return mb < 0 ? -1.0 : mb / 1024.0; };
    perf_title(v.title, sizeof v.title);
    const perf_machine::Machine m = perf_machine::latest();
    snprintf(v.gpu_name, sizeof v.gpu_name, "%s", m.gpu_name);
    snprintf(v.cpu_name, sizeof v.cpu_name, "%s", m.cpu_name);
    cell(v.top[0][0], "%.0f%%", m.gpu_pct);
    cell(v.top[0][1], "%.0f \xC2\xB0" "C", m.gpu_temp_c);
    empty(v.top[0][2]);   // ((Triforce, 11-17) NX2navi's watts left out: the card's power is not read, perf_machine.cpp)
    {   // (the card's memory in use by every program and in all; the game's own beside it: what the driver counts for this
        // process on the card's heaps, the budget code's number, vk_vma.cpp. Where the driver does not say, the GPU's clock in
        // its place, as NX2navi's)
        uint64_t used = 0, allowed = 0;
        const bool known = vram_usage(&used, &allowed) && used;
        cell(v.top[1][0], "%.1f GB", gb(m.vram_used_mb));
        cell(v.top[1][1], "/ %.1f GB", gb(m.vram_total_mb));
        if (known) cell(v.top[1][2], "game %.1f GB", (double)used / 1073741824.0);
        else cell(v.top[1][2], "%.0f MHz", m.gpu_clock_mhz);
    }
    cell(v.top[2][0], "%.0f%%", m.cpu_pct);
    cell(v.top[2][1], "%.0f \xC2\xB0" "C", m.cpu_temp_c);
    cell(v.top[2][2], "game %.0f%%", m.cpu_game_pct);
    cell(v.top[3][0], "%.1f GB", gb(m.ram_used_mb));
    cell(v.top[3][1], "/ %.1f GB", gb(m.ram_total_mb));
    cell(v.top[3][2], "game %.1f GB", gb(m.ram_game_mb));
    // (the game's frames: the rate of the last second, the lows of the last ten (from 100 frames on))
    cell(v.top[4][0], "%.0f", second.frames ? second.fps : game);
    cell(v.top[4][1], "1%% low %.0f", ten.low1_fps);
    cell(v.top[4][2], "0.1%% low %.0f", ten.low01_fps);
    // (what is shown while generated frames are: DLSS frame generation's go in at the present, which counts them by its
    // multiplier ((Triforce, 11-16) vk_replay.cpp do_present); the renderer's own, AMD FSR 3.1's and AMD FSR 4's while
    // frame generation runs (vk_framegen.cpp framegen_on: the row set, where it can run, not beside DLSS's). As NX2navi's
    // fg_fps, by what runs and not by the row: a row set where nothing can make frames shows no FG)
    v.fg = perf_fg_running();
    cell(v.top[kPerfFG][0], "%.0f", shown);
    empty(v.top[kPerfFG][1]), empty(v.top[kPerfFG][2]);
    cell(v.top[6][0], "%.1f ms", second.frames ? second.avg_ms : -1.0);
    cell(v.top[6][1], "max %.1f ms", second.frames ? second.max_ms : -1.0);
    empty(v.top[6][2]);
    {   // (per frame since the sample before, over the game's frames since: the replay's time to record the frame (its submits
        // and its present, as the frame trace's replay), the GPU's (its timestamps: none without them), the replay's waits for
        // pipelines and for translations (vk_draw.cpp draw_wait_split), the textures uploaded. The step is perf_stats::per_frame:
        // fresh or the first, every figure "-"; no game frame since, as they were)
        perf_stats::Counts now;
        now.frames = game_frames.load(std::memory_order_relaxed);
        now.prep_ns = prof_ns[PROF_SUBMIT] + prof_ns[PROF_PRESENT], now.gpu_ns = gpu_time_busy_ns();
        int64_t astc = 0, bytes = 0;
        texture_stats(&now.uploads, &astc, &bytes);
        draw_wait_split(&now.pipe_us, &now.shader_us);
        perf_stats::PerFrame f;
        if (perf_stats::per_frame(v.base, now, fresh, &f) != perf_stats::STEP_KEEP) {
            cell(v.frame[0], "%.2f ms", f.prep_ms);
            cell(v.frame[1], "%.2f ms", f.gpu_ms);
            cell(v.frame[2], "%.2f ms", f.pipe_ms);
            cell(v.frame[3], "%.2f ms", f.shader_ms);
            cell(v.frame[4], "%.1f per frame", f.uploads);
        }
    }
    {   // (the settings that shape the picture, kPerfSetting's rows in NX2navi's words and order, from the options' rows here:
        // the window and the game's picture as the last present had them (menu_note_present_sizes); the upscaler in effect with
        // its mode (perf_upscaling_text); the frame rate cap as a rate ("60 FPS"); the output resolution by its lines ("1440p");
        // what makes the frames (perf_framegen_text). An empty one: its row left out.
        // ((Triforce) the Frame limit with who holds it where that is not the game's own wait: "60 FPS (RivaTuner)")
        char t[48];
        const auto set = [&](int i, const char* value) { snprintf(v.setting[i], sizeof v.setting[i], "%s", value ? value : ""); };
        const uint64_t ps = present_sizes.load(std::memory_order_relaxed);
        const unsigned pw = (unsigned)(ps >> 48), ph = (unsigned)(ps >> 32) & 0xffff, ww = (unsigned)(ps >> 16) & 0xffff, wh = (unsigned)ps & 0xffff;
        t[0] = 0;
        if (ww && wh) snprintf(t, sizeof t, "%ux%u", ww, wh);
        set(0, t);
        t[0] = 0;
        if (pw && ph) snprintf(t, sizeof t, "%ux%u", pw, ph);
        set(1, t);
        set(2, perf_upscaling_text(t, sizeof t));
        set(3, tx_aa(opts.aa));
        perf_rate_text(tx_fps_cap(opts.fps_cap), t, sizeof t);   // (and who holds it where the game's own wait does not: vk_pace.cpp)
        const int holder = mkwvk::pace::owner();
        if (holder != mkwvk::pace::GAME) strncat(t, holder == mkwvk::pace::RTSS ? " (RivaTuner)" : " (NVIDIA Reflex)", sizeof t - strlen(t) - 1);
        set(4, t);
        set(5, tx_vsync(opts.vsync));
        set(6, shape_now(opts.ultrawide));   // ((Triforce) the Output resolution's own shape where it has one)
        unsigned ow = 0, oh = 0;
        t[0] = 0;
        oh = shown_output().h, ow = shown_output().w;   // ((Triforce) Screen's and Custom's too)
        if (ow && oh) snprintf(t, sizeof t, "%up", oh);
        set(7, t);
        set(8, tx_hdr(opts.hdr));
        set(9, perf_framegen_text(t, sizeof t));   // (what makes the frames, by name, as NX2navi's)
    }
    v.have = true;
}

/// (Triforce) The overlay's machine sampler starts (the row went to Full, a GPU chosen): the GPU the game renders on, as
/// Vulkan has it (its name, its LUID, the card's memory: its device-local heaps, NVML's figure over it where it is)
/// ((Triforce: from NX2navi runtime/ui/menu.cpp perf_gpu_once, at 62cc3b13))
void perf_machine_start() {
    perf_machine::Gpu g;
    snprintf(g.name, sizeof g.name, "%s", dev.props.deviceName);
    g.has_luid = gpu_device_luid(g.luid);
    // (NX2navi's: the device-local heaps added up)
    g.vram_total_mb = perf_machine::local_heap_mb(dev.memory.memoryHeaps, dev.memory.memoryHeapCount, VK_MEMORY_HEAP_DEVICE_LOCAL_BIT);
    perf_machine::start(g, [](const char* line) { logf("vk: the performance overlay: %s", line); });
}

// ((Triforce) 11-24) what plays the controller used last, as the host wrote it back (menu_option_set)
int menu_vibration_status_option() { return vibration_status_cache.load(std::memory_order_relaxed); }

void menu_option_set(int id, int value) {
    if (id == HOS_OPT_VIBRATION_STATUS) {   // ((Triforce) 11-24: what plays the controller used last, host/pad_sdl.c)
        vibration_status_cache.store(value, std::memory_order_relaxed);
        return;
    }
    if (id >= HOS_OPT_MODS_X0 && id <= HOS_OPT_MODS_PITCH) {   // (Triforce: the Mods entry's list, host/oot_menu.c)
        mods_box[id - HOS_OPT_MODS_X0].store(value, std::memory_order_relaxed);
        return;
    }
    if (id == HOS_OPT_MODS_ALPHA) {   // ((Triforce, 11-20) how much of its own buttons the game shows: the entry's too)
        mods_list_alpha.store(std::clamp(value, 0, 1000), std::memory_order_relaxed);
        return;
    }
    if (id == HOS_OPT_MODS_LIST) {
        if (!(value & HOS_MODS_LIST_SHOWN)) {   // ((Triforce, 11-20) the list is no longer the entry's: gone at once, not after 150 ms)
            mods_list_ns.store(0, std::memory_order_release);
            return;
        }
        mods_list_bits.store(value, std::memory_order_relaxed);
        mods_list_frame.store(game_frames.load(std::memory_order_relaxed), std::memory_order_relaxed);
        mods_list_ns.store(prof_now(), std::memory_order_release);
        return;
    }
    if (id == HOS_OPT_MODS_ENTER) {
        mods_enter.store(value, std::memory_order_relaxed);
        return;
    }
    if (id == HOS_OPT_MODS_PRESS) {   // (Triforce: a test's scripted presses while Mods has the cursor, host/nn_hid.c)
        mods_press.fetch_or(value & 0xff, std::memory_order_relaxed);
        if (value & HOS_MODS_REPORT) {   // ((Triforce, 11-19) each read's: the directions held then)
            mods_held_dirs.store(value >> HOS_MODS_HELD_SHIFT & HOS_MODS_PRESS_DIRS, std::memory_order_relaxed);
            mods_held_ns.store(prof_now(), std::memory_order_relaxed);
        }
        return;
    }
    if (id == HOS_OPT_TEXT_CHAR) {   // ((Triforce) a character typed into the Mods screen's search: host/display.c, the window's thread)
        std::lock_guard<std::mutex> g(mods_typed_mu);
        if (mods_typed.size() < 256) mods_typed.push_back(value);
        return;
    }
    if (id == HOS_OPT_GAME_OPTIONS) {   // (Triforce: the game's own Options screen runs: each frame it does)
        game_options_ns.store(value ? prof_now() : 0, std::memory_order_relaxed);
        game_options_from_pause.store(value == 2, std::memory_order_relaxed);
        return;
    }
    // (Triforce: the save files, named by the host once this renderer answers, and its word on a file chosen: host/save_files.c)
    if (id == HOS_OPT_FILES_TEXT) return save_files.text(value);
    if (id == HOS_OPT_FILES_ADD) return save_files.add(value);
    if (id == HOS_OPT_FILES_COUNT) {
        save_files.done(value);
        menu_refresh = true;
        return;
    }
    if (id == HOS_OPT_FILES_SAID) {
        save_files.said(value);
        menu_refresh = true;
        return;
    }
    // (Triforce: the achievements, named by the host once this renderer answers, and each one earned as it is:
    // host/achievements.c, one call at a time)
    if (id == HOS_OPT_ACH_TEXT) return ach_list.text(value);
    if (id == HOS_OPT_ACH_ADD) return ach_list.add(value);
    if (id == HOS_OPT_ACH_COUNT) {
        ach_list.done(value);
        menu_refresh = true;
        return;
    }
    if (id == HOS_OPT_ACH_EARNED) {
        if (ach_list.earn(value)) menu_refresh = true;
        return;
    }
    // (Triforce: the cheats of the mods' cheat files, named by the host at the first frame: host/mod_cheats.c. A cheat may not
    // have the name of a row that acts by its name, share_row's)
    if (id == HOS_OPT_MODCHEAT_TEXT) return mod_cheats.text(value);
    if (id == HOS_OPT_MODCHEAT_ADD) {
        static const char* const taken[] = {"Export save", "Export save for a bug report", "Import a save", "Bug capture (F8)"};
        return mod_cheats.add(value, taken, (int)(sizeof taken / sizeof taken[0]));
    }
    if (id == HOS_OPT_MODCHEAT_COUNT) {
        mod_cheats.done(value);
        menu_refresh = true;
        return;
    }
    if (id == HOS_OPT_SHARE_TEXT) {   // (Triforce: the host's line for a share row, a byte a call: host/save_share.c)
        std::lock_guard lk(share_mu);
        if (value > 0 && value < 256 && share_in.size() < 600) share_in += (char)value;
        return;
    }
    if (id == HOS_OPT_SHARE_SAID) {   // (and whose line it is: that row's work is done)
        std::lock_guard lk(share_mu);
        if (value >= HOS_SHARE_EXPORT && value <= HOS_SHARE_NOTICE) share_lines[value] = share_in;
        if (value == HOS_SHARE_NOTICE) share_notice_new.store(true, std::memory_order_release);
        share_in.clear();
        if (value == share_busy_row.load(std::memory_order_relaxed)) share_busy_until.store(0, std::memory_order_relaxed);
        return;
    }
    if (id == HOS_OPT_SHARE_IMPORT) {   // (an imported save waits for the next start, or no longer)
        share_import_waits.store(value != 0, std::memory_order_relaxed);
        return;
    }
    if (id == HOS_OPT_BUG_SHOT) {   // (a bug capture wants the frame shown next as a picture, or no longer: vk_bugshot.cpp)
        bugshot_request(value != 0);
        return;
    }
    if (id == OOT_CHEAT_AGE_ID) {   // (Link's age: the Switch age row shows it)
        if (link_age.exchange(value, std::memory_order_relaxed) != value && page == 0 && cur_tab == TAB_DEBUG) menu_refresh = true;
        return;
    }
    if (id == HOS_OPT_BUG_SETTINGS) {   // ((Triforce) 11-24: a bug capture's settings changed from the defaults, read a byte at a time)
        if (value) menu_bug_settings_begin();
        return;
    }
    if (id == HOS_OPT_SIM_TURF_AREA_TEXT) return sim_turf_area_byte(value);   // ((Triforce, 11-24) the area, for the Simulated turf page
    if (id == HOS_OPT_SIM_TURF_AREA) return sim_turf_area_end(value);         // (host/hos_main.c oot_inventory_refresh)
    if (id >= OOT_CHEAT_ITEM_BASE && id < OOT_CHEAT_ITEM_BASE + kItems) {   // (the game side's inventory counts)
        if (item_counts[id - OOT_CHEAT_ITEM_BASE].exchange(value, std::memory_order_relaxed) != value && page == 4)
            menu_refresh = true;
        return;
    }
    if (id == HOS_OPT_CHEAT_FLIGHT) {
        if (cheats_on()) {
            int expected = value ? 0 : 1;
            player_flight.compare_exchange_strong(expected, value != 0, std::memory_order_relaxed);
        }
        return;
    }
    if (id == HOS_OPT_DEBUG_TEXT) {   // (Triforce: the game side's line for the name pages, a byte a call: host/hos_main.c)
        std::lock_guard lk(names_mu);
        if (value > 0 && value < 256 && names_in.size() < 600) names_in += (char)value;
        return;
    }
    if (id == HOS_OPT_DEBUG_SAID) {   // (and what the line is: the shown flags' states, or what became of a flag or an event)
        std::lock_guard lk(names_mu);
        if (value == OOT_SAID_FLAGS) names_states.take(names_in.c_str());
        else if (value == OOT_SAID_STATUS) names_status = names_in, names_status_new.store(true, std::memory_order_relaxed);
        names_in.clear();
        if (page == 6) menu_refresh = true;
        return;
    }
    if (id == HOS_OPT_AMIIBO_SAID) {   // (what became of the figure chosen: host/nn_nfp.c)
        if (amiibo_said.exchange(value, std::memory_order_relaxed) != value) amiibo_new.store(true, std::memory_order_relaxed), menu_refresh = true;
        return;
    }
    if (id != 7) return;
    opts.mouse_sens = std::min(std::max(value, 10), 500);   // (the keys work while the menu is closed: it shows it when opened)
    save();
}

// ---- (Triforce) the control bridge's option_get and option_set (host/control.c; called only with HOS_CONTROL set) ----
// The settings rows (a value, not a heading, a debug tool or a hidden saved value, shown on this PC: row_shown), found by
// their key in triforce_options.ini (ini_key), which stays the same while rows come and go or are renamed. The bridge calls
// these from its own thread: menu_mu keeps them apart from menu_tick (the presenting thread), which takes it each frame.
// Recursive: a setter reached from inside menu_tick's frame on the same thread does not lock itself out
std::recursive_mutex menu_mu;
static bool bridge_row(int i) {
    return rows[i].value && !rows[i].heading && rows[i].cheat < 0 && rows[i].tab != TAB_HIDDEN && row_shown(i);
}
static void bridge_fill(int i, MkwVkSetting* out) {
    static const char* const tabs[] = {"display", "graphics", "audio", "controls", "system", "debug", "motion", "controls",
                                       "display", "display", "controls",   // ((Triforce VR) VR Controls, 3D Settings, VR Settings, then Controls)
                                       "graphics", "graphics", "hidden"};   // (N64 Classic's and Simulated turf's pages: Graphics)
    static_assert(sizeof tabs / sizeof tabs[0] == TAB_HIDDEN + 1, "a name for each MenuTab");
    const Row& r = rows[i];
    *out = MkwVkSetting{};
    snprintf(out->key, sizeof out->key, "%s", ini_key(r));
    snprintf(out->name, sizeof out->name, "%s", r.name);
    snprintf(out->tab, sizeof out->tab, "%s", r.tab >= 0 && r.tab <= TAB_HIDDEN ? tabs[r.tab] : "");
    out->value = *r.value, out->lo = r.lo, out->hi = r.hi, out->step = r.step;
    out->restart = r.restart, out->fixed = row_fixed(r.value);
    snprintf(out->text, sizeof out->text, "%s", r.text ? r.text(out->value) : "");
}
// (the Upscaler row's questions, asked before menu_mu is taken: row_shown and row_fixed ask upscalers_available(), which
// may wait for the libraries' start-up probe while it runs. Under menu_mu that would hold menu_tick, and the present with
// it; this way only the bridge's thread waits, and once answered the questions return at once)
static void bridge_probe_first() { (void)upscalers_available(), (void)dlss_why(); }
/// A row whose choices are not in the order of their numbers (the output sizes, the Render resolution's steps, the Upscaler's
/// engines, the merged rows' choices here), walked in the arrows' own order to the value asked for: one way, then the other,
/// each way until at() holds, the row stops at an end (state() unchanged) or it comes round to where that way began. state():
/// all a step changes; step(dir): one arrow press. false: no step reaches it (then stepped back towards where it began)
template <class State, class At, class Step>
static bool walk_to(State state, At at, Step step, int limit) {
    const auto start = state();
    for (const int dir : {1, -1}) {
        const auto from = state();
        for (int k = 0; k < limit && !at(); k++) {
            const auto was = state();
            step(dir);
            if (state() == was || state() == from) break;
        }
        if (at()) return true;
    }
    for (int k = 0; k < limit && state() != start; k++) step(1);
    return false;
}
/// The index-th settings row (an enumeration, for listing them; the index is not a name: rows come and go). 0: past the last
int menu_setting(int index, MkwVkSetting* out) {
    bridge_probe_first();
    std::lock_guard<std::recursive_mutex> lk(menu_mu);
    merged_sync();   // (the merged rows from the saved values, as menu_tick has them)
    for (int i = 0, n = 0; i < kRows; i++)
        if (bridge_row(i) && n++ == index) return bridge_fill(i, out), 1;
    return 0;
}
/// The settings row whose ini key is key, set to value as the menu's Left and Right set it (set_row: cut to its range, a
/// restart noted, kept in the options file). The rows the arrows step through a list of their own are walked to value
/// (walk_to); a value none of their steps reach leaves them and the rest as they were. out: the row as it is now. 1 set, 0
/// no such row, -1 nothing to choose on this PC (row_fixed), -2 no step of a list row reaches value here
int menu_setting_set(const char* key, int value, MkwVkSetting* out) {
    bridge_probe_first();
    std::lock_guard<std::recursive_mutex> lk(menu_mu);
    merged_sync();
    int i = 0;
    while (i < kRows && !(bridge_row(i) && !strcmp(ini_key(rows[i]), key))) i++;
    if (i == kRows) return 0;
    Row& r = rows[i];
    if (row_fixed(r.value)) return bridge_fill(i, out), -1;
    const int want = std::min(std::max(value, r.lo), r.value == &opts.pad_layout ? std::min(r.hi, 2) : r.hi);   // (3: Custom, shown only)
    if (r.value == &opts.dlss || r.value == &opts.resolution || r.value == &opts.output_res || is_merged(r.value)) {
        const Options opts_was = opts;
        const Merged merged_was = merged;
        const mr::State restart_was = restart_state;
        const auto state = [&] { return std::array<int, 5>{*r.value, opts.dlss, opts.resolution, opts.output_res, opts.framegen}; };
        if (!walk_to(state, [&] { return *r.value == want; }, [&](int dir) { set_row(r, *r.value + dir * r.step, dir, false); }, 64)) {
            opts = opts_was, merged = merged_was, restart_state = restart_was;
            menu_refresh = true;
            bridge_fill(i, out);
            return -2;
        }
        save();
    } else if (want != *r.value) {
        set_row(r, want, want > *r.value ? 1 : -1);
    }
    menu_refresh = true;
    bridge_fill(i, out);
    return 1;
}

/// (hookshot) the mouse on the inventory: a section tab chooses it, a card the item (a click selects it, it does not edit),
/// the page arrows turn the page with the choice, the action button and the amount's halves act; the wheel turns the page
/// shown and leaves the choice where it is; a right click goes back
void inventory_mouse(const MkwVkPointer& ptr, int mx, int my, bool* press, bool& changed) {
    const menu_hit::Hit hit = hits.at((float)mx, (float)my);
    if (ptr.pressed & HOS_MOUSE_LEFT) {
        if (hit.part == menu_hit::kRow && hit.index >= 0 && hit.index <= kItemSections) choose_inventory_filter(hit.index), changed = true;
        else if (hit.part == menu_hit::kListLine && hit.index >= inventory_begin() && hit.index < inventory_end())
            item_choice = hit.index, inventory_amount = false, changed = true;
        else if (hit.part == menu_hit::kButton && hit.index == 0) press[7] = true;
        else if (hit.part == menu_hit::kButton && hit.index == 1 && hit.side) press[hit.side < 0 ? 3 : 4] = true;
        else if (hit.part == menu_hit::kButton && (hit.index == 2 || hit.index == 3))   // (the page arrows)
            press[hit.index == 2 ? 13 : 14] = true, inventory_amount = false;
    }
    if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
    if (ptr.wheel) {
        const int was = inventory_page;
        inventory_page = std::max(0, inventory_page - ptr.wheel);   // (drawing keeps it to the pages there are)
        changed |= inventory_page != was;
    }
}
/// (hookshot) the mouse on the teleport list: a click on a card selects it (Travel, or confirm, goes), the Travel button
/// goes; the wheel scrolls the cards and leaves the choice where it is; a right click goes back
void teleport_mouse(const MkwVkPointer& ptr, int mx, int my, bool* press, bool& changed) {
    const menu_hit::Hit hit = hits.at((float)mx, (float)my);
    if (ptr.pressed & HOS_MOUSE_LEFT) {
        if (hit.part == menu_hit::kListLine && hit.index >= 0 && hit.index < kTeleports)
            teleport_choice = hit.index, teleport_follow = true, changed = true;
        else if (hit.part == menu_hit::kButton) press[7] = true;
    }
    if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
    if (ptr.wheel) teleport_wheel += ptr.wheel, teleport_follow = false, changed = true;
}
/// A debug tool's row on the Debug tab (Row::cheat i): Left and Right, and confirm (press[7]: A, Enter, a click). Teleport and
/// Inventory open their pages; back from them comes to the Debug tab, the row still selected
void cheat_press(int i, const bool* press, bool& changed) {
    if (i < 2 && (press[3] || press[4] || press[7])) {   // (Left On, Right Off, as they are drawn; confirm flips)
        const bool was = i == 0 ? protect_hearts.load() == 1 : player_flight.load() >= 0;
        const bool on = press[7] ? !was : press[3];
        if (i == 0) protect_hearts.store(on ? 1 : 0);
        else if (on != was) player_flight.store(on ? 0 : -1);
        changed = true;
    }
    if (i == 4 && (press[3] || press[4])) {
        clock_hour = (clock_hour + (press[4] ? 1 : 23)) % 24;
        changed = true;
    }
    if (i == 5 && (press[3] || press[4])) {
        pouch_item = (pouch_item + kPouchItems + (press[4] ? 1 : -1)) % kPouchItems;
        changed = true;
    }
    if (i == 14 && (press[3] || press[4])) {   // ((Triforce) Movement speed: it stops at 1x and at 3x)
        link_speed.store(std::clamp(link_speed.load() + (press[4] ? 1 : -1), 0, kLinkSpeeds - 1));
        changed = true;
    }
    if (i == 6 && (press[3] || press[4])) {
        const int step = press[4] ? 1 : -1;
        pouch_delta = std::clamp(pouch_delta + step, -10, 10);
        if (!pouch_delta) pouch_delta = step;
        changed = true;
    }
    if (press[7] && i >= 2 && i <= 4) cheat_action.store(i == 4 ? 100 + clock_hour : i);
    if (press[7] && i == 6) cheat_action.store(200 + pouch_item * 32 + pouch_delta + 10);
    if ((press[3] || press[4] || press[7]) && i == 7) {   // (an On / Off as the first two: Left On, Right Off, confirm flips)
        free_camera.store(press[7] ? !free_camera.load() : press[3] ? 1 : 0);
        changed = true;
    }
    if (press[7] && i == 8) page = 3, teleport_follow = true, changed = true;
    if (press[7] && i == 10) page = 4, choose_inventory_filter(0), changed = true;
    if (press[7] && i >= 11 && i <= 13) names_open(i - 11), changed = true;   // ((Triforce) Game flags, Cutscenes, Scan amiibo)
    if (i == 9 && (press[3] || press[4])) {   // (Kid | Adult: Left Kid, Right Adult, a switch when Link is the other age)
        const int age = link_age.load(std::memory_order_relaxed);
        if (age >= 0 && age != (press[4] ? 1 : 0)) {
            cheat_action.store(999);
            open_now = false;
            changed = true;
        }
    }
    if (press[7] && i == 9) {
        cheat_action.store(999);   // (host/hos_main.c OOT_AGE_ACTION)
        open_now = false;
        changed = true;
    }
}

void mods_open_page();   // ((Triforce) below: the Mods screen opened, its search ended)
/// (Triforce) A step along the tab strip (dir -1 left, 1 right) from the tab or the Mods page shown: the strip's order is
/// ours to System, Mods, Debug when shown; inside the game's Options, past either end is the game's own tab again
void tab_move(int dir) {
    int entry[TAB_COUNT + 2], n = 0;
    for (int t = 0; t < TAB_DEBUG; t++) entry[n++] = t;
    if (debug_shown()) entry[n++] = TAB_DEBUG;
    const int from = page == kModsPage ? kModsTab : page_parent(cur_tab);
    int at = 0;
    while (at < n - 1 && entry[at] != from) at++;
    if (embed_open && ((dir < 0 && at == 0) || (dir > 0 && at == n - 1))) {
        open_now = false;
        page = 0;
        return;
    }
    const int to = entry[(at + n + dir) % n];
    if (to == kModsTab) {
        page = kModsPage, mods_btn = 0, mods_follow = true;
        cur_tab = TAB_SYSTEM;   // (where Back from it would be)
        mods_open_page();
    } else {
        page = 0, cur_tab = to;
    }
}

/// (Triforce) The Mods page's input: the warning first; the cards (Up and Down, Page Up and Down, Home and End), the file
/// (Left and Right), Install (Confirm); an install's Cancel; its end's Restart Now or Later
/// (Triforce) Back from the Mods screen: to the game's list it was opened from, the cursor on the Mods entry (as the game's own
/// screens give the cursor back to the entry that opened them); the list gone meanwhile, the menu shuts
void mods_back(bool& changed) {
    if (mods_list_fresh()) page = kModsRowPage;
    else open_now = false, page = 0;
    changed = true;
}
/// ((Triforce) 11-17) The pictures' textures of a list the engine emptied (a search's results, a list after a failure): let go
void mods_retire(const std::vector<void*>& textures) {
    for (void* t : textures) texture_retire((ImTextureData*)t);
}
/// ((Triforce) the Mods screen opened: the list asked for (vk_mods.cpp open), a search left behind ended and its text cleared)
void mods_open_page() {
    mods_retire(mods::open());
    mods_query.clear(), mods_query_sent.clear(), mods_kbd = false;
    if (mods_choice < 0) mods_choice = 0;
}
/// ((Triforce) the list made the search of q: the results from the top; fewer than 2 characters is the whole list again,
/// its choice and scroll as they were when the search began
void mods_set_search(const std::string& q, bool& changed) {
    const std::string before = mods::search_text();
    const bool was = !before.empty();
    mods_retire(mods::search(q));
    mods_query_sent = q, changed = true;
    const std::string after = mods::search_text();
    if (after == before) return;   // (the same search, its text trimmed: the list as it is)
    if (!was) mods_browse_choice = mods_choice, mods_browse_px = mods_want_px;
    if (!after.empty()) {
        if (mods_choice >= 0) mods_choice = 0;
        mods_scroll_px = mods_want_px = 0;
    } else if (was) {
        if (mods_choice >= 0) mods_choice = std::max(0, mods_browse_choice);
        mods_scroll_px = mods_want_px = mods_browse_px;
    }
    mods_follow = true, changed = true;
}

void mods_tick(bool* press, bool tab_left, bool tab_right, bool mouse, bool moved, const MkwVkPointer& ptr, int mx, int my, bool& changed) {
    const mods::InstallState inst = mods::install_state();
    const bool busy = inst.job == mods::Job::Downloading || inst.job == mods::Job::Unpacking;
    const bool ended = inst.job == mods::Job::Done || inst.job == mods::Job::Failed || inst.job == mods::Job::Cancelled;
    const bool dialog = !mods::accepted() || busy || ended;
    {   // (the Salesman's big moments: his hello the first time the page shows each run, an install's end; the mask comes off)
        static bool smiled_done = false;
        if (inst.job == mods::Job::Done && !smiled_done) {   // (the game's item-get fanfare, the mask off for it)
            salesman::smile(9), smiled_done = true;
            mods_sound(HOS_MENU_SOUND_FANFARE);
        }
        if (inst.job != mods::Job::Done) smiled_done = false;
        if (!salesman_said_hello && mods::accepted() && salesman::state() == salesman::State::Ready && salesman_tex)
            salesman::smile(2.8f), salesman_said_hello = true;
    }
    static bool was_busy = false;
    if (busy || inst.job == mods::Job::Done) changed = true;   // (the bar moves, the dialog comes: drawn again)
    if (was_busy && !busy) changed = true;
    was_busy = busy;
    // ((Triforce) the text typed since the last tick (host/display.c), the search's; none taken while a dialog is up)
    std::vector<int> typed;
    {
        std::lock_guard<std::mutex> g(mods_typed_mu);
        typed.swap(mods_typed);
    }
    mods_text_wanted.store(mods::available() && !dialog, std::memory_order_relaxed);
    if (dialog) mods_kbd = false;
    bool kbd_click = false;   // (a key clicked: typed, not the keyboard's Enter)
    if (mouse) {
        const menu_hit::Hit hit = hits.at((float)mx, (float)my);
        if (hit.part == menu_hit::kButton && (moved || ptr.pressed) && hit.index != mods_btn) mods_btn = hit.index, changed = true;
        if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kButton) press[7] = true;
        if (!dialog && mods_kbd) {   // ((Triforce) the on-screen keyboard: a key pointed at is chosen, a click types it; a click off it shuts it)
            if (hit.part == menu_hit::kKey && (moved || ptr.pressed)) {
                const int r = hit.index / 10, col = hit.index % 10;
                if (r != mods_kbd_row || col != mods_kbd_col) {
                    mods_kbd_row = r, mods_kbd_col = col, changed = true;
                    if (ptr.pressed & HOS_MOUSE_LEFT) mods_sound(HOS_MENU_SOUND_CURSOR);   // (a click; hover alone is quiet)
                }
            }
            const bool inside = mx >= mods_kbd_box[0] && mx <= mods_kbd_box[2] && my >= mods_kbd_box[1] && my <= mods_kbd_box[3];
            if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kKey) press[7] = true, kbd_click = true;
            else if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part != menu_hit::kSearch && !inside) mods_kbd = false, changed = true;
        } else if (!dialog) {
            if (hit.part == menu_hit::kListLine && (moved || ptr.pressed) && hit.index != mods_choice)
                mods_choice = hit.index, mods_follow = true, changed = true, mods_sound(HOS_MENU_SOUND_CURSOR);
            if (hit.part == menu_hit::kSearch && (moved || ptr.pressed) && mods_choice != -1) mods_choice = -1, mods_follow = true, changed = true;
            if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kSearch)
                mods_kbd = true, mods_kbd_row = 1, mods_kbd_col = 0, changed = true, mods_sound(HOS_MENU_SOUND_DECIDE);
            if (ptr.pressed & HOS_MOUSE_LEFT) {
                if (hit.part == menu_hit::kTabPrev) tab_left = true;
                else if (hit.part == menu_hit::kTabNext) tab_right = true;
                else if (hit.part == menu_hit::kTab && hit.index == kGameTab) open_now = false, page = 0, changed = true;
                else if (hit.part == menu_hit::kTab && hit.index >= 100 && hit.index < 100 + kModsCats) mods_cat_pick = hit.index - 100;
                else if (hit.part == menu_hit::kTab && hit.index != kModsTab && hit.index >= 0 && hit.index < TAB_COUNT) page = 0, cur_tab = hit.index, changed = true;
            }
            if (ptr.wheel) (mx >= mods_desc_x0 ? mods_desc_wheel : mods_wheel) += ptr.wheel, changed = true;   // (over the details: theirs)
        }
        if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
    }
    if (!mods::available()) {
        if (press[5]) mods_back(changed);   // (back to the game's list it was opened from)
        return;
    }
    if (!mods::accepted()) {   // (the warning: I understand, or Not now)
        if (press[1] || press[2] || press[3] || press[4]) mods_btn ^= 1, changed = true, mods_sound(HOS_MENU_SOUND_CURSOR);
        if (press[7] && mods_btn == 0) {
            mods::accept();
            logf("mods: the warning accepted");
            mods_open_page();
            changed = true, mods_sound(HOS_MENU_SOUND_DECIDE);
        } else if (press[5] || press[7]) {   // (Not now: back to the game's list)
            mods_sound(HOS_MENU_SOUND_CANCEL);
            mods_back(changed);
        }
        return;
    }
    if (busy) {   // (only Cancel)
        if (press[5] || press[7]) mods::cancel(), changed = true, mods_sound(HOS_MENU_SOUND_CANCEL);
        return;
    }
    if (ended) {
        if (inst.job == mods::Job::Done && inst.kit) {   // ((Triforce) 11-18) a kit started: OK alone
            if (press[5] || press[7]) mods::clear_done(), mods_btn = 0, changed = true, mods_sound(HOS_MENU_SOUND_DECIDE);
        } else if (inst.job == mods::Job::Done) {
            if (press[1] || press[2] || press[3] || press[4]) mods_btn ^= 1, changed = true, mods_sound(HOS_MENU_SOUND_CURSOR);
            if (press[7] && mods_btn == 0) {   // (Restart Now: as the restart question's, everything saved first)
                logf("mods: restart now, to load %s", inst.mod_name.c_str());
                mods::clear_done();
                mods_sound(HOS_MENU_SOUND_DECIDE);
                save();
                pipeline_cache_save(true);
                memory_trial_orderly_end();
                open_now = false, page = 0, changed = true;
                PostMessageA(app_window(), WM_APP + 9, 0, 0);
            } else if (press[5] || press[7]) {
                mods::clear_done(), mods_btn = 0, changed = true, mods_sound(HOS_MENU_SOUND_CANCEL);
            }
        } else if (press[5] || press[7]) {
            mods::clear_done(), mods_btn = 0, changed = true, mods_sound(HOS_MENU_SOUND_CANCEL);
        }
        return;
    }
    // ((Triforce) the search: the text typed (the keyboard's characters, Backspace, Ctrl+Backspace), the on-screen keyboard's
    // keys while it is open, and the search made 0.5 s after the typing stops or at once with Confirm)
    const int64_t now = prof_now();
    bool edited = false, search_now = false;
    for (int cp : typed) {
        if (cp == 8) edited |= utf8_pop(mods_query);
        else if (cp == 127) edited |= !mods_query.empty(), mods_query.clear();
        else if (cp >= 0x20 && mods_query.size() < 100) utf8_add(mods_query, cp), edited = true;
    }
    if (edited && !mods_kbd) mods_sound(HOS_MENU_SOUND_CURSOR);   // ((Triforce, 11-18) a character typed; the host's
                                                                  // cursor gap keeps fast typing from stacking)
    if (edited && !mods_kbd && mods_choice != -1) mods_choice = -1, mods_follow = true;   // (typing: the cursor on the bar)
    if (mods_kbd && !pad_last && !kbd_click && (press[7] || press[5])) {
        if (press[7]) search_now = true;
        mods_kbd = false, changed = true;
        press[7] = press[5] = false;
    }
    if (mods_kbd) {
        const int was_row = mods_kbd_row, was_col = mods_kbd_col;
        if (press[1] || press[2]) {
            mods_kbd_row = (mods_kbd_row + (press[2] ? 1 : 4)) % 5;
            if (mods_kbd_row == 4) mods_kbd_col = kKbdWideAt[kbd_wide(mods_kbd_col)];
        }
        if (press[3] || press[4]) {
            if (mods_kbd_row == 4) mods_kbd_col = kKbdWideAt[(kbd_wide(mods_kbd_col) + (press[4] ? 1 : 3)) % 4];
            else mods_kbd_col = (mods_kbd_col + (press[4] ? 1 : 9)) % 10;
        }
        if (mods_kbd_row != was_row || mods_kbd_col != was_col) changed = true, mods_sound(HOS_MENU_SOUND_CURSOR);
        if (press[7]) {
            if (mods_kbd_row < 4) {
                if (mods_query.size() < 100) utf8_add(mods_query, kKbdRows[mods_kbd_row][mods_kbd_col]), edited = true;
            } else {
                const int k = kbd_wide(mods_kbd_col);
                if (k == 0 && mods_query.size() < 100) mods_query += ' ', edited = true;
                else if (k == 1) edited |= utf8_pop(mods_query);
                else if (k == 2) edited |= !mods_query.empty(), mods_query.clear();
                else if (k == 3) search_now = true, mods_kbd = false;
            }
            changed = true, mods_sound(search_now ? HOS_MENU_SOUND_DECIDE : HOS_MENU_SOUND_CURSOR);   // (a key pressed)
        }
        if (press[5]) {   // (Back: a character off; with none left the keyboard shut)
            if (!mods_query.empty()) edited |= utf8_pop(mods_query);
            else mods_kbd = false;
            changed = true, mods_sound(mods_kbd ? HOS_MENU_SOUND_CURSOR : HOS_MENU_SOUND_CANCEL);
        }
        press[7] = press[5] = false;
        for (int i = 1; i <= 4; i++) press[i] = false;
        for (int i = 13; i <= 16; i++) press[i] = false;
    } else if (press[5]) {   // (Back: a search ended first, its text cleared; then back to the game's list it was opened from)
        if (!mods_query.empty() || !mods::search_text().empty()) {
            mods_query.clear();
            mods_set_search("", changed);
            return;
        }
        mods_back(changed);
        return;
    }
    if (edited) mods_query_edit_ns = now, changed = true;
    const bool pending = mods_query != mods_query_sent;
    if (pending && press[7]) search_now = true, press[7] = false;   // (Confirm with the text changed: its search, not an install)
    // (the on-screen keyboard open: its Search key, or shutting it, searches; its letters one by one do not)
    if (pending && (search_now || (!mods_kbd && now - mods_query_edit_ns > 500000000LL))) mods_set_search(mods_query, changed);
    else if (pending) changed = true;   // (drawn again until it is searched)
    std::string err;
    const mods::Feed feed = mods::feed_state(&err);
    const bool searching = !mods::search_text().empty();
    mods::lock();
    const int n_all = (int)mods::list().size();
    int install = -1;
    bool retry = false, keyboard = false;
    // ((Triforce) 11-17, layout A) L and R turn the category; the cursor moves over its cards (vis), by their places
    if (!mods_kbd && (tab_left || tab_right || mods_cat_pick >= 0)) {
        const int was_cat = mods_cat;
        mods_cat = mods_cat_pick >= 0 ? mods_cat_pick : (mods_cat + kModsCats + (tab_left ? -1 : 1)) % kModsCats;
        mods_cat_pick = -1;
        if (mods_cat != was_cat) {
            mods_sound(tab_left ? HOS_MENU_SOUND_TAB_LEFT : HOS_MENU_SOUND_TAB_RIGHT);
            mods_choice = -2, mods_follow = true, mods_want_px = mods_scroll_px = 0, changed = true;   // (-2: the first card, below)
        }
    }
    std::vector<int> vis;
    for (int i = 0; i < n_all; i++)
        if (mods_in_cat(mods::list()[i], mods_cat)) vis.push_back(i);
    const int n = (int)vis.size();
    if (mods_choice == -2) mods_choice = n ? vis[0] : -1;
    int at = -1;
    for (int k = 0; k < n; k++)
        if (vis[k] == mods_choice) at = k;
    if (mods_choice >= 0 && at < 0) mods_choice = n ? vis[0] : -1, at = n ? 0 : -1;   // (not in this category: its first)
    if (!n && press[7] && feed == mods::Feed::Failed && mods_choice >= 0) retry = true;
    else if (n || mods_choice < 0 || press[1] || press[2] || press[13] || press[14] || press[15] || press[16]) {
        const int was = mods_choice;
        if (press[15]) at = n ? 0 : -1;
        else if (press[16]) at = n - 1;
        else at = std::clamp(at + (press[2] - press[1]) + (press[14] - press[13]) * mods_page_rows, -1, std::max(n - 1, -1));
        mods_choice = at >= 0 ? vis[at] : -1;
        if (mods_choice != was) mods_follow = true, changed = true, mods_sound(HOS_MENU_SOUND_CURSOR);
        if (mods_choice >= 0) {
            mods::Mod& m = mods::list()[mods_choice];
            const int files = (int)m.files.size();
            if ((press[3] || press[4]) && files > 1)
                m.file_choice = (m.file_choice + files + (press[4] ? 1 : -1)) % files, changed = true, mods_sound(HOS_MENU_SOUND_CURSOR);
            if (press[7] && m.details_state == 2 && files) install = mods_choice;
        } else if (press[7]) {   // (Confirm on the bar: tried again after a failure; else the on-screen keyboard (a pad), or the results)
            if (feed == mods::Feed::Failed) retry = true;   // ((Triforce) 11-18: also a list that stopped with cards in it)
            else if (pad_last || !n) keyboard = true;
            else mods_choice = 0, mods_follow = true, changed = true;
        }
    }
    mods::unlock();
    if (install >= 0) {
        mods::install(install);
        mods_btn = 0, changed = true, mods_sound(HOS_MENU_SOUND_DECIDE);
    } else if (retry) {   // (try again: the search, or the list; (Triforce) 11-18: a list that stopped on a page goes on from it)
        if (searching) mods_retire(mods::search(mods::search_text()));
        else if (n_all) mods::load_more();
        else mods_retire(mods::open());
        changed = true, mods_sound(HOS_MENU_SOUND_CURSOR);
    } else if (keyboard) {
        mods_kbd = true, mods_kbd_row = 1, mods_kbd_col = 0, changed = true, mods_sound(HOS_MENU_SOUND_DECIDE);
    }
    // ((Triforce) 11-18) the next pages: asked for by the engine one after another (vk_mods.cpp fetch_page), not by the cursor
    if (feed == mods::Feed::Loading) changed = true;   // (drawn again as it comes)
    {   // (a picture or the details came in since the last drawing: drawn again, now and then)
        static int64_t last = 0;
        const int64_t now = prof_now();
        if (now - last > 250000000LL) last = now, changed = true;
    }
}

/// ((Triforce) 11-24) The Test microphone row's test, at each menu tick's end whichever way it ends: off unless the options
/// show the Audio tab with the focus and a microphone chosen; the host told either way, its levels taken
void mic_test_tick(bool focused) {
    if (!focused || !open_now.load() || cur_tab != TAB_AUDIO || page != 0 || opts.mic == 0) mic_testing = false;
    if (!mic_testing && !mic_test_state) return;   // (off and told so: the host is not asked each tick)
    mic_levels[0] = mic_levels[1] = 0;
    mic_test_state = host && host->mic_test ? host->mic_test(mic_testing, mic_levels) : 0;
    if (!(mic_test_state & HOS_MIC_TEST_ON)) mic_testing = false, mic_test_state = 0;
}
void menu_tick() {
    std::lock_guard<std::recursive_mutex> bridge_lk(menu_mu);   // ((Triforce) the control bridge's settings: menu_setting_set)
    auto_tick();   // ((Triforce) Auto (this PC): a step its tuning asked for
    if (sim_turf_tick(prof_now())) menu_refresh = true;   // ((Triforce, 11-24) the Simulated turf page: its rows' changes, the area)
    menu_debug_rows(opts.descriptor_reuse, opts.sampler_cache);   // ((Triforce) the two Debug rows, taken in play: vk_draw.cpp)
    fullscreen_tick();
    merged_sync();   // ((Triforce, options_version 7) the merged rows from the saved values: a change made elsewhere shows)
    // (Triforce) the Mods entry under the game's list: the host's word that the cursor goes onto it (the game's Down, which the
    // game was not given) or that it was clicked (open at once)
    // ((Triforce, 11-19) the owner: "when scrolling with the controller, the mods tab gets skipped over and goes straight to quit".
    // The host tells of the Down (host/nn_hid.c npad_states) in the same read that gives the pad's bits, so at this tick the
    // pad's Down is also new below (pad_held is the last tick's, before it), and the menu being open now, it was taken a
    // second time as the entry's own Down: on to Quit at once. That Down is the move onto Mods, made: not one of the entry's.
    // The keys had it seldom (their Down is mostly taken on a tick before, with the menu shut). Held, it repeats on to Quit
    // after 0.35 s as the game's list does)
    bool entered_by_down = false;
    static int64_t mods_down_repeat_ns = 0;   // (the held Down's repeat onto Mods, word 5: when; 0 none)
    if (const int enter = mods_enter.exchange(0, std::memory_order_relaxed)) {
        if (!open_now.load() && mods_list_fresh()) {
            // ((Triforce, 11-19) a click on the title's entry: the game's Decide on it first, then the Mods screen (as A, below))
            const bool decide = enter == 2 && mods_title_list();
            open_now = true, embed_open = false, listening = 0, mods_btn = 0, mods_follow = true;
            page = enter == 2 && !decide ? kModsPage : kModsRowPage;
            // ((Triforce) 11-19: 3, Quit clicked: its dialog opens; 4, the mouse moved onto Quit: it has the cursor)
            mods_row_sel = enter == 3 || enter == 4 ? 1 : 0, quit_gone(), quit_sel = 0;
            if (enter == 3 && !mods_title_list()) quit_open();
            if (enter == 3 && files_row_shown()) files_open(true);   // ((Triforce) on the title it is Save Select: the file select at once)
            entered_by_down = enter == 1 || enter == 5;
            // ((Triforce, 11-19) 5: a Down held from higher up the game's list, its repeat onto Mods: held on, it repeats
            // on at the step (the repeat below takes it as held past the first delay), as the game's list went on)
            mods_down_repeat_ns = enter == 5 ? prof_now() : 0;
            if (enter == 2 && !decide) mods_open_page();
            if (decide) mods_decide_ns = prof_now();
            auto_pad = pad_last;
            ui::want_glyphs();
            // (its own: before the options' state is taken. (Triforce, 11-17) the system menu's, as the game's list it is under)
            const bool clicked = enter == 2 || enter == 3;
            mods_sound(clicked ? HOS_MENU_SOUND_SYS_DECIDE : HOS_MENU_SOUND_SYS_CURSOR);
            logf("menu: the %s entry %s%s", enter == 3 || enter == 4 ? "Quit" : "Mods", clicked ? "clicked" : "has the cursor",
                 enter == 5 ? " (a held Down's repeat)" : "");
            menu_refresh = true;
        } else {   // ((Triforce, 11-19) a word not taken says so: the lab's lost Down left no line)
            logf("menu: the host's word %d for the Mods entry not taken: %s", enter,
                 open_now.load() ? "the menu is open" : "the game's list was last told of too long ago");
        }
    }
    // (Triforce) the host's word on a file chosen at the file select: kept as the next start's, the game restarts as Restart now does; or not kept)
    if (const int said = save_files.take_said()) {
        files_wait = -1, menu_refresh = true;
        if (said == save_file_rows::kRestart) {
            save();
            pipeline_cache_save(true);
            memory_trial_orderly_end();
            logf("menu: restart (another save file)");
            open_now = false, page = 0;
            if (const HWND window = app_window()) PostMessageA(window, WM_APP + 9, 0, 0);
        } else files_failed = true;
    }
    if (!open_now.load() || page != kModsPage) {   // ((Triforce) no text taken off the Mods screen: none kept for it either)
        mods_text_wanted.store(false, std::memory_order_relaxed);
        std::lock_guard<std::mutex> g(mods_typed_mu);
        // ((Triforce) but the Output width and height rows' digits, while one of them is selected: size_edit)
        if (size_text_wanted.load(std::memory_order_relaxed) && size_typed.size() < 64)
            size_typed.insert(size_typed.end(), mods_typed.begin(), mods_typed.end());
        mods_typed.clear();
    }
    const menu_sound::State sound_before = sound_state();   // ((Triforce) the options' own sounds: told at this tick's end)
    const int64_t sound_share = share_busy_until.load(std::memory_order_relaxed);
    enum { K_N = 17 };
    static bool held[K_N];
    static const int keys[K_N] = {VK_INSERT, VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT, VK_ESCAPE, VK_F1,   // (F1: for keyboards without Insert)
                                  VK_RETURN, VK_DELETE, VK_BACK,
                                  'Q', 'E', VK_TAB,   // (the tabs: Q and E, Tab and Shift+Tab)
                                  VK_PRIOR, VK_NEXT, VK_HOME, VK_END};   // (the long lists: a page, the ends)
    HWND fg = GetForegroundWindow();
    DWORD pid = 0;
    if (fg) GetWindowThreadProcessId(fg, &pid);
    const bool mine = pid == GetCurrentProcessId();
    struct MicTick {   // ((Triforce) 11-24: the Test microphone row's test, as this tick ends: mic_test_tick)
        bool focused;
        ~MicTick() { mic_test_tick(focused); }
    } mic_tick{mine};
    bool press[K_N] = {};
    bool key_queued[K_N] = {};   // ((Triforce, 11-19) the host's queue had a press of it: the game's keys below)
    for (int i = 0; i < K_N; i++) {
        const bool down = mine && (GetAsyncKeyState(keys[i]) & 0x8000) != 0;
        const bool queued = host && host->take_key_press && host->take_key_press(keys[i]);
        key_queued[i] = mine && queued;
        // Read both keys even if one is disabled, so old presses cannot toggle the menu after a change.
        // (F1 always opens the menu; Menu shortcut's F1 only leaves Insert to an overlay)
        const bool enabled = keys[i] != VK_INSERT || opts.menu_shortcut != 1;   // (Insert: all but F1 only)
        press[i] = enabled && (host && host->take_key_press ? mine && queued : down && !held[i]);
        held[i] = down;
        if (press[i]) pad_last = false;   // (the keys: their names in the prompts)
    }
    // (hookshot) the gamepads, by position: Home, or Select and Start together, as Insert; the D-pad as the arrows; the
    // buttons the Switch's A and B are bound to as Enter and Esc, as in the game (vk_menu_keys.h; with the Nintendo layout A
    // is the right face button), not while a binding waits for its button
    static uint32_t pad_held = 0;
    // ((Triforce, 11-18) the controllers as the game has them: also with its window behind another one when "Controller in
    // background" is on (host/nn_hid.c pads_in_background: HOS_INPUT_BACKGROUND over the row). They were the front window's
    // only here, so with the row on and another window in front the game took the pad and the menu did not: L and R did not
    // reach our tabs from the game's Options screen, the owner's for a while. The keys stay the front window's)
    static const char* pad_bg_env = getenv("HOS_INPUT_BACKGROUND");
    // ((Triforce VR) in the headset the window is seldom in front: a VR session in focus counts as in front for the pads)
    const bool pads_ok = mine || vk_xr_head_active() || (pad_bg_env ? atoi(pad_bg_env) != 0 : opts.pad_background != 0);
    uint32_t raw = pads_ok && host && host->pad_raw ? host->pad_raw() : 0;
    {   // ((Triforce VR) the hand controllers in a menu: their buttons as the pad inputs those Switch buttons are bound to, the
        // left stick as the menus' stick bits, the right's up and down too)
        uint64_t sw = 0;
        float st[2][2];
        if (vk_xr_menu_buttons(&sw, st)) {
            for (int b = 0; b < HOS_SW_N && host && host->binding; b++)
                if (sw >> b & 1) {
                    const int p = host->binding(HOS_BIND_PAD, b, 0);
                    if (p >= 0 && p < HOS_PAD_N) raw |= 1u << p;
                }
            if (st[0][1] > 0.5f) raw |= 1u << HOS_PAD_LS_UP;
            if (st[0][1] < -0.5f) raw |= 1u << HOS_PAD_LS_DOWN;
            if (st[0][0] < -0.5f) raw |= 1u << HOS_PAD_LS_LEFT;
            if (st[0][0] > 0.5f) raw |= 1u << HOS_PAD_LS_RIGHT;
            if (st[1][1] > 0.5f) raw |= 1u << HOS_PAD_RS_UP;
            if (st[1][1] < -0.5f) raw |= 1u << HOS_PAD_RS_DOWN;
        }
    }
    const uint32_t pad_press = raw & ~pad_held;
    const uint32_t chord = 1u << HOS_PAD_BACK | 1u << HOS_PAD_START;
    const bool chord_now = (raw & chord) == chord && (pad_held & chord) != chord;
    pad_held = raw;
    menu_pad_raw = raw;   // ((Triforce) the Mods screen's description scroll reads the right stick's bits)
    if (pad_press) pad_last = auto_pad = true;   // (a controller: its buttons in the prompts, and Menu size Auto's choice)
    {   // (RX_VK_UI_PROMPTS=pad or keys: the prompts for screenshots of test runs, which have no controller and no focus)
        static const char* force = getenv("RX_VK_UI_PROMPTS");
        if (force) pad_last = !strcmp(force, "pad");
    }
    auto pad = [&](int p) { return listening != 1 && (pad_press >> p & 1) != 0; };
    if (host && host->binding)   // (A and B as bound now: the Controls page or the Layout preset can change them)
        menu_keys::confirm_back(host->binding(HOS_BIND_PAD, HOS_SW_A, 0), host->binding(HOS_BIND_PAD, HOS_SW_B, 0), &pad_confirm,
                                &pad_back);
    {   // ((Triforce) per-control reset) the Controls page's Clear on a controller: the top face button, else the first free one
        static const int order[4] = {HOS_PAD_NORTH, HOS_PAD_WEST, HOS_PAD_SOUTH, HOS_PAD_EAST};
        pad_clear = HOS_PAD_NORTH;
        for (int k = 3; k >= 0; k--)
            if (order[k] != pad_confirm && order[k] != pad_back) pad_clear = order[k];
    }
    if (pad(HOS_PAD_GUIDE) || chord_now) press[0] = true;
    // (Menu shortcut's touchpad choices: a DualShock 4's or DualSense's touchpad click is F1, it opens and closes the menu as
    // the key does, where the keys open it at all: menu_allowed below)
    if (opts.menu_shortcut >= 3 && pad(HOS_PAD_TOUCHPAD)) press[6] = true;
    // ((Triforce, 11-19) the keys the player bound to the game's D-pad, its movement and its A, on the entries under the game's
    // list (Mods, Quit and its dialog): the keys that brought the game's cursor down the list (S, or the D-pad's 4, by default)
    // go on in the same way from Mods, and its A (E) chooses. They were the menu's own arrows and Enter alone there, and E,
    // the menu's next tab, gave the cursor back to the game. A bit each, by press[]'s places (1 Up to 4 Right, 7 A): held now
    // (game_keys) and new since the last tick (game_keys_new; read every tick, so one held from before is no press).
    // ((Triforce, 11-19) a key's press is one, from one place: as the L, R and B keys' below, it counts when the key was not
    // down at the last tick and is down now or the host's queue has its press (a tap between two ticks). The queue's press
    // comes a little after the key's state (the window's thread notes it): one counted on the key's state is not counted
    // again when its queued press comes at the next tick, and a key that is one of the menu's own (E, its next tab; an arrow)
    // is the game's only there, not also the menu's: E on Mods was A by its state and the next tab by its queued press, one
    // press two moves, and a quick tap the next tab alone, the cursor given back to the game. Its queued press that comes
    // after A opened the Mods screen is that same press, not the screen's next category)
    uint32_t game_keys = 0, game_keys_new = 0;
    int gk_vk[20] = {}, gk_n = 0;   // (the game's keys read here and what the queue had of each, for the L, R and B keys below)
    bool gk_q[20] = {};
    {
        static menu_keys::KeyPress gk_key[256];
        static const int binds[5][2] = {{HOS_SW_UP, HOS_KEY_MOVE_UP}, {HOS_SW_DOWN, HOS_KEY_MOVE_DOWN},
                                        {HOS_SW_LEFT, HOS_KEY_MOVE_LEFT}, {HOS_SW_RIGHT, HOS_KEY_MOVE_RIGHT}, {HOS_SW_A, -1}};
        static const int places[5] = {1, 2, 3, 4, 7};
        uint32_t vk_places[20] = {};
        for (int b = 0; b < 5 && host && host->binding; b++)
            for (int j = 0; j < 2; j++)
                for (int slot = 0; slot < 2 && binds[b][j] >= 0; slot++) {
                    const int vk = host->binding(HOS_BIND_KEY, binds[b][j], slot);
                    if (vk < 8 || vk >= 256) continue;
                    int m = 0;
                    while (m < gk_n && gk_vk[m] != vk) m++;
                    if (m == gk_n) gk_vk[gk_n++] = vk;
                    vk_places[m] |= 1u << places[b];
                }
        const bool row = open_now.load() && page == kModsRowPage && listening == 0;
        const bool queue = host && host->take_key_press;
        const int64_t t = prof_now();
        for (int m = 0; m < gk_n; m++) {
            const int vk = gk_vk[m];
            int own = -1;   // (the menu's own key it is, if any: its queued press taken above)
            for (int i = 0; i < K_N && own < 0; i++)
                if (keys[i] == vk) own = i;
            const bool down = mine && (GetAsyncKeyState(vk) & 0x8000) != 0;
            const bool q = own >= 0 ? key_queued[own] : queue && host->take_key_press(vk) && mine;
            bool echo = false;
            const bool went = menu_keys::key_press(gk_key[vk], down, q, row, queue, t, &echo);
            if (echo && own >= 0) press[own] = false;   // (the queued press of one counted already, on the entries)
            if (row) {
                if (down) game_keys |= vk_places[m];
                if (went) game_keys_new |= vk_places[m];
                if (own >= 0) press[own] = false;   // (the game's key there, its press counted in went)
            }
            gk_q[m] = q && !echo && !row;
        }
        if (game_keys_new) pad_last = false;
    }
    {   // holding an arrow or the D-pad repeats it: after 0.35 s, 12 a second, then 30 a second after 1.5 s held
        static int64_t held_since[5], next_repeat[5];
        const int pads[5] = {0, HOS_PAD_UP, HOS_PAD_DOWN, HOS_PAD_LEFT, HOS_PAD_RIGHT};
        // ((Triforce) 11-17, his "you cannot go up from mods ... with the analog stick": the left stick as the D-pad)
        const int sticks[5] = {0, HOS_PAD_LS_UP, HOS_PAD_LS_DOWN, HOS_PAD_LS_LEFT, HOS_PAD_LS_RIGHT};
        const int64_t t = prof_now();
        // ((Triforce, 11-19) and the directions a test's script holds while the Mods entry or its screen has the cursor, as the
        // host told at its last read (host/nn_hid.c mods_input): repeated as a pad's are. A report older than a quarter second
        // is none (the host reads each game frame))
        const bool mods_here = page == kModsRowPage || page == kModsPage;
        const int host_held = mods_here && t - mods_held_ns.load(std::memory_order_relaxed) < 250000000LL
                                  ? mods_held_dirs.load(std::memory_order_relaxed) : 0;
        for (int i = 1; i <= 4; i++) {
            const bool down = held[i] || (game_keys >> i & 1) || (open_now.load() && listening != 1 &&
                                          ((raw >> pads[i] & 1) || (raw >> sticks[i] & 1) || (host_held >> (i - 1) & 1)));
            if (!down) { held_since[i] = 0; continue; }
            if (!held_since[i] && i == 2 && mods_down_repeat_ns && t - mods_down_repeat_ns < 250000000LL) {
                // ((Triforce, 11-19) the held Down that came onto Mods by repeat: past the first delay already, on at the step)
                held_since[i] = t - 350000000LL, next_repeat[i] = t + 83000000LL, mods_down_repeat_ns = 0;
                continue;   // (a script's held Down is told at the host's next read: a quarter second for it)
            }
            if (!held_since[i]) { held_since[i] = t, next_repeat[i] = t + 350000000LL; continue; }
            if (t >= next_repeat[i] && open_now.load() && listening == 0) {
                press[i] = true;
                next_repeat[i] = t + (t - held_since[i] > 1500000000LL ? 33000000LL : 83000000LL);
            }
        }
    }
    if (open_now.load() && listening != 1) {
        press[1] |= pad(HOS_PAD_UP) || pad(HOS_PAD_LS_UP), press[2] |= pad(HOS_PAD_DOWN) || pad(HOS_PAD_LS_DOWN);
        press[3] |= pad(HOS_PAD_LEFT) || pad(HOS_PAD_LS_LEFT), press[4] |= pad(HOS_PAD_RIGHT) || pad(HOS_PAD_LS_RIGHT);
        press[5] |= pad(pad_back), press[7] |= pad(pad_confirm);
    }
    int script_tab = 0;   // (a test's TABL or TABR: on the game's own tab too, where Q and E are not ours)
    {   // RX_VK_MENU_SCRIPT (test runs, which never have the focus): timed menu keys, "<seconds>:<INS|UP|DOWN|LEFT|RIGHT|ESC|ENTER|TABL|TABR>,...";
        // and the gamepad's face buttons by position, PADS PADE PADW PADN (bottom, right, left, top), as a controller's press
        static const char* next = getenv("RX_VK_MENU_SCRIPT");
        static const int64_t start = prof_now();
        double at;
        char key[8];
        int n = 0;
        if (next && sscanf(next, "%lf:%7[A-Z]%n", &at, key, &n) == 2 && (prof_now() - start) / 1e9 >= at) {
            static const char* names[] = {"INS", "UP", "DOWN", "LEFT", "RIGHT", "ESC", "", "ENTER", "", "", "TABL", "TABR"};
            for (int i = 0; i < 12; i++) press[i] |= *names[i] && !strcmp(key, names[i]);
            script_tab = !strcmp(key, "TABL") ? -1 : !strcmp(key, "TABR") ? 1 : 0;
            static const char* pads[] = {"PADS", "PADE", "PADW", "PADN"};
            for (int p = 0; p < 4; p++)
                if (!strcmp(key, pads[p]) && open_now.load() && listening != 1) {
                    press[5] |= p == pad_back, press[7] |= p == pad_confirm;
                    pad_last = auto_pad = true;
                }
            next = next[n] == ',' ? next + n + 1 : nullptr;
        }
    }
    {   // ((Triforce, 11-22, N64 Classic, step 5) F7: N64 Classic between Off and the last preset (n64_rules.h Toggle, the last
        // kept as n64_classic_last), saved as the row is, said at the foot of the screen; not while RX_VK_N64 sets it for the run.
        // The last preset follows the row too, whoever chose it
        static bool f7_held = false;
        if (opts.n64_classic == n64_rules::FAITHFUL || opts.n64_classic == n64_rules::REMEMBERED) opts.n64_last = opts.n64_classic;
        const bool f7_down = mine && (GetAsyncKeyState(VK_F7) & 0x8000) != 0;
        if (f7_down && !f7_held && !n64_env_set()) {
            n64_rules::Toggle toggle;
            toggle.last = opts.n64_last;
            opts.n64_classic = toggle.pressed(opts.n64_classic);
            opts.n64_last = toggle.last;
            save();
            snprintf(notice_text, sizeof notice_text, "N64 Classic: %s", n64_rules::name(opts.n64_classic));
            notice_until = prof_now() + 2000000000LL;
            logf("menu: F7: N64 Classic %s", n64_rules::name(opts.n64_classic));
        }
        f7_held = f7_down;
    }
    {   // ((Triforce, 11-24) F2: Evil HD on and off, the owner's "i want f2 to enable evil [hd] ... it updates in the options
        // menu": the row's own value (opts.evil_hd), saved as the row is, said at the foot of the screen as F7 says N64 Classic.
        // Texture detail Full still waits for the next start, as the row says
        static bool f2_held = false;
        const bool f2_down = mine && (GetAsyncKeyState(VK_F2) & 0x8000) != 0;
        if (f2_down && !f2_held) {
            opts.evil_hd = opts.evil_hd ? 0 : 1;
            save();
            snprintf(notice_text, sizeof notice_text, "Evil HD: %s", opts.evil_hd ? "On" : "Off");
            notice_until = prof_now() + 2000000000LL;
            logf("menu: F2: Evil HD %s", opts.evil_hd ? "on" : "off");
        }
        f2_held = f2_down;
    }
    {   // (Triforce) F8, a bug capture. The window's key handler asks the host for it itself (host/display.c); where the host has
        // no queue of key presses (Linux) the key is read here, and asked for as the rows ask
        static bool f8_held = false;
        const bool f8_down = mine && !(host && host->take_key_press) && (GetAsyncKeyState(VK_F8) & 0x8000) != 0;
        if (f8_down && !f8_held) share_ask.store(HOS_SHARE_CAPTURE_KEY, std::memory_order_relaxed);
        f8_held = f8_down;
    }
    // (the host's line for the foot of the screen: a capture was saved. One load a tick while there is none)
    if (share_notice_new.load(std::memory_order_relaxed) && share_notice_new.exchange(false, std::memory_order_acq_rel)) {
        std::lock_guard lk(share_mu);
        snprintf(notice_text, sizeof notice_text, "%s", share_lines[HOS_SHARE_NOTICE].c_str());
        notice_until = prof_now() + 4000000000LL;
    }
    // ((Triforce) an achievement earned: its notice, from now for kAchNoticeMs)
    // ((Triforce) 11-23: not with the Achievement notices row Off; the list has it as earned all the same)
    if (const int earned = ach_list.take_fresh(); earned >= 0 && opts.achievement_notices) ach_notice = earned, ach_notice_at = prof_now();
    if (cur_tab == TAB_DEBUG && !debug_shown()) cur_tab = TAB_DISPLAY;
    {   // (Triforce) presses the host passed on while the Mods entry or its screen has the cursor (a test's scripted ones)
        const int mp = mods_press.exchange(0, std::memory_order_relaxed);
        if (mp && open_now.load() && (page == kModsRowPage || page == kModsPage)) {
            press[1] |= (mp & HOS_MODS_PRESS_UP) != 0, press[2] |= (mp & HOS_MODS_PRESS_DOWN) != 0;
            press[3] |= (mp & HOS_MODS_PRESS_LEFT) != 0, press[4] |= (mp & HOS_MODS_PRESS_RIGHT) != 0;
            press[7] |= (mp & HOS_MODS_PRESS_A) != 0, press[5] |= (mp & HOS_MODS_PRESS_B) != 0;
            script_tab = (mp & HOS_MODS_PRESS_L) ? -1 : (mp & HOS_MODS_PRESS_R) ? 1 : script_tab;
            pad_last = true;
        }
    }
    for (int i : {1, 2, 3, 4, 7}) press[i] |= (game_keys_new >> i & 1) != 0;   // ((Triforce, 11-19) the game's keys on Mods, above)
    if (entered_by_down) press[2] = false;   // ((Triforce, 11-19) the Down that brought the cursor onto Mods: the game list's move, made)
    bool tab_left = press[10] || pad(HOS_PAD_LSHOULDER) || pad(HOS_PAD_LTRIGGER);
    bool tab_right = press[11] || press[12] || pad(HOS_PAD_RSHOULDER) || pad(HOS_PAD_RTRIGGER);
    if (press[12] && (GetAsyncKeyState(VK_SHIFT) & 0x8000)) tab_left = true, tab_right = false;
    // ((Triforce) the keys the player bound to the Switch's L, R and B (triforce_options.ini key_l, key_r, key_b: Q, R and Shift
    // by default), which the tab strip's ends and the guides name (ui_ctx): our tabs and Back answer to them as the game's own
    // Options tab does, beside Q, E, Tab and Esc; and the gamepad inputs L and R are bound to, beside the shoulders and the
    // triggers. A key the menu has a use of its own for keeps that use (menu_bound_key). A modifier (B's Shift by default)
    // counts as it is let go with nothing else pressed meanwhile, so Shift+Tab still steps back a tab (the host
    // taps the game's Back for it all the same, host/nn_hid.c). Read every tick, so a press from before the menu opened is
    // not taken. game_lr: the keys bound to L and R as the game has them, every one, for its own tab below)
    // (A key that is no modifier also counts from the host's queue of presses, as the menu's own keys do, so a quick tap
    // between two ticks is not lost: counted when the key was not down at the last tick, so no press counts twice. A
    // modifier is no press of its own once anything else went with it: any other key or mouse button down, a pad press, the
    // wheel (below, at the mouse's read), or the window losing the front, Win+Shift+S or Alt+Tab)
    bool bound_go[3] = {}, game_lr[2] = {};   // (L, R, B pressed this tick)
    static bool bound_armed[3][2];            // (a modifier bound to L, R or B down alone so far: a press as it is let go)
    {
        static bool bound_held[3][2], game_held[2][2];
        static const int buttons[3] = {HOS_SW_L, HOS_SW_R, HOS_SW_B};
        bool other = !mine || pad_press != 0;   // (a key of the menu's down or pressed, and the rest above)
        for (int i = 0; i < K_N; i++) other |= held[i] || press[i];
        int vks[6] = {};
        bool downs[6] = {}, queued[6] = {};
        for (int n = 0; n < 6; n++) {
            const int b = n / 2, slot = n % 2, vk = vks[n] = menu_bound_key(buttons[b], slot);
            if (vk && !menu_modifier_key(vk) && host && host->take_key_press) {   // (one key bound twice: taken once)
                int m = 0;
                while (m < n && vks[m] != vk) m++;
                int g = 0;   // ((Triforce, 11-19) a key also bound to the game's D-pad, movement or A: its queue read there)
                while (g < gk_n && gk_vk[g] != vk) g++;
                queued[n] = m < n ? queued[m] : g < gk_n ? gk_q[g] : host->take_key_press(vk) && mine;
            }
            const bool down = downs[n] = mine && vk && (GetAsyncKeyState(vk) & 0x8000) != 0;
            const bool went = !bound_held[b][slot] && (down || queued[n]);
            bound_held[b][slot] = down;
            if (!menu_modifier_key(vk)) {
                bound_go[b] |= went, other |= went, bound_armed[b][slot] = false;
                continue;
            }
            if (went) bound_armed[b][slot] = true;
        }
        for (int n = 0; n < 6; n++) {
            const int b = n / 2, slot = n % 2, vk = vks[n];
            if (!bound_armed[b][slot]) continue;
            bool with = other;   // (any other key or mouse button down: read only while a modifier waits)
            for (int k = 1; k < 255 && !with; k++) with = !menu_same_modifier(vk, k) && (GetAsyncKeyState(k) & 0x8000) != 0;
            if (with || listening || !open_now.load()) bound_armed[b][slot] = false;   // (or it went down for a binding, or in play)
            else if (!downs[n]) bound_go[b] = true, bound_armed[b][slot] = false;
        }
        for (int side = 0; side < 2 && host && host->binding; side++)
            for (int slot = 0; slot < 2; slot++) {
                const int vk = host->binding(HOS_BIND_KEY, side ? HOS_SW_R : HOS_SW_L, slot);
                const bool down = mine && vk && (GetAsyncKeyState(vk) & 0x8000) != 0;
                if (down && !game_held[side][slot]) game_lr[side] = true;
                game_held[side][slot] = down;
            }
    }
    // (not while the Mods screen's search takes the keyboard's text, menu_mods_typing: there a bound R is a letter of the
    // search, not the next category, and B's Shift let go alone would clear it. Read all the same above, so no press is kept)
    if (open_now.load() && listening == 0) {
        if (bound_go[0] || bound_go[1] || bound_go[2]) pad_last = false;
        if (!menu_mods_typing()) tab_left |= bound_go[0], tab_right |= bound_go[1], press[5] |= bound_go[2];
        for (int side = 0; side < 2 && host && host->binding; side++) {   // (a pad input the menu has no other use for)
            const int p = host->binding(HOS_BIND_PAD, side ? HOS_SW_R : HOS_SW_L, 0);
            const bool own = p == HOS_PAD_UP || p == HOS_PAD_DOWN || p == HOS_PAD_LEFT || p == HOS_PAD_RIGHT || p == HOS_PAD_GUIDE ||
                             p == HOS_PAD_BACK || p == HOS_PAD_START || p == pad_confirm || p == pad_back ||
                             p == HOS_PAD_LSHOULDER || p == HOS_PAD_RSHOULDER || p == HOS_PAD_LTRIGGER || p == HOS_PAD_RTRIGGER;
            if (hos_pad_bindable(p) && !own && pad(p)) (side ? tab_right : tab_left) = true;
        }
    }
    // ((Triforce) the upscalers asked ahead once the game has a frame up (menu_ahead), and the Frame generation row set again once
    // they have answered. The game's button icons asked for as the game's own Options screen comes, ahead of our tabs' open:
    // read on a thread of their own, vk_imgui.cpp)
    if (ahead_allowed() && dev.device && !dev.offscreen && game_frames.load(std::memory_order_relaxed) > 0) menu_ahead();
    {
        static bool resynced = false;
        if (!resynced && ahead_state.load(std::memory_order_acquire) == 2) resynced = true, framegen_row_sync();
    }
    // (Triforce) inside the game's own Options screen (see game_options_ns)
    const bool in_game_options = game_options_shown();
    if (in_game_options) ui::want_glyphs();
    if (!in_game_options) {
        embed_since = 0;
        game_tab_read = false;   // ((Triforce) the game's tab's mouse: read anew when its screen comes again)
        if (embed_open) {   // (the game's screen went: ours with it)
            embed_open = false;
            if (open_now.load() && page != 5) open_now = false, page = 0, menu_refresh = true;
        }
    } else {
        if (!embed_since) embed_since = prof_now();
        if (open_now.load()) embed_open = true;   // (opened over it with F1 as well)
    }
    if (in_game_options && !open_now.load()) {
        // The game's own tab: the game has the input. L and R as it has them go to our tabs: the gamepad inputs the Switch's L
        // and R are bound to, and their keys (Q, E and Tab are the game's own keys here: E is its A by default)
        // ((Triforce) the keys' presses are game_lr's, above: read every tick, so a key that closed our tabs at their end and is
        // still held does not open them again)
        bool go[2] = {script_tab < 0, script_tab > 0};
        for (int side = 0; side < 2 && host && host->binding; side++) {
            const int sw = side ? HOS_SW_R : HOS_SW_L, p = host->binding(HOS_BIND_PAD, sw, 0);
            if (hos_pad_bindable(p) && (pad_press >> p & 1)) go[side] = true, pad_last = auto_pad = true;
            if (game_lr[side]) go[side] = true, pad_last = false;
        }
        // ((Triforce) the mouse on our tabs over the game's header, as on the open menu's: a tab under it lit, a click on one shows
        // it, on the L and R (Q and E) at their ends as L and R. Its presses are the window's for the game's menus too
        // (host/display.c game_menu_press), and host/oot_menu.c leaves the header's to these; elsewhere the game's)
        int clicked_tab = -1;
        if (host && host->pointer) {
            MkwVkPointer gp{};
            const bool on = host->pointer(&gp) != 0 && hits_game_tab;
            if (!game_tab_read) gp.pressed = 0, game_tab_read = true;   // (pressed before the tabs were shown: not theirs)
            int ix = 0, iy = 0;
            menu_hit::to_image(gp.x, gp.y, gp.width, gp.height, (int)dev.swap_extent.width, (int)dev.swap_extent.height, &ix, &iy);
            // ((Triforce, 11-22, N64 Classic) the tabs drawn under its TV: the cursor where the curve showed them)
            if (options_under_tv) n64_screen_point(&ix, &iy, (int)dev.swap_extent.width, (int)dev.swap_extent.height);
            const menu_hit::Hit hit = on ? hits.at(game_tab_map.back_x((float)ix), game_tab_map.back_y((float)iy)) : menu_hit::Hit{};
            hover_tab = hit.part == menu_hit::kTab && hit.index != kGameTab ? hit.index : -1;
            if (on && (gp.pressed & HOS_MOUSE_LEFT)) {
                if (hit.part == menu_hit::kTabPrev) go[0] = true, pad_last = false;
                else if (hit.part == menu_hit::kTabNext) go[1] = true, pad_last = false;
                else if (hover_tab >= 0 && hover_tab < tabs_shown()) clicked_tab = hover_tab, pad_last = false;
            }
        }
        if (go[0] || go[1] || clicked_tab >= 0) {
            const int64_t open0 = prof_now();   // ((Triforce) the open's own work, logged at the first: nothing of it should wait)
            open_now = true, embed_open = true, page = 0, listening = 0;
            cur_tab = clicked_tab >= 0 ? clicked_tab : go[1] ? TAB_DISPLAY : tabs_shown() - 1;
            auto_pad = pad_last;
            ui::want_glyphs();
            opts.pad_layout = detect_pad_layout();
            menu_ahead();   // ((Triforce) whether the Upscaler row can offer DLSS and FSR here: asked off this thread)
            framegen_row_sync();   // (Triforce: whether the Frame generation row can offer AMD FSR 4 here, as known)
            refresh_mics();
            menu_refresh = true;
            static bool told = false;
            if (!told)
                told = true, logf("menu: the options opened from the game's Options in %.1f ms (the upscalers %s)", (prof_now() - open0) / 1e6,
                                  ahead_state.load(std::memory_order_acquire) == 2 ? "answered ahead" : "still being asked, off this thread");
        }
        tab_left = tab_right = false;   // (taken: the first tick of ours does not step on)
    }
    bool changed = menu_refresh;
    menu_refresh = false;
    // (hookshot) the mouse, while the menu is open: the cursor in the window image's pixels (mx, my), tested against the
    // controls as last drawn (hits, vk_menu_hit.h), whether it moved since the last frame, and its clicks and wheel since then
    MkwVkPointer ptr{};
    int mx = -1, my = -1;
    bool mouse = false, moved = false;
    if (open_now.load() && host && host->pointer) {
        mouse = host->pointer(&ptr) != 0;
        int ix = 0, iy = 0;
        menu_hit::to_image(ptr.x, ptr.y, ptr.width, ptr.height, (int)dev.swap_extent.width, (int)dev.swap_extent.height,
                           &ix, &iy);
        // ((Triforce, 11-22, N64 Classic) the options drawn under its TV: the cursor where the curve showed them)
        if (options_under_tv) n64_screen_point(&ix, &iy, (int)dev.swap_extent.width, (int)dev.swap_extent.height);
        if (mouse) mx = (int)std::floor(menu_map.back_x((float)ix)), my = (int)std::floor(menu_map.back_y((float)iy));   // (the menu's column's pixels: draw_menu)
        // ((Triforce) the first read takes no click: one from before the menu opened is not its own. The window keeps the
        // clicks on the game's Options screen for its tabs over the header, host/display.c game_menu_press)
        if (!mouse_read) ptr.pressed = 0;
        static int last_x = -1, last_y = -1;
        moved = mouse && mouse_read && (mx != last_x || my != last_y);   // (not the first read: a cursor resting over the
        last_x = mx, last_y = my, mouse_read = true;                     // menu as it opens leaves the selection alone)
        if (moved) pad_last = false;
        if (!mouse) ptr.pressed = 0, ptr.wheel = 0;
        if (ptr.pressed || ptr.wheel)   // (a click or the wheel with a modifier bound to L, R or B held: it is no press of its own)
            for (auto& armed : bound_armed) armed[0] = armed[1] = false;
    }
    // (closing with a setting that takes a restart changed: the restart question first, Later already chosen on it)
    auto later = [&] {
        int now[mr::kMax];
        restart_values(now);
        restart_state.choose_later(now);
        open_now = false, page = 0, changed = true;
    };
    // (Triforce) Setup chooses the settings before the game starts, and the menu was hidden for that. 11-10: on by default again,
    // for upstream's new rows that Setup has no place for yet. TRIFORCE_INGAME_MENU=0 (triforce_env.txt) hides it: Insert, F1,
    // Home and Select+Start then open nothing
    // (Triforce, 11-13: off by default now, overlay_allowed above. While the options are open, from inside the game's Options,
    // the keys still close them)
    static const bool menu_allowed = overlay_allowed();
    // (Menu shortcut "Insert, F1 or Esc": Esc on a closed menu opens it, the keyboard's and RX_VK_MENU_SCRIPT's ESC alone (the
    // gamepad's back is Esc only while it is open, above), and only where the keys open it at all (menu_allowed). The press
    // that opened it does not go back a page below. No control can be bound to Esc (bindable_keys), so nothing in play
    // changes; the window gives the captured mouse back on the close (host/display.c esc_had_capture))
    // ((Triforce) 11-24) the ReShade comparison (reshade_menu.h): its bar takes the keys and the mouse alone. Up and down its rows,
    // left and right its choices, confirm; back, Insert, F1 or the right button close it, the saved preset back. The options shut
    // another way end it too
    if (reshade_menu::comparing()) {
        if (!open_now.load()) reshade_menu::end_comparison();
        else {
            const auto click = mouse && (ptr.pressed & HOS_MOUSE_LEFT) ? hits.at((float)mx, (float)my) : menu_hit::Hit{};
            const bool cancel = press[0] || press[6] || press[5] || (mouse && (ptr.pressed & HOS_MOUSE_RIGHT));
            changed |= reshade_menu::update_comparison(int(press[4]) - int(press[3]), int(press[2] || tab_right) - int(press[1] || tab_left),
                                                       press[7], cancel, click);
            for (int i = 0; i < K_N; i++) press[i] = false;
            tab_left = tab_right = false, moved = false;
            ptr.pressed = 0, ptr.wheel = 0;   // (nothing of them for the page under the bar)
        }
    }
    const bool esc_opens = (opts.menu_shortcut == 2 || opts.menu_shortcut == 4) && menu_allowed && press[5] && !open_now.load();
    if (esc_opens) press[5] = false;
    if ((press[0] || press[6]) && open_now.load() && page == 5) {
        later();
    } else if ((press[0] || press[6]) && open_now.load() && restart_ask()) {
        page = 5, ask_sel = 0, listening = 0, changed = true;
    } else if (((press[0] || press[6]) && (menu_allowed || open_now.load())) || esc_opens) {
        open_now = !open_now.load(), changed = true;
        page = 0, listening = 0;
        // (the layout row shows the controls as they are: host/nn_hid.c keeps them, the ini's pad_ lines, and a saved
        // layout is not applied over them at start)
        if (open_now.load()) auto_pad = pad_last;   // (Menu size Auto: by what opened the menu)
        if (open_now.load()) ui::want_glyphs();   // (Triforce: the game's button icons, as it was served them this run)
        if (open_now.load()) opts.pad_layout = detect_pad_layout();
        if (open_now.load()) menu_ahead();   // (whether the Upscaler row can offer DLSS and FSR here: asked once, (Triforce) off this thread)
        if (open_now.load()) framegen_row_sync();   // (Triforce: and the Frame generation row AMD FSR 4, as known)
        if (open_now.load()) refresh_mics();   // (the microphones as they are now)
        if (open_now.load()) refresh_outputs();   // ((Triforce) and the playback devices)
        // ((Triforce) Right Ctrl held as it opens: the tuning bar, draw_tune_bar)
        tune_mode = open_now.load() && mine && (GetAsyncKeyState(VK_RCONTROL) & 0x8000) != 0;
    }
    {   // ((Triforce) the tuning bar: Right Ctrl or the gamepad's left face button switches the options page to it and back, over
        // play; gone with the menu. Not while a control waits for its key, nor inside the game's own Options screen)
        static bool rctrl_held = false;
        const bool rctrl = mine && (GetAsyncKeyState(VK_RCONTROL) & 0x8000) != 0, rctrl_press = rctrl && !rctrl_held;
        rctrl_held = rctrl;
        if (open_now.load()) read_mode_sizes();   // ((Triforce) the Output resolution's display modes, once, as the options first open
        if (!open_now.load() || embed_open) tune_mode = false;
        else if (page == 0 && !listening && !press[0] && !press[6] && (rctrl_press || pad(HOS_PAD_WEST)))
            tune_mode = !tune_mode, changed = true, pad_last = !rctrl_press;
    }
    if (open_now.load() && page == 5) {   // (hookshot) the restart question: Later (the default) or Restart now
        if (mouse) {   // (a button under the cursor chosen, a click on it pressed, a right click is Later; no list: the wheel does nothing)
            const menu_hit::Hit hit = hits.at((float)mx, (float)my);
            if (hit.part == menu_hit::kButton && (moved || ptr.pressed) && hit.index != ask_sel) ask_sel = hit.index, changed = true;
            if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kButton) press[7] = true;
            if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
        }
        if (press[1] || press[2] || press[3] || press[4] || tab_left || tab_right) ask_sel ^= 1, changed = true;
        if (press[5] || (press[7] && ask_sel == 0)) {
            later();
        } else if (press[7]) {   // (Restart now: everything saved, then the window closes as the player would close it)
            logf("menu: restart now, to apply %s", restart_list(", ").c_str());
            save();
            pipeline_cache_save(true);
            memory_trial_orderly_end();   // (an exit on purpose: no verdict on the memory trial)
            open_now = false, page = 0, changed = true;
            PostMessageA(app_window(), WM_APP + 9, 0, 0);
        }
    } else if (open_now.load() && page == 1) {   // (hookshot) the Controls page
        if (!can_bind()) page = 0;
        else if (control_confirmation.action != kAskNone) {   // ((Triforce) its question: Cancel or the change, as the restart question)
            ControlConfirmation& q = control_confirmation;
            if (mouse) {
                const menu_hit::Hit hit = hits.at((float)mx, (float)my);
                if (hit.part == menu_hit::kButton && (moved || ptr.pressed) && hit.index != q.choice) q.choice = hit.index, changed = true;
                if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kButton) press[7] = true;
                if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
            }
            if (press[1] || press[2] || press[3] || press[4]) q.choice ^= 1, changed = true;
            if (press[5] || (press[7] && q.choice == 0)) {
                q = {};
                changed = true;
            } else if (press[7]) {
                const ControlConfirmation done = q;
                q = {};
                if (done.action == kAskRebind) {   // (approved: the controls named; another since asks again)
                    uint64_t now = 0;
                    if (host->rebind_control(done.set, controls[done.row].button, done.slot, done.code, done.conflicts, &now))
                        after_binding(done.set);
                    else if (now) control_confirmation = {kAskRebind, done.row, done.set, done.slot, done.code, 0, now};
                } else if (done.action == kAskResetRow) {
                    if (host->reset_binding(controls[done.row].button)) blocked_reset_row = -1, after_binding(HOS_BIND_PAD);
                    else blocked_reset_row = done.row;   // (another control has one of its defaults: its help says so)
                } else {
                    host->bind(HOS_BIND_PAD, -1, 0, 0);
                    opts.pad_layout = 0;
                    save();
                }
                changed = true;
            }
        } else if (listening) {
            if (press[5] || prof_now() > listen_end) listening = 0, changed = true;   // (Esc, or nothing for a while)
            else if (listening == 1) {
                if (!listen_armed) listen_armed = (raw & ~(1u << HOS_PAD_GUIDE) & HOS_PAD_BIND_MASK) == 0;   // (not the stick's menu bits)
                // (the inputs a binding can take: not the sticks' menu bits nor the touchpad's, which bind refuses)
                else if (const uint32_t p = pad_press & ~(1u << HOS_PAD_GUIDE) & HOS_PAD_BIND_MASK) {
                    int bit = 0;
                    while (!(p >> bit & 1)) bit++;
                    listening = 0, changed = true;   // ((Triforce) its Input; asked first when another control has it)
                    bind_or_ask(HOS_BIND_PAD, csel - kTop, ccol == kColAlt ? 1 : 0, bit);
                }
            } else {
                int down = 0;
                for (int k : bindable_keys())
                    if (mine && (GetAsyncKeyState(k) & 0x8000)) {
                        // ((Triforce) 11-24: an ocarina note takes no mouse button, host/nn_hid.c hos_bind: not listened for)
                        if (note_row(csel - kTop) && (k == VK_LBUTTON || k == VK_RBUTTON || k == VK_MBUTTON || k == 0x05 || k == 0x06))
                            continue;
                        down = k;
                        break;
                    }
                if (!listen_armed) listen_armed = !down;
                else if (down) {
                    listening = 0, changed = true;   // ((Triforce) the one key; asked first when another control has it)
                    bind_or_ask(HOS_BIND_KEY, csel - kTop, 0, down);
                }
            }
        } else {
            if (mouse) {   // (the mouse: the row under it selected, a click on a binding listens for its new input, on
                           // Reset resets; the wheel scrolls the page, a right click goes back)
                const menu_hit::Hit hit = hits.at((float)mx, (float)my);
                const bool option = hit.part == menu_hit::kCtlOption;
                const bool on = option || hit.part == menu_hit::kCtlRow || hit.part == menu_hit::kCtlCell;
                const int at = option ? hit.index : kTop + hit.index;   // (the page's row: its own rows first)
                if (on && (moved || ptr.pressed)) {
                    if (at != csel) csel = at, changed = true;
                    if (hit.part == menu_hit::kCtlCell && col_usable(hit.index, hit.side) && ccol != hit.side) ccol = hit.side, changed = true;
                }
                if (ptr.pressed & HOS_MOUSE_LEFT) {
                    if (option) press[hit.side < 0 ? 3 : 4] = true;   // (a value's halves: Left and Right; the name: Right)
                    else if (hit.part == menu_hit::kCtlCell || (hit.part == menu_hit::kCtlRow && hit.index == kControls))
                        press[7] = true;   // (as Enter)
                }
                if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
                if (ptr.wheel) wheel_rows[kControlsSlot] += ptr.wheel, changed = true;   // (scrolls; the selection stays)
            }
            if (press[5]) page = 0, changed = true;
            const int n = kTop + kControls + 1, i = csel - kTop;   // (i: the control's, or reset's)
            (void)n;   // ((Triforce) per-control reset: on the Reset column, Up and Down go to the controls with one)
            if (press[1]) csel = next_control_selection(csel, ccol, -1), blocked_reset_row = -1, changed = true;
            if (press[2]) csel = next_control_selection(csel, ccol, 1), blocked_reset_row = -1, changed = true;
            if (i < 0 && (press[3] || press[4] || press[7])) {   // (the page's own rows: Enter as Right)
                Row& r = rows[tab_row_to_global(TAB_PAGE, csel)];   // (Custom is only what the bindings are: set_row skips it)
                set_row(r, *r.value + (press[3] ? -r.step : r.step), press[3] ? -1 : 1);
                changed = true;
            } else if (i >= 0) {
                if ((press[3] || press[4]) && i < kControls && (!keys_only(i) || col_usable(i, kColReset))) {   // ((Triforce) 11-24: the next usable column; a keys-only row's Reset too)
                    do ccol = (ccol + kCols + (press[3] ? -1 : 1)) % kCols;
                    while (!col_usable(i, ccol));
                    changed = true;
                }
                if (i < kControls && !col_usable(i, ccol)) ccol = keys_only(i) ? kColKeys : kColPad;   // (keys only; a note's one input)
                if (press[7]) {   // ((Triforce) Reset to defaults and a control's Reset: asked first)
                    if (i == kControls) control_confirmation = {kAskResetAll};
                    else if (ccol == kColReset) control_confirmation = {kAskResetRow, i};
                    else listening = ccol == kColKeys ? 2 : 1, listen_armed = false, listen_end = prof_now() + 6000000000LL;
                    changed = true;
                }
                if ((press[8] || press[9] || pad(pad_clear)) && i < kControls && ccol != kColReset) {   // ((Triforce) a pad's Clear too)
                    if (ccol != kColKeys) {
                        host->bind(HOS_BIND_PAD, controls[i].button, ccol == kColAlt ? 1 : 0, -1);
                        opts.pad_layout = detect_pad_layout();
                    }
                    else for (int k = 0; k < 2; k++) host->bind(HOS_BIND_KEY, controls[i].button, k, 0);
                    changed = true;
                    save();
                }
            }
        }
    } else if (open_now.load() && page == 4) {   // the inventory
        const int chosen = item_choice;   // (the page follows the choice when it moves; the wheel's page stays otherwise)
        if (mouse) inventory_mouse(ptr, mx, my, press, changed);
        if (press[5] && inventory_amount) inventory_amount = false, changed = true;   // (back: out of the amount first)
        else if (press[5]) page = 0, changed = true;   // (to the Debug tab, Inventory still selected)
        else if (tab_left || tab_right) {   // (another section, from editing an amount too: that ends)
            const int filters = kItemSections + 1;
            choose_inventory_filter((inventory_filter + filters + (tab_left ? -1 : 1)) % filters);
            changed = true;
        } else if (inventory_amount) {
            if (press[7]) inventory_amount = false, changed = true;
            else if (press[3] || press[4]) {   // ((Triforce) added to the change still waiting, debug_pending.h: each press counts)
                const int count = item_counts[item_choice].load(std::memory_order_relaxed);
                int was = cheat_action.load(std::memory_order_relaxed);
                while (count >= 0 && !cheat_action.compare_exchange_weak(was, debug_pending::amount_step(was, item_choice, count, press[4] ? 1 : -1),
                                                                         std::memory_order_relaxed)) {}
                changed = true;
            }
        } else {
            // (the cards as drawn, inventory_columns to a row: the arrows move, Page Up and Down a page, Home and End the ends)
            const int begin = inventory_begin(), end = inventory_end();
            const int step = (press[4] - press[3]) + (press[2] - press[1]) * inventory_columns + (press[14] - press[13]) * inventory_capacity;
            if (step || press[15] || press[16]) {
                item_choice = press[15] ? begin : press[16] ? end - 1 : std::clamp(item_choice + step, begin, end - 1);
                inventory_reveal();
                changed = true;
            } else if (press[7] && item_counts[item_choice].load(std::memory_order_relaxed) >= 0) {
                if (item_kinds[item_choice]) inventory_amount = true, changed = true;   // (an amount: Left and Right change it)
                else {   // (unlock or relock; (Triforce) a second press before the game took the first takes it back)
                    int was = cheat_action.load(std::memory_order_relaxed);
                    while (!cheat_action.compare_exchange_weak(was, debug_pending::toggle(was, item_choice), std::memory_order_relaxed)) {}
                    changed = true;
                }
            }
            if (item_choice != chosen) inventory_reveal();   // (a click on a card: its page)
        }
    } else if (open_now.load() && page == 6) {   // (Triforce) a name page: Game flags, Cutscenes, Scan amiibo
        if (mouse) names_mouse(ptr, mx, my, press, changed);
        names_press(press, tab_left, tab_right, changed);
    } else if (open_now.load() && page == 3) {   // the teleport list
        if (mouse) teleport_mouse(ptr, mx, my, press, changed);
        if (press[5]) page = 0, changed = true;   // (to the Debug tab, Teleport still selected)
        else if (press[7]) {
            cheat_action.store(1000 + teleport_choice);
            open_now = false, page = 0;   // (back to the game: the map change starts with an event)
            changed = true;
        } else if (tab_left || tab_right) {   // (the first map of the previous or next section)
            const int section = (teleport_section_of(teleport_choice) + kTeleportSections + (tab_left ? -1 : 1)) % kTeleportSections;
            teleport_choice = teleport_sections[section].first, teleport_follow = true;
            changed = true;
        } else {
            // (the cards as drawn, each section's in rows under its heading: Up and Down a row, the column kept; Left and Right the
            // previous and next card; Page Up and Down the rows that fit; Home and End the ends)
            const int rows = (press[2] - press[1]) + (press[14] - press[13]) * teleport_page_rows;
            const int was = teleport_choice;
            if (press[15]) teleport_choice = 0;
            else if (press[16]) teleport_choice = kTeleports - 1;
            else teleport_choice = std::clamp(teleport_step_rows(teleport_choice, rows) + (press[4] - press[3]), 0, kTeleports - 1);
            if (teleport_choice != was) teleport_follow = true, changed = true;
        }
    } else if (open_now.load() && page == kFilesPage) {   // (Triforce) the file select: the choice moves, confirm plays the file
        const int n = save_files.shown();
        if (mouse) {   // (a card chosen by a click, the button plays it; a right click goes back)
            const menu_hit::Hit hit = hits.at((float)mx, (float)my);
            if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kListLine && hit.index >= 0 && hit.index < n && files_wait < 0)
                changed |= files_choice != hit.index, files_choice = hit.index;
            else if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kButton && hit.index == 0) press[7] = true;
            if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
        }
        // (Back from the title's: the cursor on Save Select again; Play there, or the list gone: the game's list. From its row:
        // the System tab, the row still selected)
        const auto leave = [&](bool play) {
            if (files_at_title && !play && mods_list_fresh() && files_row_shown()) page = kModsRowPage, mods_row_sel = 1;
            else if (files_at_title) open_now = false, page = 0;
            else page = 0;
            changed = true;
        };
        if (files_wait >= 0) {}   // (asked of the host: its word comes at the next tick or two, menu_tick's top)
        else if (press[5] || !n) leave(false);
        else if (press[7]) {
            files_failed = false;
            if (save_files.choose(files_choice)) leave(true);   // (the file this run plays: on with it)
            else files_wait = files_choice, changed = true;
        } else changed |= save_file_rows::move(files_choice, press[2] - press[1], press[15], press[16], n);
    } else if (open_now.load() && page == kAchPage) {   // (Triforce) the Achievements page: nothing to set, the choice moves
        const int n = ach_list.shown();
        if (mouse) {   // (a card chosen by a click, the page arrows, the wheel a page; a right click goes back)
            const menu_hit::Hit hit = hits.at((float)mx, (float)my);
            if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kListLine) changed |= ach_view.choose(hit.index, n);
            else if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kButton && (hit.index == 2 || hit.index == 3))
                press[hit.index == 2 ? 13 : 14] = true;
            if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
            if (ptr.wheel) changed |= ach_view.turn(-ptr.wheel, n, ach_capacity);
        }
        if (press[5] || !n) page = 0, changed = true;   // (to the System tab, Achievements still selected)
        else changed |= ach_view.move(press[4] - press[3], press[2] - press[1], (press[14] - press[13]) + (tab_right ? 1 : 0) - (tab_left ? 1 : 0),
                                      press[15], press[16], n, ach_columns, ach_capacity);
    } else if (open_now.load() && page == kModsRowPage && mods_decide_ns) {   // ((Triforce, 11-19) the title's entry's Decide plays
        // (its sound with the press; no input meanwhile, as the game takes none during its own; the Mods screen at its end)
        if (!mods_list_fresh()) mods_decide_ns = 0, open_now = false, page = 0, changed = true;
        else if (prof_now() - mods_decide_ns >= mods_entry::kDecideNs) {
            mods_decide_ns = 0, mods_decided = true;
            page = kModsPage, mods_btn = 0, mods_follow = true, changed = true;
            mods_open_page();
        }
    } else if (open_now.load() && page == kModsRowPage) {   // (Triforce) the cursor on the entries under the game's list
        const bool quit_here = quit_entry_shown();
        const bool files_here = files_row_shown();   // ((Triforce) on the title Save Select is under Mods, as Quit is here)
        if (!quit_here && !files_here) mods_row_sel = 0;
        if (!quit_here) quit_gone();
        // ((Triforce, 11-19) the dialog takes input once its In has played, as the game's: what comes before is not kept)
        const bool quit_ready = quit_ask && focus_anim::window_ready(prof_now() - quit_open_ns);
        if (mouse) {   // (the cursor on an entry or a dialog button chooses it; a click is A)
            const menu_hit::Hit hit = hits.at((float)mx, (float)my);
            if (hit.part == menu_hit::kButton) {
                if (quit_ready && hit.index >= 10 && hit.index - 10 != quit_sel && (moved || ptr.pressed))
                    quit_sel = hit.index - 10, mods_sound(HOS_MENU_SOUND_SYS_CURSOR), changed = true;
                if (!quit_ask && hit.index < 2 && hit.index != mods_row_sel && (moved || ptr.pressed))
                    mods_row_sel = hit.index, mods_sound(HOS_MENU_SOUND_SYS_CURSOR), changed = true;
                // (with the dialog open, a click is A only on its own buttons: draw_quit_ask leaves no others, and a tick
                // before its first drawing still has the entries')
                if ((ptr.pressed & HOS_MOUSE_LEFT) && (!quit_ask || hit.index >= 10)) press[7] = true;
            } else if (moved && !quit_ask && !quit_closing()) {
                // ((Triforce, 11-19) the mouse moved up off the entries onto the game's list (the title's four entries above,
                // the System page's buttons, as wide): the game's cursor again, as Up from Mods (the host gives the mouse back
                // to the game's list, which takes the focus under it)
                const float* e = mods_entry_px;
                if (mx >= e[0] && mx <= e[2] && my < e[1] && my > e[1] - (quit_here ? 6 : 4) * e[4]) mods_row_sel = 0, press[1] = true;
            }
        }
        if (!mods_list_fresh()) {   // (the game's list went: its screen closed under it)
            open_now = false, page = 0, quit_gone(), mods_row_sel = 0, changed = true;
        } else if (quit_ask && !quit_ready) {   // (its In playing: drawn each frame, no input)
            press[1] = press[2] = press[5] = press[0] = press[6] = press[7] = false, tab_left = tab_right = false;
        } else if (quit_ask) {   // (Quit's dialog: Up and Down its buttons, A chooses, B is Cancel)
            if (press[1] && quit_sel > 0) quit_sel--, mods_sound(HOS_MENU_SOUND_SYS_CURSOR), changed = true;
            else if (press[2] && quit_sel < 2) quit_sel++, mods_sound(HOS_MENU_SOUND_SYS_CURSOR), changed = true;
            else if (press[7]) {
                mods_sound(quit_sel == 2 ? HOS_MENU_SOUND_CANCEL : HOS_MENU_SOUND_SYS_DECIDE);
                if (quit_sel == 2) quit_cancel();
                else end_game(quit_sel == 1), quit_gone(), quit_ended = true, open_now = false, page = 0;
                changed = true;
            } else if (press[5] || press[0] || press[6]) quit_cancel(), mods_sound(HOS_MENU_SOUND_CANCEL), changed = true;
            press[1] = press[2] = press[5] = press[0] = press[6] = false, tab_left = tab_right = false;
        } else if (press[7] && files_here && mods_row_sel == 1) {   // ((Triforce) A on Save Select: the file select)
            files_open(true), mods_sound(HOS_MENU_SOUND_SYS_DECIDE), changed = true;
        } else if (press[2] && files_here && mods_row_sel == 0) {   // ((Triforce) Down from the title's Mods: Save Select)
            mods_row_sel = 1, mods_sound(HOS_MENU_SOUND_SYS_CURSOR), changed = true;
        } else if (press[7]) {   // (A: Mods opens; on Quit its dialog)
            if (mods_row_sel == 1) quit_open(), mods_sound(HOS_MENU_SOUND_SYS_DECIDE), changed = true;
            else if (mods_title_list()) mods_decide_ns = prof_now(), mods_sound(HOS_MENU_SOUND_SYS_DECIDE), changed = true;   // (its Decide first)
            else {
                page = kModsPage, mods_btn = 0, mods_follow = true, changed = true;
                mods_open_page();
            }
        } else if (press[2] && quit_here && mods_row_sel == 0) {   // (Down from Mods: Quit)
            mods_row_sel = 1, mods_sound(HOS_MENU_SOUND_SYS_CURSOR), changed = true;
        } else if (press[1] && mods_row_sel == 1) {   // (Up from Quit: Mods)
            mods_row_sel = 0, mods_sound(HOS_MENU_SOUND_SYS_CURSOR), changed = true;
        } else if (press[1] || press[5] || press[0] || press[6] || tab_left || tab_right) {   // (Up from Mods, or Back: the game's cursor again)
            open_now = false, page = 0, mods_row_sel = 0, changed = true;
        }
    } else if (open_now.load() && page == kModsPage) {   // (Triforce) the Mods page
        // ((Triforce, 11-20) it takes input once its In has played, as the game's screens and Quit's dialog: what comes
        // before is not kept)
        if (mods_screen.ready(prof_now())) mods_tick(press, tab_left, tab_right, mouse, moved, ptr, mx, my, changed);
    } else if (open_now.load()) {
        if (mouse) {   // (the mouse: see the top of this file)
            const menu_hit::Hit hit = hits.at((float)mx, (float)my);
            const int ht = hit.part == menu_hit::kTab ? (hit.index == kGameTab ? -1 : hit.index) : hit.part == menu_hit::kTabPrev ? TAB_COUNT
                         : hit.part == menu_hit::kTabNext ? TAB_COUNT + 1 : -1;
            if (ht != hover_tab) hover_tab = ht, changed = true;
            int& sel = tab_selected[cur_tab];
            const bool on_row = hit.part == menu_hit::kRow || hit.part == menu_hit::kSlider;
            if (drag_row >= 0) {   // (a slider held: it follows the cursor's x until let go)
                Row& d = rows[tab_row_to_global(cur_tab, drag_row)];
                if (!(ptr.held & HOS_MOUSE_LEFT) || !d.value) {
                    drag_row = -1;
                    save();
                } else {
                    const int permille = hits.drag((float)mx, drag_row);
                    const int v = permille < 0 ? *d.value : menu_hit::slider_value(permille, d.lo, d.hi, d.step);
                    if (v != *d.value) set_row(d, v, v > *d.value ? 1 : -1, false), changed = true;
                }
            } else if (on_row && (moved || ptr.pressed) && hit.index != sel) {
                sel = hit.index, changed = true;
            }
            if ((ptr.pressed & HOS_MOUSE_LEFT) && drag_row < 0) {
                if (hit.part == menu_hit::kTabPrev) tab_left = true;
                else if (hit.part == menu_hit::kTabNext) tab_right = true;
                else if (hit.part == menu_hit::kTab && hit.index == kGameTab) open_now = false, changed = true;   // (the game's own tab)
                else if (hit.part == menu_hit::kTab && hit.index == kModsTab) {   // (Triforce: the Mods page)
                    page = kModsPage, mods_btn = 0, mods_follow = true, cur_tab = TAB_SYSTEM, changed = true;
                    mods_open_page();
                }
                else if (hit.part == menu_hit::kTab && hit.index != cur_tab && hit.index < tabs_shown()) cur_tab = hit.index, changed = true;
                else if (hit.part == menu_hit::kSlider) {
                    Row& d = rows[tab_row_to_global(cur_tab, hit.index)];
                    drag_row = hit.index;
                    const int v = menu_hit::slider_value(hit.permille, d.lo, d.hi, d.step);
                    if (v != *d.value) set_row(d, v, v > *d.value ? 1 : -1, false);
                    changed = true;
                } else if (hit.part == menu_hit::kRow) {
                    Row& d = rows[tab_row_to_global(cur_tab, hit.index)];
                    if (!d.value && d.cheat >= 0 && (cheat_chooses(d.cheat) || age_shown(d.cheat) || d.cheat <= 1 || d.cheat == 7) &&
                        hit.side != 0)
                        press[hit.side < 0 ? 3 : 4] = true;   // (a tool's choice: its halves as Left and Right)
                    else if (!d.value && hit.halves && mod_cheat_slot(d.name) >= 0)
                        press[hit.side < 0 ? 3 : 4] = true;   // ((Triforce) a mod's cheat: On, its left half, as Left; Off as Right)
                    else if (!d.value) press[7] = true;   // (a page, a tool: as Enter)
                    else if (hit.halves && d.hi - d.lo == d.step) {   // ((Triforce) a toggle's half: that value, as the game's own
                        // toggles are picked; the left half is the high value (On), the right the low. The one it has: nothing)
                        if (*d.value != (hit.side < 0 ? d.hi : d.lo)) press[4] = true;
                    }
                    else if (d.hi - d.lo == d.step || hit.side >= 0) press[4] = true;   // (a toggle flips; the right half, or the name, as Right)
                    else press[3] = true;                                               // (the left half as Left)
                }
            }
            if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;   // (as Esc)
            // (the wheel scrolls the rows, wherever the cursor is; it never changes a value, the selection or the tab: the
            // values change by a click on their arrows or halves, a slider's drag, Left and Right, A and Enter)
            if (ptr.wheel && drag_row < 0) wheel_rows[cur_tab] += ptr.wheel, changed = true;
        }
        {   // ((Triforce) the Output width and height rows typed into (size_edit): before Back, which ends the typing first)
            const int tc = tab_row_count(cur_tab), si = std::min(tab_selected[cur_tab], tc - 1);
            Row* sr = tc > 0 && si >= 0 ? &rows[tab_row_to_global(cur_tab, si)] : nullptr;
            const bool size_row = sr && (sr->value == &opts.output_width || sr->value == &opts.output_height) && !row_fixed(sr->value) &&
                                  output_choice(opts.output_res) == OUTPUT_CUSTOM;
            if (!size_row || (size_edit && size_edit != sr->value)) {
                if (size_edit) changed = true;
                size_edit = nullptr, size_text.clear();
            }
            std::vector<int> typed;
            {
                std::lock_guard<std::mutex> g(mods_typed_mu);
                typed.swap(size_typed);
            }
            for (int cp : size_row ? typed : std::vector<int>()) {
                if (cp >= '0' && cp <= '9') {
                    if (!size_edit) size_edit = sr->value, size_text.clear();
                    if (size_text.size() < 4) size_text += (char)cp;
                    changed = true;
                } else if (cp == 8 && size_edit) {
                    if (!size_text.empty()) size_text.pop_back();
                    changed = true;
                } else if (cp == 127 && size_edit) {
                    size_text.clear(), changed = true;
                }
            }
            if (size_edit) {
                if (press[7] && !size_text.empty()) {   // (Enter: the number, on the row's steps and in its range)
                    int v = atoi(size_text.c_str());
                    v = std::min(std::max(v / sr->step * sr->step, sr->lo), sr->hi);
                    if (v != *sr->value) set_row(*sr, v, v > *sr->value ? 1 : -1);
                    size_edit = nullptr, size_text.clear(), changed = true;
                } else if (press[7] || press[5]) {   // (Enter with nothing typed, or Esc: as it was)
                    size_edit = nullptr, size_text.clear(), changed = true;
                }
                press[1] = press[2] = press[3] = press[4] = press[5] = press[7] = press[8] = press[9] = false;
                tab_left = tab_right = false;
            }
            size_text_wanted.store(size_row, std::memory_order_relaxed);
        }
        if (press[5] && sub_page(cur_tab)) cur_tab = page_parent(cur_tab), press[5] = false, changed = true;   // (back)
        if (press[5] && pending) pending = nullptr, changed = true;   // (a Restart or Quit waiting for its second press: cancelled)
        else if (press[5] && sub_page(cur_tab)) cur_tab = page_parent(cur_tab), press[5] = false, changed = true;   // (back)
        else if (press[5] && restart_ask()) page = 5, ask_sel = 0, changed = true;   // (the restart question first)
        else if (press[5]) open_now = false;
        // (the tabs: LB and RB, Q and E, or Tab; from the Motion page, as from Controls)
        if ((tab_left || tab_right) && sub_page(cur_tab)) cur_tab = page_parent(cur_tab);
        if (tab_left || tab_right) {   // (inside the game's Options: past our first or last tab is the game's own again; Mods
                                       // after System: tab_move)
            tab_move(tab_left ? -1 : 1);
            changed = true;
        }
        const int tab_count = tab_row_count(cur_tab);
        int& selected = tab_selected[cur_tab];
        if (selected >= tab_count) selected = tab_count - 1;   // (a row gone since: the debug tools with them turned off)
        auto heading_at = [&](int k) { return rows[tab_row_to_global(cur_tab, k)].heading; };   // (stepped over)
        // ((Triforce, options_version 7) every tab but Debug starts with a group's heading: the first row under it)
        for (int k = 0; k < tab_count && heading_at(selected); k++) selected = (selected + 1) % tab_count;
        if (cur_tab == TAB_DEBUG && (press[1] || press[2])) {   // (the Debug tab: in its layout's order, debug_rows)
            selected = debug_step(selected, press[2] ? 1 : -1);
            changed = true;
        } else {
            if (press[1]) {
                do selected = (selected + tab_count - 1) % tab_count;
                while (heading_at(selected));
                changed = true;
            }
            if (press[2]) {
                do selected = (selected + 1) % tab_count;
                while (heading_at(selected));
                changed = true;
            }
        }
        Row& r = rows[tab_row_to_global(cur_tab, selected)];
        if (pending) pending = nullptr, changed = true;
        if (r.cheat >= 0) cheat_press(r.cheat, press, changed);   // (a debug tool: on the Debug tab itself)
        // (Triforce: a mod's cheat: Left On, Right Off, confirm flips; the host takes the change, menu_take_mod_cheat. Before the
        // rows that act by their name or open a page: a cheat's name is the file's)
        else if (mod_cheat_slot(r.name) >= 0) changed |= mod_cheats.press(mod_cheat_slot(r.name), press[3], press[4], press[7]);
        else if (press[7] && share_row(r)) share_press(share_row(r)), press[7] = false, changed = true;   // (Triforce: the host does it)
        else if (press[7] && is_ach_row(r)) page = kAchPage, ach_view.reveal(ach_capacity), press[7] = false, changed = true;
        else if (press[7] && r.name == kUseWindowSize) {
            use_window_size(dev.swap_extent.width, dev.swap_extent.height);
            press[7] = false;
            changed = true;
        }
        else if (press[7] && is_files_row(r)) files_open(false), press[7] = false, changed = true;
        else if (press[7] && is_motion_row(r)) cur_tab = TAB_MOTION, tab_selected[TAB_MOTION] = 0, press[7] = false, changed = true;
        else if (press[7] && row_page(r) >= 0) cur_tab = row_page(r), tab_selected[cur_tab] = 0, press[7] = false, changed = true;
        else if (press[7] && r.name == kNfcTag) names_open(kNamesAmiibo), press[7] = false, changed = true;   // ((Triforce) 11-24)
        else if (press[7] && reshade_menu::act(r.name)) press[7] = false, changed = true;   // ((Triforce) 11-24: Compare, Rescan)
        // ((Triforce) 11-24) the Test microphone row: on and off again (mic_test_tick tells the host)
        else if (press[7] && r.name == kTestMic) {
            if (opts.mic != 0 && host && host->mic_test) mic_testing = !mic_testing;
            press[7] = false, changed = true;
        }
        // ((Triforce, 11-22, N64 Classic) Remembered settings opens its page; the page's two actions act on a press)
        else if (press[7] && is_n64_page_row(r)) cur_tab = TAB_N64, tab_selected[TAB_N64] = 0, press[7] = false, changed = true;
        // (its press kept: the sound's confirm, kDecide. The row has no value, and nothing after this takes press[7] for it)
        else if (press[7] && n64_action(r)) n64_act(n64_action(r)), changed = true;
        // ((Triforce, 11-24) Simulated turf opens its page; the page's Reset current area acts on a press (its press kept, as above)
        else if (press[7] && is_sim_turf_page_row(r)) cur_tab = TAB_SIM_TURF, tab_selected[TAB_SIM_TURF] = 0, press[7] = false, changed = true;
        else if (press[7] && is_sim_turf_reset_row(r)) sim_turf_reset(), changed = true;
        else if (press[7] && !r.value && can_bind()) page = 1, csel = 0, ccol = 0, changed = true;
        if ((press[3] || press[4] || press[7]) && r.value) {   // (Enter, or A, as Right)
            if (press[7]) press[4] = true;
            set_row(r, *r.value + (press[4] ? r.step : -r.step), press[4] ? 1 : -1);
            changed = true;
        }
        const int64_t now = prof_now();
        if (changed) {   // (a new row or value: its name from the start, after a rest)
            marquee_pos = 0, marquee_next = now + kMarqueeRest;
        } else if (marquee_max > 0 && now >= marquee_next) {
            if (marquee_pos >= marquee_max) marquee_pos = 0, marquee_next = now + kMarqueeRest;   // (back to the start)
            else if (++marquee_pos >= marquee_max) marquee_next = now + kMarqueeRest;            // (rest at the end)
            else marquee_next = now + kMarqueeStep;
            changed = true;
        }
    }
    {   // (Triforce) the options' own sounds, the game's interface sounds: what this tick's input did to the options names one
        // sound at most (menu_sound_events.h sound_of), which waits for the host's sound thread (menu_take_sound). None is
        // asked for while the Menu sounds row is at 0. A save row and the Motion row take their press for themselves
        // (press[7] is false again by now): the save rows' is told from the time their answer is waited for, which a press
        // moves on (the host's answer meanwhile sets it back to 0: no press)
        menu_sound::Input in;
        in.toggle = press[0] || press[6], in.back = press[5];
        in.confirm = press[7] || share_busy_until.load(std::memory_order_relaxed) > sound_share;
        in.tab_left = tab_left, in.tab_right = tab_right, in.left = press[3], in.right = press[4];
        in.move = press[1] || press[2] || press[13] || press[14] || press[15] || press[16], in.clear = press[8] || press[9];
        in.click = (ptr.pressed & HOS_MOUSE_LEFT) != 0, in.drag = drag_row >= 0;
        // ((Triforce) 11-17, his "it makes a different noise from the regular menu sounds") The Mods entry under the game's list
        // sounds as that list does, not as the options: A the system menu's "decide" (the Mods screen opens), the cursor going
        // back to the game's list its cursor. Coming onto the entry is told where the host's word comes (menu_tick's top)
        const menu_sound::State after = sound_state();
        const bool row_before = sound_before.open && sound_before.page == kModsRowPage;
        if (row_before) {
            if (after.open && after.page == kModsPage) { if (!mods_decided) mods_sound(HOS_MENU_SOUND_SYS_DECIDE); }   // (the title's: at the press)
            else if (!after.open && !quit_ended) mods_sound(HOS_MENU_SOUND_SYS_CURSOR);   // (not after Quit Game or Restart Game's decide)
        } else if (sound_before.open || !after.open || after.page != kModsRowPage) {
            if (opts.menu_sounds > 0) sound_queue.put(menu_sound::sound_of(sound_before, sound_state(), in), prof_now());
        }
        mods_decided = false;
        quit_ended = false;
        if (!open_now.load() || page != kModsRowPage) mods_decide_ns = 0;   // (a Decide cut short: the menu shut by its keys)
    }
    names_tick();   // ((Triforce) the name pages: their lists, the flags asked for, what the game's side said)
    // (Triforce) the Salesman's thread draws only while the Mods page shows him
    salesman::show(open_now.load() && page == kModsPage && mods::available() && mods::accepted(), salesman_w, salesman_h);
    if (open_now.load() && page == kModsPage) changed = true;   // (he moves: drawn again)
    mods_screen.step(prof_now(), open_now.load() && page == kModsPage);   // ((Triforce, 11-20) its In from the tick it came at)
    {   // (hookshot) the window lets the mouse go while the menu is open, and takes it back after (host/display.c)
        static bool told = false;
        const bool now_open = open_now.load();
        if (!now_open) {
            if (drag_row >= 0) save();   // (a slider let go off the window: kept now)
            sim_turf_flush();   // ((Triforce, 11-24) the Simulated turf page's file: written now, if it waits)
            if (!in_game_options) hover_tab = -1;   // ((Triforce) on the game's own tab, the tabs' own: above)
            drag_row = -1, mouse_read = false;
            pending = nullptr;
        }
        if (now_open != told && app_window()) {
            told = now_open;
            PostMessageA(app_window(), WM_APP + 8, (WPARAM)now_open, 0);
        }
    }
    if (opts.show_fps != 2) perf_view.full = false, perf_view.have = false;   // (Triforce: not on Full: the next Full starts its frame times anew)
    {   // (Triforce: the machine's numbers, sampled on a thread of their own while the row is on Full and a GPU is chosen:
        // perf_machine.cpp. Here only its start and its stop)
        static bool machine = false;
        const bool want = opts.show_fps == 2 && dev.props.deviceName[0];
        if (want != machine) {
            machine = want;
            if (want) perf_machine_start();
            else perf_machine::stop();
        }
    }
    if (opts.show_fps) {
        static int64_t next = 0, last_game = 0, last_shown = 0;
        const int64_t now = prof_now();
        double shown = 0, game = 0;
        if (fps_take(now, shown_frames.load(), game_frames.load(), &next, &last_shown, &last_game, &shown, &game)) {
            snprintf(fps_text, sizeof fps_text, "%.0f", shown);
            // ((Triforce, 11-16) the game's own rate beside it with DLSS frame generation too, while it generates)
            if (opts.framegen >= 1 || mkwvk::dlssg::multiplier() > 1) snprintf(fps_sub, sizeof fps_sub, "%.0f", game);
            else fps_sub[0] = 0;
            if (opts.show_fps == 2) perf_sample(shown, game);   // (Triforce: the Full overlay's lines)
            if (fps_levels::shows_time(opts.show_fps)) fps_detail_sample();   // ((Triforce) the levels between On and Full
        }
    }
}

/// (Triforce, 11-19) Benchmark mode's panel (host/hos_bench.c, HOS_BENCHMARK; MkwVkHost.bench): what the run does, drawn over
/// the game in the launcher's look, top left, clear of the middle: near-black at 85% with a thin gold edge, the title in gold,
/// the scene and its place in the run, the live frame rate big with the scene's 1% low beside it, the newest frame times as
/// a line (the 60 fps time marked), the whole run's progress as a gold bar along the panel's foot and how to stop it.
/// While the start loads the save, while a teleport loads the next place and at the end it says so in the scene's line
bool bench_now(MkwVkBench* b) { return host && host->bench && host->bench(b) && b->phase != MKWVK_BENCH_OFF; }
void draw_bench(ui::Ctx& c, const MkwVkBench& b) {
    ImFont* title_f = c.f.heading ? c.f.heading : c.f.strong;
    ImFont* body = c.f.body ? c.f.body : c.f.strong;
    ImFont* strong = c.f.strong ? c.f.strong : body;
    ImFont* digits = c.f.number ? c.f.number : strong;
    if (!body || !title_f) return;
    const float k = std::max(0.6f, c.h / 1080.0f);
    const ImU32 gold = ui::rgba(224, 178, 62), ink = ui::rgba(243, 234, 213), soft = ui::rgba(243, 234, 213, 165),
                faint = ui::rgba(243, 234, 213, 110), bg = ui::rgba(10, 9, 8, 217);
    const float m = std::floor(28 * k), pad = std::floor(22 * k), pw = std::floor(440 * k);
    const float t_px = 28 * k, l_px = 21 * k, big = 64 * k, unit_px = 22 * k, small = 15.5f * k, low_px = 30 * k;
    const float graph_h = 64 * k, bar_h = std::max(3.0f, std::floor(5 * k));
    const float x0 = m + pad, x1 = m + pw - pad;
    // (the heights first: the panel keeps one size through the run)
    const float h_title = t_px * 1.15f, h_line = l_px * 1.3f, h_big = big * 1.05f;
    const float ph = std::ceil(pad + h_title + 6 * k + h_line + 14 * k + h_big + 12 * k + graph_h + 16 * k + bar_h + 12 * k + small * 1.2f + pad);
    const ImVec2 a(m, m), z(m + pw, m + ph);
    c.d->AddRectFilled(a, z, bg, 6 * k);
    c.d->AddRect(a, z, ui::alpha(gold, 0.85f), 6 * k, 0, std::max(1.0f, 1.25f * k));
    float y = m + pad;
    c.d->AddText(title_f, t_px, ImVec2(x0, y), gold, "Triforce benchmark");
    y += h_title + 6 * k;
    char line[160];
    switch (b.phase) {
    case MKWVK_BENCH_BOOT: snprintf(line, sizeof line, "Loading your newest save"); break;
    case MKWVK_BENCH_TRAVEL: snprintf(line, sizeof line, "Going to %s", b.name); break;
    case MKWVK_BENCH_DONE: snprintf(line, sizeof line, "Finished \xC2\xB7 the launcher has your results"); break;
    case MKWVK_BENCH_STOPPED: snprintf(line, sizeof line, "Stopped \xC2\xB7 the launcher has what was measured"); break;
    case MKWVK_BENCH_FAILED: snprintf(line, sizeof line, "%s", b.line[0] ? b.line : "The benchmark could not finish"); break;
    default: snprintf(line, sizeof line, "Scene %d of %d \xC2\xB7 %s", b.scene, b.scenes, b.name); break;
    }
    c.d->PushClipRect(ImVec2(x0, y), ImVec2(x1, y + h_line), true);   // (a long name or reason stays inside the panel)
    c.d->AddText(body, l_px, ImVec2(x0, y), b.phase == MKWVK_BENCH_FAILED ? ui::rgba(236, 120, 96) : ink, line);
    c.d->PopClipRect();
    y += h_line + 14 * k;
    {   // (the live rate, big; the scene's 1% low at the right. Finished: the whole run's average and its lowest 1% low)
        const bool live = b.phase == MKWVK_BENCH_SETTLE || b.phase == MKWVK_BENCH_MEASURE || b.phase == MKWVK_BENCH_DONE;
        char fps[16], low[16];
        snprintf(fps, sizeof fps, live && b.fps > 0 ? "%.0f" : "--", b.fps);
        snprintf(low, sizeof low, live && b.low1 > 0 ? "%.0f" : "--", b.low1);
        const ImVec2 fs = ui::size_of(digits, big, fps);
        c.d->AddText(digits, big, ImVec2(x0, y), live ? ink : faint, fps);
        c.d->AddText(strong, unit_px, ImVec2(x0 + fs.x + 10 * k, y + big * 0.98f - unit_px * 1.25f), gold, "fps");
        const ImVec2 ls = ui::size_of(strong, low_px, low), ll = ui::size_of(body, small, "1% low");
        c.d->AddText(body, small, ImVec2(x1 - ll.x, y + 4 * k), soft, "1% low");
        c.d->AddText(strong, low_px, ImVec2(x1 - ls.x, y + 4 * k + small * 1.25f), live ? ink : faint, low);
    }
    y += h_big + 12 * k;
    {   // (the frame times: the newest at the right, 0 at the bottom, the top 33 ms or the longest shown; the 60 fps time marked)
        const ImVec2 g0(x0, y), g1(x1, y + graph_h);
        c.d->AddRectFilled(g0, g1, ui::rgba(0, 0, 0, 110), 3 * k);
        const int n = std::min<int>(b.graph_n, MKWVK_BENCH_GRAPH);
        float most = 33.4f;
        for (int i = 0; i < n; i++) most = std::max(most, std::min(b.graph_ms[i], 250.0f));
        const float top = g0.y + 4 * k, bot = g1.y - 3 * k;
        const float y60 = bot - 16.667f / most * (bot - top);
        c.d->AddLine(ImVec2(g0.x, y60), ImVec2(g1.x, y60), ui::rgba(243, 234, 213, 40), 1.0f);
        if (n >= 2) {
            static ImVec2 pts[MKWVK_BENCH_GRAPH];
            for (int i = 0; i < n; i++) {
                const float t = std::min(b.graph_ms[i], most);
                pts[i] = ImVec2(g1.x - (g1.x - g0.x) * (float)(n - 1 - i) / (MKWVK_BENCH_GRAPH - 1), bot - t / most * (bot - top));
            }
            const bool live = b.phase == MKWVK_BENCH_SETTLE || b.phase == MKWVK_BENCH_MEASURE;
            c.d->AddPolyline(pts, n, live ? gold : ui::alpha(gold, 0.4f), ImDrawFlags_None, std::max(1.0f, 1.5f * k));
        }
    }
    y += graph_h + 16 * k;
    {   // (the whole run's progress)
        const float p = std::clamp(b.progress, 0.0f, 1.0f);
        c.d->AddRectFilled(ImVec2(x0, y), ImVec2(x1, y + bar_h), ui::rgba(243, 234, 213, 36), bar_h * 0.5f);
        if (p > 0) c.d->AddRectFilled(ImVec2(x0, y), ImVec2(x0 + (x1 - x0) * p, y + bar_h), gold, bar_h * 0.5f);
    }
    y += bar_h + 12 * k;
    if (b.phase < MKWVK_BENCH_DONE) c.d->AddText(body, small, ImVec2(x0, y), faint, "Esc stops the benchmark");
}

namespace {
/// (Triforce) What the overlays show at a present, asked once (menu_tv_layer's, or menu_record's)
struct Showing {
    bool start = false, fps = false, open = false, note = false, game_tab = false, mods_row = false, bench_on = false;
    bool earned = false;   // ((Triforce, 11-23) an achievement's notice (draw_ach_notice), flat over the TV as the notice
};
MkwVkBench overlay_bench;   // ((Triforce) benchmark mode: its panel over everything else)
Showing showing_now() {
    Showing s;
    s.start = startup_on.load(std::memory_order_acquire);
    s.bench_on = bench_now(&overlay_bench);
    s.fps = opts.show_fps && !s.start;   // (no game frames yet: not "0 FPS" over the start-up screen)
    s.open = open_now.load(std::memory_order_relaxed);
    s.note = !s.open && !s.start && notice_text[0] && prof_now() < notice_until;
    // (Triforce: the game's own Options screen is up and none of our tabs: its header's tabs alone)
    const int64_t game_seen = game_options_ns.load(std::memory_order_relaxed);
    s.game_tab = !s.open && !s.start && embed_allowed() && game_seen && prof_now() - game_seen < 250000000LL && embed_since;
    s.mods_row = !s.open && !s.start && (mods_list_fresh() || mods_title_fading());   // ((Triforce) the Mods entry under the game's list)
    perf_rect[2] = 0;   // ((Triforce VR) drawn again, or not this frame)
    s.earned = !s.start && ach_notice >= 0 && prof_now() - ach_notice_at < kAchNoticeMs * 1000000;   // ((Triforce) an achievement's notice)
    return s;
}
/// The overlays of a w x h window, after ui::begin. ((Triforce, 11-22, N64 Classic) under: the list the options' own screens
/// go into (the open menu, the game tab's header, the Mods entry; the Full panel while it is under them), for N64 Classic's TV
/// to take in (menu_tv_layer); null: one list for all, as before. The FPS counter, the notice and benchmark mode's panel stay
/// over the window, flat: a counter in a corner the curve takes away is no counter)
void draw_overlays(uint32_t w, uint32_t h, const Showing& s, ImDrawList* under) {
    {   // (the easing's step: the time since the last drawing, a quarter of the way in 1/60 s)
        static int64_t last = 0;
        const int64_t now = prof_now();
        ease_step = last ? std::min(1.0f, (float)((now - last) / 1e9) * 15.0f) : 1.0f;
        last = now;
        ease_live = true;
    }
    ui::Ctx c = menu_ctx(w, h);
    prebake(c);   // (the menu's glyphs at this size, before it opens: no hitch then)
    if (s.start) {   // (under the menu, in the overlay's own fonts)
        ui::Ctx sc = ui_ctx(w, h);
        draw_startup(sc);
    }
    ui::Ctx m = c;   // (the options' own screens)
    if (under) m.d = under;
    // ((Triforce) Full: NX2navi's panel alone, no counter beside it (its perf_draw), and under the options or the game tab's
    // header while they show (its BringWindowToDisplayBack): the open menu covers it)
    const bool full = s.fps && opts.show_fps == 2;
    // ((Triforce, 11-19) the Mods entry's page: the panel over Quit's dialog and its dim, as over the game's own dialogs, which
    // the game draws under every overlay. The lab's "its dim covers the left part of the stats overlay")
    const bool over_row = s.open && page == kModsRowPage;
    if (s.open) draw_menu(m, full && !over_row);
    else {
        if (full) draw_perf(s.game_tab || s.mods_row ? m : c);   // (under the header or the entry: in their list)
        if (s.game_tab) draw_game_tab(m);
        else if (s.mods_row) draw_mods_row_shut(m);
    }
    if (full && over_row) draw_perf(c);
    if (s.fps && !full) draw_fps(c, (s.open && page != kModsRowPage) || s.game_tab);   // ((Triforce) the Mods entry: the counter stays where the game list has it)
    if (s.note) draw_notice(c);
    if (s.earned) draw_ach_notice(c);   // ((Triforce, 11-23) flat on top, as the notice
    if (s.bench_on) {   // ((Triforce) benchmark mode's panel, in the overlay's own fonts, over the rest
        ui::Ctx bc = ui_ctx(w, h);
        draw_bench(bc, overlay_bench);
    }
}
// ((Triforce, 11-22, N64 Classic) this present's overlays were drawn by menu_tv_layer: menu_record draws what is left of them
// (tv_drawn); or it asked what shows and drew nothing: menu_record takes its answer, so benchmark mode is asked once a present)
bool tv_drawn = false;
bool tv_layer = false;   // (...and the options are in its layer: the mouse goes through the TV's curve to them)
bool tv_asked = false;
Showing tv_showing;
} // namespace

VkImageView menu_tv_layer(VkCommandBuffer cmd) {
    tv_drawn = tv_layer = tv_asked = false;
    static const bool on = !(getenv("RX_VK_N64_TV_MENU") && *getenv("RX_VK_N64_TV_MENU") && atoi(getenv("RX_VK_N64_TV_MENU")) == 0);
    uint32_t x = 0, y = 0, pw = 0, ph = 0, w = 0, h = 0;
    if (!on || !n64_screen_place(&x, &y, &pw, &ph, &w, &h)) return VK_NULL_HANDLE;   // (a shot's window pass: no window under it)
    tv_showing = showing_now(), tv_asked = true;
    const Showing& s = tv_showing;
    // (none of the options' own screens; or a bug capture waits for this frame's picture, which is taken before the
    // overlays; or an HDR10 window, whose overlays' pictures are made in its codes (vk_imgui.cpp pixels), not the SDR
    // picture's the TV draws in: menu_record then, as before)
    if (s.start || !(s.open || s.game_tab || s.mods_row) || bugshot_state() == 1 || dev.hdr || !ui::begin(w, h))
        return VK_NULL_HANDLE;
    draw_overlays(w, h, s, ImGui::GetBackgroundDrawList());
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (Dear ImGui records into cmd directly, its backend through its own pointers: what this thread recorded through vk_work.h reaches cmd first)
    const VkImageView layer = ui::record_layer(cmd, x, y, pw, ph);
    tv_drawn = true, tv_layer = layer != VK_NULL_HANDLE, tv_asked = false;
    static bool told = false;
    if (layer && !told)
        told = true, logf("menu: the options' own screens drawn under N64 Classic's TV, in a layer of the picture's place (%ux%u at "
                          "%u,%u of %ux%u); the FPS counter over it (RX_VK_N64_TV_MENU=0: all over the TV, as before)", pw, ph, x, y, w, h);
    return layer;
}

void menu_record(VkCommandBuffer cmd, uint32_t index, uint32_t w, uint32_t h) {
    if (tv_drawn) {   // ((Triforce, 11-22, N64 Classic) the options went under the TV this present: the rest over the window
        tv_drawn = false;
        options_under_tv = tv_layer;   // (no layer made: they went over the window, flat, as before)
        bugshot_record(cmd, index, w, h);   // (a copy under way goes on; none was waiting for this frame: menu_tv_layer)
        ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);
        ui::record_rest(cmd, index, w, h);
        return;
    }
    options_under_tv = false;
    const Showing s = tv_asked ? tv_showing : showing_now();
    tv_asked = false;
    if (!s.start) bugshot_record(cmd, index, w, h);   // (Triforce: a bug capture's picture of this frame, before anything is drawn over it)
    if (!s.start && !s.fps && !s.open && !s.note && !s.game_tab && !s.mods_row && !s.bench_on && !s.earned) {   // (nothing shows: no ImGui frame, no render pass)
        // (but a new window size or Menu size since the last bake: one frame with nothing drawn that bakes the menu's glyphs
        // and measures its page for the new size, so the next open has no hitch whatever was resized while nothing showed)
        if (prebake_needed(w, h) && ui::begin(w, h)) {
            ui::Ctx c = menu_ctx(w, h);
            prebake(c);
            ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (Dear ImGui records into cmd directly, its backend through its own pointers: what this thread recorded through vk_work.h reaches cmd first)
            ui::record(cmd, index, w, h);
            return;
        }
        ui::idle();
        return;
    }
    if (!ui::begin(w, h)) return;
    draw_overlays(w, h, s, nullptr);
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (Dear ImGui records into cmd directly, its backend through its own pointers: what this thread recorded through vk_work.h reaches cmd first)
    ui::record(cmd, index, w, h);
}

void menu_record_image(VkCommandBuffer cmd, VkImage image, VkImageView view, uint32_t w, uint32_t h) {
    const bool open = open_now.load(std::memory_order_relaxed);
    const bool fps = opts.show_fps && !startup_on.load(std::memory_order_acquire);
    const bool note = !open && notice_text[0] && prof_now() < notice_until;
    const bool game_tab = !open && game_options_shown() && embed_since;
    const bool mods_row = !open && (mods_list_fresh() || mods_title_fading());
    static MkwVkBench bench;   // ((Triforce) benchmark mode's panel, in the shots too)
    const bool bench_on = bench_now(&bench);
    const bool earned = ach_notice >= 0 && prof_now() - ach_notice_at < kAchNoticeMs * 1000000;   // ((Triforce) as menu_record)
    if (!open && !fps && !note && !game_tab && !mods_row && !bench_on && !earned) return;
    if (!ui::begin(w, h)) return;
    // ((Triforce) a still: with no window's frames stepping the easing (menu_record), the lists stand where the selection asks.
    // Before, a headless shot, and tests/ui_preview.cpp's pictures, showed every list at its top whatever was selected)
    if (!ease_live) ease_step = 1.0f;
    ui::Ctx c = menu_ctx(w, h);
    const bool full = fps && opts.show_fps == 2;   // ((Triforce) as menu_record: the panel alone, under the menu)
    const bool over_row = open && page == kModsRowPage;   // ((Triforce, 11-19) over Quit's dialog: as menu_record)
    if (open) draw_menu(c, full && !over_row);
    else {
        if (full) draw_perf(c);
        if (game_tab) draw_game_tab(c);
        else if (mods_row) draw_mods_row_shut(c);
    }
    if (full && over_row) draw_perf(c);
    if (fps && !full) draw_fps(c, (open && page != kModsRowPage) || game_tab);   // ((Triforce) the Mods entry: the counter stays where the game list has it)
    if (note) draw_notice(c);
    if (earned) draw_ach_notice(c);
    if (bench_on) {
        ui::Ctx bc = ui_ctx(w, h);
        draw_bench(bc, bench);
    }
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (Dear ImGui records into cmd directly, its backend through its own pointers: what this thread recorded through vk_work.h reaches cmd first)
    ui::record_to(cmd, image, view, w, h);
}

// (Triforce VR) the item panel's places, layout units of the game's 3840 x 2160 grid: the HUD's item box, its middle from
// the top right corner (measured on a 1280 x 720 shot), the grid's step and its columns
constexpr float kItemFromRight = 294, kItemFromTop = 258, kItemBox = 250, kItemStep = 270;
constexpr int kItemColumns = 8;

void menu_record_item_panel(VkCommandBuffer cmd, VkImage image, VkImageView view, uint32_t w, uint32_t h, const MkwVkItemMenu& m,
                            const int* order, int pick, int sort) {
    (void)sort;
    if (!ui::begin(w, h)) return;
    ImDrawList* d = ImGui::GetBackgroundDrawList();
    const ui::Fonts& fonts = ui::fonts();
    ImFont* digits = fonts.number ? fonts.number : fonts.menu ? fonts.menu : fonts.body;
    const float k = (float)h / 2160.0f, bx = (float)w - kItemFromRight * k, by = kItemFromTop * k;
    const int64_t now = prof_now();
    static int64_t last = 0, opened = 0;
    if (!last || now - last > 300000000LL) opened = now;   // (shut for a while: a new open)
    last = now;
    const float in = std::clamp((float)((now - opened) / 1.5e8), 0.0f, 1.0f);
    const int cols = std::max(1, std::min(m.item_n, kItemColumns));
    auto col = [&](int r, int g, int b, float a) { return IM_COL32(r, g, b, (int)(std::clamp(a * in, 0.0f, 1.0f) * 255 + 0.5f)); };
    auto spot = [&](int j, float& x, float& y) { x = (float)(j % cols - (cols - 1)) * kItemStep, y = (float)(j / cols) * kItemStep; };
    auto pic = [&](const ui::Art* t, float x, float y, float sw, ImU32 c) {   // (x, y: layout units from the item box's middle)
        if (t) d->AddImage(t->tex->GetTexRef(), ImVec2(bx + (x - sw / 2) * k, by + (y - sw / 2) * k), ImVec2(bx + (x + sw / 2) * k, by + (y + sw / 2) * k), ImVec2(0, 0), ImVec2(1, 1), c);
    };
    auto icon_of = [](const char* actor) {
        const ui::Art* t = ui::item_icon((std::string(actor) + "_PouchIcon").c_str());
        return t ? t : ui::item_icon(actor);
    };
    int pick_at = -1;
    for (int j = 0; j < m.item_n; j++)
        if (order[j] == pick) pick_at = j;
    float px = 0, py = 0;
    if (pick_at >= 0) spot(pick_at, px, py);
    const float pulse = 0.75f + 0.25f * std::sin((float)(now / 1e9) * 3.0f);
    if (pick_at >= 0) pic(ui::art("shortcut_cursor_glow"), px, py, kItemBox * 1.38f, col(255, 255, 255, 0.8f * pulse));
    for (int j = 0; j < m.item_n; j++) {
        const int i = order[j];
        float x, y;
        spot(j, x, y);
        const bool chosen = j == pick_at;
        const float box = chosen ? kItemBox * 1.06f : kItemBox;
        pic(ui::art("SelectItemBase_00"), x, y, box, col(70, 56, 38, 0.85f));
        pic(ui::art("SelectItemBase_01"), x, y, box, col(214, 196, 150, chosen ? 1.0f : 0.7f));
        pic(icon_of(m.item_list[i].item_actor), x, y, box * 0.86f, col(255, 255, 255, 1.0f));
        if (m.item_list[i].item_count >= 0 && digits) {
            char nb[16];
            snprintf(nb, sizeof nb, "%d", m.item_list[i].item_count);
            const float size = 72 * k;
            const ImVec2 sz = digits->CalcTextSizeA(size, FLT_MAX, 0, nb);
            const ImVec2 p(bx + (x + box * 0.44f) * k - sz.x, by + (y + box * 0.34f) * k - sz.y * 0.5f);
            d->AddText(digits, size, ImVec2(p.x + 3 * k, p.y + 3 * k), col(0, 0, 0, 0.6f), nb);
            d->AddText(digits, size, p, m.item_list[i].item_full ? col(120, 220, 80, 1.0f) : col(255, 255, 255, 1.0f), nb);
        }
    }
    if (pick_at >= 0) pic(ui::art("shortcut_cursor_line"), px, py, kItemBox * 1.22f, col(255, 255, 255, 0.95f));
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (Dear ImGui records into cmd directly: what this thread recorded through vk_work.h reaches cmd first)
    ui::record_to(cmd, image, view, w, h);
}

} // namespace mkwvk

// (Triforce VR) a VR row's value by its key, as text: a choice's name, else the number; "" for a key that is not a VR row
extern "C" int vk_xr_live_sword(void);
extern "C" int vk_xr_live_mirror(void);
extern "C" int vk_xr_two_hands(void);
extern "C" const char* vk_xr_cfg(const char* key) {
    static thread_local char b[24];
    // ((Triforce VR) the hand controllers always play, with motion; a gamepad alongside them as a pad (no rows for these now).
    // Control Scheme's Simplified (1): Full Gesture with fewer gestures (vk_xr.cpp, vr_game.c: VR_CONTROLS "simplified")
    if (!strcmp(key, "VR_CONTROLS")) return mkwvk::opts.vr_scheme == 1 ? "simplified" : "meta";
    // ((Triforce VR) motion play (the pointed aim, vr_game.c): both schemes'
    if (!strcmp(key, "VR_PLAY")) return "motion";
    // ((Triforce VR) the sword hand before a draw chooses one: Controls' Right handed Link (no VR row for it now)
    if (!strcmp(key, "VR_HANDEDNESS")) return mkwvk::opts.right_handed ? "right" : "left";
    if (!strcmp(key, "VR_MIRROR")) {   // ((Triforce VR) Link mirrored for what the hands last did, "" before: vk_xr.cpp)
        const int v = vk_xr_live_mirror();
        return v < 0 ? "" : v ? "on" : "off";
    }
    if (!strcmp(key, "VR_TWO_HANDS")) {   // ((Triforce VR) the hand whose item both hands hold, "alone" the shield's alone, "" neither
        const int v = vk_xr_two_hands();
        return v == 2 ? "alone" : v == 1 ? "right" : v == 0 ? "left" : "";
    }
    if (!strcmp(key, "VR_SWORD_HAND")) {   // ((Triforce VR) the last two-grip draw's sword hand, "" before one: vk_xr.cpp)
        const int v = vk_xr_live_sword();
        return v < 0 ? "" : v ? "right" : "left";
    }
    for (const mkwvk::VrKey& v : mkwvk::vr_keys) {
        if (strcmp(v.key, key)) continue;
        const int n = *v.value;
        if (!v.choices) {
            snprintf(b, sizeof b, "%d", n);
            return b;
        }
        const char* c = v.choices;
        for (int i = 0; i < n && c; i++) c = strchr(c, '|'), c = c ? c + 1 : nullptr;
        if (!c) c = v.choices;
        const char* end = strchr(c, '|');
        const size_t len = std::min(sizeof b - 1, end ? (size_t)(end - c) : strlen(c));
        memcpy(b, c, len), b[len] = 0;
        return b;
    }
    return "";
}

// (Triforce VR) where the counter's overlay was drawn this frame (window pixels {x, y, w, h}), for vk_xr.cpp to lift it onto
// the HUD's panel: 0 when not drawn
static int menu_rect_of(const float f[4], int r[4]) {
    if (!(f[2] > 0) || !(f[3] > 0)) return 0;
    for (int i = 0; i < 4; i++) r[i] = (int)(i < 2 ? std::floor(f[i]) : std::ceil(f[i]));
    return 1;
}
int menu_perf_rect(int r[4]) { return menu_rect_of(mkwvk::perf_rect, r); }
