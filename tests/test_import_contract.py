"""ADR-3 dependency rule, enforced without an external linter: core never imports endpoints
except through endpoints.base; endpoints never import ingest/normalize/derive."""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "pim"
CORE = ("config", "ingest", "normalize", "derive", "store", "changeset", "publish", "verify", "report", "util")


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_core_does_not_import_endpoint_implementations():
    for sub in CORE:
        for f in (PKG / sub).rglob("*.py") if (PKG / sub).exists() else []:
            for mod in _imports(f):
                if mod.startswith("pim.endpoints") and mod != "pim.endpoints.base":
                    raise AssertionError(f"{f.relative_to(PKG)} imports {mod}; core may only import pim.endpoints.base")


def test_endpoints_do_not_import_pipeline_stages():
    ep = PKG / "endpoints"
    if not ep.exists():
        return
    for f in ep.rglob("*.py"):
        for mod in _imports(f):
            if any(mod.startswith(f"pim.{s}") for s in ("ingest", "normalize", "derive")):
                raise AssertionError(f"{f.relative_to(PKG)} imports {mod}; endpoints never see vendor-file stages")
