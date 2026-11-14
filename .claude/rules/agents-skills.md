---
paths:
  - ".claude/**"
---
# Writing skills and agents

- **A skill holds rules, not the state of the code.** `SKILL.md` = rules, checklists, patterns. How the OMS does it today
  (class names, config values, test counts, known gaps) goes in the skill's `references/current-state.md`, in
  `architecture/`, or in the owning repo's `CLAUDE.md` — never in `SKILL.md`.
- **One owner per rule.** A rule is written out in one `sa-*` skill; the others name it in one line (`sa-<name>` rule N).
  Owners: conditional UPDATE, guards, lock order → `sa-concurrency-consistency`; indexes, migrations, transaction
  boundary → `sa-data-persistence`; Kafka failure classes, DLT, commands → `sa-messaging-events`; timeouts, retries →
  `sa-resilience-observability`; queue DLQ, S3 key layout → `sa-aws-platform`; merchant scoping, secrets, PII →
  `sa-multitenancy-security`. Renumbering rules in a skill means fixing the references to them (`grep "rule [0-9]"`).
- **Sizes.** An `sa-*` `SKILL.md` stays under about 6 KB. A description is at most 250 characters, says what the skill is
  for and "Use when …", and contains no `: ` (it breaks the YAML). `CLAUDE.md` stays under about 11 KB: detail that only
  one workflow needs goes into that skill or a file it reads.
- **Agents preload only `sa-analysis-checklist`.** Its routing table (§9) says which other skill to open; a new `sa-*`
  skill needs a row there. Agents that should open skills need `Skill` in `tools`.
- **Models.** Repo experts run on `sonnet` (`effort: high` where the reasoning is subtle: stores, inventory). `oms-architect`
  and `plan-reviewer` inherit the session's model.
- **A skill with side effects** (commits, pushes, releases) sets `disable-model-invocation: true` so only the user starts it.
- `sa-*` skills are background knowledge: `user-invocable: false`.
- **Three kinds of skill.** `sa-*` say what to check. Workflow skills (`change-event`, `change-api`, `add-migration`,
  `add-aws-resource`, `new-service`, `docs-sync`) say in which order to do recurring cross-repo work and point at the
  `sa-*` rules instead of repeating them; keep each under about 3 KB. Commands (`feature-impact`, `ship`, `release-core`)
  run a whole piece of work.
