// The radial menus (radial_menu.h): what each slot holds, read from the game data's names (oot_game_data.h), the slots fixed so
// an item is always in the same place. The item radial menu's values are the game's AssignableItem enum's, owned by their
// IsGet.<name> flags, the trade items while their stock is above 0, the bottles by the game data's
// PlayerStatus.AssignableItem.BottleInfo (IsValid, and what each holds for its icon and name); and the ocarinas and the worn
// gear (a mask, the Lens of Truth, boots) by their names. A slot may hold variants a tap on it steps through (first one, then
// the next: the bomb kinds, the adult's arrows), the last one kept for each slot.
#include <atomic>
#include <chrono>
#include <cmath>
#include <mutex>
#include <stdio.h>
#include <string>
#include <string.h>

#include "oot_game_data.h"
#include "vk_internal.h"
#include "item_names.h"
#include "radial_menu.h"
#include "vk_api.h"

// the game data, read from the guest window (oot_game_data.h)
static const uint8_t *gw() { return mkwvk::host ? mkwvk::host->guest_base() : nullptr; }
static int dbg_flag_get(const char *name, int *on) { return oot_data_flag(gw(), name, on); }
static int dbg_int_get(const char *name, int32_t *v) { return oot_data_int(gw(), name, v); }
static int dbg_enum_get(const char *name, uint32_t *value_hash) { return oot_data_enum(gw(), name, value_hash); }
static uint32_t dbg_name_hash(const char *name) { return oot_data_hash(name); }

#define ICON_DIR "UI/Tex/Icon/"
#define COMMON_BNTX "UI/Layout2Archive/Common.Product.100.Nin_Ounce_NVN2.bntx.zs"

// OWN_HELD: a mask, the one held as the Equipment page shows it (borrowed, as on the N64): its stock above 0, or its IsGet
// where the game data keeps no stock of it
typedef enum { OWN_GET, OWN_STOCK, OWN_BOTTLE, OWN_ARROW, OWN_HELD } Own;
typedef struct {
    const char *value;   // the AssignableItem value
    const char *name;    // its item's name: IsGet.<name>, PouchData.<name>.StockNum, the icon <name>
    Own own;             // OWN_ARROW: IsGet.<name> and the bow
    const char *label;   // shown under the radial menu when the game's own name is missing (item_names.cpp)
    const char *ammo;    // what counts it (PouchData.<ammo>.StockNum), NULL none
} Item;

static const Item kItems[] = {
    {"SlingShot", "Weapon_Range_SlingShot", OWN_GET, "Fairy Slingshot", "Item_DekuSeed"},
    {"Bow", "Weapon_Range_Bow", OWN_GET, "Fairy Bow", "Item_Arrow_Normal"},
    {"FireArrow", "Item_Arrow_Fire", OWN_ARROW, "Fire Arrow", "Item_Arrow_Normal"},
    {"IceArrow", "Item_Arrow_Ice", OWN_ARROW, "Ice Arrow", "Item_Arrow_Normal"},
    {"LightArrow", "Item_Arrow_Light", OWN_ARROW, "Light Arrow", "Item_Arrow_Normal"},
    {"Boomerang", "Item_Boomerang", OWN_GET, "Boomerang"},
    {"Hookshot", "Item_Hookshot", OWN_GET, "Hookshot"},
    {"Longshot", "Item_Longshot", OWN_GET, "Longshot"},
    {"DekuStick", "Item_DekuStick", OWN_GET, "Deku Stick", "Item_DekuStick"},
    {"Hammer", "Item_Hammer", OWN_GET, "Megaton Hammer"},
    {"DekuNut", "Item_DekuNut", OWN_GET, "Deku Nut", "Item_DekuNut"},
    {"Bomb", "Item_Bomb", OWN_GET, "Bombs", "Item_Bomb"},
    {"Bombchu", "Item_Bombchu", OWN_GET, "Bombchus", "Item_Bombchu"},
    {"DinFire", "Item_DinFire", OWN_GET, "Din's Fire"},
    {"FaroreWind", "Item_FaroreWind", OWN_GET, "Farore's Wind"},
    {"NayruLove", "Item_NayruLove", OWN_GET, "Nayru's Love"},
    {"MagicBean", "Item_MagicBean", OWN_GET, "Magic Beans", "Item_MagicBean"},
    {"ScrubBusinessSeed", "Item_ScrubBusinessSeed", OWN_STOCK, "Deku Seed", "Item_ScrubBusinessSeed"},
    {"BottleA", "A", OWN_BOTTLE, NULL}, {"BottleB", "B", OWN_BOTTLE, NULL}, {"BottleC", "C", OWN_BOTTLE, NULL},
    {"BottleD", "D", OWN_BOTTLE, NULL}, {"BottleE", "E", OWN_BOTTLE, NULL},
    {"WeirdEgg", "Item_WeirdEgg", OWN_STOCK, "Weird Egg"},
    {"AlarmCucco", "Item_AlarmCucco", OWN_STOCK, "Cucco"},
    {"ZeldaLetter", "Item_ZeldaLetter", OWN_STOCK, "Zelda's Letter"},
    {"PocketEgg", "Item_PocketEgg", OWN_STOCK, "Pocket Egg"},
    {"PocketCucco", "Item_PocketCucco", OWN_STOCK, "Pocket Cucco"},
    {"CojiroCucco", "Item_CojiroCucco", OWN_STOCK, "Cojiro"},
    {"OddMushroom", "Item_OddMushroom", OWN_STOCK, "Odd Mushroom"},
    {"OddPowder", "Item_OddPowder", OWN_STOCK, "Odd Potion"},
    {"PoacherSaw", "Item_PoacherSaw", OWN_STOCK, "Poacher's Saw"},
    {"BrokenSword", "Item_BrokenSword", OWN_STOCK, "Broken Goron's Sword"},
    {"Prescription", "Item_Prescription", OWN_STOCK, "Prescription"},
    {"EyeballFrog", "Item_EyeballFrog", OWN_STOCK, "Eyeball Frog"},
    {"EyeDrop", "Item_EyeDrop", OWN_STOCK, "Eye Drops"},
    {"ClaimCheck", "Item_ClaimCheck", OWN_STOCK, "Claim Check"},
    // (Triforce) used by their names: the ocarinas played (the game's D-pad left), the worn gear put on and off
    {"Item_Ocarina_Time", "Item_Ocarina_Time", OWN_GET, "Ocarina of Time"},
    {"Item_Ocarina_Fairy", "Item_Ocarina_Fairy", OWN_GET, "Fairy Ocarina"},
    {"Armor_GlassTruth", "Armor_GlassTruth", OWN_GET, "Lens of Truth"},
    {"Armor_Child_Mask_Keaton", "Armor_Child_Mask_Keaton", OWN_HELD, "Keaton Mask"},
    {"Armor_Child_Mask_Skull", "Armor_Child_Mask_Skull", OWN_HELD, "Skull Mask"},
    {"Armor_Child_Mask_Spooky", "Armor_Child_Mask_Spooky", OWN_HELD, "Spooky Mask"},
    {"Armor_Child_Mask_Bunny", "Armor_Child_Mask_Bunny", OWN_HELD, "Bunny Hood"},
    {"Armor_Child_Mask_Truth", "Armor_Child_Mask_Truth", OWN_HELD, "Mask of Truth"},
    {"Armor_Child_Mask_Goron", "Armor_Child_Mask_Goron", OWN_HELD, "Goron Mask"},
    {"Armor_Child_Mask_Zora", "Armor_Child_Mask_Zora", OWN_HELD, "Zora Mask"},
    {"Armor_Child_Mask_Gerudo", "Armor_Child_Mask_Gerudo", OWN_HELD, "Gerudo Mask"},
    {"Armor_Child_Mask_Amiibo0", "Armor_Child_Mask_Amiibo0", OWN_HELD, NULL},
    {"Armor_Child_Mask_Amiibo1", "Armor_Child_Mask_Amiibo1", OWN_HELD, NULL},
    {"Armor_Adult_HeavyBoot", "Armor_Adult_HeavyBoot", OWN_GET, "Iron Boots"},
    {"Armor_Adult_HoverBoot", "Armor_Adult_HoverBoot", OWN_GET, "Hover Boots"},
};

