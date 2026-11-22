// The eviction's stale write-back rule (gpu/vk/evict_reason.h); run by tests/test_evict_reason.py.
// (Triforce, 11-22, the performance audit's TEX-R404, after Source A's.)
#include "../gpu/vk/evict_reason.h"

#include <cstdio>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

int main() {
    using namespace evict_reason;
    // the switch: unset, empty and 0 leave a stale write-back out
    CHECK("the switch unset", !flush_stale(nullptr) && !flush_stale("") && !flush_stale("0"));
    CHECK("the switch set", flush_stale("1") && flush_stale("2"));
    // Source A's frames: a target last drawn in frame 3804, a label drawn inside it in 3987
    CHECK("a later drawing makes it stale", write_back_stale(3804, 3987));
    CHECK("no other drawing", !write_back_stale(3804, 0));
    CHECK("an older drawing", !write_back_stale(3804, 1468));
    CHECK("a drawing in the same frame keeps it", !write_back_stale(3804, 3804));
    CHECK("the frame after", write_back_stale(3804, 3805));
    // the trace's addresses: a 1920 x 1080 target of 8,640 KB and a label inside it
    const uint64_t target = 0x1001e88fc00ull, target_end = target + 8640ull * 1024;
    const uint64_t label = 0x1001f039400ull, label_end = label + 110ull * 110 * 4;
    CHECK("the label is inside the target", label > target && label_end < target_end);
    CHECK("they overlap, either way round", overlaps(target, target_end, label, label_end) && overlaps(label, label_end, target, target_end));
    CHECK("ranges that touch are apart", !overlaps(target, target_end, target_end, target_end + 4096) &&
                                         !overlaps(target_end, target_end + 4096, target, target_end));
    CHECK("one byte shared", overlaps(target, target_end, target_end - 1, target_end + 4096));
    CHECK("apart", !overlaps(target, target_end, target_end + 4096, target_end + 8192));
    CHECK("an empty range overlaps nothing", !overlaps(target, target, target - 1, target_end) && !overlaps(target, target_end, label, label));
    CHECK("the same range", overlaps(target, target_end, target, target_end));

    // the walk: candidates in any order, the others noted one by one
    int self_target = 0, self_label = 0, self_far = 0, other = 0;
    std::vector<Candidate> c;
    c.push_back({label, label_end, 7, &self_label, 0});
    c.push_back({target_end + (64ull << 20), target_end + (65ull << 20), 9, &self_far, 0});
    c.push_back({target, target_end, 3, &self_target, 0});
    const uint64_t longest = by_start(c);
    CHECK("in the order of their starts", c[0].lo == target && c[1].lo == label && c[2].self == &self_far);
    CHECK("each keeps its place in the caller's list", c[0].index == 3 && c[1].index == 7 && c[2].index == 9);
    CHECK("the longest", longest == 8640ull * 1024);
    note(c, longest, target, target_end, 3804, &self_target);                     // (the target itself)
    CHECK("a candidate is not another image over its own storage", c[0].newest == 0);
    CHECK("but it is one over the label's", c[1].newest == 3804 && c[2].newest == 0);
    note(c, longest, label, label_end, 3987, &self_label);                        // (the label itself)
    CHECK("the label, drawn later, is the target's newest other", c[0].newest == 3987 && c[1].newest == 3804);
    CHECK("the target's write-back is stale, the label's is not",
          write_back_stale(3804, c[0].newest) && !write_back_stale(3987, c[1].newest));
    note(c, longest, target + 4096, target + 8192, 1468, &other);                 // (an older image inside the target)
    CHECK("an older one does not lower it", c[0].newest == 3987);
    note(c, longest, target_end, target_end + 4096, 5000, &other);                // (one that touches the target's end)
    CHECK("one that only touches counts nothing", c[0].newest == 3987 && c[1].newest == 3804 && c[2].newest == 0);
    note(c, longest, target - 4096, target, 5000, &other);                        // (and its start)
    CHECK("nor one that ends where it starts", c[0].newest == 3987);
    note(c, longest, target - (16ull << 20), target + 1, 4100, &other);           // (a long one from far before, a byte into it)
    CHECK("a long image from before the start is found", c[0].newest == 4100 && c[1].newest == 3804);
    note(c, longest, 0, ~0ull, 4200, &other);                                     // (one over everything)
    CHECK("one over everything reaches all", c[0].newest == 4200 && c[1].newest == 4200 && c[2].newest == 4200);
    note(c, longest, label, label, 9000, &other);                                 // (an empty one)
    CHECK("an empty image counts nothing", c[1].newest == 4200);
    {   // (no candidates: nothing to do, nothing read)
        std::vector<Candidate> none;
        const uint64_t l = by_start(none);
        note(none, l, target, target_end, 1, &other);
        CHECK("no candidates", l == 0 && none.empty());
    }
    {   // (many candidates side by side, one other over three of them)
        std::vector<Candidate> v;
        static int selves[64];
        for (int i = 63; i >= 0; i--) v.push_back({0x1000ull * (uint64_t)i, 0x1000ull * (uint64_t)i + 0x1000, (size_t)i, &selves[i], 0});
        const uint64_t l = by_start(v);
        note(v, l, 0x1000ull * 10 + 0x800, 0x1000ull * 12 + 1, 77, &other);
        for (int i = 0; i < 64; i++) CHECK("only the three it covers", v[(size_t)i].newest == (i >= 10 && i <= 12 ? 77u : 0u));
    }
    std::printf("evict reason: all checks passed\n");
    return 0;
}
