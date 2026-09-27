# S0 W1 handoff: locator validation and consumer index

Branch: `s0/locator-consumer`. Baseline: `0e5b299225372f394dd3505a09cd92127b33dfa7`.
Implementation commit: `af50c0c` (`Fix S0 locator validation scans and unchanged consumer copies`).
No push. No remote CI run; the local results below do not replace CI.

## Changes and ownership

- `netsim/model/network.py`: replace the per-interface device scan with an immutable
  `PMap[(device, locator_name), block]`. Empty locator inventory takes constant
  validation work; IPv6 validation visits only locator entries. Interfaces without
  IPv6 addresses do not visit locator entries either.
- The index accompanies the committed root and each `_Edits` staging area. The
  common `Network.update()` boundary updates it from changed device shards,
  including arbitrary root replacement, locator replacement/removal, and device
  removal. Builder operations cannot change locators. A failed batch discards its
  staged index; a successful publication installs the new index before observers.
  `fork()` shares the immutable index matching its committed or staged snapshot.
  The map stores prefixes, not references to historical roots.
- This derived validation index lives in `network.py`, avoiding a schema change
  to the unowned `state.py`. Existing `srv6.add_locator()` validation still rejects
  a locator block covering any existing IPv6 interface address.
- `netsim/model/srv6.py`: determine added/removed consumer membership before
  materializing a set. Return `old.srv6_consumers` directly when membership is
  unchanged. Actual membership edits still construct and canonicalize the result.
- New regression tests: `tests/model/test_s0_locator_consumer.py`.
  New benchmark driver and results: `benchmarks/s0_w1_*`.

All tracked changes are inside W1 ownership. No changes to other workers' files,
the plan, shared Git hooks, or other branches were required.

## Source-backed reproducers

At the baseline, `network.py:742` iterates `state.devices.items()` for every
interface validation, even for IPv4-only interfaces with no locator anywhere.
The chain-build regression counts entries yielded by `_MapEdit.items()` for
64 and 128 devices, each with a loopback and chain links. Measured counts:

| Existing locators | Old, 64 devices | Old, 128 devices | New, 64 devices | New, 128 devices |
| --- | ---: | ---: | ---: | ---: |
| 0 | 10,332 | 41,148 | 188 | 380 |
| 3 | 10,902 | 42,294 | 188 | 380 |

Both IPv4 and IPv6 cases fail the linear bound on old code. The test also checks
that IPv6 prefix-containment calls equal `devices * locators`, and that IPv4
construction performs no containment calls. New counts are also recorded in
`benchmarks/s0_w1_operations.json`.

At the baseline, `srv6.py:1324` executes `set(old.srv6_consumers)` before knowing
whether membership changes. Its final `canon()` recovers identity only after
copying. The regression intercepts these copies during a real unrelated device
commit, with both zero and eight policy headends: old code copies the index twice;
the fix copies it zero times and retains the exact frozenset object.

The complete regression file has 25 cases. With baseline implementations loaded,
exactly the six performance regressions fail and the other 19 cases pass:

```sh
PYTHONHASHSEED=0 venv/bin/python -c 'from benchmarks.s0_w1_scale import load_baseline; load_baseline("0e5b299"); import pytest; raise SystemExit(pytest.main(["--no-cov", "-q", "tests/model/test_s0_locator_consumer.py"]))'
```

```text
FAILED ...test_build_interface_validation_has_linear_operation_count[0-False]
FAILED ...test_build_interface_validation_has_linear_operation_count[0-True]
FAILED ...test_build_interface_validation_has_linear_operation_count[3-False]
FAILED ...test_build_interface_validation_has_linear_operation_count[3-True]
FAILED ...test_unrelated_commit_keeps_consumer_identity_without_copy[0]
FAILED ...test_unrelated_commit_keeps_consumer_identity_without_copy[8]
6 failed, 19 passed in 0.19s
```

Those 19 semantic cases cover classic and NEXT-C-SID blocks; interface addition
and reconfiguration on local/remote devices; reverse-order overlap rejection;
locator/device removal and replacement in/out of batches; rollback; staged and
committed forks; restoring/importing a root; clearing an SR database; admission
failure; observer failure after publication; and consumer membership transitions.

## Old/new measurements

The integrator explicitly authorized running the comparison under current host
load after quiet attempts were interrupted by other workers. These timing results
are **provisional**: load exceeded 2. The integrator will rerun the benchmark on a
quiet machine before merging. Operation-count and correctness results above are
independent of timing contention.

Machine: `Mac16,6`, 14 logical CPUs, macOS 26.6.1 arm64, CPython 3.14.5.

**Provisional build wall time (seconds)**

| Devices | Old A | New | Old B | New microseconds/device |
| --- | ---: | ---: | ---: | ---: |
| 2,000 | 3.362888 | 0.135071 | 3.318929 | 67.54 |
| 8,000 | 51.958343 | 0.603794 | 51.646627 | 75.47 |

**Provisional consumer helper time (median microseconds/call)**

