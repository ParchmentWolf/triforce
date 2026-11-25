"""The controller speaker's output (host/pad_speaker.c): the DualSense's audio endpoint, its ring and its output report.

Compiles host/pad_speaker.c as it is around a made-up pad (tests/pad_speaker_test.c): no SDL, no controller, no sound
device and no game file. Checked: by default (every kind of sound Off, headphones Off) nothing opens and the pad keeps
its own sound; it stays shut without a wired DualSense or when switched off; the report that sends the pad's sound to its
speaker and the one that gives the jack back; the mixer's mono samples on the endpoint's first two channels and silence
on the voice coils' two; the 40 ms start, the under-run and the trim; the test tone; a pad that changes, dies or leaves;
the game closing; the Audio tab's Controller speaker rows (their keys against the host's classes and switches, their
defaults all Off, and their values packed as gpu/vk/vk_api.h says).

    py -3 -I -B tests/test_pad_speaker.py [--cc gcc]
"""
import argparse
import os
import re
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
SWITCHES = [name for name in os.environ if name.startswith("HOS_PAD_SPEAKER")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pad-speaker-") as tmp:
        exe = Path(tmp) / "fixture.exe"
        cmd = [args.cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
               "-I", str(ROOT / "host"), str(ROOT / "tests/pad_speaker_test.c"), "-o", str(exe), "-lm"]
        if os.name != "nt":
            cmd += ["-I", str(ROOT / "host/posix"), "-pthread"]
        subprocess.run(cmd, check=True, timeout=120)
        base = {k: v for k, v in os.environ.items() if k not in SWITCHES}
        for mode, env in (("defaults", {}), ("off", {"HOS_PAD_SPEAKER": "0"}),
                          ("modes", {"HOS_PAD_SPEAKER_UI": "0", "HOS_PAD_SPEAKER_OCARINA": "1", "HOS_PAD_SPEAKER_AGONY": "7"}),
                          ("menu", {}), ("ride", {}), ("ride_other", {}), ("wrap", {}), ("reject", {}), ("play", {"HOS_PAD_SPEAKER_VOLUME": "50"}),
                          ("legacy", {"HOS_PAD_SPEAKER_HPF": "0", "HOS_PAD_SPEAKER_LIMITER": "0", "HOS_PAD_SPEAKER_LOW_LATENCY": "0",
                                      "HOS_PAD_SPEAKER_VOLUME": "50"})):
            subprocess.run([str(exe), mode], check=True, timeout=60, env={**base, **env})
    # the mixer hands it every frame it plays, and both ways out of the game give the jack back
    audio = (ROOT / "host/nn_audio.c").read_text(encoding="utf-8")
    loop = audio[audio.index("static DWORD WINAPI renderer_main"):]
    assert "if (speaker_on) hos_pad_speaker_write(speaker_frame, FRAME);" in loop
    main_c = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    assert main_c.index("hos_pad_speaker_shutdown();") < main_c.index("return 0;", main_c.index('hos_log("nnMain returned");'))
    relaunch = (ROOT / "host/hos_relaunch.c").read_text(encoding="utf-8")
    closed = relaunch[relaunch.index("void hos_window_closed_exit(void)"):]
    assert closed.index("hos_pad_speaker_shutdown();") < closed.index("ExitProcess(0);")
    assert "hos_pad_speaker_pad(dualsense," in (ROOT / "host/pad_sdl.c").read_text(encoding="utf-8")
    # the menu's rows (gpu/vk/vk_menu.cpp) and the host agree: a row a class in the classes' order, each kind's key its
    # switch's name, every default Off, and the three numbers packed as the host unpacks them
    speaker = (ROOT / "host/pad_speaker.c").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    header = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
    switches = re.findall(r'"HOS_(PAD_SPEAKER_[A-Z_]+)"', speaker[speaker.index("class_env["):speaker.index("};", speaker.index("class_env["))])
    assert len(switches) == 12
    kept_at = menu.index("static const char* const kept[][2]")
    keys = re.findall(r'"(pad_speaker_[a-z_]+)"', menu[kept_at:menu.index("};", kept_at)])
    assert keys[4:] == [name.lower() for name in switches], keys
    rows = re.findall(r'\{TAB_AUDIO, "[^"]+", &opts\.pad_speaker\[(\d+)\], 0, 2, 1, tx_pad_speaker,', menu)
    assert [int(n) for n in rows] == list(range(12)), rows   # (each kind's row on its class, in the classes' order)
    assert '{TAB_AUDIO, "Controller sync", &opts.pad_speaker_sync, -100, 150, 10, tx_pad_sync,' in menu
    defaults = re.search(r"int pad_speaker\[12\] = \{([^}]*)\};", header).group(1).replace(" ", "").split(",")
    assert defaults == ["0"] * 12, defaults
    assert re.search(r"int pad_speaker_headphones = 0;", header)
    assert "static volatile LONG hp_mode = HOS_PAD_HEADPHONES_OFF" in speaker
    assert "rx_option(HOS_OPT_PAD_SPEAKER_CLASSES, 0)" in speaker
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    assert "packed |= std::clamp(opts.pad_speaker[k], 0, 2) << (2 * k);" in replay
    assert "std::clamp(opts.pad_speaker_volume, 0, 200) | (std::clamp(opts.pad_speaker_sync, -100, 150) + 100) << 8 |" in replay
    assert "if (id == HOS_OPT_PAD_SPEAKER_HEADPHONES) return std::clamp(opts.pad_speaker_headphones, 0, 2);" in replay
    # the vibration's stream carries the speaker's channels (host/rumble_renhdrum.c), both ways out of its pull
    vib = (ROOT / "host/rumble_renhdrum.c").read_text(encoding="utf-8")
    pull = vib[vib.index("static void usb_pull("):vib.index("int rh_usb_find(void *pad)")]
    assert pull.count("hos_pad_speaker_fill(f, frames);") == 2, "usb_pull does not hand the speaker its channels"
    # one speaker block for HD Haptics and the game's sounds: opened and given back in usb_speaker_sync alone
    assert vib.count("rh.hd_haptics_speaker_block(") == 1, "the cable's speaker is opened in more than one place"
    sync = vib[vib.index("static int usb_speaker_sync("):vib.index("static void usb_hd_set(int on) {")]
    assert "rh.hd_haptics_speaker_block(" in sync
    print("PASS: the controller speaker's endpoint, ring, report and shutdown")


if __name__ == "__main__":
    main()
