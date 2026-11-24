/* (Triforce) Achievements: what one is, the list's text, when one is earned, and the file that keeps the earned ones.
   host/achievements.c has what is the game folder's and the screen's; host/hos_main.c asks the game. Nothing of the host is
   in here: tests/test_achievements.py compiles it alone.

   An achievement has a name, a line about it, and one to ACH_CONDS conditions, all of which must hold:
     item <pouch name> [<least>]   Link has that item, <least> of it or more (1 without a number)
     flag <name>                   that flag of the game's save data is set
   The list is text:
     # a comment
     [A Sword of Your Own]
     about: Find a blade in the forest.
     icon: sword green
     item Weapon_Sword_Kokiri
   (icon: its picture on the Achievements page and in its notice, a shape and a tone the menu draws: ach_icon below.)
   ACH_BUILTIN below is the list every game has. Its conditions are items only, by the pouch names gpu/vk/oot_cheat_items.h
   already has for the Inventory page: no other name of the game's is in this file, and none of its flags' names (the
   Debug tab reads those from the player's own game files). A player's own list, achievements.txt beside the game, is read
   after it in the same form, and may ask for flags by the names the Game flags page shows.

   An achievement is earned once, for the game folder and not for a save slot, and stays earned: triforce_achievements.txt
   has a line for each, "<key> <unix time> <name>", the key the FNV-1a 32 of the name. A line whose achievement the lists
   no longer have is kept as it is, so that a list taken away and put back loses nothing. */
#ifndef HOS_ACHIEVEMENTS_H
#define HOS_ACHIEVEMENTS_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { ACH_MAX = 128, ACH_CONDS = 16, ACH_NAME = 40 /* (a name's bytes: gpu/vk/achievement_rows.h kName holds it whole) */, ACH_ABOUT = 160,
       ACH_WHAT = 96 /* (a flag's or an item's name: gpu/vk/oot_debug_link.h OOT_NAME_MAX and its end) */, ACH_ORPHANS = 64,
       ACH_LINE = 256 };
enum { ACH_ITEM = 'I', ACH_FLAG = 'F' };

typedef struct AchCond {
    int kind;              /* ACH_ITEM or ACH_FLAG */
    int least;             /* ACH_ITEM: how many of it */
    char what[ACH_WHAT];
} AchCond;
typedef struct Ach {
    char name[ACH_NAME + 1], about[ACH_ABOUT + 1];
    uint32_t key;
    int icon;              /* its picture: a shape and a tone, ach_icon */
    AchCond conds[ACH_CONDS];
    int nconds;
    int earned;
    int64_t when;          /* unix time it was earned, 0 not known */
} Ach;
typedef struct AchList {
    Ach a[ACH_MAX];
    int n;
    char orphans[ACH_ORPHANS][ACH_LINE];   /* (the earned file's lines of achievements no list has now) */
    int norphans;
} AchList;

/* What the game's save data has of a condition's name: an item's count, a flag's 1 or 0; -1 it has no such name */
typedef int (*AchProbe)(void *ctx, int kind, const char *what);

