/* (Triforce, 11-20) The Mods screen's music. The owner: "have the in game mods menu in the title screen play the shop
   theme quietly in the background ... it mutes the title screen music's audio while in the mod menu and fades in/out".
   While the Mods screen is open from the title's list, the game's own shop theme (the Happy Mask Shop's, the Salesman's:
   Sound/Resource/Stream/BGM_Shop_Market_Mask.bwav of the player's game files, a mod's where a mod replaces it) plays
   under the screen, quietly, and the game's own sound (the title's music) is turned down to nothing as it comes and
   back up as it goes. Nothing is shipped: game files without the tune leave the title's music as it is.

   This is the rule alone, no files and no threads (tests/test_mods_music.py compiles it): one level, 0 to 1, moves a
   sample at a time toward 1 while the screen wants the music and toward 0 while it does not, over MODS_MUSIC_FADE
   samples each way. The game's channels are multiplied by 1 - level and the tune is added times level, so the two
   cross over with no step and no click. The tune loops between the points its file names (the shop theme: from 5.6 s
   to its end); once the level is back at 0 it is at its top again for the next time the screen opens. */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define MODS_MUSIC_RATE 48000                          /* (nn_audio.c RATE, menu_sound.c MIX_RATE: the output's) */
#define MODS_MUSIC_FADE (MODS_MUSIC_RATE * 6 / 10)     /* the cross-over's length each way: 0.6 s */
#define MODS_MUSIC_GAIN 0.6f                           /* "quietly": the file's own level is low (peak 0.25); 4 dB under it */

typedef struct ModsMusic {
    const float *pcm;                         /* interleaved stereo at 48 kHz; NULL: no tune (not read, or not in the files) */
    uint32_t frames, loop_start, loop_end;    /* loop_end > loop_start: it goes round between them; else once, then silence */
    uint32_t pos;                             /* the next frame of the tune */
    float level;                              /* how much of the tune is heard, 0 to 1; the game's own has 1 - level */
} ModsMusic;

/* The loop a file names, as the tune keeps it: [start, end) inside its frames, or none (0, 0) */
static inline void mods_music_loop(ModsMusic *m, uint32_t start, uint32_t end) {
    if (end > m->frames) end = m->frames;
    if (end > start + MODS_MUSIC_RATE / 10) m->loop_start = start, m->loop_end = end;   /* (a loop under 0.1 s is no tune's) */
    else m->loop_start = m->loop_end = 0;
}

/* One block of the output. want: the Mods screen is open from the title and its sounds are not off. game: the nch
   channels the game mixed, frames samples each, turned down by the level sample by sample; the tune is added to left
   and right (the game's front pair) times gain. With no tune nothing changes, whatever want is. Returns the level. */
static inline float mods_music_block(ModsMusic *m, int want, float *const *game, int nch, float *left, float *right,
                                     uint32_t frames, float gain) {
    if (!m->pcm || !m->frames) {
        m->level = 0.0f;
        return 0.0f;
    }
    const float step = 1.0f / (float)MODS_MUSIC_FADE;
    if (!want && m->level <= 0.0f) return 0.0f;   /* (shut and silent: the block is the game's as it is) */
    for (uint32_t i = 0; i < frames; i++) {
        float level = m->level + (want ? step : -step);
        level = level < 0.0f ? 0.0f : level > 1.0f ? 1.0f : level;
        m->level = level;
        const float game_gain = 1.0f - level;
        for (int ch = 0; ch < nch; ch++) game[ch][i] *= game_gain;
        if (level <= 0.0f) {   /* (gone: at its top for the next time; the rest of the block is the game's) */
            m->pos = 0;
            if (!want) break;
            continue;
        }
        if (m->pos < m->frames) {
            const float g = level * gain;
            left[i] += m->pcm[2 * (size_t)m->pos] * g;
            right[i] += m->pcm[2 * (size_t)m->pos + 1] * g;
            m->pos++;
        }
        if (m->loop_end > m->loop_start && m->pos >= m->loop_end) m->pos = m->loop_start;
    }
    return m->level;
}
