#include "../gpu/vk/dlss_checks.h"

#include <clocale>
#include <cstdio>
#include <string>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

namespace dc = mkwvk::dlss_checks;

/// The menu's size for a share of the output in twelfths (gpu/vk/vk_menu.cpp game_size): what the game draws the 3D at
static void game_size(unsigned ow, unsigned oh, int k, unsigned& w, unsigned& h) { w = (ow * k + 11) / 12, h = oh * k / 12; }

static std::wstring decode(const std::string& s, bool& bad) {
    bad = false;
    return dc::utf8_to_wide(s, &bad);
}

int main() {
    // ---- the scene sizes DLSS takes for an output ----
    // (the validation report's case: the handheld profile's 1536x864 at Ultra Performance draws its scene at 512x288,
    // which the old 640x360 floor turned away)
    CHECK("handheld Ultra Performance", dc::scene_size_fits(512, 288, 1536, 864));
    CHECK("docked Ultra Performance", dc::scene_size_fits(683, 384, 2048, 1152));
    CHECK("handheld at the game's 3/4", dc::scene_size_fits(1152, 648, 1536, 864));
    CHECK("DLAA, the scene at full size", dc::scene_size_fits(1536, 864, 1536, 864));
    CHECK("1080p Ultra Performance", dc::scene_size_fits(640, 360, 1920, 1080));
    // every output the menu has, with every DLSS share (8, 7, 6, 4 twelfths) and DLAA's (12)
    const unsigned outputs[][2] = {{1536, 864}, {1920, 1080}, {2048, 1152}, {2560, 1440}, {3840, 2160}};
    for (const auto& o : outputs)
        for (int k : {12, 8, 7, 6, 4}) {
            unsigned w, h;
            game_size(o[0], o[1], k, w, h);
            CHECK("each mode at each output", dc::scene_size_fits(w, h, o[0], o[1]));
        }
    // what is still turned away
    CHECK("output not known yet", !dc::scene_size_fits(512, 288, 0, 0));
    CHECK("output not known yet (1080p scene)", !dc::scene_size_fits(1536, 864, 0, 0));
    CHECK("no size", !dc::scene_size_fits(0, 0, 1536, 864));
    CHECK("under a third wide", !dc::scene_size_fits(511, 288, 1536, 864));
    CHECK("under a third high", !dc::scene_size_fits(512, 287, 1536, 864));
    CHECK("a square shadow-map-like target", !dc::scene_size_fits(384, 384, 1536, 864));
    CHECK("a half-size pass of the handheld scene", !dc::scene_size_fits(256, 144, 1536, 864));
    CHECK("the old floor is under a third of 2048x1152", !dc::scene_size_fits(640, 360, 2048, 1152));
    CHECK("larger than the output", !dc::scene_size_fits(2048, 1152, 1536, 864));
    CHECK("wider than the output", !dc::scene_size_fits(1537, 864, 1536, 864));
    CHECK("no 32-bit overflow in the third", dc::scene_size_fits(0x60000000u, 1, 0xFFFFFFFFu, 3));

    // ---- ((Triforce, 11-22, the performance audit's PRESENT-38) the quality mode that takes a render size ----
    {
        // (NGX's ranges for 2560x1440, in vk_dlss.cpp's order: MaxQuality with its dynamic range, DLAA, Balanced and MaxPerf
        // inside MaxQuality's, Ultra Performance one size)
        const dc::ModeRange r1440[5] = {{1280, 720, 2560, 1440, true}, {2560, 1440, 2560, 1440, true}, {1280, 720, 2560, 1440, true},
                                        {1280, 720, 2560, 1440, true}, {853, 480, 853, 480, true}};
        bool wide = true;
        CHECK("Quality's share is in the first range", dc::mode_for(r1440, 5, 1707, 960, 2560, 1440, true, &wide) == 0 && !wide);
        CHECK("a range that holds the size needs no slack", dc::mode_for(r1440, 5, 1707, 960, 2560, 1440, false, &wide) == 0 && !wide);
        CHECK("the row's 33% (854x480) is Ultra Performance's by a rounding", dc::mode_for(r1440, 5, 854, 480, 2560, 1440, true, &wide) == 4 && wide);
        CHECK("without the slack it is no mode's, as before", dc::mode_for(r1440, 5, 854, 480, 2560, 1440, false, &wide) == -1 && !wide);
        CHECK("NGX's own 853x480 is taken strictly", dc::mode_for(r1440, 5, 853, 480, 2560, 1440, false, &wide) == 4 && !wide);
        CHECK("42% is between the ranges: no mode's", dc::mode_for(r1440, 5, 1075, 605, 2560, 1440, true, &wide) == -1);
        CHECK("under a third of the output is not DLSS's at all", dc::mode_for(r1440, 5, 851, 478, 2560, 1440, true, &wide) == -1);
        CHECK("a size just under the dynamic range's floor is taken by the slack", dc::mode_for(r1440, 5, 1278, 719, 2560, 1440, true, &wide) == 0 && wide);
        CHECK("the slack is a 64th of the range's largest size", dc::mode_slack(2560) == 40 && dc::mode_slack(853) == 13 && dc::mode_slack(100) == 2 && dc::mode_slack(0) == 2);
        CHECK("past the slack on one axis is refused", dc::mode_for(r1440, 5, 867, 480, 2560, 1440, true, &wide) == -1);
        CHECK("14 pixels over Ultra Performance's height is refused", dc::mode_for(r1440, 5, 854, 494, 2560, 1440, true, &wide) == -1);
        // (5120x2160: the row's 33% is 1707x720, NGX's 1706x720; 42% is in no range)
        const dc::ModeRange r2160[5] = {{2560, 1080, 5120, 2160, true}, {5120, 2160, 5120, 2160, true}, {2560, 1080, 5120, 2160, true},
                                        {2560, 1080, 5120, 2160, true}, {1706, 720, 1706, 720, true}};
        CHECK("5120x2160 at 33%", dc::mode_for(r2160, 5, 1707, 720, 5120, 2160, true, &wide) == 4 && wide);
        CHECK("5120x2160 at 42%", dc::mode_for(r2160, 5, 2150, 907, 5120, 2160, true, &wide) == -1);
        // (a mode NGX did not answer is never taken, and the first that fits wins)
        dc::ModeRange gaps[5] = {{}, {}, {1280, 720, 2560, 1440, true}, {1280, 720, 2560, 1440, true}, {}};
        CHECK("an unanswered mode is skipped", dc::mode_for(gaps, 5, 1707, 960, 2560, 1440, true, &wide) == 2 && !wide);
        CHECK("no mode answered", dc::mode_for(gaps, 2, 1707, 960, 2560, 1440, true, &wide) == -1);
        // (every twelfth of every output the menu offers is some mode's with the slack, where NGX's sizes are the share rounded down)
        const uint32_t outs[][2] = {{1920, 1080}, {2048, 1152}, {2560, 1440}, {3840, 2160}, {3440, 1440}, {5120, 2160}, {1536, 864}, {4416, 1864}};
        for (const auto& o : outs) {
            const dc::ModeRange r[5] = {{o[0] / 2, o[1] / 2, o[0], o[1], true}, {o[0], o[1], o[0], o[1], true}, {o[0] / 2, o[1] / 2, o[0], o[1], true},
                                        {o[0] / 2, o[1] / 2, o[0], o[1], true}, {o[0] / 3, o[1] / 3, o[0] / 3, o[1] / 3, true}};
            for (const uint32_t twelfths : {4u, 6u, 7u, 8u}) {
                const uint32_t w = (o[0] * twelfths + 11) / 12, h = (o[1] * twelfths + 11) / 12;
                CHECK("a share of the row at an output of the menu", dc::mode_for(r, 5, w, h, o[0], o[1], true, &wide) >= 0);
            }
        }
    }

    // ---- UTF-8 paths as NGX's wide strings, in the C locale (the decoding must not depend on it) ----
    std::setlocale(LC_ALL, "C");
    // (which paths NGX's Linux library takes as they are: ASCII only. The others go to it as /proc/self/fd/<n>)
    CHECK("ASCII path", dc::ascii("/home/u/Games/Hookshot/ngx") && dc::ascii(""));
    CHECK("accented path", !dc::ascii("/home/u/Games/Hookshot-Caf\xC3\xA9/ngx"));
    CHECK("CJK path", !dc::ascii("/g/\xE3\x82\xBC"));
    CHECK("a byte that is not UTF-8", !dc::ascii("/g/\xFF"));
    bool bad = false;
    CHECK("ASCII", decode("/home/u/Games/Hookshot/ngx", bad) == L"/home/u/Games/Hookshot/ngx" && !bad);
    CHECK("accented", decode("/home/u/Games/Hookshot-Caf\xC3\xA9/ngx", bad) == L"/home/u/Games/Hookshot-Café/ngx" && !bad);
    CHECK("CJK", decode("/g/\xE3\x82\xBC\xE3\x83\xAB\xE3\x83\x80/ngx", bad) == L"/g/ゼルダ/ngx" && !bad);
    // (U+1F3AE: one wchar_t where it has 32 bits, a surrogate pair where it has 16, as on Windows)
    const std::wstring gamepad = sizeof(wchar_t) == 2 ? std::wstring{(wchar_t)0xD83C, (wchar_t)0xDFAE}
                                                      : std::wstring(1, (wchar_t)0x1F3AE);
    CHECK("four bytes", decode("/g/\xF0\x9F\x8E\xAE", bad) == L"/g/" + gamepad && !bad);
    CHECK("all together",
          decode("/home/u/Games/Hookshot-dlss-utf8-Caf\xC3\xA9-\xE3\x82\xBC\xE3\x83\xAB\xE3\x83\x80/ngx", bad) ==
              L"/home/u/Games/Hookshot-dlss-utf8-Café-ゼルダ/ngx" && !bad);
    // (the bug this replaces: each byte widened alone)
    const std::string cafe = "Caf\xC3\xA9";
    CHECK("the old widening was wrong", std::wstring(cafe.begin(), cafe.end()) != decode(cafe, bad));
    // bytes that are not UTF-8: U+FFFD, one for each maximal ill-formed part, and *bad set
    CHECK("a Latin-1 byte", decode("a\xE9" "b", bad) == L"a�b" && bad);
    CHECK("a lone continuation", decode("\x80x", bad) == L"�x" && bad);
    CHECK("cut at the end", decode("x\xC3", bad) == L"x�" && bad);
    CHECK("cut in the middle", decode("\xE3\x82x", bad) == L"�x" && bad);
    CHECK("overlong", decode("\xC0\xAF", bad) == L"��" && bad);
    CHECK("overlong three", decode("\xE0\x80\xAF", bad) == L"���" && bad);
    CHECK("surrogate", decode("\xED\xA0\x80", bad) == L"���" && bad);
    CHECK("past U+10FFFF", decode("\xF4\x90\x80\x80", bad) == L"����" && bad);
    CHECK("F5 and up", decode("\xF5\xFF", bad) == L"��" && bad);
    CHECK("good after bad", decode("\xFF\xC3\xA9", bad) == L"�é" && bad);
    CHECK("no flag asked", dc::utf8_to_wide("\xFF") == L"�");
    CHECK("empty", decode("", bad).empty() && !bad);
    {   // ((Triforce, 11-21, PRESENT-37) the DLSS model row stepped through: no feature for a preset passed over
        dc::PresetSettle s;
        const unsigned K = 0, M = 1, L = 2;
        CHECK("no feature: the row's preset at once", s.pick(K, ~0u, false, 100, 30) == K);
        CHECK("the feature's own preset", s.pick(K, K, true, 101, 30) == K);
        CHECK("a new preset waits", s.pick(M, K, true, 200, 30) == K && s.pick(M, K, true, 210, 30) == K);
        CHECK("stepped on: the count starts again", s.pick(L, K, true, 211, 30) == K && s.pick(L, K, true, 240, 30) == K);
        CHECK("held for 30 frames: taken", s.pick(L, K, true, 241, 30) == L);
        CHECK("and it is the feature's now", s.pick(L, L, true, 242, 30) == L);
        CHECK("away and back within the wait: nothing made", s.pick(M, L, true, 300, 30) == L && s.pick(L, L, true, 310, 30) == L);
        CHECK("the feature let go: at once", s.pick(M, L, false, 311, 30) == M);
        dc::PresetSettle now;
        CHECK("0 frames: at once, as before", now.pick(K, ~0u, false, 1, 0) == K && now.pick(M, K, true, 2, 0) == M &&
                                                 now.pick(L, M, true, 3, 0) == L);
        CHECK("the switch", dc::settle_frames(nullptr) == 30 && dc::settle_frames("") == 30 && dc::settle_frames("30") == 30 &&
                            dc::settle_frames("0") == 0 && dc::settle_frames("120") == 120 && dc::settle_frames("-5") == 0 &&
                            dc::settle_frames("off") == 0);
    }
    {   // ((Triforce, 11-22, the performance audit's PRESENT-32) the one-size (DLAA) modes: before, whenever the render size is
        // the output's; with the rule, only where DLAA is the Upscaler's choice
        CHECK("as before: one size whenever the sizes are equal", dc::dlaa_feature(false, false, 2560, 1440, 2560, 1440) &&
                                                                      dc::dlaa_feature(false, true, 2560, 1440, 2560, 1440) &&
                                                                      !dc::dlaa_feature(false, true, 1707, 960, 2560, 1440) &&
                                                                      !dc::dlaa_feature(false, false, 2560, 1439, 2560, 1440));
        CHECK("the rule: DLAA at the output's size is one size", dc::dlaa_feature(true, true, 2560, 1440, 2560, 1440));
        CHECK("the rule: DLSS at the output's size is not", !dc::dlaa_feature(true, false, 2560, 1440, 2560, 1440));
        CHECK("the rule: a smaller render size never is", !dc::dlaa_feature(true, true, 1707, 960, 2560, 1440) &&
                                                             !dc::dlaa_feature(true, false, 1707, 960, 2560, 1440));
        CHECK("RX_VK_DLSS_PREWARM: on only at 1", !dc::prewarm_rule(nullptr) && !dc::prewarm_rule("") && !dc::prewarm_rule("0") &&
                                                      dc::prewarm_rule("1") && !dc::prewarm_rule("2") && !dc::prewarm_rule("on"));
        // (DLSS at full size takes the scaled mode whose range holds it, and that range holds Auto's smaller sizes: NGX's
        // ranges as it answers them, Quality's from half the output to the output's own)
        const unsigned outs[][2] = {{1920, 1080}, {2560, 1440}, {3840, 2160}, {4416, 1864}, {5120, 2160}};
        for (const auto& o : outs) {
            const dc::ModeRange r[5] = {{o[0] / 2, o[1] / 2, o[0], o[1], true}, {o[0], o[1], o[0], o[1], true}, {o[0] / 2, o[1] / 2, o[0], o[1], true},
                                        {o[0] / 2, o[1] / 2, o[0], o[1], true}, {o[0] / 3, o[1] / 3, o[0] / 3, o[1] / 3, true}};
            bool wide = false;
            const int at = dc::mode_for(r, 5, o[0], o[1], o[0], o[1], true, &wide);
            CHECK("DLSS at the output's size: the first scaled mode's", at == 0 && !wide);
            for (unsigned pct = 50; pct <= 100; pct += 5)
                CHECK("Auto's sizes are in that mode's range", o[0] * pct / 100 >= r[at].min_w && o[0] * pct / 100 <= r[at].max_w &&
                                                                   o[1] * pct / 100 >= r[at].min_h && o[1] * pct / 100 <= r[at].max_h);
        }
    }
    std::puts("dlss checks: ok");
    return 0;
}
