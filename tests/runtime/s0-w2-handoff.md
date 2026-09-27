# S0 / W2 handoff: blocked by ownership

Date: 2026-09-27. Branch: `s0/masks-retention`.
Baseline: `0e5b299225372f394dd3505a09cd92127b33dfa7`.
Environment: macOS arm64, CPython 3.14.5; free-threaded CPython 3.14.5.

## Disposition

**BLOCKED; neither fix is implemented or accepted.** The worker instruction
requires stopping and reporting when a change needs files outside ownership.
Inspection found production and test dependencies outside W2's permitted files.
Implementation stopped at that boundary. Only this report and the new standalone
acceptance probes in `benchmarks/s0_w2_reproducers.py` are changed. No production
code, existing tests, reference documentation, or other worker's files changed.

The six explicitly invoked acceptance probes fail on the baseline. They are
outside default pytest discovery, with no skip or xfail marks. The normal suite
results below validate the existing baseline plus probe lint/types; they do not
establish acceptance of either requested fix. Move the probes into the owned
test directories with the eventual implementation.

## Ownership dependencies

| File and baseline location | Evidence | Required coordinated action |
| --- | --- | --- |
| `netsim/model/routing.py:338` | Incremental RIB edits call `FrozenPrefixTable._owned(rib.prefixes.bits, tables, rib.prefixes._masks)`. | Update the production caller with mask removal; otherwise route edits access a removed field. |
| `tests/model/test_nht.py:452` | The probe-counting index fixture passes `rib.prefixes._masks` to `_owned`. | Update the existing fixture with the constructor change. Only new files in this directory are generally owned by W2. |
| `tests/runtime/test_agent_review.py:825-844` | The RC4 regression passes a mutable mask list, mutates it, then requires `owned._masks` to be an exact tuple preserving the original value. | Replace the obsolete retained-mask assertion while preserving the exact-key and caller-aliasing checks. This file is not owned by W2. |
| `tests/runtime/test_agent_review.py:1068-1089` | Metadata regressions pass masks to both constructor paths. | Coordinate constructor compatibility and keep the malformed-length rejection coverage. |
| `tests/model/test_lpm.py:135-164` | Existing constructor and persistent-shard fixtures read `_masks`. | Permit updates to these existing fixtures, beyond the stated additions-only ownership. |
| `netsim/study.py:608-628` | `_simulation()` passes `self.keep.get('events')` and `self.keep.get('records')` explicitly; both produce `None` for omitted options. | Select bounded defaults when keys are absent, and preserve explicit `None` as the unbounded opt-in. This shared path also constructs the agent-study warmup/baseline runtime (`:635-643`). |

No mask-field reads were found in the state validators. `state.py:640-644`
classifies only the exact frozen class as admissible and rejects its mutable
builder subclass. The walks at `:713-723` and `:765-778` check exact integer
metadata and keys, then values through `shards()`. No state.py edit is indicated.

The current public `FrozenPrefixTable` constructor also accepts a masks argument.
Its compatibility policy needs to be resolved alongside the callers above.
Retaining mask storage just to satisfy old assertions would not implement the
requested mask-free design. Reconstructing masks in a compatibility accessor on
the route-update path would conceal the dependency and reintroduce allocation.
Neither workaround was added.

## Source-backed reproductions

Run from the worktree root:

```sh
rg -n '_masks|FrozenPrefixTable\(|\._owned\(' netsim tests
rg -n 'keep_events|keep_records|def _simulation' netsim/study.py netsim/runtime
venv/bin/python -m pytest --no-cov -s benchmarks/s0_w2_reproducers.py
```

The last command exits 1: **6 failed in 22.00s** on the baseline.
Full local output: `/tmp/netsim-s0-w2-reproducers.log`.

### G20: per-table allocation

Source: `PrefixTable.__init__`, `netsim/model/lpm.py:189-194`, builds all masks;
`FrozenPrefixTable._init`, `:47-68`, retains them; `freeze`, `:224-227`, passes
the tuple into the frozen snapshot. `mask_for`, `netsim/model/addressing.py:178`,
allocates the mask integers. Both table representations fail the memory probe.

`test_empty_tables_have_no_per_table_mask_allocation` starts tracemalloc after
collection, keeps 1,000 fresh tables alive, and requires retained allocation below
1,000,000 bytes. This leaves space for table instances and empty dictionaries but
rejects the current mask allocations. No fix exists yet to validate that proposed
threshold against the replacement on either interpreter.

| 1,000 empty tables | Old retained bytes | New retained bytes |
| --- | ---: | --- |
| IPv4 builder | 1,484,664 | Not measured: blocked |
| IPv6 builder | 6,861,112 | Not measured: blocked |
| IPv4 frozen | 1,484,632 | Not measured: blocked |
| IPv6 frozen | 6,861,176 | Not measured: blocked |

The supplied 2,000-device convergence experiment was also run unchanged:

```sh
PYTHONPATH="$PWD" venv/bin/python /Users/networmix/.claude/plans/netsim-protocols-research/scale-experiments/converge_mem.py > /tmp/netsim-s0-w2-converge.log 2>&1
```

Output excerpt:

```text
converge retained 50.9 MB = 25.4 KB/device
   26.62 MB   640017 objs model/addressing.py:178
    5.57 MB     8002 objs model/lpm.py:193
    2.16 MB    26006 objs model/state.py:93
    1.92 MB    12000 objs model/state.py:403
    1.68 MB    42000 objs model/state.py:104
```