#define ACH_BUILTIN \
    "[A Sword of Your Own]\nabout: Find a blade in the forest.\nicon: sword green\nitem Weapon_Sword_Kokiri\n" \
    "[First Melody]\nabout: Learn the royal family's song.\nicon: note\nitem Item_Melody_ZeldaLullaby\n" \
    "[Forest's Thanks]\nabout: Earn the first Spiritual Stone.\nicon: gem green\nitem Item_Stone_Forest\n" \
    "[Heart of the Mountain]\nabout: Earn the second Spiritual Stone.\nicon: gem red\nitem Item_Stone_Fire\n" \
    "[Jewel of the River]\nabout: Earn the third Spiritual Stone.\nicon: gem blue\nitem Item_Stone_Water\n" \
    "[Three Stones]\nabout: Hold all three Spiritual Stones.\nicon: gem\nitem Item_Stone_Forest\nitem Item_Stone_Fire\nitem Item_Stone_Water\n" \
    "[Seven Years Later]\nabout: Draw the blade from its pedestal.\nicon: sword blue\nitem Weapon_Sword_Master\n" \
    "[Sage of Forest]\nabout: Earn the Forest Medallion.\nicon: medal green\nitem Item_Medal_Forest\n" \
    "[Sage of Fire]\nabout: Earn the Fire Medallion.\nicon: medal red\nitem Item_Medal_Fire\n" \
    "[Sage of Water]\nabout: Earn the Water Medallion.\nicon: medal blue\nitem Item_Medal_Water\n" \
    "[Sage of Shadow]\nabout: Earn the Shadow Medallion.\nicon: medal purple\nitem Item_Medal_Shadow\n" \
    "[Sage of Spirit]\nabout: Earn the Spirit Medallion.\nicon: medal orange\nitem Item_Medal_Spirit\n" \
    "[Sage of Light]\nabout: Earn the Light Medallion.\nicon: medal yellow\nitem Item_Medal_Light\n" \
    "[Six Awakened]\nabout: Hold all six medallions.\nicon: medal\nitem Item_Medal_Forest\nitem Item_Medal_Fire\nitem Item_Medal_Water\n" \
    "item Item_Medal_Shadow\nitem Item_Medal_Spirit\nitem Item_Medal_Light\n" \
    "[Full Songbook]\nabout: Learn all twelve songs.\nicon: note yellow\nitem Item_Melody_ZeldaLullaby\nitem Item_Melody_EponaSong\n" \
    "item Item_Melody_SariaSong\nitem Item_Melody_SunSong\nitem Item_Melody_TimeSong\nitem Item_Melody_StormSong\n" \
    "item Item_Melody_ForestMinuet\nitem Item_Melody_FireBolero\nitem Item_Melody_WaterSerenade\n" \
    "item Item_Melody_ShadowNocturne\nitem Item_Melody_SpiritRequiem\nitem Item_Melody_LightPrelude\n" \
    "[Spider Hunter]\nabout: Collect 10 Gold Skulltula Tokens.\nicon: token orange\nitem Item_Token_Gold 10\n" \
    "[Spider Slayer]\nabout: Collect 50 Gold Skulltula Tokens.\nicon: token silver\nitem Item_Token_Gold 50\n" \
    "[Curse Broken]\nabout: Collect all 100 Gold Skulltula Tokens.\nicon: token\nitem Item_Token_Gold 100\n" \
    "[Long Reach]\nabout: Find the Longshot.\nicon: star blue\nitem Item_Longshot\n" \
    "[Seeing Clearly]\nabout: Find the Lens of Truth.\nicon: star purple\nitem Armor_GlassTruth\n" \
    "[Honest Face]\nabout: Earn the Mask of Truth.\nicon: star orange\nitem Armor_Child_Mask_Truth\n" \
    "[A Giant's Blade]\nabout: Earn Biggoron's Sword.\nicon: sword\nitem Weapon_Sword_Biggoron\n" \
    "[Deep Pockets]\nabout: Carry the Giant's Wallet.\nicon: token green\nitem Item_Wallet_Large\n" \
    "[Light Against the Dark]\nabout: Receive the Light Arrow.\nicon: star yellow\nitem Item_Arrow_Light\n" \
    "[Twice as Tough]\nabout: Receive Double Defense.\nicon: shield silver\nitem Item_FairyBless_DefenseDouble\n" \
    "[Honorary Thief]\nabout: Be handed the Gerudo's Card.\nicon: star red\nitem Item_Token_Gerudo\n" \
    "[Read the Fine Print]\nabout: Buy a blade that will not last.\nicon: sword silver\nitem Weapon_Sword_Giant\n" \
    "[Something's Buzzing]\nabout: Receive the Stone of Agony.\nicon: gem silver\nitem Item_AgonyStone\n" \
    "[Fashion Victim]\nabout: Own both tunics and both pairs of boots.\nicon: shield red\nitem Armor_Adult_Goron\nitem Armor_Adult_Zora\n" \
    "item Armor_Adult_HeavyBoot\nitem Armor_Adult_HoverBoot\n" \
    "[Jack]\nabout: Carry 10 Magic Beans at once.\nicon: star green\nitem Item_MagicBean 10\n" \
    "[Going Nuts]\nabout: Carry 40 Deku Nuts.\nicon: star orange\nitem Item_DekuNut 40\n" \
    "[Demolition Permit]\nabout: Carry 40 Bombs and 50 Bombchus.\nicon: shield orange\nitem Item_Bomb 40\nitem Item_Bombchu 50\n" \
    "[Three Goddesses]\nabout: Receive Din's Fire, Farore's Wind and Nayru's Love.\nicon: gem yellow\nitem Item_DinFire\n" \
    "item Item_FaroreWind\nitem Item_NayruLove\n" \
    "[Rain Dance]\nabout: Learn the Song of Storms.\nicon: note blue\nitem Item_Melody_StormSong\n" \
    "[Deep End]\nabout: Earn the Golden Scale.\nicon: shield blue\nitem Item_Scale_Gold\n"

