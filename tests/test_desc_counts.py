"""A program's descriptor counts kept with the program (gpu/vk/desc_counts.h; vk_shader.h Program::desc_n, vk_draw.cpp
build_descriptors; no game, no GPU).

(Triforce, 11-22, the performance audit's DESC-22, after Source A's.) build_descriptors summed the program's buffers,
images and texel views at every build, six lists a stage, to size three reserve() calls. The sums are fixed once the
program is translated, so they are kept packed in one 32-bit word on the program and read at every later build.

Compiles a driver against the header: the round trip of every count up to 1023; more than 1023 of a kind packs to the
unset word; the unset and the never words hold no counts and leave the outputs alone; a build stores only with the
rule on, the program ready and the word still unset; the guard fires only for a build that did not walk and had a
vector move.

Runs a model of the build over the real rule with a std::vector as build_descriptors uses it: by kept counts the
vector never moves; with a count kept short it does, the guard sees it, the word becomes never and the next build walks.

Reads the source:
  - vk_shader.h: desc_n right after ready and before stages, mutable, ~0u, and the static_assert that keeps it in the
    padding (sizeof(Program) is in the program cache's stamp; this change must not move it);
  - build_descriptors: the word read only with the switch on, the walk only when it holds no counts, the store after
    the walk and by the rule (ready, acquire), the three data() pointers taken after the reserve and compared at the
    end, the rebuild; RX_VK_DESC_COUNTS read once and the lab's knob;
  - vk_shader.cpp, a stamp file, does not name the field; the switches table has the row.

    python -I -B tests/test_desc_counts.py [--cxx clang++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "desc_counts.h"
#include <cstdio>
#include <vector>

using namespace mkwvk::desc_counts;
static int checks, fails;
static void want(const char* what, bool ok) {
    checks++;
    if (!ok) fails++, printf("FAIL %s\n", what);
}

// build_descriptors' use of the rule, on one vector of each kind: reserve by the word or by the walk, push what the
// program really has, store, guard
struct Model {
    uint32_t word = kUnset;
    size_t bufs, imgs, views;   // (what the program has)
    std::vector<int> b, i, v;
    int walks = 0, rebuilds = 0;
    bool build(bool on, bool ready) {
        b.clear(), i.clear(), v.clear();
        size_t nb = 0, ni = 0, nv = 0;
        const uint32_t counted = on ? word : kUnset;
        const bool walked = !unpack(counted, &nb, &ni, &nv);
        if (walked) {
            walks++, nb = bufs, ni = imgs, nv = views;
            if (stores(on, ready, word)) word = pack(nb, ni, nv);
        }
        b.reserve(nb), i.reserve(ni), v.reserve(nv);
        const void *b0 = b.data(), *i0 = i.data(), *v0 = v.data();
        for (size_t k = 0; k < bufs; k++) b.push_back(1);
        for (size_t k = 0; k < imgs; k++) i.push_back(1);
        for (size_t k = 0; k < views; k++) v.push_back(1);
        if (moved(walked, b0, b.data(), i0, i.data(), v0, v.data())) {
            word = kNever, rebuilds++;
            return build(on, ready);
        }
        return walked;
    }
};

int main() {
    want("on when unset", on(nullptr) && on("1") && !on("0"));
    size_t a = 7, b = 8, c = 9;
    for (size_t n = 0; n <= kMost; n++) {
        const size_t x = n, y = (n * 7) % (kMost + 1), z = kMost - n;
        a = b = c = 5000;
        if (!unpack(pack(x, y, z), &a, &b, &c) || a != x || b != y || c != z) {
            want("round trip", false);
            break;
        }
    }
    want("round trip of every count up to 1023", true);
    want("all three at the most", holds(pack(1023, 1023, 1023)) && pack(1023, 1023, 1023) == 0x3FFFFFFFu);
    want("none at all", holds(pack(0, 0, 0)) && pack(0, 0, 0) == 0);
    want("over 1023 buffers: unset", pack(1024, 1, 1) == kUnset);
    want("over 1023 images: unset", pack(1, 1024, 1) == kUnset);
    want("over 1023 texel views: unset", pack(1, 1, 1024) == kUnset && pack(1, 1, (size_t)1 << 40) == kUnset);
    a = 7, b = 8, c = 9;
    want("the unset word holds nothing", !holds(kUnset) && !unpack(kUnset, &a, &b, &c) && a == 7 && b == 8 && c == 9);
    want("nor the never word", !holds(kNever) && !unpack(kNever, &a, &b, &c) && a == 7 && b == 8 && c == 9 && kNever != kUnset);
    want("stored: on, ready, unset", stores(true, true, kUnset));
    want("not while it is translated", !stores(true, false, kUnset));
    want("not with the switch off", !stores(false, true, kUnset));
    want("not over the never word", !stores(true, true, kNever));
    want("not over counts", !stores(true, true, pack(1, 2, 3)));
    int p0 = 0, p1 = 0;
    want("the guard: nothing moved", !moved(false, &p0, &p0, &p0, &p0, &p0, &p0));
    want("the guard: buffers moved", moved(false, &p0, &p1, &p0, &p0, &p0, &p0));
    want("the guard: images moved", moved(false, &p0, &p0, &p0, &p1, &p0, &p0));
    want("the guard: texel views moved", moved(false, &p0, &p0, &p0, &p0, &p0, &p1));
    want("the guard: a walked build is not asked", !moved(true, &p0, &p1, &p0, &p1, &p0, &p1));

    Model m;
    m.bufs = 12, m.imgs = 30, m.views = 2;
    want("a program still translated walks and stores nothing", m.build(true, false) && m.word == kUnset && m.walks == 1);
    want("ready: its first build walks and stores", m.build(true, true) && m.word == pack(12, 30, 2) && m.walks == 2);
    for (int k = 0; k < 50; k++) m.build(true, true);
    want("then no build walks and none moves", m.walks == 2 && m.rebuilds == 0 && m.b.size() == 12 && m.i.size() == 30 && m.v.size() == 2);
    want("the switch off: every build walks", m.build(false, true) && m.build(false, true) && m.walks == 4 && m.word == pack(12, 30, 2));
    Model big;
    big.bufs = 3, big.imgs = 2000, big.views = 0;
    for (int k = 0; k < 5; k++) big.build(true, true);
    want("more than 1023 of a kind: every build walks", big.walks == 5 && big.word == kUnset && big.rebuilds == 0);
    Model bad;   // (a word kept short: what the guard is for. Fresh vectors, so the short reserve is all the room there is)
    bad.bufs = 400, bad.imgs = 300, bad.views = 200;
    bad.word = pack(4, 300, 200);
    want("a count kept short: the build moves, is made again walked", bad.build(true, true) && bad.rebuilds == 1 && bad.word == kNever);
    for (int k = 0; k < 5; k++) bad.build(true, true);
    want("and walks from then on, the word never set again", bad.walks == 6 && bad.rebuilds == 1 && bad.word == kNever && bad.b.size() == 400);
    if (fails) printf("desc counts: FAILED (%d of %d checks)\n", fails, checks);
    else printf("desc counts: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def ordered(text, parts, why):
    last = 0
    for p in parts:
        k = text.find(p, last)
        need(k >= 0, why + " (missing, or out of order: " + p + ")")
        last = k + len(p)


def check_source():
    header = (ROOT / "gpu/vk/vk_shader.h").read_text(encoding="utf-8")
    prog = block(header, "struct Program {")
    ordered(prog, ["std::atomic<bool> ready{false};", "mutable std::atomic<uint32_t> desc_n{~0u};", "std::vector<Stage> stages;"],
            "vk_shader.h: Program::desc_n is not right after ready and before stages")
    between = prog[prog.index("std::atomic<bool> ready{false};"):prog.index("mutable std::atomic<uint32_t> desc_n{~0u};")].splitlines()[1:]
    need(all(not line.strip() or line.strip().startswith("//") for line in between),
         "vk_shader.h: a field came between Program::ready and Program::desc_n")
    need("MUST NOT GROW THE STRUCT" in prog, "vk_shader.h: the field's comment no longer says it must not grow the struct")
    after = header[header.index(prog) + len(prog):][:700]
    need(re.search(r"static_assert\(sizeof\(std::atomic<uint32_t>\) == 4 && offsetof\(Program, desc_n\) \+ 4 <= offsetof\(Program, stages\) &&\s*"
                   r"offsetof\(Program, stages\) == 16,", after),
         "vk_shader.h: the static_assert that keeps desc_n in the padding before stages is gone")
    need("#include <cstddef>" in header, "vk_shader.h uses offsetof without <cstddef>")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need('#include "desc_counts.h"' in draw, "vk_draw.cpp does not include desc_counts.h")
    on = block(draw, "bool desc_counts_on() {")
    need('static const bool env = desc_counts::on(getenv("RX_VK_DESC_COUNTS"));' in on and 'return env && !lab_ab::on("descwalk");' in on,
         "the switch is not RX_VK_DESC_COUNTS read once, with the lab's descwalk knob")
    build = block(draw, "void build_descriptors(")
    ordered(build, ["size_t nbuf = 0, nimg = 0, nview = 0;", "const bool counts_on = desc_counts_on();",
                    "const uint32_t counted = counts_on ? p.desc_n.load(std::memory_order_relaxed) : desc_counts::kUnset;",
                    "const bool walked = !desc_counts::unpack(counted, &nbuf, &nimg, &nview);", "if (walked) {",
                    "for (const Stage& st : p.stages) {", "st.info.constant_buffer_descriptors) nbuf += d.count;",
                    "st.info.image_descriptors) nimg += d.count;",
                    "if (desc_counts::stores(counts_on, p.ready.load(std::memory_order_acquire), p.desc_n.load(std::memory_order_relaxed)))",
                    "p.desc_n.store(desc_counts::pack(nbuf, nimg, nview), std::memory_order_relaxed);",
                    "dwr.bufs.reserve(nbuf), dwr.imgs.reserve(nimg), dwr.views.reserve(nview);",
                    "const void* const bufs_at = dwr.bufs.data();", "const void* const imgs_at = dwr.imgs.data();",
                    "const void* const views_at = dwr.views.data();", "desc_keep::prog_of(kept_descs(), &p, nbuf + nimg + nview)",
                    "if (desc_counts::moved(walked, bufs_at, dwr.bufs.data(), imgs_at, dwr.imgs.data(), views_at, dwr.views.data())) {",
                    "p.desc_n.store(desc_counts::kNever, std::memory_order_relaxed);", "build_descriptors(s, p, keep, scene);"],
            "build_descriptors does not read the kept counts, walk only without them, store by the rule, and guard its vectors")
    need(build.count("for (const auto& d : st.info.") == 6, "build_descriptors sums other than its six lists a stage")
    need(build.rstrip().endswith("build_descriptors(s, p, keep, scene);\n    }\n}"), "the guard is not the last thing build_descriptors does")
    named = lambda text: len(re.findall(r"(?<![A-Za-z0-9_])desc_n(?![A-Za-z0-9_])", text))
    need(build.count("p.desc_n.store(") == 2 and named(draw) == named(build), "something outside build_descriptors reads or writes a program's kept counts")
    # (vk_shader.cpp is a stamp file: this change does not touch it, and nothing there needs the field)
    need("desc_n" not in (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8"), "vk_shader.cpp, a stamp file, names desc_n")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_DESC_COUNTS=0`" in docs and "`gpu/vk/desc_counts.h`" in docs and "`descwalk`" in docs,
         "docs/development.md: the switches table has no RX_VK_DESC_COUNTS row")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="desc-counts-") as tmp:
        cpp, exe = Path(tmp) / "desc_counts_test.cpp", Path(tmp) / "desc-counts.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the descriptor counts' checks failed")
    check_source()
    print("PASS: a program's descriptor counts are kept with it, in the padding of Program; RX_VK_DESC_COUNTS=0 walks as before")


if __name__ == "__main__":
    main()
