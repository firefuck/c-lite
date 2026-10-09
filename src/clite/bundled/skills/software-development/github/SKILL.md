---
name: github
description: "Work GitHub end to end with the gh CLI: auth, issues, the pull-request lifecycle, reviews and repo management. Use when the task touches a GitHub repository's remote state."
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    category: software-development
    tags: [github, gh, pull-requests, issues, code-review, ci]
    attribution: "Adapted from the github skill in Nous Research's hermes-agent (skills/software-development/github, MIT, Copyright (c) 2025 Nous Research), itself consolidating work by Ben Barclay."
---

# GitHub

Drive a repository's remote state with the `gh` CLI: authenticate, file and triage issues, take a change through the pull-request lifecycle, review another person's PR, and manage repos, releases and CI. Every command here runs in `terminal`. Reach for `gh` porcelain first; drop to `gh api` only for endpoints it does not expose.

## When to use

- The task touches a GitHub remote: pushing a branch, opening or merging a PR, filing or triaging an issue, reviewing a PR, cutting a release.
- CI is red and you need the failing log, or you were asked to get a PR green.
- Auth is broken: no push, `403` on API calls, or `git push` asking for a password.

Local-only work (branching, committing, diffing) does not need this skill.

## Read before you claim

These hold in every workflow below.

- Never say a check is green without reading `gh pr checks` yourself.
- Never say a PR merged without reading its `state` and `mergedAt`.
- Read the thread, not the title: `gh issue view N --comments`, `gh pr view N --comments`. Decisions live in comments.
- Search before creating: `gh issue list --search`, `gh pr list --search`.
- When you report remote state, paste the command and its output; do not narrate from memory.

## Preflight

Run once per session, before any workflow.

```bash
gh auth status
```

If it prints a logged-in account, proceed. If it fails:

- Not logged in interactively: `gh auth login`.
- Headless or SSH box with a token: `printf '%s' "$GH_TOKEN" | gh auth login --with-token && gh auth setup-git`.
- No `gh`, no sudo: fall back to `git` over HTTPS — `git config --global credential.helper store`, then one `git ls-remote` to store the token as the password. Export `GH_TOKEN` (a classic PAT with `repo`, `workflow`, `read:org`) for API calls and for `gh` to pick up automatically.
- `remote: Permission to X denied`, or `404` on a private repo: the token lacks `repo` scope, or you are not a collaborator. Regenerate with `repo`; for a fork, confirm the push goes to your fork.
- SSH refused on port 22: use `ssh.github.com` on port `443`, or switch to HTTPS.

## Routing

| Task | Section |
|---|---|
| Branch, commit, open a PR, watch CI, merge | The pull-request lifecycle |
| File, list, triage, label, assign or close an issue | Issues |
| Review someone else's PR | Reviewing a pull request |
| Commit messages and PR bodies | Commits and PR bodies |
| Clone, fork, remotes, releases | Repositories |
| A red CI run | CI troubleshooting |
| An endpoint the porcelain lacks | gh api cheatsheet |

## The pull-request lifecycle

```bash
git fetch origin && git checkout main && git pull     # start clean
git checkout -b fix/login-redirect                    # branch: feat/ fix/ refactor/ docs/ ci/
# edit files with write_file / patch
git add src/auth/login.py tests/test_login.py
git commit -m "fix: preserve ?next= after login"      # see Commits and PR bodies
git push -u origin HEAD
gh pr create --title "fix: preserve ?next= after login" \
  --reviewer teammate --label bug --draft \
  --body "$(cat <<'EOF'
## Summary
- Keeps ?next= instead of always landing on /dashboard.

Closes #42
EOF
)"
```

```bash
gh pr checks --watch                 # polls until every check finishes
gh pr checks                         # one-shot: read the exit state, do not assume
gh pr merge --squash --delete-branch
gh pr merge --auto --squash --delete-branch   # merge as soon as checks pass
```

Never merge past a red check. If checks fail, go to CI troubleshooting, fix, push, and watch again — about three attempts, then ask the user.

## Issues

Search for a duplicate before creating anything:

```bash
gh issue list --search "login redirect" --state all
gh issue create --title "Login redirect ignores ?next=" \
  --label bug,backend --assignee username \
  --body "$(cat <<'EOF'
## Description
After login, users always land on /dashboard.

## Steps to reproduce
1. Open /settings while logged out
2. Log in

## Expected
Respect ?next=.
EOF
)"
```

List and read: `gh issue list --state open --label bug`, `gh issue list --assignee @me`, `gh issue view 42 --comments`. Triage: `gh issue edit 42 --add-label priority:high --remove-label needs-triage`, `gh issue edit 42 --add-assignee @me`, `gh issue comment 42 --body "..."`. Run `gh label list` first so you only use labels the repo has.

Close and link: `gh issue close 42 --reason "not planned"`. A PR body containing `Closes #42` (also `Fixes`, `Resolves`) closes the issue on merge. `gh issue develop 42 --checkout` branches straight from an issue.

## Reviewing a pull request

```bash
gh pr view 123 --comments            # title, body, discussion
gh pr diff 123 --name-only           # scope first
gh pr checkout 123                   # then read files with read_file / search_files
```

