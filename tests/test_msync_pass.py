"""A mirror sync's pages from the captures go by one compute dispatch, in order with the copies (gpu/vk/msync_pass.h,
vk_memory.cpp; no game, no GPU).

(Triforce, 11-21, the performance audit's MEM-48, after Source A's.) A sync copied the pages that come from a capture's
buffer into the pool's VRAM mirror as copy regions, a page or a few each, 700 to 1,300 a frame. The write-back diff's
pass is a copy when its shadow is its destination, so a sync's regions go as that pass's chunks in one dispatch.

This compiles msync_pass.h with wbd_split cut out of vk_memory.cpp and checks: the switch (NVIDIA when not set); which
runs go as chunks; that the chunks of runs, applied as the shader applies them, leave the destination as plain copies
would, byte for byte and nothing else touched, for addresses alike within 16 bytes and not; a vector chunk's addresses
on 16 bytes and no chunk past 64 KB; the table ring (a table from an atom of its own at atoms 64, 128 and 256, a block
not taken again while the GPU still reads it, a table too big refused); the barrier's rule.

And reads the source: the capture buffers are made with the pass's usage; mirror_sync adds, flushes ahead of the live
runs and notes its copies; the flush writes and flushes the table before its dispatch, marks a checkpoint and notes the
pass; every copy into a mirror in the uploads is noted for the barrier; the checkpoint kind and the switches row.

    python -I -B tests/test_msync_pass.py [--cxx clang++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, head):
    at = text.index(head)
    return text[at:text.index("\n}\n", at) + 3]


def in_order(text, parts, why):
    at = 0
    for p in parts:   # (each after the one before it: a part may be there more than once)
        at = text.find(p, at)
        check(at >= 0, why + " (missing, or out of order: " + p + ")")
        at += len(p)


PROGRAM = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include "msync_pass.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
// (vk_memory.cpp's own, cut out by the test)
@WBD_SPLIT@
struct Chunk { uint64_t src, dst; uint32_t count; bool vecs; };
static uint32_t rnd_state = 12345;
static uint32_t rnd() { return rnd_state = rnd_state * 1664525u + 1013904223u; }

// Runs (source offset, destination offset, size) between a source at src_base and a destination at dst_base, as chunks and
// as copies: the same bytes
static void copies_alike(uint64_t src_base, uint64_t dst_base, const std::vector<uint64_t>& runs) {
    const size_t n = 1u << 20;
    std::vector<uint8_t> src(n), want(n), got(n);
    for (size_t i = 0; i < n; i++) src[i] = (uint8_t)rnd(), want[i] = got[i] = (uint8_t)rnd();
    std::vector<Chunk> chunks;
    for (size_t i = 0; i + 2 < runs.size() + 0 && i < runs.size(); i += 3) {
        const uint64_t so = runs[i], d0 = runs[i + 1], size = runs[i + 2];
        CHECK(msync_pass::words(src_base + so, dst_base + d0, size));
        std::memcpy(&want[d0], &src[so], size);
        uint64_t bytes = 0;
        msync_pass::run_chunks(src_base + so, dst_base + d0, size,
                               [](uint64_t at, uint64_t sz, auto&& e) { wbd_split(at, sz, e); },
                               [&](uint64_t s, uint64_t d, uint32_t count, bool vecs) {
                                   chunks.push_back({s, d, count, vecs});
                                   bytes += (uint64_t)count * (vecs ? 16 : 4);
                               });
        CHECK(bytes == size);
    }
    for (const Chunk& c : chunks) {
        const uint64_t bytes = (uint64_t)c.count * (c.vecs ? 16 : 4);
        CHECK(c.count != 0 && bytes <= msync_pass::kChunkBytes);
        if (c.vecs) CHECK(!(c.src & 15) && !(c.dst & 15));
        else CHECK(!(c.src & 3) && !(c.dst & 3));
        CHECK(c.src >= src_base && c.src + bytes <= src_base + n && c.dst >= dst_base && c.dst + bytes <= dst_base + n);
        // (the shader: a vector or a word written where it differs, the source's value: a copy)
        const uint32_t step = c.vecs ? 16 : 4;
        for (uint32_t i = 0; i < c.count; i++) {
            const uint8_t *s = &src[c.src - src_base + (uint64_t)i * step];
            uint8_t* d = &got[c.dst - dst_base + (uint64_t)i * step];
            if (std::memcmp(s, d, step)) std::memcpy(d, s, step);
        }
    }
    CHECK(got == want);
}

int main() {
    using namespace msync_pass;
    CHECK(on(nullptr, true) && !on(nullptr, false) && on("", true) && !on("", false));
    CHECK(on("1", false) && on("1", true) && !on("0", true) && !on("0", false));
    CHECK(words(0x1000, 0x2000, 4096) && words(0x1004, 0x2008, 4));
    CHECK(!words(0x1000, 0x2000, 0) && !words(0x1001, 0x2000, 4096) && !words(0x1000, 0x2002, 4096) && !words(0x1000, 0x2000, 4094));

    // whole pages, both bases on 16 bytes; pages of a mirror whose base is 8 off the source's; odd word runs
    copies_alike(0x10000000, 0x20000000, {0, 0x3000, 4096, 0x1000, 0x8000, 3 * 4096, 0x40000, 0x80000, 5 * 65536 + 4096});
    copies_alike(0x10000000, 0x20000008, {0, 0x3000, 4096, 0x1000, 0x8000, 3 * 4096, 0x40000, 0x80000, 2 * 65536 + 4096});
    copies_alike(0x10000004, 0x20000004, {4, 0x3004, 4096, 0x100c, 0x800c, 40, 0x2000, 0x9000, 4, 0x4008, 0xa008, 65536 + 24});
    copies_alike(0x10000000, 0x20000000, {0x10, 0x3004, 4096 + 8, 0x40004, 0x80008, 3 * 65536});
    for (int k = 0; k < 40; k++) {   // (many small runs side by side, as a sync's dirty pages)
        std::vector<uint64_t> runs;
        uint64_t so = 0, d0 = 0;
        for (int i = 0; i < 24 && d0 < (1u << 19); i++) {
            const uint64_t size = (1 + rnd() % 8) * 4096;
            d0 += (rnd() % 4) * 4096;
            runs.insert(runs.end(), {so, d0, size});
            so += size, d0 += size;
        }
        copies_alike(0x10000000 + (rnd() % 4) * 4, 0x20000000 + (rnd() % 4) * 4, runs);
    }

    // the tables' ring
    for (const uint64_t atom : {64u, 128u, 256u}) {
        Ring r;
        uint64_t at = 99;
        CHECK(r.get(0, atom, 5, 4, &at) < 0 && r.get(kBlockBytes + 32, atom, 5, 4, &at) < 0 && r.get(32, 0, 5, 4, &at) < 0);
        int i = r.get(96, atom, 5, 4, &at);                    // (the first block, not made yet: the caller's to make)
        CHECK(i == 0 && at == 0 && !r.b[0].made && r.b[0].value == 5 && r.b[0].fill == 96);
        r.b[0].made = true;
        i = r.get(32, atom, 5, 4, &at);                         // (the next table: from an atom of its own)
        CHECK(i == 0 && at == (96 + atom - 1) / atom * atom && at % atom == 0 && at >= 96);
        const uint64_t second = at;
        i = r.get(32, atom, 7, 4, &at);                         // (a later recording reads the block too: its value follows)
        CHECK(i == 0 && at % atom == 0 && at >= second + 32 && r.b[0].value == 7);
        i = r.get(kBlockBytes, atom, 8, 4, &at);                // (no room left in it: the next block)
        CHECK(i == 1 && at == 0 && r.b[1].value == 8);
        r.b[1].made = true;
        for (int k = 2; k < kBlocks; k++) {
            i = r.get(kBlockBytes, atom, 8 + k, 4, &at);
            CHECK(i == k && at == 0);
            r.b[k].made = true;
        }
        CHECK(r.get(kBlockBytes, atom, 30, 6, &at) < 0);        // (block 0 is read by recording 7, the GPU at 6: none)
        CHECK(r.cur == kBlocks - 1);                            // (and nothing moved)
        i = r.get(kBlockBytes, atom, 30, 7, &at);               // (done with 7: block 0 again)
        CHECK(i == 0 && at == 0 && r.b[0].value == 30 && r.b[0].fill == kBlockBytes);
        CHECK(r.get(32, atom, 31, 7, &at) < 0);                 // (block 1, read by recording 8, is next)
    }
    {   // a block the caller could not make is asked for again
        Ring r;
        uint64_t at = 0;
        CHECK(r.get(64, 64, 1, 0, &at) == 0 && !r.b[0].made);
        CHECK(r.get(64, 64, 1, 0, &at) == 0 && !r.b[0].made && at == 64);
    }

    // the barrier
    CHECK(!barrier_first(0, kCopies) && !barrier_first(0, kPass));                      // (nothing wrote it before)
    CHECK(!barrier_first(kCopies, kCopies));                                            // (copies after copies: in order, as before)
    CHECK(barrier_first(kCopies, kPass) && barrier_first(kPass, kPass) && barrier_first(kCopies | kPass, kPass));
    CHECK(barrier_first(kPass, kCopies) && barrier_first(kCopies | kPass, kCopies));
    return fails ? 1 : 0;
}
"""


