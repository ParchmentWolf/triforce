"""Whether the caches still have what the light precompile's record lists (gpu/vk/built_check.h; vk_draw.cpp
built_check_cold, built_check_made, built_play_publish, built_play_build, precompile_run; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-21, after Source A's and Source B's.) A light precompile (little RAM) builds
the noted pipelines for the caches, lets them go and records their keys in <notes>.built; later starts left everything the
record lists to its first draw, trusting it on its stamp alone. When the caches lost them, each of those first draws
compiled in play. Now a sample of the recorded notes is asked of Triforce's own caches first (as a draw asks, without
compiling, where the device can) and some listed compute programs as a dispatch asks; at half or more cold, everything is
built again before the title. Cold again right after that: left to the draws, with a hint. RX_VK_BUILT_CHECK=0: as before.

The header is compiled and run as it is: the switch; a pipeline cold by the caches' answer, or without the flag by its
first build against its own second; the sample (24 answers: 12 cold is cold, 11 warm; 15 answers say nothing); the places;
the record of strikes; starts in a row (cold: built again; cold again: left to the draws; warm forgets; another stamp anew;
mode 2 always builds again); the counter's rules.

Then built_check_cold, built_check_made, built_play_publish and built_play_build are cut out of vk_draw.cpp and run over a
stand-in driver whose caches hold pipelines by key:
  - warm caches: not cold, 24 notes and 6 compute programs asked, each the note's own variant, nothing compiled, every
    pipeline asked for let go, the caches as they were;
  - lost caches: cold, still nothing compiled (asked without compiling: the same pipelines exist afterwards); the record
    of the rebuild written; cold again: left to the draws with the hint, not cold; warm: the strike forgotten;
  - 12 of 24 cold is cold, 11 is not; 15 answers (9 refused) say nothing, 16 do;
  - without the flag: each recorded note built twice and timed, the cold ones compiled into the caches (exactly the
    recorded pipelines, nothing else), compute programs not asked;
  - the switch at 0, or an empty record: nothing asked; at 2: cold with warm caches;
  - the counter: nothing before the record is published (nor with the switch at 0), then only the record's keys and its
    compute programs, one line at most every 10 s.
And reads the source: precompile_run asks before the erase and forgets the record when cold, records the strikes after the
record is written again, publishes the record for the counter; build_graphics and the dispatch count; the switch is read
once; the switches table has the row.

    python -I -B tests/test_built_check.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

RULES = r"""
#include <cstdio>
#include <set>
#include "built_check.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace built_check;
static Probe asked(bool cold_answer) { Probe p; p.asked = true; p.answered_cold = cold_answer; p.made = !cold_answer; return p; }
static Probe timed(double first, double again) { Probe p; p.made = true; p.first_ms = first; p.again_ms = again; return p; }
static Probe refused() { Probe p; p.asked = true; return p; }
static std::vector<Probe> sample(int cold_n, int warm_n, int refused_n = 0) {
    std::vector<Probe> v;
    for (int i = 0; i < cold_n; i++) v.push_back(asked(true));
    for (int i = 0; i < warm_n; i++) v.push_back(asked(false));
    for (int i = 0; i < refused_n; i++) v.push_back(refused());
    return v;
}
static Do start(const std::string& rec, uint64_t stamp, Verdict v, bool always = false) {
    const State had = state_read(rec);
    int next = -1;
    const Do d = decide(v, had, stamp, always, &next);
    if (v == Verdict::Warm && had.found) remove(rec.c_str());
    if (d == Do::Again && !state_write(rec, stamp, next)) return Do::Nothing;   // (as built_check_made, once built again)
    return d;
}
int main(int argc, char** argv) {
    if (argc < 2) return 2;
    const std::string dir = argv[1];
    CHECK(mode(nullptr) == 1 && mode("") == 1 && mode("1") == 1 && mode("0") == 0 && mode("2") == 2 && mode("9") == 2 && mode("-1") == 0);
    // one pipeline
    CHECK(cold(asked(true)) && !cold(asked(false)) && !counts(refused()) && !cold(refused()));
    CHECK(cold(timed(8.5, 1.0)) && !cold(timed(6.9, 1.0)) && !cold(timed(0.4, 0.3)) && cold(timed(3.2, 0.0)));
    {
        Probe p = timed(80, 0.5);
        p.asked = true;   // (asked, the answer alone counts: a slow hit is a hit)
        CHECK(!cold(p));
    }
    // the sample: 24 answers, 12 cold is cold, 11 warm; 15 answers say nothing, 16 do
    CHECK(verdict(tally(sample(12, 12))) == Verdict::Cold && verdict(tally(sample(11, 13))) == Verdict::Warm);
    CHECK(verdict(tally(sample(15, 0, 9))) == Verdict::Unknown && verdict(tally(sample(16, 0, 8))) == Verdict::Cold);
    CHECK(verdict(tally(sample(0, 15))) == Verdict::Unknown && verdict(tally(sample(0, 16))) == Verdict::Warm);
    CHECK(verdict(tally(sample(8, 8))) == Verdict::Cold && verdict(tally(sample(7, 9))) == Verdict::Warm);
    CHECK(verdict(tally({})) == Verdict::Unknown);
    {
        const Tally t = tally(sample(5, 7, 3));
        CHECK(t.got == 12 && t.cold == 5 && t.answered == 5);
    }
    // the places: spread, distinct, the same for one seed
    {
        const std::vector<size_t> a = spots(20000, kLook, 77), b = spots(20000, kLook, 77), c = spots(20000, kLook, 78);
        CHECK(a == b && a != c && a.size() == (size_t)kLook && std::set<size_t>(a.begin(), a.end()).size() == a.size());
        CHECK(spots(0, kLook, 1).empty() && spots(30, kLook, 5).size() == 30 && spots(1, kLook, 9) == std::vector<size_t>{0});
    }
    // the record
    const std::string rec = dir + "/notes.built.check";
    CHECK(!state_read(rec).found);
    CHECK(state_write(rec, 0x0123456789ABCDEFull, 2) && state_read(rec).found && state_read(rec).stamp == 0x0123456789ABCDEFull &&
          state_read(rec).strikes == 2);
    {
        FILE* f = fopen(rec.c_str(), "wb");
        fputs("predict-check 0000000000000001 0\n", f);   // (another check's record is not this one)
        fclose(f);
        CHECK(!state_read(rec).found);
        remove(rec.c_str());
    }
    // starts in a row
    const uint64_t A = 0xA, B = 0xB;
    CHECK(start(rec, A, Verdict::Cold) == Do::Again && state_read(rec).strikes == 0);
    CHECK(start(rec, A, Verdict::Cold) == Do::Stop && state_read(rec).strikes == 0);      // (cold again right after: the draws)
    CHECK(start(rec, A, Verdict::Unknown) == Do::Nothing && state_read(rec).found);
    CHECK(start(rec, B, Verdict::Cold) == Do::Again && state_read(rec).stamp == B);      // (another stamp begins anew)
    CHECK(start(rec, B, Verdict::Warm) == Do::Nothing && !state_read(rec).found);         // (warm forgets)
    CHECK(start(rec, B, Verdict::Cold) == Do::Again);
    CHECK(start(rec, B, Verdict::Warm, true) == Do::Again && start(rec, B, Verdict::Unknown, true) == Do::Again);   // (mode 2)
    // the counter
    CHECK(!slow(39999) && slow(40000) && say(1, 0) && !say(10000, 1) && say(10001, 1));
    {
        const std::vector<uint64_t> s = sorted({5, 3, 5, 9, 1});
        CHECK(s == (std::vector<uint64_t>{1, 3, 5, 9}) && has(s, 9) && !has(s, 4) && !has({}, 1));
    }
    std::printf("ok\n");
    return 0;
}
"""

FIXTURE = r"""
#include "built_check.h"
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s (%s)\n", __LINE__, #x, last_log.c_str()); return 1; } } while (0)

