"""(Triforce, RX_VK_SPARSE_SPARE_MB) gpu/vk/sparse_spare.h's list of the freed mirrors' sparse buffers kept for the next mirror
of their size: compiled and run (what a size takes, the cap, which spares go for a new one), and vk_memory.cpp read for the
rules around it: a kept buffer is unbound before it is kept and its pieces' memory is freed only once that is done; a taken
spare's buffer is never destroyed at once; the binds' flush waits for a taken spare's unbinding. Run with --cxx clang++ or g++."""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from srccut import block

RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check_source():
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    cap = block(mem, "uint64_t sparse_spare_cap() {")
    for n in ('getenv("RX_VK_SPARSE_SPARE_MB")', "sparse_spare::kDefaultMb", "sparseAddressSpaceSize / 4"):
        assert n in cap, n
    reap = block(mem, "void reap_mirrors() {")
    keep = reap[reap.index("if (!keep.empty()) {"):]
    assert "sparse_unbind(infos, &after)" in keep
    kept = keep[keep.index("std::vector<VmaAllocation> pieces;"):]
    assert "vma_piece_free(" not in kept and "vkDestroyBuffer(" not in kept, "a kept buffer's memory freed or the buffer destroyed before its unbinding is done"
    assert "spare_frees.push_back({after, std::move(pieces)})" in kept
    make = block(mem, "bool mirror_make(Pool& pool) {")
    assert "sparse_spares.take(n, &spare)" in make
    assert "sparse_spare_doom(sb, spare.after)" in make
    flush = block(mem, "void memory_mirror_binds_flush() {")
    assert "spare_after_max.load(" in flush and "pWaitSemaphoreValues = &spare_after" in flush


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="sparse-spare-") as tmp:
        exe = Path(tmp) / "sparse-spare.exe"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests/test_sparse_spare.cpp"), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
