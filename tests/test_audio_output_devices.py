"""The Audio tab's Output device row (host/audio_output_devices.c, host/nn_audio.c, gpu/vk/vk_menu.cpp).

The device module is compiled with made-up WinMM devices (tests/audio_output_devices_test.c: 80 devices, one name shared,
ids that stay when the list is reordered, the choice's mailbox, the options file's line) and run; the sound's thread's own
handling of the choice is tests/test_audio_output_errors.py's. Then the sources: the row saved by the device's id and not
its number, the devices listed when the menu opens and not each frame, the choice taken before a block is mixed, and the
host's table in the order of MkwVkHost's members.

    python -I -B tests/test_audio_output_devices.py [--cc clang] [--source-only]
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]
ROOT = Path(__file__).resolve().parents[1]


def code(text):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def sources():
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    audio = (ROOT / "host/nn_audio.c").read_text(encoding="utf-8")
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    assert re.search(r'\{TAB_AUDIO, "Output device", &output_pick,', menu), "no Output device row"
    assert re.search(r'\{TAB_AUDIO, "Audio output", &opts\.audio_output, 0, 3,', menu), "the Audio output row changed"
    assert "&& r.value != &output_pick; }" in menu, "the Output device row's number is saved"
    assert 'put("audio_output_device_id", output_want);' in menu and 'put("audio_output_device_name", output_saved_name);' in menu
    tick = menu[menu.index("void menu_tick() {"):]
    assert tick.count("refresh_outputs();") == 1 and "if (open_now.load()) refresh_outputs();" in tick, \
        "the devices are listed again other than when the menu opens"
    assert "if (r.value == &output_pick && output_forced()) return;" in menu, "HOS_AUDIO_DEVICE does not hold the row"
    mixer = audio[audio.index("static DWORD WINAPI renderer_main"):]
    assert mixer.index("output_route_update();") < mixer.index("render_frame(pcm, out_channels);") < mixer.index("output_frame(pcm);")
    body = code(api.split("typedef struct MkwVkHost {", 1)[1].split("} MkwVkHost;", 1)[0])
    fields = [d for d in body.split(";") if d.strip()]
    table = [v.strip() for v in code(backend.split("static const MkwVkHost vk_host = {", 1)[1].split("};", 1)[0]).split(",") if v.strip()]
    assert len(fields) == len(table), "MkwVkHost has %d members, host/rx_backend.c's table %d" % (len(fields), len(table))
    names = ["audio_output_count", "audio_output_info", "audio_output_select", "audio_output_state"]
    at = [i for i, d in enumerate(fields) if any("(*%s)" % n in d for n in names)]
    assert len(at) == 4 and [table[i] for i in at] == ["hos_" + n for n in names], "the host's table has not the device functions in place"
    assert re.search(r"#define MKWVK_API_VERSION (\d+)", api) and int(re.search(r"#define MKWVK_API_VERSION (\d+)", api).group(1)) >= 20


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args()
    sources()
    print("PASS: the Output device row's sources")
    if args.source_only or os.name != "nt":
        return
    with tempfile.TemporaryDirectory(prefix="audio-output-devices-") as tmp:
        exe = Path(tmp) / "devices.exe"
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wno-unused-function", "-I" + str(ROOT / "host"),
                        str(ROOT / "tests/audio_output_devices_test.c"), "-o", str(exe), "-lwinmm", "-lole32"], check=True)
        subprocess.run([str(exe)], check=True, cwd=tmp)


if __name__ == "__main__":
    main()
