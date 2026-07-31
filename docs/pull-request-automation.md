# Pull Request Automation

This document describes the automated PR checks in this repository and the
repository settings a **repository administrator** still needs to configure
by hand — GitHub does not allow branch protection or repo-wide settings to
be fully managed from committed workflow files.

## What's automated

| File | Purpose |
| --- | --- |
| [`.github/PULL_REQUEST_TEMPLATE.md`](../.github/PULL_REQUEST_TEMPLATE.md) | Structured PR description template (Details, Test Plan, Type, User Impact, Release Notes). |
| [`.github/workflows/pr-metadata.yml`](../.github/workflows/pr-metadata.yml) | Normalizes generic PR titles, injects an automated summary, applies file/title-based labels. Runs with write access (`pull_request_target`) but never checks out or executes PR code. |
| [`.github/workflows/pr-validation.yml`](../.github/workflows/pr-validation.yml) | Blocking validation: PR title/description format, secret scanning, and conditional Helm/Kubernetes/Terraform checks. Runs as unprivileged `pull_request`. |
| [`.github/workflows/platform-ci.yml`](../.github/workflows/platform-ci.yml) | Existing build/test/Docker-build pipeline, extended to run on `edited`/`ready_for_review` and to skip its expensive jobs while a PR is a draft. |
| [`.github/labeler.yml`](../.github/labeler.yml) | File-path → label rules used by `pr-metadata.yml`. |
| [`.github/CODEOWNERS`](../.github/CODEOWNERS) | Documented example only — every rule is commented out pending real owner names (see below). |
| [`.github/scripts/validate_pr.py`](../.github/scripts/validate_pr.py) | Title + description validation logic, unit tested in `test_validate_pr.py`. |
| [`.github/scripts/normalize_title.py`](../.github/scripts/normalize_title.py) | Branch-name → Conventional Commit title logic, unit tested in `test_normalize_title.py`. |
| [`.github/scripts/check_k8s_manifests.py`](../.github/scripts/check_k8s_manifests.py) | Checks rendered Kubernetes manifests for resource requests/limits, security context, image tags, and privileged containers. Used against `helm template` output since this repo has a Helm chart but no raw `k8s/`/`kubernetes/` manifests. |

## Pull Request events handled

Both `pr-metadata.yml` and `pr-validation.yml` (and now `platform-ci.yml`) run
on: `opened`, `edited`, `synchronize`, `reopened`, `ready_for_review`.

## Checks that run for every PR

- Title/description validation (`pr-validation.yml` → `validate-description`)
- Secret scanning of the PR diff (`pr-validation.yml` → `secret-scan`, via
  [gitleaks](https://github.com/gitleaks/gitleaks-action))
- Title normalization, automated summary, and labeling (`pr-metadata.yml`)
- Backend + model pytest suites, frontend lint/test/build/E2E, `npm audit`,
  and a non-pushed Docker build (`platform-ci.yml`) — skipped while the PR
  is a draft

## Checks that run only for specific file changes

Detected by `pr-validation.yml` → `detect-changes` (diffing the PR's base
and head SHAs):

- **Helm** (`helm/**`, `charts/**`): `helm lint`, `helm template`, then
  `check_k8s_manifests.py` against the rendered output.
- **Kubernetes** (`k8s/**`, `kubernetes/**`): YAML syntax check +
  `check_k8s_manifests.py`. Kept ready for when raw manifests are added —
  none exist in this repository today (only the Helm chart under `helm/`).
- **Terraform** (`**/*.tf`, `terraform/**`): `terraform fmt -check`,
  `terraform init -backend=false`, `terraform validate`. Kept ready for
  when Terraform is added — **none exists in this repository today**, so
  this job never currently runs.
  - `terraform plan` is intentionally **not** wired up: this repo has no
    trusted, read-only cloud credentials configured for CI, and running
    `plan` against real infrastructure credentials from a PR workflow is a
    credential-exfiltration risk for fork PRs. Add it only after setting up
    a dedicated, read-only, environment-scoped credential and an OIDC-based
    trust boundary.
  - No Checkov/tfsec/Trivy-config job was added for the same reason
    (nothing to scan yet, and no such tool exists elsewhere in this repo to
    reuse). Add one alongside the first `.tf` files.
- **Docker**: already covered unconditionally by `platform-ci.yml`'s
  `docker` job (`docker/build-push-action` with `push: false`, using the
  real root `Dockerfile`) — not duplicated here.

## Required secrets, variables, labels, and team names

- **Secrets**: none new. `pr-metadata.yml` and `pr-validation.yml` only use
  the automatically provided `secrets.GITHUB_TOKEN`. (`docker-build-push.yml`,
  unrelated to PRs, already uses `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN`.)
- **Labels** an administrator must create once (workflows will emit a
  `::warning::` and continue if a label is missing, rather than failing the
  whole run):
  `terraform`, `kubernetes`, `docker`, `github-actions`, `documentation`,
  `testing`, `database`, `security`, `feature`, `bug`, `maintenance`,
  `refactor`.
- **Teams/usernames**: none invented. `.github/CODEOWNERS` ships fully
  commented out with `@TODO-*` placeholders — see below.

## CODEOWNERS — action required

No ownership information (GitHub usernames or teams) exists anywhere in
this repository, so `.github/CODEOWNERS` is a documented example with every
line commented out. An administrator must:

1. Replace each `@TODO-*` placeholder with a real GitHub username or an
   existing `@HasheemYodhin/<team-slug>` team.
2. Uncomment the corresponding line.
3. Enable "Require review from Code Owners" in branch protection (below) if
   Code Owner approval should be enforced.

## Manual GitHub repository settings still required

These cannot be set from files in the repository and must be configured by
an administrator under **Settings → Branches → Branch protection rules**
for the default branch (`main`):

- [ ] Require a pull request before merging (blocks direct pushes to `main`).
- [ ] Require at least 1 approval.
- [ ] Require review from Code Owners (once `.github/CODEOWNERS` has real
      owners — see above).
- [ ] Require status checks to pass before merging, and select at least:
      - `validate-description` (from `pr-validation.yml`)
      - `secret-scan` (from `pr-validation.yml`)
      - `backend`, `model`, `frontend`, `docker` (from `platform-ci.yml`)
      - `helm-validate` / `k8s-validate` / `terraform-validate` if you want
        these enforced even though they currently only run conditionally
- [ ] Require branches to be up to date before merging (recommended if the
      test suite is sensitive to base-branch drift).
- [ ] Require conversation resolution before merging.
- [ ] Do not allow bypassing the above rules (including for administrators),
      unless a specific, documented exception is needed.
- [ ] Automatically delete head branches after a PR is merged (**Settings →
      General → Pull Requests**, not a branch protection setting).

This automation was implemented without changing any live repository
settings — no branch protection rule, label, or team was created or
modified remotely.

## Known limitations / TODOs

- `.github/CODEOWNERS` has no active owners yet (placeholders only).
- Terraform and raw Kubernetes-manifest jobs are wired up but have nothing
  to validate yet, since this repo currently only has a Helm chart.
- `terraform plan` is deliberately not implemented (see above).
- No SonarQube configuration exists in this repository, so none was added
  or invoked; if one is introduced later, wire it into `pr-validation.yml`
  as a conditional job rather than duplicating `platform-ci.yml`'s tests.
- Labels referenced by `pr-metadata.yml` must be created once by an
  administrator (see the list above) — missing labels only produce a
  warning, they do not fail the PR.
