"""The lab's low-end PC simulation (the performance audit's OS-49, after Source B's; no game, no GPU): HOS_SIM_CPU holds the
process to fewer cores (host/hos_sim_cpu.h) and the renderer sizes its pools by its threads (gpu/vk/cpu_count.h);
RX_VK_SIM_GPU_SLOW adds GPU time in proportion to the work measured (gpu/vk/sim_gpu.h, vk_replay.cpp sim_burn).

The rules, compiled and run: the switch's forms and the values refused; the mask on a 12-core, 24-thread map (6/12 takes the
last six), the floor of one core left out, the die with the largest L3 first, the fastest class first on a hybrid CPU, and the
core kept for the replay (host/hos_thread.c pick_reserved_core, cut out and run) inside every mask; the threads the
renderer takes, and cpu_count() under the variable; the factor's forms, the debt's rule and bounds, the plan net of the burns
in flight, the loop count and its calibration, and a run of the rule that reaches the factor asked within 10%. Each rule
taken out in turn (a mutation) fails. Then the sources: no hardware_concurrency() in gpu/ outside cpu_count.h and
vk_shader.cpp (a stamp file); the host applies the switch before any thread, filters the replay's core by it, sizes the
spinners by it and clears the variable when it does not apply it; the timestamps are two a recording without the switch and
three with it, the burn between the middle one and the end, between full barriers, in the replay's own recordings only, the
collection carrying what it measured; the shader's header was made from it; the docs rows.

    python -I -B tests/test_sim_cores.py [--cxx clang++]   (the host's header is compiled as C by the same driver: -x c)
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
HOST = ROOT / "host"


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


HOST_TEST = r'''
#include <stdio.h>
#include <stdlib.h>
#include "hos_sim_cpu.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
%PICK%
static int ncores;
static uint64_t masks[64];
static unsigned char classes[64];
static void add(int n, int per, int first, unsigned char cls) {
    for (int i = 0; i < n; i++) masks[ncores] = ((1ull << per) - 1) << (first + i * per), classes[ncores++] = cls;
}
int main(void) {
    HosSimCpu s = {0, 0};
    CHECK(hos_sim_cpu_parse("6/12", &s) && s.cores == 6 && s.threads == 12);
    CHECK(hos_sim_cpu_parse("4", &s) && s.cores == 4 && s.threads == 4);
    CHECK(hos_sim_cpu_parse("1/1", &s) && s.cores == 1 && s.threads == 1);
    CHECK(!hos_sim_cpu_parse(NULL, &s) && !hos_sim_cpu_parse("", &s) && !hos_sim_cpu_parse("x", &s) && !hos_sim_cpu_parse("6/", &s));
    CHECK(!hos_sim_cpu_parse("6/4", &s) && !hos_sim_cpu_parse("0/2", &s) && !hos_sim_cpu_parse("6/12x", &s) && !hos_sim_cpu_parse("300", &s));
    CHECK(!hos_sim_cpu_parse("-2/4", &s) && !hos_sim_cpu_parse("6/12/24", &s));
    /* (a 12-core, 24-thread processor of one kind: 6/12 takes the last six cores, and the replay's core is the last) */
    ncores = 0, add(12, 2, 0, 0);
    uint64_t m = hos_sim_cpu_mask(masks, classes, ncores, 0, 6);
    CHECK(m == 0xFFF000ull && hos_sim_cpu_count(m) == 12);
    CHECK(pick_reserved_core(masks, classes, ncores) & m);
    /* (one core always stays out; 0 and more than there are: not possible) */
    CHECK(hos_sim_cpu_mask(masks, classes, ncores, 0, 12) == 0 && hos_sim_cpu_mask(masks, classes, ncores, 0, 0) == 0);
    CHECK(hos_sim_cpu_mask(masks, classes, ncores, 0, 11) == 0xFFFFFCull && hos_sim_cpu_mask(masks, classes, ncores, 0, 1) == 0xC00000ull);
    /* (a two-die X3D part: the die with the largest L3 (the first eight cores here) first, its last cores) */
    ncores = 0, add(16, 2, 0, 0);
    const uint64_t die = 0xFFFFull;
    m = hos_sim_cpu_mask(masks, classes, ncores, die, 6);
    CHECK(m == 0xFFF0ull && (m & ~die) == 0);
    m = hos_sim_cpu_mask(masks, classes, ncores, die, 10);   /* (more than the die has: its eight, then the last of the other) */
    CHECK((m & die) == die && hos_sim_cpu_count(m) == 20 && (m & 0xF0000000ull) == 0xF0000000ull);
    /* (a hybrid processor: 8 performance cores with two threads, 16 efficiency cores after them: the performance ones) */
    ncores = 0, add(8, 2, 0, 1), add(16, 1, 16, 0);
    m = hos_sim_cpu_mask(masks, classes, ncores, 0, 6);
    CHECK(m == 0xFFF0ull && hos_sim_cpu_count(m) == 12);
    CHECK(pick_reserved_core(masks, classes, ncores) == 0xC000ull && (pick_reserved_core(masks, classes, ncores) & m));
    m = hos_sim_cpu_mask(masks, classes, ncores, 0, 10);   /* (all eight, then the last efficiency cores) */
    CHECK((m & 0xFFFFull) == 0xFFFFull && (m & 0xC0000000ull) == 0xC0000000ull && hos_sim_cpu_count(m) == 18);
    puts("PASS host: the switch's forms, the mask (6/12 of 12/24, the one-core floor, the die first, the fastest class first), the replay's core inside");
    return 0;
}
'''

VK_TEST = r'''
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include "cpu_count.h"
#include "sim_gpu.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
int main(int argc, char** argv) {
    using cpu_count_rule::sim_threads;
    CHECK(sim_threads("6/12", 24) == 12 && sim_threads("4", 24) == 4 && sim_threads("6/12", 0) == 12);
    CHECK(sim_threads(nullptr, 24) == 0 && sim_threads("", 24) == 0 && sim_threads("6/4", 24) == 0 && sim_threads("x", 24) == 0);
    CHECK(sim_threads("12/24", 24) == 0 && sim_threads("16/32", 24) == 0 && sim_threads("6/12z", 24) == 0);
    // (cpu_count() as the variable says: the second argument is what this process was started with)
    if (argc > 1) CHECK(cpu_count() == (unsigned)std::atoi(argv[1]));
    using namespace sim_gpu;
    CHECK(factor_of(nullptr) == 0 && factor_of("") == 0 && factor_of("1") == 0 && factor_of("0.5") == 0 && factor_of("11") == 0);
    CHECK(factor_of("2") == 2.0 && factor_of("2.5") == 2.5 && factor_of("10") == 10.0 && factor_of("2x") == 0);
    const int64_t ms = 1000000;
    // (the debt: the work's (factor - 1) share added, what the burn took taken off, held between its bounds)
    CHECK(held(owed(0, 6 * ms, 0, 2.0)) == 6 * ms && held(owed(6 * ms, 2 * ms, 5 * ms, 3.0)) == 5 * ms);
    CHECK(held(owed(0, 200 * ms, 0, 2.0)) == kDebtMost && held(owed(0, 0, 90 * ms, 2.0)) == kDebtLeast);
    // (the plan: owed less in flight, 1 to 16 ms)
    CHECK(plan_ns(6 * ms, 0) == 6 * ms && plan_ns(6 * ms, 5500000) == 0 && plan_ns(40 * ms, 4 * ms) == 16 * ms && plan_ns(-5 * ms, 0) == 0);
    CHECK(loops_for(0, 2.0) == 0 && loops_for(10 * ms, 2.0) == 5000000u && loops_for(1, 1e9) == 1u && loops_for(16 * ms, 0.0) > 0u);
    CHECK(std::fabs(calibrated(4.0, 2 * ms, 1000000) - 3.6) < 1e-9 && calibrated(4.0, 0, 100) == 4.0 && calibrated(0, 300, 100) == 3.0);
    // (a run: 4 recordings a frame of 1.6 ms of work each, factor 2, a loop truly 1.5 ns against the first guess of 4;
    // the burns are planned at recording ends and measured 3 recordings later, as the ring does)
    int64_t debt = 0, in_flight = 0, plan[3] = {0, 0, 0};
    uint32_t loops[3] = {0, 0, 0};
    double npl = kFirstNsPerLoop, work_all = 0, added_all = 0;
    for (int r = 0; r < 4000; r++) {
        const int s = r % 3;
        if (r >= 3) {   // (the slot's last use collected: its work and what its burn took)
            const int64_t work = 1600000, added = (int64_t)(loops[s] * 1.5);
            in_flight -= plan[s];
            debt = held(owed(debt, work, added, 2.0));
            if (plan[s]) npl = calibrated(npl, added, loops[s]);
            if (r > 1000) work_all += work, added_all += added;
        }
        const int64_t p = plan_ns(debt, in_flight);
        plan[s] = p, loops[s] = loops_for(p, npl), in_flight += p;
    }
    const double reached = (work_all + added_all) / work_all;
    if (!(reached > 1.8 && reached < 2.2) || std::fabs(npl - 1.5) > 0.15) {
        std::fprintf(stderr, "FAIL: the run reached x%.3f, a loop %.3f ns\n", reached, npl);
        return 1;
    }
    std::printf("PASS vk: the threads the renderer takes, cpu_count(), the factor, the debt and its bounds, the plan, the loops, "
                "a run reaching x%.2f of x2\n", reached);
    return 0;
}
'''

HOST_MUTATIONS = [
    ("one core stays out", "if (n > 256 || want < 1 || want > n - 1) return 0;", "if (n > 256 || want < 1 || want > n) return 0;"),
    ("the die first", "            if (on_i != on_best) {\n                if (on_i) best = i;\n                continue;\n            }\n", ""),
    ("the fastest class first", "            if (classes[i] != classes[best]) {\n                if (classes[i] > classes[best]) best = i;\n                continue;\n            }\n", ""),
    ("the last cores first", "if (masks[i] > masks[best]) best = i;", "if (masks[i] < masks[best]) best = i;"),
    ("threads not under cores", "if (*end || c < 1 || c > 256 || t < c || t > 256) return 0;", "if (*end || c < 1 || c > 256 || t > 256) return 0;"),
]
VK_MUTATIONS = [
    ("cpu_count: not fewer, not taken", "return hw && (unsigned)t >= hw ? 0 : (unsigned)t;", "return (unsigned)t;"),
    ("the factor over 1", "if (end == e || *end || !(f > 1.0) || f > 10.0) return 0;", "if (end == e || *end || f > 10.0) return 0;"),
    ("the burn taken off the debt", "return (double)debt + (double)work_ns * (factor - 1.0) - (double)added_ns;",
     "return (double)debt + (double)work_ns * (factor - 1.0);"),
    ("the debt's bounds", "inline int64_t held(double owed_ns) { return (int64_t)std::clamp(owed_ns, (double)kDebtLeast, (double)kDebtMost); }",
     "inline int64_t held(double owed_ns) { return (int64_t)owed_ns; }"),
    ("the burns in flight", "const int64_t o = debt - in_flight;", "const int64_t o = debt + 0 * in_flight;"),
    ("the calibration", "return ns_per_loop > 0 ? 0.8 * ns_per_loop + 0.2 * m : m;", "return ns_per_loop + 0 * m;"),
]


def check_source():
    # (no count of the PC's threads in gpu/ but through cpu_count(), and vk_shader.cpp's, a stamp file)
    for p in sorted((ROOT / "gpu").rglob("*")):
        if p.suffix not in (".cpp", ".h") or "third_party" in p.parts:
            continue
        if p.name in ("cpu_count.h", "vk_shader.cpp"):
            continue
        if "hardware_concurrency()" in p.read_text(encoding="utf-8", errors="replace"):
            raise SystemExit("%s: counts the PC's threads with hardware_concurrency(), not cpu_count() (cpu_count.h)" % p.relative_to(ROOT))
    shader = (VK / "vk_shader.cpp").read_text(encoding="utf-8")
    if "cpu_count" in shader:
        raise SystemExit("vk_shader.cpp: cpu_count() there would move the shader cache's stamp")
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    for name, text in (("vk_replay.cpp", replay), ("vk_draw.cpp", draw)):
        if '#include "cpu_count.h"' not in text:
            raise SystemExit("%s does not include cpu_count.h" % name)
    # (the host: before any thread, the replay's core inside, the spinners by it, the variable cleared when not applied)
    main = (HOST / "hos_main.c").read_text(encoding="utf-8")
    in_order(main, ["occlusion_switch();", "hos_sim_cpu_apply();", "const char *image = NULL;", "rx_prepare_shaders()"],
             "hos_main.c: HOS_SIM_CPU applied before the game and the preparation start threads")
    thread = (HOST / "hos_thread.c").read_text(encoding="utf-8")
    in_order(block(thread, "static uint64_t last_fastest_core(int *cores) {"),
             ["(!sim_cpu_mask || ((uint64_t)e->Processor.GroupMask[0].Mask & sim_cpu_mask))", "return pick_reserved_core(masks, classes, n);"],
             "hos_thread.c last_fastest_core: the replay's core inside the mask")
    apply = block(thread, "void hos_sim_cpu_apply(void) {")
    in_order(apply, ["#if defined(_WIN32)", "if (hos_sim_cpu_parse(e, &s)) {",
                     "mask = hos_sim_cpu_mask(masks, classes, n, hos_x3d_cpus(), s.cores);",
                     "if (mask && !SetProcessAffinityMask(GetCurrentProcess(), (DWORD_PTR)mask)) mask = 0;", "if (!mask) {",
                     'SetEnvironmentVariableA("HOS_SIM_CPU", NULL);', '_putenv("HOS_SIM_CPU=");', "return;", "sim_cpu_mask = mask;"],
             "hos_thread.c hos_sim_cpu_apply")
    if "vc_spin_most(sim_cpu_mask ? hos_sim_cpu_count(sim_cpu_mask) : (int)si.dwNumberOfProcessors)" not in block(thread, "static int vc_spin_max(void) {"):
        raise SystemExit("hos_thread.c vc_spin_max: not sized by the mask's processors")
    # (the GPU: two timestamps without the switch, three with it; the burn; the collection)
    if "static const int n = sim_gpu_factor() ? 3 : 2;" not in block(replay, "int ts_count() {"):
        raise SystemExit("vk_replay.cpp ts_count: not two a recording without the switch and three with it")
    if 'sim_gpu::factor_of(getenv("RX_VK_SIM_GPU_SLOW"))' not in block(replay, "double sim_gpu_factor() {"):
        raise SystemExit("vk_replay.cpp: RX_VK_SIM_GPU_SLOW is not read through sim_gpu::factor_of")
    begin = block(replay, "void gpu_time_begin(Recording& r) {")
    in_order(begin, ["qi.queryCount = ts_count() * kRecordings;", "qi.queryCount = 2 * kRecordings;",
                     "vkCmdResetQueryPool(r.cmd, ts_pool, ts_count() * r.slot, ts_count());",
                     "vkCmdWriteTimestamp2(r.cmd, VK_PIPELINE_STAGE_2_TOP_OF_PIPE_BIT, ts_pool, ts_count() * r.slot);"], "vk_replay.cpp gpu_time_begin")
    end = block(replay, "void gpu_time_end(Recording& r, bool uploads) {")
    in_order(end, ["if (!ts_pool) return;", "if (ts_count() == 3) sim_burn(r);",
                   "vkCmdWriteTimestamp2(r.cmd, VK_PIPELINE_STAGE_2_BOTTOM_OF_PIPE_BIT, ts_pool, ts_count() * r.slot + ts_count() - 1);"],
             "vk_replay.cpp gpu_time_end: the burn before the end's timestamp")
    burn = block(replay, "void sim_burn(Recording& r) {")
    in_order(burn, ["vkCmdWriteTimestamp2(r.cmd, VK_PIPELINE_STAGE_2_BOTTOM_OF_PIPE_BIT, ts_pool, 3 * r.slot + 1);",
                    "if (r.segment || !sim_ready()) return;", "const int64_t ns = sim_gpu::plan_ns(slow.debt, slow.in_flight);",
                    "const uint32_t loops = sim_gpu::loops_for(ns, slow.ns_per_loop);", "end_pass(r.cmd);",
                    "full_barrier(r.cmd,", "vkCmdDispatch(r.cmd, 1, 1, 1);", "full_barrier(r.cmd,", "slow.in_flight += ns"],
             "vk_replay.cpp sim_burn")
    collect = block(replay, "void sim_collect(const Recording& r, const uint64_t* t) {")
    in_order(collect, ["slow.in_flight -= plan", "if (!t || t[1] < t[0] || t[2] < t[1]) return;",
                       "const double o = sim_gpu::owed(slow.debt, work, added, sim_gpu_factor());", "slow.debt = sim_gpu::held(o);",
                       "if (plan) slow.ns_per_loop = sim_gpu::calibrated(slow.ns_per_loop, added, slow.loops[r.slot]);",
                       "std::chrono::seconds(10)"], "vk_replay.cpp sim_collect")
    gather = block(replay, "void gpu_time_collect(Recording& r) {")
    in_order(gather, ["const int tn = ts_count();", "vkGetQueryPoolResults(dev.device, ts_pool, tn * r.slot, tn, sizeof t, t, 8, VK_QUERY_RESULT_64_BIT)",
                      "if (tn == 3) sim_collect(r, got ? t : nullptr);", "const int64_t ns = (int64_t)((t[tn - 1] - t[0])"],
             "vk_replay.cpp gpu_time_collect: the GPU time from the start to the end, the burn inside it")
    # (the shader's header made from it)
    comp = (VK / "shaders" / "sim_gpu_burn.comp").read_text(encoding="utf-8")
    spv = (VK / "shaders" / "sim_gpu_burn_comp_spv.h").read_text(encoding="utf-8")
    if "--vn SIM_GPU_BURN_COMP_SPV -o sim_gpu_burn_comp_spv.h sim_gpu_burn.comp" not in comp or "const uint32_t SIM_GPU_BURN_COMP_SPV[] = {" not in spv \
            or "0x07230203" not in spv:
        raise SystemExit("gpu/vk/shaders: the burn's SPIR-V header is not the one sim_gpu_burn.comp names")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    for name in ("HOS_SIM_CPU", "RX_VK_SIM_GPU_SLOW"):
        if name not in dev:
            raise SystemExit("docs/development.md: %s is not in the switches table" % name)


def build(tool, d, name, src, includes, std, ext):
    path, exe = d / (name + ext), d / (name + ".exe")
    path.write_text(src, encoding="utf-8")
    cmd = [tool] + (["-x", "c"] if ext == ".c" else []) + [std, "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function"] + ["-I" + str(i) for i in includes] + [str(path), "-o", str(exe)]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return (exe, "") if r.returncode == 0 else (None, r.stdout)


def run(exe, args=(), env=None):
    return subprocess.run([str(exe)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120, env=env)


def mutate(d, tool, label, src, header_dir, header_name, mutations, std, ext, extra_inc):
    text = (header_dir / header_name).read_text(encoding="utf-8")
    for i, (what, old, new) in enumerate(mutations):
        if text.count(old) != 1:
            raise SystemExit("mutation %r: its text is not once in %s (update the test with the header)" % (what, header_name))
        inc = d / ("%s-mutant%d" % (label, i))
        inc.mkdir()
        (inc / header_name).write_text(text.replace(old, new), encoding="utf-8")
        exe, _ = build(tool, d, "%s-mutant%d" % (label, i), src, [inc] + extra_inc, std, ext)
        if exe and run(exe).returncode == 0:
            raise SystemExit("mutation %r: the test still passed without it" % what)
    return len(mutations)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    a = ap.parse_args()
    check_source()
    print("PASS sources: one thread count in gpu/, the host's switch before any thread with the replay's core and the spinners "
          "inside it, two timestamps without the GPU switch and three with it, the burn and its collection, the shader, the rows")
    pick = block((HOST / "hos_thread.c").read_text(encoding="utf-8"), "static uint64_t pick_reserved_core(")
    host_src = HOST_TEST.replace("%PICK%", pick)
    with tempfile.TemporaryDirectory(prefix="sim-cores-") as tmp:
        d = Path(tmp)
        exe, out = build(a.cxx, d, "host", host_src, [HOST], "-std=gnu11", ".c")
        if not exe:
            raise SystemExit("host: the build failed:\n" + out)
        r = run(exe)
        if r.returncode:
            raise SystemExit("the host test failed:\n" + r.stdout)
        print(r.stdout.strip())
        exe, out = build(a.cxx, d, "vk", VK_TEST, [VK], "-std=c++20", ".cpp")
        if not exe:
            raise SystemExit("vk: the build failed:\n" + out)
        r = run(exe)
        if r.returncode:
            raise SystemExit("the vk test failed:\n" + r.stdout)
        print(r.stdout.strip())
        if os.name == "nt":   # (cpu_count() reads the variable on Windows alone, as the host applies it there alone)
            env = dict(os.environ, HOS_SIM_CPU="1/1")
            if run(exe, ["1"], env).returncode:
                raise SystemExit("cpu_count(): HOS_SIM_CPU=1/1 did not give 1")
            env = dict(os.environ)
            env.pop("HOS_SIM_CPU", None)
            if run(exe, [str(os.cpu_count() or 0)], env).returncode:
                raise SystemExit("cpu_count(): without HOS_SIM_CPU it is not the PC's count")
            print("PASS cpu_count(): 1 under HOS_SIM_CPU=1/1, the PC's %d without it" % (os.cpu_count() or 0))
        n = mutate(d, a.cxx, "host", host_src, HOST, "hos_sim_cpu.h", HOST_MUTATIONS, "-std=gnu11", ".c", [])
        n += mutate(d, a.cxx, "vkc", VK_TEST, VK, "cpu_count.h", VK_MUTATIONS[:1], "-std=c++20", ".cpp", [VK])
        n += mutate(d, a.cxx, "vkg", VK_TEST, VK, "sim_gpu.h", VK_MUTATIONS[1:], "-std=c++20", ".cpp", [VK])
        print("PASS mutations: %d rules, each taken out, fail their tests" % n)


if __name__ == "__main__":
    main()
