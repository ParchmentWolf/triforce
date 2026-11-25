# SPDX-License-Identifier: GPL-3.0-or-later
"""A log line's level: none written for info, "[trace] " (and error, warn, debug) after the thread's tag for the rest.

A log viewer shows info and above unless asked for more and reads a line's level from that tag, so an info line must stay
exactly as it was (the log files, the bug report and the scripts that read them) and the others must carry it in the one
place it looks. Compiled from the real source:

- host/hos_thread.c hos_vlog and log_level_tag, with host/hos.h's levels: the line each level writes, the tag after
  "[hos <thread>] ", an info line as it was (and redacted as before: host/log_redact.h, stubbed here).
- gpu/vk/vk_main.cpp vlogf: the renderer's logf_at gives the host's log the same tag at the start of its text, and logf none.
- gpu/vk/vk_shader.cpp: a movie network left out on a card that cannot run it is a trace line, counted apart from the 30
  lines a program that failed to translate gets (on AMD the dozen networks took them all), and its summary line is trace too.

    python -I -B tests/test_log_levels.py --cxx clang++
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def block(text, marker):
    """The function or block that starts at marker, through its closing brace"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def statement(text, marker):
    """The declaration that starts at marker, through its semicolon"""
    start = text.index(marker)
    return text[start:text.index(";", start) + 1]


