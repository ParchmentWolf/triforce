/* (hookshot) The button prompts of the controller in use: the game's button-icon font (Font2/Scalable/External.*.bfotf,
   every icon in a text: dialogue, the control hints, menus) served from prompts/<face>/External.bfotf in the game folder,
   which nx2/prompt_assets.py draws per controller face at build time, with each Switch button's icon pointed at the icon of
   the pad input bound to it (host/nn_hid.c's controls, the menu's Layout preset and Controls page). So the icons say which
   button to press on this pad, custom controls too.

   The face: triforce_options.ini's button_prompts (the menu's Button prompts row): 0 Auto, from the first controller's name
   (SDL), else 1 Switch, 2 Xbox, 3 PlayStation 4, 4 PlayStation 5, 5 Steam Deck, 6 Keyboard & mouse. The game reads the font
   once, at its start; ((Triforce) among the controllers' faces) a new face or new controls are written where it keeps it, and
   its texts drawn again (the live part, below). The keyboard and mouse face, or a change to or from it, still at the next start.

   (Triforce, 11-19) Auto follows the device used last over runs: with no controller there at the start it takes the face of
   the device the player used last in the run before (<user>/prompts_auto.txt, follow_main). And while the game has the keys'
   face, the overlay's own prompts (the Insert menu, Mods, the Quit dialog, the options' tabs) show the icons of the
   controller used last, from a font of that controller's face built during play (prompts/External.pad.<n>.bfotf.zs, n
   its HOS_PROMPT_*): the game's own texts keep the face they were given at the start.

   (Triforce) The keyboard and mouse face (NX2navi's prompts = pc; nx2/prompt_keys.py draws it): its font has an icon per
   key that can be bound, at U+F700 + the key's code, and each button's icon is that of the first key bound to it
   (bound_input). The left stick's and the d-pad's icons there are those keys side by side (bind_keys); the right stick's
   are the mouse. Auto chooses it when the game starts with no controller (auto_face).

   The font as built: an OpenType font behind an 8-byte header, XORed per little-endian word with the key the header's magic
   (0x18029a7f) gives. Its cmap has one icon per pad input at U+F700 + HOS_PAD_*, and each Switch button's code point in a
   format 4 segment of its own, by idDelta: pointing a button at another icon is that segment's idDelta. The result goes out
   as a zstd frame of raw blocks (the file name says .zs; the game's decoder takes a frame made without its dictionary). */
#include "hos.h"
#include "hos_paths.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "../gpu/vk/vk_api.h"   /* (HOS_SW_*, HOS_PAD_*, HOS_BIND_PAD) */
#include "hd_rumble.h"   /* ((Triforce) hd_rumble_kind: SDL's types of the Switch's controllers, face_of_type) */

int hos_binding(int set, int button, int slot);   /* nn_hid.c */
int hos_sdl_pads(uint64_t *buttons, int32_t stick[4]);   /* pad_sdl.c */
void hos_sdl_pad_first_name(char *out, size_t cap);
int hos_xinput_connected(void);   /* nn_hid.c */
int hos_input_last(void);   /* nn_hid.c: 0 none yet, 1 the keys or the mouse, 2 a controller */
unsigned hos_input_uses(int device);   /* nn_hid.c: that device's uses so far */
extern const char *hos_user_dir;   /* nn_fs.c: the saves' folder */
void hos_sdl_pad_last_name(char *out, size_t cap);   /* pad_sdl.c */
int hos_sdl_pad_type_of(int last, int *sdl);   /* pad_sdl.c */
int hos_sdl_pad_scans(void);
void hos_host_thread_register_self(const char *name);   /* hos_prof.c */
int hos_mods_has(const char *prefix, const char *suffix);   /* mods.c */
int rx_option(int id, int otherwise);   /* rx_backend.c: the Insert menu's rows */
float hos_wide_hud_out(void);   /* oot_wide_hud.c */

#define FONT_PATH "font2/scalable/external.nin_ounce_nvn2.bfotf.zs"   /* (as hos_mods_romfs's keys: lower case) */
#define TEXTURES_PATH "ui/layout2archive/common.product.100.nin_ounce_nvn2.bntx.zs"
#define LAYOUTS_PATH "ui/layout2archive/common.product.100.nin_ounce_nvn2.blarc.zs"
#define SIZES_PATH "system/resource/resourcesizetable."   /* (then the version, ".rsizetable.zs") */
#define CAMERA_PATH "pack/actor/playercamera.pack.zs"   /* (Triforce: the Camera speed row, build_camera) */
#define MAGIC 0x18029a7fu
#define PAD_BASE 0xF700
static const char *const faces[HOS_PROMPT_N] = {"switch", "xbox", "ps4", "ps5", "steamdeck", "keyboard"};
/* the Switch buttons' code points in the font, in HOS_SW_* order (nx2/prompt_assets.py SWITCH) */
static const uint16_t switch_code[HOS_SW_N] = {0xE040, 0xE041, 0xE042, 0xE043, 0xE056, 0xE057, 0xE044, 0xE045,
                                               0xE046, 0xE047, 0xE04B, 0xE04C, 0xE062, 0xE060, 0xE063, 0xE061};
/* ((Triforce) the live part's codes, nx2/prompt_assets.py faces_font: each controller face's (HOS_PROMPT_* below
   LIVE_FACES) icon of pad input i at FACE_BASE + FACE_CODES x face + i and its d-pad icons at + STATIC_AT..; a text's code for
   Switch button b on pad input i of a face at BIND_BASE + (face x HOS_SW_N + b) x HOS_PAD_N + i. A font built before has none
   of them: then nothing follows while the game runs) */
#define LIVE_FACES HOS_PROMPT_KEYBOARD
#define FACE_BASE 0xF800
#define FACE_CODES 32
#define STATIC_AT 24
#define BIND_BASE 0xF000
/* ((Triforce VR) nx2/prompt_vr.py: for each control scheme (vr_game.c vr_prompts_scheme, 1 Full Gesture, 2 Simplified) each
   Switch button's code at VR_SW_BASE + 16 x (scheme - 1) + HOS_SW_*, the hand controllers' control that presses it. While a VR
   session plays the Switch buttons are pointed at those (cmap4_bind, text_code) */
#define VR_SW_BASE 0xF680
int vr_prompts_scheme(void);   /* vr_game.c */
static int live_vr_now;   /* (the scheme the icons show now, 0 none) */
/* the pad input whose icon an unbound Switch button shows (nx2/prompt_assets.py DEFAULT: host/nn_hid.c's default controls) */
static const unsigned char switch_pad[HOS_SW_N] = {
    HOS_PAD_EAST, HOS_PAD_SOUTH, HOS_PAD_NORTH, HOS_PAD_WEST, HOS_PAD_LSTICK, HOS_PAD_RSTICK, HOS_PAD_LSHOULDER,
    HOS_PAD_RSHOULDER, HOS_PAD_LTRIGGER, HOS_PAD_RTRIGGER, HOS_PAD_START, HOS_PAD_BACK, HOS_PAD_LEFT, HOS_PAD_UP,
    HOS_PAD_RIGHT, HOS_PAD_DOWN};
/* the d-pad icons that follow the face, not the controls (nx2/prompt_assets.py STATIC) */
static const uint16_t static_code[3] = {0xE049, 0xE064, 0xE065};

static int game_dir(char *out, size_t cap) {   /* the game folder, with its separator */
    char path[MAX_PATH];
    const DWORD len = hos_game_path_a(path, MAX_PATH);
    char *slash = len ? (strrchr(path, 92) ? strrchr(path, 92) : strrchr(path, 47)) : NULL;   /* (linux: '/') */
    if (!slash) return 0;
    slash[1] = 0;
    snprintf(out, cap, "%s", path);
    return 1;
}

static int contains(const char *text, const char *word) {   /* (any case) */
    for (; *text; text++) {
        size_t i = 0;
        while (word[i] && tolower((unsigned char)text[i]) == word[i]) i++;
        if (!word[i]) return 1;
    }
    return 0;
}

/* (Triforce) Auto's face: the first controller's, from its name (SDL's; "": it has none). xinput: XInput has a controller
   that SDL does not name (HOS_NO_SDL=1, no SDL beside the game, or one SDL had not opened yet): the Xbox's, as XInput
   reads only pads of the Xbox's layout ((11-19) it was the Switch's: an Xbox pad SDL had not opened in time showed the
   Switch's letters). With none, remembered: the face of the device used last in the run before (remembered_face,
   follow_main; -1 none), so a controller switched on after the game started is the face at the next start; without one
   the keyboard and mouse are what the player has: their keys' icons.
   The game reads its icons once, at its start, so Auto is chosen once, then: its texts cannot follow the device used last
   during play, as NX2navi's prompts setting could not. A controller that is there at the start is the face even while the
   keys are used with it, so the two never take turns */
static int auto_face(const char *name, int xinput, int remembered) {
    if (!name[0]) return xinput ? HOS_PROMPT_XBOX : remembered >= 0 && remembered < HOS_PROMPT_N ? remembered : HOS_PROMPT_KEYBOARD;
    if (contains(name, "dualsense") || contains(name, "ps5")) return HOS_PROMPT_PS5;
    if (contains(name, "dualshock") || contains(name, "ps4") || contains(name, "playstation")) return HOS_PROMPT_PS4;
    /* (a Steam Controller names its buttons as the Deck does: L1/R1, View, Menu, Steam. SDL3 calls it "Steam Controller") */
    if (contains(name, "steam deck") || contains(name, "steam controller")) return HOS_PROMPT_STEAMDECK;
    if (contains(name, "nintendo") || contains(name, "switch") || contains(name, "joy-con")) return HOS_PROMPT_SWITCH;
    return HOS_PROMPT_XBOX;   /* (Xbox pads, and the many that copy their layout) */
}

/* (Triforce) The face of a controller by the type SDL gives it (sdl: the SDL it came from, 3 or 2; type: SDL_GetGamepadType's
   or SDL_GameControllerGetType's number), HOS_PROMPT_*; -1 for a type that names no face (unknown, standard, virtual, the
   others). SDL knows the type from the pad's USB ids, where names vary ("Wireless Controller" is a DualShock 4 or a
   DualSense on some systems) */
static int face_of_type(int sdl, int type) {
    if (hd_rumble_kind(sdl, type) != HD_RUMBLE_NONE) return HOS_PROMPT_SWITCH;   /* (a Pro Controller, Joy-Cons) */
    if (sdl == 3) {   /* (SDL_GAMEPAD_TYPE_XBOX360 2, XBOXONE 3, PS3 4, PS4 5, PS5 6) */
        if (type == 2 || type == 3) return HOS_PROMPT_XBOX;
        if (type == 4 || type == 5) return HOS_PROMPT_PS4;
        if (type == 6) return HOS_PROMPT_PS5;
    } else if (sdl == 2) {   /* (SDL_CONTROLLER_TYPE_XBOX360 1, XBOXONE 2, PS3 3, PS4 4, PS5 7) */
        if (type == 1 || type == 2) return HOS_PROMPT_XBOX;
        if (type == 3 || type == 4) return HOS_PROMPT_PS4;
        if (type == 7) return HOS_PROMPT_PS5;
    }
    return -1;
}

/* (Triforce) A named controller's face with its SDL type: a name that says its maker's buttons wins (auto_face: any face
   but the Xbox's, which is also what a name that says nothing comes to); such a name asks the type (a HORIPAD for the
   Switch, "Wireless Controller"), and keeps the Xbox's when the type names no face either */
static int typed_face(int named, const char *name, int sdl, int type) {
    if (!name[0] || named != HOS_PROMPT_XBOX || contains(name, "xbox")) return named;
    const int by_type = face_of_type(sdl, type);
    return by_type >= 0 ? by_type : named;
}

/* ((Triforce, 11-19) where Auto keeps the device used last: <user>/prompts_auto.txt, beside the saves and mouse_sens.txt.
   Not in prompts/, which Setup makes again from nothing when its tools or the game's files change (nx2/make_game.py
   Prompts.finish), as a release's update does: the face remembered went with it, and the first start after each update
   without a controller ready had the keys' face again */
static void auto_path(char *out, size_t cap) {
    snprintf(out, cap, "%s/prompts_auto.txt", hos_user_dir ? hos_user_dir : "user");
}
/* ((Triforce) the face auto_path has (faces[]), the device used last in the run before (follow_main), or prompts/auto.txt's,
   where an older build kept it; -1 none */
