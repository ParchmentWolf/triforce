"""Windows' segment heap for the exe, at the build's choice (HOOKSHOT_SEGMENT_HEAP=1, nx2/win_manifest.py).

On AMD's Windows driver the shader preparation's compiles waited on the NT heap's lock (76% of the driver's samples in
RtlAllocateHeap/RtlFreeHeap's critical section): heapType SegmentHeap in the exe's manifest puts the whole process on the
segment heap. The heap is fixed when the process starts, so the two arms are two exes; on by default since the 11-22 play A/B (HOOKSHOT_SEGMENT_HEAP=0: off).

What must hold: with HOOKSHOT_SEGMENT_HEAP=0 the manifest is as it was (no heapType); unset or 1, one heapType SegmentHeap in
the 2020 WindowsSettings namespace inside windowsSettings, the UTF-8 code page and longPathAware kept; write() follows the
variable, and nx2/build.py links write()'s .res. gpu/vk/prepare_threads.h's heap_name and the log line of vk_draw.cpp's
prepare_workers are checked by tests/test_prepare_threads.py. On Windows a probe that prints the signature at byte 16 of
GetProcessHeap() is linked with each .res: 0xDDEEDDEE (the segment heap) with the element, 0xFFEEFFEE (the NT heap) without.

    python -I -B tests/test_segment_heap.py [--cc clang]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import win_manifest  # noqa: E402

WS2016 = "{http://schemas.microsoft.com/SMI/2016/WindowsSettings}"
WS2019 = "{http://schemas.microsoft.com/SMI/2019/WindowsSettings}"
WS2020 = "{http://schemas.microsoft.com/SMI/2020/WindowsSettings}"
fails = []

PROBE = r"""
#include <windows.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    unsigned sig = 0;
    memcpy(&sig, (const char*)GetProcessHeap() + 16, sizeof sig);
    void* p[64];
    for (int i = 0; i < 64; i++) p[i] = HeapAlloc(GetProcessHeap(), 0, 64 + i * 100);
    for (int i = 0; i < 64; i++) HeapFree(GetProcessHeap(), 0, p[i]);
    printf("0x%08X\n", sig);
    return 0;
}
"""


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fails.append(what)


def settings(text):
    """[(tag, text)] of a manifest's windowsSettings, in order"""
    root = ET.fromstring(text)
    for el in root.iter():
        if el.tag.endswith("}windowsSettings"):
            return [(s.tag, (s.text or "").strip()) for s in el]
    return []


def check_manifest():
    check(hasattr(win_manifest, "manifest") and hasattr(win_manifest, "segment_heap_asked"),
          "nx2/win_manifest.py has manifest() and segment_heap_asked()")
    if fails:
        return
    plain = win_manifest.manifest(False)
    check(plain == win_manifest.MANIFEST, "without the segment heap: the manifest as it was")
    check(b"heapType" not in plain, "without the segment heap: no heapType")
    on = win_manifest.manifest(True)
    s = settings(on)
    heap = [t for tag, t in s if tag == WS2020 + "heapType"]
    check(heap == ["SegmentHeap"], "with it: one heapType SegmentHeap, 2020 namespace, inside windowsSettings")
    check(not any(tag.endswith("}heapType") and tag != WS2020 + "heapType" for tag, _ in s), "no heapType in another namespace")
    check((WS2019 + "activeCodePage", "UTF-8") in s and (WS2016 + "longPathAware", "true") in s,
          "with it: the UTF-8 code page and longPathAware kept")
    check(on.replace(win_manifest.SEGMENT_HEAP, b"") == plain, "with it: nothing else changed")
    for env, want in (({}, True), ({"HOOKSHOT_SEGMENT_HEAP": ""}, True), ({"HOOKSHOT_SEGMENT_HEAP": "0"}, False),
                      ({"HOOKSHOT_SEGMENT_HEAP": " 0 "}, False), ({"HOOKSHOT_SEGMENT_HEAP": "1"}, True),
                      ({"HOOKSHOT_SEGMENT_HEAP": " 1 "}, True)):
        check(win_manifest.segment_heap_asked(env) == want, "HOOKSHOT_SEGMENT_HEAP %r: %s" % (env.get("HOOKSHOT_SEGMENT_HEAP"),
                                                                                          "on" if want else "off"))
    with tempfile.TemporaryDirectory(prefix="segment-heap-") as tmp:
        res = os.path.join(tmp, "m.res")
        was = os.environ.pop("HOOKSHOT_SEGMENT_HEAP", None)
        try:
            win_manifest.write(res)
            check(open(res, "rb").read() == win_manifest.res_bytes(on), "write(), the variable unset: the .res with heapType (on by default)")
            os.environ["HOOKSHOT_SEGMENT_HEAP"] = "0"
            win_manifest.write(res)
            check(open(res, "rb").read() == win_manifest.res_bytes(), "write(), HOOKSHOT_SEGMENT_HEAP=0: the .res as it was")
            check(open(win_manifest.write(res, False), "rb").read() == win_manifest.res_bytes(), "write(path, False): as it was")
        finally:
            os.environ.pop("HOOKSHOT_SEGMENT_HEAP", None)
            if was is not None:
                os.environ["HOOKSHOT_SEGMENT_HEAP"] = was
    build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    start = build.index('exe = os.path.join(out, "Triforce.exe")')
    check("win_manifest.write(" in build[start:build.index("capture_output=True", start)], "nx2/build.py links write()'s .res")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOOKSHOT_SEGMENT_HEAP=0`" in docs, "docs/development.md has HOOKSHOT_SEGMENT_HEAP")


def windows_cc(given):
    if given:
        return given
    if os.name == "nt":
        return shutil.which("clang")
    mingw = os.environ.get("HOOKSHOT_MINGW", "")
    cc = os.path.join(mingw, "bin", "x86_64-w64-mingw32-clang")
    return cc if mingw and os.path.exists(cc) else None


def check_probe(cc_arg):
    cc = windows_cc(cc_arg)
    if not cc:
        print("SKIP probe: no compiler for Windows here (clang on Windows, or HOOKSHOT_MINGW=<llvm-mingw>)")
        return
    with tempfile.TemporaryDirectory(prefix="segment-heap-") as tmp:
        tmp = Path(tmp)
        src = tmp / "probe.c"
        src.write_text(PROBE, encoding="utf-8")
        target = [] if os.name == "nt" or "mingw32" in os.path.basename(cc) else ["--target=x86_64-w64-mingw32"]
        flags = target + ["-std=c11", "-O0", "-Wall", "-Wextra", "-Werror", "-fuse-ld=lld"]
        arms = []
        for name, on, want in (("segment", True, "0xDDEEDDEE"), ("nt", False, "0xFFEEFFEE")):
            res = win_manifest.write(str(tmp / (name + ".res")), on)
            exe = tmp / ("probe_%s.exe" % name)
            subprocess.run([cc] + flags + [str(src), res, "-o", str(exe)], check=True)
            arms.append((name, exe, want))
        if os.name != "nt":
            print("probe built for Windows; it runs on Windows only")
            return
        for name, exe, want in arms:
            got = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.strip()
            check(got == want, "probe with the %s .res: process heap signature %s (want %s)" % (name, got, want))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="")
    args = parser.parse_args()
    check_manifest()
    if not fails:
        check_probe(args.cc)
    if fails:
        raise SystemExit("FAIL: %d check(s)" % len(fails))
    print("PASS: the segment heap at the build's choice")


if __name__ == "__main__":
    main()
