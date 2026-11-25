"""Retired capture buffers the spares cannot keep are destroyed on a thread of their own (gpu/vk/vk_memory.cpp cap_buf_free,
destroy_buffer_later, RX_VK_CAP_FREE_ASYNC).

take_capture retires old captures on the replay's thread with pools_mu held, and cap_buf_free destroyed each one past the
spares' limits right there, under cap_free_mu too: freeing a 64-256 MB host-cached buffer makes the driver unmap and release
every page. The code from cap_free_async_on to cap_buf_free and cap_exit_note is cut out unchanged and compiled with stand-ins
(a destroy_buffer that notes the thread and whether cap_free_mu is held, cap_free_mu as a mutex that knows its owner).
Checked: a spare is kept and not destroyed; one past the limits is destroyed once, on another thread, not under cap_free_mu;
RX_VK_CAP_FREE_ASYNC=0 (and off, no) destroys where it was retired, under the lock, as before; after cap_exit_note the thread
destroys nothing more; no thread to be had: destroyed inline after the lock; 4 threads retiring 400 buffers: each destroyed
exactly once; the 600-take line counts what was handed over, and the switch has its docs row.

    python -I -B tests/test_cap_free_async.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker, tail=""):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    if tail:
        end = text.index(tail, end) + len(tail)
    return text[start:end]


def fail(message):
    raise SystemExit("FAIL: " + message)


FIXTURE = r'''#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <system_error>
#include <thread>
#include <vector>
#include "cap_spare.h"   // (cap_buf_free asks its rules: MEM-33)

static void logf(const char*, ...) {}   // (the switches' log lines: not checked here)
#include "linux_pressure.h"   // (MEM-141's swap hold in cap_buf_free: off, as it always is on Windows)
static bool memory_swap_hold() { return false; }
static void memory_swap_valve(int, uint64_t) {}
typedef uint32_t VkBufferUsageFlags;   // (cap_buf_make, MEM-39, in the cut: never called here)
VkBufferUsageFlags cap_usage() { return 0; }
typedef struct VkBuffer_T* VkBuffer;
typedef struct VmaAllocation_T* VmaAllocation;
struct OwnedMutex {   // (cap_free_mu: knows which thread holds it)
    std::mutex m;
    std::atomic<std::thread::id> owner{};
    void lock() { m.lock(); owner = std::this_thread::get_id(); }
    void unlock() { owner = std::thread::id(); m.unlock(); }
    bool mine() const { return owner.load() == std::this_thread::get_id(); }
};
OwnedMutex cap_free_mu;
std::atomic<bool> cap_shutting_down{false};
uint64_t cap_free_bytes = 0;
uint64_t cap_spare_max() { return ~0ull; }
bool create_buffer_cached(uint64_t, VkBufferUsageFlags, VkBuffer&, VmaAllocation&, void**, bool) { return false; }
bool create_buffer_uncached(uint64_t, VkBufferUsageFlags, VkBuffer&, VmaAllocation&, void**, bool) { return false; }
struct Destroyed { uintptr_t id; std::thread::id by; bool under_free_mu; };
std::mutex dmu;
std::vector<Destroyed> destroyed;
void destroy_buffer(VkBuffer b, VmaAllocation) {
    std::lock_guard g(dmu);
    destroyed.push_back({(uintptr_t)b, std::this_thread::get_id(), cap_free_mu.mine()});
}
struct test_thread {   // (std::thread, or none to be had when TEST_NO_THREAD is set)
    template <class F> explicit test_thread(F f) {
        if (getenv("TEST_NO_THREAD")) throw std::system_error(std::make_error_code(std::errc::resource_unavailable_try_again));
        t = std::thread(f);
    }
    void detach() { t.detach(); }
    std::thread t;
};

@FREEBUF@
std::vector<FreeBuf> cap_free;
@ENVOFF@
@BLOCK@
@EXIT@

static VkBuffer buf(uintptr_t i) { return (VkBuffer)(i); }
static size_t count_of(uintptr_t id) {
    std::lock_guard g(dmu);
    size_t n = 0;
    for (auto& d : destroyed) n += d.id == id;
    return n;
}
static bool wait_for(uintptr_t id, size_t n = 1) {
    for (int i = 0; i < 2000; i++) {
        if (count_of(id) >= n) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    return false;
}
static void fill_spares() {   // (12 spares: the next one is past the limits)
    for (int i = 0; i < 12; i++) cap_buf_free(buf(1000 + i), nullptr, (void*)1, 1ull << 20);
}
static int bad(const char* why) { printf("BAD %s\n", why); return 1; }

int main(int argc, char** argv) {
    const std::string k = argc > 1 ? argv[1] : "";
    const auto me = std::this_thread::get_id();
    if (k == "keep") {
        cap_buf_free(buf(1), nullptr, (void*)1, 32ull << 20);
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        if (cap_free.size() != 1 || count_of(1)) return bad("a spare was not kept, or was destroyed");
    } else if (k == "past" || k == "nothread" || k == "off") {
        fill_spares();
        cap_buf_free(buf(7), nullptr, (void*)1, 32ull << 20);
        const size_t right_after = count_of(7);
        if (!wait_for(7)) return bad("never destroyed");
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        if (count_of(7) != 1) return bad("destroyed more than once");
        Destroyed d{};
        { std::lock_guard g(dmu); for (auto& x : destroyed) if (x.id == 7) d = x; }
        if (cap_free.size() != 12) return bad("the spares changed");
        if (k == "past") {
            if (right_after) return bad("destroyed inside cap_buf_free");
            if (d.by == me) return bad("destroyed on the retiring thread");
            if (d.under_free_mu) return bad("destroyed under cap_free_mu");
        } else if (k == "nothread") {
            if (d.by != me) return bad("no thread: not destroyed inline");
            if (d.under_free_mu) return bad("no thread: destroyed under cap_free_mu");
        } else {
            if (d.by != me || !d.under_free_mu) return bad("switched off: not destroyed under the lock as before");
        }
    } else if (k == "exit") {
        fill_spares();
        cap_buf_free(buf(7), nullptr, (void*)1, 32ull << 20);   // (the thread started)
        if (!wait_for(7)) return bad("never destroyed");
        cap_exit_note();
        destroy_buffer_later(buf(8), nullptr, 1ull << 20);   // (queued after the flag: the thread leaves it)
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        if (count_of(8)) return bad("destroyed after cap_exit_note");
        cap_buf_free(buf(9), nullptr, (void*)1, 32ull << 20, true);   // (a worker after the flag: nothing, as before)
        if (count_of(9) || cap_free.size() != 12) return bad("a worker's buffer touched after cap_exit_note");
    } else if (k == "many") {
        fill_spares();
        std::vector<std::thread> ts;
        for (int t = 0; t < 4; t++)
            ts.emplace_back([t] { for (int i = 0; i < 100; i++) cap_buf_free(buf(100000 + t * 1000 + i), nullptr, (void*)1, 64ull << 20); });
        for (auto& t : ts) t.join();
        for (int t = 0; t < 4; t++)
            for (int i = 0; i < 100; i++)
                if (!wait_for(100000 + t * 1000 + i) || count_of(100000 + t * 1000 + i) != 1) return bad("not destroyed exactly once");
        std::lock_guard g(dmu);
        for (auto& d : destroyed) if (d.under_free_mu) return bad("destroyed under cap_free_mu");
        if (cap_destroyed_later.load() != 400 || cap_destroyed_later_bytes.load() != 400ll * (64 << 20))
            return bad("the handed-over count is not 400 buffers of 64 MB");
    } else {
        return bad("no such case");
    }
    printf("OK %s\n", k.c_str());
    fflush(stdout);
    _Exit(0);   // (the detached thread is left, as at the process's exit)
}
'''


def fixture(mem):
    start = mem.index("bool cap_free_async_on() {")
    end_marker = "void cap_buf_free(VkBuffer buffer, VmaAllocation alloc, void* map, uint64_t size, bool from_worker = false) {"
    code = mem[start:mem.index(end_marker)] + block(mem, end_marker)
    code = code.replace("std::thread(", "test_thread(")
    if "test_thread(" not in code:
        raise ValueError("destroy_buffer_later starts no thread")
    return (FIXTURE.replace("@FREEBUF@", block(mem, "struct FreeBuf {", ";"))
            .replace("@ENVOFF@", block(mem, "bool env_value_off(const char* v) {") + "\n" + block(mem, "bool env_on(const char* name) {"))
            .replace("@BLOCK@", code).replace("@EXIT@", block(mem, "void cap_exit_note() {")))


def check_source(mem, dev):
    take = block(mem, "bool take_capture(")
    if "cap_buf_retire(oldest);" not in take:
        fail("take_capture no longer retires through cap_buf_retire")
    line = mem[mem.index("vk: a capture taken (ms): all"):]
    line = line[:line.index("logf(", 1) if "logf(" in line[1:] else len(line)]
    if "destroyed " not in line or "cap_destroyed_later.exchange(0" not in line or "cap_destroyed_later_bytes.exchange(0" not in line:
        fail("the 600-take line does not count the buffers handed to the destroying thread")
    if "`RX_VK_CAP_FREE_ASYNC=0`" not in dev:
        fail("docs/development.md has no RX_VK_CAP_FREE_ASYNC row")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    mem = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    try:
        text = fixture(mem)
        check_source(mem, dev)
    except ValueError as e:
        fail("a text this test reads moved, or is not there (%s)" % e)
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    problems = []
    with tempfile.TemporaryDirectory(prefix="cap-free-async-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(text, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-pthread", "-Wall", "-Wno-unused-function", "-I" + str(ROOT / "gpu" / "vk"), str(cpp), "-o", str(exe)],
                               capture_output=True, text=True, creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        base = {k: v for k, v in os.environ.items() if k not in ("RX_VK_CAP_FREE_ASYNC", "TEST_NO_THREAD", "RX_VK_CAPTURE_KEEP_OLD")}
        cases = [("keep", {}), ("past", {}), ("past", {"RX_VK_CAP_FREE_ASYNC": "1"}), ("off", {"RX_VK_CAP_FREE_ASYNC": "0"}),
                 ("off", {"RX_VK_CAP_FREE_ASYNC": "off"}), ("off", {"RX_VK_CAP_FREE_ASYNC": "No"}), ("exit", {}),
                 ("nothread", {"TEST_NO_THREAD": "1"}), ("many", {})]
        for case, extra in cases:
            done = subprocess.run([str(exe), case], env={**base, **extra}, capture_output=True, text=True, timeout=60,
                                  creationflags=flags)
            if done.returncode or done.stdout.strip() != "OK " + case:
                problems.append("%s %s: %s" % (case, extra, (done.stdout + done.stderr).strip()))
    if problems:
        fail("\n  ".join([""] + problems))
    print("PASS: retired capture buffers past the spares destroyed once on a thread of their own, not under cap_free_mu; "
          "=0 as before; nothing after the exit note; inline without a thread (%d cases)" % len(cases))


if __name__ == "__main__":
    main()
