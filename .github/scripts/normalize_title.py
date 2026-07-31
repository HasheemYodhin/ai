#!/usr/bin/env python3
"""Derive a Conventional Commit-style PR title from a source branch name.

Used by .github/workflows/pr-metadata.yml to fix up generic PR titles
(titles left as the GitHub default, equal to the raw branch name, or that
don't already follow the required format) without touching a title a
developer already wrote deliberately.

Usage:
    normalize_title.py --branch "feat/DEV-123-customer-login" --title "feat/DEV-123-customer-login"

Prints the normalized title on success, or nothing (exit 0) when the
current title should be left alone.
"""

import argparse
import re
import sys

from validate_pr import ALLOWED_TYPES, TITLE_RE

# Same shape as validate_pr.TITLE_RE but case-insensitive, used only to
# detect titles that are conventional *except* for the type's letter case
# (e.g. "Feat: thing", "FIX(DEV-1): thing") so those can have just the type
# lowercased instead of being discarded and re-derived from the branch name.
TITLE_RE_CI = re.compile(TITLE_RE.pattern, re.IGNORECASE)

# Branch-prefix -> Conventional Commit type.
PREFIX_TO_TYPE = {
    "feature": "feat",
    "feat": "feat",
    "bugfix": "fix",
    "fix": "fix",
    "hotfix": "fix",
    "chore": "chore",
    "docs": "docs",
    "refactor": "refactor",
    "test": "test",
    "ci": "ci",
    "build": "build",
    "perf": "perf",
    "revert": "revert",
}

TICKET_RE = re.compile(r"^([A-Za-z]+-\d+)-(.+)$")


def is_conventional(title: str) -> bool:
    return bool(TITLE_RE.match((title or "").strip()))


def derive_title_from_branch(branch: str):
    """Return a normalized title for `branch`, or None if the branch doesn't
    match a recognized `<prefix>/<...>` naming convention."""
    if "/" not in branch:
        return None
    prefix, rest = branch.split("/", 1)
    commit_type = PREFIX_TO_TYPE.get(prefix.lower())
    if not commit_type or not rest:
        return None

    ticket_match = TICKET_RE.match(rest)
    if ticket_match:
        scope, slug = ticket_match.group(1), ticket_match.group(2)
    else:
        scope, slug = None, rest

    slug = slug.strip("-")
    if not slug:
        return None
    description = slug.replace("-", " ").replace("_", " ").strip()
    if not description:
        return None

    if scope:
        return f"{commit_type}({scope.upper()}): {description}"
    return f"{commit_type}: {description}"


def lowercase_type_if_close_match(title: str):
    """If `title` already has the Conventional Commit shape except that its
    type is the wrong letter-case (e.g. "Feat: thing", "FIX(DEV-1): thing"),
    return it with just the type lowercased — preserving the scope and
    description exactly as the developer wrote them.

    Returns None when there's nothing to fix: the title is blank, already
    matches case-sensitively, or doesn't match the Conventional Commit shape
    at all (in which case the branch-derived fallback in `main` applies
    instead). Types must always be lowercase in the final title.
    """
    stripped = (title or "").strip()
    if not stripped:
        return None
    match = TITLE_RE_CI.match(stripped)
    if not match:
        return None
    matched_type = match.group(1)
    if matched_type in ALLOWED_TYPES:
        return None  # already correct case
    lowered = matched_type.lower()
    if lowered not in ALLOWED_TYPES:
        return None
    return lowered + stripped[len(matched_type) :]


def should_normalize(branch: str, current_title: str) -> bool:
    """Only normalize generic titles: the default GitHub title (== branch
    name), blank, or not already in the required Conventional Commit format.
    A title a developer wrote by hand that already matches the required
    format is left untouched, even if it happens to differ from the
    branch-derived one."""
    current_title = (current_title or "").strip()
    if current_title == "":
        return True
    if current_title == branch.strip():
        return True
    if not is_conventional(current_title):
        return True
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True, help="Source (head) branch name")
    parser.add_argument("--title", required=True, help="Current PR title")
    args = parser.parse_args(argv)

    # A title that's conventional except for the type's case just needs that
    # one fix, in place — never discard a developer-written title and
    # re-derive it from the branch name just because of letter-casing.
    case_fixed = lowercase_type_if_close_match(args.title)
    if case_fixed is not None:
        print(case_fixed)
        return 0

    if not should_normalize(args.branch, args.title):
        return 0

    new_title = derive_title_from_branch(args.branch)
    if new_title:
        print(new_title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
