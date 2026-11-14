# Delivery: branches, build, CI and releases

How code gets from a branch to a release in each repo. The rules Claude must never break are in `CLAUDE.md` →
*Rules for Claude and all agents*; this file is the detail behind them. Read it when shipping (`/ship`), fixing CI or
releasing oms-core.

## Branch model

- Service repos (`stores-service`, `inventory-service`) and `oms-web`: `master` is the release branch; **`develop`** is the
  integration branch and the GitHub default branch (new PRs and clones target `develop`).
  Branch features/fixes **from `develop`** and open PRs **into `develop`**; `master` only receives `develop` via release PRs.
- `oms-workspace`: `master` is protected. Every change (docs, agents, skills, scripts, workflows)
  goes on a short-lived branch from `master` — `docs/...`, `chore/...`, `ci/...`, `feat/...` —
  and is merged **through a PR into `master`** after the user reviews it. The only automated PR is
  `bot/refresh-facts` (GitHub Actions).
- `oms-core`, `development`: `master` only. oms-core is released continuously: the `version` in its `gradle.properties`
  is published to GitHub Packages and tagged `vX.Y.Z` by `publish.yml` when it reaches `master` (bump it in the PR to
  release); pre-releases are `vX.Y.Z-rc.N` tags on a branch (`release.yml`). See oms-core `README.md`.

## Build & run

- Java 17, Spring Boot 3.2.3, Gradle. Locally each service uses `../oms-core` as a composite build when it exists (`repos/`
  keeps the repos as siblings; the build log says so) and then ignores `coreVersion`. CI and releases have no sibling: they
  download the pinned `coreVersion` from GitHub Packages (ADR 0005). Building a service without `../oms-core` needs
  `gpr.user`/`gpr.key` (classic token, `read:packages`) in `~/.gradle/gradle.properties`.
- Infra: `cd repos/development/docker && docker compose up -d`, then Terraform in `repos/development/docker/infra/local`.
- Service: `./gradlew bootRun --args='--spring.profiles.active=localdev'`. Swagger at `/swagger-ui.html`.
- Web: Node 20.19+ or 22.12+; in `repos/oms-web` run `npm install`, then `npm run dev` → http://localhost:5173
  (Seller Centre `/seller`). It proxies to the services on 8048 / 8058. `npm run check` = typecheck + layer rule + tests.

## CI (GitHub Actions, `.github/workflows/ci.yml` in each code repo)

- **stores-service, inventory-service:** `./gradlew test` on every PR and push to `develop`/`master`, against the **pinned
  `coreVersion`** from GitHub Packages (no oms-core checkout; `GITHUB_TOKEN` with `packages: read`). Job **`core-pin`** fails
  while `coreVersion` is a pre-release (`-rc.N`). Test reports are uploaded as an artifact on failure.
- **oms-core:** its own tests plus a dry run of the publication files (POM, Gradle module metadata); on PRs, `release-version`
  says what merging will release. **CD:** `publish.yml` on every push to `master` publishes `gradle.properties` `version`
  if it is new (tests first) and tags `vX.Y.Z`; `release.yml` publishes rc tags. Versions are immutable.
- **oms-web:** `npm run build` (typecheck, layer rule, tests, Vite build) on Node 22.
- **A service picks up an oms-core change only when it bumps `coreVersion`.** Cross-repo change:
  1. change oms-core and the service together locally (composite build);
  2. optional, for CI feedback before oms-core is merged: the user tags the oms-core branch `vX.Y.Z-rc.N`, the service PR pins
     it (`test` green, `core-pin` red: not mergeable);
  3. merge oms-core with `version=X.Y.Z` bumped; wait for the **Publish** run (it tags `vX.Y.Z`);
  4. the service PR sets `coreVersion=X.Y.Z` (no `v`; `core-pin` green) and is merged.
  A service PR whose pinned version is not published yet has a red `test`: never merge it before the Publish run is green.
  Breaking change in oms-core = MAJOR version (oms-core `README.md`).
- **inventory-service** also has a job **`Integration tests`** (`./gradlew integrationTest`: Testcontainers Postgres on the
  runner's Docker; native SQL, constraints, locks, races). It is not a required check yet. Everything else is unit tests
  only (no Docker): Debezium and Kafka behaviour, and stores-service SQL, stay manual checks.
- **oms-workspace:** `Script tests` runs the unit tests (`python3 -m unittest discover -s scripts/tests`: the facts
  extractor, the git guard hook, the lint) and then `python3 scripts/lint_workspace.py` on PRs that touch `scripts/`,
  `.claude/`, `architecture/`, `CLAUDE.md` or `README.md`. The lint fails on a reference to a rule, skill, file or open
  question that does not exist, on a skill or agent that breaks `.claude/rules/agents-skills.md`, and on history notes
  (PR numbers, branch names) in the docs that describe the present. It is path-filtered, so do not make it a required
  check as it stands.
- Branch protection (after the first green runs): required checks `Unit tests` and `core-pin` on service `develop`/`master`,
  `oms-core unit tests` and `release-version` on oms-core `master`, `Check and build` on oms-web.
