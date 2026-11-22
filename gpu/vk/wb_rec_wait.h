// (Triforce, wp20-onepct; the handoff's §12.9: a read waits for its writer's part, not its whole submission) A wait for a
// write-back still on the GPU (vk_replay.cpp vk_timeline_wait: a capture's late pages on the game's submitting thread, a read or
// a binding of a page put off) waited for the submissions' timeline to reach the writer's value. That timeline is signalled only
// as far as no older submission is stopped at an event wait (vk_replay.cpp finish_recording): with another queue's work stopped,
// the wait went on after the GPU had done the write-back, until that work was let on and recorded. The lab's steady Market had a
// late-page wait of 20 to 46 ms about once a minute with the GPU 4 submissions behind at 5.5 ms of GPU time a frame (r37, r38,
// r41: 186 waits of 8 ms or more in 15 runs, the median 11.9 ms), each a stall of the game's thread.
//
// The recordings' timeline (vk_replay.cpp rec_timeline) is signalled at the end of every recording, in the queue's order, and a
// signal covers all that was submitted before it; so the recording a submission was finished in, done, means all that submission
// recorded is done, its write-backs too. The write-backs a recording makes are noted under its value (vk_memory.cpp
// wb_pages_note, mem_rec_value), and only a submission finished in a recording is known here (Finished), never one still being
// recorded or stopped at a wait: those are waited for on the timeline as before. The timeline cannot reach a value before the
// recording that finished it is done, so waiting for the recording first never makes the wait longer: the part after it is the
// timeline held (held_ns), counted always (the stall line, the frame trace, the capture's late line). RX_VK_WB_WAIT_REC=1 ends the
// wait there. Off by default: the captures' late-page wait orders something the game's frame depends on that is not known yet
// (vk_memory.cpp take_capture, RX_VK_LATE_NEW), and what the stopped work writes back lands after the copy taken without its
// wait. Tried with the lab's flicker count (scenario.ps1 -Flick) before it is turned on. tests/test_wb_rec_wait.py
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <map>
#include <vector>

