"""The shaders prepared again when the program cache was made again for another GPU, and the mark of the driver's part
without stage libraries by what it was made for (gpu/vk/prepare_again.h; vk_draw.cpp prepare_run; no game, no GPU).

After Casual Gamer's #dev-fixes post. triforce_prepared.bin said the shaders were translated for this stamp while the
program cache had been made again since for another one (a start on another GPU or with other settings that did not
prepare): prepare_check said nothing to do and every program was translated in play. And the empty mark of a start that
died in the driver's part without stage libraries left that part out for good, on any GPU and driver after it.

The header is compiled and run as it is, on files in a temporary folder:
- a program cache holds none of the shaders when there is none, when it is shorter than its head or is its head alone,
  when its head is no program cache's, or names another stamp; one of this stamp with records holds them, and so does one
  carried over an update (another build's word, the same stamp);
- the mark: none; an empty one (an older build's) is this driver's; one of this stamp is, one of another is not, unless
  RX_VK_PREPARE_RECHECK=0 (any mark is then, as before); written with the stamp, or empty with the switch off.
Then the source: prepare_run asks the program cache only where the record says nothing to do, before the game (not in the
background) and with the program cache on, removes the record before it prepares again, and reads and writes the mark through
the header in the branch without libraries; the switch is in docs/development.md.

    python -I -B tests/test_prepare_again.py --cxx clang++
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <cstdio>
#include <string>
#include "prepare_again.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace prepare_again;
static std::string dir;
static void put(const std::string& name, const void* b, size_t n) {
    FILE* f = std::fopen((dir + name).c_str(), "wb");
    if (n) std::fwrite(b, 1, n, f);
    std::fclose(f);
}
static void programs(const std::string& name, uint32_t magic, uint32_t writer, uint64_t stamp, size_t records) {
    std::string b(16 + records, 'r');
    std::memcpy(&b[0], &magic, 4), std::memcpy(&b[4], &writer, 4), std::memcpy(&b[8], &stamp, 8);
    put(name, b.data(), b.size());
}
int main(int argc, char** argv) {
    if (argc < 2) return 2;
    dir = std::string(argv[1]) + "/";
    const uint64_t A = 0x1234567890ABCDEFull, B = 0x0FEDCBA987654321ull;
    uint64_t size = 1;
    CHECK(on(nullptr) && on("1") && on("") && !on("0") && on("00"));
    CHECK(programs_none_at(dir + "missing.bin", A, &size) && size == 0);
    programs("kept.bin", kProgramsMagic, 7, A, 4096);
    CHECK(!programs_none_at(dir + "kept.bin", A, &size) && size == 16 + 4096);
    programs("carried.bin", kProgramsMagic, 8, A, 20);   // (another build's word, the same stamp: carried over an update)
    CHECK(!programs_none_at(dir + "carried.bin", A));
    CHECK(programs_none_at(dir + "kept.bin", B));         // (made again for another stamp)
    programs("head.bin", kProgramsMagic, 7, A, 0);        // (its head alone: made again, nothing in it yet)
    CHECK(programs_none_at(dir + "head.bin", A, &size) && size == 16);
    programs("magic.bin", 0x12345678, 7, A, 4096);
    CHECK(programs_none_at(dir + "magic.bin", A));
    put("short.bin", "HSP1", 4);
    CHECK(programs_none_at(dir + "short.bin", A));
    {   // (the head's bytes alone)
        uint8_t h[16]{};
        const uint32_t m = kProgramsMagic;
        std::memcpy(h, &m, 4), std::memcpy(h + 8, &A, 8);
        CHECK(!programs_none(h, 16, 17, A) && programs_none(h, 16, 16, A) && programs_none(h, 15, 4096, A) && programs_none(h, 16, 4096, B));
    }
    const std::string mark = dir + "triforce_prepared.bin.warming";
    CHECK(mark_left(mark, A, true) == Mark::None && mark_left(mark, A, false) == Mark::None);
    put("triforce_prepared.bin.warming", "", 0);   // (an older build's empty mark: this driver's, as before)
    CHECK(mark_left(mark, A, true) == Mark::Ours && mark_left(mark, A, false) == Mark::Ours);
    CHECK(mark_write(mark, A, true));
    CHECK(mark_left(mark, A, true) == Mark::Ours && mark_left(mark, B, true) == Mark::Other && mark_left(mark, B, false) == Mark::Ours);
    CHECK(mark_write(mark, B, false));   // (the switch off: empty, as before)
    CHECK(mark_left(mark, A, true) == Mark::Ours);
    {
        FILE* f = std::fopen(mark.c_str(), "rb");
        std::fseek(f, 0, SEEK_END);
        const long n = std::ftell(f);
        std::fclose(f);
        CHECK(n == 0);
    }
    std::printf("prepare_again.h: ok\n");
    return 0;
}
"""


def between(text, start, end):
    a = text.index(start)
    return text[a:text.index(end, a)]


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    run = between(draw, "bool prepare_run(void (*progress)(size_t done, size_t total), bool background) {", "\n}\n")
    ask = "if (why == PrepareWhy::None && !background && recheck && !getenv(\"RX_VK_NO_PROGRAM_CACHE\")) {"
    if ask not in run or run.index(ask) > run.index("if (why == PrepareWhy::None && !getenv(\"RX_VK_PREPARE_AGAIN\")) {"):
        raise SystemExit("prepare_run does not ask the program cache before it takes the record's word that nothing is to do")
    again = between(run, ask, "\n    }\n")
    if "prepare_again::programs_none_at(programs, program_cache_stamp(), &size)" not in again or \
            "triforce_programs.bin" not in again or "why = PrepareWhy::First;" not in again or \
            again.index("remove(path.c_str());") > again.index("why = PrepareWhy::First;"):
        raise SystemExit("prepare_run does not prepare again, with the stale record removed first, for a program cache of none "
                         "of these shaders")
    if 'prepare_again::on(getenv("RX_VK_PREPARE_RECHECK"))' not in run:
        raise SystemExit("RX_VK_PREPARE_RECHECK is not read")
    if "prepare_again::mark_left(warming, warmed, recheck)" not in run or \
            "prepare_again::mark_write(warming, warmed, recheck)" not in run or 'fopen(warming.c_str(), "wb")' in run:
        raise SystemExit("the mark of the driver's part without libraries is not read and written by what it is made for")
    dev_md = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "`RX_VK_PREPARE_RECHECK=0`" not in dev_md:
        raise SystemExit("RX_VK_PREPARE_RECHECK is not in docs/development.md's switches")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="prepare-again-") as tmp:
        tmp = Path(tmp)
        (tmp / "t.cpp").write_text(FIXTURE, encoding="utf-8")
        exe = tmp / "prepare-again.exe"
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"),
                        str(tmp / "t.cpp"), "-o", str(exe)], check=True)
        files = tmp / "files"
        files.mkdir()
        r = subprocess.run([str(exe), str(files)], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise SystemExit("prepare_again.h: " + (r.stdout.strip() or str(r.returncode)))
    print("PASS: a program cache of none of the prepared shaders prepares them again, and the mark of the driver's part "
          "without libraries is this driver's only by its stamp")


if __name__ == "__main__":
    main()
