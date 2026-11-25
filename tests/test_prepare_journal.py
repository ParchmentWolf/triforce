"""The --prepare-shaders run's journal of its driver calls (gpu/vk/prepare_journal.h; no game, no GPU).

A run given a journal (--prepare-journal <file>, HOOKSHOT_PREPARE_JOURNAL) writes a line before and after each driver compile
call, so that a supervisor of the run (not in Triforce yet) can tell which shader a run died or hung in, leave it out
(--prepare-skip, HOOKSHOT_PREPARE_SKIP) and start the run again (--prepare-from). What must hold:
- the header, compiled and run here: the run line, a begin with the program as triforce_driver_faults.txt names it, an end
  with the result and the time, numbers going on from the run before, the oldest open entry overdue at its limit (none
  without a limit), the skip file's lines (comments and bad lines skipped), the test fault's forms;
- vk_draw.cpp: the entries around the three kinds of driver call (shader modules, graphics pipelines in build_graphics, every
  compute pipeline in guarded_compute), each skipped program answered without the driver, nothing of it unless the run is the
  preparation's own and was asked; vk_main.cpp's watch ends the run with kExitEntryLimit; the host sets the switches from the
  arguments and takes them for no image.

python -I -B tests/test_prepare_journal.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

PROGRAM = r"""
#include "prepare_journal.h"
#include <cstdio>
#include <string>
using namespace prepare_journal;
static int failed = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); failed++; } } while (0)
static std::string slurp(const std::string& p) {
    std::string t;
    if (FILE* f = std::fopen(p.c_str(), "rb")) {
        char b[4096];
        size_t n;
        while ((n = std::fread(b, 1, sizeof b, f)) > 0) t.append(b, n);
        std::fclose(f);
    }
    return t;
}
int main(int, char** argv) {
    const std::string path = std::string(argv[1]) + "/journal.txt";
    {
        Writer w;
        CHECK(!w.on());
        CHECK(w.begin(kGraphics, 1, 0, 0) == 0);   // (no journal: no entry)
        CHECK(w.open(path, 0x10de, 0x1234, 41));
        CHECK(w.on());
        const uint64_t a = w.begin(kModule, 0xabcdef, 0x40, 1000);
        const uint64_t b = w.begin(kCompute, 0, 0, 1500);
        CHECK(a == 42 && b == 43);                 // (numbers go on from the run before)
        CHECK(w.open_count() == 2);
        CHECK(w.overdue(0, 99999) == 0);           // (no limit)
        CHECK(w.overdue(5000, 5999) == 0);
        uint64_t program = 0;
        int64_t open_ms = 0;
        CHECK(w.overdue(5000, 6000, &program, &open_ms) == 42 && program == 0xabcdef && open_ms == 5000);
        w.end(a, 0, 1250);
        w.end(a, 0, 1300);                         // (twice: the second is no line)
        CHECK(w.open_count() == 1);
        w.end(b, -77, 1600);
        CHECK(w.open_count() == 0);
    }
    const std::string text = slurp(path);
    CHECK(text.find("run 10de 00001234 29\n") == 0);
    CHECK(text.find("b 2a module 000010de 00001234 0000000000abcdef 0000000000000040\n") != std::string::npos);
    CHECK(text.find("b 2b compute 000010de 00001234 0000000000000000 0000000000000000\n") != std::string::npos);
    CHECK(text.find("t 2a 5\n") != std::string::npos);
    CHECK(text.find("e 2a 0 250\n") != std::string::npos);
    CHECK(text.find("e 2b -77 100\n") != std::string::npos);
    CHECK(text.find("e 2a 0 300") == std::string::npos);
    FILE* pending = std::fopen((path + ".pending").c_str(), "rb");
    CHECK(!pending);                               // (every write finished: no marker left)
    if (pending) std::fclose(pending);
    const Asked asked = asked_parse("# a note\nskip 1a2b\nalone ff\nskip\nskip zz\nwhat 12\nskip 0\nalone 3 extra\n");
    CHECK(asked.skip.size() == 1 && asked.skip.count(0x1a2b));
    CHECK(asked.alone.size() == 1 && asked.alone.count(0xff));
    bool bad = false;
    TestFault t = test_fault_parse("crash:5", &bad);
    CHECK(!bad && t.mode == 1 && t.every == 5 && test_fault_here(t, 10) && !test_fault_here(t, 11) && !test_fault_here(t, 0));
    t = test_fault_parse("hang:=abc", &bad);
    CHECK(!bad && t.mode == 2 && t.key == 0xabc && test_fault_here(t, 0xabc) && !test_fault_here(t, 0xabd));
    t = test_fault_parse("boom:1", &bad);
    CHECK(bad && t.mode == 0);
    t = test_fault_parse(nullptr, &bad);
    CHECK(!bad && t.mode == 0);
    if (failed) return 1;
    std::printf("prepare_journal: all checks passed\n");
    return 0;
}
"""


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit(where + " no longer has: " + needle)


def body(text, head):
    start = text.index(head)
    return text[start:text.index("\n}\n", start)]


def check_source():
    vk = ROOT / "gpu/vk"
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    main = (vk / "vk_main.cpp").read_text(encoding="utf-8")
    host = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    need("vk_draw.cpp", draw, ['#include "prepare_journal.h"'])
    need("vk_draw.cpp: journal_wanted()", body(draw, "bool journal_wanted() {"),
         ['getenv("HOOKSHOT_PREPARE_ONLY")', 'getenv("HOOKSHOT_PREPARE_JOURNAL")', 'getenv("HOOKSHOT_PREPARE_SKIP")'])
    need("vk_draw.cpp: extern_guarded_shader_module()", body(draw, "VkResult extern_guarded_shader_module("),
         ["JournalEntry entry(prepare_journal::kModule, program, ci->codeSize);", "kPrepareSkip",
          "entry.end(guarded_module_once(ci, m))", "journal_module_note(*m, program)"])
    compute = body(draw, "VkResult guarded_compute(VkPipelineCache cache, const VkComputePipelineCreateInfo* ci, VkPipeline* pl) {")
    need("vk_draw.cpp: guarded_compute()", compute,
         ["JournalEntry entry(prepare_journal::kCompute, journal_wanted() ? journal_module_of(ci->stage.module) : 0, ci->flags);",
          "if (entry.skip) return *pl = VK_NULL_HANDLE, kPrepareSkip;", "return entry.end(r);",
          "return entry.end(made ? VK_SUCCESS : r);"])
    if compute.index("const ComputeTurn turn(*ci);") > compute.index("JournalEntry entry("):
        raise SystemExit("vk_draw.cpp: guarded_compute's entry begins before the memory gate's wait (that wait is not the driver's)")
    graphics = draw[draw.index("VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, int part, bool* cold) {"):]
    graphics = graphics[:graphics.index("\n}\n")]
    need("vk_draw.cpp: build_graphics()", graphics,
         ["JournalEntry entry(prepare_journal::kGraphics, p.key, ci.flags);", "if (entry.skip) {", "entry.end(r);"])
    if graphics.index("JournalEntry entry(") > graphics.index("VkResult r = cached_graphics(cache, &ci, &pl);"):
        raise SystemExit("vk_draw.cpp: build_graphics's entry begins after its driver call")
    need("vk_draw.cpp: prepare_restart_forgive()", body(draw, "void prepare_restart_forgive() {"),
         ['getenv("HOOKSHOT_PREPARE_FROM")', 'pipe_notes_path() + ".running"', 'precompile_covered_path() + ".warming"'])
    need("vk_main.cpp", main, ["std::_Exit(prepare_journal::kExitEntryLimit);", "prepare_supervised();",
                               'getenv("HOOKSHOT_PREPARE_ENTRY_S")'])
    need("host/hos_main.c", host, ['#include "prepare_args.h"', "hos_prepare_args_env(argc, argv);",
                                   "else if (hos_prepare_arg_switch(argv[i]) && i + 1 < argc) i++;"])
    if host.index("hos_prepare_args_env(argc, argv);") > host.index('else if (!strcmp(argv[i], "--prepare-shaders")) {'):
        raise SystemExit("host/hos_main.c: the switches are set after the preparation began")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="prepare-journal-") as tmp:
        src = Path(tmp) / "prepare_journal_test.cpp"
        src.write_text(PROGRAM, encoding="utf-8")
        exe = Path(tmp) / "prepare-journal"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-I" + str(ROOT / "gpu/vk"), str(src), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe), tmp], check=True)
    print("PASS: the preparation's journal: lines before and after each driver call, overdue entries, skips; its hooks in the "
          "renderer and the host")


if __name__ == "__main__":
    main()
