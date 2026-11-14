---
paths:
  - "architecture/**"
---
# Writing the architecture docs

- **Describe the system as it is now.** No PR numbers, dates of change, "BREAKING (date)" or "live once merged" notes: git
  and the ADRs keep the history.
- **One fact, one place.** Structural facts (endpoints, events, tables, listeners) come from `architecture/generated/`.
  Facts that cross a repo boundary live here in `architecture/`. Facts about the inside of one repo live in that repo's
  `CLAUDE.md` or docs. Link to a fact; do not copy it.
- **Never edit `architecture/generated/` by hand.** `scripts/extract_facts.py` writes it. A "Contract check failed" or
  "No contract schema" note in it means the code, the contract or the script needs fixing first.
- **Same-PR rule.** A change that adds or changes a REST endpoint, event, table or aggregate updates `domain-map.md` and
  `integration.md` in the same piece of work.
- **A new event** gets a schema in `contracts/events/` whose `description` says "Published by <service>" (the contract
  check reads that line) and a row in `integration.md`.
- **Business rules** are decided by the user only. Do not add a rule or change a status (✅ 🟢 🟡 ❓) on your own.
- **`open-questions.md` holds open items only.** When one is resolved, delete it.
