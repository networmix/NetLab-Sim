# NetSim network layer: design (revision 17: Gate C implemented and confirmed)

> **Rename, 2026-10-02:** the project is now NetGraph-Sim: distribution `ngraph-sim`, package `ngraph_sim`, CLI `ngraph-sim`, scenario keys `attrs.sim` / `data.sim`, workflow step `SimStudy`. Paths `netsim/...` and the old names below refer to the same code, now in `ngraph_sim/`. The repository is github.com/networmix/NetGraph-Sim and the checkout `~/ws/NetGraph-Sim`. Legacy and compatibility paths described below (Study `settle` mode, `keep_*` aliases, top-level NetGraph attrs, `strict=False`, `Simulation.recorder`, unbound NHT keys, untagged deliveries) were removed on 2026-10-02.


## Context and scope

NetSim started as a zero-dependency discrete-event engine (`netsim/core.py`,
`netsim/resources.py`); Gates A and B below are implemented on `main`
(2026-09-20). The goal is a network layer that simulates devices
with a RIB and a FIB, three interface kinds (Loopback, Ethernet,
PortChannel with min-links), IPv4/IPv6/MAC addressing and UP/DOWN events,
and uses that forwarding state to **place flows (demands) and compute
capacities and utilization** as topology and routing state change over
time, including **traffic engineering with SRv6** (flows on pre-defined
paths expressed as SR Policies, micro-SIDs included). Packets (Ethernet +
IPv4/IPv6 header objects with an SRH) assist placement: hash-based path
selection for a microflow, loop, blackhole, MTU and TTL detection, tracing
and SRv6 header processing. They are not a per-packet queueing simulation.

The design is delivered in three **gates**; each gate is a shippable,
tested simulator, and nothing from a later gate is a dependency of an
earlier one:

- **Gate A**: immutable state tree, explicit scheduler rounds,
  interfaces and LAG with physical-failure accounting, static and oracle
  RIB/FIB, the plain-IP forwarding records and action interpreter
  (`forwarding.py`), plain-IP FLUID and HASH utilization under failures,
  adapters with `srv6=False`.
- **Gate B**: the same interpreter extended with exactly the supported SR
  behaviours. **Authoritative Gate B behaviour set:** H.Encaps and
  H.Encaps.Red at the headend; End and End.X with the PSP and USD flavors
  (USP rejected); default-table End.DT46; NEXT-C-SID applies to End,
  End.X and End.DT46 (uN, uA, uDT46). Rejected in Gate B with explicit
  errors: on-wire B6 (End.B6.Encaps, uB6), nested encapsulation of an
  already encapsulated packet, End.DT4, End.DT6, End.DX4, End.DX6, VRF
  table selection. Local BSID-to-policy steering (a next hop resolving to
  the headend's own BSID) is supported and is distinct from an on-wire B6
  endpoint. Gate B includes the minimal owner-scoped SID and policy
  operations (`SidClient`, `PolicyClient` with one owner per policy);
  Gate C adds agent execution and transport. One-owner SR Policies and
  tested rate and capacity accounting complete the gate. Every table,
  pseudocode block, adapter and acceptance row below is read under this
  set; behaviours listed for completeness but not in the set are
  post-Gate-C work.
- **Gate C**: scoped client and NHT contract, one minimal scoped FIFO
  connection service (incarnations, timeouts) plus link channels, a
  minimal link-state reference agent with cold-start tests.

Later gates extend existing modules; no later gate supplies a
dependency an earlier gate needs.

Deferred beyond Gate C, with named extension points: transport features
beyond the enumerated connection service, full Open/R and BGP, stateful
controllers, multi-client BSIDs, nested B6, resilient hashing,
REPLACE-C-SID, midpoint protection, VRFs, runtime checkpoint and restore,
broad adapter round trips, in-band protocol transport.

## Provenance

| NetSim concept | FBOSS | FRRouting | SONiC | Cumulus / Linux |
|---|---|---|---|---|
| Immutable versioned state tree; deltas | `SwitchState`, `StateDelta`, `HwSwitch::stateChanged` | | CONFIG_DB / APPL_DB / STATE_DB | |
| Derivations in dependency order | `StateObserver`s | zebra meta-queue | orchagent PortsOrch → IntfsOrch → NeighOrch → RouteOrch | |
| Oper state values | | | | netdev `operstate` = RFC 2863 |
| Routes keyed by client with distance | `RouteNextHopsMulti` by `ClientID`, `AdminDistance` | `zapi_route(type, instance, distance, metric)`, `connect` / `local` types | STATIC_ROUTE `distance` | |
| Next-hop kinds; SRv6 on the next hop | `NextHop` (`srv6SegmentList`, `tunnelType`) | `NEXTHOP_TYPE_*`, `blackhole_type`, staticd `segments` | ROUTE_TABLE `nexthop / ifname / weight / segment / seg_src` | `encap seg6` |
| Next-hop groups with ids | | `nhg_hash_entry` | NEXTHOP_GROUP_TABLE | kernel nexthop objects |
| Asynchronous RIB → FIB with status | | dataplane, `ROUTE_ENTRY_QUEUED / INSTALLED` | fpmsyncd → orchagent → ASIC_DB | kernel FIB, `switchd` |
| Client route API, NHT | `FbossCtrl` / `FibService`: `addUnicastRoutes(clientId)`, `syncFib`, `registerNextHops`, `streamNextHopStatus` | ZAPI `ROUTE_ADD/DELETE`, `NEXTHOP_REGISTER/UPDATE`, `REDISTRIBUTE_*`, `INTERFACE_*`, SRv6 SID manager | | |
| State store with subscriptions; agents never talk directly | FSDB path pub/sub | | Redis tables | Arista EOS Sysdb (same pattern) |
| LAG with min-links, member forwarding state | `AggregatePort.minimumLinkCount`, `portToFwdState` | | PORTCHANNEL `min_links`, member `status` | bonding `min_links`, `xmit_hash_policy` |
| ECMP / LAG hashing, resilient hashing | `LoadBalancer` (ECMP, AggregatePort) | | | per-switch seed; resilient nexthop groups |
| Local SIDs, micro-SIDs | `MySidFields` (uN, uA, uDT46, uB6), SAI `MY_SID_ENTRY` | locators, `format usid-f3216`, `seg6local` | SRV6_MY_LOCATORS / SRV6_MY_SIDS, `Srv6Orch` | `seg6local` actions and flavors |
| Unnumbered | | | | BGP unnumbered (RFC 8950) |

## Decision: topology representation

NetSim owns an interface-centric model in its own state tree. NetGraph
`Network` has no interface, address, LAG or SID concept and costs ~0.27 s
plus networkx, pandas, jsonschema and the compiled Core extension to
import; NetGraph-Core is an immutable int-indexed compute kernel with one
`int64` per edge. NetSim's history records the pain of a hard ngraph
dependency. Both are optional extras (`netsim[ngraph]`): NetGraph for
authoring and interchange, Core as an accelerator and an independent
cross-check for plain-IP placement. SONiC CONFIG_DB JSON is a
dependency-free configuration format. The core package keeps zero
runtime dependencies.

## Architecture: four layers

```
netsim.core / netsim.resources   DES engine: clock, heap, Process, resources (existing; + DEFERRED = 8)
netsim.model                     clock-free: state tree, deltas, handles, derivations, packet actions, converge()
netsim.runtime                   binds the model to the clock: rounds, kinds, observation, agents, transport
netsim.adapters                  NetGraph, NetGraph-Core, SONiC CONFIG_DB
```

Dependency direction is strict: `core ← model ← runtime ← adapters`.

```
netsim/
  core.py            + DEFERRED = 8 (base of the reserved settle band); nothing else changes
  model/
    addressing.py    AddressFamily, MacAddress, EUI-64, address normalization (ints inside the model)
    lpm.py           PrefixTable (dict per prefix length; swappable)
    packets.py       EtherType constants, EthernetFrame, IPv4Packet, IPv6Packet, SRH (validated), L4Header, FlowKey,
                     PacketTemplate, wire size of a header stack
    hashing.py       LoadBalancer (field sets, seed, HASH_THRESHOLD | RESILIENT), flow_hash, region select, tables
    state.py         NetworkState, DeviceState, records, PMap (owning, transitively immutable), StateDelta, paths,
                     canonicalization, generations
    interfaces.py    enums; interface config and oper records; derive_ethernet / derive_lag (component two-pass)
    links.py         LinkConfig, LinkOper, physical transfer availability
    routing.py       Nexthop, Route, RibState (sharded), ResolutionPolicy, resolve_fib(), per-row outcomes, epochs
    srv6.py          SidStructure, Locator, allocator, LocalSid, compression (§6.2), SegmentList, SrPolicy, validation
    forwarding.py    Adjacency, NexthopGroup, FibEntry, Fib, NeighborTable, the action program (forward step)
    flows.py         Demand, DemandSet, TrafficClass, forwarding-equivalence classes, leg walk (SCC), capacity models,
                     PlacementReport
    igp.py           RouteSource: per-device Dijkstra, ECMP, locators
    contracts.py     ClientId, RibClient, PolicyClient, SidClient, NhtClient, agent / source / controller protocols,
                     AgentContext / GlobalContext, AgentOutput, SessionEvent, SrDbView, op records
    derive.py        every derivation and the kind order (used by converge() and runtime/pipeline.py)
    entities.py      Device, Interface, Link handles (generation-checked) and the builder / operations API
    network.py       Network: state, update(), clock and observation hooks, validation, converge(), place(), trace()
  runtime/
    pipeline.py      Coordinator: rounds, kinds (COALESCE | DEBOUNCE), StageEvent, ROUND_END, retry, convergence limit
    events.py        observation queue (SETTLED deliveries with snapshot roots), Stats
    timeline.py      Timeline: Record(seq, time, round, origin) + flat typed events per delta, bounded delta/root retention,
                     series from placement arrays, rows()/to_csv() export
    simulation.py    Simulation: bind, settle(), run_until(), at(), send(), retry(), reset_agent()
    agents.py        context views, inboxes and outboxes, AGENT and IGP kinds, run_delay, RNG and stats buffering
    transport.py     LinkChannel, Session (scoped endpoints, incarnations, sequence numbers), liveness, timers
  agents/            reference.py (Gate C); openr.py, bgp.py (deferred)
  adapters/          sonic.py (no dependencies), ngraph.py, core.py
```

## Data model: the state tree

### Principle

All simulated state lives in one immutable tree, `NetworkState` (FBOSS
`SwitchState`). Nodes are frozen slotted records; maps are `PMap` (an
owning, unexposed backing dict copied on set; content `__eq__`; structural
sharing at the map level; batch edits go through a private builder that
copies each touched shard once per commit). An update produces a new root
and a `StateDelta(old, new)`; unchanged subtrees are the same objects so
diffs are identity-first. Within a node, **config** (intended) and
**oper** (derived) are separate records (RFC 8342), and every oper record
or client-keyed config entry has exactly one writer.

**Transitive immutability.** Every committed leaf is transitively
immutable: `PMap` copies or rejects mutable inputs; numeric report data
is committed as `bytes` plus immutable shape and type metadata, and
accessors return a **fresh** read-only `memoryview` (or an immutable
numeric wrapper) per call, so no caller ever receives the object stored
in a snapshot and releasing a returned view cannot invalidate the report
or another reader; never `array` or `list`; agent state, messages and
payloads follow the same contract (frozen records, tuples, `PMap`,
`bytes`), checked in debug mode by a recursive validator; RNG state is an
immutable value committed with the record. Nothing aliases a caller-owned
container.

**Canonicalization.** A derivation compares its recomputed record with the
old one by value and returns the old object when equal; per-row records
are reused the same way; `version` fields bump only on content change;
`since` fields carry forward when the value is unchanged. `update()`
computes the delta before commit and returns `None` for an empty content
delta, so a run on unchanged inputs commits nothing. Agent state is
compared by identity only (agents return the same object when nothing
changed).

**Tree equality** for tests is modulo `version` and every `since` field.

**Handles.** `Device`, `Interface`, `Link` are cached handles keyed by
(kind, key, generation); every entity gets an immutable generation at
creation; identity, equality and hash use (network, kind, key,
generation); every access validates the generation, `exists` is false for
an obsolete generation even if the name was reused; handles carry
`__dict__` for user attributes (as resources do in
`tests/test_invariants.py`).

**Paths.** Every tree location has a canonical path of typed components
(`("devices", "R1", "interfaces", "eth1", "oper")`) with a reversible
escaped string form; imported names (NetGraph uses `/`) are preserved
without changing path identity; globs are a separate query syntax.
`StateDelta.changed_paths()` is lazy; subscriptions (kinds, agents,
recorder, tooling) match by path prefix through a prefix index.

### Tree and nodes

```
NetworkState(version, devices, links, demands, traffic_classes, placement | None, transport,
             allocators: Allocators(next_mac, next_link_index, generations, per-device next_ifindex, SID allocators))
DeviceState(config, oper: DeviceOper(router_id), interfaces, ribs[af], fibs[af], resolver_epoch[af],
            neighbors, nexthop_groups, load_balancers, srv6_config, srv6_sids, srv6_policies,
            agents: PMap[name, AgentNode(config, state, srdb_view)], nht)
InterfaceNode = LoopbackNode | EthernetNode | PortChannelNode      identity (index, generation), config, oper
LinkNode(id, index, generation, a, b, config: LinkConfig, oper: LinkOper(state, since))
StateDelta sections: links, config(device), interface_oper(device), rib_rows(device, af), neighbors(device),
    srv6_sids(device), srv6_policies(device), nexthop_groups(device), fibs(device, af), nht(device),
    agents(device), transport, demands, placement
```

| Node | Config (intended) | Oper (derived) | Writer |
|---|---|---|---|
| Device | enabled (+ since), seed, fib_delay, resolution policy, router_id, srv6 source address, srv6 hop limit, srdb_source | router_id | operations / L3 |
| Loopback | admin (+ since), description, ipv4, ipv6 | oper, reason, since | L3 |
| Ethernet | admin (+ since), description, mtu, speed, metric, ipv4, ipv6, unnumbered, forwarding per AF, aggregate_id, carrier_delay_up / down | oper, reason, since, carrier_raw, carrier_raw_since | CARRIER |
| PortChannel | admin, description, mtu, metric, ipv4, ipv6, unnumbered, forwarding per AF, min_links, member_delay_up / down | oper, reason, since, members: PMap[name, MemberOper(candidate, candidate_since, active)], bandwidth | LAG |
| Link | capacity override, delay, risk_groups | state (UP / FAILED), since | operations (fault injection) |
| RibState (per AF) | rows by client key (sharded by prefix length and a radix sub-shard) | | clients through the one door |
| Resolver input epoch (per AF) | | advanced atomically by `Network`'s commit machinery with every relevant input commit | commit machinery |
| Resolver outcome (per AF) | | processed epoch (the input epoch consumed), per-row outcomes | FIB |
| NeighborTable | | (interface, scope, address) → mac | L3 |
| Srv6Sids | locators, local SID config, SID requests | allocated SIDs with adjacency state, My-SID view | L3 |
| Srv6Policies | policies and candidate paths (one owner per policy in v1), steering entries | policy states | FIB |
| NexthopGroupTable, Fib (per AF) | | groups; entries, version | FIB |
| LoadBalancers | ecmp, lag: field sets, seed, mode, buckets | | operations |
| Agent | agent config | opaque state, srdb_view | AGENT |
| NHT | registrations by (client, af, address, scope, options) | results | FIB |
| Transport | sessions opened by agents | channel liveness, session connection state | TRANSPORT |
| Demands, TrafficClasses | rows | | operations |
| PlacementReport | | read-only arrays per directed edge, per-demand results, caches, version | PLACEMENT |

Conventions: membership on the member (`aggregate_id`); addresses only on
L3 interfaces; `index` (ifIndex, creation order) is the canonical sort
key and comes from the tree's allocators so a failed update leaves no
gaps; loads live only in the `PlacementReport`; a route is one frozen
row; names may not contain `|`, `:`, `--` or `/` unless imported (then
escaped).

### Addressing and LPM

`MacAddress(int)` (validated 48-bit, parse/format, multicast and local
bits, `eui64()`, `link_local()`). IP addresses are `ipaddress` objects at
the API boundary only; **no `ipaddress` object is used inside
derivations, the forward step or placement**, and `hash()` of one is
never used. `PrefixTable[T]` in `lpm.py`: dict per prefix length,
descending tuple of populated lengths, per-instance masks; O(k) probes;
brute-force reference test.

## Event model

### `Network.update(fn, origin) -> StateDelta | None`

`fn` is a pure function from the current root to a candidate root.
`update()` validates and canonicalizes the candidate, computes the delta
and timestamps (`Network.clock()`, default `lambda: 0`, the runtime
installs `env.now`) **before** commit, returns `None` for an empty content
delta, commits once (bumps `version`), then hands the delta to the
observation queue. Internal notification preparation completes before
publication; observer exceptions after commit are reported as observer
failures and never roll back the committed root. On any exception before
commit the root and the allocators are unchanged and the exception
propagates. A nested `update()` from inside a derivation or observer
raises `RuntimeError`; observers may only mark kinds dirty, append to the
log and enqueue deliveries.

### Kinds and modes

One `StageKind` per band, not one stage per entity. A kind keeps pending
work per entity and runs the entities due at a time in sorted order in
one `update()`, so each kind emits one delta per round.

- `COALESCE` (LAG, L3, IGP, AGENT, FIB, TRANSPORT, PLACEMENT): one pending
  deadline per entity. A cause at `t` with delay `d` requests `t + d`; the
  entity keeps the **earliest** requested pending deadline: a later
  request joins the pending run, an earlier request advances it (the
  implemented rule); the deadline clears when a run claims the work, and
  causes arriving during or after the claim schedule the next run. Entities sharing a deadline share one `StageEvent`.
- `DEBOUNCE` (CARRIER, LAG member timers): absolute deadlines. On a raw
  input change the kind records `raw` and `raw_since = now` (one observed
  transition per operations batch), picks `delay(new raw value)` and
  schedules at `scheduled_at = max(now, raw_since + delay)`; a run applies
  the change only if `now >= scheduled_at` recomputed from the current
  tree, else reschedules at the new deadline. Same-timestamp raw changes
  collapsed by one batch are one transition.

Durations are validated finite and non-negative; event times finite;
asynchronous message and timer deadlines must satisfy `scheduled_at >
now` after conversion to the engine's float time (a delay that does not
advance the float clock is rejected). Tests use one supported time
quantum (integer or dyadic seconds).

