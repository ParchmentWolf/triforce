"""Compile and run the Graphics tab's Auto (this PC) rules (gpu/vk/auto_settings.h; no game, no GPU), and check that the menu
still uses them: the row is Off by default, a row it sets changed by hand turns it Off, and the replay's windows reach its tuning.

python -I -B tests/test_auto_settings.py [--cxx g++]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]

C = r'''
#include "auto_settings.h"
#include "upscaler_rows.h"
#include <cstdio>
#include <cstdlib>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace auto_settings;
static Hardware card(int vendor, unsigned mb, bool dlss = false, bool fsr4 = false) {
    Hardware h;
    h.vendor = vendor, h.vram_mb = mb, h.dlss_runs = dlss, h.fsr4_runs = fsr4, h.ram_mb = 32768, h.threads = 16;
    return h;
}
int main() {
    namespace ur = mkwvk::upscaler_rows;
    // (the menu's values, kept here so the rules compile on their own)
    CHECK(GAME == ur::GAME && DLSS == ur::DLSS && FSR3 == ur::FSR3 && FSR4 == ur::FSR4);
    CHECK(ur::percent(RES_FULL) == 100 && ur::percent(RES_75) == 75 && ur::percent(RES_QUALITY) == 67 &&
          ur::percent(RES_PERFORMANCE) == 50 && ur::percent(RES_BALANCED) == 58 && ur::percent(RES_ULTRA_PERFORMANCE) == 33);
    // the tiers by memory, and what holds a card at 1
    CHECK(tier_of(card(NVIDIA, 4096)) == 1 && tier_of(card(NVIDIA, 6144)) == 2 && tier_of(card(NVIDIA, 8192)) == 3);
    CHECK(tier_of(card(NVIDIA, 11264)) == 3 && tier_of(card(NVIDIA, 12282)) == 4 && tier_of(card(NVIDIA, 16376)) == 5);
    Hardware igpu = card(INTEL, 16384);
    igpu.integrated = true;
    CHECK(tier_of(igpu) == 1);
    Hardware nomesh = card(AMD, 8192);
    nomesh.mesh_native = false;
    CHECK(tier_of(nomesh) == 1);
    Hardware lowram = card(NVIDIA, 16384);
    lowram.ram_mb = 8192;
    CHECK(tier_of(lowram) == 2);
    // the upscaler by the card's maker, where it runs
    Choice c = choose(card(NVIDIA, 12282, true));
    CHECK(c.upscaler == DLSS && c.resolution == RES_QUALITY && c.shadow_res == 1 && c.grass == 1 && c.tex_detail == 0);
    c = choose(card(NVIDIA, 8192, true));
    CHECK(c.upscaler == DLSS && c.resolution == RES_BALANCED && c.shadow_res == 0 && c.grass == 0);
    c = choose(card(NVIDIA, 8192, false));
    CHECK(c.upscaler == GAME && c.resolution == RES_FULL);
    c = choose(card(AMD, 16304, false, true));
    CHECK(c.upscaler == FSR4 && c.resolution == RES_QUALITY && c.shadow_res == 2 && c.grass == 2);
    c = choose(card(AMD, 6144, true, false));   // (DLSS is NVIDIA's: an AMD card never gets it)
    CHECK(c.upscaler == GAME && c.resolution == RES_75);
    c = choose(card(NVIDIA, 4096, true));       // (tier 1: the game's own at 50%)
    CHECK(c.upscaler == GAME && c.resolution == RES_PERFORMANCE);
    igpu.threads = 4;
    c = choose(igpu);
    CHECK(c.upscaler == GAME && c.resolution == RES_ULTRA_PERFORMANCE);
    Hardware few = card(NVIDIA, 24576, true);
    few.threads = 4;
    c = choose(few);   // (the recording threads draw the grass: the game's with 4 threads)
    CHECK(c.grass == 0 && c.shadow_res == 2);
    // the fingerprint: another card, another memory or another upscaler that runs chooses again
    const Hardware a = card(NVIDIA, 12282, true);
    CHECK(fingerprint(a, 0x10de, 0x2782) == fingerprint(a, 0x10de, 0x2782));
    CHECK(fingerprint(a, 0x10de, 0x2782) != fingerprint(a, 0x10de, 0x2704));
    CHECK(fingerprint(a, 0x10de, 0x2782) != fingerprint(card(NVIDIA, 12282, false), 0x10de, 0x2782));
    CHECK(fingerprint(a, 0x10de, 0x2782) >= 0);
    // the tuning: gathers kWindows of play, lighter only with frames missed and the GPU busy
    Tuning t;
    for (int i = 0; i < kWindows - 1; i++) CHECK(tune(t, 16.5f, 400, 50, 60, true, true) == WAIT);
    CHECK(tune(t, 16.5f, 400, 50, 60, true, true) == LIGHTER && t.steps == 1 && t.went_down);
    for (int i = 0; i < kWindows * 3; i++) CHECK(tune(t, 1, 20, 60, 60, true, true) == WAIT);   // (menus: not play)
    for (int i = 0; i < kWindows - 1; i++) tune(t, 5, 400, 60, 60, true, true);
    CHECK(tune(t, 5, 400, 60, 60, true, true) == KEEP && t.done);   // (no step up after a step down)
    Tuning u;
    for (int i = 0; i < kWindows - 1; i++) tune(u, 6, 400, 60, 60, true, true);
    CHECK(tune(u, 6, 400, 60, 60, true, true) == HEAVIER && !u.went_down);
    Tuning cpu;
    for (int i = 0; i < kWindows - 1; i++) tune(cpu, 8, 400, 40, 60, true, true);
    CHECK(tune(cpu, 8, 400, 40, 60, true, true) == CPU_BOUND && cpu.done && cpu.steps == 0);
    // its state across a restart
    Tuning s;
    s.steps = 2, s.went_down = true;
    Tuning back;
    bool settled = false;
    unpack(pack(s, true), back, settled);
    CHECK(back.steps == 2 && back.went_down && settled && back.done);
    CHECK(best_step(DLSS) == RES_QUALITY && best_step(FSR4) == RES_QUALITY && best_step(GAME) == RES_FULL);
    std::printf("auto settings: tiers, upscalers by maker, detail rows, fingerprint, tuning and its saved state\n");
    return 0;
}
'''


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit("FAIL: " + where + " no longer has: " + needle)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    header = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    need("vk_menu.cpp", menu, ['{TAB_GRAPHICS, "Auto (this PC)", &opts.auto_pc, 0, 1, 1, tx_onoff,',
                               "auto_row_set(r.value);", "auto_start();", "auto_tick();",
                               "const auto_settings::Choice c = auto_settings::choose(hw);"])
    need("vk_menu.h", header, ["int auto_pc = 0;"])   # (Off by default: nothing set, nothing tuned)
    need("vk_replay.cpp", replay, ["menu_auto_tune(gpu_ms, draws,"])
    # (a hand change of a row it sets turns it Off)
    m = re.search(r"void auto_row_set\(const int\* value\) \{(.*?)\n\}", menu, re.S)
    if not m or "opts.auto_pc = 0;" not in m.group(1):
        raise SystemExit("FAIL: auto_row_set no longer turns Auto Off on a hand change")
    with tempfile.TemporaryDirectory(prefix="auto-settings-") as tmp:
        src = Path(tmp) / "t.cpp"
        src.write_text(C, encoding="utf-8")
        exe = Path(tmp) / ("t.exe" if sys.platform == "win32" else "t")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-I", str(ROOT / "gpu/vk"), "-o", str(exe), str(src)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        if r.returncode:
            raise SystemExit(r.stderr.strip())


if __name__ == "__main__":
    main()
