# Reference

Formats and options that are too detailed for the README.

## Batches

`with net.batch():` stages device, interface, link, route, demand and SRv6
(locator, SID and policy) edits and agent registrations, then commits them
once; hooks and the runtime see one delta with origin `('batch', n_ops)`. An
exception inside the block restores the tree and the allocators and undoes
the agent registrations; handles of entities created in the block become
stale. Reads inside the block (`state`, a device's `node`, `fork()`) see the
staged edits. `converge()` and `place()` are not allowed inside a batch.
Client profiles, route sources and the capacity model are outside the
transaction.

## Timeline

Every commit is one record (`seq`, `time`, `round`, `origin`) with typed
events: link state, interface oper transitions (RFC 2863 names and reasons),
carrier debounce, bundle membership, RIB rows, FIB entries, SIDs, policies,
demands, placement summaries, agent runs. Series come from the arrays the
placement events carry.

`Simulation(keep_roots=, keep_deltas=, keep_events=, keep_records=)` bound
what is retained. The defaults keep the last root of each of the last 256
timestamps, 64 deltas, 10,000 records and 100,000 events. `None` for roots,
records or events keeps all of them. Records and events are evicted oldest
first, in blocks, so a list can exceed its budget by fewer than
`max(64, budget // 8)` entries. `dropped_records` and `dropped_events` count
the evictions. Queries and
`to_csv` see only retained entries, while `on_record` observers receive every
record and event before eviction.

`Study` uses the same record and event budgets for absent `keep` keys,
including agent warmup and baseline runs. Its metrics come from observers and
cover the whole window. `keep={'arrays': True}` or `keep={'timeline': True}`
keeps every event unless `events` is set, because the series and rows they add
are built from retained events.

## Failure studies

Entities are `('device', name)`, `('link', id)` or `('risk_group', name)`.
All sources on one simulation share leases: an entity fails on its first
lease and recovers on its last release.

A renewal `Process` takes `mtbf` and `mttr` per entity, the mean times in
seconds. `ttf` and `ttr` choose the distributions, either by name
(`exponential`, the default, `lognormal`, `weibull` or `constant`) or as a
mapping such as `{'kind': 'lognormal', 'sigma': 0.5}`. `sigma` is the
lognormal spread in log space and `shape` the Weibull shape; both belong in
that mapping. The means stay `mtbf` and `mttr`.

`Study(network, keep=...)` sets retention, as described under Timeline: `keep`
takes `roots`, `deltas`, `events`, `records`, `arrays`, `reports` and
`timeline`. `Study.from_scenario(scenario, keep=..., **options)` builds the
network with the NetGraph adapter below.

The run methods accept these options:

| Option | Methods | Meaning |
|---|---|---|
| `t0` | `iterations`, `enumerate`, `replay` | failure time |
| `settle` | `iterations`, `enumerate`, `replay` | observation window (see below) |
| `restore` | `iterations`, `enumerate`, `replay` | restore after the window |
| `warmup` | all | simulated time run on a fresh runtime before `t0` (needed with agents) |
| `horizon` | all; required by `process` | observation window after the failure |
| `event_budget` | all | maximum engine events per iteration; exceeding it reports `budget_exceeded` |
| `stability`, `quiet` | all | predicate (`routing`, `programming`, `delivery`, `all`) that must hold for `quiet` seconds to report `converged` |

Without agents and without `warmup`, `horizon`, `event_budget`, `stability`
or `quiet`, `settle` is a minimum window after which derivations drain.
Otherwise the observation window is a hard limit: `horizon`, or `settle` when
`horizon` is absent. `iterations` also takes `parallelism`, which must be 1.

Each iteration's `data.netsim` reports `status` (`converged`,
`deadline_exceeded`, `budget_exceeded`), `converged_at`, transient and
full-window loss in bits, per-demand downtime, drop reasons, engine events
and rounds; with agents, the baseline is prepared on a warmed runtime and
carries `baseline_complete`. `StudyResult.rows()` has one row per flow and
failure pattern (with `occurrence_count`), plus `policy_*` columns for SR
policies. `to_ngraph()` returns a NetGraph `results.json` step whose
`baseline` and `flow_results` follow `FlowIterationResult`.

## NetGraph adapter

`from_scenario(scenario, *, addressing='unnumbered', capacity_unit=1e9,
failure_policy=None, demand_set=None, iterations=0, strict=True, srv6=False,
ipv6=False, igp=True, pools=None)` returns `(network, demand_ids, schedule)`.
It maps nodes to devices with loopbacks, links to Ethernets (parallel links
tagged `lag` to a PortChannel), costs to metrics and the demand set to
demands. `pairwise` demands split the volume over the pairs; `combine`
demands become one anycast prefix. NetGraph priorities (lower first) map to
NetSim priorities (higher first). The failure policy becomes a
`FailureSchedule` only when `iterations > 0`; for studies, use
`Draws.from_policy`. With `srv6=True` every device gets an F3216 locator, uN
and uDT46, every L3 link end a uA, and a pairwise demand with one explicit
`StaticPath` becomes an SR policy.

