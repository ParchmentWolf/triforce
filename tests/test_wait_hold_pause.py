"""A fence wait's hold for stopped work: counted, and with RX_VK_WAIT_HOLD_PAUSE_US paced by PAUSE gaps, the order lock taken
only when it can say something new (gpu/vk/wait_hold.h, vk_replay.cpp wait(); no game, no GPU).

(Triforce, 11-22, the performance audit's THREAD-11, after Source B's.) Off (0) unless set: a yield a look and the lock at
each look, as before.

The header's rules are compiled and run (the switch's values, when a look takes the lock, the gap's PAUSEs, the order line).
Then the hold loop itself, cut out of vk_replay.cpp's wait() with the real OrderMutex, runs against stand-ins: the fence's
value, the oldest unfinished stopped submission (which, as in the renderer, changes only inside a section of the order
lock), the flush, the forced drain, and a clock that only the loop's own yields and PAUSEs move, so nothing depends on this
PC's speed. The wait modelled: the waiter is the hold; the waker is another thread's section of the order lock that lets
the stopped work on, or a signal of the CPU's (ev_cpu_any) queued without a section, which a section then acts on; the
condition is "the oldest unfinished stopped submission is past this fence".

- 0: every look takes the lock and yields; nothing changing, the hold ends forced at its bound with one drain;
- 2: no yield, a gap of PAUSEs (16 at a time, 2 us on the clock) between looks, the lock at the first look only while no
  section leaves; a section that leaves without changing the answer costs one more take and no more; a signal of the
  CPU's queued: the lock at every look until a section has taken it, then left alone again; where the waiter's own
  section acts on a queued signal (the audit's SYNC-59 gives the hold such a look; it is not in this tree) the work it
  lets on is seen at the first look after the signal, not at the bound; a section that lets the work on is seen at the
  first look after it leaves and the hold ends there, no drain; a section in progress on another thread (the lock held
  across many looks) never blocks the waiter and is seen when it leaves; the fence done ends the hold at that look; the
  wait's own time ends it; the bound still forces the drain;
- the hold is skipped as before with no time to wait, with the replay on its own thread, and with nothing stopped;
- on real threads, 300 rounds: a signaller makes sections at its own pace and then lets the work on, by a section of its
  own or (every other round) by a signal of the CPU's that an order thread's section acts on when it gets the lock (as
  sync_watch), while the waiter holds with the bound far away: every round ends by "let on" (a lost section or signal
  would hang the round: the test's time limit).
Each rule taken out of the cut loop in turn (a mutation) must make a case fail.

    python -I -B tests/test_wait_hold_pause.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
HOLD = "    if (timeout_ns && !async_on() && blocked_n.load()) {"


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdarg>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include "lock_census.h"
#include "wait_hold.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
namespace mkwvk {
void logf(const char*, ...) {}
static std::atomic<int> order_waiters{0};
static std::mutex order_wait_mu;
static std::condition_variable order_wait_cv;
/* ORDER */;
/* ORDER_UNLOCK */
static OrderMutex sync_order_mu;

// ---- the stand-ins ----
// the clock: moved by the loop's own yields (1 us each) and PAUSEs (50 ns each) alone
static int64_t clock_ns = 1000000000;
struct test_clock {
    typedef std::chrono::nanoseconds duration;
    typedef duration::rep rep;
    typedef duration::period period;
    typedef std::chrono::time_point<test_clock> time_point;
    static time_point now() { return time_point(duration(clock_ns)); }
};
static int64_t ticks, yields, pauses, flushes, drains, looks_now, asked_unlocked;
static void (*at_tick)(int64_t) = nullptr;   // (what the rest of the program does meanwhile, by the loop's ticks)
static void tick() {
    ticks++;
    if (at_tick) at_tick(ticks);
}
static void test_yield() {
    yields++, clock_ns += 1000;
    tick();
}
namespace gate_wait {
static void pause() {
    pauses++, clock_ns += 50;
    if (pauses % wait_hold::kPauses == 0) tick();
}
} // namespace gate_wait
static bool async = false;
static bool async_on() { return async; }
static std::atomic<int> blocked_n{1};
enum { FR_WAIT = 2 };
static void queue_flush_for(int why, uint64_t = UINT64_MAX) { CHECK(why == FR_WAIT); flushes++; }
static std::atomic<uint64_t> done_value{0}, oldest{0};
static std::atomic<bool> ev_cpu_any{false};   // (a signal of the CPU's queued, which no section has acted on yet)
static std::atomic<uint64_t> signal_oldest{0};   // (the oldest unfinished stopped submission once a section has acted on it)
static bool own_look_acts = false;   // (the waiter's own section acts on a queued signal, as the audit's SYNC-59 adds)
// (SYNC-59's own look in the hold's lock section, RX_VK_ORDER_WAKE=1: off here, as by default. own_look_acts above plays it)
static bool order_wake_on() { return false; }
static int64_t st_resumed, st_wake_looks, st_wake_resumes;
static void burst_begin(int) {}
static void schedule() {}
static void burst_end() {}
static void update_blocked() {}
static uint64_t completed() {
    looks_now++;
    return done_value.load();
}
// (inside a section: the queued signal taken in, and what its event lets on let on, as schedule() does)
static void apply_signal() {
    if (sync_order_mu.entered.load() - sync_order_mu.left.load() != 1) asked_unlocked++;
    oldest = signal_oldest.load();
    ev_cpu_any = false;
}
// (asked only inside a section of the order lock, as the renderer's state it stands for is only changed in one)
static uint64_t oldest_unfinished() {
    if (sync_order_mu.entered.load() - sync_order_mu.left.load() != 1) asked_unlocked++;
    if (own_look_acts && ev_cpu_any.load()) apply_signal();
    return oldest.load();
}
static void sync_drain(int why) { CHECK(why == 2); drains++; }
static wait_hold::Stats hold_stats;
static int64_t pause_now;
static int64_t wait_hold_pause_ns() { return pause_now; }

// 1: the fence was done in the hold; 0: the hold is over (or there was none) and the timeline's own wait follows
static int hold(uint64_t f, uint64_t timeout_ns) {
/* HOLD */
    return 0;
}
} // namespace mkwvk
using namespace mkwvk;

static const uint64_t F = 100;
// another thread's section of the order lock, run between two of the loop's steps
static void section(uint64_t new_oldest) {
    std::lock_guard lk(sync_order_mu);
    oldest = new_oldest;
}
static int64_t held0;
static void fresh(int64_t pause_us) {
    pause_now = pause_us * 1000;
    ticks = yields = pauses = flushes = drains = looks_now = asked_unlocked = 0;
    at_tick = nullptr, async = false, blocked_n = 1, done_value = 0, oldest = F;   // (stopped work at this fence: needed)
    ev_cpu_any = false, signal_oldest = F, own_look_acts = false;
    for (auto* a : {&hold_stats.holds, &hold_stats.looks, &hold_stats.locks, &hold_stats.held_ns}) a->store(0);
    for (auto& e : hold_stats.ended) e.store(0);
    held0 = clock_ns;
}
static int64_t ended(int how) { return hold_stats.ended[how].load(); }
static int64_t section_looks;   // (the looks made when a scripted section left)

int main(int argc, char** argv) {
    const std::string c = argc > 1 ? argv[1] : "";
    const uint64_t far = 60000000000ull;
    if (c == "script") {
        // ---- 0: as before ----
        fresh(0);
        CHECK(hold(F, far) == 0);
        CHECK(drains == 1 && ended(wait_hold::kForced) == 1 && hold_stats.holds.load() == 1);
        CHECK(hold_stats.looks.load() == looks_now && looks_now == 3001);        // (a look a microsecond for the bound's 3 ms)
        CHECK(hold_stats.locks.load() == looks_now && asked_unlocked == 0);      // (the lock at every look)
        CHECK(yields == looks_now - 1 && pauses == 0 && flushes == looks_now);   // (a yield after every look but the last)
        CHECK(hold_stats.held_ns.load() == clock_ns - held0 && clock_ns - held0 == 3000000);
        // ---- 2 us: the gap, and the lock at the first look alone ----
        fresh(2);
        CHECK(hold(F, far) == 0);
        CHECK(drains == 1 && ended(wait_hold::kForced) == 1);                    // (the bound and the forced drain stay)
        CHECK(yields == 0 && pauses == (looks_now - 1) * 48);                    // (three rounds of 16 PAUSEs make 2 us here)
        CHECK(hold_stats.locks.load() == 1 && asked_unlocked == 0 && hold_stats.looks.load() == looks_now);
        CHECK(looks_now == 1251 && flushes == looks_now);                        // (a look every 2.4 us)
        // a section that leaves and changes nothing: one more take, then none
        fresh(2);
        at_tick = [](int64_t t) { if (t == 300) section(F); };
        CHECK(hold(F, far) == 0);
        CHECK(hold_stats.locks.load() == 2 && ended(wait_hold::kForced) == 1 && drains == 1);
        // a signal of the CPU's queued for a while (it acts in no section until the order thread's): the lock at every look
        // meanwhile, as before, and left alone again once a section has taken the signal
        fresh(2);
        at_tick = [](int64_t t) {
            if (t == 300) ev_cpu_any = true;
            if (t == 600) { std::lock_guard lk(sync_order_mu); ev_cpu_any = false; }
        };
        CHECK(hold(F, far) == 0);
        CHECK(hold_stats.locks.load() == 1 + 100 + 1 && ended(wait_hold::kForced) == 1 && drains == 1);
        // the waiter's own section acting on a queued signal (SYNC-59's look in the hold): no other section leaves, and the work
        // the signal lets on is seen at the first look after it, not forced at the bound
        fresh(2);
        own_look_acts = true, signal_oldest = F + 1;
        at_tick = [](int64_t t) { if (t == 300) ev_cpu_any = true, section_looks = looks_now; };
        CHECK(hold(F, far) == 0);
        CHECK(ended(wait_hold::kLetOn) == 1 && drains == 0 && hold_stats.locks.load() == 2 && looks_now == section_looks + 1);
        CHECK(!ev_cpu_any.load() && asked_unlocked == 0);
        // a section that lets the work on: seen at the first look after it leaves
        fresh(2);
        at_tick = [](int64_t t) { if (t == 600) section(F + 1), section_looks = looks_now; };
        CHECK(hold(F, far) == 0);
        CHECK(ended(wait_hold::kLetOn) == 1 && drains == 0 && hold_stats.locks.load() == 2);
        CHECK(looks_now == section_looks + 1 && looks_now < 300);
        // the same at 0
        fresh(0);
        at_tick = [](int64_t t) { if (t == 200) section(F + 1), section_looks = looks_now; };
        CHECK(hold(F, far) == 0);
        CHECK(ended(wait_hold::kLetOn) == 1 && drains == 0 && looks_now == section_looks + 1);
        // the fence done: the hold ends at that look, with the lock not asked again
        for (int64_t us : {0, 2}) {
            fresh(us);
            at_tick = [](int64_t t) { if (t == 150) done_value = F, section_looks = looks_now; };
            CHECK(hold(F, far) == 1);
            CHECK(ended(wait_hold::kMet) == 1 && drains == 0 && looks_now == section_looks + 1);
            CHECK(hold_stats.locks.load() == (us ? 1 : looks_now - 1));
        }
        // the wait's own time: 1 ms, before the bound
        for (int64_t us : {0, 2}) {
            fresh(us);
            CHECK(hold(F, 1000000) == 0);
            CHECK(ended(wait_hold::kTimedOut) == 1 && drains == 0 && clock_ns - held0 >= 1000000 && clock_ns - held0 < 1010000);
        }
        // a fence done already, and work older than the stopped ones: one look
        fresh(2), done_value = F + 5;
        CHECK(hold(F, far) == 1 && looks_now == 1 && hold_stats.locks.load() == 0);
        fresh(2), oldest = F + 1;
        CHECK(hold(F, far) == 0 && looks_now == 1 && ended(wait_hold::kLetOn) == 1 && hold_stats.locks.load() == 1);
        // no hold at all: no time to wait, the replay on its own thread, nothing stopped
        fresh(2);
        CHECK(hold(F, 0) == 0);
        async = true;
        CHECK(hold(F, far) == 0);
        async = false, blocked_n = 0;
        CHECK(hold(F, far) == 0);
        CHECK(looks_now == 0 && hold_stats.holds.load() == 0 && flushes == 0);
        // a section in progress on another thread: the lock held across many looks, which never block on it
        if (fails) return 1;   // (a loop that already takes the lock at every look would wait here for good)
        {
            fresh(2);
            static std::atomic<int> stage{0};
            stage = 0;
            std::thread other([] {
                while (stage.load() < 1) std::this_thread::yield();
                sync_order_mu.lock();
                oldest = F + 1;   // (the work let on, the section not left yet)
                stage = 2;
                while (stage.load() < 3) std::this_thread::yield();
                sync_order_mu.unlock();
                stage = 4;
            });
            at_tick = [](int64_t t) {
                if (t == 100) { stage = 1; while (stage.load() < 2) std::this_thread::yield(); }
                if (t == 400) { stage = 3; while (stage.load() < 4) std::this_thread::yield(); section_looks = looks_now; }
            };
            CHECK(hold(F, far) == 0);
            other.join();
            CHECK(ended(wait_hold::kLetOn) == 1 && drains == 0 && hold_stats.locks.load() == 2 && looks_now == section_looks + 1);
        }
        // the order line
        fresh(2);
        hold_stats.done(wait_hold::kMet, 10, 1, 1500000), hold_stats.done(wait_hold::kForced, 1251, 1, 3000000);
        hold_stats.done(wait_hold::kLetOn, 40, 2, 100000), hold_stats.done(wait_hold::kTimedOut, 400, 1, 1000000);
        char line[512];
        wait_hold::describe(hold_stats, 2000, line, sizeof line);
        if (strcmp(line, "vk: fence waits held for stopped work: 4 holds, 1701 looks, 5.6 ms held, the order lock taken 5 times; ended by "
                         "the fence done 1, the work let on 1, the wait's time up 1, forced on at the bound 1 (RX_VK_WAIT_HOLD_PAUSE_US=2)")) {
            std::printf("FAIL: the line is\n  %s\n", line);
            fails++;
        }
        // the rules alone
        using namespace wait_hold;
        CHECK(pause_ns(nullptr) == 0 && pause_ns("") == 0 && pause_ns("0") == 0 && pause_ns("x") == 0 && pause_ns("-3") == 0);
        CHECK(pause_ns("2") == 2000 && pause_ns("1") == 1000 && pause_ns("1000") == 1000000 && pause_ns("5000") == 1000000);
        CHECK(takes_lock(0, false, 0, 0, false) && takes_lock(0, true, 7, 8, false) && takes_lock(0, true, 7, 9, false));   // (0: always)
        CHECK(takes_lock(2000, false, 0, 0, false) && takes_lock(2000, false, 7, 8, false));           // (not asked yet)
        CHECK(!takes_lock(2000, true, 7, 8, false));                                                   // (only its own section left)
        CHECK(takes_lock(2000, true, 7, 9, false) && takes_lock(2000, true, 7, 100, false) && takes_lock(2000, true, 7, 7, false));
        CHECK(takes_lock(2000, true, 7, 8, true));                                                     // (a signal of the CPU's queued)
        int64_t t = 0, n = 0;
        gap(2000, [&] { return t; }, [&] { n++, t += 50; });
        CHECK(n == 48 && t == 2400);
        t = 0, n = 0;
        gap(100, [&] { return t; }, [&] { n++, t += 50; });
        CHECK(n == 16);                                                                                // (a round at least)
    } else if (c == "storm") {   // RX_VK_WAIT_HOLD_US far away: only a section that lets the work on ends a round
        for (int round = 0; round < 300 && !fails; round++) {
            fresh(2);
            const bool by_signal = round % 2 == 1;   // (the work let on by a signal of the CPU's rather than by a section)
            signal_oldest = F + 1;
            std::atomic<bool> begun{false}, over{false};
            // the order thread, as sync_watch: a section when it can get the lock, which acts on a queued signal
            std::thread order([&] {
                while (!over.load()) {
                    if (!ev_cpu_any.load()) {
                        std::this_thread::yield();
                        continue;
                    }
                    std::unique_lock lk(sync_order_mu, std::try_to_lock);
                    if (lk && ev_cpu_any.load()) apply_signal();
                }
            });
            std::thread signaller([&] {
                begun = true;
                unsigned seed = 77u + (unsigned)round * 7919u;
                const int sections = 1 + round % 7;
                for (int i = 0; i < sections; i++) {
                    for (unsigned spin = (seed = seed * 1103515245u + 12345u) >> 20; spin; spin--) gate_wait_spin();
                    section(F);          // (a section that changes nothing)
                }
                if (by_signal) ev_cpu_any.store(true, std::memory_order_release);   // (queued without a section)
                else section(F + 1);     // (the one that lets the work on)
            });
            while (!begun.load()) std::this_thread::yield();
            CHECK(hold(F, 1ull << 62) == 0);
            signaller.join();
            over = true;
            order.join();
            CHECK(ended(wait_hold::kLetOn) == 1 && drains == 0 && asked_unlocked == 0 && oldest.load() == F + 1 && !ev_cpu_any.load());
        }
    } else {
        std::printf("FAIL: unknown case\n");
        fails++;
    }
    if (!fails) std::printf("PASS %s\n", c.c_str());
    return fails ? 1 : 0;
}
'''

# (each: what is taken out, the text in the cut loop as the fixture has it, what replaces it)
MUTATIONS = [
    ("the lock taken again once another section has left",
     "wait_hold::takes_lock(pause_ns, asked, seen_left, sync_order_mu.left.load(std::memory_order_acquire),\n"
     "                                      ev_cpu_any.load(std::memory_order_acquire))", "(!pause_ns || !asked)"),
    ("the lock taken while a signal of the CPU's is queued", "ev_cpu_any.load(std::memory_order_acquire))", "false)"),
    ("the lock left alone while no section has left",
     "seen_left = sync_order_mu.left.load(std::memory_order_relaxed);", "seen_left = sync_order_mu.left.load(std::memory_order_relaxed) + 1;"),
    ("the gap in place of the yield", "if (!pause_ns) test_yield();", "if (true) test_yield();"),
    ("the yield with the switch at 0", "if (!pause_ns) test_yield();", "if (false) test_yield();"),
    ("the forced drain at the bound", "                sync_drain(2);\n", ""),
    ("the hold's count", "        hold_stats.done(end, looks, locks, since());\n", ""),
    ("the fence's value at every look", "            if (completed() >= f) {", "            if (looks == 1 && completed() >= f) {"),
]


def read_sources(replay, dev):
    if '#include "wait_hold.h"' not in replay:
        fail("vk_replay.cpp does not include wait_hold.h")
    pause = block(replay, "int64_t wait_hold_pause_ns() {")
    if 'static const int64_t v = wait_hold::pause_ns(getenv("RX_VK_WAIT_HOLD_PAUSE_US"));' not in pause:
        fail("vk_replay.cpp: the switch is not the header's rule over RX_VK_WAIT_HOLD_PAUSE_US, read once")
    stats = block(replay, "void log_order_stats() {")
    if "wait_hold::describe(hold_stats, wait_hold_pause_ns(), line, sizeof line);" not in stats:
        fail("vk_replay.cpp log_order_stats: the holds are not in the order's report")
    wait = block(replay, "int wait(uint64_t f, uint64_t timeout_ns) {")
    if wait.count(HOLD) != 1:
        fail("vk_replay.cpp wait(): the hold for stopped work is not there once")
    hold = block(wait, HOLD)
    for need in ("std::chrono::steady_clock", "std::this_thread::yield();", "gate_wait::pause"):
        if need not in hold:
            fail("vk_replay.cpp wait(): %r is not in the hold loop (the fixture stands in for it)" % need)
    if not hold.index("if (completed() >= f) {") < hold.index("wait_hold::takes_lock("):
        fail("vk_replay.cpp wait(): the fence's value is not read before the lock is thought of")
    if "| `RX_VK_WAIT_HOLD_PAUSE_US=<us>` |" not in dev:
        fail("docs/development.md: RX_VK_WAIT_HOLD_PAUSE_US is not in the switches table")
    # (the loop as the fixture runs it: the clock, the yield and the PAUSE are the fixture's)
    return hold.replace("std::chrono::steady_clock", "test_clock").replace("std::this_thread::yield();", "test_yield();")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    try:
        replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
        hold = read_sources(replay, (ROOT / "docs/development.md").read_text(encoding="utf-8"))
        fixture = FIXTURE.replace("/* ORDER */", block(replay, "struct OrderMutex {")) \
            .replace("/* ORDER_UNLOCK */", block(replay, "void OrderMutex::unlock() {")) \
            .replace("gate_wait_spin();", "_mm_pause();")
    except (ValueError, OSError) as e:
        fail("a text this test reads is not there (%s)" % e)
    env = {k: v for k, v in os.environ.items() if k not in ("RX_VK_WAIT_HOLD_US", "RX_VK_WAIT_HOLD_PAUSE_US", "RX_VK_LOCK_CENSUS")}
    with tempfile.TemporaryDirectory(prefix="wait-hold-") as tmp:
        def build(name, loop):
            src, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
            src.write_text("#include <immintrin.h>\n" + fixture.replace("/* HOLD */", loop), encoding="utf-8")
            built = subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                                    "-Wno-unused-but-set-variable", "-pthread", "-I" + str(VK), str(src), "-o", str(exe)],
                                   capture_output=True, text=True)
            if built.returncode:
                print(built.stdout + built.stderr)
                fail("the fixture did not build (%s)" % name)
            return exe

        def run(exe, case, **switches):
            try:
                return subprocess.run([str(exe), case], env=dict(env, **switches), capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                return subprocess.CompletedProcess([], 1, "no end in 120 s (a section never seen, or a look that blocked)", "")

        exe = build("hold", hold)
        for case, switches in (("script", {}), ("storm", {"RX_VK_WAIT_HOLD_US": "60000000000"})):
            done = run(exe, case, **switches)
            if done.returncode or "PASS " + case not in done.stdout:
                print(done.stdout[-3000:] + done.stderr[-1000:])
                fail("the hold loop: " + case)
            print("PASS " + case)
        for i, (what, old, new) in enumerate(MUTATIONS):
            if hold.count(old) != 1:
                fail("mutation %r: %r is not in the cut loop once (update the test with the code)" % (what, old))
            done = run(build("mutant%d" % i, hold.replace(old, new)), "script")
            if done.returncode == 0:
                fail("mutation %r: the script still passed without it" % what)
            first = [line for line in done.stdout.splitlines() if line.startswith("FAIL") or "no end" in line]
            print("PASS mutation: without %s the script fails (%s)" % (what, first[0][:110] if first else "exit %d" % done.returncode))
    print("PASS: the hold is counted; at 0 it is as before; with the gap the lock is taken only after a section has left, and no section is missed")


if __name__ == "__main__":
    main()
