# Routing policy for NetSim

Status: reviewed implementation proposal, revision 4, 27 September 2026. No routing implementation is added by this document. Scope: language choice, policy semantics, shared engine, node configuration, RIB/FIB/resolver integration, implementation sequence and acceptance. Review record: [routing-policy-reviews.md](routing-policy-reviews.md).

## 1. Decision

Use a small, typed **NetSim route-policy language**: Boolean matches, ordered actions, ordered terms and chains, explicit continuation and terminal allow/deny. Author it as immutable Python records; support a canonical JSON representation using the same schema. Share one pure evaluator between routing protocols, RIB admission, FIB programming and resolver filtering. Keep each attachment point's effects in its owning module.

Use RFC 9067/OpenConfig as structural guidance and eventual interchange formats. Translate an explicitly supported FRR route-map subset first. Do not use a vendor CLI, a YANG tree, Python callbacks, Rego or CEL as the execution language. Do not build a universal vendor-language virtual machine. Reject unsupported foreign semantics instead of silently approximating them.

This narrows the earlier [research guide](/Users/networmix/ws/RFCs/ROUTING-POLICY-GUIDE.md): a shared representation is useful; arbitrary configurable combinations of all vendor control-flow rules are not. Native semantics are a versioned contract. Vendor compatibility describes a tested translation subset, not the name of an entire operating system.

Every modeled behavioral setting and policy binding is overridable per node. Shared definitions are immutable values; they never make a policy update network-global by accident. Preserve current behavior for nodes with no new bindings.

## 2. Evidence and alternatives

The current worktree was inspected at `0e5b299225372f394dd3505a09cd92127b33dfa7`. The live protocol plan now contains a substantial settings system (§2A), immutable specifications, in-place agent configuration, and a BGP-local first-match route-map subset (§5.8). Its latest captured [snapshot](/Users/networmix/ws/RFCs/evidence/policy-plan-review/claude-protocol-plan.md) and [provenance](/Users/networmix/ws/RFCs/evidence/policy-plan-review/inputs.json) are the comparison boundary; this document does not edit that live plan.

| Approach | Useful properties | Reason it should not be the core execution contract |
|---|---|---|
| FRR/EOS route maps | Familiar, compact, directly relevant to SONiC/FRR | Similar syntax hides different continuation, matching and action-order behavior; BGP-first ownership cannot serve model-layer hooks |
| Junos policy statements | Clear terms, policy chains, reusable sets and explicit flow control | Defaults depend on context; policy expressions and route-filter lookup need additional semantics |
| IOS XR RPL | Readable conditionals, parameterization and reusable policies | `pass` continues and a later drop can override it; modification can confer acceptance. A simple terminal-permit translation is wrong |
| BIRD filters | Typed route values, conditionals and reusable functions | This is a router-specific programming language; implementing its runtime and attributes adds unnecessary scope |
| IETF/OpenConfig models | Common vocabulary, schema validation and interchange | They do not erase device capability and attachment differences; a management tree is a poor hot-path representation |
| RPSL/RPSLng | Inter-AS intent and registry-based filter generation | Does not provide the local programming/ACK/resolution lifecycle required here |
| CEL | Typed, side-effect-free expressions | Could express predicates, but NetSim would still need route effects, chaining, attachment validation and lifecycle; a second evaluator adds little initially |
| OPA/Rego | Declarative policy over structured data | Its declarative query model does not directly supply ordered route transformations; adding an external engine does not remove the routing-specific design |
| Arbitrary Python callables | Immediate flexibility | Hidden state, nondeterminism, nonserializable closures and unknown dependencies conflict with tree admission and replay |
| Small native records | Explicit semantics, direct validation, stable serialization, bounded evaluation | NetSim must maintain a small language contract; keep its scope disciplined and tests observable |

