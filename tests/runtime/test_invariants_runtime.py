"""Design rules for the runtime, mirroring tests/test_invariants.py."""

import inspect

import netlab_sim
from netlab_sim.runtime import events, pipeline


def _event_subclasses():
    found = []
    for module in (pipeline, events):
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, netlab_sim.Event) and cls.__module__ == module.__name__:
                found.append(cls)
    return found


def test_runtime_event_types_declare_slots_and_set_every_slot():
    env = netlab_sim.Environment()
    instances = [
        pipeline.StageEvent(env, netlab_sim.DEFERRED, 0, lambda e: None, 0, 0.0, 0),
        events._Delivery(env, lambda e: None, None),
    ]
    covered = {type(i) for i in instances}
    for cls in _event_subclasses():
        assert '__slots__' in cls.__dict__, cls.__name__
        assert cls in covered, f'add {cls.__name__} to the instances list'
    for evt in instances:
        assert not hasattr(evt, '__dict__')
        for slot in netlab_sim.Event.__slots__:
            assert hasattr(evt, slot), f'{type(evt).__name__} missing {slot}'


def test_band_constants():
    assert (
        netlab_sim.NORMAL < netlab_sim.DEFERRED < pipeline.ROUND_END < pipeline.SETTLED
    )
    assert pipeline.SETTLED == events.SETTLED
