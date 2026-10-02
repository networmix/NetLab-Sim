# S0 W1: locator validation and SRv6 consumer index

Branch `s0/locator-consumer`, baseline `0e5b299`, implementation commit
`af50c0c`.

## Changes

- `netsim/model/network.py`: interface validation no longer scans every
  device for locators. An immutable `PMap[(device, locator), block]` travels
  with the committed root and with each batch's staging area.
  `Network.update()` maintains it from the changed devices, which covers
  locator and device removal, replacement and whole-root replacement. Builder
  operations cannot change locators. A failed batch discards its index, and
  `fork()` shares the index of the snapshot it copies.
- Interfaces without IPv6 addresses skip the check; IPv6 checks visit the
  locator entries only. `srv6.add_locator()` still rejects a block that covers
  an existing interface address.
- `netsim/model/srv6.py`: `consumer_index` works out membership changes before
  building a set and returns `old.srv6_consumers` itself when there are none.
- Tests in `tests/model/test_s0_locator_consumer.py`; benchmark driver
  `benchmarks/s0_w1_scale.py` with results in `benchmarks/s0_w1_*`.

## Regression evidence

At `0e5b299`, `network.py:742` iterated `state.devices.items()` for every
interface, IPv4-only ones included. The test counts entries yielded by
`_MapEdit.items()` while building a chain with a loopback per device:

| Existing locators | Old, 64 devices | Old, 128 devices | New, 64 devices | New, 128 devices |
| --- | ---: | ---: | ---: | ---: |
| 0 | 10,332 | 41,148 | 188 | 380 |
| 3 | 10,902 | 42,294 | 188 | 380 |

It also checks that IPv6 containment calls equal devices × locators and that
IPv4 builds make none.

At `0e5b299`, `srv6.py:1324` copied `set(old.srv6_consumers)` on every commit
and recovered the identity with `canon()` afterwards. The test intercepts the
copies during an unrelated device commit with zero and eight headends. The
old code copies twice, the new code never, and the index keeps its identity.

Against `0e5b299`, 6 of the file's 25 cases fail: the four operation-count
cases and the two copy cases. The other 19 pin behaviour that must not change:
classic and NEXT-C-SID blocks, interface addition and reconfiguration on local
and remote devices, overlap rejection in both orders, locator and device
removal and replacement inside and outside batches, rollback, staged and
committed forks, root restore and import, clearing an SR database, admission
failure, observer failure after publication, and consumer membership changes.

To run the file against the baseline:

```sh
repo=$PWD
git worktree add --detach /tmp/netsim-0e5b299 0e5b299
cp tests/model/test_s0_locator_consumer.py /tmp/netsim-0e5b299/tests/model/
cd /tmp/netsim-0e5b299
PYTHONPATH=. "$repo/venv/bin/python" -m pytest --no-cov -q tests/model/test_s0_locator_consumer.py
```

## Timings

The times are indicative only. They were taken at load averages between 3.3
and 4.6 on a 14-CPU Mac16,6 (macOS 26.6.1, CPython 3.14.5), and the operation
counts above are the acceptance evidence. Each leg is a fresh process, in
old/new/old order, with `PYTHONHASHSEED=0`:

```sh
PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale --baseline 0e5b299 > benchmarks/s0_w1_old_a.jsonl
PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale > benchmarks/s0_w1_new.jsonl
PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale --baseline 0e5b299 > benchmarks/s0_w1_old_b.jsonl
```

Build wall time, in seconds, for N devices with one IPv4 loopback each and
N-1 unnumbered links in one batch, tracing off:

| Devices | Old A | New | Old B | New, µs per device |
| --- | ---: | ---: | ---: | ---: |
| 2,000 | 3.363 | 0.135 | 3.319 | 67.5 |
| 8,000 | 51.958 | 0.604 | 51.647 | 75.5 |

Median time of one `consumer_index` call, in microseconds, with one changed
non-consumer device and a synthetic index of headend names. This measures the
copy, not a full SRv6 commit:

| Headends | Old A | New | Old B |
| --- | ---: | ---: | ---: |
| 0 | 1.397 | 1.279 | 1.380 |
| 10,000 | 172.069 | 1.283 | 183.865 |
| 100,000 | 3532.350 | 1.543 | 3626.663 |

Topology fingerprints matched across all three processes:

| Devices | SHA-256 |
| --- | --- |
| 2,000 | `f49911738333dde063b8dba9bcdc0ffb7d19e0de596187a3ca5ce3a9e61fe17c` |
| 8,000 | `8e8934842944d3171aa7c34e375394d61f01ffe25ec7f18127b0e3856f9f4df2` |

Load samples taken every five seconds are in `benchmarks/s0_w1_load.json`.

## Limits

- Adding a locator still runs the full SR database validation, so bulk SRv6
  provisioning is not faster.
- The index is updated from a diff of the changed device-map shards, so its
  cost follows shard size rather than the number of changed keys.
- A real membership change still copies the consumer set, and the other SR
  invalidation scans are unchanged.

`make check-ci` and `make check-ft` passed on the branch: 1,683 passed,
14 skipped, 95.35 % coverage.
