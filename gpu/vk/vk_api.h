/* The Vulkan back end (mkw_vk.dll) and the game executable: what each gives the other.

   The executable records the game's NVN command buffers (host/nvn_native.c) and calls a renderer through the rx_*
   functions (gpu/render/rx_nvn.h). With RX_BACKEND=vulkan host/rx_backend.c loads mkw_vk.dll, hands it the host
   functions below and routes the rx_* calls to the table it returns; otherwise they go to the WebGPU renderer in
   the executable. The DLL carries Eden's shader recompiler (gpu/vk/eden, SPIR-V back end) and sirit: their C++
   namespaces are the same as those of the WebGPU renderer's suyu copy, so the two live in different binaries. */
#pragma once

#include <stdint.h>

#include "../render/rx_nvn.h"   /* (the NVN objects and command records: C) */

#ifdef __cplusplus
extern "C" {
#endif

/* ((Triforce, 11-22) 16: MkwVkRenderer's screen_point, N64 Classic's TV's curve for the game's own menus' mouse. 11-23: 19, as
   ultrawide's screens and wide_backdrop (16, 17, 18 on its own line) came first on next/update. 11-24: 20 to 23, batches of
   the same day: MkwVkHost's playback devices (audio_output_*) and the microphone's test (mic_test); MkwVkRenderer's control
   bridge functions, frame_info to setting_set; MkwVkHost's prompts_live, reset_binding, rebind_control and binding_is_default
   at its end (the live button prompts, the Controls page's per-control reset and confirmed rebinds); MkwVkRenderer's
   jitter_sample, the camera jitter's one whole sample; MkwVkRenderer's nvn_program_created at its end, the load of a
   program at its create call (RX_VK_LOAD=create). 25: all of them together */
#define MKWVK_API_VERSION 25
enum { HOS_OPT_CHEAT_HEARTS = 32, HOS_OPT_CHEAT_FLIGHT, HOS_OPT_CHEAT_ACTION, HOS_OPT_CHEAT_CAMERA };
/* (hookshot) the Motion page's rows (host/pad_sdl.c reads them, vk_replay.cpp's option answers them): Motion controls on
   or off, the horizontal's and the vertical's sensitivity in percent, each turned around, and the deadzone (0 to 2) */
enum { HOS_OPT_GYRO = 18, HOS_OPT_GYRO_SENS_X, HOS_OPT_GYRO_INV_X, HOS_OPT_GYRO_INV_Y, HOS_OPT_GYRO_SENS_Y, HOS_OPT_GYRO_DEADZONE };
/* (hookshot) NVIDIA DLSS's camera jitter (host/rx_backend.c, gpu/vk/vk_dlss.cpp): the scene's width and height while DLSS
   draws, 0 when there is to be no jitter, and the jitter sequence's length. 24 on: 18 to 23 are the motion rows' */
enum { HOS_OPT_DLSS_JITTER_W = 24, HOS_OPT_DLSS_JITTER_H, HOS_OPT_DLSS_JITTER_PHASES };
/* (hookshot) the Insert menu's HDR set to Native (host/nn_vi.c QueryDisplayHdrStatus and QueryDisplayHdrPaperWhite): whether
   the game is told its display is HDR10 (the swapchain is one), and the peak and paper white it is told, in nits */
/* (HOS_OPT_DISCORD, 43: the Insert menu's Discord status row, host/discord_rpc.c: 1 on) */
/* (HOS_OPT_SPRINT, 45, and HOS_OPT_SPRINT_HOLD, 46: the Sprint button row (0 off, 1 the left stick's click, 2 B) and
   the Sprint mode row (0 toggle, 1 hold), host/oot_sprint.c) */
/* (HOS_OPT_VOLUME, 44: the Insert menu's Master volume row, host/nn_audio.c: percent of the game's own, 0 to 100) */
enum { HOS_OPT_HDR_NATIVE = 40, HOS_OPT_HDR_PEAK, HOS_OPT_HDR_WHITE, HOS_OPT_DISCORD, HOS_OPT_VOLUME, HOS_OPT_SPRINT, HOS_OPT_SPRINT_HOLD };
/* (Triforce) option_set only, each frame the game's own Options screen runs (host/oot_menu.c): the menu then draws its tabs
   over that screen's header, the game's own list the first of them (gpu/vk/vk_menu.cpp game_options_shown) */
/* (Triforce) HOS_OPT_EXITING, option_set only: the process is about to exit (host/hos_relaunch.c): what must be shut
   down in order before the DLLs are unloaded is (NVIDIA's Streamline, gpu/vk/vk_dlssg.cpp) */
enum { HOS_OPT_GAME_OPTIONS = 48, HOS_OPT_EXITING };
/* (Triforce) HOS_OPT_DISPLAY_CAP: the frame rate cap the display the window is on gives, for the Insert menu's Game frame
   rate cap on Monitor's rate (host/nn_vi.c fps_max, gpu/vk/fps_cap.h): its refresh rate rounded, 30 to 240; 0 when the
   rate cannot be read. 60 to 69 are the display, graphics and system rows' */
enum { HOS_OPT_DISPLAY_CAP = 60 };
/* ((Triforce, 11-22, N64 Classic, step 7) HOS_OPT_N64_FPS: the frame rate N64 Classic asks the host to pace the game at
   (gpu/vk/n64_rules.h fps: Faithful's 20, the Remembered page's row; 0 none: the cap's), asked once a present
   (host/nn_vi.c n64_pace_decide, host/n64_pace.h) */
enum { HOS_OPT_N64_FPS = 61 };
/* (Triforce) The System tab's save rows (gpu/vk/vk_menu.cpp), whose work the host does on a thread of its own
   (host/save_share.c): HOS_OPT_SHARE_ASK, option: what a row asked for since the last read, HOS_SHARE_*, 0 nothing (taken:
   the next read answers 0). HOS_OPT_SHARE_TEXT, option_set: the next byte of a line for the menu, UTF-8, and
   HOS_OPT_SHARE_SAID, option_set: the bytes sent so far are the line the row of that HOS_SHARE_* shows under its help
   (HOS_SHARE_NOTICE: the line at the foot of the screen for a moment, while the options are closed).
   HOS_OPT_SHARE_IMPORT, option_set: 1 while an imported save waits for the next start (the Import row then cancels it).
   The bug capture (host/bug_capture.c, F8 or its row: HOS_SHARE_CAPTURE; HOS_SHARE_CAPTURE_KEY is F8 where the window
   has no key handler of the host's, Linux) asks for its picture with HOS_OPT_BUG_SHOT, option_set: 1 the frame shown next
   is written as captures/frame-pending.png in the game folder (gpu/vk/vk_bugshot.cpp), 0 asked no longer; option: 0 none
   asked, 1 not there yet, 2 written, 3 no picture */
enum { HOS_OPT_SHARE_ASK = 70, HOS_OPT_SHARE_TEXT, HOS_OPT_SHARE_SAID, HOS_OPT_SHARE_IMPORT, HOS_OPT_BUG_SHOT };
enum { HOS_SHARE_EXPORT = 1, HOS_SHARE_EXPORT_BUG, HOS_SHARE_IMPORT, HOS_SHARE_IMPORT_CANCEL, HOS_SHARE_CAPTURE, HOS_SHARE_CAPTURE_KEY,
       HOS_SHARE_NOTICE };
/* (Triforce) The Debug tab's name pages (gpu/vk/vk_menu.cpp; gpu/vk/oot_debug_link.h has the lines). HOS_OPT_DEBUG_ASK, option:
   the next byte of a line the Game flags or the Cutscenes page asks of the game's side (host/hos_main.c reads it on the
   game's thread, at Link's update), a line feed at a line's end, 0 while there is none. HOS_OPT_DEBUG_TEXT, option_set: the
   next byte of a line for the pages, and HOS_OPT_DEBUG_SAID, option_set: the bytes sent so far are a line of that kind
   (OOT_SAID_*). HOS_OPT_AMIIBO_ASK, option: the same for the Scan amiibo page, the name of a file of the game folder's
   amiibo folder, or a line of its own for none (host/nn_nfp.c reads it at the game's pad read). HOS_OPT_AMIIBO_SAID,
   option_set: what became of the figure, HOS_AMIIBO_* (host/amiibo.h's NFP_SAID_*): none chosen, waiting for the game to
   look for a figure, on the reader, read by the game and lifted off, the file is not a figure's dump, the file is not
   there */
enum { HOS_OPT_DEBUG_ASK = 115, HOS_OPT_DEBUG_TEXT, HOS_OPT_DEBUG_SAID, HOS_OPT_AMIIBO_ASK, HOS_OPT_AMIIBO_SAID };
enum { HOS_AMIIBO_NONE, HOS_AMIIBO_WAITING, HOS_AMIIBO_ON_READER, HOS_AMIIBO_READ, HOS_AMIIBO_REFUSED, HOS_AMIIBO_NO_FILE };
/* (Triforce) The game's frame pacing beside other limiters (host/nn_vi.c hos_vi_native_acquire, gpu/vk/vk_pace.cpp), on the
   game's presenting thread where its frame starts, once a frame. HOS_OPT_PACE_PERIOD, option_set: the period the host
   paces the frame by, in nanoseconds (the frame rate cap in effect). HOS_OPT_PACE_MOVIE, option_set: 1 while a movie
   plays (the game's own wait holds a movie). HOS_OPT_PACE_START, option, right after them: 0 the host's own wait paces
   this frame, as without a renderer to ask; 1 another limiter holds it and the host's wait steps aside for this frame
   (RivaTuner Statistics Server, which holds the frame's presents, or NVIDIA Reflex with DLSS frame generation, whose
   sleep is taken inside the call). 85 to 89 are pacing's.
   (Triforce) HOS_OPT_PACE_STEADY, the Steady frame rate row (host/pace_steady.h): option_set, after the period, 1 while the
   period told is the steady frame rate's (the present then holds the game's pictures to it: gpu/vk/present_smooth.h
   present_smooth_paced_at), 0 otherwise; option, the microseconds the present held the game's presenting thread for it since
   the last ask (what the frames needed is measured without that wait) */
enum { HOS_OPT_PACE_PERIOD = 85, HOS_OPT_PACE_START, HOS_OPT_PACE_MOVIE, HOS_OPT_PACE_STEADY };

/* (hookshot) the controls' names (host/nn_hid.c, host/pad_sdl.c, the pad_ and key_ lines of triforce_options.ini):
   the Switch's buttons in nn::hid's bit order, and a gamepad's inputs by position, SDL's order (the bottom face
   button first: A on an Xbox pad, cross on a DualSense) */
enum { HOS_SW_A, HOS_SW_B, HOS_SW_X, HOS_SW_Y, HOS_SW_LS, HOS_SW_RS, HOS_SW_L, HOS_SW_R, HOS_SW_ZL, HOS_SW_ZR,
       HOS_SW_PLUS, HOS_SW_MINUS, HOS_SW_LEFT, HOS_SW_UP, HOS_SW_RIGHT, HOS_SW_DOWN, HOS_SW_N };
enum { HOS_PAD_SOUTH, HOS_PAD_EAST, HOS_PAD_WEST, HOS_PAD_NORTH, HOS_PAD_BACK, HOS_PAD_GUIDE, HOS_PAD_START,
       HOS_PAD_LSTICK, HOS_PAD_RSTICK, HOS_PAD_LSHOULDER, HOS_PAD_RSHOULDER, HOS_PAD_UP, HOS_PAD_DOWN, HOS_PAD_LEFT,
       HOS_PAD_RIGHT, HOS_PAD_LTRIGGER, HOS_PAD_RTRIGGER, HOS_PAD_N };
/* ((Triforce) 11-17) the left stick pushed past half its travel, in the menus' pad bits only (host/nn_hid.c hos_pad_raw):
   the overlay's lists move by the stick as by the D-pad. Past HOS_PAD_N, so no binding takes them */
enum { HOS_PAD_LS_UP = 20, HOS_PAD_LS_DOWN, HOS_PAD_LS_LEFT, HOS_PAD_LS_RIGHT,
       HOS_PAD_RS_UP, HOS_PAD_RS_DOWN };   /* (and the right stick up or down: the Mods screen's description scrolls by it) */
/* ((Triforce) 11-24) the rear paddles (a Steam Controller's, an Xbox Elite's, a DualSense Edge's: SDL's paddle buttons, R4
   L4 R5 L5), inputs a binding can take: past the sticks' menu bits, 20 to 25, as HOS_PAD_N stays the inputs with an icon of
   their own (host/prompts.c: a paddle shows its Switch button's default icon). hos_pad_bindable: an input a binding takes;
   HOS_PAD_BIND_MASK their bits */
enum { HOS_PAD_RPADDLE1 = 26, HOS_PAD_LPADDLE1, HOS_PAD_RPADDLE2, HOS_PAD_LPADDLE2 };
#define hos_pad_bindable(hos_pad_input_) (((hos_pad_input_) >= 0 && (hos_pad_input_) < HOS_PAD_N) || ((hos_pad_input_) >= HOS_PAD_RPADDLE1 && (hos_pad_input_) <= HOS_PAD_LPADDLE2))
enum { HOS_PAD_BIND_MASK = ((1 << HOS_PAD_N) - 1) | (15 << HOS_PAD_RPADDLE1) };
/* a DualShock 4's or DualSense's touchpad click, which opens the Insert menu as F1 does with the Menu shortcut row's touchpad
   choices (host/pad_sdl.c, gpu/vk/vk_menu.cpp): a menu bit of its own past HOS_PAD_N and the sticks' bits, so no binding
   takes it */
enum { HOS_PAD_TOUCHPAD = 30 };
enum { HOS_BIND_PAD, HOS_BIND_KEY };
/* ((Triforce) 11-24) The Audio tab's Output device row (host/audio_output_devices.h): an endpoint id's and a device name's room,
   with their ends, and what the sound's thread has open (MkwVkHost audio_output_state): HOS_OUTPUT_FALLBACK the default
   stands in for the device chosen (not there now, or it took no sound), HOS_OUTPUT_OVERRIDE HOS_AUDIO_DEVICE chose it for
   this run, HOS_OUTPUT_UNAVAILABLE none could be opened */
#define HOS_OUTPUT_ID_CAP 200
#define HOS_OUTPUT_NAME_CAP 256
enum { HOS_OUTPUT_FALLBACK = 1, HOS_OUTPUT_OVERRIDE = 2, HOS_OUTPUT_UNAVAILABLE = 4 };
/* ((Triforce) 11-24) The Test microphone row's state (MkwVkHost mic_test): testing, the microphone open, the default standing
   in for the chosen one, samples within the last 250 ms, clipped within the last second, the Microphone row Off */
enum { HOS_MIC_TEST_ON = 1, HOS_MIC_TEST_OPEN = 2, HOS_MIC_TEST_STANDIN = 4, HOS_MIC_TEST_FRESH = 8, HOS_MIC_TEST_CLIP = 16,
       HOS_MIC_TEST_OFF = 32 };
/* (hookshot) the controller faces of the button prompts (host/prompts.c): the Switch, then nx2/prompt_faces.py FACES' order;
   the Button prompts row's value is one more (0 Auto). (Triforce) HOS_PROMPT_KEYBOARD: the keyboard and mouse, no
   controller's: each button's icon is the key or the mouse button bound to it (nx2/prompt_keys.py) */
enum { HOS_PROMPT_SWITCH, HOS_PROMPT_XBOX, HOS_PROMPT_PS4, HOS_PROMPT_PS5, HOS_PROMPT_STEAMDECK, HOS_PROMPT_KEYBOARD, HOS_PROMPT_N };
/* ((Triforce) 23) what of the button prompts follows a new face or new controls at once (MkwVkHost.prompts_live, a bit
   each): the textures (the ocarina's notes, the Talk ring's letters, the System page's controller), the layouts (the Talk
   ring's places, the ocarina hint's spacing), the icons in texts; the rest at the next start. HOS_OPT_PROMPTS: the Button
   prompts row as it is now (host/prompts.c live_face: 0 Auto, else HOS_PROMPT_* + 1) */
enum { HOS_PROMPTS_LIVE_TEXTURES = 1, HOS_PROMPTS_LIVE_LAYOUTS = 2, HOS_PROMPTS_LIVE_TEXTS = 4, HOS_PROMPTS_LIVE_ALL = 7 };
enum { HOS_OPT_PROMPTS = 326 };
/* keys only (HOS_BIND_KEY), after the Switch's buttons: the left stick's and the camera's directions; then
   ((Triforce) 11-24) the ocarina's five note controls, which take a gamepad input too (HOS_BIND_PAD, slot 0) and
   share their inputs: a note's key or gamepad input can be some other control's at once (host/nn_hid.c oc_notes).
   No new function and no change to an old one's arguments, so MKWVK_API_VERSION stays: a host without the rows
   answers -1 and 0 for them */
enum { HOS_KEY_MOVE_UP = HOS_SW_N, HOS_KEY_MOVE_DOWN, HOS_KEY_MOVE_LEFT, HOS_KEY_MOVE_RIGHT, HOS_KEY_CAM_UP,
       HOS_KEY_CAM_DOWN, HOS_KEY_CAM_LEFT, HOS_KEY_CAM_RIGHT, HOS_KEY_OC_NOTE_L, HOS_KEY_OC_NOTE_R,
       HOS_KEY_OC_NOTE_A, HOS_KEY_OC_NOTE_Y, HOS_KEY_OC_NOTE_X,
       HOS_KEY_TOGGLE_HUD,
       HOS_KEY_N };
/* ((Triforce) HOS_KEY_TOGGLE_HUD, the Controls page's Toggle HUD row: hides or shows the HUD in play at a press
   (host/hos_wide_ui.c hos_gameplay_hud_toggle), unbound out of the box; a gamepad input and two keys, which are its alone
   while it has them (host/nn_hid.c hud_shortcut) */
/* (Triforce) more of the Controls tab's rows, after NX2navi's (host/pad_sdl.c and host/nn_hid.c read them, vk_replay.cpp's
   option answers them; 50 to 59 are theirs). HOS_OPT_RUMBLE_CURVE: the Vibration curve, the power on the motors' rumble
   in hundredths, 20 to 150, 100 none. HOS_OPT_RUMBLE_TRIGGERS: Trigger vibration, 1 the rumble in an Xbox pad's triggers
   too. HOS_OPT_LSTICK_ZONE, HOS_OPT_RSTICK_ZONE: the left and the right stick's own dead zone, one more than the row's
   value: 0 none (As Stick dead zone), 1 to 51 for 0% to 50% (host/nn_hid.c hos_stick_own). HOS_OPT_WALK_KEY: the Walk
   key row, 0 Off, 1 Caps Lock, 2 Shift, 3 Ctrl, 4 Tab (host/nn_hid.c walk_key_code). HOS_OPT_WALK_SCALE: how far the
   movement keys push the left stick while it is held, in hundredths, 20 to 90 */
enum { HOS_OPT_RUMBLE_CURVE = 50, HOS_OPT_RUMBLE_TRIGGERS, HOS_OPT_LSTICK_ZONE, HOS_OPT_RSTICK_ZONE, HOS_OPT_WALK_KEY,
       HOS_OPT_WALK_SCALE };
/* ((Triforce) 11-24, the controller batch) the Controls tab's Vibration (host/vibration.h, host/pad_sdl.c reads them by
   number each poll; the existing option callback: no new member). HOS_OPT_VIBRATION: 0 Auto (the best each controller can
   do: with RenHDrum beside the game a DualSense's voice coils, an Xbox pad's four motors, a Switch pad's HD rumble made by
   RenHDrum; without it a Switch pad's own HD rumble, every other pad's motors, as before), 1 Basic (every pad's motors), 2
   Off. HOS_OPT_DS_HD_HAPTICS: 1 (the default) a DualSense that RenHDrum plays taps its speaker and kicks back its held
   L2/R2 from the game's vibration too; 0 its voice coils only. HOS_OPT_VIBRATION_STATUS: what plays the controller used
   last, written back by the host each poll (host/vibration.h: its kind times 16, plus VIB_SAY_*); the Vibration row's help
   line reads it */
enum { HOS_OPT_VIBRATION = 320 };
enum { HOS_OPT_DS_HD_HAPTICS = 321 };
enum { HOS_OPT_VIBRATION_STATUS = 322 };
/* ((Triforce) 11-24, the controller batch) the Audio tab's Controller speaker rows (host/pad_speaker.c reads them once a
   second by number; the existing option callback: no new member), three numbers for its sixteen rows.
   HOS_OPT_PAD_SPEAKER_CLASSES: where each kind of sound plays, two bits each, host/audio_source.h's classes from Navi's voice
   (bits 0-1) on: 0 Off (the game's output alone, the default for all), 1 the controller only, 2 the controller and the TV.
   HOS_OPT_PAD_SPEAKER_LEVELS: the speaker's volume in percent (0 to 200, bits 0-7), the Controller sync plus 100 (-100 to
   150 ms, bits 8-15: above 0 the pad waits, below 0 the TV's copy of the Controller + TV sounds does) and the headphones'
   volume in percent (0 to 100, bits 16-23). HOS_OPT_PAD_SPEAKER_HEADPHONES: Headphones on the controller, 0 Off (the
   default), 1 the controller's sounds there, 2 all sound there (the TV silent) */
enum { HOS_OPT_PAD_SPEAKER_CLASSES = 323 };
enum { HOS_OPT_PAD_SPEAKER_LEVELS = 324, HOS_PAD_SPEAKER_LEVELS_DEFAULT = 100 | (100 << 8) | (80 << 16) };
enum { HOS_OPT_PAD_SPEAKER_HEADPHONES = 325 };
enum { HOS_PAD_SPEAKER_CLASS_ROWS = 12 };
/* (Triforce) The System tab's rows for the cheats of the mods' cheat files (host/mod_cheats.c runs them, gpu/vk/vk_menu.cpp
   and gpu/vk/mod_cheat_rows.h show them; 130 to 134 are theirs, 134 not used). At the first frame the host names its
   cheats, in the rows' order: HOS_OPT_MODCHEAT_TEXT, option_set: the next byte of a cheat's name, UTF-8, then a line feed
   and the line the row shows under its help; HOS_OPT_MODCHEAT_ADD, option_set: the bytes sent so far are the next row's,
   the value its HOS_MODCHEAT_* bits; HOS_OPT_MODCHEAT_COUNT, option_set: the list is whole, the rows are shown (0: none).
   HOS_OPT_MODCHEAT_ASK, option: a switch the player changed since the last read, (its row + 1) * 2 + 1 for on, + 0 for
   off; 0 nothing (taken: the next read answers the next change, or 0) */
enum { HOS_OPT_MODCHEAT_TEXT = 130, HOS_OPT_MODCHEAT_ADD, HOS_OPT_MODCHEAT_COUNT, HOS_OPT_MODCHEAT_ASK };
enum { HOS_MODCHEAT_ON = 1,       /* switched on */
       HOS_MODCHEAT_ALWAYS = 2,   /* a master code: always runs, the row cannot be changed */
       HOS_MODCHEAT_REFUSED = 4   /* cannot run here (the row's line says why): the row cannot be changed */ };
/* (Triforce) The options' own sounds, the game's interface sounds, after NX2navi's menu sounds (gpu/vk/vk_menu.cpp and
   gpu/vk/menu_sound_events.h say which, host/menu_sound.c plays them; 135 to 139 are theirs). HOS_OPT_MENU_SOUND, option:
   the next sound the options asked for, HOS_MENU_SOUND_*, 0 none (taken: the next read answers the one after it). Read
   by the host's sound thread alone, at each block it mixes, so a sound starts within one block of its press.
   HOS_OPT_MENU_SOUND_VOLUME, option: the Audio tab's Menu sounds row, percent, 0 to 100 (0: silent) */
enum { HOS_OPT_MENU_SOUND = 135, HOS_OPT_MENU_SOUND_VOLUME };
enum { HOS_MENU_SOUND_OPEN = 1, HOS_MENU_SOUND_CLOSE, HOS_MENU_SOUND_CURSOR, HOS_MENU_SOUND_DECIDE, HOS_MENU_SOUND_CANCEL,
       HOS_MENU_SOUND_TAB_LEFT, HOS_MENU_SOUND_TAB_RIGHT,
       HOS_MENU_SOUND_FANFARE,   /* ((Triforce) a mod installed from the Mods screen: the game's item-get fanfare) */
       /* ((Triforce) 11-17) the Mods entry under the game's lists sounds as those lists do: the system menu's cursor and its
          "decide" (the title's Continue, the Load list's choice: the lab's file opens, HOS_FS_TRACE) */
       HOS_MENU_SOUND_SYS_CURSOR, HOS_MENU_SOUND_SYS_DECIDE,
       HOS_MENU_SOUND_N };
/* (Triforce) The Mods entry under a game list's last button (host/oot_menu.c tells, gpu/vk/vk_menu.cpp draws it): the pause
   menu's System page and the title's list. Each frame such a list runs, option_set: HOS_OPT_MODS_X0 .. HOS_OPT_MODS_Y1 its
   last button's box in the layout's units (3840 x 2160, the origin at the middle, y up), HOS_OPT_MODS_PITCH the distance to
   the button above it, then HOS_OPT_MODS_LIST: HOS_MODS_LIST_* bits (that frame's report is whole). HOS_OPT_MODS_ENTER,
   option_set: the cursor goes onto Mods (1: the game's Down there, which the game is not given, host/nn_hid.c), or Mods was
   clicked (2: open it; (Triforce, 11-19) 3: Quit under it clicked, its dialog opens; 4: the mouse moved onto Quit; 5: a Down
   held from higher up the list, its repeat onto Mods, which repeats on at the step; on the title, while the save files are on, the entry under Mods is Save Select, host/save_files.c, and 3 and 4 are its). HOS_OPT_MODS_SELECTED, option: 1 while the cursor is on Mods or its screen is open (the game gets
   no input then: host/nn_hid.c). HOS_OPT_MODS_PRESS, option_set: presses the game was given meanwhile that are the menu's (a
   test's scripted ones, which reach no window): HOS_MODS_PRESS_* bits. ((Triforce, 11-19) with HOS_MODS_REPORT, each read's
   report: also the directions held then, HOS_MODS_PRESS_DIRS bits shifted by HOS_MODS_HELD_SHIFT, which the menu repeats
   as it repeats a pad's held direction) */
enum { HOS_OPT_MODS_LIST = 150, HOS_OPT_MODS_X0, HOS_OPT_MODS_X1, HOS_OPT_MODS_Y0, HOS_OPT_MODS_Y1, HOS_OPT_MODS_PITCH, HOS_OPT_MODS_ENTER,
       HOS_OPT_MODS_SELECTED, HOS_OPT_MODS_PRESS };
enum { HOS_MODS_LIST_SHOWN = 1, HOS_MODS_LIST_LAST_FOCUSED = 2, HOS_MODS_LIST_TITLE = 4 };
enum { HOS_MODS_PRESS_UP = 1, HOS_MODS_PRESS_DOWN = 2, HOS_MODS_PRESS_LEFT = 4, HOS_MODS_PRESS_RIGHT = 8, HOS_MODS_PRESS_A = 16,
       HOS_MODS_PRESS_B = 32, HOS_MODS_PRESS_L = 64, HOS_MODS_PRESS_R = 128, HOS_MODS_PRESS_DIRS = 15, HOS_MODS_HELD_SHIFT = 8,
       HOS_MODS_REPORT = 4096 };
/* ((Triforce) 11-17) Text typed into the menu (the Mods screen's search). HOS_OPT_TEXT_WANTED, option: 1 while the menu takes
   text. HOS_OPT_TEXT_CHAR, option_set (the window's thread, host/display.c): a code point typed, or 8 Backspace, 127
   Ctrl+Backspace (a pasted text comes as its characters) */
enum { HOS_OPT_TEXT_CHAR = 159, HOS_OPT_TEXT_WANTED };
/* ((Triforce) 11-20) The Mods screen's music (host/mods_music.c). HOS_OPT_MODS_MUSIC, option: 0 none; 1 the title's list
   is there with its Mods entry (the tune is read from the game's files ahead of its use); 2 the Mods screen is open from
   the title's list: the game's shop theme plays quietly and the game's own sound, the title's music, is faded out
   under it, and back when the screen shuts */
enum { HOS_OPT_MODS_MUSIC = 161 };
/* ((Triforce) 11-20) The Mods entry with the game's own buttons, not by a clock of its own. HOS_OPT_MODS_ALPHA,
   option_set: how much of the list's last button the game shows this frame, in thousandths (0 to 1000: the button's own
   alpha as the game animates it, host/oot_menu.c), told before that frame's HOS_OPT_MODS_LIST. A HOS_OPT_MODS_LIST without
   HOS_MODS_LIST_SHOWN says that the list is there no longer for the entry (another screen has the game's cursor): the
   entry goes at once, as the game's buttons did */
enum { HOS_OPT_MODS_ALPHA = 162 };
/* (Triforce) Achievements (host/achievements.c keeps them, on unless HOS_ACHIEVEMENTS=0; gpu/vk/vk_menu.cpp and
   gpu/vk/achievement_rows.h show them: the System tab's Achievements page, and a notice when one is earned; 165 to 169 are
   theirs). HOS_OPT_ACH_ASK, option: 1 from a renderer that shows them. Once it answers the host names its list, in the list's
   order: HOS_OPT_ACH_TEXT, option_set: the next byte of an achievement's name, UTF-8, then a line feed and the line about it,
   then a line feed and the day it was earned when it was; HOS_OPT_ACH_ADD, option_set: the bytes sent so far are the next
   achievement's, the value its icon (0 to 255, host/achievements.h ach_icon) and HOS_ACH_EARNED when it is earned;
   HOS_OPT_ACH_COUNT, option_set: the list is whole (0: none). HOS_OPT_ACH_EARNED, option_set: the achievement at that place
   in the list was earned now, the bytes sent so far the day: the notice shows it. One at a time, the host waits between two */
enum { HOS_OPT_ACH_TEXT = 165, HOS_OPT_ACH_ADD, HOS_OPT_ACH_COUNT, HOS_OPT_ACH_EARNED, HOS_OPT_ACH_ASK };
/* ((Triforce) 11-23: the System tab's Achievements group. HOS_OPT_ACH_ON, option: 1 while its Achievements row is On (0:
   nothing is asked of the save data and nothing earned, at once). HOS_OPT_ACH_NOTICES, option: 1 while its Achievement
   notices row is On (0: what is earned is told to the list without the notice's sound, and the menu shows no notice).
   185 and 186: 170 is the bench's helper test, 180 to 184 the save files) */
enum { HOS_OPT_ACH_ON = 185, HOS_OPT_ACH_NOTICES };
enum { HOS_ACH_EARNED = 256 };
/* ((Triforce) 11-22) The benchmark's helper-thread test (host/hos_bench.c, HOS_BENCH_HELPERS=1). HOS_OPT_HELPERS_FORCE,
   option_set: 0 the replay thread alone, 1 the replay helper threads in use, -1 the tuner decides again (gpu/vk/replay_threads.h),
   each from the next present on; option: the helper threads such a test can use, 0 where it cannot (the Debug tab's row Off,
   RX_VK_PARALLEL, or a PC Automatic gives none) */
enum { HOS_OPT_HELPERS_FORCE = 170 };
/* (Triforce) Save files (host/save_files.c keeps them, on unless HOS_SAVE_FILES=0; gpu/vk/vk_menu.cpp and
   gpu/vk/save_file_rows.h show them: the file select at the title, and the System tab's Save files row; 180 to 184 are
   theirs; 170 is the bench's helper test). HOS_OPT_FILES_ASK, option: the file the player chose to play that is not this run's, its number (1 the first; taken:
   the next read answers 0), 0 none; a renderer that shows them answers 0 and more. Once it answers the host names the
   files, in their order: HOS_OPT_FILES_TEXT, option_set: the next byte of a file's name, UTF-8, then a line feed and when it
   was last saved (nothing: no save in it yet); HOS_OPT_FILES_ADD, option_set: the bytes sent so far are the next file's, the
   value its HOS_FILE_* bits; HOS_OPT_FILES_COUNT, option_set: the list is whole, the value how many, and HOS_FILES_CHOSEN when
   this start follows a choice (the game restarted for it). HOS_OPT_FILES_SAID, option_set: what became of the file asked
   for: 1 it is the next start's (the menu restarts the game), 2 it could not be kept (nothing changes) */
enum { HOS_OPT_FILES_TEXT = 180, HOS_OPT_FILES_ADD, HOS_OPT_FILES_COUNT, HOS_OPT_FILES_ASK, HOS_OPT_FILES_SAID };
/* ((Triforce) 11-24: input rows of the Controls tab, 190 to 199 theirs. HOS_OPT_MOUSE_INVERT_X, option: its Invert mouse
   horizontal row, 1 on: the mouse's left and right swapped, as option 8, Invert mouse vertical, swaps its up and down.
   host/mouse_native.c (the camera's yaw) and host/nn_hid.c (the mouse as the right stick) read it. The existing option
   callback: no new member) */
enum { HOS_OPT_MOUSE_INVERT_X = 190 };
/* (HOS_OPT_HOLD_TOGGLE, option: the Controls tab's Hold to toggle rows as a mask, 1 << HOS_SW_* for each of the Switch's
   buttons A to ZR whose row is on, 0 by default: a press of such a button holds it and the next lets it go (host/nn_hid.c
   npad_states, host/hold_toggle.h). The rows are saved one by one, toggle_<button>; the existing option callback) */
enum { HOS_OPT_HOLD_TOGGLE = 191 };
enum { HOS_FILE_SAVED = 1, HOS_FILE_CURRENT = 2, HOS_FILES_CHOSEN = 256 };
/* ((Triforce) 11-24: the Graphics and Display tabs' feature rows, 240 to 279 theirs. HOS_OPT_SHADOW_RES, option: the
   Graphics tab's Shadow resolution row, the size the sun's shadow cascades are drawn at: 0 the game's own (1600), 1 2200,
   2 3072 (host/oot_shadow.c, read each frame; host/oot_shadow_fit.c keeps the nearest cascade steady at 3072) */
enum { HOS_OPT_SHADOW_RES = 240 };
/* (HOS_OPT_FULLSCREEN_SCREEN, option: the Display tab's Fullscreen screen, 0 the screen the window is on (the default), n the
   n-th of MkwVkHost.screens' list (host/display.c, Windows; read at each switch to fullscreen) */
enum { HOS_OPT_FULLSCREEN_SCREEN = 241 };
/* ((Triforce) 11-24: the menu, display and HUD rows of the third batch, 340 to 379 theirs. HOS_OPT_HUD_POSITION, option: the
   Display tab's HUD position row as it is now (0 Middle, 1 Screen edges), host/hos_wide_ui.c reads it at each present: the
   HUD's layouts planned for a wider screen, live. HOS_OPT_MENU_SIDES: its Menu sides row (0 Full width, 1 Centred, blurred
   sides, 2 Centred, black bars, HOS_MENU_SIDES_EXTENDED the menus at their 16:9 size with their side panes at the screen's
   edges, planned by host/hos_wide_ui.c too). HOS_HUD_DEFAULT_PLACEMENT: a HUD group's placement left as the game makes it
   (x and y biased by 16 in percent of the picture, the scale in percent above them) */
enum { HOS_OPT_HUD_POSITION = 340 };
enum { HOS_OPT_MENU_SIDES = 341 };
enum { HOS_MENU_SIDES_EXTENDED = 3 };
/* (HOS_OPT_FPS_CAP_ROW, option: the Graphics tab's Frame rate cap row as it is now, frame_rate_cap='s values; host/nn_vi.c
   reads it once a present and takes a change in play, HOS_FPS_MAX over it) */
enum { HOS_OPT_FPS_CAP_ROW = 342 };
/* (HOS_OPT_HUD_PLACEMENT, option: the Display tab's HUD placement row, 0 the game's, 1 Custom; HOS_OPT_HUD_HEALTH,
   HOS_OPT_HUD_BUTTONS, HOS_OPT_HUD_MINIMAP: Custom's three groups, each packed as HOS_HUD_DEFAULT_PLACEMENT is (the hearts and
   magic; the action and item buttons; the minimap). host/hos_wide_ui.c reads them at each present) */
enum { HOS_OPT_HUD_PLACEMENT = 343, HOS_OPT_HUD_HEALTH, HOS_OPT_HUD_BUTTONS, HOS_OPT_HUD_MINIMAP };
enum { HOS_HUD_DEFAULT_PLACEMENT = 16 | (16 << 6) | (100 << 12) };
/* ((Triforce) 380 to 389: Threaded rendering's. HOS_OPT_RENDER_THREAD, option: 1 when the replay runs on a thread of its own
   this run (gpu/vk/vk_replay.cpp async_on: RX_VK_ASYNC when set, else the Debug tab's Threaded rendering row or RX_VK_THREADED,
   gpu/vk/threaded_rendering.h), resolved once; 0 otherwise, as by default. host/rx_backend.c rx_async_replay asks it once the
   renderer runs. The existing option callback: no new member) */
enum { HOS_OPT_RENDER_THREAD = 380 };
/* ((Triforce) 410 to 419: the simulated turf's. The host says the area Link is in for the Graphics tab's Simulated turf page
   (gpu/vk/sim_turf_settings.h: each area's own turf values), through option_set: HOS_OPT_SIM_TURF_AREA_TEXT the map's name
   (Sequence_CurrentBanc), a byte a call, then HOS_OPT_SIM_TURF_AREA 1 (the name is whole) or 0 (no map: no save loaded).
   host/hos_main.c oot_inventory_refresh says it when it changes */
enum { HOS_OPT_SIM_TURF_AREA_TEXT = 410, HOS_OPT_SIM_TURF_AREA };
/* ((Triforce, 11-25) Evil HD's render distance: HOS_OPT_EVIL_HD, option: 1 while Evil HD is on (evil_hd_now: the row, F2,
   RX_VK_EVIL_FLIP), read each frame by host/evil_hd.c; HOS_EVIL_HD over it. 420: 410 and 411 are the Simulated turf's */
enum { HOS_OPT_EVIL_HD = 420 };
/* (Triforce) More rows of how the game plays (gpu/vk/vk_menu.cpp; 200 to 239 are theirs), each an option: what the row is
   set to, the game's own at its default. HOS_OPT_FOV: the System tab's Field of view row, percent of the game's own vertical
   angle in play, 50 to 150, 100 the game's own (host/oot_fov.c). HOS_OPT_TEXT_SIZE: its Text size row, 0 the game's own
   size, 1 to 4 for 110%, 125%, 150% and 175% (host/oot_text_size.c). HOS_OPT_CAMERA_CENTERING: the Controls tab's Camera
   centering row, 1 the game's own (the camera turns by itself the way Link moves), 0 it does not (host/mouse_native.c
   hos_disable_camera_centering). HOS_OPT_DAMAGE_TAKEN: the System tab's Damage taken row, 0 Half, 1 Normal (the game's
   own), 2 Double, 3 Quadruple (host/oot_damage.c). HOS_OPT_SKIP_OPENING: its Skip opening row, 1 a new game starts without
   the story movie and Navi waking Link (host/oot_opening.c). HOS_OPT_SKIP_TITLE: its Skip title screen row, 1 the game's
   start is pressed through to the newest save (host/oot_autoload.c: read once, at the title). HOS_OPT_AUTOSAVE: its Autosave
   row, 1 the game's own, 0 the autosaves of going from one area to another are skipped (host/oot_autosave.c).
   HOS_OPT_CHEAT_SPEED: the Debug tab's Movement speed tool, percent of Link's own speed, 100 to 300; 100 while the Debug
   tools are off (host/hos_main.c hos_oot_cct_speed). HOS_OPT_AUDIO_OUTPUT: the Audio tab's Audio output row as it is now,
   0 Auto, 1 Stereo, 2 5.1, 3 Mono: the layout is read from the file at the start (host/nn_audio.c au_menu_output), only
   Mono is asked for here, at each block mixed (audio_mono). HOS_OPT_MUTE_BACKGROUND: its Mute in background row, 1 no
   sound while another window has the focus (host/nn_audio.c master_volume). HOS_OPT_MIC_GAIN: its Microphone gain row,
   percent of what the microphone gives, 25 to 400, 100 its own (host/nn_audio_in.c pump, host/mic_gain.h) */
enum { HOS_OPT_FOV = 200, HOS_OPT_TEXT_SIZE, HOS_OPT_CAMERA_CENTERING, HOS_OPT_DAMAGE_TAKEN, HOS_OPT_SKIP_OPENING,
       HOS_OPT_SKIP_TITLE, HOS_OPT_AUTOSAVE, HOS_OPT_CHEAT_SPEED, HOS_OPT_AUDIO_OUTPUT, HOS_OPT_MUTE_BACKGROUND,
       HOS_OPT_MIC_GAIN };
/* ((Triforce) 11-24) A bug capture's settings changed from the defaults (host/bug_capture.c, capture.txt; 286 to 289 the bug
   capture's). HOS_OPT_BUG_SETTINGS, option_set 1: the menu writes down its rows that are not at their defaults, as it shows
   them, "Name: value (default: value)" a line each, or one line that says none is; option: the next byte of that text,
   UTF-8, 0 at its end (and a renderer without the text: the capture says the changes are not known). No new function, so
   MKWVK_API_VERSION stays */
enum { HOS_OPT_BUG_SETTINGS = 286 };

/* (hookshot) the mouse over the window while it is free (not captured): the Insert menu's (host/display.c,
   host/posix/display_sdl.c). x and y: the cursor in the window's pixels, of a window width x height pixels (the
   swapchain's, as a rule); held: the buttons down now, pressed: those pressed since the last read (1 left, 2 right,
   4 middle); wheel: the wheel's notches since then, away from the player positive */
enum { HOS_MOUSE_LEFT = 1, HOS_MOUSE_RIGHT = 2, HOS_MOUSE_MIDDLE = 4 };
typedef struct MkwVkPointer {
    int32_t x, y, width, height;
    uint32_t held, pressed;
    int32_t wheel;
} MkwVkPointer;

/* (Triforce, 11-19) Benchmark mode (host/hos_bench.c, HOS_BENCHMARK): what the renderer's benchmark panel shows
   (gpu/vk/vk_menu.cpp draw_bench), read each frame through MkwVkHost.bench. phase: MKWVK_BENCH_*; scene: the place gone to or
   measured, 1 to scenes (0 before the first); name: its name; progress: the whole run done, 0 to 1; fps: the frame rate of
   the last second, low1: the 1% low of the scene so far (-1 under 100 frames); graph_ms: the newest graph_n frame times,
   oldest first; line: what the panel says under the title when the phase has its own words (a failure's reason) */
enum { MKWVK_BENCH_OFF, MKWVK_BENCH_BOOT, MKWVK_BENCH_TRAVEL, MKWVK_BENCH_SETTLE, MKWVK_BENCH_MEASURE, MKWVK_BENCH_DONE,
       MKWVK_BENCH_STOPPED, MKWVK_BENCH_FAILED };
#define MKWVK_BENCH_GRAPH 240
typedef struct MkwVkBench {
    int32_t phase, scene, scenes, graph_n;
    float progress, fps, low1;
    char name[48];
    char line[96];
    float graph_ms[MKWVK_BENCH_GRAPH];
} MkwVkBench;

/* what the executable gives the back end */
/* ((Triforce) a connected screen: its native size in pixels, whether the game's window opens on it, and the monitor's own
   name in UTF-8 ("" where the system has none) */
typedef struct MkwVkScreen {
    uint32_t w, h;
    int32_t opens;
    char name[64];
} MkwVkScreen;

/* ((Triforce) one of the Options screen's settings, for the control bridge (MkwVkRenderer setting, host/control.c): key is its
   line in triforce_options.ini, name the row's, text how the menu shows the value) */
typedef struct MkwVkSetting {
    char key[32], name[48], text[64], tab[16];
    int value, lo, hi, step;
    int restart, fixed;   /* the change applies at the next start; nothing to choose on this PC (the menu shows it greyed) */
} MkwVkSetting;

typedef struct MkwVkHost {
    uint32_t version;   /* MKWVK_API_VERSION */
    void (*log)(const char *line);
    /* guest memory: the window, and GPU addresses (pools, below 1 TB the guest address itself) */
    uint8_t *(*guest_base)(void);
    uint64_t (*guest_size)(void);
    uint8_t *(*gpu_ptr)(uint64_t gpu, uint64_t *avail);
    uint64_t (*gpu_guest)(uint64_t gpu);
    int (*gpu_read)(uint64_t gpu, void *dst, uint64_t n);
    int (*gpu_write)(uint64_t gpu, const void *src, uint64_t n);
    /* guest pages written since the last call (the soft write watch): count, page numbers in *pages (freed with
       free_pages) */
    int64_t (*collect_written)(uint32_t **pages);
    void (*free_pages)(uint32_t *pages);
    void (*mark_written)(const void *p, uint64_t n);
    /* clocks: the guest tick (31.25 MHz from the start), host ns */
    uint64_t (*ticks)(void);
    int64_t (*now_ns)(void);
    /* NVN texture layouts (nvn_tex.c) */
    void (*tex_layout)(const nvn_texdesc *d, nvn_texlayout *o);
    uint64_t (*tex_level_offset)(const nvn_texdesc *d, unsigned level);
    int (*fmt_bpb)(int format, int *bw, int *bh);
    void (*tex_level_tiles)(const nvn_texdesc *d, unsigned level, unsigned *tile_h, unsigned *tile_d);
    uint32_t (*tex_linear_stride)(const nvn_texdesc *d);
    int (*depth_minus_w)(void);
    /* the memory pools ({guest start, size} each; returns the count, at most max) and a number that changes with
       them (host/nvdrv.c) */
    int (*gpu_pools)(uint64_t (*out)[2], int max);
    uint32_t (*maps_generation)(void);
    /* a number that changes with every mapping of NVN's virtual pools' pages (MapVirtual: sparse textures) */
    uint32_t (*vmap_generation)(void);
    /* the logical processors kept from the game's threads, for the replay thread (0: none) */
    uint64_t (*reserved_cpus)(void);
    /// The soft write watch's marks within [ranges[i][0], ranges[i][1]) only, read and cleared (free with free_pages)
    int64_t (*collect_written_in)(const uint64_t (*ranges)[2], int n, uint32_t **pages);
    /// Zeroed guest memory of the renderer's own (address space above the heap, never freed; 0 when none is left):
    /// what the NVN driver keeps in GPU memory of its own, such as its constant banks (mkw_eden.dll)
    uint64_t (*guest_alloc)(uint64_t size);
    /// (debugging) CPU writes to [guest, guest + size) logged with the writer's guest call stack (a page watch)
    void (*watch_guest_writes)(uint64_t guest, uint64_t size);
    /* (hookshot) the gamepads' inputs held now (1 << HOS_PAD_*), whatever they are bound to: the Insert menu's
       (host/nn_hid.c) */
    uint32_t (*pad_raw)(void);
    /* (hookshot) the controls, for the Insert menu's Controls page. button: the Switch's, HOS_SW_*; set HOS_BIND_PAD:
       the gamepad input that presses it (a HOS_PAD_* position, -1 none; slot 0 only); set HOS_BIND_KEY: the keys that
       do (Windows key codes, 0 none; slots 0 and 1; a mouse button's too, and HOS_KEY_* past the Switch's buttons).
       bind with button -1: all back to their defaults. ((Triforce) 11-24: HOS_BIND_PAD takes the ocarina's note rows
       too, HOS_KEY_OC_NOTE_*, which start unset and take no mouse button) */
    int (*binding)(int set, int button, int slot);
    void (*bind)(int set, int button, int slot, int code);
    /// Display aspect of the presented picture, after crop: the camera aspect applied at startup.
    /// Zero means no override; the renderer then fits the cropped texture's pixel aspect.
    float (*aspect_ratio)(void);
    int (*take_key_press)(int key);
    /* (hookshot) the free mouse (MkwVkPointer), read and its presses and wheel cleared: 1 when the cursor is over the
       window and the window has the focus. The Insert menu releases the mouse while it is open: WM_APP + 8 to the
       window, wParam 1 open, 0 closed (the capture it had then comes back) */
    int (*pointer)(MkwVkPointer *out);
    /* (hookshot) the microphones for the game's input streams (host/nn_audio_in.c), for the Insert menu's Microphone row:
       how many there are (listing them again), one's name, and the row's choice: mode 0 off, 1 the system's default, 2 the
       microphone of that name (index: its place in the list, -1 while it is not plugged in) */
    int (*mic_count)(void);
    const char *(*mic_name)(int index);
    void (*mic_select)(int mode, const char *name, int index);
    /* (hookshot) the controllers' motion sensors, for the Insert menu's Motion controls row (host/pad_sdl.c): 0 no
       controller, 1 controllers with no gyroscope, 2 one with a gyroscope */
    int (*gyro_status)(void);
    /* (hookshot) the log lines queued so far written out now (host/hos_thread.c log_queue): before the back end ends
       the process itself (replay_fatal), so a device lost's report is not lost with it */
    void (*log_flush)(void);
    /* (hookshot) the controller face of the button prompts the game was given at its start (host/prompts.c): HOS_PROMPT_*;
       -1 none (the game's own icons), or not chosen yet */
    int (*prompt_face)(void);
    /* (hookshot) the game's romfs folder (--romfs, or romfs beside the executable): the overlays read the game's own menu font
       from it (gpu/vk/vk_imgui.cpp), in memory only */
    const char *(*romfs_dir)(void);
    /* (hookshot) ultrawide's menus (nx2/oot_wide.py KEEP_VTABLES): keep_mask sets which of those screens keep the whole picture
       (a bit each; HOS_WIDE_KEEP=<hex> over it); returns the margin of the middle 16:9 at either side, a fraction of the
       picture's width (0: the picture is 16:9) */
    float (*wide_menus)(uint32_t keep_mask);
    /* (Triforce, 11-19, version 14) benchmark mode's state for its panel: 1 while it runs (out filled), 0 otherwise */
    int (*bench)(MkwVkBench *out);
    /* (Triforce, 11-19, version 15) while the game has the keys' face (prompt_face): the face of the controller used last,
       once host/prompts.c has built its icons for the overlay (prompts/External.pad.bfotf.zs); -1 none */
    int (*prompt_pad_face)(void);
    /* ((Triforce) 16) the connected screens as the host found them at the start (host/hos_screens.h), for the Insert menu's
       Output resolution row, which offers each one's size: at most cap written, how many; 0 when none is known */
    int (*screens)(MkwVkScreen *out, int cap);
    /* ((Triforce) 17) ultrawide's menus: 1 while a game menu runs whose backdrop is the one the Ultrawide menus row puts in
       the middle 16:9 (host/oot_title_movie.h: the file select, the file's box, the Options, the system menus' backdrop
       itself). The blur of the last picture that the renderer sees drawn is then that backdrop, to be given sides, and not
       the item wheel's background, which keeps the whole picture (gpu/vk/wide_sides_rule.h) */
    int (*wide_backdrop)(void);
    /* ((Triforce) 20) the playback devices, for the Audio tab's Output device row (host/audio_output_devices.c): listed again,
       how many; one's endpoint id and name (UTF-8), 1 when there is one at index; the row's choice by its id ("" the
       default), which the sound's thread opens at its next block; what it has open, HOS_OUTPUT_* bits */
    int (*audio_output_count)(void);
    int (*audio_output_info)(int index, char *id, int id_capacity, char *name, int name_capacity);
    void (*audio_output_select)(const char *id);
    int (*audio_output_state)(void);
    /* ((Triforce) 20) the Audio tab's Test microphone row (host/nn_audio_in.c hos_mic_test), once a menu tick while it may run:
       enabled 1 reads the Microphone row's microphone through the Microphone gain row (nothing played, nothing written), 0
       lets it go. levels[0], levels[1]: the loudest sample before and after the gain over the last 150 ms, thousandths of
       full scale. The answer: HOS_MIC_TEST_* bits */
    int (*mic_test)(int enabled, int *levels);
    /* ((Triforce) 23) what of the button prompts a change of face or controls reaches at once (host/prompts.c
       hos_prompts_live_parts): HOS_PROMPTS_LIVE_* bits; 0 none (a mod's files, a font built before, the keys' face, or not
       loaded yet): the Button prompts row asks for a restart then */
    int (*prompts_live)(void);
    /* ((Triforce) 23) the Controls page's per-control reset and its confirmed rebinds (host/nn_hid.c): a control's (HOS_SW_* or
       HOS_KEY_*) default bindings back, 0 (nothing changed) when another control has one of them; hos_bind's change made only
       when the controls it takes the input from (a bit each: conflicts) are those approved, 0 and nothing changed otherwise;
       whether a control's bindings are its defaults */
    int (*reset_binding)(int button);
    int (*rebind_control)(int set, int button, int slot, int code, uint64_t approved, uint64_t *conflicts);
    int (*binding_is_default)(int button);
} MkwVkHost;

/* ((Triforce, version 22) one completed temporal upscale's camera jitter sample: the scene's width and height and the jitter
   sequence's length, together; all zero while no upscaler jitters (host/rx_backend.c hos_dlss_jitter_clip) */
typedef struct MkwVkJitter {
    uint32_t width, height, phases;
} MkwVkJitter;

/* what the back end gives the executable: the rx_* functions (gpu/render/rx_nvn.h, rx_core) */
typedef struct MkwVkRenderer {
    uint32_t version;
    int (*start)(void *hwnd);
    void (*resize)(int width, int height);
    const char *(*describe)(void);
    void (*stats)(int64_t *draws, int64_t *skipped, int64_t *pipelines);
    void (*nvn_submit)(const uint64_t *handles, int n);
    uint64_t (*nvn_fence)(void);
    uint64_t (*nvn_pushed)(void);
    uint64_t (*nvn_replayed)(void);
    int (*nvn_wait)(uint64_t fence, uint64_t timeout_ns);
    void (*wait_writebacks_reading)(const void *p, uint64_t n);
    void (*nvn_finish)(void);
    void (*nvn_present)(const nvn_tex *t, const int crop[4]);
    void (*nvn_register_texture)(int id, const nvn_tex *t, const nvn_view *v);
    void (*nvn_register_sampler)(int id, const nvn_samp_par *p);
    void (*nvn_set_texture_pool_size)(int n);
    void (*nvn_texture_released)(const nvn_tex *t);
    void (*nvn_program_released)(const nvn_prog *p);
    void (*nvn_read_texels)(const nvn_tex *t, unsigned level, unsigned layer0, const NVNcopyRegion *r, uint8_t *dst,
                            uint64_t row_pitch, uint64_t image_pitch);
    void (*nvn_write_texels)(const nvn_tex *t, unsigned level, unsigned layer0, const NVNcopyRegion *r,
                             const uint8_t *src, uint64_t row_pitch, uint64_t image_pitch);
    void (*nvn_invalidate)(uint64_t gpu, uint64_t size);
    void (*nvn_pool_created)(uint64_t gpu, uint64_t size);   /* a memory pool made (non-virtual): imported early */
    /* whether the GPU may use guest memory in [lo, hi) through an import (the host keeps such pages committed) */
    int (*guest_imported)(uint64_t lo, uint64_t hi);
    /* virtual pages [gpu, gpu + size) mapped now are about to be unmapped or remapped (the old mapping still in place):
       what the GPU wrote into textures there goes into their memory first */
    void (*nvn_vmap_changing)(uint64_t gpu, uint64_t size);
    /* a texture initialized (its storage: whether the CPU's reads of a range may need a texture's texels) */
    void (*nvn_texture_created)(const nvn_tex *t);
    /* the CPU set an event's value: in order with the submits (the GPU's waits on it) */
    void (*nvn_event_signal)(uint64_t gpu, uint32_t value);
    int (*option)(int id);   /* (hookshot, the Insert menu) 0: game time follows the clock, 1: the menu is open, 2: dynamic resolution, 3: its fixed scale in percent, 4: the controllers count behind other windows, 5: text speed (0 normal to 3 instant), 6: Mouse camera (1 native mouse look, host/mouse_native.c; (Triforce) 2 off: the mouse is never captured, host/display.c),
                                7: the mouse's sensitivity in percent, 8: its up and down swapped (host/nn_hid.c),
                                18 to 23: the Motion page (HOS_OPT_GYRO*: motion controls from a pad's gyroscope, host/pad_sdl.c;
                                the horizontal and vertical sensitivity in percent, each turned around, the deadzone) */
    /* a submit with its queue */
    void (*nvn_submit_q)(const uint64_t *handles, int n, uint64_t queue);
    /* (hookshot) a fence of one queue: the value its own last submission signals (nvnQueueFenceSync) */
    uint64_t (*nvn_fence_q)(uint64_t queue);
    /* (hookshot, the Insert menu) a setting changed from the game's side, kept in the options file: 7 the mouse's sensitivity
       in percent (the - and = keys, host/nn_hid.c) */
    void (*option_set)(int id, int value);
    /* ((Triforce, 11-22, N64 Classic) a point of a w x h window, in its pixels (the cursor's), to the point of the game's picture
       N64 Classic's TV showed there at the last present, through its screen's curve: where the game's own menus drew what the
       cursor is over (host/oot_menu.c). As it is when the TV did not draw (gpu/vk/vk_n64.h n64_screen_point) */
    void (*screen_point)(int *x, int *y, int w, int h);
    /* ((Triforce, version 20) the control bridge (host/control.c, HOS_CONTROL; nothing calls these without it): the presents
       replayed so far, the draws recorded since the start, and the picture's size (the window's swapchain) */
    void (*frame_info)(int64_t *presents, int64_t *draws, int *width, int *height);
    /* a PNG of the first present replayed after present `after` (-1: the next one), RX_VK_SHOTS' size, written to path on a
       thread of its own, which then calls done(ctx, the present, 1 when the file was written). 0: not taken (too many
       waiting) */
    int (*shot)(const char *path, int64_t after, void (*done)(void *ctx, int64_t present, int ok), void *ctx);
    /* the Options screen's settings rows (shown on this PC; not the headings or the debug tools): the index-th, to list them
       (0: past the last; an index is no name, rows come and go), and the one whose triforce_options.ini key is key set to
       value as the menu's Left and Right set it, kept in the options file, out the row after it (1 set, 0 no such row, -1
       nothing to choose on this PC, -2 none of a list row's steps reaches value here: left as it was) */
    int (*setting)(int index, MkwVkSetting *out);
    int (*setting_set)(const char *key, int value, MkwVkSetting *out);
    /* ((Triforce, version 22) the camera jitter's sample (MkwVkJitter), whole: HOS_OPT_DLSS_JITTER_W, _H and _PHASES asked one
       at a time were three answers a resize or a scale change could fall between. Kept the last of the struct */
    void (*jitter_sample)(MkwVkJitter *out);
    /* ((Triforce, version 20) the game gave a program its shaders (nvnProgramSetShaders, nvnProgramInitializeFromBuilder), on the
       game's thread, before any draw uses it: what the back end kept ready for it can be loaded now (gpu/vk/vk_programs.cpp,
       RX_VK_LOAD=create; without it, only RX_VK_LOG_PROGRAM_LIFE's log). Its stages' code and control sections are in the
       game's memory at this call */
    void (*nvn_program_created)(const nvn_prog *p);
} MkwVkRenderer;

/* the DLL's one export: null when Vulkan is not usable (the executable then falls back to WebGPU) */
typedef const MkwVkRenderer *(*mkwvk_init_fn)(const MkwVkHost *host);
#ifdef MKWVK_BUILDING
#ifdef _WIN32
__declspec(dllexport) const MkwVkRenderer *mkwvk_init(const MkwVkHost *host);
#else
__attribute__((visibility("default"))) const MkwVkRenderer *mkwvk_init(const MkwVkHost *host);
#endif
#endif

#ifndef _WIN32
/* (linux) what start() is given in place of a window handle (host/posix/display_sdl.c): the window makes the
   surface (SDL_Vulkan_CreateSurface: X11 or Wayland) and says its size in pixels */
#define MKWVK_WINDOW_VERSION 2
typedef struct MkwVkWindow {
    uint32_t version;   /* MKWVK_WINDOW_VERSION */
    int (*create_surface)(void *window, void *instance, void *surface_out);   /* (VkInstance, VkSurfaceKHR *): 1 if made */
    void (*drawable_size)(void *window, int *width, int *height);
    void *window;
    /* (version 2) the refresh rate of the display the window is on, in mHz; 0 when not known (frame generation's Auto) */
    int (*refresh_mhz)(void *window);
} MkwVkWindow;
#endif

#ifdef __cplusplus
}
#endif
