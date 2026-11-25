/* (hookshot) The Insert menu's Restart now (gpu/vk/vk_menu.cpp): it saves its options and asks the window to close for a
   restart (WM_APP + 9: host/display.c, host/posix/display_sdl.c). The window closes as when the player closes it, and at
   the very end of that, instead of only exiting, the game is started again:
     Linux: the process becomes the game again (execve) with the arguments and the environment it started with
     (/proc/self/cmdline and /proc/self/environ: triforce_env.txt's lines are read again, not kept), so whatever waits
     for it (the launcher, a stream, a test) still has it. The game is bin/hookshot on disk, never run from inside the
     AppImage (hookshot-launch starts it with the AppImage's variables taken away), so /proc/self/exe is the game;
     argv[0] on the PATH if that is gone (the folder built again meanwhile).
     Windows: a new process of this executable (GetModuleFileNameW) with this one's command line (GetCommandLineW), in
     the same folder and environment; then this one exits. */
#include "hos.h"
#include "../gpu/vk/vk_api.h"   /* (HOS_OPT_EXITING) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

static volatile LONG relaunch_asked;

void hos_relaunch_ask(void) { InterlockedExchange(&relaunch_asked, 1); }

#ifdef _WIN32
static void relaunch(void) {
    wchar_t exe[MAX_PATH * 4];
    const DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH * 4);
    if (!n || n >= MAX_PATH * 4) {
        hos_log("restart: this executable's path was not found: the game only exits");
        return;
    }
    const wchar_t *line = GetCommandLineW();
    const size_t len = wcslen(line);
    wchar_t *cmd = (wchar_t *)malloc((len + 1) * sizeof *cmd);   /* (CreateProcessW may write into it) */
    if (!cmd) return;
    memcpy(cmd, line, (len + 1) * sizeof *cmd);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof si);
    si.cb = sizeof si;
    /* (the new process waits for this one to end before it moves triforce_log.txt to .1 and opens its own: this one still
       has it open until it exits, and a rename of an open file fails on Windows, so the new run overwrote the old run's
       log. hos_main.c reads HOS_RESTART_OF) */
    wchar_t pid[16];
    swprintf(pid, 16, L"%lu", (unsigned long)GetCurrentProcessId());
    SetEnvironmentVariableW(L"HOS_RESTART_OF", pid);
    if (CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
        /* ((Triforce, 11-18) this run is in front: the new one may take the front for its window (display.c), which it
           otherwise opened behind another window once this one had gone, and the controllers did nothing there) */
        AllowSetForegroundWindow(pi.dwProcessId);
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    } else {
        hos_log("restart: the game could not be started again (error %lu): it only exits", (unsigned long)GetLastError());
        hos_log_flush();
    }
    free(cmd);
}
#else
#include "hos_relaunch.h"
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>

extern char **environ;

static int start_err_given = 1;   /* ((Triforce) whether the game was started with a stderr: hos_relaunch_keep_env) */

void hos_relaunch_keep_env(void) {
    /* ((Triforce, 11-24, after Source A's) kept before hos_main.c opens triforce_log.txt as stderr for a game given none, by
       the same test as hos_main.c's: whether it was given one */
    const HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
    start_err_given = err && err != INVALID_HANDLE_VALUE && GetFileType(err) != FILE_TYPE_UNKNOWN;
}

static void relaunch(void) {
    HosRelaunch r;
    if (!hos_relaunch_command("/proc/self/cmdline", "/proc/self/environ", &r)) {
        hos_log("restart: this process's command was not found: the game only exits");
        hos_log_flush();
        return;
    }
    /* (every file this process opened closes with it, as at an exit: the new one opens its own) */
    DIR *d = opendir("/proc/self/fd");
    if (d) {
        const int skip = dirfd(d);
        for (struct dirent *e; (e = readdir(d));) {
            const int fd = atoi(e->d_name);
            if (fd > 2 && fd != skip) fcntl(fd, F_SETFD, fcntl(fd, F_GETFD) | FD_CLOEXEC);
        }
        closedir(d);
    }
    fflush(NULL);
    /* ((Triforce, 11-24) a game given no stderr has its own log there, which execve would keep: the new run would take it for
       a stderr it was given, and neither move it to .1 nor start a log of its own. It is given none again; its log back if
       the exec fails) */
    int log_err = -1;
    if (!start_err_given) {
        const int none = open("/dev/null", O_WRONLY | O_CLOEXEC);
        if (none >= 0 && (log_err = fcntl(STDERR_FILENO, F_DUPFD_CLOEXEC, 0)) >= 0) dup2(none, STDERR_FILENO);
        if (none >= 0) close(none);
    }
    execve("/proc/self/exe", r.argv, r.envp);
    environ = r.envp;   /* (execvp searches the PATH of the environment it is given: the one the game started with) */
    execvp(r.argv[0], r.argv);
    if (log_err >= 0) dup2(log_err, STDERR_FILENO), close(log_err);
    hos_log("restart: the game could not be started again: it only exits");
    hos_log_flush();
}
#endif

/* The window was closed (host/display.c's WM_CLOSE, host/posix/display_sdl.c's quit): the game exits, and starts again
   first when the menu asked for it */
void hos_window_closed_exit(void) {
    const int again = relaunch_asked != 0;
    { void hos_bench_closing(void); hos_bench_closing(); }   /* ((Triforce) benchmark mode: a run not finished writes that it stopped) */
    /* ((Triforce) host/input_movie.c: an input recording's last run written, and a playback's count; ExitProcess runs no
       atexit handler here) */
    { void hos_input_movie_close(void); hos_input_movie_close(); }
    hos_log(again ? "display: window closed for a restart (the Insert menu's Restart now)" : "display: window closed, exiting");
    hos_log_flush();
    { void hos_fs_save_finish(void); hos_fs_save_finish(); }   /* (host/nn_fs.c: a save still being committed is finished first) */
    { void hos_pad_speaker_shutdown(void); hos_pad_speaker_shutdown(); }   /* ((Triforce) host/pad_speaker.c: a DualSense's sound back to its jack) */
    /* (Triforce) the renderer is told: NVIDIA's Streamline is shut down in order, where leaving it to the DLLs' unloading
       crashed inside nvngx_dlssg.dll at every exit with DLSS frame generation on */
    { void rx_option_set(int id, int value); rx_option_set(HOS_OPT_EXITING, 1); }
    { void hos_crash_clean_end(void); hos_crash_clean_end(); }   /* ((Triforce) a clean end: host/hos_crash_record.c */
    if (again) relaunch();
    ExitProcess(0);
}
