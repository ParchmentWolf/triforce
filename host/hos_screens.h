/* (Triforce) The connected screens, as the game's window code finds them at the start (host/display.c on Windows,
   host/posix/display_sdl.c with SDL elsewhere), for the Output resolution: host/nn_applet.c takes the size of the one the
   window opens on for the old Screen value, and the Insert menu lists each one's size as a choice (MkwVkHost.screens,
   host/rx_backend.c). Sizes are native pixels. A screen is told to the player by its size and its name; nothing keeps its
   place in this list, which changes as screens are plugged in. */
#pragma once

typedef struct HosScreen {
    int w, h;        /* (pixels) */
    int opens;       /* (1: the game's window opens on this one) */
    char name[64];   /* (the monitor's own name, UTF-8, "" where the system has none: a laptop's panel) */
} HosScreen;

/* The connected screens, at most cap of them: how many were written (0: none known, a run with no window) */
int hos_screens(HosScreen *out, int cap);
/* The size of the one the window opens on, 0 x 0 when it is not known */
void hos_screen_size(int *w, int *h);
