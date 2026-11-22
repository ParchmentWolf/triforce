"""The texture converters' compute pipelines through the pipeline cache, made before the game (gpu/vk/vk_texture.cpp
texture_compute_pipeline, texture_pipelines_warm, RX_VK_TEX_PIPES_AHEAD).

The ASTC decoder, the BC encoder, the unswizzle and the swizzle back were each made without a pipeline cache inside the first
upload that needed it: with an empty driver cache (a first start, a new driver) that upload waited for the compile. What this
checks without the game:

1. The source: none of the four ready functions creates its pipeline without the cache any more (each goes through
   texture_compute_pipeline); precompile_run makes them right after the pipeline cache is read, inside its .running marker
   (a driver that crashes there counts as a start that did not get through); a start whose preparation was skipped at the
   build makes them too (texture_pipelines_unprepared, after pcache_init); the switch has its docs row.
2. The code, cut out and compiled with stand-ins (a fake vkCreateComputePipelines and shared cache): the shared cache first,
   no cache when that fails, no cache at all with RX_VK_TEX_PIPES_AHEAD=0; the warm makes all four where the GPU does not
   sample ASTC, only the unswizzle and the swizzle back where it does, once, and nothing with the switch off.

    python -I -B tests/test_texture_pipelines_warm.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
READY = {"astc_ready": "astc_pipe", "bc_ready": "bc_pipe", "unswizzle_ready": "unsw_pipe", "swizzle_back_ready": "swz_pipe"}


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def fail(message):
    raise SystemExit("FAIL: " + message)


def check_source(tex, draw, main, dev):
    for fn, pipe in READY.items():
        body = block(tex, "bool %s() {" % fn)
        if "vkCreateComputePipelines(dev.device, VK_NULL_HANDLE" in body:
            fail("%s still makes its pipeline without the pipeline cache" % fn)
        if "texture_compute_pipeline(ci, &%s)" % pipe not in body:
            fail("%s does not make its pipeline through texture_compute_pipeline" % fn)
    pre = block(draw, "void precompile_run(")
    marker, init = pre.index("done_marker{running};"), pre.index("pcache_init();")
    warm = pre.index("texture_pipelines_warm();")
    if not marker < init < warm < pre.index("pipe_notes_read("):
        fail("precompile_run does not make the converters after the cache is read, inside its marker, before the notes")
    early = pre.index("its notes are dropped")
    if early > warm:
        fail("precompile_run makes the converters before the two-failed-starts return: a crash there would repeat every start")
    unprepared = block(draw, "void texture_pipelines_unprepared() {")
    if not unprepared.index("pcache_init();") < unprepared.index("texture_pipelines_warm();"):
        fail("texture_pipelines_unprepared does not read the cache before the converters")
    skipped = main[main.index("the shaders' preparation was skipped at the build"):]
    skipped = skipped[:skipped.index("return true;")]
    if "texture_pipelines_unprepared();" not in skipped:
        fail("a start whose preparation was skipped at the build does not make the converters")
    if "`RX_VK_TEX_PIPES_AHEAD=0`" not in dev:
        fail("docs/development.md has no RX_VK_TEX_PIPES_AHEAD row")


HEAD = r'''#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
using VkResult = int;
using VkPipeline = uintptr_t;
using VkPipelineCache = uintptr_t;
constexpr VkResult VK_SUCCESS = 0;
constexpr uintptr_t VK_NULL_HANDLE = 0;
constexpr int VK_FORMAT_ASTC_4x4_UNORM_BLOCK = 157;
constexpr unsigned VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT = 1;
struct VkComputePipelineCreateInfo { int sType; uintptr_t layout; };
struct VkFormatProperties { unsigned linearTilingFeatures, optimalTilingFeatures, bufferFeatures; };
struct { uintptr_t device = 0x1234, physical = 0x99; } dev;
#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "CHECK failed line %d: %s\n", __LINE__, #c); std::exit(7); } } while (0)
int shared_calls = 0, shared_fail = 0, null_calls = 0, native = 0;
int made[4];   // (astc, bc, unswizzle, swizzle back: each ready function's calls)
void logf(const char*, ...) {}
VkResult shared_cache_compute(const VkComputePipelineCreateInfo* ci, VkPipeline* out) {
    CHECK(ci && out);
    shared_calls++;
    if (shared_fail) { *out = 0xdead; return -3; }
    *out = 0xcace;
    return VK_SUCCESS;
}
VkResult vkCreateComputePipelines(uintptr_t device, VkPipelineCache cache, unsigned n, const VkComputePipelineCreateInfo* ci,
                                  const void* alloc, VkPipeline* out) {
    CHECK(device == dev.device && cache == VK_NULL_HANDLE && n == 1 && ci && !alloc && out);
    null_calls++;
    *out = 0xf00d;
    return VK_SUCCESS;
}
void vkGetPhysicalDeviceFormatProperties(uintptr_t physical, int format, VkFormatProperties* p) {
    CHECK(physical == dev.physical && format == VK_FORMAT_ASTC_4x4_UNORM_BLOCK);
    *p = {};
    if (native) p->optimalTilingFeatures = VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT;
}
bool astc_ready() { return ++made[0], true; }
bool bc_ready() { return ++made[1], true; }
bool unswizzle_ready() { return ++made[2], true; }
bool swizzle_back_ready() { return ++made[3], true; }
'''

MAIN = r'''
int main(int argc, char** argv) {
    CHECK(argc == 2);
    const std::string k = argv[1];
    const bool off = getenv("RX_VK_TEX_PIPES_AHEAD") && !atoi(getenv("RX_VK_TEX_PIPES_AHEAD"));
    VkComputePipelineCreateInfo ci{29, 0x1357};
    VkPipeline out = 0;
    if (k == "create") {
        CHECK(texture_compute_pipeline(ci, &out) == VK_SUCCESS);
        if (off) CHECK(shared_calls == 0 && null_calls == 1 && out == 0xf00d);
        else CHECK(shared_calls == 1 && null_calls == 0 && out == 0xcace);
    } else if (k == "fallback") {
        shared_fail = 1;
        CHECK(texture_compute_pipeline(ci, &out) == VK_SUCCESS);
        CHECK(null_calls == 1 && out == 0xf00d && shared_calls == (off ? 0 : 1));
    } else if (k == "warm" || k == "warm-native") {
        native = k == "warm-native";
        texture_pipelines_warm();
        texture_pipelines_warm();   // (once)
        if (off) CHECK(!made[0] && !made[1] && !made[2] && !made[3]);
        else if (native) CHECK(!made[0] && !made[1] && made[2] == 1 && made[3] == 1);
        else CHECK(made[0] == 1 && made[1] == 1 && made[2] == 1 && made[3] == 1);
    } else {
        CHECK(!"no such case");
    }
    std::printf("OK %s\n", k.c_str());
    return 0;
}
'''


def fixture(tex):
    parts = [block(tex, "bool tex_pipes_ahead() {"), block(tex, "VkResult texture_compute_pipeline("),
             block(tex, "void texture_pipelines_warm() {")]
    return HEAD + "\n".join(parts) + MAIN


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    vk = ROOT / "gpu" / "vk"
    tex = (vk / "vk_texture.cpp").read_text(encoding="utf-8")
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    main_cpp = (vk / "vk_main.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    try:
        check_source(tex, draw, main_cpp, dev)
        text = fixture(tex)
    except ValueError as e:
        fail("a text this test reads moved, or is not there (%s)" % e)
    problems = []
    with tempfile.TemporaryDirectory(prefix="tex-pipes-ahead-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(text, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wno-unused-function", str(cpp), "-o", str(exe)],
                               capture_output=True, text=True)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        base = {k: v for k, v in os.environ.items() if k != "RX_VK_TEX_PIPES_AHEAD"}
        n = 0
        for value in (None, "1", "0"):
            env = dict(base, **({"RX_VK_TEX_PIPES_AHEAD": value} if value is not None else {}))
            for case in ("create", "fallback", "warm", "warm-native"):
                n += 1
                done = subprocess.run([str(exe), case], env=env, capture_output=True, text=True, timeout=30)
                if done.returncode or done.stdout.strip() != "OK " + case:
                    problems.append("%s with RX_VK_TEX_PIPES_AHEAD=%s: %s" % (case, value, (done.stdout + done.stderr).strip()))
    if problems:
        fail("\n  ".join([""] + problems))
    print("PASS: the texture converters through the pipeline cache (no cache when it fails or with the switch off), made "
          "before the game inside the precompile's marker and on a start without one (%d cases)" % n)


if __name__ == "__main__":
    main()
