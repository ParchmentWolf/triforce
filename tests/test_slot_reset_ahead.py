"""A recording slot's descriptor pools are reset before the recording's first packet (gpu/vk/vk_draw.cpp
slot_reset_locked, draw_slot_reset, draw_begin_recording; vk_replay.cpp begin_recording; no game, no GPU).

(Triforce, 11-21, the performance audit's REPLAY-04, after Source A's.) With the recorder thread a descriptor pool's
reset, a pool's destruction and a buffer's are boundaries: the replay waits there until the recorder has run every packet
before them. Made in draw_begin_recording, they came after the recording's first packets, so every recording began with
a wait.

Reads the source for the order: begin_recording resets the slot right after its two command pool resets and before its
command buffers are begun and anything is recorded into them; draw_slot_reset makes the reset only for a slot that has a
pool, under ParLock, and marks it; draw_begin_recording makes a new slot's pool, skips a reset already made (and clears
the mark), and otherwise resets as before, so a helper thread's segment, which never comes through begin_recording,
still resets its slot; one function holds the reset itself; the switch turns the early reset off.

And runs a model of a slot through recordings: with the reset ahead each recording resets its pool exactly once, before
its first packet; a segment's slot once, in draw_begin_recording; with the switch off once, after the packets.

    python -I -B tests/test_slot_reset_ahead.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


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


# The same order as the source, with the calls written down as they happen
MODEL = r"""
#include <cstdio>
#include <string>
#include <vector>
struct Res { bool pool = false, reset_ahead = false; };
static std::vector<Res> res;
static std::string seen;
static bool own_on = true;
static void slot_reset_locked(Res&) { seen += "R"; }
static void draw_slot_reset(int slot) {
    if (!own_on) return;
    if ((size_t)slot >= res.size()) return;
    Res& r = res[slot];
    if (!r.pool) return;
    slot_reset_locked(r);
    r.reset_ahead = true;
}
static void draw_begin_recording(int slot) {
    if ((size_t)slot >= res.size()) res.resize((size_t)slot + 1);
    Res& r = res[slot];
    if (!r.pool) r.pool = true, seen += "M";
    else if (r.reset_ahead) r.reset_ahead = false;
    else slot_reset_locked(r);
}
static void begin_recording(int slot) {
    seen += "c";            // the command pools' resets
    draw_slot_reset(slot);
    seen += "p";            // the recording's first packets
    draw_begin_recording(slot);
    seen += ".";
}
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s (%s)\n", __LINE__, #x, seen.c_str()); fails++; } } while (0)
int main() {
    begin_recording(0), begin_recording(0), begin_recording(0);
    CHECK(seen == "cpM.cRp.cRp.");                 // (a new slot's pool made; then each reset once, before the packets)
    seen.clear();
    draw_begin_recording(1), draw_begin_recording(1);   // (a helper thread's segment: never through begin_recording)
    CHECK(seen == "MR");
    seen.clear();
    begin_recording(1);                            // (the same slot later used by the replay thread itself)
    CHECK(seen == "cRp." && !res[1].reset_ahead);
    seen.clear();
    own_on = false;
    begin_recording(0), begin_recording(0);
    CHECK(seen == "cpR.cpR.");                     // (the switch: after the packets, as before)
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")

    reset = block(draw, "void slot_reset_locked(RecordingRes& r) {")
    check("vkResetDescriptorPool(dev.device, r.pool, 0);" in reset and "vkDestroyDescriptorPool(dev.device, p, nullptr);" in reset and
          "destroy_buffer(r.streams[i].buffer, r.streams[i].alloc);" in reset, "the slot's reset is not all in one function")
    check(draw.count("vkResetDescriptorPool(dev.device, r.pool, 0);") == 1, "a slot's pool is reset in a place this test does not know")
    ahead = block(draw, "void draw_slot_reset(int slot) {")
    at = [ahead.index(p) for p in ("if (!on) return;", "ParLock lk;", "if ((size_t)slot >= res.size()) return;", "if (!r.pool) return;",
                                   "slot_reset_locked(r);", "r.reset_ahead = true;")]
    check(at == sorted(at), "draw_slot_reset does not reset only a slot that has a pool, under ParLock, and mark it")
    check('getenv("RX_VK_RECORDER_OWN") && atoi(getenv("RX_VK_RECORDER_OWN")) == 0' in ahead, "the switch is not RX_VK_RECORDER_OWN")
    begin = block(draw, "void draw_begin_recording(int slot, VkCommandBuffer cmd, uint64_t value) {")
    at = [begin.index(p) for p in ("if (!r.pool) {", "r.pool = make_pool(r.shift);", "} else if (r.reset_ahead) {", "r.reset_ahead = false;",
                                   "} else {", "slot_reset_locked(r);")]
    check(at == sorted(at), "draw_begin_recording does not skip a reset already made, or no longer resets a slot that did not have one")
    rec = block(replay, "Recording& begin_recording(uint64_t value) {")
    at = [rec.index(p) for p in ("vkResetCommandPool(dev.device, r.pool, 0);", "vkResetCommandPool(dev.device, r.upload_pool, 0);",
                                 "draw_slot_reset(r.slot);", "vkBeginCommandBuffer(r.cmd, &bi);", "occ_slot_begin(r);", "gpu_time_begin(r);",
                                 "draw_begin_recording(r.slot, r.cmd, value);")]
    check(at == sorted(at), "the slot is not reset right after its command pools' resets and before the recording's first packet")
    check(replay.count("draw_slot_reset(") == 1, "a segment's start, or another place, resets a slot ahead")
    check("void draw_slot_reset(int slot);" in (VK / "vk_draw.h").read_text(encoding="utf-8"), "vk_draw.h does not declare it")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_RECORDER_OWN=0`" in dev, "docs/development.md: RX_VK_RECORDER_OWN=0 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="slot-reset-") as tmp:
        c, exe = Path(tmp) / "model.cpp", Path(tmp) / "model.exe"
        c.write_text(MODEL, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the order's model:\n" + r.stdout)
    print("PASS: a recording slot's descriptor pools are reset before the recording's first packet, once a recording")


if __name__ == "__main__":
    main()
