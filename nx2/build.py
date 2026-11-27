"""Compile the lifted game (work/gen, from `lift.py --write`) into work/build/hookshot_game.dll (or a static library).

The flags are a64-kit's for lifted code (its build.py, cmd_native): -O1, LoopRotate's header copies capped (most of
the compile time in goto-dense giant functions otherwise), capture tracking past LLVM's 100 uses (the context
parameter is A64_NOESC), one section per function. The guest model is the 64-bit window (rtgen.py), shadowing the
vendored rt/, with the loop-header interrupt polls on (A64_POLLING, nx2/poll.py). Incremental: an object is rebuilt
only when its source or the flags changed.

hookshot_game.dll = the lifted chunks + a64-kit's tables and runtime + nx2/rt/eden_shim.c (the emulator ABI, mkw_host.h)
+ mkw_info.c (the image base and main's build id, generated here from work/image/image.json). Linking it is also the
check that the whole lifted game closes over itself: any unresolved symbol fails the link.

Heavy: 44 chunks of ~25 MB, ~100-200 s and ~2-3.5 GB each at -O1. The PC is shared with games: run it when the
machine is idle, and keep --jobs low otherwise.

--standalone builds work/sa/build/Triforce.exe instead: the standalone lift (work/sa/gen, `lift.py --standalone --write`)
+ the native runtime in host/ (TOTKPort's hos/, adapted). Objects are cached by their key in work/objcache, shared by
both builds: the two lifts share their chunk boundaries, so every chunk without a hooked function is the same source
and is not compiled twice.

Usage:  python -I nx2/build.py [--jobs 1] [--only 0,7] [--opt O1] [--no-polls] [--dll] [--lib] [--standalone]
  --only: just these code_NNN.c chunks (to measure); --dll: link hookshot_game.dll; --lib: archive hookshot_game.lib
  --dry-run: the start-up with no lift, up to the compile; fails if a file the compile reads (the lift's aside) is missing

  HOOKSHOT_TIMES=<build_times.json>: make_game.py's record of the earlier builds. With it, this run says which files it
  really rebuilds and how long each took before (@@plan, @@file, @@eta), which the builder windows show as a countdown.
"""
import argparse
import concurrent.futures
import contextlib
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (python -I leaves the script folder off)
import kit
import cold_parts
import lifted_c
import rtgen
import logo_rgba
import object_store
import reshade_fx   # ((Triforce) the ReShade FX compiler's jobs: gpu/vk/reshade
import ui_fonts
import toolchain
import version
import win_manifest

NX2_RT = os.path.join(kit.HERE, "rt")
HOST = os.path.join(kit.HERE, "..", "host")
OPUS = os.path.join(kit.HERE, "..", "third_party", "opus")
# (Triforce) zstd's decoder as the runtime compiles it (third_party/zstd/lib; host/host_zstd.h): every file the decoder needs,
# and none of the rest. tests/test_host_zstd.py compiles the same list
HOST_ZSTD_SOURCES = ("common/debug.c", "common/entropy_common.c", "common/error_private.c", "common/fse_decompress.c",
                     "common/xxhash.c", "common/zstd_common.c", "decompress/huf_decompress.c", "decompress/zstd_ddict.c",
                     "decompress/zstd_decompress.c", "decompress/zstd_decompress_block.c")
OBJ_CACHE = os.path.join(kit.WORK, "objcache")
# ((Triforce) HOOKSHOT_OBJ_STORE: one store of objects for every work folder, nx2/object_store.py. Its folder for this work
# folder's compiler and headers, or None (off unless set))
OBJ_STORE = object_store.folder(kit.WORK)
# (hookshot) work/hot_order.txt: the functions that run, hottest first (sampled), packed together by the linker; RX_NO_ORDER=1: off
PGO = os.environ.get("RX_PGO", "")
# ((Triforce, 11-21, the performance audit's LIFT-10, after Source A's) RX_VK_PGO: the renderer's own code (gpu/vk/*.cpp, not
# the vendored recompiler, ImGui or zstd) with a play profile. The back end runs the replay on the game's render thread, and
# was built at plain -O2 whatever it does most. "gen": it counts its branches (host/pgo_rt.c in the DLL, RX_VK_PGO_FILE=<path>
# in the run: <path>.reset clears the counters, <path>.dump writes them to <path>; llvm-profdata merge makes the profile).
# <file>: built with that profile. Not set, empty or 0: neither, as before (nx2/make_game.py passes a shipped profile).
VK_PGO = os.environ.get("RX_VK_PGO", "")


def vk_pgo_flags(asked=None):
    """The flags RX_VK_PGO adds to the renderer's own files. asked: its value (the environment's when not given)"""
    asked = VK_PGO if asked is None else asked
    if asked in ("", "0"):
        return []
    if asked == "gen":
        return ["-fprofile-instr-generate", "-mllvm", "-disable-vp=true"]
    # (the profile's contents in the flags the object key hashes, as the hot code's: its path names no key, flag_text)
    with open(asked, "rb") as f:
        sha = hashlib.sha1(f.read(), usedforsecurity=False).hexdigest()[:16]
    return ["-fprofile-instr-use=" + asked, "-DTRIFORCE_VK_PROFILE_SHA1=" + sha, "-Wno-profile-instr-out-of-date",
            "-Wno-profile-instr-unprofiled"]


# (linux) Linux builds: an ELF executable and triforce_vk.so, the Win32 calls of host/ and gpu/vk on POSIX
# (host/posix: its windows.h is found first), the window and sound on SDL2. HOOKSHOT_SYSROOT=<dir>: compile and link
# against that root (the AppImage's: glibc 2.35, so the game runs on older systems than the one that built it).
# HOOKSHOT_VK_PREBUILT=<triforce_vk.so>: the Vulkan back end as built already (the AppImage's), not compiled here.
LINUX = not toolchain.windows()   # (hookshot: RX_TARGET=windows on Linux builds the Windows game, with llvm-mingw)
POSIX = os.path.join(kit.HERE, "..", "host", "posix")
SYSROOT = os.environ.get("HOOKSHOT_SYSROOT", "")
EXE = "triforce" if LINUX else "Triforce.exe"
VK_LIB = "triforce_vk.so" if LINUX else "triforce_vk.dll"


def repro_link(asked=None, linux=None):
    """(Triforce, 11-22, the performance audit's IO-45, after Source A's) What HOOKSHOT_LINK_REPRO=1 adds to the Windows
    links of the game's exe and of the renderer: /Brepro, with which lld writes a hash of the file where it otherwise
    writes the time of the link, so that two links of the same objects are the same bytes and make_game.py's finish can
    pass the unchanged exe over (INSTALLED_NOTE there). Off unless asked: it changes the bytes of every linked file once.
    asked: the switch's value (the environment's when not given)"""
    asked = os.environ.get("HOOKSHOT_LINK_REPRO", "") if asked is None else asked
    if asked != "1" or (LINUX if linux is None else linux):
        return []
    return [toolchain.link_opt("/Brepro")]


def check_vk_symbols(so):
    """The back end is dlopened with RTLD_NOW, so one unresolved symbol stops the whole thing
    loading -- and the only sign of that at run time is "the renderer did not start: the window
    stays black", with no symbol named. The link itself does not fail: a shared object is allowed to
    leave symbols for its loader to supply, which is exactly what the host executable does for the
    weak hos_* ones.

    So: anything still undefined here that is not weak and not the C or C++ runtime's is a mistake,
    and this says which. It has caught two, each of which had cost a run apiece to find by hand: a
    host function referenced without __attribute__((weak)), and an `extern` of one of our own
    globals written inside an anonymous namespace, which makes a different symbol that nothing
    defines.
    """
    # ((Triforce) GNU nm on some Linux distributions leaves the symbol versions' suffixes out here, so ordinary libc imports
    # looked unresolved; llvm-nm keeps them)
    nm = shutil.which("llvm-nm") or shutil.which("nm")
    if not nm:
        return True   # (not a reason to fail a build; the check is a guard, not a dependency)
    try:
        out = subprocess.run([nm, "-D", "--undefined-only", so], capture_output=True, text=True,
                             check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return True
    bad = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] != "U":   # ("w" is weak: the host supplies those, or does not)
            continue
        name = parts[1]
        if "@GLIBC" in name or "@CXXABI" in name or "@GLIBCXX" in name or "@GCC" in name:
            continue
        bad.append(name)
    if not bad:
        return True
    print("%s has %d unresolved symbol(s); it would not load:" % (os.path.basename(so), len(bad)))
    for name in bad[:20]:
        print("    " + name)
    print("  a host function wants __attribute__((weak)); one of our own globals wants an extern at")
    print("  namespace scope, not inside an anonymous namespace")
    return False

def target():
    """toolchain.native_target(), with the sysroot on Linux"""
    return toolchain.native_target() + (["--sysroot=" + SYSROOT] if LINUX and SYSROOT else [])


def no_throttle(handle=None):
    """(issue 87) Windows' power throttling (EcoQoS) slows a background window's processes to almost nothing on some machines: the
    build sat at 0% CPU. Turned off for this process, or the one whose handle this is"""
    if os.name != "nt":
        return
    import ctypes
    class State(ctypes.Structure):
        _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    s = State(1, 1, 0)   # (PROCESS_POWER_THROTTLING_EXECUTION_SPEED in the mask, off in the state)
    try:
        k.SetProcessInformation(ctypes.c_void_p(int(handle)) if handle else k.GetCurrentProcess(), 4, ctypes.byref(s), ctypes.sizeof(s))
    except (OSError, ValueError, TypeError):
        pass

# ((Triforce) skipped links) a link whose inputs are the last one's is not run again. What decides it, kept beside the output as
# <output>.linkkey (JSON) after each link that succeeded:
#   - the key: the command, the compiler, the system headers' stamp, each object's key (its .o.sha1 stamp; its size and time
#     without one), and the contents of the other files the command names (resources, the symbol order);
#   - every file the linker itself read, as it says (link_trace): the libraries it found by search path (-l, -static-libstdc++,
#     the C runtime's archives and start files) as well as the ones named, by size and time; and the linker program;
#   - the outputs: the binary and every map the command asks for, by size, time and file id, so a file written over one, or a
#     map deleted, links again.
# A link with no such record (it failed, the linker's list could not be read, or a toolchain this does not know) always runs.
# Delete <output>.linkkey to link again by hand. 3 s for the exe and less for the DLL on Windows, every build.
# HOOKSHOT_LINK_SKIP=0: every link runs, as before
LINK_RECORD = 1


def link_inputs(cmd, output):
    """The files a link reads: the objects of its @response files, and the other existing files it names (not its outputs)"""
    objs, others = [], []
    for arg in cmd:
        if arg.startswith("@") and os.path.isfile(arg[1:]):
            with open(arg[1:], encoding="utf-8") as f:
                objs += [line.strip().strip('"') for line in f if line.strip()]
            others.append(arg[1:])
            continue
        # (a file inside an option: -Xlink=/order:@<file>, --symbol-ordering-file=<file>; a whole argument too)
        m = re.match(r"^(?:-Xlink=)?(?:/\w+:@?|-Wl,|--[\w-]+=)(.+)$", arg)
        for path in (arg, m.group(1) if m else None):
            if path and os.path.isfile(path) and os.path.abspath(path) != os.path.abspath(output) and not path.endswith(".map"):
                others.append(path)
                break
    return objs, others


def link_maps(cmd):
    """The maps the command asks the linker to write: -Map=<file> (lld, GNU ld), /map:<file> (lld-link, and lld's MinGW driver
    through -Xlink=)"""
    maps = []
    for arg in cmd:
        m = re.search(r"(?:^|[,=])(?:--?Map=|/map:)(.+)$", arg, re.I)
        if m:
            maps.append(m.group(1))
    return maps


def link_key(cmd, output):
    h = hashlib.sha1("\0".join(cmd).encode(), usedforsecurity=False)
    # (the compiler: a new one compiles every object again to the same keys, and the link must follow it)
    cc = shutil.which(cmd[0]) or cmd[0]
    st = os.stat(cc)
    h.update(("%s %d %d\n" % (cc, st.st_size, st.st_mtime_ns)).encode())
    with contextlib.suppress(OSError), open(os.path.join(kit.WORK, "system_headers.txt"), "rb") as f:
        h.update(f.read())
    objs, others = link_inputs(cmd, output)
    for obj in objs:
        stamp = obj + ".sha1"
        try:
            with open(stamp) as f:
                h.update(("%s %s\n" % (obj, f.read())).encode())
        except OSError:
            st = os.stat(obj)
            h.update(("%s %d %d\n" % (obj, st.st_size, st.st_mtime_ns)).encode())
    for path in others:
        with open(path, "rb") as f:
            h.update(path.encode() + b"\0" + hashlib.sha1(f.read(), usedforsecurity=False).digest())
    return h.hexdigest()


_LINK_TARGETS = {}


def link_trace(cmd):
    """What makes the linker list every file it reads, for the compiler's target (-dumpmachine with the command's --target):
    lld and GNU ld on Linux print each with --trace; lld's MinGW driver and lld-link say "Reading <file>" when verbose. None for
    a target this does not know: that link keeps no record and always runs"""
    probe = [cmd[0]] + [a for a in cmd if a.startswith("--target=")] + ["-dumpmachine"]
    key = tuple(probe)
    if key not in _LINK_TARGETS:
        try:
            r = subprocess.run(probe, capture_output=True, text=True)
            _LINK_TARGETS[key] = r.stdout.strip().lower() if r.returncode == 0 else ""
        except OSError:
            _LINK_TARGETS[key] = ""
    t = _LINK_TARGETS[key]
    if "msvc" in t:
        return ["-Xlinker", "/verbose"]
    if "mingw" in t or "windows" in t:
        return ["-Wl,--verbose"]
    if "linux" in t:
        return ["-Wl,--trace"]
    return None


# (lld's verbose lines: the files it reads, the archive members it takes, an object's directives, the command its MinGW driver
# made; none is an error or a warning)
_VERBOSE = re.compile(r"^(?:ld\.lld|lld-link|lld)(?:\.exe)?: (?:Reading|Loaded|Directives:) |^lld-link(?:\.exe)? -lldmingw ")


def traced_files(text):
    """The files a link's own list names (link_trace), and the rest of its output without that list. An archive's member
    (lib.a(member.o)) counts as its archive; a line that names no file that exists is output, not the list"""
    files, rest = [], []
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(?:ld\.lld|lld-link|lld)(?:\.exe)?: Reading (.+)$", s)
        name = m.group(1) if m else s
        gnu = re.match(r"^-l\S+\s+\((.+)\)$", name)   # (GNU ld's -t: a library by its -l name, then the file it found)
        name = gnu.group(1) if gnu else name
        member = re.match(r"^(.+)\(([^()]+)\)$", name)
        if member and os.path.isfile(member.group(1)):
            name = member.group(1)
        if name and os.path.isfile(name):
            files.append(os.path.abspath(name))
        elif not _VERBOSE.match(s):
            rest.append(line)
    return files, "\n".join(rest) + ("\n" if rest else "")


def link_program(cmd):
    """The linker the compiler runs for this command (the first word of -###'s last command), or None"""
    try:
        r = subprocess.run(cmd + ["-###"], capture_output=True, text=True)
    except OSError:
        return None
    for line in reversed((r.stderr or "").splitlines()):
        m = re.match(r'^\s*"([^"]+)"', line)
        if m:   # (Windows: clang names ld.lld without its .exe)
            return next((p for p in (m.group(1), m.group(1) + ".exe", shutil.which(m.group(1))) if p and os.path.isfile(p)), None)
    return None


def file_stats(paths, ident=False):
    """[path, size, mtime_ns(, file id)] for each, or None when one is gone"""
    out = []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            return None
        out.append([p, st.st_size, st.st_mtime_ns] + ([st.st_ino] if ident else []))
    return out


