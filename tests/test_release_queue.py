"""Texture and program releases queued for the replaying thread (gpu/vk/release_queue.h, vk_replay.cpp texture_released_of,
program_released_locked, releases_apply_locked; no game, no GPU).

(Triforce, 11-22, the performance audit's MEM-85, after Source B's idea.) Without the replay thread a release was held for
the replaying thread only while a queue was stopped (PR 430), and otherwise waited for sync_drain and the replay's lock on
the game's thread. RX_VK_RELEASE_QUEUE=1 (OFF unless set; lab knob relq) pushes every such release to a list the replaying
thread applies at a submission's replay start or a present with no queue stopped, and update_blocked after the stopped
work; a texture's release carries the write generation of its call. A count of the old way's waits is on in every run.

Compiles the header: the switch's text and knob; way() against the old decision over every input with the switch off, and
Queued whatever is stopped with it on; apply_now; the count's numbers, its line and its reset. Then a model: random streams
of queues stopping and going on, releases, submissions and presents, applied by the header's rule: with the switch on no
release is applied while a queue is stopped, none is left once the replaying thread has run with none stopped, and each is
applied with the generation of its call; with it off, the model's releases go the old ways (held while stopped, else at once).

And reads the source: both release entries decide by way() with the old decision's parts, the queued push under held_mu
with the call's generation and the count, the held branch as it was, the old way's sync_drain and lock timed, the job path
of the replay thread after them unchanged; releases_apply_locked asks apply_now, swaps under held_mu and applies as the
do_ functions do without taking replay_mu; run_submit and do_present call it first under replay_mu, update_blocked after
the stopped work's releases under replay_mu; texture_released_at takes the generation it is given; the switches table.

    python -I -B tests/test_release_queue.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

PROGRAM = r"""
#include "release_queue.h"
#include <cstdio>
#include <random>
#include <vector>
using namespace release_queue;
static int fails = 0;
#define CHECK(c) do { if (!(c)) { std::printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

