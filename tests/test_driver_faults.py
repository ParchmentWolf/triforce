"""Programs the driver faulted on kept out of it, and one build of a program at a time, on AMD's Windows driver
(gpu/vk/driver_faults.h; vk_draw.cpp fault_quarantine, driver_fault_file_note, guarded_graphics, build_graphics; no game,
no GPU).

(Triforce, 11-22, the performance audit's PIPE-57, after Source A's.) The guards caught a fault in the driver's compiler and
a fault during the start restarted the game, but nothing remembered the program: the next start faulted on it again, and in
play a second build of the same program could go into the driver while the first was still inside. Now, on AMD's own
Windows driver (or everywhere with RX_VK_DRIVER_FAULTS=2), a faulted program is kept out of the driver for the run and, by
a line the fault's handler writes to triforce_driver_faults.txt, for later starts with that driver; and a program has one
build inside the driver at a time. Other drivers: nothing of it. 0: nowhere.

The header is compiled and run:
- the switch, and whether it is on for many made-up PCs (Windows and Linux; AMD's own driver, RADV, AMD's open driver,
  NVIDIA's, Intel's, Mesa's, MoltenVK's): on for AMD's own driver on Windows alone at 1, everywhere at 2, nowhere at 0;
  this PC (NVIDIA on Windows) has it off, as before;
- the file's line (35 bytes, made without the C library) and its parse: this vendor's and driver's lines only, CRLF
  taken, broken lines passed over;
- the gate with 8 threads on one program: never two inside; a probe that may not wait is told busy; a fault keeps the
  program out for every later build, said once; a key from the file is kept out from the start.
Then driver_fault_file_note, cut out of vk_draw.cpp, appends the line to a file with the system's own calls, and nothing
without a program in the gate. And the source: the graphics guard clears the handle, notes the fault and writes the line
only where the gate set a program, before driver_fault_restart; build_graphics goes through the gate around the creation
and its retry (none after a fault), ends it before the probe's return, and the rule asks for AMD's own driver; the
switches table has the row.

    python -I -B tests/test_driver_faults.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

RULES = r"""
#include <atomic>
#include <cstdio>
#include <cstring>
#include <thread>
#include "driver_faults.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace driver_faults;
struct Pc { const char* what; bool windows; bool amd_proprietary; bool want1; };
int main() {
    CHECK(mode(nullptr) == 1 && mode("") == 1 && mode("0") == 0 && mode("1") == 1 && mode("2") == 2 && mode("5") == 2 && mode("-1") == 0);
    const Pc pcs[] = {
        {"this PC: NVIDIA RTX, Windows", true, false, false},
        {"RX 6800 XT, AMD's Windows driver", true, true, true},
        {"RX 5700 XT, AMD's Windows driver", true, true, true},
        {"RX 7900 XT, AMD's Windows driver", true, true, true},
        {"RX 6600, RADV on Linux", false, false, false},
        {"RX 6600, AMD's own driver on Linux", false, true, false},
        {"Arc B580, Intel's Windows driver", true, false, false},
        {"Iris Xe, Mesa on Linux", false, false, false},
        {"GTX 1060, NVIDIA on Linux", false, false, false},
        {"RTX 4070, NVIDIA on Windows", true, false, false},
    };
    for (const Pc& pc : pcs) {
        CHECK(on(1, pc.windows, pc.amd_proprietary) == pc.want1);
        CHECK(on(2, pc.windows, pc.amd_proprietary));
        CHECK(!on(0, pc.windows, pc.amd_proprietary));
    }
    // the line and its parse
    char l[kLine + 1];
    CHECK(line(l, 0x1002, 0x800161, 0x6eaa646d07ea4e43ull) == kLine && !strcmp(l, "00001002 00800161 6eaa646d07ea4e43\n"));
    std::string file = l;
    line(l, 0x1002, 0x800161, 0x5fa56485a6b07619ull);
    file += std::string(l, kLine - 1) + "\r\n";                  // (CRLF)
    line(l, 0x1002, 0x800170, 0x1111ull);                        // (another driver version)
    file += l;
    line(l, 0x10de, 0x800161, 0x2222ull);                        // (another vendor)
    file += l;
    file += "garbage line\n00001002 00800161 zz\n00001002 00800161 4e5ce183a33b0855";   // (broken, then one with no newline)
    const std::vector<uint64_t> keys = parse(file, 0x1002, 0x800161);
    CHECK(keys == (std::vector<uint64_t>{0x6eaa646d07ea4e43ull, 0x5fa56485a6b07619ull, 0x4e5ce183a33b0855ull}));
    CHECK(parse(file, 0x1002, 0x800170) == std::vector<uint64_t>{0x1111ull} && parse("", 1, 2).empty());
    // the gate: 8 threads on one program, never two inside
    Quarantine q;
    std::atomic<int> inside{0}, most{0}, went{0};
    std::vector<std::thread> threads;
    for (int t = 0; t < 8; t++)
        threads.emplace_back([&] {
            for (int i = 0; i < 200; i++) {
                if (q.begin(42, true) != Quarantine::Begin::Go) continue;
                const int now = ++inside;
                int m = most.load();
                while (now > m && !most.compare_exchange_weak(m, now)) {}
                std::this_thread::yield();
                --inside, went++;
                q.end(42, false);
            }
        });
    for (auto& th : threads) th.join();
    CHECK(most == 1 && went == 1600 && !q.faulted(42));
    // a probe that may not wait is told busy; another program goes in beside it
    CHECK(q.begin(7, true) == Quarantine::Begin::Go && q.begin(7, false) == Quarantine::Begin::Busy && q.begin(8, false) == Quarantine::Begin::Go);
    // a fault: kept out from then on, said once
    CHECK(q.end(7, true) && q.faulted(7) && q.begin(7, true) == Quarantine::Begin::Faulted && q.begin(7, false) == Quarantine::Begin::Faulted);
    CHECK(!q.end(8, false) && q.count() == 1);
    // a waiting build whose program faults while it waits is told so
    {
        CHECK(q.begin(9, true) == Quarantine::Begin::Go);
        std::atomic<int> got{-1};
        std::thread waiter([&] { got = (int)q.begin(9, true); });
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        CHECK(got == -1);   // (waiting at the gate)
        q.end(9, true);
        waiter.join();
        CHECK(got == (int)Quarantine::Begin::Faulted);
    }
    // keys from the file: kept out from the start
    Quarantine f;
    f.load(keys);
    CHECK(f.begin(0x5fa56485a6b07619ull, true) == Quarantine::Begin::Faulted && f.begin(0x1111ull, true) == Quarantine::Begin::Go && f.count() == 3);
    std::printf("ok\n");
    return 0;
}
"""

WRITER = r"""
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <string>
#include "driver_faults.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
thread_local uint64_t fault_key = 0;
uint32_t fault_vendor = 0x1002, fault_driver = 0x800161;
wchar_t fault_file_w[MAX_PATH * 2] = L"";
/* CUT */
static std::string read(const char* path) {
    std::string s;
    if (FILE* f = fopen(path, "rb")) {
        char b[256];
        for (size_t n; (n = fread(b, 1, sizeof b, f)) > 0;) s.append(b, n);
        fclose(f);
    }
    return s;
}
int main(int argc, char** argv) {
    if (argc < 2) return 2;
    const std::string path = std::string(argv[1]) + "/triforce_driver_faults.txt";
    MultiByteToWideChar(CP_UTF8, 0, path.c_str(), -1, fault_file_w, MAX_PATH * 2);
    driver_fault_file_note();                       // (no program in the gate: nothing)
    CHECK(read(path.c_str()).empty());
    fault_key = 0x6eaa646d07ea4e43ull;
    driver_fault_file_note();
    fault_key = 0x5fa56485a6b07619ull;
    driver_fault_file_note();
    const std::string got = read(path.c_str());
    CHECK(got == "00001002 00800161 6eaa646d07ea4e43\n00001002 00800161 5fa56485a6b07619\n");
    CHECK(driver_faults::parse(got, 0x1002, 0x800161).size() == 2);
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


def check_source(draw):
    need('#include "driver_faults.h"' in draw, "vk_draw.cpp does not include driver_faults.h")
    rule = block(draw, "bool driver_faults_on() {")
    need(rule.count("dev.driver_id == VK_DRIVER_ID_AMD_PROPRIETARY") == 2 and "driver_faults::on(driver_faults_mode(), true," in rule
         and "driver_faults::on(driver_faults_mode(), false," in rule, "the rule does not ask for AMD's own driver, on Windows")
    need('static const int mode = driver_faults::mode(getenv("RX_VK_DRIVER_FAULTS"));' in block(draw, "int driver_faults_mode() {"),
         "the switch is not RX_VK_DRIVER_FAULTS, read once")
    guard = block(draw, "__declspec(noinline) VkResult guarded_graphics(")
    ordered(guard, ['__except (driver_fault_note(GetExceptionInformation(), "graphics")) {',
                    "if (fault_key) *pl = VK_NULL_HANDLE, driver_fault_hit = true, driver_fault_file_note();",
                    "driver_fault_restart();", "return VK_ERROR_UNKNOWN;"],
            "the graphics guard does not clear the handle and write the line before the restart, only for a gated build")
    quar = block(draw, "driver_faults::Quarantine& fault_quarantine() {")
    ordered(quar, ["std::call_once(once,", '"triforce_driver_faults.txt"', "fault_vendor = dev.props.vendorID, fault_driver = dev.props.driverVersion;",
                   "driver_faults::parse(text, fault_vendor, fault_driver);", "q.load(keys);", "MultiByteToWideChar(CP_UTF8, 0, path.c_str(), -1, fault_file_w,",
                   'logf("vk: driver faults: %zu programs'],
            "fault_quarantine does not load the file once, make the handler's path or say it")
    build = block(draw, "VkPipeline build_graphics(const Program& p, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, int part, bool* cold) {")
    ordered(build, ["const bool fault_gated = driver_faults_on();", "if (fault_gated) {",
                    "fault_quarantine().begin(p.key, cold == nullptr);",
                    "if (b == driver_faults::Quarantine::Begin::Busy) return *cold = true, VK_NULL_HANDLE;",
                    "if (b == driver_faults::Quarantine::Begin::Faulted) {", "return VK_NULL_HANDLE;", "fault_key = p.key, driver_fault_hit = false;",
                    "const PcacheUse use(pcache_door, wanted);", "VkResult r = cached_graphics(cache, &ci, &pl);",
                    "&& !driver_fault_hit) {", "r = cached_graphics(cache, &ci, &pl);", "if (fault_gated) {", "fault_key = 0;",
                    "if (fault_quarantine().end(p.key, driver_fault_hit))", "driver_fault_hit = false;",
                    "if (cold && r == VK_PIPELINE_COMPILE_REQUIRED) return *cold = true, VK_NULL_HANDLE;"],
            "build_graphics does not go through the gate around the creation and its retry, or ends it after a return")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_DRIVER_FAULTS=0` or `2`" in docs, "docs/development.md: the switches table has no RX_VK_DRIVER_FAULTS row")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need("void driver_fault_file_note() {" in draw, "vk_draw.cpp has no driver_fault_file_note")
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="driver-faults-") as tmp:
        tmp = Path(tmp)
        tests = [("rules", RULES)]
        if os.name == "nt":   # (the handler's writer is Windows code)
            tests.append(("writer", WRITER.replace("/* CUT */", block(draw, "void driver_fault_file_note() {"))))
        for name, text in tests:
            src, exe = tmp / (name + ".cpp"), tmp / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(src), "-o", str(exe)],
                           check=True)
            work = tmp / ("work-" + name)
            work.mkdir()
            r = subprocess.run([str(exe), str(work).replace("\\", "/")], capture_output=True, text=True, timeout=120, env=env)
            need(r.returncode == 0 and r.stdout.strip() == "ok", "driver faults (%s): %s" % (name, r.stdout.strip() or r.returncode))
    check_source(draw)
    print("PASS: on AMD's Windows driver a faulted program is kept out of the driver (and in the file for later starts), one build "
          "of a program at a time; other drivers as before; RX_VK_DRIVER_FAULTS=0 nowhere")


if __name__ == "__main__":
    main()
