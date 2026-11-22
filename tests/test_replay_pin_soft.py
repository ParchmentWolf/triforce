"""A replay's pin is soft where the cores are of more than one kind (gpu/vk/replay_pin.h, vk_replay.cpp ReplayPin; no game, no GPU,
no processor of the kind).

(Triforce, 11-22, the performance audit's THREAD-09, after Source A's.) A thread that replays is pinned to the core the host keeps
for the replay, and that core is kept from the game's threads only: another program's thread on it holds the pinned replay up. On
a processor of two kinds of core the pin lets the thread also run on the fastest-kind cores among its own processors, with the
reserved core as its ideal processor, and leaves out the core it is on so that it moves at once.

Three parts:

- the rule, replay_pin.h, compiled and run over made-up processors, with the reserved core chosen by the host's own
  pick_reserved_core cut out of host/hos_thread.c: a 6+8-core hybrid (reserved 0xc00, from core 0: 0xffc), an 8+4 one, a 12-core
  and an 8-core 16-thread processor of one kind (this PC's kind: strict, the reserved core alone, exactly as before), a two-die
  X3D (soft only with the switch at 2, and then inside its die), a laptop's 2+8 (no core reserved: no pin), a thread held to the
  small cores, a thread on the reserved core already; the switch's values;
- vk_replay.cpp's ReplayPin, cut out and run over a stand-in thread that behaves as Windows' does (a thread whose processor is
  no longer allowed moves, to its ideal processor when that is allowed and free; an ideal processor outside a new affinity is
  replaced): the widening, the ideal processor, the move, pins inside a pin, and everything given back in the order that works.
  Each step taken out or reordered (a mutation of the cut code) must make a check fail;
- on Windows, the code that reads the processor (replay_pin_cpu and the four small calls) compiled against Windows itself and
  run on this PC: what it reads agrees with itself, whatever the processor.

    python -I -B tests/test_replay_pin_soft.py [--cxx clang++]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


RULE_TEST = r'''
#include <cstdint>
#include <cstdio>
#include "replay_pin.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace mkwvk::replay_pin;
/* PICK */
static uint64_t masks[256];
static unsigned char classes[256];
static int n;
static void fresh() { n = 0; }
// count cores of `per` logical processors each from logical processor `first`, of one efficiency class
static void add(int count, int per, int first, unsigned char cls) {
    for (int i = 0; i < count; i++) masks[n] = ((1ull << per) - 1) << (first + i * per), classes[n++] = cls;
}
// what a pin sets for a thread with affinity `own` on logical processor `lp`: the mask it ends with
static uint64_t pinned(int mode_, uint64_t reserved, uint64_t own, int lp) {
    const Kinds k = kinds(masks, classes, n);
    if (!reserved) return 0;   // (no core reserved: no pin at all)
    if (!soft(mode_, k.hybrid)) return reserved;
    uint64_t core = 0;
    for (int i = 0; i < n; i++) if (masks[i] >> lp & 1) core = masks[i];
    return moved(wide(reserved, k.fastest, own), reserved, core);
}
int main() {
    // the switch
    CHECK(mode(nullptr) == kHybrid && mode("") == kHybrid && mode("1") == kHybrid);
    CHECK(mode("0") == kStrict && mode("-1") == kStrict && mode("off") == kStrict);
    CHECK(mode("2") == kAlways && mode("3") == kAlways);
    CHECK(soft(kHybrid, true) && !soft(kHybrid, false) && !soft(kStrict, true) && !soft(kStrict, false));
    CHECK(soft(kAlways, false) && soft(kAlways, true));

    // a 6+8-core hybrid: 6 performance cores of 2 logical processors (0-11), 8 efficiency cores (12-19)
    fresh(), add(6, 2, 0, 1), add(8, 1, 12, 0);
    {
        const Kinds k = kinds(masks, classes, n);
        const uint64_t reserved = pick_reserved_core(masks, classes, n), all = 0xfffff, own = all & ~reserved;
        CHECK(k.hybrid && k.fastest == 0xfff && reserved == 0xc00);
        CHECK((reserved & k.fastest) == reserved);            // (the reserved core is one of the fastest kind)
        CHECK(wide(reserved, k.fastest, own) == 0xfff);
        CHECK(pinned(kHybrid, reserved, own, 0) == 0xffc);    // (from core 0: every performance core but that one)
        CHECK(pinned(kHybrid, reserved, own, 1) == 0xffc);    // (core 0's other logical processor: the same core)
        CHECK(pinned(kHybrid, reserved, own, 5) == 0xfcf);
        CHECK(pinned(kHybrid, reserved, own, 14) == 0xfff);   // (from an efficiency core: it is outside already, nothing to leave out)
        CHECK(pinned(kHybrid, reserved, all, 10) == 0xfff);   // (on the reserved core already: it stays, nothing left out)
        CHECK(pinned(kStrict, reserved, own, 0) == 0xc00);    // (=0: the reserved core alone, as before)
        CHECK(pinned(kAlways, reserved, own, 0) == 0xffc);
        CHECK(ideal(reserved) == 11);                         // (the reserved core's last logical processor)
        // a thread held to the efficiency cores (HOS_PIN): nothing of its own is of the fastest kind, so the reserved core alone
        CHECK(pinned(kHybrid, reserved, 0xff000, 13) == 0xc00);
        // a thread held to two performance cores: those and the reserved one, never more than it had beside it
        CHECK(pinned(kHybrid, reserved, 0x0f, 0) == 0xc0c);
    }
    // an 8+4-core hybrid: 8 performance cores (0-15), 4 efficiency cores (16-19)
    fresh(), add(8, 2, 0, 1), add(4, 1, 16, 0);
    {
        const Kinds k = kinds(masks, classes, n);
        const uint64_t reserved = pick_reserved_core(masks, classes, n);
        CHECK(k.hybrid && k.fastest == 0xffff && reserved == 0xc000 && ideal(reserved) == 15);
        CHECK(pinned(kHybrid, reserved, 0xfffff & ~reserved, 6) == 0xff3f);
    }
    // one kind of core, 12 cores with SMT: the strict pin, whatever the thread is on
    fresh(), add(12, 2, 0, 0);
    {
        const Kinds k = kinds(masks, classes, n);
        const uint64_t reserved = pick_reserved_core(masks, classes, n);
        CHECK(!k.hybrid && k.fastest == 0xffffff && reserved == 0xc00000);
        for (int lp = 0; lp < 24; lp++) CHECK(pinned(kHybrid, reserved, 0xffffff & ~reserved, lp) == 0xc00000);
        CHECK(pinned(kStrict, reserved, 0x3fffff, 0) == 0xc00000);
        CHECK(pinned(kAlways, reserved, 0x3fffff, 0) == 0xfffffc);   // (the lab's 2: soft there too)
    }
    // this PC's kind: 8 cores, 16 logical processors, one kind, one cache domain: nothing may change
    fresh(), add(8, 2, 0, 0);
    {
        const Kinds k = kinds(masks, classes, n);
        const uint64_t reserved = pick_reserved_core(masks, classes, n);
        CHECK(!k.hybrid && k.fastest == 0xffff && reserved == 0xc000);
        for (int lp = 0; lp < 16; lp++) {
            CHECK(pinned(kHybrid, reserved, 0x3fff, lp) == 0xc000);   // (unset and 1)
            CHECK(pinned(kStrict, reserved, 0x3fff, lp) == 0xc000);
        }
        CHECK(!soft(mode(nullptr), k.hybrid) && !soft(mode("1"), k.hybrid) && !soft(mode("0"), k.hybrid));
    }
    // the same core class reported as a non-zero number (some processors of one kind do): still one kind
    fresh(), add(8, 2, 0, 3);
    CHECK(!kinds(masks, classes, n).hybrid && kinds(masks, classes, n).fastest == 0xffff);
    // a two-die X3D, 16 cores with SMT: one kind, so strict; with the switch at 2 a game thread, which the host holds to the
    // cache die (logical processors 0-15) without the reserved core, stays on that die
    fresh(), add(16, 2, 0, 0);
    {
        const uint64_t die = 0xffff, reserved = 0xc000, own = die & ~reserved;
        CHECK(!kinds(masks, classes, n).hybrid);
        CHECK(pinned(kHybrid, reserved, own, 2) == reserved);
        CHECK(pinned(kAlways, reserved, own, 2) == 0xfff3);
        CHECK((pinned(kAlways, reserved, own, 2) & ~die) == 0);
    }
    // a laptop's 2 performance and 8 efficiency cores: the host keeps no core (fewer than 4 of the fastest kind), so no pin
    fresh(), add(2, 2, 0, 1), add(8, 1, 4, 0);
    {
        const uint64_t reserved = pick_reserved_core(masks, classes, n);
        CHECK(kinds(masks, classes, n).hybrid && reserved == 0 && pinned(kHybrid, reserved, 0xfff, 0) == 0 && ideal(reserved) == -1);
    }
    // three kinds of core: only the highest class is the fastest; a core with no processors is not one
    fresh(), add(2, 1, 0, 2), add(4, 1, 2, 1), add(4, 1, 6, 0);
    masks[n] = 0, classes[n++] = 9;
    CHECK(kinds(masks, classes, n).hybrid && kinds(masks, classes, n).fastest == 0x3);
    // nothing listed (the cores could not be read): no fastest kind, not hybrid, and a pin stays strict
    fresh();
    CHECK(!kinds(masks, classes, n).hybrid && kinds(masks, classes, n).fastest == 0);
    // moved: the processor not known, or nothing else left: whole
    CHECK(moved(0xfff, 0xc00, 0) == 0xfff && moved(0x3, 0, 0x3) == 0x3 && moved(0xc03, 0xc00, 0x3) == 0xc00);
    if (!fails) std::printf("PASS: the soft pin's rule over made-up processors\n");
    return fails ? 1 : 0;
}
'''

PIN_TEST = r'''
#include <cstdint>
#include <cstdio>
#include "replay_prio.h"
#include "replay_pin.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
typedef uintptr_t DWORD_PTR;
typedef void* HANDLE;
namespace mkwvk {
// One thread as Windows keeps it: its affinity, its ideal processor, the logical processor it is on; and the processors another
// program holds (busy). A thread whose processor is no longer allowed moves at once: to its ideal processor when that is allowed
// and free, else to the lowest free allowed one. An ideal processor outside a new affinity is replaced by one inside it.
uint64_t affinity, busy, reserved_mask, fast_mask, core_of[64];
int ideal, cur, aff_sets, ideal_sets, ideal_reads, prio;
bool refuse_aff, refuse_ideal, async;
void place() {
    if (affinity >> cur & 1) return;
    if ((affinity >> ideal & 1) && !(busy >> ideal & 1)) { cur = ideal; return; }
    for (int i = 0; i < 64; i++) if ((affinity >> i & 1) && !(busy >> i & 1)) { cur = i; return; }
    cur = __builtin_ctzll(affinity);
}
HANDLE GetCurrentThread() { return (HANDLE)1; }
DWORD_PTR SetThreadAffinityMask(HANDLE, DWORD_PTR m) {
    aff_sets++;
    if (refuse_aff || !m) return 0;
    const DWORD_PTR was = affinity;
    affinity = m;
    if (!(affinity >> ideal & 1)) ideal = __builtin_ctzll(affinity);
    place();
    return was;
}
int GetThreadPriority(HANDLE) { return prio; }
int SetThreadPriority(HANDLE, int p) { prio = p; return 1; }
bool async_on() { return async; }
uint64_t replay_pin_mask() { return reserved_mask; }
int replay_prio_level() { return 2; }
uint64_t replay_pin_soft(bool = true) { return fast_mask; }
uint64_t replay_pin_own() { return affinity; }
uint64_t replay_pin_core_now() { return core_of[cur]; }
int replay_pin_ideal_now() { ideal_reads++; return ideal; }
bool replay_pin_set_ideal(int lp) {
    ideal_sets++;
    if (refuse_ideal || lp < 0 || !(affinity >> lp & 1)) return false;   // (Windows takes an ideal processor only among the thread's own)
    ideal = lp;
    return true;
}
/* PIN */
} // namespace mkwvk
using namespace mkwvk;
// the 6+8-core hybrid: a game thread on every processor but the reserved core's, its ideal processor an efficiency core
void hybrid(int on, int ideal_was) {
    for (int lp = 0; lp < 12; lp++) core_of[lp] = 3ull << (lp & ~1);
    for (int lp = 12; lp < 20; lp++) core_of[lp] = 1ull << lp;
    reserved_mask = 0xc00, fast_mask = 0xfff, affinity = 0xff3ff, busy = 0, ideal = ideal_was, cur = on;
    aff_sets = ideal_sets = ideal_reads = 0, prio = 0, refuse_aff = refuse_ideal = async = false;
}
int main() {
    hybrid(0, 13);   // (on core 0, the reserved core free: widened, the ideal processor set, and moved there at once)
    {
        ReplayPin outer;
        CHECK(affinity == 0xffc && ideal == 11 && cur == 11 && aff_sets == 2 && ideal_sets == 1 && prio == 2);
        {
            ReplayPin inner;   // (a pin inside a pin sets nothing)
            CHECK(affinity == 0xffc && ideal == 11 && cur == 11 && aff_sets == 2 && ideal_sets == 1 && ideal_reads == 1);
        }
        CHECK(affinity == 0xffc && ideal == 11 && aff_sets == 2 && ideal_sets == 1);   // (still replaying)
    }
    CHECK(affinity == 0xff3ff && ideal == 13 && prio == 0 && aff_sets == 3 && ideal_sets == 2);   // (all of it back)
    CHECK(affinity >> cur & 1);   // (and it is on one of its own processors again)

    hybrid(0, 13), busy = 0xc00;   // (another program holds the reserved core: the replay runs on another fast core, not core 0)
    {
        ReplayPin p;
        CHECK(affinity == 0xffc && ideal == 11 && cur == 2);
        CHECK((1ull << cur & fast_mask) && !(1ull << cur & reserved_mask));
    }
    CHECK(affinity == 0xff3ff && ideal == 13);

    hybrid(14, 13);   // (on an efficiency core: the widening itself moves it to a fast core, and the pin on to the reserved one)
    {
        ReplayPin p;
        CHECK((affinity & reserved_mask) == reserved_mask && !(affinity & ~fast_mask) && cur == 11 && ideal == 11);
    }
    CHECK(affinity == 0xff3ff && ideal == 13);

    hybrid(0, 4), affinity = 0xfffff, cur = 10;   // (a thread already on the reserved core: it stays)
    {
        ReplayPin p;
        CHECK(affinity == 0xfff && cur == 10 && ideal == 11 && aff_sets == 1);
    }
    CHECK(affinity == 0xfffff && ideal == 4);

    hybrid(0, 13), fast_mask = 0;   // (strict: a processor of one kind, or the switch at 0: the reserved core alone, one call each way)
    {
        ReplayPin p;
        CHECK(affinity == 0xc00 && aff_sets == 1 && ideal_sets == 0 && ideal_reads == 0);
        CHECK(cur == 10 || cur == 11);
    }
    CHECK(affinity == 0xff3ff && aff_sets == 2 && ideal_sets == 0);

    hybrid(0, 13), reserved_mask = 0;   // (no core reserved: nothing)
    { ReplayPin p; CHECK(prio == 2); }
    CHECK(affinity == 0xff3ff && aff_sets == 0 && ideal_sets == 0 && ideal_reads == 0 && cur == 0);

    hybrid(0, 13), async = true;   // (the replay on its own thread: the pin does nothing)
    { ReplayPin p; }
    CHECK(affinity == 0xff3ff && aff_sets == 0 && ideal_sets == 0 && cur == 0);

    hybrid(0, 13), refuse_aff = true;   // (Windows refused the widening: nothing else is set, nothing given back)
    { ReplayPin p; CHECK(aff_sets == 1 && ideal_sets == 0); }
    CHECK(affinity == 0xff3ff && ideal == 13 && aff_sets == 1 && ideal_sets == 0);

    hybrid(0, 13), refuse_ideal = true;   // (Windows refused the ideal processor: the thread still moves; no ideal given back)
    {
        ReplayPin p;
        CHECK(affinity == 0xffc && cur != 0 && ideal_sets == 1);
    }
    CHECK(affinity == 0xff3ff && ideal_sets == 1);

    hybrid(0, 13);
    for (int i = 0; i < 3; i++) { ReplayPin p; CHECK(cur == 11); }   // (pin after pin)
    CHECK(affinity == 0xff3ff && ideal == 13 && aff_sets == 9 && ideal_sets == 6);
    if (!fails) std::printf("PASS: ReplayPin widens, prefers the reserved core, moves the thread and gives everything back\n");
    return fails ? 1 : 0;
}
'''

# (each: what is taken out or reordered, the text in the cut ReplayPin, what replaces it)
RESTORE_AFF = "        if (replay_pin_prev) SetThreadAffinityMask(GetCurrentThread(), replay_pin_prev), replay_pin_prev = 0;\n"
RESTORE_IDEAL = "        if (replay_pin_ideal_prev != kIdealNone) replay_pin_set_ideal(replay_pin_ideal_prev), replay_pin_ideal_prev = kIdealNone;\n"
WIDEN = "                if ((replay_pin_prev = SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)wide))) {\n"
READ = "                const int ideal = replay_pin_ideal_now();\n"
MUTATIONS = [
    ("the move off the core it is on", "if (moved != wide) SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)moved);", ""),
    ("the reserved core as the ideal processor",
     "if (ideal >= 0 && replay_pin_set_ideal(replay_pin::ideal(m))) replay_pin_ideal_prev = ideal;", ""),
    ("the old ideal processor read before the widening", READ + WIDEN, WIDEN + READ),
    ("the ideal processor given back", RESTORE_IDEAL, ""),
    ("the affinity given back before the ideal processor", None, None),
    ("the strict pin where the rule says so", "const uint64_t fast = replay_pin_soft(), own = fast ? replay_pin_own() : 0;",
     "const uint64_t fast = 0xfff, own = replay_pin_own();"),
    ("only the outermost pin", "if (replay_pin_depth++) return;", "replay_pin_depth++;"),
    ("nothing more after a refused widening", WIDEN,
     "                replay_pin_prev = SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)wide); {\n"),
    ("no ideal processor given back for a refused one",
     "if (ideal >= 0 && replay_pin_set_ideal(replay_pin::ideal(m))) replay_pin_ideal_prev = ideal;",
     "if (ideal >= 0) replay_pin_set_ideal(replay_pin::ideal(m)), replay_pin_ideal_prev = ideal;"),
]

CPU_TEST = r'''
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include "replay_pin.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
namespace mkwvk {
/* CPU */
} // namespace mkwvk
using namespace mkwvk;
int main() {
    const ReplayPinCpu& c = replay_pin_cpu();
    DWORD_PTR proc = 0, sys = 0;
    GetProcessAffinityMask(GetCurrentProcess(), &proc, &sys);
    CHECK(c.kinds.fastest != 0);                             // (the cores were read)
    CHECK((c.kinds.fastest & ~(uint64_t)sys) == 0);           // (and are this PC's)
    uint64_t all = 0;
    for (int lp = 0; lp < 64; lp++) {
        if (!c.core_of[lp]) continue;
        all |= 1ull << lp;
        CHECK(c.core_of[lp] >> lp & 1);                      // (a logical processor is on its own core)
        for (int o = 0; o < 64; o++)
            if (c.core_of[lp] >> o & 1) CHECK(c.core_of[o] == c.core_of[lp]);   // (and its siblings name the same core)
    }
    CHECK(all == (uint64_t)sys);
    CHECK(c.kinds.hybrid == (c.kinds.fastest != all));
    const uint64_t own = replay_pin_own();
    CHECK(own == (uint64_t)proc);                            // (a thread nobody pinned: the process's processors)
    const uint64_t now = replay_pin_core_now();
    CHECK(now && (now & all) == now);
    const int ideal = replay_pin_ideal_now();
    CHECK(ideal >= 0 && ideal < 64 && (own >> ideal & 1));
    CHECK(replay_pin_set_ideal(ideal) && replay_pin_ideal_now() == ideal);   // (set to what it is: nothing changes)
    CHECK(!replay_pin_set_ideal(-1));
    // the whole of a soft pin on this thread, by the real calls, and back: the lab's 2 on any processor
    const uint64_t reserved = c.core_of[63 - __builtin_clzll(own)] & own;   // (this thread's last core, standing in for the reserved one)
    const uint64_t wide = replay_pin::wide(reserved, c.kinds.fastest, own);
    const DWORD_PTR was = SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)wide);
    CHECK(was == proc);
    CHECK(replay_pin_set_ideal(replay_pin::ideal(reserved)));
    const uint64_t moved = replay_pin::moved(wide, reserved, replay_pin_core_now());
    CHECK(SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)moved) == (DWORD_PTR)wide);
    CHECK(replay_pin_ideal_now() == replay_pin::ideal(reserved));
    CHECK(moved >> GetCurrentProcessorNumber() & 1);         // (it runs inside the pin's processors at once)
    CHECK(SetThreadAffinityMask(GetCurrentThread(), was) == (DWORD_PTR)moved);
    CHECK(replay_pin_set_ideal(ideal) && replay_pin_ideal_now() == ideal && replay_pin_own() == (uint64_t)proc);
    std::printf("this PC: fastest-kind processors %#llx of %#llx, %s\n", (unsigned long long)c.kinds.fastest, (unsigned long long)all,
                c.kinds.hybrid ? "cores of more than one kind (a soft pin by default)" : "one kind of core (the strict pin, as before)");
    if (!fails) std::printf("PASS: the processor as Windows lists it here, and a soft pin's calls on a real thread\n");
    return fails ? 1 : 0;
}
'''


def cut_pin(replay):
    """ReplayPin with its thread-locals, from the first of them to the struct's end"""
    start = replay.index("thread_local int replay_pin_depth = 0;")
    struct = block(replay, "struct ReplayPin {")
    return replay[start:replay.index(struct) + len(struct)] + ";\n"


