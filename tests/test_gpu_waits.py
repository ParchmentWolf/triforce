"""The host's time in calls that block on the GPU, counted by kind at the Vulkan wait wrappers (gpu/vk/gpu_wait_kinds.h,
vk_work.h's five wrappers, vk_replay.cpp's line and the frame trace's column; no game, no GPU).

(Triforce, 11-22, the performance audit's SYNC-27, after Source A's.) The log's "GPU-bound wait" counts the waits for a
recording slot alone and reads about 0 while threads wait on the GPU elsewhere. Every blocking wait is now timed in one
place, vk_work.h, and summed by kind: fences, timelines, idle, queries.

tests/gpu_waits_test.cpp gets vk_work.h's wrappers cut from the source and runs them over stand-ins for the driver:
  - each wrapper passes its arguments and the driver's result through;
  - a fence or semaphore wait with timeout 0 and a query read without the wait bit count nothing; with a timeout above 0,
    the wait bit, or an idle, the time lands under its own kind and no other;
  - a wait inside a wait counts once, as the outer one; a wait inside an Exclude scope counts nothing, and the count
    comes back after the scope;
  - two readers each see every nanosecond and every wait, whenever they read;
  - four threads' 2,000 waits are all counted while a fifth sits in an Exclude scope;
  - RX_VK_GPU_WAITS=0: the calls are made as before and nothing is counted.

And reads the source: the five macros call their wrapper after the recorder's boundary and no other macro changed; the
low-latency sleep's wait is in an Exclude scope; the line after the 120-present line and the trace's column each have
their own reader; `lab` stays the trace's last column; the switches table has the row.

    python -I -B tests/test_gpu_waits.py [--cxx clang++]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]
WAITS = {"vkQueueWaitIdle": "queue_idle", "vkDeviceWaitIdle": "device_idle", "vkWaitForFences": "fences",
         "vkWaitSemaphores": "semaphores", "vkGetQueryPoolResults": "query_results"}


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check((VK / "gpu_wait_kinds.h").exists(), "gpu/vk/gpu_wait_kinds.h is missing")
    work = (VK / "vk_work.h").read_text(encoding="utf-8")
    check('#include "gpu_wait_kinds.h"' in work, "vk_work.h does not include gpu_wait_kinds.h")

    # the five macros, and only they
    macros = []
    for call, wrapper in WAITS.items():
        line = "#define %s(...) (::mkwvk::rec::boundary(::mkwvk::rec::B_%s), ::mkwvk::gpu_waits_vk::%s(::vkx::%s, __VA_ARGS__))" % (call, call, wrapper, call)
        check(line in work, "vk_work.h: %s does not call its timed wrapper, with the driver's call, after the recorder's boundary" % call)
        macros.append(line)
    timed_macros = re.findall(r"^#define (\w+)\(\.\.\.\) .*gpu_waits_vk::", work, re.M)
    check(sorted(timed_macros) == sorted(WAITS), "vk_work.h: the timed macros are not the five waits: %s" % timed_macros)
    start, end = work.index("namespace mkwvk::gpu_waits_vk {"), work.index("}   // namespace mkwvk::gpu_waits_vk")
    wrappers = work[start:end] + "}\n"
    check(start < work.index("#define vkCmdPipelineBarrier2("), "vk_work.h: the wrappers are below the macros they would be changed by")
    for name, kind, blocks, call in (("queue_idle", "IDLE", "true", "call(queue)"), ("device_idle", "IDLE", "true", "call(device)"),
                                     ("fences", "FENCE", "timeout != 0", "call(device, count, list, all, timeout)"),
                                     ("semaphores", "TIMELINE", "timeout != 0", "call(device, info, timeout)"),
                                     ("query_results", "QUERY", "(flags & VK_QUERY_RESULT_WAIT_BIT) != 0",
                                      "call(device, pool, first, count, size, data, stride, flags)")):
        pattern = r"inline VkResult %s\(Call&& call, [^{]*\{\s*return ::gpu_wait_kinds::timed\(::gpu_wait_kinds::%s, %s,\s*\[&\] \{ return %s; \}\);" % (
            name, kind, re.escape(blocks), re.escape(call))
        check(re.search(pattern, wrappers), "vk_work.h: %s is not timed as %s when %s" % (name, kind, blocks))
    check("::vkx::" not in wrappers, "vk_work.h: a wrapper names the driver's call itself: a file that never waits that way would need it declared")

    reflex = (VK / "vk_reflex.cpp").read_text(encoding="utf-8")
    at = reflex.index("vkWaitSemaphores(dev.device, &w, 100000000ull);")
    check("const ::gpu_wait_kinds::Exclude pacing;\n        vkWaitSemaphores(dev.device, &w, 100000000ull);" in reflex and
          reflex[at:at + 200].split("\n")[1].strip() == "}", "vk_reflex.cpp: the low-latency sleep's wait is not alone in an Exclude scope")
    check(reflex.count("vkWaitSemaphores(") == 1, "vk_reflex.cpp has another semaphore wait: excluded or not?")

    rep = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    order = [rep.find(s) for s in ("GPU-bound wait %.1f ms; ", "static ::gpu_wait_kinds::Reader waits;", "const int64_t all = waits.take(ns, n);",
                                   "if (::gpu_wait_kinds::on())", "vk: host waits for the GPU: %.2f ms a frame (fences %.2f, timelines %.2f, idle %.2f, queries %.2f;")]
    check(min(order) >= 0 and order == sorted(order), "vk_replay.cpp: the host waits' line is not after the 120-present line, from a reader of its own")
    tick = rep[rep.index("void status_tick() {"):]
    tick = tick[:tick.index("\n}\n")]
    order = [tick.find(s) for s in ("frame_trace::Split sp;", "static ::gpu_wait_kinds::Reader trace_waits;",
                                    "sp.gpu_waits = trace_waits.take(nullptr, nullptr) / 1e6;", "frame_trace::line(sp, split, sizeof split);",
                                    'snprintf(split_lab, sizeof split_lab, "%s,%d", split, lab_col);')]
    check(min(order) >= 0 and order == sorted(order), "status_tick: the trace's gpu_waits_ms is not this frame's, from a reader of its own, before lab")
    check('if (f) fputs(",lab\\n", f);' in tick and tick.index("frame_trace::kColumns);") < tick.index('if (f) fputs(",lab\\n", f);'),
          "status_tick: lab is no longer the trace's last column")
    # ((Triforce, 11-23) and the dynamic resolution's clock's, ts_dyn_present: tests/test_gpu_busy.py)
    check(rep.count("gpu_wait_kinds::Reader") == 3 and "static ::gpu_wait_kinds::Reader host_waits;" in rep,
          "vk_replay.cpp: the readers of the waits are not the line's, the trace's and the dynamic resolution's clock's")
    trace_h = (VK / "frame_trace.h").read_text(encoding="utf-8")
    check('wb_held_ms,qs_bg_ms,"\n    "gpu_waits_ms";' in trace_h and "s.qs_bg, s.gpu_waits);" in trace_h, "frame_trace.h: gpu_waits_ms is not the split's last column")
    kinds = (VK / "gpu_wait_kinds.h").read_text(encoding="utf-8")
    check('getenv("RX_VK_GPU_WAITS")' in kinds and "static const bool env" in kinds and "!(e && *e && atoi(e) == 0)" in kinds and
          'return env && !mkwvk::lab_ab::on("nogpuwaits");' in kinds, "RX_VK_GPU_WAITS is not read once, on unless 0, with the lab knob nogpuwaits")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_GPU_WAITS=0`" in dev and "`gpu_waits_ms`" in dev and "`nogpuwaits`" in dev,
          "docs/development.md: RX_VK_GPU_WAITS=0, the column gpu_waits_ms or the knob is not described")

    base_env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="gpu-waits-") as tmp:
        src, exe = Path(tmp) / "waits.cpp", Path(tmp) / "waits.exe"
        src.write_text((ROOT / "tests" / "gpu_waits_test.cpp").read_text(encoding="utf-8").replace("/* WRAPPERS */", wrappers).replace("/* MACROS */", "\n".join(macros)), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-pthread", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        for mode, env in (("on", base_env), ("off", dict(base_env, RX_VK_GPU_WAITS="0"))):
            r = subprocess.run([str(exe), mode], env=env, capture_output=True, text=True, timeout=120)
            print(r.stdout.rstrip())
            check(r.returncode == 0, "RX_VK_GPU_WAITS %s: the waits' checks failed" % mode)
    print("PASS: every blocking wait for the GPU is timed once under its kind; polls, pacing and RX_VK_GPU_WAITS=0 count nothing")


if __name__ == "__main__":
    main()
