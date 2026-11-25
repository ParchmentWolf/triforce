/* (Triforce) The System tab's Skip title screen row: the rules, apart from the game and the host, so that
   tests/test_play_rows.py runs them alone. host/oot_autoload.c has what is the game's.

   The game's start has three screens with a list, as benchmark mode found them (host/hos_bench.c): the title's list, whose
   first entry is Continue; the file select, which opens on the newest of the playthrough's saves; and the chosen save's
   box, whose first entry is Load. The row presses A on each as it gets its focused button, and that is all it does: no
   cursor is moved, so nothing but Continue and Load is ever pressed. */
#pragma once

#include <stdint.h>

/* a screen's place in the start: by its vtable (build e0f3ccfa, as host/hos_bench.c names them) */
enum { OOT_AUTOLOAD_TITLE, OOT_AUTOLOAD_FILES, OOT_AUTOLOAD_BOX, OOT_AUTOLOAD_OTHER };
static inline int oot_autoload_stage(uint64_t vt) {
    return vt == 0x84c106e8ULL ? OOT_AUTOLOAD_TITLE : vt == 0x84c0eba0ULL ? OOT_AUTOLOAD_FILES
         : vt == 0x84c0f840ULL ? OOT_AUTOLOAD_BOX : OOT_AUTOLOAD_OTHER;
}

/* Whether this run's file holds the newest save of all the files the player has (host/save_files.c's playthroughs: what
   the file select shows). times: each file's last save, 0 or less for none; n how many; current this run's. 1 only when
   this run's file has a save and no other file was saved in later: the save Continue loads is then the newest there is */
static inline int oot_autoload_newest_here(const int64_t *times, int n, int current) {
    if (current < 0 || current >= n || times[current] <= 0) return 0;
    for (int i = 0; i < n; i++)
        if (times[i] > times[current]) return 0;
    return 1;
}

enum { OOT_AUTOLOAD_WAITS, OOT_AUTOLOAD_RUNS, OOT_AUTOLOAD_OVER };
/* why a run ended */
enum { OOT_AUTOLOAD_LOADED = 1, OOT_AUTOLOAD_PLAYER, OOT_AUTOLOAD_SCREEN, OOT_AUTOLOAD_CURSOR, OOT_AUTOLOAD_NOT_TAKEN, OOT_AUTOLOAD_LATE };
enum { OOT_AUTOLOAD_PRESSES = 4 };               /* (the most on one screen) */
#define OOT_AUTOLOAD_AGAIN_NS 700000000LL        /* (a screen still there with its focus this long after a press: pressed again) */
#define OOT_AUTOLOAD_AGAIN_BOX_NS 5000000000LL   /* (the box: Load takes a moment before the box goes) */
#define OOT_AUTOLOAD_LATE_NS 90000000000LL       /* (a run older than this is over: nothing is pressed long after the start) */
#define OOT_AUTOLOAD_GAP_NS 4000000000LL         /* (no screen of the start for this long: the start is over, a later menu is the player's) */

typedef struct {
    int state, why, stage_max;
    int presses[3];
    int64_t press_ns[3];
    int64_t begin_ns, seen_ns;   /* (when the run began; when a screen was last looked at) */
} OotAutoload;

static inline void oot_autoload_begin(OotAutoload *a, int64_t now_ns) {
    for (int i = 0; i < 3; i++) a->presses[i] = 0, a->press_ns[i] = 0;
    a->state = OOT_AUTOLOAD_RUNS, a->why = 0, a->stage_max = 0, a->begin_ns = a->seen_ns = now_ns;
}
static inline int oot_autoload_end(OotAutoload *a, int why) {
    a->state = OOT_AUTOLOAD_OVER, a->why = why;
    return 0;
}

/* A menu screen with a focused button, at one of its updates: 1 when A is to be pressed now. stage: the screen's
   (oot_autoload_stage); focused_entry: the focused button's place in its list; menu_open: our own options are open (their
   presses are theirs: nothing is pressed, the run waits); player_seen: Link is being updated (the save is loaded);
   player_ns: when the player last used a pad or a bound key (0 never).
   The run is over, for good, once the save is loaded; once the player has pressed anything since it began (the choice is
   theirs from then on); on any screen that is none of the three; when the cursor is not on the first entry of the title's
   list or of the box (so that nothing but Continue and Load is pressed); when a screen did not take four presses; 90 s
   after it began; and when no screen was looked at for 4 s (the start's screens follow one another: a list that comes
   up later, the pause menu's Load among them, is the player's). A screen of an earlier step, still fading out under the
   next, is not pressed again */
static inline int oot_autoload_step(OotAutoload *a, int stage, int focused_entry, int64_t now_ns, int menu_open, int player_seen,
                                    int64_t player_ns) {
    if (a->state != OOT_AUTOLOAD_RUNS) return 0;
    if (player_seen) return oot_autoload_end(a, OOT_AUTOLOAD_LOADED);
    if (player_ns > a->begin_ns) return oot_autoload_end(a, OOT_AUTOLOAD_PLAYER);
    if (now_ns - a->begin_ns > OOT_AUTOLOAD_LATE_NS || now_ns - a->seen_ns > OOT_AUTOLOAD_GAP_NS) return oot_autoload_end(a, OOT_AUTOLOAD_LATE);
    a->seen_ns = now_ns;
    if (menu_open) return 0;
    if (stage < OOT_AUTOLOAD_TITLE || stage >= OOT_AUTOLOAD_OTHER) return oot_autoload_end(a, OOT_AUTOLOAD_SCREEN);
    if (stage < a->stage_max) return 0;
    a->stage_max = stage;
    if (stage != OOT_AUTOLOAD_FILES && focused_entry != 0) return oot_autoload_end(a, OOT_AUTOLOAD_CURSOR);
    const int64_t again = stage == OOT_AUTOLOAD_BOX ? OOT_AUTOLOAD_AGAIN_BOX_NS : OOT_AUTOLOAD_AGAIN_NS;
    if (a->presses[stage] && now_ns - a->press_ns[stage] <= again) return 0;
    if (a->presses[stage] >= OOT_AUTOLOAD_PRESSES) return oot_autoload_end(a, OOT_AUTOLOAD_NOT_TAKEN);
    a->presses[stage]++, a->press_ns[stage] = now_ns;
    return 1;
}
