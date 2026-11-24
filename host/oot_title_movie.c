/* OoT's title movie draw and its viewport share a thread; file handles and presents do not. */
#include "oot_title_movie.h"
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

extern volatile LONG64 hos_present_count;
void hos_log(const char *fmt, ...);

enum OotMovieFile oot_movie_file(const char *path) {
    const size_t n = strlen(path);
    if (n < 5 || _stricmp(path + n - 5, ".webm")) return OOT_MOVIE_NONE;
    const char *name = strchr(path, ':');
    name = name ? name + 1 : path;
    while (*name == '/') ++name;
    const char prefix[] = "Event/Movie/Dm_Title_";
    return !strncmp(name, prefix, sizeof prefix - 1) && !strchr(name + sizeof prefix - 1, '/')
           ? OOT_MOVIE_TITLE : OOT_MOVIE_OTHER;
}

static int title_only;
void oot_movie_file_change(enum OotMovieFile kind, int delta) {
    /* nn_fs holds handle_lock across each insertion and removal, including duplicate opens. */
    static int titles, others;
    if (kind == OOT_MOVIE_TITLE) titles += delta;
    else if (kind == OOT_MOVIE_OTHER) others += delta;
    else return;
    __atomic_store_n(&title_only, titles > 0 && others == 0, __ATOMIC_RELEASE);
}

static _Thread_local float pending_ratio;
static LONG64 last_draw = -1;
int hos_movie_cover_begin(float ratio) {
    pending_ratio = oot_title_cover_ratio(ratio) && __atomic_load_n(&title_only, __ATOMIC_ACQUIRE) ? ratio : 0;
    return pending_ratio != 0;
}

int hos_movie_cover_viewport(uint64_t *y, uint64_t *height) {
    if (!pending_ratio) return 0;
    const float ratio = pending_ratio;
    pending_ratio = 0;
    int32_t top = (int32_t)*y, h = (int32_t)*height;
    if (!oot_title_movie_cover(ratio, &top, &h)) return 0;
    *y = (uint32_t)top;
    *height = (uint32_t)h;
    __atomic_store_n(&last_draw, __atomic_load_n(&hos_present_count, __ATOMIC_RELAXED), __ATOMIC_RELEASE);
    return 1;
}

int oot_movie_cover_recent(void) {
    static int logged;
    const LONG64 draw = __atomic_load_n(&last_draw, __ATOMIC_ACQUIRE);
    const LONG64 now = __atomic_load_n(&hos_present_count, __ATOMIC_RELAXED);
    const int covered = draw >= 0 && now - draw <= 2;
    if (__atomic_exchange_n(&logged, covered, __ATOMIC_RELAXED) != covered)
        hos_log("wide: title movie cover %s", covered ? "on" : "off");
    return covered;
}

/* (Triforce) A menu over the filled movie (oot_title_movie.h). The menu screens' updates run on the game's threads, the
   question comes from the renderer's: the present it last ran at and its class, each written and read whole */
static LONG64 menu_ran = -1;
static LONG64 menu_class;
void oot_menu_screen_tick(uint64_t screen_class) {
    if (!oot_title_menu_class(screen_class)) return;
    __atomic_store_n(&menu_class, (LONG64)screen_class, __ATOMIC_RELAXED);
    __atomic_store_n(&menu_ran, __atomic_load_n(&hos_present_count, __ATOMIC_RELAXED), __ATOMIC_RELEASE);
}

int oot_menu_backdrop_runs(void) {
    return oot_menu_recent(__atomic_load_n(&hos_present_count, __ATOMIC_RELAXED), __atomic_load_n(&menu_ran, __ATOMIC_ACQUIRE));
}

int oot_menu_over_movie(void) {
    static int logged;
    const int over = oot_menu_backdrop_runs();
    /* (each change said, with the screen that told it: a report of a seam beside a menu at the title says which screen
       the menu was, or that none of the known ones ran) */
    if (__atomic_exchange_n(&logged, over, __ATOMIC_RELAXED) != over)
        hos_log("wide: a menu screen %s (class %#llx): menu sides %s", over ? "runs" : "has stopped",
                (unsigned long long)__atomic_load_n(&menu_class, __ATOMIC_RELAXED),
                over ? "as the Ultrawide menus row asks, over the title movie too" : "off again while the title movie fills the picture");
    return over;
}