int main() {
    CHECK(!on(nullptr, false) && on(nullptr, true) && !on("0", true) && on("1", false) && on("2", false) && !on("x", true));
    for (int q = 0; q < 2; q++)
        for (int h = 0; h < 2; h++)
            for (int s = 0; s < 2; s++)
                for (int b = 0; b < 2; b++) {
                    const Way w = way(q, h, s, b);
                    if (q) CHECK(w == Way::Queued);   // (the switch's push ignores stopped queues)
                    else CHECK(w != Way::Queued && (w == Way::Held) == held_before(h, s, b));
                }
    CHECK(!apply_now(0, 0) && apply_now(1, 0) && !apply_now(3, 1) && !apply_now(0, 2));
    {
        Waits w;
        w.note(100), w.note(Waits::kWaitNs), w.note(Waits::kWaitNs * 3), w.note_queued();
        CHECK(w.n == 3 && w.waited == 2 && w.ns == 100 + Waits::kWaitNs * 4 && w.max_ns == Waits::kWaitNs * 3 && w.queued == 1);
        CHECK(!w.due() && w.worth_a_line());
        Waits q;
        for (int i = 0; i < Waits::kEvery - 1; i++) q.note(10);
        CHECK(!q.due() && !q.worth_a_line());
        q.note_queued();
        CHECK(q.due() && q.worth_a_line());
        q.reset();
        CHECK(q.n == 0 && q.queued == 0 && q.max_ns == 0 && !q.due());
    }
    // (the model: 4 queues; a stream of stops, resumes (update_blocked), releases, submissions' starts and presents)
    std::mt19937_64 rng(85);
    for (int run = 0; run < 4000; run++) {
        const bool qon = run % 2;
        bool stopped[4] = {};
        int blocked = 0;
        uint64_t gen = 1;
        struct Rel { int id; uint64_t gen; bool stopped_at_call[4]; };
        std::vector<Rel> queued, held;
        std::vector<int> applied;
        int next_id = 0;
        auto apply = [&](std::vector<Rel>& list) {
            for (const Rel& r : list) {
                for (int k = 0; k < 4; k++) CHECK(!(r.stopped_at_call[k] && stopped[k]));   // (never before stopped work)
                applied.push_back(r.id);
            }
            list.clear();
        };
        auto replaying = [&]() {   // (run_submit's start, do_present: replay_mu held)
            if (apply_now(queued.size(), blocked)) apply(queued);
        };
        for (int step = 0; step < 200; step++) {
            const int e = (int)(rng() % 6);
            if (e == 0) {   // (a queue stops at a wait)
                const int k = (int)(rng() % 4);
                if (!stopped[k]) stopped[k] = true, blocked++;
            } else if (e == 1) {   // (a queue goes on; update_blocked)
                const int k = (int)(rng() % 4);
                if (stopped[k]) stopped[k] = false, blocked--;
                if (!blocked) {
                    apply(held);
                    if (!queued.empty()) apply(queued);   // (update_blocked's, after the held ones)
                }
            } else if (e == 2 || e == 3) {   // (a release on the game's thread)
                Rel r{next_id++, gen, {}};
                for (int k = 0; k < 4; k++) r.stopped_at_call[k] = stopped[k];
                const Way w = way(qon, true, true, blocked != 0);
                if (w == Way::Queued) queued.push_back(r);
                else if (w == Way::Held) held.push_back(r);
                else { CHECK(blocked == 0); applied.push_back(r.id); }   // (the old way: at once, nothing stopped)
                if (!qon) CHECK(queued.empty());
            } else if (e == 4) {   // (a submission's replay starts; the CPU's writes make generations)
                replaying();
                gen += 1 + rng() % 3;
            } else {
                replaying();   // (a present)
            }
        }
        // (the replaying thread with nothing stopped: nothing left)
        for (int k = 0; k < 4; k++) stopped[k] = false;
        blocked = 0;
        apply(held);
        replaying();
        CHECK(queued.empty() && held.empty() && (int)applied.size() == next_id);
    }
    // (each queued release keeps its call's generation through the list, as releases_apply_locked hands it on)
    {
        struct Q { int id; uint64_t gen; };
        std::vector<Q> list;
        for (int i = 0; i < 10; i++) list.push_back({i, 100 + (uint64_t)i * 7});
        std::vector<Q> taken;
        taken.swap(list);
        for (int i = 0; i < 10; i++) CHECK(taken[i].gen == 100 + (uint64_t)i * 7);
        CHECK(list.empty());
    }
    std::printf(fails ? "%d failed\n" : "ok\n", fails);
    return fails ? 1 : 0;
}
"""


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(text, steps, what):
    at = -1
    for s in steps:
        k = text.find(s, at + 1)
        if k < 0:
            raise SystemExit("FAIL: %s: %r is missing or out of its order" % (what, s))
        at = k


def check_source():
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    texture = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    memory = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    way = "const release_queue::Way way = release_queue::way(release_queue_on(), hold_releases(), sync_waits_on(), blocked_n.load() != 0);"
    tex = block(replay, "void texture_released_of(const nvn_tex* t) {")
    in_order(tex, ["tex_pages_add(t, -1);", "if (!async_on()) {", way, "if (way == release_queue::Way::Queued) {",
                   "std::lock_guard hl(held_mu);", "queued_tex_releases.push_back({*t, memory_generation_any_thread()});",
                   "queued_releases.fetch_add(1, std::memory_order_release);", "release_count(-1);", "return;",
                   "if (way == release_queue::Way::Held) {", "held_tex_releases.push_back(*t);", "return;",
                   "const auto r0 = std::chrono::steady_clock::now();", "sync_drain(1);", "do_texture_released(t);",
                   "release_count(", "return;", "Job j{JOB_TEXTURE_RELEASED};", "enqueue(std::move(j));"],
             "vk_replay.cpp texture_released_of")
    prog = block(replay, "void program_released_locked(const nvn_prog* p) {")
    in_order(prog, ["if (!async_on()) {", way, "if (way == release_queue::Way::Queued) {", "std::lock_guard hl(held_mu);",
                    "queued_prog_releases.push_back(*p);", "queued_releases.fetch_add(1, std::memory_order_release);",
                    "release_count(-1);", "return;", "if (way == release_queue::Way::Held) {", "held_prog_releases.push_back(*p);",
                    "st_held_releases++;", "return;", "const auto r0 = std::chrono::steady_clock::now();", "sync_drain(1);",
                    "do_program_released(p);", "release_count(", "return;", "Job j{JOB_PROGRAM_RELEASED};"],
             "vk_replay.cpp program_released_locked")
    on = block(replay, "bool release_queue_on() {")
    if 'static const char* env = getenv("RX_VK_RELEASE_QUEUE");' not in on or \
            'return release_queue::on(env, lab_ab::on("relq"));' not in on:
        raise SystemExit("FAIL: release_queue_on does not read RX_VK_RELEASE_QUEUE once with the knob relq")
    apply = block(replay, "void releases_apply_locked() {")
    in_order(apply, ["if (!release_queue::apply_now(queued_releases.load(std::memory_order_acquire), blocked_n.load())) return;",
                     "std::lock_guard hl(held_mu);", "ts.swap(queued_tex_releases);", "ps.swap(queued_prog_releases);",
                     "queued_releases.store(0, std::memory_order_release);", "mkwvk::texture_released(q.t.serial);",
                     "mkwvk::texture_released_at(&q.t, q.gen);", "program_released_after_reads(&p);"],
             "vk_replay.cpp releases_apply_locked")
    if "(replay_mu)" in apply or "do_texture_released(" in apply or "do_program_released(" in apply:
        raise SystemExit("FAIL: releases_apply_locked takes replay_mu again (its callers hold it)")
    run = block(replay, "bool run_submit(const uint64_t* handles, int n, uint64_t value, uint64_t queue, bool memory_work,")
    in_order(run, ["std::lock_guard lk(replay_mu);", "releases_apply_locked();", "ReplayPin pin;"], "vk_replay.cpp run_submit")
    present = block(replay, "void do_present(const nvn_tex* t, const int crop[4]) {")
    in_order(present, ["std::lock_guard lk(replay_mu);", "releases_apply_locked();", "bench_frame(presents);"],
             "vk_replay.cpp do_present")
    blocked = block(replay, "void update_blocked() {")
    in_order(blocked, ["if (!n) {", "for (const nvn_tex& t : ts) do_texture_released(&t);",
                       "for (const nvn_prog& p : ps) do_program_released(&p);",
                       "if (queued_releases.load(std::memory_order_acquire)) {", "std::lock_guard lk(replay_mu);",
                       "releases_apply_locked();"], "vk_replay.cpp update_blocked")
    if replay.count("releases_apply_locked();") != 3:
        raise SystemExit("FAIL: the queued releases are applied somewhere else")
    if replay.count("queued_tex_releases.push_back(") != 1 or replay.count("queued_prog_releases.push_back(") != 1:
        raise SystemExit("FAIL: a release is queued somewhere else")
    released = block(texture, "void texture_released(const nvn_tex* t) {")
    if "texture_released_at(t, memory_generation());" not in released:
        raise SystemExit("FAIL: vk_texture.cpp texture_released does not release from the generation now")
    at = block(texture, "void texture_released_at(const nvn_tex* t, WriteGen gen) {")
    if "it->second->released = true, it->second->release_gen = gen;" not in at or "memory_generation()" in at:
        raise SystemExit("FAIL: vk_texture.cpp texture_released_at does not take the generation it is given")
    any_thread = block(memory, "WriteGen memory_generation_any_thread() {")
    if "return gen_load(gens.now);" not in any_thread:
        raise SystemExit("FAIL: memory_generation_any_thread is not an atomic load of gens.now")
    dev_md = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if not any(line.startswith("| `RX_VK_RELEASE_QUEUE=1` |") and "**off unless set**" in line and "`relq`" in line
               for line in dev_md.splitlines()):
        raise SystemExit("FAIL: docs/development.md has no row for RX_VK_RELEASE_QUEUE with its default")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="release-queue-") as tmp:
        src = Path(tmp) / "t.cpp"
        exe = Path(tmp) / "t.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
        print(r.stdout.strip())
        if r.returncode:
            raise SystemExit("FAIL: release_queue.h")
    print("ok: test_release_queue")


if __name__ == "__main__":
    main()
