/* (Triforce) Save files, as the Nintendo 64 game had them: the title asks which file to play, and the game's saves and
   autosaves live in that file. host/save_files.h has what a file is and the form of triforce_files.txt; this file has
   what is the game folder's and the menu's.

   - On by default (11-23); HOS_SAVE_FILES=0 (triforce_env.txt) turns it off. While off the game's folder is the one it
     always had, and nothing is read or written here. Off too when the folder was named on the command line (--user).
   - hos_save_files_start (host/hos_main.c, before the game's memory is made): the folder of the file the last choice
     named, which becomes hos_user_dir. The game mounts it at its start, reads its saves once, before its title shows,
     and keeps them in memory (tried: files taken out of the mounted folder at the title were still listed and loaded):
     so another file is another start, and never a folder changed under a running game.
   - hos_save_files_frame (host/nvn_native.c, at each present): once the renderer answers, the files are named to the
     menu (HOS_OPT_FILES_TEXT, _ADD, _COUNT: gpu/vk/save_file_rows.h), which asks at the title which to play. A file
     chosen that is not this run's (HOS_OPT_FILES_ASK) is written to triforce_files.txt as the next start's, with the
     time, and the menu is told (HOS_OPT_FILES_SAID): it restarts the game, as its Restart now does. The start that
     follows a choice says so to the menu (which asks at the title all the same: that is where a file is changed again).
   - A file's save is never opened here: whether it has one, when it was last written and which of its files holds its
     picture are its folder's own (the menu reads the picture out of that file itself). Where it was played last, its
     stones, medallions and hearts are told by host/hos_main.c as it is played (hos_save_card_note) and kept beside it,
     triforce_card.txt: what the game's own load list shows of a save, without the save's data read. */
#include "hos.h"
#include "hos_paths.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "../gpu/vk/vk_api.h"
#include "save_files.h"
#include "oot_autoload.h"   /* (the Skip title screen row's rule for the newest save: hos_save_files_newest_here) */

int rx_option(int id, int otherwise);
void rx_option_set(int id, int value);

#define FILES_FILE "triforce_files.txt"
enum { FILES_PATH = MAX_PATH + 64, FILES_MOST = 4096 };

static SaveFiles files;
static int started;                    /* hos_save_files_start chose a folder: the files are this run's */
static int after_choice;               /* this start follows a file's choice */
static char files_path[FILES_PATH];    /* triforce_files.txt */
static char base_dir[FILES_PATH];      /* file 1's folder */
static char user_dir[FILES_PATH];      /* this run's */

/* On unless HOS_SAVE_FILES=0 ((Triforce) 11-23, the owner's word: on by default; File 1 is the folder the game always had, so
   a start with no triforce_files.txt plays the saves it always did). Read once */
int hos_save_files_on(void) {
    static int on = -1;
    if (on < 0) {
        const char *e = getenv("HOS_SAVE_FILES");
        on = !(e && e[0] == '0' && !e[1]);
    }
    return on;
}

static void files_read(void) {
    static char text[FILES_MOST + 1];
    FILE *f = fopen(files_path, "rb");
    const size_t n = f ? fread(text, 1, FILES_MOST, f) : 0;
    if (f) fclose(f);
    text[n] = 0;
    for (size_t i = 0; i < n; i++)
        if (!text[i]) text[i] = ' ';
    save_files_parse(&files, text);
}

/* triforce_files.txt whole, under another name first: 1 written */
static int files_save(void) {
    static char text[FILES_MOST];
    char fresh[FILES_PATH + 8];
    const size_t n = save_files_write(&files, text, sizeof text);
    if (!n) return 0;
    snprintf(fresh, sizeof fresh, "%s.new", files_path);
    FILE *f = fopen(fresh, "wb");   /* (its lines end the same on Windows and Linux) */
    const int ok = f && fwrite(text, 1, n, f) == n;
    if ((f && fclose(f)) || !ok || !MoveFileExA(fresh, files_path, MOVEFILE_REPLACE_EXISTING)) {
        remove(fresh);
        hos_log("save files: %s could not be written", files_path);
        return 0;
    }
    return 1;
}

/* host/hos_main.c, at the start, the game's folder known and no --user given: the folder the game saves in this run.
   game_dir: the game folder; base_user: the folder the game always had. Off: base_user itself */
