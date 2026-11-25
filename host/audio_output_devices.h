/* ((Triforce) 11-24) The playback devices for the Audio tab's Output device row (host/audio_output_devices.c), and the device
   the player chose there, which the sound's thread opens (host/nn_audio.c output_open). Listing them never opens a stream.
   A device is kept by its endpoint id (Windows' own, opaque; HOS_OUTPUT_ID_CAP), never by its place in the list or its name,
   which two devices can share. The row's choice is the options file's audio_output_device_id= line (empty: the default).
   HOS_AUDIO_DEVICE=<n> over it for a run. HOS_OUTPUT_* (gpu/vk/vk_api.h): what the sound's thread has open now */
#pragma once
#include <stddef.h>
#include <string.h>
#include "../gpu/vk/vk_api.h"   /* (HOS_OUTPUT_ID_CAP, HOS_OUTPUT_NAME_CAP, HOS_OUTPUT_*) */

/* An endpoint id copied whole: one too long, or with a control character (a line break would add lines to the options
   file), is refused, never cut into another id. 1 copied */
static inline int audio_output_copy_id(char *out, size_t capacity, const char *id) {
    if (!out || !capacity || !id || strlen(id) >= capacity) return 0;
    for (const unsigned char *p = (const unsigned char *)id; *p; p++)
        if (*p < 0x20 || *p == 0x7f) return 0;
    memmove(out, id, strlen(id) + 1);
    return 1;
}
#ifdef __cplusplus
extern "C" {
#endif
/* (the Insert menu's, through MkwVkHost) the devices listed again, how many; one's id and name (UTF-8), 1 when there is
   one at index; the row's choice (an id, "" the default); what is open now (HOS_OUTPUT_*) */
int hos_audio_output_count(void);
int hos_audio_output_info(int index, char *id, int id_capacity, char *name, int name_capacity);
void hos_audio_output_select(const char *id);
int hos_audio_output_state(void);
/* (the sound's thread) the choice, copied into id when it changed since *generation (which is then its generation); a
   device's waveOut number by its id (-1: not there now); what was opened */
void hos_audio_output_preference(char *id, int capacity, unsigned *generation);
int hos_audio_output_resolve(const char *id);
void hos_audio_output_report(int state);
#ifdef __cplusplus
}
#endif
