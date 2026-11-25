"""The game's short sleeps wait on the timer on PCs with 6 or fewer logical processors (host/short_sleep.h, host/
hos_thread.c process_threads, sleep_away, sleep_for and hos_sleep_logged; no game, no threads).

(Triforce, 11-21, the performance audit's OS-31, after Source A's.) The game's idle job workers sleep 20 us and look
again, about 7,600 times a second. A sleep under a millisecond is yielded away until its time, so each sleeper keeps a
processor busy; with few processors that is time the frame's threads need.

This compiles short_sleep.h alone and checks the rule: not set, the game's own short sleeps are on the timer with 1 to 6
processors and yield with 7, 16 or an unknown count, and the host's own always yield; set on, every short sleep is on the
timer; set to 0, off, no or false, every one yields, whatever the processors; a sleep of a millisecond or more never
yields.

And reads the source: the processors are the process's affinity mask and only with one processor group; the choice is
the rule's, of the switch's value (not its presence) and those processors, made once and logged; the game's SleepThread
goes through sleep_away as the game's own and the host's sleeps as the host's; the yield is the rule's; the switch is in
the switches table.

(Triforce, 11-22, the performance audit's OS-32, after Source A's.) Off Windows the processors are not counted. Source
A puts the game's own short sleeps on the timer there at any count when the switch is not set; that mode was never
measured in the game, so here it is built and not the default: HOS_SHORT_SLEEP_TIMER=game asks for it on any system,
and short_sleep.h's SHORT_SLEEP_ELSEWHERE says what a build that is not Windows' does with the switch not set (all
yield, as before). Checked: the rule with the system (short_sleep_timer_os), with either value of that default; and
the lines of sleep_for that choose, cut out and compiled once as Windows' and once as another system's, over stand-ins
for the environment and the processors: the other system's build gives SHORT_SLEEP_ELSEWHERE when not set whatever
the processors, the game's own on the timer for "game", all on the timer for 1 and all yield for 0, and Windows'
build goes by the processors as before.

(Triforce, 11-22, the performance audit's OS-33, after Source A's.) A cap on the game threads that yield through a short
sleep at once, HOS_SHORT_SLEEP_POLLERS, off unless set. The rule: not set, 0 or off no limit; a number that many; auto a
quarter of the processors above 6 (8: 2, 16: 4, 64: 16, not known: none); none with HOS_SHORT_SLEEP_TIMER set or where
the sleeps do not all yield. The gate, called in a scripted order: the cap's worth are let in, the next is sent to the
timer and its count given back, MainThread, the Presentation Thread and the host's sleeps are never counted, and the
count is 0 again once all have left. Three broken gates (no limit, a serial thread counted, a count not given back by
the one sent to the timer) must each fail those checks.

These sleeps end by the clock: nothing wakes them, so there is no wake-up to lose. What the cap could break is a count
that is never given back (every later sleep then waits on the timer), more threads yielding than the cap, or a sleep
that does not return. So the yield branch is cut out of hos_thread.c's sleep_for and run on real threads: 16 game
threads, one named MainThread and one host thread each sleep 20 us thousands of times against a cap of 4; never more
than 4 counted threads yield at once, the serial and the host thread never take the timer, every sleep returns, the
timer's count is the sleeps sent there, and the count of yielding threads is 0 at the end. The same cut without its
leave must fail.

    python -I -B tests/test_short_sleep_timer.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cstdio>
#include <initializer_list>
#include "short_sleep.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main() {
    const long long us20 = 20000, ms = 1000000;
    // not set: by the processors
    for (int t : {1, 2, 4, 6}) CHECK(short_sleep_timer(nullptr, t) == SHORT_SLEEP_GUEST_TIMER);
    for (int t : {0, 7, 8, 16, 24, 64}) CHECK(short_sleep_timer(nullptr, t) == SHORT_SLEEP_YIELD);   // (0: not known)
    CHECK(SHORT_SLEEP_TIMER_THREADS == 6);
    // set: on for all, or off for all, whatever the processors
    for (int t : {0, 4, 16}) {
        for (const char* on : {"1", "2", "on", "yes", "timer"}) CHECK(short_sleep_timer(on, t) == SHORT_SLEEP_ALL_TIMER);
        for (const char* off : {"0", "off", "no", "false", ""}) CHECK(short_sleep_timer(off, t) == SHORT_SLEEP_YIELD);
    }
    // who yields: 4 processors, the game's 20 us on the timer and the host's yielded
    const int few = short_sleep_timer(nullptr, 4), many = short_sleep_timer(nullptr, 16);
    CHECK(!short_sleep_yields(us20, few, 1) && short_sleep_yields(us20, few, 0));
    CHECK(short_sleep_yields(us20, many, 1) && short_sleep_yields(us20, many, 0));   // (16: as before, both yield)
    CHECK(!short_sleep_yields(us20, SHORT_SLEEP_ALL_TIMER, 1) && !short_sleep_yields(us20, SHORT_SLEEP_ALL_TIMER, 0));
    CHECK(short_sleep_yields(us20, SHORT_SLEEP_YIELD, 1) && short_sleep_yields(us20, SHORT_SLEEP_YIELD, 0));
    // a millisecond and more: the timer, always
    for (int how : {SHORT_SLEEP_YIELD, SHORT_SLEEP_GUEST_TIMER, SHORT_SLEEP_ALL_TIMER})
        for (int guest : {0, 1}) CHECK(!short_sleep_yields(ms, how, guest) && !short_sleep_yields(5 * ms, how, guest));
    CHECK(short_sleep_yields(ms - 1, SHORT_SLEEP_YIELD, 1) && short_sleep_yields(ms - 1, SHORT_SLEEP_GUEST_TIMER, 0));   // (just under: still short)
    // ((Triforce, 11-22, OS-32) the rule with the system. Windows: as short_sleep_timer, whatever the other systems' default
    for (int elsewhere : {SHORT_SLEEP_YIELD, SHORT_SLEEP_GUEST_TIMER})
        for (int t : {0, 1, 4, 6, 7, 8, 16, 64}) {
            CHECK(short_sleep_timer_os(nullptr, t, 1, elsewhere) == short_sleep_timer(nullptr, t));
            for (const char* v : {"1", "0", "off", "on", ""}) {
                CHECK(short_sleep_timer_os(v, t, 1, elsewhere) == short_sleep_timer(v, t));
                CHECK(short_sleep_timer_os(v, t, 0, elsewhere) == short_sleep_timer(v, t));   // (a value set decides anywhere)
            }
            // not Windows, not set: the default given, at any processor count (they are not counted there: 0)
            CHECK(short_sleep_timer_os(nullptr, t, 0, elsewhere) == elsewhere);
            // "game": the game's own on the timer, the host's yield, on any system at any count
            CHECK(short_sleep_timer_os("game", t, 0, elsewhere) == SHORT_SLEEP_GUEST_TIMER);
            CHECK(short_sleep_timer_os("game", t, 1, elsewhere) == SHORT_SLEEP_GUEST_TIMER);
        }
    // Source A's default off Windows, the day the constant says so: the game's 20 us on the timer on a Steam Deck's 8 and on 24
    CHECK(!short_sleep_yields(us20, short_sleep_timer_os(nullptr, 0, 0, SHORT_SLEEP_GUEST_TIMER), 1));
    CHECK(short_sleep_yields(us20, short_sleep_timer_os(nullptr, 0, 0, SHORT_SLEEP_GUEST_TIMER), 0));
    // and what is built now (11-24): that default, the game's own on the timer, the host's still yielding
    CHECK(SHORT_SLEEP_ELSEWHERE == SHORT_SLEEP_GUEST_TIMER);
    CHECK(!short_sleep_yields(us20, short_sleep_timer_os(nullptr, 0, 0, SHORT_SLEEP_ELSEWHERE), 1));
    CHECK(short_sleep_yields(us20, short_sleep_timer_os(nullptr, 0, 0, SHORT_SLEEP_ELSEWHERE), 0));
    return fails ? 1 : 0;
}
"""

