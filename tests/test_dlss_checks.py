"""NVIDIA DLSS's small checks (gpu/vk/dlss_checks.h): which scene sizes DLSS takes for an output (the handheld profile's
512x288 at Ultra Performance too, which a fixed 640x360 floor turned away), and Linux paths for NGX: which are ASCII (NGX's
Linux library takes only those; the others go to it as /proc/self/fd/<n>), and UTF-8 decoded (accents, CJK, bytes that are
not UTF-8). Built as C++ and run; also that vk_dlss.cpp and vk_draw.cpp use them. No game,
GPU or NVIDIA SDK required.

python -I -B tests/test_dlss_checks.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_sources():
    dlss = (ROOT / "gpu" / "vk" / "vk_dlss.cpp").read_text(encoding="utf-8")
    draw = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    # (the frame chain DLSS and FSR share: the scene camera and the actor motion)
    chain = (ROOT / "gpu" / "vk" / "vk_temporal.cpp").read_text(encoding="utf-8")
    # (no fixed floor on the scene's size: it follows the output)
    for name, src in (("vk_dlss.cpp", dlss), ("vk_draw.cpp", draw), ("vk_temporal.cpp", chain)):
        assert not re.search(r"\b(width|height)\s*<\s*(640|360)\b", src), name + ": a fixed scene size floor"
    assert "!temporal_scene_size(width, height)" in chain, "temporal_note_scene_draw: the output's sizes"
    assert "!temporal_scene_size(at.width, at.height)" in draw, "skin_check: the output's sizes"
    # (the Linux wide(): decoded, not each byte widened)
    widened = [l.strip() for l in dlss.splitlines() if "std::wstring(s.begin(), s.end())" in l]
    assert widened == ["if (dlss_checks::ascii(s)) return std::wstring(s.begin(), s.end());"], \
        "wide(): bytes widened one by one only for ASCII paths"
    assert "dlss_checks::utf8_to_wide(s, &bad)" in dlss, "wide(): UTF-8 decoded"
    # (NGX's Linux library converts its wide paths back in the "C" locale, ASCII only: a folder named otherwise goes to it
    # as /proc/self/fd/<n>)
    assert "dlss_checks::ascii(s)" in dlss and '"/proc/self/fd/"' in dlss, "wide(): non-ASCII folders by descriptor"
    # ((Triforce, 11-21, the performance audit's PRESENT-37) prepare reads the DLSS model row's preset only through the settle
    # rule, before it asks whether the feature there is can be used: a preset stepped past makes no feature
    prepare = dlss[dlss.index("int prepare(VkCommandBuffer cmd"):]
    prepare = prepare[:prepare.index("\n}\n")]
    assert prepare.count("wanted_preset()") == 1, "prepare: the row's preset read past the settle rule"
    settle = ("const unsigned preset = s.settle.pick(wanted_preset(), s.feature_preset, s.feature != nullptr, texture_frame_no(), "
              "settle_frames);")
    assert settle in prepare and prepare.index(settle) < prepare.index("const bool same_feature ="), \
        "prepare: the preset is not the settle rule's, or is picked after the feature's reuse test"
    assert 'dlss_checks::settle_frames(getenv("RX_VK_DLSS_MODEL_SETTLE"))' in prepare, "prepare: no RX_VK_DLSS_MODEL_SETTLE"
    assert "dlss_checks::PresetSettle settle;" in dlss, "vk_dlss.cpp: the settle rule's state is not kept with the feature"
    # ((Triforce, 11-22, the performance audit's PRESENT-38) the mode is found by mode_for, with its slack unless the switch
    # says strict, and the feature there is is let go only after a mode took the size: a refused size keeps it
    order = [prepare.find(n) for n in (
        'static const bool slack_env = !(getenv("RX_VK_DLSS_MODE_SLACK") && atoi(getenv("RX_VK_DLSS_MODE_SLACK")) == 0);',
        'dlss_checks::mode_for(ranges, nmodes, rw, rh, ow, oh, slack_env && !lab_ab::on("dlssstrict"), &widened);',
        'if (!found) return *fail = "no DLSS mode takes this render size", 0;',
        "temporal_later([old] { NVSDK_NGX_VULKAN_ReleaseFeature(old); });",
        "NGX_VULKAN_CREATE_DLSS_EXT(cmd, 1, 1, &s.feature, s.params, &cp);")]
    assert min(order) >= 0 and order == sorted(order), \
        "prepare: the mode is not found by mode_for before the old feature is let go (%s)" % order
    assert prepare.count("NVSDK_NGX_VULKAN_ReleaseFeature(old)") == 1, "prepare: the old feature is let go in a second place"
    assert "max_w = std::max<unsigned>(r.max_w, rw), max_h = std::max<unsigned>(r.max_h, rh);" in prepare, \
        "prepare: a size taken by the slack is not kept in the feature's range (it would be made again every frame)"
    assert "`RX_VK_DLSS_MODE_SLACK=0`" in (ROOT / "docs" / "development.md").read_text(encoding="utf-8"), \
        "docs/development.md: RX_VK_DLSS_MODE_SLACK is not in the switches table"
    assert "`RX_VK_DLSS_MODEL_SETTLE=<frames>`" in (ROOT / "docs" / "development.md").read_text(encoding="utf-8"), \
        "docs/development.md: RX_VK_DLSS_MODEL_SETTLE is not in the switches table"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_sources()
    with tempfile.TemporaryDirectory(prefix="dlss-checks-") as tmp:
        exe = Path(tmp) / "dlss-checks"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests" / "test_dlss_checks.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
