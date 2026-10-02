"""Structural invariants that guard against drift in the core.

These tests encode design rules rather than behaviors:

* Every Event type uses ``__slots__`` (high-volume, fixed shape) and every
  constructor, inlined or not, initializes every slot declared on ``Event``.
* Environment and resources carry a ``__dict__`` so users can attach
  attributes to them.
* FIFO resource queues remove their head in O(1).
"""

import inspect
from collections import deque

import pytest

import ngraph_sim
from ngraph_sim import core, resources


def _event_subclasses():
    found = []
    for module in (core, resources):
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, ngraph_sim.Event) and cls.__module__ == module.__name__:
                found.append(cls)
    return found


def _build_event_instances():
    """One instance of every Event type reachable through the public API."""
    env = ngraph_sim.Environment()
    store = ngraph_sim.Store(env)
    fstore = ngraph_sim.FilterStore(env)
    res = ngraph_sim.Resource(env)
    pres = ngraph_sim.PriorityResource(env)
    cont = ngraph_sim.Container(env, capacity=10, init=5)

    def gen(env):
        yield env.timeout(1)

    proc = env.process(gen(env))
    victim = env.process(gen(env))

    def attacker(env):
        yield env.timeout(0)
        victim.interrupt('x')

    env.process(attacker(env))
    # Step until the interruption event is created but not processed.
    while not any(isinstance(e[3], core._Interruption) for e in env._queue):
        env.step()
    interruption = next(
        e[3] for e in env._queue if isinstance(e[3], core._Interruption)
    )

    class _Stub(resources.BaseResource):
        def _do_put(self, event):
            return None

        def _do_get(self, event):
            return None

    stub = _Stub(env, 1)
    fresh = env.process(gen(env))  # its target is still the _Initialize event

    return [
        env.event(),
        env.timeout(1),
        proc,
        fresh._target,
        interruption,
        resources.Put(stub),
        resources.Get(stub),
        ngraph_sim.AllOf(env, [env.event()]),
        ngraph_sim.AnyOf(env, [env.event()]),
        ngraph_sim.Condition(env, ngraph_sim.Condition.all_events, []),
        store.put(1),
        store.get(),
        fstore.get(lambda x: True),
        res.request(),
        res.release(res.request()),
        pres.request(priority=1),
        cont.put(1),
        cont.get(1),
    ]


class TestEventSlots:
    def test_every_event_type_declares_slots(self):
        missing = [
            c.__name__ for c in _event_subclasses() if '__slots__' not in c.__dict__
        ]
        assert missing == [], f'Event types without __slots__: {missing}'

    def test_no_event_instance_has_a_dict(self):
        for evt in _build_event_instances():
            assert not hasattr(evt, '__dict__'), type(evt).__name__

    def test_every_event_constructor_sets_every_event_slot(self):
        """Constructors inline ``Event.__init__`` for speed; make sure none of
        them forgets a slot (an unset slot raises AttributeError on read)."""
        for evt in _build_event_instances():
            for slot in ngraph_sim.Event.__slots__:
                assert hasattr(evt, slot), f'{type(evt).__name__} missing {slot}'

    def test_all_public_event_types_are_covered(self):
        covered = {type(e) for e in _build_event_instances()}
        uncovered = [c.__name__ for c in _event_subclasses() if c not in covered]
        assert uncovered == [], f'add these to _build_event_instances: {uncovered}'


class TestUserExtensibleObjects:
    @pytest.mark.parametrize(
        'factory',
        [
            lambda env: env,
            lambda env: ngraph_sim.Store(env),
            lambda env: ngraph_sim.FilterStore(env),
            lambda env: ngraph_sim.PriorityStore(env),
            lambda env: ngraph_sim.Resource(env),
            lambda env: ngraph_sim.PriorityResource(env),
            lambda env: ngraph_sim.PreemptiveResource(env),
            lambda env: ngraph_sim.Container(env),
        ],
    )
    def test_accepts_arbitrary_attributes(self, factory):
        obj = factory(ngraph_sim.Environment())
        obj.tag = 'x'
        assert obj.tag == 'x'