// ---- a stand-in driver: the caches hold graphics pipelines by note key and compute pipelines by program key
using VkResult = int;
constexpr VkResult VK_SUCCESS = 0, VK_PIPELINE_COMPILE_REQUIRED = 1000297000;
constexpr uint32_t VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT = 0x100;
using VkPipeline = uint64_t;
#define VK_NULL_HANDLE 0
using VkPrimitiveTopology = int;
struct NvnState { uint64_t note; };
struct PipeNote { uint64_t key, prog, variant; uint32_t topo; NvnState s; };
struct Targets { int n; };
struct Stage { int m; };
struct Program { uint64_t key, variant; bool failed = false, compute = false; std::vector<Stage> stages{Stage{}}; };
struct VkComputePipelineCreateInfo { uint32_t flags; uint64_t key; };
struct { struct { bool pipelineCreationCacheControl = true; } vk13; int device = 0; } dev;
std::set<uint64_t> graphics_cache, compute_cache, refused;
std::map<uint64_t, std::vector<Program>> programs;
std::map<uint64_t, uint64_t> note_variant;
int compiles, asks, compute_asks, alive, wrong_variant, borrows, layouts, test_mode = 1, logs;
std::string dir, last_log;
VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets&, VkPrimitiveTopology, int part, bool* cold) {
    if (part != -1) return VK_NULL_HANDLE;
    wrong_variant += note_variant[s.note] != p.variant;
    if (refused.count(s.note)) return VK_NULL_HANDLE;
    if (cold) {   // (asked without compiling: the caches' answer)
        asks++;
        if (!graphics_cache.count(s.note)) return *cold = true, VK_NULL_HANDLE;
        return alive++, s.note;
    }
    if (!graphics_cache.count(s.note)) {   // (compiled into the caches: a compile's time)
        std::this_thread::sleep_for(std::chrono::milliseconds(9));
        graphics_cache.insert(s.note), compiles++;
    }
    return alive++, s.note;
}
Targets note_targets(const PipeNote&) { return Targets{}; }
void ensure_layout(Program&) { layouts++; }
void program_cache_borrow(uint64_t key, const std::function<void(Program&)>& fn) {
    borrows++;
    auto it = programs.find(key);
    if (it == programs.end()) return;
    for (Program p : it->second) fn(p);   // (a copy, let go after)
}
void vkDestroyPipeline(int, VkPipeline, const void*) { alive--; }
VkComputePipelineCreateInfo compute_create_info(const Program& p) { return {0, p.key}; }
struct PcacheUse { int cache = 1; };
PcacheUse pcache_use() { return {}; }
VkResult cached_compute(int, const VkComputePipelineCreateInfo* ci, VkPipeline* pl) {
    compute_asks++;
    if (!(ci->flags & VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT)) return compiles++, *pl = ci->key, alive++, VK_SUCCESS;
    if (!compute_cache.count(ci->key)) return VK_PIPELINE_COMPILE_REQUIRED;
    return *pl = ci->key, alive++, VK_SUCCESS;
}
std::string pipe_notes_path() { return dir + "/notes.bin"; }
bool prepare_stopped() { return false; }
void logf(const char* fmt, ...) {
    char line[2048];
    va_list a;
    va_start(a, fmt);
    vsnprintf(line, sizeof line, fmt, a);
    va_end(a);
    last_log = line, logs++;
}
int built_check_mode() { return test_mode; }
int built_check_next = 0;
std::atomic<const std::vector<uint64_t>*> built_play_keys{nullptr};
std::atomic<int64_t> st_built_slow{0}, st_built_slow_us{0}, st_built_missed{0};
/* CUT */

