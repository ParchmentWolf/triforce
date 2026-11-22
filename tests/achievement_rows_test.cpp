// gpu/vk/achievement_rows.h alone (tests/test_achievements.py): the list as the host names it, one earned and its notice,
// the page's choice and pages, and how a notice comes in and goes.
#include <cstdio>
#include <cstring>
#include "achievement_rows.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

namespace ar = achievement_rows;
static ar::List list;

static void say(const char* text) {
    for (const char* p = text; *p; p++) list.text((unsigned char)*p);
}

int main() {
    // nothing shown until the list is whole; then as named, in order
    say("First\nThe line about it.\n2026-11-18");
    list.add(1 | 3 << 4 | ar::kEarned);
    say("Second\nAnother line.\n");
    list.add(5);
    say("Third");   // (no line about it and no day)
    list.add(2 | 9 << 4);
    list.add(0);    // (no name at all)
    CHECK(list.shown() == 0 && list.earned_count() == 0 && list.take_fresh() == -1);
    CHECK(!list.earn(0) && list.take_fresh() == -1);   // (earned before the list is whole: no such place yet)
    list.done(4);
    CHECK(list.shown() == 4 && list.earned_count() == 1);
    CHECK(!strcmp(list.names[0], "First") && !strcmp(list.abouts[0], "The line about it.") && !strcmp(list.days[0], "2026-11-18"));
    CHECK(list.is_earned(0) && ar::shape_of(list.icons[0]) == ar::kSword && ar::tone_of(list.icons[0]) == ar::kBlue);
    CHECK(!strcmp(list.names[1], "Second") && !strcmp(list.abouts[1], "Another line.") && !list.days[1][0] && !list.is_earned(1));
    CHECK(ar::shape_of(list.icons[1]) == ar::kToken && ar::tone_of(list.icons[1]) == ar::kGold);
    CHECK(!strcmp(list.names[2], "Third") && !list.abouts[2][0] && !list.days[2][0]);
    CHECK(ar::shape_of(list.icons[2]) == ar::kGem && ar::tone_of(list.icons[2]) == ar::kGold);   // (a tone that is none: gold)
    CHECK(!strcmp(list.names[3], "(no name)") && ar::shape_of(15) == ar::kStar && ar::shape_of(ar::kShield) == ar::kShield);
    // a list sent again changes nothing
    say("Again\nx\n");
    list.add(0);
    list.done(1);
    CHECK(list.shown() == 4 && !strcmp(list.names[0], "First"));

    // one earned: its day, and the notice's once
    say("2026-11-19");
    CHECK(list.earn(1) && list.is_earned(1) && !strcmp(list.days[1], "2026-11-19") && list.earned_count() == 2);
    CHECK(list.take_fresh() == 1 && list.take_fresh() == -1);
    say("2030-01-01");
    CHECK(list.earn(0) && !strcmp(list.days[0], "2026-11-18") && list.take_fresh() == 0);   // (earned before: the day it was)
    say("junk");
    CHECK(!list.earn(4) && !list.earn(-1) && list.take_fresh() == -1 && list.earned_count() == 2);
    say("2026-11-20");
    CHECK(list.earn(2) && !strcmp(list.days[2], "2026-11-20"));   // (the bytes of the refused ones are not this one's day)
    CHECK(list.take_fresh() == 2);

    // a name, a line and a day longer than their room: cut, a name never inside a letter
    static ar::List wide;
    for (int i = 0; i < 39; i++) wide.text('n');
    wide.text(0xC3), wide.text(0xA9), wide.text(0xC3), wide.text(0xA9);   // (two letters of two bytes: the second does not fit)
    wide.text('\n');
    for (int i = 0; i < 400; i++) wide.text('a');
    wide.add(0);
    wide.done(1);
    CHECK(strlen(wide.names[0]) == 39 && strlen(wide.abouts[0]) <= (size_t)ar::kAbout - 1 && wide.shown() == 1);
    // more than there is room for: the first kSlots
    static ar::List many;
    for (int i = 0; i < ar::kSlots + 5; i++) many.text('a' + i % 26), many.add(0);
    many.done(ar::kSlots + 5);
    CHECK(many.shown() == ar::kSlots);
    many.done(-3);
    CHECK(many.shown() == ar::kSlots);

    // the page: 2 cards to a row, 6 to a page, 14 of them
    ar::View v;
    CHECK(ar::View::pages(14, 6) == 3 && ar::View::pages(12, 6) == 2 && ar::View::pages(0, 6) == 1 && ar::View::pages(5, 0) == 5);
    CHECK(!v.move(-1, 0, 0, false, false, 14, 2, 6) && v.choice == 0);                 // (Left at the first: stays)
    CHECK(v.move(1, 0, 0, false, false, 14, 2, 6) && v.choice == 1 && v.page == 0);
    CHECK(v.move(0, 1, 0, false, false, 14, 2, 6) && v.choice == 3);                   // (Down: a row)
    CHECK(v.move(0, 2, 0, false, false, 14, 2, 6) && v.choice == 7 && v.page == 1);    // (onto the next page: shown)
    CHECK(v.move(0, 0, 1, false, false, 14, 2, 6) && v.choice == 13 && v.page == 2);   // (a page on, kept to the last card)
    CHECK(!v.move(0, 0, 1, false, false, 14, 2, 6) && v.choice == 13);
    CHECK(v.move(0, 0, 0, true, false, 14, 2, 6) && v.choice == 0 && v.page == 0);     // (Home)
    CHECK(v.move(0, 0, 0, false, true, 14, 2, 6) && v.choice == 13 && v.page == 2);    // (End)
    CHECK(v.turn(-1, 14, 6) && v.page == 1 && v.choice == 13);                         // (the wheel: the page, not the choice)
    CHECK(v.turn(-5, 14, 6) && v.page == 0 && !v.turn(-1, 14, 6) && v.turn(9, 14, 6) && v.page == 2);
    CHECK(v.choose(4, 14) && v.choice == 4 && !v.choose(4, 14) && !v.choose(14, 14) && !v.choose(-1, 14));
    v.keep(3, 6);   // (a shorter list under the choice)
    CHECK(v.choice == 2 && v.page == 0);
    CHECK(!v.move(1, 0, 0, false, false, 0, 2, 6));
    v.keep(0, 6);
    CHECK(v.choice == 0 && v.page == 0);

    // a notice: in over a quarter of a second, there, out over the last 300 ms, gone
    CHECK(ar::notice_in(-1, 4000) == 0 && ar::notice_in(0, 4000) == 0 && ar::notice_in(4000, 4000) == 0 && ar::notice_in(9000, 4000) == 0);
    CHECK(ar::notice_in(125, 4000) == 0.5f && ar::notice_in(250, 4000) == 1 && ar::notice_in(2000, 4000) == 1 && ar::notice_in(3700, 4000) == 1);
    CHECK(ar::notice_in(3850, 4000) == 0.5f);

    if (!fails) printf("PASS\n");
    return fails != 0;
}
