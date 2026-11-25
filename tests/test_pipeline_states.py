"""The pipeline state list: the back end's records (gpu/vk/vk_draw.cpp StateRec, StateRec2) and the tools that merge and ship the lists
agree.

A list made by one build is read by another (that is its point): its record size and magic are a file format. nx2/pipeline_states.py
merges lists into work/pipeline_states.bin, each pipeline once, and nx2/make_game.py puts that beside the game. Version 1 lists are
converted to version 2 when merged with one (or with --v2): each Vulkan format back to an NVN format (V1_NVN, checked against
vk_formats.cpp, nvn_api.h and the Vulkan headers when given), a mesh record made with the mesh fallback numbered as the native one.
Synthetic data only.
python -I -B tests/test_pipeline_states.py [--headers <Vulkan headers>]
"""
import argparse
import importlib.util
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_v1_table(tool, headers):
    """V1_NVN: each Vulkan format back to an NVN format vk_format (gpu/vk/vk_formats.cpp) makes it, by the numbers in nvn_api.h and
    the Vulkan headers (when given: RUN_ALL_ARGS)"""
    formats = (ROOT / "gpu" / "vk" / "vk_formats.cpp").read_text(encoding="utf-8")
    nvn_h = (ROOT / "gpu" / "render" / "nvn_api.h").read_text(encoding="utf-8")
    nvn = {m.group(1): int(m.group(2), 0) for m in re.finditer(r"(NVN_FORMAT_\w+)\s*=\s*(0x[0-9a-fA-F]+|\d+)", nvn_h)}
    to_vk = {nvn[n]: v for n, v in re.findall(r"case (NVN_FORMAT_\w+): return \{(VK_FORMAT_\w+),", formats)}
    core = (Path(headers) / "vulkan" / "vulkan_core.h").read_text(encoding="utf-8") if headers else None
    for vk_value, nvn_value in tool.V1_NVN.items():
        name = to_vk.get(nvn_value)
        if not name or "BLOCK" in name:
            raise SystemExit("V1_NVN: NVN %#x is no target format in vk_formats.cpp" % nvn_value)
        if core:
            value = int(re.search(r"\b%s = (\d+)," % name, core).group(1))
            if value != vk_value:
                raise SystemExit("V1_NVN: %d is not %s (%d)" % (vk_value, name, value))
    targets = {v for v in to_vk.values() if "BLOCK" not in v}
    if len(tool.V1_NVN) != len(targets):
        raise SystemExit("V1_NVN has %d formats, vk_formats.cpp %d a target can be" % (len(tool.V1_NVN), len(targets)))


