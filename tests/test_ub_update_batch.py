"""A recording's uniform updates as copies of many regions from its stream, ordered where they overlap (gpu/vk/ub_batch.h,
vk_replay.cpp flush_ub_updates and flush_ub_batched; no game, no GPU).

(Triforce, 11-22, the performance audit's SYNC-21, after Source A's.) The flush wrote a vkCmdUpdateBuffer an update
between its two barriers, with nothing between two updates of the same bytes. RX_VK_UB_BATCH=1 copies each run of them
into one buffer with one vkCmdCopyBuffer; a run ends where a piece would write bytes the run already wrote, or where the
destination buffer changes, and the next starts behind a barrier. Off by default.

tests/ub_update_batch_test.cpp gets the flush, the batch and gpu_write cut from the source and runs 600 flushes a
scenario on a stand-in that records the commands and then applies them to memory in order:
  - batched: memory is the updates applied in stream order, in every scenario (aligned pieces in pools; any: unaligned
    pieces, pieces outside the pools, a second buffer onto another's memory; the stream full; the stream moved to another
    buffer); no copy's regions overlap; no byte written since the last barrier is written again;
  - as before (unset): only updates between the two barriers, two barriers a flush; with aligned pieces in pools its
    memory is the model's too, and it is the batched run's memory, byte for byte (hash);
  - the bindings asked for (address, size, written) are the same sequence either way, in every scenario;
  - RX_VK_UB_BATCH=2: the commands and the memory of the unset run, with the overlaps counted in the 600-flush line.
Then the rule is taken away a part at a time and the batched run must fail: the overlap rule, the destination rule, the
barrier between runs, and the copy before the stream's buffer changes.

And reads the source: the flush's order (the span, the first barrier, the batch or gpu_write as before, the last barrier),
the switch read once and off unless 1 or 2, the lab knob, the switches table.

    python -I -B tests/test_ub_update_batch.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]
SCENARIOS = ("aligned", "any", "full", "moved")


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    check(marker in text, "the source has no " + marker)
    start = text.index(marker)
    end = text.index("{", start + len(marker) - 1) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check((VK / "ub_batch.h").exists(), "gpu/vk/ub_batch.h is missing")
    header = (VK / "ub_batch.h").read_text(encoding="utf-8")
    rep = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    check('#include "ub_batch.h"' in rep, "vk_replay.cpp does not include ub_batch.h")

    # the source
    flush = block(rep, "void flush_ub_updates(VkCommandBuffer cmd, size_t lim = SIZE_MAX) {")
    order = [flush.find(s) for s in (
        "UbReadGuard ub_guard;", "const size_t end = std::min(lim, ub_updates.size());", "if (ub_first_of_recording >= end) return;",
        'GprofSpan gp(cmd, "ubupd (the stream\'s uniform updates -> guest memory, with its barriers)");',
        "gp.items = (int)(end - ub_first_of_recording);", "const int mode = ub_batch_mode();",
        'const bool batched = mode == 1 || lab_ab::on("ubbatch");', "full_barrier(cmd);", "if (batched) {",
        "flush_ub_batched(cmd, ub_first_of_recording, end, gp);", "} else {",
        "for (size_t i = ub_first_of_recording; i < end; i++)\n            gpu_write(cmd, ub_updates[i].dst, ub_updates[i].bytes.data(), "
        "ub_updates[i].bytes.size()), gp.bytes += ub_updates[i].bytes.size();",
        "full_barrier(cmd);\n    if (batched || mode == 2) ub_batch_line(batched);")]
    check(min(order) >= 0 and order == sorted(order), "flush_ub_updates: the guard, the span, the first barrier, the batch or the "
          "updates as before, the last barrier are not there in that order")
    check(flush.count("full_barrier(cmd);") == 2, "flush_ub_updates no longer has its two barriers")
    mode = block(rep, "int ub_batch_mode() {")
    check('getenv("RX_VK_UB_BATCH")' in mode and "static const int mode" in mode and "return v == 1 || v == 2 ? v : 0;" in mode,
          "RX_VK_UB_BATCH is not read once, or is on for anything but 1 and 2")
    batch = block(rep, "void flush_ub_batched(VkCommandBuffer cmd, size_t first, size_t end, GprofSpan& gp) {")
    barrier = "                    full_barrier(cmd);   // (the next run's writes come after this one's: the same bytes, or the same memory through another buffer)\n"
    before_copy = "                } else if (what == ub_batch::COPY || !s) {\n"
    for s in ("const BufferRef b = gpu_buffer_bind(gpu, k, true);", "guest_cpu_write(gpu, d, k), on_cpu++;", "const BufferRef s = stream_copy(d, k);",
              "run.before(s.buffer, b.buffer, b.offset, b.offset + k);", barrier, before_copy,
              "vkCmdCopyBuffer(cmd, run.src, run.dst, (uint32_t)regions.size(), regions.data());",
              "if ((b.offset & 3) || (k & 3)) guest_cpu_write(gpu, d, k);",
              "else vkCmdUpdateBuffer(cmd, b.buffer, b.offset, k, d), run.wrote(b.offset, b.offset + k);"):
        check(batch.count(s) == 1, "flush_ub_batched lost %r" % s.strip())
    check("full_barrier" not in batch.replace(barrier, ""), "flush_ub_batched has a barrier other than the one between runs")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_UB_BATCH=1`" in dev and "`ubbatch`" in dev, "docs/development.md: RX_VK_UB_BATCH=1 is not in the switches table")

    update = block(rep, "struct UbUpdate {") + ";"
    counts = "std::atomic<int64_t> st_ubb_flushes{0}, st_ubb_updates{0}, st_ubb_overlaps{0}, st_ubb_imports{0}, st_ubb_copies{0}, st_ubb_regions{0},\n    st_ubb_fallbacks{0}, st_ubb_cpu{0};"
    check(counts in rep, "vk_replay.cpp has no counts of the batch")
    cut = "\n".join([block(rep, "void gpu_write(VkCommandBuffer cmd, uint64_t gpu, const void* data, uint64_t n) {"), mode, counts,
                     block(rep, "void ub_batch_line(bool batched) {"), batch, flush])
    fixture = (ROOT / "tests" / "ub_update_batch_test.cpp").read_text(encoding="utf-8")
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}

    with tempfile.TemporaryDirectory(prefix="ub-update-batch-") as tmp:
        def build(name, code=cut, head=header):
            inc = Path(tmp) / (name + "-inc")
            inc.mkdir(exist_ok=True)
            (inc / "ub_batch.h").write_text(head, encoding="utf-8")
            src, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
            src.write_text(fixture.replace("/* ACTUAL-1 */", update).replace("/* ACTUAL-2 */", code), encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I" + str(inc), str(src), "-o", str(exe)], check=True)
            return str(exe)

        def run(exe, scenario, mode_value):
            env = dict(base_env)
            if mode_value:
                env["RX_VK_UB_BATCH"] = mode_value
            r = subprocess.run([exe, scenario], env=env, capture_output=True, text=True, timeout=300)
            lines = dict(l.split(" ", 1) for l in r.stdout.splitlines() if l.split(" ", 1)[0] in ("binds", "memory", "counts:", "line:"))
            return r.returncode, lines, r.stdout

        exe = build("now")
        for scenario in SCENARIOS:
            rc_old, old, out_old = run(exe, scenario, None)
            rc_new, new, out_new = run(exe, scenario, "1")
            rc_cnt, cnt, out_cnt = run(exe, scenario, "2")
            check(rc_old == 0, "%s as before:\n%s" % (scenario, out_old))
            check(rc_new == 0, "%s batched:\n%s" % (scenario, out_new))
            check(rc_cnt == 0, "%s counted:\n%s" % (scenario, out_cnt))
            check(old["binds"] == new["binds"] == cnt["binds"], "%s: the batch asks for other bindings than the updates did" % scenario)
            check(old["memory"] == cnt["memory"] and old["counts:"] == cnt["counts:"], "%s: RX_VK_UB_BATCH=2 changes what is written" % scenario)
            if scenario != "any":   # (aligned pieces in pools: the old way is in stream order too)
                check(old["memory"] == new["memory"], "%s: the batch leaves other bytes than the updates did" % scenario)
            check("600 flushes, batched" in new["line:"] and "600 flushes, as before, counted" in cnt["line:"] and not old["line:"].strip(),
                  "%s: the 600-flush line is not there with the switch at 1 and 2, or is there without it" % scenario)
            print("%-8s as before: %s" % (scenario, old["counts:"]))
            print("%-8s batched:   %s" % ("", new["counts:"]))

        # each part of the rule taken away: the batched run must fail somewhere
        mutations = (
            ("the overlap rule", cut, header.replace("        if (overlaps(at, end)) return RUN_OVERLAP;\n", "")),
            ("the destination rule", cut, header.replace("        if (d != dst) return RUN_IMPORT;\n", "")),
            ("the barrier between runs", cut.replace(barrier, ""), header),
            ("the copy before the stream's buffer changes", cut, header.replace("        if (pending && s != src) return COPY;\n", "")),
        )
        for name, code, head in mutations:
            check(code != cut or head != header, "the mutation %r changed nothing: the source moved" % name)
            mexe = build("mut-" + name.split()[1], code, head)
            failed = [s for s in SCENARIOS if run(mexe, s, "1")[0] != 0]
            check(failed, "without %s every batched scenario still passes: the fixture does not guard it" % name)
            print("without %s: %s fail%s" % (name, ", ".join(failed), "s" if len(failed) == 1 else ""))
    print("PASS: the uniform updates batched are the updates in stream order, no region over another, a barrier between two writes "
          "of the same bytes; unset, the flush is as before")


if __name__ == "__main__":
    main()
