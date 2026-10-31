# Development history

Reports written when a slice of work was merged: what changed, the evidence
that it fixed what it set out to fix, and the measurements. Each report is a
snapshot of its date. The code, its docstrings and the
[reference](../reference.md) define current behaviour; where a report
disagrees with them, the report is out of date.

The project was called NetSim, with the package `netsim`, until 2026-10-02,
when it became NetGraph-Sim (`ngraph-sim`, imported as `ngraph_sim`). The
reports keep the old names. On 2026-10-31 the project became NetLab-Sim
(`netlab-sim`, imported as `netlab_sim`). Benchmark scripts now import
`netlab_sim`, so a comparison against a revision from before the rename
needs the script from that revision.

Gate A is the plain-IP simulator, Gate B adds SRv6 and Gate C adds protocol
agents. The T slices are scale fixes made after Gate A. S0 is scale hygiene
before the Open/R and BGP work. Benchmark scripts and raw results are in
[`benchmarks/`](../../benchmarks).

## Project identity, 2026-10-31

| Report | Topic |
| --- | --- |
| [Rename](rename-project-identity.md) | NetLab-Sim package, distribution and command names |

## Scale fixes after Gate A, 2026-09-20

| Report | Topic | Note |
| --- | --- | --- |
| [T1](t1-pmap-sharding.md) | Persistent map sharding | |
| [T2](t2-scoped-batches.md) | `Network.batch()` and NetGraph construction | Convergence inside a batch is superseded by T2C |
| [T2B](t2b-convergence-boundaries.md) | Convergence boundaries and incremental RIB snapshots | Convergence inside a batch is superseded by T2C |
| [T2C](t2c-committed-root-derivations.md) | Committed-root derivations and complete observer dispatch | |
| [T3](t3-rib-indexes.md) | RIB prefix and client indexes | Client-index and mutation-cost notes are superseded by T3B |
| [T3B](t3b-rib-updates.md) | Deletion ownership and incremental RIB updates | |
| [T4](t4-deadline-heap.md) | Deadline heap in the scheduler | The carrier workload was finished in T7 |
| [T6](t6-failure-studies.md) | Failure sources, leases, serial studies and the NetGraph CLI, with the T6B follow-up | |
| [T7](t7-scoped-l3.md) | Interface-scoped L3 | |

T5, oracle reuse (`scale/t5-oracle-reuse`), has no report.

## Gate C, 2026-09-20 and 2026-09-21

| Report | Topic |
| --- | --- |
| [C2](c2-nht.md) | Local queries, next-hop tracking and learned SR validation |
| [C2F](c2f-nht-runtime-seams.md) | Runtime seam tests and scoped SR invalidation |
| [C2R](c2r-nht-detached-queries.md) | Detached queries and generation-bound NHT scopes |
| [C4](c4-reference-agent.md) | Reference link-state protocol |
| [C5](c5-study-windows.md) | Study windows and qualification, with the C5R baseline fix |

## S0, 2026-09-27

| Report | Topic | Note |
| --- | --- | --- |
| [W1](s0-w1-locator-index.md) | Locator validation index and SRv6 consumer index | Timings are indicative |
| [W2](s0-w2-masks-retention.md) | Prefix-table masks and bounded timeline retention | Lookup timings are indicative |
| [W3](s0-w3-prng.md) | Compact agent PRNG | Updated for the seed lifecycle fix of 2026-10-02 |

New reports go in this directory as `<slice>-<topic>.md`, with a row here.
