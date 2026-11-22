"""No uniform updates written at a part's end on Intel's GPUs without mirrors (gpu/vk/barrier_rules.h; no game, no GPU).

(Triforce, 11-22, the performance audit's REPLAY-14, after Source A's.) A split submission wrote its uniform updates
into the game's memory at every part's end. Without mirrors that memory is what later parts' other reads and the game's
CPU see, mid-submission, where an unsplit submission writes them once at its end: white blocks and flashes on Intel's
integrated GPUs. There only the submission's last part writes them now.

Compiles a small driver against the header and checks the vendor and mirror table with the switch unset and forced:
  unset   Intel without mirrors: off; Intel with mirrors (an Arc card): on; NVIDIA and AMD, with or without mirrors: on;
  0       off with any vendor, mirrors or not;   1: on with any vendor, mirrors or not;   empty: unset.

And reads gpu/vk/vk_replay.cpp: maybe_split writes the updates and moves ub_first_of_recording only where the rule is on,
in the place they were; split_rules reads the switch once with the vendor and pools_mirrored(); a whole recording's
end still writes them without asking (the last part's write); and the docs row.

    python -I -B tests/test_split_ub_flush.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include <cstdint>
#include <cstddef>
#include "barrier_rules.h"
#include <cstdio>
#include <initializer_list>

using namespace mkwvk::barrier_rules;
static int checks, fails;
static void want(const char* what, bool got, bool wanted) {
    checks++;
    if (got != wanted) fails++, printf("FAIL %s: %d, want %d\n", what, (int)got, (int)wanted);
}

int main() {
    const uint32_t intel = 0x8086, nvidia = 0x10DE, amd = 0x1002;
    want("unset, Intel without mirrors", split_ub_flush(nullptr, intel, false), false);
    want("unset, Intel with mirrors", split_ub_flush(nullptr, intel, true), true);
    want("empty is unset, Intel without mirrors", split_ub_flush("", intel, false), false);
    for (const uint32_t v : {nvidia, amd})
        for (int mirrors = 0; mirrors < 2; mirrors++) {
            want("unset, another vendor: as before", split_ub_flush(nullptr, v, mirrors != 0), true);
            want("empty, another vendor: as before", split_ub_flush("", v, mirrors != 0), true);
        }
    for (const uint32_t v : {intel, nvidia, amd})
        for (int mirrors = 0; mirrors < 2; mirrors++) {
            want("0: off with any vendor", split_ub_flush("0", v, mirrors != 0), false);
            want("1: on with any vendor", split_ub_flush("1", v, mirrors != 0), true);
        }
    if (fails) printf("split ub flush: FAILED (%d of %d checks)\n", fails, checks);
    else printf("split ub flush: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def block(src, start):
    at = src.index(start)
    return src[at:src.index("\n}\n", at)]


def check_source():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    split = block(replay, "void maybe_split(VkCommandBuffer& cmd) {")
    order = [split.find(n) for n in (
        "const uint64_t ended = work_between();", "if (split_ub_flush_on()) flush_ub_updates(cmd);", "texture_end_recording(cmd);",
        "memory_end_submission(cmd);", "submit_recording(*rec_cur, false, 0, true);",
        "if (split_ub_flush_on()) ub_first_of_recording = ub_updates.size();", "Recording& r = begin_recording(rec_cur_value);")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("maybe_split does not write a part's uniform updates, and move its first one, only where the rule is on")
    if split.count("flush_ub_updates(cmd);") != 1 or split.count("ub_first_of_recording = ub_updates.size();") != 1:
        raise SystemExit("maybe_split writes the uniform updates, or moves their first, in a place that does not ask the rule")
    rules = block(replay, "bool split_rules(int which) {")
    if 'barrier_rules::split_ub_flush(getenv("RX_VK_SPLIT_UBFLUSH"), dev.props.vendorID, pools_mirrored());' not in rules or \
            "static const bool ub_flush = [] {" not in rules:
        raise SystemExit("split_rules does not read RX_VK_SPLIT_UBFLUSH with the vendor and the mirrors, once")
    # a whole recording's end writes them whatever the rule: the submission's last part
    if replay.count("    flush_ub_updates(r.cmd);\n") < 2:
        raise SystemExit("a recording's end no longer writes its uniform updates: with the rule off nothing would write them")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `RX_VK_SPLIT_UBFLUSH=0` or `1` |" not in docs:
        raise SystemExit("docs/development.md: the switches table has no row for RX_VK_SPLIT_UBFLUSH")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="split-ub-") as tmp:
        cpp, exe = Path(tmp) / "split_ub_test.cpp", Path(tmp) / "split-ub.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the uniform flush rule's checks failed")


if __name__ == "__main__":
    main()