static int remembered_face(const char *dir) {
    char path[MAX_PATH], line[32] = "";
    auto_path(path, sizeof path);
    FILE *f = fopen(path, "r");
    if (!f) {
        snprintf(path, sizeof path, "%sprompts/auto.txt", dir);
        f = fopen(path, "r");
    }
    if (!f) return -1;
    if (!fgets(line, sizeof line, f)) line[0] = 0;
    fclose(f);
    line[strcspn(line, "\r\n")] = 0;
    for (int i = 0; i < HOS_PROMPT_N; i++)
        if (!strcmp(line, faces[i])) return i;
    return -1;
}

/* (Triforce) Auto's wait at the start: SDL's first scan for controllers and four more, a second of them (pad_sdl.c scans
   each quarter second at first), 3 s at most; none without SDL */
#define AUTO_SCANS 5
static int chosen_auto;   /* (choose_face's: the row is on Auto) */

/* HOS_PROMPT_* (faces[]) */
static int choose_face(const char *dir) {
    char path[MAX_PATH], line[80];
    int choice = 0;
    snprintf(path, sizeof path, "%striforce_options.ini", dir);
    FILE *f = fopen(path, "r");
    if (f) {
        while (fgets(line, sizeof line, f))
            if (!strncmp(line, "button_prompts=", 15)) choice = atoi(line + 15);
        fclose(f);
    }
    if (choice >= 1 && choice <= HOS_PROMPT_N) return choice - 1;
    chosen_auto = 1;
    /* Auto: the first controller SDL opens, as long as AUTO_SCANS's wait */
    char name[128] = "";
    uint64_t b = 0;
    int32_t s[4] = {0};
    for (int i = 0; i < 60; i++) {
        hos_sdl_pads(&b, s);
        hos_sdl_pad_first_name(name, sizeof name);
        const int scans = hos_sdl_pad_scans();
        if (name[0] || scans < 0 || scans >= AUTO_SCANS) break;
        Sleep(50);
    }
    const int xinput = !name[0] && hos_xinput_connected();
    const int remembered = name[0] || xinput ? -1 : remembered_face(dir);
    int sdl = 0;
    const int type = name[0] ? hos_sdl_pad_type_of(0, &sdl) : 0;
    const int face = typed_face(auto_face(name, xinput, remembered), name, sdl, type);   /* ((Triforce) by SDL's type where the name says no maker) */
    hos_log("prompts: auto: controller \"%s\" (SDL%d type %d): %s", name[0] ? name : xinput ? "(XInput's, no name)" :
            remembered >= 0 ? "(none: the device used last in the run before, prompts_auto.txt)" : "(none)", sdl, type, faces[face]);
    return face;
}

static uint32_t rd32le(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static void wr32le(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v, p[1] = (uint8_t)(v >> 8), p[2] = (uint8_t)(v >> 16), p[3] = (uint8_t)(v >> 24); }
static unsigned rd16(const uint8_t *p) { return p[0] << 8 | p[1]; }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]; }
static void wr16(uint8_t *p, unsigned v) { p[0] = (uint8_t)(v >> 8), p[1] = (uint8_t)v; }

/* the glyph of a code point in a format 4 subtable (st: its start, n its bytes), 0 none */
static unsigned cmap4_glyph(const uint8_t *st, size_t n, unsigned code) {
    const unsigned segs = rd16(st + 6) / 2;
    if (14 + 8 * (size_t)segs + 2 > n) return 0;
    const uint8_t *ends = st + 14, *starts = ends + 2 * segs + 2, *deltas = starts + 2 * segs, *ranges = deltas + 2 * segs;
    for (unsigned i = 0; i < segs; i++) {
        if (rd16(ends + 2 * i) < code) continue;
        if (rd16(starts + 2 * i) > code) return 0;
        const unsigned ro = rd16(ranges + 2 * i);
        if (!ro) return (code + rd16(deltas + 2 * i)) & 0xFFFF;
        const uint8_t *g = ranges + 2 * i + ro + 2 * (code - rd16(starts + 2 * i));
        if (g + 2 > st + n) return 0;
        const unsigned gid = rd16(g);
        return gid ? (gid + rd16(deltas + 2 * i)) & 0xFFFF : 0;
    }
    return 0;
}

/* (Triforce) What a control is on (control: a Switch button, HOS_SW_*, or a movement key's place, HOS_KEY_*), as the
   face's icons are numbered: a controller's input (HOS_PAD_*; -1 none, and for what is no button), or on the keyboard and
   mouse face the first of the control's keys (its key code; 0 none: the blank cap), as NX2navi's showed the first key */
static int bound_input(int face, int control) {
    if (face != HOS_PROMPT_KEYBOARD) return hos_binding(HOS_BIND_PAD, control, 0);
    const int first = hos_binding(HOS_BIND_KEY, control, 0);
    return first > 0 ? first : hos_binding(HOS_BIND_KEY, control, 1);
}

/* a code point's own segment (one code, by idDelta alone) pointed at glyph gid; 0 when it has none */
static int cmap4_point(uint8_t *st, unsigned segs, unsigned code, unsigned gid) {
    uint8_t *ends = st + 14, *starts = ends + 2 * segs + 2, *deltas = starts + 2 * segs, *ranges = deltas + 2 * segs;
    for (unsigned i = 0; i < segs; i++)
        if (rd16(starts + 2 * i) == code && rd16(ends + 2 * i) == code && !rd16(ranges + 2 * i)) {
            wr16(deltas + 2 * i, (gid - code) & 0xFFFF);
            return 1;
        }
    return 0;
}

/* each Switch button's segment pointed at its input's icon (bound_input); how many. (Triforce) On the keyboard and mouse
   face the left stick's four directions too, at their movement keys' icons (nx2/prompt_keys.py MOVES), and a key that has
   no icon (one a hand put into the options file) shows the blank cap. ((Triforce) the live part) A controller's face in a
   font with every face's icons (FACE_BASE): each Switch button at that face's icon of its input, an unbound one (or one on a
   paddle) at its default's, and the d-pad's at the face's, so the font served for one face is pointed at another's while the
   game runs (live_font); for the face the font was built for, the same as it has */
static int cmap4_bind(uint8_t *st, size_t n, int face) {
    const unsigned segs = rd16(st + 6) / 2;
    if (14 + 8 * (size_t)segs + 2 > n) return 0;   /* (as cmap4_glyph: the ranges' last entry too) */
    static const struct { uint16_t code; uint8_t control; } moves[4] = {
        {0xE052, HOS_KEY_MOVE_UP}, {0xE050, HOS_KEY_MOVE_DOWN}, {0xE05A, HOS_KEY_MOVE_LEFT}, {0xE058, HOS_KEY_MOVE_RIGHT}};
    const int keys = face == HOS_PROMPT_KEYBOARD, inputs = keys ? 256 : HOS_PAD_N;
    const unsigned base = FACE_BASE + FACE_CODES * (unsigned)face;
    const int faces = !keys && face < LIVE_FACES && cmap4_glyph(st, n, base + HOS_PAD_SOUTH) != 0;
    int done = 0;
    if (faces && live_vr_now > 0 && cmap4_glyph(st, n, VR_SW_BASE + 16u * (unsigned)(live_vr_now - 1))) {
        for (int b = 0; b < HOS_SW_N; b++) {   /* ((Triforce VR) the hand controllers' controls */
            const unsigned gid = cmap4_glyph(st, n, VR_SW_BASE + 16u * (unsigned)(live_vr_now - 1) + (unsigned)b);
            if (gid) done += cmap4_point(st, segs, switch_code[b], gid);
        }
        return done;
    }
    for (int b = 0; b < HOS_SW_N + (keys ? 4 : 0); b++) {
        const unsigned code = b < HOS_SW_N ? switch_code[b] : moves[b - HOS_SW_N].code;
        const int pad = bound_input(face, b < HOS_SW_N ? b : moves[b - HOS_SW_N].control);
        if (faces) {
            const int bound = pad >= 0 && pad < HOS_PAD_N;
            const unsigned gid = cmap4_glyph(st, n, base + (unsigned)(bound ? pad : switch_pad[b]));
            if (gid && cmap4_point(st, segs, code, gid)) done += bound;
            continue;
        }
        if (pad < 0 || pad >= inputs) continue;   /* (unbound: the default icon stays) */
        unsigned gid = cmap4_glyph(st, n, PAD_BASE + (unsigned)pad);
        if (!gid && keys) gid = cmap4_glyph(st, n, PAD_BASE);
        if (!gid) continue;
        done += cmap4_point(st, segs, code, gid);
    }
    for (int k = 0; faces && k < 3; k++) {
        const unsigned gid = cmap4_glyph(st, n, base + STATIC_AT + (unsigned)k);
        if (gid) cmap4_point(st, segs, static_code[k], gid);
    }
    return done;
}

/* (Triforce) The keyboard and mouse face's icons of several keys (the left stick: the movement keys; the d-pad: its four
   keys). Each such glyph calls a subroutine per key, that key's small cap, and prompts/keyboard/keys.bin (t; nx2/
   prompt_keys.py: "HPKB", u32 count; each: u32 offset in the font, u8 control (HOS_KEY_*), 3 bytes; then u32 keys, and for
   each key code the two bytes of its cap's call, 0 0 none) says where those calls are: each gets the call of the first key
   bound to its control (none bound, or a key with no cap: the blank cap's, key code 0's). A call is two bytes whatever the
   key (a charstring's number from 108 to 1131: its first byte 247 to 250), so nothing else in the font moves; a place or a
   call that is not such a number is left alone. How many were written */
static int bind_keys(uint8_t *otf, size_t n, const uint8_t *t, size_t tn) {
    if (tn < 12) return 0;
    const uint32_t count = rd32le(t + 4);
    if (count > (tn - 12) / 8) return 0;
    const uint8_t *calls = t + 12 + 8 * (size_t)count;
    const uint32_t keys = rd32le(calls - 4);
    if (!keys || keys > (tn - (size_t)(calls - t)) / 2) return 0;
    int done = 0;
    for (uint32_t i = 0; i < count; i++) {
        const uint8_t *e = t + 8 + 8 * (size_t)i;
        const uint32_t off = rd32le(e);
        const int key = bound_input(HOS_PROMPT_KEYBOARD, e[4]);
        const uint8_t *call = calls + (key > 0 && (uint32_t)key < keys && calls[2 * (size_t)key] ? 2 * (size_t)key : 0);
        if (off > n || n - off < 2 || otf[off] < 247 || otf[off] > 250 || call[0] < 247 || call[0] > 250) continue;
        otf[off] = call[0], otf[off + 1] = call[1];
        done++;
    }
    return done;
}

/* the controls into the decrypted font's format 4 subtables; how many buttons */
static int bind_font(uint8_t *otf, size_t n, int face) {
    if (n < 12) return 0;
    const unsigned tables = rd16(otf + 4);
    for (unsigned t = 0; t < tables && 12 + 16 * (size_t)(t + 1) <= n; t++) {
        const uint8_t *rec = otf + 12 + 16 * t;
        if (memcmp(rec, "cmap", 4)) continue;
        const uint32_t off = rd32(rec + 8), len = rd32(rec + 12);
        if (off > n || len > n - off || len < 4) return 0;
        uint8_t *cmap = otf + off;
        const unsigned subs = rd16(cmap + 2);
        uint32_t seen[8];
        int nseen = 0, done = 0;
        for (unsigned s = 0; s < subs && 4 + 8 * (size_t)(s + 1) <= len; s++) {
            const uint32_t so = rd32(cmap + 4 + 8 * s + 4);
            if (so > len || len - so < 14 || rd16(cmap + so) != 4) continue;   /* (so + 14 wrapped past 4 GB) */
            int dup = 0;   /* (platforms 0 and 3 share one subtable) */
            for (int k = 0; k < nseen; k++) dup |= seen[k] == so;
            if (dup) continue;
            if (nseen < 8) seen[nseen++] = so;
            const unsigned sl = rd16(cmap + so + 2);
            done = cmap4_bind(cmap + so, sl <= len - so ? sl : len - so, face);
        }
        return done;
    }
    return 0;
}

