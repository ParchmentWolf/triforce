"""No code word in host/ and gpu/vk that windows.h turns into a macro. windows.h, even with WIN32_LEAN_AND_MEAN and NOMINMAX
(gpu/vk/vk_loader.h, host/hos_instance.h), defines far, near, pascal, cdecl as nothing or a calling convention
(minwindef.h), IN, OUT, OPTIONAL as nothing, DELETE (winnt.h), and ERROR, OPAQUE, TRANSPARENT, ABSOLUTE, RELATIVE as numbers
(wingdi.h). A variable, member or enum of one of those names builds on Linux and fails on Windows once the file includes
windows.h, even through another header: "const float far = ..., near = ...;" in gpu/vk/vk_xr.cpp failed with "expected
unqualified-id" when it came to include vk_dump.h (2026-11-27). The names are this list, taken from llvm-mingw's headers, so
the check needs no Windows headers and runs anywhere.

Comments, strings and character constants are skipped. A line of Windows-only code may still use one on purpose (an API's
own constant): mark it with "// windows.h" and it is let through.

Not checked: min, max (NOMINMAX), small, hyper (rpcndr.h), interface (objbase.h): WIN32_LEAN_AND_MEAN leaves those headers
out, and the sources use min, max and small as names on purpose.

    python -I tests/test_windows_macro_names.py
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
# (the game's own sources: not host/posix, the Linux stand-ins, nor the vendored emulator and compiler code)
SOURCES = [ROOT / "host", ROOT / "gpu" / "vk"]
VENDORED = ("host/posix/", "gpu/vk/eden/", "gpu/vk/sirit/", "gpu/vk/compat/")
MACROS = ("far", "near", "pascal", "cdecl", "FAR", "NEAR", "PASCAL", "CDECL", "IN", "OUT", "OPTIONAL", "DELETE", "ERROR",
          "OPAQUE", "TRANSPARENT", "ABSOLUTE", "RELATIVE")
WORD = re.compile(r"[A-Za-z_]\w*")
ALLOWED = "// windows.h"


def code_only(text):
    """text with comments, strings and character constants blanked (newlines kept, so line numbers hold)"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif c == "R" and text.startswith('R"', i) and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
            open_ = text.find("(", i + 2)
            close = ")" + text[i + 2:open_] + '"'
            j = text.find(close, open_)
            j = n if j < 0 else j + len(close)
        elif c in "\"'" and not (c == "'" and i > 0 and text[i - 1].isalnum()):   # (1'000: a digit separator)
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
        else:
            out.append(c)
            i += 1
            continue
        out.append(re.sub(r"[^\n]", " ", text[i:j]))
        i = j
    return "".join(out)


def check_sources():
    bad = []
    for top in SOURCES:
        for p in sorted(top.rglob("*")):
            rel = p.relative_to(ROOT).as_posix()
            if p.suffix not in (".c", ".h", ".cpp", ".hpp") or rel.startswith(VENDORED) or rel.endswith("_spv.h"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            for i, line in enumerate(code_only(text).splitlines(), 1):
                if ALLOWED in lines[i - 1]:
                    continue
                for m in WORD.finditer(line):
                    if m.group(0) in MACROS and line[max(0, m.start() - 8):m.start()].rstrip()[-6:] not in ("#undef", "define"):
                        bad.append("%s:%d: %s (%s)" % (rel, i, lines[i - 1].strip(), m.group(0)))
    assert not bad, ("a name that windows.h makes a macro (rename it; a deliberate Windows API use: end the line with "
                     "\"%s\"):\n" % ALLOWED) + "\n".join(bad)


def check_self():
    sample = 'int far = 1; /* far */ const char *s = "near"; // near\nchar c = \'\\\'\'; float near;\n'
    found = [m.group(0) for m in WORD.finditer(code_only(sample)) if m.group(0) in MACROS]
    assert found == ["far", "near"], found
    assert code_only('a R"x(far)x" b').split() == ["a", "b"]
    assert code_only("int n = 1'000; int far;").count("far") == 1


def main():
    check_self()
    check_sources()
    print("PASS: no windows.h macro names as code words")


if __name__ == "__main__":
    main()
