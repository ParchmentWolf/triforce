"""Save files (host/save_files.h, host/save_files.c, host/hos_main.c, gpu/vk/save_file_rows.h, gpu/vk/vk_menu.cpp; no game).

As the Nintendo 64 game had them: the title asks which file to play, and the game's saves and autosaves live in that
file. A file is a folder the game saves in; the game reads its saves once, at its start, so another file is another
start. On unless HOS_SAVE_FILES=0 (11-23). Compiled and run here:

- tests/save_files_test.c: host/save_files.h alone. triforce_files.txt's three lines and what is not taken from it,
  written and read back; the files' folders; the start that follows a choice; a file's card (a map's name as words,
  hearts from the game's count of life, triforce_card.txt read and written);
- tests/save_files_host_test.c: host/save_files.c's own text against a stand-in menu, a stand-in for the files'
  folders and a game folder of the test's, four starts. Without the switch the game's own folder, and nothing read,
  written or asked; with it file 1 without a triforce_files.txt, the files named to the menu once, whole; a file chosen
  kept as the next start's and the menu told; the next start on that file's folder, saying that it follows a choice;
  and a later start on the same file, with the player's names, asking again;
- tests/save_file_rows_test.cpp: gpu/vk/save_file_rows.h alone. Nothing shown or asked until the list is whole; this
  run's file played at once and another asked of the host once; the host's word taken once; the choice under the keys.

Read in the sources: the folder is chosen at the start, before the game's memory is made, and not when --user named
one; the files are named at the game's present; the host and the menu have the same ids, the same room; the title's
list has Save Select under Mods, which alone opens the file select there (nothing opens by itself); the menu restarts
the game on the host's word as Restart now does, has the row and the page; and no save is opened by the host.

    python -I -B tests/test_save_files.py [--cc gcc] [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc", "--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def run(command, says=None, **more):
    """A compiler or a fixture run; a fixture must say `says`"""
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0
    result = subprocess.run(command, creationflags=flags, capture_output=True, text=True, encoding="utf-8", errors="replace", **more)
    check(result.returncode == 0 and (says is None or says in result.stdout),
          "%s:\n%s%s" % (" ".join(str(c) for c in command[:1] + command[-2:]), result.stdout, result.stderr))
    return result.stdout


def number_of(text, name):
    return int(re.search(r"\b%s = (\d+)\b" % name, text).group(1))


def check_sources():
    read = lambda *parts: ROOT.joinpath(*parts).read_text(encoding="utf-8")
    host, own, header, api = read("host", "hos_main.c"), read("host", "save_files.c"), read("host", "save_files.h"), read("gpu", "vk", "vk_api.h")
    native, rows, menu, replay = read("host", "nvn_native.c"), read("gpu", "vk", "save_file_rows.h"), read("gpu", "vk", "vk_menu.cpp"), read("gpu", "vk", "vk_replay.cpp")
    # the folder: chosen at the start, in a game folder, before the game's memory is made; a folder named with --user stays
    check("const int user_given = hos_user_dir != NULL;   /* (--user) */" in host
          and "if (!user_given) hos_user_dir = hos_save_files_start(dir, hos_user_dir);" in host and host.count("hos_save_files_start(") == 1,
          "host/hos_main.c does not take the file's folder at the start, or takes it over --user")
    check(host.index("const int user_given = hos_user_dir != NULL;") < host.index("hos_save_files_start(dir, hos_user_dir)")
          < host.index('if (!hos_user_dir) hos_user_dir = "user";') < host.index("if (!reserve_guest())"),
          "the file's folder is not chosen before the game's memory is made")
    start = block(own, "const char *hos_save_files_start(")
    check(start.index("if (!hos_save_files_on()) return base_user;") < start.index("files_read();"), "triforce_files.txt is read with the save files off")
    check("on = !(e && e[0] == '0' && !e[1]);" in block(own, "int hos_save_files_on("), "the save files are not on unless HOS_SAVE_FILES=0")
    frame = block(own, "void hos_save_files_frame(")
    check(frame.index("if (!started) return;") < frame.index("rx_option("), "the menu is asked with the save files off")
    check("files.current = was, files.chosen = 0;" in frame, "a run does not go on with the file it started on")
    # no save is opened: a file's folder is listed, its files are not read
    # the game saves: a slot's file opened to be written tells the card which slot, from the game's file call and nowhere else
    fs = read("host", "nn_fs.c")
    opened = block(fs, "HLE(_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci) {")
    check("if (want_write) { void hos_save_card_wrote(const char *guest_path); hos_save_card_wrote(g); }" in opened
          and opened.index("if (want_write && !writable)") < opened.index("hos_save_card_wrote(g)") and fs.count("hos_save_card_wrote(g)") == 1,
          "host/nn_fs.c does not tell the slot the game saves in")
    check("const int slot = started ? save_card_slot_of(guest_path) : -1;" in block(own, "void hos_save_card_wrote("), "a slot is noted with the save files off")
    # (a slot's caption.sav is named for the menu, which reads the save's picture out of it; triforce_progress.txt is host/achievements.c's)
    for word in ("recomp_", "A64_PTR", "GP(", "a64_lookup", "CreateFileA", "ReadFile", "progress.sav"):
        check(word not in own, "host/save_files.c reaches into the game or a save: " + word)
    check(own.count("fopen(") == 4 and own.count("fread(") == 2 and own.count("files_path") >= 4 and own.count("card_path(") == 3,
          "host/save_files.c opens a file that is neither triforce_files.txt nor a file's triforce_card.txt")
    # a file's card: told from the running game at Link's update, not read out of a save; the switch first, a save loaded, nothing written
    update = block(host, "static void oot_update_player_cheats(")
    check("oot_save_card_tick(c, now);" in update and host.count("oot_save_card_tick(") == 2 and host.count("hos_save_card_note(") == 1,
          "host/hos_main.c does not tell a file's card at Link's update, from one place")
    card = block(host, "static void oot_save_card_tick(")
    check("if (!hos_save_files_on() || now < next) return;" in card and card.index("hos_save_files_on()") < card.index("oot_pouch_count(")
          and "if (oot_pouch_count(c, oot_item_names[0]) < 0) return;" in card and card.index("oot_pouch_count(") < card.index("hos_save_card_note("),
          "the game is asked for a file's card before the switch is, or while no save is loaded")
    life = block(host, "static int oot_max_life(")
    for word in ("recomp_store", "oot_gd_set", "oot_item_give", "oot_flag_set", "A64_PTR"):
        check(word not in card and word not in life, "telling a file's card writes into the game: " + word)
    items = dict(re.findall(r'OOT_ITEM\("[^"]+", "([^"]+)", ([01])\)', read("gpu", "vk", "oot_cheat_items.h")))
    held = re.findall(r'"((?:Item|Weapon|Armor)_\w+)"', card)
    check(len(held) == number_of(header, "SAVE_CARD_STONES") + number_of(header, "SAVE_CARD_MEDALS") == 9 and all(name in items for name in held)
          and [name.split("_")[1] for name in held] == ["Stone"] * 3 + ["Medal"] * 6,
          "the card's stones and medallions are not nine items gpu/vk/oot_cheat_items.h names, the stones first: %s" % held)
    check(number_of(header, "SAVE_CARD_STONES") == number_of(rows, "kStones") and number_of(header, "SAVE_CARD_MEDALS") == number_of(rows, "kMedals")
          and number_of(header, "SAVE_CARD_HEARTS") == number_of(rows, "kHearts") and number_of(header, "SAVE_CARD_PLACE") + 1 == number_of(rows, "kPlace"),
          "the host's card and the menu's have not the same room")
    load = block(menu, "void files_pictures_load(")
    check("save_file_rows::jpeg_in(" in load and "save_file_rows::caption_time(" in load and "mods::decode_image(" in load and load.index("if (p.state) continue;") < load.index("fopen(")
          and "if (from >= 0 && !t.after(latest)) continue;" in load and "if (known >= 0 && slot != known) continue;" in load
          and "fwrite" not in load and '"rb"' in load, "the menu does not read a save's picture once, from the file the host named, without writing")
    # named at the game's present, from one place
    present = block(native, "NV(nvnQueuePresentTexture) {")
    check("hos_save_files_frame();" in present and native.count("hos_save_files_frame();") == 1, "the save files are not named to the menu at the game's present")
    # the host and the menu: the same ids, bits and room
    enum = block(api, "enum { HOS_OPT_FILES_TEXT")
    names = re.findall(r"\bHOS_OPT_\w+", enum)
    check("HOS_OPT_FILES_TEXT = 180" in enum and names == ["HOS_OPT_FILES_TEXT", "HOS_OPT_FILES_ADD", "HOS_OPT_FILES_COUNT", "HOS_OPT_FILES_ASK", "HOS_OPT_FILES_SAID"],
          "the option ids are not 180 to 184")
    others = re.sub(r"enum \{ HOS_OPT_FILES_TEXT[^}]*\}", "", api)
    for value in range(180, 185):
        check(not re.search(r"= %d\b" % value, others), "another option has the id %d" % value)
    check("enum { HOS_FILE_SAVED = 1, HOS_FILE_CURRENT = 2, HOS_FILES_CHOSEN = 256 };" in api and "constexpr int kSaved = 1, kCurrent = 2;" in rows
          and "constexpr int kChosen = 256;" in rows, "the files' bits are not the same on both sides")
    number = lambda text, name: int(re.search(r"\b%s = (\d+)\b" % name, text).group(1))
    check(number(header, "SAVE_FILES") == number(rows, "kSlots") and number(header, "SAVE_FILE_NAME") + 1 == number(rows, "kName"),
          "the host's files and the menu's have not the same room")
    # the menu: told by the host, asks at the title once, restarts on the host's word, the row and the page
    check("if (id == HOS_OPT_FILES_ASK) return menu_take_file_ask();" in replay and "int menu_take_file_ask() { return save_files.take_ask(); }" in menu,
          "the renderer does not hand the file chosen to the host")
    setter = block(menu, "void menu_option_set(")
    for line in ("if (id == HOS_OPT_FILES_TEXT) return save_files.text(value);", "if (id == HOS_OPT_FILES_ADD) return save_files.add(value);",
                 "save_files.done(value);", "save_files.said(value);"):
        check(line in setter, "the menu does not take the host's files: " + line)
    tick = block(menu, "void menu_tick() {")
    # the title: no page opens by itself; Save Select, an entry under Mods on the title's list, opens the file select
    check("files_offered" not in menu and tick.count("files_open(true)") == 2, "the file select opens by itself, or not from Save Select alone")
    shown = block(menu, "bool files_row_shown(")
    check("save_files.shown() > 0" in shown and "HOS_MODS_LIST_TITLE" in shown, "Save Select shows off the title, or before the host named the files")
    # (0.7.0: the title's entries are the game's own part, and the System list has Quit under Mods. Save Select is that second
    # entry on the title: the same part a pitch lower, mods_row_sel 1, the host's words 3 and 4)
    entry = block(menu, "void draw_title_files(")
    check(entry.index("std::swap(title_anim, files_title_anim);") < entry.index('title_label = "Save Select", title_entry = 1;') < entry.index("draw_title_mods(c, sel, cx, cy, k, pitch);")
          < entry.index('title_label = "Mods", title_entry = 0;') and entry.count("std::swap(title_anim, files_title_anim);") == 2,
          "Save Select is not the title's own entry with its own label and animation, or leaves Mods' changed")
    part = block(menu, "void draw_title_mods(ui::Ctx& c, bool sel, float cx, float cy, float k, float pitch) {")
    check("const char* const label = title_label;" in part and "menu_hit::kButton, title_entry);" in part
          and part.index("if (title_entry) return;") < part.index("mods_entry_px[0] ="), "Save Select has Mods' label, hit or place")
    row = block(menu, "void draw_mods_row(ui::Ctx& c, bool sel) {")
    check("if (files_row_shown()) draw_title_files(c, sel && mods_row_sel == 1, cx, cy - pitch, k, pitch), sel = sel && mods_row_sel == 0;" in row
          and row.index("draw_title_files(") < row.index("draw_title_mods(c, sel, cx, cy, k, pitch);"),
          "Save Select is not drawn a pitch under the title's Mods, the cursor on one of the two")
    cursor = tick[tick.index("} else if (open_now.load() && page == kModsRowPage) {"):tick.index("} else if (open_now.load() && page == kModsPage) {")]
    a_files, down_files = "} else if (press[7] && files_here && mods_row_sel == 1) {", "} else if (press[2] && files_here && mods_row_sel == 0) {"
    check("const bool files_here = files_row_shown();" in cursor and "if (!quit_here && !files_here) mods_row_sel = 0;" in cursor
          and cursor.index(a_files) < cursor.index(down_files) < cursor.index("} else if (press[7]) {   // (A: Mods opens; on Quit its dialog)")
          and cursor.index(down_files) < cursor.index("} else if (press[1] && mods_row_sel == 1) {") < cursor.index("} else if (press[1] || press[5]"),
          "the cursor does not move between Mods and Save Select, or A on Save Select opens Mods or Quit's dialog")
    # (the Down that brought the cursor onto Mods is not also the entries' own: 0.7.0's entered_by_down)
    check(tick.index("if (entered_by_down) press[2] = false;") < tick.index("} else if (open_now.load() && page == kModsRowPage) {"),
          "the Down that comes onto Mods goes on to Save Select at once")
    enter = tick[tick.index("bool entered_by_down = false;"):tick.index("if (!open_now.load() || page != kModsPage) {")]
    check(enter.index("if (enter == 3 && !mods_title_list()) quit_open();") < enter.index("if (enter == 3 && files_row_shown()) files_open(true);"),
          "a click on Save Select does not open the file select, or opens Quit's dialog on the title")
    mouse = read("host", "oot_menu.c")
    list_tick = block(mouse, "static void mods_list_tick(uint64_t screen, int title, ModsCall *call) {")
    check(list_tick.index("quit_entry = title ? (Rect){0, 0, 0, 0} :") < list_tick.index("if (title && hos_save_files_on()) {")
          < list_tick.index("quit_entry = (Rect){mx - 550, my - pitch / 2, mx + 550, my + pitch / 2};")
          and "my = (r.y0 + r.y1) / 2 - 2 * pitch;" in list_tick and "files_entry" not in mouse,
          "the host has no box for Save Select under the title's Mods, or has one with the save files off")
    check("(page == kFilesPage && files_at_title)" in block(menu, "int menu_mods_selected("), "the game is given input while the title's file select is open")
    word = tick[tick.index("if (const int said = save_files.take_said()) {"):]
    word = word[:word.index("if (!open_now.load() || page != kModsPage)")]
    check("if (said == save_file_rows::kRestart) {" in word and word.index("save();") < word.index("PostMessageA(window, WM_APP + 9, 0, 0);")
          and "pipeline_cache_save(true);" in word and "else files_failed = true;" in word,
          "the game is not restarted on the host's word as Restart now restarts it")
    page = tick[tick.index("} else if (open_now.load() && page == kFilesPage) {"):tick.index("} else if (open_now.load() && page == kAchPage) {")]
    check("if (files_wait >= 0) {}" in page and page.index("if (files_wait >= 0) {}") < page.index("else if (press[7]) {")
          and "if (save_files.choose(files_choice)) leave(true);" in page and "else files_wait = files_choice, changed = true;" in page,
          "a file can be chosen again while the host is asked, or this run's file is not played at once")
    table = menu[menu.index("Row rows[] = {"):]
    check(table.index('"Bug capture (F8)"') < table.index('{TAB_SYSTEM, "Save files", nullptr, 0, 0, 0, nullptr,') < table.index('MENU_HEADING(TAB_SYSTEM, "Mod cheats")')
          and 'constexpr char kFilesRow[] = "Save files";' in menu, "the Save files row is not on the System tab after Bug capture (F8)")
    check("(strcmp(rows[i].name, kFilesRow) || rows[i].tab != TAB_SYSTEM || save_files.shown() > 0) &&" in block(menu, "bool row_shown("),
          "the Save files row shows before the host named the files")
    press = tick[tick.index("else if (press[7] && is_files_row(r)) files_open(false)"):]
    check(press.index("is_files_row(r)") < press.index("else if (press[7] && !r.value && can_bind()) page = 1"),
          "the Save files row opens the Controls page: it is asked after the rows without a value")
    check("else if (page == kFilesPage) draw_files(k);" in block(menu, "void draw_menu(ui::Ctx& c, bool perf_under) {"), "the file select is not drawn")
    pages = [number(menu, name) for name in ("kFilesPage", "kAchPage", "kModsPage", "kModsRowPage")]
    check(len(set(pages + [0, 1, 3, 4, 5, 6])) == len(pages) + 6, "kFilesPage is another page's number")
    return api, own


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="cc")
    p.add_argument("--cxx", default="c++")
    a = p.parse_args()
    api, own = check_sources()
    with tempfile.TemporaryDirectory(prefix="triforce-save-files-") as tmp:
        tmp = Path(tmp)
        warnings = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
        exe = tmp / "form.exe"
        run([a.cc] + warnings + ["-I" + str(ROOT / "host"), str(ROOT / "tests" / "save_files_test.c"), "-o", str(exe)])
        run([str(exe)], says="PASS")
        exe = tmp / "rows.exe"
        run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu" / "vk"), str(ROOT / "tests" / "save_file_rows_test.cpp"),
             "-o", str(exe)])
        run([str(exe)], says="PASS")
        # the host's side: host/save_files.c from after its includes on, with the menu's ids from vk_api.h
        marker = '#include "save_files.h"\n'
        check(own.count(marker) == 1, "host/save_files.c no longer includes save_files.h last")
        (tmp / "save_files_actual.inc").write_text(own[own.index(marker) + len(marker):], encoding="utf-8")
        (tmp / "save_files_constants.inc").write_text(
            "".join(block(api, start) + ";\n" for start in ("enum { HOS_OPT_FILES_TEXT = 180", "enum { HOS_FILE_SAVED = 1")), encoding="utf-8")
        exe = tmp / "host.exe"
        run([a.cc] + warnings + ["-Wno-unused-function", "-I" + str(ROOT / "host"), "-I" + str(tmp), str(ROOT / "tests" / "save_files_host_test.c"),
                                 "-o", str(exe)])
        game = tmp / "game folder"
        game.mkdir()
        kept = game / "triforce_files.txt"
        env = {k: v for k, v in os.environ.items() if k != "HOS_SAVE_FILES"}
        # ((Triforce) 11-23: on by default: off only with HOS_SAVE_FILES=0; the first start runs with it not set at all)
        run([str(exe), str(game), "off"], says="PASS", cwd=str(tmp), env=dict(env, HOS_SAVE_FILES="0"))
        check(not kept.exists(), "a file was written with the save files off")
        on = dict(env, HOS_SAVE_FILES="1")
        run([str(exe), str(game), "first"], says="PASS", cwd=str(tmp), env=env)
        run([str(exe), str(game), "second"], says="PASS", cwd=str(tmp), env=on)
        check(kept.read_text(encoding="utf-8").splitlines()[1:] == ["current=2", "1=File 1", "2=File 2", "3=File 3"], "triforce_files.txt after a choice was taken: %r" % kept.read_text(encoding="utf-8"))
        kept.write_bytes(b"current=2\r\nchosen=1000\r\n1=Spanky\r\n2=Bukwheat\r\n")   # (the player's names, and a choice long past)
        # (file 2's card, as the host kept it in the file's folder, which it names with Windows' separator)
        if os.name == "nt":
            (game / "user-2").mkdir()
        with open(str(game) + "\\user-2\\triforce_card.txt", "wb") as f:
            f.write(b"# a note\r\nplace=Kokiri Forest\r\nitems=1c9\r\nhearts=7\r\n")
        run([str(exe), str(game), "third"], says="PASS", cwd=str(tmp), env=on)
        check(sorted(f.name for f in game.iterdir() if f.name != "user-2") == ["triforce_files.txt"], "the game folder has other files now: no folder is made for a file here")
    print("PASS: save files: triforce_files.txt, the files' folders, the host's naming and a file chosen for the next start, "
          "the menu's list and its file select, and off unless asked for")


if __name__ == "__main__":
    main()
