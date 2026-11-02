# NetSim protocols: Open/R and BGP (design and plan, revision 8, 2026-09-27)

> **Rename, 2026-10-02:** the project is now NetGraph-Sim: distribution `ngraph-sim`, package `ngraph_sim`, CLI `ngraph-sim`, scenario keys `attrs.sim` / `data.sim`, workflow step `SimStudy`. Paths `netsim/...` and the old names below refer to the same code, now in `ngraph_sim/`. The repository is github.com/networmix/NetGraph-Sim and the checkout `~/ws/NetGraph-Sim`. Legacy and compatibility paths described below (Study `settle` mode, `keep_*` aliases, top-level NetGraph attrs, `strict=False`, `Simulation.recorder`, unbound NHT keys, untagged deliveries) were removed on 2026-10-02.


Companion to the network-layer design of record,
`/Users/networmix/.claude/plans/hazy-foraging-cloud.md` (revision 17, Gates A,
B and C implemented). This document plans the item "After Gate C: Open/R, BGP"
of that design. Research reports, benchmarks and their citations live in
`/Users/networmix/.claude/plans/netsim-protocols-research/`:

- `research-openr.md`: Open/R at `facebook/openr` commit `81dae4c` (MIT), cloned at `~/ws/openr`.
- `research-frr-decision.md`: FRR bgpd and zebra decision process, multipath, NHT, next-hop rules, install, profiles, pipeline. Read at master `f1d7bec` (10.8.0-dev), cloned at `~/ws/frr`.
- `research-frr-rr-confed.md`: peer sort, route reflection, confederations, AS_PATH, attribute propagation, update groups, FSM, graceful restart (same commit).
- `research-bgp-options.md`: FRR, BIRD, GoBGP, OpenBGPD, ExaBGP, Batfish, C-BGP, Holo, RustyBGP and bgpsim compared; FRR topotests as a corpus; licensing; the FRR differential lane.
- `bench_bgp_scale.py`, `bench_agent_ctx.py`, `bench_pmap.py`: the measurements in section 1.

The default FRR dialect is **`frr-modern`**: master `f1d7bec` (10.8.0-dev),
cloned at `~/ws/frr`, with one suspect master change quarantined (Z5, section
2B.2). The **`frr-10.5`** dialect covers what SONiC builds (frr-10.5.4, tag
`4cb6d9e`, `~/ws/frr-10.5.4`). The full history with tags is at `~/ws/frr-git`.
Section 11 records what changed in each revision.

FRR `file:line` citations refer to master `f1d7bec` unless marked `10.5.4:`.
Open/R citations refer to `81dae4c`, and NetSim citations to main `0e5b299`.

---

## 0. Summary

NetSim gets a faithful Open/R IGP and an FRR-dialect BGP, both as protocol
agents on the Gate C contract. Nothing gets a privileged path into the model:
routes go through `RibClient`, next hops through NHT, messages through the
transport, and configuration through the tree. Protocols meet only through the
RIB, NHT and published device-local views.

Four phases:

1. **Foundation (S0, F0–F8, RP1, RP3, RP4).** In order of the list:
   - S0 scale hygiene: five measured fixes that make builds linear and idle
     agent runs cheap (section 14);
   - contract additions;
   - a fix for a confirmed defect: the resolver's answers depend on traversal
     order;
   - fixes for the measured O(table) costs that would make BGP-sized tables
     unusable;
   - the transport, underlay and toolkit pieces both protocols need;
   - the settings system (per-node overrides, dialects, profiles; section 2A);
   - the forwarding programming contract with FIB acknowledgement gating (F8,
     section 5.13);
   - the shared route-policy engine and its RIB, FIB and resolver hooks (RP1,
     RP3, RP4; section 5.8, from the reviewed routing-policy plan).
2. **Open/R (OR1–OR6) and BGP (BG1–BG7)** as two parallel tracks. BGP tests use
   a domain-scoped oracle IGP underlay, so neither track waits on the other.
3. **Integration (IX)**: IGP plus BGP scenarios for every deployment shape in
   the brief.

Section 12 is the implementation roadmap: milestones M0–M6, the test harness,
and per-slice files, signatures, tests-first lists and exit checks. Section 14
is the scale review: measurements on the current tree, experiments proving the
fixes, prototypes at 1M prefixes, the honest scale target with passports, and
the streamlined slice set (S0 first). Section 15 applies the Codex review of
that revision: the immutable `PackedTable` contract, corrected passports and
measurements, the per-leg cycle rule, the activation-stage `ip protocol`
filter, group versions for programming, and the authoritative slice and
dependency table (§15.9), which supersedes the earlier ones. Section 13
answers each part of the brief directly: IGP domain shapes, session types,
hop-by-hop iBGP instead of an IGP, flavor swapping, RR and confederations, RFC
annotation and direct versus indirect next hops.
4. **Later (BG8 and beyond)**: more decision flavors, add-path, graceful restart,
   BFD, SR color steering, an analytical BGP solver.

| Decision | Choice |
|---|---|
| IGP reference | The Open/R open-source daemon, module for module. Features absent upstream stay absent unless labelled `netsim_ext` |
| BGP reference | RFCs first; modern FRR (master, 10.8.0-dev) as the default dialect where the RFCs leave room, with `frr-10.5` (SONiC) as a settings preset; generic version differences are settings, bugs are not emulated; clean-room reimplementation with no FRR code |
| Differential oracle | Optional containerlab lane running FRR images: `10.7.1` release, the `master` nightly pinned by digest, and `10.5.4` for the SONiC dialect. It compares converged state only; goldens are committed as NetSim-generated data |
| Configuration | Tree state: agent configuration changes in place within a generation; commands are exec-only operations |
| Observability | Agents publish immutable operational views; tests, the timeline and studies read views, never agent internals |
| Modularity | One package per protocol and one submodule per real module. Submodules are pure functions over frozen sub-states, joined by explicit worklist queues |
| Replaceable parts | Frozen specs resolved against built-in tables with citations (decision flavors, multipath rules, Open/R selection mode, policy dialect), plus a settings system in which every setting is overridable per node, with dialects and presets as data (section 2A) |
| Domains | Configuration, not topology: a device runs 0..k IGP instances (more than one is `netsim_ext`) and at most one BGP instance |
| Scale rule | Cost proportional to change is a performance exit criterion for every protocol slice (§8), backed by operation-count and ratio benchmarks |
| Next hops | Direct and indirect exactly as FRR and zebra handle them: single-hop eBGP is non-recursive with a connected check, everything else is recursive, and BGP-over-BGP is allowed |
| Routing policy | One typed native language and evaluator shared by BGP, Open/R and the RIB, FIB and resolver hooks; exact vendor adapters (FRR subset first); bindings per node (D13) |
| Installation | An asynchronous programming contract with generation-guarded completions; FIB acknowledgement gating and inactive export per node (D14) |

---

## 1. Where the project stands

**Implemented** on main `0e5b299`: `make qt` passes 1648 tests, skips 11 and
deselects 13 slow ones (2026-09-26); CI runs Python 3.11–3.14 and 3.14t.

- Gate A: immutable state tree, rounds, interfaces and LAG, static and oracle
  routing, the FIB resolver with recursion and RFC 8950, placement, the NetGraph
  and Core adapters.
- Gate B: SRv6 with micro-SIDs, SR policies, steering, the SONiC subset.
- Gate C:
  - the agent contract (`netsim/model/contracts.py`);
  - NHT (`netsim/model/nht.py`);
  - transport (`netsim/runtime/transport.py`): link-channel datagrams,
    route-free scoped link-local sessions, routed sessions, simultaneous open
    giving two connections (RFC 4271 §6.8), abort versus drain, no-progress
    timeout, bounded queues;
  - the reference link-state protocol (`netsim/agents/reference.py`);
  - study windows with fresh-runtime warm-up.

**What already fits:**

- Several named agents per device, each with its own `ClientId(name, instance)`
  (`netsim/model/network.py:483-545`).
- Per-row distance: `rib_apply` never uses the profile distance, so one BGP
  client can install at 20 and at 200.
- Recursive next hops with a depth limit and cross-family resolution.
- NHT with `connected_only` and `resolve_via_default`.
- Scoped link-local sessions for cold start, unnumbered BGP and KvStore peering.
- Advertised SR-DB views.
- Fingerprints hash flattened FIB group content, not group ids
  (`tests/test_fingerprints.py:56-83`).

**Gaps.** Measured on this tree with the scripts in the research folder
(same machine, CPython 3.14), or confirmed in code:

| # | Gap | Evidence | Consequence |
|---|---|---|---|
| G1 | The FIB rebuilds every prefix of a (device, AF) on any input change (`netsim/model/routing.py:834-934`) | 4-router diamond with N recursive `/24`s via a loopback. One unrelated row added: 1.4 / 15.7 / 177 / 1709 ms at N = 0 / 1k / 10k / 50k. One IGP metric change: 1.6 / 16.5 / 187 / 1803 ms (≈ 35 µs per row) | Every event on a BGP-sized table costs O(table) |
| G2 | The agent context copies every RIB row of every client on every run (`netsim/runtime/agents.py:511-529`) | An idle agent whose run only re-arms a timer: 0.19 / 1.23 / 12.9 / 130 ms per run at 0 / 1k / 10k / 50k rows on its device | Every keepalive and hello costs O(RIB) |
| G3 | Admission re-walks every key of a changed `PMap` (`netsim/model/state.py:735-790`, `for k, v in o.items()`) | Agent state holding a `PMap` of N paths, one entry changed. `PMap.set` takes 1.5 / 3.4 µs, `validate_admitted` 20 / 236 ms, at 10k / 100k | Any large agent table costs O(size) per run |
| G4 | `CAUSE_ROUTES` scans every outcome row of each agent's client on a changed device (`netsim/runtime/agents.py:338-365`) | 8.5 / 270 ms per agent per commit at 10k / 50k rows, for every agent on the device | O(rows) per commit per agent; the largest per-agent cost measured |
| G5 | NHT per-owner views and notifications scan all registrations (`agents.py:366-391`); every epoch bump refreshes every registration (`nht.py:327-350`, `derive.py:904-911`) | code | O(registrations × agents) per commit |
| G6 | Listeners bind exact endpoints; sessions carry no TTL or GTSM (`netsim/runtime/transport.py:805-925`) | code | Cannot model single-hop versus multihop eBGP, per-peer TTL on one listening socket, or `ttl-security` |
| G7 | The oracle IGP is one flat domain over all devices (`netsim/model/igp.py:191-218`) | code | Multi-AS and multi-domain BGP tests cannot use the fast underlay |
| G8 | `AgentConfig` is fixed per generation, yet the runtime reads `run_delay`, the inbox limits and `listen_ports` from it (`agents.py:234, 424`; `transport.py:339-349`); reset and fresh runtimes rebuild from it (`agents.py:267, 1046`) | code | A configuration change would need a restart, which drops sessions |
| G9 | NHT reports a cost only for link-state sources and only when a single source resolves (`netsim/model/nht.py:180-196`); the answer is prospective (RIB), not installed | code | FRR's IGP-metric step uses the metric of the installed resolving route from any protocol: a BGP route contributes its MED, a connected or static route contributes 0 (`research-frr-decision.md` §3.4) |
| G10 | Agents can publish only `srdb_view` into the tree (`contracts.py:697`) | code | Tests, `Timeline.series` and study stability predicates would have to read opaque agent state. BFD-like cooperation has no channel |
| G11 | The reference protocol is monolithic and re-scans the whole LSDB on every run | `netsim/agents/reference.py` | Not a base for Open/R. It stays as the teaching protocol and contract probe |
| G12 | **Defect: the full resolver gives order-dependent answers.** The memo is consulted before the stack and depth checks, and results that were stack-excluded or depth-truncated are memoized (`routing.py:446-471`; lookups exclude everything on the stack, `:503`) | Reproduced (scale review `order_dep.py`, `order_dep2.py`). A two-route cycle A ↔ B under a covering `/8` resolves both to A's next hop or both to B's, depending on which is visited first. With `max_recursion_depth=4`, adding unrelated deeper chain members uninstalls a valid chain | An incremental resolver cannot be checked against the full one, and today's results depend on traversal order |
| G13 | `FibEntry.depends_on` is transitive and has no runtime consumer (only `forwarding.py:92` and tests) | After an IGP metric change every recursive entry changes (`interfaces` goes from `('e2','e3')` to `('e3',)`) and the group id changes. About 1.5 KB per row across RIB, FIB and outcomes (74.6 MB for 50k rows) | A hierarchical FIB cannot leave entries untouched |
| G14 | The Simulation path has further O(table) steps. The resolver builds fresh per-length dicts (`lpm.py:223-227`), so timeline FIB-event extraction (`timeline.py:832-866`) and the unchanged-FIB check (`routing.py:921`) walk everything. NHT refresh recomputes every registration on every RIB change, up to three times per commit (`derive.py:760-763, 810-812, 906-910`) | One added row at 10k / 50k: timeline FIB events 31 / 168 ms; unchanged-FIB check 5.9 / 102 ms; G4 8.5 / 270 ms per agent on the device. NHT refresh 40–49 µs per registration at 50k rows. One-row agent run 1.0 ms at 0 rows, 411 ms at 10k | Fixing only `resolve_fib` leaves the Simulation path O(table) |
| G15 | Conservative downstream invalidation. Placement recomputes every class through a device on any FIB change (`pipeline.py:643`; `flows.py:929-971`). Transport re-traces every connection through a device on any FIB change (`transport.py:608-660`). Both families' epochs are bumped on any RIB change (`pipeline.py:613`; `derive.py:869-879`), so PENDING is device-wide | code | Every BGP FIB commit re-places demands and re-traces sessions, and `rib_view` shows the whole table PENDING during `fib_delay` |
| G17 | **Quadratic network build.** `_validate_interface_config` walks every device per interface add (`network.py:738`) | 5.5 / 21 / 31 ms per device at 2k / 8k / 10k devices; linear at 95–125 µs once indexed (section 14.2) | 100k devices cannot be built |
| G18 | The MT RNG state (625 ints) is committed per agent run (`agents.py:792`) | 27 KB retained per idle run; 1.8 KB without it | Long runs with many agents grow without bound |
| G19 | Every agent run commits, because `runs`, `receipt` and `rng` change | 160–200 µs per idle tick; the DES core alone costs about 1.5 µs per timeout | 100k agents cannot tick |
| G20 | Per-table mask tuples (`lpm.py:193`) and about ten resolver objects per prefix | 25 KB per device with no routes; 1.5 KB per recursive row | Memory at 100k devices and 1M prefixes |
| G16 | Garbage collection multiplies allocation-heavy paths | G4 at 50k rows: 219 ms with GC, 54 ms without (778k tracked objects) | Passports must report heap object counts. Removing per-entry `DependsOn` saves about 8 objects per FIB entry |

---

## 2. Decisions

**D1. References, pins and licensing.**

- **Open/R** (MIT) is followed module for module at `81dae4c`: messages, FSMs,
  merge rules, timers and the initialization chain. Upstream facts that
  contradict common assumptions are honoured (`research-openr.md`, headline):
  - there is no domain name;
  - Decision implements only shortest-path ECMP;
  - DUAL flood optimisation is not wired in;
  - the default metric is RTT-based;
  - a fresh node boots soft-drained;
  - area import policy is a stub;
  - metric-based best-route selection is off by default.

  Anything NetSim adds is named `netsim_ext` and is off by default.
- **BGP.** The RFCs come first: 4271, 4456, 5065, 6793, 4760, 2545, 8950, 7606,
  8212, 5004, 6286, 1997, 4360, 8092, 5082, and later 7911 and 4724. Where the
  RFCs leave room, the dialect is **modern FRR**. Three reasons:
  - FRR covers everything in scope;
  - it publishes `bgp_path_selection_reason` codes that make selection traces
    diffable;
  - SONiC runs FRR, and NetSim has a SONiC adapter.

  Section 2B carries the analysis of 10.5 against modern:
  - the default dialect `frr-modern` follows master `f1d7bec`, except the
    quarantined Z5 tie-break;
  - `frr-10.5` reproduces SONiC's release defaults and generic behaviour
    choices, not its bugs;
  - every generic version difference is a setting with per-dialect defaults
    (section 2A), never a version check in code.

  Profiles (FRR `frr defaults`): `traditional` and `datacenter`. Distribution
  overlay: `sonic` (section 2B.4), each with provenance.
- **Licensing.** FRR is GPL-2.0+, so NetSim reimplements it clean-room.
  Behaviour comes from RFCs, FRR's documentation and FRR black-box runs.
  Comments cite FRR function names, steps and reason enums. No code or
  transliteration is copied.
- **Rejected as reference:**
  - GoBGP: no IGP-metric step;
  - OpenBGPD: no confederations;
  - Batfish: a fixed point with an approximate MED rule;
  - C-BGP: unmaintained since 2013;
  - Holo: no RR or confederations;
  - bgpsim: no confederations;
  - FRR under DES time: impossible, because it uses the wall clock and kernel TCP.

  BIRD 3 is kept as an optional second opinion when NetSim and FRR disagree.
- **Differential lane.** The FRR differential lane compares converged state
  only, and is opt-in and off `make check`. Its images and pins are in section
  2A.5 rule 7. FRR topotest data is read at run time
  from a pinned FRR checkout and never vendored; the data files carry no licence
  header.

**D2. Protocols are agents; no privileged path.** Agents see only what
`AgentContext` gives them and act only through `AgentOutput`. They interact only
through three channels:

- the RIB, through `RibClient` and the RIB feed;
- NHT;
- published views (`AgentOutput.views`, F0), which other agents on the same
  device may read. This is the FSDB/Sysdb principle.

No agent reads another agent's state.

**D3. Structure mirrors the real implementation, joined by explicit queues.**

- Each protocol is a package with one submodule per real module.
- Each submodule is a pure function over frozen records and `PMap`s:
  `(sub_state, queue_inputs, projection) -> (sub_state', queue_outputs,
  timer_ops)`.
- **Declared projections.** Each submodule receives only the declared slice of
  the context it needs, never the whole `ctx`. A guarded proxy checks this in
  tests.
- **Worklist.** The agent run drains a worklist of explicit module queues in a
  fixed priority order until every queue is empty, with a bound that raises if
  exceeded. This matters because Open/R's queues form cycles:
  - LinkMonitor ↔ Spark;
  - KvStore → Decision → Fib → PrefixManager → KvStore.
- **Programming-gated edges.** Edges that in reality wait for programming
  consume the F0 owner notification (`RowNotice INSTALLED`) instead of
  handing off within the run: Open/R Fib → PrefixManager, and FULL_SYNC →
  PREFIX_DB_SYNCED.
- **Timers.** Timers are namespaced `module/key`. Per-key deadlines (KvStore
  TTL, per-peer MRAI, hold timers) are multiplexed through one armed timer per
  module plus a deadline heap in state, as Open/R's `ttlCountdownQueue` does.
- **Randomness.** Each module draws from its own RNG stream, derived by name
  from `ctx.rng`, so a new draw in one module does not shift the jitter of
  another.

**D4. Replaceable parts are frozen specs with provenance.**

- Decision flavors are **named code implementations** of a small interface
  (`compare`, `select`, `multipath`) over narrow immutable inputs: `frr` and
  `rfc4271` ship built in, and a scenario may add a class at deployment. The
  setting `bgp.decision` stores the name, so it is overridable per node. There
  is no step interpreter and no per-run step compilation (§15.8, §16). Knobs
  that FRR exposes as `bgp bestpath ...` are ordinary settings.
- Multipath rules, the Open/R selection mode and the policy dialect are
  likewise named implementations selected by settings.
- User-defined steps are immutable classes with a purity contract and `refs`,
  passed by value inside the spec. There is no global mutable registry.
- Every built-in and user step declares `refs`: an RFC section, an FRR
  function, step or reason, an Open/R `file:line`, or a vendor document URL. An
  invariant test rejects a missing reference, which turns "annotated with RFCs"
  into a checked design rule.
- The flavor implementation is looked up by name from `ctx.agent_config` on
  each run (an O(1) dict lookup in an immutable per-agent table); callables
  never live in state or configuration (`validate_immutable`), and shared
  mutable caches are banned by the free-threading rule in AGENTS.md.

**D5. Domains are configuration.** An IGP domain is the set of IGP instances
that can form adjacencies. Four things decide it:

- which interfaces each instance owns;
- area membership (interface and neighbour regexes);
- interface exclusions;
- ports, which are per-domain configuration with equal defaults.

Consequences:

- A device runs 0..k IGP instances with distinct `ClientId('openr', i)` and
  disjoint interface sets; overlapping sets are rejected. More than one instance
  is `netsim_ext.multi_instance` (a per-node setting, off by default), because upstream Open/R hard-codes FIB client
  786 (`Fib.h:392`), so two daemons would overwrite each other. Each instance
  drops hellos on interfaces it does not own, and only one instance's
  `srdb_view` backs the device's SR-DB.
- A device runs at most one BGP instance (VRFs stay deferred).
- A single-device domain is either an instance whose interfaces are not
  discovered, or no IGP at all (connected, static and BGP routes only).
- Area `"0"` matches any area during negotiation (`Spark.cpp:2112-2121`), so
  domains separated only by area id still peer if either side says `"0"`. The
  deploy helpers never rely on area names for separation.

**D6. Cost proportional to change is a performance exit criterion.** Functional
work starts once F0, F2a and F5 land (§8). Every protocol slice's performance
exit ships two benchmarks, as operation counts in CI and wall-time ratios in
slow runs:

- a one-prefix change costs the same at 10× the table size, within a stated
  factor;
- an idle run admits O(1) changed records (for example a small Spark liveness
  record) and does no SPF, FIB or placement work, whatever the table size.

A faithful Spark increments its sequence number on every hello, so "idle runs
return the same state object" is not the claim. Large tables are always `PMap`s
updated with `set`, never tuples or frozensets, which admission walks in full.

**D7. Timing fidelity through defaults and presets.** Defaults are faithful:
Open/R's `OpenrConfig.thrift`, FRR's `traditional` and `datacenter` profiles,
and the `sonic` preset. The `lab` preset shortens timers but keeps the order of
events. Protocol presets and dialects require `run_delay > 0`, so feedback
between agents on one device can never run away inside one timestamp. Jitter comes from per-module RNG streams
and is deterministic per seed.

**D8. Next hops and sessions follow FRR and zebra.**

- **Single-hop eBGP** (TTL 1, no `disable-connected-check`) registers NHT with
  `connected_only`. Connection attempts wait for that answer
  (`bgp_fsm.c:2704-2717`). The route installs non-recursive: interface plus
  address, taken from the NHT legs.
- **Recursive install.** iBGP, confed, multihop and GTSM eBGP routes install
  recursively: address-only next hops resolved by F1's hierarchical resolver.
  BGP-over-BGP is allowed (`research-frr-decision.md` §3.4, §3.8, §5).
- **Confed peers** default to TTL 1, like eBGP (`peer_ttl_update`,
  `bgpd.c:2532-2552`; in 10.5.4 the same rule is inline in `peer_create`,
  `10.5.4:bgpd.c:2098`, and `peer_as_change`, `10.5.4:bgpd.c:2201-2205`). They get no connected check, install recursively, and use
  distance 200. Loopback confed peering more than one hop away needs
  `ebgp-multihop`.
- **Fast external failover** is on by default. An interface going down stops
  every peer on it with TTL 1 or `ttl-security hops 1` (`bgp_zebra.c:286-299`;
  `10.5.4:bgp_zebra.c:273-286`).
  iBGP and multihop sessions survive the loss of their next hop until the hold
  timer expires, unless `bgp fast-convergence` is set.
- **IGP metric.** The decision process uses the metric of the installed
  resolving route (`NhtResult.via_metric` under `mode='installed'`, F0),
  matching zebra's NHT (G9).

**D9. Keys are ready for add-path and VRFs.** Paths are keyed
`(peer, path_id)` and destinations `(vrf, afi, safi, prefix)` from day one,
with `path_id = 0` and the default VRF until those features land.

**D10. No analytical BGP in this phase.** Import policy, decision and export
stay pure, so a later timeless solver (C-BGP style, bounded iterations with
non-convergence detection) can reuse them for Monte Carlo studies.

**D11. Configuration is tree state; commands are exec-only.**

Users change settings through the layered settings system (section 2A). It
resolves per device and writes the results with the primitive below.

- **In-place configuration.** `Network.configure_agent(device, name, config)`,
  also exposed as `Simulation.configure`, replaces `AgentNode.config` within the
  same generation in one `update()`.
  - It adds `Cause(CAUSE_CONFIG)` and is validated at submission by the
    plugin's pure `validate_config`.
  - Reset and fresh runtimes keep the latest configuration.
  - Plugins read configuration only from `ctx.agent_config`, enforced by an
    invariant test. The reference agent's `self.config.params` read is fixed to
    match.
- **Persistent state.** `AgentNode.persistent` is an immutable record that
  survives reset unless purged. It models Open/R's PersistentStore: drain,
  overload and metric overrides.
- **Commands.** `Command`s are exec-only operations, such as clear, soft
  in/out, route refresh and the Open/R drain APIs (which write `persistent`
  through `AgentOutput.persistent`).
  - Each is validated synchronously by the plugin's pure `validate_command` at
    `Simulation.command`.
  - Errors at run time are reported in a view, never raised, so a bad command
    cannot stall retry.
  - Commands are control-class inbox entries. A command addressed to a
    generation reset before it runs is dropped and counted.
- **Policy edits.** A validated definition is active for new inputs at commit.
  The owner schedules reevaluation of existing routes by
  `policy.reevaluation.mode` and `.delay_s`, the `REEVALUATE` apply action of
  section 5.8. In the FRR dialects the default delay is the 5 s
  `route-map delay-timer` (`bgpd.c:9561`; `bgp_routemap.c:5191-5194`), and
  FRR's delay 0 means manual.

**D12. Restart semantics are explicit.**

- `reset_agent(purge=True)` models a plain daemon restart: zebra removes a
  disconnected client's routes.
- `reset_agent(purge=False)` models retention: Open/R's FibService keeps routes
  until the first `syncFib`, and BGP graceful restart (BG8).
- Open/R persisted drain state survives either reset.
- FRR's default GR helper mode advertises the capability without address
  families (`bgp_open.c:1684-1745`), so FRR-to-FRR sessions flush routes on
  loss. Deferring GR is therefore safe for default configurations, but not for
  SONiC ToR routers, whose template enables GR. That is a recorded divergence
  of the `sonic` preset until BG8 (section 2B.4).

**D13. Routing policy is one shared, typed engine in the model layer.** It
adopts the reviewed routing-policy plan (`NetSim/docs/plans/routing-policy.md`,
revision 4) with the integration corrections of section 5.8:
- FRR `ip protocol route-map` maps to a candidate-next-hop **activation
  filter** in the resolver, evaluated once per original activated next hop
  (§15.4, §16.4), not to submission-time admission and not to `FIB_INSTALL`;
- FRR `ip nht route-map` maps to `RESOLUTION_IMPORT(scope='nht')` with no
  fall-through.

BGP, Open/R and the device hooks all use this one evaluator; BGP keeps only an
access adapter.

**D14. Forwarding installation is an explicit asynchronous contract, F8.**
Desired and installed actions are separate, with generation-guarded completions
at a named boundary. FIB acknowledgement gating and inactive-route export are
first-class, per-node behaviours (section 5.13).

---

## 2A. Settings: per-node overrides, dialects and presets

**Requirement.** Every setting can be overridden per node. Behavioural
differences between FRR releases that are generic and reasonable become
settings with per-dialect defaults; protocol code never checks a version.
Maintainability comes first: the system must stay auditable as FRR moves.

### 2A.1 The schema

Each setting is declared once, in a fragment owned by its consumer package
(`netsim/agents/bgp/settings.py`, `.../openr/settings.py`,
`netsim/model/device_settings.py`). The engine `netsim/settings/` sits in the
model layer and never imports agents. A composition root assembles the
catalog from the fragments by explicit import, with no runtime registration.

```python
Setting(key='bgp.bestpath.med.missing_as_worst', type=bool,
        scopes=(INSTANCE,),                  # where an explicit value may be written
        default=DefaultsSpec(False),         # joint first-match entries on (dialect range, profile)
        since=None,                          # first dialect that has the knob; the resolver rejects it earlier
        unit=None,                           # override unit (e.g. 'bgp.timers' covers keepalive and hold)
        apply=RECALC_BESTPATH,
        refs=('FRR bgp_vty.c `bgp bestpath med missing-as-worst`', 'RFC 4271 §9.1.2.2(c)'),
        doc='Treat a missing MED as the worst value instead of 0.')
```

**Key grammar.** Keys carry object indices:
- `device.fib_delay`;
- `zebra.nht.resolve_via_default`;
- `bgp.timers`;
- `bgp.af[ipv6-unicast].nexthop_prefer_global`;
- `bgp.peer_group[FABRIC].timers`;
- `bgp.neighbor[10.0.0.1].af[ipv4-unicast].allowas_in`;
- `openr[dc1].spark.hello_time_s`.

FRR's global `bgp …` commands map onto instance scope, since each device runs
one instance.

**Defaults.** A `DefaultsSpec` is FRR's `FRR_CFG_DEFAULT` form: an ordered list
of `(dialect range?, profile?, value)` entries, where the first match wins. One
joint list covers entries such as `BGP_IMPORT_CHECK`, which needs "traditional
and version < 7.4". Gates below 10.5 are dropped, because no NetSim dialect
predates it.

**Availability.** `since` and `allowed_values_by_dialect` record when a knob or
value exists. The generic resolver rejects out-of-range writes, so protocol code
never sees a dialect.

**Override units.** A unit such as `timers` (keepalive and hold) or
maximum-prefix (limit, threshold, restart) is written whole. A partial write is
a validation error, as in FRR's CLI. Structured and list values (Open/R regex
lists such as `static_interface_metrics`, route-map terms, flavor specs) are
replaced, never merged.

**Apply actions** follow modern FRR in every dialect:

| Action | Meaning |
|---|---|
| `LIVE` | Takes effect on next use |
| `NEXT_SESSION` | Takes effect at the next session (values negotiated at OPEN) |
| `RECALC_BESTPATH` | Re-runs best-path selection (`bgp_recalculate_all_bestpaths`) |
| `SOFT_IN` | Re-applies inbound policy |
| `SOFT_OUT` | Re-runs outbound policy under duplicate suppression; a forced re-send happens only on `clear soft out` or ROUTE-REFRESH (AP-36) |
| `REEVALUATE` | Policy edits: the definition is active for new inputs at commit; the owner schedules reevaluation of existing routes by `policy.reevaluation.mode` and `.delay_s` (section 5.8). Replaces the former fixed 5 s `DELAYED` |
| `SESSION_RESET` | Resets the session. Keys that change the peer sort (remote-as, local-as, confederation peers) also re-derive the TTL (AP-19) |
| `CAPABILITY_ELSE_RESET` | Signals a CAPABILITY message when dynamic capability was negotiated, otherwise resets (BG2 models this) |
| `RESTART_INSTANCE` | Restarts the protocol instance |
| `DEPLOY_ONLY` | Read only when an object is created, as FRR's `peer_new` snapshot of `bgp default dynamic-capability` does (`bgpd.c:1836`) |

**Upstream constants** that are not user settings (for example Open/R's
hard-coded throttles) live in a per-package `constants.py`, each with refs.

### 2A.2 Dialects and presets

**Dialects** are immutable pins that supply defaults and availability:
- `frr-master-f1d7bec`, with the alias `frr-modern`;
- `frr-10.5.4`, with the alias `frr-10.5`;
- `native`: today's NetSim defaults. It applies to devices with no FRR agent and
  keeps current fingerprints unchanged. For example, NetSim's
  `ResolutionPolicy.resolve_via_default` is False while FRR traditional defaults
  zebra's to True.

An alias is resolved to its pin when a layer is stored, so a stored scenario
keeps its behaviour when the alias moves, as FRR's `frr version` line does.
There is no `frr-10.7` dialect: every master-only delta is a fix or out of
scope, so its column would equal `frr-modern`.

**Profiles** are FRR's `frr defaults`: `traditional` or `datacenter`.

**Presets** are ordered named bundles of meta-keys and values:
- `sonic` (section 2B.4);
- `lab`, with short timers that keep event order, which gives D7 a home.

