/* (Triforce) Save files, as the Nintendo 64 game had them: a few files to choose from at the title, each a playthrough of
   its own. host/save_files.c has what is the game folder's and the menu's. Nothing of the host is in here:
   tests/test_save_files.py compiles it alone.

   The game keeps all it saves under one folder (hos_user_dir: account.sav, option.sav and its slot_NN folders, the saves
   and the autosaves of one playthrough), which it reads once, at its start, before its title shows. A file is such a
   folder: file 1 the folder the game always had ("user"), file N that folder's name with "-N" after it ("user-2"). The
   game is started on one of them and knows of no other; another file is another start (host/hos_relaunch.c).

   triforce_files.txt in the game folder keeps which, and their names:
     current=2                 the file the next start plays (1 without the line, or with one that names none)
     chosen=1763456789         when a file was chosen for a restart (unix time): the start that follows knows it is that restart
     1=Spanky                  a file's name, SAVE_FILE_NAME bytes at most ("File 1" without the line) */
#ifndef HOS_SAVE_FILES_H
#define HOS_SAVE_FILES_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { SAVE_FILES = 3, SAVE_FILE_NAME = 24, SAVE_FILES_CHOSEN_S = 180 /* (a restart is a few seconds; a start long after it asks again) */ };

typedef struct SaveFiles {
    int current;                                   /* 0 to SAVE_FILES - 1 */
    int64_t chosen;                                /* unix time of the choice a restart follows, 0 none */
    char names[SAVE_FILES][SAVE_FILE_NAME + 1];
} SaveFiles;

static inline void save_files_defaults(SaveFiles *f) {
    memset(f, 0, sizeof *f);
    for (int i = 0; i < SAVE_FILES; i++) snprintf(f->names[i], sizeof f->names[i], "File %d", i + 1);
}

/* triforce_files.txt's text read over the defaults. A line that is none of its three is passed over, a file's number that
   is none and an empty name are not taken, a name is cut at SAVE_FILE_NAME bytes (never inside a letter) */
static inline void save_files_parse(SaveFiles *f, const char *text) {
    save_files_defaults(f);
    for (const char *line = text; *line; ) {
        const char *end = line;
        while (*end && *end != '\n') end++;
        size_t n = (size_t)(end - line);
        while (n && (line[n - 1] == '\r' || line[n - 1] == ' ' || line[n - 1] == '\t')) n--;
        if (n > 8 && !memcmp(line, "current=", 8)) {
            const long v = strtol(line + 8, NULL, 10);
            if (v >= 1 && v <= SAVE_FILES) f->current = (int)v - 1;
        } else if (n > 7 && !memcmp(line, "chosen=", 7)) {
            const long long v = strtoll(line + 7, NULL, 10);
            f->chosen = v > 0 ? v : 0;
        } else if (n > 2 && line[0] >= '1' && line[0] < '1' + SAVE_FILES && line[1] == '=') {
            size_t len = n - 2;
            if (len > SAVE_FILE_NAME) {
                len = SAVE_FILE_NAME;
                while (len && ((unsigned char)line[2 + len] & 0xC0) == 0x80) len--;
            }
            int plain = len > 0;
            for (size_t i = 0; i < len; i++) plain &= (unsigned char)line[2 + i] >= 32;
            if (plain) memcpy(f->names[line[0] - '1'], line + 2, len), f->names[line[0] - '1'][len] = 0;
        }
        line = *end ? end + 1 : end;
    }
}

/* triforce_files.txt's text written into out: its length, 0 when cap is too small for it */
static inline size_t save_files_write(const SaveFiles *f, char *out, size_t cap) {
    int n = snprintf(out, cap, "# The save files (the title's file select): the one the next start plays, and their names.\ncurrent=%d\n", f->current + 1);
    if (n < 0 || (size_t)n >= cap) return 0;
    size_t at = (size_t)n;
    if (f->chosen > 0) {
        n = snprintf(out + at, cap - at, "chosen=%lld\n", (long long)f->chosen);
        if (n < 0 || (size_t)n >= cap - at) return 0;
        at += (size_t)n;
    }
    for (int i = 0; i < SAVE_FILES; i++) {
        n = snprintf(out + at, cap - at, "%d=%s\n", i + 1, f->names[i]);
        if (n < 0 || (size_t)n >= cap - at) return 0;
        at += (size_t)n;
    }
    return at;
}

