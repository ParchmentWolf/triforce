/* (Triforce, 11-20) The Mods screen's music: the game's shop theme under the Mods screen opened from the title, the
   title's own music faded out meanwhile (mods_music.h has the rule and the owner's words). Here are the file and the
   sound thread's side.

   Which tune: the Happy Mask Shop's, where the Salesman of the Mods screen keeps his masks, else the Market's shop
   (the game's shops share the tune): Sound/Resource/Stream/BGM_Shop_Market_Mask.bwav of the player's game files, read
   through nn_fs.c (a mod's where a mod replaces it), decoded by menu_sound.c's decoder (two channels of DSP-ADPCM at
   48 kHz, a minute long, looping from 5.6 s to its end as its file says). It is read once, on a thread of its own,
   when the title's list first shows with its Mods entry, so that it is there when the screen opens; about 23 MB of
   samples are kept from then on. Nothing is shipped: without the file the title's music plays on as it is.

   When: the options say (gpu/vk/vk_menu.cpp menu_mods_music, HOS_OPT_MODS_MUSIC), asked at each block the sound thread
   mixes, 5 ms. How loud: MODS_MUSIC_GAIN under the Audio tab's Menu sounds row, and the Master volume over it as over
   everything; with that row at 0 there is no tune and the title's music stays. */
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "hos.h"
#include "menu_sound.h"
#include "mods_music.h"
#include "../gpu/vk/vk_api.h"   /* (HOS_OPT_MODS_MUSIC, HOS_OPT_MENU_SOUND_VOLUME) */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int rx_option(int id, int otherwise);                                         /* rx_backend.c */
uint8_t *hos_fs_rom_file(const char *rel, uint64_t most, uint64_t *size);   /* nn_fs.c */

#define FILE_MOST (32u << 20)   /* (the shop theme is 3.3 MB) */
#define SECONDS_MOST 600

static const char *const files[] = {
    "Sound/Resource/Stream/BGM_Shop_Market_Mask.bwav",
    "Sound/Resource/Stream/BGM_Shop_Market.bwav",
};

static ModsMusic music;   /* (the sound thread's) */
/* (what the reading thread made: written before its release store of 2 into loaded, taken by the sound thread after) */
static struct { float *pcm; uint32_t frames, loop_start, loop_end; } read_tune;
static atomic_int loaded;   /* 0 not yet, 1 being read, 2 ready, 3 none in the game's files */

static uint32_t u32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }

static DWORD WINAPI load_main(void *arg) {
    (void)arg;
    for (size_t i = 0; i < sizeof files / sizeof *files; i++) {
        uint64_t size = 0;
        uint8_t *b = hos_fs_rom_file(files[i], FILE_MOST, &size);
        if (!b) continue;
        uint32_t frames = 0;
        float *pcm = hos_menu_sound_decode_long(b, size, &frames, SECONDS_MOST);
        /* (the first channel's: its rate, and the loop's end and start in the file's own samples, 0xffffffff for none) */
        uint32_t rate = 0, loop_end = 0, loop_start = 0;
        if (pcm && size >= 0x10 + 0x4c) rate = u32(b + 0x14), loop_end = u32(b + 0x10 + 0x3c), loop_start = u32(b + 0x10 + 0x40);
        free(b);
        if (!pcm) {
            hos_log("mods music: %s is not a BWAV file the Mods screen plays (PCM16 or DSP-ADPCM, one or two channels, at most "
                    "%d s): left out", files[i], SECONDS_MOST);
            continue;
        }
        if (loop_end == 0xffffffffu || !rate) loop_end = loop_start = 0;
        else {   /* (at the mixer's rate, as the samples are) */
            loop_end = (uint32_t)((uint64_t)loop_end * MODS_MUSIC_RATE / rate);
            loop_start = (uint32_t)((uint64_t)loop_start * MODS_MUSIC_RATE / rate);
        }
        read_tune.pcm = pcm, read_tune.frames = frames, read_tune.loop_start = loop_start, read_tune.loop_end = loop_end;
        hos_log("mods music: the Mods screen's tune from the game's files: %s, %.1f s%s", files[i],
                (double)frames / MODS_MUSIC_RATE, loop_end > loop_start ? ", looping" : ", played once");
        atomic_store_explicit(&loaded, 2, memory_order_release);
        return 0;
    }
    hos_log("mods music: the game's files have no shop theme (%s): the Mods screen has no music, the title's plays on", files[0]);
    atomic_store_explicit(&loaded, 3, memory_order_release);
    return 0;
}

void hos_mods_music_frame(float *const *channels, int nch, uint32_t frames) {
    if (nch < 1) return;
    const int mode = rx_option(HOS_OPT_MODS_MUSIC, 0);
    int state = atomic_load_explicit(&loaded, memory_order_acquire);
    if (!mode && state != 2) return;   /* (nothing asked and nothing playing: no other option is read) */
    const int volume = rx_option(HOS_OPT_MENU_SOUND_VOLUME, -1);
    if (state == 0 && mode >= 1 && volume > 0) {
        int none = 0;
        if (atomic_compare_exchange_strong(&loaded, &none, 1)) {   /* (read off the sound thread: a disk may take its time) */
            const HANDLE t = CreateThread(NULL, 0, load_main, NULL, 0, NULL);
            if (t) CloseHandle(t);
            else {
                hos_log("mods music: no thread to read the Mods screen's tune: no music there");
                atomic_store_explicit(&loaded, 3, memory_order_release);
            }
        }
        return;
    }
    if (state != 2) return;
    if (!music.pcm) {   /* (the tune was read: the sound thread's from here) */
        music.pcm = read_tune.pcm, music.frames = read_tune.frames;
        mods_music_loop(&music, read_tune.loop_start, read_tune.loop_end);
    }
    const int want = mode == 2 && volume > 0;
    static int wanted;
    if (want != wanted) {
        wanted = want;
        hos_log(want ? "mods music: the Mods screen opened from the title: the shop theme comes, the title's music goes (0.6 s)"
                     : "mods music: the Mods screen shut: the shop theme goes, the title's music comes back (0.6 s)");
    }
    /* (the tune into the front pair; a single channel takes both of its sides) */
    mods_music_block(&music, want, channels, nch, channels[0], channels[nch > 1 ? 1 : 0], frames,
                     MODS_MUSIC_GAIN * hos_menu_sound_gain(volume) * (nch > 1 ? 1.0f : 0.5f));
}
