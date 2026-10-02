"""The v1 sequence and API do not depend on stdlib random or interpreter state."""

import json
import os
import random
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from netsim.model.prng import Prng, _splitmix64
from netsim.model.state import validate_admitted, validate_immutable


def test_splitmix64_reference_known_answers():
    # Vigna's splitmix64.c, uint64_t x=0; five successive next() calls.
    assert [_splitmix64(0, n) for n in range(1, 6)] == [
        0xE220A8397B1DCDAF,
        0x6E789E6AA1B965F4,
        0x06C45D188009454F,
        0xF88BB8A8724C81EC,
        0x1B39896A51A8749B,
    ]
    assert _splitmix64(0, 1 << 64) == _splitmix64(0, 0) == 0


def test_v1_seed_encoding_and_public_known_answers():
    rng = Prng.for_agent(1, -2, 'a:β', 3)
    assert rng.VERSION == 1
    assert [rng.getrandbits(64) for _ in range(4)] == [
        3171570192269507457,
        8438255699371477715,
        8398029112726890720,
        5784434096098153939,
    ]
    key = 9845853327430893526
    assert rng.getstate() == (key, ((9511305789293171608, 4),))
    assert [rng.stream('m:β').getrandbits(64) for _ in range(4)] == [
        6401095837003498183,
        4586300332935740154,
        14362780155090693659,
        3624566571900516395,
    ]
    assert rng.getstate() == (
        key,
        ((9149529816362344692, 4), (9511305789293171608, 4)),
    )
    assert Prng.for_agent(1, -2, 'a:β', 3).getstate() == (key, ())


def test_each_seed_field_and_name_path_is_distinct():
    seeds = [(1, 2, 'agent', 3), (-1, 2, 'agent', 3), (1, -2, 'agent', 3)]
    seeds += [(1, 2, 'Agent', 3), (1, 2, 'agent', 4), (12, 3, 'agent', 4)]
    seeds += [(1, 23, 'agent', 4), (1 << 200, 2, 'agent', 3)]
    assert len({Prng.for_agent(*seed).getrandbits(64) for seed in seeds}) == len(seeds)
    rng = Prng(0)
    streams = [rng, rng.stream(''), rng.stream('a/b'), rng.stream('a').stream('b')]
    streams += [rng.stream('ab').stream('c'), rng.stream('a').stream('bc')]
    assert len({stream.getrandbits(64) for stream in streams}) == len(streams)


def test_stream_independence_across_runs_including_previously_idle_run():
    def scenario(extra):
        state = None
        values = []
        for run in range(8):
            rng = Prng(123) if state is None else Prng.restore(state)
            if extra:
                for _ in range(run + 1):
                    rng.stream('noisy').random()
                rng.random()
            if run % 2:
                values.append([rng.stream('jitter').random() for _ in range(3)])
            state = rng.getstate()
        return values

    assert scenario(False) == scenario(True)


def test_repeated_handles_continue_and_state_is_canonical():
    first, second = Prng(91), Prng(91)
    for name in ('b', 'a', 'b', ''):
        first.stream(name).random()
    for name in ('', 'b', 'b', 'a'):
        second.stream(name).random()
    state = first.getstate()
    assert state == second.getstate()
    key, counters = state
    assert key == 91 and counters == tuple(sorted(counters))
    assert len(counters) == 3  # No unused base stream entry.
    validate_immutable(state)
    validate_admitted(state, None)
    restored = Prng.restore(state)
    assert restored.getstate() is state
    assert restored.stream('b').random() == first.stream('b').random()
    assert restored.getstate() == first.getstate()
    validate_admitted(restored.getstate(), state)


def test_named_handles_are_identical_only_within_the_invocation():
    rng = Prng(51)
    first = rng.stream('module')
    assert rng.stream('module') is first
    assert rng.stream('module').stream('child') is first.stream('child')
    assert rng.stream('different') is not first
    fresh = rng.getstate()
    assert fresh == (51, ()) and rng.getstate() is fresh  # No cursor from a handle.
    first.random()
    restored = Prng.restore(rng.getstate())
    assert restored.stream('module') is not first
    assert restored.stream('module').random() == first.random()