# ((Triforce, 11-22, OS-32) sleep_for's lines that choose, compiled as Windows' build (T_WINDOWS defined) and as another
# system's: the source's own #if, its _WIN32 spelled T_WINDOWS so that a Windows compiler can build both
CHOICE = r"""
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "short_sleep.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static const char* t_value;
static int t_threads;
static const char* t_getenv(const char* name) {
    if (std::strcmp(name, "HOS_SHORT_SLEEP_TIMER")) std::printf("FAIL: getenv(%s)\n", name), fails++;
    return t_value;
}
static int process_threads() { return t_threads; }
#define getenv t_getenv
static int choose(const char* value, int threads_there) {
    t_value = value, t_threads = threads_there;
    {   // (the cut declares how: OS-33 keeps it with the cap in one word)
@CUT@
        return how;
    }
}
int main() {
#ifdef T_WINDOWS
    // Windows: by the processors, as before
    CHECK(choose(nullptr, 4) == SHORT_SLEEP_GUEST_TIMER && choose(nullptr, 6) == SHORT_SLEEP_GUEST_TIMER);
    CHECK(choose(nullptr, 8) == SHORT_SLEEP_YIELD && choose(nullptr, 16) == SHORT_SLEEP_YIELD && choose(nullptr, 0) == SHORT_SLEEP_YIELD);
    CHECK(choose("game", 16) == SHORT_SLEEP_GUEST_TIMER && choose("1", 16) == SHORT_SLEEP_ALL_TIMER && choose("0", 4) == SHORT_SLEEP_YIELD);
#else
    // another system: the processors are not known (0); not set gives the header's default at any count
    for (int t : {0, 4, 8, 24}) CHECK(choose(nullptr, t) == SHORT_SLEEP_ELSEWHERE);
    for (int t : {0, 4, 8, 24}) {
        CHECK(choose("game", t) == SHORT_SLEEP_GUEST_TIMER);   // (Source A's mode, asked for)
        CHECK(choose("1", t) == SHORT_SLEEP_ALL_TIMER && choose("0", t) == SHORT_SLEEP_YIELD && choose("off", t) == SHORT_SLEEP_YIELD);
    }
#endif
    return fails ? 1 : 0;
}
"""


