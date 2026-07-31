import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_pr import validate, validate_title, validate_body  # noqa: E402


VALID_TITLE = "feat(DEV-123): customer login"

VALID_BODY = """
## Details

Adds a new login flow for customers using the DEV-123 ticket requirements.

## Test Plan

Ran the backend pytest suite and manually logged in via the staging UI.

## Type

Select exactly one:

- [ ] Feature
- [x] Fix
- [ ] Breaking Change
- [ ] Chore
- [ ] Documentation
- [ ] Refactor

## User Impact

Customers can now log in with their email instead of a username.

## Release Notes

Added email-based login.
"""


def test_valid_pr_passes():
    assert validate(VALID_TITLE, VALID_BODY) == []


def test_valid_pr_with_na_user_impact_and_release_notes():
    body = VALID_BODY.replace(
        "Customers can now log in with their email instead of a username.",
        "N/A",
    ).replace("Added email-based login.", "N/A")
    assert validate(VALID_TITLE, body) == []


def test_missing_details_section_fails():
    body = VALID_BODY.replace(
        "## Details\n\nAdds a new login flow for customers using the DEV-123 ticket requirements.\n",
        "",
    )
    errors = validate_body(body)
    assert any("Missing required section" in e and "Details" in e for e in errors)


def test_empty_details_placeholder_only_fails():
    body = VALID_BODY.replace(
        "Adds a new login flow for customers using the DEV-123 ticket requirements.",
        "<!-- Explain what was changed and why -->",
    )
    errors = validate_body(body)
    assert any("'Details'" in e for e in errors)


def test_empty_test_plan_fails():
    body = VALID_BODY.replace(
        "Ran the backend pytest suite and manually logged in via the staging UI.",
        "",
    )
    errors = validate_body(body)
    assert any("'Test Plan'" in e for e in errors)


def test_no_type_selected_fails():
    body = VALID_BODY.replace("- [x] Fix", "- [ ] Fix")
    errors = validate_body(body)
    assert any("No 'Type' checkbox" in e for e in errors)


def test_multiple_types_selected_fails():
    body = VALID_BODY.replace("- [ ] Chore", "- [x] Chore")
    errors = validate_body(body)
    assert any("Multiple 'Type' checkboxes" in e for e in errors)


def test_empty_user_impact_fails():
    body = VALID_BODY.replace(
        "Customers can now log in with their email instead of a username.",
        "",
    )
    errors = validate_body(body)
    assert any("'User Impact'" in e for e in errors)


def test_empty_release_notes_fails():
    body = VALID_BODY.replace("Added email-based login.", "")
    errors = validate_body(body)
    assert any("'Release Notes'" in e for e in errors)


def test_invalid_title_format_fails():
    errors = validate_title("Fix payment timeout")
    assert len(errors) == 1
    assert "Conventional Commit" in errors[0]


def test_invalid_title_type_fails():
    errors = validate_title("feature(DEV-1): oops")
    assert errors


def test_valid_title_without_scope_passes():
    assert validate_title("chore: update dependencies") == []


def test_automation_summary_block_is_ignored_by_validation():
    body = VALID_BODY + (
        "\n<!-- PR-AUTOMATION-SUMMARY:START -->\n"
        "## Automated Summary\n\n- Source branch: feat/DEV-123-customer-login\n"
        "<!-- PR-AUTOMATION-SUMMARY:END -->\n"
    )
    assert validate_body(body) == []


def test_empty_body_fails_with_all_missing_sections():
    errors = validate_body("")
    assert any("Missing required section" in e for e in errors)
