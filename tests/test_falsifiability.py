"""AC-17 / FR-87: every check is green on good input and RED on its corruptor."""
import pytest

import pim.verify.gates  # noqa: F401 — registers checks
import tests.corruptors  # noqa: F401 — registers corruptors
from pim.verify.check import checks, corruptors


def test_every_check_has_a_corruptor():
    missing = sorted(set(checks()) - set(corruptors()))
    assert not missing, f"checks without a corruptor (ADR-7): {missing}"


@pytest.mark.parametrize("check_id", sorted(checks()))
def test_check_passes_good_and_fails_corrupted(check_id, good_ctx):
    check = checks()[check_id]
    good = check.measure(good_ctx)
    assert good.passed, f"{check_id} failed on GOOD input: {good.details}"
    bad_ctx = corruptors()[check_id](good_ctx)
    bad = check.measure(bad_ctx)
    assert not bad.passed, f"{check_id} did not go red on corrupted input — a check that cannot fail is not a check"
    assert len(bad.details) >= bad_ctx.get("expected_min_errors", 1), (
        f"{check_id} reported {len(bad.details)} error(s); corruptor planted {bad_ctx.get('expected_min_errors')} — not every error at once (FR-4)"
    )
    # FR-101: a measurement carries numbers, not only a verdict
    assert good.observed and bad.observed
