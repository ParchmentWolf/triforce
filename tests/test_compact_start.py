"""The free space a VRAM compaction run starts from, by the card (gpu/vk/vram_compact.h default_min_free; the performance
audit's TEX-38, after Source A's; no game, no GPU).

The rule, compiled and run: a sixteenth of what the driver allows, 64 MB at least and 512 at most, 512 while nothing is
known; for cards from 2 to 32 GB as drivers report them (a little under the card's size) it is 512 from 8 GB up, exactly as
before, and less only under that; 192 MB still while the count is pressed. Each part taken out (a mutation) fails it. Then
the source: compact_step takes RX_VK_COMPACT_MB first and the rule otherwise, with the allowance of texture_frame's last
look; and the docs row.

    python -I -B tests/test_compact_start.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(text, parts, where):
    at = 0
    for part in parts:
        found = text.find(part, at)
        if found < 0:
            raise SystemExit("%s: %r is missing, or not after the part before it (update the test with the code)" % (where, part))
        at = found + len(part)


RULE_TEST = r'''
#include <cstdio>
#include <cstdlib>
#include "vram_compact.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace vram_compact;
int main() {
    const uint64_t MB = 1ull << 20, GB = 1ull << 30;
    // (the entry's four: not known, 512 MB, a 6 GB laptop's 5,233 MB, 16 GB)
    CHECK(default_min_free(0) == 512 * MB);
    CHECK(default_min_free(512 * MB) == 64 * MB);
    CHECK(default_min_free(5233 * MB) >> 20 == 327);
    CHECK(default_min_free(16 * GB) == 512 * MB);
    // (cards from 2 to 32 GB, the allowance a driver gives a little under the card: 512 from 8 GB up, as before)
    const struct { uint64_t card_gb, allowed_mb, want_mb; } cards[] = {
        {2, 1843, 115}, {3, 2867, 179}, {4, 3686, 230}, {6, 5233, 327}, {6, 5734, 358}, {8, 7300, 456},
        {8, 7782, 486}, {10, 9420, 512}, {11, 10900, 512}, {12, 11468, 512}, {16, 15564, 512}, {20, 19456, 512},
        {24, 23552, 512}, {32, 31784, 512}, {32, 32607, 512},
    };
    for (const auto& c : cards) {
        const uint64_t v = default_min_free(c.allowed_mb * MB);
        if ((v >> 20) != c.want_mb) {
            std::fprintf(stderr, "FAIL: a %llu GB card allowing %llu MB: %llu MB, want %llu\n", (unsigned long long)c.card_gb,
                         (unsigned long long)c.allowed_mb, (unsigned long long)(v >> 20), (unsigned long long)c.want_mb);
            return 1;
        }
        CHECK(v >= 64 * MB && v <= 512 * MB);
        if (c.allowed_mb >= 8192) CHECK(v == 512 * MB);   // (this PC's 32 GB card and every card from 8 GB: today's 512)
        CHECK(run_from(v, true) == (v < 192 * MB ? v : 192 * MB) && run_from(v, false) == v);
    }
    // (the bounds)
    CHECK(default_min_free(1) == 64 * MB && default_min_free(1024 * MB) == 64 * MB && default_min_free(1040 * MB) == 65 * MB);
    CHECK(default_min_free(8 * GB) == 512 * MB && default_min_free(8 * GB - 16 * MB) == 511 * MB && default_min_free(~0ull) == 512 * MB);
    std::puts("PASS rule: a sixteenth of the allowance, 64 to 512 MB, 512 unknown; 512 on every card from 8 GB");
    return 0;
}
'''

MUTATIONS = [
    ("512 while not known", "    if (!allowed) return 512ull << 20;\n", ""),
    ("a sixteenth", "return std::clamp<uint64_t>(allowed / 16, 64ull << 20, 512ull << 20);",
     "return std::clamp<uint64_t>(allowed / 8, 64ull << 20, 512ull << 20);"),
    ("64 MB at least", "return std::clamp<uint64_t>(allowed / 16, 64ull << 20, 512ull << 20);",
     "return std::clamp<uint64_t>(allowed / 16, 1, 512ull << 20);"),
    ("512 MB at most", "return std::clamp<uint64_t>(allowed / 16, 64ull << 20, 512ull << 20);",
     "return std::clamp<uint64_t>(allowed / 16, 64ull << 20, 4096ull << 20);"),
]


def check_source(tex, dev):
    step = block(tex, "void compact_step(uint64_t completed) {")
    in_order(step, ['static const uint64_t asked = (uint64_t)(getenv("RX_VK_COMPACT_MB") ? std::max(1, atoi(getenv("RX_VK_COMPACT_MB"))) : 0) << 20;',
                    "const uint64_t min_free = asked ? asked : vram_compact::default_min_free(compact.allowed);",
                    "free_bytes < vram_compact::run_from(min_free, compact.pressed))"], "vk_texture.cpp compact_step")
    in_order(tex, ["const bool known = vram_usage(&used, &allowed, &block_free);",
                   "compact.pressed = known && vram_compact::pressed(used, allowed);", "compact.allowed = known ? allowed : 0;"],
             "vk_texture.cpp texture_frame: the allowance of the last look")
    if "uint64_t allowed = 0;" not in block(tex, "struct Compact {"):
        raise SystemExit("vk_texture.cpp: struct Compact has no allowance")
    if "default_min_free" not in dev or "RX_VK_COMPACT_MB=512" not in dev:
        raise SystemExit("docs/development.md: the compaction's row does not say the start by the card, nor the switch back")


def build(cxx, d, name, src, include):
    cpp, exe = d / (name + ".cpp"), d / (name + ".exe")
    cpp.write_text(src, encoding="utf-8")
    r = subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(include), str(cpp), "-o", str(exe)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode:
        return None, r.stdout
    return exe, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    a = ap.parse_args()
    check_source((VK / "vk_texture.cpp").read_text(encoding="utf-8"), (ROOT / "docs" / "development.md").read_text(encoding="utf-8"))
    print("PASS sources: compact_step takes RX_VK_COMPACT_MB first, the rule with the last look's allowance otherwise; the row")
    header = (VK / "vram_compact.h").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="compact-start-") as tmp:
        d = Path(tmp)
        exe, out = build(a.cxx, d, "rule", RULE_TEST, VK)
        if not exe:
            raise SystemExit("rule: the build failed:\n" + out)
        r = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        if r.returncode:
            raise SystemExit("the rule's test failed:\n" + r.stdout)
        print(r.stdout.strip())
        for i, (what, old, new) in enumerate(MUTATIONS):
            if header.count(old) != 1:
                raise SystemExit("mutation %r: its text is not once in vram_compact.h (update the test with the header)" % what)
            inc = d / ("mutant%d" % i)
            inc.mkdir()
            (inc / "vram_compact.h").write_text(header.replace(old, new), encoding="utf-8")
            exe, out = build(a.cxx, d, "mutant%d" % i, RULE_TEST, inc)
            if exe:
                r = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
                if r.returncode == 0:
                    raise SystemExit("mutation %r: the rule's test still passed without it" % what)
        print("PASS mutations: %d parts of the rule, each taken out, fail its test" % len(MUTATIONS))


if __name__ == "__main__":
    main()
