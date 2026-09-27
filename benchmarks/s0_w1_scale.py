"""S0 W1 old/new/old benchmark; run sequentially on an otherwise idle machine.

    PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale --baseline 0e5b299
    PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale
    PYTHONHASHSEED=0 venv/bin/python -m benchmarks.s0_w1_scale --baseline 0e5b299

Baseline mode reads the exact network module and consumer_index function from
Git into this process before building anything; it does not change the checkout.
This isolates the two W1 changes; other modules must match the baseline revision.
Build matches build_phases.py's topology. Tracing is off unless --tracemalloc is
given. Consumer timings isolate the helper with synthetic index-only headends,
as in the review probe; they are not complete SRv6 topology/commit timings.
"""

from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from dataclasses import replace

from netsim.model import network as nw
from netsim.model import srv6


def load_baseline(revision: str) -> str:
    commit = subprocess.check_output(['git', 'rev-parse', revision], text=True).strip()
    source = subprocess.check_output(
        ['git', 'show', f'{commit}:netsim/model/network.py'], text=True
    )
    exec(compile(source, f'{commit}:netsim/model/network.py', 'exec'), nw.__dict__)
    source = subprocess.check_output(
        ['git', 'show', f'{commit}:netsim/model/srv6.py'], text=True
    )
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == 'consumer_index'
    )
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, f'{commit}:netsim/model/srv6.py', 'exec'), srv6.__dict__)
    return commit


def emit(**fields):
    print(json.dumps(fields, sort_keys=True), flush=True)


def build(size: int, trace: bool):
    net = nw.Network(seed=1)
    devices = []
    gc.collect()
    if trace:
        tracemalloc.start()
    started, cpu_started = time.perf_counter(), time.process_time()
    with net.batch():
        for i in range(size):
            dev = net.add_device(f'd{i}')
            devices.append(dev)
            dev.add_loopback(
                'lo0', ipv4=[f'10.{(i >> 16) & 255}.{(i >> 8) & 255}.{i & 255}/32']
            )
        for i in range(size - 1):
            net.add_p2p(devices[i], 'e1', devices[i + 1], 'e0', unnumbered=True)
    elapsed, cpu = time.perf_counter() - started, time.process_time() - cpu_started
    retained = tracemalloc.get_traced_memory()[0] if trace else None
    if trace:
        tracemalloc.stop()
    # Exact ordered model records, including interfaces, epochs and allocators.
    # Excludes private validation bookkeeping that cannot affect model output.
    root = net.state
    fingerprint = hashlib.sha256(
        repr(
            (root.devices.sorted_items(), root.links.sorted_items(), root.allocators)
        ).encode()
    ).hexdigest()
    assert len(root.devices) == size and len(root.links) == size - 1
    emit(
        phase='build',
        devices=size,
        links=size - 1,
        seconds=elapsed,
        cpu_seconds=cpu,
        us_per_device=elapsed / size * 1e6,
        retained_bytes_per_device=retained / size if retained is not None else None,
        sha256=fingerprint,
    )


def consumers(count: int):
    net = nw.Network()
    net.add_device('spare')
    old = replace(net.state, srv6_consumers=frozenset(f'h{i}' for i in range(count)))
    dev = old.devices['spare']
    new = replace(
        old,
        devices=old.devices.set(
            'spare', replace(dev, config=replace(dev.config, enabled=False))
        ),
    )
    repeats = 10000 if count == 0 else 1000 if count <= 10000 else 100
    for _ in range(10):
        assert srv6.consumer_index(old, new) is old.srv6_consumers
    samples = []
    cpu_samples = []
    result = old.srv6_consumers
    for _ in range(7):
        gc.collect()
        gc.disable()
        start, cpu_start = time.perf_counter(), time.process_time()
        try:
            for _ in range(repeats):
                result = srv6.consumer_index(old, new)
        finally:
            samples.append((time.perf_counter() - start) / repeats * 1e6)
            cpu_samples.append((time.process_time() - cpu_start) / repeats * 1e6)
            gc.enable()
        assert result is old.srv6_consumers
    emit(
        phase='consumer_index',
        consumers=count,
        calls_per_sample=repeats,
        median_us=statistics.median(samples),
        median_cpu_us=statistics.median(cpu_samples),
        samples_us=samples,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', help='Git revision to load before timing')
    parser.add_argument('--tracemalloc', action='store_true')
    parser.add_argument('--sizes', type=int, nargs='+', default=[2000, 8000])
    parser.add_argument('--consumers', type=int, nargs='+', default=[0, 10000, 100000])
    args = parser.parse_args()
    baseline = load_baseline(args.baseline) if args.baseline else None
    emit(
        phase='environment',
        baseline=baseline,
        python=sys.version,
        platform=platform.platform(),
        processor=platform.processor(),
        hash_seed=os.environ.get('PYTHONHASHSEED'),
        tracemalloc=args.tracemalloc,
    )
    for size in args.sizes:
        build(size, args.tracemalloc)
    for count in args.consumers:
        consumers(count)


if __name__ == '__main__':
    main()
