/* Game controllers through SDL (host/hos_sdl.c: SDL3, else SDL2, third_party/sdl2/SDL2.dll; zlib license, loaded at
   run time): DualSense, DualShock 4, Switch Pro, Xbox and most other pads, over USB or Bluetooth. XInput alone sees
   only Xbox-style pads.

   A thread of its own (on Linux the window's, which runs SDL there too) opens every controller SDL knows (and ones
   plugged in later), polls them every 4 ms and keeps
   the merged state; nn_hid.c ORs it into the input with XInput, keyboard and mouse. Without SDL nothing
   changes. HOS_NO_SDL=1 leaves SDL out. The inputs go by position (HOS_PAD_*, SDL's own order: the bottom face button
   first, cross on a DualSense, A on an Xbox pad); nn_hid.c's controls make them the Switch's buttons.

   (hookshot) Motion: with the Insert menu's Motion controls on (the default), the open pad with a gyroscope and an
   accelerometer (Switch Pro and pads in Switch mode, DualSense, DualShock 4, others) that was used last has them read
   each poll and turned into the six-axis state OoT aims with (host/hos_motion.h), which nn_hid.c's
   GetSixAxisSensorStates gives the game; Motion sensitivity X/Y and Invert motion X/Y apply there. Off, or with no such pad, the game sees the pad
   lying still, as before. */
#include "hos.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>   /* ((Triforce, 11-26) sqrt: a stick's full push */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "hos_sdl.h"
#include "hd_rumble.h"
#include "vibration.h"          /* ((Triforce) what plays each pad's vibration) */
#include "rumble_renhdrum.h"    /* ((Triforce) RenHDrum's backends, when renhdrum.dll is beside the game) */
#include "pad_speaker.h"        /* ((Triforce) the game's sounds on a DualSense's own speaker) */
#include "hos_motion.h"
#include "steam_pads.h"
#include "../gpu/vk/vk_api.h"   /* (HOS_PAD_*) */

void hos_host_thread_register_self(const char *name);   /* hos_prof.c */

/* (BTN_A ... BTN_RIGHT are HOS_PAD_SOUTH ... HOS_PAD_RIGHT) */
enum { BTN_A, BTN_B, BTN_X, BTN_Y, BTN_BACK, BTN_GUIDE, BTN_START, BTN_LSTICK, BTN_RSTICK, BTN_LSHOULDER, BTN_RSHOULDER,
       BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_MISC1, BTN_RPADDLE1, BTN_LPADDLE1, BTN_RPADDLE2, BTN_LPADDLE2,
       BTN_TOUCHPAD = 20, BTN_N = 21 };
enum { AX_LX, AX_LY, AX_RX, AX_RY, AX_LT, AX_RT };

#define MAX_PADS 8
/* (motion: whether it has the sensors, whether they are on, when to try again after they would not turn on; used_ns:
   its last button or stick change; serial: which opening this is, so a pad reconnecting into the slot is a new one;
   bias: its gyroscope's learned resting rate, kept while another pad has motion) */
static struct {
    void *gc;
    int32_t id;
    uint16_t rumble_lo, rumble_hi;
    int64_t rumble_ns;
    /* (Triforce) the triggers' motors (trigger_poll): what they were last sent and when, when to ask a pad that refused
       again, and what the log has said of this pad (1 refused, 2 plays) */
    uint16_t trigger;
    uint8_t trigger_said;
    int64_t trigger_ns, trigger_retry_ns;
    uint8_t hd, hd_kind, hd_ever;   /* HD rumble (hd_rumble.h): HD_RUMBLE_UNKNOWN / ON / OFF, the pad's kind, sent once */
    /* ((Triforce) what plays its vibration (host/vibration.h: -1 not chosen yet), the kind of pad and its transport for
       that; a backend that would not open, and when to try it again; an Xbox pad's four motors as last sent (RenHDrum) */
    int8_t vib, vib_kind, wireless, vib_failed;
    int64_t vib_retry_ns, four_ns;
    uint16_t four[4];
    uint16_t vib_product;   /* (its USB product id whatever HOS_STEAM_PADS says: a Steam Controller (2026) on its cable) */
    int usb_token;          /* (a DualSense's four-channel sound card at the last look, or -1) */
    int64_t usb_next_look;
    uint8_t hd_sent[HD_RUMBLE_PACKET_SIZE];
    int64_t hd_ns;
    int motion, motion_on;
    int64_t motion_retry_ns, used_ns;
    int64_t opened_ns;   /* (Triforce) when SDL opened it, for the log's line when it goes */
    uint64_t input_sig;
    unsigned rested;   /* (hookshot) the sticks' axes seen at rest since it was opened, a bit each (AX_LX ... AX_RY):
                          only those steer; (Triforce) and its triggers seen let go (AX_LT, AX_RT): only those press */
    signed char held[4];   /* (the way each axis was last held, -1, 0 or 1: one held the other way has passed its rest) */
    int64_t trig_held_ns[2];  /* (Triforce) since when each trigger has read held, and let go, without a break (0: not */
    int64_t trig_rest_ns[2];  /* now), and what the log said of them (trigger_pull) */
    uint8_t trig_said;
    uint32_t serial;
    float bias[3], bias_t;
    int has_bias;
    /* ((Triforce) 11-24, host/steam_pads.h) its USB vendor and product, and its Steam Input handle: not 0 for a Steam
       stand-in pad; motion_only: a real Valve pad while a Steam stand-in pad is open, its motion read and no input */
    uint16_t vendor, product;
    uint64_t steam;
    int motion_only;
} pads[MAX_PADS];
static uint32_t pads_opened;
static SRWLOCK state_lock = SRWLOCK_INIT;
static uint64_t state_buttons;
static int32_t state_stick[4];
static int state_count;
static int state_deck_builtin;   /* ((Triforce) 11-24) the Steam Deck's built-in controls gave the input of that poll */
static char state_name[128];   /* the first controller's name (host/prompts.c: the button prompts' Auto) */
static char state_last_name[128];   /* ((Triforce) the name of the open controller used last (used_ns), "" none */
/* ((Triforce) and their SDL types (the loaded SDL's own numbers, 0 unknown or none), for Auto's face where a name says no
   maker's buttons: host/prompts.c face_of_type */
static int state_type, state_last_type;
/* ((Triforce, 11-19) the scans for controllers done (pads_poll), for Auto's wait at the game's start (host/prompts.c
   choose_face): -1 when SDL will not run (HOS_NO_SDL, no SDL, or it would not start), 0 while it is starting */
static volatile LONG scans;
static volatile LONG rumble_low, rumble_high;   /* 0..65535, set by the vibration HLE */
/* the game's own vibration values per side (0 left, 1 right: {amp_low, freq_low, amp_high, freq_high}), for the pads
   that play HD rumble; silence until the game sends one */
static SRWLOCK hd_lock = SRWLOCK_INIT;
static float hd_values[2][4] = {{0.0f, 160.0f, 0.0f, 320.0f}, {0.0f, 160.0f, 0.0f, 320.0f}};
/* (motion) the pad read and its filter (the polling thread's own), then what the game is handed (under state_lock): the
   last HOS_MOTION_HISTORY readings, newest at motion_hist[motion_head]; gyro_status for the menu */
static HosMotion motion;
static int64_t motion_ns, motion_reading_ns, motion_log_ns, motion_readings, motion_start_ns;
static int motion_warned;
static int motion_pad = -1;
static uint32_t motion_serial;
static HosMotionSample motion_hist[HOS_MOTION_HISTORY];
static int motion_head, motion_count, motion_live;
static volatile LONG gyro_status;   /* 0 no controller, 1 controllers but none with a gyro, 2 one with a gyro */

int32_t hos_stick_axis(int16_t v, int zone);   /* nn_hid.c: the menu's Stick dead zone, as XInput's pads */
/* ((Triforce) nn_hid.c: a stick's own dead zone, the menu's Left and Right stick dead zone, -1 none; an axis cut at it,
   or at the menu's Stick dead zone when its stick has none) */
int hos_stick_own(int stick);
int32_t hos_stick_axis_own(int16_t v, int zone, int own);
/* ((Triforce) nn_hid.c: a stick cut at its dead zone as a pair, both axes kept outside the zone's circle) */
void hos_filter_stick(int16_t x, int16_t y, int zone, int own, int32_t out[2]);

/* ((Triforce) 11-24) host/steam_pads.h's rules, on unless HOS_STEAM_PADS=0 (off, no, false): read once */
static int steam_rules(void) {
    static volatile LONG on = -1;
    if (on < 0) {
        const int now = !steam_pads_off(getenv("HOS_STEAM_PADS"));
        if (InterlockedCompareExchange(&on, now, -1) == -1 && !now)
            hos_log("hid: Steam's controllers as before (HOS_STEAM_PADS=0): its ignore list kept, every open pad's "
                    "buttons counted, the mouse beside a Steam Deck's own controls");
    }
    return on > 0;
}

