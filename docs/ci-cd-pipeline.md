# CI/CD Pipeline

This describes `.github/workflows/platform-ci.yml` (the main build/test/security/
Docker pipeline) and `.github/workflows/codeql.yml` (source-code scanning).
PR-only automation (title/description validation, labeling, Helm/Terraform
checks) is documented separately in
[`pull-request-automation.md`](pull-request-automation.md).

## Technology

- **Backend**: Python 3.10, FastAPI (`dabba/`), tested with `pytest`.
- **Frontend**: React + TypeScript, built with Vite (`frontend/`), tested
  with `vitest` and `playwright`.
- **Container**: multi-stage `Dockerfile` at the repo root — builds the
  frontend with `node:22-bookworm-slim`, then copies the static build output
  into a `python:3.10-slim` runtime image. Build context is the repo root
  (`.`). Exposes port `8080`, healthcheck on `/ready`.

## Triggers

Both workflows run on:

- `pull_request` (`opened`, `synchronize`, `reopened`, `ready_for_review`) targeting the default branch (`main`)
- `push` to `main`
- `workflow_dispatch` (manual run — Actions tab → select workflow → **Run workflow**)

`codeql.yml` additionally runs on a weekly schedule (Monday 06:00 UTC).

Draft PRs skip every job except metadata handling — the expensive
build/test/security/docker jobs only run once a PR is marked "ready for
review" (or for `push`/`workflow_dispatch`).

## Pipeline stages (`platform-ci.yml`)

```
format-check
   |
   v
backend / model / frontend   (build + unit tests, in parallel)
   |
   v
sonarqube  +  security        (in parallel)
   |
   v
docker-build
   |
   v
docker-scan
   |
   v
docker-push   (push events on main only)
   |
   v
summary       (always runs, reports every stage's result)
```

| Job | What it does |
| --- | --- |
| `format-check` | `black --check`, `ruff format --check`, `ruff check` against `dabba/`. |
| `backend` | Compiles `dabba/`, runs the non-model pytest suite with JUnit + coverage output, uploads both as artifacts. |
| `model` | Runs the torch-based model/training/RAG tests (heavier deps from `requirements.txt`). Not a dependency of `docker-build` — mirrors the pre-existing convention that this suite is isolated from the release path. |
| `frontend` | `npm run lint`, `npm audit --audit-level=high`, `vitest` (JUnit output), `npm run build`, Playwright e2e. |
| `sonarqube` | Static analysis + Quality Gate enforcement. Skips itself (with a `::notice::`) when `SONAR_TOKEN`/`SONAR_HOST_URL` aren't configured. |
| `security` | Gitleaks (push events only — PR events are already covered by `pr-validation.yml`), `pip-audit` against `requirements-server.txt` (blocking) and `requirements.txt` (report-only), Trivy config scan of the Dockerfile and Helm chart. |
| `docker-build` | Builds the image with Buildx (GHA cache), tagged but **not pushed**. Saved as a workflow artifact for the next job. |
| `docker-scan` | Trivy scan (vuln + secret + misconfig) of the built image. Report uploaded as an artifact. |
| `docker-push` | Only for `push` to `main` in this repository (not forks). Logs in to Docker Hub and pushes `latest` + short-SHA + semver tags. |
| `summary` | Always runs; writes a GitHub Actions job summary table with every stage's result and the resolved image tags. |

## Pull Request behaviour

- Runs `format-check` → `backend`/`model`/`frontend` → `sonarqube` → `security` → `docker-build` → `docker-scan`.
- **Does not** run `docker-push` — gated on `github.event_name == 'push'`.
- Fork PRs: `SONAR_TOKEN`/`DOCKERHUB_*` secrets are withheld by GitHub automatically; `sonarqube` degrades to a documented skip, and `docker-push` never runs for non-`push` events regardless.

## Default-branch (`main`) behaviour

- Runs every validation stage, then `docker-push`:
  - builds and pushes `<image>:<short-sha>` and `<image>:latest`.
  - also pushes semver tags (`X.Y.Z`, `X.Y`) when the commit is tagged `vX.Y.Z`.

## Manual runs

