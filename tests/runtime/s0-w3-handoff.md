# S0 W3 — compact agent PRNG (G18)

Branch: `s0/prng`. Baseline: `0e5b299225372f394dd3505a09cd92127b33dfa7`.
No push. All required local checks pass. Retention is accepted by the integrator;
timings are provisional pending the integrator's quiet-machine rerun before merge.

## Scope and decision

Read `AGENTS.md` first and followed plan §14.5 S0, §15.3 and §15.9.
Only owned files were changed: new `netsim/model/prng.py`, the RNG import,
Context field, construction and publication comment in `runtime/agents.py`,
RNG contract docstrings, new runtime tests, new benchmark files and this report.
No scheduler, retry, reset, timeline, unrelated generator or model behavior was
edited. No change to `tests/test_invariants.py` was necessary; focused tests
enforce the new identity/admission rules.

The user clarified that D3 requires **independent counters across runs** and
authorized a sorted tuple of `(stream_id, counter)` pairs instead of one global
counter. Only streams ever drawn from appear. The base stream is one entry when
drawn. `None` remains the state before any draw, including before the first run.
No-draw runs return the original committed object; rejected runs publish no
new cursors. Reset and fresh Simulation restart still clear all RNG state.

## Implementation and compatibility

`Prng.VERSION == 1`: [SplitMix64 reference implementation by Sebastiano Vigna](https://prng.di.unimi.it/splitmix64.c),
and [Steele, Lea and Flood, 2014](https://doi.org/10.1145/2714064.2660195).
Each stream's nth word is the reference algorithm seeded with that stream id,
after n increments; arithmetic and counters wrap at 64 bits. This is a
simulation generator, not a cryptographic generator. Distinct SplitMix64 seeds
are offsets in its period; named-stream independence here means independent
draw positions, not a claim of disjoint mathematical sequences.

Base key: BLAKE2b, 8-byte digest, personalization `NetSim.PRNG.v1`, over
`(network seed, device seed, agent name, generation)`. Integers use a sign byte
and an eight-byte big-endian length followed by unsigned big-endian magnitude
(zero has zero magnitude bytes). Names use eight-byte lengths and UTF-8.
Stream ids use BLAKE2b, 8-byte digest, personalization `NetSim.stream.v1`, over
the eight-byte big-endian base key and length-prefixed name path. The empty path
is the base stream; the empty *name* is a distinct named stream. Nested paths
cannot alias slash-containing names through delimiter ambiguity. No Python
hash, entropy source, stdlib random distribution, shared cache or mutable
module-level RNG participates. As with any 64-bit hashed key, hash collisions
are possible; the API does not promise collision-free ids.

The sorted-pair state schema is v1. External serialization must record
`Prng.VERSION` alongside the tuple and pass `version=` on restore; unsupported
versions and malformed/MT states are rejected. AgentNode's contract binds its
tuple to v1. This work does not implement checkpoint migration from MT.

API: `random`, `uniform`, `randrange`, `randint`, `choice`, `sample`, `shuffle`,
`getrandbits`, `stream`, `getstate`, and `for_agent`. Range/index behavior follows
[Python's documented random API](https://docs.python.org/3/library/random.html).
Rejection sampling avoids modulo bias. `sample` uses a sparse Fisher-Yates
shuffle with O(k) temporary storage; duplicate/unhashable population entries
work. `shuffle` accepts invocation-local lists. Optional `sample(counts=...)`,
other distributions, `seed` and `setstate` are not part of this API. Restoration
uses the constructor or `for_agent`. Other `random.Random` methods raise
`AttributeError`; this is verified for every public stdlib method outside the
supported set. No distribution caches exist. Repeated `stream(name)` calls
within a run return the identical private object; the lazy handle cache is
invocation-local, has no parent/back-reference cycle, and is never committed.
No-op zero-bit/empty operations draw nothing.
Mutable handles/banks belong to one invocation; only int/tuple snapshots enter
the tree. Snapshot storage is O(number of drawn streams), not O(number of runs).

Repository audit:

```sh
rg -n '\.rng\b|Random\(|getstate\(' netsim tests benchmarks
rg -n '\brng\s*\.' . --glob '*.py' --glob '!venv*/**'
```

Existing direct `ctx.rng` draw sites in this checkout use `random()`. The task's
requested `randrange`, `choice`, `sample`, `getrandbits`, plus `uniform`, `randint`
and `shuffle`, are all implemented/tested. Other generators in failure models,
adapters and topology/test fixtures stay unchanged. **No existing expected
random outcome was changed.** Existing agent tests compare retry/replay equality,
state identity or untouched `None`, not MT numeric literals. The numeric
adapter shuffle expectation belongs to a separate `random.Random` instance.

## Reproducer and regression evidence

Before implementation, added `test_agent_prng_retention.py` without importing
the new generator. Keep every published AgentNode alive, initialize with/without
one draw, then publish N idle runs for N = 1, 32, 128. Assert exactly one distinct
RNG object across the retained nodes and at most 256 reachable bytes. This tests
RNG retention directly, independent of timeline eviction or other commit costs.

```sh
bash .superset/workspace.sh setup > /tmp/s0-w3-setup.log 2>&1
venv/bin/python -m pytest --no-cov -q tests/runtime/test_agent_prng_retention.py \
  > /tmp/s0-w3-old-regression.log 2>&1
```

Old-code tail:

```text
assert len({id(value) for value in values}) == 1
E assert 129 == 1
6 failed in 0.23s
```

After implementation:

```sh
venv/bin/python -m pytest --no-cov -q tests/runtime/test_prng.py \
  tests/runtime/test_agent_prng.py tests/runtime/test_agent_prng_retention.py \
  tests/runtime/test_agent_retry.py > /tmp/s0-w3-focused.log 2>&1
```

```text
69 passed in 0.74s
```

New coverage includes reference SplitMix64 vectors, public v1 seed/name vectors,
64-bit wrap, canonical state/admission, handle continuity and draw-only identity,
per-module isolation across publications (including previously idle runs),
retry after callback/admission/outer-commit failures, reset and fresh Simulation,
all distribution APIs and invalid calls, large ranges, sparse sample semantics,
thread-isolated families, repeated-handle identity, unsupported methods, and subprocesses with PYTHONHASHSEED 1 and 987654321.
The deterministic uniformity smoke test has a five-second timeout; it makes no
statistical-quality claim beyond catching obvious distribution defects.

## Measurements

Reachable unique RNG objects, `sys.getsizeof` on CPython 3.14.5:

| State | Bytes |
| --- | ---: |
| Never drawn (`None`) | 16 |
| One drawn stream | 184 |
| Two drawn streams | 292 |
| `random.Random(1).getstate()` | 24,536 |

Idle publications retain the *same* object at all tested N; these values are
not multiplied by the number of retained idle publications. Runs/receipts still
publish roots and retain other bookkeeping; eliminating that is C6, outside W3.

End-to-end evidence: [`benchmarks/s0_prng_results.json`](../../benchmarks/s0_prng_results.json).
500 agents × 5 timed ticks = 2,500 runs per sample; five fresh simulations per
leg for timing, plus a separate tracemalloc simulation (10-frame tracebacks).
Each leg is a fresh sequential process on the same machine, macOS 26.6.1 arm64,
CPython 3.14.5, 14 logical CPUs, PYTHONHASHSEED=1. Timing excludes construction
and tracemalloc. Retention is after GC with explicitly unbounded root/record
history; no timeline eviction hides the old behavior. The baseline loader
executes the exact original `agents.py` from Git in a private module and uses
its AgentRuntime, leaving the worktree untouched. Other runtime/model code is
unchanged from the baseline, apart from RNG contract documentation.

| Sequential leg | Median µs/run | Retained bytes, 2,500 runs | Bytes/run |
| --- | ---: | ---: | ---: |
| Old A1 | 192.19 | 66,965,782 | 26,786.31 |
| New B | 152.58 | 4,175,614 | 1,670.25 |
| Old A2 | 189.17 | 66,965,782 | 26,786.31 |

**Retention acceptance evidence:** 93.76% less total retained memory per idle
run, reproducing the plan's ~26.8 KB → ~1.67 KB result. The residual memory is
non-RNG tree/timeline/receipt bookkeeping; W3 does not claim zero-commit runs.

**Timing status: provisional.** These samples show a 19.98% lower median than
the mean of the two old medians, but do not establish a quiet-machine speedup.
They are the chronological completed old/new/old legs from retry attempt 2's
old/new and retry attempt 3's old (no intervening measured leg). A first
manually discarded attempt and five automatically rejected comparison attempts
overlapped other host activity. The retained JSON includes all five rejected
attempt summaries and the selected legs' one-second process-CPU observations.
Competing activity included another S0 worker's checks/benchmarks and host
services. Neither other workers nor system processes were stopped.

The integrator explicitly instructed W3 to stop waiting, accept retention as
the evidence, and leave a quiet-machine timing rerun to integration before
merge. **Load averages during the discarded runs were not captured.** Do not
infer them from process CPU readings. A separately labelled handoff-time
snapshot at `2026-09-27T15:51:52.758684+00:00` was **4.40 / 3.76 / 4.03**
(1/5/15 minutes); this is not retrospectively attributed to the timing window.

Exact benchmark commands (run serially from this worktree):

```sh
PYTHONHASHSEED=1 venv/bin/python benchmarks/s0_prng.py --label old1 \
  --runtime-ref 0e5b299225372f394dd3505a09cd92127b33dfa7 > /tmp/s0-w3-old1.json
PYTHONHASHSEED=1 venv/bin/python benchmarks/s0_prng.py --label new \
  > /tmp/s0-w3-new.json
PYTHONHASHSEED=1 venv/bin/python benchmarks/s0_prng.py --label old2 \
  --runtime-ref 0e5b299225372f394dd3505a09cd92127b33dfa7 > /tmp/s0-w3-old2.json
```

The selected A2 was invoked with `--label old1` when restarting the comparison;
the JSON preserves that original label. The supervisor sampled
`ps -A -o pid=,%cpu=,comm=` once per second, waited for three consecutive
samples with no foreign process at ≥60% CPU before each leg, and discarded
attempts where that threshold was crossed later. This gate caught overlap
rather than proving whole-host quiescence. The integrator superseded this wait
requirement after the unsuccessful attempts.

## Required checks

```sh
make check-ci > /tmp/s0-w3-check-ci.log 2>&1
make venv-ft > /tmp/s0-w3-venv-ft.log 2>&1
make check-ft > /tmp/s0-w3-check-ft.log 2>&1
git diff --check
```

CPython 3.14.5 `make check-ci` exited 0:

```text
142 files already formatted
All checks passed!
0 errors, 0 warnings, 0 informations
netsim/model/prng.py                149      0   100%
TOTAL                             12915    596    95%
Required test coverage of 85% reached. Total coverage: 95.39%
1718 passed, 14 skipped in 40.39s
```

`make venv-ft` initially exited 0. After the integrator follow-up, its rerun
refused to replace the existing venv (exit 2: "A virtual environment already
exists at: venv-ft"). Following uv's documented hint, reran
`UV_VENV_CLEAR=1 make venv-ft` (exit 0), then `make check-ft` (exit 0). Only this
worktree's environment was recreated; no hooks or tracked setup files changed.
The target asserted that the GIL is disabled:

```text
free-threaded venv ready: 3.14.5
```

CPython 3.14.5t `make check-ft` exited 0:

```text
142 files already formatted
All checks passed!
0 errors, 0 warnings, 0 informations
netsim/model/prng.py                149      0   100%
TOTAL                             12915    596    95%
Required test coverage of 85% reached. Total coverage: 95.39%
1718 passed, 14 skipped in 37.83s
```

Cross-interpreter evidence: `benchmarks/s0_prng_determinism.json` contains the
exact 100-run mixed-API script and four results (normal/free-threaded, each with
hash seeds 1 and 987654321). Each emits 13,013 identical bytes, SHA-256:
`a925f90ebb3bb52f9e609b06f3213f3361d7e8c07500eec3c0811450b609c4dc`.
The script includes state restoration, root and named streams, all eight
distribution APIs, and state serialization. To reproduce:

```sh
venv/bin/python - <<'PY'
import hashlib, json, os, subprocess
from pathlib import Path
evidence = json.loads(Path('benchmarks/s0_prng_determinism.json').read_text())
for result in evidence['results']:
    data = subprocess.check_output(
        [result['python'], '-c', evidence['script']],
        env=dict(os.environ, PYTHONHASHSEED=result['hashseed']),
    )
    assert hashlib.sha256(data).hexdigest() == result['sha256']
    assert len(data) == result['bytes']
    print(result['python'], result['hashseed'], result['sha256'])
PY
```

Local checks do not replace CI. Remote CI has not been run for these unpushed
commits. No ownership exception was needed.

Implementation/tests: `d468e6a` — `Replace agent MT state with versioned independent PRNG streams`.
Benchmarks and this report are committed separately as
`Record S0 PRNG retention evidence and provisional timing handoff`.
Both commits are local to `s0/prng`; no push. Final handoff verification uses
`git status --short` (empty), `git log -2 --oneline`, and
`git diff 0e5b299..HEAD --check`. The final source tree is the one tested above;
only evidence JSON and this report were written after the passing full suites.
