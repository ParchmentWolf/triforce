/* (triforce) A bug capture: F8 in the game's window (host/display.c), or the System tab's Bug capture row, writes one folder a
   player can send with a problem report, captures/<date>-<time> in the game folder:

     frame.png              the frame the window was shown next, without the overlays (gpu/vk/vk_bugshot.cpp)
     triforce_options.ini   the settings
     Triforce-save-....zip  the save, as the System tab's Export save writes it (host/save_share.c)
     log-tail.txt           the last 400 lines of triforce_log.txt
     triforce_log.1.txt     ((Triforce) 11-24) the run before's log, where the game folder has it (the crashed run's, after a
                            start again), whole up to 10 MB (a longer one: its first MB and its last 9)
     capture.txt            written last, so a folder that has it is whole: the build, the CPU, RAM and system, the GPU and
                            its driver as the log's first lines name them, the game's frames shown so far, the frame rate
                            before the press, the map and Link's place when he is in play, the first sign of trouble in
                            this run's log and the run before's, the options changed from their defaults as the Insert
                            menu shows them, and the switches set

   Nothing of it is sent anywhere, and nothing is opened: the player sends the folder with a problem report himself. The logs'
   copies leave out the home folder and the user's name (host/log_redact.h), and a switch's value is written only where it
   cannot hold anything private (switch_value_shown).

   The behaviour is NX2navi's F8 (its docs/bug-capture.md). Its code is another author's and none of it is here; this is
   written for Triforce from what that page says a capture holds.

   Nothing of the file work is done where the key is pressed: the press only notes the time and the frame count, asks the
   renderer for the next frame's picture (rx_option_set HOS_OPT_BUG_SHOT) and wakes the save rows' thread, which writes
   the folder (hos_bug_capture_work) while the game goes on. One capture at a time: a press while one is being written is
   skipped, and said in the log.

   The map and Link's place come from what the game's own thread says when asked "where" (host/hos_main.c
   hos_oot_live_crawl, the lab's command: Sequence_CurrentBanc and the player's position, read there on the thread that
   updates him). It answers in the log within a frame while Link is in play, and the capture reads that line back: the
   first one after the line the press itself logged, which is in the log before the question is asked. At the title
   screen or in a loading screen there is no answer and capture.txt says so. The camera is not in a capture: nothing of
   the host reads it outside the debug tools' free camera.

   The frame rate is counted from the game's own presents (hos_present_count), which the save rows' thread notes ten times a
   second (hos_bug_capture_tick). */
#include "hos_paths.h"   /* (first: hos_game_path_a, and windows.h on Windows) */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "../gpu/vk/vk_api.h"
#include "log_redact.h"   /* ((Triforce) 11-24: the log's copy without the player's home folder and user name) */
#include <sys/stat.h>
#if defined(_WIN32) && (defined(__x86_64__) || defined(__i386__))
#include <intrin.h>   /* (the CPU's name: __cpuid) */
#elif defined(__x86_64__) || defined(__i386__)
#include <cpuid.h>
#endif
#ifndef _WIN32
#include <sys/utsname.h>
#include <unistd.h>
extern char **environ;
#endif

#ifdef _WIN32
#define SEP "\\"
#else
#define SEP "/"
#endif
#define CAPTURE_PATH 1024
#define TAIL_LINES 400
#define TAIL_BYTES (512u << 10)   /* (400 of the log's lines are well under this) */
#define HEAD_BYTES (64u << 10)    /* (the build, the GPUs and the driver are in the log's first hundred lines) */
#define SHOT_WAIT_MS 3000         /* (the picture is there three presents after the press; a game that shows no frame has none) */
#define TICKS 128                 /* (a tenth of a second each: the twelve seconds before a press) */

void hos_log(const char *fmt, ...);
void hos_log_flush(void);
int rx_option(int id, int otherwise);
void rx_option_set(int id, int value);
const char *hos_version(void);                  /* hos_main.c */
void hos_oot_live_crawl(const char *line);      /* hos_main.c: "!where" */
int hos_binding(int set, int button, int slot); /* nn_hid.c */
extern volatile LONG64 hos_present_count;       /* display.c, posix/display_sdl.c: the game's presents */
/* save_share.c */
int hos_share_game_dir(char *out, size_t cap);
int hos_save_export(const char *dir, int bug_report, char *path, size_t cap, int *files);
void hos_save_share_start(void);
void hos_save_share_wake(void);
void hos_save_share_say(int row, const char *text);

/* ---- the press ---- */
static volatile LONG capture_state;   /* 0 none, 1 asked: the thread has it to write, 2 being written, 3 a press is noting itself */
static struct {
    int number;   /* (the run's first capture is 1: what its lines in the log are told apart by) */
    char trigger[40];
    LONG64 presents;
    time_t when;
    ULONGLONG tick;
} asked;

