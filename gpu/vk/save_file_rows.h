// (Triforce) Save files on the menu's side: the files the host names (host/save_files.c; vk_api.h HOS_OPT_FILES_*), the one
// this run plays, the one the player chose, and what the host said became of it. vk_menu.cpp draws the file select.
//
// The files are the host's: each is a folder the game saves in, and the game is started on one of them. The menu is told
// each file's name, when it was last saved and which is this run's, a byte a call as the save rows' lines are. A file
// chosen that is this run's is played at once; another is asked of the host, which keeps it as the next start's and says
// so: the menu then restarts the game.
//
// The host's calls (text, add, done, said) come on the game's presenting thread, the page is drawn and pressed on the
// renderer's: names and lines are written before count says the files are there and never after; the rest are atomics.
//
// No ImGui and no Vulkan: tests/test_save_files.py compiles it alone.
#pragma once
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace save_file_rows {
constexpr int kSlots = 3;     // (host/save_files.h SAVE_FILES; List::slots has an entry for each)
constexpr int kName = 25, kWhen = 24;
constexpr int kPath = 600;    // (the file its picture is in: a path of the game folder's)
constexpr int kPlace = 49;    // (where it was played last: host/save_files.h SAVE_CARD_PLACE and its end)
constexpr int kStones = 3, kMedals = 6, kHearts = 20;   // (host/save_files.h SAVE_CARD_*: its items' bits, the stones first)
constexpr int kSaved = 1, kCurrent = 2;   // (vk_api.h HOS_FILE_*)
constexpr int kChosen = 256;              // (vk_api.h HOS_FILES_CHOSEN)
enum Said { kNothing, kRestart, kFailed };   // (vk_api.h HOS_OPT_FILES_SAID: 1 and 2)

struct List {
    char names[kSlots][kName] = {};
    char whens[kSlots][kWhen] = {};
    char pictures[kSlots][kPath] = {};          // (where its saves' captions are: "<this>NN\caption.sav", NN the slot; "" no save in it)
    // (its card, as the host kept it while the file was played: host/save_files.h SaveCard)
    char places[kSlots][kPlace] = {};           // (where it was played last, "" not known)
    int items[kSlots] = {};                     // (the stones and medallions held: bits 0 to kStones - 1, then kMedals)
    int hearts[kSlots] = {};                    // (heart containers, 0 not known)
    int slots[kSlots] = {-1, -1, -1};           // (the slot the game saved in last while the file was played, -1 not known)
    char made[kSlots][kWhen] = {};              // (and when, as the game writes a time; "" not known)
    unsigned char bits[kSlots] = {};
    std::atomic<int> count{0};        // (the files shown: 0 until the host's list is whole)
    std::atomic<int> after_choice{0}; // (this start follows a choice: the game restarted for it)
    std::atomic<int> ask{0};          // (the file chosen that is not this run's, its number, until the host takes it)
    std::atomic<int> answer{kNothing};
    // the host's side
    char in[kName + 2 * kWhen + kPath + kPlace + 48] = {};
    int in_n = 0, added = 0;

    /// HOS_OPT_FILES_TEXT: the next byte of the file being named
    void text(int byte) {
        if (byte > 0 && byte < 256 && in_n + 1 < (int)sizeof in) in[in_n++] = (char)byte;
    }
    static int hex(char ch) { return ch >= '0' && ch <= '9' ? ch - '0' : ch >= 'a' && ch <= 'f' ? ch - 'a' + 10 : -1; }
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
    /// HOS_OPT_FILES_ADD: the bytes so far are the next file's name and, each after a line feed, when it was last saved, the
    /// file its picture is in, and its card: "<place>|<items, hex>|<hearts>|<slot saved in last, -1 none>|<when>"
    void add(int file_bits) {
        in[in_n] = 0;
        in_n = 0;
        if (count.load(std::memory_order_acquire) || added >= kSlots) return;   // (shown already, or no room left)
        const int slot = added++;
        char* when = strchr(in, '\n');
        char* picture = when ? strchr(when + 1, '\n') : nullptr;
        char* card = picture ? strchr(picture + 1, '\n') : nullptr;
        if (when) *when++ = 0;
        if (picture) *picture++ = 0;
        if (card) *card++ = 0;
        put(names[slot], kName, in[0] ? in : "(no name)");
        put(whens[slot], kWhen, when ? when : "");
        if (picture && strlen(picture) < (size_t)kPath) strcpy(pictures[slot], picture);   // (a path cut short names no file: none then)
        if (char* bar = card ? strchr(card, '|') : nullptr) {
            *bar++ = 0;
            put(places[slot], kPlace, card);
            int held = 0, n = 0;
            for (; hex(*bar) >= 0 && n < 4; bar++, n++) held = held << 4 | hex(*bar);
            items[slot] = held & ((1 << (kStones + kMedals)) - 1);
            const int count = *bar == '|' ? atoi(bar + 1) : 0;
            hearts[slot] = count >= 1 && count <= kHearts ? count : 0;
            if (char* last = *bar == '|' ? strchr(bar + 1, '|') : nullptr) {
                const int in = atoi(last + 1);
                char* when_made = strchr(last + 1, '|');
                if (in >= 0 && in < 12 && when_made && (last[1] >= '0' && last[1] <= '9')) slots[slot] = in, put(made[slot], kWhen, when_made + 1);
            }
        }
        bits[slot] = (unsigned char)(file_bits & (kSaved | kCurrent));
    }
    /// HOS_OPT_FILES_COUNT: the list is whole: how many, and kChosen
    void done(int value) {
        in_n = 0;
        if (count.load(std::memory_order_acquire)) return;
        const int n = value & 255;
        after_choice.store((value & kChosen) != 0, std::memory_order_relaxed);
        count.store(n < added ? n : added, std::memory_order_release);
    }
    int shown() const { return count.load(std::memory_order_acquire); }
    /// The file this run plays, -1 when the host named none as it
    int current() const {
        for (int i = 0, n = shown(); i < n; i++)
            if (bits[i] & kCurrent) return i;
        return -1;
    }
    bool saved(int slot) const { return slot >= 0 && slot < shown() && (bits[slot] & kSaved); }
    /// The title asks which file to play: the files are there. At every start, the one that follows a choice too: the file
    /// select is where a file is changed again (asked once after a choice and not again, there was no way back from the title)
    bool asks() const { return shown() > 0; }
    /// This start follows a choice at the file select (the game restarted for it)
    bool chosen() const { return after_choice.load(std::memory_order_relaxed) != 0; }
    /// A file chosen. true: it is this run's, played at once. false: asked of the host (or no such file: nothing asked)
    bool choose(int slot) {
        if (slot < 0 || slot >= shown()) return false;
        if (slot == current()) return true;
        answer.store(kNothing, std::memory_order_relaxed);
        ask.store(slot + 1, std::memory_order_release);
        return false;
    }
    /// HOS_OPT_FILES_ASK: the file chosen since the last read, its number; 0 none
    int take_ask() { return ask.load(std::memory_order_relaxed) ? ask.exchange(0, std::memory_order_acq_rel) : 0; }
    /// HOS_OPT_FILES_SAID: what became of the file asked for
    void said(int value) { answer.store(value == 1 ? kRestart : value == 2 ? kFailed : kNothing, std::memory_order_release); }
    /// The host's word since the last ask, once: kRestart, kFailed, or kNothing
    int take_said() { return answer.load(std::memory_order_relaxed) ? answer.exchange(kNothing, std::memory_order_acq_rel) : kNothing; }
};

/// A save's picture in the bytes of the file that holds it: the game keeps it as a JPEG among its own data. From the first
/// start of one (FF D8 FF) to the last end of one after it (FF D9): where it is and how long, false when there is none
inline bool jpeg_in(const unsigned char* bytes, size_t n, size_t* at, size_t* len) {
    size_t first = n, last = 0;
    for (size_t i = 0; i + 2 < n; i++)
        if (bytes[i] == 0xFF && bytes[i + 1] == 0xD8 && bytes[i + 2] == 0xFF) { first = i; break; }
    if (first == n) return false;
    for (size_t i = n - 1; i > first + 2; i--)
        if (bytes[i] == 0xD9 && bytes[i - 1] == 0xFF) { last = i + 1; break; }
    if (!last) return false;
    *at = first, *len = last - first;
    return true;
}

/// When a save was made, as its caption file has it. The game shows a save's own time on its load list; the files' dates on
/// the disk are not that (the game writes every slot again when it saves any, and its settings at other times). The
/// caption's form is not known to this repository, so the time is looked for as the two shapes a console's time has, in
/// the bytes outside the picture: a calendar time (year, a 16-bit number, then month, day, hour, minute, second, a byte
/// each), and failing that a count of seconds since 1970 (64 bits). The latest found is taken, and the log says which
/// (vk_menu.cpp files_pictures_load): a card whose time is wrong says the shape is another
struct SaveTime {
    int kind = 0;        // (0 none found, 1 a calendar time, 2 a count of seconds)
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;   // (kind 1)
    int64_t seconds = 0; // (kind 2)
    /// later than `o`? (of the same kind: a file's saves are)
    bool after(const SaveTime& o) const { return kind > o.kind || (kind == o.kind && key() > o.key()); }
    int64_t key() const {
        return kind == 2 ? seconds : kind == 1 ? ((((((int64_t)year * 13 + month) * 32 + day) * 24 + hour) * 60 + minute) * 60 + second) : 0;
    }
};
/// max_year, max_seconds: now, a day on (a save is not of the future): among a file's other bytes a time of any year was
/// found where there was none ("9/25/2093", his picture, 11-18). No save of this game is older than 2025
inline SaveTime caption_time(const unsigned char* b, size_t n, size_t picture_at, size_t picture_len, int max_year, int64_t max_seconds) {
    SaveTime best, posix;
    const auto outside = [&](size_t i, size_t len) { return i + len <= picture_at || i >= picture_at + picture_len; };
    for (size_t i = 0; i + 7 <= n; i++) {
        if (!outside(i, 7)) continue;
        SaveTime t;
        t.kind = 1, t.year = b[i] | b[i + 1] << 8, t.month = b[i + 2], t.day = b[i + 3], t.hour = b[i + 4], t.minute = b[i + 5], t.second = b[i + 6];
        if (t.year < 2025 || t.year > max_year || t.month < 1 || t.month > 12 || t.day < 1 || t.day > 31 || t.hour > 23 || t.minute > 59 || t.second > 59)
            continue;
        if (t.after(best)) best = t;
    }
    if (best.kind) return best;
    for (size_t i = 0; i + 8 <= n; i++) {
        if (!outside(i, 8) || b[i + 4] || b[i + 5] || b[i + 6] || b[i + 7]) continue;
        const int64_t v = (int64_t)b[i] | (int64_t)b[i + 1] << 8 | (int64_t)b[i + 2] << 16 | (int64_t)b[i + 3] << 24;
        if (v < 1735689600LL || v > max_seconds) continue;   // (2025 to now)
        SaveTime t;
        t.kind = 2, t.seconds = v;
        if (t.after(posix)) posix = t;
    }
    return posix;
}
/// A time as the game's load list writes it: 11/18/2026 1:40 a.m.
inline void game_time(char* out, size_t cap, int year, int month, int day, int hour, int minute) {
    snprintf(out, cap, "%d/%d/%d %d:%02d %s", month, day, year, hour % 12 ? hour % 12 : 12, minute, hour < 12 ? "a.m." : "p.m.");
}

/// The choice moved by Up and Down (step), Home and End, kept to the n files. true: it moved
inline bool move(int& choice, int step, bool home, bool end, int n) {
    if (n <= 0) return false;
    const int was = choice;
    choice = home ? 0 : end ? n - 1 : choice + step;
    choice = choice < 0 ? 0 : choice >= n ? n - 1 : choice;
    return choice != was;
}
}   // namespace save_file_rows