// A slot's variant: the values it may be, the first owned taken (Longshot before Hookshot, the latest trade item)
#define ALTS 12
typedef struct {
    const char *alt[ALTS];
} Var;
// A slot: its variants for each era (up to 4; a tap steps through the owned ones; each slot keeps the one chosen last),
// arrows: the variants drawn as a row of small icons under the first's, and other_age: with none of this age's owned, the
// other age's shown gray (as the Items page shows them), not usable
typedef struct {
    Var child[4], adult[4];
    int arrows, other_age;
} SlotDef;
#define ONE(v) {{{v}}}
#define ONE2(a, b) {{{a, b}}}
#define MASKS "Armor_Child_Mask_Truth", "Armor_Child_Mask_Gerudo", "Armor_Child_Mask_Zora", "Armor_Child_Mask_Goron", \
              "Armor_Child_Mask_Bunny", "Armor_Child_Mask_Spooky", "Armor_Child_Mask_Skull", "Armor_Child_Mask_Keaton", \
              "Armor_Child_Mask_Amiibo0", "Armor_Child_Mask_Amiibo1"
static const SlotDef kSlots[RADIAL_MENU_ITEM_SLOTS] = {
    {ONE2("Item_Ocarina_Time", "Item_Ocarina_Fairy"), ONE2("Item_Ocarina_Time", "Item_Ocarina_Fairy"), 0},
    {{{{MASKS}}, {{"Armor_GlassTruth"}}}, {{{MASKS}}, {{"Armor_GlassTruth"}}}, 0},   // (the mask: the latest owned)
    {{{{"DekuNut"}}, {{"ScrubBusinessSeed"}}}, {{{"DekuNut"}}, {{"ScrubBusinessSeed"}}}, 0},
    {{{{"DekuStick"}}, {{"Boomerang"}}}, {{{"Hammer"}}, {{"Longshot", "Hookshot"}}}, 0},
    {ONE("SlingShot"), {{{"Bow"}}, {{"FireArrow"}}, {{"IceArrow"}}, {{"LightArrow"}}}, 1},
    {{{{"Bomb"}}, {{"Bombchu"}}}, {{{"Bomb"}}, {{"Bombchu"}}}, 0},
    {ONE("BottleE"), ONE("BottleE"), 0},
    {ONE("BottleD"), ONE("BottleD"), 0},
    {ONE("BottleC"), ONE("BottleC"), 0},
    {ONE("BottleB"), ONE("BottleB"), 0},
    {ONE("BottleA"), ONE("BottleA"), 0},
    {ONE("NayruLove"), ONE("NayruLove"), 0},
    {ONE("FaroreWind"), ONE("FaroreWind"), 0},
    {ONE("DinFire"), ONE("DinFire"), 0},
    {{{{"ZeldaLetter", "AlarmCucco", "WeirdEgg"}}},
     {{{"ClaimCheck", "EyeDrop", "EyeballFrog", "Prescription", "BrokenSword", "PoacherSaw", "OddPowder", "OddMushroom",
         "CojiroCucco", "PocketCucco", "PocketEgg"}}},
     0, 1},
    {ONE("MagicBean"), {{{"Armor_Adult_HeavyBoot"}}, {{"Armor_Adult_HoverBoot"}}}, 0},   // (the beans a child's alone)
};
static std::atomic<int> g_mem[RADIAL_MENU_ITEM_SLOTS];   // each slot's variant chosen last (its index in its list)

// A bottle's contents (its BottleItem enum's values), their icons and names
static const char *const kBottle[][3] = {
    {"Empty", "Item_Bottle", "Empty Bottle"},
    {"RedPotion", "Item_Bottle_RedPotion", "Red Potion"},
    {"GreenPotion", "Item_Bottle_GreenPotion", "Green Potion"},
    {"BluePotion", "Item_Bottle_BluePotion", "Blue Potion"},
    {"BlueFire", "Item_Bottle_BlueFire", "Blue Fire"},
    {"Fish", "Item_Bottle_Fish", "Fish"},
    {"Letter", "Item_Bottle_Letter", "Ruto's Letter"},
    {"BigPoe", "Item_Bottle_BigPoe", "Big Poe"},
    {"Poe", "Item_Bottle_Poe", "Poe"},
    {"Bug", "Item_Bottle_Bug", "Bug"},
    {"Fairy", "Item_Bottle_Fairy", "Fairy"},
    {"MaxMilk", "Item_Bottle_Milk", "Lon Lon Milk"},
    {"HalfMilk", "Item_Bottle_HalfMilk", "Lon Lon Milk (half)"},
};
static const char *const kArrowIcon[4] = {"Item_Arrow_Normal", "Item_Arrow_Fire", "Item_Arrow_Ice", "Item_Arrow_Light"};

