# Engine load in the Renode simulation (IronPython 2.7): executed instructions per audio block, i.e. from the input
# stage's call (0x08042458 / 0x08042474 in audioTask) to the return of the engine call (0x08042468 / 0x08042484),
# collected per named phase. Instructions, not cycles: see tests/perf.py for the CPI caveat.
_st = {"t0": None, "phase": None, "data": {}}


def start(cpu):
    _st["t0"] = int(cpu.ExecutedInstructions)


def end(cpu):
    if _st["phase"] is not None and _st["t0"] is not None:
        _st["data"].setdefault(_st["phase"], []).append(int(cpu.ExecutedInstructions) - _st["t0"])
    _st["t0"] = None


def phase(name):
    _st["phase"] = name


def report():
    for name in sorted(_st["data"], key=lambda n: n):
        v = _st["data"][name]
        v2 = sorted(v)
        print("PROF %-28s blocks %5d  mean %9.0f  p95 %9.0f  max %9.0f" % (
            name, len(v), sum(v) / float(len(v)), v2[int(0.95 * (len(v2) - 1))], v2[-1]))
