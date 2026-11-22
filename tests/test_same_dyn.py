"""A draw does not rebuild dynamic state that matches the draw before it.

python -I -B tests/test_same_dyn.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    source = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    fn = block(source, "bool dyn_same(")
    pack = block(source, "int dyn_pack(")
    for needle in ("s.viewport", "s.scissor", "s.chmask", "s.blend", "s.ds", "cur_program", "s.poly"):
        if needle not in pack:
            raise SystemExit(f"dynamic state is remembered without {needle}")
    # (the program in the key is what its write masks are made from: a draw of another program with the same masks is the same state)
    if "program_wm_sig(*cur_program)" not in pack or "RX_VK_DYN_PROG_KEY" not in pack:
        raise SystemExit("dynamic state is remembered by program, not by what the program makes of the write masks")
    reads = lambda text: set(re.findall(r"info\.(\w+)", text))
    mask, sig = block(source, "uint32_t target_write_mask("), block(source, "uint64_t program_wm_sig(")
    if reads(mask) != reads(sig):
        raise SystemExit(f"target_write_mask reads {sorted(reads(mask))} but the program's write mask word is made from {sorted(reads(sig))}")
    body = block(source, "void dynamic_state(")
    if body.index("dyn_same(") > body.index("std::memset(&d, 0"):
        raise SystemExit("dynamic state is built before checking the draw before it")
    guard = body[:body.index("dyn_same(")]
    if "last_dyn_valid" not in guard:
        raise SystemExit("a clear's dynamic state is left unset")
    # ((Triforce, 11-22, the performance audit's DESC-06, after Source A's) the words and the bytes by one memcmp each, the
    # floats still by value: the same answers as the three loops gave, at the last word and the last byte too, with -0 the
    # same as 0 and a NaN the same as nothing
    if fn.count("std::memcmp(") != 2 or "if (fp[i] != cfp[i]) return false;" not in fn:
        raise SystemExit("dyn_same does not compare its floats by value and its words and bytes by two memcmp")
    fixture = f'''#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#define CHECK(x) do {{ if (!(x)) {{ std::fprintf(stderr, "FAIL:%d %s\\n", __LINE__, #x); std::exit(1); }} }} while (0)
{fn}
int main() {{
    float fp[2]{{1.f, 2.f}}, cfp[2]{{1.f, 2.f}};
    uint32_t up[2]{{3, 4}}, cup[2]{{3, 4}};
    uint8_t raw[2]{{5, 6}}, craw[2]{{5, 6}};
    CHECK(dyn_same(fp, 2, up, 2, raw, 2, cfp, cup, craw));
    cfp[1] = 9.f;
    CHECK(!dyn_same(fp, 2, up, 2, raw, 2, cfp, cup, craw));
    cfp[1] = 2.f;
    cup[0] = 8;
    CHECK(!dyn_same(fp, 2, up, 2, raw, 2, cfp, cup, craw));
    cup[0] = 3;
    craw[1] = 7;
    CHECK(!dyn_same(fp, 2, up, 2, raw, 2, cfp, cup, craw));
    CHECK(!dyn_same(fp, 0, up, 2, raw, 2, cfp, cup, craw));
    craw[1] = 6;
    CHECK(!dyn_same(fp, 2, up, 0, raw, 2, cfp, cup, craw));
    CHECK(!dyn_same(fp, 2, up, 2, raw, 0, cfp, cup, craw));
    CHECK(dyn_same(fp, 2, up, 2, raw, 2, cfp, cup, craw));
    // (the sizes the draw uses: 13 floats, 35 words, 160 bytes; a difference in the last of each, and only there)
    float f13[13], g13[13];
    uint32_t u35[35], v35[35];
    uint8_t b160[160], c160[160];
    for (int i = 0; i < 13; i++) f13[i] = g13[i] = (float)i * 0.5f;
    for (int i = 0; i < 35; i++) u35[i] = v35[i] = 0x01010101u * (uint32_t)i;
    for (int i = 0; i < 160; i++) b160[i] = c160[i] = (uint8_t)(i * 7);
    CHECK(dyn_same(f13, 13, u35, 35, b160, 160, g13, v35, c160));
    v35[34] ^= 0x80000000u;
    CHECK(!dyn_same(f13, 13, u35, 35, b160, 160, g13, v35, c160));
    CHECK(dyn_same(f13, 13, u35, 34, b160, 160, g13, v35, c160));   // (the last word is past the count: not looked at)
    v35[34] = u35[34], v35[0] ^= 1;
    CHECK(!dyn_same(f13, 13, u35, 35, b160, 160, g13, v35, c160));
    v35[0] = u35[0], c160[159] ^= 1;
    CHECK(!dyn_same(f13, 13, u35, 35, b160, 160, g13, v35, c160));
    CHECK(dyn_same(f13, 13, u35, 35, b160, 159, g13, v35, c160));   // (the last byte is past the count: not looked at)
    c160[159] = b160[159], g13[12] += 0.25f;
    CHECK(!dyn_same(f13, 13, u35, 35, b160, 160, g13, v35, c160));
    g13[12] = f13[12];
    f13[0] = 0.0f, g13[0] = -0.0f;   // (-0 is 0: by value, not by its bits)
    CHECK(std::memcmp(&f13[0], &g13[0], sizeof(float)) != 0 && dyn_same(f13, 13, u35, 35, b160, 160, g13, v35, c160));
    f13[5] = g13[5] = std::nanf("");   // (a NaN is the same as nothing, itself included: the state is built again)
    CHECK(!dyn_same(f13, 13, u35, 35, b160, 160, g13, v35, c160));
    std::printf("PASS: the same dynamic state is not built again\\n");
}}
'''
    with tempfile.TemporaryDirectory(prefix="same-dyn-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / "fixture"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