static int32_t stick_value(int16_t v, int flip, int zone, int own) {
    const int32_t a = hos_stick_axis_own(v, zone, own);
    return flip ? -a : a;
}

/* (Triforce) Whether an axis is at rest, for the poll's rule that an axis steers once it has been seen at rest, when its
   stick has a dead zone of its own. That zone can be smaller than any stick's rest: with 0 an axis is never exactly at
   rest, and with a few percent a stick resting just past it would steer only after a push the other way. So an axis
   inside the default dead zone (XInput's 24%, hos_stick_axis's zone 0) is at rest whatever smaller zone its stick cuts
   at: the rule asks what it has always asked at the default, and a phantom axis, held far outside it, still never
   steers. Without a zone of its own (-1) this adds nothing: rest is the Stick dead zone row's, as before. raw: the axis
   as SDL gives it. */
static int stick_rests(int16_t raw, int own) { return own >= 0 && hos_stick_axis(raw, 0) == 0; }

/* SDL's controller support started; 0 when it could not be */
static int pads_start(void) {
    /* poll in the background, whatever window is in front (nn_hid.c decides when input counts) */
    hos_sdl_hint("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1");
#ifdef _WIN32
    /* (Triforce, 11-12) SDL's own thread for its controller window's messages. On Windows SDL reads an Xbox pad through
       raw input: the buttons and sticks arrive as WM_INPUT messages to a window SDL makes on the thread that starts its
       controllers, and only the triggers and Guide come from XInput. SDL handles those messages in its video event loop,
       or on a thread of its own with this hint; this thread has neither a window loop nor SDL's video, so the messages
       were never handled: once SDL had opened the pad only the triggers worked, until the game was started again with
       the pad turned on later (SDL never saw that pad, its arrival being such a message too, and XInput read it). A
       player's Xbox Series X pad on the Xbox Wireless Adapter, SDL 2.32.10, the same calls in a probe: XInput 694 state
       changes in 8 s of pressing, SDL 0 button or stick changes with the triggers moving; with the hint 579 for 700. */
    hos_sdl_hint("SDL_JOYSTICK_THREAD", "1");
#endif
    /* (SDL2: PlayStation pads' rumble asked for; SDL3 turns it on when a rumble is first sent) */
    hos_sdl_hint("SDL_JOYSTICK_HIDAPI_PS5_RUMBLE", "1");
    hos_sdl_hint("SDL_JOYSTICK_HIDAPI_PS4_RUMBLE", "1");
    /* (the map below is by position; SDL2 reports Nintendo pads by their labels unless told not to, which put a Switch Pro
       Controller's A, on the right, at the bottom button's place: A acted as B and X as Y: SkyboundTotk issue 12. SDL3's
       are by position always) */
    hos_sdl_hint("SDL_GAMECONTROLLER_USE_BUTTON_LABELS", "0");
    /* (with no window nothing reads SDL's quit event: SDL's own SIGINT/SIGTERM handlers turned a timeout's or a service
       manager's SIGTERM into that event, and the run went on until SIGKILL. Without them the signals end it as usual) */
    if (getenv("HOS_HEADLESS")) hos_sdl_hint("SDL_NO_SIGNAL_HANDLERS", "1");
    /* ((Triforce) 11-24) Valve's own pads taken out of the ignore list Steam sets for the games it starts, so that their
       motion sensors are read (host/steam_pads.h). Only in Steam's own environment (its list and its stand-in pads'
       variable, both), and only with an SDL that tells Steam's stand-in pads apart: without that, a real pad and its
       stand-in would both play. A list emptied or unset in Steam's launch options is left as it is, as is every
       environment Steam did not make */
    {
        const char *list = getenv("SDL_GAMECONTROLLER_IGNORE_DEVICES");
        char kept[4096];
        if (steam_rules() && steam_pads_from_steam(list, getenv("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD")) &&
            hos_sdl_knows_steam_pads() && steam_pads_without_valve(list, kept, sizeof kept) > 0 &&
            hos_sdl_hint_override("SDL_GAMECONTROLLER_IGNORE_DEVICES", kept))
            hos_log("hid: Valve's controllers (not the Steam Deck's) taken out of Steam's ignore list, for their motion "
                    "sensors (HOS_STEAM_PADS=0: the list as Steam set it)");
    }
    if (!hos_sdl_init(HOS_SDL_GAMEPAD)) {
        hos_log("hid: SDL could not start its controller support: %s", hos_sdl_error());
        InterlockedExchange(&scans, -1);
        return 0;
    }
    hos_log("hid: SDL controller support ready (DualSense, DualShock 4, Switch Pro, Xbox and others)");
    return 1;
}

/* SDL_GameControllerRumble runs only for the duration it is given, then stops, and a repeat of the same numbers was
   skipped. A rumble the game holds, and one that was already playing when this controller opened, never reached it. */
static int rumble_due(unsigned lo, unsigned hi, unsigned sent_lo, unsigned sent_hi, long long now, long long sent_ns) {
    if (lo != sent_lo || hi != sent_hi) return 1;
    if ((lo || hi) && now - sent_ns >= 500000000LL) return 1;   /* (half of the 1 s effect, so it does not lapse) */
    return 0;
}

/* (Triforce, after NX2navi's rumble_curve) The Insert menu's Vibration curve (hundredths, 20 to 150) on one motor's
   0..65535, before the Rumble strength: a power on the motor's strength taken as 0 to 1. 100 leaves it as it is, for
   every value. Under 100 the weak rumbles, which is most of what OoT sends, come up towards the strong ones (at 60 a
   tenth of the motor's strength becomes a quarter); over 100 they go down. Silence and the motor's top stay where they
   are, and a stronger rumble never comes out the weaker of two. 0 or less is no curve (an option table that does not
   know the row answers 0). */
static unsigned rumble_curve(unsigned value, int curve) {
    if (value >= 0xFFFFu) return 0xFFFFu;
    if (!value || curve <= 0 || curve == 100) return value;
    const double power = (curve < 20 ? 20 : curve > 150 ? 150 : curve) / 100.0;
    const double v = pow(value / 65535.0, power) * 65535.0 + 0.5;
    return v >= 65535.0 ? 0xFFFFu : (unsigned)v;
}

/* The Insert menu's Rumble strength (percent; 0 Off, up to 300) on the motors' 0..65535, heavy and light together: up
   to 100 each motor is scaled on its own (100 sends them as they are); above, when the stronger would pass the motor's
   top, both are scaled by the same factor so that it just reaches it, keeping the balance between the motors that the
   frequency split chose. Off stops a rumble that is playing (the poll sends the change). */
static void rumble_strength(unsigned heavy, unsigned light, int percent, uint16_t out[2]) {
    if (percent <= 0) {
        out[0] = out[1] = 0;
        return;
    }
    unsigned long long h = (unsigned long long)heavy * (unsigned)percent / 100u;
    unsigned long long l = (unsigned long long)light * (unsigned)percent / 100u;
    if (h > 0xFFFFu || l > 0xFFFFu) {   /* (from the motors' own values: the same factor for both, the stronger at the top) */
        const unsigned long long top = heavy > light ? heavy : light;
        h = heavy * 0xFFFFull / top;
        l = light * 0xFFFFull / top;
    }
    out[0] = (uint16_t)h;
    out[1] = (uint16_t)l;
}

/* (Triforce, after NX2navi's rumble_triggers) The motors in the triggers of an Xbox One or Series pad, with the Insert
   menu's Trigger vibration on: both play the light motor's rumble, sent when it changes and again before SDL's effect
   ends, as the motors' own is (rumble_due). want: that strength, 0 with the row off. A pad whose triggers were never
   sent a rumble is never sent a stop either, so with the row off nothing is called at all; turned off while they play,
   they are stopped. A pad without such motors, a driver that cannot reach them and an SDL without the call all refuse:
   said once a pad in the log, and that pad is asked again two seconds later at the soonest (a write that failed once
   comes back; one that never will costs a call every two seconds of rumble). */
static void trigger_poll(int i, unsigned want, long long now) {
    if (now < pads[i].trigger_retry_ns) return;
    if (!rumble_due(want, want, pads[i].trigger, pads[i].trigger, now, pads[i].trigger_ns)) return;
    const int ok = hos_sdl_pad_rumble_triggers(pads[i].gc, (uint16_t)want, (uint16_t)want, want ? 1000 : 0) != 0;
    if (want && !(pads[i].trigger_said >> ok & 1)) {
        pads[i].trigger_said |= (uint8_t)(1 << ok);
        if (ok) hos_log("hid: trigger vibration on \"%s\"", hos_sdl_pad_name(pads[i].gc));
        else hos_log("hid: \"%s\" took no trigger vibration (%s)", hos_sdl_pad_name(pads[i].gc),
                     hos_sdl_pad_has_trigger_rumble() ? hos_sdl_error() : "this SDL has no call for it");
    }
    if (!ok) {   /* (nothing plays there, as far as is known: the next rumble asks again, not before the two seconds) */
        pads[i].trigger = 0;
        pads[i].trigger_ns = 0;
        pads[i].trigger_retry_ns = now + 2000000000LL;
        return;
    }
    pads[i].trigger = (uint16_t)want;
    pads[i].trigger_ns = now;
}

