/* (Triforce, 11-24) What the debug teleport's follow-up (host/hos_main.c oot_teleport_followup, 1.5 s after a request)
   does with what it reads back. A request is sometimes answered 0 and then dropped by the game: nothing is reserved
   (Sequence_ReservedNextBanc ""), no event plays and Link is still where he was, so the map never changes. Source A
   counted it in scripted runs on an RTX 3080: 6 of 159 requests, 4 of them the first one a few frames after a save had
   loaded. Such a request is sent once more; one the game answered other than 0, one that is under way (a map reserved,
   an event playing, the map loading) or that has arrived is left alone, and a resent one is not sent a third time.

   Benchmark mode's tour (host/hos_bench.c) has a retry of its own for the teleports it sends: a request the event
   manager refuses (answered 0) is asked again every half second, up to 20 times, and one that brought no map change
   in 12 s up to 3 times more. While the tour runs it alone decides (other_retry): two retries of one request would
   send it twice, and this one would send a teleport after the tour had moved on or ended. */
#pragma once
#include <string.h>

/* 1: send the request again. reserved and current: the game's Sequence_ReservedNextBanc and Sequence_CurrentBanc; wanted:
   the map the request was for (NULL or "" when none was sent); answer: the event manager's answer to it (every drop seen
   was answered 0; one it took may only be slow to reserve); resent: whether this request was already sent again;
   other_retry: something else asks again for this request (benchmark mode's tour) */
static inline int oot_teleport_dropped(const char *reserved, const char *current, const char *wanted, int event_playing,
                                       int loading, unsigned long long answer, int resent, int other_retry) {
    if (!wanted || !*wanted || answer || resent || other_retry || event_playing || loading) return 0;
    if (reserved && *reserved) return 0;              /* (the map change is reserved: under way) */
    return !current || strcmp(current, wanted) != 0;  /* (still elsewhere: dropped) */
}
