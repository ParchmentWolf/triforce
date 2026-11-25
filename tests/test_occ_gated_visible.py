"""A samples-passed count of 0 over a draw that a written count's condition left out is not written: its record keeps
4096, visible (RX_VK_OCC_GATED_VISIBLE, on by default, =0: written as 0, as before; gpu/vk/occ_answer.h complete,
gpu/vk/vk_replay.cpp occ_read_slot).

The game draws an object under a render condition on its last count, between a reset and the next report. When the
condition skips that draw, the queries count nothing for it: a 0 for that window says only that what was drawn besides
showed no sample. It was written all the same, "for the CPU": the game's CPU read it, stopped drawing an object that may
be in view and drew its proxy instead, whose count then brought the object back: an object that comes and goes. A count
that is not known for sure is visible, never 0.

What must hold, without the game or a GPU:
- occ_answer.h (compiled and run): with the rule on, a gated 0 is not written, the word keeps the replay's value, its
  report is settled (a condition reads memory) and the stats count it; a gated count above 0 is written and marked gated,
  as before; a 0 that is not gated is written, as before (a hidden object is still hidden); with the rule off a gated 0 is
  written, as before. A frame loop with the rule on and the gate on: the word the CPU reads is 0 only in a frame whose
  draw ran and showed nothing.
- vk_replay.cpp: the switch read once in occ_init, on unless set to 0; occ_read_slot passes it to occ::complete; the line.

    python -I -B tests/test_occ_gated_visible.py [--cxx clang++]
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
#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); failures++; } } while (0)

// One report at addr: its count `sum` (gated or not) read back and completed with the rule on or off. Returns the word
struct One { uint64_t mem; S src; Stats st; int writes; };
static One one(uint64_t sum, bool gated, bool rule) {
    One o{kVisible, S::kNone, {}, 0};
    Writers w;
    Rep r;
    r.addr = 0x1000, r.pos = 7, r.present = 3, r.first = 0, r.n = 1, r.gated = gated;
    w.placed(r.addr, r.pos, r.present, true, kVisible);
    const uint64_t pairs[2] = {sum, 1};
    complete({r}, pairs, 1, true, w, 3, o.st, [&](uint64_t, uint64_t expect, uint64_t count) {
        o.writes++;
        if (o.mem != expect) return false;
        o.mem = count;
        return true;
    }, [](uint64_t, uint64_t) {}, rule);
    o.src = w.word(r.addr, 3);
    return o;
}

int main() {
    {   // a gated 0, the rule on: not written, 4096 stays, settled, counted
        const One o = one(0, true, true);
        CHECK(o.mem == kVisible && o.writes == 0);
        CHECK(o.src == S::kFinalSrc);   // (no count comes: a condition reads memory, where 4096 renders)
        CHECK(o.st.gated_kept == 1 && o.st.written == 0 && o.st.zeros == 0 && o.st.gated_written == 0 && o.st.gated_zeros == 0);
    }
    {   // a gated count above 0: something of the object showed: written, marked gated, as before
        const One o = one(37, true, true);
        CHECK(o.mem == 37 && o.writes == 1 && o.src == S::kGatedSrc);
        CHECK(o.st.gated_kept == 0 && o.st.written == 1 && o.st.gated_written == 1 && o.st.gated_zeros == 0);
    }
    {   // a 0 that is not gated: every draw of the window ran, the object is hidden: written, as before
        const One o = one(0, false, true);
        CHECK(o.mem == 0 && o.writes == 1 && o.src == S::kWrittenSrc);
        CHECK(o.st.gated_kept == 0 && o.st.written == 1 && o.st.zeros == 1);
    }
    {   // the rule off: a gated 0 is written, as before
        const One o = one(0, true, false);
        CHECK(o.mem == 0 && o.writes == 1 && o.src == S::kGatedSrc);
        CHECK(o.st.gated_kept == 0 && o.st.gated_written == 1 && o.st.gated_zeros == 1);
    }
    {   // the default of complete() is the rule off (the callers that do not say): as before
        Writers w;
        Stats st;
        Rep r;
        r.addr = 0x1000, r.pos = 7, r.present = 3, r.first = 0, r.n = 1, r.gated = true;
        w.placed(r.addr, r.pos, r.present, true, kVisible);
        const uint64_t pairs[2] = {0, 1};
        uint64_t mem = kVisible;
        complete({r}, pairs, 1, true, w, 3, st, [&](uint64_t, uint64_t, uint64_t count) { mem = count; return true; },
                 [](uint64_t, uint64_t) {});
        CHECK(mem == 0);
    }
    {   // a frame loop, one object at one address, the gate on: frame f's draw runs under a condition on the word as the
        // last completed count left it; the CPU reads the same word. shows[f]: whether the object's draw shows samples
        for (const bool rule : {true, false}) {
            const bool shows[10] = {true, false, false, true, true, true, false, true, true, true};
            uint64_t mem = kVisible;
            Writers w;
            Stats st;
            const uint64_t addr = 0x2000;
            int wrong_zero = 0;   // (frames in which the CPU read 0 though the last draw that ran showed the object)
            bool last_ran_showed = true;
            for (int f = 0; f < 10; f++) {
                // (the condition: equal to 0 means skip; a pending word, or a gated one with the gate on, renders)
                const S src = w.word(addr, f);
                const Cond c = cond_decide(mem != 0, src, S::kNone, true, true, true);
                if (mem == 0 && last_ran_showed) wrong_zero++;
                Counter k;
                k.reset(0, 9, 0);
                uint64_t pairs[2] = {0, 1};
                uint32_t used = 0;
                if (c.enabled) {
                    k.draw_enter(false);
                    CHECK(k.begin(false, 9));
                    k.draw_issued(false), used = 1, pairs[0] = shows[f] ? 500 : 0;
                    last_ran_showed = shows[f];
                } else {
                    k.gate(false);
                }
                Rep r;
                bool keep_now = false;
                CHECK(k.report(false, 9, used, &r, &keep_now) == Counter::kMeasured);
                r.addr = addr, r.pos = 100 + (uint64_t)f, r.present = f;
                // (the replay's placeholder: the word is 4096 again at each report, then the count over it)
                mem = kVisible;
                w.placed(addr, r.pos, f, true, kVisible);
                complete({r}, pairs, used, true, w, f, st, [&](uint64_t, uint64_t expect, uint64_t count) {
                    if (mem != expect) return false;
                    mem = count;
                    return true;
                }, [](uint64_t, uint64_t) {}, rule);
                // (a 0 in the word after this frame is the object's only if its draw ran and showed nothing)
                if (rule) CHECK(mem != 0 || (c.enabled && !shows[f]));
            }
            if (rule) CHECK(wrong_zero == 0);
        }
    }
    {   // the line
        Stats st;
        st.gated_kept = 12, st.gated_zeros = 0;
        char line[512];
        st.gated_line(line, sizeof line, 600, true);
        CHECK(std::string(line).find("12 such counts kept 4096") != std::string::npos);
        CHECK(std::string(line).find("not written (RX_VK_OCC_GATED_VISIBLE)") != std::string::npos);
        st.gated_line(line, sizeof line, 600, false);
        CHECK(std::string(line).find("written as 0, as before (RX_VK_OCC_GATED_VISIBLE)") != std::string::npos);
    }
    std::printf(failures ? "FAILED: %d\n" : "ok\n", failures);
    return failures ? 1 : 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="clang++")
    args = p.parse_args()
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    for needle, why in (
        ("bool occ_gated_visible = true;", "the rule is not on by default"),
        ('occ_gated_visible = !(getenv("RX_VK_OCC_GATED_VISIBLE") && atoi(getenv("RX_VK_OCC_GATED_VISIBLE")) == 0);',
         "RX_VK_OCC_GATED_VISIBLE is not read (0: off, as before)"),
        ("[](uint64_t addr, uint64_t count) { occ_sites.measured(addr, count); }, occ_gated_visible);",
         "occ_read_slot does not pass the rule to occ::complete"),
        ("occ_st.gated_line(line, sizeof line, 600, occ_gated_visible);", "the gated zeros have no line"),
    ):
        if needle not in replay:
            raise SystemExit("FAIL: vk_replay.cpp: " + why)
    if replay.count("occ::complete(") != 1:
        raise SystemExit("FAIL: vk_replay.cpp completes counts in another place too: does it pass the rule?")
    with tempfile.TemporaryDirectory(prefix="occ-gated-visible-") as tmp:
        tmp = Path(tmp)
        cpp, exe = tmp / "t.cpp", tmp / "t.exe"
        cpp.write_text(TEST_CPP, encoding="utf-8")
        r = subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu/vk"), str(cpp), "-o",
                            str(exe)], capture_output=True, text=True, timeout=180)
        if r.returncode:
            print(r.stdout + r.stderr)
            raise SystemExit("FAIL: occ_answer.h's check did not build")
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        print(r.stdout.strip())
        if r.returncode:
            raise SystemExit("FAIL: a gated count of 0 is not kept visible as it should be")
    print("PASS: a count of 0 over a draw a written count's condition left out keeps 4096; the others as before")


if __name__ == "__main__":
    main()
