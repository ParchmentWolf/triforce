"""A throwing shader/pipeline job must publish failure and wake its waiter on every execution path."""
import argparse
from pathlib import Path
import runpy
import re
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]


def recoveries(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    bodies = []
    for match in re.finditer(r"\[job\]\(\) noexcept \{", text):
        start = match.start()
        end = match.end()
        depth = 1
        while depth:
            depth += (text[end] == "{") - (text[end] == "}")
            end += 1
        bodies.append(text[start:end])
    return bodies


def resource_fixture():
    """Execute the production cleanup lambdas against small resource stand-ins."""
    shaders = recoveries("gpu/vk/vk_shader.cpp")
    draw = recoveries("gpu/vk/vk_draw.cpp")
    # ((Triforce) four in vk_draw.cpp: the graphics pipeline's two jobs (the libraries first, and the whole build first),
    # the mesh fallback's compute pipelines and a dispatch's compute pipeline)
    if len(shaders) != 2 or len(draw) != 4:
        raise SystemExit("a shader or pipeline resource recovery callback is missing")
    cases = []
    for callback in shaders:
        cases.append("{ Program p; auto job = std::make_shared<Job>(); job->p = &p; "
                     "auto recover = " + callback + "; recover(); "
                     "check(p.ready.load(std::memory_order_acquire) && p.failed); }")
    # (an entry is left ready by the rule of a whole build that failed, gpl_rules.h: with the link it had, else with none)
    for callback in draw[:2]:
        for pipeline in (0, 123):
            cases.append("{ PipeEntry e; e.pipeline = " + str(pipeline) + "; e.fast = " + str(pipeline) + "; "
                         "auto job = std::make_shared<Job>(); job->e = &e; "
                         "auto recover = " + callback + "; recover(); "
                         "check(e.ready.load(std::memory_order_acquire) && e.pipeline == " + str(pipeline) +
                         " && e.fast == " + str(pipeline) + "); }")
    # These two callbacks capture Program* directly rather than the translation/graphics Job.
    cases.append("{ Program p; p.compute_state = 1; auto* job = &p; auto recover = " + draw[2] + "; recover(); "
                 "check(p.compute_state.load(std::memory_order_acquire) == 2 && p.fallback_compute.empty()); }")
    # (a dispatch's: a pipeline published before the exception stays and the program is not failed; none: failed)
    cases.append("{ Program p; p.compute_state = 1; p.compute_pipeline = 123; const auto* job = &p; "
                 "auto recover = " + draw[3] + "; recover(); "
                 "check(p.compute_state.load(std::memory_order_acquire) == 2 && !p.failed && p.compute_pipeline == 123); }")
    cases.append("{ Program p; p.compute_state = 1; const auto* job = &p; "
                 "auto recover = " + draw[3] + "; recover(); "
                 "check(p.compute_state.load(std::memory_order_acquire) == 2 && p.failed && !p.compute_pipeline); }")
    return """#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <vector>
#include "gpl_rules.h"
constexpr uintptr_t VK_NULL_HANDLE = 0;
using VkPipeline = uintptr_t;
struct Program {
    bool failed = false;
    std::atomic<bool> ready{false};
    std::atomic<int> compute_state{0};
    uintptr_t compute_pipeline = 0;
    std::vector<uintptr_t> fallback_compute;
};
struct PipeEntry { std::atomic<uintptr_t> pipeline{0}, fast{0}; std::atomic<bool> ready{false}; };
struct Job { Program* p = nullptr; PipeEntry* e = nullptr; };
void check(bool ok) { if (!ok) std::abort(); }
int main() {
""" + "\n".join(cases) + "\n}\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    stubs = runpy.run_path(str(ROOT / "tests/test_jobs_wait_runs_queued.py"))
    with tempfile.TemporaryDirectory(prefix="jobs-failure-") as folder:
        folder = Path(folder)
        for name in ("vk_jobs.cpp", "vk_jobs.h", "cpu_count.h"):
            shutil.copy(ROOT / "gpu/vk" / name, folder / name)
        (folder / "vk_internal.h").write_text(stubs["STUB_INTERNAL"], encoding="utf-8")
        (folder / "vk_draw.h").write_text(stubs["STUB_DRAW"], encoding="utf-8")
        exe = folder / "jobs-failure.exe"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-pthread", "-I", str(folder),
                        str(folder / "vk_jobs.cpp"), str(ROOT / "tests/test_jobs_failure.cpp"), "-o", str(exe)], check=True)
        for mode in ("worker", "serial", "steal"):
            for kind in ([], ["nonstd"]):
                subprocess.run([str(exe), mode, *kind], check=True, timeout=10)
        fixture = folder / "resource-recovery.cpp"
        fixture.write_text(resource_fixture(), encoding="utf-8")
        resource_exe = folder / "resource-recovery.exe"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-I", str(ROOT / "gpu/vk"), str(fixture), "-o",
                        str(resource_exe)], check=True)
        subprocess.run([str(resource_exe)], check=True, timeout=10)
        print("PASS: production shader, graphics (null/linked), fallback and compute recovery states")


if __name__ == "__main__":
    main()
