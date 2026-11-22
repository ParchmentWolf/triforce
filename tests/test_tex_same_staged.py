"""RX_VK_TEX_SAME's compare reads a capture's texture page from the staging, ordinary memory, when the staging holds it,
not from the capture buffer (gpu/vk/vk_memory.cpp take_capture and cap_page_bytes; no game, no GPU).

(Triforce, 11-22, the performance audit's MEM-39, after Source A's.) A capture buffer asks for cached host memory, but a
driver can hand out write-combined memory, which the CPU reads at about 0.3 GB/s. Such a capture's texture pages are
copied into a staging block first and the shadow's copies read that; the compare of each copied texture page with its
shadow copy still read the buffer.

This cuts cap_page_bytes out of vk_memory.cpp and runs it on random captures built the way capture_make builds them (a
texture page that is not late: into the staging, and the buffer from there; any other page: the buffer alone):
  - the compare's verdict from cap_page_bytes is the verdict from the buffer, page for page (the same bytes);
  - a staged page's bytes are read from the staging and not from the buffer; an unstaged one's from the buffer;
  - with no staging (a cached buffer, RX_VK_SHADOW_STAGE=0) it is the old pointer exactly.

And reads the source: the compare reads cap_page_bytes(*c, c->slots[i]) after cap_ready, the buffer only in the lab
knob's phases; the other reads of the capture buffer in take_capture are the three known ones (two of late pages, one of
unstaged pages), each marked; the first uncached buffer is logged; the lab's switch and the switches table.

    python -I -B tests/test_tex_same_staged.py [--cxx clang++]
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
    check(marker in text, "the source has no " + marker)
    start = text.index(marker)
    end = text.index("{", start + len(marker) - 1) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


HEAD = r"""
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>
struct Capture {
    void* map = nullptr;
    std::unique_ptr<uint8_t[]> stage;
    std::vector<int32_t> sidx;
};
"""

TAIL = r"""
static uint64_t rnd_state = 0x2545F4914F6CDD1Dull;
static uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}
int main() {
    int fails = 0;
    long staged_n = 0, unstaged_n = 0, same_n = 0, changed_n = 0;
    for (int t = 0; t < 400; t++) {
        const uint32_t n = 1 + (uint32_t)(rnd() % 48);
        std::vector<uint8_t> guest((size_t)n * 4096), buffer((size_t)n * 4096), shadow((size_t)n * 4096);
        for (auto& b : guest) b = (uint8_t)rnd();
        shadow = guest;
        Capture c;
        c.map = buffer.data();
        const bool staging = t % 4 != 0;   // (one capture in four has a cached buffer: no staging)
        std::vector<uint8_t> tex(n), late(n);
        uint32_t tn = 0;
        if (staging) c.sidx.assign(n, -1);
        for (uint32_t i = 0; i < n; i++) {
            tex[i] = rnd() % 3 != 0, late[i] = rnd() % 7 == 0;
            if (staging && tex[i] && !late[i]) c.sidx[i] = (int32_t)tn++;
            if (rnd() % 2) shadow[(size_t)i * 4096 + rnd() % 4096] ^= 0x5a;   // (half the pages changed since their shadow copy)
        }
        if (staging && !tn) c.sidx.clear();   // (capture_make: nothing to stage, no staging)
        if (!c.sidx.empty()) c.stage.reset(new uint8_t[(size_t)tn * 4096]);
        for (uint32_t i = 0; i < n; i++) {    // (the copy: the staging first and the buffer from there, else the buffer)
            const uint8_t* src = guest.data() + (size_t)i * 4096;
            if (!c.sidx.empty() && c.sidx[i] >= 0) {
                uint8_t* st = c.stage.get() + (size_t)c.sidx[i] * 4096;
                memcpy(st, src, 4096);
                memcpy(buffer.data() + (size_t)i * 4096, st, 4096);
            } else memcpy(buffer.data() + (size_t)i * 4096, src, 4096);
        }
        for (uint32_t i = 0; i < n; i++) {
            const uint8_t* was = (const uint8_t*)c.map + (uint64_t)i * 4096;   // (the read as it was)
            const uint8_t* now = cap_page_bytes(c, i);
            const uint8_t* sh = shadow.data() + (size_t)i * 4096;
            const bool same_was = memcmp(sh, was, 4096) == 0, same_now = memcmp(sh, now, 4096) == 0;
            if (same_was != same_now || memcmp(was, now, 4096) != 0) fails++, printf("FAIL capture %d page %u: the verdict or the bytes differ\n", t, i);
            const bool in_stage = !c.sidx.empty() && c.sidx[i] >= 0;
            if (in_stage) {
                staged_n++;
                if (now != c.stage.get() + (size_t)c.sidx[i] * 4096) fails++, printf("FAIL capture %d page %u: a staged page read from the buffer\n", t, i);
                if (late[i] || !tex[i]) fails++, printf("FAIL the model staged a late or non-texture page\n");
            } else {
                unstaged_n++;
                if (now != was) fails++, printf("FAIL capture %d page %u: an unstaged page not read from the buffer\n", t, i);
            }
            (same_now ? same_n : changed_n)++;
        }
    }
    if (!staged_n || !unstaged_n || !same_n || !changed_n) fails++, printf("FAIL the trials did not cover both kinds of page and both verdicts\n");
    printf("%ld staged pages read from the staging, %ld unstaged from the buffer; %ld same, %ld changed: the verdicts of the read as it was\n",
           staged_n, unstaged_n, same_n, changed_n);
    return fails != 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    take = block(mem, "bool take_capture(std::unique_ptr<Capture> c, uint64_t value, uint64_t completed) {")

    # the compare
    old = "if (memcmp(s->second.b.get(), (const uint8_t*)c->map + (uint64_t)c->slots[i] * 4096, 4096) != 0) {"
    check(old not in take, "take_capture: RX_VK_TEX_SAME's compare still reads the capture buffer")
    order = [take.find(s) for s in (
        'const bool same_from_map = lab_ab::on("texsamemap");',
        "cap_ready(*c, c->slots[i]);",
        "const uint8_t* const cap_b = same_from_map ? (const uint8_t*)c->map + (uint64_t)c->slots[i] * 4096 : cap_page_bytes(*c, c->slots[i]);",
        "if (memcmp(s->second.b.get(), cap_b, 4096) != 0) {",
        "same_pages.push_back({p, gens.page_tex(p)});")]
    check(min(order) >= 0 and order == sorted(order),
          "take_capture: the compare does not read cap_page_bytes(*c, c->slots[i]) after cap_ready, or the lab knob is not read once a take")
    check(take[order[1]:order[3]].count("cap_ready(") == 1 and "for (" not in take[order[1]:order[3]],
          "take_capture: the compare's page is not the one made ready just before it")

    # the other reads of the capture buffer in take_capture: the known ones, each marked
    reads = [
        ("if (was && !memcmp(was, (const uint8_t*)c->map + (uint64_t)i * 4096, 4096)) {", "a late page is never staged"),
        ("memcpy(lp.bytes.data(), (const uint8_t*)c->map + (uint64_t)i * 4096, 4096);", "a late page is never staged"),
        ("else pairs.push_back({slot.b.get(), (const uint8_t*)c->map + (uint64_t)c->slots[i] * 4096}), from_map++;", "unstaged pages only"),
    ]
    for text, mark in reads:
        check(take.count(text) == 1, "take_capture: the read %r is not there once" % text)
        at = take.index(text)
        note = take[take.rindex("// ((Triforce, 11-22, MEM-39)", 0, at):at]
        check(mark in note and note.count("\n") <= 2, "take_capture: the read %r is not marked (%s)" % (text, mark))
    # (reads: a (const uint8_t*) view of the buffer. The writes, the late pages' second copies, cast to (uint8_t*))
    n_reads = take.count("(const uint8_t*)c->map")
    check(n_reads == len(reads) + 1, "take_capture reads the capture buffer in %d places, not the %d known ones and the lab knob's"
          % (n_reads, len(reads)))
    check("c.map" not in take.replace("f.map", ""), "take_capture reads a capture's map some other way")

    # the first uncached buffer is logged, the lab's switch
    make = block(mem, "std::unique_ptr<Capture> capture_make(bool behind) {")
    order = [make.find(s) for s in ("c->buf_cached = host_cached(c->alloc);", "if (!c->buf_cached) {", "if (!told.exchange(true)) {",
                                    "alloc_memory_type(c->alloc, &flags);", "if (stage_on() && !texr.empty() && !c->buf_cached) {")]
    check(min(order) >= 0 and order == sorted(order), "capture_make does not log the first capture buffer that is not cached, once")
    unc = block(mem, "bool cap_uncached() {")
    check('getenv("RX_VK_CAP_UNCACHED")' in unc and "e && atoi(e) != 0" in unc and "static const bool on" in unc,
          "RX_VK_CAP_UNCACHED is not off unless set, or is read more than once")
    mk = block(mem, "bool cap_buf_make(uint64_t size, VkBuffer& buffer, VmaAllocation& alloc, void** map, bool own) {")
    check("cap_uncached() ? create_buffer_uncached(size, cap_usage(), buffer, alloc, map, own)" in mk and
          ": create_buffer_cached(size, cap_usage(), buffer, alloc, map, own);" in mk, "cap_buf_make is not the cached buffer unless the lab's switch is set")
    check(mem.count("create_buffer_uncached(") == 1, "an uncached buffer is made elsewhere than in cap_buf_make")
    vma = (VK / "vk_vma.cpp").read_text(encoding="utf-8")
    cached, uncached = block(vma, "bool create_buffer_cached("), block(vma, "bool create_buffer_uncached(")
    check("VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT" in cached and "SEQUENTIAL_WRITE" not in cached,
          "create_buffer_cached no longer asks for cached memory")
    check("VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT" in uncached, "the lab's buffer is not asked for as written in order")
    stage = block(mem, "bool stage_on() {")
    check('getenv("RX_VK_SHADOW_STAGE")' in stage, "stage_on no longer reads RX_VK_SHADOW_STAGE")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_SHADOW_STAGE=0`" in dev and "`RX_VK_CAP_UNCACHED=1`" in dev and "`texsamemap`" in dev,
          "docs/development.md: RX_VK_SHADOW_STAGE=0, the lab's RX_VK_CAP_UNCACHED=1 or the knob texsamemap is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="tex-same-staged-") as tmp:
        src, exe = Path(tmp) / "staged.cpp", Path(tmp) / "staged.exe"
        src.write_text(HEAD + block(mem, "inline const uint8_t* cap_page_bytes(const Capture& c, uint32_t slot) {") + TAIL, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
        print(r.stdout.rstrip())
        check(r.returncode == 0, "the staged read's checks failed")
    print("PASS: RX_VK_TEX_SAME's compare reads the staging when it holds the page: the same bytes, the same verdicts")


if __name__ == "__main__":
    main()
