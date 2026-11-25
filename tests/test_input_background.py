"""Exercise real scripted parsing, routing and Npad serialization with authored files/API spies.

The parser, LIVE reader, input routing and Npad writer are extracted unmodified from production. Clock,
foreground-window, keyboard, mouse and pad APIs are fakes; no real device, desktop or game is accessed.
Each case starts a fresh process because production caches environment settings. Frame-clock cases retain holds
through a seven-second wall pause, test native-frame boundaries/live offsets/slot reuse, and keep default/0/empty controls.

Controllers counted only while the game's window was in front, so a game streamed from a screen of its own (Sunshine
and Moonlight), or left running behind another window, ignored the pad. The Insert menu's "Controller in background"
row, or HOS_INPUT_BACKGROUND=1, lets the pads through; the keyboard and mouse stay with the window in front.

The "walk" case is the Insert menu's Walk key row through the same path: the movement keys' push of the left stick is
scaled while the walk key is held, and the script's and the pad's are not (tests/test_walk_key.py has the rest).

(Triforce) The "options-back" case: our options' tabs inside the game's own Options screen left with the mouse's right button
held tap the game's Back, as the pad's B and Esc do.

The "menu-side-buttons" case: while one of the game's menus has the mouse, its side buttons stay their controls' (Mouse 4
on A confirms a choice); free in play they are none.

The "held-input" case: an input held down is the player's input (the game menus' cursor hides by it) when it goes down, not
at every read while it stays down, so the mouse's hover works while ZL is held for the ocarina's song sheet.

python -I -B tests/test_input_background.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
CASES = ("foreground", "script-background", "headless", "noactivate", "live-background",
         "no-script-background", "exclusive-foreground", "exclusive-background", "pads-env", "pads-menu", "pads-off",
         "frame-hold", "live-frame", "reuse-frame", "wall", "zero", "empty", "no-window", "walk", "options-back",
         "held-input", "menu-side-buttons", "deck-mouse")


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    p.add_argument("--case", choices=CASES)
    a = p.parse_args()
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")

    read = block(hid, "static void read_input(")
    behind = read[read.index("if (!game_in_front()"):]   # (with or without PR 545's scripted-background test)
    behind = behind[:behind.index("return;") + len("return;")]
    if "pads_in_background(" not in behind or "pads_read(" not in behind:
        raise SystemExit("behind another window the pads are never read")
    if "key(" in behind or "mouse" in behind:
        raise SystemExit("behind another window the keyboard or mouse would reach the game")
    # ((Triforce, 11-18) the Insert menu reads the pads in the background as the game does, and while it is open there the
    # pads are its own, not the game's too)
    if "if (!rx_option(1, 0)) {" not in behind or "*buttons |= pb;" not in behind:
        raise SystemExit("behind another window the pads reach the game while the Insert menu is open")
    if "const bool pads_ok = mine || (pad_bg_env ? atoi(pad_bg_env) != 0 : opts.pad_background != 0);" not in menu or \
            "uint32_t raw = pads_ok && host && host->pad_raw ? host->pad_raw() : 0" not in menu:   # ((Triforce VR) not const: the hand controllers' menu bits are added to it
        raise SystemExit("the Insert menu takes the pads only from the window in front, while the game takes them behind it")
    option = replay[replay.index("t.option = "):]
    option = option[:option.index("};") + 2]
    if "id == 4 ? opts.pad_background" not in option:
        raise SystemExit("the host cannot see the menu's row (option 4)")
    if '"Controller in background", &opts.pad_background' not in menu:
        raise SystemExit("the Insert menu has no row for it")

    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    constants = block(hid, "enum { B_A") + ";\n" + block(api, "enum { HOS_SW_A") + ";\n"
    constants += block(api, "enum { HOS_KEY_MOVE_UP") + ";\n"   # (the keys-only controls)
    # (the gamepads' inputs by position and the two sets of controls: read_input asks which pad input B is bound to)
    constants += block(api, "enum { HOS_PAD_SOUTH") + ";\n" + block(api, "enum { HOS_BIND_PAD") + ";\n"
    constants += block(api, "enum { HOS_PAD_LS_UP") + ";\n"   # (the sticks' bits among the pads': a stick the Insert menu had waits)
    # ((Triforce) 11-24: the rear paddles, inputs a binding can take)
    constants += block(api, "enum { HOS_PAD_RPADDLE1") + ";\n"
    constants += re.search(r"^#define hos_pad_bindable\(hos_pad_input_\)[^\n]*", api, re.M).group(0) + "\n"
    constants += block(api, "enum { HOS_OPT_CHEAT_HEARTS") + ";\n"
    constants += block(api, "enum { HOS_OPT_RUMBLE_CURVE") + ";\n"   # (the walk key's row and its scale, which read_input asks for)
    # ((Triforce) the Mods entry under the game's lists: npad_states keeps Down from the game there, and all while Mods has the cursor)
    constants += block(api, "enum { HOS_OPT_MODS_LIST") + ";\n" + block(api, "enum { HOS_MODS_PRESS_UP") + ";\n"
    constants += block(api, "enum { HOS_OPT_TEXT_CHAR") + ";\n"   # ((Triforce) the live file's "!type", the search's text)
    constants += block(api, "enum { HOS_OPT_HOLD_TOGGLE") + ";\n"   # ((Triforce) 11-24: hold-to-toggle's rows, which npad_states asks for)
    for name in ("STATE_SIZE", "NPAD_NO1", "ATTR_CONNECTED"):
        matches = re.findall(r"^#define " + name + r"\s+[^\n]+", hid, re.M)
        assert len(matches) == 1, name
        constants += matches[0] + "\n"
    start = hid.index("typedef struct { int64_t start_ms, end_ms;")
    script = block(hid, "static void scripted_input(")
    end = hid.index(script) + len(script)
    cheat_state = re.search(r"^static uint64_t flight_input;\nstatic uint64_t free_camera_axes;\nstatic int free_camera_height;\n"
                            r"static int move_stick_held;", hid, re.M).group(0)
    # ((Triforce, 11-24) the no-clip flight's Jump: host/flight_jump.h, the game's option not read yet, as at the start)
    cheat_state += "\n" + (ROOT / "host/flight_jump.h").read_text(encoding="utf-8")
    cheat_spies = """