def run_link(cmd, output):
    """subprocess.run(cmd) for a link, or nothing when everything it read and wrote is as the last successful one left it"""
    if os.environ.get("HOOKSHOT_LINK_SKIP") == "0":
        return subprocess.run(cmd, capture_output=True, text=True)
    keyfile = output + ".linkkey"
    outputs = [output] + link_maps(cmd)
    try:
        key = link_key(cmd, output)
    except OSError:   # (an input gone: the linker says which)
        key = None
    try:
        with open(keyfile, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = None
    program = link_program(cmd)
    if (key and program and isinstance(old, dict) and old.get("record") == LINK_RECORD and old.get("key") == key
            and old.get("linker") == file_stats([program]) and old.get("outputs") == file_stats(outputs, ident=True)
            and old.get("inputs") and old.get("inputs") == file_stats([i[0] for i in old["inputs"]])):
        print("  (%s: what it reads and writes is as the last link left it, not linked again)" % os.path.basename(output), flush=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    with contextlib.suppress(OSError):
        os.remove(keyfile)
    trace = link_trace(cmd)
    r = subprocess.run(cmd + (trace or []), capture_output=True, text=True)
    if trace is not None:
        out_files, r.stdout = traced_files(r.stdout or "")
        err_files, r.stderr = traced_files(r.stderr or "")
        objs = {os.path.abspath(o) for o in link_inputs(cmd, output)[0]}   # (the objects: their stamps are in the key)
        read = sorted({f for f in out_files + err_files if f not in objs and f not in map(os.path.abspath, outputs)})
    else:
        read = []
    record = {"record": LINK_RECORD, "key": key, "linker": file_stats([program]) if program else None,
              "outputs": file_stats(outputs, ident=True), "inputs": file_stats(read)}
    if r.returncode == 0 and key and program and read and record["outputs"] and record["inputs"] and record["linker"]:
        with open(keyfile, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=0)
    return r


COMPDB = "compile_commands.json"


def write_compdb(out, jobs, lifted=None):
    """((Triforce) <build>/compile_commands.json, for clangd and clang-tidy: every compile this build runs, with
    compile_one's compiler and flags. The lifted C
    (lifted: the gen/ folder, about 1.4 GB) is left out, or clangd's background index would read all of it; the host's commands
    still name gen/ and rt64/ for their headers. Point clangd at the file (--compile-commands-dir, or a link to it at the
    checkout's top, which .gitignore leaves out). A failure to write it is no failed build"""
    top = os.path.normcase(os.path.abspath(lifted)) + os.sep if lifted else None
    entries = [{"directory": os.getcwd(), "file": src, "output": obj, "arguments": [cc] + list(fl) + ["-c", src, "-o", obj]}
               for cc, src, obj, fl, deps in jobs
               if not (top and os.path.normcase(os.path.abspath(src)).startswith(top))]
    tmp = os.path.join(out, COMPDB + ".new")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(entries, f, indent=0)
        os.replace(tmp, os.path.join(out, COMPDB))
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def linker(*opts):
    """((Triforce, 11-24, after Source A's) Linker options, each as an argument of its own after -Xlinker. The ones that name a
    file (the map, the link order) are in the build files folder, which the player chooses (make_game.py --work), and the
    compiler splits -Wl, (and so toolchain.link_opt) at every comma: a comma in that folder's path cut the map's path in two and
    stopped the link. On Windows link.exe-style options ("/map:x"), through lld's MinGW driver (-Xlink=) for llvm-mingw, as
    toolchain.link_opt"""
    return [arg for opt in opts for arg in ("-Xlinker", "-Xlink=" + opt if toolchain.mingw() else opt)]


IMAGE_LIMIT = 2**31   # ((Triforce, 11-24, after Source A's) x86-64 code reaches its data RIP-relative, +-2 GB)


def image_span(path):
    """((Triforce, 11-24, after Source A's) Bytes from the start of the image to the end of its last section, as the loader maps
    it: a PE's SizeOfImage, or an ELF's PT_LOAD segments from the lowest address to the highest end. None when the file is
    neither. The game's code reaches its data (.data, the GOT, .refptr) RIP-relative, a signed 32-bit offset. lld does not
    range-check those fixups on x86-64 COFF: a lifted build compiled at -O0 linked a 2,262 MB exe with no error, and its first
    instruction that read a64_dirty read 4 GB below it. So the build checks the size itself. On ELF this is only a second
    check: lld does range-check x86-64 PC-relative fixups there and fails the link itself"""
    import struct
    with open(path, "rb") as f:
        head = f.read(4096)
        if head[:2] == b"MZ" and len(head) >= 64:
            pe = struct.unpack_from("<I", head, 0x3C)[0]
            f.seek(pe)
            hdr = f.read(24 + 60)
            if hdr[:4] != b"PE\0\0" or len(hdr) < 24 + 60:
                return None
            return struct.unpack_from("<I", hdr, 24 + 56)[0]   # (OptionalHeader.SizeOfImage, PE32 and PE32+ alike)
        if head[:4] == b"\x7fELF" and head[4] == 2:   # (ELFCLASS64)
            e = "<" if head[5] == 1 else ">"
            phoff, = struct.unpack_from(e + "Q", head, 0x20)
            phentsize, phnum = struct.unpack_from(e + "HH", head, 0x36)
            f.seek(phoff)
            table = f.read(phentsize * phnum)
            loads = []
            for i in range(phnum):
                p_type, = struct.unpack_from(e + "I", table, i * phentsize)
                if p_type == 1:   # (PT_LOAD)
                    vaddr, = struct.unpack_from(e + "Q", table, i * phentsize + 0x10)
                    memsz, = struct.unpack_from(e + "Q", table, i * phentsize + 0x28)
                    loads.append((vaddr, vaddr + memsz))
            return max(b for _, b in loads) - min(a for a, _ in loads) if loads else None
    return None


def image_too_big(exe):
    """The link FAILED message when the linked image is past what its code can address, else None (and the image is deleted
    then, so nothing starts it)"""
    span = image_span(exe)
    if span is None or span < IMAGE_LIMIT:
        return None
    try:
        os.remove(exe)
    except OSError:
        pass
    return ("link FAILED: the game's image is %d MB, past the %d MB its code can address (x86-64 RIP-relative); the linker "
            "does not check this and the game would read the wrong memory. The lifted code is too big for one image: "
            "build it at -O1 (not -O0), or split the lifted code into more than one module" % (span >> 20, IMAGE_LIMIT >> 20))


def HOT_ORDER():
    p = os.path.join(kit.WORK, "hot_order.txt")
    if not os.path.exists(p) or os.environ.get("RX_NO_ORDER"):
        return []
    if LINUX:
        return linker("--symbol-ordering-file=" + p, "--no-warn-symbol-ordering")
    return linker("/order:@" + p.replace("\\", "/"), "/ignore:4037")


HOST_LIBS = ["-lpthread", "-ldl", "-lm"] if LINUX else \
    ["-lwinhttp", "-luser32", "-lwinmm", "-ladvapi32", "-lole32", "-lshell32", "-lgdi32", "-ldbghelp",
     "-lsetupapi"]   # ((Triforce) the last: host/hos_sdl.c hos_sdl_pad_audio_endpoint, a DualSense's own sound card)
GPU = os.path.join(kit.HERE, "..", "gpu")
# FFmpeg (libavcodec's VP8/VP9 decoders, swscale) for nn::codec's video decoders (host/nn_video.c): the static build
# in the Eglantine clone's package cache
FFMPEG = None   # (found in the CPM caches below, once cpm_dirs is defined)
# the renderer's WebGPU: a wgpu-native release (include/, lib/); TOTKPort's build of it by default
WGPU = os.environ.get("WGPU_NATIVE", os.path.join(os.path.expanduser("~"), "Desktop", "TOTKPort", "third_party",
                                                  "wgpu-native"))


def gpu_sources():
    """The renderer (gpu/render, TOTKPort's, NVN replayed with WebGPU) and what it builds on, from suyu
    (gpu/third_party/suyu): the shader recompiler (Maxwell frontend, IR passes, the WGSL backend; the Ampere
    lowering is header-only), surface formats, texture decoders (block linear, ASTC)."""
    suyu = os.path.join(GPU, "third_party", "suyu")
    out = []
    for d, dirs, files in os.walk(os.path.join(suyu, "shader_recompiler")):
        dirs[:] = [x for x in dirs if x != "glsl"]   # (the GLSL backend: TOTKPort's shader tests' reference only)
        out += [os.path.join(d, f) for f in files if f.endswith(".cpp") and f not in ("attribute.cpp", "flow_test.cpp")]
    vc = os.path.join(suyu, "video_core")
    out += [os.path.join(vc, *f.split("/")) for f in ("surface.cpp", "texture_cache/format_lookup_table.cpp",
                                                      "textures/astc.cpp", "textures/decoders.cpp")]
    render = os.path.join(GPU, "render")
    out += [os.path.join(render, f) for f in os.listdir(render) if f.endswith(".cpp")]
    return sorted(out)


def tree_headers(*roots, skip=()):
    """Every header under these folders, as one dependency blob (suyu's headers sit in many folders); folders named
    in skip are left out"""
    h = hashlib.sha1(usedforsecurity=False)
    for root in roots:
        found = []
        # (the walk pruned as it goes: sorting the whole walk first, as this once did, made skip do nothing, and every
        # gpu/vk header change rebuilt the WebGPU renderer)
        for d, dirs, files in os.walk(root):
            dirs[:] = sorted(x for x in dirs if x not in skip)
            found += [os.path.join(d, f) for f in files if f.endswith(HEADER_EXTS)]
        for path in sorted(found):
            h.update(os.path.basename(path).encode() + open(path, "rb").read())
    return h.hexdigest().encode()


# ((Triforce) a header edit compiles the files that read it) The renderer's own files depended on every header under gpu/vk,
# gpu/render, gpu/compat and suyu's texture decoders (tree_headers), and the runtime's on every header of host/: a comment in a
# header two files include compiled 35 files again (417 s of compiler time). Each of those files is compiled with -MD now, and
# clang's depfile beside the object (vk_x.d for vk_x.o) says which headers it read. The next build names the object by those of
# them under the same folders, their names and contents (renderer_deps), and the blob stays for a file with no depfile yet or one
# that cannot be read. What a file reads from elsewhere (the Vulkan and SPIR-V headers, the compiler's, FFmpeg's) counts as
# before. What an #include can name: .def and .inl too, which the folders' blob (tree_headers) takes as well.
# HOOKSHOT_DEPFILES=0: every such file named by the whole folders' headers, as before
HEADER_EXTS = (".h", ".hpp", ".inc", ".inl", ".def")
_HEADER_DIGESTS = {}   # (a header's path -> its name and content's sha1, once a run: many files read the same headers)
DEPFILE_DEPS = b"depfile:"   # (what renderer_deps' dependency text starts with when it comes from a depfile)
DEPFILE_PENDING = "depfile-pending"   # (the stamp of an object compiled now from a depfile key, until rekey_depfiles keys it)
DEPFILES = os.environ.get("HOOKSHOT_DEPFILES") != "0"


def depfile_paths(text):
    """The prerequisites of a make-style depfile (clang -MD): the target and its ':' left out, line continuations joined,
    '\\ ' a space in a name, '$$' a '$', '\\#' a '#'. Clang writes the names with '/' on Windows too"""
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    colon = re.search(r":(\s|$)", text)
    if not colon:
        return []
    paths, cur, i, body = [], [], 0, text[colon.end():]
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body) and body[i + 1] in " #":
            cur.append(body[i + 1])
            i += 2
            continue
        if c == "$" and body[i + 1:i + 2] == "$":
            cur.append("$")
            i += 2
            continue
        if c.isspace():
            if cur:
                paths.append("".join(cur))
                cur = []
        else:
            cur.append(c)
        i += 1
    if cur:
        paths.append("".join(cur))
    return paths


def depfile_of(obj):
    return obj[:-2] + ".d" if obj.endswith(".o") else obj + ".d"


# ((Triforce) the depfiles kept beside the object cache, <work>/objcache/depfiles/<object's name>.d: a player's build lets the
# build folder go once the game folder is ready (make_game.py keep_translation, or all of sa), and the object cache keeps only the
# objects the last build's stamps name, which are the depfile keys (rekey_depfiles). Without the depfiles the next update named
# every renderer and runtime object by the folders' blob again, which the cache no longer held: ~550 files compiled again at every
# update. Any depfile gives a sound key (an object is cached by a depfile key only from its own depfile), so an old copy can only
# miss, never take a wrong object)
def kept_depfile(obj):
    return os.path.join(OBJ_CACHE, "depfiles", os.path.basename(depfile_of(obj)))


def renderer_deps(blob, roots, obj):
    """The headers under roots that obj's last compile read (its depfile), by name and content; blob, the whole folders', when
    there is no depfile or it names nothing under them. The renderer's own objects and the runtime's"""
    if not DEPFILES:
        return blob
    paths = None
    for path in (depfile_of(obj), kept_depfile(obj)):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                paths = depfile_paths(f.read())
            break
        except OSError:
            pass
    if paths is None:
        return blob
    tops = [os.path.normcase(os.path.abspath(r)) + os.sep for r in roots]
    picked = sorted({os.path.normcase(os.path.abspath(p)) for p in paths if p.endswith(HEADER_EXTS)
                     and os.path.normcase(os.path.abspath(p)).startswith(tuple(tops))})
    if not picked:
        return blob
    h = hashlib.sha1(b"depfile 1\0", usedforsecurity=False)
    for path in picked:
        if path not in _HEADER_DIGESTS:
            try:
                with open(path, "rb") as f:
                    _HEADER_DIGESTS[path] = os.path.basename(path).encode() + hashlib.sha1(f.read(), usedforsecurity=False).digest()
            except OSError:   # (a header gone since: the key changes, and the file is compiled again)
                _HEADER_DIGESTS[path] = os.path.basename(path).encode() + b"\0gone"
        h.update(_HEADER_DIGESTS[path])
    return DEPFILE_DEPS + h.hexdigest().encode()


def ngx_library(sdk, linux):
    """NVIDIA's NGX library in a HOOKSHOT_NGX_SDK folder (scripts/ngx_sdk.py's layout), for this build's platform: libnvsdk_ngx.a
    on Linux, nvsdk_ngx_s.lib on Windows (the static one, built against Microsoft's static runtime: gpu/vk/vk_ngx_msvc_rt.cpp)"""
    return os.path.join(sdk, "lib", "libnvsdk_ngx.a" if linux else "nvsdk_ngx_s.lib")


def ngx_sdk(sdk, linux):
    """HOOKSHOT_NGX_SDK as the build takes it: the folder when it has this platform's library, else "" (and why, said)"""
    if sdk and not os.path.isfile(ngx_library(sdk, linux)):
        print("build: HOOKSHOT_NGX_SDK=%s has no lib/%s (scripts/ngx_sdk.py --platform %s fetches it): built without NVIDIA "
              "DLSS" % (sdk, os.path.basename(ngx_library(sdk, linux)), "linux" if linux else "windows"), flush=True)
        return ""
    return sdk


# HOOKSHOT_NGX_SDK=<folder>: the Vulkan back end with NVIDIA DLSS Super Resolution, from NVIDIA's NGX SDK fetched into that
# folder by scripts/ngx_sdk.py (its include/ and this platform's lib/; never committed, NVIDIA's license). Off without it.
NGX_SDK = ngx_sdk(os.environ.get("HOOKSHOT_NGX_SDK", ""), LINUX)
# (llvm-mingw: what NVIDIA's library asks of Microsoft's runtime, linked in with it. Not compiled otherwise)
NGX_MSVC_RT = "vk_ngx_msvc_rt.cpp"
# HOOKSHOT_FSR=1: the Vulkan back end with AMD FSR 4 (gpu/vk/vk_fsr4.cpp), from AMD's FSR API headers (third_party/fidelityfx,
# MIT). AMD's signed DLLs are not part of the build: the user's, loaded at run time. Off without it (make_game.py --fsr sets
# it; the camera jitter it needs is in every build: nx2/oot_jitter.py)
FSR = os.environ.get("HOOKSHOT_FSR", "") == "1"


def renodx_folder(folder):
    """HOOKSHOT_RENODX as the build takes it: the folder when it has the compiled shaders, else "" (and why, said)"""
    if folder and not os.path.isfile(os.path.join(folder, "renodx_spv.h")):
        print("build: HOOKSHOT_RENODX=%s has no renodx_spv.h (scripts/renodx_shaders.py makes it): built without RenoDX"
              % folder, flush=True)
        return ""
    return folder


# HOOKSHOT_RENODX=<folder>: the Vulkan back end with RenoDX's HDR for OoT (gpu/vk/vk_renodx.cpp), from RenoDX's shaders fetched
# and compiled into that folder's renodx_spv.h by scripts/renodx_shaders.py (never committed: they are worked from the game's
# own shaders). Off without it (make_game.py --renodx does both); the host then keeps the game's own scene format (nn_vi.c)
RENODX = renodx_folder(os.environ.get("HOOKSHOT_RENODX", ""))


def ngx_link(sdk, mingw):
    """What triforce_vk.dll's link adds for NVIDIA DLSS on Windows: NVIDIA's library and the registry calls it makes; with
    llvm-mingw, not Microsoft's C++ runtime it names (libcpmt: vk_ngx_msvc_rt.cpp has what it needs of it, and the other
    libraries of Microsoft's are toolchain.native_link's /nodefaultlib already). Nothing without the SDK"""
    if not sdk:
        return []
    return [ngx_library(sdk, False), "-ladvapi32"] + (["-Wl,-Xlink=/nodefaultlib:libcpmt"] if mingw else [])


def vk_sources():
    """The Vulkan back end (triforce_vk.dll, gpu/vk/vk_api.h): Eden's shader recompiler with its SPIR-V back end
    (gpu/vk/eden), sirit with Eden's mesh shader patch (gpu/vk/sirit) and the back end itself (gpu/vk/*.cpp)"""
    vk = os.path.join(GPU, "vk")
    out = []
    for sub in ("eden", os.path.join("sirit", "src")):
        for d, _, files in os.walk(os.path.join(vk, sub)):
            out += [os.path.join(d, f) for f in files if f.endswith(".cpp")]
    out += [os.path.join(vk, f) for f in os.listdir(vk) if f.endswith(".cpp") and f != NGX_MSVC_RT]
    vc = os.path.join(GPU, "third_party", "suyu", "video_core")
    out += [os.path.join(vc, "textures", f) for f in ("decoders.cpp", "astc.cpp")]   # (the WebGPU back end's unswizzle)
    return sorted(out)


def strip_comments(data, collapse=False):
    """(Triforce) C or C++ text without its comments, for translation_text, and whether it has a raw string literal. A block
    comment becomes a space, a line's comment goes with the spaces before it; everything else is kept as it is. A string or
    character literal ends at its closing quote or at the end of its line (a backslash takes the next character with it, a
    line end too), a number's ' are digit separators, an #include's <name> and a raw string literal are kept whole: what this
    reads wrongly it keeps, it never takes code or a literal for a comment. ((Triforce, 11-24) collapse: and the blanks
    between the tokens, outside those literals, each run one space, none at a line's start but on the line after one a
    backslash ends (there it joins the two lines, and one space keeps their tokens apart): the tokens as the compiler's
    phase 3 leaves them, so an indentation edit, or more or fewer blanks where there were some, keeps the stamp)"""
    ident = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$")
    out, raw, i, n = bytearray(), False, 0, len(data)
    while i < n:
        c = data[i]
        if collapse and c in b" \t\v\f":
            i += 1
            if out and out[-1] in b" \t\v\f":
                continue
            if not out or out[-1] == 10:
                k = len(out) - 2
                while k >= 0 and out[k] in b" \t\v\f":
                    k -= 1
                if k < 0 or out[k] != 92:
                    continue
            out += b" "
            continue
        if data.startswith(b"//", i):
            j = data.find(b"\n", i)
            i = n if j < 0 else j
            while out and out[-1] in b" \t":
                del out[-1]
            continue
        if data.startswith(b"/*", i):
            j = data.find(b"*/", i + 2)
            i = n if j < 0 else j + 2
            out += b" "
            continue
        j = i + 1
        if c in b"\"'":
            while j < n and data[j] != c and data[j] != 10:
                j += 2 if data[j] == 92 else 1
            j = min(j + 1 if j < n and data[j] == c else j, n)
        elif c == 60 and out[out.rfind(b"\n") + 1:].strip().replace(b" ", b"").replace(b"\t", b"") in (b"#include", b"#include_next",
                                                                                                         b"#import"):
            while j < n and data[j] != 62 and data[j] != 10:
                j += 1
            j = min(j + 1 if j < n and data[j] == 62 else j, n)
        elif 48 <= c <= 57 or (c == 46 and i + 1 < n and 48 <= data[i + 1] <= 57):   # (a pp-number)
            while j < n:
                if data[j] in b"eEpP" and j + 1 < n and data[j + 1] in b"+-":
                    j += 2
                elif data[j] == 39 and j + 1 < n and data[j + 1] in ident:
                    j += 2
                elif data[j] in ident or data[j] == 46:
                    j += 1
                else:
                    break
        elif c in ident:
            while j < n and data[j] in ident:
                j += 1
            if data[i:j] in (b"R", b"LR", b"uR", b"UR", b"u8R") and j < n and data[j] == 34:
                k = data.find(b"(", j + 1)
                delim = data[j + 1:k] if k >= 0 else b"\n"
                if len(delim) <= 16 and not any(ch in b" ()\\\t\v\f\n" for ch in delim):
                    end = data.find(b")" + delim + b'"', k + 1)
                    j, raw = n if end < 0 else end + len(delim) + 2, True
        out += data[i:j]
        i = j
    return bytes(out), raw


def translation_text(rel, data):
    """(Triforce) A file of the translator as the translation stamp takes it (translation_stamp): its line ends as LF, and a C
    or C++ file without the parts between an "Outside the translation stamp" mark and the next "Inside the translation stamp
    again" (gpu/vk/vk_shader.cpp's: code that cannot change a translation, gpu/vk/program_carry.h), without its comments, and
    without its blank lines and the spaces at its lines' ends (but for the line after one a backslash ends, and in a file with
    a raw string literal). ((Triforce, 11-24) And the blanks between its tokens one space each, none at a line's start
    (strip_comments collapse): an indentation edit, or more or fewer blanks where there were some, no longer moves the stamp. Not in a file
    with a raw string literal, which is taken as before.) Marks that do not pair: the file whole, and the build says so"""
    out_mark, in_mark = b"// ---- (Triforce) Outside the translation stamp", b"// ---- (Triforce) Inside the translation stamp again"
    data = data.replace(bytes((13, 10)), bytes((10,)))
    if not rel.endswith((".c", ".cc", ".cpp", ".h", ".hpp", ".inc")):
        return data
    lines, kept, out, paired = data.split(b"\n"), [], False, True
    for line in lines:
        mark = line.strip()
        if mark.startswith(out_mark) or mark.startswith(in_mark):
            paired = paired and out != mark.startswith(out_mark)
            out = mark.startswith(out_mark)
        elif not out:
            kept.append(line)
    if out or not paired:
        print("build: %s: its translation stamp marks do not pair: the whole file is in the stamp (no program cache is carried "
              "over this update)" % rel, flush=True)
        kept = lines
    data, raw = strip_comments(b"\n".join(kept), True)
    if raw:   # (a raw string literal: the file without its comments only, as before)
        return strip_comments(b"\n".join(kept))[0]
    lines = []
    for line in data.split(b"\n"):
        if lines and lines[-1].endswith(b"\\"):
            lines.append(line)
        elif line.rstrip(b" \t"):
            lines.append(line.rstrip(b" \t"))
    return b"\n".join(lines)


def translation_stamp(vk, translator):
    """(Triforce) The translation stamp (HOOKSHOT_TRANSLATION_STAMP, 16 hex digits), which the program cache is carried over an
    update by (gpu/vk/program_carry.h has the rule): the files of the translator's stamp (HOOKSHOT_SHADER_STAMP), each as
    translation_text takes it, but for gpu/vk/vk_api.h, the host's interface, which no translation reads a constant or a type
    of (tests/test_program_carry.py). translator: the files of eden, sirit and compat"""
    stamp = hashlib.sha1(usedforsecurity=False)
    for f in sorted(translator) + [os.path.join(vk, n) for n in ("vk_shader.cpp", "vk_bank.cpp", "vk_state.h")]:
        rel = os.path.relpath(f, vk).replace("\\", "/")
        with open(f, "rb") as src:
            text = translation_text(rel, src.read())
        stamp.update(rel.encode() + b"\0" + len(text).to_bytes(8, "little") + text)
    return stamp.hexdigest()[:16]


TRANSLATION_RECORD = "translation_stamp.json"   # (in the build's folder: translation_stamp_keep)


def translation_files(vk, translator):
    """(Triforce) Each file of the translation stamp (translation_stamp's, in its order) to a hash of its text as the stamp takes
    it (translation_text), for the build's record of which files moved the stamp (translation_stamp_note). Its own copy of what an
    unpaired mark prints is left out: translation_stamp has said it"""
    import contextlib
    import io
    files = {}
    for f in sorted(translator) + [os.path.join(vk, n) for n in ("vk_shader.cpp", "vk_bank.cpp", "vk_state.h")]:
        rel = os.path.relpath(f, vk).replace("\\", "/")
        with open(f, "rb") as src, contextlib.redirect_stdout(io.StringIO()):
            text = translation_text(rel, src.read())
        files[rel] = hashlib.sha1(text, usedforsecurity=False).hexdigest()[:16]
    return files


# (Triforce) The translation stamp of the last release, the one players' shader caches are for: its stamp and each stamped file's
# hash, as translation_files gives them (made from that release's source). Changed only when a release goes out, to its stamp
RELEASED_STAMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "released_translation_stamp.json")


