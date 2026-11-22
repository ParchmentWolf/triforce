"""Compile and run the rule for the cards that keep every large ASTC texture as BC3 (gpu/vk/astc_bc_policy.h; no game/GPU)."""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def check_source():
    """The texture setup still asks the rule, and the switch that overrides it is still read"""
    src = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    # ((Triforce, 11-22, the performance audit's TEX-12) the rule is asked with the card's type; an unknown allowance is 0
    for needle in ('#include "astc_bc_policy.h"', "astc_bc_policy::all(allowed, integrated)", 'getenv("RX_VK_ASTC_BC_ALL")',
                   "(bw * bh >= 36 || all) ? low : 64ull << 20",
                   "if (!vram_usage(&used, &allowed)) allowed = 0;",
                   "const bool integrated = dev.props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;\n"
                   "            const bool small = astc_bc_policy::all(allowed, integrated);",
                   "if (const char* e = getenv(\"RX_VK_ASTC_BC_ALL\")) return e[0] == '1';\n            uint64_t used = 0, allowed = 0;"):
        if needle not in src:
            raise SystemExit("vk_texture.cpp no longer has: " + needle)
    if "astc_bc_policy::all_by_vram(" in src:
        raise SystemExit("vk_texture.cpp still asks the rule by the allowance alone: an integrated GPU allowed 8.5 GB or more is missed")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `RX_VK_ASTC_BC_ALL=1` or `0` |" not in docs:
        raise SystemExit("docs/development.md: RX_VK_ASTC_BC_ALL is not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="astc-bc-policy-") as tmp:
        exe = Path(tmp) / "astc-bc-policy"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_astc_bc_policy.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
