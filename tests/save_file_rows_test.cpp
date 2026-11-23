// gpu/vk/save_file_rows.h alone (tests/test_save_files.py): the files as the host names them, the file chosen and what the
// host says of it, and the choice under the keys.
#include <cstdio>
#include <cstring>
#include "save_file_rows.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

namespace sf = save_file_rows;

static void say(sf::List& list, const char* text) {
    for (const char* p = text; *p; p++) list.text((unsigned char)*p);
}

int main() {
    static sf::List list;
    // nothing shown, asked or chosen until the list is whole
    say(list, "Spanky\n2026-11-18 08:41");
    list.add(sf::kSaved);
    say(list, "Bukwheat\n");
    list.add(sf::kSaved | sf::kCurrent | 64);
    list.add(0);   // (no name, no save)
    CHECK(list.shown() == 0 && !list.asks() && list.current() == -1 && !list.choose(0) && list.take_ask() == 0);
    list.done(3);
    CHECK(list.shown() == 3 && list.asks() && list.current() == 1);
    CHECK(!strcmp(list.names[0], "Spanky") && !strcmp(list.whens[0], "2026-11-18 08:41") && list.saved(0));
    CHECK(!strcmp(list.names[1], "Bukwheat") && !list.whens[1][0] && list.saved(1) && list.bits[1] == (sf::kSaved | sf::kCurrent));
    CHECK(!strcmp(list.names[2], "(no name)") && !list.saved(2) && !list.saved(3) && !list.saved(-1));
    // a list sent again changes nothing
    say(list, "Again\n");
    list.add(sf::kCurrent);
    list.done(1);
    CHECK(list.shown() == 3 && list.current() == 1 && !strcmp(list.names[0], "Spanky"));

    // the file this run plays: played at once, nothing asked of the host
    CHECK(list.choose(1) && list.take_ask() == 0);
    // another: asked of the host, once; its word taken once
    CHECK(!list.choose(0) && list.take_ask() == 1 && list.take_ask() == 0 && list.take_said() == sf::kNothing);
    list.said(1);
    CHECK(list.take_said() == sf::kRestart && list.take_said() == sf::kNothing);
    CHECK(!list.choose(2) && list.take_ask() == 3);
    list.said(2);
    CHECK(list.take_said() == sf::kFailed);
    list.said(7);
    CHECK(list.take_said() == sf::kNothing);
    list.said(1);
    CHECK(!list.choose(0) && list.take_said() == sf::kNothing);   // (a word that came before this ask is not its answer)
    CHECK(!list.choose(3) && !list.choose(-1) && list.take_ask() == 1 && list.take_ask() == 0);   // (no such file: nothing more asked)

    // the start that follows a choice: the title asks there too; fewer files than named, and more than there is room for
    static sf::List after;
    say(after, "One\n");
    after.add(sf::kCurrent);
    say(after, "Two\n");
    after.add(0);
    after.done(2 | sf::kChosen);
    CHECK(after.shown() == 2 && after.asks() && after.chosen() && after.current() == 0 && !list.chosen());
    static sf::List many;
    for (int i = 0; i < 6; i++) many.text('a' + i), many.add(0);
    many.done(6);
    CHECK(many.shown() == sf::kSlots && many.asks() && many.current() == -1 && !many.choose(0) && many.take_ask() == 1);
    // a name longer than its room: cut, never inside a letter
    static sf::List wide;
    for (int i = 0; i < 23; i++) wide.text('n');
    wide.text(0xC3), wide.text(0xA9), wide.text('\n');
    for (int i = 0; i < 60; i++) wide.text('w');
    wide.add(0);
    wide.done(1);
    CHECK(strlen(wide.names[0]) == 23 && strlen(wide.whens[0]) <= (size_t)sf::kWhen - 1);

    // a file's picture and its card: the file the picture is in; where it was played last, its stones and medallions, its hearts
    static sf::List cards;
    say(cards, "One\n11/18/2026 1:40 a.m.\nC:\\Games\\Triforce\\user\\save\\0123\\slot_03\\caption.sav\nKokiri Forest|1c9|7");
    cards.add(sf::kSaved | sf::kCurrent);
    say(cards, "Two\n\n\n|0|0");
    cards.add(0);
    say(cards, "Three\n\n\nLake Hylia|ffff|21");   // (bits that are no item's, and more hearts than there are: not kept)
    cards.add(0);
    cards.done(3);
    CHECK(!strcmp(cards.pictures[0], "C:\\Games\\Triforce\\user\\save\\0123\\slot_03\\caption.sav") && !strcmp(cards.whens[0], "11/18/2026 1:40 a.m."));
    CHECK(!strcmp(cards.places[0], "Kokiri Forest") && cards.items[0] == 0x1c9 && cards.hearts[0] == 7);
    CHECK(cards.slots[0] == -1 && !cards.made[0][0] && cards.slots[1] == -1 && cards.slots[2] == -1);   // (a card without the slot saved in last)
    static sf::List slotted;   // (the slot the game saved in last, and when: a slot that is none is not known)
    say(slotted, "A\n\n\nKokiri Forest|1c9|7|3|11/18/2026 1:43 a.m.");
    slotted.add(sf::kSaved);
    say(slotted, "B\n\n\nLake Hylia|0|3|-1|");
    slotted.add(sf::kSaved);
    say(slotted, "C\n\n\nLake Hylia|0|3|12|11/18/2026 1:43 a.m.");
    slotted.add(sf::kSaved);
    slotted.done(3);
    CHECK(slotted.slots[0] == 3 && !strcmp(slotted.made[0], "11/18/2026 1:43 a.m.") && slotted.hearts[0] == 7 && !strcmp(slotted.places[0], "Kokiri Forest"));
    CHECK(slotted.slots[1] == -1 && !slotted.made[1][0] && slotted.hearts[1] == 3 && slotted.slots[2] == -1 && !slotted.made[2][0]);
    CHECK(!cards.pictures[1][0] && !cards.places[1][0] && !cards.items[1] && !cards.hearts[1] && !strcmp(cards.names[1], "Two"));
    CHECK(!strcmp(cards.places[2], "Lake Hylia") && cards.items[2] == 0x1ff && cards.hearts[2] == 0);
    static sf::List bare;   // (a host that sends no card, and one whose card has no bars: nothing of it)
    say(bare, "Old\n\n");
    bare.add(0);
    say(bare, "Odd\n\n\nno bars here");
    bare.add(0);
    bare.done(2);
    CHECK(!bare.places[0][0] && !bare.items[0] && !bare.places[1][0] && !bare.hearts[1] && bare.shown() == 2);
    // a save's picture among a file's bytes: from the first FF D8 FF to the last FF D9 after it
    {
        const unsigned char file[] = {1, 2, 0xFF, 0xD9, 3, 0xFF, 0xD8, 0xFF, 0xE0, 9, 9, 0xFF, 0xD9, 9, 0xFF, 0xD9, 7, 7};
        size_t at = 0, len = 0;
        CHECK(sf::jpeg_in(file, sizeof file, &at, &len) && at == 5 && len == 11);
        CHECK(!sf::jpeg_in(file, 7, &at, &len) && !sf::jpeg_in(file, 12, &at, &len) && sf::jpeg_in(file, 13, &at, &len) && at == 5 && len == 8);
        const unsigned char none[] = {0xFF, 0xD9, 0xFF, 0xD8, 0, 0xFF, 0xD8};
        CHECK(!sf::jpeg_in(none, sizeof none, &at, &len) && !sf::jpeg_in(none, 0, &at, &len) && !sf::jpeg_in(file + 5, 3, &at, &len));
    }

    // when a save was made, as its caption has it: a calendar time outside the picture, the latest of those found
    {
        unsigned char file[96] = {};
        const unsigned char early[] = {0xEA, 0x07, 11, 18, 1, 28, 9}, late[] = {0xEA, 0x07, 11, 18, 1, 43, 5};   // (2026-11-18 01:28:09, 01:43:05)
        memcpy(file + 4, early, 7), memcpy(file + 80, late, 7);
        sf::SaveTime t = sf::caption_time(file, sizeof file, 20, 40, 2026, 4102444800LL);   // (the picture: bytes 20 to 59)
        CHECK(t.kind == 1 && t.year == 2026 && t.month == 11 && t.day == 18 && t.hour == 1 && t.minute == 43 && t.second == 5);
        memcpy(file + 30, "\xEA\x07\x0C\x1F\x17\x3B\x3B", 7);   // (a later one inside the picture: not a time)
        t = sf::caption_time(file, sizeof file, 20, 40, 2026, 4102444800LL);
        CHECK(t.kind == 1 && t.minute == 43);
        t = sf::caption_time(file, 40, 20, 20, 2026, 4102444800LL);                  // (cut short of the later one)
        CHECK(t.kind == 1 && t.minute == 28);
        // what is no time: a year, month, day, hour, minute or second out of range
        const unsigned char bad[][7] = {{0xE0, 0x07, 11, 18, 1, 28, 9}, {0x35, 0x08, 1, 1, 0, 0, 0}, {0xEA, 0x07, 0, 18, 1, 28, 9}, {0xEA, 0x07, 13, 18, 1, 28, 9},
                                        {0xEA, 0x07, 11, 0, 1, 28, 9},  {0xEA, 0x07, 11, 32, 1, 28, 9}, {0xEA, 0x07, 11, 18, 24, 28, 9},
                                        {0xEA, 0x07, 11, 18, 1, 60, 9}, {0xEA, 0x07, 11, 18, 1, 28, 60}};
        for (const auto& b : bad) {
            unsigned char one[16] = {};
            memset(one, 0xFF, sizeof one), memcpy(one + 3, b, 7);
            CHECK(sf::caption_time(one, sizeof one, sizeof one, 0, 2026, 4102444800LL).kind == 0);
        }
        // a time that cannot be a save's: of a year to come (2093, among a caption's other bytes), or before this game
        {
            unsigned char one[16] = {};
            memcpy(one + 2, "\x2D\x08\x09\x19\x09\x15\x00", 7);   // (2093-09-25 09:21:00)
            CHECK(sf::caption_time(one, sizeof one, sizeof one, 0, 2026, 4102444800LL).kind == 0 && sf::caption_time(one, sizeof one, sizeof one, 0, 2093, 4102444800LL).kind == 1);
            memcpy(one + 2, "\xE8\x07\x09\x19\x09\x15\x00", 7);   // (2024)
            CHECK(sf::caption_time(one, sizeof one, sizeof one, 0, 2026, 4102444800LL).kind == 0);
            const unsigned char later[] = {0x16, 0xCD, 0x5B, 0x69, 0, 0, 0, 0};
            unsigned char two[16];
            memset(two, 0xFF, sizeof two), memcpy(two + 4, later, 8);
            CHECK(sf::caption_time(two, sizeof two, sizeof two, 0, 2026, 0x695BCD15).kind == 0 && sf::caption_time(two, sizeof two, sizeof two, 0, 2026, 0x695BCD16).kind == 2);
        }
        // no calendar time: a count of seconds since 1970, 64 bits, its upper half 0; the latest; none outside 2017 to 2100
        unsigned char secs[64];
        memset(secs, 0xFF, sizeof secs);
        const unsigned char a[] = {0x15, 0xCD, 0x5B, 0x69, 0, 0, 0, 0}, b2[] = {0x16, 0xCD, 0x5B, 0x69, 0, 0, 0, 0}, old[] = {0x00, 0x00, 0x00, 0x40, 0, 0, 0, 0};
        memcpy(secs + 8, a, 8), memcpy(secs + 24, b2, 8), memcpy(secs + 40, old, 8);
        t = sf::caption_time(secs, sizeof secs, sizeof secs, 0, 2026, 4102444800LL);
        CHECK(t.kind == 2 && t.seconds == 0x695BCD16);
        CHECK(sf::caption_time(secs, 8, 8, 0, 2026, 4102444800LL).kind == 0 && sf::caption_time(secs, 0, 0, 0, 2026, 4102444800LL).kind == 0);
        // which of two saves is the later; one that tells a time is later than one that tells none
        sf::SaveTime x, y, none;
        x.kind = y.kind = 1, x.year = y.year = 2026, x.month = y.month = 11, x.day = 18, y.day = 17, y.hour = 23;
        CHECK(x.after(y) && !y.after(x) && !x.after(x) && x.after(none) && !none.after(x) && !none.after(none));
        char text[32];
        sf::game_time(text, sizeof text, 2026, 11, 18, 1, 40);
        CHECK(!strcmp(text, "11/18/2026 1:40 a.m."));
        sf::game_time(text, sizeof text, 2026, 1, 5, 0, 5); CHECK(!strcmp(text, "1/5/2026 12:05 a.m."));
        sf::game_time(text, sizeof text, 2026, 1, 5, 12, 0); CHECK(!strcmp(text, "1/5/2026 12:00 p.m."));
        sf::game_time(text, sizeof text, 2026, 1, 5, 23, 59); CHECK(!strcmp(text, "1/5/2026 11:59 p.m."));
    }

    // the choice: Up and Down, Home and End, kept to the files
    int choice = 0;
    CHECK(!sf::move(choice, -1, false, false, 3) && choice == 0 && sf::move(choice, 1, false, false, 3) && choice == 1);
    CHECK(sf::move(choice, 5, false, false, 3) && choice == 2 && !sf::move(choice, 1, false, false, 3));
    CHECK(sf::move(choice, 0, true, false, 3) && choice == 0 && sf::move(choice, 0, false, true, 3) && choice == 2);
    CHECK(!sf::move(choice, 1, false, false, 0) && choice == 2);

    if (!fails) printf("PASS\n");
    return fails != 0;
}
