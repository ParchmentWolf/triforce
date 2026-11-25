# SPDX-License-Identifier: GPL-3.0-or-later
"""When kept programs are loaded (gpu/vk/load_default.h): RX_VK_LOAD=create or start always wins; without it start, as the game
has always loaded them (Triforce's default); RX_VK_LOAD=auto at their create calls where no earlier session left the marker (with
mesh shaders or through the compute fallback); the safety net's limits against the measured sessions (only long waits count, one
bad session leaves a strike, two running the marker); the marker and the strike written and found. And the
source: the choice is made once the device is up, the module identifiers' extension is asked for only with the switch, a first
use's time with a load goes through the safety net, and a preparation removes the marker. Compiled and run alone: no game or GPU
is needed.
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def check_source():
    main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    made = main.index("load_device(dev.device);")
    if "programs_load_decide(dev.mesh_shader && !dev.mesh_fallback && !dev.task_mesh_fallback);" not in main[made:made + 800]:
        raise SystemExit("the load mode is not decided once the device is made, from its mesh shaders")
    if "if (programs_load_asked()) optional(VK_EXT_SHADER_MODULE_IDENTIFIER_EXTENSION_NAME, module_id);" not in main:
        raise SystemExit("the module identifiers' extension is asked for without RX_VK_LOAD")
    progs = (ROOT / "gpu/vk/vk_programs.cpp").read_text(encoding="utf-8")
    wait = progs[progs.index("void programs_load_wait(uint64_t key) {"):]
    wait = wait[:wait.index("\n}\n")]
    if "load_wait_note(ns);" not in wait:
        raise SystemExit("a first use's time with a load does not reach the safety net")
    for rule in ("load_default::choose(env, native_mesh, marker, precompile_wanted())", "load_default::waits_verdict(",
                 "load_default::marker_counts(kind, ram_mb)"):
        if rule not in progs:
            raise SystemExit("vk_programs.cpp does not use load_default.h's rule: " + rule)
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    prep = draw[draw.index("void state_list_prepare(void (*progress)(size_t done, size_t total)) {"):]
    prep = prep[:prep.index("const auto t0")]
    for removed in ('remove((pipe_notes_path() + ".covered").c_str());', "remove(load_fallback_path().c_str());",
                    'remove((load_fallback_path() + ".waited").c_str());'):
        if removed not in prep:
            raise SystemExit("a preparation does not remove the covered marker, triforce_load_start.txt and its strike: " + removed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="load-default-") as tmp:
        exe = Path(tmp) / "load-default"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS",
                        str(ROOT / "tests/load_default_test.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe), tmp], check=True, timeout=60)


if __name__ == "__main__":
    main()