/* ((Triforce) the live part) the glyph of a code in the decrypted font's first format 4 subtable, 0 none */
static unsigned font_glyph(const uint8_t *otf, size_t n, unsigned code) {
    if (n < 12) return 0;
    const unsigned tables = rd16(otf + 4);
    for (unsigned t = 0; t < tables && 12 + 16 * (size_t)(t + 1) <= n; t++) {
        const uint8_t *rec = otf + 12 + 16 * t;
        if (memcmp(rec, "cmap", 4)) continue;
        const uint32_t off = rd32(rec + 8), len = rd32(rec + 12);
        if (off > n || len > n - off || len < 4) return 0;
        const uint8_t *cmap = otf + off;
        for (unsigned s = 0; s < rd16(cmap + 2) && 4 + 8 * (size_t)(s + 1) <= len; s++) {
            const uint32_t so = rd32(cmap + 4 + 8 * s + 4);
            if (so > len || len - so < 14 || rd16(cmap + so) != 4) continue;
            const unsigned sl = rd16(cmap + so + 2);
            return cmap4_glyph(cmap + so, sl <= len - so ? sl : len - so, code);
        }
        return 0;
    }
    return 0;
}

/* a zstd frame's header for raw blocks of 128 KB: the 4-byte content size, and a window of 128 KB (raw blocks never look back:
   a single-segment frame's window, the whole content, is more than decoders take: zstd's own refuses 244 MB) */
static void zstd_head(uint8_t head[10], size_t n) {
    wr32le(head, 0xFD2FB528u);
    head[4] = 0x80;   /* (FCS 4 bytes, not single segment, no checksum, no dictionary) */
    head[5] = 7 << 3;   /* (window 2^(10+7)) */
    wr32le(head + 6, (uint32_t)n);
}

/* one raw block of a frame (zstd_head): k bytes (at most 128 KB), last for the frame's last */
static int zstd_block(FILE *o, const uint8_t *data, size_t k, int last) {
    const uint32_t bh = (uint32_t)(k << 3) | (last ? 1u : 0u);
    const uint8_t b3[3] = {(uint8_t)bh, (uint8_t)(bh >> 8), (uint8_t)(bh >> 16)};
    return fwrite(b3, 1, 3, o) == 3 && fwrite(data, 1, k, o) == k;
}

/* data as a zstd frame of raw blocks (zstd_head) */
static int write_zstd_raw(const char *path, const uint8_t *data, size_t n) {
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    uint8_t head[10];
    zstd_head(head, n);
    int ok = fwrite(head, 1, 10, f) == 10;
    size_t at = 0;
    do {
        const size_t k = n - at < 131072 ? n - at : 131072;
        ok &= zstd_block(f, data + at, k, at + k == n);
        at += k;
    } while (at < n);
    ok &= fclose(f) == 0;
    return ok;
}

static uint8_t *read_all(const char *path, const char *magic, long *n) {   /* (the whole file, if it starts with magic: NULL any) */
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    *n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *t = *n > 8 ? (uint8_t *)malloc((size_t)*n) : NULL;
    const int got = t && fread(t, 1, (size_t)*n, f) == (size_t)*n;
    fclose(f);
    if (!got || (magic && memcmp(t, magic, 4))) {
        free(t);
        return NULL;
    }
    return t;
}

static volatile LONG setup_state;   /* setup's: 0 not looked, 1 looking, 2 prompts, 3 none */
static DWORD WINAPI follow_main(void *arg);

/* the game folder and the face, found once; 0 when the folder has no prompts/ (built before them: the game's own icons) */
static int setup(char *dir, size_t cap, int *face) {
    static char d[MAX_PATH];
    static int f;
    if (InterlockedCompareExchange(&setup_state, 1, 0) == 0) {
        char path[MAX_PATH];
        int ok = game_dir(d, sizeof d);
        if (ok) {
            snprintf(path, sizeof path, "%sprompts", d);
            ok = GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
        }
        if (ok) f = choose_face(d);
        /* (v0.3.5 shipped tools whose Python lacked nx2/prompt_requirements.txt: no folder was made, the Button prompts
           setting did nothing, and the log said nothing of it) */
        else hos_log("prompts: no prompts folder beside the game: the game's own icons, whatever Button prompts is set to "
                     "(Setup's Update makes them)");
        /* ((Triforce) the device used last followed, on Auto or with the keys' face: follow_main, which waits for this) */
        if (ok && (chosen_auto || f == HOS_PROMPT_KEYBOARD)) {
            HANDLE t = CreateThread(NULL, 0, follow_main, NULL, 0, NULL);
            if (t) CloseHandle(t);
        }
        InterlockedExchange(&setup_state, ok ? 2 : 3);
    }
    while (setup_state == 1) Sleep(1);
    snprintf(dir, cap, "%s", d);
    *face = f;
    return setup_state == 2;
}

static uint64_t fnv(uint64_t h, const void *p, size_t n) {
    for (size_t i = 0; i < n; i++) h = (h ^ ((const uint8_t *)p)[i]) * 0x100000001b3ull;
    return h;
}

typedef struct { uint32_t off, len, idx; const uint8_t *data; } Run;   /* (idx: its place in textures.bin) */
static int run_cmp(const void *a, const void *b) {
    const Run *x = (const Run *)a, *y = (const Run *)b;
    return x->off != y->off ? (x->off < y->off ? -1 : 1) : (x->idx > y->idx) - (x->idx < y->idx);
}
static int run_order(const void *a, const void *b) {
    const uint32_t x = (*(const Run *const *)a)->idx, y = (*(const Run *const *)b)->idx;
    return (x > y) - (x < y);
}

static void add_run(Run **runs, size_t *nruns, size_t *cap, uint32_t off, uint32_t len, const uint8_t *data) {
    if (*nruns == *cap) *runs = (Run *)realloc(*runs, (*cap *= 2) * sizeof **runs);
    (*runs)[*nruns] = (Run){off, len, (uint32_t)*nruns, data};
    (*nruns)++;
}

/* prompts/Common.bntx.zs: the game's textures (prompts/Common.bntx) with the blocks of prompts/<face>/textures.bin that this
   pad's controls choose (nx2/prompt_assets.py: "HPTX", u32 count; each: u8 Switch button (0xff: always), u8 pad input, u16,
   u32 runs; each run: u32 offset, u32 length, the bytes; a later entry over an earlier). Written again only when the face, the
   controls or the blocks changed (prompts/Common.key) */
/* out: the game's file (game) with the runs written over it (a later one over an earlier where they meet), as raw zstd blocks;
   written again only when its key (keypath: the hash h of what chose the runs) changed. Written beside it first (out.tmp), and
   moved over it with the key removed until then: a failed write leaves the last good file and its key, a stop between the
   steps leaves no key (written again at the next start) */
static int write_patched(const char *game, const char *out, const char *keypath, uint64_t h, Run *runs, size_t nruns) {
    qsort(runs, nruns, sizeof *runs, run_cmp);
    char keyline[32] = "", want[32];
    FILE *f;
    if ((f = fopen(keypath, "r"))) {
        if (!fgets(keyline, sizeof keyline, f)) keyline[0] = 0;
        fclose(f);
    }
    snprintf(want, sizeof want, "%016llx", (unsigned long long)h);
    int ok = !strcmp(keyline, want) && GetFileAttributesA(out) != INVALID_FILE_ATTRIBUTES;
    if (!ok) {   /* the game's file through, the chosen runs written over it, out as raw zstd blocks */
        char tmp[MAX_PATH + 8];
        snprintf(tmp, sizeof tmp, "%s.tmp", out);
        FILE *in = fopen(game, "rb"), *o = fopen(tmp, "wb");
        uint8_t *chunk = (uint8_t *)malloc(131072);
        ok = in && o && chunk;
        if (ok) {
            fseek(in, 0, SEEK_END);
            const uint64_t n = (uint64_t)ftell(in);
            fseek(in, 0, SEEK_SET);
            uint8_t head[10];
            zstd_head(head, n);
            ok = n < 0xFFFFFFFFull && fwrite(head, 1, 10, o) == 10;
            size_t first = 0;   /* (the first run that may reach this chunk) */
            const Run **here = (const Run **)malloc((nruns ? nruns : 1) * sizeof *here);
            ok = ok && here;
            for (uint64_t pos = 0; ok && pos < n;) {
                const size_t k = n - pos < 131072 ? (size_t)(n - pos) : 131072;
                ok = fread(chunk, 1, k, in) == k;
                while (first < nruns && runs[first].off + runs[first].len <= pos) first++;
                size_t nh = 0;   /* (the runs in this chunk, written in their order: a later one over an earlier) */
                for (size_t r = first; r < nruns && runs[r].off < pos + k; r++)
                    if (runs[r].off + runs[r].len > pos) here[nh++] = &runs[r];
                qsort(here, nh, sizeof *here, run_order);
                for (size_t i = 0; i < nh; i++) {
                    const Run *r = here[i];
                    const uint64_t a = r->off > pos ? r->off : pos;
                    const uint64_t z = r->off + r->len < pos + k ? r->off + r->len : pos + k;
                    memcpy(chunk + (a - pos), r->data + (a - r->off), (size_t)(z - a));
                }
                ok = ok && zstd_block(o, chunk, k, pos + k == n);
                pos += k;
            }
            free(here);
        }
        if (in) fclose(in);
        if (o) ok &= fclose(o) == 0;
        free(chunk);
        ok = ok && (GetFileAttributesA(keypath) == INVALID_FILE_ATTRIBUTES || DeleteFileA(keypath)) &&
             MoveFileExA(tmp, out, MOVEFILE_REPLACE_EXISTING);
        if (!ok) DeleteFileA(tmp);
        if (ok && (f = fopen(keypath, "w"))) {
            fputs(want, f);
            fclose(f);
        }
    }
    return ok;
}

/* ((Triforce) the live part's state, its code below build()) what the game is to show now (the start's, then each change's):
   the face and the controls; and what each part it loaded shows (PART_*: the start's until written over, so a part found
   after a change catches up) */
enum { PART_TEXTURES, PART_LAYOUTS, PART_FONT, PARTS };
static int live_face_now = -1, live_bind_now[HOS_SW_N];
static int part_face[PARTS], part_bind[PARTS][HOS_SW_N];
static int served_face[PARTS], served_bind[PARTS][HOS_SW_N];   /* (each part's file as served: what the game loads again) */
static void live_start(int face, const int *bind) {   /* (the first file served: the start's) */
    if (live_face_now >= 0) return;
    memcpy(live_bind_now, bind, sizeof live_bind_now);
    live_face_now = face;
}
static void part_served(int p, int face, const int *bind) {   /* (its file written for this face and these controls) */
    served_face[p] = part_face[p] = face;
    memcpy(served_bind[p], bind, sizeof served_bind[p]);
    memcpy(part_bind[p], bind, sizeof part_bind[p]);
    live_start(face, bind);
}
static struct {
    volatile uint64_t at;   /* where the game keeps the served font, decrypted (behind its header or not), 0 not seen */
    uint32_t n;             /* the file's length, 0 not served */
    uint8_t head[64];       /* its first bytes, decrypted: the tables' directory */
    int live;               /* it has every controller face's icons (nx2/prompt_assets.py faces_font): a change can show */
} font;
static void live_textures_start(const char *bntx, const Run *runs, size_t nruns);

/* the runs of a face's textures.bin (t, tn bytes) that the controls (bind: each Switch button's input) choose, in the file's
   order; *nruns of them */
static Run *texture_runs(const uint8_t *t, long tn, const int *bind, size_t *nruns) {
    const uint32_t count = rd32le(t + 4);
    size_t at = 8, cap_runs = 256;
    Run *runs = (Run *)malloc(cap_runs * sizeof *runs);
    *nruns = 0;
    for (uint32_t e = 0; e < count && at + 8 <= (size_t)tn; e++) {
        const int sw = t[at], pad = t[at + 1];
        const uint32_t nr = rd32le(t + at + 4);
        const int on = sw == 0xff || (sw < HOS_SW_N && bind[sw] == pad);
        at += 8;
        for (uint32_t r = 0; r < nr && at + 8 <= (size_t)tn; r++) {
            const uint32_t off = rd32le(t + at), len = rd32le(t + at + 4);
            if (len > (size_t)tn - at - 8) break;
            if (on) add_run(&runs, nruns, &cap_runs, off, len, t + at + 8);
            at += 8 + len;
        }
    }
    return runs;
}

