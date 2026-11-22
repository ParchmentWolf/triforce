"""On Intel's GPUs the shader preparation's translation pass builds only the compute pipelines play dispatches.

The pass (gpu/vk/vk_draw.cpp prepare_run) had the driver compile every compute program's texture variants, 9681 pipelines
on an Arc A750: 5175 s of its 5858 s pass (an RTX 4070 SUPER takes 170 s for the whole pass), where play dispatched 166
programs (920 pipelines), which the precompile builds from triforce_computes.bin anyway.

What must hold: gpu/vk/warm_computes.h's rule (compiled and run here, no game or GPU): listed only on Intel unless
RX_VK_WARM_COMPUTES says listed or all; with listed, every one while there is no list, else the listed ones. And
vk_draw.cpp: prepare_run's warm_compute asks the rule with the list computes_read gives, before the carry's note and the
build, and says what it left; the switch is in docs/development.md.

python -I -B tests/test_warm_computes.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit(where + " no longer has: " + needle)


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need("vk_draw.cpp", draw, ['#include "warm_computes.h"'])
    start = draw.index("bool prepare_run(void (*progress)(size_t done, size_t total), bool background) {")
    prepare = draw[start:draw.index("\n}\n", start)]
    need("vk_draw.cpp: prepare_run()", prepare,
         ['warm_computes::listed_only(getenv("RX_VK_WARM_COMPUTES"), dev.props.vendorID)',
          "cs_listed_only ? computes_read() : std::unordered_set<uint64_t>{}",
          "warm_computes::build(cs_listed_only, cs_listed.empty(), cs_listed.count(p.key) != 0)",
          "vk: the preparation left %zu compute variants"])
    warm = prepare[prepare.index("const auto warm_compute = [&](Program& p) {"):]
    warm = warm[:warm.index("};")]
    # (left before the carry's note, so that the carry's rebuild builds the same ones, and before the build)
    order = [warm.index(s) for s in ("warm_computes::build(", "prepare_cs_keys.insert(p.key);", "prepare_compute_pipeline(p)")]
    if order != sorted(order):
        raise SystemExit("vk_draw.cpp: warm_compute asks the rule after the carry's note or the build")
    if "const bool cs_listed_only = warm_cs &&" not in prepare:
        raise SystemExit("vk_draw.cpp: the list is read with no compute pipelines to build (behind the game, RX_VK_NO_WARM)")
    need("docs/development.md", (ROOT / "docs/development.md").read_text(encoding="utf-8"),
         ["`RX_VK_WARM_COMPUTES=listed` or `all`"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="warm-computes-") as tmp:
        exe = Path(tmp) / "warm-computes"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_warm_computes.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