/* A pad SDL just opened: HD rumble when it is a Switch Pro Controller or a Joy-Con and the SDL has the effect call
   (HOS_HD_RUMBLE=0: never); whether SDL's driver takes it shows with the first packet. */
static void hd_open(int i, void *gc) {
    static int env_off = -1;
    if (env_off < 0) {
        const char *e = getenv("HOS_HD_RUMBLE");
        env_off = e && !strcmp(e, "0");
    }
    pads[i].hd_kind = (uint8_t)hd_rumble_kind(hos_sdl_load(), hos_sdl_pad_type(gc));
    pads[i].hd = (uint8_t)hd_rumble_start(pads[i].hd_kind, hos_sdl_pad_has_effect(), env_off);
    pads[i].hd_ever = 0;
    pads[i].hd_ns = 0;
    const uint8_t n[4] = {0x00, 0x01, 0x40, 0x40};
    hd_rumble_packet(HD_RUMBLE_PRO, n, n, pads[i].hd_sent);
}

/* A pad's HD rumble, each poll: its packet when due (hd_rumble_due). 1 when the pad plays HD rumble (the motor rumble
   is not sent to it); 0 when it does not, or SDL just refused it (then it gets the motor rumble from now on). side:
   the left side's bytes, the right's, and both merged (for a single Joy-Con, which has only one). */
static int hd_poll(int i, const uint8_t side[3][4], long long now) {
    if (pads[i].hd == HD_RUMBLE_OFF) return 0;
    uint8_t packet[HD_RUMBLE_PACKET_SIZE];
    const int single = pads[i].hd_kind == HD_RUMBLE_JOYCON_LEFT || pads[i].hd_kind == HD_RUMBLE_JOYCON_RIGHT;
    hd_rumble_packet(pads[i].hd_kind, single ? side[2] : side[0], single ? side[2] : side[1], packet);
    if (!hd_rumble_due(packet, pads[i].hd_sent, pads[i].hd_ever, now, pads[i].hd_ns)) return 1;
    const int was = pads[i].hd;
    pads[i].hd = (uint8_t)hd_rumble_after_send(hos_sdl_pad_effect(pads[i].gc, packet, sizeof packet));
    if (pads[i].hd == HD_RUMBLE_OFF) {   /* (refused: HD rumble off for this pad until it is closed and opened again.
                                           SDL3 queues the write, so false means the driver does not support the effect,
                                           not a write that failed once) */
        hos_log("hid: \"%s\" did not take HD rumble (%s): its rumble goes to its motors", hos_sdl_pad_name(pads[i].gc),
                hos_sdl_error());
        pads[i].rumble_lo = pads[i].rumble_hi = 0;   /* (the motor path sends what is playing at once) */
        pads[i].rumble_ns = 0;
        return 0;
    }
    if (was == HD_RUMBLE_UNKNOWN) hos_log("hid: HD rumble on \"%s\"", hos_sdl_pad_name(pads[i].gc));
    memcpy(pads[i].hd_sent, packet, sizeof packet);
    pads[i].hd_ns = now;
    pads[i].hd_ever = 1;
    return 1;
}

/* ---- (Triforce) what plays each pad's vibration (host/vibration.h); RenHDrum's backends are host/rumble_renhdrum.c.
   Without renhdrum.dll (renhdrum.so) beside the game, Auto is what every pad had before: a Switch pad's own HD rumble,
   every other pad's motors (with Trigger vibration and Vibration curve as before) ---- */
static int vib_force = -1;   /* HOS_RUMBLE_BACKEND, read once */
/* RenHDrum for a pad of this kind: loaded (once) only for a pad it would play */
static int vib_rh_for(int kind) {
    if (vib_force == VIB_FORCE_HD || vib_force == VIB_FORCE_MOTORS || kind == VIB_PAD_OTHER) return 0;
    return rh_load();
}
/* what played pad i lets go of it, and its motors are stopped (whatever plays next sends what is playing) */
static void vib_leave(int i, int64_t now) {
    (void)now;
    void *gc = pads[i].gc;
    switch (pads[i].vib) {
    case VIB_RH_DS_USB: rh_usb_close(); break;
    case VIB_RH_DS_BT: rh_bt_close(); break;
    case VIB_RH_XBOX:
        rh_pad_close(gc);
        hos_sdl_pad_rumble_triggers(gc, 0, 0, 0);
        break;
    case VIB_RH_SWITCH: rh_pad_close(gc); break;
    case VIB_RH_STEAM: rh_steam_close(); break;
    default: break;
    }
    if (pads[i].vib >= 0) hos_sdl_pad_rumble(gc, 0, 0, 0);
    if (pads[i].trigger) hos_sdl_pad_rumble_triggers(gc, 0, 0, 0);   /* (Trigger vibration's, playing: stopped too) */
    pads[i].trigger = 0, pads[i].trigger_ns = 0;
    pads[i].rumble_lo = pads[i].rumble_hi = 0, pads[i].rumble_ns = 0;
    pads[i].hd_ever = 0;
    memset(pads[i].four, 0, sizeof pads[i].four), pads[i].four_ns = 0;
    pads[i].vib = -1;
}
static void vib_choose(int i, int mode, int64_t now) {
    void *gc = pads[i].gc;
    const int kind = pads[i].vib_kind;
    /* (one that stopped playing: let go, and chosen again below) */
    if (pads[i].vib == VIB_RH_DS_USB && !rh_usb_alive()) {
        hos_log("vibration: the DualSense's sound card went away: its motors until it is back");
        vib_leave(i, now);
        pads[i].usb_token = -1, pads[i].usb_next_look = now + 2000000000LL;
    } else if (pads[i].vib == VIB_RH_DS_BT && !rh_bt_alive()) {
        vib_leave(i, now);
        pads[i].vib_failed = VIB_RH_DS_BT, pads[i].vib_retry_ns = now + 30000000000LL;
    } else if (pads[i].vib == VIB_RH_STEAM && !rh_steam_alive()) {
        vib_leave(i, now);
        pads[i].vib_failed = VIB_RH_STEAM, pads[i].vib_retry_ns = now + 30000000000LL;
    }
    const int rh = vib_rh_for(kind);
    int ds_usb = 0, ds_hid = 0;
    if (rh && kind == VIB_PAD_DUALSENSE && mode == VIB_MODE_AUTO) {
        void *owner = rh_usb_owner();
        if (owner == gc) ds_usb = 1;
        else if (!owner && pads[i].wireless != 1) {
            if (now >= pads[i].usb_next_look) pads[i].usb_token = rh_usb_find(gc), pads[i].usb_next_look = now + 2000000000LL;
            ds_usb = pads[i].usb_token >= 0;
        }
        owner = rh_bt_owner();
        ds_hid = owner == gc || (!owner && hos_sdl_hid_can() && *hos_sdl_pad_path(gc));
    } else if (rh && kind == VIB_PAD_STEAM && mode == VIB_MODE_AUTO) {   /* (its grips: its HID device, one pad at a time) */
        void *owner = rh_steam_owner();
        ds_hid = owner == gc || (!owner && hos_sdl_hid_can() && *hos_sdl_pad_path(gc));
    }
    const int hd = pads[i].hd_kind != HD_RUMBLE_NONE && pads[i].hd != HD_RUMBLE_OFF;
    int want = vibration_pick(mode, vib_force, kind, pads[i].wireless, hd, rh, ds_usb, ds_hid);
    /* (a Joy-Con alone: our HD rumble merges both sides into it, RenHDrum's engine plays its own side's only. Testers'
       =renhdrum still gets RenHDrum's) */
    const int single = pads[i].hd_kind == HD_RUMBLE_JOYCON_LEFT || pads[i].hd_kind == HD_RUMBLE_JOYCON_RIGHT;
    if (want == VIB_RH_SWITCH && single && vib_force != VIB_FORCE_RENHDRUM) want = hd ? VIB_HD : VIB_MOTORS;
    if (want == pads[i].vib_failed && now < pads[i].vib_retry_ns) want = VIB_MOTORS;   /* (it would not open: not yet) */
    if (want == pads[i].vib) return;
    vib_leave(i, now);
    int ok = 1;
    if (want == VIB_RH_DS_USB) ok = rh_usb_open(gc, pads[i].usb_token);
    else if (want == VIB_RH_DS_BT) ok = rh_bt_open(gc, hos_sdl_pad_path(gc));
    else if (want == VIB_RH_STEAM) ok = rh_steam_open(gc, hos_sdl_pad_path(gc), pads[i].vib_product == VIB_STEAM_CABLE);
    else if (want == VIB_RH_XBOX || want == VIB_RH_SWITCH)
        ok = rh_pad_open(gc, want, pads[i].wireless == 1, pads[i].hd_kind == HD_RUMBLE_PRO);
    if (!ok) {
        pads[i].vib_failed = (int8_t)want, pads[i].vib_retry_ns = now + 5000000000LL;
        want = VIB_MOTORS;
    }
    if (want != VIB_MOTORS || pads[i].vib_kind != VIB_PAD_OTHER)
        hos_log("vibration: \"%s\": %s", hos_sdl_pad_name(gc),
                want == VIB_NONE ? "off" : want == VIB_MOTORS ? "its motors" : want == VIB_HD ? "its own HD rumble" :
                want == VIB_RH_DS_USB ? "fine haptics on its cable (RenHDrum)" :
                want == VIB_RH_DS_BT ? "fine haptics over Bluetooth (RenHDrum)" :
                want == VIB_RH_XBOX ? "four motors (RenHDrum)" :
                want == VIB_RH_STEAM ? "its grips (RenHDrum, experimental)" : "HD rumble (RenHDrum)");
    pads[i].vib = (int8_t)want;
}
/* an Xbox pad's four motors (RenHDrum): sent when RenHDrum says, and again every half second while they turn, as the
   motor rumble is (SDL's rumble lasts the time it is given). triggers: the Trigger vibration row; off, the triggers' two
   motors stay still, as they do with the plain motors */
