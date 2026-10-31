"""Bounded defaults and explicit full-history retention for simulations/studies."""

import sys

import pytest

from netlab_sim import Environment
from netlab_sim.model import contracts as c
from netlab_sim.model.network import Network
from netlab_sim.runtime import Simulation
from netlab_sim.runtime.timeline import Timeline
from netlab_sim.study import Study


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
    # Default budgets plus the amortized trim slack.
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


@pytest.mark.parametrize('keep', [None, 0, 7])
def test_explicit_retention_overrides_survive_all_constructor_paths(keep):
    timeline = Timeline(keep_records=keep, keep_events=keep)
    simulation = Simulation(
        Environment(), Network(), keep_records=keep, keep_events=keep
    )
    study = Study(Network(), keep={'records': keep, 'events': keep})._simulation()
    for tl in (timeline, simulation.timeline, study.timeline):
        assert tl.keep_records == tl.keep_events == keep


def test_standalone_timeline_and_agent_study_share_bounded_defaults():
    tl = Timeline()
    assert tl.keep_records == 10_000 and tl.keep_events == 100_000
    net = Network(seed=1)
    net.add_device('r')
    net.add_agent('r', _Ticker())
    study = Study(net)
    sim = study._simulation(warmup=1)
    sim.run_until(1)
    assert sim.timeline.keep_records == 10_000
    assert sim.timeline.keep_events == 100_000


@pytest.mark.parametrize(
    'keep,expected',
    [
        ({}, (100_000, 10_000)),
        ({'events': None, 'records': None}, (None, None)),
        ({'events': 5}, (5, 10_000)),
        # Series and exported rows come from events: asking for them keeps all.
        ({'arrays': True}, (None, 10_000)),
        ({'timeline': True}, (None, 10_000)),
        ({'arrays': True, 'timeline': True, 'events': 7}, (7, 10_000)),
    ],
)
def test_workload_reports_effective_runtime_retention(keep, expected):
    study = Study(Network(), keep=keep)
    retention = dict(study.describe().retention)
    runtime = study._simulation().timeline
    assert (retention['events'], retention['records']) == expected
    assert (runtime.keep_events, runtime.keep_records) == expected