**Meta-keys.** `device.dialect`, `device.profile` and `device.presets` are
device-scoped and resolved first, through the user layers only.
- A device has a single dialect, shared by its zebra and BGP.
- Changing the dialect is `RESTART_INSTANCE` (a software upgrade).

### 2A.3 Layers and precedence

Layers are immutable records in the tree (`NetworkState.settings`), so forks,
studies and resets carry them. From lowest to highest:

1. the network layer;
2. group layers, each with a selector (a device-name regex and/or labels from
   `DeviceState.labels`, a new F0 field that adapters fill from NetGraph
   attributes and roles) and a priority;
3. the device layer.

**Resolution per device:**

1. Resolve the meta-keys (dialect, profile, presets) from the layers.
2. For each (object, key), the explicit value comes from the highest layer that
   writes that exact (object, key). Layer order only ranks writers of the same
   (object, key).
3. FRR inheritance runs over objects, not layers: instance → AF → peer-group →
   neighbor → neighbor-AF (section 2B.5). A value set on
   `peer_group[FABRIC].timers` by a group layer therefore wins over an
   instance-level `timers` from the device layer for FABRIC members, as FRR
   templates behave.
4. Absent explicit values fall back to presets, then the `DefaultsSpec` for the
   device's dialect and profile.

**Validation.**
- A layer that targets an object absent from a device is a validation error.
- Two equal-priority layers that write the same (object, key) on the same device
  are rejected by the `update()` that creates the conflict: adding the layer,
  adding the device, or changing its labels.

### 2A.4 One write path; resolution output

**The resolver is the only writer of:**
- `AgentNode.config`, meaning the whole `AgentConfig`: the runtime fields
  (`run_delay`, `processing_delay`, inbox, queue and byte limits,
  `listen_ports`) as well as `params`;
- the settings fields of `DeviceConfig`.

`enabled`, `enabled_since` and `seed` are not settings; operations and failure
sources own them (`failures.py:207`). `Network.configure_agent` is internal to
the resolver. `add_agent(device, BgpAgent(BgpConfig(...)))` is sugar that writes
a device layer and object layers. A `debug_validate` invariant checks that
re-resolving the layers reproduces the stored configurations.

**Output** is typed frozen records per consumer module (`BgpTimers`,
`DecisionSettings`, `NeighborSettings`, `SparkSettings`):
- when a new record equals the device's previous one, the previous object is
  reused;
- hashable leaf records are interned in a dict local to one resolution call (no
  module-level table, per the free-threading rule; `PMap` is unhashable,
  `state.py:222`);
- validation uses `validate_admitted(new, old)` (`state.py:735`).

**Provenance** is computed on demand, by re-resolving one device with tracing:
`net.settings.explain('leaf7', 'bgp.neighbor[10.0.0.1].timers')` returns the
value and its chain of layers. No side map is stored.

**Change.** A layer change re-resolves the affected devices in the same
`update()`. It delivers `CAUSE_CONFIG` with the changed keys (F2a), and the
timeline records the settings diff (F1 owns `timeline.py`). The agent receives
one per-owner action plan compiled from the effective-record diff (§15.5), not
a set of per-key actions.

### 2A.5 Rules enforced by tests

1. Resolved-record classes declare no field defaults (AST check). Upstream
   constants live only in `constants.py` files with refs.
2. Resolved records carry no dialect, so protocol code cannot branch on one; the
   rule holds by construction.
3. Every setting has scopes, a type or validator, a unit if it belongs to one,
   an apply action, refs and a doc string.
4. Setting keys and resolved-record fields are in a declared bijection (checked).
5. A new setting needs evidence that it changes behaviour, and a test marked
   `@covers('key')` that exercises its values. A meta-test fails for uncovered
   keys. Spec-valued keys are exempt from value enumeration.
6. `docs/settings.md` and the dialect table are generated from the catalog.
   CI fails if they are stale.
7. The FRR lane checks whole-dialect behaviour.
   - Golden source for `frr-modern`: `quay.io/frrouting/frr:master` pinned by
     digest and mirrored.
   - `:10.7.1` is informative, with a known-difference list (AP-01, AP-19,
     AP-23, AP-36).
   - `:10.5.4` covers `frr-10.5`.
   - Avoid 10.5.0–10.5.3 and 10.6.0, which carry the IPv6 neighbour-address
     tie-break bug (D6).
8. Adding a dialect means a new pin with data rows justified by the
   per-subsystem diff review used for 10.5 → modern
   (`netsim-protocols-research/frr-diff-*.md`).

### 2A.6 Adapters write layers

| Source | Becomes |
|---|---|
| NetGraph `attrs.netsim` | Labels plus device layers. The existing keys `fib_delay` and `fast_failover` (`netsim/adapters/ngraph.py:181-183`) move into `device.*`, and the old spellings stay accepted. Risk-group mtbf/mttr are study parameters, not settings |
| SONiC CONFIG_DB | The `sonic` preset, plus role-conditional device and object layers written by the adapter: confederation on disaggregated T2, FrontEnd `redistribute connected` route-maps, GR on ToR, GR disabled with LLGR on UpperRegionalHub |
| `frr.conf` | Device and object layers. `frr version` selects the dialect pin, and versions below 10.5 are rejected. `frr defaults` selects the profile. Dumping writes every explicit value and its inheritance or unset intent (an explicit value equal to a default is still written), so the adapter round-trips and a later default change cannot alter a pinned value |

Scenario files with migrations are deferred until a stored format exists.

### 2A.7 What is not a setting, and what is only linted

- **Not settings:**
  - oracle IGP domains (`Network.sources`, off-tree route sources);
  - Simulation and transport globals (`max_rounds_per_timestamp`, retention);
  - failure parameters (studies);
  - Open/R drain and overload, which are `AgentNode.persistent`, changed by
    commands;
  - device `enabled`, `enabled_since` and `seed`.
- **Client profiles are per node** (routing-policy plan P0;
  `RFCs/PER-NODE-SETTINGS-PLAN.md`). Today `Network.profiles` is keyed only by
  `ClientId`, and `add_agent` rejects the same client with a different distance
  on another node (probe reproduced by the policy research). Identity stays
  shared, for attribution, policy matching and metrics. The behavioural
  defaults become node settings: `rib.client[<name>/<instance>].distance`,
  `.protocol_origin` and `.link_state`. The network registry keeps identity
  plus default templates only. Explicit per-row distances still win.
- **Routing policy is settings too.**
  - Definitions and named sets are immutable, revisioned values
    (`policy.definition[<name>]`, `policy.set[<name>]`), pinned by content
    digest.
  - Bindings are keys per attachment point, for example
    `bgp.neighbor[10.0.0.1].af[ipv4-unicast].policy.import`,
    `rib.admission[<client>]` and `resolution.nht[<client>]`.
  - Each resolves to exactly one `RoutePolicyBinding`. Its value is replaced
    whole, never merged.
  - `policy.reevaluation.mode`, `policy.reevaluation.delay_s` and
    `bgp.policy.on_replay_unavailable` are per node.
- **Consistency lints (warnings, not constraints):**
  - Open/R ports per domain;
  - confederation identifier and peer lists across members;
  - RR cluster ids;
  - dialect mixing across peers, which is allowed and realistic.
- **Mapped settings.**
  - `zebra.nht.resolve_via_default` drives both NHT registrations and
    `ResolutionPolicy`.
  - `zebra.multipath_num` caps FIB groups, replacing the fixed
    `max_ecmp_paths=64`, which truncated FRR's packaged 256 and SONiC's 514.
    Values: `native` 64, `frr-modern` 256, `frr-10.5` 514 for SONiC.

### 2A.8 Failure modes of settings systems, and the countermeasures

| Failure mode | Countermeasure |
|---|---|
| Setting sprawl: knobs nobody tests | Rule 5 (evidence plus `@covers`); rule 4 (bijection); combinations are covered by dialect scenarios, not pairwise |
| Precedence surprises | Per-(object, key) writer ranking, FRR object inheritance, conflicts rejected at `update()`, `explain()` provenance, settings diffs in the timeline |
| Defaults drift from the reference | Defaults exist only in `DefaultsSpec` entries with refs into pinned trees. A dialect is a new pin plus diff rows, and the documentation is generated |
| Version checks spread through code | Resolved records carry no dialect (rule 2) |
| A second write path reverts or bypasses settings | The resolver is the only writer, and `debug_validate` checks re-resolution |
| Per-node configuration costs memory and validation at 10k devices | Record reuse when equal, per-call interning, `validate_admitted`, re-resolution of affected devices only |
| Run-time change semantics re-implemented ad hoc | Apply actions declared per key, one test per apply class, modern FRR semantics in every dialect |
| Inheritance differs from FRR | Section 2B.5 rules, tested through the `frr.conf` adapter and the lane |
| Hidden global state and free-threading contention | Immutable fragments, a composition-root catalog, per-call interning, frozen outputs |

### 2A.9 Where it lives and who builds it

- **F0** adds:
  - the `NetworkState.settings` stub, `DeviceState.labels`, and the
    `Network.settings` API skeleton;
  - the `Command`, `CAUSE_CONFIG` and `persistent` records.
- **F7** builds:
  - the engine (`netsim/settings/`: schema, layers, resolution, inheritance,
    provenance, documentation generators);
  - the composition root;
  - the `native` dialect with the `device.*` and `zebra.*` fragments;
  - NetGraph label translation.

  Existing behaviour moves onto it first, with fingerprints unchanged.
- **F2a** delivers `CAUSE_CONFIG` with changed keys; **F1** adds timeline
  settings events.
- **BG1 and OR1** own their fragments, units, polarity and Open/R regex scopes.
- **BG7** writes the SONiC and `frr.conf` layers. Each later slice adds the keys
  it implements (the §2B.3 rows name their slices).

---

## 2B. FRR versions: 10.5 versus modern, and what becomes a setting

Source: three per-subsystem diffs of frr-10.5.4 against master `f1d7bec`. Each
difference is attributed to its release through the full history
(`~/ws/frr-git`) and checked by function-level code comparison, not by commit
hashes:
- `netsim-protocols-research/frr-diff-decision-nht.md`;
- `netsim-protocols-research/frr-diff-advertise-policy.md`;
- `netsim-protocols-research/frr-diff-sessions-defaults.md`.

About 1,330 bgpd, 550 zebra and 390 lib commits separate the two trees.

### 2B.1 Findings

- **The core is unchanged from 10.5.4 to master.** The following all match:
  - best-path steps 1–15, and sorted-list insertion (in FRR since 10.1);
  - the 50 ms bgpd and 10 ms zebra queue holds;
  - install flags, distances, zebra recursion, the connected check, fast
    external failover;
  - the RR matrix and attribute writing, next-hop rules, confed checks,
    RFC 8212, communities;
  - coalesce, MRAI defaults, collision, timers and the route-map delay.
- **About 60 differences are fixes, where 10.5 is simply wrong.** Examples:
  - a martian NEXT_HOP resets the session instead of treat-as-withdraw
    (RFC 7606);
  - a GR-stale path with a dead next hop stays best;
  - LLGR-stale routes leak;
  - link bandwidth is clamped at 34 Gbps;
  - `maximum-paths 1` reinstalls on every run;
  - TTL and local-as edge cases;
  - duplicate UPDATEs after policy changes;
  - BFD strict mode delays teardown by 30 s.
- **A few are genuine behaviour choices** (section 2B.3).
- **Master-only semantic changes:**
  - withdrawals before announcements in one UPDATE (a fix);
  - TTL re-derivation on every sort change (a fix);
  - non-transitive extended communities stripped toward eBGP (a fix);
  - no forced re-send after a policy edit (a fix);
  - UPA, out of scope. Its receive-side marking is unconditional in master, so
    `frr-modern` diverges on UPA-marked paths (recorded);
  - the rs-client OTC check, out of scope until RFC 9234 roles;
  - the zebra tie-break inversion (Z5), whose code contradicts its commit
    message.
