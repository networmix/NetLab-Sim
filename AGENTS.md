# Development

- Setup: `bash .superset/workspace.sh setup`. Each worktree gets its own venv;
  setup does not replace the Git hooks shared by worktrees.
- Superset **Run**: `bash .superset/workspace.sh check` runs lint, types and
  all tests with coverage (`make check-ci`).
- `make qt` runs the tests without coverage, slow tests or benchmarks;
  `venv/bin/python -m pytest --no-cov --benchmark-enable tests/test_benchmarks.py`
  reports timings.
- `make venv-ft` then `make check-ft` runs the same checks on a free-threaded
  Python; CI runs them on 3.14t. Keep hot paths free of shared mutable
  objects and module-level sentinels: their reference counts serialize
  threads without the GIL.

Confirm suspected defects with source and a reproducer, then pin the fix with
a test that fails on the old code. Design rules live in
`tests/test_invariants.py` (engine) and `tests/runtime/test_invariants_runtime.py`
(network runtime). Performance claims need an old-vs-new comparison
on the same quiet machine. Local checks do not replace CI.

# Documentation

- `README.md` and `docs/reference.md` are the user documentation. Change
  them in the same commit as the behaviour they describe.
- Docstrings and comments state behaviour. They do not cite plans, reviews
  or milestones that live outside this repository.
- A slice's report goes in `docs/history/` as `<slice>-<topic>.md`, with a
  row in its README: what changed, the evidence, measurements and limits.
  Leave out process notes such as worktrees, ownership and log paths.
- `tests/` holds tests, fixtures and test data. Benchmark scripts and their
  raw results go in `benchmarks/`.
