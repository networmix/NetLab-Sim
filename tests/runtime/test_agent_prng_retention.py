"""G18: retained idle publications share one small committed RNG value."""

import sys

import pytest

from netsim.model import contracts as c
from tests.runtime.test_agents import Plugin, fixture


def retained_size(values):
    """Count each reachable RNG value once, including the MT integer leaves."""
    seen = set()
    stack = list(values)
    size = 0
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        size += sys.getsizeof(value)
        if isinstance(value, tuple):
            stack.extend(value)
    return size


@pytest.mark.parametrize('runs', [1, 32, 128])
@pytest.mark.parametrize('initial_draw', [False, True])
def test_idle_publications_retain_constant_rng_objects_and_bytes(runs, initial_draw):
    first = True

    def callback(ctx):
        nonlocal first
        if first and initial_draw:
            ctx.rng.random()
        first = False
        return c.AgentOutput(state=ctx.agent_state)

    sim = fixture(Plugin(callback=callback), keep_roots=None, keep_records=None)
    assert sim.state.devices['r'].agents['test'].rng is None
    sim.settle()
    nodes = [sim.state.devices['r'].agents['test']]
    for _ in range(runs):
        sim.agents.deliver('r', 'test', c.TimerFired(sim.env.now, 'idle'))
        sim.settle()
        nodes.append(sim.state.devices['r'].agents['test'])
    values = [node.rng for node in nodes]
    # Keep every publication alive: bounded timeline eviction cannot mask G18.
    assert len({id(value) for value in values}) == 1
    assert retained_size(values) <= 256
    assert nodes[-1].runs == runs + 1