def check_versions(tool):
    """Version 2 records; a version 1 list converted (formats back to NVN, a fallback mesh record numbered as the native one); a
    merge of both versions; a compute record (another build's kind) read and kept"""
    def v1(colors, depth, mesh=0, topo=3, task=0, answers=()):
        r = bytearray(tool.SIZE)
        struct.pack_into("<4Q", r, 0, 0x11, 0x22, task, 0)
        struct.pack_into("<Q", r, 32, tool.answers_hash(answers))
        struct.pack_into("<6I", r, 40, mesh, topo, len(colors), 1, depth, 1 if depth else 0)
        struct.pack_into("<%dI" % len(colors), r, 64, *colors)
        struct.pack_into("<II", r, 388, len(answers), 0)
        struct.pack_into("<%dI" % len(answers), r, 396, *answers)
        return bytes(r)

    def v2_fields(r):
        f = tool._V2.unpack(r)
        return {"variant": f[4], "mesh": f[5], "topo": f[6], "n": f[7], "has_depth": f[9], "depth": f[10], "color": f[11:19],
                "view": f[19:27], "answers": f[91:91 + f[89]], "kind": f[116]}

    a = tool.v1_to_v2(v1([122, 97], 126))   # (R11G11B10F and RGBA16F, D32F)
    f = v2_fields(a)
    if f["color"][:2] != (0x3f, 0x29) or f["view"][:2] != (0x3f, 0x29) or f["depth"] != 0x34 or f["has_depth"] != 1 or f["kind"]:
        raise SystemExit("v1 -> v2: formats %s, depth %#x" % (f["color"], f["depth"]))
    if tool.v1_to_v2(v1([1000156000], 0)) is not None:   # (a format no target can be: not converted)
        raise SystemExit("v1 -> v2: a format with no NVN twin was converted")
    # a mesh record (no task) made with the fallback: fragment answers at stage 2 (after the generated vertex stage), points
    frag_fb, frag = (2 << 28) | (1 << 12) | 2, (1 << 28) | (1 << 12) | 2
    mesh_ans = (0 << 28) | 1
    fb = v2_fields(tool.v1_to_v2(v1([37], 0, mesh=1, topo=0, answers=(mesh_ans, frag_fb))))
    native = v2_fields(tool.v1_to_v2(v1([37], 0, mesh=1, topo=3, answers=(mesh_ans, frag))))
    if fb != native or fb["topo"] != 3 or fb["answers"] != (mesh_ans, frag):
        raise SystemExit("v1 -> v2: a fallback mesh record is not the native one: %s / %s" % (fb, native))
    if tool.v1_to_v2(v1([37], 0, mesh=1, topo=0)) is not None:   # (the fallback's, its answers left out)
        raise SystemExit("v1 -> v2: a fallback record without answers was converted")
    # a compute program's record (a later build's kind): sound, kept by the merge, no point list; one holding more is not sound
    comp = tool.compute_record(0x77)
    if tool.record_faults(comp) or tool.is_point(comp) or not tool.record_faults(comp[:40] + b"\x01" + comp[41:]):
        raise SystemExit("a compute record: %s" % tool.record_faults(comp))
    if tool.record_faults(a) or tool.record_faults(a[:-8] + struct.pack("<2I", 7, 0)) != ["kind 7"]:
        raise SystemExit("a version 2 record's kind: not checked")
    tool_py = str(ROOT / "nx2" / "pipeline_states.py")
    with tempfile.TemporaryDirectory() as d:
        p1, p2, out = (os.path.join(d, n) for n in ("v1.bin", "v2.bin", "out.bin"))
        open(p1, "wb").write(tool.MAGIC + struct.pack("<I", tool.SIZE) + v1([122, 97], 126) + v1([1000156000], 0))
        open(p2, "wb").write(tool.MAGIC2 + struct.pack("<I", tool.SIZE2) + a + comp)   # (the first one again, as version 2)
        ran = subprocess.run([sys.executable, "-I", tool_py, "--out", out, p1, p2], capture_output=True, text=True)
        if ran.returncode:
            raise SystemExit(ran.stderr)
        merged = tool.read(out)
        if open(out, "rb").read(8) != tool.MAGIC2 or merged != [a, comp] or "1 version 1 pipelines not converted" not in ran.stdout:
            raise SystemExit("merge of v1 and v2: %d records\n%s%s" % (len(merged), ran.stdout, ran.stderr))
        # --v2: a version 1 list alone, converted; an .xz out reads back the same
        xz = out + ".xz"
        ran = subprocess.run([sys.executable, "-I", tool_py, "--v2", "--out", xz, p1], capture_output=True, text=True)
        if ran.returncode or open(xz, "rb").read(6) != tool.XZ_MAGIC or tool.read(xz) != [a] or \
                "1 version 1 pipelines not converted" not in ran.stdout:
            raise SystemExit("--v2: %s%s" % (ran.stdout, ran.stderr))
        # --check: both versions sound
        ran = subprocess.run([sys.executable, "-I", tool_py, "--check", p2, xz], capture_output=True, text=True)
        if ran.returncode or ran.stdout.count("sound") != 2:
            raise SystemExit("--check of version 2 lists: %s%s" % (ran.stdout, ran.stderr))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headers", help="the Vulkan headers (VkFormat numbers of the version 1 table)")
    args = ap.parse_args()
    tool = load("pipeline_states", ROOT / "nx2" / "pipeline_states.py")
    draw = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    for struct_name, size in (("StateRec", tool.SIZE), ("StateRec2", tool.SIZE2)):
        m = re.search(r"static_assert\(sizeof\(%s\) == (\d+)" % struct_name, draw)
        if not m or int(m.group(1)) != size:
            raise SystemExit("the back end's %s (%s bytes) and nx2/pipeline_states.py (%d) differ" % (struct_name, m and m.group(1), size))
    for name, want in (("kStateMagic", tool.MAGIC), ("kStateMagic2", tool.MAGIC2)):
        magic = re.search(r"%s\[8\] = \{([^}]*)\}" % name, draw).group(1)
        if "".join(re.findall(r"'(.)'", magic)).encode() != want:
            raise SystemExit("the back end's magic %s and the tool's differ" % name)
    if "triforce_pipeline_states_shipped.bin" not in draw:
        raise SystemExit("the back end does not read the shipped list")
    check_v1_table(tool, args.headers)
    check_versions(tool)

    def rec(vs, fs, topo):
        r = bytearray(tool.SIZE)
        struct.pack_into("<QQ", r, 0, vs, fs)
        struct.pack_into("<I", r, 44, topo)
        return bytes(r)

    with tempfile.TemporaryDirectory() as d:
        a, b, out = (os.path.join(d, n) for n in ("a.bin", "b.bin", "out.bin"))
        head = tool.MAGIC + struct.pack("<I", tool.SIZE)
        open(a, "wb").write(head + rec(1, 2, 3) + rec(1, 2, 4))
        open(b, "wb").write(head + rec(1, 2, 4) + rec(5, 0, 3))
        ran = subprocess.run([sys.executable, "-I", str(ROOT / "nx2" / "pipeline_states.py"), "--out", out, a, b],
                             capture_output=True, text=True)
        if ran.returncode:
            raise SystemExit(ran.stderr)
        merged = tool.read(out)
        if merged != [rec(1, 2, 3), rec(1, 2, 4), rec(5, 0, 3)] or open(out, "rb").read(8) != tool.MAGIC:
            raise SystemExit("merge: %d records, expected the 3 different ones in order, version 1" % len(merged))
        # make_game: work/pipeline_states.bin beside the game as triforce_pipeline_states_shipped.bin, none when there is none
        make_game = load("make_game_under_test", ROOT / "nx2" / "make_game.py")
        game = os.path.join(d, "game")
        os.makedirs(game)
        make_game.ROOT = d
        make_game.ship_state_list(game)
        if os.listdir(game):
            raise SystemExit("a list was shipped with none in work/")
        os.makedirs(os.path.join(d, "work"))
        os.replace(out, os.path.join(d, "work", "pipeline_states.bin"))
        make_game.ship_state_list(game)
        if tool.read(os.path.join(game, "triforce_pipeline_states_shipped.bin")) != merged:
            raise SystemExit("make_game did not ship work/pipeline_states.bin")
    print("pipeline state list: records of both versions, conversion, merge and shipping ok")


if __name__ == "__main__":
    main()
