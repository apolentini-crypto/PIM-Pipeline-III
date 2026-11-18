"""Stage 1 readers (FR-6..13, FR-111). Declared, not sniffed. Everything is TEXT (FR-8).

Every reader returns RawFrames: a header list (byte-exact, never trimmed) and rows of
{header: text}. A cell that is empty is "" — never None, never "nan".
Sources are copied to a temp file before opening so a file held by Excel or a sync
client still reads, and no write lock ever touches the vendor path (FR-9/10).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from pim.config.models import Block, Source


class IngestError(Exception):
    """Names source, sheet/block and what was expected."""


@dataclass
class SourceStamp:
    source_id: str
    path: str
    sha256: str
    size: int
    mtime_iso: str


@dataclass
class RawFrame:
    source_id: str
    block_id: str              # == source_id when the source has no blocks
    key_name: str              # header text of the key column (or "#<index>" when blank)
    headers: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)   # each row includes "_row": "<n>"
    multi: bool = False

    def column_names(self) -> set[str]:
        return set(self.headers)


# ----------------------------------------------------------------- text coercion (FR-8)
def cell_text(v: Any, typed: str | None = None) -> str:
    """Render any cell value as the text a careful human would read off the sheet."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))           # 7314150103003.0 -> 7314150103003 (never a float-ified EAN)
        return f"{v:.12g}"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    s = str(v)
    if s.startswith("#") and s.endswith("?") and s[1:-1].isalpha():
        return ""                        # Excel error values (#NAME?, #REF?) are not data — reported by the gate
    return s


def _stamp(source: Source, path: Path) -> SourceStamp:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    st = path.stat()
    return SourceStamp(source.id, str(path), h.hexdigest(), st.st_size, dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat())


def _temp_copy(path: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="pim-src-")) / path.name
    shutil.copyfile(path, tmp)        # copyfile, not copy2: we never touch the vendor path's metadata
    return tmp


# ----------------------------------------------------------------- xlsx
def _xlsx_rows(path: Path, sheet: str, max_cols: int | None) -> Iterator[tuple[Any, ...]]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        raise IngestError(f"sheet {sheet!r} not in {path.name}; sheets are {wb.sheetnames}")
    ws = wb[sheet]
    for row in ws.iter_rows(values_only=True, max_col=max_cols):
        yield row
    wb.close()


def _frame_from_grid(source: Source, block: Block | None, grid: list[tuple[Any, ...]]) -> RawFrame:
    hr = source.header_row - 1
    if hr >= len(grid):
        raise IngestError(f"{source.id}: header_row {source.header_row} is past the end of the sheet ({len(grid)} rows)")
    header_cells = list(grid[hr])
    lo, hi = 0, len(header_cells)
    if block and block.col_from:
        lo = block.col_from - 1
    if block and block.col_to:
        hi = block.col_to
    headers = [cell_text(h) for h in header_cells[lo:hi]]
    # trailing phantom columns: drop headers that are blank AND whose column is blank in every row
    while headers and headers[-1] == "":
        idx = lo + len(headers) - 1
        if any(cell_text(r[idx] if idx < len(r) else None) for r in grid[hr + 1:]):
            break
        headers.pop()
    # key
    key_col = (block.key_column if block else source.key_column)
    key_idx = (block.key_index if block else source.key_index)
    key_outside = False
    if key_col:
        if headers.count(key_col) == 1:
            key_name = key_col
        else:
            # a block may be keyed by a column OUTSIDE its range (row-aligned blocks, FR-12):
            # e.g. the price block of a two-block sheet keyed on the PIM block's PRODUCT column
            full = [cell_text(h) for h in header_cells]
            if block and full.count(key_col) == 1:
                key_idx = full.index(key_col) + 1
                key_name = key_col
                key_outside = True
            else:
                raise IngestError(f"{source.id}{'/' + block.id if block else ''}: key column {key_col!r} occurs {headers.count(key_col)} times in headers (expected 1); headers: {headers[:12]}…")
    else:
        key_name = f"#{key_idx}"
        if key_idx - 1 < lo or key_idx > lo + len(headers):
            raise IngestError(f"{source.id}: key_index {key_idx} outside the block's columns")
    dup = sorted({h for h in headers if h and headers.count(h) > 1})
    if dup:
        raise IngestError(f"{source.id}{'/' + block.id if block else ''}: duplicate headers {dup} — FR-111: headers must be unique byte-exact; declare blocks to separate them")
    rows = []
    for rn, r in enumerate(grid[hr + 1:], start=source.header_row + 1):
        cells = list(r)[lo:lo + len(headers)]
        cells += [None] * (len(headers) - len(cells))
        row = {h: cell_text(c, source.typed_columns.get(h)) for h, c in zip(headers, cells) if h != ""}
        if key_col is None or key_outside:
            row[key_name] = cell_text(list(r)[key_idx - 1] if key_idx - 1 < len(r) else None)
        if not any(v for v in row.values()):
            continue
        row["_row"] = str(rn)
        rows.append(row)
    return RawFrame(source.id, block.id if block else source.id, key_name, headers if (key_col and not key_outside) else headers + [key_name], rows, multi=source.multi)


