/* (Triforce) Achievements, as a console's or a store's: things done in the game that are marked as earned, once, with a
   notice on the screen and a sound when one is, and a page of the options that lists them. host/achievements.h has what
   an achievement is, the list every game has, the form of a player's own list and of the file that keeps the earned
   ones; this file has what is the game folder's and the screen's.

   - On by default (11-22, the owner's word); HOS_ACHIEVEMENTS=0 (triforce_env.txt) turns them off. While off nothing is
     read, of the game or of the disk.
   - (11-23) The System tab's Achievements group has two rows of them, read from the renderer at each check: Achievements
     Off (HOS_OPT_ACH_ON 0) and nothing is asked of the save data or earned, from the next check on, and On again as
     soon; Achievement notices Off (HOS_OPT_ACH_NOTICES 0) and one earned is kept, said in the log and told to the list,
     without the sound (the menu shows no notice then).
   - The lists are read at the game's first present (hos_achievements_frame, host/nvn_native.c): the built-in one, then
     achievements.txt in the game folder when there is one. Once the renderer answers they are named to the menu
     (HOS_OPT_ACH_TEXT, _ADD, _COUNT: gpu/vk/achievement_rows.h), which lists them on the System tab's Achievements page.
   - host/hos_main.c asks once a second at Link's update, on the game's thread, while a save is loaded, and hands over
     how the save data is read (hos_achievements_check).
   - An achievement earned is written to triforce_achievements.txt in the game folder at once (the file whole, under
     another name first; while the save files are on, host/save_files.c, in the folder of the file played, so that each
     file has what it earned and no other's: earned_file), said in the log, and shown: the menu's notice (HOS_OPT_ACH_EARNED) with the system menu's
     decide sound (HOS_MENU_SOUND_SYS_DECIDE, at the Menu sounds row's volume; silent where that row is Off. Not the
     item fanfare: most are earned as the game plays that itself). One at a time: a save that earns several at once
     shows them one after the other.
   - The present's thread and the game's both come here: what they share is under one lock, held for a list's naming
     or a check and no longer.
   - Nothing of the game's is written here, and nothing is changed in the game: the save data is only read. */
#include "hos.h"
#include "hos_paths.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "../gpu/vk/vk_api.h"
#include "achievements.h"
#include "menu_sound.h"

int rx_option(int id, int otherwise);
void rx_option_set(int id, int value);
const char *hos_save_files_dir(int *first);   /* host/save_files.c */

#define EARNED_FILE "triforce_achievements.txt"
#define OWN_FILE "achievements.txt"
enum { OWN_MOST = 1 << 18, SHOWN_MS = 4500 /* (a notice stays 4 s: gpu/vk/vk_menu.cpp) */ };

static AchList list;
static int ready;                 /* the lists were read */
static int named;                 /* and named to the menu: it shows them, and a notice for one earned */
static int waiting[ACH_MAX], nwaiting;   /* earned, not yet shown */
static int64_t next_shown;
static volatile char busy;        /* the lock: the present's thread names the list, the game's checks it */

static void lock(void) {
    while (__atomic_test_and_set(&busy, __ATOMIC_ACQUIRE)) {}
}
static void unlock(void) { __atomic_clear(&busy, __ATOMIC_RELEASE); }

static const char *last_sep(const char *s) {
    const char *b = strrchr(s, '\\'), *f = strrchr(s, '/');
    return b > f ? b : f;
}
/* a file of the game folder */
static int game_file(char *out, size_t cap, const char *name) {
    char exe[MAX_PATH];
    const DWORD n = hos_game_path_a(exe, sizeof exe);
    const char *slash = n && n < sizeof exe ? last_sep(exe) : NULL;
    if (!slash) return 0;
    return snprintf(out, cap, "%.*s%s", (int)(slash + 1 - exe), exe, name) < (int)cap;
}

/* ((Triforce) 11-23, his "I don't want achievements to carry across" the save files.) Where the earned ones are kept: the
   game folder's triforce_achievements.txt, or, while the save files are on, the one in the folder of the file this run
   plays. *inherits: that file is File 1 and may start from the game folder's, which is what it earned before there were
   files (read only: the game folder's is left as it is) */
static int earned_file(char *out, size_t cap, int *inherits) {
    int first = 0;
    const char *dir = hos_save_files_dir(&first);
    *inherits = dir && first;
    if (!dir) return game_file(out, cap, EARNED_FILE);
    return snprintf(out, cap, "%s%c" EARNED_FILE, dir, strchr(dir, '\\') ? '\\' : '/') < (int)cap;
}

/* a text file whole, its end a 0 (freed by the caller); NULL when it is not there or over `most` */
static char *read_text(const char *path, long most) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    char *text = NULL;
    long size = 0;
    if (!fseek(f, 0, SEEK_END) && (size = ftell(f)) >= 0 && size <= most && !fseek(f, 0, SEEK_SET) && (text = (char *)malloc((size_t)size + 1))) {
        const size_t got = fread(text, 1, (size_t)size, f);
        text[got] = 0;
        for (size_t i = 0; i < got; i++)
            if (!text[i]) text[i] = ' ';   /* (a 0 in the middle is not the text's end) */
    }
    fclose(f);
    return text;
}

