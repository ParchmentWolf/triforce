"""(Triforce) The workers a build was asked for (make_game.py --jobs, HOOKSHOT_JOBS), for every step that runs work side by side.

The launcher's build workers reached the compile alone: the lift's processes and the shader preparation's sized themselves from
the CPU count, so an update filled every thread whatever the player chose, and the PC was unusable while it built.
make_game.py now puts a count it was given in HOOKSHOT_JOBS for the steps it starts, and each step takes at most that many:

  - nx2/chunks.py emit_jobs: the lift's emit processes;
  - nx2/build.py: its --jobs, as before;
  - the game's --prepare-shaders: started on that many of the CPUs make_game.py may use (children_on_cpus), and the game's
    environment drops the HOOKSHOT_ build variables (make_game.py game_env), so the mask is how the count reaches it.

Nothing asked (no --jobs, HOOKSHOT_JOBS unset, empty or 0): every step keeps its own count, as before. A step's own
variable (HOOKSHOT_LIFT_JOBS) still wins over this one, and each step's memory limits still apply below it: this is a ceiling,
never a floor.
"""
import contextlib
import os

ERROR = "HOOKSHOT_JOBS must be a whole number: use 1 or more, or 0 for automatic."


def requested(value):
    """A count as given (--jobs, HOOKSHOT_JOBS): 1 or more, or None for automatic (None, "" or 0). ValueError otherwise"""
    if value is None or str(value).strip() == "":
        return None
    try:
        jobs = int(value)
    except ValueError:
        raise ValueError(ERROR) from None
    if jobs < 0:
        raise ValueError(ERROR)
    return jobs or None


def asked(env_map=None):
    """The workers HOOKSHOT_JOBS asks for, or None (unset, automatic, or not a count: make_game.py refuses that one at its start)"""
    value = os.environ.get("HOOKSHOT_JOBS") if env_map is None else env_map.get("HOOKSHOT_JOBS")
    try:
        return requested(value)
    except ValueError:
        return None


def cap(n, env_map=None):
    """n, at most the workers asked for (asked), never fewer than 1"""
    limit = asked(env_map)
    return max(1, min(n, limit)) if limit else n


def _windows_mask(mask=None):
    """The process's affinity mask, or with mask, set to it. None when it cannot be read or set"""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    proc = k.GetCurrentProcess()
    if mask is not None:
        k.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        return mask if k.SetProcessAffinityMask(proc, mask) else None
    own, system = ctypes.c_size_t(), ctypes.c_size_t()
    k.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    return own.value if k.GetProcessAffinityMask(proc, ctypes.byref(own), ctypes.byref(system)) and own.value else None


def first_cpus(usable, n):
    """n of the usable CPUs (numbers), the lowest first: on Windows and Linux alike the performance cores of a hybrid CPU"""
    return sorted(usable)[:max(1, n)]


@contextlib.contextmanager
def children_on_cpus(n):
    """The processes started inside run on n of the CPUs this one may use; this one is as it was after. A child takes its
    parent's affinity when it is made (Linux: the thread that forks it; Windows: the process). n None, or as many as there are
    or more: nothing changes. Where the mask cannot be read or set, nothing changes either: the child takes every CPU, as before"""
    restore = None
    try:
        if n:
            if hasattr(os, "sched_setaffinity"):
                usable = os.sched_getaffinity(0)
                if n < len(usable):
                    os.sched_setaffinity(0, first_cpus(usable, n))
                    restore = lambda: os.sched_setaffinity(0, usable)   # noqa: E731
            elif os.name == "nt":
                mask = _windows_mask()
                bits = [i for i in range(64) if mask and mask >> i & 1]
                # (a mask covers one processor group, 64 CPUs at most: past that the game counts every CPU anyway, usable_cpus)
                if mask and n < len(bits) < 64 and _windows_mask(sum(1 << i for i in first_cpus(bits, n))) is not None:
                    restore = lambda: _windows_mask(mask)   # noqa: E731
    except OSError:
        restore = None
    try:
        yield
    finally:
        if restore:
            with contextlib.suppress(OSError):
                restore()