/* A file's folder: file 0 the folder the game always had (base), file N - 1 that name with "-N" after it. 1 when it fits */
static inline int save_files_folder(const char *base, int file, char *out, size_t cap) {
    if (file < 0 || file >= SAVE_FILES) return 0;
    size_t n = strlen(base);
    while (n > 1 && (base[n - 1] == '/' || base[n - 1] == '\\')) n--;   /* ("user\" and "user": the same folder) */
    const int len = file ? snprintf(out, cap, "%.*s-%d", (int)n, base, file + 1) : snprintf(out, cap, "%.*s", (int)n, base);
    return len > 0 && (size_t)len < cap;
}

/* 1 when this start follows a file's choice (now: unix time): the restart the choice asked for */
static inline int save_files_chosen_now(const SaveFiles *f, int64_t now) {
    return f->chosen > 0 && now >= f->chosen && now - f->chosen <= SAVE_FILES_CHOSEN_S;
}

/* ---- A file's card on the file select: what the game's own load list shows of a save, kept by the host as it is played ----
   The game shows a save's place, hearts, Spiritual Stones and medallions from the save's own data, whose form this
   repository does not know and does not read. The same is known while the game runs: host/hos_main.c tells it as the file is
   played (hos_save_card_note), and it is kept in the file's folder, triforce_card.txt:
     place=Kokiri Forest        where Link was (the map's own name, its words set apart)
     items=1c9                  SAVE_CARD_* bits, hex: the stones and medallions he holds
     hearts=7                   his heart containers, 0 when they are not known
     slot=3                     the slot the game saved in last while this file was played (host/nn_fs.c tells: a slot's file
     saved=1763456789           opened to be written), and when (unix time): the save whose picture and time the card shows.
                                The slots' files cannot tell: the game writes them all again when it saves one */
enum { SAVE_CARD_PLACE = 48,
       SAVE_CARD_STONES = 3,       /* bits 0 to 2: the Spiritual Stones of the forest, of fire, of water */
       SAVE_CARD_MEDALS = 6,       /* bits 3 to 8: the medallions of light, forest, fire, water, spirit, shadow */
       SAVE_CARD_ITEMS = SAVE_CARD_STONES + SAVE_CARD_MEDALS, SAVE_CARD_HEARTS = 20 };
typedef struct SaveCard {
    char place[SAVE_CARD_PLACE + 1];
    int items, hearts;
    int slot1;        /* the slot saved in last, and 1; 0 not known */
    int64_t saved;    /* when, unix time; 0 not known */
} SaveCard;

/* The slot a guest path of the save names ("save:/slot_03/caption.sav": 3), -1 when it names none of slot_00 to slot_11 */
static inline int save_card_slot_of(const char *guest) {
    const char *s = guest ? strstr(guest, "slot_") : NULL;
    if (!s || s[5] < '0' || s[5] > '9' || s[6] < '0' || s[6] > '9' || (s[7] != '/' && s[7] != '\\')) return -1;
    const int slot = (s[5] - '0') * 10 + (s[6] - '0');
    return slot < 12 ? slot : -1;
}
/* (a map that is another in each of Link's ages says which at its name's end: the game's own load list does not) */
static inline void save_card_trim_age(char *place) {
    const size_t n = strlen(place);
    if (n > 6 && (!strcmp(place + n - 6, " Adult") || !strcmp(place + n - 6, " Child"))) place[n - 6] = 0;
}

/* A map's own name as a card shows it: "KokiriForest" is "Kokiri Forest", "Inside_GanonCastle01" "Inside Ganon Castle 01",
   "DekuTree_B1F" "Deku Tree B1F". A space before a capital that follows a small letter (or a digit, when it begins a word),
   and before a digit that follows a small letter; '_' a space */
