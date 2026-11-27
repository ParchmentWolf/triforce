/* (Triforce, Evil HD) The Graphics tab's Evil HD row: the owner's own graphics mode, off unless chosen. Its first part
   is a longer render distance; later parts join the same row. host/evil_hd.c reads the row and the switches each frame
   and applies them.

   Render distance, part 1: the foliage. The game's grass, undergrowth, flowers and stones ("ornaments"), and its low trees
   (impostor cards for the trees of the distance) and their shadows are drawn by its foliage system out to the distances of
   game::foliage::ResLodSetting, one for the docked console and one for handheld in each area's ResFoliageScene. An area
   whose data does not set them (Hyrule Field, Kakariko, Lake Hylia, the Market, most of them) takes the struct's
   defaults, eight floats the game's parameter code passes to its reader by address (f_82c0d2xx: one reference each):

       Dist_Undergrowth0 40, Dist_Undergrowth1 60, Dist_Ornament 35, Dist_LowTreeShootLeaf 30, Dist_LowTreeShadow 40,
       Dist_LowTree 135 (metres), Range_LowTree01 10, Range_LowTree12 45 (the fades between the trees' three levels)

   at main+0x3eefd38, in that order. Grass stops at 40 to 60 m and the trees of the far hills at 135 m. With Evil HD on,
   host/evil_hd.c writes them times the factor (4 unless HOS_EVIL_HD_DIST says otherwise); off, the game's own again.
   The game reads the eight at each area it enters (f_80116bb0, twice: console and handheld; HOS_WATCH), but the foliage
   system builds an area's distances from them once a run, the first time it enters it, and keeps those: the row applies
   from the start of a run (the menu asks to restart), and a change mid-run reaches only the areas not visited yet. The
   areas that set their own (the Graveyard, Zora's River and Domain, Hyrule Castle's ornaments, Kokiri Forest handheld)
   keep theirs.
   Seen in the game (11-24, headless at 1920x1080, Hyrule Field from the Market's drawbridge at noon): at 4x the grass
   tufts and small plants cover the meadows out to the ranch and up the hills, where the game's own stop at about 40 to
   60 m; at 2.5x part of the way. With all eight at 0.5 m the ivy and the grass by the Lost Woods bridge go. The cost
   there, uncapped on an RTX 5090 PC whose frame the CPU limits: off 147 and 128 fps, 2.5x 128, 4x 124 and 123, about
   0.8 ms a frame at 4x; the draws stay about 2100 (the foliage's instances grow, not its draws).

   Draw only: the foliage has no logic past the player's own grass cutting, which works at arm's length. The camera's far
   plane (25 km in play, near 0.1 m, read from the scene's camera constants on 11-24: not what limits the view; the 1000 m
   seen first is the title screen's camera), the model LOD coefficient (game::gfx::ModelLodParam's LodStartDistCoef, 1
   docked and 0.8 handheld: at 0.05 from boot the Market and Lake Hylia looked the same), the actors' presence radius (DisplayRadius, which creates and deletes them: respawns, flags) and their
   update radius (CalcRadius) are left as they are.

   HOS_EVIL_HD=0 or 1 over the row. HOS_EVIL_HD_DIST=<factor>, 1 to 4 (4 when not set or not a number in range): how far
   the render distance goes with Evil HD on; 1: the game's distances, as before.

   The rule alone, no game: tests/test_evil_hd.py compiles it. */
#ifndef EVIL_HD_H
#define EVIL_HD_H
#include <stdint.h>
#include <string.h>

#define EVIL_HD_DIST_DEFAULT 4.0f
#define EVIL_HD_DIST_MOST 4.0f
enum { EVIL_HD_FOLIAGE_COUNT = 8 };
#define EVIL_HD_FOLIAGE_DEFAULTS 0x83f0fd38ULL   /* (main+0x3eefd38: the eight defaults, in this order) */
static const float evil_hd_foliage_game[EVIL_HD_FOLIAGE_COUNT] = {40.0f, 60.0f, 35.0f, 30.0f, 40.0f, 135.0f, 10.0f, 45.0f};
/* ((Triforce, 11-25, a player's report with the measurements: "Evil HD 4x: Kokiri Forest bushes and Lost Woods tree leaves
   flicker") The most two of them go to: the ornaments (Kokiri Forest's cuttable bushes and flowers) flickered at 140 m (4x)
   and 105 m (3x) and were steady at 70 and 75 m; the low trees' shoot leaves (the Lost Woods' leaves overhead) flickered at
   120 m and were steady at 30 and 70 m. The game's own areas set them no farther than 75 m (Hyrule Castle's ornaments) and
   70 m (Zora's Domain's shoot leaves): the foliage system seems to have room for about that many of them. The other six
   showed no flicker at 4x and keep the whole factor. 0: no bound
   (11-26, measured on child Kokiri Forest, KokiriForest_Child, by the Lost Woods entrance) The undergrowth too: its low,
   uncuttable ground cover popped in and out on camera turns at 4x, 3x, 2.5x and 2.25x and was steady at 2x (80 and 120 m).
   With one factor per distance: 80/120 m steady, 80/135 m steady, 90/120 m borderline, 90/135 m, 80/180 m, 160/120 m and
   80/240 m popped. The two kinds seem to share one room (more of one leaves less for the other), so both are kept to the
   steady pair, 80 and 120 m: twice the game's. */