static int flag(const char *name) {
    int on = 0;
    return dbg_flag_get(name, &on) && on;
}

static const Item *item_of(const char *value) {
    for (size_t i = 0; i < sizeof kItems / sizeof *kItems; i++)
        if (!strcmp(kItems[i].value, value)) return &kItems[i];
    return NULL;
}

// it owned now; *icon and *label its icon's name and its name (a bottle's by what it holds)
static int owned(const Item *it, const char **icon, const char **label) {
    char key[128];
    *icon = it->name, *label = it->label;
    switch (it->own) {
    case OWN_GET:
        snprintf(key, sizeof key, "IsGet.%s", it->name);
        return flag(key);
    case OWN_ARROW:
        snprintf(key, sizeof key, "IsGet.%s", it->name);
        return flag(key) && flag("IsGet.Weapon_Range_Bow");
    case OWN_STOCK: {
        int32_t n = 0;
        snprintf(key, sizeof key, "PouchData.%s.StockNum", it->name);
        return dbg_int_get(key, &n) && n > 0;
    }
    case OWN_HELD: {
        int32_t n = 0;
        snprintf(key, sizeof key, "PouchData.%s.StockNum", it->name);
        if (dbg_int_get(key, &n)) return n > 0;
        snprintf(key, sizeof key, "IsGet.%s", it->name);
        return flag(key);
    }
    case OWN_BOTTLE: {
        snprintf(key, sizeof key, "PlayerStatus.AssignableItem.BottleInfo.Bottle%s.IsValid", it->name);
        if (!flag(key)) return 0;
        snprintf(key, sizeof key, "PlayerStatus.AssignableItem.BottleInfo.Bottle%s.BottleItem", it->name);
        uint32_t held = 0;
        *icon = kBottle[0][1], *label = kBottle[0][2];
        if (dbg_enum_get(key, &held))
            for (size_t i = 0; i < sizeof kBottle / sizeof *kBottle; i++)
                if (dbg_name_hash(kBottle[i][0]) == held) *icon = kBottle[i][1], *label = kBottle[i][2];
        return 1;
    }
    }
    return 0;
}

int radial_menu_child(void) {
    int child = 1;
    dbg_flag_get("Sequence_IsChildhood", &child);
    return child;
}

static void icon_file(RadialMenuTex *out, const char *name) {
    snprintf(out->file, sizeof out->file, ICON_DIR "%s.bntx.zs", name);
    snprintf(out->tex, sizeof out->tex, "%s", name);
    out->gray = 0;
}

// A variant's value owned now (the first of its alternatives), its icon and name; NULL when none is owned
static const char *variant(const Var *v, const char **icon, const char **label) {
    for (int i = 0; i < ALTS && v->alt[i]; i++) {
        const Item *it = item_of(v->alt[i]);
        if (it && owned(it, icon, label)) return it->value;
    }
    return NULL;
}

// How many of a counted item can be carried: the largest of its bags owned (the game's RSDB/PouchActorInfo,
// AfterExpansionMaxNum of each bag, the bags the item's MaxNumGameData shares; the smallest without one), or its
// FixedMaxNum; -1 unknown
static int max_of(const char *ammo) {
    static const struct { const char *ammo, *bag; int n[3]; } bags[] = {
        {"Item_Bomb", "BombBag", {20, 30, 40}},        {"Item_Bombchu", "BombBag", {20, 30, 40}},
        {"Item_Arrow_Normal", "Quiver", {30, 40, 50}}, {"Item_DekuSeed", "BulletBag", {30, 40, 50}},
        {"Item_DekuNut", "NutBag", {20, 30, 40}},      {"Item_DekuStick", "StickBag", {10, 20, 30}},
    };
    static const char *const sizes[3] = {"Small", "Medium", "Large"};
    if (!strcmp(ammo, "Item_MagicBean")) return 10;
    for (size_t i = 0; i < sizeof bags / sizeof *bags; i++) {
        if (strcmp(bags[i].ammo, ammo)) continue;
        char key[128];
        for (int s = 2; s > 0; s--) {
            snprintf(key, sizeof key, "IsGet.Item_%s_%s", bags[i].bag, sizes[s]);
            if (flag(key)) return bags[i].n[s];
        }
        return bags[i].n[0];
    }
    return -1;
}

// A value's ammunition or stock now (-1 for an item that has none) and *max how many can be carried
static int count_of(const char *value, int *max) {
    const Item *it = value ? item_of(value) : NULL;
    char key[128];
    int32_t n = 0;
    *max = -1;
    if (!it || !it->ammo) return -1;
    snprintf(key, sizeof key, "PouchData.%s.StockNum", it->ammo);
    if (!dbg_int_get(key, &n)) return -1;
    *max = max_of(it->ammo);
    return n;
}

// The item slot now: its variants owned (their indices in the list, *n of them) and the one in use (an index of those)
static const Var *slot_vars(int slot, int *count) {
    const Var *vars = radial_menu_child() ? kSlots[slot].child : kSlots[slot].adult;
    *count = 0;
    while (*count < 4 && vars[*count].alt[0]) (*count)++;
    return vars;
}
static int slot_current(int slot, const Var *vars, int count, int owned_idx[4], int *n_owned) {
    const char *icon, *label;
    *n_owned = 0;
    for (int i = 0; i < count; i++)
        if (variant(&vars[i], &icon, &label)) owned_idx[(*n_owned)++] = i;
    if (!*n_owned) return -1;
    const int want = g_mem[slot].load();
    for (int k = 0; k < *n_owned; k++)
        if (owned_idx[k] == want) return k;
    return 0;
}

int radial_menu_slots(int kind) { return kind == RADIAL_MENU_GEAR ? RADIAL_MENU_GEAR_SLOTS : RADIAL_MENU_ITEM_SLOTS; }

