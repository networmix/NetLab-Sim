"""Version 1 compact, deterministic simulation PRNG (not cryptographic).

Each stream uses SplitMix64: Vigna's public-domain reference implementation,
https://prng.di.unimi.it/splitmix64.c (Steele, Lea and Flood, 2014,
https://doi.org/10.1145/2714064.2660195). Word n is the reference generator
seeded with the stream id, after n increments. All arithmetic wraps at 64 bits.

The v1 state is a sorted tuple of (64-bit stream id, 64-bit draw counter)
pairs, or None before any draw. Only drawn streams occupy state. Version 1
fixes the hash encoding, SplitMix64 constants and every distribution below;
it intentionally does not reproduce random.Random's Mersenne Twister sequence.
No stdlib random algorithms, Python hashes, global caches or mutable globals
participate in generation. Callers persisting state outside NetSim must record
Prng.VERSION alongside it and supply that version when restoring.
"""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import blake2b
from operator import index
from typing import TypeAlias, TypeVar

PrngState: TypeAlias = tuple[tuple[int, int], ...] | None
_T = TypeVar('_T')


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


class _Bank:
    """Invocation-local cursors shared by named handles; never enter the tree."""

    __slots__ = ('state', 'counters', 'dirty')

    def __init__(self, state: PrngState) -> None:
        if state is not None:
            if not isinstance(state, tuple) or not state:
                raise ValueError('invalid v1 PRNG state')
            previous = -1
            for pair in state:
                if not isinstance(pair, tuple) or len(pair) != 2:
                    raise ValueError('invalid v1 PRNG stream entry')
                stream, counter = pair
                if (
                    type(stream) is not int
                    or type(counter) is not int
                    or not previous < stream <= 0xFFFFFFFFFFFFFFFF
                    or not 0 <= counter <= 0xFFFFFFFFFFFFFFFF
                ):
                    raise ValueError('invalid v1 PRNG stream id/counter')
                previous = stream
        self.state = state
        self.counters: dict[int, int] | None = None
        self.dirty = False

    def word(self, stream: int) -> int:
        if self.counters is None:
            self.counters = dict(self.state or ())
        counter = (self.counters.get(stream, 0) + 1) & 0xFFFFFFFFFFFFFFFF
        self.counters[stream] = counter
        self.dirty = True
        return _splitmix64(stream, counter)

    def getstate(self) -> PrngState:
        if self.dirty:
            assert self.counters is not None
            self.state = tuple(sorted(self.counters.items()))
            self.dirty = False
        return self.state


class Prng:
    """A v1 SplitMix64 family with independent, persistent named streams.

    ``Prng(key, state=None, version=1)`` restores a family under a 64-bit
    base key. ``for_agent`` derives that key from the four agent seed fields.
    ``stream(name)`` returns a handle sharing this invocation's counters;
    repeated calls for the same path return the same private stream object.
    Nested names
    are length-delimited paths, so stream('a/b') differs from stream('a').
    stream('b'). Merely obtaining a handle consumes nothing.

    ``getstate`` snapshots all drawn streams and preserves the original object
    when no word was drawn. Restore with the same key/version in the next run;
    handles and lists passed to ``shuffle`` must stay invocation-local.
    Supported draw methods are random, uniform, randrange, randint, choice,
    sample, shuffle and getrandbits. They follow random.Random's argument/range
    semantics, without its sequence compatibility or sample(counts=...) API.
    Other random.Random methods are unsupported and raise AttributeError.
    There are no distribution caches. reset_agent starts fresh counters under
    the new generation's key; rejection preserves every pre-run counter.
    Each word advances only its stream; a k-bit draw uses ceil(k/64) words.
    """

    VERSION = 1
    __slots__ = ('_key', '_path', '_bank', '_id', '_children')

    def __init__(self, key: int, state: PrngState = None, *, version: int = 1) -> None:
        if type(version) is not int or version != 1:
            raise ValueError('unsupported PRNG version')
        key = index(key)
        if not 0 <= key <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError('PRNG base key must be a 64-bit unsigned integer')
        self._key = key
        self._path = b''
        self._bank = _Bank(state)
        self._id: int | None = None
        self._children: dict[str, Prng] | None = None

    @classmethod
    def for_agent(
        cls,
        network_seed: int,
        device_seed: int,
        agent_name: str,
        generation: int,
        state: PrngState = None,
    ) -> Prng:
        """Hash sign/magnitude integers and length-prefixed UTF-8, big-endian.

        BLAKE2b uses an 8-byte digest and the v1 personalization shown below.
        There is no normalization of names and no delimiter ambiguity.
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
        return cls(key, state)

    def stream(self, name: str) -> Prng:
        """Derive a name/path under the base key, independent of every cursor."""
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
        """Return a + (b-a)*random(), including reversed bounds and rounding."""
        return a + (b - a) * self.random()

    def _randbelow(self, n: int) -> int:
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