Actions tab → **Dabba Platform CI** (or **CodeQL**) → **Run workflow** → pick
a branch. `docker-push` will only actually push if that run is a `push` event
on `main` — a manual (`workflow_dispatch`) run builds and scans but does not
push, by design (the current gate is `github.event_name == 'push'`; broaden
this in `docker-push`'s `if` if manual pushes are ever wanted).

## Docker image naming and tags

Full image name: `${{ secrets.DOCKERHUB_USERNAME }}/${{ vars.DOCKERHUB_REPOSITORY }}`,
unless `DOCKERHUB_REPOSITORY` already contains a `/` (e.g. `hasheem/ecommerce-api`),
in which case it's used as-is without prefixing the username again. Falls
back to `dabba` if the variable is unset.

| Event | Tags produced |
| --- | --- |
| Push to `main` | `<image>:<short-sha>`, `<image>:latest` |
| Tag `vX.Y.Z` | `<image>:X.Y.Z`, `<image>:X.Y`, `<image>:latest` |
| Pull request (build+scan only, never pushed) | `<image>:pr-<number>` |
| Other branch / manual dispatch (build+scan only) | `<image>:<sanitized-branch-name>` |

Branch-name sanitization for the `type=ref,event=branch` tag is handled by
`docker/metadata-action`.

## Required GitHub Secrets

| Secret | Used by | Notes |
| --- | --- | --- |
| `DOCKERHUB_USERNAME` | `docker-build`, `docker-push` | Docker Hub username. |
| `DOCKERHUB_TOKEN` | `docker-push` | Docker Hub **access token**, not the account password. Create one at hub.docker.com → Account Settings → Security. |
| `SONAR_TOKEN` | `sonarqube` | SonarQube/SonarCloud analysis token. Omit to skip the job entirely (documented skip, not a failure). |
| `SONAR_HOST_URL` | `sonarqube` | Only needed if you don't set the `SONAR_HOST_URL` **variable** instead (see below); SonarCloud users can set this to `https://sonarcloud.io`. |

## Required/optional GitHub Variables

| Variable | Used by | Default if unset |
| --- | --- | --- |
| `DOCKERHUB_REPOSITORY` | `docker-build`, `docker-push` | `dabba` |
| `SONAR_PROJECT_KEY` | `sonarqube` | `dabba` |
| `SONAR_HOST_URL` | `sonarqube` | (falls back to the `SONAR_HOST_URL` secret if set as a variable is not) |

Set these under **Settings → Secrets and variables → Actions** (Secrets tab
for secrets, Variables tab for variables).

## SonarQube configuration

`sonar-project.properties` at the repo root is a documented placeholder — no
SonarQube server is provisioned for this repository today. To turn it on:

1. Provision a SonarQube (self-hosted) or SonarCloud project.
2. Set the `SONAR_TOKEN` secret and either the `SONAR_HOST_URL` secret/variable
   (self-hosted) or set it to `https://sonarcloud.io` (SonarCloud).
3. Optionally set `SONAR_PROJECT_KEY` if it should differ from `dabba`.
4. Configure the Quality Gate conditions in the SonarQube/SonarCloud UI — the
   `sonarqube` job enforces whatever gate is configured there via
   `sonarqube-quality-gate-action`.

Only Python coverage (`backend`'s `pytest-cov` output) is wired into Sonar
today. JS/TS coverage isn't collected because `frontend/package.json` doesn't
have `@vitest/coverage-v8` installed — see "Known gaps" below.

## Security scan policy

- **Secrets** (Gitleaks): any finding fails the job.
- **Dependencies** (`pip-audit`, `npm audit --audit-level=high`): fails on
  `requirements-server.txt` (shipped in the runtime image) and on frontend
  `high`/`critical` findings. `requirements.txt` (training-only deps, never
  shipped in the image) is reported but does not block.
- **Config** (Trivy, `scan-type: config` against the Dockerfile and Helm
  chart) and **image** (Trivy, `scanners: vuln,secret,misconfig` against the
  built image): fails on any unfixed `CRITICAL` or `HIGH` finding. Add
  accepted findings with justification and a review date to `.trivyignore`
  — never a blanket ignore.
- **Source code** (CodeQL, `codeql.yml`): findings are meant to surface in
  the repo's Security tab; this workflow does not currently fail the build
  on findings (CodeQL doesn't gate merges by default — pair it with a branch
  protection rule requiring the CodeQL check if you want it to block).
  **This repository is currently private without code scanning/GitHub
  Advanced Security enabled**, so the SARIF upload 403s with "Code scanning
  is not enabled for this repository" — a repo Settings toggle, not
  something a workflow file can fix. The `Perform CodeQL analysis` step uses
  `continue-on-error: true` so that doesn't fail the job; the SARIF is still
  produced and uploaded as a `codeql-sarif-<language>` build artifact so
  findings aren't silently lost. Enable **Settings → Security → Code
  security and analysis → Code scanning** (requires GitHub Advanced Security
  for private repos, or make the repo public) to get results in the
  Security tab automatically — no workflow change needed once that's on.

## Troubleshooting common failures

| Symptom | Likely cause |
| --- | --- |
| `format-check` fails with many `black`/`ruff format` diffs | Pre-existing formatting debt (142/177 files as of this writing) — this task did not bulk-reformat the codebase (out of scope; would be a large, unrelated diff). Run `black dabba && ruff format dabba` in a dedicated PR to clear it. |
| `frontend` fails at "Lint (eslint)" with `eslint: not found` | `eslint` is referenced by `npm run lint` but is not currently a `devDependency` in `frontend/package.json`. Add `eslint` + a flat config (`eslint.config.js`) as a dedicated frontend change. |
| `frontend` fails `npm audit --audit-level=high` | Real vulnerable transitive deps (e.g. `dompurify`, `postcss`) as of this writing. Run `npm audit fix` (or `--force` for breaking upgrades) in a frontend-focused PR. |
| `sonarqube` shows "SonarQube is not configured" notice | Expected until `SONAR_TOKEN`/`SONAR_HOST_URL` are set — see above. |
| `docker-push` fails "DOCKERHUB_USERNAME and/or DOCKERHUB_TOKEN ... not set" | Add both secrets under Settings → Secrets and variables → Actions. |
| `docker-push` never ran on a PR | By design — pushes only happen on `push` to `main` in this repository. |
| `security` fails on `requirements.txt` pip-audit | Non-blocking by design (see policy above) — check the `::warning::` in the job log for the specific package/CVE. |
| `pr-validation.yml`'s `secret-scan` fails with `403 Resource not accessible by integration` | `gitleaks-action` calls `GET /pulls/:number/commits`, which needs `pull-requests: read` on the job's token. Already fixed — the job now grants it explicitly. |
| `codeql.yml` fails with `Code scanning is not enabled for this repository` | Repo-settings/GHAS gap, not a workflow bug — see the Security scan policy section above. The job stays green (`continue-on-error`) and still uploads the SARIF as an artifact. |
| `validate-description` keeps failing on a PR's own title/body even after `pr-metadata.yml` should have fixed it | Check whether `pr-metadata.yml` has actually run at all (`gh run list` — look for a "PR Metadata Automation" entry). It uses `pull_request_target`, which GitHub always runs using the **base branch's** copy of the workflow file — a PR that introduces or changes `pr-metadata.yml` itself can't benefit from those changes (or from the workflow existing at all, the first time it's added) until merged to `main`. This is a one-time bootstrapping gap, not a bug to fix in the workflow. |
| Every job shows a `##[warning] The process '/usr/bin/git' failed with exit code 128` / `fatal: No url found for submodule path 'llama.cpp' in .gitmodules` annotation | Pre-existing repo issue, unrelated to any specific workflow: `llama.cpp` is committed as a git **gitlink** (mode `160000`, i.e. as if it were a submodule) but there is no `.gitmodules` file defining its URL anywhere in history (`git ls-tree HEAD llama.cpp` shows the gitlink; `git log --all -- .gitmodules` is empty). `actions/checkout`'s post-job cleanup runs `git submodule foreach` and hits this on every job, on every workflow — it's a harmless warning (jobs still succeed), not a task failure, but worth a deliberate fix: either add a real `.gitmodules` entry for it, or `git rm --cached llama.cpp && git add llama.cpp` to commit it as normal files instead (recommended, since **the current setup means a fresh clone gets an empty `llama.cpp/` directory** — it isn't actually version-controlled today). Out of scope for this task since it doesn't fail any check; flagged here for a deliberate follow-up decision.

## Known gaps (not fixed by this task — out of scope for a CI setup change)

- Frontend has no working lint tool installed (`eslint` missing from
  `package.json`).
- Frontend has no code-coverage tool installed (`@vitest/coverage-v8`
  missing), so `sonar.javascript.lcov.reportPaths` isn't set.
- 142 of 177 Python files and most of the frontend are not currently
  formatted per `black`/`ruff format` — `format-check` will fail against the
  current codebase until a dedicated formatting pass lands.
- No SonarQube server is provisioned yet — `sonarqube` runs as a documented
  no-op until secrets are configured.
- CodeQL results appear in the Security tab but don't currently block merges
  — add a branch protection rule if that's desired.
