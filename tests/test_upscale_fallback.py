"""Exercise the actual generic upscale fallback without Vulkan or a GPU.

(Triforce, 11-22, the performance audit's GPUWORK-21, after Source B's and Source A's; gpu/vk/stub_same_size.h.) A gameplay
network that cannot run is stood in for at its input's size too, and both gameplay networks take the typed upscale: the
cases 9dc, 9dc-same, fd-same, same and 9dc-pipeline-failure, and all of them once more with RX_VK_STUB_SAME_SIZE=0 (as
before: a same-size 9dc98871 declined, an upscaling one blitted). The rule's header is compiled with the function.

python tests/test_upscale_fallback.py [--source gpu/vk/vk_draw.cpp] [--cxx clang++]
Use --cxx g++ on Linux, or --cxx cl in a configured Visual Studio compiler shell. No SDK needed.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'gpu/vk/vk_draw.cpp').is_file())

def block(text, marker):
    start = text.index(marker)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

PREFIX = r'''
#define _CRT_SECURE_NO_WARNINGS

#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <unordered_set>
#include <vector>
#include "stub_same_size.h"   // ((Triforce, 11-22, GPUWORK-21) the rule upscale_stub asks, as it is)

// Only the Vulkan declarations used by upscale_stub; no Vulkan SDK or runtime.
using VkCommandBuffer = uintptr_t;
using VkImage = uintptr_t;
using VkImageView = uintptr_t;
using VkPhysicalDevice = uintptr_t;
using VkFormat = uint32_t;
using VkFormatFeatureFlags = uint32_t;
using VkImageAspectFlags = uint32_t;
using VkImageType = uint32_t;
using VkImageViewType = uint32_t;
constexpr uint32_t VK_IMAGE_VIEW_TYPE_2D = 1;
using VkSampleCountFlagBits = uint32_t;
using VkImageLayout = uint32_t;
using VkFilter = uint32_t;
constexpr uint32_t VK_FORMAT_UNDEFINED = 0, VK_FORMAT_B10G11R11_UFLOAT_PACK32 = 122,
                   VK_FORMAT_E5B9G9R9_UFLOAT_PACK32 = 123, VK_FORMAT_R8G8B8A8_UNORM = 37;
constexpr uint32_t VK_IMAGE_TYPE_2D = 1, VK_IMAGE_ASPECT_COLOR_BIT = 1, VK_SAMPLE_COUNT_1_BIT = 1,
                   VK_IMAGE_LAYOUT_GENERAL = 1, VK_FILTER_LINEAR = 1;
constexpr uint32_t VK_FORMAT_FEATURE_BLIT_SRC_BIT = 1, VK_FORMAT_FEATURE_BLIT_DST_BIT = 2,
                   VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT = 4,
                   VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT = 8, VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT = 16;
struct VkFormatProperties {
    VkFormatFeatureFlags optimalTilingFeatures{};
};
struct Subresource {
    uint32_t aspectMask{}, mipLevel{}, baseArrayLayer{}, layerCount{};
};
struct Offset {
    int32_t x{}, y{}, z{};
};
struct VkImageBlit {
    Subresource srcSubresource;
    Offset srcOffsets[2];
    Subresource dstSubresource;
    Offset dstOffsets[2];
};
constexpr int NVN_FORMAT_RGB9E5F = 64, NVN_FORMAT_R11G11B10F = 63;
constexpr unsigned NVN_TEXTURE_SWIZZLE_R = 2, NVN_TEXTURE_SWIZZLE_G = 3, NVN_TEXTURE_SWIZZLE_B = 4;
struct Desc {
    int target = 2, format = 64;
    unsigned width = 64, height = 32, depth = 1;
    unsigned swizzle_r = 2, swizzle_g = 3, swizzle_b = 4;
};
struct nvn_tex {
    Desc d;
    uint64_t gpu = 10, serial = 99;
};
struct nvn_view {};
struct NvnState {
    uint64_t tex[6][128]{}, img[6][32]{};
};
struct Texture {
    VkImage image = (VkImage)11;
    VkFormat format = VK_FORMAT_B10G11R11_UFLOAT_PACK32;
    unsigned width = 64, height = 32, depth = 1, layers = 1, levels = 1, skip = 0;
    VkImageType type = VK_IMAGE_TYPE_2D;
    VkImageAspectFlags aspect = VK_IMAGE_ASPECT_COLOR_BIT;
    bool bc = false;
    VkSampleCountFlagBits samples = VK_SAMPLE_COUNT_1_BIT;
};
Texture src, dst;
nvn_tex source, destination;
bool override_view = false, movie = false, pipeline_ok = true;
bool missing_storage = false, missing_sample = false, missing_linear = false;
bool missing_input_view = false, missing_output_view = false;
unsigned blits = 0, typed_calls = 0, views = 0, movie_calls = 0, writes = 0, gameplay_logs = 0, gameplay_warnings = 0;
struct {
    VkPhysicalDevice physical{};
} dev;
void cs_slot_counts(const NvnState &, uint32_t *t, uint32_t *i) { *t = *i = 1; }
bool texture_of(int h, nvn_tex *t, nvn_view *v, bool *hv) {
    assert(h == 1 || h == 2);
    *t = h == 1 ? source : destination;
    *v = {};
    *hv = override_view;
    return true;
}
// (the recording lock of a parallel replay: upscale_stub holds it around the texture cache and the typed helper, and never
// across the temporal upscaler, which takes its own lock first. The stand-ins below say so each time they are called)
static int lock_depth;
struct ParLock {
    ParLock() { lock_depth++; }
    ~ParLock() { lock_depth--; }
};
Texture *texture_get(const nvn_tex *t, bool) { assert(lock_depth > 0); return t->gpu == 10 ? &src : &dst; }
void vkGetPhysicalDeviceFormatProperties(VkPhysicalDevice, VkFormat format, VkFormatProperties *p) {
    p->optimalTilingFeatures = VK_FORMAT_FEATURE_BLIT_SRC_BIT | VK_FORMAT_FEATURE_BLIT_DST_BIT |
                               VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT |
                               VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT | VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT;
    if (missing_storage && format == VK_FORMAT_B10G11R11_UFLOAT_PACK32)
        p->optimalTilingFeatures &= ~VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT;
    if (missing_sample && format == VK_FORMAT_E5B9G9R9_UFLOAT_PACK32)
        p->optimalTilingFeatures &= ~VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT;
    if (missing_linear && format == VK_FORMAT_E5B9G9R9_UFLOAT_PACK32)
        p->optimalTilingFeatures &= ~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
}
void end_pass(VkCommandBuffer) {}
// (the temporal upscaler, off here: upscale_stub offers it the frame first, vk_draw.cpp temporal_rejected_network)
bool temporal_wanted() { return false; }
static bool temporal_rejected_network(VkCommandBuffer, uint64_t, Texture *, const nvn_tex *, Texture *, const nvn_tex *) {
    assert(lock_depth == 0);
    return false;
}
void full_barrier(VkCommandBuffer) {}
bool dump_on() { return false; }
void logf(const char *format, ...) {
    if (std::strstr(format, "gameplay RGB9E5 upscale uses the typed fallback"))
        gameplay_logs++;
    if (std::strstr(format, "gameplay RGB9E5 upscale unavailable"))
        gameplay_warnings++;
}
void texture_written(Texture *t) {
    assert(t == &dst && lock_depth > 0);
    writes++;
}
void dump_image(VkCommandBuffer, Texture *, unsigned, unsigned, const char *) {}
bool movie_upscale(VkCommandBuffer, uint64_t, uint64_t, Texture *) {
    movie_calls++;
    return movie;
}
bool gameplay_network(uint64_t key) {
    return key == 0xfd029a317a9a4b94ull || key == 0x9dc98871eb7fc101ull;
}
enum class ViewUse { Sample, Storage };
constexpr VkImageView VK_NULL_HANDLE = 0;
VkImageView texture_view(Texture *t, const nvn_tex *, const nvn_view *v, VkImageViewType type,
                         ViewUse use, VkFormat *f = nullptr, VkFormat forced = VK_FORMAT_UNDEFINED) {
    assert(!v && type == VK_IMAGE_VIEW_TYPE_2D && lock_depth > 0);
    views++;
    if (t == &src) {
        assert(use == ViewUse::Sample && forced == VK_FORMAT_UNDEFINED);
        if (f) *f = VK_FORMAT_E5B9G9R9_UFLOAT_PACK32;
        return missing_input_view ? 0 : (VkImageView)101;
    }
    assert(t == &dst && use == ViewUse::Storage && forced == VK_FORMAT_B10G11R11_UFLOAT_PACK32);
    if (f) *f = VK_FORMAT_B10G11R11_UFLOAT_PACK32;
    return missing_output_view ? 0 : (VkImageView)102;
}
// ((Triforce, 11-18) FSR 3.1 picked as the upscaler takes a rejected network's pass first, outside the recording lock, with
// the two textures' views; off unless the case says)
bool fsr3_on = false;
unsigned fsr3_calls = 0;
bool fsr3_wanted() { return fsr3_on; }
bool fsr3_upscale(VkCommandBuffer, uint64_t, bool known, Texture *in, VkImageView in_view, Texture *out, VkImageView out_view,
                  uint32_t level) {
    assert(lock_depth == 0 && !known && in == &src && out == &dst && in_view == (VkImageView)101 &&
           out_view == (VkImageView)102 && level == 0);
    fsr3_calls++;
    return true;
}
static bool typed_upscale(VkCommandBuffer, VkImageView input, VkImageView output, Texture *t,
                          uint32_t level, uint64_t, const char *, bool temporal) {
    assert(input == (VkImageView)101 && output == (VkImageView)102 && t == &dst && level == 0 &&
           !temporal && lock_depth > 0);
    typed_calls++;
    return pipeline_ok;
}
void vkCmdBlitImage(VkCommandBuffer, VkImage a, VkImageLayout al, VkImage b, VkImageLayout bl,
                    uint32_t n, const VkImageBlit *r, VkFilter filter) {
    assert(a == src.image && b == dst.image && al == VK_IMAGE_LAYOUT_GENERAL &&
           bl == VK_IMAGE_LAYOUT_GENERAL && n == 1 && filter == VK_FILTER_LINEAR);
    assert(r->srcSubresource.mipLevel == 0 && r->srcSubresource.baseArrayLayer == 0 &&
           r->dstSubresource.mipLevel == 0 && r->dstSubresource.baseArrayLayer == 0);
    assert(r->srcOffsets[1].x == 64 && r->srcOffsets[1].y == 32 && r->dstOffsets[1].x == (int32_t)dst.width &&
           r->dstOffsets[1].y == (int32_t)dst.height);
    blits++;
}
'''
SUFFIX = r'''
int main(int argc, char **argv) {
    assert(argc == 2 || argc == 3);
    const std::string mode = argv[1];
    // ((Triforce, 11-22, GPUWORK-21) "off": run with RX_VK_STUB_SAME_SIZE=0, where everything is as it was before the rule)
    const bool rule = !(argc == 3 && std::string(argv[2]) == "off");
    const bool same = mode == "same" || mode == "9dc-same" || mode == "fd-same";
    uint64_t key = 0x0775215f8da720e6ull;
    destination.gpu = 20;
    destination.d.format = 63;
    destination.d.width = 128;
    destination.d.height = 64;
    dst.width = 128;
    dst.height = 64;
    dst.image = (VkImage)22;
    if (mode == "r11" || mode == "fd-r11")
        source.d.format = 63;
    if (mode == "movie") {
        dst.format = VK_FORMAT_R8G8B8A8_UNORM;
        movie = true;
    }
    if (mode == "view" || mode == "fd-view")
        override_view = true;
    if (mode == "skip")
        src.skip = 1;
    if (mode == "mip")
        src.levels = 2;
    if (mode == "swizzle")
        source.d.swizzle_r = 4;
    if (mode.compare(0, 2, "fd") == 0)
        key = 0xfd029a317a9a4b94ull;
    if (mode.compare(0, 3, "9dc") == 0)
        key = 0x9dc98871eb7fc101ull;
    if (same) {   // (the output as large as the input: the network of Render resolution 100%)
        destination.d.width = 64, destination.d.height = 32;
        dst.width = 64, dst.height = 32;
    }
    if (mode == "pipeline-failure" || mode == "fd-pipeline-failure" || mode == "9dc-pipeline-failure")
        pipeline_ok = false;
    if (mode == "no-storage" || mode == "fd-no-storage")
        missing_storage = true;
    if (mode == "no-e5-sample" || mode == "fd-no-e5-sample")
        missing_sample = true;
    if (mode == "no-e5-linear" || mode == "fd-no-e5-linear")
        missing_linear = true;
    if (mode == "null-input-view" || mode == "fd-null-input-view")
        missing_input_view = true;
    if (mode == "null-output-view" || mode == "fd-null-output-view")
        missing_output_view = true;
    if (mode == "fsr3")
        fsr3_on = true;
    NvnState state;
    state.tex[5][0] = 1;
    state.img[5][0] = 2;
    // ((Triforce, 11-22, GPUWORK-21) the same size: a gameplay network is stood in for, any other program declined; with the
    // rule off every one is declined, as before, and nothing is drawn or written)
    const bool taken = upscale_stub((VkCommandBuffer)5, state, key);
    if (same && !(rule && mode != "same")) {
        assert(!taken && typed_calls == 0 && blits == 0 && writes == 0 && views == 0 && movie_calls == 0);
        printf("PASS: %s declined%s\n", mode.c_str(), rule ? "" : " (RX_VK_STUB_SAME_SIZE=0)");
        return 0;
    }
    assert(taken);
    if (rule && (mode == "9dc" || mode == "9dc-same" || mode == "fd-same")) {
        // (both gameplay networks through the typed upscale, at either size: nothing blitted)
        assert(typed_calls == 1 && views == 2 && blits == 0 && writes == 1 && gameplay_warnings == 0);
        assert(gameplay_logs == (mode == "fd-same" ? 1u : 0u));
    } else if (mode == "9dc-pipeline-failure") {
        // (the typed upscale could not be made: the blit, and with the rule its warning of wrong colours; without it
        // 9dc98871 never asked for the typed upscale)
        assert(typed_calls == (rule ? 1u : 0u) && views == (rule ? 2u : 0u) && blits == 1 && writes == 1);
        assert(gameplay_warnings == (rule ? 1u : 0u) && gameplay_logs == 0);
    } else if (mode == "captured" || mode == "fd") {
        if (typed_calls != 1 || views != 2 || blits != 0) {
            puts("RED: RGB9E5 input still used physical-format blit");
            return 7;
        }
        assert(writes == 1);
        assert(gameplay_logs == (mode == "fd" ? 1u : 0u) && gameplay_warnings == 0);
    } else if (mode == "fsr3") {
        assert(fsr3_calls == 1 && views == 2 && typed_calls == 0 && blits == 0);
    } else if (mode == "movie") {
        assert(movie_calls == 1 && typed_calls == 0 && blits == 0 && writes == 1);
    } else if (mode == "pipeline-failure" || mode == "fd-pipeline-failure") {
        assert(typed_calls == 1 && views == 2 && blits == 1 && writes == 1);
    } else if (missing_input_view || missing_output_view) {
        assert(typed_calls == 0 && views == 2 && blits == 1 && writes == 1);
    } else {
        assert(typed_calls == 0 && views == 0 && blits == 1 && writes == 1);
    }
    if (mode == "fd-view" || mode == "fd-pipeline-failure" || mode == "fd-no-storage" ||
        mode == "fd-no-e5-sample" || mode == "fd-no-e5-linear" ||
        mode == "fd-null-input-view" || mode == "fd-null-output-view")
        assert(gameplay_warnings == 1 && gameplay_logs == 0);
    if (mode == "fd-r11" || mode == "9dc")
        assert(gameplay_warnings == 0 && gameplay_logs == 0);
    if (mode == "9dc" && !rule) assert(typed_calls == 0 && blits == 1);   // (as before: the encoded bits blitted)
    printf("PASS: %s\n", mode.c_str());
}
'''

RULE = r'''
#include "stub_same_size.h"
#include <cstdio>
using namespace stub_same_size;
// (the rule as constants: it decides at compile time)
static_assert(sized(8192, 2048, false, false) && sized(8192, 2048, false, true), "an upscale's last pass is taken");
static_assert(sized(2048, 2048, true, true), "a gameplay network at its input's size is taken");
static_assert(!sized(2048, 2048, true, false), "not with the rule off");
static_assert(!sized(2048, 2048, false, true), "not a program that is no gameplay network");
static_assert(!sized(1024, 2048, true, true) && !sized(1024, 2048, false, false), "an output smaller than its input never");
static_assert(!sized(0, 0, true, true), "nothing written is not taken");
static_assert(typed(false, false, false) && typed(false, false, true), "a program that is no gameplay network asks for the typed upscale");
static_assert(typed(true, true, false) && typed(true, true, true), "the 3/4 network does");
static_assert(typed(true, false, true) && !typed(true, false, false), "the other gameplay network only with the rule");
static_assert(warns(true, true, false) && warns(true, true, true) && warns(true, false, true), "the gameplay networks' blit warns");
static_assert(!warns(true, false, false) && !warns(false, false, true) && !warns(false, false, false), "and no other");
int main() {
    const bool ok = on(nullptr) && on("1") && !on("0") && on("2");
    std::puts(ok ? "PASS: the rule" : "FAIL: RX_VK_STUB_SAME_SIZE is not on unless 0");
    return !ok;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'gpu/vk/vk_draw.cpp')
    parser.add_argument('--cxx', default='clang++')
    args = parser.parse_args()
    body = block(args.source.read_text(encoding='utf-8'), 'bool upscale_stub(')
    env = os.environ.copy()
    env.pop('RX_VK_NO_UPSCALE_STUB', None)
    env.pop('RX_VK_STUB_SAME_SIZE', None)
    # ((Triforce, 11-22, GPUWORK-21) the rule's hooks, and its switch read once)
    for line in ('static const bool same_size = stub_same_size::on(getenv("RX_VK_STUB_SAME_SIZE"));',
                 'if (!stub_same_size::sized(out_area, in_area, gameplay, same_size))',
                 'if (stub_same_size::typed(gameplay, gameplay_taau, same_size) && in.d.format == NVN_FORMAT_RGB9E5F',
                 'if (stub_same_size::warns(gameplay, gameplay_taau, same_size) && in.d.format == NVN_FORMAT_RGB9E5F'):
        if line not in body:
            raise SystemExit('upscale_stub lost: ' + line)
    if 'static const bool off = getenv("RX_VK_NO_UPSCALE_STUB") != nullptr;' not in body:
        raise SystemExit('RX_VK_NO_UPSCALE_STUB no longer turns the stub off')
    docs = (ROOT / 'docs/development.md').read_text(encoding='utf-8')
    if '`RX_VK_STUB_SAME_SIZE=0`' not in docs or '`gpu/vk/stub_same_size.h`' not in docs:
        raise SystemExit('docs/development.md: the switches table has no RX_VK_STUB_SAME_SIZE row')
    with tempfile.TemporaryDirectory(prefix='upscale-fallback-') as tmp:
        tmp = Path(tmp)
        source = tmp / 'check.cpp'
        exe = tmp / ('check.exe' if os.name == 'nt' else 'check')
        source.write_text(PREFIX + body + SUFFIX, encoding='utf-8')
        if Path(args.cxx).name.lower() in ('cl', 'cl.exe', 'clang-cl', 'clang-cl.exe'):
            command = [args.cxx, '/nologo', '/std:c++20', '/EHsc', '/UNDEBUG', '/I' + str(ROOT / 'gpu/vk'), str(source),
                       '/Fo' + str(tmp / 'check.obj'), '/Fe' + str(exe)]
            cwd = tmp
        else:
            command = [args.cxx, '-std=c++20', '-UNDEBUG', '-I' + str(ROOT / 'gpu/vk'), str(source), '-o', str(exe)]
            cwd = None
        subprocess.run(command, cwd=cwd, env=env, check=True)
        cases = ('captured', 'r11', 'movie', 'view', 'skip', 'mip', 'swizzle', 'fd', 'fd-r11',
                 'fd-view', 'fd-pipeline-failure', 'fd-no-storage', 'fd-no-e5-sample',
                 'fd-no-e5-linear', 'fd-null-input-view', 'fd-null-output-view', '9dc',
                 'pipeline-failure', 'no-storage', 'no-e5-sample', 'no-e5-linear',
                 'null-input-view', 'null-output-view', 'fsr3',
                 '9dc-same', 'fd-same', 'same', '9dc-pipeline-failure')   # ((Triforce, 11-22, GPUWORK-21))
        for case in cases:
            subprocess.run([str(exe), case], env=env, check=True)
        # (and all of them as before the rule: RX_VK_STUB_SAME_SIZE=0)
        for case in cases:
            subprocess.run([str(exe), case, 'off'], env={**env, 'RX_VK_STUB_SAME_SIZE': '0'}, check=True, stdout=subprocess.DEVNULL)
        # (the rule itself)
        rule = tmp / 'rule.cpp'
        rule.write_text(RULE, encoding='utf-8')
        rule_exe = tmp / ('rule.exe' if os.name == 'nt' else 'rule')
        if Path(args.cxx).name.lower() in ('cl', 'cl.exe', 'clang-cl', 'clang-cl.exe'):
            subprocess.run([args.cxx, '/nologo', '/std:c++20', '/EHsc', '/I' + str(ROOT / 'gpu/vk'), str(rule),
                            '/Fo' + str(tmp / 'rule.obj'), '/Fe' + str(rule_exe)], cwd=tmp, env=env, check=True)
        else:
            subprocess.run([args.cxx, '-std=c++20', '-I' + str(ROOT / 'gpu/vk'), str(rule), '-o', str(rule_exe)], env=env, check=True)
        subprocess.run([str(rule_exe)], env=env, check=True)

if __name__ == '__main__':
    main()
