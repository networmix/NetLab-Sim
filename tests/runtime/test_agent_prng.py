"""Runtime boundaries for compact base and module-stream counters."""

import pytest

from netsim import Environment
from netsim.model import contracts as c
from netsim.model.prng import Prng
from netsim.model.state import validate_admitted, validate_immutable
from netsim.runtime import Simulation
from netsim.runtime.agents import AgentBatchError
from tests.runtime.test_agents import Plugin, fixture


def node(sim):
    return sim.state.devices['r'].agents['test']


def test_named_streams_stay_independent_through_publication():
    def scenario(noisy):
        values = []
        runs = 0

        def callback(ctx):
            nonlocal runs
            if noisy:
                ctx.rng.stream('other').getrandbits(65 + runs)
                ctx.rng.random()
            if runs % 2:
                values.append(ctx.rng.stream('jitter').random())
            runs += 1
            return c.AgentOutput(state=ctx.agent_state)

        sim = fixture(Plugin(callback=callback))
        sim.network.debug_validate = True
        sim.settle()
        for _ in range(8):
            sim.agents.deliver('r', 'test', c.TimerFired(0, 'tick'))
            sim.settle()
        validate_immutable(node(sim).rng)
        validate_admitted(node(sim).rng, None)
        return values

    assert scenario(False) == scenario(True)


@pytest.mark.parametrize('failure', ['callback', 'admission', 'outer_commit'])
def test_rejected_named_draws_replay_and_preserve_pre_run_identity(
    failure, monkeypatch
):
    attempts = []
    reject = False

    def callback(ctx):
        attempts.append((ctx.rng.random(), ctx.rng.stream('jitter').getrandbits(96)))
        if reject and failure == 'callback':
            raise ValueError('reject draw')
        if reject and failure == 'admission':
            return c.AgentOutput(state=[])
        return c.AgentOutput(state=ctx.agent_state)

    sim = fixture(Plugin(callback=callback))
    sim.settle()
    admitted = node(sim).rng
    reject = True
    update = sim.network.update

    def guarded(fn, origin='op'):
        if reject and failure == 'outer_commit' and origin[:2] == ('kind', 'agent'):
            fn(sim.state)
            raise RuntimeError('reject outer commit')
        return update(fn, origin)

    monkeypatch.setattr(sim.network, 'update', guarded)
    sim.agents.deliver('r', 'test', c.TimerFired(0, 'tick'))
    with pytest.raises(RuntimeError if failure == 'outer_commit' else AgentBatchError):
        sim.settle()
    assert node(sim).rng is admitted
    reject = False
    sim.retry()
    sim.settle()
    assert attempts[-1] == attempts[-2] != attempts[0]
    assert node(sim).rng is not admitted


def test_reset_and_fresh_simulation_clear_all_streams():
    observed = []

    def callback(ctx):
        actual = (ctx.rng.random(), ctx.rng.stream('jitter').random())
        expected = Prng.for_agent(0, ctx.config.seed, ctx.agent, ctx.generation)
        assert actual == (expected.random(), expected.stream('jitter').random())
        observed.append((ctx.generation, actual))
        return c.AgentOutput()

    sim = fixture(Plugin(callback=callback))
    assert node(sim).rng is None
    sim.settle()
    original = node(sim)
    sim.reset_agent('r', 'test')
    assert node(sim).rng is None and not node(sim).initialized
    sim.settle()
    assert node(sim).generation != original.generation
    fork = sim.network.fork()
    fresh = Simulation(Environment(), fork)
    assert node(fresh).rng is None and not node(fresh).initialized
    fresh.settle()
    assert len({generation for generation, _ in observed}) == 3
    assert len({values for _, values in observed}) == 3
    assert node(sim).rng is not None  # The existing runtime's snapshot stays intact.