volatile int hos_oot_jump_swapped = -1;
volatile int hos_oot_live_action;
volatile uint64_t hos_npad_buttons;   /* (nn_hid.c's own, beside npad_states: the buttons the game was given, for the mods' cheats) */
int hos_oot_flight_shortcut_ready(void) { CHECK(!"unexpected cheat readiness query"); return 0; }
void rx_option_set(int id, int value) { (void)id; (void)value; CHECK(!"unexpected cheat option change"); }
"""
    # (the host's own presses and stick, for the game's menus' mouse (host/oot_menu.c): none here; the player's input
    # time it hides the mouse by: not looked at; the Scan amiibo page's choice, which the pad read takes
    # (host/nn_nfp.c, tests/test_amiibo.py): none here)
    host_spies = """
static void host_taps(void) {}
static void host_stick_read(int32_t stick[4]) { (void)stick; }
static void host_drag_read(int32_t stick[4]) { (void)stick; }
static int player_stamps;   /* (the input the game menus' cursor hides by: the "held-input" case counts them) */
static void player_used(void) { player_stamps++; }
void hos_amiibo_poll(void) {}
int hos_oot_mods_down(void) { return 0; }   /* ((Triforce) host/oot_menu.c: no game list's last button has the cursor here) */
void vr_pad_read(Ctx *c, uint64_t *buttons, int32_t stick[4]) { (void)c; (void)buttons; (void)stick; }   /* ((Triforce VR) host/vr_game.c: no headset here) */
static void device_used(int device) { (void)device; }   /* ((Triforce) the device used last, for the button prompts: not looked at */
static void mods_input(uint64_t *buttons, int32_t stick[4]) { (void)buttons, (void)stick; }   /* (and no Mods entry's input) */
int hos_bench_input_only(void) { return 0; }   /* ((Triforce) host/hos_bench.c: benchmark mode off */
/* ((Triforce) host/control.c: the control bridge off (HOS_CONTROL unset), its presses none */
static int hos_control_input(uint64_t *buttons, int32_t stick[4]) { (void)buttons, (void)stick; return 0; }
"""
    # ((Triforce) 11-24: hold-to-toggle's rule and its state as nn_hid.c has them, beside its bindings; every row off here)
    toggle_at = hid.index("static volatile LONG toggle_reset;")
    toggle_state = ("typedef long LONG;\nstatic LONG InterlockedExchange(volatile LONG *p, LONG v) { const LONG o = *p; *p = v; return o; }\n" +
                    (ROOT / "host/hold_toggle.h").read_text(encoding="utf-8") + "\n" +
                    hid[toggle_at:hid.index("\n", hid.index("void hos_input_clear_toggles(void) {", toggle_at)) + 1])
    actual = "\n".join((cheat_state, cheat_spies, host_spies, toggle_state, block(hid, "static int key("), block(hid, "static int kmap_down("),
        block(hid, "static int game_in_front("), hid[start:end], block(hid, "static void stick_max("),
        block(hid, "static int pads_in_background("),
        # (the bound keys' helpers read_input calls: a mouse button counts only while the mouse is captured)
        block(hid, "static int mouse_vk_slot("), re.search(r"^static int mouse_armed\[5\];", hid, re.M).group(0),
        block(hid, "static void mouse_buttons_arm("),
        # (the walk key: no control's key while it is the walk key, and the movement keys' stick while it is held)
        re.search(r"^static int walk_vk;", hid, re.M).group(0), block(hid, "static int is_hud_row("),
        block(hid, "static uint64_t hud_pad_mask("), block(hid, "static int bound_down("),
        block(hid, "static void hud_shortcut("),   # ((Triforce) the Toggle HUD row: unbound here)
        block(hid, "static int walk_key_code("), block(hid, "static void walk_keys("),
        # ((Triforce) 11-24: the ocarina's note layer, which read_input runs first and npad_states asks last)
        block(hid, "static void oc_notes("), block(hid, "static uint64_t oc_pad_word("),
        block(hid, "static uint64_t flight_jump(void) {"), block(hid, "static int flight_jump_shortcut("), read, block(hid, "static void npad_states(")))
    glue = (ROOT / "host/mkw_glue.c").read_text(encoding="utf-8")
    actual += "\n" + "\n".join(block(glue, "uint64_t " + name + "(")
                                  for name in ("hos_title_input", "hos_frame_step_buttons"))
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("HOS_INPUT_") or name in ("HOS_HEADLESS", "HOS_WINDOW_NOACTIVATE"):
            del env[name]
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    def run(command, environment=None):
        result = subprocess.run(command, env=environment, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=flags)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        result.check_returncode()
    with tempfile.TemporaryDirectory(prefix="input-background-") as tmp:
        folder = Path(tmp).resolve()
        assert folder.parent == Path(tempfile.gettempdir()).resolve() and folder.name.startswith("input-background-")
        (folder / "input_constants.inc").write_text(constants, encoding="utf-8")
        (folder / "input_actual.inc").write_text(actual, encoding="utf-8")
        exe = folder / "fixture.exe"
        # Production's button table deliberately leaves its unused axis fields zero-initialized.
        run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
             "-D_CRT_SECURE_NO_WARNINGS",
             "-I" + str(folder), str(ROOT / "tests/input_background_test.c"), "-o", str(exe)])
        for case in ((a.case,) if a.case else CASES):
            case_env = dict(env)
            if case not in ("live-background", "no-script-background", "live-frame", "reuse-frame", "held-input", "menu-side-buttons", "deck-mouse"):
                case_env["HOS_INPUT_SCRIPT"] = "0:A+LUP/200"
            if case in ("frame-hold", "live-frame", "reuse-frame"):
                case_env["HOS_INPUT_FRAME_CLOCK"] = "1"
            elif case in ("zero", "empty"):
                case_env["HOS_INPUT_FRAME_CLOCK"] = "0" if case == "zero" else ""
            if case.startswith("exclusive-") or case in ("frame-hold", "wall", "zero", "empty"):
                case_env["HOS_INPUT_EXCLUSIVE"] = "1"
            if case in ("pads-env", "pads-off"):
                case_env["HOS_INPUT_BACKGROUND"] = "1" if case == "pads-env" else "0"
            if case == "headless":
                case_env["HOS_HEADLESS"] = "1"
            if case == "noactivate":
                case_env["HOS_WINDOW_NOACTIVATE"] = "1"
            if case in ("live-background", "live-frame"):
                live = folder / (case + ".txt")
                live.write_bytes(b"")
                case_env["HOS_INPUT_LIVE"] = str(live)
            run([str(exe), case], case_env)
        assert folder.parent == Path(tempfile.gettempdir()).resolve() and folder.name.startswith("input-background-")


if __name__ == "__main__":
    main()
