/* Achievements on the host's side: host/achievements.c's own text (achievements_actual.inc, cut by
   tests/test_achievements.py) against a stand-in save data, a stand-in menu and a game folder of the test's.
   Run three times: "off" with HOS_ACHIEVEMENTS=0, then "first" and "second" with it on the same folder, the second the
   next start. */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

/* ---- what host/achievements.c takes from hos.h, hos_paths.h, windows.h and menu_sound.c ---- */
#define MAX_PATH 260
typedef unsigned long DWORD;
#define MOVEFILE_REPLACE_EXISTING 1
static char game_dir[400];
static DWORD hos_game_path_a(char *buf, DWORD size) { return (DWORD)snprintf(buf, size, "%s/Triforce.exe", game_dir); }
static int MoveFileExA(const char *from, const char *to, int flags) {
    (void)flags;
    remove(to);
    return rename(from, to) == 0;
}
static char logged[1 << 14];
static void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    const size_t at = strlen(logged);
    vsnprintf(logged + at, sizeof logged - at - 2, fmt, ap);
    va_end(ap);
    strcat(logged, "\n");
}
static int said(const char *text) {   /* how often the log has it */
    int n = 0;
    for (const char *p = logged; (p = strstr(p, text)) != NULL; p++) n++;
    return n;
}
#include "achievements_constants.inc"
static int sounds;
static int64_t sound_at;
static void hos_menu_sound_play(int id, int64_t now_ns) {
    CHECK(id == HOS_MENU_SOUND_SYS_DECIDE);
    sounds++, sound_at = now_ns;
}

/* ---- the menu's side of HOS_OPT_ACH_* (gpu/vk/achievement_rows.h is tested by itself) ---- */
static int renderer;   /* 0: no renderer yet (rx_option answers what it is given) */
static char incoming[600], row_text[160][400], notice_day[16][32];
static int incoming_n, row_bits[160], rows_added, rows_shown = -1, notices[16], nnotices;
int rx_option(int id, int otherwise) {
    if (!renderer) return otherwise;
    CHECK(id == HOS_OPT_ACH_ASK);
    return 1;
}
void rx_option_set(int id, int value) {
    CHECK(renderer);
    if (id == HOS_OPT_ACH_TEXT) {
        CHECK(value > 0 && value < 256 && incoming_n + 1 < (int)sizeof incoming);
        incoming[incoming_n++] = (char)value;
    } else if (id == HOS_OPT_ACH_ADD) {
        incoming[incoming_n] = 0, incoming_n = 0;
        CHECK(rows_shown < 0 && rows_added < 160);
        snprintf(row_text[rows_added], sizeof row_text[0], "%s", incoming);
        row_bits[rows_added++] = value;
    } else if (id == HOS_OPT_ACH_COUNT) {
        CHECK(rows_shown < 0 && !incoming_n);
        rows_shown = value;
    } else if (id == HOS_OPT_ACH_EARNED) {
        incoming[incoming_n] = 0, incoming_n = 0;
        CHECK(rows_shown >= 0 && value >= 0 && value < rows_shown && nnotices < 16);   /* (never before the list is whole) */
        snprintf(notice_day[nnotices], sizeof notice_day[0], "%s", incoming);
        notices[nnotices++] = value;
    } else CHECK(!"an option of another feature set");
}

#include "achievements.h"
#include "achievements_actual.inc"

/* ---- a stand-in for the save data ---- */
static struct { int kind; const char *what; int value; } have[16];
static int nhave, asked;
static void set(int kind, const char *what, int value) { have[nhave].kind = kind, have[nhave].what = what, have[nhave++].value = value; }
static int probe(void *ctx, int kind, const char *what) {
    (void)ctx;
    asked++;
    for (int i = 0; i < nhave; i++)
        if (have[i].kind == kind && !strcmp(have[i].what, what)) return have[i].value;
    return -1;
}
#define S 1000000000LL
static void at(int64_t seconds_x10) { hos_achievements_check(probe, NULL, seconds_x10 * (S / 10)); }
static int row_of(const char *name) {   /* the place the menu was given an achievement at, -1 none */
    const size_t n = strlen(name);
    for (int i = 0; i < rows_added; i++)
        if (!strncmp(row_text[i], name, n) && row_text[i][n] == '\n') return i;
    return -1;
}
static int is_day(const char *text) {   /* "2026-11-18" */
    return strlen(text) == 10 && text[4] == '-' && text[7] == '-' && text[0] == '2';
}

