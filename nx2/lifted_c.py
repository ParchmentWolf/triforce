"""Where the lifted functions begin in the lift's C (code_*.c): each definition is one line, `void f_<address>(Ctx *__restrict
A64_NOESC c) {`, its name in group 1. Small on purpose: nx2/build.py reads it for every compile, without the lifter.

HEAD                 the definitions alone (split_hot: a piece takes each function from its own line)
HEAD_NOTED           with the /* ... */ line the lift may put just above one (chunks: a part keeps a function's note with it)
HEAD_BYTES           HEAD, for bytes (build.py's memory estimate reads the files as they lie)

The lift writes its C with \n line ends; a file with \r\n ones (written in text mode on Windows) is read the same: none of the
patterns needs the end of the definition's line, and a note's line may end in \r\n.

(Triforce, 11-22, the performance audit's IO-40, after Source A's) The scans themselves, for the callers:

definitions(text)    HEAD's matches (HEAD_BYTES's for bytes), one after the other, as HEAD.finditer gives them
noted_starts(text)   where HEAD_NOTED's matches start, as [m.start() for m in HEAD_NOTED.finditer(text)]

A pattern that begins with ^ is tried by finditer at every line of 1.5 GB of C. These jump from one "\nvoid f_" to the
next with str.find and try the pattern only there: the same matches, far fewer tries (Source A: two scans over 1.56 GB in
1.49 s where they took 11.49 s). HOOKSHOT_LIFTED_C_REGEX=1 (read once): both are the patterns' own finditer, as before.
tests/test_lifted_c_scan.py holds them to the patterns.
"""
import os
import re

_DEF = r"void (f_[0-9a-f]+)\(Ctx \*__restrict A64_NOESC c\) \{"
HEAD = re.compile(r"^" + _DEF, re.M)
HEAD_NOTED = re.compile(r"^(?:/\* .* \*/\r?\n)?" + _DEF, re.M)
HEAD_BYTES = re.compile((r"^" + _DEF).encode(), re.M)

REGEX_SCAN = os.environ.get("HOOKSHOT_LIFTED_C_REGEX", "0") not in ("", "0")
_NOTE = re.compile(r"/\* .* \*/\r?\n")   # (HEAD_NOTED's optional first line, by itself)


def definitions(text):
    """Each definition in text (str or bytes), in order: the match HEAD (or HEAD_BYTES) has for it"""
    head, mark = (HEAD_BYTES, b"\nvoid f_") if isinstance(text, (bytes, bytearray, memoryview)) else (HEAD, "\nvoid f_")
    if REGEX_SCAN:
        yield from head.finditer(text)
        return
    # (^ is the start of the text or the place after a \n: the first line, then every "\nvoid f_". A definition is one
    # line and holds no "\n", so the next one is looked for from where this one's line began)
    at = 0
    while at >= 0:
        m = head.match(text, at)
        if m:
            yield m
        at = text.find(mark, at)
        if at >= 0:
            at += 1


def noted_starts(text):
    """Where each definition in text (str) starts, its note's line counted in when the line just above is one: the starts
    of HEAD_NOTED's matches, in order"""
    if REGEX_SCAN:
        for m in HEAD_NOTED.finditer(text):
            yield m.start()
        return
    # (HEAD_NOTED matches from the note's line when the line above the definition, whole, is "/* ... */" and its line
    # end; a match never reaches into the line after a definition's, so that line is free to be the next one's note)
    for m in definitions(text):
        start = m.start()
        if start:
            above = text.rfind("\n", 0, start - 1) + 1
            if _NOTE.fullmatch(text, above, start):
                start = above
        yield start
