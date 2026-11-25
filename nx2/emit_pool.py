"""(Triforce) The lift's emit in several processes where there is no fork (Windows).

nx2/chunks.py's forked workers inherit the lifter as it stands: 5 GB of decoded functions, tables and texts, shared for nothing.
A spawned process starts empty, and handing it that state whole costs more than it saves (425 MB of functions and 180 MB of texts
pickled, read again and held by every worker). So the lifter stays in the lift's own process, and each worker is sent what it
needs and no more:

  - once, when it starts: every attribute of the lifter but NOT_SENT (the entries, the PLT stubs, the jump tables, the names, the
    patches after instructions: 4 MB pickled), the functions that set the lifter's class up as this process did (poll.install),
    and where the counters live;
  - with each run of consecutive functions: those functions' bodies as the discovery left them (about 3 MB a run).

A worker translates its run's instructions itself, as a64_lift.Lifter.write does for all of them (each distinct word once, per pc
where its text reads the pc: run_texts), emits the run with the lifter's own emit_function and sends back the texts, the names
each calls, what the run added to the counters and the FPX shapes its instructions use (a64_fpx.h's helpers: the lift's process
writes that header from every run's, fill_fpx in nx2/chunks.py). The lift's process takes the runs in order and hands write() the
functions one by one, as if it had made them: the C is the one-process C, byte for byte (tests/test_spawn_emit.py on authored code;
the game's own lift was compared file by file). Nothing a worker computes is taken from anywhere but these two messages, so
discovery is done once and is not assumed to repeat itself.

(Triforce, 11-24) The lift's process no longer translates every instruction for itself on this path (nx2/chunks.py no_texts: ~15 s
and 1-2 GB, before, only to send the texts on), and the processes start when write() is called, before the coverage report, so
they work while the lift's process makes it (emit(): the first runs are asked for at once).

Measured on a 16-thread PC (the game: 294,523 functions, 17.6 million instructions, 185 runs): write()'s emit loop takes 46 s in
one process, 37 s of it in emit_function, and 13 s with 8 processes (21 s with 3, on a PC that was not idle). What is left is
the lift's own process: about 7 s to send (3 s to pickle the bodies, 3 s to pick each run's texts, 1 s to pickle them) and what
write() itself needs for a gigabyte of C. More processes than keep up with it only wait for it, so emit_jobs (chunks.py) asks
for half the processors, at most 8, and the files compiled beside the lift keep the rest. A worker held 230 to 480 MB at its
most.

A worker that raises, dies or does not answer ends the lift with what it said (SystemExit, never a wait forever), and the
workers still running are ended. A worker whose parent is gone ends by itself: Windows leaves the children of a stopped process
running, and one of them could be writing a lifted file into the next build's folder.
"""
import collections
import concurrent.futures
import gc
import importlib
import multiprocessing
import os
import pickle
import sys
import threading
import traceback
from concurrent.futures.process import BrokenProcessPool

import a64_lift

# (the lifter's attributes a worker is not sent: the image and the functions (each run brings its own), write()'s stand-in for
# emit_function, which exists only in the lift's process, and what only the discovery reads)
NOT_SENT = ("img", "funcs", "emit_function", "eh_starts", "_preds",
            "_op_entries")   # ((Triforce) nx2/walk.py's shared entries of the discovery's plain ops: a million, read by no emit)
RUN_FUNCS = 2000      # (a run: at most this many functions,
RUN_INSNS = 120000    # and no more once it holds this many instructions: 2000 functions are 120,000 on average, a few are 20,000 each)
AHEAD = 2             # (runs asked for beyond one a worker: none waits while the lift's process writes a chunk)
WAIT = 600            # (seconds without an answer to a run, a split or a file's marks, which take a second: the worker is taken for hung)
SLICE = 5.0
MOST = 60             # (Windows waits on at most 64 handles at once, and the pool keeps a few of its own)
# (a process that is gone: what it printed as it went, a Python error at its start for one, is in the lift's output above this)
GONE = "%s: a process of the lift stopped before it answered (out of memory, ended from outside, or it could not start): %s"


