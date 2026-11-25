"""The pipeline state lists' checked merge and export (nx2/pipeline_states.py --check, --contrib, --export; no game, made-up
lists only).

(Triforce, 11-22, the performance audit's PIPE-11, after Source A's.) The shipped list is to grow from more than one PC's
play, so a list handed in is checked before it is merged, the merge says what each source added, and a player's list is
packed with a report of what it holds. Not ported: the in-game tour and the menu's export row.

Checks, each through the tool as a process:
  - --check: a sound list passes; a list without the head, of another record size, cut short, or with a record whose counts
    or topology are out of range, or with no first stage, is refused with why; point-list records are refused unless
    --keep-points;
  - --contrib: the positional lists, then contrib/'s *.bin.xz by name, each checked (one not sound is left out whole), each
    pipeline once in the order first met, point-list records left out (kept with --keep-points), each source's line with
    its records, what it added, its repeats and its note; the same output whatever order the files were written in;
  - --export: the list as triforce_pipeline_states.bin.xz (the same bytes) and report.txt with its counts; a list that is
    not sound makes no file;
  - the plain merge keeps every record, point lists too, as before.

    python -I -B tests/test_pipeline_contrib.py
"""
import importlib.util
import lzma
import os
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "nx2" / "pipeline_states.py"


def load():
    spec = importlib.util.spec_from_file_location("pipeline_states", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = load()


def rec(vs, fs=0, topo=3, n=1, samples=1, nvattr=2, nanswers=0, mesh=0):
    r = bytearray(tool.SIZE)
    struct.pack_into("<QQ", r, 0, vs, fs)
    struct.pack_into("<6I", r, 40, mesh, topo, n, samples, 0, 0)
    struct.pack_into("<I", r, 232, nvattr)
    struct.pack_into("<2I", r, 388, nanswers, 0)
    return bytes(r)


def listing(*recs):
    return tool.MAGIC + struct.pack("<I", tool.SIZE) + b"".join(recs)


def run(*args):
    r = subprocess.run([sys.executable, "-I", str(TOOL)] + [str(a) for a in args], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def main():
    with tempfile.TemporaryDirectory(prefix="pipeline-contrib-") as d:
        d = Path(d)
        sound = d / "sound.bin"
        sound.write_bytes(listing(rec(1, 2), rec(3, 4), rec(5, 0, topo=4)))
        code, out = run("--check", sound)
        need(code == 0 and "sound, 3 pipelines" in out, "a sound list is not passed: " + out)
        bad_cases = {
            "head.bin": (b"HKSTATE9" + listing(rec(1))[8:], "no HKSTATE2 or HKSTATE1 head"),
            "size.bin": (tool.MAGIC + struct.pack("<I", 520) + rec(1), "record size 520"),
            "cut.bin": (listing(rec(1), rec(2))[:-100], "cut short"),
            "targets.bin": (listing(rec(1), rec(2, n=9)), "9 colour targets"),
            "topology.bin": (listing(rec(1, topo=11)), "topology 11"),
            "attributes.bin": (listing(rec(1, nvattr=17)), "17 vertex attributes"),
            "answers.bin": (listing(rec(1, nanswers=25)), "25 answers"),
            "stage.bin": (listing(rec(0)), "no vertex or mesh stage"),
            "samples.bin": (listing(rec(1, samples=3)), "3 samples"),
        }
        for name, (data, why) in bad_cases.items():
            (d / name).write_bytes(data)
            code, out = run("--check", d / name)
            need(code == 1 and why in out, "%s is not refused for %s: %s" % (name, why, out))
        points = d / "points.bin"
        points.write_bytes(listing(rec(1), rec(7, topo=0)))
        code, out = run("--check", points)
        need(code == 1 and "1 point-list records" in out, "a point-list record is not refused: " + out)
        code, out = run("--check", "--keep-points", points)
        need(code == 0, "--keep-points does not allow it: " + out)
        code, out = run("--check", sound, points)
        need(code == 1, "one bad list among several does not fail the check")
        # --contrib: a base list and three players' lists, written out of their names' order
        contrib = d / "contrib"
        contrib.mkdir()
        (contrib / "c_player.bin.xz").write_bytes(lzma.compress(listing(rec(9), rec(1, 2), rec(8, topo=0))))
        (contrib / "a_player.bin.xz").write_bytes(lzma.compress(listing(rec(3, 4), rec(6))))
        (contrib / "a_player.note").write_text("a 16 GB laptop, two areas\n", encoding="utf-8")
        (contrib / "b_player.bin.xz").write_bytes(lzma.compress(listing(rec(1), rec(2, n=12))))
        (contrib / "ignored.txt").write_text("not a list", encoding="utf-8")
        merged = d / "merged.bin"
        code, out = run("--out", merged, "--contrib", contrib, sound)
        lines = out.splitlines()
        need(code == 0, "the contrib merge failed: " + out)
        need(lines[0] == "sound.bin: 3 pipelines, 3 added, 0 already in, 0 point-list records left out", "the base's line: " + lines[0])
        need(lines[1] == "a_player.bin.xz: 2 pipelines, 1 added, 1 already in, 0 point-list records left out (a 16 GB laptop, two areas)",
             "a_player's line: " + lines[1])
        need(lines[2].startswith("b_player.bin.xz: left out: ") and "12 colour targets" in lines[2], "b_player is not left out whole: " + lines[2])
        need(lines[3] == "c_player.bin.xz: 3 pipelines, 1 added, 1 already in, 1 point-list records left out", "c_player's line: " + lines[3])
        got = tool.read(str(merged))
        need(got == [rec(1, 2), rec(3, 4), rec(5, 0, topo=4), rec(6), rec(9)], "the merged records or their order: %d" % len(got))
        # the same again, the files written in another order: the same bytes
        first = merged.read_bytes()
        for f in sorted(contrib.iterdir(), reverse=True):
            data = f.read_bytes()
            f.unlink()
            f.write_bytes(data)
        code, out2 = run("--out", merged, "--contrib", contrib, sound)
        need(code == 0 and merged.read_bytes() == first and out2 == out, "the merge is not the same twice")
        code, out = run("--out", merged, "--contrib", contrib, "--keep-points", sound)
        need(rec(8, topo=0) in tool.read(str(merged)), "--keep-points does not keep a point-list record in the merge")
        # --export
        z = d / "mine.zip"
        code, out = run("--export", sound, z)
        need(code == 0 and z.exists(), "the export failed: " + out)
        with zipfile.ZipFile(z) as zf:
            need(sorted(zf.namelist()) == ["report.txt", "triforce_pipeline_states.bin.xz"], "the export's files: %s" % zf.namelist())
            need(lzma.decompress(zf.read("triforce_pipeline_states.bin.xz")) == sound.read_bytes(), "the exported list is not the list")
            report = zf.read("report.txt").decode()
            need("3 pipelines" in report and "point-list records: 0" in report and "no game code" in report, "the report: " + report)
        z2 = d / "bad.zip"
        code, out = run("--export", d / "targets.bin", z2)
        need(code == 1 and not z2.exists(), "a list that is not sound was exported")
        # the plain merge, as before: every record, point lists too
        plain = d / "plain.bin"
        code, out = run("--out", plain, points, sound)
        need(code == 0 and tool.read(str(plain)) == [rec(1), rec(7, topo=0), rec(1, 2), rec(3, 4), rec(5, 0, topo=4)],
             "the plain merge changed")
    print("PASS: pipeline state lists checked, merged by source with a report, exported with a report; the plain merge as before")


if __name__ == "__main__":
    main()
