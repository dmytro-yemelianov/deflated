#!/usr/bin/env python3
"""Fetch author-hosted Canterbury/large/Silesia corpora into ignored target/.

Data stays outside git. Manifest records hashes and the fixed training/holdout
assignment so a tuning result can be reproduced without changing that split.
"""
import argparse
import hashlib
import io
import json
import pathlib
import subprocess
import tarfile
import zipfile

CANTERBURY = "https://corpus.canterbury.ac.nz/resources/"
SILESIA = "https://sun.aei.polsl.pl/~sdeor/corpus/silesia.zip"
TRAIN = {
    "alice29.txt", "cp.html", "fields.c", "grammar.lsp", "ptt5", "sum",
    "E.coli", "bible.txt", "dickens", "mr", "nci", "ooffice", "xml",
}
SILESIA_MD5 = {
    "dickens": "88334708559f6db57d79096bc0aca07e",
    "mozilla": "c7789a2097f1ff944b0c737430a339b3",
    "mr": "38e623e3093b7bf2003ca4b1bbc19927",
    "nci": "31f85bc8706f3c921104e7c169e2e2e1",
    "ooffice": "573c4ae915e36631d8f2dcffb9b9b66d",
    "osdb": "e734b0c48e6a982adfb5802da3032ecd",
    "reymont": "d8f54d78105079775f32d76dc55fc671",
    "samba": "154eaea7ea70e89f6339ff0abf4112ca",
    "sao": "79e95a22e18cd82b7e42bf91b380d30b",
    "webster": "474931ad907ac27bf962c75ded46c069",
    "xml": "9b09c0c80104adb8aae910b7d7db003e",
    "x-ray": "9baec32ad14ec3eff487d254382cb91c",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("target/tuning-corpus"))
    args = parser.parse_args()
    root = args.out
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for archive, url in [("cantrbry.tar.gz", CANTERBURY + "cantrbry.tar.gz"),
                         ("large.tar.gz", CANTERBURY + "large.tar.gz"),
                         ("silesia.zip", SILESIA)]:
        cached = root / archive
        if not cached.exists():
            temporary = root / (archive + ".download")
            subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                            "--retry", "2", "--max-time", "120", "--user-agent",
                            "Mozilla/5.0", url, "--output", str(temporary)], check=True)
            temporary.replace(cached)
        if archive.endswith(".zip"):
            with zipfile.ZipFile(cached) as zf:
                files = [(pathlib.PurePosixPath(n).name, zf.read(n))
                         for n in zf.namelist() if not n.endswith("/")]
        else:
            with tarfile.open(fileobj=io.BytesIO(cached.read_bytes()), mode="r:gz") as tf:
                files = [(pathlib.PurePosixPath(m.name).name, tf.extractfile(m).read())
                         for m in tf.getmembers() if m.isfile()]
        for name, raw in files:
            if archive.endswith(".zip"):
                assert hashlib.md5(raw).hexdigest() == SILESIA_MD5[name], name
            partition = "train" if name in TRAIN else "holdout"
            destination = root / partition
            destination.mkdir(exist_ok=True)
            (destination / (name + ".raw")).write_bytes(raw)
            records.append({"input": name + ".raw", "partition": partition,
                            "source": url, "bytes": len(raw),
                            "sha256": hashlib.sha256(raw).hexdigest()})
            print(partition, name, len(raw), flush=True)
    stress = root / "stress"
    subprocess.run(["python3", str(pathlib.Path(__file__).with_name("perf_corpus.py")), str(stress)], check=True)
    for name in ["random.raw", "repetitive.raw", "text.raw", "zeros.raw"]:
        raw = (stress / name).read_bytes()
        records.append({"input": name, "partition": "stress", "source": "scripts/perf_corpus.py:seed1951",
                        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    (root / "manifest.json").write_text(json.dumps(sorted(records, key=lambda r: r["input"]), indent=2) + "\n")


if __name__ == "__main__":
    main()
