"""Longest-prefix-match table.

A dict per prefix length plus a descending tuple of populated lengths.
``lookup`` truncates the address for each populated length and probes, so the
cost is O(k) dict probes with k = number of distinct lengths present
(typically 3 to 6), and insert/remove are O(1). Shift arithmetic avoids
per-table mask storage and shared hot-path mask objects (free-threading
rule from ``AGENTS.md``).

``PrefixTable`` is the mutable builder; ``freeze()`` returns a
``FrozenPrefixTable`` with the same lookups and no mutators, which is what
the state tree stores.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Generic, Iterator, Mapping, TypeVar

V = TypeVar('V')

PrefixKey = tuple[int, int]
"""``(network_int, prefix_len)``."""


class FrozenPrefixTable(Generic[V]):
    """Read-only LPM table."""

    __slots__ = ('_bits', '_tables', '_lengths', '_probes', '_count')

    def __init__(self, bits: int, tables: dict[int, dict[int, V]]) -> None:
        # Public construction copies: a frozen table never aliases caller
        # dicts, and keys are exact ints (never a caller's int subclass);
        # empty shards are dropped so no key survives without an entry.
        self._init(
            bits,
            {
                int(plen): {int(net): value for net, value in t.items()}
                for plen, t in tables.items()
                if t
            },
        )

    def _init(
        self,
        bits: int,
        tables: dict[int, Mapping[int, V]],
    ) -> None:
        if type(bits) is not int:
            bits = int(bits)  # exact metadata, never a caller's int subclass
        if bits not in (32, 128):
            raise ValueError('bits must be 32 or 128')
        self._bits = bits
        self._tables = tables
        self._index_lengths()
        self._count = sum(len(t) for t in tables.values())

    def _index_lengths(self) -> None:
        self._lengths: tuple[int, ...] = tuple(sorted(self._tables, reverse=True))
        # Only populated lengths need probe metadata. Bind each shift and shard
        # once, avoiding an outer dict probe and subtraction per lookup step.
        self._probes = tuple(
            (plen, self._bits - plen, self._tables[plen]) for plen in self._lengths
        )

    @classmethod
    def _owned(
        cls,
        bits: int,
        tables: dict[int, Mapping[int, V]],
    ) -> FrozenPrefixTable[V]:
        """Own fresh dicts, or share immutable PMaps for incremental RIB edits.

        ``freeze`` has already copied the mutable builder's dicts.
        """
        self = cls.__new__(cls)
        self._init(bits, tables)
        return self

    @property
    def bits(self) -> int:
        return self._bits

    def shards(self) -> Mapping[int, Mapping[int, V]]:
        """Read-only view of the per-length tables (network int → value);
        the inner tables are wrapped too, so nothing reachable is writable."""
        return MappingProxyType(
            {k: MappingProxyType(v) for k, v in self._tables.items()}
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenPrefixTable):
            if self._bits != other._bits:
                return False
            if self._tables == other._tables:
                return True
            if self._tables.keys() != other._tables.keys():
                return False
            for plen, table in self._tables.items():
                peer = other._tables[plen]
                if table is peer or table == peer:
                    continue
                # PMap deliberately only compares equal to another PMap.
                # Prefix tables compare by content even across storage layouts.
                if isinstance(table, dict) == isinstance(peer, dict):
                    return False
                if len(table) != len(peer) or any(
                    net not in peer or value != peer[net]
                    for net, value in table.items()
                ):
                    return False
            return True
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __len__(self) -> int:
        return self._count

    def __contains__(self, key: PrefixKey) -> bool:
        net, plen = key
        table = self._tables.get(plen)
        return table is not None and net in table

    def get(self, net: int, plen: int, default: Any = None) -> V | Any:
        table = self._tables.get(plen)
        if table is None:
            return default
        return table.get(net, default)

    def lookup_iter(
        self,
        addr: int,
        *,
        exclude: Callable[[int, int], bool] | None = None,
        min_len: int = 0,
    ) -> Iterator[tuple[int, int, V]]:
        """Matching prefixes from longest to shortest.

        ``exclude(net, plen)`` skips a match (used by the resolver's gray
        stack); ``min_len`` stops the walk before shorter prefixes (used to
        refuse resolution via a default route).
        """
        bits = self._bits
        if addr >> bits:
            addr %= 1 << bits  # preserve low-bit lookup for out-of-range integers
        for plen, shift, table in self._probes:
            if plen < min_len:
                break
            net = (addr >> shift) << shift if shift else addr
            if net in table:
                if exclude is not None and exclude(net, plen):
                    continue
                yield net, plen, table[net]

    def lookup(
        self,
        addr: int,
        *,
        exclude: Callable[[int, int], bool] | None = None,
        min_len: int = 0,
    ) -> tuple[int, int, V] | None:
        # Probe directly: constructing and closing an iterator for one result
        # would outweigh the arithmetic work for short tables.
        bits = self._bits
        if addr >> bits:
            addr %= 1 << bits
        for plen, shift, table in self._probes:
            if plen < min_len:
                break
            net = (addr >> shift) << shift if shift else addr
            if net in table:
                if exclude is not None and exclude(net, plen):
                    continue
                return net, plen, table[net]
        return None

    def items(self) -> list[tuple[int, int, V]]:
        """All entries sorted by ``(network_int, prefix_len)``."""
        out = [
            (net, plen, v)
            for plen, table in self._tables.items()
            for net, v in table.items()
        ]
        out.sort(key=lambda e: (e[0], e[1]))
        return out

    def lengths(self) -> tuple[int, ...]:
        return self._lengths


class PrefixTable(FrozenPrefixTable[V]):
    """Mutable LPM table; ``freeze()`` snapshots it."""

    __slots__ = ()

    def __init__(self, bits: int) -> None:
        if bits not in (32, 128):
            raise ValueError('bits must be 32 or 128')
        super().__init__(bits, {})

    def insert(self, net: int, plen: int, value: V) -> None:
        if type(net) is not int or type(plen) is not int:
            net, plen = int(net), int(plen)  # keys are exact ints, never subclasses
        if not 0 <= plen <= self._bits:
            raise ValueError(f'prefix length {plen} out of range')
        shift = self._bits - plen
        if net < 0 or net >> self._bits or (net >> shift) << shift != net:
            raise ValueError(f'host bits set in {net:#x}/{plen}')
        table = self._tables.get(plen)
        if table is None:
            table = self._tables[plen] = {}
            self._index_lengths()
        assert isinstance(table, dict)  # mutable builders never own persistent shards
        if net not in table:
            self._count += 1
        table[net] = value

    def remove(self, net: int, plen: int) -> V:
        table = self._tables.get(plen)
        if table is None or net not in table:
            raise KeyError((net, plen))
        assert isinstance(table, dict)
        value = table.pop(net)
        self._count -= 1
        if not table:
            del self._tables[plen]
            self._index_lengths()
        return value

    def freeze(self) -> FrozenPrefixTable[V]:
        return FrozenPrefixTable._owned(
            self._bits, {plen: dict(t) for plen, t in self._tables.items()}
        )
