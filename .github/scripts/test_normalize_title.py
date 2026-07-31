import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from normalize_title import (  # noqa: E402
    derive_title_from_branch,
    lowercase_type_if_close_match,
    should_normalize,
)


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


# --- Generic branch names without a ticket segment (e.g. "feat/firstbranch") ---


def test_feat_branch_without_ticket_or_separators():
    # No hyphen/underscore in the remainder to split on, so the description
    # stays a single word — still a valid Conventional Commit title (the
    # regex only requires `type: <non-empty text>`, not multiple words).
    assert derive_title_from_branch("feat/firstbranch") == "feat: firstbranch"


def test_capitalized_prefix_branch_is_case_insensitive():
    # Mirrors GitHub's default PR title, which is literally the branch name
    # (e.g. "Feat/firstbranch") — the prefix lookup must not be case-sensitive.
    assert derive_title_from_branch("Feat/firstbranch") == "feat: firstbranch"


def test_should_normalize_default_title_with_capitalized_branch():
    assert should_normalize("Feat/firstbranch", "Feat/firstbranch") is True


# --- lowercase_type_if_close_match: fix case without discarding content ---


def test_lowercase_type_if_close_match_fixes_uppercase_type():
    assert (
        lowercase_type_if_close_match("Feat: a completely custom title")
        == "feat: a completely custom title"
    )


def test_lowercase_type_if_close_match_fixes_uppercase_type_with_scope():
    assert (
        lowercase_type_if_close_match("FIX(DEV-123): payment timeout")
        == "fix(DEV-123): payment timeout"
    )


def test_lowercase_type_if_close_match_leaves_already_lowercase_alone():
    assert lowercase_type_if_close_match("feat(DEV-1): thing") is None


def test_lowercase_type_if_close_match_returns_none_for_non_conventional():
    assert lowercase_type_if_close_match("WIP fix stuff") is None


def test_lowercase_type_if_close_match_returns_none_for_blank():
    assert lowercase_type_if_close_match("") is None
    assert lowercase_type_if_close_match(None) is None


def test_lowercase_type_if_close_match_returns_none_for_unknown_type():
    # "Featuring" isn't in ALLOWED_TYPES even lowercased — must not be
    # mistaken for a case-only variant of "feat".
    assert lowercase_type_if_close_match("Featuring: something") is None
