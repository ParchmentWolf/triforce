/* host/save_files.h alone (tests/test_save_files.py): the form of triforce_files.txt and what is not taken from it, the
   files' folders, and the start that follows a choice. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "save_files.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

int main(void) {
    SaveFiles f, g;
    char text[512], dir[64];

    /* no file, or an empty one: file 1, and the names "File N" */
    save_files_parse(&f, "");
    CHECK(f.current == 0 && f.chosen == 0 && !strcmp(f.names[0], "File 1") && !strcmp(f.names[1], "File 2") && !strcmp(f.names[2], "File 3"));

    /* its three lines, in any order, with Windows' line ends; what is none of them is passed over */
    save_files_parse(&f, "# a note\r\n2=Bukwheat\r\ncurrent=2\r\nchosen=1763456789\r\nsomething else\r\n1=Spanky  \r\n=x\n4=No such file\n0=Nor this\n");
    CHECK(f.current == 1 && f.chosen == 1763456789 && !strcmp(f.names[0], "Spanky") && !strcmp(f.names[1], "Bukwheat") && !strcmp(f.names[2], "File 3"));

    /* a file's number that is none: file 1; a time that is none: no choice; a name that is empty or has a control: not taken */
    save_files_parse(&f, "current=0\nchosen=-5\n1=\n2=a\tb\n3=Last line, no line feed");
    CHECK(f.current == 0 && f.chosen == 0 && !strcmp(f.names[0], "File 1") && !strcmp(f.names[1], "File 2") && !strcmp(f.names[2], "Last line, no line feed"));
    save_files_parse(&f, "current=4\n");
    CHECK(f.current == 0);
    save_files_parse(&f, "current=3\ncurrent=x\n");
    CHECK(f.current == 2);

    /* a name cut at SAVE_FILE_NAME bytes, never inside a letter */
    save_files_parse(&f, "1=abcdefghijklmnopqrstuvwxyz\n2=abcdefghijklmnopqrstuvw\xc3\xa9z\n");
    CHECK(!strcmp(f.names[0], "abcdefghijklmnopqrstuvwx") && strlen(f.names[0]) == SAVE_FILE_NAME);
    CHECK(!strcmp(f.names[1], "abcdefghijklmnopqrstuvw"));   /* (23 letters and a letter of two bytes: 25, one too many) */

    /* written and read back */
    save_files_parse(&f, "current=3\nchosen=1700000000\n1=Spanky\n3=Third one\n");
    const size_t n = save_files_write(&f, text, sizeof text);
    CHECK(n == strlen(text) && text[0] == '#' && strstr(text, "\ncurrent=3\n") && strstr(text, "\nchosen=1700000000\n") && strstr(text, "\n1=Spanky\n2=File 2\n3=Third one\n"));
    save_files_parse(&g, text);
    CHECK(!memcmp(&f, &g, sizeof f));
    f.chosen = 0;
    CHECK(save_files_write(&f, text, sizeof text) && !strstr(text, "chosen"));   /* (no choice: no line) */
    CHECK(save_files_write(&f, text, 20) == 0 && save_files_write(&f, text, 100) == 0);

    /* the folders: file 1 the game's own, the others its name with their number */
    CHECK(save_files_folder("C:\\Games\\Triforce\\user", 0, dir, sizeof dir) && !strcmp(dir, "C:\\Games\\Triforce\\user"));
    CHECK(save_files_folder("C:\\Games\\Triforce\\user", 1, dir, sizeof dir) && !strcmp(dir, "C:\\Games\\Triforce\\user-2"));
    CHECK(save_files_folder("/home/me/.local/share/hookshot/", 2, dir, sizeof dir) && !strcmp(dir, "/home/me/.local/share/hookshot-3"));
    CHECK(save_files_folder("user\\", 0, dir, sizeof dir) && !strcmp(dir, "user"));
    CHECK(!save_files_folder("user", 3, dir, sizeof dir) && !save_files_folder("user", -1, dir, sizeof dir));
    CHECK(!save_files_folder("user", 1, dir, 6) && save_files_folder("user", 1, dir, 7) && !save_files_folder("user", 0, dir, 4));

    /* the start that follows a choice: within SAVE_FILES_CHOSEN_S of it, and not before it */
    f.chosen = 1000;
    CHECK(save_files_chosen_now(&f, 1000) && save_files_chosen_now(&f, 1000 + SAVE_FILES_CHOSEN_S) && !save_files_chosen_now(&f, 1001 + SAVE_FILES_CHOSEN_S));
    CHECK(!save_files_chosen_now(&f, 999));
    f.chosen = 0;
    CHECK(!save_files_chosen_now(&f, 5));

    /* a file's card: a map's own name as words */
    char place[SAVE_CARD_PLACE + 1], small[8];
    save_card_place("KokiriForest", place, sizeof place);
    CHECK(!strcmp(place, "Kokiri Forest"));
    save_card_place("Inside_GanonCastle01", place, sizeof place);
    CHECK(!strcmp(place, "Inside Ganon Castle 01"));
    save_card_place("HyruleField", place, sizeof place); CHECK(!strcmp(place, "Hyrule Field"));
    save_card_place("DekuTree_B1F", place, sizeof place); CHECK(!strcmp(place, "Deku Tree B1F"));
    save_card_place("Area2Boss", place, sizeof place); CHECK(!strcmp(place, "Area 2 Boss"));
    save_card_place("__Lost__Woods__", place, sizeof place); CHECK(!strcmp(place, "Lost Woods"));
    save_card_place("", place, sizeof place); CHECK(!place[0]);
    /* (a map that says Link's age at its name's end: the place without it, as the game's own load list has it) */
    save_card_place("KokiriForest_Adult", place, sizeof place); CHECK(!strcmp(place, "Kokiri Forest"));
    save_card_place("KokiriForestChild", place, sizeof place); CHECK(!strcmp(place, "Kokiri Forest"));
    save_card_place("Adult", place, sizeof place); CHECK(!strcmp(place, "Adult"));
    save_card_place("ChildhoodHome", place, sizeof place); CHECK(!strcmp(place, "Childhood Home"));
    save_card_place("KokiriForest", small, sizeof small); CHECK(!strcmp(small, "Kokiri") && strlen(small) < sizeof small);
    /* hearts: the game's count of Link's life, in quarters of a heart; what is no such count: none */
    CHECK(save_card_hearts(12) == 3 && save_card_hearts(28) == 7 && save_card_hearts(80) == 20 && save_card_hearts(84) == 0);
    CHECK(save_card_hearts(0) == 0 && save_card_hearts(8) == 0 && save_card_hearts(13) == 0 && save_card_hearts(-12) == 0 && save_card_hearts(7) == 0);
    /* triforce_card.txt: read, written and read back; what is none of its lines passed over, numbers that are none 0 */
    SaveCard c, d;
    save_card_parse(&c, "# a note\r\nplace=Kokiri Forest\r\nitems=1c9\r\nhearts=7\r\nwhat=this\r\n");
    CHECK(!strcmp(c.place, "Kokiri Forest") && c.items == 0x1c9 && c.hearts == 7);
    const size_t cn = save_card_write(&c, text, sizeof text);
    CHECK(cn == strlen(text) && text[0] == '#' && strstr(text, "\nplace=Kokiri Forest\nitems=1c9\nhearts=7\n"));
    save_card_parse(&d, text);
    CHECK(save_card_same(&c, &d) && save_card_write(&c, text, 40) == 0);
    d.hearts = 8; CHECK(!save_card_same(&c, &d));
    d = c, d.items ^= 1; CHECK(!save_card_same(&c, &d));
    d = c, d.place[0] = 'L'; CHECK(!save_card_same(&c, &d));
    save_card_parse(&c, "items=fffff\nhearts=21\nplace=A|B\tC\n");
    CHECK(c.items == 0x1ff && c.hearts == 0 && !strcmp(c.place, "A B C"));   /* (the bar and a control are the list's own: spaces) */
    save_card_parse(&c, "");
    CHECK(!c.place[0] && !c.items && !c.hearts && !c.slot1 && !c.saved);
    /* the slot the game saved in last, and when: kept with the card; a slot that is none is not known */
    save_card_parse(&c, "place=Kokiri Forest Adult\nitems=1\nhearts=3\nslot=3\nsaved=1763456789\n");
    CHECK(c.slot1 == 4 && c.saved == 1763456789 && !strcmp(c.place, "Kokiri Forest"));   /* (and a place kept with its age: without) */
    CHECK(save_card_write(&c, text, sizeof text) && strstr(text, "\nhearts=3\nslot=3\nsaved=1763456789\n"));
    save_card_parse(&d, text);
    CHECK(save_card_same(&c, &d));
    d.slot1 = 1; CHECK(!save_card_same(&c, &d));
    d = c; d.saved++; CHECK(!save_card_same(&c, &d));
    save_card_parse(&c, "slot=12\nsaved=-4\n"); CHECK(!c.slot1 && !c.saved);
    save_card_parse(&c, "slot=0\n"); CHECK(c.slot1 == 1);
    save_card_parse(&c, "slot=\nslot=x\n"); CHECK(!c.slot1);
    CHECK(save_card_slot_of("save:/slot_03/caption.sav") == 3 && save_card_slot_of("save:/slot_11/progress.sav") == 11 && save_card_slot_of("save:\\slot_00\\x") == 0);
    CHECK(save_card_slot_of("save:/slot_12/caption.sav") < 0 && save_card_slot_of("save:/option.sav") < 0 && save_card_slot_of("save:/slot_3/x") < 0);
    CHECK(save_card_slot_of("save:/slot_03") < 0 && save_card_slot_of("") < 0 && save_card_slot_of(NULL) < 0);
    save_card_parse(&c, "hearts=x\nitems=\nplace=\n");
    CHECK(!c.place[0] && !c.items && !c.hearts);

    if (!fails) printf("PASS\n");
    return fails != 0;
}
