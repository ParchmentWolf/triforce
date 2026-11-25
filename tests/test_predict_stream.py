"""The predicted builder keeps its plan as record numbers and reads its notes when it builds (gpu/vk/predict_stream.h,
vk_draw.cpp predict_background, vk_predict.cpp; no game, no GPU).

(Triforce, 11-21, the performance audit's PIPE-83, after Source B's.) predict_background builds the predicted pipelines
the start did not get to, behind the game, resting while it is in play. It held every note of the notes file (~27 KB
each) and a full note of every predicted pipeline until it ended: about 1 GB for much of a session.

This compiles predict_stream.h alone and, on a notes file of its own: each key's record, a record that is not sane
skipped and still counted, a key twice keeping its first record, another build's head giving nothing; the plan as
programs in the order it first names them, the ones built by earlier starts left out, a pipeline whose note is gone
dropped and a program left with none not listed.

And reads the source: predict_background reads every note and rebuilds the plan only under the switch, a worker opens
its own handle on the notes file and reads the two notes by their records, predict_rebuild's note is made by
predicted_into (one result), and the switch is in the switches table.

    python -I -B tests/test_predict_stream.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "predict_stream.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
struct Rec { uint64_t key; uint32_t ok, pad[5]; };          // (a stand-in note: 32 bytes, its key first)
struct Plan { uint64_t prog, variant, vertex_note, output_note; };
int main(int argc, char** argv) {
    if (argc < 2) return 2;
    const uint64_t stamp = 0x1234;
    {   // records 0..5: keys 10, 11 (not sane), 12, 10 again, 13, 14
        FILE* f = std::fopen(argv[1], "wb");
        const uint64_t head[2] = {stamp, sizeof(Rec)};
        std::fwrite(head, 8, 2, f);
        const Rec recs[] = {{10, 1, {}}, {11, 0, {}}, {12, 1, {}}, {10, 1, {}}, {13, 1, {}}, {14, 1, {}}};
        std::fwrite(recs, sizeof(Rec), 6, f);
        std::fwrite("half", 1, 4, f);                       // (a record cut short at the end: not one)
        std::fclose(f);
    }
    Rec rec{};
    FILE* f = std::fopen(argv[1], "rb");
    const auto at = predict_stream::index(f, stamp, sizeof(Rec), &rec, [&] { return rec.ok != 0; });
    std::fclose(f);
    CHECK(at.size() == 4);
    CHECK(at.count(10) && at.at(10) == 0);                  // (the first of the two)
    CHECK(!at.count(11));                                   // (not sane: not used)
    CHECK(at.count(12) && at.at(12) == 2);                  // (and still counted: 12 is record 2)
    CHECK(at.count(13) && at.at(13) == 4 && at.count(14) && at.at(14) == 5);
    f = std::fopen(argv[1], "rb");
    CHECK(predict_stream::index(f, stamp + 1, sizeof(Rec), &rec, [] { return true; }).empty());   // (another build's)
    std::fclose(f);
    f = std::fopen(argv[1], "rb");
    CHECK(predict_stream::index(f, stamp, sizeof(Rec) + 8, &rec, [] { return true; }).empty());   // (another note's size)
    std::fclose(f);
    CHECK(predict_stream::index((FILE*)nullptr, stamp, sizeof(Rec), &rec, [] { return true; }).empty());

    // the plan: programs 7, 5, 9, 7 again, 6 (built by an earlier start), 8 (its only pipeline's note gone)
    const std::vector<Plan> plan = {
        {7, 1, 10, 12}, {5, 0, 12, 13}, {9, 2, 14, 10}, {7, 3, 13, 14}, {7, 1, 11, 12},   // (the last: note 11 is gone)
        {6, 0, 10, 12}, {8, 0, 10, 99}, {5, 4, 99, 10}, {5, 4, 10, 10}};
    const auto g = predict_stream::group(plan, at, {6});
    CHECK(g.size() == 3);
    CHECK(g[0].prog == 7 && g[1].prog == 5 && g[2].prog == 9);                         // (the plan's order)
    CHECK(g[0].entries.size() == 2);
    CHECK(g[0].entries[0].variant == 1 && g[0].entries[0].vertex_rec == 0 && g[0].entries[0].output_rec == 2);
    CHECK(g[0].entries[1].variant == 3 && g[0].entries[1].vertex_rec == 4 && g[0].entries[1].output_rec == 5);
    CHECK(g[1].entries.size() == 2);
    CHECK(g[1].entries[0].variant == 0 && g[1].entries[0].vertex_rec == 2 && g[1].entries[0].output_rec == 4);
    CHECK(g[1].entries[1].variant == 4 && g[1].entries[1].vertex_rec == 0 && g[1].entries[1].output_rec == 0);
    CHECK(g[2].entries.size() == 1 && g[2].entries[0].vertex_rec == 5 && g[2].entries[0].output_rec == 0);
    CHECK(predict_stream::group(plan, at, {5, 6, 7, 9}).empty());                      // (all built: nothing to do)
    CHECK(predict_stream::group(plan, {}, {}).empty());
    CHECK(sizeof(predict_stream::Entry) == 16);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    start = draw.index("void predict_background() {")
    bg = draw[start:draw.index("\n}\n", start)]
    check('#include "predict_stream.h"' in draw, "vk_draw.cpp does not use predict_stream.h")
    check('static const bool stream = !(getenv("RX_VK_PREDICT_BG_STREAM") && !atoi(getenv("RX_VK_PREDICT_BG_STREAM")));' in bg,
          "predict_background has no RX_VK_PREDICT_BG_STREAM switch, on unless it is 0")
    # (every note read and the plan made into full notes only with the switch at 0)
    check(bg.count("pipe_notes_read()") == 1 and bg.count("predict_rebuild(") == 1, "predict_background reads all the notes more than once")
    other = bg.index("} else {", bg.index("if (stream) {"))
    check(other < bg.index("notes = pipe_notes_read();") < bg.index("predicted = predict_rebuild(notes, plan);") < bg.index("if (keys.empty()) {"),
          "predict_background reads every note or rebuilds the plan with the switch on")
    first = bg[bg.index("if (stream) {"):other]
    check("predict_stream::index(f, notes_stamp(), sizeof(PipeNote), rec.get(), [&] { return note_sane(*rec); });" in first and
          "groups = predict_stream::group(plan, at, had);" in first and "if (!plan_read(&plan)) return no_plan();" in first,
          "the records' index or the plan's groups are not made as predict_stream.h makes them")
    check("std::unordered_map<uint64_t, uint32_t> at;" in first and "std::vector<PredictPlan> plan;" in first,
          "the index and the plan outlive the block that makes the groups: held while the builder rests")
    worker = bg[bg.index("const auto worker = [&](unsigned id) {"):]
    check('in.f = fopen(pipe_notes_path().c_str(), "rb");' in worker and "~Notes() { if (f) fclose(f); }" in worker,
          "a worker does not open (and close) its own handle on the notes file")
    at = [worker.index(p) for p in ("for (const predict_stream::Entry& e : groups[i].entries) {",
                                    "if (e.variant != p.variant || !in.f) continue;",
                                    "if (!pipe_note_at(in.f, e.vertex_rec, *in.v) || !pipe_note_at(in.f, e.output_rec, *in.o)) continue;",
                                    "predicted_into(*in.n, *in.v, *in.o, keys[i], e.variant);", "build(in.n.get());")]
    check(at == sorted(at), "a worker does not read a pipeline's two notes by their records and build of them")
    check("by_program[keys[i]]" not in worker, "a worker writes into by_program (operator[]) from its thread")
    check("predicted_done(pstamp, keys[i]);" in worker, "a program built is no longer recorded")
    pred = (VK / "vk_predict.cpp").read_text(encoding="utf-8")
    note = pred[pred.index("std::unique_ptr<PipeNote> predicted_note("):pred.index("predict_rebuild(")]
    check("predicted_into(*n, V, O, prog, variant);" in note, "predict_rebuild's note is not made by predicted_into: two results")
    into = pred[pred.index("void predicted_into(PipeNote& n, const PipeNote& V, const PipeNote& O, uint64_t prog, uint64_t variant) {"):pred.index("std::unique_ptr<PipeNote> predicted_note(")]
    for line in ("n = O;", "std::memcpy(n.s.vattr, V.s.vattr, sizeof n.s.vattr);", "n.s.nvattr = V.s.nvattr;",
                 "std::memcpy(n.s.vstream, V.s.vstream, sizeof n.s.vstream);", "n.topo = V.topo;", "n.prog = prog, n.variant = variant;", "n.key = 0;"):
        check(line in into, "predicted_into no longer does: " + line)
    check("void predicted_into(PipeNote& n, const PipeNote& V, const PipeNote& O, uint64_t prog, uint64_t variant);" in
          (VK / "vk_draw.h").read_text(encoding="utf-8"), "vk_draw.h does not declare predicted_into")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_PREDICT_BG_STREAM=0`" in dev, "docs/development.md: RX_VK_PREDICT_BG_STREAM is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="predict-stream-") as tmp:
        c, exe = Path(tmp) / "stream.cpp", Path(tmp) / "stream.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe), str(Path(tmp) / "notes.bin")], capture_output=True, text=True)
        check(r.returncode == 0, "the plan as records:\n" + r.stdout)
    print("PASS: the predicted builder keeps record numbers and reads its notes when it builds")


if __name__ == "__main__":
    main()
