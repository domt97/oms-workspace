---
name: ship
description: Implement a feature or fix in ONE OMS service end to end — branch from develop, plan, code, test, review, update docs, commit, push and open a PR into develop. Use when the user asks to implement, build, fix or ship something in stores-service, inventory-service or another service repo.
---
# Ship a change to one service

Arguments (`$ARGUMENTS`): `<service> <feature|fix> <short-slug> [description]`
Example: `/ship inventory-service fix product-created-idempotent "make ProductCreated consumer idempotent"`

If an argument is missing, ask for it before doing anything. `<service>` must be a folder in `repos/`.
If the change spans more than one service, stop and suggest `/feature-impact` first, then one `/ship` per service.

Work in the service repo at `repos/<service>`. Never touch `master` or `develop` directly. Never merge.
Apply `sa-analysis-checklist` throughout; load other `sa-*` skills when the change touches their area
(messaging, data, concurrency, DDD, performance/scale, API, multi-tenancy/security, resilience/observability,
testing, AWS platform).

## 1. Branch from latest develop
```bash
cd repos/<service>
git status --porcelain          # must be empty — otherwise stop and ask the user what to do
git fetch origin
git checkout develop && git pull --ff-only origin develop
git checkout -b <feature|fix>/<short-slug>
```
Branch name: `feature/<slug>` or `fix/<slug>`, lowercase, words joined with `-`.
If the branch already exists, ask whether to continue on it instead of creating a new one.
**Report to the user before going on:** `Branch <name> created from develop @ <short-sha>`.
Do not start step 2 until the branch exists.

## 2. Understand, then plan — CHECKPOINT
1. Read `architecture/generated/<service>.md`, `repos/<service>/CLAUDE.md` and the relevant parts of
   `architecture/domain-map.md`, `integration.md`, `open-questions.md`.
2. Ask the domain expert agent (`store-expert`, `inventory-expert`, …) to analyse the change.
3. Draft the plan so that it passes `sa-analysis-checklist`:
   - root cause + real impact, with `file:line` evidence; runtime behaviour verified, not guessed;
   - business rules the change enforces: each must be ✅/🟢 in `architecture/business-rules.md`. If the code
     enforces (or the fix would enforce) a rule that is not written there, ask the user to confirm it, and
     record it in `business-rules.md` in this same piece of work (oms-workspace docs branch);
   - race table (who runs concurrently, what makes it safe) and idempotency on redelivery;
   - edge cases and one test each, including negative assertions;
   - files to add/change in order (domain → application → infrastructure → tests), migrations,
     contracts touched (mark BREAKING);
   - routing table: file → repo → branch → PR base; docs to update.
4. Send the draft to the **`plan-reviewer`** agent. Fix every "Must fix"; address or justify "Should fix".
5. Present the plan to the user **with the reviewer's verdict** and what you changed because of it.
6. **Wait for the user to approve the plan.** Adjust and re-present if asked.

## 3. Implement
Follow the "Adding a use case" checklist and the invariants in `repos/<service>/CLAUDE.md`.
Keep the change limited to the approved plan. Write the tests the plan lists.

## 4. Test — gate
```bash
./gradlew test
```
If tests fail, fix them. If you cannot make them pass, stop and report — do not commit.

## 5. Review
Ask the **`plan-reviewer`** agent to review the uncommitted diff of `repos/<service>` against the approved
plan: correctness, invariants, races, idempotency, missing tests. Fix real findings, then re-run `./gradlew test`.

## 6. Docs
- If the change added/changed a REST endpoint, event, consumer, table or aggregate:
  - update `repos/<service>/CLAUDE.md` in this same branch if layout, checklist or known gaps changed;
  - update `oms-workspace` docs (`architecture/domain-map.md`, `integration.md`, flows, `open-questions.md`)
    on a separate branch `docs/<short-slug>` from `master` of oms-workspace — never on master.
- Remove items from `open-questions.md` / "Known gaps" that this change fixes.

## 7. Commit and push — CHECKPOINT
**Branch gate (do this first, every time):**
```bash
git -C repos/<service> branch --show-current
```
It must be the working branch from step 1 (`feature/…`, `fix/…`, `docs/…`, `refactor/…`).
If it is `master` or `develop`, **stop**: do not commit there. Create the working branch from
`origin/develop` (`git switch -c <branch> origin/develop`), carry the changes over, and continue.
Same gate for oms-workspace: never commit on its `master`.

Show the user: `git status`, a one-paragraph summary, test result. **Ask before committing.**
Never commit IDE files (`.idea/`, `*.iml`) or `memory/`.
Then:
```bash
git add <only the files of this change>
git commit -m "<feat|fix>: <what changed>"
git push -u origin <branch>
```
Commit message: imperative, English, `feat:` / `fix:` / `test:` / `docs:` / `refactor:` prefix.
Same for the oms-workspace docs branch if there is one (commit there separately).

## 8. Pull request into develop — CHECKPOINT
**Ask before opening the PR.** Always set the base explicitly.
If `gh` is not authenticated, ask the user to run `gh auth login` (or give the compare URL below).
**Never ask the user to paste a token, password or `gh auth token` output into the chat.**
```bash
gh pr create --base develop --head <branch> --title "<feat|fix>: <what changed>" --body-file <file>
```
For the oms-workspace docs branch: `--base master`, and link the two PRs to each other.
If `gh` is unavailable, print the compare URL instead:
`https://github.com/domt97/<service>/compare/develop...<branch>?expand=1`

PR body template:
```markdown
## What
<1–3 sentences: what and why>

## Changes
- <domain / application / infrastructure / migration bullets>

## Contracts
- REST: <none | added/changed endpoints, BREAKING?>
- Events: <none | published/consumed changes>
- DB: <none | migration V<n>__...>

## Tests
- `./gradlew test`: passed
- <new tests>

## Docs
- <service CLAUDE.md / oms-workspace PR link / none>
```

## 9. Finish
Report the PR link(s) and anything left for the user. Do not merge, do not delete branches.
Leave the service repo on the new branch (`./scripts/sync-repos.sh` returns it to `develop` after the merge).

## 10. Lessons learned
Ask yourself: *where did the user (or plan-reviewer) have to correct me in this run?*
For each correction that reflects missing knowledge or a missing rule, propose — do not apply — an update:
the relevant `sa-*` skill, the service `CLAUDE.md`, or this skill. List them for the user; if they agree,
make them on a `docs/` or `chore/` branch of oms-workspace (PR into `master`) or in the service PR.
