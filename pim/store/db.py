"""Stage 4 — authoritative SQLite store (ADR-2, FR-39..47). One db per brand: var/<brand>/pim.db."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS builds(
  build_id TEXT PRIMARY KEY, created TEXT, tool_version TEXT, pack_hash TEXT,
  vocab_version TEXT, row_count INTEGER, manifest_json TEXT);
CREATE TABLE IF NOT EXISTS rows(
  build_id TEXT, sku TEXT, held INTEGER DEFAULT 0, hold_reason TEXT,
  PRIMARY KEY(build_id, sku));
CREATE TABLE IF NOT EXISTS field_values(
  build_id TEXT, sku TEXT, field TEXT, value TEXT, unit TEXT, prov_kind TEXT, prov_ref TEXT,
  PRIMARY KEY(build_id, sku, field));
CREATE TABLE IF NOT EXISTS catalog_rows(
  build_id TEXT, sku TEXT, mpn TEXT, kind TEXT, parent_mpn TEXT, pack_qty INTEGER,
  held TEXT, price_basis TEXT, unpriced INTEGER, margin_pct REAL,
  PRIMARY KEY(build_id, sku));                    -- A1 §4
CREATE TABLE IF NOT EXISTS catalog_values(
  build_id TEXT, sku TEXT, field TEXT, value TEXT, unit TEXT, prov_kind TEXT, prov_ref TEXT,
  PRIMARY KEY(build_id, sku, field));
CREATE TABLE IF NOT EXISTS families(
  build_id TEXT, family_key TEXT, position INTEGER, sku TEXT,
  PRIMARY KEY(build_id, family_key, position));
CREATE TABLE IF NOT EXISTS vocab(
  facet_key TEXT, value TEXT, version TEXT, added_when TEXT, added_why TEXT,
  PRIMARY KEY(facet_key, value, version));
CREATE TABLE IF NOT EXISTS remote_ids(
  sku TEXT, endpoint TEXT, environment TEXT, remote_id TEXT,
  PRIMARY KEY(sku, endpoint, environment));
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, build_id TEXT, mode TEXT, environment TEXT,
  status TEXT, started TEXT, finished TEXT, report_path TEXT);
CREATE TABLE IF NOT EXISTS ledger(
  run_id TEXT, seq INTEGER, sku TEXT, action TEXT, remote_id TEXT,
  fields_json TEXT, before_json TEXT, status TEXT, detail TEXT,
  PRIMARY KEY(run_id, seq));
CREATE TABLE IF NOT EXISTS rulings(ruling_id TEXT PRIMARY KEY, status TEXT, evidence TEXT);
"""
SCHEMA_VERSION = "1"


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        con.execute("PRAGMA journal_mode=DELETE")   # WAL is unavailable on some network/FUSE mounts
    con.executescript(SCHEMA)
    con.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version',?)", (SCHEMA_VERSION,))
    return con


def write_build(con: sqlite3.Connection, build_id: str, created: str, tool_version: str, pack_hash: str,
                vocab_version: str, rows: dict, held: dict[str, str], manifest: dict) -> None:
    """rows: {sku: {field: (value, unit, prov_kind, prov_ref)}}. Idempotent per build_id (replace)."""
    with con:
        con.execute("DELETE FROM field_values WHERE build_id=?", (build_id,))
        con.execute("DELETE FROM rows WHERE build_id=?", (build_id,))
        con.execute("DELETE FROM families WHERE build_id=?", (build_id,))
        con.execute("INSERT OR REPLACE INTO builds VALUES(?,?,?,?,?,?,?)",
                    (build_id, created, tool_version, pack_hash, vocab_version, len(rows), json.dumps(manifest, sort_keys=True)))
        con.executemany("INSERT INTO rows VALUES(?,?,?,?)",
                        [(build_id, sku, 1 if sku in held else 0, held.get(sku)) for sku in sorted(rows)])
        con.executemany("INSERT INTO field_values VALUES(?,?,?,?,?,?,?)",
                        [(build_id, sku, f, v, u, pk, pr) for sku in sorted(rows) for f, (v, u, pk, pr) in sorted(rows[sku].items())])


def write_catalog(con: sqlite3.Connection, build_id: str, rows: dict, meta: dict) -> None:
    with con:
        con.execute("DELETE FROM catalog_rows WHERE build_id=?", (build_id,))
        con.execute("DELETE FROM catalog_values WHERE build_id=?", (build_id,))
        con.executemany("INSERT INTO catalog_rows VALUES(?,?,?,?,?,?,?,?,?,?)",
                        [(build_id, sku, m["mpn"], m["kind"], m["parent_mpn"], m["pack_qty"], m["held"], m["price_basis"], 1 if m["unpriced"] else 0, m["margin_pct"]) for sku, m in sorted(meta.items())])
        con.executemany("INSERT INTO catalog_values VALUES(?,?,?,?,?,?,?)",
                        [(build_id, sku, f, v, u, pk, pr) for sku in sorted(rows) for f, (v, u, pk, pr) in sorted(rows[sku].items())])


def read_catalog(con: sqlite3.Connection, build_id: str) -> tuple[dict, dict]:
    rows: dict = {}; meta: dict = {}
    for sku, f, v, u, pk, pr in con.execute("SELECT sku, field, value, unit, prov_kind, prov_ref FROM catalog_values WHERE build_id=? ORDER BY sku, field", (build_id,)):
        rows.setdefault(sku, {})[f] = (v, u, pk, pr)
    for sku, mpn, kind, parent, qty, held, basis, unpriced, margin in con.execute("SELECT sku, mpn, kind, parent_mpn, pack_qty, held, price_basis, unpriced, margin_pct FROM catalog_rows WHERE build_id=?", (build_id,)):
        meta[sku] = {"mpn": mpn, "kind": kind, "parent_mpn": parent, "pack_qty": qty, "held": held, "price_basis": basis, "unpriced": bool(unpriced), "margin_pct": margin}
    return rows, meta


def read_build(con: sqlite3.Connection, build_id: str) -> dict:
    rows: dict = {}
    for sku, f, v, u, pk, pr in con.execute("SELECT sku, field, value, unit, prov_kind, prov_ref FROM field_values WHERE build_id=? ORDER BY sku, field", (build_id,)):
        rows.setdefault(sku, {})[f] = (v, u, pk, pr)
    for sku, held, reason in con.execute("SELECT sku, held, hold_reason FROM rows WHERE build_id=?", (build_id,)):
        rows.setdefault(sku, {})
    return rows


def latest_build_id(con: sqlite3.Connection) -> str | None:
    r = con.execute("SELECT build_id FROM builds ORDER BY created DESC LIMIT 1").fetchone()
    return r[0] if r else None
