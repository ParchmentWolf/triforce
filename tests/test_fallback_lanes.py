"""The lanes a mesh fallback compute stage runs at (gpu/vk/fallback_lanes.h): a stage with nothing that depends on its subgroup
(spirv_lane_free, read from its SPIR-V where the module is made: vk_shader.cpp size_note) runs at 8 lanes on Mesa's Intel
driver where the device can be held to 8, every other stage at 32; RX_VK_MESH_LANES=8, 16 or 32 over it.

No Vulkan, GPU or game. python -I -B tests/test_fallback_lanes.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def check_source():
    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    if "s.lane_free = fallback_lanes::spirv_lane_free(code.data(), code.size());" not in shader:
        raise SystemExit("vk_shader.cpp size_note: a compute module's lane-freedom is no longer read from its SPIR-V")
    main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    if "dev.subgroup_min = sc.minSubgroupSize;" not in main:
        raise SystemExit("vk_main.cpp: the fewest lanes a stage can be held to is no longer read")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    fn = draw[draw.index("bool fallback_compute_pipelines(Program& p) {"):]
    fn = fn[:fn.index("guarded_compute(pcache_use().cache, &ci, &made[i])")]
    # (the stage's own lanes replace the 32 pin_subgroup asked for, and only where the device can be asked at all)
    if not fn.index("pin_subgroup(si);") < fn.index("si.pNext = &lanes_size;") < fn.index("ci.stage = si;"):
        raise SystemExit("vk_draw.cpp: the fallback stage's lanes must be chosen after pin_subgroup and before the pipeline is asked for")
    header = (ROOT / "gpu/vk/fallback_lanes.h").read_text(encoding="utf-8")
    if "inline uint32_t lanes_of(bool lane_free, uint32_t wanted_lanes) { return lane_free ? wanted_lanes : 32; }" not in header:
        raise SystemExit("fallback_lanes.h: a stage that is not lane-free must run at 32 lanes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="fallback-lanes-") as tmp:
        exe = Path(tmp) / "fallback-lanes"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_fallback_lanes.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("ok")


if __name__ == "__main__":
    main()
