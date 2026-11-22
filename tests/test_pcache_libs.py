"""A pipeline cache file of stage libraries and compute pipelines alone, on NVIDIA PCs of little RAM (gpu/vk/pcache_libs.h;
vk_draw.cpp pcache_libs_decide, pcache_init, build_graphics, pcache_play_open; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-78, after Source A's and Source B's.) The whole pipeline cache file is read
and held all session on every PC. With RX_VK_PCACHE_LIBS_ONLY=1 (off by default), a fresh file on NVIDIA's own driver with
20 GB of RAM or less and 512 MB or more in the driver's own cache keeps the stage libraries (which a draw's link must find in
the cache it hands over) and the compute pipelines alone, whole graphics pipelines going to the driver's cache, and opens no
play file; recorded in <file>.lean for that file's life. 2 forces it at a fresh file.

The header is compiled and run:
- the switch (off unless set), and the rule over many made-up PCs: NVIDIA's own driver at 8, 16 and 20 GB with a 512 MB+
  cache lean; 24 and 32 GB (this PC), a small cache, no stage libraries, AMD's, Intel's, Mesa's, NVK, a start that only
  prepares: full; 2 lean anywhere but a prepare-only start; 0 never;
- the driver's cache folder on Windows and Linux (its variable, XDG, HOME), and its size walked on a temporary tree;
- the record: written, read for its stamp only; and a start's verdict: fresh by the rule, a file read by its record, off
  with the switch at 0 whatever was recorded.
And reads the source: pcache_init decides once the file read (or not) is known, through pcache_libs_decide, which records
or removes <file>.lean only at a fresh file and decides nothing in a start that only prepares; build_graphics leaves whole
pipelines out of our cache when lean (libraries stay); pcache_play_open opens no play file when lean; the switches table has
the row.

    python -I -B tests/test_pcache_libs.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <cstdio>
#include <fstream>
#include "pcache_libs.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace pcache_libs;
struct Case { const char* what; bool nvidia; uint64_t ram_gb; uint64_t cache_mb; bool gpl; bool prepare_only; bool want1; };
int main(int argc, char** argv) {
    if (argc < 2) return 2;
    const std::string dir = argv[1];
    CHECK(mode(nullptr) == 0 && mode("") == 0 && mode("0") == 0 && mode("1") == 1 && mode("2") == 2 && mode("3") == 2 && mode("-1") == 0);
    const Case cases[] = {
        {"RTX 3060, 16 GB, 1 GB cache", true, 16, 1024, true, false, true},
        {"RTX 3070 Ti, 16 GB, 600 MB cache", true, 16, 600, true, false, true},
        {"GTX 1660, 8 GB, 512 MB cache", true, 8, 512, true, false, true},
        {"RTX 4060, 20 GB, 2 GB cache", true, 20, 2048, true, false, true},
        {"RTX 4060, 24 GB", true, 24, 2048, true, false, false},
        {"this PC: RTX, 32 GB", true, 32, 4096, true, false, false},
        {"RTX 3060, 16 GB, 511 MB cache", true, 16, 511, true, false, false},
        {"RTX 3060, 16 GB, empty cache", true, 16, 0, true, false, false},
        {"RTX 3060, 16 GB, no stage libraries kept", true, 16, 1024, false, false, false},
        {"RTX 3060, 16 GB, a start that only prepares", true, 16, 1024, true, true, false},
        {"RTX 3060, RAM unknown", true, 0, 1024, true, false, false},
        {"RX 6600, 16 GB (AMD)", false, 16, 1024, true, false, false},
        {"Arc A750, 16 GB (Intel)", false, 16, 1024, true, false, false},
        {"Iris Xe, 8 GB (Mesa)", false, 8, 1024, true, false, false},
        {"RTX 3060, NVK, 16 GB", false, 16, 1024, true, false, false},
    };
    for (const Case& c : cases) {
        Pc pc;
        pc.nvidia_proprietary = c.nvidia, pc.ram = c.ram_gb << 30, pc.glcache = c.cache_mb << 20, pc.gpl = c.gpl, pc.prepare_only = c.prepare_only;
        if (choose(1, pc) != c.want1) { std::printf("rule: %s\n", c.what); return 1; }
        CHECK(!choose(0, pc));
        CHECK(choose(2, pc) == !c.prepare_only);
    }
    // the driver's folder
    CHECK(nvidia_cache_dir(true, "C:\\Users\\a\\AppData\\Local", nullptr, nullptr, nullptr) == "C:\\Users\\a\\AppData\\Local\\NVIDIA\\GLCache");
    CHECK(nvidia_cache_dir(true, nullptr, "/x", "/y", "/z").empty());
    CHECK(nvidia_cache_dir(false, nullptr, "/cache/gl", "/xdg", "/home/a") == "/cache/gl");
    CHECK(nvidia_cache_dir(false, nullptr, "", "/xdg", "/home/a") == "/xdg/nvidia/GLCache");
    CHECK(nvidia_cache_dir(false, nullptr, nullptr, nullptr, "/home/a") == "/home/a/.cache/nvidia/GLCache");
    CHECK(nvidia_cache_dir(false, nullptr, nullptr, nullptr, nullptr).empty());
    // its size, on a tree
    {
        const std::string root = dir + "/GLCache";
        std::filesystem::create_directories(root + "/a/b");
        std::ofstream(root + "/one.bin", std::ios::binary) << std::string(1000, 'x');
        std::ofstream(root + "/a/two.bin", std::ios::binary) << std::string(2500, 'y');
        std::ofstream(root + "/a/b/three.bin", std::ios::binary) << std::string(7, 'z');
        CHECK(folder_bytes(root) == 3507 && folder_bytes(dir + "/none") == 0 && folder_bytes("") == 0);
        CHECK(folder_bytes(root, 1) <= 3507);
    }
    // the record
    const std::string lean = dir + "/mkw_vk_pipelines.bin.lean";
    const char* A = "0123456789abcdef";
    const char* B = "fedcba9876543210";
    CHECK(!lean_read(lean, A));
    CHECK(lean_write(lean, A) && lean_read(lean, A) && !lean_read(lean, B));
    // a start's verdict
    CHECK(lean_now(1, true, true, false) && !lean_now(1, true, false, true));     // (fresh: the rule, whatever was recorded)
    CHECK(lean_now(1, false, false, true) && !lean_now(1, false, true, false));   // (a file read: its record)
    CHECK(!lean_now(0, true, true, true) && !lean_now(0, false, false, true));    // (the switch at 0: full)
    CHECK(lean_now(2, false, false, true) && !lean_now(2, false, true, false));
    std::printf("ok\n");
    return 0;
}
"""


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


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need('#include "pcache_libs.h"' in draw, "vk_draw.cpp does not include pcache_libs.h")
    decide = block(draw, "bool pcache_libs_decide(bool fresh, const char* stamp, uint64_t ram) {")
    ordered(decide, ['pcache_libs::mode(getenv("RX_VK_PCACHE_LIBS_ONLY"));', "if (!mode) return false;", 'pcache_path + ".lean"',
                     "if (!fresh || prepare_only_start()) {", "!fresh && pcache_libs::lean_read(lean, stamp);",
                     "return pcache_libs::lean_now(mode, fresh, false, recorded);",
                     "pc.nvidia_proprietary = dev.driver_id == VK_DRIVER_ID_NVIDIA_PROPRIETARY;", "pc.gpl = gpl_wanted() && gpl_libs_cached();",
                     "pcache_libs::folder_bytes(pcache_libs::nvidia_cache_dir(true, getenv(\"LOCALAPPDATA\")",
                     "const bool on = pcache_libs::choose(mode, pc);", "if (on) pcache_libs::lean_write(lean, stamp);", "else remove(lean.c_str());"],
            "pcache_libs_decide does not decide only at a fresh file, by the rule, recording it")
    need(decide.count("lean_write(") == 1 and decide.count("remove(") == 1, "the record is written or removed outside a fresh file")
    init = block(draw, "void pcache_init() {")
    ordered(init, ["bool with_data = !data.empty();", "pcache_side = pcache_carry::session(how, history);",
                   "pcache_libs_only = pcache_libs_decide(!with_data, pcache_for, ram);", "pcache_play_open(pcache_same);"],
            "pcache_init does not decide before the play file is opened, once the file read is known")
    play = block(draw, "void pcache_play_open(bool same) {")
    need("if (!on || !pcache || !dev.vk13.pipelineCreationCacheControl || pcache_libs_only) {" in play, "a lean file still opens a play file")
    build = block(draw, "VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, int part, bool* cold) {")
    need("const VkPipelineCache wanted = lib_cached || (part < 0 && !driver_cache_only && !pcache_libs_only) ? pcache : VK_NULL_HANDLE;" in build,
         "build_graphics does not leave whole pipelines out of our cache when lean, or the libraries are not kept in it")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_PCACHE_LIBS_ONLY=1` or `2`" in docs, "docs/development.md: the switches table has no RX_VK_PCACHE_LIBS_ONLY row")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pcache-libs-") as tmp:
        src, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        src.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(src), "-o", str(exe)],
                       check=True)
        work = Path(tmp) / "work"
        work.mkdir()
        r = subprocess.run([str(exe), str(work).replace("\\", "/")], capture_output=True, text=True, timeout=60)
        need(r.returncode == 0 and r.stdout.strip() == "ok", "the libraries-only rule: " + (r.stdout.strip() or "exit %d" % r.returncode))
    check_source()
    print("PASS: RX_VK_PCACHE_LIBS_ONLY=1 makes a fresh cache file of libraries alone on small-RAM NVIDIA PCs, recorded for its "
          "life; unset, every pipeline in the file as before")


if __name__ == "__main__":
    main()
