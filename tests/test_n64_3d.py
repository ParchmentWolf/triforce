"""N64 Classic's 3D pass (gpu/vk/shaders/n64_3d.comp; vk_draw.cpp n64_upscale and taau_stand_in) and what steps aside for
it while it draws: DLSS and FSR 4 (vk_temporal.cpp temporal_mode), FSR 3.1 (vk_fsr3.cpp fsr3_wanted) and the game's SMAA
(vk_aa.cpp). Step 2 of n64-classic-mode-plan.md, behind RX_VK_N64 (vk_n64.cpp). No game, no GPU.

n64_3d_comp_spv.h names the hash of the sources it was compiled from (n64_3d.comp and n64_common.glsl, its first line),
checked against the files as they are, with or without glslang; with glslangValidator of the version the header names,
the rest of the header is the pass compiled now, byte for byte. --write makes the header.

Read in the sources: the shader includes n64_common.glsl and keeps each channel with it on the grid's own pixels, takes
the square root encoding off the network's input, drops a texel that is not a number, and shows each output pixel from
its grid row whole and a place along it; n64_upscale's push constants are the shader's, in its order, its grid image is
RGBA16F storage made again at a new size, and its two dispatches have a barrier between; taau_stand_in asks n64_3d_now,
hands it to upscale_off.h, looks at the input for the grid's size, draws under the recording lock and still takes the
picture before the HUD; temporal_mode, fsr3_wanted and the Anti-aliasing row's choice ask n64_rules.h with
n64_in_front; vk_n64.cpp reads the switches and leaves a RenoDX run's RGBA16F scene alone; the development guide names
the switches. The rule each of these asks is run by tests/test_n64_rules.py and tests/test_upscale_off.py.

    python -I -B tests/test_n64_3d.py [--glslang glslangValidator] [--write]
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
SHADERS = VK / "shaders"
PARTS = ("n64_3d.comp", "n64_common.glsl")
HEADER = SHADERS / "n64_3d_comp_spv.h"
FLAGS = ["-V", "--target-env", "vulkan1.2", "--vn", "N64_3D_COMP_SPV"]


def fail(what):
    raise SystemExit("FAIL: " + what)


def source_line():
    """the header's first line: the hash of the pass's sources (each by its name and its bytes, line ends as LF) and how it is made"""
    digest = hashlib.sha256()
    for part in PARTS:
        digest.update(part.encode() + b"\0" + (SHADERS / part).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return ("// %s sha256 %s (tests/test_n64_3d.py --write: glslangValidator %s)\n"
            % (" + ".join(PARTS), digest.hexdigest(), " ".join(FLAGS))).encode()


def compiled(glslang, tmp):
    out = Path(tmp) / "n64_3d.h"
    r = subprocess.run([glslang, *FLAGS, "-o", str(out), str(SHADERS / "n64_3d.comp")], capture_output=True, text=True)
    if r.returncode:
        fail("n64_3d.comp does not compile:\n%s%s" % (r.stdout, r.stderr))
    return out.read_bytes().replace(b"\r\n", b"\n")


def glslang_version(glslang):
    got = subprocess.run([glslang, "--version"], capture_output=True, text=True).stdout
    m = re.search(r"Glslang Version: \d+:(\d+)\.(\d+)\.(\d+)", got)
    return m and "11%02d.%s.%s" % (int(m.group(1)), m.group(2), m.group(3))


def function(src, head):
    at = src.index(head)
    return src[at:src.index("\n}\n", at)]


def in_order(text, parts, what):
    at = [text.find(p) for p in parts]
    if min(at) < 0 or at != sorted(at):
        fail("%s: %s" % (what, [p for p, a in zip(parts, at) if a < 0] or at))


def check_shader():
    comp = (SHADERS / "n64_3d.comp").read_text(encoding="utf-8")
    in_order(comp, ['#extension GL_GOOGLE_include_directive : require', '#include "n64_common.glsl"', "void make(ivec2 g)",
                    "void show(ivec2 o)", "void main()"], "n64_3d.comp no longer includes n64_common.glsl before its two passes")
    make = function(comp, "void make(ivec2 g)")
    for need in ("for (int j = 0; j < 4; j++)", "for (int i = 0; i < 4; i++)", "vec3 c = s * s;",
                 "if (any(isnan(c)) || any(isinf(c))) c = vec3(0.0);", "n64_keep(c.r, pc.bits, pc.dither, g.x, g.y)",
                 "n64_keep(c.g, pc.bits, pc.dither, g.x, g.y)", "n64_keep(c.b, pc.bits, pc.dither, g.x, g.y)",
                 "imageStore(grid_img, g,"):
        if need not in make:
            fail("make: %s is gone (16 taps in linear light, no NaN, each channel kept on the grid's own pixel)" % need)
    show = function(comp, "void show(ivec2 o)")
    for need in ("n64_row(o.y, pc.grid.y, pc.size.y)", "n64_column(o.x, pc.grid.x, pc.size.x)", "imageLoad(grid_img,",
                 "mix(a, b, t)", "imageStore(dst, o,"):
        if need not in show:
            fail("show: %s is gone (a grid row whole, linear along it)" % need)
    push = re.search(r"layout\(push_constant\) uniform P \{(.*?)\} pc;", comp, re.S)
    fields = re.findall(r"^\s*(\w+) (\w+);", push.group(1), re.M) if push else []
    if fields != [("ivec2", "grid"), ("ivec2", "size"), ("int", "pass"), ("int", "bits"), ("float", "dither")]:
        fail("n64_3d.comp's push constants are not grid, size, pass, bits, dither: %s" % fields)
    for b in ("layout(binding = 0) uniform sampler2D src;", "layout(binding = 1, rgba16f) uniform image2D grid_img;",
              "layout(binding = 2, r11f_g11f_b10f) uniform writeonly image2D dst;"):
        if b not in comp:
            fail("n64_3d.comp: %s is not its binding" % b)


def check_draw():
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    for inc in ('#include "vk_n64.h"', '#include "shaders/n64_3d_comp_spv.h"'):
        if inc not in draw:
            fail("vk_draw.cpp does not %s" % inc)
    up = function(draw, "static bool n64_upscale(")
    for need in ("struct Push {\n        int32_t grid[2], size[2];\n        int32_t pass, bits;\n        float dither;\n    };",
                 "mi.codeSize = sizeof N64_3D_COMP_SPV, mi.pCode = N64_3D_COMP_SPV;",
                 "const VkPushConstantRange pr{VK_SHADER_STAGE_COMPUTE_BIT, 0, (uint32_t)sizeof(Push)};",
                 "const n64_rules::Grid g = n64_rules::grid(look.lines, ow, oh);",
                 "ic.format = VK_FORMAT_R16G16B16A16_SFLOAT", "ic.usage = VK_IMAGE_USAGE_STORAGE_BIT",
                 "if (texture_frame_no() - old[i].frame < 120)",
                 "Push pc{{(int32_t)g.w, (int32_t)g.h}, {(int32_t)ow, (int32_t)oh}, 0, look.colour_bits, look.dither};",
                 "descriptors_disturbed();"):
        if need not in up:
            fail("n64_upscale: %s is gone" % need.split("\n")[0])
    in_order(up, ["vkCmdDispatch(cmd, (g.w + 7) / 8, (g.h + 7) / 8, 1);", 'full_barrier(cmd, "barrier (N64 Classic\'s grid)");',
                  "pc.pass = 1;", "vkCmdDispatch(cmd, (ow + 7) / 8, (oh + 7) / 8, 1);"],
             "n64_upscale: the grid, a barrier, then the picture from it")
    stand = function(draw, "bool taau_stand_in(VkCommandBuffer cmd, const NvnState& s, const Program& p) {")
    in_order(stand, ["const bool n64 = n64_3d_now();", "const bool shaped = (off || n64) &&",
                     "upscale_off::choose(taau_key(p.key), off, gameplay_network(p.key), shaped, n64);",
                     "if (ch.by_shape || ch.n64) {", "ParLock lk;",
                     "if (ch.n64) done = n64_upscale(cmd, dw().imgs[0].imageView, in, dw().imgs[ntex].imageView, out, level);",
                     "if (done) hudless_after_dispatch(cmd, p.key);"],
             "taau_stand_in no longer asks n64_3d_now, looks at the input, draws N64 Classic's pass under the lock and takes the picture")


def check_asides():
    temporal = (VK / "vk_temporal.cpp").read_text(encoding="utf-8")
    mode = function(temporal, "int temporal_mode() {")
    in_order(mode, ["v = n64_rules::upscaler(n64_in_front(), v);", "if (!ur::is_dlss(v) && !ur::is_fsr4(v)) return ur::GAME;"],
             "temporal_mode: DLSS and FSR 4 no longer step aside for N64 Classic's 3D pass, over the switches too")
    fsr3 = function((VK / "vk_fsr3.cpp").read_text(encoding="utf-8"), "bool fsr3_wanted() {")
    in_order(fsr3, ["if (env == 0) return false;",
                    "if (n64_rules::upscaler(n64_in_front(), upscaler_rows::FSR3) != upscaler_rows::FSR3) return false;",
                    "return (env > 0 ||"], "fsr3_wanted: FSR 3.1 no longer steps aside for N64 Classic's 3D pass")
    aa = (VK / "vk_aa.cpp").read_text(encoding="utf-8")
    choice = function(aa, "int choice_now() {")
    if "return env_choice() >= 0 ? choice : n64_rules::anti_aliasing(n64_in_front(), choice);" not in choice:
        fail("vk_aa.cpp choice_now: the game's SMAA is no longer left out for N64 Classic's 3D pass, or RX_VK_AA no longer goes over it")
    if "const int choice = choice_now();" not in function(aa, "int aa_mode() {") or "bool aa_asked() { return choice_now() != ar::GAME ||" not in aa:
        fail("vk_aa.cpp: aa_mode and aa_asked no longer ask choice_now")
    n64 = (VK / "vk_n64.cpp").read_text(encoding="utf-8")
    for need in ('env_number("RX_VK_N64", -1)', 'env_number("RX_VK_N64_LINES", -1)', 'getenv("RX_VK_N64_LOD")',
                 'env_number("RX_VK_N64_TV", -1)', 'env_number("RX_VK_N64_MASK", -1)', 'env_number("RX_VK_N64_FPS", -1)',
                 "temporal_scene_format(VK_FORMAT_R16G16B16A16_SFLOAT)", "return n64_rules::three_d_runs(l, rgba16f);",
                 "int n64_in_front() { return n64_3d_now() ? n64_shown() : (int)n64_rules::OFF; }"):
        if need not in n64:
            fail("vk_n64.cpp: %s is gone" % need)
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if "`RX_VK_N64=<0..2>`" not in docs or "`RX_VK_N64_LINES=<n>`" not in docs:
        fail("docs/development.md: RX_VK_N64 and the lab's switches are not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--glslang", default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    glslang = args.glslang or shutil.which("glslangValidator")
    if args.write:
        if not glslang:
            fail("--write needs glslangValidator")
        with tempfile.TemporaryDirectory(prefix="n64-3d-") as tmp:
            HEADER.write_bytes(source_line() + compiled(glslang, tmp))
        print("wrote %s" % HEADER.relative_to(ROOT))
    check_shader()
    check_draw()
    check_asides()
    if not HEADER.exists():
        fail("n64_3d_comp_spv.h is missing: run with --write")
    header = HEADER.read_bytes().replace(b"\r\n", b"\n")
    first, _, rest = header.partition(b"\n")
    if first + b"\n" != source_line():
        fail("n64_3d_comp_spv.h was not made from n64_3d.comp and n64_common.glsl as they are now: run with --write")
    if glslang:
        named = rest.split(b"\n", 1)[0].decode("ascii", "replace").strip().lstrip("/ ").strip()
        if glslang_version(glslang) == named:
            with tempfile.TemporaryDirectory(prefix="n64-3d-") as tmp:
                if compiled(glslang, tmp) != rest:
                    fail("n64_3d_comp_spv.h is not n64_3d.comp compiled: run with --write")
            print("(the SPIR-V header is its source compiled, byte for byte)")
        else:
            print("(glslangValidator is not version %s: the header was not compiled again)" % named)
    else:
        print("(glslangValidator is not on the PATH: the header's hash was checked, not its bytes)")
    print("PASS: N64 Classic's 3D pass, its place in the gameplay upscale, and what steps aside for it")


if __name__ == "__main__":
    main()
