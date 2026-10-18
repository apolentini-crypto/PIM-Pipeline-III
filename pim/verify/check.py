"""The Check framework (ARCH §7, ADR-7).

Every gate, assertion and verification is a Check: it returns a Measurement (numbers,
never only a verdict — FR-101) and must have a registered corruptor that turns it red
(FR-87, INV-1). A Check without a corruptor fails the test suite (tests/test_falsifiability.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class Measurement:
    check_id: str
    passed: bool
    observed: dict[str, Any] = field(default_factory=dict)   # the numbers
    before: dict[str, Any] | None = None                      # FR-126: "N defects remain" needs a before-count
    details: list[str] = field(default_factory=list)          # every offending row/field, named

    def line(self) -> str:
        nums = ", ".join(f"{k}={v}" for k, v in self.observed.items())
        return f"[{'PASS' if self.passed else 'FAIL'}] {self.check_id}: {nums}"


class Check(Protocol):
    id: str
    requirement: str  # the FR/gate it implements

    def measure(self, ctx: Any) -> Measurement: ...


# ---------------------------------------------------------------- registry
_CHECKS: dict[str, Check] = {}
_CORRUPTORS: dict[str, Callable[[Any], Any]] = {}


def register_check(check: Check) -> Check:
    if check.id in _CHECKS:
        raise ValueError(f"duplicate check id {check.id}")
    _CHECKS[check.id] = check
    return check


def register_corruptor(check_id: str):
    """Decorator: registers a function ctx -> corrupted_ctx that MUST make the check fail."""
    def deco(fn):
        _CORRUPTORS[check_id] = fn
        return fn
    return deco


def checks() -> dict[str, Check]:
    return dict(_CHECKS)


def corruptors() -> dict[str, Callable]:
    return dict(_CORRUPTORS)


def run_all(ctx: Any) -> list[Measurement]:
    return [c.measure(ctx) for c in _CHECKS.values()]