/* A capture is asked for (any thread; trigger: what asked, for the log). 1: it will be written; 0: one is under way */
int hos_bug_capture_ask(const char *trigger) {
    if (InterlockedCompareExchange(&capture_state, 3, 0) != 0) {
        hos_log("capture: %s: skipped, the capture before it is still being written", trigger);
        return 0;
    }
    static int count;   /* (one press at a time gets here: capture_state) */
    asked.number = ++count;
    snprintf(asked.trigger, sizeof asked.trigger, "%s", trigger);
    asked.presents = InterlockedCompareExchange64(&hos_present_count, 0, 0);
    asked.when = time(NULL);
    asked.tick = GetTickCount64();
    /* (in the log before the game's thread is asked where Link is: its answer is the first one after this line) */
    hos_log("capture: bug capture %d asked for (%s) at present %lld", asked.number, trigger, (long long)asked.presents);
    rx_option_set(HOS_OPT_BUG_SHOT, 1);   /* (the frame shown next) */
#if defined(_WIN32) || defined(__linux__)   /* (the debug tools' side of hos_main.c: as there) */
    hos_oot_live_crawl("!where");   /* (the game's thread says the map and Link's place in the log, while he is in play) */
#endif
    InterlockedExchange(&capture_state, 1);
    hos_save_share_start();
    hos_save_share_wake();
    return 1;
}

/* F8 in the game's window. Not when the player bound F8 to one of the controls (none is by default): the key is the
   game's then, and the System tab's row still takes a capture */
void hos_bug_capture_key(void) {
    for (int button = 0; button < HOS_KEY_N; button++)
        for (int slot = 0; slot < 2; slot++)
            if (hos_binding(HOS_BIND_KEY, button, slot) == VK_F8) {
                static volatile LONG said;
                if (!InterlockedExchange(&said, 1))
                    hos_log("capture: F8 is bound to one of the controls: no capture from the key (the System tab's Bug capture row takes one)");
                return;
            }
    hos_bug_capture_ask("F8");
}

/* ---- the frames shown, a tenth of a second at a time (the save rows' thread, each time round) ---- */
static struct {
    ULONGLONG ms;
    LONG64 presents;
} ticks[TICKS];
static unsigned tick_n;

void hos_bug_capture_tick(void) {
    const ULONGLONG now = GetTickCount64();
    if (tick_n && now - ticks[(tick_n - 1) % TICKS].ms < 50) return;   /* (woken early: not a tenth of a second yet) */
    ticks[tick_n % TICKS].ms = now;
    ticks[tick_n % TICKS].presents = InterlockedCompareExchange64(&hos_present_count, 0, 0);
    tick_n++;
}

/* The frame rate over the span_ms before the press (span_ms > 0): from the newest tick that far back to the press itself,
   whose own count and time the press noted; -1 when the ticks do not reach that far back */
static double rate_before(unsigned span_ms) {
    const unsigned kept = tick_n < TICKS ? tick_n : TICKS;
    for (unsigned k = 0; k < kept; k++) {   /* (newest first) */
        const unsigned i = (tick_n - 1 - k) % TICKS;
        if (ticks[i].ms + span_ms > asked.tick || ticks[i].presents > asked.presents) continue;
        return (double)(asked.presents - ticks[i].presents) * 1000.0 / (double)(asked.tick - ticks[i].ms);
    }
    return -1;
}

/* ---- files ---- */
/* Up to max bytes of a file, from its start or its end: malloc'd with a NUL after them, NULL when it is not there */
static char *read_part(const char *path, size_t max, int from_end, size_t *n) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    _fseeki64(f, 0, SEEK_END);
    const long long size = _ftelli64(f);
    const size_t want = size < 0 ? 0 : (unsigned long long)size > max ? max : (size_t)size;
    char *data = (char *)malloc(want + 1);
    _fseeki64(f, from_end ? size - (long long)want : 0, SEEK_SET);
    *n = data ? fread(data, 1, want, f) : 0;
    fclose(f);
    if (data) data[*n] = 0;
    return data;
}

static int write_file(const char *path, const void *data, size_t n) {
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    const size_t put = fwrite(data, 1, n, f);
    return !fclose(f) && put == n;
}

/* Where the last `lines` lines of text[0..n) begin */
static const char *last_lines(const char *text, size_t n, int lines) {
    const char *p = text + n;
    if (p > text && p[-1] == '\n') p--;   /* (the last line's own end) */
    while (p > text) {
        if (p[-1] == '\n' && --lines == 0) break;
        p--;
    }
    return p;
}

/* A line of the log without its "[hos <thread>] " and its end, into out. Returns the line after it */
static const char *log_line(const char *line, char *out, size_t cap) {
    const char *end = strchr(line, '\n');
    if (!end) end = line + strlen(line);
    const char *from = line;
    if (!strncmp(line, "[hos ", 5)) {
        const char *close = strstr(line, "] ");
        if (close && close < end) from = close + 2;
    }
    size_t len = (size_t)(end - from);
    while (len && (from[len - 1] == '\r' || from[len - 1] == ' ')) len--;
    snprintf(out, cap, "%.*s", (int)len, from);
    return *end ? end + 1 : end;
}

