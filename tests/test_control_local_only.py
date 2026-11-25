"""The control bridge (host/control.c) stays local, this user's alone, and off unless asked for: read from its source, as
other checks here read theirs, so a change that would open it up fails here and not in someone's hands.

  - off by default: hos_control_start returns at once without HOS_CONTROL; guest memory only with HOS_CONTROL_MEM (ro, rw),
    anything else leaving it off; the hooks in the game (nn_hid.c, hos_thread.c) return on hos_control_on;
  - no network: no TCP or UDP socket, no address of another PC (AF_INET, AF_INET6, getaddrinfo, WSAStartup, connect to a
    host), only a Unix socket (Linux) or a named pipe (Windows);
  - Windows: PIPE_REJECT_REMOTE_CLIENTS and FILE_FLAG_FIRST_PIPE_INSTANCE on every instance, a protected DACL that grants
    the current user (and the game's own AppContainer) and no one else;
  - Linux: the socket made 0600 with the umask around bind, its folder this user's and writable by no one else, and a
    client of another user turned away (SO_PEERCRED).

python -I -B tests/test_control_local_only.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS = []


def check(ok, what):
    if not ok:
        FAILS.append(what)
        print("FAIL: " + what)


def body(src, start):
    """the text of the C function whose definition starts with start, to its closing brace at column 0"""
    i = src.index(start)
    return src[i:src.index("\n}\n", i) + 2]


def main():
    src = (ROOT / "host" / "control.c").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)   # (the code alone: a comment may name what the code must not do)
    start = body(src, "void hos_control_start(const char *version) {")
    check('const char *path = getenv("HOS_CONTROL");\n    if (!path || !*path) return;' in start,
          "hos_control_start does not return at once without HOS_CONTROL")
    check(code.count("hos_control_on = 1") == 1 and "hos_control_on = 1;\n    return 1;\n}" in code,
          "hos_control_on is set elsewhere than at the end of a served hos_control_serve")
    check("if (!hos_control_on) return 0;" in body(src, "int hos_control_input(uint64_t *buttons, int32_t stick[4]) {"),
          "the controller's read hook does not return at once with the bridge off")
    check("if (!hos_control_on || !G.log_wanted) return;" in body(src, "void hos_control_log(const char *line) {"),
          "the log hook does not return at once with the bridge off")
    level = body(src, "int hos_control_mem_level(const char *v) {")
    check("if (!v || !*v) return 0;" in level and level.count("return 1;") == 1 and level.count("return 2;") == 1,
          "HOS_CONTROL_MEM: unset is not off, or more than ro and rw turn memory on")
    check('if (!G.mem_level)\n        return reply_error(c, id, "forbidden"' in body(src, "static void cmd_mem(") and
          "if (write && G.mem_level < 2)" in body(src, "static void cmd_mem("), "guest memory is served without HOS_CONTROL_MEM")
    for word in ("AF_INET", "AF_INET6", "getaddrinfo", "gethostbyname", "WSAStartup", "winsock", "SOCK_DGRAM", "inet_",
                 "htons", "InternetOpen", "WinHttp", "curl", "PEER_SID", "GRGW"):
        check(word not in code, "host/control.c names %s: the bridge must stay local and this user's" % word)
    check(code.count("socket(AF_UNIX") == 2, "a socket other than the Unix socket and its liveness probe")
    pipe = body(src, "static int pipe_listen(void) {")
    check("PIPE_REJECT_REMOTE_CLIENTS" in pipe and "FILE_FLAG_FIRST_PIPE_INSTANCE" in pipe and "&pipe_sa" in pipe,
          "a pipe instance without PIPE_REJECT_REMOTE_CLIENTS, the first-instance flag or the DACL")
    sec = body(src, "static int pipe_security(void) {")
    grants = re.findall(r'"(?:D:P)?\(A;;([A-Z]+);;;%s\)"', sec)
    check('"D:P(A;;GA;;;%s)", user' in sec and grants == ["GA", "GA"] and '"(A;;GA;;;%s)", ac' in sec and "getenv" not in sec,
          "the pipe's DACL grants someone other than this user and the game's own AppContainer")
    check("CreateNamedPipeA(" in code and code.count("CreateNamedPipe") == 1, "a pipe made outside pipe_listen")
    lin = body(src, "static int transport_open(const char *path) {")
    check("umask(077)" in lin and "chmod(path, 0600)" in lin and "folder_private(path)" in lin,
          "the Unix socket is not made 0600 in a private folder")
    check("SO_PEERCRED" in code and "cred.uid != getuid()" in code, "a client of another user is not turned away")
    return 1 if FAILS else 0


if __name__ == "__main__":
    rc = main()
    print("PASS: the control bridge is local, this user's alone, and off unless HOS_CONTROL is set" if not rc else
          "%d failed" % len(FAILS))
    sys.exit(rc)
