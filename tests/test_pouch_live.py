"""The Debug tab's Inventory gives an item to the game's live pouch, through the game's own add and remove, before GameData
(host/pouch_live.h, host/hos_main.c; no game).

The Inventory page set an item's count in GameData alone (its Pouch struct's Stock and its "got it once" flag). The pause
menu showed it, but what the game does when it gives Link something through its pouch manager was not done (the owner,
11-24: "item unlocks not detecting in game"). The pouch manager's add (f_8112d570) and remove (f_833c4fa0) are what
the game's event action OneShotAddOrRemovePouchContent (f_828d4a70) calls; the Inventory now asks them for the difference
between the count wanted and the pouch's own count, then sets GameData as before.

Compiles host/pouch_live.h's rule and runs it: the difference, nothing when the pouch has no answer (-1: no save loaded or
no such content) or already holds the count, nothing with HOS_POUCH_LIVE=0. Reads hos_main.c: the add and the remove are
the game's functions with the action's arguments (the reason "Script"), the name passed as the action passes it, the
change asked of the pouch before GameData is set, and a switch back; the docs row.

    python -I -B tests/test_pouch_live.py [--cc gcc]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def function(text, head):
    start = text.index(head)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <stdio.h>
#include "pouch_live.h"
#define CHECK(x) do { if (!(x)) { printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
int main(void) {
    CHECK(pouch_live_env(NULL) == 1 && pouch_live_env("") == 1 && pouch_live_env("1") == 1 && pouch_live_env("00") == 1);
    CHECK(pouch_live_env("0") == 0);
    CHECK(pouch_live_delta(1, 0, 1) == 1);      /* an unlock: one more */
    CHECK(pouch_live_delta(1, 1, 0) == -1);     /* a relock: one taken */
    CHECK(pouch_live_delta(1, 5, 30) == 25);    /* an amount */
    CHECK(pouch_live_delta(1, 30, 12) == -18);
    CHECK(pouch_live_delta(1, 3, 3) == 0);      /* held already */
    CHECK(pouch_live_delta(1, -1, 1) == 0);     /* no answer: no save loaded, no such content */
    CHECK(pouch_live_delta(1, 2, -1) == 0);
    CHECK(pouch_live_delta(0, 0, 1) == 0);      /* HOS_POUCH_LIVE=0 */
    CHECK(POUCH_REASON_SCRIPT == 9);
    printf("ok\n");
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp) / "pouch_live_test.c", Path(tmp) / "pouch_live_test.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"), str(src), "-o", str(exe)],
                       check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        check(run.returncode == 0 and run.stdout.strip() == "ok", "the rule: %s%s" % (run.stdout, run.stderr))

    main_c = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    change = function(main_c, "static int oot_pouch_change(Ctx *c, const char *name, int delta) {")
    check("a64_lookup(0x8112d570ULL)" in change and "a64_lookup(0x833c4fa0ULL)" in change,
          "the change is not the game's own pouch add and remove")
    check("recomp_load64(c, 0x84e98e28ULL)" in change, "the change is not asked of the pouch manager")
    check("c->x[4] = POUCH_REASON_SCRIPT" in change and "c->x[3] = (uint64_t)(uint32_t)delta" in change,
          "the add does not pass the count and the reason as the game's action does")
    check("c->x[2] = (uint64_t)(uint32_t)-delta" in change, "the remove does not pass the count taken")
    check("recomp_store64_sp(c, text, text + 0xc)" in change and "recomp_store32_sp(c, text + 8, POUCH_NAME_ROOM)" in change,
          "the name is not passed as the game's action passes it (its text, its buffer's size, the buffer)")
    check("*c = saved;" in change, "the change leaves the game's registers changed")
    check("took = (int)(c->x[0] & 1);" in change, "an add the game refused is taken as done")
    give = function(main_c, "static int oot_item_give(Ctx *c, const char *name, int count) {")
    at_live, at_set = give.find("pouch_live_delta(live_on, live, count)"), give.find("if (oot_pouch_set(c, mgr, name, count)) return 1;")
    check(at_live >= 0 and at_set >= 0 and at_live < at_set, "the pouch is not asked before GameData is set")
    check("oot_pouch_change(c, name, delta)" in give and 'pouch_live_env(getenv("HOS_POUCH_LIVE"))' in give,
          "oot_item_give does not ask the pouch, or has no switch back")
    # (the pouch writes GameData itself, a frame later and by the difference: a count set in GameData too was counted twice,
    # 20 bombs and three more made 26 in a run on 11-24)
    at_took = give.find("if (took) return 1;")
    check(0 <= at_took < at_set, "GameData's count is set again over a change the pouch took")

    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    check("`HOS_POUCH_LIVE=0`" in docs, "docs/development.md's switches have no HOS_POUCH_LIVE row")
    print("PASS: the Inventory gives and takes through the game's own pouch, then sets GameData")


if __name__ == "__main__":
    main()