Read the whole diff, then open the changed files — a diff alone hides surrounding context. Check correctness and edge cases, security (secrets, injection, missing authz), tests, and naming; run the project's test and lint commands in `terminal`.

```bash
gh pr review 123 --comment --body "Some suggestions, nothing blocking."
gh pr review 123 --approve --body "LGTM — good coverage."
gh pr review 123 --request-changes --body "See inline comments."
```

`--approve` when nothing is blocking, `--request-changes` for any correctness or security issue that must be fixed first, `--comment` for observations only. After checking out a PR, return and clean up: `git checkout main && git branch -D pr-123`.

## Commits and PR bodies

Conventional Commits: `type(scope): description`; wrap the body at 72 characters.

| Type | For |
|---|---|
| `feat` | new capability |
| `fix` | bug fix |
| `refactor` | restructuring, no behaviour change |
| `docs` | documentation |
| `test` | tests |

Types you will also see: `ci` (CI/CD config), `chore` (deps, tooling), `perf` (faster code). `!` after the type, or a `BREAKING CHANGE:` footer, marks a breaking change: `feat(api)!: require bearer tokens`.

A good PR body carries: a bullet summary of what changed, why it is needed (link the issue with `Closes #N`), how it was tested, and anything a reviewer should look at. A good bug report carries: description, steps to reproduce, expected vs actual, environment.

## Repositories

```bash
gh repo clone owner/repo -- --depth 1        # gh repo clone o/r is the shorthand
gh repo fork owner/repo --clone              # adds upstream; sync it as below
git fetch upstream && git checkout main && git merge upstream/main
gh repo create name --private --description "..." --clone
gh release create v1.0.0 --generate-notes    # add --draft --prerelease for a candidate
```

A fork keeps the original at `upstream` and your copy at `origin`; check `git remote -v` before pushing so the branch does not land upstream. Releases are a tag plus notes and optional assets — cut them from a clean, green `main`.

## CI troubleshooting

Read the failing log before guessing.

```bash
gh run list --branch "$(git branch --show-current)" --limit 5
gh run view <RUN_ID> --log-failed
gh run rerun <RUN_ID> --failed         # retry a flake, or rerun once the fix is pushed
gh pr checks                           # confirm the new run, do not assume
```

Signatures worth naming, and the usual fix:

- `FAILED tests/...` or `ModuleNotFoundError` — a real logic change, or a dependency missing from the manifest.
- `E501 line too long`, `would reformat` — run the formatter (`ruff format`, `black`, `isort`) and push the result.
- `error: ... incompatible type` (mypy/pyright) — fix the type or signature; `# type: ignore` only with a reason.
- `Resource not accessible by integration` / `403` — the workflow needs a `permissions:` block, or a secret a fork PR cannot see.
- `has exceeded the maximum execution time` — a hung step; add `timeout-minutes` and fix the underlying hang.

After a fix: `git add <files> && git commit -m "fix: resolve CI failure in <check>" && git push`, then watch the new run.

## gh api cheatsheet

`gh api` adds auth and fills `{owner}/{repo}` from the current repo; `-f` sends a string field, `-F` a typed one, and `--jq` filters the response.

```bash
gh api repos/{owner}/{repo}/pulls/123/comments --method POST \
  -f body="Simplify with a list comprehension." \
  -f path="src/auth.py" -f commit_id="$(gh pr view 123 --json headRefOid --jq .headRefOid)" \
  -F line=45 -f side=RIGHT
```

Endpoints the porcelain lacks: `GET /repos/{o}/{r}/branches/main/protection` (`PUT` to set it), `.../actions/workflows`, `.../commits/{sha}/check-runs`, `.../actions/secrets`, and `GET /rate_limit` for remaining quota. Add `--paginate` for list endpoints that span pages.

## Pitfalls

- Reporting success from memory. A running check, a passing check and a cancelled one look different; read the state.
- Pushing onto a fork's upstream remote. Check `git remote -v`; your branch belongs on `origin`.
- Opening a PR against the wrong base (`main` vs `develop`), or from a stale branch. Fetch and rebase first.
- Committing a token, `.netrc` or `.env`. Grep the staged diff before pushing.
- Inventing label or reviewer names; run `gh label list` or `gh api user` first.
- `gh auth login` hanging in a headless shell. Use `--with-token` with `GH_TOKEN` set, then `gh auth setup-git`.
- Merging on green while branch protection still wants a review — the merge is refused.

## Verification

Before you report a GitHub workflow done, confirm:

- [ ] `gh auth status` still shows the account, and push access was tested, not assumed.
- [ ] `gh pr checks` (or `gh run list`) was read after the last push and every check is green.
- [ ] `gh pr view N --json state,mergedAt` confirms the merge rather than assuming it.
- [ ] The issue is closed by the merged PR, or closed explicitly with a reason.
- [ ] No token, secret or credential appears in the diff you pushed.
- [ ] For a review: the verdict (`--approve` / `--request-changes` / `--comment`) matches what you actually found.
- [ ] For a release: the tag points at a green, intended commit.
