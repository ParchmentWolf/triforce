"""Without mirrors nothing is noted for a write-back that never comes (gpu/vk/vk_memory.cpp wb_notes_off, memory_cpu_owned,
shadow_written_to, guest_cpu_wrote; no game, no GPU).

(Triforce, 11-22, the performance audit's MEM-51, after Source A's.) The three functions note the CPU's writes for a
mirror's write-back: the replay's own report words, which the write-back leaves out, and the pages the write-back diff's
shadows must read again. Without mirrors (Intel's integrated GPUs, RX_VK_MIRROR=0) no write-back reads them: the lists
grew to 65,536 words and 8 million pages, were dropped and grew again.

tests/mirror_bookkeeping_test.cpp gets the functions cut from the source and is built twice, from the code as it is and
from the code with the new condition taken out (the code as it was):
  - mirrors on: after each of 40 rounds of 3,000 random calls every list is the same in both builds, entry for entry
    (size and hash), and so are the host's page look-ups and writes: nothing changes where there are mirrors;
  - mirrors off: every list stays empty, guest_cpu_wrote looks no guest page up, guest_cpu_write still writes. The build
    of the code as it was fails this case, so the case means something;
  - before the device is made mirror_on() is not asked (it decides once, by the card) and everything is noted.

And reads the source, for the invariant the skip rests on: the two readers (cut_cpu_words, shadows_forget_written) are
called once each, inside memory_end_submission's `if (!writebacks.empty())`; the only writebacks.push_back is in
gpu_buffer_bind after its `!mirror_on()` return; mirror_make is called only after such a return; shadow_make needs a
mirror; mirror_on() reads its switch once.

    python -I -B tests/test_mirror_bookkeeping.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    check(marker in text, "vk_memory.cpp has no " + marker)
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
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")

    # the three early returns
    off = block(mem, "bool wb_notes_off() {")
    check(off == "bool wb_notes_off() { return dev.device != VK_NULL_HANDLE && !mirror_on(); }", "wb_notes_off is not: the device made and no mirrors")
    owned = block(mem, "void memory_cpu_owned(uint64_t guest, uint64_t size) {")
    check("if (off || !guest || wb_notes_off()) return;" in owned and owned.index("wb_notes_off()") < owned.index("std::lock_guard lk(cpu_words_mu);"),
          "memory_cpu_owned notes words without mirrors, or takes its lock first")
    to = block(mem, "void shadow_written_to(std::vector<uint32_t>& list, const uint32_t* pages, int64_t n) {")
    check("if (n <= 0 || !wb_diff_on() || wb_notes_off()) return;" in to and to.index("wb_notes_off()") < to.index("std::lock_guard lk(shadow_written_mu);"),
          "shadow_written_to notes pages without mirrors, or takes its lock first")
    wrote = block(mem, "void guest_cpu_wrote(uint64_t gpu, uint64_t n) {")
    check("if (!n || !wb_diff_on() || wb_notes_off()) return;" in wrote and wrote.index("wb_notes_off()") < wrote.index("host->gpu_guest(a)"),
          "guest_cpu_wrote looks guest pages up without mirrors")

    # the invariant: no write-back, and so no reader, without mirrors
    end = block(mem, "void memory_end_submission(VkCommandBuffer cmd) {")
    wb = block(end, "if (!writebacks.empty()) {")
    check(mem.count("cut_cpu_words(") == 2 and "cut_cpu_words(*p, runs);" in wb, "cut_cpu_words is called outside the write-back")
    check(mem.count("shadows_forget_written()") == 2 and "shadows_forget_written();" in wb, "shadows_forget_written is called outside the write-back")
    bind = block(mem, "BufferRef gpu_buffer_bind(uint64_t gpu, uint64_t size, bool written) {")
    gate = "if (!mirror_on() || !mirror_upload || p->mstate == Pool::MIRROR_REFUSED) {"
    # (every write-back is queued in gpu_buffer_bind, after its return without mirrors: one push, or (Triforce) the split
    # write-back's push of each part beside it)
    check(mem.count("writebacks.push_back(") == bind.count("writebacks.push_back(") >= 1 and gate in bind and
          "return remember(in_guest({p->buffer, off, size, 0}));" in block(bind, gate) and
          bind.index(gate) < bind.index("writebacks.push_back("), "a write-back is queued before gpu_buffer_bind's return without mirrors")
    check(mem.count("mirror_make(*p)") == 2 and bind.index(gate) < bind.index("mirror_make(*p)"), "gpu_buffer_bind makes a mirror before its return without mirrors")
    begin = block(mem, "void memory_begin_submission() {")
    check("if (!mirror_on()) return;" in begin and begin.index("if (!mirror_on()) return;") < begin.index("for (Pool* p : mirror_wanted) mirror_make(*p);"),
          "memory_begin_submission makes mirrors before its return without mirrors")
    check("if (!p.mirror || !shadow_room(n)) return false;" in block(mem, "bool shadow_make(Pool& p) {"), "a shadow is made for a pool without a mirror")
    on = block(mem, "bool mirror_on() {")
    check("static const int on = [] {" in on and 'getenv("RX_VK_MIRROR")' in on, "mirror_on() is not fixed for the run")

    cut = "\n".join(block(mem, m) for m in (
        "bool wb_notes_off() {", "void sorted_merge(", "void cpu_words_merge() {", "void memory_cpu_owned(uint64_t guest, uint64_t size) {",
        "void shadow_written_to(std::vector<uint32_t>& list, const uint32_t* pages, int64_t n) {",
        "void shadow_written(const uint32_t* pages, int64_t n) {", "void shadow_written_collected(const uint32_t* pages, int64_t n) {",
        "int guest_cpu_write(uint64_t gpu, const void* src, uint64_t n) {", "void guest_cpu_wrote(uint64_t gpu, uint64_t n) {"))
    check(cut.count(" || wb_notes_off()") == 3, "the three early returns do not ask wb_notes_off()")
    before = cut.replace(" || wb_notes_off()", "")   # (the code as it was)
    fixture = (ROOT / "tests" / "mirror_bookkeeping_test.cpp").read_text(encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="mirror-bookkeeping-") as tmp:
        exes = {}
        for name, code in (("now", cut), ("before", before)):
            src, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
            src.write_text(fixture.replace("/* ACTUAL */", code), encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Wno-unused-function", str(src), "-o", str(exe)], check=True)
            exes[name] = str(exe)

        def run(name, case):
            return subprocess.run([exes[name], case], env=env, capture_output=True, text=True, timeout=300)

        now, was = run("now", "dump"), run("before", "dump")
        check(now.returncode == 0 and was.returncode == 0, "with mirrors:\n" + now.stdout + was.stdout)
        check(now.stdout == was.stdout and now.stdout.count("\n") == 40 * 7, "with mirrors the lists are not what they were")
        r = run("now", "off")
        check(r.returncode == 0, "without mirrors:\n" + r.stdout)
        check(run("before", "off").returncode != 0, "the code as it was passes the case without mirrors: the case checks nothing")
        r = run("now", "early")
        check(r.returncode == 0, "before the device is made:\n" + r.stdout)
    print("PASS: without mirrors nothing is noted for a write-back and no guest page is looked up; with mirrors every list is "
          "what it was")


if __name__ == "__main__":
    main()
