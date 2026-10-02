"""S0: bounded locator validation and unchanged consumer-index work."""

from contextlib import nullcontext
from dataclasses import replace

import pytest

from ngraph_sim.model import network as nw
from ngraph_sim.model import srv6
from ngraph_sim.model.contracts import STATIC
from ngraph_sim.model.state import PMap, validate_immutable


@pytest.mark.parametrize('ipv6', [False, True])
@pytest.mark.parametrize('locators', [0, 3])
def test_build_interface_validation_has_linear_operation_count(
    monkeypatch, ipv6, locators
):
    original = nw._MapEdit.items
    original_contains = srv6.contains
    visits = 0
    contains_calls = 0

    def counted(mapping):
        nonlocal visits
        for item in original(mapping):
            visits += 1
            yield item

    def contains(prefix, address):
        nonlocal contains_calls
        contains_calls += 1
        return original_contains(prefix, address)

    monkeypatch.setattr(nw._MapEdit, 'items', counted)
    monkeypatch.setattr(srv6, 'contains', contains)
    counts = []
    for size in (64, 128):
        net = nw.Network()
        for i in range(locators):
            net.add_device(f'sr{i}').add_locator(
                'sr', prefix=f'2001:db8:{i + 1:x}::/64'
            )
        visits = 0
        contains_calls = 0
        with net.batch():
            devices = []
            for i in range(size):
                dev = net.add_device(f'd{i}')
                devices.append(dev)
                addresses = (
                    {'ipv6': [f'2001:db8:ffff::{i + 1:x}/128']}
                    if ipv6
                    else {'ipv4': [f'10.0.0.{i + 1}/32']}
                )
                dev.add_loopback('lo', **addresses)
            for a, b in zip(devices, devices[1:], strict=False):
                net.add_p2p(a, 'right', b, 'left', unnumbered=True)
        counts.append(visits)
        assert contains_calls == (locators * size if ipv6 else 0)
    assert counts[1] <= 2 * counts[0] + 8, counts
    assert counts[1] <= 8 * 128, counts


@pytest.mark.parametrize('batched', [False, True])
@pytest.mark.parametrize('classic', [False, True])
def test_locator_rejects_interface_add_and_reconfigure(batched, classic):
    net = nw.Network()
    owner = net.add_device('owner')
    peer = net.add_device('peer')
    with net.batch() if batched else nullcontext():
        if classic:
            owner.add_locator('sr', prefix='2001:db8:1::/64')
            conflict = '2001:db8:1::abcd/128'
        else:
            owner.add_locator('sr', structure=srv6.F3216_GIB)
            # Outside the owner's /48, but inside its reserved /32 block.
            conflict = '5f00:0:ffff::abcd/128'
        for dev in (owner, peer):
            before = net.state
            with pytest.raises(ValueError, match='locator block on owner'):
                dev.add_loopback('bad', ipv6=[conflict])
            assert net.state == before
            port = dev.add_loopback('good', ipv6=['2001:db8:ffff::1/128'])
            before = net.state
            with pytest.raises(ValueError, match='locator block on owner'):
                port.configure(ipv6=[conflict])
            assert net.state == before
    validate_immutable(net.state)
    assert net.validate() == []


@pytest.mark.parametrize('batched', [False, True])
def test_adding_locator_over_existing_interface_is_atomic(batched):
    net = nw.Network()
    owner = net.add_device('owner')
    peer = net.add_device('peer')
    with net.batch() if batched else nullcontext():
        peer.add_loopback('lo', ipv6=['5f00:0:ffff::1/128'])
        before = net.state
        with pytest.raises(ValueError, match='locator block covers interface'):
            owner.add_locator('sr', structure=srv6.F3216_GIB)
        assert net.state == before
        peer.add_loopback('still-free', ipv6=['5f00:0:ffff::2/128'])


def set_locators(net, device, locators):
    def update(state):
        dev = state.devices[device]
        db = replace(dev.srv6_sids, locators=locators)
        return replace(
            state, devices=state.devices.set(device, replace(dev, srv6_sids=db))
        )

    net.update(update)


@pytest.mark.parametrize('batched', [False, True])
@pytest.mark.parametrize(
    'operation', ['remove_locator', 'remove_device', 'replace_locator']
)
def test_locator_removal_and_replacement_update_validation(batched, operation):
    net = nw.Network()
    owner = net.add_device('owner')
    peer = net.add_device('peer')
    loc = owner.add_locator('sr', prefix='2001:db8:1::/64')
    with net.batch() if batched else nullcontext():
        if operation == 'remove_device':
            net.remove_device('owner')
        elif operation == 'remove_locator':
            set_locators(net, 'owner', PMap())
        else:
            prefix = srv6.prefix6('2001:db8:2::/64')
            block = srv6.prefix6('2001:db8:2::/48')
            set_locators(
                net, 'owner', PMap({'sr': replace(loc, prefix=prefix, block=block)})
            )
            with pytest.raises(ValueError, match='locator block on owner'):
                peer.add_loopback('bad', ipv6=['2001:db8:2::1/128'])
        peer.add_loopback('released', ipv6=['2001:db8:1::1/128'])
    assert net.validate() == []


