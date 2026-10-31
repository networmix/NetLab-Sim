# Routing-policy plan: adversarial reviews and refinements

27 September 2026. These are sequential self-review passes with different acceptance lenses, not claims of independent reviewers or vendor conformance runs. The implementation target is [routing-policy.md](routing-policy.md). Earlier drafts and source provenance are retained in [research evidence](/Users/networmix/ws/RFCs/evidence/policy-plan-review/).

## Review method

Review the actual draft against current source, primary language descriptions and concrete route/event traces. For every finding, classify the claim and change the plan or record why no change is justified. A heading/link check proves document integrity only. It does not prove future implementation correctness. The final audit maps the user's requirements to the revised artifact and its evidence.

## Pass 1 — semantics and expressiveness

Input: revision 1, SHA-256 `9cf5f3ef55047f2ff063ea6629094748a4efc7f19e514cc21f0bf754263a3ff5`. Review focused on composition, attachment effects and edits that must restore previously filtered information.

| ID | Finding / adversarial case | Disposition and refinement |
|---|---|---|
| S01 | RIB admission had no concrete retained-input owner. Deny→allow cannot reconstruct a rejected row | Confirmed; retain submission and admitted views, reuse RibState indexes, centralize submission handling (§5) |
| S02 | A single generic admission hook cannot both remain protocol-neutral and inspect full BGP attributes for table-map | Confirmed; separate `BGP_RIB_EXPORT` from generic `RIB_ADMISSION`, with exact read/write boundaries (§5) |
| S03 | ORIGINAL could mean pre-UPDATE or pre-attachment, producing different results after redistribution/export | Confirmed ambiguity; define original relative to each invocation and require pre-policy input for replay (§4) |
| S04 | Terminal reject with actions suggests meaningful side effects before rejection | Confirmed simplification opportunity; reject that syntax, discard earlier tentative edits on later rejection (§4) |
| S05 | Proposed PolicyRef collides with existing SR policy terminology | Confirmed; public name is RoutePolicyRef; existing SrPolicy/PolicyClient remain unchanged |
| S06 | Absent MED could be confused with zero, and a BGP-only field might be read at a device hook | Confirmed; separate unsupported-at-hook errors from legal absence; add Present and explicit comparison semantics (§4) |
| S07 | Resolution permission could reintroduce a noninstalled path into installed-mode lookup | Confirmed ambiguity; source-view selection precedes policy; permission cannot fabricate eligibility (§5) |
| S08 | Policy rejection could accidentally trigger less-specific fallback irrespective of resolver settings | Confirmed; reuse effective fallthrough and ordered-table rules (§5) |
| S09 | Mentioning VRF/table keys implied current model support despite family-keyed RIBs and RowKey shape | Confirmed; retain design scope, reject unsupported live bindings until routing owner supports them (§5) |
| S10 | Import replay without raw routes or ROUTE-REFRESH cannot completely enact a policy edit | Confirmed; explicit pending/reset-needed state, old effective binding retained unless reset is authorized by configuration (§6) |
| S11 | Example community literal looked like an encoded integer and was ambiguous | Confirmed; typed StandardCommunity(65000, 100) and distinct community kinds (§8) |
| S12 | “Just use a broader language” would remove these lifecycle problems | Rejected claim; language syntax does not supply retained input, owner/generation purge or installation boundaries |

Result: revision 2 incorporates S01–S11. The pure language remains small; new complexity was assigned to the stage that already owns the affected state.

## Pass 2 — lifecycle, concurrency and current-code integration

Input: revision 2, SHA-256 `0c6d19f99a17074432d0cfeba7f5b7fcaf176f7a12751bffd3e51707b57a2fc6`. Reread production submission callsites, StateDelta, NHT/derive entry points and pinned FRR timer code. Reran the existing read-only two-node ClientProfile probe: the same client with distance 20 on node A and 200 on node B is still rejected. This confirms a current ownership requirement gap, not a regression claim.

