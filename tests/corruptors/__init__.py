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


# ----------------------------------------------------------------- M1 build-gate corruptors
def _copy_pack(ctx, name):
    src, dst = Path(ctx["pack_dir"]), Path(ctx["tmp"]) / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    bad = dict(ctx); bad["pack_dir"] = str(dst); bad["var_dir"] = str(Path(ctx["tmp"]) / "var")
    return dst, bad


def _edit(path: Path, old: str, new: str):
    t = path.read_text(encoding="utf-8"); assert old in t, f"corruptor target {old!r} not in {path}"
    path.write_text(t.replace(old, new), encoding="utf-8")


@register_corruptor("G-ROSTER")
def corrupt_roster(ctx):
    dst, bad = _copy_pack(ctx, "bad-roster")
    (dst / "expectations.yaml").write_text("roster_count: 99\n")
    return bad


@register_corruptor("G-REQUIRED")
def corrupt_required(ctx):
    dst, bad = _copy_pack(ctx, "bad-required")
    _edit(dst / "sources" / "products.csv", "HS-200,Long Cutter 200", "HS-200,")
    return bad


@register_corruptor("G-ENCODING")
def corrupt_encoding(ctx):
    dst, bad = _copy_pack(ctx, "bad-encoding")
    _edit(dst / "sources" / "products.csv", "Tapered", "45º Tapered")
    return bad


@register_corruptor("G-ALIAS-CONFLICT")
def corrupt_alias(ctx):
    dst, bad = _copy_pack(ctx, "bad-alias")
    _edit(dst / "sources" / "prices.csv", "RX-100,100.50,133.5 mm", "RX-100,100.50,150 mm")
    return bad


@register_corruptor("G-OVERRIDE-STALE")
def corrupt_override(ctx):
    dst, bad = _copy_pack(ctx, "bad-override")
    (dst / "overrides").mkdir(exist_ok=True)
    (dst / "overrides" / "stale.yaml").write_text(
        "overrides:\n  - { sku: RX-100, field: name, before: 'Old Title', after: 'New', basis: { who: t, when: '2026-10-19', why: fixture } }\n")
    return bad


@register_corruptor("G-KEY-UNIQUE")
def corrupt_key(ctx):
    dst, bad = _copy_pack(ctx, "bad-key")
    p = dst / "sources" / "products.csv"; p.write_text(p.read_text() + "RX-100,Dup,,Oval,1\n")
    return bad
