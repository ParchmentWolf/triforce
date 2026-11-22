"""Compile and run the rule for which parts of a written binding go back to guest memory while the capture leaves memory out
(gpu/vk/wb_excl_clip.h, RX_VK_WB_EXCL_CLIP; no game/GPU), and check that gpu_buffer_bind still uses it."""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_source():
    """gpu_buffer_bind clips its write-backs through the rule, behind the switch, and the docs name the switch"""
    src = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    for needle in ('#include "wb_excl_clip.h"', 'wb_excl_clip::on(getenv("RX_VK_WB_EXCL_CLIP"), cap_only_gpu())',
                   "return wb_excl_clip::kept(lo, hi, mine, out);",
                   "if (excl_clip && cap_excl_hit(p->lo + off, p->lo + wb_end)) {",
                   "for (const auto& [a, b] : parts) writebacks.push_back({p, a - p->lo, b - p->lo, tl_event_write});"):
        if needle not in src:
            raise SystemExit("vk_memory.cpp no longer has: " + needle)
    bind = src[src.index("BufferRef gpu_buffer_bind(uint64_t gpu, uint64_t size, bool written) {"):]
    bind = bind[:bind.index("\n}\n")]
    # (the one write-back of a written binding: the clipped parts, or the whole range when nothing of it is left out)
    if bind.count("writebacks.push_back(") != 2:
        raise SystemExit("gpu_buffer_bind queues a write-back outside the clip")
    # (the collection still leaves the same memory unstamped: the reason the mirror's copy there is stale)
    if "if (only_gpu && cap_excl_page(guest)) continue;" not in src:
        raise SystemExit("memory_collect_written's left-out pages changed: recheck wb_excl_clip.h")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "RX_VK_WB_EXCL_CLIP=0" not in docs:
        raise SystemExit("docs/development.md does not name RX_VK_WB_EXCL_CLIP")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="wb-excl-clip-") as tmp:
        exe = Path(tmp) / "wb-excl-clip"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_wb_excl_clip.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