uint64_t key_of(const PipeNote& n) { return n.key; }
std::vector<std::unique_ptr<PipeNote>> notes;
std::unordered_set<uint64_t> built;
std::vector<uint64_t> listed;
constexpr uint64_t kComputesKey = 0xC0FFEE, kStamp = 0x5157;
static bool run(bool computes_built = true) { return built_check_cold(notes, built, key_of, computes_built, listed, kStamp); }
static void fill_caches() {
    graphics_cache.clear(), compute_cache.clear();
    for (const auto& n : notes) graphics_cache.insert(n->key);
    compute_cache.insert(listed.begin(), listed.end());
}
static bool has(const std::string& s) { return last_log.find(s) != std::string::npos; }

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    dir = argv[1];
    const std::string state = dir + "/notes.bin.built.check";
    for (uint64_t k = 1; k <= 40; k++) {
        const uint64_t variant = k % 5 == 0 ? 2 : 1;   // (some notes are of the program's second variant)
        notes.push_back(std::make_unique<PipeNote>(PipeNote{k, 1000 + k, variant, 3, NvnState{k}}));
        note_variant[k] = variant;
        programs[1000 + k] = {Program{1000 + k, 1}, Program{1000 + k, 2}};
        built.insert(k);
    }
    built.insert(kComputesKey);
    for (uint64_t k = 500; k < 520; k++) {
        listed.push_back(k);
        Program c{k, 1};
        c.compute = true;
        programs[k] = {c};
    }
    // warm caches: nothing compiled, every pipeline let go, the caches as they were
    fill_caches();
    const std::set<uint64_t> had_graphics = graphics_cache;
    CHECK(!run() && asks == 24 && compute_asks == 6 && compiles == 0 && alive == 0 && wrong_variant == 0 && has("have what it lists"));
    CHECK(graphics_cache == had_graphics && !fopen(state.c_str(), "rb"));
    // the caches lost them: cold, and still nothing compiled by the check
    graphics_cache.clear(), compute_cache.clear();
    asks = compute_asks = 0;
    CHECK(run() && asks == 24 && compute_asks == 6 && compiles == 0 && alive == 0 && graphics_cache.empty() && has("built again now"));
    built_check_made(kStamp);   // (precompile_run's, once everything was built and recorded again)
    CHECK(built_check::state_read(state).found && built_check::state_read(state).stamp == kStamp);
    // cold again right after: left to the draws, with the hint
    CHECK(!run() && has("Shader Cache Size") && built_check::state_read(state).found);
    // warm again: the strike forgotten
    fill_caches();
    CHECK(!run() && !built_check::state_read(state).found);
    // the threshold: the first 24 recorded notes are asked (40 notes, under kLook); computes left out here
    graphics_cache.clear();
    for (uint64_t k = 13; k <= 40; k++) graphics_cache.insert(k);   // (1-12 lost: 12 of 24)
    CHECK(run(false) && has("12 of 24"));
    graphics_cache.insert(12);                                       // (11 of 24)
    CHECK(!run(false) && has("11 of 24"));
    // too few answers: 9 refused leave 15, 8 leave 16
    graphics_cache.clear();
    for (uint64_t k = 1; k <= 9; k++) refused.insert(k);
    CHECK(!run(false) && has("too few"));
    refused.erase(9);
    CHECK(run(false));
    refused.clear();
    // without the flag: built twice and timed; the cold ones compiled, exactly the recorded notes asked, nothing else
    dev.vk13.pipelineCreationCacheControl = false;
    compute_asks = 0, compiles = 0;
    CHECK(run() && compiles == 24 && compute_asks == 0 && alive == 0 && has("built twice"));
    for (uint64_t k = 1; k <= 24; k++) CHECK(graphics_cache.count(k));
    CHECK(graphics_cache.size() == 24);
    fill_caches();
    compiles = 0;
    CHECK(!run() && compiles == 0 && alive == 0);
    dev.vk13.pipelineCreationCacheControl = true;
    // the switch at 0, or no record: nothing asked; at 2: cold with warm caches
    asks = compute_asks = borrows = 0;
    test_mode = 0;
    CHECK(!run() && asks == 0 && compute_asks == 0 && borrows == 0);
    test_mode = 1;
    {
        const std::unordered_set<uint64_t> none;
        CHECK(!built_check_cold(notes, none, key_of, true, listed, kStamp) && asks == 0 && borrows == 0);
    }
    test_mode = 2;
    CHECK(run() && asks == 24 && has("RX_VK_BUILT_CHECK=2"));
    remove(state.c_str());
    // the counter: nothing until published, nor with the switch at 0; then the record's keys and its compute programs
    test_mode = 1;
    built_play_build(3, 50000, false);
    CHECK(st_built_slow == 0);
    test_mode = 0;
    built_play_publish(built, kComputesKey, listed);
    CHECK(built_play_keys.load() == nullptr);
    test_mode = 1;
    built_play_publish(built, kComputesKey, listed);
    CHECK(built_play_keys.load() != nullptr && built_check::has(*built_play_keys.load(), 507) && built_check::has(*built_play_keys.load(), 3));
    logs = 0;
    built_play_build(3, 50000, false);
    built_play_build(4, 60000, false);
    built_play_build(999, 90000, false);   // (not in the record)
    built_play_build(507, 0, true);
    built_play_build(888, 0, true);        // (not listed)
    CHECK(st_built_slow == 2 && st_built_slow_us == 110000 && st_built_missed == 1 && logs == 1);   // (one line in 10 s)
    {   // (a record without the compute key lists no compute program)
        std::unordered_set<uint64_t> graphics_only(built);
        graphics_only.erase(kComputesKey);
        const std::vector<uint64_t>* was = built_play_keys.exchange(nullptr);
        built_play_publish(graphics_only, kComputesKey, listed);
        CHECK(built_play_keys.load() && !built_check::has(*built_play_keys.load(), 507) && built_check::has(*built_play_keys.load(), 3));
        delete was;
    }
    std::printf("ok\n");
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


