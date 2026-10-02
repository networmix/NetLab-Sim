"""Tests for Timeout events."""

import pytest

import ngraph_sim


class TestTimeoutBasic:
    def test_basic_delay(self):
        env = ngraph_sim.Environment()
        evt = env.timeout(5)
        env.run()
        assert env.now == 5
        assert evt.processed

    def test_timeout_value(self):
        env = ngraph_sim.Environment()

        def proc(env):
            val = yield env.timeout(3, value='result')
            assert val == 'result'

        env.process(proc(env))
        env.run()
        assert env.now == 3

    def test_zero_delay(self):
        env = ngraph_sim.Environment()
        evt = env.timeout(0)
        env.run()
        assert env.now == 0
        assert evt.processed
        assert evt.ok

    def test_negative_delay_raises(self):
        env = ngraph_sim.Environment()
        with pytest.raises(ValueError, match='non-negative'):
            env.timeout(-1)

    def test_nan_delay_raises(self):
        """NaN compares false with everything and would corrupt heap order."""
        env = ngraph_sim.Environment()
        with pytest.raises(ValueError, match='non-negative'):
            env.timeout(float('nan'))

    def test_infinite_delay_is_allowed(self):
        env = ngraph_sim.Environment()
        evt = env.timeout(ngraph_sim.Infinity)
        assert env.peek() == ngraph_sim.Infinity
        assert not evt.processed

    def test_timeout_default_value_is_none(self):
        env = ngraph_sim.Environment()

        def proc(env):
            val = yield env.timeout(1)
            assert val is None

        env.process(proc(env))
        env.run()

    def test_multiple_timeouts_ordering(self):
        env = ngraph_sim.Environment()
        order = []

        def p1(env):
            yield env.timeout(5)
            order.append('p1')

        def p2(env):
            yield env.timeout(3)
            order.append('p2')

        env.process(p1(env))
        env.process(p2(env))
        env.run()
        assert order == ['p2', 'p1']