class TestResourceQueues:
    @pytest.mark.parametrize(
        'factory',
        [
            lambda env: ngraph_sim.Store(env),
            lambda env: ngraph_sim.FilterStore(env),
            lambda env: ngraph_sim.PriorityStore(env),
            lambda env: ngraph_sim.Resource(env),
            lambda env: ngraph_sim.Container(env),
        ],
    )
    def test_fifo_queues_are_deques(self, factory):
        r = factory(ngraph_sim.Environment())
        assert isinstance(r.put_queue, deque)
        assert isinstance(r.get_queue, deque)

    def test_priority_put_queue_is_sorted(self):
        r = ngraph_sim.PriorityResource(ngraph_sim.Environment())
        assert isinstance(r.put_queue, resources.SortedQueue)
        assert isinstance(r.get_queue, deque)

    def test_resource_queue_alias(self):
        r = ngraph_sim.Resource(ngraph_sim.Environment())
        assert r.queue is r.put_queue

    def test_large_backlog_drains_in_fifo_order(self):
        env = ngraph_sim.Environment()
        res = ngraph_sim.Resource(env, capacity=1)
        order = []

        def user(env, i):
            with res.request() as req:
                yield req
                order.append(i)
                yield env.timeout(1)

        n = 2000
        for i in range(n):
            env.process(user(env, i))
        env.run()
        assert order == list(range(n))
        assert len(res.queue) == 0
        assert res.count == 0


class TestTriggerLoopProtocol:
    """The trigger loop must honor the ``_do_put``/``_do_get`` return
    protocol for custom resources, including non-head (bypass) removal."""

    class _MatchStore(resources.BaseResource):
        """Puts are served out of order: a get claims the pending put holding
        its exact item, and that put is then completed by the put loop even
        when it is not at the head of the queue."""

        class _Put(resources.Put):
            __slots__ = ('item', 'claimed')

            def __init__(self, store, item):
                self.item = item
                self.claimed = False
                super().__init__(store)

        class _Get(resources.Get):
            __slots__ = ('item',)

            def __init__(self, store, item):
                self.item = item
                super().__init__(store)

        def __init__(self, env):
            super().__init__(env, capacity=float('inf'))

        def put(self, item):
            return self._Put(self, item)

        def get(self, item):
            return self._Get(self, item)

        def _do_put(self, event):
            if event.claimed:
                event.succeed()
            return True  # keep scanning: later puts may be claimed too

        def _do_get(self, event):
            for put_event in self.put_queue:
                if put_event.item == event.item and not put_event.claimed:
                    put_event.claimed = True
                    event.succeed(put_event.item)
                    break
            return True

    def test_non_head_put_is_removed_from_the_middle_of_the_queue(self):
        env = ngraph_sim.Environment()
        store = self._MatchStore(env)
        got = []
        done = []

        def producer(env):
            yield store.put('a') & store.put('b') & store.put('c')
            done.append(env.now)

        def consumer(env):
            yield env.timeout(1)
            got.append((yield store.get('b')))  # served from index 1
            got.append((yield store.get('c')))  # served from index 1 again
            got.append((yield store.get('a')))  # served from the head

        env.process(producer(env))
        env.process(consumer(env))
        env.run()
        assert got == ['b', 'c', 'a']
        assert done == [1]
        assert len(store.put_queue) == 0
        assert len(store.get_queue) == 0

    def test_queue_mutation_inside_do_put_is_detected(self):
        """A ``_do_put`` that reorders the queue under the loop's feet must be
        caught by the invariant guard rather than corrupt the queue."""
        env = ngraph_sim.Environment()

        class Broken(resources.BaseResource):
            def _do_put(self, event):
                if len(self.put_queue) < 2:
                    return None  # first put stays pending
                # Loop is at index 0; move that event to the tail, then
                # trigger it, so the head is no longer the triggered event.
                self.put_queue.remove(event)
                self.put_queue.append(event)
                event.succeed()
                return None

            def _do_get(self, event):
                return None

        broken = Broken(env, capacity=1)
        first = resources.Put(broken)
        assert not first.triggered
        with pytest.raises(RuntimeError, match='Put queue invariant violated'):
            resources.Put(broken)