def check_source(draw):
    need('#include "built_check.h"' in draw, "vk_draw.cpp does not include built_check.h")
    need('static const int mode = built_check::mode(getenv("RX_VK_BUILT_CHECK"));' in block(draw, "int built_check_mode() {"),
         "the switch is not RX_VK_BUILT_CHECK, read once")
    pre = block(draw, "void precompile_run(void (*progress)(size_t done, size_t total)) {")
    ordered(pre, ["const std::vector<uint64_t> computes_listed = computes_in_order();", "bool rebuilt = false;", "if (light) {",
                  "built = built_read(built_stamp);", "computes_built = built.count(computes_key) != 0;",
                  "if (!built.empty() && built_check_cold(notes, built, built_key, computes_built, computes_listed, built_stamp))",
                  "built.clear(), computes_built = false, rebuilt = true;", "std::erase_if(notes,",
                  "const std::unordered_set<uint64_t> used = computes_built ?", "pipeline_cache_save(true);",
                  "built_write(built_stamp, built);", "if (rebuilt) built_check_made(built_stamp);",
                  "if (light && !prepare_stopped()) built_play_publish(built, computes_key, computes_listed);"],
            "precompile_run does not ask before the erase, forget the record when cold, record the strikes after the record, "
            "or publish it for the counter")
    need(pre.count("built_check_cold(") == 1, "precompile_run asks more than once")
    check = block(draw, "bool built_check_cold(")
    ordered(check, ["if (!mode || built.empty()) return false;", "const bool ask = dev.vk13.pipelineCreationCacheControl;",
                    "built_check::spots(recorded.size(), (size_t)built_check::kLook, seed)", "program_cache_borrow(n.prog,",
                    "build_graphics(p, n.s, note_targets(n), (VkPrimitiveTopology)n.topo, -1, ask ? &cold : nullptr);",
                    "if (computes_built && ask)", "ci.flags |= VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT;",
                    "cached_compute(pcache_use().cache, &ci, &pl);", 'pipe_notes_path() + ".built.check"',
                    "built_check::decide(v, had, stamp, mode == 2, &built_check_next);", "return true;", "return false;"],
            "built_check_cold does not ask our caches as a draw and a dispatch ask, or does not decide by the record of strikes")
    need("driver_cache_only" not in check, "the check asks the driver's own cache, not ours (AMD's Windows driver keeps none)")
    build = block(draw, "VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, int part, bool* cold) {")
    ordered(build, ["const int64_t build_us =", "if (!driver_cache_only && pl && built_check::slow(build_us) && built_play_keys.load(std::memory_order_relaxed))",
                    "built_play_build(pipeline_key(p, s, at, topo), build_us, false);", "return pl;"],
            "build_graphics does not count a slow play build of a recorded pipeline")
    disp = block(draw, "void dispatch(VkCommandBuffer cmd, NvnState& s,")
    ordered(disp, ["cached_compute(pcache_use().cache, &asked, &cached)",
                   "if (!cached && dev.vk13.pipelineCreationCacheControl && built_play_keys.load(std::memory_order_relaxed))",
                   "built_play_build(p.key, 0, true);", "auto build = [job, info] {"],
            "the dispatch does not count a recorded compute program its ask missed")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_BUILT_CHECK=0`, `=2`" in docs and "`gpu/vk/built_check.h`" in docs,
         "docs/development.md: the switches table has no RX_VK_BUILT_CHECK row")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need("bool built_check_cold(" in draw, "vk_draw.cpp has no built_check_cold")
    cut = "\n".join(block(draw, m) for m in ("bool built_check_cold(", "void built_check_made(uint64_t stamp) {",
                                              "void built_play_publish(", "void built_play_build(uint64_t key, int64_t us, bool compute) {"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="built-check-") as tmp:
        tmp = Path(tmp)
        for name, text in (("rules", RULES), ("cut", FIXTURE.replace("/* CUT */", cut))):
            src, exe = tmp / (name + ".cpp"), tmp / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-I" + str(ROOT / "gpu/vk"),
                            str(src), "-o", str(exe)], check=True)
            work = tmp / ("work-" + name)
            work.mkdir()
            r = subprocess.run([str(exe), str(work).replace("\\", "/")], capture_output=True, text=True, timeout=120, env=env)
            need(r.returncode == 0 and r.stdout.strip() == "ok", "the built check (%s): %s" % (name, r.stdout.strip() or r.returncode))
    check_source(draw)
    print("PASS: the light precompile's record is asked of the caches before it is trusted; lost, everything is built again "
          "before the title, then left to the draws if lost again; RX_VK_BUILT_CHECK=0 as before")


if __name__ == "__main__":
    main()
