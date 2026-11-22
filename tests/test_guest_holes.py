"""The all-zero upload check reads only the guest memfd's data, not its holes (gpu/vk/guest_holes.h, vk_texture.cpp
upload_all_zero, RX_VK_ZERO_HOLES; no game/GPU).

On Linux the guest window is a memfd's where /dev/udmabuf is usable; a page the game never wrote is a hole, which reads as zero
but becomes RAM when read through the shared mapping. The check read the whole storage (the never-written 288 MB shadow map
became RAM at each Hyrule Field arrival).

upload_all_zero's Linux block is cut out of vk_texture.cpp unchanged and compiled with guest_holes.h, stand-ins for the host's
window and dlsym, and a scripted file for lseek's SEEK_DATA and SEEK_HOLE (so it runs on Windows too). Bytes the file calls holes
are set non-zero, so a read of any of them shows. Checked: all holes: nothing read, all zero; data past holes: only the data read,
a set byte there found; the data clipped at the storage's end; a storage outside the window, no memfd, a seek that fails and
RX_VK_ZERO_HOLES=0 each read the whole storage; past 1,024 extents the rest is read whole. share: every byte of the extents in
exactly one thread's part, the tail of a size not a multiple of 8 or of the threads too. The source: upload_all_zero asks
any_set with the extents, the block is Linux's alone, the log lines say how much was read, and the switch has its docs row.

    python -I -B tests/test_guest_holes.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/types.h>
#include <vector>
#ifndef SEEK_DATA
#define SEEK_DATA 3
#define SEEK_HOLE 4
#endif
#ifndef ENXIO
#define ENXIO 6
#endif
// (the scripted file: its data as [lo, hi) offsets from its start, the rest holes, kFileSize long)
static std::vector<std::pair<uint64_t, uint64_t>> g_data;
static bool g_fail = false;
static int g_seeks = 0;
constexpr uint64_t kFileSize = 8ull << 20;
static int64_t fake_lseek(int fd, int64_t pos, int whence) {
    g_seeks++;
    if (fd != 7 || g_fail || pos < 0) return errno = EBADF, -1;
    if (whence == SEEK_DATA) {
        for (const auto& d : g_data)
            if (d.second > (uint64_t)pos) return d.first > (uint64_t)pos ? (int64_t)d.first : pos;
        return errno = ENXIO, -1;
    }
    if (whence == SEEK_HOLE) {
        for (const auto& d : g_data)
            if (d.first <= (uint64_t)pos && (uint64_t)pos < d.second) return (int64_t)d.second;
        return pos;
    }
    return errno = EINVAL, -1;
}
#define lseek fake_lseek
#define GUEST_HOLES_TEST 1
#include "guest_holes.h"
using namespace mkwvk;

static uint8_t g_window[kFileSize];
static int g_memfd = 7;
static int hos_posix_guest_memfd() { return g_memfd; }
#define RTLD_DEFAULT nullptr
static void* dlsym(void*, const char* name) { return !strcmp(name, "hos_posix_guest_memfd") ? (void*)&hos_posix_guest_memfd : nullptr; }
struct Host { uint8_t* (*guest_base)(void); uint64_t (*guest_size)(void); };
static uint8_t* base_fn() { return g_window; }
static uint64_t size_fn() { return sizeof g_window; }
static const Host host_obj{base_fn, size_fn};
static const Host* host = &host_obj;

struct Result { bool found; uint64_t read; };
static Result check(const uint8_t* p, uint64_t total) {
    const uint32_t threads = 4;
@CUT@
    (void)threads;
    return {guest_holes::any_set(p, extents, threads), read_bytes};
}

static int bad = 0;
static void expect(bool ok, const char* what) {
    if (!ok) { std::printf("FAIL %s\n", what); bad++; }
}
// (every byte the file calls a hole set to 0xAB, its data 0)
static void fill() {
    memset(g_window, 0xAB, sizeof g_window);
    for (const auto& d : g_data) memset(g_window + d.first, 0, d.second - d.first);
}

int main(int argc, char** argv) {
    const char* c = argv[1];
    const uint64_t off = 1ull << 20, total = 4ull << 20;   // (the storage: 4 MB at 1 MB into the window)
    uint8_t* p = g_window + off;
    if (!strcmp(c, "share")) {
        static const uint64_t sizes[] = {1, 7, 4095, 4096, 4097, 65536 * 3 + 5, (1ull << 20) + 3};
        for (uint32_t n = 1; n <= 9; n++)
            for (uint64_t sz : sizes) {
                std::vector<guest_holes::Extent> ex{{3, 3 + sz / 3}, {sz, sz + sz / 2 + 1}, {5 * sz, 5 * sz + sz - sz / 3 - sz / 2 - 1}};
                std::vector<int> seen(6 * sz + 8, 0);
                for (uint32_t t = 0; t < n; t++)
                    for (const auto& e : guest_holes::share(ex, t, n))
                        for (uint64_t k = e.lo; k < e.hi; k++) seen[k]++;
                for (const auto& e : ex)
                    for (uint64_t k = e.lo; k < e.hi; k++)
                        if (seen[k] != 1) { std::printf("FAIL share n=%u size=%llu byte %llu read %d times\n", n, (unsigned long long)sz, (unsigned long long)k, seen[k]); return 1; }
                uint64_t all = 0;
                for (int v : seen) all += v;
                expect(all == guest_holes::bytes(ex), "share: nothing outside the extents");
            }
        expect(guest_holes::share({}, 0, 4).empty(), "share: no extents, no part");
        expect(!guest_holes::any_set(p, {}, 4), "any_set: no extents, nothing set");
    } else if (!strcmp(c, "holes")) {   // (all holes)
        g_data.clear();
        fill();
        const Result r = check(p, total);
        expect(!r.found && r.read == 0, "all holes: all zero, nothing read");
    } else if (!strcmp(c, "data")) {   // (data past holes, a byte set in it)
        g_data = {{off + 65536, off + 2 * 65536}, {off + (2ull << 20), off + (2ull << 20) + 12288}};
        fill();
        const Result r = check(p, total);
        expect(!r.found, "data past holes, all zero: all zero");
        expect(r.read == 65536 + 12288, "data past holes: only the data read");
        g_window[off + (2ull << 20) + 12287] = 1;
        expect(check(p, total).found, "data past holes: its last byte set found");
    } else if (!strcmp(c, "tail")) {   // (data running past the storage's end, and before its start)
        g_data = {{off - 4096, off + 4096}, {off + total - 4096, off + total + 65536}};
        fill();
        const Result r = check(p, total);
        expect(!r.found && r.read == 8192, "data past either end: clipped to the storage");
    } else if (!strcmp(c, "whole")) {   // (a storage outside the window, no memfd, a failing seek, the switch: the whole read)
        g_data = {{off + 65536, off + 2 * 65536}};
        fill();
        const char* how = argv[2];
        const uint8_t* q = p;
        uint8_t* outside = nullptr;
        if (!strcmp(how, "outside")) q = outside = (uint8_t*)calloc(total, 1);
        if (!strcmp(how, "nomemfd")) g_memfd = -1;
        if (!strcmp(how, "fail")) g_fail = true;
        if (outside) outside[total - 1] = 1;
        const Result r = check(q, total);
        expect(r.found && r.read == total, "the whole storage read, the set bytes found");
        if (!strcmp(how, "switch") || !strcmp(how, "nomemfd") || !strcmp(how, "outside")) expect(g_seeks == 0, "no seek made");
        free(outside);
    } else if (!strcmp(c, "many")) {   // (2,000 extents: the first 1,023, then the rest whole)
        g_data.clear();
        for (uint64_t i = 0; i < 2000; i++) g_data.push_back({off + i * 2048, off + i * 2048 + 1024});
        fill();
        const Result r = check(p, total);
        expect(r.found, "past 1,024 extents: the rest read whole (its holes' set bytes found)");
        expect(r.read == total - 1022 * 1024, "past 1,024 extents: 1,023 of them, then the rest");
    } else {
        return 2;
    }
    if (bad) return 1;
    std::printf("OK %s\n", c);
    return 0;
}
'''

CASES = [(["share"], {}), (["holes"], {}), (["data"], {}), (["tail"], {}), (["whole", "outside"], {}), (["whole", "nomemfd"], {}),
         (["whole", "fail"], {}), (["whole", "switch"], {"RX_VK_ZERO_HOLES": "0"}), (["many"], {}), (["data"], {"RX_VK_ZERO_HOLES": "1"})]


def fail(message):
    raise SystemExit("FAIL: " + message)


def cut(tex):
    body = tex[tex.index("bool upload_all_zero(Texture& tex, uint64_t total, const Ranges* dirty, bool widened_format) {"):]
    body = body[:body.index("\n}\n")]
    start = body.index("    std::vector<guest_holes::Extent> extents{{0, total}};")
    end = body.index("    const uint64_t read_bytes = guest_holes::bytes(extents);")
    block = body[start:end]
    if "#ifdef __linux__" not in block or "#endif" not in block:
        fail("upload_all_zero's look at the memfd is not Linux's alone")
    if "guest_holes::any_set(p, extents, std::clamp(cpu_count() / 2, 1u, 8u));" not in body:
        fail("upload_all_zero does not read the extents through any_set")
    for line in ("is not all zero (checked in %.1f ms, %llu MB read)", "is all zero: cleared on the GPU (checked in %.1f ms, %llu MB read)"):
        if line not in body:
            fail("upload_all_zero's log lines do not say how much was read: " + line)
    block = block.replace("#ifdef __linux__\n", "").replace("#endif\n", "")
    return block + "    const uint64_t read_bytes = guest_holes::bytes(extents);\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    try:
        text = FIXTURE.replace("@CUT@", cut(tex))
    except ValueError as e:
        fail("a text this test reads moved, or is not there (%s)" % e)
    if "`RX_VK_ZERO_HOLES=0`" not in dev:
        fail("docs/development.md has no RX_VK_ZERO_HOLES row")
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    problems = []
    with tempfile.TemporaryDirectory(prefix="guest-holes-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(text, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-pthread", "-D_FILE_OFFSET_BITS=64", "-Wall", "-Wno-unused-function",
                                "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)], capture_output=True, text=True, creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        base = {k: v for k, v in os.environ.items() if k != "RX_VK_ZERO_HOLES"}
        for args, extra in CASES:
            done = subprocess.run([str(exe)] + args, env={**base, **extra}, capture_output=True, text=True, timeout=60,
                                  creationflags=flags)
            if done.returncode or done.stdout.strip() != "OK " + args[0]:
                problems.append("%s %s: %s" % (" ".join(args), extra, (done.stdout + done.stderr).strip()))
    if problems:
        fail("\n  ".join([""] + problems))
    print("PASS: the all-zero check reads the memfd's data only, the whole storage otherwise or with RX_VK_ZERO_HOLES=0; every byte "
          "in one thread's part (%d cases)" % len(CASES))


if __name__ == "__main__":
    main()
