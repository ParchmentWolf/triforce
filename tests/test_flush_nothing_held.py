"""Flushes with nothing held skip the queue's lock (gpu/vk/vk_replay.cpp pend_held, RX_VK_PEND_HELD).

queue_flush_for and queue_flush_poll took dev.present_mu to find nothing held, at every fence wait and progress poll (with
batching off, always), behind a present or a late page's fix waiting on the GPU. pend_held is raised under the lock when a
submit is held and lowered when the batch goes out; both flushes look at it first. A held submit's recording is registered
for the waiters only after it is in pend with the flag raised, so a waiter that finds the registration finds it held (or
already sent) and flushes it.

Checked, compiled (pend_held, pend_held_on, queue_flush_for and queue_flush_poll cut out of vk_replay.cpp unchanged, with a
counting mutex for dev.present_mu): nothing held, no lock; held, the lock and the flush; RX_VK_PEND_HELD=0 and the lab knob
nopendheld, the lock every time; four waiters against a submitter that holds, raises and then registers: every waiter's
flush after it found a registration leaves that recording sent. In the source: the lowering after pend.cbs.clear(); in
submit_recording the registration before the lock only when not registered late, after the push and the raise when held,
before the direct submit otherwise; wait_recorded's counter read before its flush; vk_timeline_wait's second flush once its
lookup finds the recording; the docs row.

    python -I -B tests/test_flush_nothing_held.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def fail(message):
    raise SystemExit("FAIL: " + message)


def in_order(text, parts, where):
    at = 0
    for part in parts:
        found = text.find(part, at)
        if found < 0:
            fail("%s: %r is missing, or not after the part before it" % (where, part))
        at = found + len(part)


FIXTURE = r"""
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>

namespace lab_ab {
bool knob = false;
bool on(const char* name) { return knob && !strcmp(name, "nopendheld"); }
}
struct CountingMutex {
    std::mutex m;
    std::atomic<long> locks{0};
    void lock() { locks.fetch_add(1); m.lock(); }
    void unlock() { m.unlock(); }
};
struct { CountingMutex present_mu; } dev;
struct { std::vector<int> cbs; } pend;
int flush_reason;
enum { FR_OTHER, FR_POLL, FR_WAIT, FR_VALUE };
std::chrono::steady_clock::time_point pend_since;

DECL

uint64_t held_seq;                    // (the newest recording in pend; dev.present_mu)
std::atomic<uint64_t> sent_seq{0};    // (the newest one sent)
long flushes;
void queue_flush_locked() {   // (the real one's end: the batch out, then the flag lowered)
    if (pend.cbs.empty()) return;
    flushes++;
    sent_seq.store(held_seq, std::memory_order_relaxed);
    pend.cbs.clear();
    pend_held.store(false, std::memory_order_release);
}
void hold(uint64_t seq) {   // (submit_recording's held path)
    std::lock_guard lk(dev.present_mu);
    pend.cbs.push_back(1);
    held_seq = seq;
    pend_held.store(true, std::memory_order_release);
}

FLUSH

