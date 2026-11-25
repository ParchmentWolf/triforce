/* (Triforce) nn::nfp: an amiibo from a file.

   The game's amiibo sequence asks its NfpMgr for a reader and waits while there is none; with one, it starts detection,
   reads the figure's TagInfo and ModelInfo and waits for the figure to be lifted off (host/amiibo.h says what it reads
   of them, and has the readers' states). Until now every nn::nfp function was the lift's stub, which answers 0 and
   writes nothing: no reader, so the sequence waited for ever.

   The player puts dumps of their own figures into a folder "amiibo" in the game folder and chooses one on the Debug
   tab's Scan amiibo page (gpu/vk/vk_menu.cpp). The page sends the file's name (HOS_OPT_AMIIBO_ASK, a byte a read, a line
   feed at its end; a line of its own for "none"), read here at the game's pad read. From the first figure chosen on, two
   readers are listed and the game is told that the readers changed (the event of AttachAvailabilityChangeEvent, which
   its NfpMgr thread asks about while it has none); the figure goes onto the reader the game looks for one with. Until
   a figure is chosen every function here answers as the stub did, so a player who chooses none gets the game as it was.
   The page is told what became of the figure (HOS_OPT_AMIIBO_SAID, NFP_SAID_*).

   Only what a tag keeps in the clear is read from a dump (the serial number and which figure it is), so no key is
   needed, none is looked for and none is read. A dump is a tag's bytes (.bin) or a Flipper Zero's NFC file of them
   (.nfc). The game's own code asks for nothing else (host/amiibo.h); the SDK's functions for a figure's owner and
   nickname stay the stubs they were.

   ((Triforce) The application area, the data a game keeps on a figure (this game's request opens none): for a figure of
   ours it is answered from a file of Triforce's own, the amiibo folder's areas/<serial number>.area (amiibo_area_*),
   written when a game makes one or flushes it. The player's dump is never written. For a handle that is not a listed
   reader's these answer as the stubs did. */
#include "hos.h"
#include "amiibo.h"
#include "../gpu/vk/vk_api.h"
#include <stdio.h>
#include <string.h>
#include <windows.h>   /* (SRWLOCK; linux: host/posix's) */

int rx_option(int id, int otherwise);            /* rx_backend.c */
void rx_option_set(int id, int value);
void hos_system_event_signal(uint64_t event);    /* nn_os_sync.c: by the event's address in the game */
int hos_share_game_dir(char *out, size_t cap);   /* save_share.c: the game folder, no separator at its end */

/* (what the page is told is what host/amiibo.h says became of the figure) */
_Static_assert(NFP_SAID_NONE == HOS_AMIIBO_NONE && NFP_SAID_WAITING == HOS_AMIIBO_WAITING && NFP_SAID_ON_READER == HOS_AMIIBO_ON_READER &&
               NFP_SAID_READ == HOS_AMIIBO_READ && NFP_SAID_REFUSED == HOS_AMIIBO_REFUSED && NFP_SAID_NO_FILE == HOS_AMIIBO_NO_FILE,
               "HOS_AMIIBO_* (gpu/vk/vk_api.h) and NFP_SAID_* (host/amiibo.h)");

static SRWLOCK nfp_lock = SRWLOCK_INIT;
static Nfp nfp = {.holder = -1};
static uint64_t availability_event;   /* the SystemEventType the game gave AttachAvailabilityChangeEvent, 0 none */

/* the reader a call names (its DeviceHandle is the argument's first eight bytes), -1 when it is none of ours: the
   caller then answers as the stub did */
static int reader_of(uint64_t handle_ptr) { return handle_ptr ? nfp_reader(&nfp, G64(handle_ptr)) : -1; }

HLE(_ZN2nn3nfp10InitializeEv) {
    AcquireSRWLockExclusive(&nfp_lock);
    nfp_restart(&nfp);
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(0);
}
HLE(_ZN2nn3nfp8FinalizeEv) {
    AcquireSRWLockExclusive(&nfp_lock);
    nfp_restart(&nfp);
    availability_event = 0;   /* (the game's event goes with its NfpMgr: never signalled after this) */
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(0);
}
/* AttachAvailabilityChangeEvent(os::SystemEventType*): only kept. The game clears and asks it as before (nn_os_sync.c
   makes an event of an address at its first use); it is signalled when the first figure is chosen */