CODE = r"""
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
%(hos_enum)s
struct HosThread { const char* name; };
HosThread* cur;
std::string queued;
static int log_queue(const char* line) { queued = line; return 1; }
#define HOS_REPORT_DEVICE_LOST_PREFIX "vk: device lost"   // (host/hos_report_prefixes.h: no crash record here)
#define HOS_REPORT_FATAL_PREFIX "vk: FATAL"
static void hos_crash_record_fatal(const void*, const char*) {}
volatile int hos_control_on;   // (host/control.c: no control bridge here)
void hos_control_log(const char*) {}
static size_t hos_log_redact(char* out, size_t cap, const char* line) {   // (host/log_redact.h: nothing to leave out here)
    std::snprintf(out, cap, "%%s", line);
    const size_t n = std::strlen(line);
    return n < cap ? n : cap - 1;
}
%(tag)s
%(hos_vlog)s
void host_line(int level, const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    hos_vlog(level, fmt, ap);
    va_end(ap);
}
%(enum)s
std::string got;
struct Host { void (*log)(const char*); };
const Host the_host{[](const char* line) { got = line; }};
const Host* host = &the_host;
%(vlogf)s
%(logf)s
%(logf_at)s
int fails = 0;
void want(const std::string& a, const char* b, const char* what) {
    if (a != b) { std::printf("FAIL: %%s: \"%%s\", not \"%%s\"\n", what, a.c_str(), b); fails++; }
}
int main() {
    want(log_level_tag(HOS_LOG_INFO), "", "host: info has no tag");
    want(log_level_tag(HOS_LOG_ERROR), "[error] ", "host: error");
    want(log_level_tag(HOS_LOG_WARN), "[warn] ", "host: warn");
    want(log_level_tag(HOS_LOG_DEBUG), "[debug] ", "host: debug");
    want(log_level_tag(HOS_LOG_TRACE), "[trace] ", "host: trace");
    want(log_level_tag(42), "", "host: a level out of range is info");
    host_line(HOS_LOG_INFO, "vk: device %%d", 1);
    want(queued, "[hos host] vk: device 1\n", "host: an info line as it was");
    host_line(HOS_LOG_TRACE, "vk: program %%s", "x");
    want(queued, "[hos host] [trace] vk: program x\n", "host: trace after the thread's tag");
    HosThread main_thread{"Main"};
    cur = &main_thread;
    host_line(HOS_LOG_DEBUG, "codec: y");
    want(queued, "[hos Main] [debug] codec: y\n", "host: debug, on a named thread");
    cur = nullptr;
    logf("vk: device %%d", 1);
    want(got, "vk: device 1", "renderer: logf is info, untagged");
    logf_at(log_trace, "vk: program %%016llx not translated", 0x95fca6f01e3030aull);
    want(got, "[trace] vk: program 095fca6f01e3030a not translated", "renderer: trace");
    logf_at(log_debug, "x");
    want(got, "[debug] x", "renderer: debug");
    logf_at(log_info, "y");
    want(got, "y", "renderer: logf_at info is untagged");
    logf_at((LogLevel)42, "z");
    want(got, "z", "renderer: a level out of range is info");
    if (!fails) std::printf("PASS: the log's levels\n");
    return fails != 0;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default=os.environ.get("CXX", "clang++"))
    a = ap.parse_args()
    thread = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    vk_main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    internal = (ROOT / "gpu/vk/vk_internal.h").read_text(encoding="utf-8")
    shader = (ROOT / "gpu/vk/vk_shader.cpp").read_text(encoding="utf-8")
    hos_h = (ROOT / "host/hos.h").read_text(encoding="utf-8")
    code = CODE % {"hos_enum": statement(hos_h, "enum { HOS_LOG_ERROR"),
                   "tag": block(thread, "static const char *log_level_tag(int level) {"),
                   "hos_vlog": block(thread, "static void hos_vlog(int level, const char *fmt, va_list ap) {"),
                   "enum": statement(internal, "enum LogLevel"),
                   "vlogf": block(vk_main, "static void vlogf("),
                   "logf": block(vk_main, "void logf(const char* fmt, ...) {"),
                   "logf_at": block(vk_main, "void logf_at(LogLevel level, const char* fmt, ...) {")}
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp) / "levels.cpp", Path(tmp) / ("levels" + (".exe" if os.name == "nt" else ""))
        src.write_text(code, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-format-security",
                        "-D_CRT_SECURE_NO_WARNINGS", str(src), "-o", str(exe)], check=True, timeout=180)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        sys.stdout.write(r.stdout)
        if r.returncode:
            raise SystemExit("FAIL: the log's levels")
    # (the host's two callers write through hos_vlog, info and the level asked; HOS_TRACE's calls are trace)
    if "hos_vlog(HOS_LOG_INFO, fmt, ap);" not in block(thread, "void hos_log(const char *fmt, ...) {") or \
            "hos_vlog(level, fmt, ap);" not in block(thread, "void hos_log_at(int level, const char *fmt, ...) {"):
        raise SystemExit("FAIL: hos_log and hos_log_at do not write through hos_vlog")
    if "if (hos_trace) hos_log_at(HOS_LOG_TRACE," not in hos_h:
        raise SystemExit("FAIL: HOS_TRACE_CALL's lines are not trace")
    # (the shader's catch: the network left out is told apart from a failure, at trace, on a count of its own)
    catch = shader[shader.index("} catch (const std::exception& e) {", shader.index("throw std::runtime_error(kNetworkLeftOut);")):]
    catch = catch[:catch.index("st_translate_ns")]
    if "if (!trial && !strcmp(e.what(), kNetworkLeftOut)) {" not in catch or \
            "if (st_network_left_out++ < kFailNamed)\n                logf_at(log_trace," not in catch or \
            "} else if (!trial && st_not_translated++ < kFailNamed) {" not in catch:
        raise SystemExit("FAIL: a network left out is not a trace line counted apart")
    if 'constexpr char kNetworkLeftOut[] = "a network left out on this card";' not in shader or \
            shader.count('"a network left out on this card"') != 1:
        raise SystemExit("FAIL: the network left out is not thrown with the text the catch compares")
    fails = block(shader, "void shader_fail_lines() {")
    if 'line(", a network left out on this card", st_network_left_out.load(), log_trace);' not in fails or \
            'line("", st_not_translated.load(), log_info);' not in fails:
        raise SystemExit("FAIL: shader_fail_lines does not count the networks apart, at trace")
    print("PASS: a network left out is a trace line, counted apart from failures")


if __name__ == "__main__":
    main()