| ID | Finding / adversarial case | Disposition and refinement |
|---|---|---|
| L01 | Trusted generated-route bypass plus retained raw RIB can restore deleted connected routes when policy is detached | Confirmed; every bypass updates both views, and all production writers are enumerated (§5) |
| L02 | Batch comparison against admitted rows can discard changes to a still-denied route | Confirmed; batch/sync uses submission view; raw-only changes persist; no unnecessary FIB programming (§5) |
| L03 | FIB-deny on an already installed route was described only as blocking requests | Confirmed; desired absence schedules DELETE, with actual forwarding visible until completion/failure (§5) |
| L04 | Changing every policy revision could force needless FIB reprogramming, while accepting any old ACK is unsafe | Confirmed; action/eligibility/gate equivalence permits request reuse; superseded request cannot release current gate (§5) |
| L05 | “Apply after five seconds” conflates definition activation with an old-route sweep | Confirmed; distinct active and reevaluated revisions; exact FRR pre-expiry timing remains a named compatibility fixture (§6) |
| L06 | Zero-delay normalization would mis-model FRR zero, including disabling a pending timer | Confirmed directly in bgp_routemap.c / bgp_vty.c; mode plus delay and explicit pending-timer transition (§6) |
| L07 | Revision 2's keep-old-binding rule for unavailable replay creates a second activation model and hides new-input behavior | Refined S10; native activation is uniform, incomplete historical sweep is explicit, per-node report/reset action (§6) |
| L08 | Basic ROUTE-REFRESH cannot by itself justify a fully settled status | Confirmed from RFC 7313 boundary distinction; report unverified completion unless a modeled marker/mechanism proves it |
| L09 | Delayed work can replay withdrawn routes or old revisions | Confirmed; generation/revision guard plus current-input read at execution; E15 |
| L10 | Export grouping keyed by policy name omits peer-dependent matches and changed semantics | Confirmed; compiled fingerprint and declared peer/context projection; E18 |
| L11 | A code-owned access adapter could still read global state or silently turn failures into denial | Confirmed contract gap; minimal explicit local inputs, guarded access tests, transactional invariant failure (§4) |
| L12 | New raw-RIB fields necessarily require a separate event system | Rejected; current StateDelta iterates DeviceState fields; verify coverage and reuse it |

Result: revision 3 incorporates L01–L11 and adds E13–E18. These are implementation requirements and design traces; no new daemon/runtime feature was executed.

## Pass 3 — maintainability, minimality and implementation readiness

Input: revision 3, SHA-256 `d1a774b2eee190b069572a52fb7e012fe162edb04c2b9bb77b845bedefed1530`. Review challenged every proposed abstraction: does it avoid duplication, preserve needed expressions and give an implementer an unambiguous owner/contract?

| ID | Finding / challenge | Disposition and refinement |
|---|---|---|
| M01 | Rejecting every ordered prefix list makes the initial FRR subset needlessly weak; Boolean expansion can be quadratic | Confirmed; one domain-specific first-match PrefixListPermits predicate, E19. No general calls/jumps added |
| M02 | “Typed actions at legal hooks” was underspecified and could lead to duplicate capability checks | Confirmed; one explicit read/write capability table used for validation/documentation (§4) |
| M03 | A second universal route DTO or dynamic dictionary would duplicate BGP state and weaken types | Rejected alternative; retain owner-specific immutable route types and a narrow trusted access protocol; no arbitrary set(field, Any) |
| M04 | Per-node layering could accidentally execute every inherited binding, applying transforms twice | Confirmed; exactly one resolved binding per scoped point; composition only through its explicit chain (§6) |
| M05 | Semantic fingerprints could depend on Python hash, set order or comments | Confirmed; canonical tagged serialization, semantic order preservation and fixed language revision (§4) |
| M06 | Named policies were pinned but example named sets were not, allowing later set changes to alter old revisions | Confirmed; RouteSetRef, transitive digest pins, self-contained materialized configuration (§4/§8) |
| M07 | Matchers over community/multipath values could choose accidental quantifiers; AS-path segment treatment was vague | Confirmed; explicit quantified collection behavior and native AS-path definitions (§4) |
| M08 | A separate trace interpreter could disagree with actual decisions or retain unbounded state | Confirmed risk; same evaluator with bounded optional trace sink and two explanation views (§6) |
| M09 | Fine-grained route caches/global interning look attractive but complicate correctness before a workload justifies them | Confirmed decision to omit initially; compiled-binding reuse and local full reevaluation are the baseline (§6) |
| M10 | The plan's integration prose did not say which Claude-plan sections must change or who owns shared files | Confirmed; explicit section-level deltas and owner contract before parallel implementation (§9) |
| M11 | “Performance tests” without workload or attribution are not actionable | Confirmed; scale-passport sizes, baseline/edit/churn cases, separate memory/evaluation/downstream costs and old/new/old measurement (§9) |
| M12 | Expanding to a full vendor VM would remove unsupported constructs from the plan | Rejected scope expansion; exact supported subsets are explicit, and native expressiveness is exercised by E01–E24 |

