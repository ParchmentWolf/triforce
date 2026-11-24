/* Save files on the host's side: host/save_files.c's own text (save_files_actual.inc, cut by tests/test_save_files.py)
   against a stand-in menu, a stand-in for the files' folders and a game folder of the test's. Run four times: "off"
   with HOS_SAVE_FILES=0, then "first" without it (on by default since 11-23), then "first", "second" and "third" with it on the same folder, each a start of the game. */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

/* ---- what host/save_files.c takes from hos.h, hos_paths.h and windows.h ---- */
#define MAX_PATH 260
typedef unsigned long DWORD;
typedef void *HANDLE;
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define MOVEFILE_REPLACE_EXISTING 1
#define S 1000000000LL
typedef struct { DWORD dwLowDateTime, dwHighDateTime; } FILETIME;
typedef struct { FILETIME ftLastWriteTime; char cFileName[MAX_PATH]; } WIN32_FIND_DATAA;
static int MoveFileExA(const char *from, const char *to, int flags) {
    (void)flags;
    remove(to);
    return rename(from, to) == 0;
}
/* the files' folders: which have a save, when its account.sav was written (unix time; 0: the time is not told), and
   when each of its slots' caption.sav was (0: no such slot) */
static int has_save[3];
static int64_t save_time[3], slot_time[3][12];
static int finds;
static int file_of(const char *pattern) { return strstr(pattern, "user-3\\save\\") ? 2 : strstr(pattern, "user-2\\save\\") ? 1 : strstr(pattern, "user\\save\\") ? 0 : -1; }
static HANDLE FindFirstFileA(const char *pattern, WIN32_FIND_DATAA *fd) {
    const int file = file_of(pattern);
    finds++;
    CHECK(file >= 0);
    memset(fd, 0, sizeof *fd);
    if (file < 0 || !has_save[file]) return INVALID_HANDLE_VALUE;
    if (strstr(pattern, "\\save\\*")) {
        snprintf(fd->cFileName, sizeof fd->cFileName, ".");   /* (the folder itself first, as a listing has it) */
        return (HANDLE)(intptr_t)(100 + file);
    }
    const char *slot = strstr(pattern, "\\save\\0123456789abcdef0123456789abcdef\\slot_");
    CHECK(slot || strstr(pattern, "\\save\\0123456789abcdef0123456789abcdef\\account.sav") != NULL);
    CHECK(!slot || !strcmp(slot + 46, "\\caption.sav"));   /* (a slot's caption is named, never opened here; its progress never) */
    const int64_t at = slot ? slot_time[file][atoi(slot + 44) % 12] : save_time[file];
    if (slot && !at) return INVALID_HANDLE_VALUE;
    const uint64_t ft = at ? (uint64_t)at * 10000000ULL + 116444736000000000ULL : 0;
    fd->ftLastWriteTime.dwLowDateTime = (DWORD)(ft & 0xffffffffu), fd->ftLastWriteTime.dwHighDateTime = (DWORD)(ft >> 32);
    return (HANDLE)(intptr_t)(200 + file);
}
static int FindNextFileA(HANDLE h, WIN32_FIND_DATAA *fd) {
    if ((intptr_t)h < 100 || (intptr_t)h >= 200 || fd->cFileName[0] != '.') return 0;
    snprintf(fd->cFileName, sizeof fd->cFileName, "0123456789abcdef0123456789abcdef");
    return 1;
}
static int FindClose(HANDLE h) { (void)h; return 1; }
static char logged[1 << 14];
static void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    const size_t at = strlen(logged);
    vsnprintf(logged + at, sizeof logged - at - 2, fmt, ap);
    va_end(ap);
    strcat(logged, "\n");
}
static int said(const char *text) { return strstr(logged, text) != NULL; }

