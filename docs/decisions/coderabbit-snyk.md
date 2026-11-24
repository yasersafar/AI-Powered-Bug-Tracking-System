# CodeRabbit and Snyk in the development workflow

Both tools check the team's **source code during development**. Neither is ever called by
the running system, so no bug report or user data reaches them (DC-03 is about runtime data).

## Where they sit

```
feature branch --push--> pull request on GitHub
                              |-- GitHub Actions: CI (.github/workflows/ci.yml)
                              |     backend: ruff, mypy --strict, alembic check, pytest + coverage >= 70%
                              |     ml: ruff, mypy, pytest
                              |     extension: eslint, tsc, prettier, VS Code tests, .vsix
                              |     compose: docker compose config
                              |-- Security workflow: Snyk (.github/workflows/security.yml)
                              |-- CodeRabbit: AI review comments on the diff (.coderabbit.yaml)
                              `-- human review by another team member -> merge to main
```

| | CodeRabbit | Snyk |
|---|---|---|
| Role | AI code review of every pull request: summary, line comments, project-specific checks | Security scanning: known vulnerabilities in dependencies (SCA) and insecure code patterns (SAST) |
| Trigger | Pull requests against `main` (not drafts) | Every pull request, every push to `main`, weekly (Monday 06:00 UTC) for newly published CVEs, and manually |
| Configuration | `.coderabbit.yaml` | `.github/workflows/security.yml` |
| Blocks a merge? | No (`request_changes_workflow: false`); comments are advice, the human reviewer decides | The job fails on high or critical findings; branch protection can make it required |
| One-time setup | Install the CodeRabbit GitHub App on the repository | Add the repository secret `SNYK_TOKEN`; without it the job is skipped with a notice |

## Configuration used

**CodeRabbit** (`.coderabbit.yaml`):
* Profile `chill`, review summary kept inside CodeRabbit's walkthrough comment (the PR
  description stays written by the team), no poem, generated files excluded
  (`package-lock.json`, `docs/openapi.json`, `docs/results/**`, images).
* Path instructions that turn our requirements into review checks:
  backend (403 for other projects' data, Pydantic validation, audit log, 409 on invalid
  transitions, no secrets), backend tests (must be able to fail), ML (no external AI API,
  no tuning on the test split, no hard-coded metrics), extension (JWT only in
  SecretStorage, CSP, no remote scripts, theme variables, WCAG 2.1 AA).
* Linters run by CodeRabbit: ruff, eslint, gitleaks (secret detection), hadolint
  (Dockerfile), yamllint, actionlint, markdownlint.

**Snyk** (`.github/workflows/security.yml`):
* `snyk test` on `backend/pyproject.toml`, `ml/requirements.txt` (the triage models run in
  the backend) and `extension/package-lock.json`, failing at severity `high`.
* `snyk code test` (static analysis of the Python and TypeScript sources), failing at `high`.
* Read-only repository permissions.

## Why both

They answer different questions: CodeRabbit "is this change correct and does it follow our
rules?", Snyk "does this change or its dependencies bring a known security problem?". The
automated tests and linters in CI remain the hard gate; the human reviewer from another
team member is the final approval (supervisor requirement: each member's contribution is
visible through their own pushes and reviews).
