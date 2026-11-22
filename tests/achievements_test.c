/* host/achievements.h alone (tests/test_achievements.py): the list's form and what is refused, when an achievement is
   earned, and the file that keeps the earned ones. With "names" as its argument it prints the built-in list's
   conditions instead, a line each, for the test to hold against gpu/vk/oot_cheat_items.h. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "achievements.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

static AchList list, again;

/* ---- a stand-in for the save data ---- */
static struct { int kind; const char *what; int value; } have[16];
static int nhave, asked;
static void set(int kind, const char *what, int value) {
    for (int i = 0; i < nhave; i++)
        if (have[i].kind == kind && !strcmp(have[i].what, what)) { have[i].value = value; return; }
    have[nhave].kind = kind, have[nhave].what = what, have[nhave++].value = value;
}
static int probe(void *ctx, int kind, const char *what) {
    CHECK(ctx == (void *)&asked);
    asked++;
    for (int i = 0; i < nhave; i++)
        if (have[i].kind == kind && !strcmp(have[i].what, what)) return have[i].value;
    return -1;
}

static const char FORM[] =
    "stray line\n# a comment\n[One]\r\nabout:  First.  \r\nitem A_b 3\r\n\tflag F.x-1\r\n\r\n"
    "[No conditions]\nabout: x\n"
    "[Bad line]\nitem A\nwhat is this\n"
    "[One]\nitem Dup\n"
    "[]\nitem A\n"
    "[A name that is too long to be an achievement's]\nitem A\n"
    "[Bad count]\nitem A 0\n"
    "[Bad count 2]\nitem A 10000\n"
    "[Bad count 3]\nitem A 3x\n"
    "[Flag count]\nflag F 2\n"
    "[Bad name]\nitem A$b\n"
    "[No name]\nitem\n"
    "[No bracket\nitem A\n"
    "[ Last ]\n# its line about it is left out\nitem Z 2";

static void built_in(int print) {
    int refused = 0;
    memset(&list, 0, sizeof list);
    const int n = ach_parse(&list, ACH_BUILTIN, &refused);
    if (print) {
        for (int i = 0; i < list.n; i++)
            for (int k = 0; k < list.a[i].nconds; k++) printf("%c %s %d\n", list.a[i].conds[k].kind, list.a[i].conds[k].what, list.a[i].conds[k].least);
        return;
    }
    CHECK(n == 25 && list.n == 25 && refused == 0);
    for (int i = 0; i < list.n; i++) {
        const Ach *a = &list.a[i];
        CHECK(a->name[0] && a->about[0] && a->nconds >= 1 && !a->earned && a->key == ach_key(a->name));
        CHECK(ach_find(&list, a->key) == i);
        for (int k = 0; k < a->nconds; k++) CHECK(a->conds[k].kind == ACH_ITEM && a->conds[k].least >= 1);
    }
    CHECK(ach_key("") == 2166136261u && ach_key("a") == 0xe40c292cu);
    CHECK(list.a[0].icon == (1 | 1 << 4) && list.a[1].icon == 4 && list.a[24].icon == (6 | 7 << 4));   /* (sword green, a note, shield silver) */
}