static char file_text[8192];
static const char *file(const char *name) {   /* a file of the game folder as it is now ("" when there is none) */
    char path[600];
    snprintf(path, sizeof path, "%s/%s", game_dir, name);
    FILE *f = fopen(path, "rb");
    file_text[f ? fread(file_text, 1, sizeof file_text - 1, f) : 0] = 0;
    if (f) fclose(f);
    return file_text;
}
static int lines(const char *text) {
    int n = 0;
    for (; *text; text++) n += *text == '\n';
    return n;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    snprintf(game_dir, sizeof game_dir, "%s", argv[1]);
    set(ACH_ITEM, "Weapon_Sword_Kokiri", 1), set(ACH_ITEM, "Item_Stone_Forest", 1), set(ACH_ITEM, "Item_Stone_Fire", 1);
    set(ACH_ITEM, "Item_Stone_Water", 1), set(ACH_FLAG, "My_Flag", 1), set(ACH_ITEM, "Item_Token_Gold", 9);
    if (!strcmp(argv[2], "off")) {   /* turned off: nothing asked of the save data or the menu, nothing read, written or said */
        CHECK(!hos_achievements_on());
        renderer = 1;
        hos_achievements_frame(), at(10), hos_achievements_frame(), at(100);
        CHECK(!asked && !logged[0] && !rows_added && rows_shown < 0 && !nnotices && !sounds && !ready && !file("triforce_achievements.txt")[0]);
    } else if (!strcmp(argv[2], "first")) {
        CHECK(hos_achievements_on());
        hos_achievements_frame();   /* the first present, before the renderer answers: the lists are read, nothing is named */
        CHECK(said("achievements: 26 (1 of achievements.txt), 0 earned so far") == 1 && said("achievements: 2 left out") == 1);
        CHECK(!rows_added && rows_shown < 0);
        at(20);   /* six earned before the menu has the list: written and said at once, shown only once it has */
        CHECK(said("achievements: earned \"") == 6 && said("earned \"A Sword of Your Own\" (1 of 26)") == 1 && said("earned \"Mine\" (6 of 26)") == 1);
        CHECK(said("earned \"Three Stones\"") == 1 && !said("Spider Hunter") && !said("could not be written"));
        CHECK(lines(file("triforce_achievements.txt")) == 7 && strstr(file_text, " A Sword of Your Own\n") && strstr(file_text, " Mine\n"));
        CHECK(!nnotices && !sounds);
        renderer = 1;
        hos_achievements_frame();   /* the list named, whole, in its order: name, the line about it, the day; the icon and earned */
        CHECK(rows_added == 26 && rows_shown == 26 && !nnotices);
        CHECK(!strncmp(row_text[0], "A Sword of Your Own\nFind a blade in the forest.\n", 48) && is_day(row_text[0] + 48));
        CHECK(row_bits[0] == (1 | 1 << 4 | HOS_ACH_EARNED));                 /* (sword green, earned) */
        CHECK(!strcmp(row_text[1], "First Melody\nLearn the royal family's song.\n") && row_bits[1] == 4);   /* (a note, gold; not earned: no day) */
        CHECK(row_of("Mine") == 25 && row_bits[25] == (2 | 3 << 4 | HOS_ACH_EARNED) && row_bits[row_of("Twice as Tough")] == (6 | 7 << 4));
        hos_achievements_frame(), hos_achievements_frame();
        CHECK(rows_added == 26);   /* (named once) */
        /* shown one at a time, each for its 4.5 s, in the list's order, with the sound and the day */
        at(30);
        CHECK(nnotices == 1 && sounds == 1 && sound_at == 3 * S && notices[0] == 0 && is_day(notice_day[0]));
        at(40), at(74);
        CHECK(nnotices == 1);
        at(75);
        CHECK(nnotices == 2 && sounds == 2 && notices[1] == row_of("Forest's Thanks"));
        for (int t = 120; t <= 400; t += 10) at(t);
        CHECK(nnotices == 6 && sounds == 6 && notices[5] == 25);
        CHECK(said("achievements: earned \"") == 6 && said("achievements: 26 (") == 1 && lines(file("triforce_achievements.txt")) == 7);
    } else {
        renderer = 1;
        hos_achievements_frame();   /* the next start: what was earned is, and is neither said nor shown again */
        CHECK(said("achievements: 26 (1 of achievements.txt), 6 earned so far") == 1 && rows_shown == 26);
        at(10);
        CHECK(!said("earned \"") && !nnotices && !sounds);
        CHECK((row_bits[0] & HOS_ACH_EARNED) && !(row_bits[row_of("Spider Hunter")] & HOS_ACH_EARNED));
        have[5].value = 10;   /* (the tenth token) */
        at(20);
        CHECK(said("earned \"Spider Hunter\" (7 of 26)") == 1 && nnotices == 1 && notices[0] == row_of("Spider Hunter") && is_day(notice_day[0]));
        /* the file whole again: the seven, and the line of an achievement no list has now, as it was */
        CHECK(lines(file("triforce_achievements.txt")) == 9 && strstr(file_text, " Spider Hunter\n") && strstr(file_text, "\ndeadbeef 5 Gone\n"));
        CHECK(!file("triforce_achievements.txt.new")[0]);
    }
    if (!fails) printf("PASS\n");
    return fails != 0;
}
