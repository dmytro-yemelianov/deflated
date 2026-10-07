#!/usr/bin/env python3
"""Evidence integrity, holdout protection and sample-accounting regressions."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest

from encoder_baseline import BASELINE, check as check_baseline
from encoder_corpus import validate
from encoder_measure import inputs
from encoder_profile import attribute, symbol_labels
from encoder_synthetic import REGIMES, payload as synthetic_payload


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CorpusIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "licenses").mkdir()
        cases = []
        classes = ["source", "structured", "markup", "executable", "compressed", "mixed-binary", "source", "mixed-binary"]
        for partition in ("train", "validation", "test"):
            (self.root / partition).mkdir()
            for index, category in enumerate(classes):
                name = partition + "-" + str(index)
                raw = ("payload-" + name).encode() * 32
                license_raw = ("license-" + name).encode()
                path = partition + "/" + name + ".raw"
                license_path = "licenses/" + name + ".txt"
                (self.root / path).write_bytes(raw)
                (self.root / license_path).write_bytes(license_raw)
                cases.append({"path": path, "partition": partition, "class": category,
                    "source_group": name, "bytes": len(raw), "sha256": sha(raw),
                    "license_path": license_path, "provenance": {"license_download": {"sha256": sha(license_raw)}},
                    "extraction_range": [0, len(raw)], "extracted_source_bytes": len(raw)})
        self.meta = {"cases": cases, "cap_bytes": 1 << 20}

    def test_valid_source_split(self):
        self.assertEqual([v["sources"] for v in validate(self.root, self.meta).values()], [8, 8, 8])

    def test_holdout_unavailable_to_pilot(self):
        with self.assertRaisesRegex(ValueError, "inaccessible"):
            inputs(self.root, "test")

    def test_input_corruption(self):
        (self.root / self.meta["cases"][0]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "input changed"):
            validate(self.root, self.meta)

    def test_license_corruption(self):
        (self.root / self.meta["cases"][0]["license_path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "license snapshot"):
            validate(self.root, self.meta)

    def test_extra_unrecorded_input(self):
        (self.root / "test/extra.raw").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "unrecorded"):
            validate(self.root, self.meta)

    def test_invalid_path(self):
        self.meta["cases"][0]["path"] = "../escaped.raw"
        with self.assertRaisesRegex(ValueError, "invalid raw path"):
            validate(self.root, self.meta)

    def test_duplicate_source(self):
        self.meta["cases"][1] = copy.deepcopy(self.meta["cases"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate(self.root, self.meta)

    def test_no_selector_features_in_acquisition(self):
        self.meta["cases"][-1]["features"] = {"entropy": 7}
        with self.assertRaisesRegex(ValueError, "selector features"):
            validate(self.root, self.meta)

    def test_cross_partition_near_copy(self):
        original = random.Random(43).randbytes(65536)
        for index, raw in ((0, original), (8, b"x" * 4096 + original[4096:])):
            case = self.meta["cases"][index]
            (self.root / case["path"]).write_bytes(raw)
            case.update(bytes=len(raw), sha256=sha(raw), extraction_range=[0, len(raw)], extracted_source_bytes=len(raw))
        with self.assertRaisesRegex(ValueError, "near-copy"):
            validate(self.root, self.meta)


class ArtifactIntegrity(unittest.TestCase):
    def test_generic_argument_does_not_own_std_function(self):
        labels = symbol_labels(["next<deflate_core::matcher::Matcher> (in final_bench) (peekable.rs:32)"])
        self.assertEqual(labels[0][0], "binary-other")

    def test_sealed_binary_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "binary").write_bytes(b"original")
            (root / "baseline.json").write_text(json.dumps({"commit": BASELINE, "artifacts": {"binary": sha(b"original")}}))
            check_baseline(root)
            (root / "binary").write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                check_baseline(root)

    def test_inclusive_union_and_exclusive_leaf(self):
        data = {"libs": [{"name": "final_bench"}], "threads": [{
            "stackTable": {"frame": [0, 1], "prefix": [None, 0]},
            "frameTable": {"address": [8, 16], "func": [0, 1]},
            "funcTable": {"resource": [0, 0]}, "resourceTable": {"lib": [0]},
            "samples": {"stack": [1, 1, None]}}]}
        cache = {("final_bench", 8): [("deflate-core", "caller")],
                 ("final_bench", 16): [("deflate-core", "leaf"), ("deflate-core", "caller")]}
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json.gz"
            with gzip.open(profile, "wt") as out:
                json.dump(data, out)
            result = attribute(profile, Path("final_bench"), cache)
        self.assertEqual(result["samples"], 2)
        self.assertEqual(result["null_stack_samples"], 1)
        self.assertEqual(result["inclusive_samples"], {"caller": 2, "leaf": 2})
        self.assertEqual(result["exclusive_samples"], {"leaf": 2})
        self.assertEqual(sum(result["exclusive_pct"].values()), 100)


class SyntheticContracts(unittest.TestCase):
    def test_regimes_are_disjoint_and_new(self):
        sets = [set(regimes) for regimes in REGIMES.values()]
        self.assertTrue(all(min(values) > 6 for values in sets))
        self.assertEqual(len(set.union(*sets)), sum(map(len, sets)))

    def test_aligned_keys_collide_under_production_hashes(self):
        for kind, width, endian, multiplier in (
            ("trigram", 3, "big", 0x9e3779b1),
            ("fourbyte", 4, "little", 0x1e35a7bd),
            ("cost_trigram", 3, "little", 0x1e35a7bd),
        ):
            for regime in (7, 12):
                [raw], evidence = synthetic_payload("collision_" + kind, regime, 43, 65536)
                stride = width + evidence["suffix_bytes"]
                buckets = {((int.from_bytes(raw[i:i+width], endian) * multiplier) & 0xffffffff) >> 17
                           for i in range(0, len(raw)-width+1, stride)}
                self.assertEqual(buckets, {evidence["bucket"]})
                self.assertEqual(evidence["hash_bits"], 15)

    def test_transform_relationships_and_determinism(self):
        transforms = set()
        for regime in range(7, 13):
            bodies, evidence = synthetic_payload("paired_transforms", regime, 43, 65536)
            self.assertEqual((bodies, evidence), synthetic_payload("paired_transforms", regime, 43, 65536))
            base, changed = bodies
            self.assertEqual(sha(base), evidence["base_sha256"])
            self.assertNotEqual(base, changed)
            transform = evidence["transform"]
            transforms.add(transform)
            if transform == "duplicate":
                self.assertEqual(changed, base + base)
            elif transform in ("append", "concatenate"):
                self.assertTrue(changed.startswith(base))
            elif transform == "prepend":
                self.assertTrue(changed.endswith(base))
            else:
                self.assertEqual(len(changed), len(base))
        self.assertEqual(transforms, {"prepend", "append", "concatenate", "duplicate", "mutate", "change_point"})


if __name__ == "__main__":
    unittest.main()
