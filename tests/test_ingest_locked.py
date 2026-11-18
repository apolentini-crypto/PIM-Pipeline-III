"""A vendor file held open by Excel must produce a plain-English halt, never a raw PermissionError."""
import pytest

from pim.config.models import Source
from pim.ingest import readers


def test_locked_file_reads_as_plain_english(tmp_path, monkeypatch):
    f = tmp_path / "PACE PIM LIST.xlsx"
    f.write_bytes(b"not really a workbook")
    src = Source(id="S1", path=f.name, format="xlsx", sheet="Sheet1", key_column="SKU")

    def refuse(*a, **k):
        raise PermissionError(13, "Permission denied", str(f))
    monkeypatch.setattr(readers.shutil, "copyfile", refuse)

    with pytest.raises(readers.IngestError) as ei:
        readers.read_source(src, tmp_path)
    msg = str(ei.value)
    assert "PACE PIM LIST.xlsx" in msg and "S1" in msg
    assert "open in Excel" in msg and "run the build again" in msg
    assert "PermissionError" not in msg
