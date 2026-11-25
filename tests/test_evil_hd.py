"""(Triforce, 11-23) Evil HD (gpu/vk/evil_hd.h): the Graphics tab's one switch for a powerful PC. No game, no GPU.

Compiles and runs the header's rules (SMAA Ultra, 16x, Full, the far foliage shadows whole while on; each row's own value
while off), then reads the source for where they apply: the Anti-aliasing choice (vk_aa.cpp choice_now), the samplers'
filtering (vk_draw.cpp sampler_for), the Texture detail at the start (vk_menu.cpp), the foliage shadow cull and shading rate
(vk_draw.cpp draw_cull, draw_rate), the row on the Graphics tab, its key (evil_hd) and the notes the rows it covers show.

    python -I -B tests/test_evil_hd.py [--cxx g++]
"""
import argparse
import hashlib
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

RULES = r'''
#include <cstdio>
#include <cstdlib>
#include "aa_rows.h"
#include "evil_hd.h"
#include "tex_detail.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace mkwvk;
int main() {
    static_assert(evil_hd::kAa == aa_rows::SMAA, "Evil HD's anti-aliasing is SMAA Ultra");
    CHECK(std::string_view(aa_rows::name(evil_hd::kAa)) == "SMAA Ultra");
    for (int row = 0; row < aa_rows::kValues; row++) {
        CHECK(evil_hd::aa(0, row) == row);
        CHECK(evil_hd::aa(1, row) == aa_rows::SMAA);
    }
    for (int row = 0; row <= 4; row++) {
        CHECK(evil_hd::aniso(0, row) == row);
        CHECK(evil_hd::aniso(1, row) == 4);
    }
    for (int row = 0; row <= 3; row++) {
        CHECK(evil_hd::tex_detail(0, row) == row);
        CHECK(tex_detail::from_row(evil_hd::tex_detail(1, row)) == tex_detail::kFull);
    }
    for (int from = -1; from <= 3; from++) {
        CHECK(evil_hd::foliage_from(0, from) == from);
        CHECK(evil_hd::foliage_from(1, from) < 0);
    }
    std::printf("PASS: Evil HD's rules: SMAA Ultra, 16x, Full and the foliage shadows whole while on, each row's own while off\n");
}
'''


SHADERS = ROOT / "gpu" / "vk" / "shaders"
AO_SHADERS = ("evil_ao", "evil_ao_apply", "evil_shafts")


def shader_digest(name):
    """The sources a header is made from: the .comp and the aa_common.glsl it may include, their bytes one after the other"""
    return hashlib.sha256((SHADERS / (name + ".comp")).read_bytes() + bytes(1) + (SHADERS / "aa_common.glsl").read_bytes()).hexdigest()


def write_headers(glslang):
    """--write: each shader's header again from its source (glslangValidator -V --target-env vulkan1.2), the digest first"""
    for name in AO_SHADERS:
        var = name.upper() + "_COMP_SPV"
        with tempfile.TemporaryDirectory(prefix="evil-ao-") as tmp:
            out = Path(tmp) / "h"
            subprocess.run([glslang, "-V", "--target-env", "vulkan1.2", "-I" + str(SHADERS), "--vn", var, "-o", str(out),
                            str(SHADERS / (name + ".comp"))], check=True, stdout=subprocess.DEVNULL)
            body = out.read_text(encoding="utf-8")
        (SHADERS / (name + "_comp_spv.h")).write_text(
            f"// {name}.comp + aa_common.glsl sha256 {shader_digest(name)} (tests/test_evil_hd.py --write: glslangValidator -V "
            f"--target-env vulkan1.2 --vn {var})" + chr(10) + body, encoding="utf-8", newline=chr(10))
        print("wrote shaders/" + name + "_comp_spv.h")


def need(text, piece, what):
    if piece not in text:
        raise SystemExit("FAIL: " + what)


