"""The guest page table's changes of a recording streamed into transfers of at most 64 KiB, without a pair for every page
and a sort (gpu/vk/table_stream.h, vk_memory.cpp memory_table_flush; no game, no GPU).

(Triforce, 11-22, the performance audit's SYNC-04, after Source A's.) The flush made a (page, value) pair for every page
of every change of the recording, sorted them and kept the last of each page: 16 bytes a page and a sort on the recording
thread, for ranges of hundreds of MB when a pool is imported ahead or merged.

tests/page_table_stream_test.cpp gets vk_memory.cpp's own table code (TableRun to memory_table_flush, the span
tests/test_parallel_fixes.py cuts) and runs the flush both ways on the same changes, the streamed one and the sort as it
was (table_flush_sorted, RX_VK_TABLE_STREAM=0's):
  - 50 trials of 128 random runs that overlap in any order, 50 of runs in page order and apart (the path without the
    sweep), the same with two swapped and one repeated, 256 single pages, the empty cases: the two write the SAME
    transfers, entry for entry and in the same order; the table they leave is the last writer's of every page; no
    transfer is over 64 KiB; pages come ascending, none twice;
  - four overlapping ranges over 150,000 pages: the streamed flush's largest allocation is at most 128 KiB, the sorted
    one's is over 2 MB (so the count means something), and with RX_VK_TABLE_STREAM=0 memory_table_flush is the sorted one.

And reads the source: the switch, read once and on unless 0; the old flush kept whole; the switches table.

    python -I -B tests/test_page_table_stream.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    check((VK / "table_stream.h").exists(), "gpu/vk/table_stream.h is missing")
    check('#include "table_stream.h"' in mem, "vk_memory.cpp does not include table_stream.h")
    start = mem.index("struct TableRun {")
    flush_at = mem.index("bool memory_table_flush() {", start)
    table = mem[start:mem.index("\n}\n", flush_at) + 3]
    flush = table[table.index("bool memory_table_flush() {"):]

    check("bool table_flush_sorted() {" in table and table.index("bool table_flush_sorted() {") < table.index("bool memory_table_flush() {"),
          "the flush as it was is not kept, before memory_table_flush, in the span the tests cut")
    order = [flush.find(s) for s in (
        "table_defer = false;", "if (table_pending.empty()) return false;", "if (!table_stream_on()) return table_flush_sorted();",
        "VkCommandBuffer cmd = upload_command_buffer();", 'GprofSpan gp(cmd, "ptable update (guest page table)");', "gp.items = 0;",
        "static thread_local table_stream::Scratch scratch;",
        "table_stream::stream(table_pending.data(), table_pending.size(), scratch,",
        "vkCmdUpdateBuffer(cmd, guest_pages_buffer, first * 8, n * 8, values), gp.items++, gp.bytes += n * 8;",
        "table_pending.clear();", "if (ms > 1.0 &&", "return true;")]
    check(min(order) >= 0 and order == sorted(order), "memory_table_flush: the switch, the span, the stream and its counts are not there in that order")
    check("stable_sort" not in flush and "push_back" not in flush, "memory_table_flush still expands or sorts the pages itself")
    old = table[table.index("bool table_flush_sorted() {"):table.index("bool memory_table_flush() {")]
    for s in ("for (uint64_t i = 0; i < r.count; i++) pages.push_back({r.first + i, r.address ? r.address + (i << 12) : 0});",
              "table_pending.clear();", "std::stable_sort(pages.begin(), pages.end(), [](const auto& a, const auto& b) { return a.first < b.first; });",
              "if (i + 1 < pages.size() && pages[i + 1].first == pages[i].first) continue;",
              "if (!run.empty() && (pages[i].first != run_first + run.size() || run.size() == 8192)) emit();"):
        check(s in old, "the flush as it was lost %r" % s)
    on = table[table.index("bool table_stream_on() {"):table.index("bool table_flush_sorted() {")]
    check('getenv("RX_VK_TABLE_STREAM")' in on and "!(e && *e && atoi(e) == 0)" in on and "static const bool on" in on,
          "RX_VK_TABLE_STREAM is not on unless set to 0, or is read more than once")
    check("RX_VK_TABLE_NOW" in table, "RX_VK_TABLE_NOW is gone")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_TABLE_STREAM=0`" in dev, "docs/development.md: RX_VK_TABLE_STREAM=0 is not in the switches table")

    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="page-table-stream-") as tmp:
        src, exe = Path(tmp) / "stream.cpp", Path(tmp) / "stream.exe"
        src.write_text((ROOT / "tests" / "page_table_stream_test.cpp").read_text(encoding="utf-8").replace("/* ACTUAL */", table), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-I" + str(VK), str(src), "-o", str(exe)], check=True)

        def case(name, extra=None):
            r = subprocess.run([str(exe), name], env=dict(env, **(extra or {})), capture_output=True, text=True, timeout=300)
            check(r.returncode == 0, "%s:\n%s" % (name, r.stdout + r.stderr))
            return r.stdout.strip().splitlines()

        print(case("random")[-1])
        largest = {}
        for name, extra in (("four", None), ("four-sorted", None), ("four", {"RX_VK_TABLE_STREAM": "0"})):
            line = [l for l in case(name, extra) if l.startswith("largest ")]
            check(len(line) == 1, "%s did not say its largest allocation" % name)
            largest[(name, bool(extra))] = int(line[0].split()[1])
        streamed, sorted_, off = largest[("four", False)], largest[("four-sorted", False)], largest[("four", True)]
        print("four ranges over 150,000 pages: the largest allocation %d bytes streamed, %d sorted, %d with RX_VK_TABLE_STREAM=0"
              % (streamed, sorted_, off))
        check(0 < streamed <= 128 << 10, "the streamed flush allocated %d bytes at once: over 128 KiB" % streamed)
        check(sorted_ > 2 << 20, "the sorted flush's allocation was not counted (%d bytes): the limit above means nothing" % sorted_)
        check(off > 2 << 20, "RX_VK_TABLE_STREAM=0 does not bring the sorted flush back")
    print("PASS: the page table's changes are streamed into the transfers the sort made, in 64 KiB of scratch")


if __name__ == "__main__":
    main()