static void form(void) {
    int refused = 0;
    memset(&list, 0, sizeof list);
    CHECK(ach_parse(&list, FORM, &refused) == 2 && list.n == 2);
    CHECK(refused == 12);
    const Ach *one = &list.a[0], *last = &list.a[1];
    CHECK(!strcmp(one->name, "One") && !strcmp(one->about, "First.") && one->nconds == 2);
    CHECK(one->conds[0].kind == ACH_ITEM && !strcmp(one->conds[0].what, "A_b") && one->conds[0].least == 3);
    CHECK(one->conds[1].kind == ACH_FLAG && !strcmp(one->conds[1].what, "F.x-1") && one->conds[1].least == 1);
    CHECK(!strcmp(last->name, "Last") && !last->about[0] && last->nconds == 1 && last->conds[0].least == 2 && !strcmp(last->conds[0].what, "Z"));
    CHECK(ach_parse(&list, "", &refused) == 0 && ach_parse(&list, "\n\n# nothing\n", &refused) == 0 && refused == 12 && list.n == 2);
    CHECK(ach_parse(&list, "[Whole]\nitem W\n", NULL) == 1 && list.n == 3);

    /* an icon: a shape, and a tone or none (gold); without the line a gold star; anything else is no achievement */
    CHECK(ach_icon_parse("star", 4) == 0 && ach_icon_parse("gem blue", 8) == (2 | 3 << 4) && ach_icon_parse("shield \t silver", 15) == (6 | 7 << 4));
    CHECK(ach_icon_parse("", 0) < 0 && ach_icon_parse("circle", 6) < 0 && ach_icon_parse("gem pink", 8) < 0 && ach_icon_parse("gem blue x", 10) < 0);
    CHECK(ach_icon_parse("gemblue", 7) < 0 && ach_icon_parse("Gem", 3) < 0 && ach_icon_parse("blue", 4) < 0);
    CHECK(one->icon == 0 && list.a[2].icon == 0);
    refused = 0;
    CHECK(ach_parse(&list, "[Pictured]\nicon:  medal   purple \nitem P\n[Unpictured]\nicon: medal mauve\nitem P\n[Bare]\nicon:\nitem P\n", &refused) == 1);
    CHECK(refused == 2 && list.a[list.n - 1].icon == (3 | 4 << 4));
    refused = 12;

    /* ACH_CONDS conditions are an achievement, one more is none; a name of ACH_NAME bytes is one; a name's 95 bytes */
    static char text[1 << 16];
    for (int over = 0; over < 2; over++) {
        int at = snprintf(text, sizeof text, "[%s]\n", over ? "Over" : "Full");
        for (int i = 0; i < ACH_CONDS + over; i++) at += snprintf(text + at, sizeof text - (size_t)at, "item I%d\n", i);
        refused = 0;
        CHECK(ach_parse(&list, text, &refused) == !over && refused == over);
    }
    CHECK(ach_parse(&list, "[0123456789012345678901234567890123456789]\nitem A\n", NULL) == 1 && strlen(list.a[list.n - 1].name) == ACH_NAME);
    memset(text, 'n', sizeof text);
    memcpy(text, "[Long]\nflag ", 12);
    text[12 + ACH_WHAT - 1] = 0;
    CHECK(ach_parse(&list, text, NULL) == 1 && strlen(list.a[list.n - 1].conds[0].what) == ACH_WHAT - 1);
    text[12 + ACH_WHAT - 1] = 'n', text[12 + ACH_WHAT] = 0;
    memcpy(text, "[Lon2]", 6);
    refused = 0;
    CHECK(ach_parse(&list, text, &refused) == 0 && refused == 1);

    /* no more than ACH_MAX */
    memset(&list, 0, sizeof list);
    int at = 0;
    for (int i = 0; i < ACH_MAX + 2; i++) at += snprintf(text + at, sizeof text - (size_t)at, "[N%d]\nitem A\n", i);
    refused = 0;
    CHECK(ach_parse(&list, text, &refused) == ACH_MAX && list.n == ACH_MAX && refused == 2);
}