const char *hos_save_files_start(const char *game_dir, const char *base_user) {
    if (!hos_save_files_on()) return base_user;
    if (snprintf(files_path, sizeof files_path, "%s%c%s", game_dir, strchr(game_dir, '\\') ? '\\' : '/', FILES_FILE) >= (int)sizeof files_path ||
        !save_files_folder(base_user, 0, base_dir, sizeof base_dir)) {
        hos_log("save files: the game folder's path is too long: the game's own folder is used, %s", base_user);
        return base_user;
    }
    files_read();
    if (!save_files_folder(base_dir, files.current, user_dir, sizeof user_dir)) files.current = 0, snprintf(user_dir, sizeof user_dir, "%s", base_dir);
    after_choice = save_files_chosen_now(&files, (int64_t)time(NULL));
    if (files.chosen) {   /* (taken: a start after this one asks again) */
        files.chosen = 0;
        files_save();
    }
    started = 1;
    hos_log("save files: file %d of %d, \"%s\": its saves are in %s%s", files.current + 1, SAVE_FILES, files.names[files.current], user_dir,
            after_choice ? " (chosen at the title: the game restarted for it)" : "");
    return user_dir;
}

/* ---- the menu's side: gpu/vk/save_file_rows.h ---- */
static void to_menu(const char *text) {
    for (const char *p = text; *p; p++) rx_option_set(HOS_OPT_FILES_TEXT, (unsigned char)*p);
}
/* a time as the game's own load list writes a save's: 11/18/2026 1:40 a.m. ("" for none) */
static void game_time(time_t t, char *out, size_t cap) {
    const struct tm *tm = t > 0 ? localtime(&t) : NULL;
    out[0] = 0;
    if (tm) snprintf(out, cap, "%d/%d/%d %d:%02d %s", tm->tm_mon + 1, tm->tm_mday, tm->tm_year + 1900, tm->tm_hour % 12 ? tm->tm_hour % 12 : 12, tm->tm_min,
                     tm->tm_hour < 12 ? "a.m." : "p.m.");
}
static time_t unix_of(const FILETIME *ft) {   /* (a FILETIME: 100 ns since 1601; 0 when it is none) */
    const uint64_t v = (uint64_t)ft->dwHighDateTime << 32 | ft->dwLowDateTime;
    return v > 116444736000000000ULL ? (time_t)((v - 116444736000000000ULL) / 10000000ULL) : 0;
}
/* What a file's card shows of its save, from its folder alone (no save is opened here): when its account.sav was last
   written, in `when` ("" when it has no save yet, or the time cannot be told), and where its slots are, in `picture`: the
   start of their caption files' paths, up to the slot's number ("" none). The game keeps a save's picture and its time
   in that file, and the menu reads them from there itself (gpu/vk/save_file_rows.h jpeg_in, caption_time). 1 when the
   file has a save: a slot, not the account.sav alone */
static int last_saved(int file, char *when, size_t when_cap, char *picture, size_t picture_cap) {
    char dir[FILES_PATH], pat[FILES_PATH + 96];
    WIN32_FIND_DATAA fd, found;
    int saved = 0;
    when[0] = picture[0] = 0;
    if (!save_files_folder(base_dir, file, dir, sizeof dir)) return 0;
    snprintf(pat, sizeof pat, "%s\\save\\*", dir);
    HANDLE h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        if (fd.cFileName[0] == '.' || strlen(fd.cFileName) > 40) continue;
        snprintf(pat, sizeof pat, "%s\\save\\%s\\account.sav", dir, fd.cFileName);
        HANDLE a = FindFirstFileA(pat, &found);
        if (a == INVALID_HANDLE_VALUE) continue;
        FindClose(a);
        const time_t t = unix_of(&found.ftLastWriteTime);
        game_time(t, when, when_cap);
        for (int slot = 0; slot < 12; slot++) {   /* (the game looks for slot_00 to slot_11) */
            snprintf(pat, sizeof pat, "%s\\save\\%s\\slot_%02d\\caption.sav", dir, fd.cFileName, slot);
            HANDLE s = FindFirstFileA(pat, &found);
            if (s == INVALID_HANDLE_VALUE) continue;
            FindClose(s);
            saved = 1;
        }
        /* ((Triforce) 11-18, his picture of the game's own load list beside the card: "the screenshot doesn't match the last
           autosave either nor does the time". The slot written last cannot be told from the disk: the game writes them all
           again whenever it saves one. Where the slots are, then, and the menu reads each one's own time out of it) */
        if (saved && snprintf(picture, picture_cap, "%s\\save\\%s\\slot_", dir, fd.cFileName) >= (int)picture_cap) picture[0] = 0;
        /* ((Triforce) 11-18, his picture: File 2, a new game started and not yet saved, said "Saved game" with no picture. The
           game makes account.sav as it starts on a file: a file has a save once it has a slot) */
        if (!saved) when[0] = 0;
        break;
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    return saved;
}
/* When a folder of the game's (a file's, or the game's own with the save files off) was last saved in: the newest write time
   of its slots' caption.sav (the game writes a slot's caption and its save one after the other), as the folder's list has it
   (a FILETIME's number), 0 when it has no save. Nothing is opened */
