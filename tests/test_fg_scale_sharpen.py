"""The window pass's Sharpness (gpu/vk/shaders/fg_scale.comp): its neighbours are one picture (source) pixel apart, not one
window pixel (inside the same picture pixel when the window is the larger, so Sharpness did next to nothing), and its
per-pixel math, the shader's own sharpen() compiled as C++, is the picture unchanged at 0, never past the lightest or
darkest pixel around it nor outside 0..1 (no halos, no clipping) at any setting, and steeper edges as the setting rises.
The shader's side_outside() is compiled too: full side fill outside the middle, with both soft edges wholly inside it.
fg_scale_comp_spv.h names the hash of the fg_scale.comp it was made from (its first line), checked against the shader as it
is now with or without glslang; with glslangValidator the shader compiles, and with the version the header names, the rest of
the header is its output byte for byte. --write makes the header: glslang's output with that line on top.

python -I -B tests/test_fg_scale_sharpen.py [--cxx g++] [--glslang glslangValidator] [--write]
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]
SHADERS = ROOT / "gpu" / "vk" / "shaders"


def source_line(comp):
    """the header's first line: the shader's hash (line ends as LF, as the checkout has them) and how the header is made"""
    digest = hashlib.sha256(comp.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return ("// fg_scale.comp sha256 %s (tests/test_fg_scale_sharpen.py --write: glslangValidator -V --target-env vulkan1.2 "
            "--vn FG_SCALE_COMP_SPV)\n" % digest).encode()


def compile_header(glslang, comp, out):
    r = subprocess.run([glslang, "-V", "--target-env", "vulkan1.2", "--vn", "FG_SCALE_COMP_SPV", "-o", str(out), str(comp)],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("fg_scale.comp does not compile:\n" + r.stdout + r.stderr)
    return out.read_bytes()


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


# (just enough of GLSL's vec3 for sharpen())
SHIM = r'''
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
struct vec3 {
    float r, g, b;
    vec3() : r(0), g(0), b(0) {}
    explicit vec3(float v) : r(v), g(v), b(v) {}
    vec3(float x, float y, float z) : r(x), g(y), b(z) {}
};
static vec3 map2(vec3 a, vec3 b, float (*f)(float, float)) { return {f(a.r, b.r), f(a.g, b.g), f(a.b, b.b)}; }
static float fadd(float a, float b) { return a + b; }
static float fsub(float a, float b) { return a - b; }
static float fmul(float a, float b) { return a * b; }
static float fdiv(float a, float b) { return a / b; }
static float fmin_(float a, float b) { return std::min(a, b); }
static float fmax_(float a, float b) { return std::max(a, b); }
static vec3 operator+(vec3 a, vec3 b) { return map2(a, b, fadd); }
static vec3 operator-(vec3 a, vec3 b) { return map2(a, b, fsub); }
static vec3 operator*(vec3 a, vec3 b) { return map2(a, b, fmul); }
static vec3 operator/(vec3 a, vec3 b) { return map2(a, b, fdiv); }
static vec3 operator+(float a, vec3 b) { return vec3(a) + b; }
static vec3 operator-(float a, vec3 b) { return vec3(a) - b; }
static vec3 operator*(float a, vec3 b) { return vec3(a) * b; }
static vec3 operator/(vec3 a, float b) { return a / vec3(b); }
static vec3 min(vec3 a, vec3 b) { return map2(a, b, fmin_); }
static vec3 max(vec3 a, vec3 b) { return map2(a, b, fmax_); }
static float min(float a, float b) { return std::min(a, b); }
static float max(float a, float b) { return std::max(a, b); }
static float clamp(float v, float lo, float hi) { return std::min(std::max(v, lo), hi); }
static vec3 clamp(vec3 v, vec3 lo, vec3 hi) { return min(max(v, lo), hi); }
static float smoothstep(float lo, float hi, float x) {
    const float t = clamp((x - lo) / (hi - lo), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}
'''

FIXTURE = r'''
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
static unsigned seed = 12345;
static float rnd() { seed = seed * 1664525u + 1013904223u; return (seed >> 8) / 16777216.0f; }
static vec3 rnd3() { return {rnd(), rnd(), rnd()}; }
static float ch(vec3 v, int i) { return i == 0 ? v.r : i == 1 ? v.g : v.b; }
// a blurred edge (the picture as it reaches the window pass), sampled one picture pixel apart around x
static float edge(float x) { return 0.1f + 0.8f / (1.0f + std::exp(-2.0f * x)); }
static void check_sides() {
    // Player's 3840x1600, both fixed wide pictures, and the normalized pixel-cap picture.
    const int pictures[][2] = {{3840, 2848}, {5120, 2560}, {5120, 3840}, {7224, 3616}};
    const float feather = 0.006f;
    for (const auto& picture : pictures) {
        const int width = picture[0];
        const float x0 = float(width - picture[1]) / (2.0f * width), x1 = 1.0f - x0;
        float previous = 1.0f;
        for (int pixel = 0; pixel < width; ++pixel) {
            const float x = (pixel + 0.5f) / width;
            const float outside = side_outside(x, x0, x1);
            CHECK(outside >= 0.0f && outside <= 1.0f);
            if (x <= x0 || x >= x1) CHECK(outside == 1.0f);
            else if (x >= x0 + feather && x <= x1 - feather) CHECK(outside == 0.0f);
            else CHECK(outside > 0.0f && outside < 1.0f);
            if (x < 0.5f) CHECK(outside <= previous);
            else CHECK(outside >= previous);
            previous = outside;
        }
        CHECK(side_outside(x0, x0, x1) == 1.0f);
        CHECK(side_outside(x1, x0, x1) == 1.0f);
        CHECK(side_outside(x0 + feather, x0, x1) == 0.0f);
        CHECK(side_outside(x1 - feather, x0, x1) == 0.0f);
        CHECK(std::abs(side_outside(x0 + feather * 0.5f, x0, x1) - 0.5f) < 1e-4f);
        CHECK(std::abs(side_outside(x1 - feather * 0.5f, x0, x1) - 0.5f) < 1e-4f);
    }
    std::puts("PASS: side fill is whole outside the middle; monotonic 0.006 soft edges stay inside at 3840, 5120 and 7224");
}
int main() {
    check_sides();
    const float amounts[] = {0.0f, 0.1f, 0.4f, 0.8f, 1.0f};
    for (int i = 0; i < 200000; i++) {
        const vec3 c = rnd3(), n = rnd3(), s = rnd3(), w = rnd3(), e = rnd3();
        for (float a : amounts) {
            const vec3 o = sharpen(c, n, s, w, e, a);
            for (int k = 0; k < 3; k++) {
                const float lo = std::min({ch(c, k), ch(n, k), ch(s, k), ch(w, k), ch(e, k)});
                const float hi = std::max({ch(c, k), ch(n, k), ch(s, k), ch(w, k), ch(e, k)});
                CHECK(ch(o, k) >= lo - 1e-6f && ch(o, k) <= hi + 1e-6f);   // no halo: inside the neighbourhood
                CHECK(ch(o, k) >= 0.0f && ch(o, k) <= 1.0f);                 // no clipping
                CHECK(std::isfinite(ch(o, k)));
                if (a == 0.0f) CHECK(ch(o, k) == ch(c, k));                  // 0: the picture unchanged
            }
        }
    }
    // flat light, black and white stay as they are at full strength
    for (float v : {0.0f, 0.5f, 1.0f}) {
        const vec3 o = sharpen(vec3(v), vec3(v), vec3(v), vec3(v), vec3(v), 1.0f);
        CHECK(o.r == v && o.g == v && o.b == v);
    }
    // a blurred edge gets steeper as the setting rises: the pixel on the light side lighter, never past the light beyond it
    float last = edge(0.6f);
    for (float a : {0.25f, 0.5f, 0.75f, 1.0f}) {
        const vec3 c(edge(0.6f)), mid(edge(0.6f));
        const vec3 o = sharpen(c, mid, mid, vec3(edge(-0.4f)), vec3(edge(1.6f)), a);
        CHECK(o.r > last && o.r <= edge(1.6f));
        last = o.r;
    }
    CHECK(last - edge(0.6f) > 0.01f);   // (a visible step, not a rounding)
    std::printf("PASS: sharpen() is the picture at 0, stays inside its neighbourhood and 0..1, and steepens edges with the setting\n");
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    p.add_argument("--glslang", default="glslangValidator")
    p.add_argument("--write", action="store_true", help="make fg_scale_comp_spv.h from fg_scale.comp")
    a = p.parse_args()
    comp = SHADERS / "fg_scale.comp"
    header_path = SHADERS / "fg_scale_comp_spv.h"
    if a.write:
        glslang = shutil.which(a.glslang)
        if not glslang:
            raise SystemExit("--write needs %s" % a.glslang)
        with tempfile.TemporaryDirectory(prefix="fg-sharpen-") as tmp:
            header_path.write_bytes(source_line(comp) + compile_header(glslang, comp, Path(tmp) / "out.h"))
        print("wrote %s" % header_path)
        return
    header = header_path.read_bytes()
    first, _, hbody = header.partition(b"\n")
    if first + b"\n" != source_line(comp):
        raise SystemExit("fg_scale_comp_spv.h was not made from this fg_scale.comp (its first line names another hash): "
                         "python -I -B tests/test_fg_scale_sharpen.py --write")
    text = comp.read_text(encoding="utf-8")
    body = block(text, "void main()")
    sharp = body[body.index("if (pc.sharp > 0.0)"):]
    if "textureSize(src, 0)" not in sharp:
        raise SystemExit("the sharpen's neighbours are not spaced by the picture's size (textureSize(src, 0))")
    spacing = re.search(r"const vec2 e = ([^;]*);", sharp)
    if not spacing or "textureSize(src, 0)" not in spacing.group(1):
        raise SystemExit("the neighbour spacing e is not one picture pixel")
    for tap in ("uv + vec2(0.0, -e.y)", "uv + vec2(0.0, e.y)", "uv + vec2(-e.x, 0.0)", "uv + vec2(e.x, 0.0)"):
        if tap not in sharp:
            raise SystemExit("missing the neighbour at %s" % tap)
    lobe = re.search(r"const float kMaxLobe = [^;]*;", text).group(0)
    fn = block(text, "vec3 sharpen(")
    sides = block(text, "float side_outside(")
    side_branch = block(body, "if (pc.side != 0 && pc.x1 > pc.x0)")
    if "outside = side_outside(uv.x, pc.x0, pc.x1);" not in side_branch:
        raise SystemExit("the side pass does not use the tested side_outside rule")
    fixture = SHIM + lobe.replace("const float", "static const float") + "\nstatic " + fn + "\nstatic " + sides + FIXTURE
    with tempfile.TemporaryDirectory(prefix="fg-sharpen-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / "fixture"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Wno-unused-function", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
        glslang = shutil.which(a.glslang)
        if not glslang:
            print("PASS: the header names this shader (no %s: its compile not checked)" % a.glslang)
            return
        made = compile_header(glslang, comp, Path(tmp) / "fg_scale_comp_spv.h")
        if made.splitlines()[0] != hbody.splitlines()[0]:
            print("PASS: the header names this shader, and it compiles (glslang %s, the header's is %s: bytes not compared)" %
                  (made.splitlines()[0].decode().strip(), hbody.splitlines()[0].decode().strip()))
            return
        if made != hbody:
            raise SystemExit("fg_scale_comp_spv.h is not fg_scale.comp compiled: python -I -B tests/test_fg_scale_sharpen.py --write")
        print("PASS: fg_scale_comp_spv.h is fg_scale.comp compiled")


if __name__ == "__main__":
    main()
