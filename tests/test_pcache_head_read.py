"""The pipeline cache's files: the 32-byte header checked before the rest is read (gpu/vk/pcache_bound.h read's head_ok,
vk_draw.cpp pcache_head_ok, pcache_init and pcache_play_open; no game/GPU).

The file's stamp names only the translated shaders, so after a driver update or with another GPU it still matched, and the
whole file (0.65-1.6 GB) was read into memory only for its header to be refused. pcache_bound.h is compiled as it is, with a
fread that counts the bytes it reads, and pcache_head_ok is cut out of vk_draw.cpp and compiled with a stand-in device.
Checked: another vendor, device or pipelineCacheUUID, another header version, a header size under 32 or past the file's end
give Foreign with nothing kept and 32 bytes read; a matching file comes back byte for byte, whole; short, missing and over-bound
files answer as before with nothing read; with no check the read is as before. Then the source: both of pcache_init's and
pcache_play_open's reads pass the check, and the data read is still checked before Vulkan sees it.

    python -I -B tests/test_pcache_head_read.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def fail(message):
    raise SystemExit("FAIL: " + message)


FIXTURE = r'''#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
static uint64_t read_bytes = 0;
static size_t counting_fread(void* p, size_t size, size_t n, FILE* f) {
    const size_t got = std::fread(p, size, n, f);
    read_bytes += got * size;
    return got;
}
#define fread counting_fread
#include "pcache_bound.h"
#undef fread
constexpr uint32_t VK_PIPELINE_CACHE_HEADER_VERSION_ONE = 1;
constexpr uint32_t VK_UUID_SIZE = 16;
struct { struct { uint32_t vendorID = 0x10de, deviceID = 0x2b85; uint8_t pipelineCacheUUID[16]; } props; } dev;
@HEAD_OK@
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace pcache_bound;
static std::vector<uint8_t> cache(size_t n, uint32_t head_size, uint32_t version, uint32_t vendor, uint32_t device, int uuid_off) {
    std::vector<uint8_t> d(n);
    for (size_t i = 0; i < n; i++) d[i] = (uint8_t)(i * 13 + 5);
    std::memcpy(d.data(), &head_size, 4);
    std::memcpy(d.data() + 4, &version, 4);
    std::memcpy(d.data() + 8, &vendor, 4);
    std::memcpy(d.data() + 12, &device, 4);
    std::memcpy(d.data() + 16, dev.props.pipelineCacheUUID, 16);
    if (uuid_off >= 0) d[16 + uuid_off] ^= 0x5a;
    return d;
}
static bool put(const std::string& path, const std::vector<uint8_t>& d) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    const bool ok = std::fwrite(d.data(), 1, d.size(), f) == d.size();
    return std::fclose(f) == 0 && ok;
}
int main(int, char** argv) {
    for (int i = 0; i < 16; i++) dev.props.pipelineCacheUUID[i] = (uint8_t)(0xa0 + i);
    const std::string dir = argv[1];
    const size_t MB = 1u << 20;
    const uint32_t V = dev.props.vendorID, D = dev.props.deviceID;
    std::vector<uint8_t> out{9, 9};
    uint64_t len = 0;
    // (this GPU's and driver's: whole, byte for byte, read once)
    const auto good = cache(MB + 77, 32, 1, V, D, -1);
    CHECK(put(dir + "/good.bin", good));
    read_bytes = 0;
    CHECK(read((dir + "/good.bin").c_str(), 32, 0, out, &len, pcache_head_ok) == Read::Ok);
    CHECK(out == good && len == good.size() && read_bytes == good.size());
    // (with no check: as before)
    read_bytes = 0;
    CHECK(read((dir + "/good.bin").c_str(), 32, 0, out, &len) == Read::Ok && out == good && read_bytes == good.size());
    // (another GPU's or driver's: its header read, not a byte more, nothing kept)
    const struct { const char* name; std::vector<uint8_t> d; } foreign[] = {
        {"vendor", cache(MB, 32, 1, 0x1002, D, -1)}, {"device", cache(MB, 32, 1, V, D + 1, -1)},
        {"uuid0", cache(MB, 32, 1, V, D, 0)}, {"uuid15", cache(MB, 32, 1, V, D, 15)},
        {"version", cache(MB, 32, 2, V, D, -1)}, {"head16", cache(MB, 16, 1, V, D, -1)},
        {"headpast", cache(MB, (uint32_t)MB + 1, 1, V, D, -1)}};
    for (const auto& c : foreign) {
        CHECK(put(dir + "/" + c.name + ".bin", c.d));
        out = {1, 2, 3};
        read_bytes = 0;
        const Read r = read((dir + "/" + c.name + ".bin").c_str(), 32, 0, out, &len, pcache_head_ok);
        if (r != Read::Foreign || !out.empty() || read_bytes != 32 || len != c.d.size()) {
            std::printf("%s: answer %d, %zu kept, %llu bytes read\n", c.name, (int)r, out.size(), (unsigned long long)read_bytes);
            return 1;
        }
        // (and as before without the check: whole)
        CHECK(read((dir + "/" + c.name + ".bin").c_str(), 32, 0, out, &len) == Read::Ok && out == c.d);
    }
    CHECK(std::string(why(Read::Foreign)).find("another GPU") != std::string::npos);
    // (short, missing, over the bound: as before, nothing read)
    CHECK(put(dir + "/short.bin", cache(32, 32, 1, V, D, -1)));
    read_bytes = 0;
    CHECK(read((dir + "/short.bin").c_str(), 32, 0, out, &len, pcache_head_ok) == Read::Short && out.empty() && !read_bytes);
    CHECK(read((dir + "/none.bin").c_str(), 32, 0, out, &len, pcache_head_ok) == Read::None && out.empty() && len == 0);
    read_bytes = 0;
    CHECK(read((dir + "/good.bin").c_str(), 32, MB, out, &len, pcache_head_ok) == Read::OverBound && out.empty() && !read_bytes);
    // (a header of 33 bytes and the rest: whole)
    const auto small = cache(33, 32, 1, V, D, -1);
    CHECK(put(dir + "/small.bin", small));
    CHECK(read((dir + "/small.bin").c_str(), 32, 0, out, &len, pcache_head_ok) == Read::Ok && out == small);
    std::printf("OK\n");
    return 0;
}
'''


def check_source(draw):
    init = block(draw, "void pcache_init() {")
    play = block(draw, "void pcache_play_open(bool same) {")
    for name, body in (("pcache_init", init), ("pcache_play_open", play)):
        reads = body.count("pcache_bound::read(")
        if reads != 1:
            fail("%s reads its file %d times" % (name, reads))
        call = body[body.index("pcache_bound::read("):]
        call = call[:call.index(";")]
        if "pcache_head_ok" not in call:
            fail("%s reads its file without checking the header first" % name)
        if "!pcache_head_ok(data.data(), data.size())" not in body:
            fail("%s no longer checks the data read before Vulkan sees it" % name)
        if "pcache_bound::Read::Foreign" not in body:
            fail("%s does not say when a file is another GPU's or driver's" % name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    vk = ROOT / "gpu" / "vk"
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    try:
        check_source(draw)
        text = FIXTURE.replace("@HEAD_OK@", block(draw, "bool pcache_head_ok(const uint8_t* head, uint64_t size) {"))
    except ValueError as e:
        fail("a text this test reads moved, or is not there (%s)" % e)
    with tempfile.TemporaryDirectory(prefix="pcache-head-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(text, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-I", str(vk), str(cpp), "-o", str(exe)],
                               capture_output=True, text=True)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        done = subprocess.run([str(exe), tmp], capture_output=True, text=True, timeout=60)
        if done.returncode or done.stdout.strip() != "OK":
            fail("the reads: " + (done.stdout + done.stderr).strip())
    print("PASS: a pipeline cache of another GPU or driver refused after its 32-byte header, a matching one read whole as "
          "before, both files' reads checked first")


if __name__ == "__main__":
    main()