HLE(_ZN2nn3nfp29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE) {
    AcquireSRWLockExclusive(&nfp_lock);
    availability_event = ARG(0);
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(0);
}
/* ListDevices(DeviceHandle* out, int* count, int max): eight bytes a handle. Nothing written while none is listed */
HLE(_ZN2nn3nfp11ListDevicesEPNS0_12DeviceHandleEPii) {
    uint64_t handles[NFP_READERS];
    AcquireSRWLockExclusive(&nfp_lock);
    const int max = (int)(int32_t)ARG(2);
    const int n = ARG(0) && ARG(1) ? nfp_list(&nfp, handles, max < NFP_READERS ? max : NFP_READERS) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    for (int i = 0; i < n; i++) G64(ARG(0) + 8ULL * i) = handles[i];
    if (n > 0) G32(ARG(1)) = (uint32_t)n;
    RET(0);
}
/* GetNpadId(unsigned* out, DeviceHandle const&) */
HLE(_ZN2nn3nfp9GetNpadIdEPjRKNS0_12DeviceHandleE) {
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(1));
    ReleaseSRWLockExclusive(&nfp_lock);
    if (reader >= 0 && ARG(0)) G32(ARG(0)) = nfp_reader_npad(reader);
    RET(0);
}
/* GetDeviceState(DeviceHandle const&) -> DeviceState */
HLE(_ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE) {
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(0));
    const int state = reader >= 0 ? nfp_state(&nfp, reader, hos_now_ns()) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(state);
}
HLE(_ZN2nn3nfp14StartDetectionERKNS0_12DeviceHandleE) {
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(0));
    const uint32_t result = reader >= 0 ? nfp_start(&nfp, reader, hos_now_ns()) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(result);
}
HLE(_ZN2nn3nfp13StopDetectionERKNS0_12DeviceHandleE) {
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(0));
    const uint32_t result = reader >= 0 ? nfp_stop(&nfp, reader) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(result);
}
/* GetTagInfo(TagInfo* out, DeviceHandle const&) */
HLE(_ZN2nn3nfp10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE) {
    uint8_t info[NFP_TAG_INFO_SIZE];
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(1));
    const uint32_t result = reader >= 0 ? nfp_tag_info(&nfp, reader, hos_now_ns(), info) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    if (reader >= 0 && !result && ARG(0)) memcpy(GP(ARG(0)), info, sizeof info);
    RET(result);
}
/* Mount(DeviceHandle const&, ModelType, MountTarget) */
HLE(_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE) {
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(0));
    const uint32_t result = reader >= 0 ? nfp_mount(&nfp, reader, hos_now_ns()) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(result);
}
/* GetModelInfo(ModelInfo* out, DeviceHandle const&) */
HLE(_ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE) {
    uint8_t info[NFP_MODEL_INFO_SIZE];
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(1));
    const uint32_t result = reader >= 0 ? nfp_model_info(&nfp, reader, hos_now_ns(), info) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    if (reader >= 0 && !result && ARG(0)) memcpy(GP(ARG(0)), info, sizeof info);
    if (reader >= 0 && !result) hos_log("nfp: the game read the figure's ModelInfo");
    RET(result);
}

/* ---- ((Triforce) the application area (host/amiibo.h nfp_area_*), for a figure of ours: its file written outside the lock ---- */
static void area_save(const AmiiboTag *tag, const uint8_t bytes[NFP_AREA_FILE]);
/* OpenApplicationArea(DeviceHandle const&, unsigned access_id) */
HLE(_ZN2nn3nfp19OpenApplicationAreaERKNS0_12DeviceHandleEj) {
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(0));
    const uint32_t result = reader >= 0 ? nfp_area_open(&nfp, reader, hos_now_ns(), (uint32_t)ARG(1)) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(result);
}
/* GetApplicationArea(void* out, size_t* size, DeviceHandle const&, size_t max) */
HLE(_ZN2nn3nfp18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm) {
    uint8_t data[NFP_AREA_SIZE];
    uint64_t size = 0;
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(2));
    const uint32_t result = reader >= 0 ? nfp_area_get(&nfp, reader, hos_now_ns(), data, ARG(3), &size) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    void *out = reader >= 0 && !result && ARG(0) ? hos_guest_range(ARG(0), ARG(3) < NFP_AREA_SIZE ? ARG(3) : NFP_AREA_SIZE) : NULL;
    if (reader >= 0 && out) memcpy(out, data, ARG(3) < NFP_AREA_SIZE ? (size_t)ARG(3) : NFP_AREA_SIZE);
    if (reader >= 0 && !result && ARG(1)) G64(ARG(1)) = size;
    RET(result);
}
/* SetApplicationArea(DeviceHandle const&, void const* data, size_t size) */
HLE(_ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvm) {
    const uint64_t size = ARG(2) < NFP_AREA_SIZE ? ARG(2) : NFP_AREA_SIZE;
    const uint8_t *data = ARG(1) ? hos_guest_range(ARG(1), size) : NULL;
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(0));
    const uint32_t result = reader >= 0 ? nfp_area_set(&nfp, reader, hos_now_ns(), data, data ? size : 0) : 0;
    ReleaseSRWLockExclusive(&nfp_lock);
    RET(result);
}
/* CreateApplicationArea and RecreateApplicationArea(DeviceHandle const&, ApplicationAreaCreateInfo const&): the info's
   access ID at 0, its first data's address at 8 and size at 16 */