Strict mode, the default, accepts only the `SHORTEST_PATHS_ECMP` and
`SHORTEST_PATHS_ECMP_LOSSY` flow policies, the `combine` and `pairwise`
modes, the `flatten` group mode, and static paths only with `srv6=True`.

Per-entity settings are read from `attrs`:

| Entity | In `attrs.netsim` only | In `attrs` or `attrs.netsim` |
|---|---|---|
| node | `fib_delay`, `fast_failover`, `mtbf`, `mttr`, `ttf`, `ttr` | `loopback_ipv4`, `loopback_ipv6` |
| link | `carrier_delay_down`, `carrier_delay_up`, `mtbf`, `mttr`, `ttf`, `ttr` | `source_interface`, `target_interface`, `lag`, `min_links`, `reverse_cost` |
| risk group | `mtbf`, `mttr`, `ttf`, `ttr` | |
| demand | | `allow_bundle_pins` |

Entities that set both `mtbf` and `mttr` form `Study.failure_parameters`,
the renewal process of the `NetSimStudy` process mode.

Importing `netsim.adapters.ngraph` registers the `NetSimStudy` workflow step:

```yaml
workflow:
  - type: NetSimStudy
    name: transients
    demand_set: traffic
    failure_policy: single_link_failure
    iterations: 50
    seed: 42
    mode: iterations          # or process (rate, duration, horizon) or replay (results_json, step, select)
    addressing: unnumbered
    capacity_unit: 1000000000
    keep: {roots: 0, deltas: 0, arrays: false, timeline: false}
```

`netsim run scenario.yaml --results results.json` runs the scenario with
NetGraph and writes the complete results.

## SONiC adapter

`sonic.load(source)` takes a mapping, JSON text or a `pathlib.Path`; a plain
string is parsed as JSON text. `sonic.dump(network, destination=None)` returns
the mapping and also writes it to `destination` when one is given.
`sonic.appl_db(network)` returns the APPL_DB view. All three use the envelope
`{"version": 1, "devices": {"R1": {"TABLE": {"key": {"field": "value"}}}}}`.
Devices are unconnected on load; add links with
`net.add_link((device, interface), (device, interface))`.

| Table | Fields |
|---|---|
| `PORT` | `speed` (Mbit/s, default 10000), `mtu` (1500), `admin_status` |
| `INTERFACE`, `LOOPBACK_INTERFACE` | keys `interface` and `interface\|address/prefix` |
| `STATIC_ROUTE` | `nexthop` and/or `ifname` as comma-separated strings, or `blackhole: "true"`; `distance` (1 to 255, default 1) |
| `SRV6_MY_LOCATORS` | `prefix`; `block_len`, `node_len`, `func_len`, `arg_len` (default 32/16/16/0, a classic locator; micro-SIDs need `arg_len: 64`); `vrf` (default only) |
| `SRV6_MY_SIDS` | key `locator\|prefix`; `action` (`End`, `End.X`, `End.DT46`, `uN`, `uA`, `uDT46`), `flavors` (`psp`, `usd`, `usid`), `interface`, `adj`, `decap_dscp_mode` (`pipe` only), `decap_vrf` (default only), and the four `*_len` fields |
| `SRV6_SID_LIST` | `path`: literal IPv6 addresses or objects with `sid`, lengths and `flavors` |
| `SRV6_POLICY` | `color`, `endpoint`, `candidate_paths`, `bsid`, `fallback` (`IGP`, the default, or `DROP`) |

A candidate path has `preference` (default 100), `name`, `segment_lists`,
`protocol_origin`, `originator` and `discriminator`. Each `segment_lists`
entry is `{"name": ..., "weight": ...}`, naming an `SRV6_SID_LIST` entry; the
weight defaults to 1.

Unknown tables or fields, unsupported behaviours and non-default VRFs raise
`SchemaError` with the entry path. Load followed by dump returns the input
except for key order. APPL_DB output lists the forwarding-order wire SIDs of
each SID list.

`dump` raises `SchemaError` for configuration that version 1 cannot express:
bundles, unnumbered interfaces, symbolic segments, an interface metric other
than 1, descriptions, explicit `forwarding_v4` or `forwarding_v6`, carrier
delays, an MTU outside 1280 to 65535, speeds that are not whole Mbit/s,
disabled devices, `srv6_source`, a non-default `srv6_hop_limit`, SIDs or
policies not owned by static configuration, and steering rules. Derived
routes, such as the oracle IGP's, demands and agents are not configuration
and are not exported. The device settings `fib_delay` and `fast_failover`
are dropped without an error.
