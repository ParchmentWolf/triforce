// (Triforce, 11-21, the performance audit's PIPE-83, after Source B's) The predicted builder's plan as record numbers, its
// notes read when their program's turn comes.
//
// predict_background (vk_draw.cpp) builds, behind the game, the predicted pipelines the start did not get to: on the starts
// after a translator or driver update that is most of them, and it rests while the game is in play, so it runs for much of
// a session. It read every note of the notes file (a PipeNote is ~27 KB), made a full note of every predicted pipeline, and
// held both until it ended: about 1 GB with the game's 14,535 notes and 24,182 predicted pipelines. The draws, the
// read-ahead and the warm read a note by its record already (pipe_note_at). Here: the notes file is gone through once into
// one record's buffer for each key's record number, the plan becomes {variant, the vertex note's record, the output note's
// record} for each program still to build, 16 bytes a pipeline, and a worker reads the two notes through its own handle
// when it builds that pipeline. The same programs and pipelines; a note gone since drops its pipeline, as before.
// RX_VK_PREDICT_BG_STREAM=0: every note and predicted note held, as before.
//
// No Vulkan and no PipeNote here: tests/test_predict_stream.py compiles it with a file of its own.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace predict_stream {

/// One predicted pipeline: its program's variant, and the records of the note whose vertex layout and of the note whose
/// targets and state it takes
struct Entry {
    uint64_t variant;
    uint32_t vertex_rec, output_rec;
};
/// A program still to build and its pipelines, in the plan's order
struct Program {
    uint64_t prog;
    std::vector<Entry> entries;
};

/// Each note's key to its record (0: the first after the head), of the notes file f at its start: a head of {stamp,
/// rec_bytes}, then records of rec_bytes whose first 8 bytes are the key. rec: a buffer of rec_bytes each is read into;
/// sane(): whether the one in it is used (it may mend it). A key twice keeps its first record, as pipe_notes_read. Empty
/// when the head is another build's
template <class Sane>
std::unordered_map<uint64_t, uint32_t> index(FILE* f, uint64_t stamp, uint64_t rec_bytes, void* rec, Sane&& sane) {
    std::unordered_map<uint64_t, uint32_t> at;
    uint64_t head[2] = {0, 0};
    if (!f || rec_bytes < 8 || fread(head, 8, 2, f) != 2 || head[0] != stamp || head[1] != rec_bytes) return at;
    for (uint32_t i = 0; fread(rec, (size_t)rec_bytes, 1, f) == 1; i++) {
        if (!sane()) continue;
        uint64_t key;
        std::memcpy(&key, rec, 8);
        at.emplace(key, i);
    }
    return at;
}

/// The plan (entries with prog, variant, vertex_note, output_note: PredictPlan) as the programs still to build: those not
/// in had, in the order the plan first names them, each with its pipelines in the plan's order. A pipeline one of whose
/// notes is not in the index is dropped, and a program left with none is not listed
template <class Plan>
std::vector<Program> group(const std::vector<Plan>& plan, const std::unordered_map<uint64_t, uint32_t>& at,
                           const std::unordered_set<uint64_t>& had) {
    std::vector<Program> out;
    std::unordered_map<uint64_t, size_t> where;
    for (const Plan& p : plan) {
        if (had.count(p.prog)) continue;
        const auto v = at.find(p.vertex_note), o = at.find(p.output_note);
        if (v == at.end() || o == at.end()) continue;
        const auto [it, fresh] = where.try_emplace(p.prog, out.size());
        if (fresh) out.push_back(Program{p.prog, {}});
        out[it->second].entries.push_back(Entry{p.variant, v->second, o->second});
    }
    return out;
}

}   // namespace predict_stream
