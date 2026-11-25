// SPDX-License-Identifier: GPL-3.0-or-later
// gpu/vk/load_default.h alone (tests/test_load_default.py)
#include "../gpu/vk/load_default.h"
#include <cstdlib>
#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "CHECK failed line %d: %s\n", __LINE__, #c); std::exit(1); } } while (0)

int main(int argc, char** argv) {
    CHECK(argc == 2);
    using load_default::choose;
    // the switch always wins, whatever the GPU and the marker
    for (int mesh = 0; mesh < 2; mesh++)
        for (int marker = 0; marker < 2; marker++) {
            CHECK(choose("create", mesh, marker).create);
            CHECK(!choose("start", mesh, marker).create);
            // (Triforce) without it, or with anything else, start: how the game has always loaded its programs
            CHECK(!choose(nullptr, mesh, marker).create && !choose("", mesh, marker).create && !choose("1", mesh, marker).create);
            CHECK(std::strstr(choose(nullptr, mesh, marker).why, "Triforce's default"));
        }
    // auto: create with no marker, with mesh shaders or through the compute fallback (only the reason differs)
    CHECK(choose("auto", true, false).create);
    CHECK(choose("auto", false, false).create && std::strstr(choose("auto", false, false).why, "compute fallback"));
    CHECK(!choose("auto", true, true).create);
    CHECK(!choose("auto", false, true).create);
    CHECK(std::strstr(choose("auto", true, true).why, "triforce_load_start.txt"));
    // without the shader preparation start loads nothing before the title: the marker is left aside there
    CHECK(choose("auto", true, true, false).create && choose("auto", false, true, false).create);
    CHECK(std::strstr(choose("auto", true, true, false).why, "RX_VK_PRECOMPILE=0"));
    CHECK(!choose(nullptr, true, false, false).create && !choose("start", true, false, false).create);
    // the safety net: only waits over kLongMs count; a healthy session's few milliseconds each never add up
    using load_default::counts;
    using load_default::waits_verdict;
    using load_default::Waits;
    CHECK(!counts(2.0) && !counts(7.0) && !counts(20.0) && counts(20.1) && counts(261));
    // one bad moment (261 ms, 322 in the session) is fine; over kStrikeMs a strike, the marker only the second session running
    CHECK(waits_verdict(322, false) == Waits::kFine && waits_verdict(500, false) == Waits::kFine);
    CHECK(waits_verdict(500.1, false) == Waits::kStrike && waits_verdict(500.1, true) == Waits::kStart);
    // the PC where loads at create do not work: 2.5-4.7 s of waits, the marker at once
    CHECK(waits_verdict(2556.6, false) == Waits::kStart && waits_verdict(4733, false) == Waits::kStart);
    CHECK(waits_verdict(2000, false) == Waits::kStrike && waits_verdict(2000.1, false) == Waits::kStart);
    {   // the strike: written, found once by the next start and taken away
        const std::string marker = std::string(argv[1]) + "/triforce_load_start.txt";
        CHECK(!load_default::strike_take(marker));
        CHECK(load_default::strike_write(marker, 612) && load_default::marker_there(load_default::strike_path(marker)));
        CHECK(load_default::strike_take(marker) && !load_default::strike_take(marker));
    }
    // its second part: listed pipelines in no cache, 0 where the caches held the preparation's work, thousands where they did not
    CHECK(!load_default::caches_lacked(0) && !load_default::caches_lacked(39) && !load_default::caches_lacked(500));
    CHECK(load_default::caches_lacked(501) && load_default::caches_lacked(4189));
    // the marker: not there, written, there; its text says how to take it away
    const std::string path = std::string(argv[1]) + "/triforce_load_start.txt";
    CHECK(!load_default::marker_there(path));
    CHECK(load_default::marker_write(path, 884.4, 2556.6) && load_default::marker_there(path));
    char text[400]{};
    FILE* f = std::fopen(path.c_str(), "rb");
    CHECK(f && std::fread(text, 1, sizeof text - 1, f) > 0);
    std::fclose(f);
    CHECK(std::strstr(text, "2557 ms") && std::strstr(text, "884 ms") && std::strstr(text, "Delete this file"));
    using load_default::Marker;
    CHECK(load_default::marker_kind(path) == Marker::kWaits);
    CHECK(load_default::marker_write_lacked(path, 4189) && load_default::marker_there(path));
    CHECK(load_default::marker_kind(path) == Marker::kLacked);
    // the lacked marker is not followed on a PC of 20 GB or less (start would not fit there); the waits' one is, on any RAM
    CHECK(!load_default::marker_counts(Marker::kLacked, 16384) && !load_default::marker_counts(Marker::kLacked, 20480));
    CHECK(load_default::marker_counts(Marker::kLacked, 20481) && load_default::marker_counts(Marker::kLacked, 0));
    CHECK(load_default::marker_counts(Marker::kWaits, 16384) && !load_default::marker_counts(Marker::kNone, 65536));
    {   // (a marker written by hand: the waits')
        FILE* h = std::fopen(path.c_str(), "wb");
        CHECK(h && std::fputs("x\n", h) >= 0 && std::fclose(h) == 0);
        CHECK(load_default::marker_kind(path) == Marker::kWaits);
    }
    CHECK(load_default::marker_kind(std::string(argv[1]) + "/none.txt") == Marker::kNone);
    CHECK(!load_default::marker_write(std::string(argv[1]) + "/no-such-folder/x.txt", 1, 1));
    CHECK(std::remove(path.c_str()) == 0 && !load_default::marker_there(path));
    std::printf("load_default: ok\n");
    return 0;
}
