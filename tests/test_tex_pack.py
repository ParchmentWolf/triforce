"""(Triforce, 11-24) Evil HD's texture pack key (gpu/vk/tex_pack.h): the renderer and the pack's tool (D:/src/tools/texpack)
name a texture the same way. No game, no GPU: compiles the header and checks the key against values computed here the same
way (FNV-1a 64 over the first 16 KB, then the width's and height's bytes), the file name, and which shapes are wanted.

    python -I -B tests/test_tex_pack.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]
NL = chr(10)


def fnv(data, w, h):
    v = 1469598103934665603
    for b in data[:16384]:
        v = ((v ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    for x in (w, h):
        for k in range(4):
            v = ((v ^ ((x >> (8 * k)) & 0xFF)) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return v


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    data = bytes((i * 37 + 11) & 0xFF for i in range(20000))
    cases = [(len(data), 512, 512), (1000, 256, 256), (16384, 1024, 512)]
    checks = "".join("    CHECK(tex_pack::key(data, %d, %d, %d) == %dull);%s" % (n, w, h, fnv(data[:n], w, h), NL) for n, w, h in cases)
    src = NL.join([
        "#include <cstdio>",
        "#include <cstdlib>",
        "#include <cstring>",
        '#include "tex_pack.h"',
        '#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\\n", __LINE__, #x); std::exit(1); } } while (0)',
        "using namespace mkwvk;",
        "int main() {",
        "    static unsigned char data[20000];",
        "    for (int i = 0; i < 20000; i++) data[i] = (unsigned char)((i * 37 + 11) & 0xFF);",
        checks,
        "    char name[21];",
        "    tex_pack::file_name(0x00ab00cd00ef0012ull, name);",
        '    CHECK(!std::strcmp(name, "00ab00cd00ef0012.png"));',
        "    CHECK(tex_pack::wanted(true, 1, true, 256, 256) && !tex_pack::wanted(true, 1, true, 255, 512));",
        "    CHECK(!tex_pack::wanted(false, 1, true, 512, 512) && !tex_pack::wanted(true, 2, true, 512, 512));",
        "    CHECK(!tex_pack::wanted(true, 1, false, 512, 512));",
        '    std::puts("PASS: the texture pack\'s key, file name and shapes");',
        "}",
        ""])
    with tempfile.TemporaryDirectory(prefix="tex-pack-") as tmp:
        cpp, exe = Path(tmp) / "t.cpp", Path(tmp) / "t.exe"
        cpp.write_text(src, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Werror", "-I" + str(ROOT / "gpu" / "vk"), str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=30)


if __name__ == "__main__":
    main()
