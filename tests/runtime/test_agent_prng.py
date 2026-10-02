"""Agent PRNG state across publication, rejection, seed edits, reset and restart."""

import pytest

from ngraph_sim import Environment
from ngraph_sim.model import contracts as c
from ngraph_sim.model.prng import Prng
from ngraph_sim.model.state import validate_admitted, validate_immutable
from ngraph_sim.runtime import Simulation
from ngraph_sim.runtime.agents import AgentBatchError
from tests.runtime.inbox import deliver_now
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
            deliver_now(sim, 'r', 'test', c.TimerFired(0, 'tick'))
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
    deliver_now(sim, 'r', 'test', c.TimerFired(0, 'tick'))
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


def _tick(sim):
    deliver_now(sim, 'r', 'test', c.TimerFired(0, 'tick'))
    sim.settle()


def test_seed_edit_before_first_publication_is_honored():
    values = []

    def callback(ctx):
        values.append(ctx.rng.random())
        return c.AgentOutput(state=ctx.agent_state)

    sim = fixture(Plugin(callback=callback))
    sim.network['r'].configure(seed=7)
    assert node(sim).rng is None
    sim.settle()
    expected = Prng.for_agent(0, 7, 'test', node(sim).generation)
    assert values == [expected.random()]
    assert node(sim).rng == expected.getstate()


def test_seed_edits_after_first_publication_neither_reseed_nor_grow_state():
    def scenario(edit):
        values = []

        def callback(ctx):
            values.append(ctx.rng.stream('jitter').random())
            return c.AgentOutput(state=ctx.agent_state)

        sim = fixture(Plugin(callback=callback))
        sim.settle()
        committed = node(sim).rng
        base = sim.state.devices['r'].config.seed
        keys = set()
        for run in range(64):
            if edit:  # Cycling through eight seeds includes changing back.
                sim.network['r'].configure(seed=base + 1 + run % 8)
                sim.network.seed = run
            _tick(sim)
            keys.add(node(sim).rng[0])
        assert keys == {committed[0]}
        assert len(node(sim).rng[1]) == 1
        return values

    assert scenario(True) == scenario(False)


def test_seed_edit_after_idle_first_publication_keeps_the_committed_key():
    draws = []
    draw = False

    def callback(ctx):
        if draw:
            draws.append(ctx.rng.random())
        return c.AgentOutput(state=ctx.agent_state)

    sim = fixture(Plugin(callback=callback))
    sim.settle()  # The first publication commits the key before any draw.
    seed = sim.state.devices['r'].config.seed
    family = Prng.for_agent(0, seed, 'test', node(sim).generation)
    assert node(sim).rng == (family.getstate()[0], ())
    sim.network['r'].configure(seed=seed + 5)
    draw = True
    _tick(sim)
    assert draws == [family.random()]
    assert node(sim).rng == family.getstate()


def test_rejected_run_then_seed_edit_continues_the_family_until_reset():
    values = []
    fail = False

    def callback(ctx):
        values.append((ctx.generation, ctx.rng.random()))
        if fail:
            raise ValueError('reject')
        return c.AgentOutput(state=ctx.agent_state)

    sim = fixture(Plugin(callback=callback))
    sim.settle()
    seed = sim.state.devices['r'].config.seed
    first = node(sim)
    fail = True
    deliver_now(sim, 'r', 'test', c.TimerFired(0, 'tick'))
    with pytest.raises(AgentBatchError):
        sim.settle()
    assert node(sim).rng is first.rng
    sim.network['r'].configure(seed=seed + 1)
    fail = False
    sim.retry()
    sim.settle()
    family = Prng.for_agent(0, seed, 'test', first.generation)
    one, two = family.random(), family.random()
    assert [value for _, value in values] == [one, two, two]
    sim.reset_agent('r', 'test')
    assert node(sim).rng is None
    sim.settle()
    generation = node(sim).generation
    assert generation != first.generation
    fresh = Prng.for_agent(0, seed + 1, 'test', generation)
    assert values[-1] == (generation, fresh.random())
    assert node(sim).rng == fresh.getstate()


def test_restart_adopts_the_current_network_seed_for_the_new_generation():
    values = []

    def callback(ctx):
        values.append((ctx.generation, ctx.rng.random()))
        return c.AgentOutput(state=ctx.agent_state)

    sim = fixture(Plugin(callback=callback))
    sim.settle()
    seed = sim.state.devices['r'].config.seed
    sim.network.seed = 42  # Ignored by the committed generation...
    _tick(sim)
    generation = node(sim).generation
    family = Prng.for_agent(0, seed, 'test', generation)
    assert [v for g, v in values if g == generation] == [
        family.random(),
        family.random(),
    ]
    fresh = Simulation(Environment(), sim.network.fork())  # ...adopted on restart.
    fresh.settle()
    restarted = node(fresh).generation
    assert restarted != generation
    assert values[-1] == (
        restarted,
        Prng.for_agent(42, seed, 'test', restarted).random(),
    )
