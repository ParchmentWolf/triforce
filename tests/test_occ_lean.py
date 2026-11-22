"""The occlusion proxies' census (gpu/vk/occ_lean.h, RX_VK_OCC_LEAN=3; the performance audit's DESC-82, after Source B's: its
first step; no game, no GPU).

The rules, compiled and run: only 3 turns the census on (1 and 2, the lean pipelines and their check, are not built); each
refusal class refuses, in its order, and a draw with none is lean; the census counts draws and fragment descriptors by
class from several threads, its line gives them a frame and a draw, and the counts start again. Each rule taken out in turn
(a mutation) fails. Then the sources: draw() notes a draw only when an occlusion query is open on its thread after
occ_draw_begin and the draw writes no colour, with the switch; the note reads the fragment stage's Shader::Info and the
state's alpha to coverage and alpha test; the line every 600 presents; and nothing that makes a pipeline, its key or its
descriptors reads the census.

    python -I -B tests/test_occ_lean.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(text, parts, where):
    at = 0
    for part in parts:
        found = text.find(part, at)
        if found < 0:
            raise SystemExit("%s: %r is missing, or not after the part before it (update the test with the code)" % (where, part))
        at = found + len(part)


TEST = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include "occ_lean.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace occ_lean;
int main() {
    CHECK(mode_of(nullptr) == 0 && mode_of("") == 0 && mode_of("0") == 0 && mode_of("1") == 0 && mode_of("2") == 0 && mode_of("3") == 3);
    CHECK(mode_of("x") == 0 && mode_of("4") == 0);
    Facts f;
    CHECK(classify(f) == kLean);
    // (each refusal refuses, and the first that applies names the class)
    { Facts g; g.has_fragment = false; g.depth_out = true; CHECK(classify(g) == kNoFragment); }
    { Facts g; g.depth_out = true; g.stores = true; CHECK(classify(g) == kDepth); }
    { Facts g; g.sample_mask = true; CHECK(classify(g) == kSampleMask); }
    { Facts g; g.demote = true; g.a2c = true; CHECK(classify(g) == kDemote); }
    { Facts g; g.stores = true; CHECK(classify(g) == kStores); }
    { Facts g; g.image_writes = true; CHECK(classify(g) == kImageWrites); }
    { Facts g; g.atomics = true; CHECK(classify(g) == kAtomics); }
    { Facts g; g.global = true; CHECK(classify(g) == kGlobal); }
    { Facts g; g.a2c = true; g.alpha_test = true; CHECK(classify(g) == kA2c); }
    { Facts g; g.alpha_test = true; CHECK(classify(g) == kAlphaTest); }
    // (the counts, from two threads, and the line)
    Census c;
    std::thread t([&c] { for (int i = 0; i < 1000; i++) c.note(kLean, 3); });
    for (int i = 0; i < 1000; i++) c.note(kLean, 3);
    t.join();
    for (int i = 0; i < 600; i++) c.note(kDemote, 5);
    CHECK(c.draws[kLean].load() == 2000 && c.descriptors[kLean].load() == 6000 && c.draws[kDemote].load() == 600);
    char line[1024];
    CHECK(c.line(line, sizeof line, 600) > 0);
    CHECK(std::strstr(line, "600 presents): 4 colour-off counted draws a frame; lean 3 a frame with 3.00 fragment descriptors each"));
    CHECK(std::strstr(line, "; demote 1 (5.00 descriptors each)") && !std::strstr(line, "stores"));
    CHECK(c.draws[kLean].load() == 0 && c.descriptors[kDemote].load() == 0);
    CHECK(c.line(line, sizeof line, 600) > 0 && std::strstr(line, ": 0 colour-off counted draws a frame; lean 0 a frame with 0.00"));
    char small[40];
    c.note(kStores, 1);
    CHECK(c.line(small, sizeof small, 1) > 0 && std::strlen(small) < sizeof small);
    std::puts("PASS occ_lean.h: the switch (3 only), each refusal in its order, the counts from two threads, the line, the reset");
    return 0;
}
'''

MUTATIONS = [
    ("only the census is built", "return e && *e && std::atoi(e) == 3 ? 3 : 0;", "return e && *e ? std::atoi(e) : 0;"),
    ("no fragment stage first", "    if (!f.has_fragment) return kNoFragment;\n", ""),
    ("depth out refuses", "    if (f.depth_out) return kDepth;\n", ""),
    ("demote refuses", "    if (f.demote) return kDemote;\n", ""),
    ("stores refuse", "    if (f.stores) return kStores;\n", ""),
    ("alpha to coverage refuses", "    if (f.a2c) return kA2c;\n", ""),
    ("the alpha test refuses", "    if (f.alpha_test) return kAlphaTest;\n", ""),
    ("the counts start again", "d[i] = draws[i].exchange(0, std::memory_order_relaxed)", "d[i] = draws[i].load(std::memory_order_relaxed)"),
]


def check_source(draw, draw_h, replay, dev):
    d = block(draw, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d) {")
    in_order(d, ["if (occ_live && ps.open && (writes & 0xFF)) occ_draw_colour(cmd);", "if (occ_live && ps.open) occ_draw_begin(cmd);",
                 "if (occ_live && ps.open && !(writes & 0xFF) && occ_lean_census_on() && occ_counting()) occ_lean_note(p, s);"],
             "vk_draw.cpp draw(): the census after the query may begin, for colour-off draws it counts")
    if d.count("occ_lean") != 2:
        raise SystemExit("vk_draw.cpp draw(): the census is asked in a place this test does not know")
    note = block(draw, "void occ_lean_note(const Program& p, const NvnState& s) {")
    in_order(note, ["if (st.vk_stage == VK_SHADER_STAGE_FRAGMENT_BIT) fs = &st;", "f.has_fragment = fs != nullptr;",
                    "f.depth_out = i.stores_frag_depth, f.sample_mask = i.stores_sample_mask, f.demote = i.uses_demote_to_helper_invocation;",
                    "f.stores = i.stores_global_memory;", "f.stores = f.stores || d.is_written",
                    "f.image_writes = i.uses_typeless_image_writes;", "f.atomics = i.uses_global_increment", "i.uses_atomic_image_u32;",
                    "f.global = i.uses_global_memory;", "f.a2c = s.ms.a2c != 0;",
                    "f.alpha_test = s.color.alpha_func != 0 && s.color.alpha_func != NVN_ALPHA_FUNC_ALWAYS;",
                    "occ_lean::census.note(occ_lean::classify(f), descriptors);"], "vk_draw.cpp occ_lean_note")
    on = block(draw, "bool occ_lean_census_on() {")
    if 'occ_lean::mode_of(e) == 3' not in on or 'getenv("RX_VK_OCC_LEAN")' not in on:
        raise SystemExit("vk_draw.cpp occ_lean_census_on: not RX_VK_OCC_LEAN=3 read once")
    if "bool occ_counting();" not in draw_h or "bool occ_lean_census_on();" not in draw_h:
        raise SystemExit("vk_draw.h: occ_counting and occ_lean_census_on are not declared")
    if "bool occ_counting() { return occ_ctr().open >= 0; }" not in replay:
        raise SystemExit("vk_replay.cpp: occ_counting is not whether the thread's count has a query open")
    tick = block(replay, "void status_tick() {")
    in_order(tick, ["if (occ_lean_census_on()) {", "if (++presents % 600 == 0) {", "occ_lean::census.line(line, sizeof line, 600);"],
             "vk_replay.cpp status_tick: the census's line every 600 presents")
    # (no pipeline, key or descriptor reads it: the census changes nothing drawn)
    for marker in ("uint64_t pipeline_key(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo) {",
                   "VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, int part, bool* cold) {",
                   "void build_descriptors(const NvnState& s, const Program& p, bool keep = false, bool scene = false) {"):
        if marker not in draw:
            raise SystemExit("vk_draw.cpp: %r moved (update the test with the code)" % marker)
        if "occ_lean" in block(draw, marker):
            raise SystemExit("vk_draw.cpp %s reads the census: it must change no pipeline" % marker)
    if "RX_VK_OCC_LEAN" not in dev:
        raise SystemExit("docs/development.md: RX_VK_OCC_LEAN is not in the switches table")


def build(cxx, d, name, include):
    cpp, exe = d / (name + ".cpp"), d / (name + ".exe")
    cpp.write_text(TEST, encoding="utf-8")
    r = subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-format-truncation",
                        "-pthread", "-I" + str(include), str(cpp), "-o", str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return (exe, "") if r.returncode == 0 else (None, r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    a = ap.parse_args()
    check_source((VK / "vk_draw.cpp").read_text(encoding="utf-8"), (VK / "vk_draw.h").read_text(encoding="utf-8"),
                 (VK / "vk_replay.cpp").read_text(encoding="utf-8"), (ROOT / "docs" / "development.md").read_text(encoding="utf-8"))
    print("PASS sources: the census in draw() for colour-off draws a query counts, the note's facts, the switch, the line, "
          "no pipeline reads it, the row")
    header = (VK / "occ_lean.h").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="occ-lean-") as tmp:
        d = Path(tmp)
        exe, out = build(a.cxx, d, "lean", VK)
        if not exe:
            raise SystemExit("the build failed:\n" + out)
        r = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        if r.returncode:
            raise SystemExit("the test failed:\n" + r.stdout)
        print(r.stdout.strip())
        for i, (what, old, new) in enumerate(MUTATIONS):
            if header.count(old) != 1:
                raise SystemExit("mutation %r: its text is not once in occ_lean.h (update the test with the header)" % what)
            inc = d / ("mutant%d" % i)
            inc.mkdir()
            (inc / "occ_lean.h").write_text(header.replace(old, new), encoding="utf-8")
            exe, out = build(a.cxx, d, "mutant%d" % i, inc)
            if exe:
                r = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
                if r.returncode == 0:
                    raise SystemExit("mutation %r: the test still passed without it" % what)
        print("PASS mutations: %d rules of the census, each taken out, fail the test" % len(MUTATIONS))


if __name__ == "__main__":
    main()
