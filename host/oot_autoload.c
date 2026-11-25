/* (Triforce) The System tab's Skip title screen row: the game starts on the newest save, the title screen and its file
   list pressed through.

   The way is benchmark mode's (host/hos_bench.c hos_bench_menu, which starts the game into play the same way): the game's
   start has three screens with a list, and as each gets its focused button A is pressed on it (host/oot_menu.c, at a menu
   screen's update): the title's list on Continue, the file select on the save it opens on (the newest of the playthrough),
   the save's box on Load. host/oot_autoload.h has the rules, and when a run ends.

   - Off, the default: hos_oot_autoload_wants is asked at a menu screen's update, reads the row once the renderer answers,
     and says 0 from then on for the whole run. Nothing is read of the game and nothing is pressed.
   - The newest save is the newest of all the save files (host/save_files.c: the playthroughs the file select shows). The
     game starts on the file played last; when another file was saved in later, or this one has no save yet (a first
     start, a new file), the title stays and the player chooses.
   - Nothing is written: no file of a save is opened here (the saves' times are their folders' own), and the only presses
     are A on Continue and A on Load, which the rules hold to the first entry of their lists. Not in benchmark mode,
     which has its own start. */
#include "hos.h"
#include "hos_bench.h"
#include "oot_autoload.h"
#include "../gpu/vk/vk_api.h"

int rx_option(int id, int otherwise);                 /* rx_backend.c */
int hos_save_files_newest_here(const char *own_dir);  /* save_files.c */
extern const char *hos_user_dir;                      /* nn_fs.c: the folder the game saves in */
int hos_oot_flight_shortcut_ready(void);              /* hos_main.c: Link was updated within the last quarter second */
int64_t hos_player_input_ns(void);                    /* nn_hid.c: the player's own pads and bound keys, last used */

static OotAutoload run;
static volatile char busy;
static volatile int over;   /* (the run is over, or the row is Off: nothing more is asked) */

/* host/oot_menu.c, before it looks at a screen for us: 0 while no renderer has answered for the row, and for the whole run
   once the row is known Off or the run is over */
int hos_oot_autoload_wants(void) {
    if (over) return 0;
    if (run.state == OOT_AUTOLOAD_WAITS) {
        const int row = rx_option(HOS_OPT_SKIP_TITLE, -1);
        if (row == 0) over = 1;
        if (row <= 0) return 0;
    }
    return 1;
}

static const char *why_text(int why) {
    return why == OOT_AUTOLOAD_LOADED ? "the save is loaded" : why == OOT_AUTOLOAD_PLAYER ? "the player pressed something: the choice is theirs"
         : why == OOT_AUTOLOAD_SCREEN ? "another screen came up: left to the player"
         : why == OOT_AUTOLOAD_CURSOR ? "the cursor is not on the first entry: left to the player"
         : why == OOT_AUTOLOAD_NOT_TAKEN ? "a screen did not take the presses" : "too long after the start";
}

/* host/oot_menu.c, a menu screen's update while it has a focused button: its vtable and the focused entry's place in its
   list. 1: press A now */
int hos_oot_autoload_menu(uint64_t vt, int focused_entry) {
    if (over) return 0;
    int press = 0;
    while (__atomic_test_and_set(&busy, __ATOMIC_ACQUIRE)) {}
    const int64_t now = hos_now_ns();
    const int stage = oot_autoload_stage(vt);
    if (run.state == OOT_AUTOLOAD_WAITS) {
        const int row = rx_option(HOS_OPT_SKIP_TITLE, -1);
        if (row == 0 || hos_bench_on()) {
            over = 1;   /* (Off, or benchmark mode: for the whole run) */
        } else if (row > 0) {
            if (stage != OOT_AUTOLOAD_TITLE) {
                hos_log("skip title: the first screen is not the title's list (vtable %#llx): left to the player", (unsigned long long)vt);
                over = 1;
            } else if (!hos_save_files_newest_here(hos_user_dir)) {
                hos_log("skip title: this file has no save yet, or another file was saved in later: the title stays");
                over = 1;
            } else {
                oot_autoload_begin(&run, now);
                hos_log("skip title: this file holds the newest save: Continue, the file it opens on, Load");
            }
        }   /* (row < 0: no renderer has answered yet; asked again at the next update) */
    }
    if (run.state == OOT_AUTOLOAD_RUNS) {
        press = oot_autoload_step(&run, stage, focused_entry, now, rx_option(1, 0), hos_oot_flight_shortcut_ready(), hos_player_input_ns());
        if (press) hos_log("skip title: A pressed on %s", stage == OOT_AUTOLOAD_TITLE ? "the title" : stage == OOT_AUTOLOAD_FILES ? "the file select" : "the file's box");
        if (run.state == OOT_AUTOLOAD_OVER) {
            hos_log("skip title: over, %s", why_text(run.why));
            over = 1;
        }
    }
    __atomic_clear(&busy, __ATOMIC_RELEASE);
    return press;
}