# ((Triforce, OS-33) the cap's rule and its gate in a scripted order)
POLLERS = r"""
#include <cstdio>
#include <initializer_list>
#include "short_sleep.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main() {
    const int Y = SHORT_SLEEP_YIELD;
    // off unless asked for
    for (int t : {0, 4, 8, 16, 24, 64}) CHECK(short_sleep_pollers(nullptr, nullptr, Y, t) == 0);
    for (const char* off : {"0", "off", "no", "false", ""}) CHECK(short_sleep_pollers(off, nullptr, Y, 16) == 0);
    // auto: a quarter of the processors above 6
    CHECK(short_sleep_pollers("auto", nullptr, Y, 8) == 2 && short_sleep_pollers("auto", nullptr, Y, 16) == 4);
    CHECK(short_sleep_pollers("auto", nullptr, Y, 24) == 6 && short_sleep_pollers("auto", nullptr, Y, 64) == 16);
    CHECK(short_sleep_pollers("auto", nullptr, Y, 7) == 1 && short_sleep_pollers("auto", nullptr, Y, 12) == 3);
    CHECK(short_sleep_pollers("auto", nullptr, Y, 0) == 0 && short_sleep_pollers("auto", nullptr, Y, 6) == 0);   // (not known; few)
    CHECK(short_sleep_pollers("on", nullptr, Y, 16) == 4 && short_sleep_pollers("yes", nullptr, Y, 16) == 4);
    // a number: that many, whatever the processors, 1024 at most
    CHECK(short_sleep_pollers("2", nullptr, Y, 16) == 2 && short_sleep_pollers("2", nullptr, Y, 0) == 2);
    CHECK(short_sleep_pollers("1", nullptr, Y, 64) == 1 && short_sleep_pollers("12", nullptr, Y, 8) == 12);
    CHECK(short_sleep_pollers("1024", nullptr, Y, 8) == 1024 && short_sleep_pollers("5000", nullptr, Y, 8) == 1024);
    CHECK(short_sleep_pollers("99999999999999999999", nullptr, Y, 8) == 1024);
    // any HOS_SHORT_SLEEP_TIMER value, or sleeps that do not all yield: no cap
    for (const char* timer : {"0", "1", "off", ""}) CHECK(short_sleep_pollers("auto", timer, Y, 16) == 0 && short_sleep_pollers("2", timer, Y, 16) == 0);
    CHECK(short_sleep_pollers("2", nullptr, SHORT_SLEEP_GUEST_TIMER, 4) == 0 && short_sleep_pollers("auto", nullptr, SHORT_SLEEP_ALL_TIMER, 16) == 0);
    // the word
    for (int how : {SHORT_SLEEP_YIELD, SHORT_SLEEP_GUEST_TIMER, SHORT_SLEEP_ALL_TIMER})
        for (int cap : {0, 1, 4, 16, 1024}) {
            const int w = short_sleep_word(how, cap);
            CHECK(w >= 0 && short_sleep_how(w) == how && short_sleep_cap(w) == cap);
        }
    CHECK(short_sleep_word(SHORT_SLEEP_YIELD, 0) == SHORT_SLEEP_YIELD);   // (no cap: the word is what it was)
    // who is never counted
    CHECK(short_sleep_serial_name("MainThread") && short_sleep_serial_name("Presentation Thread") && short_sleep_serial_name("sead::MainThread"));
    CHECK(!short_sleep_serial_name("WorkerThread0") && !short_sleep_serial_name("Presentation Thread 2") && !short_sleep_serial_name(""));
    CHECK(!short_sleep_serial_name("Thread_80012340") && !short_sleep_serial_name(nullptr));
    // the gate, cap 2: two in, the third to the timer with its count given back
    int n = 0, a = 9, b = 9, c = 9, s = 9, h = 9;
    CHECK(short_sleep_poll_enter(&n, 2, 1, 0, &a) == 1 && a == 1 && n == 1);
    CHECK(short_sleep_poll_enter(&n, 2, 1, 0, &b) == 1 && b == 1 && n == 2);
    CHECK(short_sleep_poll_enter(&n, 2, 1, 0, &c) == 0 && c == 0 && n == 2);
    CHECK(short_sleep_poll_enter(&n, 2, 1, 1, &s) == 1 && s == 0 && n == 2);   // (a serial thread: yields, not counted, cap full or not)
    CHECK(short_sleep_poll_enter(&n, 2, 0, 0, &h) == 1 && h == 0 && n == 2);   // (the host's own sleep: the same)
    short_sleep_poll_leave(&n, c), short_sleep_poll_leave(&n, s), short_sleep_poll_leave(&n, h);
    CHECK(n == 2);                                                              // (who took nothing gives nothing back)
    short_sleep_poll_leave(&n, a);
    CHECK(n == 1 && short_sleep_poll_enter(&n, 2, 1, 0, &c) == 1 && c == 1 && n == 2);   // (a place freed: the next is let in)
    short_sleep_poll_leave(&n, b), short_sleep_poll_leave(&n, c);
    CHECK(n == 0);
    for (int i = 0; i < 100; i++) CHECK(short_sleep_poll_enter(&n, 0, 1, 0, &a) == 1 && a == 0 && n == 0);   // (no cap: nothing counted)
    for (int i = 0; i < 100; i++) {   // (sent to the timer again and again: nothing leaks)
        CHECK(short_sleep_poll_enter(&n, 1, 1, 0, &a) == 1 && short_sleep_poll_enter(&n, 1, 1, 0, &b) == 0);
        short_sleep_poll_leave(&n, a), short_sleep_poll_leave(&n, b);
    }
    CHECK(n == 0);
    return fails ? 1 : 0;
}
"""

