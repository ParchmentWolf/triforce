/* (Triforce) The options' sounds, the game's own interface sounds (menu_sound.c). */
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* A BWAV file's samples as interleaved stereo floats at 48 kHz, *frames of them (freed by the caller); NULL when the
   bytes are not a file this plays. Nothing outside [file, file + size) is read */
float *hos_menu_sound_decode(const uint8_t *file, uint64_t size, uint32_t *frames);
/* ((Triforce, 11-20) the same for a file of up to `seconds`: a tune (host/mods_music.c, the Mods screen's music) */
float *hos_menu_sound_decode_long(const uint8_t *file, uint64_t size, uint32_t *frames, uint32_t seconds);
/* The Mods screen's music (host/mods_music.c), at each block the sound thread mixes, after the game's own mix and its
   limiter and before the options' sounds: while the Mods screen is open from the title the game's nch channels are
   turned down and the game's shop theme is added to the front pair, crossing over in 0.6 s each way */
void hos_mods_music_frame(float *const *channels, int nch, uint32_t frames);
/* The Menu sounds row's percent as a gain: 0 at 0 and under, 1 at 100 and over */
float hos_menu_sound_gain(int percent);
/* Starts the sound of a HOS_MENU_SOUND_* (gpu/vk/vk_api.h) on a free voice, else on the oldest. No lock is taken: it
   may run while another thread mixes. now_ns: the caller's clock (the cursor's tick is not started twice in 180 ms) */
void hos_menu_sound_play(int id, int64_t now_ns);
/* Adds the playing sounds to `frames` samples of the left and the right channel at 48 kHz, times gain, and moves the
   voices on (at gain 0 too: a sound goes on unheard) */
void hos_menu_sound_mix(float *left, float *right, uint32_t frames, float gain);
/* The sound thread, at each block it mixes (host/nn_audio.c render_frame), after the game's own mix and before the
   Master volume: the sounds the options asked for since the last block are started, and those playing are added to
   the block's front left and right */
void hos_menu_sound_frame(float *left, float *right, uint32_t frames);

#ifdef __cplusplus
}
#endif
