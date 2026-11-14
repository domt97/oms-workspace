---
name: add-migration
description: Steps to add a Flyway migration to an OMS service without downtime or broken data. Use when a change adds or alters a table, column, index or constraint.
---
# Add a database migration

Rules: `sa-data-persistence`; add `sa-concurrency-consistency` when the new column or constraint guards concurrent writes.

1. **Number.** Take the next `V<n>__<what>.sql` in `src/main/resources/db/migration` **on the latest `develop`**
   (`architecture/generated/<service>.md` shows the latest). Never edit a migration that has been merged.
2. **Expand, migrate, contract.** The old code must run against the new schema and the new code against the old data:
   add (nullable or with a default) → backfill → switch the code → only then drop or tighten, in a later migration.
3. **Existing rows.** Before adding a constraint, say what rows could violate it today and how the migration handles them.
4. **Index** every new query; name it in the plan. Say how big the table is and whether the statement locks it.
5. **One database per service** (system rule 1): no reference to another service's tables.
6. **Verify on real Postgres.** inventory-service: an integration test (`./gradlew integrationTest`, Testcontainers) for new
   native SQL, constraints and locks. stores-service has no such suite: run the migration against the local database and
   say so in the PR.
7. **Docs** (oms-workspace): the table in `architecture/domain-map.md`; re-run `scripts/extract_facts.py`.
