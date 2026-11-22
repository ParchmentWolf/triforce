"""Compute programs held to 32 lanes only where they can tell (gpu/vk/compute_pin.h; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-52, after Source A's and Source B's.) Every compute pipeline asked for
subgroups of 32 lanes. Mesa's Intel driver compiles such a program for 32 lanes only, minutes and gigabytes on the large
ones; most programs cannot tell how many lanes run beside them. On Mesa's Intel driver only the ones that can are pinned
now; every other driver keeps "all", its pipelines exactly as they were.

Compiles a small driver against the header and checks:
  the mode    unset: lanes on Mesa's Intel driver, all on any other; all / lanes / shared as written; an unknown value
              is the driver's default;
  all         every program pinned, whatever it is;
  lanes       each of the six flags pins by itself (vote, lane mask, lane index, shuffles, FSWZADD, matrices); a
              barrier of Subgroup scope pins, and so does a module nobody looked at (the default); shared memory pins at
              1, 32 invocations, not at 33 or 64; a program with none of these is free; a program without a stage is
              pinned;
  shared      as lanes, and shared memory pins at 64 and 4096 invocations too;
  the scan    a made-up module with OpControlBarrier at Subgroup scope: found; at Workgroup scope: not; none: not;
              a scope that is no constant, a cut-off module, a wrong magic word: counted as one (a doubt pins);
              compute_entry: a GLCompute entry point yes, a Fragment one no, no entry point no.

And reads the source: the four places that make a compute program's pipeline call pin_compute and no longer
pin_subgroup; build_graphics and the mesh fallback still call pin_subgroup; pin_compute with "all" is pin_subgroup with
the workgroup's width, before anything is asked or counted; the note is made in make_module between vk_shader.cpp's
"Outside the translation stamp" marks; and the switches table has the row.

    python -I -B tests/test_compute_pin.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "compute_pin.h"
#include <cstdio>
#include <vector>

using namespace compute_pin;
static int checks, fails;
static void want(const char* what, bool got, bool wanted) {
    checks++;
    if (got != wanted) fails++, printf("FAIL %s: %d, want %d\n", what, (int)got, (int)wanted);
}
// a program that sees nothing: its module looked at, no barrier, no shared memory
static Facts plain() {
    Facts f;
    f.has_stage = true, f.subgroup_barrier = false, f.invocations = 64;
    return f;
}
static std::vector<uint32_t> module(uint32_t model, int barrier_scope, bool constant_scope = true) {
    std::vector<uint32_t> m{0x07230203, 0x00010600, 0, 100, 0};
    const auto op = [&m](uint32_t code, std::initializer_list<uint32_t> words) {
        m.push_back((uint32_t)((words.size() + 1) << 16) | code);
        for (uint32_t w : words) m.push_back(w);
    };
    op(17, {1});                       // OpCapability Shader
    if (model != ~0u) op(15, {model, 4, 0x6e69616d, 0});   // OpEntryPoint <model> %4 "main"
    op(21, {2, 32, 0});                // %2 = OpTypeInt 32 0
    op(43, {2, 10, 2});                // %10 = OpConstant %2 2 (Workgroup)
    op(43, {2, 11, 3});                // %11 = OpConstant %2 3 (Subgroup)
    op(43, {2, 12, 0x100});            // %12 = semantics
    if (!constant_scope) op(50, {2, 13, 0});   // %13 = OpSpecConstant: no plain constant
    op(19, {3});                       // %3 = OpTypeVoid
    op(33, {5, 3});                    // %5 = OpTypeFunction %3
    op(54, {3, 4, 0, 5});              // %4 = OpFunction
    op(248, {6});                      // OpLabel
    if (barrier_scope) op(224, {(uint32_t)(constant_scope ? (barrier_scope == 3 ? 11 : 10) : 13), 10, 12});   // OpControlBarrier
    op(253, {});                       // OpReturn
    op(56, {});                        // OpFunctionEnd
    return m;
}

int main() {
    // the mode
    want("unset on Mesa's Intel driver: lanes", mode_for(nullptr, true) == Mode::Lanes, true);
    want("unset on any other driver: all", mode_for(nullptr, false) == Mode::All, true);
    for (int intel = 0; intel < 2; intel++) {
        want("all as written", mode_for("all", intel) == Mode::All, true);
        want("lanes as written", mode_for("lanes", intel) == Mode::Lanes, true);
        want("shared as written", mode_for("shared", intel) == Mode::Shared, true);
        want("an unknown value is the driver's default", mode_for("1", intel) == mode_for(nullptr, intel), true);
        want("an empty value is the driver's default", mode_for("", intel) == mode_for(nullptr, intel), true);
    }
    // all: everything pinned
    want("all: a plain program", needed(Mode::All, plain()), true);
    want("all: no stage", needed(Mode::All, Facts{}), true);
    // lanes and shared
    for (const Mode m : {Mode::Lanes, Mode::Shared}) {
        want("a plain program is free", needed(m, plain()), false);
        want("no stage: pinned", needed(m, Facts{}), true);
        Facts unknown;   // (a stage, but its module nobody looked at)
        unknown.has_stage = true, unknown.invocations = 64;
        want("a module nobody looked at: pinned", needed(m, unknown), true);
        bool Facts::* const flags[] = {&Facts::vote, &Facts::mask, &Facts::lane_index, &Facts::shuffles, &Facts::fswzadd,
                                       &Facts::matrices, &Facts::subgroup_barrier};
        for (bool Facts::* flag : flags) {
            Facts f = plain();
            f.*flag = true;
            want("each flag pins by itself", needed(m, f) && sees_lanes(f), true);
        }
        want("a plain program sees no lanes", sees_lanes(plain()), false);
        for (const uint64_t n : {1ull, 32ull, 33ull, 64ull, 4096ull}) {
            Facts f = plain();
            f.shared_memory = 256, f.invocations = n;
            want("shared memory by the workgroup's invocations", needed(m, f), m == Mode::Shared || n <= 32);
            f.shared_memory = 0;
            want("no shared memory: the workgroup's size alone pins nothing", needed(m, f), false);
        }
    }
    // the scan of a module
    const auto barrier = [](const std::vector<uint32_t>& m) { return subgroup_barrier(m.data(), m.size()); };
    want("a barrier of Subgroup scope", barrier(module(5, 3)), true);
    want("a barrier of Workgroup scope", barrier(module(5, 2)), false);
    want("no barrier", barrier(module(5, 0)), false);
    want("a scope that is no constant: a doubt", barrier(module(5, 3, false)), true);
    std::vector<uint32_t> cut = module(5, 0);
    cut.pop_back();
    cut.back() = (9u << 16) | 253;   // (an instruction longer than what is left)
    want("a cut-off module: a doubt", barrier(cut), true);
    std::vector<uint32_t> wrong = module(5, 0);
    wrong[0] = 0;
    want("a wrong magic word: a doubt", barrier(wrong), true);
    want("no module: a doubt", subgroup_barrier(nullptr, 0), true);
    const auto compute = [](const std::vector<uint32_t>& m) { return compute_entry(m.data(), m.size()); };
    want("a GLCompute entry point", compute(module(5, 0)), true);
    want("a Fragment entry point", compute(module(4, 0)), false);
    want("no entry point", compute(module(~0u, 0)), false);
    want("a wrong magic word is no compute module", compute(wrong), false);
    if (fails) printf("compute pin: FAILED (%d of %d checks)\n", fails, checks);
    else printf("compute pin: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    at = draw.find("void pin_compute(VkPipelineShaderStageCreateInfo& st, const Program& p) {")
    if at < 0:
        raise SystemExit("vk_draw.cpp has no pin_compute")
    pin = draw[at:draw.index("\n}\n", at)]
    first = "if (mode == compute_pin::Mode::All) return pin_subgroup(st, p.workgroup[0]);"
    if first not in pin or min(pin.find(n) for n in ("compute_pin::Facts f;", "st_pin_free++", "st_pin_pinned++")) < pin.index(first):
        raise SystemExit("pin_compute: with RX_VK_COMPUTE_PIN=all it is not pin_subgroup as it was, before anything is asked or counted")
    for needle in ("f.vote = i.uses_subgroup_vote", "f.mask = i.uses_subgroup_mask", "f.lane_index = i.uses_subgroup_invocation_id",
                   "f.shuffles = i.uses_subgroup_shuffles", "f.fswzadd = i.uses_fswzadd", "f.matrices = i.uses_cooperative_matrix",
                   "f.subgroup_barrier = !compute_lanes_free(st.module);", "f.shared_memory = p.shared_memory;",
                   "f.invocations = (uint64_t)p.workgroup[0] * p.workgroup[1] * p.workgroup[2];",
                   "if (!compute_pin::needed(mode, f)) {"):
        if needle not in pin:
            raise SystemExit("pin_compute does not fill the rule's facts: " + needle)
    if pin.index("if (!compute_pin::needed(mode, f)) {") > pin.rindex("pin_subgroup(st, p.workgroup[0]);"):
        raise SystemExit("pin_compute pins before it asks the rule")
    # the four makers of a compute program's pipeline, and the two that are not asked
    makers = (("bool prepare_compute_pipeline(Program& p) {", "pin_compute(ci.stage, p);"),
              ("VkComputePipelineCreateInfo compute_create_info(const Program& q) {", "pin_compute(ci.stage, q);"))
    for start, call in makers:
        body = draw[draw.index(start):]
        if call not in body[:body.index("\n}\n")]:
            raise SystemExit(start + " does not call pin_compute")
    if draw.count("pin_compute(ci.stage, p);") != 3 or draw.count("pin_compute(ci.stage, q);") != 1:
        raise SystemExit("wanted pin_compute at the four makers of a compute program's pipeline")
    if "pin_subgroup(ci.stage," in draw:
        raise SystemExit("a compute program's pipeline is still pinned by pin_subgroup directly")
    if draw.count("        pin_subgroup(si);\n") != 2:
        raise SystemExit("build_graphics and the mesh fallback's stages no longer call pin_subgroup")
    if "compute_pin_mode() != compute_pin::Mode::All)\n        logf(\"vk: precompile: compute pipelines held to 32 lanes" not in draw:
        raise SystemExit("the precompile does not log the pinned and free counts, only where the rule is asked")

    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    out_mark, in_mark = "// ---- (Triforce) Outside the translation stamp", "// ---- (Triforce) Inside the translation stamp again"
    lo = shader.index(out_mark)
    hi = shader.index(in_mark, lo)
    for needle in ("void lanes_note(VkShaderModule m, const std::vector<uint32_t>& code) {",
                   "if (!m || compute_pin_mode() == compute_pin::Mode::All) return;",
                   "lanes_note(m, code);", "compute_pin::Mode compute_pin_mode() {", "bool compute_lanes_free(VkShaderModule m) {",
                   'compute_pin::mode_for(env, dev.driver_id == VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA)'):
        found = shader.find(needle)
        if not lo < found < hi:
            raise SystemExit("vk_shader.cpp: not between the first pair of translation stamp marks: " + needle)
    if shader.count("compute_pin") != shader[lo:hi].count("compute_pin") or shader.count("lanes_") != shader[lo:hi].count("lanes_"):
        raise SystemExit("vk_shader.cpp names the rule outside the marks: the translation stamp would move")
    make = shader[shader.index("VkShaderModule make_module("):hi]
    if make.count("lanes_note(m, code);") != 2 or make.index("exact_note(m, code);") > make.index("lanes_note(m, code);"):
        raise SystemExit("make_module does not note each module it makes")
    header = (ROOT / "gpu/vk/vk_shader.h").read_text(encoding="utf-8")
    if '#include "compute_pin.h"' not in header or "compute_pin::Mode compute_pin_mode();" not in header:
        raise SystemExit("vk_shader.h does not declare compute_pin_mode")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `RX_VK_COMPUTE_PIN=all`, `lanes` or `shared` |" not in docs or "`gpu/vk/compute_pin.h`" not in docs:
        raise SystemExit("docs/development.md: the switches table has no row for RX_VK_COMPUTE_PIN")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="compute-pin-") as tmp:
        cpp, exe = Path(tmp) / "compute_pin_test.cpp", Path(tmp) / "compute-pin.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the compute pin's checks failed")


if __name__ == "__main__":
    main()
