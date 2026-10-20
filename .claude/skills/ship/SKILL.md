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

## 2. Understand, then plan — CHECKPOINT
1. Read `architecture/generated/<service>.md`, `repos/<service>/CLAUDE.md` and the relevant parts of
   `architecture/domain-map.md`, `integration.md`, `open-questions.md`.
2. Ask the domain expert agent (`store-expert`, `inventory-expert`, …) to analyse the change.
3. Present a short plan to the user: files to add/change (domain → application → infrastructure → tests),
   migrations, events/APIs touched (mark BREAKING), docs to update.
4. **Wait for the user to approve the plan.** Adjust and re-present if asked.

## 3. Implement
Follow the "Adding a use case" checklist and the invariants in `repos/<service>/CLAUDE.md`.
Keep the change limited to the approved plan. Write the tests the plan lists.

## 4. Test — gate
```bash
./gradlew test
```
If tests fail, fix them. If you cannot make them pass, stop and report — do not commit.

## 5. Review
Ask the same expert agent to review the uncommitted diff of `repos/<service>`:
correctness, invariants, idempotency, missing tests. Fix real findings, then re-run `./gradlew test`.

## 6. Docs
- If the change added/changed a REST endpoint, event, consumer, table or aggregate:
  - update `repos/<service>/CLAUDE.md` in this same branch if layout, checklist or known gaps changed;
  - update `oms-workspace` docs (`architecture/domain-map.md`, `integration.md`, flows, `open-questions.md`)
    on a separate branch `docs/<short-slug>` from `master` of oms-workspace — never on master.
- Remove items from `open-questions.md` / "Known gaps" that this change fixes.

## 7. Commit and push — CHECKPOINT
Show the user: `git status`, a one-paragraph summary, test result. **Ask before committing.**
Then:
```bash
git add <only the files of this change>
git commit -m "<feat|fix>: <what changed>"
git push -u origin <branch>
```
Commit message: imperative, English, `feat:` / `fix:` / `test:` / `docs:` / `refactor:` prefix.
Same for the oms-workspace docs branch if there is one (commit there separately).

## 8. Pull request into develop — CHECKPOINT
**Ask before opening the PR.** Always set the base explicitly:
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
Leave the service repo on the new branch.
