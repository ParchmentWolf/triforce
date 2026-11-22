"""A samples-passed count over a draw that a written count's condition left out (on by default, RX_VK_OCC_GATE=0: off;
gpu/vk/occ_answer.h Counter::gate, Writers::kGatedSrc, cond_decide; vk_replay.cpp occ_gate_note).

Tickets 11-21 (Forest Temple items and trees, black interiors; RX_VK_OCC_QUERY=0 showed them): the game draws an object it
thinks visible under a render condition on its last count, between a reset and the next report. When that count was a 0
the condition skips the draw, NVN counts nothing for it and neither do the queries: the next count is 0 again because of the
skip, the next condition skips again, and the object never comes back. On the console the game's CPU reads the 0 after its
frame wait and draws the object's proxy instead; here most counts land after the CPU has read the placeholder (4096), so
nothing breaks the loop. Such a count is marked gated (still written, for the CPU); with RX_VK_OCC_GATE=1 a condition on it
renders. What must hold, without the game or a GPU:
- occ_answer.h (compiled and run): gate only while counting; a reset clears it; the cumulative count after a report (keep)
  stays gated until the reset; the report carries it; complete writes a gated count (0 too) and marks the word gated;
  word() says so; cond_decide renders on it with the switch on, reads memory with it off, a pending word still renders; the
  stats line counts them. A frame loop: with the switch off an object hidden once stays hidden after it shows again (the
  tickets' loop); with it on it is drawn again within two frames, and a hidden object is still skipped every other frame.
- vk_replay.cpp: the switch read once in occ_init (off unless set), occ_gate_note on draws only (not dispatches, not the dry
  pass) after occ_skip_note, the serial replay's state from occ_cond_off and a segment's from par_conds (2: off from a
  written count), occ_seg_off cleared at a render enable and a segment's edge; occ_cond reads a gated word again and passes
  the switch to cond_decide.
- docs/development.md: the switch in the table.

    python -I -B tests/test_occ_gate.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

TEST_CPP = r'''
#include "occ_answer.h"
#include <cstdio>
#include <string>
#include <vector>
using namespace mkwvk::occ;
using S = Writers::Src;
static int failures = 0;
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x); failures++; } } while (0)

// One object the game draws under a condition on its last count, its draw counted for the next report (the tickets' loop).
// visible[f]: whether it shows in frame f when drawn. The count of frame f lands before frame f + 1's condition. Returns
// the frames it was drawn in.
static std::vector<int> loop(const std::vector<bool>& visible, bool gate_on) {
    Writers w;
    Stats st;
    std::vector<int> drawn;
    const uint64_t slot_serial = 9;
    for (int f = 0; f < (int)visible.size(); f++) {
        const uint64_t prev = 0x1000 + 32 * (uint64_t)((f + 1) % 2), addr = 0x1000 + 32 * (uint64_t)(f % 2);   // (a ring of two)
        bool enabled = true;
        if (f) {   // (the condition: render if the count is not 0; memory holds the last written count)
            const S sx = w.word(prev, f);
            const Cond c = cond_decide(w.value(prev) != 0, sx, S::kNone, true, true, gate_on);
            st.cond(c.kind);
            enabled = c.enabled;
        }
        Counter k;
        k.reset(0, slot_serial, 0);
        uint64_t pairs[2] = {0, 1};
        uint32_t used = 0;
        if (enabled) {   // (draw(): its query begun, the draw recorded)
            k.draw_enter(false);
            CHECK(k.begin(false, slot_serial));
            k.draw_issued(false), used = 1, pairs[0] = visible[f] ? 500 : 0, drawn.push_back(f);
        } else {         // (a draw the condition skips never goes into draw(): replay()'s occ_gate_note)
            k.gate(false);
        }
        Rep r;
        bool keep_now = false;
        CHECK(k.report(false, slot_serial, used, &r, &keep_now) == Counter::kMeasured && !keep_now);
        CHECK(r.gated == !enabled);
        r.addr = addr, r.pos = 100 + (uint64_t)f, r.present = f;
        w.placed(addr, r.pos, f, true, kVisible);
        uint64_t mem = kVisible;
        complete({r}, pairs, used, true, w, f, st, [&](uint64_t, uint64_t expect, uint64_t count) {
            if (mem != expect) return false;
            mem = count;
            return true;
        }, [](uint64_t, uint64_t) {});
        CHECK(mem == (enabled && visible[f] ? 500u : 0u));   // (a gated count is written too: the CPU reads it)
        CHECK(w.word(addr, f) == (enabled ? S::kWrittenSrc : S::kGatedSrc));
    }
    return drawn;
}

int main() {
    {   // the counter: gated only while counting, cleared by a reset, kept past a report while counting goes on (keep)
        Counter k;
        k.gate(false);
        CHECK(!k.gated);
        k.reset(0, 5, 0);
        k.gate(false);
        CHECK(k.gated);
        Rep r;
        bool kn = false;
        CHECK(k.report(false, 5, 0, &r, &kn) == Counter::kMeasured && r.gated);
        k.reset(0, 5, 0);
        CHECK(!k.gated);
        CHECK(k.report(false, 5, 0, &r, &kn) == Counter::kMeasured && !r.gated);
        k.gate(false);   // (reported, no keep: not counting)
        CHECK(!k.gated);
        k.gate(true);    // (keep: the counting goes on past the report, the next cumulative count is gated)
        CHECK(k.gated);
        CHECK(k.report(true, 5, 0, &r, &kn) == Counter::kMeasured && r.gated);
        k.segment();
        CHECK(!k.gated);
    }
    {   // Writers and cond_decide
        Writers w;
        w.placed(0x40, 1, 0, true, kVisible);
        w.wrote(0x40, 1, 0, true);
        CHECK(w.word(0x40, 0) == S::kGatedSrc && w.value(0x40) == 0);
        w.placed(0x40, 2, 0, true, kVisible);   // (a new report there: not gated, pending)
        CHECK(w.word(0x40, 0) == S::kPendingSrc);
        w.wrote(0x40, 2, 0);
        CHECK(w.word(0x40, 0) == S::kWrittenSrc);
        CHECK(cond_decide(false, S::kGatedSrc, S::kNone, true, true, true).enabled);
        CHECK(cond_decide(false, S::kGatedSrc, S::kNone, true, true, true).kind == Cond::kGated);
        CHECK(cond_decide(false, S::kNone, S::kGatedSrc, true, true, true).kind == Cond::kGated);
        CHECK(!cond_decide(false, S::kGatedSrc, S::kNone, true, true, false).enabled);   // (off: a written count, from memory)
        CHECK(cond_decide(false, S::kGatedSrc, S::kNone, true, true, false).kind == Cond::kWrittenOff);
        CHECK(cond_decide(true, S::kGatedSrc, S::kNone, true, true).kind == Cond::kWrittenOn);   // (the default: off)
        CHECK(cond_decide(false, S::kGatedSrc, S::kPendingSrc, true, true, false).kind == Cond::kUnknown);
        CHECK(!cond_decide(false, S::kGatedSrc, S::kNone, false, true, true).enabled);   // (the knob's off phase: as before)
        CHECK(cond_decide(false, S::kWrittenSrc, S::kNone, true, true, true).kind == Cond::kWrittenOff);   // (not gated: skips)
        CHECK(std::string(src_name(S::kGatedSrc)).find("written") == 0);
    }
    {   // the frame loop of the tickets: hidden for frames 2-3, shows again from frame 4
        std::vector<bool> vis(12, true);
        vis[2] = vis[3] = false;
        const std::vector<int> off = loop(vis, false);
        CHECK(off.size() == 3 && off.back() == 2);   // (drawn 0-2, then never again: the skip's 0 keeps it hidden)
        const std::vector<int> on = loop(vis, true);
        CHECK(std::find(on.begin(), on.end(), 3) == on.end());   // (frame 2's real 0 still skips frame 3, as on the console)
        for (int f = 4; f < 12; f++) CHECK(std::find(on.begin(), on.end(), f) != on.end());   // (back as it shows)
        std::vector<bool> hidden(12, false);
        const std::vector<int> h = loop(hidden, true);
        CHECK(h == (std::vector<int>{0, 2, 4, 6, 8, 10}));   // (still skipped every other frame while it stays hidden)
    }
    {   // the stats line
        Stats s;
        s.gated = 5, s.gated_written = 4, s.gated_zeros = 3, s.cond_gated_read = 2, s.cond_gated = 1;
        s.cond(Cond::kGated);
        CHECK(s.cond_gated == 2 && s.conds == 1);
        char line[2048];
        CHECK(s.line(line, sizeof line, 600, 1) < (int)sizeof line);
        CHECK(std::string(line).find("counts over a draw such a skip left out: 5 counted whole, 4 written (3 of them 0), 2 "
                                     "conditions read one (2 rendered: RX_VK_OCC_GATE=1)") != std::string::npos);
    }
    if (failures) {
        std::fprintf(stderr, "occ_gate: %d failed\n", failures);
        return 1;
    }
    std::puts("occ_gate: all cases pass");
    return 0;
}
'''


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(where, text, needles):
    at = [text.index(n) if n in text else -1 for n in needles]
    if -1 in at or at != sorted(at):
        raise SystemExit(where + ": not in this order: " + " / ".join(needles))


def check_source(src):
    replay = (src / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    in_order("vk_replay.cpp occ_init (RX_VK_OCC_GATE: on unless 0)", block(replay, "bool occ_init() {"),
             ['occ_log_cond = getenv("RX_VK_OCC_LOG_COND")',
              'occ_gate_on = !(getenv("RX_VK_OCC_GATE") && atoi(getenv("RX_VK_OCC_GATE")) == 0);'])
    if "bool occ_gate_on = true;" not in replay:
        raise SystemExit("vk_replay.cpp: occ_gate_on is not on by default")
    in_order("vk_replay.cpp occ_gate_note (a draw off from a written count's condition gates the thread's counting)",
             block(replay, "void occ_gate_note(const NvnState& s, bool worker) {"),
             ["if (s.render_enabled || s.raster_discard || (worker ? occ_seg_off : occ_cond_off) != &s) return;",
              "occ_ctr().gate(occ_keep.load(std::memory_order_relaxed));"])
    in_order("vk_replay.cpp occ_cond (a gated word read again; the switch to cond_decide; counted)",
             block(replay, "void occ_cond(const NvnState& s, uint64_t addr, int mode, uint64_t& x, uint64_t& y, bool* enabled) {"),
             ["const bool gated = sx == occ::Writers::kGatedSrc || sy == occ::Writers::kGatedSrc;",
              "sy == occ::Writers::kWrittenSrc || gated)) {", "host->gpu_read(addr, &x, 8);",
              "occ::cond_decide(*enabled, sx, sy, active, occ_cond_on, occ_gate_on);", "occ_st.cond_gated_read += active && gated ? 1 : 0;",
              "if (c.kind == occ::Cond::kWrittenOff) occ_cond_off = &s;"])
    in_order("vk_replay.cpp occ_report_measure (gated counts counted)",
             block(replay, "void occ_report_measure(VkCommandBuffer cmd, uint64_t addr, uint64_t pos, bool writable) {"),
             ["case occ::Counter::kMeasured: occ_st.measured++, occ_st.gated += rep.gated ? 1 : 0; break;"])
    in_order("vk_replay.cpp occ_segment_edge (a segment's state cleared)", block(replay, "void occ_segment_edge(VkCommandBuffer cmd) {"),
             ["c.segment();", "occ_seg_off = nullptr;"])
    replay_fn = block(replay, "void replay(VkCommandBuffer& cmd, NvnState& s, const uint8_t* p, const uint8_t* end = nullptr) {")
    enable = replay_fn[replay_fn.index("case NOP_RENDER_ENABLE:"):replay_fn.index("case NOP_RENDER_COND: {")]
    in_order("vk_replay.cpp NOP_RENDER_ENABLE (both threads' states end)", enable,
             ["if (occ_live && !worker && occ_cond_off == &s) occ_cond_off = nullptr;",
              "if (occ_live && worker && occ_seg_off == &s) occ_seg_off = nullptr;"])
    cond = replay_fn[replay_fn.index("case NOP_RENDER_COND: {"):]
    in_order("vk_replay.cpp NOP_RENDER_COND (par_conds: 1 on, 0 off, 2 off from a written count)", cond[:3000],
             ["if (worker) {", "const uint8_t v = cond_at < par_conds_n.load(std::memory_order_acquire) ? par_conds[cond_at] : 1;",
              "s.render_enabled = v == 1;", "occ_seg_off = v == 2 ? &s : nullptr;", "break;",
              "else occ_cond(s, r.addr, (int)r.mode, x, y, &s.render_enabled);",
              "const uint8_t v = s.render_enabled ? 1 : occ_live && occ_cond_off == &s ? 2 : 0;", "par_conds.push_back(v);"])
    if "par_conds[cond_at] != 0" in replay:
        raise SystemExit("vk_replay.cpp: a segment takes a condition's 2 (off from a written count) for on")
    in_order("vk_replay.cpp replay() (draws only, the serial replay's and a segment's, after the skip's note)", replay_fn,
             ["h.op == NOP_DISPATCH || h.op == NOP_DISPATCH_INDIRECT) {", "if (occ_live && !worker) occ_skip_note(s, false);",
              "if (occ_live && !dry && h.op != NOP_DISPATCH && h.op != NOP_DISPATCH_INDIRECT) occ_gate_note(s, worker);"])
    if replay.count("occ_gate_note(") != 2:   # (its definition and replay()'s call)
        raise SystemExit("vk_replay.cpp: occ_gate_note is called somewhere other than replay()'s draws")
    dev = (src / "docs/development.md").read_text(encoding="utf-8")
    if "`RX_VK_OCC_GATE=0`" not in dev:
        raise SystemExit("docs/development.md: RX_VK_OCC_GATE=0 is not in the switches table")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=ROOT)
    p.add_argument("--cxx", default="clang++")
    a = p.parse_args()
    check_source(a.source)
    with tempfile.TemporaryDirectory(prefix="occ-gate-") as temp:
        cpp, exe = Path(temp) / "occ_gate_test.cpp", Path(temp) / "occ_gate_test.exe"
        cpp.write_text(TEST_CPP, encoding="utf-8")
        flags = ["-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS", "-I" + str(a.source / "gpu/vk")]
        subprocess.run([a.cxx, *flags, str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("occ_gate: ok")


if __name__ == "__main__":
    main()