def check_source():
    vk = ROOT / "gpu" / "vk"
    aa = (vk / "vk_aa.cpp").read_text(encoding="utf-8")
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    menu = (vk / "vk_menu.cpp").read_text(encoding="utf-8")
    header = (vk / "vk_menu.h").read_text(encoding="utf-8")
    need(header, "int evil_hd = 0;", "vk_menu.h: no opts.evil_hd, off by default")
    need(aa, "ar::chosen(evil_hd::aa(evil_hd_now(), opts.aa), env_choice())", "vk_aa.cpp choice_now: not Evil HD's anti-aliasing")
    need(draw, "evil_hd::aniso(evil_hd_now(), opts.aniso)", "vk_draw.cpp sampler_for: not Evil HD's filtering")
    need(draw, "if (evil_hd::foliage_from(evil_hd_now(), rule.from) < 0) return game;", "vk_draw.cpp draw_cull: not Evil HD's")
    need(draw, "foliage_shadow::rate(evil_hd::foliage_from(evil_hd_now(), from)", "vk_draw.cpp draw_rate: not Evil HD's")
    need(menu, "tex_detail_at_start = evil_hd::tex_detail(opts.evil_hd, opts.tex_detail);",
         "vk_menu.cpp: the Texture detail at the start is not Evil HD's")
    need(menu, '{TAB_GRAPHICS, "Evil HD", &opts.evil_hd, 0, 1, 1, tx_onoff,', "vk_menu.cpp: no Evil HD row on the Graphics tab")
    graphics = menu.index("// ---- Graphics: the picture, top to bottom ----")
    if not graphics < menu.index('{TAB_GRAPHICS, "Evil HD"') < menu.index('MENU_HEADING(TAB_GRAPHICS, "Upscaling")'):
        raise SystemExit("FAIL: vk_menu.cpp: the Evil HD row is not the Graphics tab's first")
    for note in ("Evil HD is on: SMAA Ultra", "Evil HD is on: 16x", "Evil HD is on: Full from the next start"):
        need(menu, note, "vk_menu.cpp: the note '" + note + "' is missing")
    need(menu, "sharpest, at a small cost.\", hn_aniso},", "vk_menu.cpp: the Texture filtering row has no Evil HD note")
    # ((Triforce, 11-24) F2 turns the row's own value, saved, with a notice; the row's help says so)
    need(menu, "GetAsyncKeyState(VK_F2) & 0x8000", "vk_menu.cpp: no F2 key for Evil HD")
    need(menu, "opts.evil_hd = opts.evil_hd ? 0 : 1;" + chr(10) + "            save();",
         "vk_menu.cpp: F2 does not turn the row's value and save it")
    need(menu, "F2 turns it on and off.", "vk_menu.cpp: the Evil HD row's help does not name F2")
    print("PASS: Evil HD's row, its key and where it applies")


def check_ao():
    """The ambient occlusion: its passes in vk_aa.cpp after the picture is stored (both ways: the post pass and SMAA's blend),
    the camera's depth gate, and the two shader headers made from today's sources (their first line's hash: sha256sum of
    the .comp and aa_common.glsl, hashed again, as the build note in each says)"""
    vk = ROOT / "gpu" / "vk"
    aa = (vk / "vk_aa.cpp").read_text(encoding="utf-8")
    temporal = (vk / "vk_temporal.cpp").read_text(encoding="utf-8")
    if aa.count("if (evil_hd_now()) ao_after(s, cmd, src, dst, w, h);") != 2:
        raise SystemExit("FAIL: vk_aa.cpp aa_record: the ambient occlusion does not follow both ways of storing the picture")
    need(temporal, "pre_wanted(ur::GAME) || evil_hd_now()", "vk_temporal.cpp: the scene's camera is not noted for Evil HD")
    need(aa, "const PassInfo kPasses[P_N]", "vk_aa.cpp: the pass table moved")
    for name in AO_SHADERS:
        first = (SHADERS / (name + "_comp_spv.h")).read_text(encoding="utf-8").splitlines()[0]
        if shader_digest(name) not in first:
            raise SystemExit(f"FAIL: shaders/{name}_comp_spv.h is not made from today's {name}.comp: tests/test_evil_hd.py --write")
    print("PASS: Evil HD's ambient occlusion: where it runs, the camera it needs, its shaders up to date")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    p.add_argument("--write", metavar="GLSLANG", help="make the ambient occlusion's shader headers again with this glslangValidator")
    a = p.parse_args()
    if a.write:
        write_headers(a.write)
    check_source()
    check_ao()
    with tempfile.TemporaryDirectory(prefix="evil-hd-") as tmp:
        cpp, exe = Path(tmp) / "rules.cpp", Path(tmp) / "rules.exe"
        cpp.write_text(RULES.replace("#include <cstdio>", "#include <cstdio>\n#include <string_view>"), encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu" / "vk"), str(cpp), "-o",
                        str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=30)
    print("PASS: Evil HD")


if __name__ == "__main__":
    main()
