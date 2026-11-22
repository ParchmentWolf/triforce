// (Triforce) Achievements on the menu's side: the list the host names (host/achievements.c; vk_api.h HOS_OPT_ACH_*), which of
// them are earned, the one a notice shows, and the Achievements page's choice and pages. vk_menu.cpp draws them.
//
// The achievements are the host's: it reads the lists, asks the save data and keeps what was earned. The menu is told
// each one's name, the line about it, its icon and the day it was earned, a byte a call as the save rows' lines are, and
// later each one earned as it is. An icon is drawn, not a picture file: a shape and a tone (host/achievements.h has the
// same in the same order, ACH_SHAPES and ACH_TONES; tests/test_achievements.py holds the two together).
//
// The host's calls (text, add, done, earn) come on its threads, one at a time (its lock); the list is drawn on the
// renderer's: names, lines and icons are written before count says they are there and never after, a day before its
// achievement's earned says so.
//
// No ImGui and no Vulkan: tests/test_achievements.py compiles it alone.
#pragma once
#include <atomic>
#include <cstdint>
#include <cstring>

namespace achievement_rows {
constexpr int kSlots = 128;   // (host/achievements.h ACH_MAX)
constexpr int kName = 41, kAbout = 161, kDay = 16;
constexpr int kEarned = 256;  // (vk_api.h HOS_ACH_EARNED)
enum Shape { kStar, kSword, kGem, kMedal, kNote, kToken, kShield, kShapes };
enum Tone { kGold, kGreen, kRed, kBlue, kPurple, kOrange, kYellow, kSilver, kTones };
constexpr int shape_of(int icon) { return (icon & 15) < kShapes ? icon & 15 : kStar; }
constexpr int tone_of(int icon) { return (icon >> 4 & 15) < kTones ? icon >> 4 & 15 : kGold; }

struct List {
    char names[kSlots][kName] = {};
    char abouts[kSlots][kAbout] = {};
    char days[kSlots][kDay] = {};
    unsigned char icons[kSlots] = {};
    std::atomic<int> earned[kSlots] = {};
    std::atomic<int> count{0};     // (the achievements shown: 0 until the host's list is whole)
    std::atomic<int> fresh{-1};    // (the one earned now, until the notice takes it)
    // the host's side
    char in[kName + kAbout + kDay + 8] = {};
    int in_n = 0, added = 0;

    /// HOS_OPT_ACH_TEXT: the next byte of what is being named
    void text(int byte) {
        if (byte > 0 && byte < 256 && in_n + 1 < (int)sizeof in) in[in_n++] = (char)byte;
    }
    /// `from` copied into a field of `cap` bytes, cut at a whole letter
    static void put(char* to, int cap, const char* from) {
        int n = (int)strlen(from);
        if (n > cap - 1) {
            n = cap - 1;
            while (n && ((unsigned char)from[n] & 0xC0) == 0x80) n--;
        }
        memcpy(to, from, (size_t)n);
        to[n] = 0;
    }
    /// HOS_OPT_ACH_ADD: the bytes so far are the next achievement's name and, each after a line feed, the line about it and
    /// the day it was earned; bits: its icon, and kEarned
    void add(int bits) {
        in[in_n] = 0;
        in_n = 0;
        if (count.load(std::memory_order_acquire) || added >= kSlots) return;   // (shown already, or no room left)
        const int slot = added++;
        char* about = strchr(in, '\n');
        char* day = about ? strchr(about + 1, '\n') : nullptr;
        if (about) *about++ = 0;
        if (day) *day++ = 0;
        put(names[slot], kName, in[0] ? in : "(no name)");
        put(abouts[slot], kAbout, about ? about : "");
        put(days[slot], kDay, day ? day : "");
        icons[slot] = (unsigned char)(bits & 255);
        earned[slot].store((bits & kEarned) != 0, std::memory_order_relaxed);
    }
    /// HOS_OPT_ACH_COUNT: the list is whole: shown from now on
    void done(int n) {
        in_n = 0;
        if (count.load(std::memory_order_acquire)) return;
        count.store(n < 0 ? 0 : n < added ? n : added, std::memory_order_release);
    }
    /// HOS_OPT_ACH_EARNED: the achievement at that place was earned now, the bytes so far the day. false: no such place
    bool earn(int slot) {
        in[in_n] = 0;
        in_n = 0;
        if (slot < 0 || slot >= shown()) return false;
        if (!earned[slot].load(std::memory_order_relaxed)) put(days[slot], kDay, in);
        earned[slot].store(1, std::memory_order_release);
        fresh.store(slot, std::memory_order_release);
        return true;
    }
    int shown() const { return count.load(std::memory_order_acquire); }
    bool is_earned(int slot) const { return slot >= 0 && slot < kSlots && earned[slot].load(std::memory_order_acquire) != 0; }
    int earned_count() const {
        int n = 0;
        for (int i = 0, end = shown(); i < end; i++) n += is_earned(i);
        return n;
    }
    /// The one earned since the last ask, for the notice; -1 none
    int take_fresh() { return fresh.load(std::memory_order_relaxed) < 0 ? -1 : fresh.exchange(-1, std::memory_order_acq_rel); }
};

/// The page's cards: `columns` to a row, `capacity` to a page (both 1 at least), n of them
struct View {
    int choice = 0, page = 0;

    static int pages(int n, int capacity) { return n <= 0 ? 1 : (n + (capacity < 1 ? 1 : capacity) - 1) / (capacity < 1 ? 1 : capacity); }
    /// The choice kept to the list, and the page shown to the pages there are
    void keep(int n, int capacity) {
        choice = n <= 0 ? 0 : choice < 0 ? 0 : choice >= n ? n - 1 : choice;
        const int last = pages(n, capacity) - 1;
        page = page < 0 ? 0 : page > last ? last : page;
    }
    /// The page that shows the choice
    void reveal(int capacity) { page = choice / (capacity < 1 ? 1 : capacity); }
    /// The arrows (cards: Left and Right, rows: Up and Down), Page Up and Down (turns), Home and End. true: the choice moved
    bool move(int cards, int rows, int turns, bool home, bool end, int n, int columns, int capacity) {
        if (n <= 0) return false;
        const int was = choice;
        const int step = cards + rows * (columns < 1 ? 1 : columns) + turns * (capacity < 1 ? 1 : capacity);
        choice = home ? 0 : end ? n - 1 : choice + step;
        keep(n, capacity);
        if (choice == was) return false;
        reveal(capacity);
        return true;
    }
    /// The wheel, or a page arrow that leaves the choice where it is: the page shown turned. true: it changed
    bool turn(int by, int n, int capacity) {
        const int was = page;
        page += by;
        keep(n, capacity);
        return page != was;
    }
    /// A click on a card. true: the choice changed
    bool choose(int slot, int n) {
        if (slot < 0 || slot >= n || slot == choice) return false;
        choice = slot;
        return true;
    }
};

/// How far a notice has come in, 0 (out of sight) to 1 (in place): in over the first 250 ms of its `shown_ms`, out over
/// the last 300
inline float notice_in(int64_t age_ms, int64_t shown_ms) {
    if (age_ms < 0 || age_ms >= shown_ms) return 0;
    const float in = (float)age_ms / 250.0f, out = (float)(shown_ms - age_ms) / 300.0f;
    const float k = in < out ? in : out;
    return k > 1 ? 1 : k;
}
}   // namespace achievement_rows
