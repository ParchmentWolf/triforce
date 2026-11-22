"""No udmabuf dma-bufs are offered to NVIDIA's proprietary driver on Linux (gpu/vk/dmabuf_gate.h; no game, no GPU).

(Triforce, 11-22, the performance audit's OS-08, after Source A's.) On Linux each pool of guest memory is first offered
to the driver as a dma-buf made by udmabuf. NVIDIA's proprietary driver refuses every one and the pool ends as a
host-pointer import anyway, after a refused import each (one took 198 ms during a load). With that driver
/dev/udmabuf is no longer opened.

Compiles the rule and import_dma_buf's first-call block, cut out of gpu/vk/vk_memory.cpp, over stand-ins for the
device, dlsym, open, fopen, the environment and the log (so it runs on Windows too), and checks:
  RADV, NVK                               /dev/udmabuf opened once, "yes", pieces of 64 MB
  NVIDIA's proprietary driver             not opened, "no (NVIDIA's driver refuses them: host pointers)", no pieces line
  ... with RX_VK_DMABUF_NVIDIA=1          opened, "yes" (as before); =0: not opened
  RADV, /dev/udmabuf does not open        "no (/dev/udmabuf cannot be opened)"
  an anonymous window, RX_VK_NO_DMABUF,   not opened, each with its own reason (and before NVIDIA's, when both hold)
    no dma-buf import on the device
And reads the source: the rule is asked before the open, the answer comes from the header, the fd guard of a failed
import is still there; the switches table has the row.

    python -I -B tests/test_dmabuf_driver_gate.py --headers <Vulkan-Headers>/include [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]


def block(text, marker, start=0):
    at = text.find(marker, start)
    if at < 0:
        raise SystemExit("FAIL: vk_memory.cpp has no '%s'" % marker)
    end = text.index("{", at) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[at:end]


FIXTURE = r'''#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>
#include <algorithm>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <vector>
#include "dmabuf_gate.h"
#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif

static int checks, fails;
#define CHECK(x) do { checks++; if (!(x)) { fails++; printf("FAIL line %d: %s (logged: %s)\n", __LINE__, #x, logged.c_str()); } } while (0)

// stand-ins: the device, the host's memfd function, /dev/udmabuf, the limit file, the environment, the log
static struct { bool dma_buf_import = true, sparse_buffers = true; VkDriverId driver_id{}; } dev;
static bool vkGetMemoryFdPropertiesKHR = true;   // (the fd properties call is there)
static int t_memfd = 5, t_opens, t_dlsyms;
static bool t_open_ok = true;
static std::string logged;
static const char *t_no_dmabuf, *t_piece_mb, *t_nvidia_too;
static int memfd_fn() { return t_memfd; }
#define RTLD_DEFAULT nullptr
static void* dlsym(void*, const char* name) {
    if (strcmp(name, "hos_posix_guest_memfd")) printf("FAIL: dlsym(%s)\n", name), exit(1);
    t_dlsyms++;
    return (void*)memfd_fn;
}
static int t_open(const char* path, int) {
    if (strcmp(path, "/dev/udmabuf")) printf("FAIL: opened %s\n", path), exit(1);
    t_opens++;
    return t_open_ok ? 9 : -1;
}
static FILE* t_fopen(const char*, const char*) { return nullptr; }   // (the limit file not readable: 64 MB)
static const char* t_getenv(const char* name) {
    if (!strcmp(name, "RX_VK_NO_DMABUF")) return t_no_dmabuf;
    if (!strcmp(name, "RX_VK_DMABUF_PIECE_MB")) return t_piece_mb;
    if (!strcmp(name, "RX_VK_DMABUF_NVIDIA")) return t_nvidia_too;
    printf("FAIL: getenv(%s)\n", name), exit(1);
}
static void logf(const char* fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    logged += line, logged += "\n";
}
#define open t_open
#define fopen t_fopen
#define getenv t_getenv

static int dmabuf_memfd = -2, dmabuf_dev = -1;
static uint64_t dmabuf_limit = 0;
static uint64_t piece;
static void first_call() {
    @CUT@
}

// One start. Returns the number of opens
static int start(VkDriverId driver, bool open_ok = true, int memfd = 5, bool ext = true, const char* no_dmabuf = nullptr,
                 const char* nvidia_too = nullptr) {
    dev.driver_id = driver, dev.dma_buf_import = ext;
    t_open_ok = open_ok, t_memfd = memfd, t_no_dmabuf = no_dmabuf, t_nvidia_too = nvidia_too, t_piece_mb = nullptr;
    t_opens = t_dlsyms = 0, logged.clear();
    dmabuf_memfd = -2, dmabuf_dev = -1, dmabuf_limit = 0, piece = 0;
    first_call();
    CHECK(dmabuf_memfd != -2);   // (decided once)
    return t_opens;
}
static bool said(const char* what) { return logged.find(what) != std::string::npos; }

int main() {
    using dmabuf_gate::Facts;
    // the rule by itself
    Facts f;
    f.fn = f.memfd = f.ext = true;
    CHECK(dmabuf_gate::try_udmabuf(f) && !strcmp(dmabuf_gate::answer(f, true), "yes"));
    CHECK(!strcmp(dmabuf_gate::answer(f, false), "no (/dev/udmabuf cannot be opened)"));
    f.nvidia = true;
    CHECK(!dmabuf_gate::try_udmabuf(f) && dmabuf_gate::try_udmabuf_before(f));   // (as it was: offered to NVIDIA's too)
    CHECK(!strcmp(dmabuf_gate::answer(f, false), "no (NVIDIA's driver refuses them: host pointers)"));
    CHECK(strcmp(dmabuf_gate::answer(f, true), "yes"));   // (never "yes" where it is not tried)
    f.ext = false;
    CHECK(!dmabuf_gate::try_udmabuf(f) && !strcmp(dmabuf_gate::answer(f, false), "no (VK_EXT_external_memory_dma_buf)"));
    f.memfd = false;
    CHECK(!strcmp(dmabuf_gate::answer(f, false), "no (the window is anonymous memory)"));
    f.fn = false;
    CHECK(!strcmp(dmabuf_gate::answer(f, false), "no (no memfd window, or RX_VK_NO_DMABUF)"));
    CHECK(!dmabuf_gate::try_udmabuf(Facts{}) && !dmabuf_gate::try_udmabuf_before(Facts{}));

    // the first-call block of import_dma_buf
    CHECK(start(VK_DRIVER_ID_MESA_RADV) == 1 && dmabuf_memfd == 5 && dmabuf_dev == 9);
    CHECK(said("vk: guest memory as dma-bufs: yes\n") && said("vk: dma-bufs of at most 64 MB (udmabuf's limit 64 MB)"));
    CHECK(piece == 64ull << 20 && dmabuf_limit == 64ull << 20);
    CHECK(start(VK_DRIVER_ID_MESA_NVK) == 1 && dmabuf_memfd == 5 && said("dma-bufs: yes\n"));
    CHECK(start(VK_DRIVER_ID_AMD_OPEN_SOURCE) == 1 && said("dma-bufs: yes\n"));

    CHECK(start(VK_DRIVER_ID_NVIDIA_PROPRIETARY) == 0 && dmabuf_memfd == -1 && dmabuf_dev == -1);
    CHECK(said("vk: guest memory as dma-bufs: no (NVIDIA's driver refuses them: host pointers)\n") && !said("dma-bufs of at most"));
    CHECK(t_dlsyms == 1);   // (the window's memfd is still asked for: only the offer is skipped)
    CHECK(start(VK_DRIVER_ID_NVIDIA_PROPRIETARY, true, 5, true, nullptr, "1") == 1 && dmabuf_memfd == 5 && said("dma-bufs: yes\n"));
    CHECK(start(VK_DRIVER_ID_NVIDIA_PROPRIETARY, true, 5, true, nullptr, "0") == 0 && said("NVIDIA's driver refuses them"));

    CHECK(start(VK_DRIVER_ID_MESA_RADV, false) == 1 && dmabuf_memfd == -1 && said("no (/dev/udmabuf cannot be opened)\n"));
    CHECK(start(VK_DRIVER_ID_MESA_RADV, true, -1) == 0 && dmabuf_memfd == -1 && said("no (the window is anonymous memory)\n"));
    CHECK(start(VK_DRIVER_ID_MESA_RADV, true, 5, false) == 0 && said("no (VK_EXT_external_memory_dma_buf)\n"));
    CHECK(start(VK_DRIVER_ID_MESA_RADV, true, 5, true, "1") == 0 && t_dlsyms == 0 && said("no (no memfd window, or RX_VK_NO_DMABUF)\n"));
    // NVIDIA's with an anonymous window, or RX_VK_NO_DMABUF: the earlier reason is the one said
    CHECK(start(VK_DRIVER_ID_NVIDIA_PROPRIETARY, true, -1) == 0 && said("no (the window is anonymous memory)\n"));
    CHECK(start(VK_DRIVER_ID_NVIDIA_PROPRIETARY, true, 5, true, "1") == 0 && said("no (no memfd window, or RX_VK_NO_DMABUF)\n"));

    if (fails) printf("dmabuf driver gate: FAILED (%d of %d checks)\n", fails, checks);
    else printf("dmabuf driver gate: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check_source():
    src = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    if '#include "dmabuf_gate.h"' not in src:
        raise SystemExit("FAIL: vk_memory.cpp does not include dmabuf_gate.h")
    fn_at = src.find("bool import_dma_buf(uint64_t lo, uint64_t hi, Pool& p) {")
    if fn_at < 0:
        raise SystemExit("FAIL: vk_memory.cpp has no import_dma_buf")
    first = block(src, "    if (dmabuf_memfd == -2) {", fn_at)
    order = [first.find(n) for n in (
        "gate.nvidia = dev.driver_id == VK_DRIVER_ID_NVIDIA_PROPRIETARY &&",
        'if (dmabuf_gate::try_udmabuf(gate)) dmabuf_dev = open("/dev/udmabuf", O_RDWR | O_CLOEXEC);',
        'logf("vk: guest memory as dma-bufs: %s", dmabuf_gate::answer(gate, dmabuf_dev >= 0));')]
    if min(order) < 0 or order != sorted(order) or first.count("open(") != 2:   # (the open and the limit file's fopen)
        raise SystemExit("FAIL: import_dma_buf's first call does not ask dmabuf_gate.h before its one open of "
                         "/dev/udmabuf, or its line is not the header's answer (%r)" % (order,))
    guard = block(src, "VkDeviceMemory dma_buf_memory(uint64_t lo, uint64_t size) {")
    if "fcntl(fd, F_DUPFD_CLOEXEC, 1024)" not in guard or "if (fcntl(fd, F_GETFD) != -1) close(fd);" not in guard:
        raise SystemExit("FAIL: dma_buf_memory lost the guard for a failed import's fd (other drivers and layers need it)")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `RX_VK_DMABUF_NVIDIA=1`, `RX_VK_NO_DMABUF=1`, `RX_VK_DMABUF_PIECE_MB=<n>` |" not in docs or "`gpu/vk/dmabuf_gate.h`" not in docs:
        raise SystemExit("FAIL: docs/development.md: the switches table has no RX_VK_DMABUF_NVIDIA row")
    return first


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--headers", required=True, help="Vulkan-Headers' include folder")
    args = parser.parse_args()
    first = check_source()
    with tempfile.TemporaryDirectory(prefix="dmabuf-gate-") as tmp:
        cpp, exe = Path(tmp) / "dmabuf_gate_test.cpp", Path(tmp) / "dmabuf-gate.exe"
        cpp.write_text(FIXTURE.replace("@CUT@", first), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-I" + args.headers, "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the dma-buf driver gate's checks failed")


if __name__ == "__main__":
    main()
