// Game-free regression for the production Vulkan presentation rectangle helper.
#include <cstdio>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <limits>

#include "../vk_present_rect.h"

namespace {
int failures = 0;

void expect(const char* name, mkwvk::PresentRect got, mkwvk::PresentRect want) {
    if (got.x == want.x && got.y == want.y && got.w == want.w && got.h == want.h) return;
    std::fprintf(stderr, "%s: got {%u,%u,%u,%u}, wanted {%u,%u,%u,%u}\n", name, got.x, got.y, got.w, got.h,
                 want.x, want.y, want.w, want.h);
    failures++;
}

}  // namespace

int main() {
    using mkwvk::PresentRect;
    using mkwvk::PresentAspect;
    constexpr PresentAspect wide{43.0 / 18.0};
    const PresentRect fit_16_10 = mkwvk::present_rect(1920, 1080, nullptr, 1600, 1000);
    expect("16:9 into 16:10", fit_16_10, {0, 50, 1600, 900});
    expect("16:9 same aspect", mkwvk::present_rect(1920, 1080, nullptr, 1920, 1080), {0, 0, 1920, 1080});
    expect("logical ultrawide picture fills its own aspect even in a 16:9 texture",
           mkwvk::present_rect(1920, 1080, nullptr, 3440, 1440, wide), {0, 0, 3440, 1440});
    expect("ultrawide camera keeps its aspect after maximize",
           mkwvk::present_rect(1920, 1080, nullptr, 1920, 1009, wide), {0, 102, 1920, 804});
    expect("ultrawide picture in a 16:9 window",
           mkwvk::present_rect(1920, 1080, nullptr, 1280, 720, wide), {0, 92, 1280, 536});
    expect("ultrawide restore",
           mkwvk::present_rect(1920, 1080, nullptr, 1720, 720, wide), {0, 0, 1720, 720});
    expect("float camera ratio keeps the full 32:9 destination",
           mkwvk::present_rect(1920, 1080, nullptr, 5120, 1440, {static_cast<float>(32.0 / 9.0)}),
           {0, 0, 5120, 1440});
    expect("logical portrait content", mkwvk::present_rect(1920, 1080, nullptr, 1600, 1000, {0.5}),
           {550, 0, 500, 1000});
    // (Triforce) An Output resolution of its own shape is the picture (gpu/vk/output_sizes.h), and the host gives its shape as a
    // float (host/hos_main.c hos_aspect_ratio): on a screen of that size it fills it pixel for pixel, with no bar from the float;
    // the window it opens in (720 high) has its shape; a screen or a window of another shape shows it whole between bars
    struct Own {
        uint32_t w, h;
    };
    for (const Own o : {Own{3840, 1600}, Own{3440, 1440}, Own{2560, 1080}, Own{5120, 1440}, Own{5120, 2160}, Own{1920, 1200},
                        Own{1280, 1024}}) {
        const PresentAspect own{static_cast<float>((double)o.w / (double)o.h)};
        expect("an output size's picture on its own screen", mkwvk::present_rect(o.w, o.h, nullptr, o.w, o.h, own), {0, 0, o.w, o.h});
        const uint32_t win_w = static_cast<uint32_t>(720 * static_cast<float>(own.ratio) + 0.5f);   // (host/display.c)
        expect("an output size's picture in its starting window", mkwvk::present_rect(o.w, o.h, nullptr, win_w, 720, own),
               {0, 0, win_w, 720});
    }
    constexpr PresentAspect twelve_five{static_cast<float>(3840.0 / 1600.0)};
    expect("3840x1600 picture, fullscreen on a 3840x2160 screen",
           mkwvk::present_rect(3840, 1600, nullptr, 3840, 2160, twelve_five), {0, 280, 3840, 1600});
    expect("3840x1600 picture, fullscreen on a 3440x1440 screen",
           mkwvk::present_rect(3840, 1600, nullptr, 3440, 1440, twelve_five), {0, 3, 3440, 1433});
    expect("3840x1600 picture in a 16:9 window", mkwvk::present_rect(3840, 1600, nullptr, 1280, 720, twelve_five),
           {0, 93, 1280, 533});
    expect("3440x1440 picture, fullscreen on a 3840x1600 screen",
           mkwvk::present_rect(3440, 1440, nullptr, 3840, 1600, {static_cast<float>(3440.0 / 1440.0)}), {9, 0, 3822, 1600});
    expect("1920x1200 picture, fullscreen on a 1920x1080 screen",
           mkwvk::present_rect(1920, 1200, nullptr, 1920, 1080, {1.6f}), {96, 0, 1728, 1080});
    expect("ultrawide source aspect fits naturally",
           mkwvk::present_rect(3440, 1440, nullptr, 3440, 1440), {0, 0, 3440, 1440});
    expect("ultrawide source remains wider than 16:9",
           mkwvk::present_rect(3440, 1440, nullptr, 1600, 1000), {0, 165, 1600, 669});
    expect("portrait target", mkwvk::present_rect(1920, 1080, nullptr, 1000, 1600), {0, 519, 1000, 562});
    expect("odd resized destination", mkwvk::present_rect(1920, 1080, nullptr, 1601, 1001), {0, 50, 1601, 900});

    const int crop_16_9[4] = {160, 90, 2240, 1260};
    expect("cropped 16:9 content", mkwvk::present_rect(2560, 1440, crop_16_9, 1600, 1000), {0, 50, 1600, 900});
    const int crop_odd[4] = {7, 11, 1900, 1069};
    expect("odd crop and resized target", mkwvk::present_rect(1920, 1080, crop_odd, 1600, 1000), {0, 50, 1600, 900});
    const int crop_at_edge[4] = {90, 70, 20, 20};
    expect("small crop clamps to source edge", mkwvk::present_rect(100, 80, crop_at_edge, 160, 100), {30, 0, 100, 100});
    expect("zero source falls back to destination", mkwvk::present_rect(0, 0, nullptr, 160, 100), {0, 0, 160, 100});

    const int padded_crop[4] = {16, 8, 2560, 1440};
    expect("logical aspect belongs to the cropped picture, not the allocation",
           mkwvk::present_rect(4096, 2160, padded_crop, 1920, 1009, wide), {0, 102, 1920, 804});
    expect("generated frame keeps the same display aspect after crop is materialized",
           mkwvk::present_rect(2560, 1440, nullptr, 1920, 1009, wide), {0, 102, 1920, 804});
    const double invalid[] = {0, -1, std::numeric_limits<double>::infinity(),
                              -std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()};
    for (double ratio : invalid) {
        expect("invalid logical aspect falls back to the actual crop",
               mkwvk::present_rect(100, 80, crop_at_edge, 160, 100, {ratio}), {30, 0, 100, 100});
    }
    const uint32_t sizes[] = {1, 2, 7, 720, 1280, 1601, 3440, std::numeric_limits<uint32_t>::max()};
    const double ratios[] = {std::numeric_limits<double>::denorm_min(), 0.5, 1, 16.0 / 9.0, 43.0 / 18.0,
                              static_cast<float>(32.0 / 9.0), 1e30, std::numeric_limits<double>::max()};
    for (uint32_t dw : sizes) for (uint32_t dh : sizes) for (double ratio : ratios) {
        const PresentRect rect = mkwvk::present_rect(1920, 1080, nullptr, dw, dh, {ratio});
        if (!rect.w || !rect.h || static_cast<uint64_t>(rect.x) + rect.w > dw ||
            static_cast<uint64_t>(rect.y) + rect.h > dh || (rect.w != dw && rect.h != dh)) {
            std::fprintf(stderr, "logical fit outside destination %u x %u, aspect %.17g\n", dw, dh, ratio);
            failures++;
            continue;
        }
        const uint32_t right = dw - rect.x - rect.w, bottom = dh - rect.y - rect.h;
        if ((right > rect.x ? right - rect.x : rect.x - right) > 1 ||
            (bottom > rect.y ? bottom - rect.y : rect.y - bottom) > 1) {
            std::fprintf(stderr, "logical fit is not centered\n");
            failures++;
        }
        // Ignore the unavoidable one-pixel clamp at extreme aspects.
        if (rect.w > 1 && rect.h > 1 &&
            std::fabs(static_cast<long double>(rect.w) - rect.h * static_cast<long double>(ratio)) >
                0.5001L * (ratio > 1 ? ratio : 1)) {
            std::fprintf(stderr, "logical fit exceeds half-pixel rounding error\n");
            failures++;
        }
        expect("crop and generated frame agree", mkwvk::present_rect(4096, 2160, padded_crop, dw, dh, {ratio}), rect);
    }
    return failures ? 1 : 0;
}
