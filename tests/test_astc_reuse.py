"""Decoded ASTC used again, its first step: the blocks hashed, the finalized textures listed, a hit counted
(gpu/vk/astc_reuse.h, vk_texture.cpp; no game, no GPU).

(Triforce, 11-21, the performance audit's TEX-14, after Source A's.) When the game comes back to an area it makes its
textures again, mostly at other addresses, and the same ASTC blocks are decoded and encoded again while the image made
of them the first time may still be in VRAM. This step counts what taking that image would save (RX_VK_ASTC_REUSE=2);
nothing is copied.

This compiles astc_reuse.h alone: the switch's modes; the two lanes are different hashes and both change with one byte;
a storage hashed in pieces of any size gives one hash, and another order or length another; never all zero; shapes that
differ in any one field never match; a texture is listed once, found by hash, both lanes and shape, never itself, and
unlisted by its pointer alone.

And reads the source: with the switch off nothing of it runs; a new ASTC texture's blocks are hashed once at its first
upload and the count never stands in for the decode; a finalized one is listed only when it was uploaded from memory,
never drawn into, and of the finalized texture's own description; it is unlisted when used again or gone; the switch
is in the switches table.

    python -I -B tests/test_astc_reuse.py [--cxx clang++]
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


def block(text, head):
    at = text.index(head)
    return text[at:text.index("\n}\n", at) + 3]


def in_order(text, parts, why):
    at = 0
    for p in parts:
        at = text.find(p, at)
        check(at >= 0, why + " (missing, or out of order: " + p + ")")
        at += len(p)


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include <vector>
#include "astc_reuse.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace astc_reuse;
struct Tex { Shape s; int id; };
static Hash of(const std::vector<uint8_t>& d, uint64_t piece) {
    Hasher h;
    for (uint64_t at = 0; at < d.size(); at += piece) h.add(d.data() + at, d.size() - at < piece ? d.size() - at : piece);
    return h.done();
}
int main() {
    CHECK(mode(nullptr) == kOff && mode("") == kOff && mode("0") == kOff && mode("1") == kCopy && mode("2") == kCount && mode("3") == kOff &&
          mode("on") == kOff);

    std::vector<uint8_t> d(3 * kStep + 12345);
    uint32_t r = 7;
    for (uint8_t& b : d) r = r * 1664525u + 1013904223u, b = (uint8_t)(r >> 24);
    // the lanes: two hashes, each moved by one byte anywhere
    CHECK(lane2(d.data(), d.size()) != upload_same::content_hash(d.data(), d.size()));
    for (const size_t at : {(size_t)0, (size_t)63, (size_t)4096, d.size() / 2, d.size() - 1}) {
        const Hash before = of(d, 64u << 20);
        const uint64_t l2 = lane2(d.data(), d.size());
        d[at] ^= 0x10;
        const Hash after = of(d, 64u << 20);
        CHECK(after.a != before.a && after.b != before.b && lane2(d.data(), d.size()) != l2);
        d[at] ^= 0x10;
        CHECK(of(d, 64u << 20) == before);
    }
    // pieces: whatever multiple of the step the storage is read in, one hash
    const Hash whole = of(d, 64u << 20);
    CHECK(of(d, kStep) == whole && of(d, 2 * kStep) == whole && of(d, 1u << 20) == whole);
    CHECK(bool(whole));
    {   // the length and the order count
        std::vector<uint8_t> shorter(d.begin(), d.end() - 1), swapped(d);
        for (size_t i = 0; i < kStep; i++) std::swap(swapped[i], swapped[i + kStep]);
        CHECK(!(of(shorter, 64u << 20) == whole) && !(of(swapped, 64u << 20) == whole));
        Hasher none;
        CHECK(bool(none.done()));                                   // (never all zero: zero is "not hashed")
        CHECK(!bool(Hash{}));
    }

    // shapes: every field
    const Shape s{131, 1024, 512, 1, 11, 6, 0, 0x79, 2, true, false, false, false, false};
    CHECK(s == s);
    { Shape o = s; o.format = 145; CHECK(!(o == s)); }
    { Shape o = s; o.width = 512; CHECK(!(o == s)); }
    { Shape o = s; o.height = 1024; CHECK(!(o == s)); }
    { Shape o = s; o.depth = 2; CHECK(!(o == s)); }
    { Shape o = s; o.levels = 10; CHECK(!(o == s)); }
    { Shape o = s; o.layers = 1; CHECK(!(o == s)); }
    { Shape o = s; o.skip = 1; CHECK(!(o == s)); }
    { Shape o = s; o.nvn_format = 0x7a; CHECK(!(o == s)); }
    { Shape o = s; o.layout = 3; CHECK(!(o == s)); }
    { Shape o = s; o.bc = false; CHECK(!(o == s)); }
    { Shape o = s; o.bc_resized = true; CHECK(!(o == s)); }
    { Shape o = s; o.bc1 = true; CHECK(!(o == s)); }
    { Shape o = s; o.bc1_no = true; CHECK(!(o == s)); }
    { Shape o = s; o.detail_skip = true; CHECK(!(o == s)); }

    // the list
    Freed<Tex> freed;
    Tex a{s, 1}, b{s, 2}, c{s, 3};
    c.s.width = 2048;
    const Hash h1{11, 22}, h2{11, 33}, h3{44, 22};
    const auto shape_of = [](const Tex* t) { return t->s; };
    CHECK(freed.size() == 0 && freed.find(h1, s, nullptr, shape_of) == nullptr);
    freed.list(h1, &a);
    CHECK(freed.size() == 1 && freed.find(h1, s, nullptr, shape_of) == &a);
    CHECK(freed.find(h1, s, &a, shape_of) == nullptr);              // (never itself)
    CHECK(freed.find(h2, s, nullptr, shape_of) == nullptr);         // (the second lane differs)
    CHECK(freed.find(h3, s, nullptr, shape_of) == nullptr);         // (the first lane differs)
    CHECK(freed.find(h1, c.s, nullptr, shape_of) == nullptr);       // (another shape)
    freed.list(h1, &c);                                             // (the same blocks decoded to another shape)
    CHECK(freed.find(h1, c.s, nullptr, shape_of) == &c && freed.find(h1, s, nullptr, shape_of) == &a);
    freed.list(h2, &b);                                             // (the first lane alike, the second not)
    CHECK(freed.size() == 3 && freed.find(h2, s, nullptr, shape_of) == &b && freed.find(h1, s, nullptr, shape_of) == &a);
    Tex never{s, 4};
    freed.unlist(h1, &never), freed.unlist(h3, &b);                 // (not listed, or not under that hash: nothing goes)
    CHECK(freed.size() == 3);
    freed.unlist(h1, &a);
    CHECK(freed.size() == 2 && freed.find(h1, s, nullptr, shape_of) == nullptr && freed.find(h1, c.s, nullptr, shape_of) == &c);
    freed.unlist(h1, &a);                                           // (once is all)
    CHECK(freed.size() == 2);
    freed.unlist(h2, &b), freed.unlist(h1, &c);
    CHECK(freed.size() == 0);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    head = (VK / "vk_texture.h").read_text(encoding="utf-8")
    check('static const astc_reuse::Mode m = astc_reuse::mode(getenv("RX_VK_ASTC_REUSE"));' in tex, "the switch is not the rule's")
    check("astc_reuse::Hash blocks_hash;" in head and "bool freed_listed = false;" in head, "a texture does not keep its blocks' hash")

    inner = block(tex, "bool upload_inner(Texture& tex, const Ranges* dirty) {")
    ask = ("if (tex.astc && !tex.uploaded && !tex.blocks_hash && astc_reuse_mode() != astc_reuse::kOff && reuse_upload(tex, total))")
    in_order(inner, [ask, "if (tex.astc && (up_route = UP_ASTC, upload_astc_gpu(tex, total, dirty))) return true;"],
             "upload_inner does not hash a new ASTC texture's blocks once, only with the switch on, before its decode")
    up = block(tex, "bool reuse_upload(Texture& tex, uint64_t total) {")
    in_order(up, ["h.add(guest_bytes(tex.gpu + at, n, scratch), n);", "tex.blocks_hash = h.done();",
                  "if (tex.sparse || tex.type != VK_IMAGE_TYPE_2D || !tex.image) return false;", "std::lock_guard lk(reuse_mu);",
                  "reuse_freed.find(tex.blocks_hash, reuse_shape(tex), &tex,",
                  "if (!from || !from->image || !from->uploaded || from->gpu_written) return false;",
                  "reuse_freed.unlist(from->blocks_hash, from);", "from->freed_listed = false;", "st_reuse_hits"],
             "reuse_upload does not hash the blocks as the decoder is given them, or look for a listed texture under the lock")
    check("return true;" not in up, "reuse_upload stands in for the decode: this step only counts, and nothing was copied")
    shape = block(tex, "astc_reuse::Shape reuse_shape(const Texture& t) {")
    check("(uint32_t)t.format, t.width, t.height, t.depth, t.levels, t.layers, t.skip, (uint32_t)t.nvn_format, t.key_layout," in shape and
          "t.bc, t.bc_resized, t.bc1, t.bc1_no, t.detail_skip};" in shape, "a texture's shape leaves a field of its image out")

    rel = block(tex, "void reuse_released(const nvn_tex* t) {")
    in_order(rel, ["if (!x->astc || !x->blocks_hash || !x->uploaded || x->gpu_written || x->freed_listed) continue;",
                   "x->d.format != t->d.format", "x->d.levels != t->d.levels || x->d.target != t->d.target", "std::lock_guard lk(reuse_mu);",
                   "reuse_freed.list(x->blocks_hash, x);", "x->freed_listed = true;"],
             "a finalized texture is listed though it was drawn into, not uploaded, not hashed, or of another description")
    # ((Triforce, 11-22, the performance audit's MEM-85) texture_released's body is texture_released_at, from a given generation)
    released = block(tex, "void texture_released_at(const nvn_tex* t, WriteGen gen) {")
    check("if (astc_reuse_mode() != astc_reuse::kOff) reuse_released(t);" in released, "texture_released does not list, or lists with the switch off")
    for name, fn in (("forget_gpu", "void forget_gpu(Texture* tex) {"), ("texture_touch", "Texture* texture_touch(Texture* tex, bool for_sampling) {"),
                     ("texture_touch_quick", "bool texture_touch_quick(Texture* tex, bool for_sampling) {")):
        body = block(tex, fn)
        check("if (tex->freed_listed) reuse_drop(*tex);" in body and body.index("if (tex->freed_listed) reuse_drop(*tex);") < 400,
              name + " does not unlist a texture used again or gone: a later texture could be given a dangling or a live one's image")
    drop = block(tex, "void reuse_drop(Texture& t) {")
    in_order(drop, ["std::lock_guard lk(reuse_mu);", "if (t.freed_listed) reuse_freed.unlist(t.blocks_hash, &t), t.freed_listed = false;"],
             "reuse_drop does not unlist under the lock")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_ASTC_REUSE=2`" in dev, "docs/development.md: RX_VK_ASTC_REUSE is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="astc-reuse-") as tmp:
        c, exe = Path(tmp) / "reuse.cpp", Path(tmp) / "reuse.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rules as made:\n" + r.stdout)
    print("PASS: decoded ASTC's blocks are hashed, the finalized textures listed and a hit counted")


if __name__ == "__main__":
    main()
