"""RADV on a GCN 1 to 4 GPU told apart (gpu/vk/vk_vendor.h radv_gcn), on made-up devices; no game, no GPU.

(Triforce, 11-22, the performance audit's MEM-23 and PIPE-56, after Source A's.) Source A tells AMD's GCN 1 to 4 GPUs
(HD 7000 to RX 500) under Mesa's RADV by RADV reporting no 16-bit storage input and output there; Vega and later have it.
This is the fact alone (VendorFacts::storage_io16, radv_gcn(), dev.radv_gcn): nothing is decided by it in this change.

Compiles radv_gcn() with the Vulkan headers and runs it on the properties of GPUs players have:
  RADV without 16-bit storage I/O (an RX 580, an R9 380)            -> GCN
  RADV with it (a Steam Deck, an RX 6800, a Vega 56)                 -> not
  AMD's Windows driver and AMDVLK, with or without it                -> not (not RADV)
  NVIDIA's driver, NVK, Intel's Windows driver, ANV, llvmpipe, without it too -> not
  facts made without the feature (the default)                       -> not, on any driver
and that vendor_fixes() is the same for a device whichever way the new fact is set.

And reads the source: create_device fills the fact from VkPhysicalDeviceVulkan11Features and sets dev.radv_gcn before
the device is made, and logs only where it is true (so no other device's log changes).

    python -I -B tests/test_radv_gcn.py --headers <Vulkan-Headers/include> [--cxx clang++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"

FIXTURE = r"""
#include <cstdio>
#include "vk_vendor.h"
using namespace mkwvk;

static int checks, fails;
static void want(const char* what, bool got, bool wanted) {
    checks++;
    if (got != wanted) fails++, std::printf("FAIL %s: %d, want %d\n", what, (int)got, (int)wanted);
}

int main() {
    struct D { const char* name; uint32_t vendor; VkDriverId driver; VkPhysicalDeviceType type; const char* info; bool io16, gcn; };
    const D devices[] = {
        {"RX 580, RADV", 0x1002, VK_DRIVER_ID_MESA_RADV, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "Mesa 26.2.5", false, true},
        {"R9 380, RADV", 0x1002, VK_DRIVER_ID_MESA_RADV, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "Mesa 25.3.0", false, true},
        {"Steam Deck, RADV", 0x1002, VK_DRIVER_ID_MESA_RADV, VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU, "Mesa 25.1.0", true, false},
        {"RX 6800, RADV", 0x1002, VK_DRIVER_ID_MESA_RADV, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "Mesa 26.2.5", true, false},
        {"Vega 56, RADV", 0x1002, VK_DRIVER_ID_MESA_RADV, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "Mesa 26.2.5", true, false},
        {"RX 580, AMD's Windows driver", 0x1002, VK_DRIVER_ID_AMD_PROPRIETARY, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU,
         "26.5.2 (AMD proprietary shader compiler)", false, false},
        {"RX 6700 XT, AMD's Windows driver", 0x1002, VK_DRIVER_ID_AMD_PROPRIETARY, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU,
         "26.10.1 (AMD proprietary shader compiler)", true, false},
        {"RX 580, AMDVLK", 0x1002, VK_DRIVER_ID_AMD_OPEN_SOURCE, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "2025.Q2.1 (LLPC)", false, false},
        {"RTX 5090, NVIDIA's Windows driver", 0x10DE, VK_DRIVER_ID_NVIDIA_PROPRIETARY, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "581.57", true, false},
        {"an NVIDIA card whose driver reported none", 0x10DE, VK_DRIVER_ID_NVIDIA_PROPRIETARY, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "581.57", false, false},
        {"GTX 1650, NVK", 0x10DE, VK_DRIVER_ID_MESA_NVK, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "Mesa 26.0.1", false, false},
        {"Arc B580, Intel's Windows driver", 0x8086, VK_DRIVER_ID_INTEL_PROPRIETARY_WINDOWS, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU, "101.8132", false, false},
        {"Iris Xe, ANV", 0x8086, VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA, VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU, "Mesa 26.0.1", false, false},
        {"llvmpipe", 0x10005, VK_DRIVER_ID_MESA_LLVMPIPE, VK_PHYSICAL_DEVICE_TYPE_CPU, "Mesa 26.0.1", false, false},
    };
    for (const D& d : devices) {
        VendorFacts f;
        f.vendor_id = d.vendor, f.driver_id = d.driver, f.device_type = d.type, f.driver_info = d.info;
        want("facts without the feature filled name no GCN card", radv_gcn(f), false);
        const VendorFixes before = vendor_fixes(f);
        f.storage_io16 = d.io16;
        want(d.name, radv_gcn(f), d.gcn);
        const VendorFixes after = vendor_fixes(f);
        want("the vendor fixes do not read the new fact",
             before.fetch_bounds == after.fetch_bounds && before.nan_bits == after.nan_bits && before.gather_offset == after.gather_offset, true);
    }
    if (fails) std::printf("radv gcn: FAILED (%d of %d checks)\n", fails, checks);
    else std::printf("radv gcn: all %d checks passed\n", checks);
    return fails != 0;
}
"""


def check_source():
    main = (VK / "vk_main.cpp").read_text(encoding="utf-8")
    order = [main.find(n) for n in (
        "vkGetPhysicalDeviceFeatures2(dev.physical, &f);",
        "facts.storage_io16 = f11.storageInputOutput16 != VK_FALSE;",
        "dev.radv_gcn = radv_gcn(facts);",
        'if (dev.radv_gcn) logf("vk: RADV on a GCN 1 to 4 GPU',
        "vkCreateDevice(dev.physical, &ci")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("FAIL: create_device does not fill the 16-bit storage I/O fact and dev.radv_gcn after the features are "
                         "asked and before the device is made, logging only where it is true")
    if main.count("dev.radv_gcn =") != 1:
        raise SystemExit("FAIL: dev.radv_gcn is set in more than one place")
    internal = (VK / "vk_internal.h").read_text(encoding="utf-8")
    if "bool radv_gcn = false;" not in internal:
        raise SystemExit("FAIL: vk_internal.h: Device has no radv_gcn, false until create_device says otherwise")
    vendor = (VK / "vk_vendor.h").read_text(encoding="utf-8")
    if "bool storage_io16 = true;" not in vendor or \
            "return f.driver_id == VK_DRIVER_ID_MESA_RADV && !f.storage_io16;" not in vendor:
        raise SystemExit("FAIL: vk_vendor.h: radv_gcn is not RADV without 16-bit storage input and output")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--headers", type=Path, required=True)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="radv-gcn-") as tmp:
        tmp = Path(tmp)
        cpp, exe = tmp / "fixture.cpp", tmp / "fixture.exe"
        cpp.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Werror", "-I" + str(VK), "-I" + str(args.headers), str(cpp),
                        "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the GCN rule's checks failed")


if __name__ == "__main__":
    main()