`StageEvent` is an `Event` subclass with `__slots__` scheduled through
`env.schedule(event, priority, delay)`, the pattern `run(until=t)` uses;
`Timeout` is untouched; `tests/test_invariants.py` scans `netsim.runtime`
for Event subclasses.

### Rounds (the coordinator owns ordering; priorities only order within a round)

```
NORMAL    = 1            operations, user processes, deliveries, timer firings
CARRIER   = DEFERRED+0   LAG = +1   L3 = +2   IGP = +3   AGENT = +4   FIB = +5   TRANSPORT = +6   PLACEMENT = +7
ROUND_END = DEFERRED+8   coordinator sentinel
SETTLED   = DEFERRED+9   observation deliveries
```

The heap orders events by (time, priority, eid); it does not know
dependencies. The runtime **coordinator** turns that into rounds:

1. A round at time `t` is the set of kind runs scheduled at `t` before
   its `ROUND_END` sentinel. Kinds run in priority order. **Exactly one
   round is active at a timestamp.** `StageEvent`s and `ROUND_END` carry
   a round generation; events of a stale generation do nothing.
2. Each entity's pending **deadline is computed first** (COALESCE or
   DEBOUNCE rule). Work due after `now` belongs to that future timestamp
   and is not part of any current round. For work due now: a forward
   invalidation (a kind of higher priority than the running one) joins
   the current round; a backward or already-executed invalidation (lower
   or equal priority, or a kind that already ran in this round: AGENT SID
   requests → L3, FIB → AGENT via NHT and policy states, TRANSPORT →
   AGENT, PLACEMENT → controllers) joins the **successor** round at `t`.
   FIB → AGENT with `run_delay = 0.001` is therefore work at `t + 0.001`,
   not a round at `t`.
3. `ROUND_END` finishes the round: if successor work exists the
   coordinator schedules those kinds and a new `ROUND_END` at `t` with the
   next generation; otherwise it releases the observation deliveries for
   `t` at `SETTLED`.
4. Every round, including SID-allocation rounds, counts against
   `Simulation.max_rounds_per_timestamp` (default 10 000); exceeding it
   raises `ConvergenceError(time, rounds, last_origins)`. With positive
   delays a timestamp normally needs one round.

Non-band events (NORMAL, URGENT) can interleave with an active round: an
operation, a user process resumed by a condition, a resource completion
or a process termination may schedule NORMAL or URGENT events at `now`.
A state change from such an event uses the same rule as any other cause
(forward work joins the active round, backward work its successor); it
never opens a second concurrent round. The band itself never schedules a
NORMAL event for the current time. The log records `(time, round, origin,
delta)`.

### Dependency and invalidation matrix

The runtime keeps an **explicit invalidation matrix** from input paths to
owning kinds, and every edge has an insertion, withdrawal, replacement and
recovery test. Until an incremental rule is proven, invalidation is
conservative: every SR consumer on any SR-DB change; every local AF on any
resolver-input change; every session whose recorded dependency set
intersects the change. Dependency records track **lookup queries,
including failed lookups**, not only returned prefixes, so a newly
inserted more-specific route or a formerly absent SID re-triggers.

