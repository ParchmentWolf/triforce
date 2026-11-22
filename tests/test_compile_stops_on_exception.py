"""The compile stops when a compile raises (nx2/build.py main's compile loop, MemoryGate.stop; no compiler, no game).

(Triforce, 11-21, the performance audit's LIFT-31, after Source A's.) A compiler's error comes back as a value and is
tried again alone. An exception does not (a missing or blocked compiler, an object that cannot be written, a full disk,
Ctrl-C): it left the pool's block, and the block's exit ran every compile still queued first, the whole compile with
nothing said, before the build stopped.

Runs main's own statements, from "t0, failed =" to "if still", cut out through the AST as tests/test_compile_retry_jobs.py
does, and the real MemoryGate, with stand-in compiles:
1. one worker, 12 jobs, the first raises: the exception reaches the caller, and at most one more compile starts;
2. the real memory gate holding three workers back (no memory free): the first compile raises, the gate is stopped, at
   most one of the three starts (the one that took the raising compile's lease first), and none is left holding a lease;
3. the gate alone: a waiter and a late comer both raise CompileStopped once it is stopped, and a gate not stopped gives
   leases as before.

    python -I -B tests/test_compile_stops_on_exception.py
"""
import argparse
import ast
import concurrent.futures
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "nx2/build.py"


def actual(source):
    """main's compile statements as run_compile_jobs(), and the real MemoryGate and CompileStopped, in one scope"""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in ("MemoryGate", "CompileStopped")]
    main, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"]
    start, = [i for i, node in enumerate(main.body) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Tuple) and [getattr(n, "id", None) for n in t.elts] == ["t0", "failed"]
                      for t in node.targets)]
    end, = [i for i, node in enumerate(main.body) if i > start and isinstance(node, ast.If)
            and isinstance(node.test, ast.Name) and node.test.id == "still"]
    wrapper = ast.parse("def run_compile_jobs():\n    return 0\n").body[0]
    wrapper.body = main.body[start:end + 1] + wrapper.body
    module = ast.fix_missing_locations(ast.Module(body=classes + [wrapper], type_ignores=[]))
    scope = dict(os=os, time=time, concurrent=concurrent, threading=threading, GATE=None, COMPILER_MB=1000,
                 counted=False, expected={}, pending=[], eta_jobs=1, eta_left=lambda pending, jobs: 0)
    exec(compile(module, str(source), "exec"), scope)
    return scope


class CompileStopsOnException(unittest.TestCase):
    def setUp(self):
        self.scope = actual(SOURCE)
        self.started, self.lock = [], threading.Lock()

    def run_jobs(self):
        with redirect_stdout(io.StringIO()):
            return self.scope["run_compile_jobs"]()

    def test_one_worker_stops_after_the_compile_that_raised(self):
        jobs = [("cc", __file__, "obj%d.o" % i, [], b"") for i in range(12)]

        def compile_one(job):
            with self.lock:
                self.started.append(job[2])
            if job[2] == "obj0.o":
                raise FileNotFoundError("authored: the compiler is gone")
            time.sleep(0.05)
            return job[1], 0.05, ""
        self.scope.update(compile_one=compile_one, jobs=jobs, a=SimpleNamespace(jobs=1))
        with self.assertRaisesRegex(FileNotFoundError, "the compiler is gone"):
            self.run_jobs()
        # (the worker may have taken the next job before the queue was cancelled: that one, no more. Before: all 12)
        self.assertLessEqual(len(self.started), 2, self.started)
        self.assertEqual(self.started[0], "obj0.o")

    def test_workers_waiting_at_the_memory_gate_start_nothing(self):
        gate = self.scope["MemoryGate"]()
        gate.floor = 1
        # (nothing free: with one compile running, every other waits at the gate)
        self.scope.update(mem_need=lambda src: 400, free_mb=lambda: 0, rss_mb=lambda p: 0, GATE=gate)
        waiting = threading.Event()
        jobs = [("cc", __file__, "obj%d.o" % i, [], b"") for i in range(4)]

        def compile_one(job):   # (as build.py's: the lease first, then the compiler)
            first = job[2] == "obj0.o"
            if first:
                lease = gate.enter(job[1])
                for _ in range(400):   # (until the other three wait at the gate)
                    if len(self.started) == 3:
                        break
                    time.sleep(0.005)
                gate.leave(lease)
                raise OSError("authored: the object cannot be written")
            with self.lock:
                self.started.append(job[2])   # (asked for its lease)
            lease = gate.enter(job[1])
            with self.lock:
                self.started.append("compiling " + job[2])
            time.sleep(0.3)   # (a compile takes its time: the gate is stopped long before this one's lease is free)
            gate.leave(lease)
            return job[1], 0.3, ""
        # (obj0 holds the one lease the floor gives before the others ask)
        real_submit = concurrent.futures.ThreadPoolExecutor.submit

        def submit(ex, fn, job):
            future = real_submit(ex, fn, job)
            if job[2] == "obj0.o":
                for _ in range(400):
                    if gate.running:
                        break
                    time.sleep(0.005)
            return future
        concurrent.futures.ThreadPoolExecutor.submit = submit
        try:
            self.scope.update(compile_one=compile_one, jobs=jobs, a=SimpleNamespace(jobs=4))
            with self.assertRaisesRegex(OSError, "cannot be written"):
                self.run_jobs()
        finally:
            concurrent.futures.ThreadPoolExecutor.submit = real_submit
        self.assertTrue(gate.stopped, "the gate was not told the build is stopping")
        # (the raising compile's own lease is free before the exception reaches the loop: the waiter that takes it in
        # between is the one compile that may still start. Before: all three)
        self.assertLessEqual(len([s for s in self.started if s.startswith("compiling")]), 1, self.started)
        self.assertEqual(len(gate.running), 0, "a stopped compile was left holding a lease")
        waiting.set()

    def test_a_stopped_gate_gives_no_lease(self):
        Stopped = self.scope["CompileStopped"]
        gate = self.scope["MemoryGate"]()
        gate.floor = 1
        self.scope.update(mem_need=lambda src: 400, free_mb=lambda: 0, rss_mb=lambda p: 0)
        first = gate.enter("a.c")           # (under the floor: at once, as before)
        self.assertEqual(len(gate.running), 1)
        raised = []

        def waiter():
            try:
                gate.enter("b.c")
            except Stopped:
                raised.append(1)
        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        self.assertTrue(t.is_alive(), "the waiter did not wait at the gate")
        t0 = time.time()
        gate.stop()
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertLess(time.time() - t0, 0.9, "the waiter was not woken: it waited out its second")
        self.assertEqual(raised, [1])
        with self.assertRaises(Stopped):    # (and one that comes after)
            gate.enter("c.c")
        self.assertEqual(len(gate.running), 1)
        gate.leave(first)
        self.assertEqual(len(gate.running), 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    args, remaining = parser.parse_known_args()
    SOURCE = args.source.resolve()
    unittest.main(argv=[__file__, *remaining])