Result: revision 4. Core control flow still has four outcomes, no loops/calls/jumps, no general-purpose external evaluator, no duplicate settings framework and no policy-result cache. Added specificity is concentrated in attachment contracts, state ownership and acceptance, where it prevents implementation forks.

## Final completion audit

The final artifact was reread against the objective, current worktree and captured protocol plan. The live Claude plan still matched the captured snapshot at the closing comparison. NetSim HEAD remained `0e5b299225372f394dd3505a09cd92127b33dfa7`; the only NetSim working-tree additions were the two documents in this directory.

| Required outcome | Authoritative evidence inspected | Assessment |
|---|---|---|
| Critically review policy languages | Plan §2 compares FRR/EOS, Junos, IOS XR, BIRD, IETF/OpenConfig, RPSL, CEL, Rego, callbacks and native records, with primary sources and explicit tradeoffs | Complete for the design decision; no claim of a complete vendor feature survey |
| Propose the best approach for NetSim | §§1/3/4/7 choose a small native core, model-layer ownership, exact adapters and explicit unsupported features | Complete recommendation with reasons and limits |
| Write an actionable plan | §9 provides P0–P6, dependencies, code owners, source callsites, required protocol-plan changes and acceptance gates | Complete planning artifact |
| Run deep reviews and refine | Three captured input revisions, S01–S12/L01–L12/M01–M12, and final revision 4 | Complete: 36 findings dispositioned, including rejected alternatives and a revised earlier decision |
| Maintainable implementation | Existing settings/state machinery reused; typed capability table; one evaluator; no universal route DTO, dynamic registry or second ACK system | Covered by explicit contracts and review findings |
| Streamlined implementation | Four control outcomes; bounded typed predicates; no calls/jumps/general regexes/external interpreter/result cache initially | Explicitly bounded core; restrictions do not remove required device hooks |
| Expressive policy behavior | E01–E24 cover common route transformations, composition, ordered prefix filters and adversarial lifecycle cases | Required behavior specified; proposed implementation tests, not passing test results |
| Per-node configuration and isolation | §6 binding identity/overrides/revision pins, E07/E18/E23; current two-node profile probe rerun | Requirement and current prerequisite are explicit |
| RIB/FIB/resolution plus ACK/inactive interactions | Separate hooks in §5, retained submissions, actual versus desired FIB, gate causality and P4 acceptance | Covered without equating absence, exclusion, failure and discard |

Verification: [document verification](/Users/networmix/ws/RFCs/evidence/policy-plan-review/document-verification.json) checked local links, contiguous E01–E24/P0–P6 IDs, unique review IDs and whitespace. Source snapshots/downloads are included in the RFC library integrity seal. These checks support artifact integrity and traceability, not semantic correctness of code that has not been written.

Remaining work is implementation P0–P6 and their specified tests, benchmarks and CI. Exact FRR pre-expiry edit behavior and the conflicting EOS FIB documentation require the named compatibility fixtures before those behaviors receive a vendor conformance label. They do not prevent adopting the fully specified native design. No production source, live Claude plan or agent session was modified by this planning work.
