#include "../gpu/vk/target_overlap.h"

#include <cstdio>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

int main() {
    using mkwvk::target_overlap::shifted_over;
    // (OoT's 768 x 432 RGBA16F transient targets: 2.6 MB each, made ~1.2 MB apart in a scratch heap)
    const uint64_t size = 768ull * 432 * 8, step = 0x128200;
    const uint64_t a = 0x10005db1600, b = a + step;

    CHECK("a newer target from a shifted start kills it", shifted_over(a, a + size, 100, b, b + size, 101));
    CHECK("and one that starts before it", shifted_over(b, b + size, 100, a, a + size, 101));
    CHECK("not when it was written before the last use", !shifted_over(a, a + size, 100, b, b + size, 100));
    CHECK("not when it was written before the last use (older)", !shifted_over(a, a + size, 100, b, b + size, 40));
    CHECK("the same start is drawn_over's case", !shifted_over(a, a + size, 100, a, a + size / 2, 101));
    CHECK("a view inside it is not a new target", !shifted_over(a, a + size, 100, a + 4096, a + size - 4096, 101));
    CHECK("one covering it whole is", shifted_over(a + 4096, a + size, 100, a, a + 2 * size, 101));
    CHECK("an overlap of an eighth is enough", shifted_over(a, a + 8 * 4096, 100, a + 7 * 4096, a + 20 * 4096, 101));
    CHECK("less than an eighth is not", !shifted_over(a, a + 8 * 4096, 100, a + 7 * 4096 + 1, a + 20 * 4096, 101));
    CHECK("apart is not", !shifted_over(a, a + size, 100, a + size, a + 2 * size, 101));
    CHECK("empty ranges are not", !shifted_over(a, a, 100, a - 1, a + size, 101) && !shifted_over(a, a + size, 100, b, b, 101));
    {   // ((Triforce, 11-21, TEX-30) the others' parts added up, each byte once
        using mkwvk::target_overlap::ShiftedOver;
        const uint64_t p = 4096, t = a, n = 16 * p;   // (a target of 16 pages)
        ShiftedOver s{t, t + n, 100};
        s.add(t - 4 * p, t + p, 101);                 // (a sixteenth over its head)
        CHECK("a sixteenth alone is not an eighth", !s.an_eighth() && s.covered() == p);
        CHECK("nor is it one by one", !shifted_over(t, t + n, 100, t - 4 * p, t + p, 101) && !shifted_over(t, t + n, 100, t + 15 * p, t + 20 * p, 101));
        s.add(t + 15 * p, t + 20 * p, 101);           // (and a sixteenth over its tail)
        CHECK("a sixteenth over the head and one over the tail make an eighth", s.an_eighth() && s.covered() == 2 * p);
        ShiftedOver o{t, t + n, 100};
        o.add(t - p, t + p, 101), o.add(t - p / 2, t + p + p / 2, 105);   // (two over its head, half a page of them shared)
        CHECK("parts that overlap count once", o.covered() == p + p / 2 && !o.an_eighth());
        o.add(t + 15 * p + p / 2, t + 20 * p, 101);   // (and half a page over its tail)
        CHECK("and a part elsewhere adds to them", o.covered() == 2 * p && o.an_eighth());
        ShiftedOver w{t, t + n, 100};
        w.add(t - p, t + 8 * p, 100), w.add(t - p, t + 8 * p, 40);
        CHECK("one written by its last use counts nothing", w.covered() == 0 && !w.an_eighth());
        w.add(t, t + 8 * p, 101);
        CHECK("the same start is drawn_over's case", w.covered() == 0);
        w.add(t + p, t + 9 * p, 101);
        CHECK("a view inside it is not a new target", w.covered() == 0);
        w.add(t + n, t + 2 * n, 101);
        CHECK("apart is not", w.covered() == 0 && !w.an_eighth());
        ShiftedOver whole{t + p, t + n, 100};
        whole.add(t, t + 2 * n, 101);
        CHECK("one covering it whole is", whole.an_eighth() && whole.covered() == n - p);
        ShiftedOver empty{t, t, 100};
        empty.add(t - p, t + p, 101);
        CHECK("an empty range is not", !empty.an_eighth());
    }
    std::puts("target overlap: all checks passed");
}
