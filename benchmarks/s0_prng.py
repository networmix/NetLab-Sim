"""Idle agent runs: 500 agents x 5 ticks, timed without tracemalloc.

Retention is measured in a separate run. Run fresh processes in sequence:
--runtime-ref BASE, current, --runtime-ref BASE. Only agents.py is loaded from
BASE and the checkout is untouched, so the comparison holds only where all
other runtime and model files match BASE, as on s0/prng. History is explicitly
unbounded, so timeline eviction cannot hide retained PRNG state.
"""

import argparse
import gc
import json
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ngraph_sim import Environment  # noqa: E402
from ngraph_sim.model import contracts as c  # noqa: E402
from ngraph_sim.model.network import Network  # noqa: E402
from ngraph_sim.runtime import simulation  # noqa: E402


class Ticker:
    client = c.ClientId('tick')
    config = c.AgentConfig()
    profile = c.ClientProfile(client, 250)

    def subscriptions(self):
        return ()

    def on_init(self, ctx):
        return self.on_run(ctx)

    def on_run(self, ctx):
        return c.AgentOutput(state=ctx.agent_state, timers=(c.TimerOp('t', 1.0),))


def build(count):
    net = Network(seed=1)
    with net.batch():
        for i in range(count):
            device = net.add_device(f'd{i}')
            device.add_loopback('lo0', ipv4=[f'10.0.{i >> 8}.{i & 255}/32'])
            net.add_agent(device.name, Ticker())
    sim = simulation.Simulation(
        Environment(), net, keep_roots=None, keep_records=None, keep_events=None
    )
    sim.run_until(1.5)
    return sim


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-ref')
    parser.add_argument('--label', default='current')
    parser.add_argument('--agents', type=int, default=500)
    parser.add_argument('--ticks', type=int, default=5)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if args.runtime_ref:
        source = subprocess.check_output(
            ['git', 'show', f'{args.runtime_ref}:netsim/runtime/agents.py'], text=True
        )
        module = types.ModuleType('ngraph_sim.runtime._s0_benchmark_agents')
        sys.modules[module.__name__] = module
        exec(compile(source, f'{args.runtime_ref}:agents.py', 'exec'), module.__dict__)
        simulation.AgentRuntime = module.AgentRuntime

    runs = args.agents * args.ticks
    samples = []
    for _ in range(args.repeats):
        sim = build(args.agents)
        gc.collect()
        start = time.perf_counter()
        sim.run_until(1.5 + args.ticks)
        samples.append((time.perf_counter() - start) * 1e6 / runs)
        del sim
        gc.collect()

    sim = build(args.agents)
    gc.collect()
    tracemalloc.start(10)
    before = tracemalloc.take_snapshot()
    sim.run_until(1.5 + args.ticks)
    gc.collect()
    after = tracemalloc.take_snapshot()
    diffs = after.compare_to(before, 'lineno')
    retained = sum(diff.size_diff for diff in diffs)
    tracemalloc.stop()
    print(
        json.dumps(
            {
                'label': args.label,
                'runtime_ref': args.runtime_ref,
                'python': platform.python_version(),
                'gil': getattr(sys, '_is_gil_enabled', lambda: True)(),
                'machine': platform.platform(),
                'agents': args.agents,
                'ticks': args.ticks,
                'runs': runs,
                'median_us_per_run': statistics.median(samples),
                'samples_us_per_run': samples,
                'retained_bytes': retained,
                'bytes_per_run': retained / runs,
                'timeline_records': len(sim.timeline.records),
                'largest_allocations': [
                    {
                        'site': str(diff.traceback[0]),
                        'bytes': diff.size_diff,
                        'objects': diff.count_diff,
                    }
                    for diff in diffs[:8]
                ],
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
