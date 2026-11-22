// tests/test_warm_computes.py: gpu/vk/warm_computes.h's rule, no game or GPU
#include "../gpu/vk/warm_computes.h"

#include <cstdio>
#include <cstdlib>

static int failures = 0;
static void check(bool ok, const char* what) {
    if (!ok) std::printf("FAIL: %s\n", what), failures++;
}

int main() {
    using namespace warm_computes;
    // (unset: listed on Intel, every one on the others)
    check(listed_only(nullptr, 0x8086), "Intel, unset: listed");
    check(!listed_only(nullptr, 0x10DE), "NVIDIA, unset: all");
    check(!listed_only(nullptr, 0x1002), "AMD, unset: all");
    // (the switch decides on any GPU; anything else is as unset)
    check(listed_only("listed", 0x10DE), "NVIDIA, listed");
    check(listed_only("listed", 0x1002), "AMD, listed");
    check(!listed_only("all", 0x8086), "Intel, all");
    check(listed_only("", 0x8086) && !listed_only("", 0x10DE), "empty: as unset");
    check(listed_only("1", 0x8086) && !listed_only("1", 0x1002), "other text: as unset");
    // (built: without listed_only every one; with it the listed ones, and every one while there is no list)
    check(build(false, false, false) && build(false, true, false) && build(false, false, true), "all: every one");
    check(build(true, true, false), "listed, no list yet: every one");
    check(build(true, false, true), "listed: a listed program");
    check(!build(true, false, false), "listed: a program play has not dispatched is left");
    if (failures) return 1;
    std::printf("warm_computes: all checks passed\n");
    return 0;
}