/* ---- ((Triforce) 11-24) what a problem report asks for besides: the PC, the first sign of trouble in a log, the run
   before's log, the options changed and the switches set ---- */
static void add(char *out, size_t cap, const char *fmt, ...) {
    const size_t len = strlen(out);
    if (len + 1 >= cap) return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(out + len, cap - len, fmt, ap);
    va_end(ap);
}

/* The CPU (cpuid's own name for it, the same on every system) and its threads, and the RAM: "AMD Ryzen 7 5800X3D 8-Core
   Processor (16 threads), 32 GB" */
static void cpu_text(char *out, size_t cap) {
    char name[49] = "";
#if defined(__x86_64__) || defined(__i386__)
    unsigned r[12] = {0};
#ifdef _WIN32
    int v[4];
    __cpuid(v, (int)0x80000000);
    if ((unsigned)v[0] >= 0x80000004u)
        for (int k = 0; k < 3; k++) __cpuid((int *)&r[k * 4], (int)(0x80000002u + (unsigned)k));
#else
    unsigned a, b, c, d;
    if (__get_cpuid(0x80000000u, &a, &b, &c, &d) && a >= 0x80000004u)
        for (unsigned k = 0; k < 3; k++) __get_cpuid(0x80000002u + k, &r[k * 4], &r[k * 4 + 1], &r[k * 4 + 2], &r[k * 4 + 3]);
#endif
    memcpy(name, r, 48);
#endif
    const char *p = name;
    while (*p == ' ') p++;
    size_t n = strlen(p);
    while (n && p[n - 1] == ' ') n--;
    unsigned threads = 0;
    unsigned long long ram = 0;
#ifdef _WIN32
    threads = (unsigned)GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    MEMORYSTATUSEX m;
    memset(&m, 0, sizeof m);
    m.dwLength = sizeof m;
    if (GlobalMemoryStatusEx(&m)) ram = m.ullTotalPhys;
#else
    const long online = sysconf(_SC_NPROCESSORS_ONLN), pages = sysconf(_SC_PHYS_PAGES), page = sysconf(_SC_PAGE_SIZE);
    threads = online > 0 ? (unsigned)online : 0;
    if (pages > 0 && page > 0) ram = (unsigned long long)pages * (unsigned long long)page;
#endif
    out[0] = 0;
    if (n) add(out, cap, "%.*s", (int)n, p);
    else add(out, cap, "an unknown CPU");
    if (threads) add(out, cap, " (%u threads)", threads);
    if (ram) add(out, cap, ", %llu GB", (ram + (1ull << 29)) >> 30);
}

/* The system: "Windows 11 (build 26100)" (and ", Wine 9.0" under Wine), "Arch Linux (Linux 6.12.1), KDE (wayland)" (and
   ", the AppImage" when it runs from one) */
static void os_text(char *out, size_t cap) {
    out[0] = 0;
#ifdef _WIN32
    {   /* (RtlGetVersion: GetVersionEx answers as the program's manifest allows) */
        typedef LONG(WINAPI * GetVersionFn)(OSVERSIONINFOW *);
        typedef const char *(__cdecl * WineFn)(void);
        const HMODULE nt = GetModuleHandleA("ntdll.dll");
        const GetVersionFn get = nt ? (GetVersionFn)(void *)GetProcAddress(nt, "RtlGetVersion") : NULL;
        OSVERSIONINFOW v;
        memset(&v, 0, sizeof v);
        v.dwOSVersionInfoSize = sizeof v;
        if (get && get(&v) == 0) {
            if (v.dwMajorVersion == 10) add(out, cap, v.dwBuildNumber >= 22000 ? "Windows 11" : "Windows 10");
            else add(out, cap, "Windows %lu.%lu", (unsigned long)v.dwMajorVersion, (unsigned long)v.dwMinorVersion);
            add(out, cap, " (build %lu)", (unsigned long)v.dwBuildNumber);
        } else {
            add(out, cap, "Windows");
        }
        const WineFn wine = nt ? (WineFn)(void *)GetProcAddress(nt, "wine_get_version") : NULL;
        if (wine) add(out, cap, ", Wine %s", wine());
    }
#else
    static const char *const files[] = {"/etc/os-release", "/usr/lib/os-release"};
    for (size_t i = 0; i < sizeof files / sizeof *files && !out[0]; i++) {
        FILE *f = fopen(files[i], "r");
        if (!f) continue;
        char line[256];
        while (fgets(line, sizeof line, f)) {
            if (strncmp(line, "PRETTY_NAME=", 12)) continue;
            char *v = line + 12;
            size_t n = strlen(v);
            while (n && (v[n - 1] == '\n' || v[n - 1] == '\r' || v[n - 1] == ' ')) n--;
            if (n >= 2 && (v[0] == '"' || v[0] == '\'') && v[n - 1] == v[0]) v++, n -= 2;
            out[0] = 0;
            add(out, cap, "%.*s", (int)n, v);
        }
        fclose(f);
    }
    if (!out[0]) add(out, cap, "Linux");
    struct utsname u;
    if (!uname(&u)) add(out, cap, " (%s %s)", u.sysname, u.release);
    /* (the desktop and its display protocol: what a window problem depends on; gamescope is a Steam Deck's Game Mode) */
    const char *desktop = getenv("XDG_CURRENT_DESKTOP"), *session = getenv("XDG_SESSION_TYPE");
    if (desktop && *desktop) {
        add(out, cap, ", %s", desktop);
        if (session && *session) add(out, cap, " (%s)", session);
    }
    if (getenv("APPIMAGE")) add(out, cap, ", the AppImage");
#endif
}

