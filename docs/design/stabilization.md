# Stabilization

This page states what the stabilization work must guarantee: a review of the
implemented product (RV), the port to NetGraph 0.26 and the NetGraph-Core
release it requires (NG-026), and the fixes for confirmed defects (FX). Order,
ownership and state are in [docs/roadmap.md](../roadmap.md).

## What counts as a defect

- A defect is a wrong result, a crash or a wrong error in a scenario the
  product supports today: the README, the reference, the tests or the domain's
  first principles give a different answer. It is shown by the source and a
  reproducer on a pinned commit.
- Behaviour that a planned slice adds is not a defect unless a current
  contract is shown to be violated. Two examples: an idle agent run still
  commits ([C6](protocols.md#current-behaviour)), and client profiles are
  network-wide ([F0](protocols.md#per-node-client-profiles)).

## RV: review of the implemented product

- The object is Gate A, Gate B, Gate C and S0 at a pinned commit. RV assesses
  implemented behaviour, architecture and code, tests and documentation, the
  supported integrations, and scale risks in proportion. Expected answers are
  derived independently of the code. A passing suite does not show the
  absence of defects, and tests skipped for a missing optional package count
  as not run.
- The NetGraph and NetGraph-Core adapters are reviewed against their
  documented translation rules; NG-026 qualifies their code on the new
  releases.
- Every finding has a reproducer, a grade (blocks an existing supported
  scenario, does not block, or is not a defect) and an owning slice.
- The known resolver defects ([two separating examples](protocols.md#two-separating-examples))
  are confirmed again on the pinned commit.
- The findings are recorded in a history report.

## NG-026: NetGraph 0.26 port

`netlab-sim run` calls `Scenario.run()`, which NetGraph 0.26 replaced with
preparing a scenario and running the prepared scenario. The port qualifies
every boundary between NetLab-Sim and NetGraph or NetGraph-Core, not only the
CLI, against the public interfaces of the pinned releases. For NetGraph these
are documented in the
[NetGraph 0.26 API reference](https://github.com/networmix/NetGraph/blob/v0.26.0/docs/reference/api.md)
(sections "Custom steps and exporters", "Failure cases", "Results and
export"):

- **Dependencies**: the exact supported NetGraph release and the NetGraph-Core
  release it requires, installed clean into a fresh environment, and a test
  lane that runs the adapter tests against them.
- **CLI**: `netlab-sim run` runs and exports through the public path.
- **Workflow step**: `SimStudy` works as a public custom workflow step:
  registration, declared needs, and its result through the step output and an
  exporter.
- **Network and Core**: network import and export (topology, capacities,
  `attrs.sim` settings, risk groups) and the Core adapter (`edge_arrays`,
  `build_graph`) work on the pinned releases.
- **Inputs**: demand sets and failure policies come from public scenario
  interfaces. Each demand keeps its declared volume and the expansion the
  reference states; an unsupported shape gets a clear error.
- **Failures**: NetGraph's failure cases are deduplicated, with occurrence
  counts; they are not an ordered stream of draws. The iterations, process and
  replay modes each state their draw order, seed derivation and treatment of
  repeated patterns.
- The README and the reference change in the same commit as the port.

## FX: confirmed defect fixes

- FX fixes and confirms the blockers found by RV or NG-026 that the
  [roadmap](../roadmap.md#landing-rules) assigns to it. Each fix has a regression
  test that fails on the old code and an independent confirmation of the fix
  and of its intended differences.
- A deferred finding that does not block names its owning slice and the
  reason. A finding is not closed by being graded.
- **Resolver.** FX corrects today's cycle, depth and order defects for the
  inputs the product already accepts: both
  [separating examples](protocols.md#two-separating-examples) and the F1a
  rules that existing static routes, links and next-hop types can express.
  Before the change, FX meets F1a's fingerprint rule
  ([Rules](protocols.md#rules), first item) on today's inputs: it extends
  `tests/test_fingerprints.py` to the outputs and scenarios listed there,
  records the baselines, and lists and confirms every difference as intended.
  The correction changes the one resolver in place, with no fallback or
  second resolver.
- FX is complete when every blocker assigned to it is fixed and confirmed and
  every other finding has an owner and a reason.