static int build_textures(char *out, size_t cap) {
    char dir[MAX_PATH], path[MAX_PATH];
    int face;
    if (!setup(dir, sizeof dir, &face)) return 0;
    snprintf(path, sizeof path, "%sprompts/%s/textures.bin", dir, faces[face]);
    long tn;
    uint8_t *t = read_all(path, "HPTX", &tn);
    if (!t) return 0;   /* (built without the textures: the game's) */
    int bind[HOS_SW_N];   /* ((Triforce) on the keyboard and mouse face the entries' inputs are key codes: bound_input) */
    for (int b = 0; b < HOS_SW_N; b++) bind[b] = bound_input(face, b);
    uint64_t h = fnv(fnv(fnv(0xcbf29ce484222325ull, &face, sizeof face), bind, sizeof bind), t, (size_t)tn);
    size_t nruns;   /* the runs these controls choose */
    Run *runs = texture_runs(t, tn, bind, &nruns);
    snprintf(out, cap, "%sprompts/Common.bntx.zs", dir);
    snprintf(path, sizeof path, "%sprompts/Common.bntx", dir);
    char keypath[MAX_PATH];
    snprintf(keypath, sizeof keypath, "%sprompts/Common.key", dir);
    const int ok = write_patched(path, out, keypath, h, runs, nruns);
    hos_log("prompts: %s textures, %zu runs for these controls%s", faces[face], nruns,
            ok ? "" : ": could not be written");
    if (ok && face < LIVE_FACES) {   /* ((Triforce) the live part: what the game loads is this file, these runs over it) */
        live_textures_start(path, runs, nruns);
        part_served(PART_TEXTURES, face, bind);
    }
    free(runs);
    free(t);
    return ok;
}

/* the face the game was given (faces[]; (Triforce) or shown since, the live part), -1 none: the Insert menu names the pad inputs as that controller does. -1 too
   until the game has asked for a prompt file: the menu asks from the present thread, and choose_face can wait for SDL */
int hos_prompts_face(void) {
    char dir[MAX_PATH];
    int face;
    if (live_face_now >= 0) return live_face_now;   /* ((Triforce) the live part: the face shown now) */
    return setup_state >= 2 && setup(dir, sizeof dir, &face) ? face : -1;
}

/* the Talk ring's place for each of A B X Y (0 east, 1 south, 2 north, 3 west: nx2/prompt_assets.py RING_PLACES): where its pad
   input is among the face buttons, else its own place on the Switch when free, else the first one free */
static void ring_places(const int *bind, int place[4]) {
    static const int of_pad[4] = {1, 0, 3, 2};   /* (HOS_PAD_SOUTH, EAST, WEST, NORTH) */
    int taken[4] = {0};
    for (int s = 0; s < 4; s++) {
        const int p = bind[s] >= 0 && bind[s] < 4 ? of_pad[bind[s]] : -1;
        place[s] = p >= 0 && !taken[p] ? p : -1;
        if (place[s] >= 0) taken[place[s]] = 1;
    }
    for (int s = 0; s < 4; s++) {
        if (place[s] >= 0) continue;
        int p = s;   /* (A B X Y's own places are 0 1 2 3) */
        if (taken[p])
            for (p = 0; taken[p]; p++) {}
        place[s] = p;
        taken[p] = 1;
    }
}

/* prompts/Common.blarc.zs: the game's layouts (prompts/Common.blarc) with
   - the Talk ring's A B X Y where their pad inputs are (prompts/ring.bin, nx2/prompt_assets.py: "HPRG", u32 count; each: u8
     group, u8 Switch button placed, u8 place, u8, u32 runs, the runs);
   - the ocarina hint's icons moved apart for the wide ones bound (prompts/<face>/hint.bin, nx2/prompt_assets.py HINTS: "HPHN",
     u32 count of pad inputs, each one's icon's extra width (f32), u32 panes; each: u32 offset, u8 slot, 3 bytes, f32 x): each
     icon the one before's extra further on, the last one where it is;
   - the edge-anchored HUD out at a wide picture's sides (prompts/wide.bin, nx2/prompt_assets.py HUD_SIDE_PANES: "HPWD", u32
     count; each: u32 offset, i8 side, 3 bytes, f32 x), with the Insert menu's Ultrawide HUD row on Screen edges
     (host/oot_wide_hud.h);
   none when all are as the game has them (the game's own file) */
/* ((Triforce) the live part) the runs over the game's Common.blarc for a face and its controls (bind: each Switch button's
   input, bound_input's), and what they point into (freed with layout_free) */
typedef struct {
    Run *runs;
    size_t n;
    uint64_t h;   /* (what chose them: the file's key) */
    uint8_t *ring, *hint, *wide;
    float *xs, *wxs;
    int place[4];
} Layout;
static void layout_free(Layout *o) {
    free(o->wxs);
    free(o->wide);
    free(o->xs);
    free(o->hint);
    free(o->runs);
    free(o->ring);
    memset(o, 0, sizeof *o);
}

static int layout_runs(const char *dir, int face, const int *bind, Layout *o) {
    char path[MAX_PATH];
    memset(o, 0, sizeof *o);
    for (int i = 0; i < 4; i++) o->place[i] = i;
    /* ((Triforce) keys have no places among four face buttons: the keyboard and mouse face keeps the Switch's) */
    if (face != HOS_PROMPT_KEYBOARD) ring_places(bind, o->place);
    const int ring_moved = !(o->place[0] == 0 && o->place[1] == 1 && o->place[2] == 2 && o->place[3] == 3);
    size_t cap_runs = 64;
    o->runs = (Run *)malloc(cap_runs * sizeof *o->runs);
    o->h = fnv(0xcbf29ce484222325ull, o->place, sizeof o->place);
    long tn = 0, hn = 0;
    snprintf(path, sizeof path, "%sprompts/ring.bin", dir);
    uint8_t *t = o->ring = ring_moved ? read_all(path, "HPRG", &tn) : NULL;
    if (t) {
        const uint32_t count = rd32le(t + 4);
        size_t at = 8;
        for (uint32_t e = 0; e < count && at + 8 <= (size_t)tn; e++) {
            const int placed = t[at + 1], where = t[at + 2];
            const uint32_t nr = rd32le(t + at + 4);
            const int on = placed < 4 && o->place[placed] == where;
            at += 8;
            for (uint32_t r = 0; r < nr && at + 8 <= (size_t)tn; r++) {
                const uint32_t off = rd32le(t + at), len = rd32le(t + at + 4);
                if (len > (size_t)tn - at - 8) break;
                if (on) add_run(&o->runs, &o->n, &cap_runs, off, len, t + at + 8);
                at += 8 + len;
            }
        }
        o->h = fnv(o->h, t, (size_t)tn);
    }
    /* the hint's notes, in its order (Switch L R Y X A: up, down, left, right, A) */
    static const int notes[5] = {HOS_SW_L, HOS_SW_R, HOS_SW_Y, HOS_SW_X, HOS_SW_A};
    snprintf(path, sizeof path, "%sprompts/%s/hint.bin", dir, faces[face]);
    uint8_t *hint = o->hint = read_all(path, "HPHN", &hn);
    if (hint) {
        const uint32_t npads = rd32le(hint + 4);
        const size_t panes_at = 8 + 4 * (size_t)npads;
        float extra[5], shift[6] = {0};
        for (int i = 0; i < 5; i++) {
            const int p = bind[notes[i]];
            extra[i] = 0;
            if (p >= 0 && (uint32_t)p < npads && panes_at <= (size_t)hn) memcpy(&extra[i], hint + 8 + 4 * p, 4);
        }
        for (int i = 3; i >= 0; i--) shift[i] = shift[i + 1] - extra[i];   /* (an icon is drawn from its pane's left) */
        shift[5] = shift[0];   /* (the text with the first icon) */
        const int spread = shift[0] != 0;
        const uint32_t count = panes_at + 4 <= (size_t)hn ? rd32le(hint + panes_at) : 0;
        if (spread && count <= ((size_t)hn - panes_at - 4) / 12) {
            o->xs = (float *)malloc((count ? count : 1) * sizeof *o->xs);
            for (uint32_t k = 0; k < count; k++) {
                const uint8_t *e = hint + panes_at + 4 + 12 * k;
                memcpy(&o->xs[k], e + 8, 4);
                o->xs[k] += shift[e[4] < 6 ? e[4] : 5];
                add_run(&o->runs, &o->n, &cap_runs, rd32le(e), 4, (const uint8_t *)&o->xs[k]);
            }
            o->h = fnv(fnv(o->h, shift, sizeof shift), hint, (size_t)hn);
        }
    }
    const float wide_out = hos_wide_hud_out();
    long wn = 0;
    snprintf(path, sizeof path, "%sprompts/wide.bin", dir);
    uint8_t *wide = o->wide = wide_out > 0.0f ? read_all(path, "HPWD", &wn) : NULL;
    if (wide) {
        const uint32_t count = rd32le(wide + 4);
        if (count && count <= ((size_t)wn - 8) / 12) {
            o->wxs = (float *)malloc(count * sizeof *o->wxs);
            for (uint32_t k = 0; k < count; k++) {
                const uint8_t *e = wide + 8 + 12 * k;
                memcpy(&o->wxs[k], e + 8, 4);
                o->wxs[k] += (float)(int8_t)e[4] * wide_out;
                add_run(&o->runs, &o->n, &cap_runs, rd32le(e), 4, (const uint8_t *)&o->wxs[k]);
            }
            o->h = fnv(fnv(o->h, &wide_out, sizeof wide_out), wide, (size_t)wn);
        }
    }
    return 1;
}

static void live_layouts_start(const char *blarc, const Layout *o);

static int build_layouts(char *out, size_t cap) {
    char dir[MAX_PATH], path[MAX_PATH];
    int face;
    if (!setup(dir, sizeof dir, &face)) return 0;
    int bind[HOS_SW_N];
    for (int b = 0; b < HOS_SW_N; b++) bind[b] = bound_input(face, b);
    Layout o;
    layout_runs(dir, face, bind, &o);
    if (!o.wide && hos_wide_hud_out() > 0.0f)
        hos_log("prompts: no prompts/wide.bin: the Ultrawide HUD stays in the middle (Setup's Update makes it)");
    int ok = 0;
    snprintf(path, sizeof path, "%sprompts/Common.blarc", dir);
    if (o.n) {
        char keypath[MAX_PATH];
        snprintf(out, cap, "%sprompts/Common.blarc.zs", dir);
        snprintf(keypath, sizeof keypath, "%sprompts/Common.blarc.key", dir);
        ok = write_patched(path, out, keypath, o.h, o.runs, o.n);
        hos_log("prompts: the Talk ring's A B X Y at places %d %d %d %d, the ocarina hint %s, edge-anchored HUD %s%s",
                o.place[0], o.place[1], o.place[2], o.place[3], o.xs ? "spread" : "as is", o.wxs ? "at the picture's sides" : "as is",
                ok ? "" : ": could not be written");
    }
    /* ((Triforce) the live part: the file the game loads, ours or its own as the game has it (none to write over it), and the
       runs in it; not when ours could not be written: what the game has is not known then */
    if (face < LIVE_FACES && (ok || !o.n)) {
        Layout served = o;
        if (!ok) served.n = 0;
        live_layouts_start(path, &served);
        part_served(PART_LAYOUTS, face, bind);
    } else {
        layout_free(&o);
    }
    return ok;
}

/* face's font (prompts/<face>/External.bfotf) with these controls, written to prompts/<name> (out its path); 1 when written,
   -1 when the folder has no font of that face. pad: (Triforce) the overlay's font of the controller used last
   (follow_main), written whole and then put in place: (11-19) once a run for each face, before the overlay is told of it,
   so never while it reads it */
