import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from normalize_title import derive_title_from_branch, should_normalize  # noqa: E402


def test_feature_branch_with_ticket():
    assert (
        derive_title_from_branch("feature/DEV-123-customer-login")
        == "feat(DEV-123): customer login"
    )


def test_feat_branch_with_ticket():
    assert (
        derive_title_from_branch("feat/DEV-123-customer-login")
        == "feat(DEV-123): customer login"
    )


def test_bugfix_branch_with_ticket():
    assert (
        derive_title_from_branch("bugfix/DEV-456-payment-timeout")
        == "fix(DEV-456): payment timeout"
    )


def test_fix_branch_with_ticket():
    assert (
        derive_title_from_branch("fix/DEV-456-payment-timeout")
        == "fix(DEV-456): payment timeout"
    )


def test_hotfix_branch_with_ticket():
    assert (
        derive_title_from_branch("hotfix/DEV-789-production-error")
        == "fix(DEV-789): production error"
    )


def test_chore_branch_without_ticket():
    assert (
        derive_title_from_branch("chore/update-dependencies")
        == "chore: update dependencies"
    )


def test_unrecognized_prefix_returns_none():
    assert derive_title_from_branch("random-branch-name") is None
    assert derive_title_from_branch("weirdprefix/some-change") is None


def test_should_normalize_when_title_equals_branch():
    assert should_normalize("feat/DEV-1-thing", "feat/DEV-1-thing") is True


def test_should_normalize_when_title_blank():
    assert should_normalize("feat/DEV-1-thing", "") is True


def test_should_not_normalize_meaningful_conventional_title():
    assert (
        should_normalize(
            "feat/DEV-1-thing", "feat(DEV-1): a completely different, better title"
        )
        is False
    )


def test_should_normalize_when_title_not_conventional():
    assert should_normalize("feat/DEV-1-thing", "WIP fix stuff") is True