static void four_poll(int i, int64_t now, int triggers) {
    uint16_t m[4];
    int due = rh_xbox_poll(pads[i].gc, now, m);
    if (!due) {
        if (!(pads[i].four[0] | pads[i].four[1] | pads[i].four[2] | pads[i].four[3]) || now - pads[i].four_ns < 500000000LL)
            return;
        memcpy(m, pads[i].four, sizeof m);
    }
    if (!triggers) m[2] = m[3] = 0;
    const int on = m[0] || m[1] || m[2] || m[3];
    hos_sdl_pad_rumble(pads[i].gc, m[0], m[1], on ? 1000 : 0);
    hos_sdl_pad_rumble_triggers(pads[i].gc, m[2], m[3], on ? 1000 : 0);
    memcpy(pads[i].four, m, sizeof m), pads[i].four_ns = now;
}

/* (motion) the sensors on while Motion controls is on (HOS_OPT_GYRO, on without the menu), off otherwise; the pad with
   them that was used last read into the filter. count: the pads open */
static void motion_poll(int64_t now, int count) {
    int rx_option(int id, int otherwise);
    static int debug = -1;   /* (HOS_MOTION_DEBUG, read once) */
    if (debug < 0) debug = getenv("HOS_MOTION_DEBUG") != NULL;
    const int want = rx_option(HOS_OPT_GYRO, 1) != 0;
    int pick = -1, any = 0;
    for (int i = 0; i < MAX_PADS; i++) {
        if (!pads[i].gc || !pads[i].motion) continue;
        any = 1;
        if (pads[i].motion_on != want && now >= pads[i].motion_retry_ns) {
            const int ok = hos_sdl_pad_sensor_enable(pads[i].gc, HOS_SDL_SENSOR_ACCEL, want) &
                           hos_sdl_pad_sensor_enable(pads[i].gc, HOS_SDL_SENSOR_GYRO, want);
            if (want && !ok) {   /* (both off again, and another try in two seconds: a pad over Bluetooth may still be
                                     starting) */
                hos_sdl_pad_sensor_enable(pads[i].gc, HOS_SDL_SENSOR_ACCEL, 0);
                hos_sdl_pad_sensor_enable(pads[i].gc, HOS_SDL_SENSOR_GYRO, 0);
                pads[i].motion_on = 0;
                if (!pads[i].motion_retry_ns)
                    hos_log("hid: \"%s\": its motion sensors could not be turned on yet, trying again",
                            hos_sdl_pad_name(pads[i].gc));
                pads[i].motion_retry_ns = now + 2000000000LL;
            } else {
                pads[i].motion_on = want;
                pads[i].motion_retry_ns = 0;
            }
        }
        if (want && pads[i].motion_on && (pick < 0 || pads[i].used_ns > pads[pick].used_ns)) pick = i;
    }
    InterlockedExchange(&gyro_status, any ? 2 : count ? 1 : 0);
    float a[3], g[3];
    const int read = pick >= 0 && hos_sdl_pad_sensor(pads[pick].gc, HOS_SDL_SENSOR_ACCEL, a, 3) &&
                     hos_sdl_pad_sensor(pads[pick].gc, HOS_SDL_SENSOR_GYRO, g, 3);
    /* (a gyroscope reading the very same values for over a second has stopped when its accelerometer does too: a real
       accelerometer always moves a little, while a gyroscope may read exactly 0 at rest, as a Steam Deck's in its dock
       does. Seen with a Steam Controller under Steam after Alt+Tab, when Steam's layout switch left its sensors off while
       SDL still had them on. Off and on again, as the menu's Motion controls row does, brings it back) */
    {
        static float last_a[3], last_g[3];
        static int64_t same_since, rearm_ns;
        if (read && !memcmp(g, last_g, sizeof g) && !memcmp(a, last_a, sizeof a)) {
            if (!same_since) same_since = now;
            else if (now - same_since > 1200000000LL && now >= rearm_ns) {
                hos_sdl_pad_sensor_enable(pads[pick].gc, HOS_SDL_SENSOR_ACCEL, 0);
                hos_sdl_pad_sensor_enable(pads[pick].gc, HOS_SDL_SENSOR_GYRO, 0);
                pads[pick].motion_on = 0;   /* (turned on again by the loop above on the next poll) */
                hos_log("hid: \"%s\": its gyroscope and accelerometer stopped changing: motion sensors turned off "
                        "and on again", hos_sdl_pad_name(pads[pick].gc));
                same_since = 0, rearm_ns = now + 3000000000LL;
            }
        } else {
            if (read) memcpy(last_a, a, sizeof a), memcpy(last_g, g, sizeof g);
            same_since = 0;
        }
    }
    /* (the pad that had motion keeps what its filter learned of its gyroscope's bias, for when it has motion again) */
    if (motion_pad >= 0 && (!read || pick != motion_pad) && pads[motion_pad].gc && pads[motion_pad].serial == motion_serial &&
        motion.learned_t > 0) {
        memcpy(pads[motion_pad].bias, motion.bias, sizeof motion.bias);
        pads[motion_pad].bias_t = motion.learned_t, pads[motion_pad].has_bias = 1;
    }
    if (!read) {
        motion_pad = -1;
        AcquireSRWLockExclusive(&state_lock);
        motion_live = 0, motion_count = 0;
        ReleaseSRWLockExclusive(&state_lock);
        return;
    }
    int fresh = 0;
    if (pick != motion_pad || pads[pick].serial != motion_serial) {   /* (another pad, or one reconnected: a fresh filter) */
        hos_motion_reset(&motion);
        if (pads[pick].has_bias)
            memcpy(motion.bias, pads[pick].bias, sizeof motion.bias), motion.learned_t = pads[pick].bias_t;
        motion_pad = pick, motion_serial = pads[pick].serial, motion_ns = now;
        fresh = 1;
        motion_start_ns = now, motion_warned = 0;
        hos_log("hid: motion controls from \"%s\"", hos_sdl_pad_name(pads[pick].gc));
    }
    /* the filter runs outside the lock (the game's input calls take it); a repeat of the last reading is no reading */
    const int64_t dt_ns = now - motion_ns;
    motion_ns = now;
    {   /* (the Motion deadzone row: the console's tight, standard and loose zero-drift thresholds, turns a second) */
        static const float zone[3] = {HOS_MOTION_THRESHOLD_TIGHT, HOS_MOTION_THRESHOLD, HOS_MOTION_THRESHOLD_LOOSE};
        const int z = rx_option(HOS_OPT_GYRO_DEADZONE, 1);
        motion.threshold = zone[z < 0 ? 0 : z > 2 ? 2 : z];
    }
    if (!hos_motion_update(&motion, a, g, (float)(dt_ns / 1e9), rx_option(HOS_OPT_GYRO_SENS_X, 100) / 100.0f,
                           rx_option(HOS_OPT_GYRO_SENS_Y, 100) / 100.0f, rx_option(HOS_OPT_GYRO_INV_X, 0),
                           rx_option(HOS_OPT_GYRO_INV_Y, 0)) && !fresh)
        return;
    if (!motion_warned && motion.learned_t <= 0 && now - motion_start_ns > 30000000000LL) {
        motion_warned = 1;   /* (a pad noisier than the stillness test allows: its drift is never taken off) */
        hos_log("hid: motion: \"%s\" has not been set down yet, so its gyroscope's drift is not learned: set it on a "
                "table for a second (if it is on a table and this stays, its sensor may be noisier than the stillness "
                "test allows)", hos_sdl_pad_name(pads[pick].gc));
    }
    if (debug && now >= motion_log_ns) {   /* (twice a second: what the game gets) */
        motion_log_ns = now + 500000000LL;
        hos_log("hid: motion: accel (%+.2f, %+.2f, %+.2f) G, gyro (%+.3f, %+.3f, %+.3f) turns/s, direction rows "
                "(%+.2f %+.2f %+.2f / %+.2f %+.2f %+.2f / %+.2f %+.2f %+.2f), bias (%+.4f, %+.4f, %+.4f)", motion.out.accel[0],
                motion.out.accel[1], motion.out.accel[2], motion.out.gyro[0], motion.out.gyro[1], motion.out.gyro[2],
                motion.out.direction[0], motion.out.direction[1], motion.out.direction[2], motion.out.direction[3],
                motion.out.direction[4], motion.out.direction[5], motion.out.direction[6], motion.out.direction[7],
                motion.out.direction[8], motion.bias[0], motion.bias[1], motion.bias[2]);
    }
    HosMotionSample r;
    r.st = motion.out;
    r.n = ++motion_readings;
    /* (the time since the reading before, capped as the filter caps it: a stalled pad's next reading is no jump) */
    r.dt_ns = fresh ? 5000000 : now - motion_reading_ns;
    if (r.dt_ns > (int64_t)(HOS_MOTION_DT_MAX * 1e9)) r.dt_ns = (int64_t)(HOS_MOTION_DT_MAX * 1e9);
    motion_reading_ns = now;
    AcquireSRWLockExclusive(&state_lock);
    motion_head = (motion_head + 1) % HOS_MOTION_HISTORY;
    motion_hist[motion_head] = r;
    if (fresh) motion_count = 0;
    if (motion_count < HOS_MOTION_HISTORY) motion_count++;
    motion_live = 1;
    ReleaseSRWLockExclusive(&state_lock);
}