// The gear radial menu, clockwise from the top: the swords, the tunics, the shields (three thirds, a third's edge at the top).
// A slot shows the first of its gear owned (none: empty), gray when Link's age cannot wear it
static const struct {
    const char *alt[3], *label;
    bool child, adult;
} kGearSlots[RADIAL_MENU_GEAR_SLOTS] = {
    {{"Weapon_Sword_Kokiri"}, "Kokiri Sword", true, false},
    {{"Weapon_Sword_Master"}, "Master Sword", false, true},
    {{"Weapon_Sword_Biggoron", "Weapon_Sword_Giant", "Weapon_Sword_BrokenGiant"}, "Biggoron's Sword", false, true},
    {{"Armor_Adult_Zora"}, "Zora Tunic", false, true},
    {{"Armor_Adult_Goron"}, "Goron Tunic", false, true},
    {{"Armor_Adult_Normal"}, "Kokiri Tunic", false, true},
    {{"Weapon_Shield_Mirror"}, "Mirror Shield", false, true},
    {{"Weapon_Shield_Hylian"}, "Hylian Shield", true, true},
    {{"Weapon_Shield_Deku"}, "Deku Shield", true, false},
};
// the gear of the slot owned (NULL none), *wearable at Link's age
static const char *gear_slot_owned(int slot, int *wearable) {
    if (slot < 0 || slot >= RADIAL_MENU_GEAR_SLOTS) return NULL;
    char key[128];
    for (int i = 0; i < 3 && kGearSlots[slot].alt[i]; i++) {
        snprintf(key, sizeof key, "IsGet.%s", kGearSlots[slot].alt[i]);
        if (!flag(key)) continue;
        *wearable = radial_menu_child() ? kGearSlots[slot].child : kGearSlots[slot].adult;
        return kGearSlots[slot].alt[i];
    }
    return NULL;
}

static int gear_slot(int slot, RadialMenuSlot *out) {
    int wearable = 0;
    const char *gear = gear_slot_owned(slot, &wearable);
    if (!gear) return 0;
    icon_file(&out->main, gear);
    out->main.gray = !wearable;
    out->now = out->main;
    out->label = item_name_text(gear, kGearSlots[slot].label);
    return 1;
}

int radial_menu_slot(int kind, int slot, RadialMenuSlot *out) {
    memset(out, 0, sizeof *out);
    out->mini_selected = -1, out->count = out->max = -1;
    for (int i = 0; i < 4; i++) out->mini_count[i] = out->mini_max[i] = -1;
    if (kind == RADIAL_MENU_GEAR) return gear_slot(slot, out);
    if (slot < 0 || slot >= RADIAL_MENU_ITEM_SLOTS) return 0;
    int count, owned_idx[4], n_owned;
    const Var *vars = slot_vars(slot, &count);
    const int cur = slot_current(slot, vars, count, owned_idx, &n_owned);
    const char *icon, *label;
    if (cur < 0) {
        if (!kSlots[slot].other_age) return 0;
        const Var *other = radial_menu_child() ? kSlots[slot].adult : kSlots[slot].child;
        for (int i = 0; i < 4 && other[i].alt[0]; i++)
            if (variant(&other[i], &icon, &label)) {
                out->label = item_name_text(icon, label);
                icon_file(&out->main, icon), icon_file(&out->now, icon);
                out->main.gray = out->now.gray = 1;
                return 1;
            }
        return 0;
    }
    const char *value = variant(&vars[owned_idx[cur]], &icon, &label);
    out->label = item_name_text(icon, label);   // (an item's icon is named as the item is)
    out->count = count_of(value, &out->max);   // (the arrows share one count, the bow's)
    icon_file(&out->now, owned_idx[cur] == 0 || !kSlots[slot].arrows ? icon : kArrowIcon[owned_idx[cur] & 3]);
    if (kSlots[slot].arrows && !radial_menu_child()) {   // the bow, its arrows under it, the one in use framed
        icon_file(&out->main, "Weapon_Range_Bow");
        for (int k = 0; k < n_owned; k++) {
            icon_file(&out->mini[out->minis], kArrowIcon[owned_idx[k] & 3]);
            if (k == cur) out->mini_selected = out->minis;
            out->minis++;
        }
        return 1;
    }
    icon_file(&out->main, icon);
    for (int k = 0; k < n_owned && out->minis < 3; k++) {   // the others a tap swaps to
        const char *other = k != cur ? variant(&vars[owned_idx[k]], &icon, &label) : NULL;
        if (other) {
            out->mini_count[out->minis] = count_of(other, &out->mini_max[out->minis]);
            icon_file(&out->mini[out->minis++], icon);
        }
    }
    return 1;
}

int radial_menu_usable(int kind, int slot) {
    RadialMenuSlot s;
    return radial_menu_slot(kind, slot, &s) && !s.now.gray;
}

int radial_menu_can_swap(int kind, int slot) {
    if (kind != RADIAL_MENU_ITEMS || slot < 0 || slot >= RADIAL_MENU_ITEM_SLOTS) return 0;
    int count, owned_idx[4], n_owned;
    const Var *vars = slot_vars(slot, &count);
    return slot_current(slot, vars, count, owned_idx, &n_owned) >= 0 && n_owned >= 2;
}

int radial_menu_tap(int kind, int slot, int dir) {
    if (kind != RADIAL_MENU_ITEMS || slot < 0 || slot >= RADIAL_MENU_ITEM_SLOTS) return 0;
    int count, owned_idx[4], n_owned;
    const Var *vars = slot_vars(slot, &count);
    const int cur = slot_current(slot, vars, count, owned_idx, &n_owned);
    if (cur < 0 || n_owned < 2) return 0;
    const int next = (cur + (dir < 0 ? n_owned - 1 : 1)) % n_owned;
    g_mem[slot].store(owned_idx[next]);
    return next > cur ? 1 : 2;
}

const char *radial_menu_equip(int slot) {
    if (slot < 0 || slot >= RADIAL_MENU_ITEM_SLOTS) return NULL;
    int count, owned_idx[4], n_owned;
    const Var *vars = slot_vars(slot, &count);
    const int cur = slot_current(slot, vars, count, owned_idx, &n_owned);
    const char *icon, *label;
    return cur < 0 ? NULL : variant(&vars[owned_idx[cur]], &icon, &label);
}

void radial_menu_nav_sound(int sound);
void radial_menu_swapped(int kind, int slot, int cw);

