# Routing policy contract

NetLab-Sim will get one small, typed route-policy language and one pure
evaluator, shared by BGP, Open/R route injection and the device's RIB, FIB and
resolver hooks. This page is the contract for that language, its attachment
points, per-node configuration, lifecycle and acceptance examples. It is a
planned feature: none of the records or names below exist in the package yet.
Order and state are in [docs/roadmap.md](../roadmap.md), and the slices that deliver
this page are listed under [Slices](#slices).

The page carries the reviewed routing-policy design (revision 4 of 27 September
2026, [archived](archive/routing-policy-r4.md) with its
[review record](archive/routing-policy-reviews.md)) and the later amendments of
the protocol design
([§5.8](archive/protocols-r8.md#58-routing-policy-one-shared-engine-integrates-docsplansrouting-policymd),
[§15.4](archive/protocols-r8.md#154-p1s-on-the-resolver-and-policy-hooks),
[§16.4–16.7](archive/protocols-r8.md#164-resolver-and-policy-hooks-findings-8-9)):
activation per original candidate next hop, separate forwarding and NHT
resolution scopes, group and acknowledgement causality, settings storage and
precedence, regular-expression lowering, RFC 8212, and no JSON codec in the
first delivery. Where the two disagreed, the amendment is what this page says.

The existing SR policies (`SrPolicy`, `Device.policy_client()`) are
segment-routing policies. They solve a different problem, keep their meaning
and are not route policies.

## Decision

- A small, typed **NetLab-Sim route-policy language**: Boolean matches,
  ordered actions, ordered terms and chains, explicit continuation and terminal
  allow or deny. It is authored as immutable Python records.
- One pure evaluator shared by routing protocols, RIB admission, FIB
  programming and resolver filtering. Each attachment point's effects stay in
  the module that owns them.
- RFC 9067 and OpenConfig guide the structure and are possible later
  interchange formats. An explicitly supported FRR route-map subset is
  translated first. A vendor CLI, a YANG tree, Python callbacks, Rego or CEL are
  not the execution language, and there is no universal vendor-language
  virtual machine. Unsupported foreign semantics are rejected, never silently
  approximated.
- Native semantics are a versioned contract. Vendor compatibility describes a
  tested translation subset, not the name of an operating system.
- Every modelled behavioural setting and policy binding is overridable per
  node. Shared definitions are immutable values; a policy update is never
  network-wide by accident. Nodes with no new bindings keep today's behaviour.

## Alternatives

| Approach | Useful properties | Why it is not the execution contract |
|---|---|---|
| FRR and EOS route maps | Familiar, compact, directly relevant to SONiC and FRR | Similar syntax hides different continuation, matching and action-order rules; BGP-first ownership cannot serve model-layer hooks |
| Junos policy statements | Clear terms, chains, reusable sets, explicit flow control | Defaults depend on context; policy expressions and route-filter lookup need more semantics |
| IOS XR RPL | Readable conditionals, parameters, reusable policies | `pass` continues and a later drop can override it; modification can confer acceptance; a terminal-permit translation is wrong |
| BIRD filters | Typed route values, conditionals, functions | A router-specific programming language; its runtime and attributes add scope |
| IETF and OpenConfig models | Common vocabulary, schema validation, interchange | Do not erase device capability and attachment differences; a management tree is a poor hot-path form |
| RPSL and RPSLng | Inter-AS intent, registry-based filter generation | No local programming, acknowledgement or resolution lifecycle |
| CEL | Typed, side-effect-free expressions | Route effects, chaining, attachment validation and lifecycle would still be needed; a second evaluator adds little |
| OPA and Rego | Declarative policy over structured data | No ordered route transformations; an external engine does not remove the routing design |
| Python callables | Immediate flexibility | Hidden state, nondeterminism, unserializable closures and unknown dependencies conflict with tree admission and replay |
| Small native records | Explicit semantics, direct validation, stable serialization, bounded evaluation | NetLab-Sim maintains a small language contract with disciplined scope |

Primary sources: [RFC 9067](https://www.rfc-editor.org/rfc/rfc9067.html)
§§4–6,
[OpenConfig routing policy](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-routing-policy.html),
[Junos policy chains](https://www.juniper.net/documentation/us/en/software/junos/routing-policy/topics/concept/policy-routing-policies-chain-evaluation-method.html),
[IOS XR RPL](https://www.cisco.com/c/en/us/td/docs/iosxr/cisco8000/routing/configuration-guide/routing-config-cisco8000/routing-policy-language-wrapper/routing-policy-language-structure.html),
[BIRD 3.1 filters](https://bird.nic.cz/doc/bird-3.1.0.html#filters),
[CEL](https://github.com/cel-expr/cel-go),
[Rego](https://www.openpolicyagent.org/docs/policy-language),
[RPSL](https://www.rfc-editor.org/rfc/rfc2622.html); FRR route maps as
documented in `doc/user/routemap.rst` at FRR master `f1d7bec`.

RFC 9067 exposes original-versus-modified attribute matching as
implementation-specific read-only state; a configurable binding here is a
simulator feature, not a writable reading of that leaf. FRR distinguishes
match, no-match and NOOP and applies different call and exit rules
(`route_map_apply_ext()`); lowering every native FRR feature into a plain
first-match list would lose behaviour, so the first adapter rejects those
constructs.

## Code it builds on

| Current code | Consequence |
|---|---|
| `Route`, `RibState`, `rib_apply` in [`routing.py`](../../netlab_sim/model/routing.py) | Route identity is `(prefix, source, distinguisher)` within a family; local route attributes differ from BGP wire attributes. Policy preserves identity and provenance |
| `ResolutionPolicy` in [`routing.py`](../../netlab_sim/model/routing.py) | Already owns default-route, fall-through, depth and ECMP behaviour; it is extended rather than duplicated |
| `DeviceConfig` and immutable records in [`state.py`](../../netlab_sim/model/state.py) | Published configuration holds admitted frozen records, tuples and persistent maps; no functions or compiled opaque objects |
| `AgentConfig.params` in [`contracts.py`](../../netlab_sim/model/contracts.py) | Holds immutable protocol settings; policy types are shared without importing BGP into model code |
| `Network.add_agent` in [`network.py`](../../netlab_sim/model/network.py), `RibClient` in [`entities.py`](../../netlab_sim/model/entities.py), agent route submission in [`agents.py`](../../netlab_sim/runtime/agents.py) | Client profiles are network-wide today; the node-local split covers every consumer, not only agent registration ([per-node profiles](protocols.md#per-node-client-profiles)) |
| NHT in [`nht.py`](../../netlab_sim/model/nht.py), FIB derivation in [`derive.py`](../../netlab_sim/model/derive.py) | Resolver policy is device-wide today; client-scoped filters need explicit identity and invalidation |

The planned package is `netlab_sim.model.route_policy`, with public entry
points prefixed `RoutePolicy`; short syntax names such as `Term` stay scoped to
it. Its first modules hold immutable syntax and results, validation and
reference resolution, and pure execution. Protocol-specific access code and
scheduling stay with BGP and Open/R; the resolver owns resolution effects;
vendor adapters live with the other adapters, not in the evaluator. There is no
new generic settings framework (bindings use the [settings system](protocols.md#settings-delta-and-precedence))
and no second BGP evaluator: BGP keeps only its field and action adapter,
attachment wiring and refresh scheduling.

## Language

These are intended record shapes, not callable APIs:

```python
RoutePolicy(name, terms: tuple[Term, ...])
Term(name, when: Expr, actions: tuple[Action, ...], flow: Flow)
RoutePolicyBinding(point, policies: tuple[RoutePolicyRef, ...],
                   fallback: ALLOW | DENY, match_input: ORIGINAL | WORKING)
RoutePolicyRef(name, revision)
RouteSetRef(name, revision)
PolicyResult(verdict: ALLOW | DENY, route, reason)
```

### Evaluation

- `Flow` has exactly four values: `ACCEPT`, `REJECT`, `NEXT_TERM`,
  `NEXT_POLICY`. A term's flow is explicit, and a chain's fallback is explicit
  in resolved configuration. An absent attachment is distinct from an attached
  empty chain, so adapters can enforce rules such as RFC 8212.
- Evaluation starts with the immutable original input and a working route
  equal to it. Policies and terms run in written order. A false condition
  advances to the next term. A true condition runs its ordered actions, then its
  flow. `NEXT_TERM` continues this policy; `NEXT_POLICY` skips its remaining
  terms; the end of a policy continues the chain. `ACCEPT` and `REJECT` end the
  whole chain; the end of the chain applies the fallback. Acceptance returns the
  working route; rejection returns no publishable route and discards tentative
  edits. A later policy cannot undo a terminal rejection.
- A `REJECT` term with actions is a compilation error. A terminal acceptance
  applies to the whole binding, not only the named policy.
- `ORIGINAL` means the input to **this attachment**, before any term of its
  chain, not necessarily the original BGP UPDATE; earlier attachment results
  are part of it. Reapplication uses that attachment's retained pre-policy
  input.
- Actions always read the current working route. Conditions read the original
  or the working route by the binding's `match_input`, fixed for the whole
  invocation; the native default is `WORKING`. Context facts such as peer
  identity cannot be changed by actions; a profile change goes through node
  configuration.
- There are no loops, arbitrary jumps, recursive calls, runtime name
  resolution, general expressions in actions or user functions. Reuse comes
  from named sets, ordered chains and construction-time helpers that produce
  immutable records; helpers are scenario-authoring code, never serialized
  callbacks. The language grows only when the examples below need it.

### Matches

- Typed leaves composed with `AllOf`, `AnyOf` and `Not`. Empty conjunctions and
  disjunctions are rejected; `Always` and `Never` are explicit.
- Leaves cover prefix membership with exact, minimum and maximum length,
  address family, source protocol or client, origin kind, peer and role, tag,
  next-hop address and interface, community membership and scalar comparison.
  BGP adds AS-path contains, first, last and length, origin and local
  attributes.
- Named-set predicates carry a `RouteSetRef`; definitions and the sets they
  reference are pinned. A per-node set change builds a new revision and
  reference through the authoring helpers instead of mutating a shared name.
- Prefix sets are unordered unions of typed prefix ranges.
  `PrefixListPermits(ref)` is a separate predicate over ordered
  `(range, permit | deny)` entries with first-match result and false at
  exhaustion. It is a domain predicate, not a nested policy call, and claims no
  Junos longest-match semantics. IPv4 and IPv6 never match across families.
- Community sets state ANY (nonempty intersection), ALL (every member of the
  nonempty configured set is present) or NONE (disjoint); empty configured
  match sets are rejected. Replace, add and delete are distinct actions.
- AS-path predicates work on the structured path and keep AS_SET and
  confederation distinctions. First and last return false for an empty path or
  an ambiguous endpoint set and examine the non-confederation external
  endpoint. Native path length counts BGP hops: each sequence ASN, a nonempty
  AS_SET once, confederation segments not at all (as the decision process
  counts). Contains states `NON_CONFED` or `ALL_SEGMENTS`, with AS_SET members
  included.
- BGP MED and the local RIB metric, LOCAL_PREF and the local distance, the
  protocol NEXT_HOP and the resolved egress, and the source client and the peer
  are separate fields. Fields are a closed tagged union, not string paths. A
  field unavailable at an attachment is a compile error even in an unreachable
  branch.
- A legal absent optional attribute is not zero: `Present(field)` tests
  presence, ordinary comparisons on absence are false, and `Not` negates that
  Boolean normally. Operators, families, literal types and ranges are checked at
  compile time, including rejecting a Boolean where an integer is required.
  Typed next hops keep family and interface scope; an IPv6 link-local address
  without its scope is invalid.
- Next-hop predicates select proposed or resolved values and use explicit ANY
  or nonempty ALL over that collection; there is no hidden choice of the first
  ECMP leg. A FIB allow or deny applies to the complete selected action, not
  per leg.
- Raw regular expressions are not in the native core. Typed AS predicates
  cover the required examples; Python `re` is never run on an invented AS-path
  rendering.

### Actions and typed access

- Initial actions: set local preference, MED, weight, origin or tag; add,
  delete or replace communities; prepend an explicit AS sequence; set an
  explicit next hop; set local RIB distance or metric where the hook permits.
  BGP protocol next-hop rewriting and replacing a local row's complete
  next-hop tuple are distinct actions. There is no public generic
  `set(field, Any)`. A further programming attribute needs a concrete scenario
  and attachment validation.
- `StandardCommunity` validates two unsigned 16-bit parts; large and extended
  communities have their own constructors. LOCAL_PREF and MED are unsigned
  32-bit; origin is a closed enum; the local distance follows the model's
  routing contract. Source, peer and origin stay separate fields; redistribution
  never overwrites provenance. `RoutePolicyRef` is distinct from the SR
  `PolicyRef`.
- A code-owned `PolicyAccess[T]` supplies typed reads and ordered action
  application over the owner's own immutable route type, with three operations:
  `read(route, field)`, `read_context(context, field)` and
  `apply(route, ordered_actions)`. The owner passes it at execution; it is never
  configured or stored in the tree. Inputs are explicit immutable local facts:
  no network state, clocks, RNGs, external lookups or hidden NHT queries. Reads
  are pure and total for their declared domain; a no-op application returns
  its input by identity. Trusted implementations are still tested with guarded
  inputs for locality and mutation.
- Compilation errors reject the entire candidate configuration. An access or
  type failure at run time is an invariant violation that aborts the owner's
  transaction without partial publication and keeps a diagnostic; it never
  becomes a policy deny. Protocol limits on an accepted route (such as BGP
  message size) are validated by the host after policy.
- Compilation resolves named sets once (no textual expansion), validates ranges
  and attachment legality, records the fields each binding reads and writes,
  including its named-set dependencies, computes a canonical semantic
  fingerprint and produces immutable terms with resolved references. It generates no code; the
  interpreter dispatches over a closed set of typed operations. Missing
  references, duplicate definitions or term ids, reference cycles and malformed
  trees fail compilation. Each term runs at most once per invocation; costs are
  bounded by explicit input sizes, with no latency promise.
- The schema version owns semantics; two language versions never share a
  fingerprint. Canonical serialization uses tagged unions with fixed field names
  and canonical number and address forms, keeps chain, term, action and
  prefix-list order, and sorts only mathematically unordered sets. Fingerprints
  come from canonical bytes, never Python `hash()`, identity or labels. Resolved
  references pin a content digest as well as a revision label; reusing a label
  for different content is rejected. A materialized configuration is
  self-contained for replay.

### Capabilities

One table, declared once, drives validation and documentation.

| Point | Read domain | Writes in the first delivery |
|---|---|---|
| `BGP_IMPORT` | BGP candidate attributes, common prefix and source facts, ingress peer facts | BGP attributes, local weight and local tag; next hop only with typed family and scope |
| `BGP_EXPORT` | Selected BGP attributes, common facts, egress peer facts | Advertised BGP attributes and advertised next hop; no RIB distance, metric or identity change |
| `BGP_RIB_EXPORT` | Selected BGP attributes and the proposed local route | Local row metric and next hops; the selected BGP path is immutable |
| `REDISTRIBUTE` to BGP | Source route common facts and explicit destination-BGP defaults | Derived BGP attributes and local tag; source row and ownership immutable |
| `RIB_ADMISSION` | Local route prefix, family, source, origin, distance, metric, tag, proposed next hops | Local distance, metric, tag and next hops; no prefix, source, key or table rewrite |
| Candidate-next-hop activation filter | One original candidate next hop after activation (its activated type, address, interface and recursion state) plus permitted row facts | None; allow or deny for that next hop |
| `FIB_INSTALL` | Selected route common facts and resolved forwarding facts | None; allow or deny |
| `RESOLUTION_IMPORT` | Candidate common facts plus explicit resolver query facts | None; allow or deny |

Redistribution into another protocol needs a capability row owned by that
protocol when its origination lands; a generic attachment name grants no BGP
setters to Open/R. The activation filter's point name is fixed when RP3's
contract is reconciled.

## Attachment points

These hooks are separate even where a vendor uses one word, such as import or
export, for several of them.

| Point | Subject and owner | Meaning of rejection | FRR construct |
|---|---|---|---|
| `BGP_IMPORT` | Received candidate; BGP inbound | The candidate is filtered; a previously admitted incarnation is withdrawn | `neighbor X route-map M in` |
| `BGP_EXPORT` | Eligible path and target peer; BGP outbound | Advertisement suppressed or withdrawn for this peer only | `neighbor X route-map M out` |
| `BGP_RIB_EXPORT` | Selected BGP path plus proposed local route; BGP's RIB adapter | That submission is withdrawn or omitted; BGP's selection is unchanged | `table-map M`; its filtering behaviour needs a pinned fixture |
| `REDISTRIBUTE` | Source RIB route and target protocol; originator | The derived route is not originated | `redistribute P route-map M` |
| `RIB_ADMISSION` | Protocol-selected row submitted to the main RIB; model-owned admission | No admitted main-RIB row; protocol selection is unaffected | None |
| Activation filter | Each original candidate next hop during next-hop activation; resolver | That next hop and its resolved contribution are deactivated; a route left with no active next hop is ineligible and the next candidate is selected | `ip protocol P route-map M` |
| `FIB_INSTALL` | Selected and resolved action; model programming stage | Desired action is absent by policy (`POLICY_EXCLUDED`); an older installed action is removed; no fallback to another candidate, no leg pruning | None; native only |
| `RESOLUTION_IMPORT` | Potential underlay route and resolver context; resolver; scope `nht` or `forwarding` | The candidate is excluded from this query's inputs | `ip nht P route-map M` is scope `nht` with no fall-through; scope `forwarding` has no FRR equivalent |

The FRR column is a vendor reference from a reading of FRR master `f1d7bec`;
each mapping is confirmed by a pinned fixture in the FRR lane before it is
called conformant.

### BGP to RIB

`BGP_RIB_EXPORT` is the FRR `table-map` boundary. It reads BGP attributes and
the proposed local row, but writes **only that row**: local metric and next
hops at first. `SetMed` is not an alias for setting the RIB metric. BGP keeps
the selected path and regenerates its submission after a policy edit; a denied
new submission deletes the previously submitted row.

### RIB admission and retained submissions

- `RIB_ADMISSION` applies to all supported submitting sources through common
  local route fields. Every production RIB writer goes through one
  model-owned submission helper: connected, local and SR-local routes in
  `derive.py`, the oracle IGP in `igp.py`, `RibClient` in `entities.py`, batch
  reconciliation in `network.py` and agent route operations in
  `runtime/agents.py`. `rib_apply` stays the pure table primitive and never runs
  policy for unrelated internal uses; an audit test fails on a new direct call
  from production code. New route sources use the same boundary.
- Generated connected, local and SR-local routes stay trusted, unbound sources
  in the first delivery; attaching an admission filter to them is rejected as
  unsupported, not ignored.
- When a family's first admission binding becomes active, the unfiltered RIB
  is kept as that family's immutable **submission view** and the admitted view
  is derived from it. Add, delete and sync operations update the submission
  view first, even for rejected routes; affected admitted rows are regenerated.
  The existing RIB and client indexes are reused. With no bindings the single
  view stays; on the last binding's removal the submitted table becomes the
  admitted table. Unchanged row objects are shared; index overhead is measured.
- Trusted bypass writers update **both** views while retention is active, so
  detaching the last policy cannot resurrect a deleted connected or SR route.
  Batch collapse, equality and sync reconciliation compare submitted rows, so a
  new version of a still-denied route is not lost as a no-op. A raw-only change
  is a real state change (the state delta stays nonempty) but causes no FIB work
  when the admitted output is unchanged. Owner or generation deletion purges
  retained inputs as well as admitted rows, so a later allow cannot resurrect a
  dead agent's route.
- Admission sees local distance, metric, tag, source, prefix and proposed next
  hops. BGP communities and AS paths are not available there; use
  `BGP_RIB_EXPORT` while BGP owns them.

### Next-hop activation

FRR's `ip protocol` is not a submission filter. The activation filter runs in
the resolver after next-hop activation, when the resolving interface is known,
once per **original** candidate next hop, with that next hop's activated type,
address, interface index and recursion state plus permitted row facts. A deny
deactivates that original next hop and its resolved contribution, never each
flattened child independently. System routes and family mismatches bypass it.
Positive and negative underlay dependencies are recorded, and the filter is
evaluated again when they change, without a new submission. When no next hop
survives, the route is ineligible and the next candidate is tried. Vendor
reference: `zebra_nhg.c:2403-2406, 2622-2628, 2693-2716, 2880-2921,
2909-2917`, `zebra_routemap.c:70-87`. Native submission admission, this filter
and whole-action FIB policy are separate capability rows.

### Resolver filtering

- The binding names its source view (selected RIB or installed forwarding
  state), table, family, client and query mode. Filtering does not copy routes
  between tables.
- Scope `nht` filters one client's next-hop tracking answers: the resolving
  route is chosen by longest match, then its next hops are filtered for that
  client; if none remains, the client is told filtered or unresolved and no less
  specific route is tried (vendor reference: `zebra_rnh.c:515-576`). Forwarding
  recursion is unaffected. Scope `forwarding` filters recursive resolution for
  installation, and a denied more-specific falls through to a less specific one
  only when the effective `lpm_fallthrough` rule allows it.
- The source view is chosen before evaluation. In installed mode a rejected or
  uninstalled row never returns because policy allows it. Resolution does not
  run the route's import policy again. Ordered table fallback and less-specific
  fallback stay resolver settings. Policy cannot disable recursion-loop
  detection, make a link-local address global or fabricate an installed next
  hop. Rejected and absent candidates are dependencies too.
- Recursive next-hop keys include the interface identity and generation for
  link-local addresses and every scope that changes resolution. Owner and
  client projections (policy binding, query mode) are keyed separately and
  applied per row, never to a shared group. A filtered NHT answer receives the
  selected row's tag, metric, distance and source and its activated next hops
  from the processed snapshot.
- The RIB is stored per family and its row key has no table field, so bindings
  for a table or VRF the routing model does not support are rejected until it
  does.

### Installation and acknowledgements

- Export acceptance cannot bypass protocol eligibility, AS, cluster or
  originator loop protection, session or family capability, inactive-route
  eligibility or a FIB gate. A next-hop export action changes the advertised
  copy, not the locally installed next hop. Programming exclusion, capacity
  failure, pending completion and later removal are separate states.
- When policy removes an installed route, desired and installed state stay
  separate: rejection sets desired absence with reason `POLICY_EXCLUDED`; the
  existing entry stays until the modelled DELETE completes; no ADD is pending
  and a DELETE acknowledgement is not an install success; a failed deletion
  shows the retained entry and its retry or failure state. FIB-policy
  exclusion is never replaced by an implicit discard or a fallback candidate.
- A programming request's identity includes node and owner generation, table,
  family, prefix and desired-action generation. A binding edit that changes
  the desired action, its eligibility or its gate contract supersedes pending
  requests; an unchanged action, eligibility and gate keeps its request after
  an explicit equivalence check, so a new source label does not reprogram
  identical forwarding. An old completion never satisfies the current gate.
  Group obligations follow the
  [programming contract](protocols.md#programming-sync-and-feeds); there is no
  policy-specific acknowledgement mechanism.
- Native `FIB_INSTALL` affects installation only; export changes only through a
  separately configured gate or eligibility policy. Published Arista EOS
  documentation describes this hook in two conflicting ways; neither is the
  native default, and an EOS adapter needs a pinned executable fixture first.

### Out of scope for policy

Route policy does not apply to packets, LSDB flooding or SPF topology events.
Packet policy-based routing, SR steering and route leaking keep their own
owners. Route leaking may later reuse the evaluator through a typed attachment
with its own provenance and loop rules; a policy record alone implements no
table or VPN feature.

## Configuration and lifecycle

- Definitions and named sets are immutable, revisioned values. A node's
  effective binding references exact revisions; reusing a definition does not
  subscribe nodes to a mutable name. One transaction may replace bindings on
  several nodes; node edits stay local. Chains and definitions are replaced as
  whole values, never merged by term name.
- Exactly one resolved binding exists per (node, attachment point, owner or
  instance, family, supported table, peer where applicable). Group, instance
  and peer layers choose or replace that binding through the settings schema;
  the evaluator never runs inherited layers as extra policies. Node defaults,
  individual bindings, match-input mode, reevaluation mode and delay, and the
  replay-unavailable action all have node-local overrides. Scope restrictions
  are type constraints (a FIB-only field need not accept a peer scope).
- Bindings are stored in the settings tree. The highest layer that writes an
  exact (object, key) wins; absent explicit values fall back to presets, then
  to the dialect's defaults (archived
  [layers and precedence](archive/protocols-r8.md#2a3-layers-and-precedence),
  reconciled with F7a). Preset precedence is in
  [settings](protocols.md#settings-delta-and-precedence). Materialized
  device-hook bindings live with the device configuration and protocol-hook
  bindings with the agent configuration. Equal immutable definitions may be
  shared by reference. BGP refresh status belongs to that agent's runtime
  state; device-hook work to the existing per-device scheduling. No counters,
  deadlines or executable functions enter a shared definition, and no
  external mutable registry is authoritative.
- The complete candidate configuration is resolved and validated before it is
  published; one bad field, missing reference or illegal action rejects the
  transaction. Scenario defaults and node, instance, family and peer overrides
  compile into concrete bindings once. Explanations keep provenance apart from semantic fingerprints.
  Serialization records the language revision, the foreign source or profile
  and any deviation from compatibility defaults.
- Three things are distinct: committed configuration, the definition active for
  new inputs, and completion of reevaluation of older inputs. A validated
  definition is active for new inputs at commit; existing routes are
  reevaluated by `policy.reevaluation.mode` (`automatic` or `manual`) and
  `policy.reevaluation.delay_s`, owned per node and attachment domain. The
  native default is automatic with zero delay; the FRR dialects default to
  automatic with 5 s, FRR's route-map delay timer.
- In automatic mode successive edits replace pending work with the newest
  revision and restart the debounce deadline; in manual mode a visible pending
  revision waits for a command or a new route event. Scheduled work captures the
  owner generation and target revision, reads current inputs when it runs, and
  cannot publish an obsolete result after a withdrawal or replacement. BGP
  import replay, outbound duplicate suppression, RIB refresh, resolver
  invalidation and FIB work stay separate owner operations. No global scan or
  timer crosses nodes.
- **FRR delay timer.** FRR's zero delay disables automatic route updates while
  references refresh, and changing a running timer to zero first runs the
  pending update (vendor reference: `bgp_route_map_mark_update`,
  `bgp_route_map_process_update` in `bgp_routemap.c`;
  `bgp_set_route_map_delay_timer` in `bgp_vty.c`). The FRR adapter maps zero to
  `manual` with an explicit transition action; zero never means native
  immediate reevaluation. Native activation at commit is a declared
  simplification until a pinned daemon fixture shows FRR's exact timing before
  expiry.
- Import reevaluation needs complete pre-policy input or a peer refresh. With
  retained input, replay once from it. With negotiated ROUTE-REFRESH
  (RFC 2918), request it and process the returned routes under the active
  revision. With neither, the state is `needs_session_reset`: new inputs use
  the active definition, the old-route sweep stays incomplete, and the view
  never calls this settled. The per-node setting
  `bgp.policy.on_replay_unavailable` is `report` (native default) or
  `reset_session`. Enhanced route refresh
  ([RFC 7313](https://www.rfc-editor.org/rfc/rfc7313.html)) gives BoRR and EoRR
  boundaries; a basic refresh alone does not, so completion is reported as
  unverified unless another modelled mechanism proves it. A quiet interval is
  not completion, and EoR is not EoRR.
- Device RIB, FIB and resolver hooks reevaluate completely from retained local
  inputs at the scheduled node event; derived programming stays asynchronous.
  A raw-only change or a same-result revision adoption is a real state change
  but need not emit BGP advertisements or FIB writes. Reset, fork and
  fresh-runtime reconstruction carry definitions, active revisions and pending
  work through the owner lifecycle; replay neither loses nor duplicates a
  pending edit.

### Cost and observability

- No policy-result cache and no global interning at first; compiled bindings
  are reused within their effective configuration, results are not (import
  policy depends on the prefix and context, not only the attributes). The
  routes attached to an affected binding are reevaluated; node-local
  conservative work is the correctness baseline. Finer route indexes come only
  when measurements show they matter, with a full local reevaluation as their
  oracle, and never for fields that cannot affect a decision.
- BGP update groups are keyed by the compiled export-binding fingerprint and
  every declared peer and context fact the policy reads, never by policy name.
  Groups split by the complete declared projection first; sharing is optimized
  only where equal policy inputs imply equal outputs. Resolver query identity
  includes its policy binding and scope. Without a result cache, correctness
  still needs reevaluation after edits and underlay changes, including
  negative dependencies.
- Shared definitions hold no mutable counters. Optional bounded traces record
  input identity, attachment, matched terms, edits, final reason and downstream
  eligibility; full traces are opt-in, and outcomes are identical with tracing
  on or off. Published records pass immutability validation and the
  free-threading ownership rules. No speedup is claimed before measurement.
- Explanations use the same evaluator with an optional trace sink.
  `explain_effective_policy` reports the winning configuration sources, exact
  revisions, fallback, capabilities and active or reevaluated status;
  `explain_route_policy` adds the local input and the term and action path.
  Output is limited and omissions counted.

## Compatibility

- The first adapter is a typed FRR adapter for first-match permit and deny
  maps over the proven predicate and action subset, including ordered prefix
  lists. It produces native records and a translation report (exact mappings,
  rejected constructs, intended deviations) and claims no full CLI parsing. It
  rejects call, continue and goto, NOOP-sensitive matches and unsupported filter
  semantics unless an exact lowering is delivered and tested. It normalizes
  FRR's documented grouping of matches and order of actions; text order is not
  assumed.
- The FRR adapter lowers only anchored single-ASN AS-path patterns (`^A_`,
  `_A$`, `_A_` and their equivalents) to typed predicates and rejects every
  other regular expression with a report. A bounded regular-expression grammar
  with source-backed semantics is a separate later slice.
- The native language does not grow to claim more import coverage. A new
  foreign feature needs an operational use, pinned expected behaviour, a compact
  exact representation and tests for tricky composition. IETF and OpenConfig
  serialization is a later adapter over the supported subset; IETF condition
  subroutines are rejected until their Boolean return and side effects can be
  kept. FRR called-deny and Junos policy-expression results are not
  substitutes for each other.
- Pinned, corrected FRR behaviour is the model; FRR 10.5 differences are
  behaviour settings where useful, and historical bugs stay out of normal
  settings. FRR master is a development commit, not a released standard.
- The canonical JSON policy codec is not part of the first delivery; nothing
  consumes JSON policies yet, and the record schema already defines the
  canonical form.

## RFC 8212

With `bgp.ebgp_requires_policy` set (the FRR `traditional` profile), a missing
import binding discards received routes and a missing export binding
suppresses advertisements, per address family and direction. The eBGP session
still reaches Established and exchanges control messages; the configuration and
the OPEN are never rejected for a missing policy; views report the
missing-policy state; behaviour changes once a policy is attached. An attached
empty binding is distinct and follows its fallback. The rule is not enforced
under the `datacenter` profile or the `sonic` preset, and confederation peers
are exempt (a recorded FRR behaviour). Vendor reference:
`bgp_route.c:2692-2702, 6265-6275`.

## Examples

These are required design fixtures, not tests that exist or have run.

| ID | Policy or scenario | Expected result |
|---|---|---|
| E01 | Customer import: allowed prefix AND acceptable path; set LOCAL_PREF 200, add customer community, accept; fallback deny | Only permitted customer routes admitted; shared received attributes unchanged |
| E02 | Tag in one policy and match that tag in the next | Working mode sees the new tag; original mode does not; actions still operate on working state |
| E03 | Reject bogons, then select outbound communities and AS prepend for one peer | Rejected routes never reach later transforms; another peer is unchanged |
| E04 | Protocol-selected BGP route denied by RIB admission | BGP candidate and export eligibility preserved; no admitted main-RIB row |
| E05 | FIB-deny a selected /24 with an installed covering /16 | /24 programming excluded; packets may follow the /16. This is not an explicit discard route |
| E06 | Same next hop, two node or client resolution filters: allow an IGP versus deny that IGP source | Distinct results and complete dependencies; no cache cross-talk |
| E07 | Two nodes share a policy revision; an unmatched prefix reaches fallback ALLOW on A and a node-overridden DENY on B | B's override changes no state or decision on A |
| E08 | Reapply an edited import policy after a prior prepend | The new policy runs once on the original received path, not the prepended value |
| E09 | FIB policy changes while an older programming request is in flight | An old success cannot release an advertisement for a new desired action |
| E10 | A term transforms, then `NEXT_POLICY`; the next policy rejects | No tentative edit reaches a route table or a peer |
| E11 | A filtered resolver /32 becomes permitted without a new BGP UPDATE | Relevant next-hop users are reevaluated, including prior negative results |
| E12 | Attach a BGP LOCAL_PREF action to FIB installation | Configuration rejected before any node state changes |
| E13 | Replace a denied submitted row, then allow it; detach the final policy after a connected-route deletion | The latest submitted row appears; the deleted generated route does not reappear |
| E14 | Change an installed route to FIB-denied, with a delayed or failed DELETE | The old forwarding stays observable until successful removal; no false install acknowledgement |
| E15 | Edit twice during debounce, then withdraw a route before the sweep | The latest revision runs on current inputs; stale scheduled work does not resurrect the route |
| E16 | Route-map timer set to zero with a pending timer, then edited again | The pinned FRR transition and disabled automatic processing are distinguished from native zero-delay mode |
| E17 | No retained pre-policy input and no refresh capability | The new-input revision is visible; existing-route completion stays reset-needed, never falsely settled |
| E18 | Same export policy name and revision but different peer facts read by the policy | Update-group sharing does not give both peers the first peer's result |
| E19 | A prefix list denies a /24 before permitting its covering /16 | The /24 is false and another /24 within the /16 is true; a union-of-permits translation is rejected |
| E20 | Same semantic policy with reordered unordered sets versus reordered actions | Set reordering keeps fingerprint and result; action reordering may change both |
| E21 | Missing MED compared with zero, then `Not` and `Present` compositions | Missing is not zero; negation and presence follow the native truth rules |
| E22 | A later REJECT versus a throwing access adapter after an earlier tentative transform | No partial publication; policy deny and invariant failure stay distinct |
| E23 | Node fork or reset with an active revision and a pending delayed sweep | Correct lifecycle reconstruction, one current sweep, no cross-fork state or stale generation |
| E24 | No policy bindings on an existing plain-IP scenario | Existing behaviour, fingerprints and the single-view RIB path preserved |

An illustrative construction (proposed names, not current APIs):

```python
customer = RoutePolicy('customer-in', terms=(
    Term('authorized',
         AllOf(PrefixIn(RouteSetRef('customer-prefixes', 'r1')), AsPathFirst(64512)),
         actions=(SetLocalPref(200), AddCommunities((StandardCommunity(65000, 100),))),
         flow=ACCEPT),
))
binding = RoutePolicyBinding(
    point=BGP_IMPORT, policies=(RoutePolicyRef('customer-in', 'r1'),),
    fallback=DENY, match_input=WORKING)
```

## Slices

The route-policy work is delivered inside the slices of
[docs/roadmap.md](../roadmap.md), which orders them. The device-side hooks are part of
the first complete delivery, not optional.

| Part | Delivered in | Content | Exit evidence |
|---|---|---|---|
| P0 ownership | F0, F7a | Node-local client profiles, binding storage in settings, the retained-submission contract; the resolver and programming boundaries agreed with X | The two-node, same-client, different-profile regression passes; no client-identity workaround |
| P1 language | RP1 | Types, compiler, pure evaluator, typed prefix, community and AS predicates, immutable results, the capability table | E01–E03, E10, E12, E19–E22; flow, default and absence truth tables; fingerprint canonicalization; no mutable admission escape |
| P2 BGP | BG3 (import), BG4 (export and hooks) | BGP access adapter; import, export, RIB-export and origination hooks; refresh and edit scheduling | E04 at the BGP boundary, E08, E15–E18; peer isolation; policy with reflection and next-hop transforms; RFC 8212 |
| P3 RIB | RP3 | Admission for agents and existing sources, retained submissions, restore on policy edit; the activation filter; `RESOLUTION_IMPORT` scope `nht` | E04 at the device boundary, E13; distance and metric changes; deny → allow and allow → deny; generation purge; activation per original next hop, with fallback to the next candidate when none survives |
| P4 resolver and FIB | RP4, with X | `RESOLUTION_IMPORT` scope `forwarding`, `FIB_INSTALL` exclusion, reasoned state and acknowledgement causality on the programming contract | E05, E06, E09, E11, E14; mixed node profiles; inactive route × FIB gate × policy |
| P5 interfaces | BG7 | Typed FRR subset adapter with the `ip protocol` and `ip nht` mappings and AS-path lowering; explanations | E16 and E19 source comparisons; grouping and action-order fixtures; precise errors; unsupported constructs rejected |
| P6 acceptance | M5 | Integration, replay, fork and reset, free-threaded correctness, measurements | E07, E23, E24 and the whole matrix; scope documentation; the repository's checks; measured local work limits |

P1 lands before BGP's import hook, BG4 and OR5; BGP consumes it instead of
building its own evaluator. P0 and P4 follow the resolver redesign instead of
filtering around today's combined selection and FIB function. The small type
and capability contract is frozen before parallel work starts.

### Validation and measurement

- Validation covers: the evaluator's truth and control-flow cases; each hook's
  legal fields and actions; source retention and dynamic updates; fallback
  versus discard; negative dependencies; revision changes with equal outputs;
  stale acknowledgements; the same prefix across node, table and client scope;
  fork, reset and replay; unchanged plain-IP fingerprints for unconfigured
  nodes. A standalone policy result is not evidence for a hook's integrated
  behaviour.
- Implementation follows the repository's [development rules](../../AGENTS.md):
  a source-backed reproducer and a failing regression for defects, the standard
  and free-threaded checks, and CI.
- Measurements compare old and new on the same quiet machine for the
  unconfigured baseline, bulk initial policies, one-node policy edits and route
  churn, reporting absolute time, memory, affected-route counts and
  equivalence, on representative 1k- and 10k-node fabrics with the protocol
  design's route and peer counts plus small adversarial topologies. Policy
  evaluation, retained-input and index memory, binding compilation and
  downstream routing work are reported separately. A one-node edit never
  enumerates unrelated nodes; within its attachment, full reevaluation is the
  initial baseline. A material regression needs investigation and a recorded
  decision before release, not a universal percentage threshold. Vendor
  differential fixtures compare normalized decisions and event boundaries
  against exact builds; source reading alone never earns a conformance label.

## Outside the first delivery

Full vendor CLI coverage, a universal compiler, policy-driven packet
forwarding, route leaking and VPN features, general regular expressions, a YANG
management server and the canonical JSON codec are separate later work.