/* The first sign of trouble in a log (a crash, a fatal error, the GPU's device lost), without the line's "[hos <thread>] ",
   cut to 300 bytes and redacted; "" when there is none. Read a line at a time: a log can be long */
static void first_trouble(const char *path, char *out, size_t cap) {
    out[0] = 0;
    FILE *f = fopen(path, "rb");
    if (!f) return;
    char line[4096];
    while (fgets(line, sizeof line, f)) {
        if (!strstr(line, "CRASH:") && !strstr(line, "FATAL:") && !strstr(line, "device lost")) continue;
        char bare[400];
        log_line(line, bare, 301);
        hos_log_redact(out, cap, bare);
        break;
    }
    fclose(f);
}

/* The run before's log, copied as it is up to 10 MB (a longer one: its first MB, where the start, the GPU and the options
   are, and its last 9 MB, where the problem usually is), the home folder and the user's name left out. *size: the log's
   size; *when: when it was last written; version: the build its first line names. 1: copied */
#define BEFORE_CAP (10ull << 20)
#define BEFORE_HEAD (1ull << 20)
static int copy_log_before(const char *from, const char *to, unsigned long long *size, time_t *when, char *version, size_t vcap) {
    *size = 0, *when = 0, version[0] = 0;
#ifdef _WIN32
    struct _stat64 st;
    if (_stat64(from, &st)) return 0;
#else
    struct stat st;
    if (stat(from, &st)) return 0;
#endif
    *size = (unsigned long long)st.st_size, *when = st.st_mtime;
    size_t hn = 0, tn = 0;
    const int cut = *size > BEFORE_CAP;
    char *head = read_part(from, cut ? (size_t)BEFORE_HEAD : (size_t)BEFORE_CAP, 0, &hn);
    if (!head) return 0;
    char *tail = cut ? read_part(from, (size_t)(BEFORE_CAP - BEFORE_HEAD), 1, &tn) : NULL;
    if (cut && !tail) {
        free(head);
        return 0;
    }
    {   /* (its build: the first line that names it, "[hos host] triforce <version>") */
        const char *v = strstr(head, "] triforce ");
        if (v) {
            char bare[200];
            log_line(v + 2, bare, sizeof bare);
            snprintf(version, vcap, "%s", bare + strlen("triforce "));
        }
    }
    size_t n = hn;
    if (cut) {   /* (whole lines either side of what is left out, and a line that says so) */
        while (hn && head[hn - 1] != '\n') hn--;
        const char *t = memchr(tail, '\n', tn);
        const size_t skip = t ? (size_t)(t + 1 - tail) : 0;
        char said[200];
        const int sn = snprintf(said, sizeof said, "[bug capture: %.1f MB of this log's middle left out here: the copy keeps its first and its last part]\n",
                                (double)(*size - hn - (tn - skip)) / 1048576.0);
        char *whole = (char *)malloc(hn + (size_t)sn + (tn - skip) + 1);
        if (!whole) {
            free(head), free(tail);
            return 0;
        }
        memcpy(whole, head, hn);
        memcpy(whole + hn, said, (size_t)sn);
        memcpy(whole + hn + (size_t)sn, tail + skip, tn - skip);
        n = hn + (size_t)sn + (tn - skip);
        whole[n] = 0;
        free(head), free(tail);
        head = whole;
    }
    size_t clean_n = 0;
    char *clean = hos_log_redact_text(head, n, &clean_n);
    const int ok = clean && write_file(to, clean, clean_n);
    free(clean);
    free(head);
    return ok;
}

/* Whether a switch's value goes into capture.txt. triforce_env.txt is a player's own file, so only a value that cannot hold
   anything private is written: a number of at most 12 characters (60, -1, 1.5), a size (1920x1080), or on/off, true/false,
   yes/no; and never for a name that may hold a secret, a place or a person (TOKEN, KEY, ROOM, SECRET, PASS, SERVER or USER
   in it). Every other value is left out, paths and addresses with them */
