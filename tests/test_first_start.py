"""A first start sized to the card: with RX_VK_FIRST_START_AUTO, the Render resolution row set once on a weak GPU
(gpu/vk/first_start.h, vk_menu.cpp menu_first_start, vk_main.cpp mkwvk_init; no game, no GPU).

(Triforce, 11-22, the performance audit's PRESENT-46, after Source A's.) With no options file every card started with
the Render resolution at Auto. Source A's tier 1 (an integrated GPU, a card without mesh shaders, 4.5 GB of video memory
or less) starts with the 3D at 50%, or 33% for an integrated GPU beside 4 threads or fewer. Here that is behind a
switch that is off unless set: what a first start on a weak card gets is the owner's to decide.

Compiles first_start.h and checks the rule for many cards:
  integrated GPUs (a handheld's, a laptop's, a desktop's with 2 to 32 threads)   50%, and 33% at 4 threads or fewer
  discrete cards without mesh shaders (2 to 12 GB)                                50%
  discrete cards with them: 2, 3, 4 and 4.5 GB                                    50%
                            4.5 GB and a megabyte, 6, 8, 11, 12, 16, 24, 32 GB    no change
  a card that reports no memory, or no thread count                               never tier 1 for that alone
  and that nothing in the rule reads the SteamDeck variable (a desktop card started from that launcher stays as it is);
the switch (off when unset or 0, on at 1, a larger number plays that many MB); and that the choice is made only with
the switch on, no options file, RX_VK_LOW_SPEC not asked and HOS_DYNRES not set.

Then the source: menu_init only notes that there was no file; menu_first_start reads the switch and the card, sets the
row through the upscaler's own steps, moves the restart row's start value with it, saves nothing and logs one line;
mkwvk_init calls it after the device is made and its line logged; and the switch's row is in the development guide.

    python -I -B tests/test_first_start.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


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


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "first_start.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace first_start;
static Choice card(bool integrated, bool mesh, uint64_t mb, unsigned threads) {
    Card c;
    c.integrated = integrated, c.mesh_shaders = mesh, c.vram_mb = mb, c.threads = threads;
    return choose(c);
}
int main() {
    CHECK(kRowHalf == 4 && kRowThird == 6 && kSmallVramMb == 4608 && kFewThreads == 4);
    // integrated GPUs: tier 1 whatever they report; 33% beside 4 threads or fewer
    for (uint64_t mb : {0ull, 512ull, 2048ull, 3840ull, 8192ull, 16384ull, 32768ull})
        for (int mesh = 0; mesh < 2; mesh++) {
            for (unsigned t : {1u, 2u, 4u}) CHECK(card(true, mesh, mb, t).row == kRowThird && card(true, mesh, mb, t).why == kIntegrated);
            for (unsigned t : {0u, 5u, 6u, 8u, 12u, 16u, 32u})
                CHECK(card(true, mesh, mb, t).row == kRowHalf && card(true, mesh, mb, t).why == kIntegrated);
        }
    CHECK(card(true, true, 3840, 8).row == kRowHalf);    // (a handheld: 4 cores, 8 threads, its own GPU)
    CHECK(card(true, true, 8192, 4).row == kRowThird);   // (Source A's note: a 2-core, 4-thread laptop's own GPU)
    // discrete cards without mesh shaders: 50%, whatever their memory and threads
    for (uint64_t mb : {0ull, 2048ull, 4096ull, 8192ull, 11264ull, 12288ull})
        for (unsigned t : {0u, 2u, 4u, 8u, 16u}) CHECK(card(false, false, mb, t).row == kRowHalf && card(false, false, mb, t).why == kNoMeshShaders);
    // discrete cards with mesh shaders: by their video memory alone, 4.5 GB the last of tier 1
    for (unsigned t : {0u, 2u, 4u, 6u, 8u, 16u, 32u}) {
        for (uint64_t mb : {1024ull, 2048ull, 3072ull, 4018ull, 4096ull, 4607ull, 4608ull})
            CHECK(card(false, true, mb, t).row == kRowHalf && card(false, true, mb, t).why == kSmallVram);
        for (uint64_t mb : {4609ull, 5892ull, 6144ull, 8188ull, 8192ull, 10240ull, 11264ull, 12288ull, 16376ull, 24564ull, 32607ull})
            CHECK(card(false, true, mb, t).row == 0 && card(false, true, mb, t).why == kKeep);
        CHECK(card(false, true, 0, t).row == 0);   // (no memory reported: not tier 1 for that)
    }
    // the switch
    CHECK(switch_mb(nullptr) == -1 && switch_mb("") == -1 && switch_mb("0") == -1 && switch_mb("-5") == -1 && switch_mb("on") == -1);
    CHECK(switch_mb("1") == 0 && switch_mb("2") == 2 && switch_mb("4096") == 4096 && switch_mb("24564") == 24564);
    // when the choice is made at all: (has_options, low_spec, resolution_env, switch)
    CHECK(applies(false, false, false, 0) && applies(false, false, false, 4096));
    CHECK(!applies(false, false, false, -1));                 // (the switch off: the default)
    CHECK(!applies(true, false, false, 0) && !applies(true, false, false, 4096));   // (an options file: the player's own)
    CHECK(!applies(false, true, false, 0));                   // (RX_VK_LOW_SPEC sets the row itself)
    CHECK(!applies(false, false, true, 0));                   // (HOS_DYNRES sets it for the run)
    for (int m = 0; m < 8; m++)
        for (int64_t sw : {(int64_t)-1, (int64_t)0, (int64_t)4096})
            CHECK(applies(m & 1, m & 2, m & 4, sw) == (m == 0 && sw >= 0));
    // the lab's number plays a small card on a large one
    CHECK(card(false, true, (uint64_t)switch_mb("4096"), 32).row == kRowHalf && card(false, true, (uint64_t)switch_mb("6144"), 32).row == 0);
    CHECK(std::strlen(why_text(kIntegrated)) && std::strlen(why_text(kNoMeshShaders)) && std::strlen(why_text(kSmallVram)) &&
          std::strlen(why_text(kKeep)));
    std::puts("first start: tier 1 for integrated GPUs, cards without mesh shaders and 4.5 GB or less; off unless asked");
    return fails ? 1 : 0;
}
"""