/* ---- the menu's side of HOS_OPT_FILES_* (gpu/vk/save_file_rows.h is tested by itself) ---- */
#include "save_files_constants.inc"
static int renderer, asked, ask_next;   /* renderer 0: none yet (rx_option answers what it is given) */
static char incoming[1200], row_text[8][1200];
static int incoming_n, row_bits[8], rows_added, rows_count = -1, answers[8], nanswers;
int rx_option(int id, int otherwise) {
    asked++;
    CHECK(id == HOS_OPT_FILES_ASK);
    if (!renderer) return otherwise;
    const int ask = ask_next;
    ask_next = 0;
    return ask;
}
void rx_option_set(int id, int value) {
    CHECK(renderer);
    if (id == HOS_OPT_FILES_TEXT) {
        CHECK(value > 0 && value < 256 && incoming_n + 1 < (int)sizeof incoming);
        incoming[incoming_n++] = (char)value;
    } else if (id == HOS_OPT_FILES_ADD) {
        incoming[incoming_n] = 0, incoming_n = 0;
        CHECK(rows_count < 0 && rows_added < 8);
        snprintf(row_text[rows_added], sizeof row_text[0], "%s", incoming);
        row_bits[rows_added++] = value;
    } else if (id == HOS_OPT_FILES_COUNT) {
        CHECK(rows_count < 0 && !incoming_n);
        rows_count = value;
    } else if (id == HOS_OPT_FILES_SAID) {
        CHECK(rows_count >= 0 && nanswers < 8);
        answers[nanswers++] = value;
    } else CHECK(!"an option of another feature set");
}

#include "save_files.h"
#include "save_files_actual.inc"

