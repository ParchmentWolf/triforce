"""The game's freed pages under an import given back and not freed yet (gpu/vk/vk_memory.cpp memory_guest_imported,
imports_leaving_overlap; no game, no GPU).

The host asks the Vulkan back end, before it discards or decommits the game's freed pages (host/hos_mem.c discard_pages and
FreeMemoryPages, host/hos_svc.c UnmapPhysicalMemory), whether an import holds them: if one does they are zeroed and stay. The
answer counted the imports in the table, the retired pools still imported and the ranges under way on the background thread,
but not the imports already given back whose memory is freed only once the GPU is past them: an evicted pool
(imports_give_back) and a retired pool's import (retired_imports_give_back, dead_imports). The driver keeps their pages locked
until then, and a free in that window discarded pages under the lock: device lost (after Casual Gamer's #dev-fixes post:
v0.4.0 on a 16 GB laptop, 2 tours of 5 without the fix, 0 of 53 with it). The census's give-back (guest_release_unimported)
counted them already.

Cuts memory_guest_imported and imports_leaving_overlap out of vk_memory.cpp and runs them against stand-ins: such imports
must answer "imported" over their pages, edges included, and not next to them; an evicted pool whose memory is gone is no
import's; the log line comes for the first 8 and every 64th; RX_VK_IMPORT_LEAVING=0 answers as before. With the new check
taken out, the fixture must fail.

    python -I -B tests/test_import_leaving.py [--cxx g++]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    if text.count(marker) != 1:
        raise SystemExit("FAIL: not found once in vk_memory.cpp: " + marker)
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <utility>
#include <vector>
typedef void* VkBuffer;
typedef void* VkDeviceMemory;
struct Pool {
    uint64_t lo = 0, hi = 0;
    VkDeviceMemory memory = nullptr;
};
std::mutex pools_mu, bg_mu;
std::map<uint64_t, Pool> imported;
std::deque<std::map<uint64_t, Pool>::node_type> retired_pools, evicted_pools;
std::vector<std::pair<uint64_t, uint64_t>> bg_held;
@@DEAD_IMPORT@@
std::deque<DeadImport> dead_imports;
int logged = 0;
void logf(const char* f, ...) { logged += std::strstr(f, "still being given back") != nullptr; }
@@LEAVING@@
@@IMPORTED@@
int fails = 0;
#define CHECK(c, what) do { if (!(c)) { std::printf("FAIL: %s\n", what); fails++; } } while (0)
constexpr uint64_t MB = 1ull << 20;
const auto mem = (VkDeviceMemory)(uintptr_t)1;
std::map<uint64_t, Pool>::node_type node(uint64_t lo, uint64_t hi, bool memory) {
    std::map<uint64_t, Pool> m;
    m[lo] = Pool{lo, hi, memory ? mem : nullptr};
    return m.extract(lo);
}

int main(int argc, char**) {
    const bool off = argc > 1;   // (RX_VK_IMPORT_LEAVING=0: as before, nothing of these counts)
    const uint64_t a = 0x7F00000000ull, b = a + 16 * MB;
    for (int kind = 0; kind < 2; kind++) {
        evicted_pools.clear(), dead_imports.clear();
        if (kind == 0) evicted_pools.push_back(node(a, b, true));
        else {
            DeadImport d{};
            d.memory = mem, d.bytes = b - a, d.lo = a, d.hi = b;
            dead_imports.push_back(std::move(d));
        }
        const char* name = kind ? "a retired pool's import given back, not freed yet" : "an evicted pool, not freed yet";
        char what[160];
        std::snprintf(what, sizeof what, "%s: its pages", name);
        CHECK(memory_guest_imported(a + 4 * MB, a + 5 * MB) == !off, what);
        std::snprintf(what, sizeof what, "%s: a range reaching its first page", name);
        CHECK(memory_guest_imported(a - MB, a + 4096) == !off, what);
        std::snprintf(what, sizeof what, "%s: a range reaching its last page", name);
        CHECK(memory_guest_imported(b - 4096, b + MB) == !off, what);
        std::snprintf(what, sizeof what, "%s: the pages just below and above it", name);
        CHECK(!memory_guest_imported(a - 2 * MB, a) && !memory_guest_imported(b, b + MB), what);
    }
    evicted_pools.clear(), dead_imports.clear();
    evicted_pools.push_back(node(a, b, false));
    CHECK(!memory_guest_imported(a, b), "an evicted pool whose memory is freed: not imported");
    evicted_pools.clear();
    evicted_pools.push_back(node(a, b, true));
    logged = 0;
    for (int i = 0; i < 200; i++) memory_guest_imported(a, a + MB);
    if (!off) CHECK(logged == 8 + 3 - 6, "the line for the first 8 and every 64th (6 were told above)");
    else CHECK(logged == 0, "RX_VK_IMPORT_LEAVING=0: a line");
    if (fails) return 1;
    std::printf(off ? "imports leaving: RX_VK_IMPORT_LEAVING=0 answers as before\n"
                    : "imports leaving: the pages of an import given back and not freed yet are zeroed, not discarded\n");
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    memory = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    dead = re.findall(r"^struct DeadImport \{[^\n]*\};$", memory, re.M)
    if len(dead) != 1:
        raise SystemExit("FAIL: vk_memory.cpp's struct DeadImport not found once")
    imported = block(memory, "int memory_guest_imported(uint64_t lo, uint64_t hi) {")
    leaving = block(memory, "bool imports_leaving_overlap(uint64_t lo, uint64_t hi) {")
    release = block(memory, "int guest_release_unimported(uint64_t lo, uint64_t hi, int (*release)(uint64_t, uint64_t))")
    if "evicted_pools" not in release or "dead_imports" not in release:
        raise SystemExit("FAIL: guest_release_unimported no longer counts the imports given back and not freed yet")
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0

    def build(tmp, name, fn):
        src, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
        src.write_text(FIXTURE.replace("@@DEAD_IMPORT@@", dead[0]).replace("@@LEAVING@@", leaving).replace("@@IMPORTED@@", fn),
                       encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-variable",
                        str(src), "-o", str(exe)], check=True)
        return exe

    with tempfile.TemporaryDirectory(prefix="import-leaving-") as tmp:
        exe = build(tmp, "leaving", imported)
        env = dict(os.environ)
        env.pop("RX_VK_IMPORT_LEAVING", None)
        ran = 0
        for argv, value in (([str(exe)], None), ([str(exe), "off"], "0")):
            if value is not None:
                env["RX_VK_IMPORT_LEAVING"] = value
            r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, creationflags=flags)
            print(r.stdout, end="")
            ran = ran or r.returncode
        if ran:
            raise SystemExit("FAIL: the host's question about pages under an import still being given back")
        cut = "leaving && imports_leaving_overlap(lo, hi)"
        if imported.count(cut) != 1:
            raise SystemExit("FAIL: memory_guest_imported no longer asks imports_leaving_overlap once")
        env.pop("RX_VK_IMPORT_LEAVING", None)
        m = subprocess.run([str(build(tmp, "mutant", imported.replace(cut, "false")))], env=env, capture_output=True,
                           creationflags=flags)
        if m.returncode == 0:
            raise SystemExit("FAIL: the fixture passes without the check of the imports given back")
        print("PASS: without the check the fixture fails (the device lost's way)")


if __name__ == "__main__":
    main()
