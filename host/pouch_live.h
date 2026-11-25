/* (Triforce, 11-24) The Debug tab's Inventory: an item given or taken away is given to or taken from the live pouch, the
   pouch manager the game asks whether Link has something, through the game's own add and remove (host/hos_main.c
   oot_pouch_change), and then set in GameData as before. Set in GameData alone, it showed on the Inventory page and in the
   save, and the game did not see it: unlocked gauntlets lifted nothing (the owner, 11-24).

   pouch_live_delta says what the pouch is asked: the difference between the count wanted and the pouch's own count, none
   when the pouch has no answer (no save loaded, no such content: -1) or already holds it. HOS_POUCH_LIVE=0: GameData alone,
   as before. Read by host/hos_main.c and tests/test_pouch_live.py, which compiles these rules. */
#ifndef HOS_POUCH_LIVE_H
#define HOS_POUCH_LIVE_H

#define POUCH_NAME_ROOM 0x60      /* the name's buffer: the longest content name the pouch is asked about, as oot_pouch_count */
#define POUCH_REASON_SCRIPT 9     /* OneShotAddOrRemovePouchContent's reasons: PickUp 0 ... Event 7, Seq 8, Script 9 */

static inline int pouch_live_env(const char *e) { return !(e && e[0] == '0' && !e[1]); }

/* the add (> 0) or remove (< 0) the pouch is asked for, 0 none: live is the pouch's count (-1 no answer), want the count set */
static inline int pouch_live_delta(int on, int live, int want) {
    if (!on || live < 0 || want < 0 || live == want) return 0;
    return want - live;
}

#endif
