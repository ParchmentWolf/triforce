"""The host's camera jitter is one whole sample (gpu/vk/temporal_jitter.h): the upscalers publish the scene's size and the
jitter sequence's length together (vk_temporal.cpp, vk_fsr3_inputs.cpp), the replay table gives them to the host in one
call (vk_replay.cpp jitter_sample, MkwVkRenderer.jitter_sample) and the host caches a frame's under a lock of its own
(host/rx_backend.c hos_dlss_jitter_clip). TemporalJitter itself is built and run with a publisher and readers on threads:
a sample read is never one publication's size with another's length. No game or GPU required.

python -I -B tests/test_temporal_jitter.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, signature):
    start = text.index(signature)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(condition, why):
    if not condition:
        raise SystemExit("FAIL: " + why)


STRESS = r"""
#include "gpu/vk/temporal_jitter.h"
#include <atomic>
#include <cstdio>
#include <thread>
#include <vector>

int main() {
    mkwvk::TemporalJitter j;
    if (j.read(1).width) return std::puts("FAIL: a sample before any was published"), 1;
    j.publish(1280, 720, 32, 10);
    MkwVkJitter s = j.read(40);
    if (s.width != 1280 || s.height != 720 || s.phases != 32) return std::puts("FAIL: the sample 30 frames on"), 1;
    if (j.read(41).width) return std::puts("FAIL: a sample more than 30 frames old"), 1;
    j.publish(0, 720, 32, 50);
    if (j.read(50).width || j.read(50).phases) return std::puts("FAIL: a size of 0 is not none"), 1;
    std::atomic<bool> stop{false};
    std::atomic<int> torn{0}, seen{0};
    std::thread writer([&] {
        for (uint32_t n = 1; n < 200000; n++) j.publish(n, n + 1, n + 2, 100);
        stop = true;
    });
    std::vector<std::thread> readers;
    for (int r = 0; r < 3; r++)
        readers.emplace_back([&] {
            while (!stop) {
                const MkwVkJitter x = j.read(100);
                if (x.width && (x.height != x.width + 1 || x.phases != x.width + 2)) torn++;
                if (x.width) seen++;
            }
        });
    writer.join();
    for (auto& t : readers) t.join();
    if (torn) return std::printf("FAIL: %d samples of two publications\n", torn.load()), 1;
    std::printf("temporal jitter: ok (%d samples read whole)\n", seen.load());
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    temporal = (VK / "vk_temporal.cpp").read_text(encoding="utf-8")
    fsr = (VK / "vk_fsr3_inputs.cpp").read_text(encoding="utf-8")
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    api = (VK / "vk_api.h").read_text(encoding="utf-8")
    host = (ROOT / "host" / "rx_backend.c").read_text(encoding="utf-8")
    # the producers publish one sample; the readers read it whole, with their own conditions before
    need(re.search(r"s\.jitter\.publish\(rw, rh, ", temporal), "vk_temporal.cpp: the engines' upscale does not publish one sample")
    need("s.jitter.publish(rw, rh, fsr3_math::jitter_phases(rw, dw), now);" in block(fsr, "void upscaled("),
         "vk_fsr3_inputs.cpp upscaled: FSR 3.1 does not publish one sample")
    for text, name in ((temporal, "MkwVkJitter temporal_jitter_sample()"), (fsr, "MkwVkJitter jitter_sample()")):
        body = block(text, name)
        need("s.jitter.read(" in body, "%s: the sample is not read whole" % name)
    need("jitter_w" not in temporal and "jitter_w" not in fsr, "the size is still kept apart from the length")
    need("if (miss && now >= miss && now - miss > kMissedFrames) return {};" in block(fsr, "MkwVkJitter jitter_sample()"),
         "vk_fsr3_inputs.cpp jitter_sample: FSR 3.1's missed frames no longer end the jitter")
    # the replay table and the host
    need("*out = temporal_jitter_sample();" in block(replay, "void jitter_sample(MkwVkJitter* out)") and
         "t.jitter_sample = jitter_sample;" in replay, "vk_replay.cpp: the table gives the host no whole sample")
    need(re.search(r"void \(\*jitter_sample\)\(MkwVkJitter \*out\);", api) and
         int(re.search(r"#define MKWVK_API_VERSION (\d+)", api).group(1)) >= 22,
         "vk_api.h: MkwVkRenderer has no jitter_sample, at version 22 or later")
    clip = block(host, "int hos_dlss_jitter_clip(")
    need("AcquireSRWLockExclusive(&lock);" in clip and clip.index("const LONG frame = presents;") >
         clip.index("AcquireSRWLockExclusive(&lock);") and "vk->jitter_sample(&jitter);" in clip and
         clip.index("ReleaseSRWLockExclusive(&lock);") < clip.index("dlss_jitter_clip(p,"),
         "rx_backend.c hos_dlss_jitter_clip: the frame's sample is not taken whole under its lock")
    with tempfile.TemporaryDirectory(prefix="temporal-jitter-") as folder:
        cpp, exe = Path(folder) / "stress.cpp", Path(folder) / "stress.exe"
        cpp.write_text(STRESS, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                        "-pthread", "-DVK_NO_PROTOTYPES", "-I" + str(ROOT), "-I" + str(VK), str(cpp), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True, timeout=60)
    print("PASS: the host's camera jitter is one whole sample")


if __name__ == "__main__":
    main()
