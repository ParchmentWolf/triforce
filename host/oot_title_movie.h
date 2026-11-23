#ifndef OOT_TITLE_MOVIE_H
#define OOT_TITLE_MOVIE_H

#include <stdint.h>

enum OotMovieFile { OOT_MOVIE_NONE, OOT_MOVIE_TITLE, OOT_MOVIE_OTHER };
enum OotMovieFile oot_movie_file(const char *path);
void oot_movie_file_change(enum OotMovieFile kind, int delta);
int hos_movie_cover_begin(float ratio);
int hos_movie_cover_viewport(uint64_t *y, uint64_t *height);
int oot_movie_cover_recent(void);

/* (Triforce) A game menu open over the title's filled movie. The filled movie has no menu sides (it is the picture, edge
   to edge), but a menu opened over it is drawn as in play: with the Insert menu's Ultrawide menus row on Centred its
   backdrop takes the middle 16:9, and the sides beside it are the renderer's (blurred or black). Seen in the game: with the
   sides off for the movie's sake the file select's blurred backdrop stood in the middle of the sharp movie, a seam at each
   side. So the title alone and a menu over it have to be told apart.
   What tells them apart is the game's own menu screens: every menu screen's update calls host/oot_menu.c each frame it
   runs (nx2/oot_patches.py patch_menu_tick), with the screen, whose first word is its class. The title's own list
   (0x84c106e8, Continue and the rest) is such a screen too and is the title, so "some menu screen runs" will not do.
   A menu over the title is one of:
   - the system menus' backdrop itself (host/oot_wide_hud.h's keep class 1), where it runs as a screen: the very thing
     that is drawn in the middle;
   - the screens the title's list opens: the file select, the chosen file's box (host/hos_bench.c names both), and the
     game's Options (host/oot_menu.c OPTIONS_SCREEN_VTABLE).
   None of them runs while the title alone shows, so the title cannot be taken for a menu. */
static inline int oot_title_menu_class(uint64_t screen_class) {
    return screen_class == 0x84c04fb0ULL ||   /* the pause and system menus' backdrop */
           screen_class == 0x84c0eba0ULL ||   /* the file select */
           screen_class == 0x84c0f840ULL ||   /* the chosen file's box */
           screen_class == 0x84c0f108ULL;     /* the game's Options */
}
/* host/oot_menu.c, each frame a menu screen runs: its class */
void oot_menu_screen_tick(uint64_t screen_class);
/* 1 while such a menu ran within the last OOT_MENU_PRESENTS presents of the game (its screens run once a frame; a frame
   or two can pass between a screen's last update and the last picture that shows it) */
#define OOT_MENU_PRESENTS 3
int oot_menu_over_movie(void);
/* The same without a word in the log: for the renderer, which asks whether the blur of the last picture it sees drawn is
   such a menu's centred backdrop or the item wheel's whole one (MkwVkHost.wide_backdrop, gpu/vk/wide_sides_rule.h). The
   item wheel is play's: none of these screens runs with it */
int oot_menu_backdrop_runs(void);
static inline int oot_menu_recent(int64_t now, int64_t ran) { return ran >= 0 && now - ran <= OOT_MENU_PRESENTS; }

/* The menu sides' margin the renderer is given (MkwVkHost.wide_menus, host/rx_backend.c): none while the filled title
   movie alone shows; the picture's own (hos_wide_margin) in play, and with a menu open over the movie */
static inline float oot_wide_menu_margin(float margin, int movie_covers, int menu_over_it) {
    return movie_covers && !menu_over_it ? 0.0f : margin;
}

static inline int oot_title_cover_ratio(float ratio) {
    /* Allow the same 1% tolerance as the output shape check: picture widths round to 8 pixels. */
    return ratio > 16.0f / 9.0f && ratio <= (12.0f / 5.0f) * 1.01f;
}

/* The SetViewport site at main+0x284824 passes y and height in target pixels and the picture's
   hos_wide_ratio. Return 1 with the viewport grown and centred, or 0 with both values untouched.
   At 12:5 the crop still shows 800 of 1080 lines; beyond it keep the whole movie in the middle. */
static inline int oot_title_movie_cover(float ratio, int32_t *y, int32_t *height) {
    if (!oot_title_cover_ratio(ratio) || *height <= 0)
        return 0;
    const int64_t covered = (int64_t)((double)*height * ratio * 9 / 16 + 0.5);
    const int64_t top = (int64_t)*y - (covered - *height) / 2;
    if (covered > INT32_MAX || top < INT32_MIN)
        return 0;
    *y = (int32_t)top;
    *height = (int32_t)covered;
    return 1;
}

#endif