static int switch_value_shown(const char *name, const char *value) {
    static const char *const secret[] = {"TOKEN", "KEY", "ROOM", "SECRET", "PASS", "SERVER", "USER"};
    static const char *const words[] = {"", "on", "off", "true", "false", "yes", "no"};
    char upper[128], lower[16];
    size_t i;
    for (i = 0; name[i] && i + 1 < sizeof upper; i++) upper[i] = (char)(name[i] >= 'a' && name[i] <= 'z' ? name[i] - 32 : name[i]);
    upper[i] = 0;
    for (i = 0; i < sizeof secret / sizeof *secret; i++)
        if (strstr(upper, secret[i])) return 0;
    const size_t n = strlen(value);
    if (n > 12) return 0;
    for (i = 0; i < n; i++) lower[i] = (char)(value[i] >= 'A' && value[i] <= 'Z' ? value[i] + 32 : value[i]);
    lower[n] = 0;
    for (i = 0; i < sizeof words / sizeof *words; i++)
        if (!strcmp(lower, words[i])) return 1;
    size_t at = value[0] == '-' ? 1 : 0, from = at;
    while (at < n && value[at] >= '0' && value[at] <= '9') at++;
    if (at == from) return 0;
    if (at == n) return 1;   /* (a whole number) */
    const char mid = value[at++];
    if (mid != '.' && !(mid == 'x' && value[0] != '-')) return 0;
    from = at;
    while (at < n && value[at] >= '0' && value[at] <= '9') at++;
    return at > from && at == n;   /* (1.5, 1920x1080) */
}

/* Whether a variable of the environment is a switch for capture.txt: the game's own (host/hos_main.c env_line_allowed's
   prefixes, and TRIFORCE_), a driver's (RADV_, MESA_), and what loads other code into the game (a problem report asks about
   software hooked in: overlays, layers, a preload) */
static int switch_wanted(const char *name, size_t n) {
    static const char *const prefixes[] = {"RX_", "HOS_", "HOOKSHOT_", "TRIFORCE_", "EDEN_", "NVN_", "TOTK_", "SDL_", "RADV_", "MESA_"};
    static const char *const hooks[] = {"VK_INSTANCE_LAYERS", "VK_LOADER_LAYERS_ENABLE", "VK_DRIVER_FILES", "VK_ICD_FILENAMES",
                                        "ENABLE_VKBASALT", "MANGOHUD", "LD_PRELOAD", "DXVK_HUD"};
    for (size_t i = 0; i < sizeof prefixes / sizeof *prefixes; i++)
        if (n > strlen(prefixes[i]) && !strncmp(name, prefixes[i], strlen(prefixes[i]))) return 1;
    for (size_t i = 0; i < sizeof hooks / sizeof *hooks; i++)
        if (n == strlen(hooks[i]) && !strncmp(name, hooks[i], n)) return 1;
    return 0;
}
static int by_name(const void *a, const void *b) { return strcmp(*(const char *const *)a, *(const char *const *)b); }

/* The switches set, "  NAME=VALUE" a line each in the order of their names, the value as switch_value_shown allows. The
   number of them */
