// The Insert menu (vk_menu.cpp): options that apply while the game runs, kept in triforce_options.ini beside the executable.
#pragma once

#include "vk_internal.h"
#include "replay_threads.h"   // (the Replay helper threads row: its Automatic and what it is unless set)

namespace mkwvk {

// (out of the box every feature is off: what the game does on its own. The ini beside the executable keeps a player's choices)
struct Options {
    int framegen = 0;     // made frames: 0 off, 1 Auto (to the display's refresh), or 2 to 8 times the game's frames
    int fg_by = 0;        // ((Triforce) 11-24) Frame generation by, at Auto and 2x to 8x: 0 the renderer's own, 1 AMD FSR 3.1's frame
                          // interpolation (framegen_rows.h BY_*, vk_fsr3fi.h); taken at each present
    int pace = 1;         // frames shown on an even line (vk_framegen.cpp); (Triforce) on by default since options_version 7
    int tail_early = 1;   // (Triforce) Start next frame early (Debug tab, on by default since options_version 6): 1 the game's frame wait ends before its frame's upscaler and interface run on
                          // the GPU (gpu/vk/vk_replay.cpp the early tail, tail_early.h; RX_VK_TAIL_EARLY over it); read at the start
                          // (tail_early=, NX2navi's key)
    int threaded_rendering = 0;   // ((Triforce) Threaded rendering, Debug tab: 0 Off (the default: as before), 1 On, 2 Auto (by the
                                  // physical cores); threaded_rendering.h, vk_main.cpp threaded_choice; RX_VK_THREADED over it; read at the start
    int hdr = 0;          // (hookshot) HDR10 out (vk_framegen.cpp framegen_hdr): 0 off, 1 the SDR picture expanded, 2 the game's own (native) HDR; when the display has it (the swapchain made again at once)
    int hdr_white = 200;  // HDR paper white, nits (the picture's white)
    int colour_vision = 0;   // ((Triforce) 11-24) Colour vision correction: 0 Off, 1 Protan, 2 Deutan, 3 Tritan; taken at each
                             // present (colour_vision.h, vk_framegen.cpp framegen_scale)
    int hdr_peak = 1000;  // HDR peak brightness, nits (its brightest highlights): 400 to 10,000, HDR10's ceiling
    // (Triforce, 11-13: both additions of the 11-13 patches are off until their row turns them on, read once at the start)
    int renodx = 0;       // RenoDX HDR: 0 off, 1 RenoDX's shaders with HDR Native (host/nn_vi.c reads renodx_hdr= at the start)
    int upscale_pre = 0;  // Upscale before bloom: 0 the Upscaler's engine on the finished picture, as before; 1 on the scene
                          // before the game's bloom and tone mapping (vk_temporal.cpp pre_wanted)
    // (local, RenoDX port: vk_renodx.cpp) with HDR Native, RenoDX's shaders in place of the game's tone mapping and HDR output
    int rdx_tonemap = 1;      // 0 Vanilla (the game's curve), 1 PsychoV35, 2 RenoDRT (Triforce: renodx_glue/triforce_scene.slangi)
    // (Triforce: NX2navi's HDR rows, each at the value that leaves the picture as it was before the row. vk_renodx.cpp
    // fill_settings maps them; the rows of one tone mapper show while it is the one chosen, vk_menu.cpp rdx_applies)
    int rdx_gamma = 0;        // the finished picture shown as a display of that gamma would: 0 off (the sRGB curve), 1 2.2, 2 BT.1886 (2.4)
    int rdx_match_slope = 1;  // PsychoV35: its mid tones as steep as the game's own curve; 0: the response's own slope
    int rdx_tone_slope = 50;  // PsychoV35: the tone curve's steepness through middle grey, 0 to 100, 50 unchanged
    int rdx_hue_clip = 50;    // PsychoV35: percent of the hue bend the game's clamp gives bright colours
    int rdx_highlight_sat = 50;   // RenoDRT: the brightest parts' saturation, 0 to 100, 50 unchanged
    int rdx_blowout = 0;      // RenoDRT: the brightest parts towards white, 0 to 100, 0 none
    int rdx_flare = 0;        // RenoDRT: the darkest parts lifted, 0 to 100, 0 none
    int rdx_hue = 100;        // RenoDRT: percent of their hue bright colours keep through the tone mapper
    int rdx_grade = 100;      // RenoDRT: percent of the game's own colour grading the picture keeps
    int rdx_midgray = 1;      // what PsychoV35 holds middle grey to: 0 the render's, 1 vanilla's, 2 the eye adaptation's
    int rdx_ui_white = 200;   // the menus' and HUD's white, nits
    int rdx_space = 1;        // the output's colour space: 0 Vanilla (the game's matrix), 1 BT.709, 2 DCI-P3
    int rdx_exposure = 100;   // percent, 0 to 200
    int rdx_highlights = 50, rdx_shadows = 50, rdx_contrast = 50, rdx_saturation = 50;   // 0 to 100, 50 neutral
    int rdx_bloom = 50;       // 0 to 100, 50 the game's
    int fps_cap = 0;      // (hookshot) Frame rate cap: 0 60 (the console's), 90, 120, 144, 165, 240; -1 45, -2 40, -3 30; 6 the monitor's
                          // refresh rate (fps_cap.h); 7 Uncapped (host/nn_vi.c reads frame_rate_cap= at the start)
    int steady_fps = 0;   // (Triforce) Steady frame rate: 0 Off, 1 any rate, 2 steps of the display's refresh (host/pace_steady.h; host/nn_vi.c
                          // reads steady_frame_rate= at the start)
    int reflex_limit = 0; // (Triforce) Reflex frame limit: 1 with DLSS frame generation NVIDIA Reflex's sleep holds the frame rate cap where the
                          // game's frame starts and the game's own wait steps aside (vk_dlssg.cpp pace, dlssg_pace.h); 0 the game's own wait.
                          // (options_version 7) No row, no key: 0, the old row's default and what nearly every options file held,
                          // until the path has been played with DLSS frame generation on an RTX 40/50 card (the old row's note:
                          // nobody had run it in the game). RX_VK_REFLEX_LIMIT=1 turns it on for a run (menu_init), as it does
                          // Reflex's hold without frame generation (vk_reflex.cpp reflex_pace)
    int resolution = 0;   // the 3D's (Render resolution): 0 Auto (the game's dynamic resolution), else a share of the output,
                          // 1..6 = 100%, 75%, 67%, 50%, 58%, 33% (upscaler_rows.h; nx2/oot_patches.py)
    int output_res = 0;   // the game's whole frame, docked: 0 its 2048x1152, 1 2560x1440, 2 3840x2160, 3 1920x1080, 4 5120x1440, 5 5120x2880, 6 5120x2160;
                          // 8 Screen, 9 Custom (output_sizes.h); 7 1536x864, the game's handheld profile (merged_rows.h kHandheldOutput); read once, at the start (host/nn_applet.c)
    int output_width = 2560, output_height = 1440;
    int upscale = 0;      // to the window: 0 off (the plain copy), 1 Catmull-Rom, 2 Lanczos, 3 AMD FSR 1 (EASU + RCAS). (options_version 7) No
                          // row: chosen at each present by the picture's size and its place in the window (vk_menu.cpp
                          // menu_note_present_sizes, upscaler_rows.h auto_filter); RX_VK_UPSCALE=<0..3> fixes it for a run
    int reflex = 2;       // NVIDIA Reflex: 0 off, 1 on, 2 on + boost (the default since options_version 5) (vk_reflex.cpp; NVIDIA GPUs with VK_NV_low_latency2)
    int antilag = 0;      // AMD Anti-Lag 2: 0 off, 1 on (vk_antilag.cpp; AMD GPUs with VK_AMD_anti_lag)
    int dlss = 0;         // the Upscaler (its name from before FSR: options files and the tests' stand-ins keep it): 0 the game's
                          // own network, 1 NVIDIA DLSS, 2 NVIDIA DLAA (a build with NVIDIA's SDK only), 3 AMD FSR 3.1 (vk_fsr3.cpp),
                          // 4 AMD FSR 4, 5 its native AA (a build with FSR 4 only), 6 FSR 3.1's native AA. upscaler_rows.h;
                          // vk_temporal.cpp. Saved as dlss
    int fsr4_model = 0;   // ((Triforce) AMD FSR 4's network: 0 Auto (AMD's own pick for this GPU), 1 Lite (the faster INT8
                          // network; upscaler_rows.h FSR4_MODEL_LITE; vk_fsr4.cpp fsr4_model). RX_VK_FSR4_MODEL over it
    int dlss_model = 0;   // DLSS's network, by its preset: 0 K (transformer), 1 M, 2 L (second-generation transformer), 3 NVIDIA's
                          // default (upscaler_rows.h model_preset; vk_dlss.cpp). RX_VK_DLSS_PRESET over it
    // 0 to 100. ((Triforce, S1) With DLSS, DLAA, FSR 3.1 and FSR 4 the 3D before the HUD, the upscaler's own sharpening
    // (vk_temporal.h temporal_sharpens_3d); with the game's own upscaler the finished picture at the window. 0 by default,
    // as before: the default Upscaler is the game's own, where any other value sharpens the HUD and text at the window and
    // runs that pass every present. A file that has the key keeps its value
    int sharpness = 0;
    int aa = 0;           // (Triforce) Anti-aliasing: 0 the game's own SMAA, as before the row; in its place 1 nothing, 2 FXAA, 3 SMAA at
                          // its Ultra preset (aa_rows.h, vk_aa.cpp; RX_VK_AA over it). Not applied while DLSS, DLAA or FSR
                          // upscales. Taken each frame. Saved as anti-aliasing
    // ((Triforce, 11-22, N64 Classic, step 5) the 1998 look (n64_rules.h, vk_n64.cpp): 0 Off, 1 Faithful (fixed), 2 Remembered
    // (the Remembered page's rows below). Taken at each frame; RX_VK_N64 over it. Saved as n64_classic
    int n64_classic = 0;
    int n64_last = 1;     // the preset F7 turns on from Off, the last one chosen (n64_rules.h Toggle); saved as n64_classic_last
    // Remembered's page, by n64_rules::Row: n64_rules.h kSpec's defaults (tests/test_n64_row.py holds the two the same), saved
    // under kSpec's keys (vk_menu.cpp ini_key)
    int n64_rem[13] = {0, 2, 2, 0, 3, 1, 35, 0, 15, 1, 25, 1, 110};
    int evil_hd = 0;      // (Triforce, 11-23) Evil HD: 0 Off, 1 On: SMAA Ultra, 16x filtering, Full textures (from the next start) and
                          // the far foliage shadows whole, over the rows below while on (evil_hd.h). Saved as evil_hd
    int aniso = 0;        // texture filtering: 0 the game's, 1 2x, 2 4x, 3 8x, 4 16x anisotropic at least (vk_draw.cpp sampler_for)
    int tex_detail = 0;   // (Triforce) Texture detail: 0 Automatic (by the card's video memory), 1 Full, 2 Reduced, 3 Low; read at the
                          // start (tex_detail.h, vk_texture.cpp texture_detail_level; RX_VK_TEX_DETAIL over it)
    int tex_bc1 = 1;      // (Triforce) Opaque textures as BC1: 0 Off, 1 On (the default since options_version 5): ASTC textures the renderer keeps as BC3 are kept as BC1,
                          // half the video memory, when every block of them is opaque; read at the start (tex_bc1.h, vk_texture.cpp
                          // bc1_on; RX_VK_TEX_BC1 over it)
    // ((Triforce) 11-24) the Graphics tab's Detail rows, taken at once. shadow_res: Shadow resolution, the sun's cascades: 0 the
    // game's 1600 (default), 1 2200, 2 3072, the nearest cascade then also kept steady (HOS_OPT_SHADOW_RES: host/oot_shadow.c,
    // host/oot_shadow_fit.c). grass_distance: Grass distance, the short grass blades' reach: 0 the game's (default), 1 2x,
    // 2 3x, 3 4x (vk_draw.cpp grass_reach; RX_VK_GRASS_DISTANCE over it)
    int shadow_res = 0;
    int grass_distance = 0;
    // ((Triforce) Auto (this PC), the Graphics tab's first row (auto_settings.h, vk_menu.cpp auto_apply): 0 Off (default,
    // nothing set or tuned), 1 On: the Upscaler, Render resolution, Texture detail, Shadow resolution and Grass distance set
    // from the hardware when turned On (or at a start on new hardware), and tuned in play. A row it sets changed by hand turns
    // it Off. auto_tune: the tuning's state (auto_settings.h pack); auto_for: the hardware it chose for (fingerprint)
    int auto_pc = 0;
    int auto_tune = 0;
    int auto_for = 0;
    int realtime = 1;     // game time follows the clock (host/nn_vi.c); 0: per frame (slower frames, slower game)
    int ultrawide = 0;    // the picture's shape for a 16:9 Output resolution: 0 the game's 16:9, 1 a fixed 16:10, 2 a fixed 21:9, 3 a fixed
                          // 32:9 (ultrawide_rows.h); read once, at the start (host/hos_main.c ultrawide_ratio)
    // ((Triforce) and 3 Extended: at their 16:9 size with their side panes at the screen's edges, host/hos_wide_ui.c)
    // ((Triforce) the HUD placement row: 0 the game's, 1 Custom, the three groups below moved (percent of the picture, -15 to 15)
    // and sized (75 to 125 percent): host/hos_wide_ui.c, at each present (menu_hud_option))
    int hud_placement = 0;
    int hud_health_x = 0, hud_health_y = 0, hud_health_scale = 100;
    int hud_buttons_x = 0, hud_buttons_y = 0, hud_buttons_scale = 100;
    int hud_minimap_x = 0, hud_minimap_y = 0, hud_minimap_scale = 100;
    int wide_menus = 1;   // ultrawide: the pause, item and map menus 0 at full width (stretched), 1 in the middle 16:9 with the sides
                          // blurred, 2 with black bars (nx2/oot_wide.py, vk_framegen.cpp)
    int show_fps = 0;     // the FPS counter row: 0 off, 1 the counter, 2 (Triforce) Full, NX2navi's full performance overlay in the counter's place:
                          // the machine, the frames, the waits per frame, the settings (vk_menu.cpp draw_perf, perf_stats.h,
                          // perf_machine.h), measured only while shown
    int menu_shortcut = 0;   // 0 Insert or F1, 1 F1 only, 2 Insert, F1 or Esc, 3 Insert, F1 or touchpad,
                             // 4 Insert, F1, Esc or touchpad (F1 always opens the menu; the touchpad as F1)
    int menu_size = 0;   // (hookshot) the overlays' size: 0 Auto, 1 Small, 2 Medium, 3 Large (gpu/vk/vk_ui.h unit)
    int fullscreen = 0;   // borderless, at the monitor's size: F10 and Alt+Enter are the same setting
    int fs_screen = 0;    // ((Triforce) 11-24) Fullscreen screen: 0 the window's (the default), n the n-th connected screen as the host
                          // lists them (MkwVkHost.screens), kept by its name too (fullscreen_screen_name); HOS_OPT_FULLSCREEN_SCREEN
    int vsync = 1;        // (Triforce) VSync: 1 the swapchain's present mode as before the row (mailbox where the driver has it), 2 FIFO
                          // (11-24: Every refresh, present_mode.h's force_fifo), 0 immediate
                          // where the surface lists it (present_mode.h, vk_main.cpp create_swapchain; the swapchain made again at once)
    int gpu_device = 0;   // graphics card index: 0 Auto, 1..N device 0..N-1 (gpu/vk/vk_main.cpp; RX_VK_DEVICE)
    int pad_background = 0;   // the controllers count while another window has the focus (host/nn_hid.c; HOS_INPUT_BACKGROUND)
    int mouse_native = 0; // Mouse camera: 1 the mouse turns the camera's own angles (host/mouse_native.c); 0: as the right stick;
                          // (Triforce) 2 Off: the mouse is never captured, so it turns no camera and presses no button (host/display.c)
    int mouse_sens = 100; // the mouse's sensitivity in percent: 0.1 degrees a count at 100 with native look (host/nn_hid.c)
    int mouse_invert = 0; // the mouse's up and down swapped
    int mouse_invert_x = 0;   // ((Triforce) 11-24) the mouse's left and right swapped (HOS_OPT_MOUSE_INVERT_X, 190)
    // ((Triforce) 11-24) hold-to-toggle, a row for each of the Switch's buttons A to ZR, by HOS_SW_*: 1, a press holds the
    // button and the next lets it go. Saved one by one (toggle_a .. toggle_zr); the host reads them as one mask
    // (HOS_OPT_HOLD_TOGGLE, 191: host/nn_hid.c npad_states)
    int toggle[10] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
    int text_speed = 0;   // how fast dialogue prints: 0 the game's, 1 2x, 2 4x, 3 instant (host/nn_vi.c, nx2/oot_patches.py; HOS_TEXT_SPEED)
    int fov = 100;        // (Triforce) Field of view: the camera's vertical angle in play, percent of the game's own, 50 to 150 (host/oot_fov.c)
    int text_size = 0;    // (Triforce) Text size: the text of dialogue, Navi and signs, 0 the game's own, 1 110%, 2 125%, 3 150%, 4 175%
                          // (host/oot_text_size.c, nx2/oot_patches.py; HOS_TEXT_SIZE over it)
    int camera_centering = 1;   // (Triforce) Camera centering: 1 the game's own, the camera turns by itself the way Link moves; 0 it
                                // stays where the player put it (host/mouse_native.c hos_disable_camera_centering, nx2/oot_patches.py)
    int damage_taken = 1; // (Triforce) Damage taken: what a hit takes off Link's life, 0 Half, 1 Normal (the game's own), 2 Double,
                          // 3 Quadruple (host/oot_damage.c, nx2/oot_patches.py)
    int skip_opening = 0; // (Triforce) Skip opening: 1 a new game starts without its opening, the story movie and Navi waking Link
                          // (host/oot_opening.c, nx2/oot_patches.py)
    int skip_title = 0;   // (Triforce) Skip title screen: 1 the game's start is pressed through to the newest save, Continue and Load
                          // (host/oot_autoload.c: read once, when the title's list first shows)
    int autosave = 1;     // (Triforce) Autosave: 1 the game's own; 0 its autosaves of going from one area to another are skipped
                          // (host/oot_autosave.c, nx2/oot_patches.py)
    int mute_background = 0;   // (Triforce) Mute in background: 1 no sound while another window has the focus (host/nn_audio.c master_volume)
    int mic_gain = 100;   // (Triforce) Microphone gain: the ocarina's microphone, percent of what it gives, 25 to 400 (host/nn_audio_in.c, host/mic_gain.h)
    int invert_cam_x = 0; // right-stick camera horizontal inversion: 0 normal, 1 inverted
    int camera_speed = 100;   // (Triforce) the right stick's camera speed, percent of the game's own (host/prompts.c build_camera)
    int invert_cam_y = 0; // right-stick camera vertical inversion: 0 normal, 1 inverted
    int rumble = 100;     // the controllers' rumble in percent of the game's: 0 Off, 25 to 300 (host/pad_sdl.c)
    int rumble_curve = 100;   // (Triforce) the power on the motors' rumble, in hundredths: 20 to 150, 100 none (host/pad_sdl.c rumble_curve)
    int rumble_triggers = 0;  // (Triforce) the rumble in an Xbox pad's trigger motors too: 0 off (host/pad_sdl.c trigger_poll)
    int vibration = 0;        // ((Triforce) 11-24) Vibration: 0 Auto, 1 Basic (the motors), 2 Off (host/vibration.h)
    int ds_hd_haptics = 1;    // ((Triforce) 11-24) DualSense HD Haptics with RenHDrum: its speaker and triggers too, 1 on
    // ((Triforce) 11-24) the Audio tab's Controller speaker rows: a DualSense's own speaker (host/pad_speaker.c;
    // HOS_OPT_PAD_SPEAKER_*). Off for every kind of sound and for the headphones by default: the game sounds as before
    int pad_speaker_volume = 100;   // its volume in percent, 0 to 200: 100 is twice the mixer's level (a small speaker)
    int pad_speaker_sync = 0;       // -100 to 150 ms: above 0 the controller waits (a later TV), below 0 the TV's copy waits
    int pad_speaker_headphones = 0; // headphones in its jack: 0 left out, 1 the controller's sounds there, 2 all sound there
    int pad_speaker_headphone_volume = 80;   // their volume in percent, 0 to 100
    // where each kind of sound plays, host/audio_source.h's classes in order from Navi's voice: 0 Off (the game's sound
    // alone), 1 the controller only, 2 the controller and the TV
    int pad_speaker[12] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
    int stick_dead_zone = 0;  // a stick axis below it is 0: 0 XInput's 7849 (~24%), 1..5 5% to 30% (host/nn_hid.c). (options_version 7) No
                              // row: always 0, the Default; an older file's moved into each stick's own (merged_rows.h migrate)
    int lstick_dead_zone = -1;   // (Triforce) the left stick's own dead zone, percent: -1 Default (XInput's ~24%), 0 to 50 (host/nn_hid.c hos_stick_axis_own)
    int rstick_dead_zone = -1;   // (Triforce) the right stick's own
    int walk_key = 0;     // (Triforce) the key that makes the movement keys walk while it is held: 0 Off, 1 Caps Lock, 2 Shift, 3 Ctrl, 4 Tab (host/nn_hid.c walk_key_code)
    int walk_scale = 51;  // (Triforce) how far they push the left stick then, in hundredths of all the way: 20 to 90 (host/nn_hid.c walk_keys)
    int pad_layout = 0;   // 0 Nintendo (default), 1 Xbox / PC, 2 Swap Face Buttons, 3 Custom
    int gyro = 1;         // motion controls from a pad's gyroscope (host/pad_sdl.c, host/hos_motion.h); on by default
    int gyro_sens_x = 100;   // the motion aim's horizontal sensitivity in percent
    int gyro_sens_y = 100;   // the motion aim's vertical sensitivity in percent
    int gyro_inv_x = 0;   // the motion aim's horizontal turned around
    int gyro_inv_y = 0;   // the motion aim's vertical turned around
    int gyro_deadzone = 1;   // the motion's deadzone: 0 tight, 1 standard (the console's default), 2 loose
    int prompts = 0;      // the button icons: 0 Auto (the controller), 1 Switch, 2 Xbox, 3 PS4, 4 PS5, 5 Steam Deck (host/prompts.c),
                          // (Triforce) 6 Keyboard & mouse
    int robust = 1;       // bounds-checked buffer access: 0 Auto (off), 1 Off (the default since 11-17, the owner's), 2 On (gpu/vk/vk_main.cpp; RX_VK_ROBUST)
    int mesh_mode = 0;    // (Triforce, 11-18) the game's mesh-shader draws: 0 Auto (vk_main.cpp's rule), 1 Compute fallback (RX_VK_TASK_MESH_FALLBACK over it)
    int descriptor_reuse = 1;  // (on by default since options_version 4) a draw keeps its descriptors through other slots' registrations (gpu/vk/vk_draw.cpp; RX_VK_DESC_SLOTGEN)
    int sampler_cache = 1;     // (on by default since options_version 5) sampler ids answer their parameters without the registrations' lock (gpu/vk/vk_draw.cpp; RX_VK_SAMPLER_CACHE)
    int fast_pipeline_link = 1;   // (Triforce, the Debug tab; on by default since options_version 5) Fast pipeline link: a new pipeline is linked from its stage libraries first
    int compile_shaders = 0;      // ((Triforce, 11-24) the Debug tab's Compile shaders: 0 All (the default), 1 Most; read by the shader preparation (gpu/vk/compile_level.h)
                               // (gpu/vk/vk_draw.cpp gpl_wanted, gpl_rules.h; RX_VK_GPL over it); read at the start, from the file
    int lazy_write_back = 1;   // (Triforce, the Debug tab; on by default since options_version 5) Lazy write-back: what shaders write into mirrored pools is copied back
                               // to guest memory when it is read (gpu/vk/vk_memory.cpp, wb_lazy_state.h; RX_VK_LAZY_WB over it,
                               // off on AMD's driver unless that says 1, Windows only); read at the start, from the file
                               // (lazy_write-back=, the row's name)
    int replay_threads = 8;    // (Triforce, the Debug tab) Replay helper threads: 0 off, 1 to 7 the parallel replay tried on 2 to 8
                               // threads, what RX_VK_PARALLEL_AUTO=<n> does, 8 Automatic (the default, replay_threads.h
                               // kDefaultRow: that header says why), the count replay_threads.h gives this PC
                               // (replay_threads_of; gpu/vk/vk_replay.cpp par_threads_max); read at the start
    // ((Triforce, options_version 7) The Quality preset row is gone: these limits, which only it set, stay 0, the card's own
    // sizes from its video memory (vk_texture.cpp texture_frame, vk_memory.cpp mirror_budget))
    int vram_mb = 0;      // dynamic texture cache budget limit in MB
    int mirror_mb = 0;    // staging mirror limit in MB
    int audio_output = 0; // (hookshot) the speakers the game mixes for: 0 Auto (the default output's), 1 Stereo, 2 5.1; read once, at the start (host/nn_audio.c; HOS_AUDIO_CHANNELS);
                          // (Triforce) 3 Mono: stereo's layout, the two channels' average in both, taken at once (host/nn_audio.c audio_mono)
    int volume = 100;  // (Triforce) Master volume, percent of the game's own (host/nn_audio.c render_frame; master_volume= in the ini)
    int menu_sounds = 80;   // (Triforce) Menu sounds: how loud the options' own sounds are, the game's interface sounds, percent,
                            // 0 silent; 80 as NX2navi's menu_sound_volume (host/menu_sound.c; menu_sounds= in the ini)
    int dlssg = 0;           // (Triforce) NVIDIA DLSS frame generation: 0 off, 1 2x, 2 3x, 3 4x; read at the start (vk_dlssg.cpp, dlss_frame_generation=)
    int wide_hud = 0;        // (Triforce) with Ultrawide: 0 the HUD in the middle 16:9, 1 its corner pieces at the screen's edges (host/oot_wide_hud.c)
    int sprint_button = 0;   // (Triforce) the sprint button: 0 off, 1 the left stick's click, 2 B (host/oot_sprint.h)
    int right_handed = 0;    // (Triforce) Link right-handed: his animation mirrored, what he holds in the other hand (host/vr_body.c)
    int sprint_mode = 0;     // 0 toggle (a press starts it, the next ends it), 1 hold
    // ((Triforce) 11-23) the System tab's Achievements group (host/achievements.c): whether anything is earned, and whether
    // one earned shows its notice and plays its sound. HOS_ACHIEVEMENTS=0 still turns them off whole
    int achievements = 1;
    int achievement_notices = 1;
    int discord = 1;   // (hookshot) the Discord status (host/discord_rpc.c): 1 on, shown while a Discord client runs on this PC
    int language = 0;  // (Triforce) Game language: the row's entry among the languages language.txt names (game_language.h). Not kept in
                       // the options file: the choice is that file's line, which the host reads at the start (host/nn_applet.c)
    // (Triforce) Menu language: this menu's own. 0 Auto (the language the game runs in), 1 English (the default, as before
    // the row), then menu_i18n.h's other languages (vk_menu_i18n.h lang_name(menu_lang - 1)). Saved as menu_language
    int menu_lang = 1;
    int debug_tools = 0;   // (hookshot) the Debug tab's tools (#785: flight, free camera, teleport, inventory): 0 off; HOS_OOT_CHEATS=1 also turns them on
    int mic = 1;          // (hookshot) the ocarina's microphone: 0 Off, 1 the system's default, 2.. a device as host->mic_name lists it (host/nn_audio_in.c)
    // (Triforce VR) the VR tab (vk_xr.cpp and host/vr_game.c read them through vk_xr_cfg; vr is read at the start)
    int vr = 0;                 // 0 off, 1 VR through OpenXR
    int vr_view = 1;            // 0 Theater (the game on a floating screen), 1 Immersive (the game's camera follows the head)
    int vr_screen_size = 65;    // the floating screen's width, degrees of the view (45 to 125)
    int vr_screen_curve = 1;    // the floating screen curved around the head
    int vr_camera = 0;          // Immersive: 0 first person (Link's eyes), 1 third person (the game's camera turned by the head)
    int vr_view_scale = 100;    // the game's lens over the headset's, percent (50 to 200)
    int flat3d = 0;             // (Triforce) Flatscreen 3D without a headset: 0 off, 1 red/cyan, 2 side by side, 3 crossed eyes, 4 above and below, 5 Cardboard
    int flat3d_depth = 250;     // its eyes' distance, percent of 6.4 cm
    int flat3d_screen = 0;      // the screen's distance in cm, 0 the nearest thing in the picture's middle
    int vr_resolution = 1;      // (Triforce VR) the 3D's size while VR is on: 0 the Graphics tab's Render resolution, else its values
    int vr_stereo = 1;          // 0 Performant (each eye from one picture and its depth), 1 Balanced (eyes in turn, the game's time held)
    int vr_depth = 100;         // the eyes' distance, percent of the wearer's own (0 to 200)
    int vr_eye_up = 0, vr_eye_side = 0, vr_eye_forward = 0;   // first person: the eyes moved from Link's, cm (-30 to 30)
    int vr_event_up = 0;        // cutscenes: the eyes raised this many cm (-50 to 50)
    int vr_cutscenes = 1;       // Full Dive: cutscenes from 0 the game's camera (Classic), 1 Link's eyes
    int vr_aim_tilt = 35;       // Motion's pointed aim: the controller's ray tilted down, degrees (0 to 60)
    int vr_swing_speed = 230;   // a sword swing's hand speed, cm a second (100 to 500)
    int vr_charge_reach = 35;   // how far out from the head a swing must leave the hand to hold the charge, cm (25 to 70)
    int vr_hud_size = 100;      // the HUD panel's width, cm a metre away (40 to 200)
    int vr_scheme = 0;          // the VR hand controllers' control scheme: 0 Full Gesture, 1 [PlaceHolder] (vk_xr.cpp)
    int vr_body = 1;            // first person: 0 Link hidden, 1 his arms on the controllers and his head hidden (host/vr_body.c)
    int vr_arm_reach = 135;     // the arms' stretch to reach the controllers, percent of their length (100 to 160)
    // ((Triforce) 11-24) the Graphics tab's ReShade preset (reshade/fx_builtin.h): 0 Off, the default; 1 Warm, 2 Cool, 3 User (its
    // file named in the game folder's reshade/selected.txt), 4.. the others. Saved as reshade_preset
    int reshade = 0;
};
extern Options opts;
/// (local, RenoDX port) opts.hdr as triforce_options.ini had it at the start (menu_init), before any change in play: what
/// host/nn_vi.c hos_scene_rgba16f decided the scene's format from (vk_temporal.cpp temporal_scene_format)
extern int hdr_at_start;
/// (Triforce) opts.renodx and opts.upscale_pre as the file had them at the start: what this run does (RX_VK_RENODX and
/// RX_VK_DLSS_PRE, 0 or 1, over them)
extern int renodx_at_start, upscale_pre_at_start;
/// Whether RenoDX's shaders run in this session: the RenoDX HDR row as it was at the start, or RX_VK_RENODX
bool renodx_chosen();
/// (Triforce) opts.replay_threads as the file had it at the start, and the threads a value of that row stands for: 0 none,
/// else one more than the value (the row has no "1 thread": that is the replay thread alone, off). RX_VK_PARALLEL_AUTO and
/// RX_VK_PARALLEL go over the row (vk_replay.cpp par_threads_max). The row's 8, Automatic, is not one of these: its count
/// is the PC's (replay_threads.h automatic, vk_replay.cpp replay_threads_automatic)
extern int replay_threads_at_start;
constexpr int replay_threads_of(int row) { return row >= 1 && row <= 7 ? row + 1 : 0; }
/// (Triforce) opts.tex_detail as the file had it at the start: what this run's textures are made with (vk_texture.cpp
/// texture_detail_level; RX_VK_TEX_DETAIL over it)
extern int tex_detail_at_start;
/// ((Triforce, 11-23) Evil HD as the renderer applies it now: the row's value, or for the lab's before/after pictures
/// RX_VK_EVIL_FLIP=<presents> turning it the other way every that many presents (vk_menu.cpp). The row's own notes read the row)
int evil_hd_now();
/// (Triforce) opts.tex_bc1 as the file had it at the start: whether this run keeps opaque ASTC textures as BC1
/// (vk_texture.cpp bc1_on; RX_VK_TEX_BC1 over it)
extern int tex_bc1_at_start;
/// (vk_memory.cpp) true when the quality preset's memory budgets (vram_mb, mirror_mb) are to be used. (options_version 7)
/// There is no preset any more: false, the card's own sizes
bool preset_caps_memory();

void menu_init();             // (the options from the file, once)
/// (Triforce, 11-22, the performance audit's PRESENT-46) With RX_VK_FIRST_START_AUTO, a first start (no options file) on a
/// weak card sets the Render resolution row; once, after the device is made (first_start.h)
void menu_first_start();
void menu_set_gpu_count(int count);
/// ((Triforce) 11-20) the GPU device row's card by its name, as triforce_options.ini's gpu_device_name had it (empty: none
/// saved): vk_main.cpp pick_device finds the card by it first (gpu_choice.h pick)
const std::string& menu_gpu_name();
void menu_tick();             // (each frame shown: the keys, while the game's window has the focus)
bool menu_is_open();
int menu_grass_distance();    // ((Triforce) the Grass distance row as now, for the recording threads: opts.grass_distance read atomically)
bool resolution_auto();       // (the game's dynamic resolution: Resolution Auto)
int resolution_scale();       // (the fixed path's scale in 1/10000: the Resolution row's, as a twelfth of the output)
void menu_option_set(int id, int value);   // (from the game's side: 7 the mouse's sensitivity, the - and = keys)
int menu_setting(int index, MkwVkSetting* out);   // ((Triforce) the control bridge, host/control.c: the rows with a value)
int menu_setting_set(const char* key, int value, MkwVkSetting* out);
int menu_heart_protection();
int menu_player_flight();
int menu_free_camera();
/// (Triforce) The Debug tab's Movement speed tool, percent of Link's own speed: 100 while the tools are off
int menu_link_speed();
int menu_take_cheat_action();
/// (Triforce) What a row of the System tab asked the host to do since the last call: HOS_SHARE_* (vk_api.h), 0 nothing
int menu_take_share_ask();
/// (Triforce) The next byte of a line the Debug tab's name pages wait to send (gpu/vk/oot_debug_link.h), a line feed at a
/// line's end, 0 while none waits: the Game flags' and the Cutscenes' (HOS_OPT_DEBUG_ASK), and the Scan amiibo page's file
/// name (HOS_OPT_AMIIBO_ASK)
int menu_take_debug_ask();
int menu_take_amiibo_ask();
int menu_vibration_status_option();   // ((Triforce) 11-24) what plays the controller used last (HOS_OPT_VIBRATION_STATUS)
/// (Triforce) A cheat of a mod's cheat file the player switched on the System tab since the last call: (its row + 1) * 2, plus 1
/// for on; 0 nothing (vk_api.h HOS_OPT_MODCHEAT_ASK, mod_cheat_rows.h)
int menu_take_mod_cheat();
/// (Triforce) The save file the player chose to play that is not this run's, its number (1 the first), since the last call; 0
/// none (vk_api.h HOS_OPT_FILES_ASK, save_file_rows.h)
int menu_take_file_ask();
/// (Triforce) The next of the options' own sounds asked for since the last call, HOS_MENU_SOUND_* (vk_api.h), 0 none: for the
/// host's sound thread alone (HOS_OPT_MENU_SOUND; menu_sound_events.h's queue, host/menu_sound.c)
int menu_take_sound();
/// (Triforce) 1 while the Mods entry under a game list has the cursor, or its screen is open (HOS_OPT_MODS_SELECTED: the
/// host lets the game's own cursor go then, host/oot_menu.c)
int menu_mods_selected();
/// ((Triforce, 11-20) the Mods screen's music: 0 none, 1 the title's list is there (the tune read ahead), 2 the Mods screen
/// is open from the title's list (HOS_OPT_MODS_MUSIC, host/mods_music.c)
int menu_mods_music();
/// (Triforce) 1 while the Mods screen's search takes typed text (HOS_OPT_TEXT_WANTED: host/display.c sends it then)
int menu_text_wanted();
int menu_hud_option(int id);   // ((Triforce) the HUD placement rows for host/hos_wide_ui.c: HOS_OPT_HUD_PLACEMENT to HOS_OPT_HUD_MINIMAP)
/// (Triforce) What became of the picture a bug capture asked for (vk_bugshot.h bugshot_state): 0 none asked, 1 not there yet,
/// 2 written, 3 no picture
int menu_bug_shot();
/// ((Triforce) 11-24) A bug capture's settings changed from the defaults (HOS_OPT_BUG_SETTINGS): begin writes them down
/// (option_set 1), take gives the next byte of them, 0 at their end (option). Any thread: the capture's (host/bug_capture.c)
void menu_bug_settings_begin();
int menu_take_bug_settings();
void menu_note_frame(bool game_frame, int shown = 1);   // (the frame rates the FPS counter shows)
void menu_auto_tune(double gpu_ms, double draws, double fps);
void menu_fps_render_thread(int64_t work_ns, int64_t wait_ns);   // ((Triforce) a render thread's frame: the FPS counter's Breakdown lane   // ((Triforce) Auto (this PC)'s tuning: the replay's 120-present windows   // (the frame rates the FPS counter shows)
/// The game's picture's size (the Output resolution, its crop) and the window's, at each present: ((Triforce, options_version
/// 7) the filter the picture is scaled to its place in the window with follows them (opts.upscale, upscaler_rows.h auto_filter)
void menu_note_present_sizes(uint32_t picture_w, uint32_t picture_h, uint32_t window_w, uint32_t window_h);
/// Over the window's image `index` (TRANSFER_DST_OPTIMAL before and after), w x h: the start-up screen, the menu and the FPS
/// counter, drawn with Dear ImGui (vk_imgui.h, vk_ui.h). Nothing recorded while none of them shows
void menu_record(VkCommandBuffer cmd, uint32_t index, uint32_t w, uint32_t h);
/// ((Triforce, 11-22, N64 Classic, after the owner's test) From N64 Classic's TV pass, before it draws (vk_framegen.cpp
/// framegen_scale): while the options' own screens show (the menu open, our tabs over the game's Options screen, the Mods
/// entry), this present's overlays are drawn now, the options into a layer of the picture's place that the TV takes in
/// with the game's picture (vk_imgui.h record_layer), so they bend, scan and bleed as the game's own screens under them do;
/// menu_record then draws the rest over the window, flat (the FPS counter). Null: nothing of the options this present, or
/// no layer; menu_record draws as before. RX_VK_N64_TV_MENU=0: never (the options over the TV, flat, as before)
VkImageView menu_tv_layer(VkCommandBuffer cmd);
/// (headless shots, RX_VK_SHOT_MENU) The menu and the counter over another image: TRANSFER_DST_OPTIMAL before and after,
/// R8G8B8A8_UNORM with colour-attachment use, view a view of it
void menu_record_image(VkCommandBuffer cmd, VkImage image, VkImageView view, uint32_t w, uint32_t h);
/// (hookshot) The start-up screen while the shaders are prepared (vk_main.cpp, vk_progress.h), drawn by menu_record under the
/// counter and the menu. Null takes it away.
struct StartupView;
void startup_screen(const StartupView* view);
/// The start-up screen's fade to black as it ends: 0 none, 1 black (vk_main.cpp prepare_with_screen)
void startup_fade_to(float f);

} // namespace mkwvk