def plan(order, size, most_funcs=None, most_size=None):
    """order cut into runs of consecutive functions: a run ends at most_funcs functions, or with the function that brings it to
    most_size (size(e): a function's instructions), so a run of giant functions is no longer than a run of small ones. Every
    function is in exactly one run and the runs, joined, are order"""
    most_funcs, most_size = most_funcs or RUN_FUNCS, most_size or RUN_INSNS
    runs, cur, held = [], [], 0
    for e in order:
        cur.append(e)
        held += size(e)
        if len(cur) >= most_funcs or held >= most_size:
            runs.append(cur)
            cur, held = [], 0
    if cur:
        runs.append(cur)
    return runs


def run_texts(bodies, fpx):
    """The instruction texts the emit of the functions in bodies ({e: (body, labels)}) reads, made as a64_lift.Lifter.write makes
    them for every function: a64_lift's emit_function, dead_flags and dirty_regs look a plain instruction's text up by its word,
    or by the word and its address where the text depends on the address (pc_relative), and no other kind's. Each is translated
    once, by a64emit.translate and a64_lift.op_text as they stand (nx2/insn.py's, nx2/vecfp.py's, nx2/fastvec.py's: this
    process ran nx2/lift.py's module level as the lift's did). The FPX shapes the texts use are added to fpx"""
    import a64emit
    relative = a64_lift.pc_relative
    keys = {}
    for body, _ in bodies.values():
        for pc, (k, w) in body.items():
            if k[0] == "op":
                keys.setdefault((w, pc) if relative(w) else w, (pc, w))
    order = list(keys)
    tx, fl = a64emit.translate([keys[x] for x in order])
    op_text = a64_lift.op_text
    return dict(zip(order, zip((op_text(t, fpx) for t in tx), fl)))


def emit_print(cls):
    """What the class's emit_function is made of: its own name and, through the closures, the names of the functions it wraps
    (poll.install keeps the one before it in its closure). A worker whose class has another emit_function than the lift's
    process (a wrapper installed there and not named in `setup`) would write other C, without a word: it compares this first"""
    return chain(getattr(cls, "emit_function", None))


def lift_print(cls):
    """(Triforce) What a worker's emit and texts are made of: emit_print, and the same for the lifter's dead_flags and for the
    translator (a64emit.translate) and a64_lift.op_text, which a worker now calls itself (run_texts)"""
    import a64emit
    return [emit_print(cls), chain(getattr(cls, "dead_flags", None)), chain(a64emit.translate), chain(a64_lift.op_text)]


def chain(f):
    """f's own name and, through the closures, the names of the functions it wraps"""
    out, todo, seen = [], [f], set()
    while todo:
        f = todo.pop()
        f = getattr(f, "__func__", f)
        if f is None or id(f) in seen:
            continue
        seen.add(id(f))
        module = getattr(f, "__module__", None) or "?"
        out.append("%s.%s" % ("__main__" if module == "__mp_main__" else module, getattr(f, "__qualname__", "?")))
        for cell in getattr(f, "__closure__", None) or ():
            try:
                v = cell.cell_contents
            except ValueError:
                continue
            if hasattr(v, "__code__") or hasattr(v, "__func__"):
                todo.append(v)
    return out


def where(L, counter):
    """How a worker finds a counter of the lift's process again: an attribute of the lifter (stats), or a module's global
    (poll.stats). ("L", name) or (module, name)"""
    for k, v in vars(L).items():
        if v is counter:
            return "L", k
    for name, module in list(sys.modules.items()):
        for k, v in list((getattr(module, "__dict__", None) or {}).items()):
            if v is counter:
                return name, k
    raise SystemExit("emit: a counter that neither the lifter nor a module holds by name cannot be counted in other processes")


# ---- in a worker ------------------------------------------------------------------------------------------------------------
_mine = None   # (a worker's own: its lifter and its counters, or what kept it from having them, as text)


def _no_throttle():
    """Windows' power throttling off for this process, as the build does for every process it starts: it slows the processes
    of a window in the background to almost nothing on some PCs"""
    if os.name != "nt":
        return
    try:
        import ctypes

        class State(ctypes.Structure):
            _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]
        k = ctypes.WinDLL("kernel32")
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        s = State(1, 1, 0)
        k.SetProcessInformation(k.GetCurrentProcess(), 4, ctypes.byref(s), ctypes.sizeof(s))
    except (OSError, ValueError, TypeError, AttributeError):
        pass


