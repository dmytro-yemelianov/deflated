#!/usr/bin/env python3
"""G0 Rust worker/framing/timer contracts, using shared correctness fixtures.

No measurements on study train/validation/holdout data. Published packets and
the sealed b7 worker are independent of these adapter implementations.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import tempfile

from structured_correspondence import witnesses
from structured_reference import decode
from test_native_codec_workers import independent

ROOT = Path(__file__).resolve().parents[1]


def call(binary, mode, codec, level, frame, input_path, output_path, expected=0, second=None):
    command = [str(binary), mode, codec, str(level), frame, str(input_path), str(output_path),
               "2000000" if "warm" in mode else "0", str(expected)]
    if second is not None:
        command.append(str(second))
    return subprocess.run(command, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=Path, default=ROOT / "target/release")
    parser.add_argument("--baseline", type=Path, help="optional sealed b7 research worker; verify all six raw controls")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    rows, rejects, resets, timers, baseline_matches = [], 0, 0, 0, 0
    roster = [("core", level, frame) for level in ("fast", "balanced", "best") for frame in ("raw", "gzip", "zip")]
    roster += [("miniz", level, frame) for level in (1, 6, 9) for frame in ("raw", "gzip", "zip")]
    roster += [("dsc1", f"{log2}/{dictionary}/{numbers}", "frame")
               for log2, dictionary, numbers in itertools.product((16, 18), ("off", "keys", "all-quoted"), ("off", "checked-delta"))]
    roster += [("dsc1", f"{log2}/off/off", "plain") for log2 in (16, 18)]
    binaries = {codec: (args.workers / name).resolve() for codec, name in
                (("core", "core_worker"), ("miniz", "miniz_worker"), ("dsc1", "structured_worker"))}
    with tempfile.TemporaryDirectory(prefix="rust-workers-") as temporary:
        directory = Path(temporary)
        raw_path, packet_path, decoded_path, second_path = (directory / n for n in ("raw", "packet", "decoded", "second"))
        for codec, level, frame in roster:
            binary = binaries[codec]
            for name, raw in witnesses():
                raw_path.write_bytes(raw)
                result = call(binary, "encode", codec, level, frame, raw_path, packet_path)
                assert result.returncode == 0, (codec, level, frame, name, result.stderr)
                packet = packet_path.read_bytes()
                assert (decode(packet) if codec == "dsc1" else independent(codec, frame, packet)) == raw
                result = call(binary, "decode", codec, level, frame, packet_path, decoded_path, len(raw))
                assert result.returncode == 0 and decoded_path.read_bytes() == raw, (codec, level, frame, name, result.stderr)
                if args.baseline and frame == "raw":
                    method = str(level) if codec == "core" else "miniz" + str(level)
                    subprocess.run([str(args.baseline.resolve()), "--memory", str(raw_path),
                                    str(directory / "b7"), method], check=True, capture_output=True)
                    assert (directory / "b7").read_bytes() == packet, (codec, level, name, "b7 identity")
                    baseline_matches += 1
                rows.append({"codec": codec, "level": level, "framing": frame, "case": name,
                             "raw_bytes": len(raw), "packed_bytes": len(packet),
                             "raw_sha256": hashlib.sha256(raw).hexdigest(), "packet_sha256": hashlib.sha256(packet).hexdigest()})
                second = raw[::-1] + b'\n{"changed":18446744073709551615,"raw":"\xff"}\n'
                second_path.write_bytes(second)
                result = call(binary, "reset-check", codec, level, frame, raw_path, packet_path, second=second_path)
                assert result.returncode == 0, result.stderr
                assert json.loads(result.stdout)["reset_check"] == "passed-stateless-A-B-A"
                assert (decode(packet_path.read_bytes()) if codec == "dsc1" else independent(codec, frame, packet_path.read_bytes())) == second
                resets += 1
                for changed in (packet[:-1], packet + b"x", packet + b"\0" * 8, packet + packet):
                    packet_path.write_bytes(changed)
                    result = call(binary, "decode", codec, level, frame, packet_path, decoded_path, len(raw))
                    assert result.returncode == 2, (codec, level, frame, name, "consumption", result.stderr)
                    rejects += 1
                packet_path.write_bytes(packet)
                result = call(binary, "decode", codec, level, frame, packet_path, decoded_path, len(raw) + 1)
                assert result.returncode == 2, (codec, level, frame, name, "declared size")
                rejects += 1
                if frame != "raw":
                    altered = bytearray(packet)
                    offset = {"gzip": -8, "zip": 14}.get(frame, 20)  # whole-frame CRC for DSC1
                    altered[offset] ^= 1
                    packet_path.write_bytes(altered)
                    result = call(binary, "decode", codec, level, frame, packet_path, decoded_path, len(raw))
                    assert result.returncode == 2, (codec, level, frame, name, "checksum")
                    rejects += 1
                if name in ("one", "chunk65537"):
                    for mode in ("cold", "warm", "reuse-cold", "reuse-warm"):
                        result = call(binary, mode, codec, level, frame, raw_path, packet_path)
                        assert result.returncode == 0, result.stderr
                        sample = json.loads(result.stdout)
                        assert sample["context"] == ("fresh-no-reuse-adapter" if mode.startswith("reuse-") else "fresh")
                        for direction in ("encode", "decode"):
                            assert sample[direction + "_ns"] > 0 and sample["first_" + direction + "_ns"] > 0
                            assert sample[direction + "_init_ns"] == 0
                            count = sample[direction + "_iterations"]
                            assert count >= 1
                            if "warm" in mode:
                                assert sample[direction + "_ns"] * count >= 1999999
                            else:
                                assert count == 1
                        assert packet_path.read_bytes() == packet, (codec, level, frame, name, mode, "packet identity")
                        timers += 1
        clocks = {codec: json.loads(subprocess.check_output([str(binary), "--clock"], text=True)) for codec, binary in binaries.items()}
        assert all(0 < row["minimum_observed_clock_step_ns"] < 1000 for row in clocks.values())
    receipt = {"schema_version": 1, "status": "passed", "scope": "shared correctness/calibration only; no study screening",
               "success_cases": len(rows), "rejected_cases": rejects, "stateless_identity_cases": resets,
               "timer_contract_cases": timers, "b7_packet_identity_cases": baseline_matches, "clocks": clocks,
               "binary_sha256": {codec: hashlib.sha256(binary.read_bytes()).hexdigest() for codec, binary in binaries.items()},
               "baseline_worker_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest() if args.baseline else None,
               "rows": rows}
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: value for key, value in receipt.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
