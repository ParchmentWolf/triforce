// The radial menus' item names in the game's language (item_names.cpp), from its own message files
#pragma once

// item: the item's name in the game's files ("Item_Hookshot"); its name in the game's language, or fallback when the
// files have none. The text stays valid until the game's language changes.
const char *item_name_text(const char *item, const char *fallback);
