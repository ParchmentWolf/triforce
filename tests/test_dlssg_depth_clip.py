"""NVIDIA DLSS frame generation's camera matrices are in the clip space of the depth it is given (gpu/vk/dlss_math.h
depth_clip_projection and depth_clip_reprojection, vk_dlssg.cpp frame, fsr3_math.h Camera::flip_depth; no game, no GPU).

(Triforce, 11-20) The owner's "DLSS flicker": the whole picture and the shadows flickered while the camera moved, with
NVIDIA DLSS frame generation on and not without it. Streamline takes its matrices in the clip space of its depth buffer:
the depth is clip z over w, 1 at the near plane with depthInverted. It was given the game's own projection and
reprojection, whose clip z is NVN's (-1 at the near plane, 1 at the far one), beside FSR's copy of the depth (1 at the
near plane, 0 far). Read with those matrices, that depth put what is far a fifth of a metre from the camera and what is
near at the far plane: wrong for everything as soon as the camera moved, and right while it stood. Only DLSS frame
generation takes matrices, so no other path showed it.

This compiles dlss_math.h and fsr3_math.h alone and checks, with the game's projection (near 0.1, far 1000.53, 45
degrees) and two cameras a step and a turn apart:

- a point's clip z over w through depth_clip_projection is the depth FSR's copy holds for it (1 - d where the game's
  buffer has 0 at the near plane; d itself where it is reversed already), 1 at the near plane and 0 at the far one;
- with the game's own matrix that depth is not the point's clip z (the error the flicker came from);
- a pixel and its depth through depth_clip_reprojection land on the same pixel of the frame before as the game's own
  reprojection puts the point, with the frame before's depth; the identity (a reset) stays the identity;
- Streamline's linear depth for an inverted buffer, 1 / depth, grows with the distance.

And reads the source: frame gives Streamline the converted matrices and their inverses, by the frame's flip_depth, with
depthInverted, and RX_VK_DLSSG_CLIP=0 is in the switches table.

    python -I -B tests/test_dlssg_depth_clip.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cfloat>
#include <cmath>
#include <cstdio>
#include <cstring>
#include "dlss_math.h"
#include "fsr3_math.h"
using namespace mkwvk;
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static bool near(double a, double b, double tol) { return std::fabs(a - b) <= tol; }
static void mul(const float a[16], const float b[16], float out[16]) {
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 4; c++) {
            double v = 0;
            for (int k = 0; k < 4; k++) v += (double)a[r * 4 + k] * b[k * 4 + c];
            out[r * 4 + c] = (float)v;
        }
}
static void apply(const float m[16], const double p[4], double out[4]) {
    for (int r = 0; r < 4; r++) out[r] = m[r * 4] * p[0] + m[r * 4 + 1] * p[1] + m[r * 4 + 2] * p[2] + m[r * 4 + 3] * p[3];
}
/// NVN's projection, row major (clip = P * view position, the camera looking down -z): clip z -1 at near, 1 at far;
/// reversed: 1 at near, -1 at far (a buffer with 1 at the near plane)
static void projection(float p[16], float n, float f, bool reversed) {
    std::memset(p, 0, 16 * sizeof(float));
    const float t = 1.0f / std::tan(0.5f * 0.785398f);
    p[0] = t / 2.369f, p[5] = t;
    p[10] = -(f + n) / (f - n), p[11] = -2.0f * f * n / (f - n);
    if (reversed) p[10] = -p[10], p[11] = -p[11];
    p[14] = -1.0f;
}
/// A view matrix: a turn of a radians about y, then a move of the camera by (x, 0, z)
static void view(float v[16], float a, float x, float z) {
    std::memset(v, 0, 16 * sizeof(float));
    v[0] = std::cos(a), v[2] = -std::sin(a), v[5] = 1, v[8] = std::sin(a), v[10] = std::cos(a), v[15] = 1;
    v[3] = -(v[0] * x + v[2] * z), v[11] = -(v[8] * x + v[10] * z);
}

static void run(bool reversed) {
    const float n = 0.1f, f = 1000.53f;
    float p[16], vn[16], vb[16], cur[16], prev[16], game_to_prev[16], dp[16], dr[16];
    projection(p, n, f, reversed);
    view(vn, 0.02f, 0.3f, 0.1f), view(vb, 0.0f, 0.0f, 0.0f);   // (now: a small turn and a step; before: at the origin)
    mul(p, vn, cur), mul(p, vb, prev);
    CHECK(dlss_math::reprojection(cur, prev, game_to_prev));
    fsr3_math::Camera cam;
    CHECK(fsr3_math::camera_from_projection(p, cam));
    CHECK(cam.flip_depth == !reversed && near(cam.near_plane, n, 1e-4));
    dlss_math::depth_clip_projection(p, cam.flip_depth, dp);
    dlss_math::depth_clip_reprojection(game_to_prev, cam.flip_depth, dr);

    double last_linear = 0;
    const double dist[] = {0.1, 0.5, 2.0, 15.0, 120.0, 900.0, 1000.53};
    for (double v : dist) {
        // (a point v in front of this frame's camera, off the axis: in its view space)
        const double pv[4] = {0.31 * v, -0.17 * v, -v, 1.0};
        double c[4], d[4];
        apply(p, pv, c), apply(dp, pv, d);
        const double ndc = c[2] / c[3], stored = (ndc + 1.0) * 0.5;   // (the game's depth buffer: fsr3_math.h)
        const double copy = cam.flip_depth ? 1.0 - stored : stored;    // (FSR's copy: what frame generation is given)
        CHECK(near(d[2] / d[3], copy, 2e-5));
        CHECK(near(d[0] / d[3], c[0] / c[3], 1e-6) && near(d[1] / d[3], c[1] / c[3], 1e-6) && near(d[3], c[3], 1e-6));
        CHECK(copy > -1e-4 && copy < 1.0 + 1e-4);
        if (v > 0.2 && v < 900.0) CHECK(std::fabs(ndc - copy) > 0.3);   // (the game's clip z is not that depth)
        if (copy > 1e-6) {   // (Streamline's linear depth of an inverted buffer)
            CHECK(1.0 / copy > last_linear);
            last_linear = 1.0 / copy;
        }
        // (the pixel and its depth to the frame before: as the game's own reprojection puts the point)
        const double game_clip[4] = {c[0] / c[3], c[1] / c[3], ndc, 1.0}, depth_clip[4] = {c[0] / c[3], c[1] / c[3], copy, 1.0};
        double g[4], s[4];
        apply(game_to_prev, game_clip, g), apply(dr, depth_clip, s);
        CHECK(near(s[0] / s[3], g[0] / g[3], 2e-4) && near(s[1] / s[3], g[1] / g[3], 2e-4));
        const double before_stored = (g[2] / g[3] + 1.0) * 0.5, before_copy = cam.flip_depth ? 1.0 - before_stored : before_stored;
        CHECK(near(s[2] / s[3], before_copy, 2e-4));
        if (v > 0.5 && v < 120.0) {   // (and what the game's own matrix makes of that depth: somewhere else, by far more)
            double w[4];
            apply(game_to_prev, depth_clip, w);
            CHECK(std::fabs(w[0] / w[3] - g[0] / g[3]) > 20 * 2e-4);
        }
    }
    // (the near and far planes: 1 and 0)
    const double pn[4] = {0, 0, -n, 1}, pf[4] = {0, 0, -f, 1};
    double a[4], b[4];
    apply(dp, pn, a), apply(dp, pf, b);
    CHECK(near(a[2] / a[3], 1.0, 1e-4) && near(b[2] / b[3], 0.0, 1e-4));
    // (a reset: the identity stays the identity)
    float id[16], out[16];
    for (int i = 0; i < 16; i++) id[i] = i % 5 == 0 ? 1.0f : 0.0f;
    dlss_math::depth_clip_reprojection(id, cam.flip_depth, out);
    for (int i = 0; i < 16; i++) CHECK(near(out[i], id[i], 1e-6));
}

int main() {
    run(false);   // (the game's: 0 at the near plane, flipped for FSR's copy)
    run(true);    // (a buffer reversed already)
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()

    sl = (VK / "vk_dlssg.cpp").read_text(encoding="utf-8")
    frame = block(sl, "void frame(VkCommandBuffer cmd, uint32_t out_width, uint32_t out_height) {")
    check("dlss_math::depth_clip_projection(in.projection, in.camera.flip_depth, projection);" in frame and
          "dlss_math::depth_clip_reprojection(in.clip_to_prev, in.camera.flip_depth, clip_to_prev);" in frame,
          "frame: the matrices are not brought into the clip space of the depth Streamline is given")
    check("if (!inverse(projection, clip_to_view) || !inverse(clip_to_prev, prev_to_clip)) {" in frame,
          "frame: the inverses are not the converted matrices'")
    check("matrix(c.cameraViewToClip, projection);" in frame and "matrix(c.clipToPrevClip, clip_to_prev);" in frame and
          "matrix(c.clipToCameraView, clip_to_view);" in frame and "matrix(c.prevClipToClip, prev_to_clip);" in frame,
          "frame: Streamline is not given the converted matrices")
    check("matrix(c.cameraViewToClip, in.projection);" not in frame and "matrix(c.clipToPrevClip, in.clip_to_prev);" not in frame,
          "frame: Streamline is still given the game's own matrices")
    check("c.depthInverted = sl::Boolean::eTrue;" in frame, "frame: the depth is FSR's copy, 1 at the near plane")
    check('getenv("RX_VK_DLSSG_CLIP")' in frame, "frame: no switch for the game's own matrices, for comparing")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_DLSSG_CLIP=0`" in dev, "docs/development.md: RX_VK_DLSSG_CLIP=0 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="dlssg-depth-clip-") as tmp:
        src, exe = Path(tmp) / "clip.cpp", Path(tmp) / "clip.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the matrices in the depth's clip space:\n" + r.stdout)
    print("PASS: DLSS frame generation's matrices are in the clip space of the depth it is given")


if __name__ == "__main__":
    main()
