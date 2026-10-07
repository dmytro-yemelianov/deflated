#!/usr/bin/env python3
"""New disjoint encoder regimes, reusing checked collision/cost generators."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import random

from encoder_corpus import ROOT, write_json
from encoder_measure import sha
from search_corpus import seed_for, validate
from search_extended_corpus import collision_keys, payload as extension_payload

REGIMES = {"train":(7,10), "validation":(8,11), "test":(9,12)}
FAMILIES = ("cost_sensitive","collision_trigram","collision_fourbyte","collision_cost_trigram",
            "change_points","drift","feature_sampling_trap","random_islands","paired_transforms")


def payload(family, regime, seed, n=262144):
    rng = random.Random(seed)
    if family.startswith("collision_"):
        keys, evidence = collision_keys(family.removeprefix("collision_"),15,2*regime+5,rng)
        rows = [key+rng.randbytes(19+regime) for key in keys]
        raw = bytearray()
        while len(raw)<n:
            raw.extend(rng.choice(rows))
        return [bytes(raw[:n])], {**evidence,"suffix_bytes":19+regime,"actual_production_hash_bits":15}
    if family == "random_islands":
        motif=rng.randbytes(31+2*regime)
        raw=bytearray((motif*((n+len(motif)-1)//len(motif)))[:n])
        width=7*regime+1
        locations=[]
        for position in range(511+regime,n-width,4096+31*regime):
            raw[position:position+width]=rng.randbytes(width)
            locations.append([position,width])
        return [bytes(raw)], {"period":len(motif),"random_islands":locations,"window_wraps":n//32768}
    if family == "paired_transforms":
        motif=rng.randbytes(257+2*regime)
        base=bytearray((motif*((n+len(motif)-1)//len(motif)))[:n//2])
        for position in range(1000+regime,len(base),4093+regime):
            base[position]^=1
        transform=("prepend","append","concatenate","duplicate","mutate","change_point")[regime%6]
        extra=rng.randbytes(511+regime)
        if transform=="prepend": changed=extra+base
        elif transform=="append": changed=base+extra
        elif transform=="concatenate": changed=base+rng.randbytes(len(base))
        elif transform=="duplicate": changed=base+base
        else:
            changed=bytearray(base)
            if transform=="mutate":
                for position in range(regime,len(changed),67+regime): changed[position]^=rng.randrange(1,256)
            else: changed[len(changed)//2:]=rng.randbytes(len(changed)-len(changed)//2)
        return [bytes(base),bytes(changed)], {"transform":transform,"period":len(motif),
            "base_sha256":hashlib.sha256(base).hexdigest(),"window_wraps_base":len(base)//32768}
    return extension_payload(family,regime,seed,n)


def build(out, check=False):
    cases, bodies = [], {}
    for partition, regimes in REGIMES.items():
        for family in FAMILIES:
            for regime in regimes:
                params={"version":1,"regime":regime}
                seed=seed_for(20261007,partition,"encoder-"+family,params)
                variants,evidence=payload(family,regime,seed)
                pair_id=f"{partition}:{family}:{regime}"
                for variant, raw in enumerate(variants):
                    path=f"{partition}/{family}-{regime}-{variant}.raw"
                    cases.append({"path":path,"partition":partition,"family":family,
                        "params":{**params,"variant":variant},"seed":seed,"regime":f"encoder:{family}:{regime}:{variant}",
                        "bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"pair_id":pair_id,"construction":evidence})
                    bodies[path]=raw
    meta={"schema_version":1,"profile":"encoder-new-256k","generator_sha256":sha(Path(__file__)),
          "helper_sha256":{p:sha(ROOT/p) for p in ("scripts/search_corpus.py","scripts/search_extended_corpus.py")},
          "test_policy":"reserved; construct/regenerate/hash only; no selector features or encoder labels before freeze",
          "partition_regimes":REGIMES,"cases":cases}
    # JSON canonicalization normalizes tuples for deterministic rechecking.
    meta=json.loads(json.dumps(meta))
    manifest=out/"manifest.json"
    if check:
        if json.loads(manifest.read_text())!=meta:
            raise ValueError("generator/provenance changed")
    else:
        out.mkdir(parents=True,exist_ok=False)
        for name,raw in bodies.items():
            file=out/name
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(raw)
        write_json(manifest,meta)
    validate(out,meta)
    if any((out/name).read_bytes()!=raw for name,raw in bodies.items()):
        raise ValueError("synthetic regeneration differs")
    print(json.dumps({"manifest":str(manifest),"sha256":sha(manifest),"counts":dict(collections.Counter(c["partition"] for c in cases))}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=ROOT/"target/encoder-performance/synthetic-v1")
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    build(args.out.resolve(),args.check)