RadialMenuCtl::Out RadialMenuCtl::step(int held, bool allowed, const float sticks[2][2], uint64_t, int swap) {
    Out o;
    if (open && !(held & (1 << (open - 1)))) {   // its button let go: the slot held toward used
        if (slot >= 0 && radial_menu_usable(open, slot)) o.used_kind = open, o.used_slot = slot;
        o.closed = true, open = 0;
    }
    if (!open && held && allowed) open = held & 1 ? RADIAL_MENU_GEAR : RADIAL_MENU_ITEMS;
    const int was = slot;
    slot = -1;
    if (!open) return o;
    const int n = radial_menu_slots(open);
    const float sx = sticks[open - 1][0], sy = sticks[open - 1][1];
    if (sx * sx + sy * sy > 0.25f) {
        float a = std::atan2(sx, sy);   // 0 up, clockwise
        if (a < 0) a += 2.0f * 3.14159265f;
        // (the item radial menu's first slot centred at the top; the gear's first starts there: a third's edge at the top)
        slot = (int)std::floor(a / (2.0f * 3.14159265f / n) + (open == RADIAL_MENU_GEAR ? 0.0f : 0.5f)) % n;
    }
    if (const int step = swap && slot >= 0 ? radial_menu_tap(open, slot, swap) : 0) radial_menu_nav_sound(4), radial_menu_swapped(open, slot, step == 1);
    else if (slot >= 0 && slot != was) radial_menu_nav_sound(3);
    return o;
}

// ---- the D-pad's gear: the Equipment page's, put on as its PlayerStatus member (host/radial_menu_game.c)

namespace {
struct Gear {
    const char *name, *member;
    bool child, adult;
};
const Gear kGear[] = {
    {"Weapon_Sword_Kokiri", "EquipWeapon", true, false},     {"Weapon_Sword_Master", "EquipWeapon", false, true},
    {"Weapon_Sword_Giant", "EquipWeapon", false, true},      {"Weapon_Sword_BrokenGiant", "EquipWeapon", false, true},
    {"Weapon_Sword_Biggoron", "EquipWeapon", false, true},   {"Weapon_Shield_Deku", "EquipShield", true, false},
    {"Weapon_Shield_Hylian", "EquipShield", true, true},     {"Weapon_Shield_Mirror", "EquipShield", false, true},
    {"Armor_Adult_Normal", "EquipArmor", false, true},       {"Armor_Adult_Goron", "EquipArmor", false, true},
    {"Armor_Adult_Zora", "EquipArmor", false, true},         {"Armor_Adult_HeavyBoot", "EquipBoot", false, true},
    {"Armor_Adult_HoverBoot", "EquipBoot", false, true},     {"Armor_GlassTruth", "EquipHeadArmor", true, true},
    {"Armor_Child_Mask_Keaton", "EquipHeadArmor", true, true}, {"Armor_Child_Mask_Skull", "EquipHeadArmor", true, true},
    {"Armor_Child_Mask_Spooky", "EquipHeadArmor", true, true}, {"Armor_Child_Mask_Bunny", "EquipHeadArmor", true, true},
    {"Armor_Child_Mask_Goron", "EquipHeadArmor", true, true},  {"Armor_Child_Mask_Zora", "EquipHeadArmor", true, true},
    {"Armor_Child_Mask_Gerudo", "EquipHeadArmor", true, true}, {"Armor_Child_Mask_Truth", "EquipHeadArmor", true, true},
    {"Armor_Child_Mask_Amiibo0", "EquipHeadArmor", true, true}, {"Armor_Child_Mask_Amiibo1", "EquipHeadArmor", true, true},
};
constexpr int kGearBase = 100, kGearN = (int)(sizeof kGear / sizeof *kGear);
// (owned, and Link's age can wear it)
const Gear *gear_usable(int stored) {
    if (stored < kGearBase || stored >= kGearBase + kGearN) return nullptr;
    const Gear *g = &kGear[stored - kGearBase];
    const Item *it = item_of(g->name);   // (a mask: the one held, OWN_HELD)
    const char *icon, *label;
    if (it ? !owned(it, &icon, &label) : !flag((std::string("IsGet.") + g->name).c_str())) return nullptr;
    return (radial_menu_child() ? g->child : g->adult) ? g : nullptr;
}
}   // namespace

// ---- the D-pad's items' store (radial_menu.h): each direction keeps an item by its key, the first of its variant's values
// (the Hookshot's and the Longshot's "Longshot", the ocarinas' "Item_Ocarina_Time", the masks' the first mask: the one held
// is used), or a gear's name; so an item is on one direction alone however it was put there (a radial menu, a page)

