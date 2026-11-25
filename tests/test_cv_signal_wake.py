"""SignalConditionVariable makes its one wake while it still holds the condition variable's lock (host/nn_os_sync.c).

A waiter sleeps until the generation moves and a wake reaches it. A signal that moved the generation, let the lock go and
only then woke one waiter could have that wake taken by a waiter that came in between (it needs the lock to come in): that
one finds its own generation unchanged and sleeps again, and the waiter the signal was for sleeps on with the mutex the
signal reserved for it; the host's wake order is not the order of entry. Made under the lock, the wake can only reach a
waiter that was in before the signal, and every one of those leaves at it.

The source is read: in the signal, the generation moves, then the wake, then the unlock; a waiter reads the generation
under that lock before it sleeps; and the early return for a signal with no waiter (HOS_CV_SIGNAL_FAST) is still before
the lock.

    python -I -B tests/test_cv_signal_wake.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNAL = "HLE(_ZN2nn2os23SignalConditionVariableEPNS0_21ConditionVariableTypeE) {"
WAIT = "HLE(_ZN2nn2os21WaitConditionVariableEPNS0_21ConditionVariableTypeEPNS0_9MutexTypeE) {"
TIMED = "HLE(_ZN2nn2os26TimedWaitConditionVariableEPNS0_21ConditionVariableTypeEPNS0_9MutexTypeENS_8TimeSpanE) {"


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(text, needles, what):
    at = -1
    for needle in needles:
        nxt = text.find(needle, at + 1)
        if nxt < 0:
            fail("%s: %r is not there, or not after what comes before it" % (what, needle))
        at = nxt


def main():
    sync = (ROOT / "host/nn_os_sync.c").read_text(encoding="utf-8")
    try:
        signal, wait, timed = block(sync, SIGNAL), block(sync, WAIT), block(sync, TIMED)
    except ValueError as e:
        fail("a function this test reads is not there (%s)" % e)
    in_order(signal, ["if (fast && !__atomic_load_n(&cv->cv_waiting, __ATOMIC_SEQ_CST)) return;", "AcquireSRWLockExclusive(&cv->lk);",
                      "cv_reserve(cv);", "cv->gen++;", "WakeConditionVariable(&cv->cv);", "ReleaseSRWLockExclusive(&cv->lk);"],
             "SignalConditionVariable")
    if signal.count("WakeConditionVariable(&cv->cv);") != 1 or signal.count("ReleaseSRWLockExclusive(&cv->lk);") != 1:
        fail("SignalConditionVariable: more than one wake or unlock")
    for name, body in (("WaitConditionVariable", wait), ("TimedWaitConditionVariable", timed)):
        # ((Triforce, 11-24) counted in for the signal's early return before the lock, not under it after the generation read)
        in_order(body, ["cv_count_in(cv);", "AcquireSRWLockExclusive(&cv->lk);", "uint64_t gen = cv->gen;", "cv_enter(cv, m);", "mutex_release_all(m);",
                        "cv->gen == gen", "cv_leave(cv, m);", "ReleaseSRWLockExclusive(&cv->lk);"], name)
    print("PASS: a signal's wake is made under the condition variable's lock, after the generation moves; waiters read the "
          "generation under that lock")


if __name__ == "__main__":
    main()
