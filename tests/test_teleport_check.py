"""The debug teleport sends a dropped request once more (host/oot_teleport_check.h, host/hos_main.c oot_teleport_followup).

A request sent in the first frames after a save has loaded was answered 0 and then dropped by the game: nothing reserved, no
event, Link where he was. The follow-up 1.5 s later read exactly that and only logged it. Game-free: the decision compiled
with its cases, and the follow-up run on its own: teleport's state, the start of oot_teleport (its refusals, the 8 s guard
among them), the bookkeeping of a request sent and oot_teleport_followup, all cut from host/hos_main.c, with the game's
reads stubbed. It sends a dropped request again, once, to the same destination, also when a call in between was refused,
and leaves alone one the game took (answered other than 0) or one with an event playing or a map loading at the check.

Benchmark mode's tour asks again itself for the teleports it sends (host/hos_bench.c: a refused one every half second, one
with no map change after 12 s): while it runs the follow-up sends nothing, so a request has one retry, and the tour's own
is as it was. The crawl's "!banc" asks again itself too: its request is never the follow-up's.

    python -I -B tests/test_teleport_check.py [--cc gcc]   (default: $CC, else gcc)
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import srccut   # noqa: E402

FIXTURE = r"""
#include <stdio.h>
#include "oot_teleport_check.h"
static int fails;
static void check(int got, int want, const char *what) {
    if (got != want) { printf("FAIL: %s: %d, wanted %d\n", what, got, want); fails++; }
}
int main(void) {
    check(oot_teleport_dropped("", "HyruleField_Adult", "Market_Adult", 0, 0, 0, 0, 0), 1, "nothing reserved, no event, elsewhere: dropped");
    check(oot_teleport_dropped("Market_Adult", "HyruleField_Adult", "Market_Adult", 0, 0, 0, 0, 0), 0, "reserved: under way");
    check(oot_teleport_dropped("", "HyruleField_Adult", "Market_Adult", 1, 0, 0, 0, 0), 0, "an event playing: under way");
    check(oot_teleport_dropped("", "HyruleField_Adult", "Market_Adult", 0, 1, 0, 0, 0), 0, "the map loading: under way");
    check(oot_teleport_dropped("", "Market_Adult", "Market_Adult", 0, 0, 0, 0, 0), 0, "arrived");
    check(oot_teleport_dropped("", "HyruleField_Adult", "Market_Adult", 0, 0, 0, 1, 0), 0, "sent again already: not a third time");
    check(oot_teleport_dropped("", "HyruleField_Adult", NULL, 0, 0, 0, 0, 0), 0, "nothing was sent");
    check(oot_teleport_dropped("", "HyruleField_Adult", "", 0, 0, 0, 0, 0), 0, "nothing was sent (no map kept)");
    check(oot_teleport_dropped("", "", "Market_Adult", 0, 0, 0, 0, 0), 1, "no map read: still not there");
    check(oot_teleport_dropped("", "HyruleField_Adult", "Market_Adult", 0, 0, 1, 0, 0), 0, "the game took it (answered other than 0): only slow, not dropped");
    check(oot_teleport_dropped("", "HyruleField_Adult", "Market_Adult", 0, 0, 0, 0, 1), 0, "the benchmark's tour asks again itself");
    if (!fails) printf("OK: a dropped teleport is sent once more; one under way or arrived is left alone\n");
    return fails != 0;
}
"""

# The follow-up run on its own. @STATE@, @PRELUDE@, @SENT@ and @FOLLOWUP@ are cut from host/hos_main.c: oot_teleport is its
# own start (every refusal before the game is asked) and its own bookkeeping of a request sent, around a stand-in for the
# request the game takes.
SEQUENCE = r"""
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "oot_teleport_check.h"
typedef struct Ctx { int unused; } Ctx;
#define OOT_EVENTMGR_SLOT 0
static int64_t now_ns;
static char reserved[80], current[80];
static int sends;
static unsigned sent_index;
static int64_t hos_now_ns(void) { return now_ns; }
static void hos_log(const char *fmt, ...) { (void)fmt; }
static int event_playing, loading_now, bench;
static uint64_t answer;
static int hos_bench_on(void) { return bench; }   /* (host/hos_bench.c: benchmark mode, its tour's own retry) */
static const char *crawl_banc;                    /* (the crawl's "!banc", set while oot_teleport serves one) */
#define EVENTS 0x1000u
static uint64_t oot_singleton(Ctx *c, int slot) { (void)c; return slot == OOT_EVENTMGR_SLOT ? EVENTS : 0; }
static uint64_t recomp_load64(Ctx *c, uint64_t at) { (void)c; return at == EVENTS + 104 ? (uint64_t)event_playing : 0; }
static int oot_gamedata_string(Ctx *c, uint32_t hash, char *out, size_t size) {
    (void)c;
    snprintf(out, size, "%s", hash == 0xee27bf71u ? reserved : current);
    return 1;
}
static int oot_gamedata_bool(Ctx *c, uint32_t hash, int *out) { (void)c; *out = hash == 0xef2b60c2u ? loading_now : 0; return 1; }
typedef struct { const char *adult_banc; } OotDestination;
static const OotDestination oot_destinations[] = {{"Kokiri_Adult"}, {"Kakariko_Adult"}, {"Lake_Adult"}, {"Market_Adult"}};
@STATE@
@PRELUDE@
    const char *banc = crawl_banc ? crawl_banc : oot_destinations[index].adult_banc, *start = "Start", *boot = "Boot", *event = "Event";
    const int ok = 1, child = 0, with_starter = 1;
    const uint64_t result = answer;   /* (the event manager's answer: 0, as every dropped request was answered) */
    sends++, sent_index = index;
    (void)c, (void)actor;