def _leave_with_parent():
    """This process ends when the lift's does (stopped from outside: nothing tells its children)"""
    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def watch():
        parent.join()
        os._exit(3)
    threading.Thread(target=watch, daemon=True).start()


def _start(blob):
    global _mine
    try:
        _no_throttle()
        _leave_with_parent()
        setup, cls, state, counters, want = pickle.loads(blob)
        for f in setup:
            f()
        got = lift_print(cls)
        for what, mine, theirs in zip(("the lifter's emit_function", "the lifter's dead_flags", "the translator (a64emit.translate)",
                                       "a64_lift.op_text"), got, want):
            if mine != theirs:
                raise RuntimeError("%s here is %s, the lift's process has %s: what set it up there must be named in `setup` "
                                   "(nx2/chunks.py write)" % (what, " over ".join(mine), " over ".join(theirs)))
        L = cls.__new__(cls)
        vars(L).update(state)
        _mine = (L, [vars(L)[k] if m == "L" else getattr(importlib.import_module(m), k) for m, k in counters])
    except BaseException:   # (said by the first run it is asked for: an initializer's own failure only breaks the pool)
        _mine = traceback.format_exc()


def _emit_run(bodies):
    """A run's functions emitted: [(e, text, refs)], each counter's keys with what this run added (every key the counter holds,
    in its order: the lift's process adds them in the runs' order, so its counters get their keys in the order one process gives
    them), and (Triforce) the FPX shapes of the run's instructions (run_texts)"""
    if not isinstance(_mine, tuple):
        raise RuntimeError("a process of the emit could not be set up:\n%s" % _mine)
    L, counters = _mine
    fpx = set()
    texts = run_texts(bodies, fpx)
    L.funcs = bodies
    for c in counters:
        for k in c:
            c[k] = 0
    out = [(e,) + tuple(L.emit_function(e, texts)) for e in bodies]
    return out, [list(c.items()) for c in counters], fpx