namespace {
int gear_index(const char *name) {
    for (int i = 0; name && i < kGearN; i++)
        if (!strcmp(kGear[i].name, name)) return i;
    return -1;
}
// (a variant of either age that has the value: its key)
const char *var_key(const char *value) {
    for (int age = 0; age < 2; age++)
        for (int slot = 0; slot < RADIAL_MENU_ITEM_SLOTS; slot++) {
            const Var *vars = age == 0 ? kSlots[slot].child : kSlots[slot].adult;
            for (int v = 0; v < 4 && vars[v].alt[0]; v++)
                for (int k = 0; k < ALTS && vars[v].alt[k]; k++)
                    if (!strcmp(vars[v].alt[k], value)) return vars[v].alt[0];
        }
    return nullptr;
}
// (a variant of Link's age now has the value)
bool in_age(const char *value) {
    const bool child = radial_menu_child() != 0;
    for (int slot = 0; slot < RADIAL_MENU_ITEM_SLOTS; slot++) {
        const Var *vars = child ? kSlots[slot].child : kSlots[slot].adult;
        for (int v = 0; v < 4 && vars[v].alt[0]; v++)
            for (int k = 0; k < ALTS && vars[v].alt[k]; k++)
                if (!strcmp(vars[v].alt[k], value)) return true;
    }
    return false;
}
const char *key_of(const char *value) {
    if (!value || !*value) return nullptr;
    if (const char *k = var_key(value)) return k;
    return gear_index(value) >= 0 ? kGear[gear_index(value)].name : nullptr;
}
// (the bow and its arrows: one of them on the D-pad, as the bow fires one kind at a time)
bool arrow_key(const char *k) {
    return k && (!strcmp(k, "Bow") || !strcmp(k, "FireArrow") || !strcmp(k, "IceArrow") || !strcmp(k, "LightArrow"));
}
// (each age its own four: [0] the child's, [1] the adult's. With no file yet the adult's down holds the bombs, as the N64's
// C-down did)
std::mutex g_dpad_mu;
std::string g_dpad[2][4];
std::once_flag g_dpad_read;
int dpad_age() { return radial_menu_child() ? 0 : 1; }
void dpad_load() {
    std::call_once(g_dpad_read, [] {
        std::lock_guard<std::mutex> lk(g_dpad_mu);
        FILE *f = fopen(menu_radial_dpad_path(), "rb");
        if (!f) {
            g_dpad[1][2] = "Bomb";
            return;
        }
        char line[128];
        int n = 0;
        for (; n < 8 && fgets(line, sizeof line, f); n++) {
            line[strcspn(line, "\r\n")] = 0;
            const char *k = key_of(line);   // (a key no item has: none)
            g_dpad[n / 4][n % 4] = k ? k : "";
        }
        fclose(f);
        if (n <= 4) g_dpad[1][2] = "Bomb";   // (a file of one set, from before the ages kept their own: the child's)
    });
}
void dpad_save() {   // (written whole beside it and put in its place; the caller holds g_dpad_mu)
    const std::string path = menu_radial_dpad_path(), fresh = path + ".new";
    FILE *f = fopen(fresh.c_str(), "wb");
    if (!f) return;
    bool ok = true;
    for (int n = 0; n < 8; n++) ok = fprintf(f, "%s\n", g_dpad[n / 4][n % 4].empty() ? "-" : g_dpad[n / 4][n % 4].c_str()) > 0 && ok;
    if (fclose(f) == 0 && ok) {
        remove(path.c_str());
        if (rename(fresh.c_str(), path.c_str()) == 0) return;
    }
    remove(fresh.c_str());
}
// (an item on one direction of Link's age's alone: put where another direction had it, the two swap (what this one held goes
// there); NULL empties the direction. None with the Assignable D-Pad off, nor on up with Navi there)
bool dpad_put(int dir, const char *key) {
    const int mode = radial_menu_dpad_mode();
    if (!mode || (mode == 1 && dir == 0)) return false;
    dpad_load();
    const int age = dpad_age();
    std::lock_guard<std::mutex> lk(g_dpad_mu);
    std::string *set = g_dpad[age];
    for (int d = 0; key && d < 4; d++)
        if (d != dir && (set[d] == key || (arrow_key(key) && arrow_key(set[d].c_str())))) set[d] = set[dir];
    set[dir] = key ? key : "";
    dpad_save();
    return true;
}
std::string dpad_key(int dir) {
    dpad_load();
    const int age = dpad_age();
    std::lock_guard<std::mutex> lk(g_dpad_mu);
    return g_dpad[age][dir];
}
// (the N64's bag glitches kept possible: the bombs and bombchus with a bomb bag, the bow and its arrows with a quiver, are the
// D-pad's to use without the item itself got; the game decides what then happens)
bool bag_held(const std::string &k) {
    const char *bag = k == "Bomb" || k == "Bombchu" ? "BombBag" : arrow_key(k.c_str()) ? "Quiver" : nullptr;
    if (!bag) return false;
    for (const char *size : {"Small", "Medium", "Large"})
        if (flag((std::string("IsGet.Item_") + bag + "_" + size).c_str())) return true;
    return false;
}
// (the direction's item: 1 owned and Link's age's (*value the variant owned best), 2 not usable now (not owned, or the other
// age's): shown gray, by the owned one's icon or else the item's own; 0 none or no item's key)
int dpad_item(int dir, const char **value, const char **icon, const char **label) {
    const std::string k = dpad_key(dir);
    *value = nullptr;
    if (k.empty()) return 0;
    const bool child = radial_menu_child() != 0;
    const Item *any = nullptr;
    for (int pass = 0; pass < 2; pass++)
        for (int slot = 0; slot < RADIAL_MENU_ITEM_SLOTS; slot++) {
            const Var *vars = (pass == 0) == child ? kSlots[slot].child : kSlots[slot].adult;
            for (int v = 0; v < 4 && vars[v].alt[0]; v++) {
                if (k != vars[v].alt[0]) continue;
                if (const char *owned_value = variant(&vars[v], icon, label)) {
                    if (pass == 0) return *value = owned_value, 1;
                    return 2;
                }
                if (pass == 0 && bag_held(k))
                    if (const Item *it = item_of(vars[v].alt[0])) return *value = it->value, *icon = it->name, *label = it->label, 1;
                if (!any) any = item_of(vars[v].alt[0]);
            }
        }
    if (!any) return 0;
    *icon = any->own == OWN_BOTTLE ? kBottle[0][1] : any->name, *label = any->label;
    return 2;
}
constexpr int kDpadBit[4] = {13, 14, 15, 12};   // (the game's pad: Up, Right, Down, Left)
}   // namespace

// ---- the radial menus' state: the gamepad's (radial_menu_pad, the game's pad thread) and another input's (radial_menu_external)

