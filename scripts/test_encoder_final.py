import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from encoder_final_stats import validate_rows, role_guards
from encoder_final_campaign import measure
from search_final_stats import summary
from search_poc import decode_exact

BINARY=None


def rows():
    return [{"session":s,"input":str(i),"method":"x","raw_bytes":n,"packed_bytes":5,"baseline_bytes":10,
        "packet_sha256":"a","baseline_packet_sha256":"b","encode_ns":n,"decode_ns":n,"baseline_encode_ns":2*n,"baseline_decode_ns":2*n,
        "cold_encode_ns":n,"cold_decode_ns":n,"cold_baseline_encode_ns":2*n,"cold_baseline_decode_ns":2*n}
        for s in range(10) for i,n in enumerate((10,1000))]


class FinalContract(unittest.TestCase):
    def test_started_holdout_cannot_be_silently_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/"freeze.json").write_text("{}")
            (root/"started.json").write_text("{}")
            with patch("encoder_final_campaign.guard"),patch("encoder_final_campaign.subprocess.check_output") as native:
                with self.assertRaises(ValueError):measure(root)
                native.assert_not_called()

    def test_complete_session_product_required(self):
        data=rows();cases=[{"path":"0"},{"path":"1"}]
        validate_rows(data,cases,["x"],10)
        with self.assertRaises(ValueError):validate_rows(data[:-1],cases,["x"],10)
        with self.assertRaises(ValueError):validate_rows(data+[data[0]],cases,["x"],10)

    def test_file_and_secondary_scope_caps_cannot_hide_in_aggregate(self):
        report=summary(rows(),resamples=100)
        metrics={s:json.loads(json.dumps(report)) for s in ("new-real-test","new-synthetic-test","old-regression","tiny")}
        role={"warm_speed_lower_95_min":1.5,"first_call_speed_lower_95_min":1.5,"aggregate_size_ratio_max":1.01,"per_file_size_ratio_max":1.2}
        common={"decoder_time_upper_95_ratio_max":1.2,"worst_tiny_warm_median_ratio_max":1.2,"max_per_case_median_process_rss_increase_bytes":8388608,"portable_release_binary_growth_bytes_max":65536}
        memory={"maximum_increase_bytes":0}
        self.assertTrue(role_guards(metrics,role,common,memory,0)["passed"])
        metrics["new-synthetic-test"]["max_file_size_vs_balanced"]=1.21
        self.assertFalse(role_guards(metrics,role,common,memory,0)["checks"]["per_file_sizes"])
        metrics["old-regression"]["size_vs_balanced"]=1.02
        self.assertFalse(role_guards(metrics,role,common,memory,0)["checks"]["aggregate_sizes"])

    def test_default_harness_first_warm_and_memory_packets_match(self):
        if BINARY is None:self.skipTest("pass --binary after a default-feature build")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"input.raw";output=root/"streams"
            for raw in (b"",b"abcabc"*17,bytes(range(256))*129,b"abc"*21846):
                source.write_bytes(raw);packets=[]
                for mode in ("cold","warm"):
                    data=json.loads(subprocess.check_output([BINARY,mode,str(source),str(output),"1","balanced","0"],text=True))
                    packet=(output/"candidate.deflate").read_bytes();decode_exact(packet,raw);packets.append(packet)
                    self.assertGreater(data["encode_ns"],0);self.assertGreater(data["decode_ns"],0)
                memory=root/"memory.deflate"
                subprocess.check_output([BINARY,"--memory",str(source),str(memory),"balanced"])
                self.assertEqual(packets[0],packets[1]);self.assertEqual(packets[0],memory.read_bytes())


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--binary")
    args,remaining=parser.parse_known_args()
    BINARY=str(Path(args.binary).resolve()) if args.binary else None
    unittest.main(argv=[__file__,*remaining])