def test_other_random_methods_raise_attribute_error():
    supported = {
        'random',
        'uniform',
        'randrange',
        'randint',
        'choice',
        'sample',
        'shuffle',
        'getrandbits',
        'getstate',
    }
    rng = Prng(3)
    for name in dir(random.Random):
        if (
            not name.startswith('_')
            and name not in supported
            and callable(getattr(random.Random, name))
        ):
            with pytest.raises(AttributeError):
                getattr(rng, name)
    assert not hasattr(rng, 'gauss_next')  # No stdlib distribution cache.


def test_idle_and_zero_size_operations_reuse_state_identity():
    rng = Prng(1)
    fresh = rng.getstate()
    rng.stream('unused')
    assert rng.getrandbits(0) == 0
    assert rng.sample([], 0) == []
    assert rng.shuffle([]) is None
    rng.shuffle([1])
    assert fresh == (1, ()) and rng.getstate() is fresh
    rng.random()
    state = rng.getstate()
    assert state is not fresh and rng.getstate() is state
    resumed = Prng.restore(state)
    resumed.stream('still unused').getrandbits(0)
    assert resumed.getstate() is state
    # Retaining the old invocation's mutable handle cannot mutate a snapshot.
    before = (state[0], tuple(state[1]))
    rng.random()
    assert state == before and rng.getstate() is not state


def test_counter_wrap_is_64_bit_and_retains_drawn_stream():
    rng = Prng(3)
    rng.random()
    (_, ((stream, _),)) = rng.getstate()
    wrapped = Prng(3, ((stream, (1 << 64) - 1),))
    assert wrapped.getrandbits(64) == _splitmix64(stream, 0)
    assert wrapped.getstate() == (3, ((stream, 0),))


def test_float_and_bit_mapping():
    word = Prng(5).getrandbits(64)
    assert Prng(5).random() == (word >> 11) / (1 << 53)
    assert Prng(5).getrandbits(3) == word >> 61
    words = Prng(5)
    low, high = words.getrandbits(64), words.getrandbits(64)
    assert Prng(5).getrandbits(70) == low | ((high >> 58) << 64)
    for k in (0, 1, 32, 63, 64, 65, 129, 513):
        assert 0 <= Prng(5).getrandbits(k) < 1 << k


@pytest.mark.parametrize('args', [(8,), (-10, 8, 3), (10, -8, -3), (2**150,)])
def test_randrange_bounds(args):
    rng = Prng(7)
    population = range(*args)
    assert all(rng.randrange(*args) in population for _ in range(100))


def test_uniform_and_inclusive_randint():
    for a, b in ((-2.0, 5.0), (5.0, -2.0), (4.0, 4.0)):
        rng, reference = Prng(8), Prng(8)
        assert rng.uniform(a, b) == a + (b - a) * reference.random()
    rng = Prng(4)
    assert {rng.randint(-1, 1) for _ in range(100)} == {-1, 0, 1}
    assert rng.randint(4, 4) == 4


def test_choice_sample_and_shuffle_do_not_mutate_population():
    rng = Prng(54)
    source = [[1], [1], [2], [3]]  # Unhashable and repeated values are allowed.
    original = list(source)
    assert rng.choice(source) in source
    sample = rng.sample(source, 4)
    assert sorted(map(id, sample)) == sorted(map(id, source))
    assert source == original
    assert len(set(rng.sample(range(10**12), 50))) == 50
    items = list(range(20))
    assert rng.shuffle(items) is None
    assert sorted(items) == list(range(20)) and items != list(range(20))


@pytest.mark.timeout(5)
def test_uniformity_smoke():
    rng = Prng(12345)
    bins = Counter(rng.randrange(10) for _ in range(20_000))
    assert set(bins) == set(range(10))
    assert all(1750 < count < 2250 for count in bins.values())
    floats = [rng.random() for _ in range(20_000)]
    assert all(0 <= value < 1 for value in floats)
    assert 0.49 < sum(floats) / len(floats) < 0.51
    counts = Counter(tuple(rng.sample(range(3), 2)) for _ in range(6000))
    assert len(counts) == 6 and all(850 < count < 1150 for count in counts.values())