- **Corrections.**
  - `bgp deterministic-med` stopped affecting best path in 10.4.0 (83ad94694,
    #18210; also 10.2.2 and 10.3.1).
  - "Withdrawn first" is master-only; "MRAI gates withdrawals" holds from
    10.6.0.
- **Conflicts between the reports, resolved:**
  - N1 (a fix) over S24 (proposed as a setting): the GR-stale deletion is
    followed;
  - the suppress-fib-pending delay range is 0–10000 ms (`bgp_vty.c:2122`), not
    0–1000;
  - AP-20 over S18: a member's remote-as override is accepted, and the
    `frr-10.5` adapter warns.

### 2B.2 Target, quarantine and quirks (revises D1)

- **`frr-modern`** is master `f1d7bec`.
  - Only Z5 is quarantined: the zebra tie-break defers to NetSim's F1a rule
    until a black-box run on the pinned master image decides.
  - All other master deltas are fixes and are followed.
  - The pin moves at 10.8.0 by repeating the diff review.
- **`frr-10.5`** reproduces SONiC's release defaults and generic behaviour
  choices, never its bugs. The 10.5 bugs are documented divergences. When a
  10.5.4 lane run disagrees on one of them, triage cites the divergence list.
- **Quirks.** A `quirk.*` flag is allowed only when all of these hold:
  - it materially changes converged state or timing;
  - it ships in a release users run;
  - a test pins it.

  Quirks default to off everywhere; a preset may enable one with a stated
  reason. There are currently no candidates:
  - N6 (`bandwidth ignore` falls through to link-bandwidth weighting, since
    10.6.0) contradicts FRR's documented plain ECMP, so a quirk for it would
    be off in all dialects. It is revisited with UCMP in BG8;
  - the 10.5.4 link-bandwidth clamp fails the rule, because SONiC's template
    configures no link bandwidth.

### 2B.3 Behaviour choices that become settings

Only true choices carry per-dialect defaults. Knobs that exist only in newer
releases are expressed through `since`, not as dialect columns.

| Key | Values | `frr-10.5` | `frr-modern` | Scopes | Apply | Slice | Rows |
|---|---|---|---|---|---|---|---|
| `bgp.bestpath.redist_admin_distance` | bool | False | True | instance (NetSim knob; FRR has none) | RECALC_BESTPATH | BG3 | D1 |
| `bgp.out.mrai_withdrawals` | `bypass`, `gated` | `bypass` (writes at once unless the peer's MRAI timer is already running, `10.5.4:bgp_packet.c:448`) | `gated` (RFC 4271 §9.2.1.1) | instance (so it stays out of the update-group key) | LIVE | BG4 | AP-35, S03 |
| `bgp.bestpath.deterministic_med` | bool | profile (dc True, trad False) | profile | instance | RECALC_BESTPATH | BG3 | D3 |
| `bgp.bestpath.dmed_semantics` | `frr-current`, `classic` | `frr-current` | `frr-current` | instance | RECALC_BESTPATH | BG3 | D3. `classic` means pre-10.1 FRR: grouping, and only group winners compete, when `deterministic_med` is True |
| `bgp.gr.select_defer_time_s` | seconds | 240 | 120 | instance | LIVE | BG8 | P4, S01 |

Knobs with `since=frr-modern`, following the FRR scope and default:

| Key | Default | Scope | Slice |
|---|---|---|---|
| `bgp.af[ipv6].nexthop_prefer_global` | False | AF | BG3 |
| `bgp.neighbor[*].af[*].allowas_in.route_map` | None | peer-group, neighbor-AF | BG4 |
| `bgp.advertisement_delay_s` | None | instance | BG4 |
| `bgp.suppress_fib_pending.adv_delay_ms` | 1000; range 0–10000, fixed at 1000 in 10.5 | instance | BG4 |
| `bgp.use_underlay_nexthop_weight` | False | instance | BG8 |

Knobs with the same default in both dialects:

| Key | Default | Scope | Slice |
|---|---|---|---|
| `bgp.suppress_fib_pending` | off; on in `sonic`; maps to the `frr-suppress-fib-pending` gate profile of section 5.13 | instance | BG4 (after F8) |
| `bgp.export.inactive` | True in FRR dialects (inactive best paths are advertised unless suppress-fib-pending), False in `native` | instance | BG4 |
| `bgp.suppress_duplicates` | True, modern semantics (AP-33) | instance | BG4 |
| `bgp.ucmp.link_bandwidth_mode` | `default` | instance | BG8 |
| `bgp.default.dynamic_capability` | profile (dc True, trad False); DEPLOY_ONLY | instance | BG2 (with CAPABILITY messages) |

`zebra.rib_tiebreak` (Z5) is not a key. F1a records NetSim's tie rule for equal
distance and metric (today: `ClientId` order, `routing.py:225`). An FRR arrival
order ("oldest" or "newest") would need a per-row sequence in the RIB, so it is
added only if the black-box run shows the difference matters.

**suppress-fib-pending changes converged state, not only timing.** When a
selected path is not FIB-installed (`FAIL_INSTALL`, `BETTER_ADMIN_WON`), bgpd
withdraws it from peers (`bgp_check_withdrawal`; `bgp_route.h:771-806`;
`bgp_zebra.c:3128-3160`; identical in 10.5.4). Example: a redistributed /31
that loses to the connected route is never re-advertised. A selected `network`
static is exempt unless another non-selected non-NORMAL path exists at that destination (`bgp_route.h:779-801`). It uses the F0 owner notifications.

### 2B.4 Profile defaults and the `sonic` preset

| Key | datacenter | traditional |
|---|---|---|
| keepalive / hold | 3 / 9 s | 60 / 180 s |
| connect retry | 10 s | 30 s |
| `ebgp-requires-policy` (RFC 8212) | False | True |
| `deterministic-med` | True | False |
| `suppress-duplicates` | True | True |
| `graceful-restart notification` (RFC 8538) | True | True |
| `hard-administrative-reset` | True | True |
| `enforce-first-as` | True | True |
| `network import-check` | True | True |
| dynamic capability | True | False |
| link-local capability; RR allow-outbound-policy; `bestpath aigp`; IPv6 `nexthop prefer-global` | False | False |
| zebra `ip nht resolve-via-default` (per VRF) | False | True |

Values are unchanged 10.5.4 → master (`FRR_CFG_DEFAULT_*`).

**`sonic` preset**, verified against SONiC master:
- **Profile: traditional.** The generated `frr.conf` has no `frr defaults`
  line, the daemons start without `-F` (`supervisord.conf.common.j2`), and
  FRR's packaging does not enable datacenter.
- **Dialect:** `frr-10.5` (FRR 10.5.4, `rules/frr.mk`).
- **Values** (`bgpd.main.conf.j2`, saved in the research folder):
  - `bgp suppress-fib-pending`;
  - `no bgp ebgp-requires-policy`;
  - `no bgp default ipv4-unicast`;
  - `maximum-paths 64` (IPv4 and IPv6) when `constants.bgp.maximum_paths` is
    enabled, capped by `MULTIPATH_NUM` 514;
  - `bgp bestpath as-path multipath-relax` when enabled.
- **ASIC-offload notification.** zebra runs with
  `--asic-offload=notify_on_offload`, so INSTALLED follows ASIC programming.
  `device.fib_delay` models that delay under suppress-fib-pending.
- **Role-conditional lines** are written by the SONiC adapter as device layers:
  - GR on ToR routers when enabled (restart-time 240 s, select-defer 45 s,
    preserve-fw-state);
  - `coalesce-time 10000` on dual-ToR;
  - UpperRegionalHub `graceful-restart-disable` with LLGR stale-time 864000;
  - confederation on disaggregated T2;
  - FrontEnd `redistribute connected` route-maps.
- **Recorded divergence until BG8.** GR is not modelled, so where SONiC enables
  GR (ToR), T1 helpers retaining ToR routes is not reproduced.

### 2B.5 Mirroring FRR's inheritance machinery

From `frr-diff-sessions-defaults.md` §5–§6:

| FRR | NetSim rule |
|---|---|
| Override bits (`flags_override`, `af_flags_override`, `filter_override`) with invert polarity for default-on flags | Each object stores only its explicit values; polarity is a property of the key |
| `no` on a member restores the inherited value (`peer_flag_inherit`, `bgpd.c:1153-1170`); group edits skip overriding members | Removing a layer's explicit value restores inheritance; group values never override explicit member values |
| The override unit is the flag group (`timers` covers keepalive and hold; maximum-prefix covers limit, threshold, restart) | Units are written whole (2A.1) |
| Role, GR mode and BFD are copied group → member without override tracking (last writer wins) | An explicit member value always wins (recorded deviation) |
| One group per neighbor; a member remote-as override is allowed since 10.7.0 | One group per neighbor; the override is accepted in every dialect, and the `frr-10.5` adapter warns |
| Instance defaults applied at creation; capability flags copied into peers at creation | `DEPLOY_ONLY` apply action for those keys |
| `peergroup_flag_check` reads the member's override bit rather than its effective flag (link-local capability, strict BFD) | Use the effective value (recorded FRR quirk) |
| `DFLT_*` resolved against the configuration's `frr version`, `SAVE_*` against the running version | Dialect pins resolved at storage; dumps write explicit values and inheritance intent, never only differences from defaults |

---

## 3. Foundation

### F0. Contract additions (integrator; records, defaults, stubs)

All additions go in `netsim/model/contracts.py` (and `network.py` for
`configure_agent`). Each has a default, so existing agents are unaffected.

- **Configuration, persistence, commands.** As D11:
  - `Network.configure_agent`;
  - `CAUSE_CONFIG`;
  - `AgentNode.persistent` and `AgentOutput.persistent`;
  - `Command(time, name, payload, generation)`;
  - `Simulation.command`;
  - plugin hooks `validate_config` and `validate_command`.
- **Views.** `AgentOutput.views: PMap[str, immutable]` is stored in `AgentNode`
  and compared by identity.
  - `ctx.view(agent, name)` reads another agent's view on the same device.
  - Subscriptions may target `('agents', name, 'views', key)`.
  - The timeline records view changes; tests, `Timeline.series` and study
    stability predicates read views only.
  - Open/R and BGP publish bounded show-records: neighbours, adjacencies,
    sessions, best path and reason per prefix, command results.
- **RIB feed** (zebra `REDISTRIBUTE_*` analogue). The op is
  `WatchOp(af, sources, kind)`.
  - Watches are stored in `DeviceState` as (owner, af, sources, kind).
  - `sources` is a set of `ClientId`s or `ALL`. `ALL` excludes the owner's own
    client, and naming it is rejected, because zebra has no redistribute-self.
  - `kind='selected'` covers rows the resolver installed. The FIB kind emits
    `RouteChange(watch, af, epoch, upserts, removals)` when it commits
    processed epoch `e`. The changed set is the prefixes whose FIB entry
    changed, plus installed prefixes whose contributing rows changed content
    (from `rib_apply`'s changed set), so metric-only and tag-only changes reach
    the feed:
    - upserts are the `Route` objects of `FibEntry.contributing` from the RIB
      that run consumed, filtered to the watched sources;
    - removals are keys that left the set;
    - nothing is emitted while PENDING.

    This matches zebra, which redistributes after dataplane success. Rows carry
    `tag`, `metric` and `distance`, so injection policies can match and set tags
    against two-border redistribution loops.
  - `kind='all'` covers every row of the watched sources whatever its
    selection. It emits at the RIB commit of those rows (input epoch),
    independent of FIB processing. It serves Open/R-style injection, which
    upstream receives through thrift `advertisePrefixes` whatever the RIB
    selected.
  - A snapshot is delivered on registration and on every generation change.
  - `RouteChange` is a control-class entry. At most one uncaptured entry exists
    per watch, coalesced latest-state-wins and never merged into a captured or
    parked prefix.
  - Rows taken from the tree skip re-validation.
- **Owner notifications.** `ctx.route_notifications` holds
  `RowNotice(key, status, reason, zapi)` for changed own rows.
  - It carries NetSim's native status and reason (`INSTALLED` or
    `NOT_INSTALLED`, with `SHADOWED`, `UNRESOLVED`, `AMBIGUOUS_ACTION` or
    `LOOP_DETECTED`), plus
    the derived ZAPI code: `INSTALLED`, `FAIL_INSTALL`, `BETTER_ADMIN_WON` or
    `REMOVED`.
  - Metric-only row changes count as changes.
- **NHT.**
  - `NhtKey.mode ∈ {'rib', 'installed'}`. `installed` answers from the last
    processed FIB (zebra NHT accepts only installed next hops), and F1's
    recursive-next-hop table backs it.
  - `NhtResult.via_metric` is the metric of the selected resolving row at the
    first level (zebra `nhr->metric`), next to the strict `cost`.
  - Notifications fire only on answer fields: `eligible`, `via_prefix`,
    `via_source`, `via_metric`, `cost`, `legs`. They no longer fire on
    `queries` or `interfaces`, which are dependencies.
  - An exact-prefix mode serves BGP `network` import-check (zebra IMPORT_CHECK):
    the prefix must be present exactly and resolved by a row that is not from a
    BGP client (`bgp_nht.c:699-714`, `nhr->type == ZEBRA_ROUTE_BGP`).
- **Change-key semantics.** `ctx.nht_changes` and `ctx.route_notifications` list
  the keys captured by this receipt.
  - That means the union since the generation's previous published run, kept
    on rejection. A key may have changed back since.
  - Values are read from the snapshot.
  - `on_init` receives empty lists and reconciles from `ctx.nht` and
    `ctx.rows_of(own client)`.
- **Route views.** `RouteView` is split into `rib_selected` (first resolvable
  group at the input epoch; zebra `ZEBRA_FLAG_SELECTED`) and `installed`
  (processed epoch, `None` while PENDING). This replaces today's field, which
  reads the installed FIB entry even while the row is PENDING
  (`agents.py:521-525`).
- **Transport.**
  - Wildcard listeners use `Endpoint(address=None)` for a family, scoped to an
    interface set so that two instances never collide.
  - Each listener carries an immutable accept table keyed by remote address (a
    prefix for BG8 listen ranges) → `(ttl, min_ttl)`. A remote not in the table
    is REFUSED, as FRR's `bgp_accept` closes unconfigured peers.
  - `SessionOp.ttl` and `SessionOp.min_ttl` apply to the open.
    `SessionOp('set_opts', connection, ttl, min_ttl)` changes them later.
  - `ConnectionView.local` always reports the concrete local endpoint.
- **Lazy accessors, all O(1) over immutable records.** They are built from the
  detached `LocalContext` (`nht.py:57-122`), never from `DeviceState`, which
  holds other agents' state, and they keep no mutable cache (the context must
  pass `validate_immutable`, `tests/runtime/test_agents.py:213-259`).
  - `ctx.rows_of(af, client)` returns the existing
    `RibState.clients[client]` map.
  - `ctx.route(af, prefix)` reads through `prefixes`.
  - `ctx.row_status(af, key)` reads the outcome.
  - `ctx.rib_view(af)` keeps its meaning and is computed on demand.
- **Records F1 and F2 share.**
  - `ResolverOutcome.rows` becomes `PMap[ClientId, PMap[RowKey, RowOutcome]]`.
  - NHT registrations are held in per-owner maps.
  - `RecursiveNexthop` and group records.
  - `FibGroupEvent` for the timeline.

  With per-client maps, G4 and G5 become identity checks per client, and
  `RowNotice` becomes a `diff_pmap` of the client's sub-map, so F2 does not wait
  for F1's incremental resolver.

- **Routing policy, installation and client-profile records** (contracts only;
  owners in section 8):
  - `RoutePolicyBinding` storage in settings;
  - the `RouteSubmission` helper signature;
  - the F8 records (`ProgrammingRequest`, `ProgrammingResult`, desired and
    installed action, `POLICY_EXCLUDED`);
  - node-local client-profile settings;
  - a regression test that fails today: the same client with distance 20 on
    node A and 200 on node B.

Exit: contract tests for every new record and rule; existing agents and tests
unchanged; the locality rules extend to every new accessor.

### F1. Resolver: deterministic semantics, persistent FIB, then incremental

Files: `netsim/model/routing.py`, `netsim/model/forwarding.py`,
`netsim/model/lpm.py`, `netsim/model/derive.py` (FIB kind, `bump_epochs`, NHT
refresh calls), `netsim/runtime/timeline.py`. It is split in three, with a
design-review gate before F1c.

**F1a. Order-independent resolver semantics** (fixes G12, a defect today).

- *Fingerprints first.* Extend the fingerprint oracle before touching anything
  (`tests/test_fingerprints.py:55-67` covers only prefix, action, interface,
  next hop and weight on oracle-IGP topologies).
  - New fields: outcomes (status, reason), MAC, encap, adjacency AF, NHT
    answers, selection and PENDING.
  - New scenarios: recursive, cyclic, cross-family (RFC 8950), `lpm_fallthrough`,
    `resolve_via_default` and SR.
  - Record baselines and list F1a's intended diffs explicitly.
- *Rules.* Each prefix's answer becomes a function of the RIB only:
  - depth is the length of the next-hop chain (kept per recursive entry), not
    stack height;
  - a depth-truncated result is never memoized;
  - a prefix excludes only itself from its own resolution;
  - recursion is decided per leg: a leg resolves when it has a finite witness
    within the depth bound; a leg whose resolution closes a cycle with no
    escape fails with `LOOP_DETECTED`; the route's other legs are unaffected
    and weights are normalized over the survivors (§15.4).

  Each rule is pinned by a test that fails on the old code. The reproducers are
  `netsim-protocols-research/scale-review/order_dep.py` and `order_dep2.py`.
- *Free fix.* `DeviceContext.rib` uses truthiness (`derive.py:728-729`), which
  calls `RibState.__len__` twice per prefix, about 7% of resolver time. It
  becomes `is None`.

**F1b. Persistent FIB storage and a non-transitive FIB** (fixes G13, G14).

- *Two-level next-hop groups*, as zebra and hierarchical FIBs use.
  - A per-(device, next-hop family) table of recursive entries,
    `RecursiveNexthop(af, address, interface, interface_generation,
    connected_only, resolve_via_default)`: the physical resolution key carries
    every resolution-changing scope, including the interface identity and
    generation for link-local addresses (§15.4). Each entry holds the resolved
    legs with a depth **per leg**, the resolving prefix and source,
    `via_metric`, and the transitive dependencies, failed lookups included.
    Owner and client projections (policy binding, query mode) are keyed
    separately and applied per row, never to a shared group.
  - A `FibEntry.depends_on` holds only its own prefix plus references to
    recursive-entry ids; the transitive dependencies live on the recursive
    entries. The 23 tests that read `depends_on` are updated.
- *Group key:*
  - the route AF;
  - the unresolved next-hop set with weights;
  - the route's own prefix, only when it covers one of its recursive next-hop
    addresses (so 10/8 via 10.1.1.1 and 20/24 via 10.1.1.1 do not share a group
    while resolving differently).

  Group ids are stable and reference-counted with garbage collection, so churn
  does not leak groups. Group content is the flattened legs, truncated to
  `max_ecmp_paths` and normalized exactly as `_group_from_legs`
  (`routing.py:819`) does now. Forwarding, placement and fingerprints stay
  one-level.
- *Storage and diffs.*
  - FIB entries move to persistent per-length `PMap` tables, as the RIB uses.
    The lookup slowdown (117 vs 64 ns on the design record's numbers) is
    measured against placement and trace.
  - The unchanged-FIB check and the timeline diff use shard identity and
    `diff_pmap`.
- *Timeline contract.* An underlay change alters only group content, so the
  timeline gains `FibGroupEvent(device, af, group, nexthops)` and keeps a
  per-prefix `FibEvent` only when the entry itself changes. This is a
  documented change to `tests/runtime/test_timeline.py:141-143`. Expanding to
  per-prefix events would be O(dependents): 50k events cost at least 150 ms.
- *NHT refresh* is selected through the prefix watch index, using each
  registration's recorded queries, instead of refreshing every registration.
- *One RIB submission boundary.* Every production writer calls a single
  model-owned `submit_rows(...)` that wraps `rib_apply`:
  - `derive.py` connected, local and SR-local;
  - `igp.py` sources;
  - `entities.py` `RibClient`;
  - `network.py` batch reconciliation;
  - `runtime/agents.py` `RouteOp`s.

  `rib_apply` stays the pure table primitive. The boundary emits the
  changed-row sets F1c, F2b and RP3 need, and an audit test fails on any new
  direct `rib_apply` call from production code.
- *Prefix watch index* (zebra `rnh` longest-match watchers). It keeps sorted
  watched addresses per family and answers "which watched addresses fall inside
  a newly inserted prefix" by bisect. A per-length scan would cost O(watchers)
  per insertion, about 5M checks in a 50k-prefix load with 100 watchers.

**F1c. Incremental resolution with the full resolver as oracle.**

- *Dirty sets.*
  - `rib_apply` reports changed prefixes.
  - Interface and neighbour changes reach direct legs through an index.
  - The watch index invalidates recursive entries.
  - A recursive entry that flips between resolved and unresolved (including
    partial resolution under `all_or_nothing`) re-queues every dependent prefix,
    because the prefix falls through to the next row group.
  - Dirty sets are processed in sorted order, since `str`-hashed sets are
    randomized per process.
  - A measured fallback runs a full rebuild when the closure is large.
- *SR entries* stay on the full path first and migrate last.
- *Oracle.* The full resolver runs on every commit in F1 tests and in seeded
  random RIB sequences, and is sampled at quiescence elsewhere. Running it
  everywhere would roughly double FIB time across the suite.

**Exit.**

- F1a: fingerprint baselines and the intended diffs; new rule tests fail on the
  old code.
- F1b and F1c: the resolver acceptance matrix of the design of record.
- Operation-count assertions in CI: `resolve_prefix` calls, entries touched,
  NHT refreshes.
- Wall-time ratio benchmarks, slow and deselected, on both harnesses:
  - `net.converge()`: with 50k recursive rows, the FIB step for an IGP change
    goes from 1.80 s to ≤ 5 ms with O(1) entries touched, and a one-row add
    from 1.71 s to ≤ 1 ms.
  - Simulation: the FIB, timeline and NHT-refresh share of the one-row agent
    run at 10k rows is ≤ 3 ms. The whole run at ≤ 5 ms (from 411 ms) is a joint
    F1c + F2c exit.
- Existing converge benchmarks not more than 5% slower.
- The end-to-end BGP cost of a next-hop metric change stays O(paths on that next
  hop): about 0.5 s at 50k paths. It is published in passport (b), not claimed
  as a FIB target.

### F2. Agent runtime at scale

Three sub-slices, so functional protocol work is not blocked on scale work:

- **F2a**: configuration, persistence, commands, views and change keys. It
  follows F0 and runs in parallel with F3–F5.
- **F2b**: the RIB feed, owner notifications and the NHT `installed` mode with
  `via_metric`. It needs F1b.
- **F2c**: the scale work for G2–G5 and admission.

Files: `netsim/runtime/agents.py`, `validate_admitted` and the `PMap` builder
in `netsim/model/state.py`, NHT delivery in `netsim/model/nht.py`, and F0
delivery.

- **Lazy context** as F0 defines it. Interface views are cached in the runtime,
  holding strong references to nodes, and never keyed by `id()`.
- **Per-client identity notifications** (G4, G5). F0's per-client outcome map
  and per-owner NHT maps turn the scans into O(1) identity checks per client,
  and `RowNotice` into a `diff_pmap` of the client's sub-map. Row content is
  tracked, so a metric-only change counts.
- **Shard-identity admission** (G3). Published shard dicts are never mutated:
  `set` and `remove` copy, the builder copies on first write and forgets its
  shards on `build` (`state.py:371-429`), and `_wrap` owns only fresh dicts,
  with its callers confined to `state.py`, `lpm.py` and `rib_apply`. The rule:
  - pair new with previous only when `o._mask == prev._mask`, otherwise walk
    everything (promotion from flat to sharded at 513 entries);
  - skip a shard when `o._shards[i] is prev._shards[i]`;
  - in a changed shard, trust an entry only when `prev_shard.get(k, MISSING) is
    v` and `k` is an exact `int` or `str`, or an exact tuple of such leaves.
    Otherwise validate both key and value;
  - for `FrozenPrefixTable`, compare `o._tables[plen] is prev._tables[plen]`,
    never `shards()`, which allocates fresh proxies (`lpm.py:88-93`). A
    persistent prefix-table builder makes identity meaningful.

  Guard tests:
  - the visited-node count is at most N/256 + c (the old code visits at least N);
  - a mutable value in a changed shard raises;
  - removing then re-adding a key as a tuple subclass with storage raises;
  - promotion walks fully;
  - `PMap(dict(old))` walks fully;
  - a builder `set` after `build()` leaves the published shard unchanged.

  Protocol tables are nested (per peer, per area, per AF), so each map stays at
  or below about 50k entries. A changed-key log emitted by the `PMap` builder is
  the follow-up option for O(k) admission.
- **F0 behaviour implemented,** delivered through the inbox with the existing
  bounds:
  - configuration, persistence, commands, views and change keys (F2a);
  - the RIB feed (`selected` at the processed epoch, `all` at the input epoch),
    owner notifications, and the NHT `installed` mode with `via_metric`, read
    from F1b's recursive-next-hop table (F2b).
- **`connected_only` parity.** FRR's connected check accepts a CONNECT or STATIC
  resolving route, not LOCAL (`zebra_rnh.c:646-667`). This touches
  `_CandidateResolver` in `routing.py`, so it is coordinated with F1. It is
  pinned by test, and the install-time difference is reproduced: a
  non-recursive route over a static stays inactive in zebra.

Exit (operation counts in CI, wall-time ratios in slow benchmarks):

- G2: an idle run at 50k rows goes from 130 ms to ≤ 0.3 ms.
- G3: one-entry admission at 100k goes from 236 ms to ≤ 100 µs, with the
  visited-count ratio asserted.
- G4 and G5 become per-client identity checks.
- The Gate C agent suites pass on both interpreters.

### F3. Transport for BGP

Files: `netsim/runtime/transport.py`, `netsim/runtime/channels.py`.

- **Wildcard listeners** with interface-set scoping and socket precedence: a
  specific binding beats the wildcard.
- **Accept tables.** Per-remote TTL and `min_ttl` on accepted connections, with
  `set_opts`.
- **Hop limit.** A routed session derives its hop count from the path trace it
  already computes. A path whose forwarding hops exceed the TTL is unreachable,
  so the connect or the queue stalls until the no-progress timeout, as a kernel
  that drops the packets behaves.
- **GTSM** (RFC 5082). The sender uses TTL 255 and the receiver requires
  `min_ttl = 256 − hops` (FRR `ttl-security hops N` sets `IP_MINTTL`).

Exit (TTL counts forwarding hops, so a TTL-1 packet still reaches the adjacent
router's loopback):

- With `disable-connected-check`, a TTL-1 session to the adjacent loopback
  establishes.
- A loopback two hops away needs `ebgp-multihop 2`.
- GTSM with `hops 1` rejects a two-hop path.
- Wildcard versus specific listener precedence; the accept table refuses an
  unknown remote.
- Existing transport suites unchanged.

"No single-hop eBGP session to a loopback without multihop" is a BG2 test,
because the NHT connected gating is what blocks it in FRR.

### F4. Domain-scoped oracle IGP

File: `netsim/model/igp.py`.

- **Factory.** `oracle_igp_domains(domains)` returns a `RouteSource`. Each
  `IgpDomain(name, devices, include, exclude, passive, instance, distance,
  metric_mode)` runs its own SPF.
  - Passive interfaces advertise their prefixes without forming adjacencies.
  - Each domain installs rows as `ClientId('igp', instance)`.
- **Purpose.** The fast analytical underlay for BGP tests and mixed studies. The
  global `oracle_igp` equals one domain spanning every device.

Exit:

- Two ASes, each with its own domain and the inter-AS links excluded: no
  inter-domain rows.
- The single-domain variant reproduces the current fingerprints.

### F5. Shared protocol toolkit

Location: `netsim/agents/common/`.

- `selection.py`: the `DecisionFlavor` protocol (`compare`, `select`,
  `multipath`), `PathView`, `DecisionContext`, `Verdict`, `Selection`, and the
  small shared comparison helpers (AS_PATH length, MED comparability, router-id
  substitution) that both built-in flavors use, each with refs. No interpreter.
- `spf.py`: pure ECMP Dijkstra (distances, first hops, predecessor sets) over
  integer node ids.
- `timers.py`:
  - `ExponentialBackoff` (Open/R semantics);
  - `AsyncDebounce` (`AsyncDebounce.h:43-67`);
  - throttle;
  - jitter from per-module RNG streams;
  - the per-module deadline heap multiplexer of D3.
- `routeops.py`: a RIB delta emitter keyed by changed-key sets.
- `sizes.py`: modelled message sizes.
- `refs.py`: the `@ref(...)` decorator (an immutable `__refs__` tuple on rule
  functions and steps) and `@covers_ref(...)` for tests, feeding the generated
  `docs/traceability.md` (section 13.8).
- `net.py`: the source-address selection helper (primary address of the egress
  interface toward a destination), used by BGP when no `update-source` is set,
  mirroring FRR's `getsockname` (`research-frr-decision.md` §4.2).
- `tests/agents/harness.py`:
  - the locality harness;
  - guarded submodule projection proxies;
  - twin comparisons and normalizers;
  - view-based assertions.

### F6. Downstream invalidation (measured, optional)

G15's conservative scans (placement on any FIB change, transport re-trace,
device-wide epochs) are narrowed with F1b's FIB diff: changed prefixes and
changed groups. This happens only if IX profiles show them dominating. Until
then, IX scenarios measure placement at declared points (`settle_delay` or
measurement-point placement) and passports report the cost.

### F8. Forwarding programming contract (D14, section 5.13)

Files: the FIB kind in `model/derive.py` and the programming records in
`model/forwarding.py` (F1 owner), with completion notifications in
`runtime/agents.py` (F2 owner). F8 follows F1b.

- **State.** Each (device, table, family, prefix) holds a desired action and an
  installed action. Requests carry `(device, table, af, prefix, generation,
  request_id, action)`. Completion arrives after `device.fib.latency_s`, or
  fails per `device.fib.failure_model` or `device.fib.capacity`, at the
  configured boundary.
- **Guards.**
  - Stale-generation completions are ignored.
  - A withdrawal cancels obligations.
  - Same-time completion and withdrawal are ordered deterministically.
  - `POLICY_EXCLUDED` desired absence keeps the old installed entry until its
    DELETE completes.
- **Default cost.** Today's `fib_delay` becomes the zero-failure special case,
  so existing fingerprints hold.
- **Exit.** G01–G04 (gate-independent parts), E09, E14, the stale-ACK tests, and
  unchanged fingerprints with default settings.

### RP1. Route-policy language (routing-policy plan P1)

- **Files:** `netsim/model/route_policy/` (`types.py`, `compile.py`,
  `evaluate.py`), plus the capability table.
- **Timing:** after F0 and F7, in parallel with F1b/F2b. It must land before
  BG3's import hook, BG4 and OR5.
- **Exit:** E01–E03, E10, E12 and E19–E22; the flow, default and absence
  truth tables; fingerprint canonicalisation.

### RP3. RIB admission with retained submissions (P3)

- **Files:** retained submission and admitted views in `model/routing.py`; the
  `RIB_ADMISSION` hook, including per-next-hop mode, on F1b's submission
  boundary.
- **Timing:** after F1b and F2b.
- **Exit:**
  - E04 (device side) and E13;
  - deny → allow and allow → deny;
  - generation purge;
  - `ip protocol` per-next-hop semantics: leg pruning, and fallback to the next
    candidate when no leg survives (`zebra_nhg.c:2880-2921`).

### RP4. Resolver and FIB policy hooks (P4)

- **Scope:** `RESOLUTION_IMPORT` with `scope='nht'` (per-client NHT answers, no
  fall-through, as `zebra_rnh.c:515-576`) and `scope='forwarding'`; the
  `FIB_INSTALL` exclusion.
- **Timing:** after F1c and F8.
- **Exit:** E05, E06, E09, E11 and E14; mixed node profiles; inactive × FIB gate
  × policy.

RP2 (BGP hooks) is part of BG3 and BG4. RP5 (the JSON codec, the typed FRR
adapter and explanations) is part of BG7. RP6 (acceptance, including E07, E23
and E24) is part of M5. P0 (ownership and client profiles) is part of F0 and
F7.

---

## 4. Open/R

### 4.1 Fidelity target

**Reproduce.** The eight behaviour groups of `research-openr.md` §10:

1. the Spark FSM, area negotiation, GR and timers with jitter;
2. the metric pipeline;
3. LinkMonitor backoff, throttles and the adjacency hold;
4. KvStore merge, TTL, refresh, self-originated override, 3-way sync, peer FSM,
   flood loop checks and per-area isolation;
5. Decision debounce and route computation;
6. PrefixManager selection, `area_stack` and cross-area rewrite;
7. the initialization chain;
8. the Fib delete delay and programming boundary.

**Simplify.** Thrift encoding, KvStore transport internals, the ctrl server,
counters, dead features, FabricHelper, NeighborMonitor and FSDB, netlink resync,
and the RTT step detector (the first sample sets the metric; an optional step
model covers changes).

### 4.2 Package

```
netsim/agents/openr/
  config.py          OpenrConfig and AreaConfig (fields the daemon reads), resolved from settings.py (the fragment
                     whose DefaultsSpec holds upstream defaults) and the lab preset
  types.py           Spark messages, NeighborEvent, PeerEvent, Adjacency, AdjacencyDatabase, PrefixMetrics,
                     PrefixEntry, PrefixDatabase, KvValue, Publication, sync records, InitializationEvent
  spark.py           neighbor FSM per (interface, neighbor), area deduction, RTT, GR, fast init
  link_monitor.py    interfaces with flap backoff, adjacency DB per area, metric pipeline, drain and
                     overload, KvStore peer specs, interface-address redistribution
  kvstore.py         per-area KvStoreDb: merge, TTL (deadline heap), flooding, peer FSM, 3-way sync,
                     self-originated keys
  decision.py        LinkState per area, SPF, PrefixState, per-prefix routes, debounce
  prefix_manager.py  prefix types and selection, originated prefixes, cross-area redistribution,
                     injection from the RIB feed
  fib.py             AWAITING / SYNCING / SYNCED, RouteOps, delete delay, FULL_SYNC after RowNotice INSTALLED
  init.py            initialization event gates
  agent.py           OpenrAgent: worklist of module queues, timer namespaces, sessions, views
```

State: `OpenrState(init, spark, spark_liveness, link_monitor, kv: PMap[area,
KvStoreDb], decision, prefix_manager, fib)`. Liveness counters (sequence numbers,
reflected timestamps) live in a small record, so a hello run admits only that
record. Drain, overload and metric overrides live in `AgentNode.persistent`.

### 4.3 Mapping to NetSim primitives

| Open/R | NetSim |
|---|---|
| Spark over UDP `ff02::1:6666` per interface, hop limit 255 (`Spark.cpp:484-566, 1024-1034`) | `Datagram(interface, link_local=True, port=spark_port)` on the link channel. Links are point-to-point, so there is no LAN fan-out |
| KvStore thrift over TCP to `<nbr LL>%<if>:2018`, connect 500 ms, request 2500 ms (`KvStore-inl.h:1716-1790`) | A scoped session to the neighbour's link-local address on `kvstore_port`. Both sides open their own client connection, giving two connections as with thrift. Requests and responses are `Message`s with request ids; timeouts are timers |
| Inter-module queues (`Main.cpp`) | The D3 worklist. Explicit throttles and debounces are timers. Fib → PrefixManager waits for `RowNotice INSTALLED` |
| FIB client 786 (`Fib.h:392`); Linux handler protocol 99, priority 10 (`Platform.thrift:128-138`) | `RouteOp` under `ClientId('openr', i)`. Distance 10, matching Open/R's priority 10 and FBOSS `AdminDistance.OPENR = 10`; configurable per row |
| Route metric | **Declared modelling choice**, the setting `openr.fib.metric_mode` (a `netsim.*`-style choice, per node). `metric_mode='igp_cost'` (default) sets the row metric to `igpCost`, so FRR hot potato over Open/R is observable. `metric_mode='linux'` uses a constant 10, as the kernel handler programs, so hot potato disappears. FRR's redistribution MED follows the row metric (`bgp_route.c:11951`) |
| Netlink interface events | A subscription on `('interfaces',)`; `InterfaceView` supplies oper state, link-local address and addresses |
| Thrift drain APIs | `Command`s writing `AgentNode.persistent` (D11) |
| RTT from reflected hello timestamps (`Spark.cpp:889-975`) | The same arithmetic on simulated timestamps. Metric = `max(rtt_us/100, 1)` after rounding down to whole ms with a 1 ms floor (`LinkMonitor.cpp:33-35`; `Spark.cpp:872-886`). Links with an RTT under 2 ms therefore all get metric 10 |
| `enable_v4`, `v4_over_v6_nexthop` (RFC 5549 / RFC 8950) | IPv4 routes use `Nexthop.via(interface, neighbor LL, af=6)` or the neighbour's IPv4 transport address |

### 4.4 Domains, areas, instances

- **Deploy helpers.** Open/R's default area `"0"` with empty regexes discovers
  nothing (`Config.cpp:34-39, 85-90`), so `openr.deploy` always writes explicit
  `AreaConfig`s.
- **Multi-area.** The lowest matching area wins (`Spark.cpp:2802-2841`). A node
  in several areas redistributes through PrefixManager: `distance + 1`,
  `area_stack`, destination areas exclude the next-hop areas
  (`PrefixManager.cpp:1669-1786`).
- **Separation.** Interfaces are owned by one instance or excluded from
  discovery. Never rely on area names, because of the `"0"` wildcard (D5).
- **Multiple instances** are `netsim_ext.multi_instance` (D5). They exchange
  routes only through an explicit RIB-feed redistribution, with tags against
  two-border loops.
- **Single-device domain.** An instance with no discovering interfaces behaves
  as `research-openr.md` §9 describes: KVSTORE_SYNCED on the first empty
  PeerEvent, an empty computed RIB, FIB_SYNCED, and its own keys in its own
  store.

### 4.5 Behaviour by module

Each rule carries its citation in code. The key rules:

- **Spark.**
  - The FSM (`Spark.cpp:103-172`).
  - The incarnation check on WARM → NEGOTIATE.
  - Handshakes every 500 ms under a 2 s negotiate timer.
  - Negotiated hold and GR times are the minimum of both sides.
  - One-way teardown.
  - Hello 20 s ±20%; fast-init 500 ms for six periods.
  - Heartbeat every hold/3 ±20%; hold 30 s; GR 30 s with restarting hellos.
  - `holdAdjacency` and `adjOnlyUsedByOtherNode`.
  - NEIGHBOR_DISCOVERED after 2 s minimum, 15 s maximum.
  - Check that an adjacency brought up from WARM through a handshake can carry
    RTT 0 (`getRttMetric(0)` returns 1); reproduce whatever upstream does.
- **LinkMonitor.**
  - Flap backoff of 60–300 s.
  - The metric pipeline, including soft-drain increments, which boot at +100
    when `assume_drained` (`LinkMonitor.cpp:243-254`).
  - Adjacency up throttled 1 s, down immediate.
  - `adj:<node>` persisted per area.
  - One KvStore peer per neighbour per area.
  - `adj_hold_time_s` 4 s.
  - Interface addresses redistributed as `LOOPBACK` (path_pref 1000,
    source_pref 200).
- **KvStore.**
  - The merge order of `KvStoreUtil.cpp:344-584`.
  - TTL decrement and the 500 ms threshold.
  - Floods go to INITIALIZED peers except the sender, with a `nodeIds` loop
    check.
  - Pending keys for syncing peers.
  - 3-way sync, the peer FSM, backoff of 4–256 s, parallel sync limit 2 → 32.
  - Self-originated keys: version bump, refresh at ttl/4, withdrawal by
    version + 1 then expiry.
  - Optional `flood_rate`.
- **Decision.**
  - Bidirectional (node, ifName, otherIfName) matching.
  - Overloaded nodes are not expanded; link cost is the maximum of both
    directions.
  - SPF is memoized per topology.
  - The steps of `SpfSolver.cpp:184-319`.
  - Debounce 10 → 250 ms.
  - A full rebuild on topology change; prefix-only changes recompute only those
    prefixes.
  - With `enable_best_route_selection=false` (the default), `bestNodeArea` is
    the lexicographically lowest (node, area) pair. It supplies
    `bestPrefixEntry` and `bestArea` independently of which areas' next hops
    are used (`SpfSolver.cpp:390-399, 543-560`; `SpfSolver.h:44`).
- **PrefixManager.**
  - Type tie-break and `selectBestPrefixMetrics`.
  - Per-area writes skip `area_stack` areas and send delete markers.
  - `minimum_supporting_routes`.
  - Cross-area rewrite: append `bestArea`, `distance + 1`, type RIB, reset
    non-transitive fields; runs only with more than one area.
  - RIB-feed injection with a configured `PrefixType` (for example `BGP`).
- **Fib.**
  - AWAITING → SYNCING → SYNCED.
  - Deletes held back 1 s.
  - FULL_SYNC publishes once `RowNotice INSTALLED` confirms programming.
  - On restart, routes are retained until the first sync (D12).
- **Initialization.** The chain of `research-openr.md` §1, every gate with its
  timeout.

### 4.6 Performance design

- **Work per run.** O(merged keys) plus SPF only on a topology change. A
  hello or heartbeat run admits only the liveness record, runs no SPF and emits
  no route ops.
- **Indexes.** LSDB indexes (adjacency by node, prefix by prefix) are updated
  from merged deltas.
- **Passport.** 256-node three-tier Clos in two areas, one loopback per node,
  `lab` and `openr-default` profiles, expected to take minutes. It reports
  cold-start and single-failure wall time, events, messages, SPF runs, memory
  and heap objects. With the default RTT metric and sub-2 ms links, the metric
  is hop count × 10. The fixed cost of about 0.2 ms per agent run plus a commit
  per hello interval is part of the budget.

### 4.7 Acceptance

- **Oracle equivalence.**
  - Configuration: a single area, `use_rtt_metric=False`, static metrics equal
    to symmetric interface metrics, `assume_drained=False` (or an undrain
    command), and `enable_v4=True` or `v4_over_v6_nexthop=True`.
  - On random graphs of 6–10 nodes, normalized routes, next hops, FIB groups
    and placement equal a domain oracle restricted to the redistributed
    prefixes.
- **Faithful defaults.**
  - RTT metrics come from link delays.
  - Soft-drain at boot shows +100 until an undrain command.
  - Cold start is no faster than the modelled gates allow.
- **Multi-area.**
  - ABR redistribution; two ABRs do not loop.
  - A case where `bestArea` differs from the areas that supply next hops.
- **Separation.**
  - Excluded boundaries leak nothing.
  - An area-`"0"` wildcard case documents the pitfall.
  - Multi-instance isolation.
- **Spark.**
  - The FSM matrix.
  - An area mismatch sends NEGOTIATE back to WARM.
  - GR within the GR time keeps routes.
  - One-way teardown.
  - A muted channel with oper still UP expires on the hold timer.
- **KvStore.**
  - Merge property tests (random interleavings converge).
  - TTL expiry after a partition.
  - 3-way sync after heal.
  - Self-originated override.
  - Flood loop check.
- **Decision and drain.**
  - Hard drain keeps the drained node reachable but removes it as transit.
  - Soft-drain increments apply.
  - `minNexthop`.
  - `drain_metric` propagates across areas.
- **Fib.**
  - The delete delay is observable in placement.
  - Redistribution waits for programming.
- **Locality and regression.** The locality harness passes; submodule
  projection proxies pass; both interpreters; fingerprints unchanged for
  non-Open/R networks.

### 4.8 Slices

| Slice | Deliverable | Exit evidence |
|---|---|---|
| OR1 | config, types, Spark, agent shell (worklist, timers, views) | FSM matrix; area negotiation; RTT metric; GR; jitter determinism; liveness-only admission |
| OR2 | LinkMonitor and KvStore, single area | LSDB convergence properties; partition, heal, expiry; peer FSM |
| OR3 | Decision, PrefixManager and Fib (single area), initialization chain, PrefixManager's programmed-prefix readiness gate (membership, as `PrefixManager.cpp:650`) | Oracle equivalence; delete delay; gate timings; readiness withdrawal on programming loss (G10 Open/R part); ratio benchmarks |
| OR4 | multi-area, `netsim_ext.multi_instance`, boundaries | ABR, `area_stack`, `bestArea` case; separation tests |
| OR5 | drain and overload through commands and `persistent`, overrides, RIB-feed injection | Drain matrix; restart keeps drain; injected prefix from a static stand-in |
| OR6 | scale passport, study integration, `netsim_ext` SRv6 locator and SID advertisement for learned SR validation | Passport numbers; learned SR policy over Open/R |

---

## 5. BGP

### 5.1 Scope

**In scope:**

- IPv4 and IPv6 unicast over MP-BGP, with 4-byte AS numbers.
- eBGP, iBGP and confederation peers; route reflection.
- Session modes: interface addresses, loopbacks (update-source, multihop,
  GTSM) and unnumbered IPv6 link-local with ENHE.
- A typed route-map subset for policy, with FRR's delay timer.
- `network`, `redistribute`, `maximum-prefix`.
- Soft reset: replay with soft-reconfiguration inbound, otherwise
  ROUTE-REFRESH.
- Named decision flavors and multipath.
- FRR pipeline timing (`frr-modern` defaults; `frr-10.5` differences are settings, section 2B).

**Out of scope for now:** EVPN, VPN, labeled unicast, flowspec, RPKI,
dampening, BMP, ORF, multi-access LANs. NetSim links are point-to-point.

### 5.2 Package

```
netsim/agents/bgp/
  config.py        global, neighbor, peer-group, AF config; validate_config; profiles
                   frr-traditional, frr-datacenter, sonic, lab
  types.py         AFI/SAFI, NLRI, path ids, OPEN / UPDATE / KEEPALIVE / NOTIFICATION / ROUTE-REFRESH / EoR,
                   capabilities, NOTIFICATION codes
  attrs.py         PathAttributes (shared by identity), communities, ORIGINATOR_ID, CLUSTER_LIST,
                   next hops (IPv4; IPv6 global [+ link-local]), modelled sizes (RFC 4271 §4)
  aspath.py        SEQ/SET/CONFED_SEQ/CONFED_SET; hop count (confed excluded, a set counts 1); confed ops;
                   loop checks with allowas-in; AS4 semantics
  peer.py          peer_sort, effective local AS, local-as, router-id selection, negotiated capabilities
  fsm.py           Idle, Connect, Active, OpenSent, OpenConfirm, Established, Clearing; timers; collision;
                   OPEN validation (identifier, RFC 6286); NOTIFICATION; fast external failover
  policy.py        BGP adapter to the shared route-policy engine (section 5.8): PolicyAccess for BGP attributes,
                   hook wiring (import, export, table-map, redistribute), reevaluation scheduling, RFC 8212
  inbound.py       UPDATE processing in FRR's check order; outcome classes (session reset,
                   treat-as-withdraw, attribute discard, filtered); soft-reconfiguration store; maximum-prefix
  nexthop.py       next-hop cache keyed (address, interface for link-local); NHT registrations
                   (mode installed); validity, via_metric; back-index next hop -> paths; connect gating
  decision/
    frr.py         bgp_path_info_cmp (modern; version differences are settings), hand-written with refs per reason; sorted-list insertion
    rfc4271.py     §9.1.1 preference, §9.1.2 exclusions, §9.1.2.2 elimination, RFC 4456 §9, RFC 5065 §5.2/§5.3
    multipath.py   maximum-paths per profile, equal-cluster-length, as-path relax, peer-type relax
  locrib.py        Dest (below); dirty queue; 50 ms process hold
  outbound.py      update groups keyed by compiled export-policy fingerprint and peer facts; announce check in FRR order; next-hop rules with a self sentinel patched
                   per peer; Adj-RIB-Out per group; duplicate suppression; source echo; packing by attribute
                   set; withdrawals first; per-peer MRAI; coalesce timer; EoR
  rr.py            reflection matrix, ORIGINATOR_ID and CLUSTER_LIST writing, inbound loop checks
  confed.py        confederation data, send-side AS_PATH construction, receive checks
  zebra.py         BGP_RIB_EXPORT (table-map) hook, then Loc-RIB -> RouteOps (distances, recursion, legs, weights, metric = MED,
                   reinstall conditions, latest-state-wins queue)
  origination.py   network with exact-prefix, non-BGP import-check; redistribute from the RIB feed with policy and tags
  agent.py         BgpAgent: worklist composition, timers, sessions, views, commands
```

### 5.3 Sessions

| Mode | Configuration | Transport | Next hop sent | Receiver NHT and install |
|---|---|---|---|---|
| eBGP single-hop on link addresses | `neighbor 10.1.12.1 remote-as X` | routed, TTL 1; source address from `agents/common/net.py` | self (the local address) | `connected_only`, connect gated on it; non-recursive install (interface + address) |
| iBGP over loopbacks | `remote-as internal`, `update-source lo` | TTL 255; needs a route to the peer (IGP, static or BGP) | unchanged for eBGP-learned routes unless next-hop-self | recursive; `via_metric` (installed) feeds the IGP step |
| eBGP multihop or GTSM on loopbacks | `ebgp-multihop N` or `ttl-security hops N` | TTL N, or TTL 255 with `min_ttl` | self (a loopback, indirect for the receiver) | recursive |
| Confed peer | peer AS in `bgp confederation peers` | TTL 1 by default (`bgpd.c:2532-2552`); `ebgp-multihop` for loopbacks further away | unchanged; next-hop-self applies | no connected check; recursive; distance 200 |
| iBGP on link addresses | `neighbor <link addr> remote-as internal` | TTL 255 | unchanged; with `next-hop-self force` on reflected routes, self | recursive (resolves over the connected route) |
| Unnumbered | `neighbor eth1 interface remote-as external` | scoped link-local session; the peer's link-local comes from `ctx.neighbors` | ENHE: IPv4 NLRI over an IPv6 link-local next hop (RFC 8950) | driven by interface state, never registered with zebra (`bgp_nht_ifp_up/down`) |
| Passive; dynamic peers (BG8) | `passive`; `bgp listen range` | listener with accept table | by sort | by sort |

- **Collision** (RFC 4271 §6.8, FRR): the connection initiated by the speaker
  with the higher BGP identifier survives; on equal identifiers, the higher AS
  wins. The loser gets Cease/7. An Established or Clearing connection always
  survives.
- **Router id** follows zebra: the configured value; else the highest IPv4
  loopback address; else the highest IPv4 interface address
  (`zebra/router-id.c`). IPv6-only fabrics need an explicit id. An iBGP OPEN
  carrying our own identifier is rejected (RFC 6286).
- **Teardown.** Fast external failover (D8). Hold expiry sends NOTIFICATION
  4/0, flushes the Adj-RIB-In and withdraws from other peers. Recovery goes
  through idle hold, connect retry and the coalesce timer.
- **Unnumbered simplifications, recorded.**
  - FRR learns the peer's link-local from RAs with a 10 s interval
    (`bgpd.h:68`); NetSim knows it as soon as the L3 neighbour entry exists.
  - The final tie-break compares the IPv6 scope id, which needs NetSim's stable
    ifindex.

### 5.4 Next hops and attributes on send and receive

**Send side** (`research-frr-decision.md` §4.5; `research-frr-rr-confed.md` §5):

| Route → target | NEXT_HOP |
|---|---|
| local `network`, aggregate, redistributed connected → any | self |
| any → eBGP | self, unless the next hop shares a connected subnet with the target (RFC 4271 §5.1.3 third party) |
| eBGP-learned → iBGP | unchanged, unless next-hop-self or force |
| iBGP → iBGP (reflected) | unchanged; plain next-hop-self ignored; `force` sets self |
| any → confed member peer | unchanged; next-hop-self applies |
| confed-learned → iBGP | unchanged; plain next-hop-self applies (this is not reflection) |
| `attribute-unchanged next-hop` / route-map `unchanged` | kept |
| a link-local next hop placed in the global field | always reset to self (`bgp_route.c:3205-3217`) |

Other attributes on send:

- MED is stripped toward eBGP unless the route is locally originated or
  `attribute-unchanged med` is set.
- LOCAL_PREF is sent to iBGP and confed peers, filled with the default when
  absent.
- ORIGINATOR_ID and CLUSTER_LIST are written only iBGP → iBGP.
- Communities follow the well-known rules.
- IPv6 carries a global plus link-local next hop only under RFC 2545 §3.

**Receive side.**

- Checks run in FRR's order (`research-frr-rr-confed.md`, implications §5):
  1. local-as;
  2. AS loop with allowas-in;
  3. originator;
  4. cluster;
  5. RFC 8212;
  6. filters;
  7. route-map;
  8. BLACKHOLE and GSHUT;
  9. own next hop (`bgp_update_martian_nexthop`: filtered).

  A martian IPv4 NEXT_HOP (0/8, 127/8, class D/E) is caught earlier, at
  attribute parse, and is treat-as-withdraw (RFC 7606 §7.3). 10.5.4 reset the
  session instead; this is a fix, not modelled.
- Additional semantic checks:
  - confed sanity: a confed peer's path must start with a confed segment, and
    an eBGP path may contain none; a violation is treat-as-withdraw;
  - `enforce-first-as` (on by default);
  - AS 0 from eBGP;
  - `reject-as-sets` (on by default).
- Every loop-check failure is an implicit withdraw, never a NOTIFICATION.
- Validity comes from NHT. When a next hop changes, only the paths on it are
  re-evaluated (FRR `evaluate_paths` over `bnc->paths`).

**Install.**

- Distances: eBGP 20, iBGP 200, confed 200.
- Recursion is allowed except for single-hop eBGP.
- Metric = MED.
- `network` and redistributed winners are not installed.
- For an unchanged best path with unchanged attributes and no clear or
  add-path in effect, a route is reinstalled only on an IGP-metric, multipath or
  bandwidth change (`bgp_route.c:4439-4462`); otherwise the complete emitted
  local row is compared and replaced when its semantics change (a MED edit
  changes the installed metric). `zebra.py` never re-emits identical rows: each costs about 7.8 µs of `RouteOp`
  validation plus about 2 µs of `rib_apply` equality checking.

### 5.5 Decision process and flavors

**Per-destination state.** Everything a flavor needs across runs is explicit and
immutable:

```python
Dest(key=(vrf, afi, safi, prefix), paths: PMap[PathKey, Path], order: tuple[PathKey, ...],
     unsorted: tuple[PathKey, ...],      # in bgp_process order: each changed path moves to the head
     removed_best: PathKey | None,       # a removed old best survives one round
     best: PathKey | None, multipath: tuple[PathKey, ...], reason: str,
     flags: frozenset[str],              # multipath_changed, igp_changed, attr_changed
     flavor_memo: Any)                   # reset on any flavor or knob change (full recalculation)
PathView(attrs, peer, sort, received_seq, established, valid, via_metric, stale, ...)
DecisionContext(config knobs, router id, confederation, prev_best)
```

**Candidate filter** (all flavors). Excluded: holddown paths (invalid next hop,
removed) and paths from peers that are not Established, except local paths and
paths in GR helper wait. GR-stale paths stay and lose late, unless their next hop
becomes unreachable, in which case modern FRR deletes them (RFC 4724 §4.2;
N1 in section 2B).

**`frr`**: modern `bgp_path_info_cmp`, hand-written with a reference per reason.

- **Pre-steps**, in order:
  - LLGR_STALE loses, ahead of weight, and sets no reason (quirk kept);
  - step 0, admin distance between a redistributed path and an installable BGP
    path, gated by `bgp.bestpath.redist_admin_distance`: on in `frr-modern`
    (since 10.6.0), off in `frr-10.5`;
  - UPA is master-only and out of scope.
- **Main steps:**
  - 1–3: weight (32768 for local routes); local-pref; local route (all local
    sub-types tie).
  - 3.5: AIGP (off by default).
  - 4: AS_PATH length (confed excluded, a set counts as 1). 5: origin.
  - 6: MED, under the leftmost-AS rules with the confed variants and
    missing-as-worst.
  - 7: peer type (confed counts as internal).
  - 8: IGP metric, held.
  - 9: cluster-list length as an IGP substitute, only with
    `equal-cluster-length`.
  - 10: confed-external over confed-internal. It returns immediately,
    overriding step 8, except under `bgp bestpath peer-type multipath-relax`,
    where it is deferred past the multipath check like step 7
    (`bgp_route.c:1654-1684`).
  - 11: multipath check.
  - 12: keep the current eBGP best (RFC 5004), unless `compare-routerid`.
  - 13: router id, with ORIGINATOR_ID substituted.
  - 14: cluster-list length.
  - 15: stale, locally configured, lower neighbour address (IPv4 before IPv6,
    then scope id).
- **Selection is sorted-list insertion**, with three rules that decide results:
  - (a) within one 50 ms batch, changed paths are inserted in reverse arrival
    order, because each moves to the head;
  - (b) withdrawals and holddown do not re-sort the remaining list; the new
    best is the head of the existing order;
  - (c) step 12 reads the previous best, so history matters.
- **Reason strings** equal FRR's `selectionReason`.
- **`dmed`** (`bgp.bestpath.dmed`).
  - `'frr-current'` is FRR since 10.4.0 (also 10.2.2 and 10.3.1): grouping
    feeds only add-path.
  - `'classic'` is pre-10.1 FRR: only the neighbouring-AS group winners compete.
  - The default in both dialects is `'frr-current'`.

**`rfc4271`**, in three phases:

- §9.1.1 Phase 1 assigns the degree of preference: LOCAL_PREF for iBGP-learned
  routes, a policy value for eBGP-learned routes.
- §9.1.2 Phase 2 excludes unresolvable next hops (§9.1.2.1) and AS loops, then
  keeps the highest preference.
- §9.1.2.2 a–g eliminates over the whole set:
  - (a) AS_PATH length, with an AS_SET counting as 1;
  - (b) origin;
  - (c) MED per neighbour AS, with a missing MED as 0; `neighborAS` for
    iBGP-learned routes as the section defines it;
  - (d) eBGP over iBGP;
  - (e) interior cost, skipped when no cost can be determined;
  - (f) lowest BGP identifier;
  - (g) lowest peer address.

Amendments:

- RFC 4456 §9: ORIGINATOR_ID replaces the identifier; the shorter CLUSTER_LIST
  rule sits between (f) and (g).
- RFC 5065 §5.2: MED comparison skips confed segments.
- RFC 5065 §5.3, all four rules:
  1. a path with only confed segments has the local AS as its neighbour AS;
  2. otherwise the neighbour AS is the leftmost AS of the first AS_SEQUENCE;
  3. confed segments are not counted in path length;
  4. confed peers count as internal at (d).

Locally originated routes compete through a documented NetSim choice, since the
RFC does not say. There is no multipath by default (RFC 4271 defines none); the
FRR rule can be enabled explicitly. The result does not depend on order.

**Later flavors (BG8).** `cisco-ios` and `junos` (section 10), each verified
against the vendor document for the targeted release.

**Custom flavors.** A `FlavorSpec` holds built-in step names and user step
instances with refs and is the value of the `bgp.decision` setting, so it is
overridable per node. Knob arguments to `FlavorSpec.use(...)` write the
corresponding `bgp.bestpath.*` settings.

**Multipath (FRR).**

- `maximum-paths` defaults to `MULTIPATH_NUM` per profile:
  - 16 for a bare `./configure`;
  - 256 for FRR's packages (`debian/rules:84`; `redhat/frr.spec.in:21`);
  - SONiC: patch 0016 raises `MULTIPATH_NUM` to 514, which caps the value; the
    SONiC template configures `maximum-paths 64`.
- Candidates tie with the best path through step 11. iBGP needs an identical
  AS_PATH; eBGP and confed need the same configured neighbour AS, unless
  `as-path multipath-relax`.
- `equal-cluster-length` applies to iBGP.
- `maxpaths` is chosen by the best path's peer sort; the set follows sort order.
- Link-bandwidth UCMP comes in BG8.

### 5.6 Route reflection (RFC 4456, FRR dialect)

- **Reflection matrix.** It applies only when source and target are both IBGP.
  - A client route goes to clients (unless
    `no bgp client-to-client reflection`), non-clients, confed and eBGP peers.
  - A non-client route goes to clients, confed and eBGP peers.
  - eBGP, confed and local routes go to everyone.
- **Attributes.** ORIGINATOR_ID is set from the source peer's identifier
  **only when absent** (`bgp_route.c:2820-2825`), and the cluster id is
  prepended to CLUSTER_LIST, iBGP → iBGP only. Both are stripped toward confed
  and eBGP peers. The cluster id defaults to the router id.
- **Inbound loop checks.** Our identifier as ORIGINATOR_ID, or our cluster id in
  CLUSTER_LIST, is an implicit withdraw.
- **Outbound policy on reflected routes.** Only permit and deny apply; set
  actions are dropped unless `bgp route-reflector allow-outbound-policy`, in
  which case a route-map may rewrite the next hop and that explicit rewrite
  prevents the automatic reset (`bgp_route.c:2963-2981, 3127-3149`). Plain
  `next-hop-self` is ignored on reflected routes; `force` applies.
- **Echo.** FRR suppresses sending a route back to its source only for
  `neighbor X solo` peers (`PEER_FLAG_LONESOUL`, `bgp_route.c:2471, 2612`).
  Echoes to eBGP sources and RR clients are therefore sent and dropped by the
  receiver. They are modelled, because they change message counts.

### 5.7 Confederations (RFC 5065, FRR dialect)

- **Peer sort.** A peer AS listed in `bgp confederation peers` is CONFED. A
  peer whose AS equals our confederation identifier is iBGP (10.7.0 fix; 10.5.4
  classed it eBGP).
  - TTL 1 by default.
  - Distance 200.
  - No connected check.
  - RFC 8212 exempts confed peers in FRR, although the RFC names
    confederation boundaries (recorded deviation).
- **Sending to a confed peer.** The member AS is prepended as
  AS_CONFED_SEQUENCE. LOCAL_PREF is sent, MED is kept and the next hop is
  unchanged. ORIGINATOR_ID and CLUSTER_LIST are dropped. NO_EXPORT_SUBCONFED
  blocks the route.
- **Sending to a true external peer.** Confed segments are stripped and the
  confederation id is prepended.
- **Receiving.**
  - The confed sanity checks of §5.4.
  - The loop check covers the member AS in any segment and the confed id in
    non-confed segments.
  - Any path containing the confed id is suppressed on send.
- **Decision.**
  - Step 7 counts confed peers as internal.
  - Step 10 prefers confed-external over confed-internal before the IGP metric.
  - `med confed`; `as-path confed`.

### 5.8 Routing policy: one shared engine (integrates `docs/plans/routing-policy.md`)

The BGP-local route-map evaluator of earlier revisions is replaced by the shared
route-policy engine specified in the reviewed routing-policy plan
(`NetSim/docs/plans/routing-policy.md`, revision 4; review record
`routing-policy-reviews.md`, 36 findings). That document is the contract for
the language, evaluator, attachment capabilities, lifecycle and fixtures
E01–E24. This section states how it fits this plan and records the corrections
made during integration (section 11, revision 5).

**Language and engine.** `netsim/model/route_policy/` (`types.py`,
`compile.py`, `evaluate.py`; a codec later) is model-layer code shared by BGP,
Open/R injection, RIB admission, FIB installation and resolver filtering.
- **Records:** `RoutePolicy(name, terms)`; `Term(name, when, actions, flow)`;
  `RoutePolicyBinding(point, policies, fallback, match_input)`;
  `RoutePolicyRef` / `RouteSetRef` pinned by revision and content digest.
  `RoutePolicyRef` is distinct from the SR `PolicyRef`.
- **Flow values**, exactly four: `ACCEPT`, `REJECT`, `NEXT_TERM`,
  `NEXT_POLICY`. `ACCEPT` and `REJECT` end the whole chain, and the fallback at
  the end of a chain is explicit. An absent binding is distinct from an empty
  chain (RFC 8212 needs the difference). A `REJECT` term cannot carry actions,
  and a rejection discards tentative edits.
- **Match input:** `ORIGINAL` means this attachment's input; `WORKING` is the
  default. Actions always operate on the working route.
- **Predicates:** typed leaves composed with `AllOf`, `AnyOf` and `Not`.
  - Quantifiers are explicit, and an absent attribute is not zero (`Present`).
  - `PrefixListPermits` gives ordered first-match prefix lists.
  - BGP AS-path predicates count hops as section 5.5 does: confederation
    segments excluded, an AS_SET counted once.
- **Excluded from the language:** loops, calls, jumps, runtime name resolution,
  Python callbacks and raw regular expressions.
- **Access to route fields:** a code-owned `PolicyAccess[T]` (`read`,
  `read_context`, `apply`) over the owner's own immutable route type, with a
  closed field and action catalog and one capability table per attachment
  point. There is no universal route record and no `set(field, Any)`.
- **Failure handling:** compilation rejects the whole configuration on any
  error. Failures in an access adapter are invariant violations that abort the
  owner's transaction; they never become a policy deny.

**Attachment points and their FRR mappings.** Integration checked each FRR
mapping in source and corrected two. The FRR adapter in BG7 uses this table,
and it rejects every construct it cannot lower exactly.

| Point | Owner and meaning | FRR construct it translates, verified in source |
|---|---|---|
| `BGP_IMPORT` | BGP inbound; filter or modify a received candidate | `neighbor X route-map M in` |
| `BGP_EXPORT` | BGP outbound, per peer; suppress or modify an advertisement | `neighbor X route-map M out` |
| `BGP_RIB_EXPORT` | BGP → RIB submission; may rewrite the local row's metric and next hops or omit it; the selected BGP path is untouched | `table-map M`. Filtering behaviour is to be confirmed by a lane fixture |
| `REDISTRIBUTE` | Origination into BGP from RIB rows | `redistribute P route-map M` |
| `RIB_ADMISSION` | Model-owned admission of a submitted row into the main RIB, keeping a retained submission view | **None directly.** FRR's `ip protocol P route-map M` is not a submission filter: zebra evaluates it per original next hop during next-hop activation (`zebra_nhg.c:2880-2921`, after `nexthop_active` fills the interface), deactivating a denied next hop and its resolved contribution; a route left with no active next hop is ineligible and zebra selects the next candidate; system routes and family mismatches bypass it. It maps to the resolver's candidate-next-hop activation filter (RP3), which reevaluates on underlay change without a new submission |
| `FIB_INSTALL` | Model programming stage; desired absence (`POLICY_EXCLUDED`) without fallback to another candidate and without leg pruning | **None.** Native only, and the FRR adapter never targets it; `ip protocol` belongs to `RIB_ADMISSION`, per the row above. The EOS documentation conflict stays a named fixture |
| `RESOLUTION_IMPORT` | Resolver; excludes candidates for a query. **Integration adds a scope:** `nht` (next-hop tracking answers for one client) or `forwarding` (recursive resolution for installation) | **`ip nht P route-map M` = scope `nht`, `fallthrough='never'`.** zebra first picks the resolving route by longest match, then filters that route's next hops for that client protocol. If all are filtered, the client is told "filtered/unresolved" and no less specific route is tried (`zebra_rnh.c:515-576`). Forwarding recursion is unaffected. The native `forwarding` scope, with fall-through obeying `lpm_fallthrough`, has no FRR equivalent |

**Where the pieces live.**
- `agents/bgp/policy.py` becomes the BGP field and action adapter plus hook
  wiring. It is not an evaluator.
- Open/R's `prefix_manager.py` uses `REDISTRIBUTE`-style bindings when RIB-feed
  injection lands (OR5), through a destination-owned capability row.
- The device hooks (`RIB_ADMISSION`, `FIB_INSTALL`, `RESOLUTION_IMPORT`) belong
  to F1/F2 and the new F8 programming contract.
- Policy bindings are per-node settings (section 2A): exactly one resolved
  binding per (node, point, owner or instance, family, table, peer).

**Retained inputs.**
- `RIB_ADMISSION` keeps the unfiltered submission view next to the admitted
  view once a family has a binding, so deny → allow can restore a row.
- Every production RIB writer goes through one model-owned submission helper
  (F1b): `derive.py` connected, local and SR-local; `igp.py`; `entities.py`
  `RibClient`; `network.py` batch reconciliation; `runtime/agents.py`
  `RouteOp`s. Trusted bypass writers update both views.
- BGP import reevaluation replays the soft-reconfiguration store when one is
  kept, else sends ROUTE-REFRESH (RFC 2918). Enhanced route refresh (RFC 7313,
  BoRR/EoRR) gives a completion boundary. With neither, the state is
  `needs_session_reset`, never reported as settled; the per-node setting
  `bgp.policy.on_replay_unavailable` is `report` or `reset_session`.

**Edit timing** replaces the old fixed 5 s `DELAYED` action.
- A validated definition is active for new inputs at commit. Reevaluation of
  existing routes follows `policy.reevaluation.mode` (`automatic` or `manual`)
  and `policy.reevaluation.delay_s`.
- The `native` default is `automatic`, 0 s. The FRR dialects default to
  `automatic`, 5 s, the `bgp route-map delay-timer` default.
- The FRR adapter maps a delay-timer of 0 to `manual`, because FRR's zero
  disables automatic route updates and flushes a pending timer
  (`bgp_set_route_map_delay_timer`). Zero never maps to native immediate
  reevaluation.
- Scheduled work captures the owner generation and target revision, and reads
  current inputs when it runs.

**Update groups** are keyed by the compiled export-binding fingerprint plus the
declared peer and context facts the policy reads, never by policy name.

**Regular expressions.** None in the native core. The FRR adapter lowers only
anchored single-ASN AS-path patterns (`^A_`, `_A$`, `_A_` and their
equivalents) to typed predicates, and rejects the rest with a report. A bounded
regex grammar is a separate later slice with source-backed semantics.

**RFC 8212 and profiles.** With `bgp.ebgp_requires_policy` True (the
`traditional` profile) an otherwise valid eBGP session still reaches Established
and exchanges control messages; per AF and direction, a missing import binding
discards received routes and a missing export binding suppresses advertisements
(FRR filters in announce and UPDATE processing, `bgp_route.c:2692-2702,
6265-6275`, and reports the state operationally). The configuration and the
OPEN are never rejected for a missing policy; views report the missing-policy
state; an attached empty binding is distinct and follows its fallback. Not
enforced under `datacenter`, or under the `sonic` preset, which writes `no bgp
ebgp-requires-policy`. Confed peers are exempt (a recorded FRR deviation).

**`maximum-prefix`.** Cease/1, with restart-after or warning-only.

### 5.9 Pipeline timing (`frr-modern` defaults)

| Stage | Behaviour | Default |
|---|---|---|
| inbound | withdrawn NLRI (IPv4, then MP_UNREACH) before announced; a duplicate of the interned attributes triggers nothing. Master-only (#23420); 10.5.4 applies IPv4 announce first, so a prefix in both fields ends withdrawn. That is a fix, not modelled for `frr-10.5` | – |
| best-path scheduling | one selection per destination per burst; the work queue holds the first enqueue | 50 ms hold |
| install | latest-state-wins queue to `RouteOp`s, then the device's `fib_delay`. zebra's own 10 ms RIB queue hold (`zebra_router.h:185`) is folded into `fib_delay` (recorded simplification) | – |
| new subgroup | coalesce timer; the initial table bypasses MRAI. "Peers" counts the peers configured in the instance at each creation | `min(10 s, 1 s + 50 ms × peers)` |
| MRAI | per peer; withdrawals gated per `bgp.out.mrai_withdrawals` (`gated` in modern, `bypass` in `frr-10.5`) | 0 s for eBGP and iBGP |
| install queue | two classes: destinations that resolve tracked next hops are drained first (10.7.0) | – |
| suppress-fib-pending / FIB ACK gate | the F8 programming contract and gate profiles of section 5.13; FRR's `suppress-fib-pending` = the limited-scope `frr-suppress-fib-pending` profile (new peer-learned routes gated; a selected path not installed is withdrawn, except a selected `network` static) | off; on in `sonic`; batch 1000 ms |
| inactive export | whether a BGP best path that lost the main-RIB election is advertised (`bgp.export.inactive`, section 5.13) | on in FRR dialects unless suppress-fib-pending |
| advertisement-delay | hold UPDATEs N s after the first Established peer; selection and FIB proceed | off |
| GR select-defer | restarter deferral (BG8) | 120 s modern, 240 s `frr-10.5`, 45 s `sonic` ToR |
| keepalive / hold | negotiated as the minimum hold; keepalive capped at hold/3 | 60/180 s traditional, 3/9 s datacenter |
| connect retry | doubles to 120 s unless set explicitly | 30 s traditional, 10 s datacenter |
| idle hold | 1 s for the first start; doubled before re-arming after an error (so 2 s first), up to 120 s; reset on Established | 1 s |
| policy edits | active for new inputs at commit; reevaluation per `policy.reevaluation.mode`/`.delay_s`; import replay needs a soft-reconfiguration store, ROUTE-REFRESH or reports `needs_session_reset` (section 5.8) | automatic, 5 s in FRR dialects; 0 s in `native` |
| update-delay | plugs selection until timer or EoR from all peers | off |

### 5.10 State and performance

- **Tables.**
  - `Dest` per key in a sharded `PMap`.
  - A next-hop back-index `PMap[nh_key, PMap[(dest, path), None]]`.
  - Adj-RIB-Out as `PMap[group, PMap[dest, advertised attrs]]`.
  - Per-peer deadlines in the module deadline heap.
- **Attribute sharing.** Attributes are shared by identity: an UPDATE's
  attribute object is delivered by reference. Import policy is evaluated per
  route and context; compiled bindings are reused, results are not (a policy
  may depend on the prefix, so attribute identity is not a valid cache key).
- **Change-proportional targets.**
  - An UPDATE with k prefixes costs O(k × affected groups).
  - A next-hop change costs O(paths on that next hop).
  - A keepalive run admits O(1) records.
- **Cost model.** Primitive costs measured on this tree:
  - `PMap.set` 1.5 / 3.4 µs at 10k / 100k;
  - `rib_apply` 9 µs per row in a batch, 23 µs for a single row at 50k;
  - `RouteOp` validation 7.8 µs per row;
  - incremental FIB about 30 µs per prefix;
  - admission about 30 µs per touched shard at 50k;
  - a fixed 0.2 ms per agent run. Each route op also triggers a second
    `CAUSE_ROUTES` run.

  So a BGP path arrival costs roughly 150–250 µs per router, plus about 40 µs
  per update group. Keepalives with the datacenter profile cost about 670 runs
  per simulated second per 1000 sessions (0.13–0.33 s of wall time).
- **Passports** are defined in section 14.4 (P-A analytical 100k devices, P-B
  BGP full table, P-C wide protocol fabric). The earlier list below is kept
  for the cost model only; each publishes wall time, events, messages, memory
  and heap object counts (GC multiplies allocation-heavy paths by about 4×,
  G16), with `keep_records` bounded:
  - (a) RFC 7938 Clos, 128 devices, eBGP unnumbered. Plausible, but minutes,
    not seconds: a 64-neighbour spine holds about 70k paths, and MRAI 0 path
    hunting multiplies that.
  - (b) An AS with 2 RRs, 10k external prefixes on 32 clients plus 50k on 4
    clients. Gated on the cost of a single-prefix flap. The revision 1 size
    (50k × 32) was about 3.2M path arrivals, roughly 8 minutes and at least
    4 GB, beyond a CI runner.
  - (c) Hop-by-hop iBGP RR with next-hop-self force on a 64-device ring and Clos.

### 5.11 Acceptance scenarios

Each scenario records its provenance: an RFC section and the FRR topotest it is
written after, where one exists. Topotests are not copied.

1. **eBGP single-hop, numbered, IPv4 and IPv6.** The next hop is direct and
   installs non-recursive. An interface going down triggers fast external
   failover:
   - the session is stopped;
   - the Adj-RIB-In is flushed;
   - withdrawals go to the other peers;
   - recovery follows idle hold, connect retry and coalesce.

   With `no bgp fast-external-failover`, the path is invalidated by the
   connected check and the session survives until hold expiry.
2. **Unnumbered eBGP with RFC 8950** (after `bgp_unnumbered`,
   `bgp_ipv4_over_ipv6`).
3. **iBGP full mesh over loopbacks, first on a domain oracle, then on Open/R**
   with `metric_mode='igp_cost'`.
   - Hot potato by IGP metric, reason "IGP Metric" (after
     `bgp_path_selection`).
   - An IGP failure reprocesses only the paths on the affected next hops (count
     assertion).
   - `metric_mode='linux'` removes hot potato, as it would on a real device.
4. **eBGP over loopbacks.**
   - With the loopback learned from an IGP and no multihop, there is no
     session: NHT connected gating holds the connect.
   - With a static route to the loopback, the session establishes at TTL 1,
     because zebra's connected check accepts STATIC, but the routes stay
     inactive (§9 quirk).
   - `disable-connected-check` at TTL 1 establishes and installs recursively
     (`10.5.4:bgp_zebra.c:1570-1574`).
   - `ebgp-multihop` establishes it.
   - GTSM rejects a longer path.
5. **Route reflection** (after `bgp_rr_ibgp`).
   - Single cluster; redundant RRs with the same and with different cluster
     ids.
   - Client-to-client reflection off.
   - ORIGINATOR_ID and CLUSTER_LIST loops handled as implicit withdraws.
   - Reflected next hops unchanged, so an IGP or next-hop-self force is
     required.
   - Echo message counts.
6. **Hop-by-hop iBGP, every router an RR for its neighbours,
   `next-hop-self force`, no IGP.** A NetSim scenario; `bgp_cluster_length`
   covers the related case without force, with next hops resolved BGP-over-BGP.
   - With `maximum-paths ibgp N equal-cluster-length`, this equals shortest-hop
     ECMP.
   - Without it, step 9 is skipped. The multipath set is every neighbour whose
     best path does not contain the receiver's cluster id, so A→C and C→A can
     coexist. The forwarding loop is asserted by trace.
7. **Confederations** (after `bgp_confed1` and
   `bgp_confederation_stripped_to_external`).
   - Externals see the confed id.
   - LOCAL_PREF is kept across sub-ASes.
   - Confed-external wins before the IGP metric.
   - `med confed`.
   - Loopback confed peering one hop away establishes at TTL 1 (no connected
     check); two hops away needs `ebgp-multihop 2`.
8. **Decision flavors.**
   - Per-step unit tables per flavor.
   - Order dependence with controlled batching: all iBGP paths A = (AS1,
     MED 0, rid 3), B = (AS1, MED 10, rid 1), C = (AS2, MED 5, rid 2).
     - Under `frr` with one path per batch, arrival A, B, C selects C, and
       B, C, A selects A.
     - The same paths delivered in one batch follow rule (a).
     - `rfc4271` selects the same path for every order.
   - `compare-routerid` versus RFC 5004.
   - A unit test that a withdrawal does not re-sort.
9. **Policy** (the routing-policy plan's fixtures E01–E24 apply in full; the
   BGP-side ones belong to this scenario).
   - RFC 8212 per profile, with absent and empty bindings distinguished.
   - local-pref, MED, communities, prepend.
   - NO_EXPORT, NO_ADVERTISE, NO_EXPORT_SUBCONFED.
   - Edit reevaluation (automatic, manual, FRR delay 0) and soft reset in, all
     three paths: replay, ROUTE-REFRESH and `needs_session_reset`
     (E08, E15–E17).
   - Update-group isolation by policy fingerprint and peer facts (E18).
   - `table-map` and redistribute hooks.
   - `maximum-prefix`.
13. **Installation gating and inactive export** (section 5.13, G01–G10).
    - An ACK-gated first advertisement.
    - Failure, capacity limits and a lost completion.
    - A stale ACK after replacement.
    - A withdrawal while a request is pending.
    - A static or IGP route winning the RIB, with inactive export on and off.
    - The three gate profiles.
    - The FRR suppress-fib-pending limited-scope profile.
10. **Dynamics.** Expected results are per flavor.
    - RFC 3345 §2 MED oscillation: `rfc4271` cycles, and the study reports
      `deadline_exceeded`. `frr` may settle in a stable, suboptimal state,
      because withdrawals do not re-sort; the arrival order decides, and the FRR
      lane confirms.
    - BAD GADGET (Griffin–Shepherd–Wilfong) diverges under both flavors.
    - DISAGREE settles in one of two stable states depending on timing and
      seed.
11. **Timing.**
    - MRAI 0 versus 30 s.
    - The coalesce delay dominates initial convergence.
    - Hold expiry on a stalled transport.
    - Connect-retry and idle-hold backoff.
12. **Origination.**
    - `network` with exact-prefix import-check.
    - `redistribute` through the RIB feed.
    - Tag-based loop prevention between two borders (IX).

### 5.12 Slices

| Slice | Deliverable | Exit evidence |
|---|---|---|
| BG1 | `types`, `attrs`, `aspath`, `peer` (sort, router id), `config`, profiles | Semantic vectors re-derived from RFC 4271 §9.1.2.2, RFC 5065 §5.2/§5.3 and RFC 6793 (FRR `tests/bgpd/test_aspath.c` as an edge-case checklist only); sizes; profile provenance |
| BG2 | `fsm` and session modes (needs F2a, F3), capabilities, collision, timers, fast external failover, NHT connect gating | Establishment matrix for every row of §5.3; collision; hold negotiation; backoffs; teardown and flush |
| BG3 | `inbound`, `nexthop`, `frr` and `rfc4271` flavors, multipath, `locrib`, `zebra` (needs F2b; performance exit F1c, F2c) | Decision tables; scenario 8; direct and indirect next hops; BGP-over-BGP; `via_metric`; ratio benchmarks |
| BG4 | `outbound`, the `policy` adapter and hooks (RP2: export, table-map, redistribute, reevaluation), MRAI and coalesce (with `bgp.out.mrai_withdrawals`), FIB ACK gate profiles and inactive export on F8, advertisement-delay, `origination`, soft reset and refresh paths, `maximum-prefix` | Scenarios 1–4, 9, 11, 12, 13 (except IX); message counts (echo, withdrawals first); `sonic` preset timing and withdrawal effects of suppress-fib-pending; `@covers` tests for every key BG4 introduces |
| BG5 | route reflection | Scenarios 5, 6 |
| BG6 | confederations | Scenario 7 |
| BG7 | conformance and dynamics: scenario 10; RP5 (the canonical JSON policy codec, explanations, and the typed FRR route-map subset adapter with the corrected `ip protocol` and `ip nht` mappings and anchored AS-path regex lowering); `netsim/adapters/frr.py` (a bounded `frr.conf` subset: load and dump); SONiC BGP tables (`BGP_NEIGHBOR`, `BGP_GLOBALS`, `DEVICE_METADATA.bgp_asn`); the optional FRR containerlab lane (10.5.4, 10.7.1, master by digest) with committed goldens; the Z5 and N6 black-box checks that decide the quarantined items | Scenario pass list; lane report; goldens replayed by `make check` without dependencies |

### 5.13 FIB programming, acknowledgement gating and advertising inactive routes

These two functions are required (`RFCs/FIB-ACK-AND-INACTIVE.md`): gating an
advertisement on forwarding installation, and advertising a valid BGP best path
that another protocol displaced in the main RIB (RFC 4277 §11). The
routing-policy plan's `FIB_INSTALL` fixtures E09 and E14 depend on the same
programming contract, so it becomes foundation slice F8.

**Programming contract (F8).**
- Each (device, table, family, prefix) keeps a desired action and an installed
  action.
- Requests carry `(device, table, family, prefix, generation, request_id,
  action)`, and completions name a configured boundary (`control`, `kernel` or
  `hardware`).
- Delay, capacity failure, explicit error, lost completion, retry and
  withdrawal are observable. A timeout is never turned into success.
- A completion for an old generation, another table or an obsolete request is
  ignored, and a withdrawal cancels outstanding obligations.
- The hardware model is per-node settings: `device.fib.latency_s`, which
  supersedes the current `fib_delay`, and `device.fib.capacity`,
  `device.fib.failure_model` and `device.fib.multipath_completion` (partial or
  atomic).
- `RowNotice` carries the request generation, so stale completions cannot
  satisfy a gate.

**Settings** (per node; the bundle is one override unit named
`fib_advertisement`):

| Key | Values | Default |
|---|---|---|
| `bgp.export.inactive` | bool: may a BGP best path that lost the main-RIB election be exported? | True in the FRR dialects, which advertise the best path regardless of the zebra winner unless suppress-fib-pending (`bgp_route.h:771-806`); False in `native`, as Junos defaults |
| `fib.ack.gate` | `off`, `selected`, `effective`, `strict` | `off`. The three gate profiles follow the analysis: `selected` gives an inactive route no own-install obligation (recorded as `not_applicable`); `effective` waits for the forwarding action that will carry attracted traffic; `strict` requires the route's own installation |
| `fib.ack.boundary` | `control`, `kernel`, `hardware` | `kernel`, and `hardware` under `sonic`, because zebra runs with `--asic-offload=notify_on_offload` |
| `fib.ack.post_delay_s` | seconds | 0; 1 s under FRR suppress-fib-pending batching |
| `fib.ack.loss_action` | `withdraw`, `keep` | `withdraw` |

**FRR compatibility.** `bgp suppress-fib-pending` maps to the profile
`frr-suppress-fib-pending`: `strict` scope, limited as FRR documents it.
- Only newly peer-learned routes are gated. Later attribute or best-path changes
  and redistributed routes are excluded, and a later generic dataplane deletion
  does not cause a withdrawal (FRR 10.5 manual).
- The withdrawal predicate returns "withdraw" for any non-selected non-NORMAL path before it reaches the selected-`network`-static exemption (`bgp_route.h:779-801`); the exemption applies only when no such other path exists.
- When a better-administrative-distance route wins, the BGP route is withdrawn
  (`bgp_check_withdrawal`), so inactive export is effectively off.

The exact 10.5.4 and master behaviour is a lane fixture before it earns a
compatibility label.

**Open/R.** PrefixManager's readiness gate checks membership of programmed
prefixes (`PrefixManager.cpp:650`, withdrawal near line 710). It does not check
an exact next-hop generation, and the model reproduces that weaker gate for
Open/R.

**Acceptance.** Fixtures G01–G10 of the analysis, plus the coupled pairs to test
explicitly:
- FIB gate × inactive export;
- startup hold × GR;
- MED strategy × reflection;
- resolver source policy × route leaking (when VRFs land);
- weight source × missing weights.

---

## 6. Integration scenarios (IX)

These cover every deployment shape in the brief. Each runs a failure, reports
convergence timing (Open/R debounce, FIB delay, NHT, BGP process hold, MRAI)
and transient loss from placement, and compares against an oracle where one
exists.

1. **One IGP domain over every device** (Open/R), with iBGP over loopbacks in a
   full mesh, then through RRs. Next hops are indirect.
2. **Per-device domains (no IGP)** with eBGP per hop, as in RFC 7938:
   unnumbered, multipath-relax, next hops direct.
3. **Several IGP domains** (per AS or region), eBGP between them, iBGP inside.
   A failure in one domain reprocesses only that domain's BGP paths.
4. **Hop-by-hop iBGP RR with `next-hop-self force` instead of an IGP**, plus an
   overlay RR peering over loopbacks learned from BGP (BGP-over-BGP).
5. **A confederation**, first with an IGP domain per sub-AS (confed peering on
   link addresses, or on loopbacks with `ebgp-multihop` when not adjacent),
   then with one IGP
   across the confederation.
6. **Open/R multi-area** with BGP injected into Open/R (`PrefixType.BGP`, RIB
   feed `kind='all'`) and Open/R redistributed into BGP. A two-border case
   shows that the injection loops without tags and holds with them. The same
   prefix learned over BGP and redistributed locally is decided by
   `bgp.bestpath.redist_admin_distance`, run under both dialects.
7. **Per-node settings.** One fabric runs a network layer, a spine group layer
   and a single-leaf override, and `explain()` output is asserted. A mixed
   deployment puts the `sonic` preset (`frr-10.5`, traditional) on the leaves
   and `frr-modern` with the datacenter profile on the spines. It shows the
   timing effect of suppress-fib-pending and its advertisement effect: a
   selected but not installed path is withdrawn. A run-time settings change on one device re-resolves
   only that device, and its apply action is visible in the timeline.

### 6.1 Configuration sketches

Names are indicative.

```python
from netsim.agents import bgp, openr
from netsim.agents.common.selection import FlavorSpec
from netsim.model.igp import IgpDomain, oracle_igp_domains

# (1) One Open/R domain over the fabric; iBGP over loopbacks to two RRs.
net.settings.layer('fabric', values={'device.dialect': 'frr-modern', 'device.profile': 'datacenter'})
openr.deploy(net, devices=net.devices,                               # upstream defaults: RTT metric, soft-drain at boot
             enable_v4=True,                                          # upstream default is off
             areas=(openr.AreaConfig('0', include_interface_regexes=('eth.*', 'Po.*'),
                                     redistribute_interface_regexes=('lo.*',)),))
clients = bgp.PeerGroup('clients', remote_as='internal', update_source='lo',
                        route_reflector_client=True)
for rr in ('RR1', 'RR2'):
    net.add_agent(rr, bgp.BgpAgent(bgp.BgpConfig(
        asn=65000, cluster_id='10.0.0.100', peer_groups=(clients,),     # sugar: writes device and object layers
        neighbors=tuple(bgp.Neighbor(loopback(c), group='clients') for c in edge))))

# (2) No IGP: eBGP per hop over unnumbered links (RFC 7938), SONiC-like leaves.
net.settings.group('sonic-leaves', select=label('leaf'), priority=10, values={'device.presets': ('sonic',)})
for dev in fabric:
    net.add_agent(dev, bgp.BgpAgent(bgp.BgpConfig(
        asn=asn_of(dev),
        neighbors=tuple(bgp.Neighbor.interface(p, remote_as='external',
                                               activate=('ipv4-unicast', 'ipv6-unicast'))   # sonic: no default ipv4-unicast
                        for p in ports(dev)),
        redistribute=(bgp.Redistribute('connected', policy='LOOPBACKS'),))))

# (3) Two IGP domains on the fast oracle underlay, eBGP between them.
net.add_source(oracle_igp_domains((
    IgpDomain('as1', devices=as1, exclude=('ext.*',), instance=1),
    IgpDomain('as2', devices=as2, exclude=('ext.*',), instance=2))))

# (4) Hop-by-hop iBGP instead of an IGP: every router reflects to its neighbours.
for dev in fabric:
    net.add_agent(dev, bgp.BgpAgent(bgp.BgpConfig(
        asn=65000, networks=(loopback(dev),),
        neighbors=tuple(bgp.Neighbor(peer_address(dev, p), remote_as='internal',
                                     route_reflector_client=True, next_hop_self='force')
                        for p in ports(dev)),
        multipath=bgp.Multipath(ibgp=8, equal_cluster_length=True))))

# (5) Confederation: member AS 65001 of AS 100, peering with member AS 65002.
bgp.BgpConfig(asn=65001, confederation=bgp.Confederation(identifier=100, peers=(65002,)), ...)

# (6) Two Open/R domains on one border router (netsim_ext.multi_instance): disjoint interfaces.
net.add_agent('B1', openr.OpenrAgent(cfg_dc1, instance=0), name='openr-dc1')
net.add_agent('B1', openr.OpenrAgent(cfg_dc2, instance=1), name='openr-dc2')

# Decision flavors: by name with knob overrides; custom specs carry their own refs.
bgp.BgpConfig(..., decision=FlavorSpec.use('rfc4271'))
bgp.BgpConfig(..., decision=FlavorSpec.use('frr', always_compare_med=True,        # knobs are sugar for settings
                                            deterministic_med=True, dmed_semantics='classic'))
bgp.BgpConfig(..., decision=FlavorSpec(                  # a custom flavor: built-in steps plus a user step
    'lab-prefer-short-cluster', selection='elimination',
    steps=('local_pref', 'as_path_length', 'origin', 'med', 'ebgp_over_ibgp',
           ShortestClusterListFirst(refs=('RFC 4456 §9',)),   # frozen, pure, carries refs
           'igp_metric', 'router_id', 'peer_address'),
    refs=('NetSim plan §5.5',)))

# Settings are layered and overridable per node (section 2A); changes re-resolve only affected devices.
net.settings.layer('dc-defaults', values={'device.dialect': 'frr-modern', 'device.profile': 'datacenter',
                                          'bgp.timers': (3, 9)})           # a unit is written whole
net.settings.group('spines', select=label('spine'), priority=10,
                   values={'bgp.af[ipv4-unicast].maximum_paths': 64,
                           'bgp.bestpath.as_path.multipath_relax': True})
net.settings.device('leaf7', values={'bgp.neighbor[10.0.0.1].timers': (10, 30)})
print(net.settings.explain('leaf7', 'bgp.neighbor[10.0.0.1].timers'))      # value and its layer chain
# Changes are tree updates (CAUSE_CONFIG with changed keys and apply actions); commands are exec-only.
sim.at(30, lambda: net.settings.device('RR1', values={'bgp.neighbor[10.0.0.7].shutdown': True}))
sim.at(35, lambda: net.settings.device('R9', values={'device.dialect': 'frr-10.5'}))   # upgrade/downgrade: RESTART_INSTANCE
sim.at(40, lambda: sim.command('R3', 'openr', 'set_node_overload', True))
sim.at(50, lambda: sim.command('R1', 'bgp', 'clear_soft_in', '10.1.12.1'))
```

---

## 7. Verification

- **Invariants** (additions to `tests/test_invariants.py`):
  - protocol packages import only contracts, addressing, routing records,
    `state.PMap`/`record` and `agents/common`, checked at symbol level;
  - every step and profile value has refs, and every public rule function in
    the protocol packages carries `@ref` (section 13.8);
  - `docs/traceability.md` (RFC section → functions → tests) is fresh, and
    every cited section has a test;
  - plugins read configuration only from `ctx.agent_config`;
  - agent states, views and messages are frozen;
  - no module-level mutable state in protocol packages;
  - flavors are deterministic given inputs and history.
- **Locality and projections.** The locality harness runs for both agents, and
  guarded projections run per submodule.
- **Views only.** Tests assert on published views and on RIB/FIB/placement,
  never on agent state.
- **Property tests.**
  - KvStore merge convergence.
  - BGP under Gao–Rexford-safe policies converges to the unique stable state of
    a small static solver in the tests.
  - RR equals a full mesh, and a confederation equals a full mesh, where RFC 4456
    and RFC 5065 guarantee it.
  - The `rfc4271` flavor gives the same result for any arrival order.
- **Conformance.** The scenario list and the FRR lane goldens.
  - The lane needs privileged Docker and about 50–100 MB per FRR container, and
    polls until converged.
  - Order-dependent scenarios (RFC 3345 under `frr`, DISAGREE) get no goldens;
    they assert the set of admissible outcomes instead.
- **Performance.**
  - CI asserts operation counts, never wall time: `resolve_prefix` calls,
    entries touched, admission visits, NHT refreshes, agent runs per event.
  - Wall-time ratios live in slow, deselected benchmarks and passports.
  - Performance claims need old-versus-new runs on the same quiet machine.
- **Generators.** `hypothesis` is not a dependency. Property tests use seeded
  generators with fixed seeds and bounded sizes, each under 5 s, well inside the
  60 s per-test hang guard.
- **Determinism.**
  - CI runs 3.11–3.14 and 3.14t (`.github/workflows/python-test.yml:12`).
  - Dirty sets are processed in sorted order.
  - A test runs key scenarios under two `PYTHONHASHSEED` values and compares
    fingerprints and event streams.
- **Checks.** `make check-ci` (coverage ≥ 85%) and `make check-ft` for every
  slice; local checks do not replace CI.

---

## 8. Execution plan

1. **Design review.** Three internal reviewers on revision 1 (section 11), then
   Codex through the Superset CLI on revision 4. The Gate C reviewer terminal
   has ended, so a fresh Codex reviewer is used. Findings are applied before F0.
2. **F0** by the integrator: contract records, defaults and stubs, committed
   first as the skeleton. F0 includes the records F1 and F2 share (per-client
   outcome map, per-owner NHT maps, recursive-next-hop and group records,
   `FibGroupEvent`). It also includes the settings stubs every worker builds on:
   `NetworkState.settings`, `DeviceState.labels`, the `Network.settings` API
   skeleton, `CAUSE_CONFIG`, `Command` and `AgentNode.persistent`.
3. **Foundation workers** on isolated worktree branches. Merge order:
   F0 → F2a, F3, F4, F5, F7 (parallel) → F1a and RP1 → F1b → F2b and F8 → F2c,
   F1c and RP3 (parallel) → RP4. A design review gate sits after F1b, before F1c.
   F6 runs only if IX profiles require it.

   | Worker | Files owned |
   |---|---|
   | F1 (a, b, c) | `model/routing.py`, `model/forwarding.py`, `model/lpm.py`, `model/derive.py` (FIB kind, `bump_epochs`, NHT refresh selection), `runtime/timeline.py`, `tests/test_fingerprints.py` |
   | F2 (a, b, c) | `runtime/agents.py`, `validate_admitted` and the `PMap` builder in `model/state.py`, NHT delivery, `installed` mode and `via_metric` computation in `model/nht.py` (reading F1b's recursive-next-hop table), F0 delivery in `runtime/simulation.py` |
   | F3 | `runtime/transport.py`, `runtime/channels.py` |
   | F4 | `model/igp.py` |
   | F5 | `agents/common/`, `tests/agents/harness.py` |
   | F8 | programming records in `model/forwarding.py` and the FIB kind in `model/derive.py` (with the F1 owner); completion notifications in `runtime/agents.py` (with the F2 owner) |
   | RP1 | `netsim/model/route_policy/` (types, compiler, evaluator, capability table) and `tests/model/route_policy/` |
   | RP3 | retained submission and admitted views and the `RIB_ADMISSION` hook in `model/routing.py` (coordinated with F1b's submission boundary) |
   | RP4 | `RESOLUTION_IMPORT` scopes in the resolver and NHT, and `FIB_INSTALL` exclusion on F8 |
   | F7 | the `netsim/settings/` engine (schema, layers, resolution, inheritance, provenance, documentation generators), the composition-root catalog, the `native` dialect with `device.*` and `zebra.*` fragments, NetGraph label translation in `adapters/ngraph.py`. The `NetworkState.settings` and `DeviceState.labels` stubs and the `Network.settings` skeleton come from F0 |

   `connected_only` parity touches `_CandidateResolver` in `routing.py`; the
   F1 owner makes that change and F2 supplies the tests. Integration uses the
   extended fingerprints (F1a) as the equivalence oracle, runs full checks on
   both interpreters, and ends with an adversarial review round.
4. **Two tracks.** Every protocol slice has separate functional and performance
   exits, so functional work never waits for F1c or F2c.

   | Slice | Needs (functional) | Needs (performance exit) |
   |---|---|---|
   | OR1, OR2 | F0, F2a, F5, F7 | F2c |
   | OR3 | OR2, F2b | F1b, F2c |
   | OR4 | OR3 | F2c |
   | OR5 | OR3, RP1 (F2a commands and persistence, F2b RIB feed) | F2c |
   | OR6 | OR5 | F1c, F2c |
   | BG1 | F5, F7 | – |
   | BG2 | BG1, F2a, F3 | F2c |
   | BG3 | BG2, F2b, F4, RP1 (import hook) | F1c, F2c |
   | BG4 | BG3, RP1, F8 (suppress-fib-pending, ACK gate, inactive export) | F1c, F2c |
   | BG5–BG6 | BG3 | F1c, F2c |
   | BG7 | BG6 | – |

   - OR1–OR6 own `agents/openr/`.
   - BG1–BG7 own `agents/bgp/`, `adapters/frr.py` and the BGP tables in
     `adapters/sonic.py`.
   - Reviews run after OR3 and BG4 and at each track's end.
5. **IX**, then README and reference documentation, then a final review.
6. **Orchestration** as in Gates B and C:
   - Codex xhigh workers created with `superset workspaces create --local
     --project <NetSim id> --branch <slice> --base-branch main --agent codex
     --effort xhigh --prompt ...`;
   - progress read with `superset terminals read`;
   - findings routed back to the owning workers;
   - commits and pushes only when the user asks.

---

## 9. Risks and open questions

- **FRR sorted-list semantics** (deterministic-MED, no re-sort on withdrawal)
  rest on source reading. The lane confirms them, and both `dmed` semantics are
  offered.
- **Master is a moving target.** `frr-modern` resolves to the immutable pin
  `frr-master-f1d7bec`. Z5 is quarantined until a black-box run, and N6 is
  revisited with UCMP in BG8. At 10.8.0 the per-subsystem diff review repeats, and the dialect
  table changes only by data rows.
- **Dialects do not emulate bugs.** A 10.5.4 lane run will disagree wherever
  10.5.4 is buggy (section 2B.1). Those disagreements are triaged against the
  divergence list, and a `quirk.*` flag is added only under the 2B.2 rule.
- **Other FRR quirks** are recorded as named deviations:
  - the lower neighbour address wins, contrary to the documentation;
  - `bandwidth ignore` still weights;
  - a static route passes the connected check, yet the non-recursive install
    over it stays inactive;
  - no send-side check for a next hop equal to the receiver's address;
  - RFC 8212 exempts confed peers.
- **Open/R route metric** is a declared modelling choice (`metric_mode`) that
  decides whether hot potato over Open/R is observable.
- **Open/R defaults** (RTT metric, soft-drain at boot, empty default area,
  `enable_v4` off, the `"0"` wildcard) make naive comparisons fail. Profiles and
  deploy helpers handle this.
- **SONiC's FRR.** The template is verified (`bgpd.main.conf.j2`, saved in the
  research folder: suppress-fib-pending, no RFC 8212, `maximum-paths 64`, GR on
  ToR only). The patch series still needs a review for behaviour changes, for
  example the 10.5.5 backports it may carry.
- **Python performance** at 100k prefixes × many peers. Passports set
  expectations; native kernels stay deferred.
- **Hierarchical FIB.** Group-id semantics change; SR entries migrate last.
- **Licensing.** No FRR code, and topotest data is not vendored.
- **No multi-access LANs.**

---

## 10. Deferred (named extension points)

- **BGP (BG8 and beyond):**
  - `cisco-ios`, from Cisco document 13753: weight; local origin; oldest eBGP
    path; router id before cluster length.
  - `junos`, from Juniper "Understanding BGP Path Selection": no weight;
    strictly internal paths first; oldest external path; router id before
    cluster length; MED grouped by neighbouring AS unless
    `cisco-non-deterministic`.
  - add-path (RFC 7911).
  - graceful restart, EoR and update-delay (RFC 4724, 8538).
  - BFD as an agent publishing views (RFC 5880, 5883).
  - link-bandwidth UCMP.
  - aggregates.
  - dynamic neighbours.
  - SR color steering (RFC 9256 §8) and SRv6 services (RFC 9252, which needs
    VRFs).
  - an analytical BGP solver.
  - RFC 9107 optimal route reflection (absent in FRR too).
- **Open/R:** KSP2 and UCMP (absent upstream); the RIB policy API; an RTT step
  detector model.
- **Common:** a control-plane CPU model; incremental SPF; native kernels by
  profile.

---

## 11. Review log

**Revision 1 → 2 (2026-09-27).** Three internal adversarial reviews, each
checked against source; spot checks reproduced by the integrator.

- **Architecture and contract fit** (16 findings; 1 P0, 11 P1, 4 P2, all
  accepted):
  - P0: configuration becomes tree state (D11), because the runtime reads
    `AgentNode.config`, and commands become exec-only.
  - The RIB feed has a precise definition (processed epoch, installed rows,
    snapshots, coalescing, kinds, tags).
  - Change-key semantics per receipt.
  - `RouteView` split.
  - `run_delay > 0` for protocol profiles.
  - Flavors become frozen specs, since `validate_immutable` rejects callables;
    `Dest` history is explicit.
  - Open/R worklist with programming-gated edges.
  - The idle claim is restated.
  - Listener accept tables.
  - Views (G10).
  - Multi-instance becomes `netsim_ext`, separated by interface ownership.
  - Lazy accessors from `LocalContext`, and NHT costs (G5).
  - Module projections, RNG streams, timer multiplexing.
  - The iBGP-on-link row corrected.
  - Restart semantics (D12).
- **Protocol fidelity** (25 findings; 2 P0, 13 P1, 10 P2, all accepted):
  - P0: the FRR pin is frr-10.5.4, where step 0 is absent and the LLGR_STALE
    pre-step is present.
  - P0: MED-oscillation expectations are per flavor.
  - The sorted-list rules are written down.
  - The `rfc4271` flavor is completed (§9.1.1, §9.1.2, RFC 5065 §5.2 and all
    four §5.3 rules).
  - `MULTIPATH_NUM` per profile (16 / 256 / 514).
  - Fast external failover.
  - The F3 TTL test is corrected; NHT gating moves to BG2.
  - Confed TTL 1.
  - Router-id rule.
  - Receive-side AS_PATH checks.
  - Route-map delay timer, soft reset, `maximum-prefix`.
  - Multi-instance labelled.
  - Open/R route metric declared as a modelling choice.
  - `bestNodeArea` default rule.
  - Oracle-equivalence configuration.
  - Scenario 6 expected set.
  - Idle-hold doubling.
  - zebra queue simplification recorded.
  - Unnumbered simplifications recorded.
  - Send-side MED, LOCAL_PREF and link-local rules.
  - Echo wording.
  - Area `"0"` warning.
  - RTT floor.
  - Restart semantics.
  - Research report corrections appended as errata sections:
    `research-frr-decision.md` (version pin, finding 1 holds for bare builds
    only, missing fast external failover and confed TTL);
    `research-frr-rr-confed.md` (§2.6 row 9, the §3.3 RFC section, idle hold);
    `research-openr.md` (§6 step 4, distance source).
- **Scale, tests and execution** (13 findings; 3 P0, 8 P1, 2 P2, all accepted;
  the P0s reproduced by the integrator):
  - P0: the full resolver is order-dependent (G12), so F1a comes first, with
    fingerprints extended beforehand.
  - P0: `depends_on` is transitive (G13), so F1b makes the FIB non-transitive,
    with a refined group key and reference-counted group garbage collection.
  - P0: the missed Simulation-path O(table) costs (G14): persistent FIB storage,
    `diff_pmap` timeline diffs, `FibGroupEvent`, NHT refresh by watch index.
  - The ≤ 5 ms target is scoped to the FIB step, with both harnesses stated.
  - `zebra.py` suppresses identical rows.
  - Exact shard-identity admission rule and guard tests; target ≤ 100 µs at
    100k with nested maps.
  - Lazy context without a cache; per-client outcome maps and per-owner NHT maps
    in F0.
  - GC multiplier and heap counts in passports.
  - Cost model; passport (b) re-scoped.
  - Operation-count assertions in CI; seeded generators; `PYTHONHASHSEED`
    determinism; CI matrix corrected.
  - FRR lane needs; no goldens for order-dependent scenarios.
  - Merge order F0 → F3/F4/F5 → F1a → F1b → F2 ∥ F1c, file ownership fixed,
    functional versus performance exits per slice.
  - F6 for the conservative downstream scans (G15).
  - Watch-index range queries by bisect.

**Revision 3 → 4 (2026-09-27).**

- **Verification pass on revision 3** (7 P1, 14 P2, all applied):
  - F2 split into F2a, F2b and F2c, with real functional dependencies;
  - G2 and G3 numbers made consistent;
  - the F1 Simulation target scoped to the FIB share;
  - the RIB feed now carries metric-only and tag-only changes, with the
    `kind='all'` trigger defined;
  - citation convention stated, with 10.5.4 citations for `peer_ttl_update` and
    fast external failover;
  - SONiC `maximum-paths 64` capped by 514;
  - the confed loopback statement corrected;
  - "entry criterion" reworded as a performance exit;
  - `FlavorSpec.use` defined, the no-cache flavor resolution, a custom-flavor
    example;
  - per-watch coalescing;
  - non-BGP import-check;
  - scenario 4 static and `disable-connected-check` cases;
  - `enable_v4` in the Open/R example;
  - G12 wording;
  - `LOOP_DETECTED` in `RowNotice`;
  - NHT `installed` mode ownership;
  - the confed-learned → iBGP send row.
- **User direction (2026-09-27):** target the most modern FRR and keep a precise
  record of 10.5 differences; generic differences become settings; every setting
  is overridable per node; plan for maintainability.
  - Three per-subsystem diffs of frr-10.5.4 against master, each difference
    attributed to its release through the full history
    (`frr-diff-decision-nht.md`, `frr-diff-advertise-policy.md`,
    `frr-diff-sessions-defaults.md`).
  - Section 2B: findings; dialects `frr-modern` (master `f1d7bec` with Z5 and
    N6 quarantined) and `frr-10.5` (defaults and choices, not bugs); the quirk
    rule; the settings table; profile defaults; FRR's defaults and inheritance
    machinery mirrored.
  - Section 2A: the settings system (schema, dialects, layers in the tree,
    FRR inheritance, typed interned resolution with provenance, apply actions,
    test-enforced rules, adapters, failure modes), delivered as slice F7.
  - Corrections:
    - `deterministic-med` changed in 10.4.0, not 10.5.0;
    - "withdrawn first" and "MRAI gates withdrawals" are modern-only;
    - martian NEXT_HOP is treat-as-withdraw in modern;
    - a peer AS equal to the confed id is iBGP in modern;
    - GR-stale paths with dead next hops are deleted in modern;
    - SONiC's template enables suppress-fib-pending, now in BG4 scope.
- **Review of sections 2A and 2B** (2 P0, 15 P1, 7 P2; all applied; the SONiC
  traditional-profile claim verified: no `-F`, no `frr defaults` line):
  - P0: precedence is defined per (object, key), with dialect, profile and
    presets as device meta-keys resolved first, and FRR inheritance over
    objects;
  - P0: a single write path: the resolver is the only writer of `AgentConfig`
    and the `DeviceConfig` settings fields, `add_agent` configurations are
    sugar, and a `debug_validate` re-resolution check;
  - interning via record reuse and per-call tables, not identity memos;
  - selectors use `DeviceState.labels`;
  - a `native` dialect keeps today's defaults and fingerprints;
  - the Apply enum is completed (`DEPLOY_ONLY`, `CAPABILITY_ELSE_RESET`,
    sort-changing `SESSION_RESET`, `SOFT_OUT` semantics);
  - `since` and `allowed_values_by_dialect` replace per-dialect rejection;
  - dialect ids are immutable pins behind aliases, and `frr-10.7` is dropped;
  - only Z5 is quarantined; N6 and the link-bandwidth clamp are not quirks;
  - `zebra.rib_tiebreak` is deferred to F1a;
  - suppress-fib-pending withdraws selected but not installed paths;
  - the `sonic` preset corrected: traditional profile, conditional
    `maximum-paths`, role-conditional lines written by the adapter, GR on ToR as
    a divergence, ASIC-offload notification;
  - distribution replaced by ordered presets, and `lab` becomes a preset;
  - partial unit writes rejected;
  - the whole `AgentConfig` is resolved, including run-time fields;
  - non-settings and lints listed;
  - `deterministic_med` boolean kept, with `dmed_semantics`;
  - slice ownership fixed (F0 stubs, F2a, F1 timeline, BG7 adapters, fragments
    in BG1 and OR1);
  - enforcement rules rewritten as an AST check and a key-field bijection with
    `@covers`;
  - DefaultsSpec joint first-match with no gates below 10.5;
  - `mrai_withdrawals` wording and instance scope;
  - structured values replace;
  - provenance on demand;
  - the key grammar;
  - the composition root;
  - report conflicts recorded (N1 over S24, the 0–10000 ms range, AP-20 over
    S18, UPA receive marking).



**Revision 4 → 5 (2026-09-27): integration of the reviewed routing-policy plan.**

Sources:
- `NetSim/docs/plans/routing-policy.md`, revision 4, with
  `routing-policy-reviews.md` (36 findings), written by a separate session.
  Both are untracked in the NetSim repository; committing them is the user's
  decision.
- `RFCs/FIB-ACK-AND-INACTIVE.md`.
- `RFCs/PER-NODE-SETTINGS-PLAN.md`.

**Adopted as written:**
- the shared typed language and one evaluator in the model layer (D13, section
  5.8), replacing the BGP-local route-map evaluator;
- four flows, explicit fallback, absent versus empty binding,
  `ORIGINAL`/`WORKING` match input;
- the closed field and action catalog, with owner-supplied `PolicyAccess`;
- the capability table per point;
- no regex, loops, calls or callbacks in the core;
- digest-pinned revisions;
- retained submission views for RIB admission, and the single RIB submission
  boundary with its callsite audit (F1b, RP3);
- desired versus installed FIB with generation-guarded completions (F8, D14);
- owner-defined reevaluation replacing the fixed 5 s delay (`REEVALUATE`), with
  import replay needing retained input or ROUTE-REFRESH, else
  `needs_session_reset`;
- update groups keyed by compiled fingerprint plus peer facts;
- `RoutePolicyRef` distinct from SR `PolicyRef`;
- node-local client profiles (P0), which moves client profiles from the
  non-settings list into per-node settings;
- fixtures E01–E24;
- the FIB acknowledgement gate and inactive-export contract with fixtures
  G01–G10.

**Corrected during integration, checked in FRR source:**
1. **`ip protocol P route-map`.** It is evaluated per next hop inside zebra's
   next-hop activation (`zebra_nhg.c:2880-2921`). A deny deactivates that leg,
   and a route with no active leg is ineligible, so zebra selects the next
   candidate. The routing-policy plan's native `FIB_INSTALL` (whole action, no
   fallback) cannot represent it. The FRR construct maps to `RIB_ADMISSION`
   with a new `per_nexthop=True` mode, and `FIB_INSTALL` stays native only.
2. **`ip nht P route-map`.** It filters the next hops of the resolving route
   zebra has already chosen, for one client protocol. If all are filtered, the
   client is told "filtered/unresolved" with no less-specific fallback
   (`zebra_rnh.c:515-576`), and forwarding recursion is unaffected.
   `RESOLUTION_IMPORT` gains an explicit scope (`nht` or `forwarding`), and the
   FRR adapter uses `nht` with `fallthrough='never'`.
3. **Inactive export default.** FRR advertises its BGP best path regardless of
   the zebra winner unless suppress-fib-pending, in which case
   `bgp_check_withdrawal` withdraws non-installed selected paths
   (`bgp_route.h:771-806`). So `bgp.export.inactive` defaults to True in the FRR
   dialects and False in `native`.
4. **SONiC completion boundary.** SONiC's zebra runs with
   `--asic-offload=notify_on_offload`, so the `sonic` preset uses
   `fib.ack.boundary='hardware'`.
5. **Anchored AS-path regexes.** Common SONiC and FRR configurations use
   anchored AS-path regexes. The FRR adapter lowers the anchored single-ASN
   shapes to typed predicates instead of rejecting every regex; other patterns
   are rejected with a report.
6. **FRR deny entries with `set` clauses.** FRR ignores the sets. The adapter
   drops them and records a deviation, because native `REJECT` terms cannot
   carry actions.
7. **Reevaluation defaults per dialect.** The FRR dialects use 5 s, the
   `route-map delay-timer` default. `native` uses 0 s. FRR's delay-timer of 0
   maps to `manual`.

**Scheduling.**
- P0 goes to F0 and F7.
- P1 becomes RP1 in M1.
- P2 goes to BG3 and BG4.
- P3 becomes RP3 and P4 becomes RP4, both in M2, with the new F8.
- P5 goes to BG7.
- P6 goes to M5.
- Dependencies, file ownership, milestones and roadmap signatures were updated
  accordingly (sections 3, 8 and 12).
- Scenario 9 now includes E01–E24's BGP-side fixtures; new scenario 13 covers
  installation gating.
- Sections 13.11 and 13.12 answer the two new requirements.


**Revision 5 → 6 (2026-09-27): scale review with experiments and prototypes**
(section 14; scripts in `scale-experiments/`).
- Measured: 1.5 KB and 84 µs per recursive row; quadratic build (G17); 27 KB
  retained and 160–200 µs per idle agent run (G18, G19); 25 KB per device with
  no routes (G20); `PMap` admission 3.15 s per change at 1M; DES core 0.9 µs
  per event.
- Proved: linear build by indexing the locator check; 1.8 KB retention without
  the RNG commit; shard-identity admission 1.5 ms at 1M, hence a changed-key
  log; a columnar hierarchical FIB at 13 B per route with 5 µs underlay changes;
  a struct-of-arrays Loc-RIB at 17 B per path; columnar LPM rejected.
- Decided: S0 scale hygiene first; zero-commit idle runs (runtime bookkeeping
  out of `AgentNode`); columnar FIB and BGP payloads with interned attributes;
  lazy analytical mode at 100k devices; the honest passports P-A, P-B, P-C;
  streamlining (F2a into F0, F7 in two steps, RP4 and parts of F8 deferred,
  JSON codec dropped, lane on two images).


**Revision 6 → 7 (2026-09-27): Codex adversarial review of revision 6**
(`codex-review-rev6.md`; 1 P0, 17 P1, 4 P2; all accepted; source claims
re-verified by the integrator; the P0 answered with `proto_chunked.py`).
- P0: packed storage gets an immutable persistent contract (`PackedTable`,
  §15.1): 16 B per row, 10 µs per single-row update, 0.1 ms admission.
- Passports re-budgeted with every index and component (P-A ≤ 4 GB, P-B
  ≤ 3 GB); measurement labels corrected (DES 1.5 µs per timeout; `RowKey`, not
  `Route`; allocation increments); the columnar-LPM rejection withdrawn.
- Zero-commit publication becomes Gate C slice C6; the `PMap` changed-key
  certificate and `PackedTable` become slice S1; the SRv6 consumer copy joins
  S0; lazy analytical mode becomes slice A1 with a query contract.
- Per-leg cycle rule (F1a); `ip protocol` as an activation-stage filter; scope
  in shared recursive keys; no import-policy memoization.
- Root settings delta and dump of explicit intent; one action plan per
  configuration transaction; preset precedence examples.
- Group versions and ERROR completion in minimal F8; Open/R sync completion
  including the empty sync; scoped listener accept identity.
- BGP corrections: reinstall guard, ORIGINATOR_ID only if absent and outbound
  policy next-hop rewrite, confed step deferral under peer-type relax,
  suppress-fib-pending predicate order, multipath ceiling as package data.
- Streamlining: two explicit selection functions instead of a flavor
  interpreter; smaller settings start; §15.9 is the single authoritative
  dependency table; readiness: S0 and additive F0 now, everything else after
  the `PackedTable` and C6 gates.


**Revision 7 → 8 (2026-09-27): second Codex review** (`codex-review-rev7.md`;
1 P0, 14 P1, 1 P2; all accepted; body contradictions fixed in place; §16 records
the decisions).
- P0: positional identity across compaction; the first `PackedTable` is
  append-only with logical or generation-checked references and a bound
  change certificate.
- Index choice per device class after update benchmarks; the common RIB
  assigned to the X owner; BG3 without CSR; budgets as hypotheses with
  per-component reporting.
- Certificates as immutable evidence; S1 split into S1a and S1b.
- C6 publication seam before root observers; `initialized` stays in the tree;
  per-stream PRNG counters (sent to worker W3).
- Per-leg witness recurrence; activation filter on the original next hop.
- Route and group obligations; sync operation identity with empty and total
  failure; per-key feed coalescing with bounded payloads.
- F0 owns the root settings delta; preset precedence decided; dumps keep
  explicit intent; one action plan per transaction.
- RFC 8212 discards and suppresses rather than refusing.
- §15.9 edges and owners amended (§16.9); readiness gates must pass, not
  merely exist.


**S0 delivered (2026-09-27)** on `main` locally: see §17. Two Codex review
rounds ran in parallel with the implementation (§15, §16).

---

## 12. Implementation roadmap: how each slice is built

This section turns the design into buildable work. Each slice lists files,
the key types and function signatures, the tests written first, and the exit
check. Signatures are Python and indicative, but binding in shape: pure
functions over frozen records, no runtime objects in protocol modules. Size
estimates are rough lines of code (implementation + tests) for scheduling only.

### 12.1 Milestones

| Milestone | Slices | Gate to pass | Rough size |
|---|---|---|---|
| M0 skeleton | F0 | contract tests green, all existing tests green, stubs importable | 0.8k |
| M1 foundation | F1a, F2a, F3, F4, F5, F7, RP1 (parallel after F0) | resolver order tests, extended fingerprints, settings engine on `native` with fingerprints unchanged, transport TTL/accept tests, toolkit unit tests, route-policy truth tables (E01–E03, E10, E12, E19–E22), the two-node client-profile regression passing; review round | 8k |
| M2 scale foundation | F1b → F2b and F8, then F1c ∥ F2c ∥ RP3, then RP4; design gate before F1c | op-count assertions and G1–G5 ratio benchmarks; full-vs-incremental oracle; stale-ACK and programming tests (G01–G04, E09, E14); RIB admission (E04, E13); resolver and FIB policy (E05, E06, E11) | 8k |
| M3 protocol cores | OR1–OR3 ∥ BG1–BG3 | Open/R oracle equivalence (single area); BGP decision tables, session matrix, direct and indirect next hops; review round after OR3 and BG3/BG4 | 9k |
| M4 protocol breadth | OR4–OR5 ∥ BG4–BG6 | multi-area, drain; outbound, policy, RR, confederations; scenarios 1–9, 11, 12 | 7k |
| M5 conformance and integration | OR6, BG7, IX | passports, FRR lane report, IX 1–7 | 5k |
| M6 release | docs, README, final review | generated `docs/settings.md`, reference pages, review with no open P0/P1 | 1k |

Each milestone ends with an integration merge on main (full `make check-ci` and
`make check-ft`), an adversarial review round (internal reviewers, optionally
Codex), and a memory/plan update. Nothing is pushed without the user's request.

### 12.2 Test harness (built once, in F5 and F7, used by every slice)

```
tests/
  agents/
    harness.py        locality guard, submodule projection proxy, twin comparison, view assertions,
                      op counters (resolve_prefix calls, admission visits, agent runs per event)
    topo.py           declarative fixtures: build(TopoSpec) -> Network  (ring, clos(k), diamond, random(n, seed),
                      numbered | unnumbered | dual-stack, labels for settings selectors)
    openr/            test_spark.py, test_kvstore.py, test_decision.py, ..., test_oracle_equivalence.py
    bgp/              test_aspath.py, test_decision_frr.py, test_decision_rfc4271.py, test_sessions.py,
                      test_nexthop.py, test_outbound.py, test_rr.py, test_confed.py, scenarios/
  settings/           test_schema.py, test_precedence.py, test_inheritance.py, test_apply.py, test_docs_fresh.py
  model/              test_resolver_order.py, test_fib_hierarchical.py, test_resolver_incremental.py
tools/frr_lane/       render.py (frr.conf + containerlab topology), run.sh, collect.py, normalize.py, compare.py
```

Test layers, cheapest first:

1. **Pure module tests.** Feed frozen records into one submodule and assert the
   returned records. No `Network`, no runtime. Most protocol logic is covered
   here (decision tables, merge rules, FSM transitions, AS_PATH vectors).
2. **Agent tests on small fixtures.** `topo.build(...)` plus agents plus
   `Simulation`, asserting published views, RIB/FIB and placement only.
3. **Scenario tests.** Named scenarios (section 5.11, section 6) as Python data:
   topology, layers, events, expected views at given times.
4. **Equivalence tests.** Protocol twin against the domain oracle; incremental
   resolver against the full resolver; `rfc4271` flavor against permuted
   arrival orders.
5. **Seeded property tests** (no `hypothesis`): fixed seeds, bounded sizes,
   each under 5 s.
6. **Performance.** Op-count assertions in CI; wall-time ratio benchmarks and
   passports marked slow and deselected.
7. **FRR lane** (opt-in, Linux with Docker): `tools/frr_lane/` renders the same
   scenario for FRR, collects `show ... json`, normalizes, and writes goldens
   that the scenario tests replay without dependencies.

Every test that pins a defect fails on the old code (AGENTS.md); each new
setting has an `@covers('key')` test (rule 5).

### 12.3 Foundation slices

**F0: contract and settings skeleton** (integrator).

- `netsim/model/contracts.py`
  ```python
  CAUSE_CONFIG = 'config'
  @record class Command: time: float; name: str; payload: Any; generation: int | None = None
  @record class WatchOp: kind: str; af: int; sources: frozenset[ClientId] | None; watch: str  # kind: 'selected'|'all'
  @record class RouteChange: watch: str; af: int; epoch: int; upserts: tuple[Route, ...]; removals: tuple[RowKey, ...]
  @record class RowNotice: key: RowKey; status: str; reason: str | None; zapi: str
  # NhtKey.mode: str = 'rib' ('rib' | 'installed' | 'exact');  NhtResult.via_metric: int | None = None
  # AgentOutput: views: PMap[str, Any] = empty; persistent: Any = None; watches: tuple[WatchOp, ...] = ()
  # AgentNode: views, persistent;  SessionOp: ttl: int | None = None; min_ttl: int | None = None; kind 'set_opts'
  # Endpoint.address: int | None  (None = wildcard, listen only);  Listener.accept: PMap[RemoteId, AcceptOpts]  # RemoteId(af, address, interface, interface_generation | None)
  ```
- `netsim/model/state.py`: `NetworkState.settings: Any = None` (the layers
  record, F7 fills it), `DeviceState.labels: frozenset[str] = frozenset()`.
- `netsim/model/network.py`: `Network.settings` property returning a
  `SettingsAPI` whose methods (`layer`, `group`, `device`, `explain`) raise
  `NotImplementedError` until F7; `Device.label(*names)`.
- `netsim/runtime/simulation.py`: `Simulation.command(device, agent, name,
  payload) -> None` (stub raising until F2a).
- Shared F1/F2 records: `ResolverOutcome.rows: PMap[ClientId, PMap[RowKey,
  RowOutcome]]` accessor shim over today's flat map; `RecursiveNexthop`,
  `GroupKey`, `FibGroupEvent` record definitions.
- Tests: `tests/model/test_contract_f0.py` (construction, validation,
  immutability of every new record; defaults keep old behaviour).

**F1a: order-independent resolver** (`routing.py`, `tests/test_fingerprints.py`).

1. Extend the fingerprint (outcomes, MAC, encap, adjacency AF, NHT answers,
   selection, PENDING) and add recursive, cyclic, cross-family, fallthrough,
   resolve-via-default and SR scenarios; record baselines.
2. Tests first (`tests/model/test_resolver_order.py`): the A↔B cycle yields
   `LOOP_DETECTED` for both under every order; a depth-4 chain resolves the same
   with and without unrelated deeper members; a seeded fuzz resolves 200 random
   RIBs in 20 random prefix orders and asserts identical outcomes.
3. Implementation: `_Resolver.resolve_prefix(af, prefix)` computes chain depth
   per recursive next hop (`depth(nh) = 1 + depth(resolving prefix)`), never
   memoizes a truncated result, excludes only the prefix itself, and marks
   a leg whose only witnesses close a cycle `LOOP_DETECTED`, while the route's
   other legs keep their finite witnesses (per-leg rule, §15.4 and §16.4).
4. Fix `DeviceContext.rib` truthiness (`derive.py:728-729`).

**F1b: hierarchical, persistent FIB** (`forwarding.py`, `lpm.py`, `routing.py`,
`derive.py`, `timeline.py`, `nht.py` refresh selection).

```python
@record class RecursiveNexthop: key: tuple[int, int, str | None, int | None, bool, bool]  # (af, address, interface, if_gen, connected_only, via_default)
                                legs: tuple[tuple[Adjacency, int], ...]   # (leg, depth of its witness)
                                via_prefix: Prefix | None; via_source: ClientId | None
                                via_metric: int | None; deps: DependsOn
@record class GroupKey: af: int; nexthops: tuple[Nexthop, ...]; self_prefix: Prefix | None
class PersistentPrefixTable(Generic[T]): set(net, plen, v) -> Self; remove(net, plen) -> Self; lookup(addr) -> ...
                                         diff(other) -> Iterator[tuple[Prefix, T | None, T | None]]
class WatchIndex: add(af, address, key) -> WatchIndex; covered_by(af, prefix) -> Iterator[key]   # bisect ranges
def resolve_fib(rib, ctx, policy, version, processed_epoch, old=None) -> tuple[Fib, ResolverOutcome, FibChanges]
```

Tests: `tests/model/test_fib_hierarchical.py` (group reuse by key, refcount GC,
self-covering key split, IGP change touches one recursive entry and no FIB
entry, flattened adjacencies equal the old resolver's), timeline
`FibGroupEvent` test replacing `test_timeline.py:141-143`, NHT selective
refresh counts.

**F1c: incremental resolution** (`routing.py`, FIB kind in `derive.py`).

```python
@record class Dirty: prefixes: frozenset[Prefix]; interfaces: frozenset[str]; neighbors: frozenset[tuple[str, int]]
                     recursive: frozenset[tuple]      # RecursiveNexthop keys
def resolve_fib_incremental(rib, ctx, policy, old_fib, old_outcome, dirty, *, fallback_ratio=0.2
                            ) -> tuple[Fib, ResolverOutcome, FibChanges]
```

Tests: `tests/model/test_resolver_incremental.py` runs the design-of-record
matrix and a seeded random event stream, asserting equality with the full
resolver after every event; op-count assertions (entries touched, recursive
entries recomputed).

**F2a: configuration, commands, views** (`runtime/agents.py`,
`runtime/simulation.py`, `model/network.py` internal `configure_agent`).

- `AgentRuntime.deliver_command(device, agent, Command)` with synchronous
  `plugin.validate_command(name, payload, agent_config)`.
- `AgentRuntime._publish` stores `views` and `persistent`; `ctx.view(agent,
  name)`; subscriptions on `('agents', name, 'views', key)`.
- `CAUSE_CONFIG` carries `changed_keys: frozenset[str]` computed by F7.
- Tests: `tests/runtime/test_agent_config.py` (config change without new
  generation, reset keeps latest config, bad command rejected at submit, run-time
  command error reported in a view, stale-generation command dropped and
  counted, views readable by a second agent on the device, persistent survives
  reset unless purged).

**F2b: RIB feed, owner notifications, NHT installed mode** (FIB kind hook,
`model/nht.py`, `runtime/agents.py`).

```python
def route_changes(dev_old, dev_new, af, fib_changes, rib_changed) -> tuple[tuple[WatchOwner, RouteChange], ...]
def row_notices(outcome_old, outcome_new, client) -> tuple[RowNotice, ...]        # diff_pmap of the client sub-map
def resolve_installed(ctx, key) -> NhtResult                                          # reads RecursiveNexthop table
```

Tests: `tests/runtime/test_rib_feed.py` (selected vs all, metric-only and
tag-only changes, PENDING suppression, snapshot on registration and on reset,
per-watch coalescing, own-client exclusion, two-border tag loop),
`test_row_notice.py`, `test_nht_installed.py` (installed answer lags RIB
answer by `fib_delay`; `via_metric` from a BGP resolver equals its MED).

**F2c: runtime scale** (`runtime/agents.py`, `model/state.py`).

- Lazy context accessors backed by `RibState.clients` and per-client outcome
  maps; interface-view cache holding strong node references.
- `validate_admitted` shard-identity rule (section 3, F2) and a `PMap`
  visited-node counter for tests.
- Tests: guard tests of section 3 F2; G2–G5 op-count assertions; ratio
  benchmarks (slow).

**F3: transport** (`runtime/transport.py`, `runtime/channels.py`).

```python
def listen(device, agent, gen, endpoint: Endpoint, scope: frozenset[str] | None,
           accept: PMap[RemoteId, AcceptOpts]) -> None | Rejection   # RemoteId scoped by ingress interface for link-local
def _path(state, device, local, remote, connection, *, ttl: int, min_ttl: int | None) -> _Path  # hop-limited trace
```

`agents/common/net.py`: `source_address(ctx, af, destination) -> int | None`.
Tests: the F3 exit list (section 3) in `tests/runtime/test_transport_ttl.py`.

**F4: domain oracle** (`model/igp.py`).

```python
@record class IgpDomain: name: str; devices: frozenset[str] | None; include: tuple[str, ...] = ('.*',)
                         exclude: tuple[str, ...] = (); passive: tuple[str, ...] = (); instance: int = 0
                         distance: int = 110; metric_mode: str = 'interface'
def oracle_igp_domains(domains: Sequence[IgpDomain]) -> RouteSource
```

Tests: two-AS isolation, passive interfaces, single-domain fingerprint equality.

**F5: protocol toolkit** (`netsim/agents/common/`).

```python
# selection.py
class DecisionFlavor(Protocol):
    name: str; refs: tuple[str, ...]
    def compare(self, new: PathView, exist: PathView, ctx: DecisionContext) -> Verdict: ...
    def select(self, dest: Dest, changed: tuple[PathKey, ...], ctx: DecisionContext) -> Selection: ...
    def multipath(self, dest: Dest, best: PathKey, ctx: DecisionContext) -> tuple[PathKey, ...]: ...
BUILTIN_FLAVORS: Mapping[str, DecisionFlavor]      # 'frr', 'rfc4271'; a deployment may pass more by name
# spf.py
def ecmp_spf(adjacency: Mapping[int, tuple[tuple[int, int, int], ...]], source: int) -> SpfResult  # (peer, metric, link id)
# timers.py
class DeadlineHeap: ...   # one shared persistent priority structure (F5): arm/cancel O(log n), due(now) O(k log n), stale entries bounded; never a tuple rebuilt per edit
@record class ExponentialBackoff: initial: float; maximum: float; current: float; last_error: float | None
@record class AsyncDebounce: min_s: float; max_s: float; current: float | None
def jitter(rng: random.Random, value: float, pct: float) -> float
# routeops.py
def route_ops(old: PMap[RowKey, Route], new: PMap[RowKey, Route], changed: frozenset[RowKey], af: int, *,
              sync_threshold: int) -> tuple[RouteOp, ...]
```

Tests: unit tests per helper; `tests/agents/harness.py` self-tests (the
projection proxy rejects an undeclared attribute read).

**F7: settings engine** (`netsim/settings/`, `netsim/model/device_settings.py`,
`adapters/ngraph.py`).

```python
@record class DefaultsSpec: entries: tuple[tuple[str | None, str | None, Any], ...]; fallback: Any  # (dialect range, profile, value)
@record class Setting: key: str; type: Any; scopes: tuple[str, ...]; default: DefaultsSpec; apply: str
                       unit: str | None = None; since: str | None = None; refs: tuple[str, ...] = (); doc: str = ''
@record class Fragment: owner: str; settings: tuple[Setting, ...]; records: Mapping[str, type]   # key -> resolved field
@record class Layer: name: str; priority: int; selector: Selector | None; values: PMap[str, Any]
@record class Selector: names: str | None = None; labels: frozenset[str] = frozenset()
def catalog_for(device_fragments: tuple[Fragment, ...]) -> Catalog   # model fragments + fragments of agents on the device
def resolve_device(catalog, layers, device_state, previous: Resolved | None) -> Resolved
@record class Resolved: dialect: str; profile: str; device_config: DeviceConfig
                        agent_configs: PMap[str, AgentConfig]; changed_keys: frozenset[str]
def explain(catalog, layers, device_state, key) -> tuple[tuple[str, Any], ...]   # (layer or default, value) chain
```

The catalog is per device: model-owned fragments plus the immutable
`settings_fragment()` of each agent plugin present on that device, so no global
registry exists and the model layer never imports agent packages.

Tests: `tests/settings/` precedence matrix (network, group, device, object;
equal-priority conflict rejected at `update()`; absent-object target rejected),
inheritance (peer-group, override units, unset restores), dialect pins and
aliases, `since` rejection, apply-action classes, `explain` chains, record
reuse, generated docs freshness, `native` fingerprints unchanged, NetGraph
`attrs.netsim` keys migrated.

**F8: forwarding programming contract.**

```python
@record class ProgrammingRequest: device: str; table: int; af: int; prefix: Prefix; generation: int
                                  request_id: int; action: Any                  # desired FIB action or DELETE
@record class ProgrammingResult: request_id: int; generation: int; outcome: str  # OK|ERROR|CAPACITY|LOST
                                 boundary: str                                  # control|kernel|hardware
@record class FibSlot: desired: Any | None; installed: Any | None; pending: ProgrammingRequest | None
                       reason: str | None                                       # e.g. POLICY_EXCLUDED
def program(slot: FibSlot, desired: Any, gen: int, now: float, hw: FibHardware) -> tuple[FibSlot, tuple[Event, ...]]
def complete(slot: FibSlot, result: ProgrammingResult) -> FibSlot               # ignores stale generations
```

Tests: `tests/model/test_programming.py` (G01–G04 without a gate, E09, E14,
deterministic same-time ordering, fingerprints unchanged with default
settings).

**RP1: route-policy language.**

```python
# netsim/model/route_policy/types.py
class Flow(Enum): ACCEPT; REJECT; NEXT_TERM; NEXT_POLICY
@record class RoutePolicy: name: str; terms: tuple[Term, ...]
@record class Term: name: str; when: Expr; actions: tuple[Action, ...]; flow: Flow
@record class RoutePolicyBinding: point: str; policies: tuple[RoutePolicyRef, ...]; fallback: str
                                  match_input: str = 'WORKING'; per_nexthop: bool = False
                                  scope: str | None = None; fallthrough: str = 'inherit'   # RESOLUTION_IMPORT only
@record class RoutePolicyRef: name: str; revision: str; digest: str
class PolicyAccess(Protocol[T]):
    def read(self, route: T, field: Field) -> Any: ...
    def read_context(self, context: Any, field: Field) -> Any: ...
    def apply(self, route: T, actions: tuple[Action, ...]) -> T: ...
# compile.py / evaluate.py
def compile_binding(binding, definitions, sets, capability: CapabilityRow) -> CompiledBinding   # raises on any error
def evaluate(compiled: CompiledBinding, route: T, context: Any, access: PolicyAccess[T],
             trace: TraceSink | None = None) -> PolicyResult                                   # pure
```

Tests: `tests/model/route_policy/` (truth and flow tables, absence rules,
quantifiers, `PrefixListPermits`, capability violations at compile time,
canonical fingerprints, E01–E03, E10, E12, E19–E22).

**RP3 and RP4: device hooks.**

```python
def submit_rows(dev: DeviceState, af: int, client: ClientId, op: RouteOp, *, bypass: bool = False
                ) -> tuple[DeviceState, RowChanges]         # F1b boundary; RP3 adds the admission views
def admit(submitted: RibState, bindings, access) -> RibState   # per_nexthop mode prunes legs; zero legs = not admitted
def nht_filtered(answer: NhtResult, binding, client) -> NhtResult   # scope 'nht': filter the chosen resolver, no fallthrough
```

Tests: E04, E05, E06, E11 and E13; `ip protocol` leg pruning and fallback to
the next candidate; `ip nht` returning filtered with no fall-through.

### 12.4 Open/R slices

**OR1: config, types, Spark, agent shell.**

- `settings.py` fragment (upstream defaults from `OpenrConfig.thrift` with refs;
  area and interface-regex scopes); `config.py` resolved records
  (`OpenrSettings`, `AreaSettings`, `SparkSettings`).
- `types.py`: `SparkHello`, `SparkHandshake`, `SparkHeartbeat`, `NeighborEvent`.
- `spark.py`:
  ```python
  @record class SparkNeighbor: name: str; interface: str; area: str; state: str; seq: int; rtt_us: int | None
                               hold: float; gr: float; established_at: float | None
  def on_hello(st: SparkState, iface: str, msg: SparkHello, now: float, cfg) -> tuple[SparkState, SparkOut]
  def on_handshake(st, iface, msg, now, cfg) -> tuple[SparkState, SparkOut]
  def on_heartbeat(st, iface, msg, now, cfg) -> tuple[SparkState, SparkOut]
  def on_timer(st, name, now, cfg) -> tuple[SparkState, SparkOut]
  def deduce_area(areas, iface, neighbor_name) -> str | None
  ```
- `agent.py`: `OpenrAgent(instance=0)`; worklist runner; timer namespace;
  views (`neighbors`, `adjacencies`).
- Tests first: FSM transition table (one test per row), area mismatch, GR
  window, one-way teardown, RTT arithmetic and floor, hello jitter determinism,
  liveness-only admission count.

**OR2: LinkMonitor and KvStore.**

```python
def merge_key(local: KvValue | None, incoming: KvValue, *, sender_is_originator: bool) -> MergeResult
def full_sync_request(db: KvStoreDb) -> KvSyncRequest            # hashes only
def dump_difference(db, req) -> KvSyncResponse                   # values + tobe_updated keys
def flood(db, delta, exclude_peer, node_id) -> tuple[Message, ...]
def ttl_tick(db, now, heap) -> tuple[KvStoreDb, Publication]
def adjacency_db(lm: LinkMonitorState, area, cfg, persistent) -> AdjacencyDatabase
```

Tests: merge-rule table (version, originator, value, ttlVersion), seeded
interleaving convergence property, 3-way sync after partition, TTL expiry,
self-originated override, flood loop check, metric pipeline table, flap backoff.

**OR3: Decision, PrefixManager, Fib, initialization.**

```python
def link_state(adj_dbs: PMap[str, AdjacencyDatabase]) -> LinkState      # bidirectional (node, if, otherIf)
def compute_routes(ls_by_area, prefix_state, me, cfg, changed: frozenset[Prefix] | None) -> RibDelta
def select_best_node_area(entries, cfg) -> tuple[str, str]               # lowest (node, area) when selection off
def redistribute_cross_area(programmed: RibDelta, areas) -> tuple[PrefixEntry, ...]
def fib_step(fib: FibState, delta: RibDelta, notices: tuple[RowNotice, ...], now) -> tuple[FibState, RouteOps, Timers]
```

Tests: oracle equivalence twins (section 4.7 configuration), delete delay in
placement, init-gate timings, change-proportional op counts.

**OR4–OR6.** Multi-area and multi-instance (`deduce_area`, `area_stack`,
`bestArea` case, separation tests); drain and overload commands writing
`persistent`, RIB-feed injection (`kind='all'`); passport and study
integration, the `netsim_ext` SRv6 advertisement.

### 12.5 BGP slices

**BG1: data types, AS_PATH, peers, settings.**

```python
@record class Segment: kind: int; asns: tuple[int, ...]           # SEQ, SET, CONFED_SEQ, CONFED_SET
@record class AsPath: segments: tuple[Segment, ...]
def hop_count(p: AsPath, *, count_confed: bool = False) -> int   # a set counts 1, confed excluded (RFC 5065 §5.3)
def prepend(p, asn, *, confed: bool = False, times: int = 1) -> AsPath
def strip_confed(p) -> AsPath;  def left_as(p, *, skip_confed: bool = True) -> int | None
def loop_count(p, asn, *, exclude_confed: bool = False) -> int      # FRR aspath_loop_check vs _confed
@record class PathAttributes: origin: int; as_path: AsPath; next_hop: NextHop; med: int | None; local_pref: int | None
    atomic_aggregate: bool; aggregator: tuple[int, int] | None; communities: frozenset[int]
    ext_communities: frozenset[bytes]; large_communities: frozenset[tuple[int, int, int]]
    originator_id: int | None; cluster_list: tuple[int, ...]; aigp: int | None
def peer_sort(inst: InstanceSettings, nbr: NeighborSettings, open_as: int | None) -> str   # IBGP|EBGP|CONFED|INTERNAL
def router_id(configured: int | None, interfaces: PMap[str, InterfaceView]) -> int | None  # zebra rule
def update_size(attrs, nlri: int, afi: int, *, extended: bool) -> int                       # RFC 4271 §4
```

Tests: AS_PATH vectors re-derived from RFC 4271/5065/6793; peer-sort matrix
(incl. peer AS == confed id → IBGP; `remote-as auto`); router-id selection;
fragment coverage.

**BG2: sessions.**

```python
@record class PeerFsm: state: str; conn: int | None; caps: Caps | None; hold: float; keepalive: float
                       connect_retry: float; idle_hold: float; last_error: str | None
def fsm_step(fsm: PeerFsm, ev: FsmEvent, now: float, cfg: NeighborSettings) -> tuple[PeerFsm, tuple[FsmAction, ...]]
def resolve_collision(ours: PeerFsm, theirs_conn: int, my_id: int, peer_id: int, my_as: int, peer_as: int) -> int
def negotiate(local: Caps, remote: Caps) -> Caps
def session_endpoints(ctx, nbr: NeighborSettings) -> tuple[Endpoint, Endpoint, int, int | None]   # local, remote, ttl, min_ttl
```

Events include `InterfaceDown` (fast external failover) and `NhtChanged`
(connect gating). Tests: establishment matrix for every row of section 5.3,
collision, hold negotiation and expiry, backoff sequences, fast external failover
flush, dynamic-capability CAPABILITY-vs-reset.

**BG3: inbound, next hops, decision, Loc-RIB, install.**

```python
def process_update(st: BgpState, peer: PeerKey, upd: Update, now, cfg) -> tuple[BgpState, frozenset[DestKey]]
def nexthop_register(st, path) -> tuple[BgpState, tuple[NhtOp, ...]]
def on_nht_changes(st, keys: tuple[NhtKey, ...], ctx) -> tuple[BgpState, frozenset[DestKey]]
# decision/frr.py and decision/rfc4271.py
def compare(new: PathView, exist: PathView, ctx: DecisionContext) -> Verdict
def select(dest: Dest, changed: tuple[PathKey, ...], ctx: DecisionContext) -> Selection
def select_multipath(dest: Dest, best: PathKey, ctx) -> tuple[PathKey, ...]
def process_dirty(st, dirty: frozenset[DestKey], ctx) -> tuple[BgpState, tuple[LocRibChange, ...]]  # after 50 ms hold
def install_ops(changes, st, cfg) -> tuple[RouteOp, ...]        # distances, recursion, legs, metric = MED
```

Decision tests are data tables (one row per step and flavor, with the expected
winner and reason string), plus scenario 8 order dependence, direct and
indirect next hops, BGP-over-BGP and `via_metric`.

**BG4–BG6: outbound, policy, RR, confederations.**

```python
@record class UpdateGroupKey: sort: str; policy_out: str | None; nh_self: str | None; rr_client: bool; ...
def announce_check(route: LocRibEntry, src: PeerKey, grp: UpdateGroupKey, st, cfg) -> Advert | None
def per_peer_nexthop(advert: Advert, peer: PeerKey, st) -> NextHop
def queue_and_pack(adj_out: AdjRibOut, adverts, withdraws, now, mrai) -> tuple[AdjRibOut, tuple[Update, ...]]
# policy: BGP's PolicyAccess over its own route type; evaluation is route_policy.evaluate (RP1)
def bgp_policy_access() -> PolicyAccess[BgpRoute]
def apply_binding(binding: CompiledBinding, route: BgpRoute, context: BgpPolicyContext) -> PolicyResult
def reflect_to(src_sort, src_client: bool, dst_sort, dst_client: bool, c2c: bool) -> bool   # RFC 4456
def rr_stamp(attrs, src_router_id: int, cluster_id: int) -> PathAttributes
def confed_outbound(attrs, dst_sort: str, member_as: int, confed_id: int) -> PathAttributes  # RFC 5065
```

Tests: scenarios 1–7, 9, 11, 12; message-count assertions; settings `@covers`
tests for each key the slice introduces.

**BG7: conformance.** `netsim/adapters/frr.py` (load and dump a bounded
`frr.conf` subset into layers), SONiC BGP tables into layers, `tools/frr_lane/`
scripts, goldens, the Z5 and N6 black-box checks, scenario 10 dynamics.

### 12.6 Worker assignment template

Each slice is one worker branch (`protocols/<slice>`), created as in Gates B
and C. The prompt contains: the slice section of this plan (sections 3, 4.8,
5.12 and 12), the owned files, the tests to write first, the exit check, the
rule "no edits outside owned files except through the integrator", and the
checks to run (`make check-ci`, `make check-ft`, the slice's benchmarks). The
integrator merges in the order of section 8, runs the fingerprint oracle and
full checks, and routes review findings back to the owning worker.

### 12.7 First actions after approval

1. F0 commit by the integrator (records, stubs, `test_contract_f0.py`).
2. Launch F1a, F2a, F3, F4, F5 and F7 workers in parallel.
3. Integrate M1, run the review round, update this plan and memory.
4. Launch F1b, then F2b; hold the F1c design gate; launch OR1 and BG1 as soon
   as F5 and F7 are merged.

---

## 13. How the plan answers each part of the brief

One subsection per requirement. Each gives the mechanism, where it lives in
code, how a user configures it, and the test that proves it.

### 13.1 A proper Open/R IGP, following the GitHub source

- **Mechanism.** `netsim/agents/openr/` mirrors the daemon module for module
  (Spark, LinkMonitor, KvStore, Decision, PrefixManager, Fib, initialization)
  at `facebook/openr` `81dae4c`, cloned in `~/ws/openr`. Each submodule is a
  pure function over its frozen state; the agent drains the modules' queues as
  a worklist in the daemon's order. Programming-gated edges wait for FIB
  confirmation (D3).
- **Fidelity.** The eight behaviour groups of section 4.1 are reproduced with
  upstream defaults and `file:line` refs. Upstream facts that surprise people
  are kept as upstream has them: no domain name, SP_ECMP only, RTT metric by
  default, soft-drain at boot, area policy a stub. Anything added is
  `netsim_ext` and off by default.
- **Proof.** Section 4.7: oracle equivalence on random graphs, FSM and merge
  tables, partition and heal, multi-area, drain, delete delay in placement.

### 13.2 Which BGP to follow

- **Decision.** RFCs first; FRR as the dialect where the RFCs leave room;
  clean-room Python on NetSim's agent contract (D1, research
  `research-bgp-options.md`).
- **Why FRR.** It implements everything asked (RR, confederations, add-path,
  ENHE, unnumbered), publishes selection reason codes that make traces
  diffable, and is what SONiC runs.
- **Why not run FRR itself.** FRR is wall-clock and kernel-TCP bound, so it
  cannot run under simulated time, and it is GPL, so its code cannot be ported
  into MIT NetSim.
- **Rejected.** GoBGP (no IGP-metric step), OpenBGPD (no confederations),
  Batfish (fixed point with an approximate MED rule), C-BGP (unmaintained),
  Holo (no RR or confederations), bgpsim (no confederations).
- **Version.** Modern FRR (master `f1d7bec`), with FRR 10.5 (SONiC) as a
  settings preset; generic version differences are settings (section 2B).
- **Checked against real FRR.** An optional containerlab lane compares
  converged state; its goldens are replayed by the normal test suite.

### 13.3 IGP domain size: one device, all devices, several domains

An IGP domain is not a declared object. It is the set of IGP instances that
can form adjacencies, which follows from configuration (D5).

| Shape | How it is configured | What happens |
|---|---|---|
| All devices in one domain | `openr.deploy(net, devices=all, areas=(AreaConfig('0', include_interface_regexes=('eth.*','Po.*'), redistribute_interface_regexes=('lo.*',)),))` | Spark discovers every included interface, KvStores flood one LSDB, Decision computes routes to every loopback |
| Several domains | Deploy Open/R per domain with device sets whose boundary interfaces are excluded from discovery (`exclude_interface_regexes`), or leave boundary devices without Open/R on those interfaces | No Spark hello crosses the boundary, so no adjacency and no flooding. Each domain has its own KvStore contents. Never rely on area names, because area `"0"` is a wildcard (`Spark.cpp:2112-2121`) |
| A border device in two domains | Two agents, `OpenrAgent(instance=0)` and `OpenrAgent(instance=1)`, with disjoint interface sets (`netsim_ext.multi_instance`) | Each instance owns its interfaces and drops hellos on the others. Routes cross only by explicit RIB-feed redistribution with tags |
| Multi-area inside one domain | Several `AreaConfig`s selected by interface and neighbour regexes | Per-area LinkState and KvStore; ABRs redistribute through PrefixManager with `area_stack` loop prevention (section 4.4) |
| One device as its own domain | An Open/R instance whose interfaces are not discovered, or no IGP at all | The instance originates its own prefixes into its own store and computes nothing remote (`research-openr.md` §9). Without an IGP, the device relies on connected, static and BGP routes |
| Fast analytical underlay | `oracle_igp_domains((IgpDomain('as1', devices=..., exclude=('ext.*',)), ...))` (F4) | Per-domain SPF with passive interfaces; used by BGP tests and studies that do not need protocol timing |

- **Code.** `openr/spark.py` `deduce_area(areas, iface, neighbor_name)`,
  interface ownership checks in `openr/link_monitor.py`, `model/igp.py`
  `oracle_igp_domains`.
- **How BGP sees domains.** BGP resolves next hops through whatever the device's
  RIB holds, so a next hop inside another domain is unresolvable unless
  something (BGP itself, a static route, redistribution) provides a route.
  That is the real behaviour.
- **Proof.** Section 4.7 separation tests; IX 1, 2, 3, 5 and 6.

### 13.4 BGP sessions: iBGP, eBGP, confederation; loopbacks or interface addresses

Session setup is one pure function, `bgp/fsm.py` `session_endpoints(ctx, nbr)`,
evaluated from the resolved neighbour settings:

1. **Peer sort** (`bgp/peer.py` `peer_sort`): IBGP when the remote AS equals the
   local AS; CONFED when it is listed in `bgp confederation peers`; EBGP
   otherwise. `remote-as internal|external|auto` is resolved at OPEN. A peer AS
   equal to our confederation id is IBGP.
2. **Remote endpoint.** The configured neighbour address, or for
   `neighbor eth1 interface` the peer's link-local address from `ctx.neighbors`
   on that interface (unnumbered, RFC 8950 ENHE turned on).
3. **Local endpoint.** `update-source` gives that interface's address, typically
   the loopback. Otherwise the egress interface's primary address toward the
   peer (`agents/common/net.py` `source_address`, as FRR's `getsockname`). For
   unnumbered, the interface's link-local address, scoped.
4. **TTL.** 255 for IBGP; 1 for EBGP and CONFED; N with `ebgp-multihop N`; 255
   plus `min_ttl = 256 - hops` with `ttl-security hops N` (F3).
5. **Connect gating.** Single-hop EBGP registers NHT with `connected_only` and
   does not connect until the peer address is on a connected network
   (`bgp_fsm.c:2704-2717`).
6. **Passive side.** A wildcard listener on port 179 scoped to the device's
   interfaces, with an accept table of configured peers giving each peer's TTL
   and `min_ttl`; unknown remotes are refused (`bgp_accept`).
7. **Collision.** Both sides may open, and transport keeps both connections; the
   FSM keeps the one initiated by the higher BGP identifier (RFC 4271 §6.8).

What each combination therefore does, with no special cases in code:

| Configuration | Outcome |
|---|---|
| eBGP on link addresses | TTL 1, connected check passes, session up; next hop direct |
| iBGP on loopbacks with `update-source lo` | TTL 255; the session comes up once an IGP, static or BGP route reaches the peer loopback; next hops indirect |
| eBGP on loopbacks without multihop | Held by the connected check (no session), unless a static route satisfies it (then up, but routes stay inactive, a recorded FRR quirk) |
| eBGP on loopbacks with `ebgp-multihop 2` or GTSM | Up across one transit router; GTSM rejects longer paths |
| Confederation peers | TTL 1 by default: adjacent loopbacks work, farther ones need `ebgp-multihop` |
| iBGP on link addresses | TTL 255 across one hop; next hops unchanged unless next-hop-self |
| Unnumbered eBGP | Scoped link-local session with no routes needed; IPv4 routes use IPv6 link-local next hops |

- **Proof.** BG2 establishes one session per row of section 5.3; scenarios 1, 2
  and 4; IX 1, 2, 4 and 5.

### 13.5 iBGP hop by hop with RR and next-hop-self instead of an IGP

- **Configuration** (sketch 4 in section 6.1). On every router:
  - one iBGP session per link, on link addresses;
  - every neighbour is a route-reflector client;
  - the cluster id defaults to the router id, so every router is its own
    cluster;
  - `next-hop-self force` on every neighbour;
  - `network <own loopback>`;
  - `maximum-paths ibgp N equal-cluster-length`.
- **Why it works like an IGP:**
  - Loop prevention: each reflection prepends the reflector's cluster id to
    CLUSTER_LIST, and a router drops a route carrying its own cluster id or its
    own ORIGINATOR_ID as an implicit withdraw (RFC 4456 §8; `rr.py`
    `inbound_loop`).
  - Path choice: all copies of a loopback carry the same ORIGINATOR_ID, so the
    router-id step ties (RFC 4456 §9 substitution) and the shorter CLUSTER_LIST
    wins (step 14). The result is shortest-hop routing.
  - Next hops: `force` rewrites the next hop to the local link address on every
    hop (plain next-hop-self is ignored on reflected routes). So every next hop
    is direct, resolved through the connected route, and no IGP is needed.
  - ECMP: with `equal-cluster-length`, only equal-hop paths join the multipath
    set.
- **Recorded pitfall.** Without `equal-cluster-length`, FRR admits longer
  cluster-list paths into the multipath set, which can form forwarding loops.
  The simulator reproduces this and the test detects the loop by trace
  (scenario 6).
- **Overlay on top.** Loopback sessions, for example to a central RR, then
  resolve over these BGP-learned loopback routes: BGP over BGP, allowed as in
  zebra (IX 4).
- **Proof.** Scenario 6 (with and without `equal-cluster-length`); IX 4 against
  a hop-count oracle.

### 13.6 Replaceable, named decision flavors

- **What a flavor is.** A frozen `FlavorSpec(name, selection, steps, refs)`
  (`agents/common/selection.py`). `selection` is `insertion` (FRR's sorted
  list), `elimination` (RFC 4271 whole-set elimination) or `grouped(key)`.
  `steps` names built-in steps or carries user step objects. Each step is a
  `PairStep` (returns win, tie, or a held result released later, which FRR's
  IGP-metric and confederation steps need) or a `FilterStep` (set
  elimination). Steps may mark the multipath checkpoint.
- **Where it plugs in.** The flavor is the value of the per-node setting
  `bgp.decision`. `locrib.process_dirty` calls
  `select(dest, changed, ctx)` for each changed destination only, using the
  flavor resolved from `ctx.agent_config` (a pure O(steps) lookup, nothing
  cached). Multipath is a separate rule object (`multipath.py`).
- **What flavors see.** Everything they may depend on is explicit per-prefix
  state in `Dest`: the ordered path list, unsorted paths in arrival order, the
  previous best, arrival sequence numbers. So history-dependent flavors (FRR's
  RFC 5004 step, vendors' oldest-path steps) are expressible and deterministic.
- **Built in.** `frr` (hand-written from `bgp_path_info_cmp`, step by step) and
  `rfc4271`. `cisco-ios` and `junos` come in BG8.
- **Adding a named flavor.**
  1. List built-in step names and any new step classes (frozen, pure, with
     refs).
  2. Choose the selection algorithm.
  3. Give it a name and refs.
  4. Set it as `bgp.decision` on a network, group or device layer.

  No change to the agent is needed (example in section 6.1).
- **Knobs versus flavors.** Knobs such as `always-compare-med` are ordinary
  settings; `FlavorSpec.use('frr', always_compare_med=True)` is sugar that
  writes them.
- **Proof.** Per-step data tables per flavor, the order-dependence test
  (scenario 8), and an invariant that every step carries refs.

### 13.7 Route reflection and confederations

- **Route reflection** (`bgp/rr.py`), RFC 4456 in FRR's dialect (section 5.6).
  - Hooks: `reflect_to(...)` in the outbound announce check (the reflection
    matrix); `rr_stamp(...)` writes ORIGINATOR_ID and prepends CLUSTER_LIST on
    iBGP → iBGP only; `inbound_loop(...)` in inbound processing; decision steps
    13 (ORIGINATOR_ID as router id) and 14 (CLUSTER_LIST length), plus step 9
    with `equal-cluster-length`.
  - Per-node settings: client flag per neighbour and AF, `cluster_id`,
    client-to-client reflection, allow-outbound-policy, next-hop-self force.
  - Proof: scenarios 5 and 6.
- **Confederations** (`bgp/confed.py`), RFC 5065 in FRR's dialect (section 5.7).
  - Hooks: `peer_sort` returns CONFED; `confed_outbound(...)` prepends
    AS_CONFED_SEQUENCE toward members and strips confederation segments and
    prepends the confederation id toward true external peers; receive checks
    (segment sanity, loops over member AS and confederation id); decision steps
    4 (confed segments not counted), 6 (MED rules), 7 (confed counts as
    internal) and 10 (confed-external before the IGP metric); distance 200; TTL
    1 by default.
  - Proof: scenario 7, IX 5.

### 13.8 RFC annotations

- **In code.** A decorator `@ref(...)` from `agents/common/refs.py` records
  citations on every rule-bearing function and step, for example
  `@ref('RFC 4456 §8', 'FRR bgp_route.c:6235-6255 inbound cluster check')`. It
  stores an immutable `__refs__` tuple: no registry, no runtime cost.
  - Module docstrings cite the governing RFC sections.
  - Behaviour borrowed from FRR or Open/R cites function, step or reason names
    and `file:line` in the pinned tree.
- **In settings.** Every `Setting` and `DefaultsSpec` entry carries refs
  (section 2A.1).
- **Enforced.** An invariant test scans the protocol packages (`decision/`,
  `aspath.py`, `inbound.py`, `outbound.py`, `rr.py`, `confed.py`, `fsm.py`,
  `nexthop.py`, `openr/*`) and fails on any public rule function or step
  without refs.
- **Traceability.** Tests carry `@covers_ref('RFC 4456 §8')`. A generator writes
  `docs/traceability.md` (RFC section → functions → tests), and CI fails if a
  cited section has no test or the file is stale.

### 13.9 Direct and indirect next hops

The same path through the code, from receipt to forwarding (D8, section 5.4,
F1b):

1. **Receive** (`bgp/inbound.py`, `bgp/nexthop.py`). The next hop is classified
   by the session:
   - single-hop eBGP (TTL 1, no `disable-connected-check`) registers NHT with
     `connected_only=True`, so it must be on a connected network: **direct**;
   - everything else (iBGP, confed, multihop, GTSM) registers a recursive NHT
     key, which may resolve over IGP, static, connected or BGP routes:
     **indirect**;
   - link-local next hops (unnumbered) are keyed by interface and follow
     interface state, never registered with zebra.
2. **Validity and metric.** The path is valid when the NHT answer is eligible
   (installed mode). The decision process's IGP-metric step uses `via_metric`:
   the metric of the installed resolving route, which is the IGP cost for an
   IGP route, 0 for connected or static, and the MED for a BGP route.
3. **Install** (`bgp/zebra.py`).
   - Direct routes install as `Nexthop.via(interface, address)`, taken from the
     NHT legs (non-recursive, as FRR sends single-hop eBGP).
   - Indirect routes install as `Nexthop.recursive(address, af)` with recursion
     allowed.
   - Distances: eBGP 20, iBGP and confed 200.
4. **Forwarding** (F1b hierarchical FIB). Every recursive next hop becomes one
   `RecursiveNexthop` entry shared by all routes that use it. A FIB group is
   keyed by the unresolved next-hop set, and its content is the flattened legs.
   An IGP change recomputes one recursive entry and the groups using it; the
   50k BGP entries keep their group id, so the change costs O(affected next
   hops), not O(routes) (G1: from 1.8 s to a target of 5 ms).
5. **Next-hop change.** NHT notifies the changed keys, and BGP re-evaluates only
   the paths on those next hops (FRR `evaluate_paths` over `bnc->paths`).
6. **Send side** (`bgp/outbound.py`).
   - To eBGP, the next hop is self unless third party (RFC 4271 §5.1.3).
   - To iBGP, it is unchanged unless next-hop-self; on reflected routes plain
     next-hop-self is ignored and `force` applies, and a permitted outbound
     route-map may rewrite it explicitly.
   - To confed peers, it is unchanged.
   - Self is a sentinel patched per peer with that session's local address.

   The sender's configuration therefore decides whether the receiver sees a
   direct or an indirect next hop.
- **Proof.** Scenarios 1 (direct, fast external failover), 3 (indirect, hot
  potato, reprocessing counts), 4 (static quirk, `disable-connected-check`);
  BGP over BGP in IX 4; the G1 and op-count benchmarks.

### 13.10 Modularity and flexibility, in one place

- **Layers.** `core ← model ← runtime ← agents / adapters`. Protocol packages
  import only contracts, addressing, routing records, `state.PMap`/`record`
  and `agents/common` (invariant test).
- **Inside a protocol.** One submodule per real module, each a pure function
  over frozen state with a declared context projection, joined by explicit
  queues (D3). Adding behaviour means adding or replacing a submodule, not
  editing the agent.
- **Replaceable parts.**
  - decision flavors and multipath rules as values of settings;
  - policy as typed route-map records;
  - Open/R route selection mode as a setting;
  - dialects and presets as data.
- **Configuration.** Every setting is per node through layers (section 2A), and
  run-time changes follow declared apply actions.
- **Cooperation.** Protocols meet only through the RIB (with the redistribution
  feed), NHT and published views (D2). So Open/R, BGP, statics, the analytical
  oracle and future IGPs (IS-IS) mix on any device without knowing each other.
- **Extending.**
  - A new IGP reuses `agents/common` (SPF, timers, routeops, settings,
    harness).
  - A new BGP feature (add-path, GR, BFD) is a submodule plus settings; keys
    are already add-path and VRF ready (D9).

### 13.11 Routing policy (integrated from the reviewed routing-policy plan)

- **One engine for every hook.** A small typed language and one pure evaluator
  (`netsim/model/route_policy/`, RP1) serve every attachment point: BGP import,
  export, table-map, redistribution, RIB admission, FIB installation and
  resolution.
- **Per-node bindings.** Bindings are per-node settings that resolve to exactly
  one binding per scope. Definitions are immutable and pinned by digest.
- **Access by owners.** Each owner supplies a typed `PolicyAccess` for its own
  route type, and one capability table per point limits which fields may be
  read and written.
- **Vendor fidelity.** Exact adapters, FRR first (RP5 in BG7). Integration
  corrected two mappings from source: `ip protocol route-map` is per-next-hop
  RIB admission with fallback to the next candidate, and `ip nht route-map` is
  NHT-scoped with no fall-through.
- **Edits.** Changes follow owner-defined reevaluation, and import replay
  reports `needs_session_reset` when neither retained input nor ROUTE-REFRESH
  is available.
- **Proof.** E01–E24 across RP1, RP3, RP4, BG3/BG4 and M5.

### 13.12 Installation gating and advertising inactive routes

- **Mechanism.** The F8 programming contract keeps desired and installed actions
  separate, with generation-guarded completions at a named boundary.
  - The gate profiles `selected`, `effective` and `strict`, plus
    `bgp.export.inactive`, are per-node settings.
  - FRR's `suppress-fib-pending` is a limited-scope profile.
  - Open/R's readiness gate is reproduced as upstream has it, on
    programmed-prefix membership.
- **Proof.** G01–G10, scenario 13, and the coupled pair FIB gate × inactive
  export.

---

## 14. Scale review: experiments, prototypes and the streamlined plan (revision 6)

Goal set on 2026-09-27: review the plan critically, prove its points with
experiments and prototypes, and make sure the implementation stays simple to
maintain and performs for more than 100k devices and 1M prefixes. Scripts are in
`netsim-protocols-research/scale-experiments/`, all run on main `0e5b299`,
CPython 3.14.5, one machine. No repository code changed.

### 14.1 What the current tree costs

| Measurement | Result | Script |
|---|---|---|
| One device with 200k recursive BGP-style rows, converged | 296 MB and 16.9 s: about **1.5 KB and 84 µs per row** | `mem_probe.py` |
| Where the bytes go | RIB 504 B per row (360 B of it `PMap` shard overhead, 80 B `Route`, 56 B prefix tuple). Converge adds 981 B per row: about ten objects per prefix in the resolver (`FibEntry`, `RowOutcome`, `DependsOn`, `_Leg`, memo and frame tuples) | `mem_breakdown.py` |
| Building a network | **Quadratic**: 5.5 ms per device at 2k devices, 21 ms at 8k, 31 ms at 10k (312 s for 10k). Cause: `_validate_interface_config` (`network.py:738`) walks every device on every interface add for the SRv6 locator-overlap check; 22.5M `items()` calls for 9k interfaces | `build_phases.py`, `prof_build.py` |
| Converge with no routes | 1.7 ms and **25 KB per device**. 13 KB of it is `addressing.py:178`: every `PrefixTable` allocates a tuple of 33 or 129 mask ints (`lpm.py:193`), four tables per device | `converge_mem.py` |
| Idle agent tick (timer re-arm, state returned by identity) | **160–200 µs per run** and **27 KB retained per run** | `build_phases.py`, `tick_retention.py` |
| Cause of the retention | `AgentNode.rng = ctx.rng.getstate()` (`agents.py:792`): the 625-int Mersenne Twister state is committed on every run and kept by every retained root | `tick_retention.py` |
| Cause of the run cost | Every run is a full tree commit, because `runs`, `receipt` and `rng` change on every run. The commit pays delta diffing, `bump_epochs`, SRv6 `consumers_affected`, output validation and `AgentNode.__eq__` | `prof_ticks.py` |
| Raw DES core, 100k periodic processes | about 1.5 µs per timeout firing (712k firings, not 1M: the periods exceed 1 s), 776 B per process. The engine is not the bottleneck | `des_core_100k.py` |
| `PMap` at 1M entries | 104 B per entry, 1.35 s to build, `set` 40 µs. `validate_admitted` of one changed entry: **3.15 s** | `proto_pmap_1m.py` |

### 14.2 Experiments that prove the fixes

| Fix | Experiment | Result |
|---|---|---|
| Index the locator check (skip it when no device has locators; otherwise a block index) | monkeypatched `_validate_interface_config` | Build becomes linear: **95–125 µs per device**, 20k devices in 2.5 s; 100k projected at about 15 s instead of hours (`exp_build_fix.py`) |
| Stop committing the MT state | `getstate()` returns `None` | Retention falls from 26.9 KB to **1.8 KB per run** (`exp_rng_fix.py`) |
| Replace mask tuples by shifts (`(addr >> (bits − plen)) << (bits − plen)`) | arithmetic; per-device tables hold no mask objects | Saves about 13 KB per device (1.3 GB at 100k), and removes a shared object from the lookup hot path, which also helps free-threading |
| Shard-identity admission | prototype over the changed shard only | 1 change in 1M: **1.5 ms** instead of 3.15 s; but still O(N / 256) per change, so a changed-key log from the `PMap` builder (O(k)) is the mechanism, not the follow-up |

### 14.3 Prototypes at 1M prefixes

| Prototype | Result | Conclusion |
|---|---|---|
| Columnar route table: `array('Q')` prefixes, `array('B')` lengths, `array('I')` group ids; groups keyed by unresolved next-hop set; recursive next hops with dependent-group sets (`proto_hfib.py`) | 1M routes in 240 ms and **13 B per route** (plus 106 B per route for a dict exact-match index). An underlay change touches one recursive entry and its groups and **zero routes: 4.8 µs**. A route add: 9 µs. A trivial O(N) scan of 1M routes: 51 ms | A mutable lower bound: the hierarchical dependency structure avoids touching routes on an underlay change, and the payload is about 100× smaller than the object model (the exact-match index is not, at 106 B per row). The immutable design is §15.1 with the §16 corrections. Any per-event O(N) walk is at least 50 ms at 1M, so "cost proportional to change" is a hard requirement |
| Columnar LPM: sorted arrays per length with `bisect` (`proto_columnar_lpm.py`) | 117 B per prefix, 4.6 µs per lookup, 52 µs per insert (memmove), against the current dict-per-length table at 104 B and 1.3 µs | Withdrawn in §15.2: the probe retained temporaries and kept duplicates. Corrected, packed columns hold 11.8 MB against 98.6 MB for the dict-per-length table at 1M, with 4.1 µs against 1.2 µs lookups. The index is chosen per device class (§16.2) |
| BGP Loc-RIB, 1M prefixes × 4 paths with interned attributes (`proto_locrib.py`) | Frozen path objects: 650 MB, 9 s, 162 B per path. Struct-of-arrays (CSR offsets, peer, attribute id, sequence, flags): **68 MB, 1.7 s, 17 B per path**; a simple selection over one destination 0.4 µs | Object-per-path is unaffordable at 1M. Attribute interning plus arrays is the design |

### 14.4 The scale target, stated honestly

"100k devices and 1M prefixes" has two readings, and only one is feasible on
one machine in any language:

- **Every device holds the full 1M table:** 10^11 route entries. At 16 B each
  that is 1.6 TB. Not feasible.
- **1M prefixes network-wide, bounded per-device tables:** leaves hold locals
  plus a default or summaries; spines hold pod summaries; a few dozen border,
  route-reflector or super-spine devices hold full tables. Total rows about
  10^8, which is 2–3 GB in columnar form. Feasible, with the changes below.

The design of record already states the N(N − 1) flat-domain limit. Two more
limits are measured now:

- **Full per-device SPF at 100k devices** is 100k Dijkstra runs. In Python
  that is hours; with the NetGraph-Core kernel (10 ms per 100k-vertex SPF, per
  the design of record) it is about 1,000 s. So the analytical mode at 100k
  devices must be **demand-driven and lazy**: compute forwarding only on the
  devices and prefixes a query or a demand touches, which the design of record
  already allows ("lazy routes behind an explicit interface").
- **Initial load of a 1M-prefix BGP table** on one device is 4M path arrivals.
  At 20 µs per path that is 80 s per device; at 2–5 µs, with bulk array
  operations per UPDATE, 8–20 s. Bulk paths need array-level work, and
  optionally a numpy or native kernel behind the same pure interface, like the
  Core kernel today.

**Passports** (section 5.10 replaces its earlier list):

| Passport | Shape | Targets |
|---|---|---|
| P-A analytical, 100k devices | Clos with summaries and defaults; 1M prefixes network-wide; full tables on ≤ 64 devices; demand-driven forwarding | build ≤ 60 s; ≤ 8 KB per device baseline (≤ 0.8 GB); one failure re-derives only affected devices and prefixes |
| P-B protocol, BGP full table | 16 devices (2 RRs, 14 clients or peers), 1M prefixes × 4 paths | ≤ 1.5 GB total; initial load ≤ 5 min; one prefix flap ≤ 1 ms per device; one next-hop change ≤ O(paths on that next hop) |
| P-C protocol, wide fabric | 4k devices, Open/R or eBGP unnumbered, 40k prefixes, `lab` timers | cold start ≤ 10 min; idle tick ≤ 40 µs and 0 B retained; one link failure ≤ 5 s wall |

Every claim beyond these passports is unproven. The user confirmed on
2026-09-27 that the target is the bounded-table reading: about 1M prefixes
network-wide, per-device tables of locals plus aggregates and defaults, and
full tables on a few dozen devices (passport P-A).

### 14.5 Plan changes (revision 6)

**S0, scale hygiene: before everything else in M1.** Five small fixes, each
with a benchmark that fails on the old code:

1. Locator-overlap check through an index; build is linear.
2. A small deterministic PRNG in place of `random.Random` state: a 64-bit
   counter-based generator whose state is one int, with per-module streams
   derived by name (D3). The 25 KB per run goes away.
3. Masks by shift arithmetic; no mask tuples per table.
4. Timeline retention bounded by default (`keep_records`, `keep_events`) so a
   long run cannot grow without limit.
5. A `PMap` builder changed-key log, used by admission (F2c) and by RIB
   change sets (F1b). Admission becomes O(changed keys).

**Zero-commit idle runs (F2a, a design change to Gate C).** `runs`, `receipt`
and `rng` move from `AgentNode` into runtime bookkeeping keyed by
(device, agent, generation); the tree keeps `state`, `views`, `persistent` and
`config`. A run whose output is identity state plus timers or messages commits
nothing: no delta, no `bump_epochs`, no SRv6 invalidation, no timeline record.
Target: ≤ 40 µs and 0 B retained per idle run, from 160–200 µs and 27 KB.
Receipts stay observable through views and the runtime's budget API.

**Packed payloads (F1b, renamed "persistent packed FIB").** Storage is the
immutable `PackedTable` of §15.1 (bytes chunks, copy-on-write builder,
changed-row log), never mutable arrays. The prefix index stays a dict per
length for bounded devices and becomes packed sorted key columns for
full-table devices. The payloads become packed rows:
- FIB: per family, `entries` = arrays of (prefix, length, group id, action);
  groups interned by unresolved next-hop set; recursive next hops in one table
  with dependent-group sets; no per-entry `DependsOn` object.
- RIB: rows stay objects at the API (`Route` is the contract), but the per-row
  outcome becomes an array indexed by row position, and `RowOutcome` objects
  are created only on read.

  Target: ≤ 60 B per FIB entry, from about 1 KB.

**BGP tables (BG3).** Loc-RIB as struct-of-arrays with interned attributes:
CSR offsets per destination; per path: peer id, attribute id, sequence, flags.
`PathView` objects are created only for the paths a decision compares.
Adj-RIB-Out per update group as arrays of (destination, attribute id). Target:
≤ 24 B per path.

**Bulk paths.** Initial table load, `sync`, and full best-path recomputation
after a knob change operate on arrays per UPDATE or per table, behind the same
pure functions. A numpy or native kernel may back them later, chosen by
profile, as with the Core kernel.

**Analytical mode at scale (new item in F4).** `oracle_igp_domains` gains a
lazy mode: routes for a (device, prefix) are computed on first query from a
per-domain SPF cache keyed by source, and demands drive which sources are
computed. The mode is an explicit per-domain setting; it is never chosen by device count.

**PMap fixed shard count.** 256 shards make every map operation O(N/256).
Above about 1M entries the count should grow with the map (for example
√N rounded to a power of two, decided at promotion). This is a contained change
in `state.py` with the existing `PMap` tests as the oracle.

### 14.6 Streamlining: what to merge, defer or drop

The plan grew to twelve foundation slices, two protocol tracks and a policy
engine. The following keeps the requirements and cuts the surface:

| Change | Reason |
|---|---|
| Merge F2a into F0 as "contract and delivery"; the runtime side of the new records is small once idle runs are zero-commit | One owner for the contract and its delivery avoids a hand-off |
| F7 settings engine lands in two steps: **F7a** (schema, device layer, dialects and profiles as data, `native` dialect, no groups) with M1; **F7b** (group layers with selectors, presets, `explain`, generated docs) with M3 | Protocol slices need only per-device resolution at first; groups and provenance are conveniences |
| Defer RP4 (`RESOLUTION_IMPORT` forwarding scope and `FIB_INSTALL`) to M4; keep the `nht` scope, which FRR needs, in RP3 | No scenario before M4 uses them; F8 is the dependency |
| F8 delivers desired versus installed actions and **group versions** with generation-guarded completions, an explicit ERROR completion and a deterministic injection seam, and the sync completion event; the `effective` gate profile and stochastic failure models come with BG8 | Pending, error and success must be distinguishable from the start; the two profiles FRR and Open/R need (`strict` and `selected`) cover scenario 13 |
| Drop the JSON policy codec from BG7; keep the FRR adapter and explanations | Nothing consumes JSON policies yet; the schema exists in the records |
| The FRR lane runs 10.7.1 and master by digest routinely; the pinned 10.5.4 fixtures run whenever `frr-10.5` behaviour changes | Two images cover `frr-modern`; a different release cannot certify the `frr-10.5` dialect |
| One test harness module (`tests/agents/harness.py`) rather than per-package fixtures | Already planned; stated as a rule |
| Decision flavors are two explicit functions plus a code-level named-class seam, not a step interpreter (§15.8) | Two known algorithms do not justify an interpreter; named replaceable flavors remain |

Simplicity rules added to section 7's invariants:
- no unrelated-table scan for a local edit (an op-count test per kind); affected closure, bulk configuration and SPF work, and amortized compaction are budgeted explicitly;
- no Python object per route, path or FIB entry outside API boundaries
  (a memory-per-row benchmark per table);
- no per-run tree write for identity outputs.

### 14.7 Revised milestone M1 and first actions

M1 now starts with S0 (one worker, one week) and F0 with delivery, then
F1a, RP1, F3, F4, F5 and F7a in parallel. Exit adds: linear build to 100k
devices under 60 s, idle run ≤ 40 µs with 0 B retained, admission O(k),
fingerprints unchanged.

First actions after approval:
1. S0 with its five benchmarks (each failing on the old code), as the first
   commit series.
2. F0 with zero-commit idle runs and the changed-key log records.
3. The rest of M1 in parallel.

---

## 15. Codex review of revision 6: dispositions and the contracts it required (revision 7)

Report: `netsim-protocols-research/codex-review-rev6.md` (GPT-6-Astra, xhigh;
26 minutes; every `scale-experiments` script re-run; four new probes, copied to
`scale-experiments/codex-probes/`). Verdict: S0 conditional go as a small
staged series; the expanded F0 of §14.6 no-go until the storage, publication,
scope, settings-delta and completion contracts exist. All 22 findings are
accepted; the integrator verified the source claims (ORIGINATOR_ID, confed
deferral, reinstall guard, SRv6 consumer copy, Open/R empty sync) and answered
the P0 with a new prototype. Where this section conflicts with earlier text,
this section wins; §15.9 is the authoritative dependency table.

### 15.1 P0: packed storage now has an immutable, incremental contract

**Finding.** The §14.3 prototypes mutate `array` and `dict` objects. The tree
admits only transitively immutable values (`validate_immutable` rejects
`array`; a read-only `memoryview` over a mutable buffer is not immutable); the
only safe packed pattern in the tree today is bytes-backed `FloatArray`
(`state.py:437-474`). Freezing a whole array per edit is O(table bytes).

**Contract: `PackedTable`** (model layer, `netsim/model/packed.py`), a
persistent vector of fixed-width rows:
- **Storage.** `chunks: tuple[bytes, ...]` of `CH` rows each (4096), a row
  struct per table kind (FIB row 16 B: prefix u64, plen u8, flags u8, group
  u32; path row 24 B: peer u32, attr u32, seq u64, flags u8 and padding), plus
  `count`. A 4096-row chunk is therefore 64 KB for 16 B rows and 96 KB for
  24 B rows.
  IPv6 prefixes use a 16-byte key field or a prefix-id indirection (below).
- **Identity.** Positions are private to one table generation. External
  references use logical keys (prefix, `(peer, path_id)`), or
  `(table_generation, slot, slot_generation)` checked on dereference; bare
  positions never cross a publication boundary (queued requests, dirty sets,
  back-indexes and completions carry logical identity or their snapshot).
  The **first implementation is append-only**: no slot reuse or compaction
  within a live generation, an explicit memory limit, and rebuilding at a
  generation boundary as one owner transaction that publishes the table, every
  index, the pools and the allocator together with an explicit old-to-new
  remap (a storage change, never a route withdrawal). Bounded churn is not
  claimed for that version. Old snapshots keep old chunks.
- **Builder.** Private, copy-on-write per chunk: the first write to a chunk
  copies 64 KB; further writes to that chunk are in place on the private copy;
  `build()` freezes touched chunks to `bytes` and emits a **change
  certificate**: logical adds, updates and deletes, bound to the exact base and
  result generations and naming its coordinate system and any remap. The
  trusted builder also validates row schema, bounds and references (generic
  immutability does not). No published chunk is ever mutated.
- **Admission.** `bytes` are leaves, so validating a 1M-row table costs 0.1 ms;
  no walk over rows.
- **Widths.** Attribute ids u32 (not the prototype's u16); peer ids u32;
  sequence u64; overflow is a validation error at the builder.
- **Index.** Small and full-table indexes implement the same exact lookup,
  LPM, exclusion and last-write-wins semantics. Bounded devices keep persistent
  per-length maps. For full-table devices the candidate is ordered
  `(network_key, row_reference)` entries in bounded sorted blocks behind a
  persistent block directory, with a defined 128-bit IPv6 ordering and family
  separation; a full per-length rebuild is a budgeted bulk operation, never
  the one-prefix edit. That index is adopted only after insertion, withdrawal,
  replacement, LPM and publication are measured under held snapshots
  (§16.2). The prototype's 0.24 µs bisect over a mutable key array is a lower
  bound, not that design.

**Measured on the prototype** (`scale-experiments/proto_chunked.py`, 1M rows):
16 B per row; one persistent single-row update 10 µs; held old snapshot
unchanged; 10k updates in one builder 4.7 ms; `validate_immutable` 0.1 ms.
Changed rows come from the builder log, not from diffing chunks (a diff of 2000
changes took 138 ms).

**Gate.** Before any protocol depends on it: tests holding an old snapshot
across insert, update, delete and compaction; admission; changed-row log
correctness against a brute-force diff; free-threaded readers on one snapshot;
edit and publication cost and retained-version memory measured.

### 15.2 P1s on measurements and passports

- **Passport arithmetic corrected (finding 2).** The 106 B per row dict index
  dominated and was omitted from the 2–3 GB figure. Revised budgets, per
  component, current plus retained history:
  - **P-A** (100k devices, 1M prefixes network-wide, ≤ 64 full-table devices):
    bounded devices at ≤ 8 KB each = 0.8 GB; full-table devices at ≤ 40 B per
    row (packed row 16 B, packed index 8 B, outcomes and group refs 16 B) =
    64 × 1M × 40 B = 2.6 GB; shared prefix dictionary and attribute pools
    0.2 GB; history bounded by retention settings. **Target ≤ 4 GB**, split by
    device class in the report.
  - **P-B** (16 BGP devices, 1M prefixes × 4 paths per device): Loc-RIB paths
    16 × 4M × 24 B = 1.5 GB; FIB and RIB rows 16 × 1M × 40 B = 0.6 GB;
    Adj-RIB-Out per group as packed (dest, attr) pairs; attribute pool shared.
    **Target ≤ 3 GB**; initial load measured across all 16 devices, not one
    table.
  - **P-C** unchanged in shape, with the workload named (areas, degree, prefix
    distribution, timers) and "idle" defined as identity-state timer work.

  Every passport reports `sum(submitted rows)`, selected rows, installed rows,
  paths, distinct attribute sets, update groups, queued NLRI and retained
  generations, and budgets current, peak-build and retained memory separately.
- **Measurement labels corrected (findings 3, 4).** Section 14.1's "80 B
  `Route`" is a `RowKey` tuple; the 296 MB is an allocation increment; the
  25 KB per device includes one loopback route; the DES probe fired 712k
  events, not 1M, so the raw core costs about **1.5 µs per timeout**; the
  "route add" in `proto_hfib.py` replaced an existing index entry. "Proved" in
  §14.3 means the mutable lower bound; §15.1 is the immutable design. The
  columnar-LPM rejection is withdrawn: packed columns save memory and cost
  lookup time, so the index is chosen per device class (above).

### 15.3 P1s on runtime and state semantics

- **Zero-commit idle runs are a Gate C slice, not F0 work (finding 5).** New
  slice **C6** after F0: pre-run RNG, counter and initialization state are
  captured in the per-generation journal; runtime state is published at the
  same success boundary as the tree, including the no-delta case; captured
  prefixes are consumed before external callbacks; parked rejection and
  explicit retry are preserved; receipts are exposed as a current view plus
  bounded history; reset, remove and generation purge clear every runtime
  map; `Network.fork()` does not clone a running scheduler. Gate: all Gate C
  tests plus no-delta RNG use, mixed batches, failed outer commit and
  post-publication callback failure. The S0 step is smaller: a versioned
  compact PRNG whose state (one 64-bit counter) changes only when drawn, with
  module streams derived by a fixed hash of `(seed, device, agent, module)`,
  never Python `hash()`.
- **Changed-key certificate for `PMap` (finding 6).** Its own reviewed state
  slice **S1**: the builder emits a delta (changed and deleted keys) certified
  against the exact base map identity; composition across staged edits;
  delete-then-reinsert and equal-but-different keys validate in full; an
  unrelated or rebuilt map falls back to full validation; the certificate is
  consumed on admission and never retains a parent chain. The shard count stays
  256 until a measured workload justifies bulk sizing.
- **More linear commit-path work (finding 7).** `srv6.consumer_index` copies
  the whole consumer frozenset on any device change (`srv6.py:1323-1332`;
  3.5 ms at 100k consumers): S0 keeps the object when membership is
  unchanged. `DeadlineHeap` becomes a shared persistent priority structure with
  stated update cost, not a tuple rebuilt per edit; watch indexes state their
  insertion cost. The invariant is reworded: no unrelated-table scan for a
  local edit; affected closure, bulk configuration and SPF work, and amortized
  compaction are budgeted explicitly. Op-count tests cover unchanged consumers,
  timer-only runs and one-key edits.
- **Lazy analytical mode gets a query contract (finding 8).** A pure
  `forwarding_query(snapshot, domain, device, prefix)` shared by trace and
  placement; memoized SPF as disposable runtime data keyed by input epochs with
  an eviction budget; old-snapshot answers preserved; never reachable from
  agents; enumeration, absent-route, aggregate and default semantics and
  invalidation defined; mode selection explicit, never by device count. It is
  its own analytical slice (**A1**) and does not block protocol work. P-A
  names the demanded source count.

### 15.4 P1s on the resolver and policy hooks

- **Cycle rule (finding 9).** Blanket `LOOP_DETECTED` for every member of a
  dependency cycle over-rejects: a route with a cyclic recursive leg **and** an
  independent direct leg must keep the direct leg. F1a's rule becomes per leg:
  a leg resolves when it has a finite witness within the depth bound; a leg
  whose resolution closes a cycle with no escape fails with `LOOP_DETECTED`;
  other legs of the same route are unaffected; weights are normalized over
  surviving legs. Tests: closed cycle, cycle plus direct leg (`resolver_escape.py`),
  cycle plus lower-priority candidate, blocked less-specific fallback, under
  every enumeration order.
- **`ip protocol` stage (finding 10).** The filter runs after next-hop
  activation, when the resolving interface is known, not at submission: a
  named **candidate-next-hop activation filter** in the resolver, per row,
  with FRR-equivalent activated-next-hop facts; positive and negative underlay
  dependencies recorded; reevaluated on their change without a new submission;
  fallback to another candidate when no leg survives. Native `RIB_ADMISSION`
  (submission) and native `FIB_INSTALL` stay distinct. The shared evaluator
  is reused with its own capability row.
- **Scope in shared keys (finding 11).** `RecursiveNexthop` keys include
  interface identity and generation for link-local addresses and every
  resolution-changing scope; owner and client projections (policy binding,
  query mode) are keyed separately and applied per row, never to a shared
  group. `nht_filtered` receives the selected row's tag, metric, distance and
  source and its activated next hops from the processed snapshot.
- **No import-policy memoization (finding 12).** Policies depend on the
  prefix and context, not only the attributes; §5.10's memoization is removed.
  Compiled bindings are reused; results are not.

### 15.5 P1s on settings and configuration

- **Root settings delta (finding 13).** `NetworkState.settings` is added to
  the root fields `StateDelta.changed_paths()` enumerates, and to batch and
  fork preservation; a settings-only update is never an empty delta. Desired
  layer changes and effective changes are tracked separately, and only the
  latter schedule protocol work. Dumps serialize explicit values and
  inheritance intent, not only differences from dialect defaults. Tests:
  equal-effective edit followed by a parent change; clear and unset; dump and
  load; aborted batch; fork; reset.
- **One action plan per transaction (finding 14).** A configuration
  transaction resolves the complete candidate, diffs old and new effective
  records once, and compiles one per-owner plan with a dominance order: reset
  or restart supersedes session work; recalculation, export and replay
  coalesce against the new revision; `NEXT_SESSION` keeps its pending intent.
  Preset precedence is stated with two conflicting examples (a preset's
  neighbor value against an explicitly inherited instance value; preset
  profile metadata against user layers) and unsupported combinations are
  rejected. Minimal provenance sufficient to explain each winner ships in F7a.

### 15.6 P1s on programming, sync and sessions

- **Group versions (finding 15).** Installed forwarding dereferences
  **installed** group content. An underlay change programs the group once and
  advances its installed version at the completion boundary; prefixes keep
  their group reference and are not re-requested. Prefix obligations name the
  installed route or group generation they need; obsolete completions cannot
  release a gate; installed content survives a pending or failed DELETE.
  Minimal F8 keeps an explicit ERROR completion and a deterministic injection
  seam, because pending, error and success must be distinguishable.
- **Open/R sync completion (finding 16).** An owner- and generation-scoped
  sync completion event with batch identity and explicit successful and failed
  members, including the empty set (Open/R publishes an empty FULL_SYNC,
  `Fib.cpp:386-401, 849-859`). PrefixManager's gate applies only to entries
  that carry next hops (`PrefixManager.cpp:650-662`). OR3 depends on this
  minimal F8 contract.
- **Listener accept identity (finding 17).** The accept table is keyed by
  scoped remote identity: AF, address and ingress interface identity and
  generation where the address is link-local; that scope flows through
  connection lookup, accept options and collision identity. Listen ranges are
  a separate matching mode for globally scoped addresses.

### 15.7 BGP corrections (findings 18, 19, 20)

- **Reinstall.** For an unchanged best path with unchanged attributes and no
  clear or add-path in effect, use FRR's reduced change flags
  (`bgp_route.c:4439-4462`); otherwise compare the complete emitted local row
  and replace it when its semantics change. A MED edit changes the installed
  metric.
- **Route reflection.** ORIGINATOR_ID is set only if absent
  (`bgp_route.c:2820-2825`); `force` affects ordinary next-hop-self on
  reflection; with `allow-outbound-policy` a route-map may rewrite the next
  hop and an explicit rewrite prevents the automatic reset. Tests: two RRs in
  series; an allowed route-map rewrite.
- **Confederation step.** Step 10 returns immediately by default and defers
  under `bgp bestpath peer-type multipath-relax` (`bgp_route.c:1654-1684`);
  both are tested.
- **suppress-fib-pending.** `bgp_check_withdrawal` returns "withdraw" for any
  non-selected non-NORMAL path before the selected-static exemption
  (`bgp_route.h:779-801`); the FRR profile gets an explicit event and state
  projection with source-backed fixtures (selected `network` plus a
  non-selected local path; delayed failure; better-admin; generic removal) and
  is not reduced to `strict` plus flags.
- **Multipath ceiling.** The build ceiling is package data: FRR's Debian
  packaging configures 256 for both 10.5.4 and master; SONiC's 514 is SONiC's
  own build value; the template configures 64. `frr-10.5` behaviour changes
  run the pinned 10.5.4 fixtures.

### 15.8 Streamlining, revised (findings 21, 22)

- **Decision flavors are two explicit functions**, `frr_select` and
  `rfc4271_select`, over the same narrow immutable inputs, sharing small
  comparison helpers with source references. No step interpreter, no
  hold/release slots. The extension seam is code: a flavor is a named class
  implementing `DecisionFlavor` (`compare`, `select`, `multipath`) added to the
  per-agent flavor table at deployment; configuration selects by name. This
  keeps "named, replaceable flavors" without an interpreter.
- **Settings start small:** typed desired and effective records, explicit
  resolution, a small action planner, unknown keys rejected, precedence and
  default tests. Generated-documentation enforcement, the key-field bijection
  check and broad selector syntax move to F7b or later.
- **Policy evaluator stays as reviewed:** four flows, typed capability table,
  no result cache, no regex, VM or callbacks.
- **Kept early because they prevent rewrites:** source-exact decision
  fixtures, one settings transaction, one submission boundary, installed
  versus desired group semantics, scoped NHT, immutable snapshots, exactly-once
  publication, ERROR completion, empty sync.

### 15.9 Authoritative slices and dependencies (supersedes §8, §12.1 and §14.7)

| Slice | Content | Needs |
|---|---|---|
| S0 | locator index; arithmetic masks; bounded retention defaults; SRv6 consumer index without copy; compact PRNG (state changes only when drawn) | – |
| S1a | `PMap` changed-key certificate (§16.2) | S0 |
| S1b | `PackedTable` (append-only first version) and its index gate (§16.1, §16.2) | S0 |
| F0 | additive contract records only: commands, views, persistent, RIB feed, `RowNotice`, NHT modes, transport options, settings root field with delta, labels, packed-table and programming record types, F1/F2 shared records | – |
| C6 | zero-commit publication and off-tree runtime bookkeeping (§15.3) | F0 |
| F1a | order-independent resolver with the per-leg cycle rule; extended fingerprints | F0 |
| F2a | delivery of F0 records (commands, config, views, change keys) | F0, C6 |
| F3 | transport: scoped accept identity, TTL, GTSM, wildcard listeners | F0 |
| F4 | domain oracle (materialized); A1 lazy mode is separate | F0 |
| F5 | toolkit: spf, timers (shared persistent priority structure), routeops, sizes, refs, harness | – |
| F7a | settings: schema, dialects and profiles as data, device layer, transaction and action plan, root delta, minimal provenance | F0 |
| RP1 | route-policy language and evaluator | F0, F7a |
| F1b + F2b + F8 | one integration boundary with one merge owner for `derive.py`, `forwarding.py`, row and group completion: persistent packed FIB with group versions; RIB submission boundary; RIB feed and owner notifications; NHT installed mode; programming contract with ERROR completion and sync completion | S1, F1a, F2a |
| F1c | incremental resolution with the full resolver as oracle | F1b, design gate |
| F2c | runtime scale (lazy context, per-client identity notifications, admission via S1a) | F2a, S1a; performance exit after X |
| RP3 | RIB admission with retained submissions; candidate-next-hop activation filter (`ip protocol`, per original activated next hop); `nht` scope | F1b/F2b/F8, RP1 |
| RP4 | forwarding-scope resolution filter; `FIB_INSTALL` exclusion | F1c, F8, RP1 |
| A1 | lazy analytical forwarding query | F4, F1b |
| F7b | group selectors, presets, `explain`, generated docs | F7a |
| OR1 | Spark and the agent shell | F0, F2a, F5, F7a |
| OR2 | LinkMonitor and KvStore | OR1 |
| OR3 | Decision, PrefixManager, Fib with sync completion | OR2, F1b/F2b/F8 |
| OR4 | multi-area | OR3 |
| OR5 | drain, overload, RIB-feed injection | OR4, RP1 |
| OR6 | passport, study integration, learned SR | OR5; performance exit F1c, F2c |
| BG1 | types, AS_PATH, peers, settings fragment | F5, F7a |
| BG2 | sessions and FSM; a session-only NHT registration (`rib` mode) for connect gating until installed mode lands in X | BG1, F2a, F3 |
| BG3 | inbound, next hops and path tracking, the `frr` and `rfc4271` flavors, Loc-RIB on `PackedTable` with stable path slots, install; differential source fixtures | BG2, F1b/F2b/F8, F4, RP1, S1b; performance exit F1c, F2c |
| BG4 | outbound, policy hooks, MRAI, gate profiles, origination | BG3; performance exit F1c, F2c |
| BG5, BG6 | RR, confederations | BG4 |
| BG7 | conformance, FRR adapter, lane | BG5, BG6 |
| IX | integration scenarios | OR6, BG7, RP4, A1, F7b |

Milestones: **M0** S0, F0, F5 · **M1** S1, C6, F1a, F2a, F3, F4, F7a, RP1 · **M2** the
F1b/F2b/F8 boundary, then F1c, F2c, RP3, A1 · **M3** OR1–OR3, BG1–BG3 · **M4**
OR4–OR5, BG4–BG6, RP4, F7b · **M5** OR6, BG7, IX · **M6** docs and final review.
Reviews after M0+M1, after the F1b/F2b/F8 boundary, after M3 and at the end.

### 15.10 Readiness

S0 can start now, as a staged series with reproducers first. F0's additive
records can start with S0. S1 and C6 start by writing their own gates; F3, F4,
F5 and F7a do not wait for `PackedTable`. Consumers of `PackedTable` and of
zero-commit publication merge only after the corresponding gates **pass**
(§16.9).

---

## 16. Codex review of revision 7: dispositions (revision 8)

Report: `netsim-protocols-research/codex-review-rev7.md` (GPT-6-Astra, xhigh;
17 minutes; 1 P0, 14 P1, 1 P2; probes copied to
`scale-experiments/codex-probes-rev7/`). All 16 findings are accepted. The body
text they contradicted has been corrected in place (D4, F5, F0, F1b, the F3
signature, §5.8, §5.13, §13.9, §14, §15.1 and §15.10); this section records the
decisions and the contracts that remain to be built. Where it conflicts with
§15, §16 wins.

### 16.1 P0: identity across compaction (finding 1)

Positions are private to a table generation; external references are logical
keys or `(table_generation, slot, slot_generation)`; the first `PackedTable` is
append-only with rebuild at a generation boundary in one owner transaction
(table, indexes, pools, allocator, remap). The change certificate is bound to
exact base and result generations and names its coordinate system. Gate:
held-snapshot tests across insert, update, delete and rebuild; stale queued
references; remap failure rolling back everything; certificate correctness
against a brute-force logical diff.

### 16.2 Indexes, budgets and admission (findings 2, 3, 4)

- No mandated packed sorted column. Bounded devices keep persistent per-length
  maps; full-table devices adopt bounded sorted blocks behind a persistent
  directory only after their update benchmark passes; 128-bit IPv6 ordering
  and `(network_key, row_reference)` entries are required; numeric prefix ids
  are not address-order keys.
- The 40 B per row and 24 B per path figures are hypotheses for named layouts.
  The **common submitted and admitted RIB with its three indexes** is assigned
  to the X boundary owner (F1b/F2b/F8); if it stays an object RIB, the P-A
  ceiling is revised upward and stated. BG3 uses stable path slots plus a
  bounded per-destination membership and order structure, never monolithic
  CSR. Passports report current, builder-peak, rebuild-peak and retained
  history separately; P-A names links, interfaces and local rows per device;
  P-C is instantiated (areas, degree, distribution, timers) before it can pass.
- Generic immutability and semantic admission are distinct. Certificates are
  immutable evidence that never mutate a published map or table; an
  owner-local admission transaction composes edits back to the admitted base;
  a missing or mismatched certificate means full validation; no unbounded
  ancestor chain. The same lifecycle covers `set`, `remove`, `update`,
  `build` and the packed builder. S1 splits into **S1a** (`PMap` certificate)
  and **S1b** (`PackedTable` and its index), each with its own gate.

### 16.3 Publication, initialization, PRNG (findings 5, 6, 7)

- **C6 publication seam.** A non-user-code finalizer commits accepted runtime
  successors at the root publication point, **before root observers**, and
  performs the same transition on accepted no-delta batches; a failed outer
  commit publishes neither side and keeps retry captures; captured prefixes
  are consumed before external callbacks; the pipeline distinguishes prepare,
  abort, publish and external finalization. Tests place an observer ahead of
  the runtime observers and inject an outer commit failure. `after_run` alone
  is not the publication hook.
- **Initialization stays in the tree.** `AgentNode.initialized` remains a
  one-time tree transition on a successful `on_init`; only per-run bookkeeping
  (`runs`, `receipt`, `rng`) leaves the tree. Fresh runtimes keep today's
  generation and reset semantics. Current receipts come from an explicit
  `Simulation`/`AgentRuntime` API as freshly frozen values; bounded
  `AgentRunEvent`s are emitted at runtime publication even without a root
  delta; old snapshots never acquire newer receipts.
- **PRNG.** A named, versioned generator with golden vectors; **one counter per
  declared module stream**, persisted across accepted runs, advanced only when
  drawn; stream keys from a fixed encoding hashed with blake2b of network seed,
  device identity, agent identity, generation and module; rejected runs
  restore every counter; a stated supported API and reset rule; the change
  from MT seed sequences documented. This is the S0 W3 contract.

### 16.4 Resolver and policy hooks (findings 8, 9)

- **Per-leg witnesses.** F1a defines a finite, non-self-supporting resolution
  witness with its candidate and exclusion context; depth is checked per
  witness, not by one scalar per record; cyclic branches contribute no weight
  unless an explicitly permitted acyclic escape exists; lower-ranked and
  less-specific fallback obey the selection and `lpm_fallthrough` rules;
  `all_or_nothing` is preserved; deduplication and weight combination are
  deterministic; cached physical results are reused only where exclusion
  context and remaining depth cannot change the answer. Tests add
  cycle-with-two-exits, unequal branch depths, cycle plus lower-ranked
  candidate, all-or-nothing, repeated adjacency with unequal weights and a
  blocked covering prefix, under every enumeration order.
- **Activation filter.** The FRR attachment evaluates once per **original
  candidate next hop** after activation, with that next hop's activated type,
  address, ifindex and recursion state plus permitted row facts; it preserves
  the system-route and family bypasses; a deny deactivates the original next
  hop and its resolved contribution, never each flattened child independently
  (`zebra_nhg.c:2403-2406, 2622-2628, 2693-2716, 2909-2917`;
  `zebra_routemap.c:70-87`). Native submission admission and native
  whole-action FIB policy stay separate capability rows.

### 16.5 Programming, sync, feeds (findings 10, 11, 12)

- **Route and group obligations.** Separate route and group request
  identities, desired and installed generations, and explicit dependency
  completion: a route becomes installed only when its group content is
  installed, and the prior installed action survives until then. Group-only
  updates avoid per-prefix programming only while selection and eligibility
  are unchanged; loss of eligibility triggers the budgeted affected-prefix
  re-election (F1c). Supersession is resolved once at the group obligation;
  obsolete acknowledgements never satisfy newer intents. Reclamation counts
  desired, installed and in-flight references; snapshots own their data.
  `installed=None while PENDING` is a desired-row projection and never erases
  a retained installed action. Installed NHT and forwarding read installed
  content and matching provenance.
- **Sync operations.** An accepted sync carries owner, generation and batch id
  even when its RIB edit is identity (`rib_apply(empty, sync=...)` returns the
  same RIB today). The programming boundary tracks the batch's upserts and
  deletions, including cleanup of retained installed routes, and emits one
  immutable completion with per-operation success and failure or a distinct
  total failure; an empty no-work batch completes successfully; failed
  removals are never omitted. Partial success reaches Open/R with failed
  members scheduled for retry; total failure does not advance initial sync.
  These records belong to F0 and the X owner, not to OR3 reconstruction.
- **Route feed coalescing.** Messages identify baseline and result epochs;
  coalescing composes per-key final upserts and removals relative to the last
  captured baseline (disjoint edits are preserved, net no-ops cancel);
  registration and reset snapshots are distinct; large snapshots and change
  sets use bounded pages or immutable table-backed views with declared byte
  limits and an explicit resync outcome; entry count is not a memory bound.

### 16.6 Settings decisions (finding 13)

- Root settings delta integration is **F0**; resolution and the per-owner
  action plan are **F7a**. Desired-layer edits are preserved when effective
  values are equal.
- Preset precedence, decided: an explicitly inherited user instance value
  (100) beats a preset's neighbor value (200); only absent explicit inheritance
  falls back to presets. An explicit user profile (`datacenter`) beats a preset
  profile (`traditional`); without a user profile the preset supplies it.
  Preset recursion and conflicting meta-key combinations are rejected.

### 16.7 RFC 8212 (finding 15)

Missing policy discards received routes and suppresses advertisements per AF
and direction; the session still establishes; the state is reported in views;
configuration and OPEN are never rejected for it. Scenario 9 pins Established
with zero accepted and advertised prefixes, independent directions and AFs, and
behaviour after attaching policy.

### 16.8 Body cleanup and A1 (finding 16)

Applied in place: no step interpreter (D4, F5, §12), scoped listener and
recursive keys, a shared timer facility instead of a tuple heap, corrected §14
rows, §13.9 reflection wording, the 10.5.4 fixture rule, and the exemption
wording in §5.13. Deferred by §14.6 and now consistent: JSON codec and
stochastic capacity or lost-completion models; ERROR, empty sync and stale-ACK
tests stay. **A1 mini-contract**, required before A1 starts: address-LPM and
exact-prefix queries; enumerable materialized state; absent, default and
aggregate answers; domain identity; cache lifetime; old-snapshot behaviour;
never a silent replacement of materialized RIB semantics.

### 16.9 Slices, edges and owners (finding 14; amends §15.9)

Edges added: RP1 → RP3, RP4, OR5; OR1 → OR2; OR4 and OR5 → OR6; BG5 → BG7;
F2c's performance exit waits for X (its lazy-context work may start after F2a
and S1a); BG2 owns a session-only NHT registration in `rib` mode until the
installed mode lands in X, and BG3 owns path tracking. Functional and
performance gates are separate for every protocol slice (BG3 and BG4 keep
their F1c/F2c performance gates). IX depends on OR6, BG7, RP4, A1 and F7b.

Owners: one state owner for S1a and S1b; one C6 owner for `agents.py`,
`pipeline.py`, `network.py` publication and runtime receipt events; F0 owns
root settings-delta integration; F7a owns its resolver and planner; the X
merge owner coordinates `routing.py`, `lpm.py`, `nht.py`, `derive.py`,
`forwarding.py` and `timeline.py` against one reviewed storage and programming
contract; F2c consumes S1 and X. The worker template distributes §15.9 as
amended here.

Milestones: **M0** S0, F0, F5 · **M1** S1a, S1b gate, C6, F1a, F2a, F3, F4, F7a,
RP1 · **M2** X (F1b/F2b/F8), then F1c, F2c, RP3, A1 · **M3** OR1–OR3, BG1–BG3 ·
**M4** OR4–OR5, BG4–BG6, RP4, F7b · **M5** OR6, BG7, IX · **M6** docs and
final review.

### 16.10 Readiness

S0 continues as a staged series (W1 locator index and SRv6 consumer copy,
W2 masks and retention, W3 PRNG per §16.3). S1a and S1b start by writing their
gates; F0's additive records proceed, with the listener, recursive-resolution,
programming, sync and packed-table records frozen only after §16.1–16.5 are
in their signatures; C6 starts with its seam design and tests; F3, F4, F5 and
F7a do not wait.

---

## 17. S0 delivered (2026-09-27)

Three Codex xhigh workers on isolated worktree branches, integrated on `main`
locally (not pushed) after `make check-ci` and `make check-ft` on the merged
tree: **1,759 passed, 14 skipped, coverage 95.40 %** on CPython 3.14.5 and
3.14.5t. Handoff reports: `docs/history/s0-w1-locator-index.md`,
`docs/history/s0-w2-masks-retention.md`, `docs/history/s0-w3-prng.md`.

| Fix | Change | Regression test (fails on `0e5b299`) |
|---|---|---|
| Locator scan (G17) | An off-tree immutable index `(device, locator) → block`, maintained by identity diff at every `update()` boundary, inside batches and on fork; validation is O(locators) and skipped for IPv4-only interfaces | `tests/model/test_s0_locator_consumer.py` (25 cases: linear operation count, atomic rejection, rollback, fork, root replacement) |
| SRv6 consumer copy | `consumer_index` returns the previous frozenset when membership is unchanged | same file: identity kept across an unrelated commit |
| Mask tuples (G20) | Shift arithmetic; `FrozenPrefixTable` and `PrefixTable` hold no masks; the `masks` parameter removed from `_owned` and its callers | `tests/model/test_lpm_scale.py` (1,000 tables: 1.5–6.9 MB → 0.15 MB) |
| Unbounded retention | `Simulation` and `Timeline` default to `keep_records=10_000`, `keep_events=100_000`; `Study` follows; explicit `None` stays unbounded; documented in `docs/reference.md` | `tests/runtime/test_timeline_retention.py` |
| MT state per run (G18) | `netsim/model/prng.py`: versioned SplitMix64 with per-stream counters, blake2b-derived stream keys, identity reuse when nothing is drawn; `ctx.rng` is a `Prng` with the documented API; `AgentNode.rng` holds a sorted tuple of `(stream, counter)` or `None` | `tests/runtime/test_prng.py`, `test_agent_prng.py`, `test_agent_prng_retention.py` (golden vectors, stream isolation, `PYTHONHASHSEED` independence, O(1) retention) |

Old/new/old on the same machine (load about 2.3, fresh sequential processes,
`scale-experiments`-style probe at 2k and 6k devices):

| Metric | `0e5b299` | S0 |
|---|---|---|
| build, 2k / 6k devices | 3.8 s / 34 s (1.9 / 5.7 ms per device, quadratic) | 0.13 s / 0.40 s (66 / 67 µs per device, linear) |
| converge, no protocol routes | 25.4 KB per device | 9.5 KB per device |
| idle agent run, retained | 26.9 KB per run | 1.8 KB per run |
| idle agent run, time (under tracemalloc) | 563 µs | 461 µs; the per-run tree commit remains and is the C6 target |

W1's and W2's provisional numbers (build 52 s → 0.6 s at 8k; consumer helper
3.5 ms → 1.5 µs at 100k; converge 50.9 → 19.2 MB at 2k) are consistent with
these. Fingerprints are unchanged. Not done in S0, by design: the `PMap`
changed-key certificate (S1a), packed storage (S1b) and zero-commit publication
(C6).

**S0 review fix (2026-10-02).** A Codex xhigh adversarial review of the merged S0
diff (`netsim-protocols-research/codex-review-s0.md`) confirmed one P2 and no
P0/P1: `Device.configure(seed=...)` or a `Network.seed` edit on a live agent
re-keyed its `Prng` family mid-generation, changing the sequence without a
reset and accumulating counters (64 edits → 65 entries). Fix: the v1 committed
state is now `(key, counters)`; the key is hashed once at the generation's
first publication (`Prng.for_agent`) and restored by `Prng.restore` afterwards,
so seed edits take effect only at `reset_agent`/`restart_all`, as under the
old MT seeding. `AgentNode.rng` is `None` only before the first publication.
Also applied: `Study` with `keep={'arrays': True}` or `{'timeline': True}`
selects unbounded events unless `events` is given; `_randbelow` rejects
non-positive bounds; `lookup` is pinned to `lookup_iter`; the workload
retention tests assert explicit defaults. Lifecycle tests in
`tests/runtime/test_agent_prng.py` (seed edit before/after first publication,
64 edits with change-back, rejection then edit then retry, reset and restart
adopting new seeds).
