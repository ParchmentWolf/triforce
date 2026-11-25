/* (Triforce, 11-24) The Debug tab's No-clip flight: the button its double-tap takes off and lands with, and holds to climb.
   It is the game's own Jump: X, or B with the game's Swap Jump Controls (its option OptionData.IsChangeJumpButton, a Bool of
   GameData; host/hos_main.c reads it at Link's update and says it here through hos_oot_jump_swapped). The tool had B, the
   jump of the game it came from, so the Jump the player pressed (X, the keyboard's Space) never took off.
   HOS_FLIGHT_JUMP=B keeps B whatever the game's option says, as before; =X keeps X. Read by host/nn_hid.c, and by
   tests/test_flight_jump.py, which compiles these rules. */
#ifndef HOS_FLIGHT_JUMP_H
#define HOS_FLIGHT_JUMP_H

#include <stdint.h>

#define FLIGHT_JUMP_HASH 0xef35e764u   /* MurmurHash3("OptionData.IsChangeJumpButton"): the game's Swap Jump Controls */
enum { FLIGHT_JUMP_GAME = 0, FLIGHT_JUMP_ALWAYS_B = 1, FLIGHT_JUMP_ALWAYS_X = 2 };
enum { FLIGHT_BIT_B = 1, FLIGHT_BIT_X = 2 };   /* HidNpadButton: A 0, B 1, X 2 */

/* HOS_FLIGHT_JUMP: "B" or "b" B always (as before), "X" or "x" X always, anything else (or unset) the game's Jump */
static inline int flight_jump_mode_env(const char *e) {
    if (e && (e[0] == 'B' || e[0] == 'b') && !e[1]) return FLIGHT_JUMP_ALWAYS_B;
    if (e && (e[0] == 'X' || e[0] == 'x') && !e[1]) return FLIGHT_JUMP_ALWAYS_X;
    return FLIGHT_JUMP_GAME;
}

/* The Jump's button bit, by the switch and the game's option (swapped: 1 Swap Jump Controls on, 0 off, -1 not read yet:
   the game's default, X) */
static inline uint64_t flight_jump_bit(int mode, int swapped) {
    if (mode == FLIGHT_JUMP_ALWAYS_B) return 1ULL << FLIGHT_BIT_B;
    if (mode == FLIGHT_JUMP_ALWAYS_X) return 1ULL << FLIGHT_BIT_X;
    return 1ULL << (swapped > 0 ? FLIGHT_BIT_B : FLIGHT_BIT_X);
}

#endif
