import unittest

from encoder_selector import folds, scope_summary, serialize


class SelectorContract(unittest.TestCase):
    def test_source_and_paired_family_groups_never_cross_folds(self):
        cases=[{"group":f"source-{i//2}","id":i} for i in range(24)]
        held=folds(cases,1951)
        for group in {c["group"] for c in cases}:
            self.assertEqual(sum(any(c["group"]==group for c in fold) for fold in held),1)
        self.assertEqual(sorted(c["id"] for fold in held for c in fold),list(range(24)))

    def test_small_scope_cannot_hide_a_size_guard_failure(self):
        cases=[{"scope":scope,"baseline_ns":100,"baseline_bytes":size,
                "measurements":[{"encode_ns":50,"packed_bytes":packed}]} for scope,size,packed in
                [("new-real-train",100000,100000),("new-synthetic-train",100,121)]]
        self.assertFalse(scope_summary(cases,[0,0])["feasible"])
        self.assertTrue(serialize({"config":0}).startswith("policy-v2 features-15"))


if __name__=="__main__":unittest.main()
