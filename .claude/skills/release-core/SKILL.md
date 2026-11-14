---
name: release-core
description: Steps to release a new oms-core version and move a service onto it. Runs only when the user types /release-core.
argument-hint: <service that needs the new version>
disable-model-invocation: true
---
# Release oms-core and adopt it in a service

Detail and failure cases: `repos/oms-core/README.md` → *Releasing*; CI: `architecture/delivery.md`. Claude prepares; **the
user tags and merges** (`CLAUDE.md` → *Rules for Claude and all agents*).

1. Change oms-core and the service together locally (composite build: the service uses `../oms-core`).
2. In the oms-core PR, bump `version` in `gradle.properties` by semver: a removed or renamed public type, method or config
   key, or behaviour services must adapt to, is **MAJOR**. The `release-version` check says what merging will release.
   Say in the PR what merging publishes — a published version can never be changed.
3. Optional, for CI feedback before the merge: ask the user to tag the oms-core branch `vX.Y.Z-rc.N`. The service PR may
   pin that rc to get a green `test`; its `core-pin` check stays red, so an rc is never merged.
4. The user merges the oms-core PR. Wait for the **Publish** run to be green (it tags `vX.Y.Z`).
5. In the service PR set `coreVersion=X.Y.Z` (no `v`). `test` and `core-pin` must both be green before it is merged.
6. If Publish failed half-way, follow *A release that failed half-way* in the oms-core README. Never move or re-use a tag.