static void earning(void) {
    int fresh[4];
    memset(&list, 0, sizeof list);
    CHECK(ach_parse(&list, FORM, NULL) == 2);
    CHECK(ach_check(&list, probe, &asked, 100, fresh, 4) == 0 && !list.a[0].earned && !list.a[1].earned);
    set(ACH_ITEM, "A_b", 3);
    CHECK(ach_check(&list, probe, &asked, 100, fresh, 4) == 0);   /* (the flag is not in the save data) */
    set(ACH_FLAG, "F.x-1", 0);
    CHECK(ach_check(&list, probe, &asked, 100, fresh, 4) == 0);
    set(ACH_FLAG, "A_b", 1), set(ACH_ITEM, "F.x-1", 9);            /* (an item of a flag's name is not that flag) */
    CHECK(ach_check(&list, probe, &asked, 100, fresh, 4) == 0);
    set(ACH_FLAG, "F.x-1", 1), set(ACH_ITEM, "A_b", 2);
    CHECK(ach_check(&list, probe, &asked, 100, fresh, 4) == 0);   /* (one too few) */
    set(ACH_ITEM, "A_b", 3);
    CHECK(ach_check(&list, probe, &asked, 101, fresh, 4) == 1 && fresh[0] == 0 && list.a[0].earned && list.a[0].when == 101 && !list.a[1].earned);
    CHECK(ach_earned_count(&list) == 1);
    /* earned stays earned, and is not asked about again */
    set(ACH_ITEM, "A_b", 0), set(ACH_FLAG, "F.x-1", 0);
    asked = 0;
    CHECK(ach_check(&list, probe, &asked, 102, fresh, 4) == 0 && asked == 1 && list.a[0].earned && list.a[0].when == 101);
    set(ACH_ITEM, "Z", 1);
    CHECK(ach_check(&list, probe, &asked, 102, fresh, 4) == 0);
    set(ACH_ITEM, "Z", 7);
    CHECK(ach_check(&list, probe, &asked, 103, fresh, 4) == 1 && fresh[0] == 1 && list.a[1].when == 103 && ach_earned_count(&list) == 2);
    asked = 0;
    CHECK(ach_check(&list, probe, &asked, 104, fresh, 4) == 0 && asked == 0);

    /* no more than the caller has room for: the rest at the next call */
    memset(&list, 0, sizeof list);
    CHECK(ach_parse(&list, "[P]\nitem Z\n[Q]\nitem Z\n[R]\nitem Z\n", NULL) == 3);
    CHECK(ach_check(&list, probe, &asked, 1, fresh, 2) == 2 && fresh[0] == 0 && fresh[1] == 1 && !list.a[2].earned);
    CHECK(ach_check(&list, probe, &asked, 2, fresh, 2) == 1 && fresh[0] == 2 && list.a[2].when == 2);
}

static void kept(void) {
    static char text[4096], more[4096];
    int fresh[4];
    memset(&list, 0, sizeof list);
    CHECK(ach_parse(&list, FORM, NULL) == 2);
    size_t n = ach_earned_write(&list, text, sizeof text);
    CHECK(n == strlen(text) && text[0] == '#' && strchr(text, '\n') == text + n - 1);   /* (none earned: the first line alone) */
    set(ACH_ITEM, "Z", 2);
    CHECK(ach_check(&list, probe, &asked, 1700000000, fresh, 4) == 1);
    n = ach_earned_write(&list, text, sizeof text);
    char line[80];
    snprintf(line, sizeof line, "\n%08x 1700000000 Last\n", (unsigned)ach_key("Last"));
    CHECK(n && strstr(text, line) && !strstr(text, " One\n"));
    CHECK(ach_earned_write(&list, more, 40) == 0 && ach_earned_write(&list, more, n) == 0 && ach_earned_write(&list, more, n + 1) == n);

    /* the next start: the same lists, the file read */
    memset(&again, 0, sizeof again);
    CHECK(ach_parse(&again, FORM, NULL) == 2);
    CHECK(ach_earned_read(&again, text) == 1 && !again.a[0].earned && again.a[1].earned && again.a[1].when == 1700000000 && !again.norphans);
    CHECK(ach_earned_read(&again, text) == 0);   /* (read twice: marked once) */

    /* a line of an achievement no list has is kept as it is, once; what is not such a line is dropped */
    snprintf(more, sizeof more, "%sdeadbeef 5 Gone from the lists\r\nhello\n1234 5 short key\ndeadbeef 6 Gone again\n0000000g 1 x\n%08x -3 One\n", text,
             (unsigned)ach_key("One"));
    memset(&again, 0, sizeof again);
    CHECK(ach_parse(&again, FORM, NULL) == 2);
    CHECK(ach_earned_read(&again, more) == 2 && again.a[0].earned && again.a[0].when == 0 && again.norphans == 1);
    CHECK(!strcmp(again.orphans[0], "deadbeef 5 Gone from the lists"));
    n = ach_earned_write(&again, text, sizeof text);
    CHECK(n && strstr(text, "\ndeadbeef 5 Gone from the lists\n") && !strstr(text, "hello") && !strstr(text, "short key") && !strstr(text, "Gone again"));
    CHECK(strstr(text, " 0 One\n") && strstr(text, " 1700000000 Last\n"));
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "names")) return built_in(1), 0;
    built_in(0);
    form();
    earning();
    kept();
    if (!fails) printf("PASS\n");
    return fails != 0;
}
