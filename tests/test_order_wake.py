"""The order thread woken when the CPU signals an event while a queue is stopped at a wait (gpu/vk/vk_replay.cpp
order_wake_on, sync_watch, event_signal_queued, the hold loop of wait; no game, no GPU).

(Triforce, 11-22, the performance audit's SYNC-59, after Source B's.) A queue stopped at a wait goes on when a submit
finds the wait met. A signal of the CPU's wakes no one: the stop waits for the order thread's next Sleep(1), or for a
game thread's wait that yields up to 3 ms and then forces it. RX_VK_ORDER_WAKE=1 (off unless set; the lab knob
orderwake): the order thread waits on an auto-reset event, 1 ms at most, that the signal sets.

This cuts order_wake_on, sync_watch (its endless loop bounded) and the signal's part of event_signal_queued out of the
source and runs them over stand-ins, once with the switch unset and once with RX_VK_ORDER_WAKE=1:
  - unset: the order thread sleeps 1 ms a turn and never waits on the event; a signal sets nothing;
  - on: it waits on the event, 1 ms at most, and never sleeps; a signal sets the event exactly when a queue is stopped,
    after the signal is queued and marked, holding no lock (ev_cpu_mu is free at the SetEvent);
  - either way the order thread makes the same looks, in the same turns, from the same stopped queues (burst_begin,
    schedule, burst_end, update_blocked, and the forced drain past hold_ms): the script's decisions print the same;
  - on, a turn the event woke counts as a look, and as a resume when it let work on.

And reads the source: the hold loop of wait lets the met waits on inside its sync_order_mu block when a signal is
pending and the switch is on, with the four calls sync_settle makes, before it asks what is left; the order line counts
the wakes; the switches table has the row.

    python -I -B tests/test_order_wake.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    check(text.count(marker) == 1, "vk_replay.cpp does not have once: " + marker)
    start = text.index(marker)
    end = text.index("{", start + len(marker) - 1) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>
#include <utility>
#include <vector>
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)

// ---- stand-ins ----
typedef void* HANDLE;
#define FALSE 0
#define WAIT_OBJECT_0 0u
#define WAIT_TIMEOUT 258u
static int the_thread;
static HANDLE GetCurrentThread() { return &the_thread; }
static void SetThreadDescription(HANDLE, const wchar_t*) {}
static int the_event, events_made = 0;
static HANDLE CreateEventA(void*, int manual, int initial, const char*) {
    CHECK(!manual && !initial);   // (auto-reset, not signalled)
    events_made++;
    return &the_event;
}
static bool event_set = false;
static int sleeps = 0, event_waits = 0, sets = 0, sets_locked = 0, sets_before_store = 0;
static std::string trace;   // (what the order thread did, turn by turn)
static void Sleep(unsigned ms) { CHECK(ms == 1); sleeps++; }
static unsigned WaitForSingleObject(HANDLE h, unsigned ms) {
    CHECK(h == &the_event && ms == 1);
    event_waits++;
    const bool was = event_set;
    event_set = false;   // (auto-reset)
    return was ? WAIT_OBJECT_0 : WAIT_TIMEOUT;
}
namespace lab_ab { bool on(const char*) { return false; } }
static void logf(const char*, ...) {}
static bool async_on() { return false; }
// (a lock that can say whether it is held, asked from the thread that may hold it)
struct Mu {
    bool held = false;
    void lock() { held = true; }
    void unlock() { held = false; }
    bool try_lock() { return held ? false : (held = true); }
};
Mu ev_cpu_mu;
std::vector<std::pair<uint64_t, uint32_t>> ev_cpu_pending;
std::atomic<bool> ev_cpu_any{false};
std::atomic<uint64_t> ev_cpu_signals{0};   // ((Triforce, 11-22, SYNC-29) the signal's part counts it for the reads' gate
static int SetEvent(HANDLE h) {
    CHECK(h == &the_event);
    sets++, event_set = true;
    if (!ev_cpu_mu.try_lock()) sets_locked++;   // (the signalling thread holds no lock at the wake)
    else ev_cpu_mu.unlock();
    if (!ev_cpu_any.load() || ev_cpu_pending.empty()) sets_before_store++;
    return 1;
}
// (the order's state: the script says, turn by turn, how many queues are stopped and whether their wait is met)
std::atomic<int> blocked_n{0};
Mu sync_order_mu;
std::chrono::steady_clock::time_point blocked_since;
int64_t st_resumed = 0, st_wake_looks = 0, st_wake_resumes = 0;
std::atomic<int64_t> st_wake_sets{0};
std::atomic<HANDLE> order_wake_event{nullptr};
static bool met = false, stopped_long = false;
static int hold_ms() { return stopped_long ? -1 : 1000000; }   // (past the hold or far from it, whatever the clock says)
static void burst_begin(uint64_t v) { CHECK(v == 0); trace += 'b'; }
static void schedule() {
    trace += 's';
    if (met && blocked_n.load()) st_resumed++, blocked_n = 0, trace += '+';
}
static void burst_end() { trace += 'e'; }
static void update_blocked() { trace += 'u'; }
static void drain(int why) { CHECK(why == 3); trace += 'D'; blocked_n = 0; }
static int turns = 0, turn_now = 0;
static void script(int turn);

@@ORDER_WAKE_ON@@
@@SYNC_WATCH@@
void signal_part(uint64_t gpu, uint32_t value) {
@@SIGNAL@@
}

static uint64_t rnd_state = 0x6A09E667F3BCC909ull;
static uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}
static int signals = 0, signals_while_stopped = 0;
// before each turn of the order thread: the game's threads stop queues, signal events, hold the order's lock
static bool lock_held = false;
static void script(int turn) {
    trace += '|';
    if (lock_held) sync_order_mu.unlock(), lock_held = false;
    const uint64_t r = rnd();
    if (!blocked_n.load() && r % 3 == 0) blocked_n = 1 + (int)(r >> 8) % 2;   // (a queue stops at a wait)
    met = (r >> 16) % 3 == 0, stopped_long = (r >> 24) % 11 == 0;
    if ((r >> 32) % 2 == 0) {   // (the CPU signals an event)
        signals++, signals_while_stopped += blocked_n.load() != 0;
        signal_part(0x1000 + (uint64_t)turn, (uint32_t)turn);
        met = met || (r >> 40) % 2 == 0;
    }
    if ((r >> 48) % 13 == 0) sync_order_mu.lock(), lock_held = true;   // (a submit holds the order: the thread looks next turn)
}

int main(int argc, char** argv) {
    const bool on = argc > 1 && std::string(argv[1]) == "on";
    turns = 20000;
    CHECK(order_wake_on() == on);
    sync_watch();
    CHECK(turn_now == turns && events_made == 1 && order_wake_event.load() == &the_event);
    CHECK((int)ev_cpu_pending.size() == signals && ev_cpu_any.load());   // (every signal queued and marked, on or off)
    CHECK((int)ev_cpu_signals.load() == signals);                        // ((Triforce, 11-22, SYNC-29) and counted, on or off)
    if (on) {
        CHECK(sleeps == 0 && event_waits == turns);
        CHECK(sets == signals_while_stopped && sets > 100 && st_wake_sets.load() == sets);   // (set exactly while a queue is stopped)
        CHECK(sets_locked == 0 && sets_before_store == 0);
        CHECK(st_wake_looks > 0 && st_wake_resumes > 0 && st_wake_resumes <= st_wake_looks && st_wake_looks <= sets);
    } else {
        CHECK(sleeps == turns && event_waits == 0 && sets == 0 && st_wake_sets.load() == 0 && st_wake_looks == 0 && st_wake_resumes == 0);
    }
    uint64_t h = 1469598103934665603ull;
    for (char c : trace) h = (h ^ (uint8_t)c) * 1099511628211ull;
    std::printf("decisions %zu %016llx resumed %lld\n", trace.size(), (unsigned long long)h, (long long)st_resumed);
    std::printf("%s: %d turns, %d sleeps, %d waits on the event, %d signals (%d while a queue was stopped), %d sets, %lld looks after a wake, %lld let work on\n",
                on ? "on" : "unset", turns, sleeps, event_waits, signals, signals_while_stopped, sets, (long long)st_wake_looks, (long long)st_wake_resumes);
    return fails != 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    rep = (VK / "vk_replay.cpp").read_text(encoding="utf-8")

    on = block(rep, "bool order_wake_on() {")
    check('getenv("RX_VK_ORDER_WAKE")' in on and "static const bool env" in on and "e && atoi(e) != 0" in on and
          'return env || lab_ab::on("orderwake");' in on, "RX_VK_ORDER_WAKE is not read once, off unless set, with the lab knob orderwake")
    watch = block(rep, "void sync_watch() {")
    order = [watch.find(s) for s in (
        "const HANDLE wake = CreateEventA(nullptr, FALSE, FALSE, nullptr);", "order_wake_event.store(wake, std::memory_order_release);",
        "for (;;) {", "if (wake && order_wake_on()) woken = WaitForSingleObject(wake, 1) == WAIT_OBJECT_0;", "else Sleep(1);",
        "if (!blocked_n.load()) continue;", "std::unique_lock lk(sync_order_mu, std::try_to_lock);", "if (!lk) continue;",
        "burst_begin(0);", "schedule();", "burst_end();", "update_blocked();",
        "if (woken) st_wake_looks++, st_wake_resumes += st_resumed != resumed0;", "if (blocked_n.load() && held > hold_ms()) {", "drain(3);")]
    check(min(order) >= 0 and order == sorted(order), "sync_watch: the event, the wait or the sleep, the look and the forced drain are not there in that order")
    # (the part of event_signal_queued without the replay thread: its first statement, a block)
    signal = block(rep, "void event_signal_queued(uint64_t gpu, uint32_t value) {\n    if (!async_on()) {").split("\n", 1)[1]
    order = [signal.find(s) for s in (
        "ev_cpu_pending.emplace_back(gpu, value);", "ev_cpu_any.store(true, std::memory_order_release);\n        }",
        "if (blocked_n.load(std::memory_order_relaxed) && order_wake_on())", "SetEvent(wake), st_wake_sets.fetch_add(1, std::memory_order_relaxed);",
        "return;")]
    check(min(order) >= 0 and order == sorted(order), "event_signal_queued does not wake the order thread after the signal is queued and marked, its lock let go")
    for lock in ("sync_order_mu", "replay_mu", "schedule(", "burst_begin(", "drain("):
        check(lock not in signal, "event_signal_queued's wake takes the order's lock or replays on the signalling thread (%s)" % lock)
    check(rep.count("SetEvent(wake)") == 1 and "SetEvent(wake)" in signal, "the wake is set elsewhere than in event_signal_queued")

    # the hold loop of a game thread's wait: the met waits go on inside its sync_order_mu block, none forced
    look = block(rep, "if (ev_cpu_any.load(std::memory_order_acquire) && order_wake_on()) {")
    order = [look.find(s) for s in ("burst_begin(0);", "schedule();", "burst_end();", "update_blocked();",
                                    "st_wake_looks++, st_wake_resumes += st_resumed != resumed0;")]
    check(min(order) >= 0 and order == sorted(order) and "drain(" not in look, "the hold loop's look is not sync_settle's four calls, or forces a wait")
    at = rep.index(look)
    before, after = rep[max(0, at - 420):at], rep[at + len(look):at + len(look) + 200]
    check("std::lock_guard lk(sync_order_mu);" in before and before.rindex("std::lock_guard lk(sync_order_mu);") > before.rfind("}"),
          "the hold loop's look is not inside its sync_order_mu block")
    check(after.lstrip().startswith("needs = oldest_unfinished() <= f;"), "the hold loop no longer asks what is left right after its look")
    settle = block(rep, "void sync_settle() {")
    for s in ("burst_begin(0);", "schedule();", "burst_end();", "update_blocked();"):
        check(s in settle, "sync_settle changed: the hold loop's look copies it")
    stats = block(rep, "void log_order_stats() {")
    check("st_wake_sets.load(std::memory_order_relaxed)" in stats and "st_wake_resumes" in stats, "the order line does not count the wakes")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_ORDER_WAKE=1`" in dev and "`orderwake`" in dev, "docs/development.md: RX_VK_ORDER_WAKE=1 is not in the switches table")

    loop = "    for (;;) {\n"
    check(watch.count(loop) == 1, "sync_watch has no single endless loop")
    bounded = watch.replace(loop, "    for (turn_now = 0; turn_now < turns; turn_now++) {\n        script(turn_now);\n")
    body = signal   # (the non-async part of event_signal_queued, as a function's body)
    src_text = FIXTURE.replace("@@ORDER_WAKE_ON@@", on).replace("@@SYNC_WATCH@@", bounded).replace("@@SIGNAL@@", body)
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="order-wake-") as tmp:
        src, exe = Path(tmp) / "wake.cpp", Path(tmp) / "wake.exe"
        src.write_text(src_text, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Wno-unused-function", "-Wno-unused-parameter", str(src), "-o", str(exe)], check=True)
        outs = {}
        for name, env in (("unset", base_env), ("on", dict(base_env, RX_VK_ORDER_WAKE="1")), ("0", dict(base_env, RX_VK_ORDER_WAKE="0"))):
            r = subprocess.run([str(exe), "on" if name == "on" else "off"], env=env, capture_output=True, text=True, timeout=120)
            check(r.returncode == 0, "RX_VK_ORDER_WAKE %s:\n%s" % (name, r.stdout + r.stderr))
            outs[name] = r.stdout.splitlines()
            print(outs[name][-1])
        check(outs["unset"][0] == outs["0"][0], "RX_VK_ORDER_WAKE=0 is not the same as unset")
        check(outs["unset"][0] == outs["on"][0], "with the wake the order thread's looks are not the ones it made without: %s / %s"
              % (outs["unset"][0], outs["on"][0]))
    print("PASS: a CPU signal wakes the order thread while a queue is stopped, with no lock held; unset it sleeps as before, and "
          "its looks are the same either way")


if __name__ == "__main__":
    main()