static uint32_t area_create(Ctx *c, int again) {
    const uint8_t *info = ARG(1) ? hos_guest_range(ARG(1), 24) : NULL;
    uint32_t id = 0, size = 0;
    uint64_t at = 0;
    if (info) memcpy(&id, info, 4), memcpy(&at, info + 8, 8), memcpy(&size, info + 16, 4);
    const uint64_t take = size < NFP_AREA_SIZE ? size : NFP_AREA_SIZE;
    const uint8_t *data = at ? hos_guest_range(at, take) : NULL;
    uint8_t bytes[NFP_AREA_FILE];
    AmiiboTag tag;
    int save = 0;
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(0));
    const uint32_t result = reader >= 0 && info ? nfp_area_create(&nfp, reader, hos_now_ns(), id, data, data ? take : 0, again, &save) : 0;
    if (save) amiibo_area_bytes(&nfp.area, bytes), tag = nfp.tag;
    ReleaseSRWLockExclusive(&nfp_lock);
    if (save) area_save(&tag, bytes), hos_log("nfp: a game made its application area on the figure (amiibo/areas)");
    return result;
}
HLE(_ZN2nn3nfp21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) {
    const uint32_t result = area_create(c, 0);
    RET(result);
}
HLE(_ZN2nn3nfp23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) {
    const uint32_t result = area_create(c, 1);
    RET(result);
}
/* Flush(DeviceHandle const&): what was set written to the tag, here its area's file */
HLE(_ZN2nn3nfp5FlushERKNS0_12DeviceHandleE) {
    uint8_t bytes[NFP_AREA_FILE];
    AmiiboTag tag;
    int save = 0;
    AcquireSRWLockExclusive(&nfp_lock);
    const int reader = reader_of(ARG(0));
    const uint32_t result = reader >= 0 ? nfp_flush(&nfp, reader, hos_now_ns(), &save) : 0;
    if (save) amiibo_area_bytes(&nfp.area, bytes), tag = nfp.tag;
    ReleaseSRWLockExclusive(&nfp_lock);
    if (save) area_save(&tag, bytes);
    RET(result);
}

/* The dump "name" of the game folder's amiibo folder: NFP_SAID_WAITING when it is a figure's (*tag filled), else
   NFP_SAID_NO_FILE or NFP_SAID_REFUSED. At most AMIIBO_FILE_MAX bytes of a tag's bytes are read, AMIIBO_NFC_MAX of a
   Flipper NFC file. (Called under hos_amiibo_poll's own lock: the buffers are static) */
static int load_dump(const char *name, AmiiboTag *tag) {
    char dir[600], path[900];
    static uint8_t data[AMIIBO_NFC_MAX + 1], pages[540];
    if (!amiibo_name_ok(name) || !hos_share_game_dir(dir, sizeof dir)) return NFP_SAID_NO_FILE;
    snprintf(path, sizeof path, "%s/amiibo/%s", dir, name);
    FILE *f = fopen(path, "rb");
    if (!f) return NFP_SAID_NO_FILE;
    const size_t n = fread(data, 1, sizeof data, f);   /* (one byte more than a file may have: a longer file is refused) */
    fclose(f);
    /* ((Triforce) a Flipper NFC file: its pages as the tag's bytes; anything else, the tag's bytes as they are) */
    const int flipper = n <= AMIIBO_NFC_MAX && amiibo_flipper((const char *)data, n, pages) == sizeof pages;
    const int why = flipper ? amiibo_parse(pages, sizeof pages, tag) : amiibo_parse(data, n, tag);
    if (why != AMIIBO_OK) {
        hos_log("nfp: amiibo/%s is not taken: %s", name, why == AMIIBO_BAD_SIZE ? "not the size of a figure's dump (532, 540 or 572 bytes, or a Flipper .nfc file of one)"
                                                                                   : "it does not hold a figure's serial number and number");
        return NFP_SAID_REFUSED;
    }
    return NFP_SAID_WAITING;
}