namespace {
uint64_t radial_now_ns() {
    return (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}
struct Menus {
    std::mutex mu;
    RadialMenuCtl pad;
    int ext_open = 0, ext_slot = -1;
    uint64_t ext_at = 0;   // (when the other input last said: one gone quiet a quarter second is taken as closed)
    int used_kind = 0, used_slot = -1;
    bool allowed = false;
    uint64_t closed_at = 0;
    uint64_t dpad_was = 0;   // (the D-pad held at the last read while a radial menu was open)
    bool zl_was = false, zr_was = false;
};
Menus &menus() {
    static Menus w;
    return w;
}
// the game's pad: L 6, R 7 (kept the game's while a radial menu is open: its sequence's item bar stays open, paused)
constexpr int kL = 6, kR = 7, kZL = 8, kZR = 9;

// the last put's flight to its direction (radial_menu_dpad_fly): from the item radial menu's slot, or from a point of the
// pause menu's layout
struct Fly {
    int dir = -1, radial_kind = 0, radial_slot = -1;
    bool from_layout = false;
    float x = 0, y = 0;
    uint64_t at = 0;
};
std::mutex g_fly_mu;
Fly g_fly;
std::atomic<int> g_put_sound{0};   // (a put not sounded yet, 1, or a refused one, 2: radial_menu_take_put_sound)
std::atomic<int> g_nav_sound{0};   // (a slot picked, 3, or its variants stepped, 4)
constexpr uint64_t kFlyNs = 350000000ull;
// (a refused put's shake of its radial menu slot, as the pause menu shakes an item it cannot equip)
std::atomic<int> g_shake_kind{0}, g_shake_slot{-1};
std::atomic<uint64_t> g_shake_at{0};
constexpr uint64_t kShakeNs = 300000000ull;
std::atomic<int> g_swap_kind{0}, g_swap_slot{-1}, g_swap_cw{0};
std::atomic<uint64_t> g_swap_at{0};
constexpr uint64_t kSwapNs = 260000000ull;
void put_refused(int radial_kind, int radial_slot) {
    g_put_sound.store(2, std::memory_order_release);
    if (radial_kind && radial_slot >= 0)
        g_shake_slot.store(radial_slot), g_shake_kind.store(radial_kind), g_shake_at.store(radial_now_ns());
}
void fly_start(int dir, int radial_kind, int radial_slot, bool from_layout, float x, float y) {
    g_put_sound.store(1, std::memory_order_release);
    std::lock_guard<std::mutex> lk(g_fly_mu);
    g_fly.dir = dir, g_fly.radial_kind = radial_kind, g_fly.radial_slot = radial_slot, g_fly.from_layout = from_layout;
    g_fly.x = x, g_fly.y = y;
    g_fly.at = radial_now_ns();
}
}   // namespace

void radial_menu_swapped(int kind, int slot, int cw) {
    g_swap_cw.store(cw), g_swap_slot.store(slot), g_swap_kind.store(kind), g_swap_at.store(radial_now_ns());
}
int radial_menu_swap_anim(int kind, int slot, float *t, uint64_t *id, int *cw) {
    if (g_swap_kind.load() != kind || g_swap_slot.load() != slot) return 0;
    const uint64_t at = g_swap_at.load(), now = radial_now_ns();
    if (!at || now - at >= kSwapNs) return 0;
    *t = (float)(now - at) / (float)kSwapNs, *id = at, *cw = g_swap_cw.load();
    return 1;
}
int radial_menu_take_put_sound(void) {
    const int put = g_put_sound.exchange(0, std::memory_order_acq_rel);
    return put ? put : g_nav_sound.exchange(0, std::memory_order_acq_rel);
}
void radial_menu_nav_sound(int sound) { g_nav_sound.store(sound, std::memory_order_release); }

int radial_menu_shake(int kind, int slot, float *t) {
    if (g_shake_kind.load() != kind || g_shake_slot.load() != slot) return 0;
    const uint64_t at = g_shake_at.load(), now = radial_now_ns();
    if (!at || now - at >= kShakeNs) return 0;
    *t = (float)(now - at) / (float)kShakeNs;
    return 1;
}

int radial_menu_dpad_fly(int *dir, int *radial_kind, int *radial_slot, int *from_layout, float *x, float *y, float *t) {
    std::lock_guard<std::mutex> lk(g_fly_mu);
    const uint64_t now = radial_now_ns();
    if (g_fly.dir < 0 || now - g_fly.at >= kFlyNs) return 0;
    *dir = g_fly.dir, *radial_kind = g_fly.radial_kind, *radial_slot = g_fly.radial_slot, *from_layout = g_fly.from_layout;
    *x = g_fly.x, *y = g_fly.y;
    *t = (float)(now - g_fly.at) / (float)kFlyNs;
    return 1;
}

int radial_menu_pad(uint64_t *buttons, int32_t left[2], int32_t right[2], int want) {
    Menus &w = menus();
    const uint64_t now = radial_now_ns();
    std::lock_guard<std::mutex> lk(w.mu);
    w.allowed = want != 0;
    if ((w.ext_open && now - w.ext_at < 250000000ull) || !menu_radial_menus()) {   // (another input's radial menu open, or the row off: the gamepad's stays shut)
        if (w.pad.open) w.closed_at = now;
        w.pad.reset();
        return 0;
    }
    const int held = want == RADIAL_MENU_GEAR ? 1 : want == RADIAL_MENU_ITEMS ? 2 : 0;
    // (the right stick picks for both: the left thumb stays on the D-pad, to put what it points at there)
    const float rx = right[0] / 32767.0f, ry = right[1] / 32767.0f, sticks[2][2] = {{rx, ry}, {rx, ry}};
    // (ZR steps the picked slot's variants on, ZL back)
    const bool zl = *buttons >> kZL & 1, zr = *buttons >> kZR & 1;
    const int swap = !w.pad.open ? 0 : zr && !w.zr_was ? 1 : zl && !w.zl_was ? -1 : 0;
    w.zl_was = zl, w.zr_was = zr;
    const RadialMenuCtl::Out o = w.pad.step(held, w.allowed, sticks, now, swap);
    if (o.closed) w.closed_at = now;
    if (o.used_kind) w.used_kind = o.used_kind, w.used_slot = o.used_slot;
    if (!w.pad.open) {
        w.dpad_was = 0;
        return 0;
    }
    {   // (a D-pad press while a radial menu is open: the item the stick points at put on that direction (the variant shown,
        // the gear's as its gear); the stick at no slot does nothing; a slot with nothing usable (empty, gray) is refused)
        const uint64_t dpad = *buttons & (0xfull << 12), pressed = dpad & ~w.dpad_was;
        w.dpad_was = dpad;
        for (int d = 0; d < 4; d++) {
            if (!(pressed >> kDpadBit[d] & 1)) continue;
            const int open = w.pad.open, slot = w.pad.slot;
            const char *member, *value = nullptr;
            if (slot >= 0 && radial_menu_usable(open, slot))
                value = open == RADIAL_MENU_GEAR ? radial_menu_gear_equip(slot, &member) : radial_menu_equip(slot);
            if (slot < 0) continue;   // (the stick at no slot: nothing; a direction is never emptied, as the N64's C buttons)
            if (!key_of(value)) put_refused(open, slot);
            else if (dpad_put(d, key_of(value))) fly_start(d, open, slot, false, 0, 0);
        }
    }
    // (while open the game gets its L or R alone, which keeps its own item bar open and the game paused: no stick, D-pad or
    // other button, so the bar behind stays on the item equipped and its release changes nothing; the slot picked is
    // equipped after it)
    *buttons &= 1ull << kL | 1ull << kR;
    left[0] = left[1] = right[0] = right[1] = 0;
    return 1;
}

int radial_menu_used(int *kind, int *slot) {
    Menus &w = menus();
    std::lock_guard<std::mutex> lk(w.mu);
    if (!w.used_kind) return 0;
    *kind = w.used_kind, *slot = w.used_slot, w.used_kind = 0;
    return 1;
}

int radial_menu_open(int *slot) {
    Menus &w = menus();
    std::lock_guard<std::mutex> lk(w.mu);
    if (w.ext_open && radial_now_ns() - w.ext_at < 250000000ull) return *slot = w.ext_slot, w.ext_open;
    *slot = w.pad.slot;
    return w.pad.open;
}

int radial_menu_allowed(void) {
    Menus &w = menus();
    std::lock_guard<std::mutex> lk(w.mu);
    return w.allowed;
}

uint64_t radial_menu_closed_at(void) {
    Menus &w = menus();
    std::lock_guard<std::mutex> lk(w.mu);
    return w.closed_at;
}

void radial_menu_external(int open, int slot) {
    Menus &w = menus();
    std::lock_guard<std::mutex> lk(w.mu);
    if (w.ext_open && !open) w.closed_at = radial_now_ns();
    w.ext_open = open, w.ext_slot = open ? slot : -1, w.ext_at = radial_now_ns();
}

void radial_menu_external_used(int kind, int slot) {
    Menus &w = menus();
    std::lock_guard<std::mutex> lk(w.mu);
    w.used_kind = kind, w.used_slot = slot;
}

// ---- the D-pad's items (radial_menu.h)

const char *radial_menu_dpad_equip(int dir) {
    if (dir < 0 || dir > 3) return NULL;
    const char *value, *icon, *label;
    return dpad_item(dir, &value, &icon, &label) == 1 ? value : NULL;
}

const char *radial_menu_dpad_gear(int dir, const char **member) {
    if (dir < 0 || dir > 3) return NULL;
    const Gear *g = gear_usable(kGearBase + gear_index(dpad_key(dir).c_str()));
    if (!g) return NULL;
    if (member) *member = g->member;
    return g->name;
}

int radial_menu_dpad_icon(int dir, RadialMenuTex *out, int *count, int *max) {
    *count = *max = -1;
    if (dir < 0 || dir > 3) return 0;
    const char *value, *icon, *label;
    if (const int got = dpad_item(dir, &value, &icon, &label)) {
        icon_file(out, icon);
        out->gray = got == 2;
        if (got == 1) *count = count_of(value, max);
        return 1;
    }
    const int gi = gear_index(dpad_key(dir).c_str());
    if (gi < 0) return 0;
    icon_file(out, kGear[gi].name);
    out->gray = !gear_usable(kGearBase + gi);   // (not owned, or not Link's age's)
    return 1;
}

namespace mkwvk {
extern std::atomic<int64_t> world_drawn_at;   // (vk_draw.cpp: the last present that drew the world)
extern int64_t presents_now;                  // (vk_replay.cpp)
}

// (in play: Link there, the world drawn (not a loading screen or a movie), no pause, no event (a cutscene, a conversation))
static bool in_play() {
    if (!gw() || !oot_data_player(gw())) return false;
    if (mkwvk::presents_now - mkwvk::world_drawn_at.load(std::memory_order_relaxed) > 3) return false;
    int on = 0;
    for (const char *f : {"Sequence_IsPause", "Sequence_IsPreGamePause", "Sequence_IsPostGamePause"})
        if (dbg_flag_get(f, &on) && on) return false;
    // (an event running: the event manager's singleton, main+0x4c7e090, its manager's +104)
    const uint64_t singleton = oot_data_ptr(gw(), OOT_DATA_MAIN + 0x4c7e090), events = singleton ? oot_data_ptr(gw(), singleton) : 0;
    return !(events && oot_data_ptr(gw(), events + 104));
}

int radial_menu_dpad_hud(void) {
    if (!radial_menu_dpad_mode()) return 0;   // (the game's own D-pad)
    // (shown once play has gone on 0.5 s: not over a loading screen's end or a cutscene's)
    // (a radial menu's pause, to the game running again after it, is play's: the 2 s are not waited again)
    static uint64_t play_since;
    static bool radial_pause;
    const uint64_t now = radial_now_ns();
    int slot;
    if (radial_menu_open(&slot)) radial_pause = true;
    if (!in_play()) {
        if (!radial_pause) play_since = 0;
        return 0;
    }
    radial_pause = false;
    if (!play_since) play_since = now;
    return now - play_since >= 500000000ull;
}

namespace {
std::atomic<int> g_menu_page{-1};
}
void radial_menu_menu_page(int page) { g_menu_page.store(page); }
int radial_menu_menu_page_now(void) { return radial_menu_dpad_mode() ? g_menu_page.load() : -1; }

int radial_menu_dpad_put_item(int dir, const char *item, int from_layout, float x, float y) {
    if (dir < 0 || dir > 3 || !item) return 0;
    // (the page's item's name: a gear's, an item's (its value then), a bottle's place; Link's age's alone, and owned, as its
    // radial menu would show it, the other age's refused)
    const char *value = nullptr, *icon, *label;
    const int gi = gear_index(item);
    if (gi >= 0 && !item_of(item)) {
        if (gear_usable(kGearBase + gi)) value = kGear[gi].name;
    } else {
        const Item *it = nullptr;
        for (size_t i = 0; i < sizeof kItems / sizeof *kItems && !it; i++)
            if (!strcmp(kItems[i].name, item) || !strcmp(kItems[i].value, item)) it = &kItems[i];
        if (it && owned(it, &icon, &label) && in_age(it->value) && (gi < 0 || gear_usable(kGearBase + gi)))
            value = it->value;
    }
    const char *key = key_of(value);
    if (!key) return put_refused(0, -1), 0;
    if (!dpad_put(dir, key)) return 0;
    fly_start(dir, 0, -1, from_layout != 0, x, y);
    return 1;
}

const char *radial_menu_gear_member(const char *name) {
    const int i = gear_index(name);
    return i < 0 ? NULL : kGear[i].member;
}

const char *radial_menu_gear_equip(int slot, const char **member) {
    int wearable = 0;
    const char *gear = gear_slot_owned(slot, &wearable);
    if (!gear || !wearable) return NULL;
    if (member) *member = radial_menu_gear_member(gear);
    return gear;
}

// the game's side's table (vk_api.h MkwVkRadialMenu)
const MkwVkRadialMenu *radial_menu_table(void) {
    static const MkwVkRadialMenu t = {radial_menu_pad,  radial_menu_used,  radial_menu_equip,
                                      radial_menu_open, menu_radial_menus, radial_menu_dpad_equip,
                                      radial_menu_menu_page, radial_menu_dpad_put_item, radial_menu_dpad_gear,
                                      radial_menu_dpad_mode, radial_menu_gear_member, radial_menu_gear_equip};
    return &t;
}