static char file_text[2048];
static const char *file(const char *dir, const char *name) {   /* a file of the game folder as it is now ("" when there is none) */
    char path[600];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "rb");
    file_text[f ? fread(file_text, 1, sizeof file_text - 1, f) : 0] = 0;
    if (f) fclose(f);
    return file_text;
}
static const char *file_at(const char *path) {   /* a file by its whole path, as the host names it */
    FILE *f = fopen(path, "rb");
    file_text[f ? fread(file_text, 1, sizeof file_text - 1, f) : 0] = 0;
    if (f) fclose(f);
    return file_text;
}
static int ends(const char *text, const char *end) { return strlen(text) >= strlen(end) && !strcmp(text + strlen(text) - strlen(end), end); }

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const char *game = argv[1], *mode = argv[2];
    char base[400];
    snprintf(base, sizeof base, "%s\\user", game);
    has_save[0] = 1, save_time[0] = 1763456789;
    slot_time[0][0] = 1763456000, slot_time[0][3] = 1763456789, slot_time[0][5] = 1763456789;   /* (slots 3 and 5 written together, last) */
    const char *dir = hos_save_files_start(game, base);
    if (!strcmp(mode, "off")) {   /* HOS_SAVE_FILES=0: the game's own folder, nothing read, written, said or asked of the menu */
        renderer = 1, ask_next = 2;
        CHECK(!hos_save_files_on() && dir == base);
        hos_save_files_frame(), hos_save_files_frame();
        hos_save_card_note("KokiriForest", 1, 12, 100 * S);   /* (and no card kept) */
        CHECK(!asked && !finds && !logged[0] && !rows_added && rows_count < 0 && !nanswers && !file(game, "triforce_files.txt")[0]);
    } else if (!strcmp(mode, "first")) {   /* no triforce_files.txt yet: file 1, the game's own folder, and no file made for that */
        CHECK(hos_save_files_on() && !strcmp(dir, base) && said("save files: file 1 of 3, \"File 1\": its saves are in ") && !said("chosen at the title"));
        CHECK(!file(game, "triforce_files.txt")[0]);
        hos_save_files_frame();   /* (no renderer yet: nothing named) */
        CHECK(asked == 1 && !rows_added && !finds);
        renderer = 1;
        hos_save_files_frame();   /* the files named, whole: name, when last saved; which has a save, which is this run's */
        CHECK(rows_added == 3 && rows_count == 3 && !nanswers);
        /* (when it was last saved, as the game's load list writes a time: 11/18/2025 1:06 a.m.) */
        const char *when_end = strstr(row_text[0], ".m.\n");
        CHECK(!strncmp(row_text[0], "File 1\n1", 8) && when_end && strstr(row_text[0], "/2025 ") && row_bits[0] == (HOS_FILE_SAVED | HOS_FILE_CURRENT));
        /* (where its slots are, up to a slot's number: the menu reads each one's picture and time itself; no card kept for it yet) */
        CHECK(when_end && !strncmp(when_end + 4, base, strlen(base)) && ends(row_text[0], "\\user\\save\\0123456789abcdef0123456789abcdef\\slot_\n|0|0|-1|"));
        CHECK(!strcmp(row_text[1], "File 2\n\n\n|0|0|-1|") && row_bits[1] == 0 && !strcmp(row_text[2], "File 3\n\n\n|0|0|-1|") && row_bits[2] == 0);
        hos_save_files_frame();
        CHECK(rows_added == 3);   /* (named once) */
        /* a file that is none, and this run's own: nothing kept, nothing said */
        ask_next = 9, hos_save_files_frame(), ask_next = 1, hos_save_files_frame();
        CHECK(!nanswers && !file(game, "triforce_files.txt")[0]);
        /* another file: kept as the next start's, with the time, and the menu told */
        ask_next = 2, hos_save_files_frame();
        CHECK(nanswers == 1 && answers[0] == 1 && said("save files: file 2, \"File 2\", chosen: the game starts again on it"));
        CHECK(strstr(file(game, "triforce_files.txt"), "\ncurrent=2\n") && strstr(file_text, "\nchosen=1") && !file(game, "triforce_files.txt.new")[0]);
        /* this run goes on with its own file: the same choice again is asked for again (the restart had not come yet) */
        ask_next = 2, hos_save_files_frame();
        CHECK(nanswers == 2 && answers[1] == 1);
    } else if (!strcmp(mode, "second")) {   /* the start that follows the choice: file 2's folder, and the menu told that it is that restart */
        has_save[1] = 1, save_time[1] = 0;
        CHECK(ends(dir, "\\user-2") && !strncmp(dir, base, strlen(base)) && said("file 2 of 3, \"File 2\"") && said("(chosen at the title: the game restarted for it)"));
        CHECK(strstr(file(game, "triforce_files.txt"), "\ncurrent=2\n") && !strstr(file_text, "chosen"));   /* (the choice is taken) */
        renderer = 1;
        hos_save_files_frame();
        /* (file 2: started on, its account.sav made, nothing saved in it yet: no save, as its card says) */
        CHECK(rows_count == (3 | HOS_FILES_CHOSEN) && row_bits[0] == HOS_FILE_SAVED && row_bits[1] == HOS_FILE_CURRENT);
        CHECK(!strcmp(row_text[1], "File 2\n\n\n|0|0|-1|"));   /* (a save whose time is not told: no time shown; no slot found: no picture) */
    } else {   /* a later start: the same file, the names the player gave, and the title asks again (an old choice is none) */
        CHECK(ends(dir, "\\user-2") && said("file 2 of 3, \"Bukwheat\"") && !said("chosen at the title"));
        CHECK(!strstr(file(game, "triforce_files.txt"), "chosen") && strstr(file_text, "\n1=Spanky\n2=Bukwheat\n3=File 3\n"));
        renderer = 1;
        hos_save_files_frame();
        /* (file 2's card, as its folder kept it when it was last played: its place, its stones and medallions, its hearts) */
        CHECK(rows_count == 3 && !strncmp(row_text[0], "Spanky\n", 7) && strstr(row_text[0], ".m.\n") && row_bits[1] == HOS_FILE_CURRENT);
        CHECK(!strcmp(row_text[1], "Bukwheat\n\n\nKokiri Forest|1c9|7|-1|") && ends(row_text[0], "\\slot_\n|0|0|-1|") && !strcmp(row_text[2], "File 3\n\n\n|0|0|-1|"));
        /* the file played: what the game tells of it is kept in its folder when it is not what is kept there already, and
           not more often than every five seconds; a map with no name (no save loaded) is not a place */
        char card[700];
        snprintf(card, sizeof card, "%s\\user-2\\triforce_card.txt", game);
        hos_save_card_note("KokiriForest", 0x1c9, 28, 10 * S);
        CHECK(strstr(file_at(card), "place=Kokiri Forest\r\nitems=1c9\r\nhearts=7"));   /* (as it was: the test's own bytes, not written again) */
        hos_save_card_note("", 0, 0, 11 * S), hos_save_card_note(NULL, 0, 0, 11 * S);
        hos_save_card_note("DeathMountain_Crater", 0x1cb, 32, 12 * S);
        CHECK(strstr(file_at(card), "\nplace=Death Mountain Crater\nitems=1cb\nhearts=8\n") && file_text[0] == '#');
        hos_save_card_note("LakeHylia", 0x1cb, 32, 13 * S);   /* (too soon after the last) */
        CHECK(strstr(file_at(card), "place=Death Mountain Crater\n"));
        hos_save_card_note("LakeHylia", 0xffff, 33, 18 * S);   /* (bits that are no item's are not kept; a life that is no count of hearts: none) */
        CHECK(strstr(file_at(card), "\nplace=Lake Hylia\nitems=1ff\nhearts=0\n"));
        /* the game saves: a slot's file opened to be written is the slot saved in last, kept with the card and its time; a
           path that names no slot is none */
        hos_save_card_wrote("save:/option.sav"), hos_save_card_wrote("save:/slot_12/caption.sav"), hos_save_card_wrote(NULL);
        hos_save_card_note("LakeHylia", 0x1ff, 33, 24 * S);
        CHECK(!strstr(file_at(card), "slot="));
        /* (kept at once, with what was last told: a save made in the pause menu, where Link is not updated, and the game closed) */
        hos_save_card_note("ZoraDomain", 0x1ff, 16, 22 * S);   /* (told, under five seconds after the last write: not kept by itself) */
        CHECK(strstr(file_at(card), "place=Lake Hylia\n"));
        hos_save_card_wrote("save:/slot_03/caption.sav");
        CHECK(strstr(file_at(card), "\nplace=Zora Domain\nitems=1ff\nhearts=4\nslot=3\nsaved=1"));
        const size_t once = strlen(file_text);
        hos_save_card_wrote("save:/slot_03/progress.sav");   /* (the same save's other file: the same time) */
        CHECK(strlen(file_at(card)) == once);
        hos_save_card_note("LakeHylia", 0x1ff, 33, 30 * S);
        CHECK(strstr(file_at(card), "\nplace=Lake Hylia\nitems=1ff\nhearts=0\nslot=3\nsaved=1") && !said("could not be written"));
        hos_save_card_wrote("save:/slot_01/caption.sav");   /* (another slot: that one, with the place as last told) */
        CHECK(strstr(file_at(card), "\nplace=Lake Hylia\nitems=1ff\nhearts=0\nslot=1\nsaved=1"));
        snprintf(card, sizeof card, "%s\\user-2\\triforce_card.txt.new", game);
        CHECK(!file_at(card)[0] && !said("could not be written"));
        ask_next = 1, hos_save_files_frame();   /* back to file 1 */
        CHECK(nanswers == 1 && answers[0] == 1 && strstr(file(game, "triforce_files.txt"), "\ncurrent=1\n") && strstr(file_text, "\n2=Bukwheat\n"));
    }
    if (!fails) printf("PASS\n");
    return fails != 0;
}
