"""Mesh-fallback compute stages too big for RADV on GCN or Mesa's Intel driver are not built (gpu/vk/fallback_size_policy.h).

(Triforce, 11-22, the performance audit's PIPE-56, after Source A's.) No game, no GPU. Every fallback stage went to the
driver; on those two drivers the largest ones took tens of GB and minutes and ended with the game killed. A program with
a stage over its driver's limit is now left out before anything is built, as a program the driver refused is.

Compiles a small driver against the header and checks:
  the counters   OpPhi is opcode 245 and OpFunctionCall 57; a made-up module with 3 phis and 2 calls counts 3 and 2;
                 a cut-off module, a wrong magic word and no module count 0 of both;
  the driver     RADV on GCN first, then Mesa's Intel driver, any other: none;
  the limits     GCN: 50,000 phis, no call limit; Mesa's Intel driver: 20,000 phis, 200 calls; any other driver: none,
                 whatever the switches say;
  the switches   unset, empty or not a number: the driver's own; 0: none; a number: that number;
  refused        just over a limit yes, at the limit no; 79,947 phis on GCN yes, on Mesa's Intel driver yes, on any other
                 driver no; 251 calls on Mesa's Intel driver yes, on GCN no; nothing with both limits 0.

And reads the source: fallback_compute_pipelines asks the rule after the failed-set lookup and before the first stage is
built, only where fallback_size_driver() names one of the two drivers, and puts the program into the failed set;
vk_shader.cpp counts in make_module, moves the counts in program_pack and forgets them in stage_module_destroy, all
between its first pair of "Outside the translation stamp" marks; and the switches table has the two rows.

    python -I -B tests/test_fallback_size_policy.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "fallback_size_policy.h"
#include <cstdio>
#include <initializer_list>
#include <vector>

using namespace fallback_size;
static int checks, fails;
static void want(const char* what, bool got, bool wanted) {
    checks++;
    if (got != wanted) fails++, printf("FAIL %s: %d, want %d\n", what, (int)got, (int)wanted);
}

int main() {
    want("OpPhi is 245", kOpPhi == 245, true);
    want("OpFunctionCall is 57", kOpFunctionCall == 57, true);
    std::vector<uint32_t> m{0x07230203, 0x00010600, 0, 100, 0};
    const auto op = [&m](uint32_t code, std::initializer_list<uint32_t> words) {
        m.push_back((uint32_t)((words.size() + 1) << 16) | code);
        for (uint32_t w : words) m.push_back(w);
    };
    op(17, {1});
    for (int i = 0; i < 3; i++) op(245, {2, 20u + i, 7, 8, 9, 10});   // OpPhi
    op(57, {3, 30, 4});                                              // OpFunctionCall
    op(57, {3, 31, 4, 30});
    op(253, {});
    want("3 phis", spirv_phis(m.data(), m.size()) == 3, true);
    want("2 calls", spirv_calls(m.data(), m.size()) == 2, true);
    std::vector<uint32_t> cut = m;
    cut.back() = (5u << 16) | 245;   // (the last instruction, one word, made one longer than what is left)
    want("a cut-off module counts 0", count(cut.data(), cut.size()).phis == 0 && count(cut.data(), cut.size()).calls == 0, true);
    std::vector<uint32_t> wrong = m;
    wrong[0] = 0;
    want("a wrong magic word counts 0", spirv_phis(wrong.data(), wrong.size()) == 0 && spirv_calls(wrong.data(), wrong.size()) == 0, true);
    want("no module counts 0", spirv_phis(nullptr, 0) == 0, true);

    want("RADV on GCN", driver_of(true, false) == Driver::RadvGcn, true);
    want("Mesa's Intel driver", driver_of(false, true) == Driver::MesaIntel, true);
    want("any other driver", driver_of(false, false) == Driver::Other, true);

    const Limits gcn = limits(Driver::RadvGcn, nullptr, nullptr), intel = limits(Driver::MesaIntel, nullptr, nullptr);
    want("GCN: 50,000 phis, no call limit", gcn.phis == 50000 && gcn.calls == 0, true);
    want("Mesa's Intel driver: 20,000 phis, 200 calls", intel.phis == 20000 && intel.calls == 200, true);
    for (const char* v : {(const char*)nullptr, "", "0", "5", "100000"}) {
        const Limits other = limits(Driver::Other, v, v);
        want("no limit on any other driver, whatever is set", other.phis == 0 && other.calls == 0, true);
        want("nothing refused on any other driver", refused(other, Size{4000000, 4000000}), false);
    }
    want("unset: the driver's own", parse_limit(nullptr, 50000) == 50000, true);
    want("empty: the driver's own", parse_limit("", 50000) == 50000, true);
    want("not a number: the driver's own", parse_limit("many", 50000) == 50000 && parse_limit("12x", 50000) == 50000, true);
    want("0: none", parse_limit("0", 50000) == 0, true);
    want("a number: that number", parse_limit("30000", 50000) == 30000, true);
    want("a number too large: the largest", parse_limit("99999999999", 5) == 0xffffffffu, true);
    const Limits set = limits(Driver::MesaIntel, "0", "300");
    want("the switches on Mesa's Intel driver", set.phis == 0 && set.calls == 300, true);

    want("just over the phi limit", refused(gcn, Size{50001, 0}), true);
    want("at the phi limit", refused(gcn, Size{50000, 0}), false);
    want("79,947 phis on GCN", refused(gcn, Size{79947, 12}), true);
    want("79,947 phis on Mesa's Intel driver", refused(intel, Size{79947, 12}), true);
    want("251 calls on Mesa's Intel driver", refused(intel, Size{100, 251}), true);
    want("200 calls on Mesa's Intel driver", refused(intel, Size{100, 200}), false);
    want("251 calls on GCN: no call limit there", refused(gcn, Size{100, 251}), false);
    want("both limits 0: nothing refused", refused(limits(Driver::RadvGcn, "0", "0"), Size{4000000, 4000000}), false);
    want("a stage nobody counted is built", refused(intel, Size{}) || refused(gcn, Size{}), false);
    if (fails) printf("fallback size policy: FAILED (%d of %d checks)\n", fails, checks);
    else printf("fallback size policy: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    at = draw.index("bool fallback_compute_pipelines(Program& p) {")
    body = draw[at:draw.index("\n}\n", at)]
    order = [body.find(n) for n in (
        "if (failed.count({p.key, p.variant})) return false;",
        "if (const fallback_size::Driver size_driver = fallback_size_driver(); size_driver != fallback_size::Driver::Other) {",
        'fallback_size::limits(size_driver, getenv("RX_VK_FALLBACK_PHI_LIMIT"), getenv("RX_VK_FALLBACK_CALL_LIMIT"));',
        "const fallback_size::Size size = stage_size(st);",
        "if (!fallback_size::refused(limits, size)) continue;",
        "failed.insert({p.key, p.variant});",
        "std::vector<VkPipeline> made(p.stages.size(), VK_NULL_HANDLE);",
        "guarded_compute(pcache_use().cache, &ci, &made[i])")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("fallback_compute_pipelines does not ask the size rule after the failed-set lookup and before the first "
                         "build, putting a program over the limit into the failed set")
    if "return false;" not in body[order[5]:order[6]]:
        raise SystemExit("fallback_compute_pipelines goes on to build a program the size rule put into the failed set")
    if body.count("failed.insert({p.key, p.variant});") != 2:
        raise SystemExit("fallback_compute_pipelines: wanted the failed set written by the size rule and by a refused build")
    if "size_told++ < 8" not in body:
        raise SystemExit("fallback_compute_pipelines: the size rule's log line is not capped at 8")

    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    out_mark, in_mark = "// ---- (Triforce) Outside the translation stamp", "// ---- (Triforce) Inside the translation stamp again"
    lo = shader.index(out_mark)
    hi = shader.index(in_mark, lo)
    between = shader[lo:hi]
    for needle in ("void size_note(VkShaderModule m, const std::vector<uint32_t>& code) {",
                   "if (!m || fallback_size_driver() == fallback_size::Driver::Other) return;",
                   "void size_move(VkShaderModule from, VkShaderModule to) {",
                   "size_move(st.module, (VkShaderModule)(uintptr_t)code.get());",
                   "fallback_size::Driver fallback_size_driver() {",
                   "fallback_size::driver_of(dev.radv_gcn, dev.driver_id == VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA);",
                   "fallback_size::Size stage_size(const Stage& st) {",
                   "const auto it = size_of.find(stage_exact_key(st));",
                   "size_of.erase(m);"):
        if needle not in between:
            raise SystemExit("vk_shader.cpp: not between the first pair of translation stamp marks: " + needle)
    if shader.count("fallback_size") != between.count("fallback_size") or shader.count("size_of") != between.count("size_of"):
        raise SystemExit("vk_shader.cpp names the size rule outside the marks: the translation stamp would move")
    make = between[between.index("VkShaderModule make_module("):]
    if make.count("size_note(m, code);") != 2:
        raise SystemExit("make_module does not count each module it makes")
    pack = between[between.index("void program_pack(Program& p) {"):]
    pack = pack[:pack.index("\n}\n")]
    if pack.index("exact_move(st.module,") > pack.index("size_move(st.module,") or \
            pack.index("size_move(st.module,") > pack.index("vkDestroyShaderModule(dev.device, st.module, nullptr);"):
        raise SystemExit("program_pack does not move a stage's counts with its key before the module goes")
    destroy = between[between.index("void stage_module_destroy(VkShaderModule m) {"):]
    if "size_of.erase(m);" not in destroy[:destroy.index("\n}\n")]:
        raise SystemExit("stage_module_destroy does not forget a module's counts")
    header = (ROOT / "gpu/vk/vk_shader.h").read_text(encoding="utf-8")
    for needle in ('#include "fallback_size_policy.h"', "fallback_size::Driver fallback_size_driver();",
                   "fallback_size::Size stage_size(const Stage& st);"):
        if needle not in header:
            raise SystemExit("vk_shader.h: no " + needle)
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `RX_VK_FALLBACK_PHI_LIMIT=<n>` |" not in docs or "| `RX_VK_FALLBACK_CALL_LIMIT=<n>` |" not in docs or \
            "`gpu/vk/fallback_size_policy.h`" not in docs:
        raise SystemExit("docs/development.md: the switches table lacks the two rows for the fallback's size limits")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="fallback-size-") as tmp:
        cpp, exe = Path(tmp) / "fallback_size_test.cpp", Path(tmp) / "fallback-size.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the fallback size policy's checks failed")


if __name__ == "__main__":
    main()
