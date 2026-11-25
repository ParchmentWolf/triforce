"""nn::fs::OpenFile gives its virtual core up before the path is worked out, and takes it back on every way out
(host/nn_fs.c OpenFile, host/prompts.c hos_prompts_font_file; no game).

(Triforce, 11-21, the performance audit's IO-24, after Source A's.) OpenFile gave the core up only around the host's
own open. Working the path out reaches the button prompts' builder, which builds a file at its first open, a quarter of
a second and more, while the other openers wait for it: each of them held a virtual core the whole time.

Reads the source, and walks OpenFile's text: the core is given up after the guest's path is read and before host_path;
between the give-up and the host's open no guest memory is read or written but through RET; every return on the way
has the take-back right before its RET; the open's own take-back is still there; with the switch the core is given up
around CreateFileA alone, as before; the prompts' font hook gives the core up around the builder, not inside it.

    python -I -B tests/test_open_file_vcore.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    fs = (ROOT / "host" / "nn_fs.c").read_text(encoding="utf-8")
    body = block(fs, "HLE(_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci) {")
    code = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    give, path, create = code.index("int away = open_keep_core ? 0 : hos_vcore_away();"), code.index("host_path(g, path"), code.index("CreateFileA(")
    check(code.index("const char *g = gstr(ARG(1));") < give < path < create,
          "the core is not given up after the guest's path is read and before host_path")
    check('open_keep_core = getenv("HOS_OPEN_KEEP_CORE") != NULL;' in code and
          "if (open_keep_core) away = hos_vcore_away();" in code[give:create],
          "the switch does not keep the core until the host's open, as before")
    away_part = code[give:create]
    # (no guest memory touched while the core is away, except the answer: each RET is right after a take-back)
    check("gstr(" not in away_part and "G64(" not in away_part and "G32(" not in away_part and "recomp_" not in away_part,
          "guest memory is read or written while the core is away")
    returns = [m.start() for m in re.finditer(r"\bRET\(", away_part)]
    check(len(returns) == 4, "OpenFile has %d ways out before its open: this test knows 4" % len(returns))
    for at in returns:
        before = away_part[:at].rstrip()
        check(before.endswith("if (away) hos_vcore_back();"), "a return before the open answers the game without taking the core back: ..." + before[-80:])
    after = code[create:]
    # (the open's error is read before the take-back, which waits and may change it: that one line is all there is between)
    back = after.index("if (away) hos_vcore_back();")
    between = after[after.index(";") + 1:back].strip()
    check(between in ("", "const DWORD open_err = h == INVALID_HANDLE_VALUE ? GetLastError() : 0;"),
          "the core is not taken back right after the host's open: " + between[:120])
    check(back < after.index("if (h == INVALID_HANDLE_VALUE)"), "the open's answer is looked at before the core is taken back")
    check(code.count("hos_vcore_away()") == 2 and code.count("hos_vcore_back()") == 5, "a give-up or take-back this test does not know")
    # ((Triforce, 11-24) WriteFile and FlushFile: the core given up around the host's call alone, the answer after it is back
    for name, call in (("_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE", "WriteFile(fh->h"),
                       ("_ZN2nn2fs9FlushFileENS0_10FileHandleE", "FlushFileBuffers(fh->h)")):
        w = re.sub(r"/\*.*?\*/", " ", block(fs, "HLE(%s) {" % name), flags=re.S)
        at = [w.index(p) for p in ("get_handle(c, ARG(0))", "fs_write_keep_core() ? 0 : hos_vcore_away();", call,
                                   "if (away) hos_vcore_back();", "RET(")]
        check(at == sorted(at), name + ": the core is not given up around the host's call")
        check(w.count("RET(") == 1 and w.count("hos_vcore_away()") == 1 and w.count("hos_vcore_back()") == 1,
              name + ": a way out this test does not know")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_WRITE_KEEP_CORE=1`" in dev, "docs/development.md: HOS_WRITE_KEEP_CORE=1 is not in the switches table")
    prompts = (ROOT / "host" / "prompts.c").read_text(encoding="utf-8")
    font = block(prompts, "int hos_prompts_font_file(const char *key, char *out, size_t cap) {")
    at = [font.index(p) for p in ("if (strcmp(key, FONT_PATH)) return 0;", "const int away = hos_vcore_away();",
                                  "hos_prompts_romfs(FONT_PATH, out, cap);", "if (away) hos_vcore_back();", "return found;")]
    check(at == sorted(at), "the font hook does not give the core up around the builder")
    romfs = block(prompts, "int hos_prompts_romfs(const char *key, char *out, size_t cap) {")
    check("hos_vcore_away" not in romfs, "the core is given up inside the builder, where its lock is held")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_OPEN_KEEP_CORE=1`" in dev, "docs/development.md: HOS_OPEN_KEEP_CORE=1 is not in the switches table")
    print("PASS: OpenFile gives its core up before the path is worked out and takes it back on every way out")


if __name__ == "__main__":
    main()
