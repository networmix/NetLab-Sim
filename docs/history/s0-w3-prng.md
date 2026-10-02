# S0 W3: compact agent PRNG

Branch `s0/prng`, baseline `0e5b299`, implementation commit `d468e6a`. The
review fix in `9d53746` changed when the family key is fixed; this report
describes the result.

## Design

`netsim/model/prng.py` implements `Prng`, version 1. Every stream is
[SplitMix64](https://prng.di.unimi.it/splitmix64.c) (Steele, Lea and Flood,
[2014](https://doi.org/10.1145/2714064.2660195)): word n of a stream is the
reference generator seeded with the stream id after n increments, and counters
wrap at 64 bits. It is a simulation generator, not a cryptographic one.
Streams are independent in that each has its own draw position; distinct
SplitMix64 seeds are offsets in one period, not disjoint sequences.

- **Family key.** An 8-byte BLAKE2b digest with personalization
  `NetSim.PRNG.v1` over network seed, device seed, agent name and generation.
  Integers are a sign byte, an eight-byte big-endian length and the
  big-endian magnitude. The name is an eight-byte length and UTF-8.
- **Stream id.** An 8-byte BLAKE2b digest with personalization
  `NetSim.stream.v1` over the eight-byte key and the length-prefixed name
  path. The empty path is the base stream, and the empty name is a separate
  stream. As with any 64-bit hash, two ids can collide.
- **State.** `(key, counters)`, where `counters` is a sorted tuple of
  `(stream id, count)` pairs for the streams that have drawn. State stored
  outside NetSim must carry `Prng.VERSION`. Malformed states and
  `random.Random` states are rejected.

The runtime derives the key at a generation's first publication and stores it
in `AgentNode.rng`, which is `None` until then. Later edits to the device or
network seed take effect only when `reset_agent` or `restart_all` starts a new
generation. A run that draws nothing publishes the committed object itself,
and a rejected run commits nothing.

The API is `random`, `uniform`, `randrange`, `randint`, `choice`, `sample`,
`shuffle`, `getrandbits`, `stream`, `getstate`, `restore` and `for_agent`.
Argument and range rules follow Python's `random` module. Rejection sampling
avoids modulo bias, and `sample` is a sparse Fisher-Yates shuffle with O(k)
extra space. Other `random.Random` methods raise `AttributeError`. Handles and
their counters belong to one invocation; only tuples of ints enter the tree.

No existing expected value changed. Agent tests compare replay equality and
identity, not Mersenne Twister numbers, and the generators in failure models,
adapters and fixtures are separate `random.Random` instances.

## Regression evidence

`tests/runtime/test_agent_prng_retention.py` keeps every published node alive
and publishes 1, 32 or 128 idle runs. Against `0e5b299` all six cases fail,
because every idle run committed a new Mersenne Twister state: 128 runs left
129 distinct objects. Now every case retains one object. To run it against the
baseline:

```sh
repo=$PWD
git worktree add --detach /tmp/netsim-0e5b299 0e5b299
cp tests/runtime/test_agent_prng_retention.py /tmp/netsim-0e5b299/tests/runtime/
cd /tmp/netsim-0e5b299
PYTHONPATH=. "$repo/venv/bin/python" -m pytest --no-cov -q tests/runtime/test_agent_prng_retention.py
```

`tests/runtime/test_prng.py` covers the reference SplitMix64 vectors, the v1
key and stream vectors, 64-bit wrap, state validation and restore, handle
identity, stream isolation across runs, every draw method with its invalid
arguments, per-thread families, and `PYTHONHASHSEED` independence in
subprocesses. `tests/runtime/test_agent_prng.py` covers the runtime: stream
isolation through publication, replay after callback, admission and
outer-commit rejection, seed edits before and after the first publication,
repeated edits that return to an earlier seed, reset and restart. Both files
need the new module, so they cannot run against the baseline.

`benchmarks/s0_prng_determinism.json` holds a 100-run script that uses every
draw method, named streams and state restore, with its output on CPython
3.14.5 and 3.14.5t under hash seeds 1 and 987654321. All four outputs are
13,036 bytes with SHA-256
`e2970cfff88ce21760a462bac72961fd469bb7dee20010db35fe3e380d6c747e`. The draws
and counters are identical to the output before `9d53746`, whose state lacked
the key. To check:

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
PY
```

## Measurements

Bytes reachable from one state object, by `sys.getsizeof`:

| State | CPython 3.14.5 | 3.14.5t |
| --- | ---: | ---: |
| Before the first publication (`None`) | 16 | 32 |
| Published, nothing drawn | 148 | 164 |
| One drawn stream | 284 | 332 |
| Two drawn streams | 392 | 456 |
| `random.Random(1).getstate()`, for comparison | 24,536 | 34,568 |

Idle publications share one state object, so these sizes do not grow with the
number of runs. Runs still publish roots, receipts and other bookkeeping;
removing that per-run commit is planned as slice C6.

`benchmarks/s0_prng.py` ran 500 agents × 5 ticks, 2,500 runs per sample, five
fresh simulations per leg for timing and a separate run under tracemalloc.
History was explicitly unbounded, so eviction hides nothing. These numbers
were taken at `d468e6a`, before the key joined the state:

| Leg | Median µs per run | Retained bytes, 2,500 runs | Bytes per run |
| --- | ---: | ---: | ---: |
| Old 1 | 192.19 | 66,965,782 | 26,786 |
| New | 152.58 | 4,175,614 | 1,670 |
| Old 2 | 189.17 | 66,965,782 | 26,786 |

The retention result is the acceptance evidence. The timings are indicative
only: other checks were running, the first two legs come from one
attempt and the third from the next, and no load average was recorded.

`make check-ci` and `make check-ft` passed on the branch: 1,718 passed,
14 skipped, 95.39 % coverage.
