"""A read looks at the stopped queues only after a new CPU signal (gpu/vk/settle_gate.h, vk_replay.cpp; no game, no GPU).

(Triforce, 11-22, the performance audit's SYNC-29, after Source A's.) A CPU read that lets the stopped queues whose waits are
met go on takes the order's lock whenever a queue is stopped: the readback's look (RX_VK_RB_SETTLE, off) and the two looks made
for a range a texture may be in. RX_VK_SETTLE_GATE=1 gates the first, =2 the others too; unset, every look as before.

Compiles a driver against the header and
- checks the switch's text, the levels the lab knobs raise, which site is gated at which level, and the decision's table;
- runs a model of the order: three queues that stop at waits on four events, holders of the order's lock that replay signals
  of the stream, look (schedule) and end their burst before they let the lock go, the CPU's signals (queued, then counted, as
  two steps that fall anywhere between a holder's steps), a holder that only takes the pending signals in without looking
  (the submit's gate wait), and plain stores into an event's memory. 400,000 random steps, and at every quiet point (no
  signal half made) a read asks the header's decide(): whenever the gate skips the look, a look would have let nothing on.
  With no gate (level 0) nothing is ever skipped;
- runs the same model with each of three mistakes and requires that it then FINDS a skipped look that would have let work
  on: the signal counted before it is queued; the count published as it is at the look's end; a wait on an event read from
  memory not marked.
And reads vk_replay.cpp: the signal counted after it is queued; the count noted in burst_begin and published in burst_end
after finish_recording; update_blocked marks a wait read from memory; the three sites go through sync_settle_at with their
site, which asks the header and counts; the holders the model stands on (submit_job looks and ends its burst, submit_q
updates after it); the switches table.

    python -I -B tests/test_settle_gate.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "settle_gate.h"
#include <cstdio>
#include <vector>

namespace sg = mkwvk::settle_gate;
static int checks, fails;
#define CHECK(what, cond) do { checks++; if (!(cond)) fails++, printf("FAIL %s (line %d)\n", what, __LINE__); } while (0)

enum Mistake { kNone, kCountFirst, kPublishAtEnd, kNoMemoryMark };

struct Model {
    Mistake mistake = kNone;
    uint64_t rng = 0x9E3779B97F4A7C15ull;
    uint64_t rnd(uint64_t n) { rng ^= rng << 13, rng ^= rng >> 7, rng ^= rng << 17; return rng % n; }
    // the events: a value the replay knows (set) or the game's memory
    // (the first two are signalled, by the stream and the CPU; the last two only ever stored into: read from memory for good)
    static constexpr int kEvents = 4, kSignalled = 2, kQueues = 3;
    uint32_t value[kEvents] = {}, memory[kEvents] = {};
    bool set[kEvents] = {};
    std::vector<std::pair<int, uint32_t>> pending;   // (the CPU's signals queued)
    uint64_t signals = 0, settled = 0, burst_signals = 0;
    bool wait_in_memory = false;
    struct Queue { bool waiting = false; int event = 0; uint32_t want = 0; } q[kQueues];
    // a CPU signal half made: 0 none; else its event + 1
    int flight = 0;
    uint32_t flight_value = 0;
    int64_t skips = 0, looks = 0, skipped_met = 0, quiet_reads = 0, resumed = 0;

    uint32_t have(int e) const { return set[e] ? value[e] : memory[e]; }
    bool met(const Queue& w) const { return w.waiting && (int32_t)(have(w.event) - w.want) >= 0; }
    void apply() {   // (ev_cpu_apply)
        for (const auto& s : pending) value[s.first] = s.second, set[s.first] = true;
        pending.clear();
    }
    void signal_step() {   // (event_signal_queued, a step at a time)
        if (!flight) {
            if (rnd(3)) return;
            flight = (int)rnd(kSignalled) + 1, flight_value = have(flight - 1) + 1 + (uint32_t)rnd(2);
            if (mistake == kCountFirst) signals++;
            else pending.emplace_back(flight - 1, flight_value);
            return;
        }
        if (mistake == kCountFirst) pending.emplace_back(flight - 1, flight_value);
        else signals++;
        flight = 0;
    }
    /// None, one or two steps of the CPU's signals: another thread's, anywhere between a holder's steps
    void signal_steps() {
        for (uint64_t n = rnd(3); n; n--) signal_step();
    }
    void schedule() {
        apply();
        for (bool moved = true; moved;) {
            moved = false;
            for (Queue& w : q)
                if (met(w)) {
                    w.waiting = false, moved = true, resumed++;
                    if (rnd(2)) stream_signal();   // (what it replays may signal and let another on)
                }
        }
    }
    void stream_signal() {
        const int e = (int)rnd(kSignalled);
        value[e] = have(e) + (uint32_t)rnd(3), set[e] = true;
    }
    void update_blocked() {
        bool in_memory = false;
        for (const Queue& w : q)
            if (w.waiting && !set[w.event]) in_memory = true;
        wait_in_memory = mistake == kNoMemoryMark ? false : in_memory;
    }
    bool blocked() const { return q[0].waiting || q[1].waiting || q[2].waiting; }
    /// A holder of the order's lock: its burst begins, it replays (signals of the stream, a wait it stops at), looks, ends its
    /// burst and updates. The CPU's signal steps fall between its steps
    void section(bool replays) {
        burst_signals = signals;                         // (burst_begin)
        signal_steps();
        if (replays) {
            if (rnd(2)) stream_signal();
            const int k = (int)rnd(kQueues);
            if (!q[k].waiting && rnd(2)) {               // (NOP_WAIT_EVENT: the pending signals taken in, then the wait)
                apply();
                Queue w{true, rnd(8) ? (int)rnd(kSignalled) : kSignalled + (int)rnd(kEvents - kSignalled), 0};   // (one in eight on memory)
                w.want = have(w.event) + 1 + (uint32_t)rnd(2);
                if (!met(w)) q[k] = w;
            }
            signal_steps();
        }
        schedule();
        signal_steps();
        settled = mistake == kPublishAtEnd ? signals : burst_signals;   // (burst_end, after finish_recording)
        update_blocked();
    }
    /// A read at a quiet point: the header's decision at this level; a skipped look that would have let work on is the fault
    void read(int level) {
        const int what = sg::decide(level, sg::kReadback, blocked(), signals, settled, wait_in_memory);
        if (what == sg::kNothing) return;
        if (what == sg::kSkip) {
            skips++;
            if (!flight) {
                quiet_reads++;
                Model after = *this;
                after.apply();
                for (const Queue& w : after.q) skipped_met += after.met(w);
            }
            return;
        }
        looks++;
        section(false);
    }
    void run(int level, int steps) {
        for (int i = 0; i < steps; i++) {
            switch (rnd(8)) {
            case 0: case 1: section(true); break;
            case 2: signal_step(); break;
            case 3: apply(); break;                       // (the submit's gate wait: signals taken in, no look, nothing published)
            case 4: memory[rnd(kEvents)] += (uint32_t)rnd(3); break;   // (a plain store into an event's memory)
            default: read(level); break;
            }
        }
    }
};

int main() {
    // the switch and the levels
    CHECK("unset", sg::level(nullptr) == 0);
    CHECK("empty", sg::level("") == 0);
    CHECK("0", sg::level("0") == 0);
    CHECK("1", sg::level("1") == 1);
    CHECK("2", sg::level("2") == 2);
    CHECK("3", sg::level("3") == 0);
    CHECK("a word", sg::level("on") == 0);
    CHECK("10", sg::level("10") == 0);
    CHECK("no knob", sg::level_now(0, false, false) == 0 && sg::level_now(1, false, false) == 1 && sg::level_now(2, false, false) == 2);
    CHECK("settlegate", sg::level_now(0, true, false) == 1 && sg::level_now(2, true, false) == 2);
    CHECK("texgate", sg::level_now(0, false, true) == 2 && sg::level_now(1, true, true) == 2);
    CHECK("level 0 gates nothing", !sg::gated(0, sg::kReadback) && !sg::gated(0, sg::kTexture));
    CHECK("level 1 gates the readback's look", sg::gated(1, sg::kReadback) && !sg::gated(1, sg::kTexture));
    CHECK("level 2 gates both", sg::gated(2, sg::kReadback) && sg::gated(2, sg::kTexture));
    // the decision: nothing stopped, nothing to do at any level; ungated, a look whenever a queue is stopped
    for (int level = 0; level <= 2; level++)
        for (int site = 0; site < sg::kSites; site++)
            for (int bits = 0; bits < 8; bits++) {
                const bool blocked = bits & 1, fresh = bits & 2, mem = bits & 4;
                const int d = sg::decide(level, site, blocked, fresh ? 8 : 7, 7, mem);
                const int want = !blocked ? sg::kNothing : (sg::gated(level, site) && !fresh && !mem) ? sg::kSkip : sg::kLook;
                CHECK("the decision's table", d == want);
            }
    CHECK("a count behind as well as ahead is a new signal", sg::look(true, 3, 9, false) && !sg::look(true, 9, 9, false) && !sg::look(false, 3, 9, true));

    // the model
    {
        Model m;
        m.run(1, 400000);
        printf("gate on: %lld looks, %lld skipped (%lld at a quiet point), %lld waits let on\n", (long long)m.looks, (long long)m.skips,
               (long long)m.quiet_reads, (long long)m.resumed);
        CHECK("the gate skipped a look that would have let work on", m.skipped_met == 0);
        CHECK("the model skipped looks and let work on", m.quiet_reads > 5000 && m.looks > 5000 && m.resumed > 5000);
    }
    {
        Model m;
        m.run(0, 100000);
        CHECK("no gate: nothing skipped", m.skips == 0 && m.looks > 1000);
    }
    static const struct { Mistake mistake; const char* what; } kMistakes[] = {
        {kCountFirst, "a signal counted before it is queued was not found"},
        {kPublishAtEnd, "the count published as it is at the look's end was not found"},
        {kNoMemoryMark, "a wait on an event read from memory, not marked, was not found"},
    };
    for (const auto& k : kMistakes) {
        Model m;
        m.mistake = k.mistake;
        m.run(1, 400000);
        CHECK(k.what, m.skipped_met > 0);
    }
    if (fails) printf("settle gate: FAILED (%d of %d checks)\n", fails, checks);
    else printf("settle gate: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def function(text, head):
    at = text.index(head)
    return text[at:text.index("\n}\n", at)]


def check_source():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    # every CPU signal is counted, after it is queued (and nothing else queues one)
    check(replay.count("ev_cpu_pending.emplace_back(") == 1 and replay.count("ev_cpu_signals.fetch_add(") == 1,
          "a CPU signal is queued somewhere it is not counted, or counted twice")
    sig = function(replay, "void event_signal_queued(uint64_t gpu, uint32_t value) {")
    queued = sig.index("ev_cpu_pending.emplace_back(gpu, value);")
    counted = sig.index("ev_cpu_signals.fetch_add(1, std::memory_order_release);")
    check(queued < sig.index("ev_cpu_any.store(true, std::memory_order_release);") < counted < sig.index("return;"),
          "event_signal_queued counts the signal before it is queued, or not on the submitting thread's path")
    # the look notes the count at its start and publishes it after its recording is finished
    begin = function(replay, "void burst_begin(uint64_t value) {")
    check("burst_signals = ev_cpu_signals.load(std::memory_order_acquire);" in begin, "burst_begin does not note the signals' count")
    end = function(replay, "void burst_end() {")
    check("ev_cpu_settled.store(burst_signals, std::memory_order_release);" in end and
          end.index("if (rec_cur) finish_recording(burst_value);") < end.index("ev_cpu_settled.store(") and
          end.index("if (!burst_open) return;") < end.index("ev_cpu_settled.store("),
          "burst_end does not publish the noted count after finish_recording")
    check(replay.count("ev_cpu_settled.store(") == 1 and "ev_cpu_settled.store(ev_cpu_signals" not in replay,
          "the settled count is published somewhere else, or as the count is at the look's end")
    upd = function(replay, "void update_blocked() {")
    check("if (q.waiting && ev_values.find(wait_at(q.p).gpu) == ev_values.end()) in_memory = true;" in upd and
          "ev_wait_in_memory.store(in_memory, std::memory_order_release);" in upd,
          "update_blocked does not mark a stopped queue that waits on an event read from guest memory")
    # the sites
    at = function(replay, "void sync_settle_at(int site) {")
    check("settle_gate::decide(settle_gate_level(), site, blocked_n.load() != 0, ev_cpu_signals.load(std::memory_order_acquire)," in at and
          "ev_cpu_settled.load(std::memory_order_acquire), ev_wait_in_memory.load(std::memory_order_acquire));" in at,
          "sync_settle_at does not ask the header with the counts and the mark")
    check(at.index("if (what == settle_gate::kNothing) return;") < at.index("if (what == settle_gate::kSkip) {") < at.index("sync_settle();") and
          "st_settle_skips[site].fetch_add(" in at and "st_settle_looks[site].fetch_add(" in at, "sync_settle_at does not look, skip and count as decided")
    lvl = function(replay, "int settle_gate_level() {")
    check('settle_gate::level(getenv("RX_VK_SETTLE_GATE"));' in lvl and
          'return settle_gate::level_now(env, lab_ab::on("settlegate"), lab_ab::on("texgate"));' in lvl,
          "RX_VK_SETTLE_GATE and its two lab knobs are not read")
    inv = function(replay, "void invalidate(uint64_t gpu, uint64_t size) {")
    check(inv.count("rb_fix(2)) sync_settle_at(settle_gate::kReadback), w = true;") == 1, "the readback's look is not the gated site, behind RX_VK_RB_SETTLE")
    check(inv.count("unforced ? sync_settle_at(settle_gate::kTexture) : wait_queue_empty();") == 2, "the two texture sites are not the gated site")
    check("sync_settle()" not in inv.replace("sync_settle() as it was", ""), "invalidate settles past the gate somewhere")
    check("st_settle_looks[settle_gate::kReadback].exchange(0)" in inv and "st_settle_looks[settle_gate::kTexture].exchange(0)" in inv,
          "the looks and skips are not in the two log lines")
    # what the model stands on: a holder that replays looks and ends its burst before it lets the lock go
    job = function(replay, "void submit_job(std::vector<uint64_t>& handles, uint64_t value, uint64_t queue) {")
    check("    schedule();   // (what it signalled may let the stopped ones on)\n    burst_end();" in job, "submit_job no longer looks and ends its burst after its replay")
    check("            submit_job(h, value, queue);\n            update_blocked();" in replay, "submit_q no longer updates the stopped queues after its job")
    settle = function(replay, "void sync_settle() {")
    check(settle.index("burst_begin(0);") < settle.index("schedule();") < settle.index("burst_end();") < settle.index("update_blocked();"),
          "sync_settle is no longer a look inside a burst")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    row = [line for line in dev.splitlines() if line.startswith("| `RX_VK_SETTLE_GATE=1`, `=2` |")]
    check(len(row) == 1 and "off by default" in row[0] and "`settlegate`" in row[0] and "`texgate`" in row[0],
          "docs/development.md: the switches table does not have RX_VK_SETTLE_GATE's row")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="settle-gate-") as tmp:
        src = Path(tmp) / "driver.cpp"
        src.write_text(DRIVER, encoding="utf-8")
        exe = Path(tmp) / "driver.exe"
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu/vk"), str(src), "-o", str(exe)],
                       check=True)
        out = subprocess.run([str(exe)], capture_output=True, text=True)
        print(out.stdout, end="")
        check(out.returncode == 0, "the header's checks or the model failed")
    print("PASS: a read looks at the stopped queues only after a new CPU signal, where RX_VK_SETTLE_GATE says so")


if __name__ == "__main__":
    main()
