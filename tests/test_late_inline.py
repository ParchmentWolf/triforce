"""The late pages' partial rule alone, and one read of the GPU's progress for it (gpu/vk/late_inline.h, vk_memory.cpp
capture_make and take_capture; no game, no GPU).

(Triforce, 11-22, the performance audit's MEM-80, after Source B's.) RX_VK_LATE_NEW (knob latenew) turns four no-wait rules
for late pages on; RX_VK_LATE_INLINE=1 (knob lateinline), OFF unless set, turns on the partial rule alone (a page written
back in part has its other parts synced, no wait), and every other late page is waited for as by default. The partial rule
measures the write-backs still on the GPU against the progress capture_make read before its copies (kept in the Capture),
not a second read at the take.

Compiles the header: the switch's text and knob; over every input, with RX_VK_LATE_INLINE off the rules are the ones
RX_VK_LATE_NEW gave (all four by their own switches, or none), with it on and RX_VK_LATE_NEW off the partial rule alone.

And reads the source: the Capture keeps late_done, cleared with late_value when a capture is reused and set where
capture_make reads the progress; take_capture's gate is the rules' any, the four rules each asked by their flag, a page of
a pool with no mirror waited for when the skip rule is off, the partial rule's progress the capture's with no
vk_timeline_completed() in that block, the switch read once, the switches table.

    python -I -B tests/test_late_inline.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

PROGRAM = r"""
#include "late_inline.h"
#include <cstdio>
using namespace late_inline;
static int fails = 0;
#define CHECK(c) do { if (!(c)) { std::printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

int main() {
    CHECK(!on(nullptr, false) && on(nullptr, true) && !on("0", true) && on("1", false) && !on("x", true));
    for (int bits = 0; bits < 32; bits++) {
        const bool nw = bits & 1, in = bits & 2, same = bits & 4, part = bits & 8, defer = bits & 16;
        const Rules r = rules(nw, in, same, part, defer);
        if (!in) {   // (as RX_VK_LATE_NEW gave them: late_all = !late_new, each rule by its own switch)
            CHECK(r.any == nw && r.skip == nw && r.same == (nw && same) && r.part == (nw && part) && r.defer == (nw && defer));
        } else if (!nw) {   // (the partial rule alone)
            CHECK(r.any && !r.skip && !r.same && !r.defer && r.part == part);
        } else {   // (both: RX_VK_LATE_NEW's rules)
            CHECK(r.any && r.skip && r.same == same && r.part == part && r.defer == defer);
        }
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
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    if '#include "late_inline.h"' not in mem:
        raise SystemExit("FAIL: vk_memory.cpp does not include late_inline.h")
    cap = block(mem, "struct Capture {")
    if "uint64_t late_done = 0;" not in cap:
        raise SystemExit("FAIL: the Capture keeps no late_done")
    make = block(mem, "std::unique_ptr<Capture> capture_make(bool behind) {")
    in_order(make, ["c->late.clear(), c->late_value = 0, c->late_done = 0;", "const uint64_t done = vk_timeline_completed();",
                    "c->late_done = done;", "if (pv > done) {", "c->late.push_back((uint32_t)i);", "c->late_value = v;"],
             "vk_memory.cpp capture_make")
    take = mem[mem.index("if (c->late_value && c->map) {   // (the pages a submission still on the GPU writes back: see capture_make)"):]
    take = take[:take.index("c->late.assign(need.begin(), need.end());")]
    in_order(take, ['static const char* late_inline_env = getenv("RX_VK_LATE_INLINE");',
                    'const late_inline::Rules rules = late_inline::rules(late_new_env || lab_ab::on("latenew"),',
                    'late_inline::on(late_inline_env, lab_ab::on("lateinline")), late_same_on(),', "late_part_on(), late_defer_on());",
                    "const bool late_all = !rules.any;", "if (!late_all) {",
                    "if (p && p->mstate != Pool::MIRROR_ON && p->mstate != Pool::MIRROR_WANTED) {",
                    "if (rules.skip) late_skipped_now.push_back(i);", "else need.push_back(i);", "continue;",
                    "if (rules.same && std::binary_search(c->slots.begin(), c->slots.end(), i)) {",
                    "if (rules.part && std::binary_search(c->slots.begin(), c->slots.end(), i)) late_part_cand.push_back(i);",
                    "else need.push_back(i);", "if (!late_part_cand.empty()) {", "const uint64_t done = c->late_done;",
                    "wb_inflight_in(c->pages[i], done, g, LatePartial::kRanges, &n);", "&& rules.defer &&"],
             "vk_memory.cpp take_capture's late pages")
    part = take[take.index("if (!late_part_cand.empty()) {"):]
    part = part[:part.index("st_late_part += ")]
    if "vk_timeline_completed()" in part:
        raise SystemExit("FAIL: the partial rule reads the GPU's progress again at the take")
    for old in ("if (late_same_on() && std::binary_search", "if (late_part_on() && std::binary_search", "&& late_defer_on() &&"):
        if old in take:
            raise SystemExit("FAIL: take_capture asks a rule's switch directly, not its flag: %s" % old)
    dev_md = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if not any(line.startswith("| `RX_VK_LATE_INLINE=1` |") and "**off unless set**" in line and "`lateinline`" in line
               for line in dev_md.splitlines()):
        raise SystemExit("FAIL: docs/development.md has no row for RX_VK_LATE_INLINE with its default")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="late-inline-") as tmp:
        src = Path(tmp) / "t.cpp"
        exe = Path(tmp) / "t.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        print(r.stdout.strip())
        if r.returncode:
            raise SystemExit("FAIL: late_inline.h")
    print("ok: test_late_inline")


if __name__ == "__main__":
    main()
