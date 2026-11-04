# ADR 0005 — Services consume oms-core by pinned version from GitHub Packages

Status: Accepted (2026-11)

## Context
Every service built against oms-core **source**: locally through the composite build (`includeBuild('../oms-core')`),
in CI by checking out oms-core `master` (or a same-named branch) next to the service. A merge into oms-core reached every
service at its next build, so service builds were not reproducible and one oms-core change could turn every `develop`
red. A downstream job in oms-core's CI tested the services against each oms-core PR to catch that. The declared
`com.dotran.oms:oms-core:1.0.0` was never published and was always substituted.

## Decision
- oms-core is a versioned library with **continuous delivery**: the `version` in its `gradle.properties` is what `master`
  releases. On every push to `master`, `publish.yml` publishes that version to **GitHub Packages** if it has no tag yet
  (tests first; jar, sources, POM and Gradle module metadata with resolved versions) and tags `vX.Y.Z` with a GitHub
  Release. Releasing = bumping `version` in the PR; a merge without a bump releases nothing. A PR check reports what
  merging will release. `vX.Y.Z-rc.N` tags, created by the repository owner on a branch, publish pre-releases for CI
  feedback only (`release.yml`). Versions are immutable; `publish` refuses to run outside these workflows.
- Services pin `coreVersion` in `gradle.properties`. CI and releases resolve it from GitHub Packages (`exclusiveContent`:
  `com.dotran.oms` only from there, nothing else from there), reading with `GITHUB_TOKEN`. A `core-pin` check rejects
  `-rc` pins, so a pre-release is never merged.
- Locally, when `../oms-core` exists, the composite build is still used automatically (fast cross-repo work); the build
  log says so and `coreVersion` is ignored.
- oms-core's CI no longer tests the services (downstream job removed): a service is affected only when it bumps.
- Semantic versioning (oms-core `README.md`): MAJOR for any change services must adapt to (incl. Java, Spring Boot or
  BOM baselines), MINOR for additive API, PATCH for fixes.

## Alternatives considered
- **Keep source builds in CI with a downstream job:** simple, but no versions; every oms-core merge hits every service.
- **JitPack:** no token to read, but a third-party build service and a slow first build of each version.
- **CI checks out oms-core at tag `v${coreVersion}`:** tokenless and pinned; kept as the fallback if `GITHUB_TOKEN` cannot
  read the package from another repository (the service CI's "no ../oms-core" guard would then change).
- **AWS CodeArtifact:** the equivalent on AWS; only the repository URL and credentials in Gradle would change.

## Consequences
- Service builds are reproducible; oms-core can change without breaking services that have not bumped.
- A cross-repo change takes more steps: local composite build → (optional rc) → merge oms-core with a version bump
  (auto-published) → `coreVersion` bump in the service.
- Publishing on merge is safe because services pin: a new oms-core version changes nothing until a service bumps.
- Locally a service can pass against newer oms-core source than the one CI pins (accepted for speed; the build log shows
  it). To test exactly what CI tests, build without the sibling (needs a `read:packages` token).
- Breaking oms-core changes are found when a service bumps, not when oms-core merges; semver discipline and an optional
  API-compatibility check (open question) replace the downstream job.
- GitHub Packages Maven always needs authentication, even for public packages: CI uses `GITHUB_TOKEN`; a machine without
  `../oms-core` needs a classic token with `read:packages`.
- Production: the oms-core jar is packed into each service's boot jar at build time; nothing is downloaded at runtime.
