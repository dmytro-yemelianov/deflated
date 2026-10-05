"""lean-zip as a fourth oracle (ADR 0002).

It is here because it is an *independent reading of RFC 1951 by a different
author*. zlib is not that: zlib is the de facto definition, so agreeing with
it proves compatibility. A disagreement with lean-zip is a finding to
investigate — possibly our bug, possibly theirs, possibly a genuine RFC
ambiguity that belongs in an ADR — and is reported separately from a failure.
"""
import os
import pathlib
import subprocess

LEANZIP = os.environ.get("LEANZIP_BIN")


def available() -> bool:
    return bool(LEANZIP) and pathlib.Path(LEANZIP).exists()


def decode_all(streams, run_oracle_fn):
    """Returns a list of Outcome-shaped (ok, data, err) tuples, or None when
    lean-zip is not built on this machine. Never fails the run on absence:
    ADR 0002 records whether it builds here, and CI may not have it."""
    if not available():
        return None
    return run_oracle_fn([str(LEANZIP)], streams)
