"""The 90% and 97% rules take their excess, not an eighth of the cache (gpu/vk/vram_compact.h rule_target's three-argument
form, vk_texture.cpp texture_frame, RX_VK_EVICT_EXCESS; no game/GPU).

With the compaction on, the hold's pass let textures unused for 60 presents go down to 7/8 of the budget the 90% and 97%
rules left. Those budgets are "the textures less the excess", not sizes: 62 MB over the line on an 8 GB card took about
400 MB, all on screen again within the camera's turn, made again, and over the line again. Now the budget's size is kept
apart: 7/8 of the size when over it, and for the two rules their budget less 64 MB. Checked:

1. The rule, compiled from the header: the Market on an 8 GB card (2,873 MB held, a size of 3,285 MB, the 90% rule's budget
   2,811 MB) lets 126 MB go, not 413; the size alone as before; both over, the lower; never under nothing.
2. texture_frame: the size taken after the live line and before the 90% rule; the rules' budget after the 90% rule and
   through the 97% one; rule_to from both with the switch on, the old form with RX_VK_EVICT_EXCESS=0 or the lab's knob
   noexcess, read the way the other switches are (on unless 0); the switch has its docs row.

    python -I -B tests/test_evict_excess.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

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


FIXTURE = r'''#include <cstdint>
#include <cstdio>
#include "vram_compact.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace vram_compact;
int main() {
    const uint64_t MB = 1ull << 20;
    // (the Market entered from Hyrule Field, an 8 GB card: 62 MB over the 90% line)
    const uint64_t total = 2873 * MB, size = 3285 * MB, rule = 2811 * MB;
    CHECK(total - rule_target(total, size, rule) == 126 * MB);
    CHECK(total - rule_target(total, rule) == total - rule / 8 * 7);   // (the old form: 413 MB)
    CHECK(total - rule / 8 * 7 > 413 * MB - MB && total - rule / 8 * 7 < 414 * MB);
    // (under every line: nothing; the size alone: 7/8 of it, as the old form; both: the lower)
    CHECK(rule_target(rule, size, rule) == UINT64_MAX && rule_target(size, size, size) == UINT64_MAX);
    CHECK(rule_target(3500 * MB, size, size) == rule_target(3500 * MB, size));
    CHECK(rule_target(3500 * MB, size, 3000 * MB) == size / 8 * 7);
    CHECK(rule_target(3500 * MB, size, 2600 * MB) == 2600 * MB - 64 * MB);
    CHECK(rule_target(3500 * MB, size, 10 * MB) == 0 && rule_target(3500 * MB, size, 0) == 0);
    std::printf("OK\n");
    return 0;
}
'''


def check_source(tex, dev):
    frame = block(tex, "void texture_frame(uint64_t completed)")
    order = ["if (press.live) budget = tex_pressure::budget(", "const uint64_t size_budget = budget;",
             "if (known && pressure > allowed / 10 * 9) {", "uint64_t rule_budget = budget;",
             "rule_budget = std::min(rule_budget, total_bytes > over ? total_bytes - over : 0);",
             "const uint64_t rule_to = ", "texture_sweep(completed, "]
    at = -1
    for needle in order:
        i = frame.find(needle, at + 1)
        if i < 0:
            fail("texture_frame: %r missing or out of order (the size after the live line and before the 90%% rule, the "
                 "rules' budget after both rules, rule_to after them)" % needle)
        at = i
    rule = frame[frame.index("const uint64_t rule_to = "):]
    rule = rule[:rule.index(";\n") + 1]
    if "vram_compact::rule_target(total_bytes, size_budget, rule_budget)" not in rule or \
            "vram_compact::rule_target(total_bytes, rule_budget)" not in rule:
        fail("rule_to is not the three-argument rule with the old form for the switch off")
    if 'lab_ab::on("noexcess")' not in rule:
        fail("the lab's knob noexcess does not turn the rule back")
    env = frame[frame.index('getenv("RX_VK_EVICT_EXCESS")') - 120:frame.index("const uint64_t rule_to = ")]
    if "return !e || atoi(e) != 0;" not in env:
        fail("RX_VK_EVICT_EXCESS is not on unless 0")
    if "`RX_VK_EVICT_EXCESS=0`" not in dev:
        fail("docs/development.md has no RX_VK_EVICT_EXCESS row")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    vk = ROOT / "gpu" / "vk"
    tex = (vk / "vk_texture.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    try:
        check_source(tex, dev)
    except ValueError as e:
        fail("a text this test reads moved (%s)" % e)
    with tempfile.TemporaryDirectory(prefix="evict-excess-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(FIXTURE, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(vk), str(cpp), "-o", str(exe)],
                               capture_output=True, text=True)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        if done.returncode or done.stdout.strip() != "OK":
            fail("the rule: " + (done.stdout + done.stderr).strip())
    print("PASS: the 90% and 97% rules go down to their budget less 64 MB, the size to 7/8 of it; RX_VK_EVICT_EXCESS=0 and "
          "noexcess as before")


if __name__ == "__main__":
    main()
