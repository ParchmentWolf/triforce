"""The prediction's checks: a predicted vertex layout against the program's vertex inputs' types, and each predicted
pipeline built once (gpu/vk/predict_types.h; vk_predict.cpp candidates, layout_kinds, predict_pipelines; vk_draw.cpp
predict_first, predict_run, predict_background; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-44, after Source A's.) A program's key already says which vertex inputs it
reads as integers, so a predicted layout borrowed from other programs can hand an integer input a float attribute, or the
other signedness: an invalid pipeline. With RX_VK_PREDICT_TYPES=1 the plan drops such a layout (read from the vertex
module's SPIR-V; scaled formats count as integers). And a program's predictions could give the same pipeline twice; unset,
each is built once by its key as play keys it: the same pipelines. 0: as before.

The header is compiled against hand-made SPIR-V: the inputs with a Location and their base types through pointers,
vectors and arrays, built-ins and outputs not counted; a uint input against a float attribute does not fit, float against
float and sint against a signed integer do, an unset attribute or an unread location says nothing; the switch.
Then cut out of vk_predict.cpp and run: candidates() with every class fitting gives what it gave before (an exact module's
classes, else the signature's most common, the earliest of a tie); with the check, a class that does not fit is dropped and
counted, the signature's next most common taken, an exact module whose classes all differ falls back to the signature;
layout_kinds reads unset attributes as unknown and scaled formats as integers.
Then predict_first, cut out of vk_draw.cpp, in the builder's loop over a stand-in driver: the same pipelines are built as
with every prediction built, each once, and the repeats counted; with the switch at 0, every one built, as before.
And reads the source for the hooks and the switches table's row.

    python -I -B tests/test_predict_types.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

HEADER = r"""
#include <cstdio>
#include "predict_types.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace predict_types;
static void op(std::vector<uint32_t>& w, uint32_t code, std::initializer_list<uint32_t> args) {
    w.push_back(((uint32_t)args.size() + 1) << 16 | code);
    w.insert(w.end(), args);
}
int main() {
    CHECK(mode(nullptr) == 1 && mode("") == 1 && mode("0") == 0 && mode("1") == 2 && mode("2") == 1);
    CHECK(!once(0) && once(1) && once(2) && !typed(0) && !typed(1) && typed(2));
    std::vector<uint32_t> w = {0x07230203, 0x10000, 0, 40, 0};
    op(w, 22, {1, 32});            // %1 float
    op(w, 21, {2, 32, 0});         // %2 uint
    op(w, 21, {3, 32, 1});         // %3 int
    op(w, 23, {4, 1, 4});          // %4 vec4
    op(w, 23, {5, 2, 4});          // %5 uvec4
    op(w, 23, {6, 3, 2});          // %6 ivec2
    op(w, 28, {14, 5, 1});         // %14 uvec4[1] (an array of vectors)
    op(w, 32, {7, 1, 4});          // %7 Input vec4*
    op(w, 32, {8, 1, 5});          // %8 Input uvec4*
    op(w, 32, {9, 1, 6});          // %9 Input ivec2*
    op(w, 32, {15, 1, 14});        // %15 Input uvec4[1]*
    op(w, 32, {16, 1, 3});         // %16 Input int* (the built-in's)
    op(w, 32, {17, 3, 4});         // %17 Output vec4*
    op(w, 71, {10, 30, 0});        // %10 Location 0
    op(w, 71, {11, 30, 1});        // %11 Location 1
    op(w, 71, {12, 30, 3});        // %12 Location 3
    op(w, 71, {18, 30, 5});        // %18 Location 5
    op(w, 71, {13, 11, 42});       // %13 BuiltIn VertexIndex (no Location)
    op(w, 71, {19, 30, 2});        // %19 Location 2, an output
    op(w, 59, {7, 10, 1});         // OpVariable %10 Input
    op(w, 59, {8, 11, 1});
    op(w, 59, {9, 12, 1});
    op(w, 59, {15, 18, 1});
    op(w, 59, {16, 13, 1});
    op(w, 59, {17, 19, 3});
    const Locations in = locations(w);
    CHECK(in.mask == 0x2B && in.ints == 0x2A && in.sign == 0x08);
    Kind k[16] = {};
    k[0] = Kind::Float, k[1] = Kind::Uint, k[3] = Kind::Sint, k[5] = Kind::Uint;
    CHECK(fits(in, k));
    k[2] = Kind::Sint;                                   // (a location the module does not read)
    CHECK(fits(in, k));
    k[1] = Kind::Float;                                  // (a uint input against a float attribute)
    CHECK(!fits(in, k));
    k[1] = Kind::Sint;                                   // (the other signedness)
    CHECK(!fits(in, k));
    k[1] = Kind::Unknown;                                // (unset: reads zeros, as in play)
    CHECK(fits(in, k));
    k[0] = Kind::Uint;                                   // (a float input against an integer attribute)
    CHECK(!fits(in, k));
    k[0] = Kind::Float, k[3] = Kind::Uint;
    CHECK(!fits(in, k));
    CHECK(locations({}).mask == 0 && locations({0x07230203, 0, 0, 0, 0, 0xFFFF0047}).mask == 0);   // (empty, broken)
    std::printf("ok\n");
    return 0;
}
"""

PREDICT = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "predict_types.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
namespace Shader { enum class AttributeType { Float, SignedInt, UnsignedInt, SignedScaled, UnsignedScaled, Disabled }; }
Shader::AttributeType attribute_type_of(uint32_t vattr) { return (Shader::AttributeType)(vattr & 7); }
struct NvnState { int nvattr; uint32_t vattr[16]; struct { uint32_t stride, divisor; } vstream[16]; };
struct PipeNote { uint64_t key; uint32_t topo, samples, n, color_format[8], depth_format; bool has_depth; NvnState s; };
namespace t {
/* CUT */
}
using namespace t;
int main() {
    size_t mis = 0;
    const auto all = [](const Class&) { return true; };
    Seen exact, sig;
    const Class a{1, 2}, b{3, 4}, c{5, 6};
    exact.add(a, {1, 0}), exact.add(b, {2, 0});
    sig.add(a, {1, 0}), sig.add(b, {2, 0}), sig.add(b, {3, 0}), sig.add(c, {4, 0}), sig.add(c, {5, 0});
    // every class fitting: what it gave before
    CHECK(candidates(&exact, &sig, all, &mis) == (std::vector<Class>{a, b}) && mis == 0);
    CHECK(candidates(nullptr, &sig, all, &mis) == (std::vector<Class>{b}) && mis == 0);   // (b and c tie: the earliest)
    CHECK(candidates(nullptr, nullptr, all, &mis).empty() && candidates(nullptr, &exact, all, &mis) == (std::vector<Class>{a}));
    // the check: a class that does not fit is dropped and counted
    const auto no_b = [&](const Class& x) { return x != b; };
    CHECK(candidates(&exact, &sig, no_b, &mis) == (std::vector<Class>{a}) && mis == 1);
    mis = 0;
    CHECK(candidates(nullptr, &sig, no_b, &mis) == (std::vector<Class>{c}) && mis == 1);  // (the next most common)
    mis = 0;
    const auto only_c = [&](const Class& x) { return x == c; };
    CHECK(candidates(&exact, &sig, only_c, &mis) == (std::vector<Class>{c}));                // (the exact all differ: the signature)
    const auto none = [](const Class&) { return false; };
    CHECK(candidates(&exact, &sig, none, &mis).empty());
    // layout_kinds: unset (past nvattr, or no stream) unknown, scaled as integers
    PipeNote n{};
    n.s.nvattr = 6;
    n.s.vattr[0] = 0;                        // float
    n.s.vattr[1] = 2;                        // unsigned int
    n.s.vattr[2] = 1;                        // signed int
    n.s.vattr[3] = 3;                        // signed scaled
    n.s.vattr[4] = 4 | (15u << 27);          // unsigned scaled, but no stream: unset
    n.s.vattr[5] = 4;                        // unsigned scaled
    n.s.vattr[6] = 2;                        // past nvattr: unset
    predict_types::Kind k[16];
    layout_kinds(n, k);
    using K = predict_types::Kind;
    CHECK(k[0] == K::Float && k[1] == K::Uint && k[2] == K::Sint && k[3] == K::Sint && k[4] == K::Unknown && k[5] == K::Uint && k[6] == K::Unknown);
    std::printf("ok\n");
    return 0;
}
"""

