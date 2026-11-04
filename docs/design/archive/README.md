# Design archive

Frozen copies of the design documents written before the plan moved into this
repository. They are kept byte for byte as they were last revised, so that
every requirement can be traced to its source. They are not current rules: the
[design pages](../README.md) and [docs/roadmap.md](../../roadmap.md) override them,
and their status statements (what is implemented, what can start, test counts,
review outcomes, measurements) describe their own date and older commits.

The project was called NetSim, with the package `netsim`, and from
2026-10-02 NetGraph-Sim (`ngraph_sim`); it is now NetLab-Sim (`netlab_sim`).
The documents keep the old names, file paths and links. Links to files
outside this repository (research notes, local checkouts, other documents
under their old names) are not repaired and may not resolve; nothing current
depends on them.

| File | Original name | Content | Revision and date | SHA-256 |
|---|---|---|---|---|
| [network-layer-r17.md](network-layer-r17.md) | `hazy-foraging-cloud.md` | Network-layer design of record: Gates A, B and C | Revision 17 (Gate C implemented), with a rename note of 2026-10-02 | `22bf74952aaeb9c975b428b88fcd1bbf4f9f5202b4a4f49cd7d5ec42112aca5e` |
| [protocols-r8.md](protocols-r8.md) | `netsim-protocols.md` | Open/R and BGP design and plan; slice table §15.9 amended by §16.9; S0 delivery in §17 | Revision 8, 2026-09-27, with S0 updates of 2026-10-02 | `995c2d5b0c1ef986804125cd5737971e01beedce7d7329105e6b8ed1caaf53a9` |
| [routing-policy-r4.md](routing-policy-r4.md) | `routing-policy.md` | Routing-policy language and hooks | Revision 4, 2026-09-27 | `2319e0a49de9aa29fefafe92bc757a9db15bfb655f1db55aa977c4db1c8b36d3` |
| [routing-policy-reviews.md](routing-policy-reviews.md) | `routing-policy-reviews.md` | Review passes that produced routing-policy revision 4 | 2026-09-27 | `8e2f9d5759ea133f4fe77ee90e1b049cc01ca8c1884ba78366fbdf72d742283a` |

Within `protocols-r8.md`, later sections override earlier ones (§16 over §15,
§15 over the body). `routing-policy-r4.md` links to its review record by its
original file name, which is kept here.

To check the copies, run `shasum -a 256` on the four files in this directory
and compare with the table.
