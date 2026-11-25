"""gpu/vk/menu_i18n.h, the Insert menu's translations, against Triforce's own menu: every table's texts are texts the menu
writes (vk_menu.cpp and the headers it includes), every translation keeps its text's printf conversions in order and its
leading and trailing spaces (the menu joins pieces), no translation is empty, each table is sorted with each text once, and
the language list holds what vk_menu_i18n.cpp expects (English first, with no table; each other language's count its
table's length, lang()'s). The Menu language row and the restart line's pieces are in every table. No game, no compiler
(tests/test_menu_i18n_count.py compiles the header and compares the counts as compiled).

Run with: python -I tests/test_menu_i18n.py
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def c_strings(text):
    """The C string literals of a source, adjacent ones joined, escapes as written"""
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'"\s*\n\s*"', '', text)
    return re.findall(r'"((?:[^"\\\n]|\\.)*)"', text)


def menu_sources():
    """vk_menu.cpp and the headers of gpu/vk it includes: the texts the menu can draw"""
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    out = [menu]
    for name in re.findall(r'^#include "([^"]+)"', menu, re.M):
        if name.endswith(".h") and (VK / name).is_file() and name != "menu_i18n.h":
            out.append((VK / name).read_text(encoding="utf-8"))
    return "\n".join(out)


def conversions(s):
    """The printf conversions of s in order (as vk_menu_i18n.cpp conversion() reads them; not ' ': "80% suits" is a sign)"""
    return re.findall(r'%[-+#0]*\d*(?:\.\d+)?[lhz]*[sducxgf%]', s)


# ((Triforce) the ReShade preset row's line under its help (reshade_menu.h hn_preset): the runtime's status, from these)
RESHADE_STATUS = (
    "Waiting for the gameplay scene", "Preparing ReShade preset", "Ready for linear HDR gameplay",
    "Ready for SDR gameplay", "Use Expanded HDR for imported SDR presets.",
    "This preset requires active Native HDR", "Could not read the ReShade preset",
)


def tables():
    src = (VK / "menu_i18n.h").read_text(encoding="utf-8")
    out = {}
    for name, body in re.findall(r'inline constexpr Entry (k\w+)\[\] = \{\n(.*?)\n\};', src, re.S):
        out[name] = re.findall(r'^    \{"((?:[^"\\]|\\.)*)", "((?:[^"\\]|\\.)*)"\},$', body, re.M)
    # (English's row {"en", "English", nullptr, 0}; the others lang(code, name, table), whose count is the table's length)
    langs = re.findall(r'^    (?:\{|lang\()"([\w-]+)", "((?:[^"\\]|\\.)*)", (\w+)(?:, (\d+)\}|\)),$', src, re.M)
    return src, out, langs


class MenuI18nTests(unittest.TestCase):
    def setUp(self):
        self.src, self.tables, self.langs = tables()
        self.menu = set(c_strings(menu_sources()))
        runtime = set()
        for name in ("fx_runtime.cpp", "fx_preset.cpp"):
            runtime.update(c_strings((VK / "reshade" / name).read_text(encoding="utf-8")))
        self.menu.update(text for text in RESHADE_STATUS if text in runtime)

    def test_languages(self):
        self.assertEqual(self.langs[0], ("en", "English", "nullptr", "0"))
        self.assertEqual(len(self.tables), 13)
        codes = [code for code, _, _, _ in self.langs]
        self.assertEqual(len(codes), len(set(codes)), "a language listed twice")
        for code, _, table, count in self.langs[1:]:
            self.assertIn(table, self.tables, code)
            self.assertEqual(count, "", "%s: a count written by hand, not lang()'s, its table's length" % code)
        self.assertEqual(sorted(table for _, _, table, _ in self.langs[1:]), sorted(self.tables), "a table no language reads")
        # (Auto: the game's language codes, game_language.h, find their table by the code or its first part)
        game = re.findall(r'\{"([\w-]+)", "[^"]+"\}', (VK / "game_language.h").read_text(encoding="utf-8"))
        for code in game:
            self.assertTrue(code in codes or code.split("-")[0] in codes, "%s: no menu language for Auto" % code)

    def test_texts_are_the_menus(self):
        for table, pairs in self.tables.items():
            for en, _ in pairs:
                self.assertIn(en, self.menu, "%s: %r is no text of the menu (renamed? then translate it again)" % (table, en))

    def test_conversions_and_spaces(self):
        for table, pairs in self.tables.items():
            keys = [en for en, _ in pairs]
            self.assertTrue(keys, table)
            self.assertEqual(len(keys), len(set(keys)), "%s: a text twice" % table)
            self.assertEqual(keys, sorted(keys), "%s: not sorted (menu_i18n.h is written sorted)" % table)
            for en, text in pairs:
                self.assertTrue(text, "%s: %r has an empty translation" % (table, en))
                self.assertEqual(conversions(en), conversions(text), "%s: %r and %r" % (table, en, text))
                for side in (lambda s: s[:len(s) - len(s.lstrip(" "))], lambda s: s[len(s.rstrip(" ")):]):
                    self.assertEqual(side(en), side(text), "%s: the spaces around %r" % (table, en))

    def test_rows_and_restart_line(self):
        texts = ("Menu language", "Game language", "Auto (game's language)", "The language of this menu.",
                 "Follows the game's language (language.txt in the game folder).", "Restart needed: ", "Restart to apply ",
                 " and ", " more", " setting", " settings")
        for text in texts:
            self.assertIn(text, self.menu)
        for table, pairs in self.tables.items():
            translated = dict(pairs)
            for text in texts:
                with self.subTest(table=table, text=text):
                    self.assertIn(text, translated)

    def test_reshade_texts_are_translated(self):
        texts = (
            "Post-processing", "ReShade preset", "Compare ReShade Preset", "User preset file",
            "Rescan ReShade presets", "Enabled · On", "Enabled · Off", "No user presets", "Choose a preset",
            "Warm", "Cool", "User", "HDR Vibrance", "Depth View", "Depth Haze",
            "Native HDR supports built-in and LinearHDR presets. Use Expanded HDR for imported SDR presets.",
            "Preview presets. Back restores your saved selection.",
            "Copy INI files to reshade/presets and FX and FXH files to reshade/shaders, then rescan.",
            *RESHADE_STATUS,
        )
        for text in texts:
            self.assertIn(text, self.menu)
        for table, pairs in self.tables.items():
            for text in texts:
                with self.subTest(table=table, text=text):
                    self.assertIn(text, dict(pairs))

    def test_plural_forms(self):
        # (i18n::plural: Russian and Polish ask for a third form, " settings (many)", for 5 and up; the menu shows it
        # nowhere else, so only their tables have it)
        cpp = (VK / "vk_menu_i18n.cpp").read_text(encoding="utf-8")
        self.assertIn('" settings (many)"', (VK / "vk_menu.cpp").read_text(encoding="utf-8"))
        for table, code in (("kru", "ru"), ("kpl", "pl")):
            self.assertIn('code == "%s"' % code, cpp)
            self.assertIn(" settings (many)", dict(self.tables[table]), table)
            self.assertIn(" settings", dict(self.tables[table]), table)

    def test_own_names(self):
        # (each language by its own name, on both rows: the menu's languages here, the game's in game_language.h)
        names = dict((code, name) for code, name, _, _ in self.langs)
        for code, name in (("ru", "Русский"), ("ja", "日本語"), ("ko", "한국어"), ("zh-Hans", "简体中文"), ("zh-Hant", "繁體中文")):
            self.assertEqual(names[code], name)
        game = (VK / "game_language.h").read_text(encoding="utf-8")
        own = game[game.index("constexpr const char* kOwnNames[] = {"):]
        own = re.findall(r'"([^"]+)"', own[:own.index("};")])
        self.assertEqual(len(own), 16)
        for name in ("Русский", "日本語", "한국어", "简体中文", "繁體中文"):
            self.assertIn(name, own)

    def test_no_other_project_names(self):
        self.assertIsNone(re.search(r"(?i)long" r"shot|magic" r"bean", self.src))


if __name__ == "__main__":
    unittest.main()
