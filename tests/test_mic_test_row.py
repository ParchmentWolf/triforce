"""The Audio tab's Test microphone row (host/nn_audio_in.c hos_mic_test, host/mic_gain.h, gpu/vk/vk_menu.cpp).

mic_peak_permille, the meter's level, is compiled and run on each sample format: silence 0, full scale 1000, half scale
500, a float out of range held at 1000. Then the sources: the test reads through a source of its own (one more than the
game's streams), the level is taken only while it runs, the host's table has mic_test where MkwVkHost has it, the row
stops the test when the Audio tab is left (its tick at every menu tick's end), and HOS_MIC_TEST_*'s values agree in the
renderer's header and the host's file.

    python -I -B tests/test_mic_test_row.py [--cc clang]
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]
ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include "mic_gain.h"
#include <stdio.h>
#include <stdlib.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
int main(void) {
    int16_t s16[4] = {0, 0, 0, 0};
    CHECK(mic_peak_permille(MIC_GAIN_PCM16, (const uint8_t *)s16, sizeof s16) == 0);
    s16[2] = -32768;
    CHECK(mic_peak_permille(MIC_GAIN_PCM16, (const uint8_t *)s16, sizeof s16) == 1000);
    s16[2] = 16384;
    CHECK(mic_peak_permille(MIC_GAIN_PCM16, (const uint8_t *)s16, sizeof s16) == 500);
    int8_t s8[2] = {-64, 3};
    CHECK(mic_peak_permille(MIC_GAIN_PCM8, (const uint8_t *)s8, sizeof s8) == 500);
    float f[3] = {0.25f, -2.0f, 0.1f};
    CHECK(mic_peak_permille(MIC_GAIN_FLOAT, (const uint8_t *)f, sizeof f) == 1000);
    f[1] = -0.5f;
    CHECK(mic_peak_permille(MIC_GAIN_FLOAT, (const uint8_t *)f, sizeof f) == 500);
    int32_t s32[1] = {1073741824};
    CHECK(mic_peak_permille(MIC_GAIN_PCM32, (const uint8_t *)s32, sizeof s32) == 500);
    CHECK(mic_peak_permille(3, (const uint8_t *)s32, sizeof s32) == 0);   /* (24-bit: not one of the gain's formats) */
    puts("PASS: the meter's level for each sample format");
    return 0;
}
'''


def code(text):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="clang")
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="mic-test-row-") as tmp:
        c, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture.exe"
        c.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "host"), str(c), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    audio_in = (ROOT / "host/nn_audio_in.c").read_text(encoding="utf-8")
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    assert "static Source sources[MAX_STREAMS + 1];" in audio_in, "the test has no source of its own"
    pump = audio_in[audio_in.index("static void pump(Source *src) {"):audio_in.index("static void pump_all(void) {")]
    assert "if (test_here) {" in pump and "} else mic_gain_apply(src->format, buf, got, gain);" in pump, \
        "the level is measured when no test runs"
    enum = r"enum \{ HOS_MIC_TEST_ON = 1, HOS_MIC_TEST_OPEN = 2, HOS_MIC_TEST_STANDIN = 4, HOS_MIC_TEST_FRESH = 8, HOS_MIC_TEST_CLIP = 16,\s*HOS_MIC_TEST_OFF = 32 \};"
    assert re.search(enum, api) and re.search(enum, audio_in), "HOS_MIC_TEST_* differ between vk_api.h and nn_audio_in.c"
    body = code(api.split("typedef struct MkwVkHost {", 1)[1].split("} MkwVkHost;", 1)[0])
    fields = [d for d in body.split(";") if d.strip()]
    table = [v.strip() for v in code(backend.split("static const MkwVkHost vk_host = {", 1)[1].split("};", 1)[0]).split(",") if v.strip()]
    at = [i for i, d in enumerate(fields) if "(*mic_test)" in d]
    assert len(fields) == len(table) and len(at) == 1 and table[at[0]] == "hos_mic_test", "the host's table has no hos_mic_test in its place"
    tick = menu[menu.index("void mic_test_tick(bool focused) {"):menu.index("void menu_tick() {")]
    assert "cur_tab != TAB_AUDIO" in tick and "opts.mic == 0" in tick and "!open_now.load()" in tick, "the test outlives the Audio tab"
    assert "~MicTick() { mic_test_tick(focused); }" in menu, "the test is not told at each tick's end"
    assert '{TAB_AUDIO, kTestMic, nullptr, 0, 0, 0, nullptr,' in menu
    print("PASS: the Test microphone row's sources")


if __name__ == "__main__":
    main()