int main(int argc, char** argv) {
    const char* mode = argc > 1 ? argv[1] : "";
    int bad = 0;
    auto check = [&](bool ok, const char* what) { if (!ok) { std::printf("FAIL %s\n", what); bad++; } };
    if (!strcmp(mode, "basic") || !strcmp(mode, "off") || !strcmp(mode, "knob")) {
        lab_ab::knob = !strcmp(mode, "knob");
        const bool skip = !strcmp(mode, "basic");
        const long l0 = dev.present_mu.locks;
        for (int i = 0; i < 1000; i++) queue_flush_for(FR_WAIT), queue_flush_poll();
        check(skip ? dev.present_mu.locks == l0 : dev.present_mu.locks == l0 + 2000, "nothing held: the lock as the mode says");
        check(flushes == 0, "nothing held: no flush");
        hold(7);
        const long l1 = dev.present_mu.locks;
        queue_flush_for(FR_WAIT);
        check(dev.present_mu.locks == l1 + 1 && flushes == 1 && sent_seq == 7 && !pend_held.load(), "held: the lock and the flush");
        hold(8);
        queue_flush_poll();
        check(flushes == 2 && sent_seq == 8 && pend.cbs.empty(), "held: the poll flushes (RX_VK_BATCH_POLL_US=0)");
        const long l2 = dev.present_mu.locks;
        queue_flush_for(FR_WAIT), queue_flush_poll();
        check(skip ? dev.present_mu.locks == l2 : dev.present_mu.locks == l2 + 2, "after the flush: nothing held again");
        std::printf("%s: %ld locks, %ld flushes\n", mode, (long)dev.present_mu.locks, flushes);
        return bad;
    }
    if (!strcmp(mode, "race")) {
        std::mutex map_mu;   // (rec_map_mu)
        uint64_t registered = 0;
        std::atomic<bool> stop{false};
        std::atomic<long> late{0}, looks{0};
        std::thread submitter([&] {
            for (uint64_t s = 1; s <= 200000; s++) {
                {
                    std::lock_guard lk(dev.present_mu);
                    pend.cbs.push_back(1);
                    held_seq = s;
                    pend_held.store(true, std::memory_order_release);
                    std::lock_guard mk(map_mu);   // (registered after the raise, under the lock)
                    registered = s;
                }
                if (s % 64 == 0) { std::lock_guard lk(dev.present_mu); queue_flush_locked(); }   // (the cap)
            }
            stop = true;
        });
        std::vector<std::thread> waiters;
        for (int w = 0; w < 4; w++)
            waiters.emplace_back([&] {
                while (!stop) {
                    uint64_t s;
                    {
                        std::lock_guard mk(map_mu);
                        s = registered;
                    }
                    if (!s) continue;
                    queue_flush_for(FR_WAIT);
                    looks++;
                    if (sent_seq.load(std::memory_order_relaxed) < s) late++;
                }
            });
        submitter.join();
        for (auto& t : waiters) t.join();
        std::printf("race: %ld looks, %ld left a found recording held\n", (long)looks, (long)late);
        return late != 0;
    }
    return 1;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    src = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    if "std::atomic<bool> pend_held{false};" not in src:
        fail("vk_replay.cpp has no pend_held")
    decl = src[src.index("std::atomic<bool> pend_held{false};"):]
    decl = decl[:decl.index(block(decl, "bool pend_held_on() {")) + len(block(decl, "bool pend_held_on() {"))]
    flush = block(src, "void queue_flush_for(int why) {") + "\n" + block(src, "void queue_flush_poll() {")
    for name in ("queue_flush_for", "queue_flush_poll"):
        body = block(src, "void %s(" % name)
        if body.index("pend_held.load(std::memory_order_acquire)") > body.index("std::lock_guard lk(dev.present_mu);"):
            fail("%s: the look is not before the lock" % name)
    locked = block(src, "void queue_flush_locked() {")
    in_order(locked, ["pend.cbs.clear()", "pend_held.store(false, std::memory_order_release);"], "queue_flush_locked")
    sub = block(src, "void submit_recording(Recording& r, bool signal_value = true, uint64_t signal_at = 0, bool part = false) {")
    in_order(sub, ["seq = ++rec_seq;", "const auto register_recording = [&] {", "std::lock_guard mk(rec_map_mu);",
                   "fin_rec.submitted(rec_open_values, seq, !part);", "};",
                   "const bool batching = batch_on(), registered_late = batching && pend_held_on();",
                   "if (!registered_late) register_recording();", "std::lock_guard lk(dev.present_mu);", "if (batch_on()) {",
                   "for (uint32_t i = 0; i < n; i++) pend.cbs.push_back(cb[i]);", "pend.recs++;",
                   "pend_held.store(true, std::memory_order_release);", "if (registered_late) register_recording();",
                   "queue_flush_locked();", "return;", "if (registered_late) register_recording();",
                   "vkQueueSubmit2(dev.queue, 1, &si, r.fence);"], "submit_recording")
    if sub.count("register_recording();") != 3:
        fail("submit_recording: the registration is made somewhere this test does not know")
    wr = block(src, "bool wait_recorded(uint64_t f, uint64_t timeout_ns, int* ok) {")
    in_order(wr, ["seq = it->second;", "pend_held_on() && vkGetSemaphoreCounterValue(dev.device, rec_timeline, &rec_done) == VK_SUCCESS && rec_done >= seq",
                  "*ok = 1;", "return true;", "queue_flush_for(FR_WAIT);"], "wait_recorded")
    tw = block(src, "void vk_timeline_wait(uint64_t v) {")
    in_order(tw, ["queue_flush_for(FR_VALUE);", "seq = fin_rec.of(v);", "if (seq && pend_held_on()) queue_flush_for(FR_VALUE);"],
             "vk_timeline_wait")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if "`RX_VK_PEND_HELD=0`" not in docs:
        fail("docs/development.md: no RX_VK_PEND_HELD row")
    print("ok   the source: the look before the lock, the lowering after the clear, the registration after the raise, the "
          "counter read, the second flush")
    with tempfile.TemporaryDirectory(prefix="flush-nothing-held-") as tmp:
        c, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        c.write_text(FIXTURE.replace("DECL", decl).replace("FLUSH", flush), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-pthread", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        for mode, env in (("basic", {}), ("off", {"RX_VK_PEND_HELD": "0"}), ("knob", {}), ("race", {})):
            e = dict(os.environ, RX_VK_BATCH_POLL_US="0")
            e.pop("RX_VK_PEND_HELD", None)
            e.update(env)
            r = subprocess.run([str(exe), mode], capture_output=True, text=True, env=e, timeout=300)
            print(("ok   " if r.returncode == 0 else "FAIL ") + r.stdout.strip().replace("\n", "; "))
            if r.returncode:
                fail("the fixture's %s mode" % mode)
    print("PASS: flushes with nothing held skip the queue's lock")


if __name__ == "__main__":
    main()
