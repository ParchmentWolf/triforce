"""The size of a submission's parts: RX_VK_CHUNK, the lab's knob, the driver's default (gpu/vk/barrier_rules.h part_draws,
vk_replay.cpp part_draws and maybe_split; no game, no GPU).

(Triforce, 11-22, the performance audit's SYNC-66, after Source B's.) A long submission goes to the GPU in parts of 120 draws
and dispatches on every card, read once into a static of maybe_split, so nothing could compare sizes inside a run. The size is
now RX_VK_CHUNK when set, else the RX_VK_LAB_AB knob chunk:<n> in its phases, else the driver's default: 120 for every driver
until the lab picks one.

Compiles a driver against barrier_rules.h and lab_ab.h and checks:
  the default is 120 for NVIDIA, AMD, Intel and any other vendor, with RADV or not;
  with no knob the size is what the old read gave, for 100,000 random texts of the variable (unset, 0, 120, negative, words,
  any number) on random vendors: the default path splits where it split;
  RX_VK_CHUNK beats the knob and the default; 0 stays 0 (never split); the knob beats the default only in its own phases
  (lab_ab.h's value_of with the phase's knob set, another knob's phase, and no phase).
And reads vk_replay.cpp: maybe_split has no static size and asks part_draws() at each call, still returns for a size of 0 or
less and still counts ++part_work against it after the tail's test; part_draws reads the variable once and the knob at each
call; the switches table has the row and no longer says the in-pass split is on with NVIDIA's driver.

    python -I -B tests/test_chunk_default.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "barrier_rules.h"
#include "lab_ab.h"
#include <cstdio>

namespace br = mkwvk::barrier_rules;
namespace lab = mkwvk::lab_ab;
static int checks, fails;
#define CHECK(what, cond) do { checks++; if (!(cond)) fails++, printf("FAIL %s (line %d)\n", what, __LINE__); } while (0)

int main() {
    static const uint32_t kVendors[] = {0x10de, 0x1002, 0x8086, 0x5143, 0x13b5, 0, 0xffffffffu};
    for (const uint32_t v : kVendors)
        for (int radv = 0; radv < 2; radv++) CHECK("120 for every driver until the lab picks", br::part_draws_default(v, radv != 0) == 120);
    CHECK("the constant", br::kPartDraws == 120);

    // with no knob: the old read, whatever the variable says
    uint64_t rng = 0xD1B54A32D192ED03ull;
    const auto rnd = [&](uint64_t n) { rng ^= rng << 13, rng ^= rng >> 7, rng ^= rng << 17; return rng % n; };
    static const char* const kTexts[] = {nullptr, "", "0", "120", "480", "4096", "-5", "junk", "12x", " 64", "1", "999999999999"};
    for (int i = 0; i < 100000; i++) {
        char num[32];
        const char* env = kTexts[rnd(sizeof kTexts / sizeof *kTexts)];
        if (rnd(3) == 0) snprintf(num, sizeof num, "%lld", (long long)rnd(5000) - 500), env = num;
        const uint32_t vendor = kVendors[rnd(sizeof kVendors / sizeof *kVendors)];
        const int64_t now = br::part_draws(env != nullptr, env ? atoll(env) : 0, br::part_draws_default(vendor, rnd(2) != 0));
        CHECK("with no knob the size is the old read's", now == br::part_draws_before(env));
        if (fails) break;
    }
    CHECK("unset: 120", br::part_draws(false, 0, br::part_draws_default(0x10de, false)) == 120);
    CHECK("RX_VK_CHUNK beats the knob", br::part_draws(true, 240, 480) == 240);
    CHECK("RX_VK_CHUNK=0 stays 0 under a knob", br::part_draws(true, 0, 480) == 0);
    CHECK("the knob beats the default", br::part_draws(false, 0, 480) == 480);

    // the knob through lab_ab.h, as vk_replay.cpp's part_draws asks it: only in its own phases
    CHECK("no RX_VK_LAB_AB: the default", (lab::n_knobs = 0, lab::value_of("chunk", 120)) == 120);
    lab::n_knobs = 2;
    snprintf(lab::knobs[0].name, sizeof lab::knobs[0].name, "chunk"), lab::knobs[0].value = 480;
    snprintf(lab::knobs[1].name, sizeof lab::knobs[1].name, "rblate"), lab::knobs[1].value = 1;
    lab::active.store(0);
    CHECK("a phase with no knob: the default", br::part_draws(false, 0, lab::value_of("chunk", 120)) == 120);
    lab::active.store(1);
    CHECK("the knob's phase: its number", br::part_draws(false, 0, lab::value_of("chunk", 120)) == 480);
    CHECK("the knob's phase, the variable set: the variable", br::part_draws(true, 120, lab::value_of("chunk", 120)) == 120);
    lab::active.store(2);
    CHECK("another knob's phase: the default", br::part_draws(false, 0, lab::value_of("chunk", 120)) == 120);

    if (fails) printf("chunk default: FAILED (%d of %d checks)\n", fails, checks);
    else printf("chunk default: all %d checks passed\n", checks);
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
    split = function(replay, "void maybe_split(VkCommandBuffer& cmd) {")
    check("static const int64_t every" not in replay, "maybe_split still reads the size once into a static")
    check(split.startswith("void maybe_split(VkCommandBuffer& cmd) {\n    const int64_t every = part_draws();\n"),
          "maybe_split does not ask part_draws() at each call")
    check('getenv("RX_VK_CHUNK")' not in split, "maybe_split reads RX_VK_CHUNK itself")
    check("if (tail_on()) return;" in split and
          "if (!rec_cur || every <= 0 || ++part_work < every || rec_parts + 1 >= kMaxParts || dump_on()) return;" in split and
          split.index("if (tail_on()) return;") < split.index("++part_work < every"),
          "maybe_split's test changed: a size of 0 or less must never split, and the count comes after the tail's test")
    part = function(replay, "int64_t part_draws() {")
    check('static const char* const env = getenv("RX_VK_CHUNK");' in part and "static const int64_t env_value = env ? atoll(env) : 0;" in part,
          "part_draws does not read RX_VK_CHUNK once")
    check("barrier_rules::part_draws_default(dev.props.vendorID, radv);" in part, "the default is not asked of the rule with the driver")
    check(part.rstrip().endswith('return barrier_rules::part_draws(env != nullptr, env_value, lab_ab::value_of("chunk", by_driver));'),
          "part_draws does not ask the knob at each call, behind the variable")
    # ((Triforce) and once by Threaded rendering's parts, only to step aside when it is set: pass_end_parts)
    ends = function(replay, "PassEndParts& pass_end_parts() {")
    check(replay.count('getenv("RX_VK_CHUNK")') == 2 and ends.count('getenv("RX_VK_CHUNK")') == 1, "RX_VK_CHUNK is read somewhere else")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    row = [line for line in dev.splitlines() if line.startswith("| `RX_VK_CHUNK=<n>` |")]
    check(len(row) == 1 and "**120 on every driver**" in row[0] and "`chunk:<n>`" in row[0], "docs/development.md: no row for RX_VK_CHUNK with its default")
    check("Unset: `pass` with NVIDIA's driver" not in dev, "docs/development.md still says the in-pass split is on with NVIDIA's driver")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="chunk-default-") as tmp:
        src = Path(tmp) / "driver.cpp"
        src.write_text(DRIVER, encoding="utf-8")
        exe = Path(tmp) / "driver.exe"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu/vk"), str(src), "-o", str(exe)],
                       check=True)
        out = subprocess.run([str(exe)], capture_output=True, text=True)
        print(out.stdout, end="")
        check(out.returncode == 0, "the rule's checks failed")
    print("PASS: a part's size: RX_VK_CHUNK, then the lab knob, then the driver's default, 120 for each")


if __name__ == "__main__":
    main()
