// tests/test_wb_rec_wait.py: gpu/vk/wb_rec_wait.h (a wait for a write-back by its writer's recording), and the stall line's
// held part (gpu/vk/stall_watch.h)
#include "../gpu/vk/wb_rec_wait.h"
#include "../gpu/vk/stall_watch.h"

#include <cstdio>
#include <cstring>
#include <vector>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

int main() {
    namespace wr = mkwvk::wb_rec_wait;

    // the switch: on with a number other than 0, off unset, empty, 0 or a word
    CHECK("unset", !wr::on(nullptr));
    CHECK("empty", !wr::on(""));
    CHECK("0", !wr::on("0"));
    CHECK("1", wr::on("1"));
    CHECK("2", wr::on("2"));
    CHECK("a word", !wr::on("yes"));

    // the finished submissions: known only once noted, the newest note of a value kept, the oldest values past the cap gone
    wr::Finished fin;
    CHECK("nothing known", fin.of(7) == 0);
    fin.note(7, 100);
    CHECK("noted", fin.of(7) == 100);
    CHECK("another value is not", fin.of(8) == 0);
    fin.note(7, 104);   // (finished again later: never in the replay, but the newer recording is the one that covers it)
    CHECK("the newer recording", fin.of(7) == 104);
    fin.note(0, 5), fin.note(9, 0);
    CHECK("no value or no recording: nothing noted", fin.of(0) == 0 && fin.of(9) == 0 && fin.by_value.size() == 1);
    fin.cap = 3;
    for (uint64_t v = 10; v < 14; v++) fin.note(v, 200 + v);
    CHECK("cap held", fin.by_value.size() == 3);
    CHECK("the oldest went", fin.of(7) == 0 && fin.of(10) == 0);
    CHECK("the newest stay", fin.of(11) == 211 && fin.of(13) == 213);

    // (Triforce) a burst in parts: piece 1 (value 40) finished, then the next piece's parallel replay, whose setup is a part's
    // submit (recording 300) and its post-part goes on; a split (301) later; the burst's end (302) records the write-backs. 40 is
    // known only at 302, and so is 41, finished after the setup; the parts' submits never finish a value
    wr::Finished burst;
    std::vector<uint64_t> open{40};
    burst.submitted(open, 300, false), open.clear();
    CHECK("burst: a part's submit does not finish the piece before it", burst.of(40) == 0);
    open.push_back(41);
    burst.submitted(open, 301, false), open.clear();
    CHECK("burst: nor a later part's", burst.of(40) == 0 && burst.of(41) == 0);
    burst.submitted(open, 302, true);
    CHECK("burst: its end finishes them", burst.of(40) == 302 && burst.of(41) == 302);
    CHECK("burst: nothing left pending", burst.pending.empty());
    open.push_back(50);
    burst.submitted(open, 303, true), open.clear();   // (a recording in one part: at its own submit, as before)
    CHECK("one part: at its submit", burst.of(50) == 303 && burst.of(40) == 302);
    burst.submitted(open, 304, false), burst.submitted(open, 305, true);   // (none finished in it: nothing noted)
    CHECK("none finished: nothing noted", burst.by_value.size() == 3);

    // the timeline's budget after the recording's wait: the bound less what that took, never below 0
    CHECK("nothing spent", wr::budget_left(wr::kBoundNs, 0) == wr::kBoundNs);
    CHECK("negative spent", wr::budget_left(wr::kBoundNs, -5) == wr::kBoundNs);
    CHECK("some spent", wr::budget_left(wr::kBoundNs, 50000000) == wr::kBoundNs - 50000000);
    CHECK("all spent", wr::budget_left(wr::kBoundNs, (int64_t)wr::kBoundNs) == 0);
    CHECK("more than all", wr::budget_left(wr::kBoundNs, (int64_t)wr::kBoundNs + 1) == 0);

    // the wait ends with the recording's only with the switch on and the recording known and done
    CHECK("on, known, done", wr::ends_at_recording(true, true, true));
    CHECK("off", !wr::ends_at_recording(false, true, true));
    CHECK("not known", !wr::ends_at_recording(true, false, false));
    CHECK("not done (its wait ran out)", !wr::ends_at_recording(true, true, false));

    // the held part: the wait after the recording was done; none when not known or not done; the signals' latency is not held
    CHECK("held: 40 ms wait, the recording done 2 ms in", wr::held_ns(true, true, 2000000, 40000000) == 38000000);
    CHECK("held: done at once", wr::held_ns(true, true, 0, 30000000) == 30000000);
    CHECK("not known", wr::held_ns(false, false, 0, 30000000) == 0);
    CHECK("not done", wr::held_ns(true, false, 250000000, 250000000) == 0);
    CHECK("the latency alone", wr::held_ns(true, true, 5000000, 5000000 + wr::kHeldMinNs - 1) == 0);
    CHECK("just over the latency", wr::held_ns(true, true, 5000000, 5000000 + wr::kHeldMinNs) == wr::kHeldMinNs);
    CHECK("the wait ended with the recording", wr::held_ns(true, true, 7000000, 7000000) == 0);

    // the stall line says the held part, only when there is one
    namespace sw = mkwvk::stall_watch;
    sw::Frame f;
    f.no = 23104, f.interval = 50.8, f.replay = 47.9, f.wb_wait = 39.4, f.wb_waits = 1, f.wb_ahead = 4;
    char b[2048];
    sw::stall_line(f, b, sizeof b);
    CHECK("no held part: not named", !std::strstr(b, "after their writer's recording"));
    f.wb_held = 1, f.wb_held_ms = 37.9;
    sw::stall_line(f, b, sizeof b);
    CHECK("held part named",
          std::strstr(b, "; 1 waits for write-backs still on the GPU 39.4 ms (up to 4 submissions ahead of it, 1 of them 37.9 ms after "
                         "their writer's recording was done (the timeline held by work stopped at a wait))") != nullptr);

    // ---- (Triforce, 11-22, the performance audit's SYNC-122) the reads' side ----
    // the mode: 1 on, 2 the check, anything else off
    CHECK("mode unset", wr::mode(nullptr) == wr::kOff);
    CHECK("mode empty", wr::mode("") == wr::kOff);
    CHECK("mode 0", wr::mode("0") == wr::kOff);
    CHECK("mode 1", wr::mode("1") == wr::kOn);
    CHECK("mode 2", wr::mode("2") == wr::kCheck);
    CHECK("mode 3", wr::mode("3") == wr::kOff);
    CHECK("mode 12", wr::mode("12") == wr::kOff);
    CHECK("mode a word", wr::mode("yes") == wr::kOff);
    CHECK("mode 1 with a tail", wr::mode("1x") == wr::kOff);
    // RX_VK_TL_REC: 2 the old lookup; on otherwise it ends the wait as mode 1 does
    CHECK("tl unset", !wr::tl_rec_first_part(nullptr));
    CHECK("tl 1", !wr::tl_rec_first_part("1"));
    CHECK("tl 2", wr::tl_rec_first_part("2"));
    CHECK("ends: all off", !wr::ends_by_switch(wr::kOff, false, false));
    CHECK("ends: the check never ends a wait", !wr::ends_by_switch(wr::kCheck, false, false));
    CHECK("ends: mode 1", wr::ends_by_switch(wr::kOn, false, false));
    CHECK("ends: RX_VK_TL_REC", wr::ends_by_switch(wr::kOff, true, false));
    CHECK("ends: RX_VK_TL_REC=2 has its own wait", !wr::ends_by_switch(wr::kOff, true, true));
    CHECK("ends: the check with RX_VK_TL_REC", wr::ends_by_switch(wr::kCheck, true, false));
    CHECK("callers", !std::strcmp(wr::caller_name(wr::kTake), "takes") && !std::strcmp(wr::caller_name(wr::kRead), "reads") &&
                         !std::strcmp(wr::caller_name(wr::kBind), "binds") && !std::strcmp(wr::caller_name(wr::kReadback), "readbacks") &&
                         wr::kCallers == 4);
    CHECK("sliced only with a mode and a recordings' timeline",
          !wr::fallback_sliced(wr::kOff, true) && !wr::fallback_sliced(wr::kOn, false) && !wr::fallback_sliced(wr::kCheck, false) &&
              wr::fallback_sliced(wr::kOn, true) && wr::fallback_sliced(wr::kCheck, true));

    // the fallback wait against a made-up GPU: the writer's recording is known at K, done at R, and the submissions' timeline
    // reaches the value at T (K <= R <= T: known at its submit, and the timeline cannot pass the recording that finished it)
    struct Gpu {
        int64_t K, R, T, t = 0;
        int plains = 0, flushes = 0, lookups = 0, rec_waits = 0, slices = 0;
        bool fail_slice = false;
        void plain() { plains++, t = t > T ? t : T; }
        void flush() { flushes++; }
        uint64_t lookup() { lookups++; return t >= K ? 77 : 0; }
        int rec_wait(uint64_t seq) {
            if (seq != 77) return 2;
            rec_waits++, t = t > R ? t : R;
            return 0;
        }
        bool rec_done(uint64_t seq) { return seq == 77 && t >= R; }
        int slice() {
            slices++;
            if (fail_slice) return 2;
            if (T <= t + (int64_t)wr::kSliceNs) {
                t = t > T ? t : T;
                return 0;
            }
            t += (int64_t)wr::kSliceNs;
            return 1;
        }
        int64_t now() { return t; }
    };
    uint64_t rng = 0x9E3779B97F4A7C15ull;
    const auto rnd = [&](uint64_t n) {
        rng ^= rng << 13, rng ^= rng >> 7, rng ^= rng << 17;
        return (int64_t)(rng % n);
    };
    for (int i = 0; i < 20000; i++) {
        const int64_t K = rnd(40000000), R = K + rnd(20000000), T = R + rnd(i % 3 ? 60000000 : 50000);
        Gpu off{K, R, T};
        const wr::FallbackResult a = wr::fallback_wait(wr::kOff, true, off);
        CHECK("off: the one old wait and nothing else",
              off.plains == 1 && !off.flushes && !off.lookups && !off.rec_waits && !off.slices && !a.sliced && a.total_ns == T &&
                  wr::fallback_held_ns(a) == 0);
        Gpu none{K, R, T};
        const wr::FallbackResult n1 = wr::fallback_wait(wr::kOn, false, none);
        CHECK("no recordings' timeline: the old wait in any mode", none.plains == 1 && !none.slices && !n1.sliced && n1.total_ns == T);
        Gpu chk{K, R, T};
        const wr::FallbackResult c = wr::fallback_wait(wr::kCheck, true, chk);
        CHECK("the check ends where the old wait ends", c.total_ns == a.total_ns && chk.t == off.t);
        CHECK("the check makes neither the old wait nor the recording's", !chk.plains && !chk.rec_waits && c.sliced && !c.at_recording && !c.error);
        CHECK("the check flushes before each look", chk.flushes == chk.slices);
        const int64_t h = wr::fallback_held_ns(c);
        CHECK("the check's held part is never more than the part after the recording", h <= T - R);
        // (seen done at the first look at or after R: a slice late at most; under the latency's floor it is not named)
        if (T - R >= (int64_t)wr::kSliceNs + wr::kHeldMinNs) CHECK("the check's held part, to a slice", h >= T - R - (int64_t)wr::kSliceNs);
        if (T - R < wr::kHeldMinNs) CHECK("no held part under the latency", h == 0);
        Gpu on{K, R, T};
        const wr::FallbackResult o = wr::fallback_wait(wr::kOn, true, on);
        CHECK("on: never the old wait", !on.plains && o.sliced && !o.error);
        CHECK("on: never past where the old wait ends", o.total_ns <= T);
        if (o.at_recording) {
            CHECK("on: not before the writer's recording is done", o.total_ns >= R && on.rec_waits == 1);
            CHECK("on: at the recording, or a slice after it was known", o.total_ns <= (R > K + (int64_t)wr::kSliceNs ? R : K + (int64_t)wr::kSliceNs));
            CHECK("on: nothing held", wr::fallback_held_ns(o) == 0);
        } else {
            CHECK("on: ended by the timeline only when it got there first", o.total_ns == T && !on.rec_waits);
        }
    }
    {
        Gpu bad{1000000, 2000000, 900000000};
        bad.fail_slice = true;
        const wr::FallbackResult e = wr::fallback_wait(wr::kCheck, true, bad);
        CHECK("an error ends the wait", e.error && bad.slices == 1 && wr::fallback_held_ns(e) == 0);
    }

    // the stall line names the held part by caller, only when there is one
    sw::Frame g;
    g.no = 1, g.interval = 60, g.replay = 50;
    sw::stall_line(g, b, sizeof b);
    CHECK("no held part by caller: not named", !std::strstr(b, "by caller"));
    g.wb_held_by[wr::kRead] = 12.5, g.wb_held_by[wr::kReadback] = 3.5;
    sw::stall_line(g, b, sizeof b);
    CHECK("held part by caller named",
          std::strstr(b, "; the timeline held after a writer's recording was done, by caller: takes 0.0, reads 12.5, binds 0.0, "
                         "readbacks 3.5 ms") != nullptr);

    std::puts("PASS: write-back waits by the writer's recording, and the held part");
    return 0;
}