/* FNV-1a 32 of a name's bytes */
static inline uint32_t ach_key(const char *name) {
    uint32_t h = 2166136261u;
    for (const unsigned char *p = (const unsigned char *)name; *p; p++) h = (h ^ *p) * 16777619u;
    return h;
}

/* a character of a flag's or an item's name, as the game's are: letters, digits, _ . and - */
static inline int ach_what_char(int ch) {
    return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '_' || ch == '.' || ch == '-';
}

static inline int ach_find(const AchList *l, uint32_t key) {
    for (int i = 0; i < l->n; i++)
        if (l->a[i].key == key) return i;
    return -1;
}

/* a line's text between its blanks: its start, and its length through *n */
static inline const char *ach_trim(const char *s, size_t *n) {
    while (*n && (*s == ' ' || *s == '\t')) s++, (*n)--;
    while (*n && (s[*n - 1] == ' ' || s[*n - 1] == '\t' || s[*n - 1] == '\r')) (*n)--;
    return s;
}

/* An achievement's picture, drawn by the menu and not a file (gpu/vk/achievement_rows.h has the same shapes and tones in
   the same order, and draws them): a shape in the low four bits, a tone in the next four. "icon: <shape> [<tone>]" in
   a list; without the line, a gold star */
#define ACH_SHAPES "star", "sword", "gem", "medal", "note", "token", "shield"
#define ACH_TONES "gold", "green", "red", "blue", "purple", "orange", "yellow", "silver"
static inline int ach_icon(int shape, int tone) { return shape | tone << 4; }

/* the words after "icon:" read: the icon, -1 when they are not a shape and at most a tone */
static inline int ach_icon_parse(const char *s, size_t n) {
    static const char *const shapes[] = {ACH_SHAPES}, *const tones[] = {ACH_TONES};
    size_t w = 0;
    while (w < n && s[w] != ' ' && s[w] != '\t') w++;
    int shape = -1, tone = 0;
    for (size_t i = 0; i < sizeof shapes / sizeof shapes[0]; i++)
        if (strlen(shapes[i]) == w && !memcmp(shapes[i], s, w)) shape = (int)i;
    if (shape < 0) return -1;
    size_t rest = n - w;
    const char *t = ach_trim(s + w, &rest);
    if (!rest) return ach_icon(shape, 0);
    tone = -1;
    for (size_t i = 0; i < sizeof tones / sizeof tones[0]; i++)
        if (strlen(tones[i]) == rest && !memcmp(tones[i], t, rest)) tone = (int)i;
    return tone < 0 ? -1 : ach_icon(shape, tone);
}