| Kind (entity) | Inputs |
|---|---|
| CARRIER (Ethernet e) | link state, link replacement (old and new endpoints); admin and enabled of e's device and of the peer's device; e.config; peer config |
| LAG (PortChannel p) | oper of p's members; p.config; oper of the members' peers; config of peer bundles; link capacity of members |
| L3 (Device d) | oper and config of d's interfaces; peer interface config (addresses, MAC, forwarding enablement) and endpoint replacement where they affect scoped neighbors; d's config (enabled, router_id, srv6); SID requests |
| IGP (Device d, AF) | interface oper, metric, addresses, unnumbered and forwarding flags of every device's L3 interfaces; device enabled; links; locators |
| AGENT (Device d, agent) | the agent's subscribed local paths; its inbox (deliveries, timers, session events) |
| FIB (Device d, AF) | rib rows of d (both AFs); interface oper and forwarding flags of d; neighbors; NHT registrations; load balancer config; **every config value captured in its compiled programs** (SRv6 source address, hop limit, encapsulation behavior); srv6_sids, policy config, `srdb_view` and srdb_source; SR-DB inputs recorded in `srdb_deps[d]` (conservative: all SR-DB changes) |
| TRANSPORT (session s) | interface oper and link config of link channels; **physical link state and endpoint availability**, fibs, groups, policy states, steering, interface oper and link delay of every device in `s.deps` (devices visited by the previous run's forward steps, both directions) |

Dependencies are invalidated **directly** from the changed input, even
when an intermediate derivation returns an unchanged record.
| PLACEMENT (class c) | the class cache's recorded dependencies: consulted FIBs, groups, interfaces, links (physical state and capacity), SID and policy actions, steering, load balancers, demands, traffic classes; the previous PlacementReport |

### Failures and retry

A derivation exception propagates out of `env.run()`; the engine has
already popped the event and cleared its callbacks. The failed kind
retains its captured work and marks itself retryable without
rescheduling; `Simulation.retry()` is explicit (called after the
configuration is corrected; `settle()` does not call it) and schedules a
fresh `StageEvent` for each retryable kind. Work is claimed before the run
and consumed by publication: a failure **before** publication (the
derivation raised) keeps the claimed work retryable; a failure **after**
publication (an observer raised; `Network.update` re-raises it marked as
published, see `published_failure()`) leaves the committed root in place and the work consumed,
so a retry never re-executes a published run. A retried agent run consumes
the same captured inbox prefix once.

### Observation and quiescence

`EventBus.next()` / `wait_for()` deliveries are **separate events per
subscriber**, released at `SETTLED` after the last round of the
timestamp. Each delivery carries its triggering delta(s), whose
historical roots stay as committed (a CARRIER delta's root is pre-LAG),
plus `settled_root`, captured immediately before that delivery after all
currently due rounds finished. Internal commit hooks cannot call
`update()`; public SETTLED deliveries run outside that guard and may
write, in which case the write starts new round work before the next
delivery is processed. Multiple callbacks on one engine event share no
barrier (the engine runs them back to back); the observation queue is
therefore the only settled view, and tests distinguish cause roots from
`settled_root`. `Timeline` retains the last root per timestamp for the
most recent `keep_roots` timestamps (bounded by default) plus a bounded
deque of `(time, round, origin, delta)`; `snapshot_at(t)`,
`series(path)`, `utilization_series(edge)`. A `Stats` store outside the
tree keeps timestamped counters.

`Simulation.settle(max_steps=100_000)` steps while `env.peek() ==
env.now` (the cap limits dispatched events, not instructions inside a
callback). `run_until(t)` = `env.run(until=t)` if `t > now`, then
`settle()`; `env.run(until=t)` alone stops at a newly inserted URGENT
event, so previously scheduled URGENT events at `t` with smaller eids
still run and NORMAL ones stay pending. `at(t, fn)` schedules an
operation. Binding: `Simulation(env, net)` raises if already bound,
installs the clock, runs a synchronous full derivation with delays
ignored (timeline root 0). `Network.converge()` (clock-free) runs
`model/derive.py` kinds in order ignoring delays, RouteSources included,
DeviceAgents and Controllers excluded, repeating until clean with an
iteration cap.

Tree snapshots support inspection and state-delta replay only. Restarting
execution would need a runtime checkpoint (time, scheduler ids, pending
work, timer and session generations, inboxes and outboxes, dirty rounds,
RNG and stats); that is deferred, and snapshots are not advertised as
protocol replay.

## Interfaces, links and physical failure

Enums are API-boundary values; hot-path oper fields are small ints.
`OperState` uses RFC 2863 values (UP, DOWN, LOWER_LAYER_DOWN, NOT_PRESENT).

Rules:

- Loopback: UP iff admin UP and device enabled.
- Ethernet: admin DOWN or device disabled → DOWN immediately; no link →
  NOT_PRESENT; raw carrier = link UP and peer admin UP and peer enabled;
  effective carrier after debounce; UP iff effective carrier, else DOWN
  with CARRIER or PEER_ADMIN.
- PortChannel, computed **per connected component of bundles** in three
  passes from one snapshot of interface oper and config: (1) candidates
  and candidate stability timestamps for every bundle in the component
  (member oper UP, peer port bundled); (2) every bundle's `min_links_ok`
  (admin UP, enabled, `len(candidates) >= min_links`); (3) active sets
  (candidates whose peer bundle has `min_links_ok` and whose member delay
  elapsed), oper (DOWN if admin DOWN or disabled; UP iff `len(active) >=
  min_links`; else LOWER_LAYER_DOWN with MIN_LINKS / PARTNER / MEMBERS) and
  bandwidth (sum of active members' link capacities; recomputed on
  capacity changes). The component commits together, so bundle sort order
  cannot change partner results.
- `l3_usable(af)` = oper UP, not bundled, and forwarding enabled for that
  AF (explicit per-AF flag, default: enabled iff the interface has a
  global address of that AF or is `unnumbered`; an IPv4-only link
  therefore does not forward IPv6 unless enabled explicitly, which the
  Gate-B fixture does).
- A PortChannel whose members terminate on different peer bundles is
  **rejected** at configuration (or, if imported, kept as invalid
  configuration with no candidates and reason `MULTIPLE_PARTNERS`); an
  active L3 bundle always has one unambiguous peer bundle.

**Physical transfer availability** is separate from observed oper state.
A directed edge can carry traffic iff the link is UP and both endpoint
interfaces are physically usable (admin UP, device enabled, present).
Every transmission, in the forward step, in FLUID legs and in timed
messages, checks this and rejects with `LINK_DOWN` or `RX_DOWN` while the
attempted transmission is still charged as `offered`. Routing may stay
stale through carrier delay and FIB delay; that transient is what the
utilization series shows.

`Link`: capacity = override or min of speeds, `delay`, `fail()` /
`restore()`. Validation: unique names; one link per Ethernet on different
devices; members are Ethernets on the same device, unbundled, without
addresses; no duplicate or overlapping addresses per device; MTU
≥ 1280 with IPv6; positive metrics, speeds and capacities; `min_links ≥
1`; effective member and bundle MTUs consistent; unique MACs; single peer
bundle per PortChannel; SRv6 rules.

## Routing

### Clients and rows

```
ClientId(name, instance=0)                    identity
ClientProfile(client, distance, protocol_origin: int (RFC 9256 §2.6: CLI 30, BGP SR-TE 20, PCEP 10), originator)
Route(prefix, source: ClientId, distance, metric=0, nexthops, distinguisher=(), tag=None, attrs=(), table=0)
Nexthop(interface=None, address=None, scope=None, special=None, srv6=None, policy=None, weight=1, onlink=False)
  interface only | interface + address (link-local requires scope = interface) | address only (recursive, resolved
  in the RIB of the address's family) | special BLACKHOLE | UNREACHABLE | PROHIBIT | RECEIVE | SRV6_LOCAL(behavior)
  | srv6 = Srv6Encap(segments (symbolic or literal), behavior H_ENCAPS_RED | H_ENCAPS, source) | policy = PolicyRef
```

`ClientId(name="static", instance=0)` with profile distance 1 is
reserved for operations (`Device.add_route(prefix, nexthops=[...],
distance=1, distinguisher=())` is sugar over one row with possibly
several next-hops); `ClientId(name="igp", instance=0)` with distance 110
is the oracle; agents register their own identity and profile. Examples
in this document that write `("static", 1)` or `("igp", 110)` name
(identity, distance). `RibClient.add_routes` upserts by
(prefix, source, distinguisher) and is a no-op for an identical row;
`delete_routes(keys)` ignores missing keys; `sync(rows)` replaces all rows
of the client in the AF in one update reusing unchanged rows; rows are
validated before commit (family, source, next-hop shape); an output holds
per AF either `sync` or delete-then-add. Duplicate client ids are
rejected at registration; ties between different sources at equal
(distance, metric) break by `ClientId` ascending.

### Route status and outcomes

Each (device, AF) has a **resolver input epoch**, advanced by the commit
machinery atomically with any FIB input commit (rows, interface oper,
neighbors, registrations, SR inputs), and a **processed epoch** written
by the FIB kind together with the outcomes, recording the input epoch it
consumed; writing FIB outputs never re-invalidates its inputs. A row is `PENDING` iff the
input epoch is ahead of the processed epoch (an unchanged static row is
pending when an interface change queues work); otherwise its immutable
**per-row outcome** from the last run says `INSTALLED` (with the group it
contributed to) or `NOT_INSTALLED(reason)`, and `SELECTED` means it is in
the group `best_groups()` would choose. Programming state and current
selection are exposed separately; `INSTALLED` does not imply live egress.
Owner notifications cover row deletion and interface- or policy-driven
outcome changes as well as FIB entry changes.

### Selection and resolution (`resolve_fib`)

Best-first groups of equal (distance, metric, source) with unioned
next-hops; rows from different sources never merge. Within a group the
action precedence is a **simulator policy**, not an RFC rule: a
homogeneous special action overrides forwarding legs; different special
actions in one equal-ranked group are rejected with `AMBIGUOUS_ACTION`.
The first group with a resolvable leg (or all legs under
`ALL_OR_NOTHING`) is active; otherwise `NOT_INSTALLED` and LPM falls
through to a covering prefix (`lpm_fallthrough=True`, kernel and zebra
behaviour; fallback across candidates and across prefixes are separate
documented steps).

```
resolve_nexthop(owner, nh):
  interface only / interface + address: require l3_usable(egress AF) first (cross-AF next hops also require the
      relevant neighbor-discovery enablement); then require a usable scoped adjacency: peer MAC on the p2p link
      or bundle for interface-only (connected-prefix recursion keeps the final destination), the scoped neighbor
      entry for that address otherwise; onlink bypasses prefix-membership validation only and never fabricates a
      MAC; failure is an unresolved leg before candidate selection
  address only: LPM in the RIB of the address's family excluding the gray stack (never through itself);
      RECEIVE -> unresolvable (never a recursive forwarding or drop result); DROP_* -> unresolvable, or a drop leg
      only when resolve_via_drop; SRV6_LOCAL(B6) -> resolve_policy; FORWARD -> child legs
  srv6 encap: compile the action program (below); first-entry feasibility uses the same local-action dispatch as
      transit (a matched local SID returns its continuation), not the address-only cases
  policy: valid lists of the active path, each an encap leg weighted by list weight
weights: child shares are normalized within each parent, multiplied by the parent's weight, equivalent legs
  merged, then truncated to max_ecmp_paths in a stable order (interface index, next-hop, encap) and renormalized
outcome: FibEntry(prefix, action program | group id, contributing row keys, rejected rows with reasons, depends_on:
  queried prefixes incl. failed lookups, interfaces, policies, SIDs)
```

`ResolutionPolicy` defaults: `resolve_via_default=False`,
`unresolved=PARTIAL`, `max_recursion_depth=8`, `max_ecmp_paths=64`,
`lpm_fallthrough=True`, `resolve_via_drop=False`, `validate_all_sids=True`.

### Neighbors, AF enablement, unnumbered (RFC 8950)

The L3 kind derives neighbor entries for configured peer addresses on the
attached p2p link or bundle (numbered) and for the peer's EUI-64
link-local when IPv6 forwarding is enabled (bundle MAC for bundles).
Entries are keyed (interface, scope, address). IPv4 prefixes may use
interface-only next-hops or interface + scoped IPv6 link-local next-hops;
the frame uses EtherType 0x0800 with the MAC from the IPv6 entry.
Numbered, unnumbered and cross-AF paths are tested separately.

### `igp.py` (oracle RouteSource)

Per device and AF: Dijkstra over interfaces with `l3_usable(af)` and
their metrics, ECMP successors, destinations = every device's loopback and
interface prefixes plus locator prefixes; rows `("igp", 110)` via `sync`.
Runs in the IGP band for dirty AFs; NetGraph-Core `spf_to` accelerates it
when installed. This makes unnumbered NetGraph imports routable in Gate A.

## Forwarding as an action program (`model/forwarding.py`)

Every forwarding decision compiles to an ordered **action program** over
a packet with stage metadata (`ORIGINATED | TRANSIT | AFTER_ENCAP |
AFTER_DECAP`): `L2_CHECK`, `STEER`, `LOOKUP`, `ENCAP(list)`,
`LOCAL_SID(behavior)`, `TTL`, `SELECT_GROUP`, `SELECT_MEMBER`, `MTU`,
`TRANSMIT(edge)`, `DELIVER`, `DROP(reason)`. Probes, the timed driver,
HASH placement and the resolver's compiled entries all execute the same
program interpreter, and compiled entries must be trace-equivalent to the
uncompiled step (a property test).

Order for a packet arriving on an interface:

1. `L2_CHECK`: ingress oper UP else `IFACE_DOWN`; `dst MAC ∈ {ingress MAC,
   bundle MAC, multicast}` else `MAC_MISMATCH`; EtherType else
   `UNSUPPORTED_ETHERTYPE`; tagged → `VLAN_UNSUPPORTED`.
2. `STEER` (packets entering the forwarding path and inner packets after
   decapsulation; never after a shift or End re-lookup): precedence is
   the explicit demand override (consumed at the demand's initial
   ingress, never re-applied), then the matching ingress steering rule
   (ordered by longest dst prefix, exact DSCP before wildcard, exact sport
   before wildcard, then stable rule id), then ordinary FIB. A
   decapsulating node may apply its own table once for that ingress
   context. A match yields `ENCAP`. ENCAP → DECAP → ENCAP cycles are
   caught by a per-packet transition budget over (device, action state),
   independent of the nested-header check.
3. `LOOKUP`: LPM; RECEIVE → `DELIVER`; DROP_* → `DROP`; `SRV6_LOCAL` →
   `LOCAL_SID` (the behaviour performs its own hop-limit checks and
   decrements; no generic `TTL` afterwards); miss → `NO_ROUTE`; a
   `PolicyRef` or encap entry executes wherever that FIB entry is used,
   on any device.
4. `TTL`: for TRANSIT packets only, ≤ 1 → `TTL_EXPIRED` else −1;
   ORIGINATED packets are not decremented; `ENCAP` performs the RFC 8986
   §5.1 S05 inner decrement exactly once for transit packets and
   initializes the outer hop limit from `srv6_hop_limit` without a headend
   transit decrement.
5. `ENCAP(list)`: choose the list (weighted hash on the inner flow key),
   build the outer header (flow label from the inner key, DSCP copied),
   then dispatch the first outer entry through the **same local-action
   dispatch as transit**. `LOCAL_SID` returns an explicit continuation:
   `RELOOKUP` (End / uN: look the new DA up on this device),
   `CROSS_CONNECT(adjacency)` (End.X / uA: after shift and decrement,
   proceed through the bound adjacency to egress validation, member
   selection, MTU and transmission, with **no further local DA lookup**),
   `DECAP_LOOKUP`, `DELIVER` or `DROP`; `ENCAP` follows that continuation.
   A compiled adjacency keeps this whole header and TTL transformation
   and must be trace-equivalent to the interpreted run.
6. `SELECT_GROUP`: hash on the outermost header as it exists now (L4
   fields only for a transport next header); egress `l3_usable(af)` else
   `EGRESS_DOWN`; missing neighbor → `ADJ_UNRESOLVED`. With the device
   setting `fast_failover` (data-plane pruning, as ASIC fast failover does)
   legs whose port has no raw carrier or is unusable are skipped before the
   hash and the flow re-hashes over the live legs; off, the flow drops until
   the control plane reprograms the group (`fib_delay`). FLUID placement
   applies the same rule. `SELECT_MEMBER` for
   bundles by the LAG hash. Cross-connects skip `SELECT_GROUP` but not the
   rest.
7. `MTU`: transmitted length from the actual header stack (outer 40, SRH
   8 + 16·entries only when present, inner) against the egress interface
   or bundle MTU; IPv6 never fragments; IPv4 the same in v1.
8. `TRANSMIT(edge)`: physical transfer availability (above) else
   `LINK_DOWN` / `RX_DOWN`; re-encapsulate (`src` = egress MAC, `dst` =
   neighbor MAC) and hand to the peer.

SRv6 behaviours (RFC 8986 pseudocode with the RFC 9800 §4.1.1 insertion),
each validating the SRH shape and bounds first (negative or oversized
`segments_left`, `last_entry` inconsistent with the entry count, reduced
SRH with SL = LE + 1 allowed per RFC 8754 §4.3.1) and returning modeled
drops (`SRH_MALFORMED`):

- NEXT_CSID pre-step (uN, uA; uB6 post-Gate-C), before the SL == 0 test whether or not
  an SRH is present: `arg` = DA bits after `lbl + lnfl` of the matched SID;
  `arg != 0` → hop limit ≤ 1 → `TTL_EXPIRED`; shift; hop limit −1; SL
  unchanged; uN re-looks up on the same device, uA cross-connects, uB6
  continues to its encapsulation; `arg == 0` → classic processing.
- END: SL == 0 or no SRH → USP pops the SRH if flavored, then upper layer:
  USD → decapsulate and re-lookup the inner packet, else
  `UPPER_LAYER_NOT_ALLOWED`; otherwise hop limit check, −1, SL −1, DA =
  entries[SL], PSP pops the SRH when SL reaches 0.
- END_X: as END, then cross-connect (USD: decapsulate and cross-connect).
- END_DT46 (Gate B): SL != 0 → `SRH_SL_NONZERO`; decapsulate any inner
  family and re-look up in the default table. END_DT4 / DT6 and
  END_DX4 / DX6 (post-Gate-C): the same shape with family checks (DT4
  rejects an IPv6 payload) and DX cross-connecting; configuring them in
  Gate B is rejected at validation.
- END_B6_ENCAPS / uB6 (post-Gate-C): pre-step if uB6, else SL == 0 or no
  SRH → `UPPER_LAYER_NOT_ALLOWED`, hop limit check, −1, SL −1, DA =
  entries[SL]; then encapsulate with a valid list of the bound policy and
  look up the new outer DA. In Gate B a packet whose active SID is a B6
  behaviour drops with `SRV6_UNSUPPORTED` and configuring a B6 SID is
  rejected. Nested encapsulation of an already encapsulated packet is
  rejected (`NESTED_ENCAP_UNSUPPORTED`); one hop-limit budget per header.
- Header chain: an outer `IPv6Packet` carries `next_header` (43 for a
  routing header, else the transport or inner-IP protocol number) and the
  `SRH` record carries `next_header` for what follows it; the typed payload
  must agree with those values or the packet is `SRH_MALFORMED`. Hash
  fields come from the outermost IP header plus the transport header that
  the chain reaches (through the SRH); an encapsulated inner packet
  contributes only through the flow label the headend derived from it.
- Hop limit is decremented once per SID *behaviour that decrements* (End,
  End.X, pre-step); decapsulation paths do not decrement.

Drop reasons: IFACE_DOWN, MAC_MISMATCH, UNSUPPORTED_ETHERTYPE,
VLAN_UNSUPPORTED, NO_ROUTE, DROP_BLACKHOLE, DROP_UNREACHABLE,
DROP_PROHIBIT, TTL_EXPIRED, EGRESS_DOWN, ADJ_UNRESOLVED, MTU_EXCEEDED,
LINK_DOWN, RX_DOWN, SID_UNKNOWN, SRH_MALFORMED, SRH_SL_NONZERO,
UPPER_LAYER_NOT_ALLOWED, NESTED_ENCAP_UNSUPPORTED, POLICY_DOWN, LOOP,
CONGESTION.

`Network.trace(device, packet, max_hops=64)` is synchronous;
`Simulation.send()` yields `link.delay` per hop.

## SRv6 (`model/srv6.py`)

Standards: RFC 8402, 8754, 8986, 9256, 9602, 9800.

### SID structure, locators, allocation

`SidStructure(lbl, lnl, fl, al)`; C-SID = the `lnl + fl` bits after the
block; a container = block, then C-SID bits back to back, then zeros
(C-SID 0 = End-of-Container).

| Format | SID | Structure | Installed prefix length |
|---|---|---|---|
| UNCOMPRESSED | LOC:FUNCT:ARG | e.g. (48, 16, 16, 48) | lbl + lnl + fl (convention) |
| F3216 bare | uN = block ‖ node id (GIB) | (32, 16, 0, 80) | /48 |
| F3216 bare | uA, uB6 = block ‖ function (LIB) | (32, 0, 16, 80); WLIB (32, 0, 32, 64) | /48; /64 |
| F3216 bare | uDT4/6/46, uDX4/6 (terminal) | (32, 0, 16, 0) | /48 |
| F3216 composite | block ‖ node ‖ function (FRR / SONiC form) | (32, 16, 16, 64) | /64 |

Bare and composite forms are **distinct SIDs with distinct forwarding**
(a composite SID reaches its node through the routed /48 and then executes
locally; a bare local C-SID executes wherever the packet is); both are
supported natively and preserved literally by adapters. Default ranges
(Cisco/FRR): GIB 0x0001–0xDFFF, LIB 0xE000–0xFFF6, WLIB 0xFFF7–0xFFFF.
Default block `5f00::/32` inside RFC 9602's `5f00::/16`. The default GIB
holds 57,343 node identifiers per block before reservations; that is a
property of the configured block, not a network-size limit: larger
networks model several blocks (a multi-block allocation, exhaustion and
collision test is part of Gate B), and not every simulated device needs
a global SID.

Allocation is a **persistent allocator in the root** with reserved,
disjoint sub-ranges per purpose (automatic adjacency SIDs, terminal SIDs,
BSIDs, client requests) and non-zero node ids; allocation fails
atomically on collision or exhaustion; allocated ids persist across oper
changes and until explicit deletion of the interface or device (a
re-created interface gets a new id); `uA function = adjacency sub-range
base + interface index` while it fits, else the allocator. A `srv6-local`
RIB row is installed for a SID only while it is usable (uA: interface
oper UP); the SID stays in the SR-DB with `adjacency_up=False`. With
`drop_unknown_local=True` (default for F3216) the LIB and WLIB ranges are
covered by `srv6-local` UNREACHABLE rows computed as an **exact prefix
cover of the configured ranges** (`B:E000::/35` for the defaults), so an
unknown local C-SID drops as `SID_UNKNOWN` without shadowing summaries.

Validation per block: gib, lib and wlib pairwise disjoint; node ids
unique and in gib; local functions in lib ∪ wlib; no device's srv6-local
prefix equals or covers another device's uN prefix; classic locators
disjoint; a locator block never covers a configured interface or loopback
address; exhaustion and rollback are tested.

### Compression and encapsulation (RFC 9800 §6.2, RFC 8986 §5)

RFC 9800 §6.2 presents S01–S16 "for illustrative purposes" and allows any
encoding of equal or shorter length; NetSim adopts S01–S16 as its
**deterministic encoding contract** and verifies it with independently
hand-checked vectors (there is no official golden suite). `compress(list,
sr_db)` implements §6.2 S01–S16: validate each flavored
SID's structure (invalid or unknown structure is not compressible);
initialize a container from its first compressible SID with remaining
capacity = that SID's `al` (80 bits for F3216); append further
compressible SIDs (NEXT_CSID flavor, Argument 0, same Locator-Block) while
`lnfl` fits; then admit at most one following SID with a known structure,
the same block and `lnl + fl + al ≤ remaining` (a terminal uDT46 with
`al = 0` fits), copying its Locator-Node, Function and Argument bits and
consuming it; push and continue. Tests cover mixed widths and blocks,
non-zero arguments, full containers and the terminal fit boundary.

`SRH(entries, segments_left, last_entry, flags, tag)` in RFC 8754 order;
Segments Left counts entries. Encapsulation: outer `IPv6Packet` (`src` =
SRv6 source or loopback, `dst` = first entry, hop limit `srv6_hop_limit`,
DSCP copied, flow label from the inner key); `H_ENCAPS`: SRH with all n
entries reversed, SL = LE = n − 1; `H_ENCAPS_RED` (default): entries 2..n
reversed, LE = n − 2, SL = n − 1. RFC 8986 §5.2 says the SRH *may* be
omitted when the policy has one segment and no flag, tag or TLV is
needed; NetSim's policy: omitted exactly then (n = 1, flags = 0, tag = 0,
no TLVs), else pushed. Reduced SRH validation accepts SL = LE + 1 (RFC
8754 §4.3.1.1). Transit inner TTL: H.Encaps decrements the inner hop
limit or TTL once for transit packets (RFC 8986 §5.1 S05, RFC 2473) and
never for packets originated on the headend.

### SR Policies (RFC 9256), ownership, validation, steering

```
Segment = literal SID | AdjSeg(device, interface) | NodeSeg(device) | TermSeg(device, behavior)
SegmentList(segments, weight=1, name=None)
CandidatePath(preference=100, segment_lists, name, protocol_origin, originator, discriminator=0)
SrPolicy(owner: ClientId, color, endpoint, name, bsid, candidate_paths, fallback=IGP | DROP)
PolicyState(active_path | None, valid_lists: tuple[(list, wire entries)], status, reasons)
```

In v1 a policy (color, endpoint) has **one owner** and one BSID;
conflicting writes are rejected; candidate keys (origin, originator,
discriminator) map to exactly one registered client. Active path: highest
preference among valid paths; ties by higher protocol origin, then
(`prefer_installed`, default **false** for history-independent
convergence) already active, then lower originator, then higher
discriminator. W-ECMP across lists by weight.

Validation has three separate layers: (1) **basic validity** (RFC 9256
§5.1, which declares a segment list invalid when it is empty, its weight
is 0, it mixes SR-MPLS and SRv6, the headend cannot resolve the *first*
SID to outgoing interfaces and next hops, any *non-first symbolic* SID
(types C–K; in NetSim `AdjSeg`, `NodeSeg`, `TermSeg`) cannot be resolved
to a SID, or explicitly requested verification fails): non-empty, weight
> 0, no SR-MPLS mix, every symbolic segment resolves to an owner; literal
IPv6 SIDs beyond the first are not checked by this layer, and unknown or
invalid compression metadata keeps a literal SID literal and uncompressed
without invalidating it (ownership, behaviour or strict-profile checks
may still reject it); (2) **headend first-entry resolution** by compiling
the action program with the local-action dispatch, including the
headend's own local SIDs; (3) the **strict simulator profile**
(`validate_all_sids`, default on; deliberately stronger than the RFC's
rule, which checks only the first SID's path and the symbolic SIDs'
resolution): terminal behaviour last (`TERMINAL_NOT_LAST`), last SID
decapsulates or carries USD (`ENDPOINT_NO_DECAP`), **terminal SID owner
equals the policy endpoint** (`ENDPOINT_MISMATCH`), and an **end-to-end
walk**: `RIB_RESOLVABLE` means local recursive egress feasibility only;
end-to-end validation follows the selected underlay egresses **hop by
hop** through each visited device's RIB-derived forwarding until the SID
owner is reached (a preferred blackhole on a transit device is not
reachability), with loop detection, an explicit partial-ECMP rule (a list
is valid only if every ECMP branch reaches the owner; partial reachability
is reported), and all queries and failures recorded as dependencies. A
global or composite SID first reaches its owner before its behaviour
updates the current node; a bare local C-SID is resolved in the current
node's scope and must be owned there with its adjacency UP; uA/End.X move
to the adjacency peer (a bundle's peer bundle); uB6 (post-Gate-C)
requires the referenced policy to have a valid list by the same walk and
moves to its endpoint. With `srdb_source=("agent", name)` layer 3 validates only that
agent's published `srdb_view` claims and never upgrades local
resolvability to an oracle proof. **Policy status exposes five things
separately:** basic validity (layer 1), strict-profile validity (layer
3), the selected candidate path, the programmed forwarding version
(PENDING while `fib_delay` has not elapsed: the old program still
forwards, and a path that became invalid meanwhile keeps forwarding
through it), and observed delivery from placement or probes. Actual
delivery is always determined by installed forwarding and physical state;
a drop during the programming interval stays visible in the timeline.

Steering forms: BSID (a next-hop resolving to the BSID), per-destination
(`Nexthop(policy=PolicyRef)`; executed wherever that FIB entry is used),
per-flow through the ingress `SteeringTable`, and `Demand.steer`.
Precedence and matching as in the action program. `fallback=DROP`
installs an explicit discard when the policy is DOWN; `fallback=IGP`
performs the lookup **excluding the triggering policy or steering
action**, so it cannot re-select the same policy-bearing route. After
decapsulation the inner packet is steered once; repeated encapsulation is
guarded (`NESTED_ENCAP_UNSUPPORTED`).

## Hashing (`model/hashing.py`)

`LoadBalancer(id: ECMP | AGGREGATE_PORT, ipv4_fields, ipv6_fields,
transport_fields, seed, mode: HASH_THRESHOLD | RESILIENT, buckets=256)`
with LAG presets. `flow_hash` is keyed BLAKE2b from a per-Network
prototype over the selected fields of the **outermost header as it exists
at that selection**; H.Encaps sets `outer.flow_label = flow_hash(inner
key, domain seed) & 0xFFFFF` (RFC 6437/6438).

- `HASH_THRESHOLD` (RFC 2992): region selection over the 64-bit hash with
  documented integer rounding of region boundaries; FLUID uses the ideal
  rational shares, so the two differ by the rounding only.
- `RESILIENT` (deferred to Gate C+): bucket table on the FibEntry; on
  removal only vanished buckets are reassigned; on **addition or weight
  change** the minimum number of buckets moves from over-represented
  adjacencies to satisfy the documented rounded target shares (a newly
  added adjacency therefore receives buckets); deletion-only stability and
  addition/reweight behaviour have separate tests; FLUID uses actual
  bucket counts; rounding error is bounded only after rebalancing.
- FLUID approximates HASH only under explicitly independent selection
  domains (per-device seeds, distinct ECMP and LAG personalization) and
  representative flow-key sampling; correlated revisits and polarization
  studies use HASH. Rational routing fractions are exact; report doubles
  carry a stated tolerance.

## Flow placement (`model/flows.py`)

```
Demand(id, source, dst, rate, *, template=None, payload_size=1000, mode=FLUID, dscp=0, klass=None, steer=None,
       flows=1, priority=0, tag=None)                     frozen; rate = IP-payload bit/s; time in seconds
PacketTemplate(af, src, dst, protocol, sport, dport, dscp, flow_label, payload_size, ttl, hop_limit)
    deterministic defaults from the source device (loopback address, protocol 17, ports from a seeded generator);
    a microflow generator maps index i into specified header fields (ports, flow label) before hashing, so the
    auxiliary index is never an implicit wire field; every template field that affects steering, size or forwarding
    is part of the FLUID equivalence class
DemandSet.matrix(sources, dsts, rate, mode=PAIRWISE | COMBINE, tag=...); DemandSet.pair(fwd, rev) for bidirectional
    demands (an explicit reverse demand with its own source, dst and rate; nothing is inferred)
TrafficClass(name, dscp, priority); CapacityModel: UNCONSTRAINED | LOSSY
PlacementReport(time, version, per directed edge: offered_wire, carried_wire, congestion_dropped, capacity;
                per demand: payload_delivered, drops by (reason, device or edge); classes and caches; detail)
  views: utilization(edge), interface_tx/rx, bundle_utilization, member_utilization, oversubscribed(),
         bottlenecks(k), by_risk_group(), by_tag() (available in FULL detail; SUMMARY keeps per-class aggregates
         and per-demand totals and states which queries are unavailable)
```

**Rate and wire accounting.** `rate` is IP-payload bit/s and
`payload_size` is bytes after the inner IP header (the template states
any included transport header); packet rate `q = rate / (8 ×
payload_size)`. Frame bytes on an edge = payload + inner IP header +
outer headers and SRH when present + 14 Ethernet bytes; FCS, preamble
and inter-frame gap are excluded explicitly. Attempted wire load on edge
e = `q × 8 × frame_bytes(e)`, charged as `offered` even if the physical
transfer fails; a physical failure carries zero. IP MTU compares IP
bytes only (excluding Ethernet) against the egress MTU in FLUID
(deterministic `MTU_EXCEEDED`). Reports distinguish payload delivery from
wire load, and tests use these exact units.

**Forwarding-equivalence classes.** FLUID demands are grouped only into
classes for which forwarding is provably identical: (destination, dscp,
steering outcome at ingress, packet template, and the packet-state
continuation for SR chains). Each class walk is a destination-driven
**leg chain** over nodes keyed by (device, action state, header or
segment continuation), so encapsulation, local SID execution and
decapsulation are explicit transitions, not device-only nodes. HASH
demands never use classes: each microflow (`flows = N`, keys
`(flow_key, i)`, `rate / N`) is an explicit packet template executed by
the action program.

**Leg walk.** Discover the class graph from the seed devices (LOOKUP →
group → members → `TRANSMIT` edges, with physical availability checked
per edge), compute strongly connected components over forwarding states and apply
the **loop-cut model**: a transition that stays inside a cyclic SCC
(including a self-loop) is charged as offered on that edge and recorded
as `LOOP` loss, exit transitions of the component are propagated, and
inflow is pushed through the condensation DAG in topological order, so
healthy inflow to nodes downstream of a looping branch is preserved
(the diamond fixture with the cycle {R1, R2} and the exit R1→R3→R4
delivers 50 of 100 and loses 50 as `LOOP`). This is a conservative
approximation, not a TTL simulation: real packets re-circulate and a
fraction exits per pass; that geometric model (`loop_model=AMPLIFY`, with
the per-header hop-limit bound) stays deferred and changing the default
requires its own approval. HASH and probes execute finite per-header hop
limits and drop `TTL_EXPIRED`. Splits use the FLUID
rule, then equal shares across active bundle members; drops for
NO_ROUTE, DROP_*, EGRESS_DOWN, POLICY_DOWN, LINK_DOWN, RX_DOWN,
MTU_EXCEEDED are recorded at the node or edge where they occur; TTL is
not modelled in FLUID (HASH and probes carry one budget per header). A
directed edge traversed by k legs carries the rate k times;
conservation holds per leg and per demand (delivered + drops = rate).

**Gate B forwarding identity and accounting contract.** Gate A keys the
walk's decisions by device and applies one wire factor per class, which
is exact for plain IP. Gate B keys vertices by (device, forwarding-
relevant packet and action state: header stack, active SID continuation)
so that R1→R2→R1 with a different continuation, or encapsulation followed
by decapsulation, are distinct vertices; every transmission carries its
own frame length and the packet rate, repeated visits of one physical
edge add up, MTU applies to that edge's IP stack and LOSSY clipping to its
wire load, and when several legs of one class consume the same residual
the order is the class's deterministic leg order. Reference numbers for
100 Mbit/s of 1000-byte IPv4 payload (no FCS, preamble or IFG): plain
framing 103.4 Mbit/s; outer IPv6 without SRH 107.4; outer IPv6 with a
one-entry SRH 109.8; after decapsulation 103.4 again. Probes, HASH and
FLUID share one action interpreter: FLUID expands alternatives, HASH
selects one, and the headend executes its own local SID before
transmitting.

**Caches.** A class's result (sparse per-edge fractions and per-source
contributions, kept only in FULL detail) is stored in the frozen
`PlacementReport` with its **dependency record**: every consulted FIB
entry and failed lookup, group, interface, link (state and capacity),
SID and policy action, steering rule and load balancer. A class is
recomputed when any dependency's content changed; capacity-only changes
reuse UNCONSTRAINED fractions but recompute utilization and all LOSSY
allocation; only pure rate changes under UNCONSTRAINED rescale; changing
source, flows, mode, template or steering is a new class. Aggregate
inflow per class is O(V + E); per-source attribution is budgeted
separately and off by default.

**Capacity models.** The walk propagates **packet rate** `q` (equivalently
original payload rate), never carried wire bit/s, so overhead is
recomputed per edge across ENCAP and DECAP. `UNCONSTRAINED`: no capacity
clipping (physical and MTU drops still apply), utilization may exceed 1.
`LOSSY`: demands in (−priority, id) order, lists by (weight desc, name),
legs in chain order, allocated per demand and directed edge in a stable
traversal: incoming `q` is split by the routing fractions; on edge e
`q_out = min(q, residual_wire(e) / (8 × frame_bytes(e)))`, the residual
is decremented by `q_out × 8 × frame_bytes(e)`, only `q_out` reaches
successors, the lost original payload rate is recorded as a congestion
drop on e, node and action drops are recorded separately, and original
payload demand is conserved. Strict-sequential by construction.
NetGraph-Core `EQUAL_BALANCED_LOSSY` parity holds only for plain-IP
single-leg demands without LAGs (or `expand_lags=True`) and at unit
frame overhead.

## Determinism and free-threading

Sorted iteration everywhere; never `hash()` or `id()` order; allocators in
the tree; `Device.seed` from the name; hot-path values are small ints; no
`ipaddress` in hot paths; no `lru_cache`; caches only inside a run or in
the tree. **Ownership boundary**: each `Network`/`Simulation` and its
mutable caches (handle cache, heaps, dirty sets, inboxes, observation
queue) has one owning thread; independent simulations run concurrently;
immutable snapshots may be transferred after safe publication;
cross-thread writes are queued to the owner; concurrent updates to one
Network are not supported. Verified on 3.14t by deterministic independent
runs and throughput measured against the same workload on one quiet
machine.

## Standards basis

| Area | Standard | Kept | Simplified |
|------|----------|------|------------|
| Datastores | RFC 8342 | config vs oper, one writer per key | |
| Interfaces | RFC 2863, 8343, 8344 | oper values, admin/oper, speed, mtu, addresses | statistics are rates |
| Ethernet, aggregation | IEEE 802.3, RFC 7042, IEEE 802.1AX, OpenConfig `min-links` / `aggregate-id` | frame fields, members, partner check, min-links | no FCS, no LACP PDUs |
| IPv4 / IPv6 | RFC 791, 2474, 1812, 8200, 4291, 6437, 6438 | headers, LPM, TTL rules, flow label at encapsulation | no checksum, fragmentation, ICMP |
| Unnumbered | RFC 8950 | interface or scoped link-local next hops for IPv4 | no BGP |
| RIB / FIB | RFC 8349, 8430 | distance then metric, next-hop kinds, cross-AF recursion, weighted groups | one table per AF |
| ECMP | RFC 2991, 2992 | region selection, resilient variant later | keyed BLAKE2b |
| Segment routing | RFC 8402, 8754, 8986, 9256, 9602, 9800 | SRH with containers, H.Encaps / Red, behaviours and flavors, NEXT-C-SID with F3216 (bare and composite), GIB / LIB / WLIB, §6.2 compression, 5f00::/16, one-owner SR Policy, W-ECMP, BSID, steering | no HMAC / TLVs / OAM / PCEP; nested B6 and REPLACE-C-SID deferred |
| BGP semantics used by NHT | RFC 4271 §9.1.2.1 | prospective resolvability with exclusion context | no BGP |

## Protocol agents and integration (Gate C contract, revision 16)

Refined on 2026-09-20 after an adversarial review of the implemented Gates
A and B against this section (scratchpad `codex-review-14-gatec.md`, copy
of `/private/tmp/netsim-gate-c-review-20260920/review.md`). Reproduced on
the tree: a kind run rejected by an observer after publication was
re-executed by `retry()` (fixed: an observer's exception is re-raised marked as published, `published_failure()`, and the claimed work is consumed);
`Study.iterations` drained the whole heap, which a recurring timer never
empties (fixed: the observation window, then `Simulation.run_derivations()`
which finishes only DEFERRED-band work such as a delayed FIB stage and
leaves timers alone); a metric-only RIB change
leaves the FIB object identical (so NHT cannot be keyed on FIB identity);
`changed_paths()` reports coarse device sections (a naive prefix matcher
on `.../oper` misses an interface oper change); a failed physical link
keeps both interfaces oper UP during carrier delay (a channel keyed on
oper state would pass traffic through a dead wire); the engine's heap
orders by delivery time, so a datagram sent later with a shorter delay
overtakes an earlier one; an unrelated loopback addition re-validates
every policy headend (conservative SR invalidation is a commit-path cost);
`srdb_source=("agent", name)` is ignored by policy validation, which
always reads the oracle.

### Principles

1. **One door** for routes, policies and SIDs through clients; agents and
   sources register a `ClientId` and profile.
2. **Locality.** `AgentContext` is a projection, never a `Device` handle,
   the model `_View` or a `NetworkState`. It exposes the device's
   configured values and *effective observations* (oper state after
   debounce, neighbors, its own RIB view with status, its installed
   forwarding, session states, delivered messages with their scoped sender
   identity, timers, NHT and SID results); it excludes raw carrier, remote
   endpoints, root access and any oracle-derived inventory as a discovery
   mechanism. The only global role is the `RouteSource` (pure function of
   the tree, run by `converge()` too). `srdb_source=("agent", name)`
   validates SR policies against that agent's *advertised* immutable
   `srdb_view`; claims it has not advertised are unknown; only the
   explicit oracle mode reads remote model state, and an unsupported mode
   is rejected rather than silently falling back to the oracle. Remote
   failures cost real delivery immediately where physical forwarding
   requires it, while an agent's knowledge changes only through local
   observations, messages and timeouts. Stateful `Controller`s stay
   deferred past Gate C.
3. **Agent state in the tree**, opaque and identity-compared, with
   validated immutable representations (incremental trusted builders,
   debug whole-tree checks); inboxes, outboxes and timers are runtime
   state owned by the `Simulation`. Callback objects carry immutable
   configuration and no hidden evolving state; a frozen envelope may not
   contain a mutable message or RNG.
4. **Subscriptions** are device-scoped, typed paths kept in an index: an
   ancestor replacement or removal invalidates descendant subscriptions,
   a descendant change invalidates ancestor subscriptions, and a coarse
   delta section is filtered at field level before it wakes anyone.
   Registration supplies an initial snapshot; causes are deduplicated;
   only affected agents are scheduled; wakeups use commit-time internal
   dispatch, not delayed public `SETTLED` observers. A one-device change in
   a 100k-agent idle fixture examines only the matched branches.
5. **Protocols are plugins**; the contract lives in `model/contracts.py`.

### Client APIs

`RibClient` (above); `PolicyClient` (one owner per policy; candidate keys →
one client; steering entries keyed by client); `SidClient`
(`request_sid(request_id, behavior, args)`, results in `ctx.sid_results`).

`NhtClient` is a local routing query service with three separate answers:
`resolve(candidate, exclude_rows, options)` is a pure RIB query returning
eligibility, the selected resolution prefix and source, the IGP cost to the
queried next hop (or unavailable) with its provenance (never a sum of
unrelated protocol metrics through recursion), resolved legs, the queries
made (including failed lookups) and the input epoch; installed forwarding
is exposed separately with the processed epoch, FIB version and PENDING
status; registrations are keyed by (owner, AF, address, interface
generation and scope, `connected_only`, `resolve_via_default`) and notify
on every semantic change of the answer, including cost-only changes (a
metric change does not change the FIB object) and formerly unsuccessful
queries that become resolvable. Registration never makes unrelated route
programming pending. Prospective questions (RFC 4271 §9.1.2) are asked
with an exclusion context that also excludes the candidate's own row. Exit
matrix: IPv4 and IPv6; identical link-local addresses on different
interfaces; connected-only and default controls; self-covering candidate
and mutual recursion; same-prefix alternative rows; failed lookup followed
by a more-specific insertion; cost-only change; delayed FIB; withdrawal
and recovery. Router id is derived by L3.

### Agent contract

```
class DeviceAgent(Protocol):
    client: ClientId; profile: ClientProfile; config: AgentConfig (immutable: peers, AS, timers, run_delay finite and
                     non-negative, default 1e-3, zero permitted and guarded by max_rounds_per_timestamp;
                     processing_delay; retransmit_timeout; listen ports; inbox and queue limits)
    def subscriptions(self) -> tuple[Path, ...]           # local paths only
    def on_init(self, ctx) -> AgentOutput                 # first AGENT run after registration or reset
    def on_run(self, ctx) -> AgentOutput

AgentContext (read-only projection): now; device name; device config; agent_config; router_id; interfaces (index,
    name, kind, config, effective oper, l3_usable per AF, link-local, MAC, bundle members); own link attributes
    (index, delay, capacity as configured locally); neighbors (scoped); rib_view (rows by source with status);
    lookup(af, address, scope), installed forwarding version and status; route_notifications; nht results;
    sid_results; srdb_local; policy states; agent_state; inbox (the captured prefix); connection states of own
    sessions; causes; rng (private generator seeded from committed state); stats (buffered counters)
AgentOutput (frozen): agent_state; operation records (route_ops, policy_ops, sid_requests, nht ops) produced by the
    context's clients and published only by the runtime; messages (channel, port, immutable payload; route
    advertisements batched as one immutable payload, never one event per prefix); sessions (open / close / abort);
    timers (arm(name, delay > 0) / cancel); srdb_view | None
```

**Publication.** Every captured run has a receipt `(device generation,
agent generation, run id)`. All runs of a round prepare against one
immutable input snapshot; their accepted operation records are applied in
canonical owner order onto one staging root with transaction-local
allocator reservations and a per-output journal, so a conflicting or
invalid output is undone alone (two accepted SID requests can never reserve
the same value; a failed peer output never discards a successful one). The
round publishes once (one AGENT delta with the successful receipts inside).
A published receipt consumes its captured inbox prefix and publishes its
outbox (messages, session operations, timers) exactly once, even if an
observer raises afterwards (marked as published); a rejected receipt keeps its
captured inbox prefix, pre-run agent state and RNG, and `retry()` re-runs
only rejected receipts against a local view rebuilt from the corrected
committed root at the current time, with later arrivals kept for the next
run. A messages-only output is a success even when its model edit is a
no-op. Same-timestamp feedback produces successor rounds; positive delays
must advance simulated time. Restart: `Simulation.reset_agent(device,
name, purge=False)` invalidates the old generation's receipt, cancels its
timers, sessions, pending runs and inbox and outbox entries, resets state
and runs `on_init`; retention is defined separately for routes, policies,
SIDs and NHT registrations (rows stay until the first `sync` unless
purged). Registration, unregistration and client ownership are atomic and
scoped by device and agent generation.

**Bounds.** Agent simulations expose a global time and event budget,
per-agent inbox limits and per-connection queued message and byte limits
with explicit overflow outcomes (rejection or connection failure, never
silent truncation), counts of live versus stale scheduled events, and
periodic compaction of lazy queues. Stats are counters and aggregates by
default with opt-in bounded samples. `run_delay` is a batching latency,
not a modeled CPU queue. Correctness never depends on retained history.

### Transport (`runtime/transport.py`)

- `LinkChannel(device, interface)` (datagram): a send attempt requires
  local effective eligibility (the interface l3-usable for the family, or
  bundle UP) **and** physical transfer and receive availability of the
  wire (a stale oper UP during carrier delay cannot pass traffic through a
  failed link); channel metadata never reveals raw failure to the agent.
  A channel is directed and carries an endpoint incarnation; delivery at
  `now + link.delay + processing_delay` must be a strictly future
  representable time; the same physical checks apply at delivery and a
  stale endpoint generation drops the datagram. Gate C guarantees FIFO
  for surviving datagrams within one incarnation by **ordered release**
  (a later datagram never overtakes an earlier one even when the delay
  changed), and never retransmits lost datagrams. A bundle channel
  samples its delay from the active members at send time; membership
  changes do not reorder in-flight datagrams.
- `Session` (a reliable-message abstraction, not TCP): endpoints are (AF,
  address, interface scope when link-local, port); a **connection** has a
  distinct id, initiating endpoint and port, endpoint generations and
  per-direction sequence numbers; states LISTEN, CONNECTING, ESTABLISHED,
  DOWN; active open against a listener, passive-only peers accepted,
  refused → `SessionEvent(DOWN, REFUSED)`. Simultaneous opens yield two
  distinct connections that the protocol may keep or collapse (RFC 4271
  §6.8 decides by BGP identifier after OPEN); coalescing by endpoint order
  is an opt-in policy of the reference protocol, never the only behaviour.
  Close has two forms: abort (invalidate every pending, in-flight and
  queued entry of the incarnation) and drain-then-close (a final message
  may be sent first). Directly connected scoped link-local streams need
  no routes (cold start). **Path reachability is separate from connection
  state**: derived by the TRANSPORT kind with the forward step (a stable
  per-connection probe key, both directions, dependencies including
  negative queries recorded); a transient outage stalls delivery in one
  ordered queue per direction and releases in sequence when the path
  returns. The no-progress timeout starts at the first undelivered entry
  and resets on delivery; it is distinct from protocol hold timers and
  from the optional BFD-like immediate notification; expiry closes with
  `SessionEvent(DOWN, TIMEOUT)`. Each direction has a bounded message and
  byte admission with an explicit rejection or connection-failure result;
  accepted data is never dropped silently. Control traffic is not charged
  to demand utilization unless explicitly modeled.
- All delays strictly positive and validated; deliveries and timer
  firings are NORMAL events at later times; the inbox is a runtime deque
  whose captured prefix is consumed by publication.

### Reference protocol (`agents/reference.py`)

A documented single-area link-state teaching protocol, not Open/R
compatibility: neighbor discovery over scoped link channels without
oracle peer identities, bidirectional adjacency with hold timers, immutable
versioned adjacency and prefix records synchronized over sessions, flood
deduplication, expiry or withdrawal of stale origins across partition and
restart, ECMP SPF only when the semantic LSDB changes, client-owned route
deltas, and a small SID and locator advertisement so learned SR validation
has a fixture. It is accepted **with the oracle disabled**: normalized
prefixes, metrics, next-hop sets and final forwarding equal a separate
oracle network, ignoring ownership and row identity; an observed local
interface DOWN reacts immediately while a muted hello channel with oper
still UP withdraws after the hold time; cold start, partition and heal,
origin restart, duplicate and out-of-order advertisements, stale
withdrawal and metric-only change are separate tests; a heartbeat-only
interval triggers no SPF, FIB or placement work; an agent that reads
`oracle_igp` fails the locality test even when its routes match.

### Studies with agents

`settle()` means same-timestamp quiescence only and `run_derivations()`
finishes pending derivation-band work without touching timers. Agent
studies use an
explicit warm-up and observation horizon, a maximum event budget and a
named stability predicate over selected routing, programming and delivery
outputs (liveness refreshes do not reset it unless they change those
outputs), and report `converged`, `deadline_exceeded` or
`budget_exceeded`; convergence is never inferred from the last commit.
Each iteration constructs a fresh runtime from configuration and performs
deterministic warm-up; a model fork is not a warm protocol restart
(runtime checkpoint and restore stay deferred); warm-up cost is reported
as study cost. Oracle studies keep the fast fork path.

### Scale qualification

Separate oracle and protocol workload profiles (devices, links, areas,
advertised prefixes, per-device RIB and LSDB entries, peers and sessions,
demands and classes, message rate, duration, retention) accompany every
scale claim. A flat domain with one advertised prefix per device costs
about N(N − 1) remote rows (100 million at 10k devices) whatever the
implementation; a bounded routing scenario is a declared input, not a
consequence of a faster language. Gate C validates protocol semantics on
small topologies and scheduling and locality on large idle bounded-state
fixtures; the conservative SR consumer invalidation (every headend on any
RIB or interface change) is a named commit-path cost to be scoped by the
resolver's dependency records. Pure SPF, resolution and placement
functions remain the acceleration seams; native kernels are decided from
end-to-end profiles after the protocol workload exists.

### Gate C slices

| Slice | Deliverable | Exit evidence |
|---|---|---|
| C0 contracts and lifecycle | typed `AgentNode`, `AgentContext`, `AgentOutput`, operation records, run receipts, startup, reset and fork rules, the immutable payload boundary; this section reconciled with the code | publication versus observer failure unambiguous; a messages-only output works; cross-agent conflicts isolate only rejected outputs; runtime objects cannot leak through the context |
| C1 agent scheduler | the AGENT kind, indexed local subscriptions, captured inboxes, timers, RNG and stat buffering, partial success and retry | two-agent failure and retry matrix, successor rounds, same-time versus positive-delay limits, reset and deletion generations, no wakeups or scans of unrelated idle agents |
| C2 local query and NHT | candidate overlay and exclusion query, cost and resolution epochs, installed-state distinction, scoped registrations and dependencies | the NHT exit matrix above; metric-only changes notify although the FIB object is unchanged; misses become resolved on insertion |
| C3 transport | physical link datagrams, scoped route-free sessions, routed reliable-message sessions, bounded queues and connection lifecycle | cold-start link-local exchange; physical loss during carrier delay; FIFO under delay changes; one-way outage, refusal, timeout, close, old incarnation and backpressure |
| C4 reference protocol | discovery, finite semantic LSDB, flood, sync and restart, SPF and route diffs, learned SR view test | oracle-free cold start and failure and heal; normalized final equivalence on small random graphs; delayed FIB drops observable; unchanged hellos cause no SPF or FIB work |
| C5 studies and qualification | fresh-runtime warm-up, explicit observation and stability windows, streaming convergence and loss metrics, workload benchmarks | periodic timers never hang an iteration; failures beyond the deadline report non-convergence; repeatable outputs across interpreters and seeds; bounded queue and history memory; declared scale envelope |

Not in Gate C: full Open/R or BGP (only their contract probes: discovery
without prior routes, passive and simultaneous opens, BGP-style
prospective and cost-sensitive NHT), controllers, on-wire B6, resilient
hashing, VRFs, in-band control traffic accounting, runtime checkpoint and
restore, parallel execution of one `Simulation`.

### Open/R and BGP on the contract (deferred implementations)

Open/R: Spark hellos on link channels; KvStore over link-local scoped
sessions to discovered neighbors first, loopback sessions after routes
exist; LinkMonitor from interface subscriptions; Decision SPF with
interface + link-local next-hops; PrefixManager; Fib = `RibClient` with
`sync`. BGP: listener and active-open sessions, FSM driven by
`SessionEvent`s and timers, Adj-RIB-In/Loc-RIB/Adj-RIB-Out in sharded
state, best path, `NhtClient.resolvable` for §9.1.2.1, distances 20/200,
redistribution from `rib_view`, color communities to `PolicyRef`
steering. Both are Gate C+ work items with cold-start tests.

## Runtime API and the diamond

```
env = netsim.Environment(); net = netsim.model.Network(srv6_block="5f00::/32")
R = {n: net.add_device(n) for n in ("R1", "R2", "R3", "R4")}
for i, r in enumerate(R.values(), 1):
    r.add_loopback("lo0", ipv4=f"10.0.0.{i}/32", ipv6=f"2001:db8::{i}/128")
net.add_p2p(R["R1"], "eth3", R["R3"], "eth1", ipv4=("10.1.13.0/31", "10.1.13.1/31"), speed=100e6)
net.add_p2p(R["R2"], "eth3", R["R4"], "eth1", ipv4=("10.1.24.0/31", "10.1.24.1/31"), speed=100e6)
net.add_p2p(R["R3"], "eth2", R["R4"], "eth2", ipv4=("10.1.34.0/31", "10.1.34.1/31"), speed=100e6)
net.add_lag(R["R1"], "Po1", ["eth1", "eth2"], R["R2"], "Po1", ["eth1", "eth2"],
            ipv4=("10.1.12.0/31", "10.1.12.1/31"), min_links=2, speed=100e6)
R["R1"].add_route("10.0.0.2/32", nexthops=[("Po1", "10.1.12.1")]); R["R1"].add_route("10.0.0.3/32", nexthops=[("eth3", "10.1.13.1")])
R["R1"].add_route("10.0.0.4/32", nexthops=["10.0.0.2", "10.0.0.3"])          # one row, two recursive next-hops
R["R2"].add_route("10.0.0.4/32", nexthops=[("eth3", "10.1.24.1")]); R["R3"].add_route("10.0.0.4/32", nexthops=[("eth2", "10.1.34.1")])
net.add_demand(Demand("d1", source="R1", dst="10.0.0.4", rate=100e6))
sim = netsim.runtime.Simulation(env, net)
sim.at(10, lambda: net.links["R1:eth1--R2:eth1"].fail())
sim.run_until(20)
report = sim.timeline.snapshot_at(10).placement; report.utilization(net.links["R1:eth3--R3:eth1"].edge("R1"))
sim.timeline.summary(10); sim.timeline.utilization_series(net.links["R1:eth3--R3:eth1"].edge("R1"))
```

Addresses use /31 pairs (RFC 3021), so no broadcast address is used as a
next hop. `add_route` takes a list of next-hops for one row; distinct
rows need explicit distinguishers. Clock-free: `net.converge()`,
`net.place()`.

## Adapters

`sonic.py`: CONFIG_DB load/dump preserving **literal** SID values,
prefixes, structures and behaviours (bare and composite forms are
distinct; no naming conversion); round-trip guarantees restricted to a
versioned supported schema; APPL_DB export in wire form. `core.py`:
`build_graph` (`ext_edge_id = 2*index + direction`, masks), IGP
acceleration, FLUID vs `EQUAL_BALANCED` cross-check on random simple
graphs (plain IP, unit overhead), pinned-path cross-check.

### Running a NetGraph-built network (`adapters/ngraph.py`, Gate A)

A network built with NetGraph (Python API or scenario YAML with
blueprints) is a supported input for a full simulation, not only a
topology source. The adapter maps the whole scenario:

| NetGraph | NetSim |
|---|---|
| `Node(name, disabled, risk_groups, attrs)` | `Device` (name escaped if it contains `/`), `enabled = not disabled`, `lo0` with loopback addresses from `attrs["loopback_ipv4" / "loopback_ipv6"]` or deterministic pools in name order; a locator when `srv6=True` (Gate B) |
| `Link(source, target, capacity, cost, disabled, risk_groups, attrs, id)` | one `Link` between two auto-created Ethernets (`attrs["source_interface" / "target_interface"]` or `eth{n}` in link-id order); `capacity × capacity_unit` → speed (bit/s, default unit 1 Gbit/s); `cost` → interface metric both ends (`attrs["reverse_cost"]` for asymmetry); `disabled` → FAILED; risk groups kept on the link; parallel links tagged `attrs["lag"]` → one PortChannel per side with `attrs["min_links"]` |
| addressing | `unnumbered` (default): loopbacks only, interface next-hops, oracle routes; `p2p`: /31 and /127 pairs from pools |
| routes | `igp.py` (oracle) installs shortest-path ECMP routes with NetGraph costs as metrics, so `flow_policy: SHORTEST_PATHS_ECMP` maps to FLUID over the oracle; WCMP or TE flow policies are not mapped in Gate A (Gate B expresses pinned paths as SR Policies) |
| `demands` (`TrafficDemand`: source and target regexes, volume, mode combine or pairwise) | `DemandSet.matrix(sources, dsts, rate=volume × capacity_unit, mode, tag=demand set name)`; destinations are the matched devices' loopbacks |
| `failures` (`FailurePolicy`, seeded modes and rules) | a **failure schedule**: `FailureManager.compute_exclusions(policy, seed_offset)` yields excluded nodes and links per iteration; the adapter turns each iteration into operations at a chosen time (`device.enabled = False`, `link.fail()`), optionally restored after a dwell, so a Monte Carlo study becomes one long timed run or N independent runs with the scenario seed |
| `seed` | `Network` seed for MAC pools, hash seeds and the failure schedule |
| results | `to_network(net, placement)` writes per-link utilization and offered, carried and dropped wire load into link `attrs` and per-device drops into node `attrs`; `Timeline.utilization_series` gives utilization over time; a `results.json` export mirrors NetGraph's shape (per iteration: exclusions, delivered, oversubscribed links) so existing NetGraph tooling can read it |

`from_scenario(scenario, *, capacity_unit=1e9, addressing="unnumbered",
srv6=False)` returns `(Network, DemandSet, FailureSchedule)`;
`from_network(network, ...)` is the topology-only subset. The plain-IP
FLUID results of a NetGraph-built network must match NetGraph's own
`SHORTEST_PATHS_ECMP` placement per directed edge (the
`EQUAL_BALANCED` cross-check) whenever no demand is dropped, which is the
acceptance test for the import. Caveats stated to users: NetGraph
capacities are abstract units (choose `capacity_unit`); NetGraph costs
must be non-negative integers (they are, by Core's constraint); node
names containing `/` are escaped in paths; a NetGraph link is
bidirectional with the same capacity each way, which maps to one
full-duplex NetSim link.

## Acceptance scenario (drives the tests)

Diamond as in the example (100 Mbit/s links, /31 pairs, loopbacks,
locators in `5f00::/32`; oracle routes where statics are absent). The
Gate-A variant is IPv4-only and leaves IPv6 forwarding disabled on links;
the Gate-B fixture explicitly enables IPv6 forwarding on every Ethernet
and PortChannel L3 interface (scoped link-local neighbors derived) and
verifies locator reachability before creating policies.

| Step | Expected |
|---|---|
| Build; `converge()` and `Simulation` + `run_until()` (no device agents, `prefer_installed=False`) | trees equal modulo version/since; R1 10.0.0.4/32 INSTALLED with group `[(eth3, 10.1.13.1), (Po1, 10.1.12.1)]`; contributing row key recorded |
| FLUID 100 Mbit/s R1 → 10.0.0.4 | payload: R1→R3 50, each Po1 member 25, R2→R4 50, R3→R4 50; wire load adds 34 bytes per 1000-byte packet; delivered 100 |
| t=10: fail R1:eth1 link, `min_links=2` / `1` | Po1 LOWER_LAYER_DOWN both ends, connected /31 withdrawn, static via R2 NOT_INSTALLED, all 100 via R3 / Po1 UP, remaining member 50 |
| Physical failure during debounce: `carrier_delay_down=1` on **both** endpoints of R1:eth1–R2:eth1, `carrier_delay_up=0`, `min_links=2`, UNCONSTRAINED | during 10..11 routing is stale: Po1 still splits to eth1; on that edge offered payload 25 Mbit/s (offered wire 25.85 Mbit/s at 1000-byte payload), carried 0, payload drop 25 (`LINK_DOWN`), delivered 75; at 11 the transition applies, delivered returns to 100 and the remaining path offers 103.4 Mbit/s wire. Asymmetric partner failure (one endpoint delayed) is a separate test with its immediate bundle consequences |
| Rounds at t=10 (statics only, no agents) | one round: link; CARRIER {R1.eth1, R2.eth1}; LAG {R1.Po1, R2.Po1}; L3 {R1, R2}; FIB {R1, R2}; PLACEMENT; then SETTLED deliveries |
| `fib_delay=0.05` on R1 | at 10 R1 rows PENDING (epochs), placement still into a down Po1 with `EGRESS_DOWN`; at 10.05 INSTALLED and corrected |
| Carrier delay: `delay_down=1`, fail at 10, restore at 10.5 | no oper transition (two raw transitions logged) |
| Carrier delay: `delay_up=2`, `delay_down=0.1`; raw UP at 10, DOWN at 10.5, UP at 10.6 | UP at 12.6; a `carrier_delay_up` reconfiguration to 1 at 11 reschedules to `max(11, 10.6 + 1)` |
| Asymmetric delays: R1.eth1 `delay_down=0.2`, R2.eth1 0 | R2.Po1 shrinks at 10; at 10.2 R1.Po1 `min_links_ok` false and R2.Po1 active shrinks again (component two-pass) |
| Reactive process waiting on eth1 DOWN | its delivery is a separate SETTLED event with the settled root; its failing of a second link opens another round |
| Failed derivation | an exception propagates from `run_until`; after fixing, `settle()` retries the retained work once |
| IPv6 and unnumbered variants | identical payload loads |
| HASH probe IPv4 5-tuple | one path, ttl 64 at R1 (originated), 63 at transit, delivered; TTL=1 drops `TTL_EXPIRED` at the second device |
| Mutual statics R1/R2 for 10.0.0.9/32 plus a healthy branch S→B→D | FLUID: the cyclic SCC absorbs its inflow as `LOOP`, the healthy branch delivers; HASH: `TTL_EXPIRED` |
| `resolve_via_default=True`; blackhole; mixed special+forwarding group | resolvable via default; `DROP_BLACKHOLE`; special wins (documented) |
| Gate B: SR Policy (color 10, endpoint R4), paths pref 200 strict R1→R2→R4 and pref 100 strict R1→R3→R4, demand steered by class | all 100 on Po1 (50 per member) and R2→R4; wire load on the encapsulated hops 107.4 Mbit/s without SRH and 109.8 with a one-entry SRH (1000-byte payload), 103.4 after decapsulation |
| Fail Po1 (`min_links=2`) | R1.uA→R2 adjacency DOWN in the SR-DB → list invalid → path 100 active |
| `fallback=DROP`, only path 200 | explicit discard installed, `POLICY_DOWN`; equals NetGraph-Core pinned-path result |
| W-ECMP lists via R2 (3) and via R3 (1) | 75 / 25; HASH microflows ≈ 3:1 |
| UNCOMPRESSED probe, list `[R2.End.X→R4, R4.End.DT46]` | H.Encaps.Red at R1 (SRH with one further entry, SL = 1, LE = 0), End.X at R2 (SL 0), DT46 at R4 |
| uSID strict path `[R1.uA→R2, R2.uA→R4, R4.uDT46]` (F3216 bare) | one container, no SRH; **R1 executes its own uA before transmitting** (DA shifted to `B:A2:D4::`, outer hop limit 63 on the wire), R2 shifts (62) and forwards, R4 decapsulates; compiled entry trace-equivalent to the step-by-step run |
| uSID with SRH: 7 C-SIDs (loose path with uN and uA) | DA = container 1, SRH = [container 2], SL = 1; after the sixth C-SID `arg == 0` → SL 0, DA = container 2 (PSP pops the SRH) |
| uSID validity | `[R2.uA→R4, R4.uDT46]` from R1 invalid under the strict profile and forwards wrongly under basic validation (trap test); `[..., R4.uN]` without USD invalid; `[R1.uA→R2, R2.uA→R3, R3.uDT46]` for endpoint R4 invalid (`ENDPOINT_MISMATCH`); a literal SID list without structure metadata is accepted uncompressed |
| Composite vs bare | `B:N:F::/64` and `B:F::/48` are distinct SIDs; the SONiC round trip preserves each literally |
| BSID steering | static via BSID → policy legs; H.Encaps at R1, no BSID on the wire |
| Gate C: reference protocol with the oracle disabled | after convergence the agent's rows equal the oracle rows of a separate oracle network under **normalized** comparison (prefix, metric, next-hop set, final forwarding; ownership and row identity ignored); an observed local interface DOWN at t=10 reacts immediately, a muted hello channel with oper still UP withdraws after the hold time, then re-flood, SPF and the same final placement; one AGENT delta per round with the successful receipts inside; cold start converges over link-local sessions; a heartbeat-only interval causes no SPF, FIB or placement work |
| Round overflow | a same-time subscribed-state feedback loop with `run_delay = 0` (permitted, guarded) raises `ConvergenceError`; a positive-delay message storm is bounded by a time/event budget instead |
| Agent batch failure | one agent's invalid output (including an allocation conflict with another agent's accepted output) leaves the other agents' outputs committed in the round's single AGENT delta, propagates an aggregate failure, and `retry()` re-runs only the rejected receipt with its captured inbox prefix; an observer failure after publication re-runs nothing |
| NHT | R1 registers 10.0.0.2; with every alternate route removed the result becomes UNRESOLVED and the agent withdraws dependents; a self-covered next hop reports UNRESOLVED with `via_prefix == P`; a metric-only change of the resolving route notifies with the new cost although the FIB object is unchanged; a formerly failed lookup notifies when a more-specific row appears |
| Sessions | U1, U2 sent during a transient outage arrive in order after recovery; a datagram sent later with a shorter link delay never overtakes an earlier one on the same channel; a failed wire under carrier delay drops datagrams although oper is UP; a no-progress outage longer than the timeout closes the connection, both agents get `SessionEvent(DOWN, TIMEOUT)`, late events of the old incarnation are no-ops; no listener → `REFUSED`; simultaneous opens yield two connections; a full admission queue rejects explicitly |
| Client contract | identical row add and missing-key delete yield `None`; `sync` from one client leaves another's rows untouched; a bad output raises, leaves rows, state, outbox and RNG unchanged, and the retry consumes the same inbox |
| NetGraph scenario (Gate A) | the README's dual-site Clos scenario (blueprints, `count: N` parallel links, `demands`, `failures`, `seed`) imports through `from_scenario`; with the oracle the per-directed-edge FLUID loads equal NetGraph's `SHORTEST_PATHS_ECMP` placement at 1e-9 when nothing is dropped; each failure iteration applied as a timed schedule reproduces NetGraph's per-iteration delivered volume; `to_network` writes utilization back and `results.json` loads in NetGraph tooling |

## Probabilistic failures and the study entry point (revision 13)

Decided on 2026-09-20 from experiments (scripts in the session scratchpad:
`exp_mc.py`, `exp_avail.py`, `exp_leases.py`, `exp_ng_mc.py`,
`exp_ng_vs_ns.py`, `exp_parallel.py`, `exp_profile_iter.py`).

### What was measured

| Experiment | Result |
|---|---|
| NetGraph draws vs NetSim draws, same scenario and step seed (`square_mesh`, 6 iterations) | identical failure patterns in the same order, identical `occurrence_count`, identical `failure_id` (blake2s of sorted nodes `|` sorted links) |
| `backbone_clos.yml` (127 nodes, 756 links), 50 iterations of `weighted_modes` | NetGraph static MC: 0.3 ms per iteration; NetSim fork + converge: 2.4 s per iteration; 41/41 failure ids matched |
| Profile of one NetSim iteration on that scenario | oracle IGP 4.1 s (Dijkstra for every device and AF, twice), FIB 2.8 s (32k prefix resolutions), both full recomputes for one failed link |
| Monte Carlo on Clos 16x4: rebuild vs `Network.fork()` vs timed fail/restore | 69 ms / 56 ms / 88 ms per iteration; derivation dominates, not construction |
| Forked iterations on 3.14t threads (Clos 16x4, 64 iterations) | 2.3x on 4 threads, flat at 8 (shared-root refcount traffic); 1.0x on the GIL build |
| Renewal process on Clos 8x4, 32 links, MTBF 1e4 s, MTTR 100 s, 2027 failures | 171 s wall (85 ms per failure, about 10 records each), 194k timeline events in 92 MB, availability computable from `delivered_series` |
| Policy-style events with durations, Poisson arrivals, up to 9 overlapping | lease counting keeps "link UP iff no lease held" with 0 violations over 577 failures |
| Delivered volumes vs NetGraph | comparable only under the same capacity model; NetGraph ECMP admission is lossless per demand, NetSim UNCONSTRAINED is not, so the check stays scoped to "nothing dropped" as in the acceptance row |

### Conclusions

1. **Static Monte Carlo stays NetGraph's job.** NetSim is four orders of
   magnitude slower per settled iteration and cannot compete with the
   C++ core on combinatorial studies; it should consume NetGraph's draws
   and add what NetGraph cannot express: the transient (loss during
   convergence under carrier delay, FIB delay and fast failover), time-based
   availability, and protocol behaviour. The one performance lever is
   incremental IGP and FIB (and Core-accelerated SPF), not the failure
   machinery.
2. **NetGraph failure policies are the selection language.** A policy draw
   is `FailurePolicy.apply_failures_typed` seeded per draw; NetSim reuses
   `FailureManager.compute_exclusions(policy, seed_offset=effective_seed + i)`
   bit-for-bit, so an iteration in NetSim and in NetGraph share the
   `failure_id`. Risk groups resolve to members inside NetGraph; NetSim
   applies nodes as `enabled=False` and links as `fail()`, never as masks,
   so the DES sees transitions.
3. **Time is NetSim's addition.** NetGraph has no duration, repair or
   schedule concept and its schema rejects unknown keys in `failures`, but
   policy, node, link, risk-group and demand `attrs` are free-form and
   workflow steps accept arbitrary kwargs. NetSim timing parameters
   therefore live in `attrs.netsim` (per entity: `mtbf`, `mttr`,
   `carrier_delay_down`, `fib_delay`, `fast_failover`, interface names,
   addresses) and in the NetSim workflow step's kwargs (per study: rate,
   duration distribution, horizon, model, retention).

### Failure sources (`runtime/failures.py`)

Every source yields fault events `(entities, start, duration | None)`
applied through one **lease registry**: an entity fails when its first
lease starts and restores when its last lease ends, so overlapping events
(a risk group and one of its members, two concurrent draws) compose
correctly. Entities are devices, links and risk groups (a group is the
transitive member set resolved once).

| Source | What it is | Seeds | Use |
|---|---|---|---|
| `Schedule` | explicit timed events from Python, a table, or a NetGraph `results.json` replayed by `failure_id` | none | reproductions, worst-case patterns found by NetGraph |
| `Draws` | one failure set per iteration: a NetGraph policy with `effective_seed + i` (NetGraph-compatible) or an enumeration (`all single links`, `all pairs`, `all risk groups`) | NetGraph's | transient studies per failure pattern, dedup by `failure_id` with `occurrence_count` as the weight |
| `Process` | a point process over a horizon: per-entity renewal (TTF and TTR distributions from `attrs.netsim.mtbf/mttr` or defaults; exponential, lognormal, Weibull) or policy-driven arrivals (Poisson rate per mode, each arrival draws a set through the policy and holds it for a drawn duration) | derived from the scenario seed with NetGraph's `SeedManager` formula and the components `("netsim", kind, name)`, so streams are reproducible and independent of NetGraph's | availability, loss-time, concurrent-failure distributions, recovery times |

Validation tests: seed compatibility (failure ids equal NetGraph's for a
scenario and step seed), lease invariant under random overlap, renewal
unavailability converging to `MTTR / (MTBF + MTTR)` per entity, schedule
replay reproducing a NetGraph pattern, results round trip.

### Iteration semantics

An iteration forks the converged baseline (`Network.fork()`: shared
immutable root, no copy), applies the set at `t0`, runs until settled (the
transient is on the timeline), optionally restores and settles again (the
recovery transient), and records: NetGraph's `FlowIterationResult` fields
(`failure_id`, `failure_state`, `occurrence_count`, `flows`, `summary`)
plus `data.netsim` (settle time, bits lost during the transient, drop
reasons, event counts, per-demand downtime). Iterations are independent,
so they parallelize by process (roots are immutable; threads give 2.3x on
3.14t today).

### Entry points

1. **Python one-off**: `Network` + `Simulation` + a failure source, zero
   dependencies. `Simulation.failures(Process(...))` and
   `Simulation.failures(Schedule(...))` schedule the events.
2. **NetGraph `Scenario` (recommended for studies)**: the expanded
   scenario is the description of record (network, demands, policies,
   risk groups, seed); `Study.from_scenario(scenario, **options)` builds
   the baseline through the adapter and exposes `iterations(draws, ...)`
   (a `Draws` source from a policy or an enumeration), `enumerate(...)`,
   `process(source, horizon)`, `replay(results, step, select)`, each
   returning a `StudyResult` with `to_ngraph()` (NetGraph result shape)
   and `rows()`; iterations run serially in this revision. NetGraph
   `combine` demands become one anycast destination announced by every
   target with an even share per source; `pairwise` splits the volume over
   the pairs; NetGraph priorities (lower first) map to NetSim priorities
   (higher first) with the original value kept for exports. NetSim does
   not grow its own DSL.
3. **Workflow step**: `netsim.adapters.ngraph` registers `NetSimStudy`
   with `register_workflow_step`, so a scenario YAML can carry a
   `type: NetSimStudy` step with NetSim kwargs; `netsim run scenario.yaml`
   imports both packages and writes NetGraph's `results.json` shape with
   the NetSim step beside NetGraph's steps, and `ngraph run` works once
   `netsim.adapters.ngraph` is imported.

### Work item (before Gate B)

`runtime/failures.py` (leases, Schedule, Draws with enumeration, Process
with distributions), `study.py` (Study, StudyResult, availability and
loss metrics from the timeline, process parallelism), adapter additions
(policy draws with NetGraph seeding, `attrs.netsim` mapping, `NetSimStudy`
step, results export and replay), a `netsim run` CLI, and the tests above.
Incremental IGP and FIB are a separate performance item that this work
does not depend on.

## Scale: what changes now (revision 14)

An independent Codex scale review (report at
`/private/tmp/netsim-scale-review-20260920/report.md`, critique of this
section in the session scratchpad `codex-review-4.md`) measured the Gate A
tree at 1k to 100k devices. Every headline claim was reproduced on the
live tree on 2026-09-20 (`verify_scale.py`, `verify_converge.py`,
`verify_pending.py`, `proto_shards.py`, `proto_igp_rib.py` in the
session scratchpad). What the numbers say, and what they do not:

| Claim | Reproduced | Root cause in the tree |
|---|---|---|
| one-device commit costs 16 ms at 100k devices | yes: 16.5 ms = `bump_epochs` 6.5 ms + `StateDelta.is_empty` 8.7 ms; the top-map copy itself is 0.24 ms | both walk every device although only one changed (`derive.bump_epochs`, `state.diff_pmap`) |
| RIB `rows(prefix)` is linear in the shard | yes: 631 µs per lookup at 10k rows; the resolver is quadratic | `RibState.rows` sorts and filters the whole prefix-length shard |
| pipeline pending scan is quadratic in distinct deadlines | yes: 0.8 → 5.3 ms per deadline from 250 to 2000 debounce deadlines | `_run_kind` scans all `kind.pending` on every run |
| `round_end_scheduled` never shrinks | yes | fixed: popped when the round closes |
| Tarjan recursion fails at chain length 1000 | yes | fixed: explicit-stack Tarjan, tested to 20k with a reference |
| `FrozenPrefixTable.shards()` leaks writable inner dicts | yes (introduced with the timeline) | fixed: inner tables wrapped too |
| initial convergence 512 devices 50 s; repeat without change 4 s at 256 | yes: 8.4 s / 4.1 s at 256 on the live tree | `derive_fib` re-resolved every (device, AF) even when the resolver epoch had not moved; fixed: epoch gate, now 5.6 s / 1.1 s; the remaining no-op cost is the oracle SPF for every device |
| RIB index and per-pass egress cache give only 1.3–1.5x on convergence | yes: prototype 8.4 → 6.0 s at 256 | the dominant cost is resolving every prefix on every event and running SPF for every device, not lookups |
| 100k devices need 430 MB of configuration | plausible, not re-measured | ~4.3 KB per device across five interface and link records |
| N² RIB rows in a flat all-to-all domain | arithmetic, correct | the oracle installs a route to every loopback on every device; hierarchy or aggregation is a scenario property, not a code fix |

Not accepted from the report: the "P0" framing of keyed agent
subscriptions, observation byte budgets, backend contracts and a full
point resolver as blockers before Gate B. Agents do not exist yet, the
observation policy already has retention knobs, and the resolver
acceptance matrix is the Gate C incremental-resolution item. They stay
P1/P2 by profile.

### The rule that fixes the class of issues

Bookkeeping must cost in proportion to the changed shards and inputs;
derivation must cost in proportion to the affected dependency closure
plus the output it necessarily produces (a bridge failure legitimately
changes every device's routes, and no data structure removes that
output). Any wider conservative scan is named, measured and bounded,
never implicit. Analytical and protocol-simulation scale results are
published separately against a workload passport. The Gate A tree
already provides the two ingredients: identity-first deltas and resolver
epochs. Where a step still walks everything that did not change, the fix
is structural, not a cache.

1. **Sharded persistent top-level maps** (`state.py`). `PMap` keeps its
   API but the `devices`, `links` and `demands` maps (later any per-device
   table that grows with N) become two-level: 2^k shards by key hash, a
   `set` copies one shard and the shard vector, and `diff_pmap`,
   `bump_epochs` and `changed_paths` walk only shards whose identity
   differs. Prototype at 100k keys: `set` 0.24 → 0.003 ms, one-key diff
   5.3 → 0.02 ms, `get` 0.09 → 0.15 µs. This removes the O(N) commit,
   the O(N) epoch bump, the O(N) delta and the 3.85 MB per snapshot at
   100k at once, with no transaction API change. Builder semantics stay
   (detach on build). Canonicalization returning old objects is what makes
   shard identity meaningful, so derivations must keep returning the old
   record when nothing changed.
2. **`Network.batch()`**: a scoped transaction that applies many builder
   operations to one candidate root, validates once and commits once, for
   bulk construction and the adapters (10k `add_device` calls take 6 s
   today because every call is a global commit).
3. **RIB prefix index** (`routing.py`): `prefixes` becomes
   `FrozenPrefixTable[tuple[Route, ...]]` (prefix → rows sorted by rank),
   maintained by `rib_apply`, so `rows(prefix)` is O(1) and `rows_of` uses
   a client index. Prefix-length shards remain the storage.
4. **Per-kind deadline heap** (`pipeline.py`): `(deadline, generation,
   entity)` with lazy invalidation (an entry is stale when
   `pending[entity]` no longer equals its deadline); due work pops while
   `deadline <= now`. DEBOUNCE reschedules push a new entry and leave the
   old one to expire. `scheduled` and `round_end_scheduled` entries are
   removed when consumed.
5. **Oracle IGP reuse** (`igp.py`): the adjacency and egress structure is
   built once per (invocation, AF) and shared by every source's SPF; a
   family is skipped only when its whole destination set is empty, and an
   empty result is still synced to withdraw stale rows. Memoizing across
   invocations on input identity (inside an owned source object, never a
   module-level cache, never shared through `fork()`) stays open together
   with the convergence certificate.
6. **Epoch-gated derivation** (done): `derive_fib` skips a (device, AF)
   whose processed epoch equals its input epoch, so a no-op converge and
   `Simulation()` on a converged network resolve nothing. Any RIB change
   of a device advances **both** families' epochs and schedules both FIB
   runs, because a row may resolve recursively through the other family
   (RFC 8950); until dependency-selected invalidation exists this is the
   conservative rule.
7. **Correctness now** (done): iterative Tarjan; sealed prefix-table
   views and a constructor that copies its inputs; bounded round
   bookkeeping; resolver dependencies scoped per prefix frame (memoized
   children merge their dependencies into the parent) so `depends_on` is
   exact and the total is linear in the table instead of quadratic (3000
   blackhole routes: 4.5 M references → 3018); a kind whose own commit
   dirties it again gets its successor round (due work is claimed before
   the run); adjacencies carry the next hop's family.

Contracts the Codex critique added to the items above:

- Sharding is O(S + N/S) per mutation and O(S + qN/S) per diff with q
  changed shards: linear in N with a small coefficient, not sublinear;
  benchmark 256 and 512 shards; keep small maps compact; mix the key hash
  (aligned integer keys such as `i << 8` fall into one shard under a plain
  mask); include `allocators.next_ifindex`; make `PMap.__eq__` shard-aware
  so `canon()` and record comparisons do not restore full scans; define
  iteration order explicitly (insertion order is no longer natural) and
  keep set-like `keys()` equality; never canonicalize with `tree_equal`,
  which ignores timestamps and epochs.
- `Network.batch()` must stage into builders and freeze once (persistent
  `set` per operation still copies shards), must not rebuild the prefix
  index per imported route, and must invalidate provisional handles on
  abort (generations roll back with the tree, so an escaped handle could
  become valid again): either non-reused generations or explicit
  provisional invalidation.
- The deadline heap keeps a monotonically increasing per-kind ticket,
  separate from round generations, as the invalidation key and the tie
  breaker (entities may be incomparable); COALESCE keeps the earliest
  deadline, DEBOUNCE replaces with the latest request even if earlier;
  retry keeps an in-flight batch without overwriting newer requests;
  stale entries are compacted against live pending work, and stale
  `StageEvent`s already in the engine queue are accounted for.
- Convergence shortcuts need a certificate, not a tree version: a
  version-only skip would keep a 2 Gbit/s delivery on a 1 Gbit/s link
  after `set_capacity_model(LOSSY)`, and `add_source` and the evaluated
  time also change results without a version bump. A certificate covers
  root identity, derivation-configuration revision and time, is issued
  only after a full convergence, and may be copied to a fork.
- Oracle reuse: skip a family only when the whole destination set is
  empty (an addressless device is valid unnumbered transit), sync an empty
  result to withdraw stale rows, and never key a memo inside a source
  object that `fork()` shares by numeric epoch alone.
- Observation: `Timeline` appends records unconditionally, so disabling
  extraction does not establish a memory plateau; long runs need a record
  budget (P1).

**Status (2026-09-20, branch `network-layer-gate-a`):** items 1–7 and
the revision 13 failure/study layer are implemented, each on its own
Codex worker branch with A/B/A numbers under `benchmarks/` and
`tests/runtime/*.md`, merged with FIB/placement fingerprints unchanged
(`tests/test_fingerprints.py`), and hardened by two adversarial review
rounds (scratchpad `codex-review-5.md`; fixes: batch epoch consumption
after an in-batch converge, validator rejects the mutable prefix-table
builder, Study tolerance and single-pass metrics, lease consistency under
observer exceptions, NetGraph `combine` as anycast and priority direction,
backward-band invalidations to the successor round, RIB delete ownership,
incremental client/prefix indexes, linear carrier invalidation; third
round: `converge()`/`place()` inside `batch()` raise (a batch is one commit
of builder operations, derivations run on committed roots only),
`update(fn)` inside a batch advances epochs for its own changes, retry
keeps successor-round work out of the current round, every observer runs
before an observer exception is re-raised, anycast allocation is
collision-checked and fork-safe, adapter metadata rolls back on abort and
is copied by `fork()`, `strict` import rejects untranslated NetGraph demand
options).
Integrated measurements on the same machine: one-device commit at 100k
devices 16.5 ms → 0.076 ms; 64 retained roots at 100k 246 MB → 1 MB;
`rows(prefix)` at 10k rows 631 µs → 0.3 µs; one-row RIB add or delete at
10k rows 1.5 ms → 17 µs; 256-device ring initial convergence 8.4 s →
2.0 s, no-op 4.1 s → 0.29 s, one failure 1.6 s → 0.47 s; 10k `add_device`
6.8 s → 0.09 s in a batch; NetGraph backbone import plus convergence
2.43 s → 0.66 s and 2.4 s → 0.52 s per failure iteration; 2000 carrier
deadlines on one device 10.5 s → 2.4 s (1.2 ms each, mildly rising);
Monte Carlo iteration on Clos 16x4 56 → 35 ms. Lookups cost 1.8x on
sharded maps (117 ns vs 64 ns); bulk RIB sync is 1.4x slower for the
index maintenance. Unchanged by design: the per-event cost on small
topologies (Clos 8x4 renewal study still 83 ms per failure, dominated by
the oracle SPF for every device and full dirty-FIB resolution), which is
the incremental-resolution and oracle-memo item below.

Acceptance for 1–5, each with an old-vs-new measurement on one quiet
machine and fingerprint equality of FIBs and placements before and after:
a one-device commit at 100k devices touches one shard (< 0.1 ms); 10k
devices build in a batch in under 1 s; 10k-row `rows(prefix)` in under 5
µs; 2000 distinct deadlines run in time linear in the count; no-op
converge at 256 devices under 0.2 s (measured 0.29 s: the remaining cost is the oracle SPF for every device, kept as the target of the oracle memo item); convergence fingerprints unchanged
for 32 to 256 devices.

### What remains the bottleneck afterwards, and its plan

After 1–5 the per-event cost is the oracle SPF for every device plus the
FIB re-resolution of every prefix of every device whose rows changed.
That is the **incremental resolution** item (deferred until a measured
Gate C workload requires it; Gate C itself delivers scoped point queries
and indexed notifications, see slice C2): rows reused by identity
through `sync` already mark what changed; the resolver then re-resolves
only changed prefixes and the dependents recorded in `depends_on`
(interfaces, queried prefixes including failed lookups), with a measured
fallback to a full rebuild when the closure is large, and the acceptance
matrix from the design (batch add/withdraw, competing sources, covering
prefix change, recursive chain and cycle, ECMP leg down, equality with
the full resolver after every event). Native SPF (NetGraph-Core, 10 ms
per 100k-vertex SPF vs 70 ms in Python) comes after that, by profile,
and only together with a storage that does not materialize one Python
object per route: an N² flat domain is a scenario property that no
language change removes.

Two modes, one forwarding model: the analytical mode (oracle, instant
convergence, lazy routes allowed behind an explicit interface) and the
protocol mode (local views, messages, timers, stale FIBs preserved) share
interfaces, transfer availability, RIB/FIB contracts, SRv6 semantics,
probes, accounting and the timeline schema; they may differ in how state
is materialized. Sizing a study needs a workload passport (devices,
degree, routes per device, demands and classes, sessions, event rate,
history detail), and 100k support is claimed only against such a passport
with published time and memory, never from the ability to build the
configuration.

## Gates and phases

1. **Gate A**: `core.py` `DEFERRED`; `model/addressing.py`, `lpm.py`,
   `packets.py` (templates, wire size), `hashing.py` (threshold only),
   `state.py` (owning PMap, immutability validator, generations, paths,
   canonicalization), `interfaces.py` and `links.py` (physical
   availability, LAG component two-pass), `routing.py` (rows, epochs,
   outcomes, resolver), `forwarding.py` (plain-IP records, the action
   interpreter, probes and timed forwarding), `igp.py`, `contracts.py`
   (clients only), `derive.py`, `entities.py`, `network.py`; `flows.py`
   plain IP (classes, SCC legs, wire accounting, UNCONSTRAINED and LOSSY,
   report); `runtime/pipeline.py` (rounds with generations, kinds, retry,
   convergence limit), `events.py`, `simulation.py`; diamond rows through
   "mixed group"; NetGraph adapter (`from_scenario`: topology, demands,
   failure schedule, seed; `to_network` and `results.json` export;
   `srv6=False`) and Core adapter for the cross-check.
2. **Gate B** — **implemented on 2026-09-20 on `main`** (slices B0–B4 as
   seven Codex xhigh worker branches `gateb/g1..g7` plus follow-ups,
   integrated with the plain-IP fingerprint oracle unchanged; 1238 tests on
   both interpreters, 134 against the real NetGraph and Core packages;
   three adversarial review rounds (scratchpad `codex-review-10-gateb1.md`,
   `codex-review-11-gateb2.md`) whose 16 findings were all fixed by the
   owning workers or the integrator; remaining cost: plain-IP convergence
   about 6% slower (clos 8x4 converge plus three failures 30.6 → 32.6 ms;
   1250 tests after the fourth review round) from packet-state vertices
   and SR hooks in placement). Profile of the remaining per-event cost on
   the 256-device ring, one link failure plus converge, 870 ms wall: the
   oracle runs SPF for every device and family twice (the fixed-point
   confirmation pass repeats it: 1024 SPF calls, 0.7 s profiled) and syncs
   every device's rows (3072 `rib_apply` calls, 0.39 s), while the FIB
   re-resolves every prefix of the 92 dirty (device, family) pairs (11776
   prefix resolutions, 0.6 s). The next performance items are therefore,
   in order: skip the oracle's second pass when its inputs are identical
   (the convergence certificate), avoid re-syncing unchanged devices, and
   the incremental resolver.: `srv6.py` (structures, allocator, compression, policies
   with one owner, validation layers), the SR extension of the action
   program in `forwarding.py` with the authoritative Gate-B behaviour
   set, SR legs in `flows.py`, steering precedence, SONiC adapter with
   literal SIDs; diamond Gate-B rows; hand-checked RFC 9800 §6.2 vectors.
   Delivered in acceptance-gated slices, each keeping plain-IP
   fingerprints unchanged and clock-free convergence equal to settled
   timed execution:
   - **B0** behaviour and flavor matrix as the authoritative table; typed
     SR records and the header-chain contract; owner-scoped SID and
     policy operations; allocator and invalidation wiring. Exit: every
     unsupported combination rejected; collision, exhaustion and import
     failures atomic; forks detached; local, remote and failed-query
     dependencies tested. Invalidation scenarios that must schedule the
     consumer: a remote adjacency SID goes down without changing the
     headend's RIB; a missing SID appears; the SRv6 source or hop-limit
     setting changes while rows stay identical; an owner deletes and
     recreates a SID; a batch changes and restores an input (committed
     dirty epoch). Every changed SR input advances the affected consumers'
     epochs and runtime work; negative queries are recorded; bare local
     SIDs are scoped by device and block; resolution reads one immutable
     snapshot regardless of device iteration order; the oracle originates
     locator prefixes; conservative all-SR-consumer invalidation is
     acceptable at first.
   - **B1** uncompressed literal SIDs, locator routing, H.Encaps and
     H.Encaps.Red, End, End.X, End.DT46, headend-local execution. Exit:
     hand-checked traces for IPv4 and IPv6 inner packets; malformed SRH,
     TTL, MTU, flavors and physical failures; compiled and interpreted
     execution agree on the same encoded input.
   - **B2** one-owner policies, weighted lists, steering and fallback
     (excluding the triggering action so IGP fallback cannot re-select
     it), stateful SR FLUID and HASH with capacity. Exit: timed diamond
     failover and restore; validity, programming and delivery reported
     separately; per-edge frame sizes; repeated-device visits and loop-cut
     cases; conservation including tiny rates.
   - **B3** NEXT-C-SID compression, bare and composite forms, several
     blocks and widths. Exit: independently checked encoding boundaries
     (block changes, mixed widths, non-zero arguments, unknown structures,
     capacity limits, terminal-tail fit); local-scope and cross-connect
     cases (End.X's shifted cross-connect checked apart from End's lookup
     continuation); compressed and uncompressed equivalents deliver along
     the intended physical path when TTL, MTU and capacity do not
     constrain either, with each encoding's header sizes and hop-limit
     transitions tested separately.
   - **B4** versioned, bounded SONiC subset; explicit-path NetGraph SR
     translation; policy timeline and Study export. Exit: literal SID
     preservation; strict errors for unsupported input; destination,
     priority and unit exports; repeatable study results with measured
     scaling limits.
   Across slices: nonzero FIB and carrier delays, successor-round
   invalidation, retry, observer exceptions, change-and-revert batches,
   owner conflicts and failed allocation are exercised; LOSSY keeps its
   qualified tests (no unconstrained superposition assertions) and HASH
   convergence to FLUID is asserted only for independent hash domains.
3. **Gate C** — **implemented on 2026-09-20 on `main`** (slices C0–C5:
   the C0 contract written by the integrator, then five Codex xhigh worker
   branches `gatec/c1-agents` (scheduler, subscriptions, inboxes, timers,
   transactional publication and retry), `gatec/c2-nht` (local query and
   NHT, `srdb_source` agent mode, scoped SR consumer invalidation),
   `gatec/c3-transport` (link channels, sessions, indexed reachability),
   `gatec/c4-reference` (the oracle-free reference link-state protocol with
   44 acceptance tests and a locality harness) and `gatec/c5-study` (study
   windows, fresh-runtime warm-up, streaming metrics, workload passport),
   each integrated with the plain-IP fingerprint oracle unchanged and
   verified on both interpreters and against the real NetGraph; reports in
   `tests/model/c2*-handoff.md`, `docs/history/c4-reference-agent.md`,
   `docs/history/c5-study-windows.md`). Integration decisions recorded in the
   commit history: a fresh `Simulation` restarts every agent node another
   runtime initialized (a fork is not a warm protocol restart);
   `AgentConfig.processing_delay` defaults to 1 ms so deliveries over
   zero-delay links advance the clock; opaque agent values compare by
   identity; the context exposes no path reachability. The first
   adversarial review round (scratchpad `codex-review-15-gatec1.md`: 4 P0,
   5 P1, all reproduced and accepted) was fixed by the owning workers and
   merged on 2026-09-21 (main `a2370a0`, 1588 tests on both interpreters):
   per-output commit-time validation so an invalid output is rejected
   alone, publication status fixed before any finalization step, control
   notifications (session events, rejections, timers) admitted into a
   bounded allowance whose exhaustion fails explicitly, a physically lost
   datagram admitted and lost silently (only local admission errors are
   rejections), detached prospective NHT queries on the context
   (`ctx.resolve`, `ctx.installed` over the device subtree only), scoped
   registrations bound to the interface generation (`SCOPE_STALE` after
   re-creation), whole-tree state validation only under `debug_validate`,
   dependency- and owner-indexed session dispatch with bounded DOWN
   retention, and aggregate stats with opt-in bounded samples; the
   reviewer's ten probes re-run clean on the merged tree. Measured on the
   same machine, 64-router reference-protocol cold start: 0.625 s simulated
   in 14.1 s wall before the fixes (53% transitive validation of agent
   state on every run) and 6.4 s after (4224 session messages, 2176 SPF
   runs, 4858 events); one link failure 1.09 s → 0.41 s wall (2972 → 1111
   µs per event). The second review round (scratchpad
   `codex-review-16-gatec2.md`) confirmed eight of the nine fixes, found
   one partial (the shallow admission check admitted a frozen record
   wrapping a list: fixed on 2026-09-21 by `validate_admitted`, an
   incremental walk that trusts subtrees reused by identity from the
   previously admitted value, so a new state costs only its changed
   subtrees and whole-root walks stay debug-only; 32-router cold start
   1.11 → 1.32 s wall for the guarantee) and two new items assigned to the
   owners: the agent-study baseline must come from the warmed protocol
   runtime rather than the cold synchronous tree (C5), and rejected
   receipts must be parked outside the runnable heap until `retry()`
   (C1); both merged (98a0615, 5e0ef63). Confirmation rounds 3 to 9
   (scratchpad `codex-review-17..23`; round 9 on main `380691a` found
   no new finding and no remaining blocker within the stated boundary)
   confirmed every earlier fix and
   closed the admission theme step by step: the immutability walks are now
   fail-closed through one classifier (exact leaf types; leaf, tuple and
   frozenset subclasses only without attribute storage read from real
   descriptors, which admits `MacAddress` and `NamedTuple`; enum members
   only with the enum machinery's own attributes and their values walked;
   only classes decorated as frozen dataclasses themselves, inheriting
   only frozen dataclasses and storage-free mixins, with no instance
   storage beyond their fields and every inherited slot an effective
   field; `PMap` keys
   and values; frozen prefix tables with exact-int keys, masks and bits;
   `Fraction` and its storage-free subclasses with exact-int components;
   `FloatArray` owning exact bytes; declared-immutable types), and a subscription or NHT cause that lands
   while a receipt is parked gets its own run after a successful retry.
   Boundary stated for the record: enum members and declared-immutable
   types are class-level singletons trusted by declaration at admission;
   mutating them afterwards is a program-level contract violation the
   snapshot invariant cannot police. Scoped point queries and indexed
   notifications are in; full incremental FIB reconstruction stays
   deferred unless a measured Gate C workload requires it (the remaining
   64-router cost is dominated by full local FIB rebuilds: 164k prefix
   resolutions in the qualification run).
4. **After Gate C** (each its own review). Open/R and BGP are planned in
   `/Users/networmix/.claude/plans/netsim-protocols.md` (revision 8,
   2026-09-27, after internal adversarial reviews). It targets modern FRR,
   keeps FRR 10.5 as a settings preset, and adds a per-node settings system.
   It integrates the routing-policy plan in `NetSim/docs/plans/` (a shared
   policy engine) and a FIB programming and acknowledgement contract. That plan also
   records a confirmed resolver defect: answers depend on traversal order under
   recursion cycles and memoized depth truncation, and slice F1a fixes it.
   Remaining items: Open/R, BGP, resilient hashing,
   nested B6, REPLACE-C-SID, multi-client BSIDs, NHT-based incremental
   resolution, midpoint protection, VRFs, runtime checkpoint, in-band
   transport, `loop_model=AMPLIFY`.

## Verification

- `make qt`; `make check-ci` (lint, pyright, coverage ≥ 85 %) before each
  gate; `make check-ft`; benchmarks before any scale claim (route batches
  of 100k rows, report size, retained memory, update/delta cost, 8-leaf
  smoke within the 10 s timeout, 64-leaf marked `slow` with its own
  timeout), old vs new on one quiet machine.
- Scheduler invariants: kinds run in priority order within a round;
  backward invalidations land in the next round; `ROUND_END` and SETTLED
  ordering; convergence limit; retry after failure; positive-delay rule;
  `run(until)` and `settle()` semantics against `core.py`.
- State invariants: transitive immutability (validator), identity of
  unchanged subtrees, empty delta on no-op, one writer per key (origin
  tags), generations on handles, allocators unchanged after failed
  updates, sharded state keeps other shards' identity.
- Routing and SR: resolver fixtures pinned against NOS behaviour
  (precedence, weights, truncation), epoch-based status, neighbor and AF
  enablement matrix, invalidation matrix edge tests, RFC 9800 compression
  vectors, behaviour tests per RFC branch incl. malformed SRH, compiled vs
  interpreted trace equivalence, validation layer tests.
- Placement property tests: Kirchhoff per node and per demand on random
  acyclic FIBs; superposition and scaling under UNCONSTRAINED; Core
  `EQUAL_BALANCED` cross-check on random simple graphs (plain IP); SCC
  loop regression (healthy and looping branches merging); physical
  failure during carrier delay; LOSSY monotonicity; HASH with many
  microflows converging to FLUID on independent-domain cases.
- Agents: output validation and atomicity, locality of the view, FIFO
  and incarnation rules, cold start, reference agent equals oracle on
  random graphs.
