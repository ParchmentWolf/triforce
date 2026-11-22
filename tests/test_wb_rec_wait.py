"""A wait for a write-back still on the GPU, by its writer's recording (gpu/vk/wb_rec_wait.h, vk_replay.cpp vk_timeline_wait; the
handoff's §12.9). No game, no GPU.

The waits for write-backs (a capture's late pages on the game's submitting thread, a read or a binding of a page put off) waited
for the submissions' timeline, which finish_recording signals only as far as no older submission is stopped at an event wait:
20 to 46 ms at the lab's steady Market with the GPU 4 submissions behind. The recording the submission was finished in is waited
for first, on the recordings' timeline; the rest of the wait is counted as the timeline held, and RX_VK_WB_WAIT_REC=1 ends the
wait there (off by default).

Compiles and runs the header's rules (the switch, the finished submissions' table, the budget, the held part, the stall line's
words), and reads the source for what needs the game:
- submit_recording notes in fin_rec only the submissions finished in the recording (rec_open_values), never the recording's own
  value: a submission still being recorded in parts is not known, and its wait is the timeline's as before;
- (Triforce) and only at the submit that ends the recording: a part's (a split, the early tail's start, a parallel replay's
  setup during a burst) keeps them for it, as their write-backs are recorded at the recording's end (a burst in parts, below);
- vk_timeline_wait looks the value up under rec_map_mu, waits for the recording on rec_timeline first, waits for the timeline
  unless the switch ends the wait there, with what is left of the one bound, and counts the held part for the stall line;
- status_tick gives the held part to the stall line, and the switch is in the development guide.
- (Triforce, 11-22, the performance audit's SYNC-122) the reads' side: the switch is a mode (2 the check); a readback whose
  write-back is not recorded yet is counted, and under the mode waits in slices that look the finished table up (the header's
  fallback_wait, run here against a made-up GPU on 20,000 random cases: the check ends exactly where the old wait ends, mode 1
  never before the writer's recording is done and never after the old wait); RX_VK_TL_REC ends a wait at the recording that
  finished the value, its old first-part lookup kept to =2; the held part is counted by caller (take, read, bind, readback).

    python -I -B tests/test_wb_rec_wait.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def function(text, head):
    at = text.index(head)
    return text[at:text.index("\n}\n", at)]


def check_source():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    submit = function(replay, "void submit_recording(")
    check("fin_rec.submitted(rec_open_values, seq, !part);" in submit,
          "submit_recording does not note the submissions finished in the recording at its end")
    check("fin_rec.note(" not in submit, "submit_recording notes in fin_rec past submitted (a part's, or a recording's own value?)")
    check("void submit_recording(Recording& r, bool signal_value = true, uint64_t signal_at = 0, bool part = false) {" in replay,
          "submit_recording has no part argument")
    check("::mkwvk::wb_rec_wait::Finished fin_rec;" in replay, "the finished submissions' table is missing")
    # (Triforce) the submits of a part of a recording that goes on: a split, the early tail's start, a parallel replay's setup.
    # Their write-backs are recorded at the recording's end; the submits that end it (finish_recording, a present's) finish them
    split = function(replay, "void maybe_split(VkCommandBuffer& cmd) {")
    check("submit_recording(*rec_cur, false, 0, true);" in split, "maybe_split's submit is not a part's")
    tail = function(replay, "void tail_begin(VkCommandBuffer& cmd) {")
    check("submit_recording(*rec_cur, false, 0, true);" in tail, "tail_begin's submit is not a part's")
    par = replay[replay.index("memory_sync_mirrors_before_segments();"):]
    check(par[:par.index("\n", par.index("submit_recording("))].count("submit_recording(r, false, 0, true);") == 1,
          "a parallel replay's setup submit is not a part's")
    # ((Triforce, 11-22) four since v0.6.0: the parallel replay's early segments (RX_VK_SEG_EARLY) submit what came before them
    # and the dry pass's uploads as a part too, ahead of every segment; this check still said three and failed on v0.6.0 itself)
    check("submit_recording(r, false, 0, true);   // (a part: what came before and the dry pass's uploads, ahead of every segment)" in replay,
          "the early segments' setup submit is not a part's")
    check(sum(", 0, true)" in line for line in replay.splitlines() if "submit_recording(" in line) == 4,
          "a submit other than the four parts' is a part's")
    finish = function(replay, "void finish_recording(uint64_t value) {")
    check("submit_recording(r, signal, at);" in finish, "finish_recording's submit does not end the recording")
    # (Triforce-dev: a present that leaves work stopped (RX_VK_PRESENT_DRAIN=2) names its timeline signal as finish_recording
    # does; it is still the submit that ends its recording, not a part's)
    present = function(replay, "void do_present(const nvn_tex* t, const int crop[4]) {")
    check("submit_recording(r, signal, at);" in present, "a present's submit does not end its recording")

    wait = function(replay, "void vk_timeline_wait(uint64_t v) {")
    for needle, why in (
            ("std::lock_guard mk(rec_map_mu);", "the table is read without its lock"),
            ("seq = fin_rec.of(v);", "the writer's recording is not looked up"),
            ("ri.pSemaphores = &rec_timeline;", "the recording is not waited for on the recordings' timeline"),
            ("if (!wr::ends_at_recording(ends_here, seq != 0, rec_done)) {", "the switch does not decide the timeline's wait"),
            # ((Triforce, 11-22, the performance audit's SYNC-122) the mode, RX_VK_TL_REC through the finished table, by caller
            ("const bool ends_here = wr::ends_by_switch(wb_wait_rec_mode(), rb_fix(1), tl_rec_first_part_on());",
             "RX_VK_TL_REC does not end the wait at the recording that finished the value"),
            ("if (rb_fix(1) && tl_rec_first_part_on()) {", "RX_VK_TL_REC's old lookup (a first part) is not kept to RX_VK_TL_REC=2"),
            ("stall_ct.wb_held_by_ns[wb_wait_who].fetch_add(held, std::memory_order_relaxed);", "the held part is not counted by caller"),
            ("wr::budget_left(wr::kBoundNs, rec_ns)", "the timeline's wait does not keep to what is left of the bound"),
            ("wr::held_ns(seq != 0, rec_done, rec_ns, waited_ns)", "the held part is not counted"),
            ("stall_ct.wb_held_ns.fetch_add(", "the held part does not reach the stall line's counts"),
            ("wb_held_last_ns = held;", "the held part does not reach the capture's late line")):
        check(needle in wait, "vk_replay.cpp vk_timeline_wait: " + why)
    # (the recording first, then the timeline: the timeline cannot reach v before the recording that finished it)
    check(wait.index("ri.pSemaphores = &rec_timeline;") < wait.index("wi.pSemaphores = &timeline;"),
          "vk_timeline_wait waits for the timeline before the writer's recording")
    # (the flush of held submits before either wait: a batched submit holds both timelines' signals)
    check(wait.index("queue_flush_for(FR_VALUE);") < wait.index("ri.pSemaphores = &rec_timeline;"),
          "vk_timeline_wait waits for the recording before the held submits are flushed")
    check("wb_held_last_ns = 0;" in wait[:wait.index("if (!timeline) return;")],
          "the thread's last held part is not reset at a wait's start")
    on = function(replay, "static int wb_wait_rec_mode() {")
    check('const char* e = getenv("RX_VK_WB_WAIT_REC");' in on and "const int m = wr::mode(e);" in on, "RX_VK_WB_WAIT_REC is not read as a mode")
    check("wb_wait_rec_on" not in replay, "the switch is read as on / off somewhere: 2 would be on")
    check_reads(replay)

    tick = function(replay, "void status_tick() {")
    for needle in ("stall_ct.wb_held.load(", "stall_ct.wb_held_ns.load(",
                   "f.wb_held = wb_held - s_wb_held, f.wb_held_ms = (wb_held_ns - s_wb_held_ns) / 1e6;",
                   "s_wb_held = wb_held, s_wb_held_ns = wb_held_ns;"):
        check(needle in tick, "vk_replay.cpp status_tick: the stall line's held part is not this frame's (%s)" % needle)

    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    check("`RX_VK_WB_WAIT_REC=1`" in dev, "docs/development.md: RX_VK_WB_WAIT_REC is not in the switches table")


def check_reads(replay):
    """(Triforce, 11-22, the performance audit's SYNC-122) the reads' side: the readback's fallback, the callers, RX_VK_TL_REC"""
    fb = function(replay, "void readback_fallback_wait(uint64_t v, bool by_recording) {")
    for needle, why in (
            ("void plain() { wait_value(v); }", "off, the fallback is not the wait it was"),
            ("return fin_rec.of(v);", "the slices do not look the finished table up"),
            ("std::lock_guard mk(rec_map_mu);", "the table is read without its lock"),
            ("const VkResult res = vkWaitSemaphores(dev.device, &wi, wr::kSliceNs);", "the slices are not 1 ms waits on the timeline"),
            ("return vkWaitSemaphores(dev.device, &ri, UINT64_MAX) == VK_SUCCESS ? 0 : 2;", "the recording's wait has a bound"),
            ("wr::fallback_wait(wb_wait_rec_mode(), by_recording && rec_timeline != VK_NULL_HANDLE, calls);",
             "the fallback is not the header's, by the switch's mode"),
            ("stall_ct.wb_held_by_ns[wr::kReadback].fetch_add(held, std::memory_order_relaxed);", "its held part does not reach the stall line"),
            ("st_rb_fb.fetch_add(1, std::memory_order_relaxed)", "the fallbacks are not counted")):
        check(needle in fb, "vk_replay.cpp readback_fallback_wait: " + why)
    inv = function(replay, "void invalidate(uint64_t gpu, uint64_t size) {")
    check(inv.count("readback_fallback_wait(v, unforced);") == 1, "invalidate's fallback is not the counted one")
    # (the replay thread's own path keeps its waits; only the last else, the submitting thread's, is the fallback)
    at = inv.index("readback_fallback_wait(v, unforced);")
    check(inv.rindex("if (async_unforced()) {", 0, at) < inv.rindex("} else {", 0, at) and inv.count("wait_value(v);") == 1,
          "invalidate: the fallback is not where the unbounded wait on the timeline was")
    check("st_rb_fb.exchange(0)" in inv and "(counted with RX_VK_WB_WAIT_REC=2: what 1 would not have waited)" in inv,
          "the 3000-readback line does not say the fallbacks")
    check("void vk_timeline_wait_from(uint64_t v, int who) {" in replay, "vk_timeline_wait_from is missing")
    tick = function(replay, "void status_tick() {")
    for needle in ("wb_by[i] = stall_ct.wb_held_by_ns[i].load(std::memory_order_relaxed);",
                   "f.wb_held_by[i] = (wb_by[i] - s_wb_by[i]) / 1e6;", "s_wb_by[i] = wb_by[i];"):
        check(needle in tick, "vk_replay.cpp status_tick: the held part by caller is not this frame's (%s)" % needle)
    memory = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    read = function(memory, "void late_unresolved_read(uint64_t page0, uint64_t page1) {")
    check("vk_timeline_wait_from(v, 1);" in read and "vk_timeline_wait(v)" not in read, "a read of a page put off does not wait as a read")
    bind = memory[memory.index("deferred_late_n.store((int)deferred_late.size(), std::memory_order_relaxed);\n    }\n    for (uint32_t page : hit) {"):]
    bind = bind[:bind.index("\n}\n")]
    check("if (v > done0) vk_timeline_wait_from(v, 2);" in bind, "a binding of a page put off does not wait as a bind")
    head = (ROOT / "gpu/vk/wb_rec_wait.h").read_text(encoding="utf-8")
    check("kTake = 0, kRead = 1, kBind = 2, kReadback = 3, kCallers = 4" in head, "the callers' numbers moved: vk_memory.cpp passes 1 and 2")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    check("`RX_VK_WB_WAIT_REC=1`, `=2`" in dev and "`RX_VK_TL_REC=2` keeps the old lookup" in dev,
          "docs/development.md: the mode and RX_VK_TL_REC are not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="wb-rec-wait-") as tmp:
        exe = Path(tmp) / "wb-rec-wait"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_wb_rec_wait.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: a wait for a write-back by its writer's recording, the held part counted")


if __name__ == "__main__":
    main()
