"""S0: empty prefix tables allocate no per-table mask arrays."""

import gc
import tracemalloc

import pytest

from netsim.model.lpm import PrefixTable


@pytest.mark.parametrize('bits', [32, 128])
@pytest.mark.parametrize('frozen', [False, True])
def test_empty_tables_have_no_per_table_mask_allocation(bits, frozen):
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        tables = [
            PrefixTable(bits).freeze() if frozen else PrefixTable(bits)
            for _ in range(1000)
        ]
        retained = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    print(f'{bits=}, {frozen=}, tables={len(tables)}, retained_bytes={retained}')
    # Generous allowance for table instances, dicts and the outer list, but
    # not 33/129 mask integers and their tuple per table.
    assert retained < 1_000_000
    assert all(not hasattr(table, '_masks') for table in tables)


@pytest.mark.parametrize('bits', [32, 128])
def test_shift_arithmetic_preserves_integer_address_and_key_boundaries(bits):
    table = PrefixTable(bits)
    table.insert(0, 0, 'default')
    table.insert(0, bits, None)
    table.insert((1 << bits) - 1, bits, 'last')
    for addr in (0, 1, (1 << bits) - 1, 1 << bits, -1, -(1 << bits)):
        # Integers outside the address range match on their low address bits.
        canonical = addr % (1 << bits)
        assert table.lookup(addr) == table.lookup(canonical)
        assert list(table.lookup_iter(addr)) == list(table.lookup_iter(canonical))
    assert table.lookup(0) == (0, bits, None)
    assert table.lookup(0, exclude=lambda n, p: p == bits) == (0, 0, 'default')
    assert table.lookup(1, min_len=1) is None
    for net, plen in ((-1, bits), (1 << bits, bits), (1, 0), (1, bits - 1)):
        with pytest.raises(ValueError, match='host bits'):
            table.insert(net, plen, 'invalid')
