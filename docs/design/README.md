# Design

These pages specify behaviour NetLab-Sim does not have yet: the foundation for
Open/R and BGP, and the shared route-policy language. They are for maintainers
who implement or review that work.

## Which document decides what

| Question | Where the answer lives |
|---|---|
| What the code does now | The code and its tests, then the [README](../../README.md) and the [reference](../reference.md). [History reports](../history/README.md) record what each delivered slice changed and how it was checked, as of their date |
| What future work must guarantee | The design pages below. Each statement is a requirement for planned code, or an internal guarantee or decision that implemented code still keeps; neither is user documentation |
| What is planned, in which order, and its state | The [roadmap](../plan.md), the only place with status |
| Where a requirement came from | The [archive](archive/README.md): frozen design documents kept for extraction and provenance. They are not current rules and do not override anything above |

When a design page and the code disagree, the code describes today and the
page describes the target; the plan row says which slice closes the gap. When
the archive and a design page disagree, the design page wins.

## Pages

- [Protocol foundation](protocols.md): the common design decisions, the
  contracts for F0 and F5, the requirements for F1a, C6, S1a and S1b, and the
  list of pending contracts with their archived sources.
- [Routing policy](routing-policy.md): the route-policy language, attachment
  points, per-node configuration, lifecycle and the acceptance examples E01 to
  E24.

## Pending contracts

The roadmap records whether a slice's contract is ready
([status values](../plan.md#status-values)). Reconciling a pending contract
means: collect every requirement from the archived sections and from all later
amendments of them, write them as exact rules with the examples and tests that
check them, and resolve or record each conflict. A pending contract is
reconciled before its implementation starts, not all at once: work on the next
slice needs only its own contract and those it depends on.

Rules for these pages:

- One home per requirement. The plan holds order and state; a design page holds
  the rule; neither repeats the other.
- A design page names no status and no schedule. Planned names (records,
  modules, settings) are written as code-formatted names and are not links;
  links to code point only at files that exist.
- A behaviour taken from another implementation (FRR, Open/R) names its pinned
  source. Such a statement is a vendor reference until a reproducer or pinned
  fixture confirms it.
- When a slice lands, the behaviour users rely on moves into the README or the
  reference in the same change. Internal guarantees, their proofs and
  decisions that still bind later work may stay on the design page; anything
  that is no longer true or no longer binding is removed.

How the roadmap is kept current is under
[Maintaining the roadmap](../plan.md#maintaining-the-roadmap).
