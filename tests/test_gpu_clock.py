"""The Steam Deck's GPU held at amdgpu's peak stable power state while the game runs (gpu/vk/gpu_clock.h, vk_gpu_clock.cpp,
vk_main.cpp create_device; RX_VK_GPU_CLOCK; Linux; no game/GPU).

The rule is compiled from the header and run on made-up devices: unset, the peak state on the Deck's APU (its LCD and OLED Vulkan
names, or SteamDeck=1 on an integrated GPU) only while the level is "auto"; a level set by hand, or one not read, left alone;
SteamDeck=1 on a discrete GPU, another AMD GPU and any other vendor left alone; =0 nothing; =peak, =1 and =standard on any AMD GPU
at any level, never on NVIDIA. The ioctl's numbers against what amdgpu_drm.h gives them (written out here, as it was before and
since Linux 5.18; on Linux the system's own header too, when it is there). The source: create_device calls it after vkCreateDevice,
on Linux alone, with VK_EXT_physical_device_drm's presence; vk_gpu_clock.cpp is Linux's alone, checks the node it opens is the
device Vulkan names, sets the state on a context of its own and keeps the file open; the docs row is there.

    python -I -B tests/test_gpu_clock.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <cstdio>
#include "gpu_clock.h"
#ifdef CHECK_SYSTEM_HEADER
#include <drm/amdgpu_drm.h>
static_assert(mkwvk::gpu_clock::kCtxIoctl == DRM_IOCTL_AMDGPU_CTX, "DRM_IOCTL_AMDGPU_CTX");
static_assert(mkwvk::gpu_clock::kCtxArgBytes == sizeof(union drm_amdgpu_ctx), "union drm_amdgpu_ctx");
static_assert(mkwvk::gpu_clock::kCtxOpAlloc == AMDGPU_CTX_OP_ALLOC_CTX, "AMDGPU_CTX_OP_ALLOC_CTX");
#ifdef AMDGPU_CTX_OP_SET_STABLE_PSTATE
static_assert(mkwvk::gpu_clock::kCtxOpSetStablePstate == AMDGPU_CTX_OP_SET_STABLE_PSTATE, "AMDGPU_CTX_OP_SET_STABLE_PSTATE");
static_assert(mkwvk::gpu_clock::kPstatePeak == AMDGPU_CTX_STABLE_PSTATE_PEAK, "AMDGPU_CTX_STABLE_PSTATE_PEAK");
static_assert(mkwvk::gpu_clock::kPstateStandard == AMDGPU_CTX_STABLE_PSTATE_STANDARD, "AMDGPU_CTX_STABLE_PSTATE_STANDARD");
#endif
#endif
using namespace mkwvk::gpu_clock;
// (amdgpu_drm.h's numbers, written out: DRM_COMMAND_BASE 0x40, DRM_AMDGPU_CTX 0x02, _IOC_READ | _IOC_WRITE 3, a 16-byte union;
// the ops and the states of Linux 5.18's)
static_assert(kCtxIoctl == 0xC0106442ul, "DRM_IOCTL_AMDGPU_CTX");
static_assert(kCtxOpAlloc == 1 && kCtxOpSetStablePstate == 6 && kPstateStandard == 1 && kPstatePeak == 4, "the ops and states");
static int bad = 0;
static void expect(Want got, Want want, const char* what) {
    if (got != want) { std::printf("FAIL %s: %d, wanted %d\n", what, (int)got, (int)want); bad++; }
}
int main() {
    const char* lcd = "AMD Custom GPU 0405 (RADV VANGOGH)";
    const char* oled = "AMD Custom GPU 0932 (RADV VANGOGH)";
    expect(choose(nullptr, 0x1002, true, lcd, nullptr, "auto").want, kPeak, "Deck LCD, auto");
    expect(choose(nullptr, 0x1002, true, oled, nullptr, "auto").want, kPeak, "Deck OLED, auto");
    expect(choose(nullptr, 0x1002, true, "AMD Radeon Graphics (RADV VANGOGH)", "1", "auto").want, kPeak, "SteamDeck=1, integrated");
    expect(choose(nullptr, 0x1002, false, "AMD Radeon RX 6800 XT (RADV NAVI21)", "1", "auto").want, kNone, "SteamDeck=1, discrete");
    expect(choose(nullptr, 0x1002, true, "AMD Radeon 780M (RADV PHOENIX)", nullptr, "auto").want, kNone, "another AMD APU");
    expect(choose(nullptr, 0x1002, true, "AMD Radeon 780M (RADV PHOENIX)", "0", "auto").want, kNone, "SteamDeck=0");
    expect(choose(nullptr, 0x1002, true, oled, nullptr, "manual").want, kNone, "Deck, level manual");
    expect(choose(nullptr, 0x1002, true, oled, nullptr, "profile_peak").want, kNone, "Deck, level profile_peak");
    expect(choose(nullptr, 0x1002, true, oled, nullptr, nullptr).want, kNone, "Deck, level unread");
    expect(choose("0", 0x1002, true, oled, nullptr, "auto").want, kNone, "=0 on the Deck");
    expect(choose("peak", 0x1002, false, "AMD Radeon RX 7900 XTX (RADV NAVI31)", nullptr, "manual").want, kPeak, "=peak, any AMD");
    expect(choose("1", 0x1002, false, "AMD Radeon RX 7900 XTX", nullptr, nullptr).want, kPeak, "=1, any AMD");
    expect(choose("standard", 0x1002, true, oled, nullptr, "auto").want, kStandard, "=standard");
    expect(choose("peak", 0x10DE, false, "NVIDIA GeForce RTX 4070", nullptr, "auto").want, kNone, "=peak on NVIDIA");
    expect(choose(nullptr, 0x10DE, true, lcd, "1", "auto").want, kNone, "NVIDIA, a Deck's name");
    expect(choose(nullptr, 0x8086, true, "Intel(R) Graphics", "1", "auto").want, kNone, "Intel");
    if (bad) return 1;
    std::printf("OK\n");
    return 0;
}
'''


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check_source():
    main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    clock = (ROOT / "gpu/vk/vk_gpu_clock.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    create = block(main, "bool create_device() {")
    call = "    gpu_clock_device_created(has_extension(exts, VK_EXT_PHYSICAL_DEVICE_DRM_EXTENSION_NAME));\n"
    at = create.index(call)
    if create.index("vkCreateDevice(") > at:
        fail("create_device calls gpu_clock_device_created before vkCreateDevice")
    if "#ifdef __linux__" not in "\n".join(create[:at].splitlines()[-2:]) or not create[at + len(call):].lstrip().startswith("#endif"):
        fail("the call is not Linux's alone")
    body = clock[clock.index('#include "vk_gpu_clock.h"') + len('#include "vk_gpu_clock.h"'):].strip()
    if not body.startswith("#ifdef __linux__") or not body.endswith("#endif"):
        fail("vk_gpu_clock.cpp is not Linux's alone")
    fn = block(clock, "void gpu_clock_device_created(bool drm_ext) {")
    for needle in ("major(st.st_rdev) != (unsigned)drm.renderMajor", "minor(st.st_rdev) != (unsigned)drm.renderMinor",
                   "a.in.op = gpu_clock::kCtxOpAlloc;", "s.in.op = gpu_clock::kCtxOpSetStablePstate;", "s.in.ctx_id = a.alloc.ctx_id;",
                   "held_fd = fd;", "gpu_clock::choose(sw, dev.props.vendorID, integrated, dev.props.deviceName, getenv(\"SteamDeck\")"):
        if needle not in fn:
            fail("gpu_clock_device_created no longer has: " + needle)
    tail = fn[fn.index("held_fd = fd;"):]
    if "close(fd)" in tail:
        fail("gpu_clock_device_created closes the file it holds the state with")
    if fn.index("if (dev.props.vendorID != 0x1002) return;") > fn.index("logf("):
        fail("gpu_clock_device_created logs on GPUs that are not AMD's")
    if "`RX_VK_GPU_CLOCK=0`" not in dev:
        fail("docs/development.md has no RX_VK_GPU_CLOCK row")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    try:
        check_source()
    except ValueError as e:
        fail("a text this test reads moved (%s)" % e)
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    system_header = sys.platform.startswith("linux") and any(
        Path(d, "drm/amdgpu_drm.h").is_file() for d in ("/usr/include", "/usr/include/libdrm"))
    with tempfile.TemporaryDirectory(prefix="gpu-clock-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(FIXTURE, encoding="utf-8")
        extra = ["-DCHECK_SYSTEM_HEADER", "-I/usr/include/libdrm"] if system_header else []
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Werror", "-I" + str(ROOT / "gpu/vk")] + extra +
                               [str(cpp), "-o", str(exe)], capture_output=True, text=True, creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60, creationflags=flags)
        if done.returncode or done.stdout.strip() != "OK":
            fail((done.stdout + done.stderr).strip())
    print("PASS: the GPU's stable power state: peak on the Steam Deck's APU at level auto, the switch's states on any AMD GPU, "
          "nothing elsewhere; the ioctl's numbers%s; create_device calls it on Linux after vkCreateDevice and the file stays open"
          % (" (and the system's amdgpu_drm.h)" if system_header else ""))


if __name__ == "__main__":
    main()