/* ---- ((Triforce) the application area's file: the amiibo folder's areas/<serial number>.area (host/amiibo.h). Read when a
   figure is chosen; written, whole, when a game makes its area or flushes it. Never the player's dump ---- */
static int area_path(const AmiiboTag *tag, char *path, size_t cap, int make_dir) {
    char dir[600], name[20];
    if (!hos_share_game_dir(dir, sizeof dir)) return 0;
    amiibo_area_name(tag, name);
    if (make_dir) {
        snprintf(path, cap, "%s/amiibo/areas", dir);
        CreateDirectoryA(path, NULL);   /* (the amiibo folder is there: the dump was read from it) */
    }
    snprintf(path, cap, "%s/amiibo/areas/%s", dir, name);
    return 1;
}
static void area_load(const AmiiboTag *tag, NfpArea *area) {
    char path[700];
    uint8_t bytes[NFP_AREA_FILE + 1];
    if (!area_path(tag, path, sizeof path, 0)) return;
    FILE *f = fopen(path, "rb");
    if (!f) return;
    const size_t n = fread(bytes, 1, sizeof bytes, f);
    fclose(f);
    if (amiibo_area_parse(bytes, n, area)) hos_log("nfp: the figure's application area (a game's data on it) is read from amiibo/areas");
}
static void area_save(const AmiiboTag *tag, const uint8_t bytes[NFP_AREA_FILE]) {
    char path[700];
    FILE *f = area_path(tag, path, sizeof path, 1) ? fopen(path, "wb") : NULL;
    const int ok = f && fwrite(bytes, 1, NFP_AREA_FILE, f) == NFP_AREA_FILE;
    if (f && fclose(f)) f = NULL;
    if (!ok || !f) hos_log("nfp: the figure's application area could not be kept (%s)", path);
}

/* The Scan amiibo page's choice, taken at the game's pad read (host/nn_hid.c; every 50 ms at most): a file's name, or
   an empty line for none. And the page told what became of the figure when that changed */
void hos_amiibo_poll(void) {
    static int64_t next;
    static int told = -1;
    static char line[256];
    static size_t used;
    static SRWLOCK one = SRWLOCK_INIT;   /* (the pad is read by more than one of the game's threads) */
    const int64_t now = hos_now_ns();
    if (now < __atomic_load_n(&next, __ATOMIC_RELAXED) || !TryAcquireSRWLockExclusive(&one)) return;
    __atomic_store_n(&next, now + 50000000LL, __ATOMIC_RELAXED);
    int byte;
    while ((byte = rx_option(HOS_OPT_AMIIBO_ASK, 0)) > 0) {
        if (byte != '\n') {
            if (used + 1 < sizeof line) line[used++] = (char)byte;
            continue;
        }
        line[used] = 0, used = 0;
        AmiiboTag tag;
        const int loaded = line[0] ? load_dump(line, &tag) : NFP_SAID_NONE;
        uint64_t event = 0;
        AcquireSRWLockExclusive(&nfp_lock);
        if (loaded == NFP_SAID_WAITING) {
            if (nfp_choose(&nfp, &tag)) event = availability_event;
            area_load(&tag, &nfp.area);   /* ((Triforce) a game's data kept for this figure, if any) */
        } else {
            nfp_take_away(&nfp);
            nfp.said = loaded;
        }
        ReleaseSRWLockExclusive(&nfp_lock);
        if (loaded == NFP_SAID_WAITING)
            hos_log("nfp: amiibo/%s chosen (%s dump): on the reader when the game looks for a figure%s", line,
                    tag.decrypted ? "a decrypted" : "a tag's", event ? "; the game is told a reader is there now" : "");
        if (event) hos_system_event_signal(event);
    }
    AcquireSRWLockExclusive(&nfp_lock);
    for (int i = 0; nfp.listed && i < NFP_READERS; i++) nfp_step(&nfp, i, now);   /* (a figure lifted off when its time is up) */
    const int said = nfp.said;
    ReleaseSRWLockExclusive(&nfp_lock);
    if (said != told) rx_option_set(HOS_OPT_AMIIBO_SAID, told = said);
    ReleaseSRWLockExclusive(&one);
}
