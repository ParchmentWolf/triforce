"""The lock census: who holds the lock a thread waits for (gpu/vk/lock_census.h, RX_VK_LOCK_CENSUS=1; no game, no GPU).

(Triforce, 11-22, the performance audit's THREAD-68, after Source B's.) A busy lock notes its waiter, the thread that held
it and the time waited; a thread of the census's own logs the pairs that waited longest. Off unless set, and off, every
lock is taken exactly as before.

DrainingMutex (vk_recorder.h: replay_mu) and OrderMutex (vk_replay.cpp: sync_order_mu) are cut out of the sources and
compiled with lock_census.h; the fixture runs as a process a case:

- on: a free lock reads no clock and counts nothing, and the lock knows its holder while it is held and not after; a
  thread that comes for a held lock is counted against the holder for exactly the time it waited (the fixture's own
  clock: the holder lets go 50 ms after the waiter's first clock read) under that lock's name, for both locks and for a
  CensusMutex under std::lock_guard and std::unique_lock; the report is the 12 longest pairs, longest first, in the log's
  form, and starts again after it; the reporting thread starts at the first counted wait and logs; what the locks do
  besides is unchanged (the order lock's sections counted, the drain before the replay lock is let go); a storm of four
  threads through both locks in the product's order keeps what they guard exact;
- off (the switch not set, and 0): the same held lock and the same storm count nothing, read no clock, start no thread,
  and no lock ever notes a holder;
- the lab's phases: with the switch on and the phase off, nothing is counted.

The sources are read for the rest: the six locks go through the census, the holder is cleared just before each unlock
(after the replay lock's drain and the order lock's section count), and the switch is in the switches table.

    python -I -B tests/test_lock_census.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


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
#include <condition_variable>
#include <cstdarg>
#include "lock_census.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
namespace mkwvk {
static std::mutex log_mu;
static std::vector<std::string> logged;
void logf(const char* fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    std::lock_guard lk(log_mu);
    logged.emplace_back(line);
}
namespace rec {
// (what DrainingMutex uses of the recorder, standing in)
struct Recorder {};
static Recorder g_rec;
static thread_local Recorder* t_prod = nullptr;
enum { DEFER = 1, THREAD = 2 };
static int mode() { return THREAD; }
static bool (*g_direct_hook)() = nullptr;   // (the lab's norec knob: not set here)
enum Bound { B_REPLAY_UNLOCK };
static std::atomic<int> boundaries{0};
static std::atomic<bool> held_at_boundary{true};
struct DrainingMutex;
static DrainingMutex* watched = nullptr;
static void boundary(Bound);
/* DRAINING */;
// (the drain runs while the lock is still held and still says who holds it)
static void boundary(Bound) {
    boundaries++;
    if (watched && lock_census::counting() && !watched->owner.load()) held_at_boundary = false;
}
} // namespace rec
static std::atomic<int> order_waiters{0};
static std::mutex order_wait_mu;
static std::condition_variable order_wait_cv;
/* ORDER */;
/* ORDER_UNLOCK */
} // namespace mkwvk
using namespace mkwvk;

// the fixture's clock: it moves only when a case moves it, and counts its reads
static std::atomic<int64_t> clock_now{1000000000000LL};
static std::atomic<int> clock_reads{0};
static int64_t test_clock() {
    clock_reads++;
    return clock_now.load();
}
// (a thread's name as the renderer would read its description: lock_census.h has no system call of its own)
static thread_local const char* my_name = "";
static void name_thread(const char* name) { my_name = name; }
static void read_name(char* out, size_t cap) { snprintf(out, cap, "%s", my_name); }
static std::atomic<int> report_starts{0};
static size_t pairs() {
    lock_census::Book& b = lock_census::book();
    std::lock_guard lk(b.mu);
    return b.pairs.size();
}
static bool reporter() {
    lock_census::Book& b = lock_census::book();
    std::lock_guard lk(b.mu);
    return b.reporter;
}
// A holder has the lock; a waiter comes for it; the holder lets go 50 ms of the fixture's clock after the waiter's first clock
// read (which it makes only when it finds the lock busy and the census counts). Without the census the waiter reads no clock, so
// the holder lets go once the waiter is on its way. Returns the clock reads the waiter made
template <class M>
static int held_and_waited(M& m, bool counted) {
    std::atomic<int> stage{0};
    const int reads0 = clock_reads.load();
    std::thread holder([&] {
        name_thread("holder");
        m.lock();
        stage = 1;
        while (stage.load() < 2) std::this_thread::yield();
        if (counted) {
            while (clock_reads.load() == reads0) std::this_thread::yield();   // (the waiter found it busy and read the clock)
            clock_now += 50000000;
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(30));       // (long enough for the waiter to be at the lock)
        }
        m.unlock();
    });
    while (stage.load() < 1) std::this_thread::yield();
    std::thread waiter([&] {
        name_thread("waiter");
        stage = 2;
        m.lock();
        m.unlock();
    });
    holder.join(), waiter.join();
    return clock_reads.load() - reads0;
}
static void expect_line(const char* lock) {
    // (10 s after the census's count began: 50 ms waited in 10 s is 5.0 ms/s, a tenth of a wait a second)
    int64_t since = 0;
    {
        lock_census::Book& b = lock_census::book();
        std::lock_guard lk(b.mu);
        since = b.since_ns;
    }
    const std::vector<std::string> lines = lock_census::report(since + 10000000000LL);
    CHECK(lines.size() == 1);
    if (lines.size() != 1) return;
    const std::string want = std::string("vk: lock census: waiter <- holder (") + lock + ") 5.0 ms/s (0/s, 50000 us each)";
    if (lines[0] != want) { std::printf("FAIL: the line is\n  %s\nnot\n  %s\n", lines[0].c_str(), want.c_str()); fails++; }
    CHECK(pairs() == 0 && lock_census::report(since + 20000000000LL).empty());   // (the counts start again)
}
// four threads through the order lock and then the replay lock, as the product takes them: what they guard stays exact
template <class O, class R>
static void storm(O& order, R& replay) {
    long guarded = 0;
    std::vector<std::thread> threads;
    for (int t = 0; t < 4; t++)
        threads.emplace_back([&] {
            for (int i = 0; i < 20000; i++) {
                std::lock_guard a(order);
                std::lock_guard b(replay);
                guarded = guarded + 1;
            }
        });
    for (auto& t : threads) t.join();
    CHECK(guarded == 4 * 20000);
}

int main(int argc, char** argv) {
    const std::string c = argc > 1 ? argv[1] : "";
    lock_census::now_ns = test_clock;
    lock_census::g_thread_name = read_name;
    lock_census::g_report_start = [] { report_starts++; };
    lock_census::period_ms = 3600000;   // (the reporting thread stays out of the scripted checks until it is asked for)
    static rec::DrainingMutex replay_mu;
    static OrderMutex sync_order_mu;
    static lock_census::CensusMutex held_mu{"held_mu"};
    rec::watched = &replay_mu;
    if (c == "on") {
        CHECK(lock_census::enabled() && lock_census::counting());
        // free locks: no clock, nothing counted, the holder known only while held
        for (int i = 0; i < 1000; i++) {
            replay_mu.lock();
            CHECK(replay_mu.owner.load() == lock_census::me());
            replay_mu.unlock();
            sync_order_mu.lock();
            CHECK(sync_order_mu.owner.load() == lock_census::me() && sync_order_mu.entered.load() - sync_order_mu.left.load() == 1);
            sync_order_mu.unlock();
            { std::lock_guard lk(held_mu); CHECK(held_mu.owner.load() == lock_census::me()); }
            CHECK(replay_mu.try_lock() && replay_mu.owner.load() == lock_census::me());
            replay_mu.unlock();
            CHECK(sync_order_mu.try_lock() && sync_order_mu.owner.load() == lock_census::me());
            sync_order_mu.unlock();
            std::unique_lock ul(held_mu, std::try_to_lock);
            CHECK(ul.owns_lock());
        }
        CHECK(!replay_mu.owner.load() && !sync_order_mu.owner.load() && !held_mu.owner.load());
        CHECK(clock_reads.load() == 0 && pairs() == 0 && !reporter());
        CHECK(sync_order_mu.entered.load() == 2000 && sync_order_mu.left.load() == 2000);   // (the sections counted as before)
        CHECK(rec::boundaries.load() == 2000 && rec::held_at_boundary.load());                // (the drain at every unlock, the lock still held)
        CHECK(rec::t_prod == nullptr);
        // a held lock: the wait counted against the holder, for the time waited, under the lock's name
        CHECK(held_and_waited(replay_mu, true) == 2);   // (two clock reads: before the wait and after it)
        CHECK(reporter());                               // (the first counted wait starts the reporting thread)
        for (int i = 0; i < 500 && !report_starts.load(); i++) std::this_thread::sleep_for(std::chrono::milliseconds(10));
        CHECK(report_starts.load() == 1);
        expect_line("replay_mu");
        CHECK(held_and_waited(sync_order_mu, true) == 2);
        expect_line("sync_order_mu");
        CHECK(held_and_waited(held_mu, true) == 2);
        expect_line("held_mu");
        // a busy try_lock is not a wait
        {
            std::lock_guard lk(held_mu);
            std::thread([&] { CHECK(!held_mu.try_lock()); }).join();
        }
        CHECK(pairs() == 0);
        // the report: the 12 longest of 20 pairs, longest first
        {
            static lock_census::Slot holders[20];
            lock_census::Book& b = lock_census::book();
            for (int i = 0; i < 20; i++) {
                char name[16];
                snprintf(name, sizeof name, "h%02d", i);
                { std::lock_guard lk(b.mu); holders[i].name = lock_census::intern(b, name); }
                lock_census::waited(lock_census::me(), &holders[i], "pools_mu", (i + 1) * 1000000LL, clock_now.load());
                lock_census::waited(lock_census::me(), &holders[i], "pools_mu", (i + 1) * 1000000LL, clock_now.load());
            }
            lock_census::waited(lock_census::me(), nullptr, "cap_mu", 500, clock_now.load());   // (a holder not known)
            CHECK(pairs() == 21);
            const std::vector<std::string> lines = lock_census::report(clock_now.load() + 100000000000LL);
            CHECK(lines.size() == 12);
            for (size_t i = 0; i < lines.size(); i++) {
                char want[64];
                snprintf(want, sizeof want, " <- h%02d (pools_mu) ", 19 - (int)i);
                CHECK(lines[i].find(want) != std::string::npos);
            }
            CHECK(pairs() == 0);
        }
        // the reporting thread logs what is counted (the fixture's clock stands still: it reports by its own sleep)
        clock_now += 200000000000LL;
        lock_census::waited(lock_census::me(), nullptr, "sync_mu", 7000000, clock_now.load());
        clock_now += 1000000000;
        lock_census::period_ms = 20;
        bool told = false;
        for (int i = 0; i < 500 && !told; i++) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            std::lock_guard lk(log_mu);
            for (const std::string& line : logged) told = told || line.find("(sync_mu)") != std::string::npos;
        }
        CHECK(told);
        storm(sync_order_mu, replay_mu);
        CHECK(!replay_mu.owner.load() && !sync_order_mu.owner.load());
        CHECK(sync_order_mu.entered.load() == sync_order_mu.left.load());
    } else if (c == "off") {
        CHECK(!lock_census::enabled() && !lock_census::counting());
        CHECK(held_and_waited(replay_mu, false) == 0);
        CHECK(held_and_waited(sync_order_mu, false) == 0);
        CHECK(held_and_waited(held_mu, false) == 0);
        replay_mu.lock();
        CHECK(!replay_mu.owner.load());   // (off: a lock notes no holder)
        replay_mu.unlock();
        storm(sync_order_mu, replay_mu);
        CHECK(clock_reads.load() == 0 && pairs() == 0 && !reporter() && report_starts.load() == 0);
        CHECK(!replay_mu.owner.load() && !sync_order_mu.owner.load() && !held_mu.owner.load());
        CHECK(sync_order_mu.entered.load() == sync_order_mu.left.load() && sync_order_mu.entered.load() > 80000);
        CHECK(rec::boundaries.load() > 80000);
    } else if (c == "phase") {   // (the switch on, the lab's phase off)
        CHECK(lock_census::enabled());
        lock_census::phase_on = false;
        CHECK(!lock_census::counting());
        CHECK(held_and_waited(replay_mu, false) == 0);
        storm(sync_order_mu, replay_mu);
        CHECK(clock_reads.load() == 0 && pairs() == 0 && !reporter());
        lock_census::phase_on = true;
        replay_mu.lock();
        CHECK(replay_mu.owner.load() == lock_census::me());   // (and counting again in the next phase)
        replay_mu.unlock();
    } else {
        std::printf("FAIL: unknown case\n");
        fails++;
    }
    if (!fails) std::printf("PASS %s\n", c.c_str());
    std::fflush(stdout);
    std::_Exit(fails ? 1 : 0);   // (the reporting thread sleeps on: no wait for it)
}
'''


def read_sources(recorder, replay, memory, dev):
    if '#include "lock_census.h"' not in recorder or '#include "lock_census.h"' not in memory:
        fail("vk_recorder.h or vk_memory.cpp does not include lock_census.h")
    draining = block(recorder, "struct DrainingMutex {")
    if 'lock_census::lock(m, owner, "replay_mu");' not in draining or "if (!lock_census::try_lock(m, owner)) return false;" not in draining:
        fail("DrainingMutex does not take its mutex through the census")
    if not draining.index("boundary(B_REPLAY_UNLOCK);") < draining.index("lock_census::unlocking(owner);") < draining.index("m.unlock();"):
        fail("DrainingMutex: the holder is not cleared after the drain and just before the unlock")
    order = block(replay, "struct OrderMutex {")
    if 'lock_census::lock(mu, owner, "sync_order_mu");' not in order or "if (!lock_census::try_lock(mu, owner)) return false;" not in order:
        fail("OrderMutex does not take its mutex through the census")
    unlock = block(replay, "void OrderMutex::unlock() {")
    if not unlock.index("left.fetch_add(1, std::memory_order_seq_cst);") < unlock.index("lock_census::unlocking(owner);") < unlock.index("mu.unlock();"):
        fail("OrderMutex::unlock: the holder is not cleared after the section is counted and just before the unlock")
    if 'lock_census::CensusMutex held_mu{"held_mu"};' not in replay:
        fail("vk_replay.cpp: held_mu is not counted")
    srw = block(memory, "struct SrwMutex {")
    if 'lock_census::lock(raw, owner, "pools_mu");' not in srw or "bool try_lock() { return TryAcquireSRWLockExclusive(l) != 0; }" not in srw or \
            not srw.index("lock_census::unlocking(owner);") < srw.index("ReleaseSRWLockExclusive(&l);"):
        fail("vk_memory.cpp SrwMutex: pools_mu is not tried first and counted, or its holder is not cleared before the release")
    if 'static lock_census::CensusMutex sync_mu{"sync_mu"};' not in memory or "std::lock_guard sync_lk(sync_mu);" not in memory:
        fail("vk_memory.cpp: sync_mu is not counted")
    if 'lock_census::CensusMutex cap_mu{"cap_mu"};' not in memory:
        fail("vk_memory.cpp: cap_mu is not counted")
    if "lock_census::g_thread_name = [](char* out, size_t cap) {" not in replay or "GetThreadDescription(GetCurrentThread(), &w)" not in replay:
        fail("vk_replay.cpp no longer gives the census the threads' descriptions: every waiter and holder would be a number")
    if "#include <windows.h>" in (VK / "lock_census.h").read_text(encoding="utf-8"):
        fail("lock_census.h includes windows.h: vk_recorder.h, which includes it, is built without")
    if 'occ::knob_names(lab_ab::knobs[i].name, "lockcensus")' not in replay or 'lock_census::phase_on.store(lab_ab::on("lockcensus")' not in replay:
        fail("vk_replay.cpp: the lab's knob no longer sets the census's phases")
    header = (VK / "lock_census.h").read_text(encoding="utf-8")
    lock = block(header, "inline void lock(M& m, std::atomic<const Slot*>& owner, const char* name) {")
    off = lock.index("if (!counting()) {")
    if not off < lock.index("m.lock();") < lock.index("return;") < lock.index("if (m.try_lock()) {"):
        fail("lock_census.h: with the census off a lock is not taken by its own lock() alone, before anything else")
    if "| `RX_VK_LOCK_CENSUS=1` |" not in dev:
        fail("docs/development.md: RX_VK_LOCK_CENSUS is not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    try:
        recorder = (VK / "vk_recorder.h").read_text(encoding="utf-8")
        replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
        memory = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
        read_sources(recorder, replay, memory, (ROOT / "docs/development.md").read_text(encoding="utf-8"))
        source = FIXTURE.replace("/* DRAINING */", block(recorder, "struct DrainingMutex {")) \
            .replace("/* ORDER */", block(replay, "struct OrderMutex {")) \
            .replace("/* ORDER_UNLOCK */", block(replay, "void OrderMutex::unlock() {"))
    except (ValueError, OSError) as e:
        fail("a text this test reads is not there (%s)" % e)
    env = {k: v for k, v in os.environ.items() if k != "RX_VK_LOCK_CENSUS"}
    with tempfile.TemporaryDirectory(prefix="lock-census-") as tmp:
        src, exe = Path(tmp) / "census.cpp", Path(tmp) / "census.exe"
        src.write_text(source, encoding="utf-8")
        built = subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                                "-pthread", "-I" + str(VK), str(src), "-o", str(exe)], capture_output=True, text=True)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        for case, switch in (("on", "1"), ("on", "2"), ("off", None), ("off", "0"), ("phase", "1")):
            case_env = dict(env) if switch is None else dict(env, RX_VK_LOCK_CENSUS=switch)
            try:
                done = subprocess.run([str(exe), case], env=case_env, capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                fail("%s, RX_VK_LOCK_CENSUS %s: no end in 180 s (a lock never let go)" % (case, switch))
            if done.returncode or "PASS " + case not in done.stdout:
                print(done.stdout[-3000:] + done.stderr[-1000:])
                fail("%s, RX_VK_LOCK_CENSUS %s" % (case, "not set" if switch is None else switch))
            print("PASS %s (RX_VK_LOCK_CENSUS %s)" % (case, "not set" if switch is None else switch))
    print("PASS: a wait for a held lock is counted against its holder for the time waited, a free lock reads no clock, and off, nothing is counted")


if __name__ == "__main__":
    main()
