# S0 W2: prefix-table masks and bounded timeline retention

Branch `s0/masks-retention`, baseline `0e5b299`, implementation commit
`8901ec4`.

## Changes

Prefix tables:

- `FrozenPrefixTable` and `PrefixTable` hold no masks. The `masks` parameter
  is gone from the constructor and from `_owned`, and every caller is updated.
  `addressing.mask_for` remains for its other callers.
- Lookup and insert use shifts. Lookup keeps the old low-bit behaviour for
  negative and oversized integers; insert rejects negative, oversized and
  host-bit keys. `None` values stay distinct from misses.
- Each table keeps `(length, shift, shard)` tuples for its populated lengths,
  rebuilt when the set of lengths changes. `lookup` probes them directly
  instead of going through `lookup_iter`, and a test checks that the two agree.

Retention:

- `Simulation`, `Timeline` and `Study` default to 10,000 records and 100,000
  events, and `None` keeps everything. Eviction itself is unchanged: a list
  can exceed its budget by fewer than `max(64, budget // 8)` entries, so the
  default lengths peak at 11,249 records and 112,499 events.
- `on_record` observers still receive every entry before eviction, and Study
  computes its metrics from them.
- `Study.describe()` reports the effective budgets. Since `9d53746`,
  `keep={'arrays': True}` or `keep={'timeline': True}` keeps all events unless
  `events` is set.
- `docs/reference.md` documents the defaults and how to keep full history.

Tests are in `tests/model/test_lpm_scale.py` and
`tests/runtime/test_timeline_retention.py`; the benchmark is
`benchmarks/s0_w2_scale.py`, with results in
`benchmarks/s0_w2_measurements.json`.

## Regression evidence

The baseline allocated a mask tuple per table (`lpm.py:193`) and its integers
(`addressing.py:178`). `simulation.py:42-43` and `timeline.py:894-895`
defaulted to unbounded history, and `study.py:624-625` passed absent keys as
`None`.

Against `0e5b299`, 4 of 6 cases in `test_lpm_scale.py` fail: the four
allocation cases. In `test_timeline_retention.py`, 8 of 13 fail: the idle-run,
Study and standalone-timeline defaults, and every workload case whose expected
budget differs from the baseline's `None`. To run them against the baseline:

```sh
repo=$PWD
git worktree add --detach /tmp/netsim-0e5b299 0e5b299
cp tests/model/test_lpm_scale.py /tmp/netsim-0e5b299/tests/model/
cp tests/runtime/test_timeline_retention.py /tmp/netsim-0e5b299/tests/runtime/
cd /tmp/netsim-0e5b299
PYTHONPATH=. "$repo/venv/bin/python" -m pytest --no-cov -q tests/model/test_lpm_scale.py tests/runtime/test_timeline_retention.py
```

Retained tracemalloc allocation for 1,000 empty tables, in bytes; the test
threshold is 1,000,000:

| Tables | Old | New |
| --- | ---: | ---: |
| IPv4 builder | 1,484,664 | 145,456 |
| IPv6 builder | 6,861,112 | 145,368 |
| IPv4 frozen | 1,484,632 | 145,488 |
| IPv6 frozen | 6,861,176 | 145,432 |

An idle agent that rearms a timer, with default Simulation retention:

| Horizon | Old records / events | New records / events | New dropped records / events |
| ---: | --- | --- | --- |
| 60,000.5 | 59,942 / 59,941 | 11,192 / 59,941 | 48,750 / 0 |
| 120,000.5 | 119,882 / 119,881 | 11,132 / 107,381 | 108,750 / 12,500 |

The record and event lists end at 26,962,960 bytes old and 15,632,336 bytes
new, counting the lists and their entries but not payloads. The budgets are
entry counts, not byte limits: payloads, roots and deltas are separate.

## Measurements

Each experiment ran old/new/old in fresh processes with `PYTHONHASHSEED=0`,
old code imported from an exported baseline:

```sh
venv/bin/python -m benchmarks.s0_w2_scale --baseline 0e5b299 --output benchmarks/s0_w2_measurements.json
```

The lookup times are indicative only: load averages were 2.9 to 3.3 and
another benchmark was running. Each case is one warmup and nine samples of
131,072 queries, with GC off while timing. Median nanoseconds per query; the
change compares the new median with the mean of the two old ones:

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

Host workloads hold host prefixes only. Mixed workloads hold four lengths and
a default route, queried with matching and random addresses. Miss workloads
hold four lengths and no default, queried outside the populated half of the
address space. Iterator timings consume every result.

Convergence memory, measured as retained tracemalloc allocation after
construction, not RSS. The network has 2,000 devices with one IPv4 loopback
each, an unnumbered chain and no protocol routes:

| Retained allocation | Old 1 | New | Old 2 |
| --- | ---: | ---: | ---: |
| Total bytes | 50,885,524 | 19,205,249 | 50,885,524 |
| Bytes per device | 25,443 | 9,603 | 25,443 |

`make check-ci` and `make check-ft` passed on the branch: 1,674 passed,
14 skipped, 95.34 % coverage.
