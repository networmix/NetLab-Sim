# S0 / W2 handoff: implemented; latency provisional

Date: 2026-09-27. Branch: `s0/masks-retention`.
Baseline: `0e5b299225372f394dd3505a09cd92127b33dfa7`.
Environment: macOS arm64, 14 CPU cores, CPython 3.14.5 and free-threaded 3.14.5.

## Implementation and ownership

The integrator accepted the initial ownership report and extended ownership to
the required routing call, NHT fixture, mask-related agent-review assertions,
existing LPM fixtures and Study's `_simulation` defaults. Both fixes are
implemented. The blocked report in `3826232` is superseded by this report.
No other worker's implementation was merged into this branch.

- Prefix tables hold no masks. The masks parameter was removed from both
  `FrozenPrefixTable` and `_owned`, per the integrator's compatibility decision.
  Every production/test caller was updated; no compatibility accessor remains.
- Lookup and insertion use shift arithmetic. Lookup preserves the old low-bit
  behavior for negative/oversized integers; insertion rejects negative,
  oversized and host-bit-bearing keys. None-valued entries remain valid.
- Instance-owned `(length, shift, shard)` probe tuples exist only for populated
  lengths. They avoid an outer dict lookup and subtraction per step and are
  refreshed when lengths change. `lookup` probes directly rather than creating
  and closing a generator for one result. No masks or shared caches are added.
- Frozen construction still copies caller dictionaries and normalizes integer
  keys. Snapshot independence, persistent-shard behavior and malformed-length
  rejection remain covered. `state.py` has no mask-field readers; its exact-class
  classification and shard walks require no changes. `addressing.mask_for`
  remains available for its other callers; prefix tables no longer use it.
- Simulation, Timeline and Study runtimes default to **10,000 records and
  100,000 events**. Explicit `None` opts into full unbounded history. Explicit
  zero/small limits and Study aliases are preserved. Agent warmup and baseline
  preparation use the same Study runtime constructor.
- Existing block eviction is unchanged: budgets permit fewer than
  `max(64, budget // 8)` extra entries, giving maximum default lengths of
  11,249 records and 112,499 events. Queries/exports cover retained history;
  streaming observers receive all entries before eviction. Study metrics use
  those observers. The timeline paragraph in `docs/reference.md` documents the
  behavior change, full-history opt-in and unchanged roots/deltas defaults.

The six acceptance probes are now real regressions in
`tests/model/test_lpm_scale.py` and `tests/runtime/test_timeline_retention.py`.
The standalone `benchmarks/s0_w2_reproducers.py` was removed. Additional tests
cover integer boundaries, None-valued routes, explicit retention overrides,
standalone Timeline defaults and an agent Study. Existing brute-force, NHT,
persistent-table, agent-review, Study/window and invariant tests also pass.

The integrator also authorized the two retention literals in `Study.describe()`
(the method returning Workload metadata). Only those two defaults changed there.
Metadata now reports the effective runtime budgets: bounded when omitted, `None`
only when explicitly selected. Four parameterized metadata/runtime comparison
cases cover absent, partial, explicit-unbounded and aliased settings. Before
this metadata correction they produced **2 failed, 2 passed**; afterward all
**4 passed** (`/tmp/netsim-s0-w2-metadata-red.log`). No other workload metadata
was changed. Reproduce with:

```sh
venv/bin/python -m pytest --no-cov -q tests/runtime/test_timeline_retention.py -k workload
```

## Source-backed red/green evidence

The moved six probes ran in a fresh process against an exported baseline:

```sh
venv/bin/python - <<'PY'
import io, os, pathlib, shutil, subprocess, sys, tarfile, tempfile
repo = pathlib.Path.cwd()
archive = subprocess.check_output(['git', 'archive', '--format=tar', '0e5b299', 'netsim'])
with tempfile.TemporaryDirectory(prefix='netsim-w2-red-') as directory:
    root = pathlib.Path(directory)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(root, filter='data')
    for name in ('tests/model/test_lpm_scale.py', 'tests/runtime/test_timeline_retention.py'):
        shutil.copy(repo / name, root / pathlib.Path(name).name)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-s', '--no-cov',
         '-k', 'empty_tables or default_idle_run or study_does_not'],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)})
    sys.exit(result.returncode)
PY
```

