"""Compile the production render-target pool sizing function without game data.

The 305 MiB default crashed in Castle Town's guard house; 512 MiB resolved the
reported conversation/camera reproduction. Keep existing 4K/ultrawide growth
and explicit HOS_RT_POOL_MB overrides, including overrides below the floor; the 5120x2880
output's pool is kept to 900 MiB, and so is that of every output of more pixels than
3840x2160's, whether they are the frame's or the widescreen picture's.
"""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", help="C compiler (otherwise clang, gcc or cc from PATH)")
    parser.add_argument("--source", type=Path, default=ROOT / "host/nn_applet.c")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("null_pool", ROOT / "tests/test_nvn_null_pool.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    body = helpers.block(args.source.read_text(), "uint64_t hos_rt_pool_size(uint64_t game)")
    fixture = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MIB (UINT64_C(1) << 20)
volatile uint64_t hos_wide_out;
static unsigned output_width, output_height;
static const char *override;
static uint32_t hos_output_size(int height) { return height ? output_height : output_width; }
static void hos_log(const char *fmt, ...) { (void)fmt; }
static const char *fixture_env(const char *name) {
    if (strcmp(name, "HOS_RT_POOL_MB")) exit(2);
    return override;
}
#define getenv fixture_env
/* (local, RenoDX port: host/nn_vi.c's, whether the scene's colour target is RGBA16F for the run) */
static int scene_rgba16f;
int hos_scene_rgba16f(void) { return scene_rgba16f; }
/* ((Triforce, 11-21, TEX-85) host/nn_applet.c's, beside the function: whether the heap is held to a size, which it notes) */
static int rt_pool_pinned = -1;
''' + body + r'''
#define WIDE(w, h) ((uint64_t)(h) << 32 | (w))
static const struct {
    unsigned width, height;
    uint64_t wide, game_mib;
    const char *env;
    uint64_t expected_mib;
} cases[] = {
    {2560, 1440, 0, 305, NULL, 512},
    {3840, 2160, 0, 305, NULL, 687},
    {2560, 1440, WIDE(3440, 1440), 305, NULL, 512},
    {2560, 1440, WIDE(5120, 1440), 305, NULL, 610},
    /* ((Triforce) a 7680 x 2160 picture: the 1373 MiB it scales to failed the game's reservation at boot (host/hos_main.c),
       as every pool over 900 MiB has; host/hos_main.c no longer makes that picture either) */
    {3840, 2160, WIDE(7680, 2160), 305, NULL, 900},
    /* ((Triforce) a 5120 x 2160 picture with the frame 3840 x 2160, the Output resolution 5120x2160: 915 MiB scaled, kept to
       900 as the 5120 x 2160 frame before it; 3840 x 1600 and 5120 x 1440 pictures keep their scaled pools) */
    {3840, 2160, WIDE(5120, 2160), 305, NULL, 900},
    {3840, 2160, WIDE(5120, 2160), 305, "1000", 1000},
    {2848, 1600, WIDE(3840, 1600), 305, NULL, 512},
    {5120, 2880, WIDE(7224, 2032), 305, NULL, 900},
    {2560, 1440, WIDE(1920, 1080), 305, NULL, 512},
    {2560, 1440, 0, 305, "256", 256},
    {3840, 2160, WIDE(7680, 2160), 305, "768", 768},
    {2560, 1440, 0, 305, "0x200", 512},
    {2560, 1440, 0, 305, "0", 0},
    {2560, 1440, 0, 768, NULL, 768},
    {3840, 2160, 0, 768, NULL, 1728},
    {5120, 2880, 0, 305, NULL, 900},
    {5120, 2880, 0, 305, "1220", 1220},
    {5120, 2160, 0, 305, NULL, 900},   /* ((Triforce) the 5120 x 2160 output: 915 MiB scaled, kept to 900 as 5120 x 2880's) */
    {5120, 2160, 0, 305, "1000", 1000},
};
int main(void) {
    int failed = 0;
    for (unsigned i = 0; i < sizeof cases / sizeof *cases; i++) {
        output_width = cases[i].width; output_height = cases[i].height;
        hos_wide_out = cases[i].wide; override = cases[i].env;
        uint64_t got = hos_rt_pool_size(cases[i].game_mib * MIB);
        if (got != cases[i].expected_mib * MIB) {
            fprintf(stderr, "case %u: got %llu bytes, expected %llu MiB\n", i,
                    (unsigned long long)got, (unsigned long long)cases[i].expected_mib);
            failed = 1;
        }
    }
    /* TEX-85: a cap reached by a widescreen picture pins storage just like a fixed 5K output.
       A picture over 4K whose scaled pool still has room is not pinned. Explicit budgets always are. */
    output_width = 3840; output_height = 2160; hos_wide_out = WIDE(5120, 2160); override = NULL;
    if (hos_rt_pool_size(305 * MIB) != 900 * MIB || rt_pool_pinned != 1) return 3;
    hos_wide_out = WIDE(4096, 2160);
    if (hos_rt_pool_size(305 * MIB) >= 900 * MIB || rt_pool_pinned != 0) return 4;
    scene_rgba16f = 1; hos_wide_out = WIDE(4608, 2160);
    if (hos_rt_pool_size(305 * MIB) != 900 * MIB || rt_pool_pinned != 1) return 5;
    scene_rgba16f = 0; hos_wide_out = WIDE(3840, 2400);
    if (hos_rt_pool_size(360 * MIB) != 900 * MIB || rt_pool_pinned != 1) return 7;   /* exactly at the cap */
    hos_wide_out = 0; override = "512";
    if (hos_rt_pool_size(305 * MIB) != 512 * MIB || rt_pool_pinned != 1) return 6;
    /* (local, RenoDX port) an RGBA16F scene: 128 MiB more, but not over an explicit HOS_RT_POOL_MB */
    scene_rgba16f = 1;
    output_width = 2560; output_height = 1440; hos_wide_out = 0;
    override = NULL;
    if (hos_rt_pool_size(305 * MIB) != (512 + 128) * MIB) { fprintf(stderr, "RGBA16F scene: not 640 MiB\n"); failed = 1; }
    override = "256";
    if (hos_rt_pool_size(305 * MIB) != 256 * MIB) { fprintf(stderr, "RGBA16F scene: the override not kept\n"); failed = 1; }
    /* (the 5120 x 2880 output with an RGBA16F scene: 900 MiB for the whole pool, not 900 + 128, which failed the game's
       reservation at boot; 3840 x 2160 keeps its 128 MiB more, and an explicit override still wins) */
    output_width = 5120; output_height = 2880; override = NULL;
    if (hos_rt_pool_size(305 * MIB) != 900 * MIB) { fprintf(stderr, "RGBA16F scene at 5120x2880: not 900 MiB\n"); failed = 1; }
    override = "1028";
    if (hos_rt_pool_size(305 * MIB) != 1028 * MIB) { fprintf(stderr, "RGBA16F scene at 5120x2880: the override not kept\n"); failed = 1; }
    output_width = 5120; output_height = 2160; override = NULL;
    if (hos_rt_pool_size(305 * MIB) != 900 * MIB) { fprintf(stderr, "RGBA16F scene at 5120x2160: not 900 MiB\n"); failed = 1; }
    output_width = 3840; output_height = 2160; override = NULL;
    if (hos_rt_pool_size(305 * MIB) != (687 + 128) * MIB) { fprintf(stderr, "RGBA16F scene at 3840x2160: not 815 MiB\n"); failed = 1; }
    return failed;
}
'''
    compiler = shutil.which(args.cc) if args.cc else next(
        (path for name in ("clang", "gcc", "cc") if (path := shutil.which(name))), None)
    if not compiler:
        raise SystemExit("No C compiler found (pass --cc)")
    with tempfile.TemporaryDirectory(prefix="rt-pool-minimum-") as directory:
        path = Path(directory)
        source, binary = path / "fixture.c", path / "fixture.exe"
        source.write_text(fixture)
        subprocess.run([compiler, "-std=c11", "-O2", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=5)
    print("PASS: 512 MiB floor, 4K/ultrawide growth and explicit overrides, the 900 MiB of the outputs over 3840x2160's pixels, frame or picture (20 cases), "
          "an RGBA16F scene's 128 MiB more, and the 5K output's 900 MiB with it")


if __name__ == "__main__":
    main()