def check_source(replay, dev):
    if '#include "replay_pin.h"' not in replay:
        raise SystemExit("vk_replay.cpp does not include replay_pin.h")
    soft = block(replay, "uint64_t replay_pin_soft(bool lab = true) {")
    for need, why in (('replay_pin::mode(getenv("RX_VK_REPLAY_PIN_SOFT"))', "the switch is not the header's rule over RX_VK_REPLAY_PIN_SOFT"),
                      ("static const int mode", "the switch is not read once"),
                      ("replay_pin::soft(mode, c.kinds.hybrid) || (lab && lab_ab::on(\"pinsoft\"))", "soft is not the rule's, or the lab's knob is gone"),
                      ('logf("vk: a replay\'s pin is %s', "the choice leaves no line in the log")):
        if need not in soft:
            raise SystemExit("vk_replay.cpp replay_pin_soft: " + why)
    cpu = block(replay, "const ReplayPinCpu& replay_pin_cpu() {")
    for need, why in (("e->Processor.GroupMask[0].Group == group", "cores of another processor group are taken"),
                      ("classes[n] = e->Processor.EfficiencyClass;", "the cores' kinds are not read"),
                      ("c.kinds = replay_pin::kinds(masks, classes, n);", "the fastest kind is not the header's"),
                      ("static const ReplayPinCpu cpu", "the processor is read more than once")):
        if need not in cpu:
            raise SystemExit("vk_replay.cpp replay_pin_cpu: " + why)
    pin = cut_pin(replay)
    for need in ("replay_pin::wide(m, fast, own)", "replay_pin::moved(wide, m, replay_pin_core_now())", "replay_pin::ideal(m)"):
        if need not in pin:
            raise SystemExit("vk_replay.cpp ReplayPin: %r is missing: the soft pin is not the header's" % need)
    thread = block(replay, "void replay_thread_main() {")
    if "replay_pin_soft(false)" not in thread or "replay_pin::wide(m, fast, own)" not in thread or \
            "if (on != m) replay_pin_set_ideal(replay_pin::ideal(m));" not in thread:
        raise SystemExit("vk_replay.cpp replay_thread_main: the replay thread of RX_VK_ASYNC=1 does not take the soft pin's processors")
    if "| `RX_VK_REPLAY_PIN_SOFT=0`, `=2` |" not in dev:
        raise SystemExit("docs/development.md: RX_VK_REPLAY_PIN_SOFT is not in the switches table")