@pytest.mark.parametrize(
    'method,args,error',
    [
        ('getrandbits', (-1,), ValueError),
        ('getrandbits', (1.5,), TypeError),
        ('randrange', (0,), ValueError),
        ('randrange', (2, 1), ValueError),
        ('randrange', (1, 2, -1), ValueError),
        ('randrange', (1, 2, 0), ValueError),
        ('randrange', (5, None, 2), TypeError),
        ('randrange', (1.0,), TypeError),
        ('randrange', (1, 2.0), TypeError),
        ('randint', (2, 1), ValueError),
        ('choice', ([],), IndexError),
        ('sample', ([1], 2), ValueError),
        ('sample', ([1], -1), ValueError),
        ('sample', ({1, 2}, 1), TypeError),
        ('sample', ([1], 1.0), TypeError),
        ('shuffle', ((1, 2),), TypeError),
        ('stream', (1,), TypeError),
    ],
)
def test_invalid_calls_do_not_draw(method, args, error):
    rng = Prng(7)
    state = rng.getstate()
    with pytest.raises(error):
        getattr(rng, method)(*args)
    assert rng.getstate() is state


@pytest.mark.parametrize(
    'counters',
    [
        None,
        [],
        ((1,),),
        ((1, -1),),
        ((-1, 0),),
        ((1 << 64, 0),),
        ((1, 1 << 64),),
        ((1, True),),
        ((False, 1),),
        ((2, 1), (1, 1)),
        ((1, 1), (1, 2)),
        [(1, 2)],
    ],
)
def test_invalid_counters_are_rejected(counters):
    with pytest.raises(ValueError):
        Prng(0, counters)
    with pytest.raises(ValueError):
        Prng.restore((0, counters))


@pytest.mark.parametrize(
    'state',
    [
        None,
        (),
        (0,),
        [0, ()],
        (0, (), None),
        (-1, ()),
        (1 << 64, ()),
        (True, ()),
        (1.0, ()),
        (3, (1, 2, 3), None),  # The old Mersenne Twister shape.
    ],
)
def test_invalid_or_mt_state_is_rejected(state):
    with pytest.raises(ValueError):
        Prng.restore(state)


def test_invalid_key_or_version():
    for key in (-1, 1 << 64):
        with pytest.raises(ValueError):
            Prng(key)
    with pytest.raises(TypeError):
        Prng(1.0)
    with pytest.raises(ValueError, match='version'):
        Prng(0, version=2)
    with pytest.raises(ValueError, match='version'):
        Prng.restore((0, ()), version=2)


def test_restore_resumes_by_key_alone():
    original = Prng.for_agent(1, 2, 'agent', 3)
    original.random()
    original.stream('jitter').getrandbits(96)
    state = original.getstate()
    resumed = Prng.restore(state)
    reference = Prng.for_agent(1, 2, 'agent', 3)
    reference.random()
    reference.stream('jitter').getrandbits(96)
    assert resumed.random() == reference.random()
    assert resumed.stream('jitter').random() == reference.stream('jitter').random()
    assert resumed.getstate() == reference.getstate()
    assert state[0] == Prng.for_agent(1, 2, 'agent', 3).getstate()[0]
    assert state[0] != Prng.for_agent(1, 3, 'agent', 3).getstate()[0]


def test_randbelow_rejects_non_positive_bounds_without_drawing():
    rng = Prng(7)
    state = rng.getstate()
    for bound in (0, -3):
        with pytest.raises(ValueError):
            rng._randbelow(bound)
    assert rng.getstate() is state


def test_independent_instances_are_thread_local():
    def sequence(seed):
        rng = Prng(seed)
        return [rng.stream('module').getrandbits(64) for _ in range(100)]

    seeds = list(range(16))
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(sequence, seeds)) == [sequence(seed) for seed in seeds]


def test_subprocess_hash_seed_does_not_change_streams():
    script = """
import json
from netsim.model.prng import Prng
state = None
values = []
for run in range(3):
    r = Prng.for_agent(17, -9, 'module:β', 2) if state is None else Prng.restore(state)
    values.append([r.random(), r.randrange(-10, 12, 3), r.choice('abc'),
                   r.sample(range(30), 4), r.getrandbits(101),
                   r.stream('jitter').uniform(1, 5)])
    state = r.getstate()
print(json.dumps([values, state], sort_keys=True))
"""
    outputs = [
        subprocess.check_output(
            [sys.executable, '-c', script],
            env=dict(os.environ, PYTHONHASHSEED=seed),
            text=True,
        )
        for seed in ('1', '987654321')
    ]
    assert outputs[0] == outputs[1]
    assert len(json.loads(outputs[0])[0]) == 3
