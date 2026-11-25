"""How many of the GPU driver's compute compiles run at once (gpu/vk/compute_gate.h, used by gpu/vk/vk_draw.cpp ComputeTurn).

Compile and run the rule and the gate (tests/compute_gate_test.cpp): the budget the available memory gives, one compile always
starting when none runs, the weights, the cgroup's room, and the gate under threads. And the wiring: every guarded compute
creation takes a turn first (guarded_compute), and the gate is set by the memory only on Mesa's Intel driver and on RADV with
an integrated GPU on a PC with under 13 GB of RAM (compute_gate_radv); RX_VK_COMPUTE_AT_ONCE says otherwise on any GPU.

No Vulkan, GPU or game. python -I -B tests/test_compute_gate.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    at = draw.index("VkResult guarded_compute(VkPipelineCache cache")
    body = draw[at:draw.index("\n}\n", at)]
    if body.find("const ComputeTurn turn(*ci);") < 0 or body.find("const ComputeTurn turn(*ci);") > body.find("guarded_compute_once("):
        raise SystemExit("guarded_compute no longer takes the memory gate's turn before it compiles")
    gate = draw[draw.index("compute_gate::Gate& compute_compiles() {"):draw.index("bool compute_pinned(")]
    if "} else if (intel || compute_gate_radv()) {" not in gate:
        raise SystemExit("the gate's default is no longer Mesa's Intel driver's and RADV's on a small integrated PC alone")
    if gate.count("gate.set(") != 2:
        raise SystemExit("the gate is set somewhere else: any other GPU must keep no limit unless RX_VK_COMPUTE_AT_ONCE asks")
    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    if "return compute_gate::radv_by_memory(true, ram_mb);" not in shader:
        raise SystemExit("compute_gate_radv no longer asks compute_gate.h's rule")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="compute-gate-") as tmp:
        exe = Path(tmp) / "compute-gate"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS", "-pthread",
                        str(ROOT / "tests/compute_gate_test.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=120)
    print("ok")


if __name__ == "__main__":
    main()