/* ((Triforce) 11-24) a motion-only pad's own presses (host/steam_pads.h): they are not the game's input, but they still
   mark it the pad used last, which motion_poll reads motion from */
static void motion_only_used(int i, int64_t now) {
    int rx_option(int id, int otherwise);
    const int z = rx_option(11, 0);   /* (the menu's Stick dead zone) */
    uint64_t sig = 0;
    for (int k = BTN_A; k <= BTN_RIGHT; k++)
        if (hos_sdl_pad_button(pads[i].gc, k)) sig |= 1ULL << k;
    for (int k = 0; k < 4; k++) {   /* (as the poll's own: a stick by which way it is pushed, a resting one's noise no push) */
        const int16_t raw = hos_sdl_pad_axis(pads[i].gc, AX_LX + k);
        const int own = hos_stick_own(k >> 1);
        const int32_t a = stick_rests(raw, own) ? 0 : stick_value(raw, k & 1, z, own);
        sig |= (uint64_t)(a > 0 ? 1 : a < 0 ? 2 : 0) << (32 + 2 * k);
    }
    if (sig != pads[i].input_sig) pads[i].input_sig = sig, pads[i].used_ns = now;
}

/* (Triforce) Pad i's trigger t (0 left, 1 right) at its reading a (SDL's 0 to 32767): what it gives the game, a, or 0
   until it counts. It counts once it has read let go (8000 or below) for a second without a break since the pad was
   opened, as a stick steers once seen at rest. A device whose trigger reads held for good (a ShanWan USB receiver,
   2563:0575, beside the player's own pad) held ZL and ZR from every pad, kept the Controls page from listening for a
   binding (it waits for every input to be let go) and, once the Insert menu closed, kept the player's pads from the
   game (nn_hid.c: an input down at the close waits to be let go). One let-go reading was not enough: with that
   receiver plugged in, "seen let go once" still let its triggers through (a let-go reading as it opens, or for a moment
   now and then). A real trigger rests when its pad opens, so it counts after a second. The log says, once each: still
   not counting 3 s after the pad opened, counting after that, and held 30 s without a break once it counts, with the
   pad's name and the reading. tests/test_trigger_rest.py */
#define TRIGGER_REST_NS 1000000000LL
enum { TRIG_SAID_HELD = 1, TRIG_SAID_COUNTS = 4, TRIG_SAID_LONG = 16 };   /* (<< t: the left's bit, then the right's) */
static int trigger_pull(int i, int t, int a, int64_t now) {
    const char *side = t ? "right" : "left";
    if (a > 8000) {
        pads[i].trig_rest_ns[t] = 0;
        if (!pads[i].trig_held_ns[t]) pads[i].trig_held_ns[t] = now;
    } else {
        pads[i].trig_held_ns[t] = 0;
        if (!pads[i].trig_rest_ns[t]) pads[i].trig_rest_ns[t] = now;
        if (now - pads[i].trig_rest_ns[t] >= TRIGGER_REST_NS) pads[i].rested |= 1u << (AX_LT + t);
    }
    const int counts = pads[i].rested >> (AX_LT + t) & 1;
    if (!counts && now - pads[i].opened_ns >= 3000000000LL && !(pads[i].trig_said & TRIG_SAID_HELD << t)) {
        pads[i].trig_said |= TRIG_SAID_HELD << t;
        hos_log("hid: \"%s\": its %s trigger reads %d of 32767 and has not read let go for a second since it was "
                "opened, so it does not count until it does", hos_sdl_pad_name(pads[i].gc), side, a);
    }
    if (counts && (pads[i].trig_said & TRIG_SAID_HELD << t) && !(pads[i].trig_said & TRIG_SAID_COUNTS << t)) {
        pads[i].trig_said |= TRIG_SAID_COUNTS << t;
        hos_log("hid: \"%s\": its %s trigger has read let go for a second (%d of 32767): it counts from now",
                hos_sdl_pad_name(pads[i].gc), side, a);
    }
    if (counts && pads[i].trig_held_ns[t] && now - pads[i].trig_held_ns[t] >= 30000000000LL &&
        !(pads[i].trig_said & TRIG_SAID_LONG << t)) {
        pads[i].trig_said |= TRIG_SAID_LONG << t;
        hos_log("hid: \"%s\": its %s trigger has read held (%d of 32767) for 30 s without a break",
                hos_sdl_pad_name(pads[i].gc), side, a);
    }
    return counts ? a : 0;
}

/* one poll: controllers plugged in or gone (each second; (Triforce) each quarter second for the first two, while the
   button prompts' Auto waits for them: SCANS_FAST), then every open one's buttons, sticks and rumble */
