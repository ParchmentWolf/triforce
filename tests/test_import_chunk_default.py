"""An import's chunk is 4 MB where the mirrors are whole on an NVIDIA card, 16 MB everywhere else (vk_memory.cpp
small_chunks_wanted and import_chunk; no game, no GPU).

(Triforce, 11-22, the performance audit's MEM-16, after Source A's.) An import covers whole 16 MB chunks of the game's
address space, and a whole mirror copies all of it into video memory, the padding too. Source A made the chunk 4 MB
wherever mirrors are on: about a quarter less mirror memory for about half again as many imports. Triforce's mirrors
in pieces bind memory only where bindings reach, so the gain is left where the mirrors are whole, and it is taken only
on NVIDIA's cards: an import stalled the replay 20 to 75 ms on an AMD card, so AMD and Intel keep 16 MB.

This cuts the two functions out of vk_memory.cpp and runs them over stand-ins for mirror_on, mirror_pieces_on and the
device, a process a case (the chunk is read once):
  - NVIDIA, mirrors on and whole: 4 MB; with the mirrors in pieces, or without mirrors: 16 MB;
  - AMD and Intel with whole mirrors: 16 MB, and the mirrors' switches are not even asked there;
  - RX_VK_IMPORT_CHUNK_MB=8, =16, =0 win on any card, and nothing is asked of the mirrors then;
  - the chunk is logged once.
And reads the source: mirror_pieces_on is declared above the rule, the card's maker is asked first, the switch is in
the switches table, and tests/test_import_windows.py's fixture has the stand-in and runs a 4 MB chunk.

    python -I -B tests/test_import_chunk_default.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

FIXTURE = r'''
#include <algorithm>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static bool mirrors, pieces;
static int asked_mirrors, asked_pieces, logs;
static char last_log[512];
static struct { struct { uint32_t vendorID = 0; } props; } dev;
static bool mirror_on() { asked_mirrors++; return mirrors; }
static bool mirror_pieces_on();
static void logf(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(last_log, sizeof last_log, fmt, ap);
    va_end(ap);
    logs++;
}

/* RULE */
/* CHUNK */

static bool mirror_pieces_on() { asked_pieces++; return pieces; }

int main(int argc, char** argv) {
    if (argc < 4) return 2;
    dev.props.vendorID = (uint32_t)std::strtoul(argv[1], nullptr, 16);
    mirrors = argv[2][0] == '1', pieces = argv[3][0] == '1';
    const uint64_t a = import_chunk(), b = import_chunk(), c = import_chunk();
    if (a != b || b != c) return 3;
    std::printf("%llu MB, %d line(s), mirrors asked %d, pieces asked %d\n%s\n", (unsigned long long)(a >> 20), logs, asked_mirrors,
                asked_pieces, last_log);
    return 0;
}
'''


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    check("bool small_chunks_wanted() {" in mem, "vk_memory.cpp has no small_chunks_wanted()")
    rule = block(mem, "bool small_chunks_wanted() {")
    chunk = block(mem, "uint64_t import_chunk() {")
    check("return dev.props.vendorID == 0x10de && mirror_on() && !mirror_pieces_on();" in rule,
          "small_chunks_wanted is not: an NVIDIA card (asked first), mirrors on, and whole")
    at = [mem.index(s) for s in ("bool mirror_pieces_on();   // (below", "bool small_chunks_wanted() {", "uint64_t import_chunk() {",
                                 "Pool* pool_lookup(uint64_t guest, uint64_t size) {", "bool mirror_pieces_on() {\n    static const bool on = [] {")]
    check(at == sorted(at), "vk_memory.cpp: mirror_pieces_on is not declared above the rule, or the rule is not above import_chunk")
    check('const char* e = getenv("RX_VK_IMPORT_CHUNK_MB");' in chunk and "const bool small = !e && small_chunks_wanted();" in chunk and
          "const uint64_t mb = e ? (uint64_t)std::max(0, atoi(e)) : small ? 4 : 16;" in chunk and "static const uint64_t chunk = [] {" in chunk,
          "import_chunk does not take RX_VK_IMPORT_CHUNK_MB first, then 4 MB where small chunks are wanted, else 16, once")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `RX_VK_IMPORT_CHUNK_MB=<MB>` |" in docs, "docs/development.md: RX_VK_IMPORT_CHUNK_MB is not in the switches table")
    windows = (ROOT / "tests" / "test_import_windows.py").read_text(encoding="utf-8")
    check("bool small_chunks_wanted()" in windows and "for chunk in ('16','4','3','0'):" in windows,
          "tests/test_import_windows.py: the fixture lacks the rule's stand-in, or does not run a 4 MB chunk")

    env0 = {k: v for k, v in os.environ.items() if k != "RX_VK_IMPORT_CHUNK_MB"}
    with tempfile.TemporaryDirectory(prefix="import-chunk-") as tmp:
        cpp, exe = Path(tmp) / "chunk.cpp", Path(tmp) / "chunk.exe"
        cpp.write_text(FIXTURE.replace("/* RULE */", rule).replace("/* CHUNK */", chunk), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)

        def run(vendor, mirrors, pieces, env=None):
            e = dict(env0)
            if env is not None:
                e["RX_VK_IMPORT_CHUNK_MB"] = env
            r = subprocess.run([str(exe), vendor, "1" if mirrors else "0", "1" if pieces else "0"], capture_output=True, text=True, env=e)
            check(r.returncode == 0, "the cut-out functions did not run (%s)" % r.returncode)
            first, line = r.stdout.splitlines()[:2]
            return first, line

        nv, amd, intel = "10de", "1002", "8086"
        for vendor, mirrors, pieces, env, mb, asked, what in (
                (nv, True, False, None, 4, "mirrors asked 1, pieces asked 1", "an NVIDIA card with whole mirrors"),
                (nv, True, True, None, 16, "mirrors asked 1, pieces asked 1", "an NVIDIA card with the mirrors in pieces"),
                (nv, False, False, None, 16, "mirrors asked 1, pieces asked 0", "an NVIDIA card without mirrors"),
                (nv, False, True, None, 16, "mirrors asked 1, pieces asked 0", "an NVIDIA card without mirrors"),
                (amd, True, False, None, 16, "mirrors asked 0, pieces asked 0", "an AMD card with whole mirrors"),
                (intel, True, False, None, 16, "mirrors asked 0, pieces asked 0", "an Intel card with whole mirrors"),
                ("0", True, False, None, 16, "mirrors asked 0, pieces asked 0", "a card of no known maker"),
                (nv, True, False, "8", 8, "mirrors asked 0, pieces asked 0", "RX_VK_IMPORT_CHUNK_MB=8 on an NVIDIA card with whole mirrors"),
                (nv, True, False, "16", 16, "mirrors asked 0, pieces asked 0", "RX_VK_IMPORT_CHUNK_MB=16 on an NVIDIA card with whole mirrors"),
                (nv, True, False, "0", 0, "mirrors asked 0, pieces asked 0", "RX_VK_IMPORT_CHUNK_MB=0"),
                (nv, True, True, "-5", 0, "mirrors asked 0, pieces asked 0", "RX_VK_IMPORT_CHUNK_MB=-5"),
                (amd, True, False, "4", 4, "mirrors asked 0, pieces asked 0", "RX_VK_IMPORT_CHUNK_MB=4 on an AMD card")):
            first, line = run(vendor, mirrors, pieces, env)
            check(first == "%d MB, 1 line(s), %s" % (mb, asked), "%s: %s, want %d MB said once and %s" % (what, first, mb, asked))
            check(line.startswith("vk: imports in chunks of %d MB" % mb), "%s: the log does not say the chunk: %s" % (what, line))
    print("PASS: 4 MB import chunks where the mirrors are whole on an NVIDIA card, 16 MB elsewhere; the switch wins")


if __name__ == "__main__":
    main()
