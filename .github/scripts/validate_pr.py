#!/usr/bin/env python3
"""Validate a Pull Request title and description against the repository's
PR template (.github/PULL_REQUEST_TEMPLATE.md).

Usage:
    validate_pr.py --title "feat(DEV-123): customer login" --body-file body.md
    validate_pr.py --title "..." < body.md

Exits 0 when the title and description are valid, 1 otherwise. On failure,
every problem found is printed to stderr so the developer can fix them all
in one pass instead of iterating one error at a time.
"""

import argparse
import re
import sys

ALLOWED_TYPES = (
    "feat",
    "fix",
    "docs",
    "refactor",
    "test",
    "chore",
    "ci",
    "build",
    "perf",
    "revert",
)

# type(scope): description  OR  type: description
TITLE_RE = re.compile(
    r"^(" + "|".join(ALLOWED_TYPES) + r")(\([\w.\-/]+\))?: \S.*$"
)

TYPE_CHECKBOX_RE = re.compile(r"^\s*-\s*\[( |x|X)\]\s*(.+?)\s*$")

REQUIRED_SECTIONS = ("details", "test plan", "type", "user impact", "release notes")

SUMMARY_START = "<!-- PR-AUTOMATION-SUMMARY:START -->"
SUMMARY_END = "<!-- PR-AUTOMATION-SUMMARY:END -->"


def strip_automation_summary(body: str) -> str:
    """Remove the auto-generated summary block before validating developer content."""
    start = body.find(SUMMARY_START)
    end = body.find(SUMMARY_END)
    if start != -1 and end != -1 and end > start:
        return body[:start] + body[end + len(SUMMARY_END):]
    return body


def strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def parse_sections(body: str) -> dict:
    """Split the PR body into {lowercase heading: raw content} by '## ' headings."""
    sections = {}
    current = None
    buf = []
    for line in body.splitlines():
        heading = re.match(r"^\s*##\s+(.+?)\s*$", line)
        if heading:
            if current is not None:
                sections[current] = "\n".join(buf)
            current = heading.group(1).strip().lower()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf)
    return sections


def is_effectively_empty(raw_content: str) -> bool:
    """True if content is blank, or only contains HTML comments/whitespace."""
    return strip_html_comments(raw_content).strip() == ""


def validate_title(title: str) -> list:
    errors = []
    if not title or not title.strip():
        errors.append("PR title is empty.")
        return errors
    if not TITLE_RE.match(title.strip()):
        errors.append(
            "PR title '{}' does not follow the required Conventional Commit "
            "format 'type(scope): description' or 'type: description'. "
            "Allowed types: {}.".format(title.strip(), ", ".join(ALLOWED_TYPES))
        )
    return errors


def validate_body(body: str) -> list:
    errors = []
    body = strip_automation_summary(body or "")
    sections = parse_sections(body)

    missing = [s for s in REQUIRED_SECTIONS if s not in sections]
    if missing:
        errors.append(
            "Missing required section(s): {}.".format(
                ", ".join(s.title() for s in missing)
            )
        )

    if "details" in sections and is_effectively_empty(sections["details"]):
        errors.append(
            "'Details' section is empty or only contains the placeholder comment. "
            "Explain what was changed and why."
        )

    if "test plan" in sections and is_effectively_empty(sections["test plan"]):
        errors.append(
            "'Test Plan' section is empty. Explain how the change was tested."
        )

    if "type" in sections:
        checked = []
        for line in sections["type"].splitlines():
            m = TYPE_CHECKBOX_RE.match(line)
            if m and m.group(1).lower() == "x":
                checked.append(m.group(2))
        if len(checked) == 0:
            errors.append("No 'Type' checkbox is selected. Select exactly one.")
        elif len(checked) > 1:
            errors.append(
                "Multiple 'Type' checkboxes are selected ({}). Select exactly one.".format(
                    ", ".join(checked)
                )
            )

    if "user impact" in sections:
        content = strip_html_comments(sections["user impact"]).strip()
        if content == "":
            errors.append(
                "'User Impact' section is empty. Describe the user impact or write N/A."
            )

    if "release notes" in sections:
        content = strip_html_comments(sections["release notes"]).strip()
        if content == "":
            errors.append(
                "'Release Notes' section is empty. Add release notes or write N/A."
            )

    return errors


def validate(title: str, body: str) -> list:
    return validate_title(title) + validate_body(body)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Pull request title")
    parser.add_argument(
        "--body-file",
        help="Path to a file containing the PR body. Defaults to stdin.",
    )
    args = parser.parse_args(argv)

    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as fh:
            body = fh.read()
    else:
        body = sys.stdin.read()

    errors = validate(args.title, body)

    if errors:
        print("PR validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("PR validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