ONCE = r"""
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <set>
#include <unordered_set>
#include <vector>
#include "predict_types.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using VkPrimitiveTopology = int;
struct NvnState { uint32_t stride, blend; };
struct PipeNote { uint64_t prog, variant; uint32_t topo; NvnState s; };
struct Targets { int n; };
struct Program { uint64_t key, variant; };
Targets note_targets(const PipeNote&) { return {1}; }
// (as play keys a pipeline: the stride is dynamic and not in it)
uint64_t pipeline_key(const Program& p, const NvnState& s, const Targets&, VkPrimitiveTopology topo) {
    return p.key * 1000003u ^ p.variant * 7919u ^ (uint64_t)topo * 131u ^ s.blend;
}
std::multiset<uint64_t> driver;   // (every pipeline the stand-in driver was asked to build, by key)
uint64_t build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo) {
    driver.insert(pipeline_key(p, s, at, topo));
    return 1;
}
std::atomic<int64_t> st_predict_twice{0};
/* CUT */
int main(int argc, char** argv) {
    const bool as_before = argc > 1 && argv[1][0] == '0';
    // two programs' predictions: layouts that differ by stride alone give the same pipeline
    std::map<uint64_t, std::vector<PipeNote>> by_program;
    for (uint64_t prog : {10ull, 20ull})
        for (uint64_t variant : {0ull, 1ull})
            for (uint32_t stride : {12u, 16u, 24u})
                for (uint32_t blend : {0u, 5u}) by_program[prog].push_back(PipeNote{prog, variant, 3, NvnState{stride, blend}});
    std::set<uint64_t> wanted;
    size_t asked = 0;
    for (const auto& kv : by_program)
        for (const PipeNote& n : kv.second) wanted.insert(pipeline_key(Program{n.prog, n.variant}, n.s, note_targets(n), (int)n.topo)), asked++;
    // the builder's loop: a program borrowed, each of its variants handed over, its notes of that variant built
    for (const auto& kv : by_program) {
        std::unordered_set<uint64_t> seen;
        for (uint64_t variant : {0ull, 1ull}) {
            Program p{kv.first, variant};
            for (const PipeNote& n : kv.second)
                if (n.variant == p.variant && predict_first(seen, p, n)) build_graphics(p, n.s, note_targets(n), (int)n.topo);
        }
    }
    const std::set<uint64_t> got(driver.begin(), driver.end());
    CHECK(got == wanted);   // (the same pipelines either way)
    if (as_before) {
        CHECK(driver.size() == asked && st_predict_twice == 0);
    } else {
        CHECK(driver.size() == wanted.size() && wanted.size() == 8 && st_predict_twice == (int64_t)(asked - wanted.size()));
    }
    std::printf("ok\n");
    return 0;
}
"""


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


