"""Linux playback discovery for the Output device row, with a fake SDL device list; no hardware or game.

python -I -B tests/test_linux_audio_output.py --cc clang
host/audio_output_devices.c's list and its resolve take Linux's devices from host/hos_sdl.c (hos_sdl_output_*), and the
waveOut stand-in (host/posix/win32_posix.c) opens the one chosen, closes its stream with the handle and says when it is
gone. The SDL side itself is a host test (real PipeWire/PulseAudio/ALSA playback).
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]
ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>
#undef _WIN32
#include "audio_output_devices.h"
typedef int SRWLOCK;
typedef unsigned long DWORD;
#define MAX_PATH 260
#define SRWLOCK_INIT 0
static void AcquireSRWLockExclusive(SRWLOCK *p) { assert(!*p); *p=1; }
static void ReleaseSRWLockExclusive(SRWLOCK *p) { assert(*p); *p=0; }
#define AcquireSRWLockShared AcquireSRWLockExclusive
#define ReleaseSRWLockShared ReleaseSRWLockExclusive
static DWORD hos_game_path_a(char *path, DWORD n) { (void)n; path[0] = 0; return 0; }
extern int hos_sdl_output_count(void) __attribute__((weak));
extern int hos_sdl_output_info(int, char *, int, char *, int) __attribute__((weak));
extern int hos_sdl_output_resolve(const char *) __attribute__((weak));
'''

METADATA = r'''
int hos_sdl_output_count(void) { return 2; }
int hos_sdl_output_info(int i, char *id, int cap, char *name, int ncap) {
    if (i < 0 || i > 1) return 0;
    snprintf(id,cap,"sdl:pipewire:%s",i ? "Headphones" : "Speakers");
    snprintf(name,ncap,"%s",i ? "Headphones" : "Speakers");
    return 1;
}
int hos_sdl_output_resolve(const char *id) { return !strcmp(id,"sdl:pipewire:Headphones") ? 7 : -1; }
int main(void) {
    int count=hos_audio_output_count();
    printf("Linux playback count: %d (expected 2)\n",count); fflush(stdout);
    assert(count==2);
    char id[2048], name[1024], small[2];
    assert(hos_audio_output_info(1,id,sizeof id,name,sizeof name));
    assert(!strcmp(name,"Headphones") && !strcmp(id,"sdl:pipewire:Headphones"));
    assert(!hos_audio_output_info(2,id,sizeof id,name,sizeof name));
    assert(!hos_audio_output_info(1,small,sizeof small,name,sizeof name));
    assert(hos_audio_output_resolve("sdl:pipewire:Headphones")==7);
    assert(hos_audio_output_resolve("missing")==-1);
    puts("PASS Linux metadata bridge");
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    args = parser.parse_args()
    devices = (ROOT/'host/audio_output_devices.c').read_text(encoding='utf-8')
    devices = devices[devices.index('typedef struct { char *id, *name; } OutputDevice;'):]
    # (the stand-in's open, write and close: by the device, the stream closed with the handle, a gone device told)
    posix = (ROOT/'host/posix/win32_posix.c').read_text(encoding='utf-8')
    wave = posix[posix.index("/* ---- waveOut on SDL's audio"):]
    opened = wave[wave.index('MMRESULT waveOutOpen'):wave.index('MMRESULT waveOutPrepareHeader')]
    assert 'hos_sdl_audio_open_device(device,' in opened, 'waveOutOpen opens the device it is given'
    write = wave[wave.index('MMRESULT waveOutWrite'):wave.index('MMRESULT waveOutReset')]
    assert 'if (!hos_sdl_audio_alive(w->audio)) return MMSYSERR_NODRIVER;' in write
    close = wave[wave.index('MMRESULT waveOutClose'):]
    assert close.index('hos_sdl_audio_close(w->audio)') < close.index('pthread_mutex_destroy(&w->mu)') < close.index('free(w)')
    sdl = (ROOT/'host/hos_sdl.c').read_text(encoding='utf-8')
    channels = sdl[sdl.index('int hos_sdl_audio_channels(void) {'):]
    channels = channels[:channels.index('\n}')]
    assert 'playback_chosen_channels()' in channels, "the chosen device's channels on Linux"
    with tempfile.TemporaryDirectory(prefix='linux-audio-output-') as temporary:
        folder = Path(temporary)
        c = folder/'metadata.c'
        exe = folder/('metadata' + ('.exe' if sys.platform == 'win32' else ''))
        c.write_text(PREFIX + devices + METADATA, encoding='utf-8')
        subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-I', str(ROOT/'host'),
                        str(c), '-o', str(exe)], check=True, timeout=90)
        subprocess.run([str(exe)], check=True, timeout=20)
    print('ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