static inline void save_card_place(const char *map, char *out, size_t cap) {
    size_t n = 0;
    for (const char *p = map; *p && n + 2 < cap; p++) {
        const unsigned char ch = (unsigned char)*p, before = p > map ? (unsigned char)p[-1] : 0;
        const int upper = ch >= 'A' && ch <= 'Z', digit = ch >= '0' && ch <= '9';
        const int was_lower = before >= 'a' && before <= 'z', was_digit = before >= '0' && before <= '9';
        if (ch == '_' || ch < 32) {
            if (n && out[n - 1] != ' ') out[n++] = ' ';
            continue;
        }
        const int word = p[1] >= 'a' && p[1] <= 'z';   /* (a capital that begins a word, not one of a floor's name: B1F) */
        if (n && out[n - 1] != ' ' && ((upper && (was_lower || (was_digit && word))) || (digit && was_lower))) out[n++] = ' ';
        out[n++] = (char)ch;
    }
    while (n && out[n - 1] == ' ') n--;
    if (cap) out[n] = 0, save_card_trim_age(out);
}

/* Heart containers from the game's own count of Link's life, which it keeps in quarters of a heart: 0 when the number is
   not one (not whole hearts, under the three every game starts with, or over SAVE_CARD_HEARTS) */
static inline int save_card_hearts(int life) { return life >= 12 && life <= 4 * SAVE_CARD_HEARTS && life % 4 == 0 ? life / 4 : 0; }

/* triforce_card.txt's text read: what is not one of its lines is passed over, a number that is none is 0 */
static inline void save_card_parse(SaveCard *c, const char *text) {
    memset(c, 0, sizeof *c);
    for (const char *line = text; *line; ) {
        const char *end = line;
        while (*end && *end != '\n') end++;
        size_t n = (size_t)(end - line);
        while (n && (line[n - 1] == '\r' || line[n - 1] == ' ')) n--;
        if (n > 6 && !memcmp(line, "place=", 6)) {
            size_t len = n - 6 > SAVE_CARD_PLACE ? SAVE_CARD_PLACE : n - 6;
            while (len && ((unsigned char)line[6 + len] & 0xC0) == 0x80) len--;
            memcpy(c->place, line + 6, len), c->place[len] = 0;
            for (size_t i = 0; i < len; i++)
                if ((unsigned char)c->place[i] < 32 || c->place[i] == '|') c->place[i] = ' ';
            save_card_trim_age(c->place);   /* (a card kept before the age was left out) */
        } else if (n > 6 && !memcmp(line, "items=", 6)) {
            c->items = (int)(strtoul(line + 6, NULL, 16) & ((1u << SAVE_CARD_ITEMS) - 1));
        } else if (n > 7 && !memcmp(line, "hearts=", 7)) {
            const long v = strtol(line + 7, NULL, 10);
            c->hearts = v >= 1 && v <= SAVE_CARD_HEARTS ? (int)v : 0;
        } else if (n > 5 && !memcmp(line, "slot=", 5)) {
            const long v = line[5] >= '0' && line[5] <= '9' ? strtol(line + 5, NULL, 10) : -1;
            c->slot1 = v >= 0 && v < 12 ? (int)v + 1 : 0;
        } else if (n > 6 && !memcmp(line, "saved=", 6)) {
            const long long v = strtoll(line + 6, NULL, 10);
            c->saved = v > 0 ? v : 0;
        }
        line = *end ? end + 1 : end;
    }
}
/* triforce_card.txt's text written into out: its length, 0 when cap is too small for it */
static inline size_t save_card_write(const SaveCard *c, char *out, size_t cap) {
    int n = snprintf(out, cap, "# What the file select shows of this save file: where it was played last, the stones and medallions held, the hearts,\n"
                     "# and the slot the game saved in last.\nplace=%s\nitems=%x\nhearts=%d\n", c->place, (unsigned)c->items, c->hearts);
    if (n <= 0 || (size_t)n >= cap) return 0;
    if (c->slot1) {
        const int more = snprintf(out + n, cap - (size_t)n, "slot=%d\nsaved=%lld\n", c->slot1 - 1, (long long)c->saved);
        if (more <= 0 || (size_t)more >= cap - (size_t)n) return 0;
        n += more;
    }
    return (size_t)n;
}
static inline int save_card_same(const SaveCard *a, const SaveCard *b) {
    return !strcmp(a->place, b->place) && a->items == b->items && a->hearts == b->hearts && a->slot1 == b->slot1 && a->saved == b->saved;
}

/* host/save_files.c */
void hos_save_card_note(const char *map, int items, int life, int64_t now_ns);
void hos_save_card_wrote(const char *guest_path);
int hos_save_files_on(void);
const char *hos_save_files_dir(int *first);
const char *hos_save_files_start(const char *game_dir, const char *base_user);
void hos_save_files_frame(void);
#endif