# (each: what the broken gate does, the header's text, what replaces it)
GATE_MUTANTS = [
    ("no limit", "if (__atomic_add_fetch(pollers, 1, __ATOMIC_RELAXED) <= cap) {", "if (__atomic_add_fetch(pollers, 1, __ATOMIC_RELAXED) > 0) {"),
    ("a serial thread counted", "if (cap <= 0 || !guest || serial) return 1;", "if (cap <= 0 || !guest) return 1;"),
    ("the host's sleeps counted", "if (cap <= 0 || !guest || serial) return 1;", "if (cap <= 0 || serial) return 1;"),
    ("a count not given back by the one sent to the timer", "    __atomic_sub_fetch(pollers, 1, __ATOMIC_RELAXED);\n    return 0;", "    return 0;"),
]

# ((Triforce, OS-33) hos_thread.c's yield branch on real threads. The stand-ins: the clock is real, a yield is a real yield and
# notes that this thread is yielding, the timer is only counted)
STORM = r"""
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <thread>
#include <vector>
#include "short_sleep.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
struct HosThread { int serial; };
static thread_local HosThread* cur;
static int hos_thread_serial(HosThread* t) { return t->serial; }
static int short_pollers;
static int64_t short_capped;
static std::atomic<int> inside{0}, most{0};
// in_yield: 0 this sleep has not yielded yet, 1 it is yielding, 2 its time came (the look at the clock that ends the loop, which
// is before the branch gives its count back: a thread is "yielding" here for no longer than the branch holds its count)
static thread_local int in_yield, counted;
static thread_local int64_t until_now;
static int64_t clock_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
static int64_t hos_now_ns() {
    const int64_t now = clock_ns();
    if (in_yield == 1 && now >= until_now) {
        in_yield = 2;
        if (counted) --inside;
    }
    return now;
}
static int SwitchToThread() {
    if (!in_yield) {
        in_yield = 1;
        if (counted) {
            const int now = ++inside;
            int was = most.load();
            while (now > was && !most.compare_exchange_weak(was, now)) {}
        }
    }
    std::this_thread::yield();
    return 1;
}
static void YieldProcessor() {}
// 1: the sleep yielded to its time; 0: it was sent to the timer
static thread_local int fell;
static void sleep_short(int64_t ns, int guest, int word) {
    const int64_t until = clock_ns() + ns;
    until_now = until, fell = 0;
/* CUT */
    fell = 1;
}
struct Tally { long yielded = 0, timer = 0; };
static void sleeper(int serial, int guest, int word, int rounds, Tally* out) {
    HosThread me{serial};
    cur = guest ? &me : nullptr;
    counted = guest && !serial;
    for (int i = 0; i < rounds; i++) {
        in_yield = 0;
        sleep_short(20000, guest, word);
        CHECK(in_yield != 1);   // (a sleep that yielded went on to its time)
        fell ? out->timer++ : out->yielded++;
    }
}
static void storm(int cap, int rounds) {
    const int word = short_sleep_word(SHORT_SLEEP_YIELD, cap);
    Tally game[16], serial, host;
    std::vector<std::thread> threads;
    short_pollers = 0, short_capped = 0, inside = 0, most = 0;
    for (int i = 0; i < 16; i++) threads.emplace_back(sleeper, 0, 1, word, rounds, &game[i]);
    threads.emplace_back(sleeper, 1, 1, word, rounds, &serial);
    threads.emplace_back(sleeper, 0, 0, word, rounds, &host);
    for (auto& t : threads) t.join();   // (every sleep returned)
    long yielded = 0, timer = 0;
    for (const Tally& g : game) yielded += g.yielded, timer += g.timer;
    CHECK(yielded + timer == 16L * rounds);
    CHECK(serial.timer == 0 && serial.yielded == rounds);   // (the frame's threads always yield)
    CHECK(host.timer == 0 && host.yielded == rounds);       // (and the host's own sleeps)
    CHECK(short_pollers == 0);                              // (every count given back)
    CHECK(short_capped == timer);                           // (the log's count is the sleeps sent to the timer)
    CHECK(inside.load() == 0);
    if (cap) CHECK(most.load() <= cap);                     // (never more than the cap's worth yielding at once)
    else CHECK(timer == 0);                                 // (no cap: none sent to the timer, as before)
    std::printf("cap %d: %ld sleeps yielded, %ld took the timer, at most %d game threads yielding at once\n", cap, yielded, timer, most.load());
}
int main() {
    storm(4, 2000);
    storm(1, 500);
    storm(0, 300);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    thread = (HOST / "hos_thread.c").read_text(encoding="utf-8")

    check('#include "short_sleep.h"' in thread, "hos_thread.c does not use the rule")
    procs = block(thread, "static int process_threads(void) {")
    check("GetActiveProcessorGroupCount() == 1 && GetProcessAffinityMask(GetCurrentProcess(), &proc, &sys)" in procs and
          "threads = __builtin_popcountll((uint64_t)proc);" in procs and "#if defined(_WIN32)" in procs,
          "the processors are not the process's affinity mask, or are counted with more than one processor group")
    body = block(thread, "static void sleep_for(int64_t ns, int guest) {")
    # ((Triforce, 11-22, OS-32) the rule with the system: Windows by the processors, any other build by the header's default
    first, last = "        const int threads = process_threads();\n", \
        '        const int how = short_sleep_timer_os(getenv("HOS_SHORT_SLEEP_TIMER"), threads, windows, SHORT_SLEEP_ELSEWHERE);\n'
    check(body.count(first) == 1 and body.count(last) == 1 and body.index(first) < body.index(last),
          "the choice is not the rule's of the switch's value, the process's processors and the system")
    choice = body[body.index(first):body.index(last) + len(last)]
    check("#if defined(_WIN32)\n        const int windows = 1;\n#else\n        const int windows = 0;\n#endif\n" in choice,
          "sleep_for does not tell the rule whether this is Windows' build")
    check("short_sleep_timer(getenv(" not in thread, "sleep_for still chooses without the system: off Windows the switch not "
          "set could not be given a default of its own")
    check('getenv("HOS_SHORT_SLEEP_TIMER") != NULL' not in thread, "the switch is still read by its presence: =0 would turn the timer on")
    check("if (InterlockedCompareExchange(&how_now, word, -1) == -1) {" in body and 'hos_log("sleep: sleeps under 1 ms: %s' in body,
          "the choice is not made once, or leaves no line")
    # ((Triforce, OS-33) the cap: the rule's, in the same word, and its gate around the yielding)
    check('const int cap = short_sleep_pollers(getenv("HOS_SHORT_SLEEP_POLLERS"), getenv("HOS_SHORT_SLEEP_TIMER"), how, threads);' in body and
          "word = short_sleep_word(how, cap);" in body and "const int how = short_sleep_how(word);" in body,
          "the cap is not the rule's of its switch, the timer's switch and the processors, kept with the choice")
    start, end = body.index("    const int how = short_sleep_how(word);"), body.index("    if (!tried) {")
    cut = body[start:end]
    check("if (short_sleep_poll_enter(&short_pollers, short_sleep_cap(word), guest, cur ? hos_thread_serial(cur) : 0, &took)) {" in cut and
          cut.index("short_sleep_poll_enter(") < cut.index("while (hos_now_ns() < until)") < cut.index("short_sleep_poll_leave(&short_pollers, took);")
          < cut.index("return;") < cut.index("__atomic_add_fetch(&short_capped, 1, __ATOMIC_RELAXED);"),
          "the yielding is not inside the cap's gate, or a sleeper over the cap does not go on to the timer")
    check("int serial;" in block(thread, "struct HosThread {") and
          "__atomic_store_n(&t->serial, short_sleep_serial_name(t->name), __ATOMIC_RELAXED);" in block(thread, "void hos_thread_set_name(HosThread *t, const char *name) {") and
          "__atomic_store_n(&t->serial, short_sleep_serial_name(t->name), __ATOMIC_RELAXED);" in block(thread, "Ctx *hos_boot_main_thread(uint64_t stack_size) {"),
          "a thread is not marked as one the frame waits on where it is named")
    check("if (short_sleep_yields(ns, how, guest)) {" in body, "the yield is not the rule's: the game's and the host's sleeps are not told apart")
    away = block(thread, "static void sleep_away(int64_t ns, int guest) {")
    check("sleep_for(ns, guest);" in away and away.index("hos_vcore_away()") < away.index("sleep_for(ns, guest);") < away.index("hos_vcore_back()"),
          "sleep_away does not pass on whose sleep it is, or keeps the core")
    check("void hos_sleep_ns(int64_t ns) { sleep_away(ns, 0); }" in thread and "static void sleep_ns(int64_t ns) { sleep_for(ns, 0); }" in thread,
          "the host's own sleeps are not the host's (they would wait on the timer on a small PC)")
    logged = block(thread, "void hos_sleep_logged(int64_t ns, uint64_t lr) {")
    check(logged.count("sleep_away(ns, 1);") == 2 and "hos_sleep_ns(ns)" not in logged,
          "the game's SleepThread is not the game's own sleep on both of its paths")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_SHORT_SLEEP_TIMER=1`, `=0`" in dev, "docs/development.md: HOS_SHORT_SLEEP_TIMER is not in the switches table")
    check("| `HOS_SHORT_SLEEP_POLLERS=<n>`, `=auto` |" in dev, "docs/development.md: HOS_SHORT_SLEEP_POLLERS is not in the switches table")

    check("`HOS_SHORT_SLEEP_TIMER=game`" in dev and "`SHORT_SLEEP_ELSEWHERE`" in dev,
          "docs/development.md: the HOS_SHORT_SLEEP_TIMER row does not say what =game does, or what other systems do when it is not set")

    with tempfile.TemporaryDirectory(prefix="short-sleep-") as tmp:
        src, exe = Path(tmp) / "sleep.cpp", Path(tmp) / "sleep.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(HOST), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the short sleeps' rule as made:\n" + r.stdout)
        # ((Triforce, 11-22, OS-32) the choosing lines themselves, as Windows' build and as another system's
        src.write_text(CHOICE.replace("@CUT@", choice.replace("_WIN32", "T_WINDOWS")), encoding="utf-8")
        for system, define in (("Windows", ["-DT_WINDOWS"]), ("another system", [])):
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(HOST)] + define +
                           [str(src), "-o", str(exe)], check=True)
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            check(r.returncode == 0, "sleep_for's choice built for %s:\n%s" % (system, r.stdout))

        # ((Triforce, OS-33) the cap's rule and gate; then each broken gate, a changed copy of the header, must fail them)
        def pollers(name, include):
            src, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
            src.write_text(POLLERS, encoding="utf-8")
            # (a broken gate leaves a parameter unused: not what it is to fail for)
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-I" + str(include),
                            str(src), "-o", str(exe)], check=True)
            return subprocess.run([str(exe)], capture_output=True, text=True)
        r = pollers("pollers", HOST)
        check(r.returncode == 0, "the cap on yielding sleepers as made:\n" + r.stdout)
        header = (HOST / "short_sleep.h").read_text(encoding="utf-8")
        for i, (what, old, new) in enumerate(GATE_MUTANTS):
            check(header.count(old) == 1, "short_sleep.h: %r is not there once (update the test with the header)" % old)
            folder = Path(tmp) / ("gate%d" % i)
            folder.mkdir()
            (folder / "short_sleep.h").write_text(header.replace(old, new), encoding="utf-8")
            r = pollers("gate%d" % i, folder)
            check(r.returncode != 0, "a gate with %s still passed the checks" % what)

        def storm(name, text):
            src, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
            src.write_text(STORM.replace("/* CUT */", text), encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-pthread",
                            "-I" + str(HOST), str(src), "-o", str(exe)], check=True)
            return subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        r = storm("storm", cut)
        check(r.returncode == 0, "hos_thread.c's yield branch on threads:\n" + r.stdout)
        print(r.stdout.strip())
        leave = "            short_sleep_poll_leave(&short_pollers, took);\n"
        check(cut.count(leave) == 1, "the leave is not in the cut once")
        r = storm("storm-leak", cut.replace(leave, "            (void)took;\n"))
        check(r.returncode != 0 and "short_pollers == 0" in r.stdout, "a yield branch that never gives its count back still passed")
    print("PASS: the game's short sleeps wait on the timer with 6 or fewer processors, the host's yield, and the switch reads its value; "
          "off Windows, not set: the header's default (the game's own on the timer), and =game puts the game's own on the timer anywhere")
    print("PASS: the cap on yielding sleepers is off unless set, lets the cap's worth in and sends the next to the timer, on threads too")


if __name__ == "__main__":
    main()
