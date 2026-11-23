"""Achievements (host/achievements.h, host/achievements.c, host/hos_main.c, gpu/vk/achievement_rows.h, gpu/vk/vk_menu.cpp;
authored lists, no game).

Things done in the game that are marked as earned, once, with a notice on the screen and a sound, and a page of the
options that lists them all with their icons: on unless HOS_ACHIEVEMENTS=0. Compiled and run here:

- tests/achievements_test.c: host/achievements.h alone. The built-in list is read whole; the form of a list and each
  thing that leaves an achievement out (no condition, a line that is none of the form's, a name that is empty, too long
  or another's, a count that is none, an icon that is none, too many conditions, more than there is room for); when one
  is earned (every condition, an item's count, a flag set and in the save data), that it stays earned and is not asked
  about again; and the file of the earned ones, written and read back, with the lines of achievements no list has now
  kept as they were;
- tests/achievements_host_test.c: host/achievements.c's own text against a stand-in save data, menu and game folder.
  Without the switch nothing is asked, read, written, said or named; with it a player's own achievements.txt is read
  after the built-in list, the list is named to the menu once, whole, when the renderer answers, six earned at once are
  written at once and shown one at a time with the sound and never before the menu has the list, and at the next start
  (a second run on the same folder) they are neither said nor shown again;
- tests/achievement_rows_test.cpp: gpu/vk/achievement_rows.h alone. Nothing shown until the list is whole, then as
  named; one earned, its day and its notice once; names and lines cut to their room; the page's choice and pages under
  the keys, the wheel and a click; how a notice comes in and goes.

Read in the sources: the built-in list asks only for items gpu/vk/oot_cheat_items.h already names, and for no flag, so
that no other name of the game's comes into the repository; the save data is asked at Link's update, once a second,
not before the switch is looked at, only while a save is loaded, and through nothing that writes; the host and the menu
have the same icons, the same room and the same option ids; the menu has the row, the page and the notice.

    python -I -B tests/test_achievements.py [--cc gcc] [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc", "--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]

OWN_LIST = "[Mine]\nabout: A flag of the player's own choosing.\nicon: gem blue\nflag My_Flag\n[Not one]\n[Nor this]\nitem\n"


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


def check_sources():
    read = lambda *parts: ROOT.joinpath(*parts).read_text(encoding="utf-8")
    host, own, header, api = read("host", "hos_main.c"), read("host", "achievements.c"), read("host", "achievements.h"), read("gpu", "vk", "vk_api.h")
    native, rows, menu, replay = read("host", "nvn_native.c"), read("gpu", "vk", "achievement_rows.h"), read("gpu", "vk", "vk_menu.cpp"), read("gpu", "vk", "vk_replay.cpp")
    # at Link's update, after the other tools' reads; the switch before anything is asked of the game; only with a save loaded
    update = block(host, "static void oot_update_player_cheats(")
    check("oot_achievements_tick(c, now);" in update and update.index("oot_link_tick(c, actor, now);") < update.index("oot_achievements_tick(c, now);"),
          "host/hos_main.c does not ask about the achievements at Link's update")
    check(host.count("oot_achievements_tick(") == 2 and host.count("hos_achievements_check(") == 1, "the achievements are asked about from somewhere else too")
    tick = block(host, "static void oot_achievements_tick(")
    check("if (!hos_achievements_on() || now < next) return;" in tick and "next = now + 1000000000LL;" in tick
          and tick.index("hos_achievements_on()") < tick.index("oot_pouch_count(")
          and "if (oot_pouch_count(c, oot_item_names[0]) < 0) return;" in tick
          and tick.index("oot_pouch_count(") < tick.index("hos_achievements_check("),
          "the game is asked before the switch is, more than once a second, or while no save is loaded")
    # reading only: the probe and host/achievements.c write nothing of the game's
    probe = block(host, "static int oot_achievement_probe(")
    for word in ("recomp_store", "oot_gd_set", "oot_item_give", "oot_flag_set", "A64_PTR"):
        check(word not in probe and word not in tick, "asking about an achievement writes into the game: " + word)
    for word in ("recomp_", "A64_PTR", "GP(", "a64_lookup"):
        check(word not in own, "host/achievements.c reaches into the game: " + word)
    check("on = !(e && e[0] == '0' && !e[1]);" in block(own, "int hos_achievements_on("), "the achievements are not on unless HOS_ACHIEVEMENTS=0")
    for name in ("void hos_achievements_frame(", "void hos_achievements_check("):   # (the switch before the lock, the lists and the menu)
        body = block(own, name)
        check("hos_achievements_on()" in body and body.index("hos_achievements_on()") < body.index("lock();") < body.index("lists_read();")
              and body.count("unlock();") == 1 and "return;" not in body[body.index("lock();"):],
              "%s the lists are read before the switch is looked at, or the lock is not let go" % name)
    # the list named at the game's present, after the mods' cheats, from one place
    present = block(native, "NV(nvnQueuePresentTexture) {")
    check(present.index("hos_mod_cheats_frame();") < present.index("hos_achievements_frame();") and native.count("hos_achievements_frame();") == 1,
          "the achievements are not named to the menu at the game's present")
    # the host and the menu: the same ids, the same room, the same icons in the same order
    enum = block(api, "enum { HOS_OPT_ACH_TEXT")
    names = re.findall(r"\bHOS_OPT_\w+", enum)
    check("HOS_OPT_ACH_TEXT = 165" in enum and names == ["HOS_OPT_ACH_TEXT", "HOS_OPT_ACH_ADD", "HOS_OPT_ACH_COUNT", "HOS_OPT_ACH_EARNED", "HOS_OPT_ACH_ASK"],
          "the option ids are not 165 to 169")
    others = re.sub(r"enum \{ HOS_OPT_ACH_TEXT[^}]*\}", "", api)
    for value in range(165, 170):
        check(not re.search(r"= %d\b" % value, others), "another option has the id %d" % value)
    check("enum { HOS_ACH_EARNED = 256 };" in api and "constexpr int kEarned = 256;" in rows, "the earned bit is not the same on both sides")
    number = lambda text, name: int(re.search(r"\b%s = (\d+)\b" % name, text).group(1))
    check(number(header, "ACH_MAX") == number(rows, "kSlots") and number(header, "ACH_NAME") + 1 == number(rows, "kName")
          and number(header, "ACH_ABOUT") + 1 == number(rows, "kAbout"), "the host's list and the menu's have not the same room")
    words = lambda text, name: re.findall(r'"(\w+)"', re.search(r"#define %s (.*)" % name, text).group(1))
    shapes = re.search(r"enum Shape \{ ([^}]*) \}", rows).group(1).split(", ")
    tones = re.search(r"enum Tone \{ ([^}]*) \}", rows).group(1).split(", ")
    check(["k" + w.capitalize() for w in words(header, "ACH_SHAPES")] + ["kShapes"] == shapes, "the icons' shapes differ: %s" % shapes)
    check(["k" + w.capitalize() for w in words(header, "ACH_TONES")] + ["kTones"] == tones, "the icons' tones differ: %s" % tones)
    check(len(shapes) - 1 <= 16 and len(tones) - 1 <= 16, "an icon no longer fits its eight bits")
    icon = block(menu, "void ach_icon(")
    for shape in shapes[1:-1]:   # (kStar is the default)
        check("case ar::%s" % shape in icon, "the menu does not draw the shape %s" % shape)
    check(len(re.findall(r"ui::rgba\(", icon.split("};")[0])) == len(tones) - 1, "the menu has not a colour for every tone")
    # the menu: told by the host, the row shown once it was, its page, the notice
    check("if (id == HOS_OPT_ACH_ASK) return 1;" in replay, "the renderer does not say that it shows the achievements")
    setter = block(menu, "void menu_option_set(")
    for line in ("if (id == HOS_OPT_ACH_TEXT) return ach_list.text(value);", "if (id == HOS_OPT_ACH_ADD) return ach_list.add(value);",
                 "ach_list.done(value);", "if (ach_list.earn(value)) menu_refresh = true;"):
        check(line in setter, "the menu does not take the host's achievements: " + line)
    table = menu[menu.index("Row rows[] = {"):]
    # (11-23) a group of their own, the System tab's first: the list's page, then the two switches
    system = [m.start() for m in re.finditer(r"TAB_SYSTEM", table)]
    order = [table.index(part) for part in ('MENU_HEADING(TAB_SYSTEM, "Achievements"),', '{TAB_SYSTEM, "View achievements", nullptr, 0, 0, 0, nullptr,',
                                            '{TAB_SYSTEM, "Achievements", &opts.achievements, 0, 1, 1, tx_onoff,',
                                            '{TAB_SYSTEM, "Achievement notices", &opts.achievement_notices, 0, 1, 1, tx_onoff,',
                                            'MENU_HEADING(TAB_SYSTEM, "Game"),')]
    check(order == sorted(order) and system[0] > order[0] and system[0] - order[0] < 40 and 'constexpr char kAchRow[] = "View achievements";' in menu,
          "the Achievements group is not the System tab's first, with its page's row and its two switches")
    check(re.search(r"\bint achievements = 1;", read("gpu", "vk", "vk_menu.h")) and re.search(r"\bint achievement_notices = 1;", read("gpu", "vk", "vk_menu.h")),
          "the Achievements rows are not On unless set")
    check("if (id == HOS_OPT_ACH_ON) return opts.achievements != 0;" in replay and "if (id == HOS_OPT_ACH_NOTICES) return opts.achievement_notices != 0;" in replay,
          "the renderer does not tell the host the Achievements rows")
    check("if (!hos_achievements_on() || !rx_option(HOS_OPT_ACH_ON, 1)) return;" in own and "if (!quiet) hos_menu_sound_play(HOS_MENU_SOUND_SYS_DECIDE, now_ns);" in own,
          "the host earns with the Achievements row Off, or plays the notice's sound with the notices Off")
    tick = block(menu, "void menu_tick() {")
    check("earned >= 0 && opts.achievement_notices) ach_notice = earned, ach_notice_at = prof_now();" in tick, "a notice shows with the Achievement notices row Off")
    notice = block(menu, "void draw_ach_notice(ui::Ctx& c) {")
    check('constexpr char kAchWhere[] = "See all: Options > System";' in menu and "ui::kSoft, kAchWhere);" in notice and "ui::size_of(c.f.body, 12 * s, kAchWhere).x" in notice,
          "the notice does not say where the list is, or is not as wide as that line")
    check("(strcmp(rows[i].name, kAchRow) || rows[i].tab != TAB_SYSTEM || ach_list.shown() > 0) &&" in block(menu, "bool row_shown("),
          "the Achievements row shows before the host named them")
    press = menu[menu.index("else if (press[7] && is_ach_row(r)) page = kAchPage"):]
    check(press.index("is_ach_row(r)") < press.index("else if (press[7] && !r.value && can_bind()) page = 1"),
          "the Achievements row opens the Controls page: it is asked after the rows without a value")
    check("else if (page == kAchPage) draw_achievements(k);" in block(menu, "void draw_menu(ui::Ctx& c, bool perf_under) {"), "the Achievements page is not drawn")
    page = number(menu, "kAchPage")
    check(page not in (0, 1, 3, 4, 5, 6, number(menu, "kModsPage"), number(menu, "kModsRowPage")), "kAchPage is another page's number")
    body = block(menu, "void menu_record_image(")
    check("ach_notice >= 0 && prof_now() - ach_notice_at < kAchNoticeMs * 1000000" in body and "&& !earned)" in body
          and "if (earned) draw_ach_notice(c);" in body, "menu_record_image: an achievement's notice is not drawn, or not while nothing else shows")
    # ((Triforce, 11-23) N64 Classic split menu_record: what shows (showing_now) and the drawing (draw_overlays), the notice in both)
    check("s.earned = !s.start && ach_notice >= 0 && prof_now() - ach_notice_at < kAchNoticeMs * 1000000" in block(menu, "Showing showing_now(")
          and "if (s.earned) draw_ach_notice(c);" in block(menu, "void draw_overlays(")
          and "&& !s.earned)" in block(menu, "void menu_record("), "menu_record: an achievement's notice is not drawn, or not while nothing else shows")
    check(number(own, "SHOWN_MS") > int(re.search(r"kAchNoticeMs = (\d+);", menu).group(1)), "the host shows the next notice before this one is gone")
    return api, own


def check_names(exe):
    """The built-in list asks only for items the Inventory page already names, a count only of one that has a count, and no flag"""
    items = dict(re.findall(r'OOT_ITEM\("[^"]+", "([^"]+)", ([01])\)', (ROOT / "gpu" / "vk" / "oot_cheat_items.h").read_text(encoding="utf-8")))
    check(len(items) > 60, "gpu/vk/oot_cheat_items.h: the items were not read")
    asked = [line.split() for line in run([str(exe), "names"]).splitlines()]
    check(len(asked) >= 25, "the built-in list's conditions were not printed")
    for kind, what, least in asked:
        check(kind == "I", "the built-in list asks for a flag: %s" % what)
        check(what in items, "the built-in list names what gpu/vk/oot_cheat_items.h does not: %s" % what)
        check(least == "1" or items[what] == "1", "the built-in list counts an item that has no count: %s" % what)
    header = (ROOT / "host" / "achievements.h").read_text(encoding="utf-8")
    quoted = set(re.findall(r"\b((?:Item|Weapon|Armor)_[A-Za-z0-9_]+)", header))
    check(quoted and quoted <= set(items), "host/achievements.h names what gpu/vk/oot_cheat_items.h does not: %s" % sorted(quoted - set(items))[:3])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="cc")
    p.add_argument("--cxx", default="c++")
    a = p.parse_args()
    api, own = check_sources()
    with tempfile.TemporaryDirectory(prefix="triforce-achievements-") as tmp:
        tmp = Path(tmp)
        warnings = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
        # the list, the conditions and the file
        exe = tmp / "list.exe"
        run([a.cc] + warnings + ["-I" + str(ROOT / "host"), str(ROOT / "tests" / "achievements_test.c"), "-o", str(exe)])
        run([str(exe)], says="PASS")
        check_names(exe)
        # the menu's side
        exe = tmp / "rows.exe"
        run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu" / "vk"), str(ROOT / "tests" / "achievement_rows_test.cpp"),
             "-o", str(exe)])
        run([str(exe)], says="PASS")
        # the host's side: host/achievements.c from after its includes on, with the menu's ids from vk_api.h
        marker = '#include "menu_sound.h"\n'
        check(own.count(marker) == 1, "host/achievements.c no longer includes menu_sound.h last")
        (tmp / "achievements_actual.inc").write_text(own[own.index(marker) + len(marker):], encoding="utf-8")
        (tmp / "achievements_constants.inc").write_text(
            "".join(block(api, start) + ";\n" for start in ("enum { HOS_OPT_ACH_TEXT = 165", "enum { HOS_OPT_ACH_ON = 185", "enum { HOS_ACH_EARNED = 256", "enum { HOS_MENU_SOUND_OPEN = 1")),
            encoding="utf-8")
        exe = tmp / "host.exe"
        run([a.cc] + warnings + ["-Wno-unused-function", "-I" + str(ROOT / "host"), "-I" + str(tmp), str(ROOT / "tests" / "achievements_host_test.c"),
                                 "-o", str(exe)])
        game = tmp / "game folder"
        game.mkdir()
        (game / "achievements.txt").write_bytes(OWN_LIST.encode("utf-8"))
        earned = game / "triforce_achievements.txt"
        env = {k: v for k, v in os.environ.items() if k != "HOS_ACHIEVEMENTS"}
        run([str(exe), str(game), "off"], says="PASS", cwd=str(tmp), env=dict(env, HOS_ACHIEVEMENTS="0"))   # (on unless it is 0)
        check(not earned.exists(), "a file was written with the achievements off")
        on = dict(env, HOS_ACHIEVEMENTS="1")
        run([str(exe), str(game), "first"], says="PASS", cwd=str(tmp), env=env)   # (on by default: the switch not set)
        kept = earned.read_text(encoding="utf-8").splitlines()
        check(kept[0].startswith("#") and [line.split(" ", 2)[2] for line in kept[1:]] ==
              ["A Sword of Your Own", "Forest's Thanks", "Heart of the Mountain", "Jewel of the River", "Three Stones", "Mine"],
              "what the game folder keeps of the earned ones: %r" % kept)
        check(all(re.fullmatch(r"[0-9a-f]{8} \d{9,} .+", line) for line in kept[1:]), "an earned one is not its key, its time and its name: %r" % kept)
        with open(earned, "ab") as f:   # (an achievement of a list that was taken away since)
            f.write(b"deadbeef 5 Gone\n")
        run([str(exe), str(game), "second"], says="PASS", cwd=str(tmp), env=on)
        check(sorted(f.name for f in game.iterdir()) == ["achievements.txt", "triforce_achievements.txt"], "the game folder has other files now")
        # (11-23) the System tab's two rows, in a game folder of its own
        rows_game = tmp / "rows game"
        rows_game.mkdir()
        run([str(exe), str(rows_game), "rows"], says="PASS", cwd=str(tmp), env=on)
        # the save files on (host/save_files.c): what a file earned is kept in its own folder, and is no other file's.
        # File 1 starts from what the game folder earned before; the game folder's own is left as it was
        before = earned.read_bytes()
        (game / "user").mkdir(), (game / "user-2").mkdir()
        run([str(exe), str(game), "file2"], says="PASS", cwd=str(tmp), env=on)
        run([str(exe), str(game), "file1"], says="PASS", cwd=str(tmp), env=on)
        run([str(exe), str(game), "again1"], says="PASS", cwd=str(tmp), env=on)
        check(earned.read_bytes() == before, "the game folder's earned achievements were changed by a save file's")
        check(sorted(f.name for f in (game / "user-2").iterdir()) == ["triforce_achievements.txt"] and
              sorted(f.name for f in (game / "user").iterdir()) == ["triforce_achievements.txt"], "a save file's folder has other files now")
        check((game / "achievements.txt").read_bytes() == OWN_LIST.encode("utf-8"), "the player's own list was changed")
    print("PASS: achievements: the list and what it refuses, earning, the file of the earned ones, the host's naming and notices, "
          "the menu's list and page, and on unless HOS_ACHIEVEMENTS=0")


if __name__ == "__main__":
    main()
