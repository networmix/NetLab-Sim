"""Fresh-process old/new/old LPM latency and 2,000-device convergence memory.

Run from the repository root with its venv interpreter:
  python -m benchmarks.s0_w2_scale --baseline 0e5b299 --output /tmp/s0-w2.json
Run only after other benchmarks/checks have finished. The process snapshots in
the JSON are evidence to inspect, not an automatic guarantee of a quiet host.
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import os
import random
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


def lookup():
    from ngraph_sim.model.lpm import PrefixTable

    results = {}
    for bits in (32, 128):
        for shape in ('host', 'mixed', 'miss'):
            rng = random.Random(314159 + bits)
            lengths = (
                [bits]
                if shape == 'host'
                else ([8, 16, 24, 32] if bits == 32 else [32, 48, 64, 128])
            )
            builder = PrefixTable(bits)
            entries = []
            for _ in range(1024):
                plen = rng.choice(lengths)
                shift = bits - plen
                # Only the lower half of the address space is populated.
                net = (rng.getrandbits(bits - 1) >> shift) << shift
                builder.insert(net, plen, 1)
                entries.append((net, shift))
            if shape == 'mixed':
                builder.insert(0, 0, 1)
            table = builder.freeze()
            addresses = []
            for index in range(1024):
                net, shift = entries[index]
                address = net | rng.getrandbits(shift)
                if shape == 'miss' or (shape == 'mixed' and index % 2):
                    address = rng.getrandbits(bits - 1) | (1 << (bits - 1))
                addresses.append(address)
            for method in ('lookup', 'lookup_iter'):
                call = getattr(table, method)

                def batch(call=call, addresses=addresses, method=method):
                    hits = 0
                    for _ in range(128):
                        for address in addresses:
                            if method == 'lookup':
                                hits += call(address) is not None
                            else:
                                hits += len(tuple(call(address)))
                    return hits

                batch()  # adaptive interpreter/cache warmup, outside samples
                samples = []
                hits = 0
                gc.disable()
                try:
                    for _ in range(9):
                        start = time.perf_counter_ns()
                        hits = batch()
                        samples.append((time.perf_counter_ns() - start) / 131072)
                finally:
                    gc.enable()
                results[f'ipv{4 if bits == 32 else 6}/{shape}/{method}'] = {
                    'median_ns': statistics.median(samples),
                    'samples_ns': samples,
                    'matches': hits,
                    'prefixes': len(table),
                    'lengths': table.lengths(),
                }
    return results


def converge():
    import tracemalloc

    from ngraph_sim.model.network import Network

    count = 2000
    net = Network(seed=1)
    devices = []
    with net.batch():
        for index in range(count):
            dev = net.add_device(f'd{index}')
            devices.append(dev)
            dev.add_loopback('lo0', ipv4=[f'10.0.{index >> 8}.{index & 255}/32'])
        for index in range(count - 1):
            net.add_p2p(devices[index], 'e1', devices[index + 1], 'e0', unnumbered=True)
    gc.collect()
    tracemalloc.start(25)
    before = tracemalloc.take_snapshot()
    net.converge()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    diff = after.compare_to(before, 'lineno')
    retained = sum(item.size_diff for item in diff)
    device = net.state.devices['d5']
    return {
        'devices': count,
        'retained_bytes': retained,
        'bytes_per_device': retained / count,
        'top_allocations': [str(item) for item in diff[:14]],
        'ribs': {int(af): len(rib) for af, rib in device.ribs.items()},
        'fibs': {int(af): len(fib.entries) for af, fib in device.fibs.items()},
    }


def processes():
    rows = subprocess.check_output(
        ['ps', '-Ao', 'pid,pcpu,etime,comm'], text=True
    ).splitlines()
    return sorted(rows[1:], key=lambda row: float(row.split()[1]), reverse=True)[:12]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='0e5b299')
    parser.add_argument('--output', type=Path)
    parser.add_argument(
        '--cases',
        nargs='+',
        choices=('lookup', 'converge'),
        default=('lookup', 'converge'),
    )
    parser.add_argument('--source', type=Path)
    parser.add_argument('--case', choices=('lookup', 'converge'))
    args = parser.parse_args()
    if args.case:
        assert args.source is not None
        sys.path.insert(0, str(args.source))
        # No NetGraph-Sim import is allowed before selecting the source snapshot.
        data = lookup() if args.case == 'lookup' else converge()
        import ngraph_sim

        print(json.dumps({'source': ngraph_sim.__file__, 'data': data}))
        return
    assert args.output is not None, '--output is required for the comparison'
    repo = Path(__file__).resolve().parents[1]
    baseline = subprocess.check_output(
        ['git', 'rev-parse', args.baseline], cwd=repo, text=True
    ).strip()
    archive = subprocess.check_output(
        ['git', 'archive', '--format=tar', baseline, 'ngraph_sim'], cwd=repo
    )
    result: dict[str, object] = {'baseline': baseline, 'python': sys.version}
    runs = []
    result['runs'] = runs
    with tempfile.TemporaryDirectory(prefix='ngraph-sim-s0-w2-') as temporary:
        old = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(old, filter='data')
        for case in args.cases:
            for label, path in (('old-1', old), ('new', repo), ('old-2', old)):
                print(f'{case} {label}', flush=True)
                before = processes()
                uptime_before = subprocess.check_output(['uptime'], text=True).strip()
                data = subprocess.check_output(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        '--source',
                        str(path),
                        '--case',
                        case,
                    ],
                    cwd=path,
                    env={**os.environ, 'PYTHONHASHSEED': '0'},
                    text=True,
                )
                runs.append(
                    {
                        'case': case,
                        'label': label,
                        'uptime_before': uptime_before,
                        'uptime_after': subprocess.check_output(
                            ['uptime'], text=True
                        ).strip(),
                        'processes_before': before,
                        'processes_after': processes(),
                        **json.loads(data),
                    }
                )
                args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