@SENT@
    if (crawl_banc) return ok && result != 0;
    return ok;
}
@FOLLOWUP@
static int fails;
static void check(long got, long want, const char *what) {
    if (got != want) { printf("FAIL: %s: %ld, wanted %ld\n", what, got, want); fails++; }
}
static void reset(void) {
    memset(&teleport, 0, sizeof teleport);
    teleport_result = 0;
    sends = 0, sent_index = 99, now_ns = 1000000000000LL;
    event_playing = 0, loading_now = 0, answer = 0, bench = 0, crawl_banc = NULL;
    strcpy(reserved, ""), strcpy(current, "HyruleField_Adult");
}
#define AT(ms) (now_ns = 1000000000000LL + (ms) * 1000000LL)
int main(void) {
    Ctx c = {0};
    reset();   /* A sent and dropped: sent again once, never a third time */
    check(oot_teleport(&c, 1, 3), 1, "A is sent");
    AT(1600); oot_teleport_followup(&c, 1);
    check(sends, 2, "the follow-up sends a dropped A again");
    check(sent_index, 3, "to A's destination");
    AT(3200); oot_teleport_followup(&c, 1);
    AT(5000); oot_teleport_followup(&c, 1);
    check(sends, 2, "still dropped: not sent a third time");

    reset();   /* A sent and dropped, B refused under the 8 s guard before the follow-up: A is still sent again */
    oot_teleport(&c, 1, 3);
    AT(500);
    check(oot_teleport(&c, 1, 1), 0, "B, 0.5 s after A, is refused");
    AT(1600); oot_teleport_followup(&c, 1);
    check(sends, 2, "the follow-up still sends the dropped A again");
    check(sent_index, 3, "to A's destination, not B's");
    AT(3200); oot_teleport_followup(&c, 1);
    check(sends, 2, "and once only");

    reset();   /* A arrived: left alone */
    oot_teleport(&c, 1, 3);
    strcpy(current, "Market_Adult");
    AT(1600); oot_teleport_followup(&c, 1);
    check(sends, 1, "an arrived request is not sent again");

    reset();   /* A dropped, but an event playing at the check: left alone */
    oot_teleport(&c, 1, 3);
    event_playing = 1;
    AT(1600); oot_teleport_followup(&c, 1);
    check(sends, 1, "an event playing at the check: not sent again");

    reset();   /* A dropped, but a map loading at the check: left alone */
    oot_teleport(&c, 1, 3);
    loading_now = 1;
    AT(1600); oot_teleport_followup(&c, 1);
    check(sends, 1, "a map loading at the check: not sent again");

    reset();   /* A taken by the event manager (answered other than 0), nothing reserved yet: only slow, left alone */
    answer = 1;
    oot_teleport(&c, 1, 3);
    AT(1600); oot_teleport_followup(&c, 1);
    check(sends, 1, "a request the game took is not sent again");

    reset();   /* nothing sent, only a refusal: nothing to send again */
    teleport.requested_at = now_ns, teleport.check_at = now_ns;
    check(oot_teleport(&c, 1, 3), 0, "refused under the guard");
    AT(1600); oot_teleport_followup(&c, 1);
    check(sends, 0, "no request was sent: the follow-up sends none");

    reset();   /* benchmark mode: the tour's request, answered 0 and dropped, is the tour's to ask again, as it does */
    bench = 1;
    teleport.requested_at = 0, teleport_result = 0;   /* (oot_bench_tick's own, before each of its requests) */
    oot_teleport(&c, 1, 3);
    AT(1600); oot_teleport_followup(&c, 1);
    AT(3200); oot_teleport_followup(&c, 1);
    check(sends, 1, "in benchmark mode the follow-up sends nothing");
    check(teleport.resent, 0, "and the tour's request is not marked as sent again");
    bench = 0;   /* (the tour over: its last request is not sent after it either) */
    AT(4800); oot_teleport_followup(&c, 1);
    check(sends, 1, "nor once the tour is over");

    reset();   /* the crawl's "!banc": refused, it is asked again by the crawl; taken, it was answered: never the follow-up's */
    crawl_banc = "Lake_Adult";
    check(oot_teleport(&c, 1, 0), 0, "the crawl's request, answered 0, is refused to the crawl");
    crawl_banc = NULL;
    check(teleport.check_at == 0 && !teleport.pending[0], 1, "and has no follow-up");
    AT(1600); oot_teleport_followup(&c, 1);
    check(sends, 1, "the follow-up does not send the crawl's request");
    if (!fails) printf("OK: the follow-up sends a dropped request again once, also after a refused call in between, and never beside another retry\n");
    return fails != 0;
}
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    a = p.parse_args()
    src = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    where = "host/hos_main.c"
    state = srccut.between(src, "static struct {\n    int64_t requested_at, check_at;", "\n/* (Triforce, lab) The pipeline crawl's commands", where=where)
    prelude = srccut.between(src, "static int oot_teleport(Ctx *c, uint64_t actor, unsigned index) {",
                             "    const uint64_t events = oot_singleton(c, OOT_EVENTMGR_SLOT);\n    A64Fn make_arg", where=where)
    sent = srccut.between(src, "    teleport_result = ok ? result : 0;", "    if (crawl_banc) return ok && result != 0;", where=where)
    followup = srccut.block(src, "static void oot_teleport_followup(", where=where)
    sequence = (SEQUENCE.replace("@STATE@", state).replace("@PRELUDE@", prelude).replace("@SENT@", sent)
                .replace("@FOLLOWUP@", followup))
    ok = True
    if "    oot_teleport_followup(c, actor);\n    oot_bench_tick(c, actor, now);" not in src:
        print("FAIL: the player's update gives the follow-up Link's actor, to send the request with, before the benchmark's tour")
        ok = False
    # (the tour's own retry, which the follow-up leaves the tour's requests to: host/hos_bench.c)
    bench = (ROOT / "host" / "hos_bench.c").read_text(encoding="utf-8")
    tick = srccut.block(src, "static void oot_bench_tick(", where=where)
    for needle, text, what in (
            ("hos_bench_teleport_sent(want, sent && teleport_result != 0);", tick, "the tour is not told a refused request"),
            ("B.retry_ns = now + 500000000LL;", bench, "the tour no longer asks a refused teleport again"),
            ("now - B.sent_ns > 12000000000LL", bench, "the tour no longer asks again after 12 s with no map change")):
        if needle not in text:
            print("FAIL: " + what)
            ok = False
    if not (ROOT / "host" / "oot_teleport_check.h").is_file():
        print("FAIL: no host/oot_teleport_check.h")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in (("decision", FIXTURE), ("sequence", sequence)):
            c, exe = Path(tmp) / (name + ".c"), Path(tmp) / (name + ".exe")
            c.write_text(text, encoding="utf-8")
            subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"), str(c), "-o", str(exe)],
                           check=True)
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            print(r.stdout, end="")
            ok = ok and r.returncode == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
