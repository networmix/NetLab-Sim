"""Deterministic simulation PRNG, version 1 (not cryptographic).

Every stream is SplitMix64 (Steele, Lea and Flood, 2014,
https://doi.org/10.1145/2714064.2660195; reference code at
https://prng.di.unimi.it/splitmix64.c): word n is the reference generator
seeded with the stream id after n increments, in 64-bit arithmetic.

State is ``(key, counters)``: the family's 64-bit base key and a sorted tuple
of (stream id, draw count) pairs, one per stream that has drawn. The key is
set once when the family is created, so a restored family continues its
sequence even if the seeds it came from have changed.

Version 1 fixes the hash encoding, the constants and every distribution below.
It does not reproduce ``random.Random`` sequences, and generation uses no
stdlib random code, ``hash()`` or mutable globals. Code that persists state
outside NetSim must record ``Prng.VERSION`` with it and pass it back on restore.
"""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import blake2b
from operator import index
from typing import TypeAlias, TypeVar

PrngCounters: TypeAlias = tuple[tuple[int, int], ...]
PrngState: TypeAlias = tuple[int, PrngCounters]
_T = TypeVar('_T')
_MASK = 0xFFFFFFFFFFFFFFFF


def _field(value: bytes) -> bytes:
    return len(value).to_bytes(8, 'big') + value