static int build_font(const char *dir, int face, const char *name, int pad, char *out, size_t cap) {
    char path[MAX_PATH];
    snprintf(path, sizeof path, "%sprompts/%s/External.bfotf", dir, faces[face]);
    long n;
    uint8_t *b = read_all(path, NULL, &n);
    if (!b || n < 16 || n % 4) {
        hos_log("prompts: no %s: the game's own icons", path);
        free(b);
        return -1;
    }
    const uint32_t key = rd32le(b) ^ MAGIC;
    for (long i = 8; i < n; i += 4) wr32le(b + i, rd32le(b + i) ^ key);
    const int bound = bind_font(b + 8, (size_t)n - 8, face);
    int several = 0;
    if (face == HOS_PROMPT_KEYBOARD) {   /* ((Triforce) the icons of several keys: bind_keys) */
        long kn = 0;
        snprintf(path, sizeof path, "%sprompts/%s/keys.bin", dir, faces[face]);
        uint8_t *k = read_all(path, "HPKB", &kn);
        if (k) several = bind_keys(b + 8, (size_t)n - 8, k, (size_t)kn);
        free(k);
    }
    uint8_t head[64];   /* ((Triforce) the live part: the served font's first bytes, decrypted) */
    memcpy(head, b + 8, n - 8 < 64 ? (size_t)(n - 8) : 64);
    const int live = !pad && face < LIVE_FACES && n - 8 >= 64 &&
                     font_glyph(b + 8, (size_t)n - 8, FACE_BASE + FACE_CODES * (unsigned)face + HOS_PAD_SOUTH) != 0;
    for (long i = 8; i < n; i += 4) wr32le(b + i, rd32le(b + i) ^ key);
    snprintf(out, cap, "%sprompts/%s", dir, name);
    snprintf(path, sizeof path, "%s.new", out);
    const int ok = pad ? write_zstd_raw(path, b, (size_t)n) && MoveFileExA(path, out, MOVEFILE_REPLACE_EXISTING)
                       : write_zstd_raw(out, b, (size_t)n);
    free(b);
    if (ok && !pad && face < LIVE_FACES) {   /* ((Triforce) the live part: the font the game loads; found by hos_prompts_glyph) */
        font.n = (uint32_t)n;
        memcpy(font.head, head, sizeof font.head);
        font.live = live;
        int bind[HOS_SW_N];
        for (int i = 0; i < HOS_SW_N; i++) bind[i] = bound_input(face, i);
        part_served(PART_FONT, face, bind);
        if (!live) hos_log("prompts: this font has not every controller's icons (built before): a new face or new controls show at the next start");
    }
    if (pad)
        hos_log("prompts: the overlay's icons of the controller used last: %s, %d buttons on this pad's controls%s", faces[face],
                bound, ok ? "" : ": could not be written");
    else if (face == HOS_PROMPT_KEYBOARD)
        hos_log("prompts: %s icons, %d buttons and directions on these keys, %d keys in the icons of several%s", faces[face],
                bound, several, ok ? "" : ": could not be written");
    else
        hos_log("prompts: %s icons, %d buttons on this pad's controls%s", faces[face], bound, ok ? "" : ": could not be written");
    return ok;
}

/* builds prompts/External.bfotf.zs for this run; 1 when there is one */
static int build(char *out, size_t cap) {
    char dir[MAX_PATH];
    int face;
    if (!setup(dir, sizeof dir, &face)) return 0;
    /* (a mod's size table is served, not ours: the faces' fonts, larger than the game's, do not fit it. ((Triforce, 11-18)
       unless the lifted code asks host/mods.c's hos_mods_table_size for each file's room, which gives the font its own: so
       only when that hook has not run in this game, an older build of it) */
    extern volatile LONG hos_mods_size_hook_seen;
    if (hos_mods_has(SIZES_PATH, ".rsizetable.zs")) {
        if (!hos_mods_size_hook_seen) {
            hos_log("prompts: a mod has the resource size table: the game's own icons in texts");
            return 0;
        }
        hos_log("prompts: a mod has the resource size table: the font's room comes from the size hook (host/mods.c)");
    }
    return build_font(dir, face, "External.bfotf.zs", 0, out, cap) > 0;
}

/* ---- ((Triforce) the live part) the prompts changed while the game runs: among the controllers' faces, a new face (the
   Button prompts row, or Auto's controller) or new controls (the Controls page, a layout preset) reach what the game has
   loaded, at once, by the rules the start follows (each icon the pad input bound to its button; a mod's file never touched:
   only the files served here are looked for).
   - The textures (Common.bntx): their data lies in a memory pool the game makes over the file (hos_prompts_pool, found by
     bytes no run writes). The renderer uploads what is written again (HOS_WRITTEN).
   - The layouts (Common.blarc): where the game keeps them, found by their first bytes near the start of an address region
     (find_layouts); written only where the game's bytes are still the file's.
   - The font (prompts/<face>/External.bfotf, every controller face's icons: nx2/prompt_assets.py faces_font): where FreeType
     reads it (hos_prompts_glyph, from nx2/oot_patches.py's hook in its glyph render); only its cmap changes (for the texts
     set after), and the texts' button codes are rewritten to the face's own (hos_prompts_text_layout).
   A change puts the game's own bytes back where the runs written before fall, then writes the runs the new face and controls
   choose (as the start: texture_runs, layout_runs). Only when every part the game loaded from here is found (a change never
   shows in one part and not in another), and never to or from the keyboard and mouse face (its font is another one): then at
   the next start, as before. */
typedef struct {
    char path[MAX_PATH];        /* the game's file the runs go over (prompts/Common.bntx, prompts/Common.blarc) */
    volatile uint64_t base;     /* the guest address of the file's offset 0 once seen, 0 before */
    uint64_t lo, hi;            /* the guest range runs may be written in */
    uint32_t (*ranges)[2];      /* the runs written: (offset, length), the game's own bytes back first */
    size_t nranges;
    int guarded;                /* a run written only where the game's bytes are still the file's */
} Live;

static void keep_ranges(Live *l, const Run *runs, size_t nruns) {
    free(l->ranges);
    l->ranges = (uint32_t (*)[2])malloc((nruns ? nruns : 1) * sizeof *l->ranges);
    for (size_t r = 0; l->ranges && r < nruns; r++) l->ranges[r][0] = runs[r].off, l->ranges[r][1] = runs[r].len;
    l->nranges = l->ranges ? nruns : 0;
}

/* the game's own bytes back where l's runs were, then these runs (in their order: a later one over an earlier), each marked
   written; how many were outside l's range, or (guarded) over bytes the game changed: not written. Guarded, every run is
   looked at before any is written (a later one over an earlier finds the file's bytes), and only those written are kept */
static size_t put_runs(Live *l, const Run *runs, size_t nruns, size_t *written, size_t *put_back) {
    FILE *f = fopen(l->path, "rb");
    uint8_t *chunk = (uint8_t *)malloc(131072);
    uint8_t *ok = (uint8_t *)calloc(nruns ? nruns : 1, 1);
    size_t outside = 0;
    *written = *put_back = 0;
    const uint64_t base = l->base;   /* (once: 0 when the game let the memory go, nothing written then) */
    if (!base) nruns = 0;
    for (size_t r = 0; base && f && chunk && r < l->nranges; r++) {
        const uint64_t off = l->ranges[r][0], len = l->ranges[r][1], a = base + off;
        uint8_t *q = a >= l->lo && a + len <= l->hi ? (uint8_t *)hos_guest_range(a, len) : NULL;
        if (!q) continue;
        for (uint64_t k = 0; k < len;) {
            const size_t n = len - k < 131072 ? (size_t)(len - k) : 131072;
            if (fseek(f, (long)(off + k), SEEK_SET) || fread(chunk, 1, n, f) != n) break;
            memcpy(q + k, chunk, n);
            k += n;
        }
        HOS_WRITTEN(q, (size_t)len);
        (*put_back)++;
    }
    for (size_t r = 0; r < nruns && ok; r++) {
        const uint64_t a = base + runs[r].off, len = runs[r].len;
        const uint8_t *q = a >= l->lo && a + len <= l->hi ? (const uint8_t *)hos_guest_range(a, len) : NULL;
        ok[r] = q != NULL;
        for (uint64_t k = 0; ok[r] && l->guarded && k < len;) {
            const size_t n = len - k < 131072 ? (size_t)(len - k) : 131072;
            ok[r] = f && chunk && !fseek(f, (long)(runs[r].off + k), SEEK_SET) && fread(chunk, 1, n, f) == n &&
                    !memcmp(q + k, chunk, n);
            k += n;
        }
    }
    for (size_t r = 0; r < nruns; r++) {
        if (!ok || !ok[r]) {
            outside++;
            continue;
        }
        const uint64_t a = base + runs[r].off;
        uint8_t *q = a >= l->lo && a + runs[r].len <= l->hi ? (uint8_t *)hos_guest_range(a, runs[r].len) : NULL;
        if (!q) {
            outside++;
            continue;
        }
        memcpy(q, runs[r].data, runs[r].len);
        HOS_WRITTEN(q, runs[r].len);
        (*written)++;
    }
    if (f) fclose(f);
    free(chunk);
    keep_ranges(l, runs, nruns);
    size_t kept = 0;   /* (the ones written: the next change puts the game's bytes back there) */
    for (size_t r = 0; r < l->nranges; r++)
        if (ok && ok[r]) memmove(l->ranges[kept++], l->ranges[r], sizeof *l->ranges);
    l->nranges = kept;
    free(ok);
    return outside;
}

static int in_runs(uint64_t a, uint64_t n, const Run *runs, size_t nruns) {
    for (size_t r = 0; r < nruns; r++)
        if (a < (uint64_t)runs[r].off + runs[r].len && runs[r].off < a + n) return 1;
    return 0;
}

enum { SAMPLES = 3, SAMPLE_LEN = 64 };
static struct {
    Live l;                               /* over the game's Common.bntx */
    uint64_t data_off, data_len;          /* its texture data: offset (the BRTD block's + 16) and length */
    uint64_t sample[SAMPLES];             /* file offsets of bytes no run of the start's writes */
    uint8_t want[SAMPLES][SAMPLE_LEN];
    uint8_t *bins[LIVE_FACES];            /* each face's textures.bin, read when first chosen (the runs point into it) */
    long nbins[LIVE_FACES];
    uint32_t (*served)[2];                /* the runs of the file as served (offset, length): a pool made again holds them */
    size_t nserved;
} tex;

/* (build_textures) the file's texture data, with bytes to know its pool by, and the ranges of the start's runs */
static void live_textures_start(const char *bntx, const Run *runs, size_t nruns) {
    FILE *f = fopen(bntx, "rb");
    uint8_t h[0x38], blk[16];
    if (!f) return;
    int ok = fread(h, 1, sizeof h, f) == sizeof h && !memcmp(h, "BNTX", 4);
    uint64_t brtd = 0;
    if (ok) memcpy(&brtd, h + 0x30, 8);   /* (the NX block's pointer to the BRTD block, as the file has it: an offset) */
    ok = ok && brtd < 0x7fffffff && !fseek(f, (long)brtd, SEEK_SET) && fread(blk, 1, 16, f) == 16 && !memcmp(blk, "BRTD", 4);
    if (ok) {
        uint64_t size;
        memcpy(&size, blk + 8, 8);
        tex.data_off = brtd + 16;
        tex.data_len = size > 16 ? size - 16 : 0;
        for (int s = 0; s < SAMPLES && ok; s++) {   /* (a quarter, a half, three quarters in; past any run there) */
            uint64_t at = tex.data_off + tex.data_len / 4 * (s + 1);
            while (in_runs(at, SAMPLE_LEN, runs, nruns) && at + 2 * SAMPLE_LEN < tex.data_off + tex.data_len) at += 4096;
            tex.sample[s] = at;
            ok = !fseek(f, (long)at, SEEK_SET) && fread(tex.want[s], 1, SAMPLE_LEN, f) == SAMPLE_LEN;
        }
    }
    fclose(f);
    if (!ok || !tex.data_len) {
        tex.data_len = 0;
        hos_log("prompts: %s is not a texture file known: the textures change at the next start", bntx);
        return;
    }
    snprintf(tex.l.path, sizeof tex.l.path, "%s", bntx);
    keep_ranges(&tex.l, runs, nruns);
    free(tex.served);
    tex.served = (uint32_t (*)[2])malloc((nruns ? nruns : 1) * sizeof *tex.served);
    if (tex.served) memcpy(tex.served, tex.l.ranges, tex.l.nranges * sizeof *tex.served);
    tex.nserved = tex.served ? tex.l.nranges : 0;
}

/* nvn_native.c: a memory pool the game made (its storage, size bytes): the one Common.bntx's texture data is in? (Its
   texture data there, or the whole file) */
