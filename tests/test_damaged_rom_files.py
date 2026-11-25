"""An incomplete dump's damaged textures are read as a whole texture of their kind, whoever unpacked the romfs
(host/nn_fs.c OpenFile, host/oot_damaged_files.c).

The 23.3 GB dumps hold three .zs textures that start with zeros instead of a zstd frame. The builder copies a stand-in
over each (nx2/nup.py stand_in_damaged), but only in a romfs it unpacked itself; a romfs another tool unpacked kept them,
and the game asked for the model that uses the Great Fairy Fountain's floor about 15 times a second for as long as Link
stood in Kokiri or the Market.

On every system this reads the source (OpenFile asks hos_stand_in_damaged for a file opened to be read, after its own
path is known and before the open; the two helpers it needs are nn_fs.c's own, so they open with its UTF-8 and long
path CreateFileA) and holds host/oot_damaged_files.c's table to nx2/nup.py's stand_in_for: each pair is what the builder
picks for that damaged file, so the host and the builder put the same texture in its place.

On Windows it also compiles host/oot_damaged_files.c as it is, with a made-up romfs in a temporary folder (no game
bytes) and stand-ins for nn_fs.c's two helpers, and checks:
- a damaged texture (zeros where the frame starts) becomes its stand-in's path, and one line names both, once;
- the same name whole (a dump that is complete) is left as it is, with no line;
- another file is left as it is;
- a damaged texture whose stand-in is missing or damaged too is left as it is, with a line, once;
- a file that is not there is left to the open that follows.

python -I -B tests/test_damaged_rom_files.py [--cc clang]
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import nup   # noqa: E402

RUN_ALL_ARGS = ["--cc", "clang"]

HOST_FILE = ROOT / "host" / "oot_damaged_files.c"

FAIRY = "Tex/CmnTex_Map_Soil_FairyFountain_Floor_D_Nrm.bntx.zs"
FAIRY_STAND_IN = "Tex/CmnTex_Map_Sand_FairyFountain_Sand_A_Nrm.bntx.zs"
GATE = "Tex/Rock_WaterTemple_Gate_M_01_Nrm.bntx.zs"
GANON = "Tex/RBake_Scene_GanonStage_G_2_1_d0_t0.bntx.zs"
GANON_STAND_IN = "Tex/RBake_Scene_GanonStage_G_2_2_d0_t0.bntx.zs"
ZSTD = bytes((0x28, 0xb5, 0x2f, 0xfd))

HOS_H = r"""#pragma once
#include <stddef.h>
void hos_log(const char *fmt, ...);
"""

HARNESS = r"""
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
int hos_stand_in_damaged(const char *guest, char *path, size_t cap);
static const char *romfs;
static char logged[8192];
void hos_log(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    const size_t n = strlen(logged);
    vsnprintf(logged + n, sizeof logged - n - 2, fmt, a);
    va_end(a);
    strcat(logged, "\n");
}
/* (nn_fs.c's two: a file opened to be read, and a game file's host path: here content:/X is <romfs>/X) */
HANDLE hos_fs_open_read(const char *path) {
    return CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
}
int hos_fs_resolve_read(const char *guest, char *path, size_t cap) {
    const char *rel = strstr(guest, ":/");
    if (!rel) return 0;
    return (size_t)snprintf(path, cap, "%s/%s", romfs, rel + 2) < cap;
}
/* fixture <romfs> (<file under romfs> <times>)...: each file's path as OpenFile would open it after the last of its
   asks, as "open <file>: <path's part under romfs>, changed <how many of the asks changed it>" */