Primary evidence: [RFC 9067 §§4–6](https://www.rfc-editor.org/rfc/rfc9067.html), [OpenConfig](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-routing-policy.html), [FRR pinned route maps](/Users/networmix/ws/RFCs/vendor/frr/10.8.0-dev/doc/user/routemap.rst), [Junos chains](https://www.juniper.net/documentation/us/en/software/junos/routing-policy/topics/concept/policy-routing-policies-chain-evaluation-method.html), [IOS XR RPL](https://www.cisco.com/c/en/us/td/docs/iosxr/cisco8000/routing/configuration-guide/routing-config-cisco8000/routing-policy-language-wrapper/routing-policy-language-structure.html), [BIRD 3.1 filters](https://bird.nic.cz/doc/bird-3.1.0.html#filters), [CEL implementation](https://github.com/cel-expr/cel-go), [Rego](https://www.openpolicyagent.org/docs/policy-language), [RPSL](https://www.rfc-editor.org/rfc/rfc2622.html).

RFC 9067 explicitly exposes original-versus-modified attribute matching as implementation-specific read-only state. A configurable NetSim binding is a simulator feature, not a writable interpretation of that YANG leaf. FRR's pinned `route_map_apply_ext()` also distinguishes match, no-match and NOOP and applies different call/exit rules; translating every native feature into an ordinary first-match list would lose behavior. The first adapter rejects those unsupported constructs.

## 3. Existing code and ownership

| Current seam | Consequence for implementation |
|---|---|
| [Route, RibState, rib_apply](../../netsim/model/routing.py) | Route identity is `(prefix, source, distinguisher)` within a family; local route attributes differ from BGP wire attributes. Preserve identity and provenance across policy |
| [ResolutionPolicy](../../netsim/model/routing.py) | Already owns default-route, fallthrough, depth and ECMP behavior. Extend this owner rather than creating a second resolver-settings engine |
| [DeviceConfig / immutable records](../../netsim/model/state.py) | Use admitted frozen records, tuples and PMaps. Functions and compiled opaque objects do not belong in published configuration |
| [AgentConfig.params](../../netsim/model/contracts.py) | Holds immutable protocol settings; share policy definition types without importing BGP into model code |
| [Network.add_agent](../../netsim/model/network.py), [RibClient](../../netsim/model/entities.py), [agent route submission](../../netsim/runtime/agents.py) | Current client profiles are network-global. The node-local profile split must cover all consumers, not only agent registration |
| [NHT refresh](../../netsim/model/nht.py), [derive_fib](../../netsim/model/derive.py) | Current resolver policy is device-wide; client-scoped filters need explicit identity and invalidation |
| [SR policies](../../netsim/model/srv6.py), `Device.policy_client()` | These are segment-routing policies. Do not rename or overload them with route filtering |

Put the shared package at `netsim/model/route_policy/`, using the explicit prefix `RoutePolicy` for public entry points and references; short syntax names such as `Term` remain scoped to this module. Initial modules: `types.py` for immutable syntax and results; `compile.py` for validation/reference resolution; `evaluate.py` for pure execution. Protocol-specific access code and scheduling stay with BGP/Open/R; the existing resolver owns resolution effects. Add a codec module only when the JSON surface is delivered. Vendor adapters live under `netsim/adapters/`, not inside the evaluator.

No new generic settings framework: integrate with the protocol plan's §2A schema and precedence. No duplicated BGP policy evaluator: `agents/bgp/policy.py` becomes the BGP field/action adapter, attachment wiring and refresh scheduling. No changes to `SrPolicy` semantics.

## 4. Language contract

The following are intended record shapes, not existing callable APIs:

```python
RoutePolicy(name, terms: tuple[Term, ...])
Term(name, when: Expr, actions: tuple[Action, ...], flow: Flow)
RoutePolicyBinding(point, policies: tuple[RoutePolicyRef, ...],
                   fallback: ALLOW | DENY, match_input: ORIGINAL | WORKING)
RoutePolicyRef(name, revision)
RouteSetRef(name, revision)
PolicyResult(verdict: ALLOW | DENY, route, reason)
```

`Flow` has exactly four values: `ACCEPT`, `REJECT`, `NEXT_TERM`, `NEXT_POLICY`. A term's flow is explicit. A chain's fallback is explicit in resolved configuration. An absent attachment is represented separately from an attached empty chain; adapters can enforce protocol requirements such as RFC 8212 without confusing an empty policy with no policy.

Evaluation starts with immutable original input and a working route initially identical to it. Process policies and terms in their written order. A false condition advances to the next term. A true condition executes its ordered actions, then its flow. `NEXT_TERM` continues this policy; `NEXT_POLICY` skips its remaining terms. End of a policy continues the chain. `ACCEPT` and `REJECT` terminate the entire chain. End of the chain applies its fallback. Acceptance returns the working route; rejection returns no publishable route and discards tentative edits. A later policy cannot undo terminal rejection by accepting.

A `REJECT` term must have no actions; reject that combination at compilation rather than quietly ignoring side effects. A terminal acceptance applies to the whole binding, not merely the named policy. On every invocation, ORIGINAL means the input to **this attachment**, before any term in its chain; it is not necessarily the original BGP UPDATE. Earlier attachment results are already part of this input. Reapplication obtains that attachment's retained pre-policy input.

Actions always read the current working route. Conditions read either original or working route according to the binding's `match_input`, fixed for that complete invocation. Native default is `WORKING`. There is no hidden per-term profile lookup. Context facts such as peer identity cannot be changed by actions. A profile change is validated and applied through node configuration.

There are no loops, arbitrary jumps, recursive calls, runtime name resolution, general expressions in actions or arbitrary user functions. Reuse comes from named sets, ordered chains and construction-time helpers that produce immutable records. Helpers are ordinary scenario-authoring code, never serialized callbacks. An initially sufficient language must express the examples in §8 before adding more control flow.

### Matches

Use typed leaves composed with `AllOf`, `AnyOf` and `Not`. Empty conjunction/disjunction are rejected; use explicit `Always`/`Never`. Leaves cover prefix membership with exact/min/max length, address family, source protocol/client, origin kind, peer/role, tag, next-hop address/interface, community membership and scalar comparison. BGP leaves add AS-path contains/first/last/length, origin and local attributes. Named-set predicates carry a `RouteSetRef`; both definitions and their referenced sets are pinned. A per-node set change constructs a new policy revision/reference through authoring helpers rather than mutating a globally shared name.

Prefix sets are unordered unions of typed prefix ranges. Separately provide `PrefixListPermits(ref: RouteSetRef)`, a typed predicate over ordered `(range, permit|deny)` entries with first-match result and implicit false at exhaustion. This small domain predicate lets the FRR adapter preserve common mixed permit/deny prefix lists without expanding them into quadratic Boolean expressions. It is not an arbitrary nested policy call. Neither construct claims Junos longest-match/walkup semantics; reject unsupported foreign filters. IPv4 and IPv6 never match across families. Community sets specify any/all/none; replace/add/delete are distinct actions. AS-path predicates operate on the protocol's structured path, preserving AS_SET/confederation distinctions.

Use separate field identifiers for BGP MED and local RIB metric, BGP LOCAL_PREF and local distance, protocol NEXT_HOP and resolved egress, and source client versus peer. Fields are a closed tagged union, not arbitrary string paths into `attrs`. A field unavailable at an attachment is a compile error even inside an unreachable branch. A legal but absent optional attribute is not zero: `Present(field)` tests presence; ordinary comparisons on absence are false; `Not` negates that Boolean normally. Operators, AFs, literal types and ranges are checked at compile time, including rejecting bool where an integer is required. Typed next hops retain family/interface scope; an IPv6 link-local address without required scope is invalid.

Set-valued predicates state their quantifier. Community ANY means nonempty intersection, ALL means every member of the nonempty configured set is present, and NONE means disjointness. Empty configured match sets are rejected. Next-hop address/interface predicates select proposed or resolved values and use explicit ANY or nonempty-ALL over that collection; no hidden choice of the first ECMP leg. A FIB allow/deny applies to the complete selected action, not per-leg pruning. BGP protocol next-hop rewriting and replacing a local row's complete next-hop tuple are distinct action variants.

Raw regular expressions are excluded from the initial native core. Typed AS predicates cover the required initial examples. The live plan's unspecified regex subset needs a separate bounded grammar and source-backed semantics before acceptance; do not silently run Python `re` on an invented AS-path rendering. This is a deliberate scope revision to §5.8, not an implied implementation of its regex promise.

### Actions and typed access

Initial actions: set local preference, MED, weight, origin or tag; add/delete/replace communities; prepend an explicit AS sequence; set an explicit next hop; set local RIB distance/metric where that hook permits it. FIB and resolution hooks initially need allow/deny only. Additional programming attributes can be added with a concrete scenario and attachment validation. No generic `set(field_name, Any)` escape hatch is public.

The capability table is declared once and drives validation and documentation:

| Point | Read domain | Permitted writes in first delivery |
|---|---|---|
| BGP_IMPORT | BGP candidate attributes, common prefix/source facts, ingress peer facts | BGP attributes/local weight and local tag; next hop only with typed family/scope |
| BGP_EXPORT | Selected BGP attributes/common facts and egress peer facts | Advertised BGP attributes and advertised next hop; no RIB distance/metric or identity changes |
| BGP_RIB_EXPORT | Selected BGP attributes and proposed local Route | Local row metric and next hops; selected BGP path is immutable |
| REDISTRIBUTE to BGP | Source common Route facts and explicit destination-BGP defaults | Derived BGP attributes and local tag; source row and protocol ownership are immutable |
| RIB_ADMISSION | Local Route prefix/family/source/origin, distance, metric, tag and proposed next hops | Local distance, metric, tag and next hops; no prefix/source/key/table rewrite |
| FIB_INSTALL | Selected route common facts and resolved forwarding facts | None; allow/deny only |
| RESOLUTION_IMPORT | Candidate common facts plus explicit resolver-query facts | None; allow/deny only |

Redistribution to other protocols needs a destination-owned capability row when that protocol's origination feature lands. A generic attachment name does not grant BGP setters to OSPF/Open/R. AS-path first/last matches return false for an empty path or an ambiguous endpoint set, and examine the non-confederation external endpoint. Native path length means BGP hops: sequence ASNs count individually, a nonempty AS_SET counts once, and confederation segments do not count. Contains requires `NON_CONFED` or `ALL_SEGMENTS`, with membership including applicable AS_SET members. The FRR adapter translates only the pinned meanings it can prove. Local-pref/MED are unsigned 32-bit values; origin is a closed enum; the local distance domain follows the model's validated routing contract rather than a guessed vendor-wide range.

The evaluator does not manufacture a giant universal route record. A trusted, code-owned `PolicyAccess[T]` supplies typed field reads and ordered action application over the owner's immutable route representation. These functions are passed by the owning module at execution, never supplied by configuration or stored in the state tree. A closed field/action catalog validates every combination. BGP owns BGP attribute reads and transformations; the model owns local route fields. Apply transformations to an invocation-local working value, publishing only an accepted result.

The access protocol has three operations: `read(route, field)`, `read_context(context, field)` and `apply(route, ordered_actions)`. Inputs contain only explicit immutable local facts; no NetworkState, clocks, RNGs, external lookups or hidden NHT queries are available. Reads are pure and total for the declared field domain. No-op application returns the input by identity. The compiler records the fields read/written, including named-set dependencies. Trusted implementations are code-owned, but are still tested with guarded inputs for locality and mutation.

Compile-time errors reject the entire candidate configuration. A legal absent attribute follows the presence rules above; it is not an error. Unexpected access/type failures are invariant violations that abort the owner's transaction without partial publication and retain a diagnostic. They are never converted silently into ordinary policy denial. Protocol limits on an accepted transformed route, such as outgoing BGP message size, remain explicit host validation after policy and before emission.

Compilation resolves named sets, validates ranges and attachment legality, computes a canonical semantic fingerprint, and produces immutable terms with resolved references. It does not generate Python code or introduce bytecode. The interpreter dispatches over a closed set of typed operations; additions require one semantic contract and tests.

The public schema version owns semantics; two language versions cannot silently share a compiled fingerprint. Serialize tagged unions with fixed field names and canonical numeric/address forms. Preserve chain/term/action/prefix-list order; sort only mathematically unordered sets. Compute stable fingerprints from canonical bytes, not Python `hash()`, object identity or metadata labels. Missing references, duplicate definitions/term identifiers, reference cycles and malformed expression trees fail compilation. Resolve references once, without recursive textual expansion. Each term executes at most once per invocation; expression and set costs are bounded by their explicit input sizes. No unmeasured latency promise follows from that bound.

## 5. Attachment points and stage effects

These hooks are separate even when a vendor uses the same word, such as import or export, for several of them.

| Point | Subject and owner | Meaning of rejection |
|---|---|---|
| `BGP_IMPORT` | Received candidate; BGP inbound | Candidate is filtered; any previously admitted incarnation is withdrawn appropriately |
| `BGP_EXPORT` | Eligible path + target peer; BGP outbound | Suppress/withdraw advertisement for this peer only |
| `BGP_RIB_EXPORT` | Selected BGP path plus proposed local Route; BGP zebra adapter | Withdraw/omit that protocol submission, without altering BGP's selected path |
| `REDISTRIBUTE` | Source RIB route + target protocol; originator | Do not originate the derived destination-protocol route |
| `RIB_ADMISSION` | Protocol-selected row submitted to main RIB; submitting owner | Keep protocol selection separate from main-RIB admission |
| `FIB_INSTALL` | Selected/resolved action; model programming stage | Desired action is absent by policy; remove any older installed action; do not try the next RIB candidate implicitly |
| `RESOLUTION_IMPORT` | Potential underlay route + resolver context; resolver | Exclude this candidate from this query's resolver inputs |

`BGP_RIB_EXPORT` is the FRR `table-map` boundary. Its read view includes BGP attributes and the proposed local row, but its writable result is **only that row**: local metric and next hops initially. `SetMed` is not a legal alias for `SetRibMetric` here. The BGP owner retains the selected path and regenerates the submission after policy edits; a denied new submission deletes a previously submitted row. This avoids pushing BGP wire-attribute interpretation into the generic device RIB.

`RIB_ADMISSION` follows that boundary and applies to all supported submitting sources using common local Route fields. Add a single model-owned submission helper used by agent RouteOps, `RibClient`, route-source updates and generated-route writers. Keep `rib_apply` as the pure table primitive underneath; it must not unexpectedly execute policy for unrelated internal uses. Audit every production `rib_apply` callsite and require explicit submission/bypass ownership. Generated connected/local and SR-local routes remain trusted, unbound internal sources in the first delivery; attempts to attach an admission filter to them are explicit unsupported configurations, not ignored policies. Their protocol-specific correctness rules are not an optional routing knob.

When the first device RIB-admission binding becomes active for a family, retain the existing unfiltered RibState as that family's immutable **submission view**, and derive the admitted view separately. Thereafter add/delete/sync operations update the submission view first, even for rejected routes; the affected admitted rows are regenerated from those inputs. Reuse the existing RibState/ClientId indexes rather than inventing another raw-table format. With no bindings, keep the old single-view fast path. On last binding removal, the submitted table becomes the admitted table and the extra view can be released. Shared unchanged row objects avoid copying every route payload; measure index overhead. Owner/generation deletion purges retained inputs as well as admitted rows, so a later allow cannot resurrect a dead agent's route.

Trusted bypass writers update **both** views while retention is active. Otherwise detaching the last policy could resurrect an old connected/SR route. Batch collapse/equality and sync reconciliation operate against submitted rows, not admitted rows; a new version of a still-denied route must not disappear as a no-op. Persist raw-only changes and verify StateDelta remains nonempty, while avoiding unnecessary FIB work if the admitted output is unchanged. The current `changed_paths()` iterates DeviceState fields, so reuse that mechanism rather than inventing an unrelated event bus.

The submission audit includes `derive.py` connected/local and SR-local writers; `igp.py` analytical IGP synchronization; `entities.py` RibClient; `network.py` batch reconciliation; and `runtime/agents.py` RouteOps. These are the production callsites found in the inspected tree. New route sources must use the same boundary. An explicit bypass means trusted generation semantics, not permission to omit retention maintenance.

The generic admission policy sees local distance, metric, tag, source, prefix and proposed next hops. BGP community/AS matching at this boundary is unavailable; use `BGP_RIB_EXPORT` while those attributes are still owned by BGP. FIB policy reads selected/resolved common facts. Resolver policy reads candidate route facts plus the query context. This deliberate capability split avoids a second universal attribute store.

For resolver filtering, explicitly identify the route source view (selected RIB or installed forwarding state), VRF/table, family, client and query mode. Filtering does not copy routes across tables. Ordered table fallback and less-specific fallback remain resolver settings, not arbitrary policy control flow. Policy has no authority to disable recursion-loop detection, scope link-local addresses globally or fabricate an installed next hop. Rejected and absent candidates are dependencies too.

The binding owner selects a valid underlay view before evaluation. In installed mode, rejected/noninstalled rows are never brought back merely because policy allows them. The resolver tests the permitted candidates at its lookup boundary; a denied more-specific can try a less-specific only when the effective `lpm_fallthrough` rule allows it. Resolution does not invoke the route's import policy again. Existing code stores RIBs by family and its RowKey omits the Route.table field: do not claim arbitrary VRF/table coexistence is implemented. Carry table scope in the design, but reject bindings for an unsupported table/VRF until the owning routing model supports that scope without aliasing.

Do not apply route policy to packets, LSDB flooding or SPF topology events. Packet PBR, SR steering and route leaking remain their own owners. If route leaking is implemented, it can reuse the evaluator through a typed future attachment with provenance/loop rules; a policy record alone does not implement a table or VPN feature.

Export acceptance cannot bypass protocol eligibility, AS/cluster/originator loop protection, session/AF capability, inactive-route eligibility or a FIB gate. A next-hop export action changes an advertised copy; it does not change the locally installed next hop. Hardware programming exclusion, capacity failure, pending completion and later removal are separate states. See the existing [FIB ACK/inactive analysis](/Users/networmix/ws/RFCs/FIB-ACK-AND-INACTIVE.md).

Keep desired and actual forwarding separate when policy removes an installed route. Rejection sets desired absence with reason `POLICY_EXCLUDED`; an existing entry persists until the modeled DELETE completes. No ADD is pending and a DELETE ACK is not an install success. On failure of deletion, expose the retained actual entry and retry/failure state. Do not replace a FIB-policy exclusion with an implicit discard action or a fallback candidate.

FIB request identity includes node/owner generation, table/family/prefix and desired-action generation. A binding edit that changes the desired action, its eligibility or gate contract supersedes pending requests. An unchanged action/eligibility/gate can keep its existing request after explicit equivalence checking; do not reprogram identical forwarding merely to carry a new source label. Old completion for a superseded request cannot satisfy the current gate. This uses F1/F2's programming contract, not a second policy-specific ACK mechanism.

The EOS documentation conflict recorded in the research guide remains unresolved. Do not use either conflicting passage as the generic default. Native `FIB_INSTALL` policy affects installation only; export changes only through a separately configured gate or eligibility policy. A compatibility adapter requires a pinned executable fixture before asserting EOS behavior.

## 6. Configuration, lifecycle and cost

Definitions and named sets are immutable, revisioned values. A node's effective binding references exact revisions. Reusing a definition does not subscribe every node to a mutable name. A configuration transaction may explicitly replace bindings on several selected nodes, but node edits remain local. Follow the existing settings precedence; replace ordered chains and definitions as whole values rather than merging terms by name.

There is exactly one resolved binding for `(node, attachment, owner/instance, family, supported table, peer when applicable)`. Group/instance/peer layers choose or replace that binding through the existing schema; the evaluator never runs each inheritance layer as an extra policy. Chains provide composition explicitly. Node defaults, individual bindings, match-input mode, automatic/manual reevaluation, delay and replay-unavailable behavior all have node-local override paths. Scope restrictions are type constraints: a FIB-only field need not accept peer scope. Default field values and provenance are provided by §2A's resolver once, not a second merge algorithm.

Use the planned settings tree for desired definitions/references. Materialized device-hook bindings live with DeviceConfig; materialized protocol-hook bindings live with the corresponding AgentConfig.params. Equal immutable definition payloads may be shared by reference. BGP sweep/refresh status belongs to that agent's immutable runtime state; device-hook work belongs to the model/pipeline's existing per-device scheduling state. No counters, deadlines or executable adapter functions enter a shared definition. P0 names these records with the settings/F0 owner; no external mutable registry becomes authoritative.

Resolve all references and validate the complete candidate configuration before publishing it. One bad field, missing reference or illegal action rejects the configuration transaction. Scenario defaults and node/instance/AF/peer overrides compile into concrete bindings once. Explanations retain provenance separately from semantic fingerprints. Serialization records the native language revision, foreign source/profile identity and any explicit deviation from compatibility defaults.

Maintain three concepts: committed configuration, active definition for new inputs, and completion of reevaluation of older inputs. Changing a definition atomically does not make a remote route refresh instantaneous. For the native behavior, activate a validated definition for new input at configuration commit and schedule existing-route reevaluation. The node-local default is automatic reevaluation with zero delay; compatibility profiles may delay or require manual reevaluation. This is outside the evaluator.

Use `reevaluation_mode=automatic|manual` and `reevaluation_delay_s`, owned per node/protocol attachment domain. In automatic mode, successive edits replace pending work with the newest revision and restart the debounce deadline; manual mode keeps a visible pending revision until a command or new route event processes it. A scheduled work item captures owner generation and target revision, reads the latest valid input when executed, and cannot publish an obsolete result after a withdrawal or replacement. BGP import replay, outbound duplicate suppression, RIB refresh, resolver invalidation and FIB work remain separate owner operations. No global scan/timer crosses nodes.

**FRR nuance:** the inspected `bgp_route_map_mark_update()` restarts a debounce timer; a value of zero disables route updates while refreshing references with `route_update=false`. Changing an already-running timer to zero executes that pending update first (`bgp_vty.c`). Translate this into a mode plus delay and an explicit transition action; never turn vendor zero into native immediate reevaluation. Existing map mutation and create/delete pointer refresh are not proven to have identical new-input timing. Exact pre-expiry behavior requires the pinned daemon fixture; native activation-at-commit is a declared simplification until that fixture establishes an adapter-specific need. Sources: [update scheduling](/Users/networmix/ws/RFCs/vendor/frr/10.8.0-dev/bgpd/bgp_routemap.c), functions `bgp_route_map_mark_update` and `bgp_route_map_process_update`; [CLI transition](/Users/networmix/ws/RFCs/vendor/frr/10.8.0-dev/bgpd/bgp_vty.c), `bgp_set_route_map_delay_timer`.

Import reevaluation needs complete pre-policy inputs or peer refresh. With retained input, replay once from that input. With negotiated ROUTE-REFRESH, request it and process returned routes under the active revision. With neither, report `needs_session_reset`; new inputs use the active definition but the old-route sweep remains incomplete. A node's `on_replay_unavailable=report|reset_session` controls whether to request a reset automatically; native default is report. The view must never call this mixed revision state settled. Enhanced route refresh provides BoRR/EoRR boundaries; a basic refresh alone does not provide that completion marker, so report completion as unverified unless another modeled protocol mechanism proves it. Do not infer completion from an arbitrary quiet interval or confuse EoR with EoRR. [RFC 7313](https://www.rfc-editor.org/rfc/rfc7313.html).

For native device RIB/FIB/resolver hooks, retained local inputs allow complete reevaluation at the scheduled node event; any derived programming remains asynchronous. A raw-only change and a same-result revision adoption are real state changes but need not emit new BGP advertisements or FIB writes. Reset/fork/fresh-runtime reconstruction carries definitions, active revisions and pending work according to the existing owner lifecycle; replay must not lose or duplicate a pending edit.

Start with no policy-result cache and no global interning service. Cache compiled immutable bindings within their owning effective configuration. Reevaluate the routes attached to an affected binding; node-local conservative work is the correctness baseline. Add fine-grained route indexes only if measurements show they matter, preserving a full local reevaluation oracle. Do not build dependency indexes for fields that cannot affect a decision.

BGP update-group sharing must include the compiled export-binding semantic fingerprint and every relevant peer/context input. A policy name is insufficient. Initially split groups by the complete declared peer/context projection; optimize sharing only when equal policy inputs imply equal outputs. Resolver query identity similarly includes its policy binding and scope. With no result cache, correctness still depends on scheduling reevaluation after edits and underlay changes; removing caching does not remove negative dependencies.

Store no mutable counters inside shared policy definitions. Optional bounded traces record input identity, attachment, matched terms, edits, final reason and downstream eligibility. Full traces are opt-in. All routing outcomes must be identical with tracing off/on. Published records obey `validate_immutable`; retain current free-threaded ownership rules. No performance improvement is claimed before measurement.

Use the same evaluator for normal execution and explanation; trace collection is an optional sink outside published route state, not another interpreter. `explain_effective_policy` reports the winning configuration sources, exact definition revisions, fallback, capabilities and active/reevaluated status. `explain_route_policy` additionally reports the local input and term/action path. Limit output and count omissions rather than retaining an unbounded route history.

## 7. Compatibility policy

Initially implement a typed FRR adapter for first-match permit/deny maps using the proven predicate/action subset, including ordered prefix-list predicates. It produces native records and a translation report: exact mappings, rejected constructs and intended deviations. It does not claim full CLI parsing. At first, reject call, continue/goto, NOOP-sensitive matchers and unsupported filter semantics unless a dedicated exact lowering is delivered and tested. The adapter must normalize FRR's documented grouping of matches and action order; preserving text order by assumption is insufficient. Exact grouping/order fixtures are part of P5.

The canonical native language does not grow merely to claim more import coverage. A new foreign feature must have an operational use case, pinned expected behavior, a compact exact representation and tests for tricky composition. IETF/OpenConfig serialization is a later adapter over the supported subset. Reject IETF condition-subroutines until their Boolean return and side effects can be preserved; FRR called-deny and Junos policy-expression results are not equivalent substitutes.

Use pinned corrected FRR behavior for current modeling, with 10.5 differences as deliberate behavior settings where useful. Keep historical bugs out of normal settings. The earlier [FRR comparison](/Users/networmix/ws/RFCs/FRR-VERSION-DIFFERENCES.md) records exact snapshots and limits; “10.8” here is a development commit, not a released standard of correctness.

## 8. Expressiveness and adversarial examples

All examples below are required design fixtures, not tests already executed.

| ID | Policy/scenario | Expected result |
|---|---|---|
| E01 | Customer import: allowed prefix AND acceptable path; set LOCAL_PREF 200, add customer community, accept; fallback deny | Only permitted customer routes admitted; shared received attributes unchanged |
| E02 | Tag in one policy and match that tag in the next | Working mode sees the new tag; original mode does not; actions still operate on working state |
| E03 | Reject bogons, then select outbound communities/AS prepend for one peer | Rejected routes never reach later transforms; another peer is unchanged |
| E04 | Protocol-selected BGP route denied by RIB admission | BGP candidate/export eligibility preserved; no admitted main-RIB row |
| E05 | FIB-deny a selected /24 with an installed covering /16 | /24 programming excluded; packets may follow /16. This is not an explicit discard route |
| E06 | Same next hop, two node/client resolution filters: allow IGP versus deny that IGP source | Distinct results and complete dependencies; no cache cross-talk |
| E07 | Two nodes share a policy revision; an unmatched prefix reaches fallback ALLOW on A and node-overridden DENY on B | Node B override changes no state or decision on A |
| E08 | Reapply an edited import policy after prior prepend | New policy runs once on original received path, not the already prepended value |
| E09 | FIB policy changes while an older programming request is in flight | Old success cannot release an advertisement for a new desired action |
| E10 | Term transforms then `NEXT_POLICY`; next policy rejects | No tentative edit reaches a route table or a peer |
| E11 | Filtered resolver /32 becomes permitted without a new BGP UPDATE | Relevant next-hop users are reevaluated, including prior negative results |
| E12 | Attach BGP LOCAL_PREF action to FIB installation | Configuration rejected before any node state changes |
| E13 | Replace a denied submitted row, then allow it; detach final policy after a connected-route deletion | Latest submitted row appears; deleted generated route does not reappear |
| E14 | Change installed route to FIB-denied, with delayed/failed DELETE | Actual old forwarding remains observable until successful removal; no false install ACK |
| E15 | Edit twice during debounce, then withdraw a route before the sweep | Latest revision runs on current inputs; route is not resurrected by stale scheduled work |
| E16 | Route-map timer set to zero with a pending timer, then edited again | Pinned FRR transition and disabled automatic processing are distinguished from native zero-delay mode |
| E17 | No retained pre-policy input and no refresh capability | New-input revision is visible; existing-route completion remains reset-needed, never falsely settled |
| E18 | Same export policy name/revision but different peer facts read by the policy | Update-group sharing does not give both peers the first peer's result |
| E19 | Prefix list denies a /24 before permitting its covering /16 | /24 is false and another /24 within /16 is true; union-of-permits translation is rejected |
| E20 | Same semantic policy with reordered unordered sets versus reordered actions | Set reordering preserves fingerprint/result; action reordering may change both |
| E21 | Missing MED compared with zero, then Not and Present compositions | Missing is not numeric zero; negation/presence follows the explicit native truth rules |
| E22 | Later REJECT versus a throwing access adapter after an earlier tentative transform | No partial route publication; policy deny and invariant failure remain distinct |
| E23 | Node fork/reset with an active revision and pending delayed sweep | Correct lifecycle reconstruction, one current sweep, no cross-fork state or stale generation |
| E24 | No policy bindings on an existing plain-IP scenario | Existing default behavior/fingerprints and single-view RIB path preserved |

Illustrative construction (names are proposed, not current APIs):

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

`StandardCommunity` validates two unsigned 16-bit components; large and extended communities use distinct typed constructors. Source protocol/client, peer and route origin remain separate fields; redistribution must not overwrite provenance to make matching convenient. `RoutePolicyRef` is deliberately distinct from the existing SR `PolicyRef`.

Revision labels such as `r1` are human-facing in this illustration. Resolved references and serialized manifests also pin the canonical content digest; reuse of a label for different bytes is rejected. A materialized configuration is self-contained for replay and does not fetch a later policy/set revision from disk or the network.

## 9. Implementation slices and gates

| Slice | Deliverable and dependency | Exit evidence |
|---|---|---|
| P0 ownership | Coordinate with F0/F7 settings owners: node-local client profiles, node bindings, source retention contract; confirm F1 resolver/programming boundaries | Two-node/same-client/different-profile reproducer becomes a passing regression; no client-identity workaround |
| P1 language | Types, compiler, pure evaluator, typed prefix/community/AS predicates and immutable results | E01–E03, E10, E12, E19–E22; explicit flow/default/absence cases; no mutable admission escape |
| P2 BGP | BGP access adapter, import/export/RIB-export/origination hooks, refresh and edit scheduling | E04 at BGP boundary, E08, E15–E18, peer isolation, policy × reflection/next-hop transforms, RFC 8212; depends on BG1/BG2 attributes/session contract |
| P3 RIB | Admission for agents and existing route sources, retained originals and restore-on-policy-edit | E04 at device boundary, E13, distance/metric changes, deny→allow and allow→deny, generation purge |
| P4 resolver/FIB | F1/F2 integration, resolver filters, installation exclusion, reasoned state and ACK causality | E05/E06/E09/E11/E14, mixed node profiles, inactive × FIB-gate × policy interaction |
| P5 interfaces | Canonical JSON codec, typed FRR subset adapter, explanations | E16/E19 source comparisons, round-trip equality, precise errors, grouping/action-order fixtures; reject unsupported constructs |
| P6 acceptance | Integration, replay/fork/reset, free-threaded correctness and measurements | E07/E23/E24 plus entire matrix, scope documentation, all required checks and measured local work limits |

P1 belongs before BG4 policy work; BGP must consume it rather than building an independent evaluator. P0 and P4 coordinate with F1's resolver redesign instead of applying ad hoc filtering around the current combined selection/FIB function. Device-side policy hooks are part of this plan's first complete delivery, not optional future work.

Coordinate through owned contracts, not simultaneous edits to shared files: settings/F0 owner declares binding storage and node-profile changes; policy owner supplies types/compiler/evaluator and tests; BGP owner implements its access/hooks; F1/F2 owner implements submission, resolver/programming integration and notifications. Freeze the small type/capability contract before parallel implementation. This is an ownership plan, not an instruction to launch agents or modify their live plans.

Minimum changes to the captured protocol plan: replace the §5.8 BGP-local evaluator with this shared package; add BGP_RIB_EXPORT to the zebra adapter; add P0/P3/P4 contracts to F0/F1/F2/F7; replace the undifferentiated `DELAYED = 5 s` action with owner-defined reevaluation semantics; revise the unspecified regex promise; key update groups by effective semantics and relevant peer input rather than policy name alone. Do not make P5 full vendor CLI support a dependency of native routing-policy integration.

Validation must cover: full evaluator truth/control-flow cases; each hook's legal fields/actions; source retention and dynamic updates; fallback versus discard; negative dependencies; policy revision changes with equal outputs; stale ACKs; same prefix across node/table/client scope; fork/reset/replay; unchanged plain-IP fingerprints for unconfigured nodes. A standalone policy result is insufficient evidence for a hook's integrated behavior.

For implementation, follow [AGENTS.md](../../AGENTS.md): source-backed reproducer and failing old-code regression for defects, `make check-ci`, and `make venv-ft` then `make check-ft`. Local checks do not replace CI. Measure same quiet machine old/new/old for unconfigured baseline, bulk initial policies, one-node policy edits and route churn; report absolute time, memory, affected-route counts and equivalence. Do not promise a numeric speedup from this plan.

Measure with representative 1k/10k-node fabrics and route/peer counts from the protocol plan's scale passports, plus small adversarial topologies. Separate policy evaluation cost, retained-input/index memory, binding compilation and downstream routing work. A one-node edit must never enumerate unrelated nodes; within its affected attachment, full reevaluation is permitted as the initial correctness baseline. Every material regression requires investigation and a documented acceptance decision before release, not an invented universal percentage threshold. Vendor differential fixtures compare normalized decisions and event boundaries against exact builds; source inspection alone never earns a conformance label.

## 10. Completion boundaries

This planning task is complete when the language choice has evidence, the execution contract is precise, all hooks have ownership and lifecycle rules, per-node configuration is explicit, the implementation sequence is actionable, and adversarial reviews have been applied with findings dispositioned. Implementation is complete only after P0–P6 and their acceptance evidence. Full vendor CLI coverage, a universal compiler, policy-driven packet forwarding, route-leaking/VPN features, general regexes and a YANG management server are separate expansions.
