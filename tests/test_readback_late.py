"""Late readbacks: ranges the CPU reads back without their write-back's wait (gpu/vk/readback_late.h; no game, no GPU).

(Triforce, 11-22, the performance audit's SYNC-19, after Source A's.) The replay's invalidate waits for the write-back of
every range the game is about to read back. Source A names ranges read without that wait, from what guest memory holds: a size
in hex (its default 3980, the culling camera block) or `newest` (the writer is the newest submission handed out).
RX_VK_READBACK_LATE=<rule>[,<rule>]; unset there is NO rule here and every readback waits as before, until the lab has run it.

Compiles a driver against the header and checks:
  the text      unset, empty and 0 give no rule; 3980 and 0x3980 the camera block's size; newest; several; a word, a size
                with a tail and a ninth size are left out and counted; a size named twice is one rule;
  the decision  with no rule, 200,000 random readbacks are never late (the default decides as before); with a rule a range
                is late only while its write-back is ahead of the GPU, by its size, or by `newest` only when its writer is
                at or past the newest value handed out;
  the range log counts by (address, size), sums a range's waits, keeps the rest together past its cap and lists the
                longest waits first.
And reads vk_replay.cpp's invalidate: the rule is asked with the write-back's value the readback came with, the GPU's
progress and the newest fence; a late range skips the catch-up and the wait and nothing else (its note for the CPU's
write-back stays, before the decision); nothing is noted for the range log without its switch; the lab knob gives the
default's rules only while the variable is unset; the switches table has the row.

    python -I -B tests/test_readback_late.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "readback_late.h"
#include <cstdio>

namespace rl = mkwvk::readback_late;
static int checks, fails;
#define CHECK(what, cond) do { checks++; if (!(cond)) fails++, printf("FAIL %s (line %d)\n", what, __LINE__); } while (0)

int main() {
    // the text
    CHECK("unset: no rule", !rl::parse(nullptr).any() && !rl::parse(nullptr).bad);
    CHECK("empty: no rule", !rl::parse("").any());
    CHECK("0: none", !rl::parse("0").any() && !rl::parse("0").bad);
    { const rl::Rules r = rl::parse("3980"); CHECK("3980", r.n == 1 && r.sizes[0] == 0x3980 && !r.newest && !r.bad); }
    { const rl::Rules r = rl::parse("0x3980"); CHECK("0x3980", r.n == 1 && r.sizes[0] == 0x3980 && !r.bad); }
    { const rl::Rules r = rl::parse("newest"); CHECK("newest", r.n == 0 && r.newest && r.any() && !r.bad); }
    { const rl::Rules r = rl::parse("3980,newest,1040"); CHECK("several", r.n == 2 && r.sizes[0] == 0x3980 && r.sizes[1] == 0x1040 && r.newest && !r.bad); }
    { const rl::Rules r = rl::parse("junk"); CHECK("a word: left out", !r.any() && r.bad == 1); }
    { const rl::Rules r = rl::parse("3980z,newest2,,40"); CHECK("tails", r.n == 1 && r.sizes[0] == 0x40 && !r.newest && r.bad == 2); }
    { const rl::Rules r = rl::parse("3980,3980,0x3980"); CHECK("named twice: one rule", r.n == 1 && !r.bad); }
    { const rl::Rules r = rl::parse("1,2,3,4,5,6,7,8,9,a"); CHECK("past the eighth size", r.n == rl::kMaxSizes && r.bad == 2 && !r.has(9) && r.has(8)); }
    { const rl::Rules r = rl::parse("123456789012345678901234567890"); CHECK("too long a part", !r.any() && r.bad == 1); }
    { const rl::Rules d = rl::default_rules(); CHECK("the default's rules", d.n == 1 && d.sizes[0] == rl::kCameraBlock && rl::kCameraBlock == 0x3980 && !d.newest); }

    // the decision
    uint64_t rng = 0x2545F4914F6CDD1Dull;
    const auto rnd = [&] { rng ^= rng << 13, rng ^= rng >> 7, rng ^= rng << 17; return rng; };
    const rl::Rules none = rl::parse(nullptr), zero = rl::parse("0"), cam = rl::parse("3980"), newest = rl::parse("newest"),
                    both = rl::parse("newest,3980");
    for (int i = 0; i < 200000; i++) {
        const uint64_t size = i % 5 == 0 ? 0x3980 : rnd() % 0x8000, done = rnd() % 1000, writer = rnd() % 1004, handed = done + rnd() % 6;
        const bool pending = writer > done, is_newest = writer >= handed;
        CHECK("no rule: never late", !rl::late(none, size, writer, done, handed) && !rl::late(zero, size, writer, done, handed));
        CHECK("by size", rl::late(cam, size, writer, done, handed) == (pending && size == 0x3980));
        CHECK("newest", rl::late(newest, size, writer, done, handed) == (pending && is_newest));
        CHECK("both", rl::late(both, size, writer, done, handed) == (pending && (is_newest || size == 0x3980)));
        if (fails) break;
    }
    CHECK("a write-back already done is never late", !rl::late(both, 0x3980, 7, 7, 7) && !rl::late(both, 0x3980, 6, 7, 7));
    CHECK("wanted: the size alone", rl::wanted(cam, 0x3980, false) && !rl::wanted(cam, 0x3981, true));
    CHECK("wanted: newest alone", rl::wanted(newest, 1, true) && !rl::wanted(newest, 0x3980, false));

    // the range log
    rl::RangeLog log;
    log.cap = 3;
    log.note(0x1000, 0x3980, true, 2000000, true, false);
    log.note(0x1000, 0x3980, false, 9000000, false, true);   // (not waited: its time is not a wait's)
    log.note(0x1000, 0x40, true, 500000, false, false);       // (the same address, another size: another range)
    log.note(0x9000, 0x1040, true, 7000000, true, false);
    log.note(0xA000, 0x10, true, 1, false, false);            // (past the cap: together)
    log.note(0xB000, 0x10, false, 1, true, true);
    log.note(0x9000, 0x1040, true, 1000000, false, false);    // (a range already in the table still counts under itself)
    CHECK("ranges", log.rows.size() == 3);
    { const auto& r = log.rows[{0x1000, 0x3980}]; CHECK("a range's counts", r.readbacks == 2 && r.waits == 1 && r.wait_ns == 2000000 && r.newest == 1 && r.late == 1); }
    CHECK("past the cap", log.other.readbacks == 2 && log.other.waits == 1 && log.other.wait_ns == 1 && log.other.newest == 1 && log.other.late == 1);
    { const auto top = log.top(2);
      CHECK("the longest waits first", top.size() == 2 && top[0].gpu == 0x9000 && top[0].size == 0x1040 && top[0].row.wait_ns == 8000000 &&
                                           top[1].gpu == 0x1000 && top[1].size == 0x3980); }
    CHECK("top of more than there are", log.top(50).size() == 3);

    if (fails) printf("late readbacks: FAILED (%d of %d checks)\n", fails, checks);
    else printf("late readbacks: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def function(text, head):
    at = text.index(head)
    return text[at:text.index("\n}\n", at)]


def check_source():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    check('#include "readback_late.h"' in replay, "vk_replay.cpp does not include readback_late.h")
    rules = function(replay, "const readback_late::Rules& rb_late_rules() {")
    check('const char* e = getenv("RX_VK_READBACK_LATE");' in rules and "readback_late::parse(e);" in rules and "static const" in rules,
          "RX_VK_READBACK_LATE is not parsed once by the header")
    late = function(replay, "bool rb_late(uint64_t size, uint64_t writer, uint64_t done, uint64_t handed_out) {")
    check("if (r.any()) return readback_late::late(r, size, writer, done, handed_out);" in late,
          "the variable's rules do not decide through the header")
    # (the knob gives the default's rules only while the variable is unset; with neither, never late)
    check('if (!unset || !lab_ab::on("rblate")) return false;' in late and
          late.index('if (!unset || !lab_ab::on("rblate")) return false;') < late.index("readback_late::default_rules();"),
          "the lab knob's rules are not kept to an unset variable, or something is late with no rule and no knob")
    check(late.count("return ") == 3, "rb_late has another way to say late")

    inv = function(replay, "void invalidate(uint64_t gpu, uint64_t size) {")
    note = "memory_note_readback(host->gpu_guest(gpu), size);"
    ask = "const bool is_late = rb_late(size, v0, c0, f0);"
    check("if (!off && (v0 = memory_writeback_value(host->gpu_guest(gpu), size, &ever), ever)) {" in inv,
          "the write-back's value the readback came with is not kept for the rule")
    check("const uint64_t f0 = fence(), c0 = completed();" in inv, "the newest fence and the GPU's progress are not read")
    check(inv.count(ask) == 1 and inv.index(note) < inv.index("const uint64_t f0 = fence(), c0 = completed();") < inv.index(ask),
          "the rule is not asked once, after the note for the CPU's write-back")
    # (a late range skips the catch-up: the first branch of the chain the two catch-ups are in)
    chain = inv[inv.index(ask):inv.index("const auto w1 = std::chrono::steady_clock::now();")]
    check("if (is_late) lates.fetch_add(1, std::memory_order_relaxed);\n"
          "            else if (behind0 && !no_catchup && !unforced) wait_queue_empty(), w = true;" in chain and
          "            else if (behind0 && !no_catchup && !async_on() && rb_fix(2)) sync_settle_at(settle_gate::kReadback), w = true;" in chain,
          "a late range does not skip the catch-up, or the catch-ups are no longer the rest of its chain")
    check(chain.count("wait_queue_empty()") == 1 and chain.count("sync_settle_at(") == 1 and "sync_settle()" not in chain.replace("sync_settle() as it was", ""), "another catch-up crept in beside the chain")
    # (and the wait: every wait for the write-back's value is inside the block a late range does not enter)
    check(inv.count("if (!is_late && v > completed()) {") == 1 and "if (v > completed()) {" not in inv, "a late range does not skip the wait")
    block = inv[inv.index("if (!is_late && v > completed()) {"):inv.index("if (w) {")]
    rest = inv.replace(block, "")
    for call in ("wait_recorded(", "wait_value(", "readback_fallback_wait("):
        check(call in block and call not in rest[rest.index(ask):rest.index("// (textures the GPU wrote there")],
              "invalidate waits for the write-back outside the block a late range skips (%s)" % call)
    # (nothing else changes for a late range: is_late is read in these places only)
    check(inv.count("is_late") == 4 and "rb_ranges.note(gpu, size, w, d, v0 >= f0, is_late);" in inv,
          "is_late decides something besides the catch-up, the wait and the range log's count")
    # (the range log: nothing noted or logged without its switch)
    check("if (rb_ranges_on()) {" in inv and inv.index("if (rb_ranges_on()) {") < inv.index("rb_ranges.note(") and
          replay.count("rb_ranges.note(") == 1, "the range log notes a readback without its switch")
    check("if (rb_ranges_on()) rb_ranges_line();" in inv and replay.count("rb_ranges_line();") == 1, "the range log's lines are logged without its switch")
    on = function(replay, "bool rb_ranges_on() {")
    check('getenv("RX_VK_LOG_READBACK_RANGES") && atoi(getenv("RX_VK_LOG_READBACK_RANGES")) != 0' in on, "RX_VK_LOG_READBACK_RANGES is not read")

    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    row = [line for line in dev.splitlines() if line.startswith("| `RX_VK_READBACK_LATE=<rule>[,<rule>]`, `RX_VK_LOG_READBACK_RANGES=1` |")]
    check(len(row) == 1 and "**Unset: no rule**" in row[0] and "`rblate`" in row[0] and "`newest`" in row[0],
          "docs/development.md: the switches table does not have RX_VK_READBACK_LATE's row with its default")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="readback-late-") as tmp:
        src = Path(tmp) / "driver.cpp"
        src.write_text(DRIVER, encoding="utf-8")
        exe = Path(tmp) / "driver.exe"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu/vk"), str(src), "-o", str(exe)],
                       check=True)
        out = subprocess.run([str(exe)], capture_output=True, text=True)
        print(out.stdout, end="")
        check(out.returncode == 0, "the header's checks failed")
    print("PASS: late readbacks: no rule unless asked, the catch-up and the wait skipped for a named range only")


if __name__ == "__main__":
    main()