/* A condition's line read ("item <name> [<least>]", "flag <name>"): 1 when it is one */
static inline int ach_cond_parse(const char *s, size_t n, AchCond *out) {
    memset(out, 0, sizeof *out);
    if (n < 6 || (memcmp(s, "item", 4) && memcmp(s, "flag", 4)) || (s[4] != ' ' && s[4] != '\t')) return 0;
    out->kind = s[0] == 'i' ? ACH_ITEM : ACH_FLAG;
    out->least = 1;
    size_t at = 4, w = 0;
    while (at < n && (s[at] == ' ' || s[at] == '\t')) at++;
    while (at < n && ach_what_char((unsigned char)s[at])) {
        if (w + 1 >= ACH_WHAT) return 0;
        out->what[w++] = s[at++];
    }
    if (!w) return 0;
    if (at == n) return 1;
    if (out->kind != ACH_ITEM || (s[at] != ' ' && s[at] != '\t')) return 0;
    while (at < n && (s[at] == ' ' || s[at] == '\t')) at++;
    int least = 0, digits = 0;
    for (; at < n && s[at] >= '0' && s[at] <= '9' && digits < 5; at++, digits++) least = least * 10 + (s[at] - '0');
    if (!digits || at != n || least < 1 || least > 9999) return 0;
    out->least = least;
    return 1;
}

/* A list's text added to the list. An achievement is taken whole or not at all: one with a line that is none of the
   form's, without a condition, with more than ACH_CONDS, with a name that is empty, too long or another's, or past
   ACH_MAX is left out, and counted in *refused (may be NULL). Returns how many were added */
static inline int ach_parse(AchList *l, const char *text, int *refused) {
    int added = 0, bad = 0, open = 0, broken = 0;
    static Ach cur;   /* (too large for a guest worker's stack; the lists are read by one thread, at the first check) */
    for (const char *line = text; ; ) {
        const char *end = line;
        while (*end && *end != '\n') end++;
        size_t n = (size_t)(end - line);
        const char *s = ach_trim(line, &n);
        const int head = n && s[0] == '[';
        if (open && (head || (!*end && !n))) {   /* (the achievement before this line is whole now) */
            if (broken || !cur.nconds || ach_find(l, cur.key) >= 0 || l->n >= ACH_MAX) bad++;
            else l->a[l->n++] = cur, added++;
            open = 0;
        }
        if (head) {
            memset(&cur, 0, sizeof cur);
            open = 1, broken = 0;
            size_t nn = s[n - 1] == ']' ? n - 2 : 0;
            const char *name = ach_trim(s + 1, &nn);
            if (!nn || nn > ACH_NAME) broken = 1;
            else {
                memcpy(cur.name, name, nn);
                for (size_t i = 0; i < nn; i++)
                    if ((unsigned char)cur.name[i] < 32) broken = 1;
                cur.key = ach_key(cur.name);
            }
        } else if (open && n && s[0] != '#') {   /* (a line before the first name is not an achievement's) */
            AchCond c;
            if (n >= 6 && !memcmp(s, "about:", 6)) {
                size_t an = n - 6;
                const char *a = ach_trim(s + 6, &an);
                if (an > ACH_ABOUT) broken = 1;
                else memcpy(cur.about, a, an), cur.about[an] = 0;
            } else if (n >= 5 && !memcmp(s, "icon:", 5)) {
                size_t in = n - 5;
                const char *i = ach_trim(s + 5, &in);
                if ((cur.icon = ach_icon_parse(i, in)) < 0) broken = 1;
            } else if (cur.nconds < ACH_CONDS && ach_cond_parse(s, n, &c)) cur.conds[cur.nconds++] = c;
            else broken = 1;
        }
        if (!*end) {
            if (!n) break;
            line = end;   /* (the text's last line had no line feed: once more, at its end, for the achievement it closes) */
        } else line = end + 1;
    }
    if (refused) *refused += bad;
    return added;
}