def compile_run(cxx, tmp, name, text, runs):
    src, exe = tmp / (name + ".cpp"), tmp / (name + ".exe")
    src.write_text(text, encoding="utf-8")
    subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I" + str(ROOT / "gpu/vk"),
                    str(src), "-o", str(exe)], check=True)
    base = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    for arg, env in runs:
        r = subprocess.run([str(exe)] + ([arg] if arg else []), capture_output=True, text=True, timeout=60, env={**base, **env})
        need(r.returncode == 0 and r.stdout.strip() == "ok", "%s %s: %s" % (name, arg, r.stdout.strip() or r.returncode))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    pred = (ROOT / "gpu/vk/vk_predict.cpp").read_text(encoding="utf-8")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need('#include "predict_types.h"' in pred and '#include "predict_types.h"' in draw, "predict_types.h is not included")
    head = pred.index("uint64_t fnv(")
    cut = pred[head:pred.index("} // namespace", head)]
    need("void layout_kinds(" in cut and "std::vector<Class> candidates(const Seen* exact, const Seen* sig, Fits fits, size_t* misfits)" in cut,
         "vk_predict.cpp: candidates or layout_kinds are not where the test cuts them")
    once = block(draw, "bool predict_first(std::unordered_set<uint64_t>& seen, const Program& p, const PipeNote& n) {")
    with tempfile.TemporaryDirectory(prefix="predict-types-") as tmp:
        tmp = Path(tmp)
        compile_run(args.cxx, tmp, "header", HEADER, [("", {})])
        compile_run(args.cxx, tmp, "predict", PREDICT.replace("/* CUT */", cut), [("", {})])
        compile_run(args.cxx, tmp, "once", ONCE.replace("/* CUT */", once),
                    [("", {}), ("1", {"RX_VK_PREDICT_TYPES": "1"}), ("0", {"RX_VK_PREDICT_TYPES": "0"})])
    pp = block(pred, "std::vector<std::unique_ptr<PipeNote>> predict_pipelines(")
    ordered(pp, ['static const bool typed = predict_types::typed(predict_types::mode(getenv("RX_VK_PREDICT_TYPES")));',
                 "if (typed) f.vs_in = predict_types::locations(spirv);", "tally.no_face++;",
                 "if (!typed || !f.vs_in.mask) return true;", "layout_kinds(*vdonor.at(c), kinds);", "return predict_types::fits(f.vs_in, kinds);",
                 "candidates(find(vh, f.vs), find(vsig, f.vs_locs), vertex_fits, &tally.misfits);",
                 "candidates(find(fh, f.fs), find(fsig, f.fs_locs), any, &tally.misfits);", "if (counts) *counts = tally;"],
            "predict_pipelines does not check the layouts' types only under the switch, or does not count")
    need('static const bool once = predict_types::once(predict_types::mode(getenv("RX_VK_PREDICT_TYPES")));' in once,
         "predict_first does not read the switch once")
    run = block(draw, "void predict_run(void (*progress)(size_t done, size_t total)) {")
    ordered(run, ["predict_pipelines(notes, &programs, &plan, &left);", "std::unordered_set<uint64_t> seen;", "program_cache_borrow(keys[i],",
                  "lent = true;", "if (n->variant == p.variant && predict_first(seen, p, *n))", "build_graphics(p, n->s,",
                  "if (!lent) st_predict_unlent.fetch_add(1", "left.no_face, left.misfits);"],
            "predict_run does not build each pipeline once, or does not count")
    bg = block(draw, "void predict_background() {")
    ordered(bg, ["std::unordered_set<uint64_t> seen;", "program_cache_borrow(keys[i],", "lent = true;", "const auto build = [&](const PipeNote* n) {",
                 "if (!predict_first(seen, p, *n)) return;", "build_graphics(p, n->s,", "if (!lent) st_predict_unlent.fetch_add(1",
                 "predicted_done(pstamp, keys[i]);"],
            "predict_background does not build each pipeline once, or does not count")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_PREDICT_TYPES=1` or `0`" in docs, "docs/development.md: the switches table has no RX_VK_PREDICT_TYPES row")
    print("PASS: each predicted pipeline built once (the same pipelines); RX_VK_PREDICT_TYPES=1 drops layouts whose types differ; "
          "0 as before")


if __name__ == "__main__":
    main()