static int64_t folder_saved(const char *dir) {
    char pat[FILES_PATH + 96];
    WIN32_FIND_DATAA fd, found;
    int64_t newest = 0;
    snprintf(pat, sizeof pat, "%s\\save\\*", dir);
    HANDLE h = FindFirstFileA(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        if (fd.cFileName[0] == '.' || strlen(fd.cFileName) > 40) continue;
        for (int slot = 0; slot < 12; slot++) {   /* (the game looks for slot_00 to slot_11) */
            snprintf(pat, sizeof pat, "%s\\save\\%s\\slot_%02d\\caption.sav", dir, fd.cFileName, slot);
            HANDLE s = FindFirstFileA(pat, &found);
            if (s == INVALID_HANDLE_VALUE) continue;
            FindClose(s);
            const int64_t t = (int64_t)((uint64_t)found.ftLastWriteTime.dwHighDateTime << 32 | found.ftLastWriteTime.dwLowDateTime);
            if (t > newest) newest = t;
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    return newest;
}
/* host/oot_autoload.c (the Skip title screen row): 1 when the file this run plays holds the newest save of all the files
   the file select shows (host/oot_autoload.h oot_autoload_newest_here); 0 when another file was saved in later, or this
   one has no save yet. With the save files off there is one folder, the game's own (own_dir: hos_user_dir): whether it has
   a save */
int hos_save_files_newest_here(const char *own_dir) {
    int64_t times[SAVE_FILES] = {0};
    if (!started) {
        times[0] = own_dir && own_dir[0] ? folder_saved(own_dir) : 0;
        return oot_autoload_newest_here(times, 1, 0);
    }
    for (int i = 0; i < SAVE_FILES; i++) {
        char dir[FILES_PATH];
        times[i] = save_files_folder(base_dir, i, dir, sizeof dir) ? folder_saved(dir) : 0;
    }
    return oot_autoload_newest_here(times, SAVE_FILES, files.current);
}
/* ---- a file's card: host/save_files.h SaveCard ---- */
#define CARD_FILE "triforce_card.txt"
static int card_path(const char *dir, char *out, size_t cap) {
    return snprintf(out, cap, "%s%c" CARD_FILE, dir, strchr(dir, '\\') ? '\\' : '/') < (int)cap;
}
/* A file's card as its folder keeps it: nothing of it when the file was not played with this yet */
static void card_of(int file, SaveCard *card) {
    char dir[FILES_PATH], path[FILES_PATH + 40], text[512];
    memset(card, 0, sizeof *card);
    if (!save_files_folder(base_dir, file, dir, sizeof dir) || !card_path(dir, path, sizeof path)) return;
    FILE *f = fopen(path, "rb");
    if (!f) return;
    const size_t n = fread(text, 1, sizeof text - 1, f);
    fclose(f);
    text[n] = 0;
    for (size_t i = 0; i < n; i++)
        if (!text[i]) text[i] = ' ';
    save_card_parse(card, text);
}
/* ---- the card kept. Two of the game's threads come here, Link's update and whichever one saves: what they share is under
   one lock, held for a card's writing and no longer ---- */
static volatile char card_busy;
static SaveCard card_kept;       /* what this file's triforce_card.txt has */
static SaveCard card_seen;       /* the place, the items and the hearts as last told */
static int card_known, card_told;   /* the kept card was read; something was told this run */
static void card_lock(void) {
    while (__atomic_test_and_set(&card_busy, __ATOMIC_ACQUIRE)) {}
}
static void card_unlock(void) { __atomic_clear(&card_busy, __ATOMIC_RELEASE); }
/* (with the lock held) the card written into this run's folder, whole, under another name first */
static void card_keep(const SaveCard *card) {
    char path[FILES_PATH + 40], fresh[FILES_PATH + 48], text[512];
    const size_t n = save_card_write(card, text, sizeof text);
    if (!n || !card_path(user_dir, path, sizeof path)) return;
    snprintf(fresh, sizeof fresh, "%s.new", path);
    FILE *f = fopen(fresh, "wb");   /* (its lines end the same on Windows and Linux) */
    const int ok = f && fwrite(text, 1, n, f) == n;
    if ((f && fclose(f)) || !ok || !MoveFileExA(fresh, path, MOVEFILE_REPLACE_EXISTING)) {
        remove(fresh);
        static int said;
        if (!said++) hos_log("save files: %s could not be written: this file's card stays as it was", path);
        return;
    }
    card_kept = *card;
}
/* host/nn_fs.c, a file of the save opened to be written (any of the game's threads): a slot's is that slot saved in, now.
   Kept at once, with the place, the items and the hearts as last told. ((Triforce) 11-18: it was kept at Link's next
   update. He saved from the pause menu, where Link is not updated, and went to the title: the card never had the save.)
   The game writes a slot's caption and its progress one after the other: one save, one time */
void hos_save_card_wrote(const char *guest_path) {
    const int slot = started ? save_card_slot_of(guest_path) : -1;
    if (slot < 0) return;
    const int64_t now = (int64_t)time(NULL);
    card_lock();
    if (!card_known) card_known = 1, card_of(files.current, &card_kept);
    SaveCard card = card_told ? card_seen : card_kept;
    card.slot1 = slot + 1;
    card.saved = card_kept.slot1 == slot + 1 && now >= card_kept.saved && now - card_kept.saved < 10 ? card_kept.saved : now;
    if (!save_card_same(&card, &card_kept)) card_keep(&card);
    card_unlock();
}
/* host/hos_main.c, every two seconds at Link's update while a save is loaded (the game's thread; now_ns: hos_now_ns): the
   map he is on (its own name), the stones and medallions he holds (SAVE_CARD_* bits) and the game's count of his life (0:
   not known). What the next save is kept with; and kept by itself when it is not what is kept already, five seconds
   apart at most, so that a file played and not saved in has its card too */
void hos_save_card_note(const char *map, int items, int life, int64_t now_ns) {
    static int64_t next;
    if (!started || !map || !map[0]) return;
    SaveCard card;
    memset(&card, 0, sizeof card);
    save_card_place(map, card.place, sizeof card.place);
    card.items = items & ((1 << SAVE_CARD_ITEMS) - 1), card.hearts = save_card_hearts(life);
    card_lock();
    if (!card_known) card_known = 1, card_of(files.current, &card_kept);
    card.slot1 = card_kept.slot1, card.saved = card_kept.saved;   /* (the slot saved in last: hos_save_card_wrote's) */
    card_seen = card, card_told = 1;
    if (now_ns >= next && !save_card_same(&card, &card_kept)) next = now_ns + 5000000000LL, card_keep(&card);
    card_unlock();
}
/* host/achievements.c: the folder of the file this run plays, where what that file earned is kept; NULL while the save
   files are off (the game folder keeps it then). *first: it is File 1, which was the game's only one before */
const char *hos_save_files_dir(int *first) {
    if (!started) return NULL;
    *first = files.current == 0;
    return user_dir;
}
static void name_files(void) {
    for (int i = 0; i < SAVE_FILES; i++) {
        char when[32], picture[FILES_PATH + 96], shown[SAVE_CARD_PLACE + 96], made[32] = "";
        SaveCard card;
        const int saved = last_saved(i, when, sizeof when, picture, sizeof picture);
        card_of(i, &card);
        game_time((time_t)card.saved, made, sizeof made);
        /* (its place, its items, its hearts; then the slot saved in last, -1 not known, and when, as the game writes a time) */
        snprintf(shown, sizeof shown, "%s|%x|%d|%d|%s", card.place, (unsigned)card.items, card.hearts, card.slot1 - 1, card.slot1 ? made : "");
        to_menu(files.names[i]), to_menu("\n"), to_menu(when), to_menu("\n"), to_menu(picture), to_menu("\n"), to_menu(shown);
        rx_option_set(HOS_OPT_FILES_ADD, (saved ? HOS_FILE_SAVED : 0) | (i == files.current ? HOS_FILE_CURRENT : 0));
    }
    rx_option_set(HOS_OPT_FILES_COUNT, SAVE_FILES | (after_choice ? HOS_FILES_CHOSEN : 0));
}
/* host/nvn_native.c, at each present of the game's: the files named to the menu once it answers, and the file it chose
   made the next start's */
void hos_save_files_frame(void) {
    static int named;   /* (the present's thread alone) */
    if (!started) return;
    const int ask = rx_option(HOS_OPT_FILES_ASK, -1);
    if (ask < 0) return;   /* (no renderer that shows them yet) */
    if (!named) named = 1, name_files();
    if (ask < 1 || ask > SAVE_FILES || ask - 1 == files.current) return;
    const int was = files.current;
    files.current = ask - 1, files.chosen = (int64_t)time(NULL);
    const int kept = files_save();
    hos_log("save files: file %d, \"%s\", chosen: %s", ask, files.names[ask - 1], kept ? "the game starts again on it" : "it could not be kept, nothing changes");
    files.current = was, files.chosen = 0;   /* (this run plays the file it started on, to its end) */
    rx_option_set(HOS_OPT_FILES_SAID, kept ? 1 : 2);
}