#define SCANS_FAST 8
static void pads_poll(void) {
    static int64_t next_scan = 0;
    static int64_t gone_ns;   /* (Triforce) when a controller last disconnected, for the log */
    if (vib_force < 0) vib_force = vibration_force(getenv("HOS_RUMBLE_BACKEND"));   /* ((Triforce) host/vibration.h) */
    hos_sdl_pads_update();
        const int64_t now = hos_now_ns();
        const int scanned = now >= next_scan;
        if (scanned) {   /* new controllers (and ones that went away) */
            next_scan = now + (scans < SCANS_FAST ? 250000000LL : 1000000000LL);
            for (int i = 0; i < MAX_PADS; i++)
                if (pads[i].gc && !hos_sdl_pad_connected(pads[i].gc)) {
                    /* (Triforce) how long it had been connected: a pad that leaves after seconds or minutes, again and
                       again, is its link, its battery or another program taking it, and the log then shows the rhythm */
                    hos_log("hid: controller \"%s\" disconnected (SDL), %.0f s after it connected", hos_sdl_pad_name(pads[i].gc),
                            (now - pads[i].opened_ns) / 1e9);
                    gone_ns = now;
                    hos_pad_speaker_forget(pads[i].gc);   /* ((Triforce) the controller speaker lets go of it first */
                    vib_leave(i, now);   /* (and what played its vibration) */
                    hos_sdl_pad_close(pads[i].gc);
                    pads[i].gc = NULL;
                    pads[i].rumble_lo = pads[i].rumble_hi = 0;
                    pads[i].rumble_ns = 0;
                    pads[i].motion = pads[i].motion_on = 0;
                }
            int32_t ids[32];
            int opens[32];
            const int nj = hos_sdl_pads_list(ids, opens, 32);
            for (int j = 0; j < nj; j++) {
                const int32_t id = ids[j];
                int have = 0, slot = -1;
                for (int i = 0; i < MAX_PADS; i++) {
                    if (pads[i].gc && pads[i].id == id) have = 1;
                    if (!pads[i].gc && slot < 0) slot = i;
                }
                if (have || slot < 0) continue;
                void *gc = hos_sdl_pad_open(opens[j]);
                if (!gc) continue;
                pads[slot].gc = gc;
                pads[slot].id = hos_sdl_pad_id(gc);
                pads[slot].rumble_lo = pads[slot].rumble_hi = 0;
                pads[slot].rumble_ns = 0;
                pads[slot].trigger = 0, pads[slot].trigger_said = 0;
                pads[slot].trigger_ns = pads[slot].trigger_retry_ns = 0;
                hd_open(slot, gc);
                /* ((Triforce) what plays its vibration is chosen by the poll below, host/vibration.h) */
                pads[slot].vib = -1, pads[slot].vib_failed = -1, pads[slot].vib_retry_ns = 0;
                pads[slot].usb_token = -1, pads[slot].usb_next_look = 0;
                memset(pads[slot].four, 0, sizeof pads[slot].four), pads[slot].four_ns = 0;
                pads[slot].vib_product = hos_sdl_pad_product(gc);
                pads[slot].vib_kind = (int8_t)vibration_pad_kind(hos_sdl_load(), hos_sdl_pad_type(gc), hos_sdl_pad_name(gc),
                                                                 hos_sdl_pad_vendor(gc), pads[slot].vib_product);
                pads[slot].wireless = (int8_t)hos_sdl_pad_wireless(gc);
                pads[slot].motion = hos_sdl_pad_has_sensor(gc, HOS_SDL_SENSOR_GYRO) && hos_sdl_pad_has_sensor(gc, HOS_SDL_SENSOR_ACCEL);
                pads[slot].motion_on = 0;
                pads[slot].motion_retry_ns = 0;
                pads[slot].used_ns = now, pads[slot].input_sig = 0;   /* (just connected: the one about to be used) */
                pads[slot].rested = 0;
                memset(pads[slot].held, 0, sizeof pads[slot].held);
                pads[slot].opened_ns = now;   /* ((Triforce) before the first poll: trigger_pull counts from it) */
                pads[slot].trig_held_ns[0] = pads[slot].trig_held_ns[1] = 0;
                pads[slot].trig_rest_ns[0] = pads[slot].trig_rest_ns[1] = 0;
                pads[slot].trig_said = 0;
                pads[slot].serial = ++pads_opened;
                pads[slot].has_bias = 0;
                /* ((Triforce) 11-24: who it is, for host/steam_pads.h's rules; all 0 with HOS_STEAM_PADS=0, and from an
                   SDL that cannot say, so no rule takes it) */
                pads[slot].vendor = steam_rules() ? hos_sdl_pad_vendor(gc) : 0;
                pads[slot].product = steam_rules() ? hos_sdl_pad_product(gc) : 0;
                pads[slot].steam = steam_rules() ? hos_sdl_pad_steam_handle(gc) : 0;
                pads[slot].motion_only = 0;   /* (the poll below decides, and says so) */
                hos_sdl_pad_log_connection(gc, pads[slot].motion);   /* ((Triforce) with its GUID and mapping: host/hos_sdl.c) */
                if (pads[slot].steam) hos_log("hid: that controller is Steam Input's");
                pads[slot].opened_ns = now;
                if (gone_ns && now - gone_ns < 60000000000LL)
                    hos_log("hid: that is %.1f s after a controller disconnected", (now - gone_ns) / 1e9);
            }
            {   /* ((Triforce) the controller speaker follows the DualSense that is open (host/pad_speaker.c): the first known on
                   a cable, else the first whose transport SDL cannot say */
                void *dualsense = NULL;
                int wired = 0;
                for (int i = 0; i < MAX_PADS; i++) {
                    const char *name = pads[i].gc ? hos_sdl_pad_name(pads[i].gc) : NULL;
                    if (!name || hos_sdl_pad_vendor(pads[i].gc) != 0x054c || (!strstr(name, "DualSense") && !strstr(name, "PS5")))
                        continue;
                    const int wireless = hos_sdl_pad_wireless(pads[i].gc);
                    if (wireless == 0) { dualsense = pads[i].gc; wired = 1; break; }
                    if (wireless < 0 && !dualsense) { dualsense = pads[i].gc; wired = 1; }
                }
                hos_pad_speaker_pad(dualsense, wired);
            }
        }
        uint64_t b = 0;
        int32_t s[4] = {0};
        int count = 0;
        int rx_option(int id, int otherwise);
        int strength = rx_option(9, 100);   /* (the menu's Rumble strength: the motors' and HD rumble's) */
        /* ((Triforce) the menu's Vibration (Auto, Basic, Off: host/vibration.h). Rumble strength Off is Vibration Off; its
           percent is every backend's (RenHDrum's up to 200) */
        int mode = rx_option(HOS_OPT_VIBRATION, VIB_MODE_AUTO);
        if (mode < VIB_MODE_AUTO || mode > VIB_MODE_OFF) mode = VIB_MODE_AUTO;
        if (strength <= 0) mode = VIB_MODE_OFF;
        /* (RenHDrum's backends: a side gone quiet, the strength, and the menu's DualSense HD Haptics) */
        {   /* ((Triforce) the cable's voice coils at the ocarina's share while it plays on the pad's speaker, host/pad_speaker.c) */
            const int rh_strength = strength > 0 ? strength : 100;
            rh_tick(now, 0, rh_strength, rh_strength * hos_pad_speaker_pad_rumble_percent(rh_usb_owner()) / 100,
                    rx_option(HOS_OPT_DS_HD_HAPTICS, 1) != 0);
        }
        /* ((Triforce) the menu's Vibration curve: the motors' alone. A Switch controller's HD rumble has its own,
           hd_rumble.h's hd_rumble_felt, and plays the game's values by it whatever this row says) */
        const int curve = rx_option(HOS_OPT_RUMBLE_CURVE, 100);
        const int triggers = rx_option(HOS_OPT_RUMBLE_TRIGGERS, 0) != 0;   /* ((Triforce) the menu's Trigger vibration) */
        uint16_t motors[2];
        rumble_strength(rumble_curve((uint16_t)rumble_low, curve), rumble_curve((uint16_t)rumble_high, curve), strength,
                        motors);
        const uint16_t lo = motors[0], hi = motors[1];
        uint8_t side[3][4];   /* (the HD rumble pads': each side's bytes, then both merged for a single Joy-Con) */
        {
            float hv[2][4], felt[3][4];
            AcquireSRWLockShared(&hd_lock);
            memcpy(hv, hd_values, sizeof hv);
            ReleaseSRWLockShared(&hd_lock);
            hd_rumble_felt(hv[0], felt[0]);   /* (the game's small amplitudes, as the motors get them) */
            hd_rumble_felt(hv[1], felt[1]);
            hd_rumble_encode(felt[0], strength, side[0]);
            hd_rumble_encode(felt[1], strength, side[1]);
            hd_rumble_merge(felt[0], felt[1], felt[2]);
            hd_rumble_encode(felt[2], strength, side[2]);
        }
        int stand_in = 0;       /* ((Triforce) 11-24) a Steam stand-in pad open (host/steam_pads.h) */
        int64_t status_used = -1;   /* ((Triforce) the menu's vibration line: the pad used last */
        int status_pad = -1;
        int deck_builtin = 0;   /* (and the Steam Deck's built-in controls giving input: its mouse must not) */
        for (int i = 0; i < MAX_PADS; i++) stand_in |= pads[i].gc && pads[i].steam;
        for (int i = 0; i < MAX_PADS; i++) {
            void *gc = pads[i].gc;
            if (!gc) continue;
            /* ((Triforce) 11-24) a real Valve pad beside its Steam stand-in: its motion is read (motion_poll), its
               buttons and sticks come through the stand-in as the player's Steam layout maps them, so they are not
               merged twice, and its rumble goes through Steam too. Its own presses still mark it the pad used last,
               for motion. Never without a stand-in pad open: every other pad plays as before */
            const int motion_only = steam_pads_motion_only(pads[i].vendor, pads[i].steam, stand_in);
            if (motion_only != pads[i].motion_only) {
                pads[i].motion_only = motion_only;
                /* ((Triforce) its rumble goes through Steam's stand-in now: what played it here lets go, or it would play
                   twice) */
                if (motion_only && pads[i].vib >= 0) vib_leave(i, now);
                /* (a real Valve pad this SDL opens with no gyroscope: an SDL with no driver for it, so the loosened
                   list gives no motion, said once so the next person without motion sees why) */
                if (motion_only && !pads[i].motion)
                    hos_log("hid: \"%s\": no motion sensors through this SDL, so Motion controls can't read it; "
                            "its buttons come through Steam Input's pad", hos_sdl_pad_name(gc));
                else
                    hos_log(motion_only ? "hid: \"%s\": motion only, its buttons come through Steam Input's pad"
                                        : "hid: \"%s\": its buttons count again (no Steam Input pad is open)",
                            hos_sdl_pad_name(gc));
            }
            if (motion_only) {
                motion_only_used(i, now);
                continue;
            }
            if (steam_pads_deck_builtin(pads[i].vendor, pads[i].product, pads[i].steam)) deck_builtin = 1;
            count++;
            for (int k = BTN_A; k <= BTN_RIGHT; k++)   /* (SDL3's gamepad buttons are in SDL2's order) */
                if (hos_sdl_pad_button(gc, k)) b |= 1ULL << k;
            /* a DualShock 4's or DualSense's touchpad click: with the Menu shortcut row's touchpad choices it opens the Insert
               menu as F1 does (vk_menu.cpp). SDL numbers it 20 in both SDL2 and SDL3; an SDL or a pad without it answers 0 */
            if (hos_sdl_pad_button(gc, BTN_TOUCHPAD)) b |= 1ULL << HOS_PAD_TOUCHPAD;
            /* ((Triforce) 11-24) the rear paddles, SDL's 16 to 19 (SDL2's PADDLE1 to 4 in the same places): inputs a binding
               can take, HOS_PAD_RPADDLE1 on */
            for (int k = BTN_RPADDLE1; k <= BTN_LPADDLE2; k++)
                if (hos_sdl_pad_button(gc, k)) b |= 1ULL << (HOS_PAD_RPADDLE1 + k - BTN_RPADDLE1);
            /* (Triforce) A trigger presses once it has read let go for a second since the pad was opened (trigger_pull) */
            for (int t = 0; t < 2; t++)
                if (trigger_pull(i, t, hos_sdl_pad_axis(gc, AX_LT + t), now) > 8000)
                    b |= 1ULL << (t ? HOS_PAD_RTRIGGER : HOS_PAD_LTRIGGER);
            const int inv_x = rx_option(16, 0);
            const int inv_y = rx_option(17, 0);
            const int z = rx_option(11, 0);   /* (the menu's Stick dead zone: nn_hid.c's hos_stick_axis) */
            const int own[2] = {hos_stick_own(0), hos_stick_own(1)};   /* ((Triforce) each stick's own, -1 none) */
            const int16_t raw[4] = {hos_sdl_pad_axis(gc, AX_LX), hos_sdl_pad_axis(gc, AX_LY), hos_sdl_pad_axis(gc, AX_RX),
                                    hos_sdl_pad_axis(gc, AX_RY)};
            int32_t v[4];   /* ((Triforce) each stick cut as a pair, so a push near an axis keeps its direction) */
            hos_filter_stick(raw[0], raw[1], z, own[0], v);
            hos_filter_stick(raw[2], raw[3], z, own[1], v + 2);
            v[1] = -v[1], v[3] = -v[3];   /* (SDL's Y axes point down) */
            /* (hookshot) An axis steers once it has been seen at rest (inside the dead zone) since the pad was opened. The sticks are
               the strongest of all the pads', so a device whose axis reads held for good (a mapping that puts a trigger or an
               unused axis on a stick, a second virtual pad) turned the camera or walked Link in circles on its own, with the
               player's pad at rest (#1673: Xbox 360 pad, CachyOS; #1661: GameSir 2 Lite, wired). A real stick rests at the start. */
            /* (a worn stick resting just past a small dead zone counts once it is pushed the other way: it went past its rest) */
            /* ((Triforce) with a dead zone of its stick's own, an axis inside the default one is at rest too: stick_rests) */
            /* (rest is judged axis by axis, as before the circle: a phantom axis held past the dead zone keeps its partner
               outside the circle, and the partner must still rest at its own centre) */
            for (int k = 0; k < 4; k++) {
                const int32_t alone = stick_value(raw[k], k & 1, z, own[k >> 1]);   /* (the axis by itself, cut as one) */
                const signed char way = (signed char)(alone > 0 ? 1 : alone < 0 ? -1 : 0);
                if (!way || (pads[i].held[k] && way != pads[i].held[k]) || stick_rests(raw[k], own[k >> 1]))
                    pads[i].rested |= 1u << k;
                pads[i].held[k] = way;
                if (!(pads[i].rested >> k & 1)) v[k] = 0;
            }
            /* (an axis held back above no longer counts toward its stick's circle, so its partner's drift stays inside
               the dead zone. The values are clamped already and the circle keeps them, so nothing else changes) */
            hos_filter_stick((int16_t)v[0], (int16_t)v[1], z, own[0], v);
            hos_filter_stick((int16_t)v[2], (int16_t)v[3], z, own[1], v + 2);
            /* ((Triforce, 11-26, a player's input recording: "clicking the left stick stops rolling when moving forward") A
               push past 92% of the travel is a full one, in its direction. SDL's Switch driver widens an axis's range to the
               furthest it has read: after a hard click at full tilt the same full push forward read 31083, then ~30600 (93-95%),
               and the game rolls only from a full one (angled pushes, past 32767 together, still rolled) */
            for (int st = 0; st < 4; st += 2) {
                const double m = sqrt((double)v[st] * v[st] + (double)v[st + 1] * v[st + 1]);
                if (m >= 30146.0 && m < 32767.0) {   /* (30146: 92% of 32767) */
                    for (int a = st; a < st + 2; a++) {
                        const double x = v[a] * 32767.0 / m;
                        v[a] = x >= 32767 ? 32767 : x <= -32767 ? -32767 : (int32_t)(x < 0 ? x - 0.5 : x + 0.5);
                    }
                }
            }
            /* Camera inversion changes output, not whether the physical stick crossed its rest position. Otherwise
               toggling the setting admits a held phantom axis, which stays admitted after the setting is restored. */
            if (inv_x) v[2] = -v[2];
            if (inv_y) v[3] = -v[3];
            for (int k = 0; k < 4; k++)
                if ((v[k] < 0 ? -v[k] : v[k]) > (s[k] < 0 ? -s[k] : s[k])) s[k] = v[k];
            {   /* (motion: the pad last used; a stick counts by which way it is pushed, not by how far) */
                uint64_t sig = 0;
                for (int k = BTN_A; k <= BTN_RIGHT; k++)
                    if (hos_sdl_pad_button(gc, k)) sig |= 1ULL << k;
                for (int k = 0; k < 4; k++) {   /* ((Triforce) a resting stick's noise past a small zone of its own is no push) */
                    const int32_t u = stick_rests(raw[k], own[k >> 1]) ? 0 : v[k];
                    sig |= (uint64_t)(u > 0 ? 1 : u < 0 ? 2 : 0) << (32 + 2 * k);
                }
                if (sig != pads[i].input_sig) pads[i].input_sig = sig, pads[i].used_ns = now;
            }
            /* ((Triforce) what plays its vibration: chosen again each poll (host/vibration.h), then played. Without RenHDrum
               and with Vibration on Auto: HD rumble for a Switch pad, the motors (and Trigger vibration) otherwise, as before */
            vib_choose(i, mode, now);
            if (pads[i].used_ns >= status_used) status_used = pads[i].used_ns, status_pad = i;
            if (pads[i].vib == VIB_NONE) continue;
            if (pads[i].vib == VIB_HD)   /* (refused: its motors this poll, and chosen again at the next) */
                if (hd_poll(i, side, now)) continue;
            if (pads[i].vib == VIB_RH_DS_USB || pads[i].vib == VIB_RH_DS_BT) {   /* (their own threads play) */
                /* (HD Haptics' triggers: how far each is pulled, 0 to 255, and whether another button is held) */
                const int lt = hos_sdl_pad_axis(gc, AX_LT), rt = hos_sdl_pad_axis(gc, AX_RT);
                rh_ds_triggers(gc, now, lt > 0 ? lt * 255 / 32767 : 0, rt > 0 ? rt * 255 / 32767 : 0,
                               (pads[i].input_sig & 0xFFFFFFFFULL) != 0);
                continue;
            }
            if (pads[i].vib == VIB_RH_STEAM) continue;   /* (its own thread plays) */
            if (pads[i].vib == VIB_RH_XBOX) {
                four_poll(i, now, triggers);
                continue;
            }
            if (pads[i].vib == VIB_RH_SWITCH) {
                uint8_t packet[HD_RUMBLE_PACKET_SIZE];
                if (rh_switch_poll(gc, now, packet)) hos_sdl_pad_effect(gc, packet, sizeof packet);
                continue;
            }
            /* ((Triforce) the ocarina playing on this pad's speaker: its motors at that share, host/pad_speaker.c) */
            uint16_t pad_motors[2] = {motors[0], motors[1]};
            const int pad_percent = hos_pad_speaker_pad_rumble_percent(gc);
            if (pad_percent != 100)
                rumble_strength(rumble_curve((uint16_t)rumble_low, curve), rumble_curve((uint16_t)rumble_high, curve),
                                strength * pad_percent / 100, pad_motors);
            const uint16_t lo = pad_motors[0], hi = pad_motors[1];   /* (this pad's: the poll's own, but for that) */
            if (rumble_due(lo, hi, pads[i].rumble_lo, pads[i].rumble_hi, now, pads[i].rumble_ns)) {
                hos_sdl_pad_rumble(gc, lo, hi, lo || hi ? 1000 : 0);
                pads[i].rumble_lo = lo;
                pads[i].rumble_hi = hi;
                pads[i].rumble_ns = now;
            }
            trigger_poll(i, triggers ? hi : 0, now);   /* ((Triforce) the light motor's rumble, in the triggers too) */
        }
        {   /* ((Triforce) the menu's vibration line: what plays the pad used last (host/vibration.h) */
            void rx_option_set(int id, int value);
            int st = vibration_status(VIB_PAD_OTHER, VIB_SAY_NO_PAD);
            if (status_pad >= 0) {
                const int k = pads[status_pad].vib_kind;
                st = vibration_status(k, vibration_say(pads[status_pad].vib, k, pads[status_pad].wireless, vib_rh_for(k),
                                                       mode));
            }
            rx_option_set(HOS_OPT_VIBRATION_STATUS, st);   /* (each poll: a menu loaded later has it at once) */
        }
        motion_poll(now, count);
        AcquireSRWLockExclusive(&state_lock);
        state_buttons = b;
        memcpy(state_stick, s, sizeof s);
        state_count = count;
        state_deck_builtin = deck_builtin;
        state_name[0] = 0;
        state_type = 0;
        for (int i = 0; i < MAX_PADS; i++)
            if (pads[i].gc && !pads[i].motion_only) {   /* ((Triforce) 11-24: the stand-in's name, not its motion-only pad's) */
                const char *name = hos_sdl_pad_name(pads[i].gc);
                snprintf(state_name, sizeof state_name, "%s", name ? name : "");
                state_type = hos_sdl_pad_type(pads[i].gc);   /* ((Triforce) read each time, as the name) */
                break;
            }
        {   /* ((Triforce) the one used last: its name, for the overlay's icons and Auto's next start) */
            int last = -1;
            for (int i = 0; i < MAX_PADS; i++)   /* ((Triforce) 11-24: the pad that plays, not a motion-only one beside it) */
                if (pads[i].gc && !pads[i].motion_only && (last < 0 || pads[i].used_ns > pads[last].used_ns)) last = i;
            const char *name = last >= 0 ? hos_sdl_pad_name(pads[last].gc) : NULL;
            snprintf(state_last_name, sizeof state_last_name, "%s", name ? name : "");
            state_last_type = last >= 0 ? hos_sdl_pad_type(pads[last].gc) : 0;
        }
        ReleaseSRWLockExclusive(&state_lock);
        if (scanned && scans >= 0) InterlockedIncrement(&scans);   /* (after the names: a scan counted has them) */
}

