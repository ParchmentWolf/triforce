"""Game-free: the button prompts' font patch at run time (host/prompts.c cmap4_glyph, cmap4_bind) on a cmap made the way the
build makes it (nx2/prompt_assets.py cmap4): a bound Switch button's code point gets its pad input's icon, an unbound one keeps
its own, and the pad icons stay. Also the faces' order: host/prompts.c faces[], gpu/vk/vk_api.h HOS_PROMPT_* and
nx2/prompt_faces.py FACES (after the Switch).

python -I -B tests/test_prompt_font_bind.py [--cc gcc]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import prompt_assets  # noqa: E402
import prompt_faces  # noqa: E402

# (the Switch buttons bound in the test: A to the bottom face button, B to the right shoulder; the rest unbound)
BIND = {0: 0, 1: 10}


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


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
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "prompts.c").read_text(encoding="utf-8")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")

    faces = re.search(r"faces\[HOS_PROMPT_N\] = \{([^}]*)\}", src)
    check(faces is not None, "host/prompts.c has no faces[HOS_PROMPT_N]")
    names = re.findall(r'"([a-z0-9]+)"', faces.group(1))
    check(names == ["switch"] + list(prompt_faces.FACES), "faces[] %s is not the Switch then prompt_faces.FACES" % names)
    enum = re.search(r"enum \{ (HOS_PROMPT_SWITCH[^}]*)\}", api)
    check(enum is not None, "gpu/vk/vk_api.h has no HOS_PROMPT_* enum")
    ids = [e.strip() for e in enum.group(1).split(",") if e.strip()]
    check(ids == ["HOS_PROMPT_" + n.upper() for n in names] + ["HOS_PROMPT_N"], "HOS_PROMPT_* %s is not faces[]" % ids)

    # the codes: the Switch buttons on glyphs 100.., the pad icons on 200.. (as face_font: each Switch code a segment of its own)
    mapping = {c: 100 + b for b, c in enumerate(prompt_assets.SWITCH)}
    mapping.update({prompt_assets.PAD_BASE + i: 200 + i for i in range(len(prompt_assets.PADS))})
    cmap = prompt_assets.cmap4(mapping, set(prompt_assets.SWITCH))
    sub = cmap[20:]   # (one format 4 subtable, after the cmap's header and its two records)
    codes = list(prompt_assets.SWITCH) + [prompt_assets.PAD_BASE + i for i in range(len(prompt_assets.PADS))]

    harness = "\n".join([
        "#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>", '#include "gpu/vk/vk_api.h"',
        "#define PAD_BASE 0xF700",
        "static int hos_binding(int set, int button, int slot) {",
        "    (void)slot;",
        "    if (set != HOS_BIND_PAD) return -1;",
        *("    if (button == %d) return %d;" % kv for kv in BIND.items()),
        "    return -1;",
        "}",
        re.search(r"static const uint16_t switch_code\[HOS_SW_N\] = \{[^}]*\};", src).group(0),
        src[src.index("#define LIVE_FACES"):src.index("static int game_dir(")],
        re.search(r"static unsigned rd16\(.*", src).group(0),
        re.search(r"static uint32_t rd32\(.*", src).group(0),
        re.search(r"static void wr16\(.*", src).group(0),
        block(src, "static unsigned cmap4_glyph("),
        block(src, "static int bound_input("),
        block(src, "static int cmap4_point("),
        block(src, "static int text_code("),
        block(src, "static int cmap4_bind("),
        block(src, "static int bind_font("),
        # (a controller's face: the keyboard and mouse face's keys are tests/test_prompt_keys.py's)
        "int main(int argc, char **argv) {",
        "    FILE *f = fopen(argv[1], \"rb\");",
        "    static unsigned char st[65536];",
        "    const size_t n = fread(st, 1, sizeof st, f);",
        "    fclose(f);",
        "    if (argc > 2 && !strcmp(argv[2], \"font\")) { printf(\"%d\\n\", bind_font(st, n, HOS_PROMPT_XBOX)); return 0; }",
        "    if (argc > 2 && !strcmp(argv[2], \"text\")) {   /* ((Triforce) text_code on these controls, the PS5 face) */",
        "        int bind[HOS_SW_N];",
        "        for (int b = 0; b < HOS_SW_N; b++) bind[b] = hos_binding(HOS_BIND_PAD, b, 0);",
        "        for (int i = 3; i < argc; i++) printf(\"%d\\n\", text_code((unsigned)strtoul(argv[i], NULL, 0), HOS_PROMPT_PS5, bind));",
        "        return 0;",
        "    }",
        "    printf(\"%d\\n\", cmap4_bind(st, n, HOS_PROMPT_XBOX));",
        "    for (int i = 2; i < argc; i++) printf(\"%u\\n\", cmap4_glyph(st, n, (unsigned)strtoul(argv[i], NULL, 0)));",
        "    return 0;",
        "}", ""])
    with tempfile.TemporaryDirectory() as tmp:
        c, exe, bin_ = Path(tmp) / "bind.c", Path(tmp) / "bind", Path(tmp) / "cmap4.bin"
        c.write_text(harness, encoding="utf-8")
        bin_.write_bytes(sub)
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(c), "-o", str(exe)], check=True)
        out = subprocess.run([str(exe), str(bin_)] + [str(x) for x in codes], check=True, capture_output=True,
                             text=True).stdout.split()
        # (a font whose cmap names a subtable at 0xFFFFFFF4: offset + 14 wrapped, and the check read 4 GB past the font)
        font = Path(tmp) / "wrap.otf"
        cmap_table = (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + bytes(4) + (0xFFFFFFF4).to_bytes(4, "big")
        font.write_bytes(bytes(4) + (1).to_bytes(2, "big") + bytes(6) + b"cmap" + bytes(4) + (28).to_bytes(4, "big") +
                         len(cmap_table).to_bytes(4, "big") + cmap_table)
        wrapped = subprocess.run([str(exe), str(font), "font"], capture_output=True, text=True)
        check(wrapped.returncode == 0 and wrapped.stdout.split() == ["0"],
              "a cmap subtable offset that wraps: exit %d, %r" % (wrapped.returncode, wrapped.stdout))
        faces_out = faces_cmap(exe, Path(tmp))
        text_out = subprocess.run([str(exe), str(bin_), "text"] + [str(x) for x in TEXT_CODES], check=True,
                                  capture_output=True, text=True).stdout.split()
    check_faces(faces_out)
    check_text([int(x) for x in text_out])
    done, got = int(out[0]), [int(x) for x in out[1:]]
    check(done == len(BIND), "%d buttons bound, not %d" % (done, len(BIND)))
    for b, code in enumerate(prompt_assets.SWITCH):
        want = 200 + BIND[b] if b in BIND else 100 + b
        check(got[b] == want, "Switch button %d (U+%04X): glyph %d, not %d" % (b, code, got[b], want))
    for i in range(len(prompt_assets.PADS)):
        check(got[len(prompt_assets.SWITCH) + i] == 200 + i, "pad icon %d moved" % i)
    print("ok: %d of %d Switch buttons pointed at their pad icons, the rest and the pad icons kept; in a font with every face's "
          "icons, the Xbox face's; a text's codes rewritten to the PS5 face's" % (done, len(prompt_assets.SWITCH)))


# ((Triforce) the live part) a font with every controller face's codes (as faces_font: the Xbox face's icons on glyphs 300.., its
# d-pad on 400..; the Switch buttons' and the d-pad's codes each a segment of their own): cmap4_bind for the Xbox face points
# each Switch button at the Xbox face's icon of its input (an unbound one at its default's), the d-pad at the Xbox face's
FACE_GLYPH, STATIC_GLYPH, OWN_STATIC = 300, 400, 50
XBOX, PS5 = 1, 3   # (HOS_PROMPT_*)


def faces_cmap(exe, tmp):
    pa = prompt_assets
    mapping = {c: 100 + b for b, c in enumerate(pa.SWITCH)}
    mapping.update({c: OWN_STATIC + k for k, c in enumerate(pa.STATIC)})
    base = pa.FACE_BASE + pa.FACE_CODES * XBOX
    mapping.update({base + i: FACE_GLYPH + i for i in range(len(pa.PADS))})
    mapping.update({base + pa.STATIC_AT + k: STATIC_GLYPH + k for k in range(len(pa.STATIC))})
    path = tmp / "faces.bin"
    path.write_bytes(pa.cmap4(mapping, set(pa.SWITCH) | set(pa.STATIC))[20:])
    return subprocess.run([str(exe), str(path)] + [str(x) for x in list(pa.SWITCH) + list(pa.STATIC)], check=True,
                          capture_output=True, text=True).stdout.split()


def check_faces(out):
    pa = prompt_assets
    done, got = int(out[0]), [int(x) for x in out[1:]]
    check(done == len(BIND), "faces: %d buttons bound, not %d" % (done, len(BIND)))
    for b, code in enumerate(pa.SWITCH):
        pad = BIND[b] if b in BIND else pa.PADS.index(pa.DEFAULT[b])
        check(got[b] == FACE_GLYPH + pad, "faces: Switch button %d (U+%04X): glyph %d, not the Xbox face's %d" %
              (b, code, got[b], FACE_GLYPH + pad))
    for k in range(len(pa.STATIC)):
        check(got[len(pa.SWITCH) + k] == STATIC_GLYPH + k, "faces: the d-pad's icon %d is not the Xbox face's" % k)


# a text's codes: A and B as the game has them, A on the Switch face's code for the north button, the d-pad, the Xbox face's
# d-pad icon, a letter (none of a button's: left as it is)
TEXT_CODES = [0xE040, 0xE041, prompt_assets.BIND_BASE + 3, 0xE049,
              prompt_assets.FACE_BASE + prompt_assets.FACE_CODES * XBOX + prompt_assets.STATIC_AT + 1, 0x41]


def check_text(got):
    pa = prompt_assets
    sw, npads = len(pa.SWITCH), len(pa.PADS)
    bind = pa.BIND_BASE + PS5 * sw * npads
    want = [bind + 0 * npads + BIND[0], bind + 1 * npads + BIND[1], bind + 0 * npads + BIND[0],
            pa.FACE_BASE + pa.FACE_CODES * PS5 + pa.STATIC_AT, pa.FACE_BASE + pa.FACE_CODES * PS5 + pa.STATIC_AT + 1, -1]
    check(got == want, "text_code: %s, not %s" % (got, want))
    check(pa.BIND_BASE + len(pa.LIVE_FACES) * sw * npads <= pa.PAD_BASE, "the bind codes reach the pad icons'")
    check(pa.FACE_BASE >= pa.PAD_BASE + 256, "the faces' codes among the keyboard face's keys (U+F700 + a key code)")


if __name__ == "__main__":
    main()