These are baseline allocations, not demonstrated savings. The topology and
construction match the supplied script: 2,000 devices, one IPv4 loopback each,
an unnumbered chain, no protocol routes. Converged RIB/FIB each contain one IPv4
entry and no IPv6 entries per device. No lookup latency comparison or old/new/old
run was performed: there is no candidate implementation. No speed claim is made,
and the lookup regression budget remains unverified. Future timings must use
fresh sequential processes on the same quiet machine.

### Retention defaults

Source: `Simulation.__init__`, `netsim/runtime/simulation.py:42-43`, and
`Timeline.__init__`, `netsim/runtime/timeline.py:894-895`, default both budgets to
`None`. `Timeline._trim`, `:949-965`, skips each budget when it is `None`.

`test_default_idle_run_has_bounded_event_and_record_history` runs one agent
that returns its state by identity and only rearms a timer. It uses every default
Simulation retention setting and advances through two horizons. Its proposed
acceptance bounds are 10,000 records and 100,000 events, allowing the existing
amortized trimming slack `max(64, budget // 8)`; it also requires actual eviction.

| Simulated horizon | Old records | Old events | Dropped records/events | Shallow retained bytes |
| ---: | ---: | ---: | --- | ---: |
| 60,000.5 | 59,942 | 59,941 | 0 / 0 | 13,467,728 |
| 120,000.5 | 119,882 | 119,881 | 0 / 0 | 26,962,960 |

Both final lengths exceed the proposed default bounds. Shallow bytes count the
two lists and their event/record objects using `sys.getsizeof`; they exclude
referenced payloads, roots, deltas and all other runtime storage. This is not a
total-process memory measurement. New bounded-run numbers are unavailable.

`test_study_does_not_implicitly_select_unbounded_history` independently creates
the default Study runtime and prints `Study keep_records=None, keep_events=None`.
Changing Simulation's signature alone cannot fix this because Study explicitly
supplies both keywords. The Study observer already streams via `on_record`
(`netsim/study.py:433-435`); history requirements should be checked with the
Study/agent-study suites when choosing its new defaults.

**Behavior change delivered: none.** The proposed 10,000-record/100,000-event
defaults would retain recent history, with block-trim slack, while explicit
`None` would continue selecting complete unbounded history. That proposal has
not been implemented, so the timeline paragraph in `docs/reference.md` is left
accurate for current behavior. Study callers requesting full history must opt
in explicitly after the coordinated change.

## Validation

Commands (all from this branch; no push):

```sh
bash .superset/workspace.sh setup > /tmp/netsim-s0-w2-setup.log 2>&1
venv/bin/python -m pytest --no-cov -s benchmarks/s0_w2_reproducers.py > /tmp/netsim-s0-w2-reproducers.log 2>&1
make check-ci > /tmp/netsim-s0-w2-check-ci.log 2>&1
make venv-ft > /tmp/netsim-s0-w2-venv-ft.log 2>&1
make check-ft > /tmp/netsim-s0-w2-check-ft.log 2>&1
git diff --check
```

Setup passed; `make venv-ft` passed and asserted that the GIL is disabled:

```text
free-threaded venv ready: 3.14.5
```

An initial free-threaded check caught a possibly-unbound local in the new probe.
The timeline binding was moved before its loop; the final checks below use that
corrected probe. The expected six acceptance failures remain separate from the
normal suite and are not included in its passing count.

Final `make check-ci`: exit 0; formatting, Ruff and Pyright passed (0 errors).
Output tail:

```text
netsim/study.py                     507     16    97%   600-606, 671, 743, 752-755, 813, 836, 936, 1000
---------------------------------------------------------------
TOTAL                             12768    595    95%
Required test coverage of 85% reached. Total coverage: 95.34%
====================== 1658 passed, 14 skipped in 41.66s =======================
```

Final `make check-ft`: exit 0; formatting, Ruff and Pyright passed (0 errors).
Output tail:

```text
netsim/study.py                     507     16    97%   600-606, 671, 743, 752-755, 813, 836, 936, 1000
---------------------------------------------------------------
TOTAL                             12768    595    95%
Required test coverage of 85% reached. Total coverage: 95.34%
====================== 1658 passed, 14 skipped in 38.02s =======================
```

Local checks do not replace CI. Remote CI was not run or claimed.

## Local delivery

- `11f63d3` — `test(s0): capture W2 mask and retention acceptance failures`.
- The following documentation commit contains this handoff report.
- Only the two new owned files listed in the disposition are committed.
- No push was performed. The branch remains `s0/masks-retention`.
- `git diff --check` passed; final worktree cleanliness is checked after the
  report commit.

## Remaining work

1. Coordinate ownership for the existing callers and tests listed above.
2. Implement shift arithmetic for lookups and key validation, preserving address
   bounds, IPv4/IPv6, default/host prefixes, filtering, and frozen-table contracts.
3. Implement and document bounded defaults across Simulation, Timeline and Study;
   preserve explicit `None` and verify streamed Study metrics after eviction.
4. Move/extend the acceptance probes into normal tests, run them red/green,
   then run the complete standard and free-threaded checks on the fixed tree.
5. Measure lookup latency and 2,000-device convergence memory old/new/old on a
   quiet machine; demonstrate that lookup slowdown stays within a few percent.

This handoff is evidence and a blocker report, not a completed S0 implementation.
