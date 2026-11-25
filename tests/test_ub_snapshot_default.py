"""The uniform snapshot (gpu/vk/vk_draw.cpp ub_snapshot_wanted, RX_VK_UB_SNAPSHOT) is on by default on every Intel GPU,
its discrete Arc cards with VRAM mirrors included, and on any other integrated GPU whose pools have no mirror; off
elsewhere; uniform_range asks it. The decision compiled alone against a table; no game or GPU required.

Bound where the game keeps them, a frame's uniforms are read by the GPU after the game has written the next frame's over
them: on an Arc B580 (101.9154, mirrors on) the Kokiri Forest floor and the treehouses went to sky, with white glowing
blocks and pots that came and went, as on the Intel iGPUs the snapshot was first made for.

python -I -B tests/test_ub_snapshot_default.py [--cxx g++]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402

# RX_VK_UB_SNAPSHOT's value (None: unset), the GPU's vendor, integrated or not, mirrors or not, and whether the uniforms
# are snapshotted
VENDORS = {"intel": 0x8086, "amd": 0x1002, "nvidia": 0x10DE}
CASES = ([(None, "intel", i, m, 1) for i in (0, 1) for m in (0, 1)] +
         [(None, "amd", 1, 0, 1), (None, "amd", 1, 1, 0), (None, "amd", 0, 0, 0), (None, "amd", 0, 1, 0)] +
         [(None, "nvidia", 0, 1, 0), (None, "nvidia", 0, 0, 0), (None, "nvidia", 1, 0, 1)] +
         [(v, g, 0, 1, 1) for v in ("1", "on", "yes", "2", "") for g in VENDORS] +
         [("0", g, i, 0, 0) for g in VENDORS for i in (0, 1)])
FIXTURE = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
enum { VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU = 1, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU = 2 };
static struct { struct { unsigned vendorID; int deviceType; } props; } dev;
static bool mirrored;
static bool pools_mirrored() { return mirrored; }
static const char* the_value;   // (the switch's value, nullptr: unset; read in place of the environment)
static const char* fake_getenv(const char* name) { return strcmp(name, "RX_VK_UB_SNAPSHOT") ? nullptr : the_value; }
#define getenv fake_getenv
@@DECISION@@
int main(int argc, char** argv) {
    // (argv: value or -unset, the vendor, 1 integrated, 1 mirrors, 1 snapshotted or 0)
    for (int i = 1; i + 4 < argc; i += 5) {
        the_value = strcmp(argv[i], "-unset") ? (strcmp(argv[i], "-empty") ? argv[i] : "") : nullptr;
        dev.props.vendorID = (unsigned)strtoul(argv[i + 1], nullptr, 0);
        dev.props.deviceType = atoi(argv[i + 2]) ? VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU : VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU;
        mirrored = atoi(argv[i + 3]) != 0;
        const bool got = ub_snapshot_wanted();
        if (got != (atoi(argv[i + 4]) != 0)) {
            printf("FAIL: RX_VK_UB_SNAPSHOT=[%s], vendor 0x%04x, %s, %s: %s\n", the_value ? the_value : "(unset)",
                   dev.props.vendorID, atoi(argv[i + 2]) ? "integrated" : "discrete", mirrored ? "mirrors" : "no mirrors",
                   got ? "snapshotted" : "bound in place");
            return 1;
        }
    }
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    args = p.parse_args()
    src = (VK / "vk_draw.cpp").read_text(encoding="utf-8")

    ranges = block(src, "VkDescriptorBufferInfo uniform_range(const NvnState& s, const Stage& st, uint32_t index) {")
    code = "\n".join(line.split("//")[0] for line in ranges.splitlines())
    if "static const bool snapshot = ub_snapshot_wanted();" not in code:
        raise SystemExit("FAIL: uniform_range no longer asks ub_snapshot_wanted whether to snapshot the uniforms")
    if "snapshot && !gpu_written ? BufferRef{} : gpu_buffer_bind(" not in code:
        raise SystemExit("FAIL: uniform_range binds a uniform buffer in place although the snapshot is on (and the GPU did "
                         "not write it earlier in the submission: tests/test_ub_snapshot_gpu_writes.py)")
    print("source: uniform_range copies the uniforms into the stream when ub_snapshot_wanted says so")

    decision = block(src, "bool ub_snapshot_wanted() {")
    with tempfile.TemporaryDirectory(prefix="ub-snapshot-") as tmp:
        tmp = Path(tmp)
        cpp, exe = tmp / "t.cpp", tmp / "t.exe"
        cpp.write_text(FIXTURE.replace("@@DECISION@@", decision), encoding="utf-8")
        r = subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode:
            print(r.stdout + r.stderr)
            raise SystemExit("FAIL: ub_snapshot_wanted did not build alone")
        argv = []
        for value, gpu, integrated, mirrors, want in CASES:
            argv += ["-unset" if value is None else (value or "-empty"), hex(VENDORS[gpu]), str(integrated), str(mirrors), str(want)]
        r = subprocess.run([str(exe), *argv], capture_output=True, text=True, timeout=30)
        if r.returncode:
            print(r.stdout + r.stderr)
            raise SystemExit("FAIL: the uniform snapshot's default is wrong (on for every Intel GPU, mirrors or not, and for "
                             "another integrated GPU without mirrors; off elsewhere; RX_VK_UB_SNAPSHOT: 0 off, any other "
                             "value on)")
    print("decision: %d cases: unset, on for Intel (discrete Arc included) and for integrated GPUs without mirrors, off "
          "elsewhere; RX_VK_UB_SNAPSHOT=0 off, any other value on" % len(CASES))
    print("PASS")


if __name__ == "__main__":
    main()