namespace mkwvk::wb_rec_wait {

/// The longest wait (ns): vk_timeline_wait's bound, both waits together
constexpr uint64_t kBoundNs = 250000000ull;
/// A held part shorter than this is the two signals' own latency, not the timeline held (ns)
constexpr int64_t kHeldMinNs = 100000;

/// RX_VK_WB_WAIT_REC's text: on with a number other than 0
inline bool on(const char* text) { return text && *text && std::atoi(text) != 0; }

/// What is left of the bound for the timeline's wait after the recording's took spent_ns
inline uint64_t budget_left(uint64_t bound_ns, int64_t spent_ns) {
    if (spent_ns <= 0) return bound_ns;
    return (uint64_t)spent_ns >= bound_ns ? 0 : bound_ns - (uint64_t)spent_ns;
}

/// Whether the wait ends with the recording's: the switch on, the recording known, and done within the bound
inline bool ends_at_recording(bool switch_on, bool known, bool done) { return switch_on && known && done; }

/// The part of a wait of total_ns after its writer's recording was done (rec_ns into it): 0 when the recording is not known, or
/// was not done within the bound, or the rest is the signals' latency alone
inline int64_t held_ns(bool known, bool done, int64_t rec_ns, int64_t total_ns) {
    if (!known || !done || total_ns <= rec_ns) return 0;
    const int64_t h = total_ns - rec_ns;
    return h >= kHeldMinNs ? h : 0;
}

/// The finished submissions: value -> the recording (its number on the recordings' timeline) it was finished in; the oldest go
/// past cap. Noted at the submit that ends the recording they were finished in (submitted), never for one still being recorded
struct Finished {
    std::map<uint64_t, uint64_t> by_value;
    size_t cap = 8192;
    /// ((Triforce) the submissions finished in a recording that goes on in another part. A part's submit (a split, the early
    /// tail's start, a parallel replay's setup before its segments) is not the end of their write-backs: a burst's are noted
    /// under its value, and the last of them are recorded at the burst's end (vk_replay.cpp finish_recording,
    /// memory_end_submission), a later part than the piece that finished them; a parallel replay's setup records none. Noted at
    /// the part's number, a wait ended there (RX_VK_WB_WAIT_REC=1) before its writer's part had run)
    std::vector<uint64_t> pending;
    /// A recording's submit, its number rec: values, the submissions finished in it since its submit before. ends: the recording
    /// ends with it (finish_recording, a present's); else a part of it, and they are noted at the submit that ends the recording
    void submitted(const std::vector<uint64_t>& values, uint64_t rec, bool ends) {
        pending.insert(pending.end(), values.begin(), values.end());
        if (!ends) return;
        for (uint64_t v : pending) note(v, rec);
        pending.clear();
    }
    void note(uint64_t value, uint64_t rec) {
        if (!value || !rec) return;
        by_value[value] = rec;
        while (by_value.size() > cap) by_value.erase(by_value.begin());
    }
    /// The recording value was finished in; 0: not known (not finished yet, or too old)
    uint64_t of(uint64_t value) const {
        const auto it = by_value.find(value);
        return it == by_value.end() ? 0 : it->second;
    }
};

// ---- (Triforce, 11-22, the performance audit's SYNC-122, after Source B's) The reads' side of the same held timeline ----
// A CPU readback (vk_replay.cpp invalidate) waits for its own write-back's value. Where the recording that carries it is known
// it waits on the recordings' timeline (wait_recorded) and a stopped queue does not hold it. Where it is not known yet (the
// writer still being recorded, or stopped at an event wait) it fell back to the submissions' timeline with no bound and no
// second look: recorded and done a moment later, the read still waited until every older stopped submission had gone on. The
// reads and bindings of pages put off (vk_memory.cpp late_unresolved_read, late_deferred_bound) wait in vk_timeline_wait, whose
// held part was counted for all its callers together.
//
// RX_VK_WB_WAIT_REC is a mode now: 1 as it was (the waits end at the writer's recording), 2 the check: nothing ends earlier,
// and the readback's fallback counts what 1 would not have waited. Unset, 0 or any other text: off, the fallback is the one
// unbounded wait it was. Under 1 and 2 the fallback waits in slices of 1 ms and looks the recording up between them.
// RX_VK_TL_REC=1 (and the lab knob tlrec) ended a capture's wait at value_rec's recording, a submission's FIRST part unless
// RX_VK_REC_LAST: before the burst's write-backs are recorded. It now ends the wait as RX_VK_WB_WAIT_REC=1 does, at the
// recording the submission was finished in (Finished); RX_VK_TL_REC=2 keeps the old lookup.

/// RX_VK_WB_WAIT_REC's modes
enum Mode { kOff = 0, kOn = 1, kCheck = 2 };
/// Its text: "1" on, "2" the check; unset, empty, "0" and anything else (a word, another number, a number with a tail): off
inline int mode(const char* text) {
    if (!text || !text[0] || text[1]) return kOff;
    return text[0] == '1' ? kOn : text[0] == '2' ? kCheck : kOff;
}
/// RX_VK_TL_REC's text names the old lookup (value_rec: a first part): the number 2
inline bool tl_rec_first_part(const char* text) { return text && std::atoi(text) == 2; }
/// Whether a capture's wait ends at the recording its submission was finished in: RX_VK_WB_WAIT_REC=1, or RX_VK_TL_REC (its
/// switch or its knob: tl_rec) unless that asks for the old lookup, which has its own wait before this one
inline bool ends_by_switch(int wb_mode, bool tl_rec, bool tl_first_part) {
    return wb_mode == kOn || (tl_rec && !tl_first_part);
}

/// The waits' callers, for the held part by caller: a capture's take, a read of a page put off, a binding of one, a readback
enum Caller { kTake = 0, kRead = 1, kBind = 2, kReadback = 3, kCallers = 4 };
inline const char* caller_name(int who) {
    static const char* const names[kCallers] = {"takes", "reads", "binds", "readbacks"};
    return who >= 0 && who < kCallers ? names[who] : "?";
}

/// A slice of the readback's fallback wait (ns)
constexpr uint64_t kSliceNs = 1000000ull;
/// Whether the fallback waits in slices and looks the recording up between them: the mode on or the check, and a recordings'
/// timeline to look on. Otherwise the one unbounded wait on the submissions' timeline, as before
inline bool fallback_sliced(int wb_mode, bool has_rec_timeline) { return wb_mode != kOff && has_rec_timeline; }

/// What a fallback wait did
struct FallbackResult {
    bool sliced = false;     // (it waited in slices)
    bool known = false;      // (the writer's recording became known during the wait)
    bool at_recording = false;   // (it ended with the recording's wait: mode 1)
    bool error = false;      // (a wait gave something other than done or a timeout: a lost device; the wait ends)
    int64_t rec_ns = -1;     // (when the recording was seen done, from the wait's start; -1: never seen)
    int64_t total_ns = 0;
    int64_t slices = 0;
};
/// The fallback wait over the calls it makes, so that a test can run it against a made-up GPU. d has:
///   void plain()            the old wait: the held submits flushed, then the submissions' timeline, no bound
///   void flush()            the held submits flushed (nothing when none is held)
///   uint64_t lookup()       the recording the value was finished in, 0 while not known
///   int rec_wait(seq)       the recordings' timeline waited for with no bound: 0 done, 2 an error
///   bool rec_done(seq)      the recordings' timeline has passed seq (a poll)
///   int slice()             the submissions' timeline waited for kSliceNs: 0 reached, 1 not yet, 2 an error
///   int64_t now()           ns since the wait's start
/// Mode 1 ends at the recording once it is known (no overall bound: the read needs its bytes). Mode 2 ends where the old wait
/// ends, when the submissions' timeline reaches the value, and only notes when the recording was done. Mode 0: plain()
template <class D>
FallbackResult fallback_wait(int wb_mode, bool has_rec_timeline, D& d) {
    FallbackResult r;
    if (!fallback_sliced(wb_mode, has_rec_timeline)) {
        d.plain();
        r.total_ns = d.now();
        return r;
    }
    r.sliced = true;
    uint64_t seq = 0;
    for (;;) {
        d.flush();   // (a batched submit holds both timelines' signals; the writer may have been recorded and held since)
        if (!seq) seq = d.lookup();
        if (seq) {
            r.known = true;
            if (wb_mode == kOn) {
                r.error = d.rec_wait(seq) != 0;
                r.at_recording = !r.error;
                r.rec_ns = d.now();
                break;
            }
            if (r.rec_ns < 0 && d.rec_done(seq)) r.rec_ns = d.now();
        }
        const int s = d.slice();
        r.slices++;
        if (s == 1) continue;
        r.error = s != 0;
        // (the timeline cannot reach the value before the recording that finished it is done: seen now if not before)
        if (!r.error && seq && r.rec_ns < 0 && d.rec_done(seq)) r.rec_ns = d.now();
        break;
    }
    r.total_ns = d.now();
    return r;
}
/// The part of a checked fallback wait (mode 2) after its writer's recording was seen done: what mode 1 would not have waited.
/// To a slice's grain: the recording is looked at between slices
inline int64_t fallback_held_ns(const FallbackResult& r) {
    if (!r.sliced || r.at_recording || r.error || r.rec_ns < 0) return 0;
    return held_ns(true, true, r.rec_ns, r.total_ns);
}

} // namespace mkwvk::wb_rec_wait