static SRWLOCK tex_lock = SRWLOCK_INIT;   /* (the textures' pool: found, let go, written; the game's threads and the input's) */
void hos_prompts_pool(uint64_t mem, uint64_t size) {
    if (!tex.data_len || tex.l.base || size < SAMPLE_LEN) return;
    const uint8_t *p = (const uint8_t *)hos_guest_range(mem, 4);
    if (!p) return;
    const uint64_t base = !memcmp(p, "BNTX", 4) ? mem : mem - tex.data_off;
    for (int s = 0; s < SAMPLES; s++) {
        const uint64_t a = base + tex.sample[s];
        const uint8_t *q = a >= mem && a + SAMPLE_LEN <= mem + size ? (const uint8_t *)hos_guest_range(a, SAMPLE_LEN) : NULL;
        if (!q || memcmp(q, tex.want[s], SAMPLE_LEN)) return;
    }
    AcquireSRWLockExclusive(&tex_lock);
    const int first = !tex.l.base;
    if (first) {
        tex.l.lo = mem, tex.l.hi = mem + size;
        part_face[PART_TEXTURES] = served_face[PART_TEXTURES];   /* (the file as served: a change since is written at the next look) */
        memcpy(part_bind[PART_TEXTURES], served_bind[PART_TEXTURES], sizeof part_bind[PART_TEXTURES]);
        if (tex.served) {   /* (the served runs: the bytes put back at that look) */
            free(tex.l.ranges);
            tex.l.ranges = (uint32_t (*)[2])malloc((tex.nserved ? tex.nserved : 1) * sizeof *tex.l.ranges);
            if (tex.l.ranges) memcpy(tex.l.ranges, tex.served, tex.nserved * sizeof *tex.served);
            tex.l.nranges = tex.l.ranges ? tex.nserved : 0;
        }
        __atomic_store_n(&tex.l.base, base, __ATOMIC_RELEASE);   /* (lo and hi first: the input thread reads them once base is set) */
    }
    ReleaseSRWLockExclusive(&tex_lock);
    if (first)
        hos_log("prompts: the textures' pool at %#llx (+%#llx): a new face or new controls show at once", (unsigned long long)mem,
                (unsigned long long)size);
}

/* nvn_native.c: the game finalized a memory pool (its storage): the textures' one? Then nothing is written there any more
   (the memory may hold something else), until the game makes it again (hos_prompts_pool). A change being written waits
   (tex_lock): the game frees the memory once this returns */
void hos_prompts_pool_gone(uint64_t mem) {
    if (!__atomic_load_n(&tex.l.base, __ATOMIC_ACQUIRE) || mem != tex.l.lo) return;
    AcquireSRWLockExclusive(&tex_lock);
    const int ours = tex.l.base && mem == tex.l.lo;
    if (ours) __atomic_store_n(&tex.l.base, 0, __ATOMIC_RELEASE);
    ReleaseSRWLockExclusive(&tex_lock);
    if (ours)
        hos_log("prompts: the textures' pool at %#llx was finalized: not written until the game makes it again",
                (unsigned long long)mem);
}

/* the face's textures.bin, read once (before tex_lock: a finalize waits for the writes alone); 0 none */
static int texture_bin(const char *dir, int face) {
    if (!tex.bins[face]) {
        char path[MAX_PATH];
        snprintf(path, sizeof path, "%sprompts/%s/textures.bin", dir, faces[face]);
        tex.bins[face] = read_all(path, "HPTX", &tex.nbins[face]);
    }
    return tex.bins[face] != NULL;
}

/* the pool's textures as this face and these controls choose them (tex_lock held); 0 when they could not be */
static int live_textures(const char *dir, int face, const int *bind) {
    if (!texture_bin(dir, face)) return 0;
    size_t nruns, written, put_back;
    if (!__atomic_load_n(&tex.l.base, __ATOMIC_ACQUIRE)) return 0;   /* (finalized since: hos_prompts_pool_gone) */
    Run *runs = texture_runs(tex.bins[face], tex.nbins[face], bind, &nruns);
    const size_t outside = put_runs(&tex.l, runs, nruns, &written, &put_back);
    free(runs);
    hos_log("prompts: now %s textures: %zu runs written, %zu put back%s", faces[face], written, put_back,
            outside ? " (some outside the pool: at the next start)" : "");
    return 1;
}

static Live lay;               /* over the game's Common.blarc */
static Layout lay_start;       /* the runs served (until find_layouts) */
static uint8_t lay_head[32];   /* the file's first bytes (no run writes them) */
static uint64_t lay_n;         /* its length, 0 not followed */

/* (build_layouts) the file the game loads and the runs served over it (o: kept until find_layouts) */
static void live_layouts_start(const char *blarc, const Layout *o) {
    FILE *f = fopen(blarc, "rb");
    long n = 0;
    const int headed = f && fread(lay_head, 1, sizeof lay_head, f) == sizeof lay_head &&
                       !in_runs(0, sizeof lay_head, o->runs, o->n) && !fseek(f, 0, SEEK_END) && (n = ftell(f)) > 0;
    if (f) fclose(f);
    if (!headed) {
        Layout drop = *o;
        layout_free(&drop);
        hos_log("prompts: %s is not a layout file known: the layouts change at the next start", blarc);
        return;
    }
    snprintf(lay.path, sizeof lay.path, "%s", blarc);
    lay.guarded = 1;
    lay_n = (uint64_t)n;
    lay_start = *o;
}

/* run r's bytes at q as write_patched left them: each one the run's, or a later run's (idx) over it */
static int run_as_served(const Run *runs, size_t n, size_t r, const uint8_t *q) {
    for (uint32_t k = 0; k < runs[r].len; k++) {
        if (q[k] == runs[r].data[k]) continue;
        const uint64_t at = (uint64_t)runs[r].off + k;
        int over = 0;
        for (size_t s = 0; s < n && !over; s++) over = runs[s].idx > runs[r].idx && at >= runs[s].off && at < (uint64_t)runs[s].off + runs[s].len;
        if (!over) return 0;
    }
    return 1;
}

/* where the game keeps the layouts: the whole Common.blarc, unpacked near the start of an address region of its own (the
   game's resources each take one: the textures' pool and the font too), its offsets made pointers where they lie. Looked
   for by the file's first bytes at the pages of each region's first 1 MB, every 2 s from when the textures' pool is known
   (the game unpacks its resources then; without the textures, at once), 30 times at most; then the runs served that are still
   there are the ones a change puts the game's bytes back over (put_runs, guarded: never over a pointer the game made) */
static void find_layouts(void) {
    static int tries;
    static int64_t last;
    static uint64_t regions[4096][2];
    const int64_t now = hos_now_ns();
    if (lay.base || tries >= 30 || !lay_n || (tex.data_len && !tex.l.lo) || now - last < 2000000000) return;
    last = now, tries++;
    int n = hos_regions(regions, 4096);
    if (n > 4096) n = 4096;
    for (int i = 0; i < n && !lay.base; i++) {
        const uint64_t lo = regions[i][0], hi = regions[i][1];
        for (uint64_t a = lo; a < lo + (1u << 20) && a < hi && hi - a >= lay_n && !lay.base; a += 4096) {
            const uint8_t *q = (const uint8_t *)hos_guest_range(a, sizeof lay_head);
            if (q && !memcmp(q, lay_head, sizeof lay_head) && hos_guest_range(a, lay_n)) lay.lo = a, lay.hi = a + lay_n, lay.base = a;
        }
    }
    size_t kept = 0;
    if (lay.base) {
        keep_ranges(&lay, lay_start.runs, lay_start.n);
        for (size_t r = 0; r < lay_start.n && r < lay.nranges; r++) {
            const Run *run = &lay_start.runs[r];
            const uint8_t *q = (const uint8_t *)hos_guest_range(lay.base + run->off, run->len);
            if (q && run_as_served(lay_start.runs, lay_start.n, r, q)) memmove(lay.ranges[kept++], lay.ranges[r], sizeof *lay.ranges);
        }
        lay.nranges = kept;
    }
    if (!lay.base && tries < 30) return;
    if (lay.base)
        hos_log("prompts: the layouts at %#llx: the Talk ring and the ocarina hint follow at once", (unsigned long long)lay.base);
    else
        hos_log("prompts: the layouts not found among the game's %d address regions: they change at the next start", n);
    if (lay.base && kept < lay_start.n)
        hos_log("prompts: %zu of the layouts' %zu runs served are no longer as served: left as the game has them", lay_start.n - kept,
                lay_start.n);
    layout_free(&lay_start);
}

static int live_layouts(const char *dir, int face, const int *bind) {
    const uint8_t *q = (const uint8_t *)hos_guest_range(lay.base, sizeof lay_head);
    /* (the game let the memory go: nothing written there. Unlike the textures' pool (tex_lock), nothing holds the region
       from here to the writes: the game frees its resources' regions on its own thread, with no hook here, so a region let
       go in that moment is not seen. A new run is still written only where the bytes are the file's (put_runs, guarded); the
       last change's bytes put back are not checked so) */
    if (!q || memcmp(q, lay_head, sizeof lay_head)) {
        hos_log("prompts: the layouts at %#llx are no longer there: they change at the next start", (unsigned long long)lay.base);
        lay.base = 0;
        return 0;
    }
    Layout o;
    layout_runs(dir, face, bind, &o);
    size_t written, put_back;
    const size_t outside = put_runs(&lay, o.runs, o.n, &written, &put_back);
    hos_log("prompts: now the Talk ring's A B X Y at places %d %d %d %d, the ocarina hint %s: %zu runs written, %zu put back%s",
            o.place[0], o.place[1], o.place[2], o.place[3], o.xs ? "spread" : "as is", written, put_back,
            outside ? " (some outside: at the next start)" : "");
    layout_free(&o);
    return 1;
}

/* the texts' icons after a change while the game runs. The game keeps each code's glyph drawn (by the code, whatever the font
   says now), so a text's Switch button codes are rewritten to codes of their own for the face and the pad input
   (BIND_BASE: never drawn before with another icon; in UTF-8 three bytes, as the game's), as the game lays the box out or
   updates it to draw it (nx2/oot_patches.py; box: the text box pane, its text at +0xf0 in UTF-8, often the layout's own,
   its length in bytes at +0x124), and the box laid out and drawn anew (its status, at +8: 0x20000 laid out, 0x100000 drawn,
   as the word after it allows). Until a change, the texts as the game has them: the font served for this start's face and
   controls */
static volatile LONG font_changes;

static int text_code(unsigned c, int face, const int *bind) {   /* the code that shows c's button now, else -1 */
    int b = -1, k = -1;
    for (int i = 0; i < HOS_SW_N && b < 0; i++)
        if (c == switch_code[i]) b = i;
    for (int i = 0; i < 3 && k < 0; i++)
        if (c == static_code[i]) k = i;
    if (c >= BIND_BASE && c < BIND_BASE + LIVE_FACES * HOS_SW_N * HOS_PAD_N) b = (int)((c - BIND_BASE) / HOS_PAD_N % HOS_SW_N);
    if (c >= VR_SW_BASE && c < VR_SW_BASE + 32) b = (int)((c - VR_SW_BASE) % 16);
    if (b >= 0 && live_vr_now > 0) return VR_SW_BASE + 16 * (live_vr_now - 1) + b;   /* ((Triforce VR) */
    if (c >= FACE_BASE + STATIC_AT && c < FACE_BASE + FACE_CODES * LIVE_FACES && (c - FACE_BASE) % FACE_CODES >= STATIC_AT &&
        (c - FACE_BASE) % FACE_CODES < STATIC_AT + 3)
        k = (int)((c - FACE_BASE) % FACE_CODES - STATIC_AT);
    if (k >= 0) return FACE_BASE + FACE_CODES * face + STATIC_AT + k;
    if (b < 0) return -1;
    const int pad = bind[b] >= 0 && bind[b] < HOS_PAD_N ? bind[b] : switch_pad[b];   /* (a paddle: the default's icon) */
    return BIND_BASE + (face * HOS_SW_N + b) * HOS_PAD_N + pad;
}