def translation_record_read(record):
    """(Triforce) A record of translation_stamp_keep's (or RELEASED_STAMP): (its stamp, its files, its release's name or None),
    or None when there is none or it is not one"""
    try:
        with open(record, encoding="utf-8") as f:
            old = json.load(f)
        old_stamp, old_files = old["stamp"], old["files"]
        if not isinstance(old_stamp, str) or not isinstance(old_files, dict):
            raise ValueError(record)
        release = old.get("release")
        return old_stamp, old_files, release if isinstance(release, str) else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def translation_changed(old_files, files):
    """(Triforce) The stamped files whose text differs between two records (new and gone ones too), and the same as the log names
    them: with (new)/(gone), 12 at most and then a count"""
    changed = sorted(n for n in set(old_files) | set(files) if old_files.get(n) != files.get(n))
    named = ["%s%s" % (n, " (new)" if n not in old_files else " (gone)" if n not in files else "") for n in changed]
    if not named:
        named = ["no file's text (the stamp's own rule changed)"]
    elif len(named) > 12:
        named = named[:12] + ["%d more" % (len(named) - 12)]
    return changed, ", ".join(named)


def translation_stamp_note(record, stamp, files, released=RELEASED_STAMP):
    """(Triforce) The build log's lines on the translation stamp. First against the last release's (released: RELEASED_STAMP),
    which is what players' caches are for: a stamp other than that release's starts their program and pipeline caches again at
    the update (gpu/vk/program_carry.h), hours of shader preparation on some cards, so the build names the files that moved it.
    This is the build's part of the program cache's stamp only: the runtime adds its own (disk_stamp: RX_VK_* settings, the
    robust buffers), and RX_VK_PROGRAM_CARRY=0 takes the whole translator. Then, as a note, against the previous build in this
    folder (record: its translation_stamp.json, written by translation_stamp_keep once its objects were compiled). Returns the
    files changed against the release (None without its record) and against the previous build (None without one)"""
    was = translation_record_read(released)
    against_release = None
    if was is None:
        print("build: translation stamp %s (no record of the last release's to compare with: %s)" % (stamp, released), flush=True)
    else:
        rel_stamp, rel_files, release = was
        release = release or "the last release"
        against_release, named = translation_changed(rel_files, files)
        if rel_stamp == stamp:
            print("build: translation stamp %s, as %s's: the build's part of the shader caches' stamp is kept (the runtime adds "
                  "its own settings to it: disk_stamp)" % (stamp, release), flush=True)
        else:
            print("build: translation stamp %s, NOT %s's (%s): at this update a player's program and pipeline caches from %s "
                  "start again (programs translated, pipelines compiled anew: hours on some cards). Changed against it by: %s"
                  % (stamp, release, rel_stamp, release, named), flush=True)
    old = translation_record_read(record)
    if old is None:
        print("build: (no record of the previous build's translation stamp in this folder)", flush=True)
        return against_release, None
    old_stamp, old_files, _ = old
    changed, named = translation_changed(old_files, files)
    if old_stamp == stamp:
        print("build: (the translation stamp is the previous build's in this folder)", flush=True)
    else:
        print("build: (the previous build's translation stamp in this folder was %s; changed since by: %s)" % (old_stamp, named),
              flush=True)
    return against_release, changed


def translation_stamp_keep(record, stamp, files):
    """(Triforce) This build's record for the next one's translation_stamp_note: its stamp and each stamped file's hash"""
    tmp = record + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"stamp": stamp, "files": files}, f, indent=0, sort_keys=True)
    os.replace(tmp, record)


def cpm_dirs(work=None):
    """CPM packages: RX_CPM, packaged tools/cpm, then legacy project caches (work: the build's work folder where kit.WORK is not
    it yet: make_game.py's Linux check before the build). The packages provide Vulkan and SPIR-V headers, VMA and FFmpeg."""
    eden_ns2 = os.path.dirname(kit.ROOT)
    return [d for d in (os.environ.get("RX_CPM"), os.path.join(kit.ROOT, "cpm"),
                        os.path.join(work if work is not None else kit.WORK, "eg", ".cache", "cpm"),
                        os.path.join(eden_ns2, "mkw-recomp", "work", "eg", ".cache", "cpm"),
                        os.path.join(eden_ns2, "Eglantine", ".cache", "cpm")) if d and os.path.isdir(d)]


def cpm_package(name, work=None):
    """The newest version of a package in the first CPM cache that has it (cpm_dirs), or None"""
    for root in cpm_dirs(work):
        d = os.path.join(root, name)
        if os.path.isdir(d) and os.listdir(d):
            return os.path.join(d, sorted(os.listdir(d))[-1])
    return None


def header_package(cpm_name, probe, env=None, work=None):
    """A package root with include/<probe>: CPM first, then env (package root or its include/ folder),
    then common system prefixes (/usr/local, /usr). Distro vulkan-headers / spirv-headers install
    under /usr/include; this is what makes a source build find them without a CPM tree."""
    parts = probe.split("/")

    def ok(root):
        return bool(root) and os.path.isfile(os.path.join(root, "include", *parts))

    pkg = cpm_package(cpm_name, work)
    if ok(pkg):
        return pkg
    if env:
        e = os.environ.get(env) or ""
        if e:
            e = os.path.abspath(e)
            if ok(e):
                return e
            if os.path.isfile(os.path.join(e, *parts)):
                parent = os.path.dirname(e)
                if os.path.normpath(os.path.join(parent, "include")) == os.path.normpath(e):
                    return parent
    for prefix in ("/usr/local", "/usr"):
        if ok(prefix):
            return prefix
    return None


VK_HEADERS = (("Vulkan", "vulkanheaders", "vulkan/vulkan.h", "HOOKSHOT_VULKAN_HEADERS"),
              ("SPIR-V", "spirv-headers", "spirv/unified1/spirv.h", "HOOKSHOT_SPIRV_HEADERS"),
              ("VMA", "vulkanmemoryallocator", "vk_mem_alloc.h", "HOOKSHOT_VMA_HEADERS"))


def vulkan_headers(work=None):
    """The Vulkan back end's header packages (VK_HEADERS), each its root or None: the compile's, and make_game.py's Linux check's"""
    return [header_package(package, probe, env, work) for _, package, probe, env in VK_HEADERS]


def prebuilt_renderer():
    """The AppImage's prebuilt back end (HOOKSHOT_VK_PREBUILT), or "": it is built without NVIDIA's SDK, so a build with
    HOOKSHOT_NGX_SDK compiles its own"""
    return "" if NGX_SDK else os.environ.get("HOOKSHOT_VK_PREBUILT", "")


def cache_put(obj, key):
    """Hard-link a built object into the cache under its key (a copy across volumes)"""
    os.makedirs(OBJ_CACHE, exist_ok=True)
    dst = os.path.join(OBJ_CACHE, key + ".o")
    if os.path.exists(dst):
        return
    try:
        os.link(obj, dst)
    except OSError:
        import shutil
        shutil.copyfile(obj, dst)


class MemoryStatus(ctypes.Structure):   # (Windows' MEMORYSTATUSEX, for GlobalMemoryStatusEx)
    _fields_ = [("len", ctypes.c_uint32), ("load", ctypes.c_uint32)] + \
               [(f, ctypes.c_uint64) for f in ("total", "avail", "pt", "pa", "vt", "va", "ve")]


class ProcessMemory(ctypes.Structure):   # (Windows' PROCESS_MEMORY_COUNTERS, for GetProcessMemoryInfo)
    _fields_ = [("cb", ctypes.c_uint32), ("faults", ctypes.c_uint32)] + \
               [(f, ctypes.c_size_t) for f in ("peak_ws", "ws", "qpp", "qp", "qnpp", "qnp", "pf", "peak_pf")]


# (what one compiler is counted at where its own need is not worked out: a hot piece (0.8-1.7 GB measured, -O2 and the profile),
# and the compile countdown's guess of how many the free memory holds. About the median chunk's peak)
COMPILER_MB = 1500


def free_mb():
    """The memory free now (MemAvailable on Linux, the available physical memory on Windows), in MB; None: not known"""
    try:
        if os.name == "nt":
            m = MemoryStatus()
            m.len = ctypes.sizeof(MemoryStatus)
            return m.avail >> 20 if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) else None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) >> 10
    except (OSError, ValueError, AttributeError):
        return None
    return None


def tree_rss(pid):
    """(linux) The resident bytes of a process and the processes it started (a driver that runs its compiler as a child, or ccache)"""
    with open("/proc/%d/statm" % pid) as f:
        n = int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    for task in os.listdir("/proc/%d/task" % pid):
        try:
            with open("/proc/%d/task/%s/children" % (pid, task)) as f:
                for child in f.read().split():
                    try:
                        n += tree_rss(int(child))
                    except (OSError, ValueError, IndexError):
                        pass
        except OSError:
            pass
    return n


class ProcessEntry(ctypes.Structure):   # (Windows' PROCESSENTRY32W, for CreateToolhelp32Snapshot)
    _fields_ = [("size", ctypes.c_uint32), ("usage", ctypes.c_uint32), ("pid", ctypes.c_uint32), ("heap", ctypes.c_size_t),
                ("module", ctypes.c_uint32), ("threads", ctypes.c_uint32), ("parent", ctypes.c_uint32), ("base", ctypes.c_long),
                ("flags", ctypes.c_uint32), ("exe", ctypes.c_wchar * 260)]


def tree_ws(pid):
    """(windows) The working set in bytes of a process and the processes it started: llvm-mingw's clang.exe is a 5 MB driver, and the
    memory is in the clang-23.exe it runs"""
    k = ctypes.WinDLL("kernel32")
    psapi = ctypes.WinDLL("psapi")
    k.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry)]
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.OpenProcess.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessMemory), ctypes.c_uint32]
    snapshot = k.CreateToolhelp32Snapshot(2, 0)   # (TH32CS_SNAPPROCESS)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return 0
    children = {}
    try:
        e = ProcessEntry()
        e.size = ctypes.sizeof(ProcessEntry)
        more = k.Process32FirstW(snapshot, ctypes.byref(e))
        while more:
            children.setdefault(e.parent, []).append(e.pid)
            more = k.Process32NextW(snapshot, ctypes.byref(e))
    finally:
        k.CloseHandle(snapshot)
    total, seen, todo = 0, set(), [pid]
    while todo:
        p = todo.pop()
        if p in seen:   # (Windows reuses ids: a parent id can name a newer process, and even loop)
            continue
        seen.add(p)
        todo += children.get(p, [])
        handle = k.OpenProcess(0x1000, 0, p)   # (PROCESS_QUERY_LIMITED_INFORMATION)
        if handle:
            c = ProcessMemory()
            c.cb = ctypes.sizeof(ProcessMemory)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):
                total += c.ws
            k.CloseHandle(handle)
    return total


def rss_mb(proc):
    """A running compiler's resident memory in MB (0: exited, not known, or not started yet)"""
    if proc is None:
        return 0
    try:
        # A retained Popen can outlive its driver while PID counters still remain.
        if proc.poll() is not None:
            return 0
        if os.name == "nt":
            return tree_ws(proc.pid) >> 20
        return tree_rss(proc.pid) >> 20
    except (OSError, ValueError, AttributeError, IndexError):
        return 0


# (a function from this size on is counted by the square of its size: mem_need)
GIANT_BYTES = int(1.2 * (1 << 20))
GIANT_MB = 300
# (the giant functions are counted so only on a PC with less memory free than this when the compile starts: giants_counted)
GIANT_BELOW_MB = 14 * 1024
_giants = None


def giants_counted():
    """Whether mem_need counts giant functions by the square of their size: decided once, when it is first asked. On a PC
    with GIANT_BELOW_MB or more free it does not. The count is each file's true peak, but the gate holds a file's whole
    peak back from the moment its compiler starts, and the giants reach theirs only near their end and not together: with
    21 GB free, counting them in full left 4 to 9 game files compiling at once for the first six minutes where 10 to 13
    had run without the memory ever running short, and the compile took 657 s for 462. Where memory is short the same
    files are what ran a PC out of it, so there they are counted. HOOKSHOT_MEM_GIANT=1 or 0 decides it outright."""
    global _giants
    if _giants is None:
        asked = os.environ.get("HOOKSHOT_MEM_GIANT")
        if asked in ("0", "1"):
            _giants = asked == "1"
        else:
            free = free_mb()
            _giants = free is not None and free < GIANT_BELOW_MB
        print("the memory gate: giant functions %s (%s)" % (
            "counted by the square of their size" if _giants else "counted as the other functions",
            "HOOKSHOT_MEM_GIANT" if asked in ("0", "1") else "less than %d GB free" % (GIANT_BELOW_MB >> 10) if _giants
            else "%d GB or more free, or the free memory not known" % (GIANT_BELOW_MB >> 10)), flush=True)
    return _giants


def mem_need(src):
    """What compiling a file takes at its peak, in MB, a little over. Measured on a cold build (clang 23, x86-64): a chunk of lifted
    code 0.4 GB + 50 MB per MB of C + 250 MB per MB of its largest function (1.5 GB for 24 MB of small functions, 2.2 GB for a 6 MB
    function alone); a hot piece 0.8-1.3 GB whatever its size (-O2, the profile, inlining); the runtime's C files ~0.2 GB, the C++
    files up to ~1 GB.
    (Triforce, measured again with HOOKSHOT_MEM_LOG on a build of v0.4.0, clang 23.1.5) The few files with giant functions took
    far more than that: 6.2 GB for a chunk that is one 5 MB function (counted 1.9), 3.7 and 3.1 GB for two others (counted 1.4
    and 1.5), and 2.5 to 2.7 GB for the three hot pieces that hold functions near 2 MB (counted 1.5). The compiler's memory
    grows with the square of a function's size, as its time does (nx2/chunks.py QUAD), so every function of GIANT_BYTES or
    more now adds GIANT_MB for each MB squared, in a chunk and in a hot piece: of the 76 game files measured none is then
    under by more than 250 MB, which the gate's reserve covers. Counted too low, such a file was started beside the others
    on a PC without the memory for it, where Windows pages and Linux stops the compiler. Only on a PC short of memory:
    giants_counted."""
    name = os.path.basename(src)
    if name.startswith("code_"):
        with open(src, "rb") as f:
            text = f.read()
        # (each function from the newline before its definition, as this was first measured)
        # ((Triforce, 11-22, the performance audit's IO-40) lifted_c.definitions: HEAD_BYTES's matches, found by jumps)
        starts = [m.start() - 1 for m in lifted_c.definitions(text)] + [len(text)]
        sizes = [b - a for a, b in zip(starts, starts[1:])]
        giant = GIANT_MB * sum((s / (1 << 20)) ** 2 for s in sizes if s >= GIANT_BYTES) if giants_counted() else 0
        if name.startswith("code_hot"):
            return int(COMPILER_MB + giant)
        largest = max(sizes or [0])
        return int(max(400 + 50 * len(text) / (1 << 20) + 250 * largest / (1 << 20), 300 + 50 * len(text) / (1 << 20) + giant))
    return 1000 if src.endswith(".cpp") else 400


class CompileStopped(Exception):
    """((Triforce, 11-21, the performance audit's LIFT-31) The build is stopping: a compile that waited at the memory gate
    is not started (MemoryGate.stop)"""


