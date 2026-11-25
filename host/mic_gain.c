/* (Triforce) The Audio tab's Microphone gain row for host/nn_audio_in.c: percent of what the microphone gives, 100 (its own:
   nothing is changed, host/mic_gain.h) at the row's default and without a renderer. */
#include "../gpu/vk/vk_api.h"

int rx_option(int id, int otherwise);

int hos_mic_gain(void) { return rx_option(HOS_OPT_MIC_GAIN, 100); }