def build_run(cxx, d, name, src, expect_ok=True, extra=()):
    path = d / (name + ".cpp")
    path.write_text(src, encoding="utf-8")
    exe = d / (name + ".exe")
    r = subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                        "-Wno-unused-but-set-variable", "-I" + str(VK), str(path), "-o", str(exe), *extra],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode:
        raise SystemExit("%s: the build failed:\n%s" % (name, r.stdout))
    r = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
    if expect_ok and r.returncode:
        raise SystemExit("%s failed:\n%s" % (name, r.stdout))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cxx", default="clang++")
    args = ap.parse_args()
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    host = (ROOT / "host" / "hos_thread.c").read_text(encoding="utf-8")
    check_source(replay, (ROOT / "docs" / "development.md").read_text(encoding="utf-8"))
    print("PASS sources: the switch read once through the rule, the pin and the replay thread take the rule's processors")
    pin = cut_pin(replay)
    with tempfile.TemporaryDirectory(prefix="replay-pin-soft-") as tmp:
        d = Path(tmp)
        pick = block(host, "static uint64_t pick_reserved_core(")
        print(build_run(args.cxx, d, "rule", RULE_TEST.replace("/* PICK */", pick)).stdout.strip())
        print(build_run(args.cxx, d, "pin", PIN_TEST.replace("/* PIN */", pin)).stdout.strip())
        for i, (what, old, new) in enumerate(MUTATIONS):
            if old is None:   # (the two lines that give things back, the other way round)
                old, new = RESTORE_AFF + "        // ((Triforce, THREAD-09) after the affinity, which holds the old ideal processor again)\n" + RESTORE_IDEAL, \
                    RESTORE_IDEAL + RESTORE_AFF
            if old not in pin:
                raise SystemExit("mutation %r: %r is not in the cut ReplayPin (update the test with the code)" % (what, old))
            r = build_run(args.cxx, d, "mutant%d" % i, PIN_TEST.replace("/* PIN */", pin.replace(old, new, 1)), expect_ok=False)
            if r.returncode == 0:
                raise SystemExit("mutation %r: the checks still passed without it" % what)
            print("PASS mutation: without %s a check fails (%s)" % (what, r.stdout.strip().splitlines()[0]))
        if sys.platform == "win32":
            cpu = replay[replay.index("struct ReplayPinCpu {"):replay.index("// ---- (the soft pin's processors end) ----")]
            print(build_run(args.cxx, d, "cpu", CPU_TEST.replace("/* CPU */", cpu)).stdout.strip())
        else:
            print("SKIP: the processor's reading is Windows' (not this system)")
    print("ALL PASS")


if __name__ == "__main__":
    main()
