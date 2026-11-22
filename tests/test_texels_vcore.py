"""ReadTexels and WriteTexels give their virtual core up for the back end's call (host/rx_backend.c; no game, no GPU).

(Triforce, 11-21, the performance audit's THREAD-20, after Source A's.) Both calls reach the back end, which waits for all
the GPU work submitted and then for the replay's lock. The calling thread kept its virtual core through that wait, and
the game threads allowed only on that core waited with it.

This cuts the two wrappers and their switch out of rx_backend.c as they are and compiles them with stand-ins for the back
ends and for hos_vcore_away and hos_vcore_back: no core is held inside either back end's call, on Vulkan and on the
fallback; the core is taken back after it; a thread that had no core to give is not handed one; a write kept for a
renderer not started yet keeps the core and never reaches the back end; and with HOS_TEXELS_KEEP_CORE=1 the core is held
through the call, as before.

And reads the source for the switches row.

    python -I -B tests/test_texels_vcore.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


FIXTURE = r"""
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
struct nvn_texdesc { int format; };
struct nvn_tex { nvn_texdesc d; };
struct NVNcopyRegion { int xoffset, yoffset, zoffset, width, height, depth; };
typedef struct { int kind, pad; nvn_tex t; unsigned level, layer0; NVNcopyRegion r; size_t row, img; uint8_t *data; } early_call;
// the thread's virtual core: held or not, and how often it was given up and taken back
static int held = 1, aways = 0, backs = 0, can_give = 1;
static int hos_vcore_away(void) { if (!can_give || !held) return 0; held = 0, aways++; return 1; }
static void hos_vcore_back(void) { CHECK(!held); held = 1, backs++; }
// the back ends: what they saw of the core
static int vk_reads = 0, vk_writes = 0, wgr_reads = 0, wgr_writes = 0, held_inside = 0, kept = 0;
struct Renderer {
    void (*nvn_read_texels)(const nvn_tex *, unsigned, unsigned, const NVNcopyRegion *, uint8_t *, size_t, size_t);
    void (*nvn_write_texels)(const nvn_tex *, unsigned, unsigned, const NVNcopyRegion *, const uint8_t *, size_t, size_t);
};
static void vk_read(const nvn_tex *, unsigned, unsigned, const NVNcopyRegion *, uint8_t *, size_t, size_t) { vk_reads++, held_inside += held; }
static void vk_write(const nvn_tex *, unsigned, unsigned, const NVNcopyRegion *, const uint8_t *, size_t, size_t) { vk_writes++, held_inside += held; }
static void wgr_nvn_read_texels(const nvn_tex *, unsigned, unsigned, const NVNcopyRegion *, uint8_t *, size_t, size_t) { wgr_reads++, held_inside += held; }
static void wgr_nvn_write_texels(const nvn_tex *, unsigned, unsigned, const NVNcopyRegion *, const uint8_t *, size_t, size_t) { wgr_writes++, held_inside += held; }
static const Renderer vulkan = {vk_read, vk_write};
static const Renderer *vk = &vulkan;
static int started = 1;
static int nvn_fmt_bpb(int, int *bw, int *bh) { *bw = *bh = 1; return 4; }
static int keep_early(const early_call *c) { kept++, held_inside += 0; CHECK(held); free(c->data); return 1; }

@WRAPPERS@

int main(int argc, char **argv) {
    const bool keep = argc > 1 && !strcmp(argv[1], "keep");   // (run with HOS_TEXELS_KEEP_CORE=1 in the environment)
    nvn_tex t{{0x25}};
    NVNcopyRegion r{0, 0, 0, 16, 16, 1};
    uint8_t buf[16 * 16 * 4] = {0};
    rx_nvn_read_texels(&t, 0, 0, &r, buf, 64, 1024);
    rx_nvn_write_texels(&t, 0, 0, &r, buf, 64, 1024);
    CHECK(vk_reads == 1 && vk_writes == 1 && held == 1);
    if (keep) CHECK(held_inside == 2 && aways == 0 && backs == 0);    // (as before: the core held through both)
    else CHECK(held_inside == 0 && aways == 2 && backs == 2);         // (given up for each call, and taken back)
    vk = nullptr;                                                     // (the fallback back end alike)
    held_inside = aways = backs = 0;
    rx_nvn_read_texels(&t, 0, 0, &r, buf, 64, 1024);
    rx_nvn_write_texels(&t, 0, 0, &r, buf, 64, 1024);
    CHECK(wgr_reads == 1 && wgr_writes == 1 && held == 1);
    if (keep) CHECK(held_inside == 2 && aways == 0);
    else CHECK(held_inside == 0 && aways == 2 && backs == 2);
    vk = &vulkan;
    can_give = 0, held = 0, aways = backs = 0;                        // (a thread with no core to give: none is handed to it)
    rx_nvn_read_texels(&t, 0, 0, &r, buf, 64, 1024);
    rx_nvn_write_texels(&t, 0, 0, &r, buf, 64, 1024);
    CHECK(held == 0 && aways == 0 && backs == 0 && vk_reads == 2 && vk_writes == 2);
    can_give = 1, held = 1, started = 0, aways = backs = 0;           // (the renderer not started: the write is kept, the core too)
    rx_nvn_write_texels(&t, 0, 0, &r, buf, 64, 1024);
    CHECK(kept == 1 && vk_writes == 2 && aways == 0 && backs == 0 && held == 1);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    src = (ROOT / "host" / "rx_backend.c").read_text(encoding="utf-8").replace("\r\n", "\n")
    wrappers = "\n".join(block(src, m) for m in ("static int texels_keep_core(void) {", "void rx_nvn_read_texels(", "void rx_nvn_write_texels("))
    check('getenv("HOS_TEXELS_KEEP_CORE")' in wrappers, "the wrappers' switch is not HOS_TEXELS_KEEP_CORE")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_TEXELS_KEEP_CORE=1`" in dev, "docs/development.md: HOS_TEXELS_KEEP_CORE is not in the switches table")
    with tempfile.TemporaryDirectory(prefix="texels-vcore-") as tmp:
        c, exe = Path(tmp) / "texels.cpp", Path(tmp) / "texels.exe"
        c.write_text(FIXTURE.replace("@WRAPPERS@", wrappers), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Wno-unused-function", "-Wno-missing-field-initializers", "-Werror", str(c), "-o", str(exe)], check=True)
        for arm, value in (("", None), ("keep", "1"), ("", "0")):
            env = {k: v for k, v in os.environ.items() if k != "HOS_TEXELS_KEEP_CORE"}
            if value is not None:
                env["HOS_TEXELS_KEEP_CORE"] = value
            r = subprocess.run([str(exe)] + ([arm] if arm else []), capture_output=True, text=True, env=env)
            check(r.returncode == 0, "the wrappers with HOS_TEXELS_KEEP_CORE %s:\n%s" % ("not set" if value is None else "= " + value, r.stdout))
    print("PASS: ReadTexels and WriteTexels give their virtual core up for the back end's call")


if __name__ == "__main__":
    main()
