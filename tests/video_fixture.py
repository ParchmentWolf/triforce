"""What the movie tests share (tests/test_video_*.py; not a test itself): host/nn_video.c compiled whole, as it is, over
the stand-ins of tests/video_standins.h, with a test's own program after it.

The folder made for a build holds hos.h, libavcodec/avcodec.h and libswscale/swscale.h, each one line that includes the
stand-ins, and a copy of nn_video.c beside them: an include in quotes looks in the including file's folder first, so the
copy takes the stand-in hos.h and the real rule headers (video_wait.h and the others) from host/.

The stand-ins take windows.h for the SRW locks and the interlocked counts nn_video.c uses: the fixture is built and run
on Windows only (WINDOWS_ONLY says why where a test skips it). What a test reads from the source, and the rule headers
it compiles alone, are checked on every system.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"
TESTS = ROOT / "tests"
WINDOWS = os.name == "nt"
WINDOWS_ONLY = "SKIP: nn_video.c over its stand-ins is built on Windows only (they take windows.h's locks)"


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    """The text from marker to the brace that closes the first one opened after it"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def video_source():
    return (HOST / "nn_video.c").read_text(encoding="utf-8")


def build(tmp, cc, program, name="movie"):
    """nn_video.c and `program` (C, written after it in one file) as an executable in tmp; its path"""
    tmp = Path(tmp)
    one_line = '#include "video_standins.h"\n'
    (tmp / "hos.h").write_text(one_line, encoding="utf-8")
    for folder, header in (("libavcodec", "avcodec.h"), ("libswscale", "swscale.h")):
        (tmp / folder).mkdir(exist_ok=True)
        (tmp / folder / header).write_text(one_line, encoding="utf-8")
    (tmp / "nn_video.c").write_text(video_source(), encoding="utf-8")
    src, exe = tmp / (name + ".c"), tmp / (name + ".exe")
    src.write_text('#include "nn_video.c"\n#include "video_play.h"\n' + program, encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Wno-unused-function", "-Wno-unused-parameter",
                    "-Wno-unused-variable", "-I", str(tmp), "-I", str(TESTS), "-I", str(HOST), str(src), "-o", str(exe)],
                   check=True)
    return exe


def run(exe, *args, **env):
    """The program's output; env: variables set for this run (None: unset), over a clean HOS_ / SI_ environment"""
    e = {k: v for k, v in os.environ.items() if not k.startswith(("HOS_", "SI_"))}
    e.update({k: str(v) for k, v in env.items() if v is not None})
    r = subprocess.run([str(exe), *args], capture_output=True, text=True, env=e)
    check(r.returncode == 0, "%s %s failed (%d):\n%s%s" % (Path(exe).name, " ".join(args), r.returncode, r.stdout, r.stderr))
    return r.stdout