static DWORD WINAPI pad_main(void *arg) {
    (void)arg;
    hos_host_thread_register_self("gamepads (SDL)");
    if (!pads_start()) return 0;
    for (;;) {
        pads_poll();
        Sleep(4);
    }
}
#ifndef _WIN32
int hos_display_owns_sdl(void);   /* host/posix/display_sdl.c */
/* (linux) SDL also runs the window (host/posix/display_sdl.c), and its event queue is not for two threads. Polled
   from the window's thread, between its events. Two threads pumping it corrupted the heap once a controller was
   attached. */
static volatile LONG pads_loaded;
void hos_sdl_pads_pump(void) {
    static int state;   /* 0 not started, 1 polling, -1 not available */
    if (!state && pads_loaded) state = pads_start() ? 1 : -1;
    if (state > 0) pads_poll();
}
#endif

/* The controllers' merged state (nn_hid.c): ORs their inputs in (1 << HOS_PAD_*), keeps the larger stick
   deflections; returns how many controllers SDL has open. Starts the SDL thread on the first call. */
int hos_sdl_pads(uint64_t *buttons, int32_t stick[4]) {
    static volatile LONG started;
    if (!started && !InterlockedExchange(&started, 1)) {
        if (getenv("HOS_NO_SDL")) {
            InterlockedExchange(&scans, -1);
            return 0;
        }
        if (!hos_sdl_load()) {
            hos_log("hid: no SDL beside the exe or on the system: only XInput controllers (Xbox pads) work");
            InterlockedExchange(&scans, -1);
            return 0;
        }
#ifdef _WIN32
        CreateThread(NULL, 0, pad_main, NULL, 0, NULL);
#else
        if (hos_display_owns_sdl())
            InterlockedExchange(&pads_loaded, 1);   /* (the window's thread polls: hos_sdl_pads_pump) */
        else
            CreateThread(NULL, 0, pad_main, NULL, 0, NULL);   /* (no window: nothing else pumps SDL) */
#endif
    }
    AcquireSRWLockShared(&state_lock);
    const int n = state_count;
    *buttons |= state_buttons;
    for (int k = 0; k < 4; k++)
        if ((state_stick[k] < 0 ? -state_stick[k] : state_stick[k]) > (stick[k] < 0 ? -stick[k] : stick[k]))
            stick[k] = state_stick[k];
    ReleaseSRWLockShared(&state_lock);
    return n;
}
/* ((Triforce) 11-24, nn_hid.c) Whether the Steam Deck's built-in controls gave input in the last poll
   (host/steam_pads.h steam_pads_deck_builtin): their mouse's buttons and motion are then no control's. 0 without SDL,
   before its first poll, with HOS_STEAM_PADS=0, and on every PC that is not a Steam Deck */
