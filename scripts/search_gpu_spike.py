#!/usr/bin/env python3
"""Optional MLX CPU/Metal batch-scoring crossover spike.

Uses an UNTRAINED neural scoring kernel. It measures device overhead and
numerical agreement, not compression quality or end-to-end search speed.
Install MLX separately in a research environment; core runtime deps stay empty.
"""
import argparse
import importlib.metadata
import hashlib
import json
import math
import os
import pathlib
import platform
import statistics
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batches", default="16,256,4096,65536")
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--precision", choices=["strict", "reduced"], default="strict")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "target/search/gpu-spike.json")
    args = parser.parse_args()
    batches = [int(n) for n in args.batches.split(",")]
    if args.rounds < 3 or not batches or min(batches) < 1:
        parser.error("positive batch sizes and at least three rounds required")
    # Set before MLX import/first kernel. On M5, float32 storage alone does
    # not imply full-precision matrix multiplication. See MLX precision docs.
    os.environ["MLX_ENABLE_TF32"] = "0" if args.precision == "strict" else "1"
    try:
        import mlx.core as mx
    except ImportError:
        raise SystemExit("optional spike requires MLX on Apple silicon; see docs/autotuning-investigation.md") from None
    if not mx.metal.is_available():
        raise SystemExit("Metal GPU unavailable; do not report a GPU measurement")
    with mx.stream(mx.cpu):
        mx.random.seed(195107)
        w1 = mx.random.normal((24, 128), dtype=mx.float32) / 24 ** 0.5
        b1 = mx.random.normal((128,), dtype=mx.float32)
        w2 = mx.random.normal((128, 12), dtype=mx.float32) / 128 ** 0.5
        mx.eval(w1, b1, w2)
    rows = []
    for batch in batches:
        with mx.stream(mx.cpu):
            x = mx.random.normal((batch, 24), dtype=mx.float32)
            mx.eval(x)

        def score(device):
            with mx.stream(device):
                hidden = mx.maximum(x @ w1 + b1, 0)
                # Four ensemble members, three hypothetical objective axes.
                y = (hidden @ w2).reshape(batch, 4, 3).mean(axis=1)
                order = mx.argsort(y.mean(axis=1))[:min(32, batch)]
                mx.eval(y, order)
            mx.synchronize(device)
            return y, order

        results = {}
        for device in (mx.cpu, mx.gpu):
            score(device)
            results[str(device)] = score(device)
        cpu, cpu_order = results[str(mx.cpu)]
        gpu, gpu_order = results[str(mx.gpu)]
        with mx.stream(mx.cpu):
            error = float((mx.abs(cpu - gpu) / (1 + mx.abs(cpu))).max().item())
        tolerance = 1e-4 if args.precision == "strict" else 1e-2
        if not math.isfinite(error) or error > tolerance:
            raise SystemExit(f"CPU/GPU disagreement at batch {batch}: {error}")
        cpu_ranks, gpu_ranks = cpu_order.tolist(), gpu_order.tolist()
        overlap = len(set(cpu_ranks) & set(gpu_ranks)) / min(32, batch)
        timings = {"cpu": [], "gpu": []}
        for round_index in range(args.rounds):
            order = [("cpu", mx.cpu), ("gpu", mx.gpu)]
            if round_index % 2:
                order.reverse()
            for name, device in order:
                start = time.perf_counter_ns()
                score(device)
                timings[name].append(time.perf_counter_ns() - start)
        cpu_ns, gpu_ns = (statistics.median(timings[k]) for k in ("cpu", "gpu"))
        rows.append({"batch": batch, "samples_ns": timings,
                     "cpu_median_ns": cpu_ns, "gpu_median_ns": gpu_ns,
                     "gpu_speedup": cpu_ns / gpu_ns, "max_scaled_error": error,
                     "top32_overlap": overlap,
                     "top32_order_agreement": sum(a == b for a, b in zip(cpu_ranks, gpu_ranks)) / len(cpu_ranks),
                     "top1_agreement": cpu_ranks[0] == gpu_ranks[0]})
    report = {"schema_version": 1, "purpose": "untrained kernel crossover; not an optimizer or compression benchmark",
              "mlx_version": importlib.metadata.version("mlx"), "platform": platform.platform(),
              "source_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
              "device": mx.device_info(), "dtype": "float32", "seed": 195107,
              "precision": args.precision, "MLX_ENABLE_TF32": os.environ["MLX_ENABLE_TF32"],
              "max_scaled_error_tolerance": tolerance,
              "input_axes": 24, "hidden_width": 128, "ensemble_members": 4,
              "objective_axes": 3, "rounds": args.rounds,
              "timing": "materialized float32 inputs/weights; two warmups; rotated CPU/GPU; includes scoring and top32 sort; eval and synchronize before stopping clock; excludes model fitting and input generation",
              "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.out), "batches": [
        {"batch": r["batch"], "gpu_speedup": round(r["gpu_speedup"], 2),
         "top32_overlap": r["top32_overlap"]} for r in rows]}))


if __name__ == "__main__":
    main()
