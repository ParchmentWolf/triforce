"""N64 Classic in the Insert menu (gpu/vk/vk_menu.cpp, vk_menu.h; vk_n64.cpp): the Graphics tab's N64 Classic row, the
Remembered page its Remembered settings row opens, F7, and the rows it stands in front of. Step 5 of n64-classic-mode-plan.md.
No game, no GPU.

Read in the sources:

- vk_menu.h: the row Off by default, F7's last preset Faithful, the Remembered page's values n64_rules.h's defaults;
- the rows: a heading and the N64 Classic row after the Anti-aliasing row on the Graphics tab, Off to Remembered, taken at
  once; Remembered settings, a row with no value; the Remembered page (TAB_N64, a page of its own after the Controls page,
  before the hidden rows) with a row for each of n64_rules.h's Rows, the frame rate first under Pace, each from
  N64_ROW, which takes its range and step from n64_rules.h kSpec, and Copy Faithful and Reset to defaults; F7's last preset a
  hidden row, saved under its name's key, n64_classic_last;
- each row's value names, as many as its range has values;
- the page's values a plain array in Options (n64_rules.h's defaults), so the tests that cut Options out compile it as it
  is; ini_key's table of names gives each page row kSpec's key (its saturation is Colour saturation: RenoDX has Saturation);
- row_shown: Remembered settings with Remembered chosen; row_fixed: the Upscaler and the Anti-aliasing while the 3D pass
  draws in their place, the row with RX_VK_N64 set, a page row with nothing to do (n64_rules.h row_fixed); the Upscaler and
  the Anti-aliasing then say N64 Classic, and the Anti-aliasing's line says why;
- menu_tick: Remembered settings opens its page and Copy Faithful and Reset to defaults act on a press, before a row with no
  value opens the Controls page; back and the tab keys leave the page for Graphics, and the Motion page's lines are as they
  were; F7 turns the row between Off and the last preset, saves it, says so at the foot of the screen, and does nothing
  while RX_VK_N64 is set;
- the page is drawn under Graphics, its actions' guide says Apply and its Back; the tab strip, the sounds and the tab step
  take it as Graphics; every slot array has a slot for it;
- vk_n64.cpp: the mode from the row, RX_VK_N64 over it, Remembered's look from the page;
- the readme and the development guide name the row, the page, F7 and the switch.

The rules themselves (the presets, the page's ranges, the rows with nothing to do, F7) are run by tests/test_n64_rules.py.

    python -I -B tests/test_n64_row.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def fail(what):
    raise SystemExit("FAIL: " + what)


def check(cond, what):
    if not cond:
        fail(what)


def block(text, head):
    at = text.index(head)
    end = text.index("{", at) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[at:end]


def in_order(text, parts, what):
    at = [text.find(p) for p in parts]
    check(min(at) >= 0 and at == sorted(at), "%s: %s" % (what, [p for p, a in zip(parts, at) if a < 0] or at))


def spec():
    """n64_rules.h's Row names in order and kSpec's (lo, hi, step) for each"""
    rules = (VK / "n64_rules.h").read_text(encoding="utf-8")
    names = re.search(r"enum Row \{ (.*?), kRows \};", rules).group(1).split(", ")
    global defaults, keys
    table = re.search(r"constexpr RowSpec kSpec\[kRows\] = \{(.*?)\n\};", rules, re.S).group(1)
    entries = re.findall(r'\{"(\w+)", (-?\d+), (-?\d+), (\d+), (-?\d+)\}', table)
    check(len(entries) == len(names), "n64_rules.h: kSpec has not one entry for each Row")
    defaults = {n: int(e[4]) for n, e in zip(names, entries)}
    keys = {n: e[0] for n, e in zip(names, entries)}
    return names, {n: (int(e[1]), int(e[2]), int(e[3])) for n, e in zip(names, entries)}


def main():
    header = (VK / "vk_menu.h").read_text(encoding="utf-8")
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    n64 = (VK / "vk_n64.cpp").read_text(encoding="utf-8")
    names, ranges = spec()

    for need in ("int n64_classic = 0;", "int n64_last = 1;"):
        check(need in header, "vk_menu.h: %s is gone (Off by default, F7's Faithful)" % need)
    # (the page's values a plain array, so the tests that cut Options out compile it as it is: n64_rules.h's defaults)
    arr = re.search(r"int n64_rem\[(\d+)\] = \{([^}]*)\};", header)
    check(arr and int(arr.group(1)) == len(names) and [int(v) for v in arr.group(2).split(",")] == [defaults[n] for n in names],
          "vk_menu.h: Options's n64_rem is not n64_rules.h kSpec's defaults, one for each Row")

    # ---- the rows ----
    check("TAB_N64 = TAB_PAGE + 1," in menu and "TAB_HIDDEN = TAB_N64 + 1" in menu,
          "TAB_N64 is not a page of its own after the Controls page and before the hidden rows")
    in_order(menu, ['MENU_HEADING(TAB_GRAPHICS, "Anti-aliasing"),', 'MENU_HEADING(TAB_GRAPHICS, "N64 Classic"),',
                    '{TAB_GRAPHICS, "N64 Classic", &opts.n64_classic, 0, n64_rules::kPresets - 1, 1, tx_n64,',
                    '{TAB_GRAPHICS, "Remembered settings", nullptr, 0, 0, 0, nullptr,',
                    'MENU_HEADING(TAB_GRAPHICS, "Frame generation"),'],
             "the N64 Classic row and Remembered settings are not after the Anti-aliasing on the Graphics tab")
    row = menu[menu.index('{TAB_GRAPHICS, "N64 Classic", &opts.n64_classic'):]
    row = row[:row.index("},") + 2]
    check("hn_n64, false, true}," in row and "F7" in row and "Changes at once" in row,
          "the N64 Classic row: its help says F7 and at once, its hint is hn_n64, it takes no restart")
    macro = menu[menu.index("#define N64_ROW(row, title, text, help)"):]
    macro = macro[:macro.index("false, true}") + 12]
    for part in ("{TAB_N64, title, &opts.n64_rem[n64_rules::row],", "n64_rules::kSpec[n64_rules::row].lo",
                 "n64_rules::kSpec[n64_rules::row].hi", "n64_rules::kSpec[n64_rules::row].step", "text, help, nullptr, false, true}"):
        check(part in macro, "N64_ROW no longer takes %s" % part)
    page = re.findall(r"N64_ROW\((\w+), \"([^\"]+)\", (\w+),", menu)
    check([p[0] for p in page] == names, "the Remembered page's rows are not n64_rules.h's Rows, in order: %s" % [p[0] for p in page])
    in_order(menu, ['MENU_HEADING(TAB_N64, "Pace"),', 'N64_ROW(FPS, "Frame rate", tx_n64_fps,', 'MENU_HEADING(TAB_N64, "The 3D"),'],
             "the Remembered page does not open with its Pace, the frame rate")
    for need in ('{TAB_N64, "Copy Faithful", nullptr, 0, 0, 0, nullptr,', '{TAB_N64, "Reset to defaults", nullptr, 0, 0, 0, nullptr,',
                 '{TAB_HIDDEN, "N64 Classic last", &opts.n64_last, n64_rules::FAITHFUL, n64_rules::REMEMBERED, 1, nullptr, nullptr},'):
        check(need in menu, "the rows: %s is gone" % need)
    # (each value's name: as many as its range has values)
    for row_name, title, text in page:
        lo, hi, step = ranges[row_name]
        if text in ("tx_percent", "tx_onoff"):
            continue
        fn = block(menu, "const char* %s(int v) {" % text)
        if text == "tx_n64_blur":
            check('if (v <= 0) return "Off";' in fn and "v * n64_rules::kBlurStep" in fn, "Texture blur's names are not Off, then +0.5 a step")
            continue
        count = len(re.findall(r'"[^"]*"', fn.split("};")[0]))
        check(count == (hi - lo) // step + 1 and "std::clamp(v, 0, %d)" % hi in fn,
              "%s has %d names for %d values" % (text, count, (hi - lo) // step + 1))
    check(ranges["TV"] == (0, 1, 1) and ranges["SCANLINES"][2] == 5 and ranges["SATURATION"] == (50, 150, 5),
          "a page row named by tx_onoff or tx_percent no longer has the range those names suit")

    # ---- the saved keys, shown, fixed ----
    key = block(menu, "const char* ini_key(const Row& r) {")
    kept = dict(re.findall(r'\{"([^"]+)", "([^"]+)"\}', key[:key.index("for (const auto& k : kept)")]))
    for row_name, title, _ in page:
        check(kept.get(title) == keys[row_name], "ini_key: the page's %s is not saved under %s" % (title, keys[row_name]))
    check(sum(1 for t in kept if t in [p[1] for p in page]) == len(page) and "Saturation" not in [p[1] for p in page],
          "ini_key: a page row's name is another row's (RenoDX has Saturation)")
    check("return value && value >= first && value < first + n64_rules::kRows ? (int)(value - first) : -1;" in block(menu, "int n64_rem_row(const int* value) {"),
          "n64_rem_row is not the place of a value among opts.n64_rem's")
    shown = block(menu, "bool row_shown(int i) {")
    check("(!is_n64_page_row(rows[i]) || n64_preset() == n64_rules::REMEMBERED) &&" in shown,
          "row_shown: Remembered settings is not shown with Remembered alone")
    fixed = block(menu, "bool row_fixed(const int* value) {")
    for need in ("((value == &opts.dlss || value == &opts.aa) && n64_in_front() != n64_rules::OFF)",
                 "(value == &opts.n64_classic && n64_env_set())",
                 "(n64_rem_row(value) >= 0 && n64_rules::row_fixed(n64_rules::rows_of(opts.n64_rem), n64_rem_row(value)))"):
        check(need in fixed, "row_fixed: %s is gone" % need)
    for fn in ("const char* tx_upscaler(int) {", "const char* tx_aa(int v) {"):
        body = block(menu, fn)
        check(body.split("{", 1)[1].lstrip().startswith('if (n64_in_front() != n64_rules::OFF) return "N64 Classic";'),
              "%s does not say N64 Classic while its 3D pass draws" % fn)
    hint = block(menu, "const char* hn_aa(int v, int variant) {")
    check("variant = n64_in_front() != n64_rules::OFF ? 5 :" in hint and "case 5: return n64;" in hint,
          "the Anti-aliasing's line does not say N64 Classic smooths the edges")
    check("return t[v >= 0 && v < n64_rules::kPresets ? v : 0];" in block(menu, "const char* hn_n64(int v, int variant) {") and
          "return n64_rules::name(n64_env_set() ? n64_preset() : v);" in block(menu, "const char* tx_n64(int v) {"),
          "the N64 Classic row's text or line is not its value's, RX_VK_N64's over it")
    act = block(menu, "void n64_act(int action) {")
    check("const n64_rules::Rows to = action == 1 ? n64_rules::kFaithful : n64_rules::defaults();" in act and
          "std::copy(std::begin(to.v), std::end(to.v), opts.n64_rem);" in act and "save();" in act,
          "Copy Faithful and Reset to defaults do not set the page from Faithful or the defaults, and save")

    # ---- the keys ----
    tick = block(menu, "void menu_tick() {")
    in_order(tick, ["else if (press[7] && is_motion_row(r)) cur_tab = TAB_MOTION",
                    "else if (press[7] && is_n64_page_row(r)) cur_tab = TAB_N64, tab_selected[TAB_N64] = 0, press[7] = false, changed = true;",
                    "else if (press[7] && n64_action(r)) n64_act(n64_action(r)), changed = true;",   # ((11-22) its press the sound's)
                    "else if (press[7] && !r.value && can_bind()) page = 1"],
             "menu_tick: Remembered settings and the page's actions are not taken before a row with no value opens the Controls page")
    for need in ("if (press[5] && cur_tab == TAB_N64) cur_tab = TAB_GRAPHICS, press[5] = false, changed = true;",
                 "else if (press[5] && cur_tab == TAB_N64) cur_tab = TAB_GRAPHICS, press[5] = false, changed = true;",
                 "if ((tab_left || tab_right) && cur_tab == TAB_N64) cur_tab = TAB_GRAPHICS;",
                 "if (press[5] && cur_tab == TAB_MOTION) cur_tab = TAB_CONTROLS, press[5] = false, changed = true;",
                 "if ((tab_left || tab_right) && cur_tab == TAB_MOTION) cur_tab = TAB_CONTROLS;"):
        check(need in tick, "menu_tick: %s is gone" % need)
    f7 = tick[tick.index("static bool f7_held = false;"):tick.index("f7_held = f7_down;")]
    in_order(f7, ["opts.n64_last = opts.n64_classic;", "const bool f7_down = mine && (GetAsyncKeyState(VK_F7) & 0x8000) != 0;",
                  "if (f7_down && !f7_held && !n64_env_set()) {", "toggle.last = opts.n64_last;",
                  "opts.n64_classic = toggle.pressed(opts.n64_classic);", "opts.n64_last = toggle.last;", "save();",
                  'snprintf(notice_text, sizeof notice_text, "N64 Classic: %s", n64_rules::name(opts.n64_classic));'],
             "F7: the last preset kept, a press turns the row (not with RX_VK_N64), saves it and says so")

    # ---- the page drawn, its slots ----
    check("draw_tabs(c, cur_tab == TAB_MOTION ? TAB_CONTROLS : cur_tab == TAB_N64 ? TAB_GRAPHICS : cur_tab, embed_open, true);" in menu,
          "the Remembered page is not drawn under Graphics")
    check('if (n64_action(selr)) prompt_list[0] = {ui::kConfirm, "Apply"};' in menu and
          'if (cur_tab == TAB_N64) prompt_list[1] = {ui::kBack, "Back"}, prompts_n = 2;' in menu,
          "the Remembered page's guides do not say Apply and Back")
    check("s.tab = motion ? (int)TAB_CONTROLS : cur_tab == TAB_N64 ? (int)TAB_GRAPHICS : cur_tab;" in menu and
          "cur_tab == TAB_MOTION ? TAB_CONTROLS : cur_tab == TAB_N64 ? TAB_GRAPHICS : cur_tab;" in block(menu, "void tab_move(int dir) {"),
          "the sounds or the tab step do not take the Remembered page as Graphics")
    for arr in ("int tab_selected[TAB_N64 + 1]", "float scroll_at[TAB_N64 + 1];", "int wheel_rows[TAB_N64 + 1];",
                "int scrolled_to[TAB_N64 + 1] = {-1, -1, -1, -1, -1, -1, -1, -1, -1};", "float scroll_want[TAB_N64 + 1];",
                'static_assert(TAB_N64 + 1 == 9,'):
        check(arr in menu, "a slot array has no slot for the Remembered page: %s" % arr)

    # ---- vk_n64.cpp, the readme, the guide ----
    # ((step 8) the look is the preset shown, which follows the row through the TV's switch, and is the row's before a present)
    for need in ("int n64_preset() { return n64_rules::chosen(opts.n64_classic, env_n64()); }", "bool n64_env_set() { return env_n64() >= 0; }",
                 "n64_rules::look_of(n64_shown(), n64_rules::rows_of(opts.n64_rem))", "return s >= 0 ? s : n64_preset();",
                 '#include "vk_menu.h"'):
        check(need in n64, "vk_n64.cpp: %s is gone" % need)
    readme = (ROOT / "readme.md").read_text(encoding="utf-8")
    entry = readme[readme.index("| N64 Classic |"):]
    entry = entry[:entry.index("\n")]
    for need in ("Off, Faithful, Remembered", "**F7**", "**Remembered settings**", "at 20 frames a second", "Frame rate (Frame rate cap",
                 "Colour saturation", "Copy Faithful",
                 "Reset to defaults", "`RX_VK_N64=0`"):
        check(need in entry, "readme.md: the N64 Classic row does not say %s" % need)
    check("Upscaling, Anti-aliasing, N64 Classic, Frame generation" in readme, "readme.md: the Graphics tab's groups leave N64 Classic out")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("over the Insert menu's N64 Classic row and its Remembered page" in docs, "docs/development.md: RX_VK_N64 is not said to go over the row")
    print("PASS: N64 Classic's row, the Remembered page, F7, and the rows it stands in front of")


if __name__ == "__main__":
    main()