class MemoryGate:
    """(issue 418) Compilers started by the memory there is, not only by --jobs: one per CPU thread ran PCs out of memory (the kernel
    stopped a compiler, or the whole build), and a count low enough for the biggest files and the PC's other programs left most of
    the threads idle. A compile starts when the memory free, less what the compilers running may still take on top of what they
    hold now (mem_need), keeps its own need and HOOKSHOT_MEM_RESERVE_GB (default 1.5) free. The floor is make_game's before this:
    on Windows up to 4 (half the threads on smaller CPUs) always run, as Windows pages rather than fails (issues 502, 503, 511: 1-2
    compilers on 16 GB PCs took hours); on Linux one (issue 531: Linux stops a compiler that does not fit, and it is compiled again
    alone). The free memory is read again as compiles start and end, so a game or browser opened during the build makes later
    compiles wait

    (Triforce, 11-21, the performance audit's LIFT-31, after Source A's) stop(): the build is ending on an exception. The
    pool's workers, one a CPU thread, wait here, and a compile that has left the pool's queue cannot be cancelled there:
    one that waits, or comes after, raises CompileStopped and takes no lease"""

    def __init__(self):
        self.cv = threading.Condition()
        self.stopped = False
        self.running = {}   # (per-compile lease: [need, Popen or None]; one source can have several objects)
        self.reserve = float(os.environ.get("HOOKSHOT_MEM_RESERVE_GB") or 1.5) * 1024
        self.floor = max(1, min(4, (os.cpu_count() or 2) // 2)) if os.name == "nt" else 1

    def enter(self, src):
        need = mem_need(src)
        with self.cv:
            while not self.stopped and len(self.running) >= self.floor:
                free = free_mb()
                if free is None:
                    break
                owed = sum(max(0, n - rss_mb(p)) for n, p in self.running.values())
                if free - owed - self.reserve >= need:
                    break
                self.cv.wait(1.0)
            if self.stopped:
                raise CompileStopped(src)
            lease = object()
            self.running[lease] = [need, None]
            return lease

    def stop(self):
        with self.cv:
            self.stopped = True
            self.cv.notify_all()

    def started(self, lease, proc):
        with self.cv:
            self.running[lease][1] = proc

    def expected(self, jobs):
        """How many compilers the memory free now is likely to hold at once (COMPILER_MB each), between the floor and the jobs:
        the compile countdown's estimate"""
        free = free_mb()
        if free is None:
            return jobs
        return max(self.floor, min(jobs, int((free - self.reserve) // COMPILER_MB)))

    def leave(self, lease):
        with self.cv:
            self.running.pop(lease, None)
            self.cv.notify_all()


GATE = None   # (main's MemoryGate; None: compiles start as the jobs allow)


FFMPEG = next((os.path.join(d, n) for d in [os.path.join(r, "ffmpeg") for r in cpm_dirs()] if os.path.isdir(d)
               for n in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, n, "lib"))
               and "linux" not in n.lower()), None)   # (hookshot: a cache with both systems' builds, cross-building)
FFMPEG_LIBS = ("avcodec", "swscale", "swresample", "avutil")


def ffmpeg_linux(missing=None):
    """(linux) FFmpeg's compile and link flags: HOOKSHOT_FFMPEG=<prefix> with static libraries (the AppImage's, with
    dav1d for OoT's AV1 movies), else the system's through pkg-config; None without either. missing, when given, collects what
    the route chosen lacks (make_game.py's Linux check)"""
    pre = os.environ.get("HOOKSHOT_FFMPEG")
    if pre and os.path.exists(os.path.join(pre, "lib", "libavcodec.a")):
        libs = [os.path.join(pre, "lib", "lib%s.a" % l) for l in FFMPEG_LIBS]
        if missing is not None:
            for path in libs + [os.path.join(pre, "include", "lib" + l, l + ".h") for l in FFMPEG_LIBS]:
                if not os.path.isfile(path):
                    missing.append("FFmpeg: %s (HOOKSHOT_FFMPEG's static prefix)" % path)
        libs += [os.path.join(pre, "lib", "libdav1d.a")] if os.path.exists(os.path.join(pre, "lib", "libdav1d.a")) else []
        return ["-I" + os.path.join(pre, "include")], libs + ["-lm", "-lpthread"]
    names = ["lib" + l for l in FFMPEG_LIBS]
    try:
        cflags = subprocess.run(["pkg-config", "--cflags"] + names, capture_output=True, text=True, check=True).stdout.split()
        libs = subprocess.run(["pkg-config", "--libs"] + names, capture_output=True, text=True, check=True).stdout.split()
        return cflags, libs
    except (OSError, subprocess.CalledProcessError) as e:
        if missing is not None:
            absent = []
            for name in names:
                try:
                    if subprocess.run(["pkg-config", "--exists", name], capture_output=True).returncode:
                        absent.append(name)
                except OSError:
                    absent = ["pkg-config"] + names
                    break
            missing.append("FFmpeg: %s (HOOKSHOT_FFMPEG with lib/libavcodec.a first, else pkg-config --cflags/--libs for %s; "
                           "install the development libraries or set HOOKSHOT_FFMPEG). %s" %
                           (", ".join(absent or names), " ".join(names), e))
        return None


if LINUX:
    FFMPEG_LX = ffmpeg_linux()
    FFMPEG = None


def ffmpeg_version_key():
    """The FFmpeg headers this build compiles against, so a host object from another major version is not reused.
    Codec numbers and struct layouts differ between them."""
    incs = []
    if FFMPEG:
        incs.append(os.path.join(FFMPEG, "include"))
    if LINUX and FFMPEG_LX:
        incs += [f[2:] for f in FFMPEG_LX[0] if f.startswith("-I")]
    incs.append("/usr/include")
    for inc in incs:
        parts = []
        for name in ("version_major.h", "version.h"):
            path = os.path.join(inc, "libavcodec", name)
            if os.path.exists(path):
                parts.append(open(path, "rb").read())
        if parts:
            return b"".join(parts)
    return b""


# the soft write watch (rt/a64.h A64_MARK): lifted stores mark their 4 KB page, and the renderer reads the marks
# instead of Windows' write watch (GetWriteWatch over the 6 GB MKW's GPU sees took ~20 ms a scan, in one thread or
# four: the race's replay waited ~12 ms a frame for it). RX_SOFT_WRITE_WATCH=0: Windows' write watch (a full rebuild)
WRITE_TRACK = [] if os.environ.get("RX_SOFT_WRITE_WATCH") == "0" else ["-DA64_WRITE_TRACK"]
# (triforce) RX_MARK_ONE=1: a lifted store marks the page of its first byte alone (one store and three instructions less
# at every guest store; the marks were ~5-8% of the game threads' CPU at OoT's Market), and the collection takes a mark
# as "this page and the next" (host/rx_backend.c collect_in): a store of up to 4 KB reaches no further. A full rebuild.
if WRITE_TRACK and os.environ.get("RX_MARK_ONE") == "1":
    WRITE_TRACK = WRITE_TRACK + ["-DA64_MARK_ONE"]
# (Triforce) RX_MARK_BITMAP=1: the lifted game's stores mark their page only where the page is a GPU page (host/mark_bitmap.c,
# nx2/rtgen.py A64_MARK_BITMAP: a bit per page, tested before the mark); the host's own marks stay. Off unless asked for:
# a mark missed is stale data drawn, so it wants its pictures compared first. A full rebuild (the lifted code's and the
# host's flags). MARK_BITMAP: the lifted code's flag; MARK_BITMAP_HOST: the host files' (the bitmap itself, and nvdrv.c's bits)
MARK_BITMAP = ["-DA64_MARK_BITMAP"] if WRITE_TRACK and os.environ.get("RX_MARK_BITMAP", "").strip().lower() in ("1", "on", "true", "yes") else []
MARK_BITMAP_HOST = ["-DHOS_MARK_BITMAP"] if MARK_BITMAP else []

# (hookshot) the host CPU the lifted game and the runtime are built for: x86-64-v3 (AVX2, FMA, BMI1/2, LZCNT,
# MOVBE; Haswell and Zen 1 on). With FMA the FPX1 fast paths cover double-precision FMA (RECOMP_FPX_FMA64; it took
# the exact software body on baseline x86-64) and the bit counts are single instructions. No contraction, so a C
# expression is rounded as written (the exact bodies and FPX1's proofs assume it). RX_MARCH=x86-64: the old baseline
# (issue 363: a Xeon E5-2667 v2 (Ivy Bridge, no AVX2) built the game and then stopped at its first AVX2 instruction,
# 0xc000001d. The game is built on the PC it runs on: a CPU without x86-64-v3's features gets x86-64-v2, or x86-64)
from host_cpu import host_march, host_mtune, native_cpu   # (make_game.py asks it too: the AppImage's renderer)

MARCH = os.environ.get("RX_MARCH") or host_march()
if os.environ.get("RX_MARCH"):   # ((Triforce) a choice made by hand is not a CPU without AVX2)
    if MARCH != "x86-64-v3":
        print("build: the game is built for %s (RX_MARCH)" % MARCH, flush=True)
elif MARCH != "x86-64-v3":
    print("build: this CPU has no AVX2: the game is built for %s (a little slower)" % MARCH, flush=True)
CPU = ["-march=" + MARCH, "-ffp-contract=off"]
# ((Triforce) HOOKSHOT_NATIVE_CPU=1, off by default: it changes the code the game runs, the coordinator measures its fps first)
# A CPU with x86-64-v3's features gets the game built for itself, -march=native: what it has beyond v3 (AVX-512 and the rest), and
# tuned for it (native tunes as well, the Steam Deck's Zen 2 included: no -mtune of our own then). native names no CPU, and the
# object keys are made from the flags, so the CPU clang resolves it to goes into the flags too
# (-DHOOKSHOT_NATIVE_CPU=<cpu>_<tune>_<features>): another CPU (a new one, the disk in another PC) compiles again instead of
# linking objects made for instructions it may lack. If clang can't say, it stays x86-64-v3; an RX_MARCH=native that clang
# cannot name stops the build. Every object is compiled again once when it is turned on or off
_CLANG = toolchain.find("clang") if os.environ.get("HOOKSHOT_NATIVE_CPU") == "1" or MARCH == "native" else ""   # (asked only then)
_native = None
if (os.environ.get("HOOKSHOT_NATIVE_CPU") == "1" and not os.environ.get("RX_MARCH") and MARCH == "x86-64-v3"
        and os.path.isfile(_CLANG)):
    _native = native_cpu(_CLANG, target() + ["-march=native"] + CPU[1:])
    if _native:
        MARCH, CPU[0] = "native", "-march=native"
if MARCH == "native" and not _native:
    _native = native_cpu(toolchain.need(_CLANG), target() + CPU)
    if not _native:
        sys.exit("build: clang does not say what -march=native is on this PC: set RX_MARCH to a CPU level")
if _native:
    print("build: the game is built for this PC's CPU (%s)" % _native, flush=True)
    CPU += ["-DHOOKSHOT_NATIVE_CPU=" + _native]
# (Triforce) -mtune for the host's CPU where it is known (the Steam Deck: znver2); RX_MTUNE=<cpu> chooses. Scheduling and
# instruction choice only: the instructions allowed stay -march's, and -ffp-contract=off the float results. (Not with -march=native,
# which tunes for the CPU itself, unless RX_MTUNE asks)
MTUNE = os.environ.get("RX_MTUNE") or ("" if _native else host_mtune())
if MTUNE:
    CPU += ["-mtune=" + MTUNE]


def flags(gen, rt64, opt, polls):
    return target() + CPU + [
        "-I" + rt64, "-I" + gen, "-I" + os.path.join(kit.KIT, "rt"), "-I" + NX2_RT, "-Wno-everything",
        "-fno-strict-aliasing", "-mcx16", "-" + opt, "-g0", "-mllvm", "-rotation-max-header-size=0",
        "-ffunction-sections", "-mllvm", "-capture-tracking-max-uses-to-explore=5000"] + \
        (["-DA64_POLLING"] if polls else []) + WRITE_TRACK + MARK_BITMAP


# ((Triforce) HOOKSHOT_SPLIT_GIANTS, off by default: it changes the code the game runs, the coordinator measures its fps first)
# nx2/split_giants.py: the lifted functions of split_giants.MIN_KB (256) or more are compiled as pieces cut at their labels, with a
# dispatch loop under the function's own name (compile_one compiles that copy; the lifted files stay as the lift wrote them, so its
# patches, cuts and lists never see the pieces). The lifted chunks and the hot pieces both. Measured here on this game's lifted C:
# 286 functions of 158 MB cut into 12,824 pieces (2 left whole); code_023.c, one 4.8 MB function, 122 s -> 39 s at -O1, the same
# PC. Elsewhere a whole first build's compile 1,347 -> 1,057 s on a Ryzen 5 5600, and the longest hot piece 346 -> about 60 s.
# "1": on, pieces of split_giants.PIECE_KB (8); a number: the pieces' size in KB. HOOKSHOT_SPLIT_DIRECT=0: the pieces go through
# the dispatch loop only, never straight from one to the next (split_giants.macros)
def split_giants_flags():
    """The flag the lifted chunks and the hot pieces carry when their giants are split (split_giants.FLAG: the piece size and
    the splitter's own hash, so a change of either builds them again); [] when off"""
    raw = os.environ.get("HOOKSHOT_SPLIT_GIANTS", "").strip() or "1"   # ((Triforce, 11-24) on by default: lab, no fps change)
    if raw == "0" or not raw.isdigit():
        return []
    import split_giants
    return [split_giants.flag(split_giants.PIECE_KB if raw == "1" else int(raw),
                              os.environ.get("HOOKSHOT_SPLIT_DIRECT", "").strip() != "0")]


def a64_rt_flags(fl, opt):
    """((Triforce) RX_A64_RT_O2) The shared A64 helpers' flags: fl at -O2 when RX_A64_RT_O2 is 1 (on, true, yes), else fl itself"""
    if os.environ.get("RX_A64_RT_O2", "").strip().lower() not in ("1", "on", "true", "yes"):
        return fl
    return ["-O2" if f == "-" + opt else f for f in fl]


# ((Triforce) HOOKSHOT_LIGHT_PASSES, ON by default since 11-24 (=0: off). It changes the code the game runs; lab 11-24, his save at
# the Castle Town market, 60 s windowed, twice each: plain 84.0 / 83.9 fps, this with HOOKSHOT_SPLIT_GIANTS 84.2 / 84.3; the
# game's whole compile 530 -> 257 s (5,932 -> 3,249 compiler-seconds, longest file 289 -> 100 s) on a 24-thread PC, -j16)
# Ordinary lifted chunks compile at -O1 without its module passes (the inliner, ipsccp, globalopt, function-attrs ...: -mllvm
# -opt-disable; LLVM skips only passes it marks optional, so the code stays correct). Measured elsewhere on single chunks:
# -21..-34% compile time, +3..5% code, the same peak memory; -O1's inliner barely inlines lifted code (the same call counts),
# but the few helpers it did inline (third_party/a64-kit's VFPX_HEADER a64_v_* helpers, VSET_HEADER's and FPX_FZ_HEADER's
# fallbacks) became real calls there (+4.6% game CPU) until they were made always_inline in the lifter: that lifter change is
# not made here, so measure with it. A chunk with a function of HOOKSHOT_LIGHT_PASSES_KB (1024) KB of C or more keeps every
# pass: without the module passes a giant function's later passes blow up (3.25-4.7 GB, 8x the time). The hot pieces (code_hot*)
# keep theirs (-O2 and the profile). The flags are part of each object's key (object_key), so a light object and a full one are
# never taken for each other. opt-bisect-verbose=false: without it the option prints a line for every pass on every function
LIGHT_PASSES = ["ipsccp", "called-value-propagation", "globalopt", "openmp-opt", "deadargelim", "globaldce", "elim-avail-extern",
                "rpo-function-attrs", "function-attrs", "constmerge", "cg-profile", "rel-lookup-table-converter", "inline",
                "inliner-ml-advisor-release"]
LIGHT_FLAGS = ["-mllvm", "-opt-disable=" + ",".join(LIGHT_PASSES), "-mllvm", "-opt-bisect-verbose=false"]


def light_passes_kb():
    """The largest function (KB of C) a lifted chunk may hold and still compile without the module passes; None: off"""
    if os.environ.get("HOOKSHOT_LIGHT_PASSES", "1").strip().lower() not in ("1", "true", "on", "yes", ""):   # (11-24: on by default)
        return None
    try:
        kb = max(1, int(os.environ.get("HOOKSHOT_LIGHT_PASSES_KB") or 1024))
    except ValueError:
        kb = 1024
    return kb


def light_flags_work(cc):
    """Whether cc takes LIGHT_FLAGS: one tiny compile. -opt-disable is LLVM 22's, and a Linux system's older clang stops at it,
    so every light chunk would fail: with such a compiler they keep every pass"""
    try:
        r = subprocess.run([cc, "-x", "c", "-O1", "-Wno-everything", "-S", "-o", "-", "-"] + LIGHT_FLAGS,
                           input="int f(int x) { return x + 1; }\n", capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except OSError as e:
        r = subprocess.CompletedProcess([cc], 1, "", str(e))
    if r.returncode:
        print("build: this compiler does not take the light passes' flags (%s): every lifted chunk keeps -O1's module passes"
              % (r.stderr.strip().splitlines() or ["?"])[0], flush=True)
    return r.returncode == 0


def largest_function(text):
    """The largest function of a lifted file's text, in bytes: each function from the newline before its definition, as
    mem_need was first measured"""
    starts = [m.start() - 1 for m in lifted_c.definitions(text)] + [len(text)]
    return max([b - a for a, b in zip(starts, starts[1:])] or [0])


def lifted_largest(src):
    """A lifted file's largest function in bytes (largest_function), from the record (HASHES) while it still describes the file,
    so a build reads no lifted file it already knows"""
    entry, st = known(src)
    if entry is not None and isinstance(entry.get("largest"), int):
        return entry["largest"]
    with open(src, "rb") as f:
        content = f.read()
    largest = largest_function(content)
    remember(src, st, content)["largest"] = largest
    return largest


def lifted_flags(src, fl, deps, bar_kb):
    """A lifted chunk's flags: fl, or fl + LIGHT_FLAGS (light_passes_kb). A kept file that is not on disk gets the flags whose
    part its list recorded (so the kept objects still fit)"""
    if bar_kb is None:
        return fl
    light = fl + LIGHT_FLAGS
    if src in KEPT and not os.path.exists(src):
        return light if KEPT[src][2] == kept_part(light, deps) else fl
    return light if lifted_largest(src) < bar_kb * 1024 else fl


def write_info(out):
    meta = json.load(open(os.path.join(kit.WORK, "image", "image.json")))
    mods = {m["name"]: m for m in meta["modules"]}
    path = os.path.join(out, "mkw_info.c")
    text = ('/* Generated by nx2/build.py from work/image/image.json. */\n#include <stdint.h>\n'
            'const uint64_t mkw_image_base = 0x%xULL;\nconst char mkw_main_build_id[] = "%s";\n'
            % (meta["base"], mods["main"]["build_id"]))
    if not os.path.exists(path) or open(path).read() != text:
        open(path, "w", newline="\n").write(text)
    return path


def flag_text(fl):
    """The flags an object key is named by. Include folders are left out (their headers are in deps). The builder's
    own folder is <root> (issue 565: versions\\<tag>\\... made every update look new). --sysroot= is <sysroot>: the
    AppImage mount is a new /tmp/.mount_... path every start, and that path is not a change in the headers."""
    kept = []
    for f in fl:
        if f.startswith("-I") or f == "-MD":   # ((Triforce) -MD writes the depfile beside the object: renderer_deps)
            continue
        if f.startswith("--sysroot="):
            f = "--sysroot=<sysroot>"
        elif VK_PGO not in ("", "0", "gen") and f == "-fprofile-instr-use=" + VK_PGO:
            # ((Triforce, 11-21, LIFT-10) the renderer's profile by its contents (TRIFORCE_VK_PROFILE_SHA1, beside it), not by
            # where it is: another work folder's copy of the same profile is no new key)
            f = "-fprofile-instr-use=<vk profile>"
        else:
            f = f.replace(kit.ROOT, "<root>")
        kept.append(f)
    return " ".join(kept)


def object_key(src, fl, deps):
    """What an object depends on: its source, the flags (flag_text), and the headers."""
    return hashlib.sha1(open(src, "rb").read() + flag_text(fl).encode() + deps, usedforsecurity=False).hexdigest()


def kept_part(fl, deps):
    """What of an object key is not its source: the flags (flag_text) and the headers"""
    return hashlib.sha1(flag_text(fl).encode() + deps, usedforsecurity=False).hexdigest()


def key_of(src, fl, deps):
    """object_key, without reading a source HASHES still knows: the key worked out from it before, for these flags and headers,
    is the same"""
    part = kept_part(fl, deps)
    USED.setdefault(src, set()).add(part)
    entry, st = known(src)
    if entry is not None and part in entry["keys"]:
        return entry["keys"][part]
    content = open(src, "rb").read()
    key = hashlib.sha1(content + flag_text(fl).encode() + deps, usedforsecurity=False).hexdigest()
    remember(src, st, content)["keys"][part] = key
    return key


# ((Triforce) the object keys by the sources' size, modification time and file number) Every build read and hashed each source
# again to name its object, the 1.5 GB of lifted C up to three times (migrate_stamps, the object keys' fingerprint, plan_jobs):
# 7.5 s of a one-file edit's 32 s build on Windows, measured. A file whose size, time and number are the ones recorded has the
# content it had; its key for the same flags and headers (kept_part) is the one worked out then, and its content's SHA-1 is kept
# for the fingerprint. A file written less than RACY_NS before the record's build started is read again: a change within the
# clock's step keeps the time (git's "racily clean" index entries). Kept in <build>/hash_cache.json; a record that cannot be
# read is no record. The record is written under the time its build started, before it looked at any source, and keeps, for
# each source this build looked at, only the keys this build asked for (a header's edit added a key to every renderer source,
# and the file only grew); a source this build did not look at (a renderer-only build's lifted C) keeps its record as it was.
# HOOKSHOT_HASH_CACHE=0: every source read and hashed, as before
HASH_CACHE = "hash_cache.json"
HASH_SCHEME = 1
RACY_NS = 2 * 10 ** 9
HASHES = {}   # (source path -> {"stat": [size, mtime_ns, number], "sha1": the content's, "keys": {kept_part: object key}})
HASHES_AT = [0]   # (when the record read in was started, in ns: entries for files written after it, less RACY_NS, are not trusted)
HASHES_STARTED = [0]
USED = {}   # (source path -> the kept_parts key_of was asked for this build; content_sha1's sources with none)


def file_stat(src):
    st = os.stat(src)
    return [st.st_size, st.st_mtime_ns, st.st_ino]


def known(src):
    """(the record of src while it still describes the file on disk, or None; and the file's stat, None when it is not there)"""
    try:
        st = file_stat(src)
    except OSError:
        return None, None
    entry = HASHES.get(src)
    if entry is not None and st[2] and entry.get("stat") == st and st[1] < HASHES_AT[0] - RACY_NS:
        return entry, st
    return None, st


def remember(src, st, content):
    """The record of src for the content just read from it: the one there when it was made from that same content (its other
    keys hold), else a new one. A record not trusted for its time (RACY_NS) that names other content is dropped with its keys"""
    digest = hashlib.sha1(content, usedforsecurity=False).hexdigest()
    entry = HASHES.get(src)
    if entry is None or entry.get("stat") != st or entry.get("sha1") != digest:
        entry = {"stat": st, "sha1": digest, "keys": {}}
        if st is not None:
            HASHES[src] = entry
    return entry


def content_sha1(src):
    """A source's content's SHA-1, from the record when it still describes the file"""
    USED.setdefault(src, set())
    entry, st = known(src)
    if entry is not None:
        return entry["sha1"]
    return remember(src, st, open(src, "rb").read())["sha1"]


def load_hashes(out):
    HASHES_STARTED[0] = time.time_ns()   # (before any source is stat'd: the time the next record is written under)
    HASHES.clear()
    USED.clear()
    HASHES_AT[0] = 0
    if os.environ.get("HOOKSHOT_HASH_CACHE") == "0":
        return
    try:
        with open(os.path.join(out, HASH_CACHE), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("scheme") != HASH_SCHEME:
            return
        HASHES_AT[0] = int(data["written_ns"])
        for src, entry in data["files"].items():
            if (isinstance(entry.get("stat"), list) and len(entry["stat"]) == 3 and isinstance(entry.get("sha1"), str)
                    and isinstance(entry.get("keys"), dict)):
                HASHES[src] = {"stat": [int(x) for x in entry["stat"]], "sha1": entry["sha1"], "keys": dict(entry["keys"])}
                if isinstance(entry.get("largest"), int):   # ((Triforce) a lifted file's largest function: lifted_largest)
                    HASHES[src]["largest"] = entry["largest"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        HASHES.clear()
        HASHES_AT[0] = 0


def save_hashes(out):
    """The record of the sources this build saw, for the next one (written atomically; a failure only costs the next build a read)"""
    if os.environ.get("HOOKSHOT_HASH_CACHE") == "0":
        return

    def kept(src, e):
        if src not in USED:
            return e
        return dict(e, keys={part: key for part, key in e["keys"].items() if part in USED[src]})
    data = {"scheme": HASH_SCHEME, "written_ns": HASHES_STARTED[0] or time.time_ns(),
            "files": {src: kept(src, e) for src, e in sorted(HASHES.items()) if os.path.exists(src)}}
    tmp = os.path.join(out, HASH_CACHE + ".new")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, os.path.join(out, HASH_CACHE))
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)


# ((Triforce) a player's update) make_game.py lets the lifted C (1.5 GB) go once the game folder is ready, but keeps the compiled
# objects and this list, gen/lifted_objects.txt: each lifted file's name, its object key, its size, and what of the key is not the
# source (flags and headers, kept_part). The next build with the same lift key (make_game.py kept_before) skips the lift and passes
# --kept-lift: the lifted files are then these names, linked from the object cache by these keys, the same objects as before. When
# a key's object is gone or the flags or headers changed, the build stops with KEPT_STALE before compiling anything, and
# make_game.py translates the game again. The list's first line names the lift it was written for (the lift key in gen/.lift_key)
# and KEPT_SCHEME: a list another lift left, or one of another format, is not used. KEPT_STALE is not 3, abort()'s exit status on
# Windows
KEPT_LIST = "lifted_objects.txt"
KEPT_SCHEME = 1
KEPT_STALE = 75
KEPT = {}   # (source path -> (object key, size, kept_part)) for the lifted files that are not on disk


def src_size(src):
    """A source's size; a kept lifted file's as it was"""
    if src in KEPT and not os.path.exists(src):
        return KEPT[src][1]
    return os.path.getsize(src)


def lift_key_of(gen):
    """The key of the lift in gen (the first line of make_game.py's .lift_key), or "-" without one"""
    try:
        with open(os.path.join(gen, ".lift_key"), encoding="utf-8") as f:
            return (f.read().split() or ["-"])[0]
    except OSError:
        return "-"


def kept_header(key):
    return "# lift %s %d\n" % (key, KEPT_SCHEME)


def read_kept(path):
    """The list's files, or {} when its first line is not the header of this lift (lift_key_of) and scheme"""
    kept = {}
    gen = os.path.dirname(path)
    with open(path, encoding="utf-8") as f:
        if f.readline() != kept_header(lift_key_of(gen)):
            return kept
        for line in f:
            parts = line.split()
            if len(parts) == 4 and parts[2].isdigit():
                kept[os.path.join(gen, parts[0])] = (parts[1], int(parts[2]), parts[3])
    return kept


def write_kept(gen, jobs):
    """gen/lifted_objects.txt for the lifted files of a build that compiled every file (see KEPT_LIST)"""
    lines = []
    for cc, src, obj, fl, deps in jobs:
        name = os.path.basename(src)
        if os.path.dirname(src) == gen and name.startswith("code_") and name.endswith(".c"):
            lines.append("%s %s %d %s\n" % (name, PLANNED.get((src, obj)) or key_of(src, fl, deps), src_size(src),
                                            kept_part(fl, deps)))
    tmp = os.path.join(gen, KEPT_LIST + ".new")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(kept_header(lift_key_of(gen)))
        f.writelines(sorted(lines))
    os.replace(tmp, os.path.join(gen, KEPT_LIST))


def times_from(path):
    """The seconds each module took on this PC, from make_game.py's build_times.json, or {} when there is no record to
    use (a first build, one half written, or one another version of the tools wrote): the countdown then falls back to
    the rate this PC's other measurements ran at."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): float(v) for k, v in data["seconds"].items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def eta_left(pending, jobs):
    """How long the rest of the compile takes, in seconds, with this many compilers: the work spread over them, with
    the longest file still left as the floor (each file is still one compiler)."""
    if not pending:
        return 0.0
    return max(max(pending), sum(pending) / max(1, jobs))


def per_file_seconds(jobs, history):
    """One expected duration for each job, in order: the seconds this PC measured for that module before, or, for a
    module it never compiled (a new release adds or renames files), the rate those measurements ran at. On a PC with
    no measurements at all, the first build uses the rates a full build on the development PC showed."""
    sizes = [max(0.0, src_size(src) / (1 << 20)) for _, src, *_ in jobs]
    measured = [(history[os.path.basename(src)], mb) for (_, src, *_), mb in zip(jobs, sizes)
                if os.path.basename(src) in history and mb > 0]
    rate = sum(secs for secs, _ in measured) / sum(mb for _, mb in measured) if measured else None
    out = []
    for (_, src, *_), mb in zip(jobs, sizes):
        name = os.path.basename(src)
        if name in history:
            out.append(max(0.05, history[name]))
        elif rate is not None:
            out.append(max(0.5, rate * mb))
        else:   # (seconds per MB measured on a full build: the eight hot files, the game chunks, the rest)
            out.append(23.5 * mb if name.startswith("code_hot") else 3.4 * mb + 1 if name.startswith("code_") else 1.3)
    return out


def plan_jobs(jobs):
    """Which jobs this run really compiles, and every job's object key. A job whose object is stamped with its key, or
    whose key is in the object cache (the other target's build), is only linked in: not work, and not in the countdown.
    The keys go to compile_one, which then does not hash every source a second time."""
    work, keys = [], {}
    for cc, src, obj, fl, deps in jobs:
        key = PLANNED.get((src, obj)) or key_of(src, fl, deps)
        keys[(src, obj)] = key
        stamp = obj + ".sha1"
        if os.path.exists(obj) and os.path.exists(stamp) and open(stamp).read() == key:
            continue
        if os.path.exists(os.path.join(OBJ_CACHE, key + ".o")):
            continue
        work.append((cc, src, obj, fl, deps))
    return work, keys


def migrate_stamps(gen, obj_dir, fl, deps):
    """Objects stamped with the old key (flags with include folders) are restamped with object_key and cached, so
    a build from before the cache does not have to be compiled again"""
    if not os.path.isdir(obj_dir):
        return
    if not os.path.isdir(gen) or not os.path.isdir(obj_dir):   # (a first build in a fresh folder)
        return
    for f in os.listdir(gen):
        if not (f.startswith("code_") and f.endswith(".c")):
            continue
        obj = os.path.join(obj_dir, f[:-2] + ".o")
        stamp = obj + ".sha1"
        if not (os.path.exists(obj) and os.path.exists(stamp)):
            continue
        src = os.path.join(gen, f)
        old = open(stamp).read()
        if os.path.exists(os.path.join(OBJ_CACHE, old + ".o")):
            continue   # ((Triforce) stamped with a key of today's kind already: its object is in the cache by it. Nothing to read)
        content = open(src, "rb").read()
        if old == hashlib.sha1(content + " ".join(fl).encode() + deps, usedforsecurity=False).hexdigest():
            key = object_key(src, fl, deps)
            open(stamp, "w").write(key)
            cache_put(obj, key)


PLANNED = {}   # (src, obj) -> the object key plan_jobs worked out, so compile_one does not hash every source again
DEPFILE_JOBS = {}   # ((Triforce) a renderer or runtime object -> the folders' blob, the folders, its other deps: renderer_deps)


def rekey_depfiles(jobs):
    """((Triforce) After the compile: each renderer or runtime object stamped and cached by the key its own depfile gives (renderer_deps), the only key
    that vouches for it. An object compiled now is stamped DEPFILE_PENDING by compile_one when its planned key came from the last
    compile's depfile, which may lack a header the new source reads (add an include, take it out, edit the header, put it
    back, and that key names an object built with the old header); one compiled from the folders' blob was cached
    by that key too, which covers every header. One stamped otherwise is another build's and is left alone"""
    for cc, src, obj, fl, deps in jobs:
        if obj not in DEPFILE_JOBS or not os.path.exists(obj):
            continue
        stamp = obj + ".sha1"
        try:
            with open(stamp) as f:
                old = f.read()
        except OSError:
            continue
        if old != DEPFILE_PENDING and old != (PLANNED.get((src, obj)) or key_of(src, fl, deps)):
            continue
        blob, roots, extras = DEPFILE_JOBS[obj]
        key = key_of(src, fl, renderer_deps(blob, roots, obj) + extras)
        cache_put(obj, key)   # (also when it is the planned key: compile_one caches no object by a depfile key)
        if key != old:
            with open(stamp, "w") as f:
                f.write(key)
        keep_depfile(obj)


def keep_depfile(obj):
    """((Triforce) obj's depfile copied to kept_depfile, when it is not the same there already; a failure costs the next build
    only a compile"""
    src, dst = depfile_of(obj), kept_depfile(obj)
    try:
        with open(src, "rb") as f:
            data = f.read()
        try:
            with open(dst, "rb") as f:
                if f.read() == data:
                    return
        except OSError:
            pass
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst + ".new", "wb") as f:
            f.write(data)
        os.replace(dst + ".new", dst)
    except OSError:
        pass


# (hookshot) the order of the compile: the longest first (LPT), so no long one starts late and runs alone at the end. The lift's
# estimate (gen/chunk_costs.txt, nx2/chunks.py fn_cost: functions cost with the square of their size) where it is there, else the size.
# HOT_COST: how much longer the hot flags (-O2, the profile, the hot callees inlined) take for the same estimate. Fitted to a cold build
# on a 24-thread desktop; by size alone the hot pieces (9 MB, up to 333 s) started after every 25 MB chunk (45 s)
HOT_COST = 4


def chunk_costs(gen):
    try:
        with open(os.path.join(gen, "chunk_costs.txt")) as f:
            return {name: int(n) for name, _, n in (line.partition(" ") for line in f) if n.strip().isdigit()}
    except OSError:
        return {}


def compile_cost(src, costs):
    """A file's compile time, roughly (see HOT_COST)"""
    name = os.path.basename(src)
    return costs.get(name, src_size(src)) * (HOT_COST if name.startswith("code_hot") else 1)


# HOOKSHOT_MEM_LOG=1: each compile's peak memory beside what mem_need counted it at ("@@mem <file> <peak MB> <counted MB>
# <seconds>"), sampled twice a second over the compiler and the processes it starts. For fitting mem_need and the gate to
# what the compilers really take: off unless asked for, and nothing is sampled then
MEM_LOG = os.environ.get("HOOKSHOT_MEM_LOG", "0") not in ("", "0")


def sample_peak(proc, peak):
    """(a thread of its own, beside communicate) peak[0]: the most MB the compiler's process tree was seen holding"""
    while proc.poll() is None:
        peak[0] = max(peak[0], rss_mb(proc))
        time.sleep(0.5)


def compile_one(job):
    cc, src, obj, fl, deps = job
    key = PLANNED.get((src, obj)) or object_key(src, fl, deps)
    PLANNED[(src, obj)] = key   # ((Triforce) for write_kept and rekey_depfiles)
    stamp = obj + ".sha1"
    if os.path.exists(obj) and os.path.exists(stamp) and open(stamp).read() == key:
        return src, 0.0, None
    cached = os.path.join(OBJ_CACHE, key + ".o")
    if os.path.exists(cached):   # (the same source and flags built for the other target)
        if os.path.exists(obj):
            os.remove(obj)
        try:
            os.link(cached, obj)
        except OSError:
            import shutil
            shutil.copyfile(cached, obj)
        open(stamp, "w").write(key)
        return src, 0.0, None
    # ((Triforce, 11-24, after Source A's) a zero byte in the source: the translation and the repository never write one into
    # C, so the drive or the memory changed the file after it was written. A player's code_009.c (26 MB) had one where a "("
    # belonged, and the compiler said only "extraneous ')' before ';'". Refused first, in one line with "error:", with what to
    # do. A read of a few milliseconds for the biggest file, beside a compile of seconds to minutes; a file it cannot read is
    # the compiler's to report)
    try:
        with open(src, "rb") as f:
            data = f.read()
    except OSError:
        data = b""
    at = data.find(b"\0")
    if at >= 0:
        return src, 0.0, ("%s:%d:%d: error: this file has a zero byte, which the build never writes: the drive or the PC's "
                          "memory changed it after it was written. Build again: the file is made again. If this keeps "
                          "happening, check the drive for errors and test the memory"
                          % (src, data.count(b"\n", 0, at) + 1, at - data.rfind(b"\n", 0, at)))
    del data   # (not held while the compiler runs: a 26 MB file per job)
    c_src = src
    if any(f.startswith("-DHOOKSHOT_SPLIT_GIANTS=") for f in fl):   # ((Triforce) HOOKSHOT_SPLIT_GIANTS: a copy with the giants cut, if any)
        import split_giants
        c_src = split_giants.compile_copy(src, obj, fl)
    lease = GATE.enter(src) if GATE else None   # (the whole file's need: the pieces' is less)
    t = time.time()
    peak = [0]
    try:
        with subprocess.Popen([cc] + fl + ["-c", c_src, "-o", obj], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as p:
            no_throttle(getattr(p, "_handle", None))
            if GATE:
                GATE.started(lease, p)
            if MEM_LOG:
                threading.Thread(target=sample_peak, args=(p, peak), daemon=True).start()
            out, err = p.communicate()
    finally:
        if GATE:
            GATE.leave(lease)
        if c_src != src and os.path.exists(c_src):
            os.remove(c_src)
    if MEM_LOG:
        print("@@mem %s %d %d %.1f" % (os.path.basename(src), peak[0], mem_need(src), time.time() - t), flush=True)
    r = subprocess.CompletedProcess(p.args, p.returncode, out, err)
    if r.returncode:
        failure = r.stderr or r.stdout or "Compiler exited with status %d without diagnostics." % r.returncode
        return src, time.time() - t, failure[-4000:]
    if deps.startswith(DEPFILE_DEPS):
        # ((Triforce) keyed by the last compile's depfile: this source may read headers that one did not, so the key does not vouch
        # for the object. rekey_depfiles stamps and caches it by the key its own new depfile gives; a build that stops before
        # that leaves it pending, and the next one compiles it again)
        open(stamp, "w").write(DEPFILE_PENDING)
        return src, time.time() - t, None
    open(stamp, "w").write(key)
    cache_put(obj, key)
    return src, time.time() - t, None


# RX_EARLY=1 (nx2/make_game.py, while the game is being translated): only the files that need nothing of the translated
# game are compiled, and nothing is linked: libopus, the WebGPU renderer and the Vulkan back end with its libraries, ~520 of
# the build's ~630 files and a ninth of its compile time. The lift was one process on Windows and left every other
# processor idle for two minutes (its emit has workers there now, nx2/emit_pool.py: half the processors at most); the build that follows finds these objects made (the same keys: their flags and
# dependencies hold nothing the lift writes) and compiles the game's own files alone. The lifted files are not read here:
# the lift is writing them
EARLY = os.environ.get("RX_EARLY") == "1"


def copy_renhdrum(out, name):
    """(Triforce) RenHDrum beside the game (renhdrum.dll, renhdrum.so on Linux), when scripts/renhdrum.py build has made it
    in third_party/renhdrum/: host/rumble_renhdrum.c loads it by full path from the game's own folder, for the controllers
    it plays (host/vibration.h). Optional: without it every controller keeps its motors or its own HD rumble"""
    rh = os.path.join(kit.HERE, "..", "third_party", "renhdrum", name)
    dst = os.path.join(out, name)
    if os.path.exists(rh) and (not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(rh)):
        import shutil
        shutil.copyfile(rh, dst)


def main():
    kit.wait_for_quiet('the compile')
    p = argparse.ArgumentParser()
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--only", default="")
    p.add_argument("--opt", default="O1")
    p.add_argument("--no-polls", action="store_true")
    p.add_argument("--dll", action="store_true")
    p.add_argument("--lib", action="store_true")
    p.add_argument("--standalone", action="store_true")
    # (CI: a player's build started from the tree the AppImage carries, with no game. Everything up to the compile, without the
    # lift's files; every other file the compile would read must be there, and nothing is compiled. scripts/linux/check_player_build.sh)
    p.add_argument("--dry-run", action="store_true")
    # ((Triforce) make_game.py: the lifted C was let go after the last build, its objects by this list (KEPT_LIST); exit status
    # KEPT_STALE when it no longer fits)
    p.add_argument("--kept-lift", metavar="LIST")
    a = p.parse_args()
    sa = os.path.join(kit.WORK, "sa")
    gen = os.path.join(sa if a.standalone else kit.WORK, "gen")
    out = os.path.join(sa if a.standalone else kit.WORK, "build")
    obj_dir = os.path.join(out, "obj")
    gen_dir = os.path.join(out, "gen")   # (the logo and the fonts the Vulkan back end compiles in: made with it, below)
    os.makedirs(obj_dir, exist_ok=True)
    load_hashes(out)   # ((Triforce) the sources' keys by their size, time and number: HASH_CACHE)
    if os.environ.get("RX_VK_ONLY") or a.dry_run or EARLY:   # (the Vulkan back end needs no game: built so with no lift, as the AppImage's is)
        os.makedirs(gen, exist_ok=True)
    rt64 = rtgen.write(os.path.join(out, "rt64"))
    cc = toolchain.need(toolchain.find("clang"))
    fl = flags(gen, rt64, a.opt, not a.no_polls) + (["-DA64_POLL_CTX"] if a.dll else [])   # (the shim's poll takes the context: rtgen.py)
    # (which Hookshot this is, for the log's first line and the Insert menu: given to those two files only, so a new
    # release name rebuilds them and nothing else)
    stamp_def = version.define()
    print("version: %s" % version.describe(), flush=True)
    # (the lifted chunks include only the guest model: the emulator ABI header is a dependency of the shim alone)
    # (RX_EARLY: none: the lift is writing those headers, and no file compiled early depends on them)
    deps = b"" if EARLY else b"".join(open(os.path.join(d, f), "rb").read() for d in (gen, rt64) for f in sorted(os.listdir(d))
                                      if f.endswith(".h"))
    shim_deps = deps + open(os.path.join(NX2_RT, "mkw_host.h"), "rb").read()
    eden_gen, eden_out = os.path.join(kit.WORK, "gen"), os.path.join(kit.WORK, "build")
    if not EARLY:
        migrate_stamps(eden_gen, os.path.join(eden_out, "obj"),
                       flags(eden_gen, os.path.join(eden_out, "rt64"), a.opt, not a.no_polls) +
                       (["-DA64_POLL_CTX"] if a.dll else []), deps)   # (as fl below: the flags its objects were built with)
        migrate_stamps(gen, obj_dir, fl, deps)
    chunks = [] if EARLY else sorted(f for f in os.listdir(gen) if f.startswith("code_") and f.endswith(".c"))
    if a.kept_lift and a.standalone and not chunks and not EARLY:   # ((Triforce) the lifted C of the last build, let go: KEPT_LIST)
        try:
            KEPT.update(read_kept(a.kept_lift))
        except (OSError, UnicodeDecodeError) as e:
            print("the list of the kept translation could not be read (%s): translating the game again" % e, flush=True)
            return KEPT_STALE
        if not KEPT:
            print("the list of the kept translation is empty or from another translation: translating the game again", flush=True)
            return KEPT_STALE
        chunks = sorted(os.path.basename(s) for s in KEPT)
    if a.only:
        want = {"code_%03d.c" % int(n) for n in a.only.split(",")}
        chunks = [c for c in chunks if c in want]
    srcs = [os.path.join(gen, c) for c in chunks]
    host_srcs = []
    if not a.only:
        srcs += [os.path.join(gen, f) for f in ("a64_table.c", "a64_hooks.c", "a64_suyu.c")] + \
                [os.path.join(rt64, "a64_rt.c")]
        if a.standalone:
            srcs += [os.path.join(gen, f) for f in ("a64_stubs.c", "hos_image.c", "nvn2_exports.c")]
            # (EvilOOT) host/rx_nowgpu.c stands in for the WebGPU renderer only when there is no wgpu-native to build it with (Linux has
            # its own stand-ins, host/posix/linux_stubs.c)
            have_wgpu = os.path.isfile(os.path.join(WGPU, "include", "webgpu", "webgpu.h"))
            host_srcs = sorted(os.path.join(HOST, f) for f in os.listdir(HOST) if f.endswith(".c") and (f != "pgo_rt.c" or PGO == "gen")
                               and not (LINUX and f in ("display.c", "mf_av1.c", "rx_nowgpu.c")) and (f != "rx_nowgpu.c" or not have_wgpu))
            if LINUX:   # (the window on SDL2, the Win32 calls on POSIX, no Media Foundation and no WebGPU renderer)
                host_srcs += [os.path.join(POSIX, f) for f in ("win32_posix.c", "display_sdl.c", "linux_stubs.c", "prof.c")]
        else:
            srcs += [os.path.join(NX2_RT, "eden_shim.c"), write_info(out)]
    if os.environ.get("RX_VK_ONLY"):   # (no lift needed: the back end alone)
        srcs = [s for s in srcs if os.path.exists(s)]
    if EARLY:   # (the lift's files are on their way: none of them now)
        srcs = []
    if a.dry_run:   # (the lift's files: there is no game here)
        srcs = [s for s in srcs if os.path.dirname(s) != gen]
    # ((Triforce, 11-22, the performance audit's LIFT-17, after Source A's) RX_COLD_OPT=O2, or a file that lists chunks: those
    # lifted chunks at -O2 too (never the hot pieces), each compiled as parts of RX_COLD_PART_MB under <build>/split in place
    # of the chunk (nx2/cold_parts.py). Unset: srcs as they are, and no file takes cold_fl below
    cold_stats = {}
    # ((Triforce) not with --kept-lift: the kept objects were built from the whole chunks, whose C is gone)
    srcs, cold = (srcs, set()) if KEPT else cold_parts.expand(srcs, os.path.join(out, "split"), os.environ, stats=cold_stats)
    if cold:
        print("RX_COLD_OPT: %d files at -O2 (parts of %d MB; %d chunks cut again, %d kept as cut before)" % (
            len(cold), cold_parts.part_bytes(os.environ) >> 20, cold_stats.get("written", 0), cold_stats.get("kept", 0)), flush=True)
    # the longest first, so the long ones do not end up alone at the end (compile_cost)
    costs = chunk_costs(gen)
    srcs.sort(key=lambda s: -compile_cost(s, costs))
    # (hookshot) code_hot.c, the lift's hot functions together (A64_HOT_FUNCS + A64_HOT_CHUNK=1): at RX_HOT_OPT
    # (default O2), so the hot callees inline into their hot callers
    hot_fl = [("-" + os.environ.get("RX_HOT_OPT", "O2")) if f == "-" + a.opt else f for f in fl]
    # (triforce) RX_HOT_CAPTURE=<n>: the hot pieces' own -capture-tracking-max-uses-to-explore (see flags()): a hot function
    # that names the context more often than the limit is compiled as if the context escaped (every guest store may change
    # it), and the largest functions are among the hottest
    if os.environ.get("RX_HOT_CAPTURE"):
        hot_fl = [("-capture-tracking-max-uses-to-explore=" + os.environ["RX_HOT_CAPTURE"])
                  if f.startswith("-capture-tracking-max-uses-to-explore=") else f for f in hot_fl]
    # (triforce) RX_HOT_FLAGS=<flags>: more flags for the hot pieces alone (a variant of them without building the rest again)
    if os.environ.get("RX_HOT_FLAGS"):
        hot_fl = hot_fl + os.environ["RX_HOT_FLAGS"].split()
    # ((Triforce) HOOKSHOT_SPLIT_GIANTS: the giants of the lifted chunks and of the hot pieces compiled as pieces)
    giants_fl = split_giants_flags()
    if giants_fl:
        hot_fl = hot_fl + giants_fl
        print("build: giant lifted functions compiled in pieces (HOOKSHOT_SPLIT_GIANTS: %s)" % giants_fl[0], flush=True)
    # (hookshot) RX_PGO=gen: code_hot.c counts its branches (host/pgo_rt.c writes them; -O1 builds much sooner, and the counters are
    # placed before the optimiser, so a profile from it fits the -O2 build). RX_PGO=<merged .prof>: built with that profile
    if PGO == "gen":
        hot_fl = [f if f != "-O2" else "-O1" for f in hot_fl] + ["-fprofile-instr-generate", "-mllvm", "-disable-vp=true"]
    elif PGO:
        # (the profile's contents in the flags the object key hashes: its path alone stays the same across releases, so an update with a
        # new profile kept the hot code built from the old one)
        with open(PGO, "rb") as f:
            hot_fl = hot_fl + ["-fprofile-instr-use=" + PGO, "-DHOOKSHOT_PROFILE_SHA1=" + hashlib.sha1(f.read(), usedforsecurity=False).hexdigest()[:16]]
    cold_fl = cold_parts.cold_flags(fl, a.opt, os.environ) if cold else fl   # ((Triforce, LIFT-17) -O2 and the part size)
    # ((Triforce) RX_A64_RT_O2=1, off by default: the shared instruction and runtime helpers (a64_rt.c, a64_suyu.c), small files
    # beside the giant lifted chunks, at -O2 without raising the chunks' level. It changes the code the game runs: the coordinator
    # measures its fps first (one A/B pair elsewhere went one way, the next the other)
    rt_fl = a64_rt_flags(fl, a.opt)
    if rt_fl is not fl:
        print("build: the shared A64 runtime helpers at -O2 (RX_A64_RT_O2=1)", flush=True)
    bar_kb = light_passes_kb()   # ((Triforce) HOOKSHOT_LIGHT_PASSES=1: the lifted chunks' light flags, lifted_flags)
    if bar_kb is not None and not light_flags_work(cc):
        bar_kb = None
    jobs = [(cc, s, os.path.join(obj_dir, os.path.basename(s)[:-2] + ".o"),
             hot_fl if os.path.basename(s).startswith("code_hot") else cold_fl if s in cold else
             rt_fl if os.path.basename(s) in ("a64_rt.c", "a64_suyu.c") else
             lifted_flags(s, fl + giants_fl, deps, bar_kb) if os.path.basename(s).startswith("code_") and os.path.dirname(s) == gen
             else fl,
             shim_deps if os.path.dirname(s) == NX2_RT else deps) for s in srcs]
    # (issue 624) what the game code's object keys are made of, as short fingerprints: two builds' logs side by side say which part
    # changed when an update compiled everything again (the headers, the flags, the profile, or the lifted code itself)
    if KEPT and OBJ_STORE:   # ((Triforce) a kept object the folder let go that another work folder gave the store)
        object_store.fetch(OBJ_STORE, OBJ_CACHE, [k[0] for k in KEPT.values()])
    if KEPT:   # ((Triforce) the kept translation is used only as it was: the same flags and headers, and every object still cached)
        stale = [os.path.basename(j[1]) for j in jobs if j[1] in KEPT and not os.path.exists(j[1]) and
                 (kept_part(j[3], j[4]) != KEPT[j[1]][2] or not os.path.exists(os.path.join(OBJ_CACHE, KEPT[j[1]][0] + ".o")))]
        if stale:
            print("the translation kept from the last build does not fit this one (%d of %d files: %s): translating the game again"
                  % (len(stale), len(KEPT), ", ".join(stale[:4])), flush=True)
            return KEPT_STALE
        print("the translation kept from the last build: %d files, their objects cached" % len(KEPT), flush=True)
        PLANNED.update({(j[1], j[2]): KEPT[j[1]][0] for j in jobs if j[1] in KEPT and not os.path.exists(j[1])})
    if bar_kb is not None:
        light = sorted(os.path.basename(j[1]) for j in jobs if j[3][-len(LIGHT_FLAGS):] == LIGHT_FLAGS)
        print("build: %d lifted chunks without -O1's module passes (HOOKSHOT_LIGHT_PASSES, functions under %d KB): %s"
              % (len(light), bar_kb, " ".join(light)), flush=True)
    fp = lambda b: hashlib.sha1(b, usedforsecurity=False).hexdigest()[:10]
    norm = lambda f: flag_text(f).encode()
    code = hashlib.sha1(usedforsecurity=False)
    for code_src in sorted(x for x in srcs if os.path.basename(x).startswith("code_")):
        code.update(os.path.basename(code_src).encode() +
                    (KEPT[code_src][0] if code_src in KEPT and not os.path.exists(code_src) else content_sha1(code_src)).encode())
    print("object keys: game-code headers %s, flags %s, hot flags %s, lifted code %s (%d files)" % (
        fp(deps), fp(norm(fl)), fp(norm(hot_fl)), code.hexdigest()[:10],
        sum(1 for x in srcs if os.path.basename(x).startswith("code_"))), flush=True)
    # the runtime: ordinary C at -O2, with its own headers (any host/*.h change rebuilds all of it)
    host_fl = target() + CPU + (["-I" + POSIX, "-D_GNU_SOURCE"] if LINUX else []) + \
        ["-I" + HOST, "-I" + rt64, "-I" + gen, "-Wno-everything", "-O2", "-g0", "-mcx16", "-DA64_POLLING"] + WRITE_TRACK + MARK_BITMAP_HOST
    # ((Triforce) host_deps is what every runtime file was named by before, for a file with no depfile yet (host_blob); each is
    # compiled with -MD and named by the headers its depfile says it read under host_roots (renderer_deps), so a host/*.h edit
    # compiles the files that include it, and an edit to a gpu/ header a runtime file reads (gpu/render/rx.h ...) is no longer
    # missed. host_extras: what a file reads from elsewhere (FFmpeg's version), as before)
    host_deps = deps + b"".join(open(os.path.join(HOST, f), "rb").read() for f in sorted(os.listdir(HOST))
                                if f.endswith(".h"))
    if LINUX:
        host_deps += b"".join(open(os.path.join(POSIX, f), "rb").read() for f in sorted(os.listdir(POSIX)) if f.endswith(".h"))
    host_deps += open(os.path.join(GPU, "vk", "vk_api.h"), "rb").read()   # (rx_backend.c's MKWVK_API_VERSION, vr_game.c's MkwVkXr)
    host_deps += open(os.path.join(GPU, "vk", "dlss_math.h"), "rb").read()   # (host/rx_backend.c's DLSS jitter)
    host_blob, host_extras = host_deps, ffmpeg_version_key()
    host_roots = (HOST, gen, rt64, GPU, os.path.join(OPUS, "include"), os.path.join(kit.HERE, "..", "third_party", "zstd", "lib"))
    host_objs = [os.path.join(obj_dir, "host_" + os.path.basename(s)[:-2] + ".o") for s in host_srcs]
    DEPFILE_JOBS.update((o, (host_blob, host_roots, host_extras)) for o in host_objs)
    jobs += [(cc, s, o,
              host_fl + ["-MD", "-I" + os.path.join(OPUS, "include")] +
              (["-I" + os.path.join(FFMPEG, "include")] if FFMPEG else []) +
              (FFMPEG_LX[0] if LINUX and FFMPEG_LX else []) +
              ([stamp_def] if os.path.basename(s) == "hos_main.c" else []) +
              # (RenoDX's HDR in this build: the scene's colour target is RGBA16F with HDR Native, hos_scene_rgba16f)
              (["-DHOOKSHOT_RENODX"] if RENODX and os.path.basename(s) == "nn_vi.c" else []),
              renderer_deps(host_blob, host_roots, o) + host_extras) for s, o in zip(host_srcs, host_objs)]
    # libopus 1.5.2 (third_party/opus, from TOTKPort): nn::codec's hardware Opus decoder (host/nn_codec.c)
    # (hookshot: built for the same CPU target as the rest (CPU), so its float code can be vectorized where the target has
    # AVX2: the vendored copy has no x86 intrinsics files of its own)
    if host_srcs:
        oflags = target() + CPU + ["-O2", "-g0", "-Wno-everything", "-DOPUS_BUILD", "-DUSE_ALLOCA",
                                              "-DHAVE_LRINTF", "-DHAVE_LRINT"] +             ["-I" + os.path.join(OPUS, d) for d in ("include", "celt", "silk", "silk/float", "src")]
        for rel in open(os.path.join(OPUS, "sources.txt")).read().split():
            jobs.append((cc, os.path.join(OPUS, rel), os.path.join(obj_dir, "opus_" + rel.replace("/", "_")[:-2] + ".o"),
                         oflags, b"opus-1.5.2"))
    # (Triforce) zstd's decoder for the runtime too (third_party/zstd: the same files the Vulkan back end compiles into its
    # DLL for the game's fonts, further down, where their names stay inside it). host/hos_zstd.c decodes the game's files
    # with it when HOS_HOST_ZSTD is set (host/host_zstd.h). Its names are hidden (zstd.h marks its functions visible by
    # itself), so that they are never among the names the program exports: on Linux those come first for every library
    # loaded into it, and a GPU driver that uses the system's libzstd would be handed this decoder for half of its calls
    if host_srcs:
        hzstd = os.path.normpath(os.path.join(kit.HERE, "..", "third_party", "zstd", "lib"))
        hzflags = target() + CPU + ["-O2", "-g0", "-DNDEBUG", "-Wno-everything", "-DZSTD_DISABLE_ASM", "-DZSTD_LEGACY_SUPPORT=0",
                                    "-DZSTD_MULTITHREAD=0", "-fvisibility=hidden", "-DZSTDLIB_VISIBLE=", "-DZSTDERRORLIB_VISIBLE="]
        hzdeps = b"".join(open(os.path.join(d, f), "rb").read()
                          for d in (hzstd, os.path.join(hzstd, "common"), os.path.join(hzstd, "decompress"))
                          for f in sorted(os.listdir(d)) if f.endswith(".h"))
        for f in HOST_ZSTD_SOURCES:
            jobs.append((cc, os.path.join(hzstd, *f.split("/")), os.path.join(obj_dir, "hostzstd_" + os.path.basename(f)[:-2] + ".o"),
                         hzflags, hzdeps))
    # the renderer (C++20, NDEBUG: no asserts in it or suyu), when a wgpu-native release is there
    wgpu = a.standalone and not a.only and not LINUX and os.path.isfile(os.path.join(WGPU, "include", "webgpu", "webgpu.h"))
    if a.standalone and not a.only and not wgpu and not LINUX:
        print("no wgpu-native at %s (WGPU_NATIVE): building without the renderer" % WGPU)
    if wgpu:
        cxx = toolchain.need(toolchain.find("clang++"))
        gflags = target() + ["-std=c++20", "-O2", "-g0", "-DNDEBUG", "-Wno-everything",
                                              "-I" + os.path.join(GPU, "compat"),
                                              "-I" + os.path.join(GPU, "third_party", "suyu"),
                                              "-I" + os.path.join(WGPU, "include"), "-I" + HOST, "-I" + rt64] + WRITE_TRACK +                  ["-include", os.path.join(GPU, "render", "rx_wgpu_names.h")]   # (rx_* -> wgr_*: host/rx_backend.c)
        gdeps = tree_headers(GPU, HOST, skip=("vk",)) + open(os.path.join(WGPU, "include", "webgpu", "webgpu.h"), "rb").read()
        for src in gpu_sources():
            name = os.path.relpath(src, GPU).replace(os.sep, "_")[:-4]
            jobs.append((cxx, src, os.path.join(obj_dir, "gpu_" + name + ".o"), gflags, gdeps))
    # the Vulkan back end, a DLL of its own (RX_BACKEND=vulkan): CPM cache, HOOKSHOT_*_HEADERS, or system includes
    vk_jobs = []
    vk_headers, spirv_headers, vma_headers = vulkan_headers()
    # (the AppImage's prebuilt triforce_vk.so is built without NVIDIA's SDK: a build with HOOKSHOT_NGX_SDK compiles its own)
    vk_prebuilt = prebuilt_renderer()
    build_vk = a.standalone and not a.only and not vk_prebuilt and vk_headers and spirv_headers and vma_headers
    if a.standalone and not a.only and vk_prebuilt:
        print("the Vulkan back end: %s, as built" % vk_prebuilt)
    elif a.standalone and not a.only and not build_vk:
        # (was silent: the exe linked, RX_BACKEND=vulkan then fell through to WebGPU / a stub, black window)
        missing = [n for n, p in (("Vulkan", vk_headers), ("SPIR-V", spirv_headers), ("VMA", vma_headers)) if not p]
        print("no headers for %s (missing %s). Set RX_CPM to a CPM cache, or HOOKSHOT_VULKAN_HEADERS / "
              "HOOKSHOT_SPIRV_HEADERS / HOOKSHOT_VMA_HEADERS (package root or its include/ folder), or install "
              "distro packages vulkan-headers + spirv-headers + vulkan-memory-allocator, or set HOOKSHOT_VK_PREBUILT."
              % (VK_LIB, ", ".join(missing)), flush=True)
        return 1
    elif build_vk:
        print("the Vulkan back end: Vulkan %s, SPIR-V %s, VMA %s" % (vk_headers, spirv_headers, vma_headers), flush=True)
    if build_vk:
        cxx = toolchain.need(toolchain.find("clang++"))
        vk = os.path.join(GPU, "vk")
        # (hookshot) the start-up screen's logo, assets/hookshot.png as RGBA bytes in a header of the build's own (nx2/logo_rgba.py);
        # its bytes are part of vk_imgui.cpp's dependencies. Only when the back end is compiled here: the AppImage's comes built
        # (HOOKSHOT_VK_PREBUILT) and carries neither third_party/fonts nor the back end's sources, and a player's build there
        # stopped at the fonts (FileNotFoundError: LibertinusSans-Regular.ttf, 2026-11-10)
        logo_text = logo_rgba.write(os.path.join(gen_dir, "hookshot_logo.h")).encode()
        # (the overlays' bundled fonts, third_party/fonts/libertinus, as a C++ file of the build's own: nx2/ui_fonts.py)
        fonts_cpp = os.path.join(gen_dir, "ui_fonts.cpp")
        ui_fonts.write(fonts_cpp)
        # (what the shader caches are good for: what translates shaders, not the whole DLL, so a build that changes something else
        # keeps them)
        stamp = hashlib.sha1(usedforsecurity=False)
        translator = [os.path.join(d, f) for top in ("eden", "sirit", "compat") for d, _, fs in os.walk(os.path.join(vk, top)) for f in fs]
        for f in sorted(translator) + [os.path.join(vk, n) for n in ("vk_shader.cpp", "vk_bank.cpp", "vk_state.h", "vk_api.h")]:
            with open(f, "rb") as src:
                stamp.update(os.path.relpath(f, vk).replace("\\", "/").encode() + src.read().replace(bytes((13, 10)), bytes((10,))))
        shader_stamp = "-DHOOKSHOT_SHADER_STAMP=0x%sull" % stamp.hexdigest()[:16]
        # ((Triforce) and what of those translates: the program cache is carried over an update by it, translation_stamp)
        translation_now = translation_stamp(vk, translator)
        translation_def = "-DHOOKSHOT_TRANSLATION_STAMP=0x%sull" % translation_now
        vflags = target() + CPU + (["-fPIC", "-I" + POSIX, "-D_GNU_SOURCE"] if LINUX else []) + [   # (hookshot: the replay is the frame's limit now)
            # (what the code takes for granted, which newer C++ libraries bring in by themselves and older ones do not: issue 48)
            "-include", "algorithm", "-include", "cstdio", "-include", "cstdlib", "-include", "cstring", "-include", "functional",
            "-include", "string", "-include", "vector",
            # ((Triforce, 11-21) HOOKSHOT_VK_LINES=1: a line table in the renderer (the same code, DWARF lines only) for a profile's
            # exact functions, inlined ones too, through llvm-symbolizer: the linker map lacks the file-local functions)
            "-std=c++20", "-O2", "-gline-tables-only" if os.environ.get("HOOKSHOT_VK_LINES") == "1" else "-g0", "-DNDEBUG",
            "-Wno-everything", "-DVK_NO_PROTOTYPES", "-DMKWVK_BUILDING",
            *(["-DHOOKSHOT_RELEASE"] if os.environ.get("RX_RELEASE") == "1" else []),   # (the shaders precompiled before the game)
            # (Eden's recompiler before suyu's root: suyu has its own shader_recompiler/ headers, and a Shader::Info
            # of the other layout in some objects is what crashed the descriptor walk. MKWVK_INCLUDES changes the
            # object keys, which leave the include folders out, when this order changes)
            "-DMKWVK_INCLUDES=2",
            "-I" + os.path.join(vk, "compat"), "-I" + os.path.join(GPU, "compat"), "-I" + os.path.join(vk, "eden"),
            "-I" + os.path.join(GPU, "third_party", "suyu"),
            "-I" + os.path.join(vk, "sirit", "include"), "-I" + os.path.join(vk, "sirit", "src"),
            "-I" + os.path.join(spirv_headers, "include"), "-I" + os.path.join(spirv_headers, "include", "spirv", "unified1"),
            "-I" + os.path.join(vk_headers, "include"), "-I" + os.path.join(vma_headers, "include"),
            "-I" + vk, "-I" + gen_dir]
        # (NVIDIA DLSS, a local build's option: scripts/ngx_sdk.py. Only vk_dlss.cpp sees NVIDIA's headers; without them
        # it is the stubs that say DLSS is not there)
        ngx_flags = ["-DHOOKSHOT_NGX", "-I" + os.path.join(NGX_SDK, "include")] if NGX_SDK else []
        ngx_deps = tree_headers(os.path.join(NGX_SDK, "include")) if NGX_SDK else b""
        if NGX_SDK:
            print("the Vulkan back end: with NVIDIA DLSS (NVIDIA's NGX SDK in %s)" % NGX_SDK, flush=True)
        # (NVIDIA DLSS frame generation, a local build's option: HOOKSHOT_STREAMLINE_SDK=<NVIDIA's Streamline SDK, unpacked>.
        # Only vk_dlssg.cpp sees its headers; nothing of it is linked (sl.interposer.dll is loaded beside the game at run
        # time). Without it that file is the stubs that say it is not there. Windows only)
        sl_sdk = os.environ.get("HOOKSHOT_STREAMLINE_SDK", "")
        if sl_sdk and (LINUX or not os.path.isfile(os.path.join(sl_sdk, "include", "sl_dlss_g.h"))):
            print("build: HOOKSHOT_STREAMLINE_SDK=%s has no include/sl_dlss_g.h (or this is not a Windows build): built "
                  "without NVIDIA DLSS frame generation" % sl_sdk, flush=True)
            sl_sdk = ""
        sl_flags = ["-DHOOKSHOT_DLSSG", "-I" + os.path.join(sl_sdk, "include")] if sl_sdk else []
        sl_deps = tree_headers(os.path.join(sl_sdk, "include")) if sl_sdk else b""
        if sl_sdk:
            print("the Vulkan back end: with NVIDIA DLSS frame generation (NVIDIA's Streamline SDK in %s)" % sl_sdk, flush=True)
        # (AMD FSR 4, a build's option too: only vk_fsr4.cpp sees AMD's headers; without them it is the stubs that say FSR is
        # not there)
        fsr_flags = ["-DHOOKSHOT_FSR", "-I" + os.path.join(kit.HERE, "..", "third_party", "fidelityfx")] if FSR else []
        if FSR:
            print("the Vulkan back end: with AMD FSR 4 (AMD's FSR API headers, third_party/fidelityfx)", flush=True)
        # ((Triforce) Intel XeSS Super Resolution (vk_xess.cpp), from Intel's MIT XeSS API headers (third_party/xess/inc): in every
        # Windows build, as it only loads the player's own libxess.dll at run time (never shipped: Intel's licence) and does
        # nothing without it. Only vk_xess.cpp sees Intel's headers. Not on Linux, where Intel ships no XeSS library: there it is
        # the stubs that say XeSS is Windows only)
        xess_headers = os.path.join(kit.HERE, "..", "third_party", "xess", "inc")
        xess_flags = [] if LINUX else ["-DHOOKSHOT_XESS", "-I" + xess_headers]
        xess_deps = b"" if LINUX else tree_headers(os.path.join(xess_headers, "xess"))
        # (RenoDX's HDR, a build's option too: only vk_renodx.cpp sees its compiled shaders; without them it is the stubs
        # that replace nothing)
        renodx_flags = ["-DHOOKSHOT_RENODX", "-I" + RENODX] if RENODX else []
        renodx_deps = open(os.path.join(RENODX, "renodx_spv.h"), "rb").read() if RENODX else b""
        if RENODX:
            print("the Vulkan back end: with RenoDX's HDR (its shaders compiled in %s)" % RENODX, flush=True)
        # (Eden's recompiler and sirit see only their own headers: a change to the back end's vk_*.h does not
        # rebuild their ~500 files; the back end itself depends on everything, suyu's texture decoders included)
        vk_lib_deps = tree_headers(os.path.join(vk, "eden"), os.path.join(vk, "sirit"), os.path.join(vk, "compat"),
                                   os.path.join(GPU, "compat"))
        vdeps_roots = (vk, os.path.join(GPU, "render"), os.path.join(GPU, "compat"),
                       os.path.join(GPU, "third_party", "suyu", "video_core", "textures"))
        vdeps = tree_headers(*vdeps_roots)
        # (hookshot) Dear ImGui (third_party/imgui) draws the overlays over the window's image (gpu/vk/vk_imgui.cpp; vk_menu.cpp
        # draws with it). Its objects see only its own headers; its headers are a dependency of the two files that include them
        imgui = os.path.normpath(os.path.join(kit.HERE, "..", "third_party", "imgui"))
        zstd = os.path.normpath(os.path.join(kit.HERE, "..", "third_party", "zstd", "lib"))   # (the game's font files: vk_imgui.cpp)
        imgui_flags = ["-I" + imgui, "-I" + zstd, "-DIMGUI_IMPL_VULKAN_NO_PROTOTYPES", "-DIMGUI_DISABLE_DEFAULT_SHELL_FUNCTIONS",
                       "-DIMGUI_DISABLE_WIN32_FUNCTIONS", "-DIMGUI_DISABLE_DEMO_WINDOWS", "-DIMGUI_DISABLE_DEBUG_TOOLS"]
        imgui_deps = b"".join(open(os.path.join(d, f), "rb").read() for d in (imgui, os.path.join(imgui, "backends"), zstd)
                              for f in sorted(os.listdir(d)) if f.endswith(".h"))
        imgui_users = ("vk_imgui.cpp", "vk_menu.cpp", "vk_salesman.cpp")   # (vk_salesman.cpp: the game's files through vk_game_font.h)
        for f in ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp", "backends/imgui_impl_vulkan.cpp"):
            vk_jobs.append((cxx, os.path.join(imgui, *f.split("/")),
                            os.path.join(obj_dir, "vk_imgui_" + os.path.basename(f)[:-4] + ".o"), vflags + imgui_flags, imgui_deps))
        # (zstd's decoder, third_party/zstd, plain C)
        zflags = target() + CPU + (["-fPIC"] if LINUX else []) + ["-O2", "-g0", "-DNDEBUG", "-Wno-everything", "-fvisibility=hidden",
                                                                 "-DZSTD_DISABLE_ASM", "-DZSTD_LEGACY_SUPPORT=0", "-DZSTD_MULTITHREAD=0"]
        zdeps = b"".join(open(os.path.join(d, f), "rb").read() for d in (zstd, os.path.join(zstd, "common"), os.path.join(zstd, "decompress"))
                         for f in sorted(os.listdir(d)) if f.endswith(".h"))
        for f in ("common/debug.c", "common/entropy_common.c", "common/error_private.c", "common/fse_decompress.c", "common/xxhash.c",
                  "common/zstd_common.c", "decompress/huf_decompress.c", "decompress/zstd_ddict.c", "decompress/zstd_decompress.c",
                  "decompress/zstd_decompress_block.c"):
            vk_jobs.append((cc, os.path.join(zstd, *f.split("/")), os.path.join(obj_dir, "vk_zstd_" + os.path.basename(f)[:-2] + ".o"),
                            zflags, zdeps))
        # (the bundled fonts, compiled in: nx2/ui_fonts.py's file of the build's own)
        vk_jobs.append((cxx, fonts_cpp, os.path.join(obj_dir, "vk_ui_fonts.o"), target() + (["-fPIC"] if LINUX else []) + ["-O0", "-g0", "-w"],
                        b""))
        vk_pgo = vk_pgo_flags()   # ((Triforce, 11-21, LIFT-10) the renderer's own files alone)
        if VK_PGO == "gen" and not LINUX:   # (what writes the counters, the DLL's own copy: host/pgo_rt.c)
            vk_jobs.append((cc, os.path.join(HOST, "pgo_rt.c"), os.path.join(obj_dir, "vk_pgo_rt.o"),
                            target() + ["-O2", "-g0", '-DPGO_ENV="RX_VK_PGO_FILE"'], b""))
        for src in vk_sources():
            name = os.path.relpath(src, vk).replace(os.sep, "_")[:-4]
            lib = os.path.relpath(src, vk).split(os.sep)[0] in ("eden", "sirit")
            obj = os.path.join(obj_dir, "vk_" + name + ".o")
            # ((Triforce) the renderer's own files: the headers their depfile names (renderer_deps); DEPFILE_JOBS re-keys them)
            extras = ((logo_text if os.path.basename(src) == "vk_imgui.cpp" else b"") +
                      (renodx_deps if os.path.basename(src) == "vk_renodx.cpp" else b"") +
                      (xess_deps if os.path.basename(src) == "vk_xess.cpp" else b"") +
                      (ngx_deps if os.path.basename(src) == "vk_dlss.cpp" else b"") +
                      (sl_deps if os.path.basename(src) == "vk_dlssg.cpp" else b"") +
                      (imgui_deps if os.path.basename(src) in imgui_users else b""))
            if not lib:
                DEPFILE_JOBS[obj] = (vdeps, vdeps_roots, extras)
            vk_jobs.append((cxx, src, obj,
                            vflags + ([] if lib else vk_pgo + ["-MD"]) +
                            ([shader_stamp, translation_def] if os.path.basename(src) == "vk_shader.cpp" else []) +
                            ([stamp_def] if os.path.basename(src) == "vk_menu.cpp" else []) +
                            (ngx_flags if os.path.basename(src) == "vk_dlss.cpp" else []) +
                            (sl_flags if os.path.basename(src) == "vk_dlssg.cpp" else []) +
                            (imgui_flags if os.path.basename(src) in imgui_users else []) +
                            (fsr_flags if os.path.basename(src) == "vk_fsr4.cpp" else []) +
                            (xess_flags if os.path.basename(src) == "vk_xess.cpp" else []) +
                            (renodx_flags if os.path.basename(src) == "vk_renodx.cpp" else []),
                            vk_lib_deps if lib else renderer_deps(vdeps, vdeps_roots, obj) + extras))
        # ((Triforce) the ReShade presets (the Graphics tab's ReShade preset row): ReShade's FX compiler (third_party/reshade_fx,
        # BSD-3-Clause; stb_image's PNG decoder, MIT) and the presets' runtime in gpu/vk/reshade, which vk_sources leaves out
        vk_jobs.extend(reshade_fx.build_jobs(cxx, os.path.normpath(os.path.join(kit.HERE, "..")), gen_dir, obj_dir, vflags + vk_pgo,
                                             vflags, vdeps, windows=not LINUX))
        if NGX_SDK and not LINUX and toolchain.mingw():
            # (llvm-mingw: NVIDIA's static library was built with Microsoft's compiler for its static runtime (/MT). What it asks
            # of that runtime: the C parts as for the static FFmpeg (host/mingw_msvc_shims.c), the C++ ones in vk_ngx_msvc_rt.cpp)
            vk_jobs.append((cxx, os.path.join(vk, NGX_MSVC_RT), os.path.join(obj_dir, "vk_ngx_msvc_rt.o"), vflags + ngx_flags, vdeps))
            vk_jobs.append((cc, os.path.join(HOST, "mingw_msvc_shims.c"), os.path.join(obj_dir, "vk_ngx_mingw_msvc_shims.o"),
                            target() + ["-O2", "-g0", "-Wno-everything"], b""))
        if LINUX:   # (its own copy of the Win32 calls on POSIX)
            cflags = target() + CPU + ["-fPIC", "-O2", "-g0", "-Wno-everything", "-D_GNU_SOURCE", "-I" + POSIX]
            pdeps = tree_headers(POSIX)
            for f in ("win32_posix.c",):
                vk_jobs.append((cc, os.path.join(POSIX, f), os.path.join(obj_dir, "vk_posix_" + f[:-2] + ".o"), cflags, pdeps))
        jobs += vk_jobs
    if build_vk:   # ((Triforce) which files of the translation stamp changed it against the last release's and the previous
        # build's, said in the log; the record is kept below, once the objects are compiled)
        translation_record = (os.path.join(out, TRANSLATION_RECORD), translation_now, translation_files(vk, translator))
        translation_stamp_note(*translation_record)
    vk_only = bool(os.environ.get("RX_VK_ONLY"))   # (the renderer alone, the game's objects as they are)
    if vk_only:
        jobs = list(vk_jobs)
    if EARLY:   # (by their objects' names: libopus, the WebGPU renderer, the Vulkan back end; never the runtime's host_*.o)
        jobs = [j for j in jobs if os.path.basename(j[2]).startswith(("opus_", "gpu_", "vk_"))]
    if a.dry_run:   # (the compile starts here: what it would read, said and checked, and nothing compiled)
        missing = sorted({j[1] for j in jobs if not os.path.isfile(j[1])} |
                         ({vk_prebuilt} if vk_prebuilt and not os.path.isfile(vk_prebuilt) else set()))
        print("dry run: %d files to compile besides the lift's, %d missing" % (len(jobs), len(missing)), flush=True)
        for f in missing:
            print("    missing: " + f)
        return 1 if missing else 0
    # (the builder's compile timer: HOOKSHOT_TIMES is make_game.py's record of the earlier builds on this PC. With it,
    # this run says which files it really rebuilds and how long each took before, and the builder shows the rest of the
    # compile as a countdown that follows this PC's own measurements. Run by hand, it prints none of these lines.)
    global GATE
    GATE = None if os.environ.get("HOOKSHOT_MEM_GATE") == "0" else MemoryGate()
    eta_jobs = GATE.expected(a.jobs) if GATE else a.jobs   # (the countdown with the compilers the memory holds, not --jobs)
    if not EARLY:
        write_compdb(out, jobs, gen)   # ((Triforce) for clangd and clang-tidy; the lifted C left out)
    counted, expected, pending = os.environ.get("HOOKSHOT_TIMES"), {}, []
    if OBJ_STORE and not EARLY:   # ((Triforce) the objects this build needs that another work folder built: in the folder's cache
        # before the plan counts them. The folder's own first, those of a build that stopped before it shared them too)
        object_store.share(OBJ_CACHE, OBJ_STORE)
        for _, src, obj, fl, deps in jobs:
            if (src, obj) not in PLANNED and os.path.exists(src):
                PLANNED[(src, obj)] = key_of(src, fl, deps)
        got = object_store.fetch(OBJ_STORE, OBJ_CACHE, [PLANNED[(j[1], j[2])] for j in jobs if (j[1], j[2]) in PLANNED])
        print("object store %s: %d objects from it" % (OBJ_STORE, got), flush=True)
    if counted:
        work_jobs, keys = plan_jobs(jobs)
        PLANNED.update(keys)
        if not EARLY:
            save_hashes(out)   # ((Triforce) the sources this plan hashed, for the next build: HASH_CACHE)
        estimate = per_file_seconds(work_jobs, times_from(counted))
        pending = list(estimate)
        for job, seconds in zip(work_jobs, estimate):
            expected.setdefault(job[1], []).append(seconds)
        print("@@plan %d %d" % (len(work_jobs), len(jobs)), flush=True)
        print("@@eta %d" % eta_left(pending, eta_jobs), flush=True)
    print("%d files, %d jobs, %s" % (len(jobs), a.jobs, " ".join(f for f in fl if f.startswith("-D") or f.startswith("-O"))),
          flush=True)
    t0, failed = time.time(), []
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        # (as each ends, not in order: the builder app shows progress from these lines, and the biggest file comes first)
        submitted = {ex.submit(compile_one, job): job for job in jobs}
        try:
            for future in concurrent.futures.as_completed(submitted):
                src, secs, err = future.result()
                size = src_size(src) >> 20
                if err:
                    failed.append(submitted[future])
                    print("not compiled yet: %s (%d MB, %.0fs), tried again alone at the end:\n%s"
                          % (os.path.basename(src), size, secs, err[-1500:]), flush=True)
                else:
                    print("  %-16s %4d MB  %6.0fs  (%.0fs)" % (os.path.basename(src), size, secs, time.time() - t0), flush=True)
                if counted:
                    print("@@file %s %.1f %s" % (os.path.basename(src), secs,
                                                 "failed" if err else "cached" if secs <= 0 else "new"), flush=True)
                    if not err and expected.get(src):
                        pending.remove(expected[src].pop())
                        print("@@eta %d" % eta_left(pending, eta_jobs), flush=True)
        except BaseException:
            # ((Triforce, 11-21, the performance audit's LIFT-31, after Source A's) A compiler's error comes back as a value and
            # is tried again alone. An exception does not: a compiler that is missing or blocked, an object or its stamp that
            # cannot be written, a full disk in cache_put, a file gone before its size is asked, Ctrl-C. It leaves this block,
            # and the pool's exit then ran every compile still queued first, the whole compile with nothing said, before the
            # build stopped; and make_game deletes those objects, as no "compiled in" line follows. So: the queued ones are
            # cancelled, and those waiting at the memory gate are told to go (MemoryGate.stop); the compilers running end)
            if GATE:
                GATE.stop()
            ex.shutdown(wait=False, cancel_futures=True)
            raise
    # (a compiler that ran out of memory beside the others dies "due to signal": a player's 24 MB code_021.c, 2026-11-08. The
    # files that failed are compiled again one at a time, with all the memory, before the build gives up)
    still = 0
    for job in failed:
        src, secs, err = compile_one(job)
        size = src_size(src) >> 20
        if err:
            still += 1
            print("FAILED %s (%d MB, %.0fs, alone too):\n%s" % (os.path.basename(src), size, secs, err), flush=True)
        else:
            print("  %-16s %4d MB  %6.0fs  (%.0fs, alone)" % (os.path.basename(src), size, secs, time.time() - t0), flush=True)
        if counted:
            print("@@file %s %.1f %s" % (os.path.basename(src), secs, "failed" if err else "again"), flush=True)
            if not err and expected.get(src):
                pending.remove(expected[src].pop())
                print("@@eta %d" % eta_left(pending, eta_jobs), flush=True)
    print("compiled in %.0fs, %d failed" % (time.time() - t0, still), flush=True)
    if still:
        return 1
    if not EARLY:   # ((Triforce) the keys the compile worked out, for the next build, whether or not a countdown planned them)
        save_hashes(out)
    rekey_depfiles(jobs)   # ((Triforce) the renderer's own objects and the runtime's, by their new depfiles; early ones too)
    if OBJ_STORE and not EARLY:   # ((Triforce) after rekey_depfiles: the objects it caches by their depfile's key go to the store too)
        print("object store: %d new objects to it" % object_store.share(OBJ_CACHE, OBJ_STORE), flush=True)
    if build_vk:   # ((Triforce) the translation stamp this build compiled, for the next build's line: translation_stamp_note)
        translation_stamp_keep(*translation_record)
    if EARLY:   # (nothing to link yet: the game's own objects come with the build after the lift)
        return 0
    # ((Triforce) the lifted files' object keys, for an update that skips the lift: KEPT_LIST. Not for a part of the game (--only,
    # the renderer alone) nor for chunks compiled in parts (RX_COLD_OPT): those objects are not the whole chunks')
    if a.standalone and not a.only and not vk_only and not cold and not a.dry_run:
        write_kept(gen, jobs)
    vk_objs = {j[2] for j in vk_jobs}
    objs = [j[2] for j in jobs if j[2] not in vk_objs]
    rsp = os.path.join(out, "objs.rsp")
    open(rsp, "w", encoding="utf-8").write("\n".join('"%s"' % o.replace("\\", "/") for o in objs))
    if a.lib:
        lib = os.path.join(out, "hookshot_game.lib")
        subprocess.run([toolchain.lld_link(), "/lib", "/out:" + lib, "@" + rsp], check=True)
        print("wrote %s (%d objects, %d MB)" % (lib, len(objs), os.path.getsize(lib) >> 20))
    if a.standalone and not a.only and not vk_only and LINUX:
        exe = os.path.join(out, EXE)   # (+ Triforce.map: crash offsets -> f_<guest address>)
        t = time.time()
        # (--export-dynamic-symbol: the window's state, which the Vulkan back end's own Win32 calls read by name)
        r = run_link([cc] + target() + ["-fuse-ld=lld", "-o", exe] + linker("-Map=" + exe + ".map") +
                           ["-Wl,--gc-sections", "-Wl,--export-dynamic-symbol=hos_posix_*", "@" + rsp] + HOT_ORDER() +
                           (["-fprofile-instr-generate"] if PGO == "gen" else []) +
                           (FFMPEG_LX[1] if FFMPEG_LX else []) + HOST_LIBS, exe)
        undefined = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if "undefined symbol" in l})
        if r.returncode:
            print("link FAILED (%.0fs), %d undefined symbols" % (time.time() - t, len(undefined)))
            print("\n".join(undefined[:60]) if undefined else (r.stdout + r.stderr)[-3000:])
            return 1
        too_big = image_too_big(exe)   # ((Triforce, 11-24))
        if too_big:
            print(too_big)
            return 1
        print("linked %s: %d MB (%.0fs)" % (exe, os.path.getsize(exe) >> 20, time.time() - t))
        sdl = os.environ.get("HOOKSHOT_SDL2", "")   # (libSDL2-2.0.so.0 beside it, when the AppImage brings one)
        if sdl and os.path.exists(sdl):
            import shutil
            shutil.copyfile(sdl, os.path.join(out, "libSDL2-2.0.so.0"))
        copy_renhdrum(out, "renhdrum.so")
    elif a.standalone and not a.only and not vk_only:
        exe = os.path.join(out, "Triforce.exe")   # (+ Triforce.map: crash offsets -> f_<guest address>)
        t = time.time()
        r = run_link([cc] + toolchain.native_target() + toolchain.native_link() +
                           ["-o", exe] + linker("/map:" + exe[:-4] + ".map") + [toolchain.link_opt("/stack:8388608"), "@" + rsp] + HOT_ORDER() + HOST_LIBS +
                           repro_link() +   # ((Triforce, 11-22, IO-45) HOOKSHOT_LINK_REPRO=1: no link time in the file)
                           ([toolchain.link_opt("/nodefaultlib:clang_rt.profile.lib")] if PGO == "gen" else []) +
                           ([os.path.join(kit.WORK, "hookshot.res")] if os.path.exists(os.path.join(kit.WORK, "hookshot.res")) else []) +   # (nx2/make_icon.py)
                           [win_manifest.write(os.path.join(out, "hookshot_manifest.res"))] +   # (UTF-8 paths: nx2/win_manifest.py)
                           ([toolchain.link_opt("/subsystem:windows"), toolchain.link_opt("/entry:mainCRTStartup")] if os.environ.get("RX_RELEASE") == "1" else []) +   # (no console window)
                           ([os.path.join(WGPU, "lib", "wgpu_native.dll.lib")] if wgpu else []) +
                           ([os.path.join(FFMPEG, "lib", l + ".lib") for l in ("avcodec", "swscale", "swresample", "avutil")] +
                            ["-lbcrypt", "-lmfplat", "-lmfuuid", "-lstrmiids", "-lole32"] if FFMPEG else []) +
                           (["-lc++", "-lunwind"] if toolchain.mingw() else []),   # (llvm-mingw: the C++ parts' runtime, linked in; MSVC's comes by itself)
                           exe)
        undefined = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if "undefined symbol" in l})
        if r.returncode:
            print("link FAILED (%.0fs), %d undefined symbols" % (time.time() - t, len(undefined)))
            print("\n".join(undefined[:60]) if undefined else (r.stdout + r.stderr)[-3000:])
            return 1
        too_big = image_too_big(exe)   # ((Triforce, 11-24))
        if too_big:
            print(too_big)
            return 1
        print("linked %s: %d MB (%.0fs)" % (exe, os.path.getsize(exe) >> 20, time.time() - t))
        if wgpu:   # (wgpu_native.dll beside it; in use while the game runs)
            import shutil
            dll, dst = os.path.join(WGPU, "lib", "wgpu_native.dll"), os.path.join(out, "wgpu_native.dll")
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(dll):
                shutil.copyfile(dll, dst)
        # (hookshot) a shared FFmpeg's DLLs beside it (an LGPL shared build, as cross builds find: the static one needs none)
        for l in FFMPEG_LIBS if FFMPEG and os.path.isdir(os.path.join(FFMPEG, "bin")) else ():
            import shutil
            for f in os.listdir(os.path.join(FFMPEG, "bin")):
                if f.startswith(l + "-") and f.endswith(".dll"):
                    shutil.copyfile(os.path.join(FFMPEG, "bin", f), os.path.join(out, f))
        # (hookshot) SDL2.dll beside it: host/pad_sdl.c's controllers (DualSense, DualShock 4, Switch Pro ...)
        sdl = os.path.join(kit.HERE, "..", "third_party", "sdl2", "SDL2.dll")
        sdl_dst = os.path.join(out, "SDL2.dll")
        if os.path.exists(sdl) and (not os.path.exists(sdl_dst) or os.path.getsize(sdl_dst) != os.path.getsize(sdl)):
            import shutil
            shutil.copyfile(sdl, sdl_dst)
        # (SDL2.dll is sdl2-compat: the SDL2 calls on SDL3, whose controller support is current (a Steam Controller user's
        # report). It loads SDL3.dll from beside it)
        sdl3 = os.path.join(kit.HERE, "..", "third_party", "sdl2", "SDL3.dll")
        sdl3_dst = os.path.join(out, "SDL3.dll")
        if os.path.exists(sdl3) and (not os.path.exists(sdl3_dst) or os.path.getsize(sdl3_dst) != os.path.getsize(sdl3)):
            import shutil
            shutil.copyfile(sdl3, sdl3_dst)
        copy_renhdrum(out, "renhdrum.dll")
    if vk_prebuilt and a.standalone and not a.only:
        import shutil
        shutil.copyfile(vk_prebuilt, os.path.join(out, VK_LIB))
    if vk_jobs:   # (triforce_vk.dll beside the exe: loaded by host/rx_backend.c with RX_BACKEND=vulkan)
        vdll = os.path.join(out, VK_LIB)
        vrsp = os.path.join(out, "vk_objs.rsp")
        open(vrsp, "w", encoding="utf-8").write("\n".join('"%s"' % j[2].replace("\\", "/") for j in vk_jobs))
        t = time.time()
        if LINUX:   # (its C++ runtime inside: the game folder runs where the AppImage's sysroot is older than the system)
            link = [toolchain.need(toolchain.find("clang++"))] + target() + ["-fuse-ld=lld", "-shared", "-o", vdll] + \
                linker("-Map=" + vdll + ".map") + ["-Wl,-Bsymbolic", "-Wl,--gc-sections", "-static-libstdc++", "-static-libgcc",
                                                   "@" + vrsp] + \
                ([ngx_library(NGX_SDK, True)] if NGX_SDK else []) + ["-ldl", "-lpthread", "-lm"]
        else:   # (Triforce: advapi32 for RivaTuner Statistics Server's folder in the registry, gpu/vk/rtss_sys_win.cpp)
            link = [cc] + toolchain.native_target() + toolchain.native_link() + \
                ["-shared", "-o", vdll] + linker("/map:" + vdll[:-4] + ".map") + ["@" + vrsp, "-luser32", "-ladvapi32"] +               (["-lc++", "-lunwind"] if toolchain.mingw() else []) + ngx_link(NGX_SDK, toolchain.mingw()) + repro_link()
        r = run_link(link, vdll)
        if r.returncode:
            undefined = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if "undefined symbol" in l})
            print("%s link FAILED, %d undefined symbols" % (VK_LIB, len(undefined)))
            print("\n".join(undefined[:60]) if undefined else (r.stdout + r.stderr)[-3000:])
            return 1
        if LINUX and not check_vk_symbols(vdll):
            return 1
        print("linked %s: %d MB (%.0fs)" % (vdll, os.path.getsize(vdll) >> 20, time.time() - t))
    if a.dll and not a.only:
        dll = os.path.join(out, "hookshot_game.dll")   # (+ hookshot_game.map: crash offsets -> f_<guest address>)
        t = time.time()
        r = subprocess.run([cc] + toolchain.native_target() + toolchain.native_link() +
                           ["-shared", "-o", dll] + linker("/map:" + dll[:-4] + ".map") + ["@" + rsp],
                           capture_output=True, text=True)
        undefined = sorted({l.strip() for l in (r.stdout + r.stderr).splitlines() if "undefined symbol" in l})
        if r.returncode:
            print("link FAILED (%.0fs), %d undefined symbols" % (time.time() - t, len(undefined)))
            print("\n".join(undefined[:40]) if undefined else (r.stdout + r.stderr)[-3000:])
            return 1
        too_big = image_too_big(dll)   # ((Triforce, 11-24))
        if too_big:
            print(too_big)
            return 1
        print("linked %s: %d MB, no undefined symbols (%.0fs)" % (dll, os.path.getsize(dll) >> 20, time.time() - t))
    return 0


if __name__ == "__main__":
    sys.exit(main())