/* the box's codes for the buttons as they are now; 1 when it changed them */
static int text_rewrite(uint64_t box) {
    if (!font_changes) return 0;
    const int face = live_face_now;
    if (face < 0 || face >= LIVE_FACES) return 0;
    int bind[HOS_SW_N];
    memcpy(bind, live_bind_now, sizeof bind);
    const uint64_t *text = (const uint64_t *)hos_guest_range(box + 0xf0, 8);
    const uint32_t *len = (const uint32_t *)hos_guest_range(box + 0x124, 4);
    if (!text || !len || !*text || *len < 3 || *len > 65536) return 0;
    uint8_t *s = (uint8_t *)hos_guest_range(*text, *len);
    if (!s) return 0;
    int changed = 0;
    for (uint32_t i = 0; i + 2 < *len; i++) {   /* (UTF-8: the codes here are 3 bytes, 1110xxxx 10xxxxxx 10xxxxxx) */
        if ((s[i] != 0xEE && s[i] != 0xEF) || (s[i + 1] & 0xC0) != 0x80 || (s[i + 2] & 0xC0) != 0x80) continue;
        const unsigned code = (unsigned)(s[i] & 0x0F) << 12 | (unsigned)(s[i + 1] & 0x3F) << 6 | (s[i + 2] & 0x3F);
        const int c = text_code(code, face, bind);
        if (c >= 0 && (unsigned)c != code) {
            s[i] = (uint8_t)(0xE0 | c >> 12), s[i + 1] = (uint8_t)(0x80 | (c >> 6 & 0x3F)), s[i + 2] = (uint8_t)(0x80 | (c & 0x3F));
            changed = 1;
        }
        i += 2;
    }
    return changed;
}

/* the box's status bits set (as the word after them allows) */
static void mark_box(uint64_t box, uint32_t bits) {
    const uint64_t *status = (const uint64_t *)hos_guest_range(box + 8, 8);
    uint32_t *word = status && *status ? (uint32_t *)hos_guest_range(*status, 8) : NULL;
    if (word) *word |= bits & word[1];
}

/* nx2/oot_patches.py, as the game lays a text box out (f_8152aec0, before it looks at the box's status: laid out now) */
void hos_prompts_text_layout(uint64_t box) {
    if (text_rewrite(box)) mark_box(box, 0x20000);
}

/* nx2/oot_patches.py, as the game draws a text box (f_8152b670, each time it shows it): a box rewritten is laid out again at
   the next update (its status) */
void hos_prompts_text_draw(uint64_t box) {
    if (text_rewrite(box)) mark_box(box, 0x20000 | 0x100000);
}

/* nx2/oot_patches.py, as FreeType draws a glyph (ft_smooth_render, f_81680c60; slot: its FT_GlyphSlot): the font the glyph
   is of (slot->face at +8, the face's stream at +192: its base and size), the one served? Then where the game keeps it,
   decrypted (FreeType and the text shaping read it there) */
void hos_prompts_glyph(uint64_t slot) {
    static volatile uint64_t last;   /* (the last face found to be another font: its glyphs not looked at again) */
    if (font.at || !font.n || !font.live) return;
    const uint64_t *s = (const uint64_t *)hos_guest_range(slot + 8, 8);
    const uint64_t face = s ? *s : 0;
    if (!face || face == last) return;
    const uint64_t *st = (const uint64_t *)hos_guest_range(face + 192, 8);
    const uint64_t *base = st ? (const uint64_t *)hos_guest_range(*st, 16) : NULL;
    if (!base) return;   /* (not readable yet: looked at again) */
    if (base[1] != font.n && base[1] != font.n - 8) {
        last = face;   /* (another font: not looked at again while its glyphs follow each other) */
        return;
    }
    /* (a stream of the file's size may hold the font behind its 8-byte header, or from its start, as on native Windows: the
       font's own head says which) */
    uint64_t at = 0;
    int unread = 0;
    for (uint64_t a = base[0] + (base[1] == font.n ? 8 : 0);; a = base[0]) {
        const uint8_t *q = (const uint8_t *)hos_guest_range(a, font.n - 8);
        if (!q) unread = 1;
        else if (!memcmp(q, font.head, sizeof font.head)) {
            at = a;
            break;
        }
        if (a == base[0]) break;
    }
    if (!at) {
        if (!unread) last = face;   /* (another font of that size) */
        return;   /* (else not readable yet: looked at again) */
    }
    font.at = at;
    hos_log("prompts: the font at %#llx: the icons in texts follow at once", (unsigned long long)font.at);
}

/* the served font (the start's face's file) pointed at this face and these controls (cmap4_bind), written where the game
   keeps it: its tables' directory and size the same, only the cmap changes */
static int live_font(const char *dir, int start, int face) {
    char path[MAX_PATH];
    snprintf(path, sizeof path, "%sprompts/%s/External.bfotf", dir, faces[start]);
    long n;
    uint8_t *b = read_all(path, NULL, &n);
    if (!b || n < 16 || n % 4 || (uint32_t)n != font.n) {
        free(b);
        hos_log("prompts: %s is not the font served: the icons in texts at the next start", path);
        return 0;
    }
    const uint32_t key = rd32le(b) ^ MAGIC;
    for (long i = 8; i < n; i += 4) wr32le(b + i, rd32le(b + i) ^ key);
    const int bound = bind_font(b + 8, (size_t)n - 8, face);
    uint8_t *q = (uint8_t *)hos_guest_range(font.at, (uint64_t)n - 8);
    const int ok = q && !memcmp(q, b + 8, 64);   /* (still the font: its tables' directory, which a binding leaves as is) */
    if (ok) {
        memcpy(q, b + 8, (size_t)n - 8);
        InterlockedIncrement(&font_changes);
        hos_log("prompts: now the %s icons in texts, %d buttons on these controls", faces[face], bound);
    } else {
        hos_log("prompts: the font is no longer where FreeType read it: the icons in texts at the next start");
    }
    free(b);
    return ok;
}

volatile int hos_prompts_row = -1;   /* nn_hid.c's live input ("!prompts <row>"): over the menu's row, -1 none */

/* the face the Button prompts row chooses now: Auto, the first controller's (by its type where its name says no maker; none:
   the face shown, as the keys' face cannot be followed); -1 none known */
static int live_face(void) {
    const int choice = hos_prompts_row >= 0 ? hos_prompts_row : rx_option(HOS_OPT_PROMPTS, -1);
    if (choice >= 1 && choice <= HOS_PROMPT_N) return choice - 1;
    if (choice < 0) return live_face_now;   /* (no menu: the start's) */
    char name[128] = "";
    hos_sdl_pad_first_name(name, sizeof name);
    if (!name[0]) return live_face_now;
    int sdl = 0;
    const int type = hos_sdl_pad_type_of(0, &sdl);
    return typed_face(auto_face(name, 0, -1), name, sdl, type);
}

/* nn_hid.c, as the game reads its controller (every frame; looked at every 100 ms): the face or the controls changed, or a
   part found since that still shows what was before? */
int hos_prompts_live_parts(void);
void hos_prompts_live(void) {
    static volatile LONG busy;
    static int64_t last;
    const int pool = __atomic_load_n(&tex.l.base, __ATOMIC_ACQUIRE) != 0;   /* (hos_prompts_pool: lo and hi set before) */
    if (live_face_now < 0 || live_face_now >= LIVE_FACES || (!pool && !lay_n && !font.at) ||
        InterlockedCompareExchange(&busy, 1, 0))
        return;
    const int64_t now = hos_now_ns();
    if (now - last >= 100000000) {
        last = now;
        find_layouts();
        int bind[HOS_SW_N];
        for (int b = 0; b < HOS_SW_N; b++) bind[b] = hos_binding(HOS_BIND_PAD, b, 0);
        const int face = live_face();
        const int vr = vr_prompts_scheme();   /* ((Triforce VR) a session's start or end, or another scheme: the font anew */
        static int part_vr = -1;
        const int vr_changed = vr != part_vr && font.at != 0;
        /* (the menu asks for a restart then: nothing changes before, no part on another face than the rest) */
        if (face < 0 || face >= LIVE_FACES || (hos_prompts_live_parts() & HOS_PROMPTS_LIVE_ALL) != HOS_PROMPTS_LIVE_ALL) {
            InterlockedExchange(&busy, 0);
            return;
        }
        live_face_now = face;
        memcpy(live_bind_now, bind, sizeof live_bind_now);
        const int found[PARTS] = {0, lay.base != 0, font.at != 0};   /* (the textures: looked at under tex_lock) */
        char dir[MAX_PATH];
        int ignored, ready = -1;
        if (tex.l.base && (part_face[PART_TEXTURES] != face || memcmp(part_bind[PART_TEXTURES], bind, sizeof bind)) &&
            (ready = setup(dir, sizeof dir, &ignored)))
            texture_bin(dir, face);   /* (read before tex_lock) */
        for (int p = 0; p < PARTS; p++) {
            if (p == PART_TEXTURES) AcquireSRWLockExclusive(&tex_lock);   /* (the pool kept, or let go, till its writes end) */
            const int here = p == PART_TEXTURES ? tex.l.base != 0 : found[p];
            if (here && (part_face[p] != face || memcmp(part_bind[p], bind, sizeof bind) || (p == PART_FONT && vr_changed))) {
                if (p == PART_FONT) live_vr_now = vr, part_vr = vr;
                if (ready < 0) ready = setup(dir, sizeof dir, &ignored);
                if (ready && p == PART_TEXTURES) live_textures(dir, face, bind);
                if (ready && p == PART_LAYOUTS) live_layouts(dir, face, bind);
                if (ready && p == PART_FONT) live_font(dir, served_face[PART_FONT], face);
                part_face[p] = face;   /* (also when it failed: not tried again until the next change) */
                memcpy(part_bind[p], bind, sizeof part_bind[p]);
            }
            if (p == PART_TEXTURES) ReleaseSRWLockExclusive(&tex_lock);
        }
    }
    InterlockedExchange(&busy, 0);
}

/* what the Insert menu's Button prompts row can change at once (vk_api.h HOS_PROMPTS_LIVE_*): each part the game has loaded
   from a file served here and found, or that none was served for (the game's own then, whatever the face); 0 with none found,
   with the keys' face shown, or with a font built before (not every controller's icons: font.live) */
int hos_prompts_live_parts(void) {
    if (live_face_now < 0 || live_face_now >= LIVE_FACES) return 0;
    const int t = tex.l.base != 0, l = lay.base != 0, f = font.at != 0 && font.live;
    if (!t && !l && !f) return 0;
    return (t || !tex.data_len ? HOS_PROMPTS_LIVE_TEXTURES : 0) | (l || !lay_n ? HOS_PROMPTS_LIVE_LAYOUTS : 0) |
           (f || !font.n ? HOS_PROMPTS_LIVE_TEXTS : 0);
}

/* the face of the device used last (device: hos_input_last's; name: the controller used last's, SDL's, "" none: XInput's,
   an Xbox pad), -1 none yet */
static int device_face(int device, const char *name) {
    return device == 2 ? auto_face(name, 1, -1) : device == 1 ? HOS_PROMPT_KEYBOARD : -1;
}

/* follow_main's: the device's face (device_face) held since held_ns, the looks it was used in since (active), and the face
   auto_path has (-1 none) */
typedef struct { int held, recorded; int64_t held_ns; int active; } Follow;
/* ((Triforce, 11-19) the keys' face is recorded once they have been used in this many of the looks (a quarter second
   each) while they were the device used last: a key pressed once, or the mouse bumped, and the game then left alone is
   not a player of the keys */
#define KEYS_ACTIVE 20
/* face seen at now, its device used since the last look or not (active): whether auto_path is to have it now (then
   recorded is it) */
static int follow_record(Follow *f, int face, int64_t now, int active) {
    if (face < 0) return 0;
    if (face != f->held) f->held = face, f->held_ns = now, f->active = 0;
    if (active) f->active++;
    const int keys = face == HOS_PROMPT_KEYBOARD;
    if (face == f->recorded || now - f->held_ns < (keys ? 30 : 3) * 1000000000LL || (keys && f->active < KEYS_ACTIVE)) return 0;
    f->recorded = face;
    return 1;
}

/* ((Triforce, 11-19) the overlay's icons follow a controller once it has been the one used last this long: two controllers
   of two faces given the same presses (a DualSense and the virtual Xbox pad DS4Windows makes of it, a Steam Input pad)
   take turns as the one used last, and the icons would change at each press */
#define PAD_HOLD_NS 1000000000LL
/* whether the overlay is to show face's icons now: the game has the keys' face, face is a controller's, not the one shown
   (shown: -1 none), the one used last for PAD_HOLD_NS (held_ns) unless none is shown yet, and not one whose font cannot be
   made (failed: a bit a face) */
static int pad_font_due(int served, int face, int shown, int64_t held_ns, unsigned failed) {
    return served == HOS_PROMPT_KEYBOARD && face >= 0 && face != HOS_PROMPT_KEYBOARD && face != shown && !(failed >> face & 1) &&
           (shown < 0 || held_ns >= PAD_HOLD_NS);
}