@pytest.mark.parametrize('remove', [False, True])
def test_locator_index_batch_rollback_and_staged_fork(remove):
    net = nw.Network()
    owner = net.add_device('owner')
    net.add_device('peer')
    if remove:
        owner.add_locator('sr', structure=srv6.F3216_GIB)
    before = net.state
    with pytest.raises(RuntimeError, match='abort'):
        with net.batch():
            if remove:
                set_locators(net, 'owner', PMap())
            else:
                owner.add_locator('sr', structure=srv6.F3216_GIB)
            staged = net.state
            fork = net.fork()
            assert fork.state is staged
            raise RuntimeError('abort')
    assert net.state is before
    blocked, free = (net, fork) if remove else (fork, net)
    with pytest.raises(ValueError, match='locator block on owner'):
        blocked['peer'].add_loopback('lo', ipv6=['5f00:0:ffff::1/128'])
    free['peer'].add_loopback('lo', ipv6=['5f00:0:ffff::1/128'])


@pytest.mark.parametrize('batched', [False, True])
def test_locator_index_old_root_restore_and_observer_failure(batched):
    net = nw.Network()
    owner = net.add_device('owner')
    net.add_device('peer')
    before = net.state

    def fail(*args):
        raise RuntimeError('published')

    net.on_delta.append(fail)
    with pytest.raises(RuntimeError, match='published'):
        with net.batch() if batched else nullcontext():
            owner.add_locator('sr', structure=srv6.F3216_GIB)
    net.on_delta.clear()
    with pytest.raises(ValueError, match='locator block on owner'):
        net['peer'].add_loopback('bad', ipv6=['5f00:0:ffff::1/128'])
    fork = net.fork()
    net.update(lambda _: before)
    net['peer'].add_loopback('free', ipv6=['5f00:0:ffff::1/128'])
    with pytest.raises(ValueError, match='locator block on owner'):
        fork['peer'].add_loopback('bad', ipv6=['5f00:0:ffff::1/128'])


def test_locator_index_failed_outer_commit_is_discarded(monkeypatch):
    net = nw.Network()
    owner = net.add_device('owner')
    peer = net.add_device('peer')
    before = net.state
    net.debug_validate = True

    def reject(candidate):
        raise RuntimeError('admission')

    with monkeypatch.context() as patch:
        patch.setattr(nw, 'validate_immutable', reject)
        with pytest.raises(RuntimeError, match='admission'):
            with net.batch():
                owner.add_locator('sr', structure=srv6.F3216_GIB)
    assert net.state is before
    peer.add_loopback('free', ipv6=['5f00:0:ffff::1/128'])


def test_locator_index_tracks_arbitrary_root_replacement_and_empty_sid_db():
    source = nw.Network()
    source.add_device('owner').add_locator('sr', structure=srv6.F3216_GIB)
    net = nw.Network()
    net.update(lambda _: source.state)
    with pytest.raises(ValueError, match='locator block on owner'):
        net['owner'].add_loopback('bad', ipv6=['5f00:0:ffff::1/128'])
    net.update(
        lambda state: replace(
            state,
            devices=state.devices.set(
                'owner', replace(state.devices['owner'], srv6_sids=None)
            ),
        )
    )
    net['owner'].add_loopback('free', ipv6=['5f00:0:ffff::1/128'])


@pytest.mark.parametrize('count', [0, 8])
def test_unrelated_commit_keeps_consumer_identity_without_copy(monkeypatch, count):
    net = nw.Network()
    for i in range(count):
        net.add_device(f'h{i}').policy_client().add(srv6.SrPolicy(STATIC, 1, 1))
    spare = net.add_device('spare')
    consumers = net.state.srv6_consumers
    copies = 0

    def counted_set(values=()):
        nonlocal copies
        if values is consumers:
            copies += 1
        return set(values)

    monkeypatch.setattr(srv6, 'set', counted_set, raising=False)
    spare.add_loopback('lo', ipv4=['192.0.2.1/32'])
    assert net.state.srv6_consumers is consumers
    assert copies == 0


def test_consumer_index_membership_add_remove_and_retained_headend():
    net = nw.Network()
    a, b = net.add_device('a'), net.add_device('b')
    policy = srv6.SrPolicy(STATIC, 1, 1)
    a.policy_client().add(policy)
    first = net.state.srv6_consumers
    assert first == frozenset({'a'})
    a.policy_client().add(replace(policy, color=2))
    a.policy_client().delete(policy.key)
    assert net.state.srv6_consumers is first
    with net.batch():
        b.policy_client().add(policy)
        net.remove_device('a')
    assert net.state.srv6_consumers == frozenset({'b'})
    b.policy_client().delete(policy.key)
    assert net.state.srv6_consumers == frozenset()