static void earned_save(void) {
    static char text[ACH_MAX * (ACH_NAME + 40) + ACH_ORPHANS * ACH_LINE + 200];
    char path[MAX_PATH + 160], fresh[MAX_PATH + 168];
    int inherits;
    const size_t n = ach_earned_write(&list, text, sizeof text);
    if (!n || !earned_file(path, sizeof path, &inherits)) return;
    snprintf(fresh, sizeof fresh, "%s.new", path);
    FILE *f = fopen(fresh, "wb");   /* (its lines end the same on Windows and Linux) */
    const int ok = f && fwrite(text, 1, n, f) == n;
    if ((f && fclose(f)) || !ok || !MoveFileExA(fresh, path, MOVEFILE_REPLACE_EXISTING)) {
        remove(fresh);
        hos_log("achievements: %s could not be written: what was earned is kept until the game ends", path);
    }
}

static void lists_read(void) {
    int refused = 0;
    const int built_in = ach_parse(&list, ACH_BUILTIN, &refused);
    char path[MAX_PATH + 160];
    int inherits = 0;
    char *own = game_file(path, sizeof path, OWN_FILE) ? read_text(path, OWN_MOST) : NULL;
    const int own_n = own ? ach_parse(&list, own, &refused) : 0;
    free(own);
    char *earned = earned_file(path, sizeof path, &inherits) ? read_text(path, OWN_MOST) : NULL;
    if (!earned && inherits && game_file(path, sizeof path, EARNED_FILE)) earned = read_text(path, OWN_MOST);
    const int marked = earned ? ach_earned_read(&list, earned) : 0;
    free(earned);
    hos_log("achievements: %d (%d of " OWN_FILE "%s), %d earned so far%s", list.n, own_n, own ? "" : ", which is not there", marked,
            built_in + own_n ? "" : ": none to earn");
    if (refused)
        hos_log("achievements: %d left out: a name that is empty, over %d bytes or another's, no condition, over %d of them, or a "
                "line that is not about:, icon: <shape> [<tone>], item <name> [<least>] or flag <name>", refused, ACH_NAME, ACH_CONDS);
}

/* ---- the menu's side: gpu/vk/achievement_rows.h ---- */
static void to_menu(const char *text) {
    for (const char *p = text; *p; p++) rx_option_set(HOS_OPT_ACH_TEXT, (unsigned char)*p);
}
/* the day of a unix time, as the page shows it ("" when it is not known) */
static void day_of(int64_t when, char *out, size_t cap) {
    const time_t t = (time_t)when;
    const struct tm *tm = when > 0 ? localtime(&t) : NULL;
    if (!tm || !strftime(out, cap, "%Y-%m-%d", tm)) out[0] = 0;
}
static void name_list(void) {
    for (int i = 0; i < list.n; i++) {
        const Ach *a = &list.a[i];
        char day[16];
        day_of(a->earned ? a->when : 0, day, sizeof day);
        to_menu(a->name), to_menu("\n"), to_menu(a->about), to_menu("\n"), to_menu(day);
        rx_option_set(HOS_OPT_ACH_ADD, (a->icon & 255) | (a->earned ? HOS_ACH_EARNED : 0));
    }
    rx_option_set(HOS_OPT_ACH_COUNT, list.n);
}

/* On unless HOS_ACHIEVEMENTS=0 (11-22: on by default). Read once */
int hos_achievements_on(void) {
    static int on = -1;
    if (on < 0) {
        const char *e = getenv("HOS_ACHIEVEMENTS");
        on = !(e && e[0] == '0' && !e[1]);
    }
    return on;
}

/* host/nvn_native.c, at each present of the game's: the lists read at the first, and named to the menu once it answers */
void hos_achievements_frame(void) {
    static int done;   /* (the present's thread alone) */
    if (done || !hos_achievements_on()) return;
    lock();
    if (!ready) ready = 1, lists_read();
    if (rx_option(HOS_OPT_ACH_ASK, 0) > 0) named = done = 1, name_list();
    unlock();
}

/* host/hos_main.c, once a second at Link's update while a save is loaded (now_ns: hos_now_ns): what the save data has
   earned since the last call is marked, kept and shown */
void hos_achievements_check(AchProbe probe, void *ctx, int64_t now_ns) {
    if (!hos_achievements_on() || !rx_option(HOS_OPT_ACH_ON, 1)) return;
    const int quiet = !rx_option(HOS_OPT_ACH_NOTICES, 1);
    lock();
    if (!ready) ready = 1, lists_read();
    int fresh[ACH_MAX];
    const int got = ach_check(&list, probe, ctx, (int64_t)time(NULL), fresh, ACH_MAX);
    for (int i = 0; i < got; i++) {
        hos_log("achievements: earned \"%s\" (%d of %d)", list.a[fresh[i]].name, ach_earned_count(&list) - (got - 1 - i), list.n);
        if (nwaiting < ACH_MAX) waiting[nwaiting++] = fresh[i];
    }
    if (got) earned_save();
    if (nwaiting && named && (quiet || now_ns >= next_shown)) {   /* (not before the menu has the list: it shows them by their place in it) */
        const int at = waiting[0];
        char day[16];
        memmove(waiting, waiting + 1, sizeof waiting[0] * (size_t)--nwaiting);
        next_shown = quiet ? now_ns : now_ns + SHOWN_MS * 1000000LL;   /* (no notice shown: the next need not wait for it) */
        day_of(list.a[at].when, day, sizeof day);
        to_menu(day);
        rx_option_set(HOS_OPT_ACH_EARNED, at);
        if (!quiet) hos_menu_sound_play(HOS_MENU_SOUND_SYS_DECIDE, now_ns);
    }
    unlock();
}
