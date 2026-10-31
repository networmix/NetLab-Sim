# Roadmap

This page is for maintainers. It is the rolling product roadmap and the only
place that records the state of planned work: what each slice of work is, what
it needs first, whether its contract is ready and whether it is implemented.
The user documentation
([README](../README.md) and [reference](reference.md)) describes what the
code does today. The future behaviour that this plan builds is specified in
[docs/design](design/README.md); nothing on those pages is available until its
row here says so.

## Goal

NetLab-Sim gets a faithful Open/R IGP and a BGP that follows the RFCs first
and modern FRR where the RFCs leave room. Both run as protocol agents on the
existing agent contract, with no privileged path into the model. They share a
foundation: stable storage and change certificates for large tables, agent
runs that publish nothing when nothing changed, an order-independent recursive
resolver, a persistent FIB with an asynchronous programming contract, a
per-node settings system, one route-policy language with its device hooks, and
a protocol toolkit. Integration scenarios combine the IGP and BGP in the
deployment shapes the design names.

## Boundaries

- The plan adds behaviour. Scenarios a slice does not affect keep the
  behaviour the [README](../README.md) and [reference](reference.md) describe.
  A slice may change an existing answer only as its contract states: to
  correct a demonstrated defect, with the reproducer reviewed (F1a's
  [examples](design/protocols.md#two-separating-examples)), or as a documented
  interface change with its intended differences reviewed (for example, X's
  group timeline events).
- Contracts live in [docs/design](design/README.md). This page holds order and
  state, not requirements.
- Functional and performance gates are separate for every protocol slice.
- Items listed under [Optional and deferred](#optional-and-deferred) are not
  scheduled.

## Status values

**Contract**

- `pending`: requirements exist but are not yet reconciled and reviewed into a
  contract an implementation can start from. The link names the current
  source: a design page, or an archived plan section listed on it.
- `ready`: the linked design page holds a reviewed contract for this slice.
- `—`: delivered before this roadmap; the current code and user documentation
  define the behaviour.

**Implementation**

- `planned`: none of the slice is in the product.
- `partly implemented`: part of the slice is in the product; the evidence
  names which part.
- `implemented`: the slice is in the product.

## What this page records

The rows state product facts: what the slice is, what it depends on, whether
its contract is ready and how much of it the product contains, with in-repo
witnesses (tests, history reports, user documentation). They do not record
how the work is run: an effort's plan revision, task acceptance, reviews and
CI results live in that effort's own records, outside the repository. Items
that landed before this roadmap keep their known landing commits as history.

## Maintaining the roadmap

- One row per slice. IDs never change and are never reused; a split gets new
  IDs (S1 became S1a and S1b) and the old ID disappears from the table.
- Change a row in the same commit that changes the slice's scope or
  dependencies, makes its contract ready, or lands part or all of its
  implementation. Its evidence names the in-repo witnesses of that change; a
  row never tries to name the commit that changes it.
- Status words live only in this table. Design pages state requirements, and
  history reports and the archive keep the facts of their date.
- When this table and a design page disagree on order or dependencies, this
  table wins; when they disagree on behaviour, the design page wins.

The rows were assessed at commit `4514276` (31 October 2026); each later row
changes in the commit that changes the product.

## Slices

The protocol design's authoritative slice table, with its later amendments of
edges, applied. `X` is the integration boundary F1b + F2b + F8, which lands as
one change.

| ID | Work | Needs | Contract | Implementation | Evidence |
|---|---|---|---|---|---|
| Gate A | Plain-IP simulator: state tree, interfaces, static and oracle routing, recursive FIB resolver, placement, studies, NetGraph and Core adapters; scale fixes T1–T7 | – | [—](../README.md#network-layer) | implemented | Landed `c2d658e`…`01591de`; reports [T1](history/t1-pmap-sharding.md), [T2](history/t2-scoped-batches.md), [T2B](history/t2b-convergence-boundaries.md), [T2C](history/t2c-committed-root-derivations.md), [T3](history/t3-rib-indexes.md), [T3B](history/t3b-rib-updates.md), [T4](history/t4-deadline-heap.md), [T6](history/t6-failure-studies.md), [T7](history/t7-scoped-l3.md) |
| Gate B | SRv6: SIDs and micro-SIDs, SR policies and steering, NEXT-C-SID, packet chains, SONiC subset | – | [—](../README.md#segment-routing) | implemented | Landed `ecd32d6`…`02c9fbb`; no history report |
| Gate C | Agent contract, NHT, transport and sessions, reference link-state agent, study windows | – | [—](../README.md#protocol-agents) | implemented | Landed `9032ea8`…`380691a`; reports [C2](history/c2-nht.md), [C2F](history/c2f-nht-runtime-seams.md), [C2R](history/c2r-nht-detached-queries.md), [C4](history/c4-reference-agent.md), [C5](history/c5-study-windows.md) |
| S0 | Scale hygiene: locator index, SRv6 consumer index without copy, arithmetic masks, bounded retention defaults, compact PRNG | – | [—](reference.md) | implemented | Landed `27e92cd`…`b10be0e`, seed lifecycle fix `9d53746`; reports [W1](history/s0-w1-locator-index.md), [W2](history/s0-w2-masks-retention.md), [W3](history/s0-w3-prng.md) |
| S1a | `PMap` changed-key certificate | S0 | [pending](design/protocols.md#s1a-and-s1b-certificates-and-packed-tables) | planned | |
| S1b | `PackedTable`, append-only first version, and its index gate | S0 | [pending](design/protocols.md#s1a-and-s1b-certificates-and-packed-tables) | planned | |
| F0 | Additive contract records: commands, views, persistent state, RIB feed, `RowNotice`, NHT modes, transport options, settings root field with delta, labels, packed-table and programming record types, records F1 and F2 share | – | [pending](design/protocols.md#f0-contract-additions) | planned | Known gap: [client profiles are network-wide](design/protocols.md#per-node-client-profiles) |
| C6 | Zero-commit publication and off-tree runtime bookkeeping | F0 | [pending](design/protocols.md#c6-zero-commit-publication) | planned | Known gap: [an idle agent run still commits](design/protocols.md#current-behaviour) |
| F1a | Order-independent resolver with the per-leg cycle rule; extended fingerprints | F0 | [pending](design/protocols.md#f1a-order-independent-resolver) | planned | Known defect: [answers depend on unrelated routes and order](design/protocols.md#two-separating-examples) |
| F2a | Delivery of F0 records: commands, configuration, views, change keys | F0, C6 | [pending](design/protocols.md#pending-contracts) | planned | |
| F3 | Transport: scoped accept identity, TTL, GTSM, wildcard listeners | F0 | [pending](design/protocols.md#pending-contracts) | planned | |
| F4 | Domain-scoped oracle IGP, materialized | F0 | [pending](design/protocols.md#pending-contracts) | planned | |
| F5 | Protocol toolkit: SPF, timers on a shared persistent priority structure, route operations, sizes, references, test harness | – | [pending](design/protocols.md#f5-protocol-toolkit) | planned | |
| F7a | Settings: schema, dialects and profiles as data, device layer, transaction and action plan, root delta, minimal provenance | F0 | [pending](design/protocols.md#pending-contracts) | planned | |
| RP1 | Route-policy language and evaluator | F0, F7a | [pending](design/routing-policy.md) | planned | |
| X | F1b + F2b + F8: persistent packed FIB with group versions; RIB submission boundary; RIB feed and owner notifications; NHT installed mode; programming contract with ERROR completion and sync completion | S1a, S1b, F1a, F2a | [pending](design/protocols.md#pending-contracts) | planned | |
| F1c | Incremental resolution with the full resolver as oracle | X, design gate | [pending](design/protocols.md#pending-contracts) | planned | |
| F2c | Runtime scale: lazy context, per-client identity notifications, admission via S1a | F2a, S1a; performance exit after X | [pending](design/protocols.md#pending-contracts) | planned | |
| RP3 | RIB admission with retained submissions; candidate-next-hop activation filter per original next hop; `nht` resolution scope | X, RP1 | [pending](design/routing-policy.md) | planned | |
| RP4 | Forwarding-scope resolution filter; `FIB_INSTALL` exclusion | F1c, X, RP1 | [pending](design/routing-policy.md) | planned | |
| A1 | Lazy analytical forwarding query | F4, X | [pending](design/protocols.md#pending-contracts) | planned | |
| F7b | Group selectors, presets, `explain`, generated settings docs | F7a | [pending](design/protocols.md#pending-contracts) | planned | |
| OR1 | Open/R Spark and the agent shell | F0, F2a, F5, F7a | [pending](design/protocols.md#pending-contracts) | planned | |
| OR2 | LinkMonitor and KvStore | OR1 | [pending](design/protocols.md#pending-contracts) | planned | |
| OR3 | Decision, PrefixManager, Fib with sync completion | OR2, X | [pending](design/protocols.md#pending-contracts) | planned | |
| OR4 | Multi-area | OR3 | [pending](design/protocols.md#pending-contracts) | planned | |
| OR5 | Drain, overload, RIB-feed injection | OR4, RP1 | [pending](design/protocols.md#pending-contracts) | planned | |
| OR6 | Passport, study integration, learned SR | OR4, OR5; performance exit F1c, F2c | [pending](design/protocols.md#pending-contracts) | planned | |
| BG1 | BGP types, AS_PATH, peers, settings fragment | F5, F7a | [pending](design/protocols.md#pending-contracts) | planned | |
| BG2 | Sessions and FSM; a session-only NHT registration in `rib` mode for connect gating until the installed mode lands in X | BG1, F2a, F3 | [pending](design/protocols.md#pending-contracts) | planned | |
| BG3 | Inbound, next hops and path tracking, the `frr` and `rfc4271` decision flavors, Loc-RIB on `PackedTable` with stable path slots, install; differential source fixtures | BG2, X, F4, RP1, S1b; performance exit F1c, F2c | [pending](design/protocols.md#pending-contracts) | planned | |
| BG4 | Outbound, policy hooks, MRAI, gate profiles, origination | BG3; performance exit F1c, F2c | [pending](design/protocols.md#pending-contracts) | planned | |
| BG5 | Route reflection | BG4 | [pending](design/protocols.md#pending-contracts) | planned | |
| BG6 | Confederations | BG4 | [pending](design/protocols.md#pending-contracts) | planned | |
| BG7 | Conformance, FRR adapter and route-policy interfaces, differential lane | BG5, BG6 | [pending](design/protocols.md#pending-contracts) | planned | |
| IX | Integration scenarios | OR6, BG7, RP4, A1, F7b | [pending](design/protocols.md#pending-contracts) | planned | |

## Milestones

- **M0**: S0, F0, F5. Open: F0 and F5 are planned.
- **M1**: S1a, the S1b gate, C6, F1a, F2a, F3, F4, F7a, RP1.
- **M2**: X, then F1c, F2c, RP3, A1.
- **M3**: OR1–OR3, BG1–BG3.
- **M4**: OR4–OR5, BG4–BG6, RP4, F7b.
- **M5**: OR6, BG7, IX.
- **M6**: user documentation and final review.

Design reviews run after M0 and M1 together, after X, after M3 and at the
end. Route-policy work maps onto
these slices as stated in [routing-policy](design/routing-policy.md#slices).

## Landing rules

- S1a and S1b each start by writing their gate. Consumers of `PackedTable` and
  of zero-commit publication merge only after the corresponding gate passes.
- F0's additive records can land early. The listener, recursive-resolution,
  programming, sync and packed-table records are frozen only after the
  [identity, publication, resolver and programming obligations](design/protocols.md#f0-contract-additions)
  are in their signatures.
- C6 starts with its publication-seam design and tests. F3, F4, F5 and F7a do
  not wait for `PackedTable`.
- S1a and S1b change the same state layer and land as one coordinated series,
  not as independent parallel edits. C6 alone changes the agent publication
  path in `netlab_sim/runtime/agents.py`, `netlab_sim/runtime/pipeline.py` and
  `netlab_sim/model/network.py` and the runtime receipt events.
- F0 owns the root settings-delta integration; F7a owns settings resolution and
  the action planner.
- X lands as one change against one reviewed storage and programming contract:
  `routing.py`, `lpm.py`, `nht.py`, `derive.py`, `forwarding.py` (in
  `netlab_sim/model/`) and `netlab_sim/runtime/timeline.py` change together.
  F2c consumes S1 and X.
- BG2 owns the temporary `rib`-mode session registration; BG3 owns path
  tracking.

## Backlog outside the protocol plan

Identified work with a stable ID, not part of the slice table or its
dependencies, and not scheduled:

- **NG-026**: port the `netlab-sim run` CLI to NetGraph 0.26.
  `netlab_sim/cli.py` calls `Scenario.run()`; NetGraph 0.26 replaced that
  pattern with `ngraph.prepare(...)` and `ngraph.run(...)`
  ([NetGraph 0.26 API, Results and export](https://github.com/networmix/NetGraph/blob/v0.26.0/docs/reference/api.md#results-and-export)).
  Whether the optional NetGraph adapter needs other changes is part of the
  port.

## Optional and deferred

Not in the table, and not scheduled:

- **F6**, downstream invalidation narrowed by FIB diffs: optional, only if
  integration profiles show the conservative scans dominating
  ([source](design/archive/protocols-r8.md#f6-downstream-invalidation-measured-optional)).
- **Route policy**: the canonical JSON policy codec; full vendor CLI coverage,
  a universal compiler, policy-driven packet forwarding, route leaking and VPN
  features, general regular expressions, a YANG management server
  ([routing-policy](design/routing-policy.md#outside-the-first-delivery)).
- **Programming**: the `effective` gate profile and stochastic capacity or
  lost-completion models, with BGP extensions.
- **BGP beyond BG7**: further decision flavors (`cisco-ios`, `junos`),
  add-path, graceful restart with EoR and update-delay, BFD, link-bandwidth
  UCMP, aggregates, dynamic neighbours and listen ranges, SR color steering and
  SRv6 services, an analytical BGP solver, optimal route reflection
  ([source](design/archive/protocols-r8.md#10-deferred-named-extension-points)).
- **Open/R**: KSP2 and UCMP, the RIB policy API, an RTT step detector model.
- **Common**: a control-plane CPU model, incremental SPF, native kernels.
- **Network layer**: resilient hashing, nested B6, REPLACE-C-SID, multi-client
  BSIDs, midpoint protection, VRFs, runtime checkpoint, in-band transport,
  `loop_model=AMPLIFY`
  ([source](design/archive/network-layer-r17.md#gates-and-phases)).
