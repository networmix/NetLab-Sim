# NetLab-Sim project identity

NetGraph-Sim becomes NetLab-Sim. The distribution and command change from
`ngraph-sim` to `netlab-sim`; Python imports change from `ngraph_sim` to
`netlab_sim`. The debug variable is `NETLAB_SIM_DEBUG`, and opaque immutable
plugin types declare `__netlab_sim_immutable__`. There are no compatibility
aliases; callers must use the new names.
Pickles referring to `ngraph_sim` cannot load under the new package because
old module aliases are absent.

Simulation algorithms, result schemas, package version and PRNG sequences
are unchanged. PRNG version-one hash personalizations retain their exact
bytes. Dated reports and raw benchmark provenance retain their historical
names. For comparisons with older revisions, use that revision's scripts.

Development installs require `pytest>=8,<9.2` for compatibility with
pytest-benchmark 5.3.

Lint, type checks and tests passed on GIL and free-threaded Python.
Wheel and sdist identities, installed CLI/API entry points, PRNG known
answers and deterministic simulation outputs were verified. No performance
claim is made.

NetGraph releases without `Scenario.run()` are incompatible with the
optional scenario adapter.