| Consumer count | Old A | New | Old B |
| --- | ---: | ---: | ---: |
| 0 | 1.397 | 1.279 | 1.380 |
| 10,000 | 172.069 | 1.283 | 183.865 |
| 100,000 | 3532.350 | 1.543 | 3626.663 |

Both topology fingerprints match exactly across all three processes:

| Devices | SHA-256 |
| --- | --- |
| 2,000 | `f49911738333dde063b8dba9bcdc0ffb7d19e0de596187a3ca5ce3a9e61fe17c` |
| 8,000 | `8e8934842944d3171aa7c34e375394d61f01ffe25ec7f18127b0e3856f9f4df2` |

`uptime` before/after each process (1-, 5-, and 15-minute averages):

```text
old_a before: 16:40  up 47 days, 21:16, 3 users, load averages: 3.31 4.22 4.50
old_a after:  16:41  up 47 days, 21:17, 3 users, load averages: 3.34 4.07 4.42
new before: 16:41  up 47 days, 21:17, 3 users, load averages: 3.34 4.07 4.42
new after:  16:41  up 47 days, 21:17, 3 users, load averages: 3.48 4.09 4.42
old_b before: 16:41  up 47 days, 21:17, 3 users, load averages: 3.48 4.09 4.42
old_b after:  16:42  up 47 days, 21:18, 3 users, load averages: 4.59 4.26 4.46
```

Raw results: [old A](../../benchmarks/s0_w1_old_a.jsonl),
[new](../../benchmarks/s0_w1_new.jsonl), [old B](../../benchmarks/s0_w1_old_b.jsonl),
and [host-load samples](../../benchmarks/s0_w1_load.json).
The first preliminary contended run and three interrupted quiet attempts are
excluded from these tables. The table contains only the final authorized sequence.

The driver reads the exact baseline `network.py` module and `consumer_index`
function from Git into each old process. It does not check out or edit baseline
files. All other implementation files match the baseline. Each command starts a
fresh process, in old/new/old order, with fixed `PYTHONHASHSEED=0`. `uptime` was
recorded before and after each run and every five seconds during it, alongside
`os.getloadavg()`; see `benchmarks/s0_w1_load.json`:

```sh
PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale --baseline 0e5b299 > benchmarks/s0_w1_old_a.jsonl
PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale > benchmarks/s0_w1_new.jsonl
PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale --baseline 0e5b299 > benchmarks/s0_w1_old_b.jsonl
```

Builds use the `build_phases.py` topology: N devices, one IPv4 loopback each,
N-1 unnumbered point-to-point links, and one outer batch including its commit.
Tracing is disabled for all reported runs (`--tracemalloc` is available), so these
times should not be compared directly with the research's traced timings.
Consumer measurements time only `consumer_index`: one changed nonconsumer device
and a synthetic index of 0/10k/100k headend names, with seven samples per size.
They isolate the copy cost; they are not timings of full SRv6 topology commits.

## Required checks

Setup: `bash .superset/workspace.sh setup` passed (worktree-local environment;
shared hooks left unchanged). The initial focused run passed 143 tests across
the new regressions, batches, SR database operations, and SR invalidation. The
expanded final regression file passed as part of both full checks below.

Commands, run from this worktree:

```sh
make check-ci > /tmp/s0-w1-check-ci.log 2>&1
make venv-ft > /tmp/s0-w1-venv-ft.log 2>&1
make check-ft > /tmp/s0-w1-check-ft.log 2>&1
git diff --check
```

All exited 0. Ruff format/check and Pyright passed. `make venv-ft` confirmed
`free-threaded venv ready: 3.14.5` with the GIL disabled. Output tails:

`make check-ci`:

```text
TOTAL                             12799    595    95%
Required test coverage of 85% reached. Total coverage: 95.35%
====================== 1683 passed, 14 skipped in 43.29s =======================
```

`make check-ft`:

```text
TOTAL                             12799    595    95%
Required test coverage of 85% reached. Total coverage: 95.35%
====================== 1683 passed, 14 skipped in 38.36s =======================
```

The full checks include existing deterministic plain-IP forwarding/placement
fingerprints. Pre-commit checks also passed on the implementation commit.

## Limits

- Locator addition retains its existing full SR database validation. This change
  targets repeated interface validation, not bulk SRv6 provisioning performance.
- Index maintenance uses the existing changed-shard diff; it does not claim the
  future S1 changed-key certificate or constant-time complete commits.
- Actual consumer membership changes still copy a frozenset. Other SR consumer
  invalidation/dependency scans are unchanged; no whole-commit speedup is claimed
  from the isolated consumer microbenchmark.
- The benchmark timings require the integrator's quiet-machine rerun before merge.
  Other S0 workers' changes and remote CI remain outside this handoff.

W1 disposition: both fixes, regression tests, required local checks, and the
authorized provisional comparison are delivered. The integrator owns the quiet
performance rerun and remote CI before merge. Nothing was pushed.