/* ((Triforce, 11-19) The device the player uses (host/nn_hid.c hos_input_last), looked at four times a second on a thread
   of its own, from the start (setup) on Auto or with the keys' face:
   - while the game has the keys' face, a controller used builds the overlay's font of its face (build_font's pad), once a
     run for each face (prompts/External.pad.<n>.bfotf.zs), and hos_prompts_pad_face says which to show once written;
     another face's after it has been the last for a second (pad_font_due). One not written is tried again 2 s on;
   - on Auto, the face of the device used last (a controller: its name's, auto_face; the keys or the mouse: theirs) goes
     into auto_path for the next start (remembered_face) once it has been the last for 3 s, the keys' for 30 s and used in
     5 s of them (a key pressed between a controller's presses, or to close the game, keeps the controller's); written
     only when it changes. Never on the input's thread: read_input only stores the device */
static volatile LONG pad_face_shown = -1;   /* the face of the overlay's font to show this run (built), -1 none */
static DWORD WINAPI follow_main(void *arg) {
    (void)arg;
    hos_host_thread_register_self("button prompts");
    char dir[MAX_PATH];
    int served;
    setup(dir, sizeof dir, &served);
    Follow follow = {-1, remembered_face(dir), 0, 0};
    unsigned built = 0, failed = 0, uses[3] = {0};
    int seen = -1;   /* (the face used last, since seen_ns) */
    int64_t seen_ns = 0, retry_ns[HOS_PROMPT_N] = {0};
    for (;;) {
        Sleep(250);
        char name[128] = "";
        const int device = hos_input_last();
        if (device == 2) hos_sdl_pad_last_name(name, sizeof name);
        int sdl = 0;
        const int type = device == 2 && name[0] ? hos_sdl_pad_type_of(1, &sdl) : 0;
        const int face = typed_face(device_face(device, name), name, sdl, type);   /* ((Triforce) by SDL's type where the name says no maker) */
        const int64_t now = hos_now_ns();
        const unsigned used = hos_input_uses(device);
        const int active = device >= 1 && device <= 2 && used != uses[device];
        if (device >= 1 && device <= 2) uses[device] = used;
        if (face != seen) seen = face, seen_ns = now;
        if (pad_font_due(served, face, (int)pad_face_shown, now - seen_ns, failed) && now >= retry_ns[face]) {
            char out[MAX_PATH], file[48];
            snprintf(file, sizeof file, "External.pad.%d.bfotf.zs", face);
            const int got = built >> face & 1 ? 1 : build_font(dir, face, file, 1, out, sizeof out);
            if (got > 0) built |= 1u << face, InterlockedExchange(&pad_face_shown, face);
            else if (got < 0) failed |= 1u << face;   /* (no font of that face: not tried again) */
            else retry_ns[face] = now + 2000000000LL;   /* (not written: again in 2 s) */
        }
        if (chosen_auto && follow_record(&follow, face, now, active)) {   /* (written or not: again only when it changes) */
            char path[MAX_PATH];
            auto_path(path, sizeof path);
            FILE *f = fopen(path, "w");
            int ok = f && fputs(faces[face], f) >= 0;
            if (f) ok &= fclose(f) == 0;
            hos_log("prompts: auto: the device used last has the %s face: the next start's without a controller%s",
                    faces[face], ok ? "" : " (prompts_auto.txt could not be written)");
        }
    }
}

/* ((Triforce) the face of the controller used last whose icons the overlay is to show, from prompts/External.pad.<n>.bfotf.zs
   (n the face's HOS_PROMPT_*), built while the game has the keys' face (follow_main); -1 none (no controller used yet, or the
   game has a controller's face) */
int hos_prompts_pad_face(void) {
    return (int)pad_face_shown;
}

/* (Triforce) The Insert menu's Camera speed row (camera_speed= in the options file, percent; HOS_CAMERA_SPEED=<percent>
   over it): how fast the right stick turns the camera, times the game's own speed at any of the five Camera sensitivity
   settings of its Options. The rates are five floats in the game's camera pack (nx2/prompt_assets.py CAMERA has where and
   why): prompts/PlayerCamera.pack.zs is that pack (prompts/PlayerCamera.pack) with each rate of prompts/camera.bin ("HPCM",
   u32 count; each: u32 offset, f32 the game's rate) times the factor. Read once: the game loads the pack at its start, so
   the row applies after a restart. At 100 the game's own file is served. NX2navi's camera speed setting, without its
   search of the game's memory for a change during play. */
int hos_ini_option(const char *key, int otherwise);
static volatile double camera_applied = 1.0;   /* the factor in the pack the game was given */
static double camera_wanted(void) {
    static int v = -1;
    if (v < 0) {
        const char *e = getenv("HOS_CAMERA_SPEED");
        v = e && atoi(e) > 0 ? atoi(e) : hos_ini_option("camera_speed", 100);
        v = v < 25 ? 25 : v > 300 ? 300 : v;
    }
    return v / 100.0;
}
/* host/nn_hid.c: the mouse's panning reaches the game as the right stick; divided by this it keeps its own sensitivity */
double hos_camera_speed(void) {
    return camera_applied;
}
static int build_camera(char *out, size_t cap) {
    char dir[MAX_PATH], path[MAX_PATH], keypath[MAX_PATH];
    int face;
    const double k = camera_wanted();
    if (k == 1.0 || !setup(dir, sizeof dir, &face)) return 0;
    long tn = 0;
    snprintf(path, sizeof path, "%sprompts/camera.bin", dir);
    uint8_t *t = read_all(path, "HPCM", &tn);
    const uint32_t count = t ? rd32le(t + 4) : 0;
    if (!count || count > 8 || (size_t)tn < 8 + 8 * (size_t)count) {
        hos_log("prompts: no prompts/camera.bin: the camera keeps the game's speed (Setup's Update makes it)");
        free(t);
        return 0;
    }
    float rates[8];
    size_t nruns = 0, cap_runs = 8;
    Run *runs = (Run *)malloc(cap_runs * sizeof *runs);
    for (uint32_t i = 0; i < count; i++) {
        memcpy(&rates[i], t + 8 + 8 * i + 4, 4);
        rates[i] = (float)(rates[i] * k);
        add_run(&runs, &nruns, &cap_runs, rd32le(t + 8 + 8 * i), 4, (const uint8_t *)&rates[i]);
    }
    const uint64_t h = fnv(fnv(0xcbf29ce484222325ull, &k, sizeof k), t, (size_t)tn);
    snprintf(out, cap, "%sprompts/PlayerCamera.pack.zs", dir);
    snprintf(path, sizeof path, "%sprompts/PlayerCamera.pack", dir);
    snprintf(keypath, sizeof keypath, "%sprompts/PlayerCamera.key", dir);
    const int ok = write_patched(path, out, keypath, h, runs, nruns);
    if (ok) camera_applied = k;
    hos_log("prompts: camera speed x%.2f, the first rate %.2f%s", k, (double)rates[0], ok ? "" : ": could not be written");
    free(runs);
    free(t);
    return ok;
}

int hos_prompts_romfs(const char *key, char *out, size_t cap);
/* ((Triforce, 11-18) mods.c's size hook: for the font's key (lower case, '/', packed name), the font built for this run
   (built now if it was not), 1 with one; 0 for any other key or with no prompts. A mod's own font is the mod's: the hook
   finds that one first) */
int hos_prompts_font_file(const char *key, char *out, size_t cap) {
    if (strcmp(key, FONT_PATH)) return 0;
    /* ((Triforce, 11-21, the performance audit's IO-24) from the lifted code's size hook (host/mods.c), a game thread: the
       core given up around the builder, which builds the font at its first call and holds its lock meanwhile; never inside
       hos_prompts_romfs, where that lock is held) */
    const int away = hos_vcore_away();
    const int found = hos_prompts_romfs(FONT_PATH, out, cap);
    if (away) hos_vcore_back();
    return found;
}

/* (Triforce) The title screen's third entry, "Options / ZELDA NOTES Setting" in US English, reads "Options / Triforce":
   prompts/mals/<language>.product.110.sarc.zs is that language's messages (Mals/, its name in lower case) with the entry's
   rest after the game's word for Options made Triforce's (nx2/prompt_assets.py title_messages; the wording is its
   TITLE_TEXT), built at Setup's Update from the player's own files. The one of the language the game shows is served
   (desired_language: language.txt, HOS_LANGUAGE over it), each language's messages are a file of their own. No larger
   than the game's file (title_messages writes no other), so the size table's entry holds it with its allowance. A mod's file of the same name wins (mods.c asks here only without one) */
const char *hos_desired_language(void);   /* nn_applet.c */
static const struct { const char *code, *mals; } title_languages[] = {   /* (nn_applet.c languages[] -> romfs/Mals) */
    {"en-US", "usen"}, {"en-GB", "euen"}, {"fr", "eufr"}, {"fr-CA", "usfr"}, {"de", "eude"}, {"it", "euit"},
    {"es", "eues"}, {"es-419", "uses"}, {"pt-BR", "uspt"}, {"nl", "eunl"}, {"pl", "eupl"}, {"ru", "euru"},
    {"ja", "jpja"}, {"ko", "krko"}, {"zh-Hans", "cnzh"}, {"zh-Hant", "twzh"},
};
/* (Triforce VR) the language's Mals name ("usen"), for the VR item panel's texts */
const char *hos_mals_language(void) {
    const char *lang = hos_desired_language(), *mals = "usen";
    for (size_t i = 0; i < sizeof title_languages / sizeof *title_languages; i++)
        if (!strcmp(lang, title_languages[i].code)) mals = title_languages[i].mals;
    return mals;
}
static int title_messages(const char *key, char *out, size_t cap) {
    char dir[MAX_PATH], want[16];
    int face;
    const char *lang = hos_desired_language(), *mals = "usen";
    for (size_t i = 0; i < sizeof title_languages / sizeof *title_languages; i++)
        if (!strcmp(lang, title_languages[i].code)) mals = title_languages[i].mals;
    snprintf(want, sizeof want, "mals/%s.", mals);
    if (strncmp(key, want, strlen(want)) || !setup(dir, sizeof dir, &face)) return 0;   /* (another language's: the game's) */
    snprintf(out, cap, "%sprompts/%s", dir, key);
    const int ok = GetFileAttributesA(out) != INVALID_FILE_ATTRIBUTES;
    static volatile LONG logged;
    if (InterlockedExchange(&logged, 1) == 0)
        hos_log(ok ? "prompts: the title's Options entry from prompts/%s (%s)"
                   : "prompts: no prompts/%s (%s): the title's Options entry is the game's (Setup's Update makes it)", key, lang);
    return ok;
}

/* mods.c: the file for a RomFS path the prompts replace (key: lower case, '/'), 1 with one. Asked only when no mod has
   the file: a mod's own wins */
int hos_prompts_romfs(const char *key, char *out, size_t cap) {
    static volatile LONG state[4];   /* the font, the textures, the layouts, the camera: 0 not built, 1 being built, 2 built, 3 none */
    static char path[4][MAX_PATH];
    const size_t kn = strlen(key);
    if (!strncmp(key, "mals/", 5) && kn > 8 && !strcmp(key + kn - 8, ".sarc.zs")) return title_messages(key, out, cap);
    if (!strncmp(key, SIZES_PATH, sizeof SIZES_PATH - 1) && kn > 14 && !strcmp(key + kn - 14, ".rsizetable.zs")) {
        char dir[MAX_PATH];   /* (the game's size table with room for the faces' fonts, larger than its: nx2/prompt_assets.py) */
        int face;
        if (!setup(dir, sizeof dir, &face)) return 0;
        snprintf(out, cap, "%sprompts/rsizetable.zs", dir);
        return GetFileAttributesA(out) != INVALID_FILE_ATTRIBUTES;
    }
    const int which = !strcmp(key, FONT_PATH) ? 0 : !strcmp(key, TEXTURES_PATH) ? 1 : !strcmp(key, LAYOUTS_PATH) ? 2 :
                      !strcmp(key, CAMERA_PATH) ? 3 : -1;
    if (which < 0) return 0;
    static int (*const builders[4])(char *, size_t) = {build, build_textures, build_layouts, build_camera};
    if (InterlockedCompareExchange(&state[which], 1, 0) == 0)
        InterlockedExchange(&state[which], builders[which](path[which], MAX_PATH) ? 2 : 3);
    while (state[which] == 1) Sleep(1);
    if (state[which] != 2) return 0;
    snprintf(out, cap, "%s", path[which]);
    return 1;
}