def copies_into_mirrors(mem):
    """(line number, line, the six lines before) of every vkCmdCopyBuffer whose destination, its third argument, is a mirror"""
    lines = mem.splitlines()
    found = []
    for i, line in enumerate(lines):
        at = line.find("vkCmdCopyBuffer(")
        if at < 0 or line.lstrip().startswith("//"):
            continue
        depth, args, cur = 0, [], ""
        for ch in line[at + len("vkCmdCopyBuffer("):]:
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            if ch == "," and depth == 0:
                args.append(cur.strip())
                cur = ""
            else:
                cur += ch
        if len(args) >= 3 and re.search(r"(\.|->)mirror$", args[2]):
            found.append((i + 1, line, "\n".join(lines[max(0, i - 6):i])))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")

    check('#include "msync_pass.h"' in mem, "vk_memory.cpp does not use msync_pass.h")
    check('msync_pass::on(getenv("RX_VK_MSYNC_PASS"), dev.props.vendorID == 0x10DE)' in mem, "the switch is not the rule's, on NVIDIA when not set")
    usage = block(mem, "VkBufferUsageFlags cap_usage() {")
    check("msync_pass_on() ? VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT : 0" in usage,
          "a capture buffer is not made for the pass to read by its address")
    # ((Triforce, 11-22) since MEM-39 every capture buffer is made by cap_buf_make, cached or (lab, RX_VK_CAP_UNCACHED=1)
    # not: both with the pass's usage, and no capture buffer is made anywhere else)
    make = block(mem, "bool cap_buf_make(uint64_t size, VkBuffer& buffer, VmaAllocation& alloc, void** map, bool own) {")
    check("create_buffer_uncached(size, cap_usage()," in make and "create_buffer_cached(size, cap_usage()," in make and
          mem.count("create_buffer_cached(size, cap_usage(),") == 1 and mem.count("create_buffer_uncached(") == 1 and
          "create_buffer_cached(size, VK_BUFFER_USAGE_TRANSFER_SRC_BIT" not in mem,
          "a capture buffer is made without the pass's usage: the pass would read a buffer that has no address")

    sync = block(mem, "void mirror_sync(Pool& p) {")
    in_order(sync, ["UpWrites up(p);", 'const bool pass = msync_pass_on() && !lab_ab::on("nomsyncpass");',
                    "clip_resident(p, rs);", "if (pass && msync_pass_add(p, buf, rs)) {", "up.write(msync_pass::kCopies);",
                    "vkCmdCopyBuffer(upload_command_buffer(), buf, p.mirror, (uint32_t)rs.size(), rs.data());",
                    "msync_pass_flush(up);", "clip_resident(p, runs);", "up.write(msync_pass::kCopies);",
                    "vkCmdCopyBuffer(upload_command_buffer(), p.buffer, p.mirror, (uint32_t)runs.size(), runs.data());"],
             "mirror_sync does not hand a capture's clipped runs to the pass, flush it ahead of the live runs, or note its copies")

    add = block(mem, "bool msync_pass_add(Pool& p, VkBuffer buf, const std::vector<VkBufferCopy>& rs) {")
    in_order(add, ["if (rs.empty() || !p.mirror || !buf || !wbd_pipe_ready()) return false;", "if (!src || !dst) return false;",
                   "if (!msync_pass::words(src + r.srcOffset, dst + r.dstOffset, r.size)) return false;",
                   "msync_pass::run_chunks(src + r.srcOffset, dst + r.dstOffset, r.size,", "wbd_split(at, size, e);",
                   "msync_chunks.push_back({s, d, d, count, vecs ? 1u : 0u});", "msync_copies.push_back({buf, p.mirror, rs});"],
             "msync_pass_add does not refuse a run that is not whole words before it takes any, or its chunks' shadow is not their destination")
    flush = block(mem, "void msync_pass_flush(UpWrites& up) {")
    in_order(flush, ["MsyncBlock* b = msync_block_get(bytes, at);", "if (!b) {", "up.write(msync_pass::kCopies);",
                     "vkCmdCopyBuffer(cmd, c.src, c.dst, (uint32_t)c.rs.size(), c.rs.data());", "st_msync_fallbacks++;",
                     "memcpy(b->map + at, msync_chunks.data(), bytes);", "flush_mapped_range(b->alloc, at, bytes);",
                     "up.write(msync_pass::kPass);", "checkpoint_mark(cmd, n, 's');",
                     "vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, wbd_pipe.pipe);",
                     "pc{b->address + at, n, 0};", "vkCmdDispatch(cmd, std::min<uint32_t>(n, 65535u), (n + 65534u) / 65535u, 1);",
                     "msync_chunks.clear();", "msync_copies.clear();"],
             "msync_pass_flush: a sync with no table room is not copied, or the table is not written and flushed, the barrier's "
             "note made and the checkpoint marked before the dispatch")
    get = block(mem, "MsyncBlock* msync_block_get(uint64_t bytes, uint64_t& at) {")
    in_order(get, ["std::max<uint64_t>(sizeof(WbdChunk), dev.props.limits.nonCoherentAtomSize);",
                   "msync_ring.get(bytes, align, mem_rec_value, mem_completed, &at);", "if (!msync_ring.b[i].made) {",
                   "msync_ring.b[i].made = true;"], "msync_block_get does not take its tables from the ring by the atom and the GPU's progress")

    ups = block(mem, "struct UpWrites {")
    in_order(ups, ["if (!msync_pass_on()) return;", "cmd = upload_command_buffer();",
                   "prior = p.up_cmd == cmd && p.up_value == mem_rec_value ? p.up_kinds : 0;",
                   "if (msync_pass::barrier_first(prior, kind)) {", "full_barrier(cmd,", "prior = 0", "mine |= kind;",
                   "p.up_cmd = cmd, p.up_value = mem_rec_value, p.up_kinds = (uint8_t)(prior | mine);"],
             "UpWrites does not put a full barrier before a write the rule asks one for, or does not keep what wrote the mirror")
    # (every copy into a mirror in the uploads: noted, so that a pass before or after it in that command buffer is ordered)
    writes = copies_into_mirrors(mem)
    check(len(writes) >= 8, "the copies into mirrors were not found (%d): the scan no longer reads the source" % len(writes))
    for n, line, before in writes:
        noted = ("mirror_up_copy(" in line or "mirror_up_copy(" in before or "up.write(msync_pass::kCopies);" in before or
                 "up_kinds = msync_pass::kCopies;" in before)
        check(noted, "vk_memory.cpp:%d copies into a mirror without a note for the syncs' pass: a dispatch before it in the same "
                     "upload command buffer is not ordered with it\n    %s" % (n, line.strip()))
    check("msync_pass_report();" in block(mem, "void memory_end_submission(VkCommandBuffer cmd) {"), "the pass's 600-submit report is not made")

    kinds = (VK / "checkpoint_kinds.h").read_text(encoding="utf-8")
    check(kinds.count("case 's':") == 2, "checkpoint_kinds.h does not name the pass's marker and what follows it")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_MSYNC_PASS=0`" in dev, "docs/development.md: RX_VK_MSYNC_PASS is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="msync-pass-") as tmp:
        c, exe = Path(tmp) / "pass.cpp", Path(tmp) / "pass.exe"
        c.write_text(PROGRAM.replace("@WBD_SPLIT@", block(mem, "template <class F> void wbd_split(uint64_t at, uint64_t size, F&& emit) {")),
                     encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rules as made:\n" + r.stdout)
    print("PASS: a mirror sync's pages from the captures go by one dispatch, in order with the copies")


if __name__ == "__main__":
    main()
