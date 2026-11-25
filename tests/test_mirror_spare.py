"""What the mirrors' sparse buffers cost is counted (gpu/vk/mirror_spare.h, vk_memory.cpp reap_mirrors and mirror_make;
no game, no GPU).

(Triforce, 11-21, the performance audit's MEM-27, its first step, after Source A's.) A mirror in pieces is a sparse
buffer, and the driver charges by its size to create and to destroy it; the game frees its pools at an area change and
makes them again at the same sizes. Before freed buffers are kept for the next mirror of their size, this counts what
that would save.

This compiles mirror_spare.h alone and checks the count: creates and destroys with their time, bytes and longest call;
calls over 4 ms; a create is "servable" only when a buffer of exactly its size was freed before it and not matched by an
earlier create, so two creates of one freed size count one.

And reads the source: the sparse buffer's destroy and create are timed and counted, the destroy with the pool's span
kept when the mirror was handed to the reaper (the pool's own fields are cleared by then), and the 1200-submission line
has the counts.

    python -I -B tests/test_mirror_spare.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include "mirror_spare.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main() {
    using namespace mirror_spare;
    const uint64_t MB = 1ull << 20;
    Counts c;
    CHECK(!created(c, 64 * MB, 3.5));                    // (the first of its size: nothing freed yet)
    CHECK(!created(c, 256 * MB, 15.0));
    CHECK(c.creates == 2 && c.servable == 0 && c.over == 1 && c.longest_create_ms == 15.0 && c.create_bytes == 320 * MB);
    destroyed(c, 64 * MB, 4.5);
    destroyed(c, 256 * MB, 18.0);
    CHECK(c.destroys == 2 && c.over == 3 && c.longest_destroy_ms == 18.0 && c.destroy_ms == 22.5 && c.destroy_bytes == 320 * MB);
    CHECK(created(c, 64 * MB, 3.0));                     // (an area change later: the same size again)
    CHECK(!created(c, 64 * MB, 3.0));                    // (one freed buffer serves one create)
    CHECK(!created(c, 128 * MB, 6.0));                   // (another size: not served by the 256 MB one)
    CHECK(created(c, 256 * MB, 14.0));
    CHECK(c.creates == 6 && c.servable == 2 && c.freed.empty());
    destroyed(c, 64 * MB, 1.0), destroyed(c, 64 * MB, 1.0);
    CHECK(created(c, 64 * MB, 1.0) && created(c, 64 * MB, 1.0) && !created(c, 64 * MB, 1.0) && c.servable == 4);
    CHECK(kLongMs == 4.0);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    check('#include "mirror_spare.h"' in mem, "vk_memory.cpp does not use the count")
    reap = block(mem, "void reap_mirrors() {")
    at = [reap.index(p) for p in ("const auto destroy_t0 = std::chrono::steady_clock::now();",
                                  "vkDestroyBuffer(dev.device, dead_mirrors.front().buffer, nullptr);",
                                  "mirror_spare::destroyed(sparse_ct, dead_mirrors.front().sparse_bytes, sparse_ms_since(destroy_t0));",
                                  "vma_piece_free(a);")]
    check(at == sorted(at), "the sparse buffer's destroy is not timed around the call alone, or not counted with its size")
    check("uint64_t sparse_bytes = 0;" in mem and "p.mpieces ? p.hi - p.lo : 0});" in mem,
          "the mirror's span is not kept for the reaper: the pool's own fields are cleared by then")
    free = block(mem, "void mirror_free(Pool& p) {")
    check(free.index("dead_mirrors.push_back(") < free.index("p.mpieces = false"), "the span is read after the pool's mirror state is cleared")
    make = block(mem, "bool mirror_make(Pool& pool) {")
    at = [make.index(p) for p in ("const auto create_t0 = std::chrono::steady_clock::now();",
                                  "sparse_made = vkCreateBuffer(dev.device, &bi, nullptr, &sb);",
                                  "mirror_spare::created(sparse_ct, n, sparse_ms_since(create_t0));")]
    check(at == sorted(at), "the sparse buffer's create is not timed around the call alone, or not counted")
    check("vk: mirrors' sparse buffers so far: %llu made" in mem and "of the creates had a freed" in mem, "the counts are not in the log")

    with tempfile.TemporaryDirectory(prefix="mirror-spare-") as tmp:
        c, exe = Path(tmp) / "spare.cpp", Path(tmp) / "spare.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the count as made:\n" + r.stdout)
    print("PASS: the mirrors' sparse buffers' creates and destroys are timed, and the creates a freed buffer could serve counted")


if __name__ == "__main__":
    main()
