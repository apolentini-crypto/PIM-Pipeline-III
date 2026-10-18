"""Falsifiability harness (ADR-7, FR-87, AC-17): one corruptor per registered check.

A corruptor takes a GOOD ctx and returns a BAD ctx on which the check MUST fail.
tests/test_falsifiability.py asserts (a) every check has a corruptor, (b) the check
passes on the good ctx, (c) the check fails on the corrupted ctx. A check that cannot be
made to fail is not a check (INV-1).
"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

from pim.verify.check import register_corruptor


@register_corruptor("G-PACK")
def corrupt_pack(ctx):
    """Introduce three independent defects: a typo'd key, a missing required file,
    and a dangling source reference — all must be reported together (FR-4)."""
    src = Path(ctx["pack_dir"])
    dst = Path(ctx["tmp"]) / "bad-pack"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    (dst / "managed.yaml").unlink()                                     # missing required file
    (dst / "brand.yaml").write_text((dst / "brand.yaml").read_text() + "\nslugg: oops\n")  # unknown key
    f = (dst / "fields.yaml").read_text().replace("source: S2", "source: S9")  # dangling source id
    (dst / "fields.yaml").write_text(f)
    bad = dict(ctx)
    bad["pack_dir"] = str(dst)
    bad["expected_min_errors"] = 3
    return bad


@register_corruptor("G-SKU-GRAMMAR")
def corrupt_skus(ctx):
    bad = copy.deepcopy(ctx)
    bad["skus"] = list(ctx["skus"]) + [
        "59-8130",          # dash after brand (the live Lindström shape) — forbidden by D-8
        "2.53131A.X",       # unknown ending
        "2.53131A.1-U",     # condition after the ending
        "2.53131A.P0",      # pack of zero
        "2.5313.1A",        # dot inside mpn
    ]
    bad["expected_min_errors"] = 5
    return bad
