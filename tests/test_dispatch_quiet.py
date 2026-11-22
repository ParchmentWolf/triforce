"""The leftover per-dispatch diagnostics quieted (gpu/vk/vk_draw.cpp dispatch, taau_key; vk_texture.cpp texture_frame;
no game, no GPU).

(Triforce, 11-22, the performance audit's DESC-30, after Source A's and Source B's.) Every compute dispatch still paid for
diagnostics nobody had asked for: RX_VK_LOG_PUSH's key written out as text, taau_key's key written out and its list
walked as text (several times a dispatch), two clock reads and a sequentially consistent add around the program pick, and
a clock read for the first-pipeline timer when there was nothing to time. Every 600 presents texture_frame filled a list
only RX_VK_LOG_BAKED reads and sorted every texture to print eight.

Cuts taau_key out of vk_draw.cpp and runs it both ways, the parsed prefixes and the text compare it was (kept for the
lab's "diagold" phases), over 16 lists and some 300,000 keys each: the same answer for every key, and the answers a
list must give (a prefix, a whole key, several entries, an entry that begins with '-', upper case, 17 digits, an empty
list, empty entries: none of those last ones ever match).

Reads the source:
  - taau_key: no snprintf before the parsed prefixes answer; the list's expression as it was (its reads of the
    environment are counted by tests/test_taau_env_lookup.py);
  - dispatch: no clock around program_for outside prof_full and the lab's knob, the pick's time taken from prof_t.exact
    with a relaxed add; RX_VK_LOG_PUSH's key formatted only under its switch (or the knob); PipeClock's clock read only
    when it times something (or the knob);
  - program_pick, the picks' slow path, is still under PROF_EXACT: what the pick's time now stands on;
  - texture_frame: RX_VK_LOG_BAKED read once, its list filled only for it, no whole sort outside the knob; the VRAM and
    textures lines keep their text.

    python -I -B tests/test_dispatch_quiet.py [--cxx clang++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

FIXTURE = r'''
#define _CRT_SECURE_NO_WARNINGS
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
static const char *configured_keys, *no_f16;
static const char* fixture_getenv(const char* name) {
    if (!strcmp(name, "RX_VK_TAAU_KEYS")) return configured_keys;
    if (!strcmp(name, "RX_VK_NO_F16")) return no_f16;
    return nullptr;
}
#define getenv fixture_getenv
namespace Shader { namespace Backend { namespace SPIRV { static bool mma_software = true; } } }
static bool diag_old_now;
static bool dispatch_diag_old() { return diag_old_now; }
/* CUT */

int main(int argc, char** argv) {
    // (argv[1]: the list, "(unset)" for none set; argv[2]: "hardware" for a card that runs the network itself)
    if (argc > 1 && strcmp(argv[1], "(unset)")) configured_keys = argv[1];
    if (argc > 2 && !strcmp(argv[2], "hardware")) Shader::Backend::SPIRV::mma_software = false;
    std::vector<uint64_t> keys = {0xfd029a317a9a4b94ull, 0x9dc98871eb7fc101ull, 0, ~0ull, 0xfd029a317a9a4b95ull, 0xfd029a317a9a4b84ull,
                                  0x0d029a317a9a4b94ull, 0xfd02000000000000ull, 0xfd01ffffffffffffull, 0x00000000000000fdull,
                                  0xabcdef0123456789ull, 0x0123456789abcdefull, 0xa000000000000000ull, 0x0a00000000000000ull};
    uint64_t x = 0x9E3779B97F4A7C15ull;
    for (int i = 0; i < 300000; i++) {
        x ^= x << 13, x ^= x >> 7, x ^= x << 17;
        keys.push_back(x);
        if (i % 3 == 0) keys.push_back((x & 0x0000ffffffffffffull) | 0xfd02000000000000ull);   // (many under the usual prefix)
        if (i % 7 == 0) keys.push_back(x >> (i % 61));                                           // (leading zeros)
    }
    size_t matched = 0, differ = 0;
    for (uint64_t k : keys) {
        diag_old_now = false;
        const bool now = taau_key(k);
        diag_old_now = true;
        const bool was = taau_key(k);
        matched += now, differ += now != was;
        if (now != was && differ <= 4) printf("DIFFERS %016llx: parsed %d, text %d\n", (unsigned long long)k, (int)now, (int)was);
    }
    diag_old_now = false;
    printf("%zu %zu %zu %d %d %d\n", keys.size(), matched, differ, (int)taau_key(0xfd029a317a9a4b94ull), (int)taau_key(0x9dc98871eb7fc101ull),
           (int)taau_key(0));
    return differ != 0;
}
'''

# the list, the card, and the answers for fd029a317a9a4b94, 9dc98871eb7fc101 and 0
LISTS = [("(unset)", "software", (1, 0, 0)), ("(unset)", "hardware", (0, 0, 0)), ("-", "software", (0, 0, 0)), ("", "software", (0, 0, 0)),
         ("fd029a317a9a4b94", "hardware", (1, 0, 0)), ("fd02", "software", (1, 0, 0)), ("f", "software", (1, 0, 0)),
         ("fd029a317a9a4b94,9dc98871eb7fc101", "software", (1, 1, 0)), ("9dc9,-fd02", "software", (0, 1, 0)),
         ("FD029A317A9A4B94", "software", (0, 0, 0)), ("fd029a317a9a4b940", "software", (0, 0, 0)), (",,fd,,0000,", "software", (1, 0, 1)),
         ("0", "software", (0, 0, 1)), ("g,fd0x,9d c9, fd", "software", (0, 0, 0)), ("0000000000000000", "software", (0, 0, 1)),
         ("-,fd029a317a9a4b9", "software", (1, 0, 0))]


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def ordered(text, parts, why):
    last = 0
    for p in parts:
        k = text.find(p, last)
        need(k >= 0, why + " (missing, or out of order: " + p + ")")
        last = k + len(p)


def check_source(draw):
    key = block(draw, "bool taau_key(uint64_t key) {")
    ordered(key, ['static const char* keys = getenv("RX_VK_TAAU_KEYS") ? getenv("RX_VK_TAAU_KEYS")',
                  "static const std::vector<Prefix> prefixes = [] {", "if (!dispatch_diag_old()) {",
                  "if ((key & p.mask) == p.value) return true;", "return false;", "snprintf(hex, sizeof hex,"],
            "taau_key does not answer from its list parsed once before any text is made")
    need(key.count("snprintf(") == 1 and key.count("getenv(") == 3, "taau_key formats or reads the environment in another place")
    need('return lab_ab::on("diagold");' in block(draw, "bool dispatch_diag_old() {"), "the lab's knob is not diagold")
    disp = block(draw, "void dispatch(VkCommandBuffer cmd, NvnState& s, uint32_t x, uint32_t y, uint32_t z, uint64_t indirect) {")
    ordered(disp, ["const bool pick_clocked = prof_full.load(std::memory_order_relaxed) != 0 || dispatch_diag_old();",
                   "const auto t_pick = pick_clocked ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};",
                   "const int64_t x_pick = prof_t.exact;", "const Program* cp = program_for(s, ProgramKind::Compute, types);",
                   "if (pick_clocked)", "st_disp_pick_ns +=", "else if (const int64_t dx = prof_t.exact - x_pick)",
                   "st_disp_pick_ns.fetch_add(dx, std::memory_order_relaxed);"],
            "dispatch still reads a clock around every program pick, or lost the pick's time")
    pick = disp[disp.index("const uint8_t types[8]{};"):disp.index("dclock.t_prog =")]
    need(pick.count("steady_clock::now()") == 2 and "pick_clocked ?" in pick and pick.index("if (pick_clocked)") < pick.rindex("steady_clock::now()"),
         "dispatch reads the clock around the pick outside prof_full")
    at = disp.index('static const char* want = getenv("RX_VK_LOG_PUSH");')
    push = disp[at:disp.index("Program& p = const_cast<Program&>(*cp);", at)]
    ordered(push, ["if ((want && !done) || dispatch_diag_old()) {", "snprintf(hex, sizeof hex,",
                   "if (want && !done && !strncmp(hex, want, strlen(want))) {", "done = true;"],
            "dispatch formats RX_VK_LOG_PUSH's key without its switch")
    ordered(disp, ["struct PipeClock {", "const bool pipe_timed = !p.compute_pipeline || !p.layout;",
                   "PipeClock pipe_clock{pipe_timed || dispatch_diag_old() ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{},",
                   "pipe_timed};", "ensure_layout(p);", "pipe_clock.stop();"],
            "dispatch reads PipeClock's clock when it times nothing")
    need("} pipe_clock{std::chrono::steady_clock::now()," not in disp, "PipeClock is made with a clock read at every dispatch")
    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    slow = block(shader, "const Program* program_pick(const NvnState& s, ProgramKind kind, const uint8_t color_types[8]) {")
    need(slow.split("\n")[1].strip().startswith("PROF_EXACT();"), "program_pick is no longer timed by PROF_EXACT: the pick's time stood on it")
    internal = (ROOT / "gpu/vk/vk_internal.h").read_text(encoding="utf-8")
    need("prof_t.exact = x0 + dt;" in internal and "inline thread_local ProfThread prof_t;" in internal,
         "PROF_EXACT no longer adds its time to the thread's prof_t.exact")
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    frame = block(tex, "void texture_frame(uint64_t completed) {")
    need(frame.count('getenv("RX_VK_LOG_BAKED")') == 1 and 'static const bool log_baked = getenv("RX_VK_LOG_BAKED") != nullptr;' in frame,
         "texture_frame does not read RX_VK_LOG_BAKED once")
    need("if (log_baked || diag_old) baked.push_back(t);" in frame and "if (log_baked) {" in frame and frame.count("baked.push_back(") == 1,
         "texture_frame fills the list of RX_VK_LOG_BAKED without the switch")
    need(frame.count("std::sort(") == 1 and "if (diag_old) std::sort(list.begin(), list.end(), larger);" in frame and
         "else std::partial_sort(list.begin(), list.begin() + (ptrdiff_t)std::min(n, list.size()), list.end(), larger);" in frame and
         "largest(big, 8);" in frame and "largest(baked, 10);" in frame and 'const bool diag_old = lab_ab::on("diagold");' in frame,
         "texture_frame sorts a whole list outside the lab's knob")
    for line in ('logf("vk: VRAM: %llu MB used of %llu MB allowed (%llu MB of it free in the blocks); textures %llu MB (budget %llu "',
                 'logf("vk: textures: decoded ASTC %llu MB, rendered %llu MB (%zu drawn in one frame, kept: %llu KB), other %llu MB; "',
                 "for (size_t i = 0; i < big.size() && i < 8; i++)", "for (size_t i = 0; i < baked.size() && i < 10; i++) {"):
        need(line in frame, "texture_frame's lines changed: " + line)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    check_source(draw)
    with tempfile.TemporaryDirectory(prefix="dispatch-quiet-") as tmp:
        cpp, exe = Path(tmp) / "taau_key.cpp", Path(tmp) / "taau-key.exe"
        cpp.write_text(FIXTURE.replace("/* CUT */", block(draw, "bool taau_key(uint64_t key) {")), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        for keys, card, want in LISTS:
            r = subprocess.run([str(exe), keys, card], capture_output=True, text=True, timeout=120)
            row = r.stdout.strip().splitlines()[-1].split() if r.stdout.strip() else []
            need(r.returncode == 0 and len(row) == 6, "RX_VK_TAAU_KEYS=%r (%s): the parsed list and the text compare differ:\n%s" % (keys, card, r.stdout))
            need(tuple(int(v) for v in row[3:]) == want, "RX_VK_TAAU_KEYS=%r (%s): answers %s, want %s" % (keys, card, row[3:], want))
            need((int(row[1]) > 0) == (1 in want) or keys in (",,fd,,0000,",), "RX_VK_TAAU_KEYS=%r: %s keys matched" % (keys, row[1]))
            print("RX_VK_TAAU_KEYS=%-36r %s: %s keys, %s match, both ways alike" % (keys, card, row[0], row[1]))
    print("PASS: a dispatch's leftover diagnostics are quiet, and taau_key answers as its text compare did")


if __name__ == "__main__":
    main()