#define SWITCHES_MAX 256
static int write_switches(FILE *f) {
    char *list[SWITCHES_MAX];
    int count = 0;
#ifdef _WIN32
    char *block = GetEnvironmentStringsA();   /* (NAME=VALUE\0 ... \0\0; host/hos_main.c's _putenv of triforce_env.txt reaches it) */
    for (const char *e = block; e && *e && count < SWITCHES_MAX; e += strlen(e) + 1) {
#else
    for (char **env = environ; env && *env && count < SWITCHES_MAX; env++) {
        const char *e = *env;
#endif
        const char *eq = strchr(e, '=');
        if (!eq || eq == e || !switch_wanted(e, (size_t)(eq - e))) continue;
        char name[128];
        snprintf(name, sizeof name, "%.*s", (int)(eq - e), e);
        const char *value = switch_value_shown(name, eq + 1) ? eq + 1 : "(value left out)";
        const size_t len = strlen(name) + 1 + strlen(value) + 1;
        if (!(list[count] = (char *)malloc(len))) break;
        snprintf(list[count++], len, "%s=%s", name, value);
    }
#ifdef _WIN32
    if (block) FreeEnvironmentStringsA(block);
#endif
    qsort(list, (size_t)count, sizeof *list, by_name);
    if (!count) fprintf(f, "switches set = none\n");
    else
        fprintf(f, "switches set = %d (the environment and triforce_env.txt; a value only where it is a number, a size or on/off, and never for "
                   "a name with TOKEN, KEY, ROOM, SECRET, PASS, SERVER or USER in it)\n", count);
    for (int i = 0; i < count; i++) fprintf(f, "  %s\n", list[i]), free(list[i]);
    return count;
}

/* The Insert menu's rows that are not at their defaults, as it shows them (gpu/vk/vk_menu.cpp, HOS_OPT_BUG_SETTINGS), a
   byte at a time; NULL when the renderer has none to give (the WebGPU renderer, an older renderer) */
#define SETTINGS_MAX (64u << 10)
static char *renderer_settings(void) {
    rx_option_set(HOS_OPT_BUG_SETTINGS, 1);
    char *text = (char *)malloc(SETTINGS_MAX + 1);
    size_t n = 0;
    int b = 1;
    while (text && n < SETTINGS_MAX && (b = rx_option(HOS_OPT_BUG_SETTINGS, 0)) > 0) text[n++] = (char)b;
    for (int k = 0; b > 0 && k < (1 << 20) && rx_option(HOS_OPT_BUG_SETTINGS, 0) > 0; k++) {}   /* (the rest, so the next capture's begins anew) */
    if (text) text[n] = 0;
    if (text && !n) free(text), text = NULL;
    return text;
}

/* ---- the capture, on the save rows' thread ---- */
void hos_bug_capture_work(void) {
    if (InterlockedCompareExchange(&capture_state, 2, 1) != 1) return;
    const ULONGLONG began = GetTickCount64();
    char game[MAX_PATH], name[48], dir[CAPTURE_PATH], path[CAPTURE_PATH + 64], other[CAPTURE_PATH + 64], line[CAPTURE_PATH + 200];
    struct tm local, utc;
    localtime_s(&local, &asked.when);
    gmtime_s(&utc, &asked.when);
    int made = 0;
    if (hos_share_game_dir(game, sizeof game)) {
        snprintf(dir, sizeof dir, "%s" SEP "captures", game);
        CreateDirectoryA(dir, NULL);
        for (int k = 1; k < 100 && !made; k++) {   /* (two in one second: "-2") */
            const int len = snprintf(name, sizeof name, k == 1 ? "%04d%02d%02d-%02d%02d%02d" : "%04d%02d%02d-%02d%02d%02d-%d", local.tm_year + 1900,
                                     local.tm_mon + 1, local.tm_mday, local.tm_hour, local.tm_min, local.tm_sec, k);
            if (len < 0 || snprintf(dir, sizeof dir, "%s" SEP "captures" SEP "%s", game, name) >= (int)sizeof dir) break;
            made = CreateDirectoryA(dir, NULL) != 0;
        }
    }
    if (!made) {
        rx_option_set(HOS_OPT_BUG_SHOT, 0);
        hos_log("capture: bug capture %d: no folder could be made under the game folder's captures: nothing was written", asked.number);
        hos_save_share_say(HOS_SHARE_CAPTURE, "The capture's folder could not be made in the game folder: nothing was written.");
        InterlockedExchange(&capture_state, 0);
        return;
    }
    hos_log("capture: bug capture %d goes to %s", asked.number, dir);   /* (the one line that says where) */

    /* the settings, and the save as Export save writes it */
    size_t n = 0;
    snprintf(path, sizeof path, "%s" SEP "triforce_options.ini", game);
    char *ini = read_part(path, 1u << 20, 0, &n);
    snprintf(path, sizeof path, "%s" SEP "triforce_options.ini", dir);
    const int have_ini = ini && write_file(path, ini, n);
    free(ini);
    int files = 0;
    char zip[CAPTURE_PATH + 64];
    const int have_save = hos_save_export(dir, 0, zip, sizeof zip, &files);

    /* the picture: the renderer writes it once the frame it copied is done */
    int shot = 1;
    for (unsigned waited = 0; waited < SHOT_WAIT_MS && (shot = rx_option(HOS_OPT_BUG_SHOT, 3)) == 1; waited += 20) Sleep(20);
    if (shot == 1) rx_option_set(HOS_OPT_BUG_SHOT, 0);   /* (no frame was shown in that time: asked no longer) */
    snprintf(other, sizeof other, "%s" SEP "captures" SEP "frame-pending.png", game);
    snprintf(path, sizeof path, "%s" SEP "frame.png", dir);
    const int have_picture = shot == 2 && MoveFileExA(other, path, MOVEFILE_REPLACE_EXISTING) != 0;

    /* the log: its end as log-tail.txt, and in it what the game's thread said of Link's place since the press */
    while (GetTickCount64() - asked.tick < 300) Sleep(20);   /* (a few frames, for that answer) */
    hos_log_flush();
    char place[400] = "";
    snprintf(path, sizeof path, "%s" SEP "triforce_log.txt", game);
    char *tail = read_part(path, TAIL_BYTES, 1, &n);
    int have_log = 0;
    if (tail) {
        const char *from = last_lines(tail, n, TAIL_LINES);
        snprintf(other, sizeof other, "%s" SEP "log-tail.txt", dir);
        {   /* ((Triforce) 11-24: the copy without the player's home folder and user name, the lines other code wrote to
               stderr itself too (the game's own are written without them already: host/log_redact.h). Without memory for
               it, as it is) */
            size_t clean_n = 0;
            char *clean = hos_log_redact_text(from, (size_t)(tail + n - from), &clean_n);
            have_log = clean ? write_file(other, clean, clean_n) : write_file(other, from, (size_t)(tail + n - from));
            free(clean);
        }
        char mark[64];   /* (the press's own line: a capture's number is the run's, and the log is the run's) */
        snprintf(mark, sizeof mark, "capture: bug capture %d asked for (", asked.number);
        const char *mine = NULL;
        for (const char *p = tail; (p = strstr(p, mark)) != NULL; p++) mine = p;
        const char *where = mine ? strstr(mine, "cheats: crawl: where: ") : NULL;
        if (where) log_line(where + strlen("cheats: crawl: where: "), place, sizeof place);
    }

    /* ((Triforce) 11-24) the run before's log (the crashed run's, after a start again: host/hos_main.c keeps it as
       triforce_log.1.txt), the first sign of trouble in each log, the options changed, the PC */
    char before_version[80], trouble[400], trouble_before[400] = "", cpu[200], os[300];
    unsigned long long before_size = 0;
    time_t before_when = 0;
    snprintf(path, sizeof path, "%s" SEP "triforce_log.1.txt", game);
    snprintf(other, sizeof other, "%s" SEP "triforce_log.1.txt", dir);
    const int have_before = copy_log_before(path, other, &before_size, &before_when, before_version, sizeof before_version);
    if (have_before) first_trouble(path, trouble_before, sizeof trouble_before);
    snprintf(path, sizeof path, "%s" SEP "triforce_log.txt", game);
    first_trouble(path, trouble, sizeof trouble);
    char *settings = renderer_settings();
    cpu_text(cpu, sizeof cpu);
    os_text(os, sizeof os);

    /* capture.txt, last */
    snprintf(path, sizeof path, "%s" SEP "capture.txt.part", dir);
    FILE *f = fopen(path, "wb");
    if (f) {
        fprintf(f, "Triforce bug capture %s\n\n", name);
        fprintf(f, "time = %04d-%02d-%02d %02d:%02d:%02d (%04d-%02d-%02dT%02d:%02d:%02dZ)\n", local.tm_year + 1900, local.tm_mon + 1, local.tm_mday,
                local.tm_hour, local.tm_min, local.tm_sec, utc.tm_year + 1900, utc.tm_mon + 1, utc.tm_mday, utc.tm_hour, utc.tm_min, utc.tm_sec);
        fprintf(f, "trigger = %s\n", asked.trigger);
        fprintf(f, "version = %s\n", hos_version());
        fprintf(f, "cpu = %s\n", cpu);   /* ((Triforce) 11-24: what a problem report asks for, beside the GPU below) */
        fprintf(f, "system = %s\n", os);
        /* (the build, the GPUs and the driver, as the log's first lines give them) */
        snprintf(other, sizeof other, "%s" SEP "triforce_log.txt", game);
        size_t hn = 0;
        char *head = read_part(other, HEAD_BYTES, 0, &hn);
        int head_lines = 0;
        for (const char *p = head; p && *p && head_lines < 24;) {
            static const char *const says[] = {"] triforce ", "vk: device ", "; mesh shaders ", "vk: vendor fixes", "rx: renderer:",
                                               "oe: output resolution", "vk: swapchain ", "vk: HDR:"};
            const char *end = strchr(p, '\n');
            const size_t len = end ? (size_t)(end - p) : strlen(p);
            for (size_t i = 0; i < sizeof says / sizeof *says; i++) {
                const char *hit = strstr(p, says[i]);
                if (!hit || hit >= p + len) continue;
                log_line(p, line, sizeof line);
                fprintf(f, "log = %s\n", line);
                head_lines++;
                break;
            }
            p = end ? end + 1 : p + len;
        }
        if (!head) fprintf(f, "log = none (triforce_log.txt is not in the game folder: the game was started with its output sent elsewhere)\n");
        free(head);
        fprintf(f, "\npresents = %lld (the game's frames shown up to the press)\n", (long long)asked.presents);
        const double second = rate_before(1000), ten = rate_before(10000);
        if (second >= 0) fprintf(f, "frame rate = %.1f a second over the second before the press\n", second);
        else fprintf(f, "frame rate = not known (the press came in the game's first second)\n");
        if (ten >= 0) fprintf(f, "frame rate, ten seconds = %.1f a second\n", ten);
        {   /* (the last three seconds a tenth at a time, oldest first: a stutter shows as a low count. A span that was not a
               tenth, the thread busy with an export or woken early, is written with its length) */
            const unsigned kept = tick_n < TICKS ? tick_n : TICKS;
            int shown = 0;
            fprintf(f, "frames each tenth of a second before the press =");
            for (unsigned k = kept < 31 ? kept : 31; k >= 2; k--) {
                const unsigned a = (tick_n - k) % TICKS, b = (tick_n - k + 1) % TICKS;
                if (ticks[b].ms >= asked.tick || ticks[b].presents > asked.presents) break;   /* (at the press, or after it) */
                const ULONGLONG span = ticks[b].ms - ticks[a].ms;
                if (span >= 80 && span <= 125) fprintf(f, " %lld", (long long)(ticks[b].presents - ticks[a].presents));
                else fprintf(f, " %lld/%llums", (long long)(ticks[b].presents - ticks[a].presents), (unsigned long long)span);
                shown++;
            }
            fprintf(f, shown ? "\n" : " not known\n");
        }
        if (place[0]) fprintf(f, "\nplace = %s\n", place);
        else fprintf(f, "\nplace = not known (Link is not in play: the title screen, a menu before a save is loaded, or a loading screen)\n");
        fprintf(f, "camera = not in a capture\n\n");
        if (have_picture) fprintf(f, "picture = frame.png (the frame shown after the press, without the overlays)\n");
        else
            fprintf(f, "picture = none (%s)\n", shot == 1 ? "no frame was shown in three seconds"
                                                          : "the renderer could not read the window's picture: the log says why");
        fprintf(f, "settings = %s\n", have_ini ? "triforce_options.ini" : "none (the game folder has no triforce_options.ini yet)");
        if (have_save) {
            const char *base = strrchr(zip, SEP[0]);
            fprintf(f, "save = %s (%d files, the save the next start would load)\n", base ? base + 1 : zip, files);
        } else {
            fprintf(f, "save = none (%s)\n", files == 0 ? "the game has not saved yet" : files == -1 ? "a file of it could not be read"
                                             : files == -2 ? "it is written in place in this run" : "its zip could not be written");
        }
        fprintf(f, "log tail = %s\n", have_log ? "log-tail.txt (the last 400 lines)" : "none (triforce_log.txt is not in the game folder)");
        /* ((Triforce) 11-24) the run before's log, the first sign of trouble, the options changed and the switches set */
        if (have_before) {
            fprintf(f, "log before = triforce_log.1.txt (the run before's log");
            if (before_version[0]) fprintf(f, ": triforce %s", before_version);
            struct tm written;
            if (before_when && !localtime_s(&written, &before_when))
                fprintf(f, "%s last written %04d-%02d-%02d %02d:%02d", before_version[0] ? "," : ":", written.tm_year + 1900, written.tm_mon + 1,
                        written.tm_mday, written.tm_hour, written.tm_min);
            fprintf(f, ", %.1f MB%s)\n", (double)before_size / 1048576.0,
                    before_size > BEFORE_CAP ? "; only its first and its last part are in the copy: it is longer than 10 MB" : "");
        } else {
            fprintf(f, "log before = none (the game folder has no log of an earlier run)\n");
        }
        fprintf(f, "trouble = %s\n", trouble[0] ? trouble : "none in this run's log (no crash, fatal error or device lost)");
        if (have_before) fprintf(f, "trouble before = %s\n", trouble_before[0] ? trouble_before : "none in the run before's log");
        if (settings) {
            fprintf(f, "\noptions changed from the defaults (as the Insert menu shows them; triforce_options.ini has them all):\n");
            for (const char *p = settings; *p;) {
                const char *end = strchr(p, '\n');
                const size_t len = end ? (size_t)(end - p) : strlen(p);
                fprintf(f, "  %.*s\n", (int)len, p);
                p += len + (end ? 1 : 0);
            }
        } else {
            fprintf(f, "\noptions changed from the defaults = not known (the renderer did not say; triforce_options.ini has the settings)\n");
        }
        write_switches(f);
        const int whole = !fclose(f);
        snprintf(other, sizeof other, "%s" SEP "capture.txt", dir);
        if (!whole || !MoveFileExA(path, other, MOVEFILE_REPLACE_EXISTING)) f = NULL;
    }
    free(tail);
    free(settings);
    hos_log("capture: bug capture %d written in %llu ms: picture %s, save %s, settings %s%s", asked.number,
            (unsigned long long)(GetTickCount64() - began), have_picture ? "yes" : "no", have_save ? "yes" : "no", have_ini ? "yes" : "no",
            f ? "" : "; capture.txt could not be written");
    snprintf(line, sizeof line, "Saved in %s%s", dir, have_picture ? "" : " (without a picture: the log says why)");
    hos_save_share_say(HOS_SHARE_CAPTURE, line);
    snprintf(line, sizeof line, "Bug capture saved: captures" SEP "%s", name);
    hos_save_share_say(HOS_SHARE_NOTICE, line);
    InterlockedExchange(&capture_state, 0);
}
