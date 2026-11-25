// (Triforce) The Insert menu's languages (vk_menu_i18n.cpp): its English texts as written in vk_menu.cpp, shown in the
// language the Menu language row picks (English by default; Auto: the language the game runs in). The tables are
// menu_i18n.h's. ui::text, ui::para, ui::size_of, ui::fit_text and ui::spaced (vk_ui.h) look every text up, so a row, a value
// or a help line is drawn translated without a call of its own; a text the table does not have is drawn as it is (English).
#pragma once

#include <string>
#include <utility>
#include <vector>

namespace mkwvk::i18n {

/// The language now: an index into menu_i18n::kLangs (0 English)
int lang_now();
/// Its code ("pt-BR", "ja", "en")
const char* lang_code();
/// The plural form a count takes in it: 0 one, 1 more than one, 2 many (Russian and Polish only: 5 and up, 11 to 14, ...)
int plural(int n);
/// The Menu language row's languages: each of menu_i18n::kLangs by its own name (the row's 0 is Auto, its v is lang_name(v - 1))
int lang_count();
const char* lang_name(int index);
/// The language the game runs in, this run: a place in game_language::kLanguages (vk_menu.cpp lang_load reads it as the
/// host does, HOS_LANGUAGE over language.txt). The menu's Auto follows it; it changes only with a restart
void set_game_started(int game_language);
/// A game language's own name (game_language::kOwnNames), for the Game language row
const char* game_lang_name(int game_language);
/// The languages' names the Game language and Menu language rows showed (game_lang_name, lang_name) since the last call, as
/// {code, name}: those with letters past Latin (Русский, 日本語, 한국어, 简体中文 ...), each once. vk_imgui.cpp merges in a font
/// of their letters when the menu's fonts lack them, whatever language the menu is in
std::vector<std::pair<std::string, std::string>> names_shown_since();
/// The texts of a language's table (menu_i18n.h), for vk_imgui.cpp to find which of their letters the menu's fonts lack
std::vector<const char*> texts_of(const char* code);

/// A text as the menu shows it: s itself in English or when the table lacks it, else its translation. A text made from one
/// of the table's printf formats ("%d of %d") is translated through it. The pointer stays good for many frames (a text made
/// from a format is kept in a cache of two generations of 4096 texts)
const char* tr(const char* s);
std::string tr_text(const std::string& s);

}  // namespace mkwvk::i18n