# ---- in the lift's process ----------------------------------------------------------------------------------------------------
class Workers:
    """The spawned processes. jobs: how many; L, counters, setup: what each is given when it starts (the lifter's state, where
    its counters and the others in `counters` live, and the functions to call first)"""

    def __init__(self, jobs, L, counters=(), setup=()):
        blob = pickle.dumps((list(setup), type(L), {k: v for k, v in vars(L).items() if k not in NOT_SENT},
                             [where(L, c) for c in counters], lift_print(type(L))), pickle.HIGHEST_PROTOCOL)
        self.jobs = max(1, min(int(jobs), MOST))
        self.pool = concurrent.futures.ProcessPoolExecutor(max_workers=self.jobs, mp_context=multiprocessing.get_context("spawn"),
                                                           initializer=_start, initargs=(blob,))

    def _ask(self, fn, call):
        try:
            return call[0], self.pool.submit(fn, *call[1])
        except BrokenProcessPool as e:   # (a process died since the last answer: the pool takes nothing more)
            raise SystemExit(GONE % (call[0], e)) from None

    def each(self, fn, calls, wait=None, primed=False):
        """fn(*args) in the processes for every (what, args) of calls, the results in the calls' order. calls is read as the
        processes come free (AHEAD more than there are), so what it makes for a call is not held for all of them at once.
        A call that raises, a process that dies and one that gives no answer for `wait` seconds (WAIT) end it with SystemExit
        and what was said, and with the processes ended; so does leaving it before its end.
        (Triforce) primed: the first calls are asked for at the first next(), which gives None, so the processes start (they are
        started as calls come) and work while the caller does something else before it takes the answers"""
        pending, calls, done = collections.deque(), iter(calls), False
        try:
            while True:
                while calls is not None and len(pending) < self.jobs + AHEAD:
                    call = next(calls, None)
                    if call is None:
                        calls = None
                    else:
                        pending.append(self._ask(fn, call))
                if primed:
                    primed = False
                    yield None
                    continue
                if not pending:
                    done = True
                    return
                answer = self._answer(*pending.popleft(), wait or WAIT)
                done = calls is None and not pending   # (the last: whoever takes it and asks for no more leaves the processes be)
                yield answer
        finally:
            if not done:
                self.stop(kill=True)

    def ask(self, fn, calls):
        """Every (what, args) of calls asked of the processes now: what answers() then takes. For work that must go to its
        end once it has begun (the page marks: a file each, rewritten in place): nothing is left to ask for later, so a lift
        that ends meanwhile for a reason of its own still has every file finished, the pool doing what it was asked before
        the interpreter leaves"""
        try:
            return [self._ask(fn, call) for call in calls]
        except BaseException:
            self.stop(kill=True)
            raise

    def answers(self, asked, wait=None):
        """The answers to ask()'s calls, in their order; it fails as each() does"""
        left = len(asked)
        try:
            for what, future in asked:
                answer = self._answer(what, future, wait or WAIT)
                left -= 1
                yield answer
        finally:
            if left:
                self.stop(kill=True)

    def _answer(self, what, future, wait):
        left = wait
        while not concurrent.futures.wait([future], timeout=min(left, SLICE))[0]:
            left -= SLICE   # (in slices: a PC that slept through the wait is not a worker that hung)
            if left <= 0:
                raise SystemExit("%s: its process gave no answer for %d seconds and was stopped" % (what, wait))
        try:
            return future.result()
        except KeyboardInterrupt:
            raise
        except BrokenProcessPool as e:
            raise SystemExit(GONE % (what, e)) from None
        except BaseException as e:   # (what the process raised, SystemExit too, with where it raised it; the summary last, the line a build names)
            raise SystemExit("%s%s: its process failed: %s: %s" % (
                "%s\n" % str(e.__cause__).strip() if e.__cause__ is not None else "", what, type(e).__name__, e)) from None

    def stop(self, kill=False):
        """The processes ended: asked to leave after what they are doing, or (kill) ended now"""
        pool, self.pool = self.pool, None
        if pool is None:
            return
        if kill:
            for p in list((getattr(pool, "_processes", None) or {}).values()):
                try:
                    p.kill()
                except (OSError, ValueError, AttributeError):
                    pass
        pool.shutdown(wait=True, cancel_futures=True)


class Emitted:
    """emit()'s (e, text, refs), an iterator; fpx: the FPX shapes of the runs taken so far (all of them once it is read to its
    end); close() ends what it asked for when it is not read to its end (the processes are ended then, as each() does)"""

    def __init__(self, answers, counters):
        self.fpx = set()
        self._answers = answers
        self._frozen = True
        self._made = self._take(answers, counters)

    def _take(self, answers, counters):
        for out, counts, shapes in answers:
            for c, added in zip(counters, counts):
                for k, v in added:
                    c[k] = c.get(k, 0) + v
            self.fpx |= shapes
            yield from out
        self._thaw()

    def _thaw(self):
        if self._frozen:
            self._frozen = False
            gc.unfreeze()

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._made)

    def close(self):
        try:
            self._made.close()
            self._answers.close()
        finally:
            self._thaw()


def emit(workers, L, order, counters, runs=None):
    """(e, text, refs) for every function of order, in order, emitted by the workers (an Emitted); counters (the dicts Workers
    was given) get each run's additions; runs: the runs, when not plan()'s. (Triforce) The first runs are asked for now: the
    processes start and translate them while the lift's process goes on (nx2/chunks.py write: the coverage report, then the
    lifter's write())"""
    funcs = L.funcs
    if runs is None:
        runs = plan(order, lambda e: len(funcs[e][0]))

    def calls():
        for es in runs:
            yield ("the emit of f_%08x to f_%08x" % (es[0], es[-1]), ({e: funcs[e] for e in es},))
    gc.freeze()   # (the lift's millions of objects out of the collector's sight while the runs' short-lived ones come and go)
    answers = workers.each(_emit_run, calls(), primed=True)
    try:
        next(answers)
    except BaseException:
        gc.unfreeze()
        raise
    return Emitted(answers, counters)
