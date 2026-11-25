/* ((Triforce) 11-24) The game's log written without the player's user name (host/log_redact.c). Players pass
   triforce_log.txt around, in the bug tracker and in chats, so what the game saves leaves it out: the home folder written
   ~ (%USERPROFILE% on Windows) and the user's name as a folder of any path <user>, the rest of each path as it was
   (host/redact_line.h).
   - each line the game and the renderer log (hos_log, the renderer's logf, hos_fatal) is redacted before it is written
     (host/hos_thread.c);
   - the bug capture's copy of the log's end (log-tail.txt) is redacted as a whole, so what other code wrote to stderr
     itself (the Vulkan loader, SDL) leaves the name out there too (host/bug_capture.c).
   - such a third-party line in triforce_log.txt itself is redacted once its run has ended (hos_log_redact_file, below).
   HOS_LOG_REDACT=0: nothing is taken out, as before. */
#pragma once
#include <stddef.h>

/* line (NUL-terminated) into out (cap bytes, NUL-terminated, cut to fit), the home folder and the user's name out. Safe from
   any thread; no allocation, no lock after the first call. The length written. With HOS_LOG_REDACT=0: a copy */
size_t hos_log_redact(char *out, size_t cap, const char *line);

/* text (n bytes) redacted line by line into a new buffer (malloc'd, the caller frees it; *out_n its length), NULL without
   memory. With HOS_LOG_REDACT=0: a copy */
char *hos_log_redact_text(const char *text, size_t n, size_t *out_n);

/* ((Triforce) the window after a crash, host/hos_crash_dialog.c) as hos_log_redact_text, NUL-ended too, but always redacted:
   HOS_LOG_REDACT=0 keeps the name in the game's own log, never in a report made to be pasted elsewhere */
char *hos_log_redact_report(const char *text, size_t n, size_t *out_n);

/* ((Triforce) what other code wrote to stderr itself (the Vulkan loader, SDL, an early fprintf) is redacted in the file once
   its run has ended: by the crash window's helper (host/hos_crash_dialog.c, as soon as the game is gone) and, for a run
   that had none, by the next start on the log it rotates to triforce_log.1.txt (host/hos_main.c).
   The log file at path redacted in place, line by line, once its run has ended (another writer would lose its place). With
   run_id, only when the file is that run's (its "run_id: <id>" line): a start since may have made a new log at the path.
   Locked while it is rewritten, so a start and a crash watch never rewrite one file at once. 1 rewritten, 0 already clean
   (or not that run's, or over 256 MB, or HOS_LOG_REDACT=0), -1 not opened or not written */
int hos_log_redact_file(const char *path, const char *run_id);