int main(int argc, char **argv) {
    romfs = argv[1];
    for (int i = 2; i + 1 < argc; i += 2) {
        char guest[1024], path[1024];
        int changed = 0;
        for (int n = 0; n < atoi(argv[i + 1]); n++) {
            snprintf(guest, sizeof guest, "content:/%s", argv[i]);
            snprintf(path, sizeof path, "%s/%s", romfs, argv[i]);
            changed += hos_stand_in_damaged(guest, path, sizeof path);
        }
        printf("open %s: %s, changed %d\n", argv[i], path + strlen(romfs) + 1, changed);
    }
    fputs(logged, stdout);
    return 0;
}
"""


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def table():
    """host/oot_damaged_files.c's (damaged, stand-in) pairs"""
    return re.findall(r'\{\s*"(Tex/[^"]+)",\s*"(Tex/[^"]+)"\s*\}', HOST_FILE.read_text(encoding="utf-8"))


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    failures = []

    def check(what, ok):
        if not ok:
            failures.append(what)

    pairs = table()
    check("host/oot_damaged_files.c names the three damaged textures of the 23.3 GB dumps",
          sorted(d for d, _ in pairs) == sorted((FAIRY, GATE, GANON)))
    with tempfile.TemporaryDirectory(prefix="damaged-tex-") as temporary:
        # (nup.stand_in_for's choice among the six: the damaged files as in the dump, zeros first; their stand-ins whole)
        tex = Path(temporary) / "Tex"
        for damaged, stand_in in pairs:
            write(Path(temporary) / damaged, bytes(12288) + b"rest")
            write(Path(temporary) / stand_in, ZSTD + b"whole")
        damaged_paths = {os.path.normpath(os.path.join(temporary, d)) for d, _ in pairs}
        for damaged, stand_in in pairs:
            picked = nup.stand_in_for(os.path.normpath(os.path.join(temporary, damaged)), damaged_paths)
            check("%s: the host reads %s, nup.stand_in_for picks %s" % (damaged, stand_in, picked and os.path.relpath(picked, temporary)),
                  picked and Path(picked) == tex / Path(stand_in).name)

    src = (ROOT / "host" / "nn_fs.c").read_text(encoding="utf-8")
    opened = block(src, "HLE(_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci) {")
    ask = "if (!want_write) hos_stand_in_damaged(g, path, sizeof path);"
    check("OpenFile asks for a damaged texture's stand-in, for a file opened to be read", ask in opened)
    if ask in opened:
        check("... after the file's own path is known (the mods, the overlay) and before the open",
              opened.index("HOS_FS_OVERLAY") < opened.index(ask) < opened.index("HANDLE h = CreateFileA(path,"))
    define = src.index("#define CreateFileA fs_CreateFile")
    check("nn_fs.c's own helpers open and find the files (its UTF-8 and long path CreateFileA)",
          "HANDLE hos_fs_open_read(const char *path) {" in src and "int hos_fs_resolve_read(const char *guest, char *path, size_t cap) {" in src
          and define < src.index("HANDLE hos_fs_open_read(const char *path) {"))

    if os.name != "nt":
        print("SKIP: host/oot_damaged_files.c is compiled over windows.h's file calls on Windows only")
    else:
        with tempfile.TemporaryDirectory(prefix="damaged-rom-files-") as temporary:
            folder = Path(temporary)
            (folder / "hos.h").write_text(HOS_H, encoding="utf-8")
            (folder / "oot_damaged_files.c").write_text(HOST_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            (folder / "fixture.c").write_text(HARNESS, encoding="utf-8")
            exe = folder / "fixture.exe"
            subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Wno-deprecated-declarations", "-I", str(folder),
                            str(folder / "fixture.c"), str(folder / "oot_damaged_files.c"), "-o", str(exe)], check=True, timeout=120)

            def run(romfs, *opens):
                argv = [str(exe), str(romfs).replace(os.sep, "/")]
                for rel, times in opens:
                    argv += [rel, str(times)]
                out = subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout
                paths = {m[0]: (m[1], int(m[2])) for m in re.findall(r"^open (\S+): (\S+), changed (\d+)$", out, re.M)}
                lines = [line for line in out.split("\n") if line.startswith("fs:")]
                return paths, lines

            # An incomplete dump as another tool unpacked it: the three textures zeros first, the stand-ins whole
            damaged_romfs = folder / "incomplete" / "romfs"
            write(damaged_romfs / FAIRY, bytes(12288) + b"after the zeros")
            write(damaged_romfs / FAIRY_STAND_IN, ZSTD + b"sand floor")
            write(damaged_romfs / GANON, bytes(4096) + b"ganon's own")
            write(damaged_romfs / GANON_STAND_IN, bytes(4096) + b"damaged stand-in")   # (damaged too: not taken)
            write(damaged_romfs / "Tex/Other_Nrm.bntx.zs", ZSTD + b"other")
            paths, lines = run(damaged_romfs, (FAIRY, 15), (GANON, 3), ("Tex/Other_Nrm.bntx.zs", 1), (GATE, 1))
            check("a damaged texture opens its stand-in, at each of 15 opens (%r)" % (paths.get(FAIRY),),
                  paths.get(FAIRY) == (FAIRY_STAND_IN, 15))
            fairy_lines = [line for line in lines if FAIRY in line]
            check("one line names the damaged texture and its stand-in, once in 15 opens (%r)" % fairy_lines,
                  len(fairy_lines) == 1 and Path(FAIRY_STAND_IN).name in fairy_lines[0])
            check("the line says the dump is incomplete and what to do (%r)" % fairy_lines,
                  len(fairy_lines) == 1 and "incomplete" in fairy_lines[0] and "dump the game again" in fairy_lines[0].lower())
            check("a damaged texture with no whole stand-in is read as it is (%r)" % (paths.get(GANON),), paths.get(GANON) == (GANON, 0))
            ganon_lines = [line for line in lines if GANON in line]
            check("a damaged texture with no whole stand-in is said once in 3 opens (%r)" % ganon_lines, len(ganon_lines) == 1)
            check("another file is read as it is (%r)" % (paths.get("Tex/Other_Nrm.bntx.zs"),),
                  paths.get("Tex/Other_Nrm.bntx.zs") == ("Tex/Other_Nrm.bntx.zs", 0))
            check("a file that is not there is left to the open (%r)" % (paths.get(GATE),), paths.get(GATE) == (GATE, 0))
            check("two lines in all (%r)" % lines, len(lines) == 2)

            # A complete dump: the same names whole, read as they are and nothing said
            whole_romfs = folder / "complete" / "romfs"
            write(whole_romfs / FAIRY, ZSTD + b"fairy floor")
            write(whole_romfs / FAIRY_STAND_IN, ZSTD + b"sand floor")
            paths, lines = run(whole_romfs, (FAIRY, 2))
            check("a whole texture under a damaged name is read as it is (%r)" % (paths.get(FAIRY),), paths.get(FAIRY) == (FAIRY, 0))
            check("a complete dump logs nothing (%r)" % lines, not lines)

    if failures:
        for failure in failures:
            print("FAIL: " + failure)
        raise SystemExit("an incomplete dump's damaged textures are not read as their stand-ins")
    print("ok: damaged textures read as their stand-ins, whole ones as they are, the table as nup.stand_in_for picks")


if __name__ == "__main__":
    main()
