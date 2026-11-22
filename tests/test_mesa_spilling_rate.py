"""shader_spilling_rate=2 for Mesa's Intel shader compiler, set before the driver reads it (gpu/vk/mesa_spilling.h; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-55, after Source A's.) Mesa's Intel compiler builds a program whose
registers do not fit in fewer, larger steps at spilling rate 2: minutes and gigabytes less on the large compute programs.
The Linux build sets the driver's option in its environment before the instance is made, never over a value the player
set; RX_VK_NO_SPILLING_RATE=1 leaves the driver as it is. No other driver reads the option.

Compiles a small driver against the header and checks:
  wanted      the Linux build with the switch unset, "" or 0; not with 1 or any other number; never the Windows build;
  effective   the player's own value wins (3, 1, 2); 2 where wanted and nothing set; nothing where not wanted;
  told        the log line on Mesa's Intel driver alone;
  the name and the rate are the driver's option and 2.

And reads gpu/vk/vk_main.cpp: in create_instance, under #ifndef _WIN32 and behind the switch,
setenv("shader_spilling_rate", "2", 0) (0: no overwrite) comes before vkCreateInstance(; nothing else sets it; the log
line is keyed on VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA; and the switches table has the row.

    python -I -B tests/test_mesa_spilling_rate.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "mesa_spilling.h"
#include <cstdio>
#include <cstring>
#include <initializer_list>

static int checks, fails;
static void want(const char* what, bool got, bool wanted) {
    checks++;
    if (got != wanted) fails++, printf("FAIL %s: %d, want %d\n", what, (int)got, (int)wanted);
}
static bool same(const char* a, const char* b) {
    return (!a && !b) || (a && b && !std::strcmp(a, b));
}

int main() {
    using namespace mesa_spilling;
    want("the option's name", same(kName, "shader_spilling_rate"), true);
    want("the rate", same(kRate, "2"), true);
    // the Linux build
    want("linux, the switch unset", wanted(false, nullptr), true);
    want("linux, the switch empty", wanted(false, ""), true);
    want("linux, the switch 0", wanted(false, "0"), true);
    want("linux, the switch 1", wanted(false, "1"), false);
    want("linux, the switch 2", wanted(false, "2"), false);
    // the Windows build sets nothing, whatever the switch
    for (const char* off : {(const char*)nullptr, "", "0", "1"}) want("the Windows build", wanted(true, off), false);
    // what the driver reads: the player's value first
    want("the player's 3 wins", same(effective("3", true), "3"), true);
    want("the player's 1 wins", same(effective("1", true), "1"), true);
    want("the player's 2 with the switch off", same(effective("2", false), "2"), true);
    want("nothing set, wanted: 2", same(effective(nullptr, true), "2"), true);
    want("nothing set, not wanted: the driver's own", effective(nullptr, false) == nullptr, true);
    // the log's line
    want("told on Mesa's Intel driver", told(true), true);
    want("not told on any other driver", told(false), false);
    if (fails) printf("mesa spilling rate: FAILED (%d of %d checks)\n", fails, checks);
    else printf("mesa spilling rate: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check_source():
    src = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    if '#include "mesa_spilling.h"' not in src:
        raise SystemExit("vk_main.cpp does not include mesa_spilling.h")
    at = src.find("bool create_instance() {")
    if at < 0:
        raise SystemExit("vk_main.cpp has no create_instance()")
    body = src[at:src.index("\n}\n", at)]
    call = 'if (mesa_spilling::wanted(false, getenv("RX_VK_NO_SPILLING_RATE"))) setenv("shader_spilling_rate", "2", 0);'
    if body.count(call) != 1:
        raise SystemExit("create_instance does not set shader_spilling_rate=2 without overwriting, behind RX_VK_NO_SPILLING_RATE")
    if src.count('setenv("shader_spilling_rate"') != 1 or 'putenv("shader_spilling_rate' in src:
        raise SystemExit("vk_main.cpp sets shader_spilling_rate somewhere else too")
    made = body.index("vkCreateInstance(&ci, nullptr, &dev.instance)")
    if body.index(call) > made:
        raise SystemExit("create_instance sets the rate after the instance is made: the driver has read its options by then")
    # under #ifndef _WIN32: the nearest preprocessor line before the call opens it, the nearest after closes it
    before = [l.strip() for l in body[:body.index(call)].split("\n") if l.lstrip().startswith("#")]
    after = [l.strip() for l in body[body.index(call):].split("\n") if l.lstrip().startswith("#")]
    if not before or before[-1] != "#ifndef _WIN32" or not after or after[0] != "#endif":
        raise SystemExit("create_instance: the setenv is not inside an #ifndef _WIN32 block of its own")
    device = src[src.index("bool create_device() {"):]
    told = device.find("if (mesa_spilling::told(drv.driverID == VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA)) {")
    line = device.find("vk: Mesa's Intel compiler spills at rate %s (driconf shader_spilling_rate: 2 unless set)")
    if told < 0 or line < told or line - told > 400 or "getenv(mesa_spilling::kName)" not in device[told:line]:
        raise SystemExit("create_device: the rate's log line is not keyed on Mesa's Intel driver id")
    if device.index("dev.driver_id = drv.driverID;") > told:
        raise SystemExit("create_device: the rate's log line is not beside the driver id")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `RX_VK_NO_SPILLING_RATE=1` |" not in docs or "`gpu/vk/mesa_spilling.h`" not in docs or "Linux build only" not in docs:
        raise SystemExit("docs/development.md: the switches table has no row for RX_VK_NO_SPILLING_RATE")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="mesa-spilling-") as tmp:
        cpp, exe = Path(tmp) / "mesa_spilling_test.cpp", Path(tmp) / "mesa-spilling.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the spilling rate's checks failed")


if __name__ == "__main__":
    main()