**6 failed, 6 deselected in 22.00s**, exit 1 (before adding the four metadata cases): exactly the six requested cases.
Log: `/tmp/netsim-s0-w2-baseline-regressions.log`. Baseline sources: `lpm.py:193`
allocates mask tuples and `addressing.py:178` their integers;
`simulation.py:42-43` and `timeline.py:894-895` select unbounded defaults;
`Timeline._trim` skips `None`; `study.py:624-625` forwards absent keys as `None`.
No checkout or other branch was modified by this baseline run.

The focused fixed-tree run passed **230 tests, 1 skipped in 25.13s**:

```sh
venv/bin/python -m pytest --no-cov -q -s tests/model/test_lpm.py tests/model/test_lpm_scale.py tests/model/test_nht.py tests/runtime/test_timeline_retention.py tests/runtime/test_agent_review.py tests/runtime/test_study.py tests/runtime/test_study_windows.py tests/test_invariants.py
```

After optimizing probe metadata, the LPM/NHT/agent-review subset passed **112
tests in 0.88s**. Final full suites below cover the optimized implementation.

### Allocation and bounded idle history

Command: `venv/bin/python -m pytest --no-cov -q -s tests/model/test_lpm_scale.py`.

| 1,000 empty tables | Old retained bytes | New retained bytes |
| --- | ---: | ---: |
| IPv4 builder | 1,484,664 | 145,456 |
| IPv6 builder | 6,861,112 | 145,368 |
| IPv4 frozen | 1,484,632 | 145,488 |
| IPv6 frozen | 6,861,176 | 145,432 |

All four fail the 1,000,000-byte threshold on old code and pass on new. Every
fresh table is also checked for absence of `_masks`. These are retained
tracemalloc allocations, not RSS. Log: `/tmp/netsim-s0-w2-mask-allocation.log`.

The idle regression uses one agent returning state by identity and rearming a
timer, with all default Simulation retention settings:

| Horizon | Old records / events | New records / events | New dropped records / events |
| ---: | --- | --- | --- |
| 60,000.5 | 59,942 / 59,941 | 11,192 / 59,941 | 48,750 / 0 |
| 120,000.5 | 119,882 / 119,881 | 11,132 / 107,381 | 108,750 / 12,500 |

Final shallow list-plus-event/record storage is 26,962,960 bytes old versus
15,632,336 bytes new. The test asserts bounded final lengths and actual eviction.
Shallow sizes exclude payloads, roots, deltas and other runtime storage: these
are count budgets, not whole-process byte budgets. Old dropped counts are zero.
Logs: `/tmp/netsim-s0-w2-baseline-regressions.log` and `/tmp/netsim-s0-w2-focused.log`.

## Fresh-process measurements

Harness: `benchmarks/s0_w2_scale.py`. Raw samples, process snapshots, interpreter,
source paths and uptime observations: `benchmarks/s0_w2_measurements.json`.

```sh
venv/bin/python -m benchmarks.s0_w2_scale --baseline 0e5b299 --output benchmarks/s0_w2_measurements.json
```

Each experiment uses old/new/old in fresh sequential Python processes with the
same interpreter and `PYTHONHASHSEED=0`. Old imports use an exported baseline;
new imports use this worktree. Lookup has one untimed warmup and nine samples
of 131,072 queries per family/workload/API. GC is disabled only during timing;
construction and random query generation are outside timing. Match counts agree
across all three processes.

**Latency remains provisional under the integrator's standing instruction.**
Another worker's benchmark was active during preparation; this shared desktop
was not reserved as a quiet host. No W2 tests/checks ran during the final sequence.
Uptime loads recorded before each process:

```text
lookup old-1: 16:45  up 47 days, 21:21, 3 users, load averages: 3.10 3.74 4.20
lookup new: 16:45  up 47 days, 21:21, 3 users, load averages: 3.09 3.73 4.19
lookup old-2: 16:46  up 47 days, 21:21, 3 users, load averages: 3.08 3.71 4.18
converge old-1: 16:46  up 47 days, 21:21, 3 users, load averages: 2.92 3.67 4.16
converge new: 16:46  up 47 days, 21:22, 3 users, load averages: 3.05 3.63 4.13
converge old-2: 16:46  up 47 days, 21:22, 3 users, load averages: 3.33 3.66 4.13
```

Median ns/query; change compares new with the mean of the two old medians:

| Family / workload / API | Old 1 | New | Old 2 | Change |
| --- | ---: | ---: | ---: | ---: |
| ipv4/host/lookup | 208.5 | 131.6 | 214.5 | -37.8% |
| ipv4/host/lookup_iter | 204.0 | 179.7 | 202.0 | -11.4% |
| ipv4/mixed/lookup | 379.8 | 302.3 | 382.2 | -20.7% |
| ipv4/mixed/lookup_iter | 471.0 | 456.2 | 471.5 | -3.2% |
| ipv4/miss/lookup | 383.8 | 307.8 | 379.4 | -19.3% |
| ipv4/miss/lookup_iter | 349.9 | 335.0 | 346.4 | -3.8% |
| ipv6/host/lookup | 220.7 | 142.0 | 223.1 | -36.0% |
| ipv6/host/lookup_iter | 211.4 | 190.8 | 210.9 | -9.6% |
| ipv6/mixed/lookup | 402.2 | 339.5 | 416.4 | -17.0% |
| ipv6/mixed/lookup_iter | 478.6 | 494.7 | 504.1 | +0.7% |
| ipv6/miss/lookup | 395.4 | 329.1 | 389.9 | -16.2% |
| ipv6/miss/lookup_iter | 360.8 | 367.5 | 358.3 | +2.2% |

Host workloads contain only host prefixes; mixed workloads have four nonzero
lengths plus a default and a mixture of matching/random addresses; misses have
four lengths, no default, and addresses outside the populated half of the family.
Iterator timings consume every result. Lookup is 16.2–37.8% faster; the largest
iterator slowdown is 2.2%, within a few percent. These are bounded-table
microbenchmarks, not whole-network or parallel-throughput claims. A quiet-host
rerun is needed for an unconditional latency acceptance claim.

Convergence matches the supplied `converge_mem.py`: 2,000 devices, one IPv4
loopback per device, an unnumbered chain, no protocol routes. Tracemalloc starts
after construction. Sampled devices have one IPv4 RIB/FIB entry and no IPv6 entries.

| Convergence retained allocation | Old 1 | New | Old 2 |
| --- | ---: | ---: | ---: |
| Total bytes | 50,885,524 | 19,205,249 | 50,885,524 |
| Bytes/device | 25,442.762 | 9,602.6245 | 25,442.762 |

Reduction: **31,680,275 bytes total, 15,840.1375 bytes/device (62.26%)**.
This is retained traced allocation, not RSS or a 100k-device projection.
No convergence-time claim is made. The first straightforward-shift prototype
exceeded the latency budget; all final numbers include the populated-length
probe index that resolved that regression.

## Required checks and delivery

```sh
make check-ci > /tmp/netsim-s0-w2-check-ci-final.log 2>&1
UV_VENV_CLEAR=1 make venv-ft > /tmp/netsim-s0-w2-venv-ft-final.log 2>&1
make check-ft > /tmp/netsim-s0-w2-check-ft-final.log 2>&1
git diff --check
```

The initial `make venv-ft` found the existing per-worktree environment. The
rerun used uv's explicit clear option, affecting only this worktree's `venv-ft`,
and passed with `free-threaded venv ready: 3.14.5` (GIL disabled assertion passed).

`make check-ci`: exit 0; formatting, Ruff and Pyright passed (0 errors).
Output tail after the authorized metadata correction:

```text
TOTAL                             12776    596    95%
Required test coverage of 85% reached. Total coverage: 95.34%
====================== 1674 passed, 14 skipped in 56.07s =======================
```

`make check-ft`: exit 0; formatting, Ruff and Pyright passed (0 errors).
The full suite ran with the rebuilt free-threaded interpreter. Output tail:

```text
TOTAL                             12776    596    95%
Required test coverage of 85% reached. Total coverage: 95.34%
====================== 1674 passed, 14 skipped in 53.53s =======================
```

Local checks do not replace CI. No remote CI result is claimed; no push is
performed. Earlier evidence commits: `11f63d3`, `3826232`.
Implementation commit: **`8901ec4`**, `fix(s0): remove per-table masks and bound
timeline retention by default`. This report is delivered by the following
documentation commit, `docs(s0): record W2 implementation and validation results`.
All commit hooks and `git diff --check` passed. The final worktree is checked
clean after that report commit; all changes stay on `s0/masks-retention`.

Functional acceptance: both fixes and the metadata correction are implemented;
all six requested regressions fail on baseline and pass on the fixed tree.
The only remaining measurement limitation is quiet-host confirmation of the
provisional latency figures. No ownership blocker or unfinished code change
remains.