/* 1 when every condition of the achievement holds in the save data the probe reads */
static inline int ach_met(const Ach *a, AchProbe probe, void *ctx) {
    for (int i = 0; i < a->nconds; i++) {
        const AchCond *c = &a->conds[i];
        const int have = probe(ctx, c->kind, c->what);
        if (have < (c->kind == ACH_ITEM ? c->least : 1)) return 0;
    }
    return a->nconds > 0;
}

/* The achievements not yet earned whose conditions hold are earned now (when: unix time): their places in the list go
   to fresh, cap of them at most a call (the rest at the next), and how many is returned. Nothing is asked of the probe
   for an achievement that is earned already */
static inline int ach_check(AchList *l, AchProbe probe, void *ctx, int64_t when, int *fresh, int cap) {
    int got = 0;
    for (int i = 0; i < l->n && got < cap; i++) {
        Ach *a = &l->a[i];
        if (a->earned || !ach_met(a, probe, ctx)) continue;
        a->earned = 1, a->when = when;
        fresh[got++] = i;
    }
    return got;
}

static inline int ach_earned_count(const AchList *l) {
    int n = 0;
    for (int i = 0; i < l->n; i++) n += l->a[i].earned != 0;
    return n;
}

/* The earned file's text read: "<key, 8 hex digits> <unix time> <name>" a line. A line of an achievement the list has
   marks it earned; any other line of that form is kept for the next write (ACH_ORPHANS at most); the rest is dropped.
   Returns how many of the list's were marked */
static inline int ach_earned_read(AchList *l, const char *text) {
    int marked = 0;
    for (const char *line = text; *line; ) {
        const char *end = line;
        while (*end && *end != '\n') end++;
        size_t n = (size_t)(end - line);
        const char *s = ach_trim(line, &n);
        char *after = NULL;
        const unsigned long key = n >= 10 && s[0] != '#' ? strtoul(s, &after, 16) : 0;
        if (after == s + 8 && *after == ' ') {
            const long long when = strtoll(after + 1, &after, 10);
            const int at = ach_find(l, (uint32_t)key);
            if (at >= 0) {
                if (!l->a[at].earned) marked++;
                l->a[at].earned = 1, l->a[at].when = when > 0 ? when : 0;
            } else if (l->norphans < ACH_ORPHANS && n < ACH_LINE) {
                int dup = 0;
                for (int i = 0; i < l->norphans; i++) dup |= !strncmp(l->orphans[i], s, 8);
                if (!dup) memcpy(l->orphans[l->norphans], s, n), l->orphans[l->norphans++][n] = 0;
            }
        }
        line = *end ? end + 1 : end;
    }
    return marked;
}

/* The earned file's text written into out: its length, 0 when cap is too small for it */
static inline size_t ach_earned_write(const AchList *l, char *out, size_t cap) {
    size_t at = 0;
    int n = snprintf(out, cap, "# The achievements earned in this game folder, a line each: key, when (unix time), name.\n");
    if (n < 0 || (size_t)n >= cap) return 0;
    at = (size_t)n;
    for (int i = 0; i < l->n; i++) {
        const Ach *a = &l->a[i];
        if (!a->earned) continue;
        n = snprintf(out + at, cap - at, "%08x %lld %s\n", (unsigned)a->key, (long long)a->when, a->name);
        if (n < 0 || (size_t)n >= cap - at) return 0;
        at += (size_t)n;
    }
    for (int i = 0; i < l->norphans; i++) {
        n = snprintf(out + at, cap - at, "%s\n", l->orphans[i]);
        if (n < 0 || (size_t)n >= cap - at) return 0;
        at += (size_t)n;
    }
    return at;
}

/* host/achievements.c */
int hos_achievements_on(void);
void hos_achievements_frame(void);
void hos_achievements_check(AchProbe probe, void *ctx, int64_t now_ns);
#endif
