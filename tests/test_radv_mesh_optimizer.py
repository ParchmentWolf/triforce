"""Task and mesh pipelines on RADV built with the driver's optimizer (gpu/vk/vk_draw.cpp mesh_opt_switch, mesh_unoptimized,
mesh_opt_recipe, build_graphics, warmed_stamp_of; RX_VK_MESH_OPT; no game/GPU).

On AMD's own drivers the optimizer hung the GPU minutes into Kokiri (RX 6600), so their task and mesh pipelines are built without
it. On RADV it is the other way round: built without it, the culling task programs timed out the ring at the save load.

The three functions are cut out of vk_draw.cpp unchanged and compiled with a stand-in device, one run a case: unset, RADV builds
with the optimizer and every other AMD driver without; =0 without on every AMD driver, RADV too (the rule before); =1 and any
other value with it everywhere; NVIDIA and Intel never without. The stamp word: only on RADV with native mesh shaders and the
switch unset (not on the task + mesh fallback, not with =0 or =1, not on AMD's own drivers). The source: build_graphics asks
mesh_unoptimized for task and mesh stages; the cloth rule and the retry without the optimizer are as they were; warmed_stamp_of
adds kMeshOptRecipe only when asked, warmed_stamp and libraries_stamp ask mesh_opt_recipe, warm_skip_carry tries the 8
combinations of the three words; the docs row is there.

    python -I -B tests/test_radv_mesh_optimizer.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

RADV, AMD_PRO, AMD_OPEN, NV, INTEL = 3, 1, 2, 4, 6   # (VkDriverId values: MESA_RADV, AMD_PROPRIETARY, AMD_OPEN_SOURCE, NVIDIA, Intel Mesa)

FIXTURE = r'''#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
enum VkDriverId { VK_DRIVER_ID_AMD_PROPRIETARY = 1, VK_DRIVER_ID_AMD_OPEN_SOURCE = 2, VK_DRIVER_ID_MESA_RADV = 3,
                  VK_DRIVER_ID_NVIDIA_PROPRIETARY = 4, VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA = 6 };
struct { struct { uint32_t vendorID; } props; VkDriverId driver_id; bool mesh_shader, task_mesh_fallback; } dev;
@CUT@
int main(int argc, char** argv) {
    dev.props.vendorID = (uint32_t)strtoul(argv[1], nullptr, 16);
    dev.driver_id = (VkDriverId)atoi(argv[2]);
    dev.mesh_shader = atoi(argv[3]) != 0;
    dev.task_mesh_fallback = atoi(argv[4]) != 0;
    std::printf("%d %d\n", (int)mesh_unoptimized(), (int)mesh_opt_recipe());
    return 0;
}
'''

# (vendor, driver, native mesh, task + mesh fallback, RX_VK_MESH_OPT or None) -> (built without the optimizer, stamp word)
CASES = [
    (("1002", RADV, 1, 0, None), (0, 1)),
    (("1002", RADV, 0, 0, None), (0, 0)),       # (no mesh shaders: the fallback's compute, no word)
    (("1002", RADV, 1, 1, None), (0, 0)),       # (the task + mesh fallback: no word)
    (("1002", AMD_PRO, 1, 0, None), (1, 0)),
    (("1002", AMD_OPEN, 1, 0, None), (1, 0)),
    (("1002", RADV, 1, 0, "0"), (1, 0)),
    (("1002", AMD_PRO, 1, 0, "0"), (1, 0)),
    (("1002", RADV, 1, 0, "1"), (0, 0)),
    (("1002", AMD_PRO, 1, 0, "1"), (0, 0)),
    (("1002", AMD_PRO, 1, 0, "yes"), (0, 0)),
    (("10DE", NV, 1, 0, None), (0, 0)),
    (("10DE", NV, 1, 0, "0"), (0, 0)),
    (("8086", INTEL, 1, 0, None), (0, 0)),
]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def fail(message):
    raise SystemExit("FAIL: " + message)


def cut(draw):
    return "\n".join(block(draw, m) for m in ("int mesh_opt_switch() {", "bool mesh_unoptimized() {", "bool mesh_opt_recipe() {"))


def check_source(draw, dev):
    build = block(draw, "VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, "
                        "int part, bool* cold) {")
    rule = build[build.index("if (mesh_unoptimized()) {"):]
    rule = rule[:rule.index("#ifdef _WIN32")]
    if "VK_SHADER_STAGE_TASK_BIT_EXT | VK_SHADER_STAGE_MESH_BIT_EXT" not in rule or \
            "ci.flags |= VK_PIPELINE_CREATE_DISABLE_OPTIMIZATION_BIT;" not in rule:
        fail("build_graphics no longer builds task and mesh stages without the optimizer where mesh_unoptimized says")
    if 'getenv("RX_VK_MESH_OPT") != nullptr' in draw:
        fail("RX_VK_MESH_OPT is read as set or not again (=0 would turn the optimizer on)")
    for needle in ("if (p.key == 0x5fa56485a6b07619ull) {",
                   "if (driver.driverID == VK_DRIVER_ID_AMD_PROPRIETARY) ci.flags |= VK_PIPELINE_CREATE_DISABLE_OPTIMIZATION_BIT;",
                   "if (dev.props.vendorID == 0x1002 && dev.task_mesh_fallback && !p.mesh && part < 0 && r == VK_ERROR_UNKNOWN &&"):
        if needle not in build:
            fail("build_graphics's cloth rule or retry changed: " + needle)
    stamp = block(draw, "uint64_t warmed_stamp_of(bool libraries, uint32_t patches, bool rate, bool mesh_opt) {")
    if "if (mesh_opt) add(&kMeshOptRecipe, sizeof kMeshOptRecipe);" not in stamp:
        fail("warmed_stamp_of does not add kMeshOptRecipe only when asked")
    if "warmed_stamp_of(libraries, module_patches(), false, mesh_opt_recipe());" not in block(draw, "uint64_t warmed_stamp(bool libraries) {"):
        fail("warmed_stamp does not ask mesh_opt_recipe")
    if "libraries && dev.foliage_rate, mesh_opt_recipe());" not in block(draw, "uint64_t libraries_stamp(bool libraries) {"):
        fail("libraries_stamp does not ask mesh_opt_recipe")
    carry = block(draw, "void warm_skip_carry(const std::string& skip, bool libraries, uint64_t now) {")
    if "for (int k = 0; k < 8; k++) {" not in carry or "(k & 4) != 0);" not in carry:
        fail("warm_skip_carry does not try the stamp with and without kMeshOptRecipe")
    if "`RX_VK_MESH_OPT=1` or `=0`" not in dev:
        fail("docs/development.md has no RX_VK_MESH_OPT row")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    try:
        check_source(draw, dev)
        text = FIXTURE.replace("@CUT@", cut(draw))
    except ValueError as e:
        fail("a text this test reads moved, or is not there (%s)" % e)
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    problems = []
    with tempfile.TemporaryDirectory(prefix="radv-mesh-opt-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(text, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Werror", str(cpp), "-o", str(exe)],
                               capture_output=True, text=True, creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        base = {k: v for k, v in os.environ.items() if k != "RX_VK_MESH_OPT"}
        for (vendor, driver, mesh, fallback, switch), want in CASES:
            env = dict(base, **({"RX_VK_MESH_OPT": switch} if switch is not None else {}))
            done = subprocess.run([str(exe), vendor, str(driver), str(mesh), str(fallback)], env=env, capture_output=True, text=True,
                                  timeout=60, creationflags=flags)
            got = tuple(int(x) for x in done.stdout.split()) if not done.returncode else None
            if got != want:
                problems.append("%s driver %d mesh %d fallback %d RX_VK_MESH_OPT=%r: %s, wanted %s"
                                % (vendor, driver, mesh, fallback, switch, got, want))
    if problems:
        fail("\n  ".join([""] + problems))
    print("PASS: task and mesh pipelines with the optimizer on RADV, without it on AMD's own drivers; =0 the rule before, =1 with "
          "it everywhere; the stamp word on RADV with native mesh only; cloth rule and retry unchanged (%d cases)" % len(CASES))


if __name__ == "__main__":
    main()
