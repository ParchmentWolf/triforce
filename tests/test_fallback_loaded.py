"""The mesh fallback's programs already in memory are handed to the precompile too (gpu/vk/vk_shader.cpp
program_cache_load_some; vk_draw.cpp precompile_run; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-62, after Source A's.) On the task and mesh fallback the precompile builds
the fallback programs' compute pipelines on workers before the title, for the programs program_cache_load_some hands it
with `fallbacks` set. That call handed over only the records still on the disk; in a start that prepares,
state_list_prepare has taken the state lists' records before it (with fallbacks off), so most fallback programs play draws
got no pipelines before the title, and each one's first draw waited up to 50 ms and was left out until they were built.
The call now also hands over every fallback program already in memory that is ready and not failed.
RX_VK_FALLBACK_LOADED=0: not, as before.

Cuts the end of program_cache_load_some (from its lock to its return) out of vk_shader.cpp and runs it over authored
programs: what was read from the disk is handed over as before, with what was in memory under the same key, each once;
a fallback program in memory under another key, ready and not failed, is handed over too, one that is not ready, failed
or no fallback program is not; the count returned and the log line say so; without `fallbacks`, or with the switch at 0,
only what came from the disk.

Reads the source: the walk is after the loop over what was read, under the same shader_mu, skips that loop's keys, tests
fallback, failed and ready (acquire), and is behind the switch; precompile_run still asks with fallbacks true and keeps
the fallback programs for its workers, which take compute_state first; the edit lies inside vk_shader.cpp's part marked
as outside the translation stamp (tests/test_program_carry.py holds the stamp itself); the switches table has the row.

    python -I -B tests/test_fallback_loaded.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)

struct Program {
    uint64_t key = 0;
    int id = 0;
    bool fallback = false, failed = false;
    std::atomic<bool> ready{false};
};
struct DiskRecord { int kind; };
std::mutex shader_mu;
std::unordered_map<uint64_t, std::vector<std::unique_ptr<Program>>> programs;
std::string said;
int lines;
void logf(const char* f, ...) {
    char b[512];
    va_list ap;
    va_start(ap, f);
    vsnprintf(b, sizeof b, f, ap);
    va_end(ap);
    said = b, lines++;
}
static std::unique_ptr<Program> make(uint64_t key, int id, bool fallback, bool ready = true, bool failed = false) {
    auto p = std::make_unique<Program>();
    p->key = key, p->id = id, p->fallback = fallback, p->failed = failed, p->ready = ready;
    return p;
}
// program_cache_load_some's end, as it is: `work` and `made` are what its workers read from the disk
size_t tail(std::vector<std::pair<uint64_t, std::vector<DiskRecord>>>& work, std::vector<std::vector<std::unique_ptr<Program>>>& made,
            const std::function<void(Program&)>& fn, bool fallbacks) {
/* TAIL */
}

int main(int argc, char** argv) {
    const bool off = argc > 1 && argv[1][0] == '0';
    // in memory before the call (what state_list_prepare and the draws read in)
    programs[0xA].push_back(make(0xA, 1, true));              // (and a record of the same key still on the disk: below)
    programs[0xB].push_back(make(0xB, 2, true));              // a fallback program, ready
    programs[0xC].push_back(make(0xC, 3, true, false));       // one still being translated
    programs[0xD].push_back(make(0xD, 4, true, true, true));  // one that failed
    programs[0xE].push_back(make(0xE, 5, false));             // a compute or native program
    programs[0xF].push_back(make(0xF, 6, true));              // a key with two variants, one of them a fallback's
    programs[0xF].push_back(make(0xF, 7, false));
    const auto run = [&](bool fallbacks, std::vector<int>* got) {
        std::vector<std::pair<uint64_t, std::vector<DiskRecord>>> work;
        work.push_back({0xA, {DiskRecord{4}}});
        work.push_back({0x9, {DiskRecord{4}}});
        std::vector<std::vector<std::unique_ptr<Program>>> made(2);
        made[0].push_back(make(0xA, 10 + (int)got->size(), true));
        made[1].push_back(make(0x9, 20 + (int)got->size(), true));
        got->clear();
        return tail(work, made, [&](Program& p) { got->push_back(p.id); }, fallbacks);
    };
    const auto count = [](const std::vector<int>& v, int id) {
        int n = 0;
        for (const int x : v) n += x == id;
        return n;
    };
    std::vector<int> got;
    // without `fallbacks` (the state list's call): only what was read, with what its keys had in memory
    size_t n = run(false, &got);
    CHECK(n == 3 && got.size() == 3 && count(got, 1) == 1 && count(got, 10) == 1 && count(got, 20) == 1 && lines == 0);
    // with it (the precompile's)
    n = run(true, &got);
    if (off) {   // (RX_VK_FALLBACK_LOADED=0: as before)
        CHECK(n == 5 && got.size() == 5 && count(got, 2) == 0 && count(got, 6) == 0 && lines == 0);
        std::printf("ok off\n");
        return 0;
    }
    // (0xA has three variants now: the one in memory and the two read; 0x9 two)
    CHECK(n == 7 && got.size() == 7);
    CHECK(count(got, 1) == 1 && count(got, 10) == 1 && count(got, 13) == 1);   // (a key that was read: each of its variants once, not again)
    CHECK(count(got, 2) == 1 && count(got, 6) == 1);                           // (the fallback programs in memory under other keys)
    CHECK(count(got, 3) == 0 && count(got, 4) == 0 && count(got, 5) == 0 && count(got, 7) == 0);   // (not ready, failed, no fallback)
    CHECK(lines == 1 && said == "vk: 2 mesh fallback programs read in earlier in this start are made ready with the rest");
    // one that became ready since is handed over at a later call
    programs[0xC][0]->ready = true;
    n = run(true, &got);
    CHECK(count(got, 3) == 1 && count(got, 2) == 1 && lines == 2 && said.rfind("vk: 3 mesh fallback programs", 0) == 0);
    std::printf("ok on\n");
    return 0;
}
"""


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def ordered(text, parts, why):
    last = 0
    for p in parts:
        k = text.find(p, last)
        need(k >= 0, why + " (missing, or out of order: " + p + ")")
        last = k + len(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    load = block(shader, "size_t program_cache_load_some(")
    ordered(load, ["std::lock_guard lk(shader_mu);", "for (size_t i = 0; i < work.size(); i++) {", "for (auto& p : variants) n++, fn(*p);",
                   "if (fallbacks) {", 'static const bool loaded = !(getenv("RX_VK_FALLBACK_LOADED") && atoi(getenv("RX_VK_FALLBACK_LOADED")) == 0);',
                   "if (loaded) {", "for (const auto& w : work) taken.insert(w.first);", "for (auto& kv : programs) {",
                   "if (taken.count(kv.first)) continue;",
                   "if (p->fallback && !p->failed && p->ready.load(std::memory_order_acquire)) found++, n++, fn(*p);",
                   'logf("vk: %zu mesh fallback programs read in earlier in this start are made ready with the rest", found);', "return n;"],
            "program_cache_load_some does not hand over the fallback programs already in memory after what it read, under the same lock")
    need(load.count("std::lock_guard lk(shader_mu);") == 1 and load.count("return n;") == 1, "the walk is not under the loop's own lock")
    need("Only a GPU without mesh shaders has such programs" not in load, "the comment that only a GPU without mesh shaders has such programs is back")
    # the edit is inside the part of vk_shader.cpp marked as outside the translation stamp
    out_mark, in_mark = "// ---- (Triforce) Outside the translation stamp", "// ---- (Triforce) Inside the translation stamp again"
    at = shader.index("size_t program_cache_load_some(")
    need(shader.rfind(in_mark, 0, at) < shader.rfind(out_mark, 0, at) < at < at + len(load) < shader.index(in_mark, at),
         "program_cache_load_some is no longer inside a part marked as outside the translation stamp")
    need(shader.count("RX_VK_FALLBACK_LOADED") == load.count("RX_VK_FALLBACK_LOADED"), "the switch is read outside program_cache_load_some")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    pre = block(draw, "void precompile_run(void (*progress)(size_t done, size_t total)) {")
    ordered(pre, ["const size_t programs_n = program_cache_load_some(wanted, [&](Program& p) {", "ensure_layout(p);",
                  "else if (p.fallback) fallbacks.push_back(&p);", "}, all_computes, true);",
                  "Program& p = *fallbacks[i - computes.size()];", "if (p.compute_state.compare_exchange_strong(none, 1)) {",
                  "fallback_compute_pipelines(p);", "p.compute_state.store(2, std::memory_order_release);"],
            "precompile_run does not ask with fallbacks true, keep the fallback programs, or take compute_state before it builds")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_FALLBACK_LOADED=0`" in docs, "docs/development.md: the switches table has no RX_VK_FALLBACK_LOADED row")
    tail = load[load.index("    std::lock_guard lk(shader_mu);"):load.rindex("}")]
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="fallback-loaded-") as tmp:
        cpp, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        cpp.write_text(FIXTURE.replace("/* TAIL */", tail), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        for arg, more, want in (("on", {}, "ok on"), ("0", {"RX_VK_FALLBACK_LOADED": "0"}, "ok off")):
            r = subprocess.run([str(exe), arg], capture_output=True, text=True, timeout=60, env={**env, **more})
            need(r.returncode == 0 and r.stdout.strip() == want, "program_cache_load_some's end (%s): %s" % (arg, r.stdout.strip() or r.returncode))
            print(r.stdout.strip())
    print("PASS: the mesh fallback's programs already in memory are handed to the precompile; RX_VK_FALLBACK_LOADED=0 as before")


if __name__ == "__main__":
    main()
