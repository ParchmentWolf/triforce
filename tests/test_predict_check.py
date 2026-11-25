"""Whether the driver still has the predicted pipelines, at a start whose record says they were all built
(gpu/vk/predict_check.h; vk_draw.cpp predict_check_cold, predict_background, predicted_play_build; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-68, after Source B's and Source A's.) The predicted pipelines are built once
for the driver's own cache and a record says which are done; nothing looked at whether the driver kept them (a size cap,
a cleared folder, a driver that keeps a third). The check samples up to 12 of them at a start whose record says all,
times a build against a second one, and on a cold majority removes the record so that they are built again; cold again
after that, it stops for that driver.

The header is compiled and run as it is:
- RX_VK_PREDICT_CHECK: 1 unset, 0 off, 2 every start;
- a pipeline is cold by its first build against its own second (4 times and 3 ms more), never by a fixed time, and one
  the driver refused does not count;
- a sample is cold when more than half of it is, says nothing under half a sample, and is decided as soon as what is
  still to come cannot change it;
- the places sampled are spread over the whole plan, distinct, the same for one seed and other ones for another;
- find(): the records of the wanted notes in an authored notes file, the first of a key met twice, none for another
  build's head, and the walk ends at the last wanted key;
- the record of the strikes: written whole, read back, a broken one or another stamp's is no record;
- starts in a row on a driver that loses them every time: the record removed once (Again), then Stop, then not checked
  at all (but with 2); on one that lost them once: Again, then warm forgets the strike, and a later loss is Again anew;
  another stamp begins anew;
- the counter: over 20 ms, a line at most every 10 s, the plan's programs sorted without repeats.
Then the source: predict_background asks the check only where the record says all and builds everything again when it
says cold; the check builds for the driver's cache alone, twice, only at light frames, not in a start whose predict_run
built them, and removes the record under its lock; build_graphics counts a play build of a predicted program; the
switches table has the row.

    python -I -B tests/test_predict_check.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <cstdio>
#include <set>
#include "predict_check.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace predict_check;
static Probe timed(double first, double again, bool made = true) {
    Probe p;
    p.made = made, p.first_ms = first, p.again_ms = again;
    return p;
}
static std::vector<Probe> sample(int cold_n, int warm_n, int refused = 0) {
    std::vector<Probe> v;
    for (int i = 0; i < cold_n; i++) v.push_back(timed(80, 0.6));
    for (int i = 0; i < warm_n; i++) v.push_back(timed(1.1, 0.6));
    for (int i = 0; i < refused; i++) v.push_back(timed(500, 0, false));
    return v;
}
struct Plan { uint64_t prog, variant, vertex_note, output_note; };
// A start as predict_background makes it: whether it checks, the verdict of the driver now, what it does, the record
static Do start(const std::string& rec, uint64_t stamp, Verdict v, int mode = 1, bool* checked = nullptr) {
    const State had = state_read(rec);
    if (checked) *checked = runs(mode, had, stamp);
    if (!runs(mode, had, stamp)) return Do::Nothing;
    int next = -1;
    const Do d = decide(v, had, stamp, &next);
    if (v == Verdict::Warm && had.found) remove(rec.c_str());
    if (d != Do::Nothing && !state_write(rec, stamp, next)) return Do::Nothing;
    return d;
}

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    const std::string dir = argv[1];
    // the switch
    CHECK(mode(nullptr) == 1 && mode("") == 1 && mode("1") == 1 && mode("0") == 0 && mode("2") == 2 && mode("7") == 2 && mode("-3") == 0);
    // one pipeline: cold by its own second build
    CHECK(cold(timed(80, 0.6)) && cold(timed(5.5, 0.6)) && !cold(timed(5.3, 0.6)));       // (4 x 0.6 + 3 = 5.4)
    CHECK(!cold(timed(1.1, 0.6)) && !cold(timed(2.9, 0.0)) && cold(timed(3.1, 0.0)));
    CHECK(!cold(timed(40, 12)) && cold(timed(52, 12)));                                    // (a slow driver's warm time: 51)
    CHECK(!cold(timed(500, 0, false)));                                                    // (refused: says nothing)
    // a sample
    CHECK(verdict(tally(sample(7, 5))) == Verdict::Cold && verdict(tally(sample(6, 6))) == Verdict::Warm);
    CHECK(verdict(tally(sample(0, 12))) == Verdict::Warm && verdict(tally(sample(12, 0))) == Verdict::Cold);
    CHECK(verdict(tally(sample(5, 0))) == Verdict::Unknown && verdict(tally(sample(3, 3))) == Verdict::Warm);
    CHECK(verdict(tally(sample(4, 2))) == Verdict::Cold && verdict(tally(sample(0, 5, 7))) == Verdict::Unknown);
    CHECK(verdict(tally(sample(0, 0))) == Verdict::Unknown);
    {
        const Tally t = tally(sample(7, 5, 3));
        CHECK(t.got == 12 && t.cold == 7 && t.first_median == 80 && t.again_median == 0.6);
    }
    // decided: full, or the rest cannot change it; and what it says then is what the full sample would
    CHECK(!decided(tally(sample(6, 5))) && decided(tally(sample(7, 0))) && decided(tally(sample(0, 6))) && decided(tally(sample(6, 6))));
    CHECK(!decided(tally(sample(0, 0))) && !decided(tally(sample(6, 0))) && !decided(tally(sample(3, 5))) && !decided(tally(sample(0, 5, 20))));
    for (int c = 0; c <= kSample; c++)
        for (int w = 0; c + w <= kSample; w++) {
            if (!decided(tally(sample(c, w)))) continue;
            const Verdict now = verdict(tally(sample(c, w)));
            CHECK(now != Verdict::Unknown);
            for (int more = 0; c + w + more <= kSample; more++)   // (whatever comes after, cold or warm)
                CHECK(verdict(tally(sample(c + more, w))) == now && verdict(tally(sample(c, w + more))) == now);
        }
    // the places
    {
        const std::vector<size_t> a = spots(28000, kLook, 12345), b = spots(28000, kLook, 12345), c = spots(28000, kLook, 12346);
        CHECK(a == b && a != c && a.size() == (size_t)kLook);
        std::set<size_t> distinct(a.begin(), a.end());
        CHECK(distinct.size() == a.size() && a.front() < 28000 / kLook && a.back() >= 28000 - 2 * (28000 / kLook) && a.back() < 28000);
        CHECK(spots(0, kLook, 5).empty() && spots(7, kLook, 5).size() == 7 && spots(1, kLook, 99) == std::vector<size_t>{0});
    }
    // find(): an authored notes file, records of 64 bytes whose first 8 are the key
    {
        const std::string notes = dir + "/notes.bin";
        const uint64_t stamp = 0x1122334455667788ull, rec_bytes = 64;
        const uint64_t keys[] = {100, 200, 300, 200, 400, 500, 600};   // (200 twice: its first record, 1)
        FILE* f = fopen(notes.c_str(), "wb");
        CHECK(f != nullptr);
        const uint64_t head[2] = {stamp, rec_bytes};
        fwrite(head, 8, 2, f);
        for (const uint64_t k : keys) {
            unsigned char rec[64] = {};
            memcpy(rec, &k, 8);
            memset(rec + 8, 0xEE, 56);
            fwrite(rec, 1, 64, f);
        }
        fclose(f);
        f = fopen(notes.c_str(), "rb");
        auto at = find(f, stamp, rec_bytes, {300, 200, 999, 500});
        CHECK(at.size() == 3 && at[300] == 2 && at[200] == 1 && at[500] == 5 && !at.count(999));
        fclose(f);
        f = fopen(notes.c_str(), "rb");
        at = find(f, stamp, rec_bytes, {100, 200});
        CHECK(at.size() == 2 && at[100] == 0 && at[200] == 1 && ftell(f) == 16 + 2 * 64);   // (it stopped at the last wanted key)
        fclose(f);
        f = fopen(notes.c_str(), "rb");
        CHECK(find(f, stamp + 1, rec_bytes, {100}).empty());                               // (another build's file)
        fclose(f);
        f = fopen(notes.c_str(), "rb");
        CHECK(find(f, stamp, 128, {100}).empty() && find(nullptr, stamp, rec_bytes, {100}).empty());
        fclose(f);
        f = fopen(notes.c_str(), "rb");
        CHECK(find(f, stamp, rec_bytes, {}).empty() && find(f, stamp, 4, {100}).empty());
        fclose(f);
    }
    // the record
    const std::string rec = dir + "/notes.predicted.check";
    CHECK(!state_read(rec).found);
    CHECK(state_write(rec, 0xABCDEF0123456789ull, 1));
    {
        const State s = state_read(rec);
        CHECK(s.found && s.stamp == 0xABCDEF0123456789ull && s.strikes == 1);
    }
    {
        FILE* f = fopen(rec.c_str(), "wb");
        fputs("lib-check 0000000000000001 0\n", f);   // (the libraries' record is not this one)
        fclose(f);
        CHECK(!state_read(rec).found);
        f = fopen(rec.c_str(), "wb");
        fputs("predict-check zz", f);
        fclose(f);
        CHECK(!state_read(rec).found);
        remove(rec.c_str());
    }
    // a driver that loses them every time
    const uint64_t A = 0x1111, B = 0x2222;
    bool checked = false;
    CHECK(start(rec, A, Verdict::Cold) == Do::Again && state_read(rec).strikes == 1);
    CHECK(start(rec, A, Verdict::Cold, 1, &checked) == Do::Stop && checked && state_read(rec).strikes == 2);
    CHECK(stopped(state_read(rec), A) && !stopped(state_read(rec), B));
    CHECK(start(rec, A, Verdict::Cold, 1, &checked) == Do::Nothing && !checked);         // (not checked again)
    CHECK(start(rec, A, Verdict::Cold, 2, &checked) == Do::Stop && checked);             // (but with 2, and still no rebuild)
    CHECK(start(rec, A, Verdict::Cold, 0, &checked) == Do::Nothing && !checked);
    // another stamp (a new driver, new shaders) begins anew
    CHECK(start(rec, B, Verdict::Cold, 1, &checked) == Do::Again && checked && state_read(rec).stamp == B && state_read(rec).strikes == 1);
    // a driver that lost them once: warm forgets the strike, and a later loss is built again
    CHECK(start(rec, B, Verdict::Warm) == Do::Nothing && !state_read(rec).found);
    CHECK(start(rec, B, Verdict::Cold) == Do::Again && state_read(rec).strikes == 1);
    CHECK(start(rec, B, Verdict::Unknown) == Do::Nothing && state_read(rec).strikes == 1);   // (nothing said: nothing changed)
    CHECK(start(rec, B, Verdict::Warm) == Do::Nothing && !state_read(rec).found);
    // the counter
    CHECK(!slow(20000) && slow(20001) && !slow(0) && slow(3000000));
    CHECK(say(5, 0) && !say(9999, 1) && say(10001, 1) && !say(15000, 10000) && say(20000, 10000));
    {
        const std::vector<Plan> plan = {{30, 1, 0, 0}, {10, 1, 0, 0}, {30, 2, 0, 0}, {20, 1, 0, 0}, {10, 3, 0, 0}};
        const std::vector<uint64_t> p = programs(plan);
        CHECK(p == (std::vector<uint64_t>{10, 20, 30}) && has(p, 20) && has(p, 10) && has(p, 30) && !has(p, 25) && !has({}, 10));
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


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need('#include "predict_check.h"' in draw, "vk_draw.cpp does not include predict_check.h")
    need('static const int mode = predict_check::mode(getenv("RX_VK_PREDICT_CHECK"));' in block(draw, "int predict_check_mode() {"),
         "the switch is not RX_VK_PREDICT_CHECK, read once")
    bg = block(draw, "void predict_background() {")
    ordered(bg, ["std::unordered_set<uint64_t> had = predicted_read(pstamp);", "if (had.count(kPredictedAll)) {",
                 "if (!predict_check_cold(pstamp)) return;", "had.clear();", "predict_plan_keys_publish(plan);",
                 "groups = predict_stream::group(plan, at, had);", "driver_cache_only = true;", "predicted_done(pstamp, keys[i]);"],
            "predict_background does not check where the record says all, or does not build everything again when cold")
    need(bg.count("predict_check_cold(") == 1 and bg.index("Sleep(100);   // (past the start's own loading)") < bg.index("predict_check_cold("),
         "the check does not run on the builder's thread after its delay")
    check = block(draw, "bool predict_check_cold(uint64_t pstamp) {")
    ordered(check, ["if (!mode) return false;", "if (!plan_read(&plan) || plan.empty()) return false;", "predict_plan_keys_publish(plan);",
                    'predicted_path() + ".check"', "if (!predict_check::runs(mode, had, pstamp)) return false;",
                    "std::lock_guard lk(predicted_mu);", "if (predicted_file) return false;",
                    "predict_check::spots(plan.size(), (size_t)predict_check::kLook,",
                    "predict_check::find(f, notes_stamp(), sizeof(PipeNote), want);",   # ((Triforce, 11-24) the notes' own stamp)
                    "if (predict_check::decided(predict_check::tally(probes))) break;",
                    "while (!prepare_stopped() && bg_game_in_play()) Sleep(50);", "if (prepare_stopped()) return false;",
                    "predicted_into(*n, *v, *o, e.prog, e.variant);", "program_cache_borrow(e.prog,", "ensure_layout(p);",
                    "driver_cache_only = true;", "const VkPrimitiveTopology topo = pipeline_topology(p, (VkPrimitiveTopology)n->topo);",
                    "const VkPipeline first = build_graphics(p, n->s, note_targets(*n), topo);",
                    "const VkPipeline again = first ? build_graphics(p, n->s, note_targets(*n), topo) : VK_NULL_HANDLE;",
                    "driver_cache_only = false;", "probe.made = first && again,",
                    "predict_check::decide(verdict, had, pstamp, &next);", "if (had.found) remove(state_path.c_str());",
                    "predict_check::state_write(state_path, pstamp, next);", "if (what == predict_check::Do::Stop) {", "return false;",
                    "std::lock_guard lk(predicted_mu);", "if (predicted_file) fclose(predicted_file), predicted_file = nullptr;",
                    "remove(predicted_path().c_str());", "return true;"],
            "predict_check_cold does not sample for the driver's cache alone at light frames, or does not remove the record only when cold")
    need("FAIL_ON_PIPELINE_COMPILE_REQUIRED" not in check and check.count("vkDestroyPipeline(") == 2,
         "the check asks with the compile-required flag (a driver answers that only from a cache it is handed), or keeps its pipelines")
    need(check.count("return true;") == 1, "the check says cold in more than one place")
    build = block(draw, "VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, int part, bool* cold) {")
    ordered(build, ["st_pipelines++;", "const int64_t build_us =", "st_pipeline_us += build_us;",
                    "if (!driver_cache_only && pl && predict_check_mode()) predicted_play_build(p.key, build_us);", "return pl;"],
            "build_graphics does not count a play build of a predicted program")
    count = block(draw, "void predicted_play_build(uint64_t prog, int64_t us) {")
    ordered(count, ["if (!predict_check::slow(us)) return;", "predict_plan_keys.load(std::memory_order_acquire);",
                    "if (!keys || !predict_check::has(*keys, prog)) return;", "st_predicted_slow.fetch_add(1,",
                    "if (predict_check::say(now, said) && said_ms.compare_exchange_strong(said, now))", 'logf("vk: predicted pipelines: %lld builds in play'],
            "predicted_play_build does not count only slow builds of the plan's programs, or logs at every one")
    publish = block(draw, "void predict_plan_keys_publish(const std::vector<PredictPlan>& plan) {")
    need("if (!predict_check_mode() || predict_plan_keys.load(std::memory_order_acquire)) return;" in publish and
         "new std::vector<uint64_t>(predict_check::programs(plan))" in publish and "compare_exchange_strong(none, keys)" in publish,
         "the plan's programs are not published once for the counter")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_PREDICT_CHECK=0`, `=2`" in docs and "`gpu/vk/predict_check.h`" in docs,
         "docs/development.md: the switches table has no RX_VK_PREDICT_CHECK row")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="predict-check-") as tmp:
        cpp, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        cpp.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        work = Path(tmp) / "work"
        work.mkdir()
        r = subprocess.run([str(exe), str(work).replace("\\", "/")], capture_output=True, text=True, timeout=60)
        if r.returncode or r.stdout.strip() != "ok":
            raise SystemExit("FAIL: the predicted pipelines' check: " + (r.stdout.strip() or "exit %d" % r.returncode))
    check_source()
    print("PASS: the predicted pipelines' check samples the driver's cache, builds again once when cold, then stops; "
          "RX_VK_PREDICT_CHECK=0 as before")


if __name__ == "__main__":
    main()