def read_xlsx(source: Source, path: Path) -> list[RawFrame]:
    tmp = _temp_copy(path)
    try:
        if source.blocks:
            grid = list(_xlsx_rows(tmp, source.sheet, source.max_cols))
            return [_frame_from_grid(source, b, grid) for b in source.blocks]
        grid = list(_xlsx_rows(tmp, source.sheet, source.max_cols))
        return [_frame_from_grid(source, None, grid)]
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


# ----------------------------------------------------------------- csv
def read_csv(source: Source, path: Path) -> list[RawFrame]:
    tmp = _temp_copy(path)
    try:
        try:
            with tmp.open("r", encoding=source.encoding, newline="") as fh:
                grid = [tuple(r) for r in csv.reader(fh)]
        except UnicodeDecodeError as e:
            raise IngestError(f"{source.id}: {path.name} is not {source.encoding} (byte {e.object[e.start:e.start+1]!r} at offset {e.start}); declare the file's real encoding in sources.yaml (e.g. encoding: cp1252)")
        return [_frame_from_grid(source, None, grid)]
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


# ----------------------------------------------------------------- json
def _flatten(rec: dict, prefixes: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in rec.items():
        if k in prefixes and isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = cell_text(v2) if not isinstance(v2, (list, dict)) else json.dumps(v2, ensure_ascii=False)
        elif isinstance(v, (list, dict)):
            out[k] = json.dumps(v, ensure_ascii=False)
        else:
            out[k] = cell_text(v)
    return out


def read_json(source: Source, path: Path) -> list[RawFrame]:
    tmp = _temp_copy(path)
    try:
        data = json.loads(tmp.read_text(encoding=source.encoding))
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    if isinstance(data, dict):
        data = list(data.values())
    if not isinstance(data, list):
        raise IngestError(f"{source.id}: json must be a list of records or a dict of records")
    rows = []
    headers: list[str] = []
    seen = set()
    for i, rec in enumerate(data, start=1):
        if not isinstance(rec, dict):
            raise IngestError(f"{source.id}: record {i} is not an object")
        flat = _flatten(rec, source.flatten)
        for h in flat:
            if h not in seen:
                seen.add(h); headers.append(h)
        flat["_row"] = str(i)
        rows.append(flat)
    key = source.key_column
    if key not in seen:
        raise IngestError(f"{source.id}: key column {key!r} not present in any record; keys seen: {headers[:12]}…")
    for r in rows:
        for h in headers:
            r.setdefault(h, "")
    return [RawFrame(source.id, source.id, key, headers, rows, multi=source.multi)]


READERS = {"xlsx": read_xlsx, "xlsm": read_xlsx, "csv": read_csv, "json": read_json}


def read_source(source: Source, root: Path) -> tuple[list[RawFrame], SourceStamp | None]:
    path = Path(source.path)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        if source.optional:
            return [], None
        raise IngestError(f"{source.id}: file not found: {path}")
    try:
        frames = READERS[source.format](source, path)
        return frames, _stamp(source, path)
    except PermissionError as e:
        raise IngestError(_locked_message(source, path)) from e


def _locked_message(source: Source, path: Path) -> str:
    """Windows refuses a read of a workbook that Excel has open (AutoSave on a OneDrive file
    holds it exclusively). Say so in plain words — the raw PermissionError reads like a bug."""
    return (
        f"Can't read {path.name} ({source.id}) — Windows says it is in use by another program.\n"
        f"  Most likely it is open in Excel. Close that workbook (check Task Manager for a leftover\n"
        f"  Excel.exe), then run the build again. The file itself was not touched.\n"
        f"  Full path: {path}"
    )