def check_source():
    header = (VK / "first_start.h").read_text(encoding="utf-8")
    code = "\n".join(l for l in header.splitlines() if not l.lstrip().startswith("//"))
    check("getenv" not in code and "SteamDeck" not in code and "#include <vulkan" not in code,
          "first_start.h reads the environment (a desktop card under SteamDeck=1 must stay as it is) or needs Vulkan")
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    init = block(menu, "void menu_init() {")
    check("first_start_no_file = !has_options;" in init and "first_start::" not in init and "RX_VK_FIRST_START_AUTO" not in init,
          "menu_init does more than note that there was no options file (the card is not known there)")
    check(init.index("first_start_no_file = !has_options;") < init.index('getenv("RX_VK_LOW_SPEC")'), "the note is not before RX_VK_LOW_SPEC's block")
    first = block(menu, "void menu_first_start() {")
    for part in ('first_start::switch_mb(getenv("RX_VK_FIRST_START_AUTO"))',
                 'const bool low_spec = getenv("RX_VK_LOW_SPEC") && atoi(getenv("RX_VK_LOW_SPEC")) != 0;',
                 'if (!first_start::applies(!first_start_no_file, low_spec, getenv("HOS_DYNRES") != nullptr, asked)) return;',
                 "card.integrated = dev.props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;",
                 "card.mesh_shaders = dev.mesh_shader;",
                 "card.vram_mb = asked > 0 ? (uint64_t)asked : device_vram_bytes() >> 20;",
                 "card.threads = cpu_count();",   # ((Triforce, 11-22, OS-49) cpu_count.h
                 "opts.resolution = ur::snap(upscaler(), choice.row);",
                 "restart_state.restart_value(restart_slot_of(r), restart_value_of(r));",
                 'logf("menu: first start: tier 1 ('):
        check(part in first, "menu_first_start: missing " + part)
    check(first.index("first_start::applies(") < first.index("first_start::choose(card)") < first.index("opts.resolution ="),
          "menu_first_start sets the row before it has asked whether it applies")
    check(first.count("opts.") == first.count("opts.resolution") and "SteamDeck" not in first and "fopen" not in first
          and "save" not in first.replace("nothing is saved", ""),
          "menu_first_start sets another row than the Render resolution, reads SteamDeck, or saves the options")
    check("void menu_first_start();" in (VK / "vk_menu.h").read_text(encoding="utf-8"), "vk_menu.h does not declare menu_first_start")
    main = (VK / "vk_main.cpp").read_text(encoding="utf-8")
    start = main[main.index("const MkwVkRenderer* mkwvk_init(const MkwVkHost* h) {"):]
    order = [start.index(p) for p in ("if (!create_instance() || !pick_device() || !create_device()) return nullptr;",
                                     'logf("vk: %s, Vulkan %u.%u, driver %#x; mesh shaders %s', "    menu_first_start();\n",
                                     "table.start = start;")]
    check(order == sorted(order) and main.count("menu_first_start()") == 1,
          "mkwvk_init does not call menu_first_start once, after the device is made and before the renderer's table is given out")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `RX_VK_FIRST_START_AUTO=1`, `RX_VK_FIRST_START_AUTO=<MB>` |" in docs, "docs/development.md has no row for RX_VK_FIRST_START_AUTO")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="first-start-") as tmp:
        src, exe = Path(tmp) / "first.cpp", Path(tmp) / "first.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(VK), str(src), "-o", str(exe)], check=True)
        out = subprocess.run([str(exe)], stdout=subprocess.PIPE, text=True, timeout=60)
        print(out.stdout.strip())
        if out.returncode:
            raise SystemExit("FAIL: the rule")
    print("PASS: a first start on a weak card takes its Render resolution only with RX_VK_FIRST_START_AUTO, no options file "
          "and no RX_VK_LOW_SPEC; the hook is after the device")


if __name__ == "__main__":
    main()