static const float evil_hd_foliage_most[EVIL_HD_FOLIAGE_COUNT] = {80.0f, 120.0f, 75.0f, 70.0f, 0.0f, 0.0f, 0.0f, 0.0f};
/* One distance at a factor: the game's times it, kept to its most */
static inline float evil_hd_foliage_one(int i, float factor) {
    const float v = factor == 1.0f ? evil_hd_foliage_game[i] : evil_hd_foliage_game[i] * factor;
    return evil_hd_foliage_most[i] > 0.0f && v > evil_hd_foliage_most[i] && evil_hd_foliage_game[i] <= evil_hd_foliage_most[i]
               ? evil_hd_foliage_most[i] : v;
}

/* Whether Evil HD is on: the row's value, or HOS_EVIL_HD's when it is set to 0 or 1 (anything else: the row's) */
static inline int evil_hd_on(int row, const char *asked) {
    if (asked && (asked[0] == '0' || asked[0] == '1') && !asked[1]) return asked[0] == '1';
    return row != 0;
}

/* HOS_EVIL_HD_DIST's factor: a decimal number from 1 to EVIL_HD_DIST_MOST; not set, not a number or out of range, the default */
static inline float evil_hd_dist_factor(const char *asked) {
    if (!asked || !*asked) return EVIL_HD_DIST_DEFAULT;
    float v = 0.0f, scale = 0.0f;
    int digits = 0;
    for (const char *p = asked; *p; p++) {
        if (*p >= '0' && *p <= '9') {
            if (scale > 0.0f) v += (float)(*p - '0') * scale, scale *= 0.1f;
            else v = v * 10.0f + (float)(*p - '0');
            if (++digits > 6) return EVIL_HD_DIST_DEFAULT;
        } else if (*p == '.' && scale == 0.0f) {
            scale = 0.1f;
        } else {
            return EVIL_HD_DIST_DEFAULT;
        }
    }
    if (!digits || v < 1.0f || v > EVIL_HD_DIST_MOST) return EVIL_HD_DIST_DEFAULT;
    return v;
}

/* The render distance's factor now: 1 (the game's own) with Evil HD off, else the switch's */
static inline float evil_hd_factor(int row, const char *mode, const char *dist) {
    return evil_hd_on(row, mode) ? evil_hd_dist_factor(dist) : 1.0f;
}

/* The game's eight foliage defaults, each times the factor (kept to evil_hd_foliage_most), into out (the factor 1: the game's own exactly) */
static inline void evil_hd_foliage(float factor, float out[EVIL_HD_FOLIAGE_COUNT]) {
    for (int i = 0; i < EVIL_HD_FOLIAGE_COUNT; i++) out[i] = evil_hd_foliage_one(i, factor);
}

/* Whether the eight floats at the defaults' place are a version of them this rule knows: the game's own, or the game's
   times a factor of 1 to EVIL_HD_DIST_MOST (what an earlier write of this left). Another game version's bytes: left alone */
static inline int evil_hd_foliage_known(const float have[EVIL_HD_FOLIAGE_COUNT]) {
    const float f = have[5] / evil_hd_foliage_game[5];   /* (the low trees' distance: no most, so it carries the factor) */
    if (!(f >= 1.0f && f <= EVIL_HD_DIST_MOST)) return 0;
    for (int i = 0; i < EVIL_HD_FOLIAGE_COUNT; i++) {
        const float want = evil_hd_foliage_one(i, f), d = have[i] - want;
        if (d > want * 1e-4f || d < -want * 1e-4f) return 0;
    }
    return 1;
}
#endif
