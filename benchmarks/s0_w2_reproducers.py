"""Explicit S0/W2 acceptance probes, red until the ownership blocker is resolved.

Run with: venv/bin/python -m pytest --no-cov -s benchmarks/s0_w2_reproducers.py
These are kept outside default test discovery because no fix has been applied.
See tests/runtime/s0-w2-handoff.md for the blocked integration dependencies.
"""

import gc
import sys
import tracemalloc

import pytest

from netsim import Environment
from netsim.model import contracts as c
from netsim.model.lpm import PrefixTable
from netsim.model.network import Network
from netsim.runtime import Simulation
from netsim.study import Study


@pytest.mark.parametrize('bits', [32, 128])
@pytest.mark.parametrize('frozen', [False, True])
def test_empty_tables_have_no_per_table_mask_allocation(bits, frozen):
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        tables = [
            PrefixTable(bits).freeze() if frozen else PrefixTable(bits)
            for _ in range(1000)
        ]
        retained = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    print(f'{bits=}, {frozen=}, tables={len(tables)}, retained_bytes={retained}')
    # Generous allowance for table instances, dicts and the outer list, but
    # not 33/129 mask integers and their tuple per table.
    assert retained < 1_000_000


class _Ticker:
    def __init__(self):
        self.client = c.ClientId('tick', 0)
        self.profile = c.ClientProfile(self.client, 250)
        self.config = c.AgentConfig()

    def subscriptions(self):
        return ()

    def on_init(self, ctx):
        return c.AgentOutput(state=ctx.agent_state, timers=(c.TimerOp('t', 1.0),))

    on_run = on_init


@pytest.mark.timeout(180)
def test_default_idle_run_has_bounded_event_and_record_history():
    net = Network(seed=1)
    net.add_device('r')
    net.add_agent('r', _Ticker())
    sim = Simulation(Environment(), net)
    tl = sim.timeline
    for horizon in (60_000.5, 120_000.5):
        sim.run_until(horizon)
        shallow_bytes = sum(
            sys.getsizeof(seq) + sum(map(sys.getsizeof, seq))
            for seq in (tl.records, tl.events)
        )
        print(
            f'{horizon=}, records={len(tl.records)}, events={len(tl.events)}, '
            f'dropped_records={tl.dropped_records}, '
            f'dropped_events={tl.dropped_events}, {shallow_bytes=}'
        )
    # Proposed budgets, including the existing amortized trim slack.
    assert len(tl.records) <= 10_000 + max(64, 10_000 // 8)
    assert len(tl.events) <= 100_000 + max(64, 100_000 // 8)
    assert tl.dropped_records > 0 and tl.dropped_events > 0


def test_study_does_not_implicitly_select_unbounded_history():
    sim = Study(Network())._simulation()
    print(
        f'Study keep_records={sim.timeline.keep_records}, '
        f'keep_events={sim.timeline.keep_events}'
    )
    assert sim.timeline.keep_records == 10_000
    assert sim.timeline.keep_events == 100_000