def _integer(value: int) -> bytes:
    value = index(value)
    magnitude = abs(value)
    return bytes((value < 0,)) + _field(
        magnitude.to_bytes((magnitude.bit_length() + 7) // 8, 'big')
    )


def _splitmix64(stream: int, counter: int) -> int:
    """Reference SplitMix64 word at the given (one-based) draw counter."""
    word = (stream + counter * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    word = ((word ^ (word >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    word = ((word ^ (word >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return word ^ (word >> 31)


def _check_version(version: object) -> None:
    if type(version) is not int or version != 1:
        raise ValueError('unsupported PRNG version')


def _check_key(key: object) -> int:
    if type(key) is not int or not 0 <= key <= _MASK:
        raise ValueError('PRNG base key must be a 64-bit unsigned integer')
    return key


def _check_counters(counters: object) -> PrngCounters:
    """Accept only the exact v1 shape: sorted exact-int pairs in 64-bit range."""
    if type(counters) is not tuple:
        raise ValueError('invalid v1 PRNG state')
    previous = -1
    for pair in counters:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError('invalid v1 PRNG stream entry')
        stream, counter = pair
        if (
            type(stream) is not int
            or type(counter) is not int
            or not previous < stream <= _MASK
            or not 0 <= counter <= _MASK
        ):
            raise ValueError('invalid v1 PRNG stream id/counter')
        previous = stream
    return counters


class _Bank:
    """Invocation-local counters shared by a family's handles; never committed.

    ``state`` stays the restored object until a draw marks the bank dirty.
    """

    __slots__ = ('state', 'counters', 'dirty')

    def __init__(self, state: PrngState) -> None:
        self.state = state
        self.counters: dict[int, int] | None = None
        self.dirty = False

    def word(self, stream: int) -> int:
        if self.counters is None:
            self.counters = dict(self.state[1])
        counter = (self.counters.get(stream, 0) + 1) & _MASK
        self.counters[stream] = counter
        self.dirty = True
        return _splitmix64(stream, counter)

    def getstate(self) -> PrngState:
        if self.dirty:
            assert self.counters is not None
            self.state = (self.state[0], tuple(sorted(self.counters.items())))
            self.dirty = False
        return self.state


class Prng:
    """A family of independent named streams under one base key.

    ``Prng(key, counters=())`` creates a family, ``for_agent`` derives the key
    from an agent's seeds, and ``restore(state)`` resumes a committed state
    under its own key. ``stream(name)`` returns a handle that shares the
    family's counters. Within one invocation the same name returns the same
    handle, and getting a handle draws nothing. Names nest as length-delimited
    paths, so ``stream('a/b')`` differs from ``stream('a').stream('b')``.

    ``getstate`` returns the restored object itself until something is drawn.
    Handles, and lists passed to ``shuffle``, belong to one invocation. The
    draw methods below follow ``random.Random``'s argument and range rules.
    ``sample`` takes no ``counts``, and other ``random.Random`` methods are not
    provided. A k-bit draw advances only its own stream, by ceil(k/64) words.
    """

    VERSION = 1
    __slots__ = ('_key', '_path', '_bank', '_id', '_children')

    def __init__(
        self, key: int, counters: PrngCounters = (), *, version: int = 1
    ) -> None:
        _check_version(version)
        key = _check_key(index(key))
        self._attach(key, _Bank((key, _check_counters(counters))))

    def _attach(self, key: int, bank: _Bank) -> None:
        self._key = key
        self._path = b''
        self._bank = bank
        self._id: int | None = None
        self._children: dict[str, Prng] | None = None

    @classmethod
    def restore(cls, state: PrngState, *, version: int = 1) -> Prng:
        """Resume a committed family under the key stored in ``state``."""
        _check_version(version)
        if type(state) is not tuple or len(state) != 2:
            raise ValueError('invalid v1 PRNG state')
        key, counters = state
        _check_key(key)
        _check_counters(counters)
        self = object.__new__(cls)
        self._attach(key, _Bank(state))
        return self

    @classmethod
    def for_agent(
        cls,
        network_seed: int,
        device_seed: int,
        agent_name: str,
        generation: int,
    ) -> Prng:
        """A fresh family keyed by an 8-byte BLAKE2b digest of the four fields.

        Integers are a sign byte and a length-prefixed big-endian magnitude;
        the name is length-prefixed UTF-8 without normalization. No two field
        tuples share an encoding. The runtime keys a generation here until its
        first publication and restores the committed state after that.
        """
        encoded = (
            _integer(network_seed)
            + _integer(device_seed)
            + _field(agent_name.encode('utf-8'))
            + _integer(generation)
        )
        key = int.from_bytes(
            blake2b(encoded, digest_size=8, person=b'NetSim.PRNG.v1').digest(),
            'big',
        )
        return cls(key)

    def stream(self, name: str) -> Prng:
        """The handle for ``name`` nested under this one; creating it draws nothing."""
        if not isinstance(name, str):
            raise TypeError('stream name must be a string')
        if self._children is None:
            self._children = {}
        child = self._children.get(name)
        if child is not None:
            return child
        child = object.__new__(Prng)
        child._key = self._key
        child._path = self._path + _field(name.encode('utf-8'))
        child._bank = self._bank
        child._id = None
        child._children = None
        self._children[name] = child
        return child

    def _word(self) -> int:
        if self._id is None:
            self._id = int.from_bytes(
                blake2b(
                    self._key.to_bytes(8, 'big') + self._path,
                    digest_size=8,
                    person=b'NetSim.stream.v1',
                ).digest(),
                'big',
            )
        return self._bank.word(self._id)

    def getstate(self) -> PrngState:
        """Return the family's immutable v1 state, by identity when unchanged."""
        return self._bank.getstate()

    def getrandbits(self, k: int) -> int:
        """Return k random bits; zero consumes nothing, negatives are invalid.

        Full words occupy low bits first; the last partial word uses its high
        bits. The word order and truncation are fixed by version 1.
        """
        k = index(k)
        if k < 0:
            raise ValueError('number of bits must be non-negative')
        result = 0
        for shift in range(0, k, 64):
            width = min(64, k - shift)
            result |= (self._word() >> (64 - width)) << shift
        return result

    def random(self) -> float:
        """Return a 53-bit float in [0, 1)."""
        return (self._word() >> 11) * (1.0 / 9007199254740992.0)

    def uniform(self, a: float, b: float) -> float:
        """Return ``a + (b - a) * random()``; ``b < a`` is allowed, as in ``random``."""
        return a + (b - a) * self.random()

    def _randbelow(self, n: int) -> int:
        if n <= 0:  # Rejection sampling below a non-positive bound never ends.
            raise ValueError('empty range for _randbelow()')
        bits = n.bit_length()
        value = self.getrandbits(bits)
        while value >= n:
            value = self.getrandbits(bits)
        return value

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        """Choose uniformly from range(start, stop, step), using rejection."""
        start, step = index(start), index(step)
        if stop is None:
            if step != 1:
                raise TypeError('missing stop argument')
            start, stop = 0, start
        else:
            stop = index(stop)
        if step == 0:
            raise ValueError('zero step for randrange()')
        width = stop - start
        count = (width + step - (1 if step > 0 else -1)) // step
        if count <= 0:
            raise ValueError('empty range for randrange()')
        return start + step * self._randbelow(count)

    def randint(self, a: int, b: int) -> int:
        """Choose an integer from the inclusive bounds [a, b]."""
        return self.randrange(index(a), index(b) + 1)

    def choice(self, seq: Sequence[_T]) -> _T:
        """Choose one element of a nonempty sequence."""
        if not len(seq):
            raise IndexError('cannot choose from an empty sequence')
        return seq[self._randbelow(len(seq))]

    def sample(self, population: Sequence[_T], k: int) -> list[_T]:
        """Sample positions without replacement in O(k) space (sparse shuffle)."""
        if not isinstance(population, Sequence):
            raise TypeError('population must be a sequence')
        k = index(k)
        size = len(population)
        if not 0 <= k <= size:
            raise ValueError('sample larger than population or negative')
        moved: dict[int, int] = {}
        result = []
        for i in range(k):
            remaining = size - i
            selected = self._randbelow(remaining)
            result.append(population[moved.get(selected, selected)])
            moved[selected] = moved.get(remaining - 1, remaining - 1)
        return result

    def shuffle(self, values: list[_T]) -> None:
        """Fisher-Yates shuffle of an invocation-local mutable list, in place."""
        if not isinstance(values, list):
            raise TypeError('shuffle requires an invocation-local list')
        for i in range(len(values) - 1, 0, -1):
            j = self._randbelow(i + 1)
            values[i], values[j] = values[j], values[i]
