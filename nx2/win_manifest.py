"""The game's Windows manifest, as a .res the exe links in (nx2/build.py): UTF-8 as the process's code page.

host/ and gpu/vk keep paths as UTF-8 char strings and call Windows' A functions (GetModuleFileNameA, CreateFileA, fopen ...)
with them. Without a manifest those take and give the system's ANSI code page (1252 on a Western Windows), and a game folder
whose name it cannot spell (Japanese on a Western Windows, an emoji anywhere) came back as "?": the game found neither
image.bin nor its log's folder and closed with nothing on screen. activeCodePage UTF-8 (Windows 10 1903 and newer) makes
every A function and the C runtime's narrow file functions UTF-8 for the whole process, its DLLs too (triforce_vk.dll,
SDL2, FFmpeg). host/hos_main.c says so in a message box when the Windows is too old for it and the folder's name needs it.

(Triforce) longPathAware: where Windows' own LongPathsEnabled is on (Windows 10 1607 and newer, a setting of the PC's), the A and
W functions and the C runtime's file functions take paths of MAX_PATH (260) and more, for the files the game finds in a deep
folder (the game's own nn::fs paths add the long-path prefix themselves, host/nn_fs.c fs_wide; host/hos_paths.h's and gpu/vk/vk_paths.h's
probe too). Without that setting it changes nothing.

(Triforce) HOOKSHOT_SEGMENT_HEAP=1 at the build: heapType SegmentHeap (Windows 10 2004 and newer) puts the whole process on
Windows' segment heap in place of the NT heap, its DLLs and the graphics driver too. Measured on an RX 6700 XT (AMD's Windows
driver, a cold shader preparation): 76% of the driver's compile threads' samples waited on the NT heap's lock, 12 workers ran
slower than 6, and the first part of the preparation took 1,478 s against 982 s on the segment heap; play, four pairs of
runs, within the noise. Not measured on NVIDIA, Intel or Windows 10, and the heap is fixed when the process starts, so the
arms are two exes. On by default since the lab's play A/B on an RTX card (11-22: no fps lost); HOOKSHOT_SEGMENT_HEAP=0: off. The log's "the shaders' preparation runs on" line says which heap the process has
(gpu/vk/prepare_threads.h segment_heap).

    python nx2/win_manifest.py [out.res]
"""
import os
import struct
import sys

MANIFEST = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="Hookshot.Game" version="1.0.0.0"/>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
    </windowsSettings>
  </application>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security>
  </trustInfo>
</assembly>
"""

# ((Triforce) HOOKSHOT_SEGMENT_HEAP=1: the element manifest() puts after longPathAware)
SEGMENT_HEAP = b"""      <heapType xmlns="http://schemas.microsoft.com/SMI/2020/WindowsSettings">SegmentHeap</heapType>
"""
_SEGMENT_HEAP_AFTER = b"""<longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
"""


def segment_heap_asked(environ=None):
    """(Triforce) The exe on Windows' segment heap unless HOOKSHOT_SEGMENT_HEAP=0 (the NT heap, as before). On by default since the
    lab A/B of 11-22 (the Market, 3+3, one build each way on an RTX card: 81.4 against 80.6 fps, 1% low 59.9 against 58.0)"""
    return (os.environ if environ is None else environ).get("HOOKSHOT_SEGMENT_HEAP", "").strip() != "0"


def manifest(segment_heap=False):
    """MANIFEST, with SEGMENT_HEAP in its windowsSettings when segment_heap"""
    if not segment_heap:
        return MANIFEST
    at = MANIFEST.index(_SEGMENT_HEAP_AFTER) + len(_SEGMENT_HEAP_AFTER)
    return MANIFEST[:at] + SEGMENT_HEAP + MANIFEST[at:]


RT_MANIFEST = 24
CREATEPROCESS_MANIFEST_RESOURCE_ID = 1   # (the one an exe's loader reads)


def res_entry(kind, name, data, flags=0x1030, language=0x0409):
    """one resource of a .res file (the format nx2/make_icon.py writes too): sizes, numeric type and name, flags, language"""
    header = struct.pack("<II", len(data), 32) + struct.pack("<HHHH", 0xFFFF, kind, 0xFFFF, name)
    header += struct.pack("<IHHII", 0, flags, language, 0, 0)
    return header + data + b"\0" * (-len(data) & 3)


def res_bytes(manifest=MANIFEST):
    return res_entry(0, 0, b"", 0, 0) + res_entry(RT_MANIFEST, CREATEPROCESS_MANIFEST_RESOURCE_ID, manifest)


def write(path, segment_heap=None):
    """hookshot_manifest.res at path, rewritten only when its bytes change (the link reads it each time). segment_heap: None,
    as HOOKSHOT_SEGMENT_HEAP says (segment_heap_asked)"""
    data = res_bytes(manifest(segment_heap_asked() if segment_heap is None else segment_heap))
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return path
    except OSError:
        pass
    with open(path, "wb") as f:
        f.write(data)
    return path


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "hookshot_manifest.res")))