int hos_sdl_pads_deck_builtin(void) {
    AcquireSRWLockShared(&state_lock);
    const int deck = state_deck_builtin;
    ReleaseSRWLockShared(&state_lock);
    return deck;
}

/* (motion) the latest readings for nn_hid.c's GetSixAxisSensorStates, newest first: up to max, how many there are; 0
   when there are none (Motion controls off, or no pad with a gyroscope) */
int hos_sdl_motion_history(HosMotionSample *out, int max) {
    AcquireSRWLockShared(&state_lock);
    const int n = !motion_live ? 0 : motion_count < max ? motion_count : max;
    for (int i = 0; i < n; i++) out[i] = motion_hist[(motion_head - i + HOS_MOTION_HISTORY) % HOS_MOTION_HISTORY];
    ReleaseSRWLockShared(&state_lock);
    return n;
}
/* (the Insert menu's Motion controls row) 0 no controller, 1 controllers with no gyroscope, 2 one with a gyroscope */
int hos_sdl_gyro_status(void) { return (int)gyro_status; }
/* The first open controller's name into out ("" with none) */
void hos_sdl_pad_first_name(char *out, size_t cap) {
    AcquireSRWLockShared(&state_lock);
    snprintf(out, cap, "%s", state_name);
    ReleaseSRWLockShared(&state_lock);
}
/* ((Triforce) The name of the open controller used last into out ("" with none) */
void hos_sdl_pad_last_name(char *out, size_t cap) {
    AcquireSRWLockShared(&state_lock);
    snprintf(out, cap, "%s", state_last_name);
    ReleaseSRWLockShared(&state_lock);
}
/* ((Triforce) The SDL type of the first open controller (last 0) or of the one used last (last 1): SDL_GetGamepadType's or
   SDL_GameControllerGetType's number, 0 with none or unknown; *sdl the SDL it is of (3, 2; 0 none loaded) */
int hos_sdl_pad_type_of(int last, int *sdl) {
    AcquireSRWLockShared(&state_lock);
    const int type = last ? state_last_type : state_type;
    ReleaseSRWLockShared(&state_lock);
    *sdl = type ? hos_sdl_load() : 0;   /* (loaded already: a pad is open) */
    return type;
}
/* ((Triforce) The scans for controllers done so far (pads_poll's: the first at once, then each quarter second for the
   first SCANS_FAST, then each second); -1 when SDL will not run */
int hos_sdl_pad_scans(void) { return (int)scans; }

/* Vibration from the game (0..1 amplitudes of the low and high bands), for the pads that rumble. */
void hos_sdl_rumble(float low, float high) {
    if (low < 0) low = 0;
    if (low > 1) low = 1;
    if (high < 0) high = 0;
    if (high > 1) high = 1;
    InterlockedExchange(&rumble_low, (LONG)(low * 65535));
    InterlockedExchange(&rumble_high, (LONG)(high * 65535));
}

/* The game's own vibration value for one side (0 left, 1 right; {amp_low, freq_low, amp_high, freq_high}), for the
   pads that play HD rumble (hd_rumble.h); nn_hid.c's vibration_send, beside hos_sdl_rumble. */
void hos_sdl_rumble_hd(int side, const float value[4]) {
    AcquireSRWLockExclusive(&hd_lock);
    memcpy(hd_values[side & 1], value, sizeof hd_values[0]);
    ReleaseSRWLockExclusive(&hd_lock);
}

/* ((Triforce) the game is over: RenHDrum's backends stop and let go of the pads (host/rumble_renhdrum.c); hos_main.c calls
   it once nnMain has returned */
void hos_sdl_vibration_shutdown(void) { rh_shutdown(); }
